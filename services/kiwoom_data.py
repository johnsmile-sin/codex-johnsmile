"""
services/kiwoom_data.py  —  키움 OpenAPI 조회 전용 클라이언트

⚠️  주문 기능(매수/매도/취소)은 이 파일에 절대 구현하지 않습니다.

현재 상태:
    - API 키(KIWOOM_APP_KEY, KIWOOM_SECRET_KEY)가 없으면 Mock 데이터를 반환합니다.
    - 실제 API 호출 부분은 TODO로 표시되어 있습니다.
    - 구조와 에러 처리는 완성 상태입니다.

실제 연결 방법 (향후):
    1. .env 에 KIWOOM_APP_KEY, KIWOOM_SECRET_KEY 입력
    2. TODO 블록의 requests.post() 주석을 해제하고 실제 엔드포인트 URL 기입
    3. is_available() 이 True 를 반환하면 자동으로 실제 API를 사용합니다.

공식 문서: https://apiportal.koreainvestment.com
"""

from __future__ import annotations

import logging
import random
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from config import KIWOOM_APP_KEY, KIWOOM_SECRET_KEY

logger = logging.getLogger(__name__)

# ── API 엔드포인트 (실제 연결 시 채워 넣을 상수) ─────────────────
_BASE_URL  = "https://openapi.koreainvestment.com:9443"   # 실전
_BASE_URL_MOCK = "https://openapivts.koreainvestment.com:29443"  # 모의

_TIMEOUT = 10
_API_IMPLEMENTED = False


# ════════════════════════════════════════════════════════════════
# 내부: 인증 토큰 관리
# ════════════════════════════════════════════════════════════════

_access_token: str | None = None


def _get_token() -> str | None:
    """
    OAuth2 액세스 토큰을 발급받습니다.
    이미 발급된 토큰이 있으면 재사용합니다.

    TODO: 토큰 만료(24h) 자동 갱신 처리 추가
    """
    global _access_token
    if _access_token:
        return _access_token

    if not is_available():
        return None

    # TODO: 실제 토큰 발급 요청
    # import requests
    # resp = requests.post(
    #     f"{_BASE_URL}/oauth2/tokenP",
    #     json={
    #         "grant_type":   "client_credentials",
    #         "appkey":       KIWOOM_APP_KEY,
    #         "appsecret":    KIWOOM_SECRET_KEY,
    #     },
    #     timeout=_TIMEOUT,
    # )
    # resp.raise_for_status()
    # _access_token = resp.json()["access_token"]
    # return _access_token

    logger.info("[Kiwoom] TODO: 토큰 발급 미구현 → Mock 반환")
    return None


def _headers() -> dict[str, str]:
    """공통 요청 헤더 (토큰 포함)"""
    token = _get_token()
    return {
        "Content-Type":  "application/json",
        "authorization": f"Bearer {token}" if token else "",
        "appkey":        KIWOOM_APP_KEY  or "",
        "appsecret":     KIWOOM_SECRET_KEY or "",
        "tr_id":         "",   # 각 TR마다 덮어씀
    }


# ════════════════════════════════════════════════════════════════
# 가용 여부
# ════════════════════════════════════════════════════════════════

def is_available() -> bool:
    """국내주식 조회 API를 실제로 사용할 수 있는지 반환합니다."""
    return _API_IMPLEMENTED and bool(KIWOOM_APP_KEY and KIWOOM_SECRET_KEY)


# ════════════════════════════════════════════════════════════════
# Mock 데이터 생성 헬퍼 (API 키 없을 때 사용)
# ════════════════════════════════════════════════════════════════

