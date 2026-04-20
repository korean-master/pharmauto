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

from core import paths
from core.version import VERSION

REPO = "korean-master/pharmauto"
INSTALLER_NAME = "PharmAutoSetup.exe"
DELTA_EXE_NAME = "PharmAuto.exe"


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

    # 에셋 탐색: 델타(PharmAuto.exe) 우선, 없으면 풀 인스톨러 폴백
    delta_url = ""
    installer_url = ""
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name == DELTA_EXE_NAME:
            delta_url = asset.get("browser_download_url", "")
        elif name.lower() == INSTALLER_NAME.lower():
            installer_url = asset.get("browser_download_url", "")

    download_url = delta_url or installer_url
    if not download_url:
        return None

    return {
        "version": tag.lstrip("vV"),
        "download_url": download_url,
        "is_delta": bool(delta_url),
        "notes": data.get("body", "") or "",
    }


def download_and_apply(download_url: str, progress_callback=None,
                       expected_hash: str = "", is_delta: bool = False) -> bool:
    """업데이트 파일을 다운로드하고 적용한다.

    is_delta=True: PharmAuto.exe 만 받아서 현재 exe 를 교체 (설치 UI 없음, 빠름).
    is_delta=False: PharmAutoSetup.exe 받아서 /VERYSILENT 로 재설치 (의존성 바뀐 경우).
    """
    if is_delta:
        return _apply_delta_update(download_url, progress_callback)
    return _apply_full_installer_update(download_url, progress_callback, expected_hash)


