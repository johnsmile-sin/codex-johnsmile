"""
services/virtual_order.py  –  가상 주문 서비스 (3차 모의투자)

실거래 주문 API를 절대 호출하지 않습니다.
모든 주문은 virtual_orders 테이블(또는 data/virtual_orders.json)에만 저장됩니다.

체결 기준: 주문 즉시 체결 (order_price 기준 단순 즉시 체결)

공개 함수:
    place_virtual_buy_order()    가상 매수 주문 (현금 부족 시 실패)
    place_virtual_sell_order()   가상 매도 주문 (수량 부족 시 실패)
    cancel_virtual_order()       미체결 주문 취소
    get_virtual_orders()         주문 내역 조회
    execute_virtual_order()      주문 즉시 체결 처리
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from services.virtual_trading import (
    DEFAULT_STRATEGY,
    INITIAL_CASH,
    ORDERS_FILE,
    build_positions,
    list_virtual_orders,
    save_virtual_order,
)
from services.virtual_portfolio import get_portfolio, update_portfolio_value


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼
# ════════════════════════════════════════════════════════════════

def _supabase_connected() -> bool:
    try:
        from services.supabase_client import is_connected
        return bool(is_connected())
    except Exception:
        return False


def _supabase_client():
    from services.supabase_client import get_client
    return get_client()


def _result(success: bool, message: str, order: dict | None = None, **extra) -> dict[str, Any]:
    return {"success": success, "message": message, "order": order, **extra}


def _is_accounted_order(order: dict[str, Any]) -> bool:
    status = str(order.get("status") or "CLOSED").upper()
    return status == "CLOSED"


def _compute_cash() -> float:
    """전체 주문 내역을 순서대로 적용해 현재 현금 잔고를 계산한다."""
    orders = list_virtual_orders()
    cash = float(INITIAL_CASH)
    for order in sorted(orders, key=lambda x: (x.get("order_date", ""), int(x.get("id", 0)))):
        if not _is_accounted_order(order):
            continue
        amount = float(order.get("amount", 0) or 0)
        side = str(order.get("side", "")).upper()
        if side == "BUY":
            cash -= amount
        elif side == "SELL":
            cash += amount
    return cash


def _get_holding_quantity(stock_code: str, strategy_name: str) -> int:
    """해당 전략+종목의 현재 보유 수량을 반환한다."""
    orders = list_virtual_orders()
    accounted_orders = [order for order in orders if _is_accounted_order(order)]
    positions = build_positions(accounted_orders)
    if positions.empty:
        return 0
    code = str(stock_code).zfill(6)
    matched = positions[
        (positions["stock_code"] == code) &
        (positions["strategy_name"] == strategy_name)
    ]
    if matched.empty:
        return 0
    return int(matched.iloc[0]["quantity"])


def _update_order_status_supabase(order_id: int | str, status: str) -> dict | None:
    """Supabase에서 주문 상태를 업데이트한다."""
    try:
        result = (
            _supabase_client()
            .table("virtual_orders")
            .update({"status": status})
            .eq("id", order_id)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None
    except Exception:
        return None


def _update_order_status_local(order_id: int | str, status: str) -> dict | None:
    """로컬 JSON에서 주문 상태를 업데이트한다."""
    if not ORDERS_FILE.exists():
        return None
    try:
        orders: list[dict] = json.loads(ORDERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    target = None
    for order in orders:
        if str(order.get("id")) == str(order_id):
            order["status"] = status
            target = order
            break

    if target is None:
        return None

    ORDERS_FILE.write_text(
        json.dumps(orders, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def _sync_portfolio() -> None:
    """
    전체 주문 내역을 기반으로 포트폴리오 현금·총자산·손익을 동기화한다.
    가상 포트폴리오 테이블에만 반영하며 실계좌와 무관합니다.
    """
    orders = list_virtual_orders()
    accounted_orders = [order for order in orders if _is_accounted_order(order)]
    positions = build_positions(accounted_orders)

    cash = float(INITIAL_CASH)
    realized_pnl = 0.0
    cost_basis: dict[tuple[str, str], dict[str, Any]] = {}

    for order in sorted(accounted_orders, key=lambda x: (x.get("order_date", ""), int(x.get("id", 0)))):
        code = str(order.get("stock_code", "")).zfill(6)
        strat = str(order.get("strategy_name") or DEFAULT_STRATEGY)
        key = (strat, code)
        side = str(order.get("side", "")).upper()
        qty = int(order.get("quantity", 0) or 0)
        price = float(order.get("price", 0) or 0)
        amount = qty * price
        if qty <= 0 or price <= 0:
            continue

        if side == "BUY":
            cash -= amount
            pos = cost_basis.setdefault(key, {"quantity": 0, "cost_amount": 0.0})
            pos["cost_amount"] += amount
            pos["quantity"] += qty
        elif side == "SELL":
            cash += amount
            pos = cost_basis.get(key, {"quantity": 0, "cost_amount": 0.0})
            if pos["quantity"] > 0:
                avg_cost = pos["cost_amount"] / pos["quantity"]
                sell_qty = min(qty, pos["quantity"])
                realized_pnl += (price - avg_cost) * sell_qty
                pos["cost_amount"] -= avg_cost * sell_qty
                pos["quantity"] -= sell_qty

    if not positions.empty:
        positions["current_price"] = positions["avg_price"]
        market_value = float((positions["quantity"] * positions["avg_price"]).sum())
    else:
        market_value = 0.0

    update_portfolio_value(cash=cash, market_value=market_value, realized_pnl=realized_pnl)


# ════════════════════════════════════════════════════════════════
# 공개 함수
# ════════════════════════════════════════════════════════════════

def place_virtual_buy_order(
    stock_code: str,
    stock_name: str,
    quantity: int,
    price: float,
    strategy_name: str = DEFAULT_STRATEGY,
    reason: str = "",
    score: int = 0,
    decision: str = "",
) -> dict[str, Any]:
    """
    가상 매수 주문을 생성하고 즉시 체결한다.

    현금이 부족하면 주문을 생성하지 않고 실패 결과를 반환한다.

    Returns:
        dict: {"success": bool, "message": str, "order": dict | None}
    """
    if quantity <= 0:
        return _result(False, "수량은 1주 이상이어야 합니다.")
    if price <= 0:
        return _result(False, "가격은 0원보다 커야 합니다.")

    required_cash = round(quantity * price, 2)
    current_cash = _compute_cash()

    if current_cash < required_cash:
        return _result(
            False,
            f"현금 부족: 필요 {required_cash:,.0f}원 / 가용 {current_cash:,.0f}원 "
            f"(부족분 {required_cash - current_cash:,.0f}원)",
        )

    order = save_virtual_order({
        "stock_code":    stock_code,
        "stock_name":    stock_name,
        "side":          "BUY",
        "quantity":      quantity,
        "price":         price,
        "strategy_name": strategy_name,
        "reason":        reason or f"가상 매수: {stock_name}",
        "score":         score,
        "decision":      decision,
        "status":        "OPEN",
    })

    # 즉시 체결 처리
    order = execute_virtual_order(order.get("id"))
    _sync_portfolio()

    return _result(
        True,
        f"가상 매수 체결 완료: {stock_name} {quantity}주 @ {price:,.0f}원 "
        f"(합계 {required_cash:,.0f}원)",
        order=order,
        stock_code=str(stock_code).zfill(6),
        stock_name=stock_name,
        quantity=quantity,
        price=price,
        amount=required_cash,
    )


def place_virtual_sell_order(
    stock_code: str,
    stock_name: str,
    quantity: int,
    price: float,
    strategy_name: str = DEFAULT_STRATEGY,
    reason: str = "",
    score: int = 0,
    decision: str = "",
) -> dict[str, Any]:
    """
    가상 매도 주문을 생성하고 즉시 체결한다.

    보유 수량이 부족하면 주문을 생성하지 않고 실패 결과를 반환한다.

    Returns:
        dict: {"success": bool, "message": str, "order": dict | None}
    """
    if quantity <= 0:
        return _result(False, "수량은 1주 이상이어야 합니다.")
    if price <= 0:
        return _result(False, "가격은 0원보다 커야 합니다.")

    holding_qty = _get_holding_quantity(stock_code, strategy_name)

    if holding_qty < quantity:
        return _result(
            False,
            f"보유 수량 부족: 요청 {quantity}주 / 보유 {holding_qty}주 "
            f"(부족분 {quantity - holding_qty}주)",
            holding_quantity=holding_qty,
        )

    sell_amount = round(quantity * price, 2)

    order = save_virtual_order({
        "stock_code":    stock_code,
        "stock_name":    stock_name,
        "side":          "SELL",
        "quantity":      quantity,
        "price":         price,
        "strategy_name": strategy_name,
        "reason":        reason or f"가상 매도: {stock_name}",
        "score":         score,
        "decision":      decision,
        "status":        "OPEN",
    })

    # 즉시 체결 처리
    order = execute_virtual_order(order.get("id"))
    _sync_portfolio()

    return _result(
        True,
        f"가상 매도 체결 완료: {stock_name} {quantity}주 @ {price:,.0f}원 "
        f"(합계 {sell_amount:,.0f}원)",
        order=order,
        stock_code=str(stock_code).zfill(6),
        stock_name=stock_name,
        quantity=quantity,
        price=price,
        amount=sell_amount,
    )


def cancel_virtual_order(order_id: int | str) -> dict[str, Any]:
    """
    미체결(OPEN) 상태의 가상 주문을 취소한다.
    이미 체결(CLOSED)된 주문은 취소할 수 없다.

    Args:
        order_id: 취소할 주문 ID

    Returns:
        dict: {"success": bool, "message": str, "order": dict | None}
    """
    # 주문 조회
    all_orders = list_virtual_orders()
    target = next(
        (o for o in all_orders if str(o.get("id")) == str(order_id)),
        None,
    )

    if target is None:
        return _result(False, f"주문을 찾을 수 없습니다. (ID: {order_id})")

    current_status = str(target.get("status", "")).upper()
    if current_status == "CLOSED":
        side_label = "매수" if str(target.get("side", "")).upper() == "BUY" else "매도"
        return _result(
            False,
            f"이미 체결된 주문은 취소할 수 없습니다. "
            f"({target.get('stock_name', '')} 가상 {side_label}, ID: {order_id})",
            order=target,
        )

    # 상태 업데이트 → CLOSED (취소 처리)
    updated = None
    if _supabase_connected():
        updated = _update_order_status_supabase(order_id, "CANCELLED")

    if updated is None:
        updated = _update_order_status_local(order_id, "CANCELLED")

    if updated is None:
        return _result(False, f"주문 취소 처리 중 오류가 발생했습니다. (ID: {order_id})")

    _sync_portfolio()

    side_label = "매수" if str(target.get("side", "")).upper() == "BUY" else "매도"
    return _result(
        True,
        f"가상 {side_label} 주문 취소 완료: "
        f"{target.get('stock_name', '')} {target.get('quantity', 0)}주 (ID: {order_id})",
        order=updated,
    )


def get_virtual_orders(
    strategy_name: str | None = None,
    stock_code: str | None = None,
    side: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    가상 주문 내역을 조회한다.

    Args:
        strategy_name: 전략명 필터 (None = 전체)
        stock_code:    종목코드 필터 (None = 전체)
        side:          'BUY' 또는 'SELL' 필터 (None = 전체)
        limit:         최대 반환 건수 (None = 전체)

    Returns:
        list[dict]: 주문 내역 (최신순)
    """
    orders = list_virtual_orders(strategy_name=strategy_name)

    if stock_code:
        code = str(stock_code).zfill(6)
        orders = [o for o in orders if str(o.get("stock_code", "")).zfill(6) == code]

    if side:
        side_upper = side.upper()
        orders = [o for o in orders if str(o.get("side", "")).upper() == side_upper]

    if limit and limit > 0:
        orders = orders[:limit]

    return orders


def execute_virtual_order(order_id: int | str) -> dict[str, Any]:
    """
    OPEN 상태 주문을 즉시 체결(CLOSED) 처리한다.

    체결 기준: order_price 기준 단순 즉시 체결.
    실거래 체결 로직을 포함하지 않습니다.

    Args:
        order_id: 체결할 주문 ID

    Returns:
        dict: 체결된 주문 레코드 (업데이트 실패 시 원본 반환)
    """
    # Supabase 업데이트 시도
    updated = None
    if _supabase_connected():
        updated = _update_order_status_supabase(order_id, "CLOSED")

    # 로컬 JSON 업데이트
    if updated is None:
        updated = _update_order_status_local(order_id, "CLOSED")

    # 업데이트 실패 시 원본 조회 후 반환
    if updated is None:
        all_orders = list_virtual_orders()
        fallback = next(
            (o for o in all_orders if str(o.get("id")) == str(order_id)),
            {},
        )
        return fallback

    return updated