_MOCK_STOCKS = [
    ("005930", "삼성전자",        "KOSPI",  "반도체",    75_000),
    ("000660", "SK하이닉스",      "KOSPI",  "반도체",   185_000),
    ("035720", "카카오",          "KOSPI",  "IT서비스",  52_000),
    ("035420", "NAVER",           "KOSPI",  "IT서비스", 220_000),
    ("005380", "현대차",          "KOSPI",  "자동차",   240_000),
    ("000270", "기아",            "KOSPI",  "자동차",    95_000),
    ("051910", "LG화학",          "KOSPI",  "화학",     420_000),
    ("006400", "삼성SDI",         "KOSPI",  "배터리",   380_000),
    ("207940", "삼성바이오로직스","KOSPI",  "바이오",   850_000),
    ("068270", "셀트리온",        "KOSPI",  "바이오",   170_000),
]


def _mock_daily_prices(stock_code: str, days: int) -> pd.DataFrame:
    """Mock 일봉 OHLCV 생성"""
    rng = random.Random(int(stock_code) % 9999)
    base = next(
        (p for c, *_, p in _MOCK_STOCKS if c == stock_code),
        50_000,
    )
    today = date.today()
    rows = []
    price = float(base)

    for i in range(days, 0, -1):
        d        = today - timedelta(days=i)
        if d.weekday() >= 5:        # 주말 제외
            continue
        chg      = rng.uniform(-0.04, 0.05)
        close    = max(100, round(price * (1 + chg)))
        open_p   = round(price * (1 + rng.uniform(-0.01, 0.01)))
        high     = round(max(open_p, close) * (1 + rng.uniform(0, 0.015)))
        low      = round(min(open_p, close) * (1 - rng.uniform(0, 0.015)))
        volume   = rng.randint(500_000, 15_000_000)
        rows.append({
            "date":    str(d),
            "open":    open_p,
            "high":    high,
            "low":     low,
            "close":   close,
            "volume":  volume,
            "source":  "Mock",
        })
        price = close

    return pd.DataFrame(rows)


def _mock_current_price(stock_code: str) -> dict[str, Any]:
    """Mock 현재가 조회"""
    rng   = random.Random(int(stock_code) % 9999 + 1)
    base  = next((p for c, *_, p in _MOCK_STOCKS if c == stock_code), 50_000)
    close = round(base * (1 + rng.uniform(-0.03, 0.05)))
    prev  = base
    chg   = round((close - prev) / prev * 100, 2)
    return {
        "stock_code":   stock_code,
        "current_price": close,
        "prev_close":   prev,
        "change":       close - prev,
        "change_rate":  chg,
        "volume":       rng.randint(500_000, 15_000_000),
        "source":       "Mock",
    }


