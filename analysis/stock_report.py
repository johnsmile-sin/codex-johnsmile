"""
analysis/stock_report.py v2  —  종목 종합 리포트 생성기

리포트 8개 섹션:
    기본_정보 / 기술적_분석 / 재무_요약 / 뉴스_감성 /
    최종_판단 / 핵심_리스크 / 데이터_신뢰도 / 한_줄_결론

최종 판정 5단계:
    적극 매수 / 분할 매수 / 관망 / 비중 축소 / 매도

주의:
    - 본 리포트는 투자 참고용 자료이며, 실제 투자 결정의 근거로 사용할 수 없습니다.
    - 수익을 보장하지 않으며, 확정 수익 및 실거래 주문 권유가 아닙니다.
    - Mock 데이터 기반 항목은 신뢰도가 낮으므로 판단에 주의가 필요합니다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


# ════════════════════════════════════════════════════════════════
# 상수
# ════════════════════════════════════════════════════════════════

_VERDICT_LABELS = ("적극 매수", "분할 매수", "관망", "비중 축소", "매도")

_DISCLAIMER = (
    "본 리포트는 투자 참고용 자료입니다. "
    "실제 투자 결정의 근거로 사용할 수 없으며, "
    "수익을 보장하지 않습니다. 실거래 주문을 권유하지 않습니다."
)

# 데이터 출처별 신뢰도 등급
_SOURCE_GRADE = {
    "real":    ("📡 실제 데이터", "A"),
    "csv":     ("📂 CSV 입력",   "B"),
    "mock":    ("🎲 Mock 데이터", "C"),
}


# ════════════════════════════════════════════════════════════════
# 신뢰도 계산
# ════════════════════════════════════════════════════════════════

def _price_source_grade(data_source: str) -> tuple[str, str]:
    """가격 데이터 출처 → (레이블, 등급)"""
    if "FinanceDataReader" in data_source or "Kiwoom" in data_source:
        return _SOURCE_GRADE["real"]
    return _SOURCE_GRADE["mock"]


def _fin_source_grade(fin_source: str) -> tuple[str, str]:
    """재무 출처 → (레이블, 등급)"""
    if fin_source == "DART":
        return _SOURCE_GRADE["real"]
    if fin_source == "CSV":
        return _SOURCE_GRADE["csv"]
    return _SOURCE_GRADE["mock"]


def _news_source_grade(news_items: list[dict]) -> tuple[str, str]:
    """뉴스 출처 → (레이블, 등급)"""
    sources = {item.get("source", "Mock") for item in news_items}
    if sources == {"Naver"}:
        return _SOURCE_GRADE["real"]
    if "Naver" in sources:
        return "📡+🎲 혼합", "B"
    return _SOURCE_GRADE["mock"]


def _calc_reliability(
    data_source: str,
    fin_source:  str,
    news_items:  list[dict],
) -> str:
    """
    가격·재무·뉴스 출처를 종합해 5단계 신뢰도 등급을 반환합니다.

    높음    : 가격(FDR/Kiwoom) + 재무(DART) + 뉴스(Naver)
    보통-상 : 가격(실제) + 재무 또는 뉴스 중 하나 실제
    보통-하 : 가격(실제) + 재무·뉴스 모두 Mock
    낮음    : 가격 Mock + 일부 실제
    매우 낮음: 전부 Mock
    """
    _, pg = _price_source_grade(data_source)
    _, fg = _fin_source_grade(fin_source)
    _, ng = _news_source_grade(news_items)
    a_count = sum(g == "A" for g in [pg, fg, ng])
    b_count = sum(g == "B" for g in [pg, fg, ng])

    if a_count == 3:
        return "높음 (가격·재무·뉴스 모두 실제 데이터)"
    if a_count == 2:
        return "보통-상 (주요 2개 출처 실제 데이터)"
    if a_count == 1 and pg == "A":
        return "보통-하 (가격만 실제, 재무·뉴스는 Mock)"
    if a_count >= 1:
        return "낮음 (일부 실제 데이터 혼재)"
    return "매우 낮음 (전부 Mock — 투자 판단에 직접 사용 금지)"


def _all_mock(data_source: str, fin_source: str, news_items: list[dict]) -> bool:
    """가격·재무·뉴스 모두 Mock인지 여부"""
    _, pg = _price_source_grade(data_source)
    _, fg = _fin_source_grade(fin_source)
    _, ng = _news_source_grade(news_items)
    return pg == fg == ng == "C"


# ════════════════════════════════════════════════════════════════
# 일봉 데이터 기반 기술적 분석
# ════════════════════════════════════════════════════════════════

def _tech_from_history(price_history: pd.DataFrame | None) -> dict:
    """
    price_service.load_daily_prices() 반환 DataFrame에서
    추가 기술적 지표를 추출합니다.

    Args:
        price_history: load_daily_prices() 반환값 (columns: date, close, ma5, ma20,
                       ma60, rsi14, volume, trading_value, …)

    Returns:
        {}  —  price_history 가 None 이거나 데이터 부족 시 빈 딕셔너리.
        아래 키 포함:
            rsi14, rsi_상태, 연속_상승일, 연속_하락일,
            20일_고가, 고가_대비_위치(%),
            5일_거래대금_평균, 거래대금_추이
    """
    if price_history is None or price_history.empty or len(price_history) < 5:
        return {}

    df = price_history.copy()
    df.columns = [c.lower() for c in df.columns]

    if "close" not in df.columns:
        return {}

    latest = df.iloc[-1]
    close  = float(latest.get("close", 0))

    # RSI
    rsi = float(latest.get("rsi14", 50.0))
    if rsi >= 75:
        rsi_status = "과매수 구간 (주의)"
    elif rsi >= 45:
        rsi_status = "건강한 모멘텀 구간"
    elif rsi >= 30:
        rsi_status = "중립 (관망)"
    else:
        rsi_status = "과매도 구간 (반등 가능성)"

    # 연속 상승/하락일
    up_days = down_days = 0
    closes = df["close"].tolist()
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            if down_days == 0:
                up_days += 1
            else:
                break
        elif closes[i] < closes[i - 1]:
            if up_days == 0:
                down_days += 1
            else:
                break
        else:
            break

    # 20일 고가 대비 위치
    recent_20 = df.tail(20)
    high_20d  = float(recent_20["close"].max())
    pct_from_high = round((close - high_20d) / high_20d * 100, 1) if high_20d > 0 else 0.0

    # 거래대금 추이 (최근 5일 평균 vs 20일 평균)
    tv_col = "trading_value" if "trading_value" in df.columns else None
    tv_trend = "데이터 없음"
    tv_5d_avg = 0.0
    if tv_col:
        tv_5d_avg  = round(float(df[tv_col].tail(5).mean()), 1)
        tv_20d_avg = round(float(df[tv_col].tail(20).mean()), 1)
        ratio = tv_5d_avg / tv_20d_avg if tv_20d_avg > 0 else 1.0
        if ratio >= 2.0:
            tv_trend = f"급증 ({ratio:.1f}배)"
        elif ratio >= 1.3:
            tv_trend = f"증가 ({ratio:.1f}배)"
        elif ratio <= 0.5:
            tv_trend = f"급감 ({ratio:.1f}배)"
        else:
            tv_trend = f"보합 ({ratio:.1f}배)"

    return {
        "rsi14":           round(rsi, 1),
        "rsi_상태":        rsi_status,
        "연속_상승일":     up_days,
        "연속_하락일":     down_days,
        "20일_고가":       int(high_20d),
        "고가_대비_위치":  f"{pct_from_high:+.1f}%",
        "5일_거래대금_평균": f"{tv_5d_avg:.1f}억원",
        "거래대금_추이":   tv_trend,
        "기반_일봉수":     len(df),
    }


# ════════════════════════════════════════════════════════════════
# 투자 판단 로직
# ════════════════════════════════════════════════════════════════

def _determine_verdict(
    score:             int,
    sentiment:         dict[str, int],
    has_financial_risk: bool,
    change_rate:       float,
    all_mock:          bool = False,
) -> tuple[str, str | None]:
    """
    5단계 최종 판정 + 판단 보류 사유 반환.

    v2 점수 기준 (scanner v2 판단 기준과 동일):
        90+ → 강한 관심 구간
        75+ → 관심 구간
        60+ → 관찰 구간
        40+ → 보류 구간
        <40 → 제외 구간

    Returns:
        (verdict, hold_reason)
        hold_reason: None = 정상 판단, str = 판단 보류 사유
    """
    total      = max(sentiment["합계"], 1)
    pos_ratio  = sentiment["긍정"] / total
    neg_ratio  = sentiment["부정"] / total
    is_pos     = pos_ratio >= 0.5
    is_neg     = neg_ratio >= 0.4
    is_surge   = change_rate >= 15.0
    hold_reason: str | None = None

    # 모두 Mock이고 점수가 애매한 구간(40~74)이면 판단 보류
    if all_mock and 40 <= score < 75:
        hold_reason = (
            "가격·재무·뉴스 모두 Mock 데이터입니다. "
            "실제 데이터 연결 후 재평가를 권장합니다."
        )
        return "관망", hold_reason

    # 점수별 판정
    if score >= 90:
        if is_surge or (is_neg and has_financial_risk):
            return "관망", hold_reason
        if is_neg or has_financial_risk:
            return "분할 매수", hold_reason
        if is_pos:
            return "적극 매수", hold_reason
        return "분할 매수", hold_reason

    if score >= 75:
        if is_surge:
            return "관망", hold_reason
        if is_neg or has_financial_risk:
            return "관망", hold_reason
        if is_pos:
            return "분할 매수", hold_reason
        return "분할 매수", hold_reason

    if score >= 60:
        if is_neg or has_financial_risk:
            return "관망", hold_reason
        return "관망", hold_reason

    if score >= 40:
        if is_neg:
            return "비중 축소", hold_reason
        return "관망", hold_reason

    # 40점 미만
    if is_neg and has_financial_risk:
        return "매도", hold_reason
    if is_neg:
        return "비중 축소", hold_reason
    return "관망", hold_reason


def _calc_target_return(verdict: str, score: int, all_mock: bool) -> str:
    """판정 및 점수에 따른 목표 수익률 문자열 반환."""
    if all_mock:
        return "Mock 데이터 기반 — 수치 신뢰 불가"
    if verdict == "적극 매수":
        pct = 15.0 + max(score - 90, 0) * 0.5
        return f"+{pct:.0f}% 내외 (3~6개월 시나리오, 확정 아님)"
    if verdict == "분할 매수":
        pct = 8.0 + max(score - 75, 0) * 0.2
        return f"+{pct:.0f}% 내외 (3~6개월 시나리오, 확정 아님)"
    return "해당 없음"


def _calc_stop_loss(verdict: str, close: float, ma20: float, all_mock: bool) -> str:
    """손절 라인 계산."""
    if verdict not in ("적극 매수", "분할 매수"):
        return "해당 없음"
    if all_mock:
        return "Mock 데이터 기반 — 실제 손절선 별도 설정 필요"
    pct_line  = close * 0.93
    ma20_line = ma20  * 0.97
    stop      = max(pct_line, ma20_line)
    pct_diff  = round((stop / close - 1) * 100, 1)
    return f"{int(stop):,}원 (현재가 대비 {pct_diff:+.1f}%)"


def _entry_timing(
    verdict: str,
    close: float,
    ma5: float,
    ma20: float,
    volume_ratio: float,
    rsi: float = 50.0,
) -> str:
    """진입 타이밍 판단 문자열 반환."""
    if verdict == "적극 매수":
        if rsi >= 75:
            return "RSI 과매수 — 단기 눌림목 이후 재진입 검토"
        if close > ma5 and volume_ratio >= 1.5:
            return "거래량 수반 돌파 확인 — 현재 가격대 진입 가능 (분할 매수 권장)"
        return "MA5 지지 확인 후 진입 (눌림목 대기)"

    if verdict == "분할 매수":
        if close < ma20:
            return "MA20 하회 중 — 반등 확인 후 소량 1차 진입"
        return "1차 소량 진입 → MA20 눌림목에서 2차 추가 매수 고려"

    if verdict in ("관망", "비중 축소"):
        return "MA20 재돌파 또는 거래량 급증 신호 확인 후 재검토"

    return "보유 중이라면 반등 시 분할 매도 고려"


# ════════════════════════════════════════════════════════════════
# 근거 · 리스크 구성
# ════════════════════════════════════════════════════════════════

def _build_grounds(
    reasons:   list[str],
    score:     int,
    per:       float,
    roe:       float,
    sentiment: dict[str, int],
    tech_ex:   dict,  # _tech_from_history 결과
) -> list[str]:
    """핵심 근거 최소 3가지 구성."""
    grounds: list[str] = list(reasons[:3])

    if len(grounds) < 3 and 0 < per < 15:
        grounds.append(f"PER {per:.1f}배 — 동일 섹터 대비 저평가 가능성")
    if len(grounds) < 3 and roe >= 15:
        grounds.append(f"ROE {roe:.1f}% — 높은 자기자본 수익성")
    if (
        len(grounds) < 3
        and sentiment["합계"] > 0
        and sentiment["긍정"] > sentiment["부정"]
    ):
        grounds.append(
            f"뉴스 긍정 우위 ({sentiment['긍정']}건 / 전체 {sentiment['합계']}건)"
        )
    if len(grounds) < 3 and tech_ex.get("연속_상승일", 0) >= 3:
        grounds.append(f"{tech_ex['연속_상승일']}일 연속 상승 — 단기 모멘텀 유지")
    if len(grounds) < 3:
        grounds.append(f"종합 스캐너 점수 {score}점 달성")
    if len(grounds) < 3:
        grounds.append("추가 분석 데이터 부족 — 지속 모니터링 필요")

    return grounds[:3]


def _build_risks(
    scanner_risks: list[str],
    per:           float,
    debt_ratio:    float,
    sentiment:     dict[str, int],
    change_rate:   float,
    tech_ex:       dict,
    all_mock:      bool,
) -> list[str]:
    """리스크 최소 3가지 구성."""
    risks: list[str] = list(scanner_risks)

    if debt_ratio >= 150 and not any("부채" in r for r in risks):
        risks.append(f"부채비율 {debt_ratio:.0f}% — 금리 상승 시 이자 부담 증가")
    if per > 50 and not any("PER" in r for r in risks):
        risks.append(f"PER {per:.1f}배 고평가 — 실적 미달 시 밸류에이션 조정 위험")
    if (
        sentiment["합계"] > 0
        and sentiment["부정"] > sentiment["긍정"]
        and not any("뉴스" in r for r in risks)
    ):
        risks.append(
            f"뉴스 부정 비중 과반 ({sentiment['부정']}건 / 전체 {sentiment['합계']}건)"
        )
    if change_rate >= 10 and not any("급등" in r for r in risks):
        risks.append(f"당일 {change_rate:+.1f}% 급등 — 단기 차익실현 매물 압력 가능")
    if tech_ex.get("rsi14", 50) >= 75 and not any("RSI" in r for r in risks):
        risks.append(f"RSI {tech_ex['rsi14']:.1f} — 과매수 구간, 단기 조정 가능성")

    # 공통 리스크
    _generic = [
        "거시경제 변동(금리·환율) 및 지정학적 리스크 미반영",
        "섹터 전반 악재 발생 시 동반 하락 가능",
        "Mock 데이터 기반 수치는 실제 시장 조건과 다를 수 있음" if all_mock
        else "스캐너 점수는 과거 데이터 기반이며 미래 수익을 보장하지 않음",
    ]
    for g in _generic:
        if len(risks) >= 3:
            break
        risks.append(g)

    return risks[:3]


# ════════════════════════════════════════════════════════════════
# 재무 추이 요약
# ════════════════════════════════════════════════════════════════

def _build_financial_trend(financial_years: list[dict] | None) -> list[dict]:
    """최근 3년 재무 추이 요약 리스트 구성."""
    if not financial_years:
        return []
    result = []
    for yr in financial_years[:3]:
        result.append({
            "연도":      yr.get("fiscal_year", ""),
            "매출액":    f"{yr.get('revenue', 0):,.0f}억원",
            "영업이익":  f"{yr.get('operating_profit', 0):,.0f}억원",
            "영업이익률": f"{yr.get('operating_margin', 0):.1f}%",
            "순이익":    f"{yr.get('net_profit', 0):,.0f}억원",
            "ROE":       f"{yr.get('roe', 0):.1f}%",
            "부채비율":  f"{yr.get('debt_ratio', 0):.0f}%",
        })
    return result


# ════════════════════════════════════════════════════════════════
# 한 줄 결론
# ════════════════════════════════════════════════════════════════

def _one_liner(
    verdict:     str,
    name:        str,
    score:       int,
    sentiment:   dict[str, int],
    hold_reason: str | None,
    all_mock:    bool,
) -> str:
    """한 줄 결론 생성."""
    if hold_reason:
        return (
            f"{name}({score}점)은 데이터가 Mock 기반이라 판단 신뢰도가 낮습니다. "
            f"실제 데이터 연결 후 재분석을 권장합니다."
        )

    total   = max(sentiment["합계"], 1)
    pos_pct = round(sentiment["긍정"] / total * 100)
    mock_note = " (Mock 데이터 참고용)" if all_mock else ""

    templates = {
        "적극 매수": (
            f"{name}은 기술적 지표({score}점)와 긍정 뉴스(긍정 {pos_pct}%)가 "
            f"맞물려 적극 매수 타이밍으로 판단됩니다{mock_note}."
        ),
        "분할 매수": (
            f"{name}은 기술적 흐름({score}점)이 양호하여 "
            f"리스크 분산을 위한 분할 매수 접근이 적합합니다{mock_note}."
        ),
        "관망": (
            f"{name}은 현재 점수({score}점) 및 시장 여건상 "
            f"추세 재확인 후 진입이 권장됩니다{mock_note}."
        ),
        "비중 축소": (
            f"{name}은 기술적·뉴스 신호({score}점)가 약화되어 "
            f"보유 비중 축소를 고려할 시점입니다{mock_note}."
        ),
        "매도": (
            f"{name}은 점수({score}점) 및 부정 신호로 "
            f"보유 중이라면 분할 매도가 적합합니다{mock_note}."
        ),
    }
    return templates.get(verdict, "추가 정보 수집 후 판단이 필요합니다.")


# ════════════════════════════════════════════════════════════════
# 뉴스 감성 요약
# ════════════════════════════════════════════════════════════════

def _sentiment_summary(news_items: list[dict]) -> dict[str, int | str]:
    pos = sum(1 for n in news_items if n.get("sentiment") == "긍정")
    neu = sum(1 for n in news_items if n.get("sentiment") == "중립")
    neg = sum(1 for n in news_items if n.get("sentiment") == "부정")
    total = pos + neu + neg

    dominant = "중립"
    if total > 0:
        if pos > neg and pos > neu:
            dominant = "긍정"
        elif neg > pos and neg > neu:
            dominant = "부정"

    return {"긍정": pos, "중립": neu, "부정": neg, "합계": total, "대표": dominant}


# ════════════════════════════════════════════════════════════════
# 공개 API
# ════════════════════════════════════════════════════════════════

def generate_report(
    market_row:       pd.Series,
    score_row:        pd.Series,
    news_items:       list[dict],
    fin_source:       str = "Mock",
    financial_years:  list[dict] | None = None,
    price_history:    pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    단일 종목 종합 리포트(8개 섹션)를 생성합니다.

    Args:
        market_row:      market_data DataFrame의 한 행
        score_row:       candidate_scores DataFrame의 한 행
        news_items:      get_news_for_stock() 반환 리스트
        fin_source:      재무 출처 ("DART" | "CSV" | "Mock")
        financial_years: get_financial_metrics()["years"] (선택)
        price_history:   load_daily_prices() 반환 DataFrame (선택)

    Returns:
        dict — 8개 섹션 구조화 리포트.
        리포트 키: 기본_정보 / 기술적_분석 / 재무_요약 / 뉴스_감성 /
                  최종_판단 / 핵심_리스크 / 데이터_신뢰도 / 한_줄_결론 / 메타
    """
    # ── 원시 값 추출 ─────────────────────────────────────────────
    data_source = str(market_row.get("data_source", "Mock 데이터 (샘플)"))
    ref_date    = str(market_row.get("ref_date",    str(date.today())))
    code        = str(market_row.get("stock_code", ""))
    name        = str(market_row.get("stock_name", ""))
    market      = str(market_row.get("market", ""))
    sector      = str(market_row.get("sector", ""))
    close       = float(market_row.get("close",       0))
    open_p      = float(market_row.get("open",        close))
    high        = float(market_row.get("high",        close))
    low         = float(market_row.get("low",         close))
    change_rate = float(market_row.get("change_rate", 0))
    volume      = int(market_row.get("volume",        0))
    avg_vol     = int(market_row.get("avg_volume_20d", 1))
    trading_val = float(market_row.get("trading_value", 0))
    ma5         = float(market_row.get("ma5",  close))
    ma20        = float(market_row.get("ma20", close))
    ma60        = float(market_row.get("ma60", close))
    per         = float(market_row.get("per",         0))
    pbr         = float(market_row.get("pbr",         0))
    roe         = float(market_row.get("roe",         0))
    debt_ratio  = float(market_row.get("debt_ratio",  0))
    current_ratio = float(market_row.get("current_ratio", 0))
    op_margin   = float(market_row.get("operating_margin", 0))

    score         = int(score_row.get("score",    0))
    decision      = str(score_row.get("decision", "제외"))
    reasons       = list(score_row.get("reasons", []))
    scanner_risks = list(score_row.get("risks",   []))
    data_quality  = str(score_row.get("data_quality", "Mock"))

    # ── 파생 계산 ────────────────────────────────────────────────
    volume_ratio = round(volume / max(avg_vol, 1), 2)
    has_fin_risk = debt_ratio >= 200 or per < 0 or roe < 0 or per > 50
    sentiment    = _sentiment_summary(news_items)
    is_all_mock  = _all_mock(data_source, fin_source, news_items)

    verdict, hold_reason = _determine_verdict(
        score, sentiment, has_fin_risk, change_rate, is_all_mock
    )

    # ── 일봉 데이터 기반 기술적 지표 ────────────────────────────
    tech_ex = _tech_from_history(price_history)
    rsi_val = tech_ex.get("rsi14", float(market_row.get("rsi14", 50.0)))
    price_data_src = (
        "일봉 데이터 (price_service)" if price_history is not None and not price_history.empty
        else "당일 시장 데이터 (market_data)"
    )

    # ── 출처 등급 ────────────────────────────────────────────────
    p_label, p_grade = _price_source_grade(data_source)
    f_label, f_grade = _fin_source_grade(fin_source)
    n_label, n_grade = _news_source_grade(news_items)
    news_src_str     = n_label

    # ── 핵심 근거·리스크 ─────────────────────────────────────────
    grounds = _build_grounds(reasons, score, per, roe, sentiment, tech_ex)
    risks   = _build_risks(
        scanner_risks, per, debt_ratio, sentiment,
        change_rate, tech_ex, is_all_mock
    )

    # ── 주요 뉴스 3건 ────────────────────────────────────────────
    top_news = [
        {
            "날짜":   n.get("news_date",   ""),
            "제목":   n.get("title",       ""),
            "감성":   n.get("sentiment",   ""),
            "영향도": n.get("impact_score", 0),
            "출처":   n.get("source",      "Mock"),
            "링크":   n.get("url",         ""),
        }
        for n in sorted(
            news_items,
            key=lambda x: x.get("news_date", ""),
            reverse=True,
        )[:3]
    ]

    # ── 재무 3년 추이 ────────────────────────────────────────────
    fin_trend = _build_financial_trend(financial_years)

    # ── 리포트 조립 ──────────────────────────────────────────────
    return {
        # ❶ 기본 정보
        "기본_정보": {
            "종목코드":   code,
            "종목명":     name,
            "시장":       market,
            "섹터":       sector,
            "현재가":     f"{int(close):,}원",
            "시가":       f"{int(open_p):,}원",
            "고가":       f"{int(high):,}원",
            "저가":       f"{int(low):,}원",
            "전일_대비":  f"{change_rate:+.2f}%",
            "거래대금":   f"{trading_val:.1f}억원",
            "기준일":     ref_date,
        },

        # ❷ 기술적 분석
        "기술적_분석": {
            "스캐너_점수":       score,
            "스캐너_판단":       decision,
            "MA5":               f"{int(ma5):,}원",
            "MA20":              f"{int(ma20):,}원",
            "MA60":              f"{int(ma60):,}원",
            "종가_vs_MA5":       "위" if close > ma5  else "아래",
            "종가_vs_MA20":      "위" if close > ma20 else "아래",
            "종가_vs_MA60":      "위" if close > ma60 else "아래",
            "정배열":            bool(close > ma5 > ma20),
            "거래량_비율":       volume_ratio,
            "RSI14":             round(rsi_val, 1),
            "RSI_상태":          tech_ex.get("rsi_상태", "데이터 없음"),
            "연속_상승일":       tech_ex.get("연속_상승일", 0),
            "연속_하락일":       tech_ex.get("연속_하락일", 0),
            "20일_고가":         f"{tech_ex['20일_고가']:,}원" if "20일_고가" in tech_ex else "데이터 없음",
            "고가_대비_위치":    tech_ex.get("고가_대비_위치", "데이터 없음"),
            "거래대금_추이":     tech_ex.get("거래대금_추이", "데이터 없음"),
            "달성_조건":         reasons,
            "일봉_데이터_출처":  price_data_src,
        },

        # ❸ 재무 요약
        "재무_요약": {
            "PER":        f"{per:.1f}배",
            "PBR":        f"{pbr:.2f}배",
            "ROE":        f"{roe:.1f}%",
            "부채비율":   f"{debt_ratio:.0f}%",
            "유동비율":   f"{current_ratio:.0f}%" if current_ratio > 0 else "데이터 없음",
            "영업이익률": f"{op_margin:.1f}%" if op_margin != 0 else "데이터 없음",
            "재무_출처":  f"{f_label} (등급 {f_grade})",
            "재무_리스크_여부": has_fin_risk,
            "연도별_추이": fin_trend,
        },

        # ❹ 뉴스 감성
        "뉴스_감성": {
            "긍정":     sentiment["긍정"],
            "중립":     sentiment["중립"],
            "부정":     sentiment["부정"],
            "합계":     sentiment["합계"],
            "대표_감성": sentiment["대표"],
            "뉴스_출처": f"{news_src_str} (등급 {n_grade})",
            "주요_뉴스": top_news,
        },

        # ❺ 최종 투자 판단
        "최종_판단": {
            "판정":          verdict,
            "판단_보류_이유": hold_reason,
            "목표_수익률":   _calc_target_return(verdict, score, is_all_mock),
            "손절_라인":     _calc_stop_loss(verdict, close, ma20, is_all_mock),
            "진입_타이밍":   _entry_timing(verdict, close, ma5, ma20, volume_ratio, rsi_val),
            "핵심_근거":     grounds,
            "리스크":        risks,
        },

        # ❻ 핵심 리스크 (별도 섹션 — 스캐너 리스크 전체)
        "핵심_리스크": {
            "스캐너_리스크":    scanner_risks,
            "재무_리스크":      [
                f"부채비율 {debt_ratio:.0f}%" if debt_ratio >= 200 else None,
                f"PER {per:.1f}배 고평가"    if per > 50           else None,
                f"ROE 음수 ({roe:.1f}%)"     if roe < 0            else None,
            ],
            "시장_리스크": [
                "거시경제 변동(금리·환율·지정학적 리스크) 미반영",
                "섹터 동반 하락 가능성",
            ],
        },

        # ❼ 데이터 신뢰도
        "데이터_신뢰도": {
            "종합_등급":   _calc_reliability(data_source, fin_source, news_items),
            "가격_데이터": {"출처": p_label, "등급": p_grade, "설명": data_source},
            "재무_데이터": {"출처": f_label, "등급": f_grade, "설명": fin_source},
            "뉴스_데이터": {"출처": news_src_str, "등급": n_grade},
            "일봉_데이터": {
                "출처": price_data_src,
                "일봉수": tech_ex.get("기반_일봉수", 0),
            },
            "판단_유효성": (
                "판단 보류 (Mock 데이터 기반)"
                if is_all_mock else "정상 (일부 실제 데이터 포함)"
                if not is_all_mock and any(g != "C" for g in [p_grade, f_grade, n_grade])
                else "주의 (Mock 데이터 비중 높음)"
            ),
        },

        # ❽ 한 줄 결론
        "한_줄_결론": _one_liner(
            verdict, name, score, sentiment, hold_reason, is_all_mock
        ),

        # 메타 (하위호환 유지)
        "메타": {
            "생성일":        str(date.today()),
            "기준일":        ref_date,
            "데이터_출처":   data_source,
            "재무_출처":     fin_source,
            "데이터_신뢰도": _calc_reliability(data_source, fin_source, news_items),
            "주의사항":      _DISCLAIMER,
        },
    }


