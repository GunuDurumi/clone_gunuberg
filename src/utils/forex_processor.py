import pandas as pd
from src.database import DataRepository
from src.loaders.stock_loader import StockPriceLoader
from src.config import TICKER_DXY, TICKER_USDKRW

class ForexProcessor:
    def __init__(self, repo: DataRepository):
        self.repo = repo
        # 야후 파이낸스용 로더 사용
        self.loader = StockPriceLoader() 

    def get_real_krw_value(self) -> pd.DataFrame:
        """
        원화 실질 가치 지수 산출 (1990년부터 데이터 확보)
        Formula: DXY (달러인덱스) / USD_KRW (환율)
        """
        
        # ✅ [수정 1] 1990년부터 가져오라고 'start_date' 명시
        # 이렇게 해야 로더가 30년치 데이터를 긁어옵니다.
        target_start_date = "1990-01-01"

        df_dxy = self.repo.get_data(
            filename="index_dxy.csv",
            loader=self.loader,
            ticker=TICKER_DXY,
            start_date=target_start_date  # 기간 명시 필수
        )
        
        df_krw = self.repo.get_data(
            filename="forex_usdkrw.csv",
            loader=self.loader,
            ticker=TICKER_USDKRW,
            start_date=target_start_date  # 기간 명시 필수
        )

        if df_dxy.empty or df_krw.empty:
            print("❌ 환율 또는 DXY 데이터를 가져오지 못했습니다.")
            return pd.DataFrame()

        # 데이터 컬럼 통일 (close -> price)
        df_dxy = df_dxy[['date', 'close']].rename(columns={'close': 'dxy'})
        df_krw = df_krw[['date', 'close']].rename(columns={'close': 'krw'})

        # ✅ [수정 2] Outer Join + Forward Fill
        # 휴장일이 달라도 데이터가 유실되지 않도록 outer join 후 직전 값으로 채움
        merged = pd.merge(df_dxy, df_krw, on='date', how='outer')
        merged = merged.sort_values('date')
        merged = merged.fillna(method='ffill').dropna() # 앞의 값으로 채우고, 그래도 없으면 삭제

        # 3. 계산 (DXY / KRW)
        # 값이 너무 작으므로 1000을 곱해서 보기 편하게 만듦 (선택사항)
        merged['real_krw_score'] = (merged['dxy'] / merged['krw']) * 1000

        # 컬럼 정리
        merged = merged.rename(columns={'dxy': 'close_dxy', 'krw': 'close_krw'})
        
        return merged[['date', 'real_krw_score', 'close_dxy', 'close_krw']]
