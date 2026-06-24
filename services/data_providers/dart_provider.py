"""
services/data_providers/dart_provider.py
OpenDART API 기반 재무 데이터 조회 (ROE, 부채비율)

API 키 발급: https://dart.fss.or.kr → 인증키 신청 (무료)
환경변수: DART_API_KEY
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

import requests
from dotenv import load_dotenv

load_dotenv()

logger  = logging.getLogger(__name__)
_BASE   = "https://opendart.fss.or.kr/api"
_TIMEOUT = 8


def is_available() -> bool:
    """DART_API_KEY 환경변수 존재 여부"""
    return bool(os.getenv("DART_API_KEY", "").strip())


def _api_key() -> str:
    return os.getenv("DART_API_KEY", "").strip()


@lru_cache(maxsize=512)
def get_corp_code(stock_code: str) -> str | None:
    """
    종목코드 → DART 고유번호(corp_code) 변환 (캐시 적용).
    """
    try:
        r = requests.get(
            f"{_BASE}/company.json",
            params={"crtfc_key": _api_key(), "stock_code": stock_code},
            timeout=_TIMEOUT,
        )
        data = r.json()
        if data.get("status") == "000":
            return data.get("corp_code")
    except Exception as e:
        logger.warning("[DART] corp_code 조회 실패 %s: %s", stock_code, e)
    return None


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
        return None

    from datetime import date
    current_year = date.today().year

    # 사업보고서(11011) → 없으면 반기(11012) → 없으면 1분기(11013) 순 시도
    report_codes = [
        (str(current_year - 1), "11011"),  # 전년도 사업보고서
        (str(current_year - 1), "11012"),  # 전년도 반기보고서
        (str(current_year),     "11013"),  # 당년도 1분기
    ]

    for year, reprt_code in report_codes:
        result = _fetch_ratios(corp_code, year, reprt_code)
        if result:
            return result

    return None


def _fetch_ratios(corp_code: str, bsns_year: str, reprt_code: str) -> dict | None:
    """단일 재무제표에서 ROE·부채비율을 추출합니다."""
    try:
        r = requests.get(
            f"{_BASE}/fnlttSinglAcntAll.json",
            params={
                "crtfc_key": _api_key(),
                "corp_code":  corp_code,
                "bsns_year":  bsns_year,
                "reprt_code": reprt_code,
                "fs_div":     "CFS",  # 연결재무제표 우선
            },
            timeout=_TIMEOUT,
        )
        items = r.json().get("list", [])

        # 개별재무제표로 재시도
        if not items:
            r = requests.get(
                f"{_BASE}/fnlttSinglAcntAll.json",
                params={
                    "crtfc_key": _api_key(),
                    "corp_code":  corp_code,
                    "bsns_year":  bsns_year,
                    "reprt_code": reprt_code,
                    "fs_div":     "OFS",
                },
                timeout=_TIMEOUT,
            )
            items = r.json().get("list", [])

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
        logger.warning("[DART] 재무 조회 실패 %s %s: %s", corp_code, bsns_year, e)
        return None
