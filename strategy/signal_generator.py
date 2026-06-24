"""
strategy/signal_generator.py  –  매매 신호 생성기 (4차)

후보 종목(scored_df)과 보유 포지션을 기반으로 매매 신호를 생성합니다.
생성된 신호는 trade_signals 테이블(Supabase) 또는 로컬 JSON에 저장됩니다.

⚠️  신호 생성은 주문 실행이 아닙니다.
    실제 주문은 order_intents → broker_orders 단계에서만 이루어집니다.

공개 함수:
    generate_buy_signals(candidates, strategy_name, scored_df)
    generate_sell_signals(positions, scored_df)
    save_trade_signals(signals)
    get_trade_signals(status, limit)
    expire_old_signals()
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════
# 상수
# ════════════════════════════════════════════════════════════════

DATA_DIR     = Path(__file__).resolve().parents[1] / "data"
SIGNALS_FILE = DATA_DIR / "trade_signals.json"

# 매수 신호 허용 결정값
_BUY_DECISIONS = {"강한 관심", "관심"}

# 매수 차단 뉴스 감성
_NEGATIVE_SENTIMENT = {"부정"}

# 치명적 리스크 키워드 — 포함 시 매수 신호 차단
_FATAL_RISK_KEYWORDS = [
    "상장폐지", "감사의견 거절", "유동성 위기", "횡령", "배임",
    "법적 분쟁", "불성실 공시", "관리종목", "투자주의", "조회공시",
]

# 전략 기본값 (strategy_rules DB에서 읽지 못할 때 사용)
_DEFAULT_RULES: dict[str, Any] = {
    "strategy_name":     "v3_score_momentum",
    "min_score":         75,
    "take_profit_rate":  8.0,
    "stop_loss_rate":    -4.0,
    "max_holding_days":  20,
    "max_position_amount": 1_000_000,
}

# 점수 급락 기준 — 이 값 이상 떨어지면 매도 신호
_SCORE_DROP_THRESHOLD = 15.0


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼
# ════════════════════════════════════════════════════════════════

def _today() -> str:
    return str(date.today())


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


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _row_val(row: Any, col: str, default: Any = None) -> Any:
    """DataFrame 행 또는 dict에서 값을 안전하게 가져온다."""
    try:
        val = row[col] if isinstance(row, dict) else row.get(col, default)
        if val is None:
            return default
        try:
            if pd.isna(val):
                return default
        except (TypeError, ValueError):
            pass
        return val
    except (KeyError, AttributeError):
        return default


def _load_strategy_rules(strategy_name: str | None = None) -> dict[str, Any]:
    """strategy_rules 테이블에서 전략 설정을 로드한다. 실패 시 기본값 반환."""
    rules = dict(_DEFAULT_RULES)
    if not _supabase_connected():
        return rules
    try:
        q = _supabase_client().table("strategy_rules").select("*")
        if strategy_name:
            q = q.eq("strategy_name", strategy_name)
        else:
            q = q.eq("is_active", True)
        rows = q.order("id", desc=False).limit(1).execute().data or []
        if rows:
            r = rows[0]
            rules.update({
                "strategy_name":      r.get("strategy_name",      rules["strategy_name"]),
                "min_score":          int(r.get("min_score",       rules["min_score"])),
                "take_profit_rate":   float(r.get("take_profit_rate",  rules["take_profit_rate"])),
                "stop_loss_rate":     float(r.get("stop_loss_rate",    rules["stop_loss_rate"])),
                "max_holding_days":   int(r.get("max_holding_days",    rules["max_holding_days"])),
                "max_position_amount": float(r.get("max_position_amount", rules["max_position_amount"])),
            })
    except Exception as e:
        logger.warning("[SignalGen] strategy_rules 로드 실패: %s → 기본값 사용", e)
    return rules


def _get_held_codes() -> set[str]:
    """현재 보유 중인 종목코드 집합을 반환한다. (가상 + 실계좌 병합)"""
    codes: set[str] = set()
    # 가상 포지션
    try:
        from services.virtual_position import get_positions
        for p in get_positions(status="보유"):
            codes.add(str(p.get("stock_code", "")).zfill(6))
    except Exception:
        pass
    # 키움 실계좌(모의투자)
    try:
        from services.kiwoom_data import get_positions as kiwoom_positions
        for p in kiwoom_positions():
            codes.add(str(p.get("stock_code", "")).zfill(6))
    except Exception:
        pass
    return codes


def _has_fatal_risk(risk_text: str | None) -> bool:
    """치명적 리스크 키워드가 포함되어 있으면 True."""
    if not risk_text:
        return False
    return any(kw in risk_text for kw in _FATAL_RISK_KEYWORDS)


def _build_buy_reason(row: Any, rules: dict[str, Any]) -> tuple[str, str]:
    """매수 신호 reason 및 risk_summary 문자열을 생성한다."""
    score    = _safe_float(_row_val(row, "score"))
    decision = _row_val(row, "decision", "")
    reasons  = _row_val(row, "reasons", "") or ""
    risks    = _row_val(row, "risks",   "") or ""
    sentiment = _row_val(row, "news_sentiment", "중립") or "중립"

    reason_parts = [
        f"후보 점수 {score:.1f}점 (기준 {rules['min_score']}점 이상)",
        f"판단: {decision}",
    ]
    if sentiment == "긍정":
        reason_parts.append("뉴스 심리: 긍정")
    if reasons:
        reason_parts.append(f"가산 근거: {reasons[:200]}")

    risk_parts = []
    if risks:
        risk_parts.append(risks[:200])
    if sentiment == "중립":
        risk_parts.append("뉴스 심리 중립")

    return " | ".join(reason_parts), " | ".join(risk_parts) if risk_parts else "특이 리스크 없음"


def _build_sell_reason(
    position: dict[str, Any],
    trigger: str,
    rules: dict[str, Any],
    current_score: float | None = None,
) -> tuple[str, str]:
    """매도 신호 reason 및 risk_summary 문자열을 생성한다."""
    pnl_rate     = _safe_float(position.get("pnl_rate"))
    holding_days = _safe_int(position.get("holding_days"))

    _TRIGGER_MSG = {
        "익절":       f"목표 수익률 {rules['take_profit_rate']:.1f}% 도달 (현재 {pnl_rate:+.2f}%)",
        "손절":       f"손절 라인 {rules['stop_loss_rate']:.1f}% 도달 (현재 {pnl_rate:+.2f}%)",
        "최대보유일": f"최대 보유일 {rules['max_holding_days']}일 초과 (보유 {holding_days}일)",
        "부정뉴스":   f"뉴스 심리 부정 전환 (현재 수익률 {pnl_rate:+.2f}%)",
        "점수급락":   f"후보 점수 급락 {_SCORE_DROP_THRESHOLD}점 이상 하락"
                      + (f" (현재 {current_score:.1f}점)" if current_score is not None else ""),
    }

    reason = _TRIGGER_MSG.get(trigger, trigger)
    risk   = f"매도 트리거: {trigger}"
    return reason, risk


# ════════════════════════════════════════════════════════════════
# 공개 함수 1 — 매수 신호 생성
# ════════════════════════════════════════════════════════════════

def generate_buy_signals(
    candidates: pd.DataFrame | list[dict],
    strategy_name: str | None = None,
    scored_df: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """
    후보 종목 리스트에서 매수 신호를 생성합니다.
    생성된 신호는 저장하지 않습니다. save_trade_signals()를 별도로 호출하세요.

    매수 조건:
        ① 후보 점수 >= min_score (기본 75)
        ② decision 이 '관심' 또는 '강한 관심'
        ③ 뉴스 심리가 '부정'이 아님
        ④ 치명적 리스크 키워드 없음
        ⑤ 현재 보유 중인 종목 제외

    Args:
        candidates:     scan() 결과 DataFrame 또는 dict 리스트
        strategy_name:  적용할 전략명 (None 이면 활성 전략 자동 선택)
        scored_df:      candidates 와 동일 (None 허용)

    Returns:
        list[dict]: trade_signals 형식의 신호 딕셔너리 목록
    """
    rules     = _load_strategy_rules(strategy_name)
    held_codes = _get_held_codes()
    signals: list[dict[str, Any]] = []

    # DataFrame → 행 순회 가능한 형태로 통일
    rows: list[Any]
    if isinstance(candidates, pd.DataFrame):
        rows = [candidates.iloc[i] for i in range(len(candidates))]
    else:
        rows = list(candidates)

    for row in rows:
        code  = str(_row_val(row, "stock_code", "") or "").zfill(6)
        name  = str(_row_val(row, "stock_name", "") or "")
        score = _safe_float(_row_val(row, "score"))
        decision  = str(_row_val(row, "decision", "") or "")
        sentiment = str(_row_val(row, "news_sentiment", "중립") or "중립")
        risks_txt = str(_row_val(row, "risks", "") or "")
        price     = _safe_int(_row_val(row, "close") or _row_val(row, "signal_price"))

        # ── 조건 검사 ────────────────────────────────────────────
        if not code or code == "000000":
            continue
        if score < rules["min_score"]:
            logger.debug("[SignalGen] 점수 미달 제외: %s (%.1f < %d)", code, score, rules["min_score"])
            continue
        if decision not in _BUY_DECISIONS:
            logger.debug("[SignalGen] 판단 미달 제외: %s (%s)", code, decision)
            continue
        if sentiment in _NEGATIVE_SENTIMENT:
            logger.debug("[SignalGen] 부정 뉴스 차단: %s", code)
            continue
        if _has_fatal_risk(risks_txt):
            logger.warning("[SignalGen] 치명적 리스크 차단: %s — %s", code, risks_txt[:80])
            continue
        if code in held_codes:
            logger.debug("[SignalGen] 보유 중 종목 제외: %s", code)
            continue
        if price <= 0:
            logger.debug("[SignalGen] 현재가 없음 제외: %s", code)
            continue

        reason, risk_summary = _build_buy_reason(row, rules)

        signals.append({
            "signal_date":   _today(),
            "stock_code":    code,
            "stock_name":    name,
            "strategy_name": rules["strategy_name"],
            "signal_type":   "매수신호",
            "signal_price":  price,
            "score":         round(score, 2),
            "reason":        reason,
            "risk_summary":  risk_summary,
            "status":        "생성",
        })

    logger.info(
        "[SignalGen] 매수 신호 생성 완료: %d건 / 후보 %d개",
        len(signals), len(rows),
    )
    return signals


# ════════════════════════════════════════════════════════════════
# 공개 함수 2 — 매도 신호 생성
# ════════════════════════════════════════════════════════════════

def generate_sell_signals(
    positions: list[dict[str, Any]],
    scored_df: pd.DataFrame | None = None,
    strategy_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    보유 포지션에서 매도 신호를 생성합니다.
    생성된 신호는 저장하지 않습니다. save_trade_signals()를 별도로 호출하세요.

    매도 조건 (하나라도 해당하면 신호 생성):
        ① 목표 수익률 도달 (익절)
        ② 손절 라인 도달 (손절)
        ③ 최대 보유일 초과
        ④ 뉴스 심리 부정 전환
        ⑤ 후보 점수 급락 (15점 이상 하락)

    Args:
        positions:      보유 포지션 목록 (virtual_position 또는 kiwoom_data 형식)
        scored_df:      최신 스캐너 결과 (점수 급락 감지에 사용, None 허용)
        strategy_name:  적용할 전략명

    Returns:
        list[dict]: trade_signals 형식의 신호 딕셔너리 목록
    """
    rules   = _load_strategy_rules(strategy_name)
    signals: list[dict[str, Any]] = []

    # scored_df → 종목코드 : 현재점수 인덱스
    score_index: dict[str, float] = {}
    if scored_df is not None and not scored_df.empty:
        for _, r in scored_df.iterrows():
            c = str(r.get("stock_code", "")).zfill(6)
            s = _safe_float(r.get("score"))
            if c:
                score_index[c] = s

    for pos in positions:
        code         = str(pos.get("stock_code", "")).zfill(6)
        name         = str(pos.get("stock_name", "") or "")
        pnl_rate     = _safe_float(pos.get("pnl_rate") or pos.get("return_rate"))
        holding_days = _safe_int(pos.get("holding_days"))
        curr_price   = _safe_int(pos.get("current_price") or pos.get("prpr"))
        entry_score  = _safe_float(pos.get("entry_score"))   # 진입 시 점수 (있으면)
        sentiment    = str(pos.get("news_sentiment", "중립") or "중립")

        if not code or code == "000000":
            continue

        trigger: str | None = None
        current_score: float | None = score_index.get(code)

        # ① 익절
        if pnl_rate >= rules["take_profit_rate"]:
            trigger = "익절"
        # ② 손절
        elif pnl_rate <= rules["stop_loss_rate"]:
            trigger = "손절"
        # ③ 최대 보유일
        elif holding_days > rules["max_holding_days"]:
            trigger = "최대보유일"
        # ④ 부정 뉴스
        elif sentiment in _NEGATIVE_SENTIMENT:
            trigger = "부정뉴스"
        # ⑤ 점수 급락 (진입 점수 대비 or 절대 급락)
        elif current_score is not None:
            if entry_score and (entry_score - current_score) >= _SCORE_DROP_THRESHOLD:
                trigger = "점수급락"
            elif current_score < 40:   # 절대 하한선
                trigger = "점수급락"

        if trigger is None:
            continue

        reason, risk_summary = _build_sell_reason(pos, trigger, rules, current_score)

        signals.append({
            "signal_date":   _today(),
            "stock_code":    code,
            "stock_name":    name,
            "strategy_name": rules["strategy_name"],
            "signal_type":   "매도신호",
            "signal_price":  curr_price,
            "score":         round(current_score, 2) if current_score is not None else None,
            "reason":        reason,
            "risk_summary":  risk_summary,
            "status":        "생성",
        })

    logger.info(
        "[SignalGen] 매도 신호 생성 완료: %d건 / 포지션 %d개",
        len(signals), len(positions),
    )
    return signals


