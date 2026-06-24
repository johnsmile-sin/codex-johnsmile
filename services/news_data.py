"""
services/news_data.py v2  —  종목별 뉴스 서비스

공개 API:
    fetch_news_from_naver(stock_name, days, max_items) → list[dict]
    clean_news_text(text)                              → str
    classify_news_sentiment(title, summary)            → "긍정"|"중립"|"부정"
    summarize_news_sentiment(news_items)               → dict
    save_news_to_supabase(news_items)                  → dict
    get_news_for_stock(stock_code, stock_name)         → list[dict]

    # 하위호환 유지
    get_mock_news(stock_code, stock_name)              → list[dict]
    get_news(stock_code, stock_name, display)          → list[dict]
    get_news_summary(news)                             → dict

뉴스 아이템 스키마:
    stock_code, stock_name, title, summary,
    sentiment, impact_score, news_date, url, source
"""

from __future__ import annotations

import logging
import random
import re
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# 감성 상수
POS = "긍정"
NEU = "중립"
NEG = "부정"

# 감성 분류 키워드
_POS_KEYWORDS = [
    "급등", "상승", "수주", "호실적", "어닝서프라이즈", "목표주가 상향",
    "매수", "성장", "신고가", "수익", "흑자", "증가", "확대", "개선",
    "반등", "회복", "긍정", "호재", "투자", "기대", "최대", "돌파",
    "수혜", "강세", "신규", "계약", "승인", "허가", "획득", "선정",
]
_NEG_KEYWORDS = [
    "급락", "하락", "매도", "목표주가 하향", "부진", "적자", "감소",
    "악재", "손실", "위기", "우려", "리스크", "규제", "제재", "소송",
    "공급과잉", "둔화", "약세", "하향", "취소", "연기", "폐업",
    "실망", "충격", "쇼크", "손해", "폭락", "위반", "과징금", "벌금",
]
_HIGH_IMPACT_KEYWORDS = [
    "급등", "급락", "어닝서프라이즈", "어닝쇼크", "상장폐지",
    "신고가", "신저가", "대규모 수주", "파산", "분기 최대", "사상 최대",
]


# ════════════════════════════════════════════════════════════════
# 섹터별 Mock 뉴스 템플릿
# ════════════════════════════════════════════════════════════════

