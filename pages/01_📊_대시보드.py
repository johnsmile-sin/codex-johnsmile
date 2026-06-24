"""
대시보드 페이지 – 종목 점수 랭킹 및 섹터 현황
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from data.mock_stocks import get_mock_stock_list
from modules.scoring import score_stocks

st.set_page_config(page_title="대시보드", page_icon="📊", layout="wide")
st.title("📊 오늘의 종목 점수 랭킹")

# ─── 데이터 로드 ──────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_scored():
    df = get_mock_stock_list()
    return score_stocks(df)

with st.spinner("종목 데이터 분석 중..."):
    df = load_scored()

# ─── 상단 요약 KPI ────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("분석 종목 수", f"{len(df)}개")
with col2:
    top5_avg = df.head(5)["총점"].mean()
    st.metric("상위 5종목 평균점수", f"{top5_avg:.1f}점")
with col3:
    rising = (df["change_pct"] > 0).sum()
    st.metric("상승 종목", f"{rising}개", f"{rising - (len(df) - rising):+d}")
with col4:
    s_grade = (df["등급"] == "S").sum()
    st.metric("S등급 종목", f"{s_grade}개")

st.markdown("---")

# ─── 등급 컬러 맵 ─────────────────────────────────────────────
GRADE_COLOR = {"S": "#FF4B4B", "A": "#FF914D", "B": "#FFC300", "C": "#A8D8EA", "D": "#CCCCCC"}

def grade_badge(g):
    color = GRADE_COLOR.get(str(g), "#ccc")
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-weight:bold">{g}</span>'

# ─── 종목 랭킹 테이블 ─────────────────────────────────────────
st.subheader("🏆 종목 점수 순위")

display_cols = ["종목코드", "종목명", "섹터", "시장", "current_price", "change_pct", "총점", "등급"]
rename_map = {
    "current_price": "현재가",
    "change_pct": "등락률(%)",
}
disp = df[display_cols].rename(columns=rename_map).copy()
disp["등락률(%)"] = disp["등락률(%)"].apply(lambda x: f"{x:+.2f}%")
disp["현재가"] = disp["현재가"].apply(lambda x: f"{x:,}원")

st.dataframe(
    disp,
    use_container_width=True,
    height=500,
    column_config={
        "총점": st.column_config.ProgressColumn("총점", min_value=0, max_value=100, format="%.1f"),
        "등급": st.column_config.TextColumn("등급"),
    },
)

st.markdown("---")

# ─── 차트 영역 ────────────────────────────────────────────────
col_l, col_r = st.columns(2)

with col_l:
    st.subheader("📈 섹터별 평균 점수")
    sector_avg = df.groupby("섹터")["총점"].mean().sort_values(ascending=True).reset_index()
    fig = px.bar(
        sector_avg, x="총점", y="섹터", orientation="h",
        color="총점", color_continuous_scale="RdYlGn",
        range_color=[30, 80],
        labels={"총점": "평균 점수", "섹터": ""},
    )
    fig.update_layout(height=400, margin=dict(l=0, r=0, t=20, b=0))
    st.plotly_chart(fig, use_container_width=True)

with col_r:
    st.subheader("🎯 등급 분포")
    grade_cnt = df["등급"].value_counts().reset_index()
    grade_cnt.columns = ["등급", "종목수"]
    fig2 = px.pie(
        grade_cnt, names="등급", values="종목수",
        color="등급",
        color_discrete_map=GRADE_COLOR,
        hole=0.4,
    )
    fig2.update_layout(height=400, margin=dict(l=0, r=0, t=20, b=0))
    st.plotly_chart(fig2, use_container_width=True)

# ─── 점수 vs 등락률 산점도 ───────────────────────────────────
st.subheader("📉 점수 vs 등락률 분포")
fig3 = px.scatter(
    df, x="총점", y="change_pct",
    color="섹터", size="volume",
    hover_data=["종목명", "등급"],
    labels={"총점": "종합점수", "change_pct": "당일 등락률(%)"},
    size_max=30,
)
fig3.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
fig3.update_layout(height=400)
st.plotly_chart(fig3, use_container_width=True)
