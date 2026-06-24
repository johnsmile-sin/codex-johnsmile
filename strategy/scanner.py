"""
strategy/scanner.py v2  —  후보 종목 점수화 스캐너

══════════════════════════════════════════════════════════════
점수 규칙 v2
══════════════════════════════════════════════════════════════

[기존 유지]
    +20  거래대금 100억 이상
    +20  거래량 20일 평균 대비 2배 이상
    +15  종가 > MA5
    +15  종가 > MA20
    +10  MA5 > MA20 (정배열)
    +10  전일 양봉 (close >= open)
    +10  관련 뉴스 1건 이상
    -15  등락률 20% 이상  (급등 추격 위험)
    -10  부채비율 200% 이상
    -10  PER 음수 또는 ROE 음수

[신규 추가]
    +10  종가 > MA60
    +10  RSI 45~70  (건강한 모멘텀 구간)
    -10  RSI 75 이상  (과매수 경고)
    +15  거래대금 20일 평균 대비 2배 이상
    +15  최근 20일 신고가 돌파
    +10  최근 3일 연속 상승
    +10  뉴스 심리 긍정
    -15  뉴스 심리 부정
    -20  부채비율 300% 이상  (기존 -10 과 합산 = -30)
    -15  최근 순이익 적자

[판단 기준 v2]
    90 이상 → 강한 관심
    75 이상 → 관심
    60 이상 → 관찰
    40 이상 → 보류
    40 미만  → 제외

[data_quality]
    실제 데이터  : 가격·재무·뉴스 모두 실데이터
    일부 Mock    : 일부 실데이터, 일부 Mock
    Mock         : 전체 Mock (투자 결정에 사용 금지)
"""

from __future__ import annotations

import pandas as pd


# ── 안전한 컬럼 접근 ──────────────────────────────────────────

def _safe(row: pd.Series, col: str, default=None):
    """컬럼 없거나 NaN 이면 default 반환."""
    val = row.get(col, default)
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    return val


# ══════════════════════════════════════════════════════════════
# 점수 규칙 테이블
# ══════════════════════════════════════════════════════════════