def _mock_investor_trend(stock_code: str) -> pd.DataFrame:
    """Mock 투자자별 매매 동향 (5거래일)"""
    rng = random.Random(int(stock_code) % 9999 + 2)
    today = date.today()
    rows = []
    for i in range(5, 0, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        net_inst  = rng.randint(-500, 500) * 1_000_000
        net_fore  = rng.randint(-300, 300) * 1_000_000
        net_indiv = -(net_inst + net_fore)
        rows.append({
            "date":        str(d),
            "individual":  net_indiv,
            "institution": net_inst,
            "foreign":     net_fore,
            "source":      "Mock",
        })
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════
# 공개 조회 함수  (주문 기능 없음)
# ════════════════════════════════════════════════════════════════

def get_stock_list() -> pd.DataFrame:
    """
    거래소 상장 종목 전체 목록을 반환합니다.

    Returns:
        DataFrame — columns: stock_code, stock_name, market, sector
        Mock 모드: 내장 10개 샘플 종목 반환
    """
    if not is_available():
        logger.info("[Kiwoom] 키 없음 → Mock 종목 목록 반환")
        rows = [
            {"stock_code": c, "stock_name": n, "market": m, "sector": s, "source": "Mock"}
            for c, n, m, s, _ in _MOCK_STOCKS
        ]
        return pd.DataFrame(rows)

    # TODO: 실제 API 호출
    # import requests
    # headers = {**_headers(), "tr_id": "CTPF1002R"}
    # resp = requests.get(
    #     f"{_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-member-stocklist",
    #     headers=headers,
    #     params={"PDNO": "", "PRDT_TYPE_CD": "300"},
    #     timeout=_TIMEOUT,
    # )
    # resp.raise_for_status()
    # items = resp.json().get("output", [])
    # rows = [{"stock_code": x["pdno"], "stock_name": x["prdt_abrv_name"], ...} for x in items]
    # return pd.DataFrame(rows)

    logger.warning("[Kiwoom] TODO: get_stock_list() 실제 구현 필요 → Mock 반환")
    return get_stock_list.__wrapped__(self=None) if False else _fallback_stock_list()


def _fallback_stock_list() -> pd.DataFrame:
    rows = [
        {"stock_code": c, "stock_name": n, "market": m, "sector": s, "source": "Kiwoom(TODO)"}
        for c, n, m, s, _ in _MOCK_STOCKS
    ]
    return pd.DataFrame(rows)


def get_daily_prices(stock_code: str, days: int = 120) -> pd.DataFrame:
    """
    종목의 최근 N 거래일 일봉 데이터를 반환합니다.

    Args:
        stock_code : 6자리 종목코드 (예: "005930")
        days       : 조회 일수 (기본 120 거래일 ≈ 약 6개월)

    Returns:
        DataFrame — columns: date, open, high, low, close, volume, source
        Mock 모드: 무작위 샘플 데이터 반환
    """
    code = str(stock_code).zfill(6)

    if not is_available():
        logger.info("[Kiwoom] 키 없음 → Mock 일봉 반환 (%s)", code)
        return _mock_daily_prices(code, days)

    try:
        # TODO: 실제 API 호출 (TR: FHKST01010400)
        # import requests
        # end_dt   = date.today().strftime("%Y%m%d")
        # start_dt = (date.today() - timedelta(days=days * 2)).strftime("%Y%m%d")
        # headers  = {**_headers(), "tr_id": "FHKST01010400"}
        # resp = requests.get(
        #     f"{_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
        #     headers=headers,
        #     params={
        #         "FID_COND_MRKT_DIV_CODE": "J",
        #         "FID_INPUT_ISCD":         code,
        #         "FID_INPUT_DATE_1":       start_dt,
        #         "FID_INPUT_DATE_2":       end_dt,
        #         "FID_PERIOD_DIV_CODE":    "D",
        #         "FID_ORG_ADJ_PRC":        "0",
        #     },
        #     timeout=_TIMEOUT,
        # )
        # resp.raise_for_status()
        # output = resp.json().get("output2", [])
        # rows = [{"date": x["stck_bsop_date"], "open": int(x["stck_oprc"]), ...} for x in output]
        # df = pd.DataFrame(rows).tail(days)
        # df["source"] = "Kiwoom"
        # return df

        logger.warning("[Kiwoom] TODO: get_daily_prices(%s) 실제 구현 필요 → Mock 반환", code)
        return _mock_daily_prices(code, days)

    except Exception as e:
        logger.warning("[Kiwoom] get_daily_prices(%s) 실패: %s → Mock 반환", code, e)
        return _mock_daily_prices(code, days)


def get_current_price(stock_code: str) -> dict[str, Any]:
    """
    종목의 현재가(호가 포함)를 반환합니다.

    Args:
        stock_code : 6자리 종목코드

    Returns:
        dict — {stock_code, current_price, prev_close, change, change_rate, volume, source}
        Mock 모드: 무작위 샘플 반환
    """
    code = str(stock_code).zfill(6)

    if not is_available():
        logger.info("[Kiwoom] 키 없음 → Mock 현재가 반환 (%s)", code)
        return _mock_current_price(code)

    try:
        # TODO: 실제 API 호출 (TR: FHKST01010100)
        # import requests
        # headers = {**_headers(), "tr_id": "FHKST01010100"}
        # resp = requests.get(
        #     f"{_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
        #     headers=headers,
        #     params={
        #         "FID_COND_MRKT_DIV_CODE": "J",
        #         "FID_INPUT_ISCD":         code,
        #     },
        #     timeout=_TIMEOUT,
        # )
        # resp.raise_for_status()
        # out = resp.json().get("output", {})
        # return {
        #     "stock_code":    code,
        #     "current_price": int(out["stck_prpr"]),
        #     "prev_close":    int(out["stck_sdpr"]),
        #     "change":        int(out["prdy_vrss"]),
        #     "change_rate":   float(out["prdy_ctrt"]),
        #     "volume":        int(out["acml_vol"]),
        #     "source":        "Kiwoom",
        # }

        logger.warning("[Kiwoom] TODO: get_current_price(%s) 실제 구현 필요 → Mock 반환", code)
        return _mock_current_price(code)

    except Exception as e:
        logger.warning("[Kiwoom] get_current_price(%s) 실패: %s → Mock 반환", code, e)
        return _mock_current_price(code)


def get_investor_trend(stock_code: str) -> pd.DataFrame:
    """
    종목의 최근 5 거래일 투자자별 순매수 동향을 반환합니다.

    Args:
        stock_code : 6자리 종목코드

    Returns:
        DataFrame — columns: date, individual(개인), institution(기관), foreign(외국인), source
        양수 = 순매수, 음수 = 순매도 (단위: 원)
        Mock 모드: 무작위 샘플 반환
    """
    code = str(stock_code).zfill(6)

    if not is_available():
        logger.info("[Kiwoom] 키 없음 → Mock 투자자 동향 반환 (%s)", code)
        return _mock_investor_trend(code)

    try:
        # TODO: 실제 API 호출 (TR: FHKST01010900)
        # import requests
        # headers = {**_headers(), "tr_id": "FHKST01010900"}
        # resp = requests.get(
        #     f"{_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor",
        #     headers=headers,
        #     params={
        #         "FID_COND_MRKT_DIV_CODE": "J",
        #         "FID_INPUT_ISCD":         code,
        #         "FID_INPUT_DATE_1":       (date.today() - timedelta(days=10)).strftime("%Y%m%d"),
        #         "FID_INPUT_DATE_2":       date.today().strftime("%Y%m%d"),
        #         "FID_PERIOD_DIV_CODE":    "D",
        #     },
        #     timeout=_TIMEOUT,
        # )
        # resp.raise_for_status()
        # output = resp.json().get("output2", [])
        # rows = [
        #     {
        #         "date":        x["stck_bsop_date"],
        #         "individual":  int(x["prsn_ntby_qty"]),
        #         "institution": int(x["orgn_ntby_qty"]),
        #         "foreign":     int(x["frgn_ntby_qty"]),
        #         "source":      "Kiwoom",
        #     }
        #     for x in output
        # ]
        # return pd.DataFrame(rows)

        logger.warning("[Kiwoom] TODO: get_investor_trend(%s) 실제 구현 필요 → Mock 반환", code)
        return _mock_investor_trend(code)

    except Exception as e:
        logger.warning("[Kiwoom] get_investor_trend(%s) 실패: %s → Mock 반환", code, e)
        return _mock_investor_trend(code)


# ════════════════════════════════════════════════════════════════
# 비활성화 — 주문 관련 함수 (절대 호출 금지)
# ════════════════════════════════════════════════════════════════

def _DISABLED_place_buy_order(*args, **kwargs) -> None:
    """매수 주문 — 비활성화. 이 프로젝트에서 영구 사용 금지."""
    raise NotImplementedError("매수 주문 기능은 이 프로젝트에서 지원하지 않습니다.")


def _DISABLED_place_sell_order(*args, **kwargs) -> None:
    """매도 주문 — 비활성화. 이 프로젝트에서 영구 사용 금지."""
    raise NotImplementedError("매도 주문 기능은 이 프로젝트에서 지원하지 않습니다.")


def _DISABLED_cancel_order(*args, **kwargs) -> None:
    """주문 취소 — 비활성화. 이 프로젝트에서 영구 사용 금지."""
    raise NotImplementedError("주문 취소 기능은 이 프로젝트에서 지원하지 않습니다.")
