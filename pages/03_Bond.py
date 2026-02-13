import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from src.database import DataRepository
from src.utils.gwcpi.processor import GWCPIProcessor

# 1. 페이지 설정
st.set_page_config(page_title="Buffett Bond Screener", layout="wide", page_icon="🎩")

# 스타일 커스텀
st.markdown("""
<style>
    .metric-card {background-color: #f0f2f6; padding: 15px; border-radius: 10px; margin-bottom: 10px;}
    h1 {margin-bottom: 0.5rem;}
</style>
""", unsafe_allow_html=True)

st.title("🎩 워렌 버핏의 채권 스캐너")
st.caption("Warren Buffett's Medium-Term Bond Strategy: Safety, Yield, and Duration")

# 2. 데이터 준비
repo = DataRepository()
gwcpi_processor = GWCPIProcessor(repo)

@st.cache_data(ttl=3600)
def get_bond_data():
    # 주요 국채 및 채권 ETF 티커
    # ^IRX: 13주(3개월), ^FVX: 5년, ^TNX: 10년, ^TYX: 30년
    tickers = {
        "3M T-Bill (초단기)": "^IRX",
        "2Y Note (단기)": "^IPX", # 야후에서 2년물 티커가 종종 바뀜, 대안으로 계산 필요할 수 있음. 일단 주요 지표 사용
        "5Y Note (중기)": "^FVX",
        "10Y Note (장기)": "^TNX",
        "30Y Bond (초장기)": "^TYX"
    }
    
    # 회사채 ETF (참고용)
    etfs = {
        "SHY (1-3년 국채)": "SHY",
        "IEF (7-10년 국채)": "IEF",
        "LQD (투자등급 회사채)": "LQD",
        "HYG (하이일드 - 버핏 비선호)": "HYG"
    }

    data = []
    
    # 1. 국채 금리 수집
    for name, ticker in tickers.items():
        try:
            # 국채 지수는 가격이 아니라 '수익률' 자체가 종가임 (단위: %)
            # 예: 4.5 -> 4.5%
            hist = yf.Ticker(ticker).history(period="5d")
            if not hist.empty:
                yield_val = hist['Close'].iloc[-1]
                prev_yield = hist['Close'].iloc[-2]
                data.append({
                    "Type": "Treasury",
                    "Name": name,
                    "Ticker": ticker,
                    "Yield (%)": yield_val,
                    "Change": yield_val - prev_yield,
                    "Duration_Risk": "High" if "30Y" in name or "10Y" in name else "Low"
                })
        except: pass
        
    # 2. ETF 배당 수익률(Yield) 수집
    for name, ticker in etfs.items():
        try:
            info = yf.Ticker(ticker).info
            # yield는 0.045 형태로 옴 -> 4.5로 변환
            yield_val = info.get('yield', 0) * 100 
            if yield_val == 0:
                # 데이터 없을 경우 trailingAnnualDividendYield 시도
                yield_val = info.get('trailingAnnualDividendYield', 0) * 100
                
            data.append({
                "Type": "ETF",
                "Name": name,
                "Ticker": ticker,
                "Yield (%)": yield_val,
                "Change": 0.0, # ETF는 금리 변화 추적 어려움
                "Duration_Risk": "Medium"
            })
        except: pass

    return pd.DataFrame(data)

# 데이터 로드
df_bonds = get_bond_data()

# 최신 CPI (인플레이션) 가져오기
with st.spinner("인플레이션 데이터 동기화 중..."):
    df_cpi = gwcpi_processor.get_gwcpi()
    if not df_cpi.empty:
        # 최근 1년 상승률 계산 (YoY)
        latest_cpi = df_cpi['gwcpi'].iloc[-1]
        year_ago_cpi = df_cpi['gwcpi'].iloc[-13] if len(df_cpi) > 13 else df_cpi['gwcpi'].iloc[0]
        inflation_rate = ((latest_cpi - year_ago_cpi) / year_ago_cpi) * 100
    else:
        inflation_rate = 3.0 # Fallback

