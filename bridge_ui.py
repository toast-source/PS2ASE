import sys
import os
import json
import subprocess
import time
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QTextEdit, QLabel
from PySide6.QtCore import QTimer, QThread, Signal, Qt
from PySide6.QtGui import QFont, QColor
import win32com.client

# ==========================================
# Worker Threads (UI 멈춤 방지)
# ==========================================
class PhotoshopWorker(QThread):
    finished = Signal()
    error = Signal(str)
    log = Signal(str)

    def __init__(self, jsx_path):
        super().__init__()
        self.jsx_path = jsx_path

    def run(self):
        try:
            # win32com은 스레드마다 초기화 필요
            import pythoncom
            pythoncom.CoInitialize()
            
            ps_app = None
            try:
                # 이미 켜져있는 포토샵 인스턴스를 먼저 찾음 (권한 충돌 방지)
                ps_app = win32com.client.GetActiveObject("Photoshop.Application")
                ps_app.DoJavaScriptFile(self.jsx_path)
            except Exception as com_err:
                # COM 연결 실패 시 (관리자 권한 충돌 등: CO_E_SERVER_EXEC_FAILURE)
                # Fallback: 실행 중인 Photoshop 프로세스를 찾아 CLI로 스크립트를 전달합니다.
                self.log.emit("COM 연결 실패. CLI 방식으로 Fallback 시도 중...")
                
                try:
                    import subprocess
                    import re
                    # 실행 중인 Photoshop 프로세스 경로 찾기
                    cmd = 'powershell.exe -NoProfile -Command "(Get-Process Photoshop -ErrorAction SilentlyContinue).Path | Select-Object -First 1"'
                    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    ps_path = result.stdout.strip()
                    
                    if not ps_path or not os.path.exists(ps_path):
                        raise Exception("Photoshop이 실행 중이지 않거나 경로를 찾을 수 없습니다.")
                        
                    # 포토샵 실행 파일에 스크립트 경로를 인자로 넘겨 실행
                    subprocess.run([ps_path, self.jsx_path], creationflags=subprocess.CREATE_NO_WINDOW)
                except Exception as fallback_err:
                    raise Exception(f"포토샵 제어 실패 (권한 문제일 수 있습니다).\nCOM 에러: {com_err}\nCLI 에러: {fallback_err}")

            finally:
                pythoncom.CoUninitialize()
                
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

class AsepriteWorker(QThread):
    finished = Signal()
    error = Signal(str)
    log = Signal(str)

    def __init__(self, ase_exe, lua_path):
        super().__init__()
        self.ase_exe = ase_exe
        self.lua_path = lua_path

    def run(self):
        try:
            import win32gui
            import win32com.client
            import time

            # Aseprite 클래스명으로 실행 중인 창 찾기
            hwnd = win32gui.FindWindow("Aseprite", None)
            if hwnd == 0:
                # 윈도우 타이틀 패턴으로 다시 시도
                def callback(h, hwnds):
                    title = win32gui.GetWindowText(h)
                    if "Aseprite" in title:
                        hwnds.append(h)
                    return True
                hwnds = []
                win32gui.EnumWindows(callback, hwnds)
                if hwnds:
                    hwnd = hwnds[0]

            if hwnd == 0:
                raise Exception("Aseprite가 실행 중이 아닙니다. Aseprite를 먼저 켜주세요.")

            # 1. Aseprite 창을 최상단으로 활성화 (포커스 이동)
            import win32con
            # 최소화되어 있다면 복원
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            
            # 2. 약간의 딜레이 (창 전환 시간 보장)
            time.sleep(0.1)

            # 3. Aseprite에 단축키 전송 (예: F4)
            # 사용자는 Aseprite 내부에서 편집 -> 키보드 단축키 -> 스크립트 -> aseprite_paste.lua를 F4로 지정해야 함.
            shell = win32com.client.Dispatch("WScript.Shell")
            shell.SendKeys("{F4}")

            self.log.emit("Aseprite를 활성화하고 단축키(F4)를 전송했습니다.")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

