import sys
import os
import json
import subprocess
import time
import shutil
import winreg
import xml.etree.ElementTree as ET
import io
from PIL import Image
from PySide6.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, 
                               QWidget, QTextEdit, QLabel, QRadioButton, QButtonGroup, 
                               QHBoxLayout, QMessageBox, QFileDialog, QDialog, QLineEdit, QFormLayout, QDialogButtonBox)
from PySide6.QtCore import QTimer, QThread, Signal, Qt
from PySide6.QtGui import QFont, QColor, QPixmap
import win32com.client
import pythoncom

# ==========================================
# Job Transform Worker (비파괴 변환: Flip/Rotate 비동기 처리)
# ==========================================
class JobTransformWorker(QThread):
    transform_done = Signal()
    error = Signal(str)
    log = Signal(str)

    def __init__(self, job_path, flip_h, flip_v, angle):
        super().__init__()
        self.job_path = job_path
        self.flip_h = flip_h
        self.flip_v = flip_v
        self.angle = angle # 0, 90, 180, 270 (Clockwise)

    def run(self):
        try:
            self.log.emit(f"Applying transformation (Angle:{self.angle}, H:{self.flip_h}, V:{self.flip_v})...")
            backup_path = os.path.join(self.job_path, "_backup")
            meta_path = os.path.join(self.job_path, "metadata.json")
            layers_path = os.path.join(self.job_path, "layers")
            
            backup_meta = os.path.join(backup_path, "metadata.json")
            backup_layers = os.path.join(backup_path, "layers")

            # 1. 최초 1회 원본 백업 생성 (비파괴 유지)
            if not os.path.exists(backup_path):
                os.makedirs(backup_path)
                if os.path.exists(meta_path):
                    shutil.copy2(meta_path, backup_meta)
                if os.path.exists(layers_path):
                    shutil.copytree(layers_path, backup_layers)
                self.log.emit("✅ 원본 데이터를 안전하게 백업했습니다.")

            # 2. 항상 원본(Backup)에서 시작 (누적 오차 방지)
            if os.path.exists(backup_meta):
                shutil.copy2(backup_meta, meta_path)
            if os.path.exists(backup_layers):
                if os.path.exists(layers_path):
                    shutil.rmtree(layers_path)
                shutil.copytree(backup_layers, layers_path)

            if not self.flip_h and not self.flip_v and self.angle == 0:
                self.transform_done.emit()
                return

            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            elements = metadata.get("elements") or metadata.get("layers", [])
            pixel_layers = [el for el in elements if el.get("type", "layer") == "layer"]
            
            if not pixel_layers:
                self.transform_done.emit()
                return

            # 원본 기준 바운딩 박스 계산
            min_x = min((l.get("x", 0) for l in pixel_layers))
            min_y = min((l.get("y", 0) for l in pixel_layers))
            max_x = max((l.get("x", 0) + l.get("width", 0) for l in pixel_layers))
            max_y = max((l.get("y", 0) + l.get("height", 0) for l in pixel_layers))
            bbox_w, bbox_h = max_x - min_x, max_y - min_y

            # 회전 후 가상의 바운딩 박스 크기
            new_bbox_w = bbox_h if self.angle in [90, 270] else bbox_w
            new_bbox_h = bbox_w if self.angle in [90, 270] else bbox_h

            from PIL import Image

            # 3. 레이어별 좌표 및 이미지 변환
            for el in elements:
                if el.get("type", "layer") == "layer":
                    orig_x, orig_y = el.get("x", 0), el.get("y", 0)
                    orig_w, orig_h = el.get("width", 0), el.get("height", 0)

                    # [3-1] 좌표 회전 (90도 단위 시계방향)
                    if self.angle == 90:
                        el["x"] = min_x + (bbox_h - (orig_y - min_y + orig_h))
                        el["y"] = min_y + (orig_x - min_x)
                        el["width"], el["height"] = orig_h, orig_w
                    elif self.angle == 180:
                        el["x"] = min_x + (bbox_w - (orig_x - min_x + orig_w))
                        el["y"] = min_y + (bbox_h - (orig_y - min_y + orig_h))
                    elif self.angle == 270:
                        el["x"] = min_x + (orig_y - min_y)
                        el["y"] = min_y + (bbox_w - (orig_x - min_x + orig_w))
                        el["width"], el["height"] = orig_h, orig_w

                    # [3-2] 좌표 반전 (회전된 좌표 기준)
                    if self.flip_h:
                        el["x"] = min_x + (new_bbox_w - (el["x"] - min_x + el["width"]))
                    if self.flip_v:
                        el["y"] = min_y + (new_bbox_h - (el["y"] - min_y + el["height"]))

                    # [3-3] 실제 이미지 변환
                    png_path = os.path.join(self.job_path, el.get("file", ""))
                    if os.path.exists(png_path):
                        with Image.open(png_path) as img:
                            # 회전
                            if self.angle == 90: img = img.transpose(Image.ROTATE_270)
                            elif self.angle == 180: img = img.transpose(Image.ROTATE_180)
                            elif self.angle == 270: img = img.transpose(Image.ROTATE_90)
                            # 반전
                            if self.flip_h: img = img.transpose(Image.FLIP_LEFT_RIGHT)
                            if self.flip_v: img = img.transpose(Image.FLIP_TOP_BOTTOM)
                            img.save(png_path)

            # 4. 수정된 메타데이터 저장
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)

            self.transform_done.emit()
        except Exception as e:
            self.error.emit(f"Transform error: {str(e)}")

# ==========================================
# Preview Generator Worker (UI 멈춤 방지용 비동기 합성기)
# ==========================================
class PreviewGeneratorWorker(QThread):
    preview_ready = Signal(bytes, str) # Added job_id for validation
    preview_failed = Signal(str)

    def __init__(self, job_path, job_id):
        super().__init__()
        self.job_path = job_path
        self.job_id = job_id

    def run(self):
        try:
            # 1. 안전 장치: 작업이 완전히 끝났는지(status_done) 다시 한번 확인
            # 클립보드 감지는 빠르지만 파일 시스템 동기화 지연(Race condition) 방지
            done_file = os.path.join(self.job_path, "status_done.json")
            retry_count = 0
            while not os.path.exists(done_file) and retry_count < 10:
                time.sleep(0.1)
                retry_count += 1
                
            if not os.path.exists(done_file):
                self.preview_failed.emit("작업 완료(status_done) 파일을 찾을 수 없습니다.")
                return

            meta_path = os.path.join(self.job_path, "metadata.json")
            if not os.path.exists(meta_path):
                self.preview_failed.emit("metadata.json not found")
                return

            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            elements = metadata.get("elements") or metadata.get("layers", [])
            if not elements:
                self.preview_failed.emit("표시할 레이어가 없습니다.")
                return

            # 2. 계층 구조 평탄화 (Tree Flattening) 및 렌더 순서(Z-order) 결정
            # 단순히 index만 보면 다른 부모를 가진 형제들끼리 순서가 꼬임.
            # 트리 순회를 통해 Bottom -> Top 렌더링 리스트를 추출해야 함.
            tree_map = {}
            for el in elements:
                p_id = el.get("parent_id") or "root"
                if p_id not in tree_map:
                    tree_map[p_id] = []
                tree_map[p_id].append(el)

            # 형제들끼리 index 오름차순(Bottom->Top) 정렬
            for p_id in tree_map:
                tree_map[p_id].sort(key=lambda x: x.get("index", 0))

            render_list = []
            
            # 깊이 우선 탐색(DFS) 방식으로 Bottom 요소부터 차례대로 평탄화 배열에 담음
            def flatten_tree(parent_id):
                children = tree_map.get(parent_id, [])
                for child in children:
                    if child.get("type") == "group":
                        flatten_tree(child.get("id")) # 폴더면 파고들어 자식들 먼저 수집
                    elif child.get("type", "layer") == "layer" and child.get("visible", True) is not False:
                        render_list.append(child) # 일반 픽셀 레이어면 렌더링 목록에 추가
                        
            flatten_tree("root")

            if not render_list:
                self.preview_failed.emit("표시할 픽셀(visible) 레이어가 없습니다.")
                return

            # 3. 전체 덩어리(Bounding Box) 계산
            min_x = min(l.get("x", 0) for l in render_list)
            min_y = min(l.get("y", 0) for l in render_list)
            max_x = max(l.get("x", 0) + l.get("width", 0) for l in render_list)
            max_y = max(l.get("y", 0) + l.get("height", 0) for l in render_list)

            canvas_w = max_x - min_x
            canvas_h = max_y - min_y

            if canvas_w <= 0 or canvas_h <= 0:
                self.preview_failed.emit("유효하지 않은 캔버스 크기입니다.")
                return

            # 4. 투명 캔버스 생성
            base_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

            # 5. 각 레이어를 캔버스에 얹기 (Alpha Composite)
            for l in render_list:
                png_path = os.path.join(self.job_path, l.get("file", ""))
                if not os.path.exists(png_path):
                    continue

                try:
                    with Image.open(png_path) as layer_img:
                        layer_img = layer_img.convert("RGBA")
                        
                        opacity_pct = l.get("opacity", 100)
                        if opacity_pct < 100:
                            alpha = layer_img.split()[3]
                            alpha = alpha.point(lambda p: int(p * (opacity_pct / 100.0)))
                            layer_img.putalpha(alpha)
                        
                        target_x = l.get("x", 0) - min_x
                        target_y = l.get("y", 0) - min_y
                        
                        base_canvas.alpha_composite(layer_img, dest=(target_x, target_y))
                except Exception:
                    pass

            # 6. 썸네일 축소 (픽셀아트 특성 고려)
            # 원본 이미지가 160x160 보다 작으면 픽셀이 뭉개지지 않도록 NEAREST(Nearest Neighbor)를 사용하여 그대로 키움.
            # 원본이 너무 크면 LANCZOS로 부드럽게 축소.
            target_size = (160, 160)
            if canvas_w < 160 and canvas_h < 160:
                # 작은 도트 이미지는 선명하게 확대 (Aspect Ratio 유지)
                ratio = min(160 / canvas_w, 160 / canvas_h)
                new_w, new_h = int(canvas_w * ratio), int(canvas_h * ratio)
                base_canvas = base_canvas.resize((new_w, new_h), Image.Resampling.NEAREST)
            else:
                # 큰 이미지는 부드럽게 축소
                base_canvas.thumbnail(target_size, Image.Resampling.LANCZOS)

            # 7. 메모리 바이너리로 변환하여 Signal 쏘기
            buf = io.BytesIO()
            base_canvas.save(buf, format="PNG")
            
            self.preview_ready.emit(buf.getvalue(), self.job_id)
            
        except Exception as e:
            self.preview_failed.emit(f"합성 에러: {str(e)}")