# -------------------------------------------------------------------
# 📊 섹션 1: 버핏의 눈 (Macro View)
# -------------------------------------------------------------------
col1, col2, col3 = st.columns(3)

col1.metric("현재 인플레이션 (CPI YoY)", f"{inflation_rate:.2f}%", help="채권 금리가 이보다 낮으면 실질 손실입니다.")
col2.metric("버핏의 기준 금리 (Hurdle)", "4.00%", help="버핏은 절대 수익률이 4% 미만이면 채권을 쳐다보지도 않습니다.")

# 가장 금리가 높은 국채 찾기
treasuries = df_bonds[df_bonds['Type'] == "Treasury"]
if not treasuries.empty:
    best_bond = treasuries.loc[treasuries['Yield (%)'].idxmax()]
    col3.metric(f"현재 최고 수익률 ({best_bond['Name']})", f"{best_bond['Yield (%)']:.2f}%", f"{best_bond['Change']:.2f}")

st.divider()

# -------------------------------------------------------------------
# 🕵️‍♂️ 섹션 2: 버핏 스코어링 (Buffett Scoring Logic)
# -------------------------------------------------------------------
st.subheader("🕵️‍♂️ 채권 판독기 (Buffett Test)")
st.caption("버핏의 3가지 조건: ①인플레 방어(실질금리 +) ②만기 10년 이하(리스크 관리) ③4% 이상 고금리")

# 판독 로직
results = []
for index, row in df_bonds.iterrows():
    score = 0
    reasons = []
    
    # 1. Yield Check (vs Inflation)
    real_yield = row['Yield (%)'] - inflation_rate
    if real_yield > 0.5: # 실질 금리 0.5% 이상
        score += 1
        reasons.append("✅ 인플레 방어 가능")
    else:
        reasons.append("❌ 인플레 못 이김")
        
    # 2. Hurdle Check (vs 4%)
    if row['Yield (%)'] >= 4.0:
        score += 1
        reasons.append("✅ 매력적인 금리(4%↑)")
    else:
        reasons.append("❌ 금리 매력 낮음")
        
    # 3. Duration Check (버핏은 장기채 싫어함)
    if "30Y" in row['Name']:
        score -= 1 # 감점
        reasons.append("⚠️ 초장기채 위험(비선호)")
    elif "10Y" in row['Name']:
        reasons.append("⚠️ 장기채 주의")
    else:
        score += 1
        reasons.append("✅ 만기 적절(중단기)")
        
    # 최종 판정
    if score >= 3:
        verdict = "💎 강력 매수 (Buffett Pick)"
        color = "#e6fffa" # Light Green
    elif score >= 1:
        verdict = "🤔 관망 (Hold)"
        color = "#fffaf0" # Light Orange
    else:
        verdict = "🗑️ 매도/회피 (Avoid)"
        color = "#fff5f5" # Light Red
        
    results.append({
        "상품명": row['Name'],
        "현재 금리": f"{row['Yield (%)']:.2f}%",
        "실질 금리": f"{real_yield:.2f}%",
        "판정 결과": verdict,
        "상세 분석": ", ".join(reasons),
        "_color": color
    })

df_result = pd.DataFrame(results)

