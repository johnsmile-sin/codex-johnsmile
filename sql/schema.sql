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
    sentiment     VARCHAR(20)  NOT NULL DEFAULT '중립'
                      CHECK (sentiment IN ('긍정', '중립', '부정')),
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
    target_return       TEXT,                    -- 목표 수익률 (예: "+12% 내외")
    stop_loss           TEXT,                    -- 손절 라인 (예: "74,500원 (-5.0%)")
    entry_timing        TEXT,                    -- 진입 타이밍 설명
    risks               TEXT,                    -- 리스크 요인
    conclusion          TEXT,                    -- 최종 결론
    raw_json            JSONB,                   -- 분석 원본 데이터 전체
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_stock_reports_code_date UNIQUE (stock_code, report_date)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_stock_reports_code_date'
    ) THEN
        ALTER TABLE stock_reports
            ADD CONSTRAINT uq_stock_reports_code_date UNIQUE (stock_code, report_date);
    END IF;
END;
$$;

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
    action       VARCHAR(10)   NOT NULL CHECK (action IN ('매수', '매도', '메모')),
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

-- =============================================================
-- 3차 확장: 모의투자 / 전략 검증 / 백테스트
-- 실거래 주문 테이블이 아닙니다.
-- Supabase SQL Editor에서 실행 가능합니다.
-- =============================================================

