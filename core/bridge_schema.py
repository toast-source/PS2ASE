# core/bridge_schema.py
from typing import List, TypedDict

BRIDGE_VERSION = "1.0.0"

class DocumentInfo(TypedDict):
    name: str
    width: int
    height: int
    ppi: int

class LayerMetadata(TypedDict):
    id: str
    name: str
    type: str  # "raster"
    visible: bool
    opacity: int  # 0-255
    blend_mode: str
    x: int
    y: int
    width: int
    height: int
    file: str

class BridgeMetadata(TypedDict):
    version: str
    job_id: str
    document: DocumentInfo
    layers: List[LayerMetadata]
