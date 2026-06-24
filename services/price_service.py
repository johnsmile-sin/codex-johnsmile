"""
services/price_service.py  —  일봉 가격 데이터 서비스

흐름:
    fetch_daily_prices()
        └─ 키움 API (키 있을 때) → FDR → Mock 순 폴백
        └─ indicators.py 로 ma5/ma20/ma60/rsi14 계산
        └─ trading_value, change_rate 추가

    save_daily_prices()
        ├─ Supabase 연결 시 : daily_prices 테이블 upsert
        └─ 미연결 시        : 모듈 내 메모리 캐시에 저장

    load_daily_prices()
        ├─ Supabase 연결 시 : daily_prices 테이블 조회
        └─ 미연결 시        : 메모리 캐시 조회

    update_daily_prices_for_candidates()
        └─ candidate_list 전 종목 fetch + save 일괄 처리
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd

from strategy.indicators import calculate_ma, calculate_rsi

logger = logging.getLogger(__name__)

# ── 메모리 폴백 캐시 (Supabase 미연결 시 사용) ────────────────────
# key: stock_code, value: DataFrame
_MEMORY_CACHE: dict[str, pd.DataFrame] = {}


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼
# ════════════════════════════════════════════════════════════════

def _get_stock_name(stock_code: str) -> str:
    """종목코드 → 종목명 (마스터에서 조회, 없으면 코드 그대로)"""
    try:
        from services.market_data import get_stock_by_code
        item = get_stock_by_code(stock_code)
        if item:
            return item["stock_name"]
    except Exception:
        pass
    return stock_code


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    ma5 / ma20 / ma60 / rsi14 / change_rate / trading_value 를 계산합니다.
    입력 DataFrame 에 'close', 'volume' 컬럼이 있어야 합니다.
    """
    result = df.copy()

    # 컬럼명 소문자 통일 (키움·FDR 반환값 대응)
    result.columns = [c.lower() for c in result.columns]

    if "close" not in result.columns:
        logger.warning("[price] 'close' 컬럼 없음 — 지표 계산 불가")
        return result

    # 이동평균
    result["ma5"]  = calculate_ma(result, window=5).astype(int)
    result["ma20"] = calculate_ma(result, window=20).astype(int)
    result["ma60"] = calculate_ma(result, window=60).astype(int)

    # RSI(14)
    result["rsi14"] = calculate_rsi(result, period=14, column="close").round(2)

    # 등락률 (전일 종가 대비)
    if "change_rate" not in result.columns:
        result["change_rate"] = (
            result["close"].pct_change() * 100
        ).round(2).fillna(0.0)

    # 거래대금 (억원)
    if "trading_value" not in result.columns and "volume" in result.columns:
        result["trading_value"] = (
            result["volume"].astype(float) * result["close"].astype(float) / 1e8
        ).round(1)

    return result


def _df_to_supabase_rows(
    stock_code: str,
    stock_name: str,
    df: pd.DataFrame,
    source: str,
) -> list[dict[str, Any]]:
    """DataFrame → Supabase upsert 용 딕셔너리 리스트 변환"""
    rows: list[dict[str, Any]] = []

    date_col = "date" if "date" in df.columns else (
        "price_date" if "price_date" in df.columns else None
    )

    for _, row in df.iterrows():
        price_date = str(row[date_col]) if date_col else str(date.today())
        rows.append({
            "stock_code":    stock_code,
            "stock_name":    stock_name,
            "price_date":    price_date,
            "open":          int(row.get("open",  0)),
            "high":          int(row.get("high",  0)),
            "low":           int(row.get("low",   0)),
            "close":         int(row.get("close", 0)),
            "volume":        int(row.get("volume", 0)),
            "trading_value": float(row.get("trading_value", 0.0)),
            "change_rate":   float(row.get("change_rate",   0.0)),
            "ma5":           int(row.get("ma5",   0)) or None,
            "ma20":          int(row.get("ma20",  0)) or None,
            "ma60":          int(row.get("ma60",  0)) or None,
            "rsi14":         float(row.get("rsi14", 50.0)),
            "source":        str(row.get("source", source)),
        })
    return rows


# ════════════════════════════════════════════════════════════════
# 공개 함수
# ════════════════════════════════════════════════════════════════

