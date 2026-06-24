"""
Mock 재무 요약 모듈
실제 재무데이터 API 연동 전까지 Mock 수치를 생성합니다.
"""

import random


def get_financial_summary(code: str, name: str) -> dict:
    """종목 재무 요약 반환 (Mock)"""
    random.seed(int(code) % 9999)

    revenue_q = [
        round(random.uniform(1.0, 30.0), 1) for _ in range(4)
    ]
    profit_q = [
        round(r * random.uniform(0.03, 0.18), 1) for r in revenue_q
    ]
    quarters = ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]

    yoy_rev = round(random.uniform(-10, 35), 1)
    yoy_profit = round(random.uniform(-15, 50), 1)
    per = round(random.uniform(8, 45), 1)
    pbr = round(random.uniform(0.5, 4.0), 2)
    roe = round(random.uniform(3, 25), 1)
    debt = round(random.uniform(20, 150), 1)
    dividend_yield = round(random.uniform(0, 4.0), 2)

    comment = _gen_comment(yoy_rev, yoy_profit, roe, per)

    return {
        "quarters": quarters,
        "revenue_q": revenue_q,        # 분기 매출 (조원)
        "profit_q": profit_q,          # 분기 영업이익
        "yoy_revenue_growth": yoy_rev,
        "yoy_profit_growth": yoy_profit,
        "per": per,
        "pbr": pbr,
        "roe": roe,
        "debt_ratio": debt,
        "dividend_yield": dividend_yield,
        "comment": comment,
        "source": "Mock",
    }


def _gen_comment(yoy_rev: float, yoy_profit: float, roe: float, per: float) -> str:
    parts = []

    if yoy_rev > 15:
        parts.append(f"매출이 전년 대비 {yoy_rev}% 성장하며 외형 확장세를 이어가고 있습니다.")
    elif yoy_rev > 0:
        parts.append(f"매출은 전년 대비 {yoy_rev}% 소폭 증가했습니다.")
    else:
        parts.append(f"매출은 전년 대비 {abs(yoy_rev)}% 감소하며 역성장 구간에 있습니다.")

    if yoy_profit > 20:
        parts.append(f"영업이익은 {yoy_profit}% 급증, 수익성이 크게 개선되었습니다.")
    elif yoy_profit > 0:
        parts.append(f"영업이익도 {yoy_profit}% 증가, 수익성 회복 흐름입니다.")
    else:
        parts.append(f"영업이익은 {abs(yoy_profit)}% 감소하여 수익성 압박이 있습니다.")

    if roe >= 15:
        parts.append(f"ROE {roe}%로 자본 효율이 우수합니다.")
    if per < 12:
        parts.append(f"PER {per}배로 저평가 구간으로 볼 수 있습니다.")
    elif per > 35:
        parts.append(f"PER {per}배로 성장 프리미엄이 높게 반영된 상태입니다.")

    return " ".join(parts)
