"""
Mock DB 서비스
Supabase 연결 없이 샘플 데이터를 반환합니다.
save_* 함수는 인메모리 리스트에 저장하며 앱 재시작 시 초기화됩니다.
"""

from datetime import date, datetime
from data.mock_stocks import MOCK_STOCKS

# ── 인메모리 저장소 ───────────────────────────────────────────
_candidate_scores: list[dict] = []
_news_items: list[dict] = []
_stock_reports: list[dict] = []
_trade_journal: list[dict] = []
_next_id: dict[str, int] = {
    "candidate_scores": 1,
    "news_items": 1,
    "stock_reports": 1,
    "trade_journal": 1,
}


def _now() -> str:
    return datetime.now().isoformat()


def _next(table: str) -> int:
    _id = _next_id[table]
    _next_id[table] += 1
    return _id


# ── stocks ───────────────────────────────────────────────────

def get_stocks() -> list[dict]:
    """종목 마스터 30개 반환"""
    return [
        {
            "id": i + 1,
            "stock_code": s["code"],
            "stock_name": s["name"],
            "market": s["market"],
            "sector": s["sector"],
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        for i, s in enumerate(MOCK_STOCKS)
    ]


# ── candidate_scores ─────────────────────────────────────────

def save_candidate_scores(data: dict) -> dict:
    """점수 결과 저장"""
    record = {
        "id": _next("candidate_scores"),
        "stock_code":  data.get("stock_code", ""),
        "stock_name":  data.get("stock_name", ""),
        "score":       data.get("score", 0),
        "decision":    data.get("decision", "관망"),
        "reasons":     data.get("reasons", ""),
        "risks":       data.get("risks", ""),
        "trade_date":  data.get("trade_date", str(date.today())),
        "created_at":  _now(),
        "updated_at":  _now(),
    }
    _candidate_scores.append(record)
    return record


def get_candidate_scores() -> list[dict]:
    """저장된 점수 결과 반환. 비어 있으면 샘플 5건 반환"""
    if _candidate_scores:
        return sorted(_candidate_scores, key=lambda x: x["trade_date"], reverse=True)

    # 샘플 데이터
    samples = [
        ("005930", "삼성전자",   82.4, "매수 검토", "RSI 양호, 골든크로스",          "금리 리스크"),
        ("000660", "SK하이닉스", 76.1, "매수 검토", "PBR 저평가, 수급 개선",          "재고 조정 우려"),
        ("035420", "NAVER",      61.3, "관망",      "볼린저밴드 중간대",               "광고 매출 둔화"),
        ("005380", "현대차",     55.8, "관망",      "ROE 양호하나 모멘텀 약함",       "환율 변동성"),
        ("051910", "LG화학",     43.2, "관망",      "PER 고평가 구간",                "배터리 경쟁 심화"),
    ]
    today = str(date.today())
    return [
        {
            "id": i + 1,
            "stock_code": code,
            "stock_name": name,
            "score":      score,
            "decision":   decision,
            "reasons":    reasons,
            "risks":      risks,
            "trade_date": today,
            "created_at": _now(),
            "updated_at": _now(),
        }
        for i, (code, name, score, decision, reasons, risks) in enumerate(samples)
    ]


# ── news_items ───────────────────────────────────────────────

def save_news_items(data: dict) -> dict:
    record = {
        "id":           _next("news_items"),
        "stock_code":   data.get("stock_code", ""),
        "stock_name":   data.get("stock_name", ""),
        "title":        data.get("title", ""),
        "summary":      data.get("summary", ""),
        "sentiment":    data.get("sentiment", "중립적"),
        "impact_score": data.get("impact_score", 3),
        "news_date":    data.get("news_date", str(date.today())),
        "url":          data.get("url", ""),
        "created_at":   _now(),
        "updated_at":   _now(),
    }
    _news_items.append(record)
    return record


def get_news_items(stock_code: str | None = None) -> list[dict]:
    """뉴스 반환. 비어 있으면 샘플 반환"""
    if _news_items:
        items = _news_items
        if stock_code:
            items = [n for n in items if n["stock_code"] == stock_code]
        return sorted(items, key=lambda x: x["news_date"], reverse=True)

    today = str(date.today())
    samples = [
        {
            "id": 1, "stock_code": "005930", "stock_name": "삼성전자",
            "title": "삼성전자, 3분기 영업이익 10조 돌파 전망",
            "summary": "반도체 업황 회복으로 3분기 실적 개선 기대. 증권가 목표주가 줄상향.",
            "sentiment": "긍정", "impact_score": 5,
            "news_date": today, "url": "", "created_at": _now(), "updated_at": _now(),
        },
        {
            "id": 2, "stock_code": "000660", "stock_name": "SK하이닉스",
            "title": "SK하이닉스 HBM 공급 확대…AI 수요 수혜",
            "summary": "HBM3E 생산 본격화로 엔비디아 공급 비중 증가. 수익성 개선 기대.",
            "sentiment": "긍정", "impact_score": 4,
            "news_date": today, "url": "", "created_at": _now(), "updated_at": _now(),
        },
        {
            "id": 3, "stock_code": "035420", "stock_name": "NAVER",
            "title": "NAVER, AI 검색 서비스 하이퍼클로바X 전면 도입",
            "summary": "AI 기반 검색 광고 수익 모델 전환. 단기 수익성보다 중장기 성장성 주목.",
            "sentiment": "중립", "impact_score": 3,
            "news_date": today, "url": "", "created_at": _now(), "updated_at": _now(),
        },
    ]
    if stock_code:
        return [s for s in samples if s["stock_code"] == stock_code]
    return samples


# ── stock_reports ────────────────────────────────────────────

def save_stock_report(data: dict) -> dict:
    record = {
        "id":                 _next("stock_reports"),
        "stock_code":         data.get("stock_code", ""),
        "stock_name":         data.get("stock_name", ""),
        "report_date":        data.get("report_date", str(date.today())),
        "technical_summary":  data.get("technical_summary", ""),
        "financial_summary":  data.get("financial_summary", ""),
        "news_summary":       data.get("news_summary", ""),
        "final_decision":     data.get("final_decision", "관망"),
        "target_return":      data.get("target_return"),
        "stop_loss":          data.get("stop_loss"),
        "entry_timing":       data.get("entry_timing", ""),
        "risks":              data.get("risks", ""),
        "conclusion":         data.get("conclusion", ""),
        "raw_json":           data.get("raw_json"),
        "created_at":         _now(),
        "updated_at":         _now(),
    }
    _stock_reports.append(record)
    return record


def get_stock_reports(stock_code: str | None = None) -> list[dict]:
    """리포트 반환. 비어 있으면 샘플 반환"""
    if _stock_reports:
        items = _stock_reports
        if stock_code:
            items = [r for r in items if r["stock_code"] == stock_code]
        return sorted(items, key=lambda x: x["report_date"], reverse=True)

    today = str(date.today())
    samples = [
        {
            "id": 1, "stock_code": "005930", "stock_name": "삼성전자",
            "report_date": today,
            "technical_summary": "RSI 45, MACD 골든크로스, MA 정배열 진행 중",
            "financial_summary": "PER 12.4배, ROE 18.2% — 반도체 업종 내 저평가",
            "news_summary": "HBM 수요 증가, 파운드리 수주 확대 기대",
            "final_decision": "매수 검토",
            "target_return": 12.0, "stop_loss": -3.0,
            "entry_timing": "74,500원 이하 분할 매수",
            "risks": "미국 수출 규제 강화, 환율 급변",
            "conclusion": "중장기 분할 매수 유효. 손절 원칙 준수 필수.",
            "raw_json": None,
            "created_at": _now(), "updated_at": _now(),
        }
    ]
    if stock_code:
        return [r for r in samples if r["stock_code"] == stock_code]
    return samples


# ── trade_journal ────────────────────────────────────────────

def save_trade_journal(data: dict) -> dict:
    record = {
        "id":          _next("trade_journal"),
        "trade_date":  data.get("trade_date", str(date.today())),
        "stock_code":  data.get("stock_code", ""),
        "stock_name":  data.get("stock_name", ""),
        "action":      data.get("action", "매수"),
        "entry_price": data.get("entry_price", 0),
        "exit_price":  data.get("exit_price"),
        "quantity":    data.get("quantity", 0),
        "reason":      data.get("reason", ""),
        "result_memo": data.get("result_memo", ""),
        "return_rate": data.get("return_rate"),
        "created_at":  _now(),
        "updated_at":  _now(),
    }
    _trade_journal.append(record)
    return record


def get_trade_journal() -> list[dict]:
    """매매일지 전체 반환"""
    return sorted(_trade_journal, key=lambda x: x["trade_date"], reverse=True)
