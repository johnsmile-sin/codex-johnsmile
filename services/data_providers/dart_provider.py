"""
services/data_providers/dart_provider.py
OpenDART API 기반 재무 데이터 조회

corp_code 변환 방식:
  DART /api/corpCode.xml → ZIP → CORPCODE.xml 파싱으로
  stock_code → corp_code 매핑을 구축합니다. (최초 1회 캐시)

API 키 발급: https://opendart.fss.or.kr → 인증키 신청 (무료)
환경변수: DART_API_KEY
"""

from __future__ import annotations

import io
import logging
import os
import zipfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

logger   = logging.getLogger(__name__)
_BASE    = "https://opendart.fss.or.kr/api"
_TIMEOUT = 15

# corp_code 매핑 캐시 (메모리, 앱 재시작 시 초기화)
_CORP_CODE_MAP: dict[str, str] = {}   # stock_code → corp_code
_MAP_LOADED = False


def is_available() -> bool:
    """DART_API_KEY 환경변수 존재 여부"""
    return bool(os.getenv("DART_API_KEY", "").strip())


def _api_key() -> str:
    return os.getenv("DART_API_KEY", "").strip()


# ════════════════════════════════════════════════════════════════
# corp_code 매핑 (stock_code → corp_code)
# ════════════════════════════════════════════════════════════════

def _load_corp_code_map() -> bool:
    """
    DART corpCode.xml ZIP을 다운로드해 stock_code → corp_code 딕셔너리를 빌드합니다.
    성공 시 True 반환.
    """
    global _CORP_CODE_MAP, _MAP_LOADED
    if _MAP_LOADED:
        return bool(_CORP_CODE_MAP)

    try:
        r = requests.get(
            f"{_BASE}/corpCode.xml",
            params={"crtfc_key": _api_key()},
            timeout=30,
        )
        r.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            xml_name = next((n for n in z.namelist() if n.upper().endswith(".XML")), None)
            if not xml_name:
                logger.warning("[DART] ZIP 안에 XML 파일이 없습니다.")
                return False
            xml_data = z.read(xml_name)

        root = ET.fromstring(xml_data)
        mapping: dict[str, str] = {}
        for elem in root.iter("list"):
            sc = (elem.findtext("stock_code") or "").strip()
            cc = (elem.findtext("corp_code") or "").strip()
            if sc and cc:
                mapping[sc] = cc

        _CORP_CODE_MAP = mapping
        _MAP_LOADED = True
        logger.info("[DART] corp_code 매핑 로드 완료: %d개 종목", len(mapping))
        return True

    except Exception as e:
        logger.warning("[DART] corpCode.xml 로드 실패: %s", e)
        _MAP_LOADED = True   # 재시도 방지
        return False


def get_corp_code(stock_code: str) -> str | None:
    """종목코드 → DART 고유번호(corp_code) 반환. 없으면 None."""
    if not _MAP_LOADED:
        _load_corp_code_map()
    return _CORP_CODE_MAP.get(str(stock_code).zfill(6))


# ════════════════════════════════════════════════════════════════
# 재무 데이터 조회
# ════════════════════════════════════════════════════════════════

def get_financial_ratios(stock_code: str) -> dict | None:
    """
    OpenDART에서 최근 사업연도 재무비율(ROE, 부채비율)을 조회합니다.

    Returns:
        {"roe": float, "debt_ratio": float} 또는 None (실패 시)
    """
    if not is_available():
        return None

    corp_code = get_corp_code(stock_code)
    if not corp_code:
        logger.warning("[DART] corp_code 없음: %s", stock_code)
        return None

    from datetime import date
    current_year = date.today().year

    # 사업보고서(11011) → 반기(11012) → 1분기(11013) 순 시도
    for year, reprt_code in [
        (str(current_year - 1), "11011"),
        (str(current_year - 1), "11012"),
        (str(current_year),     "11013"),
    ]:
        result = _fetch_ratios(corp_code, year, reprt_code)
        if result:
            return result

    return None


def get_financial_statements(stock_code: str, years: int = 3) -> list[dict]:
    """
    최근 N개 사업연도 재무제표를 조회합니다.

    Returns:
        [{"fiscal_year": "2024", "revenue": float, "operating_profit": float,
          "net_profit": float, "roe": float, "debt_ratio": float, ...}, ...]
        최신연도 순 정렬.
    """
    if not is_available():
        return []

    corp_code = get_corp_code(stock_code)
    if not corp_code:
        logger.warning("[DART] corp_code 없음: %s", stock_code)
        return []

    from datetime import date
    current_year = date.today().year
    results = []

    for i in range(1, years + 2):   # 여유분 +1
        year = str(current_year - i)
        data = _fetch_full_statement(corp_code, year, "11011")
        if data:
            data["fiscal_year"] = year
            results.append(data)
        if len(results) >= years:
            break

    return results


