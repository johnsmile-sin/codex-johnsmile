"""
openclaw/commands.py v4  –  OpenClaw CLI 명령 인터페이스

Streamlit 없이 단독 실행 가능합니다.
실거래 주문 기능은 포함하지 않습니다.

⚠️  OpenClaw 권한 범위:
    - 신호 생성, 조회, 요약만 가능합니다.
    - 주문 승인 및 브로커 전송은 Streamlit 화면에서 사용자가 직접 수행합니다.
    - 긴급 중지 ON/OFF는 허용됩니다 (안전 제어 목적).

지원 명령 (v2 기존):
    today_candidates            스캐너 점수 상위 후보 종목 출력
    update_candidates           후보 재스캔 + 일봉 데이터 갱신 + Supabase 저장
    analyze_stock <종목명>      종합 리포트 (일봉 데이터 + 재무 3년 + 뉴스 포함)
    news_summary <종목명>       뉴스 감성 요약 (출처 표시)
    financial_summary <종목명>  재무 3년 지표 요약
    refresh_news <종목명>       Naver API 뉴스 갱신 + 저장
    refresh_prices <종목명>     FDR/Kiwoom 일봉 데이터 갱신 + 저장
    save_trade_note <종목명> <메모>  매매 메모 저장

지원 명령 (v4 신규):
    generate_signals            매수/매도 신호 생성 및 저장
    pending_orders              승인 대기 주문 후보 목록 조회
    risk_check                  시스템 리스크 상태 종합 점검
    safety_status               안전 설정 현황 출력
    emergency_stop_on           긴급 중지 활성화 (모든 주문 차단)
    emergency_stop_off          긴급 중지 해제
    order_logs [N]              최근 주문 로그 출력 (기본: 20건)

주의: 본 도구는 투자 참고용입니다. 수익을 보장하지 않습니다.
"""

from __future__ import annotations

import sys
import os
from datetime import date
from typing import Any

# Windows cp949 터미널 한글/이모지 출력 오류 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 패키지 루트 추가 (어디서 실행하든 import 가능)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv()


# ════════════════════════════════════════════════════════════════
# 상수
# ════════════════════════════════════════════════════════════════

_SENT_ICON = {"긍정": "📈", "중립": "📊", "부정": "📉"}

_DECISION_ICON = {
    "강한 관심": "🔥",
    "관심":     "👀",
    "관찰":     "🔍",
    "보류":     "⏸",
    "제외":     "❌",
}

_DECISION_ORDER = ["강한 관심", "관심", "관찰", "보류", "제외"]

_ORDER_KEYWORDS = {
    "매수주문", "매도주문", "place_order", "place-order",
    "order", "buy_order", "sell_order", "주문",
}

_DISCLAIMER = "본 정보는 투자 참고용이며 수익을 보장하지 않습니다. 실거래 주문을 권유하지 않습니다."


# ════════════════════════════════════════════════════════════════
# 출력 헬퍼
# ════════════════════════════════════════════════════════════════

def _hr(char: str = "=", width: int = 64) -> str:
    return char * width


def _section(title: str, char: str = "─") -> None:
    pad = max(0, 56 - len(title))
    print(f"\n{char * 3} {title} {char * pad}")


def _src_label(data_source: str) -> str:
    if "FinanceDataReader" in data_source or "Kiwoom" in data_source:
        return f"📡 실제 데이터 ({data_source})"
    return f"🎲 Mock 데이터"


def _fin_src_label(fin_source: str) -> str:
    return {"DART": "📡 DART (실제)", "CSV": "📂 CSV 입력"}.get(fin_source, "🎲 Mock")


def _news_src_label(source: str) -> str:
    return {"Naver": "📡 네이버 뉴스 API"}.get(source, "🎲 Mock")


# ════════════════════════════════════════════════════════════════
# API 상태 / Mock 모드 안내
# ════════════════════════════════════════════════════════════════

def _print_api_status() -> None:
    """현재 API 연결 상태를 한 줄로 출력."""
    import config as _cfg
    parts = []
    if _cfg.is_supabase_available():
        parts.append("Supabase ✅")
    else:
        parts.append("Supabase ❌")
    parts.append("DART ✅"  if _cfg.is_dart_available()  else "DART ❌")
    parts.append("Naver ✅" if _cfg.is_naver_available() else "Naver ❌")
    parts.append("키움 ✅"  if _cfg.is_kiwoom_available() else "키움 ❌")
    print(f"  API 상태: {' | '.join(parts)}")


def _print_mock_notice(context: str = "") -> None:
    """Mock 모드로 실행 중임을 안내."""
    note = f" ({context})" if context else ""
    print(f"  ⚠️  Mock 모드로 실행됩니다{note} — .env에 API 키를 설정하면 실제 데이터를 사용합니다.")


def _check_and_notice(dart: bool = False, naver: bool = False, supabase: bool = False) -> None:
    """필요한 API 키가 없으면 Mock 안내를 출력."""
    import config as _cfg
    missing = []
    if dart   and not _cfg.is_dart_available():   missing.append("DART_API_KEY (재무)")
    if naver  and not _cfg.is_naver_available():  missing.append("NAVER_CLIENT_ID/SECRET (뉴스)")
    if supabase and not _cfg.is_supabase_available(): missing.append("SUPABASE_URL/KEY (저장)")
    if missing:
        _print_mock_notice(", ".join(missing) + " 미설정")


# ════════════════════════════════════════════════════════════════
# CLI 전용 저장 헬퍼
# (db_service.py 는 Streamlit을 모듈 레벨에서 import하므로 CLI에서 직접 사용 불가)
# ════════════════════════════════════════════════════════════════

def _cli_save_candidate(data: dict) -> dict:
    """CLI 환경: Supabase 직접 저장 → 실패 시 mock_db_service 폴백."""
    try:
        from services.supabase_client import get_client, is_connected
        if is_connected():
            result = get_client().table("candidate_scores").upsert(
                data, on_conflict="stock_code,trade_date"
            ).execute()
            return {"saved": 1, "mode": "supabase"}
    except Exception:
        pass
    import services.mock_db_service as _mock
    return _mock.save_candidate_scores(data)


def _cli_save_trade(data: dict) -> dict:
    """CLI 환경: trade_journal Supabase 직접 저장 → mock 폴백."""
    try:
        from services.supabase_client import get_client, is_connected
        if is_connected():
            result = get_client().table("trade_journal").insert(data).execute()
            return result.data[0] if result.data else {}
    except Exception:
        pass
    import services.mock_db_service as _mock
    return _mock.save_trade_journal(data)


# ════════════════════════════════════════════════════════════════
# 공통: 종목 검색
# ════════════════════════════════════════════════════════════════

def _find_stock(name_or_code: str) -> tuple[Any, Any] | None:
    """종목명(부분 일치) 또는 코드로 (market_row, score_row) 반환. 없으면 None."""
    from services.market_data import get_market_data
    from strategy.scanner import scan

    market_df = get_market_data()
    scored_df = scan(market_df)

    mask = (
        market_df["stock_name"].str.contains(name_or_code, na=False, regex=False)
        | (market_df["stock_code"] == name_or_code)
    )
    match = market_df[mask]
    if match.empty:
        return None

    mrow = match.iloc[0]
    code = str(mrow["stock_code"])
    srows = scored_df[scored_df["stock_code"] == code]
    if srows.empty:
        return None
    return mrow, srows.iloc[0]


def _print_not_found(name_or_code: str) -> None:
    print(f"\n❌ '{name_or_code}' 종목을 찾을 수 없습니다.")
    print("  예시: 삼성전자, SK하이닉스, NAVER, 현대차, LG화학, 카카오")
    print("  코드: 005930, 000660, 035420\n")


# ════════════════════════════════════════════════════════════════
# 명령 1: today_candidates
# ════════════════════════════════════════════════════════════════

