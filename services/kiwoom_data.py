"""
services/kiwoom_data.py  –  키움(한국투자증권 OpenAPI) 조회 전용 클라이언트 v4

⚠️  주문 함수는 이 파일에 구현하지 않습니다.
    주문 전송은 services/kiwoom_order_bridge.py 에서만 다룹니다.

동작 모드 (KIWOOM_INVEST_MODE):
    mock  (기본) API 키 없어도 실행 — 모든 함수가 Mock 데이터 반환
    paper 키움 모의투자 API 실제 호출 (KIWOOM_APP_KEY 필요)

보안 원칙:
    - 계좌번호는 로그에 마스킹 처리 후 기록 (예: 1234****)
    - Secret Key 는 절대 로그·화면에 출력하지 않음
    - API 응답 중 민감정보(잔고 원문 등)는 필드 선별 후만 반환

공개 함수:
    is_available()                     실제 API 사용 가능 여부
    get_access_token()                 OAuth2 토큰 발급/재사용
    get_stock_list()                   상장 종목 목록
    get_current_price(stock_code)      현재가
    get_daily_prices(stock_code, days) 일봉 OHLCV
    get_account_balance()              계좌 잔고 요약
    get_positions()                    보유 종목 목록
    get_orderable_amount(stock_code)   종목별 주문 가능 금액
    get_order_history()                당일 주문 내역 (조회 전용)
"""

from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from config import (
    KIWOOM_APP_KEY,
    KIWOOM_SECRET_KEY,
    KIWOOM_MOCK_ACCOUNT_NO,
    KIWOOM_INVEST_MODE,
)

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════
# 엔드포인트 & 상수
# ════════════════════════════════════════════════════════════════

_BASE_URL_PAPER = "https://openapivts.koreainvestment.com:29443"  # 모의투자
_BASE_URL_REAL  = "https://openapi.koreainvestment.com:9443"      # 실전 (사용 안 함)
_TIMEOUT        = 10   # 초

# 모드별 TR 코드 (조회 전용)
_TR = {
    "paper": {
        "token":          "/oauth2/tokenP",
        "stock_list":     "CTPF1002R",
        "current_price":  "FHKST01010100",
        "daily_prices":   "FHKST01010400",
        "account_balance":"VTTC8434R",
        "positions":      "VTTC8434R",
        "orderable":      "VTTC8908R",
        "order_history":  "VTTC8001R",
    },
}


# ════════════════════════════════════════════════════════════════
# 토큰 캐시 (모듈 레벨 — 24h 유효)
# ════════════════════════════════════════════════════════════════

class _TokenCache:
    token:      str | None = None
    expires_at: datetime | None = None

    @classmethod
    def get(cls) -> str | None:
        if cls.token and cls.expires_at and datetime.now() < cls.expires_at:
            return cls.token
        return None

    @classmethod
    def set(cls, token: str, ttl_seconds: int = 86_000) -> None:
        cls.token      = token
        cls.expires_at = datetime.now() + timedelta(seconds=ttl_seconds)

    @classmethod
    def clear(cls) -> None:
        cls.token      = None
        cls.expires_at = None


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼
# ════════════════════════════════════════════════════════════════

def _base_url() -> str:
    return _BASE_URL_PAPER   # 실전 엔드포인트는 사용하지 않음


