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

BASE_DIR = r"C:\Users\SOUTHPAW GAMES\Desktop\AI TS"
SETTINGS_FILE = os.path.join(BASE_DIR, "bridge_settings.json")

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
    return {}

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
    if not appdata: return False, "APPDATA 환경변수를 찾을 수 없습니다."

    ase_dir = os.path.join(appdata, "Aseprite")
    scripts_dir = os.path.join(ase_dir, "scripts")
    if not os.path.exists(scripts_dir): os.makedirs(scripts_dir)

    target_paste_lua = os.path.join(scripts_dir, "aseprite_paste.lua")
    target_copy_lua = os.path.join(scripts_dir, "aseprite_copy.lua")
    
    try:
        shutil.copy2(orig_paste_lua, target_paste_lua)
        shutil.copy2(orig_copy_lua, target_copy_lua)
    except Exception as e:
        return False, f"스크립트 복사 실패: {e}"

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
            return False, f"키보드 설정 파일 읽기 실패: {e}"

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
            return False, f"설정 파일 덮어쓰기 실패: {e}"
            
    return True, "F4, F5 단축키가 Aseprite에 정상 등록되었습니다."

# ==========================================
# Worker Threads
# ==========================================
class PhotoshopWorker(QThread):
    finished = Signal()
    error = Signal(str)
    log = Signal(str)

    def __init__(self, jsx_path, ps_exe_path):
        super().__init__()
        self.jsx_path = jsx_path
        self.ps_exe_path = ps_exe_path
        self.max_retries = 3
        self.retry_delay = 1.0

    def run(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
            
            # 1. 정밀 제어 모드 (COM Strategy) 시도
            self.log.emit("🔄 포토샵과 통신 중...")
            com_success, com_error_msg = self._try_com_strategy()
            
            if com_success:
                self.log.emit("✅ 포토샵에서 스크립트를 성공적으로 실행했습니다.")
                self.finished.emit()
                return

            # 2. COM 실패 시 안전 우회 모드 (CLI Fallback Strategy) 시도
            if "UAC" in com_error_msg or "권한" in com_error_msg:
                self.log.emit(f"⚠️ 포토샵 권한 충돌 감지됨. 안전 우회 모드로 연결을 시도합니다... (사유: {com_error_msg})")
            else:
                self.log.emit(f"⚠️ 포토샵 응답 지연. 안전 우회 모드로 연결을 시도합니다... (사유: {com_error_msg})")
                
            cli_success, cli_error_msg = self._try_cli_fallback_strategy()
            
            if cli_success:
                self.log.emit("✅ 안전 우회 모드를 통해 스크립트를 성공적으로 실행했습니다.")
                self.finished.emit()
            else:
                raise Exception(f"포토샵이 실행 중이지 않거나 응답하지 않습니다.\n포토샵을 다시 켜주세요. (상세: {cli_error_msg})")

        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                pythoncom.CoUninitialize()
            except:
                pass

    def _try_com_strategy(self):
        """COM을 통한 정밀 제어 전략 (재시도 로직 포함)"""
        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                ps_app = win32com.client.GetActiveObject("Photoshop.Application")
                ps_app.DoJavaScriptFile(self.jsx_path)
                return True, "Success"
            except Exception as e:
                last_error = str(e)
                # 권한 거부(UAC) 에러면 재시도 없이 즉시 CLI로 넘기기 위해 루프 탈출
                if "-2146959355" in last_error or "CO_E_SERVER_EXEC_FAILURE" in last_error:
                    return False, "관리자 권한 충돌(UAC)"
                
                # 포토샵이 바쁜 상태(팝업창 등)라면 기다렸다가 재시도
                if "Call was rejected by callee" in last_error or "-2147418111" in last_error:
                    self.log.emit(f"⏳ 포토샵이 다른 작업 중입니다. 대기 후 재시도... ({attempt}/{self.max_retries})")
                    time.sleep(self.retry_delay)
                else:
                    time.sleep(self.retry_delay)
                    
        return False, "응답 시간 초과 및 알 수 없는 에러"

    def _try_cli_fallback_strategy(self):
        """권한 충돌 시 우회하는 CLI 백도어 전략"""
        try:
            if not self.ps_exe_path or not os.path.exists(self.ps_exe_path):
                import subprocess
                cmd = 'powershell.exe -NoProfile -Command "(Get-Process Photoshop -ErrorAction SilentlyContinue).Path | Select-Object -First 1"'
                result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                self.ps_exe_path = result.stdout.strip()

            if not self.ps_exe_path or not os.path.exists(self.ps_exe_path):
                return False, "포토샵 프로세스를 찾을 수 없습니다."

            import subprocess
            result = subprocess.run([self.ps_exe_path, self.jsx_path], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            
            # Photoshop CLI는 기존 인스턴스에 스크립트만 전달하고 비정상 코드로 종료될 수 있으므로, 
            # 에러 메시지(stderr)가 비어있다면 성공한 것으로 간주합니다.
            if result.stderr and result.stderr.strip():
                return False, f"CLI 실행 에러: {result.stderr}"
            else:
                return True, "Success"
        except Exception as e:
            return False, f"시스템 에러: {str(e)}"

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
                    raise Exception("Aseprite가 실행 중이 아닙니다. Aseprite를 먼저 켜주세요.")

                # 창이 작업표시줄로 최소화(Iconic)되어 있을 때만 RESTORE(창 복구) 호출.
                # 무조건 RESTORE를 호출하면 전체화면(Maximized) 모드가 작은 창모드로 풀려버리는 윈도우 버그 방지.
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    
                # 최상단으로 끌어올림
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.1)

                import win32com.client
                shell = win32com.client.Dispatch("WScript.Shell")
                hotkey = "{F5}" if "copy" in (self.lua_path or "") else "{F4}"
                shell.SendKeys(hotkey)
                self.log.emit(f"Aseprite 활성화 및 단축키({hotkey}) 전송 완료.")
            else:
                import subprocess
                cmd = f'start "" "{self.ase_exe}" --script "{self.lua_path}"'
                subprocess.run(cmd, shell=True)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

# ==========================================
# Settings Dialog
# ==========================================
class SettingsDialog(QDialog):
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Bridge Settings")
        self.setFixedSize(450, 300)
        self.current_settings = current_settings
        
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        
        # Photoshop 경로
        self.ps_path_input = QLineEdit(self.current_settings.get("photoshop_exe", ""))
        ps_btn = QPushButton("찾기")
        ps_btn.clicked.connect(lambda: self.browse_exe(self.ps_path_input))
        ps_layout = QHBoxLayout()
        ps_layout.addWidget(self.ps_path_input)
        ps_layout.addWidget(ps_btn)
        form_layout.addRow("Photoshop 경로:", ps_layout)
        
        # Aseprite 경로
        self.ase_path_input = QLineEdit(self.current_settings.get("aseprite_exe", ""))
        ase_btn = QPushButton("찾기")
        ase_btn.clicked.connect(lambda: self.browse_exe(self.ase_path_input))
        ase_layout = QHBoxLayout()
        ase_layout.addWidget(self.ase_path_input)
        ase_layout.addWidget(ase_btn)
        form_layout.addRow("Aseprite 경로:", ase_layout)
        
        # Alignment 기본값
        self.align_combo = QButtonGroup(self)
        align_hlayout = QHBoxLayout()
        self.rb_center = QRadioButton("Center (중앙)")
        self.rb_absolute = QRadioButton("Absolute (절대 좌표)")
        self.align_combo.addButton(self.rb_center, 1)
        self.align_combo.addButton(self.rb_absolute, 2)
        
        if self.current_settings.get("default_alignment", "center") == "absolute":
            self.rb_absolute.setChecked(True)
        else:
            self.rb_center.setChecked(True)
            
        align_hlayout.addWidget(self.rb_center)
        align_hlayout.addWidget(self.rb_absolute)
        form_layout.addRow("기본 정렬 모드:", align_hlayout)
        
        layout.addLayout(form_layout)
        
        # 단축키 상태 표시
        self.hotkey_status = QLabel(self.current_settings.get("hotkey_status", "확인 안 됨"))
        self.hotkey_status.setStyleSheet("color: #059669; font-weight: bold;")
        layout.addWidget(QLabel("<b>Aseprite 단축키 상태:</b>"))
        layout.addWidget(self.hotkey_status)

        # 재설정 버튼
        btn_reconfigure = QPushButton("Aseprite 스크립트/단축키 강제 재설치")
        btn_reconfigure.clicked.connect(self.force_reconfigure)
        layout.addWidget(btn_reconfigure)
        
        # 확인/취소
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def browse_exe(self, line_edit):
        path, _ = QFileDialog.getOpenFileName(self, "실행 파일 선택", "C:\\", "Executables (*.exe)")
        if path:
            line_edit.setText(path)

    def force_reconfigure(self):
        ase_paste_lua_orig = os.path.join(BASE_DIR, "scripts", "aseprite_paste.lua")
        ase_copy_lua_orig = os.path.join(BASE_DIR, "scripts", "aseprite_copy.lua")
        success, msg = setup_aseprite_environment(ase_paste_lua_orig, ase_copy_lua_orig)
        if success:
            QMessageBox.information(self, "성공", msg)
            self.hotkey_status.setText("✅ 정상 (F4=Paste, F5=Copy)")
        else:
            QMessageBox.critical(self, "실패", msg)
            self.hotkey_status.setText(f"❌ 실패: {msg}")

    def get_settings(self):
        return {
            "photoshop_exe": self.ps_path_input.text(),
            "aseprite_exe": self.ase_path_input.text(),
            "default_alignment": "center" if self.rb_center.isChecked() else "absolute",
            "hotkey_status": self.hotkey_status.text()
        }

# ==========================================
# Main UI Window
# ==========================================
class BridgeApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ase-PS Bridge Pro")
        self.setFixedSize(320, 550)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Window)

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
        self.init_environment()

        self.init_ui()
        self.init_timers()
        self.log_message("🚀 Bridge Pro 양방향 UI Started.")

    def init_environment(self):
        updated = False
        
        if not self.settings.get("photoshop_exe"):
            self.settings["photoshop_exe"] = find_photoshop_exe()
            updated = True
            
        if not self.settings.get("aseprite_exe"):
            self.settings["aseprite_exe"] = find_aseprite_exe()
            updated = True

        if not self.settings.get("hotkey_status") or "실패" in self.settings.get("hotkey_status", ""):
            success, msg = setup_aseprite_environment(self.ase_paste_lua_orig, self.ase_copy_lua_orig)
            self.settings["hotkey_status"] = "✅ 정상 (F4=Paste, F5=Copy)" if success else f"❌ 실패: {msg}"
            updated = True

        if not self.settings.get("default_alignment"):
            self.settings["default_alignment"] = "center"
            updated = True

        if updated:
            save_settings(self.settings)

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # 상단 상태바 및 세팅 버튼
        top_layout = QHBoxLayout()
        self.status_label = QLabel("📋 Clipboard: Empty")
        self.status_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("padding: 10px; background-color: #f0f0f0; border-radius: 5px;")
        
        btn_settings = QPushButton("⚙️")
        btn_settings.setFixedSize(35, 35)
        btn_settings.clicked.connect(self.open_settings)
        
        top_layout.addWidget(self.status_label, stretch=1)
        top_layout.addWidget(btn_settings)
        layout.addLayout(top_layout)

        # 정렬 모드
        align_layout = QHBoxLayout()
        self.radio_center = QRadioButton("Center (중앙 정렬)")
        self.radio_absolute = QRadioButton("Absolute (절대 좌표)")
        
        if self.settings.get("default_alignment") == "absolute":
            self.radio_absolute.setChecked(True)
        else:
            self.radio_center.setChecked(True)
            
        self.align_group = QButtonGroup()
        self.align_group.addButton(self.radio_center, 1)
        self.align_group.addButton(self.radio_absolute, 2)
        
        align_layout.addWidget(QLabel("Alignment:"))
        align_layout.addWidget(self.radio_center)
        align_layout.addWidget(self.radio_absolute)
        layout.addLayout(align_layout)

        # === 정방향 ===
        self.btn_ps_copy = QPushButton("1. Photoshop에서 Copy")
        self.btn_ps_copy.setMinimumHeight(40)
        self.btn_ps_copy.setStyleSheet("background-color: #3b82f6; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_ps_copy.clicked.connect(self.run_ps_copy)
        layout.addWidget(self.btn_ps_copy)

        self.btn_ase_paste = QPushButton("2. Aseprite로 Paste (F4)")
        self.btn_ase_paste.setMinimumHeight(40)
        self.btn_ase_paste.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_ase_paste.setEnabled(False)
        self.btn_ase_paste.clicked.connect(self.run_ase_paste)
        layout.addWidget(self.btn_ase_paste)

        # === 역방향 ===
        self.btn_ase_copy = QPushButton("3. Aseprite에서 Copy (F5)")
        self.btn_ase_copy.setMinimumHeight(40)
        self.btn_ase_copy.setStyleSheet("background-color: #f59e0b; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_ase_copy.clicked.connect(self.run_ase_copy)
        layout.addWidget(self.btn_ase_copy)

        self.btn_ps_paste = QPushButton("4. Photoshop으로 Paste")
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

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.get_settings()
            save_settings(self.settings)
            
            if self.settings.get("default_alignment") == "absolute":
                self.radio_absolute.setChecked(True)
            else:
                self.radio_center.setChecked(True)
                
            self.log_message("✅ 설정이 저장되었습니다.")

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
                        self.log_message(f"Payload 에러: {parse_err}")
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
                            self.update_status(f"📋 PS -> Ase ({count} Layers)", "#dbeafe", "#1e40af")
                            self.btn_ase_paste.setEnabled(True)
                            self.btn_ps_paste.setEnabled(False)
                        elif source == "aseprite":
                            self.update_status(f"📋 Ase -> PS ({count} Layers)", "#fef3c7", "#b45309")
                            self.btn_ps_paste.setEnabled(True)
                            self.btn_ase_paste.setEnabled(False)
                            
                        self.log_message(f"클립보드 갱신: {source}에서 {count}개 레이어 준비.")
                    return
        except Exception:
            pass
            
        if self.last_job_id is not None:
            self.last_job_id = None
            self.clipboard_source = None
            self.update_status("📋 Clipboard: Empty", "#f3f4f6", "#374151")
            self.btn_ase_paste.setEnabled(False)
            self.btn_ps_paste.setEnabled(False)

    def update_status(self, text, bg_color, text_color):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"padding: 10px; background-color: {bg_color}; color: {text_color}; border-radius: 5px; font-weight: bold;")

    # === Actions ===
    def run_ps_copy(self):
        self.btn_ps_copy.setEnabled(False)
        self.log_message("PS: 추출 중...")
        self.ps_worker = PhotoshopWorker(self.ps_copy_jsx, self.settings.get("photoshop_exe"))
        self.ps_worker.finished.connect(lambda: self.btn_ps_copy.setEnabled(True))
        self.ps_worker.error.connect(lambda e: (self.btn_ps_copy.setEnabled(True), self.log_message(f"❌ [PS Error] {e}")))
        self.ps_worker.log.connect(self.log_message)
        self.ps_worker.start()

    def run_ase_paste(self):
        self.btn_ase_paste.setEnabled(False)
        self.log_message("Aseprite: 붙여넣기 중...")
        self.ase_worker = AsepriteWorker(self.settings.get("aseprite_exe"), self.ase_paste_lua_orig, trigger_hotkey=True)
        self.ase_worker.finished.connect(lambda: self.btn_ase_paste.setEnabled(True))
        self.ase_worker.error.connect(lambda e: (self.btn_ase_paste.setEnabled(True), self.log_message(f"❌ [Ase Error] {e}")))
        self.ase_worker.log.connect(self.log_message)
        self.ase_worker.start()

    def run_ase_copy(self):
        self.btn_ase_copy.setEnabled(False)
        self.log_message("Aseprite: 추출 중...")
        self.ase_worker = AsepriteWorker(self.settings.get("aseprite_exe"), self.ase_copy_lua_orig, trigger_hotkey=True)
        self.ase_worker.finished.connect(lambda: self.btn_ase_copy.setEnabled(True))
        self.ase_worker.error.connect(lambda e: (self.btn_ase_copy.setEnabled(True), self.log_message(f"❌ [Ase Error] {e}")))
        self.ase_worker.log.connect(self.log_message)
        self.ase_worker.start()

    def run_ps_paste(self):
        self.btn_ps_paste.setEnabled(False)
        self.log_message("PS: 레이어 조립 중...")
        self.ps_worker = PhotoshopWorker(self.ps_paste_jsx, self.settings.get("photoshop_exe"))
        self.ps_worker.finished.connect(lambda: self.btn_ps_paste.setEnabled(True))
        self.ps_worker.error.connect(lambda e: (self.btn_ps_paste.setEnabled(True), self.log_message(f"❌ [PS Error] {e}")))
        self.ps_worker.log.connect(self.log_message)
        self.ps_worker.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = BridgeApp()
    window.show()
    sys.exit(app.exec())