# 테이블 그리기 (Color 적용)
for i, r in df_result.iterrows():
    with st.container():
        st.markdown(f"""
        <div style="background-color: {r['_color']}; padding: 15px; border-radius: 10px; margin-bottom: 10px; border: 1px solid #eee;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h4 style="margin:0;">{r['상품명']}</h4>
                    <span style="font-size: 0.9em; color: gray;">{r['상세 분석']}</span>
                </div>
                <div style="text-align: right;">
                    <h3 style="margin:0; color: #333;">{r['현재 금리']}</h3>
                    <div style="font-weight: bold;">{r['판정 결과']}</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# -------------------------------------------------------------------
# 📈 섹션 3: 수익률 곡선 (Yield Curve)
# -------------------------------------------------------------------
st.divider()
c1, c2 = st.columns([2, 1])

with c1:
    st.subheader("📉 미국 국채 수익률 곡선 (Yield Curve)")
    
    # 국채 데이터만 필터링 및 정렬 (기간순)
    treasury_order = ["3M T-Bill (초단기)", "5Y Note (중기)", "10Y Note (장기)", "30Y Bond (초장기)"]
    df_curve = df_bonds[df_bonds['Type'] == "Treasury"].set_index("Name").reindex(treasury_order).reset_index()
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_curve['Name'], y=df_curve['Yield (%)'],
        mode='lines+markers+text',
        text=[f"{y:.2f}%" for y in df_curve['Yield (%)']],
        textposition="top center",
        line=dict(color='#2962FF', width=3),
        marker=dict(size=10, color='red')
    ))
    
    fig.add_hline(y=inflation_rate, line_dash="dot", annotation_text="인플레이션(CPI)", annotation_position="bottom right", line_color="orange")
    
    fig.update_layout(
        height=400,
        margin=dict(l=20, r=20, t=30, b=20),
        yaxis_title="수익률 (%)",
        xaxis_title="만기 (Maturity)"
    )
    st.plotly_chart(fig, use_container_width=True)

with c2:
    st.info("""
    **💡 버핏의 조언 해석**
    
    1. **단기채가 더 높다? (역전 현상)**
       - 그래프의 왼쪽(3M)이 오른쪽(10Y)보다 높다면, 굳이 위험하게 장기채를 살 필요가 없습니다.
       - **행동:** 단기 국채(T-Bills)를 사서 만기 보유하세요.
       
    2. **인플레 선(주황색) 아래다?**
       - 모든 금리가 주황색 점선보다 낮다면, 채권은 **'보증된 손실'** 자산입니다.
       - **행동:** 채권을 사지 말고 주식이나 현금을 보유하세요.
    """)

# -------------------------------------------------------------------
# 🧮 섹션 4: 채권 가치 계산기 (직접 입력)
# -------------------------------------------------------------------
with st.expander("🧮 내가 본 회사채 직접 테스트하기"):
    st.write("관심 있는 회사채의 정보를 입력하면 버핏 기준에 맞는지 확인해 드립니다.")
    
    col_i1, col_i2 = st.columns(2)
    with col_i1:
        input_yield = st.number_input("채권 수익률 (YTM, %)", value=5.5)
        input_years = st.number_input("남은 만기 (년)", value=3)
    with col_i2:
        input_rating = st.selectbox("신용 등급", ["AAA (최우량)", "AA", "A", "BBB (투자적격)", "BB이하 (정크)"])
    
    if st.button("분석 실행"):
        test_score = 0
        test_msg = []
        
        # 1. 수익률
        if input_yield > inflation_rate + 1.0: # 회사채는 국채보다 스프레드가 더 있어야 함
            test_score += 1
            test_msg.append("✅ 수익률 매력적 (인플레+1% 이상)")
        else:
            test_msg.append("❌ 수익률 부족 (리스크 대비 보상 낮음)")
            
        # 2. 만기
        if input_years <= 5:
            test_score += 1
            test_msg.append("✅ 만기 적절 (5년 이내)")
        elif input_years > 10:
            test_score -= 1
            test_msg.append("⚠️ 만기가 너무 김")
            
        # 3. 신용등급
        if "BB" in input_rating:
            test_score = -99 # 버핏은 정크본드 싫어함
            test_msg.append("💀 탈락: 투기 등급 (Buffett Hates Junk)")
        elif "AAA" in input_rating or "AA" in input_rating:
            test_score += 1
            test_msg.append("✅ 신용 등급 우수")
            
        # 결과 출력
        if test_score >= 3:
            st.success(f"결과: **강력 매수 후보** ({', '.join(test_msg)})")
        elif test_score >= 1:
            st.warning(f"결과: **고민 필요** ({', '.join(test_msg)})")
        else:
            st.error(f"결과: **매수 금지** ({', '.join(test_msg)})")