def _mask_account(account_no: str | None) -> str:
    """계좌번호 중간을 마스킹한다. 로그 전용."""
    if not account_no:
        return "(없음)"
    s = str(account_no)
    if len(s) <= 4:
        return "****"
    return s[:4] + "*" * (len(s) - 4)


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(str(val).replace(",", "").strip() or default)
    except (ValueError, TypeError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(str(val).replace(",", "").replace("%", "").strip() or default)
    except (ValueError, TypeError):
        return default


def _headers(tr_id: str = "", token: str | None = None) -> dict[str, str]:
    """공통 요청 헤더. Secret Key는 절대 로그에 남기지 않는다."""
    tok = token or _TokenCache.get() or ""
    return {
        "Content-Type":  "application/json; charset=utf-8",
        "authorization": f"Bearer {tok}",
        "appkey":        KIWOOM_APP_KEY    or "",
        "appsecret":     KIWOOM_SECRET_KEY or "",   # 헤더에만 사용, 절대 출력 금지
        "tr_id":         tr_id,
        "custtype":      "P",
    }


# ════════════════════════════════════════════════════════════════
# 가용성 확인
# ════════════════════════════════════════════════════════════════

def is_available() -> bool:
    """실제 API 호출이 가능한지 반환합니다. Mock 모드이면 False."""
    return KIWOOM_INVEST_MODE == "paper" and bool(KIWOOM_APP_KEY and KIWOOM_SECRET_KEY)


# ════════════════════════════════════════════════════════════════
# Mock 데이터 생성
# ════════════════════════════════════════════════════════════════

_MOCK_STOCKS = [
    ("005930", "삼성전자",         "KOSPI", "반도체",      75_000),
    ("000660", "SK하이닉스",       "KOSPI", "반도체",     185_000),
    ("035720", "카카오",           "KOSPI", "IT서비스",    52_000),
    ("035420", "NAVER",            "KOSPI", "IT서비스",   220_000),
    ("005380", "현대차",           "KOSPI", "자동차",     240_000),
    ("000270", "기아",             "KOSPI", "자동차",      95_000),
    ("051910", "LG화학",           "KOSPI", "화학",       420_000),
    ("006400", "삼성SDI",          "KOSPI", "배터리",     380_000),
    ("207940", "삼성바이오로직스", "KOSPI", "바이오",     850_000),
    ("068270", "셀트리온",         "KOSPI", "바이오",     170_000),
]

_MOCK_HOLDINGS = [
    ("005930", "삼성전자",   10, 72_000),
    ("035420", "NAVER",       2, 215_000),
    ("000660", "SK하이닉스",  5, 178_000),
]


def _mock_current_price(stock_code: str) -> dict[str, Any]:
    rng  = random.Random(int(stock_code) % 9999 + 1)
    base = next((p for c, *_, p in _MOCK_STOCKS if c == stock_code), 50_000)
    close = round(base * (1 + rng.uniform(-0.03, 0.05)))
    prev  = base
    chg   = round((close - prev) / prev * 100, 2)
    return {
        "stock_code":    stock_code,
        "current_price": close,
        "prev_close":    prev,
        "change":        close - prev,
        "change_rate":   chg,
        "volume":        rng.randint(500_000, 15_000_000),
        "source":        "Mock",
    }


def _mock_daily_prices(stock_code: str, days: int) -> pd.DataFrame:
    rng   = random.Random(int(stock_code) % 9999)
    base  = next((p for c, *_, p in _MOCK_STOCKS if c == stock_code), 50_000)
    today = date.today()
    rows  = []
    price = float(base)

    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        chg    = rng.uniform(-0.04, 0.05)
        close  = max(100, round(price * (1 + chg)))
        open_p = round(price * (1 + rng.uniform(-0.01, 0.01)))
        high   = round(max(open_p, close) * (1 + rng.uniform(0, 0.015)))
        low    = round(min(open_p, close) * (1 - rng.uniform(0, 0.015)))
        volume = rng.randint(500_000, 15_000_000)
        rows.append({
            "date":   str(d),
            "open":   open_p,
            "high":   high,
            "low":    low,
            "close":  close,
            "volume": volume,
            "source": "Mock",
        })
        price = close

    return pd.DataFrame(rows)


def _mock_account_balance() -> dict[str, Any]:
    total_stock = sum(qty * price for _, _, qty, price in _MOCK_HOLDINGS)
    cash        = 3_500_000
    total_asset = cash + total_stock
    pnl         = 280_000
    return {
        "total_asset":   total_asset,
        "cash_balance":  cash,
        "stock_value":   total_stock,
        "pnl":           pnl,
        "pnl_rate":      round(pnl / (total_asset - pnl) * 100, 2),
        "account_no":    _mask_account(KIWOOM_MOCK_ACCOUNT_NO),  # 마스킹 후 반환
        "account_mode":  "mock",
        "source":        "Mock",
    }


def _mock_positions() -> list[dict[str, Any]]:
    rows = []
    for code, name, qty, avg_price in _MOCK_HOLDINGS:
        price_info  = _mock_current_price(code)
        curr_price  = price_info["current_price"]
        pnl         = (curr_price - avg_price) * qty
        pnl_rate    = round((curr_price - avg_price) / avg_price * 100, 2)
        rows.append({
            "stock_code":    code,
            "stock_name":    name,
            "quantity":      qty,
            "avg_price":     avg_price,
            "current_price": curr_price,
            "eval_amount":   curr_price * qty,
            "pnl":           pnl,
            "pnl_rate":      pnl_rate,
            "source":        "Mock",
        })
    return rows


def _mock_orderable_amount(stock_code: str) -> dict[str, Any]:
    price_info = _mock_current_price(stock_code)
    curr_price = price_info["current_price"]
    cash       = 3_500_000
    max_qty    = cash // curr_price
    return {
        "stock_code":       stock_code,
        "current_price":    curr_price,
        "cash_balance":     cash,
        "orderable_amount": cash,
        "max_quantity":     int(max_qty),
        "source":           "Mock",
    }


def _mock_order_history() -> list[dict[str, Any]]:
    today = str(date.today())
    return [
        {
            "order_no":    "M20240001",
            "order_date":  today,
            "stock_code":  "005930",
            "stock_name":  "삼성전자",
            "order_type":  "매수",
            "order_price": 72_000,
            "quantity":    10,
            "status":      "전량체결",
            "source":      "Mock",
        },
    ]


# ════════════════════════════════════════════════════════════════
# 공개 함수 1 — 토큰
# ════════════════════════════════════════════════════════════════

def get_access_token() -> str | None:
    """
    OAuth2 액세스 토큰을 발급·재사용합니다.
    캐시된 토큰이 유효하면 재발급하지 않습니다 (24시간 TTL).

    Returns:
        str | None: 토큰 문자열 또는 Mock/미연결 시 None
    """
    # 캐시 확인
    cached = _TokenCache.get()
    if cached:
        return cached

    if not is_available():
        logger.debug("[Kiwoom] Mock 모드 또는 키 없음 — 토큰 발급 생략")
        return None

    try:
        import requests
        resp = requests.post(
            f"{_base_url()}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey":     KIWOOM_APP_KEY,
                "appsecret":  KIWOOM_SECRET_KEY,  # 전송은 하지만 로그에는 남기지 않음
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        body  = resp.json()
        token = body.get("access_token")
        if not token:
            logger.error("[Kiwoom] 토큰 응답에 access_token 없음")
            return None
        # expires_in 이 없으면 23시간 기본값
        ttl = int(body.get("expires_in", 82_800))
        _TokenCache.set(token, ttl)
        logger.info("[Kiwoom] 액세스 토큰 발급 완료 (TTL=%ds)", ttl)
        return token
    except Exception as e:
        logger.error("[Kiwoom] 토큰 발급 실패: %s", e)
        _TokenCache.clear()
        return None


# ════════════════════════════════════════════════════════════════
# 공개 함수 2 — 종목 목록
# ════════════════════════════════════════════════════════════════

def get_stock_list() -> pd.DataFrame:
    """
    상장 종목 전체 목록을 반환합니다.

    Returns:
        DataFrame — stock_code, stock_name, market, sector, source
    """
    if not is_available():
        logger.debug("[Kiwoom] Mock 종목 목록 반환")
        return pd.DataFrame([
            {"stock_code": c, "stock_name": n, "market": m,
             "sector": s, "source": "Mock"}
            for c, n, m, s, _ in _MOCK_STOCKS
        ])

    try:
        token = get_access_token()
        if not token:
            raise ValueError("토큰 없음")
        import requests
        resp = requests.get(
            f"{_base_url()}/uapi/domestic-stock/v1/quotations/inquire-member-stocklist",
            headers={**_headers("CTPF1002R", token)},
            params={"PDNO": "", "PRDT_TYPE_CD": "300"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get("output", [])
        rows  = [
            {
                "stock_code": x.get("pdno", ""),
                "stock_name": x.get("prdt_abrv_name", ""),
                "market":     x.get("mket_id_cd", ""),
                "sector":     x.get("std_idst_clsf_cd_name", ""),
                "source":     "Kiwoom",
            }
            for x in items
        ]
        logger.info("[Kiwoom] 종목 목록 %d건 조회 완료", len(rows))
        return pd.DataFrame(rows)
    except Exception as e:
        logger.warning("[Kiwoom] get_stock_list 실패: %s → Mock 반환", e)
        return pd.DataFrame([
            {"stock_code": c, "stock_name": n, "market": m,
             "sector": s, "source": "Mock"}
            for c, n, m, s, _ in _MOCK_STOCKS
        ])


# ════════════════════════════════════════════════════════════════
# 공개 함수 3 — 현재가
# ════════════════════════════════════════════════════════════════

def get_current_price(stock_code: str) -> dict[str, Any]:
    """
    종목의 현재가를 반환합니다.

    Args:
        stock_code: 6자리 종목코드

    Returns:
        dict — stock_code, current_price, prev_close, change, change_rate, volume, source
    """
    code = str(stock_code).zfill(6)

    if not is_available():
        return _mock_current_price(code)

    try:
        token = get_access_token()
        if not token:
            raise ValueError("토큰 없음")
        import requests
        resp = requests.get(
            f"{_base_url()}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers={**_headers("FHKST01010100", token)},
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        out = resp.json().get("output", {})
        return {
            "stock_code":    code,
            "current_price": _safe_int(out.get("stck_prpr")),
            "prev_close":    _safe_int(out.get("stck_sdpr")),
            "change":        _safe_int(out.get("prdy_vrss")),
            "change_rate":   _safe_float(out.get("prdy_ctrt")),
            "volume":        _safe_int(out.get("acml_vol")),
            "source":        "Kiwoom",
        }
    except Exception as e:
        logger.warning("[Kiwoom] get_current_price(%s) 실패: %s → Mock 반환", code, e)
        return _mock_current_price(code)


# ════════════════════════════════════════════════════════════════
# 공개 함수 4 — 일봉
# ════════════════════════════════════════════════════════════════

def get_daily_prices(stock_code: str, days: int = 120) -> pd.DataFrame:
    """
    종목의 최근 N 거래일 일봉 데이터를 반환합니다.

    Args:
        stock_code: 6자리 종목코드
        days:       조회 일수 (기본 120)

    Returns:
        DataFrame — date, open, high, low, close, volume, source
    """
    code = str(stock_code).zfill(6)

    if not is_available():
        return _mock_daily_prices(code, days)

    try:
        token = get_access_token()
        if not token:
            raise ValueError("토큰 없음")
        import requests
        end_dt   = date.today().strftime("%Y%m%d")
        start_dt = (date.today() - timedelta(days=days * 2)).strftime("%Y%m%d")
        resp = requests.get(
            f"{_base_url()}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            headers={**_headers("FHKST01010400", token)},
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD":         code,
                "FID_INPUT_DATE_1":       start_dt,
                "FID_INPUT_DATE_2":       end_dt,
                "FID_PERIOD_DIV_CODE":    "D",
                "FID_ORG_ADJ_PRC":        "0",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        output = resp.json().get("output2", [])
        rows   = [
            {
                "date":   x.get("stck_bsop_date", ""),
                "open":   _safe_int(x.get("stck_oprc")),
                "high":   _safe_int(x.get("stck_hgpr")),
                "low":    _safe_int(x.get("stck_lwpr")),
                "close":  _safe_int(x.get("stck_clpr")),
                "volume": _safe_int(x.get("acml_vol")),
                "source": "Kiwoom",
            }
            for x in output
        ]
        df = pd.DataFrame(rows)
        logger.info("[Kiwoom] 일봉 %s %d행 조회 완료", code, len(df))
        return df.tail(days)
    except Exception as e:
        logger.warning("[Kiwoom] get_daily_prices(%s) 실패: %s → Mock 반환", code, e)
        return _mock_daily_prices(code, days)


# ════════════════════════════════════════════════════════════════
# 공개 함수 5 — 계좌 잔고
# ════════════════════════════════════════════════════════════════

def get_account_balance() -> dict[str, Any]:
    """
    모의투자 계좌 잔고 요약을 반환합니다.

    보안: 계좌번호는 마스킹 처리 후 반환합니다.

    Returns:
        dict — total_asset, cash_balance, stock_value,
                pnl, pnl_rate, account_no(마스킹), account_mode, source
    """
    if not is_available():
        logger.debug("[Kiwoom] Mock 계좌 잔고 반환")
        return _mock_account_balance()

    account_no = KIWOOM_MOCK_ACCOUNT_NO
    if not account_no:
        logger.warning("[Kiwoom] KIWOOM_MOCK_ACCOUNT_NO 미설정 → Mock 반환")
        return _mock_account_balance()

    try:
        token = get_access_token()
        if not token:
            raise ValueError("토큰 없음")
        import requests
        resp = requests.get(
            f"{_base_url()}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers={**_headers("VTTC8434R", token)},
            params={
                "CANO":           account_no[:8],   # 로그에는 남기지 않음
                "ACNT_PRDT_CD":   "01",
                "AFHR_FLPR_YN":   "N",
                "OFL_YN":         "N",
                "INQR_DVSN":      "02",
                "UNPR_DVSN":      "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN":      "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        body  = resp.json()
        out2  = (body.get("output2") or [{}])[0]

        # 잔고 원문은 로그에 남기지 않음 (민감정보)
        result = {
            "total_asset":   _safe_int(out2.get("tot_evlu_amt")),
            "cash_balance":  _safe_int(out2.get("dnca_tot_amt")),
            "stock_value":   _safe_int(out2.get("scts_evlu_amt")),
            "pnl":           _safe_int(out2.get("evlu_pfls_smtl_amt")),
            "pnl_rate":      _safe_float(out2.get("asst_icdc_erng_rt")),
            "account_no":    _mask_account(account_no),   # 마스킹
            "account_mode":  KIWOOM_INVEST_MODE,
            "source":        "Kiwoom",
        }
        logger.info(
            "[Kiwoom] 잔고 조회 완료 — 계좌: %s, 총자산: %d원",
            _mask_account(account_no),
            result["total_asset"],
        )
        return result
    except Exception as e:
        logger.warning("[Kiwoom] get_account_balance 실패: %s → Mock 반환", e)
        return _mock_account_balance()


# ════════════════════════════════════════════════════════════════
# 공개 함수 6 — 보유 종목
# ════════════════════════════════════════════════════════════════

def get_positions() -> list[dict[str, Any]]:
    """
    모의투자 계좌의 보유 종목 목록을 반환합니다.

    Returns:
        list[dict] — stock_code, stock_name, quantity, avg_price,
                     current_price, eval_amount, pnl, pnl_rate, source
    """
    if not is_available():
        logger.debug("[Kiwoom] Mock 보유 종목 반환")
        return _mock_positions()

    account_no = KIWOOM_MOCK_ACCOUNT_NO
    if not account_no:
        logger.warning("[Kiwoom] KIWOOM_MOCK_ACCOUNT_NO 미설정 → Mock 반환")
        return _mock_positions()

    try:
        token = get_access_token()
        if not token:
            raise ValueError("토큰 없음")
        import requests
        resp = requests.get(
            f"{_base_url()}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers={**_headers("VTTC8434R", token)},
            params={
                "CANO":           account_no[:8],
                "ACNT_PRDT_CD":   "01",
                "AFHR_FLPR_YN":   "N",
                "OFL_YN":         "N",
                "INQR_DVSN":      "02",
                "UNPR_DVSN":      "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN":      "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        output1 = resp.json().get("output1", [])
        rows = [
            {
                "stock_code":    x.get("pdno", ""),
                "stock_name":    x.get("prdt_name", ""),
                "quantity":      _safe_int(x.get("hldg_qty")),
                "avg_price":     _safe_int(x.get("pchs_avg_pric")),
                "current_price": _safe_int(x.get("prpr")),
                "eval_amount":   _safe_int(x.get("evlu_amt")),
                "pnl":           _safe_int(x.get("evlu_pfls_amt")),
                "pnl_rate":      _safe_float(x.get("evlu_pfls_rt")),
                "source":        "Kiwoom",
            }
            for x in output1
            if _safe_int(x.get("hldg_qty")) > 0
        ]
        logger.info(
            "[Kiwoom] 보유 종목 %d건 조회 완료 — 계좌: %s",
            len(rows), _mask_account(account_no),
        )
        return rows
    except Exception as e:
        logger.warning("[Kiwoom] get_positions 실패: %s → Mock 반환", e)
        return _mock_positions()


# ════════════════════════════════════════════════════════════════
# 공개 함수 7 — 주문 가능 금액
# ════════════════════════════════════════════════════════════════

def get_orderable_amount(stock_code: str) -> dict[str, Any]:
    """
    특정 종목에 대한 주문 가능 금액·수량을 반환합니다.
    (조회 전용 — 실제 주문 생성하지 않음)

    Args:
        stock_code: 6자리 종목코드

    Returns:
        dict — stock_code, current_price, cash_balance,
                orderable_amount, max_quantity, source
    """
    code = str(stock_code).zfill(6)

    if not is_available():
        return _mock_orderable_amount(code)

    account_no = KIWOOM_MOCK_ACCOUNT_NO
    if not account_no:
        logger.warning("[Kiwoom] KIWOOM_MOCK_ACCOUNT_NO 미설정 → Mock 반환")
        return _mock_orderable_amount(code)

    try:
        token = get_access_token()
        if not token:
            raise ValueError("토큰 없음")
        import requests

        # 현재가 먼저 조회
        price_info = get_current_price(code)
        curr_price = price_info.get("current_price", 0)
        if curr_price <= 0:
            raise ValueError(f"현재가 조회 실패: {code}")

        resp = requests.get(
            f"{_base_url()}/uapi/domestic-stock/v1/trading/inquire-psbl-order",
            headers={**_headers("VTTC8908R", token)},
            params={
                "CANO":         account_no[:8],
                "ACNT_PRDT_CD": "01",
                "PDNO":         code,
                "ORD_UNPR":     str(curr_price),
                "ORD_DVSN":     "01",   # 지정가
                "CMA_EVLU_AMT_ICLD_YN": "N",
                "OVRS_ICLD_YN": "N",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        out = resp.json().get("output", {})
        orderable = _safe_int(out.get("ord_psbl_cash"))
        max_qty   = _safe_int(out.get("max_buy_qty"))
        result = {
            "stock_code":       code,
            "current_price":    curr_price,
            "cash_balance":     _safe_int(out.get("nrcvb_buy_amt")),
            "orderable_amount": orderable,
            "max_quantity":     max_qty,
            "source":           "Kiwoom",
        }
        logger.info(
            "[Kiwoom] 주문가능금액 조회 — %s: %d원 (최대 %d주)",
            code, orderable, max_qty,
        )
        return result
    except Exception as e:
        logger.warning("[Kiwoom] get_orderable_amount(%s) 실패: %s → Mock 반환", code, e)
        return _mock_orderable_amount(code)


# ════════════════════════════════════════════════════════════════
# 공개 함수 8 — 당일 주문 내역 (조회 전용)
# ════════════════════════════════════════════════════════════════

def get_order_history() -> list[dict[str, Any]]:
    """
    당일 모의투자 주문 내역을 반환합니다. (조회 전용)

    보안: 계좌번호는 마스킹 처리 후 반환합니다.

    Returns:
        list[dict] — order_no, order_date, stock_code, stock_name,
                     order_type, order_price, quantity, status, source
    """
    if not is_available():
        logger.debug("[Kiwoom] Mock 주문 내역 반환")
        return _mock_order_history()

    account_no = KIWOOM_MOCK_ACCOUNT_NO
    if not account_no:
        logger.warning("[Kiwoom] KIWOOM_MOCK_ACCOUNT_NO 미설정 → Mock 반환")
        return _mock_order_history()

    try:
        token = get_access_token()
        if not token:
            raise ValueError("토큰 없음")
        import requests

        today = date.today().strftime("%Y%m%d")
        resp  = requests.get(
            f"{_base_url()}/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
            headers={**_headers("VTTC8001R", token)},
            params={
                "CANO":           account_no[:8],
                "ACNT_PRDT_CD":   "01",
                "INQR_STRT_DT":   today,
                "INQR_END_DT":    today,
                "SLL_BUY_DVSN_CD": "00",   # 전체
                "INQR_DVSN":      "00",
                "PDNO":           "",
                "ORD_GNO_BRNO":   "",
                "ODNO":           "",
                "INQR_DVSN_3":    "00",
                "INQR_DVSN_1":    "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        output1 = resp.json().get("output1", [])

        _STATUS_MAP = {
            "02": "전량체결",
            "01": "일부체결",
            "00": "미체결",
            "03": "취소",
        }
        rows = [
            {
                "order_no":    x.get("odno", ""),
                "order_date":  x.get("ord_dt", today),
                "stock_code":  x.get("pdno", ""),
                "stock_name":  x.get("prdt_name", ""),
                "order_type":  "매수" if x.get("sll_buy_dvsn_cd") == "02" else "매도",
                "order_price": _safe_int(x.get("ord_unpr")),
                "quantity":    _safe_int(x.get("ord_qty")),
                "status":      _STATUS_MAP.get(x.get("ord_tmd", ""), x.get("ord_tmd", "")),
                "source":      "Kiwoom",
            }
            for x in output1
        ]
        logger.info(
            "[Kiwoom] 당일 주문 내역 %d건 조회 — 계좌: %s",
            len(rows), _mask_account(account_no),
        )
        return rows
    except Exception as e:
        logger.warning("[Kiwoom] get_order_history 실패: %s → Mock 반환", e)
        return _mock_order_history()


# ════════════════════════════════════════════════════════════════
# 비활성화 — 주문 함수 (절대 구현·호출 금지)
# ════════════════════════════════════════════════════════════════

def _DISABLED_place_buy_order(*args: Any, **kwargs: Any) -> None:
    """매수 주문 — 이 파일에서 영구 비활성화. services/kiwoom_order_bridge.py 사용."""
    raise NotImplementedError(
        "매수 주문은 kiwoom_data.py 에서 지원하지 않습니다. "
        "services/kiwoom_order_bridge.py 를 사용하세요."
    )


def _DISABLED_place_sell_order(*args: Any, **kwargs: Any) -> None:
    """매도 주문 — 이 파일에서 영구 비활성화."""
    raise NotImplementedError(
        "매도 주문은 kiwoom_data.py 에서 지원하지 않습니다. "
        "services/kiwoom_order_bridge.py 를 사용하세요."
    )