def fetch_daily_prices(
    stock_code: str,
    days: int = 120,
) -> pd.DataFrame:
    """
    종목 일봉 데이터를 가져오고 기술 지표를 계산합니다.

    데이터 소스 우선순위:
        1. 키움 OpenAPI (KIWOOM_APP_KEY + KIWOOM_SECRET_KEY 설정 시)
        2. FinanceDataReader (finance-datareader 설치 시)
        3. Mock 데이터 (위 두 가지 모두 없을 때)

    Args:
        stock_code : 6자리 종목코드 (예: "005930")
        days       : 조회 기간 (거래일 기준)

    Returns:
        DataFrame — columns:
            date, open, high, low, close, volume, trading_value,
            change_rate, ma5, ma20, ma60, rsi14, source
    """
    code = str(stock_code).zfill(6)
    df: pd.DataFrame | None = None
    source = "Mock"

    try:
        from config import MOCK_MODE
    except Exception:
        MOCK_MODE = False

    if MOCK_MODE:
        from services.kiwoom_data import _mock_daily_prices
        df = _mock_daily_prices(code, days)
        df = _add_indicators(df)
        return df.reset_index(drop=True)

    # 1순위: 키움 API
    try:
        from services.kiwoom_data import is_available as kiwoom_ok, get_daily_prices as kiwoom_prices
        if kiwoom_ok():
            df = kiwoom_prices(code, days=days)
            source = "Kiwoom"
            logger.info("[price] %s 키움 일봉 로드: %d건", code, len(df))
    except Exception as e:
        logger.warning("[price] 키움 실패 %s: %s", code, e)

    # 2순위: FDR
    if df is None or df.empty:
        try:
            from services.data_providers.fdr_provider import is_available as fdr_ok, get_price_history
            if fdr_ok():
                fdr_df = get_price_history(code, days=days)
                if fdr_df is not None and not fdr_df.empty:
                    # FDR 컬럼명 소문자 변환 + date 컬럼 추가
                    # reset_index() 이후 소문자 변환: FDR index 이름 "Date" → "date"
                    fdr_df = fdr_df.copy()
                    fdr_df = fdr_df.reset_index()
                    fdr_df.columns = [c.lower() for c in fdr_df.columns]
                    fdr_df.rename(columns={"index": "date"}, inplace=True)
                    fdr_df["date"] = pd.to_datetime(fdr_df["date"]).dt.strftime("%Y-%m-%d")
                    fdr_df["source"] = "FinanceDataReader"
                    df = fdr_df.tail(days)
                    source = "FinanceDataReader"
                    logger.info("[price] %s FDR 일봉 로드: %d건", code, len(df))
        except Exception as e:
            logger.warning("[price] FDR 실패 %s: %s", code, e)

    # 3순위: Mock
    if df is None or df.empty:
        from services.kiwoom_data import _mock_daily_prices
        df = _mock_daily_prices(code, days)
        source = "Mock"
        logger.info("[price] %s Mock 일봉 생성: %d건", code, len(df))

    df = _add_indicators(df)
    return df.reset_index(drop=True)


def save_daily_prices(
    stock_code: str,
    df: pd.DataFrame,
) -> dict[str, Any]:
    """
    일봉 DataFrame을 저장합니다.

    - Supabase 연결 시: daily_prices 테이블에 upsert (stock_code + price_date 기준)
    - 미연결 시        : 모듈 내 메모리 캐시에 저장

    Args:
        stock_code : 6자리 종목코드
        df         : fetch_daily_prices() 반환 DataFrame

    Returns:
        {"saved": int, "mode": "supabase"|"memory", "error": str | None}
    """
    if df is None or df.empty:
        return {"saved": 0, "mode": "none", "error": "빈 DataFrame"}

    code       = str(stock_code).zfill(6)
    stock_name = _get_stock_name(code)
    source     = str(df["source"].iloc[0]) if "source" in df.columns else "Unknown"

    # ── Supabase 저장 ─────────────────────────────────────────
    try:
        from services.supabase_client import get_client, is_connected
        if is_connected():
            client = get_client()
            rows   = _df_to_supabase_rows(code, stock_name, df, source)
            saved  = 0

            # 50건씩 배치 upsert
            batch_size = 50
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                client.table("daily_prices").upsert(
                    batch,
                    on_conflict="stock_code,price_date",
                ).execute()
                saved += len(batch)

            logger.info("[price] %s Supabase 저장: %d건", code, saved)
            return {"saved": saved, "mode": "supabase", "error": None}
    except Exception as e:
        logger.warning("[price] Supabase 저장 실패 %s: %s → 메모리 저장", code, e)

    # ── 메모리 폴백 ───────────────────────────────────────────
    _MEMORY_CACHE[code] = df.copy()
    logger.info("[price] %s 메모리 저장: %d건", code, len(df))
    return {"saved": len(df), "mode": "memory", "error": None}


