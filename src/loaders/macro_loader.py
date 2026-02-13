import pandas as pd
import requests
from bs4 import BeautifulSoup
from io import BytesIO
import re
import streamlit as st
import time
from fredapi import Fred
from src.interfaces import IDataLoader
from src.config import OECD_CORE_SERIES, FRED_API_KEY

class OECD_CSV_Loader(IDataLoader):
    """
    [Hybrid Macro Loader: FRED + e-Stat]
    - UI 위젯(checkbox) 제거 버전 (캐싱 오류 해결)
    """

    def __init__(self):
        # ❌ 삭제: 캐싱 함수 내부에서 위젯 호출 금지
        # self.debug_mode = st.sidebar.checkbox(...) 
        
        # ✅ 변경: 디버그 모드는 기본적으로 끄거나, 필요하면 print로 대체
        self.debug_mode = False 
        
        try:
            self.fred = Fred(api_key=FRED_API_KEY)
        except Exception as e:
            print(f"❌ FRED API 초기화 실패: {e}") # st.error 대신 print 사용
            self.fred = None

    def fetch_data(self, start_date: str, end_date: str = None, **kwargs) -> pd.DataFrame:
        if not start_date: start_date = "2010-01-01"
        if not end_date: end_date = pd.Timestamp.now().strftime('%Y-%m-%d')

        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        
        split_date = pd.Timestamp("2021-01-01")

        df_fred = pd.DataFrame()
        df_estat = pd.DataFrame()

        # 1. FRED (~ 2020.12.31)
        if start_dt < split_date:
            fred_end = min(end_dt, pd.Timestamp("2020-12-31"))
            if start_dt <= fred_end:
                df_fred = self._fetch_from_fred(
                    start_dt.strftime('%Y-%m-%d'), 
                    fred_end.strftime('%Y-%m-%d')
                )
        
        # 2. e-Stat (2021.01.01 ~)
        if end_dt >= split_date:
            estat_start = max(start_dt, split_date)
            if estat_start <= end_dt:
                df_estat = self._fetch_from_estat(
                    estat_start.strftime('%Y-%m-%d'), 
                    end_dt.strftime('%Y-%m-%d')
                )

        # 3. 병합
        if not df_fred.empty and not df_estat.empty:
            df_final = pd.concat([df_fred, df_estat], axis=0)
        elif not df_fred.empty:
            df_final = df_fred
        elif not df_estat.empty:
            df_final = df_estat
        else:
            return pd.DataFrame()

        df_final = df_final.drop_duplicates(subset=['date'], keep='last').sort_values('date')
        mask = (df_final['date'] >= start_date) & (df_final['date'] <= end_date)
        return df_final.loc[mask]

    def _fetch_from_fred(self, start_date, end_date) -> pd.DataFrame:
        if not self.fred: return pd.DataFrame()
        all_series = {}
        
        for currency, info in OECD_CORE_SERIES.items():
            fred_id = info.get('fred_id')
            if not fred_id: continue
            try:
                calc_start = (pd.to_datetime(start_date) - pd.DateOffset(years=1)).strftime('%Y-%m-%d')
                if pd.to_datetime(calc_start) > pd.to_datetime(end_date): continue
                
                series = self.fred.get_series(fred_id, observation_start=calc_start, observation_end=end_date)
                series_yoy = series.pct_change(periods=12) * 100
                series_yoy.name = currency
                all_series[currency] = series_yoy
            except: pass

        if not all_series: return pd.DataFrame()
        df = pd.DataFrame(all_series).reset_index().rename(columns={'index':'date'})
        return df[df['date'] >= start_date]

    def _fetch_from_estat(self, start_date, end_date) -> pd.DataFrame:
        all_dfs = []
        base_url = "https://www.e-stat.go.jp/stat-search/files"
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        start_year = pd.to_datetime(start_date).year
        end_year = pd.to_datetime(end_date).year
        target_years = range(start_year, end_year + 1)

        for year in target_years:
            target_link = None
            try:
                # 정밀 검색
                params = {
                    'page': '1', 'query': '主要国の消費者物価指数変化率', 'layout': 'dataset',
                    'toukei': '00200573', 'tstat': '000001150147', 'cycle': '1',
                    'year': f"{year}0", 'tclass1': '000001150149', 'cycle_facet': 'tclass1',
                    'tclass2val': '0', 'metadata': '1', 'data': '0'
                }
                res = requests.get(base_url, params=params, headers=headers, timeout=10)
                target_link = self._extract_excel_link(res.text)
                
                if not target_link:
                    fallback_params = {
                        'page': '1', 'query': f"主要国の消費者物価指数変化率 {year}年",
                        'layout': 'dataset', 'metadata': '1', 'data': '0'
                    }
                    res = requests.get(base_url, params=fallback_params, headers=headers, timeout=10)
                    target_link = self._extract_excel_link(res.text)

                if target_link:
                    r = requests.get(target_link, headers=headers, timeout=15)
                    if r.status_code == 200:
                        df_year = self.parse_year_specific(BytesIO(r.content), year)
                        if not df_year.empty:
                            all_dfs.append(df_year)
            except: pass
            
        if not all_dfs: return pd.DataFrame()
        merged = pd.concat(all_dfs).drop_duplicates(subset=['date'], keep='last').sort_values('date')
        mask = (merged['date'] >= start_date) & (merged['date'] <= end_date)
        return merged.loc[mask]

    def _extract_excel_link(self, html_text):
        soup = BeautifulSoup(html_text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'file-download' in href:
                full = "https://www.e-stat.go.jp" + href.split('?')[0] + '?' + href.split('?')[1] if href.startswith('/') else href
                if 'fileKind=4' in href: return full
                return full
        return None

    def parse_year_specific(self, f, target_year: int) -> pd.DataFrame:
        try:
            df = pd.read_excel(f, header=None, engine='openpyxl')
            best_header_row = -1
            best_map = {}
            max_matches = 0
            
            for r in range(5, 25): 
                if r >= len(df): break
                row_vals = [str(v).replace(' ', '').replace('\u3000', '').replace('\n', '').replace('\xa0', '') for v in df.iloc[r].values]
                temp_map = {}
                matches_count = 0
                for currency, info in OECD_CORE_SERIES.items():
                    code = info['country_code']
                    keywords = self.get_country_keywords(code)
                    for c, val_clean in enumerate(row_vals):
                        for k in keywords:
                            if k in val_clean:
                                temp_map[currency] = c
                                matches_count += 1
                                break
                        if currency in temp_map: break
                if matches_count > max_matches:
                    max_matches = matches_count
                    best_header_row = r
                    best_map = temp_map
            
            if best_header_row == -1: return pd.DataFrame()

            data = []
            for i in range(best_header_row + 1, len(df)):
                row = df.iloc[i]
                dt = self.parse_date(str(row[0]).strip(), target_year)
                
                if dt and dt.year == target_year:
                    row_data = {'date': dt}
                    has_val = False
                    for currency, col_idx in best_map.items():
                        try:
                            raw_val = str(row[col_idx]).strip()
                            raw_val = raw_val.replace('▲', '-').replace('－', '-').replace('−', '-')
                            raw_val = raw_val.replace('*', '').replace(' ', '')
                            
                            if raw_val == '-' or raw_val == '':
                                continue

                            val = float(raw_val)
                            row_data[currency] = val
                            has_val = True
                        except: pass
                    if has_val: data.append(row_data)
            return pd.DataFrame(data)
        except: return pd.DataFrame()

    def parse_date(self, text, target_year_context):
        text = str(text).strip()
        try:
            if '平均' in text or 'Average' in text: return None
            y_match = re.search(r'(\d{4})', text)
            m_match = re.search(r'(\d{1,2})', text.split('年')[-1]) if '年' in text else None
            
            if y_match and '月' in text and m_match:
                y = int(y_match.group(1))
                m = int(m_match.group(1))
                return pd.Timestamp(year=y, month=m, day=1)
            
            if y_match and not '月' in text and len(text) == 4:
                return None 

            if text.isdigit():
                val = int(text)
                if 1 <= val <= 12:
                    return pd.Timestamp(year=target_year_context, month=val, day=1)
        except: pass
        return None

    def get_country_keywords(self, code):
        keywords = {
            'USA': ['UnitedStates', 'アメリカ'],
            'JPN': ['Japan', '日本'],
            'KOR': ['Korea', '韓国'], 
            'GBP': ['UnitedKingdom', 'イギリス'],
            'CAN': ['Canada', 'カナダ'],
            'CHN': ['China', '中国'],
            'DEU': ['Germany', 'ドイツ'],
            'FRA': ['France', 'フランス'],
            'ITA': ['Italy', 'イタリア'],
        }
        return keywords.get(code, [])