def cmd_today_candidates(n: int = 10) -> None:
    """
    스캐너 점수 상위 N개 후보 종목을 출력합니다.

    python -m openclaw.commands today_candidates [N]
    """
    from services.market_data import get_market_data
    from strategy.scanner import scan

    print(f"\n  ⏳ 데이터 로딩 중...")
    market_df = get_market_data()
    scored_df = scan(market_df)

    data_source = market_df["data_source"].iloc[0] if "data_source" in market_df.columns else "Mock"
    ref_date    = market_df["ref_date"].iloc[0]    if "ref_date"    in market_df.columns else str(date.today())

    merged = scored_df.merge(
        market_df[["stock_code", "market", "sector",
                   "current_price", "change_rate", "trading_value", "news_count",
                   "data_source", "ref_date"]],
        on="stock_code", how="left",
    )
    top = merged.nlargest(n, "score")

    print()
    print(_hr())
    print(f"  📈  오늘의 후보 종목 TOP {n}   ({date.today()})")
    print(f"  데이터: {_src_label(data_source)}  |  기준일: {ref_date}")
    _print_api_status()
    print(_hr())

    for rank, (_, row) in enumerate(top.iterrows(), 1):
        decision = row["decision"]
        score    = int(row["score"])
        chg      = float(row["change_rate"])
        chg_str  = f"{chg:+.2f}%"
        tv_str   = f"{float(row['trading_value']):.0f}억"
        dq       = str(row.get("data_quality", "Mock"))
        icon     = _DECISION_ICON.get(decision, "")

        print(
            f"  {rank:>2}. {icon} [{decision}] {row['stock_name']}"
            f"({row['stock_code']})  {score}점"
            f"  {chg_str}  거래대금 {tv_str}  뉴스 {int(row['news_count'])}건"
            f"  [{dq}]"
        )
        reasons = row["reasons"]
        risks   = row["risks"]
        if reasons:
            print(f"       ✅ " + " / ".join(reasons[:2]))
        if risks:
            print(f"       ⚠️  " + str(risks[0]))

    print(_hr())

    # 5단계 판단 분포
    counts = merged["decision"].value_counts().to_dict()
    dist   = "  ".join(
        f"{_DECISION_ICON.get(k,'')} {k} {counts.get(k,0)}개"
        for k in _DECISION_ORDER
        if counts.get(k, 0) > 0
    )
    print(f"  판단 분포 (전체 {len(merged)}개): {dist}")

    # 데이터 품질 분포
    if "data_quality" in scored_df.columns:
        dq_dist = scored_df["data_quality"].value_counts().to_dict()
        dq_str  = "  ".join(f"{k} {v}개" for k, v in dq_dist.items())
        print(f"  데이터 품질 분포: {dq_str}")

    print(f"  ※ {_DISCLAIMER}")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# 명령 2: update_candidates
# ════════════════════════════════════════════════════════════════

def cmd_update_candidates() -> None:
    """
    후보 종목 재스캔, 일봉 데이터 갱신, Supabase 저장을 수행합니다.

    python -m openclaw.commands update_candidates
    """
    from services.market_data import get_market_data
    from strategy.scanner import scan
    from services.price_service import update_daily_prices_for_candidates

    _check_and_notice(supabase=True)

    print()
    print(_hr())
    print(f"  🔄  후보 업데이트  ({date.today()})")
    print(_hr())

    # ── 1. 스캐너 재실행 ─────────────────────────────────────
    print("  [1/3] 시장 데이터 로딩 + 스캐너 재실행...")
    market_df = get_market_data()
    scored_df = scan(market_df)

    data_source = market_df["data_source"].iloc[0] if "data_source" in market_df.columns else "Mock"
    ref_date    = market_df["ref_date"].iloc[0]    if "ref_date"    in market_df.columns else str(date.today())
    print(f"       후보 {len(scored_df)}개 | 데이터: {_src_label(data_source)} | 기준일: {ref_date}")

    counts = scored_df["decision"].value_counts().to_dict()
    for label in _DECISION_ORDER:
        cnt = counts.get(label, 0)
        if cnt > 0:
            print(f"       {_DECISION_ICON.get(label,'')} {label}: {cnt}개")

    # ── 2. 일봉 데이터 갱신 ──────────────────────────────────
    print("  [2/3] 일봉 데이터 갱신...")
    candidates = scored_df[["stock_code", "stock_name"]].to_dict("records")
    price_result = update_daily_prices_for_candidates(candidates)
    print(
        f"       완료: {price_result['success']}/{price_result['total']}종목 성공"
        + (f"  실패: {price_result['failed']}개" if price_result["failed"] else "")
    )

    # ── 3. 점수 Supabase 저장 ────────────────────────────────
    print("  [3/3] 스캐너 점수 저장...")
    today = str(date.today())
    merged = scored_df.merge(
        market_df[["stock_code", "stock_name"]],
        on="stock_code", how="left",
        suffixes=("", "_mkt"),
    )
    saved = failed = 0
    for _, row in merged.iterrows():
        try:
            _cli_save_candidate({
                "stock_code": str(row["stock_code"]),
                "stock_name": str(row.get("stock_name", "")),
                "score":      float(row["score"]),
                "decision":   str(row["decision"]),
                "reasons":    " / ".join(row["reasons"]) if row["reasons"] else "",
                "risks":      " / ".join(row["risks"])   if row["risks"]   else "",
                "trade_date": today,
            })
            saved += 1
        except Exception:
            failed += 1
    print(f"       저장 완료: {saved}건" + (f"  실패: {failed}건" if failed else ""))

    print(_hr())
    print(f"  ✅ 후보 업데이트 완료")
    print(f"  ※ {_DISCLAIMER}")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# 명령 3: analyze_stock
# ════════════════════════════════════════════════════════════════

def cmd_analyze_stock(name_or_code: str) -> None:
    """
    종목 종합 리포트를 출력합니다 (일봉 데이터 + 재무 3년 + 뉴스 포함).

    python -m openclaw.commands analyze_stock <종목명 또는 코드>
    """
    from services.news_data import get_news_for_stock
    from services.financial_data import get_financial_metrics
    from services.price_service import fetch_daily_prices
    from analysis.stock_report import generate_report, format_report_text

    _check_and_notice(dart=True, naver=True)

    result = _find_stock(name_or_code)
    if result is None:
        _print_not_found(name_or_code)
        return

    mrow, srow = result
    code = str(mrow["stock_code"])
    name = str(mrow["stock_name"])

    print(f"\n  ⏳ {name} ({code}) 분석 중...")

    news_items    = get_news_for_stock(stock_code=code, stock_name=name)
    fin_metrics   = get_financial_metrics(code, name)
    price_history = fetch_daily_prices(code, days=60)

    print(f"  일봉 {len(price_history)}일치 | 재무 {len(fin_metrics['years'])}년 ({fin_metrics['fin_source']}) | 뉴스 {len(news_items)}건")

    report = generate_report(
        mrow, srow, news_items,
        fin_source=fin_metrics["fin_source"],
        financial_years=fin_metrics["years"],
        price_history=price_history if not price_history.empty else None,
    )
    print()
    print(format_report_text(report))


# ════════════════════════════════════════════════════════════════
# 명령 4: news_summary
# ════════════════════════════════════════════════════════════════

def cmd_news_summary(name_or_code: str) -> None:
    """
    종목 뉴스 감성을 요약합니다 (출처 표시).

    python -m openclaw.commands news_summary <종목명 또는 코드>
    """
    from services.news_data import get_news_for_stock, summarize_news_sentiment

    _check_and_notice(naver=True)

    result = _find_stock(name_or_code)
    if result is None:
        _print_not_found(name_or_code)
        return

    mrow, _ = result
    code    = str(mrow["stock_code"])
    name    = str(mrow["stock_name"])

    news_items = get_news_for_stock(stock_code=code, stock_name=name)
    summary    = summarize_news_sentiment(news_items)
    total      = summary["합계"]
    news_src   = summary.get("출처", "Mock")

    print()
    print(_hr())
    print(f"  📰  {name} ({code})  뉴스 감성 요약")
    print(f"  출처: {_news_src_label(news_src)}  |  기준일: {date.today()}")
    print(_hr())

    if total == 0:
        print("  관련 뉴스가 없습니다.")
        print(_hr())
        print()
        return

    pos     = summary["긍정"]
    neu     = summary["중립"]
    neg     = summary["부정"]
    pos_pct = round(pos / total * 100)
    neu_pct = round(neu / total * 100)
    neg_pct = round(neg / total * 100)

    print(
        f"  전체: {total}건  |  📈 긍정 {pos}건 ({pos_pct}%)  "
        f"📊 중립 {neu}건 ({neu_pct}%)  📉 부정 {neg}건 ({neg_pct}%)"
    )

    # 감성 막대 (32칸)
    W = 32
    p_w = round(W * pos / total)
    n_w = round(W * neg / total)
    u_w = max(0, W - p_w - n_w)
    print(f"  감성 막대: 긍정[{'█' * p_w}{'░' * u_w}{'█' * n_w}]부정")

    # 대표 감성
    dominant = summary.get("대표_감성", "중립")
    if pos_pct >= 50:
        verdict = "긍정 우위 → 시장 분위기 양호"
    elif neg_pct >= 40:
        verdict = "부정 우위 → 주의 필요"
    else:
        verdict = "중립 → 추세 확인 후 판단"
    print(f"  대표 감성: {dominant}  |  종합: {verdict}")

    _section("뉴스 목록 (최신순)", "─")
    for item in sorted(news_items, key=lambda x: x.get("news_date", ""), reverse=True):
        sent   = item.get("sentiment", "중립")
        icon   = _SENT_ICON.get(sent, "📊")
        stars  = "★" * item.get("impact_score", 3) + "☆" * (5 - item.get("impact_score", 3))
        src    = item.get("source", "Mock")
        src_tag = f"[{src}]" if src else ""
        print(
            f"  {icon} [{sent:<2}] {item.get('news_date', '')}  "
            f"{item['title'][:50]}  {stars} {src_tag}"
        )

    print()
    print(_hr())
    print(f"  ※ {_DISCLAIMER}")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# 명령 5: financial_summary
# ════════════════════════════════════════════════════════════════

