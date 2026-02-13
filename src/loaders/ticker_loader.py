import pandas as pd
import FinanceDataReader as fdr
from src.interfaces import IDataLoader

class TickerListLoader(IDataLoader):
    """
    [Ticker List Loader]
    - FinanceDataReader를 이용해 한국(KRX) 및 미국(NASDAQ, NYSE, AMEX) 전 종목 리스트를 수집합니다.
    """
    def fetch_data(self, **kwargs) -> pd.DataFrame:
        try:
            all_dfs = []
            
            # 1. 한국 시장 (KRX: KOSPI + KOSDAQ)
            # print("Loading KRX tickers...")
            df_krx = fdr.StockListing('KRX')
            df_krx = df_krx[['Code', 'Name', 'Market']]
            df_krx['Country'] = 'KR'
            all_dfs.append(df_krx)
            
            # 2. 미국 시장 (NASDAQ, NYSE, AMEX)
            # print("Loading US tickers...")
            for market in ['NASDAQ', 'NYSE', 'AMEX']:
                try:
                    df_us = fdr.StockListing(market)
                    df_us = df_us[['Symbol', 'Name']]
                    df_us.columns = ['Code', 'Name'] # 컬럼명 통일
                    df_us['Market'] = market
                    df_us['Country'] = 'US'
                    all_dfs.append(df_us)
                except Exception:
                    continue # 특정 마켓 실패해도 진행
                
            if not all_dfs:
                return pd.DataFrame()

            # 병합
            df_final = pd.concat(all_dfs, ignore_index=True)
            
            # 중복 제거 (티커 기준)
            df_final = df_final.drop_duplicates(subset=['Code'], keep='first')
            
            return df_final
            
        except ImportError:
            print("❌ finance-datareader가 설치되지 않았습니다.")
            return pd.DataFrame()
        except Exception as e:
            print(f"❌ 티커 리스트 다운로드 실패: {e}")
            return pd.DataFrame()