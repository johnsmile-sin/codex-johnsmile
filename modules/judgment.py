"""
최종 투자 판단 생성 모듈
점수 + 재무 요약 + 뉴스 감성을 종합해 매매 의견을 생성합니다.
"""


def generate_judgment(
    score: float,
    grade: str,
    news_sentiment: str,
    financial: dict,
    stock_name: str,
) -> dict:
    """
    종합 투자 판단을 반환합니다.

    Returns:
        {
            "opinion": "매수 검토" | "관망" | "매도 검토",
            "confidence": "높음" | "중간" | "낮음",
            "reason": str,
            "risk_factors": list[str],
            "strategy": str,
        }
    """
    opinion, confidence = _decide_opinion(score, grade, news_sentiment, financial)
    reason = _build_reason(score, grade, news_sentiment, financial, stock_name)
    risks = _build_risks(financial, score)
    strategy = _build_strategy(opinion, score, financial)

    return {
        "opinion": opinion,
        "confidence": confidence,
        "reason": reason,
        "risk_factors": risks,
        "strategy": strategy,
    }


def _decide_opinion(score, grade, sentiment, fin) -> tuple[str, str]:
    positive_sentiment = sentiment in ("긍정적", "다소 긍정적")
    good_fundamental = fin["roe"] >= 10 and fin["per"] < 30 and fin["debt_ratio"] < 120

    if grade in ("S", "A") and positive_sentiment and good_fundamental:
        return "매수 검토", "높음"
    if grade in ("S", "A") and (positive_sentiment or good_fundamental):
        return "매수 검토", "중간"
    if grade == "B":
        return "관망", "중간"
    if grade in ("C", "D"):
        return "관망", "낮음"

    return "관망", "낮음"


def _build_reason(score, grade, sentiment, fin, name) -> str:
    lines = [
        f"{name}의 종합 점수는 {score}점(등급: {grade})입니다.",
        f"뉴스 감성은 '{sentiment}'으로 분석되었습니다.",
    ]
    if fin["yoy_revenue_growth"] > 10:
        lines.append(f"매출 성장률 {fin['yoy_revenue_growth']}%로 외형이 확대되고 있습니다.")
    if fin["roe"] >= 15:
        lines.append(f"ROE {fin['roe']}%로 자본 효율이 우수합니다.")
    if fin["per"] < 15:
        lines.append(f"PER {fin['per']}배로 밸류에이션 매력이 있습니다.")
    return " ".join(lines)


def _build_risks(fin, score) -> list:
    risks = []
    if fin["debt_ratio"] > 150:
        risks.append(f"부채비율 {fin['debt_ratio']}%로 재무 레버리지 높음")
    if fin["yoy_profit_growth"] < -10:
        risks.append(f"영업이익 {fin['yoy_profit_growth']}% 감소 – 수익성 악화 중")
    if fin["per"] > 40:
        risks.append(f"PER {fin['per']}배로 밸류에이션 부담 높음")
    if score < 50:
        risks.append("기술적 지표 약세 – 추세 전환 확인 필요")
    if not risks:
        risks.append("현재 특이 리스크 없음 (항상 손절 원칙 준수)")
    return risks


def _build_strategy(opinion, score, fin) -> str:
    if opinion == "매수 검토":
        return (
            "분할 매수 전략을 권장합니다. "
            "1차 매수 후 -3% 손절선을 설정하고, "
            "추가 상승 확인 시 2차 매수를 검토하세요. "
            "목표가는 현재가 대비 +10~15% 수준으로 설정을 권장합니다."
        )
    if opinion == "관망":
        return (
            "현시점에서는 관망을 권장합니다. "
            "추세 전환 신호(골든크로스, 거래량 증가)를 확인 후 진입하세요. "
            "섣부른 저점 매수는 피하는 것이 좋습니다."
        )
    return (
        "현재 보유 중이라면 비중 축소를 검토하세요. "
        "추가 매수는 지양하고, 반등 시 일부 익절을 고려하세요."
    )
