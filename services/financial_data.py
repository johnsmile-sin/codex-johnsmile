"""
services/financial_data.py v2  —  재무 데이터 서비스

공개 API:
    get_financial_metrics(stock_code, stock_name)         → dict
    fetch_financial_from_dart(stock_code)                 → list[dict]
    load_financial_from_csv(file_path)                    → list[dict]
    save_financial_metrics_to_supabase(data)              → dict
    get_financial_metrics_from_supabase(stock_code)       → list[dict]

    # 하위호환 유지
    get_financial_data(stock_code, mock_per, …)           → dict

반환 구조 (get_financial_metrics):
    {
        "stock_code":  str,
        "stock_name":  str,
        "fin_source":  "DART" | "CSV" | "Mock",
        "years": [
            {
                "fiscal_year":       str,   # "2024"
                "revenue":           float, # 매출액 (억원)
                "operating_profit":  float, # 영업이익 (억원)
                "net_profit":        float, # 순이익 (억원)
                "operating_margin":  float, # 영업이익률 (%)
                "net_margin":        float, # 순이익률 (%)
                "per":               float,
                "pbr":               float,
                "roe":               float, # %
                "debt_ratio":        float, # %
                "current_ratio":     float, # %
                "data_source":       str,
            },
            ...  # 최근 3년, 최신순
        ],
        "latest": { ... }  # years[0]
    }

CSV 포맷:
    stock_code, fiscal_year, revenue, operating_profit, net_profit,
    operating_margin, net_margin, per, pbr, roe, debt_ratio, current_ratio
"""

from __future__ import annotations

import csv
import logging
import random
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CURRENT_YEAR = date.today().year
# 재무보고서 발표 시차 고려: 직전 3개 사업연도
_FISCAL_YEARS = [str(_CURRENT_YEAR - i) for i in range(1, 4)]


# ════════════════════════════════════════════════════════════════
# Mock 재무 데이터 정의
# ════════════════════════════════════════════════════════════════

# (revenue_base억, op_margin%, net_margin%, per, pbr, debt_ratio%, current_ratio%)
_MOCK_BASE: dict[str, tuple] = {
    "005930": (3_000_000, 13.0,  9.5, 14.5, 1.5, 35.0, 220.0),  # 삼성전자
    "000660": (  350_000, 10.0,  7.0, 18.0, 1.8, 42.0, 190.0),  # SK하이닉스
    "035420": (   98_000, 18.0, 13.0, 22.0, 2.8, 28.0, 310.0),  # NAVER
    "035720": (   80_000,  8.0,  5.0, 35.0, 1.6, 55.0, 140.0),  # 카카오
    "005380": (1_700_000,  8.5,  6.5, 10.0, 0.8, 120.0, 130.0), # 현대차
    "000270": (  850_000,  9.0,  7.0,  9.5, 0.9, 110.0, 125.0), # 기아
    "006400": (  220_000,  5.0,  3.0, 30.0, 1.2, 90.0,  150.0), # 삼성SDI
    "373220": (  350_000,  2.0,  0.5, 60.0, 2.0, 140.0, 120.0), # LG에너지솔루션
    "207940": (   36_000, 25.0, 20.0, 45.0, 6.0, 18.0,  280.0), # 삼성바이오로직스
    "068270": (   30_000, 22.0, 18.0, 40.0, 5.5, 25.0,  250.0), # 셀트리온
    "051910": (  550_000,  4.0,  2.0, 25.0, 0.8, 75.0,  120.0), # LG화학
    "096770": (  220_000,  5.0,  3.0, 10.0, 0.7, 80.0,  130.0), # SK이노베이션
    "055550": (  160_000, 28.0, 22.0, 10.0, 0.6, 900.0, 120.0), # 신한지주 (금융)
    "105560": (  150_000, 30.0, 23.0,  9.0, 0.5, 950.0, 115.0), # KB금융
    "011200": (   40_000, 35.0, 28.0,  6.0, 0.5, 80.0,  180.0), # HMM
    "247540": (   50_000,  5.0,  3.0, 40.0, 2.5, 85.0,  140.0), # 에코프로비엠
    "086520": (  110_000,  8.0,  5.0, 50.0, 3.0, 90.0,  130.0), # 에코프로
    "066570": (  850_000,  5.0,  3.5, 12.0, 0.9, 95.0,  140.0), # LG전자
    "009540": (  280_000, 10.0,  7.0, 15.0, 1.3, 60.0,  160.0), # HD한국조선해양
    "028260": (  250_000,  5.0,  3.0, 20.0, 0.9, 45.0,  170.0), # 삼성물산
}
_MOCK_DEFAULT = (100_000, 7.0, 5.0, 20.0, 1.5, 60.0, 150.0)

