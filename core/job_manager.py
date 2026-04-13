# core/job_manager.py
import os
import datetime
import shutil

class JobManager:
    def __init__(self, base_temp_path: str):
        self.base_temp_path = base_temp_path
        if not os.path.exists(self.base_temp_path):
            os.makedirs(self.base_temp_path)

    def create_new_job(self) -> str:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        job_id = f"job_{timestamp}"
        job_path = os.path.join(self.base_temp_path, job_id)
        
        os.makedirs(os.path.join(job_path, "layers"), exist_ok=True)
        os.makedirs(os.path.join(job_path, "logs"), exist_ok=True)
        
        return job_path

    @staticmethod
    def get_layers_path(job_path: str) -> str:
        return os.path.join(job_path, "layers")

    @staticmethod
    def get_metadata_path(job_path: str) -> str:
        return os.path.join(job_path, "metadata.json")
