"""
strategy/indicators.py  –  최소 기술적 지표 함수 모음

설계 원칙:
  - 입출력 모두 pandas Series / DataFrame
  - 데이터가 부족해도 오류 없이 안전값(NaN 또는 기본값) 반환
  - 백테스트·복잡한 전략 없이 지표 계산에만 집중

사용 예시 (app.py / stock_report.py):
    from strategy.indicators import calculate_ma, calculate_rsi
    from strategy.indicators import calculate_volume_ratio, detect_bullish_candle
    from services.market_data import get_sample_market_data

    df = get_sample_market_data()

    # 이동평균 (단일 종목 시계열 기준)
    ma20 = calculate_ma(df, window=20)

    # RSI
    rsi = calculate_rsi(df)

    # 거래량 비율 (스냅샷 데이터에도 바로 적용 가능)
    df["volume_ratio"] = calculate_volume_ratio(df)

    # 양봉 판단 (row 단위)
    df["is_bullish"] = df.apply(detect_bullish_candle, axis=1)
"""

from __future__ import annotations

import pandas as pd
import numpy as np


# ════════════════════════════════════════════════════════════════
# 1. 이동평균 (Moving Average)
# ════════════════════════════════════════════════════════════════

def calculate_ma(df: pd.DataFrame, window: int, column: str = "close") -> pd.Series:
    """
    단순 이동평균(SMA)을 계산합니다.

    Args:
        df:      'close'(또는 지정 column) 컬럼이 있는 DataFrame
        window:  이동평균 기간 (예: 5, 20, 60)
        column:  계산 대상 컬럼명 (기본값: "close")

    Returns:
        이동평균 Series. 데이터 부족 구간은 가용 행으로 계산 (min_periods=1).

    Example:
        df = get_sample_market_data()
        df["ma5"]  = calculate_ma(df, 5)
        df["ma20"] = calculate_ma(df, 20)
    """
    if column not in df.columns:
        return pd.Series(index=df.index, dtype=float)

    return (
        df[column]
        .rolling(window=window, min_periods=1)
        .mean()
        .round(0)
    )


# ════════════════════════════════════════════════════════════════
# 2. RSI (Relative Strength Index)
# ════════════════════════════════════════════════════════════════

def calculate_rsi(
    df: pd.DataFrame,
    period: int = 14,
    column: str = "close",
) -> pd.Series:
    """
    RSI(상대강도지수)를 계산합니다.

    Args:
        df:      'close'(또는 지정 column) 컬럼이 있는 DataFrame
        period:  RSI 기간 (기본값: 14)
        column:  계산 대상 컬럼명

    Returns:
        0~100 범위의 RSI Series.
        - 데이터가 period 보다 적으면 가용 데이터로 계산 (min_periods=1)
        - 분모(평균손실)가 0이면 100 반환
        - 완전히 계산 불가한 경우 중립값 50 반환

    해석 가이드:
        70 초과 → 과매수 (매도 고려)
        30 미만 → 과매도 (매수 고려)
        30~70   → 중립 구간

    Example:
        df = get_sample_market_data()
        df["rsi"] = calculate_rsi(df, period=14)
    """
    if column not in df.columns or len(df) < 2:
        return pd.Series(50.0, index=df.index, dtype=float)

    delta = df[column].diff()

    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.rolling(window=period, min_periods=1).mean()
    avg_loss = loss.rolling(window=period, min_periods=1).mean()

    # 손실이 0인 경우(연속 상승) → RSI = 100
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # NaN → 중립값 50으로 채움
    return rsi.fillna(50.0).clip(0, 100).round(2)


# ════════════════════════════════════════════════════════════════
# 3. 거래량 비율 (Volume Ratio)
# ════════════════════════════════════════════════════════════════

