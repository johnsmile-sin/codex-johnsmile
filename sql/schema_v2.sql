-- ================================================================
-- local-stock-assistant · Supabase 2차 스키마 확장
-- Supabase 대시보드 > SQL Editor 에 붙여넣고 실행하세요.
-- PostgreSQL 15+ 기준
--
-- 기존 테이블(stocks, candidate_scores, news_items,
--             stock_reports, trade_journal)은 그대로 유지됩니다.
-- ================================================================


-- ================================================================
-- 6. daily_prices  –  종목 일봉 가격 이력
-- ================================================================
CREATE TABLE IF NOT EXISTS daily_prices (
    id             BIGSERIAL     PRIMARY KEY,
    stock_code     VARCHAR(10)   NOT NULL,
    stock_name     VARCHAR(100)  NOT NULL,
    price_date     DATE          NOT NULL,

    -- 가격 (원, 정수)
    open           INTEGER       NOT NULL CHECK (open  > 0),
    high           INTEGER       NOT NULL CHECK (high  > 0),
    low            INTEGER       NOT NULL CHECK (low   > 0),
    close          INTEGER       NOT NULL CHECK (close > 0),

    -- 거래량 / 거래대금
    volume         BIGINT        NOT NULL CHECK (volume >= 0),
    trading_value  NUMERIC(18,1),                      -- 거래대금 (억원)

    -- 지표
    change_rate    NUMERIC(7,2),                        -- 등락률 (%)
    ma5            INTEGER,                             -- 5일 이동평균
    ma20           INTEGER,                             -- 20일 이동평균
    ma60           INTEGER,                             -- 60일 이동평균
    rsi14          NUMERIC(6,2)  CHECK (rsi14 BETWEEN 0 AND 100),  -- RSI(14)

    -- 메타
    source         VARCHAR(50)   NOT NULL DEFAULT 'FinanceDataReader',
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_daily_prices_code_date UNIQUE (stock_code, price_date)
);

-- 종목 + 날짜 역순 (가장 빈번한 조회 패턴)
CREATE INDEX IF NOT EXISTS idx_dp_code_date
    ON daily_prices (stock_code, price_date DESC);

-- 날짜 전체 조회 (당일 전종목 bulk 조회)
CREATE INDEX IF NOT EXISTS idx_dp_date
    ON daily_prices (price_date DESC);

-- 출처별 필터
CREATE INDEX IF NOT EXISTS idx_dp_source
    ON daily_prices (source);


-- ================================================================
-- 7. financial_metrics  –  종목 재무 지표 (연간 / 분기)
-- ================================================================
CREATE TABLE IF NOT EXISTS financial_metrics (
    id               BIGSERIAL     PRIMARY KEY,
    stock_code       VARCHAR(10)   NOT NULL,
    stock_name       VARCHAR(100)  NOT NULL,
    fiscal_year      VARCHAR(10)   NOT NULL,    -- 예: '2023', '2023-Q3'

    -- 손익계산서 (단위: 원)
    revenue          BIGINT,                    -- 매출액
    operating_profit BIGINT,                    -- 영업이익
    net_income       BIGINT,                    -- 당기순이익

    -- 수익성 비율 (%)
    operating_margin NUMERIC(8,2),             -- 영업이익률
    net_margin       NUMERIC(8,2),             -- 순이익률

    -- 가치 / 안정성 지표
    per              NUMERIC(9,2),             -- PER (배)
    pbr              NUMERIC(9,2),             -- PBR (배)
    roe              NUMERIC(8,2),             -- ROE (%)
    debt_ratio       NUMERIC(9,2),             -- 부채비율 (%)
    current_ratio    NUMERIC(9,2),             -- 유동비율 (%)

    -- 메타
    source           VARCHAR(50)   NOT NULL DEFAULT 'DART',
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_fin_metrics_code_year UNIQUE (stock_code, fiscal_year)
);

-- 종목 + 연도 역순 (최신 재무 우선 조회)
CREATE INDEX IF NOT EXISTS idx_fm_code_year
    ON financial_metrics (stock_code, fiscal_year DESC);

-- 연도 전체 조회 (동기화 기준)
CREATE INDEX IF NOT EXISTS idx_fm_year
    ON financial_metrics (fiscal_year DESC);

-- 출처별 필터
CREATE INDEX IF NOT EXISTS idx_fm_source
    ON financial_metrics (source);


-- ================================================================
-- 8. api_run_logs  –  데이터 수집 작업 실행 로그
-- ================================================================
CREATE TABLE IF NOT EXISTS api_run_logs (
    id           BIGSERIAL    PRIMARY KEY,
    job_name     VARCHAR(100) NOT NULL,
    status       VARCHAR(20)  NOT NULL
                     CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    message      TEXT,                          -- 결과 메시지 또는 에러 내용
    started_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ                    -- NULL = 아직 실행 중
);

-- 작업명 + 시작시각 역순 (최근 실행 이력 조회)
CREATE INDEX IF NOT EXISTS idx_arl_job_started
    ON api_run_logs (job_name, started_at DESC);

-- 상태별 필터 (failed 빠른 조회)
CREATE INDEX IF NOT EXISTS idx_arl_status
    ON api_run_logs (status);

-- 전체 시간순 조회
CREATE INDEX IF NOT EXISTS idx_arl_started
    ON api_run_logs (started_at DESC);


-- ================================================================
-- 9. data_sources  –  데이터 출처 메타 정보
-- ================================================================
CREATE TABLE IF NOT EXISTS data_sources (
    id              BIGSERIAL    PRIMARY KEY,
    source_name     VARCHAR(50)  NOT NULL UNIQUE,  -- 출처명 (예: FinanceDataReader)
    source_type     VARCHAR(30)  NOT NULL
                        CHECK (source_type IN ('price', 'financial', 'news', 'all')),
    description     TEXT,                          -- 출처 설명
    last_updated_at TIMESTAMPTZ                    -- 마지막 수집 성공 시각
);

-- source_type 필터 (가격/재무/뉴스 분류 조회)
CREATE INDEX IF NOT EXISTS idx_ds_type
    ON data_sources (source_type);


-- ================================================================
-- data_sources 기본 데이터
-- (중복 삽입 방지: ON CONFLICT DO NOTHING)
-- ================================================================
INSERT INTO data_sources (source_name, source_type, description) VALUES
    (
        'FinanceDataReader',
        'price',
        '한국 거래소(KRX) 일봉 OHLCV + PER/PBR. pip install finance-datareader 로 설치.'
    ),
    (
        'OpenDART',
        'financial',
        '금융감독원 전자공시 API. ROE, 부채비율, 당기순이익 등 사업보고서 기반 재무 데이터.'
    ),
    (
        'NaverNews',
        'news',
        '네이버 뉴스 검색 API. 종목명 키워드 뉴스 실시간 조회.'
    ),
    (
        'Mock',
        'all',
        'API 키 없이 앱 실행을 위한 샘플 데이터. 실제 시장 수치와 다릅니다.'
    )
ON CONFLICT (source_name) DO NOTHING;