def cmd_financial_summary(name_or_code: str) -> None:
    """
    종목 재무 3년 지표를 요약합니다 (DART 또는 Mock).

    python -m openclaw.commands financial_summary <종목명 또는 코드>
    """
    from services.financial_data import get_financial_metrics

    _check_and_notice(dart=True)

    result = _find_stock(name_or_code)
    if result is None:
        _print_not_found(name_or_code)
        return

    mrow, srow = result
    code = str(mrow["stock_code"])
    name = str(mrow["stock_name"])

    print(f"\n  ⏳ {name} ({code}) 재무 데이터 조회 중...")
    metrics    = get_financial_metrics(code, name)
    fin_source = metrics["fin_source"]
    years      = metrics["years"]
    latest     = metrics["latest"]

    print()
    print(_hr())
    print(f"  💰  {name} ({code})  재무 3년 요약")
    print(f"  출처: {_fin_src_label(fin_source)}  |  기준일: {date.today()}")
    print(_hr())

    # 최신 지표 한눈에
    print(f"  [최신] PER {latest['per']:.1f}배  PBR {latest['pbr']:.2f}배  "
          f"ROE {latest['roe']:.1f}%  부채비율 {latest['debt_ratio']:.0f}%")
    if latest.get("current_ratio", 0) > 0:
        print(f"         유동비율 {latest['current_ratio']:.0f}%  "
              f"영업이익률 {latest.get('operating_margin', 0):.1f}%")

    # 재무 리스크
    risks = []
    if latest["per"] < 0:             risks.append(f"PER {latest['per']:.1f}배 — 적자")
    if latest["roe"] < 0:             risks.append(f"ROE {latest['roe']:.1f}% — 적자")
    if latest["debt_ratio"] >= 200:   risks.append(f"부채비율 {latest['debt_ratio']:.0f}% — 200% 초과")
    if latest["per"] > 50:            risks.append(f"PER {latest['per']:.1f}배 — 고평가 구간")
    if risks:
        for r in risks:
            print(f"  ⚠️  재무 리스크: {r}")
    else:
        print("  ✅ 주요 재무 지표 정상 범위")

    _section("연도별 추이", "─")

    # 헤더
    col_w = [6, 12, 12, 8, 8, 8, 8]
    headers = ["연도", "매출(억)", "영업이익(억)", "영업이익률", "ROE", "부채비율", "유동비율"]
    header_line = "  " + "  ".join(h.ljust(w) for h, w in zip(headers, col_w))
    print(header_line)
    print("  " + "─" * (sum(col_w) + len(col_w) * 2))

    for yr in years[:3]:
        row_vals = [
            str(yr.get("fiscal_year", "")),
            f"{yr.get('revenue', 0):>10,.0f}",
            f"{yr.get('operating_profit', 0):>10,.0f}",
            f"{yr.get('operating_margin', 0):>6.1f}%",
            f"{yr.get('roe', 0):>5.1f}%",
            f"{yr.get('debt_ratio', 0):>5.0f}%",
            f"{yr.get('current_ratio', 0):>5.0f}%",
        ]
        print("  " + "  ".join(v.ljust(w) for v, w in zip(row_vals, col_w)))

    print()
    print(_hr())
    print(f"  ※ {_DISCLAIMER}")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# 명령 6: refresh_news
# ════════════════════════════════════════════════════════════════

def cmd_refresh_news(name_or_code: str) -> None:
    """
    Naver API로 뉴스를 갱신하고 Supabase에 저장합니다.

    python -m openclaw.commands refresh_news <종목명 또는 코드>
    """
    from services.news_data import fetch_news_from_naver, save_news_to_supabase

    _check_and_notice(naver=True, supabase=True)

    result = _find_stock(name_or_code)
    if result is None:
        _print_not_found(name_or_code)
        return

    mrow, _ = result
    code = str(mrow["stock_code"])
    name = str(mrow["stock_name"])

    print()
    print(_hr())
    print(f"  📡  {name} ({code})  뉴스 갱신")
    print(f"  기준일: {date.today()}")
    print(_hr())
    print(f"  ⏳ Naver API 조회 중 (최근 30일, 최대 20건)...")

    items = fetch_news_from_naver(name, days=30, max_items=20, stock_code=code)

    if not items:
        print("  ⚠️  실제 뉴스를 가져오지 못했습니다.")
        print("     NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 설정 여부를 확인하세요.")
        print("     Mock 데이터로 대체됩니다.")
        from services.news_data import get_mock_news
        items = get_mock_news(stock_code=code)
        src_note = "Mock 데이터 (Naver API 키 미설정)"
    else:
        src_note = f"네이버 뉴스 API ({len(items)}건 수신)"

    # 감성 집계
    pos = sum(1 for n in items if n.get("sentiment") == "긍정")
    neu = sum(1 for n in items if n.get("sentiment") == "중립")
    neg = sum(1 for n in items if n.get("sentiment") == "부정")
    print(f"  수신: {len(items)}건  📈 긍정 {pos}  📊 중립 {neu}  📉 부정 {neg}")
    print(f"  출처: {src_note}")

    # 저장
    print(f"  ⏳ Supabase 저장 중...")
    save_result = save_news_to_supabase(items)
    if save_result.get("error"):
        print(f"  ⚠️  저장 실패: {save_result['error']}")
        print("     메모리에는 캐시됩니다 (앱 재시작 시 초기화).")
    else:
        print(f"  ✅ {save_result.get('saved', 0)}건 저장 완료")

    _section("최신 뉴스 5건", "─")
    for item in sorted(items, key=lambda x: x.get("news_date", ""), reverse=True)[:5]:
        sent  = item.get("sentiment", "중립")
        icon  = _SENT_ICON.get(sent, "📊")
        stars = "★" * item.get("impact_score", 3) + "☆" * (5 - item.get("impact_score", 3))
        print(
            f"  {icon} [{sent:<2}] {item.get('news_date', '')}  "
            f"{item['title'][:55]}  {stars}"
        )

    print()
    print(_hr())
    print(f"  ※ {_DISCLAIMER}")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# 명령 7: refresh_prices
# ════════════════════════════════════════════════════════════════

def cmd_refresh_prices(name_or_code: str) -> None:
    """
    FDR/Kiwoom 일봉 데이터를 갱신하고 저장합니다.

    python -m openclaw.commands refresh_prices <종목명 또는 코드>
    """
    from services.price_service import fetch_daily_prices, save_daily_prices

    _check_and_notice(supabase=True)

    result = _find_stock(name_or_code)
    if result is None:
        _print_not_found(name_or_code)
        return

    mrow, srow = result
    code = str(mrow["stock_code"])
    name = str(mrow["stock_name"])

    print()
    print(_hr())
    print(f"  📈  {name} ({code})  일봉 데이터 갱신")
    print(f"  기준일: {date.today()}")
    print(_hr())
    print(f"  ⏳ 일봉 데이터 다운로드 중 (최근 120일)...")

    df = fetch_daily_prices(code, days=120)

    if df.empty:
        print("  ⚠️  일봉 데이터를 가져오지 못했습니다.")
        print("     FinanceDataReader 설치 여부를 확인하세요: pip install finance-datareader")
        print(_hr())
        print()
        return

    # 데이터 출처 판단
    cols = [c.lower() for c in df.columns]
    has_ohlc = all(c in cols for c in ["open", "high", "low", "close"])
    has_ma   = all(c in cols for c in ["ma5", "ma20", "ma60"])
    has_rsi  = "rsi14" in cols
    data_src = str(mrow.get("data_source", "Mock"))
    src_note = _src_label(data_src)

    print(f"  수신: {len(df)}일치  OHLC: {'✅' if has_ohlc else '❌'}  "
          f"MA: {'✅' if has_ma else '❌'}  RSI: {'✅' if has_rsi else '❌'}")

    # 최근 5일 요약
    _section("최근 5일 종가", "─")
    df_show = df.copy()
    df_show.columns = [c.lower() for c in df_show.columns]
    if "date" in df_show.columns:
        df_show = df_show.sort_values("date", ascending=False).head(5)
    else:
        df_show = df_show.tail(5).iloc[::-1]

    for _, r in df_show.iterrows():
        dt  = str(r.get("date", ""))[:10]
        cl  = int(r.get("close", 0))
        op  = int(r.get("open",  cl))
        vol = int(r.get("volume", 0))
        chg_pct = float(r.get("change_rate", 0))
        arrow   = "▲" if chg_pct > 0 else ("▼" if chg_pct < 0 else "－")
        print(f"  {dt}  종가 {cl:>8,}원  {arrow}{abs(chg_pct):.2f}%  거래량 {vol:>12,}주")

    # 기술 지표 최신값
    latest = df_show.iloc[0] if len(df_show) > 0 else None
    if latest is not None and has_ma and has_rsi:
        _section("현재 기술적 지표", "─")
        close_v  = float(latest.get("close", 0))
        ma5_v    = float(latest.get("ma5",   close_v))
        ma20_v   = float(latest.get("ma20",  close_v))
        ma60_v   = float(latest.get("ma60",  close_v))
        rsi_v    = float(latest.get("rsi14", 50))
        aligned  = "✅ 정배열" if close_v > ma5_v > ma20_v else "❌ 역배열/혼재"
        rsi_stat = "과매수(주의)" if rsi_v >= 70 else ("과매도(반등 가능)" if rsi_v <= 30 else "정상 구간")
        print(f"  MA5 {int(ma5_v):,}원  MA20 {int(ma20_v):,}원  MA60 {int(ma60_v):,}원  {aligned}")
        print(f"  RSI(14): {rsi_v:.1f}  →  {rsi_stat}")

    # 저장
    print(f"\n  ⏳ 데이터 저장 중...")
    save_result = save_daily_prices(code, df)
    if save_result.get("error"):
        print(f"  ⚠️  저장 실패: {save_result['error']}")
        print("     메모리에는 캐시됩니다.")
    else:
        mode = save_result.get("mode", "unknown")
        rows = save_result.get("saved", 0)
        mode_label = "Supabase" if mode == "supabase" else "메모리 캐시"
        print(f"  ✅ {rows}건 저장 완료  ({mode_label})")
    print(f"  출처: {src_note}")

    print()
    print(_hr())
    print(f"  ※ {_DISCLAIMER}")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# 명령 8: save_trade_note  (v1 유지)
