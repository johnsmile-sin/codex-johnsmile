"""
종목 상세 페이지 – 리포트 / 투자 판단
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

from data.mock_stocks import get_mock_stock_list
from modules.scoring import score_stocks
from modules.report import build_stock_report

st.set_page_config(page_title="종목 상세", page_icon="🔍", layout="wide")
st.title("🔍 종목 상세 분석")

# ─── 데이터 로드 ──────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_scored():
    df = get_mock_stock_list()
    return score_stocks(df)

df = load_scored()

# ─── 종목 선택 ────────────────────────────────────────────────
names = df["종목명"].tolist()
selected = st.selectbox("📌 종목 선택", names, index=0)
row = df[df["종목명"] == selected].iloc[0]

with st.spinner(f"{selected} 리포트 생성 중..."):
    report = build_stock_report(row)

# ─── 기본 정보 헤더 ───────────────────────────────────────────
info = report["기본정보"]
score_info = report["점수"]
judgment = report["투자판단"]

grade = score_info["등급"]
GRADE_COLOR = {"S": "#FF4B4B", "A": "#FF914D", "B": "#FFC300", "C": "#A8D8EA", "D": "#CCCCCC"}
badge_color = GRADE_COLOR.get(grade, "#ccc")

col_h1, col_h2, col_h3, col_h4 = st.columns([2, 1, 1, 1])
with col_h1:
    st.markdown(f"### {info['종목명']}  `{info['종목코드']}`")
    st.caption(f"{info['시장']} | {info['섹터']}")
with col_h2:
    change_color = "red" if info["등락률"] > 0 else "blue"
    st.metric("현재가", f"{info['현재가']:,}원", f"{info['등락률']:+.2f}%")
with col_h3:
    st.metric("종합점수", f"{score_info['총점']}점")
with col_h4:
    st.markdown(
        f"<div style='text-align:center;margin-top:8px'>"
        f"<span style='font-size:14px'>등급</span><br>"
        f"<span style='background:{badge_color};color:white;font-size:28px;"
        f"font-weight:bold;padding:4px 16px;border-radius:8px'>{grade}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ─── 탭 구성 ─────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["🎯 투자 판단", "📐 기술 지표", "💰 재무 요약", "📰 뉴스"])

# ── TAB 1: 투자 판단 ─────────────────────────────────────────
with tab1:
    opinion = judgment["opinion"]
    confidence = judgment["confidence"]

    op_color = {"매수 검토": "#27AE60", "관망": "#F39C12", "매도 검토": "#E74C3C"}
    bg = op_color.get(opinion, "#888")

    st.markdown(
        f"<div style='background:{bg};color:white;padding:16px 24px;"
        f"border-radius:12px;font-size:22px;font-weight:bold;text-align:center'>"
        f"🏷️ {opinion}  (신뢰도: {confidence})</div>",
        unsafe_allow_html=True,
    )
    st.markdown("")

    col_j1, col_j2 = st.columns(2)
    with col_j1:
        st.subheader("📋 판단 근거")
        st.write(judgment["reason"])

        st.subheader("🛡️ 전략")
        st.write(judgment["strategy"])

    with col_j2:
        st.subheader("⚠️ 리스크 요인")
        for r in judgment["risk_factors"]:
            st.warning(r)

    # 점수 레이더 차트
    st.subheader("🕸️ 점수 항목별 분해")
    breakdown = score_info["항목별"]
    categories = list(breakdown.keys())
    values = list(breakdown.values())
    values_closed = values + [values[0]]
    categories_closed = categories + [categories[0]]

    fig_radar = go.Figure(go.Scatterpolar(
        r=values_closed, theta=categories_closed,
        fill="toself", fillcolor="rgba(255,75,75,0.2)",
        line=dict(color="#FF4B4B"),
        name="점수",
    ))
    fig_radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 15])),
        showlegend=False, height=350,
    )
    st.plotly_chart(fig_radar, use_container_width=True)

# ── TAB 2: 기술 지표 ─────────────────────────────────────────
with tab2:
    tech = report["기술지표"]
    col_t1, col_t2 = st.columns(2)

    with col_t1:
        st.metric("RSI", f"{tech['RSI']}")
        rsi = tech["RSI"]
        rsi_label = "과매도" if rsi < 30 else ("과매수" if rsi > 70 else "정상구간")
        rsi_color = "inverse" if rsi > 70 else "normal"
        st.progress(int(rsi) / 100)
        st.caption(f"RSI 해석: {rsi_label}")

        st.metric("볼린저밴드 위치", f"{tech['볼린저밴드위치']}%")
        bb = tech["볼린저밴드위치"]
        st.progress(int(bb) / 100)
        bb_label = "하단 근처 (매수 신호)" if bb < 30 else ("상단 근처 (매도 신호)" if bb > 70 else "중간")
        st.caption(f"볼린저밴드: {bb_label}")

    with col_t2:
        macd_icon = "✅" if tech["MACD신호"] == "골든크로스" else ("❌" if tech["MACD신호"] == "데드크로스" else "➖")
        st.metric("MACD 신호", f"{macd_icon} {tech['MACD신호']}")

        ma_icon = "✅" if tech["MA배열"] == "정배열" else "❌"
        st.metric("이동평균 배열", f"{ma_icon} {tech['MA배열']}")

        st.markdown("---")
        st.markdown("""
        **지표 해석 가이드**
        - RSI 30~50: 매수 기회 구간
        - MACD 골든크로스: 단기 상승 신호
        - 정배열: MA5 > MA20 (상승 추세)
        - 볼린저밴드 하단: 매수 검토 구간
        """)

    # 52주 고저 게이지
    st.subheader("📏 52주 고저 대비 현재가")
    high52 = info["52주고"]
    low52 = info["52주저"]
    current = info["현재가"]
    position_pct = (current - low52) / (high52 - low52) * 100 if high52 != low52 else 50

    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=position_pct,
        title={"text": "52주 레인지 내 위치 (%)"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#FF4B4B"},
            "steps": [
                {"range": [0, 30], "color": "#EAF4FB"},
                {"range": [30, 70], "color": "#D5F5E3"},
                {"range": [70, 100], "color": "#FDEDEC"},
            ],
        },
    ))
    fig_gauge.update_layout(height=300)
    st.plotly_chart(fig_gauge, use_container_width=True)
    st.caption(f"52주 저가: {low52:,}원 | 현재가: {current:,}원 | 52주 고가: {high52:,}원")

# ── TAB 3: 재무 요약 ─────────────────────────────────────────
with tab3:
    fin = report["재무정보"]

    col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
    col_f1.metric("PER", f"{fin['per']}배")
    col_f2.metric("PBR", f"{fin['pbr']}배")
    col_f3.metric("ROE", f"{fin['roe']}%")
    col_f4.metric("부채비율", f"{fin['debt_ratio']}%")
    col_f5.metric("배당수익률", f"{fin['dividend_yield']}%")

    st.markdown("")
    col_fg1, col_fg2 = st.columns(2)
    with col_fg1:
        st.metric("매출 성장률(YoY)", f"{fin['yoy_revenue_growth']:+.1f}%")
    with col_fg2:
        st.metric("영업이익 성장률(YoY)", f"{fin['yoy_profit_growth']:+.1f}%")

    # 분기 매출/영업이익 차트
    st.subheader("📊 분기별 실적")
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        x=fin["quarters"], y=fin["revenue_q"],
        name="매출(조원)", marker_color="#4A90D9",
    ))
    fig_bar.add_trace(go.Bar(
        x=fin["quarters"], y=fin["profit_q"],
        name="영업이익(조원)", marker_color="#27AE60",
    ))
    fig_bar.update_layout(
        barmode="group", height=300,
        margin=dict(l=0, r=0, t=20, b=0),
        yaxis_title="금액 (조원)",
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    st.info(f"📝 재무 요약: {fin['comment']}")
    if fin["source"] == "Mock":
        st.caption("⚠️ Mock 데이터 – 실제 재무제표와 다를 수 있습니다.")

# ── TAB 4: 뉴스 ──────────────────────────────────────────────
with tab4:
    news = report["뉴스"]
    sentiment_color = {
        "긍정적": "success",
        "다소 긍정적": "success",
        "중립적": "info",
        "부정적": "error",
    }
    alert_fn = getattr(st, sentiment_color.get(news["sentiment"], "info"))
    alert_fn(f"뉴스 감성 분석: **{news['sentiment']}**")

    st.subheader("📰 주요 뉴스 헤드라인")
    for h in news["headlines"]:
        st.markdown(f"- {h}")

    st.subheader("📋 뉴스 요약")
    st.write(news["summary"])

    if news["source"] == "Mock":
        st.caption("⚠️ Mock 뉴스 – 실제 뉴스와 다릅니다.")
