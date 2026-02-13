from abc import ABC, abstractmethod
import pandas as pd

class IDataLoader(ABC):
    """
    증분 업데이트를 지원하는 데이터 로더 인터페이스
    """
    
    @abstractmethod
    def fetch_data(self, start_date: str, end_date: str = None, **kwargs) -> pd.DataFrame:
        """
        특정 기간의 데이터를 가져옴.
        :param start_date: 'YYYY-MM-DD' 형식의 시작일
        :param end_date: 'YYYY-MM-DD' 형식의 종료일 (None이면 오늘까지)
        :return: ['date', ...] 컬럼을 포함한 DataFrame
        """
        pass