# ════════════════════════════════════════════════════════════════
# 공개 함수 3 — 신호 저장
# ════════════════════════════════════════════════════════════════

def save_trade_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    생성된 매매 신호를 저장합니다.
    Supabase 연결 시 trade_signals 테이블, 미연결 시 로컬 JSON.

    Args:
        signals: generate_buy_signals / generate_sell_signals 반환값

    Returns:
        list[dict]: 저장된 신호 목록 (id 포함, Supabase 사용 시)
    """
    if not signals:
        return []

    saved: list[dict[str, Any]] = []

    if _supabase_connected():
        try:
            resp = (
                _supabase_client()
                .table("trade_signals")
                .insert(signals)
                .execute()
            )
            saved = resp.data or signals
            logger.info("[SignalGen] Supabase 저장 완료: %d건", len(saved))
            return saved
        except Exception as e:
            logger.warning("[SignalGen] Supabase 저장 실패: %s → 로컬 저장", e)

    # ── 로컬 JSON 폴백 ───────────────────────────────────────────
    _ensure_data_dir()
    existing: list[dict[str, Any]] = []
    if SIGNALS_FILE.exists():
        try:
            existing = json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    next_id = max((s.get("id", 0) for s in existing), default=0) + 1
    for sig in signals:
        sig = dict(sig)
        sig["id"]         = next_id
        sig["created_at"] = _now()
        existing.append(sig)
        saved.append(sig)
        next_id += 1

    SIGNALS_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[SignalGen] 로컬 저장 완료: %d건 → %s", len(saved), SIGNALS_FILE)
    return saved


# ════════════════════════════════════════════════════════════════
# 공개 함수 4 — 신호 조회
# ════════════════════════════════════════════════════════════════

def get_trade_signals(
    status: str | None = None,
    signal_type: str | None = None,
    limit: int = 100,
    signal_date: str | None = None,
) -> list[dict[str, Any]]:
    """
    저장된 매매 신호를 조회합니다.

    Args:
        status:      '생성' | '주문후보생성' | '무시' | '만료' | None(전체)
        signal_type: '매수신호' | '매도신호' | None(전체)
        limit:       최대 반환 건수 (기본 100)
        signal_date: 특정 날짜 필터 (YYYY-MM-DD, None 이면 전체)

    Returns:
        list[dict]: 신호 목록 (최신순)
    """
    if _supabase_connected():
        try:
            q = (
                _supabase_client()
                .table("trade_signals")
                .select("*")
                .order("created_at", desc=True)
                .limit(limit)
            )
            if status:
                q = q.eq("status", status)
            if signal_type:
                q = q.eq("signal_type", signal_type)
            if signal_date:
                q = q.eq("signal_date", signal_date)
            return q.execute().data or []
        except Exception as e:
            logger.warning("[SignalGen] Supabase 조회 실패: %s → 로컬 조회", e)

    # ── 로컬 JSON 폴백 ───────────────────────────────────────────
    if not SIGNALS_FILE.exists():
        return []
    try:
        all_signals: list[dict] = json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    result = all_signals
    if status:
        result = [s for s in result if s.get("status") == status]
    if signal_type:
        result = [s for s in result if s.get("signal_type") == signal_type]
    if signal_date:
        result = [s for s in result if s.get("signal_date") == signal_date]

    # 최신순 정렬 후 limit 적용
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return result[:limit]


# ════════════════════════════════════════════════════════════════
# 공개 함수 5 — 오래된 신호 만료 처리
# ════════════════════════════════════════════════════════════════

def expire_old_signals() -> int:
    """
    오늘보다 이전 날짜의 '생성' 상태 신호를 '만료'로 일괄 변경합니다.

    Returns:
        int: 만료 처리된 신호 수
    """
    today    = _today()
    expired  = 0

    if _supabase_connected():
        try:
            resp = (
                _supabase_client()
                .table("trade_signals")
                .update({"status": "만료"})
                .eq("status", "생성")
                .lt("signal_date", today)
                .execute()
            )
            expired = len(resp.data or [])
            logger.info("[SignalGen] Supabase 만료 처리: %d건", expired)
            return expired
        except Exception as e:
            logger.warning("[SignalGen] Supabase 만료 처리 실패: %s → 로컬 처리", e)

    # ── 로컬 JSON 폴백 ───────────────────────────────────────────
    if not SIGNALS_FILE.exists():
        return 0
    try:
        all_signals: list[dict] = json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0

    for sig in all_signals:
        if sig.get("status") == "생성" and sig.get("signal_date", today) < today:
            sig["status"] = "만료"
            expired += 1

    if expired:
        SIGNALS_FILE.write_text(
            json.dumps(all_signals, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[SignalGen] 로컬 만료 처리: %d건", expired)

    return expired


# ════════════════════════════════════════════════════════════════
# 편의 함수 — 신호 상태 업데이트
# ════════════════════════════════════════════════════════════════

def update_signal_status(signal_id: int, new_status: str) -> bool:
    """
    단일 신호의 status를 변경합니다. (order_intent 생성 시 '주문후보생성' 으로 전환 등)

    Args:
        signal_id:  trade_signals.id
        new_status: '생성' | '주문후보생성' | '무시' | '만료'

    Returns:
        bool: 성공 여부
    """
    valid_statuses = {"생성", "주문후보생성", "무시", "만료"}
    if new_status not in valid_statuses:
        logger.error("[SignalGen] 유효하지 않은 status: %s", new_status)
        return False

    if _supabase_connected():
        try:
            _supabase_client().table("trade_signals").update(
                {"status": new_status}
            ).eq("id", signal_id).execute()
            return True
        except Exception as e:
            logger.warning("[SignalGen] 상태 업데이트 실패 (Supabase): %s", e)

    # 로컬 JSON 폴백
    if not SIGNALS_FILE.exists():
        return False
    try:
        all_signals = json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
        updated = False
        for sig in all_signals:
            if sig.get("id") == signal_id:
                sig["status"] = new_status
                updated = True
                break
        if updated:
            SIGNALS_FILE.write_text(
                json.dumps(all_signals, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return updated
    except Exception as e:
        logger.error("[SignalGen] 로컬 상태 업데이트 실패: %s", e)
        return False
