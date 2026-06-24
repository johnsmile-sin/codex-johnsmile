"""
샘플 시장 데이터 생성 모듈
get_sample_market_data() → pandas DataFrame (30종목)

수치는 고정 시드(42)를 사용해 항상 동일한 값을 반환합니다.
실제 API 연동 전 UI/로직 테스트에 사용합니다.
"""

import numpy as np
import pandas as pd

# ── 종목 마스터 정의 ──────────────────────────────────────────
# (code, name, market, sector, base_price, avg_vol, per_mid, pbr_mid, roe_mid, debt_mid)
_STOCK_MASTER = [
    # 반도체
    ("005930", "삼성전자",        "KOSPI",  "반도체",    75_000, 12_000_000, 14.5, 1.4, 18.2, 70),
    ("000660", "SK하이닉스",      "KOSPI",  "반도체",   185_000,  3_500_000, 20.1, 2.1, 14.8, 95),
    # IT서비스
    ("035720", "카카오",          "KOSPI",  "IT서비스",  52_000,  2_800_000, 38.4, 1.6,  6.2, 55),
    ("035420", "NAVER",           "KOSPI",  "IT서비스", 220_000,    900_000, 30.2, 2.8, 12.4, 40),
    # 자동차
    ("005380", "현대차",          "KOSPI",  "자동차",   240_000,    600_000,  6.4, 0.7, 14.5, 145),
    ("000270", "기아",            "KOSPI",  "자동차",    95_000,  1_200_000,  5.8, 0.9, 20.1, 120),
    # 화학·배터리
    ("051910", "LG화학",          "KOSPI",  "화학",     420_000,    250_000, 22.8, 1.5,  8.3, 80),
    ("006400", "삼성SDI",         "KOSPI",  "배터리",   380_000,    310_000, 25.4, 1.9,  9.7, 60),
    ("373220", "LG에너지솔루션",  "KOSPI",  "배터리",   390_000,    700_000, 45.2, 3.2,  8.1, 50),
    # 바이오
    ("207940", "삼성바이오로직스","KOSPI",  "바이오",   850_000,    140_000, 55.6, 6.8, 14.2, 30),
    ("068270", "셀트리온",        "KOSPI",  "바이오",   170_000,    800_000, 32.1, 3.1, 10.3, 45),
    # 지주
    ("003550", "LG",              "KOSPI",  "지주",      88_000,    350_000,  9.2, 0.5,  6.8, 90),
    # 에너지
    ("096770", "SK이노베이션",    "KOSPI",  "에너지",   210_000,    400_000, 18.5, 0.9,  5.4, 110),
    ("010950", "S-Oil",           "KOSPI",  "에너지",    78_000,    450_000, 12.3, 1.1,  9.6, 130),
    # 금융
    ("032830", "삼성생명",        "KOSPI",  "금융",      72_000,    280_000,  8.4, 0.6,  8.1, 85),
    ("055550", "신한지주",        "KOSPI",  "금융",      40_000,  1_100_000,  6.2, 0.5, 10.4, 75),
    ("105560", "KB금융",          "KOSPI",  "금융",      65_000,    900_000,  5.8, 0.6, 11.2, 70),
    ("086790", "하나금융지주",    "KOSPI",  "금융",      52_000,    700_000,  4.9, 0.5, 12.1, 72),
    # 건설·해운
    ("028260", "삼성물산",        "KOSPI",  "건설",     140_000,    300_000, 12.8, 0.9,  7.8, 100),
    ("011200", "HMM",             "KOSPI",  "해운",      18_000,  4_000_000, 10.2, 0.5, 28.4, 30),
    # 배터리소재 (KOSDAQ)
    ("247540", "에코프로비엠",    "KOSDAQ", "배터리소재",280_000,    500_000, 42.5, 5.8, 18.2, 40),
    ("086520", "에코프로",        "KOSDAQ", "배터리소재",105_000,    650_000, 60.2, 7.1, 14.6, 35),
    # 바이오 (KOSDAQ)
    ("091990", "셀트리온헬스케어","KOSDAQ", "바이오",    28_000,  1_200_000, 28.4, 2.4,  9.8, 55),
    # 게임 (KOSDAQ)
    ("263750", "펄어비스",        "KOSDAQ", "게임",      32_000,    900_000, 35.1, 2.9,  8.3, 20),
    ("112040", "위메이드",        "KOSDAQ", "게임",      24_000,  1_500_000, 48.6, 3.2,  5.1, 45),
    # 엔터
    ("041510", "에스엠",          "KOSDAQ", "엔터",      92_000,    400_000, 22.3, 3.4, 16.2, 50),
    ("035900", "JYP Ent.",        "KOSDAQ", "엔터",      88_000,    350_000, 20.5, 4.1, 22.4, 30),
    ("352820", "하이브",          "KOSPI",  "엔터",     240_000,    280_000, 28.7, 3.6, 14.8, 40),
    # 전자·조선
    ("066570", "LG전자",          "KOSPI",  "전자",     110_000,    900_000, 14.8, 1.0,  8.4, 115),
    ("009540", "HD한국조선해양",  "KOSPI",  "조선",     175_000,    600_000, 18.2, 1.8, 12.6, 80),
]


