# core/validators.py
import os
import json
from .bridge_schema import BRIDGE_VERSION

class BridgeValidator:
    @staticmethod
    def validate_job_folder(job_path: str):
        metadata_path = os.path.join(job_path, "metadata.json")
        if not os.path.exists(metadata_path):
            raise FileNotFoundError(f"metadata.json missing at {metadata_path}")

        with open(metadata_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if data.get("version") != BRIDGE_VERSION:
            raise ValueError(f"Version mismatch: Expected {BRIDGE_VERSION}, got {data.get('version')}")

        layers = data.get("layers", [])
        for layer in layers:
            img_path = os.path.join(job_path, layer["file"])
            if not os.path.exists(img_path):
                raise FileNotFoundError(f"Missing image: {layer['name']} ({img_path})")

        return data
