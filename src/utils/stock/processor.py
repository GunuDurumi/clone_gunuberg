import pandas as pd
import numpy as np
from src.database import DataRepository
from src.loaders.stock_loader import StockPriceLoader
from src.utils.gwcpi.processor import GWCPIProcessor
from src.config import TICKER_USDKRW

TICKER_DXY = "DX-Y.NYB"

class StockAnalysisProcessor:
    def __init__(self, repo: DataRepository):
        self.repo = repo
        self.stock_loader = StockPriceLoader()
        self.gwcpi_processor = GWCPIProcessor(repo)
        
    def get_analysis_data(self, ticker: str, period_years: int = 15) -> pd.DataFrame:
        # 1. 데이터 로드
        df_stock = self.repo.get_data(f"stock_{ticker}.csv", self.stock_loader, ticker=ticker, start_date="1990-01-01")
        if df_stock.empty: return pd.DataFrame()

        df_forex = self.repo.get_data("forex_usdkrw.csv", self.stock_loader, ticker=TICKER_USDKRW, start_date="1990-01-01")
        df_dxy = self.repo.get_data("forex_dxy.csv", self.stock_loader, ticker=TICKER_DXY, start_date="1990-01-01")
        df_gwcpi = self.gwcpi_processor.get_gwcpi() # 이건 '상승률(%)' 데이터임

        # --- 병합 및 전처리 ---
        df_stock['date'] = pd.to_datetime(df_stock['date'])
        df_merged = df_stock.set_index('date').sort_index()
        
        # 환율/DXY 채우기
        if not df_forex.empty:
            df_forex['date'] = pd.to_datetime(df_forex['date'])
            df_forex = df_forex.set_index('date').rename(columns={'close': 'usdkrw'})
            df_merged = df_merged.join(df_forex['usdkrw'], how='left').ffill().fillna(1200)
        else:
            df_merged['usdkrw'] = 1200

        if not df_dxy.empty:
            df_dxy['date'] = pd.to_datetime(df_dxy['date'])
            df_dxy = df_dxy.set_index('date').rename(columns={'close': 'dxy'})
            df_merged = df_merged.join(df_dxy['dxy'], how='left').ffill().fillna(100)
        else:
            df_merged['dxy'] = 100

        # -----------------------------------------------------------
        # 💸 [로직 수정] 상승률(Rate) -> 지수(Index)로 변환
        # -----------------------------------------------------------
        if not df_gwcpi.empty:
            df_gwcpi['date'] = pd.to_datetime(df_gwcpi['date'])
            df_gwcpi = df_gwcpi.set_index('date').sort_index()
            
            # 1. 주가 데이터에 병합
            df_merged = df_merged.join(df_gwcpi['gwcpi'], how='left')
            
            # 2. 물가상승률(%) 선형 보간 (부드럽게 이어주기)
            # gwcpi 컬럼은 "작년 대비 3% 올랐어" 같은 '속도'임
            df_merged['gwcpi'] = df_merged['gwcpi'].replace(0, np.nan).interpolate(method='time').ffill().bfill()
            
            # 3. [핵심] 일별 상승 계수(Factor) 만들기
            # 연율 3% -> 일율 (1.03)^(1/365)
            # 100을 나누는 이유는 %단위이기 때문 (3.0 -> 0.03)
            df_merged['daily_inflation_factor'] = (1 + df_merged['gwcpi'] / 100) ** (1/365)
            
            # 4. 누적 곱으로 '물가 지수(Index)' 생성
            # 1.0 * 1.0001 * 1.0001 ... = 1.5 (누적된 물가 높이)
            df_merged['cpi_index'] = df_merged['daily_inflation_factor'].cumprod()
            
            # 5. 실질 주가 계산 (현재 가치 기준 환산)
            # 공식: 과거주가 * (현재물가지수 / 과거물가지수)
            # 의미: 옛날 100원은 물가 2배 오른 지금의 200원과 같다.
            if not df_merged['cpi_index'].dropna().empty:
                current_index = df_merged['cpi_index'].iloc[-1]
                
                # Scaling Factor: (현재지수 / 과거지수)
                # 과거지수가 1.0이고 현재가 2.0이면 -> Factor는 2.0
                # 과거주가 100원 * 2.0 = 실질주가 200원 (맞음)
                df_merged['cpi_adjustment_factor'] = current_index / df_merged['cpi_index']
                df_merged['close_real'] = df_merged['close'] * df_merged['cpi_adjustment_factor']
            else:
                df_merged['close_real'] = df_merged['close']
        else:
            df_merged['close_real'] = df_merged['close']

        # -----------------------------------------------------------
        # 💱 환율/통화 영향 제거 (Tab 2)
        # -----------------------------------------------------------
        # -----------------------------------------------------------
        # 🧮 [최종] 절대 기준(Standard) 비교
        # 오늘 날짜에 맞추지(Scaling) 않고, '표준 상태'일 때의 가격을 산출하여
        # 현재 가격과의 'Gap'을 그대로 노출시킴.
        # -----------------------------------------------------------
        is_kr_stock = ticker.upper().endswith('.KS') or ticker.upper().endswith('.KQ') or ticker.isdigit()
        
        # 1. DXY Factor (기준: 100)
        # 100일 때가 '정상'. 높으면 달러 강세, 낮으면 달러 약세.
        dxy_factor = df_merged['dxy'] / 100
        
        if is_kr_stock:
            # [한국 주식]
            # 기준: 지난 10년 평균 환율 (Moving Average가 아니라 전체 기간 평균 상수 사용)
            # 이유: "환율이 평소(평균)대로 돌아온다면 얼마일까?"를 보기 위함.
            historical_avg_rate = df_merged['usdkrw'].mean() 
            if np.isnan(historical_avg_rate): historical_avg_rate = 1200
            
            # 1단계: 달러 환산
            price_in_usd = df_merged['close'] / df_merged['usdkrw']
            
            # 2단계: DXY 및 평균 환율 적용
            # 공식: (달러가격 * DXY) * 평균환율
            # 의미: 글로벌 가치(USD * DXY)를 한국 평균 환율로 다시 환전.
            # 이러면 "환율 거품"과 "달러 거품"이 모두 빠진 '평소 한국 돈' 기준 가격이 나옴.
            df_merged['close_currency_neutral'] = (price_in_usd * dxy_factor) * historical_avg_rate
            
            df_merged['currency_label'] = f'Fair Value (Base: {historical_avg_rate:.0f}₩, DXY 100)'
            
        else:
            # [미국 주식]
            # 기준: DXY 100
            # 공식: 주가($) * (DXY / 100)
            # 의미: "만약 달러 인덱스가 100(정상)이었다면, 이 주가는 얼마였을까?"
            # DXY가 106(강세)이라면 -> 주가는 원래 더 비싸야 함 (1.06배) -> 억눌려 있음.
            # DXY가 90(약세)이라면 -> 주가는 원래 더 싸야 함 (0.9배) -> 부풀려 있음.
            df_merged['close_currency_neutral'] = df_merged['close'] * dxy_factor
            
            df_merged['currency_label'] = 'Fair Value (Base: DXY 100)'

        return df_merged.reset_index()