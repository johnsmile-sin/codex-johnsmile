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
    "refresh_key":       0,
    "save_done":         False,
    "price_update_msg":  None,   # None | (level, text)
    "news_update_msg":   None,
    "fin_update_msg":    None,
    "rescan_msg":        None,
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
    return fetch_daily_prices(_code, days=60)


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
            ["📋 오늘의 후보 종목", "🔍 종목 상세 리포트", "📰 뉴스/이슈", "📝 매매일지"],
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
    st.title("📋 오늘의 후보 종목")

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
    st.title("🔍 종목 상세 리포트")

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

    has_ohlc = all(c in df.columns for c in ["open", "high", "low", "close"])
    has_ma   = all(c in df.columns for c in ["ma5", "ma20", "ma60"])
    has_rsi  = "rsi14" in df.columns
    has_vol  = "volume" in df.columns

    date_col = "date" if "date" in df.columns else df.index

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
    st.title("📰 뉴스/이슈")

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
    st.title("📝 매매일지")
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
else:
    render_trade_journal(market_df)
