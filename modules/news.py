"""
Mock 뉴스 요약 모듈
OpenAI API가 없으면 미리 준비된 Mock 텍스트를 반환합니다.
"""

import os
import random

_MOCK_NEWS_TEMPLATES = [
    [
        "📰 {name} 신규 수주 계약 체결 – 매출 확대 기대",
        "📰 {name} 3분기 실적 개선 전망...증권가 목표주가 상향",
        "📰 {sector} 업황 개선 신호, {name} 수혜 예상",
    ],
    [
        "📰 {name} 대규모 투자 발표 – 내년 설비 증설",
        "📰 외국인 {name} 순매수 전환...수급 개선",
        "📰 {name} 자사주 매입 결정, 주주 환원 강화",
    ],
    [
        "📰 {name} 신사업 진출 MOU 체결",
        "📰 {sector} 섹터 글로벌 공급망 안정화 – {name} 반사이익",
        "📰 {name} 분기 배당 실시 발표",
    ],
]

_MOCK_SENTIMENT = ["긍정적", "중립적", "다소 긍정적"]


def get_news_summary(code: str, name: str, sector: str) -> dict:
    """
    종목 뉴스 요약을 반환합니다.
    OPENAI_API_KEY가 설정된 경우 실제 요약을 시도하고,
    없으면 Mock 데이터를 반환합니다.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")

    if api_key and not api_key.startswith("sk-your"):
        return _fetch_openai_summary(code, name, sector, api_key)

    return _mock_summary(name, sector)


def _mock_summary(name: str, sector: str) -> dict:
    template_set = random.choice(_MOCK_NEWS_TEMPLATES)
    headlines = [t.format(name=name, sector=sector) for t in template_set]
    sentiment = random.choice(_MOCK_SENTIMENT)
    summary = (
        f"{name}은(는) 최근 {sector} 업황 개선 흐름 속에서 긍정적인 뉴스가 이어지고 있습니다. "
        f"수급 측면에서도 외국인·기관 매수세가 관찰되며 단기 모멘텀이 살아있는 상황입니다. "
        f"다만 글로벌 매크로 불확실성은 여전히 리스크 요인으로 작용할 수 있습니다."
    )
    return {
        "headlines": headlines,
        "sentiment": sentiment,
        "summary": summary,
        "source": "Mock",
    }


def _fetch_openai_summary(code: str, name: str, sector: str, api_key: str) -> dict:
    """OpenAI API를 이용한 뉴스 요약 (실제 연동 시 구현)"""
    # TODO: 실제 뉴스 크롤링 후 OpenAI 요약 연동
    return _mock_summary(name, sector)
