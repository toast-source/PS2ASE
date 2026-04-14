# Ase-PS Bridge Pro - Development Context (For AI Agents)

이 파일은 새로운 CLI 터미널이나 AI 세션이 시작될 때, 프로젝트의 현재 아키텍처와 기술적 결정 사항들을 즉시 파악하고 이어서 작업할 수 있도록 작성된 **핵심 컨텍스트 문서**입니다.

## 1. 프로젝트 개요 (Project Overview)
*   **목표**: Photoshop과 Aseprite 간의 무손실 양방향 다중 레이어 전송 (Copy & Paste) 브릿지 도구.
*   **핵심 철학**: 무거운 픽셀 데이터를 클립보드에 넣지 않고, 로컬 임시 폴더(`temp/`)와 가벼운 JSON 페이로드(`clipboard`)를 조합하여 전송 속도와 안정성을 극대화합니다.
*   **UI 컨트롤러**: `PySide6`를 사용한 플로팅 윈도우. 사용자가 스크립트를 직접 실행하지 않고 UI 버튼으로 양쪽 그래픽 툴을 원격 제어합니다.

## 2. 아키텍처 및 통신 구조 (Architecture & IPC)
프로그램은 3개의 주요 언어 환경으로 분리되어 동작합니다.

1.  **Python (마스터 컨트롤러 - `bridge_ui.py`)**
    *   **UI Thread**: PySide6 기반, 상태 표시 및 설정 관리(`bridge_settings.json`).
    *   **Worker Threads (`PhotoshopWorker`, `AsepriteWorker`)**: UI 멈춤 방지.
    *   **IPC (to Photoshop)**: `win32com`을 이용한 COM 제어 (`DoJavaScriptFile`). COM 연결 실패(UAC 충돌 등) 시, PowerShell로 `Photoshop.exe` 경로를 찾아 CLI 인자로 스크립트를 밀어넣는 **Fallback Strategy** 구현됨.
    *   **IPC (to Aseprite)**: Aseprite는 CLI로 스크립트 실행 시 새 창이 열리는 치명적 버그가 있음. 이를 우회하기 위해 `win32gui`로 켜져 있는 창 포커스를 잡고 `WScript.Shell`로 단축키(`F4`, `F5`)를 전송하는 **Hotkey Simulation** 방식 채택.
    *   **Daemon (QTimer)**: 1초마다 OS 클립보드와 `temp/` 폴더를 모니터링하여, PS/Ase 내부 단축키로 복사된 작업도 감지하여 클립보드에 JSON Payload를 주입함. 1시간 경과된 Temp 폴더 자동 Cleanup 지원.

2.  **Photoshop (ExtendScript / JSX - `scripts/`)**
    *   **Copy (`photoshop_copy.jsx`)**: 다중 레이어 추출 시 인덱스 꼬임 방지를 위해 선택된 레이어만 **새 임시 캔버스로 통째로 복제(`duplicate`)한 후 추출(Top->Bottom 배열을 Bottom->Top으로 역순 처리)**.
    *   **Paste (`photoshop_paste.jsx`)**: 크기 왜곡(Scale)을 막기 위해 `Place` 명령어를 절대 쓰지 않음. **PNG를 `app.open()` 후 메인 캔버스로 `duplicate()`** 해오는 방식 사용. (삽입 초기 좌표가 무조건 0,0 임을 보장).

3.  **Aseprite (Lua - `scripts/`)**
    *   **Copy (`aseprite_copy.lua`)**: 캔버스 밖 영역 유실 방지를 위해, `cel.bounds` 크기와 동일한 새 `Image()` 객체를 메모리에 만들고 `drawImage`로 원본을 수동 크롭하여 1:1 픽셀 매핑 저장.
    *   **Paste (`aseprite_paste.lua`)**: 특수문자 파싱 에러 방지를 위해 내장 `json` 모듈 우선 사용. 기존 레이어 개수가 부족하면 에러 없이 **`spr:newLayer()`를 자동 호출하여 Fallback 생성**.

## 3. 페이로드 및 데이터 스키마 (Payload & Schema)
OS 텍스트 클립보드에 주입되는 브릿지 통신 규격.

```json
{
  "signature": "ase_ps_bridge_payload",
  "version": "1.0",
  "job_id": "bridge_job_20260410_...",
  "source_app": "photoshop", // or "aseprite"
  "target_app": "aseprite",  // or "photoshop"
  "job_path": "C:/Users/.../temp/bridge_job_...",
  "settings": {
    "align_mode": "center" // or "absolute"
  },
  "summary": { "layer_count": 5, "document_name": "..." }
}
```

*   실제 레이어 구조 및 좌표 정보는 `job_path` 내부의 `metadata.json`에 저장됨.
*   **Opacity 정규화**: Aseprite(0~255)와 Photoshop(0~100) 간의 차이를 막기 위해, `metadata.json`의 opacity 값은 **무조건 백분율(0~100) 표준**으로 기록됨.

## 4. 정렬 정책 (Alignment Policy)
*   **Center Mode (기본)**: 양쪽 툴의 캔버스 크기가 달라도, 추출된 픽셀 조각들의 Bounding Box 전체 크기를 구하여 대상 캔버스의 **정중앙**에 배치. 상대적 위치 100% 보존.
*   **Absolute Mode**: 보정 오프셋 없이 원본 X, Y 절대 좌표에 그대로 꽂아넣음. 캔버스 사이즈가 동일할 때 사용.

## 5. 자동화 세팅 (Zero-Configuration)
*   `bridge_ui.py` 실행 시 레지스트리를 훑어 `Photoshop.exe`, `aseprite.exe` 경로를 자동 탐지.
*   Aseprite의 `AppData/Roaming/Aseprite/user.aseprite-keys` XML 파일을 직접 파싱하여 `F4(Paste)`, `F5(Copy)` 단축키를 자동으로 강제 매핑함. (사용자 수동 설정 최소화)

## 6. 디렉토리 구조 (Directory Structure)
*   `/bridge_ui.py` : 메인 실행 파일 (PyInstaller 빌드 대상)
*   `/scripts/` : PS 및 Aseprite 동작 스크립트 (빌드/배포 시 동봉 필요)
*   `/temp/` : 임시 작업(Job) PNG 및 JSON 파일 폴더 (동적 생성)
*   `/logs/` : 시스템 로그 파일 (디버깅용)
*   `/bridge_settings.json` : UI 사용자 설정 저장 (경로, 정렬 모드 등)

## 💡 이어서 개발할 때의 가이드 (Next Steps / Maintenance)
이 문서를 읽는 AI 요원은 위 아키텍처 규약을 절대적으로 준수해야 합니다.
1. UI를 수정할 때는 `PySide6` 스레드 안전성(QThread, Signal/Slot)을 유지하세요.
2. COM 연결 실패 처리, Aseprite 새 창 열림 버그 등 이미 해결된 트러블슈팅(Fallback) 로직을 손상시키지 마세요.
3. 스크립트 수정 시, 정방향/역방향 통신의 대칭성(Symmetry)이 깨지지 않는지 반드시 확인하세요.
