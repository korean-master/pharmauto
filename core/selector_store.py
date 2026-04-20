"""도매상 셀렉터 저장소 — 로컬 캐시 + Supabase 클라우드 연동.

모든 셀렉터 저장/불러오기는 이 모듈을 통해서만 한다.
조회: 로컬 → 클라우드 순. 저장: 로컬 + 클라우드 동시.
"""

import json
import os
import re
import threading

from core import paths


def _safe_filename(wid: str) -> str:
    return re.sub(r'[^\w]', '_', wid)


def _local_path(wid: str) -> str:
    return os.path.join(paths.get_selectors_dir(), f"{_safe_filename(wid)}.json")


def _extract_domain(wid: str, selectors: dict = None, url: str = "") -> str:
    """도매상의 정규화된 도메인을 추출한다."""
    from core.cloud import normalize_domain
    # URL 우선 (셀렉터 → 파라미터 → wid)
    src = ""
    if selectors and selectors.get("url"):
        src = selectors["url"]
    elif url:
        src = url
    else:
        src = wid
    normalized = normalize_domain(src)
    return normalized if normalized and len(normalized) >= 3 else wid


def load_selectors(wid: str, url: str = "") -> dict:
    """도매상 셀렉터를 불러온다.

    조회 순서:
      1. 로컬 캐시 (config/selectors/{wid}.json)
      2. 클라우드에서 다운로드 (정규화된 도메인으로 조회)

    Args:
        wid: 도매상 ID
        url: 도매상 URL (클라우드 조회 시 도메인 추출용)

    Returns:
        셀렉터 dict. 없으면 빈 dict.
    """
    # 1. 로컬 캐시
    path = _local_path(wid)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # 2. 클라우드에서 다운로드 — URL 또는 wid로 정규화 조회
    try:
        from core.cloud import fetch_selectors
        # URL이 있으면 URL로, 없으면 wid로 조회 (내부에서 정규화됨)
        cloud_sel = fetch_selectors(url or wid)
        if cloud_sel:
            save_selectors(wid, cloud_sel, upload=False)
            return cloud_sel
    except Exception:
        pass

    return {}


def save_selectors(wid: str, selectors: dict, upload: bool = True):
    """도매상 셀렉터를 저장한다.

    Args:
        wid: 도매상 ID
        selectors: 셀렉터 dict
        upload: True면 클라우드에도 업로드
    """
    # 1. 로컬 저장
    path = _local_path(wid)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(selectors, f, ensure_ascii=False, indent=2)

    # 2. 클라우드 업로드 (백그라운드)
    if upload:
        domain = _extract_domain(wid, selectors)
        name = selectors.get("name", wid)

        def _upload():
            try:
                from core.cloud import upload_selectors
                upload_selectors(domain, name, selectors)
            except Exception as e:
                print(f"[셀렉터] 클라우드 업로드 실패: {wid} - {e}")

        threading.Thread(target=_upload, daemon=True).start()


def list_cached() -> list[str]:
    """로컬에 캐시된 도매상 ID 목록을 반환한다."""
    d = paths.get_selectors_dir()
    if not os.path.exists(d):
        return []
    return [
        f.replace(".json", "")
        for f in os.listdir(d)
        if f.endswith(".json")
    ]


def delete_selectors(wid: str):
    """도매상 셀렉터를 삭제한다."""
    path = _local_path(wid)
    if os.path.exists(path):
        os.remove(path)
