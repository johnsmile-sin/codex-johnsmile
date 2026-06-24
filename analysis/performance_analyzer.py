"""
analysis/performance_analyzer.py  –  전략 성과 분석 서비스 (3차 모의투자)

청산·손절·익절 상태의 virtual_positions 데이터를 기반으로
전략별 성과 지표를 계산하고 strategy_performance 테이블에 저장합니다.

Streamlit 대시보드 호환: 모든 반환값은 DataFrame / dict 형태로 구성됩니다.

공개 함수:
    calculate_strategy_performance(strategy_name)   전략별 전체 성과 지표 계산
    calculate_win_rate(trades)                       승률 계산
    calculate_average_return(trades)                 평균 수익률 계산
    calculate_profit_factor(trades)                  손익비 계산
    calculate_max_drawdown(trades)                   최대 낙폭 계산
    summarize_performance()                          전략별 요약 + Supabase 저장

strategy_performance 테이블 컬럼:
    strategy_name, total_trades, win_trades, lose_trades,
    win_rate, avg_return_rate, total_return_rate,
    max_drawdown, profit_factor, updated_at
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

DATA_DIR            = Path(__file__).resolve().parents[1] / "data"
PERFORMANCE_FILE    = DATA_DIR / "strategy_performance.json"
INITIAL_CASH        = 10_000_000.0

CLOSED_STATUSES     = {"청산", "손절", "익절"}


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


def _get_initial_cash() -> float:
    """포트폴리오 초기 투자금을 반환한다."""
    try:
        from services.virtual_portfolio import get_portfolio
        return float(get_portfolio().get("initial_cash", INITIAL_CASH))
    except Exception:
        return INITIAL_CASH


def _load_closed_positions() -> list[dict[str, Any]]:
    """
    청산·손절·익절된 포지션 전체를 로드한다.
    Supabase → 로컬 JSON 폴백.
    """
    if _supabase_connected():
        try:
            rows = (
                _supabase_client()
                .table("virtual_positions")
                .select("*")
                .in_("status", list(CLOSED_STATUSES))
                .order("entry_date", desc=False)
                .execute()
                .data or []
            )
            return rows
        except Exception:
            pass

    # 로컬 폴백
    positions_file = DATA_DIR / "virtual_positions.json"
    if positions_file.exists():
        try:
            all_pos: list[dict] = json.loads(
                positions_file.read_text(encoding="utf-8")
            )
            return [p for p in all_pos if p.get("status") in CLOSED_STATUSES]
        except Exception:
            pass

    return []


def _positions_to_df(positions: list[dict[str, Any]]) -> pd.DataFrame:
    """포지션 리스트를 분석용 DataFrame으로 변환한다."""
    if not positions:
        return pd.DataFrame()

    df = pd.DataFrame(positions)

    # 숫자형 변환
    for col in ("profit_loss", "return_rate", "entry_price", "current_price",
                "evaluation_amount", "holding_days", "quantity"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # 날짜 변환 (정렬 용)
    if "entry_date" in df.columns:
        df["entry_date"] = pd.to_datetime(df["entry_date"], errors="coerce")

    if "updated_at" in df.columns:
        df["updated_at"] = pd.to_datetime(df["updated_at"], errors="coerce")

    # 승패 구분 컬럼
    df["is_win"] = df["profit_loss"] > 0

    return df


def _empty_metrics(strategy_name: str = "전체") -> dict[str, Any]:
    """거래 데이터가 없을 때 반환할 빈 지표 dict."""
    return {
        "strategy_name":    strategy_name,
        "total_trades":     0,
        "win_trades":       0,
        "lose_trades":      0,
        "win_rate":         0.0,
        "avg_return_rate":  0.0,
        "total_return_rate": 0.0,
        "max_drawdown":     0.0,
        "profit_factor":    0.0,
        "updated_at":       _now(),
        # Streamlit 추가 지표
        "gross_profit":     0.0,
        "gross_loss":       0.0,
        "avg_win_return":   0.0,
        "avg_loss_return":  0.0,
        "total_profit_loss": 0.0,
        "sharpe_approx":    0.0,
        "avg_holding_days": 0.0,
        "익절_count":       0,
        "손절_count":       0,
        "청산_count":       0,
    }


# ════════════════════════════════════════════════════════════════
# 개별 지표 계산 함수
# ════════════════════════════════════════════════════════════════

def calculate_win_rate(trades: pd.DataFrame) -> dict[str, Any]:
    """
    승률을 계산한다.

    Args:
        trades: 청산 거래 DataFrame (profit_loss 컬럼 필수)

    Returns:
        dict:
            total_trades  int   총 거래 수
            win_trades    int   수익 거래 수 (profit_loss > 0)
            lose_trades   int   손실 거래 수 (profit_loss <= 0)
            win_rate      float 승률 (%)
    """
    if trades.empty:
        return {"total_trades": 0, "win_trades": 0, "lose_trades": 0, "win_rate": 0.0}

    total   = len(trades)
    wins    = int((trades["profit_loss"] > 0).sum())
    losses  = total - wins
    rate    = round(wins / total * 100, 2) if total > 0 else 0.0

    return {
        "total_trades": total,
        "win_trades":   wins,
        "lose_trades":  losses,
        "win_rate":     rate,
    }


def calculate_average_return(trades: pd.DataFrame) -> dict[str, Any]:
    """
    평균 수익률과 관련 통계를 계산한다.

    Args:
        trades: 청산 거래 DataFrame (return_rate, profit_loss 컬럼 필수)

    Returns:
        dict:
            avg_return_rate   float 평균 수익률 (%)
            total_return_rate float 누적 수익률 (%) = 합산 손익 / 초기 투자금
            avg_win_return    float 수익 거래 평균 수익률
            avg_loss_return   float 손실 거래 평균 수익률 (음수)
            total_profit_loss float 합산 실현 손익 (원)
            sharpe_approx     float 근사 샤프지수 (평균수익률 / 수익률표준편차)
            avg_holding_days  float 평균 보유일
    """
    if trades.empty:
        return {
            "avg_return_rate":   0.0,
            "total_return_rate": 0.0,
            "avg_win_return":    0.0,
            "avg_loss_return":   0.0,
            "total_profit_loss": 0.0,
            "sharpe_approx":     0.0,
            "avg_holding_days":  0.0,
        }

    initial_cash = _get_initial_cash()

    avg_return    = round(float(trades["return_rate"].mean()), 4)
    total_pnl     = round(float(trades["profit_loss"].sum()), 2)
    total_return  = round(total_pnl / initial_cash * 100, 4) if initial_cash > 0 else 0.0

    wins  = trades[trades["profit_loss"] > 0]
    losses = trades[trades["profit_loss"] <= 0]
    avg_win  = round(float(wins["return_rate"].mean()),   4) if not wins.empty  else 0.0
    avg_loss = round(float(losses["return_rate"].mean()), 4) if not losses.empty else 0.0

    std = float(trades["return_rate"].std())
    sharpe = round(avg_return / std, 4) if std > 0 else 0.0

    avg_days = 0.0
    if "holding_days" in trades.columns:
        avg_days = round(float(trades["holding_days"].mean()), 1)

    return {
        "avg_return_rate":   avg_return,
        "total_return_rate": total_return,
        "avg_win_return":    avg_win,
        "avg_loss_return":   avg_loss,
        "total_profit_loss": total_pnl,
        "sharpe_approx":     sharpe,
        "avg_holding_days":  avg_days,
    }


def calculate_profit_factor(trades: pd.DataFrame) -> dict[str, Any]:
    """
    손익비(Profit Factor)를 계산한다.

    손익비 = 총 수익 합계 / 총 손실 합계의 절댓값
    2.0 이상이면 우수, 1.0 미만이면 손실 전략.

    Args:
        trades: 청산 거래 DataFrame (profit_loss 컬럼 필수)

    Returns:
        dict:
            profit_factor  float 손익비
            gross_profit   float 총 수익 합계 (원)
            gross_loss     float 총 손실 합계 (원, 양수)
    """
    if trades.empty:
        return {"profit_factor": 0.0, "gross_profit": 0.0, "gross_loss": 0.0}

    gross_profit = float(trades[trades["profit_loss"] > 0]["profit_loss"].sum())
    gross_loss   = abs(float(trades[trades["profit_loss"] < 0]["profit_loss"].sum()))

    if gross_loss == 0:
        factor = round(gross_profit, 6) if gross_profit > 0 else 0.0
    else:
        factor = round(gross_profit / gross_loss, 6)

    return {
        "profit_factor": factor,
        "gross_profit":  round(gross_profit, 2),
        "gross_loss":    round(gross_loss, 2),
    }


def calculate_max_drawdown(trades: pd.DataFrame) -> dict[str, Any]:
    """
    최대 낙폭(Max Drawdown)을 계산한다.

    entry_date 순으로 손익을 누적한 커브에서
    고점 대비 최대 하락폭을 계산한다.

    Args:
        trades: 청산 거래 DataFrame (profit_loss, entry_date 컬럼 필수)

    Returns:
        dict:
            max_drawdown        float 최대 낙폭 (%, 음수)
            max_drawdown_amount float 최대 낙폭 금액 (원, 음수)
            drawdown_series     list  누적 손익 시계열 (Streamlit 차트용)
    """
    if trades.empty or "profit_loss" not in trades.columns:
        return {
            "max_drawdown":        0.0,
            "max_drawdown_amount": 0.0,
            "drawdown_series":     [],
        }

    initial_cash = _get_initial_cash()

    # entry_date 기준 정렬 후 누적 손익 계산
    sorted_trades = trades.sort_values(
        "entry_date" if "entry_date" in trades.columns else trades.columns[0]
    ).copy()

    sorted_trades["cumulative_pnl"]    = sorted_trades["profit_loss"].cumsum()
    sorted_trades["equity"]            = initial_cash + sorted_trades["cumulative_pnl"]
    sorted_trades["running_max"]       = sorted_trades["equity"].cummax()
    sorted_trades["drawdown_amount"]   = sorted_trades["equity"] - sorted_trades["running_max"]
    sorted_trades["drawdown_pct"]      = sorted_trades["drawdown_amount"] / sorted_trades["running_max"] * 100

    max_dd_amount = float(sorted_trades["drawdown_amount"].min())
    max_dd_pct    = float(sorted_trades["drawdown_pct"].min())

    # Streamlit 차트용 시계열 데이터
    date_col = "entry_date" if "entry_date" in sorted_trades.columns else None
    series: list[dict] = []
    for _, row in sorted_trades.iterrows():
        entry = {
            "cumulative_pnl": round(float(row["cumulative_pnl"]), 2),
            "equity":         round(float(row["equity"]), 2),
            "drawdown_pct":   round(float(row["drawdown_pct"]), 4),
        }
        if date_col:
            dt = row[date_col]
            entry["date"] = str(dt)[:10] if pd.notna(dt) else ""
        series.append(entry)

    return {
        "max_drawdown":        round(max_dd_pct, 4),
        "max_drawdown_amount": round(max_dd_amount, 2),
        "drawdown_series":     series,
    }


# ════════════════════════════════════════════════════════════════
# 통합 계산 함수
# ════════════════════════════════════════════════════════════════

def calculate_strategy_performance(
    strategy_name: str | None = None,
    positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    특정 전략(또는 전체)의 성과 지표를 계산한다.

    Args:
        strategy_name: 전략명 (None이면 전체 합산)
        positions:     청산 포지션 리스트 (None이면 자동 로드)

    Returns:
        dict: strategy_performance 테이블 컬럼 + Streamlit 확장 지표
            strategy_name, total_trades, win_trades, lose_trades,
            win_rate, avg_return_rate, total_return_rate,
            max_drawdown, profit_factor, updated_at,
            gross_profit, gross_loss, avg_win_return, avg_loss_return,
            total_profit_loss, sharpe_approx, avg_holding_days,
            익절_count, 손절_count, 청산_count,
            drawdown_series, trades_df (Streamlit 차트용)
    """
    if positions is None:
        positions = _load_closed_positions()

    df = _positions_to_df(positions)

    label = strategy_name or "전체"

    if df.empty:
        return _empty_metrics(label)

    # 전략 필터
    if strategy_name and "strategy_name" in df.columns:
        df = df[df["strategy_name"] == strategy_name].copy()

    if df.empty:
        return _empty_metrics(label)

    # 개별 지표 계산
    win_info    = calculate_win_rate(df)
    return_info = calculate_average_return(df)
    pf_info     = calculate_profit_factor(df)
    dd_info     = calculate_max_drawdown(df)

    # 청산 사유별 집계
    status_counts = df["status"].value_counts().to_dict() if "status" in df.columns else {}

    result: dict[str, Any] = {
        # strategy_performance 테이블 컬럼
        "strategy_name":    label,
        "total_trades":     win_info["total_trades"],
        "win_trades":       win_info["win_trades"],
        "lose_trades":      win_info["lose_trades"],
        "win_rate":         win_info["win_rate"],
        "avg_return_rate":  return_info["avg_return_rate"],
        "total_return_rate": return_info["total_return_rate"],
        "max_drawdown":     dd_info["max_drawdown"],
        "profit_factor":    pf_info["profit_factor"],
        "updated_at":       _now(),
        # Streamlit 확장 지표
        "gross_profit":     pf_info["gross_profit"],
        "gross_loss":       pf_info["gross_loss"],
        "avg_win_return":   return_info["avg_win_return"],
        "avg_loss_return":  return_info["avg_loss_return"],
        "total_profit_loss": return_info["total_profit_loss"],
        "sharpe_approx":    return_info["sharpe_approx"],
        "avg_holding_days": return_info["avg_holding_days"],
        "max_drawdown_amount": dd_info["max_drawdown_amount"],
        "익절_count":       int(status_counts.get("익절", 0)),
        "손절_count":       int(status_counts.get("손절", 0)),
        "청산_count":       int(status_counts.get("청산", 0)),
        "drawdown_series":  dd_info["drawdown_series"],
        "trades_df":        df,  # Streamlit 테이블용 원본 DataFrame
    }

    return result


