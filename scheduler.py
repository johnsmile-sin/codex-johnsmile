"""
scheduler.py  –  수동 실행 업데이트 스크립트

자동 실행이 아닌 필요할 때 수동으로 호출하는 배치성 스크립트입니다.
실거래 주문 기능은 포함하지 않습니다.

사용법:
    python scheduler.py update_candidates   가격/스캐너 업데이트
    python scheduler.py update_news         뉴스 업데이트
    python scheduler.py update_financial    재무 데이터 업데이트
    python scheduler.py generate_reports    리포트 생성 및 저장
    python scheduler.py all                 전체 순서대로 실행

옵션:
    --top N      처리할 상위 종목 수 (기본값: 20)
    --min-score  최소 점수 필터 (기본값: 40)
"""

from __future__ import annotations

import sys
import os
import json
import time
import logging
import traceback
from datetime import date, datetime
from logging.handlers import RotatingFileHandler
from typing import Any

# ── Windows 터미널 UTF-8 ─────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 패키지 루트 경로 등록 ───────────────────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv()

# ════════════════════════════════════════════════════════════════
# 로깅 설정
# ════════════════════════════════════════════════════════════════

_LOG_DIR  = os.path.join(_ROOT, "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "scheduler.log")

_FMT = "%(asctime)s [%(levelname)s] %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _setup_logging() -> logging.Logger:
    """logs/scheduler.log (최대 5MB × 3개) + 콘솔 동시 출력."""
    os.makedirs(_LOG_DIR, exist_ok=True)

    logger = logging.getLogger("scheduler")
    if logger.handlers:
        return logger  # 중복 핸들러 방지

    logger.setLevel(logging.DEBUG)

    # 파일 핸들러 (RotatingFileHandler)
    fh = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=5 * 1024 * 1024,   # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))

    # 콘솔 핸들러
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


log = _setup_logging()


# ════════════════════════════════════════════════════════════════
# 헬퍼
# ════════════════════════════════════════════════════════════════

def _banner(title: str) -> None:
    bar = "=" * 60
    log.info(bar)
    log.info("  %s", title)
    log.info("  실행일: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info(bar)


def _print_api_status() -> None:
    """API 연결 상태를 로그에 기록."""
    import config as _cfg
    st = []
    st.append("Supabase ✅" if _cfg.is_supabase_available() else "Supabase ❌")
    st.append("DART ✅"     if _cfg.is_dart_available()     else "DART ❌")
    st.append("Naver ✅"    if _cfg.is_naver_available()    else "Naver ❌")
    st.append("키움 ✅"     if _cfg.is_kiwoom_available()   else "키움 ❌")
    log.info("API 상태: %s", "  |  ".join(st))


def _mock_notice(context: str) -> None:
    """Mock 모드 안내 로그."""
    log.warning("[Mock 모드] %s 키가 없어 Mock 데이터로 실행됩니다.", context)


def _task(name: str):
    """데코레이터: 태스크 시작/종료/소요시간/예외를 자동으로 로그."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            log.info("── [%s] 시작", name)
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                elapsed = time.perf_counter() - t0
                log.info("── [%s] 완료  (%.1f초)", name, elapsed)
                return result
            except Exception as exc:
                elapsed = time.perf_counter() - t0
                log.error("── [%s] 오류 발생 (%.1f초): %s", name, elapsed, exc)
                log.debug(traceback.format_exc())
                return None
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator


def _load_candidates(min_score: int = 40) -> tuple[Any, Any]:
    """
    시장 데이터 + 스캐너 실행 후 min_score 이상 후보 반환.

    Returns:
        (market_df, scored_df) — scored_df 는 min_score 필터 적용됨.
    """
    from services.market_data import get_market_data
    from strategy.scanner import scan

    log.info("  시장 데이터 로딩...")
    market_df = get_market_data()
    scored_df = scan(market_df)

    data_src = market_df["data_source"].iloc[0] if "data_source" in market_df.columns else "Mock"
    ref_date = market_df["ref_date"].iloc[0]     if "ref_date"    in market_df.columns else str(date.today())
    log.info("  데이터 출처: %s  |  기준일: %s", data_src, ref_date)

    filtered = scored_df[scored_df["score"] >= min_score].copy()
    log.info("  전체 종목 %d개  |  점수 %d점 이상: %d개", len(scored_df), min_score, len(filtered))

    # 판단 분포 로그
    dist = filtered["decision"].value_counts().to_dict()
    for d in ["강한 관심", "관심", "관찰", "보류"]:
        if dist.get(d, 0) > 0:
            log.info("    %s: %d개", d, dist[d])

    return market_df, filtered


def _get_stock_list(scored_df: Any, market_df: Any, top: int) -> list[dict]:
    """scored_df 상위 top개 종목을 dict 목록으로 반환."""
    import pandas as pd
    top_df = scored_df.nlargest(top, "score")
    rows = []
    for _, r in top_df.iterrows():
        code = str(r["stock_code"])
        mrows = market_df[market_df["stock_code"] == code]
        if mrows.empty:
            continue
        mrow = mrows.iloc[0]
        rows.append({
            "stock_code": code,
            "stock_name": str(r.get("stock_name", mrow.get("stock_name", ""))),
            "score":      int(r["score"]),
            "decision":   str(r["decision"]),
            "market_row": mrow,
            "score_row":  r,
        })
    return rows


def _supabase_upsert(table: str, data: dict | list, on_conflict: str = "") -> dict:
    """Supabase 직접 upsert (db_service.py 의 Streamlit 의존성 우회)."""
    try:
        from services.supabase_client import get_client, is_connected
        if not is_connected():
            return {"saved": 0, "mode": "mock", "error": "Supabase 미연결"}
        q = get_client().table(table)
        if on_conflict:
            result = q.upsert(data, on_conflict=on_conflict).execute()
        else:
            result = q.insert(data).execute()
        cnt = len(result.data) if result.data else (len(data) if isinstance(data, list) else 1)
        return {"saved": cnt, "mode": "supabase"}
    except Exception as e:
        if (
            table == "stock_reports"
            and on_conflict == "stock_code,report_date"
            and isinstance(data, dict)
            and "there is no unique or exclusion constraint" in str(e)
        ):
            try:
                client = get_client()
                client.table(table).delete().eq("stock_code", data["stock_code"]).eq(
                    "report_date",
                    data["report_date"],
                ).execute()
                result = client.table(table).insert(data).execute()
                cnt = len(result.data) if result.data else 1
                return {"saved": cnt, "mode": "supabase"}
            except Exception as fallback_error:
                return {"saved": 0, "mode": "mock", "error": str(fallback_error)}
        return {"saved": 0, "mode": "mock", "error": str(e)}


def _save_report_json(code: str, name: str, report: dict) -> str:
    """리포트를 data/reports/ 에 JSON 파일로 저장. 경로 반환."""
    reports_dir = os.path.join(_ROOT, "data", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    fname = f"{code}_{date.today()}.json"
    fpath = os.path.join(reports_dir, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return fpath


# ════════════════════════════════════════════════════════════════
# 태스크 1: update_all_candidates
# ════════════════════════════════════════════════════════════════

def update_all_candidates(top: int = 20, min_score: int = 40) -> dict:
    """
    전체 업데이트 파이프라인을 순서대로 실행합니다.

    순서: 가격 → 뉴스 → 재무 → 리포트
    각 단계 오류는 기록 후 다음 단계를 계속 진행합니다.

    Args:
        top:       처리할 상위 종목 수
        min_score: 최소 스캐너 점수

    Returns:
        {"price": dict, "news": dict, "financial": dict, "reports": dict}
    """
    _banner("전체 업데이트 시작 (update_all_candidates)")
    _print_api_status()

    results = {}
    for step_name, step_fn in [
        ("price",     lambda: _run_price_update(top, min_score)),
        ("news",      lambda: update_news_for_candidates(top, min_score)),
        ("financial", lambda: update_financial_for_candidates(top, min_score)),
        ("reports",   lambda: generate_reports_for_candidates(top, min_score)),
    ]:
        log.info("")
        try:
            results[step_name] = step_fn()
        except Exception as exc:
            log.error("[%s] 단계 전체 오류: %s", step_name, exc)
            log.debug(traceback.format_exc())
            results[step_name] = {"error": str(exc)}

    log.info("")
    log.info("=" * 60)
    log.info("  전체 업데이트 완료")
    for k, v in results.items():
        if isinstance(v, dict):
            err = v.get("error", "")
            log.info("  %-12s: %s", k, "오류: " + err if err else str({x: v[x] for x in v if x != "error"}))
    log.info("=" * 60)

    return results


# ════════════════════════════════════════════════════════════════
# 태스크 2: 가격 업데이트 (update_candidates CLI 진입점)
# ════════════════════════════════════════════════════════════════

@_task("update_price")
def _run_price_update(top: int = 20, min_score: int = 40) -> dict:
    """가격/일봉 데이터 업데이트 내부 구현."""
    from services.price_service import update_daily_prices_for_candidates

    market_df, scored_df = _load_candidates(min_score)
    candidates = (
        scored_df.nlargest(top, "score")[["stock_code", "stock_name"]]
        .to_dict("records")
    )

    log.info("  %d개 종목 일봉 데이터 업데이트 중...", len(candidates))
    result = update_daily_prices_for_candidates(candidates)

    log.info(
        "  완료: %d/%d 성공  |  실패: %d",
        result["success"], result["total"], result["failed"],
    )
    for d in result.get("details", []):
        if d.get("status") == "success":
            log.debug("    ✅ %s(%s): %d행 저장 [%s]",
                      d.get("stock_code"), d.get("stock_code"), d.get("rows", 0), d.get("mode"))
        else:
            log.warning("    ❌ %s: %s", d.get("stock_code"), d.get("error", ""))

    return result


# ════════════════════════════════════════════════════════════════
# 태스크 3: update_news_for_candidates
# ════════════════════════════════════════════════════════════════

def update_news_for_candidates(top: int = 20, min_score: int = 40) -> dict:
    """
    상위 종목의 뉴스를 Naver API로 갱신하고 Supabase에 저장합니다.

    Naver API 키가 없으면 Mock 모드 안내 후 종료합니다.

    Args:
        top:       처리할 상위 종목 수
        min_score: 최소 스캐너 점수

    Returns:
        {"total": N, "success": N, "failed": N, "saved_total": N}
    """
    import config as _cfg
    from services.news_data import fetch_news_from_naver, save_news_to_supabase

    _banner(f"뉴스 업데이트 (update_news_for_candidates) — 상위 {top}개")
    _print_api_status()

    if not _cfg.is_naver_available():
        _mock_notice("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET")
        log.info("  뉴스 업데이트를 건너뜁니다. (.env 에 Naver 키 설정 필요)")
        return {"total": 0, "success": 0, "failed": 0, "saved_total": 0, "mode": "skipped"}

    market_df, scored_df = _load_candidates(min_score)
    stocks = _get_stock_list(scored_df, market_df, top)

    total = success = failed = saved_total = 0
    for s in stocks:
        total += 1
        code = s["stock_code"]
        name = s["stock_name"]
        try:
            log.info("  [%d/%d] %s(%s) 뉴스 조회...", total, len(stocks), name, code)
            items = fetch_news_from_naver(name, days=30, max_items=20, stock_code=code)

            if not items:
                log.info("    → 0건 수신 (API 응답 없음)")
                success += 1
                continue

            # 감성 집계
            pos = sum(1 for n in items if n.get("sentiment") == "긍정")
            neg = sum(1 for n in items if n.get("sentiment") == "부정")
            log.info("    → %d건 수신  긍정 %d  부정 %d", len(items), pos, neg)

            res = save_news_to_supabase(items)
            saved = res.get("saved", 0)
            saved_total += saved

            if res.get("error"):
                log.warning("    저장 오류: %s", res["error"])
            else:
                log.info("    → %d건 저장 완료", saved)

            success += 1

        except Exception as exc:
            failed += 1
            log.error("  ❌ %s(%s) 오류: %s", name, code, exc)
            log.debug(traceback.format_exc())

    result = {"total": total, "success": success, "failed": failed, "saved_total": saved_total}
    log.info("뉴스 업데이트 완료: %d/%d 성공  저장 %d건", success, total, saved_total)
    return result


# ════════════════════════════════════════════════════════════════
# 태스크 4: update_financial_for_candidates
# ════════════════════════════════════════════════════════════════

def update_financial_for_candidates(top: int = 20, min_score: int = 40) -> dict:
    """
    상위 종목의 재무 데이터를 DART API로 갱신하고 Supabase에 저장합니다.

    DART API 키가 없으면 Mock 모드 안내 후 종료합니다.

    Args:
        top:       처리할 상위 종목 수
        min_score: 최소 스캐너 점수

    Returns:
        {"total": N, "success": N, "failed": N, "dart_count": N, "mock_count": N}
    """
    import config as _cfg
    from services.financial_data import get_financial_metrics, save_financial_metrics_to_supabase

    _banner(f"재무 데이터 업데이트 (update_financial_for_candidates) — 상위 {top}개")
    _print_api_status()

    if not _cfg.is_dart_available():
        _mock_notice("DART_API_KEY")
        log.info("  재무 업데이트를 건너뜁니다. (.env 에 DART_API_KEY 설정 필요)")
        return {"total": 0, "success": 0, "failed": 0, "dart_count": 0, "mock_count": 0, "mode": "skipped"}

    market_df, scored_df = _load_candidates(min_score)
    stocks = _get_stock_list(scored_df, market_df, top)

    total = success = failed = dart_count = mock_count = 0
    for s in stocks:
        total += 1
        code = s["stock_code"]
        name = s["stock_name"]
        try:
            log.info("  [%d/%d] %s(%s) 재무 조회...", total, len(stocks), name, code)
            metrics = get_financial_metrics(code, name)
            fin_src = metrics.get("fin_source", "Mock")
            years   = metrics.get("years", [])

            log.info(
                "    → 출처: %s  |  연도: %s",
                fin_src,
                ", ".join(y.get("fiscal_year", "") for y in years),
            )

            if fin_src == "DART":
                dart_count += 1
                res = save_financial_metrics_to_supabase(metrics)
                saved = res.get("saved", 0)
                if res.get("error"):
                    log.warning("    저장 오류: %s", res["error"])
                else:
                    log.info("    → %d건 저장 완료 (Supabase)", saved)
            else:
                mock_count += 1
                log.info("    → Mock 데이터 (DART 수신 실패 — 저장 생략)")

            success += 1

        except Exception as exc:
            failed += 1
            log.error("  ❌ %s(%s) 오류: %s", name, code, exc)
            log.debug(traceback.format_exc())

    result = {
        "total": total, "success": success, "failed": failed,
        "dart_count": dart_count, "mock_count": mock_count,
    }
    log.info(
        "재무 업데이트 완료: %d/%d 성공  DART %d건  Mock %d건",
        success, total, dart_count, mock_count,
    )
    return result


# ════════════════════════════════════════════════════════════════
# 태스크 5: generate_reports_for_candidates
# ════════════════════════════════════════════════════════════════

def generate_reports_for_candidates(top: int = 10, min_score: int = 60) -> dict:
    """
    상위 종목의 종합 리포트를 생성하고 파일/Supabase에 저장합니다.

    저장 경로:
        data/reports/{code}_{today}.json   (항상 저장)
        Supabase stock_reports 테이블       (연결된 경우)

    Args:
        top:       처리할 상위 종목 수 (기본값: 10)
        min_score: 최소 점수 (기본값: 60 = 관찰 이상)

    Returns:
        {"total": N, "success": N, "failed": N, "saved_files": [paths]}
    """
    from services.news_data import get_news_for_stock
    from services.financial_data import get_financial_metrics
    from services.price_service import fetch_daily_prices
    from analysis.stock_report import generate_report, format_report_text

    _banner(f"리포트 생성 (generate_reports_for_candidates) — 점수 {min_score}점 이상 상위 {top}개")
    _print_api_status()

    market_df, scored_df = _load_candidates(min_score)
    stocks = _get_stock_list(scored_df, market_df, top)

    if not stocks:
        log.info("  해당 조건에 맞는 종목이 없습니다 (점수 %d점 이상).", min_score)
        return {"total": 0, "success": 0, "failed": 0, "saved_files": []}

    total = success = failed = 0
    saved_files: list[str] = []

    for s in stocks:
        total += 1
        code  = s["stock_code"]
        name  = s["stock_name"]
        score = s["score"]
        mrow  = s["market_row"]
        srow  = s["score_row"]

        try:
            log.info(
                "  [%d/%d] %s(%s) — %d점 / %s",
                total, len(stocks), name, code, score, s["decision"],
            )

            # ── 데이터 수집 ───────────────────────────────────
            news_items    = get_news_for_stock(stock_code=code, stock_name=name)
            fin_metrics   = get_financial_metrics(code, name)
            price_history = fetch_daily_prices(code, days=60)

            fin_src  = fin_metrics.get("fin_source", "Mock")
            fin_yrs  = fin_metrics.get("years", [])
            ph       = price_history if not price_history.empty else None

            log.info(
                "    데이터: 일봉 %d일  재무 %d년(%s)  뉴스 %d건",
                len(price_history), len(fin_yrs), fin_src, len(news_items),
            )

            # ── 리포트 생성 ──────────────────────────────────
            report = generate_report(
                mrow, srow, news_items,
                fin_source=fin_src,
                financial_years=fin_yrs,
                price_history=ph,
            )

            verdict     = report["최종_판단"]["판정"]
            reliability = report["데이터_신뢰도"]["종합_등급"]
            hold_reason = report["최종_판단"].get("판단_보류_이유")

            log.info(
                "    판정: %s  |  신뢰도: %s%s",
                verdict, reliability,
                f"  ⚠️ 판단보류" if hold_reason else "",
            )

            # ── JSON 파일 저장 ───────────────────────────────
            fpath = _save_report_json(code, name, report)
            saved_files.append(fpath)
            log.info("    JSON 저장: %s", os.path.basename(fpath))

            # ── Supabase 저장 (stock_reports 테이블) ─────────
            j = report["최종_판단"]
            pos = sum(1 for n in news_items if n.get("sentiment") == "긍정")
            neu = sum(1 for n in news_items if n.get("sentiment") == "중립")
            neg = sum(1 for n in news_items if n.get("sentiment") == "부정")

            supa_res = _supabase_upsert(
                "stock_reports",
                {
                    "stock_code":        code,
                    "stock_name":        name,
                    "report_date":       str(date.today()),
                    "technical_summary": (
                        f"점수 {score}점 / "
                        f"MA5 {int(mrow.get('ma5', 0)):,}원 / "
                        f"MA20 {int(mrow.get('ma20', 0)):,}원"
                    ),
                    "financial_summary": (
                        f"PER {float(mrow.get('per', 0)):.1f}배 / "
                        f"ROE {float(mrow.get('roe', 0)):.1f}% / "
                        f"부채비율 {float(mrow.get('debt_ratio', 0)):.0f}%"
                    ),
                    "news_summary":   f"긍정 {pos}건 / 중립 {neu}건 / 부정 {neg}건",
                    "final_decision": verdict,
                    "target_return":  j["목표_수익률"],
                    "stop_loss":      j["손절_라인"],
                    "entry_timing":   j["진입_타이밍"],
                    "risks":          " / ".join(j["리스크"]),
                    "conclusion":     report["한_줄_결론"],
                    "raw_json":       json.dumps(report, ensure_ascii=False),
                },
                on_conflict="stock_code,report_date",
            )

            if supa_res.get("error"):
                log.warning("    Supabase 저장 실패: %s (JSON 파일만 유효)", supa_res["error"])
            else:
                log.info("    Supabase 저장 완료 [%s]", supa_res.get("mode"))

            success += 1

        except Exception as exc:
            failed += 1
            log.error("  ❌ %s(%s) 리포트 오류: %s", name, code, exc)
            log.debug(traceback.format_exc())

    result = {
        "total": total,
        "success": success,
        "failed": failed,
        "saved_files": saved_files,
    }
    log.info(
        "리포트 생성 완료: %d/%d 성공  JSON %d개 저장",
        success, total, len(saved_files),
    )
    return result


# ════════════════════════════════════════════════════════════════
# 비활성화 — 실거래 주문 (절대 활성화 금지)
# ════════════════════════════════════════════════════════════════

def _DISABLED_run_order_task(*args, **kwargs) -> None:
    """실거래 주문 태스크 — 비활성화. 절대 호출 금지."""
    raise NotImplementedError(
        "실거래 주문 기능은 이 스크립트에서 지원하지 않습니다.\n"
        "본 도구는 분석 및 참고 목적으로만 사용합니다."
    )


# ════════════════════════════════════════════════════════════════
# CLI 인자 파싱
# ════════════════════════════════════════════════════════════════

def _parse_args(argv: list[str]) -> tuple[str, int, int]:
    """
    argv 에서 (command, top, min_score) 를 파싱합니다.

    예시:
        update_news --top 15 --min-score 60
        generate_reports --top 5
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python scheduler.py",
        description="local-stock-assistant 수동 업데이트 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "명령:\n"
            "  update_candidates   가격/일봉 데이터 업데이트\n"
            "  update_news         뉴스 업데이트 (Naver API)\n"
            "  update_financial    재무 데이터 업데이트 (DART API)\n"
            "  generate_reports    리포트 생성 및 저장\n"
            "  all                 전체 순서대로 실행\n"
        ),
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="",
        help="실행할 명령",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        metavar="N",
        help="처리할 상위 종목 수 (기본값: 20)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=40,
        dest="min_score",
        metavar="N",
        help="최소 스캐너 점수 (기본값: 40)",
    )

    ns = parser.parse_args(argv)
    return ns.command.lower(), ns.top, ns.min_score