def _round_price(price: float) -> int:
    """한국 주식 호가 단위로 반올림"""
    if price >= 500_000:
        unit = 1_000
    elif price >= 100_000:
        unit = 500
    elif price >= 50_000:
        unit = 100
    elif price >= 10_000:
        unit = 50
    elif price >= 5_000:
        unit = 10
    else:
        unit = 5
    return int(round(price / unit) * unit)


def get_sample_market_data() -> pd.DataFrame:
    """
    샘플 시장 데이터 30종목을 DataFrame으로 반환합니다.

    컬럼:
        stock_code, stock_name, market, sector,
        current_price, prev_close, open, high, low, close,
        change_rate, volume, avg_volume_20d, trading_value,
        ma5, ma20, ma60,
        per, pbr, roe, debt_ratio, news_count
    """
    rng = np.random.default_rng(42)  # 고정 시드 → 항상 동일한 결과
    rows = []

    for (
        code, name, market, sector,
        base_price, base_vol,
        per_mid, pbr_mid, roe_mid, debt_mid,
    ) in _STOCK_MASTER:

        # ── 가격 생성 ──────────────────────────────────────
        # 당일 등락률: -5% ~ +7% (한국 시장 일반 범위)
        change_rate = round(float(rng.uniform(-5.0, 7.0)), 2)

        prev_close  = base_price
        close       = _round_price(prev_close * (1 + change_rate / 100))
        open_price  = _round_price(prev_close * (1 + float(rng.uniform(-0.8, 0.8)) / 100))

        # high: max(open, close)보다 0~2% 위
        high = _round_price(max(open_price, close) * (1 + float(rng.uniform(0, 2.0)) / 100))
        # low: min(open, close)보다 0~2% 아래
        low  = _round_price(min(open_price, close) * (1 - float(rng.uniform(0, 2.0)) / 100))

        current_price = close  # 장 마감 기준

        # ── 이동평균 ────────────────────────────────────────
        # 추세 방향 결정 (60% 상승 추세, 40% 하락 추세)
        uptrend = rng.random() < 0.6
        if uptrend:
            # 정배열: MA5 ≈ close, MA20 < MA5, MA60 < MA20
            ma5  = _round_price(close  * (1 + float(rng.uniform(-1.5,  1.5)) / 100))
            ma20 = _round_price(close  * (1 + float(rng.uniform(-4.0, -0.5)) / 100))
            ma60 = _round_price(close  * (1 + float(rng.uniform(-9.0, -2.0)) / 100))
        else:
            # 역배열: MA5 ≈ close, MA20 > MA5, MA60 > MA20
            ma5  = _round_price(close  * (1 + float(rng.uniform(-1.5,  1.5)) / 100))
            ma20 = _round_price(close  * (1 + float(rng.uniform( 0.5,  4.0)) / 100))
            ma60 = _round_price(close  * (1 + float(rng.uniform( 2.0,  9.0)) / 100))

        # ── 거래량 ──────────────────────────────────────────
        # 당일 거래량: 기준 거래량의 60%~180%
        volume = int(base_vol * float(rng.uniform(0.6, 1.8)))
        # 20일 평균 거래량: 기준의 80%~120%
        avg_volume_20d = int(base_vol * float(rng.uniform(0.8, 1.2)))
        # 거래대금 (억원): volume × 평균가 / 1억
        trading_value = round(volume * current_price / 1e8, 1)

        # ── 기본적 지표 ─────────────────────────────────────
        per        = round(float(rng.uniform(per_mid  * 0.7, per_mid  * 1.3)), 1)
        pbr        = round(float(rng.uniform(pbr_mid  * 0.7, pbr_mid  * 1.3)), 2)
        roe        = round(float(rng.uniform(roe_mid  * 0.6, roe_mid  * 1.4)), 1)
        debt_ratio = round(float(rng.uniform(debt_mid * 0.8, debt_mid * 1.2)), 1)

        # ── 뉴스 건수 ────────────────────────────────────────
        news_count = int(rng.integers(0, 12))

        rows.append({
            "stock_code":     code,
            "stock_name":     name,
            "market":         market,
            "sector":         sector,
            "current_price":  current_price,
            "prev_close":     prev_close,
            "open":           open_price,
            "high":           high,
            "low":            low,
            "close":          close,
            "change_rate":    change_rate,
            "volume":         volume,
            "avg_volume_20d": avg_volume_20d,
            "trading_value":  trading_value,   # 억원
            "ma5":            ma5,
            "ma20":           ma20,
            "ma60":           ma60,
            "per":            per,
            "pbr":            pbr,
            "roe":            roe,
            "debt_ratio":     debt_ratio,
            "news_count":     news_count,
        })

    return pd.DataFrame(rows)
