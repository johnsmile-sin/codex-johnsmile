"""
services/data_providers/naver_provider.py
네이버 뉴스 검색 API 기반 실제 뉴스 수집

API 키 발급: https://developers.naver.com → 애플리케이션 등록 (무료)
환경변수: NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

logger   = logging.getLogger(__name__)
_API_URL = "https://openapi.naver.com/v1/search/news.json"
_TIMEOUT = 5

# ── 감성 분류 키워드 ──────────────────────────────────────────
_POS_KEYWORDS = [
    "급등", "상승", "수주", "호실적", "어닝서프라이즈", "목표주가 상향",
    "매수", "성장", "신고가", "수익", "흑자", "증가", "확대", "개선",
    "반등", "회복", "긍정", "호재", "투자", "기대", "최대", "돌파",
]
_NEG_KEYWORDS = [
    "급락", "하락", "매도", "목표주가 하향", "부진", "적자", "감소",
    "악재", "손실", "위기", "우려", "리스크", "규제", "제재", "소송",
    "공급과잉", "둔화", "약세", "하향", "취소", "연기", "폐업",
]


def is_available() -> bool:
    """NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 환경변수 존재 여부"""
    return bool(
        os.getenv("NAVER_CLIENT_ID", "").strip()
        and os.getenv("NAVER_CLIENT_SECRET", "").strip()
    )


def search_news(
    stock_name: str,
    stock_code: str,
    display: int = 10,
) -> list[dict]:
    """
    네이버 뉴스 API로 종목 관련 최신 뉴스를 조회합니다.

    Args:
        stock_name: 종목명 (검색 키워드)
        stock_code: 종목코드 (메타 정보용)
        display:    최대 뉴스 건수 (기본 10)

    Returns:
        뉴스 딕셔너리 리스트 (mock_db_service 동일 스키마)
        각 항목: stock_code, stock_name, title, summary,
                 sentiment, impact_score, news_date, url
    """
    if not is_available():
        return []

    client_id     = os.getenv("NAVER_CLIENT_ID", "").strip()
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()

    try:
        resp = requests.get(
            _API_URL,
            headers={
                "X-Naver-Client-Id":     client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={
                "query":   f"{stock_name} 주식",
                "display": display,
                "sort":    "date",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception as e:
        logger.warning("[Naver] 뉴스 조회 실패 %s: %s", stock_name, e)
        return []

    results = []
    for item in items:
        raw_title   = _strip_html(item.get("title", ""))
        description = _strip_html(item.get("description", ""))
        pub_date    = _parse_date(item.get("pubDate", ""))
        url         = item.get("link", "")

        sentiment    = _classify_sentiment(raw_title, description)
        impact_score = _calc_impact(raw_title, description)

        results.append({
            "stock_code":   stock_code,
            "stock_name":   stock_name,
            "title":        raw_title,
            "summary":      description[:120] if description else "",
            "sentiment":    sentiment,
            "impact_score": impact_score,
            "news_date":    pub_date,
            "url":          url,
        })

    return results


# ── 내부 헬퍼 ─────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """HTML 태그 및 엔티티 제거"""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    return text.strip()


def _parse_date(pub_date: str) -> str:
    """네이버 pubDate 형식(RFC 2822) → YYYY-MM-DD 변환"""
    try:
        dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
        return str(dt.date())
    except Exception:
        return str(date.today())


def _classify_sentiment(title: str, description: str) -> str:
    """제목+요약 기반 간단한 감성 분류"""
    text = (title + " " + description).lower()

    pos_score = sum(1 for kw in _POS_KEYWORDS if kw in text)
    neg_score = sum(1 for kw in _NEG_KEYWORDS if kw in text)

    if pos_score > neg_score:
        return "긍정"
    if neg_score > pos_score:
        return "부정"
    return "중립"


def _calc_impact(title: str, description: str) -> int:
    """영향도 1~5 추정 (키워드 점수 기반)"""
    high_impact = ["급등", "급락", "어닝서프라이즈", "어닝쇼크", "상장폐지", "신고가", "신저가"]
    text = title + " " + description
    count = sum(1 for kw in high_impact if kw in text)
    return min(5, max(1, 2 + count))