# ════════════════════════════════════════════════════════════════
# 전략별 요약 + 저장
# ════════════════════════════════════════════════════════════════

def summarize_performance() -> dict[str, Any]:
    """
    모든 전략의 성과를 계산하고 strategy_performance 테이블에 저장한다.

    Streamlit 대시보드 호환 반환값:
        summary_df      pd.DataFrame  전략별 핵심 지표 테이블
        detail_list     list[dict]    전략별 전체 지표 (drawdown_series 포함)
        total           dict          전체 합산 지표
        summary_text    str           한국어 요약 문자열

    Returns:
        dict:
            summary_df    전략별 지표 DataFrame (Streamlit st.dataframe용)
            detail_list   전략별 전체 성과 dict 리스트
            total         전체 합산 성과 dict
            summary_text  한국어 요약 문자열
    """
    positions = _load_closed_positions()
    df_all    = _positions_to_df(positions)

    # 전략 목록 추출
    if not df_all.empty and "strategy_name" in df_all.columns:
        strategy_names = sorted(df_all["strategy_name"].dropna().unique().tolist())
    else:
        strategy_names = []

    detail_list: list[dict[str, Any]] = []

    for name in strategy_names:
        perf = calculate_strategy_performance(
            strategy_name=name, positions=positions
        )
        detail_list.append(perf)
        _upsert_performance(perf)

    # 전체 합산
    total = calculate_strategy_performance(strategy_name=None, positions=positions)
    total["strategy_name"] = "전체"

    # Streamlit 요약 DataFrame (trades_df/drawdown_series 제외)
    _exclude = {"trades_df", "drawdown_series"}
    summary_rows = [
        {k: v for k, v in p.items() if k not in _exclude}
        for p in detail_list
    ]
    summary_df = _build_summary_df(summary_rows)

    summary_text = _build_summary_text(detail_list, total)

    return {
        "summary_df":   summary_df,
        "detail_list":  detail_list,
        "total":        total,
        "summary_text": summary_text,
    }


