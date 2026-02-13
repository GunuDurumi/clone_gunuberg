FROM python:3.13.5-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# 1. 의존성 설치 (캐시 활용을 위해 먼저 복사)
COPY requirements.txt ./
RUN pip3 install -r requirements.txt

# 2. 모든 소스 코드 복사 (Home.py 포함)
# 기존에는 COPY src/ ./src/ 만 해서 루트에 있는 Home.py가 누락됐을 수 있음
COPY . .

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# 3. 실행 명령어 변경: src/streamlit_app.py -> Home.py
ENTRYPOINT ["streamlit", "run", "Home.py", "--server.port=8501", "--server.address=0.0.0.0"]
