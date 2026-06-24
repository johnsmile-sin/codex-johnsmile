"""
openclaw/commands.py v2  –  OpenClaw CLI 명령 인터페이스

Streamlit 없이 단독 실행 가능합니다.
실거래 주문 기능은 포함하지 않습니다.

지원 명령:
    today_candidates            스캐너 점수 상위 후보 종목 출력
    update_candidates           후보 재스캔 + 일봉 데이터 갱신 + Supabase 저장
    analyze_stock <종목명>      종합 리포트 (일봉 데이터 + 재무 3년 + 뉴스 포함)
    news_summary <종목명>       뉴스 감성 요약 (출처 표시)
    financial_summary <종목명>  재무 3년 지표 요약
    refresh_news <종목명>       Naver API 뉴스 갱신 + 저장
    refresh_prices <종목명>     FDR/Kiwoom 일봉 데이터 갱신 + 저장
    save_trade_note <종목명> <메모>  매매 메모 저장

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


# ════════════════════════════════════════════════════════════════
# 비활성화 — 실거래 주문 (절대 활성화 금지)
# ════════════════════════════════════════════════════════════════

def _DISABLED_place_order(*args, **kwargs) -> None:
    """실거래 주문 함수 — 비활성화. 절대 호출 금지."""
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
    print("  📈  OpenClaw v2  –  local-stock-assistant CLI")
    print(_hr())

    cmds = [
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
    for cmd_str, desc in cmds:
        print(f"  python -m openclaw.commands {cmd_str}")
        print(f"      {desc}")
        print()

    print(_hr("-"))
    print("  ⛔ 실거래 주문 기능은 지원하지 않습니다.")
    print("     본 도구는 분석 참고용으로만 사용하세요.")
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

    elif cmd in ("help", "--help", "-h"):
        _print_help()

    else:
        print(f"\n❌ 알 수 없는 명령: '{cmd}'")
        _print_help()


if __name__ == "__main__":
    main()
