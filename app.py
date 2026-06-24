"""
app.py – local-stock-assistant 메인 대시보드
사이드바 메뉴로 4개 화면을 전환합니다.
실행: streamlit run app.py
"""

import os
from datetime import date
from dotenv import load_dotenv
import streamlit as st
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

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
if "refresh_key" not in st.session_state:
    st.session_state["refresh_key"] = 0
if "save_done" not in st.session_state:
    st.session_state["save_done"] = False

# ════════════════════════════════════════════════════════════════
# 데이터 로드 (캐시)
# ════════════════════════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def _load_data(_key: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """market_df, scored_df 를 함께 반환합니다. _key 변경 시 캐시 무효화."""
    from services.market_data import get_sample_market_data
    from strategy.scanner import scan
    df = get_sample_market_data()
    scored = scan(df)
    return df, scored


# ════════════════════════════════════════════════════════════════
# 헬퍼
# ════════════════════════════════════════════════════════════════
DECISION_COLOR = {
    "관심": "#27AE60",
    "관찰": "#F39C12",
    "보류": "#95A5A6",
    "제외": "#E74C3C",
}

_VERDICT_COLOR = {
    "적극 매수": "#1A5276",
    "분할 매수": "#27AE60",
    "관망":     "#F39C12",
    "비중 축소": "#E67E22",
    "매도":     "#E74C3C",
}

def _badge(label: str) -> str:
    color = DECISION_COLOR.get(label, "#888")
    return (
        f"<span style='background:{color};color:white;"
        f"padding:2px 10px;border-radius:6px;font-weight:bold'>{label}</span>"
    )

