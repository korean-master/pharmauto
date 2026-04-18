"""자동 업데이트 모듈 - GitHub 릴리스 기반.

PyInstaller exe 빌드 대응:
1. GitHub API로 최신 릴리스 확인
2. PharmAutoSetup.exe 다운로드
3. 설치 프로그램 실행 (기존 파일 자동 덮어쓰기)
4. 앱 종료 → 설치 완료 후 자동 재실행
"""

import json
import os
import subprocess
import sys
import tempfile

import requests

from core.version import VERSION

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.json")

REPO = "korean-master/pharmauto"
INSTALLER_NAME = "PharmAutoSetup.exe"


def _parse_version(v: str) -> tuple[int, ...]:
    """'v1.2.3' or '1.2.3' → (1, 2, 3)"""
    v = v.lstrip("vV").strip()
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_update() -> dict | None:
    """GitHub 릴리스에서 최신 버전을 확인한다.

    Returns:
        {"version": "1.3.3", "download_url": "...", "notes": "..."} or None
    """
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    try:
        resp = requests.get(url, timeout=10,
                            headers={"Accept": "application/vnd.github.v3+json"})
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None

    tag = data.get("tag_name", "")
    if not tag:
        return None

    latest = _parse_version(tag)
    current = _parse_version(VERSION)

    if latest <= current:
        return None

    # PharmAutoSetup.exe 에셋 찾기
    download_url = ""
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.lower() == INSTALLER_NAME.lower():
            download_url = asset.get("browser_download_url", "")
            break

    if not download_url:
        return None

    return {
        "version": tag.lstrip("vV"),
        "download_url": download_url,
        "notes": data.get("body", "") or "",
    }


def download_and_apply(download_url: str, progress_callback=None,
                       expected_hash: str = "") -> bool:
    """설치파일을 다운로드하고, 앱 종료 후 설치를 실행한다.

    1. PharmAutoSetup.exe 다운로드
    2. 헬퍼 스크립트 생성 (앱 종료 대기 -> 설치 실행)
    3. 헬퍼 실행 -> 앱 종료 -> 파일 잠금 해제 후 설치 진행

    Returns:
        True if download successful (설치는 앱 종료 후 별도 프로세스)
    """
    def _progress(msg):
        print(f"[업데이트] {msg}")
        if progress_callback:
            progress_callback(msg)

    tmp_dir = tempfile.mkdtemp(prefix="pharmauto_update_")
    installer_path = os.path.join(tmp_dir, INSTALLER_NAME)

    try:
        # 다운로드
        _progress("다운로드 중...")
        resp = requests.get(download_url, stream=True, timeout=60)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        last_pct = -1

        with open(installer_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int(downloaded / total * 100)
                    if pct >= last_pct + 10 or pct == 100:
                        _progress(f"다운로드 중... {pct}%")
                        last_pct = pct

        _progress("다운로드 완료, 앱 종료 후 설치를 시작합니다...")

        # 헬퍼 배치 스크립트: 앱 종료 대기 -> 설치 실행
        helper_path = os.path.join(tmp_dir, "_update.bat")
        with open(helper_path, "w", encoding="mbcs") as f:
            f.write("@echo off\r\n")
            # PharmAuto.exe가 완전히 종료될 때까지 대기 (최대 30초)
            f.write(":wait_loop\r\n")
            f.write('tasklist /FI "IMAGENAME eq PharmAuto.exe" 2>nul '
                    '| find /I "PharmAuto.exe" >nul\r\n')
            f.write("if %ERRORLEVEL%==0 (\r\n")
            f.write("  timeout /t 2 /nobreak >nul\r\n")
            f.write("  goto wait_loop\r\n")
            f.write(")\r\n")
            # SILENT: 진행 UI 표시 (질문 없음, 취소 불가) — 사용자에게 피드백
            f.write(f'start /wait "" "{installer_path}" '
                    f"/SILENT /SUPPRESSMSGBOXES /NORESTART\r\n")
            # 설치 완료 후 앱 재시작 (콜드 스타트 대비 짧은 대기)
            app_dir = os.path.dirname(sys.executable)
            app_exe = os.path.join(app_dir, "PharmAuto.exe")
            f.write("timeout /t 1 /nobreak >nul\r\n")
            f.write(f'if exist "{app_exe}" start "" "{app_exe}"\r\n')

        # 헬퍼 실행 — 콘솔 창 표시하여 진행 상황 사용자에게 보여줌
        subprocess.Popen(
            ["cmd.exe", "/c", helper_path],
            cwd=tmp_dir,
        )

        return True

    except Exception as e:
        _progress(f"업데이트 실패: {e}")
        return False


def restart_app():
    """앱을 재시작한다."""
    if not sys.executable.endswith(("python.exe", "python3.exe", "python")):
        subprocess.Popen([sys.executable], cwd=os.path.dirname(sys.executable))
    else:
        python = sys.executable
        main_py = os.path.join(
            os.path.dirname(__file__), "..", "main.py"
        )
        subprocess.Popen([python, main_py])
    sys.exit(0)