# ==========================================
# 실행 환경에 따른 동적 경로 설정 (빌드 배포용)
# ==========================================
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APPDATA_DIR = os.environ.get('APPDATA', '')
BRIDGE_DATA_DIR = os.path.join(APPDATA_DIR, "Ase-PS-Bridge")
if not os.path.exists(BRIDGE_DATA_DIR):
    os.makedirs(BRIDGE_DATA_DIR)
    
SETTINGS_FILE = os.path.join(BRIDGE_DATA_DIR, "bridge_settings.json")

# ==========================================
# 다국어 지원 (Localization)
# ==========================================
LANG = {
    "ko": {
        "title": "Ase-PS Bridge Pro",
        "clip_empty": "📋 클립보드: 비어있음",
        "clip_ready": "📋 {src} -> {dst} ({count}개 레이어)",
        "align_label": "정렬 기준:",
        "align_center": "Center (중앙 정렬)",
        "align_abs": "Absolute (절대 좌표)",
        "btn_ps_copy": "1. Photoshop에서 복사",
        "btn_ase_paste": "2. Aseprite로 붙여넣기 (F4)",
        "btn_ase_copy": "3. Aseprite에서 복사 (F5)",
        "btn_ps_paste": "4. Photoshop으로 붙여넣기",
        "btn_settings": "⚙️ 설정",
        "btn_clean": "🗑️ 임시파일 정리",
        "msg_started": "🚀 Bridge Pro 양방향 UI 시작됨.",
        "msg_detecting": "경로 자동 탐지 중...",
        "msg_detect_fail": "❌ 필수 실행 파일 경로를 찾지 못했습니다.",
        "msg_detect_success": "✅ 프로그램 설치 경로 자동 탐지 완료!",
        "msg_ase_setup_success": "✅ Aseprite 스크립트/단축키(F4/F5) 맵핑 완료! (단축키를 쓰기 전에 메뉴에서 수동 실행하여 Trust 승인 필요)",
        "msg_ase_setup_fail": "⚠️ Aseprite 단축키 맵핑 실패 (수동 설정 필요).",
        "msg_settings_saved": "✅ 설정이 저장되었습니다.",
        "msg_clean_success": "✅ 임시 폴더(Temp)가 깨끗하게 정리되었습니다! 확보된 용량: {size}MB",
        "msg_clean_fail": "❌ 임시 폴더 정리 실패: {error}",
        "msg_ps_copying": "PS: 레이어 추출 중...",
        "msg_ps_pasting": "PS: 레이어 조립 중...",
        "msg_ase_copying": "Aseprite: 레이어 추출 중...",
        "msg_ase_pasting": "Aseprite: 붙여넣기 중...",
        "msg_ps_success": "✅ 포토샵 작업이 성공적으로 완료되었습니다!",
        "msg_clip_update": "클립보드 갱신: {count}개 레이어 준비 완료.",
        "msg_transforming": "변환 적용 중...",
        "msg_transform_success": "✅ 변환 완료 (H:{h}, V:{v}, 각도:{a})",
        "msg_transform_fail": "❌ 변환 실패: {error}",
        "msg_transform_failed": "변환 실패",
        "msg_generating_preview": "미리보기 생성 중...",
        "msg_preview_failed": "미리보기 생성 실패",
        "err_no_ase_clip": "❌ [Error] 클립보드에 Aseprite 데이터가 없습니다.",
        "msg_ase_trust_err": "💡 힌트: 단축키가 작동하지 않거나 엉뚱한 창이 뜬다면, Aseprite 상단 메뉴 [File] ➔ [Scripts] 에서 직접 스크립트를 한 번씩 클릭하여 'Trust' 권한을 승인해 주세요.",
        "set_title": "⚙️ 브릿지 설정",
        "set_ps_path": "Photoshop 경로:",
        "set_ase_path": "Aseprite 경로:",
        "set_find": "찾기",
        "set_align": "기본 정렬 모드:",
        "set_lang": "언어 (Language):",
        "set_hotkey": "Aseprite 단축키 상태:",
        "set_force_reinstall": "Aseprite 스크립트/단축키 강제 재설치",
        "btn_tutorial": "❓ 튜토리얼",
        "tut_title": "📖 프로그램 사용 방법",
        "tut_content": "<b>[ 💡 Ase-PS Bridge Pro 사용 가이드 ]</b><br><br>"
                       "<b>1. 정방향 (Photoshop ➔ Aseprite)</b><br>"
                       "① Photoshop에서 옮길 레이어(또는 폴더)들을 다중 선택합니다.<br>"
                       "② 앱에서 <span style='color:#3b82f6;'>[1. Photoshop에서 복사]</span> 버튼을 누릅니다.<br>"
                       "③ Aseprite 캔버스로 넘어간 뒤, 앱의 <span style='color:#10b981;'>[2. Aseprite로 붙여넣기]</span> 버튼을 누르거나 키보드 <b>F4</b>를 누르면 완벽하게 붙여넣어집니다.<br><br>"
                       "<b>2. 역방향 (Aseprite ➔ Photoshop)</b><br>"
                       "① Aseprite에서 레이어를 선택한 뒤, 앱의 <span style='color:#f59e0b;'>[3. Aseprite에서 복사]</span> 버튼을 누르거나 키보드 <b>F5</b>를 누릅니다.<br>"
                       "② Photoshop 문서로 넘어가서, 앱의 <span style='color:#8b5cf6;'>[4. Photoshop으로 붙여넣기]</span> 버튼을 누릅니다.<br><br>"
                       "<b>⭐ 정렬 모드 설명 (Alignment)</b><br>"
                       "• <b>Center (중앙 정렬)</b>: 캔버스 크기가 달라도 캐릭터 덩어리를 화면 정중앙에 맞춰서 붙여넣습니다. (기본/권장)<br>"
                       "• <b>Absolute (절대 좌표)</b>: 중앙 보정 없이 원래 있던 좌표 그대로 꽂아넣습니다. (양쪽 캔버스 사이즈가 똑같을 때만 쓰세요)<br><br>"
                       "<b>⚠️ Warnings</b><br>"
                       "• <b>[필수] 최초 1회 스크립트 권한 승인</b><br>"
                       "  Aseprite의 보안 정책상, 단축키(F4/F5)를 누르기 전에 <b>반드시 상단 메뉴 [File] ➔ [Scripts]</b>에서 <b>aseprite_copy</b>와 <b>aseprite_paste</b>를 각각 수동으로 한 번씩 클릭해야 합니다.<br>"
                       "  경고창이 뜨면 <b>'Give full trust to this script(이 스크립트를 전적으로 신뢰함)'</b>에 체크하고 OK를 누르세요. 이후부터는 단축키가 정상 작동합니다.<br><br>"
                       "• <b>Aseprite의 '최근 파일(Recent Files)' 목록이 지저분해질 수 있습니다</b><br>"
                       "Ase-PS Bridge Pro는 픽셀 정확성과 레이어 보존을 위해 임시 이미지를 생성하여 Aseprite에 불러옵니다.<br>"
                       "이 과정에서 Aseprite의 '최근 파일(Recent Files)' 목록에 임시 파일들이 추가될 수 있습니다. 이는 정상적인 동작이며, 원본 데이터에는 전혀 영향을 주지 않습니다.<br><br>"
                       "<b>✔ 추천 작업 방식</b><br>"
                       "1. 자주 사용하는 작업 파일을 <b>'즐겨찾기(Favorites)'</b>에 추가하세요.<br>"
                       "2. Recent 목록 대신 Favorites를 기준으로 작업하세요.<br>"
                       "3. 필요 시 Recent 목록은 주기적으로 정리해 주세요.<br>"
                       "👉 이 방법을 사용하면 Recent 목록 문제 없이 쾌적하게 작업할 수 있습니다.",
        "tut_dont_show": "다음 실행부터 이 창을 띄우지 않음",
        "btn_flip_h": "↔ 좌우 반전",
        "btn_flip_v": "↕ 상하 반전",
        "btn_rotate": "↻ 90° 회전",
        "btn_undo": "↩ Undo",
        "btn_redo": "↪ Redo"
    },
    "en": {
        "title": "Ase-PS Bridge Pro",
        "clip_empty": "📋 Clipboard: Empty",
        "clip_ready": "📋 {src} -> {dst} ({count} Layers)",
        "align_label": "Alignment:",
        "align_center": "Center (Auto-Fit)",
        "align_abs": "Absolute (Original Pos)",
        "btn_ps_copy": "1. Copy from Photoshop",
        "btn_ase_paste": "2. Paste to Aseprite (F4)",
        "btn_ase_copy": "3. Copy from Aseprite (F5)",
        "btn_ps_paste": "4. Paste to Photoshop",
        "btn_settings": "⚙️ Settings",
        "btn_clean": "🗑️ Clean Temp",
        "btn_flip_h": "↔ Flip Horizontal",
        "btn_flip_v": "↕ Flip Vertical",
        "btn_rotate": "↻ Rotate 90°",
        "btn_undo": "↩ Undo",
        "btn_redo": "↪ Redo",
        "btn_tutorial": "❓ Tutorial",
        "msg_started": "🚀 Bridge Pro Bi-directional UI Started.",
        "msg_detecting": "Auto-detecting paths...",
        "msg_detect_fail": "❌ Failed to detect essential executable paths.",
        "msg_detect_success": "✅ Auto-detection of program paths completed!",
        "msg_ase_setup_success": "✅ Aseprite scripts & hotkeys (F4/F5) mapped successfully! (You must run them manually from the menu once to grant Trust permissions)",
        "msg_ase_setup_fail": "⚠️ Failed to map Aseprite hotkeys (Manual setup required).",
        "msg_settings_saved": "✅ Settings saved successfully.",
        "msg_clean_success": "✅ Temp folder cleaned successfully! Freed space: {size}MB",
        "msg_clean_fail": "❌ Failed to clean temp folder: {error}",
        "msg_ps_copying": "PS: Extracting layers...",
        "msg_ps_pasting": "PS: Assembling layers...",
        "msg_ase_copying": "Aseprite: Extracting layers...",
        "msg_ase_pasting": "Aseprite: Pasting layers...",
        "msg_ps_success": "✅ Photoshop task completed successfully!",
        "msg_clip_update": "Clipboard updated: {count} layers ready.",
        "msg_transforming": "Applying transformation...",
        "msg_transform_success": "✅ Transform applied (H:{h}, V:{v}, Angle:{a})",
        "msg_transform_fail": "❌ Transform failed: {error}",
        "msg_transform_failed": "Transform Failed",
        "msg_generating_preview": "Generating Preview...",
        "msg_preview_failed": "Preview Generation Failed",
        "err_no_ase_clip": "❌ [Error] No Aseprite data in clipboard.",
        "msg_ase_trust_err": "💡 Hint: If hotkeys (F4/F5) don't work or open wrong windows, go to Aseprite menu [File] ➔ [Scripts] and click the scripts manually once to grant 'Trust' permissions.",
        "set_title": "⚙️ Bridge Settings",
        "set_ps_path": "Photoshop Path:",
        "set_ase_path": "Aseprite Path:",
        "set_find": "Browse",
        "set_align": "Default Alignment:",
        "set_lang": "Language (언어):",
        "set_hotkey": "Aseprite Hotkey Status:",
        "set_force_reinstall": "Force Reinstall Aseprite Scripts/Hotkeys",
        "tut_title": "📖 How to use",
        "tut_content": "<b>[ 💡 Ase-PS Bridge Pro Guide ]</b><br><br>"
                       "<b>1. PS ➔ Aseprite</b><br>"
                       "① Select layers/folders in Photoshop.<br>"
                       "② Click <span style='color:#3b82f6;'>[1. Copy from Photoshop]</span>.<br>"
                       "③ Go to Aseprite, click <span style='color:#10b981;'>[2. Paste to Aseprite]</span> or press <b>F4</b>.<br><br>"
                       "<b>2. Aseprite ➔ PS</b><br>"
                       "① Select layers in Aseprite, click <span style='color:#f59e0b;'>[3. Copy from Aseprite]</span> or press <b>F5</b>.<br>"
                       "② Go to Photoshop, click <span style='color:#8b5cf6;'>[4. Paste to Photoshop]</span>.<br><br>"
                       "<b>⭐ Alignment Mode</b><br>"
                       "• <b>Center</b>: Auto-centers the bounding box of copied layers to the target canvas. (Recommended)<br>"
                       "• <b>Absolute</b>: Keeps the exact original X/Y coordinates. (Use only when canvas sizes are identical)<br><br>"
                       "<b>⚠️ Warnings</b><br>"
                       "• <b>[REQUIRED] First-time Script Trust Approval</b><br>"
                       "  Due to Aseprite's security policy, before using hotkeys (F4/F5), you <b>MUST manually click</b> <b>aseprite_copy</b> and <b>aseprite_paste</b> from the top menu: <b>[File] ➔ [Scripts]</b> once.<br>"
                       "  When the warning popup appears, check <b>'Give full trust to this script'</b> and click OK. Hotkeys will work normally afterwards.<br><br>"
                       "• <b>Aseprite 'Recent files' list may get messy</b><br>"
                       "  To ensure perfect pixel transfer, this tool repeatedly opens and closes temporary PNG files in the background, which will leave traces in Aseprite's recent files list.<br><br>"
                       "<b>✔ Recommended workflow</b><br>"
                       "1. Add your working files to <b>'Favorites'</b> in Aseprite.<br>"
                       "2. Always work from the Favorites list instead of Recent files.<br>"
                       "3. Occasionally clean up the Recent files list if needed.<br>"
                       "👉 This workflow avoids the Recent files issue and keeps your workspace stable.",
        "tut_dont_show": "Do not show this window on startup"
    },
    "ja": {
        "title": "Ase-PS Bridge Pro",
        "clip_empty": "📋 クリップボード：空",
        "clip_ready": "📋 {src} -> {dst} ({count}個のレイヤー)",
        "align_label": "配置の基準:",
        "align_center": "Center (中央揃え)",
        "align_abs": "Absolute (絶対座標)",
        "btn_ps_copy": "1. Photoshopからコピー",
        "btn_ase_paste": "2. Asepriteへペースト (F4)",
        "btn_ase_copy": "3. Asepriteからコピー (F5)",
        "btn_ps_paste": "4. Photoshopへペースト",
        "btn_settings": "⚙️ 設定",
        "btn_clean": "🗑️ 一時ファイル整理",
        "msg_started": "🚀 Bridge Pro 双方向UIが起動しました。",
        "msg_detecting": "パスの自動検出中...",
        "msg_detect_fail": "❌ 必須の実行ファイルパスが見つかりませんでした。",
        "msg_detect_success": "✅ プログラムのインストールパス自動検出完了！",
        "msg_ase_setup_success": "✅ Asepriteスクリプト/ショートカット(F4/F5)のマッピング完了！ (ショートカットを使う前に、メニューから1回手動で実行してTrust権限を承認してください)",
        "msg_ase_setup_fail": "⚠️ Asepriteショートカットのマッピング失敗 (手動設定が必要)。",
        "msg_settings_saved": "✅ 設定が保存されました。",
        "msg_clean_success": "✅ 一時フォルダ(Temp)が整理されました！確保された容量: {size}MB",
        "msg_clean_fail": "❌ 一時フォルダの整理失敗: {error}",
        "msg_ps_copying": "PS: レイヤーを抽出中...",
        "msg_ps_pasting": "PS: レイヤーを組み立て中...",
        "msg_ase_copying": "Aseprite: レイヤーを抽出中...",
        "msg_ase_pasting": "Aseprite: ペースト中...",
        "msg_ps_success": "✅ Photoshopの作業が正常に完了しました！",
        "msg_clip_update": "クリップボード更新: {count}個のレイヤーが準備完了。",
        "err_no_ase_clip": "❌ [Error] クリップボードにAsepriteのデータがありません。",
        "msg_ase_trust_err": "💡 ヒント: ショートカットが効かない、または別の機能が開く場合は、Asepriteの上部メニュー [File] ➔ [Scripts] から手動でスクリプトを1回ずつクリックし、「Trust(信頼)」権限を承認してください。",
        "set_title": "⚙️ ブリッジ設定",
        "set_ps_path": "Photoshopのパス:",
        "set_ase_path": "Asepriteのパス:",
        "set_find": "参照",
        "set_align": "デフォルトの配置モード:",
        "set_lang": "言語 (Language):",
        "set_hotkey": "Asepriteのショートカット状態:",
        "set_force_reinstall": "Asepriteスクリプト/ショートカットの強制再インストール",
        "btn_tutorial": "❓ チュートリアル",
        "tut_title": "📖 プログラムの使い方",
        "tut_content": "<b>[ 💡 Ase-PS Bridge Pro ガイド ]</b><br><br>"
                       "<b>1. 順方向 (Photoshop ➔ Aseprite)</b><br>"
                       "① Photoshopで転送するレイヤー(またはフォルダ)を複数選択します。<br>"
                       "② アプリの <span style='color:#3b82f6;'>[1. Photoshopからコピー]</span> ボタンを押します。<br>"
                       "③ Asepriteのキャンバスに移動し、アプリの <span style='color:#10b981;'>[2. Asepriteへペースト]</span> ボタンを押すか、キーボードの <b>F4</b> を押すと完璧にペーストされます。<br><br>"
                       "<b>2. 逆方向 (Aseprite ➔ Photoshop)</b><br>"
                       "① Asepriteでレイヤーを選択した後、アプリの <span style='color:#f59e0b;'>[3. Asepriteからコピー]</span> ボタンを押すか、キーボードの <b>F5</b> を押します。<br>"
                       "② Photoshopのドキュメントに移動し、アプリの <span style='color:#8b5cf6;'>[4. Photoshopへペースト]</span> ボタンを押します。<br><br>"
                       "<b>⭐ 配置モードの説明 (Alignment)</b><br>"
                       "• <b>Center (中央揃え)</b>: キャンバスのサイズが異なっても、キャラクター全体を画面の中央に合わせてペーストします。(推奨)<br>"
                       "• <b>Absolute (絶対座標)</b>: 中央補正を行わず、元の座標のままペーストします。(両方のキャンバスサイズが完全に同じ時だけ使用してください)<br><br>"
                       "<b>⚠️ Warnings (注意事項)</b><br>"
                       "• <b>[必須] 初回実行時のスクリプト権限承認</b><br>"
                       "  Asepriteのセキュリティポリシーにより、ショートカット(F4/F5)を使用する前に、<b>必ず上部メニュー [File] ➔ [Scripts]</b> から <b>aseprite_copy</b> と <b>aseprite_paste</b> を手動で1回ずつクリックしてください。<br>"
                       "  警告窓が表示されたら、<b>'Give full trust to this script(このスクリプトを完全に信頼する)'</b> にチェックを入れてOKを押します。以降はショートカットが正常に動作します。<br><br>"
                       "• <b>Asepriteの「最近開いたファイル(Recent files)」リストが汚れる可能性があります</b><br>"
                       "完璧なピクセル転送のため、バックグラウンドで一時的なPNGファイルを開閉します。そのため、Asepriteの「最近開いたファイル(Recent files)」リストに一時ファイルが残る場合があります。これは正常な動作であり、データに影響はありません。<br><br>"
                       "<b>✔ お勧めの作業方法</b><br>"
                       "1. よく使う作業ファイルは<b>「お気に入り(Favorites)」</b>に追加してください。<br>"
                       "2. Recentリストの代わりにお気に入りを基準に作業してください。<br>"
                       "3. 必要に応じてRecentリストを定期的に整理してください。",
        "tut_dont_show": "次回からこのウィンドウを表示しない",
        "btn_flip_h": "↔ 左右反転",
        "btn_flip_v": "↕ 上下反転",
        "btn_rotate": "↻ 90° 回転",
        "btn_undo": "↩ 元に戻す",
        "btn_redo": "↪ やり直し",
        "msg_transforming": "変形を適用中...",
        "msg_transform_success": "✅ 変形完了 (H:{h}, V:{v}, 角度:{a})",
        "msg_transform_fail": "❌ 変形失敗: {error}",
        "msg_transform_failed": "変形失敗",
        "msg_generating_preview": "プレビュー生成中...",
        "msg_preview_failed": "プレビュー生成失敗"
    }
}