# ════════════════════════════════════════════════════════════════

def cmd_save_trade_note(name_or_code: str, note: str) -> None:
    """
    종목 메모를 매매일지에 저장합니다.

    python -m openclaw.commands save_trade_note <종목명> "<메모>"
    """
    if not note.strip():
        print("\n❌ 메모 내용을 입력하세요.")
        print('  사용법: save_trade_note <종목명> "<메모 내용>"\n')
        return

    result = _find_stock(name_or_code)
    if result is None:
        _print_not_found(name_or_code)
        return

    mrow, srow = result
    code  = str(mrow["stock_code"])
    name  = str(mrow["stock_name"])
    today = str(date.today())

    record = _cli_save_trade({
        "trade_date":  today,
        "stock_code":  code,
        "stock_name":  name,
        "action":      "메모",
        "entry_price": 0,
        "exit_price":  None,
        "quantity":    0,
        "reason":      note.strip(),
        "result_memo": (
            f"OpenClaw CLI  |  "
            f"스캐너 {int(srow['score'])}점 / {srow['decision']}"
        ),
        "return_rate": None,
    })

    print()
    print(_hr())
    print("  ✅ 매매 메모 저장 완료")
    print(_hr("-"))
    print(f"  종목    : {name} ({code})")
    print(f"  날짜    : {today}")
    print(f"  메모    : {note.strip()}")
    print(f"  스캐너  : {int(srow['score'])}점 / {srow['decision']}")
    rec_id = record.get("id", "-") if isinstance(record, dict) else "-"
    print(f"  저장 ID : {rec_id}")
    print(_hr())
    print()


def cmd_virtual_summary() -> None:
    from services.market_data import get_market_data
    from services.virtual_trading import get_portfolio_snapshot, summarize_strategy_performance

    market_df = get_market_data()
    snapshot = get_portfolio_snapshot(market_df)
    positions = snapshot["positions"]
    perf = summarize_strategy_performance(market_df)

    print()
    print(_hr())
    print("  💼 모의투자 요약")
    print(_hr("-"))
    print(f"  초기 자금  : {snapshot['initial_cash']:,.0f}원")
    print(f"  현금       : {snapshot['cash']:,.0f}원")
    print(f"  평가금액   : {snapshot['market_value']:,.0f}원")
    print(f"  평가손익   : {snapshot['unrealized_pnl']:+,.0f}원")
    print(f"  총 수익률  : {snapshot['total_return']:+.2f}%")
    print(f"  가상 주문  : {len(snapshot['orders'])}건")
    print(_hr("-"))

    if positions.empty:
        print("  보유 중인 가상 포지션이 없습니다.")
    else:
        print("  보유 포지션")
        for _, row in positions.iterrows():
            print(
                f"  - {row['stock_name']}({row['stock_code']}) "
                f"{int(row['quantity'])}주 / 수익률 {float(row['return_rate']):+.2f}%"
            )

    if not perf.empty:
        print(_hr("-"))
        print("  전략별 성과")
        for _, row in perf.iterrows():
            print(
                f"  - {row['strategy_name']}: 주문 {int(row['orders'])}건, "
                f"보유 {int(row['open_positions'])}개, "
                f"수익률 {float(row['return_rate']):+.2f}%"
            )

    print(_hr())
    print("  ※ 실거래 주문이 아니며 virtual_orders 저장소 기준입니다.")
    print()


def cmd_virtual_run() -> None:
    from services.market_data import get_market_data
    from strategy.scanner import scan
    from services.virtual_trading import run_strategy_once

    market_df = get_market_data()
    scored_df = scan(market_df)
    result = run_strategy_once(market_df, scored_df)

    print()
    print(_hr())
    print("  ⚙️ 모의투자 전략 1회 실행")
    print(_hr("-"))
    print(f"  전략명       : {result['strategy_name']}")
    print(f"  생성 주문 수 : {result['created_count']}건")
    for order in result["created"]:
        side = "가상 매수" if order["side"] == "BUY" else "가상 매도"
        print(
            f"  - {side}: {order['stock_name']}({order['stock_code']}) "
            f"{order['quantity']}주 @ {float(order['price']):,.0f}원"
        )
    if not result["created"]:
        print("  생성된 가상 주문이 없습니다.")
    print(_hr())
    print("  ※ 키움 주문 API는 호출하지 않았습니다.")
    print()


def cmd_virtual_backtest(days: int = 20) -> None:
    from services.market_data import get_market_data
    from strategy.scanner import scan
    from services.virtual_trading import run_light_backtest

    market_df = get_market_data()
    scored_df = scan(market_df)
    result = run_light_backtest(scored_df, days=days)

    print()
    print(_hr())
    print(f"  🧪 경량 백테스트 ({days}거래일)")
    print(_hr("-"))
    if result.empty:
        print("  백테스트할 후보 종목이 없습니다.")
        print(_hr())
        return

    print(f"  대상 종목   : {len(result)}개")
    print(f"  평균 수익률 : {float(result['return_rate'].mean()):+.2f}%")
    print(f"  승률        : {float((result['return_rate'] > 0).mean() * 100):.1f}%")
    print(_hr("-"))
    for _, row in result.iterrows():
        print(
            f"  - {row['stock_name']}({row['stock_code']}) "
            f"{int(row['score'])}점 / {row['decision']} / "
            f"{float(row['return_rate']):+.2f}% / {row['result']}"
        )
    print(_hr())
    print("  ※ 단순 검증용 경량 백테스트이며 수익을 보장하지 않습니다.")
    print()


# ════════════════════════════════════════════════════════════════
# 비활성화 — 실거래 주문 (절대 활성화 금지)
# ════════════════════════════════════════════════════════════════

def cmd_virtual_portfolio() -> None:
    """3차 CLI: 가상 포트폴리오 현황을 한국어 텍스트로 출력한다."""
    from services.market_data import get_market_data
    from services.virtual_trading import get_portfolio_snapshot

    market_df = get_market_data()
    snapshot = get_portfolio_snapshot(market_df)
    positions = snapshot["positions"]
    orders = snapshot["orders"]

    print()
    print(_hr())
    print("  💼 가상 포트폴리오 현황")
    print(_hr("-"))
    print("  ※ 실제 주문 기능은 없습니다. 모든 주문은 가상 주문 저장소에만 기록됩니다.")
    print(f"  초기 자금      : {snapshot['initial_cash']:,.0f}원")
    print(f"  현금 잔고      : {snapshot['cash']:,.0f}원")
    print(f"  보유 평가금액  : {snapshot['market_value']:,.0f}원")
    print(f"  평가손익       : {snapshot['unrealized_pnl']:+,.0f}원")
    print(f"  실현손익       : {snapshot['realized_pnl']:+,.0f}원")
    print(f"  총자산         : {snapshot['total_value']:,.0f}원")
    print(f"  총 수익률      : {snapshot['total_return']:+.2f}%")
    print(f"  가상 주문 수   : {len(orders)}건")
    print(_hr("-"))
    if positions.empty:
        print("  현재 보유 중인 가상 포지션이 없습니다.")
    else:
        print("  보유 포지션")
        for _, row in positions.iterrows():
            print(
                f"  - {row['stock_name']}({row['stock_code']}) "
                f"{int(row['quantity'])}주 | 평균단가 {float(row['avg_price']):,.0f}원 | "
                f"현재가 {float(row['current_price']):,.0f}원 | "
                f"평가손익 {float(row['unrealized_pnl']):+,.0f}원 | "
                f"수익률 {float(row['return_rate']):+.2f}%"
            )
    print(_hr())
    print("  안내: 이 결과는 모의매매 기준이며 실거래 주문을 실행하지 않습니다.")
    print()