_SECTOR_TEMPLATES: dict[str, list[tuple]] = {
    "반도체": [
        ("HBM3E 공급 확대… AI 서버 수요 급증", "엔비디아향 HBM3E 공급 비중이 크게 늘며 ASP 상승 기대.", POS, 5),
        ("메모리 반도체 가격 반등세 지속", "DDR5·LPDDR5 가격이 3개월 연속 상승하며 업황 회복 신호.", POS, 4),
        ("삼성·SK, AI 반도체 투자 2조 확대 발표", "차세대 HBM4 라인 증설로 내년 글로벌 점유율 방어 전략.", POS, 4),
        ("미국 반도체 수출 규제 추가 강화 검토", "바이든·트럼프 정부 모두 대중 수출 제한 유지 방침으로 불확실성 확대.", NEG, 4),
        ("레거시 반도체 공급과잉 지속, 가격 약세", "DRAM·낸드 레거시 제품 재고 정상화 지연.", NEU, 3),
    ],
    "IT서비스": [
        ("AI 검색 광고 수익 2분기 연속 성장", "하이퍼클로바X 기반 광고 CTR이 기존 대비 23% 향상.", POS, 4),
        ("플랫폼 법 국회 통과…수수료 상한 규제 본격화", "앱마켓·중개 플랫폼 수수료 상한 30% 법제화로 수익성 압박 우려.", NEG, 4),
        ("웹툰·콘텐츠 글로벌 MAU 1억 돌파", "일본·동남아 콘텐츠 플랫폼 합산 MAU 사상 최초 1억 달성.", POS, 3),
        ("클라우드 B2B 매출 전년비 40% 성장", "국내 공공·금융 클라우드 전환 수요 급증으로 기업향 매출 가속화.", POS, 4),
        ("카카오페이 분기 적자 지속…수익 구조 개선 필요", "간편결제 시장 경쟁 심화로 핀테크 계열사 손실 지속.", NEG, 3),
    ],
    "자동차": [
        ("현대·기아, 미국 전기차 IRA 세액공제 전 모델 유지", "인플레이션감축법 세액공제 요건 충족으로 판매 경쟁력 유지.", POS, 4),
        ("유럽 전기차 수요 급감…판매 목표 하향", "EU 충전 인프라 부족·보조금 축소로 유럽 전기차 판매 15% 감소.", NEG, 4),
        ("미국 딜러 인센티브 증가로 수익성 소폭 저하", "재고 증가에 따른 인센티브 확대로 단기 마진 압박.", NEU, 2),
        ("현대차그룹 글로벌 판매 역대 최고 경신 전망", "1~5월 누적 345만 대로 전년비 6% 증가, 연간 기록 경신 가능.", POS, 5),
        ("환율 강세로 수출 채산성 일시 개선", "원·달러 환율 1,360원대 유지로 수출 기업 환차익 발생.", POS, 3),
    ],
    "배터리": [
        ("LFP 배터리 단가 급락…프리미엄 NCM 수요 전환", "LFP 대비 에너지 밀도 우위로 하이엔드 전기차향 NCM 수요 증가.", POS, 4),
        ("배터리 원자재 리튬 가격 30% 반등", "리튬 공급 감소로 수산화리튬 가격이 저점 대비 30% 상승.", NEU, 3),
        ("북미 배터리 공장 가동률 50% 하회…수익성 저하", "전기차 수요 성장 둔화로 조지아·켄터키 합작법인 가동률 부진.", NEG, 4),
        ("전고체 배터리 2027년 양산 로드맵 발표", "전고체 배터리 파일럿 라인 2025년 완공, 2027년 소량 양산 목표.", POS, 3),
        ("ESS 수요 급증으로 비자동차향 매출 확대", "태양광 연계 ESS 프로젝트 수주 급증으로 수익 다각화.", POS, 4),
    ],
    "배터리소재": [
        ("에코프로, 양극재 공급망 수직계열화 완성", "전구체~양극재~리사이클링까지 일관 생산 체계로 원가 경쟁력 확보.", POS, 5),
        ("중국 저가 양극재 공세…마진 압박 심화", "중국 업체 CNGR·BTR의 저가 공세로 국산 양극재 ASP 하락 압박.", NEG, 4),
        ("IRA 핵심광물 요건 충족으로 미국향 수출 확대", "미국 파트너십을 통해 IRA FEOC 요건 충족, 북미 공급망 편입.", POS, 4),
        ("에코프로비엠, 유럽 합작공장 착공", "헝가리 생산법인 착공으로 유럽 OEM 직납 체계 구축 시작.", POS, 3),
        ("양극재 재고 조정 2분기 내 마무리 전망", "재고 소진 속도 개선, 3분기부터 출하량 반등 기대.", NEU, 3),
    ],
    "바이오": [
        ("ADC 항체 신약, FDA 패스트트랙 지정", "차세대 항체-약물 접합체가 FDA 패스트트랙 지정으로 개발 기간 단축 기대.", POS, 5),
        ("바이오시밀러 유럽 승인…글로벌 점유율 확대", "자가면역 바이오시밀러 유럽 EMA 허가로 유럽 매출 2배 확대 전망.", POS, 4),
        ("임상 3상 중간분석 유효성 기준 미달", "주요 파이프라인 임상 3상에서 1차 평가지표 미달…재설계 논의 중.", NEG, 5),
        ("CMO 수주 잔고 2조 돌파…안정적 매출 확보", "글로벌 제약사로부터 바이오의약품 위탁생산 수주 잔고 2조 돌파.", POS, 4),
        ("원료의약품 가격 상승으로 원가 부담 증가", "주요 배지·원료 가격 15% 인상으로 CMO 마진 일시 저하.", NEU, 2),
    ],
    "금융": [
        ("순이자마진(NIM) 유지…대출 성장 4% 전망", "기준금리 동결 기조 속 NIM 안정화로 이자 이익 성장 지속.", POS, 3),
        ("부동산 PF 충당금 추가 적립…단기 이익 감소", "부동산 프로젝트파이낸싱 부실 우려로 충당금 적립 확대.", NEG, 4),
        ("주주 환원 강화…자사주 매입·소각 발표", "밸류업 프로그램 일환으로 연간 순이익의 35% 주주 환원 목표.", POS, 4),
        ("개인 연금·ISA 자금 유입 증가로 수탁 수수료 성장", "금융투자소득세 유예 이후 개인 투자 자금 유입 지속.", POS, 3),
        ("가계부채 총량 규제 강화로 대출 성장 제한", "DSR 3단계 강화로 하반기 신규 대출 수요 위축 전망.", NEG, 3),
    ],
    "에너지": [
        ("정유 마진 반등…크랙 스프레드 확대", "중동 분쟁 우려로 원유 공급 우려 부각, 정유 스프레드 확대.", POS, 4),
        ("국제유가 변동성 확대…실적 예측 불확실", "OPEC+ 감산 vs 미국 증산 엇박자로 유가 변동성 지속.", NEU, 3),
        ("배터리·수소 등 신사업 투자 계획 발표", "탄소중립 대응으로 수소에너지·재생에너지 투자 5년간 3조 계획.", POS, 3),
        ("윤활유 부문 마진 개선…스페셜티 수익 확대", "고마진 특수윤활유 판매 증가로 하반기 이익 개선 기대.", POS, 3),
        ("환경부 탄소배출권 할당 축소…비용 부담 증가", "2026년부터 탄소배출권 무상 할당 60%→40% 축소 예정.", NEG, 3),
    ],
    "화학": [
        ("친환경 소재 수요 급증…고부가 제품 비중 확대", "EV 배터리 케이스·경량화 소재 수요로 고부가 화학 매출 성장.", POS, 4),
        ("중국 화학 업체 저가 공세로 범용 제품 마진 약세", "에틸렌·PO 등 범용 제품 스프레드 역대 최저 수준.", NEG, 4),
        ("납사 가격 하락으로 원가 부담 완화", "원유 하락과 함께 핵심 원료인 납사 가격 15% 하락.", POS, 3),
        ("배터리 전해질 소재 공급 계약 체결", "국내 배터리 셀 메이커와 3년 장기 공급 계약 체결 발표.", POS, 4),
        ("2분기 영업이익 컨센서스 하회 전망", "수요 부진·마진 압박으로 2분기 영업이익 시장 기대치 하회.", NEG, 3),
    ],
    "지주": [
        ("자회사 실적 개선으로 배당 수익 증가 전망", "주요 자회사 영업이익 성장으로 지주 배당 수입 확대 기대.", POS, 3),
        ("비상장 자회사 IPO 추진…기업가치 재평가 기대", "신성장 자회사의 코스피 상장 추진으로 지주 NAV 상승 기대.", POS, 4),
        ("저PBR·고배당 정책으로 밸류업 수혜", "자사주 소각·배당 확대로 밸류업 우수 기업 선정.", POS, 3),
        ("지배구조 개선 요구 압박 지속", "국내외 행동주의 펀드의 이사회 독립성 강화 요구 증가.", NEU, 2),
        ("그룹 내부거래 비율 감소…투명성 개선", "내부거래 비율 전년 대비 5%p 감소, 공정거래법 리스크 완화.", POS, 2),
    ],
    "건설": [
        ("해외 플랜트 대규모 수주…수익성 개선 기대", "중동·동남아 LNG·정유 플랜트 2조 수주로 수주 잔고 사상 최대.", POS, 5),
        ("국내 부동산 경기 침체…신규 분양 부진", "고금리 지속으로 국내 분양 미계약률 상승, 미분양 리스크 확대.", NEG, 4),
        ("원가율 개선…철근·레미콘 가격 안정화", "건설 원자재 가격 안정화로 국내 건축 부문 원가율 1~2%p 개선.", POS, 3),
        ("PF 우발 채무 리스크 관리 강화", "프로젝트 파이낸싱 익스포저 축소 및 충당금 적립 확대.", NEU, 3),
        ("친환경 건설 인증 사업 수주 확대", "그린빌딩·모듈러 주택 수요 증가로 친환경 부문 매출 확대.", POS, 3),
    ],
    "해운": [
        ("홍해 사태 장기화…운임 고공행진 지속", "수에즈 운하 우회 항로 지속으로 컨테이너 운임 급등세 유지.", POS, 5),
        ("글로벌 컨테이너 공급 과잉 우려…중장기 운임 하락 전망", "신규 선박 발주 급증으로 2025년 이후 공급 과잉 전환 우려.", NEG, 4),
        ("연료비 부담 완화…벙커유 가격 하락", "국제유가 하락에 따라 벙커유 비용 감소, 운항 원가 개선.", POS, 3),
        ("아시아-미국 노선 물동량 전년비 12% 증가", "리쇼어링·재고 확충 수요로 태평양 노선 물동량 증가세.", POS, 4),
        ("2024년 배당 축소 결정…현금 보유 전략", "운임 불확실성 대비 배당 축소 및 현금 유보 강화.", NEU, 2),
    ],
    "게임": [
        ("신작 글로벌 동시 출시…해외 매출 급증", "기대작 글로벌 론칭 첫 주 다운로드 1,000만 돌파, 매출 상위권 진입.", POS, 5),
        ("블록체인 게임 규제 완화 기대…NFT 수익 재개", "정부 P2E 게임 가이드라인 발표, 새로운 수익 모델 허용 논의.", POS, 3),
        ("중국 판호 발급 지연…핵심 시장 진출 차질", "중국 당국 판호 심사 강화로 출시 일정 6개월 지연 공식화.", NEG, 4),
        ("구글·애플 수수료 인상 대응 방안 검토", "앱 마켓 수수료 30% 유지 결정으로 모바일 수익성 압박.", NEG, 3),
        ("PC·콘솔 크로스플레이 업데이트로 유저 유입 증가", "크로스플레이 지원 후 DAU 20% 증가, 신규 시즌 패스 판매 호조.", POS, 4),
    ],
    "엔터": [
        ("아티스트 글로벌 투어 사상 최대 규모 발표", "월드 투어 60개 도시 100회 공연 계획으로 공연 매출 최대 전망.", POS, 5),
        ("IP 기반 MD·팝업스토어 매출 급성장", "아티스트 IP 활용 굿즈 및 팝업스토어 매출 전년 대비 80% 증가.", POS, 4),
        ("주요 아티스트 군 입대…공백기 매출 공백", "핵심 그룹 멤버 순차 입대로 18개월 공연·앨범 공백 불가피.", NEG, 4),
        ("OTT 콘텐츠 판매 계약 체결…수익 다각화", "넷플릭스·디즈니+ 대상 드라마·다큐 콘텐츠 공급 계약 체결.", POS, 3),
        ("AI 음원 저작권 분쟁 리스크 부각", "생성형 AI 학습 데이터 저작권 소송 가능성으로 법적 불확실성.", NEU, 2),
    ],
    "전자": [
        ("가전 프리미엄 전략 성공…OLED TV 점유율 1위", "프리미엄 OLED TV 글로벌 점유율 53%로 1위 수성, ASP 상승.", POS, 4),
        ("B2B 솔루션 사업 매출 2조 돌파", "의료·상업용 디스플레이·공조 사업 통합 B2B 매출 역대 최고.", POS, 4),
        ("글로벌 가전 수요 부진…보급형 매출 약세", "경기 침체 우려로 500달러 이하 보급형 가전 수요 감소.", NEG, 3),
        ("스마트홈 플랫폼 구독자 1,000만 돌파", "씽큐 플랫폼 글로벌 구독자 1,000만 돌파로 소프트웨어 수익화 본격화.", POS, 3),
        ("원달러 환율 수혜…수출 채산성 개선", "달러 강세로 미국·유럽 수출 환차익 발생, 영업이익 개선.", POS, 3),
    ],
    "조선": [
        ("LNG선 수주 잔고 역대 최대…2027년까지 물량 확보", "글로벌 LNG 운반선 발주 급증으로 수주 잔고 3년치 이상 확보.", POS, 5),
        ("고부가 선박 비중 증가…수익성 구조 개선", "VLCC·FPSO 등 고부가 선박 비중 70% 돌파로 마진 개선 가속.", POS, 4),
        ("철강 후판 가격 안정화…원가 부담 완화", "주요 원재료인 후판 가격 하락으로 2분기부터 원가율 개선 전망.", POS, 3),
        ("인력 부족…생산 지연 리스크 증가", "용접공·배관공 등 숙련 인력 부족으로 납기 지연 가능성 증가.", NEG, 3),
        ("친환경 암모니아·메탄올 선박 설계 수주", "탄소중립 선박 수요 증가로 차세대 연료 추진 선박 수주 확대.", POS, 4),
    ],
}

