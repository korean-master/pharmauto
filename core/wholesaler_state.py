"""도매상 온보딩 상태 저장/조회 헬퍼 (v1.5.40).

wholesalers.json 의 각 도매상 엔트리에 다음 평문 필드를 관리한다:
    onboard_status:        "verified" | "failed" | "pending"
    onboard_last_tried_at: ISO 시각 (full_onboard 또는 test_connection 실행 시점)
    onboard_stage:         마지막 실패 단계 (login/search/cart_button/verify/save)
    onboard_error:         사용자 표시용 간단 메시지 (기술 상세 금지)

ID/PW 는 DPAPI 로 암호화된 상태 그대로 유지된다.
전체 파일 load/save 대신 평문 필드만 partial update 하여
암호화 상태가 깨지지 않도록 한다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from core import paths

STATUS_VERIFIED = "verified"
STATUS_FAILED = "failed"
STATUS_PENDING = "pending"


def _load_raw() -> dict:
    path = paths.wholesalers_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_raw(data: dict) -> None:
    try:
        with open(paths.wholesalers_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def set_onboard_status(
    wid: str,
    status: str,
    stage: str = "",
    error: str = "",
) -> None:
    """온보딩 상태 기록. ID/PW 암호화 필드는 건드리지 않는다."""
    data = _load_raw()
    if wid not in data:
        return
    data[wid]["onboard_status"] = status
    data[wid]["onboard_last_tried_at"] = datetime.now().isoformat()
    if status == STATUS_VERIFIED:
        data[wid]["onboard_stage"] = ""
        data[wid]["onboard_error"] = ""
    else:
        data[wid]["onboard_stage"] = stage or ""
        data[wid]["onboard_error"] = error or ""
    _save_raw(data)


def get_onboard_status(wid: str) -> str:
    """저장된 onboard_status 반환. 없으면 과거 connection_status 기반 폴백."""
    entry = _load_raw().get(wid, {})
    st = entry.get("onboard_status")
    if st in (STATUS_VERIFIED, STATUS_FAILED, STATUS_PENDING):
        return st
    # 과거 호환: v1.5.39 이하에서 저장된 connection_status 만 있는 경우
    if entry.get("connection_status") == "정상":
        return STATUS_VERIFIED
    return STATUS_PENDING


def get_last_tried_at(wid: str) -> str:
    """마지막 시도 ISO 시각. 없으면 빈 문자열."""
    return _load_raw().get(wid, {}).get("onboard_last_tried_at", "")


def is_verified(wid: str) -> bool:
    return get_onboard_status(wid) == STATUS_VERIFIED


def is_failed(wid: str) -> bool:
    return get_onboard_status(wid) == STATUS_FAILED


def all_statuses() -> dict:
    """모든 도매상의 상태 dict 반환: {wid: status}."""
    data = _load_raw()
    return {wid: get_onboard_status(wid) for wid in data.keys()}