def cmd_run_virtual_trading() -> None:
    """3차 CLI: 실제 주문 없이 가상 주문만 생성하는 전략 1회 실행."""
    from services.market_data import get_market_data
    from strategy.scanner import scan
    from services.virtual_trading import run_strategy_once

    market_df = get_market_data()
    scored_df = scan(market_df)
    result = run_strategy_once(market_df, scored_df)

    print()
    print(_hr())
    print("  ▶ 모의매매 전략 1회 실행")
    print(_hr("-"))
    print("  ※ 실제 주문 기능은 없습니다. run_virtual_trading은 가상 주문만 생성합니다.")
    print(f"  전략명        : {result['strategy_name']}")
    print(f"  생성 주문 수  : {result['created_count']}건")
    if result["created"]:
        print("  생성된 가상 주문")
        for order in result["created"]:
            side = "가상 매수" if order["side"] == "BUY" else "가상 매도"
            print(
                f"  - {side}: {order['stock_name']}({order['stock_code']}) "
                f"{int(order['quantity'])}주 @ {float(order['price']):,.0f}원 "
                f"({order.get('status', 'CLOSED')})"
            )
    else:
        print("  이번 실행에서 생성된 가상 주문은 없습니다.")
    skipped = result.get("skipped", [])
    if skipped:
        print("  제외 사유")
        for item in skipped[:10]:
            print(f"  - {item}")
    print(_hr())
    print("  안내: 키움/증권사 주문 API는 호출하지 않았습니다.")
    print()


def cmd_strategy_performance() -> None:
    """3차 CLI: 전략 성과 요약. 승률, 누적 수익률, 최대 낙폭 포함."""
    from analysis.performance_analyzer import summarize_performance

    summary = summarize_performance()
    total = summary["total"]
    detail_list = summary["detail_list"]

    print()
    print(_hr())
    print("  📊 전략 성과 요약")
    print(_hr("-"))
    print("  ※ 실제 주문 기능은 없습니다. 모의매매와 백테스트 기록만 분석합니다.")
    print(f"  총 거래 수     : {int(total.get('total_trades', 0))}건")
    print(f"  승률           : {float(total.get('win_rate', 0.0)):.2f}%")
    print(f"  누적 수익률    : {float(total.get('total_return_rate', 0.0)):+.2f}%")
    print(f"  최대 낙폭      : {float(total.get('max_drawdown', 0.0)):.2f}%")
    print(f"  평균 수익률    : {float(total.get('avg_return_rate', 0.0)):+.2f}%")
    print(f"  손익 합계      : {float(total.get('total_profit_loss', 0.0)):+,.0f}원")
    print(f"  수익비         : {float(total.get('profit_factor', 0.0)):.2f}")
    print(_hr("-"))
    if not detail_list:
        print("  아직 청산된 모의매매 포지션이 없어 전략별 성과가 없습니다.")
    else:
        print("  전략별 상세")
        for perf in detail_list:
            print(
                f"  - {perf['strategy_name']}: 거래 {int(perf.get('total_trades', 0))}건 | "
                f"승률 {float(perf.get('win_rate', 0.0)):.1f}% | "
                f"누적 수익률 {float(perf.get('total_return_rate', 0.0)):+.2f}% | "
                f"최대 낙폭 {float(perf.get('max_drawdown', 0.0)):.2f}%"
            )
    print(_hr())
    print("  안내: 성과 지표는 과거/가상 데이터 기준이며 수익을 보장하지 않습니다.")
    print()


def cmd_backtest_strategy(strategy_name: str) -> None:
    """3차 CLI: 지정 전략을 최근 180일 기준으로 경량 백테스트한다."""
    from datetime import timedelta
    from analysis.backtester import run_backtest

    end_date = date.today()
    start_date = end_date - timedelta(days=180)
    result = run_backtest(
        strategy_name=strategy_name,
        start_date=str(start_date),
        end_date=str(end_date),
        save_result=False,
    )

    print()
    print(_hr())
    print(f"  🧪 전략 백테스트: {strategy_name}")
    print(_hr("-"))
    print("  ※ 실제 주문 기능은 없습니다. 과거 데이터 기반 가상 검증만 수행합니다.")
    print(f"  기간           : {start_date} ~ {end_date}")
    print(f"  초기 자금      : {float(result['initial_cash']):,.0f}원")
    print(f"  최종 자산      : {float(result['final_asset']):,.0f}원")
    print(f"  총 거래 수     : {int(result['total_trades'])}건")
    print(f"  승률           : {float(result['win_rate']):.2f}%")
    print(f"  누적 수익률    : {float(result['total_return_rate']):+.2f}%")
    print(f"  최대 낙폭      : {float(result['max_drawdown']):.2f}%")
    print(f"  평균 수익률    : {float(result.get('avg_return_rate', 0.0)):+.2f}%")
    print(f"  수익비         : {float(result.get('profit_factor', 0.0)):.2f}")
    trades_df = result.get("trades_df")
    if trades_df is not None and not trades_df.empty:
        print(_hr("-"))
        print("  최근 거래 예시")
        for _, row in trades_df.tail(10).iterrows():
            print(
                f"  - {row.get('stock_name', '')}({row.get('stock_code', '')}) | "
                f"{row.get('entry_date', '')} 진입 → {row.get('exit_date', '')} 청산 | "
                f"{float(row.get('return_rate', 0.0)):+.2f}% | {row.get('exit_reason', '')}"
            )
    else:
        print("  해당 기간에 백테스트 거래가 발생하지 않았습니다.")
    print(_hr())
    print("  안내: 백테스트 결과는 실제 수익을 보장하지 않습니다.")
    print()


def cmd_risk_summary() -> None:
    """3차 CLI: 현재 모의매매 리스크 상태 요약."""
    from services.virtual_trading import get_portfolio_snapshot
    from services.market_data import get_market_data
    from strategy.risk_manager import (
        check_max_position_count,
        check_max_position_amount,
        check_daily_loss_limit,
        check_single_stock_ratio,
    )

    market_df = get_market_data()
    snapshot = get_portfolio_snapshot(market_df)
    positions = snapshot["positions"]
    sample_code = "005930"
    sample_amount = 1_000_000.0
    if not positions.empty:
        sample_code = str(positions.iloc[0]["stock_code"])

    checks = [
        ("최대 보유 종목 수", check_max_position_count()),
        ("종목별 최대 투자금", check_max_position_amount(sample_amount)),
        ("일일 손실 한도", check_daily_loss_limit()),
        ("단일 종목 비중", check_single_stock_ratio(sample_code, sample_amount, snapshot["total_value"])),
    ]

    print()
    print(_hr())
    print("  🛡 리스크 요약")
    print(_hr("-"))
    print("  ※ 실제 주문 기능은 없습니다. 가상 주문 전 리스크 조건만 점검합니다.")
    print(f"  총자산         : {snapshot['total_value']:,.0f}원")
    print(f"  현금 잔고      : {snapshot['cash']:,.0f}원")
    print(f"  보유 종목 수   : {0 if positions.empty else len(positions)}개")
    print(f"  점검 기준 금액 : {sample_amount:,.0f}원")
    print(_hr("-"))
    for name, result in checks:
        mark = "통과" if result.get("allowed") else "차단"
        print(f"  - {name}: {mark}")
        print(f"    {result.get('message', '')}")
    print(_hr())
    print("  안내: 리스크 점검은 모의매매 기준이며 실거래 주문을 실행하지 않습니다.")
    print()


# ════════════════════════════════════════════════════════════════
# v4 신규 명령 1: generate_signals
# ════════════════════════════════════════════════════════════════

def cmd_generate_signals() -> None:
    """
    스캐너 점수를 기반으로 매수/매도 신호를 생성하고 저장합니다.
    주문 생성은 하지 않으며 신호 생성까지만 수행합니다.

    python -m openclaw.commands generate_signals
    """
    from services.market_data import get_market_data
    from strategy.scanner import scan
    from strategy.signal_generator import (
        generate_buy_signals, generate_sell_signals,
        save_trade_signals, expire_old_signals,
    )
    from services.system_settings import get_system_settings

    settings = get_system_settings()
    e_stop   = settings.get("emergency_stop", False)
    mode     = settings.get("trading_mode", "analysis_only")

    print()
    print(_hr())
    print(f"  📡  신호 생성  ({date.today()})")
    print(f"  매매 모드: {mode}  |  긴급 중지: {'🔴 활성' if e_stop else '🟢 비활성'}")
    print(_hr())

    if e_stop:
        print("  🚨 긴급 중지 상태입니다. 신호 생성이 차단됩니다.")
        print("     emergency_stop_off 명령으로 긴급 중지를 해제하세요.")
        print(_hr())
        print()
        return

    print("  ⏳ 시장 데이터 로딩 중...")
    market_df = get_market_data()
    scored_df = scan(market_df)
    print(f"  스캐너 완료: {len(scored_df)}개 종목 분석")

    # 만료 처리
    print("  ⏳ 만료 신호 처리 중...")
    expire_result = expire_old_signals()
    expired_count = expire_result.get("expired", 0) if isinstance(expire_result, dict) else 0
    if expired_count > 0:
        print(f"  ⏰ 만료 신호 {expired_count}건 처리 완료")

    # 매수 신호 생성
    print("  ⏳ 매수 신호 생성 중...")
    buy_signals = generate_buy_signals(market_df, scored_df)

    # 매도 신호 생성
    print("  ⏳ 매도 신호 생성 중...")
    sell_signals = generate_sell_signals(market_df)

    all_signals = buy_signals + sell_signals

    if not all_signals:
        print("  ℹ️  생성된 신호가 없습니다.")
        print("     점수 기준 미달 또는 보유 종목 없음으로 인해 조건 불충족일 수 있습니다.")
        print(_hr())
        print()
        return

    # 저장
    print(f"  ⏳ 신호 {len(all_signals)}건 저장 중...")
    save_result = save_trade_signals(all_signals)
    saved_count = save_result.get("saved", len(all_signals)) if isinstance(save_result, dict) else len(all_signals)

    _section("생성된 신호 목록", "─")
    for sig in all_signals:
        sig_type = sig.get("signal_type", "매수")
        code     = sig.get("stock_code", "")
        name     = sig.get("stock_name", code)
        score    = sig.get("score", 0)
        decision = sig.get("decision", "")
        reason   = sig.get("signal_reason", "")
        icon     = "🟢" if sig_type == "매수" else "🔴"
        print(f"  {icon} [{sig_type}] {name}({code})  점수 {float(score):.0f}점  [{decision}]")
        if reason:
            print(f"       사유: {reason[:70]}")

    print(_hr("-"))
    print(f"  매수 신호: {len(buy_signals)}건  |  매도 신호: {len(sell_signals)}건  |  저장: {saved_count}건")
    print()
    print("  ⚠️  신호는 참고용입니다.")
    print("     주문 후보 생성은 Streamlit '✅ 주문 승인' 화면에서 진행하세요.")
    print(f"  ※ {_DISCLAIMER}")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# v4 신규 명령 2: pending_orders