# 연도별 성장률 노이즈 (시드 기반 재현성)
def _year_growth(seed: int, year_idx: int) -> float:
    """연도별 매출 성장률 (-15% ~ +25%) — 재현 가능한 랜덤"""
    rng = random.Random(seed * 100 + year_idx)
    return 1.0 + rng.uniform(-0.15, 0.25)


def _mock_year(
    stock_code: str,
    fiscal_year: str,
    year_idx: int,       # 0=최신, 1=1년전, 2=2년전
) -> dict:
    """단일 연도 Mock 재무 데이터 딕셔너리"""
    base = _MOCK_BASE.get(stock_code, _MOCK_DEFAULT)
    rev_base, op_m, net_m, per, pbr, debt, curr = base

    seed = int(stock_code) % 9999 if stock_code.isdigit() else hash(stock_code) % 9999

    # 연도가 오래될수록 매출이 낮음 (성장 시뮬레이션)
    rev = rev_base
    for i in range(year_idx, 0, -1):
        rev = rev / _year_growth(seed, i)

    rev = round(rev, 1)
    op  = round(rev * op_m  / 100, 1)
    net = round(rev * net_m / 100, 1)

    # 연도별 소폭 지표 변동
    rng = random.Random(seed + year_idx * 37)
    roe = round(net / max(rev * 0.6, 1) * 100 + rng.uniform(-2, 2), 1)

    return {
        "fiscal_year":      fiscal_year,
        "revenue":          rev,
        "operating_profit": op,
        "net_profit":       net,
        "operating_margin": round(op_m  + rng.uniform(-1.5, 1.5), 1),
        "net_margin":       round(net_m + rng.uniform(-1.0, 1.0), 1),
        "per":              round(per   + rng.uniform(-3.0, 3.0), 1),
        "pbr":              round(pbr   + rng.uniform(-0.2, 0.2), 2),
        "roe":              roe,
        "debt_ratio":       round(debt  + rng.uniform(-10, 10), 1),
        "current_ratio":    round(curr  + rng.uniform(-20, 20), 1),
        "data_source":      "Mock",
    }


# ════════════════════════════════════════════════════════════════
# 1. fetch_financial_from_dart
# ════════════════════════════════════════════════════════════════

def fetch_financial_from_dart(stock_code: str) -> list[dict]:
    """
    OpenDART API로 최근 3년 재무 데이터를 조회합니다.

    DART_API_KEY 가 없으면 즉시 빈 리스트를 반환합니다.
    API 오류가 발생해도 앱이 중단되지 않습니다.

    Args:
        stock_code: 6자리 종목코드

    Returns:
        최신순 재무 연도 딕셔너리 리스트 (최대 3개).
        각 항목에 data_source="DART" 포함.
        실패 시 빈 리스트 반환.
    """
    try:
        from config import DART_API_KEY
    except ImportError:
        DART_API_KEY = None

    if not DART_API_KEY:
        logger.debug("[재무] DART API 키 없음 → Mock 폴백")
        return []

    try:
        from services.data_providers.dart_provider import get_corp_code
        corp_code = get_corp_code(stock_code)
        if not corp_code:
            logger.warning("[재무] DART corp_code 없음: %s", stock_code)
            return []
    except Exception as e:
        logger.warning("[재무] DART corp_code 조회 실패 %s: %s", stock_code, e)
        return []

    results: list[dict] = []

    for year_idx, fiscal_year in enumerate(_FISCAL_YEARS):
        row = _dart_fetch_year(corp_code, fiscal_year, DART_API_KEY)
        if row:
            row["fiscal_year"] = fiscal_year
            row["data_source"] = "DART"
            results.append(row)

    if results:
        logger.info("[재무] DART 조회 완료: %s → %d년", stock_code, len(results))
    return results