def _upsert_performance(perf: dict[str, Any]) -> None:
    """strategy_performance 테이블에 UPSERT한다."""
    # DB 저장 컬럼만 추출 (strategy_name은 UNIQUE 키)
    db_cols = {
        "strategy_name", "total_trades", "win_trades", "lose_trades",
        "win_rate", "avg_return_rate", "total_return_rate",
        "max_drawdown", "profit_factor", "updated_at",
    }
    record = {k: v for k, v in perf.items() if k in db_cols}

    if _supabase_connected():
        try:
            _supabase_client().table("strategy_performance").upsert(
                record, on_conflict="strategy_name"
            ).execute()
            return
        except Exception:
            pass

    # 로컬 JSON 폴백
    _save_performance_local(record)


def _save_performance_local(record: dict[str, Any]) -> None:
    """strategy_performance를 로컬 JSON 파일에 저장(업데이트)한다."""
    _ensure_data_dir()
    existing: list[dict] = []
    if PERFORMANCE_FILE.exists():
        try:
            existing = json.loads(PERFORMANCE_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    # 동일 strategy_name 교체
    name = record.get("strategy_name", "")
    existing = [e for e in existing if e.get("strategy_name") != name]
    existing.append(record)

    PERFORMANCE_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_summary_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Streamlit 테이블 표시용 요약 DataFrame을 생성한다."""
    if not rows:
        return pd.DataFrame(columns=[
            "전략명", "총 거래", "승리", "손실", "승률(%)",
            "평균 수익률(%)", "누적 수익률(%)", "최대 낙폭(%)",
            "손익비", "실현 손익(원)",
        ])

    display_rows = []
    for r in rows:
        display_rows.append({
            "전략명":        r.get("strategy_name", ""),
            "총 거래":       r.get("total_trades", 0),
            "승리":          r.get("win_trades", 0),
            "손실":          r.get("lose_trades", 0),
            "승률(%)":       r.get("win_rate", 0.0),
            "평균 수익률(%)": r.get("avg_return_rate", 0.0),
            "누적 수익률(%)": r.get("total_return_rate", 0.0),
            "최대 낙폭(%)":  r.get("max_drawdown", 0.0),
            "손익비":        r.get("profit_factor", 0.0),
            "실현 손익(원)": r.get("total_profit_loss", 0.0),
            "익절":          r.get("익절_count", 0),
            "손절":          r.get("손절_count", 0),
            "기타 청산":     r.get("청산_count", 0),
            "평균 보유일":   r.get("avg_holding_days", 0.0),
        })

    return pd.DataFrame(display_rows)


def _build_summary_text(
    detail_list: list[dict[str, Any]],
    total: dict[str, Any],
) -> str:
    """한국어 성과 요약 문자열을 생성한다."""
    lines = [
        "【 모의투자 전략별 성과 분석 】",
        "",
        f"  분석 대상 전략: {len(detail_list)}개",
        f"  총 거래 수:     {total.get('total_trades', 0)}건",
        f"  전체 승률:      {total.get('win_rate', 0.0):.2f}%",
        f"  누적 수익률:    {total.get('total_return_rate', 0.0):+.2f}%",
        f"  실현 손익 합계: {total.get('total_profit_loss', 0.0):+,.0f}원",
        f"  최대 낙폭:      {total.get('max_drawdown', 0.0):.2f}%",
        f"  전체 손익비:    {total.get('profit_factor', 0.0):.2f}",
        "",
        "▶ 전략별 상세",
    ]

    for p in detail_list:
        pnl_sign = "+" if p.get("total_profit_loss", 0) >= 0 else ""
        lines.append(
            f"  [{p['strategy_name']}]  "
            f"거래 {p['total_trades']}건  승률 {p['win_rate']:.1f}%  "
            f"수익 {p.get('avg_return_rate', 0):+.2f}%  "
            f"손익비 {p['profit_factor']:.2f}  "
            f"실현 {pnl_sign}{p.get('total_profit_loss', 0):,.0f}원  "
            f"최대낙폭 {p['max_drawdown']:.1f}%  "
            f"(익절 {p.get('익절_count', 0)} / 손절 {p.get('손절_count', 0)} / 청산 {p.get('청산_count', 0)})"
        )

    if not detail_list:
        lines.append("  ※ 청산된 거래 내역이 없습니다.")

    return "\n".join(lines)