# ════════════════════════════════════════════════════════════════

def cmd_pending_orders() -> None:
    """
    승인 대기 중인 주문 후보 목록을 출력합니다.
    주문 승인/전송은 Streamlit 화면에서만 가능합니다.

    python -m openclaw.commands pending_orders
    """
    from services.order_intent_service import get_order_intents

    print()
    print(_hr())
    print(f"  📋  승인 대기 주문 후보  ({date.today()})")
    print(_hr())

    try:
        intents = get_order_intents(approval_status="승인대기", limit=20)
    except Exception as e:
        intents = []
        print(f"  ⚠️  조회 실패: {e}")

    if not intents:
        print("  ℹ️  현재 승인 대기 중인 주문 후보가 없습니다.")
        print(_hr())
        print()
        return

    _section(f"승인 대기 {len(intents)}건", "─")
    for intent in intents:
        code      = intent.get("stock_code", "")
        name      = intent.get("stock_name", code)
        o_type    = intent.get("order_type", "매수")
        qty       = int(intent.get("quantity", 0))
        price     = float(intent.get("price", 0))
        amount    = float(intent.get("order_amount", qty * price))
        risk_st   = intent.get("risk_check_status", "미검사")
        risk_msg  = intent.get("risk_check_message", "")
        created   = str(intent.get("created_at", ""))[:16]
        o_icon    = "🟢" if o_type == "매수" else "🔴"
        risk_icon = {"통과": "✅", "차단": "🚫", "확인필요": "⚠️"}.get(risk_st, "❓")

        print(f"  {o_icon} [{o_type}] {name}({code})")
        print(f"       수량 {qty:,}주  |  단가 {int(price):,}원  |  금액 {int(amount):,.0f}원")
        print(f"       리스크: {risk_icon} {risk_st}  |  생성: {created}")
        if risk_st == "차단" and risk_msg:
            print(f"       ⛔ {risk_msg[:70]}")

    print(_hr("-"))
    print("  ⚠️  주문 승인 및 전송은 Streamlit '✅ 주문 승인' 화면에서 진행하세요.")
    print("     OpenClaw CLI에서는 주문 승인/전송을 지원하지 않습니다.")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# v4 신규 명령 3: risk_check
# ════════════════════════════════════════════════════════════════

def cmd_risk_check() -> None:
    """
    현재 시스템 리스크 상태를 종합 점검합니다.

    python -m openclaw.commands risk_check
    """
    from strategy.risk_manager import run_full_risk_check
    from services.system_settings import get_system_settings

    settings = get_system_settings()
    e_stop   = settings.get("emergency_stop", False)
    mode     = settings.get("trading_mode", "analysis_only")
    max_amt  = settings.get("max_order_amount", 1_000_000)
    max_loss = settings.get("max_daily_loss_rate", -3.0)
    max_pos  = settings.get("max_position_count", 5)

    print()
    print(_hr())
    print(f"  🛡  리스크 상태 점검  ({date.today()})")
    print(_hr())

    # 샘플 파라미터로 종합 리스크 검사 실행
    try:
        result = run_full_risk_check(
            stock_code="005930",
            order_amount=float(max_amt),
            order_type="매수",
            price_type="지정가",
            account_mode="paper",
        )
    except Exception as e:
        print(f"  ❌ 리스크 검사 실행 실패: {e}")
        print(_hr())
        print()
        return

    status   = result.get("status", "확인필요")
    message  = result.get("message", "")
    checks   = result.get("checks", [])
    blocked  = result.get("blocked_checks", [])
    warnings = result.get("warning_checks", [])

    status_icon = {"통과": "✅", "차단": "🚫", "확인필요": "⚠️"}.get(status, "❓")
    print(f"  종합 상태: {status_icon} {status}")
    if message:
        print(f"  메시지: {message}")

    _section("개별 검사 항목", "─")
    for chk in checks:
        chk_name = chk.get("name", "")
        chk_st   = chk.get("status", "")
        chk_msg  = chk.get("message", "")
        chk_icon = {"통과": "✅", "차단": "🚫", "확인필요": "⚠️"}.get(chk_st, "❓")
        print(f"  {chk_icon} {chk_name}: {chk_st}")
        if chk_msg:
            print(f"       {chk_msg[:70]}")

    _section("시스템 설정 요약", "─")
    print(f"  긴급 중지      : {'🔴 활성 (모든 주문 차단)' if e_stop else '🟢 비활성'}")
    print(f"  매매 모드      : {mode}")
    print(f"  실거래 허용    : ⛔ 항상 False (코드 레벨 고정)")
    print(f"  최대 주문 금액 : {int(max_amt):,.0f}원")
    print(f"  최대 손실 한도 : {float(max_loss):.1f}%")
    print(f"  최대 보유 종목 : {int(max_pos)}개")

    if blocked:
        print(_hr("-"))
        print(f"  🚫 차단 항목 {len(blocked)}개: {', '.join(str(b) for b in blocked)}")
    if warnings:
        print(f"  ⚠️  경고 항목 {len(warnings)}개: {', '.join(str(w) for w in warnings)}")

    print(_hr())
    print(f"  ※ {_DISCLAIMER}")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# v4 신규 명령 4: safety_status
# ════════════════════════════════════════════════════════════════

def cmd_safety_status() -> None:
    """
    현재 시스템 안전 설정 상태를 출력합니다.

    python -m openclaw.commands safety_status
    """
    from services.system_settings import get_system_settings

    s        = get_system_settings()
    e_stop   = s.get("emergency_stop", False)
    mode     = s.get("trading_mode", "analysis_only")
    manual   = s.get("require_manual_approval", True)
    max_amt  = s.get("max_order_amount", 1_000_000)
    max_loss = s.get("max_daily_loss_rate", -3.0)
    max_pos  = s.get("max_position_count", 5)
    src      = s.get("source", "default")
    updated  = str(s.get("updated_at", "-") or "-")[:19]

    mode_labels = {
        "analysis_only": "분석 전용 (신호 생성까지만, 주문 불가)",
        "paper_trading": "모의투자 (수동 승인 후 모의주문 가능)",
        "real_ready":    "실거래 준비 (실제 주문은 여전히 차단됨)",
    }

    print()
    print(_hr())
    print(f"  ⚙️  안전 설정 현황  ({date.today()})")
    print(f"  데이터 출처: {src}  |  최종 수정: {updated}")
    print(_hr())

    if e_stop:
        print("  🚨🚨🚨  긴급 중지 활성  🚨🚨🚨")
        print("  ⛔ 모든 주문 후보 생성 및 전송이 차단됩니다.")
        print()
    else:
        print("  🟢 긴급 중지: 비활성")
        print()

    print(f"  매매 모드      : {mode_labels.get(mode, mode)}")
    print(f"  실거래 허용    : ⛔ 항상 False (코드 레벨 고정, 변경 불가)")
    print(f"  수동 승인 필수 : {'✅ 예' if manual else '⚠️  아니오 (주의!)'}")
    print(f"  최대 주문 금액 : {int(max_amt):,.0f}원")
    print(f"  최대 손실 한도 : {float(max_loss):.1f}%")
    print(f"  최대 보유 종목 : {int(max_pos)}개")

    print(_hr("-"))
    print("  📌 안내:")
    print("     - 설정 변경은 Streamlit '⚙️ 안전 설정' 화면에서 진행하세요.")
    print("     - 긴급 중지 ON/OFF: emergency_stop_on / emergency_stop_off 명령 사용")
    print("     - 실거래 자동주문은 이 프로젝트에서 지원하지 않습니다.")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# v4 신규 명령 5: emergency_stop_on
