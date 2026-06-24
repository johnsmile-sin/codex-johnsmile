"""
샘플 종목 30개 Mock 데이터
실제 API 연동 전에 앱을 테스트할 때 사용합니다.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

random.seed(42)
np.random.seed(42)


MOCK_STOCKS = [
    {"code": "005930", "name": "삼성전자",    "sector": "반도체",   "market": "KOSPI"},
    {"code": "000660", "name": "SK하이닉스",  "sector": "반도체",   "market": "KOSPI"},
    {"code": "035720", "name": "카카오",      "sector": "IT서비스", "market": "KOSPI"},
    {"code": "035420", "name": "NAVER",       "sector": "IT서비스", "market": "KOSPI"},
    {"code": "005380", "name": "현대차",      "sector": "자동차",   "market": "KOSPI"},
    {"code": "000270", "name": "기아",        "sector": "자동차",   "market": "KOSPI"},
    {"code": "051910", "name": "LG화학",      "sector": "화학",     "market": "KOSPI"},
    {"code": "006400", "name": "삼성SDI",     "sector": "배터리",   "market": "KOSPI"},
    {"code": "373220", "name": "LG에너지솔루션","sector": "배터리",  "market": "KOSPI"},
    {"code": "207940", "name": "삼성바이오로직스","sector": "바이오", "market": "KOSPI"},
    {"code": "068270", "name": "셀트리온",    "sector": "바이오",   "market": "KOSPI"},
    {"code": "003550", "name": "LG",          "sector": "지주",     "market": "KOSPI"},
    {"code": "096770", "name": "SK이노베이션","sector": "에너지",   "market": "KOSPI"},
    {"code": "032830", "name": "삼성생명",    "sector": "금융",     "market": "KOSPI"},
    {"code": "055550", "name": "신한지주",    "sector": "금융",     "market": "KOSPI"},
    {"code": "105560", "name": "KB금융",      "sector": "금융",     "market": "KOSPI"},
    {"code": "086790", "name": "하나금융지주","sector": "금융",     "market": "KOSPI"},
    {"code": "028260", "name": "삼성물산",    "sector": "건설",     "market": "KOSPI"},
    {"code": "011200", "name": "HMM",         "sector": "해운",     "market": "KOSPI"},
    {"code": "010950", "name": "S-Oil",       "sector": "에너지",   "market": "KOSPI"},
    {"code": "247540", "name": "에코프로비엠","sector": "배터리소재","market": "KOSDAQ"},
    {"code": "086520", "name": "에코프로",    "sector": "배터리소재","market": "KOSDAQ"},
    {"code": "091990", "name": "셀트리온헬스케어","sector": "바이오","market": "KOSDAQ"},
    {"code": "263750", "name": "펄어비스",    "sector": "게임",     "market": "KOSDAQ"},
    {"code": "112040", "name": "위메이드",    "sector": "게임",     "market": "KOSDAQ"},
    {"code": "041510", "name": "에스엠",      "sector": "엔터",     "market": "KOSDAQ"},
    {"code": "035900", "name": "JYP Ent.",    "sector": "엔터",     "market": "KOSDAQ"},
    {"code": "352820", "name": "하이브",      "sector": "엔터",     "market": "KOSPI"},
    {"code": "066570", "name": "LG전자",      "sector": "전자",     "market": "KOSPI"},
    {"code": "009540", "name": "HD한국조선해양","sector": "조선",   "market": "KOSPI"},
]


def _gen_price(base: int) -> dict:
    """현재가, 전일 대비, 거래량 등을 랜덤 생성"""
    change_pct = round(random.uniform(-5.0, 7.0), 2)
    prev_close = base
    current = int(prev_close * (1 + change_pct / 100))
    volume = random.randint(100_000, 10_000_000)
    return {
        "current_price": current,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "volume": volume,
        "high_52w": int(current * random.uniform(1.0, 1.5)),
        "low_52w": int(current * random.uniform(0.5, 1.0)),
    }


def _gen_technical() -> dict:
    """기술적 지표 Mock"""
    rsi = round(random.uniform(20, 80), 1)
    macd_signal = random.choice(["골든크로스", "데드크로스", "중립"])
    ma5_above_ma20 = random.choice([True, False])
    bb_position = round(random.uniform(0, 100), 1)  # 볼린저밴드 위치(%)
    return {
        "rsi": rsi,
        "macd_signal": macd_signal,
        "ma5_above_ma20": ma5_above_ma20,
        "bb_position": bb_position,
    }


def _gen_fundamental() -> dict:
    """기본적 지표 Mock"""
    return {
        "per": round(random.uniform(5, 60), 1),
        "pbr": round(random.uniform(0.3, 5.0), 2),
        "roe": round(random.uniform(-5, 30), 1),
        "debt_ratio": round(random.uniform(10, 200), 1),
        "revenue_growth": round(random.uniform(-20, 40), 1),
    }


# 종목별 기준 가격
_BASE_PRICES = {
    "005930": 75000, "000660": 185000, "035720": 52000, "035420": 220000,
    "005380": 240000, "000270": 95000, "051910": 420000, "006400": 380000,
    "373220": 390000, "207940": 850000, "068270": 170000, "003550": 88000,
    "096770": 210000, "032830": 72000, "055550": 40000, "105560": 65000,
    "086790": 52000, "028260": 140000, "011200": 18000, "010950": 78000,
    "247540": 280000, "086520": 105000, "091990": 28000, "263750": 32000,
    "112040": 24000, "041510": 92000, "035900": 88000, "352820": 240000,
    "066570": 110000, "009540": 175000,
}


def get_mock_stock_list() -> pd.DataFrame:
    """Mock 종목 30개 DataFrame 반환"""
    rows = []
    for s in MOCK_STOCKS:
        price = _gen_price(_BASE_PRICES.get(s["code"], 50000))
        tech = _gen_technical()
        fund = _gen_fundamental()
        rows.append({
            "종목코드": s["code"],
            "종목명": s["name"],
            "섹터": s["sector"],
            "시장": s["market"],
            **price,
            **tech,
            **fund,
        })
    return pd.DataFrame(rows)
