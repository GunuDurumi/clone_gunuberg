import streamlit as st
import pandas as pd
import plotly.graph_objects as go
# make_subplots는 이제 쓰지 않으므로 삭제해도 되지만, 혹시 모르니 남겨둡니다.
from plotly.subplots import make_subplots

from src.database import DataRepository
from src.utils.stock.processor import StockAnalysisProcessor
from src.utils.ticker_manager import TickerManager

# 1. 페이지 설정
st.set_page_config(page_title="Stock Deep Dive", layout="wide", page_icon="📈")

# 스타일 커스텀
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 2rem;}
    h1 {margin-bottom: 0.5rem;}
</style>
""", unsafe_allow_html=True)

st.title("📈 주식 실질 가치 심층 분석")
st.caption("Nominal Price vs Real Value (Inflation & Currency Adjusted)")

# 2. 공통 Repository 및 Processor 생성
repo = DataRepository()
processor = StockAnalysisProcessor(repo)
ticker_manager = TickerManager(repo)

# -------------------------------------------------------------------
# 🔍 사이드바: 종목 검색
# -------------------------------------------------------------------
st.sidebar.header("🔍 종목 검색")

ticker_map = ticker_manager.get_ticker_map()

if not ticker_map:
    st.sidebar.warning("종목 리스트를 불러오는 중입니다. 잠시 후 다시 시도하거나 직접 입력하세요.")
    target_ticker = st.sidebar.text_input("티커 직접 입력", value="AAPL").upper()
    selected_option = target_ticker
else:
    search_keys = list(ticker_map.keys())
    default_idx = 0
    for i, k in enumerate(search_keys):
        if "AAPL" in k:
            default_idx = i
            break
            
    selected_option = st.sidebar.selectbox(
        "종목 선택 (전 세계)",
        options=search_keys,
        index=default_idx
    )
    target_ticker = ticker_map[selected_option]

if st.sidebar.button("🔄 종목 리스트 최신화"):
    ticker_manager.force_update()
    st.rerun()

# -------------------------------------------------------------------
# 📊 메인 분석 로직
# -------------------------------------------------------------------
if target_ticker:
    with st.spinner(f"'{selected_option}' 데이터 정밀 분석 중..."):
        df = processor.get_analysis_data(target_ticker)

    if df.empty:
        st.error(f"❌ '{target_ticker}' 데이터를 가져올 수 없습니다. (상장 폐지 또는 티커 오류)")
    else:
        # --- [Step 1] 핵심 지표 (Metrics) ---
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        
        m1, m2, m3 = st.columns(3)
        
        m1.metric(
            "현재 주가 (Nominal)", 
            f"{last['close']:,.2f}", 
            f"{(last['close']-prev['close'])/prev['close']*100:.2f}%"
        )
        
        m2.metric(
            "실질 주가 (인플레 제거)", 
            f"{last['close_real']:,.2f}", 
            f"{(last['close_real']-prev['close_real'])/prev['close_real']*100:.2f}%", 
            help="물가 상승분을 제거한 구매력 기준 가치"
        )
        
        label = last.get('currency_label', 'Converted')
        m3.metric(
            f"공정 가치 ({label})", 
            f"{last['close_currency_neutral']:,.2f}", 
            f"{(last['close_currency_neutral']-prev['close_currency_neutral'])/prev['close_currency_neutral']*100:.2f}%",
            help="환율 및 달러 인덱스(DXY) 거품을 제거한 본질 가치"
        )
        
        st.divider()

        # --- [Step 2] 차트 뷰 컨트롤 ---
        c_opt1, c_opt2 = st.columns([1, 4])
        with c_opt1:
            view_mode = st.radio("데이터 주기", ["Monthly (빠름)", "Daily (상세)"], index=0, horizontal=True)
        
        if "Monthly" in view_mode:
            chart_df = df.resample('M', on='date').last().reset_index()
        else:
            chart_df = df

        # --- [Step 3] 탭별 고성능 차트 그리기 ---
        tab1, tab2 = st.tabs(["💸 물가(Inflation) 영향", "💱 환율(Currency) 영향"])
        
        # 1️⃣ 탭 1: 인플레이션 (Real vs Nominal)
        with tab1:
            st.markdown("##### 📉 물가를 뺀 '진짜 주가'는 얼마인가?")
            fig1 = go.Figure()
            
            fig1.add_trace(go.Scattergl(
                x=chart_df['date'], y=chart_df['close'], 
                name="명목 주가 (눈에 보이는 가격)", 
                line=dict(color='gray', width=1)
            ))
            
            fig1.add_trace(go.Scattergl(
                x=chart_df['date'], y=chart_df['close_real'], 
                name="실질 주가 (물가 반영)", 
                line=dict(color='#00C853', width=2), 
                fill='tozeroy', 
                fillcolor='rgba(0, 200, 83, 0.1)'
            ))
            
            fig1.update_layout(
                height=500, hovermode="x unified",
                legend=dict(orientation="h", y=1.02, x=1, xanchor="right"),
                xaxis=dict(rangeslider=dict(visible=True), type="date")
            )
            st.plotly_chart(fig1, use_container_width=True)
            
        # 2️⃣ 탭 2: 환율 (Currency Adjusted) - [핵심 수정: 단일 축 & Gap 표시]
        with tab2:
            st.markdown("##### 🌏 환율/달러 거품을 걷어낸 '담백한 주가'는?")
            
            # [변경] make_subplots 제거 -> 단일 Figure로 통일
            # 이유: 축을 하나로 써야 두 그래프 사이의 'Gap'이 왜곡 없이 보임
            fig2 = go.Figure()
            
            # A. 원래 주가 (Nominal) - 회색 점선
            fig2.add_trace(go.Scattergl(
                x=chart_df['date'], y=chart_df['close'], 
                name=f"현재 주가 (거품 포함)", 
                line=dict(color='gray', width=1, dash='dot') 
            ))
            
            # B. 공정 가치 (Fair Value) - 파란 실선 & Gap 색칠
            fig2.add_trace(go.Scattergl(
                x=chart_df['date'], y=chart_df['close_currency_neutral'], 
                name=f"공정 가치 ({label})", 
                line=dict(color='#2962FF', width=2),
                fill='tonexty', # 두 선 사이를 칠해서 'Gap' 시각화
                fillcolor='rgba(41, 98, 255, 0.1)' 
            ))
            
            fig2.update_layout(
                height=500, hovermode="x unified",
                legend=dict(orientation="h", y=1.02, x=1, xanchor="right"),
                xaxis=dict(rangeslider=dict(visible=True), type="date"),
                yaxis=dict(title="주가 (Price)") # 단일 축 사용
            )
            
            st.plotly_chart(fig2, use_container_width=True)

            # [Gap 수치화] 그래프 하단에 괴리율 명시
            curr_price = last['close']
            fair_price = last['close_currency_neutral']
            gap = curr_price - fair_price
            gap_pct = (gap / fair_price) * 100
            
            c_gap1, c_gap2 = st.columns([1, 3])
            
            with c_gap1:
                st.metric(
                    "괴리율 (Bubble Gap)", 
                    f"{gap_pct:.1f}%", 
                    f"{gap:,.0f}",
                    delta_color="inverse" # 양수(거품)면 빨간색, 음수(할인)면 초록색
                )
            
            with c_gap2:
                if gap > 0:
                    st.warning(f"🚨 현재 주가는 공정 가치보다 **{gap_pct:.1f}% 고평가(거품)** 상태입니다. (환율/달러 영향)")
                else:
                    st.success(f"✅ 현재 주가는 공정 가치보다 **{abs(gap_pct):.1f}% 저평가(할인)** 상태입니다. (환율/달러 영향)")

        # (옵션) 상세 데이터
        with st.expander("📊 상세 데이터 테이블 보기"):
            st.dataframe(df.sort_values('date', ascending=False).head(100), use_container_width=True)