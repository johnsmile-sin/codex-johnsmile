"""
services/kiwoom_order.py  –  키움 모의투자 주문 Client (4차)

승인된 주문 후보(order_intents)를 키움 모의투자 API로 전송하고
결과를 broker_orders / order_execution_logs에 저장합니다.

⚠️  안전 원칙:
    - 실거래(real) 주문 함수는 구현하지 않습니다.
    - account_mode = 'paper' | 'mock' 만 허용합니다.
    - emergency_stop 활성 → 전송 차단
    - require_manual_approval=True → approval_status='승인' 이 아니면 차단
    - risk_check_status='차단' → 전송 차단
    - API 키 없음 → Mock 성공 응답 반환

TODO 섹션:
    _call_paper_order_api() 내부에 실제 API 호출을 구현합니다.
    _call_cancel_api()      내부에 실제 취소 API를 구현합니다.
    _query_order_api()      내부에 실제 상태 조회 API를 구현합니다.

공개 함수:
    send_paper_buy_order(order_intent)
    send_paper_sell_order(order_intent)
    get_paper_order_status(internal_broker_order_id)
    cancel_paper_order(internal_broker_order_id)
"""

from __future__ import annotations

import json
import logging
import random
import string
from datetime import datetime
from pathlib import Path
from typing import Any

from config import (
    ALLOW_REAL_TRADING,
    KIWOOM_APP_KEY,
    KIWOOM_MOCK_ACCOUNT_NO,
    KIWOOM_INVEST_MODE,
    REQUIRE_MANUAL_APPROVAL,
)

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════
# 상수
# ════════════════════════════════════════════════════════════════

DATA_DIR             = Path(__file__).resolve().parents[1] / "data"
BROKER_ORDERS_FILE   = DATA_DIR / "broker_orders.json"
EXEC_LOGS_FILE       = DATA_DIR / "order_execution_logs.json"

_BASE_URL_PAPER = "https://openapivts.koreainvestment.com:29443"  # 모의투자 전용
_TIMEOUT        = 10   # 초

# 모의투자 주문 TR 코드 (V 접두사 = 모의투자)
_TR_BUY     = "VTTC0802U"   # 주식 현금 매수 주문
_TR_SELL    = "VTTC0801U"   # 주식 현금 매도 주문
_TR_CANCEL  = "VTTC0803U"   # 주식 취소 주문
_TR_HISTORY = "VTTC8001R"   # 당일 주문 내역 조회 (kiwoom_data.py 와 공유)

# 지정가 주문 구분 코드 (00 = 지정가)
_ORD_DVSN_LIMIT = "00"

# 취소 주문 구분 코드 (02 = 취소)
_RVSE_CNCL_DVSN_CANCEL = "02"

# broker_orders.order_status 값
_STATUS_PENDING   = "전송대기"
_STATUS_SENT      = "전송완료"
_STATUS_CANCELLED = "취소"
_STATUS_FAILED    = "실패"