# ════════════════════════════════════════════════════════════════

def cmd_emergency_stop_on() -> None:
    """
    긴급 중지를 활성화합니다. 모든 주문 후보 생성 및 전송이 차단됩니다.

    python -m openclaw.commands emergency_stop_on
    """
    from services.system_settings import set_emergency_stop, get_system_settings

    print()
    print(_hr())
    print("  🚨  긴급 중지 활성화")
    print(_hr())

    s = get_system_settings()
    if s.get("emergency_stop", False):
        print("  ℹ️  이미 긴급 중지가 활성화되어 있습니다.")
        print(_hr())
        print()
        return

    result = set_emergency_stop(True)
    ok = result.get("success", False) if isinstance(result, dict) else bool(result)

    if ok:
        print("  ✅ 긴급 중지 활성화 완료")
        print("  ⛔ 모든 주문 후보 생성 및 전송이 차단됩니다.")
        print("     해제하려면: python -m openclaw.commands emergency_stop_off")
    else:
        err = result.get("error", "알 수 없는 오류") if isinstance(result, dict) else "저장 실패"
        print(f"  ❌ 긴급 중지 활성화 실패: {err}")
        print("     data/system_settings.json 또는 Supabase 연결을 확인하세요.")

    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# v4 신규 명령 6: emergency_stop_off
# ════════════════════════════════════════════════════════════════

def cmd_emergency_stop_off() -> None:
    """
    긴급 중지를 해제합니다.

    python -m openclaw.commands emergency_stop_off
    """
    from services.system_settings import set_emergency_stop, get_system_settings

    print()
    print(_hr())
    print("  🟢  긴급 중지 해제")
    print(_hr())

    s = get_system_settings()
    if not s.get("emergency_stop", False):
        print("  ℹ️  현재 긴급 중지가 비활성 상태입니다. 변경할 필요가 없습니다.")
        print(_hr())
        print()
        return

    print("  ⚠️  긴급 중지를 해제하면 매매 모드에 따라 주문 후보 생성이 가능해집니다.")
    print("  진행하려면 Enter 를 누르세요. 취소하려면 Ctrl+C 를 누르세요.")
    try:
        input("  > ")
    except KeyboardInterrupt:
        print("\n  ↩️  취소되었습니다.")
        print(_hr())
        print()
        return

    result = set_emergency_stop(False)
    ok = result.get("success", False) if isinstance(result, dict) else bool(result)

    if ok:
        print("  ✅ 긴급 중지 해제 완료")
        mode = s.get("trading_mode", "analysis_only")
        print(f"  현재 매매 모드: {mode}")
        if mode == "analysis_only":
            print("  ℹ️  분석 전용 모드 — 주문 후보 생성은 여전히 불가합니다.")
        elif mode == "paper_trading":
            print("  ℹ️  모의투자 모드 — 주문 후보 생성 후 수동 승인이 필요합니다.")
        elif mode == "real_ready":
            print("  ℹ️  실거래 준비 모드 — 실제 주문 전송은 여전히 차단됩니다.")
    else:
        err = result.get("error", "알 수 없는 오류") if isinstance(result, dict) else "저장 실패"
        print(f"  ❌ 긴급 중지 해제 실패: {err}")
        print("     data/system_settings.json 또는 Supabase 연결을 확인하세요.")

    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# v4 신규 명령 7: order_logs
# ════════════════════════════════════════════════════════════════

def cmd_order_logs(n: int = 20) -> None:
    """
    최근 주문 로그를 출력합니다 (broker_orders + 실행 이벤트 로그).

    python -m openclaw.commands order_logs [N]
    """
    import json as _json
    from pathlib import Path as _Path

    _data_dir = _Path(_ROOT) / "data"
    _bo_file  = _data_dir / "broker_orders.json"
    _el_file  = _data_dir / "order_execution_logs.json"

    print()
    print(_hr())
    print(f"  📋  최근 주문 로그  ({date.today()})")
    print(_hr())

    # ── broker_orders ─────────────────────────────────────────
    broker_orders: list[dict] = []
    if _bo_file.exists():
        try:
            broker_orders = _json.loads(_bo_file.read_text(encoding="utf-8")) or []
        except Exception:
            pass

    if not broker_orders:
        try:
            from services.supabase_client import get_client, is_connected
            if is_connected():
                rows = (
                    get_client()
                    .table("broker_orders")
                    .select("*")
                    .order("created_at", desc=True)
                    .limit(n)
                    .execute()
                    .data or []
                )
                broker_orders = rows
        except Exception:
            pass

    _section(f"브로커 주문 (최근 {n}건)", "─")
    if not broker_orders:
        print("  ℹ️  주문 기록이 없습니다.")
    else:
        _bo_icon = {
            "전송대기": "⏳", "전송완료": "📤", "전량체결": "✅",
            "일부체결": "🔶", "취소": "❌", "실패": "💥",
        }
        for order in sorted(
            broker_orders,
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )[:n]:
            code      = order.get("stock_code", "")
            name      = order.get("stock_name", code)
            o_type    = order.get("order_type", "")
            qty       = int(order.get("quantity", 0))
            price     = float(order.get("price", 0))
            status    = order.get("order_status", "")
            mode      = order.get("account_mode", "")
            broker_no = order.get("broker_order_no", "-")
            created   = str(order.get("created_at", ""))[:16]
            s_icon    = _bo_icon.get(status, "❓")
            print(
                f"  {s_icon} [{status}] {o_type} {name}({code}) "
                f"{qty:,}주 @ {int(price):,}원"
            )
            print(f"       모드:{mode}  주문번호:{broker_no}  생성:{created}")

    # ── 실행 이벤트 로그 ──────────────────────────────────────
    exec_logs: list[dict] = []
    if _el_file.exists():
        try:
            exec_logs = _json.loads(_el_file.read_text(encoding="utf-8")) or []
        except Exception:
            pass

    if not exec_logs:
        try:
            from services.supabase_client import get_client, is_connected
            if is_connected():
                rows = (
                    get_client()
                    .table("order_execution_logs")
                    .select("*")
                    .order("created_at", desc=True)
                    .limit(min(n, 30))
                    .execute()
                    .data or []
                )
                exec_logs = rows
        except Exception:
            pass

    _section(f"실행 이벤트 로그 (최근 {min(n, 30)}건)", "─")
    _el_icon = {
        "ORDER_SENT":   "📤",
        "ORDER_FAILED": "💥",
        "CANCEL_SENT":  "🚫",
        "SEND_ATTEMPT": "⏳",
        "SEND_BLOCKED": "⛔",
        "STATUS_QUERY": "🔍",
        "CANCEL_FAILED":"⚠️",
    }
    if not exec_logs:
        print("  ℹ️  실행 이벤트 로그가 없습니다.")
    else:
        for log in sorted(
            exec_logs,
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )[:min(n, 30)]:
            evt    = log.get("event_type", "")
            msg    = log.get("message", "")
            logged = str(log.get("created_at", ""))[:16]
            e_icon = _el_icon.get(evt, "📝")
            print(f"  {e_icon} [{evt}] {logged}  {msg[:65]}")

    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# 텔레그램 명령
# ════════════════════════════════════════════════════════════════

def cmd_bot_start() -> None:
    """
    텔레그램 양방향 봇을 시작합니다 (blocking polling).

    openclaw bot_start
    """
    from services.telegram_bot import run_bot
    run_bot()


def cmd_notify(message: str) -> None:
    """
    텔레그램으로 메시지를 전송합니다.

    openclaw notify "<메시지>"
    """
    from services.telegram_notifier import send_message, is_available

    if not is_available():
        print("\n❌ TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 가 .env 에 설정되지 않았습니다.")
        print("   .env 파일에 TELEGRAM_BOT_TOKEN 과 TELEGRAM_CHAT_ID 를 추가하세요.\n")
        return

    ok = send_message(message)
    if ok:
        print(f"\n✅ 텔레그램 전송 완료: {message[:60]}\n")
    else:
        print("\n❌ 전송 실패. 토큰·채팅 ID·인터넷 연결을 확인하세요.\n")


def cmd_notify_test() -> None:
    """
    텔레그램 연결 테스트 메시지를 전송합니다.

    openclaw notify_test
    """
    from services.telegram_notifier import send_message, is_available

    if not is_available():
        print("\n❌ TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 가 미설정입니다.\n")
        return

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = (
        f"✅ <b>[연결 테스트]</b> local-stock-assistant\n"
        f"텔레그램 봇 연결이 정상입니다.\n"
        f"시각: {now}"
    )
    ok = send_message(text)
    if ok:
        print("\n✅ 텔레그램 테스트 메시지 전송 성공!\n")
    else:
        print("\n❌ 전송 실패. 토큰·채팅 ID·인터넷 연결을 확인하세요.\n")


def _raise_unsupported_trading_action(*args, **kwargs) -> None:
    """미지원 거래 액션 가드."""
    raise NotImplementedError(
        "실거래 주문 기능은 이 프로젝트에서 지원하지 않습니다.\n"
        "본 도구는 분석 및 참고 목적으로만 사용합니다."
    )