# 종목코드 → (종목명, 섹터)
_STOCK_SECTOR: dict[str, tuple[str, str]] = {
    "005930": ("삼성전자",         "반도체"),
    "000660": ("SK하이닉스",       "반도체"),
    "035720": ("카카오",           "IT서비스"),
    "035420": ("NAVER",            "IT서비스"),
    "005380": ("현대차",           "자동차"),
    "000270": ("기아",             "자동차"),
    "051910": ("LG화학",           "화학"),
    "006400": ("삼성SDI",          "배터리"),
    "373220": ("LG에너지솔루션",   "배터리"),
    "207940": ("삼성바이오로직스", "바이오"),
    "068270": ("셀트리온",         "바이오"),
    "003550": ("LG",               "지주"),
    "096770": ("SK이노베이션",     "에너지"),
    "032830": ("삼성생명",         "금융"),
    "055550": ("신한지주",         "금융"),
    "105560": ("KB금융",           "금융"),
    "086790": ("하나금융지주",     "금융"),
    "028260": ("삼성물산",         "건설"),
    "011200": ("HMM",              "해운"),
    "010950": ("S-Oil",            "에너지"),
    "247540": ("에코프로비엠",     "배터리소재"),
    "086520": ("에코프로",         "배터리소재"),
    "091990": ("셀트리온헬스케어", "바이오"),
    "263750": ("펄어비스",         "게임"),
    "112040": ("위메이드",         "게임"),
    "041510": ("에스엠",           "엔터"),
    "035900": ("JYP Ent.",         "엔터"),
    "352820": ("하이브",           "엔터"),
    "066570": ("LG전자",           "전자"),
    "009540": ("HD한국조선해양",   "조선"),
}