# ==========================================
# 설정 관리 (Settings Management)
# ==========================================
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"language": "en"} # 기본값 영어

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"설정 저장 실패: {e}")

# ==========================================
# 설치 경로 탐색 및 환경 구성 함수들
# ==========================================
def find_photoshop_exe() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Photoshop.exe") as key:
            ps_path, _ = winreg.QueryValueEx(key, "")
            if ps_path and os.path.exists(ps_path): return ps_path
    except Exception:
        pass
    try:
        base_key_path = r"SOFTWARE\Adobe\Photoshop"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_key_path) as base_key:
            versions = [winreg.EnumKey(base_key, i) for i in range(winreg.QueryInfoKey(base_key)[0])]
            versions.sort(key=lambda v: float(v) if v.replace('.','',1).isdigit() else 0, reverse=True)
            for v in versions:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{base_key_path}\\{v}") as v_key:
                        app_path, _ = winreg.QueryValueEx(v_key, "ApplicationPath")
                        exe_path = os.path.join(app_path, "Photoshop.exe")
                        if os.path.exists(exe_path): return exe_path
                except Exception:
                    continue
    except Exception:
        pass
    return ""

def find_aseprite_exe() -> str:
    common_paths = [
        r"C:\Program Files (x86)\Steam\steamapps\common\Aseprite\aseprite.exe",
        r"C:\Program Files\Steam\steamapps\common\Aseprite\aseprite.exe",
        r"C:\Program Files\Aseprite\aseprite.exe",
        r"C:\Program Files (x86)\Aseprite\aseprite.exe"
    ]
    for path in common_paths:
        if os.path.exists(path): return path
    which_path = shutil.which("aseprite")
    if which_path and os.path.exists(which_path): return os.path.normpath(which_path)
    return ""