def load_daily_prices(stock_code: str) -> pd.DataFrame:
    """
    저장된 일봉 데이터를 불러옵니다.

    - Supabase 연결 시: daily_prices 테이블에서 조회 (최신 120건, 날짜 오름차순)
    - 미연결 시        : 메모리 캐시에서 조회

    Args:
        stock_code : 6자리 종목코드

    Returns:
        DataFrame. 데이터 없으면 빈 DataFrame.
    """
    code = str(stock_code).zfill(6)

    # ── Supabase 조회 ─────────────────────────────────────────
    try:
        from services.supabase_client import get_client, is_connected
        if is_connected():
            resp = (
                get_client()
                .table("daily_prices")
                .select("*")
                .eq("stock_code", code)
                .order("price_date", desc=False)
                .limit(120)
                .execute()
            )
            rows = resp.data or []
            if rows:
                df = pd.DataFrame(rows)
                df.rename(columns={"price_date": "date"}, inplace=True)
                logger.info("[price] %s Supabase 로드: %d건", code, len(df))
                return df
    except Exception as e:
        logger.warning("[price] Supabase 로드 실패 %s: %s → 메모리 조회", code, e)

    # ── 메모리 폴백 ───────────────────────────────────────────
    cached = _MEMORY_CACHE.get(code)
    if cached is not None:
        logger.info("[price] %s 메모리 로드: %d건", code, len(cached))
        return cached.copy()

    logger.info("[price] %s 저장 데이터 없음 → 빈 DataFrame 반환", code)
    return pd.DataFrame()


def update_daily_prices_for_candidates(
    candidate_list: list[str | dict],
    days: int = 120,
) -> dict[str, Any]:
    """
    후보 종목 전체의 일봉 데이터를 일괄 갱신합니다.

    Args:
        candidate_list : 종목코드 문자열 리스트 또는 {"stock_code": ...} 딕셔너리 리스트
        days           : 조회 기간 (기본 120 거래일)

    Returns:
        {
            "total":   int,           # 처리 대상 종목 수
            "success": int,           # 성공 종목 수
            "failed":  int,           # 실패 종목 수
            "details": list[dict],    # 종목별 결과 상세
        }

    Example:
        from services.price_service import update_daily_prices_for_candidates

        # 종목코드 리스트로 호출
        result = update_daily_prices_for_candidates(["005930", "000660"])

        # 스캐너 결과 DataFrame 에서 직접 호출
        scored_df = scan(market_df)
        result = update_daily_prices_for_candidates(
            scored_df[scored_df["decision"] == "관심"]["stock_code"].tolist()
        )
    """
    # 입력 정규화: str | dict → str
    codes: list[str] = []
    for item in candidate_list:
        if isinstance(item, dict):
            code = item.get("stock_code", "")
        else:
            code = str(item)
        code = code.strip().zfill(6)
        if code:
            codes.append(code)

    total   = len(codes)
    success = 0
    failed  = 0
    details: list[dict[str, Any]] = []

    for code in codes:
        try:
            df     = fetch_daily_prices(code, days=days)
            result = save_daily_prices(code, df)
            success += 1
            details.append({
                "stock_code": code,
                "status":     "success",
                "saved":      result["saved"],
                "mode":       result["mode"],
                "rows":       len(df),
            })
            logger.info("[price] %s 갱신 완료 (%d건)", code, len(df))
        except Exception as e:
            failed += 1
            details.append({
                "stock_code": code,
                "status":     "failed",
                "error":      str(e),
            })
            logger.warning("[price] %s 갱신 실패: %s", code, e)

    summary = {
        "total":   total,
        "success": success,
        "failed":  failed,
        "details": details,
    }
    logger.info("[price] 일괄 갱신 완료 — 성공 %d / 실패 %d / 전체 %d", success, failed, total)
    return summary