_TODAY = date.today()
_DATES = [str(_TODAY - timedelta(days=i)) for i in range(7)]


# ════════════════════════════════════════════════════════════════
# 1. clean_news_text
# ════════════════════════════════════════════════════════════════

def clean_news_text(text: str) -> str:
    """
    뉴스 텍스트에서 HTML 태그, 엔티티, 불필요한 공백을 제거합니다.

    Args:
        text: 원본 텍스트 (HTML 포함 가능)

    Returns:
        정제된 텍스트 문자열
    """
    if not text:
        return ""
    # HTML 태그 제거
    text = re.sub(r"<[^>]+>", "", text)
    # HTML 엔티티 변환
    _ENTITIES = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&nbsp;": " ",
        "&#x27;": "'", "&apos;": "'",
    }
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    # 남은 숫자 엔티티 (예: &#123;)
    text = re.sub(r"&#\d+;", "", text)
    # 연속 공백 정규화
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ════════════════════════════════════════════════════════════════
# 2. classify_news_sentiment
# ════════════════════════════════════════════════════════════════

def classify_news_sentiment(title: str, summary: str = "") -> str:
    """
    제목·요약 키워드 기반으로 뉴스 감성을 분류합니다.

    긍정/부정 키워드 등장 횟수를 비교하며,
    동점이면 "중립"을 반환합니다.

    Args:
        title:   뉴스 제목
        summary: 뉴스 요약 (선택)

    Returns:
        "긍정" | "중립" | "부정"
    """
    text = (title + " " + summary).lower()
    pos = sum(1 for kw in _POS_KEYWORDS if kw in text)
    neg = sum(1 for kw in _NEG_KEYWORDS if kw in text)
    if pos > neg:
        return POS
    if neg > pos:
        return NEG
    return NEU


