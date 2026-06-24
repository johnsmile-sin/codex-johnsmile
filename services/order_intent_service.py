"""
services/order_intent_service.py  –  주문 후보(Order Intent) 서비스 (4차)

매매 신호(trade_signals)를 사용자 승인 대기 주문(order_intents)으로 변환합니다.
실제 브로커 전송은 kiwoom_order_bridge.py 에서만 수행하며,
이 서비스는 승인 전 검토 단계까지만 담당합니다.

흐름:
    trade_signals → create_order_intent_from_signal()
                  → run_risk_check()        (risk_check_status 결정)
                  → approve_order_intent()  (approval_status = 승인)
                  → [kiwoom_order_bridge.py 로 전달]

⚠️  안전 원칙:
    - analysis_only 모드에서는 주문 후보를 생성할 수 없습니다.
    - risk_check_status = '차단' 인 주문은 승인할 수 없습니다.
    - emergency_stop 활성 시 생성·승인 모두 차단됩니다.
    - 실거래(real) 주문 후보 생성은 항상 차단됩니다.

공개 함수:
    create_order_intent_from_signal(signal)
    calculate_order_quantity(stock_code, order_price, max_order_amount)
    run_risk_check(order_intent)
    approve_order_intent(order_intent_id)
    reject_order_intent(order_intent_id, reason)
    get_order_intents(status, limit)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════
# 상수
# ════════════════════════════════════════════════════════════════

DATA_DIR    = Path(__file__).resolve().parents[1] / "data"
INTENTS_FILE = DATA_DIR / "order_intents.json"

# 리스크 검사 항목 이름
_RISK_EMERGENCY_STOP    = "긴급_중지_확인"
_RISK_TRADING_MODE      = "매매_모드_확인"
_RISK_ORDER_AMOUNT      = "주문_금액_한도"
_RISK_POSITION_COUNT    = "최대_포지션_수"
_RISK_DUPLICATE_INTENT  = "중복_주문_확인"
_RISK_DUPLICATE_HOLDING = "보유_종목_중복"


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


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _load_intents_from_file() -> list[dict]:
    if not INTENTS_FILE.exists():
        return []
    try:
        return json.loads(INTENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_intents_to_file(intents: list[dict]) -> None:
    _ensure_data_dir()
    INTENTS_FILE.write_text(
        json.dumps(intents, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _get_intent_by_id(intent_id: int) -> dict | None:
    """Supabase 또는 로컬에서 단일 order_intent를 조회한다."""
    if _supabase_connected():
        try:
            rows = (
                _supabase_client()
                .table("order_intents")
                .select("*")
                .eq("id", intent_id)
                .limit(1)
                .execute()
                .data or []
            )
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("[OrderIntent] Supabase 단건 조회 실패: %s", e)

    for intent in _load_intents_from_file():
        if intent.get("id") == intent_id:
            return intent
    return None


def _update_intent_in_file(intent_id: int, updates: dict) -> bool:
    intents = _load_intents_from_file()
    updated = False
    for item in intents:
        if item.get("id") == intent_id:
            item.update(updates)
            updated = True
            break
    if updated:
        _save_intents_to_file(intents)
    return updated


def _get_system_settings() -> dict:
    try:
        from services.system_settings import get_system_settings
        return get_system_settings()
    except Exception:
        return {
            "trading_mode":            "analysis_only",
            "allow_real_trading":      False,
            "require_manual_approval": True,
            "emergency_stop":          False,
            "max_order_amount":        1_000_000,
            "max_position_count":      5,
        }


def _get_held_codes() -> set[str]:
    """현재 보유 중인 종목코드 집합 (가상 + 키움 합산)."""
    codes: set[str] = set()
    try:
        from services.virtual_position import get_positions
        for p in get_positions(status="보유"):
            codes.add(str(p.get("stock_code", "")).zfill(6))
    except Exception:
        pass
    try:
        from services.kiwoom_data import get_positions as kp
        for p in kp():
            codes.add(str(p.get("stock_code", "")).zfill(6))
    except Exception:
        pass
    return codes


def _get_pending_intent_codes() -> set[str]:
    """현재 승인대기 상태인 주문 후보의 종목코드 집합."""
    try:
        pending = get_order_intents(status="승인대기", limit=200)
        return {str(i.get("stock_code", "")).zfill(6) for i in pending}
    except Exception:
        return set()


def _count_held_positions() -> int:
    """현재 보유 포지션 수 (가상 + 키움)."""
    return len(_get_held_codes())


def _update_signal_status_to_candidate(signal_id: int | None) -> None:
    """trade_signals 의 status를 '주문후보생성' 으로 변경한다."""
    if signal_id is None:
        return
    try:
        from strategy.signal_generator import update_signal_status
        update_signal_status(signal_id, "주문후보생성")
    except Exception as e:
        logger.warning("[OrderIntent] 신호 상태 업데이트 실패: %s", e)


# ════════════════════════════════════════════════════════════════
# 공개 함수 1 — 주문 수량 계산
# ════════════════════════════════════════════════════════════════

def calculate_order_quantity(
    stock_code: str,
    order_price: int,
    max_order_amount: int | None = None,
) -> dict[str, Any]:
    """
    주문 가능 수량을 계산합니다.

    Args:
        stock_code:       종목코드 (로깅용)
        order_price:      주문 단가 (원)
        max_order_amount: 1회 최대 주문 금액 (None이면 system_settings 에서 읽음)

    Returns:
        dict:
            quantity     int   계산된 수량
            order_amount int   실제 주문 금액
            order_price  int   입력된 주문 단가
            max_amount   int   적용된 한도
    """
    if max_order_amount is None:
        settings = _get_system_settings()
        max_order_amount = _safe_int(settings.get("max_order_amount"), 1_000_000)

    order_price = _safe_int(order_price)
    if order_price <= 0:
        logger.warning("[OrderIntent] 주문 단가 0 이하: %s", stock_code)
        return {"quantity": 0, "order_amount": 0, "order_price": 0, "max_amount": max_order_amount}

    quantity     = max(1, max_order_amount // order_price)
    order_amount = quantity * order_price

    return {
        "quantity":     quantity,
        "order_amount": order_amount,
        "order_price":  order_price,
        "max_amount":   max_order_amount,
    }


# ════════════════════════════════════════════════════════════════
# 공개 함수 2 — 리스크 검사
# ════════════════════════════════════════════════════════════════

def run_risk_check(order_intent: dict[str, Any]) -> dict[str, Any]:
    """
    주문 후보에 대해 리스크 검사를 수행합니다.

    검사 항목:
        ① 긴급 중지 활성 여부
        ② 매매 모드 (analysis_only 차단)
        ③ 주문 금액 한도 초과 여부
        ④ 최대 포지션 수 초과 여부 (매수 신호만)
        ⑤ 동일 종목 중복 주문 후보 존재 여부
        ⑥ 동일 종목 이미 보유 여부 (매수 신호만)

    Args:
        order_intent: create_order_intent_from_signal() 반환값 또는 order_intents 행 dict

    Returns:
        dict:
            status   str   '통과' | '차단' | '확인필요'
            message  str   종합 메시지
            checks   list  개별 검사 결과 목록
    """
    settings     = _get_system_settings()
    stock_code   = str(order_intent.get("stock_code", "")).zfill(6)
    order_type   = order_intent.get("order_type", "매수")
    order_amount = _safe_int(order_intent.get("order_amount"))
    is_buy       = (order_type == "매수")

    checks: list[dict] = []
    blocked = False

    # ① 긴급 중지
    if settings.get("emergency_stop", False):
        checks.append({
            "name":    _RISK_EMERGENCY_STOP,
            "passed":  False,
            "message": "긴급 중지가 활성화되어 있습니다.",
        })
        blocked = True
    else:
        checks.append({"name": _RISK_EMERGENCY_STOP, "passed": True, "message": "정상"})

    # ② 매매 모드
    trading_mode = settings.get("trading_mode", "analysis_only")
    if trading_mode == "analysis_only":
        checks.append({
            "name":    _RISK_TRADING_MODE,
            "passed":  False,
            "message": "분석 전용 모드(analysis_only)에서는 주문 후보를 생성할 수 없습니다.",
        })
        blocked = True
    else:
        checks.append({
            "name":    _RISK_TRADING_MODE,
            "passed":  True,
            "message": f"매매 모드: {trading_mode}",
        })

    # ③ 주문 금액 한도
    max_amount = _safe_int(settings.get("max_order_amount"), 1_000_000)
    if order_amount > max_amount:
        checks.append({
            "name":    _RISK_ORDER_AMOUNT,
            "passed":  False,
            "message": (
                f"주문 금액 {order_amount:,}원이 한도 {max_amount:,}원을 초과합니다."
            ),
        })
        blocked = True
    else:
        checks.append({
            "name":    _RISK_ORDER_AMOUNT,
            "passed":  True,
            "message": f"주문 금액 {order_amount:,}원 ≤ 한도 {max_amount:,}원",
        })

    # ④ 최대 포지션 수 (매수만)
    if is_buy:
        max_pos  = _safe_int(settings.get("max_position_count"), 5)
        held_cnt = _count_held_positions()
        if held_cnt >= max_pos:
            checks.append({
                "name":    _RISK_POSITION_COUNT,
                "passed":  False,
                "message": (
                    f"현재 보유 포지션 {held_cnt}개가 최대 {max_pos}개에 도달했습니다."
                ),
            })
            blocked = True
        else:
            checks.append({
                "name":    _RISK_POSITION_COUNT,
                "passed":  True,
                "message": f"보유 {held_cnt}개 / 최대 {max_pos}개",
            })

    # ⑤ 중복 주문 후보
    pending_codes = _get_pending_intent_codes()
    if stock_code in pending_codes:
        checks.append({
            "name":    _RISK_DUPLICATE_INTENT,
            "passed":  False,
            "message": f"{stock_code} 에 대한 승인대기 주문이 이미 존재합니다.",
        })
        blocked = True
    else:
        checks.append({"name": _RISK_DUPLICATE_INTENT, "passed": True, "message": "중복 없음"})

    # ⑥ 보유 종목 중복 (매수만)
    if is_buy:
        held_codes = _get_held_codes()
        if stock_code in held_codes:
            checks.append({
                "name":    _RISK_DUPLICATE_HOLDING,
                "passed":  False,
                "message": f"{stock_code} 은(는) 이미 보유 중입니다.",
            })
            blocked = True
        else:
            checks.append({
                "name":    _RISK_DUPLICATE_HOLDING,
                "passed":  True,
                "message": "미보유 종목",
            })

    # 결과 집계
    failed = [c for c in checks if not c["passed"]]
    if blocked:
        status  = "차단"
        message = " | ".join(c["message"] for c in failed)
    elif failed:
        status  = "확인필요"
        message = " | ".join(c["message"] for c in failed)
    else:
        status  = "통과"
        message = f"전체 {len(checks)}개 항목 통과"

    return {"status": status, "message": message, "checks": checks}


# ════════════════════════════════════════════════════════════════
# 공개 함수 3 — 주문 후보 생성
# ════════════════════════════════════════════════════════════════

def create_order_intent_from_signal(signal: dict[str, Any]) -> dict[str, Any]:
    """
    trade_signals 신호로부터 order_intents 행을 생성합니다.

    생성 흐름:
        1. 시스템 설정 사전 검사 (긴급 중지·모드)
        2. 주문 수량 계산
        3. 리스크 검사
        4. order_intents 저장
        5. trade_signals 상태 → '주문후보생성' 업데이트

    Args:
        signal: trade_signals 행 dict
                (signal_type, signal_price, stock_code, stock_name, strategy_name, id 필수)

    Returns:
        dict:
            success      bool
            message      str
            order_intent dict | None   저장된 order_intent (실패 시 None)
    """
    settings = _get_system_settings()

    # ── 사전 검사 (리스크 검사보다 먼저) ────────────────────────
    if settings.get("emergency_stop", False):
        return {
            "success":     False,
            "message":     "긴급 중지 활성화 상태입니다. 주문 후보를 생성할 수 없습니다.",
            "order_intent": None,
        }

    trading_mode = settings.get("trading_mode", "analysis_only")
    if trading_mode == "analysis_only":
        return {
            "success":     False,
            "message":     "분석 전용(analysis_only) 모드입니다. '모의투자' 모드로 전환 후 시도하세요.",
            "order_intent": None,
        }

    # ── 신호 필드 추출 ─────────────────────────────────────────
    signal_id    = signal.get("id")
    stock_code   = str(signal.get("stock_code", "")).zfill(6)
    stock_name   = str(signal.get("stock_name", "") or "")
    strategy     = str(signal.get("strategy_name", "") or "")
    signal_type  = str(signal.get("signal_type", ""))
    signal_price = _safe_int(signal.get("signal_price"))

    if signal_type == "매수신호":
        order_type = "매수"
    elif signal_type == "매도신호":
        order_type = "매도"
    else:
        return {
            "success":     False,
            "message":     f"알 수 없는 signal_type: '{signal_type}'",
            "order_intent": None,
        }

    if not stock_code or stock_code == "000000":
        return {"success": False, "message": "유효하지 않은 종목코드", "order_intent": None}

    if signal_price <= 0:
        return {"success": False, "message": f"유효하지 않은 신호 가격: {signal_price}", "order_intent": None}

    # ── 수량 계산 ────────────────────────────────────────────────
    qty_result   = calculate_order_quantity(stock_code, signal_price)
    quantity     = qty_result["quantity"]
    order_amount = qty_result["order_amount"]

    if quantity <= 0:
        return {
            "success":     False,
            "message":     f"계산된 주문 수량이 0입니다. (가격: {signal_price:,}원)",
            "order_intent": None,
        }

    # ── 임시 intent dict 구성 → 리스크 검사 ──────────────────────
    intent_draft: dict[str, Any] = {
        "signal_id":          signal_id,
        "stock_code":         stock_code,
        "stock_name":         stock_name,
        "strategy_name":      strategy,
        "order_type":         order_type,
        "order_price":        signal_price,
        "quantity":           quantity,
        "order_amount":       order_amount,
        "approval_status":    "승인대기",
        "risk_check_status":  "확인필요",
        "risk_check_message": None,
    }

    risk_result = run_risk_check(intent_draft)
    intent_draft["risk_check_status"]  = risk_result["status"]
    intent_draft["risk_check_message"] = risk_result["message"]

    # ── 저장 ─────────────────────────────────────────────────────
    saved = _save_order_intent(intent_draft)
    if saved is None:
        return {
            "success":      False,
            "message":      "주문 후보 저장에 실패했습니다.",
            "order_intent": None,
        }

    # ── 신호 상태 업데이트 ─────────────────────────────────────
    _update_signal_status_to_candidate(signal_id)

    risk_label = risk_result["status"]
    logger.info(
        "[OrderIntent] 생성 완료: %s %s %d주 @%s원 (리스크: %s)",
        order_type, stock_code, quantity, f"{signal_price:,}", risk_label,
    )
    return {
        "success":      True,
        "message":      f"주문 후보 생성 완료 (리스크 검사: {risk_label})",
        "order_intent": saved,
    }


def _save_order_intent(intent: dict[str, Any]) -> dict[str, Any] | None:
    """order_intent를 Supabase 또는 로컬 JSON에 저장한다."""
    if _supabase_connected():
        try:
            payload = {k: v for k, v in intent.items() if k not in ("id", "created_at")}
            resp = (
                _supabase_client()
                .table("order_intents")
                .insert(payload)
                .execute()
            )
            rows = resp.data or []
            if rows:
                return rows[0]
        except Exception as e:
            logger.warning("[OrderIntent] Supabase 저장 실패: %s → 로컬 저장", e)

    # 로컬 JSON 폴백
    _ensure_data_dir()
    all_intents = _load_intents_from_file()
    next_id     = max((i.get("id", 0) for i in all_intents), default=0) + 1
    saved       = dict(intent)
    saved["id"]         = next_id
    saved["created_at"] = _now()
    all_intents.append(saved)
    try:
        _save_intents_to_file(all_intents)
        return saved
    except Exception as e:
        logger.error("[OrderIntent] 로컬 저장 실패: %s", e)
        return None


# ════════════════════════════════════════════════════════════════
# 공개 함수 4 — 승인
# ════════════════════════════════════════════════════════════════

def approve_order_intent(order_intent_id: int) -> dict[str, Any]:
    """
    주문 후보를 승인합니다.

    차단 조건:
        - approval_status 가 '승인대기' 가 아닌 경우
        - risk_check_status 가 '차단' 인 경우

    Args:
        order_intent_id: order_intents.id

    Returns:
        dict: {"success": bool, "message": str, "order_intent": dict | None}
    """
    intent = _get_intent_by_id(order_intent_id)
    if intent is None:
        return {
            "success":      False,
            "message":      f"주문 후보 ID {order_intent_id} 를 찾을 수 없습니다.",
            "order_intent": None,
        }

    approval_status   = intent.get("approval_status", "")
    risk_check_status = intent.get("risk_check_status", "")

    if approval_status != "승인대기":
        return {
            "success":      False,
            "message":      f"현재 상태({approval_status})에서는 승인할 수 없습니다.",
            "order_intent": intent,
        }

    if risk_check_status == "차단":
        return {
            "success":      False,
            "message":      (
                f"리스크 검사 차단 상태입니다. 승인 불가. "
                f"사유: {intent.get('risk_check_message', '')}"
            ),
            "order_intent": intent,
        }

    now     = _now()
    updates = {"approval_status": "승인", "approved_at": now}

    if _supabase_connected():
        try:
            (
                _supabase_client()
                .table("order_intents")
                .update(updates)
                .eq("id", order_intent_id)
                .execute()
            )
        except Exception as e:
            logger.warning("[OrderIntent] Supabase 승인 업데이트 실패: %s", e)

    _update_intent_in_file(order_intent_id, updates)

    updated = dict(intent)
    updated.update(updates)
    logger.info(
        "[OrderIntent] 승인 완료: ID=%d %s %s",
        order_intent_id, intent.get("order_type"), intent.get("stock_code"),
    )
    return {"success": True, "message": "주문 후보가 승인되었습니다.", "order_intent": updated}


# ════════════════════════════════════════════════════════════════
# 공개 함수 5 — 거절
# ════════════════════════════════════════════════════════════════

def reject_order_intent(order_intent_id: int, reason: str = "") -> dict[str, Any]:
    """
    주문 후보를 거절합니다.

    Args:
        order_intent_id: order_intents.id
        reason:          거절 사유 (risk_check_message 에 추가 기록)

    Returns:
        dict: {"success": bool, "message": str, "order_intent": dict | None}
    """
    intent = _get_intent_by_id(order_intent_id)
    if intent is None:
        return {
            "success":      False,
            "message":      f"주문 후보 ID {order_intent_id} 를 찾을 수 없습니다.",
            "order_intent": None,
        }

    if intent.get("approval_status") in ("승인", "거절", "만료"):
        return {
            "success":      False,
            "message":      f"이미 처리된 주문입니다 (상태: {intent.get('approval_status')}).",
            "order_intent": intent,
        }

    now             = _now()
    prev_risk_msg   = intent.get("risk_check_message") or ""
    new_risk_msg    = f"[거절] {reason}" if reason else "[사용자 거절]"
    if prev_risk_msg:
        new_risk_msg = f"{prev_risk_msg} | {new_risk_msg}"

    updates = {
        "approval_status":    "거절",
        "rejected_at":        now,
        "risk_check_message": new_risk_msg,
    }

    if _supabase_connected():
        try:
            (
                _supabase_client()
                .table("order_intents")
                .update(updates)
                .eq("id", order_intent_id)
                .execute()
            )
        except Exception as e:
            logger.warning("[OrderIntent] Supabase 거절 업데이트 실패: %s", e)

    _update_intent_in_file(order_intent_id, updates)

    updated = dict(intent)
    updated.update(updates)
    logger.info(
        "[OrderIntent] 거절 완료: ID=%d %s %s / 사유: %s",
        order_intent_id, intent.get("order_type"), intent.get("stock_code"), reason,
    )
    return {"success": True, "message": "주문 후보가 거절되었습니다.", "order_intent": updated}


# ════════════════════════════════════════════════════════════════
# 공개 함수 6 — 조회
# ════════════════════════════════════════════════════════════════

def get_order_intents(
    status: str | None = None,
    order_type: str | None = None,
    stock_code: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    저장된 주문 후보를 조회합니다.

    Args:
        status:     '승인대기' | '승인' | '거절' | '만료' | None(전체)
        order_type: '매수' | '매도' | None(전체)
        stock_code: 종목코드 필터 (None 이면 전체)
        limit:      최대 반환 건수 (기본 100)

    Returns:
        list[dict]: 주문 후보 목록 (최신순)
    """
    if _supabase_connected():
        try:
            q = (
                _supabase_client()
                .table("order_intents")
                .select("*")
                .order("created_at", desc=True)
                .limit(limit)
            )
            if status:
                q = q.eq("approval_status", status)
            if order_type:
                q = q.eq("order_type", order_type)
            if stock_code:
                q = q.eq("stock_code", stock_code.zfill(6))
            return q.execute().data or []
        except Exception as e:
            logger.warning("[OrderIntent] Supabase 조회 실패: %s → 로컬 조회", e)

    result = _load_intents_from_file()
    if status:
        result = [i for i in result if i.get("approval_status") == status]
    if order_type:
        result = [i for i in result if i.get("order_type") == order_type]
    if stock_code:
        target = stock_code.zfill(6)
        result = [i for i in result if str(i.get("stock_code", "")).zfill(6) == target]

    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return result[:limit]


