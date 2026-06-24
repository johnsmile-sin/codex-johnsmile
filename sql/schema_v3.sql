-- =============================================================
-- schema_v3.sql  —  뉴스 기사 저장 테이블
-- Supabase SQL Editor 에 붙여넣어 실행하세요.
-- =============================================================

-- ── news_articles ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_articles (
    id           BIGSERIAL PRIMARY KEY,
    stock_code   VARCHAR(10)  NOT NULL,
    stock_name   VARCHAR(50),
    title        TEXT         NOT NULL,
    summary      TEXT,
    sentiment    VARCHAR(10)  NOT NULL DEFAULT '중립'
                     CHECK (sentiment IN ('긍정', '중립', '부정')),
    impact_score INTEGER      NOT NULL DEFAULT 3
                     CHECK (impact_score BETWEEN 1 AND 5),
    news_date    DATE         NOT NULL,
    url          TEXT,
    source       VARCHAR(20)  NOT NULL DEFAULT 'Mock'
                     CHECK (source IN ('Naver', 'Mock', '기타')),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 중복 방지: 같은 종목 + 제목 + 날짜 조합은 1건만
CREATE UNIQUE INDEX IF NOT EXISTS uq_news_articles_key
    ON news_articles (stock_code, title, news_date);

-- 조회 성능 인덱스
CREATE INDEX IF NOT EXISTS idx_news_stock_date
    ON news_articles (stock_code, news_date DESC);

CREATE INDEX IF NOT EXISTS idx_news_sentiment
    ON news_articles (sentiment);

CREATE INDEX IF NOT EXISTS idx_news_source
    ON news_articles (source);

COMMENT ON TABLE  news_articles               IS '종목별 뉴스 기사 (Naver API 또는 Mock)';
COMMENT ON COLUMN news_articles.source        IS 'Naver = 실제 API, Mock = 샘플 데이터';
COMMENT ON COLUMN news_articles.impact_score  IS '1(낮음) ~ 5(높음) 영향도';
COMMENT ON COLUMN news_articles.sentiment     IS '긍정 / 중립 / 부정';
