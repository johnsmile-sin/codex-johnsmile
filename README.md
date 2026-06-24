# 📈 local-stock-assistant  v2

> **개인 PC에서 실행하는 주식 후보 발굴 · 분석 · 매매일지 관리 도구**  
> Python · Streamlit · Supabase (선택) · Naver 뉴스 · OpenDART · 키움 조회

---

> ⚠️ **투자 유의사항**  
> 이 프로그램은 **개인 학습 및 분석 보조 목적**으로 제작된 참고 도구입니다.  
> 표시되는 점수, 등급, 투자 판단은 **알고리즘 기반 참고 정보**이며, **수익을 보장하지 않습니다.**  
> 실제 투자 결정과 그에 따른 손익은 **전적으로 본인 책임**입니다.  
> **실거래 주문 기능은 없습니다.**

---

## 목차

1. [1차 주요 기능](#1-1차-주요-기능)
2. [2차 추가 기능](#2-2차-추가-기능-v2)
3. [설치 방법](#3-설치-방법)
4. [환경변수 설정](#4-환경변수-설정)
5. [Supabase 설정](#5-supabase-설정-선택-사항)
6. [네이버 뉴스 API 설정](#6-네이버-뉴스-api-설정-선택-사항)
7. [OpenDART API 설정](#7-opendart-api-설정-선택-사항)
8. [키움 API 안내](#8-키움-api-안내-조회-전용)
9. [Mock 모드 안내](#9-mock-모드-안내)
10. [앱 실행](#10-앱-실행)
11. [OpenClaw CLI 명령](#11-openclaw-cli-명령-v2)
12. [scheduler.py 수동 배치](#12-schedulerpy-수동-배치-실행)
13. [실거래 주문 기능 없음](#13-실거래-주문-기능-없음)
14. [폴더 구조](#14-폴더-구조)
15. [GitHub 업로드](#15-github-최초-업로드)

---

## 1. 1차 주요 기능

| 기능 | 설명 |
|------|------|
| 📋 후보 종목 스캐너 | 종목을 10개 규칙으로 자동 점수화 (0~100점), 5단계 판단 |
| 🔍 종목 상세 리포트 | 기술적 점수 · 재무 요약 · 뉴스 감성 · 최종 투자 판단 |
| 📰 뉴스/이슈 | Mock 뉴스, 감성(긍정/중립/부정) 분류 |
| 📝 매매일지 | 거래 내역 등록 · 조회 · Supabase 저장 |
| 🖥️ OpenClaw CLI | Streamlit 없이 터미널에서 분석 명령 실행 (4개 명령) |

**기술 스택:** Python 3.10+, Streamlit, pandas, plotly, Supabase PostgreSQL, python-dotenv

---

## 2. 2차 추가 기능 (v2)

### 2-1. 대시보드 (app.py v0.3)

| 기능 | 설명 |
|------|------|
| 🔌 API 연결 상태 표시 | 사이드바에 Supabase·DART·Naver·키움 실시간 연결 여부 표시 |
| 🔄 데이터 업데이트 버튼 4종 | 종목 · 뉴스 · 재무 · 후보 재계산을 각각 즉시 갱신 |
| 📊 일봉 캔들스틱 차트 | MA5·MA20·MA60 이동평균선 + 거래량 + RSI(14) 서브플롯 |
| 💰 재무 3년 추이 | 매출·영업이익·순이익·PER·ROE·부채비율 3년 테이블 및 차트 |
| 🏅 5단계 판단 배지 | 강한 관심(90+) · 관심(75+) · 관찰(60+) · 보류(40+) · 제외 개수 표시 |
| 🔒 재무 리스크 필터 | PER 음수·ROE 음수·부채비율 200% 초과·PER 50 초과 필터 |
| 🔍 종목 검색 | 이름 또는 종목코드로 즉시 검색 |
| 📡 데이터 출처·신뢰도 표시 | 가격(키움/FDR/Mock) · 재무(DART/CSV/Mock) · 뉴스(Naver/Mock) 등급 표시 |

### 2-2. 스캐너 (strategy/scanner.py v2)

- 규칙 수 10개 → **19개**로 확장
- 5단계 판단 기준: 강한 관심(90+) · 관심(75+) · 관찰(60+) · 보류(40+) · 제외
- `data_quality` 필드로 데이터 품질(A/B/C) 추적

### 2-3. 종목 리포트 (analysis/stock_report.py v2)

- 5섹션 → **8섹션**: 기본 정보 · 기술적 분석 · 재무 요약 · 뉴스 감성 · 최종 판단 · 핵심 리스크 · 데이터 신뢰도 · 한 줄 결론
- 일봉 데이터 기반 RSI14 · 연속 상승/하락일 · 20일 고가 대비 위치 자동 계산
- **5단계 데이터 신뢰도**: 높음 / 보통-상 / 보통-하 / 낮음 / 매우 낮음
- **5단계 투자 판정**: 적극 매수 / 분할 매수 / 관망 / 비중 축소 / 매도

### 2-4. 신규 데이터 서비스

| 서비스 | 역할 |
|--------|------|
| `services/price_service.py` | FinanceDataReader로 일봉 OHLCV 수집·저장·조회 |
| `services/financial_data.py` v2 | OpenDART REST API → CSV 캐시 → Mock 3단계 폴백 |
| `services/news_data.py` v2 | Naver 뉴스 API + 키워드 감성 분류 |

### 2-5. OpenClaw CLI (openclaw/commands.py v2)

- 4개 → **7개 명령**: `today_candidates` · `update_candidates` · `analyze_stock` · `news_summary` · `financial_summary` · `refresh_news` · `refresh_prices`
- 데이터 출처 · 기준일 · API 상태 · Mock 여부 표시

### 2-6. 수동 배치 스크립트 (scheduler.py)

- `python scheduler.py update_candidates / update_news / update_financial / generate_reports / all`
- 실행 로그 `logs/scheduler.log` 자동 저장 (RotatingFileHandler)
- 리포트 JSON `data/reports/{코드}_{날짜}.json` 자동 저장

---

## 3. 설치 방법

> **전제 조건:** Python 3.10 이상

### 3-1. 저장소 클론

```powershell
git clone https://github.com/YOUR_USERNAME/local-stock-assistant.git
cd local-stock-assistant
```

### 3-2. 가상환경 생성 및 활성화 (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

> 활성화 오류 시:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### 3-3. 패키지 설치

```powershell
pip install -r requirements.txt
```

---

## 4. 환경변수 설정

`.env.example`을 복사해 `.env` 파일을 만들고 값을 입력합니다.

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env` 파일 항목:

```env
# ── Supabase (없으면 Mock 모드 자동 실행) ─────────────────────────
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here

# ── 네이버 뉴스 API (없으면 Mock 뉴스 사용) ──────────────────────
NAVER_CLIENT_ID=your-naver-client-id
NAVER_CLIENT_SECRET=your-naver-client-secret

# ── OpenDART API (없으면 Mock 재무 데이터 사용) ──────────────────
DART_API_KEY=your-dart-api-key

# ── 키움증권 OpenAPI (없으면 FinanceDataReader 폴백) ─────────────
# 조회 전용 — 주문 기능은 비활성화 상태
KIWOOM_APP_KEY=your-kiwoom-app-key
KIWOOM_SECRET_KEY=your-kiwoom-secret-key

# ── OpenAI (선택 — 현재 사용 안 함) ────────────────────────────
OPENAI_API_KEY=sk-...

# ── Mock 모드 강제 (true = 모든 외부 API 무시) ──────────────────
MOCK_MODE=false
```

> `.env` 파일은 `.gitignore`에 포함되어 있어 GitHub에 업로드되지 않습니다.  
> **절대로 `.env` 파일을 커밋하지 마세요.** `.env.example`만 커밋하세요.

---

## 5. Supabase 설정 (선택 사항)

Supabase 없이도 Mock 모드로 모든 기능을 사용할 수 있습니다.  
데이터를 영구 저장하려면 아래 절차를 따르세요.

### 5-1. 프로젝트 생성

1. [https://supabase.com](https://supabase.com) 접속 후 로그인
2. **New Project** 클릭 → 프로젝트 이름 입력 → DB 비밀번호 설정
3. 생성 완료 후 **Settings → API** 이동

### 5-2. API 키 확인

| 항목 | 위치 |
|------|------|
| `SUPABASE_URL` | Settings → API → Project URL |
| `SUPABASE_ANON_KEY` | Settings → API → anon (public) key |

### 5-3. 스키마 생성

1. Supabase 대시보드 → **SQL Editor**
2. `sql/schema_v3.sql` 파일 내용을 전체 복사 후 붙여넣기
3. **Run** 클릭

생성되는 테이블:

| 테이블 | 용도 |
|--------|------|
| `stocks` | 종목 마스터 |
| `candidate_scores` | 스캐너 점수 결과 |
| `daily_prices` | 일봉 OHLCV 데이터 (v2) |
| `news_articles` | Naver 뉴스 데이터 (v2) |
| `financial_metrics` | DART 재무 지표 (v2) |
| `stock_reports` | 종합 리포트 JSON (v2) |
| `trade_journal` | 매매일지 |

---

## 6. 네이버 뉴스 API 설정 (선택 사항)

키가 없으면 Mock 뉴스 데이터로 자동 대체됩니다.

### 6-1. 애플리케이션 등록

1. [https://developers.naver.com/apps](https://developers.naver.com/apps) 접속 후 로그인
2. **Application 등록** 클릭
3. 애플리케이션 이름 입력 (예: `stock-news-reader`)
4. 사용 API에서 **검색** 선택
5. 환경 → **WEB 설정** → 서비스 URL에 `http://localhost` 입력
6. 등록 완료 후 Client ID · Client Secret 복사

### 6-2. .env 설정

```env
NAVER_CLIENT_ID=AbCdEfGhIjKlMnOp
NAVER_CLIENT_SECRET=XyZ123...
```

### 6-3. 동작 방식

- 종목명으로 뉴스 검색 (최근 30일, 최대 20건)
- 제목 · 본문 키워드 기반 감성 분류: 긍정 / 중립 / 부정
- Supabase `news_articles` 테이블에 저장 (없으면 메모리 저장)

---

## 7. OpenDART API 설정 (선택 사항)

키가 없으면 CSV 캐시 → Mock 재무 데이터 순으로 대체됩니다.

### 7-1. API 키 발급

1. [https://opendart.fss.or.kr](https://opendart.fss.or.kr) 접속 후 회원가입 / 로그인
2. **OpenAPI 신청** → 이용 목적 입력 (개인 학습)
3. 발급된 API Key 복사

### 7-2. .env 설정

```env
DART_API_KEY=abcdef1234567890abcdef1234567890
```

### 7-3. 동작 방식

- 종목 코드로 최근 3년치 재무 데이터 조회
  - 매출액 · 영업이익 · 당기순이익 · PER · ROE · 부채비율
- Supabase `financial_metrics`에 저장 (없으면 메모리 저장)
- 조회 실패 시 `data/financial/` CSV 캐시 → Mock 순으로 폴백

---

## 8. 키움 API 안내 (조회 전용)

> ⚠️ **키움 OpenAPI는 조회(시세·일봉) 전용으로만 사용합니다.**  
> **주문 기능은 코드 수준에서 비활성화되어 있으며, 절대 호출하지 않습니다.**

### 8-1. 키움 API 용도

| 용도 | 사용 여부 |
|------|-----------|
| 현재가·일봉 조회 | ✅ 조회 전용 |
| 계좌 잔고 조회 | ❌ 미사용 |
| 매수·매도 주문 | ❌ **비활성화** (코드 내 `_DISABLED_` 접두사) |

### 8-2. 키움 API 설정 (선택)

키가 없으면 FinanceDataReader(무료)로 자동 대체됩니다.

1. 키움증권 계좌 보유 및 OpenAPI 신청 완료 상태 필요
2. 키움 OpenAPI+ 포털에서 App Key · App Secret 발급
3. `.env` 설정:

```env
KIWOOM_APP_KEY=your-kiwoom-app-key
KIWOOM_SECRET_KEY=your-kiwoom-secret-key
```

### 8-3. 가격 데이터 우선순위

```
키움 OpenAPI (조회 전용)
  └→ 실패 시 FinanceDataReader (무료, 인터넷만 있으면 동작)
        └→ 실패 시 Mock 데이터
```

---

## 9. Mock 모드 안내

**모든 API 키가 없어도 앱이 정상 동작합니다.**  
키가 없는 서비스는 자동으로 Mock 데이터로 대체되며, 별도 설정이 필요 없습니다.

### 9-1. Mock 대체 동작

| API | 키 없을 때 동작 |
|-----|----------------|
| Supabase | 메모리 내 저장 (재시작 시 초기화) |
| Naver 뉴스 | 섹터별 템플릿 기반 Mock 뉴스 생성 |
| OpenDART | CSV 캐시 확인 후 → Mock 재무 데이터 |
| 키움 API | FinanceDataReader(무료) → Mock 일봉 |

### 9-2. 데이터 신뢰도 표시

데이터 출처에 따라 3단계 신뢰도를 사이드바와 리포트에 표시합니다.

| 신뢰도 | 가격 | 재무 | 뉴스 |
|--------|------|------|------|
| 높음 | 키움 API | DART | Naver API |
| 보통 | FinanceDataReader | CSV 캐시 | — |
| 낮음 | Mock | Mock | Mock |

사이드바에 **🟡 일부 Mock 모드** 또는 **🔴 전체 Mock 모드** 표시가 나타나면 해당 API 키를 확인하세요.

### 9-3. Mock 모드 강제 설정

```env
MOCK_MODE=true   # 모든 외부 API를 무시하고 Mock 데이터만 사용
```

---

## 10. 앱 실행

```powershell
cd local-stock-assistant
.\.venv\Scripts\activate
streamlit run app.py
```

브라우저에서 자동으로 `http://localhost:8501`이 열립니다.

### 화면 구성 (v0.3)

| 메뉴 | 주요 기능 |
|------|-----------|
| 📋 오늘의 후보 종목 | 5단계 판단 배지 · 종목 목록 · 재무 리스크 필터 · 검색 · 데이터 품질 차트 |
| 🔍 종목 상세 리포트 | 일봉 캔들+MA+RSI 차트 · 8섹션 리포트 · 재무 3년 추이 · 데이터 신뢰도 |
| 📝 매매일지 | 거래 등록 · 수익률 자동 계산 · 내역 조회 |

### 사이드바 업데이트 버튼

| 버튼 | 동작 |
|------|------|
| 📈 종목 업데이트 | 일봉 가격 데이터 갱신 (FDR / 키움) |
| 📰 뉴스 업데이트 | 후보 종목 뉴스 재수집 (Naver API) |
| 💰 재무 업데이트 | 재무 데이터 재조회 (DART API) |
| 🎯 후보 재계산 | 스캐너 재실행 + 캐시 초기화 |

---

## 11. OpenClaw CLI 명령 (v2)

Streamlit 없이 터미널에서 바로 분석을 실행합니다.  
**반드시 프로젝트 루트 디렉토리에서 실행하세요.**

```powershell
cd local-stock-assistant
.\.venv\Scripts\activate
```

### 11-1. 후보 종목 조회

```powershell
python -m openclaw.commands today_candidates
python -m openclaw.commands today_candidates 5     # 상위 5개
python -m openclaw.commands top 10                 # 단축 명령
```

출력 예시:
```
==============================================================
  📈  오늘의 후보 종목 TOP 10   (2026-06-24)
  출처: FinanceDataReader  |  기준일: 2026-06-24
==============================================================
  판단 분포: 🔥 강한 관심 2개  ⭐ 관심 4개  👀 관찰 3개  ⏸ 보류 1개

   1. [🔥 강한 관심] 삼성전자(005930)  92점  +2.3%
   2. [⭐ 관심] 현대차(005380)  78점  +1.1%
```

### 11-2. 데이터 업데이트

```powershell
python -m openclaw.commands update_candidates      # 스캔 + 가격 업데이트 + Supabase 저장
```

출력 예시:
```
[1/3] 후보 재스캔... 완료 (27종목 발견)
[2/3] 일봉 데이터 업데이트... 완료 (27종목, FDR 소스)
[3/3] Supabase 저장... 완료 (27건 upsert)
업데이트 완료: 27종목
```

### 11-3. 종목 분석 리포트

```powershell
python -m openclaw.commands analyze_stock 삼성전자
python -m openclaw.commands analyze_stock 005930    # 종목코드로도 가능
python -m openclaw.commands report 현대차           # 단축 명령
```

출력 항목: 기본 정보 / 기술적 분석 / 재무 요약 / 뉴스 감성 / 최종 투자 판단 / 데이터 신뢰도 / 한 줄 결론

### 11-4. 뉴스 감성 요약

```powershell
python -m openclaw.commands news_summary 삼성전자
python -m openclaw.commands news_summary SK하이닉스
```

출력 예시:
```
  출처: Naver API  |  기준일: 2026-06-24  |  전체: 12건
  감성 막대: 긍정[████████████████░░░░░░░░░░░░]부정
  📈 긍정 7건(58%)  📊 중립 3건(25%)  📉 부정 2건(17%)
  종합 판단: 긍정 우위 → 시장 분위기 양호
```

### 11-5. 재무 3년 요약

```powershell
python -m openclaw.commands financial_summary 삼성전자
python -m openclaw.commands fin 현대차              # 단축 명령
```

출력 예시:
```
  출처: DART API  |  최신연도: 2024
  연도   매출액(억)  영업이익  영업이익률  PER   ROE   부채비율
  2022   3,005,700   437,600    14.6%    9.8  17.3    40.2%
  2023   2,589,300   106,900     4.1%   19.1   4.4    39.1%
  2024   3,007,500   322,400    10.7%   13.2  12.8    41.8%
```

### 11-6. 뉴스 갱신 (Naver API → Supabase)

```powershell
python -m openclaw.commands refresh_news 삼성전자
```

### 11-7. 가격 갱신 (FDR/키움 → Supabase)

```powershell
python -m openclaw.commands refresh_prices 삼성전자
python -m openclaw.commands refresh_price 005930   # 단축 명령
```

### 11-8. 매매 메모 저장

```powershell
python -m openclaw.commands save_trade_note 삼성전자 "분할매수 검토"
python -m openclaw.commands save_trade_note 현대차 "실적 발표 후 재검토 예정"
```

### 11-9. 도움말

```powershell
python -m openclaw.commands help
python -m openclaw.commands --help
```

> ⛔ **주문 명령은 차단됩니다.**  
> `매수주문`, `매도주문`, `place_order`, `order` 등 입력 시 "실거래 주문 기능은 지원하지 않습니다"를 출력하고 즉시 종료합니다.

---

## 12. scheduler.py 수동 배치 실행

자동 스케줄러가 아닌, 필요할 때 수동으로 호출하는 배치 스크립트입니다.

```powershell
cd local-stock-assistant
.\.venv\Scripts\activate
```

### 12-1. 명령 목록

| 명령 | 동작 |
|------|------|
| `update_candidates` | FDR/키움으로 일봉 가격 데이터 갱신 |
| `update_news` | Naver API로 상위 종목 뉴스 갱신 |
| `update_financial` | DART API로 재무 데이터 갱신 |
| `generate_reports` | 종합 리포트 생성 (`data/reports/` + Supabase) |
| `all` | 위 4단계를 순서대로 전체 실행 |

### 12-2. 사용 예시

```powershell
# 가격 데이터만 갱신
python scheduler.py update_candidates

# 상위 15개 종목 뉴스 갱신
python scheduler.py update_news --top 15

# 점수 60점 이상 종목만 재무 갱신
python scheduler.py update_financial --min-score 60

# 상위 5개 종목 리포트 생성
python scheduler.py generate_reports --top 5

# 전체 파이프라인 실행 (가격 → 뉴스 → 재무 → 리포트)
python scheduler.py all --top 20
```

### 12-3. 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--top N` | 처리할 상위 종목 수 | 20 |
| `--min-score N` | 최소 스캐너 점수 | 40 |

### 12-4. 로그 및 저장 위치

| 항목 | 경로 |
|------|------|
| 실행 로그 | `logs/scheduler.log` (5MB × 3개 자동 순환) |
| 리포트 JSON | `data/reports/{종목코드}_{날짜}.json` |
| Supabase | `stock_reports` 테이블 (연결된 경우) |

### 12-5. 에러 처리

- 종목별 try/except 격리 — 1개 실패해도 나머지 종목 계속 처리
- API 오류 → Mock 모드 자동 전환 후 계속 실행
- 전체 프로그램이 중단되지 않습니다

> ⛔ **주문 관련 명령은 scheduler.py에서도 차단됩니다.**

---

## 13. 실거래 주문 기능 없음

```
⛔ 이 프로그램은 실거래 주문 기능을 제공하지 않습니다.
```

- 키움증권 등 증권사 주문 API를 호출하지 않습니다.
- 코드 내 주문 관련 함수는 `_DISABLED_` 접두사로 비활성화되어 있습니다.
- 해당 함수 호출 시 `NotImplementedError`가 발생합니다.
- OpenClaw CLI와 scheduler.py에서 주문 키워드 입력 시 즉시 차단 메시지를 출력합니다.

차단되는 키워드: `매수주문` · `매도주문` · `place_order` · `order` · `buy_order` · `sell_order` · `주문`

---

## 14. 폴더 구조

```
local-stock-assistant/
│
├── app.py                      # Streamlit 메인 앱 v0.3 (사이드바 메뉴)
├── scheduler.py                # 수동 배치 스크립트 (4개 명령)
├── config.py                   # API 키 중앙 관리 + is_*_available()
├── requirements.txt
├── .env.example                # 환경변수 예시 (커밋 허용)
├── .gitignore
│
├── services/                   # 데이터 서비스 레이어
│   ├── market_data.py          # 시장 데이터 조회 (키움 → FDR → Mock)
│   ├── price_service.py        # 일봉 OHLCV 수집·저장·조회 (v2)
│   ├── news_data.py            # Naver 뉴스 수집 + 감성 분류 (v2)
│   ├── financial_data.py       # DART 재무 조회 + CSV 캐시 (v2)
│   ├── supabase_client.py      # Supabase 연결 / Mock 자동 전환
│   ├── db_service.py           # DB 라우터 (Supabase ↔ Mock, Streamlit 전용)
│   └── mock_db_service.py      # 인메모리 Mock DB
│
├── strategy/                   # 분석 전략 레이어
│   ├── scanner.py              # 후보 종목 점수화 19개 규칙, 5단계 판단 (v2)
│   └── indicators.py           # 기술 지표 계산 (MA, RSI, 거래량비율)
│
├── analysis/                   # 리포트 생성 레이어
│   └── stock_report.py         # 8섹션 리포트, 5단계 판정, 데이터 신뢰도 (v2)
│
├── openclaw/                   # OpenClaw CLI 통합
│   └── commands.py             # 7개 명령, 주문 차단 (v2)
│
├── openclaw-skills/            # OpenClaw Skill 정의
│   ├── stock-risk-guard/
│   │   └── SKILL.md
│   └── stock-analysis-core/
│       └── SKILL.md
│
├── data/
│   ├── mock_stocks.py          # 종목 마스터 샘플 데이터
│   ├── financial/              # DART CSV 캐시 (자동 생성)
│   └── reports/                # 리포트 JSON (scheduler.py 생성)
│
├── logs/
│   └── scheduler.log           # 배치 실행 로그 (자동 생성)
│
└── sql/
    ├── schema.sql              # Supabase PostgreSQL DDL v1
    └── schema_v3.sql           # Supabase PostgreSQL DDL v3 (news_articles 포함)
```

---

## 15. GitHub 최초 업로드

### 사전 확인

업로드 전 아래 항목을 반드시 확인하세요.

```powershell
# .env 파일이 추적 대상이 아닌지 확인 (출력에 .env가 없어야 함)
git status

# .gitignore가 .env를 제외하는지 확인
git check-ignore -v .env
```

### GitHub 저장소 생성

1. [https://github.com/new](https://github.com/new) 접속
2. Repository name: `local-stock-assistant`
3. **Private** 선택 (API 키 등 민감 정보 방지)
4. **Create repository** 클릭

### 업로드 명령

```powershell
cd "C:\Users\YOUR_USERNAME\path\to\local-stock-assistant"

git init
git add .
git commit -m "feat: local-stock-assistant v2 초기 커밋"
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

### 절대 커밋하지 말아야 할 파일

| 파일 | 이유 |
|------|------|
| `.env` | Supabase · Naver · DART · 키움 API 키 포함 |
| `.venv/` | 가상환경 (수백 MB, 재설치 가능) |
| `__pycache__/` | Python 컴파일 캐시 |
| `logs/*.log` | 로그 파일 |
| `data/financial/*.csv` | DART 캐시 (자동 재생성됨) |

위 파일은 `.gitignore`에 이미 포함되어 있으나, `git add .` 전에 반드시 `git status`로 확인하세요.

---

## 16. 2차 개발 성공 기준 및 테스트 순서

### 16-1. 성공 기준 (13개 체크 항목)

아래 13개 항목을 모두 통과하면 2차 개발 완료로 판정합니다.

| # | 항목 | 확인 방법 |
|---|------|-----------|
| 1 | app.py 구문 오류 없음 | `python -c "import ast; ast.parse(open('app.py').read())"` |
| 2 | Mock 모드 정상 실행 | API 키 없이 앱 실행 → 종목 목록 표시 |
| 3 | Supabase 연결 여부 표시 | 사이드바 API 상태 위젯 표시 |
| 4 | Naver 키 없을 때 Mock 뉴스 대체 | 뉴스 조회 시 source="Mock" |
| 5 | DART 키 없을 때 Mock 재무 대체 | 재무 조회 시 fin_source="Mock" |
| 6 | 키움 키 없을 때 FDR/Mock 시세 대체 | 일봉 데이터 30행 이상 반환 |
| 7 | 스캐너 v2 19규칙 5단계 판단 정상 | decision: 강한관심/관심/관찰/보류/제외 |
| 8 | 8섹션 리포트 생성 | generate_report() → 8섹션 + 신뢰도 등급 |
| 9 | 데이터 출처·기준일 표시 | data_source, ref_date 컬럼 존재 |
| 10 | OpenClaw CLI 7개 명령 실행 | `python -m openclaw.commands --help` |
| 11 | scheduler.py 수동 실행 | `python scheduler.py --help` |
| 12 | 실거래 주문 명령 차단 | 주문 키워드 입력 → 즉시 차단 메시지 |
| 13 | .env GitHub 제외 | `git check-ignore -v .env` |

### 16-2. 테스트 순서 (단계별 실행 명령)

**준비**

```powershell
cd local-stock-assistant
.\.venv\Scripts\activate
```

---

**STEP 1 — 환경 및 구문 확인**

```powershell
# 패키지 설치 확인
pip list | Select-String "streamlit|pandas|plotly|finance-datareader|supabase"

# app.py 구문 오류 확인
python -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('OK')"

# .env 파일 존재 확인 (.env.example을 복사했는지)
Test-Path .env
```

---

**STEP 2 — Mock 모드 기본 동작 확인**

```powershell
# 시장 데이터 + 스캐너 동작 확인
python -c "
from services.market_data import get_market_data
from strategy.scanner import scan
mdf = get_market_data()
sdf = scan(mdf)
print(f'종목수: {len(mdf)}  스캐너: {len(sdf)}')
print(f'출처: {mdf[\"data_source\"].iloc[0]}')
print(f'기준일: {mdf[\"ref_date\"].iloc[0]}')
print(f'판단분포: {dict(sdf[\"decision\"].value_counts())}')
"
```

기대 출력: 종목수 29개 이상, 기준일 오늘 날짜, 판단 분포 표시

---

**STEP 3 — Mock 폴백 확인 (API 키 없이)**

```powershell
# 뉴스: Naver 키 없음 → Mock 뉴스 대체
python -c "
from services.news_data import get_news_for_stock
news = get_news_for_stock(stock_code='005930')
print(f'뉴스 {len(news)}건 | 출처: {news[0][\"source\"]}')
"

# 재무: DART 키 없음 → Mock 재무 대체
python -c "
from services.financial_data import get_financial_metrics
fm = get_financial_metrics('005930', '삼성전자')
print(f'재무 출처: {fm[\"fin_source\"]}  연도수: {len(fm[\"years\"])}')
"

# 가격: 키움 없음 → FDR 또는 Mock 대체
python -c "
from services.price_service import fetch_daily_prices
ph = fetch_daily_prices('005930', days=30)
print(f'일봉 {len(ph)}행 | 컬럼: {list(ph.columns[:6])}')
"
```

---

**STEP 4 — 리포트 생성 확인**

```powershell
python -c "
from services.market_data import get_market_data
from strategy.scanner import scan
from services.news_data import get_news_for_stock
from services.financial_data import get_financial_metrics
from services.price_service import fetch_daily_prices
from analysis.stock_report import generate_report

mdf = get_market_data()
sdf = scan(mdf)
code = '005930'
mrow = mdf[mdf['stock_code']==code].iloc[0]
srow = sdf[sdf['stock_code']==code].iloc[0]
news = get_news_for_stock(stock_code=code)
fm   = get_financial_metrics(code, '삼성전자')
ph   = fetch_daily_prices(code, days=60)
r    = generate_report(mrow, srow, news, fin_source=fm['fin_source'],
                       financial_years=fm['years'], price_history=ph)
print('섹션:', list(r.keys()))
print('판정:', r['최종_판단']['판정'])
print('신뢰도:', r['데이터_신뢰도']['종합_등급'])
"
```

기대 출력: 8개 섹션, 판정(5단계 중 하나), 신뢰도 등급

---

**STEP 5 — Streamlit 앱 실행**

```powershell
streamlit run app.py
```

브라우저 `http://localhost:8501` 에서 확인:
- [ ] 사이드바 API 연결 상태 4행 표시 (Supabase · 키움 · Naver · DART)
- [ ] 오늘의 후보 종목: 5단계 판단 배지 표시
- [ ] 종목 선택 → 일봉 차트 + RSI 표시
- [ ] 재무 3년 추이 테이블 표시
- [ ] 데이터 신뢰도 섹션 표시

---

**STEP 6 — OpenClaw CLI 확인**

```powershell
# 도움말 확인 (7개 명령 표시)
python -m openclaw.commands --help

# 후보 종목 Top 5 출력
python -m openclaw.commands today_candidates 5

# 종목 분석 리포트
python -m openclaw.commands analyze_stock 삼성전자

# 주문 명령 차단 확인
python -m openclaw.commands 매수주문
# 기대: "실거래 주문 기능은 지원하지 않습니다"
```

---

**STEP 7 — scheduler.py 배치 실행 확인**

```powershell
# 도움말
python scheduler.py --help

# 가격 업데이트 (Mock 모드로 실행됨)
python scheduler.py update_candidates --top 5

# 로그 확인
Get-Content logs\scheduler.log -Tail 20

# 주문 명령 차단 확인
python scheduler.py 매수주문
# 기대: "실거래 주문 기능은 지원하지 않습니다"
```

---

**STEP 8 — 보안 확인**

```powershell
# .env가 git 추적 대상이 아닌지 확인
git check-ignore -v .env
# 기대: .gitignore:1:.env    .env

# git status에 .env가 없는지 확인
git status
# 기대: .env 가 표시되지 않아야 함
```

---

### 16-3. API 연결 후 추가 확인 사항

API 키를 `.env`에 설정한 뒤 아래를 추가로 확인하세요.

| API | 설정 키 | 확인 명령 |
|-----|--------|-----------|
| Supabase | `SUPABASE_URL` + `SUPABASE_ANON_KEY` | 사이드바 → Supabase 연결됨 표시 |
| Naver 뉴스 | `NAVER_CLIENT_ID` + `NAVER_CLIENT_SECRET` | `python -m openclaw.commands refresh_news 삼성전자` |
| OpenDART | `DART_API_KEY` | `python -m openclaw.commands financial_summary 삼성전자` → 출처: DART |
| 키움 | `KIWOOM_APP_KEY` + `KIWOOM_SECRET_KEY` | `python -m openclaw.commands refresh_prices 삼성전자` → 출처: Kiwoom |

---

## 라이선스

개인 학습 · 비상업적 사용 목적으로 제작되었습니다.  
상업적 이용 및 재배포 시 작성자에게 문의하세요.

---

*본 분석 도구는 투자 참고용이며, 수익을 보장하지 않습니다.*  
*실거래 주문 기능은 없으며, 투자 결정과 손익은 전적으로 본인 책임입니다.*