_RULES: list[dict] = [

    # ── 기존 가산 규칙 ─────────────────────────────────────────
    {
        "key":       "trading_value_100",
        "points":    20,
        "condition": lambda r: (_safe(r, "trading_value", 0) or 0) >= 100,
        "reason":    "거래대금 100억 이상 (+20)",
        "risk":      None,
        "optional":  False,
    },
    {
        "key":       "volume_surge",
        "points":    20,
        "condition": lambda r: (
            (_safe(r, "avg_volume_20d", 0) or 0) > 0
            and (_safe(r, "volume", 0) or 0) >= (_safe(r, "avg_volume_20d", 1) or 1) * 2
        ),
        "reason":    "거래량 20일 평균 2배 이상 (+20)",
        "risk":      None,
        "optional":  False,
    },
    {
        "key":       "close_above_ma5",
        "points":    15,
        "condition": lambda r: (
            _safe(r, "close") is not None and _safe(r, "ma5") is not None
            and _safe(r, "close", 0) > _safe(r, "ma5", 0)
        ),
        "reason":    "종가 > MA5 (+15)",
        "risk":      None,
        "optional":  False,
    },
    {
        "key":       "close_above_ma20",
        "points":    15,
        "condition": lambda r: (
            _safe(r, "close") is not None and _safe(r, "ma20") is not None
            and _safe(r, "close", 0) > _safe(r, "ma20", 0)
        ),
        "reason":    "종가 > MA20 (+15)",
        "risk":      None,
        "optional":  False,
    },
    {
        "key":       "ma5_above_ma20",
        "points":    10,
        "condition": lambda r: (
            _safe(r, "ma5") is not None and _safe(r, "ma20") is not None
            and _safe(r, "ma5", 0) > _safe(r, "ma20", 0)
        ),
        "reason":    "MA5 > MA20 정배열 (+10)",
        "risk":      None,
        "optional":  False,
    },
    {
        "key":       "bullish_candle",
        "points":    10,
        "condition": lambda r: (
            _safe(r, "close") is not None and _safe(r, "open") is not None
            and _safe(r, "close", 0) >= _safe(r, "open", 0)
        ),
        "reason":    "양봉 마감 (+10)",
        "risk":      None,
        "optional":  False,
    },
    {
        "key":       "has_news",
        "points":    10,
        "condition": lambda r: (_safe(r, "news_count", 0) or 0) >= 1,
        "reason":    "관련 뉴스 존재 (+10)",
        "risk":      None,
        "optional":  False,
    },

    # ── 기존 감산 규칙 ─────────────────────────────────────────
    {
        "key":       "surge_risk",
        "points":    -15,
        "condition": lambda r: (_safe(r, "change_rate", 0) or 0) >= 20,
        "reason":    None,
        "risk":      "등락률 20% 이상 — 급등 추격 위험 (-15)",
        "optional":  False,
    },
    {
        "key":       "high_debt",
        "points":    -10,
        "condition": lambda r: (
            _safe(r, "debt_ratio") is not None
            and (_safe(r, "debt_ratio", 0) or 0) >= 200
        ),
        "reason":    None,
        "risk":      "부채비율 200% 이상 — 재무 레버리지 높음 (-10)",
        "optional":  False,
    },
    {
        "key":       "negative_fundamentals",
        "points":    -10,
        "condition": lambda r: (
            (_safe(r, "per") is not None and (_safe(r, "per", 0) or 0) < 0)
            or (_safe(r, "roe") is not None and (_safe(r, "roe", 0) or 0) < 0)
        ),
        "reason":    None,
        "risk":      "PER 또는 ROE 음수 — 적자 기업 (-10)",
        "optional":  False,
    },

    # ── 신규 가산 규칙 ─────────────────────────────────────────
    {
        "key":       "close_above_ma60",
        "points":    10,
        "condition": lambda r: (
            _safe(r, "ma60") is not None
            and (_safe(r, "close", 0) or 0) > (_safe(r, "ma60", 0) or 0)
        ),
        "reason":    "종가 > MA60 — 중기 추세 우위 (+10)",
        "risk":      None,
        "optional":  True,
    },
    {
        "key":       "rsi_healthy",
        "points":    10,
        "condition": lambda r: (
            _safe(r, "rsi14") is not None
            and 45 <= (_safe(r, "rsi14", 0) or 0) <= 70
        ),
        "reason":    "RSI 45~70 — 건강한 모멘텀 구간 (+10)",
        "risk":      None,
        "optional":  True,
    },
    {
        "key":       "trading_value_surge_20d",
        "points":    15,
        "condition": lambda r: (
            _safe(r, "avg_trading_value_20d") is not None
            and (_safe(r, "avg_trading_value_20d", 0) or 0) > 0
            and (_safe(r, "trading_value", 0) or 0) >= (_safe(r, "avg_trading_value_20d", 1) or 1) * 2
        ),
        "reason":    "거래대금 20일 평균 2배 이상 — 자금 유입 신호 (+15)",
        "risk":      None,
        "optional":  True,
    },
    {
        "key":       "high_20d_breakout",
        "points":    15,
        "condition": lambda r: (
            _safe(r, "high_20d") is not None
            and (_safe(r, "close", 0) or 0) > (_safe(r, "high_20d", 0) or 0)
        ),
        "reason":    "20일 신고가 돌파 — 저항선 상향 돌파 (+15)",
        "risk":      None,
        "optional":  True,
    },
    {
        "key":       "three_day_rally",
        "points":    10,
        "condition": lambda r: (
            _safe(r, "consecutive_up_days") is not None
            and (_safe(r, "consecutive_up_days", 0) or 0) >= 3
        ),
        "reason":    "3일 연속 상승 — 단기 상승 모멘텀 (+10)",
        "risk":      None,
        "optional":  True,
    },
    {
        "key":       "positive_sentiment",
        "points":    10,
        "condition": lambda r: _safe(r, "news_sentiment") == "긍정",
        "reason":    "뉴스 심리 긍정 (+10)",
        "risk":      None,
        "optional":  True,
    },

    # ── 신규 감산 규칙 ─────────────────────────────────────────
    {
        "key":       "rsi_overbought",
        "points":    -10,
        "condition": lambda r: (
            _safe(r, "rsi14") is not None
            and (_safe(r, "rsi14", 0) or 0) >= 75
        ),
        "reason":    None,
        "risk":      "RSI 75 이상 — 과매수 구간, 단기 조정 가능성 (-10)",
        "optional":  True,
    },
    {
        "key":       "negative_sentiment",
        "points":    -15,
        "condition": lambda r: _safe(r, "news_sentiment") == "부정",
        "reason":    None,
        "risk":      "뉴스 심리 부정 — 악재 리스크 (-15)",
        "optional":  True,
    },
    {
        "key":       "very_high_debt",
        "points":    -20,
        "condition": lambda r: (
            _safe(r, "debt_ratio") is not None
            and (_safe(r, "debt_ratio", 0) or 0) >= 300
        ),
        "reason":    None,
        "risk":      "부채비율 300% 이상 — 재무 구조 위험 (-20)",
        "optional":  False,
    },
    {
        "key":       "net_loss",
        "points":    -15,
        "condition": lambda r: (
            _safe(r, "net_profit") is not None
            and (_safe(r, "net_profit", 0) or 0) < 0
        ),
        "reason":    None,
        "risk":      "최근 순이익 적자 — 실적 악화 (-15)",
        "optional":  True,
    },
]

_DECISION_MAP = [
    (90, "강한 관심"),
    (75, "관심"),
    (60, "관찰"),
    (40, "보류"),
    (0,  "제외"),
]

_DECISION_COLOR = {
    "강한 관심": "#1A5E35",
    "관심":     "#27AE60",
    "관찰":     "#F39C12",
    "보류":     "#95A5A6",
    "제외":     "#E74C3C",
}