def setup_aseprite_environment(orig_paste_lua: str, orig_copy_lua: str) -> (bool, str):
    appdata = os.environ.get('APPDATA')
    if not appdata: return False, "APPDATA environment variable not found."

    ase_dir = os.path.join(appdata, "Aseprite")
    scripts_dir = os.path.join(ase_dir, "scripts")
    if not os.path.exists(scripts_dir): os.makedirs(scripts_dir)

    target_paste_lua = os.path.join(scripts_dir, "aseprite_paste.lua")
    target_copy_lua = os.path.join(scripts_dir, "aseprite_copy.lua")
    
    import filecmp
    try:
        if not os.path.exists(target_paste_lua) or not filecmp.cmp(orig_paste_lua, target_paste_lua, shallow=False):
            shutil.copy2(orig_paste_lua, target_paste_lua)
        if not os.path.exists(target_copy_lua) or not filecmp.cmp(orig_copy_lua, target_copy_lua, shallow=False):
            shutil.copy2(orig_copy_lua, target_copy_lua)
    except Exception as e:
        return False, f"Script copy failed: {e}"

    keys_file = os.path.join(ase_dir, "user.aseprite-keys")
    if not os.path.exists(keys_file):
        root = ET.Element("keyboard", {"version": "1"})
        commands = ET.SubElement(root, "commands")
        tree = ET.ElementTree(root)
    else:
        try:
            tree = ET.parse(keys_file)
            root = tree.getroot()
            commands = root.find("commands")
            if commands is None: commands = ET.SubElement(root, "commands")
        except Exception as e:
            return False, f"Keyboard settings read failed: {e}"

    scripts_to_register = [(target_paste_lua, "F4"), (target_copy_lua, "F5")]
    modified = False

    for script_path, hotkey in scripts_to_register:
        script_path = os.path.normpath(script_path)
        found_existing = False

        for key_node in commands.findall("key"):
            if key_node.get("shortcut") == hotkey:
                param_node = key_node.find("param")
                if param_node is not None and param_node.get("name") == "filename" and param_node.get("value") == script_path:
                    found_existing = True
                else:
                    key_node.attrib.pop("shortcut", None) 
                    modified = True

        if not found_existing:
            for key_node in commands.findall("key"):
                if key_node.get("command") == "RunScript":
                    param_node = key_node.find("param")
                    if param_node is not None and param_node.get("name") == "filename" and param_node.get("value") == script_path:
                        key_node.set("shortcut", hotkey)
                        found_existing = True
                        modified = True
                        break

        if not found_existing:
            new_key = ET.SubElement(commands, "key", {"command": "RunScript", "shortcut": hotkey})
            ET.SubElement(new_key, "param", {"name": "filename", "value": script_path})
            modified = True

    if modified:
        try:
            tree.write(keys_file, encoding="utf-8", xml_declaration=True)
        except Exception as e:
            return False, f"Settings overwrite failed: {e}"
            
    return True, "F4, F5 Hotkeys registered in Aseprite."

# ==========================================
# Worker Threads & Status Pollers
# ==========================================
class PhotoshopCLIWorker(QThread):
    finished = Signal(bool, str) # 성공여부, 메시지
    log = Signal(str)

    def __init__(self, jsx_template_path, ps_exe_path, job_id, temp_dir, align_mode):
        super().__init__()
        self.jsx_template_path = jsx_template_path
        self.ps_exe_path = ps_exe_path
        self.job_id = job_id
        self.temp_dir = temp_dir
        self.align_mode = align_mode
        self.job_path = os.path.join(self.temp_dir, self.job_id)

    def run(self):
        try:
            if not os.path.exists(self.job_path):
                os.makedirs(self.job_path)

            done_file = os.path.join(self.job_path, "status_done.json")
            error_file = os.path.join(self.job_path, "status_error.txt")
            if os.path.exists(done_file): os.remove(done_file)
            if os.path.exists(error_file): os.remove(error_file)

            with open(self.jsx_template_path, "r", encoding="utf-8") as f:
                script_content = f.read()

            safe_job_path = self.job_path.replace("\\", "\\\\")
            script_content = script_content.replace('"REPLACE_ME_JOB_PATH"', f'"{safe_job_path}"')
            script_content = script_content.replace('"REPLACE_ME_ALIGN_MODE"', f'"{self.align_mode}"')

            wrapper_jsx_path = os.path.join(self.job_path, "run_bridge.jsx")
            with open(wrapper_jsx_path, "w", encoding="utf-8") as f:
                f.write(script_content)

            if not self.ps_exe_path or not os.path.exists(self.ps_exe_path):
                cmd = 'powershell.exe -NoProfile -Command "(Get-Process Photoshop -ErrorAction SilentlyContinue).Path | Select-Object -First 1"'
                result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                self.ps_exe_path = result.stdout.strip()

            if not self.ps_exe_path or not os.path.exists(self.ps_exe_path):
                self.finished.emit(False, "포토샵 프로세스를 찾을 수 없습니다. (Photoshop process not found)")
                return

            self.log.emit("🔄 [CLI] 전송 중... (Sending command...)")

            subprocess.Popen([self.ps_exe_path, wrapper_jsx_path], creationflags=subprocess.CREATE_NO_WINDOW)
            
            timeout = 30
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                if os.path.exists(error_file):
                    time.sleep(0.2)
                    try:
                        with open(error_file, "r", encoding="utf-8") as f:
                            err_msg = f.read()
                    except:
                        err_msg = "Unknown Error"
                    self.finished.emit(False, err_msg)
                    return
                
                if os.path.exists(done_file):
                    time.sleep(0.2)
                    self.finished.emit(True, "Success")
                    return
                    
                time.sleep(0.5)

            self.finished.emit(False, "포토샵 응답 시간 초과. (Photoshop timeout)")

        except Exception as e:
            self.finished.emit(False, f"시스템 에러 (System error): {str(e)}")

