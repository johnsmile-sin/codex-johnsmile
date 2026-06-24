-- =============================================================
-- schema_v4.sql  –  4차 키움 연동 기반 제한형 자동매매 준비
--
-- 전제: schema.sql (3차) 이 먼저 적용되어 있어야 합니다.
--       (risk_settings 등 기존 테이블 의존)
--
-- 신규 테이블 6개:
--   1. trade_signals         전략 매매 신호
--   2. order_intents         사용자 승인 대기 주문
--   3. broker_orders         브로커(모의투자) 전송 주문
--   4. order_execution_logs  주문 실행 이벤트 로그
--   5. safety_events         리스크·긴급중지 이벤트 로그
--   6. system_settings       시스템 동작 모드 설정 (단일 행)
--
-- Supabase SQL Editor 에서 한 번에 실행하세요.
-- =============================================================


-- =============================================================
-- 공통 set_updated_at 함수 (schema.sql 에 이미 있으면 OR REPLACE 로 무해)
-- =============================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- =============================================================
-- 1. trade_signals  –  전략이 생성한 매매 신호
-- =============================================================
CREATE TABLE IF NOT EXISTS trade_signals (
    id              BIGSERIAL       PRIMARY KEY,
    signal_date     DATE            NOT NULL DEFAULT CURRENT_DATE,
    stock_code      VARCHAR(10)     NOT NULL,
    stock_name      VARCHAR(100),
    strategy_name   VARCHAR(100)    NOT NULL,

    signal_type     VARCHAR(10)     NOT NULL
                        CHECK (signal_type IN ('매수신호', '매도신호')),

    signal_price    INTEGER         NOT NULL CHECK (signal_price > 0),
    score           NUMERIC(6, 2),
    reason          TEXT,
    risk_summary    TEXT,

    -- 생성 → 주문후보생성 → (무시 | 만료)
    status          VARCHAR(20)     NOT NULL DEFAULT '생성'
                        CHECK (status IN ('생성', '주문후보생성', '무시', '만료')),

    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_signals_date
    ON trade_signals (signal_date DESC);

CREATE INDEX IF NOT EXISTS idx_trade_signals_code_date
    ON trade_signals (stock_code, signal_date DESC);

CREATE INDEX IF NOT EXISTS idx_trade_signals_status
    ON trade_signals (status, signal_date DESC);

CREATE INDEX IF NOT EXISTS idx_trade_signals_strategy
    ON trade_signals (strategy_name, signal_date DESC);

COMMENT ON TABLE  trade_signals IS '전략 엔진이 생성한 매매 신호. 실거래 연결 없음.';
COMMENT ON COLUMN trade_signals.risk_summary IS '신호 생성 시 리스크 검사 요약 문자열.';


-- =============================================================
-- 2. order_intents  –  사용자 승인 대기 주문
--    approval_status = 승인 이 될 때만 broker_orders 로 전송됩니다.
-- =============================================================
CREATE TABLE IF NOT EXISTS order_intents (
    id                  BIGSERIAL       PRIMARY KEY,
    signal_id           BIGINT          REFERENCES trade_signals (id) ON DELETE SET NULL,

    stock_code          VARCHAR(10)     NOT NULL,
    stock_name          VARCHAR(100),
    strategy_name       VARCHAR(100),

    -- 주문 방향 (시장가 자동주문 금지 — 지정가만 허용)
    order_type          VARCHAR(4)      NOT NULL
                            CHECK (order_type IN ('매수', '매도')),

    order_price         INTEGER         NOT NULL CHECK (order_price > 0),
    quantity            INTEGER         NOT NULL CHECK (quantity >= 1),
    order_amount        INTEGER         NOT NULL CHECK (order_amount > 0),

    -- 승인 상태
    approval_status     VARCHAR(10)     NOT NULL DEFAULT '승인대기'
                            CHECK (approval_status IN ('승인대기', '승인', '거절', '만료')),

    -- 리스크 검사 결과
    risk_check_status   VARCHAR(10)     NOT NULL DEFAULT '확인필요'
                            CHECK (risk_check_status IN ('통과', '차단', '확인필요')),
    risk_check_message  TEXT,

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    approved_at         TIMESTAMPTZ,
    rejected_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_order_intents_approval
    ON order_intents (approval_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_order_intents_code
    ON order_intents (stock_code, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_order_intents_signal
    ON order_intents (signal_id);

COMMENT ON TABLE  order_intents IS '사용자 검토 대기 주문. approval_status=승인 후에만 broker_orders 로 전환됨.';
COMMENT ON COLUMN order_intents.order_type IS '매수/매도만 허용. 시장가 자동주문은 코드·DB 양쪽에서 차단.';


-- =============================================================
-- 3. broker_orders  –  브로커(키움 모의투자) 전송 주문
--    account_mode = real 은 DB 에 저장 가능하나
--    애플리케이션에서 전송 경로를 차단합니다 (services/kiwoom_order_bridge.py).
-- =============================================================
CREATE TABLE IF NOT EXISTS broker_orders (
    id                  BIGSERIAL       PRIMARY KEY,
    order_intent_id     BIGINT          REFERENCES order_intents (id) ON DELETE SET NULL,

    broker_name         VARCHAR(30)     NOT NULL DEFAULT '키움증권',

    -- mock: 내부 시뮬레이션 / paper: 키움 모의투자 API / real: 실계좌(차단됨)
    account_mode        VARCHAR(10)     NOT NULL DEFAULT 'mock'
                            CHECK (account_mode IN ('mock', 'paper', 'real')),

    -- 브로커가 부여한 외부 주문번호 (모의투자 API 응답값)
    broker_order_id     VARCHAR(30),

    stock_code          VARCHAR(10)     NOT NULL,
    stock_name          VARCHAR(100),
    order_type          VARCHAR(4)      NOT NULL
                            CHECK (order_type IN ('매수', '매도')),
    order_price         INTEGER         NOT NULL CHECK (order_price > 0),
    quantity            INTEGER         NOT NULL CHECK (quantity >= 1),

    order_status        VARCHAR(10)     NOT NULL DEFAULT '전송대기'
                            CHECK (order_status IN (
                                '전송대기', '전송완료', '일부체결', '전량체결', '취소', '실패'
                            )),

    filled_quantity     INTEGER         NOT NULL DEFAULT 0 CHECK (filled_quantity >= 0),
    avg_fill_price      INTEGER         NOT NULL DEFAULT 0 CHECK (avg_fill_price >= 0),

    sent_at             TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_broker_orders_intent
    ON broker_orders (order_intent_id);

CREATE INDEX IF NOT EXISTS idx_broker_orders_status
    ON broker_orders (order_status, sent_at DESC);

CREATE INDEX IF NOT EXISTS idx_broker_orders_code
    ON broker_orders (stock_code, sent_at DESC);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_broker_orders_updated_at'
    ) THEN
        CREATE TRIGGER trg_broker_orders_updated_at
            BEFORE UPDATE ON broker_orders
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END;
$$;

COMMENT ON TABLE  broker_orders IS '브로커로 전송된 주문 기록. account_mode=real 경로는 애플리케이션에서 차단.';
COMMENT ON COLUMN broker_orders.broker_order_id IS '키움 모의투자 API 가 반환한 외부 주문번호.';


-- =============================================================
-- 4. order_execution_logs  –  주문 실행 이벤트 상세 로그
--    broker_order_id: broker_orders.id 를 참조하는 FK
--    external_order_id: 브로커가 부여한 외부 주문번호 (broker_orders.broker_order_id)
-- =============================================================
CREATE TABLE IF NOT EXISTS order_execution_logs (
    id                  BIGSERIAL       PRIMARY KEY,

    -- 내부 FK (broker_orders 행)
    order_intent_id     BIGINT          REFERENCES order_intents (id)  ON DELETE SET NULL,
    broker_order_id     BIGINT          REFERENCES broker_orders (id)  ON DELETE SET NULL,

    -- 브로커 외부 주문번호 (broker_orders.broker_order_id 복사)
    external_order_id   VARCHAR(30),

    event_type          VARCHAR(30)     NOT NULL,
    message             TEXT,
    raw_response        JSONB,

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exec_logs_intent
    ON order_execution_logs (order_intent_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_exec_logs_broker_order
    ON order_execution_logs (broker_order_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_exec_logs_event
    ON order_execution_logs (event_type, created_at DESC);

COMMENT ON TABLE  order_execution_logs IS '주문 전송·체결·실패 등 모든 실행 이벤트 상세 로그.';
COMMENT ON COLUMN order_execution_logs.broker_order_id IS 'broker_orders.id (내부 PK).';
COMMENT ON COLUMN order_execution_logs.external_order_id IS '키움 API 반환 주문번호 (broker_orders.broker_order_id 복사).';


-- =============================================================
-- 5. safety_events  –  리스크 위반·긴급 중지·시스템 이상 이벤트
-- =============================================================
CREATE TABLE IF NOT EXISTS safety_events (
    id                  BIGSERIAL       PRIMARY KEY,
    event_date          DATE            NOT NULL DEFAULT CURRENT_DATE,

    event_type          VARCHAR(30)     NOT NULL
                            CHECK (event_type IN (
                                'RISK_BREACH',      -- 리스크 한도 초과
                                'EMERGENCY_STOP',   -- 긴급 중지 발동/해제
                                'ORDER_BLOCKED',    -- 주문 차단
                                'DAILY_LIMIT',      -- 일일 주문 한도 도달
                                'SYSTEM_ERROR'      -- 시스템 오류
                            )),

    severity            VARCHAR(10)     NOT NULL DEFAULT 'MEDIUM'
                            CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),

    message             TEXT            NOT NULL,
    related_stock_code  VARCHAR(10),

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_safety_events_date
    ON safety_events (event_date DESC);

CREATE INDEX IF NOT EXISTS idx_safety_events_type_sev
    ON safety_events (event_type, severity, event_date DESC);

CREATE INDEX IF NOT EXISTS idx_safety_events_stock
    ON safety_events (related_stock_code, event_date DESC);

COMMENT ON TABLE  safety_events IS '리스크 위반·긴급 중지·주문 차단 이벤트 감사 로그.';


-- =============================================================
-- 6. system_settings  –  시스템 동작 모드 (단일 행)
--    숫자 한도(max_daily_loss_rate 등)는 기존 risk_settings 를 사용합니다.
--    이 테이블은 모드·플래그만 담습니다.
-- =============================================================
CREATE TABLE IF NOT EXISTS system_settings (
    id                      INTEGER         PRIMARY KEY DEFAULT 1,

    -- 동작 모드
    -- analysis_only : 신호 생성까지만 허용 (주문 생성 불가)
    -- paper_trading : 모의투자 주문 생성 허용 (수동 승인 필요)
    trading_mode            VARCHAR(20)     NOT NULL DEFAULT 'analysis_only'
                                CHECK (trading_mode IN ('analysis_only', 'paper_trading')),

    -- 안전 플래그 (기본값 모두 보수적)
    allow_real_trading      BOOLEAN         NOT NULL DEFAULT FALSE,  -- 항상 FALSE 권장
    require_manual_approval BOOLEAN         NOT NULL DEFAULT TRUE,
    emergency_stop          BOOLEAN         NOT NULL DEFAULT FALSE,

    -- 주문 한도 (risk_settings 의 포지션 한도와 별개 — 1회 주문 단위)
    max_order_amount        INTEGER         NOT NULL DEFAULT 1000000 CHECK (max_order_amount > 0),

    -- 비고
    note                    TEXT,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_system_settings_single_row CHECK (id = 1)
);

-- 초기 행 (기본값 = 가장 보수적인 설정)
INSERT INTO system_settings (
    id,
    trading_mode,
    allow_real_trading,
    require_manual_approval,
    emergency_stop,
    max_order_amount
) VALUES (
    1,
    'analysis_only',
    FALSE,
    TRUE,
    FALSE,
    1000000
) ON CONFLICT (id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_system_settings_updated_at'
    ) THEN
        CREATE TRIGGER trg_system_settings_updated_at
            BEFORE UPDATE ON system_settings
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END;
$$;

COMMENT ON TABLE  system_settings IS '시스템 동작 모드 단일 행 설정. 숫자 한도는 risk_settings 참조.';
COMMENT ON COLUMN system_settings.trading_mode IS 'analysis_only(기본): 신호 생성만. paper_trading: 모의투자 주문 허용.';
COMMENT ON COLUMN system_settings.allow_real_trading IS '항상 FALSE 유지 권장. TRUE 로 변경해도 코드에서 차단됨.';
COMMENT ON COLUMN system_settings.emergency_stop IS 'TRUE 이면 모든 주문 생성·전송 즉시 차단.';
