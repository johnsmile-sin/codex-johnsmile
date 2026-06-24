-- =============================================================
-- schema_v3.sql
-- 2차 뉴스 저장 + 3차 모의투자 저장 테이블
-- Supabase SQL Editor에서 실행하세요.
-- =============================================================

-- =============================================================
-- 뉴스 기사 저장
-- =============================================================

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

CREATE UNIQUE INDEX IF NOT EXISTS uq_news_articles_key
    ON news_articles (stock_code, title, news_date);

CREATE INDEX IF NOT EXISTS idx_news_stock_date
    ON news_articles (stock_code, news_date DESC);

CREATE INDEX IF NOT EXISTS idx_news_sentiment
    ON news_articles (sentiment);

CREATE INDEX IF NOT EXISTS idx_news_source
    ON news_articles (source);

COMMENT ON TABLE  news_articles              IS '종목별 뉴스 기사. Naver API 또는 Mock.';
COMMENT ON COLUMN news_articles.source       IS 'Naver = 실제 API, Mock = 샘플 데이터';
COMMENT ON COLUMN news_articles.impact_score IS '1 낮음 ~ 5 높음 영향도';
COMMENT ON COLUMN news_articles.sentiment    IS '긍정 / 중립 / 부정';

-- =============================================================
-- 3차 모의투자 가상 주문
-- =============================================================

CREATE TABLE IF NOT EXISTS virtual_orders (
    id                  BIGSERIAL PRIMARY KEY,
    order_date          DATE          NOT NULL DEFAULT CURRENT_DATE,
    strategy_name       VARCHAR(80)   NOT NULL DEFAULT 'v3_score_momentum',
    stock_code          VARCHAR(10)   NOT NULL,
    stock_name          VARCHAR(80),
    side                VARCHAR(10)   NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity            INTEGER       NOT NULL CHECK (quantity > 0),
    price               NUMERIC(18,2) NOT NULL CHECK (price > 0),
    amount              NUMERIC(18,2) NOT NULL CHECK (amount >= 0),
    status              VARCHAR(20)   NOT NULL DEFAULT 'OPEN'
                         CHECK (status IN ('OPEN', 'CLOSED', 'CANCELLED')),
    reason              TEXT,
    score               INTEGER       DEFAULT 0,
    decision            VARCHAR(20),
    linked_buy_order_id BIGINT,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_virtual_orders_strategy_date
    ON virtual_orders (strategy_name, order_date DESC);

CREATE INDEX IF NOT EXISTS idx_virtual_orders_stock_date
    ON virtual_orders (stock_code, order_date DESC);

CREATE INDEX IF NOT EXISTS idx_virtual_orders_side
    ON virtual_orders (side);

COMMENT ON TABLE virtual_orders IS '3차 모의투자 가상 주문 기록. 실거래 주문 아님.';
COMMENT ON COLUMN virtual_orders.strategy_name IS '전략명. 예: v3_score_momentum';
COMMENT ON COLUMN virtual_orders.side IS 'BUY/SELL 가상 주문 구분';
COMMENT ON COLUMN virtual_orders.reason IS '가상 주문 생성 사유';