# optional 규칙 키 목록 (data_quality 판정에 사용)
_OPTIONAL_KEYS: set[str] = {r["key"] for r in _RULES if r["optional"]}

# optional 규칙이 의존하는 컬럼 (존재 여부로 data_quality 판정)
_OPTIONAL_COLS = [
    "ma60", "rsi14",
    "avg_trading_value_20d", "high_20d",
    "consecutive_up_days", "news_sentiment", "net_profit",
]


# ══════════════════════════════════════════════════════════════
# data_quality 계산
# ══════════════════════════════════════════════════════════════

def _calc_data_quality(row: pd.Series) -> str:
    """
    가격·재무·뉴스 데이터 출처를 종합해 품질 등급을 반환합니다.

    반환값:
        "실제 데이터"  - 가격/재무/뉴스 모두 실데이터
        "일부 Mock"    - 일부는 실데이터, 일부는 Mock
        "Mock"         - 전체 Mock
    """
    ds       = str(row.get("data_source", ""))
    fin_src  = str(row.get("fin_source",  "Mock"))
    news_src = str(row.get("news_source", "Mock"))

    real_price = "FinanceDataReader" in ds or "Kiwoom" in ds
    real_fin   = fin_src == "DART"
    real_news  = "Naver" in news_src

    real_count = sum([real_price, real_fin, real_news])

    if real_count >= 3:
        return "실제 데이터"
    if real_count >= 1:
        return "일부 Mock"
    return "Mock"


# ══════════════════════════════════════════════════════════════
# 단일 종목 점수화
# ══════════════════════════════════════════════════════════════

def _score_row(row: pd.Series) -> dict:
    """단일 종목 행을 점수화하고 결과 딕셔너리를 반환합니다."""
    score    = 0
    reasons: list[str] = []
    risks:   list[str] = []

    # 사용 불가 optional 컬럼 수집 (data_quality 보조 판정용)
    missing_optional = [
        col for col in _OPTIONAL_COLS
        if _safe(row, col) is None
    ]

    for rule in _RULES:
        try:
            triggered = bool(rule["condition"](row))
        except Exception:
            triggered = False

        if triggered:
            score += rule["points"]
            if rule["reason"]:
                reasons.append(rule["reason"])
            if rule["risk"]:
                risks.append(rule["risk"])

    # RSI 수치를 이유/리스크에 구체적으로 표시
    rsi_val = _safe(row, "rsi14")
    if rsi_val is not None:
        for i, reason in enumerate(reasons):
            if "RSI 45~70" in reason:
                reasons[i] = f"RSI {rsi_val:.1f} — 건강한 모멘텀 구간 (+10)"
        for i, risk in enumerate(risks):
            if "RSI 75" in risk:
                risks[i] = f"RSI {rsi_val:.1f} — 과매수 구간, 단기 조정 가능성 (-10)"

    # 부채비율 수치를 리스크에 표시
    debt = _safe(row, "debt_ratio")
    if debt is not None:
        for i, risk in enumerate(risks):
            if "200% 이상" in risk and "300%" not in risk:
                risks[i] = f"부채비율 {debt:.0f}% — 재무 레버리지 높음 (-10)"
            if "300% 이상" in risk:
                risks[i] = f"부채비율 {debt:.0f}% — 재무 구조 위험 (-20)"

    # 점수 하한 0
    score = max(0, score)

    # 판단 결정
    decision = "제외"
    for threshold, label in _DECISION_MAP:
        if score >= threshold:
            decision = label
            break

    # data_quality
    data_quality = _calc_data_quality(row)
    # optional 컬럼 대부분 없으면 품질 강등
    if len(missing_optional) >= 4 and data_quality == "실제 데이터":
        data_quality = "일부 Mock"

    return {
        "stock_code":    row.get("stock_code", ""),
        "stock_name":    row.get("stock_name", ""),
        "score":         score,
        "decision":      decision,
        "reasons":       reasons,
        "risks":         risks,
        "data_quality":  data_quality,
        "data_source":   row.get("data_source", "Mock 데이터 (샘플)"),
        "ref_date":      row.get("ref_date",    ""),
    }


# ══════════════════════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════════════════════

def scan(market_data: pd.DataFrame) -> pd.DataFrame:
    """
    market_data DataFrame을 받아 후보 종목 점수 DataFrame을 반환합니다.

    반환 컬럼:
        stock_code, stock_name, score, decision, reasons, risks,
        data_quality, data_source, ref_date

    결과는 score 내림차순으로 정렬됩니다.
    """
    records = [_score_row(row) for _, row in market_data.iterrows()]
    result  = pd.DataFrame(records)
    return result.sort_values("score", ascending=False).reset_index(drop=True)


def get_decision_color(decision: str) -> str:
    """판단 레이블에 해당하는 색상 코드를 반환합니다."""
    return _DECISION_COLOR.get(decision, "#888888")


def get_decision_labels() -> list[str]:
    """판단 레이블 목록을 점수 내림차순으로 반환합니다."""
    return [label for _, label in _DECISION_MAP]
