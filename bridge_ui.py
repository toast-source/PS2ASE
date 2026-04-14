import sys
import os
import json
import subprocess
import time
import shutil
import winreg
import xml.etree.ElementTree as ET
from PySide6.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, 
                               QWidget, QTextEdit, QLabel, QRadioButton, QButtonGroup, 
                               QHBoxLayout, QMessageBox, QFileDialog, QDialog, QLineEdit, QFormLayout, QDialogButtonBox)
from PySide6.QtCore import QTimer, QThread, Signal, Qt
from PySide6.QtGui import QFont, QColor
import win32com.client
import pythoncom

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
        "msg_ase_setup_success": "✅ Aseprite 스크립트/단축키(F4/F5) 맵핑 완료!",
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
        "err_no_ase_clip": "❌ [Error] 클립보드에 Aseprite 데이터가 없습니다.",
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
                       "<b>🔥 꿀팁 (Overwriting)</b><br>"
                       "Aseprite에서 일반 레이어만 복사해왔을 때, 캔버스에 있는 기존 레이어를 선택하고 붙여넣으면 새 레이어를 만들지 않고 <b>원래 이름 그대로 픽셀만 덮어씌워줍니다!</b>"
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
        "msg_started": "🚀 Bridge Pro Bi-directional UI Started.",
        "msg_detecting": "Auto-detecting paths...",
        "msg_detect_fail": "❌ Failed to detect essential executable paths.",
        "msg_detect_success": "✅ Auto-detection of program paths completed!",
        "msg_ase_setup_success": "✅ Aseprite scripts & hotkeys (F4/F5) mapped successfully!",
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
        "err_no_ase_clip": "❌ [Error] No Aseprite data in clipboard.",
        "set_title": "⚙️ Bridge Settings",
        "set_ps_path": "Photoshop Path:",
        "set_ase_path": "Aseprite Path:",
        "set_find": "Browse",
        "set_align": "Default Alignment:",
        "set_lang": "Language (언어):",
        "set_hotkey": "Aseprite Hotkey Status:",
        "set_force_reinstall": "Force Reinstall Aseprite Scripts/Hotkeys",
        "btn_tutorial": "❓ Tutorial",
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
                       "<b>🔥 Overwriting Tip</b><br>"
                       "When pasting into Aseprite without folders, the tool will <b>intelligently overwrite</b> existing layers instead of creating new ones!"
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
    return {"language": "ko"} # 기본값 한국어

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
    
    try:
        shutil.copy2(orig_paste_lua, target_paste_lua)
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
        self.lang_combo.addButton(self.rb_ko, 1)
        self.lang_combo.addButton(self.rb_en, 2)
        
        if self.current_settings.get("language", "ko") == "en":
            self.rb_en.setChecked(True)
        else:
            self.rb_ko.setChecked(True)
            
        lang_hlayout.addWidget(self.rb_ko)
        lang_hlayout.addWidget(self.rb_en)
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
        return {
            "photoshop_exe": self.ps_path_input.text(),
            "aseprite_exe": self.ase_path_input.text(),
            "default_alignment": "center" if self.rb_center.isChecked() else "absolute",
            "language": "en" if self.rb_en.isChecked() else "ko",
            "hotkey_status": self.hotkey_status.text()
        }

# ==========================================
# Tutorial Dialog
# ==========================================
class TutorialDialog(QDialog):
    def __init__(self, lang_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(lang_dict["tut_title"])
        self.setMinimumSize(400, 350)
        
        layout = QVBoxLayout(self)
        
        content_label = QLabel(lang_dict["tut_content"])
        content_label.setWordWrap(True)
        content_label.setStyleSheet("font-size: 13px; line-height: 1.5;")
        layout.addWidget(content_label)
        
        btn_close = QPushButton("OK")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignCenter)