class AsepriteWorker(QThread):
    finished = Signal()
    error = Signal(str)
    log = Signal(str)

    def __init__(self, ase_exe, lua_path=None, trigger_hotkey=False):
        super().__init__()
        self.ase_exe = ase_exe
        self.lua_path = lua_path
        self.trigger_hotkey = trigger_hotkey

    def run(self):
        try:
            if self.trigger_hotkey:
                import win32gui
                import win32con
                import time
                hwnd = win32gui.FindWindow("Aseprite", None)
                if hwnd == 0:
                    def callback(h, hwnds):
                        title = win32gui.GetWindowText(h)
                        if "Aseprite" in title: hwnds.append(h)
                        return True
                    hwnds = []
                    win32gui.EnumWindows(callback, hwnds)
                    if hwnds: hwnd = hwnds[0]

                if hwnd == 0:
                    raise Exception("Aseprite가 실행 중이 아닙니다. (Aseprite is not running)")

                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.1)

                import ctypes
                VK_F4 = 0x73
                VK_F5 = 0x74
                KEYEVENTF_KEYUP = 0x0002
                
                vk_code = VK_F5 if "copy" in (self.lua_path or "") else VK_F4
                hotkey_name = "F5" if "copy" in (self.lua_path or "") else "F4"
                
                ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
                time.sleep(0.05)
                ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
                
                self.log.emit(f"단축키({hotkey_name}) 전송 완료. (Hotkey sent)")
            else:
                cmd = f'start "" "{self.ase_exe}" --script "{self.lua_path}"'
                subprocess.run(cmd, shell=True)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

# ==========================================
# Settings Dialog
# ==========================================
class SettingsDialog(QDialog):
    def __init__(self, current_settings, lang_dict, parent=None):
        super().__init__(parent)
        self.lang = lang_dict
        self.setWindowTitle(self.lang["set_title"])
        self.setFixedSize(500, 350)
        self.current_settings = current_settings
        
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        
        # Photoshop 경로
        self.ps_path_input = QLineEdit(self.current_settings.get("photoshop_exe", ""))
        ps_btn = QPushButton(self.lang["set_find"])
        ps_btn.clicked.connect(lambda: self.browse_exe(self.ps_path_input))
        ps_layout = QHBoxLayout()
        ps_layout.addWidget(self.ps_path_input)
        ps_layout.addWidget(ps_btn)
        form_layout.addRow(self.lang["set_ps_path"], ps_layout)
        
        # Aseprite 경로
        self.ase_path_input = QLineEdit(self.current_settings.get("aseprite_exe", ""))
        ase_btn = QPushButton(self.lang["set_find"])
        ase_btn.clicked.connect(lambda: self.browse_exe(self.ase_path_input))
        ase_layout = QHBoxLayout()
        ase_layout.addWidget(self.ase_path_input)
        ase_layout.addWidget(ase_btn)
        form_layout.addRow(self.lang["set_ase_path"], ase_layout)
        
        # Alignment 기본값
        self.align_combo = QButtonGroup(self)
        align_hlayout = QHBoxLayout()
        self.rb_center = QRadioButton(self.lang["align_center"])
        self.rb_absolute = QRadioButton(self.lang["align_abs"])
        self.align_combo.addButton(self.rb_center, 1)
        self.align_combo.addButton(self.rb_absolute, 2)
        
        if self.current_settings.get("default_alignment", "center") == "absolute":
            self.rb_absolute.setChecked(True)
        else:
            self.rb_center.setChecked(True)
            
        align_hlayout.addWidget(self.rb_center)
        align_hlayout.addWidget(self.rb_absolute)
        form_layout.addRow(self.lang["set_align"], align_hlayout)
        
        # 언어 설정 (Language)
        self.lang_combo = QButtonGroup(self)
        lang_hlayout = QHBoxLayout()
        self.rb_ko = QRadioButton("한국어")
        self.rb_en = QRadioButton("English")
        self.rb_ja = QRadioButton("日本語")
        self.lang_combo.addButton(self.rb_ko, 1)
        self.lang_combo.addButton(self.rb_en, 2)
        self.lang_combo.addButton(self.rb_ja, 3)
        
        current_lang = self.current_settings.get("language", "ko")
        if current_lang == "en":
            self.rb_en.setChecked(True)
        elif current_lang == "ja":
            self.rb_ja.setChecked(True)
        else:
            self.rb_ko.setChecked(True)
            
        lang_hlayout.addWidget(self.rb_ko)
        lang_hlayout.addWidget(self.rb_en)
        lang_hlayout.addWidget(self.rb_ja)
        form_layout.addRow(self.lang["set_lang"], lang_hlayout)
        
        layout.addLayout(form_layout)
        
        # 단축키 상태 표시
        self.hotkey_status = QLabel(self.current_settings.get("hotkey_status", "Unknown"))
        self.hotkey_status.setStyleSheet("color: #059669; font-weight: bold;")
        layout.addWidget(QLabel(f"<b>{self.lang['set_hotkey']}</b>"))
        layout.addWidget(self.hotkey_status)

        # 재설정 버튼
        btn_reconfigure = QPushButton(self.lang["set_force_reinstall"])
        btn_reconfigure.clicked.connect(self.force_reconfigure)
        layout.addWidget(btn_reconfigure)
        
        # 확인/취소
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def browse_exe(self, line_edit):
        path, _ = QFileDialog.getOpenFileName(self, "Select Executable", "C:\\", "Executables (*.exe)")
        if path:
            line_edit.setText(path)

    def force_reconfigure(self):
        ase_paste_lua_orig = os.path.join(BASE_DIR, "scripts", "aseprite_paste.lua")
        ase_copy_lua_orig = os.path.join(BASE_DIR, "scripts", "aseprite_copy.lua")
        success, msg = setup_aseprite_environment(ase_paste_lua_orig, ase_copy_lua_orig)
        if success:
            QMessageBox.information(self, "Success", msg)
            self.hotkey_status.setText("✅ 정상 (F4=Paste, F5=Copy)")
        else:
            QMessageBox.critical(self, "Failed", msg)
            self.hotkey_status.setText(f"❌ Failed: {msg}")

    def get_settings(self):
        lang = "ko"
        if self.rb_en.isChecked():
            lang = "en"
        elif self.rb_ja.isChecked():
            lang = "ja"
            
        return {
            "photoshop_exe": self.ps_path_input.text(),
            "aseprite_exe": self.ase_path_input.text(),
            "default_alignment": "center" if self.rb_center.isChecked() else "absolute",
            "language": lang,
            "hotkey_status": self.hotkey_status.text()
        }

# ==========================================
# Tutorial Dialog
# ==========================================
from PySide6.QtWidgets import QCheckBox

class TutorialDialog(QDialog):
    def __init__(self, lang_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(lang_dict["tut_title"])
        self.setMinimumSize(400, 350)
        self.parent_app = parent
        
        layout = QVBoxLayout(self)
        
        content_label = QLabel(lang_dict["tut_content"])
        content_label.setWordWrap(True)
        content_label.setStyleSheet("font-size: 13px; line-height: 1.5;")
        layout.addWidget(content_label)
        
        self.cb_dont_show = QCheckBox(lang_dict["tut_dont_show"])
        layout.addWidget(self.cb_dont_show)
        
        btn_close = QPushButton("OK")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignCenter)

    def accept(self):
        if self.parent_app and hasattr(self.parent_app, 'settings'):
            if self.cb_dont_show.isChecked():
                self.parent_app.settings["show_tutorial"] = False
                save_settings(self.parent_app.settings)
        super().accept()

