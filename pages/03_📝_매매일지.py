"""
매매일지 페이지 – 거래 기록 등록 / 조회 / 삭제
"""

import streamlit as st
import pandas as pd
from datetime import date

from modules.db import insert_trade, fetch_trades, delete_trade, is_mock
from data.mock_stocks import get_mock_stock_list

st.set_page_config(page_title="매매일지", page_icon="📝", layout="wide")
st.title("📝 매매일지")

if is_mock():
    st.info("ℹ️ Mock 모드: 기록은 앱 재시작 시 초기화됩니다. Supabase 연결 시 영구 저장됩니다.")

# ─── 종목 목록 캐시 ───────────────────────────────────────────
@st.cache_data(ttl=600)
def get_stock_names():
    df = get_mock_stock_list()
    return {row["종목명"]: row["종목코드"] for _, row in df.iterrows()}

stock_map = get_stock_names()
stock_names = list(stock_map.keys())

# ─── 탭 ──────────────────────────────────────────────────────
tab_add, tab_list = st.tabs(["✏️ 거래 등록", "📋 거래 조회"])

# ── TAB 1: 등록 ──────────────────────────────────────────────
with tab_add:
    st.subheader("새 거래 기록 등록")

    with st.form("trade_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            trade_date = st.date_input("거래일", value=date.today())
            stock_name = st.selectbox("종목", stock_names)
            trade_type = st.selectbox("거래 유형", ["매수", "매도"])

        with col2:
            price = st.number_input("거래 단가 (원)", min_value=1, value=50000, step=100)
            quantity = st.number_input("수량 (주)", min_value=1, value=10, step=1)
            fee = st.number_input("수수료 (원)", min_value=0, value=0, step=100)

        memo = st.text_area("메모 (선택)", placeholder="거래 이유, 전략, 감상 등을 자유롭게 기록하세요.")

        submitted = st.form_submit_button("💾 등록", use_container_width=True)

    if submitted:
        code = stock_map[stock_name]
        total_amount = price * quantity
        record = {
            "날짜": str(trade_date),
            "종목코드": code,
            "종목명": stock_name,
            "거래유형": trade_type,
            "단가": price,
            "수량": quantity,
            "총금액": total_amount,
            "수수료": fee,
            "메모": memo,
        }
        result = insert_trade(record)
        if result.get("error"):
            st.error(f"등록 실패: {result['error']}")
        else:
            st.success(f"✅ {trade_date} | {stock_name} {trade_type} {quantity}주 @ {price:,}원 등록 완료!")

    # 계산 미리보기
    st.markdown("---")
    st.subheader("🧮 거래 금액 미리보기")
    preview_price = st.number_input("단가", min_value=1, value=75000, key="prev_p")
    preview_qty = st.number_input("수량", min_value=1, value=10, key="prev_q")
    preview_fee = st.number_input("수수료", min_value=0, value=150, key="prev_f")
    total = preview_price * preview_qty
    net = total + preview_fee
    c1, c2, c3 = st.columns(3)
    c1.metric("거래 금액", f"{total:,}원")
    c2.metric("수수료", f"{preview_fee:,}원")
    c3.metric("실제 비용", f"{net:,}원")

# ── TAB 2: 조회 ──────────────────────────────────────────────
with tab_list:
    st.subheader("거래 기록 조회")

    filter_col1, filter_col2 = st.columns([2, 1])
    with filter_col1:
        filter_stock = st.selectbox(
            "종목 필터", ["전체"] + stock_names, key="filter_stock"
        )
    with filter_col2:
        filter_type = st.selectbox("거래 유형", ["전체", "매수", "매도"], key="filter_type")

    code_filter = stock_map.get(filter_stock) if filter_stock != "전체" else None
    trades = fetch_trades(code=code_filter)

    if not trades:
        st.info("📭 등록된 거래 내역이 없습니다. '거래 등록' 탭에서 기록을 추가하세요.")
    else:
        df_trades = pd.DataFrame(trades)

        if filter_type != "전체" and "거래유형" in df_trades.columns:
            df_trades = df_trades[df_trades["거래유형"] == filter_type]

        # 요약 KPI
        if "총금액" in df_trades.columns and "거래유형" in df_trades.columns:
            buy_total = df_trades[df_trades["거래유형"] == "매수"]["총금액"].sum()
            sell_total = df_trades[df_trades["거래유형"] == "매도"]["총금액"].sum()
            col_s1, col_s2, col_s3 = st.columns(3)
            col_s1.metric("총 거래 건수", f"{len(df_trades)}건")
            col_s2.metric("총 매수 금액", f"{buy_total:,.0f}원")
            col_s3.metric("총 매도 금액", f"{sell_total:,.0f}원")
            st.markdown("")

        # 테이블 표시
        disp_cols = [c for c in ["날짜", "종목명", "거래유형", "단가", "수량", "총금액", "수수료", "메모", "id"]
                     if c in df_trades.columns]
        st.dataframe(df_trades[disp_cols], use_container_width=True, height=400)

        # 삭제
        st.markdown("---")
        st.subheader("🗑️ 기록 삭제")
        if "id" in df_trades.columns:
            del_id = st.number_input("삭제할 ID", min_value=1, step=1)
            if st.button("삭제", type="secondary"):
                success = delete_trade(int(del_id))
                if success:
                    st.success(f"ID {del_id} 삭제 완료. 페이지를 새로고침하세요.")
                else:
                    st.error("삭제 실패: 해당 ID가 없습니다.")
        else:
            st.caption("삭제 기능은 ID 컬럼이 있을 때 사용 가능합니다.")
