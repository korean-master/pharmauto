"""도매상 이력 검색 설정 관리.

각 도매상의 이력 페이지 URL, 검색 셀렉터, 테이블 구조를 저장/조회한다.
로컬 캐시 + Supabase 클라우드 동기화.
"""

import json
import os

from core import paths


# ────────── 기본 설정 (하드코딩 — 스캔으로 발견한 것) ──────────

DEFAULT_CONFIGS = {
    "geo": {
        "name": "지오영",
        "base_url": "https://bpm.geoweb.kr",
        "history_url": "/MyPage/Serial",
        "login": {
            "url": "/",
            "id_sel": "#LoginID",
            "pw_sel": "#Password",
            "btn_sel": "button.btn_login",
        },
        "search": {
            "date_from": "#dtpFrom",
            "date_to": "#dtpTo",
            "keyword": "#txtitem",
            "keyword_placeholder": "상품명으로 입력하세요.",
            "search_btn": "button.btn_search",
        },
        "table": {
            "selector": "table:first-of-type tbody tr",
            "columns": {
                "date": 0,
                "drug_name": 4,
                "qty": 5,
            },
        },
        "lot_detail": {
            "method": "row_click_modal",
            "modal_table": ".ui-dialog .popup_contents table",
            "lot_column": 2,
            "expiry_column": 1,
            "close_btn": '.ui-dialog button:has-text("닫기")',
            "close_fallback": ".ui-dialog .ui-dialog-titlebar-close",
        },
        "notes": "행 클릭 시 jQuery UI 모달이 열리고 LOT번호/유효기한 확인 가능",
    },
    "baekje": {
        "name": "백제약품",
        "base_url": "http://www.ibjp.kr",
        "history_url": "/dist/return",
        "login": {
            "url": "/dist/login",
            "id_sel": 'input[type="text"]',
            "pw_sel": 'input[type="password"]',
            "btn_sel": "button.login_btn",
        },
        "search": {
            "keyword": 'input[placeholder*="품목명"], input[placeholder*="보험코드"]',
            "lot_number": 'input[placeholder*="제조번호"]',
            "period_btn": 'button:has-text("3년")',
            "search_btn": 'button:has-text("검색")',
        },
        "popup_close": '.q-dialog button:has-text("닫기"), '
                       '.q-dialog button:has-text("확인"), '
                       '.q-dialog .q-btn--flat',
        "table": {
            "selector": "table.q-table:first-of-type tbody tr",
            "columns": {
                "drug_name": 0,
                "date": 1,
                "spec": 2,
                "qty": 3,
                "returnable_qty": 8,
            },
        },
        "detail_table": {
            "selector": "table.q-table:nth-of-type(2) tbody tr",
            "columns": {
                "date": 0,
                "expiry": 2,
                "lot_number": 3,
                "qty": 4,
            },
        },
        "notes": "반품 전용 페이지. 약품명+제조번호 검색 가능. 상세 테이블에 LOT 있음",
    },
    "삼원약품": {
        "name": "삼원약품",
        "base_url": "https://www.pharmbox.co.kr",
        "history_url": "/mypharm/sales_ledger.jsp",
        "login": {
            "url": "/",
            "id_sel": "#P_H_USER_ID",
            "pw_sel": "#P_H_PWD",
            "btn_sel": "Enter",
        },
        "search": {
            "keyword": "#P_SRH_SALES_KEY",
            "period_btn": 'button:has-text("6개월")',
            "search_btn": "button.lookup-btn",
        },
        "table": {
            "index": 1,
            "columns": {
                "date": 0,
                "drug_name": 2,
                "qty": 3,
                "lot_number": 8,
                "expiry": 9,
            },
        },
        "notes": "매출원장 페이지. 테이블에서 직접 제조번호/유효기한 확인",
    },
}


# ────────── 로컬 캐시 ──────────

def _load_cache() -> dict:
    cache_path = paths.history_configs_path()
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(data: dict):
    with open(paths.history_configs_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ────────── 공개 API ──────────

def get_config(wholesaler_id: str) -> dict:
    """도매상 이력 검색 설정을 반환한다.

    조회 순서: 로컬 캐시 → 서버 → 기본값
    """
    # 1) 로컬 캐시
    cache = _load_cache()
    if wholesaler_id in cache:
        return cache[wholesaler_id]

    # 2) 서버
    try:
        from core.cloud import fetch_history_config
        server = fetch_history_config(wholesaler_id)
        if server:
            cache[wholesaler_id] = server
            _save_cache(cache)
            return server
    except Exception:
        pass

    # 3) 기본값
    return DEFAULT_CONFIGS.get(wholesaler_id, {})


def save_config(wholesaler_id: str, config: dict, upload: bool = True):
    """도매상 이력 검색 설정을 저장한다.

    로컬 캐시에 저장하고, upload=True면 서버에도 업로드.
    """
    cache = _load_cache()
    cache[wholesaler_id] = config
    _save_cache(cache)

    if upload:
        try:
            from core.cloud import upload_history_config
            import threading
            name = config.get("name", wholesaler_id)
            threading.Thread(
                target=upload_history_config,
                args=(wholesaler_id, name, config),
                daemon=True,
            ).start()
        except Exception:
            pass


def get_all_configs() -> dict:
    """모든 도매상 이력 검색 설정을 반환한다."""
    result = dict(DEFAULT_CONFIGS)

    # 로컬 캐시로 덮어쓰기
    cache = _load_cache()
    result.update(cache)

    # 서버에서 추가 도매상 가져오기
    try:
        from core.cloud import fetch_all_history_configs
        server_configs = fetch_all_history_configs()
        for cfg in server_configs:
            wid = cfg.get("wholesaler_id", "")
            if wid and wid not in result:
                result[wid] = cfg
    except Exception:
        pass

    return result


def upload_all_defaults():
    """기본 설정을 서버에 모두 업로드한다 (초기 세팅 시 1회)."""
    for wid, config in DEFAULT_CONFIGS.items():
        save_config(wid, config, upload=True)
