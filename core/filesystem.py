import os
import shutil
import json

class BridgeFileSystem:
    def __init__(self, root_path):
        self.root = root_path
        self.temp_dir = os.path.join(self.root, "temp_bridge")
        self.metadata_path = os.path.join(self.temp_dir, "metadata.json")
        
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)

    def clear_temp(self):
        """임시 폴더의 모든 파일을 삭제하여 깨끗한 상태로 만듭니다."""
        for filename in os.listdir(self.temp_dir):
            file_path = os.path.join(self.temp_dir, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f'Failed to delete {file_path}. Reason: {e}')

    def get_temp_path(self):
        return self.temp_dir

    def read_metadata(self):
        if os.path.exists(self.metadata_path):
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
