"""재연동 자동 감지 (v1.5.40).

앱 시작 시 onboard_status == failed 인 도매상에 대해
서버 셀렉터가 마지막 시도 이후 갱신됐는지 확인한다.
갱신됐으면 사용자에게 재시도를 제안한다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from core import paths
from core import wholesaler_state


def _load_wholesalers_raw() -> dict:
    path = paths.wholesalers_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        # 'Z' 접미사 / 타임존 오프셋 모두 수용
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def find_candidates() -> list[dict]:
    """재연동 후보 목록 반환.

    조건:
        - onboard_status == "failed"
        - 서버 셀렉터의 updated_at > onboard_last_tried_at

    Returns: [{"wid", "name", "url", "server_updated_at"}, ...]
    """
    from core.cloud import fetch_selector_updated_at, is_enabled
    if not is_enabled():
        return []

    data = _load_wholesalers_raw()
    out = []
    for wid, entry in data.items():
        if wholesaler_state.get_onboard_status(wid) != wholesaler_state.STATUS_FAILED:
            continue
        url = entry.get("url", "")
        if not url:
            continue
        server_ts = fetch_selector_updated_at(url)
        if not server_ts:
            continue
        tried_ts = entry.get("onboard_last_tried_at", "")
        server_dt = _parse_iso(server_ts)
        tried_dt = _parse_iso(tried_ts)
        if not server_dt:
            continue
        # 마지막 시도 시각이 없으면 갱신된 것으로 간주
        if tried_dt is None:
            fresh = True
        else:
            # tried_dt 는 로컬 타임(naive), server_dt 는 UTC 일 수 있음
            if tried_dt.tzinfo is None and server_dt.tzinfo is not None:
                tried_dt = tried_dt.replace(tzinfo=server_dt.tzinfo)
            fresh = server_dt > tried_dt
        if fresh:
            out.append({
                "wid": wid,
                "name": entry.get("name", wid),
                "url": url,
                "server_updated_at": server_ts,
            })
    return out
