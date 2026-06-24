"""
strategy/strategy_rules.py  –  전략 규칙 서비스 (3차 모의투자)

기본 전략 3종을 정의하고, 후보 종목이 어느 전략에 해당하는지 판정합니다.
전략 규칙은 Supabase strategy_rules 테이블 또는 로컬 JSON으로 저장·로드합니다.
Streamlit에서 수정 가능하도록 dict 구조로 관리합니다.

공개 함수:
    get_default_strategy_rules()          기본 전략 3개 반환 (dict 리스트)
    save_strategy_rules(rules)            전략 규칙 저장 (Supabase / 로컬 JSON)
    load_strategy_rules()                 전략 규칙 로드
    match_strategy(candidate, ...)        후보 종목이 매칭되는 전략 목록 반환
    calculate_target_and_stop(price, rule)  목표가·손절가 계산
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR   = Path(__file__).resolve().parents[1] / "data"
RULES_FILE = DATA_DIR / "strategy_rules.json"


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


def _safe(d: dict | Any, key: str, default=None):
    """dict 또는 pandas Series에서 안전하게 값을 꺼낸다."""
    try:
        val = d.get(key, default) if hasattr(d, "get") else getattr(d, key, default)
    except Exception:
        return default
    if val is None:
        return default
    try:
        import pandas as pd
        if pd.isna(val):
            return default
    except (TypeError, ImportError):
        pass
    return val


# ════════════════════════════════════════════════════════════════
# 기본 전략 정의
# ════════════════════════════════════════════════════════════════

def get_default_strategy_rules() -> list[dict[str, Any]]:
    """
    기본 전략 3개를 반환한다.

    각 전략은 strategy_rules 테이블 컬럼과 동일한 구조를 가진다.
    rule_json 안의 match_conditions 항목이 match_strategy() 판정에 사용된다.

    Returns:
        list[dict]: 전략 규칙 리스트
    """
    return [
        {
            "strategy_name":       "거래량 급증 모멘텀",
            "description":         "거래량이 평균 대비 2배 이상 급증하고 점수가 높은 단기 모멘텀 전략",
            "min_score":           75,
            "take_profit_rate":    5.0,
            "stop_loss_rate":      -3.0,
            "max_holding_days":    5,
            "max_position_amount": 2_000_000,
            "is_active":           True,
            "rule_json": {
                "buy_decisions":    ["강한 관심", "관심"],
                "sell_decisions":   ["보류", "제외"],
                "real_order":       False,
                "match_conditions": {
                    "min_score":         75,
                    "min_volume_ratio":  2.0,   # 거래량 비율 기준
                    "min_change_rate":   0.0,   # 당일 등락률 0% 이상 (하락 중 제외)
                    "max_change_rate":   15.0,  # 15% 이상 급등 추격 제외
                    "require_news":      False,
                },
            },
            "created_at": _now(),
            "updated_at": _now(),
        },
        {
            "strategy_name":       "뉴스 호재 단기매매",
            "description":         "긍정 뉴스 심리가 우세하고 점수 60점 이상인 단기 매매 전략",
            "min_score":           60,
            "take_profit_rate":    7.0,
            "stop_loss_rate":      -4.0,
            "max_holding_days":    3,
            "max_position_amount": 1_500_000,
            "is_active":           True,
            "rule_json": {
                "buy_decisions":    ["강한 관심", "관심", "관찰"],
                "sell_decisions":   ["보류", "제외"],
                "real_order":       False,
                "match_conditions": {
                    "min_score":           60,
                    "min_news_count":      1,     # 뉴스 1건 이상
                    "require_positive_news": True, # 긍정 뉴스 우세 필요
                    "min_positive_ratio":  0.4,   # 긍정 뉴스 비율 40% 이상
                    "max_change_rate":     20.0,
                },
            },
            "created_at": _now(),
            "updated_at": _now(),
        },
        {
            "strategy_name":       "안정형 분할매수 후보",
            "description":         "재무 안정성이 검증된 종목에 분할 매수하는 중기 전략",
            "min_score":           60,
            "take_profit_rate":    8.0,
            "stop_loss_rate":      -5.0,
            "max_holding_days":    10,
            "max_position_amount": 2_500_000,
            "is_active":           True,
            "rule_json": {
                "buy_decisions":    ["강한 관심", "관심", "관찰"],
                "sell_decisions":   ["보류", "제외"],
                "real_order":       False,
                "match_conditions": {
                    "min_score":       60,
                    "max_debt_ratio":  150.0,  # 부채비율 150% 이하
                    "min_roe":         0.0,    # ROE 0% 이상 (적자 제외)
                    "max_per":         50.0,   # PER 50배 이하
                    "require_profit":  True,   # 흑자 기업
                },
            },
            "created_at": _now(),
            "updated_at": _now(),
        },
    ]


# ════════════════════════════════════════════════════════════════
# 저장 / 로드
# ════════════════════════════════════════════════════════════════

def save_strategy_rules(rules: list[dict[str, Any]]) -> dict[str, Any]:
    """
    전략 규칙 리스트를 저장한다.
    Supabase 연결 시 strategy_rules 테이블에 upsert, 없으면 로컬 JSON에 저장한다.

    Args:
        rules: 전략 규칙 리스트 (get_default_strategy_rules() 형식)

    Returns:
        dict: {"saved": int, "mode": "supabase" | "local"}
    """
    if _supabase_connected():
        try:
            saved = 0
            client = _supabase_client()
            for rule in rules:
                payload = {k: v for k, v in rule.items() if k not in ("id",)}
                if isinstance(payload.get("rule_json"), dict):
                    payload["rule_json"] = json.dumps(payload["rule_json"], ensure_ascii=False)
                client.table("strategy_rules").upsert(
                    payload, on_conflict="strategy_name"
                ).execute()
                saved += 1
            return {"saved": saved, "mode": "supabase"}
        except Exception:
            pass

    _ensure_data_dir()
    RULES_FILE.write_text(
        json.dumps(rules, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"saved": len(rules), "mode": "local"}


def load_strategy_rules(active_only: bool = True) -> list[dict[str, Any]]:
    """
    저장된 전략 규칙을 로드한다.
    저장된 규칙이 없으면 기본 전략 3개를 자동으로 저장하고 반환한다.

    Args:
        active_only: True이면 is_active=True 규칙만 반환 (기본값)

    Returns:
        list[dict]: 전략 규칙 리스트
    """
    rules: list[dict[str, Any]] = []

    if _supabase_connected():
        try:
            query = _supabase_client().table("strategy_rules").select("*")
            if active_only:
                query = query.eq("is_active", True)
            rows = query.order("strategy_name").execute().data or []
            if rows:
                # rule_json이 문자열로 저장된 경우 파싱
                for row in rows:
                    if isinstance(row.get("rule_json"), str):
                        try:
                            row["rule_json"] = json.loads(row["rule_json"])
                        except Exception:
                            pass
                return rows
        except Exception:
            pass

    if RULES_FILE.exists():
        try:
            rules = json.loads(RULES_FILE.read_text(encoding="utf-8"))
            if active_only:
                rules = [r for r in rules if r.get("is_active", True)]
            if rules:
                return rules
        except Exception:
            pass

    # 저장된 규칙 없음 → 기본값으로 초기화
    defaults = get_default_strategy_rules()
    save_strategy_rules(defaults)
    return defaults if not active_only else [r for r in defaults if r.get("is_active", True)]


# ════════════════════════════════════════════════════════════════
# 전략 매칭
# ════════════════════════════════════════════════════════════════

def match_strategy(
    candidate: dict | Any,
    news_summary: dict[str, Any] | None = None,
    financial_summary: dict[str, Any] | None = None,
    rules: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    후보 종목이 어떤 전략에 해당하는지 판정한다.

    Args:
        candidate:          스캐너 결과 row (dict 또는 pd.Series)
                            필드: score, decision, change_rate, news_count,
                                  volume, avg_volume_20d, per, roe, debt_ratio
        news_summary:       뉴스 감성 요약 dict
                            {"합계": int, "긍정": int, "중립": int, "부정": int}
        financial_summary:  재무 지표 dict
                            {"per": float, "roe": float, "debt_ratio": float}
        rules:              전략 규칙 리스트 (None이면 load_strategy_rules() 사용)

    Returns:
        list[dict]: 매칭된 전략 리스트
                    [{"strategy_name": str, "reason": str, "rule": dict}, ...]
    """
    if rules is None:
        rules = load_strategy_rules(active_only=True)

    news_summary       = news_summary or {}
    financial_summary  = financial_summary or {}

    score        = float(_safe(candidate, "score", 0) or 0)
    decision     = str(_safe(candidate, "decision", "") or "")
    change_rate  = float(_safe(candidate, "change_rate", 0) or 0)
    news_count   = int(_safe(candidate, "news_count", 0) or 0)
    volume       = float(_safe(candidate, "volume", 0) or 0)
    avg_vol      = float(_safe(candidate, "avg_volume_20d", 1) or 1)
    volume_ratio = volume / avg_vol if avg_vol > 0 else 0.0

    per        = float(_safe(financial_summary, "per",        _safe(candidate, "per",        999)) or 999)
    roe        = float(_safe(financial_summary, "roe",        _safe(candidate, "roe",        0)) or 0)
    debt_ratio = float(_safe(financial_summary, "debt_ratio", _safe(candidate, "debt_ratio", 0)) or 0)

    news_total    = int(news_summary.get("합계", news_count) or news_count)
    news_positive = int(news_summary.get("긍정", 0))
    positive_ratio = news_positive / news_total if news_total > 0 else 0.0

    matched: list[dict[str, Any]] = []

    for rule in rules:
        cond = rule.get("rule_json", {})
        if isinstance(cond, str):
            try:
                cond = json.loads(cond)
            except Exception:
                cond = {}
        mc = cond.get("match_conditions", {})

        strategy_name = rule["strategy_name"]
        buy_decisions = cond.get("buy_decisions", ["강한 관심", "관심"])

        # ── 공통 조건 ─────────────────────────────────────────
        min_score = float(mc.get("min_score", rule.get("min_score", 0)))
        if score < min_score:
            continue
        if decision not in buy_decisions:
            continue

        # ── 전략별 조건 ───────────────────────────────────────
        reasons: list[str] = [f"점수 {score:.0f}점 ({decision})"]

        if strategy_name == "거래량 급증 모멘텀":
            min_vr   = float(mc.get("min_volume_ratio", 2.0))
            min_chg  = float(mc.get("min_change_rate",  0.0))
            max_chg  = float(mc.get("max_change_rate",  15.0))
            if volume_ratio < min_vr:
                continue
            if not (min_chg <= change_rate <= max_chg):
                continue
            reasons.append(f"거래량비율 {volume_ratio:.1f}배")
            reasons.append(f"등락률 {change_rate:+.2f}%")

        elif strategy_name == "뉴스 호재 단기매매":
            min_news   = int(mc.get("min_news_count", 1))
            req_pos    = bool(mc.get("require_positive_news", True))
            min_pos_rt = float(mc.get("min_positive_ratio", 0.4))
            if news_count < min_news:
                continue
            if req_pos and positive_ratio < min_pos_rt:
                continue
            reasons.append(f"뉴스 {news_count}건 (긍정 {positive_ratio:.0%})")

        elif strategy_name == "안정형 분할매수 후보":
            max_debt   = float(mc.get("max_debt_ratio", 150.0))
            min_roe    = float(mc.get("min_roe", 0.0))
            max_per    = float(mc.get("max_per", 50.0))
            req_profit = bool(mc.get("require_profit", True))
            if debt_ratio > max_debt:
                continue
            if roe < min_roe:
                continue
            if req_profit and (per < 0 or roe < 0):
                continue
            if 0 < per > max_per:
                continue
            reasons.append(f"부채비율 {debt_ratio:.0f}% / ROE {roe:.1f}%")

        matched.append({
            "strategy_name": strategy_name,
            "reason":        " | ".join(reasons),
            "rule":          rule,
        })

    return matched


