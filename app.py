"""
app.py v2 – local-stock-assistant 메인 대시보드
사이드바 메뉴로 4개 화면을 전환합니다.
실행: streamlit run app.py
"""

import os
import sys
import json
from datetime import date
from dotenv import load_dotenv

# Streamlit 스크립트 재실행 시 sys.path 보장
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# 서비스 모듈 — 모듈 레벨에서 import (Streamlit cache_data 내부 lazy import 충돌 방지)
try:
    from services.market_data import get_market_data
except ImportError:
    from services.market_data import get_sample_market_data as get_market_data
from strategy.scanner import scan

load_dotenv()

# ════════════════════════════════════════════════════════════════
# 페이지 설정
# ════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="주식 분석 도우미",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ════════════════════════════════════════════════════════════════
# 세션 상태 초기화
# ════════════════════════════════════════════════════════════════
_ss_defaults = {
    "refresh_key":         0,
    "save_done":           False,
    "price_update_msg":    None,   # None | (level, text)
    "news_update_msg":     None,
    "fin_update_msg":      None,
    "rescan_msg":          None,
    "paper_trade_result":  None,   # 일일 모의매매 실행 결과
    "paper_reset_confirm": False,  # 포트폴리오 초기화 확인 단계
    "bt_result":           None,   # 백테스트 결과 dict
    "bt_running":          False,  # 백테스트 실행 중 플래그
    "order_action_msg":    None,   # 주문 승인/거절/전송 결과 메시지
    "reject_pending_id":   None,   # 거절 확인 중인 order_intent id
    "settings_msg":        None,   # 안전 설정 저장 결과 메시지
}
for k, v in _ss_defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ════════════════════════════════════════════════════════════════
# 데이터 로드 (캐시)
# ════════════════════════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def _load_data(_key: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """market_df, scored_df를 함께 반환. _key 변경 시 캐시 무효화."""
    df     = get_market_data()
    scored = scan(df)
    return df, scored


@st.cache_data(ttl=120, show_spinner=False)
def _load_price_history(_code: str, _key: int) -> pd.DataFrame:
    """종목 일봉 데이터 로드 (캐시 2분)."""
    from services.price_service import fetch_daily_prices
    return fetch_daily_prices(_code, days=365)


@st.cache_data(ttl=300, show_spinner=False)
def _load_fin_metrics(_code: str, _name: str, _key: int) -> dict:
    """재무 지표 로드 (캐시 5분)."""
    from services.financial_data import get_financial_metrics
    return get_financial_metrics(_code, _name)


def _get_news_for_stock_safe(stock_code: str | None = None, stock_name: str | None = None) -> list[dict]:
    """news_data 모듈 버전 차이를 흡수하는 뉴스 조회 wrapper."""
    import services.news_data as news_data

    if hasattr(news_data, "get_news_for_stock"):
        return news_data.get_news_for_stock(stock_code=stock_code, stock_name=stock_name)
    if hasattr(news_data, "get_news"):
        return news_data.get_news(stock_code=stock_code, stock_name=stock_name)
    return news_data.get_mock_news(stock_code=stock_code, stock_name=stock_name)


def _summarize_news_safe(news_items: list[dict]) -> dict:
    """뉴스 감성 요약 함수명 변경에 대한 하위호환 wrapper."""
    import services.news_data as news_data

    if hasattr(news_data, "summarize_news_sentiment"):
        return news_data.summarize_news_sentiment(news_items)
    return news_data.get_news_summary(news_items)


def _fetch_news_from_naver_safe(stock_name: str, **kwargs) -> list[dict]:
    """Naver API 함수가 없는 버전에서는 빈 목록을 반환."""
    import services.news_data as news_data

    if hasattr(news_data, "fetch_news_from_naver"):
        return news_data.fetch_news_from_naver(stock_name, **kwargs)
    return []


def _save_news_to_supabase_safe(news_items: list[dict]) -> dict:
    """뉴스 저장 함수가 없는 버전에서는 저장을 건너뜀."""
    import services.news_data as news_data

    if hasattr(news_data, "save_news_to_supabase"):
        return news_data.save_news_to_supabase(news_items)
    return {"saved": 0, "skipped": len(news_items), "error": "save_news_to_supabase 미지원"}


# ════════════════════════════════════════════════════════════════
# 헬퍼 상수 & 함수
# ════════════════════════════════════════════════════════════════
DECISION_COLOR = {
    "강한 관심": "#1A5E35",
    "관심":     "#27AE60",
    "관찰":     "#F39C12",
    "보류":     "#95A5A6",
    "제외":     "#E74C3C",
}
DECISION_ORDER = ["강한 관심", "관심", "관찰", "보류", "제외"]

_VERDICT_COLOR = {
    "적극 매수": "#1A5276",
    "분할 매수": "#27AE60",
    "관망":     "#F39C12",
    "비중 축소": "#E67E22",
    "매도":     "#E74C3C",
}
_SENT_COLOR = {"긍정": "#27AE60", "중립": "#F39C12", "부정": "#E74C3C"}
_SENT_ICON  = {"긤정": "📈", "긍정": "📈", "중립": "📊", "부정": "📉"}

_DQ_COLOR = {
    "실제 데이터": "#1A5E35",
    "일부 Mock":   "#F39C12",
    "Mock":        "#95A5A6",
}
_GRADE_COLOR = {"A": "#27AE60", "B": "#F39C12", "C": "#95A5A6"}


def _badge(label: str, color_map: dict | None = None) -> str:
    color = (color_map or DECISION_COLOR).get(label, "#888")
    return (
        f"<span style='background:{color};color:white;"
        f"padding:2px 10px;border-radius:6px;font-weight:bold'>{label}</span>"
    )


def _change_rate_color(v: float) -> str:
    return "#E74C3C" if v > 0 else ("#2980B9" if v < 0 else "#7F8C8D")


def _change_rate_badge(v: float) -> str:
    c = _change_rate_color(v)
    icon = "▲" if v > 0 else ("▼" if v < 0 else "－")
    return (
        f"<span style='display:inline-block;color:{c};background:{c}18;"
        f"border:1px solid {c};padding:3px 10px;border-radius:999px;"
        f"font-weight:700;font-size:14px'>{icon} {v:+.2f}%</span>"
    )


def _style_change_rate(v: float) -> str:
    c = _change_rate_color(v)
    return f"color:{c};background-color:{c}18;font-weight:700"


