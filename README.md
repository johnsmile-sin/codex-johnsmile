# 📈 local-stock-assistant  v4

> **개인 PC에서 실행하는 주식 후보 발굴 · 분석 · 모의투자 · 매매일지 관리 도구**  
> Python · Streamlit · Supabase (선택) · Naver 뉴스 · OpenDART · 키움 모의투자 API

---

> ⚠️ **투자 유의사항**  
> 이 프로그램은 **개인 학습 및 분석 보조 목적**으로 제작된 참고 도구입니다.  
> 표시되는 점수, 등급, 투자 판단은 **알고리즘 기반 참고 정보**이며, **수익을 보장하지 않습니다.**  
> 모의투자·백테스트 결과는 과거 기준이며 미래 성과를 의미하지 않습니다.  
> 실제 투자 결정과 그에 따른 손익은 **전적으로 본인 책임**입니다.
>
> ⛔ **실거래 자동주문 기능은 없습니다.**  
> 키움 API는 모의투자 전용으로만 사용하며, 실제 계좌에 주문을 전송하지 않습니다.

---

## 목차

1. [1차 주요 기능](#1-1차-주요-기능)
2. [2차 추가 기능](#2-2차-추가-기능-v2)
3. [3차 추가 기능](#3-3차-추가-기능-모의투자)
4. [4차 추가 기능](#4-4차-추가-기능-키움-연동-제한형-자동매매-준비)
5. [설치 방법](#5-설치-방법)
6. [환경변수 설정](#6-환경변수-설정)
7. [Supabase 설정](#7-supabase-설정-선택-사항)
8. [네이버 뉴스 API 설정](#8-네이버-뉴스-api-설정-선택-사항)
9. [OpenDART API 설정](#9-opendart-api-설정-선택-사항)
10. [키움 API 안내](#10-키움-api-안내)
11. [Mock 모드 안내](#11-mock-모드-안내)
12. [앱 실행](#12-앱-실행)
13. [신호 → 주문 흐름](#13-신호--주문-후보--승인--전송-흐름)
14. [주문 신호와 실제 주문의 차이](#14-주문-신호와-실제-주문의-차이)
15. [주문 승인 프로세스](#15-주문-승인-프로세스)
16. [리스크 검사 규칙](#16-리스크-검사-규칙-10개)
17. [긴급 중지 기능](#17-긴급-중지-기능)
18. [OpenClaw CLI 명령](#18-openclaw-cli-명령-v4)
19. [실거래 자동주문 미지원 안내](#19-실거래-자동주문-미지원-안내)
20. [API 키 보안 주의사항](#20-api-키-보안-주의사항)
21. [scheduler.py 수동 배치](#21-schedulerpy-수동-배치-실행)
22. [폴더 구조](#22-폴더-구조)
23. [GitHub 업로드](#23-github-최초-업로드)
24. [4차 성공 기준 및 테스트 순서](#24-4차-성공-기준-및-테스트-순서)

---

## 1. 1차 주요 기능

| 기능 | 설명 |
|------|------|
| 📋 후보 종목 스캐너 | 종목을 10개 규칙으로 자동 점수화 (0~100점), 5단계 판단 |
| 🔍 종목 상세 리포트 | 기술적 점수 · 재무 요약 · 뉴스 감성 · 최종 투자 판단 |
| 📰 뉴스/이슈 | Mock 뉴스, 감성(긍정/중립/부정) 분류 |
| 📝 매매일지 | 거래 내역 등록 · 조회 · Supabase 저장 |
| 🖥️ OpenClaw CLI | Streamlit 없이 터미널에서 분석 명령 실행 |

**기술 스택:** Python 3.10+, Streamlit, pandas, plotly, Supabase PostgreSQL, python-dotenv

---

## 2. 2차 추가 기능 (v2)

| 기능 | 설명 |
|------|------|
| 📊 일봉 캔들스틱 차트 | MA5·MA20·MA60 + 거래량 + RSI(14) |
| 💰 재무 3년 추이 | 매출·영업이익·PER·ROE·부채비율 |
| 🔌 API 연결 상태 표시 | 사이드바 Supabase·DART·Naver·키움 실시간 표시 |
| 📡 데이터 출처·신뢰도 | 가격(키움/FDR/Mock)·재무(DART/CSV/Mock)·뉴스(Naver/Mock) |
| 🔄 스캐너 v2 | 규칙 10개 → 19개, 데이터 품질(A/B/C) 추적 |
| 📋 리포트 v2 | 5섹션 → 8섹션, 5단계 투자 판정 |

---

## 3. 3차 추가 기능 (모의투자)

| 기능 | 설명 |
|------|------|
| 💼 가상 포트폴리오 | 초기 자금 1,000만원 기준 현금·보유·평가손익 추적 |
| ⚙️ 전략 실행 | 후보 점수 조건으로 가상 매수/매도 1회 실행 |
| 📈 전략 성과 | 승률·누적 수익률·최대 낙폭 요약 |
| 🧪 경량 백테스트 | 최근 180일 기준 전략별 백테스트 |
| 🛡 리스크 점검 | 보유 종목 수·투자금 한도·일일 손실 한도 |
| 🖥️ OpenClaw v3 | `virtual_portfolio`, `run_virtual_trading`, `backtest_strategy` 등 |

> ⚠️ 3차 모의투자도 실거래 주문이 아니며 `virtual_orders` 저장소에만 기록됩니다.

---

## 4. 4차 추가 기능 (키움 연동 제한형 자동매매 준비)

### 4-1. 4차 목표

4차 개발의 목표는 **키움증권 모의투자 REST API**와 연동하여 신호 생성부터 모의투자 주문 전송까지의 전체 흐름을 구축하는 것입니다.  
실거래 자동주문은 만들지 않습니다.

| 목표 | 설명 |
|------|------|
| 📡 신호 생성 자동화 | 스캐너 점수 기반 매수/매도 신호 자동 생성 |
| 📋 주문 후보 관리 | 신호 → 주문 후보 변환, 리스크 검사, 승인 대기 상태 관리 |
| ✅ 수동 승인 프로세스 | 모든 주문은 사용자가 Streamlit 화면에서 직접 승인 |
| 🏦 키움 모의투자 연동 | 모의투자 전용 REST API로 주문 전송 (실계좌 미사용) |
| 🛡 리스크 검사 강화 | 10개 항목 자동 검사, 차단/경고/통과 3단계 분류 |
| 🚨 긴급 중지 | 즉시 모든 주문 후보 생성 및 전송 차단 |
| 📋 주문 로그 | 신호 → 후보 → 승인 → 전송 전 과정 이력 추적 |

### 4-2. 4차 신규 파일

| 파일 | 역할 |
|------|------|
| `strategy/signal_generator.py` | 매수/매도 신호 생성·저장·만료 |
| `services/order_intent_service.py` | 주문 후보 생성·승인·거절·만료 |
| `strategy/risk_manager.py` v4 | 10개 리스크 검사, 통과/차단/확인필요 반환 |
| `services/kiwoom_order.py` | 키움 모의투자 REST API 주문 전송 |

### 4-3. 4차 신규 Streamlit 화면

| 메뉴 | 내용 |
|------|------|
| ✅ 주문 승인 | 승인 대기 주문 후보 목록 · 리스크 검사 결과 · 승인/거절 버튼 · 모의투자 전송 |
| ⚙️ 안전 설정 | 매매 모드 · 긴급 중지 · 주문 한도 · 손실 한도 설정 |
| 📋 주문 로그 | 신호·주문 후보·브로커 주문·리스크·실행 이벤트 5개 탭 조회 |

### 4-4. 4차 Supabase 신규 테이블

Supabase를 사용하는 경우 SQL Editor에서 `sql/schema_v4.sql`을 실행하세요.

| 테이블 | 용도 |
|--------|------|
| `trade_signals` | 매수/매도 신호 (status: 생성/주문후보생성/무시/만료) |
| `order_intents` | 주문 후보 (approval_status: 승인대기/승인/거절/만료) |
| `broker_orders` | 브로커 전송 주문 (account_mode: paper만 허용) |
| `order_execution_logs` | 주문 실행 이벤트 로그 |
| `system_settings` | 매매 모드·긴급 중지·주문 한도 설정 |
| `safety_events` | 리스크 차단·긴급 중지 이벤트 로그 |

### 4-5. 4차 안전 원칙 (코드 레벨 고정)

아래 원칙은 설정으로 변경할 수 없으며 코드에 하드코딩되어 있습니다.

```python
ALLOW_REAL_TRADING  = False   # 항상 False — 절대 변경 불가
ALLOW_MARKET_ORDER  = False   # 시장가 주문 항상 차단
DEFAULT_ACCOUNT_MODE = "paper" # 기본값 항상 모의투자
```

---

## 5. 설치 방법

> **전제 조건:** Python 3.10 이상

### 5-1. 저장소 클론

```powershell
git clone https://github.com/YOUR_USERNAME/local-stock-assistant.git
cd local-stock-assistant
```

### 5-2. 가상환경 생성 및 활성화 (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

> 활성화 오류 시:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### 5-3. 패키지 설치

```powershell
pip install -r requirements.txt
```

---

## 6. 환경변수 설정

`.env.example`을 복사해 `.env` 파일을 만들고 값을 입력합니다.

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env` 파일 항목:

```env
# ── Supabase (없으면 로컬 JSON 폴백) ──────────────────────────
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here

# ── 네이버 뉴스 API (없으면 Mock 뉴스 사용) ──────────────────
NAVER_CLIENT_ID=your-naver-client-id
NAVER_CLIENT_SECRET=your-naver-client-secret

# ── OpenDART API (없으면 Mock 재무 데이터 사용) ──────────────
DART_API_KEY=your-dart-api-key

# ── 키움증권 모의투자 REST API (없으면 Mock 반환) ────────────
# ⚠️ 모의투자 전용 — 실거래 계좌 키를 입력하지 마세요
KIWOOM_APP_KEY=your-kiwoom-app-key
KIWOOM_SECRET_KEY=your-kiwoom-secret-key
KIWOOM_ACCOUNT_NO=your-paper-trading-account-no

# ── Mock 모드 강제 (true = 모든 외부 API 무시) ──────────────
MOCK_MODE=false
```

> ⛔ **`.env` 파일은 절대로 GitHub에 올리지 마세요.**  
> `.gitignore`에 포함되어 있으나, 업로드 전 반드시 `git status`로 확인하세요.  
> API 키·계좌번호가 유출되면 즉시 키움·Supabase에서 키를 재발급하세요.  
> **커밋 허용 파일은 `.env.example`뿐입니다.** (실제 값 없이 키 이름만 포함)

---

## 7. Supabase 설정 (선택 사항)

Supabase 없이도 로컬 JSON 파일(`data/`)로 모든 기능을 사용할 수 있습니다.

### 7-1. API 키 확인

| 항목 | 위치 |
|------|------|
| `SUPABASE_URL` | Settings → API → Project URL |
| `SUPABASE_ANON_KEY` | Settings → API → anon (public) key |

### 7-2. 스키마 생성 (순서대로 실행)

Supabase 대시보드 → SQL Editor에서 아래 파일을 순서대로 실행합니다.

```
sql/schema.sql               # 1차: 기본 테이블
sql/schema_v2.sql            # 2차: 가격·뉴스·재무
sql/schema_v3.sql            # 3차: 모의투자·전략
supabase/schema_v3_virtual_trading.sql
sql/schema_v4.sql            # 4차: 신호·주문·안전설정 (6개 신규 테이블)
```

---

## 8. 네이버 뉴스 API 설정 (선택 사항)

키가 없으면 Mock 뉴스 데이터로 자동 대체됩니다.

1. [https://developers.naver.com/apps](https://developers.naver.com/apps) 접속 후 로그인
2. Application 등록 → 사용 API: **검색** 선택
3. `.env`에 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` 입력

---

## 9. OpenDART API 설정 (선택 사항)

키가 없으면 CSV 캐시 → Mock 재무 데이터 순으로 대체됩니다.

1. [https://opendart.fss.or.kr](https://opendart.fss.or.kr) 접속 후 API Key 발급
2. `.env`에 `DART_API_KEY` 입력

---

## 10. 키움 API 안내

### 10-1. 4차: 모의투자 주문 연동 (신규)

4차에서 키움 REST API를 모의투자 주문 전송에 사용합니다.

| 항목 | 내용 |
|------|------|
| 연결 URL | `https://openapivts.koreainvestment.com:29443` (모의투자 전용) |
| 매수 TR | `VTTC0802U` — 주식 매수 (모의) |
| 매도 TR | `VTTC0801U` — 주식 매도 (모의) |
| 취소 TR | `VTTC0803U` — 주문 취소 (모의) |
| 허용 모드 | `account_mode = "paper"` 만 허용 |
| 실거래 | ❌ **차단** (`account_mode = "real"` 시 즉시 차단) |

> ⚠️ **키움 API 키가 없으면 Mock 주문 번호를 반환합니다.**  
> Mock 번호 형식: `M` + 8자리 숫자 (예: `M12345678`).  
> Supabase/JSON에 저장되어 주문 흐름 전체를 테스트할 수 있습니다.

### 10-2. 키움 API 용도 요약

| 용도 | 사용 여부 |
|------|-----------|
| 현재가·일봉 조회 | ✅ 조회 전용 |
| 모의투자 매수 주문 전송 | ✅ 4차 신규 (paper 모드만) |
| 모의투자 매도 주문 전송 | ✅ 4차 신규 (paper 모드만) |
| 실계좌 매수·매도 주문 | ❌ **비활성화** (코드 레벨 차단) |
| 계좌 잔고 조회 | ❌ 미사용 |

### 10-3. 가격 데이터 우선순위

```
키움 OpenAPI (조회 전용)
  └→ 실패 시 FinanceDataReader (무료)
        └→ 실패 시 Mock 데이터
```

---

## 11. Mock 모드 안내

**모든 API 키가 없어도 앱이 정상 동작합니다.**

| API | 키 없을 때 동작 |
|-----|----------------|
| Supabase | 로컬 JSON 파일 (`data/*.json`) 사용 |
| Naver 뉴스 | Mock 뉴스 자동 생성 |
| OpenDART | CSV 캐시 → Mock 재무 |
| 키움 시세 | FinanceDataReader → Mock |
| 키움 주문 | Mock 주문번호 반환 (`M` + 8자리) |

```env
MOCK_MODE=true   # 모든 외부 API를 무시하고 Mock 데이터만 사용
```

---

## 12. 앱 실행

```powershell
cd local-stock-assistant
.\.venv\Scripts\activate
streamlit run app.py
```

브라우저에서 `http://localhost:8501`이 자동으로 열립니다.

### Streamlit 화면 구성 (v4)

| 메뉴 | 주요 기능 |
|------|-----------|
| 📋 오늘의 후보 종목 | 5단계 판단 배지 · 종목 목록 · 재무 리스크 필터 · 검색 |
| 🔍 종목 상세 리포트 | 일봉 차트 + RSI · 8섹션 리포트 · 재무 3년 추이 |
| 💼 모의투자 | 가상 포트폴리오 · 보유 종목 · 전략 실행 · 백테스트 |
| 📝 매매일지 | 거래 등록 · 수익률 자동 계산 · 내역 조회 |
| ✅ 주문 승인 | 승인 대기 목록 · 리스크 결과 · 승인/거절 · 모의투자 전송 |
| ⚙️ 안전 설정 | 매매 모드 · 긴급 중지 · 주문 한도 · 손실 한도 |
| 📋 주문 로그 | 신호·후보·브로커·리스크·이벤트 5개 탭 |

> ⛔ **"✅ 주문 승인" 화면에서 실거래 주문을 전송할 수 없습니다.**  
> 모의투자(`paper`) 모드에서만 키움 모의투자 API로 전송됩니다.

---

## 13. 신호 → 주문 후보 → 승인 → 전송 흐름

4차에서 주문은 아래 4단계를 거칩니다.  
**각 단계는 사람이 직접 개입하며, 자동 주문 전송은 지원하지 않습니다.**

```
[1단계] 신호 생성
  스캐너 점수 기반 매수/매도 신호 자동 생성
  → trade_signals 테이블 저장
  → status: "생성"

[2단계] 주문 후보 생성
  신호를 주문 후보(order_intents)로 변환
  주문 수량 자동 계산 (max_order_amount 기준)
  10개 리스크 검사 자동 실행
  → approval_status: "승인대기"
  → risk_check_status: "통과" / "차단" / "확인필요"

[3단계] 사용자 승인 (Streamlit 화면 필수)
  사용자가 "✅ 주문 승인" 화면에서 직접 확인 후 승인 또는 거절
  리스크 차단 주문은 승인 버튼이 비활성화됨
  → approval_status: "승인" 또는 "거절"

[4단계] 모의투자 전송 (승인된 주문만)
  paper 모드에서 키움 모의투자 REST API로 전송
  실거래(real) 모드는 코드 레벨에서 차단
  → broker_orders 저장
  → order_execution_logs 이벤트 기록
```

---

## 14. 주문 신호와 실제 주문의 차이

| 구분 | 매매 신호 (trade_signals) | 주문 후보 (order_intents) | 브로커 주문 (broker_orders) |
|------|--------------------------|--------------------------|------------------------------|
| 생성 주체 | 스캐너 자동 | 사용자 또는 시스템 | 사용자 승인 후 |
| 증권사 API 호출 | ❌ 없음 | ❌ 없음 | ✅ 모의투자만 |
| 실계좌 영향 | ❌ 없음 | ❌ 없음 | ❌ 없음 (paper) |
| 승인 필요 | ❌ 자동 저장 | ✅ 리스크 검사 | ✅ 사용자 직접 승인 |
| 상태 값 | 생성/주문후보생성/무시/만료 | 승인대기/승인/거절/만료 | 전송대기/전송완료/체결/취소/실패 |

**핵심:** 신호는 "관심 종목 알림"이며, 주문 후보는 "검토 대상"입니다.  
실제 모의투자 전송은 사용자가 화면에서 승인한 후에만 이루어집니다.

---

## 15. 주문 승인 프로세스

### 15-1. Streamlit "✅ 주문 승인" 화면 구성

**탭 1 — 승인 대기**
- 리스크 검사 상태(통과/차단/확인필요)별 색상 표시
- 리스크 차단 주문 → 승인 버튼 비활성화
- 2단계 거절 확인 (실수 방지)

**탭 2 — 전송 대기**
- 승인된 주문 목록
- 모의투자 모드에서만 "전송" 버튼 활성화
- analysis_only 모드에서는 전송 불가

**탭 3 — 전송 결과 로그**
- 최근 30건 broker_orders 조회

### 15-2. 승인 가능 조건

| 조건 | 설명 |
|------|------|
| risk_check_status ≠ "차단" | 리스크 차단 주문은 승인 불가 |
| emergency_stop = False | 긴급 중지 시 승인 불가 |
| approval_status = "승인대기" | 이미 처리된 주문은 재승인 불가 |

### 15-3. 전송 가능 조건

| 조건 | 설명 |
|------|------|
| approval_status = "승인" | 미승인 주문 전송 불가 |
| trading_mode = "paper_trading" | analysis_only 모드에서 전송 불가 |
| account_mode = "paper" | 실거래 모드 전송 코드 레벨 차단 |
| emergency_stop = False | 긴급 중지 시 전송 차단 |

---

## 16. 리스크 검사 규칙 (10개)

주문 후보 생성 시 아래 10개 항목을 자동으로 검사합니다.  
각 항목은 **통과** / **차단** / **확인필요** 중 하나를 반환합니다.

| # | 검사 항목 | 차단 조건 | 경고 조건 |
|---|-----------|-----------|-----------|
| 1 | 긴급_중지_확인 | emergency_stop = True | — |
| 2 | 매매_모드_확인 | trading_mode = "analysis_only" | trading_mode = "real_ready" |
| 3 | 실거래_차단 | account_mode = "real" | — |
| 4 | 시장가_주문_차단 | price_type = "시장가" | — |
| 5 | 주문_금액_한도 | order_amount > max_order_amount | — |
| 6 | 최대_포지션_수 | 보유 종목 수 ≥ max_position_count (매수 시) | — |
| 7 | 중복_주문_확인 | 동일 종목 승인대기 주문 존재 | — |
| 8 | 보유_종목_중복 | 이미 보유 중인 종목 매수 시도 | — |
| 9 | 뉴스_감성_확인 | 매수 + 부정 뉴스 | 매수 + 중립 뉴스 |
| 10 | 데이터_품질_확인 | — | data_quality = "LOW" |

**종합 결과:**
- 차단 항목 1개 이상 → 종합 `차단` (승인 불가)
- 경고 항목만 존재 → 종합 `확인필요` (승인 가능, 주의 필요)
- 모두 통과 → 종합 `통과`

---

## 17. 긴급 중지 기능

긴급 중지(emergency_stop)를 활성화하면 **모든 주문 후보 생성과 전송이 즉시 차단**됩니다.

### 17-1. 긴급 중지 활성화/해제 방법

**Streamlit 화면 (권장):**
- `⚙️ 안전 설정` → 긴급 중지 토글

**CLI:**
```powershell
# 긴급 중지 ON
python -m openclaw.commands emergency_stop_on

# 긴급 중지 OFF (확인 프롬프트 있음)
python -m openclaw.commands emergency_stop_off
```

### 17-2. 긴급 중지 영향 범위

| 기능 | 영향 |
|------|------|
| 신호 생성 | 🚫 차단 (generate_signals 실행 불가) |
| 주문 후보 생성 | 🚫 차단 |
| 주문 승인 | 🚫 차단 |
| 모의투자 전송 | 🚫 차단 |
| 데이터 조회·분석 | ✅ 정상 동작 |
| 백테스트·리포트 | ✅ 정상 동작 |

### 17-3. 긴급 중지 상태 확인

```powershell
python -m openclaw.commands safety_status
```

---

## 18. OpenClaw CLI 명령 (v4)

Streamlit 없이 터미널에서 분석과 안전 제어를 실행합니다.  
**반드시 프로젝트 루트 디렉토리에서 실행하세요.**

```powershell
cd local-stock-assistant
.\.venv\Scripts\activate
```

### 18-1. 기존 명령 (v2)

```powershell
# 후보 종목 조회
python -m openclaw.commands today_candidates
python -m openclaw.commands today_candidates 5    # 상위 5개

# 데이터 업데이트
python -m openclaw.commands update_candidates

# 종목 분석
python -m openclaw.commands analyze_stock 삼성전자
python -m openclaw.commands news_summary SK하이닉스
python -m openclaw.commands financial_summary 현대차

# 데이터 갱신
python -m openclaw.commands refresh_news 삼성전자
python -m openclaw.commands refresh_prices 005930

# 매매 메모
python -m openclaw.commands save_trade_note 삼성전자 "분할매수 검토"
```

### 18-2. 모의투자 명령 (v3)

```powershell
python -m openclaw.commands virtual_portfolio      # 가상 포트폴리오 현황
python -m openclaw.commands virtual_run            # 가상 매수/매도 1회 실행
python -m openclaw.commands virtual_backtest 20   # 경량 백테스트 20거래일
python -m openclaw.commands strategy_performance  # 전략별 성과
python -m openclaw.commands risk_summary          # 리스크 조건 요약
```

### 18-3. v4 신규 명령 (7개)

#### generate_signals — 신호 생성

스캐너 점수 기반 매수/매도 신호를 생성하고 저장합니다.

```powershell
python -m openclaw.commands generate_signals
```

출력 예시:
```
  📡  신호 생성  (2026-06-25)
  매매 모드: paper_trading  |  긴급 중지: 🟢 비활성
  ──────────────────────────────────────────────────
  🟢 [매수] 삼성전자(005930)  점수 82점  [관심]
       사유: 점수 82점, 뉴스 감성: 긍정, 정배열 확인
  🔴 [매도] SK바이오팜(326030)  점수 45점  [제외]
       사유: 점수 급락(15점 이상), 부정 뉴스 감지
  ──────────────────────────────────────────────────
  매수 신호: 3건  |  매도 신호: 1건  |  저장: 4건
```

> ⚠️ 신호 생성은 주문 생성과 다릅니다.  
> 주문 후보 생성은 Streamlit '✅ 주문 승인' 화면에서 진행합니다.

#### pending_orders — 승인 대기 조회

```powershell
python -m openclaw.commands pending_orders
```

승인 대기 중인 주문 후보 목록을 출력합니다.  
주문 승인 및 전송은 CLI에서 불가능하며 Streamlit 화면에서만 가능합니다.

#### risk_check — 리스크 상태 점검

```powershell
python -m openclaw.commands risk_check
```

10개 리스크 항목을 실행하고 종합 상태를 출력합니다.

#### safety_status — 안전 설정 현황

```powershell
python -m openclaw.commands safety_status
```

현재 매매 모드, 긴급 중지 상태, 주문 한도, 손실 한도를 출력합니다.

출력 예시:
```
  ⚙️  안전 설정 현황  (2026-06-25)
  🟢 긴급 중지: 비활성

  매매 모드      : 모의투자 (수동 승인 후 모의주문 가능)
  실거래 허용    : ⛔ 항상 False (코드 레벨 고정, 변경 불가)
  수동 승인 필수 : ✅ 예
  최대 주문 금액 : 1,000,000원
  최대 손실 한도 : -3.0%
  최대 보유 종목 : 5개
```

#### emergency_stop_on / emergency_stop_off — 긴급 중지 제어

```powershell
# 긴급 중지 활성화 (확인 프롬프트 없음)
python -m openclaw.commands emergency_stop_on

# 긴급 중지 해제 (Enter 확인 프롬프트 있음)
python -m openclaw.commands emergency_stop_off
```

#### order_logs — 주문 로그 조회

```powershell
python -m openclaw.commands order_logs        # 최근 20건
python -m openclaw.commands order_logs 50     # 최근 50건
python -m openclaw.commands logs              # 단축 명령
```

브로커 주문과 실행 이벤트 로그를 출력합니다.

### 18-4. v4 명령 제한 사항

> ⛔ **OpenClaw CLI는 주문 승인 또는 브로커 전송을 할 수 없습니다.**  
> 주문 승인·거절·전송은 반드시 Streamlit '✅ 주문 승인' 화면에서 사용자가 직접 진행합니다.

| OpenClaw 가능 | OpenClaw 불가 |
|---------------|---------------|
| ✅ 신호 생성 | ❌ 주문 후보 승인 |
| ✅ 데이터 조회·요약 | ❌ 주문 거절 |
| ✅ 리스크 상태 확인 | ❌ 브로커 주문 전송 |
| ✅ 긴급 중지 ON/OFF | ❌ 실거래 주문 |
| ✅ 주문 로그 조회 | ❌ 계좌 잔고 변경 |

### 18-5. 도움말

```powershell
python -m openclaw.commands help
python -m openclaw.commands --help
```

---

## 19. 실거래 자동주문 미지원 안내

```
⛔ 이 프로젝트는 실거래 자동주문을 지원하지 않습니다.
```

### 19-1. 코드 레벨 차단 목록

| 항목 | 내용 |
|------|------|
| `ALLOW_REAL_TRADING = False` | 코드에 하드코딩 — 설정으로 변경 불가 |
| `ALLOW_MARKET_ORDER = False` | 시장가 주문 항상 차단 |
| `account_mode = "real"` | 브로커 전송 즉시 차단, `NotImplementedError` 발생 |
| 실거래 주문 API 함수 | 제공하지 않음. CLI 주문 키워드는 즉시 차단 |

### 19-2. 주문 키워드 차단

CLI에서 아래 키워드 입력 시 즉시 차단 메시지를 출력합니다.

```
매수주문 / 매도주문 / place_order / order / buy_order / sell_order / 주문
```

### 19-3. Streamlit 화면 안내

- `✅ 주문 승인` 화면에는 "실거래 주문은 지원하지 않습니다" 배너가 상시 표시됩니다.
- `⚙️ 안전 설정` 화면에서 `allow_real_trading`을 True로 변경할 수 없습니다.
- `real_ready` 매매 모드는 표시 목적이며 실제 주문을 전송하지 않습니다.

### 19-4. 모의투자 vs 실거래 비교

| 구분 | 이 프로젝트 | 실거래 |
|------|------------|--------|
| 사용 API | 키움 모의투자 전용 URL | 사용 안 함 |
| 계좌 영향 | 모의투자 계좌 (가상 잔고) | 지원 안 함 |
| 주문 체결 | 모의투자 시스템 내 가상 체결 | 지원 안 함 |
| 실금전 손익 | 없음 | 지원 안 함 |

---

## 20. API 키 보안 주의사항

### 20-1. .env 파일 관리 원칙

| 원칙 | 설명 |
|------|------|
| ❌ `.env` GitHub 업로드 금지 | `.gitignore`에 포함되어 있으나 매번 `git status`로 확인 |
| ✅ `.env.example`만 커밋 | 키 이름만 포함, 실제 값 없음 |
| 🔒 파일 접근 제한 | PC 공유 시 `.env` 파일 타인 접근 차단 |
| ⚠️ 유출 시 즉시 재발급 | 키움·Supabase·Naver·DART 각각 키 재발급 |

### 20-2. 업로드 전 필수 확인

```powershell
# .env가 git 추적 대상이 아닌지 확인 (출력에 .env가 없어야 함)
git status

# .gitignore가 .env를 제외하는지 확인
git check-ignore -v .env
# 기대: .gitignore:1:.env    .env

# .env가 git 인덱스에 없는지 확인 (아무것도 출력되지 않아야 함)
git ls-files .env
```

### 20-3. 절대 커밋하지 말아야 할 파일

| 파일 | 이유 |
|------|------|
| `.env` | 모든 API 키·계좌번호 포함 |
| `data/system_settings.json` | 긴급 중지·매매 모드 설정 포함 |
| `data/broker_orders.json` | 주문 이력 (계좌 연관 정보) |
| `.venv/` | 가상환경 (수백 MB, 재설치 가능) |
| `__pycache__/` | Python 컴파일 캐시 |
| `logs/*.log` | 로그 파일 |

### 20-4. GitHub 저장소 설정 권장

| 설정 | 권장값 |
|------|--------|
| 저장소 가시성 | **Private** (API 키·전략 코드 보호) |
| 브랜치 보호 | main 브랜치 직접 push 제한 |
| Dependabot | 의존성 취약점 알림 활성화 |

---

## 21. scheduler.py 수동 배치 실행

자동 스케줄러가 아닌, 필요할 때 수동으로 호출하는 배치 스크립트입니다.

```powershell
cd local-stock-assistant
.\.venv\Scripts\activate
```

### 명령 목록

| 명령 | 동작 |
|------|------|
| `update_candidates` | FDR/키움으로 일봉 가격 데이터 갱신 |
| `update_news` | Naver API로 상위 종목 뉴스 갱신 |
| `update_financial` | DART API로 재무 데이터 갱신 |
| `generate_reports` | 종합 리포트 생성 (`data/reports/` + Supabase) |
| `all` | 위 4단계를 순서대로 전체 실행 |

```powershell
python scheduler.py update_candidates
python scheduler.py update_news --top 15
python scheduler.py all --top 20
```

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--top N` | 처리할 상위 종목 수 | 20 |
| `--min-score N` | 최소 스캐너 점수 | 40 |

> ⛔ **주문 관련 명령은 scheduler.py에서도 차단됩니다.**

---

## 22. 폴더 구조

```
local-stock-assistant/
│
├── app.py                       # Streamlit 메인 앱 v4 (11개 메뉴)
├── scheduler.py                 # 수동 배치 스크립트
├── config.py                    # API 키 중앙 관리
├── requirements.txt
├── .env.example                 # 환경변수 예시 (커밋 허용)
├── .gitignore
│
├── services/                    # 데이터 서비스 레이어
│   ├── market_data.py           # 시장 데이터 (키움 → FDR → Mock)
│   ├── price_service.py         # 일봉 OHLCV 수집·저장
│   ├── news_data.py             # Naver 뉴스 + 감성 분류
│   ├── financial_data.py        # DART 재무 조회 + CSV 캐시
│   ├── supabase_client.py       # Supabase 연결 / 로컬 JSON 폴백
│   ├── db_service.py            # DB 라우터 (Streamlit 전용)
│   ├── mock_db_service.py       # 인메모리 Mock DB
│   ├── virtual_trading.py       # 가상 포트폴리오·주문 (3차)
│   ├── system_settings.py       # 시스템 설정 (4차) ★
│   ├── order_intent_service.py  # 주문 후보 관리 (4차) ★
│   └── kiwoom_order.py          # 키움 모의투자 주문 (4차) ★
│
├── strategy/                    # 분석·전략 레이어
│   ├── scanner.py               # 후보 종목 점수화 19개 규칙
│   ├── indicators.py            # 기술 지표 (MA, RSI)
│   ├── risk_manager.py          # 리스크 검사 10개 (4차 강화) ★
│   ├── signal_generator.py      # 매수/매도 신호 생성 (4차) ★
│   └── strategy_rules.py        # 전략 규칙 관리
│
├── analysis/
│   ├── stock_report.py          # 8섹션 리포트
│   └── performance_analyzer.py  # 전략 성과 분석
│
├── openclaw/
│   └── commands.py              # CLI v4 (23개 명령) ★
│
├── data/                        # 로컬 JSON 폴백 저장소
│   ├── mock_stocks.py           # Mock 종목 마스터
│   ├── system_settings.json     # 안전 설정 (4차, Git 제외)
│   ├── trade_signals.json       # 신호 데이터 (4차)
│   ├── order_intents.json       # 주문 후보 (4차)
│   ├── broker_orders.json       # 브로커 주문 (4차, Git 제외)
│   ├── order_execution_logs.json # 실행 이벤트 (4차)
│   ├── virtual_orders.json      # 가상 주문 (3차)
│   ├── financial/               # DART CSV 캐시
│   └── reports/                 # 리포트 JSON
│
├── sql/
│   ├── schema.sql               # Supabase DDL v1
│   ├── schema_v2.sql            # DDL v2
│   ├── schema_v3.sql            # DDL v3
│   └── schema_v4.sql            # DDL v4: 신호·주문·안전설정 6개 테이블 ★
│
└── logs/
    └── scheduler.log            # 배치 실행 로그
```

★ = 4차 신규 파일

---

## 23. GitHub 최초 업로드

### 사전 보안 확인 (필수)

```powershell
# .env가 추적 대상이 아닌지 확인
git status

# .gitignore가 .env를 제외하는지 확인
git check-ignore -v .env

# 민감 파일이 인덱스에 없는지 확인
git ls-files .env data/system_settings.json data/broker_orders.json
```

### GitHub 저장소 생성

1. [https://github.com/new](https://github.com/new) 접속
2. Repository name: `local-stock-assistant`
3. **Private** 선택 (API 키·전략 코드 보호)
4. **Create repository** 클릭

### 업로드 명령

```powershell
git init
git add .
git commit -m "feat: local-stock-assistant v4 초기 커밋"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/local-stock-assistant.git
git push -u origin main
```

### 이후 변경사항

```powershell
git add .
git commit -m "feat: 기능 설명"
git push
```

---

## 24. 4차 성공 기준 및 테스트 순서

### 24-1. 4차 성공 기준

아래 항목을 모두 만족해야 4차 개발 완료로 판단합니다.

| 번호 | 성공 기준 | 기대 결과 |
|------|-----------|-----------|
| 1 | `streamlit run app.py` 실행 | 앱이 오류 없이 시작되고 HTTP 200 응답 |
| 2 | 시스템 설정 기본값 | `trading_mode = "analysis_only"` |
| 3 | 실거래 허용 기본값 | `allow_real_trading = False` |
| 4 | 수동 승인 기본값 | `require_manual_approval = True` |
| 5 | 긴급 중지 | `emergency_stop = True`이면 주문 후보 생성 및 전송 차단 |
| 6 | 매매 신호 생성 | 스캐너 점수 기반 `trade_signals` 생성 |
| 7 | 주문 후보 생성 | `paper_trading` 모드에서 `approval_status = "승인대기"`로 생성 |
| 8 | 리스크 차단 주문 | `risk_check_status = "차단"`이면 승인 불가 |
| 9 | 모의투자 전송 | `approval_status = "승인"`인 주문만 전송 가능 |
| 10 | 실거래 주문 함수 | 실거래 전송 함수는 제공하지 않음 |
| 11 | OpenClaw 권한 | OpenClaw CLI로 주문 승인·전송 불가 |
| 12 | 주문 로그 | 전송 시도, 전송 성공, 전송 실패, 안전 차단 이벤트 저장 |
| 13 | README 고지 | 실거래 자동주문 미지원 문구 명시 |
| 14 | GitHub 보안 | `.env`는 `.gitignore`로 제외되고 Git 추적 대상이 아님 |

### 24-2. 테스트 순서

아래 순서로 검증합니다. 실거래 주문은 어떤 단계에서도 발생하지 않습니다.

```powershell
# 1. 앱 실행 확인
streamlit run app.py

# 2. 기본 안전 설정 확인
python -c "from services.system_settings import get_system_settings; print(get_system_settings())"

# 3. OpenClaw 주문 권한 차단 확인
python -m openclaw.commands place_order
python -m openclaw.commands pending_orders

# 4. 매매 신호 생성 확인
python -m openclaw.commands generate_signals

# 5. Streamlit에서 안전 설정을 모의투자(paper_trading)로 전환
# 메뉴: ⚙️ 안전 설정 → 매매 모드: 모의투자

# 6. Streamlit에서 주문 후보 생성 확인
# 메뉴: ✅ 주문 승인 → 승인대기 주문 후보 확인

# 7. 리스크 차단 주문 승인 불가 확인
# risk_check_status = "차단"인 주문 후보는 승인 버튼이 비활성화되거나 승인 실패

# 8. 승인된 주문만 모의투자 전송 확인
# approval_status = "승인" 이후에만 모의투자 전송 버튼 사용

# 9. 긴급 중지 확인
python -m openclaw.commands emergency_stop_on
python -m openclaw.commands safety_status

# 10. 로그 저장 확인
python -m openclaw.commands order_logs 20

# 11. GitHub 업로드 전 .env 제외 확인
git check-ignore -v .env
git ls-files .env
```

### 24-3. 테스트 후 복구

테스트가 끝나면 안전 기본 상태로 되돌립니다.

```powershell
python -m openclaw.commands emergency_stop_off
```

Streamlit `⚙️ 안전 설정` 화면에서 매매 모드를 `analysis_only`로 되돌립니다.

---

## 라이선스

개인 학습 · 비상업적 사용 목적으로 제작되었습니다.  
상업적 이용 및 재배포 시 작성자에게 문의하세요.

---

## 투자 참고 및 책임 안내

이 도구는 **개인 학습, 분석 보조, 전략 검증**을 위한 참고용 소프트웨어입니다.

- 후보 점수와 투자 판단은 알고리즘 기반 참고 정보이며 **수익을 보장하지 않습니다.**
- 모의투자·백테스트 결과는 **과거 기준**이며 미래 성과를 보장하지 않습니다.
- 실거래 자동주문 기능은 없으며, 모든 거래 결정과 손익 책임은 **전적으로 사용자 본인**에게 있습니다.
- 이 소프트웨어 사용으로 인한 투자 손실에 대해 개발자는 어떠한 책임도 지지 않습니다.

---

*본 분석 도구는 투자 참고용이며, 수익을 보장하지 않습니다.*  
*실거래 자동주문 기능은 없으며, 투자 결정과 손익은 전적으로 본인 책임입니다.*
