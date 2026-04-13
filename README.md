# PS2ASE (Ase-PS Bridge Pro)

Photoshop과 Aseprite 간의 완벽한 **다중 레이어 복사/붙여넣기(Copy & Paste)**를 지원하는 브릿지 도구입니다. 
무거운 픽셀 데이터를 시스템 클립보드에 직접 욱여넣는 대신, 로컬 임시 폴더와 가벼운 JSON 페이로드(Payload)를 활용하여 오류 없이 빠르고 안전하게 레이어를 전송합니다.

## ✨ 주요 기능 (Features)

*   **완벽한 다중 레이어 전송**: Photoshop에서 1개든 100개든 선택된 레이어들의 순서와 투명도를 100% 보존하여 Aseprite로 가져옵니다.
*   **모양 훼손 방지 (Bounding Box 조립)**: 레이어별로 따로 노는 것이 아니라, 복사된 캐릭터 조각들의 전체 덩어리(Bounding Box)를 계산하여 Aseprite 캔버스 정중앙에 완벽한 비율로 안착시킵니다.
*   **지능형 덮어쓰기 (Smart Overwrite)**: Aseprite에 이미 존재하는 레이어들을 우선적으로 재사용(덮어쓰기)하여 타임라인을 지저분하게 만들지 않습니다. 덮어쓸 레이어가 모자랄 때만 필요한 개수만큼 자동으로 새 레이어를 생성합니다.
*   **PySide6 독립 UI 컨트롤러**: 단축키나 스크립트를 일일이 찾을 필요 없이, 화면에 항상 떠 있는 조그만 플로팅 UI 창에서 원클릭으로 양쪽 프로그램을 제어합니다.
*   **자동 용량 관리 (Auto Cleanup)**: 파이썬 백그라운드 데몬이 오래된 임시 파일(Temp Job)들을 스스로 청소하여 하드디스크 용량 누수를 완벽하게 차단합니다.

---

## 🛠️ 개발 과정 및 트러블슈팅 (Development Process)

이 프로젝트는 "어떻게 하면 사용자가 완벽한 복사/붙여넣기(UX)를 경험하게 할까?"라는 목표 아래 여러 치명적인 기술적 한계를 돌파하며 개발되었습니다.

### 1. Photoshop의 다중 레이어 인덱싱 꼬임 문제
*   **문제**: Photoshop의 Action Manager를 통해 선택된 레이어들의 인덱스를 추출하려 했으나, 배경 레이어나 그룹(폴더)의 유무, 버전에 따라 순서가 뒤죽박죽 섞여 캐릭터가 엉망으로 조립되는 문제가 있었습니다.
*   **해결**: 사용자가 선택한 레이어들만 모아서 **새로운 "투명한 임시 도화지(Document)"에 통째로 복제**한 뒤, 그곳에서 눈에 보이는 위-아래 순서 그대로 직관적으로 레이어를 추출하는 방식으로 전면 개편하여 100%의 무결성을 확보했습니다.

### 2. Aseprite 중앙 정렬 및 레이어 역순 매핑
*   **문제**: Photoshop은 위에서 아래로(Top -> Bottom) 레이어를 쌓지만, Aseprite는 1번 인덱스가 가장 아래(Bottom)를 향합니다. 또한 캔버스 크기가 다를 경우 붙여넣은 이미지가 화면 밖으로 날아가는 문제가 있었습니다.
*   **해결**: 추출된 픽셀들의 최소/최대 좌표(Min/Max X,Y)를 모두 순회하여 전체 콘텐츠의 Bounding Box를 구하고, 이를 Aseprite 캔버스의 중심 좌표(Offset)와 더해 중앙 정렬을 구현했습니다. 배열 순서 역시 스크립트 단에서 완벽하게 역순 매핑(Reverse Mapping)하도록 처리했습니다.

### 3. Aseprite 외부 제어 시 "새 창 열림" 문제
*   **문제**: Python(`subprocess`)에서 Aseprite CLI(`--script`)를 호출하면 기존에 작업 중이던 창에 덮어씌워지지 않고 무조건 "새로운 Aseprite 프로그램"이 팝업되는 고질적인 구조적 한계가 있었습니다.
*   **해결**: Python이 `win32gui`와 `win32com`을 사용하여 현재 켜져 있는 Aseprite 창을 화면 맨 앞으로 끌어온(Focus) 뒤, 키보드 단축키(`F4`)를 사람 대신 자동으로 눌러주는 **단축키 시뮬레이션(Hotkey Simulation)** 방식으로 완전히 우회하여 해결했습니다.

### 4. 권한(UAC) 충돌 및 COM 서버 오류
*   **문제**: Photoshop이 관리자 권한으로 실행 중일 때 일반 권한의 Python 데몬이 `win32com`으로 접근하면 `CO_E_SERVER_EXEC_FAILURE` 에러가 발생했습니다.
*   **해결**: COM 객체 획득 실패 시, 백그라운드 PowerShell을 통해 현재 켜져 있는 `Photoshop.exe`의 실제 경로를 추적해내고, 스크립트 경로를 CLI 인자로 강제 주입하는 **CLI Fallback 로직**을 도입하여 권한 충돌을 무력화했습니다.

---

## 🚀 설치 및 사용 방법 (How to Use)

### 1. 사전 준비 (Aseprite 단축키 설정)
Aseprite가 새 창으로 열리는 것을 방지하기 위한 필수 1회성 세팅입니다.
1. `scripts/aseprite_paste.lua` 파일을 Aseprite의 스크립트 폴더(`File -> Scripts -> Open Scripts Folder`)에 복사합니다.
2. Aseprite에서 **Edit -> Keyboard Shortcuts**로 이동합니다.
3. 좌측 탭에서 `Scripts`를 선택하고, `aseprite_paste` 항목에 단축키 **`F4`**를 지정합니다.

### 2. 실행
1. Python 환경이 준비된 상태에서 (필요 시 `pip install PySide6 pywin32`)
2. `python bridge_ui.py` 를 실행합니다.
3. 화면에 나타난 플로팅 UI 창을 통해 Photoshop과 Aseprite를 자유롭게 오가며 Copy & Paste를 즐기시면 됩니다!

---
*Developed as an internal tool by SOUTHPAW GAMES.*