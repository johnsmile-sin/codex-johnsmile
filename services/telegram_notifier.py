"""
services/telegram_notifier.py
단방향 텔레그램 메시지 전송 서비스 (알림 전용)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.telegram.org/bot{token}/{method}"


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _chat_id() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()


def is_available() -> bool:
    return bool(_token() and _chat_id())


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """텔레그램으로 메시지 전송. 성공 시 True."""
    if not is_available():
        logger.warning("[Telegram] 봇 토큰 또는 채팅 ID 미설정")
        return False
    try:
        url = _BASE_URL.format(token=_token(), method="sendMessage")
        resp = requests.post(
            url,
            json={"chat_id": _chat_id(), "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("ok", False)
    except Exception as e:
        logger.error("[Telegram] 전송 실패: %s", e)
        return False


# ─── 알림 유형별 헬퍼 ───────────────────────────────────────────────

def notify_signal(stock_code: str, stock_name: str, signal_type: str,
                  reason: str, price: float) -> bool:
    """매매 신호 알림"""
    emoji = "🟢" if signal_type == "매수신호" else "🔴"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = (
        f"{emoji} <b>[매매신호] {signal_type}</b>\n"
        f"종목: {stock_name} ({stock_code})\n"
        f"현재가: {price:,.0f}원\n"
        f"근거: {reason}\n"
        f"시각: {now}\n"
        f"⚠️ <i>analysis_only 모드 — 자동주문 없음</i>"
    )
    return send_message(text)


def notify_emergency_stop(reason: str) -> bool:
    """긴급 중지 알림"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = (
        f"🚨 <b>[긴급중지] 시스템 중단</b>\n"
        f"사유: {reason}\n"
        f"시각: {now}\n"
        f"모든 자동 처리가 중단되었습니다."
    )
    return send_message(text)


def notify_daily_summary(portfolio_value: float, daily_pnl: float,
                         signal_count: int) -> bool:
    """일일 요약 알림"""
    pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
    now = datetime.now().strftime("%Y-%m-%d")
    text = (
        f"📊 <b>[일일 요약] {now}</b>\n"
        f"평가금액: {portfolio_value:,.0f}원\n"
        f"일손익: {pnl_emoji} {daily_pnl:+,.0f}원\n"
        f"금일 신호: {signal_count}건"
    )
    return send_message(text)


def notify_system_status(status: str, details: str = "") -> bool:
    """시스템 상태 알림"""
    text = f"ℹ️ <b>[시스템]</b> {status}"
    if details:
        text += f"\n{details}"
    return send_message(text)
