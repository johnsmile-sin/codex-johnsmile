"""
services/virtual_position.py  –  가상 보유 종목 서비스 (3차 모의투자)

virtual_positions 테이블과 연결합니다.
Supabase 연결 시 DB 저장, 미연결 시 data/virtual_positions.json 파일로 폴백합니다.

status 값:
    보유   – 현재 보유 중
    청산   – 수동 청산
    손절   – 손절가 도달 청산
    익절   – 목표가 도달 청산

공개 함수:
    get_positions()             보유 포지션 조회
    add_position()              포지션 추가 (이미 있으면 수량/평균단가 병합)
    update_position_price()     현재가 업데이트 → 평가금액·손익·수익률 재계산
    close_position()            포지션 청산 (청산·손절·익절)
    calculate_position_return() 수익률 계산 (순수 계산, DB 미사용)
    update_holding_days()       전체 보유 포지션 보유일수 갱신
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
POSITIONS_FILE = DATA_DIR / "virtual_positions.json"

STATUS_OPEN    = "보유"
STATUS_CLOSED  = "청산"
STATUS_STOP    = "손절"
STATUS_PROFIT  = "익절"
OPEN_STATUSES  = {STATUS_OPEN}

_mock_positions: list[dict[str, Any]] | None = None


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼
# ════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return str(date.today())


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


def _get_portfolio_id() -> int | None:
    """Supabase 포트폴리오 ID를 반환한다. 미연결 시 None."""
    try:
        from services.virtual_portfolio import get_portfolio
        portfolio = get_portfolio()
        return portfolio.get("id")
    except Exception:
        return None


def _next_local_id(positions: list[dict]) -> int:
    ids = [int(p.get("id", 0)) for p in positions if str(p.get("id", "")).isdigit()]
    return max(ids, default=0) + 1


# ── 로컬 JSON 저장/로드 ───────────────────────────────────────────

def _load_local() -> list[dict[str, Any]]:
    global _mock_positions
    if _mock_positions is not None:
        return _mock_positions
    if POSITIONS_FILE.exists():
        try:
            _mock_positions = json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
            return _mock_positions
        except Exception:
            pass
    _mock_positions = []
    return _mock_positions


def _save_local(positions: list[dict[str, Any]]) -> None:
    global _mock_positions
    _mock_positions = positions
    _ensure_data_dir()
    POSITIONS_FILE.write_text(
        json.dumps(positions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── 수익률 계산 (공통) ────────────────────────────────────────────

def _calc_metrics(entry_price: float, current_price: float, quantity: int) -> dict[str, float]:
    """평가금액·손익·수익률을 계산해 dict로 반환한다."""
    cost            = round(entry_price * quantity, 2)
    evaluation      = round(current_price * quantity, 2)
    profit_loss     = round(evaluation - cost, 2)
    return_rate     = round(profit_loss / cost * 100, 4) if cost else 0.0
    return {
        "evaluation_amount": evaluation,
        "profit_loss":       profit_loss,
        "return_rate":       return_rate,
    }


# ════════════════════════════════════════════════════════════════
# 공개 함수
# ════════════════════════════════════════════════════════════════

def get_positions(
    strategy_name: str | None = None,
    status: str | None = STATUS_OPEN,
    stock_code: str | None = None,
) -> list[dict[str, Any]]:
    """
    보유 포지션을 조회한다.

    Args:
        strategy_name: 전략명 필터 (None = 전체)
        status:        상태 필터 (기본값: '보유', None = 전체)
        stock_code:    종목코드 필터 (None = 전체)

    Returns:
        list[dict]: 포지션 목록 (최신 entry_date 순)
    """
    if _supabase_connected():
        try:
            query = _supabase_client().table("virtual_positions").select("*")
            if status:
                query = query.eq("status", status)
            if strategy_name:
                query = query.eq("strategy_name", strategy_name)
            if stock_code:
                query = query.eq("stock_code", str(stock_code).zfill(6))
            rows = query.order("entry_date", desc=True).execute().data or []
            return rows
        except Exception:
            pass

    positions = _load_local()
    if status:
        positions = [p for p in positions if p.get("status") == status]
    if strategy_name:
        positions = [p for p in positions if p.get("strategy_name") == strategy_name]
    if stock_code:
        code = str(stock_code).zfill(6)
        positions = [p for p in positions if str(p.get("stock_code", "")).zfill(6) == code]
    return sorted(positions, key=lambda x: x.get("entry_date", ""), reverse=True)


def add_position(
    stock_code: str,
    stock_name: str,
    entry_price: float,
    quantity: int,
    strategy_name: str = "v3_score_momentum",
    stop_loss_price: float | None = None,
    target_price: float | None = None,
) -> dict[str, Any]:
    """
    포지션을 추가한다.
    동일 전략+종목의 보유 포지션이 이미 있으면 수량·평균단가를 병합한다.

    Args:
        stock_code:      종목코드 (6자리)
        stock_name:      종목명
        entry_price:     진입 단가 (원)
        quantity:        수량 (주)
        strategy_name:   전략명
        stop_loss_price: 손절가 (원, 선택)
        target_price:    목표가 (원, 선택)

    Returns:
        dict: 생성 또는 병합된 포지션 레코드
    """
    code = str(stock_code).zfill(6)
    metrics = _calc_metrics(entry_price, entry_price, quantity)

    existing = get_positions(strategy_name=strategy_name, status=STATUS_OPEN, stock_code=code)

    if existing:
        # 기존 포지션 병합 (가중평균 단가)
        pos = existing[0]
        old_qty   = int(pos.get("quantity", 0))
        old_price = float(pos.get("entry_price", entry_price))
        new_qty   = old_qty + quantity
        avg_price = round((old_price * old_qty + entry_price * quantity) / new_qty, 2)
        merged_metrics = _calc_metrics(avg_price, avg_price, new_qty)

        updates = {
            "quantity":          new_qty,
            "entry_price":       avg_price,
            "current_price":     avg_price,
            "evaluation_amount": merged_metrics["evaluation_amount"],
            "profit_loss":       0.0,
            "return_rate":       0.0,
            "updated_at":        _now(),
        }
        if stop_loss_price is not None:
            updates["stop_loss_price"] = stop_loss_price
        if target_price is not None:
            updates["target_price"] = target_price

        if _supabase_connected():
            try:
                result = (
                    _supabase_client()
                    .table("virtual_positions")
                    .update(updates)
                    .eq("id", pos["id"])
                    .execute()
                )
                rows = result.data or []
                if rows:
                    return rows[0]
            except Exception:
                pass

        positions = _load_local()
        for p in positions:
            if str(p.get("id")) == str(pos.get("id")):
                p.update(updates)
                _save_local(positions)
                return p
        return pos

    # 신규 포지션 생성
    record: dict[str, Any] = {
        "stock_code":        code,
        "stock_name":        stock_name,
        "strategy_name":     strategy_name,
        "entry_date":        _today(),
        "entry_price":       round(entry_price, 2),
        "quantity":          quantity,
        "current_price":     round(entry_price, 2),
        "evaluation_amount": metrics["evaluation_amount"],
        "profit_loss":       0.0,
        "return_rate":       0.0,
        "stop_loss_price":   round(stop_loss_price, 2) if stop_loss_price else None,
        "target_price":      round(target_price, 2) if target_price else None,
        "holding_days":      0,
        "status":            STATUS_OPEN,
        "created_at":        _now(),
        "updated_at":        _now(),
    }

    if _supabase_connected():
        try:
            portfolio_id = _get_portfolio_id()
            if portfolio_id:
                record["portfolio_id"] = portfolio_id
            result = _supabase_client().table("virtual_positions").insert(record).execute()
            rows = result.data or []
            if rows:
                return rows[0]
        except Exception:
            pass

    positions = _load_local()
    record["id"] = _next_local_id(positions)
    positions.append(record)
    _save_local(positions)
    return record


def update_position_price(
    position_id: int | str,
    current_price: float,
) -> dict[str, Any] | None:
    """
    현재가를 업데이트하고 평가금액·손익·수익률을 재계산한다.

    Args:
        position_id:   포지션 ID
        current_price: 현재가 (원)

    Returns:
        dict: 업데이트된 포지션 레코드, 없으면 None
    """
    if current_price < 0:
        return None

    # 현재 포지션 조회
    target = None
    if _supabase_connected():
        try:
            rows = (
                _supabase_client()
                .table("virtual_positions")
                .select("*")
                .eq("id", position_id)
                .execute()
                .data or []
            )
            if rows:
                target = rows[0]
        except Exception:
            pass

    if target is None:
        all_pos = _load_local()
        target = next((p for p in all_pos if str(p.get("id")) == str(position_id)), None)

    if target is None:
        return None

    entry_price = float(target.get("entry_price", current_price))
    quantity    = int(target.get("quantity", 0))
    metrics     = _calc_metrics(entry_price, current_price, quantity)

    updates = {
        "current_price":     round(current_price, 2),
        "evaluation_amount": metrics["evaluation_amount"],
        "profit_loss":       metrics["profit_loss"],
        "return_rate":       metrics["return_rate"],
        "updated_at":        _now(),
    }

    if _supabase_connected():
        try:
            result = (
                _supabase_client()
                .table("virtual_positions")
                .update(updates)
                .eq("id", position_id)
                .execute()
            )
            rows = result.data or []
            if rows:
                return rows[0]
        except Exception:
            pass

    positions = _load_local()
    for p in positions:
        if str(p.get("id")) == str(position_id):
            p.update(updates)
            _save_local(positions)
            return p
    return None


def close_position(
    position_id: int | str,
    close_price: float | None = None,
    close_reason: str = "청산",
) -> dict[str, Any] | None:
    """
    포지션을 청산한다.

    Args:
        position_id:  청산할 포지션 ID
        close_price:  청산 가격 (None이면 현재가 유지)
        close_reason: '청산' | '손절' | '익절' (기본값: '청산')

    Returns:
        dict: 청산된 포지션 레코드, 없으면 None
    """
    valid_reasons = {STATUS_CLOSED, STATUS_STOP, STATUS_PROFIT}
    status = close_reason if close_reason in valid_reasons else STATUS_CLOSED

    updates: dict[str, Any] = {
        "status":     status,
        "updated_at": _now(),
    }

    if close_price is not None and close_price > 0:
        target = None
        if _supabase_connected():
            try:
                rows = (
                    _supabase_client()
                    .table("virtual_positions")
                    .select("entry_price,quantity")
                    .eq("id", position_id)
                    .execute()
                    .data or []
                )
                if rows:
                    target = rows[0]
            except Exception:
                pass

        if target is None:
            all_pos = _load_local()
            target = next((p for p in all_pos if str(p.get("id")) == str(position_id)), None)

        if target:
            entry_price = float(target.get("entry_price", close_price))
            quantity    = int(target.get("quantity", 0))
            metrics     = _calc_metrics(entry_price, close_price, quantity)
            updates.update({
                "current_price":     round(close_price, 2),
                "evaluation_amount": metrics["evaluation_amount"],
                "profit_loss":       metrics["profit_loss"],
                "return_rate":       metrics["return_rate"],
            })

    if _supabase_connected():
        try:
            result = (
                _supabase_client()
                .table("virtual_positions")
                .update(updates)
                .eq("id", position_id)
                .execute()
            )
            rows = result.data or []
            if rows:
                return rows[0]
        except Exception:
            pass

    positions = _load_local()
    for p in positions:
        if str(p.get("id")) == str(position_id):
            p.update(updates)
            _save_local(positions)
            return p
    return None


def calculate_position_return(
    entry_price: float,
    current_price: float,
    quantity: int,
) -> dict[str, float]:
    """
    수익률을 계산한다 (DB 조회 없는 순수 계산 함수).

    Args:
        entry_price:   매수 평균 단가 (원)
        current_price: 현재가 (원)
        quantity:      보유 수량 (주)

    Returns:
        dict:
            cost             매수 금액 합계
            evaluation_amount 현재 평가금액
            profit_loss      평가 손익
            return_rate      수익률 (%)
    """
    cost = round(entry_price * quantity, 2)
    metrics = _calc_metrics(entry_price, current_price, quantity)
    return {"cost": cost, **metrics}


def update_holding_days() -> int:
    """
    status='보유' 인 모든 포지션의 보유일수(holding_days)를 오늘 기준으로 갱신한다.

    Returns:
        int: 갱신된 포지션 수
    """
    today = date.today()
    open_positions = get_positions(status=STATUS_OPEN)
    updated_count = 0

    for pos in open_positions:
        entry_date_str = pos.get("entry_date", str(today))
        try:
            entry_date = date.fromisoformat(str(entry_date_str)[:10])
        except ValueError:
            entry_date = today

        holding_days = (today - entry_date).days
        updates = {
            "holding_days": holding_days,
            "updated_at":   _now(),
        }

        success = False
        if _supabase_connected():
            try:
                result = (
                    _supabase_client()
                    .table("virtual_positions")
                    .update(updates)
                    .eq("id", pos["id"])
                    .execute()
                )
                if result.data:
                    success = True
                    updated_count += 1
            except Exception:
                pass

        if not success:
            positions = _load_local()
            for p in positions:
                if str(p.get("id")) == str(pos.get("id")):
                    p.update(updates)
                    updated_count += 1
                    break
            _save_local(positions)

    return updated_count
