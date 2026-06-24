"""
services/telegram_bot.py
양방향 텔레그램 봇 — 명령 수신 + 응답 (polling 방식)

지원 명령:
  /start      - 봇 소개
  /status     - 시스템 상태 조회
  /signals    - 최근 매매 신호 목록
  /portfolio  - 모의 포트폴리오 현황
  /stop       - 긴급 중지 (emergency_stop ON)
  /resume     - 긴급 중지 해제
  /help       - 도움말

실행 방법:
  python -m services.telegram_bot
  또는 openclaw 명령 통해 백그라운드 실행
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _allowed_chat_id() -> int | None:
    """허용된 채팅 ID (보안: 등록된 사용자만 명령 수신)"""
    raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return int(raw) if raw else None


def _is_authorized(update: Update) -> bool:
    allowed = _allowed_chat_id()
    if allowed is None:
        return False
    return update.effective_chat.id == allowed


# ─── 명령 핸들러 ─────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    text = (
        "👋 <b>주식 어시스턴트 봇</b>에 오신 것을 환영합니다!\n\n"
        "사용 가능한 명령어:\n"
        "/status — 시스템 상태\n"
        "/signals — 최근 매매 신호\n"
        "/portfolio — 모의 포트폴리오\n"
        "/stop — 긴급 중지\n"
        "/resume — 긴급 중지 해제\n"
        "/help — 도움말\n\n"
        "⚠️ <i>현재 analysis_only 모드 — 자동주문 없음</i>"
    )
    await update.message.reply_html(text)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    try:
        from services.system_settings import get_system_settings
        settings = get_system_settings()
        trading_mode = settings.get("trading_mode", "알 수 없음")
        emergency_stop = settings.get("emergency_stop", False)
        allow_real = settings.get("allow_real_trading", False)

        stop_icon = "🚨 ON" if emergency_stop else "✅ OFF"
        text = (
            f"⚙️ <b>시스템 상태</b>\n\n"
            f"거래 모드: <b>{trading_mode}</b>\n"
            f"긴급 중지: {stop_icon}\n"
            f"실거래 허용: {'❌ 차단' if not allow_real else '⚠️ 허용'}\n"
        )
    except Exception as e:
        text = f"⚠️ 상태 조회 실패: {e}"
    await update.message.reply_html(text)


async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    try:
        from services.supabase_client import get_supabase_client
        client = get_supabase_client()
        rows = (
            client.table("trade_signals")
            .select("stock_code,stock_name,signal_type,reason,created_at")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
            .data
        )
        if not rows:
            text = "📭 최근 매매 신호가 없습니다."
        else:
            lines = ["📋 <b>최근 매매 신호 (최대 5건)</b>\n"]
            for r in rows:
                emoji = "🟢" if r.get("signal_type") == "매수신호" else "🔴"
                ts = r.get("created_at", "")[:16].replace("T", " ")
                lines.append(
                    f"{emoji} {r.get('stock_name','?')}({r.get('stock_code','?')}) "
                    f"— {r.get('signal_type','?')}\n"
                    f"   {r.get('reason','')[:40]} [{ts}]"
                )
            text = "\n".join(lines)
    except Exception as e:
        text = f"⚠️ 신호 조회 실패: {e}"
    await update.message.reply_html(text)


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    try:
        from services.supabase_client import get_supabase_client
        client = get_supabase_client()
        rows = (
            client.table("virtual_positions")
            .select("stock_code,stock_name,quantity,avg_price,current_price")
            .gt("quantity", 0)
            .execute()
            .data
        )
        if not rows:
            text = "📭 보유 종목이 없습니다."
        else:
            lines = ["💼 <b>모의 포트폴리오</b>\n"]
            total_eval = 0
            for r in rows:
                qty = r.get("quantity", 0)
                avg = r.get("avg_price", 0)
                cur = r.get("current_price", avg)
                eval_val = qty * cur
                pnl_rate = (cur - avg) / avg * 100 if avg else 0
                total_eval += eval_val
                lines.append(
                    f"• {r.get('stock_name','?')}({r.get('stock_code','?')}) "
                    f"{qty:,}주 | {pnl_rate:+.1f}%"
                )
            lines.append(f"\n총 평가: {total_eval:,.0f}원")
            text = "\n".join(lines)
    except Exception as e:
        text = f"⚠️ 포트폴리오 조회 실패: {e}"
    await update.message.reply_html(text)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    try:
        from services.system_settings import set_emergency_stop
        set_emergency_stop(True)
        text = "🚨 <b>긴급 중지 활성화</b>\n모든 자동 처리가 중단되었습니다."
    except Exception as e:
        text = f"⚠️ 긴급 중지 실패: {e}"
    await update.message.reply_html(text)


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    try:
        from services.system_settings import set_emergency_stop
        set_emergency_stop(False)
        text = "✅ <b>긴급 중지 해제</b>\n시스템이 정상 상태로 복귀했습니다."
    except Exception as e:
        text = f"⚠️ 해제 실패: {e}"
    await update.message.reply_html(text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    text = (
        "📖 <b>도움말</b>\n\n"
        "/start — 봇 소개\n"
        "/status — 시스템 모드·긴급중지 상태\n"
        "/signals — 최근 매매 신호 5건\n"
        "/portfolio — 모의 보유 종목 현황\n"
        "/stop — 긴급 중지 ON\n"
        "/resume — 긴급 중지 OFF\n"
        "/help — 이 도움말\n\n"
        "⚠️ <i>등록된 사용자만 명령을 수신합니다.</i>"
    )
    await update.message.reply_html(text)


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await update.message.reply_text("❓ 알 수 없는 명령입니다. /help 를 입력하세요.")


# ─── 봇 실행 ──────────────────────────────────────────────────────────

def run_bot() -> None:
    """봇 polling 시작 (블로킹)"""
    token = _token()
    if not token:
        logger.error("[TelegramBot] TELEGRAM_BOT_TOKEN 이 설정되지 않았습니다.")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("signals",   cmd_signals))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("stop",      cmd_stop))
    app.add_handler(CommandHandler("resume",    cmd_resume))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    logger.info("[TelegramBot] 봇 시작 (polling)...")
    print("텔레그램 봇 실행 중... Ctrl+C 로 종료")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_bot()
