"""
종목 상세 리포트 생성 모듈
"""

from modules.scoring import get_score_breakdown
from modules.news import get_news_summary
from modules.financials import get_financial_summary
from modules.judgment import generate_judgment
import pandas as pd


def build_stock_report(row: pd.Series) -> dict:
    """
    단일 종목 행(row)을 받아 전체 리포트 딕셔너리를 반환합니다.
    """
    code = row["종목코드"]
    name = row["종목명"]
    sector = row["섹터"]

    score_breakdown = get_score_breakdown(row)
    news = get_news_summary(code, name, sector)
    financial = get_financial_summary(code, name)

    judgment = generate_judgment(
        score=float(row["총점"]),
        grade=str(row["등급"]),
        news_sentiment=news["sentiment"],
        financial=financial,
        stock_name=name,
    )

    return {
        "기본정보": {
            "종목코드": code,
            "종목명": name,
            "섹터": sector,
            "시장": row["시장"],
            "현재가": row["current_price"],
            "등락률": row["change_pct"],
            "거래량": row["volume"],
            "52주고": row["high_52w"],
            "52주저": row["low_52w"],
        },
        "점수": {
            "총점": row["총점"],
            "등급": str(row["등급"]),
            "항목별": score_breakdown,
        },
        "기술지표": {
            "RSI": row["rsi"],
            "MACD신호": row["macd_signal"],
            "MA배열": "정배열" if row["ma5_above_ma20"] else "역배열",
            "볼린저밴드위치": row["bb_position"],
        },
        "재무정보": financial,
        "뉴스": news,
        "투자판단": judgment,
    }