def _dart_fetch_year(corp_code: str, bsns_year: str, api_key: str) -> dict | None:
    """
    단일 사업연도 재무 데이터를 DART fnlttSinglAcntAll API로 조회합니다.

    조회 계정과목:
        매출액, 영업이익, 당기순이익, 자본총계, 부채총계, 유동자산, 유동부채

    TODO: PER·PBR은 DART에서 직접 제공하지 않으므로
          FDR 또는 별도 시장 데이터로 보완 필요.
    TODO: 연결재무제표(CFS) 우선, 없으면 개별(OFS) 재시도.
    TODO: reprt_code: 11011(사업보고서), 11012(반기), 11013(1분기) 순 시도.
    """
    import requests

    _BASE    = "https://opendart.fss.or.kr/api"
    _TIMEOUT = 8

    # 보고서 종류 우선순위: 사업보고서(11011) → 반기(11012) → 1분기(11013)
    for reprt_code in ["11011", "11012", "11013"]:
        for fs_div in ["CFS", "OFS"]:  # 연결 우선, 없으면 개별
            try:
                resp = requests.get(
                    f"{_BASE}/fnlttSinglAcntAll.json",
                    params={
                        "crtfc_key":  api_key,
                        "corp_code":  corp_code,
                        "bsns_year":  bsns_year,
                        "reprt_code": reprt_code,
                        "fs_div":     fs_div,
                    },
                    timeout=_TIMEOUT,
                )
                items = resp.json().get("list", [])
            except Exception as e:
                logger.debug("[DART] API 오류 %s %s: %s", bsns_year, reprt_code, e)
                continue

            if not items:
                continue

            # 계정과목 → 금액 매핑 (단위: 원 → 억원 변환)
            acc: dict[str, float] = {}
            _ACCOUNT_MAP = {
                "매출액":    "revenue",
                "영업수익":  "revenue",        # 금융사 대체 계정
                "영업이익":  "operating_profit",
                "당기순이익": "net_profit",
                "자본총계":  "equity",
                "부채총계":  "liabilities",
                "유동자산":  "current_assets",
                "유동부채":  "current_liabilities",
            }
            for item in items:
                acnt = item.get("account_nm", "")
                val  = str(item.get("thstrm_amount", "")).replace(",", "").strip()
                if acnt in _ACCOUNT_MAP:
                    try:
                        acc[_ACCOUNT_MAP[acnt]] = float(val) / 1e8  # 원 → 억원
                    except ValueError:
                        pass

            # 필수 항목 누락 시 다음 보고서 시도
            if "revenue" not in acc or "equity" not in acc:
                continue

            rev    = acc.get("revenue", 0)
            op     = acc.get("operating_profit", 0)
            net    = acc.get("net_profit", 0)
            equity = acc.get("equity", 1)
            liab   = acc.get("liabilities", 0)
            c_ast  = acc.get("current_assets", 0)
            c_liab = acc.get("current_liabilities", 1)

            return {
                "revenue":           round(rev, 1),
                "operating_profit":  round(op,  1),
                "net_profit":        round(net, 1),
                "operating_margin":  round(op  / rev   * 100, 1) if rev   > 0 else 0.0,
                "net_margin":        round(net / rev   * 100, 1) if rev   > 0 else 0.0,
                "roe":               round(net / equity * 100, 1) if equity > 0 else 0.0,
                "debt_ratio":        round(liab / equity * 100, 1) if equity > 0 else 0.0,
                "current_ratio":     round(c_ast / c_liab * 100, 1) if c_liab > 0 else 0.0,
                # TODO: PER·PBR은 시장 데이터에서 보완 (DART 미제공)
                "per":               0.0,
                "pbr":               0.0,
                "dart_reprt":        reprt_code,
            }

    return None