def _calc_impact_score(title: str, summary: str = "") -> int:
    """영향도 1~5 추정 (고영향 키워드 등장 수 기반)"""
    text = title + " " + summary
    count = sum(1 for kw in _HIGH_IMPACT_KEYWORDS if kw in text)
    return min(5, max(1, 2 + count))


# ════════════════════════════════════════════════════════════════
# 3. fetch_news_from_naver
# ════════════════════════════════════════════════════════════════

def fetch_news_from_naver(
    stock_name: str,
    days: int = 30,
    max_items: int = 10,
    stock_code: str = "",
) -> list[dict]:
    """
    네이버 뉴스 API로 종목 관련 최신 뉴스를 수집합니다.

    NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 없으면 빈 리스트를 반환합니다.
    API 오류가 발생해도 앱이 중단되지 않습니다.

    Args:
        stock_name: 검색 키워드 (종목명)
        days:       최근 N일 이내 뉴스만 포함 (기본 30일)
        max_items:  최대 반환 건수 (기본 10)
        stock_code: 종목코드 (메타 정보용, 선택)

    Returns:
        뉴스 딕셔너리 리스트. 각 항목에 source="Naver" 포함.
        빈 리스트 = 키 없음 또는 오류.
    """
    try:
        from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
    except ImportError:
        NAVER_CLIENT_ID = NAVER_CLIENT_SECRET = None

    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        logger.debug("[뉴스] Naver API 키 없음 → Mock 폴백")
        return []

    import requests  # lazy import — 설치 안 돼도 safe

    _API_URL = "https://openapi.naver.com/v1/search/news.json"
    cutoff   = date.today() - timedelta(days=days)

    try:
        resp = requests.get(
            _API_URL,
            headers={
                "X-Naver-Client-Id":     NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
            },
            params={
                "query":   f"{stock_name} 주식",
                "display": min(max_items * 2, 100),  # 필터 여유분
                "sort":    "date",
            },
            timeout=5,
        )
        resp.raise_for_status()
        raw_items = resp.json().get("items", [])
    except Exception as e:
        logger.warning("[뉴스] Naver API 오류 (%s): %s", stock_name, e)
        return []

    results: list[dict] = []
    for item in raw_items:
        title   = clean_news_text(item.get("title",       ""))
        summary = clean_news_text(item.get("description", ""))
        url     = item.get("originallink", "") or item.get("link", "")
        pub_str = item.get("pubDate", "")

        # 날짜 파싱
        news_date = _parse_pub_date(pub_str)

        # days 필터
        try:
            if datetime.strptime(news_date, "%Y-%m-%d").date() < cutoff:
                continue
        except ValueError:
            pass

        if not title:
            continue

        results.append({
            "stock_code":   stock_code,
            "stock_name":   stock_name,
            "title":        title,
            "summary":      summary[:200] if summary else "",
            "sentiment":    classify_news_sentiment(title, summary),
            "impact_score": _calc_impact_score(title, summary),
            "news_date":    news_date,
            "url":          url,
            "source":       "Naver",
        })

        if len(results) >= max_items:
            break

    logger.info("[뉴스] Naver 수집 완료: %s → %d건", stock_name, len(results))
    return results


