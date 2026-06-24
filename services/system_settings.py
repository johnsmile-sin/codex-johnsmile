"""
services/system_settings.py  –  시스템 설정 서비스 (4차)

Supabase system_settings 테이블(id=1 단일 행) 읽기/쓰기.
미연결 시 data/system_settings.json 으로 폴백합니다.

⚠️  안전 원칙 (코드 레벨 하드코딩, 설정으로 변경 불가):
    - allow_real_trading  : 항상 False
    - real_trading 모드   : 지원하지 않음
    - emergency_stop=True : 모든 주문 후보 생성 및 전송 즉시 차단

trading_mode 값:
    analysis_only  (기본) 신호 생성까지만 허용, 주문 후보 생성 불가
    paper_trading         모의투자 주문 후보 생성 허용 (수동 승인 필수)
    real_ready            실거래 전환 준비 상태 표시용 (실거래 주문은 여전히 차단)

공개 함수:
    get_system_settings()            전체 설정 딕셔너리 반환
    update_trading_mode(mode)        trading_mode 변경
    set_emergency_stop(is_enabled)   긴급 중지 ON/OFF
    is_trading_allowed()             주문 후보 생성 가능 여부
    is_real_trading_allowed()        항상 False
    is_manual_approval_required()    수동 승인 필요 여부
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

DATA_DIR      = Path(__file__).resolve().parents[1] / "data"
SETTINGS_FILE = DATA_DIR / "system_settings.json"

VALID_TRADING_MODES = {"analysis_only", "paper_trading", "real_ready"}

# Supabase CHECK 제약이 analysis_only / paper_trading 만 허용하므로
# real_ready 는 Supabase 에 저장하지 않고 로컬 파일로만 관리한다.
_SUPABASE_ALLOWED_MODES = {"analysis_only", "paper_trading"}

_DEFAULT_SETTINGS: dict[str, Any] = {
    "id":                      1,
    "trading_mode":            "analysis_only",
    "allow_real_trading":      False,   # 코드 레벨 고정 — 절대 True 불가
    "require_manual_approval": True,
    "emergency_stop":          False,
    "max_order_amount":        1_000_000,
    # 숫자 한도는 risk_settings 에서 가져오지만 기본값을 여기서도 보관
    "max_daily_loss_rate":     -3.0,
    "max_position_count":      5,
    "note":                    None,
    "updated_at":              None,
}


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


def _enforce_safety(settings: dict[str, Any]) -> dict[str, Any]:
    """allow_real_trading 을 항상 False 로 강제한다."""
    settings["allow_real_trading"] = False
    return settings


def _load_from_supabase() -> dict[str, Any] | None:
    """Supabase system_settings 단일 행을 읽는다. 실패 시 None."""
    try:
        rows = (
            _supabase_client()
            .table("system_settings")
            .select("*")
            .eq("id", 1)
            .limit(1)
            .execute()
            .data or []
        )
        if rows:
            return rows[0]
    except Exception as e:
        logger.warning("[SystemSettings] Supabase 읽기 실패: %s", e)
    return None


def _load_from_file() -> dict[str, Any] | None:
    """로컬 JSON 파일에서 설정을 읽는다. 실패 시 None."""
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[SystemSettings] 파일 읽기 실패: %s", e)
    return None


def _save_to_file(settings: dict[str, Any]) -> None:
    """설정을 로컬 JSON 파일에 저장한다."""
    try:
        _ensure_data_dir()
        SETTINGS_FILE.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error("[SystemSettings] 파일 저장 실패: %s", e)


def _load_risk_settings_limits() -> dict[str, Any]:
    """risk_settings 테이블에서 숫자 한도만 가져온다. 실패 시 기본값."""
    defaults = {
        "max_daily_loss_rate": _DEFAULT_SETTINGS["max_daily_loss_rate"],
        "max_position_count":  _DEFAULT_SETTINGS["max_position_count"],
    }
    if not _supabase_connected():
        return defaults
    try:
        rows = (
            _supabase_client()
            .table("risk_settings")
            .select("max_daily_loss_rate, max_position_count")
            .order("id", desc=False)
            .limit(1)
            .execute()
            .data or []
        )
        if rows:
            r = rows[0]
            defaults["max_daily_loss_rate"] = float(r.get("max_daily_loss_rate", defaults["max_daily_loss_rate"]))
            defaults["max_position_count"]  = int(r.get("max_position_count",    defaults["max_position_count"]))
    except Exception as e:
        logger.warning("[SystemSettings] risk_settings 읽기 실패: %s", e)
    return defaults


def _merge_with_defaults(raw: dict[str, Any]) -> dict[str, Any]:
    """누락 키를 기본값으로 채운 뒤 안전 강제를 적용한다."""
    merged = dict(_DEFAULT_SETTINGS)
    merged.update({k: v for k, v in raw.items() if k in merged})
    # 숫자 한도를 risk_settings 에서 보완
    limits = _load_risk_settings_limits()
    merged["max_daily_loss_rate"] = limits["max_daily_loss_rate"]
    merged["max_position_count"]  = limits["max_position_count"]
    return _enforce_safety(merged)


# ════════════════════════════════════════════════════════════════
# 공개 함수
# ════════════════════════════════════════════════════════════════

def get_system_settings() -> dict[str, Any]:
    """
    시스템 설정 전체를 반환합니다.
    Supabase → 로컬 JSON → 기본값 순으로 폴백합니다.

    Returns:
        dict:
            trading_mode            str   'analysis_only' | 'paper_trading' | 'real_ready'
            allow_real_trading      bool  항상 False
            require_manual_approval bool
            emergency_stop          bool
            max_order_amount        int   원
            max_daily_loss_rate     float % (음수, risk_settings 에서 병합)
            max_position_count      int   (risk_settings 에서 병합)
            note                    str | None
            updated_at              str | None
            source                  str   'supabase' | 'file' | 'default'
    """
    raw: dict[str, Any] | None = None
    source = "default"

    if _supabase_connected():
        raw = _load_from_supabase()
        if raw:
            source = "supabase"

    if raw is None:
        raw = _load_from_file()
        if raw:
            source = "file"

    settings = _merge_with_defaults(raw or {})
    settings["source"] = source
    return settings


def update_trading_mode(mode: str) -> dict[str, Any]:
    """
    trading_mode 를 변경합니다.

    Args:
        mode: 'analysis_only' | 'paper_trading' | 'real_ready'
              (real_trading 은 지원하지 않음)

    Returns:
        dict: {"success": bool, "mode": str, "message": str}
    """
    mode = str(mode).strip().lower()

    if mode not in VALID_TRADING_MODES:
        return {
            "success": False,
            "mode":    mode,
            "message": (
                f"유효하지 않은 trading_mode: '{mode}'. "
                f"허용값: {sorted(VALID_TRADING_MODES)}"
            ),
        }

    now = _now()
    settings = get_system_settings()
    prev_mode = settings.get("trading_mode", "analysis_only")

    settings["trading_mode"] = mode
    settings["updated_at"]   = now
    settings.pop("source", None)

    # 로컬 파일에는 항상 저장 (real_ready 포함 모든 모드 지원)
    _save_to_file(settings)

    # Supabase 에는 허용 모드만 저장
    if _supabase_connected() and mode in _SUPABASE_ALLOWED_MODES:
        try:
            _supabase_client().table("system_settings").upsert(
                {"id": 1, "trading_mode": mode, "updated_at": now},
                on_conflict="id",
            ).execute()
        except Exception as e:
            logger.warning("[SystemSettings] Supabase trading_mode 업데이트 실패: %s", e)

    logger.info("[SystemSettings] trading_mode 변경: %s → %s", prev_mode, mode)
    return {
        "success": True,
        "mode":    mode,
        "message": f"trading_mode 가 '{prev_mode}' 에서 '{mode}' 으로 변경되었습니다.",
    }


def set_emergency_stop(is_enabled: bool) -> dict[str, Any]:
    """
    긴급 중지를 활성화/비활성화합니다.

    is_enabled=True  → 모든 주문 후보 생성 및 전송 즉시 차단
    is_enabled=False → 긴급 중지 해제

    Returns:
        dict: {"success": bool, "emergency_stop": bool, "message": str}
    """
    is_enabled = bool(is_enabled)
    now        = _now()

    settings = get_system_settings()
    settings["emergency_stop"] = is_enabled
    settings["updated_at"]     = now
    settings.pop("source", None)

    # 로컬 파일 저장
    _save_to_file(settings)

    # Supabase 업데이트
    if _supabase_connected():
        try:
            _supabase_client().table("system_settings").upsert(
                {"id": 1, "emergency_stop": is_enabled, "updated_at": now},
                on_conflict="id",
            ).execute()
        except Exception as e:
            logger.warning("[SystemSettings] Supabase emergency_stop 업데이트 실패: %s", e)

    # safety_events 에 긴급 중지 이벤트 기록
    _log_safety_event(
        event_type="EMERGENCY_STOP",
        severity="CRITICAL" if is_enabled else "LOW",
        message=(
            "긴급 중지 활성화: 모든 주문 후보 생성 및 전송이 차단됩니다."
            if is_enabled
            else "긴급 중지 해제: 정상 운영으로 복귀합니다."
        ),
    )

    action = "활성화" if is_enabled else "해제"
    logger.warning("[SystemSettings] 긴급 중지 %s", action)
    return {
        "success":       True,
        "emergency_stop": is_enabled,
        "message":       f"긴급 중지가 {action}되었습니다.",
    }


def is_trading_allowed() -> bool:
    """
    주문 후보(order_intent) 생성이 허용되는지 반환합니다.

    False 조건:
        - trading_mode == 'analysis_only'
        - emergency_stop == True
        - allow_real_trading 은 항상 False 이므로 영향 없음

    Returns:
        bool: True 이면 paper_trading 모드에서 주문 후보 생성 가능
    """
    settings = get_system_settings()

    if settings.get("emergency_stop", False):
        logger.info("[SystemSettings] 주문 차단: 긴급 중지 활성 상태")
        return False

    if settings.get("trading_mode", "analysis_only") == "analysis_only":
        logger.info("[SystemSettings] 주문 차단: analysis_only 모드")
        return False

    return True


def is_real_trading_allowed() -> bool:
    """
    실거래 주문 허용 여부를 반환합니다.

    이 프로젝트에서는 항상 False 입니다.
    설정·DB 값과 무관하게 코드 레벨에서 고정됩니다.

    Returns:
        bool: 항상 False
    """
    return False


def is_manual_approval_required() -> bool:
    """
    주문 후보를 브로커로 전송하기 전 사용자 수동 승인이 필요한지 반환합니다.

    Returns:
        bool: True 이면 approval_status='승인' 확인 후에만 전송 가능
    """
    settings = get_system_settings()
    return bool(settings.get("require_manual_approval", True))


# ════════════════════════════════════════════════════════════════
# 내부 — 안전 이벤트 기록 (safety_events 테이블)
# ════════════════════════════════════════════════════════════════

def _log_safety_event(
    event_type: str,
    severity: str,
    message: str,
    related_stock_code: str | None = None,
) -> None:
    """safety_events 테이블에 이벤트를 기록한다. 실패해도 예외를 전파하지 않는다."""
    if not _supabase_connected():
        return
    try:
        _supabase_client().table("safety_events").insert({
            "event_type":         event_type,
            "severity":           severity,
            "message":            message,
            "related_stock_code": related_stock_code,
        }).execute()
    except Exception as e:
        logger.warning("[SystemSettings] safety_events 기록 실패: %s", e)


# ════════════════════════════════════════════════════════════════
# 편의 함수 — 대시보드 표시용
# ════════════════════════════════════════════════════════════════

def get_status_summary() -> dict[str, Any]:
    """
    대시보드 표시용 상태 요약을 반환합니다.

    Returns:
        dict:
            trading_mode        str
            trading_allowed     bool
            emergency_stop      bool
            manual_approval     bool
            max_order_amount    int
            max_daily_loss_rate float
            max_position_count  int
            mode_label          str   한국어 모드 이름
            mode_color          str   상태 색상 (#hex)
            source              str   설정 출처
    """
    settings = get_system_settings()
    mode     = settings.get("trading_mode", "analysis_only")

    _MODE_LABEL = {
        "analysis_only": "분석 전용",
        "paper_trading": "모의투자",
        "real_ready":    "실거래 준비",
    }
    _MODE_COLOR = {
        "analysis_only": "#5DADE2",   # 파란색 — 안전
        "paper_trading": "#F39C12",   # 주황색 — 주의
        "real_ready":    "#E74C3C",   # 빨간색 — 경고
    }

    return {
        "trading_mode":        mode,
        "trading_allowed":     is_trading_allowed(),
        "emergency_stop":      bool(settings.get("emergency_stop", False)),
        "manual_approval":     bool(settings.get("require_manual_approval", True)),
        "max_order_amount":    int(settings.get("max_order_amount", 1_000_000)),
        "max_daily_loss_rate": float(settings.get("max_daily_loss_rate", -3.0)),
        "max_position_count":  int(settings.get("max_position_count", 5)),
        "mode_label":          _MODE_LABEL.get(mode, mode),
        "mode_color":          _MODE_COLOR.get(mode, "#888"),
        "source":              settings.get("source", "default"),
    }