# ==========================================
# Main UI Window
# ==========================================
class BridgeApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 윈도우 작업표시줄 아이콘 강제 적용 (Python 기본 아이콘 덮어쓰기)
        import ctypes
        myappid = 'southpawgames.bridgepro.1.1'
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except:
            pass

        self.setMinimumSize(380, 580)
        self.resize(380, 580)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Window)
        
        # 앱 아이콘 설정 (빌드된 .exe 파일 내부에서 아이콘 추출)
        from PySide6.QtGui import QIcon
        if getattr(sys, 'frozen', False):
            icon_dir = sys._MEIPASS # PyInstaller 임시 압축해제 폴더
        else:
            icon_dir = BASE_DIR
        icon_path = os.path.join(icon_dir, "bridge_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 경로 캐싱
        self.ps_copy_jsx = os.path.join(BASE_DIR, "scripts", "photoshop_copy.jsx")
        self.ps_paste_jsx = os.path.join(BASE_DIR, "scripts", "photoshop_paste.jsx")
        self.ase_copy_lua_orig = os.path.join(BASE_DIR, "scripts", "aseprite_copy.lua")
        self.ase_paste_lua_orig = os.path.join(BASE_DIR, "scripts", "aseprite_paste.lua")
        self.temp_dir = os.path.join(BASE_DIR, "temp")
        
        self.last_job_id = None
        self.clipboard_source = None 
        self.processed_jobs = set()
        
        # 설정 불러오기 및 초기화
        self.settings = load_settings()
        self.current_lang = self.settings.get("language", "ko")
        self.t = LANG[self.current_lang]
        
        self.setWindowTitle(self.t["title"])
        self.init_environment()

        self.init_ui()
        self.init_timers()
        self.log_message(self.t["msg_started"])

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
            self.settings["language"] = "ko"
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
        
        btn_clean = QPushButton(self.t["btn_clean"])
        btn_clean.setStyleSheet("background-color: #ef4444; color: white; border-radius: 4px; padding: 5px;")
        btn_clean.clicked.connect(self.clean_temp_folder)
        
        settings_tut_layout = QHBoxLayout()
        btn_tutorial = QPushButton(self.t["btn_tutorial"])
        btn_tutorial.clicked.connect(self.show_tutorial)
        
        btn_settings = QPushButton(self.t["btn_settings"])
        btn_settings.clicked.connect(self.open_settings)
        
        settings_tut_layout.addWidget(btn_tutorial)
        settings_tut_layout.addWidget(btn_settings)
        
        btn_layout.addWidget(btn_clean)
        btn_layout.addLayout(settings_tut_layout)
        
        top_layout.addWidget(self.status_label, stretch=1)
        top_layout.addLayout(btn_layout)
        layout.addLayout(top_layout)

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
        if not self.last_job_id:
            self.update_status(self.t["clip_empty"], "#f3f4f6", "#374151")

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
            self.clipboard_source = None
            self.processed_jobs.clear()
            self.update_status(self.t["clip_empty"], "#f3f4f6", "#374151")
            self.btn_ase_paste.setEnabled(False)
            self.btn_ps_paste.setEnabled(False)
            
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

    def check_clipboard(self):
        import win32clipboard
        try:
            win32clipboard.OpenClipboard()
            data = None
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()

            if data:
                payload = json.loads(data)
                if payload.get("signature") == "ase_ps_bridge_payload":
                    job_id = payload.get("job_id")
                    source = payload.get("source_app", "unknown")
                    count = payload.get("summary", {}).get("layer_count", 0)
                    
                    if job_id != self.last_job_id:
                        self.last_job_id = job_id
                        self.clipboard_source = source
                        
                        if source == "photoshop":
                            msg = self.t["clip_ready"].format(src="PS", dst="Ase", count=count)
                            self.update_status(msg, "#dbeafe", "#1e40af")
                            self.btn_ase_paste.setEnabled(True)
                            self.btn_ps_paste.setEnabled(False)
                        elif source == "aseprite":
                            msg = self.t["clip_ready"].format(src="Ase", dst="PS", count=count)
                            self.update_status(msg, "#fef3c7", "#b45309")
                            self.btn_ps_paste.setEnabled(True)
                            self.btn_ase_paste.setEnabled(False)
                            
                        self.log_message(self.t["msg_clip_update"].format(count=count))
                    return
        except Exception:
            pass
            
        if self.last_job_id is not None:
            self.last_job_id = None
            self.clipboard_source = None
            self.update_status(self.t["clip_empty"], "#f3f4f6", "#374151")
            self.btn_ase_paste.setEnabled(False)
            self.btn_ps_paste.setEnabled(False)

    def update_status(self, text, bg_color, text_color):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"padding: 10px; background-color: {bg_color}; color: {text_color}; border-radius: 5px; font-weight: bold;")

    # === Actions ===
    def run_ps_copy(self):
        self.btn_ps_copy.setEnabled(False)
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

    def on_ps_copy_finished(self, success, msg):
        self.btn_ps_copy.setEnabled(True)
        if not success:
            self.log_message(f"❌ [PS Error] {msg}")

    def run_ase_paste(self):
        self.btn_ase_paste.setEnabled(False)
        self.log_message(self.t["msg_ase_pasting"])
        self.ase_worker = AsepriteWorker(self.settings.get("aseprite_exe"), self.ase_paste_lua_orig, trigger_hotkey=True)
        self.ase_worker.finished.connect(lambda: self.btn_ase_paste.setEnabled(True))
        self.ase_worker.error.connect(lambda e: (self.btn_ase_paste.setEnabled(True), self.log_message(f"❌ [Ase Error] {e}")))
        self.ase_worker.log.connect(self.log_message)
        self.ase_worker.start()

    def run_ase_copy(self):
        self.btn_ase_copy.setEnabled(False)
        self.log_message(self.t["msg_ase_copying"])
        self.ase_worker = AsepriteWorker(self.settings.get("aseprite_exe"), self.ase_copy_lua_orig, trigger_hotkey=True)
        self.ase_worker.finished.connect(lambda: self.btn_ase_copy.setEnabled(True))
        self.ase_worker.error.connect(lambda e: (self.btn_ase_copy.setEnabled(True), self.log_message(f"❌ [Ase Error] {e}")))
        self.ase_worker.log.connect(self.log_message)
        self.ase_worker.start()

    def run_ps_paste(self):
        self.btn_ps_paste.setEnabled(False)
        self.log_message(self.t["msg_ps_pasting"])
        
        if not self.last_job_id:
            self.log_message(self.t["err_no_ase_clip"])
            self.btn_ps_paste.setEnabled(True)
            return

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

    def on_ps_paste_finished(self, success, msg):
        self.btn_ps_paste.setEnabled(True)
        if success:
            self.log_message(self.t["msg_ps_success"])
        else:
            self.log_message(f"❌ [PS Error] {msg}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = BridgeApp()
    window.show()
    sys.exit(app.exec())