def _parse_pub_date(pub_date: str) -> str:
    """네이버 pubDate (RFC 2822) → YYYY-MM-DD"""
    try:
        dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
        return str(dt.date())
    except Exception:
        return str(date.today())


# ════════════════════════════════════════════════════════════════
# 4. summarize_news_sentiment
# ════════════════════════════════════════════════════════════════

def summarize_news_sentiment(news_items: list[dict]) -> dict[str, Any]:
    """
    뉴스 리스트의 감성을 집계합니다.

    Args:
        news_items: get_news_for_stock() 반환 리스트

    Returns:
        {
            "긍정": int,
            "중립": int,
            "부정": int,
            "합계": int,
            "대표_감성": "긍정" | "중립" | "부정",
            "출처": "Naver" | "Mock" | "혼합",
        }
    """
    counts = {POS: 0, NEU: 0, NEG: 0}
    sources: set[str] = set()

    for item in news_items:
        s = item.get("sentiment", NEU)
        if s in counts:
            counts[s] += 1
        src = item.get("source", "Mock")
        sources.add(src)

    total = sum(counts.values())

    # 대표 감성: 최다 득표, 동점이면 중립
    dominant = NEU
    if total > 0:
        sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        if sorted_counts[0][1] > sorted_counts[1][1]:
            dominant = sorted_counts[0][0]

    # 출처 레이블
    if sources == {"Naver"}:
        source_label = "Naver"
    elif "Naver" in sources:
        source_label = "혼합"
    else:
        source_label = "Mock"

    return {
        POS:         counts[POS],
        NEU:         counts[NEU],
        NEG:         counts[NEG],
        "합계":      total,
        "대표_감성": dominant,
        "출처":      source_label,
    }