def _print_help() -> None:
    print()
    print("=" * 60)
    print("  📈  scheduler.py  –  수동 업데이트 스크립트")
    print("=" * 60)
    cmds = [
        ("update_candidates",  "가격/일봉 데이터 업데이트 (FinanceDataReader)"),
        ("update_news",        "뉴스 데이터 업데이트 (Naver API → Supabase)"),
        ("update_financial",   "재무 데이터 업데이트 (DART API → Supabase)"),
        ("generate_reports",   "종합 리포트 생성 (data/reports/ 저장)"),
        ("all",                "전체 순서대로 실행 (가격→뉴스→재무→리포트)"),
    ]
    for cmd, desc in cmds:
        print(f"  python scheduler.py {cmd:<22} {desc}")

    print()
    print("  옵션:")
    print("    --top N          처리할 상위 종목 수 (기본값: 20)")
    print("    --min-score N    최소 점수 필터  (기본값: 40)")
    print()
    print("  예시:")
    print("    python scheduler.py update_candidates")
    print("    python scheduler.py generate_reports --top 5 --min-score 60")
    print("    python scheduler.py all --top 15")
    print()
    print("  로그 파일: logs/scheduler.log")
    print("  리포트:   data/reports/{코드}_{날짜}.json")
    print("-" * 60)
    print("  ⛔ 실거래 주문 기능은 지원하지 않습니다.")
    print("  ⚠️  API 키 없으면 Mock 모드로 실행됩니다.")
    print("=" * 60)
    print()


