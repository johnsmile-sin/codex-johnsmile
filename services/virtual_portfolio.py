"""
services/virtual_portfolio.py  –  가상 포트폴리오 서비스 (3차 모의투자)

실거래 계좌와 연결하지 않습니다.
Supabase 연결 시 virtual_portfolio 테이블 사용,
미연결 시 data/virtual_portfolio.json 파일로 폴백합니다.

공개 함수:
    create_default_portfolio()         기본 포트폴리오 생성 (없으면 생성, 있으면 반환)
    get_portfolio()                    현재 포트폴리오 조회
    update_portfolio_value(cash, market_value, realized_pnl)
                                       총자산·손익·수익률 재계산 및 저장
    get_cash_balance()                 현금 잔고 반환
    reset_portfolio()                  초기 상태(1000만원)로 리셋
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

PORTFOLIO_NAME = "기본 모의투자"
INITIAL_CASH = 10_000_000
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PORTFOLIO_FILE = DATA_DIR / "virtual_portfolio.json"

_mock_portfolio: dict[str, Any] | None = None


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼
# ════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _supabase_connected() -> bool:
    try:
        from services.supabase_client import is_connected
        return bool(is_connected())
    except Exception:
        return False


def _supabase_client():
    from services.supabase_client import get_client
    return get_client()


def _default_record() -> dict[str, Any]:
    now = _now()
    return {
        "portfolio_name":    PORTFOLIO_NAME,
        "initial_cash":      float(INITIAL_CASH),
        "cash_balance":      float(INITIAL_CASH),
        "total_asset":       float(INITIAL_CASH),
        "total_profit_loss": 0.0,
        "total_return_rate": 0.0,
        "created_at":        now,
        "updated_at":        now,
    }


# ── Mock 저장/로드 ────────────────────────────────────────────────

def _load_mock() -> dict[str, Any] | None:
    global _mock_portfolio
    if _mock_portfolio is not None:
        return _mock_portfolio
    if PORTFOLIO_FILE.exists():
        try:
            _mock_portfolio = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
            return _mock_portfolio
        except Exception:
            pass
    return None


def _save_mock(record: dict[str, Any]) -> dict[str, Any]:
    global _mock_portfolio
    record["updated_at"] = _now()
    _mock_portfolio = record
    _ensure_data_dir()
    PORTFOLIO_FILE.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return record


# ════════════════════════════════════════════════════════════════
# 공개 함수
# ════════════════════════════════════════════════════════════════

def create_default_portfolio() -> dict[str, Any]:
    """
    기본 포트폴리오가 없으면 생성하고, 있으면 기존 레코드를 반환한다.

    Returns:
        dict: 포트폴리오 레코드
    """
    if _supabase_connected():
        try:
            client = _supabase_client()
            rows = (
                client.table("virtual_portfolio")
                .select("*")
                .eq("portfolio_name", PORTFOLIO_NAME)
                .limit(1)
                .execute()
                .data or []
            )
            if rows:
                return rows[0]
            result = client.table("virtual_portfolio").insert(_default_record()).execute()
            return (result.data or [_default_record()])[0]
        except Exception:
            pass

    existing = _load_mock()
    if existing:
        return existing
    return _save_mock(_default_record())


def get_portfolio() -> dict[str, Any]:
    """
    현재 포트폴리오를 조회한다. 없으면 기본 포트폴리오를 생성한다.

    Returns:
        dict: 포트폴리오 레코드
            - portfolio_name, initial_cash, cash_balance
            - total_asset, total_profit_loss, total_return_rate
    """
    if _supabase_connected():
        try:
            rows = (
                _supabase_client()
                .table("virtual_portfolio")
                .select("*")
                .eq("portfolio_name", PORTFOLIO_NAME)
                .order("id", desc=False)
                .limit(1)
                .execute()
                .data or []
            )
            if rows:
                return rows[0]
        except Exception:
            pass

    existing = _load_mock()
    if existing:
        return existing
    return create_default_portfolio()


def update_portfolio_value(
    cash: float,
    market_value: float,
    realized_pnl: float = 0.0,
) -> dict[str, Any]:
    """
    포트폴리오 총자산·손익·수익률을 재계산하고 저장한다.

    Args:
        cash:          현재 현금 잔고
        market_value:  보유 포지션 평가금액 합계
        realized_pnl:  실현 손익 합계 (현재는 참고값으로 기록)

    Returns:
        dict: 업데이트된 포트폴리오 레코드
    """
    portfolio = get_portfolio()
    initial_cash = float(portfolio.get("initial_cash", INITIAL_CASH))

    total_asset       = round(cash + market_value, 2)
    total_profit_loss = round(total_asset - initial_cash, 2)
    total_return_rate = round(
        total_profit_loss / initial_cash * 100 if initial_cash else 0.0, 4
    )

    updates = {
        "cash_balance":      round(cash, 2),
        "total_asset":       total_asset,
        "total_profit_loss": total_profit_loss,
        "total_return_rate": total_return_rate,
        "updated_at":        _now(),
    }

    if _supabase_connected():
        try:
            portfolio_id = portfolio.get("id")
            if portfolio_id:
                result = (
                    _supabase_client()
                    .table("virtual_portfolio")
                    .update(updates)
                    .eq("id", portfolio_id)
                    .execute()
                )
                rows = result.data or []
                if rows:
                    return rows[0]
        except Exception:
            pass

    return _save_mock({**portfolio, **updates})


def get_cash_balance() -> float:
    """
    현금 잔고를 반환한다.

    Returns:
        float: 현금 잔고 (원)
    """
    return float(get_portfolio().get("cash_balance", INITIAL_CASH))


def reset_portfolio() -> dict[str, Any]:
    """
    포트폴리오를 초기 상태(현금 1000만원)로 리셋한다.

    Returns:
        dict: 리셋된 포트폴리오 레코드
    """
    global _mock_portfolio

    resets = {
        "cash_balance":      float(INITIAL_CASH),
        "total_asset":       float(INITIAL_CASH),
        "total_profit_loss": 0.0,
        "total_return_rate": 0.0,
        "updated_at":        _now(),
    }

    if _supabase_connected():
        try:
            portfolio = get_portfolio()
            portfolio_id = portfolio.get("id")
            if portfolio_id:
                result = (
                    _supabase_client()
                    .table("virtual_portfolio")
                    .update(resets)
                    .eq("id", portfolio_id)
                    .execute()
                )
                rows = result.data or []
                if rows:
                    # Mock 캐시도 초기화
                    _mock_portfolio = None
                    return rows[0]
        except Exception:
            pass

    _mock_portfolio = None
    if PORTFOLIO_FILE.exists():
        PORTFOLIO_FILE.unlink()
    return _save_mock(_default_record())
