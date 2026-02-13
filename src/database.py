import pandas as pd
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
import streamlit as st
from huggingface_hub import HfApi
from src.config import DATA_DIR, HF_TOKEN, HF_DATASET_ID

class DataRepository:
    """
    [Metadata-Driven Data Repository]
    - 파일 수정 시간(OS Time) 대신, 별도의 메타데이터(Last Checked)로 갱신 주기를 관리합니다.
    - 발표 주기가 긴 데이터(월간/분기)의 불필요한 API 호출을 원천 차단합니다.
    """
    def __init__(self):
        self.data_dir = Path(DATA_DIR)
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
            
        self.api = HfApi(token=HF_TOKEN)
        self.repo_id = HF_DATASET_ID

    def get_data(self, filename: str, loader, check_interval_days: int = 0.00035, start_date=None, **kwargs) -> pd.DataFrame:
        """
        :param check_interval_days: 이 기간 내에는 재조회를 시도하지 않음 (발표 주기 고려)
        """
        file_path = self.data_dir / filename
        meta_path = self.data_dir / f"{filename}.meta.json"
        
        # 1. 파일이 없으면 -> 무조건 신규 생성 (HF 복구 시도 포함)
        if not file_path.exists():
            if self._pull_from_hub(filename): # 데이터 복구
                self._pull_from_hub(f"{filename}.meta.json") # 메타데이터도 같이 복구
            else:
                return self._fetch_and_save(filename, loader, meta_path, start_date=start_date, **kwargs)

        # 2. 파일 로드
        df_existing = self._load_csv(file_path)
        if df_existing.empty:
             # 빈 껍데기만 있으면 다시 받음
             return self._fetch_and_save(filename, loader, meta_path, start_date=start_date, **kwargs)

        # 3. [핵심] 쿨타임(Last Checked) 확인
        last_checked = self._get_last_checked(meta_path)
        
        # 아직 쿨타임 안 지났으면 -> 기존 데이터 리턴 (결측치가 있든 말든 신경 끄고 리턴)
        if datetime.now() - last_checked < timedelta(days=check_interval_days):
            # print(f"zzz [Repo] 쿨타임 중: {filename} (남은 시간: {timedelta(days=check_interval_days) - (datetime.now() - last_checked)})")
            return df_existing

        # -----------------------------------------------------------
        # 여기 내려왔다는 건 쿨타임이 끝났다는 뜻 -> 이제야 API 호출 시도
        # -----------------------------------------------------------
        
        try:
            current_max_date = df_existing['date'].max() if 'date' in df_existing.columns else None
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

            # A. 과거 데이터 구멍 메우기 (이건 쿨타임 지났으니 한번 체크)
            if start_date:
                current_min_date = df_existing['date'].min() if 'date' in df_existing.columns else None
                req_start = pd.to_datetime(start_date).replace(tzinfo=None)
                if current_min_date and current_min_date > req_start + timedelta(days=5):
                    print(f"🔄 [Repo] 과거 데이터 부족 발견 -> 전체 재수집")
                    return self._fetch_and_save(filename, loader, meta_path, start_date=start_date, **kwargs)

            # B. 최신 데이터 이어붙이기
            # (데이터가 오늘보다 옛날 것임 -> 새 데이터가 나왔나 확인해볼 시간임)
            if current_max_date and current_max_date < today - timedelta(days=1):
                next_day = current_max_date + timedelta(days=1)
                
                # 아직 미래 날짜면 패스 (이럴 일은 거의 없지만)
                if next_day > datetime.now():
                    self._update_meta(meta_path) # 확인했음을 기록
                    return df_existing

                print(f"🔎 [Repo] 갱신 주기 도래 ({check_interval_days}일 경과) -> API 조회: {filename}")
                
                kwargs_copy = kwargs.copy()
                kwargs_copy.pop('start_date', None)
                
                df_new = loader.fetch_data(start_date=next_day.strftime('%Y-%m-%d'), **kwargs_copy)
                
                if not df_new.empty:
                    df_new = self._ensure_date_format(df_new)
                    
                    df_combined = pd.concat([df_existing, df_new])
                    df_combined = df_combined.drop_duplicates(subset=['date'], keep='last').sort_values('date')
                    
                    self._save_and_push(file_path, df_combined, filename, meta_path)
                    return df_combined
                else:
                    # **중요**: 데이터가 없어도(발표 안 됨/휴장) "확인했음"을 기록해야 함!
                    # 그래야 내일 또 헛되이 조회하지 않고 쿨타임을 가짐.
                    print(f"💤 [Repo] 신규 데이터 없음 (다음 주기까지 대기)")
                    self._update_meta(meta_path) # Last Checked 갱신
                    self._push_meta_only(filename, meta_path) # 메타파일만 업로드
                    return df_existing
            
            # C. 데이터가 이미 최신임 (오늘자 데이터까지 있음)
            else:
                self._update_meta(meta_path) # 확인했음 기록
                return df_existing

        except Exception as e:
            print(f"❌ [Repo] 자동 갱신 중 오류 ({filename}): {e}")
            return df_existing

    # --- 내부 메서드 ---

    def _fetch_and_save(self, filename, loader, meta_path, **kwargs) -> pd.DataFrame:
        try:
            df = loader.fetch_data(**kwargs)
            if df is not None and not df.empty:
                df = self._ensure_date_format(df)
                file_path = self.data_dir / filename
                self._save_and_push(file_path, df, filename, meta_path)
            return df
        except Exception:
            return pd.DataFrame()

    def _save_and_push(self, file_path, df, filename, meta_path):
        """데이터 저장 + 메타데이터 갱신 + 둘 다 업로드"""
        try:
            # 1. 데이터 저장
            df.to_csv(file_path, index=False)
            
            # 2. 메타데이터(조회 시각) 갱신 및 저장
            self._update_meta(meta_path)
            
            # 3. HF 업로드 (데이터 + 메타)
            try:
                self.api.upload_file(
                    path_or_fileobj=file_path, path_in_repo=f"data/{filename}",
                    repo_id=self.repo_id, repo_type="dataset"
                )
                self.api.upload_file(
                    path_or_fileobj=meta_path, path_in_repo=f"data/{filename}.meta.json",
                    repo_id=self.repo_id, repo_type="dataset"
                )
                # print(f"☁️ [Repo] 동기화 완료: {filename}")
            except Exception: pass
        except Exception: pass

    def _push_meta_only(self, filename, meta_path):
        """데이터는 그대로두고 메타데이터만 업로드 (조회 기록 갱신용)"""
        try:
            self.api.upload_file(
                path_or_fileobj=meta_path, path_in_repo=f"data/{filename}.meta.json",
                repo_id=self.repo_id, repo_type="dataset"
            )
        except Exception: pass

    def _update_meta(self, meta_path):
        """현재 시각을 Last Checked로 기록"""
        meta = {"last_checked": datetime.now().isoformat()}
        with open(meta_path, 'w') as f:
            json.dump(meta, f)

    def _get_last_checked(self, meta_path):
        """마지막 조회 시각 반환 (없으면 아주 옛날)"""
        if not meta_path.exists():
             return datetime.min
        try:
            with open(meta_path, 'r') as f:
                data = json.load(f)
                return datetime.fromisoformat(data['last_checked'])
        except:
            return datetime.min

    def _pull_from_hub(self, filename):
        try:
            self.api.hf_hub_download(repo_id=self.repo_id, filename=f"data/{filename}", repo_type="dataset", local_dir=DATA_DIR.parent)
            return True
        except: return False

    def _load_csv(self, file_path) -> pd.DataFrame:
        try:
            df = pd.read_csv(file_path)
            return self._ensure_date_format(df)
        except: return pd.DataFrame()

    def _ensure_date_format(self, df) -> pd.DataFrame:
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            if df['date'].dt.tz is not None:
                df['date'] = df['date'].dt.tz_localize(None)
        return df