def _merge_with_market(scored: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    extra = market[[
        "stock_code", "market", "sector",
        "current_price", "change_rate",
        "trading_value", "news_count",
    ]]
    return scored.merge(extra, on="stock_code", how="left")


def _dq_badge_html(dq: str) -> str:
    color = _DQ_COLOR.get(dq, "#888")
    return (
        f"<span style='background:{color}22;border:1px solid {color};"
        f"color:{color};padding:1px 7px;border-radius:4px;font-size:11px'>{dq}</span>"
    )


def _render_menu_title(title: str, guide: str) -> None:
    """메뉴 제목과 사용 목적 안내를 함께 표시한다."""
    st.markdown(
        f"""
        <div style="display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap;margin:0 0 12px 0">
            <h1 style="margin:0;font-size:2.25rem;line-height:1.2">{title}</h1>
            <div style="
                border:1px solid #D6EAF8;
                background:#F4FAFF;
                color:#2C3E50;
                border-radius:8px;
                padding:7px 11px;
                font-size:0.92rem;
                line-height:1.35;
                max-width:720px;
            ">
                <b>사용 목적</b> · {guide}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _has_fin_risk(row: pd.Series) -> bool:
    return (
        float(row.get("per", 0))        < 0
        or float(row.get("roe", 0))     < 0
        or float(row.get("debt_ratio", 0)) >= 200
        or float(row.get("per", 0))     > 50
    )


# ════════════════════════════════════════════════════════════════
# 사이드바
# ════════════════════════════════════════════════════════════════
def _render_sidebar(market_df: pd.DataFrame, scored_df: pd.DataFrame) -> str:
    """사이드바 전체 렌더링. 선택된 메뉴명을 반환."""
    with st.sidebar:
        st.title("📈 주식 분석 도우미")
        st.caption("local-stock-assistant v0.3")
        st.divider()

        # ── API 연결 상태 ─────────────────────────────────────
        _render_api_status()
        st.divider()

        # ── 메뉴 ─────────────────────────────────────────────
        menu = st.radio(
            "메뉴 선택",
            [
                "📋 오늘의 후보 종목",
                "🔍 종목 상세 리포트",
                "📰 뉴스/이슈",
                "📝 매매일지",
                "💼 모의투자",
                "📊 모의 포트폴리오",
                "🏆 전략 성과",
                "🧪 백테스트",
                "✅ 주문 승인",
                "⚙️ 안전 설정",
                "📋 주문 로그",
            ],
            label_visibility="collapsed",
        )
        st.divider()

        # ── 업데이트 버튼들 ───────────────────────────────────
        st.markdown("**🔄 데이터 업데이트**")
        ub1, ub2 = st.columns(2)

        with ub1:
            if st.button("📈 종목 데이터", width="stretch"):
                _do_price_update(scored_df)
            if st.button("💰 재무 데이터", width="stretch"):
                _do_fin_update(market_df)

        with ub2:
            if st.button("📰 뉴스", width="stretch"):
                _do_news_update(market_df)
            if st.button("🎯 후보 재계산", width="stretch"):
                _do_rescan()

        # 업데이트 결과 메시지
        for msg_key in ["price_update_msg", "news_update_msg", "fin_update_msg", "rescan_msg"]:
            msg = st.session_state.get(msg_key)
            if msg:
                level, text = msg
                if level == "success":
                    st.success(text, icon="✅")
                elif level == "error":
                    st.error(text, icon="❌")
                else:
                    st.info(text, icon="ℹ️")

        st.divider()

        # ── 데이터 현황 ───────────────────────────────────────
        _render_data_status(market_df, scored_df)

    return menu


def _render_api_status() -> None:
    """API 연결 상태 패널."""
    st.markdown("**📡 API 연결 상태**")

    import config as _cfg

    try:
        from services.supabase_client import is_connected as _supa_conn
        supa_ok = _supa_conn()
    except Exception:
        supa_ok = False

    items = [
        ("Supabase",  supa_ok,                      "DB 저장"),
        ("DART",      _cfg.is_dart_available(),      "재무 데이터"),
        ("Naver",     _cfg.is_naver_available(),     "뉴스 API"),
        ("키움",      _cfg.is_kiwoom_available(),    "조회 전용"),
    ]

    for name, ok, desc in items:
        dot   = "🟢" if ok else "🔴"
        label = "연결" if ok else "미연결"
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;"
            f"padding:2px 0;font-size:13px'>"
            f"<span>{dot} <b>{name}</b></span>"
            f"<span style='color:#888'>{label} · {desc}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )


def _render_data_status(market_df: pd.DataFrame, scored_df: pd.DataFrame) -> None:
    """데이터 출처·신뢰도·기준일 표시."""
    st.markdown("**📊 데이터 현황**")

    try:
        src   = str(market_df["data_source"].iloc[0]) if "data_source" in market_df.columns else "Mock"
        rdate = str(market_df["ref_date"].iloc[0])    if "ref_date"    in market_df.columns else str(date.today())
        label = "FDR 실제 데이터" if "FinanceDataReader" in src else "Mock 데이터"
        total = len(scored_df)
        keen  = int(scored_df["decision"].isin(["강한 관심", "관심"]).sum())

        # 간단 신뢰도
        from analysis.stock_report import _calc_reliability
        reliability = _calc_reliability(src, "Mock", [{"source": "Mock"}])
        rel_short   = reliability.split(" (")[0] if " (" in reliability else reliability

        st.markdown(
            f"<div style='font-size:12px;line-height:1.9'>"
            f"출처: <b>{label}</b><br>"
            f"기준일: <b>{rdate}</b><br>"
            f"후보 수: <b>{total}개</b> (관심 {keen}개)<br>"
            f"신뢰도: <b>{rel_short}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )
    except Exception:
        st.caption(f"갱신 횟수: {st.session_state['refresh_key']}회")


# ── 업데이트 작업 ────────────────────────────────────────────────

def _do_price_update(scored_df: pd.DataFrame) -> None:
    """종목 일봉 데이터 업데이트 (스캐너 후보 기준)."""
    with st.sidebar:
        with st.spinner("종목 데이터 업데이트 중..."):
            try:
                from services.price_service import update_daily_prices_for_candidates
                candidates = scored_df[["stock_code", "stock_name"]].to_dict("records")
                result = update_daily_prices_for_candidates(candidates)
                msg = (
                    f"success",
                    f"종목 업데이트 완료 ({result['success']}/{result['total']})",
                )
            except Exception as e:
                msg = ("error", f"종목 업데이트 실패: {e}")
    st.session_state["price_update_msg"] = msg
    st.cache_data.clear()
    st.session_state["refresh_key"] += 1
    st.rerun()


def _do_news_update(market_df: pd.DataFrame) -> None:
    """상위 20개 종목 뉴스 업데이트."""
    with st.sidebar:
        with st.spinner("뉴스 업데이트 중..."):
            try:
                top20 = market_df.head(20)
                total_saved = 0
                for _, r in top20.iterrows():
                    items = _fetch_news_from_naver_safe(
                        str(r["stock_name"]),
                        days=7,
                        max_items=10,
                        stock_code=str(r["stock_code"]),
                    )
                    if items:
                        res = _save_news_to_supabase_safe(items)
                        total_saved += res.get("saved", 0)
                msg = ("success", f"뉴스 업데이트 완료 ({total_saved}건 저장)")
            except Exception as e:
                msg = ("error", f"뉴스 업데이트 실패: {e}")
    st.session_state["news_update_msg"] = msg
    st.rerun()


def _do_fin_update(market_df: pd.DataFrame) -> None:
    """상위 10개 종목 재무 데이터 업데이트 (DART)."""
    with st.sidebar:
        with st.spinner("재무 데이터 업데이트 중..."):
            try:
                from services.financial_data import get_financial_metrics, save_financial_metrics_to_supabase
                top10 = market_df.head(10)
                success = 0
                for _, r in top10.iterrows():
                    m = get_financial_metrics(str(r["stock_code"]), str(r.get("stock_name", "")))
                    if m.get("fin_source") == "DART":
                        save_financial_metrics_to_supabase(m)
                        success += 1
                msg = ("success", f"재무 업데이트 완료 ({success}종목 DART 수신)")
            except Exception as e:
                msg = ("error", f"재무 업데이트 실패: {e}")
    st.session_state["fin_update_msg"] = msg
    st.cache_data.clear()
    st.session_state["refresh_key"] += 1
    st.rerun()


def _do_rescan() -> None:
    """후보 재계산 (캐시 초기화 후 리로드)."""
    st.session_state["rescan_msg"] = ("info", "후보 재계산 중... (새로고침)")
    st.cache_data.clear()
    st.session_state["refresh_key"] += 1
    st.rerun()


# ════════════════════════════════════════════════════════════════
# 화면 1 – 오늘의 후보 종목
# ════════════════════════════════════════════════════════════════
def render_candidates(market_df: pd.DataFrame, scored_df: pd.DataFrame) -> None:
    _render_menu_title(
        "📋 오늘의 후보 종목",
        "시장 데이터를 점수화해 오늘 우선 검토할 종목을 찾고, 판단·데이터 품질·리스크를 한눈에 비교합니다.",
    )

    merged = _merge_with_market(scored_df, market_df)

    # ── 상단 요약 카드: 5단계 판단별 개수 ────────────────────
    st.subheader("📊 판단별 분포")
    kc = st.columns(5)
    for col, label in zip(kc, DECISION_ORDER):
        cnt   = int((merged["decision"] == label).sum())
        color = DECISION_COLOR[label]
        col.markdown(
            f"<div style='text-align:center;padding:10px 4px;border-radius:10px;"
            f"border:2px solid {color};background:{color}11'>"
            f"<div style='font-size:11px;color:{color};font-weight:bold'>{label}</div>"
            f"<div style='font-size:26px;font-weight:bold;color:{color}'>{cnt}</div>"
            f"<div style='font-size:11px;color:#888'>종목</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("")

    # 두 번째 행 KPI
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전체 후보 수",       f"{len(merged)}개")
    c2.metric("평균 점수",          f"{merged['score'].mean():.1f}점")
    c3.metric("뉴스 있는 종목 수",  f"{(merged['news_count'] >= 1).sum()}개")
    fin_risk_cnt = sum(_has_fin_risk(market_df[market_df["stock_code"] == r["stock_code"]].iloc[0])
                       for _, r in merged.iterrows()
                       if len(market_df[market_df["stock_code"] == r["stock_code"]]) > 0)
    c4.metric("재무 리스크 종목",   f"{fin_risk_cnt}개")

    st.divider()

    # ── 필터 & 액션 버튼 ─────────────────────────────────────
    fl1, fl2, fl3, fl4 = st.columns([2, 2, 1, 1])

    with fl1:
        decision_opts = st.multiselect(
            "판단 필터",
            DECISION_ORDER,
            default=["강한 관심", "관심", "관찰"],
        )
    with fl2:
        search = st.text_input("종목 검색", placeholder="종목명 또는 코드 입력")
    with fl3:
        only_risk = st.checkbox("재무 리스크만", value=False)
    with fl4:
        if st.button("💾 점수 저장", type="primary", width="stretch"):
            _save_scores(merged)

    if st.session_state["save_done"]:
        st.success("✅ 점수가 저장되었습니다.")
        st.session_state["save_done"] = False

    # ── 필터 적용 ─────────────────────────────────────────────
    view = merged[merged["decision"].isin(decision_opts)] if decision_opts else merged

    if search.strip():
        kw = search.strip()
        view = view[
            view["stock_name"].str.contains(kw, na=False)
            | view["stock_code"].astype(str).str.contains(kw, na=False)
        ]

    if only_risk:
        risk_codes = set()
        for _, r in view.iterrows():
            mrows = market_df[market_df["stock_code"] == r["stock_code"]]
            if len(mrows) > 0 and _has_fin_risk(mrows.iloc[0]):
                risk_codes.add(r["stock_code"])
        view = view[view["stock_code"].isin(risk_codes)]

    # ── 후보 종목 테이블 ──────────────────────────────────────
    st.subheader(f"📋 후보 종목 목록  ({len(view)}개)")

    dq_series = (
        view["data_quality"]
        if "data_quality" in view.columns
        else pd.Series(["Mock"] * len(view), index=view.index)
    )

    table = view[[
        "stock_code", "stock_name", "market", "sector",
        "current_price", "change_rate", "trading_value",
        "score", "decision", "news_count",
    ]].copy()

    table["reasons_str"]  = view["reasons"].apply(lambda x: " / ".join(x) if x else "-")
    table["risks_str"]    = view["risks"].apply(lambda x: " / ".join(x) if x else "-")
    table["data_quality"] = dq_series.values

    table.columns = [
        "종목코드", "종목명", "시장", "섹터",
        "현재가", "등락률(%)", "거래대금(억)",
        "점수", "판단", "뉴스",
        "매수 이유", "리스크", "데이터 품질",
    ]
    styled = (
        table.style
        .format({
            "현재가":     "{:,.0f}원",
            "등락률(%)": "{:+.2f}%",
            "거래대금(억)": "{:,.1f}",
        })
        .map(_style_change_rate, subset=["등락률(%)"])
    )

    _DQ_HELP = "실제 데이터 = 가격·재무·뉴스 모두 실데이터 / 일부 Mock = 일부 실데이터 / Mock = 전체 Mock"
    st.dataframe(
        styled,
        width="stretch",
        height=420,
        column_config={
            "점수":        st.column_config.ProgressColumn("점수", min_value=0, max_value=170, format="%d"),
            "뉴스":        st.column_config.NumberColumn("뉴스", format="%d건"),
            "데이터 품질": st.column_config.TextColumn("데이터 품질", help=_DQ_HELP),
        },
    )

    st.divider()

    # ── 차트 ─────────────────────────────────────────────────
    chart_l, chart_r = st.columns(2)

    with chart_l:
        st.subheader("🏆 점수 상위 10개 종목")
        top10 = merged.nlargest(10, "score")[["stock_name", "score", "decision"]].copy()
        top10 = top10.sort_values("score")
        fig_bar = px.bar(
            top10, x="score", y="stock_name", orientation="h",
            color="decision",
            color_discrete_map=DECISION_COLOR,
            text="score",
            labels={"score": "점수", "stock_name": ""},
        )
        fig_bar.update_traces(textposition="outside")
        fig_bar.update_layout(
            height=380,
            showlegend=False,
            margin=dict(l=0, r=50, t=10, b=0),
            xaxis=dict(range=[0, 180]),
        )
        st.plotly_chart(fig_bar, width="stretch")

    with chart_r:
        st.subheader("🎯 판단별 종목 분포")
        dist = (
            merged["decision"]
            .value_counts()
            .reindex(DECISION_ORDER, fill_value=0)
            .reset_index()
        )
        dist.columns = ["판단", "종목 수"]
        fig_pie = px.pie(
            dist, names="판단", values="종목 수",
            color="판단",
            color_discrete_map=DECISION_COLOR,
            hole=0.45,
        )
        fig_pie.update_traces(textinfo="label+value", textfont_size=13)
        fig_pie.update_layout(
            height=380,
            showlegend=True,
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_pie, width="stretch")

    # ── 데이터 품질 요약 ─────────────────────────────────────
    if "data_quality" in scored_df.columns:
        st.divider()
        st.subheader("📊 데이터 품질 분포")
        dq_counts = scored_df["data_quality"].value_counts().reset_index()
        dq_counts.columns = ["데이터 품질", "종목 수"]
        dq_color_map = {
            "실제 데이터": "#27AE60",
            "일부 Mock":   "#F39C12",
            "Mock":        "#95A5A6",
        }
        fig_dq = px.bar(
            dq_counts, x="데이터 품질", y="종목 수",
            color="데이터 품질",
            color_discrete_map=dq_color_map,
            text="종목 수",
        )
        fig_dq.update_traces(textposition="outside")
        fig_dq.update_layout(
            height=250,
            showlegend=False,
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_dq, width="stretch")


def _save_scores(merged: pd.DataFrame) -> None:
    from services.db_service import save_candidate_scores
    today = str(date.today())
    for _, row in merged.iterrows():
        save_candidate_scores({
            "stock_code": row["stock_code"],
            "stock_name": row["stock_name"],
            "score":      float(row["score"]),
            "decision":   row["decision"],
            "reasons":    " / ".join(row["reasons"]) if row["reasons"] else "",
            "risks":      " / ".join(row["risks"])   if row["risks"]   else "",
            "trade_date": today,
        })
    st.session_state["save_done"] = True
    st.rerun()


# ════════════════════════════════════════════════════════════════
# 화면 2 – 종목 상세 리포트
# ════════════════════════════════════════════════════════════════
def render_report(market_df: pd.DataFrame, scored_df: pd.DataFrame) -> None:
    _render_menu_title(
        "🔍 종목 상세 리포트",
        "특정 종목의 가격 흐름, 기술 점수, 재무, 뉴스 감성, 종합 판단을 상세히 검토합니다.",
    )

    merged = _merge_with_market(scored_df, market_df).sort_values("score", ascending=False)
    stock_names = merged["stock_name"].tolist()

    sel_col, info_col = st.columns([2, 3])
    with sel_col:
        selected = st.selectbox(
            "분석할 종목 선택",
            stock_names,
            help="스캐너 점수 높은 순 정렬",
        )

    row  = merged[merged["stock_name"] == selected].iloc[0]
    mrow = market_df[market_df["stock_name"] == selected].iloc[0]
    code = str(row["stock_code"])

    with info_col:
        color     = DECISION_COLOR.get(row["decision"], "#888")
        chg_badge = _change_rate_badge(float(row["change_rate"]))
        dq        = str(row.get("data_quality", "Mock")) if "data_quality" in row.index else "Mock"
        dq_color  = _DQ_COLOR.get(dq, "#888")
        st.markdown(
            f"<div style='margin-top:4px;padding:10px 14px;border-radius:10px;border:1px solid #ddd'>"
            f"<b style='font-size:17px'>{row['stock_name']}</b> "
            f"<span style='color:#999;font-size:12px'>{code} | {row['market']} | {row['sector']}</span><br>"
            f"<span style='font-size:22px;font-weight:bold'>{row['current_price']:,}원</span> "
            f"{chg_badge}"
            f"&nbsp;&nbsp;<span style='background:{color};color:#fff;padding:2px 12px;"
            f"border-radius:6px;font-size:13px;font-weight:bold'>{row['decision']} {row['score']}점</span>"
            f"&nbsp;<span style='background:{dq_color}22;border:1px solid {dq_color};"
            f"color:{dq_color};padding:1px 8px;border-radius:4px;font-size:11px'>{dq}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    tab_gen, tab_hist = st.tabs(["📊 리포트 생성", "📂 과거 리포트"])

    with tab_gen:
        _render_report_generator(mrow, row, code)
    with tab_hist:
        _render_report_history(code, selected)


def _render_report_generator(mrow: pd.Series, row: pd.Series, code: str) -> None:
    """리포트 생성 탭 — 일봉차트·기술·재무·뉴스 미리보기 + 생성 버튼 + 결과 표시."""
    from services.db_service import save_stock_report

    key = st.session_state["refresh_key"]
    name = str(mrow.get("stock_name", ""))

    # 데이터 로드
    news_items   = _get_news_for_stock_safe(stock_code=code, stock_name=name)
    price_history = _load_price_history(code, key)
    fin_metrics   = _load_fin_metrics(code, name, key)
    fin_years     = fin_metrics.get("years", [])
    fin_source    = fin_metrics.get("fin_source", "Mock")

    # 뉴스 감성 집계
    pos   = sum(1 for n in news_items if n.get("sentiment") == "긍정")
    neu   = sum(1 for n in news_items if n.get("sentiment") == "중립")
    neg   = sum(1 for n in news_items if n.get("sentiment") == "부정")
    total = len(news_items)

    # ── 섹션 1: 일봉 차트 ─────────────────────────────────────
    st.subheader("📈 일봉 차트")
    _render_price_chart(price_history, name)

    st.divider()

    # ── 섹션 2: 기술적 점수 / 재무 요약 ──────────────────────
    col_tech, col_fin = st.columns(2)

    with col_tech:
        st.subheader("📐 기술적 점수")
        t1, t2, t3 = st.columns(3)
        t1.metric("MA5",  f"{int(mrow['ma5']):,}원")
        t2.metric("MA20", f"{int(mrow['ma20']):,}원")
        t3.metric("MA60", f"{int(mrow['ma60']):,}원")

        signals = {
            "이동평균 정배열 (MA5 > MA20)": mrow["close"] > mrow["ma5"] > mrow["ma20"],
            "종가 MA5 위":                  mrow["close"] > mrow["ma5"],
            "종가 MA20 위":                 mrow["close"] > mrow["ma20"],
            "양봉 마감 (종가 ≥ 시가)":      mrow["close"] >= mrow["open"],
        }
        for label, ok in signals.items():
            (st.success if ok else st.error)(("✅ " if ok else "❌ ") + label)

        vol_ratio = round(mrow["volume"] / max(mrow["avg_volume_20d"], 1), 2)
        surge     = vol_ratio >= 2.0
        (st.success if surge else st.info)(
            f"{'✅' if surge else 'ℹ️'} 거래량 비율: {vol_ratio:.2f}배 (평균 대비)"
        )

    with col_fin:
        st.subheader("💰 재무 요약")
        f1, f2 = st.columns(2)
        f1.metric("PER",  f"{mrow['per']:.1f}배")
        f2.metric("PBR",  f"{mrow['pbr']:.2f}배")
        f3, f4 = st.columns(2)
        f3.metric("ROE",  f"{mrow['roe']:.1f}%")
        f4.metric("부채비율", f"{mrow['debt_ratio']:.0f}%")

        # 재무 출처 배지
        fsrc_color = {"DART": "#27AE60", "CSV": "#F39C12"}.get(fin_source, "#95A5A6")
        fsrc_icon  = {"DART": "📡", "CSV": "📂"}.get(fin_source, "🎲")
        st.markdown(
            f"재무 출처: <span style='background:{fsrc_color}22;border:1px solid {fsrc_color};"
            f"color:{fsrc_color};padding:1px 8px;border-radius:4px;font-size:12px'>"
            f"{fsrc_icon} {fin_source}</span>",
            unsafe_allow_html=True,
        )

        fin_risks = []
        if mrow["per"]         < 0:   fin_risks.append(f"PER {mrow['per']:.1f}배 — 적자")
        if mrow["roe"]         < 0:   fin_risks.append(f"ROE {mrow['roe']:.1f}% — 적자")
        if mrow["debt_ratio"] >= 200: fin_risks.append(f"부채비율 {mrow['debt_ratio']:.0f}% — 200% 초과")
        if mrow["per"]         > 50:  fin_risks.append(f"PER {mrow['per']:.1f}배 — 고평가")
        if fin_risks:
            for fr in fin_risks:
                st.error(f"⚠️ {fr}")
        else:
            st.success("✅ 주요 재무 지표 정상 범위")

        with st.expander("재무 레이더 차트 보기"):
            cats = ["PER 경쟁력", "PBR 경쟁력", "ROE", "부채 안전성", "거래 활성도"]
            vals = [
                max(0, 100 - mrow["per"] * 2),
                max(0, 100 - mrow["pbr"] * 20),
                min(100, max(0, mrow["roe"] * 4)),
                max(0, 100 - mrow["debt_ratio"] * 0.5),
                min(100, mrow["trading_value"] / 2),
            ]
            dc = DECISION_COLOR.get(row["decision"], "#888")
            fig_r = go.Figure(go.Scatterpolar(
                r=vals + [vals[0]],
                theta=cats + [cats[0]],
                fill="toself",
                fillcolor="rgba(39,174,96,0.12)",
                line=dict(color=dc),
            ))
            fig_r.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=False, height=280,
                margin=dict(l=30, r=30, t=10, b=10),
            )
            st.plotly_chart(fig_r, width="stretch")

    st.divider()

    # ── 섹션 3: 재무 3년 추이 ────────────────────────────────
    _render_financial_trend(fin_years, fin_source)

    st.divider()

    # ── 섹션 4: 뉴스 감성 요약 ──────────────────────────────
    st.subheader("📰 뉴스 감성 요약")

    # 뉴스 출처 배지
    news_sources = {n.get("source", "Mock") for n in news_items}
    if news_sources == {"Naver"}:
        st.success("📡 실제 데이터 (네이버 뉴스 API)", icon="✅")
    elif "Naver" in news_sources:
        st.info("📡 혼합 (네이버 + Mock)", icon="ℹ️")
    else:
        st.warning("🎲 Mock 데이터 — NAVER_CLIENT_ID·SECRET 설정 시 실제 뉴스", icon="⚠️")

    nc1, nc2, nc3, nc4 = st.columns(4)
    nc1.metric("전체 뉴스", f"{total}건")
    nc2.metric("📈 긍정",   f"{pos}건")
    nc3.metric("📊 중립",   f"{neu}건")
    nc4.metric("📉 부정",   f"{neg}건")

    for item in sorted(news_items, key=lambda x: x.get("news_date", ""), reverse=True)[:3]:
        sent  = item.get("sentiment", "중립")
        color = _SENT_COLOR.get(sent, "#888")
        icon  = _SENT_ICON.get(sent, "📊")
        stars = "★" * item.get("impact_score", 3) + "☆" * (5 - item.get("impact_score", 3))
        src   = item.get("source", "Mock")
        src_color = {"Naver": "#2980B9"}.get(src, "#95A5A6")
        st.markdown(
            f"<div style='padding:8px 12px;margin:4px 0;"
            f"border-left:4px solid {color};background:#fafafa;border-radius:0 6px 6px 0'>"
            f"{icon} <b>{item['title']}</b> "
            f"<span style='color:#F39C12;font-size:11px'>{stars}</span>"
            f"<span style='float:right;color:{src_color};font-size:11px'>{src}</span><br>"
            f"<span style='color:#aaa;font-size:12px'>{item.get('news_date','')}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── 섹션 5: 리포트 생성 버튼 ────────────────────────────
    report_key = f"report_{code}"
    btn_col, _ = st.columns([2, 5])
    with btn_col:
        gen_clicked = st.button(
            "📋 리포트 생성 및 저장",
            type="primary",
            width="stretch",
            key=f"gen_btn_{code}",
        )

    if gen_clicked:
        from analysis.stock_report import generate_report
        with st.spinner("리포트 분석 중..."):
            report = generate_report(
                mrow, row, news_items,
                fin_source=fin_source,
                financial_years=fin_years,
                price_history=price_history if not price_history.empty else None,
            )
            st.session_state[report_key] = report

            j = report["최종_판단"]
            save_stock_report({
                "stock_code":        code,
                "stock_name":        str(row["stock_name"]),
                "report_date":       str(date.today()),
                "technical_summary": (
                    f"점수 {int(row['score'])}점 / "
                    f"MA5 {int(mrow['ma5']):,}원 / MA20 {int(mrow['ma20']):,}원 / "
                    f"거래량비율 {vol_ratio:.2f}배"
                ),
                "financial_summary": (
                    f"PER {mrow['per']:.1f}배 / PBR {mrow['pbr']:.2f}배 / "
                    f"ROE {mrow['roe']:.1f}% / 부채비율 {mrow['debt_ratio']:.0f}%"
                ),
                "news_summary":   f"긍정 {pos}건 / 중립 {neu}건 / 부정 {neg}건 (총 {total}건)",
                "final_decision": j["판정"],
                "target_return":  j["목표_수익률"],
                "stop_loss":      j["손절_라인"],
                "entry_timing":   j["진입_타이밍"],
                "risks":          " / ".join(j["리스크"]),
                "conclusion":     report["한_줄_결론"],
                "raw_json":       json.dumps(report, ensure_ascii=False),
            })
        st.success("✅ 리포트가 생성되어 저장되었습니다.")

    if report_key in st.session_state:
        _display_final_report(st.session_state[report_key])


# ── 일봉 차트 ─────────────────────────────────────────────────

def _build_chart_trade_signals(df: pd.DataFrame) -> list[dict]:
    """chart-skill 기준 일봉 단기 스윙 보조 신호를 생성한다."""
    if df is None or df.empty or "close" not in df.columns:
        return []

    work = df.copy().reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    close = work["close"]
    open_ = work["open"] if "open" in work.columns else close
    high = work["high"] if "high" in work.columns else close
    low = work["low"] if "low" in work.columns else close
    volume = work["volume"] if "volume" in work.columns else pd.Series([0] * len(work))

    ma5 = pd.to_numeric(work.get("ma5", close.rolling(5).mean()), errors="coerce")
    ma20 = pd.to_numeric(work.get("ma20", close.rolling(20).mean()), errors="coerce")
    ma60 = pd.to_numeric(work.get("ma60", close.rolling(60).mean()), errors="coerce")
    rsi = pd.to_numeric(work.get("rsi14", pd.Series([50] * len(work))), errors="coerce").fillna(50)
    vol_avg20 = volume.rolling(20, min_periods=5).mean().replace(0, pd.NA)
    prev_high20 = high.rolling(20, min_periods=10).max().shift(1)
    prev_low20 = low.rolling(20, min_periods=10).min().shift(1)

    signals: list[dict] = []
    last_signal_idx: dict[str, int] = {"buy": -99, "sell": -99}

    for i in range(1, len(work)):
        if pd.isna(close.iloc[i]) or pd.isna(ma20.iloc[i]):
            continue

        vol_ratio = 1.0
        if i < len(vol_avg20) and pd.notna(vol_avg20.iloc[i]) and vol_avg20.iloc[i] > 0:
            vol_ratio = float(volume.iloc[i] / vol_avg20.iloc[i])

        buy_reasons: list[str] = []
        sell_reasons: list[str] = []

        crossed_ma20_up = close.iloc[i - 1] <= ma20.iloc[i - 1] and close.iloc[i] > ma20.iloc[i]
        crossed_ma20_down = close.iloc[i - 1] >= ma20.iloc[i - 1] and close.iloc[i] < ma20.iloc[i]
        ma5_turn_up = pd.notna(ma5.iloc[i - 1]) and ma5.iloc[i] > ma5.iloc[i - 1]
        ma5_turn_down = pd.notna(ma5.iloc[i - 1]) and ma5.iloc[i] < ma5.iloc[i - 1]

        if crossed_ma20_up and rsi.iloc[i] >= 45:
            buy_reasons.append("MA20 상향 돌파")
        if low.iloc[i] <= ma20.iloc[i] * 1.01 and close.iloc[i] > ma20.iloc[i] and close.iloc[i] > open_.iloc[i]:
            buy_reasons.append("MA20 지지 반등")
        if pd.notna(prev_high20.iloc[i]) and close.iloc[i] > prev_high20.iloc[i] and vol_ratio >= 1.5 and rsi.iloc[i] < 75:
            buy_reasons.append("20일 고점 돌파 + 거래량")
        if rsi.iloc[i - 1] < 50 <= rsi.iloc[i] and ma5_turn_up:
            buy_reasons.append("RSI 50 회복 + MA5 상승")
        if vol_ratio >= 1.5 and close.iloc[i] > open_.iloc[i] and close.iloc[i] > ma5.iloc[i]:
            buy_reasons.append("양봉 거래량 증가")

        upper_wick = high.iloc[i] - max(open_.iloc[i], close.iloc[i])
        candle_range = max(high.iloc[i] - low.iloc[i], 1)
        upper_wick_ratio = upper_wick / candle_range

        if crossed_ma20_down and vol_ratio >= 1.1:
            sell_reasons.append("MA20 하향 이탈")
        if close.iloc[i] < ma5.iloc[i] and ma5_turn_down and rsi.iloc[i] < 50:
            sell_reasons.append("MA5 하락 전환 + RSI 50 이탈")
        if rsi.iloc[i] >= 75 and upper_wick_ratio >= 0.35 and vol_ratio >= 1.3:
            sell_reasons.append("과열권 윗꼬리")
        if pd.notna(prev_low20.iloc[i]) and close.iloc[i] < prev_low20.iloc[i] and vol_ratio >= 1.2:
            sell_reasons.append("20일 저점 이탈")
        if pd.notna(ma60.iloc[i]) and close.iloc[i] < ma60.iloc[i] and ma20.iloc[i] < ma20.iloc[i - 1]:
            sell_reasons.append("중기 추세 훼손")

        if len(buy_reasons) >= 2 and (i - last_signal_idx["buy"]) >= 3:
            strength = "strong" if len(buy_reasons) >= 3 and vol_ratio >= 1.5 else "normal"
            signals.append({
                "index": i,
                "date": str(work["date"].iloc[i]) if "date" in work.columns else str(i),
                "signal_type": "buy",
                "price": float(close.iloc[i]),
                "marker_y": float(low.iloc[i] * 0.985),
                "strength": strength,
                "reason": " + ".join(buy_reasons[:3]),
                "marker_color": "#E74C3C",
            })
            last_signal_idx["buy"] = i

        if sell_reasons and (i - last_signal_idx["sell"]) >= 3:
            strength = "strong" if len(sell_reasons) >= 2 and vol_ratio >= 1.3 else "normal"
            signals.append({
                "index": i,
                "date": str(work["date"].iloc[i]) if "date" in work.columns else str(i),
                "signal_type": "sell",
                "price": float(close.iloc[i]),
                "marker_y": float(high.iloc[i] * 1.015),
                "strength": strength,
                "reason": " + ".join(sell_reasons[:3]),
                "marker_color": "#2980B9",
            })
            last_signal_idx["sell"] = i

    return signals


def _render_price_chart(price_history: pd.DataFrame, name: str) -> None:
    """일봉 차트 (캔들스틱 or 라인) + MA5/MA20/MA60 + RSI 서브차트."""
    if price_history is None or price_history.empty:
        st.info(
            "💡 일봉 데이터가 없습니다. "
            "사이드바 [📈 종목 데이터] 버튼을 눌러 업데이트하세요.",
            icon="ℹ️",
        )
        return

    df = price_history.copy()
    df.columns = [c.lower() for c in df.columns]
    if "date" in df.columns:
        df["_chart_date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values("_chart_date").reset_index(drop=True)

    unit_col, period_col = st.columns([1, 3])
    with unit_col:
        chart_unit = st.selectbox(
            "차트 단위",
            ["일별", "시간별(준비중)"],
            index=0,
            key=f"price_chart_unit_{name}",
        )
    with period_col:
        chart_period = st.radio(
            "조회 기간",
            ["5일", "20일", "60일", "120일", "1년"],
            index=2,
            horizontal=True,
            key=f"price_chart_period_{name}",
        )

    if chart_unit.startswith("시간별"):
        st.warning(
            "시간별 차트는 분봉/시간봉 데이터 연동 후 활성화됩니다. 현재는 일봉 기준으로 표시합니다.",
            icon="ℹ️",
        )

    original_len = len(df)
    period_days = {"5일": 5, "20일": 20, "60일": 60, "120일": 120}
    if chart_period == "1년":
        if "_chart_date" in df.columns and df["_chart_date"].notna().any():
            latest_date = df["_chart_date"].max()
            cutoff_date = latest_date - pd.DateOffset(years=1)
            df = df[df["_chart_date"] >= cutoff_date].copy()
        else:
            df = df.tail(252).copy()
    else:
        df = df.tail(period_days[chart_period]).copy()

    if df.empty:
        st.info("선택한 기간에 표시할 일봉 데이터가 없습니다.", icon="ℹ️")
        return

    st.caption(
        f"표시 기준: 일봉 · {chart_period} · {len(df)}개 봉"
        + (f" / 전체 로드 {original_len}개" if original_len != len(df) else "")
    )

    has_ohlc = all(c in df.columns for c in ["open", "high", "low", "close"])
    has_ma   = all(c in df.columns for c in ["ma5", "ma20", "ma60"])
    has_rsi  = "rsi14" in df.columns
    has_vol  = "volume" in df.columns

    date_col = "date" if "date" in df.columns else df.index
    chart_signals = _build_chart_trade_signals(df)

    # ── 가격 차트 ─────────────────────────────────────────────
    rows = 3 if has_vol else 2
    row_heights = [0.55, 0.15, 0.30] if has_vol else [0.65, 0.35]

    fig = go.Figure()
    from plotly.subplots import make_subplots
    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        row_heights=row_heights,
        vertical_spacing=0.03,
    )

    # 캔들스틱 또는 종가 라인
    if has_ohlc:
        fig.add_trace(go.Candlestick(
            x=df[date_col] if isinstance(date_col, str) else date_col,
            open=df["open"], high=df["high"],
            low=df["low"],  close=df["close"],
            name="주가",
            increasing_line_color="#E74C3C",
            decreasing_line_color="#2980B9",
        ), row=1, col=1)
    else:
        fig.add_trace(go.Scatter(
            x=df[date_col] if isinstance(date_col, str) else date_col,
            y=df["close"],
            name="종가",
            line=dict(color="#555", width=1.5),
        ), row=1, col=1)

    # MA 라인
    ma_styles = [("ma5", "#F39C12", 1.2), ("ma20", "#27AE60", 1.8), ("ma60", "#8E44AD", 2.0)]
    if has_ma:
        for col, color, width in ma_styles:
            if col in df.columns:
                fig.add_trace(go.Scatter(
                    x=df[date_col] if isinstance(date_col, str) else date_col,
                    y=df[col],
                    name=col.upper(),
                    line=dict(color=color, width=width),
                    opacity=0.85,
                ), row=1, col=1)

    buy_signals = [s for s in chart_signals if s["signal_type"] == "buy"]
    sell_signals = [s for s in chart_signals if s["signal_type"] == "sell"]

    if buy_signals:
        fig.add_trace(go.Scatter(
            x=[s["date"] for s in buy_signals],
            y=[s["marker_y"] for s in buy_signals],
            mode="markers",
            name="단타 매수",
            marker=dict(
                symbol="triangle-up",
                size=13,
                color="#E74C3C",
                line=dict(color="white", width=1),
            ),
            customdata=[[s["strength"], s["reason"], f"{s['price']:,.0f}"] for s in buy_signals],
            hovertemplate=(
                "<b>매수 신호</b><br>"
                "가격: %{customdata[2]}원<br>"
                "강도: %{customdata[0]}<br>"
                "근거: %{customdata[1]}<extra></extra>"
            ),
        ), row=1, col=1)

    if sell_signals:
        fig.add_trace(go.Scatter(
            x=[s["date"] for s in sell_signals],
            y=[s["marker_y"] for s in sell_signals],
            mode="markers",
            name="단타 매도",
            marker=dict(
                symbol="triangle-down",
                size=13,
                color="#2980B9",
                line=dict(color="white", width=1),
            ),
            customdata=[[s["strength"], s["reason"], f"{s['price']:,.0f}"] for s in sell_signals],
            hovertemplate=(
                "<b>매도 신호</b><br>"
                "가격: %{customdata[2]}원<br>"
                "강도: %{customdata[0]}<br>"
                "근거: %{customdata[1]}<extra></extra>"
            ),
        ), row=1, col=1)

    # 거래량
    if has_vol:
        vol_colors = [
            "#E74C3C" if (i > 0 and df["close"].iloc[i] >= df["close"].iloc[i - 1]) else "#2980B9"
            for i in range(len(df))
        ]
        fig.add_trace(go.Bar(
            x=df[date_col] if isinstance(date_col, str) else date_col,
            y=df["volume"],
            name="거래량",
            marker_color=vol_colors,
            opacity=0.6,
        ), row=2, col=1)

    # RSI
    if has_rsi:
        rsi_row = 3 if has_vol else 2
        x_data = df[date_col] if isinstance(date_col, str) else date_col
        fig.add_trace(go.Scatter(
            x=x_data, y=df["rsi14"],
            name="RSI(14)",
            line=dict(color="#8E44AD", width=1.5),
        ), row=rsi_row, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#E74C3C",
                      annotation_text="과매수(70)", annotation_position="right",
                      row=rsi_row, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#2980B9",
                      annotation_text="과매도(30)", annotation_position="right",
                      row=rsi_row, col=1)

    fig.update_layout(
        title=dict(text=f"{name} — 일봉 (최근 {len(df)}일)", font=dict(size=14)),
        height=500 if rows == 3 else 420,
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(orientation="h", y=1.02, x=0),
        margin=dict(l=0, r=0, t=40, b=0),
    )
    # RSI Y축 범위
    if has_rsi:
        rsi_row = 3 if has_vol else 2
        fig.update_yaxes(range=[0, 100], row=rsi_row, col=1)

    st.plotly_chart(fig, width="stretch")

    # 현황 요약
    latest = df.iloc[-1]
    rsi_val = round(float(latest.get("rsi14", 50)), 1) if has_rsi else None
    ma5_v   = int(latest.get("ma5",  latest["close"])) if has_ma else None
    ma20_v  = int(latest.get("ma20", latest["close"])) if has_ma else None
    ma60_v  = int(latest.get("ma60", latest["close"])) if has_ma else None

    ic1, ic2, ic3, ic4, ic5 = st.columns(5)
    ic1.metric("현재가",    f"{int(latest['close']):,}원")
    ic2.metric("MA5",      f"{ma5_v:,}원"  if ma5_v  else "—")
    ic3.metric("MA20",     f"{ma20_v:,}원" if ma20_v else "—")
    ic4.metric("MA60",     f"{ma60_v:,}원" if ma60_v else "—")
    ic5.metric("RSI(14)",  f"{rsi_val}"   if rsi_val else "—")

    st.caption("단타 신호는 chart-skill 기준의 일봉 단기 스윙 보조 신호입니다. 실제 주문과 연결되지 않습니다.")
    recent_signals = sorted(chart_signals, key=lambda x: x["index"], reverse=True)[:5]
    if recent_signals:
        with st.expander("최근 단타 신호 근거", expanded=False):
            for sig in recent_signals:
                label = "매수" if sig["signal_type"] == "buy" else "매도"
                color = sig["marker_color"]
                st.markdown(
                    f"<div style='border-left:4px solid {color};padding:6px 10px;margin:4px 0;background:{color}10'>"
                    f"<b style='color:{color}'>{sig['date']} · {label} · {sig['strength']}</b><br>"
                    f"<span style='font-size:13px'>가격 {sig['price']:,.0f}원 · {sig['reason']}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
    else:
        st.info("선택한 기간에는 단타 매수·매도 보조 신호가 없습니다.", icon="ℹ️")


# ── 재무 3년 추이 테이블 ─────────────────────────────────────────

def _render_financial_trend(fin_years: list[dict], fin_source: str) -> None:
    """재무 3년 추이 섹션."""
    fsrc_color = {"DART": "#27AE60", "CSV": "#F39C12"}.get(fin_source, "#95A5A6")
    fsrc_icon  = {"DART": "📡", "CSV": "📂"}.get(fin_source, "🎲")

    st.subheader("📊 재무 3년 추이")
    st.markdown(
        f"출처: <span style='background:{fsrc_color}22;border:1px solid {fsrc_color};"
        f"color:{fsrc_color};padding:1px 8px;border-radius:4px;font-size:12px'>"
        f"{fsrc_icon} {fin_source}</span>",
        unsafe_allow_html=True,
    )

    if not fin_years:
        st.info("재무 데이터가 없습니다. 사이드바 [💰 재무 데이터] 버튼을 눌러 업데이트하세요.")
        return

    rows = []
    for yr in fin_years[:3]:
        rows.append({
            "연도":       yr.get("fiscal_year", ""),
            "매출액(억)": f"{yr.get('revenue', 0):,.0f}",
            "영업이익(억)": f"{yr.get('operating_profit', 0):,.0f}",
            "영업이익률":  f"{yr.get('operating_margin', 0):.1f}%",
            "순이익(억)":  f"{yr.get('net_profit', 0):,.0f}",
            "ROE":         f"{yr.get('roe', 0):.1f}%",
            "부채비율":    f"{yr.get('debt_ratio', 0):.0f}%",
            "유동비율":    f"{yr.get('current_ratio', 0):.0f}%",
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    # 영업이익률 추이 미니 차트
    if len(fin_years) >= 2:
        with st.expander("영업이익률 추이 차트 보기"):
            years   = [y.get("fiscal_year", "") for y in reversed(fin_years[:3])]
            op_marg = [float(y.get("operating_margin", 0)) for y in reversed(fin_years[:3])]
            roe_vals = [float(y.get("roe", 0)) for y in reversed(fin_years[:3])]

            fig_trend = go.Figure()
            fig_trend.add_trace(go.Bar(
                x=years, y=op_marg, name="영업이익률(%)",
                marker_color="#27AE60", opacity=0.7,
            ))
            fig_trend.add_trace(go.Scatter(
                x=years, y=roe_vals, name="ROE(%)",
                mode="lines+markers",
                line=dict(color="#E74C3C", width=2),
            ))
            fig_trend.update_layout(
                height=220, showlegend=True,
                margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h"),
            )
            st.plotly_chart(fig_trend, width="stretch")


# ── 리포트 결과 표시 ─────────────────────────────────────────────

def _display_final_report(report: dict) -> None:
    """generate_report() 결과를 Streamlit으로 시각화 (v2)."""
    j      = report["최종_판단"]
    dr     = report.get("데이터_신뢰도", {})
    meta   = report["메타"]
    verdict = j["판정"]
    vcolor  = _VERDICT_COLOR.get(verdict, "#888")

    st.divider()
    st.subheader("📋 종합 리포트 결과")

    # 판단 보류 경고
    if j.get("판단_보류_이유"):
        st.warning(
            f"⚠️ **판단 보류**: {j['판단_보류_이유']}",
            icon="⚠️",
        )

    # 최종 판정 배너
    st.markdown(
        f"<div style='text-align:center;padding:22px;border-radius:12px;"
        f"border:3px solid {vcolor};margin:8px 0 16px'>"
        f"<div style='font-size:13px;color:#888;margin-bottom:6px'>최종 투자 판단</div>"
        f"<div style='font-size:40px;font-weight:bold;color:{vcolor}'>{verdict}</div>"
        f"<div style='font-size:14px;color:#555;margin-top:10px;line-height:1.6'>"
        f"{report['한_줄_결론']}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # 주요 지표
    m1, m2, m3 = st.columns(3)
    m1.metric("🎯 목표 수익률", j["목표_수익률"])
    m2.metric("🛑 손절 라인",   j["손절_라인"])
    m3.metric("⏰ 진입 타이밍", j["진입_타이밍"])

    st.markdown("")

    # 핵심 근거 & 리스크
    g_col, r_col = st.columns(2)
    with g_col:
        st.subheader("✅ 핵심 근거")
        for i, g in enumerate(j["핵심_근거"], 1):
            st.success(f"{i}. {g}")
    with r_col:
        st.subheader("⚠️ 주요 리스크")
        for i, r in enumerate(j["리스크"], 1):
            st.warning(f"{i}. {r}")

    # 핵심 리스크 상세 (스캐너 전체)
    hr = report.get("핵심_리스크", {})
    scanner_risks = [x for x in hr.get("스캐너_리스크", []) if x]
    if scanner_risks:
        with st.expander("📋 스캐너 전체 리스크 보기"):
            for r in scanner_risks:
                st.markdown(f"- {r}")

    st.divider()

    # 데이터 신뢰도 섹션
    st.subheader("📡 데이터 신뢰도")

    if dr:
        grade_val = str(dr.get("종합_등급", "알 수 없음"))
        grade_color = (
            "#27AE60" if "높음" in grade_val
            else "#F39C12" if "보통" in grade_val
            else "#E74C3C"
        )
        st.markdown(
            f"<div style='padding:10px 14px;border-radius:8px;"
            f"border:2px solid {grade_color};background:{grade_color}11;margin-bottom:10px'>"
            f"<b style='color:{grade_color}'>종합 신뢰도: {grade_val}</b></div>",
            unsafe_allow_html=True,
        )

        dc1, dc2, dc3 = st.columns(3)
        items = [
            ("📈 가격 데이터", dr.get("가격_데이터", {}), dc1),
            ("💰 재무 데이터", dr.get("재무_데이터", {}), dc2),
            ("📰 뉴스 데이터", dr.get("뉴스_데이터", {}), dc3),
        ]
        for label, info, col in items:
            src   = info.get("출처", "—")
            grade = info.get("등급", "C")
            gc    = _GRADE_COLOR.get(grade, "#888")
            col.markdown(
                f"<div style='padding:8px;border-radius:6px;border:1px solid {gc};text-align:center'>"
                f"<div style='font-size:11px;color:#888'>{label}</div>"
                f"<div style='font-size:13px;margin:2px 0'>{src}</div>"
                f"<span style='background:{gc};color:#fff;padding:1px 8px;"
                f"border-radius:4px;font-size:12px;font-weight:bold'>등급 {grade}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("")
        validity = dr.get("판단_유효성", "—")
        val_color = "#27AE60" if "정상" in validity else "#E67E22"
        st.markdown(
            f"판단 유효성: <span style='color:{val_color};font-weight:bold'>{validity}</span>",
            unsafe_allow_html=True,
        )

        # 일봉 데이터 현황
        od = dr.get("일봉_데이터", {})
        if od:
            st.caption(f"일봉: {od.get('출처','—')}  ({od.get('일봉수', 0)}일치 확보)")

    st.markdown("")
    st.caption(
        f"🗓 생성일: {meta['생성일']}  |  기준일: {meta['기준일']}  |  "
        f"신뢰도: {meta['데이터_신뢰도']}"
    )
    st.info(f"⚠️ {meta['주의사항']}", icon="ℹ️")


def _render_report_history(code: str, name: str) -> None:
    """과거 리포트 탭 — 저장된 리포트 목록 표시."""
    from services.db_service import get_stock_reports

    st.subheader(f"📂 {name} 저장된 리포트")
    reports = get_stock_reports(stock_code=code)

    if not reports:
        st.info("💡 저장된 리포트가 없습니다. '리포트 생성' 탭에서 생성하세요.")
        return

    for i, r in enumerate(reports):
        verdict = r.get("final_decision", "-")
        vcolor  = _VERDICT_COLOR.get(verdict, "#888")
        concl   = r.get("conclusion", "")
        preview = concl[:50] + "…" if len(concl) > 50 else concl

        with st.expander(
            f"[{r.get('report_date', '-')}]  {verdict}  —  {preview}",
            expanded=(i == 0),
        ):
            rc1, rc2 = st.columns(2)
            with rc1:
                st.markdown(
                    f"**최종 판단** &nbsp;"
                    f"<span style='background:{vcolor};color:#fff;padding:2px 10px;"
                    f"border-radius:5px;font-weight:bold'>{verdict}</span>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"**목표 수익률**: {r.get('target_return', '-')}")
                st.markdown(f"**손절 라인**: {r.get('stop_loss', '-')}")
                st.markdown(f"**진입 타이밍**: {r.get('entry_timing', '-')}")
            with rc2:
                st.markdown(f"**기술 요약**: {r.get('technical_summary', '-')}")
                st.markdown(f"**재무 요약**: {r.get('financial_summary', '-')}")
                st.markdown(f"**뉴스 요약**: {r.get('news_summary', '-')}")
            if r.get("risks"):
                st.markdown(f"**리스크**: {r['risks']}")
            st.divider()
            st.info(f"💡 결론: {r.get('conclusion', '-')}")
            raw = r.get("raw_json")
            if raw:
                with st.expander("🔍 전체 JSON 보기"):
                    try:
                        st.json(json.loads(raw) if isinstance(raw, str) else raw)
                    except Exception:
                        st.code(str(raw))


# ════════════════════════════════════════════════════════════════
# 화면 3 – 뉴스/이슈
# ════════════════════════════════════════════════════════════════
def render_news(market_df: pd.DataFrame) -> None:
    _render_menu_title(
        "📰 뉴스/이슈",
        "관심 종목 관련 뉴스와 감성 분류를 확인해 단기 이슈와 리스크를 빠르게 파악합니다.",
    )

    from services.news_data import get_mock_news

    f1, f2, f3 = st.columns([2, 2, 1])
    stock_names = ["전체"] + market_df["stock_name"].tolist()
    with f1:
        sel_stock = st.selectbox("종목 선택", stock_names, key="news_stock")
    with f2:
        sel_sent = st.multiselect(
            "감성 필터",
            ["긍정", "중립", "부정"],
            default=["긍정", "중립", "부정"],
            key="news_sent",
        )
    with f3:
        sel_impact = st.slider("최소 영향도", 1, 5, 1, key="news_impact")

    if sel_stock == "전체":
        all_news = get_mock_news()
    else:
        code = market_df[market_df["stock_name"] == sel_stock]["stock_code"].values[0]
        all_news = _get_news_for_stock_safe(stock_code=str(code), stock_name=sel_stock)

    _news_sources = {item.get("source", "Mock") for item in all_news}
    if _news_sources == {"Naver"}:
        st.success("📡 실제 데이터 (네이버 뉴스 API)", icon="✅")
    elif "Naver" in _news_sources:
        st.info("📡 혼합 데이터 (네이버 + Mock)", icon="ℹ️")
    else:
        st.warning("🎲 Mock 데이터 — NAVER_CLIENT_ID·SECRET 설정 시 실제 뉴스로 전환됩니다.", icon="⚠️")

    filtered = [
        n for n in all_news
        if n["sentiment"] in (sel_sent or ["긍정", "중립", "부정"])
        and n["impact_score"] >= sel_impact
    ]

    st.divider()
    summary = _summarize_news_safe(all_news)
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("전체 뉴스", f"{summary['합계']}건")
    for col, sent in zip([s2, s3, s4], ["긍정", "중립", "부정"]):
        cnt   = summary[sent]
        pct   = cnt / summary["합계"] * 100 if summary["합계"] else 0
        icon  = _SENT_ICON.get(sent, "📊")
        color = _SENT_COLOR[sent]
        col.markdown(
            f"<div style='text-align:center;padding:8px;border-radius:8px;"
            f"border:1px solid {color}'>"
            f"<div style='font-size:22px'>{icon}</div>"
            f"<div style='font-size:20px;font-weight:bold;color:{color}'>{cnt}건</div>"
            f"<div style='font-size:12px;color:#888'>{sent} ({pct:.0f}%)</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    with st.expander("감성 분포 차트 보기", expanded=False):
        fig_dist = px.bar(
            {"감성": ["긍정", "중립", "부정"],
             "건수": [summary["긍정"], summary["중립"], summary["부정"]]},
            x="건수", y="감성", orientation="h",
            color="감성", color_discrete_map=_SENT_COLOR, text="건수",
        )
        fig_dist.update_traces(textposition="outside")
        fig_dist.update_layout(height=200, showlegend=False, margin=dict(l=0, r=40, t=10, b=0))
        st.plotly_chart(fig_dist, width="stretch")

    st.subheader(f"뉴스 목록  ({len(filtered)}건)")

    if not filtered:
        st.info("선택한 조건에 해당하는 뉴스가 없습니다.")
        return

    _SRC_BADGE = {"Naver": ("📡", "#2980B9"), "Mock": ("🎲", "#95A5A6")}
    for item in filtered:
        sent  = item.get("sentiment", "중립")
        color = _SENT_COLOR.get(sent, "#888")
        icon  = _SENT_ICON.get(sent, "📊")
        score = item.get("impact_score", 3)
        stars = "★" * score + "☆" * (5 - score)
        src   = item.get("source", "Mock")
        src_icon, src_color = _SRC_BADGE.get(src, ("🎲", "#95A5A6"))
        link_html = (
            f"<a href='{item['url']}' target='_blank' "
            f"style='font-size:11px;color:{src_color}'>{src_icon} {src}</a>"
            if item.get("url") else
            f"<span style='font-size:11px;color:{src_color}'>{src_icon} {src}</span>"
        )
        with st.container():
            nc1, nc2 = st.columns([6, 1])
            with nc1:
                st.markdown(
                    f"**{icon} {item['title']}**  \n"
                    f"<span style='font-size:12px;color:#888'>"
                    f"{item.get('stock_name','')} ({item.get('stock_code','')})  |  "
                    f"{item.get('news_date','')}  |  {link_html}</span>",
                    unsafe_allow_html=True,
                )
                if item.get("summary"):
                    st.caption(item["summary"])
            with nc2:
                st.markdown(
                    f"<div style='text-align:center;margin-top:6px'>"
                    f"<span style='background:{color};color:white;padding:3px 10px;"
                    f"border-radius:6px;font-size:12px;font-weight:bold'>{sent}</span><br>"
                    f"<span style='font-size:11px;color:#F39C12'>{stars}</span></div>",
                    unsafe_allow_html=True,
                )
            st.divider()


# ════════════════════════════════════════════════════════════════
# 화면 4 – 매매일지
# ════════════════════════════════════════════════════════════════
def render_trade_journal(market_df: pd.DataFrame) -> None:
    _render_menu_title(
        "📝 매매일지",
        "사용자의 판단과 거래 메모를 기록하고, 진입·청산 근거와 결과를 복기합니다.",
    )
    from services.db_service import save_trade_journal, get_trade_journal
    from services.supabase_client import is_connected

    if not is_connected():
        st.info("ℹ️ Mock 모드: 앱 재시작 시 기록이 초기화됩니다.")

    tab_add, tab_list = st.tabs(["✏️ 거래 등록", "📋 거래 조회"])
    stock_map = {row["stock_name"]: row["stock_code"] for _, row in market_df.iterrows()}

    with tab_add:
        with st.form("trade_form", clear_on_submit=True):
            fc1, fc2 = st.columns(2)
            with fc1:
                trade_date  = st.date_input("거래일", value=date.today())
                stock_name  = st.selectbox("종목", list(stock_map.keys()))
                action      = st.selectbox("거래 유형", ["매수", "매도"])
            with fc2:
                entry_price = st.number_input("진입 단가 (원)", min_value=1,  value=50_000, step=100)
                exit_price  = st.number_input("청산 단가 (원, 매도 시)",     min_value=0, value=0, step=100)
                quantity    = st.number_input("수량 (주)",      min_value=1,  value=10, step=1)
            reason      = st.text_area("매매 이유")
            result_memo = st.text_area("결과 메모")

            return_rate = None
            if action == "매도" and exit_price > 0 and entry_price > 0:
                return_rate = round((exit_price - entry_price) / entry_price * 100, 2)
                st.info(f"예상 수익률: **{return_rate:+.2f}%**")

            submitted = st.form_submit_button("💾 등록", width="stretch")

        if submitted:
            save_trade_journal({
                "trade_date":  str(trade_date),
                "stock_code":  stock_map[stock_name],
                "stock_name":  stock_name,
                "action":      action,
                "entry_price": int(entry_price),
                "exit_price":  int(exit_price) if exit_price > 0 else None,
                "quantity":    int(quantity),
                "reason":      reason,
                "result_memo": result_memo,
                "return_rate": return_rate,
            })
            st.success(f"✅ {trade_date} | {stock_name} {action} {quantity}주 @ {entry_price:,}원 등록 완료!")

    with tab_list:
        trades = get_trade_journal()
        if not trades:
            st.info("📭 등록된 거래 내역이 없습니다.")
            return

        df_t = pd.DataFrame(trades)
        kc1, kc2, kc3 = st.columns(3)
        kc1.metric("총 거래 건수", f"{len(df_t)}건")
        kc2.metric("매수 건수", f"{(df_t['action'] == '매수').sum()}건" if "action" in df_t.columns else "-")
        kc3.metric("매도 건수", f"{(df_t['action'] == '매도').sum()}건" if "action" in df_t.columns else "-")

        show_cols = [c for c in [
            "trade_date", "stock_name", "action",
            "entry_price", "exit_price", "quantity",
            "return_rate", "reason", "result_memo",
        ] if c in df_t.columns]
        rename = {
            "trade_date": "거래일", "stock_name": "종목명", "action": "유형",
            "entry_price": "진입가", "exit_price": "청산가", "quantity": "수량",
            "return_rate": "수익률(%)", "reason": "이유", "result_memo": "메모",
        }
        st.dataframe(
            df_t[show_cols].rename(columns=rename),
            width="stretch",
            height=400,
        )


# ════════════════════════════════════════════════════════════════
# 화면 5 – 모의투자
# ════════════════════════════════════════════════════════════════
def render_virtual_trading(market_df: pd.DataFrame, scored_df: pd.DataFrame) -> None:
    _render_menu_title(
        "💼 모의투자",
        "실제 주문 없이 전략 조건에 따른 가상 매수·매도를 실행해 주문 흐름을 연습합니다.",
    )
    st.caption("실거래 주문이 아닌 가상 주문만 생성합니다. 키움 주문 API와 실계좌 정보는 사용하지 않습니다.")

    from services.virtual_trading import (
        DEFAULT_RULE,
        create_virtual_order,
        get_portfolio_snapshot,
        run_light_backtest,
        run_strategy_once,
        summarize_strategy_performance,
    )

    snapshot = get_portfolio_snapshot(market_df)
    positions = snapshot["positions"]
    orders = snapshot["orders"]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("초기 자금", f"{snapshot['initial_cash']:,.0f}원")
    k2.metric("현금", f"{snapshot['cash']:,.0f}원")
    k3.metric("평가금액", f"{snapshot['market_value']:,.0f}원")
    k4.metric("총 수익률", f"{snapshot['total_return']:+.2f}%")

    st.warning("안전장치: 이 화면의 모든 주문은 `virtual_orders` 저장소에만 기록됩니다. 실거래 주문 함수는 호출하지 않습니다.")

    tab_portfolio, tab_order, tab_strategy, tab_backtest = st.tabs([
        "📌 포트폴리오",
        "🧾 가상 주문",
        "⚙️ 전략 실행",
        "🧪 백테스트",
    ])

    with tab_portfolio:
        st.subheader("보유 포지션")
        if positions.empty:
            st.info("아직 보유 중인 가상 포지션이 없습니다.")
        else:
            show = positions.copy()
            show_cols = [
                "strategy_name", "stock_name", "stock_code", "quantity",
                "avg_price", "current_price", "market_value",
                "unrealized_pnl", "return_rate",
            ]
            rename = {
                "strategy_name": "전략",
                "stock_name": "종목명",
                "stock_code": "종목코드",
                "quantity": "수량",
                "avg_price": "평단가",
                "current_price": "현재가",
                "market_value": "평가금액",
                "unrealized_pnl": "평가손익",
                "return_rate": "수익률(%)",
            }
            st.dataframe(show[show_cols].rename(columns=rename), width="stretch", height=320)

        perf = summarize_strategy_performance(market_df)
        st.subheader("전략별 성과")
        if perf.empty:
            st.info("전략 성과를 계산할 가상 주문이 없습니다.")
        else:
            st.dataframe(perf.rename(columns={
                "strategy_name": "전략",
                "orders": "주문수",
                "buy_orders": "매수",
                "sell_orders": "매도",
                "open_positions": "보유종목",
                "market_value": "평가금액",
                "unrealized_pnl": "평가손익",
                "return_rate": "수익률(%)",
            }), width="stretch")

    with tab_order:
        st.subheader("수동 가상 주문")
        stock_map = {
            f"{row['stock_name']} ({row['stock_code']})": row
            for _, row in market_df.iterrows()
        }
        with st.form("virtual_order_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                selected = st.selectbox("종목", list(stock_map.keys()))
                side = st.selectbox("구분", ["BUY", "SELL"], format_func=lambda x: "가상 매수" if x == "BUY" else "가상 매도")
            selected_row = stock_map[selected]
            default_price = int(selected_row.get("current_price", selected_row.get("close", 0)) or 0)
            with c2:
                quantity = st.number_input("수량", min_value=1, value=1, step=1)
                price = st.number_input("가격", min_value=1, value=max(default_price, 1), step=100)
            with c3:
                strategy_name = st.text_input("전략명", value=DEFAULT_RULE.name)
                reason = st.text_area("사유", value="수동 가상 주문")
            submitted = st.form_submit_button("가상 주문 저장", width="stretch")

        if submitted:
            order = create_virtual_order(
                str(selected_row["stock_code"]),
                str(selected_row["stock_name"]),
                side,
                int(quantity),
                float(price),
                strategy_name=strategy_name,
                reason=reason,
            )
            st.success(f"가상 주문 저장 완료: {order['stock_name']} {order['side']} {order['quantity']}주")

        st.subheader("가상 주문 내역")
        if not orders:
            st.info("저장된 가상 주문이 없습니다.")
        else:
            df_orders = pd.DataFrame(orders)
            show_cols = [c for c in [
                "order_date", "strategy_name", "stock_name", "side",
                "quantity", "price", "amount", "status", "reason",
            ] if c in df_orders.columns]
            st.dataframe(df_orders[show_cols].rename(columns={
                "order_date": "주문일",
                "strategy_name": "전략",
                "stock_name": "종목명",
                "side": "구분",
                "quantity": "수량",
                "price": "가격",
                "amount": "금액",
                "status": "상태",
                "reason": "사유",
            }), width="stretch", height=360)

    with tab_strategy:
        st.subheader("전략 조건 가상 매수/매도")
        st.write(
            f"기본 전략: 점수 {DEFAULT_RULE.min_score}점 이상, "
            f"{', '.join(DEFAULT_RULE.buy_decisions)} 매수 후보. "
            f"손절 {DEFAULT_RULE.stop_loss_pct:+.1f}%, 익절 {DEFAULT_RULE.take_profit_pct:+.1f}%."
        )
        if st.button("전략 1회 실행", width="stretch"):
            result = run_strategy_once(market_df, scored_df)
            if result["created_count"] == 0:
                st.info("이번 실행에서 생성된 가상 주문이 없습니다.")
            else:
                st.success(f"가상 주문 {result['created_count']}건 생성")
                st.dataframe(pd.DataFrame(result["created"]), width="stretch")

    with tab_backtest:
        st.subheader("경량 백테스트")
        days = st.slider("백테스트 기간(거래일)", min_value=5, max_value=60, value=20, step=5)
        bt = run_light_backtest(scored_df, days=days)
        if bt.empty:
            st.info("백테스트할 후보 종목이 없습니다.")
        else:
            avg_return = float(bt["return_rate"].mean())
            win_rate = float((bt["return_rate"] > 0).mean() * 100)
            b1, b2, b3 = st.columns(3)
            b1.metric("대상 종목", f"{len(bt)}개")
            b2.metric("평균 수익률", f"{avg_return:+.2f}%")
            b3.metric("승률", f"{win_rate:.1f}%")
            st.dataframe(bt.rename(columns={
                "stock_code": "종목코드",
                "stock_name": "종목명",
                "strategy_name": "전략",
                "score": "점수",
                "decision": "판단",
                "backtest_days": "기간",
                "entry_price": "진입가",
                "return_rate": "수익률(%)",
                "result": "결과",
            }), width="stretch")


# ════════════════════════════════════════════════════════════════
# 화면 6 – 모의 포트폴리오
# ════════════════════════════════════════════════════════════════
def render_paper_portfolio(market_df: pd.DataFrame, scored_df: pd.DataFrame) -> None:
    _render_menu_title(
        "📊 모의 포트폴리오",
        "가상 보유 종목, 현금, 평가손익, 주문 내역을 확인하고 모의 계좌 상태를 관리합니다.",
    )

    # ── 가상 주문 안내 배너 ────────────────────────────────────
    st.warning(
        "⚠️  **이 화면은 가상(모의) 투자 전용입니다.**  "
        "모든 주문은 `virtual_orders` 테이블에만 기록되며, "
        "키움증권 주문 API·실계좌·계좌 비밀번호와 **완전히 분리**되어 있습니다.  "
        "표시된 수치는 모의 투자 결과이며 실제 자산과 무관합니다.",
        icon="🛡️",
    )

    # ── 데이터 로드 ────────────────────────────────────────────
    try:
        from services.virtual_portfolio import get_portfolio
        from services.virtual_position import get_positions
        from services.virtual_trading import list_virtual_orders
    except Exception as e:
        st.error(f"모의투자 서비스 로드 실패: {e}")
        return

    portfolio   = get_portfolio()
    positions   = get_positions(status="보유")
    all_positions = get_positions(status=None)
    raw_orders  = list_virtual_orders()

    # ── KPI 카드 ───────────────────────────────────────────────
    initial_cash      = float(portfolio.get("initial_cash",      10_000_000))
    cash_balance      = float(portfolio.get("cash_balance",      initial_cash))
    total_asset       = float(portfolio.get("total_asset",       initial_cash))
    total_profit_loss = float(portfolio.get("total_profit_loss", 0))
    total_return_rate = float(portfolio.get("total_return_rate", 0))

    # 현재 보유 평가금액 계산
    market_index = {
        str(r["stock_code"]).zfill(6): r
        for _, r in market_df.iterrows()
    }
    market_value = 0.0
    for pos in positions:
        code  = str(pos.get("stock_code", "")).zfill(6)
        qty   = int(pos.get("quantity", 0))
        mrow  = market_index.get(code, {})
        cprice = float(
            mrow.get("current_price") or mrow.get("close") or
            pos.get("current_price") or pos.get("entry_price") or 0
        )
        market_value += cprice * qty

    pnl_color = "#E74C3C" if total_profit_loss < 0 else "#27AE60"

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(
        "총자산",
        f"{total_asset:,.0f}원",
        help="현금 + 보유 종목 평가금액",
    )
    k2.metric(
        "현금 잔고",
        f"{cash_balance:,.0f}원",
        help="가용 현금 (가상)",
    )
    k3.metric(
        "보유 평가금액",
        f"{market_value:,.0f}원",
        help="현재가 × 보유 수량 합계",
    )
    k4.metric(
        "총 손익",
        f"{total_profit_loss:+,.0f}원",
        delta=f"{total_return_rate:+.2f}%",
        delta_color="normal",
    )
    k5.metric(
        "총 수익률",
        f"{total_return_rate:+.2f}%",
        help=f"기준 초기 자금: {initial_cash:,.0f}원",
    )

    st.markdown("")

    # ── 탭 구성 ────────────────────────────────────────────────
    tab_holdings, tab_orders, tab_run = st.tabs([
        "📌 보유 종목",
        "🧾 가상 주문 내역",
        "⚡ 일일 매매 실행",
    ])

    # ── Tab 1: 보유 종목 ────────────────────────────────────────
    with tab_holdings:
        st.subheader(f"📌 현재 보유 종목  ({len(positions)}종목)")

        if not positions:
            st.info("현재 보유 중인 가상 포지션이 없습니다.")
        else:
            rows = []
            for pos in positions:
                code       = str(pos.get("stock_code", "")).zfill(6)
                qty        = int(pos.get("quantity", 0))
                entry_p    = float(pos.get("entry_price", 0))
                mrow       = market_index.get(code, {})
                curr_p     = float(
                    mrow.get("current_price") or mrow.get("close") or
                    pos.get("current_price") or entry_p or 0
                )
                eval_amt   = round(curr_p * qty, 0)
                cost_amt   = round(entry_p * qty, 0)
                pnl_amt    = round(eval_amt - cost_amt, 0)
                ret_rate   = round(pnl_amt / cost_amt * 100, 2) if cost_amt else 0.0
                target_p   = pos.get("target_price")
                stop_p     = pos.get("stop_loss_price")
                hdays      = int(pos.get("holding_days", 0))
                strategy   = pos.get("strategy_name", "—")

                rows.append({
                    "종목명":    pos.get("stock_name", code),
                    "종목코드":  code,
                    "전략":      strategy,
                    "수량(주)":  qty,
                    "진입단가":  int(entry_p),
                    "현재가":    int(curr_p),
                    "평가금액":  int(eval_amt),
                    "평가손익":  int(pnl_amt),
                    "수익률(%)": ret_rate,
                    "목표가":    int(target_p) if target_p else None,
                    "손절가":    int(stop_p)   if stop_p   else None,
                    "보유일":    hdays,
                    "상태":      pos.get("status", "보유"),
                })

            df_pos = pd.DataFrame(rows)

            def _color_pnl(val):
                if isinstance(val, (int, float)):
                    color = "#E74C3C" if val < 0 else ("#27AE60" if val > 0 else "#555")
                    return f"color:{color};font-weight:bold"
                return ""

            styled_pos = (
                df_pos.style
                .format({
                    "진입단가":  "{:,}원",
                    "현재가":    "{:,}원",
                    "평가금액":  "{:,}원",
                    "평가손익":  "{:+,}원",
                    "수익률(%)": "{:+.2f}%",
                    "목표가":    lambda v: f"{v:,}원" if v is not None else "—",
                    "손절가":    lambda v: f"{v:,}원" if v is not None else "—",
                }, na_rep="—")
                .map(_color_pnl, subset=["평가손익", "수익률(%)"])
            )
            st.dataframe(styled_pos, width="stretch", height=350, hide_index=True)

            # 보유 종목 수익률 막대 차트
            if len(df_pos) >= 2:
                with st.expander("📊 보유 종목 수익률 차트"):
                    chart_df = df_pos[["종목명", "수익률(%)"]].sort_values("수익률(%)")
                    colors = ["#E74C3C" if v < 0 else "#27AE60" for v in chart_df["수익률(%)"]]
                    fig_hold = go.Figure(go.Bar(
                        x=chart_df["수익률(%)"],
                        y=chart_df["종목명"],
                        orientation="h",
                        marker_color=colors,
                        text=[f"{v:+.2f}%" for v in chart_df["수익률(%)"]],
                        textposition="outside",
                    ))
                    fig_hold.update_layout(
                        height=max(220, len(chart_df) * 44),
                        xaxis_title="수익률 (%)",
                        margin=dict(l=0, r=60, t=10, b=0),
                    )
                    st.plotly_chart(fig_hold, width="stretch")

        # 청산 포지션 요약
        closed_pos = [p for p in all_positions if p.get("status") in ("청산", "손절", "익절")]
        if closed_pos:
            st.divider()
            st.subheader(f"📂 청산 내역  ({len(closed_pos)}건)")
            익절 = sum(1 for p in closed_pos if p.get("status") == "익절")
            손절 = sum(1 for p in closed_pos if p.get("status") == "손절")
            청산 = sum(1 for p in closed_pos if p.get("status") == "청산")
            cl1, cl2, cl3 = st.columns(3)
            cl1.metric("익절", f"{익절}건", delta="수익")
            cl2.metric("손절", f"{손절}건", delta="손실", delta_color="inverse")
            cl3.metric("기타 청산", f"{청산}건")

            with st.expander("청산 내역 전체 보기"):
                closed_rows = []
                for p in closed_pos:
                    ep    = float(p.get("entry_price", 0))
                    cp    = float(p.get("current_price", ep))
                    qty   = int(p.get("quantity", 0))
                    pnl   = float(p.get("profit_loss", round((cp - ep) * qty, 0)))
                    ret   = float(p.get("return_rate", round(pnl / (ep * qty) * 100, 2) if ep * qty else 0))
                    closed_rows.append({
                        "종목명":    p.get("stock_name", ""),
                        "전략":      p.get("strategy_name", ""),
                        "진입일":    p.get("entry_date", ""),
                        "수량":      qty,
                        "진입단가":  int(ep),
                        "청산단가":  int(cp),
                        "손익(원)":  int(pnl),
                        "수익률(%)": ret,
                        "보유일":    p.get("holding_days", ""),
                        "청산유형":  p.get("status", ""),
                    })
                st.dataframe(pd.DataFrame(closed_rows), width="stretch", height=300, hide_index=True)

    # ── Tab 2: 가상 주문 내역 ────────────────────────────────────
    with tab_orders:
        st.subheader("🧾 가상 주문 내역")
        st.caption("🔒 아래 모든 주문은 가상 주문입니다. 실제 계좌 거래와 무관합니다.")

        if not raw_orders:
            st.info("저장된 가상 주문이 없습니다.")
        else:
            df_ord = pd.DataFrame(raw_orders)

            # 필터
            flt1, flt2, flt3 = st.columns(3)
            with flt1:
                side_opts = ["전체"] + sorted(df_ord["side"].dropna().unique().tolist()) if "side" in df_ord.columns else ["전체"]
                sel_side  = st.selectbox("구분 필터", side_opts, key="pp_side")
            with flt2:
                strat_opts = ["전체"] + sorted(df_ord["strategy_name"].dropna().unique().tolist()) if "strategy_name" in df_ord.columns else ["전체"]
                sel_strat  = st.selectbox("전략 필터", strat_opts, key="pp_strat")
            with flt3:
                st.caption(f"총 {len(df_ord)}건")

            view_ord = df_ord.copy()
            if sel_side != "전체" and "side" in view_ord.columns:
                view_ord = view_ord[view_ord["side"] == sel_side]
            if sel_strat != "전체" and "strategy_name" in view_ord.columns:
                view_ord = view_ord[view_ord["strategy_name"] == sel_strat]

            show_cols = [c for c in [
                "order_date", "strategy_name", "stock_name", "stock_code",
                "side", "quantity", "price", "amount", "status", "reason",
            ] if c in view_ord.columns]

            rename_map = {
                "order_date":    "주문일",
                "strategy_name": "전략",
                "stock_name":    "종목명",
                "stock_code":    "코드",
                "side":          "구분",
                "quantity":      "수량",
                "price":         "단가(원)",
                "amount":        "금액(원)",
                "status":        "상태",
                "reason":        "사유",
            }
            view_display = view_ord[show_cols].rename(columns=rename_map)

            def _side_color(val):
                if val == "BUY":
                    return "color:#E74C3C;font-weight:bold"
                if val == "SELL":
                    return "color:#2980B9;font-weight:bold"
                return ""

            styled_ord = view_display.style
            if "구분" in view_display.columns:
                styled_ord = styled_ord.map(_side_color, subset=["구분"])
            if "단가(원)" in view_display.columns:
                styled_ord = styled_ord.format({"단가(원)": "{:,.0f}", "금액(원)": "{:,.0f}"})

            st.dataframe(styled_ord, width="stretch", height=400, hide_index=True)

            # 매수/매도 집계
            if "side" in df_ord.columns and "amount" in df_ord.columns:
                buy_amt  = float(df_ord[df_ord["side"] == "BUY"]["amount"].sum())
                sell_amt = float(df_ord[df_ord["side"] == "SELL"]["amount"].sum())
                oc1, oc2, oc3 = st.columns(3)
                oc1.metric("전체 주문", f"{len(df_ord)}건")
                oc2.metric("총 매수금액 (가상)", f"{buy_amt:,.0f}원")
                oc3.metric("총 매도금액 (가상)", f"{sell_amt:,.0f}원")

    # ── Tab 3: 일일 매매 실행 ────────────────────────────────────
    with tab_run:
        st.subheader("⚡ 일일 모의매매 실행")
        st.info(
            "스캐너 점수·전략 규칙·리스크 조건을 적용하여 오늘의 가상 매수/매도를 자동 실행합니다.  \n"
            "실제 주문은 절대 생성되지 않습니다.",
            icon="ℹ️",
        )

        # 실행 버튼
        run_col, _ = st.columns([2, 5])
        with run_col:
            run_clicked = st.button(
                "🚀 일일 모의매매 실행",
                type="primary",
                width="stretch",
                key="pp_run_btn",
            )

        if run_clicked:
            with st.spinner("모의매매 실행 중..."):
                try:
                    from strategy.paper_trading_engine import run_daily_virtual_trading
                    result = run_daily_virtual_trading(market_df, scored_df)
                    st.session_state["paper_trade_result"] = result
                    st.rerun()
                except Exception as e:
                    st.error(f"모의매매 실행 오류: {e}")

        # 실행 결과 표시
        result = st.session_state.get("paper_trade_result")
        if result:
            st.success("✅ 일일 모의매매 실행 완료")
            rm1, rm2, rm3 = st.columns(3)
            rm1.metric("매수 체결",  f"{result.get('buy_count',  0)}건")
            rm2.metric("매도 체결",  f"{result.get('sell_count', 0)}건")
            pnl = result.get("total_pnl", 0)
            rm3.metric("오늘 실현 손익", f"{pnl:+,.0f}원",
                       delta_color="normal" if pnl >= 0 else "inverse")

            with st.expander("📋 실행 결과 상세 보기", expanded=True):
                st.code(result.get("summary_text", "결과 없음"), language=None)

            buy_details  = result.get("buy_details",  [])
            sell_details = result.get("sell_details", [])

            if buy_details:
                st.subheader("매수 체결 내역 (가상)")
                buy_rows = [
                    {
                        "종목명":    r.get("stock_name", ""),
                        "전략":      r.get("strategy_name", ""),
                        "수량":      r.get("quantity", 0),
                        "단가(원)":  f"{r.get('price', 0):,.0f}",
                        "목표가(원)": f"{r.get('target_price', 0):,.0f}" if r.get("target_price") else "—",
                        "손절가(원)": f"{r.get('stop_loss_price', 0):,.0f}" if r.get("stop_loss_price") else "—",
                        "결과":      "✅ 체결" if r.get("success") else "❌ 실패",
                        "메시지":    r.get("message", ""),
                    }
                    for r in buy_details
                ]
                st.dataframe(pd.DataFrame(buy_rows), width="stretch", hide_index=True)

            if sell_details:
                st.subheader("매도 체결 내역 (가상)")
                sell_rows = [
                    {
                        "종목명":    r.get("stock_name", ""),
                        "청산유형":  r.get("close_reason", ""),
                        "수량":      r.get("quantity", 0),
                        "단가(원)":  f"{r.get('price', 0):,.0f}",
                        "손익(원)":  f"{r.get('profit_loss', 0):+,.0f}",
                        "수익률(%)": f"{r.get('return_rate', 0):+.2f}%",
                        "사유":      r.get("exit_reason", ""),
                        "결과":      "✅ 체결" if r.get("success") else "❌ 실패",
                    }
                    for r in sell_details
                ]
                st.dataframe(pd.DataFrame(sell_rows), width="stretch", hide_index=True)

        st.divider()

        # ── 포트폴리오 초기화 ─────────────────────────────────
        st.subheader("🔄 포트폴리오 초기화")
        st.caption(
            f"가상 포트폴리오를 초기 상태(현금 {initial_cash:,.0f}원)로 리셋합니다.  "
            "보유 포지션·주문 내역은 삭제되지 않으나 현금이 초기화됩니다."
        )

        if not st.session_state["paper_reset_confirm"]:
            rst_col, _ = st.columns([2, 5])
            with rst_col:
                if st.button("🔄 포트폴리오 초기화", type="secondary", width="stretch", key="pp_reset_btn"):
                    st.session_state["paper_reset_confirm"] = True
                    st.rerun()
        else:
            st.warning("정말로 포트폴리오를 초기 자금으로 리셋하시겠습니까?")
            rc1, rc2, _ = st.columns([1, 1, 4])
            with rc1:
                if st.button("✅ 확인 — 초기화", type="primary", key="pp_reset_yes"):
                    try:
                        from services.virtual_portfolio import reset_portfolio
                        reset_portfolio()
                        st.session_state["paper_reset_confirm"] = False
                        st.session_state["paper_trade_result"]  = None
                        st.success("✅ 포트폴리오가 초기화되었습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"초기화 실패: {e}")
            with rc2:
                if st.button("❌ 취소", key="pp_reset_no"):
                    st.session_state["paper_reset_confirm"] = False
                    st.rerun()

    # ── 하단 면책 안내 ─────────────────────────────────────────
    st.divider()
    st.caption(
        "🔒 **법적 고지**: 이 화면에 표시된 모든 정보는 모의(가상) 투자 결과이며, "
        "실제 투자 손익과 무관합니다. 투자 판단에 참고하지 마십시오."
    )


# ════════════════════════════════════════════════════════════════
# 화면 7 – 전략 성과
# ════════════════════════════════════════════════════════════════
def render_strategy_performance() -> None:
    _render_menu_title(
        "🏆 전략 성과",
        "청산된 가상 거래를 기준으로 전략별 승률, 손익, 낙폭, 거래 분포를 비교합니다.",
    )
    st.caption("청산·손절·익절된 가상 포지션을 기반으로 전략별 성과를 분석합니다.")

    # ── 데이터 로드 ────────────────────────────────────────────
    with st.spinner("성과 데이터 분석 중..."):
        try:
            from analysis.performance_analyzer import summarize_performance
            perf = summarize_performance()
        except Exception as e:
            st.error(f"성과 분석 오류: {e}")
            return

    summary_df  = perf.get("summary_df",  pd.DataFrame())
    detail_list = perf.get("detail_list", [])
    total       = perf.get("total",       {})

    # ── 데이터 없음 ────────────────────────────────────────────
    if not detail_list or total.get("total_trades", 0) == 0:
        st.info(
            "📭 분석할 청산 거래 내역이 없습니다.  \n"
            "**모의 포트폴리오** 화면에서 일일 모의매매를 실행하고 "
            "포지션이 익절·손절·청산된 후 다시 확인해 주세요.",
            icon="ℹ️",
        )
        return

    # ── 전체 요약 KPI ──────────────────────────────────────────
    t_trades  = int(total.get("total_trades",     0))
    t_wins    = int(total.get("win_trades",        0))
    t_losses  = int(total.get("lose_trades",       0))
    t_winrate = float(total.get("win_rate",        0.0))
    t_pnl     = float(total.get("total_profit_loss", 0.0))
    t_ret     = float(total.get("total_return_rate", 0.0))
    t_mdd     = float(total.get("max_drawdown",    0.0))
    t_pf      = float(total.get("profit_factor",   0.0))
    t_avg_ret = float(total.get("avg_return_rate", 0.0))

    st.subheader("📈 전체 통합 성과")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("총 거래 수",   f"{t_trades}건",
              help=f"승 {t_wins}건 / 패 {t_losses}건")
    k2.metric("승률",          f"{t_winrate:.1f}%",
              delta=f"승 {t_wins} / 패 {t_losses}")
    k3.metric("평균 수익률",   f"{t_avg_ret:+.2f}%")
    k4.metric("누적 수익률",   f"{t_ret:+.2f}%",
              delta=f"{t_pnl:+,.0f}원",
              delta_color="normal" if t_pnl >= 0 else "inverse")
    k5.metric("최대 낙폭",     f"{t_mdd:.2f}%",
              delta_color="inverse")
    k6.metric("손익비",        f"{t_pf:.2f}",
              help="총 수익 ÷ 총 손실 (2 이상 우수)")

    st.divider()

    # ── 전략 등급 배지 ─────────────────────────────────────────
    def _perf_grade(ret: float, winrate: float, pf: float) -> tuple[str, str]:
        """수익률·승률·손익비로 전략 등급을 결정한다."""
        score = 0
        if ret   >  5:  score += 2
        elif ret >  0:  score += 1
        if winrate > 60: score += 2
        elif winrate > 45: score += 1
        if pf > 2.0: score += 2
        elif pf > 1.0: score += 1
        if score >= 5:   return "A등급", "#1A5E35"
        elif score >= 3: return "B등급", "#F39C12"
        else:            return "C등급", "#E74C3C"

    # ── 탭 구성 ────────────────────────────────────────────────
    tab_compare, tab_chart, tab_curve, tab_loss = st.tabs([
        "📊 전략별 비교",
        "📉 성과 차트",
        "📈 손익 곡선",
        "❌ 손실 거래 목록",
    ])

    # ════════════════════════════════════════════════════════════
    # Tab 1: 전략별 비교
    # ════════════════════════════════════════════════════════════
    with tab_compare:
        st.subheader(f"전략별 비교  ({len(detail_list)}개 전략)")

        # ── 전략 카드 ──────────────────────────────────────────
        best_ret   = max(detail_list, key=lambda d: d.get("total_return_rate", -999))
        worst_ret  = min(detail_list, key=lambda d: d.get("total_return_rate", 999))
        best_win   = max(detail_list, key=lambda d: d.get("win_rate", 0))
        best_pf    = max(detail_list, key=lambda d: d.get("profit_factor", 0))

        # 하이라이트 카드 행
        if len(detail_list) >= 2:
            bc1, bc2, bc3 = st.columns(3)
            def _highlight_card(col, label: str, detail: dict, color: str) -> None:
                ret  = float(detail.get("total_return_rate", 0))
                name = detail.get("strategy_name", "—")
                col.markdown(
                    f"<div style='padding:10px 14px;border-radius:10px;"
                    f"border:2px solid {color};background:{color}11;text-align:center'>"
                    f"<div style='font-size:11px;color:{color};font-weight:bold'>{label}</div>"
                    f"<div style='font-size:14px;font-weight:bold;margin:4px 0'>{name}</div>"
                    f"<div style='font-size:22px;font-weight:bold;color:{color}'>{ret:+.2f}%</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            _highlight_card(bc1, "🥇 최고 수익 전략", best_ret,  "#27AE60")
            _highlight_card(bc2, "📉 최저 수익 전략", worst_ret, "#E74C3C")
            _highlight_card(bc3, "🎯 최고 승률 전략", best_win,  "#2980B9")

        st.markdown("")

        # ── 전략 상세 카드 목록 ────────────────────────────────
        for detail in sorted(detail_list,
                              key=lambda d: d.get("total_return_rate", 0), reverse=True):
            name    = detail.get("strategy_name", "—")
            trades  = int(detail.get("total_trades",      0))
            wins    = int(detail.get("win_trades",         0))
            losses  = int(detail.get("lose_trades",        0))
            winrate = float(detail.get("win_rate",         0.0))
            avg_ret = float(detail.get("avg_return_rate",  0.0))
            tot_ret = float(detail.get("total_return_rate",0.0))
            mdd     = float(detail.get("max_drawdown",     0.0))
            pf      = float(detail.get("profit_factor",    0.0))
            pnl     = float(detail.get("total_profit_loss",0.0))
            ikjeol  = int(detail.get("익절_count", 0))
            sonjeol = int(detail.get("손절_count", 0))
            cheong  = int(detail.get("청산_count",  0))
            avg_hold = float(detail.get("avg_holding_days", 0.0))
            grade, gcolor = _perf_grade(tot_ret, winrate, pf)

            ret_color = "#27AE60" if tot_ret >= 0 else "#E74C3C"
            pnl_sign  = "+" if pnl >= 0 else ""

            with st.expander(
                f"[{grade}]  {name}  —  수익률 {tot_ret:+.2f}%  |  승률 {winrate:.1f}%  |  "
                f"손익비 {pf:.2f}  |  거래 {trades}건",
                expanded=True,
            ):
                # 등급 배지
                st.markdown(
                    f"<span style='background:{gcolor};color:white;padding:3px 12px;"
                    f"border-radius:6px;font-size:13px;font-weight:bold'>{grade}</span>"
                    f"&nbsp;"
                    f"<span style='color:{ret_color};font-size:18px;font-weight:bold'>"
                    f"누적 수익률 {tot_ret:+.2f}%  ({pnl_sign}{pnl:,.0f}원)</span>",
                    unsafe_allow_html=True,
                )
                st.markdown("")

                m1, m2, m3, m4, m5, m6 = st.columns(6)
                m1.metric("총 거래",  f"{trades}건")
                m2.metric("승률",     f"{winrate:.1f}%",
                          delta=f"승 {wins} / 패 {losses}")
                m3.metric("평균 수익률", f"{avg_ret:+.2f}%")
                m4.metric("최대 낙폭", f"{mdd:.2f}%")
                m5.metric("손익비",   f"{pf:.2f}")
                m6.metric("평균 보유일", f"{avg_hold:.1f}일")

                # 청산 유형 분포
                if trades > 0:
                    dist_cols = st.columns(3)
                    for col, label, cnt, color in [
                        (dist_cols[0], "익절", ikjeol, "#27AE60"),
                        (dist_cols[1], "손절", sonjeol, "#E74C3C"),
                        (dist_cols[2], "청산", cheong,  "#95A5A6"),
                    ]:
                        pct = cnt / trades * 100 if trades else 0
                        col.markdown(
                            f"<div style='text-align:center;padding:6px;border-radius:6px;"
                            f"border:1px solid {color};background:{color}11'>"
                            f"<div style='font-size:11px;color:{color};font-weight:bold'>{label}</div>"
                            f"<div style='font-size:20px;font-weight:bold;color:{color}'>{cnt}건</div>"
                            f"<div style='font-size:11px;color:#888'>{pct:.0f}%</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

        st.divider()

        # ── 전략 비교 요약 테이블 ─────────────────────────────
        st.subheader("📋 전략 비교 요약 테이블")

        if not summary_df.empty:
            display_cols = [c for c in [
                "전략명", "총 거래", "승리", "손실", "승률(%)",
                "평균 수익률(%)", "누적 수익률(%)", "최대 낙폭(%)",
                "손익비", "실현 손익(원)", "익절", "손절", "기타 청산", "평균 보유일",
            ] if c in summary_df.columns]

            def _style_ret(val):
                try:
                    v = float(val)
                    if v > 0:  return "color:#27AE60;font-weight:bold"
                    if v < 0:  return "color:#E74C3C;font-weight:bold"
                except (TypeError, ValueError):
                    pass
                return ""

            styled = summary_df[display_cols].style
            for col in ["누적 수익률(%)", "평균 수익률(%)"]:
                if col in display_cols:
                    styled = styled.map(_style_ret, subset=[col])
            if "실현 손익(원)" in display_cols:
                styled = styled.map(_style_ret, subset=["실현 손익(원)"])
                styled = styled.format({"실현 손익(원)": "{:+,.0f}"})
            if "승률(%)" in display_cols:
                styled = styled.format({"승률(%)": "{:.1f}%"})
            for col in ["누적 수익률(%)", "평균 수익률(%)"]:
                if col in display_cols:
                    styled = styled.format({col: "{:+.2f}%"})

            st.dataframe(styled, width="stretch", height=280, hide_index=True)

    # ════════════════════════════════════════════════════════════
    # Tab 2: 성과 차트
    # ════════════════════════════════════════════════════════════
    with tab_chart:
        if summary_df.empty:
            st.info("차트를 표시할 데이터가 없습니다.")
        else:
            names = summary_df["전략명"].tolist() if "전략명" in summary_df.columns else []

            # 전략명별 색상 (수익률 기준)
            ret_vals = summary_df["누적 수익률(%)"].tolist() if "누적 수익률(%)" in summary_df.columns else [0] * len(names)
            bar_colors = ["#27AE60" if v >= 0 else "#E74C3C" for v in ret_vals]

            # ── 행 1: 승률 + 누적 수익률 ──────────────────────
            ch1, ch2 = st.columns(2)

            with ch1:
                st.subheader("🎯 전략별 승률")
                win_vals = summary_df["승률(%)"].tolist() if "승률(%)" in summary_df.columns else []
                win_colors = ["#27AE60" if v >= 50 else "#E74C3C" for v in win_vals]
                fig_win = go.Figure(go.Bar(
                    x=names, y=win_vals,
                    marker_color=win_colors,
                    text=[f"{v:.1f}%" for v in win_vals],
                    textposition="outside",
                ))
                fig_win.add_hline(y=50, line_dash="dot", line_color="#888",
                                  annotation_text="50% 기준선")
                fig_win.update_layout(
                    height=320,
                    yaxis=dict(title="승률 (%)", range=[0, 110]),
                    margin=dict(l=0, r=0, t=10, b=40),
                    showlegend=False,
                )
                st.plotly_chart(fig_win, width="stretch")

            with ch2:
                st.subheader("💰 전략별 누적 수익률")
                fig_ret = go.Figure(go.Bar(
                    x=names, y=ret_vals,
                    marker_color=bar_colors,
                    text=[f"{v:+.2f}%" for v in ret_vals],
                    textposition="outside",
                ))
                fig_ret.add_hline(y=0, line_color="#555", line_width=1)
                fig_ret.update_layout(
                    height=320,
                    yaxis_title="누적 수익률 (%)",
                    margin=dict(l=0, r=0, t=10, b=40),
                    showlegend=False,
                )
                st.plotly_chart(fig_ret, width="stretch")

            st.divider()

            # ── 행 2: 손익비 + 최대 낙폭 ──────────────────────
            ch3, ch4 = st.columns(2)

            with ch3:
                st.subheader("⚖️ 전략별 손익비")
                pf_vals = summary_df["손익비"].tolist() if "손익비" in summary_df.columns else []
                pf_colors = ["#27AE60" if v >= 1.0 else "#E74C3C" for v in pf_vals]
                fig_pf = go.Figure(go.Bar(
                    x=names, y=pf_vals,
                    marker_color=pf_colors,
                    text=[f"{v:.2f}" for v in pf_vals],
                    textposition="outside",
                ))
                fig_pf.add_hline(y=1.0, line_dash="dot", line_color="#F39C12",
                                 annotation_text="손익비 1.0 (손익분기)")
                fig_pf.add_hline(y=2.0, line_dash="dot", line_color="#27AE60",
                                 annotation_text="손익비 2.0 (우수)")
                fig_pf.update_layout(
                    height=320,
                    yaxis_title="손익비",
                    margin=dict(l=0, r=0, t=10, b=40),
                    showlegend=False,
                )
                st.plotly_chart(fig_pf, width="stretch")

            with ch4:
                st.subheader("📉 전략별 최대 낙폭 (MDD)")
                mdd_vals = [abs(v) for v in (
                    summary_df["최대 낙폭(%)"].tolist() if "최대 낙폭(%)" in summary_df.columns else []
                )]
                mdd_colors = ["#E74C3C" if v >= 10 else "#F39C12" if v >= 5 else "#27AE60"
                              for v in mdd_vals]
                fig_mdd = go.Figure(go.Bar(
                    x=names, y=mdd_vals,
                    marker_color=mdd_colors,
                    text=[f"{v:.1f}%" for v in mdd_vals],
                    textposition="outside",
                ))
                fig_mdd.update_layout(
                    height=320,
                    yaxis_title="최대 낙폭 |MDD| (%)",
                    margin=dict(l=0, r=0, t=10, b=40),
                    showlegend=False,
                )
                st.plotly_chart(fig_mdd, width="stretch")

            st.divider()

            # ── 행 3: 전략별 거래 수 + 청산 유형 분포 ──────────
            ch5, ch6 = st.columns(2)

            with ch5:
                st.subheader("📊 전략별 거래 수")
                trade_vals = summary_df["총 거래"].tolist() if "총 거래" in summary_df.columns else []
                fig_cnt = go.Figure(go.Bar(
                    x=names, y=trade_vals,
                    marker_color="#2980B9",
                    text=trade_vals,
                    textposition="outside",
                ))
                fig_cnt.update_layout(
                    height=300,
                    yaxis_title="거래 수",
                    margin=dict(l=0, r=0, t=10, b=40),
                    showlegend=False,
                )
                st.plotly_chart(fig_cnt, width="stretch")

            with ch6:
                st.subheader("🎯 전체 청산 유형 분포")
                total_ikjeol  = sum(d.get("익절_count", 0) for d in detail_list)
                total_sonjeol = sum(d.get("손절_count", 0) for d in detail_list)
                total_cheong  = sum(d.get("청산_count",  0) for d in detail_list)

                if total_ikjeol + total_sonjeol + total_cheong > 0:
                    fig_pie = go.Figure(go.Pie(
                        labels=["익절", "손절", "기타 청산"],
                        values=[total_ikjeol, total_sonjeol, total_cheong],
                        marker_colors=["#27AE60", "#E74C3C", "#95A5A6"],
                        textinfo="label+percent+value",
                        hole=0.40,
                    ))
                    fig_pie.update_layout(
                        height=300,
                        showlegend=True,
                        margin=dict(l=0, r=0, t=10, b=0),
                    )
                    st.plotly_chart(fig_pie, width="stretch")
                else:
                    st.info("청산 유형 데이터 없음")

            st.divider()

            # ── 레이더 차트: 전략 종합 비교 ──────────────────
            if len(detail_list) >= 2:
                st.subheader("🕸️ 전략 종합 비교 (레이더 차트)")
                categories = ["승률", "평균 수익률", "손익비", "MDD 안전성", "거래량"]
                fig_radar = go.Figure()

                for detail in detail_list:
                    name     = detail.get("strategy_name", "—")
                    winrate  = min(float(detail.get("win_rate",         0)) / 100 * 100, 100)
                    avg_r    = min(max(float(detail.get("avg_return_rate",  0)) * 5 + 50, 0), 100)
                    pf_norm  = min(float(detail.get("profit_factor", 0)) / 3 * 100, 100)
                    mdd_safe = max(100 + float(detail.get("max_drawdown", 0)) * 5, 0)
                    trd_norm = min(int(detail.get("total_trades", 0)) / max(t_trades, 1) * 100, 100)

                    vals = [winrate, avg_r, pf_norm, mdd_safe, trd_norm]
                    fig_radar.add_trace(go.Scatterpolar(
                        r=vals + [vals[0]],
                        theta=categories + [categories[0]],
                        fill="toself",
                        opacity=0.5,
                        name=name,
                    ))

                fig_radar.update_layout(
                    polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                    showlegend=True,
                    height=380,
                    margin=dict(l=30, r=30, t=10, b=10),
                )
                st.plotly_chart(fig_radar, width="stretch")

    # ════════════════════════════════════════════════════════════
    # Tab 3: 손익 곡선
    # ════════════════════════════════════════════════════════════
    with tab_curve:
        st.subheader("📈 전략별 누적 손익 곡선")

        # detail_list의 trades_df 에서 날짜별 누적 손익 계산
        from services.virtual_portfolio import get_portfolio
        try:
            initial_cash = float(get_portfolio().get("initial_cash", 10_000_000))
        except Exception:
            initial_cash = 10_000_000.0

        has_curve = False
        fig_curve = go.Figure()

        for detail in detail_list:
            trades_df = detail.get("trades_df", pd.DataFrame())
            if isinstance(trades_df, pd.DataFrame) and not trades_df.empty \
                    and "profit_loss" in trades_df.columns and "entry_date" in trades_df.columns:

                tdf = trades_df.copy()
                tdf["entry_date"] = pd.to_datetime(tdf["entry_date"], errors="coerce")
                tdf = tdf.dropna(subset=["entry_date"]).sort_values("entry_date")
                tdf["cumulative_pnl"] = tdf["profit_loss"].cumsum()
                tdf["equity"]         = initial_cash + tdf["cumulative_pnl"]

                fig_curve.add_trace(go.Scatter(
                    x=tdf["entry_date"].astype(str),
                    y=tdf["equity"],
                    mode="lines+markers",
                    name=detail.get("strategy_name", "—"),
                    line=dict(width=2),
                    marker=dict(size=5),
                ))
                has_curve = True

        if has_curve:
            fig_curve.add_hline(
                y=initial_cash,
                line_dash="dot",
                line_color="#888",
                annotation_text=f"초기 자금 {initial_cash:,.0f}원",
                annotation_position="right",
            )
            fig_curve.update_layout(
                height=420,
                yaxis_title="평가 자산 (원)",
                xaxis_title="날짜",
                legend=dict(orientation="h", y=1.02),
                margin=dict(l=0, r=0, t=30, b=0),
                hovermode="x unified",
            )
            fig_curve.update_yaxes(tickformat=",.0f")
            st.plotly_chart(fig_curve, width="stretch")
        else:
            st.info("손익 곡선을 표시할 데이터가 없습니다.")

        # ── 손익 히스토그램 (전체) ─────────────────────────────
        all_trades_rows: list[dict] = []
        for detail in detail_list:
            tdf = detail.get("trades_df", pd.DataFrame())
            if isinstance(tdf, pd.DataFrame) and not tdf.empty:
                for _, row in tdf.iterrows():
                    all_trades_rows.append({
                        "전략":    detail.get("strategy_name", "—"),
                        "수익률":  float(row.get("return_rate", 0)),
                        "손익":    float(row.get("profit_loss", 0)),
                    })

        if all_trades_rows:
            st.divider()
            st.subheader("📊 거래별 수익률 분포")
            hist_df = pd.DataFrame(all_trades_rows)
            fig_hist = go.Figure()
            for strat_name in hist_df["전략"].unique():
                subset = hist_df[hist_df["전략"] == strat_name]["수익률"]
                fig_hist.add_trace(go.Histogram(
                    x=subset,
                    name=strat_name,
                    opacity=0.65,
                    nbinsx=20,
                ))
            fig_hist.add_vline(x=0, line_dash="dot", line_color="#555",
                               annotation_text="손익분기")
            fig_hist.update_layout(
                barmode="overlay",
                height=320,
                xaxis_title="거래별 수익률 (%)",
                yaxis_title="빈도",
                legend=dict(orientation="h"),
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig_hist, width="stretch")

    # ════════════════════════════════════════════════════════════
    # Tab 4: 손실 거래 목록
    # ════════════════════════════════════════════════════════════
    with tab_loss:
        st.subheader("❌ 손실 거래 목록")
        st.caption("수익률 기준 손실(음수) 거래를 모아 표시합니다.")

        loss_rows: list[dict] = []
        for detail in detail_list:
            tdf = detail.get("trades_df", pd.DataFrame())
            if not isinstance(tdf, pd.DataFrame) or tdf.empty:
                continue
            if "profit_loss" not in tdf.columns:
                continue
            loss_tdf = tdf[tdf["profit_loss"] < 0].copy()
            for _, row in loss_tdf.iterrows():
                loss_rows.append({
                    "전략":      detail.get("strategy_name", "—"),
                    "종목명":    str(row.get("stock_name", row.get("stock_code", "—"))),
                    "종목코드":  str(row.get("stock_code", "—")),
                    "진입일":    str(row.get("entry_date", ""))[:10],
                    "청산일":    str(row.get("exit_date",  row.get("updated_at", "")))[:10],
                    "수량(주)":  int(row.get("quantity", 0)),
                    "진입단가":  float(row.get("entry_price",   0)),
                    "청산단가":  float(row.get("current_price", row.get("exit_price", 0))),
                    "손익(원)":  float(row.get("profit_loss",   0)),
                    "수익률(%)": float(row.get("return_rate",   0)),
                    "보유일":    int(row.get("holding_days",    0)),
                    "상태":      str(row.get("status", "손절")),
                })

        if not loss_rows:
            st.success("✅ 손실 거래가 없습니다.", icon="🎉")
        else:
            loss_df = pd.DataFrame(loss_rows).sort_values("수익률(%)")

            # 손실 요약
            ls1, ls2, ls3, ls4 = st.columns(4)
            ls1.metric("손실 거래 수",   f"{len(loss_df)}건")
            ls2.metric("총 손실 금액",   f"{loss_df['손익(원)'].sum():,.0f}원")
            ls3.metric("평균 손실률",    f"{loss_df['수익률(%)'].mean():+.2f}%")
            ls4.metric("최대 단일 손실", f"{loss_df['손익(원)'].min():,.0f}원")

            # 전략별 손실 건수 필터
            loss_strats = ["전체"] + sorted(loss_df["전략"].unique().tolist())
            sel_loss_strat = st.selectbox("전략 필터", loss_strats, key="loss_strat_filter")
            view_loss = loss_df if sel_loss_strat == "전체" else loss_df[loss_df["전략"] == sel_loss_strat]

            styled_loss = (
                view_loss.style
                .format({
                    "진입단가":  "{:,.0f}원",
                    "청산단가":  "{:,.0f}원",
                    "손익(원)":  "{:+,.0f}원",
                    "수익률(%)": "{:+.2f}%",
                })
                .map(lambda _: "color:#E74C3C;font-weight:bold",
                     subset=["손익(원)", "수익률(%)"])
            )
            st.dataframe(styled_loss, width="stretch", height=400, hide_index=True)

            # 손실 원인 분포 차트
            with st.expander("📊 손실 원인 분포"):
                status_dist = view_loss["상태"].value_counts().reset_index()
                status_dist.columns = ["상태", "건수"]
                status_colors = {"손절": "#E74C3C", "청산": "#F39C12", "기간만료": "#95A5A6"}
                fig_loss_dist = px.bar(
                    status_dist, x="상태", y="건수",
                    color="상태",
                    color_discrete_map=status_colors,
                    text="건수",
                )
                fig_loss_dist.update_traces(textposition="outside")
                fig_loss_dist.update_layout(
                    height=240, showlegend=False,
                    margin=dict(l=0, r=0, t=10, b=0),
                )
                st.plotly_chart(fig_loss_dist, width="stretch")

    # ── 요약 텍스트 (접기) ─────────────────────────────────────
    with st.expander("📋 전략 성과 전체 요약 (텍스트)"):
        st.code(perf.get("summary_text", "요약 없음"), language=None)


# ════════════════════════════════════════════════════════════════
# 화면 8 – 백테스트
# ════════════════════════════════════════════════════════════════
def render_backtest(market_df: pd.DataFrame) -> None:
    _render_menu_title(
        "🧪 백테스트",
        "과거 데이터로 전략을 재현해 수익률, 낙폭, 거래 빈도, 청산 유형을 사전 점검합니다.",
    )

    # ── 투자 참고 안내 배너 ────────────────────────────────────
    st.info(
        "📌 **투자 참고용 안내**: 이 백테스트는 과거 일봉 데이터 기반의 시뮬레이션 결과입니다.  \n"
        "과거 성과가 미래 수익을 보장하지 않으며, 실제 투자 판단에 직접 활용하지 마십시오.  \n"
        "수수료·세금은 단순 비율로 반영되며, 슬리피지·유동성 제약은 고려되지 않습니다.",
        icon="⚠️",
    )

    # ── 전략 목록 로드 ─────────────────────────────────────────
    strategy_options: list[str] = []
    try:
        from strategy.strategy_rules import load_strategy_rules
        rules = load_strategy_rules(active_only=False)
        strategy_options = [r["strategy_name"] for r in rules if r.get("strategy_name")]
    except Exception:
        pass
    if not strategy_options:
        strategy_options = ["v3_score_momentum", "거래량_급증_모멘텀", "뉴스_호재_단기매매", "안정형_분할매수"]

    # ── 종목 목록 ──────────────────────────────────────────────
    all_codes: list[str] = []
    code_name_map: dict[str, str] = {}
    if not market_df.empty and "stock_code" in market_df.columns:
        for _, r in market_df.iterrows():
            c = str(r["stock_code"]).zfill(6)
            n = str(r.get("stock_name", c))
            all_codes.append(c)
            code_name_map[c] = n

    # ════════════════════════════════════════════════════════════
    # 설정 폼
    # ════════════════════════════════════════════════════════════
    with st.form("bt_form"):
        st.subheader("⚙️ 백테스트 설정")

        fc1, fc2 = st.columns(2)

        with fc1:
            sel_strategy = st.selectbox(
                "전략 선택",
                strategy_options,
                help="백테스트할 전략을 선택합니다.",
            )
            start_date = st.date_input(
                "시작일",
                value=date.today().replace(month=1, day=1),
                min_value=date(2020, 1, 1),
                max_value=date.today(),
            )
            end_date = st.date_input(
                "종료일",
                value=date.today(),
                min_value=date(2020, 1, 2),
                max_value=date.today(),
            )

        with fc2:
            initial_cash = st.number_input(
                "초기 투자금 (원)",
                min_value=1_000_000,
                max_value=1_000_000_000,
                value=10_000_000,
                step=1_000_000,
                format="%d",
                help="백테스트 시뮬레이션에 사용할 가상 초기 자금",
            )
            max_position_amount = st.number_input(
                "종목당 최대 투자금 (원)",
                min_value=100_000,
                max_value=10_000_000,
                value=1_000_000,
                step=100_000,
                format="%d",
            )

            # 대상 종목 선택
            stock_scope = st.radio(
                "대상 종목",
                ["전체 (시장 마스터)", "직접 선택"],
                horizontal=True,
            )

        if stock_scope == "직접 선택" and all_codes:
            stock_display = [f"{n} ({c})" for c, n in code_name_map.items()]
            sel_stocks = st.multiselect(
                "종목 선택 (복수 선택 가능)",
                stock_display,
                default=stock_display[:5],
                help="선택하지 않으면 전체 종목을 대상으로 합니다.",
            )
            selected_codes = [s.split("(")[-1].rstrip(")") for s in sel_stocks]
        else:
            selected_codes = all_codes if all_codes else None

        # 고급 설정
        with st.expander("🔧 고급 설정 (수수료·세금)"):
            adv1, adv2 = st.columns(2)
            with adv1:
                fee_rate = st.number_input(
                    "매수·매도 수수료율 (%)",
                    min_value=0.0, max_value=1.0,
                    value=0.35, step=0.05, format="%.2f",
                    help="매수·매도 각각 적용 (기본 0.35%)",
                ) / 100
            with adv2:
                tax_rate = st.number_input(
                    "증권거래세율 (%)",
                    min_value=0.0, max_value=1.0,
                    value=0.20, step=0.05, format="%.2f",
                    help="매도 시 적용 (기본 0.20%)",
                ) / 100

        submitted = st.form_submit_button(
            "🚀 백테스트 실행",
            type="primary",
            use_container_width=True,
        )

    # ── 입력 검증 ──────────────────────────────────────────────
    if submitted:
        if start_date >= end_date:
            st.error("❌ 시작일은 종료일보다 이전이어야 합니다.")
        elif (end_date - start_date).days < 5:
            st.error("❌ 백테스트 기간이 너무 짧습니다. 최소 5일 이상으로 설정해 주세요.")
        else:
            with st.spinner(f"백테스트 실행 중... ({sel_strategy} / {start_date} ~ {end_date})"):
                try:
                    from analysis.backtester import run_backtest
                    result = run_backtest(
                        strategy_name=sel_strategy,
                        start_date=str(start_date),
                        end_date=str(end_date),
                        initial_cash=float(initial_cash),
                        stock_codes=selected_codes if selected_codes else None,
                        fee_rate=fee_rate,
                        tax_rate=tax_rate,
                        max_position_amount=float(max_position_amount),
                        save_result=True,
                    )
                    st.session_state["bt_result"] = result
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 백테스트 실행 오류: {e}")
                    st.session_state["bt_result"] = None

    # ════════════════════════════════════════════════════════════
    # 결과 표시
    # ════════════════════════════════════════════════════════════
    result = st.session_state.get("bt_result")
    if result is None:
        st.divider()
        st.caption("⬆️ 설정을 입력하고 실행 버튼을 눌러 백테스트를 시작하세요.")
        return

    st.divider()
    st.subheader(
        f"📊 백테스트 결과 — {result.get('strategy_name', '')}  "
        f"({result.get('start_date', '')} ~ {result.get('end_date', '')})"
    )

    # ── 데이터 부족 / 거래 없음 처리 ──────────────────────────
    total_trades = int(result.get("total_trades", 0))
    if total_trades == 0:
        st.warning(
            "⚠️ **데이터 부족 또는 신호 없음**  \n"
            "선택한 기간·전략·종목 조건에서 매수 신호가 발생하지 않았습니다.  \n"
            "• 기간을 늘리거나, 다른 전략을 선택해 보세요.  \n"
            "• 사이드바 [📈 종목 데이터] 버튼으로 일봉 데이터를 업데이트한 후 재시도하세요.",
            icon="📭",
        )
        return

    # ── KPI 카드 ───────────────────────────────────────────────
    initial  = float(result.get("initial_cash",      10_000_000))
    final    = float(result.get("final_asset",        initial))
    tot_ret  = float(result.get("total_return_rate",  0.0))
    win_rate = float(result.get("win_rate",            0.0))
    mdd      = float(result.get("max_drawdown",        0.0))
    pf       = float(result.get("profit_factor",       0.0))
    avg_ret  = float(result.get("avg_return_rate",     0.0))
    net_pnl  = float(result.get("total_net_pnl",       0.0))
    wins     = int(result.get("win_trades",            0))
    losses   = int(result.get("lose_trades",           0))
    avg_hold = float(result.get("avg_holding_days",    0.0))

    pnl_delta_color = "normal" if net_pnl >= 0 else "inverse"

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "최종 자산",
        f"{final:,.0f}원",
        delta=f"{net_pnl:+,.0f}원",
        delta_color=pnl_delta_color,
    )
    k2.metric(
        "총 수익률",
        f"{tot_ret:+.2f}%",
        help=f"초기 {initial:,.0f}원 기준",
    )
    k3.metric(
        "승률",
        f"{win_rate:.1f}%",
        delta=f"승 {wins} / 패 {losses}",
    )
    k4.metric(
        "총 거래 수",
        f"{total_trades}건",
        help=f"평균 보유 {avg_hold:.1f}일",
    )

    k5, k6, k7, k8 = st.columns(4)
    k5.metric("평균 수익률",  f"{avg_ret:+.2f}%")
    k6.metric("최대 낙폭",    f"{mdd:.2f}%")
    k7.metric("손익비",       f"{pf:.2f}",
              help="총 수익 ÷ 총 손실 (2.0 이상 우수)")
    k8.metric("평균 보유일",  f"{avg_hold:.1f}일")

    st.divider()

    # ── 탭 ────────────────────────────────────────────────────
    tab_curve, tab_dist, tab_trades, tab_saved = st.tabs([
        "📈 손익 곡선",
        "📊 수익률 분포",
        "📋 거래 내역",
        "💾 저장된 결과",
    ])

    trades_df = result.get("trades_df", pd.DataFrame())
    equity_series = result.get("equity_series", [])
    exit_counts   = result.get("exit_counts",   {})

    # ── Tab 1: 손익 곡선 ──────────────────────────────────────
    with tab_curve:
        st.subheader("📈 누적 손익 곡선 (자산 추이)")

        if equity_series:
            eq_df = pd.DataFrame(equity_series)
            eq_df["entry_date"] = eq_df["entry_date"].astype(str).str[:10]

            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(
                x=eq_df["entry_date"],
                y=eq_df["equity"],
                mode="lines+markers",
                name="자산 추이",
                line=dict(color="#2980B9", width=2.5),
                marker=dict(size=5),
                fill="tozeroy",
                fillcolor="rgba(41,128,185,0.08)",
            ))
            fig_eq.add_hline(
                y=initial,
                line_dash="dash",
                line_color="#888",
                annotation_text=f"초기 자금 {initial:,.0f}원",
                annotation_position="right",
            )
            # 고점·저점 마커
            if not eq_df.empty:
                max_idx = eq_df["equity"].idxmax()
                min_idx = eq_df["equity"].idxmin()
                fig_eq.add_trace(go.Scatter(
                    x=[eq_df.loc[max_idx, "entry_date"]],
                    y=[eq_df.loc[max_idx, "equity"]],
                    mode="markers+text",
                    marker=dict(color="#27AE60", size=10, symbol="triangle-up"),
                    text=[f"고점 {eq_df.loc[max_idx,'equity']:,.0f}원"],
                    textposition="top center",
                    showlegend=False,
                ))
                fig_eq.add_trace(go.Scatter(
                    x=[eq_df.loc[min_idx, "entry_date"]],
                    y=[eq_df.loc[min_idx, "equity"]],
                    mode="markers+text",
                    marker=dict(color="#E74C3C", size=10, symbol="triangle-down"),
                    text=[f"저점 {eq_df.loc[min_idx,'equity']:,.0f}원"],
                    textposition="bottom center",
                    showlegend=False,
                ))
            fig_eq.update_layout(
                height=400,
                xaxis_title="날짜",
                yaxis_title="자산 (원)",
                yaxis=dict(tickformat=",.0f"),
                margin=dict(l=0, r=0, t=10, b=40),
                hovermode="x unified",
                showlegend=False,
            )
            st.plotly_chart(fig_eq, width="stretch")
        else:
            st.info("누적 손익 데이터 없음")

        # MDD 낙폭 구간 차트
        if equity_series:
            st.subheader("📉 낙폭 추이")
            mdd_df = pd.DataFrame(equity_series)
            mdd_df["entry_date"] = mdd_df["entry_date"].astype(str).str[:10]
            if "equity" in mdd_df.columns:
                mdd_df["peak"]         = mdd_df["equity"].cummax()
                mdd_df["drawdown_pct"] = (mdd_df["equity"] - mdd_df["peak"]) / mdd_df["peak"] * 100
                fig_dd = go.Figure(go.Scatter(
                    x=mdd_df["entry_date"],
                    y=mdd_df["drawdown_pct"],
                    mode="lines",
                    fill="tozeroy",
                    fillcolor="rgba(231,76,60,0.18)",
                    line=dict(color="#E74C3C", width=1.5),
                    name="낙폭(%)",
                ))
                fig_dd.add_hline(y=0, line_color="#888", line_width=1)
                fig_dd.update_layout(
                    height=220,
                    xaxis_title="날짜",
                    yaxis_title="낙폭 (%)",
                    margin=dict(l=0, r=0, t=10, b=40),
                    showlegend=False,
                    hovermode="x unified",
                )
                st.plotly_chart(fig_dd, width="stretch")

    # ── Tab 2: 수익률 분포 ────────────────────────────────────
    with tab_dist:
        if not isinstance(trades_df, pd.DataFrame) or trades_df.empty:
            st.info("분포 차트를 표시할 거래 데이터 없음")
        else:
            ch1, ch2 = st.columns(2)

            with ch1:
                st.subheader("📊 거래별 수익률 분포")
                returns = trades_df["return_rate"].dropna().tolist() if "return_rate" in trades_df.columns else []
                if returns:
                    fig_hist = go.Figure(go.Histogram(
                        x=returns,
                        nbinsx=20,
                        marker_color=[
                            "#27AE60" if v >= 0 else "#E74C3C" for v in returns
                        ],
                        opacity=0.8,
                        name="수익률",
                    ))
                    fig_hist.add_vline(x=0, line_dash="dash", line_color="#555",
                                       annotation_text="손익분기")
                    avg_r = sum(returns) / len(returns)
                    fig_hist.add_vline(x=avg_r, line_dash="dot",
                                       line_color="#F39C12",
                                       annotation_text=f"평균 {avg_r:+.2f}%",
                                       annotation_position="top right")
                    fig_hist.update_layout(
                        height=320,
                        xaxis_title="수익률 (%)",
                        yaxis_title="거래 수",
                        margin=dict(l=0, r=0, t=10, b=40),
                        showlegend=False,
                    )
                    st.plotly_chart(fig_hist, width="stretch")

            with ch2:
                st.subheader("🎯 청산 유형 분포")
                if exit_counts:
                    exit_labels = list(exit_counts.keys())
                    exit_vals   = list(exit_counts.values())
                    exit_colors = {
                        "익절":   "#27AE60",
                        "손절":   "#E74C3C",
                        "기간만료": "#F39C12",
                        "데이터부족": "#95A5A6",
                    }
                    fig_exit = go.Figure(go.Pie(
                        labels=exit_labels,
                        values=exit_vals,
                        marker_colors=[exit_colors.get(l, "#888") for l in exit_labels],
                        textinfo="label+percent+value",
                        hole=0.40,
                    ))
                    fig_exit.update_layout(
                        height=320,
                        showlegend=True,
                        margin=dict(l=0, r=0, t=10, b=10),
                    )
                    st.plotly_chart(fig_exit, width="stretch")
                else:
                    st.info("청산 유형 데이터 없음")

            # 거래별 수익률 산점도 (날짜 × 수익률)
            if "entry_date" in trades_df.columns and "return_rate" in trades_df.columns:
                st.divider()
                st.subheader("🗓️ 날짜별 개별 거래 수익률")
                scatter_df = trades_df[["entry_date", "return_rate", "stock_name"]].copy()
                scatter_df["entry_date"] = scatter_df["entry_date"].astype(str).str[:10]
                scatter_df["color"] = scatter_df["return_rate"].apply(
                    lambda v: "#27AE60" if v >= 0 else "#E74C3C"
                )
                fig_sc = go.Figure()
                for _, row in scatter_df.iterrows():
                    fig_sc.add_trace(go.Scatter(
                        x=[row["entry_date"]],
                        y=[row["return_rate"]],
                        mode="markers",
                        marker=dict(color=row["color"], size=9, opacity=0.75),
                        name=str(row.get("stock_name", "")),
                        showlegend=False,
                        hovertemplate=(
                            f"<b>{row.get('stock_name','')}</b><br>"
                            f"날짜: {row['entry_date']}<br>"
                            f"수익률: {row['return_rate']:+.2f}%"
                            "<extra></extra>"
                        ),
                    ))
                fig_sc.add_hline(y=0, line_dash="dash", line_color="#888")
                fig_sc.update_layout(
                    height=280,
                    xaxis_title="진입일",
                    yaxis_title="수익률 (%)",
                    margin=dict(l=0, r=0, t=10, b=40),
                    hovermode="closest",
                )
                st.plotly_chart(fig_sc, width="stretch")

    # ── Tab 3: 거래 내역 ──────────────────────────────────────
    with tab_trades:
        st.subheader("📋 백테스트 거래 내역")

        if not isinstance(trades_df, pd.DataFrame) or trades_df.empty:
            st.info("거래 내역이 없습니다.")
        else:
            # 필터
            tf1, tf2 = st.columns(2)
            with tf1:
                reason_opts = ["전체"] + sorted(
                    trades_df["exit_reason"].dropna().unique().tolist()
                ) if "exit_reason" in trades_df.columns else ["전체"]
                sel_reason = st.selectbox("청산 유형 필터", reason_opts, key="bt_reason_filter")
            with tf2:
                win_only = st.checkbox("수익 거래만 보기", value=False, key="bt_win_only")

            view_td = trades_df.copy()
            if sel_reason != "전체" and "exit_reason" in view_td.columns:
                view_td = view_td[view_td["exit_reason"] == sel_reason]
            if win_only and "net_profit_loss" in view_td.columns:
                view_td = view_td[view_td["net_profit_loss"] > 0]

            show_cols = [c for c in [
                "stock_name", "stock_code", "signal_date", "entry_date",
                "entry_price", "exit_date", "exit_price", "exit_reason",
                "quantity", "profit_loss", "net_profit_loss",
                "return_rate", "holding_days",
            ] if c in view_td.columns]

            rename_bt = {
                "stock_name":     "종목명",
                "stock_code":     "코드",
                "signal_date":    "신호일",
                "entry_date":     "진입일",
                "entry_price":    "진입가(원)",
                "exit_date":      "청산일",
                "exit_price":     "청산가(원)",
                "exit_reason":    "청산유형",
                "quantity":       "수량",
                "profit_loss":    "손익(원)",
                "net_profit_loss": "순손익(원)",
                "return_rate":    "수익률(%)",
                "holding_days":   "보유일",
            }
            display_td = view_td[show_cols].rename(columns=rename_bt)

            def _color_ret(val):
                try:
                    v = float(val)
                    if v > 0: return "color:#27AE60;font-weight:bold"
                    if v < 0: return "color:#E74C3C;font-weight:bold"
                except (TypeError, ValueError):
                    pass
                return ""

            styled_td = display_td.style
            for col in ["수익률(%)", "손익(원)", "순손익(원)"]:
                if col in display_td.columns:
                    styled_td = styled_td.map(_color_ret, subset=[col])
            fmt = {}
            for col in ["진입가(원)", "청산가(원)"]:
                if col in display_td.columns:
                    fmt[col] = "{:,.0f}"
            for col in ["손익(원)", "순손익(원)"]:
                if col in display_td.columns:
                    fmt[col] = "{:+,.0f}"
            if "수익률(%)" in display_td.columns:
                fmt["수익률(%)"] = "{:+.2f}%"
            if fmt:
                styled_td = styled_td.format(fmt)

            st.dataframe(styled_td, width="stretch", height=440, hide_index=True)

            tc1, tc2 = st.columns(2)
            tc1.caption(f"표시 거래: {len(display_td)}건 / 전체 {total_trades}건")
            if "net_profit_loss" in view_td.columns:
                subset_pnl = float(view_td["net_profit_loss"].sum())
                tc2.caption(f"필터 구간 순손익: {subset_pnl:+,.0f}원")

    # ── Tab 4: 저장된 결과 ────────────────────────────────────
    with tab_saved:
        st.subheader("💾 저장된 백테스트 결과")

        saved_results: list[dict] = []
        try:
            from services.supabase_client import is_connected, get_client
            if is_connected():
                rows = (
                    get_client()
                    .table("backtest_results")
                    .select("id,strategy_name,start_date,end_date,initial_cash,"
                            "final_asset,total_return_rate,win_rate,max_drawdown,"
                            "total_trades,created_at")
                    .order("created_at", desc=True)
                    .limit(30)
                    .execute()
                    .data or []
                )
                saved_results = rows
        except Exception:
            pass

        # Supabase 미연결 시 로컬 JSON 폴백
        if not saved_results:
            from pathlib import Path as _Path
            _bt_file = _Path(__file__).parent / "data" / "backtest_results.json"
            if _bt_file.exists():
                try:
                    import json as _json
                    saved_results = _json.loads(_bt_file.read_text(encoding="utf-8"))
                    # 최신순 30건
                    saved_results = sorted(
                        saved_results,
                        key=lambda x: str(x.get("created_at", "")),
                        reverse=True,
                    )[:30]
                except Exception:
                    pass

        if not saved_results:
            st.info("저장된 백테스트 결과가 없습니다.  백테스트를 실행하면 자동으로 저장됩니다.")
        else:
            saved_df = pd.DataFrame(saved_results)
            display_sv_cols = [c for c in [
                "id", "strategy_name", "start_date", "end_date",
                "initial_cash", "final_asset",
                "total_return_rate", "win_rate", "max_drawdown",
                "total_trades", "created_at",
            ] if c in saved_df.columns]
            rename_sv = {
                "id":                "ID",
                "strategy_name":     "전략명",
                "start_date":        "시작일",
                "end_date":          "종료일",
                "initial_cash":      "초기자금(원)",
                "final_asset":       "최종자산(원)",
                "total_return_rate": "수익률(%)",
                "win_rate":          "승률(%)",
                "max_drawdown":      "MDD(%)",
                "total_trades":      "거래수",
                "created_at":        "실행일시",
            }

            def _color_tr(val):
                try:
                    v = float(val)
                    if v > 0: return "color:#27AE60;font-weight:bold"
                    if v < 0: return "color:#E74C3C;font-weight:bold"
                except (TypeError, ValueError):
                    pass
                return ""

            display_sv = saved_df[display_sv_cols].rename(columns=rename_sv)
            styled_sv  = display_sv.style
            if "수익률(%)" in display_sv.columns:
                styled_sv = styled_sv.map(_color_tr, subset=["수익률(%)"])
                styled_sv = styled_sv.format({"수익률(%)": "{:+.2f}%", "승률(%)": "{:.1f}%"})
            if "초기자금(원)" in display_sv.columns:
                styled_sv = styled_sv.format({
                    "초기자금(원)": "{:,.0f}",
                    "최종자산(원)": "{:,.0f}",
                })

            st.dataframe(styled_sv, width="stretch", height=360, hide_index=True)
            st.caption(f"최근 {len(saved_results)}건 표시")

    # ── 요약 텍스트 ───────────────────────────────────────────
    st.divider()
    with st.expander("📋 백테스트 결과 전체 요약 (텍스트)"):
        st.code(result.get("summary_text", "요약 없음"), language=None)

    # ── 새 백테스트 실행 안내 ─────────────────────────────────
    if st.button("🔄 새 백테스트 실행 (결과 초기화)", key="bt_clear_btn"):
        st.session_state["bt_result"] = None
        st.rerun()

    st.caption(
        "⚠️ 이 결과는 과거 데이터 기반 시뮬레이션이며 투자 참고용으로만 활용하십시오.  "
        "실제 투자 성과와 다를 수 있으며, 투자 손실에 대한 책임은 본인에게 있습니다."
    )


# ════════════════════════════════════════════════════════════════
# 화면 9 – 주문 승인
# ════════════════════════════════════════════════════════════════
def render_order_approval() -> None:
    """주문 후보 승인 / 거절 / 모의투자 전송 화면 (8단계)."""

    _render_menu_title(
        "✅ 주문 승인",
        "매매 신호로 생성된 주문 후보를 검토하고, 리스크 확인 후 수동 승인·모의전송만 진행합니다.",
    )

    # ── 서비스 import (없으면 안내만 표시) ──────────────────────
    try:
        from services.system_settings import get_status_summary
        from services.order_intent_service import (
            get_order_intents,
            approve_order_intent,
            reject_order_intent,
        )
        from services.kiwoom_order import (
            send_paper_buy_order,
            send_paper_sell_order,
        )
        _services_ok = True
    except ImportError as _e:
        st.error(f"서비스 모듈 로드 실패: {_e}")
        _services_ok = False

    if not _services_ok:
        return

    # ══════════════════════════════════════════════════════════
    # 시스템 상태 패널
    # ══════════════════════════════════════════════════════════
    try:
        sys = get_status_summary()
    except Exception:
        sys = {
            "trading_mode":    "analysis_only",
            "mode_label":      "분석 전용",
            "mode_color":      "#5DADE2",
            "emergency_stop":  False,
            "manual_approval": True,
            "trading_allowed": False,
        }

    mode_label  = sys.get("mode_label",      "분석 전용")
    mode_color  = sys.get("mode_color",      "#5DADE2")
    e_stop      = bool(sys.get("emergency_stop",  False))
    req_approval = bool(sys.get("manual_approval", True))
    trading_ok  = bool(sys.get("trading_allowed", False))

    # 상태 카드 3열
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.markdown(
            f"<div style='background:{mode_color}22;border:2px solid {mode_color};"
            f"border-radius:10px;padding:12px;text-align:center'>"
            f"<div style='font-size:11px;color:{mode_color};font-weight:bold'>현재 거래 모드</div>"
            f"<div style='font-size:20px;font-weight:bold;color:{mode_color}'>{mode_label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with sc2:
        e_color = "#E74C3C" if e_stop else "#27AE60"
        e_icon  = "🚨 활성" if e_stop else "✅ 정상"
        st.markdown(
            f"<div style='background:{e_color}22;border:2px solid {e_color};"
            f"border-radius:10px;padding:12px;text-align:center'>"
            f"<div style='font-size:11px;color:{e_color};font-weight:bold'>긴급 중지</div>"
            f"<div style='font-size:20px;font-weight:bold;color:{e_color}'>{e_icon}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with sc3:
        ap_color = "#F39C12" if req_approval else "#27AE60"
        ap_label = "필수" if req_approval else "불필요"
        st.markdown(
            f"<div style='background:{ap_color}22;border:2px solid {ap_color};"
            f"border-radius:10px;padding:12px;text-align:center'>"
            f"<div style='font-size:11px;color:{ap_color};font-weight:bold'>수동 승인</div>"
            f"<div style='font-size:20px;font-weight:bold;color:{ap_color}'>{ap_label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("")

    # ── 고정 경고 배너 ───────────────────────────────────────────
    st.error(
        "⛔  실거래 주문은 이 시스템에서 영구적으로 차단됩니다.  "
        "모의투자(paper) 또는 Mock 모드 전용입니다.  "
        "실제 자산에 영향을 주는 주문은 절대 발생하지 않습니다.",
        icon="🚫",
    )

    if e_stop:
        st.warning(
            "🚨 긴급 중지가 활성화되어 있습니다. 주문 승인 및 전송이 모두 차단됩니다. "
            "해제하려면 시스템 설정에서 긴급 중지를 OFF 하세요.",
        )

    if sys.get("trading_mode") == "analysis_only":
        st.info(
            "ℹ️ 현재 '분석 전용' 모드입니다. 주문 전송을 하려면 시스템 설정에서 "
            "'모의투자' 모드로 전환하세요.",
        )

    # ── 액션 결과 메시지 ────────────────────────────────────────
    action_msg = st.session_state.get("order_action_msg")
    if action_msg:
        level, text = action_msg
        if level == "success":
            st.success(text)
        elif level == "error":
            st.error(text)
        else:
            st.warning(text)
        st.session_state["order_action_msg"] = None

    st.divider()

    # ══════════════════════════════════════════════════════════
    # 탭 구성
    # ══════════════════════════════════════════════════════════
    tab_pending, tab_approved, tab_log = st.tabs([
        "📋 승인 대기",
        "✅ 전송 대기 (승인됨)",
        "📜 전송 결과 로그",
    ])

    # ──────────────────────────────────────────────────────────
    # TAB 1 — 승인 대기
    # ──────────────────────────────────────────────────────────
    with tab_pending:
        try:
            pending = get_order_intents(status="승인대기", limit=50)
        except Exception as _e:
            st.error(f"승인 대기 주문 조회 실패: {_e}")
            pending = []

        if not pending:
            st.info("📭 승인 대기 중인 주문이 없습니다.")
        else:
            st.caption(f"총 {len(pending)}건의 승인 대기 주문")
            for intent in pending:
                _render_pending_intent_card(
                    intent,
                    approve_order_intent,
                    reject_order_intent,
                    e_stop,
                )

    # ──────────────────────────────────────────────────────────
    # TAB 2 — 전송 대기 (승인됨)
    # ──────────────────────────────────────────────────────────
    with tab_approved:
        try:
            approved = get_order_intents(status="승인", limit=50)
        except Exception as _e:
            st.error(f"승인 완료 주문 조회 실패: {_e}")
            approved = []

        if not approved:
            st.info("📭 전송 대기 중인 승인 주문이 없습니다.")
        else:
            st.caption(f"총 {len(approved)}건 — 아래 [전송] 버튼으로 모의투자 API에 전송합니다.")
            for intent in approved:
                _render_approved_intent_card(
                    intent,
                    send_paper_buy_order,
                    send_paper_sell_order,
                    trading_ok,
                    e_stop,
                )

    # ──────────────────────────────────────────────────────────
    # TAB 3 — 전송 결과 로그
    # ──────────────────────────────────────────────────────────
    with tab_log:
        _render_broker_orders_log()


# ════════════════════════════════════════════════════════════════
# 주문 승인 화면 서브 렌더러
# ════════════════════════════════════════════════════════════════

def _risk_badge(status: str) -> str:
    """리스크 검사 상태 뱃지 HTML."""
    _c = {"통과": "#27AE60", "확인필요": "#F39C12", "차단": "#E74C3C", "확인필요(기본)": "#95A5A6"}
    c  = _c.get(status, "#888")
    return (
        f"<span style='background:{c};color:white;padding:2px 10px;"
        f"border-radius:6px;font-weight:bold;font-size:12px'>{status}</span>"
    )


def _order_type_badge(order_type: str) -> str:
    c = "#E74C3C" if order_type == "매수" else "#2980B9"
    return (
        f"<span style='background:{c};color:white;padding:2px 8px;"
        f"border-radius:5px;font-weight:bold;font-size:13px'>{order_type}</span>"
    )


def _render_pending_intent_card(
    intent: dict,
    approve_fn,
    reject_fn,
    e_stop: bool,
) -> None:
    """승인 대기 주문 카드 1건 렌더링."""
    intent_id    = intent.get("id")
    stock_code   = str(intent.get("stock_code", ""))
    stock_name   = str(intent.get("stock_name", "") or "")
    order_type   = str(intent.get("order_type", ""))
    order_price  = int(intent.get("order_price", 0) or 0)
    quantity     = int(intent.get("quantity", 0) or 0)
    order_amount = int(intent.get("order_amount", 0) or 0)
    risk_status  = str(intent.get("risk_check_status", "확인필요") or "확인필요")
    risk_msg     = str(intent.get("risk_check_message", "") or "")
    strategy     = str(intent.get("strategy_name", "") or "")
    created_at   = str(intent.get("created_at", ""))[:16]

    is_blocked   = (risk_status == "차단")

    with st.container(border=True):
        h1, h2 = st.columns([3, 1])
        with h1:
            st.markdown(
                f"{_order_type_badge(order_type)}&nbsp;&nbsp;"
                f"<b style='font-size:16px'>{stock_name}</b> "
                f"<span style='color:#888;font-size:13px'>({stock_code})</span>",
                unsafe_allow_html=True,
            )
        with h2:
            st.markdown(
                _risk_badge(risk_status),
                unsafe_allow_html=True,
            )

        # 주문 세부 정보
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("주문 수량",  f"{quantity:,}주")
        d2.metric("주문 단가",  f"{order_price:,}원")
        d3.metric("주문 금액",  f"{order_amount:,}원")
        d4.metric("전략",       strategy or "-")
        st.caption(f"생성: {created_at}")

        # 리스크 검사 결과 상세
        if risk_msg:
            with st.expander("🔍 리스크 검사 상세"):
                if is_blocked:
                    st.error(f"차단 사유: {risk_msg}")
                elif risk_status == "확인필요":
                    st.warning(f"주의 항목: {risk_msg}")
                else:
                    st.success(risk_msg)

        if is_blocked:
            st.error(
                "🚫 리스크 검사 결과 **차단** 상태입니다. 이 주문은 승인할 수 없습니다.  "
                "주문 조건을 검토하거나 [거절] 처리하세요.",
            )

        # 버튼 영역
        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 3])

        # [승인] 버튼
        with btn_col1:
            approve_disabled = is_blocked or e_stop
            approve_tip = (
                "리스크 차단 주문은 승인할 수 없습니다." if is_blocked else
                "긴급 중지 활성 상태입니다." if e_stop else
                None
            )
            if approve_tip:
                st.button(
                    "✅ 승인",
                    key=f"approve_{intent_id}",
                    disabled=True,
                    help=approve_tip,
                    use_container_width=True,
                )
            elif st.button(
                "✅ 승인",
                key=f"approve_{intent_id}",
                type="primary",
                use_container_width=True,
            ):
                result = approve_fn(intent_id)
                if result["success"]:
                    st.session_state["order_action_msg"] = (
                        "success",
                        f"✅ {stock_name}({stock_code}) {order_type} 주문이 승인되었습니다. "
                        f"'전송 대기' 탭에서 전송하세요.",
                    )
                else:
                    st.session_state["order_action_msg"] = ("error", f"승인 실패: {result['message']}")
                st.rerun()

        # [거절] 버튼
        with btn_col2:
            reject_key = f"reject_btn_{intent_id}"
            if st.button("❌ 거절", key=reject_key, use_container_width=True):
                st.session_state["reject_pending_id"] = intent_id
                st.rerun()

        # 거절 사유 입력 (이 intent가 거절 대기 중일 때)
        if st.session_state.get("reject_pending_id") == intent_id:
            st.markdown("---")
            reason = st.text_input(
                "거절 사유 (선택)",
                placeholder="예: 리스크 검토 후 기회 없음",
                key=f"reject_reason_{intent_id}",
            )
            rc1, rc2, _ = st.columns([1, 1, 3])
            with rc1:
                if st.button("확인", key=f"reject_confirm_{intent_id}", type="primary"):
                    result = reject_fn(intent_id, reason)
                    st.session_state["reject_pending_id"] = None
                    if result["success"]:
                        st.session_state["order_action_msg"] = (
                            "warning",
                            f"❌ {stock_name}({stock_code}) {order_type} 주문이 거절되었습니다.",
                        )
                    else:
                        st.session_state["order_action_msg"] = ("error", f"거절 실패: {result['message']}")
                    st.rerun()
            with rc2:
                if st.button("취소", key=f"reject_cancel_{intent_id}"):
                    st.session_state["reject_pending_id"] = None
                    st.rerun()


def _render_approved_intent_card(
    intent:       dict,
    buy_fn,
    sell_fn,
    trading_ok:   bool,
    e_stop:       bool,
) -> None:
    """승인된 주문 카드 1건 + 전송 버튼 렌더링."""
    intent_id    = intent.get("id")
    stock_code   = str(intent.get("stock_code", ""))
    stock_name   = str(intent.get("stock_name", "") or "")
    order_type   = str(intent.get("order_type", ""))
    order_price  = int(intent.get("order_price", 0) or 0)
    quantity     = int(intent.get("quantity", 0) or 0)
    order_amount = int(intent.get("order_amount", 0) or 0)
    approved_at  = str(intent.get("approved_at", "") or "")[:16]

    with st.container(border=True):
        h1, h2 = st.columns([3, 1])
        with h1:
            st.markdown(
                f"{_order_type_badge(order_type)}&nbsp;&nbsp;"
                f"<b style='font-size:16px'>{stock_name}</b> "
                f"<span style='color:#888;font-size:13px'>({stock_code})</span>",
                unsafe_allow_html=True,
            )
        with h2:
            st.markdown(
                "<span style='background:#27AE60;color:white;padding:2px 10px;"
                "border-radius:6px;font-weight:bold;font-size:12px'>승인됨</span>",
                unsafe_allow_html=True,
            )

        d1, d2, d3 = st.columns(3)
        d1.metric("주문 수량", f"{quantity:,}주")
        d2.metric("주문 단가", f"{order_price:,}원")
        d3.metric("주문 금액", f"{order_amount:,}원")
        if approved_at:
            st.caption(f"승인 일시: {approved_at}")

        # 전송 버튼
        send_disabled = (not trading_ok) or e_stop
        send_tip: str | None = None
        if e_stop:
            send_tip = "긴급 중지 활성 상태입니다."
        elif not trading_ok:
            send_tip = "모의투자 모드에서만 전송 가능합니다. 시스템 설정을 확인하세요."

        bc1, bc2 = st.columns([1, 4])
        with bc1:
            if send_tip:
                st.button(
                    "📡 주문 전송",
                    key=f"send_{intent_id}",
                    disabled=True,
                    help=send_tip,
                    use_container_width=True,
                )
            elif st.button(
                "📡 주문 전송",
                key=f"send_{intent_id}",
                type="primary",
                use_container_width=True,
            ):
                with st.spinner(f"{stock_name} {order_type} 주문 전송 중..."):
                    fn = buy_fn if order_type == "매수" else sell_fn
                    result = fn(intent)
                if result["success"]:
                    mock_note = " (Mock)" if result.get("is_mock") else ""
                    bo = result.get("broker_order") or {}
                    ext_no = bo.get("broker_order_id", "-")
                    st.session_state["order_action_msg"] = (
                        "success",
                        f"📡 {stock_name}({stock_code}) {order_type} 전송 완료{mock_note} "
                        f"/ 주문번호: {ext_no}",
                    )
                else:
                    st.session_state["order_action_msg"] = ("error", f"전송 실패: {result['message']}")
                st.rerun()

        if not trading_ok and not e_stop:
            st.info(
                "ℹ️ '모의투자' 모드에서만 주문을 전송할 수 있습니다. "
                "시스템 설정 → trading_mode를 'paper_trading' 으로 변경 후 재시도하세요."
            )


def _render_broker_orders_log() -> None:
    """broker_orders 최근 기록 조회 및 표시."""
    st.subheader("📜 주문 전송 결과")

    # Supabase 또는 로컬 파일에서 로드
    orders: list[dict] = []
    try:
        from services.supabase_client import is_connected, get_client
        if is_connected():
            rows = (
                get_client()
                .table("broker_orders")
                .select("*")
                .order("updated_at", desc=True)
                .limit(30)
                .execute()
                .data or []
            )
            orders = rows
    except Exception:
        pass

    if not orders:
        from pathlib import Path
        import json as _json
        fpath = Path(__file__).parent / "data" / "broker_orders.json"
        if fpath.exists():
            try:
                data = _json.loads(fpath.read_text(encoding="utf-8"))
                orders = sorted(data, key=lambda x: x.get("updated_at", ""), reverse=True)[:30]
            except Exception:
                pass

    if not orders:
        st.info("📭 전송된 주문 기록이 없습니다.")
        return

    # 테이블 표시
    _STATUS_COLOR = {
        "전송대기":  "#F39C12",
        "전송완료":  "#2980B9",
        "일부체결":  "#8E44AD",
        "전량체결":  "#27AE60",
        "취소":     "#95A5A6",
        "실패":     "#E74C3C",
    }

    for order in orders:
        o_status = str(order.get("order_status", ""))
        o_type   = str(order.get("order_type", ""))
        o_code   = str(order.get("stock_code", ""))
        o_name   = str(order.get("stock_name", "") or o_code)
        o_mode   = str(order.get("account_mode", ""))
        o_price  = int(order.get("order_price", 0) or 0)
        o_qty    = int(order.get("quantity", 0) or 0)
        o_ext    = str(order.get("broker_order_id", "-") or "-")
        o_time   = str(order.get("sent_at", "") or order.get("updated_at", ""))[:16]
        is_mock  = o_mode == "mock"

        s_color = _STATUS_COLOR.get(o_status, "#888")

        with st.container(border=True):
            lc, rc = st.columns([4, 1])
            with lc:
                st.markdown(
                    f"{_order_type_badge(o_type)}&nbsp;&nbsp;"
                    f"<b>{o_name}</b> <span style='color:#888;font-size:12px'>({o_code})</span>"
                    f"{'&nbsp;<span style=\"background:#888;color:white;padding:1px 6px;border-radius:4px;font-size:11px\">MOCK</span>' if is_mock else ''}",
                    unsafe_allow_html=True,
                )
            with rc:
                st.markdown(
                    f"<span style='background:{s_color};color:white;padding:2px 8px;"
                    f"border-radius:5px;font-weight:bold;font-size:12px'>{o_status}</span>",
                    unsafe_allow_html=True,
                )

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.caption(f"수량: **{o_qty:,}주**")
            mc2.caption(f"단가: **{o_price:,}원**")
            mc3.caption(f"주문번호: **{o_ext}**")
            mc4.caption(f"전송: **{o_time}**")


# ════════════════════════════════════════════════════════════════
# 화면 10 – 안전 설정
# ════════════════════════════════════════════════════════════════

# 거래 모드 메타정보 (render 함수 외부에서 공유)
_MODE_INFO: dict[str, dict] = {
    "analysis_only": {
        "label": "분석 전용",
        "color": "#5DADE2",
        "icon":  "📊",
        "desc":  "신호 생성까지만 허용합니다. 주문 후보를 생성하거나 전송할 수 없습니다.",
    },
    "paper_trading": {
        "label": "모의투자",
        "color": "#F39C12",
        "icon":  "📝",
        "desc":  "모의투자 주문 후보 생성 및 전송을 허용합니다. 수동 승인 필수. 실거래 없음.",
    },
    "real_ready": {
        "label": "실거래 준비",
        "color": "#E74C3C",
        "icon":  "⚠️",
        "desc":  "실거래 전환 준비 상태 표시용입니다. 실제 주문은 절대 발생하지 않습니다.",
    },
}


def _save_limit_settings(
    max_order_amount:    int,
    max_daily_loss_rate: float,
    max_position_count:  int,
) -> tuple[bool, str]:
    """
    주문 한도 3개 항목을 저장한다.
    Supabase 연결 시 system_settings + risk_settings 동시 업데이트.
    항상 로컬 JSON 에도 반영한다.
    """
    errors: list[str] = []

    # ── 로컬 JSON (system_settings.py 의 파일 경로 그대로) ─────
    try:
        from services.system_settings import get_system_settings, SETTINGS_FILE
        import json as _json
        current = get_system_settings()
        current.update({
            "max_order_amount":    max_order_amount,
            "max_daily_loss_rate": max_daily_loss_rate,
            "max_position_count":  max_position_count,
        })
        current.pop("source", None)
        SETTINGS_FILE.write_text(
            _json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        errors.append(f"로컬 저장 실패: {e}")

    # ── Supabase system_settings (max_order_amount) ─────────────
    try:
        from services.supabase_client import is_connected, get_client
        if is_connected():
            get_client().table("system_settings").update(
                {"max_order_amount": max_order_amount}
            ).eq("id", 1).execute()
    except Exception as e:
        errors.append(f"system_settings Supabase 업데이트 실패: {e}")

    # ── Supabase risk_settings (loss_rate, position_count) ───────
    try:
        from services.supabase_client import is_connected, get_client
        if is_connected():
            rows = (
                get_client()
                .table("risk_settings")
                .select("id")
                .order("id", desc=False)
                .limit(1)
                .execute()
                .data or []
            )
            if rows:
                rid = rows[0]["id"]
                get_client().table("risk_settings").update({
                    "max_daily_loss_rate": max_daily_loss_rate,
                    "max_position_count":  max_position_count,
                }).eq("id", rid).execute()
    except Exception as e:
        errors.append(f"risk_settings Supabase 업데이트 실패: {e}")

    if errors:
        return False, "일부 저장 실패: " + " | ".join(errors)
    return True, (
        f"저장 완료 — 최대 주문금액 {max_order_amount:,}원 / "
        f"일 손실 한도 {max_daily_loss_rate:.1f}% / "
        f"최대 보유 {max_position_count}종목"
    )


def render_safety_settings() -> None:
    """안전 설정 화면 (9단계)."""
    _render_menu_title(
        "⚙️ 안전 설정",
        "분석 전용·모의투자 모드, 긴급 중지, 주문 한도 등 주문 안전장치를 확인하고 조정합니다.",
    )

    # ── 서비스 import ────────────────────────────────────────────
    try:
        from services.system_settings import (
            get_system_settings,
            update_trading_mode,
            set_emergency_stop,
        )
    except ImportError as _e:
        st.error(f"시스템 설정 서비스 로드 실패: {_e}")
        return

    # ── 고정 경고 배너 ──────────────────────────────────────────
    st.error(
        "⛔  실거래 자동주문은 이 시스템에서 지원하지 않습니다.  "
        "allow_real_trading 은 코드 레벨에서 영구적으로 False 로 고정되어 있으며,  "
        "어떤 설정으로도 변경할 수 없습니다.",
        icon="🚫",
    )

    # ── 설정 로드 ───────────────────────────────────────────────
    try:
        settings = get_system_settings()
    except Exception as _e:
        st.error(f"설정 로드 실패: {_e}")
        return

    curr_mode      = str(settings.get("trading_mode",        "analysis_only"))
    e_stop         = bool(settings.get("emergency_stop",       False))
    max_amount     = int(settings.get("max_order_amount",      1_000_000))
    max_loss       = float(settings.get("max_daily_loss_rate", -3.0))
    max_pos        = int(settings.get("max_position_count",    5))
    req_approval   = bool(settings.get("require_manual_approval", True))
    src            = str(settings.get("source", "default"))

    # ── 액션 메시지 ─────────────────────────────────────────────
    settings_msg = st.session_state.get("settings_msg")
    if settings_msg:
        level, text = settings_msg
        if level == "success":
            st.success(text)
        elif level == "error":
            st.error(text)
        else:
            st.warning(text)
        st.session_state["settings_msg"] = None

    st.caption(f"설정 출처: **{src}**")
    st.divider()

    # ══════════════════════════════════════════════════════════
    # Section 1 — 거래 모드
    # ══════════════════════════════════════════════════════════
    st.subheader("🔄 거래 모드 선택")

    # 모드 카드 3열
    mode_keys = list(_MODE_INFO.keys())
    mc1, mc2, mc3 = st.columns(3)
    for col, mode_key in zip([mc1, mc2, mc3], mode_keys):
        m     = _MODE_INFO[mode_key]
        sel   = (mode_key == curr_mode)
        bdr   = f"3px solid {m['color']}" if sel else f"1px solid {m['color']}55"
        bg    = f"{m['color']}33" if sel else f"{m['color']}0D"
        badge = (
            f"<div style='font-size:10px;background:white;color:{m['color']};"
            f"border:1px solid {m['color']};display:inline-block;"
            f"padding:1px 7px;border-radius:4px;font-weight:bold;margin-top:5px'>현재 선택</div>"
        ) if sel else ""
        col.markdown(
            f"<div style='border:{bdr};border-radius:10px;padding:14px 12px;background:{bg};min-height:120px'>"
            f"<div style='font-size:22px'>{m['icon']}</div>"
            f"<div style='font-weight:bold;color:{m['color']};font-size:15px'>{m['label']}</div>"
            f"<div style='font-size:11px;color:#555;margin-top:4px;line-height:1.5'>{m['desc']}</div>"
            f"{badge}"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("")
    new_mode = st.selectbox(
        "변경할 거래 모드를 선택하세요",
        mode_keys,
        index=mode_keys.index(curr_mode),
        format_func=lambda x: f"{_MODE_INFO[x]['icon']}  {_MODE_INFO[x]['label']}  ({x})",
        key="mode_select",
    )

    if new_mode == "real_ready":
        st.warning(
            "⚠️ **real_ready** 모드는 실거래 준비 상태 **표시 전용** 입니다.  "
            "이 모드를 선택해도 실거래 주문은 코드 레벨에서 영구 차단됩니다.  "
            "주문 후보 생성 및 전송 동작은 paper_trading 모드와 동일하지 않습니다.",
        )
    elif new_mode == "paper_trading":
        st.info(
            "📝 **모의투자** 모드에서는 주문 후보 생성이 허용됩니다.  "
            "수동 승인 후 모의투자 API로 전송됩니다. 실거래 자금은 사용되지 않습니다."
        )

    if st.button("✅ 거래 모드 변경", type="primary", key="change_mode_btn"):
        result = update_trading_mode(new_mode)
        lvl = "success" if result["success"] else "error"
        st.session_state["settings_msg"] = (lvl, result["message"])
        st.rerun()

    st.divider()

    # ══════════════════════════════════════════════════════════
    # Section 2 — 긴급 중지
    # ══════════════════════════════════════════════════════════
    st.subheader("🚨 긴급 중지")

    if e_stop:
        st.error(
            "🚨 **긴급 중지 활성화** 상태입니다.  "
            "모든 주문 후보 생성 및 전송이 즉시 차단됩니다.  "
            "해제하려면 아래 [긴급 중지 해제] 버튼을 클릭하세요."
        )
    else:
        st.success("✅ 긴급 중지 비활성. 정상 운영 중입니다.")

    eb1, eb2, _ = st.columns([1, 1, 3])
    with eb1:
        if e_stop:
            st.button("🚨 긴급 중지 ON", disabled=True, use_container_width=True,
                      help="이미 활성화 상태입니다.")
        elif st.button("🚨 긴급 중지 ON", type="primary", use_container_width=True,
                       key="estop_on"):
            result = set_emergency_stop(True)
            st.session_state["settings_msg"] = ("error", f"🚨 {result['message']}")
            st.rerun()

    with eb2:
        if not e_stop:
            st.button("✅ 긴급 중지 해제", disabled=True, use_container_width=True,
                      help="이미 비활성 상태입니다.")
        elif st.button("✅ 긴급 중지 해제", type="primary", use_container_width=True,
                       key="estop_off"):
            result = set_emergency_stop(False)
            st.session_state["settings_msg"] = ("success", f"✅ {result['message']}")
            st.rerun()

    st.divider()

    # ══════════════════════════════════════════════════════════
    # Section 3 — 주문 한도
    # ══════════════════════════════════════════════════════════
    st.subheader("💰 주문 한도 설정")
    st.caption(
        "변경 후 **[한도 저장]** 버튼을 클릭해야 적용됩니다.  "
        "risk_settings 테이블(Supabase) 및 로컬 JSON에 동시 저장됩니다."
    )

    with st.form("limit_settings_form", border=True):
        lc1, lc2, lc3 = st.columns(3)

        with lc1:
            form_max_amount = st.number_input(
                "1회 최대 주문 금액 (원)",
                min_value=100_000,
                max_value=10_000_000,
                value=max_amount,
                step=100_000,
                format="%d",
                help="단일 주문 1건의 최대 허용 금액. system_settings.max_order_amount",
            )

        with lc2:
            form_max_loss = st.number_input(
                "1일 최대 손실률 (%)",
                min_value=-20.0,
                max_value=-0.5,
                value=max_loss,
                step=0.5,
                format="%.1f",
                help="음수 값. 예: -3.0 → 당일 손실이 3% 이상이면 이후 주문 차단. "
                     "risk_settings.max_daily_loss_rate",
            )

        with lc3:
            form_max_pos = st.number_input(
                "최대 보유 종목 수",
                min_value=1,
                max_value=20,
                value=max_pos,
                step=1,
                help="동시 보유 가능한 최대 종목 수. risk_settings.max_position_count",
            )

        # 설정 미리보기
        preview_amount = form_max_loss * form_max_amount / 100
        st.markdown(
            f"<div style='background:#1A5276;color:white;border-radius:6px;padding:8px 14px;"
            f"font-size:13px;margin-top:4px'>"
            f"💡 미리보기: 최대 주문금액 <b>{int(form_max_amount):,}원</b> · "
            f"손실 한도 <b>{form_max_loss:.1f}%</b> · "
            f"최대 보유 <b>{int(form_max_pos)}종목</b>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown("")

        submitted = st.form_submit_button("💾 한도 저장", type="primary", use_container_width=True)
        if submitted:
            ok, msg = _save_limit_settings(
                int(form_max_amount),
                float(form_max_loss),
                int(form_max_pos),
            )
            st.session_state["settings_msg"] = ("success" if ok else "error", msg)
            st.rerun()

    st.divider()

    # ══════════════════════════════════════════════════════════
    # Section 4 — 고정 안전 값 (읽기 전용)
    # ══════════════════════════════════════════════════════════
    st.subheader("🔒 고정 안전 값 (변경 불가)")
    st.caption(
        "아래 항목들은 코드 레벨 하드코딩 상수입니다.  "
        "설정 화면이나 DB 값으로 변경할 수 없습니다."
    )

    fixed_rows = [
        ("수동 승인 필수",       "항상 True",     "#27AE60",
         "주문 후보는 반드시 사용자 승인 후에만 전송 가능합니다."),
        ("실거래 허용",          "영구 False",    "#E74C3C",
         "allow_real_trading = False. 절대 True로 변경되지 않습니다."),
        ("시장가 자동주문",      "영구 차단",     "#E74C3C",
         "ALLOW_MARKET_ORDER = False. 지정가 주문만 허용됩니다."),
        ("실거래 계좌 연결",     "미지원",        "#95A5A6",
         "실거래 API 연결 기능은 구현되지 않습니다."),
        ("OpenClaw 주문 권한",   "없음",          "#95A5A6",
         "AI 에이전트(OpenClaw)는 주문 실행 권한을 갖지 않습니다."),
    ]

    for label, value, color, desc in fixed_rows:
        fc1, fc2 = st.columns([2, 3])
        with fc1:
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:8px;padding:6px 0'>"
                f"<span style='background:{color};color:white;padding:2px 10px;"
                f"border-radius:5px;font-weight:bold;font-size:12px'>{value}</span>"
                f"<span style='font-weight:bold'>{label}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with fc2:
            st.markdown(
                f"<div style='color:#666;font-size:13px;padding:8px 0'>{desc}</div>",
                unsafe_allow_html=True,
            )

    # 수동 승인 현재 상태
    if req_approval:
        st.success("✅ 수동 승인 필수 = True (정상)", icon="🔐")
    else:
        st.warning("⚠️ 수동 승인이 비활성 상태입니다. 설정을 확인하세요.")


# ════════════════════════════════════════════════════════════════
# 화면 11 – 주문 로그
# ════════════════════════════════════════════════════════════════

# ── 로그 화면용 색상 팔레트 ────────────────────────────────────
_SIG_STATUS_COLOR = {
    "생성":        "#2980B9",
    "주문후보생성": "#F39C12",
    "무시":        "#95A5A6",
    "만료":        "#7F8C8D",
}
_APPR_STATUS_COLOR = {
    "승인대기": "#F39C12",
    "승인":     "#27AE60",
    "거절":     "#E74C3C",
    "만료":     "#7F8C8D",
}
_RISK_STATUS_COLOR = {
    "통과":    "#27AE60",
    "차단":    "#E74C3C",
    "확인필요": "#F39C12",
}
_BROKER_STATUS_COLOR = {
    "전송대기":  "#F39C12",
    "전송완료":  "#2980B9",
    "일부체결":  "#8E44AD",
    "전량체결":  "#27AE60",
    "취소":     "#95A5A6",
    "실패":     "#E74C3C",
}
_SEVERITY_COLOR = {
    "LOW":      "#27AE60",
    "MEDIUM":   "#F39C12",
    "HIGH":     "#E74C3C",
    "CRITICAL": "#922B21",
}
_EVT_TYPE_COLOR = {
    "SEND_ATTEMPT":  "#2980B9",
    "ORDER_SENT":    "#27AE60",
    "ORDER_FAILED":  "#E74C3C",
    "CANCEL_SENT":   "#F39C12",
    "CANCEL_FAILED": "#C0392B",
    "STATUS_QUERY":  "#95A5A6",
}
_SAFETY_EVT_ICON = {
    "RISK_BREACH":    "⚠️",
    "EMERGENCY_STOP": "🚨",
    "ORDER_BLOCKED":  "🚫",
    "DAILY_LIMIT":    "📉",
    "SYSTEM_ERROR":   "🔧",
}


def _scolor_badge(text: str, color_map: dict, fallback: str = "#888") -> str:
    c = color_map.get(str(text), fallback)
    return (
        f"<span style='background:{c};color:white;padding:1px 8px;"
        f"border-radius:5px;font-size:12px;font-weight:bold'>{text}</span>"
    )


def _load_log_table(
    table:        str,
    date_col:     str,
    date_from:    str,
    stock_col:    str | None,
    stock_filter: str,
    extra_eq:     dict | None,
    limit:        int,
    local_file:   str | None = None,
) -> list[dict]:
    """
    Supabase 또는 로컬 JSON에서 로그 테이블 데이터를 로드한다.

    Args:
        table:        Supabase 테이블명
        date_col:     날짜 기준 컬럼명 (gte 필터 적용)
        date_from:    날짜 하한 (YYYY-MM-DD)
        stock_col:    종목 코드/명 컬럼명 (None이면 종목 필터 스킵)
        stock_filter: 종목 검색어 (빈 문자열이면 전체)
        extra_eq:     추가 동등 필터 {col: value} (None이면 없음)
        limit:        최대 건수
        local_file:   로컬 JSON 파일명 (data/ 하위, None이면 로컬 폴백 없음)
    """
    try:
        from services.supabase_client import is_connected, get_client
        if is_connected():
            q = (
                get_client()
                .table(table)
                .select("*")
                .gte(date_col, date_from)
                .order("created_at", desc=True)
                .limit(limit)
            )
            if extra_eq:
                for col, val in extra_eq.items():
                    if val and val != "전체":
                        q = q.eq(col, val)
            rows = q.execute().data or []

            # 종목 필터 (Python 레벨)
            if stock_filter and stock_col:
                sf = stock_filter.strip().lower()
                rows = [
                    r for r in rows
                    if sf in str(r.get(stock_col, "")).lower()
                    or sf in str(r.get("stock_name", "")).lower()
                    or sf in str(r.get("stock_code", "")).lower()
                ]
            return rows
    except Exception:
        pass

    # 로컬 JSON 폴백
    if not local_file:
        return []
    from pathlib import Path as _Path
    import json as _json
    fpath = _Path(__file__).parent / "data" / local_file
    if not fpath.exists():
        return []
    try:
        rows = _json.loads(fpath.read_text(encoding="utf-8"))
    except Exception:
        return []

    # 날짜 필터
    rows = [r for r in rows if str(r.get(date_col, ""))[:10] >= date_from]
    # 종목 필터
    if stock_filter and stock_col:
        sf = stock_filter.strip().lower()
        rows = [
            r for r in rows
            if sf in str(r.get(stock_col, "")).lower()
            or sf in str(r.get("stock_name", "")).lower()
            or sf in str(r.get("stock_code", "")).lower()
        ]
    # extra_eq 필터
    if extra_eq:
        for col, val in (extra_eq or {}).items():
            if val and val != "전체":
                rows = [r for r in rows if str(r.get(col, "")) == val]

    rows.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    return rows[:limit]


def render_order_log() -> None:
    """주문 로그 화면 — 전체 주문 흐름 추적 (10단계)."""
    _render_menu_title(
        "📋 주문 로그",
        "신호 생성부터 후보, 승인, 브로커 전송, 안전 이벤트까지 주문 흐름 전체 이력을 추적합니다.",
    )
    st.caption(
        "매매 신호 생성부터 브로커 전송까지 전체 주문 흐름을 추적합니다.  "
        "Supabase 연결 시 실시간 데이터를, 미연결 시 로컬 JSON을 표시합니다."
    )

    # ══════════════════════════════════════════════════════════
    # 공통 필터
    # ══════════════════════════════════════════════════════════
    from datetime import timedelta as _td
    st.subheader("🔍 공통 필터")
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        f_date = st.date_input("조회 시작일", value=date.today() - _td(days=7), key="log_date")
    with fc2:
        f_stock = st.text_input("종목코드 / 종목명", placeholder="예: 005930 또는 삼성", key="log_stock")
    with fc3:
        f_strategy = st.text_input("전략명", placeholder="예: v3_score_momentum", key="log_strategy")
    with fc4:
        f_limit = st.number_input("최대 조회 건수", min_value=10, max_value=500, value=50, step=10, key="log_limit")

    date_from = str(f_date)
    stock_q   = f_stock.strip()
    strat_q   = f_strategy.strip()
    limit     = int(f_limit)

    st.divider()

    # ══════════════════════════════════════════════════════════
    # 탭
    # ══════════════════════════════════════════════════════════
    tab_sig, tab_intent, tab_broker, tab_exec, tab_safety = st.tabs([
        "📡 매매 신호",
        "📋 주문 후보",
        "📤 전송 주문",
        "📜 실행 로그",
        "🚨 안전 이벤트",
    ])

    # ──────────────────────────────────────────────────────────
    # TAB 1 — 매매 신호 (trade_signals)
    # ──────────────────────────────────────────────────────────
    with tab_sig:
        sc1, sc2 = st.columns([2, 1])
        with sc1:
            f_sig_type = st.selectbox(
                "신호 유형",
                ["전체", "매수신호", "매도신호"],
                key="log_sig_type",
            )
        with sc2:
            f_sig_status = st.selectbox(
                "상태",
                ["전체", "생성", "주문후보생성", "무시", "만료"],
                key="log_sig_status",
            )

        extra: dict = {}
        if f_sig_type != "전체":
            extra["signal_type"] = f_sig_type
        if f_sig_status != "전체":
            extra["status"] = f_sig_status
        if strat_q:
            extra["strategy_name"] = strat_q

        signals = _load_log_table(
            table="trade_signals",
            date_col="signal_date",
            date_from=date_from,
            stock_col="stock_code",
            stock_filter=stock_q,
            extra_eq=extra if extra else None,
            limit=limit,
            local_file="trade_signals.json",
        )

        st.caption(f"총 **{len(signals)}건** 조회됨")

        if not signals:
            st.info("조회된 매매 신호가 없습니다.")
        else:
            # 요약 메트릭
            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("전체", len(signals))
            sm2.metric("매수신호", sum(1 for s in signals if s.get("signal_type") == "매수신호"))
            sm3.metric("매도신호", sum(1 for s in signals if s.get("signal_type") == "매도신호"))
            sm4.metric("주문후보 전환", sum(1 for s in signals if s.get("status") == "주문후보생성"))

            for sig in signals:
                sig_id     = sig.get("id", "")
                s_date     = str(sig.get("signal_date", ""))
                s_code     = str(sig.get("stock_code", ""))
                s_name     = str(sig.get("stock_name", "") or s_code)
                s_type     = str(sig.get("signal_type", ""))
                s_price    = int(sig.get("signal_price", 0) or 0)
                s_score    = sig.get("score")
                s_status   = str(sig.get("status", ""))
                s_strategy = str(sig.get("strategy_name", "") or "")
                s_reason   = str(sig.get("reason", "") or "")
                s_risk     = str(sig.get("risk_summary", "") or "")

                type_color = "#E74C3C" if s_type == "매수신호" else "#2980B9"
                with st.container(border=True):
                    h1, h2, h3 = st.columns([3, 1, 1])
                    with h1:
                        st.markdown(
                            f"<span style='background:{type_color};color:white;padding:1px 8px;"
                            f"border-radius:4px;font-size:12px;font-weight:bold'>{s_type}</span>"
                            f"&nbsp;&nbsp;<b>{s_name}</b> "
                            f"<span style='color:#888;font-size:12px'>({s_code})</span>",
                            unsafe_allow_html=True,
                        )
                    with h2:
                        st.markdown(
                            _scolor_badge(s_status, _SIG_STATUS_COLOR),
                            unsafe_allow_html=True,
                        )
                    with h3:
                        st.caption(s_date)

                    dc1, dc2, dc3, dc4 = st.columns(4)
                    dc1.caption(f"신호가: **{s_price:,}원**")
                    dc2.caption(f"점수: **{s_score:.1f}점**" if s_score is not None else "점수: **-**")
                    dc3.caption(f"전략: **{s_strategy or '-'}**")
                    dc4.caption(f"ID: **#{sig_id}**")

                    if s_reason or s_risk:
                        with st.expander("📋 신호 상세"):
                            if s_reason:
                                st.markdown(f"**근거:** {s_reason}")
                            if s_risk:
                                st.warning(f"**리스크:** {s_risk}")

    # ──────────────────────────────────────────────────────────
    # TAB 2 — 주문 후보 (order_intents)
    # ──────────────────────────────────────────────────────────
    with tab_intent:
        ic1, ic2 = st.columns(2)
        with ic1:
            f_appr = st.selectbox(
                "승인 상태",
                ["전체", "승인대기", "승인", "거절", "만료"],
                key="log_appr_status",
            )
        with ic2:
            f_risk = st.selectbox(
                "리스크 검사 결과",
                ["전체", "통과", "확인필요", "차단"],
                key="log_risk_status",
            )

        i_extra: dict = {}
        if f_appr != "전체":
            i_extra["approval_status"] = f_appr
        if f_risk != "전체":
            i_extra["risk_check_status"] = f_risk
        if strat_q:
            i_extra["strategy_name"] = strat_q

        intents = _load_log_table(
            table="order_intents",
            date_col="created_at",
            date_from=date_from,
            stock_col="stock_code",
            stock_filter=stock_q,
            extra_eq=i_extra if i_extra else None,
            limit=limit,
            local_file="order_intents.json",
        )

        st.caption(f"총 **{len(intents)}건** 조회됨")

        # 차단 건 주의 표시
        blocked = [i for i in intents if i.get("risk_check_status") == "차단"]
        if blocked:
            st.error(f"🚫 리스크 차단 주문 **{len(blocked)}건** 포함 — 아래에서 확인하세요.")

        if not intents:
            st.info("조회된 주문 후보가 없습니다.")
        else:
            im1, im2, im3, im4 = st.columns(4)
            im1.metric("전체", len(intents))
            im2.metric("승인 완료", sum(1 for i in intents if i.get("approval_status") == "승인"))
            im3.metric("리스크 차단", len(blocked))
            im4.metric(
                "승인 대기",
                sum(1 for i in intents if i.get("approval_status") == "승인대기"),
            )

            for intent in intents:
                i_id     = intent.get("id", "")
                i_code   = str(intent.get("stock_code", ""))
                i_name   = str(intent.get("stock_name", "") or i_code)
                i_type   = str(intent.get("order_type", ""))
                i_price  = int(intent.get("order_price", 0) or 0)
                i_qty    = int(intent.get("quantity", 0) or 0)
                i_amount = int(intent.get("order_amount", 0) or 0)
                i_appr   = str(intent.get("approval_status", ""))
                i_risk   = str(intent.get("risk_check_status", ""))
                i_rmsg   = str(intent.get("risk_check_message", "") or "")
                i_strat  = str(intent.get("strategy_name", "") or "")
                i_at     = str(intent.get("created_at", ""))[:16]
                i_appr_at = str(intent.get("approved_at") or intent.get("rejected_at") or "")[:16]

                is_blocked = (i_risk == "차단")
                border_color = "#E74C3C" if is_blocked else "#DDD"

                with st.container(border=True):
                    h1, h2, h3 = st.columns([3, 1, 1])
                    with h1:
                        otype_c = "#E74C3C" if i_type == "매수" else "#2980B9"
                        st.markdown(
                            f"<span style='background:{otype_c};color:white;padding:1px 8px;"
                            f"border-radius:4px;font-size:12px;font-weight:bold'>{i_type}</span>"
                            f"&nbsp;&nbsp;<b>{i_name}</b> "
                            f"<span style='color:#888;font-size:12px'>({i_code})</span>",
                            unsafe_allow_html=True,
                        )
                    with h2:
                        st.markdown(
                            _scolor_badge(i_appr, _APPR_STATUS_COLOR),
                            unsafe_allow_html=True,
                        )
                    with h3:
                        st.markdown(
                            _scolor_badge(i_risk, _RISK_STATUS_COLOR),
                            unsafe_allow_html=True,
                        )

                    dc1, dc2, dc3, dc4 = st.columns(4)
                    dc1.caption(f"수량: **{i_qty:,}주**")
                    dc2.caption(f"단가: **{i_price:,}원**")
                    dc3.caption(f"금액: **{i_amount:,}원**")
                    dc4.caption(f"전략: **{i_strat or '-'}**")
                    st.caption(f"생성: {i_at}" + (f"  |  처리: {i_appr_at}" if i_appr_at else ""))

                    if is_blocked and i_rmsg:
                        st.error(f"🚫 차단 사유: {i_rmsg}")
                    elif i_rmsg:
                        with st.expander("🔍 리스크 검사 메시지"):
                            st.write(i_rmsg)

    # ──────────────────────────────────────────────────────────
    # TAB 3 — 전송 주문 (broker_orders)
    # ──────────────────────────────────────────────────────────
    with tab_broker:
        bc1, bc2 = st.columns(2)
        with bc1:
            f_bstatus = st.selectbox(
                "주문 상태",
                ["전체", "전송대기", "전송완료", "일부체결", "전량체결", "취소", "실패"],
                key="log_broker_status",
            )
        with bc2:
            f_bmode = st.selectbox(
                "계좌 모드",
                ["전체", "mock", "paper"],
                key="log_broker_mode",
            )

        b_extra: dict = {}
        if f_bstatus != "전체":
            b_extra["order_status"] = f_bstatus
        if f_bmode != "전체":
            b_extra["account_mode"] = f_bmode

        brokers = _load_log_table(
            table="broker_orders",
            date_col="updated_at",
            date_from=date_from,
            stock_col="stock_code",
            stock_filter=stock_q,
            extra_eq=b_extra if b_extra else None,
            limit=limit,
            local_file="broker_orders.json",
        )

        st.caption(f"총 **{len(brokers)}건** 조회됨")

        if not brokers:
            st.info("조회된 전송 주문이 없습니다.")
        else:
            bm1, bm2, bm3, bm4 = st.columns(4)
            bm1.metric("전체", len(brokers))
            bm2.metric("전량체결", sum(1 for b in brokers if b.get("order_status") == "전량체결"))
            bm3.metric("취소", sum(1 for b in brokers if b.get("order_status") == "취소"))
            bm4.metric("실패", sum(1 for b in brokers if b.get("order_status") == "실패"))

            for bo in brokers:
                b_id     = bo.get("id", "")
                b_code   = str(bo.get("stock_code", ""))
                b_name   = str(bo.get("stock_name", "") or b_code)
                b_type   = str(bo.get("order_type", ""))
                b_price  = int(bo.get("order_price", 0) or 0)
                b_qty    = int(bo.get("quantity", 0) or 0)
                b_status = str(bo.get("order_status", ""))
                b_mode   = str(bo.get("account_mode", ""))
                b_ext    = str(bo.get("broker_order_id", "-") or "-")
                b_filled = int(bo.get("filled_quantity", 0) or 0)
                b_avg    = int(bo.get("avg_fill_price", 0) or 0)
                b_sent   = str(bo.get("sent_at", "") or bo.get("updated_at", ""))[:16]
                is_mock  = (b_mode == "mock")

                s_color = _BROKER_STATUS_COLOR.get(b_status, "#888")

                with st.container(border=True):
                    h1, h2, h3 = st.columns([3, 1, 1])
                    with h1:
                        otype_c = "#E74C3C" if b_type == "매수" else "#2980B9"
                        mock_tag = (
                            " <span style='background:#888;color:white;padding:1px 5px;"
                            "border-radius:3px;font-size:10px'>MOCK</span>"
                            if is_mock else ""
                        )
                        st.markdown(
                            f"<span style='background:{otype_c};color:white;padding:1px 8px;"
                            f"border-radius:4px;font-size:12px;font-weight:bold'>{b_type}</span>"
                            f"&nbsp;&nbsp;<b>{b_name}</b> "
                            f"<span style='color:#888;font-size:12px'>({b_code})</span>{mock_tag}",
                            unsafe_allow_html=True,
                        )
                    with h2:
                        st.markdown(
                            _scolor_badge(b_status, _BROKER_STATUS_COLOR),
                            unsafe_allow_html=True,
                        )
                    with h3:
                        st.caption(f"#{b_id}")

                    dc1, dc2, dc3, dc4 = st.columns(4)
                    dc1.caption(f"수량: **{b_qty:,}주** / 체결: **{b_filled:,}주**")
                    dc2.caption(f"단가: **{b_price:,}원**" + (f" / 체결가: **{b_avg:,}원**" if b_avg else ""))
                    dc3.caption(f"주문번호: **{b_ext}**")
                    dc4.caption(f"전송: **{b_sent}**")

                    if b_status == "실패":
                        st.error("❌ 주문 전송 실패. 실행 로그 탭에서 상세 사유를 확인하세요.")
                    elif b_status in ("일부체결", "전량체결"):
                        fill_rate = round(b_filled / b_qty * 100, 1) if b_qty else 0
                        st.success(f"체결률: {fill_rate:.1f}% ({b_filled:,}/{b_qty:,}주)")

    # ──────────────────────────────────────────────────────────
    # TAB 4 — 실행 로그 (order_execution_logs)
    # ──────────────────────────────────────────────────────────
    with tab_exec:
        ec1, ec2 = st.columns(2)
        with ec1:
            f_evt = st.selectbox(
                "이벤트 유형",
                ["전체", "SEND_ATTEMPT", "ORDER_SENT", "ORDER_FAILED",
                 "CANCEL_SENT", "CANCEL_FAILED", "STATUS_QUERY"],
                key="log_exec_evt",
            )
        with ec2:
            f_ext_no = st.text_input("외부 주문번호", placeholder="예: M12345678", key="log_ext_no")

        e_extra: dict = {}
        if f_evt != "전체":
            e_extra["event_type"] = f_evt

        exec_logs = _load_log_table(
            table="order_execution_logs",
            date_col="created_at",
            date_from=date_from,
            stock_col=None,
            stock_filter="",
            extra_eq=e_extra if e_extra else None,
            limit=limit,
            local_file="order_execution_logs.json",
        )

        # 외부 주문번호 필터 (Python 레벨)
        if f_ext_no.strip():
            exec_logs = [
                e for e in exec_logs
                if f_ext_no.strip() in str(e.get("external_order_id", ""))
            ]

        st.caption(f"총 **{len(exec_logs)}건** 조회됨")

        if not exec_logs:
            st.info("조회된 실행 로그가 없습니다.")
        else:
            em1, em2, em3 = st.columns(3)
            em1.metric("전체", len(exec_logs))
            em2.metric(
                "주문 성공",
                sum(1 for e in exec_logs if e.get("event_type") == "ORDER_SENT"),
            )
            em3.metric(
                "주문 실패",
                sum(1 for e in exec_logs if e.get("event_type") == "ORDER_FAILED"),
            )

            for log in exec_logs:
                l_id      = log.get("id", "")
                l_evt     = str(log.get("event_type", ""))
                l_msg     = str(log.get("message", "") or "")
                l_ext     = str(log.get("external_order_id", "-") or "-")
                l_bo_id   = log.get("broker_order_id", "")
                l_at      = str(log.get("created_at", ""))[:19]
                l_resp    = log.get("raw_response")

                e_color = _EVT_TYPE_COLOR.get(l_evt, "#888")
                is_fail = l_evt in ("ORDER_FAILED", "CANCEL_FAILED")

                with st.container(border=True):
                    h1, h2 = st.columns([4, 1])
                    with h1:
                        st.markdown(
                            f"<span style='background:{e_color};color:white;padding:1px 9px;"
                            f"border-radius:4px;font-size:12px;font-weight:bold'>{l_evt}</span>"
                            f"&nbsp;&nbsp;<span style='font-size:13px'>{l_msg[:80]}</span>",
                            unsafe_allow_html=True,
                        )
                    with h2:
                        st.caption(l_at)

                    dc1, dc2 = st.columns(2)
                    dc1.caption(f"주문번호: **{l_ext}**")
                    dc2.caption(f"broker_orders_id: **{l_bo_id or '-'}**")

                    if is_fail:
                        st.error(f"실패 메시지: {l_msg}")
                    if l_resp and not is_fail:
                        with st.expander("📄 API 응답 원문"):
                            st.json(l_resp)

    # ──────────────────────────────────────────────────────────
    # TAB 5 — 안전 이벤트 (safety_events)
    # ──────────────────────────────────────────────────────────
    with tab_safety:
        vc1, vc2 = st.columns(2)
        with vc1:
            f_sev = st.selectbox(
                "심각도",
                ["전체", "CRITICAL", "HIGH", "MEDIUM", "LOW"],
                key="log_severity",
            )
        with vc2:
            f_sevt = st.selectbox(
                "이벤트 유형",
                ["전체", "RISK_BREACH", "EMERGENCY_STOP", "ORDER_BLOCKED",
                 "DAILY_LIMIT", "SYSTEM_ERROR"],
                key="log_safety_evt",
            )

        v_extra: dict = {}
        if f_sev != "전체":
            v_extra["severity"] = f_sev
        if f_sevt != "전체":
            v_extra["event_type"] = f_sevt

        safety_rows = _load_log_table(
            table="safety_events",
            date_col="event_date",
            date_from=date_from,
            stock_col="related_stock_code",
            stock_filter=stock_q,
            extra_eq=v_extra if v_extra else None,
            limit=limit,
            local_file=None,   # safety_events는 Supabase 전용
        )

        st.caption(f"총 **{len(safety_rows)}건** 조회됨")

        criticals = [s for s in safety_rows if s.get("severity") == "CRITICAL"]
        if criticals:
            st.error(f"🚨 CRITICAL 이벤트 **{len(criticals)}건** — 즉시 확인이 필요합니다!")

        if not safety_rows:
            st.info("조회된 안전 이벤트가 없습니다.")
        else:
            vm1, vm2, vm3, vm4 = st.columns(4)
            vm1.metric("전체", len(safety_rows))
            vm2.metric("CRITICAL", sum(1 for s in safety_rows if s.get("severity") == "CRITICAL"))
            vm3.metric("HIGH", sum(1 for s in safety_rows if s.get("severity") == "HIGH"))
            vm4.metric("긴급중지", sum(1 for s in safety_rows if s.get("event_type") == "EMERGENCY_STOP"))

            for ev in safety_rows:
                ev_type   = str(ev.get("event_type", ""))
                ev_sev    = str(ev.get("severity", "MEDIUM"))
                ev_msg    = str(ev.get("message", "") or "")
                ev_code   = str(ev.get("related_stock_code", "") or "-")
                ev_date   = str(ev.get("event_date", ""))
                ev_at     = str(ev.get("created_at", ""))[:19]

                sev_color = _SEVERITY_COLOR.get(ev_sev, "#888")
                evt_icon  = _SAFETY_EVT_ICON.get(ev_type, "🔔")
                is_crit   = ev_sev in ("CRITICAL", "HIGH")

                with st.container(border=True):
                    h1, h2, h3 = st.columns([3, 1, 1])
                    with h1:
                        st.markdown(
                            f"<span style='font-size:16px'>{evt_icon}</span>&nbsp;&nbsp;"
                            f"<b>{ev_type}</b>"
                            f"&nbsp;<span style='color:#888;font-size:12px'>{ev_date}</span>",
                            unsafe_allow_html=True,
                        )
                    with h2:
                        st.markdown(
                            _scolor_badge(ev_sev, _SEVERITY_COLOR),
                            unsafe_allow_html=True,
                        )
                    with h3:
                        if ev_code and ev_code != "-":
                            st.caption(f"관련 종목: **{ev_code}**")

                    if is_crit:
                        st.error(ev_msg)
                    elif ev_sev == "MEDIUM":
                        st.warning(ev_msg)
                    else:
                        st.info(ev_msg)

                    st.caption(f"기록: {ev_at}")


# ════════════════════════════════════════════════════════════════
# 데이터 로드 & 라우팅
# ════════════════════════════════════════════════════════════════
with st.spinner("데이터 로딩 중..."):
    market_df, scored_df = _load_data(st.session_state["refresh_key"])

menu = _render_sidebar(market_df, scored_df)

if menu == "📋 오늘의 후보 종목":
    render_candidates(market_df, scored_df)
elif menu == "🔍 종목 상세 리포트":
    render_report(market_df, scored_df)
elif menu == "📰 뉴스/이슈":
    render_news(market_df)
elif menu == "📝 매매일지":
    render_trade_journal(market_df)
elif menu == "💼 모의투자":
    render_virtual_trading(market_df, scored_df)
elif menu == "📊 모의 포트폴리오":
    render_paper_portfolio(market_df, scored_df)
elif menu == "🏆 전략 성과":
    render_strategy_performance()
elif menu == "✅ 주문 승인":
    render_order_approval()
elif menu == "⚙️ 안전 설정":
    render_safety_settings()
elif menu == "📋 주문 로그":
    render_order_log()
else:
    render_backtest(market_df)
