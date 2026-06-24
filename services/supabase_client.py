"""
Supabase 연결 클라이언트
- .env 에서 SUPABASE_URL, SUPABASE_ANON_KEY 를 읽는다.
- MOCK_MODE=true 이면 Supabase 키가 있어도 Mock 모드로 실행한다.
- 둘 중 하나라도 없으면 Mock 모드로 전환된다.
- 모듈 임포트 시 1회만 연결을 시도한다.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_client = None
_connected: bool = False
_error_message: str = ""


def _is_mock_mode() -> bool:
    return os.getenv("MOCK_MODE", "false").strip().lower() in {"1", "true", "yes", "y", "on"}


def _init() -> None:
    global _client, _connected, _error_message

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_ANON_KEY", "").strip()

    if _is_mock_mode():
        _error_message = "MOCK_MODE=true"
        logger.info("[Supabase] MOCK_MODE=true → Mock 모드로 실행합니다.")
        return

    # 환경변수 누락 → Mock 모드
    if not url or not key:
        missing = []
        if not url:
            missing.append("SUPABASE_URL")
        if not key:
            missing.append("SUPABASE_ANON_KEY")
        _error_message = f"환경변수 미설정: {', '.join(missing)}"
        logger.info("[Supabase] %s → Mock 모드로 실행합니다.", _error_message)
        return

    try:
        from supabase import create_client, Client
        _client = create_client(url, key)
        _connected = True
        logger.info("[Supabase] 연결 성공: %s", url)
    except ImportError:
        _error_message = "supabase 패키지가 설치되지 않았습니다. (pip install supabase)"
        logger.warning("[Supabase] %s", _error_message)
    except Exception as e:
        _error_message = str(e)
        logger.warning("[Supabase] 연결 실패: %s", e)


# 모듈 로드 시 1회 실행
_init()


def get_client():
    """연결된 Supabase 클라이언트를 반환. 미연결 시 None."""
    return _client


def is_connected() -> bool:
    """Supabase 연결 여부"""
    return _connected


def get_error() -> str:
    """연결 실패 이유 반환"""
    return _error_message
