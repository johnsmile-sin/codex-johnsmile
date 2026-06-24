"""
3차 모의투자 서비스.

실거래 주문은 절대 수행하지 않습니다.
모든 매수/매도는 virtual_orders 테이블 또는 로컬 JSON 파일에만 기록합니다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

INITIAL_CASH = 10_000_000
DEFAULT_STRATEGY = "v3_score_momentum"
TAKE_PROFIT_PCT = 8.0
STOP_LOSS_PCT = -4.0
MAX_POSITION_PCT = 0.20
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ORDERS_FILE = DATA_DIR / "virtual_orders.json"


@dataclass(frozen=True)
class StrategyRule:
    name: str
    min_score: int = 75
    buy_decisions: tuple[str, ...] = ("강한 관심", "관심")
    sell_decisions: tuple[str, ...] = ("보류", "제외")
    take_profit_pct: float = TAKE_PROFIT_PCT
    stop_loss_pct: float = STOP_LOSS_PCT
    max_position_pct: float = MAX_POSITION_PCT


DEFAULT_RULE = StrategyRule(name=DEFAULT_STRATEGY)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return str(date.today())


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_local_orders() -> list[dict[str, Any]]:
    if not ORDERS_FILE.exists():
        return []
    try:
        return json.loads(ORDERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_local_orders(orders: list[dict[str, Any]]) -> None:
    _ensure_data_dir()
    ORDERS_FILE.write_text(
        json.dumps(orders, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _next_local_id(orders: list[dict[str, Any]]) -> int:
    ids = [int(order.get("id", 0)) for order in orders if str(order.get("id", "")).isdigit()]
    return max(ids, default=0) + 1


def _supabase_connected() -> bool:
    try:
        from services.supabase_client import is_connected
        return bool(is_connected())
    except Exception:
        return False


def _supabase_client():
    from services.supabase_client import get_client
    return get_client()


def _normalize_order(data: dict[str, Any]) -> dict[str, Any]:
    side = str(data.get("side", "BUY")).upper()
    quantity = int(data.get("quantity", 0))
    price = float(data.get("price", 0))
    amount = round(quantity * price, 2)
    status = str(data.get("status") or "CLOSED").upper()
    if status not in {"OPEN", "CLOSED", "CANCELLED"}:
        status = "CLOSED"
    order_date = str(data.get("order_date") or _today())
    strategy_name = str(data.get("strategy_name") or DEFAULT_STRATEGY)
    return {
        "order_date": order_date,
        "strategy_name": strategy_name,
        "stock_code": str(data.get("stock_code", "")).zfill(6),
        "stock_name": str(data.get("stock_name", "")),
        "side": side,
        "quantity": quantity,
        "price": price,
        "amount": amount,
        "status": status,
        "reason": str(data.get("reason", "")),
        "score": int(float(data.get("score", 0) or 0)),
        "decision": str(data.get("decision", "")),
        "linked_buy_order_id": data.get("linked_buy_order_id"),
        "created_at": str(data.get("created_at") or _now()),
    }


def _is_accounted_order(order: dict[str, Any]) -> bool:
    status = str(order.get("status") or "CLOSED").upper()
    return status == "CLOSED"


def list_virtual_orders(strategy_name: str | None = None) -> list[dict[str, Any]]:
    if _supabase_connected():
        try:
            query = (
                _supabase_client()
                .table("virtual_orders")
                .select("*")
                .order("order_date", desc=True)
                .order("id", desc=True)
            )
            if strategy_name:
                query = query.eq("strategy_name", strategy_name)
            return query.execute().data or []
        except Exception:
            pass

    orders = _load_local_orders()
    if strategy_name:
        orders = [order for order in orders if order.get("strategy_name") == strategy_name]
    return sorted(orders, key=lambda x: (x.get("order_date", ""), int(x.get("id", 0))), reverse=True)


def save_virtual_order(data: dict[str, Any]) -> dict[str, Any]:
    order = _normalize_order(data)

    if _supabase_connected():
        try:
            result = _supabase_client().table("virtual_orders").insert(order).execute()
            rows = result.data or []
            return rows[0] if rows else order
        except Exception:
            pass

    orders = _load_local_orders()
    order["id"] = _next_local_id(orders)
    orders.append(order)
    _save_local_orders(orders)
    return order


def create_virtual_order(
    stock_code: str,
    stock_name: str,
    side: str,
    quantity: int,
    price: float,
    strategy_name: str = DEFAULT_STRATEGY,
    reason: str = "",
    score: int = 0,
    decision: str = "",
    linked_buy_order_id: int | str | None = None,
) -> dict[str, Any]:
    return save_virtual_order({
        "stock_code": stock_code,
        "stock_name": stock_name,
        "side": side,
        "quantity": quantity,
        "price": price,
        "strategy_name": strategy_name,
        "reason": reason,
        "score": score,
        "decision": decision,
        "linked_buy_order_id": linked_buy_order_id,
    })


def build_positions(orders: list[dict[str, Any]] | None = None) -> pd.DataFrame:
    orders = orders if orders is not None else list_virtual_orders()
    orders = [order for order in orders if _is_accounted_order(order)]
    lots: dict[tuple[str, str], dict[str, Any]] = {}

    for order in sorted(orders, key=lambda x: (x.get("order_date", ""), int(x.get("id", 0)))):
        code = str(order.get("stock_code", "")).zfill(6)
        strategy_name = str(order.get("strategy_name") or DEFAULT_STRATEGY)
        key = (strategy_name, code)
        side = str(order.get("side", "")).upper()
        quantity = int(order.get("quantity", 0) or 0)
        price = float(order.get("price", 0) or 0)
        amount = quantity * price
        if quantity <= 0 or price <= 0:
            continue

        pos = lots.setdefault(key, {
            "strategy_name": strategy_name,
            "stock_code": code,
            "stock_name": order.get("stock_name", code),
            "quantity": 0,
            "cost_amount": 0.0,
            "avg_price": 0.0,
        })

        if side == "BUY":
            pos["cost_amount"] += amount
            pos["quantity"] += quantity
        elif side == "SELL":
            sell_qty = min(quantity, int(pos["quantity"]))
            pos["cost_amount"] -= pos["avg_price"] * sell_qty
            pos["quantity"] -= sell_qty

        pos["avg_price"] = (
            pos["cost_amount"] / pos["quantity"]
            if pos["quantity"] > 0 else 0.0
        )

    rows = [pos for pos in lots.values() if int(pos["quantity"]) > 0]
    return pd.DataFrame(rows)


def get_portfolio_snapshot(market_df: pd.DataFrame | None = None) -> dict[str, Any]:
    orders = list_virtual_orders()
    accounted_orders = [order for order in orders if _is_accounted_order(order)]
    positions = build_positions(accounted_orders)
    cash = INITIAL_CASH
    realized_pnl = 0.0

    # 시간순으로 처리하여 실현 손익 계산
    cost_basis: dict[tuple[str, str], dict[str, Any]] = {}
    for order in sorted(accounted_orders, key=lambda x: (x.get("order_date", ""), int(x.get("id", 0)))):
        code = str(order.get("stock_code", "")).zfill(6)
        strategy_name = str(order.get("strategy_name") or DEFAULT_STRATEGY)
        key = (strategy_name, code)
        side = str(order.get("side", "")).upper()
        quantity = int(order.get("quantity", 0) or 0)
        price = float(order.get("price", 0) or 0)
        amount = quantity * price
        if quantity <= 0 or price <= 0:
            continue

        if side == "BUY":
            cash -= amount
            pos = cost_basis.setdefault(key, {"quantity": 0, "cost_amount": 0.0})
            pos["cost_amount"] += amount
            pos["quantity"] += quantity
        elif side == "SELL":
            cash += amount
            pos = cost_basis.get(key, {"quantity": 0, "cost_amount": 0.0})
            if pos["quantity"] > 0:
                avg_cost = pos["cost_amount"] / pos["quantity"]
                sell_qty = min(quantity, pos["quantity"])
                realized_pnl += (price - avg_cost) * sell_qty
                pos["cost_amount"] -= avg_cost * sell_qty
                pos["quantity"] -= sell_qty

    if not positions.empty and market_df is not None and not market_df.empty:
        price_map = {
            str(row["stock_code"]).zfill(6): float(row.get("current_price", row.get("close", 0)) or 0)
            for _, row in market_df.iterrows()
        }
        positions["current_price"] = positions["stock_code"].map(price_map).fillna(positions["avg_price"])
    elif not positions.empty:
        positions["current_price"] = positions["avg_price"]

    if not positions.empty:
        positions["market_value"] = positions["quantity"] * positions["current_price"]
        positions["unrealized_pnl"] = positions["market_value"] - positions["cost_amount"]
        positions["return_rate"] = (
            positions["unrealized_pnl"] / positions["cost_amount"] * 100
        ).round(2)
        invested = float(positions["cost_amount"].sum())
        market_value = float(positions["market_value"].sum())
        unrealized_pnl = float(positions["unrealized_pnl"].sum())
    else:
        invested = 0.0
        market_value = 0.0
        unrealized_pnl = 0.0

    total_value = cash + market_value
    total_return = round((total_value - INITIAL_CASH) / INITIAL_CASH * 100, 2)
    return {
        "initial_cash": INITIAL_CASH,
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "market_value": round(market_value, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "realized_pnl": round(realized_pnl, 2),
        "total_value": round(total_value, 2),
        "total_return": total_return,
        "positions": positions,
        "orders": orders,
    }


def _find_position(positions: pd.DataFrame, stock_code: str, strategy_name: str) -> dict[str, Any] | None:
    if positions.empty:
        return None
    code = str(stock_code).zfill(6)
    matched = positions[
        (positions["stock_code"] == code)
        & (positions["strategy_name"] == strategy_name)
    ]
    if matched.empty:
        return None
    return matched.iloc[0].to_dict()


def run_strategy_once(
    market_df: pd.DataFrame,
    scored_df: pd.DataFrame,
    strategy: StrategyRule = DEFAULT_RULE,
) -> dict[str, Any]:
    snapshot = get_portfolio_snapshot(market_df)
    positions = snapshot["positions"]
    cash = float(snapshot["cash"])
    created: list[dict[str, Any]] = []
    skipped: list[str] = []

    market_by_code = {
        str(row["stock_code"]).zfill(6): row
        for _, row in market_df.iterrows()
    }

    for _, row in scored_df.sort_values("score", ascending=False).iterrows():
        code = str(row["stock_code"]).zfill(6)
        decision = str(row.get("decision", ""))
        score = int(float(row.get("score", 0) or 0))
        mrow = market_by_code.get(code)
        if mrow is None:
            continue
        price = float(mrow.get("current_price", mrow.get("close", 0)) or 0)
        if price <= 0:
            continue

        pos = _find_position(positions, code, strategy.name)
        if pos:
            return_rate = (price - float(pos["avg_price"])) / float(pos["avg_price"]) * 100
            should_sell = (
                return_rate <= strategy.stop_loss_pct
                or return_rate >= strategy.take_profit_pct
                or decision in strategy.sell_decisions
            )
            if should_sell:
                reason = (
                    f"전략 매도: 수익률 {return_rate:+.2f}% "
                    f"(손절 {strategy.stop_loss_pct:+.1f}%, 익절 {strategy.take_profit_pct:+.1f}%)"
                )
                created.append(create_virtual_order(
                    code,
                    str(row.get("stock_name", code)),
                    "SELL",
                    int(pos["quantity"]),
                    price,
                    strategy.name,
                    reason,
                    score,
                    decision,
                ))
            continue

        if decision not in strategy.buy_decisions or score < strategy.min_score:
            continue

        budget = min(INITIAL_CASH * strategy.max_position_pct, cash)
        quantity = int(budget // price)
        if quantity <= 0:
            skipped.append(f"{row.get('stock_name', code)}: 현금 부족")
            continue
        reason = (
            f"전략 매수: 점수 {score}점, 판단 {decision}, "
            f"종목당 최대 {strategy.max_position_pct:.0%}"
        )
        order = create_virtual_order(
            code,
            str(row.get("stock_name", code)),
            "BUY",
            quantity,
            price,
            strategy.name,
            reason,
            score,
            decision,
        )
        created.append(order)
        cash -= quantity * price

    return {
        "strategy_name": strategy.name,
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
    }


def summarize_strategy_performance(market_df: pd.DataFrame | None = None) -> pd.DataFrame:
    snapshot = get_portfolio_snapshot(market_df)
    orders = pd.DataFrame(snapshot["orders"])
    positions = snapshot["positions"]

    if orders.empty:
        return pd.DataFrame(columns=[
            "strategy_name", "orders", "buy_orders", "sell_orders",
            "open_positions", "market_value", "unrealized_pnl", "return_rate",
        ])

    rows = []
    for strategy_name, group in orders.groupby("strategy_name"):
        pos = positions[positions["strategy_name"] == strategy_name] if not positions.empty else pd.DataFrame()
        market_value = float(pos["market_value"].sum()) if "market_value" in pos.columns else 0.0
        cost_amount = float(pos["cost_amount"].sum()) if "cost_amount" in pos.columns else 0.0
        unrealized_pnl = float(pos["unrealized_pnl"].sum()) if "unrealized_pnl" in pos.columns else 0.0
        rows.append({
            "strategy_name": strategy_name,
            "orders": len(group),
            "buy_orders": int((group["side"] == "BUY").sum()),
            "sell_orders": int((group["side"] == "SELL").sum()),
            "open_positions": len(pos),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "return_rate": round(unrealized_pnl / cost_amount * 100, 2) if cost_amount else 0.0,
        })
    return pd.DataFrame(rows).sort_values("return_rate", ascending=False)


def run_light_backtest(scored_df: pd.DataFrame, days: int = 20) -> pd.DataFrame:
    if scored_df.empty:
        return pd.DataFrame()

    rows = []
    top = scored_df.sort_values("score", ascending=False).head(10)
    for idx, row in top.reset_index(drop=True).iterrows():
        score = int(float(row.get("score", 0) or 0))
        change_rate = float(row.get("change_rate", 0) or 0)
        seed_return = (score - 60) * 0.12 + change_rate * 0.35 - idx * 0.15
        simulated_return = round(max(min(seed_return, TAKE_PROFIT_PCT), STOP_LOSS_PCT), 2)
        result = "익절" if simulated_return >= TAKE_PROFIT_PCT else (
            "손절" if simulated_return <= STOP_LOSS_PCT else "보유"
        )
        rows.append({
            "stock_code": str(row.get("stock_code", "")).zfill(6),
            "stock_name": row.get("stock_name", ""),
            "strategy_name": DEFAULT_STRATEGY,
            "score": score,
            "decision": row.get("decision", ""),
            "backtest_days": days,
            "entry_price": float(row.get("current_price", row.get("close", 0)) or 0),
            "return_rate": simulated_return,
            "result": result,
        })
    return pd.DataFrame(rows)
