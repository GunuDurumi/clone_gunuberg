import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.database import DataRepository
from src.utils.forex_processor import ForexProcessor
from src.utils.gwcpi.processor import GWCPIProcessor

# 1. 페이지 설정
st.set_page_config(page_title="Gunuberg Dashboard", layout="wide", page_icon="🚀")

# 2. 스타일 커스텀 (여백 줄이기 등)
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 0rem;}
    h1 {margin-bottom: 0rem;}
</style>
""", unsafe_allow_html=True)

st.title("🚀 Gunuberg Dashboard")
st.caption("Macro Insights: Real Value vs Inflation (Auto-Sync Mode)")

# 3. 데이터 로드 및 초기화
@st.cache_resource
def get_processors():
    repo = DataRepository() # 이제 여기서 HF 동기화/자동갱신 다 알아서 함
    return ForexProcessor(repo), GWCPIProcessor(repo)

forex_processor, gwcpi_processor = get_processors()

# -------------------------------------------------------------------
# 🔄 데이터 수집 (스피너는 데이터가 없을 때만 돌도록 됨)
# -------------------------------------------------------------------
with st.spinner("데이터 동기화 및 분석 중..."):
    # 옵션 없이 호출해도 Smart Repository가 알아서 쿨타임/이어붙이기 판단
    df_krw = forex_processor.get_real_krw_value()
    df_cpi = gwcpi_processor.get_gwcpi()

# -------------------------------------------------------------------
# 📊 데이터 가공 (Merge & Normalize)
# -------------------------------------------------------------------
if not df_krw.empty and not df_cpi.empty:
    # 1. 병합
    merged = pd.merge(df_krw, df_cpi, on='date', how='outer').sort_values('date')
    
    # 2. 결측치 보간 (선형 보간 -> 앞뒤 채우기)
    cols = ['real_krw_score', 'gwcpi', 'close_dxy', 'close_krw']
    for c in cols:
        if c in merged.columns:
            merged[c] = merged[c].interpolate(method='linear').ffill().bfill()

    # 3. 정규화 (0~100)
    def normalize(series):
        return ((series - series.min()) / (series.max() - series.min())) * 100

    merged['norm_krw'] = normalize(merged['real_krw_score'])
    merged['norm_gwcpi'] = normalize(merged['gwcpi'])

    # -------------------------------------------------------------------
    # 📈 섹션 1: 핵심 지표 (Metrics) - 최상단 배치
    # -------------------------------------------------------------------
    latest = merged.iloc[-1]
    prev = merged.iloc[-2] if len(merged) > 1 else latest

    # 14년 전 비교 데이터
    date_14y_ago = pd.to_datetime(latest['date']) - pd.DateOffset(years=14)
    past_14y = merged[merged['date'] <= date_14y_ago]
    inflation_14y = 0.0
    if not past_14y.empty:
        past_val = past_14y.iloc[-1]['gwcpi']
        inflation_14y = ((latest['gwcpi'] / past_val) - 1) * 100

    # 5개의 컬럼으로 구성
    k1, k2, k3, k4, k5 = st.columns(5)
    
    k1.metric("Real KRW Score", f"{latest['norm_krw']:.1f}", f"{latest['norm_krw']-prev['norm_krw']:.2f}", help="원화 실질 가치 (0~100)")
    k2.metric("GWCPI (Inflation)", f"{latest['gwcpi']:.1f}", f"{latest['gwcpi']-prev['gwcpi']:.2f}", delta_color="inverse", help="글로벌 가중 물가 지수")
    k3.metric("USD/KRW", f"{latest['close_krw']:,.0f}원", f"{latest['close_krw']-prev['close_krw']:.0f}원", delta_color="inverse")
    k4.metric("Dollar Index (DXY)", f"{latest['close_dxy']:.2f}", f"{latest['close_dxy']-prev['close_dxy']:.2f}")
    k5.metric("14Y Inflation", f"{inflation_14y:.1f}%", f"{date_14y_ago.year}년 대비", delta_color="inverse", help="14년 간 누적 물가 상승률")

    st.divider()

    # -------------------------------------------------------------------
    # 📉 섹션 2: 고성능 차트 (Plotly WebGL)
    # -------------------------------------------------------------------
    
    # [Lag 해결] 보기 설정 (일간/월간)
    col_opt1, col_opt2 = st.columns([1, 5])
    with col_opt1:
        view_mode = st.radio("데이터 주기", ["Monthly (빠름)", "Daily (상세)"], index=0, horizontal=True)
    
    # 데이터 다운샘플링 (Lag 해결의 핵심)
    if "Monthly" in view_mode:
        chart_df = merged.resample('M', on='date').last().reset_index()
    else:
        chart_df = merged # 전체 데이터 (Daily)

    # 차트 그리기
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # A. 원화 실질 가치 (Red)
    fig.add_trace(
        go.Scattergl( # Scattergl 사용 (GPU 가속)
            x=chart_df['date'], y=chart_df['norm_krw'],
            name="원화 실질 가치 (Real KRW)",
            line=dict(color='#FF4B4B', width=2),
            mode='lines'
        ), secondary_y=False
    )

    # B. GWCPI (Blue)
    fig.add_trace(
        go.Scattergl(
            x=chart_df['date'], y=chart_df['norm_gwcpi'],
            name="글로벌 물가 (GWCPI)",
            line=dict(color='#1E88E5', width=2),
            mode='lines'
        ), secondary_y=False # 같은 축 사용 (0~100 정규화했으므로)
    )

    # C. 환율 (Grey, 배경) - 선택 사항
    fig.add_trace(
        go.Scattergl(
            x=chart_df['date'], y=chart_df['close_krw'],
            name="환율 (USD/KRW)",
            line=dict(color='rgba(128, 128, 128, 0.3)', width=1, dash='dot'),
            hoverinfo='y'
        ), secondary_y=True
    )

    # 레이아웃 최적화
    fig.update_layout(
        height=500,
        hovermode="x unified",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(
            rangeslider=dict(visible=True), # 하단 스크롤바
            type="date"
        )
    )
    
    # 축 설정
    fig.update_yaxes(title_text="Score (0~100)", secondary_y=False, showgrid=True, gridcolor='rgba(200,200,200,0.2)')
    fig.update_yaxes(title_text="환율 (KRW)", secondary_y=True, showgrid=False)

    st.plotly_chart(fig, use_container_width=True)
    
    st.info("💡 **팁**: 하단의 'Range Slider'를 조절하여 원하는 기간을 확대해 볼 수 있습니다. 'Monthly' 모드를 사용하면 로딩이 훨씬 빠릅니다.")

else:
    st.warning("데이터를 불러올 수 없습니다. API 설정이나 네트워크 연결을 확인해주세요.")
    st.write("Tip: `src/config.py`의 `FRED_API_KEY`와 인터넷 연결을 확인하세요.")