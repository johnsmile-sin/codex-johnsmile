"""
commands.py – OpenClaw / CLI에서 호출 가능한 명령 인터페이스
실행 예: python commands.py top5
         python commands.py report 005930
         python commands.py journal list
"""

import sys
import json
from dotenv import load_dotenv

load_dotenv()

from data.mock_stocks import get_mock_stock_list
from modules.scoring import score_stocks
from modules.report import build_stock_report
from modules.db import init_db, fetch_trades, insert_trade


def cmd_top(n: int = 5):
    """상위 N개 종목 점수 출력"""
    df = score_stocks(get_mock_stock_list())
    top = df.head(n)[["종목명", "종목코드", "총점", "등급", "change_pct"]].copy()
    top["change_pct"] = top["change_pct"].apply(lambda x: f"{x:+.2f}%")
    print(f"\n{'='*40}")
    print(f"  📈 오늘의 TOP {n} 종목")
    print(f"{'='*40}")
    for _, row in top.iterrows():
        print(
            f"  [{row['등급']}] {row['종목명']:12s}  "
            f"{row['총점']:5.1f}점  {row['change_pct']}"
        )
    print(f"{'='*40}\n")


def cmd_report(code: str):
    """특정 종목 리포트 출력"""
    df = score_stocks(get_mock_stock_list())
    rows = df[df["종목코드"] == code]
    if rows.empty:
        print(f"종목코드 {code}를 찾을 수 없습니다.")
        return

    report = build_stock_report(rows.iloc[0])
    judgment = report["투자판단"]
    info = report["기본정보"]

    print(f"\n{'='*50}")
    print(f"  {info['종목명']} ({info['종목코드']})  |  {info['시장']}  |  {info['섹터']}")
    print(f"  현재가: {info['현재가']:,}원  등락률: {info['등락률']:+.2f}%")
    print(f"  종합점수: {report['점수']['총점']}점  등급: {report['점수']['등급']}")
    print(f"  투자판단: {judgment['opinion']} (신뢰도: {judgment['confidence']})")
    print(f"\n  판단 근거:")
    print(f"  {judgment['reason']}")
    print(f"\n  전략:")
    print(f"  {judgment['strategy']}")
    print(f"\n  리스크:")
    for r in judgment["risk_factors"]:
        print(f"  ⚠️  {r}")
    print(f"{'='*50}\n")


def cmd_journal(action: str, *args):
    """매매일지 CLI"""
    init_db()

    if action == "list":
        trades = fetch_trades()
        if not trades:
            print("기록된 거래가 없습니다.")
            return
        print(f"\n{'='*60}")
        print(f"  📝 매매일지 ({len(trades)}건)")
        print(f"{'='*60}")
        for t in trades:
            print(
                f"  [{t.get('id', '-')}] {t['날짜']}  "
                f"{t['종목명']:10s}  {t['거래유형']}  "
                f"{t['수량']}주 @ {t['단가']:,}원"
            )
        print(f"{'='*60}\n")

    elif action == "add":
        # 예: python commands.py journal add 005930 매수 75000 10
        if len(args) < 4:
            print("사용법: journal add <종목코드> <매수|매도> <단가> <수량>")
            return
        code, trade_type, price, qty = args[0], args[1], int(args[2]), int(args[3])
        df = get_mock_stock_list()
        name_row = df[df["종목코드"] == code]
        name = name_row["종목명"].values[0] if not name_row.empty else code
        from datetime import date
        record = {
            "날짜": str(date.today()),
            "종목코드": code,
            "종목명": name,
            "거래유형": trade_type,
            "단가": price,
            "수량": qty,
            "총금액": price * qty,
            "수수료": 0,
            "메모": "CLI 등록",
        }
        insert_trade(record)
        print(f"✅ {name} {trade_type} {qty}주 @ {price:,}원 등록 완료")

    else:
        print(f"알 수 없는 액션: {action}")


# ─── 비활성화된 주문 기능 (절대 활성화 금지) ──────────────────
def _DISABLED_place_order(*args, **kwargs):
    """
    실거래 주문 함수 – 비활성화 상태.
    실계좌 주문 기능은 이 프로젝트 범위 밖입니다.
    """
    raise NotImplementedError("실거래 주문 기능은 비활성화되어 있습니다.")


# ─── 엔트리포인트 ─────────────────────────────────────────────
if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("사용법: python commands.py <명령> [옵션]")
        print("  top [N]              – 상위 N개 종목 (기본 5)")
        print("  report <종목코드>     – 종목 상세 리포트")
        print("  journal list         – 매매일지 조회")
        print("  journal add <코드> <매수|매도> <단가> <수량>")
        sys.exit(0)

    cmd = args[0].lower()

    if cmd == "top":
        n = int(args[1]) if len(args) > 1 else 5
        cmd_top(n)

    elif cmd == "report":
        if len(args) < 2:
            print("사용법: python commands.py report <종목코드>")
        else:
            cmd_report(args[1])

    elif cmd == "journal":
        if len(args) < 2:
            print("사용법: python commands.py journal <list|add> ...")
        else:
            cmd_journal(args[1], *args[2:])

    else:
        print(f"알 수 없는 명령: {cmd}")
