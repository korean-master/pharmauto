"""사용자 데이터 경로 중앙 관리.

v1.5.35 부터 config/data/logs 는 %APPDATA%\\PharmAuto\\ 에 저장된다.
이전 버전은 {app}\\config\\ 에 저장했기 때문에, 최초 호출 시 자동 마이그레이션한다.

_is_frozen 은 `sys.frozen` 이나 `__compiled__` 를 사용하지 않고 실행 파일 이름으로
판단한다. Nuitka standalone 빌드에서 이 두 플래그는 안정적이지 않다.
(feedback_nuitka_build 참고)
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime

APP_NAME = "PharmAuto"


def _project_root() -> str:
    """core/ 의 부모 폴더. 개발/빌드 상관없이 동일한 규칙."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _is_frozen() -> bool:
    """빌드(Nuitka standalone)인지 개발 모드인지를 **소스 존재 여부**로 판단한다.

    `sys.frozen` / `__compiled__` / `sys.executable` 이름 비교는 Nuitka 빌드에서
    불안정하다 (feedback_nuitka_build 참고). 가장 robust 한 판별은:
        개발 모드 → core/ 의 부모 폴더에 main.py 소스가 있음
        Nuitka   → 소스 파일 포함하지 않으므로 main.py 없음
    """
    return not os.path.exists(os.path.join(_project_root(), "main.py"))


def get_user_data_root() -> str:
    """사용자 데이터 루트.

    빌드(Nuitka) 시 %APPDATA%\\PharmAuto, 개발 시 프로젝트 루트를 반환한다.
    반환 경로가 없으면 생성한다.
    """
    if _is_frozen():
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
        root = os.path.join(appdata, APP_NAME)
    else:
        root = _project_root()
    os.makedirs(root, exist_ok=True)
    return root


def _ensured(sub: str) -> str:
    d = os.path.join(get_user_data_root(), sub)
    os.makedirs(d, exist_ok=True)
    return d


def get_config_dir() -> str:
    return _ensured("config")


def get_data_dir() -> str:
    return _ensured("data")


def get_logs_dir() -> str:
    return _ensured("logs")


def get_selectors_dir() -> str:
    d = os.path.join(get_config_dir(), "selectors")
    os.makedirs(d, exist_ok=True)
    return d


def get_screenshots_dir() -> str:
    return _ensured("screenshots")


def get_traces_dir() -> str:
    return _ensured("traces")


def get_backup_dir() -> str:
    return _ensured("backup")


def settings_path() -> str:
    return os.path.join(get_config_dir(), "settings.json")


def wholesalers_path() -> str:
    return os.path.join(get_config_dir(), "wholesalers.json")


def exclusions_path() -> str:
    return os.path.join(get_config_dir(), "exclusions.json")


def auth_path() -> str:
    return os.path.join(get_config_dir(), "auth.json")


def history_configs_path() -> str:
    return os.path.join(get_config_dir(), "history_configs.json")


# ---------------------------------------------------------------------------
# 마이그레이션
# ---------------------------------------------------------------------------

_MIGRATION_MARKER = ".migrated_to_appdata"


def _legacy_install_root() -> str:
    """구 버전에서 config/data 가 있던 위치 — exe 가 있는 폴더."""
    return os.path.dirname(os.path.abspath(sys.executable))


def migrate_from_legacy_install() -> bool:
    """{app}\\config + {app}\\data 를 %APPDATA%\\PharmAuto 로 일회성 이전.

    이미 마이그레이션 완료 마커가 있으면 스킵한다.
    대상(%APPDATA%)에 같은 이름 파일이 이미 있으면 건드리지 않는다 (덮어쓰기 금지).
    개발 모드에서는 아무것도 하지 않는다.

    Returns:
        실제로 파일을 옮겼으면 True.
    """
    if not _is_frozen():
        return False

    root = get_user_data_root()
    marker = os.path.join(root, _MIGRATION_MARKER)
    if os.path.exists(marker):
        return False

    legacy_root = _legacy_install_root()
    moved_any = False

    for sub in ("config", "data", "screenshots"):
        legacy_sub = os.path.join(legacy_root, sub)
        if not os.path.isdir(legacy_sub):
            continue
        target_sub = _ensured(sub)
        moved_any |= _copy_tree_noclobber(legacy_sub, target_sub)

    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat())
    except OSError:
        pass

    return moved_any


def _copy_tree_noclobber(src: str, dst: str) -> bool:
    """덮어쓰지 않고 재귀 복사. 대상에 이미 있으면 건너뛴다."""
    moved = False
    for name in os.listdir(src):
        src_path = os.path.join(src, name)
        dst_path = os.path.join(dst, name)
        if os.path.exists(dst_path):
            if os.path.isdir(src_path) and os.path.isdir(dst_path):
                moved |= _copy_tree_noclobber(src_path, dst_path)
            continue
        try:
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)
            moved = True
        except OSError:
            pass
    return moved


# ---------------------------------------------------------------------------
# 자동 백업 (일 1회 스냅샷, 최근 7개 유지)
# ---------------------------------------------------------------------------

def snapshot_config_daily(keep: int = 7) -> str | None:
    """하루 한 번 config 폴더를 backup/YYYYMMDD/config 로 스냅샷한다.

    오늘자 스냅샷이 이미 있으면 건너뛴다. 오래된 스냅샷을 `keep` 개만 남기고 삭제한다.
    Returns: 새로 만들어진 스냅샷 경로, 없으면 None.
    """
    today = datetime.now().strftime("%Y%m%d")
    backup_root = get_backup_dir()
    today_dir = os.path.join(backup_root, today)
    if os.path.exists(today_dir):
        _prune_backups(backup_root, keep)
        return None

    try:
        shutil.copytree(get_config_dir(), os.path.join(today_dir, "config"))
    except OSError:
        return None

    _prune_backups(backup_root, keep)
    return today_dir


def _prune_backups(backup_root: str, keep: int) -> None:
    try:
        entries = [
            e for e in os.listdir(backup_root)
            if len(e) == 8 and e.isdigit() and os.path.isdir(os.path.join(backup_root, e))
        ]
    except OSError:
        return
    entries.sort(reverse=True)
    for old in entries[keep:]:
        try:
            shutil.rmtree(os.path.join(backup_root, old))
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 일회성 셀렉터 캐시 invalidate (v1.5.38)
# ---------------------------------------------------------------------------

_SELECTORS_INVALIDATE_MARKER = ".selectors_invalidated_v1538"


def invalidate_selectors_cache_once() -> int:
    """v1.5.38 첫 실행 시 로컬 selector 캐시를 비운다 (일회성).

    배경: v1.5.37 까지 `sync_local_to_cloud()` 가 로컬 셀렉터를 서버에
    무조건 upsert 해서, 낡은 로컬 파일이 서버 최신본을 덮어쓰는 사고 발생
    (세화 사례). v1.5.38 에서 업로드 로직은 제거했지만, 기존 오염된 로컬
    캐시도 한 번 비워줘야 다음 주문 시 서버에서 깨끗하게 fetch 된다.

    Returns: 삭제된 파일 개수. 이미 실행됐으면 -1.
    """
    marker = os.path.join(get_user_data_root(), _SELECTORS_INVALIDATE_MARKER)
    if os.path.exists(marker):
        return -1

    count = 0
    sel_dir = get_selectors_dir()
    try:
        for name in os.listdir(sel_dir):
            if name.endswith(".json"):
                try:
                    os.remove(os.path.join(sel_dir, name))
                    count += 1
                except OSError:
                    pass
    except OSError:
        pass

    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat())
    except OSError:
        pass

    return count
