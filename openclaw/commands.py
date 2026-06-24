"""
openclaw/commands.py  –  OpenClaw CLI 명령 인터페이스

Streamlit 없이 단독 실행 가능합니다.
실거래 주문 기능은 포함하지 않습니다.

사용법:
    python -m openclaw.commands today_candidates [N]
    python -m openclaw.commands analyze_stock <종목명 또는 코드>
    python -m openclaw.commands news_summary <종목명 또는 코드>
    python -m openclaw.commands save_trade_note <종목명> "<메모>"
"""

from __future__ import annotations

import sys
import os
from datetime import date
from typing import Any

# Windows cp949 터미널에서 이모지/한글 출력 오류 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 패키지 루트를 sys.path에 추가 (어디서 실행하든 import 가능)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv()


# ════════════════════════════════════════════════════════════════
# 출력 헬퍼
# ════════════════════════════════════════════════════════════════

_SENT_ICON = {"긍정": "📈", "중립": "📊", "부정": "📉"}

_ORDER_KEYWORDS = {
    "매수주문", "매도주문", "place_order", "place-order",
    "order", "buy_order", "sell_order",
}


def _hr(char: str = "=", width: int = 62) -> str:
    return char * width


def _section(title: str) -> None:
    print(f"\n{'─' * 4} {title} {'─' * (55 - len(title))}")


# ════════════════════════════════════════════════════════════════
# 공통: 종목 검색
# ════════════════════════════════════════════════════════════════

def _find_stock(name_or_code: str) -> tuple[Any, Any] | None:
    """
    종목명(부분 일치) 또는 코드로 (market_row, score_row) 반환.
    없으면 None.
    """
    from services.market_data import get_sample_market_data
    from strategy.scanner import scan

    market_df = get_sample_market_data()
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
    srow = scored_df[scored_df["stock_code"] == code].iloc[0]
    return mrow, srow


def _print_not_found(name_or_code: str) -> None:
    print(f"\n❌ '{name_or_code}' 종목을 찾을 수 없습니다.")
    print("  종목명 예시: 삼성전자, SK하이닉스, NAVER, 현대차, LG화학, 카카오")
    print("  종목코드 예시: 005930, 000660, 035420")
    print()


# ════════════════════════════════════════════════════════════════
# 명령 1: today_candidates
# ════════════════════════════════════════════════════════════════

def cmd_today_candidates(n: int = 10) -> None:
    """
    스캐너 점수 상위 N개 후보 종목을 출력합니다.

    python -m openclaw.commands today_candidates [N]
    """
    from services.market_data import get_sample_market_data
    from strategy.scanner import scan

    market_df = get_sample_market_data()
    scored_df = scan(market_df)

    merged = scored_df.merge(
        market_df[[
            "stock_code", "market", "sector",
            "current_price", "change_rate", "trading_value", "news_count",
        ]],
        on="stock_code",
        how="left",
    )
    top = merged.head(n)

    print()
    print(_hr())
    print(f"  📈  오늘의 후보 종목 TOP {n}   ({date.today()})")
    print(_hr())

    for rank, (_, row) in enumerate(top.iterrows(), 1):
        decision = row["decision"]
        score    = int(row["score"])
        chg      = row["change_rate"]
        chg_str  = f"{chg:+.2f}%"
        tv_str   = f"{row['trading_value']:.0f}억"

        print(
            f"  {rank:>2}. [{decision}] {row['stock_name']}"
            f"({row['stock_code']})  {score}점"
            f"  {chg_str}  거래대금 {tv_str}  뉴스 {int(row['news_count'])}건"
        )

        reasons = row["reasons"]
        risks   = row["risks"]
        if reasons:
            print(f"      ✅ " + " / ".join(reasons[:2]))
        if risks:
            print(f"      ⚠️  " + risks[0])

    print(_hr())

    counts  = top["decision"].value_counts().to_dict()
    summary = "  ".join(
        f"{k} {counts.get(k, 0)}개"
        for k in ("관심", "관찰", "보류", "제외")
        if counts.get(k, 0) > 0
    )
    print(f"  판단 분포: {summary}")
    print(f"  ※ 본 정보는 투자 참고용이며 수익을 보장하지 않습니다.")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# 명령 2: analyze_stock
# ════════════════════════════════════════════════════════════════

def cmd_analyze_stock(name_or_code: str) -> None:
    """
    종목 종합 리포트를 출력합니다.

    python -m openclaw.commands analyze_stock <종목명 또는 코드>
    """
    from services.news_data import get_mock_news
    from analysis.stock_report import generate_report, format_report_text

    result = _find_stock(name_or_code)
    if result is None:
        _print_not_found(name_or_code)
        return

    mrow, srow = result
    code       = str(mrow["stock_code"])
    news_items = get_mock_news(stock_code=code)

    report = generate_report(mrow, srow, news_items)
    print()
    print(format_report_text(report))


# ════════════════════════════════════════════════════════════════
# 명령 3: news_summary
# ════════════════════════════════════════════════════════════════

