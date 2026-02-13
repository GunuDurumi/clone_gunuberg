import pandas as pd
import yfinance as yf
from src.interfaces import IDataLoader

class StockPriceLoader(IDataLoader):
    def fetch_data(self, start_date: str, end_date: str = None, **kwargs) -> pd.DataFrame:
        ticker = kwargs.get('ticker')
        if not ticker: return pd.DataFrame()

        print(f"🌍 Fetching {ticker}: {start_date} ~ {end_date}")
        
        try:
            # yfinance download는 start는 포함, end는 제외함 (주의)
            # 따라서 end_date가 있으면 하루 더해서 요청하거나 그대로 사용
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            
            if df.empty: return pd.DataFrame()

            df = df.reset_index()
            
            # 멀티 인덱스 처리
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)

            # 컬럼명 통일 (소문자 date 필수)
            df = df.rename(columns={'Date': 'date', 'Close': 'close', 'Volume': 'volume'})
            
            # 날짜 포맷 통일 (문자열)
            df['date'] = df['date'].dt.strftime('%Y-%m-%d')
            
            return df[['date', 'close', 'volume']]

        except Exception as e:
            print(f"❌ Error fetching {ticker}: {e}")
            return pd.DataFrame()
