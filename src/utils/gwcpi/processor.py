import pandas as pd
from functools import reduce
from src.database import DataRepository
from src.loaders.macro_loader import OECD_CSV_Loader
from src.config import OECD_CORE_SERIES

class GWCPIProcessor:
    def __init__(self, repo: DataRepository):
        self.repo = repo
        self.loader = OECD_CSV_Loader()

    def get_gwcpi(self) -> pd.DataFrame:
        # 매크로 데이터는 자주 변하지 않으므로 7일 쿨타임 설정
        # Database 모듈은 이제 파일명을 몰라도 됩니다.
        df_all = self.repo.get_data(
            filename="macro_combined_v2.csv",
            loader=self.loader,
            required_years=20,
            check_interval_days=7  # 👈 여기서 정책 결정!
        )
        
        if df_all is None or df_all.empty:
            return pd.DataFrame()

        df_all = df_all.set_index('date').sort_index()
        df_all = df_all.fillna(method='ffill')

        df_all['gwcpi'] = 0.0
        total_weight = 0.0
        
        for currency, info in OECD_CORE_SERIES.items():
            if currency in df_all.columns:
                weight = info['weight']
                df_all['gwcpi'] += (df_all[currency] * weight)
                total_weight += weight
        
        if total_weight == 0:
            return pd.DataFrame()

        df_all['gwcpi'] = df_all['gwcpi'] / total_weight

        return df_all[['gwcpi']].reset_index()