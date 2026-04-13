# main.py (UX Monitor Mode)
import os
import time
import json
import logging
import shutil
from core.clipboard import BridgeClipboard

# 로깅 설정 (콘솔 출력 대신 파일에 기록)
base_dir = r"C:\Users\SOUTHPAW GAMES\Desktop\AI TS"
log_dir = os.path.join(base_dir, "logs")
if not os.path.exists(log_dir): os.makedirs(log_dir)

log_file = os.path.join(log_dir, "bridge_daemon.log")
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 콘솔에도 심플하게 출력
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger("").addHandler(console)

def cleanup_old_jobs(temp_dir, max_jobs=5, max_age_hours=1):
    """
    하드디스크 용량 확보를 위해 오래된 임시 Job 폴더를 삭제합니다.
    1. 생성된 지 max_age_hours가 지난 폴더 삭제
    2. 총 개수가 max_jobs를 초과하면 오래된 순으로 삭제 (단, 가장 최근 1개는 무조건 보존)
    """
    try:
        if not os.path.exists(temp_dir): return
        
        job_folders = []
        for name in os.listdir(temp_dir):
            path = os.path.join(temp_dir, name)
            if os.path.isdir(path) and name.startswith("bridge_job_") or name.startswith("job_"):
                # 수정 시간(mtime) 기준으로 정렬하기 위해 튜플 저장
                job_folders.append((path, os.path.getmtime(path)))
        
        if not job_folders: return
        
        # 오래된 순으로 정렬 (오름차순: 옛날 -> 최근)
        job_folders.sort(key=lambda x: x[1])
        
        current_time = time.time()
        
        # 가장 최근(마지막) 1개는 무조건 보존하기 위해 목록에서 분리
        jobs_to_check = job_folders[:-1]
        
        for path, mtime in jobs_to_check:
            age_hours = (current_time - mtime) / 3600.0
            
            # 조건 1: 시간 초과 (1시간) 또는 조건 2: 개수 초과
            if age_hours > max_age_hours or len(job_folders) > max_jobs:
                try:
                    shutil.rmtree(path)
                    logging.info(f"Cleanup: 오래된 임시 폴더 자동 삭제 ({os.path.basename(path)})")
                    job_folders = [j for j in job_folders if j[0] != path] # 갱신
                except Exception as e:
                    logging.warning(f"Cleanup 실패 ({os.path.basename(path)}): {e}")
    except Exception as e:
        logging.error(f"Cleanup 시스템 에러: {e}")

def main():
    temp_dir = os.path.join(base_dir, "temp")
    if not os.path.exists(temp_dir): os.makedirs(temp_dir)

    logging.info("=== Ase-PS Bridge Daemon Started ===")
    
    processed_jobs = set()
    cleanup_timer = time.time()

    while True:
        try:
            for job_id in os.listdir(temp_dir):
                if job_id in processed_jobs:
                    continue
                
                job_path = os.path.join(temp_dir, job_id)
                if not os.path.isdir(job_path):
                    continue
                    
                trigger_path = os.path.join(job_path, "trigger_copy.json")
                
                if os.path.exists(trigger_path):
                    # 파일이 방금 생성되어 아직 내용이 덜 쓰였을 수 있으므로 약간 대기
                    time.sleep(0.2)
                    with open(trigger_path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                    
                    # 클립보드에 페이로드 쓰기
                    if BridgeClipboard.set_payload(payload):
                        layer_count = payload.get("summary", {}).get("layer_count", "?")
                        logging.info(f"클립보드 동기화 완료: {job_id} ({layer_count}개 레이어)")
                        processed_jobs.add(job_id)
                    else:
                        logging.error(f"클립보드 쓰기 실패: {job_id}")
            
            # 1분(60초)마다 한 번씩 Cleanup 로직 실행
            if time.time() - cleanup_timer > 60:
                cleanup_old_jobs(temp_dir, max_jobs=5, max_age_hours=1)
                cleanup_timer = time.time()
                
        except Exception as e:
            logging.error(f"에러 발생: {e}")
        
        time.sleep(1)

if __name__ == "__main__":
    main()