# ════════════════════════════════════════════════════════════════
# 5. save_news_to_supabase
# ════════════════════════════════════════════════════════════════

def save_news_to_supabase(news_items: list[dict]) -> dict[str, Any]:
    """
    뉴스 아이템을 Supabase news_articles 테이블에 저장합니다.

    중복 제거: (stock_code, title, news_date) 기준 upsert.
    Supabase 미연결 또는 테이블 미생성 시 조용히 실패합니다.

    Args:
        news_items: get_news_for_stock() 반환 리스트

    Returns:
        {"saved": int, "skipped": int, "error": str | None}

    Note:
        news_articles 테이블이 없으면 Supabase에서 에러가 발생합니다.
        sql/schema_v3.sql 을 실행해 테이블을 먼저 생성하세요.
    """
    if not news_items:
        return {"saved": 0, "skipped": 0, "error": None}

    try:
        from services.supabase_client import get_client, is_connected
        if not is_connected():
            return {"saved": 0, "skipped": len(news_items), "error": "Supabase 미연결"}

        client = get_client()
        rows = [
            {
                "stock_code":   item.get("stock_code",   ""),
                "stock_name":   item.get("stock_name",   ""),
                "title":        item.get("title",        "")[:500],
                "summary":      item.get("summary",      "")[:1000],
                "sentiment":    item.get("sentiment",    NEU),
                "impact_score": int(item.get("impact_score", 3)),
                "news_date":    item.get("news_date",    str(date.today())),
                "url":          item.get("url",          "")[:500],
                "source":       item.get("source",       "Mock"),
            }
            for item in news_items
            if item.get("title")
        ]

        saved = 0
        batch_size = 30
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            client.table("news_articles").upsert(
                batch,
                on_conflict="stock_code,title,news_date",
            ).execute()
            saved += len(batch)

        logger.info("[뉴스] Supabase 저장: %d건", saved)
        return {"saved": saved, "skipped": 0, "error": None}

    except Exception as e:
        logger.warning("[뉴스] Supabase 저장 실패: %s", e)
        return {"saved": 0, "skipped": len(news_items), "error": str(e)}


# ════════════════════════════════════════════════════════════════
# 6. get_news_for_stock  (메인 진입점)
# ════════════════════════════════════════════════════════════════

def get_news_for_stock(
    stock_code: str | None = None,
    stock_name: str | None = None,
    days: int = 30,
    max_items: int = 10,
) -> list[dict]:
    """
    종목 뉴스를 수집합니다. Naver API 우선, 없으면 Mock 폴백.

    우선순위:
        1. Naver News API (NAVER_CLIENT_ID + NAVER_CLIENT_SECRET)
        2. Mock 뉴스 (섹터별 템플릿)

    모든 뉴스 항목에 source 필드("Naver" 또는 "Mock")가 포함됩니다.
    이 필드를 UI에서 사용해 실제/Mock 데이터 여부를 표시하세요.

    Args:
        stock_code: 6자리 종목코드 (예: "005930")
        stock_name: 종목명 (stock_code 없을 때 사용)
        days:       최근 N일 이내 뉴스 (Naver API 필터, 기본 30일)
        max_items:  최대 반환 건수 (기본 10)

    Returns:
        뉴스 딕셔너리 리스트, news_date 내림차순.
        각 항목: stock_code, stock_name, title, summary,
                 sentiment, impact_score, news_date, url, source
    """
    code = str(stock_code).zfill(6) if stock_code else ""
    name = stock_name or ""

    # 종목명 보완 (code → name)
    if code and not name and code in _STOCK_SECTOR:
        name = _STOCK_SECTOR[code][0]

    # 1순위: Naver API
    if name:
        naver_items = fetch_news_from_naver(
            stock_name=name,
            days=days,
            max_items=max_items,
            stock_code=code,
        )
        if naver_items:
            deduped = _dedup(naver_items)
            logger.info("[뉴스] %s Naver 사용: %d건", name, len(deduped))
            return sorted(deduped, key=lambda x: x["news_date"], reverse=True)

    # 2순위: Mock
    mock_items = get_mock_news(stock_code=code or None, stock_name=name or None)
    logger.info("[뉴스] %s Mock 사용: %d건", name or code, len(mock_items))
    return mock_items