# ════════════════════════════════════════════════════════════════
# 2. load_financial_from_csv
# ════════════════════════════════════════════════════════════════

_CSV_REQUIRED_COLS = {
    "stock_code", "fiscal_year", "revenue", "operating_profit", "net_profit",
}
_CSV_OPTIONAL_COLS = {
    "operating_margin", "net_margin", "per", "pbr",
    "roe", "debt_ratio", "current_ratio", "stock_name",
}


def load_financial_from_csv(file_path: str | Path) -> list[dict]:
    """
    CSV 파일에서 재무 데이터를 로드합니다.

    필수 컬럼:
        stock_code, fiscal_year, revenue, operating_profit, net_profit

    선택 컬럼:
        operating_margin, net_margin, per, pbr, roe, debt_ratio, current_ratio,
        stock_name

    누락된 선택 컬럼은 자동 계산하거나 0으로 채웁니다.
    숫자 단위: 매출·이익은 억원, 비율은 % 기준.

    CSV 예시:
        stock_code,fiscal_year,revenue,operating_profit,net_profit,roe,debt_ratio
        005930,2024,3100000,403000,294500,12.5,35.0
        005930,2023,2580000,65000,154900,4.3,36.0

    Args:
        file_path: CSV 파일 경로

    Returns:
        재무 딕셔너리 리스트 (fiscal_year 내림차순).
        각 항목에 data_source="CSV" 포함.

    Raises:
        FileNotFoundError: 파일이 없을 때
        ValueError: 필수 컬럼 누락 또는 데이터 형식 오류
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV 파일 없음: {path}")

    rows: list[dict] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        # 헤더 검증
        if reader.fieldnames is None:
            raise ValueError("CSV 파일이 비어 있습니다.")
        cols = {c.strip().lower() for c in reader.fieldnames}
        missing = _CSV_REQUIRED_COLS - cols
        if missing:
            raise ValueError(f"필수 컬럼 누락: {missing}")

        for i, raw in enumerate(reader, start=2):
            row = {k.strip().lower(): v.strip() for k, v in raw.items() if v}
            try:
                code  = str(row["stock_code"]).zfill(6)
                year  = str(row["fiscal_year"]).strip()
                rev   = float(row["revenue"])
                op    = float(row["operating_profit"])
                net   = float(row["net_profit"])
            except (KeyError, ValueError) as e:
                raise ValueError(f"CSV {i}행 파싱 오류: {e}")

            op_m = (
                float(row["operating_margin"])
                if "operating_margin" in row else
                round(op / rev * 100, 1) if rev else 0.0
            )
            net_m = (
                float(row["net_margin"])
                if "net_margin" in row else
                round(net / rev * 100, 1) if rev else 0.0
            )

            def _flt(key: str, default: float = 0.0) -> float:
                try:
                    return float(row[key]) if key in row else default
                except (ValueError, KeyError):
                    return default

            rows.append({
                "stock_code":       code,
                "stock_name":       row.get("stock_name", code),
                "fiscal_year":      year,
                "revenue":          rev,
                "operating_profit": op,
                "net_profit":       net,
                "operating_margin": op_m,
                "net_margin":       net_m,
                "per":              _flt("per"),
                "pbr":              _flt("pbr"),
                "roe":              _flt("roe"),
                "debt_ratio":       _flt("debt_ratio"),
                "current_ratio":    _flt("current_ratio"),
                "data_source":      "CSV",
            })

    rows.sort(key=lambda x: x["fiscal_year"], reverse=True)
    logger.info("[재무] CSV 로드: %s → %d행", path.name, len(rows))
    return rows


# ════════════════════════════════════════════════════════════════
# 3. save_financial_metrics_to_supabase
# ════════════════════════════════════════════════════════════════

def save_financial_metrics_to_supabase(
    data: dict | list[dict],
) -> dict[str, Any]:
    """
    재무 데이터를 Supabase financial_metrics 테이블에 저장합니다.

    get_financial_metrics() 반환값 또는 연도 딕셔너리 리스트를 모두 수용합니다.
    중복 방지: (stock_code, fiscal_year) 기준 upsert.
    Supabase 미연결 시 조용히 실패합니다.

    Args:
        data: get_financial_metrics() 반환 dict, 또는 연도 dict 리스트

    Returns:
        {"saved": int, "skipped": int, "error": str | None}
    """
    # 입력 정규화
    if isinstance(data, dict):
        stock_code = data.get("stock_code", "")
        stock_name = data.get("stock_name", "")
        year_rows  = data.get("years", [])
    elif isinstance(data, list):
        stock_code = data[0].get("stock_code", "") if data else ""
        stock_name = data[0].get("stock_name", "") if data else ""
        year_rows  = data
    else:
        return {"saved": 0, "skipped": 0, "error": "지원하지 않는 입력 형식"}

    if not year_rows:
        return {"saved": 0, "skipped": 0, "error": None}

    try:
        from services.supabase_client import get_client, is_connected
        if not is_connected():
            return {"saved": 0, "skipped": len(year_rows), "error": "Supabase 미연결"}

        client = get_client()
        rows = [
            {
                "stock_code":       stock_code or yr.get("stock_code", ""),
                "stock_name":       stock_name or yr.get("stock_name", ""),
                "fiscal_year":      yr["fiscal_year"],
                "revenue":          yr.get("revenue",           0.0),
                "operating_profit": yr.get("operating_profit",  0.0),
                "net_profit":       yr.get("net_profit",        0.0),
                "operating_margin": yr.get("operating_margin",  0.0),
                "net_margin":       yr.get("net_margin",        0.0),
                "per":              yr.get("per",               0.0),
                "pbr":              yr.get("pbr",               0.0),
                "roe":              yr.get("roe",               0.0),
                "debt_ratio":       yr.get("debt_ratio",        0.0),
                "current_ratio":    yr.get("current_ratio",     0.0),
                "source":           yr.get("data_source",       "Mock"),
            }
            for yr in year_rows
        ]

        client.table("financial_metrics").upsert(
            rows,
            on_conflict="stock_code,fiscal_year",
        ).execute()

        saved = len(rows)
        logger.info("[재무] Supabase 저장: %s → %d건", stock_code, saved)
        return {"saved": saved, "skipped": 0, "error": None}

    except Exception as e:
        logger.warning("[재무] Supabase 저장 실패 %s: %s", stock_code, e)
        return {"saved": 0, "skipped": len(year_rows), "error": str(e)}


# ════════════════════════════════════════════════════════════════
# 4. get_financial_metrics_from_supabase
# ════════════════════════════════════════════════════════════════

def get_financial_metrics_from_supabase(stock_code: str) -> list[dict]:
    """
    Supabase financial_metrics 테이블에서 종목 재무 데이터를 조회합니다.

    Args:
        stock_code: 6자리 종목코드

    Returns:
        연도 딕셔너리 리스트 (fiscal_year 내림차순, 최대 3건).
        Supabase 미연결 또는 데이터 없으면 빈 리스트.
    """
    code = str(stock_code).zfill(6)
    try:
        from services.supabase_client import get_client, is_connected
        if not is_connected():
            return []

        resp = (
            get_client()
            .table("financial_metrics")
            .select("*")
            .eq("stock_code", code)
            .order("fiscal_year", desc=True)
            .limit(3)
            .execute()
        )
        rows = resp.data or []
        if rows:
            # Supabase 컬럼 → 내부 스키마 정렬
            return [
                {
                    "fiscal_year":      r["fiscal_year"],
                    "revenue":          r.get("revenue",           0.0),
                    "operating_profit": r.get("operating_profit",  0.0),
                    "net_profit":       r.get("net_profit",        0.0),
                    "operating_margin": r.get("operating_margin",  0.0),
                    "net_margin":       r.get("net_margin",        0.0),
                    "per":              r.get("per",               0.0),
                    "pbr":              r.get("pbr",               0.0),
                    "roe":              r.get("roe",               0.0),
                    "debt_ratio":       r.get("debt_ratio",        0.0),
                    "current_ratio":    r.get("current_ratio",     0.0),
                    "data_source":      r.get("source",            "Mock"),
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("[재무] Supabase 조회 실패 %s: %s", code, e)
    return []


# ════════════════════════════════════════════════════════════════
# 5. get_financial_metrics  (메인 진입점)
# ════════════════════════════════════════════════════════════════

def get_financial_metrics(
    stock_code: str,
    stock_name: str = "",
) -> dict[str, Any]:
    """
    종목 재무 데이터를 최근 3년치 반환합니다.

    데이터 소스 우선순위:
        1. Supabase (캐시된 DART 또는 CSV 데이터)
        2. OpenDART API (DART_API_KEY 설정 시)
        3. Mock 데이터 (섹터별 현실적인 값)

    Args:
        stock_code: 6자리 종목코드 (예: "005930")
        stock_name: 종목명 (메타 정보용, 선택)

    Returns:
        {
            "stock_code":  str,
            "stock_name":  str,
            "fin_source":  "DART" | "CSV" | "Mock",
            "years":       list[dict],   # 최신순 3년
            "latest":      dict,         # years[0]
        }

    Example:
        metrics = get_financial_metrics("005930", "삼성전자")
        for yr in metrics["years"]:
            print(yr["fiscal_year"], yr["revenue"], yr["roe"])
        latest = metrics["latest"]
        print(latest["per"], latest["debt_ratio"])
    """
    code = str(stock_code).zfill(6)
    name = stock_name or code

    year_rows: list[dict] = []
    fin_source = "Mock"

    # 1순위: Supabase 캐시
    cached = get_financial_metrics_from_supabase(code)
    if cached:
        year_rows  = cached
        fin_source = cached[0].get("data_source", "Mock") if cached else "Mock"
        logger.info("[재무] %s Supabase 캐시 사용: %d건", code, len(year_rows))

    # 2순위: DART API
    if not year_rows:
        dart_rows = fetch_financial_from_dart(code)
        if dart_rows:
            year_rows  = dart_rows
            fin_source = "DART"
            # DART 결과를 Supabase에 캐시
            _rows_with_meta = [{**r, "stock_code": code, "stock_name": name} for r in dart_rows]
            save_financial_metrics_to_supabase({
                "stock_code": code,
                "stock_name": name,
                "years":      year_rows,
            })
            logger.info("[재무] %s DART 사용: %d건", code, len(year_rows))

    # 3순위: Mock
    if not year_rows:
        year_rows  = [_mock_year(code, yr, i) for i, yr in enumerate(_FISCAL_YEARS)]
        fin_source = "Mock"
        logger.info("[재무] %s Mock 사용", code)

    # 최신 3년만 유지
    year_rows = year_rows[:3]

    return {
        "stock_code": code,
        "stock_name": name,
        "fin_source": fin_source,
        "years":      year_rows,
        "latest":     year_rows[0] if year_rows else {},
    }


# ════════════════════════════════════════════════════════════════
# 하위호환 — 기존 get_financial_data() 유지
# ════════════════════════════════════════════════════════════════

def get_financial_data(
    stock_code: str,
    mock_per:   float,
    mock_pbr:   float,
    mock_roe:   float,
    mock_debt:  float,
) -> dict[str, Any]:
    """
    단일 연도 재무 요약 반환 (하위호환).
    app.py, openclaw/commands.py 등 기존 호출부가 그대로 동작합니다.

    Returns:
        {"per": float, "pbr": float, "roe": float, "debt_ratio": float, "fin_source": str}
    """
    metrics = get_financial_metrics(stock_code)
    latest  = metrics.get("latest", {})

    return {
        "per":        latest.get("per",        mock_per),
        "pbr":        latest.get("pbr",        mock_pbr),
        "roe":        latest.get("roe",        mock_roe),
        "debt_ratio": latest.get("debt_ratio", mock_debt),
        "fin_source": metrics.get("fin_source", "Mock"),
    }