def _apply_delta_update(download_url: str, progress_callback=None) -> bool:
    """PharmAuto.exe 만 다운로드 후 즉시 교체. 설치 과정 없이 빠른 업데이트."""
    def _progress(msg):
        print(f"[업데이트] {msg}")
        if progress_callback:
            progress_callback(msg)

    tmp_dir = tempfile.mkdtemp(prefix="pharmauto_delta_")
    new_exe = os.path.join(tmp_dir, DELTA_EXE_NAME)

    try:
        _progress("다운로드 중...")
        resp = requests.get(download_url, stream=True, timeout=60)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        last_pct = -1
        with open(new_exe, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int(downloaded / total * 100)
                    if pct >= last_pct + 10 or pct == 100:
                        _progress(f"다운로드 중... {pct}%")
                        last_pct = pct

        _progress("다운로드 완료, 교체 준비 중...")

        app_dir = os.path.dirname(sys.executable)
        current_exe = os.path.join(app_dir, "PharmAuto.exe")
        data_dir = paths.get_data_dir()
        marker_path = os.path.join(data_dir, "installed_version.txt")

        helper_path = os.path.join(tmp_dir, "_delta.bat")
        with open(helper_path, "w", encoding="mbcs") as f:
            f.write("@echo off\r\n")
            f.write("chcp 65001 >nul\r\n")
            # 현재 PharmAuto.exe 종료 대기
            f.write(":wait_loop\r\n")
            f.write('tasklist /FI "IMAGENAME eq PharmAuto.exe" 2>nul '
                    '| find /I "PharmAuto.exe" >nul\r\n')
            f.write("if %ERRORLEVEL%==0 (\r\n")
            f.write("  timeout /t 1 /nobreak >nul\r\n")
            f.write("  goto wait_loop\r\n")
            f.write(")\r\n")
            # exe 교체 (파일 잠금 해제 직후)
            f.write(f'copy /Y "{new_exe}" "{current_exe}" >nul\r\n')
            f.write("if not %ERRORLEVEL%==0 (\r\n")
            f.write(
                '  mshta "javascript:alert(\'PharmAuto 업데이트 교체 실패. '
                '앱을 수동으로 다시 실행하거나 홈페이지에서 최신 인스톨러를 받아주세요.\');'
                'close()"\r\n'
            )
            f.write("  exit /b 1\r\n")
            f.write(")\r\n")
            # 마커 저장 (재시작 후 업데이트 루프 방지)
            f.write(f'if not exist "{data_dir}" mkdir "{data_dir}"\r\n')
            # 현재 버전 = 서버에서 받은 최신 버전
            # (배치에서 직접 알 수 없으므로 새 exe 실행 시 본인 VERSION 으로 기록하도록
            #  여기서는 빈 파일만 생성 → 앱 시작 시 감지해서 체크 스킵)
            f.write(f'echo updated> "{marker_path}"\r\n')
            # 새 exe 실행
            f.write("timeout /t 1 /nobreak >nul\r\n")
            f.write(f'start "" "{current_exe}"\r\n')
            # 실행 확인
            f.write("timeout /t 5 /nobreak >nul\r\n")
            f.write('tasklist /FI "IMAGENAME eq PharmAuto.exe" 2>nul '
                    '| find /I "PharmAuto.exe" >nul\r\n')
            f.write("if not %ERRORLEVEL%==0 (\r\n")
            f.write(
                '  mshta "javascript:alert(\'PharmAuto 실행 실패. '
                '바탕화면 아이콘에서 수동으로 실행해주세요.\');close()"\r\n'
            )
            f.write(")\r\n")
            f.write("exit /b 0\r\n")

        subprocess.Popen(
            ["cmd.exe", "/c", helper_path],
            cwd=tmp_dir,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        _progress("교체 준비 완료, 앱 종료 후 자동 재시작됩니다.")
        return True
    except Exception as e:
        _progress(f"델타 업데이트 실패: {e}")
        return False


def _apply_full_installer_update(download_url: str, progress_callback=None,
                                  expected_hash: str = "") -> bool:
    """전체 인스톨러 다운로드 후 /VERYSILENT 로 재설치 (기존 방식)."""
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

        # 업데이트 완료 마커 — 재시작 후 첫 기동에서 업데이트 중복 체크 방지용
        app_dir = os.path.dirname(sys.executable)
        app_exe = os.path.join(app_dir, "PharmAuto.exe")
        data_dir = paths.get_data_dir()
        marker_path = os.path.join(data_dir, "installed_version.txt")
        new_version = ""
        # 다운로드 URL의 tag 부분에서 버전 추출 (예: /v1.5.31/ → 1.5.31)
        import re as _re
        m = _re.search(r'/v?(\d+\.\d+\.\d+)/', download_url)
        if m:
            new_version = m.group(1)

        # 업데이트 진행 중 사용자에게 보여줄 HTA 팝업 (자동 닫힘)
        hta_path = os.path.join(tmp_dir, "updating.hta")
        with open(hta_path, "w", encoding="utf-8") as f:
            f.write("""<html>
<head>
<title>PharmAuto 업데이트</title>
<HTA:APPLICATION WINDOWSTATE="normal" SHOWINTASKBAR="no" SYSMENU="no"
 CAPTION="yes" BORDER="thin" MAXIMIZEBUTTON="no" MINIMIZEBUTTON="no"
 SCROLL="no" INNERBORDER="no" CONTEXTMENU="no" SELECTION="no"/>
<style>
body { font-family: 'Malgun Gothic'; text-align: center; padding: 28px;
       background: #fff; margin: 0; color: #1A1A2E; }
h3 { margin: 0 0 12px 0; font-size: 16px; }
p { color: #6B7280; font-size: 12px; margin: 4px 0; }
.bar { width: 100%; height: 4px; background: #E5E7EB; border-radius: 2px;
       overflow: hidden; margin-top: 16px; }
.bar > span { display: block; width: 40%; height: 100%; background: #4B6BFB;
              animation: slide 1.4s infinite linear; }
@keyframes slide { 0% { margin-left: -40%; } 100% { margin-left: 100%; } }
</style>
<script>
window.resizeTo(400, 200);
window.moveTo(screen.availWidth/2 - 200, screen.availHeight/2 - 100);
setTimeout(function(){ window.close(); }, 18000);
</script>
</head>
<body>
<h3>PharmAuto 업데이트 적용 중</h3>
<p>앱이 잠시 종료됩니다.</p>
<p>완료되면 자동으로 다시 실행됩니다.</p>
<div class="bar"><span></span></div>
</body>
</html>
""")

        # 헬퍼 배치 스크립트: 앱 종료 대기 -> 설치 -> 검증 -> 재시작
        helper_path = os.path.join(tmp_dir, "_update.bat")
        with open(helper_path, "w", encoding="mbcs") as f:
            f.write("@echo off\r\n")
            f.write("chcp 65001 >nul\r\n")
            # 진행 안내 팝업 표시 (자동 18초 후 닫힘, 비모달)
            f.write(f'start "" mshta "{hta_path}"\r\n')
            # PharmAuto.exe가 완전히 종료될 때까지 대기
            f.write(":wait_loop\r\n")
            f.write('tasklist /FI "IMAGENAME eq PharmAuto.exe" 2>nul '
                    '| find /I "PharmAuto.exe" >nul\r\n')
            f.write("if %ERRORLEVEL%==0 (\r\n")
            f.write("  timeout /t 2 /nobreak >nul\r\n")
            f.write("  goto wait_loop\r\n")
            f.write(")\r\n")
            # VERYSILENT: 설치 UI 일체 없음 (progress bar 포함) — 사용자는 앱 종료 후 새 앱이 뜨는 것만 봄
            f.write(f'start /wait "" "{installer_path}" '
                    f"/VERYSILENT /SUPPRESSMSGBOXES /NORESTART\r\n")
            f.write("set INSTALL_CODE=%ERRORLEVEL%\r\n")
            # 설치 실패 팝업
            f.write("if not %INSTALL_CODE%==0 (\r\n")
            f.write(
                '  mshta "javascript:alert(\'PharmAuto 업데이트 설치 실패. '
                '기존 버전으로 실행됩니다.\');close()"\r\n'
            )
            f.write(")\r\n")
            # 업데이트 마커 작성 (설치 성공 시만)
            if new_version:
                f.write(f'if %INSTALL_CODE%==0 (\r\n')
                f.write(f'  if not exist "{data_dir}" mkdir "{data_dir}"\r\n')
                f.write(f'  echo {new_version}> "{marker_path}"\r\n')
                f.write(f')\r\n')
            # 앱 기동 + 프로세스 생존 확인
            f.write("timeout /t 1 /nobreak >nul\r\n")
            f.write(f'if exist "{app_exe}" start "" "{app_exe}"\r\n')
            f.write("timeout /t 5 /nobreak >nul\r\n")
            f.write('tasklist /FI "IMAGENAME eq PharmAuto.exe" 2>nul '
                    '| find /I "PharmAuto.exe" >nul\r\n')
            f.write("if not %ERRORLEVEL%==0 (\r\n")
            f.write(
                '  mshta "javascript:alert(\'PharmAuto 실행 실패. '
                '바탕화면 아이콘에서 수동으로 실행해주세요.\');close()"\r\n'
            )
            f.write(")\r\n")
            f.write("exit /b 0\r\n")

        # 헬퍼 실행 — cmd 창 숨김 (스플래시와 mshta 팝업이 피드백 담당)
        subprocess.Popen(
            ["cmd.exe", "/c", helper_path],
            cwd=tmp_dir,
            creationflags=subprocess.CREATE_NO_WINDOW,
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
