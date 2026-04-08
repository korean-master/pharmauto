"""자동 업데이트 모듈 - GitHub 릴리스 기반."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from core.version import VERSION

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.json")
APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# 기본 GitHub 저장소 (settings.json에서 오버라이드 가능)
DEFAULT_REPO = "owner/PharmAuto"


def _get_repo() -> str:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
        return settings.get("github_repo", DEFAULT_REPO)
    except Exception:
        return DEFAULT_REPO


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
        {"version": "1.1.0", "download_url": "...", "notes": "..."} or None
    """
    repo = _get_repo()
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        resp = requests.get(url, timeout=5, headers={"Accept": "application/vnd.github.v3+json"})
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

    # zip 에셋 + 체크섬 찾기
    download_url = ""
    expected_hash = ""
    for asset in data.get("assets", []):
        name = asset.get("name", "").lower()
        if name.endswith(".zip"):
            download_url = asset.get("browser_download_url", "")
        elif name.endswith(".sha256") or name == "checksum.txt":
            # 체크섬 파일 다운로드
            try:
                hash_resp = requests.get(
                    asset.get("browser_download_url", ""), timeout=5
                )
                expected_hash = hash_resp.text.strip().split()[0].lower()
            except Exception:
                pass

    # 에셋 없으면 소스코드 zip 사용
    if not download_url:
        download_url = data.get("zipball_url", "")

    if not download_url:
        return None

    return {
        "version": tag.lstrip("vV"),
        "download_url": download_url,
        "expected_hash": expected_hash,
        "notes": data.get("body", "") or "",
    }


def download_and_apply(download_url: str, progress_callback=None,
                       expected_hash: str = "") -> bool:
    """업데이트를 다운로드하고 적용한다.

    1. zip 다운로드 → 임시 폴더에 압축 해제
    2. config/, data/ 폴더는 보존 (사용자 설정)
    3. 나머지 파일 교체
    4. 완료 후 재시작

    Returns:
        True if successful
    """
    def _progress(msg):
        print(f"[업데이트] {msg}")
        if progress_callback:
            progress_callback(msg)

    tmp_dir = tempfile.mkdtemp(prefix="pharmauto_update_")

    try:
        # 1. 다운로드
        _progress("다운로드 중...")
        zip_path = os.path.join(tmp_dir, "update.zip")
        resp = requests.get(download_url, stream=True, timeout=30)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int(downloaded / total * 100)
                    _progress(f"다운로드 중... {pct}%")

        # 1.5. 체크섬 검증
        if expected_hash:
            import hashlib
            _progress("무결성 검증 중...")
            sha256 = hashlib.sha256()
            with open(zip_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            actual_hash = sha256.hexdigest().lower()
            if actual_hash != expected_hash.lower():
                _progress(f"무결성 검증 실패! 다운로드가 변조되었을 수 있습니다.")
                return False
            _progress("무결성 검증 통과")

        # 2. 압축 해제
        _progress("압축 해제 중...")
        extract_dir = os.path.join(tmp_dir, "extracted")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # zip 내부에 단일 폴더가 있으면 그 안으로 진입
        entries = os.listdir(extract_dir)
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            source_dir = os.path.join(extract_dir, entries[0])
            # 한 단계 더 확인 (GitHub zipball은 repo-branch/ 구조)
            inner = os.listdir(source_dir)
            if len(inner) == 1 and os.path.isdir(os.path.join(source_dir, inner[0])):
                if "main.py" in os.listdir(os.path.join(source_dir, inner[0])):
                    source_dir = os.path.join(source_dir, inner[0])
            elif "main.py" not in inner:
                # main.py가 없으면 구조가 다른 것
                _progress("업데이트 파일 구조 오류")
                return False
        else:
            source_dir = extract_dir

        # main.py 존재 확인
        if not os.path.exists(os.path.join(source_dir, "main.py")):
            _progress("업데이트 파일에 main.py가 없습니다")
            return False

        # 3. 파일 교체 (config, data, screenshots 보존)
        _progress("파일 교체 중...")
        preserve_dirs = {"config", "data", "screenshots", ".git", "__pycache__"}

        for item in os.listdir(source_dir):
            src = os.path.join(source_dir, item)
            dst = os.path.join(APP_ROOT, item)

            if item in preserve_dirs:
                continue

            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        _progress("업데이트 완료!")
        return True

    except Exception as e:
        _progress(f"업데이트 실패: {e}")
        return False
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def restart_app():
    """앱을 재시작한다."""
    python = sys.executable
    main_py = os.path.join(APP_ROOT, "main.py")
    subprocess.Popen([python, main_py], cwd=APP_ROOT)
    sys.exit(0)
