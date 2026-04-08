"""도매상 셀렉터 저장소 — 로컬 캐시 + Supabase 클라우드 연동.

모든 셀렉터 저장/불러오기는 이 모듈을 통해서만 한다.
조회: 로컬 → 클라우드 순. 저장: 로컬 + 클라우드 동시.
"""

import json
import os
import re
import threading

SELECTORS_DIR = os.path.join(os.path.dirname(__file__), "..", "config", "selectors")


def _safe_filename(wid: str) -> str:
    return re.sub(r'[^\w]', '_', wid)


def _local_path(wid: str) -> str:
    os.makedirs(SELECTORS_DIR, exist_ok=True)
    return os.path.join(SELECTORS_DIR, f"{_safe_filename(wid)}.json")


def _extract_domain(wid: str, selectors: dict = None) -> str:
    """도매상 ID 또는 셀렉터에서 도메인을 추출한다."""
    if selectors and selectors.get("url"):
        from urllib.parse import urlparse
        parsed = urlparse(selectors["url"])
        if parsed.netloc:
            return parsed.netloc
    return wid


def load_selectors(wid: str) -> dict:
    """도매상 셀렉터를 불러온다.

    조회 순서:
      1. 로컬 캐시 (config/selectors/{wid}.json)
      2. 클라우드에서 다운로드 → 로컬에 저장

    Returns:
        셀렉터 dict. 없으면 빈 dict.
    """
    # 1. 로컬 캐시
    path = _local_path(wid)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # 2. 클라우드에서 다운로드
    domain = _extract_domain(wid)
    try:
        from core.cloud import fetch_selectors
        cloud_sel = fetch_selectors(domain)
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
            except Exception:
                pass

        threading.Thread(target=_upload, daemon=True).start()


def list_cached() -> list[str]:
    """로컬에 캐시된 도매상 ID 목록을 반환한다."""
    if not os.path.exists(SELECTORS_DIR):
        return []
    return [
        f.replace(".json", "")
        for f in os.listdir(SELECTORS_DIR)
        if f.endswith(".json")
    ]


def delete_selectors(wid: str):
    """도매상 셀렉터를 삭제한다."""
    path = _local_path(wid)
    if os.path.exists(path):
        os.remove(path)
