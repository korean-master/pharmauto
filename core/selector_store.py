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


def _is_legacy_format(selectors: dict) -> bool:
    """v1.5.43 이전 포맷 (절대경로 cart_btn 또는 bool 타입 필드) 감지."""
    if not selectors:
        return False
    table = selectors.get("table", {}) or {}
    # 명시적 스키마 버전 — v1.5.43 이후는 전부 현대 포맷으로 인정
    schema = table.get("schema_version", "")
    if schema in ("v1.5.43", "v1.5.44", "v1.5.45", "v1.5.46"):
        return False
    layout = table.get("layout_mode", "")
    # v1.5.44: global_cart_btn — global_cart_btn 필드 있으면 현대
    if layout == "global_cart_btn":
        return False if table.get("global_cart_btn") else True
    # v1.5.46: select_then_add — cart_btn + qty_input 필드 있으면 현대
    # (cart_btn 필드명이 구 포맷 "cart_btn" 과 겹치므로 layout_mode 로만 구분)
    if layout == "select_then_add":
        return False if (table.get("cart_btn") and table.get("qty_input")) else True
    cart_rel = table.get("cart_btn_in_row")
    # 새 포맷: cart_btn_in_row 가 str 이고 row 상대경로
    if isinstance(cart_rel, str) and cart_rel.strip():
        # tr 포함 체크 (절대경로 잔재)
        if "tr:nth-of-type" in cart_rel or cart_rel.startswith("tr"):
            return True
        # tr 없어도 cart_btn (절대경로) 필드가 같이 있으면 구 포맷 혼재
        return False
    # cart_btn_in_row 없음/bool → 구 포맷 (단, layout_mode 가 명시된 신 포맷은 위에서 처리됨)
    if isinstance(cart_rel, bool):
        return True
    if table.get("cart_btn"):
        return True
    return False


def _invalidate_legacy(wid: str, source: str = "load") -> None:
    """구 포맷 감지 시 로컬 삭제 + onboard_status=failed 전환."""
    try:
        path = _local_path(wid)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    try:
        from core.wholesaler_state import set_onboard_status, STATUS_FAILED
        set_onboard_status(
            wid, STATUS_FAILED,
            stage="schema",
            error=f"셀렉터가 구 포맷 (v1.5.43 이전) — 재연동 필요 [{source}]"
        )
    except Exception:
        pass


def load_selectors(wid: str, url: str = "") -> dict:
    """도매상 셀렉터를 불러온다.

    조회 순서:
      1. 로컬 캐시 (config/selectors/{wid}.json)
      2. 클라우드에서 다운로드 (정규화된 도메인으로 조회)

    v1.5.43: 구 포맷 감지 시 자동 무효화 + onboard_status=failed 전환.

    Args:
        wid: 도매상 ID
        url: 도매상 URL (클라우드 조회 시 도메인 추출용)

    Returns:
        셀렉터 dict. 없거나 구 포맷이면 빈 dict.
    """
    # 1. 로컬 캐시
    path = _local_path(wid)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if _is_legacy_format(data):
                _invalidate_legacy(wid, source="local")
                return {}
            return data
        except Exception:
            pass

    # 2. 클라우드에서 다운로드 — URL 또는 wid로 정규화 조회
    try:
        from core.cloud import fetch_selectors
        cloud_sel = fetch_selectors(url or wid)
        if cloud_sel:
            if _is_legacy_format(cloud_sel):
                # 서버에도 구 포맷이면 저장 생략 + failed 처리
                _invalidate_legacy(wid, source="cloud")
                return {}
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
