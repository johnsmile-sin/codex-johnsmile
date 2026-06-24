"""
strategy/risk_manager.py  –  리스크 관리 서비스 (4차)

모든 주문 전에 리스크 조건을 검사합니다.
실거래 주문 허용(allow_real_trading)은 항상 False로 고정됩니다.

4차 추가 검사 (10개):
    ① emergency_stop 활성 → 차단
    ② trading_mode = analysis_only → 차단
    ③ account_mode = real → 차단 (항상, 코드 레벨)
    ④ 시장가 주문 → 차단
    ⑤ 주문 금액 > max_order_amount (system_settings) → 차단
    ⑥ 최대 보유 종목 수 초과 → 차단
    ⑦ 동일 종목 중복 주문 → 차단
    ⑧ 1일 손실률 ≤ max_daily_loss_rate → 차단
    ⑨ 뉴스 심리 부정 (매수 시) → 확인필요
    ⑩ 데이터 신뢰도 낮음 → 확인필요

3차 검사 (유지):
    ⑪ 종목당 최대 투자금(max_position_amount) 초과 → 차단
    ⑫ 단일 종목 비중 초과 → 차단

반환 형식 (4차 신규):
    {
        "status":          "통과" | "차단" | "확인필요",
        "message":         str,        한국어 종합 메시지
        "checks":          list[dict], 개별 검사 결과
        "blocked_checks":  list[dict], 차단 항목만
        "warning_checks":  list[dict], 확인필요 항목만
    }

3차 기존 함수 (하위 호환):
    check_max_position_count()
    check_max_position_amount(amount)
    check_daily_loss_limit()
    check_single_stock_ratio(...)
    can_place_virtual_order(...)    → 내부적으로 run_full_risk_check() 호출
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════
# 기본 리스크 설정
# ════════════════════════════════════════════════════════════════

_DEFAULT_RISK: dict[str, Any] = {
    "max_daily_loss_rate":    -3.0,
    "max_position_count":      5,
    "max_position_amount":     1_000_000,
    "max_single_stock_ratio":  20.0,
    "allow_real_trading":      False,
}

_DEFAULT_SYSTEM: dict[str, Any] = {
    "trading_mode":       "analysis_only",
    "emergency_stop":     False,
    "max_order_amount":   1_000_000,
}


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼 — 설정 로드
# ════════════════════════════════════════════════════════════════

def _supabase_connected() -> bool:
    try:
        from services.supabase_client import is_connected
        return bool(is_connected())
    except Exception:
        return False


def _supabase_client():
    from services.supabase_client import get_client
    return get_client()


def _load_risk_settings() -> dict[str, Any]:
    """risk_settings 테이블 → 기본값 폴백. allow_real_trading 항상 False."""
    settings = dict(_DEFAULT_RISK)
    if _supabase_connected():
        try:
            rows = (
                _supabase_client()
                .table("risk_settings")
                .select("*")
                .order("id", desc=False)
                .limit(1)
                .execute()
                .data or []
            )
            if rows:
                r = rows[0]
                settings.update({
                    "max_daily_loss_rate":    float(r.get("max_daily_loss_rate",   _DEFAULT_RISK["max_daily_loss_rate"])),
                    "max_position_count":     int(r.get("max_position_count",      _DEFAULT_RISK["max_position_count"])),
                    "max_position_amount":    float(r.get("max_position_amount",   _DEFAULT_RISK["max_position_amount"])),
                    "max_single_stock_ratio": float(r.get("max_single_stock_ratio", _DEFAULT_RISK["max_single_stock_ratio"])),
                })
        except Exception as e:
            logger.warning("[RiskManager] risk_settings 로드 실패: %s", e)
    settings["allow_real_trading"] = False
    return settings


def _load_system_settings() -> dict[str, Any]:
    """system_settings 서비스 → 기본값 폴백."""
    try:
        from services.system_settings import get_system_settings
        s = get_system_settings()
        return {
            "trading_mode":     s.get("trading_mode",     _DEFAULT_SYSTEM["trading_mode"]),
            "emergency_stop":   bool(s.get("emergency_stop",   False)),
            "max_order_amount": int(s.get("max_order_amount",  _DEFAULT_SYSTEM["max_order_amount"])),
        }
    except Exception as e:
        logger.warning("[RiskManager] system_settings 로드 실패: %s → 기본값", e)
        return dict(_DEFAULT_SYSTEM)


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼 — 결과 생성
# ════════════════════════════════════════════════════════════════

def _pass(name: str, message: str, **extra) -> dict[str, Any]:
    return {"name": name, "status": "통과", "message": message, **extra}


def _warn(name: str, message: str, **extra) -> dict[str, Any]:
    return {"name": name, "status": "확인필요", "message": message, **extra}


def _block(name: str, message: str, **extra) -> dict[str, Any]:
    return {"name": name, "status": "차단", "message": message, **extra}


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼 — 데이터 조회
# ════════════════════════════════════════════════════════════════

def _get_open_position_count() -> int:
    """현재 보유 중(status='보유') 포지션 수."""
    try:
        from services.virtual_position import get_positions
        return len(get_positions(status="보유"))
    except Exception:
        pass
    try:
        from services.virtual_trading import list_virtual_orders, build_positions
        positions = build_positions(list_virtual_orders())
        return 0 if positions.empty else len(positions)
    except Exception:
        return 0


def _get_total_portfolio_value() -> float:
    try:
        from services.virtual_portfolio import get_portfolio
        return float(get_portfolio().get("total_asset", 10_000_000))
    except Exception:
        return 10_000_000.0


def _get_today_realized_pnl() -> float:
    """오늘 체결된 가상 매도 주문의 실현 손익 합계."""
    try:
        from services.virtual_trading import list_virtual_orders, DEFAULT_STRATEGY
    except Exception:
        return 0.0

    today_str = str(date.today())
    orders = list_virtual_orders()
    cost_basis: dict[tuple, dict] = {}
    today_pnl = 0.0

    for order in sorted(orders, key=lambda x: (x.get("order_date", ""), int(x.get("id", 0)))):
        code  = str(order.get("stock_code", "")).zfill(6)
        strat = str(order.get("strategy_name") or DEFAULT_STRATEGY)
        key   = (strat, code)
        side  = str(order.get("side", "")).upper()
        qty   = int(order.get("quantity", 0) or 0)
        price = float(order.get("price", 0) or 0)
        if qty <= 0 or price <= 0:
            continue

        if side == "BUY":
            pos = cost_basis.setdefault(key, {"quantity": 0, "cost_amount": 0.0})
            pos["cost_amount"] += qty * price
            pos["quantity"]    += qty
        elif side == "SELL":
            pos = cost_basis.get(key, {"quantity": 0, "cost_amount": 0.0})
            if pos["quantity"] > 0:
                avg_cost = pos["cost_amount"] / pos["quantity"]
                sell_qty = min(qty, pos["quantity"])
                pnl      = (price - avg_cost) * sell_qty
                pos["cost_amount"] -= avg_cost * sell_qty
                pos["quantity"]    -= sell_qty
                if str(order.get("order_date", ""))[:10] == today_str:
                    today_pnl += pnl

    return round(today_pnl, 2)


def _get_initial_cash() -> float:
    try:
        from services.virtual_portfolio import get_portfolio
        return float(get_portfolio().get("initial_cash", 10_000_000))
    except Exception:
        return 10_000_000.0


def _get_stock_invested_amount(stock_code: str) -> float:
    try:
        from services.virtual_position import get_positions
        positions = get_positions(status="보유", stock_code=stock_code)
        if positions:
            p = positions[0]
            return float(p.get("entry_price", 0)) * int(p.get("quantity", 0))
    except Exception:
        pass
    try:
        from services.virtual_trading import list_virtual_orders, build_positions
        positions = build_positions(list_virtual_orders())
        if not positions.empty:
            code = str(stock_code).zfill(6)
            matched = positions[positions["stock_code"] == code]
            if not matched.empty:
                r = matched.iloc[0]
                return float(r["avg_price"]) * int(r["quantity"])
    except Exception:
        pass
    return 0.0


def _has_pending_intent(stock_code: str) -> bool:
    """동일 종목에 대해 승인대기 주문 후보가 이미 있는지 확인."""
    try:
        from services.order_intent_service import get_order_intents
        intents = get_order_intents(status="승인대기", stock_code=stock_code, limit=1)
        return len(intents) > 0
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════
# 4차 개별 검사 함수  (name, status, message 형식)
# ════════════════════════════════════════════════════════════════

def check_emergency_stop() -> dict[str, Any]:
    """① 긴급 중지 활성 여부."""
    sys = _load_system_settings()
    if sys.get("emergency_stop", False):
        return _block("긴급_중지", "긴급 중지가 활성화되어 있습니다. 모든 주문이 차단됩니다.")
    return _pass("긴급_중지", "정상")


def check_trading_mode() -> dict[str, Any]:
    """② trading_mode가 analysis_only이면 주문 후보 생성 차단."""
    sys  = _load_system_settings()
    mode = sys.get("trading_mode", "analysis_only")
    if mode == "analysis_only":
        return _block(
            "매매_모드",
            "분석 전용(analysis_only) 모드입니다. '모의투자' 모드로 전환 후 시도하세요.",
        )
    return _pass("매매_모드", f"매매 모드: {mode}")


def check_real_trading_blocked(account_mode: str = "paper") -> dict[str, Any]:
    """③ account_mode = 'real' 이면 항상 차단. 코드 레벨 하드코딩."""
    mode = str(account_mode).strip().lower()
    if mode == "real":
        return _block(
            "실거래_차단",
            "실거래 주문은 이 서비스에서 영구적으로 차단됩니다. (allow_real_trading=False)",
        )
    if mode not in ("mock", "paper"):
        return _block("실거래_차단", f"알 수 없는 account_mode: '{account_mode}'")
    return _pass("실거래_차단", f"모드 확인: {mode}")


def check_order_type(price_type: str = "지정가") -> dict[str, Any]:
    """④ 시장가 주문은 항상 차단. 지정가만 허용."""
    if str(price_type).strip() == "시장가":
        return _block(
            "주문_유형",
            "시장가 자동주문은 차단됩니다. 지정가 주문만 허용됩니다. (ALLOW_MARKET_ORDER=False)",
        )
    return _pass("주문_유형", f"주문 유형: {price_type}")


def check_order_amount_limit(order_amount: float) -> dict[str, Any]:
    """⑤ 주문 금액이 system_settings.max_order_amount를 초과하면 차단."""
    sys        = _load_system_settings()
    max_amount = int(sys.get("max_order_amount", 1_000_000))
    amount     = float(order_amount)

    if amount > max_amount:
        return _block(
            "주문_금액_한도",
            f"주문 금액 {amount:,.0f}원이 1회 한도 {max_amount:,.0f}원을 초과합니다.",
            order_amount=amount,
            max_amount=max_amount,
        )
    return _pass(
        "주문_금액_한도",
        f"주문 금액 {amount:,.0f}원 ≤ 한도 {max_amount:,.0f}원",
        order_amount=amount,
        max_amount=max_amount,
    )


def check_position_count_limit() -> dict[str, Any]:
    """⑥ 동시 보유 종목 수가 max_position_count를 초과하면 차단."""
    risk     = _load_risk_settings()
    max_cnt  = int(risk["max_position_count"])
    curr_cnt = _get_open_position_count()

    if curr_cnt >= max_cnt:
        return _block(
            "최대_포지션_수",
            f"최대 보유 종목 수 도달: {curr_cnt}/{max_cnt}개. 기존 포지션 청산 후 신규 매수 가능합니다.",
            current_count=curr_cnt,
            max_count=max_cnt,
        )
    return _pass(
        "최대_포지션_수",
        f"보유 종목 수 정상: {curr_cnt}/{max_cnt}개",
        current_count=curr_cnt,
        max_count=max_cnt,
    )


def check_duplicate_order(stock_code: str) -> dict[str, Any]:
    """⑦ 동일 종목에 대해 승인대기 주문 후보가 이미 존재하면 차단."""
    code = str(stock_code).zfill(6)
    if _has_pending_intent(code):
        return _block(
            "중복_주문",
            f"{code} 종목에 대한 승인대기 주문이 이미 존재합니다. 해당 주문을 먼저 처리하세요.",
        )
    return _pass("중복_주문", "중복 주문 없음")


def check_daily_loss_rate() -> dict[str, Any]:
    """⑧ 오늘 실현 손익이 max_daily_loss_rate 이하이면 차단."""
    risk          = _load_risk_settings()
    max_loss_rate = float(risk["max_daily_loss_rate"])   # 음수 (예: -3.0)
    initial_cash  = _get_initial_cash()
    loss_limit    = round(initial_cash * max_loss_rate / 100, 2)
    today_pnl     = _get_today_realized_pnl()
    loss_rate     = round(today_pnl / initial_cash * 100, 4) if initial_cash else 0.0

    if today_pnl <= loss_limit:
        return _block(
            "일일_손실_한도",
            (
                f"1일 손실 한도 초과: 오늘 손익 {today_pnl:+,.0f}원 ({loss_rate:+.2f}%) / "
                f"한도 {max_loss_rate:.1f}% ({loss_limit:,.0f}원). 오늘 추가 주문 불가."
            ),
            today_pnl=today_pnl,
            loss_limit=loss_limit,
            loss_rate=loss_rate,
        )
    return _pass(
        "일일_손실_한도",
        f"1일 손익 정상: {today_pnl:+,.0f}원 ({loss_rate:+.2f}%) / 한도 {max_loss_rate:.1f}%",
        today_pnl=today_pnl,
        loss_limit=loss_limit,
        loss_rate=loss_rate,
    )


def check_news_sentiment(
    sentiment: str | None,
    order_type: str = "매수",
) -> dict[str, Any]:
    """
    ⑨ 뉴스 심리 검사.
    매수 + 부정 → 차단 (신호 생성 단계에서도 이미 차단되지만 이중 방어)
    매도 + 부정 → 통과 (부정 뉴스는 오히려 매도 근거)
    중립/None   → 확인필요 (정보 없음)
    """
    if sentiment is None or sentiment == "":
        return _warn("뉴스_심리", "뉴스 심리 정보가 없습니다. 수동 확인을 권장합니다.")

    if order_type == "매수":
        if sentiment == "부정":
            return _block(
                "뉴스_심리",
                "부정적 뉴스 심리가 감지되었습니다. 매수 신호 차단.",
                sentiment=sentiment,
            )
        if sentiment == "중립":
            return _warn(
                "뉴스_심리",
                "뉴스 심리 중립. 긍정적 뉴스 확인 후 진입을 권장합니다.",
                sentiment=sentiment,
            )
        return _pass("뉴스_심리", f"뉴스 심리: {sentiment}", sentiment=sentiment)

    # 매도 신호 — 부정 뉴스는 매도 근거이므로 통과
    return _pass("뉴스_심리", f"뉴스 심리: {sentiment} (매도)", sentiment=sentiment)


def check_data_quality(data_quality: str | None) -> dict[str, Any]:
    """⑩ 데이터 신뢰도가 낮으면 확인필요. LOW → 확인필요, MEDIUM/HIGH/None → 통과."""
    if str(data_quality or "").upper() == "LOW":
        return _warn(
            "데이터_신뢰도",
            "데이터 신뢰도가 낮습니다(LOW). 수동 확인 후 진행하세요.",
            data_quality=data_quality,
        )
    return _pass(
        "데이터_신뢰도",
        f"데이터 신뢰도: {data_quality or '확인불가'}",
        data_quality=data_quality,
    )


def check_position_amount_limit(order_amount: float) -> dict[str, Any]:
    """⑪ 종목당 최대 투자금(risk_settings.max_position_amount) 초과 검사."""
    risk       = _load_risk_settings()
    max_amount = float(risk["max_position_amount"])
    amount     = float(order_amount)

    if amount > max_amount:
        return _block(
            "종목당_최대_투자금",
            f"종목당 최대 투자금 초과: 주문 {amount:,.0f}원 / 한도 {max_amount:,.0f}원",
            order_amount=amount,
            max_amount=max_amount,
        )
    return _pass(
        "종목당_최대_투자금",
        f"투자금 정상: {amount:,.0f}원 / {max_amount:,.0f}원",
        order_amount=amount,
        max_amount=max_amount,
    )


def check_single_stock_ratio_v4(
    stock_code: str,
    order_amount: float,
    total_portfolio_value: float | None = None,
) -> dict[str, Any]:
    """⑫ 단일 종목 비중 초과 검사."""
    risk      = _load_risk_settings()
    max_ratio = float(risk["max_single_stock_ratio"])

    total_val = total_portfolio_value
    if not total_val or total_val <= 0:
        total_val = _get_total_portfolio_value()

    existing = _get_stock_invested_amount(stock_code)
    after    = existing + float(order_amount)
    ratio    = round(after / total_val * 100, 2) if total_val > 0 else 0.0

    if ratio > max_ratio:
        return _block(
            "단일_종목_비중",
            (
                f"단일 종목 비중 한도 초과: 주문 후 {ratio:.1f}% / 한도 {max_ratio:.0f}% "
                f"(기존 {existing:,.0f}원 + 신규 {order_amount:,.0f}원)"
            ),
            stock_ratio=ratio,
            max_ratio=max_ratio,
            total_value=total_val,
        )
    return _pass(
        "단일_종목_비중",
        f"비중 정상: 주문 후 {ratio:.1f}% / 한도 {max_ratio:.0f}%",
        stock_ratio=ratio,
        max_ratio=max_ratio,
        total_value=total_val,
    )


# ════════════════════════════════════════════════════════════════
# 4차 메인 — 통합 리스크 검사
# ════════════════════════════════════════════════════════════════

def run_full_risk_check(
    stock_code: str,
    order_amount: float,
    order_type: str = "매수",          # 매수 / 매도
    price_type: str = "지정가",        # 지정가 / 시장가
    account_mode: str = "paper",       # mock / paper / real
    news_sentiment: str | None = None, # 긍정 / 중립 / 부정
    data_quality: str | None = None,   # HIGH / MEDIUM / LOW
    total_portfolio_value: float | None = None,
) -> dict[str, Any]:
    """
    4차 통합 리스크 검사.

    Args:
        stock_code:             종목코드
        order_amount:           주문 금액 (원)
        order_type:             '매수' | '매도'
        price_type:             '지정가' | '시장가'
        account_mode:           'mock' | 'paper' | 'real'
        news_sentiment:         '긍정' | '중립' | '부정' | None
        data_quality:           'HIGH' | 'MEDIUM' | 'LOW' | None
        total_portfolio_value:  포트폴리오 총자산 (None이면 자동 조회)

    Returns:
        dict:
            status          "통과" | "차단" | "확인필요"
            message         str   한국어 종합 메시지
            checks          list  개별 검사 결과 전체
            blocked_checks  list  차단 항목만
            warning_checks  list  확인필요 항목만
    """
    code   = str(stock_code).zfill(6)
    is_buy = (order_type == "매수")
    checks: list[dict[str, Any]] = []

    # ── 하드 차단 검사 (순서 중요 — 나머지 검사 이전에 수행) ────────

    # ① 긴급 중지
    checks.append(check_emergency_stop())
    # ② 매매 모드
    checks.append(check_trading_mode())
    # ③ 실거래 차단
    checks.append(check_real_trading_blocked(account_mode))
    # ④ 시장가 주문 차단
    checks.append(check_order_type(price_type))

    # 위 4개에서 하나라도 차단이면 즉시 반환 (의미 없는 나머지 검사 생략)
    early_blocks = [c for c in checks if c["status"] == "차단"]
    if early_blocks:
        return _build_result(checks)

    # ── 수치 한도 검사 ───────────────────────────────────────────────

    # ⑤ 주문 금액 한도 (system_settings)
    checks.append(check_order_amount_limit(order_amount))
    # ⑥ 최대 보유 종목 수 (매수만)
    if is_buy:
        checks.append(check_position_count_limit())
    # ⑦ 동일 종목 중복 주문
    checks.append(check_duplicate_order(code))
    # ⑧ 1일 손실 한도
    checks.append(check_daily_loss_rate())
    # ⑪ 종목당 최대 투자금 (매수만)
    if is_buy:
        checks.append(check_position_amount_limit(order_amount))
    # ⑫ 단일 종목 비중 (매수만)
    if is_buy:
        checks.append(check_single_stock_ratio_v4(code, order_amount, total_portfolio_value))

    # ── 소프트 경고 검사 (확인필요 — 차단하지 않음) ─────────────────

    # ⑨ 뉴스 심리
    checks.append(check_news_sentiment(news_sentiment, order_type))
    # ⑩ 데이터 신뢰도
    checks.append(check_data_quality(data_quality))

    return _build_result(checks)


def _build_result(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """검사 결과 목록에서 최종 status/message를 계산한다."""
    blocked  = [c for c in checks if c["status"] == "차단"]
    warnings = [c for c in checks if c["status"] == "확인필요"]

    if blocked:
        status  = "차단"
        message = " | ".join(c["message"] for c in blocked)
    elif warnings:
        status  = "확인필요"
        message = " | ".join(c["message"] for c in warnings)
    else:
        status  = "통과"
        message = f"전체 {len(checks)}개 검사 통과"

    return {
        "status":         status,
        "message":        message,
        "checks":         checks,
        "blocked_checks": blocked,
        "warning_checks": warnings,
    }


# ════════════════════════════════════════════════════════════════
# 3차 하위 호환 함수 (기존 paper_trading_engine 등과의 호환성 유지)
# ════════════════════════════════════════════════════════════════

def check_max_position_count() -> dict[str, Any]:
    """3차 호환: 최대 보유 종목 수 검사. allowed/message 형식 반환."""
    r = check_position_count_limit()
    return {
        "allowed": r["status"] != "차단",
        "message": r["message"],
        "current_count": r.get("current_count"),
        "max_count":     r.get("max_count"),
    }


def check_max_position_amount(amount: float) -> dict[str, Any]:
    """3차 호환: 종목당 최대 투자금 검사. allowed/message 형식 반환."""
    r = check_position_amount_limit(amount)
    return {
        "allowed":      r["status"] != "차단",
        "message":      r["message"],
        "order_amount": r.get("order_amount"),
        "max_amount":   r.get("max_amount"),
    }


def check_daily_loss_limit() -> dict[str, Any]:
    """3차 호환: 1일 손실 한도 검사. allowed/message 형식 반환."""
    r = check_daily_loss_rate()
    return {
        "allowed":    r["status"] != "차단",
        "message":    r["message"],
        "today_pnl":  r.get("today_pnl"),
        "loss_limit": r.get("loss_limit"),
        "loss_rate":  r.get("loss_rate"),
    }


def check_single_stock_ratio(
    stock_code: str,
    order_amount: float,
    total_portfolio_value: float | None = None,
) -> dict[str, Any]:
    """3차 호환: 단일 종목 비중 검사. allowed/message 형식 반환."""
    r = check_single_stock_ratio_v4(stock_code, order_amount, total_portfolio_value)
    return {
        "allowed":     r["status"] != "차단",
        "message":     r["message"],
        "stock_ratio": r.get("stock_ratio"),
        "max_ratio":   r.get("max_ratio"),
        "total_value": r.get("total_value"),
    }


def can_place_virtual_order(
    stock_code: str,
    order_amount: float,
    total_portfolio_value: float | None = None,
) -> dict[str, Any]:
    """
    3차 호환: 가상 매수 주문 전 통합 리스크 검사.
    내부적으로 run_full_risk_check()를 호출하고 3차 형식으로 변환합니다.

    Returns:
        dict: {"allowed": bool, "message": str, "checks": list}
    """
    result = run_full_risk_check(
        stock_code=stock_code,
        order_amount=order_amount,
        order_type="매수",
        price_type="지정가",
        account_mode="paper",
        total_portfolio_value=total_portfolio_value,
    )
    return {
        "allowed": result["status"] == "통과",
        "message": result["message"],
        "checks":  [
            {"항목": c["name"], "allowed": c["status"] != "차단", "message": c["message"]}
            for c in result["checks"]
        ],
    }