CREATE TABLE IF NOT EXISTS virtual_portfolio (
    id                 BIGSERIAL PRIMARY KEY,
    portfolio_name     VARCHAR(100) NOT NULL UNIQUE,
    initial_cash       NUMERIC(18,2) NOT NULL DEFAULT 10000000 CHECK (initial_cash >= 0),
    cash_balance       NUMERIC(18,2) NOT NULL DEFAULT 10000000 CHECK (cash_balance >= 0),
    total_asset        NUMERIC(18,2) NOT NULL DEFAULT 10000000 CHECK (total_asset >= 0),
    total_profit_loss  NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_return_rate  NUMERIC(10,4) NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_virtual_portfolio_name
    ON virtual_portfolio (portfolio_name);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_virtual_portfolio_updated_at') THEN
        CREATE TRIGGER trg_virtual_portfolio_updated_at
            BEFORE UPDATE ON virtual_portfolio
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS virtual_orders (
    id             BIGSERIAL PRIMARY KEY,
    portfolio_id   BIGINT NOT NULL REFERENCES virtual_portfolio(id) ON DELETE CASCADE,
    order_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    stock_code     VARCHAR(10) NOT NULL,
    stock_name     VARCHAR(100) NOT NULL,
    strategy_name  VARCHAR(100),
    order_type     VARCHAR(20) NOT NULL CHECK (order_type IN ('가상매수', '가상매도')),
    order_price    NUMERIC(18,2) NOT NULL CHECK (order_price > 0),
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    order_amount   NUMERIC(18,2) NOT NULL CHECK (order_amount >= 0),
    order_status   VARCHAR(20) NOT NULL DEFAULT '체결'
                   CHECK (order_status IN ('대기', '체결', '취소', '실패')),
    reason         TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_virtual_orders_portfolio_date
    ON virtual_orders (portfolio_id, order_date DESC);

CREATE INDEX IF NOT EXISTS idx_virtual_orders_stock_date
    ON virtual_orders (stock_code, order_date DESC);

CREATE INDEX IF NOT EXISTS idx_virtual_orders_strategy_date
    ON virtual_orders (strategy_name, order_date DESC);

CREATE INDEX IF NOT EXISTS idx_virtual_orders_type_status
    ON virtual_orders (order_type, order_status);

CREATE TABLE IF NOT EXISTS virtual_positions (
    id                 BIGSERIAL PRIMARY KEY,
    portfolio_id       BIGINT NOT NULL REFERENCES virtual_portfolio(id) ON DELETE CASCADE,
    stock_code         VARCHAR(10) NOT NULL,
    stock_name         VARCHAR(100) NOT NULL,
    strategy_name      VARCHAR(100),
    entry_date         DATE NOT NULL DEFAULT CURRENT_DATE,
    entry_price        NUMERIC(18,2) NOT NULL CHECK (entry_price > 0),
    quantity           INTEGER NOT NULL CHECK (quantity > 0),
    current_price      NUMERIC(18,2) NOT NULL CHECK (current_price >= 0),
    evaluation_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,
    profit_loss        NUMERIC(18,2) NOT NULL DEFAULT 0,
    return_rate        NUMERIC(10,4) NOT NULL DEFAULT 0,
    stop_loss_price    NUMERIC(18,2) CHECK (stop_loss_price >= 0),
    target_price       NUMERIC(18,2) CHECK (target_price >= 0),
    holding_days       INTEGER NOT NULL DEFAULT 0 CHECK (holding_days >= 0),
    status             VARCHAR(20) NOT NULL DEFAULT '보유'
                       CHECK (status IN ('보유', '청산', '손절', '익절')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_virtual_positions_portfolio_status
    ON virtual_positions (portfolio_id, status);

CREATE INDEX IF NOT EXISTS idx_virtual_positions_stock
    ON virtual_positions (stock_code);

CREATE INDEX IF NOT EXISTS idx_virtual_positions_strategy
    ON virtual_positions (strategy_name);

CREATE UNIQUE INDEX IF NOT EXISTS uq_virtual_positions_open
    ON virtual_positions (portfolio_id, stock_code, strategy_name)
    WHERE status = '보유';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_virtual_positions_updated_at') THEN
        CREATE TRIGGER trg_virtual_positions_updated_at
            BEFORE UPDATE ON virtual_positions
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS strategy_rules (
    id                   BIGSERIAL PRIMARY KEY,
    strategy_name        VARCHAR(100) NOT NULL UNIQUE,
    description          TEXT,
    min_score            INTEGER NOT NULL DEFAULT 75 CHECK (min_score BETWEEN 0 AND 100),
    take_profit_rate     NUMERIC(10,4) NOT NULL DEFAULT 8.0,
    stop_loss_rate       NUMERIC(10,4) NOT NULL DEFAULT -4.0,
    max_holding_days     INTEGER NOT NULL DEFAULT 20 CHECK (max_holding_days > 0),
    max_position_amount  NUMERIC(18,2) NOT NULL DEFAULT 2000000 CHECK (max_position_amount >= 0),
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    rule_json            JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_rules_active
    ON strategy_rules (is_active);

CREATE INDEX IF NOT EXISTS idx_strategy_rules_json
    ON strategy_rules USING GIN (rule_json);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_strategy_rules_updated_at') THEN
        CREATE TRIGGER trg_strategy_rules_updated_at
            BEFORE UPDATE ON strategy_rules
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS strategy_performance (
    id                 BIGSERIAL PRIMARY KEY,
    strategy_name      VARCHAR(100) NOT NULL UNIQUE,
    total_trades       INTEGER NOT NULL DEFAULT 0 CHECK (total_trades >= 0),
    win_trades         INTEGER NOT NULL DEFAULT 0 CHECK (win_trades >= 0),
    lose_trades        INTEGER NOT NULL DEFAULT 0 CHECK (lose_trades >= 0),
    win_rate           NUMERIC(10,4) NOT NULL DEFAULT 0,
    avg_return_rate    NUMERIC(10,4) NOT NULL DEFAULT 0,
    total_return_rate  NUMERIC(10,4) NOT NULL DEFAULT 0,
    max_drawdown       NUMERIC(10,4) NOT NULL DEFAULT 0,
    profit_factor      NUMERIC(18,6) NOT NULL DEFAULT 0,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_performance_return
    ON strategy_performance (total_return_rate DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_performance_win_rate
    ON strategy_performance (win_rate DESC);

CREATE TABLE IF NOT EXISTS backtest_results (
    id                 BIGSERIAL PRIMARY KEY,
    strategy_name      VARCHAR(100) NOT NULL,
    start_date         DATE NOT NULL,
    end_date           DATE NOT NULL,
    initial_cash       NUMERIC(18,2) NOT NULL CHECK (initial_cash >= 0),
    final_asset        NUMERIC(18,2) NOT NULL CHECK (final_asset >= 0),
    total_return_rate  NUMERIC(10,4) NOT NULL DEFAULT 0,
    win_rate           NUMERIC(10,4) NOT NULL DEFAULT 0,
    max_drawdown       NUMERIC(10,4) NOT NULL DEFAULT 0,
    total_trades       INTEGER NOT NULL DEFAULT 0 CHECK (total_trades >= 0),
    result_json        JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_backtest_results_strategy_date
    ON backtest_results (strategy_name, start_date DESC, end_date DESC);

CREATE INDEX IF NOT EXISTS idx_backtest_results_return
    ON backtest_results (total_return_rate DESC);

CREATE INDEX IF NOT EXISTS idx_backtest_results_json
    ON backtest_results USING GIN (result_json);

CREATE TABLE IF NOT EXISTS risk_settings (
    id                       BIGSERIAL PRIMARY KEY,
    max_daily_loss_rate      NUMERIC(10,4) NOT NULL DEFAULT -3.0,
    max_position_count       INTEGER NOT NULL DEFAULT 5 CHECK (max_position_count > 0),
    max_position_amount      NUMERIC(18,2) NOT NULL DEFAULT 2000000 CHECK (max_position_amount >= 0),
    max_single_stock_ratio   NUMERIC(10,4) NOT NULL DEFAULT 20.0
                             CHECK (max_single_stock_ratio >= 0 AND max_single_stock_ratio <= 100),
    allow_virtual_trading    BOOLEAN NOT NULL DEFAULT TRUE,
    allow_real_trading       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_settings_flags
    ON risk_settings (allow_virtual_trading, allow_real_trading);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_risk_settings_updated_at') THEN
        CREATE TRIGGER trg_risk_settings_updated_at
            BEFORE UPDATE ON risk_settings
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END;
$$;

INSERT INTO virtual_portfolio (
    portfolio_name,
    initial_cash,
    cash_balance,
    total_asset,
    total_profit_loss,
    total_return_rate
) VALUES (
    '기본 모의투자',
    10000000,
    10000000,
    10000000,
    0,
    0
) ON CONFLICT (portfolio_name) DO NOTHING;

INSERT INTO strategy_rules (
    strategy_name,
    description,
    min_score,
    take_profit_rate,
    stop_loss_rate,
    max_holding_days,
    max_position_amount,
    is_active,
    rule_json
) VALUES (
    'v3_score_momentum',
    '후보 점수와 추세 조건을 활용하는 3차 기본 모의투자 전략',
    75,
    8.0,
    -4.0,
    20,
    2000000,
    TRUE,
    '{"buy_decisions":["강한 관심","관심"],"sell_decisions":["보류","제외"],"real_order":false}'::JSONB
) ON CONFLICT (strategy_name) DO NOTHING;

INSERT INTO risk_settings (
    max_daily_loss_rate,
    max_position_count,
    max_position_amount,
    max_single_stock_ratio,
    allow_virtual_trading,
    allow_real_trading
) SELECT
    -3.0,
    5,
    2000000,
    20.0,
    TRUE,
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM risk_settings);