def _fetch_ratios(corp_code: str, bsns_year: str, reprt_code: str) -> dict | None:
    """단일 재무제표에서 ROE·부채비율을 추출합니다."""
    try:
        for fs_div in ("CFS", "OFS"):
            r = requests.get(
                f"{_BASE}/fnlttSinglAcntAll.json",
                params={
                    "crtfc_key":  _api_key(),
                    "corp_code":  corp_code,
                    "bsns_year":  bsns_year,
                    "reprt_code": reprt_code,
                    "fs_div":     fs_div,
                },
                timeout=_TIMEOUT,
            )
            items = r.json().get("list", [])
            if items:
                break

        if not items:
            return None

        acc: dict[str, float] = {}
        for item in items:
            acnt = item.get("account_nm", "")
            val  = str(item.get("thstrm_amount", "")).replace(",", "").strip()
            try:
                v = float(val)
            except ValueError:
                continue
            if acnt == "당기순이익":
                acc["net_income"] = v
            elif acnt == "자본총계":
                acc["equity"] = v
            elif acnt == "부채총계":
                acc["liabilities"] = v

        if "equity" not in acc or acc["equity"] <= 0:
            return None

        result: dict = {}
        if "net_income" in acc:
            result["roe"] = round(acc["net_income"] / acc["equity"] * 100, 1)
        if "liabilities" in acc:
            result["debt_ratio"] = round(acc["liabilities"] / acc["equity"] * 100, 1)
        result["dart_year"]  = bsns_year
        result["dart_reprt"] = reprt_code
        return result if len(result) > 1 else None

    except Exception as e:
        logger.warning("[DART] 재무비율 조회 실패 %s %s: %s", corp_code, bsns_year, e)
        return None


def _fetch_full_statement(corp_code: str, bsns_year: str, reprt_code: str) -> dict | None:
    """단일 사업연도 전체 재무제표 주요 항목을 추출합니다."""
    try:
        for fs_div in ("CFS", "OFS"):
            r = requests.get(
                f"{_BASE}/fnlttSinglAcntAll.json",
                params={
                    "crtfc_key":  _api_key(),
                    "corp_code":  corp_code,
                    "bsns_year":  bsns_year,
                    "reprt_code": reprt_code,
                    "fs_div":     fs_div,
                },
                timeout=_TIMEOUT,
            )
            data = r.json()
            items = data.get("list", [])
            if data.get("status") == "000" and items:
                break

        if not items:
            return None

        def _v(val: str) -> float:
            try:
                return float(str(val).replace(",", "").strip())
            except (ValueError, TypeError):
                return 0.0

        # key → (DART 계정명 후보들) 매핑
        _ACNT_MAP = {
            "revenue":           ("매출액", "영업수익"),
            "operating_profit":  ("영업이익", "영업이익(손실)"),
            "net_profit":        ("당기순이익", "당기순이익(손실)"),
            "equity":            ("자본총계",),
            "liabilities":       ("부채총계",),
            "current_assets":    ("유동자산",),
            "current_liabilities": ("유동부채",),
        }
        _ACNT_REVERSE: dict[str, str] = {
            name: key
            for key, names in _ACNT_MAP.items()
            for name in names
        }

        acc: dict[str, float] = {}
        for item in items:
            acnt = item.get("account_nm", "")
            key  = _ACNT_REVERSE.get(acnt)
            if key is None or key in acc:
                # 이미 값이 있으면 스킵 (첫 번째 유효 값 우선)
                continue
            v = _v(item.get("thstrm_amount", "0"))
            if v != 0.0:
                acc[key] = v

        if not acc.get("revenue"):
            return None

        revenue = acc.get("revenue", 0)
        op      = acc.get("operating_profit", 0)
        net     = acc.get("net_profit", 0)
        equity  = acc.get("equity", 1)
        liab    = acc.get("liabilities", 0)
        cur_a   = acc.get("current_assets", 0)
        cur_l   = acc.get("current_liabilities", 1)

        # 억원 단위로 변환 (DART는 원 단위)
        to_uk = lambda x: round(x / 1e8, 1)

        result = {
            "revenue":          to_uk(revenue),
            "operating_profit": to_uk(op),
            "net_profit":       to_uk(net),
            "operating_margin": round(op / revenue * 100, 1) if revenue else 0.0,
            "net_margin":       round(net / revenue * 100, 1) if revenue else 0.0,
            "roe":              round(net / equity * 100, 1) if equity > 0 else 0.0,
            "debt_ratio":       round(liab / equity * 100, 1) if equity > 0 else 0.0,
            "current_ratio":    round(cur_a / cur_l * 100, 1) if cur_l > 0 else 0.0,
            "data_source":      "DART",
        }
        return result

    except Exception as e:
        logger.warning("[DART] 전체 재무제표 조회 실패 %s %s: %s", corp_code, bsns_year, e)
        return None