# order_execution_logs.event_type 값
_EVT_SEND_ATTEMPT = "SEND_ATTEMPT"
_EVT_ORDER_SENT   = "ORDER_SENT"
_EVT_ORDER_FAILED = "ORDER_FAILED"
_EVT_SEND_BLOCKED = "SEND_BLOCKED"
_EVT_CANCEL_SENT  = "CANCEL_SENT"
_EVT_CANCEL_FAILED = "CANCEL_FAILED"
_EVT_STATUS_QUERY = "STATUS_QUERY"


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼 — 공통
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
        return int(str(val).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _mask_account(account_no: str | None) -> str:
    if not account_no:
        return "(없음)"
    s = str(account_no)
    return s[:4] + "*" * (len(s) - 4) if len(s) > 4 else "****"


def _account_no() -> str:
    """모의투자 계좌번호. 실계좌는 절대 사용하지 않는다."""
    return str(KIWOOM_MOCK_ACCOUNT_NO or "")


def _is_paper_available() -> bool:
    """실제 Kiwoom 모의투자 API 사용 가능 여부."""
    return bool(KIWOOM_INVEST_MODE == "paper" and KIWOOM_APP_KEY)


def _mock_order_no() -> str:
    """Mock 주문번호 생성 (M + 숫자 8자리)."""
    return "M" + "".join(random.choices(string.digits, k=8))


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼 — 안전 검사
# ════════════════════════════════════════════════════════════════

def _check_send_safety(order_intent: dict[str, Any]) -> dict[str, Any] | None:
    """
    전송 전 안전 검사. 문제가 있으면 에러 dict 반환, 통과하면 None.

    검사 순서:
        ① emergency_stop 활성
        ② allow_real_trading = False 강제
        ③ account_mode ≠ real
        ④ approval_status = 승인 (require_manual_approval=True 일 때)
        ⑤ risk_check_status ≠ 차단
    """
    # ① 긴급 중지
    try:
        from services.system_settings import get_system_settings
        sys = get_system_settings()
        if sys.get("emergency_stop", False):
            return _err("긴급 중지가 활성화되어 있습니다. 주문 전송이 차단됩니다.")
        require_approval = bool(sys.get("require_manual_approval", True))
    except Exception:
        require_approval = REQUIRE_MANUAL_APPROVAL

    # ② 실거래 하드 차단
    if ALLOW_REAL_TRADING:
        return _err("allow_real_trading=True 는 이 서비스에서 지원하지 않습니다.")

    # ③ account_mode 검사
    account_mode = str(order_intent.get("account_mode", "paper")).lower()
    if account_mode == "real":
        return _err("실거래(real) 주문은 영구적으로 차단됩니다.")
    if account_mode not in ("paper", "mock"):
        return _err(f"지원하지 않는 account_mode: '{account_mode}'")

    # ④ 수동 승인 검사
    if require_approval:
        if order_intent.get("approval_status") != "승인":
            current = order_intent.get("approval_status", "알 수 없음")
            return _err(
                f"수동 승인 필수 모드입니다. 현재 승인 상태: '{current}'. "
                f"먼저 approve_order_intent()를 호출하세요."
            )

    # ⑤ 리스크 차단 상태
    if order_intent.get("risk_check_status") == "차단":
        msg = order_intent.get("risk_check_message", "")
        return _err(f"리스크 검사 차단 상태입니다. 전송 불가. 사유: {msg}")

    return None


def _err(message: str) -> dict[str, Any]:
    return {"success": False, "message": message, "broker_order": None}


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼 — broker_orders 저장
# ════════════════════════════════════════════════════════════════

def _save_broker_order(record: dict[str, Any]) -> dict[str, Any] | None:
    """broker_orders 테이블 또는 로컬 JSON에 저장한다."""
    if _supabase_connected():
        try:
            payload = {k: v for k, v in record.items() if k not in ("id",)}
            resp    = _supabase_client().table("broker_orders").insert(payload).execute()
            rows    = resp.data or []
            if rows:
                return rows[0]
        except Exception as e:
            logger.warning("[KiwoomOrder] broker_orders Supabase 저장 실패: %s", e)

    _ensure_data_dir()
    all_rows = _load_file(BROKER_ORDERS_FILE)
    next_id  = max((r.get("id", 0) for r in all_rows), default=0) + 1
    saved    = dict(record)
    saved["id"]         = next_id
    saved["updated_at"] = _now()
    all_rows.append(saved)
    _save_file(BROKER_ORDERS_FILE, all_rows)
    return saved


def _update_broker_order(internal_id: int, updates: dict[str, Any]) -> None:
    """broker_orders 행을 업데이트한다."""
    updates["updated_at"] = _now()

    if _supabase_connected():
        try:
            _supabase_client().table("broker_orders").update(updates).eq("id", internal_id).execute()
        except Exception as e:
            logger.warning("[KiwoomOrder] broker_orders 업데이트 실패: %s", e)

    rows = _load_file(BROKER_ORDERS_FILE)
    for row in rows:
        if row.get("id") == internal_id:
            row.update(updates)
            break
    _save_file(BROKER_ORDERS_FILE, rows)


def _get_broker_order(internal_id: int) -> dict[str, Any] | None:
    """내부 ID로 broker_orders 행을 조회한다."""
    if _supabase_connected():
        try:
            rows = (
                _supabase_client()
                .table("broker_orders")
                .select("*")
                .eq("id", internal_id)
                .limit(1)
                .execute()
                .data or []
            )
            if rows:
                return rows[0]
        except Exception as e:
            logger.warning("[KiwoomOrder] broker_orders 조회 실패: %s", e)

    for row in _load_file(BROKER_ORDERS_FILE):
        if row.get("id") == internal_id:
            return row
    return None


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼 — order_execution_logs 저장
# ════════════════════════════════════════════════════════════════

def _log_execution(
    event_type:         str,
    message:            str,
    order_intent_id:    int | None = None,
    broker_order_id:    int | None = None,
    external_order_id:  str | None = None,
    raw_response:       dict | None = None,
) -> None:
    """order_execution_logs에 이벤트를 기록한다. 실패해도 예외를 전파하지 않는다."""
    record: dict[str, Any] = {
        "order_intent_id":   order_intent_id,
        "broker_order_id":   broker_order_id,
        "external_order_id": external_order_id,
        "event_type":        event_type,
        "message":           message,
        "raw_response":      raw_response,
        "created_at":        _now(),
    }

    if _supabase_connected():
        try:
            _supabase_client().table("order_execution_logs").insert(record).execute()
            return
        except Exception as e:
            logger.warning("[KiwoomOrder] execution_log Supabase 저장 실패: %s", e)

    _ensure_data_dir()
    all_logs = _load_file(EXEC_LOGS_FILE)
    record["id"] = max((r.get("id", 0) for r in all_logs), default=0) + 1
    all_logs.append(record)
    _save_file(EXEC_LOGS_FILE, all_logs)


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼 — 로컬 JSON
# ════════════════════════════════════════════════════════════════

def _load_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_file(path: Path, data: list[dict]) -> None:
    _ensure_data_dir()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ════════════════════════════════════════════════════════════════
# TODO 섹션 — 실제 Kiwoom API 호출 (현재: Mock 응답 반환)
# ════════════════════════════════════════════════════════════════

def _call_paper_order_api(
    tr_id:      str,
    stock_code: str,
    quantity:   int,
    price:      int,
) -> dict[str, Any]:
    """
    키움 모의투자 주문 API 호출.
    API 키 없음 → Mock 응답 반환.

    # ──────────────────────────────────────────────────────────────
    # TODO: 실제 API 구현 (KIWOOM_INVEST_MODE=paper 이고 키 있을 때만)
    #
    # import requests
    # from services.kiwoom_data import get_access_token
    #
    # token = get_access_token()
    # headers = {
    #     "Content-Type":  "application/json; charset=utf-8",
    #     "authorization": f"Bearer {token}",
    #     "appkey":        KIWOOM_APP_KEY,
    #     "appsecret":     KIWOOM_SECRET_KEY,   # 로그 출력 금지
    #     "tr_id":         tr_id,
    #     "custtype":      "P",
    # }
    # body = {
    #     "CANO":              _account_no()[:8],
    #     "ACNT_PRDT_CD":      "01",
    #     "PDNO":              stock_code,
    #     "ORD_DVSN":          _ORD_DVSN_LIMIT,  # 00 = 지정가
    #     "ORD_QTY":           str(quantity),
    #     "ORD_UNPR":          str(price),
    #     "ORD_SVR_DVSN_CD":   "0",
    # }
    # resp = requests.post(
    #     f"{_BASE_URL_PAPER}/uapi/domestic-stock/v1/trading/order-cash",
    #     headers=headers,
    #     json=body,
    #     timeout=_TIMEOUT,
    # )
    # resp.raise_for_status()
    # return resp.json()
    # ──────────────────────────────────────────────────────────────
    """
    if _is_paper_available():
        # 실제 API 연동 준비 완료 시 위 TODO 블록을 활성화하세요.
        logger.warning("[KiwoomOrder] paper 모드이지만 실제 API 호출은 아직 TODO 상태입니다.")

    mock_order_no = _mock_order_no()
    logger.info("[KiwoomOrder] Mock 주문 응답 반환: %s (tr_id=%s)", mock_order_no, tr_id)
    return {
        "rt_cd":  "0",
        "msg_cd": "APPP076",
        "msg1":   "[MOCK] 주문이 완료되었습니다.",
        "output": {
            "KRX_FWDG_ORD_ORGNO": "00000",
            "ORNO":                mock_order_no,
            "ORD_TMD":             datetime.now().strftime("%H%M%S"),
        },
        "_mock": True,
    }


def _call_cancel_api(
    external_order_no: str,
    stock_code:        str,
    quantity:          int,
) -> dict[str, Any]:
    """
    키움 모의투자 취소 주문 API 호출.
    API 키 없음 → Mock 취소 성공 응답.

    # ──────────────────────────────────────────────────────────────
    # TODO: 실제 취소 API 구현
    #
    # headers = {...}  # _call_paper_order_api 참조
    # headers["tr_id"] = _TR_CANCEL
    # body = {
    #     "CANO":               _account_no()[:8],
    #     "ACNT_PRDT_CD":       "01",
    #     "KRX_FWDG_ORD_ORGNO": "00000",
    #     "ORGN_ODNO":          external_order_no,
    #     "ORD_DVSN":           _ORD_DVSN_LIMIT,
    #     "RVSE_CNCL_DVSN_CD":  _RVSE_CNCL_DVSN_CANCEL,  # 02 = 취소
    #     "ORD_QTY":            str(quantity),
    #     "ORD_UNPR":           "0",
    #     "QTY_ALL_ORD_YN":     "Y",
    # }
    # resp = requests.post(...)
    # ──────────────────────────────────────────────────────────────
    """
    logger.info("[KiwoomOrder] Mock 취소 응답 반환: 원주문=%s", external_order_no)
    return {
        "rt_cd":  "0",
        "msg_cd": "APPP076",
        "msg1":   "[MOCK] 취소 주문이 완료되었습니다.",
        "output": {
            "KRX_FWDG_ORD_ORGNO": "00000",
            "ORNO":                _mock_order_no(),
            "ORGN_ODNO":           external_order_no,
        },
        "_mock": True,
    }


def _query_order_api(external_order_no: str) -> dict[str, Any]:
    """
    키움 모의투자 주문 상태 조회 API 호출.
    API 키 없음 → Mock 상태 응답.

    # ──────────────────────────────────────────────────────────────
    # TODO: kiwoom_data.get_order_history() 결과에서 해당 주문 필터링
    #       또는 별도 TR 코드로 단건 조회
    # ──────────────────────────────────────────────────────────────
    """
    logger.info("[KiwoomOrder] Mock 상태 조회 응답: %s", external_order_no)
    return {
        "rt_cd": "0",
        "msg1":  "[MOCK] 주문 조회 완료",
        "output": [{
            "ODNO":        external_order_no,
            "ORD_STTS":    "접수",        # 전송완료 상태
            "TOT_CCLD_QTY": "0",          # 체결 수량
            "AVG_PRVS":    "0",           # 평균 체결가
        }],
        "_mock": True,
    }


# ════════════════════════════════════════════════════════════════
# 내부 핵심 — 공통 주문 전송 로직
# ════════════════════════════════════════════════════════════════

def _send_order(
    order_intent: dict[str, Any],
    order_type:   str,   # '매수' | '매도'
    tr_id:        str,   # _TR_BUY | _TR_SELL
) -> dict[str, Any]:
    """
    매수/매도 공통 전송 로직.
    안전 검사 → broker_order 생성 → API 호출 → 결과 저장.
    """
    # ── 안전 검사 ────────────────────────────────────────────────
    err = _check_send_safety(order_intent)
    if err:
        _log_execution(
            event_type=_EVT_SEND_BLOCKED,
            message=f"{order_type} 주문 전송 차단: {err.get('message', '')}",
            order_intent_id=order_intent.get("id"),
        )
        return err

    intent_id    = order_intent.get("id")
    stock_code   = str(order_intent.get("stock_code", "")).zfill(6)
    stock_name   = str(order_intent.get("stock_name", "") or "")
    order_price  = _safe_int(order_intent.get("order_price"))
    quantity     = _safe_int(order_intent.get("quantity"))
    strategy     = str(order_intent.get("strategy_name", "") or "")
    account_mode = str(order_intent.get("account_mode", KIWOOM_INVEST_MODE)).lower()

    if not stock_code or stock_code == "000000":
        return _err("유효하지 않은 종목코드")
    if order_price <= 0 or quantity <= 0:
        return _err(f"주문 가격({order_price}) 또는 수량({quantity})이 유효하지 않습니다.")

    logger.info(
        "[KiwoomOrder] %s 주문 전송 시작: %s %d주 @%s원 [%s]",
        order_type, stock_code, quantity, f"{order_price:,}", _mask_account(_account_no()),
    )

    # ── broker_order 생성 (전송대기) ─────────────────────────────
    broker_record: dict[str, Any] = {
        "order_intent_id": intent_id,
        "broker_name":     "키움증권",
        "account_mode":    account_mode if account_mode != "real" else "mock",
        "broker_order_id": None,
        "stock_code":      stock_code,
        "stock_name":      stock_name,
        "order_type":      order_type,
        "order_price":     order_price,
        "quantity":        quantity,
        "order_status":    _STATUS_PENDING,
        "filled_quantity": 0,
        "avg_fill_price":  0,
        "sent_at":         None,
    }
    broker_order = _save_broker_order(broker_record)
    if broker_order is None:
        return _err("broker_orders 저장 실패")

    bo_id = broker_order.get("id")

    # ── 전송 시도 로그 ────────────────────────────────────────────
    _log_execution(
        event_type="SEND_ATTEMPT",
        message=f"{order_type} 주문 전송 시도: {stock_code} {quantity}주 @{order_price:,}원",
        order_intent_id=intent_id,
        broker_order_id=bo_id,
    )

    # ── 실제 API 호출 ─────────────────────────────────────────────
    try:
        api_resp = _call_paper_order_api(tr_id, stock_code, quantity, order_price)
    except Exception as e:
        logger.error("[KiwoomOrder] API 호출 예외: %s", e)
        _update_broker_order(bo_id, {"order_status": _STATUS_FAILED})
        _log_execution(
            event_type=_EVT_ORDER_FAILED,
            message=f"API 호출 실패: {e}",
            order_intent_id=intent_id,
            broker_order_id=bo_id,
        )
        return _err(f"API 호출 실패: {e}")

    rt_cd          = str(api_resp.get("rt_cd", "1"))
    is_mock        = api_resp.get("_mock", False)
    external_order = api_resp.get("output", {}).get("ORNO", "")

    # ── 성공 처리 ─────────────────────────────────────────────────
    if rt_cd == "0":
        sent_at = _now()
        _update_broker_order(bo_id, {
            "order_status":    _STATUS_SENT,
            "broker_order_id": external_order,
            "sent_at":         sent_at,
        })
        _log_execution(
            event_type=_EVT_ORDER_SENT,
            message=(
                f"{'[MOCK] ' if is_mock else ''}{order_type} 주문 전송 완료: "
                f"{stock_code} {quantity}주 @{order_price:,}원 / 주문번호={external_order}"
            ),
            order_intent_id=intent_id,
            broker_order_id=bo_id,
            external_order_id=external_order,
            raw_response={k: v for k, v in api_resp.items() if k != "_mock"},
        )

        broker_order["order_status"]    = _STATUS_SENT
        broker_order["broker_order_id"] = external_order
        broker_order["sent_at"]         = sent_at

        logger.info(
            "[KiwoomOrder] %s 완료: %s / 주문번호=%s%s",
            order_type, stock_code, external_order, " (MOCK)" if is_mock else "",
        )
        return {
            "success":      True,
            "message":      f"{order_type} 주문 전송 완료 (주문번호: {external_order})",
            "broker_order": broker_order,
            "is_mock":      is_mock,
        }

    # ── 실패 처리 ─────────────────────────────────────────────────
    fail_msg = api_resp.get("msg1", "알 수 없는 오류")
    _update_broker_order(bo_id, {"order_status": _STATUS_FAILED})
    _log_execution(
        event_type=_EVT_ORDER_FAILED,
        message=f"주문 거부: {fail_msg}",
        order_intent_id=intent_id,
        broker_order_id=bo_id,
        raw_response=api_resp,
    )
    logger.error("[KiwoomOrder] %s 거부: %s", order_type, fail_msg)
    return _err(f"주문 거부: {fail_msg}")


# ════════════════════════════════════════════════════════════════
# 공개 함수 1, 2 — 매수 / 매도 주문 전송
# ════════════════════════════════════════════════════════════════

def send_paper_buy_order(order_intent: dict[str, Any]) -> dict[str, Any]:
    """
    승인된 주문 후보를 키움 모의투자 매수 주문으로 전송합니다.

    Args:
        order_intent: order_intents 테이블 행 dict
                      approval_status='승인' 이어야 전송 가능

    Returns:
        dict:
            success      bool
            message      str
            broker_order dict | None   생성된 broker_orders 행
            is_mock      bool          Mock 응답 여부
    """
    if order_intent.get("order_type") not in ("매수", None):
        return _err(
            f"매수 주문 함수에 '{order_intent.get('order_type')}' 유형이 전달되었습니다."
        )
    return _send_order(order_intent, "매수", _TR_BUY)


def send_paper_sell_order(order_intent: dict[str, Any]) -> dict[str, Any]:
    """
    승인된 주문 후보를 키움 모의투자 매도 주문으로 전송합니다.

    Args:
        order_intent: order_intents 테이블 행 dict
                      approval_status='승인' 이어야 전송 가능

    Returns:
        dict:
            success      bool
            message      str
            broker_order dict | None
            is_mock      bool
    """
    if order_intent.get("order_type") not in ("매도", None):
        return _err(
            f"매도 주문 함수에 '{order_intent.get('order_type')}' 유형이 전달되었습니다."
        )
    return _send_order(order_intent, "매도", _TR_SELL)


# ════════════════════════════════════════════════════════════════
# 공개 함수 3 — 주문 상태 조회
# ════════════════════════════════════════════════════════════════

def get_paper_order_status(internal_broker_order_id: int) -> dict[str, Any]:
    """
    브로커 주문의 현재 상태를 조회합니다.

    Args:
        internal_broker_order_id: broker_orders.id (내부 PK)

    Returns:
        dict:
            success        bool
            message        str
            order_status   str   DB 저장된 현재 상태
            broker_order   dict  broker_orders 행 전체
            api_response   dict | None   Kiwoom API 응답 (가능할 때)
    """
    broker_order = _get_broker_order(internal_broker_order_id)
    if broker_order is None:
        return {
            "success":      False,
            "message":      f"broker_orders ID {internal_broker_order_id} 를 찾을 수 없습니다.",
            "order_status": None,
            "broker_order": None,
            "api_response": None,
        }

    external_no = broker_order.get("broker_order_id", "")
    api_resp    = None

    if external_no:
        try:
            api_resp = _query_order_api(external_no)
            _log_execution(
                event_type=_EVT_STATUS_QUERY,
                message=f"주문 상태 조회: {external_no}",
                broker_order_id=internal_broker_order_id,
                external_order_id=external_no,
            )

            # TODO: API 응답에서 체결 수량/평균가 파싱 후 broker_orders 업데이트
            # output = api_resp.get("output", [{}])
            # if output:
            #     row = output[0] if isinstance(output, list) else output
            #     filled = _safe_int(row.get("TOT_CCLD_QTY"))
            #     avg_price = _safe_int(row.get("AVG_PRVS"))
            #     if filled > 0:
            #         new_status = "전량체결" if filled >= broker_order["quantity"] else "일부체결"
            #         _update_broker_order(internal_broker_order_id, {
            #             "order_status": new_status,
            #             "filled_quantity": filled,
            #             "avg_fill_price": avg_price,
            #         })
            #         broker_order["order_status"] = new_status

        except Exception as e:
            logger.warning("[KiwoomOrder] 상태 조회 API 실패: %s", e)

    return {
        "success":      True,
        "message":      f"주문 상태: {broker_order.get('order_status', '알 수 없음')}",
        "order_status": broker_order.get("order_status"),
        "broker_order": broker_order,
        "api_response": api_resp,
    }


# ════════════════════════════════════════════════════════════════
# 공개 함수 4 — 주문 취소
# ════════════════════════════════════════════════════════════════

def cancel_paper_order(internal_broker_order_id: int) -> dict[str, Any]:
    """
    전송된 모의투자 주문을 취소합니다.

    취소 가능 상태: '전송완료' | '일부체결'
    이미 '전량체결', '취소', '실패' 상태는 취소 불가.

    Args:
        internal_broker_order_id: broker_orders.id (내부 PK)

    Returns:
        dict:
            success      bool
            message      str
            broker_order dict | None   업데이트된 broker_orders 행
    """
    broker_order = _get_broker_order(internal_broker_order_id)
    if broker_order is None:
        return _err(f"broker_orders ID {internal_broker_order_id} 를 찾을 수 없습니다.")

    current_status = broker_order.get("order_status", "")
    cancellable    = {"전송완료", "일부체결"}

    if current_status not in cancellable:
        return _err(
            f"현재 상태({current_status})에서는 취소할 수 없습니다. "
            f"취소 가능 상태: {', '.join(sorted(cancellable))}"
        )

    # 긴급 중지 확인 (취소는 긴급 중지와 무관하게 허용)
    external_no  = broker_order.get("broker_order_id", "")
    stock_code   = broker_order.get("stock_code", "")
    remaining_qty = (
        _safe_int(broker_order.get("quantity"))
        - _safe_int(broker_order.get("filled_quantity"))
    )
    intent_id    = broker_order.get("order_intent_id")
    bo_id        = broker_order.get("id")

    _log_execution(
        event_type=_EVT_CANCEL_SENT,
        message=f"취소 주문 전송 시도: {stock_code} 잔여{remaining_qty}주 / 주문번호={external_no}",
        order_intent_id=intent_id,
        broker_order_id=bo_id,
        external_order_id=external_no,
    )

    try:
        api_resp = _call_cancel_api(external_no, stock_code, remaining_qty)
    except Exception as e:
        logger.error("[KiwoomOrder] 취소 API 예외: %s", e)
        _log_execution(
            event_type=_EVT_CANCEL_FAILED,
            message=f"취소 API 실패: {e}",
            order_intent_id=intent_id,
            broker_order_id=bo_id,
        )
        return _err(f"취소 API 호출 실패: {e}")

    rt_cd   = str(api_resp.get("rt_cd", "1"))
    is_mock = api_resp.get("_mock", False)

    if rt_cd == "0":
        _update_broker_order(bo_id, {"order_status": _STATUS_CANCELLED})
        _log_execution(
            event_type=_EVT_CANCEL_SENT,
            message=f"{'[MOCK] ' if is_mock else ''}취소 완료: {stock_code} / 주문번호={external_no}",
            order_intent_id=intent_id,
            broker_order_id=bo_id,
            external_order_id=external_no,
            raw_response={k: v for k, v in api_resp.items() if k != "_mock"},
        )
        broker_order["order_status"] = _STATUS_CANCELLED
        logger.info("[KiwoomOrder] 취소 완료: %s %s", stock_code, external_no)
        return {
            "success":      True,
            "message":      f"취소 주문 완료 (주문번호: {external_no})",
            "broker_order": broker_order,
        }

    fail_msg = api_resp.get("msg1", "알 수 없는 오류")
    _log_execution(
        event_type=_EVT_CANCEL_FAILED,
        message=f"취소 거부: {fail_msg}",
        order_intent_id=intent_id,
        broker_order_id=bo_id,
    )
    return _err(f"취소 거부: {fail_msg}")