# ════════════════════════════════════════════════════════════════
# 목표가 · 손절가 계산
# ════════════════════════════════════════════════════════════════

def calculate_target_and_stop(
    entry_price: float,
    rule: dict[str, Any],
) -> dict[str, Any]:
    """
    진입 단가와 전략 규칙으로 목표가·손절가·최대 보유일을 계산한다.

    Args:
        entry_price: 매수 진입 단가 (원)
        rule:        전략 규칙 dict (load_strategy_rules() 반환값의 개별 항목)

    Returns:
        dict:
            target_price      목표가 (원, 1원 단위 반올림)
            stop_loss_price   손절가 (원, 1원 단위 반올림)
            take_profit_rate  익절률 (%)
            stop_loss_rate    손절률 (%)
            max_holding_days  최대 보유일
            expected_profit   예상 수익 (원)
            expected_loss     예상 손실 (원)
            risk_reward_ratio 손익비 (수익/손실, 높을수록 유리)
    """
    take_profit_rate = float(rule.get("take_profit_rate", 5.0))
    stop_loss_rate   = float(rule.get("stop_loss_rate",   -3.0))
    max_holding_days = int(rule.get("max_holding_days",    5))

    target_price    = round(entry_price * (1 + take_profit_rate / 100))
    stop_loss_price = round(entry_price * (1 + stop_loss_rate   / 100))

    expected_profit = round(target_price    - entry_price, 2)
    expected_loss   = round(entry_price - stop_loss_price, 2)
    risk_reward     = round(expected_profit / expected_loss, 2) if expected_loss > 0 else 0.0

    return {
        "target_price":      target_price,
        "stop_loss_price":   stop_loss_price,
        "take_profit_rate":  take_profit_rate,
        "stop_loss_rate":    stop_loss_rate,
        "max_holding_days":  max_holding_days,
        "expected_profit":   expected_profit,
        "expected_loss":     expected_loss,
        "risk_reward_ratio": risk_reward,
    }
