"""원격 지원 공통 모듈 - AnyDesk 탐색/실행/ID 복사.

SetupWizard(초기 DB 연결 실패 시)와 SettingsTab(일반 사용 중) 양쪽에서 사용.
"""

import os
import subprocess
import webbrowser
from typing import Optional

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget


_ANYDESK_PATHS = [
    r"%ProgramFiles(x86)%\AnyDesk\AnyDesk.exe",
    r"%ProgramFiles%\AnyDesk\AnyDesk.exe",
    r"%LOCALAPPDATA%\AnyDesk\AnyDesk.exe",
    r"%APPDATA%\AnyDesk\AnyDesk.exe",
]

_DOWNLOAD_URL = "https://anydesk.com/ko/downloads"


def _find_anydesk() -> Optional[str]:
    for raw in _ANYDESK_PATHS:
        path = os.path.expandvars(raw)
        if os.path.exists(path):
            return path
    return None


def _get_anydesk_id(exe: str) -> str:
    try:
        result = subprocess.run(
            [exe, "--get-id"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def request_remote_support(parent: QWidget) -> tuple[bool, str]:
    """원격 지원 요청 흐름을 실행한다.

    반환: (성공 여부, AnyDesk ID 또는 상태 메시지)
    """
    exe = _find_anydesk()

    if not exe:
        reply = QMessageBox.question(
            parent, "AnyDesk 미설치",
            "원격 지원을 위해 AnyDesk가 필요합니다.\n"
            "다운로드 페이지를 열까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            webbrowser.open(_DOWNLOAD_URL)
        return False, "AnyDesk 미설치"

    try:
        subprocess.Popen([exe])
    except Exception as e:
        QMessageBox.warning(parent, "오류", f"AnyDesk 실행 실패: {e}")
        return False, "실행 실패"

    anydesk_id = _get_anydesk_id(exe)

    if anydesk_id:
        clipboard = QApplication.clipboard()
        clipboard.setText(anydesk_id)

        QMessageBox.information(
            parent, "원격 지원 준비 완료",
            f"AnyDesk ID: {anydesk_id}\n"
            f"(클립보드에 복사되었습니다)\n\n"
            f"카카오톡 오픈채팅방에 ID를 보내주세요.",
            QMessageBox.StandardButton.Ok,
        )
        return True, anydesk_id

    return True, "AnyDesk가 실행되었습니다. ID를 확인해주세요."