def _dedup(news_items: list[dict]) -> list[dict]:
    """URL 또는 제목 기준 중복 제거"""
    seen: set[str] = set()
    result: list[dict] = []
    for item in news_items:
        url   = (item.get("url")   or "").strip()
        title = (item.get("title") or "").strip()
        key   = url if url else title
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


# ════════════════════════════════════════════════════════════════
# Mock 뉴스 내부 생성기
# ════════════════════════════════════════════════════════════════

def _make_news_items(
    stock_code: str,
    stock_name: str,
    sector: str,
    count: int,
    seed: int,
) -> list[dict]:
    rng       = random.Random(seed)
    templates = _SECTOR_TEMPLATES.get(sector, _SECTOR_TEMPLATES["IT서비스"])
    chosen    = rng.sample(templates, min(count, len(templates)))
    if len(chosen) < count:
        chosen += rng.choices(templates, k=count - len(chosen))

    items = []
    for title, summary, sentiment, impact_score in chosen:
        full_title = (
            f"{stock_name}, {title[0].lower()}{title[1:]}"
            if rng.random() > 0.4 else title
        )
        items.append({
            "stock_code":   stock_code,
            "stock_name":   stock_name,
            "title":        full_title,
            "summary":      summary,
            "sentiment":    sentiment,
            "impact_score": impact_score,
            "news_date":    rng.choice(_DATES),
            "url":          "",
            "source":       "Mock",
        })
    return items


# ════════════════════════════════════════════════════════════════
# 하위호환 공개 함수 (기존 코드 호환)
# ════════════════════════════════════════════════════════════════

def get_mock_news(
    stock_code: str | None = None,
    stock_name: str | None = None,
) -> list[dict]:
    """Mock 뉴스 반환 (하위호환). source="Mock" 포함."""
    if stock_code:
        if stock_code not in _STOCK_SECTOR:
            return []
        name, sector = _STOCK_SECTOR[stock_code]
        seed  = int(stock_code) % 9999
        count = (seed % 3) + 3
        return sorted(
            _make_news_items(stock_code, name, sector, count, seed),
            key=lambda x: x["news_date"],
            reverse=True,
        )

    if stock_name:
        matched = {
            code: (nm, sec)
            for code, (nm, sec) in _STOCK_SECTOR.items()
            if nm == stock_name
        }
        if not matched:
            return []
        code, _ = next(iter(matched.items()))
        return get_mock_news(stock_code=code)

    all_news: list[dict] = []
    for code, (name, sector) in _STOCK_SECTOR.items():
        seed  = int(code) % 9999
        count = (seed % 3) + 3
        all_news.extend(_make_news_items(code, name, sector, count, seed))
    return sorted(all_news, key=lambda x: x["news_date"], reverse=True)


def get_news(
    stock_code: str | None = None,
    stock_name: str | None = None,
    display: int = 10,
) -> list[dict]:
    """실 뉴스 우선 조회 (하위호환). get_news_for_stock() 위임."""
    return get_news_for_stock(
        stock_code=stock_code,
        stock_name=stock_name,
        max_items=display,
    )


def get_news_summary(news: list[dict]) -> dict[str, int]:
    """감성별 건수 집계 (하위호환). summarize_news_sentiment() 위임."""
    s = summarize_news_sentiment(news)
    return {POS: s[POS], NEU: s[NEU], NEG: s[NEG], "합계": s["합계"]}