# ════════════════════════════════════════════════════════════════
# 편의 함수 — 만료 처리
# ════════════════════════════════════════════════════════════════

def expire_old_intents(older_than_days: int = 1) -> int:
    """
    오래된 '승인대기' 주문 후보를 '만료' 로 일괄 변경합니다.

    Args:
        older_than_days: 며칠 이전 주문을 만료 처리할지 (기본 1일)

    Returns:
        int: 만료 처리된 건수
    """
    from datetime import timedelta, date
    cutoff = (date.today() - timedelta(days=older_than_days)).isoformat()
    expired = 0

    if _supabase_connected():
        try:
            resp = (
                _supabase_client()
                .table("order_intents")
                .update({"approval_status": "만료"})
                .eq("approval_status", "승인대기")
                .lt("created_at", cutoff)
                .execute()
            )
            expired = len(resp.data or [])
            logger.info("[OrderIntent] Supabase 만료 처리: %d건", expired)
            return expired
        except Exception as e:
            logger.warning("[OrderIntent] Supabase 만료 처리 실패: %s → 로컬 처리", e)

    intents = _load_intents_from_file()
    for item in intents:
        if (
            item.get("approval_status") == "승인대기"
            and str(item.get("created_at", "")) < cutoff
        ):
            item["approval_status"] = "만료"
            expired += 1

    if expired:
        _save_intents_to_file(intents)
        logger.info("[OrderIntent] 로컬 만료 처리: %d건", expired)

    return expired