def calculate_volume_ratio(
    df: pd.DataFrame,
    volume_col: str = "volume",
    avg_col: str = "avg_volume_20d",
    avg_window: int = 20,
) -> pd.Series:
    """
    당일 거래량 / 평균 거래량 비율을 계산합니다.

    우선순위:
        1. DataFrame에 'avg_volume_20d' 컬럼이 있으면 그것을 분모로 사용
           (services/market_data.py 스냅샷 데이터에서 바로 동작)
        2. 없으면 'volume' 컬럼의 rolling mean(avg_window)으로 계산
           (시계열 OHLCV 데이터에서 사용)

    Returns:
        비율 Series (예: 2.0 = 평균의 2배).
        분모가 0이거나 없으면 1.0 반환.

    Example:
        df = get_sample_market_data()
        df["volume_ratio"] = calculate_volume_ratio(df)
        high_vol = df[df["volume_ratio"] >= 2.0]  # 평균 2배 이상
    """
    if volume_col not in df.columns:
        return pd.Series(1.0, index=df.index, dtype=float)

    vol = df[volume_col].astype(float)

    if avg_col in df.columns:
        avg = df[avg_col].astype(float)
    else:
        avg = vol.rolling(window=avg_window, min_periods=1).mean()

    ratio = vol / avg.replace(0, np.nan)
    return ratio.fillna(1.0).round(2)


# ════════════════════════════════════════════════════════════════
# 4. 양봉 판단 (Bullish Candle Detection)
# ════════════════════════════════════════════════════════════════

def detect_bullish_candle(row: pd.Series) -> bool:
    """
    단일 행(row)이 양봉인지 판단합니다.

    양봉 조건: close >= open

    Args:
        row: 'open'과 'close' 컬럼이 있는 Series

    Returns:
        True  → 양봉 (close ≥ open)
        False → 음봉 또는 판단 불가

    Example:
        df = get_sample_market_data()
        df["is_bullish"] = df.apply(detect_bullish_candle, axis=1)

        # 스캐너에서 단일 행 판단
        row = df.iloc[0]
        print(detect_bullish_candle(row))  # True or False
    """
    try:
        return float(row["close"]) >= float(row["open"])
    except (KeyError, TypeError, ValueError):
        return False


# ════════════════════════════════════════════════════════════════
# 편의 함수: 모든 지표를 DataFrame에 한 번에 추가
# ════════════════════════════════════════════════════════════════

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    calculate_ma / calculate_rsi / calculate_volume_ratio /
    detect_bullish_candle 를 모두 계산해 새 컬럼으로 추가합니다.

    추가 컬럼:
        ma5, ma20, ma60        – 이동평균 (이미 있으면 덮어쓰지 않음)
        rsi                    – RSI
        volume_ratio           – 거래량 비율
        is_bullish             – 양봉 여부

    Example:
        from strategy.indicators import add_all_indicators
        from services.market_data import get_sample_market_data

        df = add_all_indicators(get_sample_market_data())
        print(df[["stock_name", "rsi", "volume_ratio", "is_bullish"]].head())
    """
    result = df.copy()

    # MA – 스냅샷 데이터에서는 이미 ma5/ma20/ma60이 있으므로 없을 때만 계산
    for window, col in [(5, "ma5"), (20, "ma20"), (60, "ma60")]:
        if col not in result.columns:
            result[col] = calculate_ma(result, window)

    result["rsi"]          = calculate_rsi(result)
    result["volume_ratio"] = calculate_volume_ratio(result)
    result["is_bullish"]   = result.apply(detect_bullish_candle, axis=1)

    return result


# ════════════════════════════════════════════════════════════════
# 실행 예시  (python strategy/indicators.py)
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from services.market_data import get_sample_market_data

    df = get_sample_market_data()
    result = add_all_indicators(df)

    cols = ["stock_name", "close", "ma5", "ma20", "rsi", "volume_ratio", "is_bullish"]
    print("\n=== 기술 지표 결과 (상위 10개) ===")
    print(result[cols].head(10).to_string(index=False))

    print("\n=== RSI 구간별 종목 수 ===")
    print(f"  과매도(RSI < 30): {(result['rsi'] < 30).sum()}개")
    print(f"  중립  (30~70)   : {((result['rsi'] >= 30) & (result['rsi'] <= 70)).sum()}개")
    print(f"  과매수(RSI > 70): {(result['rsi'] > 70).sum()}개")

    print("\n=== 거래량 급등 종목 (평균 2배↑) ===")
    surge = result[result["volume_ratio"] >= 2.0][["stock_name", "volume_ratio"]]
    print(surge.to_string(index=False) if not surge.empty else "  없음")

    print("\n=== 양봉 종목 수 ===")
    print(f"  양봉: {result['is_bullish'].sum()}개 / 음봉: {(~result['is_bullish']).sum()}개")
