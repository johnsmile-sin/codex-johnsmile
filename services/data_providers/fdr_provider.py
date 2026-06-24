"""
services/data_providers/fdr_provider.py
FinanceDataReader 기반 실제 주가 · 재무 데이터 조회

설치:
    pip install finance-datareader

제공 데이터:
    - 일봉 OHLCV (종가·고가·저가·시가·거래량)
    - MA5 / MA20 / MA60
    - KRX 상장 정보 (PER, PBR, 시가총액)
"""

from __future__ import annotations

import logging
import os
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── fdr 패키지 가용 여부 ──────────────────────────────────────
_FDR_AVAILABLE = False
try:
    import FinanceDataReader as fdr
    _FDR_AVAILABLE = True
except ImportError:
    logger.warning("[FDR] finance-datareader 미설치. 'pip install finance-datareader' 실행 후 재시작하세요.")

# ── 당일 캐시 경로 ────────────────────────────────────────────
_CACHE_DIR  = Path(os.path.dirname(__file__)).parent.parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)

_LISTING_CACHE = _CACHE_DIR / f"krx_listing_{date.today()}.pkl"
_PRICE_CACHE   = _CACHE_DIR / f"price_{date.today()}.pkl"


# ══════════════════════════════════════════════════════════════
# 공개 함수
# ══════════════════════════════════════════════════════════════

def is_available() -> bool:
    """FinanceDataReader 설치 여부"""
    return _FDR_AVAILABLE


def get_krx_listing() -> pd.DataFrame | None:
    """
    KRX 전체 상장 종목 스냅샷을 반환합니다 (당일 캐시 사용).
    컬럼 예시: Symbol, Market, Name, Sector, PER, PBR, Marcap, Shares
    """
    if not _FDR_AVAILABLE:
        return None

    if _LISTING_CACHE.exists():
        try:
            return pickle.loads(_LISTING_CACHE.read_bytes())
        except Exception:
            pass

    try:
        df = fdr.StockListing("KRX")
        _LISTING_CACHE.write_bytes(pickle.dumps(df))
        return df
    except Exception as e:
        logger.warning("[FDR] KRX 상장 목록 조회 실패: %s", e)
        return None


def get_price_history(code: str, days: int = 90) -> pd.DataFrame | None:
    """
    종목코드 기준 최근 N일 일봉 데이터를 반환합니다 (당일 캐시 사용).
    반환 컬럼: Date(index), Open, High, Low, Close, Volume, Change
    """
    if not _FDR_AVAILABLE:
        return None

    # 당일 캐시 확인
    cache = _load_price_cache()
    if code in cache:
        return cache[code]

    try:
        end_dt   = date.today()
        start_dt = end_dt - timedelta(days=days * 2)  # 영업일 보정
        df = fdr.DataReader(code, start=str(start_dt), end=str(end_dt))
        if df is None or df.empty or len(df) < 5:
            return None
        _save_price_cache(code, df, cache)
        return df
    except Exception as e:
        logger.warning("[FDR] %s 가격 조회 실패: %s", code, e)
        return None


def fetch_all_stocks(
    stock_master: list[tuple],
    max_workers: int = 8,
) -> pd.DataFrame | None:
    """
    stock_master의 전 종목을 병렬로 조회해 market_data 형식 DataFrame을 반환합니다.

    Args:
        stock_master: [(code, name, market, sector, base_price, ...), ...]
        max_workers:  병렬 스레드 수

    Returns:
        market_data DataFrame (get_sample_market_data 동일 스키마 + data_source, ref_date 컬럼)
    """
    if not _FDR_AVAILABLE:
        return None

    listing = get_krx_listing()

    def _fetch_one(item: tuple) -> dict[str, Any] | None:
        code, name, market, sector = item[0], item[1], item[2], item[3]
        mock_per, mock_pbr, mock_roe, mock_debt = item[5], item[6], item[7], item[8]

        price_df = get_price_history(code)
        if price_df is None or len(price_df) < 21:
            return None

        # PER / PBR: KRX 상장 정보에서 우선 사용
        per, pbr = mock_per, mock_pbr
        if listing is not None:
            sym_col = "Symbol" if "Symbol" in listing.columns else "Code"
            row = listing[listing[sym_col] == code]
            if not row.empty:
                try:
                    per_val = float(row["PER"].values[0])
                    pbr_val = float(row["PBR"].values[0])
                    if per_val > 0:
                        per = round(per_val, 1)
                    if pbr_val > 0:
                        pbr = round(pbr_val, 2)
                except Exception:
                    pass

        row_dict = _build_row(
            code=code, name=name, market=market, sector=sector,
            price_df=price_df,
            per=per, pbr=pbr, roe=mock_roe, debt_ratio=mock_debt,
        )
        return row_dict

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, item): item for item in stock_master}
        for future in as_completed(futures):
            result = future.result()
            if result:
                rows.append(result)

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["data_source"] = "실제 데이터 (FinanceDataReader)"
    df["ref_date"]    = str(date.today())
    return df.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════
# 내부 헬퍼
# ══════════════════════════════════════════════════════════════

def _build_row(
    code: str,
    name: str,
    market: str,
    sector: str,
    price_df: pd.DataFrame,
    per: float,
    pbr: float,
    roe: float,
    debt_ratio: float,
    news_count: int = 0,
) -> dict[str, Any]:
    """price_df로부터 market_data 행 딕셔너리를 생성합니다."""
    latest = price_df.iloc[-1]
    prev   = price_df.iloc[-2]

    close      = float(latest["Close"])
    prev_close = float(prev["Close"])
    open_p     = float(latest.get("Open", close))
    high       = float(latest.get("High", close))
    low        = float(latest.get("Low", close))
    volume     = int(latest.get("Volume", 0))

    change_rate = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0

    closes = price_df["Close"].astype(float)
    ma5    = round(float(closes.tail(5).mean()),  0)
    ma20   = round(float(closes.tail(20).mean()), 0)
    ma60   = round(float(closes.tail(min(60, len(closes))).mean()), 0)

    vols          = price_df["Volume"].astype(float)
    avg_volume_20d = int(vols.tail(20).mean())
    trading_value  = round(volume * close / 1e8, 1)

    return {
        "stock_code":     code,
        "stock_name":     name,
        "market":         market,
        "sector":         sector,
        "current_price":  int(close),
        "prev_close":     int(prev_close),
        "open":           int(open_p),
        "high":           int(high),
        "low":            int(low),
        "close":          int(close),
        "change_rate":    change_rate,
        "volume":         volume,
        "avg_volume_20d": avg_volume_20d,
        "trading_value":  trading_value,
        "ma5":            int(ma5),
        "ma20":           int(ma20),
        "ma60":           int(ma60),
        "per":            per,
        "pbr":            pbr,
        "roe":            roe,
        "debt_ratio":     debt_ratio,
        "news_count":     news_count,
    }


def _load_price_cache() -> dict[str, pd.DataFrame]:
    if _PRICE_CACHE.exists():
        try:
            return pickle.loads(_PRICE_CACHE.read_bytes())
        except Exception:
            pass
    return {}


def _save_price_cache(code: str, df: pd.DataFrame, cache: dict) -> None:
    cache[code] = df
    try:
        _PRICE_CACHE.write_bytes(pickle.dumps(cache))
    except Exception:
        pass