# ==========================================
# Main UI Window
# ==========================================
class BridgeApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setMinimumSize(440, 620) # 너비 확장 (380 -> 440)
        self.resize(440, 620)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Window)

        # 경로 캐싱
        self.ps_copy_jsx = os.path.join(BASE_DIR, "scripts", "photoshop_copy.jsx")
        self.ps_paste_jsx = os.path.join(BASE_DIR, "scripts", "photoshop_paste.jsx")
        self.ase_copy_lua_orig = os.path.join(BASE_DIR, "scripts", "aseprite_copy.lua")
        self.ase_paste_lua_orig = os.path.join(BASE_DIR, "scripts", "aseprite_paste.lua")
        self.temp_dir = os.path.join(BASE_DIR, "temp")
        
        self.last_job_id = None
        self.current_job_path = None
        self.clipboard_source = None 
        self.clipboard_count = 0
        
        # 변환 상태 관리
        self.cur_h = False
        self.cur_v = False
        self.cur_angle = 0
        self.undo_stack = []
        self.redo_stack = []
        
        self.processed_jobs = set()
        self.clipboard_empty_count = 0
        self.ui_busy_transform = False
        self.ui_busy_preview = False
        self.ui_busy_transfer = False
        self.pending_preview_path = None
        self.pending_preview_id = None
        
        # 설정 불러오기 및 초기화
        is_first_run = not os.path.exists(SETTINGS_FILE)
        self.settings = load_settings()
        
        # 첫 실행 시 언어 선택 팝업 (취소 시 영어 기본값)
        if is_first_run:
            try:
                from PySide6.QtWidgets import QInputDialog
                items = ["English", "한국어", "日本語"]
                item, ok = QInputDialog.getItem(None, "Language / 언어 / 言語", "Select Language:", items, 0, False)
                if ok and item:
                    if item == "한국어":
                        self.settings["language"] = "ko"
                    elif item == "日本語":
                        self.settings["language"] = "ja"
                    else:
                        self.settings["language"] = "en"
                else:
                    self.settings["language"] = "en"
                save_settings(self.settings)
            except Exception:
                self.settings["language"] = "en"
                save_settings(self.settings)

        self.current_lang = self.settings.get("language", "en") # 기본값 fallback 보장
        if self.current_lang not in LANG:
            self.current_lang = "en"
            
        self.t = LANG[self.current_lang]
        
        self.setWindowTitle(self.t["title"])
        self.init_environment()

        self.init_ui()
        self.init_timers()
        self.log_message(self.t["msg_started"])
        
        # 튜토리얼 자동 표시 로직
        if self.settings.get("show_tutorial", True):
            QTimer.singleShot(500, self.show_tutorial)

    def init_environment(self):
        updated = False
        
        if self.settings.get("active_temp_path") != self.temp_dir:
            self.settings["active_temp_path"] = self.temp_dir
            updated = True
            
        if not self.settings.get("photoshop_exe"):
            self.settings["photoshop_exe"] = find_photoshop_exe()
            updated = True
            
        if not self.settings.get("aseprite_exe"):
            self.settings["aseprite_exe"] = find_aseprite_exe()
            updated = True

        if not self.settings.get("hotkey_status") or "❌" in self.settings.get("hotkey_status", ""):
            success, msg = setup_aseprite_environment(self.ase_paste_lua_orig, self.ase_copy_lua_orig)
            self.settings["hotkey_status"] = "✅ 정상 (F4=Paste, F5=Copy)" if success else f"❌ {msg}"
            updated = True

        if not self.settings.get("default_alignment"):
            self.settings["default_alignment"] = "center"
            updated = True
            
        if not self.settings.get("language"):
            self.settings["language"] = "en"
            updated = True

        if updated:
            save_settings(self.settings)

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # 상단 상태바 및 세팅 버튼, 클린업 버튼
        top_layout = QHBoxLayout()
        self.status_label = QLabel(self.t["clip_empty"])
        self.status_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("padding: 10px; background-color: #f0f0f0; border-radius: 5px;")
        
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(5)
        
        self.btn_clean = QPushButton(self.t["btn_clean"])
        self.btn_clean.setStyleSheet("background-color: #ef4444; color: white; border-radius: 4px; padding: 5px;")
        self.btn_clean.clicked.connect(self.clean_temp_folder)
        
        settings_tut_layout = QHBoxLayout()
        self.btn_tutorial = QPushButton(self.t["btn_tutorial"])
        self.btn_tutorial.clicked.connect(self.show_tutorial)
        
        self.btn_settings = QPushButton(self.t["btn_settings"])
        self.btn_settings.clicked.connect(self.open_settings)
        
        settings_tut_layout.addWidget(self.btn_tutorial)
        settings_tut_layout.addWidget(self.btn_settings)
        
        btn_layout.addWidget(self.btn_clean)
        btn_layout.addLayout(settings_tut_layout)
        
        top_layout.addWidget(self.status_label, stretch=1)
        top_layout.addLayout(btn_layout)
        layout.addLayout(top_layout)

        # === 썸네일 Preview 영역 ===
        self.preview_label = QLabel("No Preview")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFixedSize(350, 160)
        self.preview_label.setStyleSheet("""
            background-color: #e5e7eb;
            background-image: repeating-linear-gradient(45deg, #d1d5db 25%, transparent 25%, transparent 75%, #d1d5db 75%, #d1d5db);
            background-position: 0 0, 10px 10px;
            background-size: 20px 20px;
            border-radius: 5px;
            border: 1px solid #d1d5db;
        """)
        layout.addWidget(self.preview_label, alignment=Qt.AlignCenter)

        # === 🔄 변환(Transform) 컨트롤 영역 ===
        flip_layout = QHBoxLayout()
        self.btn_flip_h = QPushButton(self.t.get("btn_flip_h", "↔ 좌우 반전"))
        self.btn_flip_v = QPushButton(self.t.get("btn_flip_v", "↕ 상하 반전"))
        self.btn_rotate = QPushButton(self.t.get("btn_rotate", "↻ 90° 회전"))
        
        self.btn_flip_h.setEnabled(False)
        self.btn_flip_v.setEnabled(False)
        self.btn_rotate.setEnabled(False)
        
        btn_style = "background-color: #4b5563; color: white; border-radius: 4px; padding: 5px;"
        self.btn_flip_h.setStyleSheet(btn_style)
        self.btn_flip_v.setStyleSheet(btn_style)
        self.btn_rotate.setStyleSheet(btn_style)

        # Undo/Redo 버튼
        self.btn_undo = QPushButton(self.t.get("btn_undo", "↩ Undo"))
        self.btn_redo = QPushButton(self.t.get("btn_redo", "↪ Redo"))
        self.btn_undo.setEnabled(False)
        self.btn_redo.setEnabled(False)
        self.btn_undo.setStyleSheet(btn_style)
        self.btn_redo.setStyleSheet(btn_style)

        # 클릭 이벤트 연결 (Lambda 제거)
        self.btn_flip_h.clicked.connect(self.handle_flip_h)
        self.btn_flip_v.clicked.connect(self.handle_flip_v)
        self.btn_rotate.clicked.connect(self.handle_rotate)
        self.btn_undo.clicked.connect(self.handle_undo)
        self.btn_redo.clicked.connect(self.handle_redo)

        flip_layout.addWidget(self.btn_undo)
        flip_layout.addWidget(self.btn_flip_h)
        flip_layout.addWidget(self.btn_flip_v)
        flip_layout.addWidget(self.btn_rotate)
        flip_layout.addWidget(self.btn_redo)
        layout.addLayout(flip_layout)

        # 정렬 모드
        align_layout = QHBoxLayout()
        self.radio_center = QRadioButton(self.t["align_center"])
        self.radio_absolute = QRadioButton(self.t["align_abs"])
        
        if self.settings.get("default_alignment") == "absolute":
            self.radio_absolute.setChecked(True)
        else:
            self.radio_center.setChecked(True)
            
        self.align_group = QButtonGroup()
        self.align_group.addButton(self.radio_center, 1)
        self.align_group.addButton(self.radio_absolute, 2)
        
        align_layout.addWidget(QLabel(self.t["align_label"]))
        align_layout.addWidget(self.radio_center)
        align_layout.addWidget(self.radio_absolute)
        layout.addLayout(align_layout)

        # === 정방향 ===
        self.btn_ps_copy = QPushButton(self.t["btn_ps_copy"])
        self.btn_ps_copy.setMinimumHeight(40)
        self.btn_ps_copy.setStyleSheet("background-color: #3b82f6; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_ps_copy.clicked.connect(self.run_ps_copy)
        layout.addWidget(self.btn_ps_copy)

        self.btn_ase_paste = QPushButton(self.t["btn_ase_paste"])
        self.btn_ase_paste.setMinimumHeight(40)
        self.btn_ase_paste.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_ase_paste.setEnabled(False)
        self.btn_ase_paste.clicked.connect(self.run_ase_paste)
        layout.addWidget(self.btn_ase_paste)

        # === 역방향 ===
        self.btn_ase_copy = QPushButton(self.t["btn_ase_copy"])
        self.btn_ase_copy.setMinimumHeight(40)
        self.btn_ase_copy.setStyleSheet("background-color: #f59e0b; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_ase_copy.clicked.connect(self.run_ase_copy)
        layout.addWidget(self.btn_ase_copy)

        self.btn_ps_paste = QPushButton(self.t["btn_ps_paste"])
        self.btn_ps_paste.setMinimumHeight(40)
        self.btn_ps_paste.setStyleSheet("background-color: #8b5cf6; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_ps_paste.setEnabled(False)
        self.btn_ps_paste.clicked.connect(self.run_ps_paste)
        layout.addWidget(self.btn_ps_paste)

        # 로그 콘솔
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setFont(QFont("Consolas", 8))
        self.log_console.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; padding: 5px;")
        layout.addWidget(self.log_console)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        
    def show_tutorial(self):
        dlg = TutorialDialog(self.t, self)
        dlg.exec()
        
    def refresh_ui_language(self):
        self.t = LANG[self.current_lang]
        self.setWindowTitle(self.t["title"])
        self.radio_center.setText(self.t["align_center"])
        self.radio_absolute.setText(self.t["align_abs"])
        self.btn_ps_copy.setText(self.t["btn_ps_copy"])
        self.btn_ase_paste.setText(self.t["btn_ase_paste"])
        self.btn_ase_copy.setText(self.t["btn_ase_copy"])
        self.btn_ps_paste.setText(self.t["btn_ps_paste"])
        
        # 추가된 버튼들의 텍스트 갱신
        self.btn_clean.setText(self.t["btn_clean"])
        self.btn_tutorial.setText(self.t["btn_tutorial"])
        self.btn_settings.setText(self.t["btn_settings"])
        
        # 변환 버튼 텍스트 갱신
        self.btn_flip_h.setText(self.t.get("btn_flip_h", "↔ 좌우 반전"))
        self.btn_flip_v.setText(self.t.get("btn_flip_v", "↕ 상하 반전"))
        self.btn_rotate.setText(self.t.get("btn_rotate", "↻ 90° 회전"))
        self.btn_undo.setText(self.t.get("btn_undo", "↩ Undo"))
        self.btn_redo.setText(self.t.get("btn_redo", "↪ Redo"))

        if not self.last_job_id:
            self.update_status(self.t["clip_empty"], "#f3f4f6", "#374151")
        else:
            if getattr(self, "clipboard_source", "") == "photoshop":
                msg = self.t["clip_ready"].format(src="PS", dst="Ase", count=getattr(self, "clipboard_count", 0))
                self.update_status(msg, "#dbeafe", "#1e40af")
            elif getattr(self, "clipboard_source", "") == "aseprite":
                msg = self.t["clip_ready"].format(src="Ase", dst="PS", count=getattr(self, "clipboard_count", 0))
                self.update_status(msg, "#fef3c7", "#b45309")

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self.t, self)
        if dlg.exec():
            self.settings = dlg.get_settings()
            save_settings(self.settings)
            
            if self.settings.get("default_alignment") == "absolute":
                self.radio_absolute.setChecked(True)
            else:
                self.radio_center.setChecked(True)
                
            new_lang = self.settings.get("language", "ko")
            if new_lang != self.current_lang:
                self.current_lang = new_lang
                self.refresh_ui_language()
                
            self.log_message(self.t["msg_settings_saved"])
            
    def clean_temp_folder(self):
        try:
            if not os.path.exists(self.temp_dir):
                return
                
            total_size = 0
            for item in os.listdir(self.temp_dir):
                item_path = os.path.join(self.temp_dir, item)
                if os.path.isdir(item_path):
                    for dirpath, _, filenames in os.walk(item_path):
                        for f in filenames:
                            fp = os.path.join(dirpath, f)
                            if not os.path.islink(fp):
                                total_size += os.path.getsize(fp)
                    shutil.rmtree(item_path, ignore_errors=True)
                else:
                    total_size += os.path.getsize(item_path)
                    os.remove(item_path)
            
            # Reset UI states
            self.last_job_id = None
            self.current_job_path = None
            self.clipboard_source = None 
            self.clipboard_count = 0
            self.processed_jobs = set()
            
            # 🌟 [추가] 변환 및 프리뷰 플래그/예약 상태 초기화
            self.ui_busy_transform = False
            self.ui_busy_preview = False
            self.pending_preview_path = None
            self.pending_preview_id = None
            
            self.update_status(self.t["clip_empty"], "#f3f4f6", "#374151")
            self.btn_ase_paste.setEnabled(False)
            self.btn_ps_paste.setEnabled(False)
            self.clear_preview()
            
            # 실제 윈도우 클립보드도 완전히 비워서 QTimer가 다시 읽어오는 것을 방지
            try:
                import win32clipboard
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.CloseClipboard()
            except:
                pass
            
            size_mb = round(total_size / (1024 * 1024), 2)
            self.log_message(self.t["msg_clean_success"].format(size=size_mb))
            
        except Exception as e:
            self.log_message(self.t["msg_clean_fail"].format(error=str(e)))

    def init_timers(self):
        self.clip_timer = QTimer(self)
        self.clip_timer.timeout.connect(self.check_clipboard)
        self.clip_timer.timeout.connect(self.check_temp_folder)
        self.clip_timer.start(1000)

    def log_message(self, message):
        time_str = time.strftime('%H:%M:%S')
        self.log_console.append(f"[{time_str}] {message}")
        self.log_console.verticalScrollBar().setValue(self.log_console.verticalScrollBar().maximum())

    def get_align_mode(self):
        return "center" if self.radio_center.isChecked() else "absolute"

    def check_temp_folder(self):
        try:
            if not os.path.exists(self.temp_dir): return
            for job_id in os.listdir(self.temp_dir):
                if job_id in self.processed_jobs: continue
                job_path = os.path.join(self.temp_dir, job_id)
                if not os.path.isdir(job_path): continue
                
                trigger_path = os.path.join(job_path, "trigger_copy.json")
                if os.path.exists(trigger_path):
                    time.sleep(0.1)
                    try:
                        with open(trigger_path, "r", encoding="utf-8") as f:
                            payload = json.load(f)
                            
                        payload["settings"] = {"align_mode": self.get_align_mode()}
                            
                        import win32clipboard
                        payload_str = json.dumps(payload, ensure_ascii=False)
                        win32clipboard.OpenClipboard()
                        win32clipboard.EmptyClipboard()
                        win32clipboard.SetClipboardText(payload_str, win32clipboard.CF_UNICODETEXT)
                        win32clipboard.CloseClipboard()
                        
                        self.processed_jobs.add(job_id)
                    except Exception as parse_err:
                        pass
        except Exception:
            pass

    # 🌟 [신규 추가] Preview 처리 메서드
    def set_preview_image(self, img_bytes):
        pixmap = QPixmap()
        pixmap.loadFromData(img_bytes, "PNG")
        self.preview_label.setPixmap(pixmap)

    def is_transforming(self):
        return self.ui_busy_transform or (hasattr(self, "transform_worker") and self.transform_worker.isRunning())

    def is_previewing(self):
        return self.ui_busy_preview or (hasattr(self, "preview_worker") and self.preview_worker.isRunning())

    def is_transferring(self):
        return getattr(self, "ui_busy_transfer", False) or \
               (hasattr(self, "ps_worker") and self.ps_worker.isRunning()) or \
               (hasattr(self, "ase_worker") and self.ase_worker.isRunning())

    def update_ui_state(self):
        """Job 유효성 및 모든 워커 상태를 검증하여 일관된 UI 상태 유지"""
        valid_job = (self.last_job_id is not None) and \
                    (self.current_job_path is not None) and \
                    (os.path.exists(self.current_job_path))
        
        transforming = self.is_transforming()
        previewing = self.is_previewing()
        transferring = self.is_transferring()
        
        # [변환 버튼군] - 파일 수정 작업, 프리뷰 합성, 전송 작업 중일 때 잠금
        can_transform = valid_job and not transforming and not previewing and not transferring
        self.btn_flip_h.setEnabled(can_transform)
        self.btn_flip_v.setEnabled(can_transform)
        self.btn_rotate.setEnabled(can_transform)
        self.btn_undo.setEnabled(can_transform and len(self.undo_stack) > 0)
        self.btn_redo.setEnabled(can_transform and len(self.redo_stack) > 0)
        
        # [복사/붙여넣기 버튼군] - 전송 및 변환 작업 중에는 잠금
        can_transfer = not transferring and not transforming
        self.btn_ps_copy.setEnabled(can_transfer)
        self.btn_ase_copy.setEnabled(can_transfer)
        
        can_paste = valid_job and can_transfer
        self.btn_ase_paste.setEnabled(can_paste and self.clipboard_source == "photoshop")
        self.btn_ps_paste.setEnabled(can_paste and self.clipboard_source == "aseprite")

    def clear_preview(self):
        self.preview_label.clear()
        self.preview_label.setText("No Preview")
        self.update_ui_state()

    def start_preview_generation(self, job_path):
        if not job_path or not os.path.exists(job_path): return
        
        # 이미 실행 중이면 예약만 하고 리턴
        if self.is_previewing():
            self.pending_preview_path = job_path
            self.pending_preview_id = self.last_job_id
            return

        self.ui_busy_preview = True
        self.pending_preview_path = None
        self.pending_preview_id = None
        
        try:
            self.preview_label.setText(self.t.get("msg_generating_preview", "Generating Preview..."))
            self.preview_worker = PreviewGeneratorWorker(job_path, self.last_job_id)
            self.preview_worker.preview_ready.connect(self.on_preview_success)
            self.preview_worker.preview_failed.connect(self.on_preview_failed)
            self.preview_worker.start()
            self.update_ui_state()
        except Exception as e:
            self.log_message(f"⚠️ Preview start failed: {e}")
            self.finish_preview_job()

    def on_preview_success(self, img_bytes, worker_job_id):
        try:
            if worker_job_id == self.last_job_id:
                self.set_preview_image(img_bytes)
        finally:
            self.finish_preview_job()

    def on_preview_failed(self, msg):
        try:
            self.preview_label.setText(self.t.get("msg_preview_failed", "Preview Failed"))
            self.log_message(f"⚠️ Preview error: {msg}")
        finally:
            self.finish_preview_job()

    def finish_preview_job(self):
        self.ui_busy_preview = False
        self.update_ui_state()

        p_path = self.pending_preview_path
        p_id = self.pending_preview_id
        self.pending_preview_path = None
        self.pending_preview_id = None

        if p_path and p_id == self.last_job_id:
            self.start_preview_generation(p_path)

    def check_clipboard(self):
        import win32clipboard
        try:
            win32clipboard.OpenClipboard()
            data = None
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()

            if data:
                try:
                    payload = json.loads(data)
                    if payload.get("signature") == "ase_ps_bridge_payload":
                        self.clipboard_empty_count = 0
                        job_id = payload.get("job_id")
                        source = payload.get("source_app", "unknown")
                        count = payload.get("summary", {}).get("layer_count", 0)

                        if job_id != self.last_job_id:
                            self.last_job_id = job_id
                            self.clipboard_source = source
                            self.clipboard_count = count
                            self.current_job_path = payload.get("job_path")

                            self.undo_stack.clear()
                            self.redo_stack.clear()
                            self.cur_h, self.cur_v, self.cur_angle = False, False, 0

                            if self.current_job_path and os.path.exists(self.current_job_path):
                                self.start_preview_generation(self.current_job_path)

                            self.update_ui_state()

                            if source == "photoshop":
                                msg = self.t["clip_ready"].format(src="PS", dst="Ase", count=count)
                                self.update_status(msg, "#dbeafe", "#1e40af")
                            elif source == "aseprite":
                                msg = self.t["clip_ready"].format(src="Ase", dst="PS", count=count)
                                self.update_status(msg, "#fef3c7", "#b45309")

                            self.log_message(self.t["msg_clip_update"].format(count=count))
                        return
                except: pass
        except Exception:
            pass

        if self.last_job_id is not None:
            self.clipboard_empty_count += 1
            path_missing = self.current_job_path and not os.path.exists(self.current_job_path)
            
            if self.clipboard_empty_count >= 5 or path_missing:
                self.last_job_id = None
                self.current_job_path = None
                self.clipboard_source = None
                self.clipboard_count = 0
                self.undo_stack.clear()
                self.redo_stack.clear()
                self.cur_h, self.cur_v, self.cur_angle = False, False, 0
                self.clipboard_empty_count = 0
                
                self.ui_busy_transform = False
                self.ui_busy_preview = False
                self.pending_preview_path = None
                self.pending_preview_id = None
                
                self.update_status(self.t["clip_empty"], "#f3f4f6", "#374151")
                self.clear_preview()
                self.log_message("Stale job state cleared.")

    def update_status(self, text, bg_color, text_color):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"padding: 10px; background-color: {bg_color}; color: {text_color}; border-radius: 5px; font-weight: bold;")

    # === 변환(Transform) 안정성 패치 영역 ===
    def handle_flip_h(self):
        if self.is_transforming() or not self.current_job_path: return
        self.undo_stack.append((self.cur_h, self.cur_v, self.cur_angle))
        self.redo_stack.clear()
        self.cur_h = not self.cur_h
        self.execute_worker()

    def handle_flip_v(self):
        if self.is_transforming() or not self.current_job_path: return
        self.undo_stack.append((self.cur_h, self.cur_v, self.cur_angle))
        self.redo_stack.clear()
        self.cur_v = not self.cur_v
        self.execute_worker()

    def handle_rotate(self):
        if self.is_transforming() or not self.current_job_path: return
        self.undo_stack.append((self.cur_h, self.cur_v, self.cur_angle))
        self.redo_stack.clear()
        self.cur_angle = (self.cur_angle + 90) % 360
        self.execute_worker()

    def handle_undo(self):
        if self.is_transforming() or not self.undo_stack: return
        self.redo_stack.append((self.cur_h, self.cur_v, self.cur_angle))
        self.cur_h, self.cur_v, self.cur_angle = self.undo_stack.pop()
        self.execute_worker()

    def handle_redo(self):
        if self.is_transforming() or not self.redo_stack: return
        self.undo_stack.append((self.cur_h, self.cur_v, self.cur_angle))
        self.cur_h, self.cur_v, self.cur_angle = self.redo_stack.pop()
        self.execute_worker()

    def execute_worker(self):
        if not self.current_job_path or not os.path.exists(self.current_job_path): return
        if self.is_transforming(): return

        self.ui_busy_transform = True
        self.update_ui_state()
        
        try:
            self.preview_label.setText(self.t.get("msg_transforming", "Transforming..."))

            self.transform_worker = JobTransformWorker(
                self.current_job_path, 
                self.cur_h, 
                self.cur_v, 
                self.cur_angle
            )
            self.transform_worker.transform_done.connect(self.on_transform_success)
            self.transform_worker.error.connect(self.on_transform_error)
            self.transform_worker.log.connect(self.log_message)
            self.transform_worker.start()
        except Exception as e:
            self.ui_busy_transform = False
            self.update_ui_state()
            self.log_message(f"❌ Transform start failed: {e}")

    def on_transform_success(self):
        """연속적인 Busy 상태 유지를 위해 순서 조정"""
        try:
            # 1. 프리뷰 생성을 먼저 시작 (ui_busy_preview가 True가 됨)
            if self.current_job_path:
                self.start_preview_generation(self.current_job_path)
            
            msg = self.t.get("msg_transform_success", "✅ Transform applied").format(
                h=self.cur_h, v=self.cur_v, a=self.cur_angle
            )
            self.log_message(msg)
        finally:
            # 2. 그 다음 트랜스폼 점유 해제
            self.ui_busy_transform = False
            
            # 3. 마지막으로 UI 갱신 (프리뷰 때문에 변환 버튼은 계속 비활성 유지됨)
            self.update_ui_state()

    def on_transform_error(self, msg):
        self.ui_busy_transform = False
        try:
            err_msg = self.t.get("msg_transform_fail", "❌ Transform failed").format(error=msg)
            self.log_message(err_msg)
            # 하드코딩 제거: 다국어 지원되는 msg_transform_failed 사용
            self.preview_label.setText(self.t.get("msg_transform_failed", "Transform Failed"))
        finally:
            self.update_ui_state()

    # === Actions ===
    def run_ps_copy(self):
        if self.is_transferring() or self.is_transforming(): return
        self.ui_busy_transfer = True
        self.update_ui_state()
        
        try:
            self.log_message(self.t["msg_ps_copying"])
            
            import uuid
            job_id = "bridge_job_" + time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
            
            self.ps_worker = PhotoshopCLIWorker(
                self.ps_copy_jsx, 
                self.settings.get("photoshop_exe"), 
                job_id, 
                self.temp_dir, 
                self.get_align_mode()
            )
            self.ps_worker.finished.connect(self.on_ps_copy_finished)
            self.ps_worker.log.connect(self.log_message)
            self.ps_worker.start()
        except Exception as e:
            self.ui_busy_transfer = False
            self.update_ui_state()
            self.log_message(f"❌ [PS Error] {e}")

    def on_ps_copy_finished(self, success, msg):
        self.ui_busy_transfer = False
        try:
            if not success:
                self.log_message(f"❌ [PS Error] {msg}")
        finally:
            self.update_ui_state()

    def run_ase_paste(self):
        if self.is_transferring() or self.is_transforming(): return
        self.ui_busy_transfer = True
        self.update_ui_state()
        
        try:
            self.log_message(self.t["msg_ase_pasting"])
            self.ase_worker = AsepriteWorker(self.settings.get("aseprite_exe"), self.ase_paste_lua_orig, trigger_hotkey=True)
            self.ase_worker.finished.connect(self.on_ase_paste_finished)
            self.ase_worker.error.connect(self.on_ase_paste_error)
            self.ase_worker.log.connect(self.log_message)
            self.ase_worker.start()
        except Exception as e:
            self.ui_busy_transfer = False
            self.update_ui_state()
            self.log_message(f"❌ [Ase Error] {e}\n{self.t.get('msg_ase_trust_err', '')}")

    def on_ase_paste_finished(self):
        self.ui_busy_transfer = False
        self.update_ui_state()
        
    def on_ase_paste_error(self, e):
        self.ui_busy_transfer = False
        try:
            self.log_message(f"❌ [Ase Error] {e}\n{self.t.get('msg_ase_trust_err', '')}")
        finally:
            self.update_ui_state()

    def run_ase_copy(self):
        if self.is_transferring() or self.is_transforming(): return
        self.ui_busy_transfer = True
        self.update_ui_state()
        
        try:
            self.log_message(self.t["msg_ase_copying"])
            self.ase_worker = AsepriteWorker(self.settings.get("aseprite_exe"), self.ase_copy_lua_orig, trigger_hotkey=True)
            self.ase_worker.finished.connect(self.on_ase_copy_finished)
            self.ase_worker.error.connect(self.on_ase_copy_error)
            self.ase_worker.log.connect(self.log_message)
            self.ase_worker.start()
        except Exception as e:
            self.ui_busy_transfer = False
            self.update_ui_state()
            self.log_message(f"❌ [Ase Error] {e}\n{self.t.get('msg_ase_trust_err', '')}")

    def on_ase_copy_finished(self):
        self.ui_busy_transfer = False
        self.update_ui_state()
        
    def on_ase_copy_error(self, e):
        self.ui_busy_transfer = False
        try:
            self.log_message(f"❌ [Ase Error] {e}\n{self.t.get('msg_ase_trust_err', '')}")
        finally:
            self.update_ui_state()

    def run_ps_paste(self):
        if self.is_transferring() or self.is_transforming(): return
        if not self.last_job_id:
            self.log_message(self.t["err_no_ase_clip"])
            return

        self.ui_busy_transfer = True
        self.update_ui_state()
        
        try:
            self.log_message(self.t["msg_ps_pasting"])

            self.ps_worker = PhotoshopCLIWorker(
                self.ps_paste_jsx, 
                self.settings.get("photoshop_exe"), 
                self.last_job_id, 
                self.temp_dir, 
                self.get_align_mode()
            )
            self.ps_worker.finished.connect(self.on_ps_paste_finished)
            self.ps_worker.log.connect(self.log_message)
            self.ps_worker.start()
        except Exception as e:
            self.ui_busy_transfer = False
            self.update_ui_state()
            self.log_message(f"❌ [PS Error] {e}")

    def on_ps_paste_finished(self, success, msg):
        self.ui_busy_transfer = False
        try:
            if success:
                self.log_message(self.t["msg_ps_success"])
            else:
                self.log_message(f"❌ [PS Error] {msg}")
        finally:
            self.update_ui_state()

    def closeEvent(self, event):
        """종료 시 실행 중인 워커 안전하게 종료"""
        if hasattr(self, "transform_worker") and self.transform_worker.isRunning():
            self.transform_worker.wait(1000)
        if hasattr(self, "preview_worker") and self.preview_worker.isRunning():
            self.preview_worker.wait(1000)
        super().closeEvent(event)

if __name__ == "__main__":
    # 윈도우 작업표시줄 아이콘 강제 적용 (Python 기본 아이콘 덮어쓰기)
    import ctypes
    myappid = 'southpawgames.bridgepro.1.1'
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except:
        pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # 앱 전체 기본 아이콘 설정 (Taskbar 및 모든 창)
    from PySide6.QtGui import QIcon
    if getattr(sys, 'frozen', False):
        icon_dir = sys._MEIPASS
    else:
        icon_dir = BASE_DIR
    icon_path = os.path.join(icon_dir, "bridge_icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = BridgeApp()
    window.show()
    sys.exit(app.exec())
