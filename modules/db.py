"""
데이터베이스 연결 모듈
Supabase 설정이 없으면 자동으로 Mock 모드로 전환됩니다.
"""

import os
from typing import Optional

_supabase_client = None
_mock_mode: bool = True

# 인메모리 Mock 저장소
_mock_trade_journal: list[dict] = []


def init_db() -> bool:
    """DB 초기화. True = Supabase 연결 성공, False = Mock 모드"""
    global _supabase_client, _mock_mode

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    force_mock = os.getenv("MOCK_MODE", "true").lower() == "true"

    if force_mock or not url or not key:
        _mock_mode = True
        return False

    try:
        from supabase import create_client
        _supabase_client = create_client(url, key)
        _mock_mode = False
        return True
    except Exception as e:
        print(f"[DB] Supabase 연결 실패 → Mock 모드로 전환: {e}")
        _mock_mode = True
        return False


def is_mock() -> bool:
    return _mock_mode


# ─── 매매일지 CRUD ─────────────────────────────────────────────


def insert_trade(record: dict) -> dict:
    """매매일지 신규 등록"""
    if _mock_mode:
        record["id"] = len(_mock_trade_journal) + 1
        _mock_trade_journal.append(record)
        return {"data": record, "error": None}

    return _supabase_client.table("trade_journal").insert(record).execute()


def fetch_trades(code: Optional[str] = None) -> list[dict]:
    """매매일지 조회. code 지정 시 해당 종목만 반환"""
    if _mock_mode:
        if code:
            return [t for t in _mock_trade_journal if t.get("종목코드") == code]
        return list(_mock_trade_journal)

    q = _supabase_client.table("trade_journal").select("*").order("날짜", desc=True)
    if code:
        q = q.eq("종목코드", code)
    result = q.execute()
    return result.data or []


def delete_trade(trade_id: int) -> bool:
    """매매일지 삭제"""
    if _mock_mode:
        before = len(_mock_trade_journal)
        _mock_trade_journal[:] = [
            t for t in _mock_trade_journal if t.get("id") != trade_id
        ]
        return len(_mock_trade_journal) < before

    result = (
        _supabase_client.table("trade_journal").delete().eq("id", trade_id).execute()
    )
    return result.data is not None
