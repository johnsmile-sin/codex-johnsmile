"""
config.py — 환경변수 중앙 관리 및 API 상태 확인

모든 env var는 이 모듈을 통해 읽는다.
- 값이 없으면 None 반환 (앱은 절대 죽지 않음)
- API 키 값은 화면에 절대 표시하지 않음
- Streamlit 사이드바용 show_api_status() 제공
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


# ════════════════════════════════════════════════════════════════
# 환경변수 읽기 (전체 목록)
# ════════════════════════════════════════════════════════════════

# ── Supabase ────────────────────────────────────────────────────
SUPABASE_URL      = os.getenv("SUPABASE_URL",      None)
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", None)

# ── 앱 모드 ─────────────────────────────────────────────────────
MOCK_MODE = os.getenv("MOCK_MODE", "false").strip().lower() in {"1", "true", "yes", "y", "on"}
APP_MODE  = os.getenv("APP_MODE", "dev").strip()

# ── 키움 (4차: 조회 + 모의투자 전용) ─────────────────────────
KIWOOM_APP_KEY        = os.getenv("KIWOOM_APP_KEY",         None)
KIWOOM_SECRET_KEY     = os.getenv("KIWOOM_SECRET_KEY",      None)
KIWOOM_MOCK_ACCOUNT_NO = os.getenv("KIWOOM_MOCK_ACCOUNT_NO", None)   # 모의투자 계좌번호만 허용

# 투자 모드: "mock"(기본) | "paper"(모의투자 API)
# "real" 을 입력해도 코드 레벨에서 "mock" 으로 강제 전환됩니다.
_raw_invest_mode  = os.getenv("KIWOOM_INVEST_MODE", "mock").strip().lower()
KIWOOM_INVEST_MODE = "paper" if _raw_invest_mode == "paper" else "mock"

# ── 4차 자동매매 안전 스위치 (기본값은 모두 보수적) ───────────
# analysis_only=True 이면 신호 생성까지만 허용, 주문 객체 생성 금지
ANALYSIS_ONLY_MODE = os.getenv("ANALYSIS_ONLY_MODE", "true").strip().lower() not in {
    "0", "false", "no", "n", "off"
}
# require_approval=True 이면 order_intent 가 APPROVED 상태일 때만 전송 허용
REQUIRE_MANUAL_APPROVAL = os.getenv("REQUIRE_MANUAL_APPROVAL", "true").strip().lower() not in {
    "0", "false", "no", "n", "off"
}
# 1일 최대 자동 주문 건수 (0 = 제한 없음)
MAX_DAILY_AUTO_ORDERS  = int(os.getenv("MAX_DAILY_AUTO_ORDERS",  "3") or "3")
# 종목당 최대 1회 주문금액 (0 이면 risk_manager 설정값 사용)
MAX_ORDER_AMOUNT_PER_STOCK = int(os.getenv("MAX_ORDER_AMOUNT_PER_STOCK", "500000") or "0")

# ── 하드코딩 상수 (env 로 변경 불가) ──────────────────────────
ALLOW_REAL_TRADING   = False   # 실거래 주문 영구 금지
ALLOW_MARKET_ORDER   = False   # 시장가 자동주문 영구 금지

# ── 네이버 뉴스 ─────────────────────────────────────────────────
NAVER_CLIENT_ID     = os.getenv("NAVER_CLIENT_ID",     None)
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", None)

# ── OpenDART ────────────────────────────────────────────────────
DART_API_KEY = os.getenv("DART_API_KEY", None)

# ── OpenAI (선택) ────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", None)


# ════════════════════════════════════════════════════════════════
# API 가용 여부 확인 함수 (키 값은 절대 반환하지 않음)
# ════════════════════════════════════════════════════════════════

def is_supabase_available() -> bool:
    """Supabase 키 존재 + MOCK_MODE=false 확인"""
    if MOCK_MODE:
        return False
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def is_supabase_connected() -> bool:
    """실제 Supabase 소켓 연결 성공 여부 (supabase_client 모듈 참조)"""
    try:
        from services.supabase_client import is_connected
        return is_connected()
    except Exception:
        return False


def is_kiwoom_available() -> bool:
    """국내주식 조회 API 실제 사용 가능 여부."""
    try:
        from services.kiwoom_data import is_available
        return is_available()
    except Exception:
        return False


def is_kiwoom_configured() -> bool:
    """국내주식 조회 API 키 입력 여부."""
    return bool(KIWOOM_APP_KEY and KIWOOM_SECRET_KEY)


def is_kiwoom_paper_ready() -> bool:
    """모의투자 API 사용 조건: 키 있음 + paper 모드 + 계좌번호 있음."""
    return (
        KIWOOM_INVEST_MODE == "paper"
        and bool(KIWOOM_APP_KEY)
        and bool(KIWOOM_SECRET_KEY)
        and bool(KIWOOM_MOCK_ACCOUNT_NO)
    )


def get_safety_flags() -> dict:
    """4차 안전 스위치 상태를 딕셔너리로 반환 (대시보드 표시용)."""
    return {
        "analysis_only":       ANALYSIS_ONLY_MODE,
        "require_approval":    REQUIRE_MANUAL_APPROVAL,
        "allow_real_trading":  ALLOW_REAL_TRADING,    # 항상 False
        "allow_market_order":  ALLOW_MARKET_ORDER,    # 항상 False
        "invest_mode":         KIWOOM_INVEST_MODE,
        "max_daily_orders":    MAX_DAILY_AUTO_ORDERS,
        "max_order_amount":    MAX_ORDER_AMOUNT_PER_STOCK,
    }


def is_naver_available() -> bool:
    """네이버 뉴스 API 키 존재 여부"""
    return bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET)


def is_dart_available() -> bool:
    """OpenDART API 키 존재 여부"""
    return bool(DART_API_KEY)


def is_openai_available() -> bool:
    """OpenAI API 키 존재 여부"""
    return bool(OPENAI_API_KEY)


# ════════════════════════════════════════════════════════════════
# Streamlit 사이드바 — API 상태 위젯
# ════════════════════════════════════════════════════════════════

def show_api_status() -> None:
    """
    Streamlit 사이드바에 API 연결 상태를 표시합니다.
    API 키 값은 절대 화면에 출력하지 않습니다.
    """
    try:
        import streamlit as st
    except ImportError:
        return

    _CONNECTED    = "#27AE60"   # 초록
    _PARTIAL      = "#F39C12"   # 주황
    _DISCONNECTED = "#BDC3C7"   # 회색

    def _dot(color: str) -> str:
        return (
            f"<span style='display:inline-block;width:10px;height:10px;"
            f"border-radius:50%;background:{color};margin-right:6px'></span>"
        )

    def _row(label: str, connected: bool, note: str = "") -> str:
        color = _CONNECTED if connected else _DISCONNECTED
        status = "연결됨" if connected else "미연결"
        note_html = f"<span style='color:#999;font-size:11px'> {note}</span>" if note else ""
        return (
            f"<div style='margin:3px 0;font-size:13px'>"
            f"{_dot(color)}<b>{label}</b> "
            f"<span style='color:{color};font-size:12px'>{status}</span>"
            f"{note_html}</div>"
        )

    # ── Supabase ─────────────────────────────────────────────────
    supa_conn  = is_supabase_connected()
    supa_avail = is_supabase_available()
    if MOCK_MODE:
        supa_note = "MOCK_MODE=true"
        supa_color = _PARTIAL
    elif supa_conn:
        supa_note  = ""
        supa_color = _CONNECTED
    elif supa_avail:
        supa_note  = "키 있음·연결 실패"
        supa_color = _PARTIAL
    else:
        supa_note  = "키 없음"
        supa_color = _DISCONNECTED

    def _supa_row() -> str:
        status = "Mock 모드" if MOCK_MODE else ("연결됨" if supa_conn else "미연결")
        return (
            f"<div style='margin:3px 0;font-size:13px'>"
            f"<span style='display:inline-block;width:10px;height:10px;"
            f"border-radius:50%;background:{supa_color};margin-right:6px'></span>"
            f"<b>Supabase</b> "
            f"<span style='color:{supa_color};font-size:12px'>{status}</span>"
            + (f"<span style='color:#999;font-size:11px'> {supa_note}</span>" if supa_note else "")
            + "</div>"
        )

    html = (
        "<div style='background:#F8F9FA;border-radius:8px;padding:10px 12px;margin-bottom:4px'>"
        "<div style='font-size:12px;font-weight:600;color:#555;margin-bottom:6px'>API 연결 상태</div>"
        + _supa_row()
        + _row(
            "국내주식 API",
            is_kiwoom_available(),
            "키 입력됨·구현 대기" if is_kiwoom_configured() else "조회 모듈 구현 대기",
        )
        + _row("Naver 뉴스",    is_naver_available())
        + _row("OpenDART",      is_dart_available())
        + _row(
            "키움 모의투자",
            is_kiwoom_paper_ready(),
            "paper 모드 준비됨" if is_kiwoom_paper_ready() else (
                "키 없음 (Mock)" if not is_kiwoom_configured() else "mock 모드"
            ),
        )
        + "</div>"
    )

    # ── 4차 안전 스위치 표시 ──────────────────────────────────
    flags = get_safety_flags()
    _color_on  = "#27AE60"
    _color_off = "#E74C3C"

    def _flag_row(label: str, value: bool, safe_when: bool = True) -> str:
        is_safe = (value == safe_when)
        color   = _color_on if is_safe else _color_off
        text    = "ON" if value else "OFF"
        return (
            f"<div style='margin:2px 0;font-size:12px'>"
            f"<span style='color:{color};font-weight:600'>[{text}]</span> "
            f"{label}</div>"
        )

    safety_html = (
        "<div style='background:#FFF8E1;border-radius:8px;padding:8px 12px;margin-top:6px'>"
        "<div style='font-size:11px;font-weight:600;color:#7D6608;margin-bottom:4px'>"
        "🔒 안전 스위치</div>"
        + _flag_row("분석 전용 모드 (주문 생성 차단)", flags["analysis_only"],    safe_when=True)
        + _flag_row("수동 승인 필수",                  flags["require_approval"], safe_when=True)
        + _flag_row("실거래 주문 (항상 차단됨)",       flags["allow_real_trading"], safe_when=False)
        + f"<div style='font-size:11px;color:#888;margin-top:2px'>"
        f"모드: {flags['invest_mode'].upper()} · "
        f"일일 최대 {flags['max_daily_orders']}건</div>"
        + "</div>"
    )
    st.markdown(safety_html, unsafe_allow_html=True)

    st.markdown(html, unsafe_allow_html=True)