# ==========================================
# Main UI Window
# ==========================================
class BridgeApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ase-PS Bridge Pro")
        self.setFixedSize(300, 400)
        
        # 윈도우 항상 위 속성 적용
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Window)

        # 설정 및 경로
        base_dir = r"C:\Users\SOUTHPAW GAMES\Desktop\AI TS"
        self.jsx_path = os.path.join(base_dir, "scripts", "photoshop_copy.jsx")
        self.lua_path = os.path.join(base_dir, "scripts", "aseprite_paste.lua")
        self.aseprite_exe = r"C:\Program Files (x86)\Steam\steamapps\common\Aseprite\aseprite.exe"
        self.temp_dir = os.path.join(base_dir, "temp")
        
        self.last_job_id = None
        self.clipboard_layers_count = 0

        self.init_ui()
        self.init_timers()
        self.processed_jobs = set()
        self.log_message("🚀 Bridge Pro UI Started.")

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # 상태 표시창
        self.status_label = QLabel("📋 Clipboard: Empty")
        self.status_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("padding: 10px; background-color: #f0f0f0; border-radius: 5px;")
        layout.addWidget(self.status_label)

        # Copy 버튼
        self.btn_copy = QPushButton("Photoshop에서 Copy")
        self.btn_copy.setMinimumHeight(45)
        self.btn_copy.setFont(QFont("Arial", 10))
        self.btn_copy.setStyleSheet("background-color: #3b82f6; color: white; border-radius: 5px;")
        self.btn_copy.clicked.connect(self.run_copy)
        layout.addWidget(self.btn_copy)

        # Paste 버튼
        self.btn_paste = QPushButton("Aseprite로 Paste")
        self.btn_paste.setMinimumHeight(45)
        self.btn_paste.setFont(QFont("Arial", 10))
        self.btn_paste.setStyleSheet("background-color: #10b981; color: white; border-radius: 5px;")
        self.btn_paste.setEnabled(False) # 클립보드에 데이터가 없으면 비활성화
        self.btn_paste.clicked.connect(self.run_paste)
        layout.addWidget(self.btn_paste)

        # 로그 콘솔
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setFont(QFont("Consolas", 9))
        self.log_console.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; padding: 5px;")
        layout.addWidget(self.log_console)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def init_timers(self):
        # 1초마다 OS 클립보드 및 temp 폴더를 감시하는 타이머
        self.clip_timer = QTimer(self)
        self.clip_timer.timeout.connect(self.check_clipboard)
        self.clip_timer.timeout.connect(self.check_temp_folder)
        self.clip_timer.start(1000)

    def log_message(self, message):
        time_str = time.strftime('%H:%M:%S')
        self.log_console.append(f"[{time_str}] {message}")
        # 스크롤 맨 아래로 이동
        self.log_console.verticalScrollBar().setValue(self.log_console.verticalScrollBar().maximum())

    def check_temp_folder(self):
        # 포토샵 내부에서 단축키로 복사했을 때나 UI 버튼으로 복사했을 때 모두 감지하여 클립보드에 주입
        try:
            if not os.path.exists(self.temp_dir):
                return
                
            for job_id in os.listdir(self.temp_dir):
                if job_id in self.processed_jobs:
                    continue
                    
                job_path = os.path.join(self.temp_dir, job_id)
                if not os.path.isdir(job_path):
                    continue
                    
                trigger_path = os.path.join(job_path, "trigger_copy.json")
                if os.path.exists(trigger_path):
                    # 파일 쓰기 완료 대기
                    time.sleep(0.1)
                    try:
                        with open(trigger_path, "r", encoding="utf-8") as f:
                            payload = json.load(f)
                            
                        import win32clipboard
                        payload_str = json.dumps(payload, ensure_ascii=False)
                        win32clipboard.OpenClipboard()
                        win32clipboard.EmptyClipboard()
                        win32clipboard.SetClipboardText(payload_str, win32clipboard.CF_UNICODETEXT)
                        win32clipboard.CloseClipboard()
                        
                        self.processed_jobs.add(job_id)
                        # 클립보드에 주입되면 check_clipboard에서 자연스럽게 상태를 업데이트함
                    except Exception as parse_err:
                        self.log_message(f"Payload 파싱/주입 에러: {parse_err}")
        except Exception:
            pass

    def check_clipboard(self):
        # 파이썬에서 win32clipboard를 이용해 페이로드 시그니처 감지
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
                    count = payload.get("summary", {}).get("layer_count", 0)
                    
                    if job_id != self.last_job_id:
                        self.last_job_id = job_id
                        self.clipboard_layers_count = count
                        self.update_status(f"📋 {count} Layers Ready", "#d1fae5", "#065f46")
                        self.btn_paste.setEnabled(True)
                        self.log_message(f"클립보드 감지: {count}개 레이어 준비됨.")
                    return
        except Exception:
            pass # 일반 텍스트이거나 JSON 파싱 에러 시 무시
            
        # 브릿지 데이터가 없는 경우
        if self.last_job_id is not None:
            self.last_job_id = None
            self.clipboard_layers_count = 0
            self.update_status("📋 Clipboard: Empty", "#f3f4f6", "#374151")
            self.btn_paste.setEnabled(False)

    def update_status(self, text, bg_color, text_color):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"padding: 10px; background-color: {bg_color}; color: {text_color}; border-radius: 5px; font-weight: bold;")

    # ==========================================
    # Actions
    # ==========================================
    def run_copy(self):
        self.btn_copy.setEnabled(False)
        self.btn_copy.setText("Extracting...")
        self.log_message("PS: 추출 스크립트 실행 중...")
        
        self.ps_worker = PhotoshopWorker(self.jsx_path)
        self.ps_worker.finished.connect(self.on_copy_finished)
        self.ps_worker.error.connect(self.on_copy_error)
        self.ps_worker.log.connect(self.log_message)
        self.ps_worker.start()

    def on_copy_finished(self):
        self.btn_copy.setEnabled(True)
        self.btn_copy.setText("Photoshop에서 Copy")
        self.log_message("PS: 성공적으로 내보냈습니다.")

    def on_copy_error(self, err_msg):
        self.btn_copy.setEnabled(True)
        self.btn_copy.setText("Photoshop에서 Copy")
        self.log_message(f"❌ [PS Error] {err_msg}")

    def run_paste(self):
        self.btn_paste.setEnabled(False)
        self.btn_paste.setText("Pasting...")
        self.log_message("Aseprite: 레이어 재구성 중...")
        
        self.ase_worker = AsepriteWorker(self.aseprite_exe, self.lua_path)
        self.ase_worker.finished.connect(self.on_paste_finished)
        self.ase_worker.error.connect(self.on_paste_error)
        self.ase_worker.start()

    def on_paste_finished(self):
        self.btn_paste.setEnabled(True)
        self.btn_paste.setText("Aseprite로 Paste")
        self.log_message("Aseprite: 완벽하게 붙여넣었습니다.")

    def on_paste_error(self, err_msg):
        self.btn_paste.setEnabled(True)
        self.btn_paste.setText("Aseprite로 Paste")
        self.log_message(f"❌ [Aseprite Error] {err_msg}")

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    
    # 윈도우 스타일 지정
    app.setStyle("Fusion")
    
    window = BridgeApp()
    window.show()
    sys.exit(app.exec())
