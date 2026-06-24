# 📈 local-stock-assistant

> **개인 PC에서 실행하는 주식 후보 발굴 · 분석 · 매매일지 관리 도구**  
> Python · Streamlit · Supabase (선택)

---

> ⚠️ **투자 유의사항**  
> 이 프로그램은 **개인 학습 및 분석 보조 목적**으로 제작된 참고 도구입니다.  
> 표시되는 점수, 등급, 투자 판단은 **알고리즘 기반 참고 정보**이며, **수익을 보장하지 않습니다.**  
> 실제 투자 결정과 그에 따른 손익은 **전적으로 본인 책임**입니다.  
> **실거래 주문 기능은 없습니다.**

---

## 목차

1. [주요 기능](#1-주요-기능)
2. [스크린샷](#2-스크린샷)
3. [설치 방법](#3-설치-방법)
4. [환경변수 설정](#4-환경변수-설정)
5. [Supabase 설정](#5-supabase-설정-선택-사항)
6. [앱 실행](#6-앱-실행)
7. [OpenClaw CLI 명령](#7-openclaw-cli-명령)
8. [Mock 모드 안내](#8-mock-모드-안내)
9. [실거래 주문 기능 없음](#9-실거래-주문-기능-없음)
10. [폴더 구조](#10-폴더-구조)
11. [GitHub 업로드](#11-github-최초-업로드)

---

## 1. 주요 기능

| 기능 | 설명 |
|------|------|
| 📋 후보 종목 스캐너 | 30개 종목을 10개 규칙으로 자동 점수화 (0~100점) |
| 🔍 종목 상세 리포트 | 기술적 점수 · 재무 요약 · 뉴스 감성 · 최종 투자 판단 |
| 📰 뉴스/이슈 | 섹터별 Mock 뉴스, 감성(긍정/중립/부정) 필터 |
| 📝 매매일지 | 거래 내역 등록 · 조회 · Supabase 저장 |
| 🖥️ OpenClaw CLI | Streamlit 없이 터미널에서 분석 명령 실행 |

**기술 스택:** Python 3.10+, Streamlit, pandas, plotly, Supabase PostgreSQL, python-dotenv

---

## 2. 스크린샷

```
┌──────────────────────────────────────────────────────────────┐
│  사이드바         │  메인 화면                                │
│  ─────────────── │  ─────────────────────────────────────── │
│  📋 오늘의 후보   │  📊 점수 상위 10개 종목 차트              │
│  🔍 종목 상세     │  🎯 판단별 종목 분포 파이차트             │
│  📰 뉴스/이슈    │  종목 목록 (필터링 · 점수 ProgressBar)    │
│  📝 매매일지     │                                           │
│  ─────────────── │                                           │
│  🟡 Mock 모드    │                                           │
│  🔄 새로고침     │                                           │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 설치 방법

> **전제 조건:** Python 3.10 이상이 설치되어 있어야 합니다.

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

> 활성화 오류 시 아래 명령 후 재시도:
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

`.env` 파일 예시:

```env
# Supabase 연결 정보 (없으면 Mock 모드로 자동 실행)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here

# Mock 모드 (true = Supabase 미사용, false = Supabase 연결)
MOCK_MODE=true

# OpenAI API (선택 — 없으면 Mock 뉴스 텍스트 사용)
OPENAI_API_KEY=sk-...
```

> `.env` 파일은 `.gitignore`에 포함되어 있어 GitHub에 업로드되지 않습니다.  
> **절대로 `.env` 파일을 커밋하지 마세요.**

---

## 5. Supabase 설정 (선택 사항)

Supabase 없이도 Mock 모드로 모든 기능을 사용할 수 있습니다.  
데이터를 영구 저장하려면 아래 절차를 따르세요.

### 5-1. Supabase 프로젝트 생성

1. [https://supabase.com](https://supabase.com) 접속 후 로그인
2. **New Project** 클릭 → 프로젝트 이름 입력 → 데이터베이스 비밀번호 설정
3. 생성 완료 후 **Settings → API** 메뉴로 이동

### 5-2. API 키 확인

| 항목 | 위치 |
|------|------|
| `SUPABASE_URL` | Settings → API → Project URL |
| `SUPABASE_ANON_KEY` | Settings → API → anon (public) key |

### 5-3. 데이터베이스 스키마 생성

1. Supabase 대시보드 → **SQL Editor** 클릭
2. `sql/schema.sql` 파일 내용을 전체 복사
3. SQL Editor에 붙여넣기 후 **Run** 클릭

생성되는 테이블:

| 테이블 | 용도 |
|--------|------|
| `stocks` | 종목 마스터 |
| `candidate_scores` | 스캐너 점수 결과 |
| `news_items` | 뉴스 데이터 |
| `stock_reports` | 종목 상세 리포트 |
| `trade_journal` | 매매일지 |

### 5-4. .env 연결 설정

```env
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6...
MOCK_MODE=false
```

---

## 6. 앱 실행

```powershell
streamlit run app.py
```

브라우저에서 자동으로 `http://localhost:8501`이 열립니다.

### 화면 구성

| 메뉴 | 주요 기능 |
|------|-----------|
| 📋 오늘의 후보 종목 | 점수 상위 종목 목록, 판단별 분포 차트, 점수 저장 |
| 🔍 종목 상세 리포트 | 기술 지표, 재무 레이더, 최종 투자 판단, 과거 리포트 조회 |
| 📰 뉴스/이슈 | 종목별/섹터별 뉴스, 감성 필터, 영향도 슬라이더 |
| 📝 매매일지 | 거래 등록 (매수/매도), 수익률 자동 계산, 내역 조회 |

---

## 7. OpenClaw CLI 명령

Streamlit 없이 터미널에서 바로 분석을 실행합니다.  
**반드시 프로젝트 루트 디렉토리에서 실행하세요.**

```powershell
cd local-stock-assistant
.\.venv\Scripts\activate
```

### 7-1. 후보 종목 조회

```powershell
python -m openclaw.commands today_candidates
python -m openclaw.commands today_candidates 5   # 상위 5개
```

출력 예시:
```
==============================================================
  📈  오늘의 후보 종목 TOP 10   (2026-06-24)
==============================================================
   1. [관심] 삼성물산(028260)  80점  +4.90%  거래대금 276억  뉴스 9건
      ✅ 거래대금 100억 이상 (+20) / 종가가 MA5 위 (+15)
```

### 7-2. 종목 분석 리포트

```powershell
python -m openclaw.commands analyze_stock 삼성전자
python -m openclaw.commands analyze_stock 005930   # 종목코드로도 가능
```

출력 항목: 기본 정보 / 기술적 점수 / 재무 요약 / 뉴스 감성 / 최종 투자 판단 / 한 줄 결론

### 7-3. 뉴스 감성 요약

```powershell
python -m openclaw.commands news_summary 삼성전자
python -m openclaw.commands news_summary SK하이닉스
```

출력 예시:
```
  전체: 5건  |  📈 긍정 3건 (60%)  📊 중립 1건 (20%)  📉 부정 1건 (20%)
  감성 막대: 긍정[██████████████████░░░░░░░░░░░░]부정
  종합 판단: 긍정 우위 → 시장 분위기 양호
```

### 7-4. 매매 메모 저장

```powershell
python -m openclaw.commands save_trade_note 삼성전자 "분할매수 검토"
python -m openclaw.commands save_trade_note 현대차 "실적 발표 후 재검토 예정"
```

### 7-5. 도움말

```powershell
python -m openclaw.commands help
```

> ⛔ **주문 명령은 차단됩니다.**  
> `매수주문`, `매도주문` 등 거래 관련 명령 입력 시 "실거래 주문 기능은 지원하지 않습니다"라고 응답합니다.

---

## 8. Mock 모드 안내

**Supabase 연결 없이도 모든 기능이 동작합니다.**

| 항목 | Mock 모드 동작 |
|------|---------------|
| 종목 데이터 | 고정 시드(42)로 생성된 샘플 30개 종목 |
| 뉴스 | 섹터별 템플릿 기반 Mock 뉴스 (결정론적 생성) |
| 매매일지 | 앱 실행 중 메모리 저장, 재시작 시 초기화 |
| DB 저장 버튼 | 메모리 내 저장 (재시작 시 리셋) |

사이드바에 **🟡 Mock 모드 실행 중** 표시가 나타나면 정상입니다.

---

## 9. 실거래 주문 기능 없음

```
⛔ 이 프로그램은 실거래 주문 기능을 제공하지 않습니다.
```

- 키움증권·한국투자증권 등 증권사 API와 연동되지 않습니다.
- 코드 내 주문 관련 함수는 `_DISABLED_` 접두사로 비활성화되어 있습니다.
- 해당 함수 호출 시 `NotImplementedError`가 발생합니다.
- OpenClaw CLI에서 주문 명령 입력 시 즉시 차단 메시지를 출력합니다.

---

## 10. 폴더 구조

```
local-stock-assistant/
│
├── app.py                      # Streamlit 메인 앱 (사이드바 메뉴 방식)
├── requirements.txt
├── .env.example                # 환경변수 예시 (커밋 허용)
├── .gitignore
│
├── services/                   # 데이터 서비스 레이어
│   ├── market_data.py          # 샘플 종목 30개 생성
│   ├── news_data.py            # Mock 뉴스 생성 (섹터별)
│   ├── supabase_client.py      # Supabase 연결 / Mock 자동 전환
│   ├── db_service.py           # DB 라우터 (Supabase ↔ Mock)
│   └── mock_db_service.py      # 인메모리 Mock DB
│
├── strategy/                   # 분석 전략 레이어
│   ├── scanner.py              # 후보 종목 점수화 (10개 규칙)
│   └── indicators.py           # 기술 지표 계산 (MA, RSI, 거래량비율)
│
├── analysis/                   # 리포트 생성 레이어
│   └── stock_report.py         # 경량 종합 리포트 생성기
│
├── openclaw/                   # OpenClaw CLI 통합
│   └── commands.py             # 4개 명령 (Streamlit 불필요)
│
├── openclaw-skills/            # OpenClaw Skill 정의
│   ├── stock-risk-guard/
│   │   └── SKILL.md            # 안전 가드레일 Skill
│   └── stock-analysis-core/
│       └── SKILL.md            # 분석 리포트 Skill
│
├── data/
│   └── mock_stocks.py          # 종목 마스터 30개
│
├── modules/                    # 레거시 모듈 (참조용)
│   ├── scoring.py
│   ├── report.py
│   ├── news.py
│   ├── financials.py
│   ├── judgment.py
│   └── db.py
│
└── sql/
    └── schema.sql              # Supabase PostgreSQL DDL
```

---

## 11. GitHub 최초 업로드

### 사전 확인 사항

업로드 전 아래 항목을 반드시 확인하세요.

```powershell
# 1. .env 파일이 추적 대상이 아닌지 확인 (출력에 .env가 없어야 함)
git status

# 2. .gitignore가 .env를 제외하는지 확인
git check-ignore -v .env
```

### GitHub 저장소 생성

1. [https://github.com/new](https://github.com/new) 접속
2. Repository name: `local-stock-assistant`
3. **Private** 선택 (API 키 등 민감 정보 방지)
4. **Create repository** 클릭

### 업로드 명령

```powershell
# 프로젝트 루트에서 실행
cd "C:\Users\YOUR_USERNAME\path\to\local-stock-assistant"

git init
git add .
git commit -m "feat: local-stock-assistant 초기 커밋"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/local-stock-assistant.git
git push -u origin main
```

> `YOUR_USERNAME`을 본인의 GitHub 사용자명으로 교체하세요.

### 이후 변경사항 커밋

```powershell
git add .
git commit -m "feat: 기능 설명"
git push
```

### 주의 — 절대 커밋하지 말아야 할 파일

| 파일 | 이유 |
|------|------|
| `.env` | Supabase 키, OpenAI 키 포함 |
| `.venv/` | 가상환경 (수백 MB, 재설치 가능) |
| `__pycache__/` | Python 컴파일 캐시 |
| `*.log` | 로그 파일 |
| `*.db` / `*.sqlite` | 로컬 데이터베이스 |

위 파일은 `.gitignore`에 이미 포함되어 있으나,  
`git add .` 이전에 반드시 `git status`로 확인하는 습관을 권장합니다.

---

## 라이선스

개인 학습 · 비상업적 사용 목적으로 제작되었습니다.  
상업적 이용 및 재배포 시 작성자에게 문의하세요.

---

*본 분석 도구는 투자 참고용이며, 수익을 보장하지 않습니다.*
