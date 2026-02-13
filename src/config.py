import streamlit as st
import os
from pathlib import Path

# [Path Settings]
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = Path(os.path.join(BASE_DIR, "data"))

# 데이터 폴더 생성
DATA_DIR.mkdir(parents=True, exist_ok=True)

# [File Names]
FILE_KRX_TICKERS = "krx_tickers.csv"

# [Secret Management]
# Hugging Face Secrets(환경변수)와 Streamlit 로컬 Secrets를 모두 지원하는 함수
def get_secret(key, default=""):
    # 1. Hugging Face Spaces (환경 변수 우선 확인)
    # os.environ에서 값을 찾습니다. HF Secrets에 넣은 값은 여기로 들어옵니다.
    env_val = os.getenv(key)
    if env_val is not None:
        return env_val
    
    # 2. Local Streamlit (.streamlit/secrets.toml 확인)
    # 로컬 개발 환경에서는 이 파일을 참조합니다.
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    
    return default

# [API Keys]
# 이제 os.getenv를 통해 Hugging Face에 설정한 값을 가져옵니다.
FRED_API_KEY = get_secret("FRED_API_KEY")
HF_TOKEN = get_secret("HF_TOKEN")
HF_DATASET_ID = get_secret("HF_DATASET_ID")

# [Forex & Indices Tickers]
TICKER_DXY = "DX-Y.NYB"
TICKER_USDKRW = "KRW=X"

# [GWCPI 국가별 설정]
OECD_CORE_SERIES = {
    "USA": { "country_code": "USA", "weight": 0.5008, "fred_id": "CPIAUCSL" },
    "CNY": { "country_code": "CHN", "weight": 0.1796, "fred_id": "CHNCPIALLMINMEI" },
    "DEU": { "country_code": "DEU", "weight": 0.0661, "fred_id": "DEUCPIALLMINMEI" },
    "GBP": { "country_code": "GBR", "weight": 0.0604, "fred_id": "GBRCPIALLMINMEI" },
    "JPY": { "country_code": "JPN", "weight": 0.0578, "fred_id": "JPNCPIALLMINMEI" },
    "FRA": { "country_code": "FRA", "weight": 0.0445, "fred_id": "FRACPIALLMINMEI" },
    "ITA": { "country_code": "ITA", "weight": 0.0375, "fred_id": "ITACPIALLMINMEI" },
    "CAN": { "country_code": "CAN", "weight": 0.0314, "fred_id": "CANCPIALLMINMEI" },
    "KOR": { "country_code": "KOR", "weight": 0.0220, "fred_id": "KORCPIALLMINMEI" }
}