def _merge_with_market(scored: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    extra = market[["stock_code", "market", "sector",
                    "current_price", "change_rate",
                    "trading_value", "news_count"]]
    return scored.merge(extra, on="stock_code", how="left")


# ════════════════════════════════════════════════════════════════
# 화면 1 – 오늘의 후보 종목
# ════════════════════════════════════════════════════════════════
def render_candidates(market_df: pd.DataFrame, scored_df: pd.DataFrame) -> None:
    st.title("📋 오늘의 후보 종목")

    merged = _merge_with_market(scored_df, market_df)

    # ── 상단 요약 카드 4개 ────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전체 후보 수",       f"{len(merged)}개")
    c2.metric("관심 종목 수",       f"{(merged['decision'] == '관심').sum()}개")
    c3.metric("평균 점수",          f"{merged['score'].mean():.1f}점")
    c4.metric("뉴스 있는 종목 수",  f"{(merged['news_count'] >= 1).sum()}개")

    st.divider()

    # ── 액션 버튼 ─────────────────────────────────────────────
    btn_col1, btn_col2, _ = st.columns([1, 1, 4])

    with btn_col1:
        if st.button("💾 점수 저장", use_container_width=True, type="primary"):
            _save_scores(merged)

    with btn_col2:
        decision_opts = st.multiselect(
            "판단 필터",
            ["관심", "관찰", "보류", "제외"],
            default=["관심", "관찰"],
            label_visibility="collapsed",
        )

    if st.session_state["save_done"]:
        st.success("✅ 점수가 저장되었습니다.")
        st.session_state["save_done"] = False

    # ── 후보 종목 테이블 ──────────────────────────────────────
    st.subheader("📊 후보 종목 목록")

    view = merged[merged["decision"].isin(decision_opts)] if decision_opts else merged

    table = view[[
        "stock_code", "stock_name", "market", "sector",
        "current_price", "change_rate", "trading_value",
        "score", "decision", "news_count",
    ]].copy()

    # reasons/risks 리스트 → 문자열
    table["reasons_str"] = view["reasons"].apply(lambda x: " / ".join(x) if x else "-")
    table["risks_str"]   = view["risks"].apply(lambda x: " / ".join(x) if x else "-")

    table.columns = [
        "종목코드", "종목명", "시장", "섹터",
        "현재가", "등락률(%)", "거래대금(억)",
        "점수", "판단", "뉴스",
        "매수 이유", "리스크",
    ]

    st.dataframe(
        table,
        use_container_width=True,
        height=420,
        column_config={
            "현재가":      st.column_config.NumberColumn("현재가",      format="%d원"),
            "등락률(%)":  st.column_config.NumberColumn("등락률(%)",   format="%.2f%%"),
            "거래대금(억)":st.column_config.NumberColumn("거래대금(억)",format="%.1f"),
            "점수":        st.column_config.ProgressColumn("점수", min_value=0, max_value=100, format="%d"),
            "뉴스":        st.column_config.NumberColumn("뉴스",        format="%d건"),
        },
    )

    st.divider()

    # ── 차트 영역 ─────────────────────────────────────────────
    chart_l, chart_r = st.columns(2)

    with chart_l:
        st.subheader("🏆 점수 상위 10개 종목")
        top10 = merged.nlargest(10, "score")[["stock_name", "score", "decision"]].copy()
        top10 = top10.sort_values("score")  # 오름차순 = 가로 막대 위쪽이 높음
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
            margin=dict(l=0, r=40, t=10, b=0),
            xaxis=dict(range=[0, 105]),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with chart_r:
        st.subheader("🎯 판단별 종목 분포")
        dist = (
            merged["decision"]
            .value_counts()
            .reindex(["관심", "관찰", "보류", "제외"], fill_value=0)
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
        st.plotly_chart(fig_pie, use_container_width=True)


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

    # ── 종목 선택 & 헤더 ──────────────────────────────────────
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
        chg_icon  = "▲" if row["change_rate"] >= 0 else "▼"
        chg_color = "#E74C3C" if row["change_rate"] >= 0 else "#2980B9"
        st.markdown(
            f"<div style='margin-top:4px;padding:10px 14px;border-radius:10px;border:1px solid #ddd'>"
            f"<b style='font-size:17px'>{row['stock_name']}</b> "
            f"<span style='color:#999;font-size:12px'>{code} | {row['market']} | {row['sector']}</span><br>"
            f"<span style='font-size:22px;font-weight:bold'>{row['current_price']:,}원</span> "
            f"<span style='color:{chg_color}'>{chg_icon} {row['change_rate']:+.2f}%</span>"
            f"&nbsp;&nbsp;<span style='background:{color};color:#fff;padding:2px 12px;"
            f"border-radius:6px;font-size:13px;font-weight:bold'>{row['decision']} {row['score']}점</span>"
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
    """리포트 생성 탭 — 기술/재무/뉴스 미리보기 + 생성 버튼 + 결과 표시"""
    from services.news_data import get_mock_news
    from services.db_service import save_stock_report

    news_items = get_mock_news(stock_code=code)

    # ── 1. 기술적 점수 / 재무 요약 ────────────────────────────
    col_tech, col_fin = st.columns(2)

    with col_tech:
        st.subheader("📐 기술적 점수")
        t1, t2, t3 = st.columns(3)
        t1.metric("MA5",  f"{int(mrow['ma5']):,}원")
        t2.metric("MA20", f"{int(mrow['ma20']):,}원")
        t3.metric("MA60", f"{int(mrow['ma60']):,}원")
        st.markdown("")

        signals = {
            "이동평균 정배열 (MA5 > MA20)": mrow["close"] > mrow["ma5"] > mrow["ma20"],
            "종가 MA5 위":                  mrow["close"] > mrow["ma5"],
            "종가 MA20 위":                 mrow["close"] > mrow["ma20"],
            "양봉 마감 (종가 ≥ 시가)":      mrow["close"] >= mrow["open"],
        }
        for label, ok in signals.items():
            (st.success if ok else st.error)(("✅ " if ok else "❌ ") + label)

        vol_ratio = round(mrow["volume"] / max(mrow["avg_volume_20d"], 1), 2)
        surge = vol_ratio >= 2.0
        (st.success if surge else st.info)(
            f"{'✅' if surge else 'ℹ️'} 거래량 비율: {vol_ratio:.2f}배 (평균 대비)"
        )

    with col_fin:
        st.subheader("💰 재무 요약")
        f1, f2 = st.columns(2)
        f1.metric("PER", f"{mrow['per']:.1f}배")
        f2.metric("PBR", f"{mrow['pbr']:.2f}배")
        f3, f4 = st.columns(2)
        f3.metric("ROE", f"{mrow['roe']:.1f}%")
        f4.metric("부채비율", f"{mrow['debt_ratio']:.0f}%")
        st.markdown("")

        fin_risks = []
        if mrow["per"]        < 0:   fin_risks.append(f"PER {mrow['per']:.1f}배 — 적자 기업")
        if mrow["roe"]        < 0:   fin_risks.append(f"ROE {mrow['roe']:.1f}% — 적자")
        if mrow["debt_ratio"] >= 200: fin_risks.append(f"부채비율 {mrow['debt_ratio']:.0f}% — 200% 초과")
        if mrow["per"]        > 50:  fin_risks.append(f"PER {mrow['per']:.1f}배 — 고평가 구간")
        if fin_risks:
            for fr in fin_risks:
                st.error(f"⚠️ {fr}")
        else:
            st.success("✅ 주요 재무 지표 정상 범위")

        # 재무 레이더 차트
        with st.expander("재무 레이더 차트 보기"):
            categories = ["PER 경쟁력", "PBR 경쟁력", "ROE", "부채 안전성", "거래 활성도"]
            vals = [
                max(0, 100 - mrow["per"] * 2),
                max(0, 100 - mrow["pbr"] * 20),
                min(100, max(0, mrow["roe"] * 4)),
                max(0, 100 - mrow["debt_ratio"] * 0.5),
                min(100, mrow["trading_value"] / 2),
            ]
            dc = DECISION_COLOR.get(row["decision"], "#888")
            fig_r = go.Figure(go.Scatterpolar(
                r=vals + [vals[0]], theta=categories + [categories[0]],
                fill="toself", fillcolor="rgba(39,174,96,0.12)",
                line=dict(color=dc),
            ))
            fig_r.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=False, height=280,
                margin=dict(l=30, r=30, t=10, b=10),
            )
            st.plotly_chart(fig_r, use_container_width=True)

    st.divider()

    # ── 2. 뉴스 감성 요약 ─────────────────────────────────────
    st.subheader("📰 뉴스 감성 요약")
    pos   = sum(1 for n in news_items if n.get("sentiment") == "긍정")
    neu   = sum(1 for n in news_items if n.get("sentiment") == "중립")
    neg   = sum(1 for n in news_items if n.get("sentiment") == "부정")
    total = len(news_items)

    nc1, nc2, nc3, nc4 = st.columns(4)
    nc1.metric("전체 뉴스", f"{total}건")
    nc2.metric("📈 긍정",   f"{pos}건")
    nc3.metric("📊 중립",   f"{neu}건")
    nc4.metric("📉 부정",   f"{neg}건")

    st.markdown("")
    for item in sorted(news_items, key=lambda x: x.get("news_date", ""), reverse=True)[:3]:
        sent  = item.get("sentiment", "중립")
        color = _SENT_COLOR.get(sent, "#888")
        icon  = _SENT_ICON.get(sent, "📊")
        stars = "★" * item.get("impact_score", 3) + "☆" * (5 - item.get("impact_score", 3))
        st.markdown(
            f"<div style='padding:8px 12px;margin:4px 0;"
            f"border-left:4px solid {color};background:#fafafa;border-radius:0 6px 6px 0'>"
            f"{icon} <b>{item['title']}</b> "
            f"<span style='color:#F39C12;font-size:11px'>{stars}</span><br>"
            f"<span style='color:#aaa;font-size:12px'>{item.get('news_date','')}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── 3. 리포트 생성 버튼 ───────────────────────────────────
    report_key = f"report_{code}"
    btn_col, _ = st.columns([2, 5])
    with btn_col:
        gen_clicked = st.button(
            "📋 리포트 생성 및 저장",
            type="primary",
            use_container_width=True,
            key=f"gen_btn_{code}",
        )

    if gen_clicked:
        from analysis.stock_report import generate_report
        with st.spinner("리포트 분석 중..."):
            report = generate_report(mrow, row, news_items)
            st.session_state[report_key] = report

            verdict_data = report["최종_판단"]
            save_stock_report({
                "stock_code":        code,
                "stock_name":        str(row["stock_name"]),
                "report_date":       str(date.today()),
                "technical_summary": (
                    f"점수 {int(row['score'])}점 / "
                    f"MA5 {int(mrow['ma5']):,}원 / MA20 {int(mrow['ma20']):,}원 / "
                    f"거래량비율 {round(mrow['volume'] / max(mrow['avg_volume_20d'], 1), 2):.2f}배"
                ),
                "financial_summary": (
                    f"PER {mrow['per']:.1f}배 / PBR {mrow['pbr']:.2f}배 / "
                    f"ROE {mrow['roe']:.1f}% / 부채비율 {mrow['debt_ratio']:.0f}%"
                ),
                "news_summary":   f"긍정 {pos}건 / 중립 {neu}건 / 부정 {neg}건 (총 {total}건)",
                "final_decision": verdict_data["판정"],
                "target_return":  verdict_data["목표_수익률"],
                "stop_loss":      verdict_data["손절_라인"],
                "entry_timing":   verdict_data["진입_타이밍"],
                "risks":          " / ".join(verdict_data["리스크"]),
                "conclusion":     report["한_줄_결론"],
                "raw_json":       json.dumps(report, ensure_ascii=False),
            })
        st.success("✅ 리포트가 생성되어 저장되었습니다.")

    # ── 4. 생성된 리포트 표시 ─────────────────────────────────
    if report_key in st.session_state:
        _display_final_report(st.session_state[report_key])


def _display_final_report(report: dict) -> None:
    """generate_report() 결과를 Streamlit으로 시각화합니다."""
    j       = report["최종_판단"]
    verdict = j["판정"]
    vcolor  = _VERDICT_COLOR.get(verdict, "#888")
    meta    = report["메타"]

    st.divider()
    st.subheader("📋 종합 리포트 결과")

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

    # 주요 지표 3가지
    m1, m2, m3 = st.columns(3)
    m1.metric("🎯 목표 수익률", j["목표_수익률"])
    m2.metric("🛑 손절 라인",   j["손절_라인"])
    m3.metric("⏰ 진입 타이밍", j["진입_타이밍"])

    st.markdown("")

    # 핵심 근거 & 리스크
    g_col, r_col = st.columns(2)
    with g_col:
        st.subheader("✅ 핵심 근거 3가지")
        for i, g in enumerate(j["핵심_근거"], 1):
            st.success(f"{i}. {g}")
    with r_col:
        st.subheader("⚠️ 리스크 3가지")
        for i, r in enumerate(j["리스크"], 1):
            st.warning(f"{i}. {r}")

    st.markdown("")
    st.caption(
        f"🗓 생성일: {meta['생성일']}  |  "
        f"📊 데이터 신뢰도: {meta['데이터_신뢰도']}"
    )
    st.info(f"⚠️ {meta['주의사항']}", icon="ℹ️")


def _render_report_history(code: str, name: str) -> None:
    """과거 리포트 탭 — 저장된 리포트 목록 표시"""
    from services.db_service import get_stock_reports

    st.subheader(f"📂 {name} 저장된 리포트")
    reports = get_stock_reports(stock_code=code)

    if not reports:
        st.info("💡 저장된 리포트가 없습니다. '리포트 생성' 탭에서 리포트를 생성하세요.")
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
                        data = json.loads(raw) if isinstance(raw, str) else raw
                        st.json(data)
                    except Exception:
                        st.code(str(raw))


# ════════════════════════════════════════════════════════════════
# 화면 3 – 뉴스/이슈
# ════════════════════════════════════════════════════════════════
_SENT_COLOR = {"긍정": "#27AE60", "중립": "#F39C12", "부정": "#E74C3C"}
_SENT_ICON  = {"긍정": "📈",       "중립": "📊",       "부정": "📉"}


def render_news(market_df: pd.DataFrame) -> None:
    st.title("📰 뉴스/이슈")

    from services.news_data import get_mock_news, get_news_summary

    # ── 필터 영역 ─────────────────────────────────────────────
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

    # ── 뉴스 로드 ─────────────────────────────────────────────
    if sel_stock == "전체":
        all_news = get_mock_news()
    else:
        code = market_df[market_df["stock_name"] == sel_stock]["stock_code"].values[0]
        all_news = get_mock_news(stock_code=str(code))

    # 필터 적용
    filtered = [
        n for n in all_news
        if n["sentiment"] in (sel_sent or ["긍정", "중립", "부정"])
        and n["impact_score"] >= sel_impact
    ]

    # ── 감성 요약 카드 ────────────────────────────────────────
    st.divider()
    summary = get_news_summary(all_news)
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("전체 뉴스",  f"{summary['합계']}건")

    for col, sent in zip([s2, s3, s4], ["긍정", "중립", "부정"]):
        cnt   = summary[sent]
        pct   = cnt / summary["합계"] * 100 if summary["합계"] else 0
        icon  = _SENT_ICON[sent]
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

    # ── 감성 분포 가로 막대 ───────────────────────────────────
    with st.expander("감성 분포 차트 보기", expanded=False):
        dist_data = {
            "감성": ["긍정", "중립", "부정"],
            "건수": [summary["긍정"], summary["중립"], summary["부정"]],
        }
        fig_dist = px.bar(
            dist_data, x="건수", y="감성", orientation="h",
            color="감성",
            color_discrete_map=_SENT_COLOR,
            text="건수",
        )
        fig_dist.update_traces(textposition="outside")
        fig_dist.update_layout(
            height=200, showlegend=False,
            margin=dict(l=0, r=40, t=10, b=0),
        )
        st.plotly_chart(fig_dist, use_container_width=True)

    # ── 뉴스 목록 ─────────────────────────────────────────────
    st.subheader(f"뉴스 목록  ({len(filtered)}건)")

    if not filtered:
        st.info("선택한 조건에 해당하는 뉴스가 없습니다.")
        return

    for item in filtered:
        sent  = item.get("sentiment", "중립")
        color = _SENT_COLOR.get(sent, "#888")
        icon  = _SENT_ICON.get(sent, "📊")
        score = item.get("impact_score", 3)
        stars = "★" * score + "☆" * (5 - score)

        with st.container():
            nc1, nc2 = st.columns([6, 1])
            with nc1:
                st.markdown(
                    f"**{icon} {item['title']}**  \n"
                    f"<span style='font-size:12px;color:#888'>"
                    f"{item['stock_name']} ({item['stock_code']})  |  {item['news_date']}</span>",
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

    stock_map = {row["stock_name"]: row["stock_code"]
                 for _, row in market_df.iterrows()}
    stock_names = list(stock_map.keys())

    # ── 등록 탭 ───────────────────────────────────────────────
    with tab_add:
        with st.form("trade_form", clear_on_submit=True):
            fc1, fc2 = st.columns(2)
            with fc1:
                trade_date  = st.date_input("거래일", value=date.today())
                stock_name  = st.selectbox("종목", stock_names)
                action      = st.selectbox("거래 유형", ["매수", "매도"])
            with fc2:
                entry_price = st.number_input("진입 단가 (원)", min_value=1,    value=50_000, step=100)
                exit_price  = st.number_input("청산 단가 (원, 매도 시 입력)", min_value=0, value=0, step=100)
                quantity    = st.number_input("수량 (주)",      min_value=1,    value=10,     step=1)

            reason      = st.text_area("매매 이유")
            result_memo = st.text_area("결과 메모")

            return_rate = None
            if action == "매도" and exit_price > 0 and entry_price > 0:
                return_rate = round((exit_price - entry_price) / entry_price * 100, 2)
                st.info(f"예상 수익률: **{return_rate:+.2f}%**")

            submitted = st.form_submit_button("💾 등록", use_container_width=True)

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

    # ── 조회 탭 ───────────────────────────────────────────────
    with tab_list:
        trades = get_trade_journal()
        if not trades:
            st.info("📭 등록된 거래 내역이 없습니다.")
            return

        df_t = pd.DataFrame(trades)

        # 요약 KPI
        buy_total  = df_t[df_t.get("action", pd.Series(dtype=str)) == "매수"]["entry_price"].fillna(0).mul(
                     df_t.get("quantity", pd.Series(0))).sum() if "action" in df_t.columns else 0
        kc1, kc2, kc3 = st.columns(3)
        kc1.metric("총 거래 건수", f"{len(df_t)}건")
        kc2.metric("매수 건수", f"{(df_t['action'] == '매수').sum()}건" if "action" in df_t.columns else "-")
        kc3.metric("매도 건수", f"{(df_t['action'] == '매도').sum()}건" if "action" in df_t.columns else "-")

        show_cols = [c for c in [
            "trade_date", "stock_name", "action",
            "entry_price", "exit_price", "quantity",
            "return_rate", "reason", "result_memo"
        ] if c in df_t.columns]

        rename = {
            "trade_date": "거래일", "stock_name": "종목명", "action": "유형",
            "entry_price": "진입가", "exit_price": "청산가", "quantity": "수량",
            "return_rate": "수익률(%)", "reason": "이유", "result_memo": "메모",
        }
        st.dataframe(
            df_t[show_cols].rename(columns=rename),
            use_container_width=True,
            height=400,
        )


# ════════════════════════════════════════════════════════════════
# 사이드바
# ════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("📈 주식 분석 도우미")
    st.caption("local-stock-assistant v0.1")
    st.divider()

    # DB 연결 상태
    try:
        from services.db_service import show_db_status
        show_db_status()
    except Exception as _e:
        st.warning(f"🟡 Mock 모드\n\n{_e}")

    st.divider()

    # 메뉴
    menu = st.radio(
        "메뉴 선택",
        ["📋 오늘의 후보 종목", "🔍 종목 상세 리포트", "📰 뉴스/이슈", "📝 매매일지"],
        label_visibility="collapsed",
    )

    st.divider()

    # 새로고침
    if st.button("🔄 데이터 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.session_state["refresh_key"] += 1
        st.rerun()

    st.caption(f"마지막 갱신: {st.session_state['refresh_key']}회")

# ════════════════════════════════════════════════════════════════
# 데이터 로드 & 라우팅
# ════════════════════════════════════════════════════════════════
with st.spinner("데이터 로딩 중..."):
    market_df, scored_df = _load_data(st.session_state["refresh_key"])

if menu == "📋 오늘의 후보 종목":
    render_candidates(market_df, scored_df)
elif menu == "🔍 종목 상세 리포트":
    render_report(market_df, scored_df)
elif menu == "📰 뉴스/이슈":
    render_news(market_df)
else:
    render_trade_journal(market_df)
