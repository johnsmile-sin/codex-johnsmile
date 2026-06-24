"""
strategy/paper_trading_engine.py  –  모의매매 엔진 (3차 모의투자)

실제 주문은 절대 실행하지 않습니다.
모든 결과는 virtual_orders, virtual_positions 테이블(또는 로컬 JSON)에만 저장됩니다.

공개 함수:
    run_daily_virtual_trading(market_df, scored_df)   하루 모의매매 사이클 실행
    generate_virtual_buy_candidates(scored_df, ...)   매수 후보 선정
    execute_virtual_buys(candidates)                  가상 매수 주문 실행
    check_exit_conditions(market_df, scored_df)       청산 조건 판단
    execute_virtual_sells(exit_list)                  가상 매도 주문 실행
    summarize_daily_result(buy_results, sell_results) 일일 결과 한국어 요약

진입 조건:
    - 후보 점수 >= 전략 최소 점수
    - 전략 매칭 성공
    - 리스크 조건 4가지 모두 통과
    - 이미 보유 중인 종목 중복 매수 금지

청산 조건:
    - 현재가 >= 목표가  →  익절
    - 현재가 <= 손절가  →  손절
    - 보유일 > 최대 보유일  →  기간 만료 청산
    - 점수 급락(전일 대비 15점 이상 하락) 또는 뉴스 부정 전환  →  조기 청산
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd


# ════════════════════════════════════════════════════════════════
# 내부 헬퍼
# ════════════════════════════════════════════════════════════════

def _safe_float(val, default: float = 0.0) -> float:
    try:
        v = float(val)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return default


def _safe_int(val, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _safe_str(val, default: str = "") -> str:
    try:
        return str(val) if val is not None else default
    except Exception:
        return default


def _build_market_index(market_df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """market_df → {종목코드: row_dict} 인덱스를 만든다."""
    index: dict[str, dict[str, Any]] = {}
    if market_df is None or market_df.empty:
        return index
    for _, row in market_df.iterrows():
        code = _safe_str(row.get("stock_code", "")).zfill(6)
        if code:
            index[code] = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    return index


def _build_scored_index(scored_df: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """scored_df → {종목코드: row_dict} 인덱스를 만든다."""
    index: dict[str, dict[str, Any]] = {}
    if scored_df is None or scored_df.empty:
        return index
    for _, row in scored_df.iterrows():
        code = _safe_str(row.get("stock_code", "")).zfill(6)
        if code:
            index[code] = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    return index


def _get_current_price(code: str, market_index: dict) -> float:
    """market_index에서 종목의 현재가를 꺼낸다."""
    row = market_index.get(code, {})
    for key in ("current_price", "close", "price"):
        v = _safe_float(row.get(key), -1.0)
        if v > 0:
            return v
    return 0.0


def _get_score(code: str, scored_index: dict) -> int:
    """scored_index에서 종목 점수를 꺼낸다. 없으면 -1 (점수 소멸)."""
    row = scored_index.get(code)
    if row is None:
        return -1
    return _safe_int(row.get("score", 0))


def _is_news_negative(code: str, scored_index: dict) -> bool:
    """뉴스 감성이 부정으로 전환됐는지 판단한다."""
    row = scored_index.get(code, {})
    news_sentiment = _safe_str(row.get("news_sentiment", "")).lower()
    return news_sentiment in ("부정", "negative", "neg")


def _max_holding_days_for_position(pos: dict, rules: list[dict]) -> int:
    """포지션의 전략명에 해당하는 최대 보유일을 반환한다."""
    strategy_name = _safe_str(pos.get("strategy_name", ""))
    for rule in rules:
        if rule.get("strategy_name") == strategy_name:
            rj = rule.get("rule_json", {})
            return _safe_int(rj.get("max_holding_days", 5), 5)
    return 5


# ════════════════════════════════════════════════════════════════
# 공개 함수
# ════════════════════════════════════════════════════════════════

def generate_virtual_buy_candidates(
    scored_df: pd.DataFrame,
    market_df: pd.DataFrame,
    rules: list[dict[str, Any]] | None = None,
    max_candidates: int = 10,
) -> list[dict[str, Any]]:
    """
    매수 후보를 선정한다.

    진입 조건:
        1. 후보 점수 >= 전략 최소 점수
        2. 전략 매칭 성공 (match_strategy)
        3. 리스크 조건 4가지 모두 통과 (can_place_virtual_order)
        4. 이미 보유 중인 종목 중복 매수 금지

    Args:
        scored_df:      스코어 계산된 후보 종목 DataFrame
        market_df:      현재가·거래량 포함 시장 데이터 DataFrame
        rules:          전략 규칙 리스트 (None이면 자동 로드)
        max_candidates: 최대 후보 수

    Returns:
        list[dict]: 매수 후보 리스트. 각 항목:
            stock_code, stock_name, current_price, quantity, order_amount,
            strategy_name, reason, target_price, stop_loss_price,
            score, decision, rule
    """
    from strategy.strategy_rules import load_strategy_rules, match_strategy, calculate_target_and_stop
    from strategy.risk_manager import can_place_virtual_order
    from services.virtual_position import get_positions

    if rules is None:
        rules = load_strategy_rules(active_only=True)

    market_index = _build_market_index(market_df)

    # 현재 보유 중인 종목 코드 셋 (중복 매수 방지)
    open_positions = get_positions(status="보유")
    held_codes = {_safe_str(p.get("stock_code", "")).zfill(6) for p in open_positions}

    candidates: list[dict[str, Any]] = []

    if scored_df is None or scored_df.empty:
        return candidates

    # 점수 내림차순 정렬
    sorted_df = scored_df.sort_values("score", ascending=False)

    for _, row in sorted_df.iterrows():
        if len(candidates) >= max_candidates:
            break

        code = _safe_str(row.get("stock_code", "")).zfill(6)
        if not code or code == "000000":
            continue

        # 이미 보유 중 → 건너뜀
        if code in held_codes:
            continue

        # 현재가 조회
        current_price = _get_current_price(code, market_index)
        if current_price <= 0:
            continue

        # 전략 매칭
        matched = match_strategy(row, rules=rules)
        if not matched:
            continue

        strategy_match = matched[0]
        rule = strategy_match["rule"]

        # 매수 수량 계산 (전략 최대 투자금 / 현재가)
        max_amount = _safe_float(rule.get("rule_json", {}).get("max_position_amount", 1_000_000), 1_000_000)
        quantity = int(max_amount // current_price)
        if quantity <= 0:
            continue

        order_amount = round(quantity * current_price, 2)

        # 리스크 검사
        risk = can_place_virtual_order(code, order_amount)
        if not risk["allowed"]:
            continue

        # 목표가·손절가 계산
        targets = calculate_target_and_stop(current_price, rule)

        candidates.append({
            "stock_code":      code,
            "stock_name":      _safe_str(row.get("stock_name", code)),
            "current_price":   current_price,
            "quantity":        quantity,
            "order_amount":    order_amount,
            "strategy_name":   _safe_str(rule.get("strategy_name", "v3_score_momentum")),
            "reason":          strategy_match["reason"],
            "target_price":    targets["target_price"],
            "stop_loss_price": targets["stop_loss_price"],
            "max_holding_days": targets["max_holding_days"],
            "risk_reward_ratio": targets["risk_reward_ratio"],
            "score":           _safe_int(row.get("score", 0)),
            "decision":        _safe_str(row.get("decision", "")),
            "rule":            rule,
        })

    return candidates


def execute_virtual_buys(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    매수 후보 리스트에 대해 가상 매수 주문을 실행하고 포지션을 추가한다.

    Args:
        candidates: generate_virtual_buy_candidates() 반환값

    Returns:
        list[dict]: 매수 실행 결과 리스트. 각 항목:
            stock_code, stock_name, success, message, order, quantity, price
    """
    from services.virtual_order import place_virtual_buy_order
    from services.virtual_position import add_position

    results: list[dict[str, Any]] = []

    for c in candidates:
        code          = c["stock_code"]
        name          = c["stock_name"]
        price         = c["current_price"]
        quantity      = c["quantity"]
        strategy_name = c["strategy_name"]
        reason        = c["reason"]
        score         = c["score"]
        decision      = c["decision"]

        # 가상 매수 주문
        order_result = place_virtual_buy_order(
            stock_code=code,
            stock_name=name,
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
            reason=reason,
            score=score,
            decision=decision,
        )

        if order_result["success"]:
            # 포지션 추가
            add_position(
                stock_code=code,
                stock_name=name,
                entry_price=price,
                quantity=quantity,
                strategy_name=strategy_name,
                stop_loss_price=c.get("stop_loss_price"),
                target_price=c.get("target_price"),
            )

        results.append({
            "stock_code": code,
            "stock_name": name,
            "success":    order_result["success"],
            "message":    order_result["message"],
            "order":      order_result.get("order"),
            "quantity":   quantity,
            "price":      price,
            "strategy_name": strategy_name,
            "target_price":   c.get("target_price"),
            "stop_loss_price": c.get("stop_loss_price"),
        })

    return results


