-- ================================================================
-- local-stock-assistant · Supabase MVP 스키마
-- Supabase 대시보드 > SQL Editor 에 붙여넣고 실행하세요.
-- PostgreSQL 15+ 기준
-- ================================================================


-- ----------------------------------------------------------------
-- 공통 함수: updated_at 자동 갱신 트리거
-- ----------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ================================================================
-- 1. stocks  –  종목 마스터
-- ================================================================
CREATE TABLE IF NOT EXISTS stocks (
    id           BIGSERIAL    PRIMARY KEY,
    stock_code   VARCHAR(10)  NOT NULL UNIQUE,   -- 종목코드 (예: 005930)
    stock_name   VARCHAR(100) NOT NULL,           -- 종목명
    market       VARCHAR(20)  NOT NULL,           -- KOSPI | KOSDAQ
    sector       VARCHAR(50),                     -- 섹터 (예: 반도체)
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stocks_code   ON stocks (stock_code);
CREATE INDEX IF NOT EXISTS idx_stocks_market ON stocks (market);
CREATE INDEX IF NOT EXISTS idx_stocks_sector ON stocks (sector);

CREATE TRIGGER trg_stocks_updated_at
    BEFORE UPDATE ON stocks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ================================================================
-- 2. candidate_scores  –  종목 점수화 결과
-- ================================================================
CREATE TABLE IF NOT EXISTS candidate_scores (
    id           BIGSERIAL    PRIMARY KEY,
    stock_code   VARCHAR(10)  NOT NULL,
    stock_name   VARCHAR(100) NOT NULL,
    score        NUMERIC(5,2) NOT NULL CHECK (score >= 0 AND score <= 100),
    decision     VARCHAR(20)  NOT NULL,           -- 매수 검토 | 관망 | 매도 검토
    reasons      TEXT,                            -- 판단 근거 (자유 텍스트)
    risks        TEXT,                            -- 리스크 요인 (자유 텍스트)
    trade_date   DATE         NOT NULL DEFAULT CURRENT_DATE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cscores_code ON candidate_scores (stock_code);
CREATE INDEX IF NOT EXISTS idx_cscores_date ON candidate_scores (trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_cscores_score ON candidate_scores (score DESC);

CREATE TRIGGER trg_candidate_scores_updated_at
    BEFORE UPDATE ON candidate_scores
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ================================================================
-- 3. news_items  –  종목별 뉴스
-- ================================================================
CREATE TABLE IF NOT EXISTS news_items (
    id            BIGSERIAL    PRIMARY KEY,
    stock_code    VARCHAR(10)  NOT NULL,
    stock_name    VARCHAR(100) NOT NULL,
    title         TEXT         NOT NULL,          -- 뉴스 제목
    summary       TEXT,                           -- 요약문
    sentiment     VARCHAR(20)  NOT NULL DEFAULT '중립적'
                      CHECK (sentiment IN ('긍정적', '다소 긍정적', '중립적', '다소 부정적', '부정적')),
    impact_score  SMALLINT     CHECK (impact_score BETWEEN 1 AND 5),  -- 영향도 1~5
    news_date     DATE         NOT NULL DEFAULT CURRENT_DATE,
    url           TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_code      ON news_items (stock_code);
CREATE INDEX IF NOT EXISTS idx_news_date      ON news_items (news_date DESC);
CREATE INDEX IF NOT EXISTS idx_news_sentiment ON news_items (sentiment);

CREATE TRIGGER trg_news_items_updated_at
    BEFORE UPDATE ON news_items
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ================================================================
-- 4. stock_reports  –  종목 상세 분석 리포트
-- ================================================================
CREATE TABLE IF NOT EXISTS stock_reports (
    id                  BIGSERIAL    PRIMARY KEY,
    stock_code          VARCHAR(10)  NOT NULL,
    stock_name          VARCHAR(100) NOT NULL,
    report_date         DATE         NOT NULL DEFAULT CURRENT_DATE,
    technical_summary   TEXT,                    -- 기술적 분석 요약
    financial_summary   TEXT,                    -- 재무 요약
    news_summary        TEXT,                    -- 뉴스 요약
    final_decision      VARCHAR(20)  NOT NULL,   -- 매수 검토 | 관망 | 매도 검토
    target_return       NUMERIC(5,2),            -- 목표 수익률 (%)
    stop_loss           NUMERIC(5,2),            -- 손절 기준 (%)
    entry_timing        TEXT,                    -- 진입 타이밍 설명
    risks               TEXT,                    -- 리스크 요인
    conclusion          TEXT,                    -- 최종 결론
    raw_json            JSONB,                   -- 분석 원본 데이터 전체
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reports_code ON stock_reports (stock_code);
CREATE INDEX IF NOT EXISTS idx_reports_date ON stock_reports (report_date DESC);
CREATE INDEX IF NOT EXISTS idx_reports_decision ON stock_reports (final_decision);
CREATE INDEX IF NOT EXISTS idx_reports_raw_json ON stock_reports USING GIN (raw_json);

CREATE TRIGGER trg_stock_reports_updated_at
    BEFORE UPDATE ON stock_reports
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ================================================================
-- 5. trade_journal  –  매매일지
-- ================================================================
CREATE TABLE IF NOT EXISTS trade_journal (
    id           BIGSERIAL     PRIMARY KEY,
    trade_date   DATE          NOT NULL DEFAULT CURRENT_DATE,
    stock_code   VARCHAR(10)   NOT NULL,
    stock_name   VARCHAR(100)  NOT NULL,
    action       VARCHAR(10)   NOT NULL CHECK (action IN ('매수', '매도')),
    entry_price  INTEGER       NOT NULL CHECK (entry_price > 0),   -- 진입 단가 (원)
    exit_price   INTEGER       CHECK (exit_price > 0),             -- 청산 단가 (매도 시)
    quantity     INTEGER       NOT NULL CHECK (quantity > 0),       -- 수량 (주)
    reason       TEXT,                                             -- 매매 이유
    result_memo  TEXT,                                             -- 결과 메모
    return_rate  NUMERIC(6,2),                                     -- 수익률 (%)
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_journal_code ON trade_journal (stock_code);
CREATE INDEX IF NOT EXISTS idx_journal_date ON trade_journal (trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_journal_action ON trade_journal (action);

CREATE TRIGGER trg_trade_journal_updated_at
    BEFORE UPDATE ON trade_journal
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ================================================================
-- 샘플 데이터 (선택 – 테스트 시 실행)
-- ================================================================

/*
INSERT INTO stocks (stock_code, stock_name, market, sector) VALUES
    ('005930', '삼성전자',      'KOSPI',  '반도체'),
    ('000660', 'SK하이닉스',    'KOSPI',  '반도체'),
    ('035720', '카카오',        'KOSPI',  'IT서비스'),
    ('035420', 'NAVER',         'KOSPI',  'IT서비스'),
    ('005380', '현대차',        'KOSPI',  '자동차')
ON CONFLICT (stock_code) DO NOTHING;
*/