# ════════════════════════════════════════════════════════════════
# 텍스트 포맷
# ════════════════════════════════════════════════════════════════

def format_report_text(report: dict[str, Any]) -> str:
    """generate_report() 결과를 터미널·로그용 텍스트로 포맷합니다."""
    b  = report["기본_정보"]
    t  = report["기술적_분석"]
    f  = report["재무_요약"]
    n  = report["뉴스_감성"]
    j  = report["최종_판단"]
    dr = report["데이터_신뢰도"]
    m  = report["메타"]

    lines = [
        "=" * 64,
        f"  [{b['종목코드']}] {b['종목명']}  |  {b['시장']} / {b['섹터']}",
        f"  기준일: {b['기준일']}  |  생성일: {m['생성일']}",
        "=" * 64,

        "\n■ 기본 정보",
        f"  현재가     : {b['현재가']}  ({b['전일_대비']})",
        f"  시가/고/저  : {b['시가']} / {b['고가']} / {b['저가']}",
        f"  거래대금    : {b['거래대금']}",

        "\n■ 기술적 분석",
        f"  스캐너 점수 : {t['스캐너_점수']}점  →  {t['스캐너_판단']}",
        f"  MA5/MA20/MA60 : {t['MA5']} / {t['MA20']} / {t['MA60']}",
        f"  정배열      : {'✅' if t['정배열'] else '❌'}"
        f"  |  거래량 비율 : {t['거래량_비율']:.2f}배",
        f"  RSI14       : {t['RSI14']}  ({t['RSI_상태']})",
        f"  연속 상승일  : {t['연속_상승일']}일  |  연속 하락일 : {t['연속_하락일']}일",
        f"  20일 고가    : {t['20일_고가']}  |  현재 위치 : {t['고가_대비_위치']}",
        f"  거래대금 추이: {t['거래대금_추이']}",
        f"  일봉 출처    : {t['일봉_데이터_출처']}",

        "\n■ 재무 요약",
        f"  PER {f['PER']}  /  PBR {f['PBR']}  /  ROE {f['ROE']}",
        f"  부채비율 {f['부채비율']}  /  유동비율 {f['유동비율']}",
        f"  영업이익률 {f['영업이익률']}",
        f"  재무 출처    : {f['재무_출처']}",
        f"  재무 리스크  : {'있음 ⚠️' if f['재무_리스크_여부'] else '없음 ✅'}",
    ]

    if f["연도별_추이"]:
        lines.append("  연도별 추이:")
        for yr in f["연도별_추이"]:
            lines.append(
                f"    [{yr['연도']}] 매출 {yr['매출액']}  "
                f"영업이익률 {yr['영업이익률']}  ROE {yr['ROE']}"
            )

    lines += [
        "\n■ 뉴스 감성",
        f"  긍정 {n['긍정']}건  /  중립 {n['중립']}건  /  부정 {n['부정']}건  "
        f"(총 {n['합계']}건  /  대표: {n['대표_감성']})",
        f"  뉴스 출처    : {n['뉴스_출처']}",
    ]
    if n["주요_뉴스"]:
        lines.append("  최근 주요 뉴스:")
        for item in n["주요_뉴스"]:
            src_tag = f"[{item['출처']}]" if item.get("출처") else ""
            lines.append(
                f"    {src_tag}[{item['감성']}] {item['날짜']}  {item['제목']}"
            )

    # 최종 판단
    lines += [
        "\n■ 최종 투자 판단",
        f"  ★ 판정       : {j['판정']}",
    ]
    if j.get("판단_보류_이유"):
        lines.append(f"  ⚠️  판단 보류 : {j['판단_보류_이유']}")

    lines += [
        f"  목표 수익률  : {j['목표_수익률']}",
        f"  손절 라인    : {j['손절_라인']}",
        f"  진입 타이밍  : {j['진입_타이밍']}",
        "\n  핵심 근거:",
    ]
    for i, g in enumerate(j["핵심_근거"], 1):
        lines.append(f"    {i}. {g}")
    lines.append("\n  주요 리스크:")
    for i, r in enumerate(j["리스크"], 1):
        lines.append(f"    {i}. {r}")

    # 데이터 신뢰도 섹션
    lines += [
        "\n■ 데이터 신뢰도",
        f"  종합 등급    : {dr['종합_등급']}",
        f"  가격 데이터  : {dr['가격_데이터']['출처']} (등급 {dr['가격_데이터']['등급']})",
        f"  재무 데이터  : {dr['재무_데이터']['출처']} (등급 {dr['재무_데이터']['등급']})",
        f"  뉴스 데이터  : {dr['뉴스_데이터']['출처']} (등급 {dr['뉴스_데이터']['등급']})",
        f"  일봉 데이터  : {dr['일봉_데이터']['출처']} ({dr['일봉_데이터']['일봉수']}일치)",
        f"  판단 유효성  : {dr['판단_유효성']}",
    ]

    lines += [
        f"\n■ 한 줄 결론",
        f"  {report['한_줄_결론']}",

        f"\n{'─' * 64}",
        f"  ※ {m['주의사항']}",
        "=" * 64,
    ]

    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
# 실행 예시
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from services.market_data import get_sample_market_data
    from services.news_data import get_mock_news
    from services.financial_data import get_financial_metrics
    from services.price_service import fetch_daily_prices
    from strategy.scanner import scan

    market_df = get_sample_market_data()
    scored_df = scan(market_df)

    target = "005930"
    market_row = market_df[market_df["stock_code"] == target].iloc[0]
    score_row  = scored_df[scored_df["stock_code"] == target].iloc[0]
    news_items = get_mock_news(stock_code=target)
    metrics    = get_financial_metrics(target, str(market_row.get("stock_name", "")))
    history    = fetch_daily_prices(target, days=60)

    report = generate_report(
        market_row,
        score_row,
        news_items,
        fin_source=metrics["fin_source"],
        financial_years=metrics["years"],
        price_history=history,
    )
    print(format_report_text(report))

    # 기본 검증
    assert report["최종_판단"]["판정"] in _VERDICT_LABELS
    assert len(report["최종_판단"]["핵심_근거"]) == 3
    assert len(report["최종_판단"]["리스크"])   == 3
    assert "종합_등급" in report["데이터_신뢰도"]
    print("\n모든 검증 통과")
