import pandas as pd
import streamlit as st
from src.database import DataRepository
from src.loaders.ticker_loader import TickerListLoader

class TickerManager:
    def __init__(self, repo: DataRepository):
        self.repo = repo
        self.loader = TickerListLoader()
        
    @st.cache_data(ttl=3600*24) # UI용 딕셔너리 생성은 메모리에 캐싱
    def get_ticker_map(_self):
        """
        DataRepository를 통해 티커 데이터를 가져와서
        UI 검색용 딕셔너리 { "이름 (코드)": "실제티커" } 로 변환합니다.
        """
        # ✅ DataRepository 사용! (파일명: all_tickers.csv)
        # check_interval_days=30: 한 달에 한 번만 갱신 (주식 종목이 매일 바뀌진 않으므로)
        df = _self.repo.get_data(
            filename="all_tickers.csv",
            loader=_self.loader,
            check_interval_days=30 
        )
        
        if df.empty:
            return {}
        
        ticker_map = {}
        try:
            # 데이터프레임 -> 딕셔너리 변환 (속도 최적화)
            # iterrows보다 zip이 훨씬 빠릅니다.
            for code, name, market, country in zip(df['Code'], df['Name'], df['Market'], df['Country']):
                
                # yfinance용 티커 변환
                full_ticker = code
                if country == 'KR':
                    if market == 'KOSDAQ':
                        full_ticker = f"{code}.KQ"
                    else: # KOSPI 등
                        full_ticker = f"{code}.KS"
                
                # 표시 이름 (Flag 추가)
                flag = "🇰🇷" if country == 'KR' else "🇺🇸"
                # 이름이 너무 길면 자르거나, 특수문자 처리 (선택)
                display_name = f"{flag} {name} ({code})"
                
                ticker_map[display_name] = full_ticker
                
        except Exception as e:
            print(f"티커 맵 변환 중 오류: {e}")
            
        return ticker_map

    def force_update(self):
        """
        강제 업데이트가 필요할 때 (버튼 클릭 시)
        DataRepository는 파일이 있으면 안 받아오므로,
        여기서 명시적으로 로더를 호출하거나 파일을 지우는 로직이 필요할 수 있으나,
        Repo 구조상 check_interval_days를 0으로 호출하거나 repo의 갱신 로직을 이용해야 함.
        """
        # 가장 깔끔한 방법: 기존 파일을 무시하고 새로 받아오라고 Repo에 요청하는 기능이 필요하지만,
        # 현재 Repo 구조에서는 파일을 삭제하는 게 가장 확실함.
        import os
        from src.config import DATA_DIR
        file_path = os.path.join(DATA_DIR, "all_tickers.csv")
        if os.path.exists(file_path):
            os.remove(file_path)
            
        # 캐시 초기화 후 다시 get_ticker_map 호출 유도
        st.cache_data.clear()