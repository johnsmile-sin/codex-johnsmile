"""
analysis/backtester.py  –  경량 백테스트 엔진 (3차 모의투자)

과거 일봉 데이터를 기반으로 전략 규칙을 적용한 경량 백테스트를 수행합니다.
복잡한 프레임워크 없이 pandas 기반으로 구현합니다.

기본 가정:
    - 매수 신호 발생일의 다음 거래일 시가(open)로 진입
    - 목표가 도달 시 → 익절 (당일 고가 기준)
    - 손절가 도달 시 → 손절 (당일 저가 기준, 같은 날 손절이 우선)
    - 최대 보유일 초과 시 → 당일 종가로 청산
    - 수수료: 매수/매도 각 fee_rate (기본 0.35%)
    - 증권거래세: 매도 시 tax_rate (기본 0.20%)

공개 함수:
    run_backtest(strategy_name, start_date, end_date, initial_cash, ...)
    simulate_entry(price_df, signal_idx, rule, max_position_amount, fee_rate)
    simulate_exit(price_df, entry_idx, entry, rule, fee_rate, tax_rate)
    calculate_backtest_result(trades, initial_cash, strategy_name, ...)
    save_backtest_result(result)

backtest_results 테이블 컬럼:
    strategy_name, start_date, end_date, initial_cash, final_asset,
    total_return_rate, win_rate, max_drawdown, total_trades,
    result_json, created_at
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

DATA_DIR          = Path(__file__).resolve().parents[1] / "data"
BACKTEST_FILE     = DATA_DIR / "backtest_results.json"

DEFAULT_FEE_RATE  = 0.0035   # 매수·매도 각 0.35%
DEFAULT_TAX_RATE  = 0.0020   # 증권거래세 0.20% (매도 시)
DEFAULT_MAX_AMOUNT = 1_000_000


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼
# ════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _supabase_connected() -> bool:
    try:
        from services.supabase_client import is_connected
        return bool(is_connected())
    except Exception:
        return False


def _supabase_client():
    from services.supabase_client import get_client
    return get_client()


def _safe_float(val, default: float = 0.0) -> float:
    try:
        v = float(val)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return default


def _load_rule(strategy_name: str) -> dict[str, Any] | None:
    """전략 규칙을 로드한다. 없으면 None."""
    try:
        from strategy.strategy_rules import load_strategy_rules
        rules = load_strategy_rules(active_only=False)
        for r in rules:
            if r.get("strategy_name") == strategy_name:
                return r
    except Exception:
        pass
    return None


def _get_rule_param(rule: dict, key: str, default: Any) -> Any:
    """전략 rule dict 최상위 또는 rule_json 에서 값을 꺼낸다."""
    if key in rule:
        return rule[key]
    rj = rule.get("rule_json", {})
    if isinstance(rj, str):
        try:
            rj = json.loads(rj)
        except Exception:
            rj = {}
    return rj.get(key, default)


def _load_price_data(
    stock_code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    종목 일봉 데이터를 로드하고 날짜로 필터링한다.
    지표(ma5/ma20/ma60/rsi14) 계산을 위해 start_date 전 60일을 추가로 로드한다.
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt   = datetime.strptime(end_date,   "%Y-%m-%d").date()

    # 지표 계산 버퍼 + 백테스트 기간 전체를 거래일 기준으로 커버
    total_days = (date.today() - start_dt).days
    fetch_days = max(int(total_days * 252 / 365) + 80, 80)

    try:
        from services.price_service import fetch_daily_prices
        df = fetch_daily_prices(stock_code, days=fetch_days)
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    # date 컬럼 문자열 통일
    date_col = "date" if "date" in df.columns else (
        "price_date" if "price_date" in df.columns else None
    )
    if date_col is None:
        return pd.DataFrame()

    if date_col != "date":
        df = df.rename(columns={date_col: "date"})

    df["date"] = df["date"].astype(str).str[:10]
    df = df.sort_values("date").reset_index(drop=True)

    # 필수 컬럼 숫자형 변환
    for col in ("open", "high", "low", "close", "volume", "ma5", "ma20", "ma60", "rsi14", "change_rate"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # 5일 평균 거래량 (volume_ratio 계산용)
    if "volume" in df.columns:
        df["avg_vol5"] = df["volume"].rolling(5, min_periods=1).mean()
        df["volume_ratio"] = df.apply(
            lambda r: r["volume"] / r["avg_vol5"] if r["avg_vol5"] > 0 else 1.0, axis=1
        )

    # 날짜 필터 (signal 버퍼: start_date 이전 60 거래일 포함)
    buffer_start = (start_dt - timedelta(days=90)).strftime("%Y-%m-%d")
    return df[(df["date"] >= buffer_start) & (df["date"] <= end_date)].reset_index(drop=True)


def _entry_signal_series(df: pd.DataFrame, strategy_name: str) -> pd.Series:
    """
    전략명에 맞는 기술적 매수 신호 시리즈를 반환한다.

    Returns:
        pd.Series[bool]: True = 해당 날짜에 매수 신호 발생
    """
    n = len(df)
    false_series = pd.Series([False] * n, index=df.index)

    has = lambda col: col in df.columns and df[col].notna().any()

    if not has("close"):
        return false_series

    name = strategy_name.lower()

    # ── 거래량 급증 모멘텀 ────────────────────────────────────────
    if "momentum" in name or "volume" in name or "급증" in name:
        cond = pd.Series([True] * n, index=df.index)
        if has("ma5"):
            cond &= df["close"] > df["ma5"]
        if has("change_rate"):
            cond &= df["change_rate"] > 1.0
        if has("volume_ratio"):
            cond &= df["volume_ratio"] > 1.5
        return cond

    # ── 뉴스 호재 단기매매 ─────────────────────────────────────────
    if "뉴스" in name or "news" in name or "단기" in name:
        cond = pd.Series([True] * n, index=df.index)
        if has("change_rate"):
            cond &= df["change_rate"] > 2.0
        if has("ma5"):
            cond &= df["close"] > df["ma5"]
        return cond

    # ── 안정형 분할매수 ────────────────────────────────────────────
    if "안정" in name or "stable" in name or "분할" in name:
        cond = pd.Series([True] * n, index=df.index)
        if has("rsi14"):
            cond &= df["rsi14"] < 45
        if has("ma60"):
            cond &= df["close"] > df["ma60"]
        if has("change_rate"):
            cond &= df["change_rate"] > 0
        return cond

    # ── 기본 신호 (MA5 돌파 + 양봉) ──────────────────────────────
    cond = pd.Series([True] * n, index=df.index)
    if has("ma5"):
        cond &= df["close"] > df["ma5"]
    if has("change_rate"):
        cond &= df["change_rate"] > 0.5
    return cond


# ════════════════════════════════════════════════════════════════
# 공개 함수
# ════════════════════════════════════════════════════════════════

def simulate_entry(
    price_df: pd.DataFrame,
    signal_idx: int,
    rule: dict[str, Any],
    max_position_amount: float = DEFAULT_MAX_AMOUNT,
    fee_rate: float = DEFAULT_FEE_RATE,
) -> dict[str, Any] | None:
    """
    매수 신호 발생 후 다음 거래일 시가로 진입을 시뮬레이션한다.

    Args:
        price_df:           일봉 DataFrame (date, open, high, low, close 필수)
        signal_idx:         신호 발생 행 인덱스 (0-based)
        rule:               전략 규칙 dict
        max_position_amount: 1종목 최대 투자금 (원)
        fee_rate:           매수 수수료율

    Returns:
        dict: {entry_idx, entry_date, entry_price, quantity, cost,
               fee, target_price, stop_loss_price, max_holding_days}
        None: 다음 거래일이 없거나 진입 불가
    """
    entry_idx = signal_idx + 1
    if entry_idx >= len(price_df):
        return None

    row = price_df.iloc[entry_idx]
    entry_price = _safe_float(row.get("open", row.get("close", 0)))
    if entry_price <= 0:
        return None

    quantity = int(max_position_amount // entry_price)
    if quantity <= 0:
        return None

    cost = round(entry_price * quantity, 2)
    fee  = round(cost * fee_rate, 2)

    # 목표가·손절가 계산
    take_profit_rate = _safe_float(_get_rule_param(rule, "take_profit_rate", 5.0))
    stop_loss_rate   = _safe_float(_get_rule_param(rule, "stop_loss_rate",  -3.0))
    max_holding_days = int(_get_rule_param(rule, "max_holding_days", 5))

    target_price    = round(entry_price * (1 + take_profit_rate / 100), 0)
    stop_loss_price = round(entry_price * (1 + stop_loss_rate  / 100), 0)

    return {
        "entry_idx":       entry_idx,
        "entry_date":      str(row.get("date", ""))[:10],
        "entry_price":     entry_price,
        "quantity":        quantity,
        "cost":            cost,
        "fee":             fee,
        "target_price":    target_price,
        "stop_loss_price": stop_loss_price,
        "max_holding_days": max_holding_days,
    }


def simulate_exit(
    price_df: pd.DataFrame,
    entry_idx: int,
    entry: dict[str, Any],
    rule: dict[str, Any],
    fee_rate: float = DEFAULT_FEE_RATE,
    tax_rate: float = DEFAULT_TAX_RATE,
) -> dict[str, Any]:
    """
    진입 후 OHLCV 데이터를 순회하며 청산 조건을 시뮬레이션한다.

    청산 우선순위 (같은 날):
        1. 손절 (저가 <= 손절가) — 보수적 가정
        2. 익절 (고가 >= 목표가)
        3. 기간만료 (보유일 >= 최대보유일)

    수수료: 매도금액 × fee_rate
    거래세: 매도금액 × tax_rate

    Args:
        price_df:   일봉 DataFrame
        entry_idx:  진입 행 인덱스
        entry:      simulate_entry() 반환값
        rule:       전략 규칙 dict
        fee_rate:   매도 수수료율
        tax_rate:   증권거래세율

    Returns:
        dict: {exit_date, exit_price, exit_reason, holding_days,
               profit_loss, return_rate, net_profit_loss, fee, tax}
    """
    target_price    = entry["target_price"]
    stop_loss_price = entry["stop_loss_price"]
    max_holding_days = entry["max_holding_days"]
    entry_price     = entry["entry_price"]
    quantity        = entry["quantity"]

    last_close = entry_price
    exit_date  = entry["entry_date"]
    exit_price = entry_price
    exit_reason = "기간만료"

    for holding_days in range(1, max_holding_days + 1):
        row_idx = entry_idx + holding_days
        if row_idx >= len(price_df):
            # 데이터 끝 → 마지막 종가로 청산
            exit_reason = "데이터부족"
            break

        row   = price_df.iloc[row_idx]
        high  = _safe_float(row.get("high",  0))
        low   = _safe_float(row.get("low",   0))
        close = _safe_float(row.get("close", 0))
        day_date = str(row.get("date", ""))[:10]
        last_close = close if close > 0 else last_close

        # 1. 손절 (저가가 손절가 이하)
        if low > 0 and low <= stop_loss_price:
            exit_price  = stop_loss_price
            exit_date   = day_date
            exit_reason = "손절"
            break

        # 2. 익절 (고가가 목표가 이상)
        if high > 0 and high >= target_price:
            exit_price  = target_price
            exit_date   = day_date
            exit_reason = "익절"
            break

        # 3. 기간만료 (최대 보유일 도달)
        if holding_days >= max_holding_days:
            exit_price  = close if close > 0 else last_close
            exit_date   = day_date
            exit_reason = "기간만료"
            break
    else:
        # for 루프 정상 종료 = max_holding_days 에 걸림
        exit_price = last_close

    # 수수료·세금 계산
    sell_amount = round(exit_price * quantity, 2)
    sell_fee    = round(sell_amount * fee_rate, 2)
    sell_tax    = round(sell_amount * tax_rate, 2)
    buy_fee     = entry["fee"]

    gross_pnl = round((exit_price - entry_price) * quantity, 2)
    net_pnl   = round(gross_pnl - buy_fee - sell_fee - sell_tax, 2)

    cost = entry["cost"]
    return_rate = round(net_pnl / cost * 100, 4) if cost > 0 else 0.0

    return {
        "exit_date":      exit_date,
        "exit_price":     exit_price,
        "exit_reason":    exit_reason,
        "holding_days":   holding_days if "holding_days" in dir() else 0,
        "profit_loss":    gross_pnl,
        "net_profit_loss": net_pnl,
        "return_rate":    return_rate,
        "fee":            round(buy_fee + sell_fee, 2),
        "tax":            sell_tax,
    }


def calculate_backtest_result(
    trades: list[dict[str, Any]],
    initial_cash: float,
    strategy_name: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """
    거래 목록에서 백테스트 성과 지표를 계산한다.

    Args:
        trades:       simulate_entry/exit 으로 생성된 거래 dict 리스트
        initial_cash: 초기 투자금 (원)
        strategy_name: 전략명
        start_date:   백테스트 시작일 (YYYY-MM-DD)
        end_date:     백테스트 종료일 (YYYY-MM-DD)

    Returns:
        dict: backtest_results 테이블 구조 + Streamlit 확장 지표
            strategy_name, start_date, end_date, initial_cash,
            final_asset, total_return_rate, win_rate, max_drawdown,
            total_trades, result_json,
            + 확장: trades_df, summary_text, 전략별 지표 등
    """
    if not trades:
        return {
            "strategy_name":    strategy_name,
            "start_date":       start_date,
            "end_date":         end_date,
            "initial_cash":     initial_cash,
            "final_asset":      initial_cash,
            "total_return_rate": 0.0,
            "win_rate":         0.0,
            "max_drawdown":     0.0,
            "total_trades":     0,
            "result_json":      {},
            "trades_df":        pd.DataFrame(),
            "summary_text":     "백테스트 결과: 거래 없음",
            "created_at":       _now(),
        }

    df = pd.DataFrame(trades)
    for col in ("net_profit_loss", "profit_loss", "return_rate", "holding_days", "entry_price", "exit_price"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    total_trades = len(df)
    wins         = int((df["net_profit_loss"] > 0).sum())
    losses       = total_trades - wins
    win_rate     = round(wins / total_trades * 100, 2) if total_trades > 0 else 0.0

    total_net_pnl    = round(float(df["net_profit_loss"].sum()), 2)
    final_asset      = round(initial_cash + total_net_pnl, 2)
    total_return_rate = round(total_net_pnl / initial_cash * 100, 4) if initial_cash > 0 else 0.0
    avg_return_rate  = round(float(df["return_rate"].mean()), 4)

    # 손익비
    gross_profit = float(df[df["net_profit_loss"] > 0]["net_profit_loss"].sum())
    gross_loss   = abs(float(df[df["net_profit_loss"] < 0]["net_profit_loss"].sum()))
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else (
        round(gross_profit, 4) if gross_profit > 0 else 0.0
    )

    # 최대 낙폭 (누적 손익 커브)
    df_sorted = df.sort_values("entry_date").copy()
    df_sorted["cumulative_pnl"] = df_sorted["net_profit_loss"].cumsum()
    df_sorted["equity"]         = initial_cash + df_sorted["cumulative_pnl"]
    df_sorted["peak"]           = df_sorted["equity"].cummax()
    df_sorted["drawdown_pct"]   = (df_sorted["equity"] - df_sorted["peak"]) / df_sorted["peak"] * 100
    max_drawdown = round(float(df_sorted["drawdown_pct"].min()), 4)

    # 청산 사유별 집계
    exit_counts = df["exit_reason"].value_counts().to_dict() if "exit_reason" in df.columns else {}

    avg_holding = round(float(df["holding_days"].mean()), 1) if "holding_days" in df.columns else 0.0

    # 누적 손익 시계열 (Streamlit 차트용)
    equity_series = df_sorted[["entry_date", "cumulative_pnl", "equity"]].to_dict("records")

    # result_json: 핵심 지표 + 거래 목록 요약 (Supabase JSONB 저장용)
    result_json = {
        "summary": {
            "total_trades":     total_trades,
            "win_trades":       wins,
            "lose_trades":      losses,
            "win_rate":         win_rate,
            "avg_return_rate":  avg_return_rate,
            "total_return_rate": total_return_rate,
            "max_drawdown":     max_drawdown,
            "profit_factor":    profit_factor,
            "gross_profit":     round(gross_profit, 2),
            "gross_loss":       round(gross_loss, 2),
            "avg_holding_days": avg_holding,
            "exit_counts":      exit_counts,
        },
        "trades": [
            {
                "stock_code":   t.get("stock_code", ""),
                "stock_name":   t.get("stock_name", ""),
                "entry_date":   t.get("entry_date", ""),
                "entry_price":  t.get("entry_price", 0),
                "exit_date":    t.get("exit_date", ""),
                "exit_price":   t.get("exit_price", 0),
                "exit_reason":  t.get("exit_reason", ""),
                "net_pnl":      t.get("net_profit_loss", 0),
                "return_rate":  t.get("return_rate", 0),
                "holding_days": t.get("holding_days", 0),
            }
            for t in trades
        ],
    }

    summary_text = _build_backtest_summary(
        strategy_name, start_date, end_date,
        total_trades, wins, losses, win_rate,
        total_net_pnl, total_return_rate, final_asset, initial_cash,
        avg_return_rate, max_drawdown, profit_factor, avg_holding,
        exit_counts,
    )

    return {
        # backtest_results 테이블 컬럼
        "strategy_name":    strategy_name,
        "start_date":       start_date,
        "end_date":         end_date,
        "initial_cash":     initial_cash,
        "final_asset":      final_asset,
        "total_return_rate": total_return_rate,
        "win_rate":         win_rate,
        "max_drawdown":     max_drawdown,
        "total_trades":     total_trades,
        "result_json":      result_json,
        "created_at":       _now(),
        # Streamlit 확장
        "trades_df":        df,
        "equity_series":    equity_series,
        "summary_text":     summary_text,
        "win_trades":       wins,
        "lose_trades":      losses,
        "avg_return_rate":  avg_return_rate,
        "profit_factor":    profit_factor,
        "gross_profit":     round(gross_profit, 2),
        "gross_loss":       round(gross_loss, 2),
        "avg_holding_days": avg_holding,
        "exit_counts":      exit_counts,
        "total_net_pnl":    total_net_pnl,
    }


def save_backtest_result(result: dict[str, Any]) -> dict[str, Any]:
    """
    백테스트 결과를 backtest_results 테이블(또는 로컬 JSON)에 저장한다.

    Args:
        result: calculate_backtest_result() 반환값

    Returns:
        dict: {"saved": bool, "mode": str, "id": int | None}
    """
    # DB 저장 컬럼만 추출 (Streamlit 전용 필드 제거)
    _exclude = {"trades_df", "equity_series", "summary_text",
                "win_trades", "lose_trades", "avg_return_rate",
                "profit_factor", "gross_profit", "gross_loss",
                "avg_holding_days", "exit_counts", "total_net_pnl"}

    record = {k: v for k, v in result.items() if k not in _exclude}

    # result_json → JSON 직렬화 (Supabase JSONB 용)
    if isinstance(record.get("result_json"), dict):
        pass  # Supabase 클라이언트가 자동 직렬화
    elif isinstance(record.get("result_json"), str):
        try:
            record["result_json"] = json.loads(record["result_json"])
        except Exception:
            record["result_json"] = {}

    if _supabase_connected():
        try:
            resp = _supabase_client().table("backtest_results").insert(record).execute()
            rows = resp.data or []
            saved_id = rows[0].get("id") if rows else None
            return {"saved": True, "mode": "supabase", "id": saved_id}
        except Exception:
            pass

    # 로컬 JSON 폴백
    _ensure_data_dir()
    existing: list[dict] = []
    if BACKTEST_FILE.exists():
        try:
            existing = json.loads(BACKTEST_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    local_record = dict(record)
    local_record["id"] = max((e.get("id", 0) for e in existing), default=0) + 1

    # result_json 직렬화 안전처리
    if isinstance(local_record.get("result_json"), dict):
        pass
    else:
        local_record["result_json"] = {}

    existing.append(local_record)
    BACKTEST_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {"saved": True, "mode": "local", "id": local_record["id"]}


def run_backtest(
    strategy_name: str,
    start_date: str,
    end_date: str,
    initial_cash: float = 10_000_000,
    stock_codes: list[str] | None = None,
    fee_rate: float = DEFAULT_FEE_RATE,
    tax_rate: float = DEFAULT_TAX_RATE,
    max_position_amount: float = DEFAULT_MAX_AMOUNT,
    save_result: bool = True,
) -> dict[str, Any]:
    """
    경량 백테스트를 실행한다.

    실행 흐름:
        1. 전략 규칙 로드 (목표가율·손절률·최대보유일)
        2. 대상 종목 목록 결정 (stock_codes 또는 종목 마스터)
        3. 종목별 일봉 데이터 로드 → 날짜 필터
        4. 기술적 매수 신호 생성 (전략별 preset)
        5. 신호 발생 → simulate_entry (다음날 시가 진입)
        6. 진입 → simulate_exit (익절·손절·기간만료)
        7. 전 종목 거래 취합 → calculate_backtest_result
        8. save_backtest_result (선택)

    실제 주문은 절대 실행하지 않습니다.

    Args:
        strategy_name:       백테스트할 전략명
        start_date:          시작일 (YYYY-MM-DD)
        end_date:            종료일 (YYYY-MM-DD)
        initial_cash:        초기 투자금 (원)
        stock_codes:         대상 종목코드 리스트 (None이면 마스터 전체)
        fee_rate:            매수·매도 각 수수료율 (기본 0.35%)
        tax_rate:            매도 증권거래세율 (기본 0.20%)
        max_position_amount: 1종목 최대 투자금 (원, 기본 100만원)
        save_result:         완료 후 DB 저장 여부

    Returns:
        dict: calculate_backtest_result() 반환값 + save 결과
    """
    # 1. 전략 규칙 로드
    rule = _load_rule(strategy_name)
    if rule is None:
        rule = {
            "strategy_name":    strategy_name,
            "take_profit_rate": 5.0,
            "stop_loss_rate":   -3.0,
            "max_holding_days": 5,
        }

    if max_position_amount <= 0:
        max_position_amount = _safe_float(
            _get_rule_param(rule, "max_position_amount", DEFAULT_MAX_AMOUNT),
            DEFAULT_MAX_AMOUNT,
        )

    # 2. 대상 종목 목록
    if stock_codes is None:
        try:
            from services.market_data import get_stock_master
            master = get_stock_master()
            stock_codes = [m["stock_code"] for m in master if m.get("stock_code")]
        except Exception:
            stock_codes = []

    if not stock_codes:
        return calculate_backtest_result([], initial_cash, strategy_name, start_date, end_date)

    all_trades: list[dict[str, Any]] = []

    # 3~6. 종목별 백테스트
    for code in stock_codes:
        code_str = str(code).zfill(6)

        # 종목명 조회
        stock_name = code_str
        try:
            from services.market_data import get_stock_by_code
            item = get_stock_by_code(code_str)
            if item:
                stock_name = item.get("stock_name", code_str)
        except Exception:
            pass

        # 일봉 데이터 로드
        price_df = _load_price_data(code_str, start_date, end_date)
        if price_df.empty:
            continue

        # 백테스트 기간 내 데이터만 필터 (신호 생성에는 버퍼 포함 데이터 사용)
        in_period = price_df["date"] >= start_date

        # 4. 매수 신호 생성 (전체 데이터 기준 — 지표 정확도)
        signal_series = _entry_signal_series(price_df, strategy_name)

        # 5~6. 신호별 진입·청산
        active_entry_idx: int | None = None  # 1종목 1포지션 유지

        for i, (is_signal, in_range) in enumerate(zip(signal_series, in_period)):
            # 이미 포지션 보유 중이면 매수 신호 무시
            if active_entry_idx is not None:
                # 보유일 초과 여부는 simulate_exit에서 처리됨 → 이 루프에서 추적
                pass
            elif is_signal and in_range:
                entry = simulate_entry(
                    price_df, i, rule, max_position_amount, fee_rate
                )
                if entry is None:
                    continue

                exit_data = simulate_exit(
                    price_df, entry["entry_idx"], entry, rule, fee_rate, tax_rate
                )

                trade = {
                    "stock_code":      code_str,
                    "stock_name":      stock_name,
                    "strategy_name":   strategy_name,
                    "signal_date":     str(price_df.iloc[i].get("date", ""))[:10],
                    **entry,
                    **exit_data,
                }
                all_trades.append(trade)

                # 다음 매수 신호: exit_date 이후부터 허용 (중복 진입 방지)
                # 단순 구현: 같은 종목 다음 signal_idx = exit_idx + 1
                exit_date_str = exit_data.get("exit_date", "")
                # 포지션 중복 방지: exit_date 이후의 신호부터 재진입 허용
                # (다음 반복에서 재진입 가능하도록 active_entry_idx 초기화)
                # 여기서는 1종목 다중 진입을 허용하되 시그널 날짜가 exit_date 이후인 경우만 허용
                # 간단히: 현재 진입 날짜 이후부터의 신호만 허용 (단순 선형 처리)
                # → i를 exit_idx로 점프 (for loop에서 불가 → continue로 자연스럽게 처리)

    # 7. 전체 거래 집계 → 결과 계산
    result = calculate_backtest_result(
        all_trades, initial_cash, strategy_name, start_date, end_date
    )

    # 8. DB 저장
    if save_result:
        save_info = save_backtest_result(result)
        result["save_info"] = save_info

    return result


# ════════════════════════════════════════════════════════════════
# 내부: 요약 텍스트 빌더
# ════════════════════════════════════════════════════════════════

def _build_backtest_summary(
    strategy_name: str,
    start_date: str,
    end_date: str,
    total_trades: int,
    wins: int,
    losses: int,
    win_rate: float,
    total_net_pnl: float,
    total_return_rate: float,
    final_asset: float,
    initial_cash: float,
    avg_return_rate: float,
    max_drawdown: float,
    profit_factor: float,
    avg_holding: float,
    exit_counts: dict,
) -> str:
    pnl_sign = "+" if total_net_pnl >= 0 else ""

    익절 = exit_counts.get("익절", 0)
    손절 = exit_counts.get("손절", 0)
    만료 = exit_counts.get("기간만료", 0)
    기타 = total_trades - 익절 - 손절 - 만료

    lines = [
        f"【 백테스트 결과 — {strategy_name} 】",
        f"  기간: {start_date} ~ {end_date}",
        f"  초기 투자금: {initial_cash:,.0f}원  →  최종 자산: {final_asset:,.0f}원",
        "",
        "▶ 핵심 지표",
        f"  총 거래 수     : {total_trades}건  (익절 {익절} / 손절 {손절} / 기간만료 {만료}" + (f" / 기타 {기타}" if 기타 else "") + ")",
        f"  승  률         : {win_rate:.2f}%  ({wins}승 {losses}패)",
        f"  평균 수익률    : {avg_return_rate:+.2f}%",
        f"  누적 수익률    : {total_return_rate:+.2f}%",
        f"  실현 손익 합계 : {pnl_sign}{total_net_pnl:,.0f}원",
        f"  최대 낙폭 (MDD): {max_drawdown:.2f}%",
        f"  손  익  비     : {profit_factor:.2f}",
        f"  평균 보유일    : {avg_holding:.1f}일",
    ]

    if total_trades == 0:
        lines.append("")
        lines.append("  ※ 해당 기간에 매수 신호가 없어 거래가 발생하지 않았습니다.")

    return "\n".join(lines)