def check_exit_conditions(
    market_df: pd.DataFrame,
    scored_df: pd.DataFrame | None = None,
    rules: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    보유 포지션 전체를 순회하며 청산 조건을 판단한다.

    청산 조건:
        1. 현재가 >= 목표가  →  익절
        2. 현재가 <= 손절가  →  손절
        3. 보유일 > 최대 보유일  →  기간 만료 청산
        4. 점수 15점 이상 급락 또는 뉴스 부정 전환  →  조기 청산

    Args:
        market_df:  현재가 포함 시장 데이터 DataFrame
        scored_df:  점수 데이터 DataFrame (None이면 점수 조건 미적용)
        rules:      전략 규칙 리스트 (None이면 자동 로드)

    Returns:
        list[dict]: 청산 대상 리스트. 각 항목:
            position, current_price, exit_reason, close_reason
    """
    from services.virtual_position import get_positions
    from strategy.strategy_rules import load_strategy_rules

    if rules is None:
        try:
            rules = load_strategy_rules(active_only=True)
        except Exception:
            rules = []

    market_index = _build_market_index(market_df)
    scored_index = _build_scored_index(scored_df)

    open_positions = get_positions(status="보유")
    exit_list: list[dict[str, Any]] = []

    for pos in open_positions:
        code  = _safe_str(pos.get("stock_code", "")).zfill(6)
        name  = _safe_str(pos.get("stock_name", code))

        current_price = _get_current_price(code, market_index)
        if current_price <= 0:
            # 시장 데이터 없으면 포지션 저장 현재가 사용
            current_price = _safe_float(pos.get("current_price", 0))
        if current_price <= 0:
            continue

        target_price    = _safe_float(pos.get("target_price", 0))
        stop_loss_price = _safe_float(pos.get("stop_loss_price", 0))
        entry_score     = _safe_int(pos.get("score", 0))
        holding_days    = _safe_int(pos.get("holding_days", 0))
        max_days        = _max_holding_days_for_position(pos, rules)

        # 1. 익절 (목표가 도달)
        if target_price > 0 and current_price >= target_price:
            exit_list.append({
                "position":      pos,
                "current_price": current_price,
                "exit_reason":   f"목표가 도달: {current_price:,.0f}원 >= {target_price:,.0f}원",
                "close_reason":  "익절",
            })
            continue

        # 2. 손절 (손절가 도달)
        if stop_loss_price > 0 and current_price <= stop_loss_price:
            exit_list.append({
                "position":      pos,
                "current_price": current_price,
                "exit_reason":   f"손절가 도달: {current_price:,.0f}원 <= {stop_loss_price:,.0f}원",
                "close_reason":  "손절",
            })
            continue

        # 3. 기간 만료 (최대 보유일 초과)
        if holding_days > max_days:
            exit_list.append({
                "position":      pos,
                "current_price": current_price,
                "exit_reason":   f"최대 보유일 초과: {holding_days}일 > {max_days}일",
                "close_reason":  "청산",
            })
            continue

        # 4. 점수 급락 또는 뉴스 부정 전환 (scored_df 제공 시)
        if scored_df is not None:
            current_score = _get_score(code, scored_index)

            # 현재 점수가 없거나 (후보 탈락) 15점 이상 급락
            if current_score == -1:
                exit_list.append({
                    "position":      pos,
                    "current_price": current_price,
                    "exit_reason":   f"후보 점수 소멸 (스캐너 탈락): {name}",
                    "close_reason":  "청산",
                })
                continue

            if entry_score > 0 and (entry_score - current_score) >= 15:
                exit_list.append({
                    "position":      pos,
                    "current_price": current_price,
                    "exit_reason":   f"점수 급락: {entry_score}→{current_score}점 (낙폭 {entry_score - current_score}점)",
                    "close_reason":  "청산",
                })
                continue

            # 뉴스 부정 전환
            if _is_news_negative(code, scored_index):
                exit_list.append({
                    "position":      pos,
                    "current_price": current_price,
                    "exit_reason":   f"뉴스 감성 부정 전환: {name}",
                    "close_reason":  "청산",
                })
                continue

    return exit_list


def execute_virtual_sells(exit_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    청산 대상 리스트에 대해 가상 매도 주문을 실행하고 포지션을 청산한다.

    Args:
        exit_list: check_exit_conditions() 반환값

    Returns:
        list[dict]: 매도 실행 결과 리스트. 각 항목:
            stock_code, stock_name, success, message, order,
            exit_reason, close_reason, profit_loss, return_rate
    """
    from services.virtual_order import place_virtual_sell_order
    from services.virtual_position import close_position, calculate_position_return

    results: list[dict[str, Any]] = []

    for item in exit_list:
        pos           = item["position"]
        current_price = item["current_price"]
        exit_reason   = item["exit_reason"]
        close_reason  = item["close_reason"]

        code          = _safe_str(pos.get("stock_code", "")).zfill(6)
        name          = _safe_str(pos.get("stock_name", code))
        quantity      = _safe_int(pos.get("quantity", 0))
        strategy_name = _safe_str(pos.get("strategy_name", "v3_score_momentum"))
        entry_price   = _safe_float(pos.get("entry_price", current_price))

        if quantity <= 0 or current_price <= 0:
            results.append({
                "stock_code": code,
                "stock_name": name,
                "success":    False,
                "message":    f"수량 또는 가격이 유효하지 않습니다. ({name})",
                "order":      None,
                "exit_reason":  exit_reason,
                "close_reason": close_reason,
                "profit_loss":  0.0,
                "return_rate":  0.0,
            })
            continue

        # 수익률 계산
        pnl_info = calculate_position_return(entry_price, current_price, quantity)

        # 가상 매도 주문
        order_result = place_virtual_sell_order(
            stock_code=code,
            stock_name=name,
            quantity=quantity,
            price=current_price,
            strategy_name=strategy_name,
            reason=f"[{close_reason}] {exit_reason}",
            score=_safe_int(pos.get("score", 0)),
            decision=close_reason,
        )

        if order_result["success"]:
            # 포지션 청산
            close_position(
                position_id=pos["id"],
                close_price=current_price,
                close_reason=close_reason,
            )

        results.append({
            "stock_code":   code,
            "stock_name":   name,
            "success":      order_result["success"],
            "message":      order_result["message"],
            "order":        order_result.get("order"),
            "exit_reason":  exit_reason,
            "close_reason": close_reason,
            "profit_loss":  pnl_info["profit_loss"],
            "return_rate":  pnl_info["return_rate"],
            "quantity":     quantity,
            "price":        current_price,
            "entry_price":  entry_price,
        })

    return results


def summarize_daily_result(
    buy_results: list[dict[str, Any]],
    sell_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    하루 모의매매 결과를 한국어로 요약한다.

    Args:
        buy_results:  execute_virtual_buys() 반환값
        sell_results: execute_virtual_sells() 반환값

    Returns:
        dict:
            summary_text   str  전체 요약 문자열 (한국어)
            buy_count      int  매수 성공 건수
            sell_count     int  매도 성공 건수
            total_pnl      float 오늘 실현 손익 합계
            buy_details    list  매수 상세
            sell_details   list  매도 상세
            trade_date     str  거래 일자
    """
    today_str = str(date.today())

    buy_ok  = [r for r in buy_results  if r.get("success")]
    buy_fail = [r for r in buy_results if not r.get("success")]
    sell_ok = [r for r in sell_results if r.get("success")]
    sell_fail = [r for r in sell_results if not r.get("success")]

    total_pnl = sum(_safe_float(r.get("profit_loss", 0)) for r in sell_ok)

    lines: list[str] = [
        f"【 모의매매 일일 결과 — {today_str} 】",
        "",
        f"▶ 매수 체결: {len(buy_ok)}건 / 시도 {len(buy_results)}건",
    ]

    for r in buy_ok:
        lines.append(
            f"  ✅ 매수 체결  {r['stock_name']}({r['stock_code']})  "
            f"{r['quantity']}주 @ {_safe_float(r['price']):,.0f}원  "
            f"목표가 {_safe_float(r.get('target_price', 0)):,.0f}원 / "
            f"손절가 {_safe_float(r.get('stop_loss_price', 0)):,.0f}원"
        )
    for r in buy_fail:
        lines.append(f"  ❌ 매수 실패  {r['stock_name']}({r['stock_code']})  — {r['message']}")

    lines += ["", f"▶ 매도 체결: {len(sell_ok)}건 / 시도 {len(sell_results)}건"]

    익절_cnt = sum(1 for r in sell_ok if r.get("close_reason") == "익절")
    손절_cnt = sum(1 for r in sell_ok if r.get("close_reason") == "손절")
    청산_cnt = sum(1 for r in sell_ok if r.get("close_reason") == "청산")

    for r in sell_ok:
        pnl_sign = "+" if r["profit_loss"] >= 0 else ""
        lines.append(
            f"  {'✅' if r['profit_loss'] >= 0 else '🔻'} [{r['close_reason']}]  "
            f"{r['stock_name']}({r['stock_code']})  "
            f"{r['quantity']}주 @ {_safe_float(r['price']):,.0f}원  "
            f"손익 {pnl_sign}{r['profit_loss']:,.0f}원 ({pnl_sign}{r['return_rate']:.2f}%)  "
            f"— {r['exit_reason']}"
        )
    for r in sell_fail:
        lines.append(f"  ❌ 매도 실패  {r['stock_name']}({r['stock_code']})  — {r['message']}")

    pnl_sign = "+" if total_pnl >= 0 else ""
    lines += [
        "",
        "▶ 오늘 실현 손익 요약",
        f"  익절 {익절_cnt}건 / 손절 {손절_cnt}건 / 기타 청산 {청산_cnt}건",
        f"  오늘 실현 손익 합계: {pnl_sign}{total_pnl:,.0f}원",
        "",
    ]

    if not buy_results and not sell_results:
        lines.append("  ※ 오늘 해당하는 조건의 종목이 없어 거래가 발생하지 않았습니다.")

    summary_text = "\n".join(lines)

    return {
        "summary_text": summary_text,
        "buy_count":    len(buy_ok),
        "sell_count":   len(sell_ok),
        "total_pnl":    round(total_pnl, 2),
        "buy_details":  buy_results,
        "sell_details": sell_results,
        "trade_date":   today_str,
    }


def run_daily_virtual_trading(
    market_df: pd.DataFrame,
    scored_df: pd.DataFrame,
    rules: list[dict[str, Any]] | None = None,
    max_buy_candidates: int = 10,
) -> dict[str, Any]:
    """
    하루 모의매매 사이클을 실행한다.

    실행 순서:
        1. 보유일수 갱신
        2. 현재가로 포지션 평가금액 업데이트
        3. 청산 조건 체크 → 가상 매도 실행
        4. 매수 후보 선정 → 가상 매수 실행
        5. 포트폴리오 동기화
        6. 일일 결과 요약 반환

    실제 주문은 절대 실행하지 않습니다.
    모든 결과는 virtual_orders, virtual_positions에만 저장됩니다.

    Args:
        market_df:          현재가·거래량 포함 시장 데이터 DataFrame
        scored_df:          스코어 계산된 후보 종목 DataFrame
        rules:              전략 규칙 리스트 (None이면 자동 로드)
        max_buy_candidates: 최대 매수 후보 수

    Returns:
        dict: summarize_daily_result() 반환값 (summary_text 포함)
    """
    from services.virtual_position import get_positions, update_position_price, update_holding_days

    # 1. 보유일수 갱신
    updated_count = update_holding_days()

    # 2. 현재가로 포지션 평가금액 업데이트
    market_index = _build_market_index(market_df)
    open_positions = get_positions(status="보유")

    for pos in open_positions:
        code = _safe_str(pos.get("stock_code", "")).zfill(6)
        current_price = _get_current_price(code, market_index)
        if current_price > 0:
            update_position_price(pos["id"], current_price)

    # 3. 청산 조건 체크 → 가상 매도 실행
    exit_list    = check_exit_conditions(market_df, scored_df, rules=rules)
    sell_results = execute_virtual_sells(exit_list)

    # 4. 매수 후보 선정 → 가상 매수 실행 (매도 완료 후 포지션 슬롯 확보)
    candidates  = generate_virtual_buy_candidates(
        scored_df, market_df, rules=rules, max_candidates=max_buy_candidates
    )
    buy_results = execute_virtual_buys(candidates)

    # 5. 결과 요약 반환
    summary = summarize_daily_result(buy_results, sell_results)
    summary["updated_positions"] = updated_count

    return summary