_ORDER_KEYWORDS = {
    "매수주문", "매도주문", "place_order", "order",
    "buy_order", "sell_order", "주문",
}


# ════════════════════════════════════════════════════════════════
# 엔트리포인트
# ════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]

    # 도움말
    if not args or args[0].lower() in ("-h", "--help", "help"):
        _print_help()
        return

    # 주문 명령 차단
    if args[0].lower() in _ORDER_KEYWORDS:
        print()
        print("⛔ 실거래 주문 기능은 지원하지 않습니다.")
        print("   본 도구는 분석 참고용으로만 사용할 수 있습니다.")
        print()
        log.warning("차단된 주문 명령 입력: %s", args[0])
        return

    # 인자 파싱
    cmd, top, min_score = _parse_args(args)

    # 라우팅
    if cmd in ("update_candidates", "update_price", "price"):
        _run_price_update(top=top, min_score=min_score)

    elif cmd in ("update_news", "news"):
        update_news_for_candidates(top=top, min_score=min_score)

    elif cmd in ("update_financial", "financial", "fin"):
        update_financial_for_candidates(top=top, min_score=min_score)

    elif cmd in ("generate_reports", "reports", "report"):
        # 리포트는 기본 min_score 를 60으로 올려서 관찰 이상만 처리
        effective_min = max(min_score, 60)
        effective_top = min(top, 10)
        if effective_min != min_score or effective_top != top:
            log.info(
                "리포트 생성: min_score=%d→%d, top=%d→%d (자동 조정)",
                min_score, effective_min, top, effective_top,
            )
        generate_reports_for_candidates(top=effective_top, min_score=effective_min)

    elif cmd in ("all",):
        update_all_candidates(top=top, min_score=min_score)

    else:
        print(f"\n❌ 알 수 없는 명령: '{cmd}'")
        _print_help()


if __name__ == "__main__":
    main()
