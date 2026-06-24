"""
analysis/stock_report.py  —  단일 종목 경량 종합 리포트 생성기

입력:
    market_row  : pd.Series  (market_data DataFrame의 한 행)
    score_row   : pd.Series  (candidate_scores DataFrame의 한 행)
    news_items  : list[dict] (services.news_data.get_mock_news() 반환값)

출력:
    dict — 7개 섹션 구조화 리포트

주의:
    - 본 리포트는 투자 참고용 자료이며, 실제 투자 결정의 근거로 사용할 수 없습니다.
    - Mock 데이터 기반이므로 실제 시장 수치와 다릅니다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


# ── 상수 정의 ──────────────────────────────────────────────────

_VERDICT_LABELS = ("적극 매수", "분할 매수", "관망", "비중 축소", "매도")

_DATA_RELIABILITY = "낮음 (Mock 데이터 기반 — 실제 투자 결정에 사용 금지)"

_DISCLAIMER = (
    "본 리포트는 투자 참고용 자료입니다. "
    "실제 투자 결정의 근거로 사용할 수 없으며, "
    "수익을 보장하지 않습니다."
)


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼 함수
# ════════════════════════════════════════════════════════════════

def _sentiment_summary(news_items: list[dict]) -> dict[str, int]:
    pos   = sum(1 for n in news_items if n.get("sentiment") == "긍정")
    neu   = sum(1 for n in news_items if n.get("sentiment") == "중립")
    neg   = sum(1 for n in news_items if n.get("sentiment") == "부정")
    return {"긍정": pos, "중립": neu, "부정": neg, "합계": pos + neu + neg}


def _determine_verdict(
    score: int,
    sentiment: dict[str, int],
    has_financial_risk: bool,
    change_rate: float,
) -> str:
    """
    5단계 최종 판정 결정.

    판정 로직:
        80점 이상 + 긍정 뉴스  → 적극 매수
        80점 이상 (중립)       → 분할 매수
        80점 이상 + 부정/재무  → 관망
        60~79점 + 긍정/중립    → 분할 매수
        60~79점 + 부정/재무    → 관망
        40~59점 + 부정 뉴스    → 비중 축소
        40~59점 (기타)         → 관망
        40점 미만 + 부정+재무  → 매도
        40점 미만 (기타)       → 비중 축소 or 관망
    """
    total      = max(sentiment["합계"], 1)
    pos_ratio  = sentiment["긍정"] / total
    neg_ratio  = sentiment["부정"] / total

    is_positive = pos_ratio >= 0.5
    is_negative = neg_ratio >= 0.4        # 40% 이상이면 부정 우위로 판단
    is_surge    = change_rate >= 15.0     # 15% 이상 급등 → 추격 자제

    if score >= 80:
        if is_surge or (is_negative and has_financial_risk):
            return "관망"
        if is_negative or has_financial_risk:
            return "관망"
        if is_positive:
            return "적극 매수"
        return "분할 매수"

    if score >= 60:
        if is_negative or has_financial_risk:
            return "관망"
        return "분할 매수"

    if score >= 40:
        if is_negative:
            return "비중 축소"
        return "관망"

    # 40점 미만
    if is_negative and has_financial_risk:
        return "매도"
    if is_negative:
        return "비중 축소"
    return "관망"


def _calc_target_return(verdict: str, score: int) -> str:
    """판정 및 점수에 따른 목표 수익률 문자열 반환."""
    if verdict == "적극 매수":
        # 80점→+15%, 100점→+25% (선형 보간)
        pct = 15.0 + max(score - 80, 0) * 0.5
        return f"+{pct:.0f}% 내외 (3~6개월 목표, 확정 아님)"
    if verdict == "분할 매수":
        # 60점→+8%, 80점→+12%
        pct = 8.0 + max(score - 60, 0) * 0.2
        return f"+{pct:.0f}% 내외 (3~6개월 목표, 확정 아님)"
    return "해당 없음"


def _calc_stop_loss(verdict: str, close: float, ma20: float) -> str:
    """손절 라인 계산 — MA20 기준 또는 현재가 대비 고정 비율 중 높은 쪽."""
    if verdict not in ("적극 매수", "분할 매수"):
        return "해당 없음"

    pct_line  = close * 0.93          # 현재가 -7%
    ma20_line = ma20  * 0.97          # MA20 -3%
    stop      = max(pct_line, ma20_line)   # 더 위에 있는 쪽(더 엄격한) 선택
    pct_diff  = round((stop / close - 1) * 100, 1)
    return f"{int(stop):,}원 (현재가 대비 {pct_diff:+.1f}%)"


def _entry_timing(
    verdict: str,
    close: float,
    ma5: float,
    ma20: float,
    volume_ratio: float,
) -> str:
    """진입 타이밍 판단 문자열 반환."""
    if verdict == "적극 매수":
        if close > ma5 and volume_ratio >= 1.5:
            return "거래량 수반 돌파 확인 — 현재 가격대 진입 가능"
        return "MA5 지지 확인 후 진입 (눌림목 대기)"

    if verdict == "분할 매수":
        return "1차 소량 진입 → MA20 눌림목에서 2차 추가 매수 고려"

    if verdict in ("관망", "비중 축소"):
        return "MA20 재돌파 또는 거래량 급증 신호 확인 후 재검토"

    # 매도
    return "보유 중이라면 반등 시 분할 매도 고려"


def _build_grounds(
    reasons: list[str],
    score: int,
    per: float,
    roe: float,
    sentiment: dict[str, int],
) -> list[str]:
    """핵심 근거 3가지 목록 구성. 스캐너 reasons → 재무/뉴스 보완 → 기본값 순."""
    grounds: list[str] = list(reasons[:3])

    if len(grounds) < 3:
        if 0 < per < 15:
            grounds.append(f"PER {per:.1f}배 — 동일 섹터 대비 저평가 가능성")
        if roe >= 15:
            grounds.append(f"ROE {roe:.1f}% — 높은 자기자본 수익성")
        if sentiment["합계"] > 0 and sentiment["긍정"] > sentiment["부정"]:
            grounds.append(
                f"뉴스 긍정 우위 "
                f"({sentiment['긍정']}건 / 전체 {sentiment['합계']}건)"
            )

    if len(grounds) < 3:
        grounds.append(f"종합 스캐너 점수 {score}점 기록")
    if len(grounds) < 3:
        grounds.append("추가 분석 데이터 부족 — 지속 모니터링 필요")

    return grounds[:3]


def _build_risks(
    scanner_risks: list[str],
    per: float,
    debt_ratio: float,
    sentiment: dict[str, int],
    change_rate: float,
) -> list[str]:
    """리스크 3가지 목록 구성. 스캐너 risks → 재무/뉴스/시장 보완 → 공통값 순."""
    risks: list[str] = list(scanner_risks)

    # 스캐너에서 미포함된 재무 리스크 보완
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
            f"뉴스 부정 비중 과반 "
            f"({sentiment['부정']}건 / 전체 {sentiment['합계']}건)"
        )
    if change_rate >= 10 and not any("급등" in r for r in risks):
        risks.append(
            f"당일 {change_rate:+.1f}% 급등 — 단기 차익실현 매물 압력 가능"
        )

    # 최소 3개 보장 — 공통 리스크
    _generic = [
        "거시경제 변동(금리·환율) 및 지정학적 리스크 미반영",
        "섹터 전반 악재 발생 시 동반 하락 가능",
        "Mock 데이터 기반 — 실제 시장 조건과 다를 수 있음",
    ]
    for g in _generic:
        if len(risks) >= 3:
            break
        risks.append(g)

    return risks[:3]


def _one_liner(verdict: str, name: str, score: int, sentiment: dict[str, int]) -> str:
    """한 줄 결론 생성."""
    total    = max(sentiment["합계"], 1)
    pos_pct  = round(sentiment["긍정"] / total * 100)

    templates = {
        "적극 매수": (
            f"{name}은 기술적 지표({score}점)와 긍정 뉴스(긍정 {pos_pct}%)가 "
            f"맞물려 현 시점 적극 매수 타이밍으로 판단됩니다."
        ),
        "분할 매수": (
            f"{name}은 기술적 흐름({score}점)이 양호하여 "
            f"리스크 분산을 위한 분할 매수 접근이 적합합니다."
        ),
        "관망": (
            f"{name}은 현재 점수({score}점) 및 시장 여건상 "
            f"추세 재확인 후 진입이 권장됩니다."
        ),
        "비중 축소": (
            f"{name}은 기술적·뉴스 신호({score}점)가 약화되어 "
            f"보유 비중 축소를 고려할 시점입니다."
        ),
        "매도": (
            f"{name}은 점수({score}점) 및 부정 뉴스 신호로 "
            f"보유 중이라면 분할 매도가 적합합니다."
        ),
    }
    return templates.get(verdict, "추가 정보 수집 후 판단이 필요합니다.")


# ════════════════════════════════════════════════════════════════
# 공개 API
# ════════════════════════════════════════════════════════════════

def generate_report(
    market_row: pd.Series,
    score_row: pd.Series,
    news_items: list[dict],
) -> dict[str, Any]:
    """
    단일 종목에 대한 경량 종합 리포트를 생성합니다.

    Args:
        market_row  : market_data DataFrame의 한 행 (pd.Series)
        score_row   : candidate_scores DataFrame의 한 행 (pd.Series)
        news_items  : get_mock_news() 반환 리스트

    Returns:
        dict — 아래 7개 섹션을 포함하는 구조화 딕셔너리:
            기본_정보 / 기술적_점수 / 재무_요약 / 뉴스_감성 /
            최종_판단 / 한_줄_결론 / 메타
    """
    # ── 원시 값 추출 ─────────────────────────────────────────────
    code        = str(market_row.get("stock_code", ""))
    name        = str(market_row.get("stock_name", ""))
    market      = str(market_row.get("market", ""))
    sector      = str(market_row.get("sector", ""))
    close       = float(market_row.get("close", 0))
    prev_close  = float(market_row.get("prev_close", close))
    open_p      = float(market_row.get("open", close))
    high        = float(market_row.get("high", close))
    low         = float(market_row.get("low", close))
    change_rate = float(market_row.get("change_rate", 0))
    volume      = int(market_row.get("volume", 0))
    avg_vol     = int(market_row.get("avg_volume_20d", 1))
    trading_val = float(market_row.get("trading_value", 0))
    ma5         = float(market_row.get("ma5", close))
    ma20        = float(market_row.get("ma20", close))
    ma60        = float(market_row.get("ma60", close))
    per         = float(market_row.get("per", 0))
    pbr         = float(market_row.get("pbr", 0))
    roe         = float(market_row.get("roe", 0))
    debt_ratio  = float(market_row.get("debt_ratio", 0))

    score         = int(score_row.get("score", 0))
    decision      = str(score_row.get("decision", "제외"))
    reasons       = list(score_row.get("reasons", []))
    scanner_risks = list(score_row.get("risks", []))

    # ── 파생 계산 ────────────────────────────────────────────────
    volume_ratio      = round(volume / max(avg_vol, 1), 2)
    has_financial_risk = debt_ratio >= 200 or per < 0 or roe < 0 or per > 50
    sentiment         = _sentiment_summary(news_items)
    verdict           = _determine_verdict(score, sentiment, has_financial_risk, change_rate)

    grounds = _build_grounds(reasons, score, per, roe, sentiment)
    risks   = _build_risks(scanner_risks, per, debt_ratio, sentiment, change_rate)

    # ── 주요 뉴스 3건 (최신순) ───────────────────────────────────
    top_news = [
        {
            "날짜":   n.get("news_date", ""),
            "제목":   n.get("title", ""),
            "감성":   n.get("sentiment", ""),
            "영향도": n.get("impact_score", 0),
        }
        for n in sorted(
            news_items,
            key=lambda x: x.get("news_date", ""),
            reverse=True,
        )[:3]
    ]

    return {
        "기본_정보": {
            "종목코드":  code,
            "종목명":    name,
            "시장":      market,
            "섹터":      sector,
            "현재가":    f"{int(close):,}원",
            "시가":      f"{int(open_p):,}원",
            "고가":      f"{int(high):,}원",
            "저가":      f"{int(low):,}원",
            "전일_대비": f"{change_rate:+.2f}%",
            "거래대금":  f"{trading_val:.1f}억원",
        },
        "기술적_점수": {
            "스캐너_점수":  score,
            "스캐너_판단":  decision,
            "MA5":          f"{int(ma5):,}원",
            "MA20":         f"{int(ma20):,}원",
            "MA60":         f"{int(ma60):,}원",
            "종가_vs_MA5":  "위" if close > ma5 else "아래",
            "종가_vs_MA20": "위" if close > ma20 else "아래",
            "정배열":       bool(close > ma5 > ma20),
            "거래량_비율":  volume_ratio,
            "달성_조건":    reasons,
        },
        "재무_요약": {
            "PER":       f"{per:.1f}배",
            "PBR":       f"{pbr:.2f}배",
            "ROE":       f"{roe:.1f}%",
            "부채비율":  f"{debt_ratio:.0f}%",
            "재무_리스크_여부": has_financial_risk,
        },
        "뉴스_감성": {
            "긍정":     sentiment["긍정"],
            "중립":     sentiment["중립"],
            "부정":     sentiment["부정"],
            "합계":     sentiment["합계"],
            "주요_뉴스": top_news,
        },
        "최종_판단": {
            "판정":       verdict,
            "목표_수익률": _calc_target_return(verdict, score),
            "손절_라인":  _calc_stop_loss(verdict, close, ma20),
            "진입_타이밍": _entry_timing(verdict, close, ma5, ma20, volume_ratio),
            "핵심_근거":  grounds,
            "리스크":     risks,
        },
        "한_줄_결론": _one_liner(verdict, name, score, sentiment),
        "메타": {
            "생성일":      str(date.today()),
            "데이터_신뢰도": _DATA_RELIABILITY,
            "주의사항":    _DISCLAIMER,
        },
    }


def format_report_text(report: dict[str, Any]) -> str:
    """
    generate_report() 결과를 읽기 좋은 한국어 텍스트로 포맷합니다.
    터미널 출력 또는 로그 저장에 활용합니다.
    """
    b  = report["기본_정보"]
    t  = report["기술적_점수"]
    f  = report["재무_요약"]
    n  = report["뉴스_감성"]
    j  = report["최종_판단"]
    m  = report["메타"]

    lines = [
        "=" * 60,
        f"  [{b['종목코드']}] {b['종목명']}  |  {b['시장']} / {b['섹터']}",
        "=" * 60,

        "\n■ 기본 정보",
        f"  현재가    : {b['현재가']}  ({b['전일_대비']})",
        f"  시가/고/저 : {b['시가']} / {b['고가']} / {b['저가']}",
        f"  거래대금   : {b['거래대금']}",

        "\n■ 기술적 점수",
        f"  스캐너 점수 : {t['스캐너_점수']}점  →  {t['스캐너_판단']}",
        f"  MA5 / MA20 / MA60 : {t['MA5']} / {t['MA20']} / {t['MA60']}",
        f"  정배열    : {'✅' if t['정배열'] else '❌'}  |  거래량 비율 : {t['거래량_비율']:.2f}배",

        "\n■ 재무 요약",
        f"  PER {f['PER']}  /  PBR {f['PBR']}  /  ROE {f['ROE']}  /  부채비율 {f['부채비율']}",
        f"  재무 리스크 : {'있음 ⚠️' if f['재무_리스크_여부'] else '없음 ✅'}",

        "\n■ 뉴스 감성",
        f"  긍정 {n['긍정']}건  /  중립 {n['중립']}건  /  부정 {n['부정']}건  (총 {n['합계']}건)",
    ]

    if n["주요_뉴스"]:
        lines.append("  최근 뉴스:")
        for item in n["주요_뉴스"]:
            lines.append(f"    [{item['감성']}] {item['날짜']}  {item['제목']}")

    lines += [
        "\n■ 최종 투자 판단",
        f"  ★ 판정       : {j['판정']}",
        f"  목표 수익률  : {j['목표_수익률']}",
        f"  손절 라인    : {j['손절_라인']}",
        f"  진입 타이밍  : {j['진입_타이밍']}",
        "\n  핵심 근거:",
    ]
    for i, g in enumerate(j["핵심_근거"], 1):
        lines.append(f"    {i}. {g}")

    lines.append("\n  리스크:")
    for i, r in enumerate(j["리스크"], 1):
        lines.append(f"    {i}. {r}")

    lines += [
        f"\n■ 한 줄 결론",
        f"  {report['한_줄_결론']}",

        f"\n{'─' * 60}",
        f"  생성일       : {m['생성일']}",
        f"  데이터 신뢰도 : {m['데이터_신뢰도']}",
        f"  ※ {m['주의사항']}",
        "=" * 60,
    ]

    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
# 실행 예시  (python analysis/stock_report.py)
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    import os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from services.market_data import get_sample_market_data
    from services.news_data import get_mock_news
    from strategy.scanner import scan

    market_df = get_sample_market_data()
    scored_df = scan(market_df)

    # 삼성전자(005930) 리포트 예시
    target_code = "005930"
    market_row = market_df[market_df["stock_code"] == target_code].iloc[0]
    score_row  = scored_df[scored_df["stock_code"] == target_code].iloc[0]
    news_items = get_mock_news(stock_code=target_code)

    report = generate_report(market_row, score_row, news_items)
    print(format_report_text(report))

    print(f"\n[검증] 판정: {report['최종_판단']['판정']}")
    print(f"[검증] 핵심 근거 수: {len(report['최종_판단']['핵심_근거'])}")
    print(f"[검증] 리스크 수: {len(report['최종_판단']['리스크'])}")
    assert report["최종_판단"]["판정"] in (
        "적극 매수", "분할 매수", "관망", "비중 축소", "매도"
    ), "판정 값 오류"
    assert len(report["최종_판단"]["핵심_근거"]) == 3, "핵심 근거 3개 필요"
    assert len(report["최종_판단"]["리스크"]) == 3, "리스크 3개 필요"
    print("\n✅ 모든 검증 통과")