# ════════════════════════════════════════════════════════════════
# 도움말
# ════════════════════════════════════════════════════════════════

def _print_help() -> None:
    print()
    print(_hr())
    print("  📈  OpenClaw v4  –  local-stock-assistant CLI")
    print(_hr())

    base_cmds = [
        ("today_candidates [N]",
         "스캐너 점수 상위 N개 후보 종목 출력 (기본값: 10)"),
        ("update_candidates",
         "후보 재스캔 + 일봉 데이터 갱신 + Supabase 저장"),
        ("analyze_stock <종목명>",
         "종합 리포트 (일봉 차트 지표·재무 3년·뉴스·최종 판단)"),
        ("news_summary <종목명>",
         "뉴스 감성 요약 및 목록 출력 (Naver/Mock 출처 표시)"),
        ("financial_summary <종목명>",
         "재무 3년 지표 요약 (DART/Mock 출처 표시)"),
        ("refresh_news <종목명>",
         "Naver API 뉴스 갱신 + Supabase 저장"),
        ("refresh_prices <종목명>",
         "FDR/Kiwoom 일봉 데이터 갱신 + 저장"),
        ('save_trade_note <종목명> "<메모>"',
         "매매 메모 저장"),
    ]
    print("  ── 분석/데이터 명령 ──")
    for cmd_str, desc in base_cmds:
        print(f"  python -m openclaw.commands {cmd_str}")
        print(f"      {desc}")
        print()

    v4_cmds = [
        ("generate_signals",
         "스캐너 점수 기반 매수/매도 신호 생성 및 저장"),
        ("pending_orders",
         "승인 대기 주문 후보 목록 조회 (승인은 Streamlit 에서)"),
        ("risk_check",
         "시스템 리스크 상태 종합 점검 (10개 검사 항목)"),
        ("safety_status",
         "안전 설정 현황 출력 (긴급 중지, 매매 모드, 한도 등)"),
        ("emergency_stop_on",
         "긴급 중지 활성화 — 모든 주문 후보 생성 및 전송 즉시 차단"),
        ("emergency_stop_off",
         "긴급 중지 해제 (확인 프롬프트 필요)"),
        ("order_logs [N]",
         "최근 주문 로그 출력: 브로커 주문 + 실행 이벤트 (기본: 20건)"),
    ]
    print("  ── v4 신규: 신호/주문/안전 명령 ──")
    for cmd_str, desc in v4_cmds:
        print(f"  python -m openclaw.commands {cmd_str}")
        print(f"      {desc}")
        print()

    virtual_cmds = [
        ("virtual_portfolio", "가상 포트폴리오, 현금, 보유 종목, 수익률 출력"),
        ("run_virtual_trading", "실제 주문 없이 가상 매수/매도 주문만 1회 생성"),
        ("strategy_performance", "전략 성과 요약: 승률, 누적 수익률, 최대 낙폭"),
        ('backtest_strategy "<전략명>"', "지정 전략을 최근 180일 기준으로 백테스트"),
        ("risk_summary", "가상 주문 전 리스크 조건 요약"),
        ("virtual_summary", "모의투자 포트폴리오, 주문, 전략 성과 요약"),
        ("virtual_run", "후보 종목 조건에 따라 가상 매수/매도 1회 실행"),
        ("virtual_backtest [일수]", "후보 점수 기반 경량 백테스트 실행"),
    ]
    print("  ── 모의투자/백테스트 명령 ──")
    for cmd_str, desc in virtual_cmds:
        print(f"  python -m openclaw.commands {cmd_str}")
        print(f"      {desc}")
        print()

    telegram_cmds = [
        ("bot_start",         "텔레그램 양방향 봇 시작 (Ctrl+C 로 종료)"),
        ('notify "<메시지>"', "텔레그램으로 메시지 전송"),
        ("notify_test",       "텔레그램 연결 테스트 메시지 전송"),
    ]
    print("  ── 텔레그램 명령 ──")
    for cmd_str, desc in telegram_cmds:
        print(f"  openclaw {cmd_str}")
        print(f"      {desc}")
        print()

    print(_hr("-"))
    print("  ⛔ 실거래 주문 기능은 지원하지 않습니다.")
    print("     주문 승인/전송은 Streamlit '✅ 주문 승인' 화면에서 직접 진행하세요.")
    print()
    print("  ⚠️  API 키가 없으면 Mock 데이터로 실행됩니다.")
    print("     .env 파일에 DART_API_KEY, NAVER_CLIENT_ID, SUPABASE_URL 등을")
    print("     설정하면 실제 데이터를 사용할 수 있습니다.")
    print(_hr())
    print()


def _is_order_cmd(cmd: str) -> bool:
    return cmd.lower() in _ORDER_KEYWORDS


# ════════════════════════════════════════════════════════════════
# 엔트리포인트
# ════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        _print_help()
        return

    cmd = args[0].lower()

    # 주문 관련 명령 차단
    if _is_order_cmd(cmd):
        print()
        print("⛔ 실거래 주문 기능은 지원하지 않습니다.")
        print("   본 도구는 분석 참고용으로만 사용할 수 있습니다.")
        print()
        return

    if cmd in ("today_candidates", "top", "candidates"):
        n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 10
        cmd_today_candidates(n)

    elif cmd == "update_candidates":
        cmd_update_candidates()

    elif cmd in ("analyze_stock", "analyze", "report"):
        if len(args) < 2:
            print("\n사용법: analyze_stock <종목명 또는 코드>\n")
            return
        cmd_analyze_stock(" ".join(args[1:]))

    elif cmd in ("news_summary", "news"):
        if len(args) < 2:
            print("\n사용법: news_summary <종목명 또는 코드>\n")
            return
        cmd_news_summary(" ".join(args[1:]))

    elif cmd in ("financial_summary", "financial", "fin"):
        if len(args) < 2:
            print("\n사용법: financial_summary <종목명 또는 코드>\n")
            return
        cmd_financial_summary(" ".join(args[1:]))

    elif cmd in ("refresh_news",):
        if len(args) < 2:
            print("\n사용법: refresh_news <종목명 또는 코드>\n")
            return
        cmd_refresh_news(" ".join(args[1:]))

    elif cmd in ("refresh_prices", "refresh_price", "prices"):
        if len(args) < 2:
            print("\n사용법: refresh_prices <종목명 또는 코드>\n")
            return
        cmd_refresh_prices(" ".join(args[1:]))

    elif cmd in ("save_trade_note", "note"):
        if len(args) < 3:
            print('\n사용법: save_trade_note <종목명> "<메모 내용>"\n')
            return
        name = args[1]
        note = " ".join(args[2:])
        cmd_save_trade_note(name, note)

    elif cmd in ("virtual_portfolio",):
        cmd_virtual_portfolio()

    elif cmd in ("run_virtual_trading",):
        cmd_run_virtual_trading()

    elif cmd in ("strategy_performance",):
        cmd_strategy_performance()

    elif cmd in ("backtest_strategy",):
        if len(args) < 2:
            print('\n사용법: backtest_strategy "<전략명>"\n')
            print('예시: python -m openclaw.commands backtest_strategy "거래량 급증 모멘텀"\n')
            return
        cmd_backtest_strategy(" ".join(args[1:]))

    elif cmd in ("risk_summary",):
        cmd_risk_summary()

    elif cmd in ("virtual_summary", "paper_summary", "portfolio"):
        cmd_virtual_summary()

    elif cmd in ("virtual_run", "paper_run"):
        cmd_run_virtual_trading()

    elif cmd in ("virtual_backtest", "paper_backtest", "backtest"):
        days = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20
        cmd_virtual_backtest(days)

    # ── v4 신규 명령 ─────────────────────────────────────────────
    elif cmd in ("generate_signals", "signals"):
        cmd_generate_signals()

    elif cmd in ("pending_orders", "pending"):
        cmd_pending_orders()

    elif cmd in ("risk_check", "riskcheck"):
        cmd_risk_check()

    elif cmd in ("safety_status", "safety"):
        cmd_safety_status()

    elif cmd in ("emergency_stop_on", "estop_on", "stop_on"):
        cmd_emergency_stop_on()

    elif cmd in ("emergency_stop_off", "estop_off", "stop_off"):
        cmd_emergency_stop_off()

    elif cmd in ("order_logs", "logs"):
        n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20
        cmd_order_logs(n)

    # ── 텔레그램 명령 ─────────────────────────────────────────────
    elif cmd in ("bot_start", "bot", "telegram"):
        cmd_bot_start()

    elif cmd in ("notify",):
        if len(args) < 2:
            print('\n사용법: notify "<메시지 내용>"\n')
            return
        cmd_notify(" ".join(args[1:]))

    elif cmd in ("notify_test", "test_notify"):
        cmd_notify_test()

    elif cmd in ("help", "--help", "-h"):
        _print_help()

    else:
        print(f"\n❌ 알 수 없는 명령: '{cmd}'")
        _print_help()


if __name__ == "__main__":
    main()
