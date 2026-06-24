"""
종목 후보 점수화 모듈
기술적 지표 + 기본적 지표를 조합해 0~100점으로 점수화합니다.
"""

import pandas as pd


# 각 항목별 가중치 (합계 = 100)
WEIGHTS = {
    "rsi_score":        15,
    "macd_score":       15,
    "ma_score":         10,
    "bb_score":         10,
    "per_score":        15,
    "pbr_score":        10,
    "roe_score":        15,
    "momentum_score":   10,
}


def _score_rsi(rsi: float) -> float:
    """RSI: 30~50 구간이 매수 타이밍으로 높은 점수"""
    if rsi < 20:
        return 40   # 과매도 위험
    if 20 <= rsi < 30:
        return 75
    if 30 <= rsi < 50:
        return 100
    if 50 <= rsi < 70:
        return 70
    if 70 <= rsi < 80:
        return 40
    return 10       # 80 이상: 과매수


def _score_macd(signal: str) -> float:
    if signal == "골든크로스":
        return 100
    if signal == "중립":
        return 50
    return 10       # 데드크로스


def _score_ma(ma5_above_ma20: bool) -> float:
    return 100 if ma5_above_ma20 else 30


def _score_bb(bb_position: float) -> float:
    """볼린저밴드 하단 근처(0~30%)가 매수 기회"""
    if bb_position <= 20:
        return 100
    if bb_position <= 40:
        return 70
    if bb_position <= 60:
        return 50
    if bb_position <= 80:
        return 30
    return 10


def _score_per(per: float) -> float:
    """PER: 낮을수록 저평가. 업종 평균 무시하고 절대값 기준"""
    if per <= 0:
        return 0    # 적자
    if per <= 10:
        return 100
    if per <= 15:
        return 85
    if per <= 20:
        return 70
    if per <= 30:
        return 50
    if per <= 40:
        return 30
    return 10


def _score_pbr(pbr: float) -> float:
    if pbr <= 0:
        return 0
    if pbr <= 1.0:
        return 100
    if pbr <= 2.0:
        return 70
    if pbr <= 3.0:
        return 45
    return 20


def _score_roe(roe: float) -> float:
    if roe < 0:
        return 0
    if roe >= 20:
        return 100
    if roe >= 15:
        return 80
    if roe >= 10:
        return 60
    if roe >= 5:
        return 40
    return 20


def _score_momentum(change_pct: float) -> float:
    """당일 등락률: 약한 상승(1~4%)이 가장 좋음"""
    if 1.0 <= change_pct <= 4.0:
        return 100
    if 0.0 <= change_pct < 1.0:
        return 70
    if -2.0 <= change_pct < 0.0:
        return 50
    if change_pct > 5.0:
        return 40   # 급등 – 추격 매수 위험
    return 20


def score_stocks(df: pd.DataFrame) -> pd.DataFrame:
    """
    종목 DataFrame을 받아 점수 컬럼을 추가해 반환합니다.
    입력 컬럼: rsi, macd_signal, ma5_above_ma20, bb_position,
               per, pbr, roe, change_pct
    """
    df = df.copy()

    df["rsi_score"]      = df["rsi"].apply(_score_rsi)
    df["macd_score"]     = df["macd_signal"].apply(_score_macd)
    df["ma_score"]       = df["ma5_above_ma20"].apply(_score_ma)
    df["bb_score"]       = df["bb_position"].apply(_score_bb)
    df["per_score"]      = df["per"].apply(_score_per)
    df["pbr_score"]      = df["pbr"].apply(_score_pbr)
    df["roe_score"]      = df["roe"].apply(_score_roe)
    df["momentum_score"] = df["change_pct"].apply(_score_momentum)

    # 가중 합산
    total = sum(WEIGHTS.values())
    df["총점"] = sum(
        df[col] * w / total
        for col, w in WEIGHTS.items()
    ).round(1)

    # 등급 부여
    df["등급"] = pd.cut(
        df["총점"],
        bins=[0, 40, 55, 70, 85, 100],
        labels=["D", "C", "B", "A", "S"],
        right=True,
    )

    return df.sort_values("총점", ascending=False).reset_index(drop=True)


def get_score_breakdown(row: pd.Series) -> dict:
    """단일 종목의 점수 항목별 분해 반환"""
    labels = {
        "rsi_score":      "RSI",
        "macd_score":     "MACD",
        "ma_score":       "이동평균",
        "bb_score":       "볼린저밴드",
        "per_score":      "PER",
        "pbr_score":      "PBR",
        "roe_score":      "ROE",
        "momentum_score": "모멘텀",
    }
    return {labels[k]: round(row[k] * WEIGHTS[k] / 100, 1) for k in labels}