def cmd_news_summary(name_or_code: str) -> None:
    """
    종목 뉴스 감성을 요약합니다.

    python -m openclaw.commands news_summary <종목명 또는 코드>
    """
    from services.news_data import get_mock_news, get_news_summary

    result = _find_stock(name_or_code)
    if result is None:
        _print_not_found(name_or_code)
        return

    mrow, _ = result
    code    = str(mrow["stock_code"])
    name    = str(mrow["stock_name"])

    news_items = get_mock_news(stock_code=code)
    summary    = get_news_summary(news_items)
    total      = summary["합계"]

    print()
    print(_hr())
    print(f"  📰  {name} ({code})  뉴스 감성 요약")
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

    print(f"  전체: {total}건  |  📈 긍정 {pos}건 ({pos_pct}%)  "
          f"📊 중립 {neu}건 ({neu_pct}%)  📉 부정 {neg}건 ({neg_pct}%)")

    # 감성 바 (30칸)
    bar_total = 30
    pos_bar = "█" * round(bar_total * pos / total)
    neg_bar = "█" * round(bar_total * neg / total)
    neu_bar = "░" * max(0, bar_total - len(pos_bar) - len(neg_bar))
    print(f"  감성 막대: 긍정[{pos_bar}{neu_bar}{neg_bar}]부정")

    # 전반적 판단
    if pos_pct >= 50:
        overall = "긍정 우위 → 시장 분위기 양호"
    elif neg_pct >= 40:
        overall = "부정 우위 → 주의 필요"
    else:
        overall = "중립 → 추가 확인 후 판단"
    print(f"  종합 판단: {overall}")

    print(_hr("-"))
    print("  뉴스 목록 (최신순):")
    for item in sorted(news_items, key=lambda x: x.get("news_date", ""), reverse=True):
        sent   = item.get("sentiment", "중립")
        icon   = _SENT_ICON.get(sent, "📊")
        stars  = "★" * item.get("impact_score", 3) + "☆" * (5 - item.get("impact_score", 3))
        print(
            f"  {icon} [{sent:<2}] {item.get('news_date', '')}  "
            f"{item['title']}  {stars}"
        )

    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# 명령 4: save_trade_note
# ════════════════════════════════════════════════════════════════

def cmd_save_trade_note(name_or_code: str, note: str) -> None:
    """
    종목 메모를 매매일지에 저장합니다.

    python -m openclaw.commands save_trade_note <종목명> "<메모>"
    """
    import services.mock_db_service as mock

    if not note.strip():
        print("\n❌ 메모 내용을 입력하세요.")
        print('  사용법: save_trade_note <종목명> "<메모 내용>"')
        print()
        return

    result = _find_stock(name_or_code)
    if result is None:
        _print_not_found(name_or_code)
        return

    mrow, srow = result
    code  = str(mrow["stock_code"])
    name  = str(mrow["stock_name"])
    today = str(date.today())

    record = mock.save_trade_journal({
        "trade_date":  today,
        "stock_code":  code,
        "stock_name":  name,
        "action":      "메모",
        "entry_price": 0,
        "exit_price":  None,
        "quantity":    0,
        "reason":      note.strip(),
        "result_memo": (
            f"OpenClaw CLI 등록  |  "
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
    print(f"  저장 ID : {record.get('id', '-')}")
    print(_hr())
    print()


# ════════════════════════════════════════════════════════════════
# 비활성화 — 실거래 주문 (절대 활성화 금지)
# ════════════════════════════════════════════════════════════════

def _DISABLED_place_order(*args, **kwargs) -> None:
    """실거래 주문 함수 — 비활성화 상태. 절대 호출하지 않습니다."""
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
    print("  📈  OpenClaw  –  local-stock-assistant CLI")
    print(_hr())
    print("  python -m openclaw.commands today_candidates [N]")
    print("      스캐너 점수 상위 N개 후보 종목 출력  (기본값: 10)")
    print()
    print("  python -m openclaw.commands analyze_stock <종목명 또는 코드>")
    print("      종합 리포트 출력 (기술·재무·뉴스·최종 판단)")
    print()
    print("  python -m openclaw.commands news_summary <종목명 또는 코드>")
    print("      뉴스 감성 요약 및 목록 출력")
    print()
    print('  python -m openclaw.commands save_trade_note <종목명> "<메모>"')
    print("      매매 메모를 매매일지에 저장")
    print(_hr("-"))
    print("  ⛔ 실거래 주문 기능은 지원하지 않습니다.")
    print("     본 도구는 분석 참고용으로만 사용하세요.")
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

    elif cmd in ("analyze_stock", "analyze", "report"):
        if len(args) < 2:
            print("\n사용법: analyze_stock <종목명 또는 코드>\n")
            return
        cmd_analyze_stock(args[1])

    elif cmd in ("news_summary", "news"):
        if len(args) < 2:
            print("\n사용법: news_summary <종목명 또는 코드>\n")
            return
        cmd_news_summary(args[1])

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
