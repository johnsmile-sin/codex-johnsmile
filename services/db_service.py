"""
DB 서비스 라우터
- Supabase 연결 상태에 따라 실제 DB 또는 Mock 서비스로 분기합니다.
- 모든 함수는 list[dict] 또는 dict 를 반환합니다.
- Supabase 오류는 내부에서 잡아 경고 로그를 남기고 빈 결과를 반환합니다.
- show_db_status() 를 Streamlit 사이드바에서 호출해 현재 모드를 표시합니다.
"""

import logging
from typing import Any

import streamlit as st

from services.supabase_client import get_client, is_connected, get_error
import services.mock_db_service as mock

logger = logging.getLogger(__name__)


# ── 내부 헬퍼 ────────────────────────────────────────────────

def _supabase_call(fn) -> list[dict] | dict | None:
    """Supabase 호출을 try/except 로 감싸 앱 크래시를 방지합니다."""
    try:
        result = fn()
        if hasattr(result, "data"):
            return result.data or []
        return result
    except Exception as e:
        logger.warning("[Supabase] 쿼리 실패: %s", e)
        st.warning(f"⚠️ Supabase 오류가 발생했습니다. Mock 데이터로 대체합니다.\n\n`{e}`")
        return None


# ── 사이드바 상태 표시 ────────────────────────────────────────

def show_db_status() -> None:
    """
    Streamlit 사이드바에 현재 DB 연결 모드를 표시합니다.
    app.py 또는 각 페이지의 사이드바 영역에서 호출하세요.
    """
    if is_connected():
        st.sidebar.success("🟢 Supabase 연결됨")
    else:
        st.sidebar.warning("🟡 Mock 모드 실행 중")
        err = get_error()
        if err:
            st.sidebar.caption(f"사유: {err}")


# ── stocks ───────────────────────────────────────────────────

def get_stocks() -> list[dict]:
    """종목 마스터 반환"""
    if not is_connected():
        return mock.get_stocks()

    result = _supabase_call(
        lambda: get_client().table("stocks").select("*").order("stock_code").execute()
    )
    return result if result is not None else mock.get_stocks()


# ── candidate_scores ─────────────────────────────────────────

def save_candidate_scores(data: dict) -> dict:
    """점수 결과 저장"""
    if not is_connected():
        return mock.save_candidate_scores(data)

    result = _supabase_call(
        lambda: get_client().table("candidate_scores").insert(data).execute()
    )
    if result is None:
        return mock.save_candidate_scores(data)
    return result[0] if result else data


def get_candidate_scores() -> list[dict]:
    """점수 결과 목록 반환 (최신순)"""
    if not is_connected():
        return mock.get_candidate_scores()

    result = _supabase_call(
        lambda: get_client()
        .table("candidate_scores")
        .select("*")
        .order("trade_date", desc=True)
        .execute()
    )
    return result if result is not None else mock.get_candidate_scores()


# ── news_items ───────────────────────────────────────────────

def save_news_items(data: dict) -> dict:
    """뉴스 저장"""
    if not is_connected():
        return mock.save_news_items(data)

    result = _supabase_call(
        lambda: get_client().table("news_items").insert(data).execute()
    )
    if result is None:
        return mock.save_news_items(data)
    return result[0] if result else data


def get_news_items(stock_code: str | None = None) -> list[dict]:
    """뉴스 목록 반환. stock_code 지정 시 해당 종목만."""
    if not is_connected():
        return mock.get_news_items(stock_code)

    def _query():
        q = get_client().table("news_items").select("*").order("news_date", desc=True)
        if stock_code:
            q = q.eq("stock_code", stock_code)
        return q.execute()

    result = _supabase_call(_query)
    return result if result is not None else mock.get_news_items(stock_code)


# ── stock_reports ────────────────────────────────────────────

def save_stock_report(data: dict) -> dict:
    """리포트 저장"""
    if not is_connected():
        return mock.save_stock_report(data)

    result = _supabase_call(
        lambda: get_client().table("stock_reports").insert(data).execute()
    )
    if result is None:
        return mock.save_stock_report(data)
    return result[0] if result else data


def get_stock_reports(stock_code: str | None = None) -> list[dict]:
    """리포트 목록 반환. stock_code 지정 시 해당 종목만."""
    if not is_connected():
        return mock.get_stock_reports(stock_code)

    def _query():
        q = get_client().table("stock_reports").select("*").order("report_date", desc=True)
        if stock_code:
            q = q.eq("stock_code", stock_code)
        return q.execute()

    result = _supabase_call(_query)
    return result if result is not None else mock.get_stock_reports(stock_code)


# ── trade_journal ────────────────────────────────────────────

def save_trade_journal(data: dict) -> dict:
    """매매일지 저장"""
    if not is_connected():
        return mock.save_trade_journal(data)

    result = _supabase_call(
        lambda: get_client().table("trade_journal").insert(data).execute()
    )
    if result is None:
        return mock.save_trade_journal(data)
    return result[0] if result else data


def get_trade_journal() -> list[dict]:
    """매매일지 전체 반환 (최신순)"""
    if not is_connected():
        return mock.get_trade_journal()

    result = _supabase_call(
        lambda: get_client()
        .table("trade_journal")
        .select("*")
        .order("trade_date", desc=True)
        .execute()
    )
    return result if result is not None else mock.get_trade_journal()
