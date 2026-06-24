"""
strategy/scanner.py  –  후보 종목 점수화 스캐너

입력:  market_data DataFrame  (services/market_data.py 형식)
출력:  score DataFrame  (stock_code, stock_name, score, decision, reasons, risks)

점수 규칙 (총 가산 100점, 감산 -35점 가능):
    +20  거래대금 100억 이상
    +20  거래량이 20일 평균 거래량 대비 2배 이상
    +15  종가 > MA5
    +15  종가 > MA20
    +10  MA5 > MA20  (정배열)
    +10  전일 양봉  (close >= open)
    +10  뉴스 1건 이상
    -15  전일 등락률 20% 이상  (급등 추격 위험)
    -10  부채비율 200% 이상
    -10  PER 음수 또는 ROE 음수  (적자 기업)

판단:
    80 이상 → 관심
    60 이상 → 관찰
    40 이상 → 보류
    40 미만  → 제외
"""

from __future__ import annotations

import pandas as pd


# ── 점수 규칙 정의 ────────────────────────────────────────────

_RULES: list[dict] = [
    {
        "key":       "trading_value_100",
        "points":    20,
        "condition": lambda r: r["trading_value"] >= 100,
        "reason":    "거래대금 100억 이상 (+20)",
        "risk":      None,
    },
    {
        "key":       "volume_surge",
        "points":    20,
        "condition": lambda r: r["avg_volume_20d"] > 0 and r["volume"] >= r["avg_volume_20d"] * 2,
        "reason":    "거래량 20일 평균 2배 이상 (+20)",
        "risk":      None,
    },
    {
        "key":       "close_above_ma5",
        "points":    15,
        "condition": lambda r: r["close"] > r["ma5"],
        "reason":    "종가가 MA5 위 (+15)",
        "risk":      None,
    },
    {
        "key":       "close_above_ma20",
        "points":    15,
        "condition": lambda r: r["close"] > r["ma20"],
        "reason":    "종가가 MA20 위 (+15)",
        "risk":      None,
    },
    {
        "key":       "ma5_above_ma20",
        "points":    10,
        "condition": lambda r: r["ma5"] > r["ma20"],
        "reason":    "MA5 > MA20 정배열 (+10)",
        "risk":      None,
    },
    {
        "key":       "bullish_candle",
        "points":    10,
        "condition": lambda r: r["close"] >= r["open"],
        "reason":    "양봉 마감 (+10)",
        "risk":      None,
    },
    {
        "key":       "has_news",
        "points":    10,
        "condition": lambda r: r["news_count"] >= 1,
        "reason":    f"관련 뉴스 존재 (+10)",
        "risk":      None,
    },
    # ── 감점 규칙 ──────────────────────────────────────────────
    {
        "key":       "surge_risk",
        "points":    -15,
        "condition": lambda r: r["change_rate"] >= 20,
        "reason":    None,
        "risk":      f"당일 등락률 20% 이상 — 추격 매수 위험 (-15)",
    },
    {
        "key":       "high_debt",
        "points":    -10,
        "condition": lambda r: r["debt_ratio"] >= 200,
        "reason":    None,
        "risk":      "부채비율 200% 이상 — 재무 레버리지 높음 (-10)",
    },
    {
        "key":       "negative_fundamentals",
        "points":    -10,
        "condition": lambda r: r["per"] < 0 or r["roe"] < 0,
        "reason":    None,
        "risk":      "PER 또는 ROE 음수 — 적자 기업 (-10)",
    },
]

_DECISION_MAP = [
    (80, "관심"),
    (60, "관찰"),
    (40, "보류"),
    (0,  "제외"),
]

_DECISION_COLOR = {
    "관심": "#27AE60",
    "관찰": "#F39C12",
    "보류": "#95A5A6",
    "제외": "#E74C3C",
}


def _score_row(row: pd.Series) -> dict:
    """단일 종목 행을 점수화하고 결과 딕셔너리를 반환합니다."""
    score = 0
    reasons: list[str] = []
    risks: list[str] = []

    for rule in _RULES:
        try:
            triggered = rule["condition"](row)
        except Exception:
            triggered = False

        if triggered:
            score += rule["points"]
            if rule["reason"]:
                reasons.append(rule["reason"])
            if rule["risk"]:
                risks.append(rule["risk"])

    # 점수 범위 클램핑: 이론 최대 100, 이론 최소 -35 → 0으로 floor
    score = max(0, score)

    # 판단 결정
    decision = "제외"
    for threshold, label in _DECISION_MAP:
        if score >= threshold:
            decision = label
            break

    return {
        "stock_code": row["stock_code"],
        "stock_name": row["stock_name"],
        "score":      score,
        "decision":   decision,
        "reasons":    reasons,
        "risks":      risks,
    }


def scan(market_data: pd.DataFrame) -> pd.DataFrame:
    """
    market_data DataFrame을 받아 후보 종목 점수 DataFrame을 반환합니다.

    반환 컬럼:
        stock_code, stock_name, score, decision, reasons, risks
    결과는 score 내림차순으로 정렬됩니다.
    """
    records = [_score_row(row) for _, row in market_data.iterrows()]
    result = pd.DataFrame(records)
    return result.sort_values("score", ascending=False).reset_index(drop=True)


def get_decision_color(decision: str) -> str:
    """판단 레이블에 해당하는 색상 코드를 반환합니다."""
    return _DECISION_COLOR.get(decision, "#888888")
