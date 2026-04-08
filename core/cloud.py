"""Supabase 클라우드 동기화 — 약품 정보, 규격, 셀렉터 공유.

사용자가 늘수록 데이터가 쌓여 전체 시스템이 개선되는 구조.
서버 장애 시에도 로컬 데이터로 정상 동작한다.
"""

import json
import os
import threading
from datetime import datetime
from urllib.parse import quote

import requests

# ────────────────────── 설정 ──────────────────────

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.json")


def _load_cloud_config() -> tuple[str, str]:
    """settings.json에서 Supabase URL과 anon key를 읽는다."""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            s = json.load(f)
        return s.get("supabase_url", ""), s.get("supabase_key", "")
    except Exception:
        return "", ""


def _headers() -> dict:
    url, key = _load_cloud_config()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def _api_url(table: str) -> str:
    url, _ = _load_cloud_config()
    return f"{url}/rest/v1/{table}"


def is_enabled() -> bool:
    """클라우드 동기화가 설정되어 있는지 확인."""
    url, key = _load_cloud_config()
    return bool(url and key)


# ────────────────────── 약품 정보 (drugs) ──────────────────────

def upload_drug(insurance_code: str, drug_name: str, spec: str = ""):
    """약품 정보를 서버에 기여한다 (upsert)."""
    if not is_enabled() or not insurance_code or not drug_name:
        return
    try:
        requests.post(
            _api_url("drugs"),
            headers=_headers(),
            json={
                "insurance_code": insurance_code,
                "drug_name": drug_name,
                "spec": spec,
                "updated_at": datetime.utcnow().isoformat(),
            },
            timeout=5,
        )
    except Exception:
        pass


def upload_drugs_bulk(drugs: list[dict]):
    """약품 정보를 일괄 업로드한다.

    Args:
        drugs: [{"insurance_code", "drug_name", "spec"}, ...]
    """
    if not is_enabled() or not drugs:
        return
    now = datetime.utcnow().isoformat()
    rows = [
        {
            "insurance_code": d["insurance_code"],
            "drug_name": d["drug_name"],
            "spec": d.get("spec", ""),
            "updated_at": now,
        }
        for d in drugs
        if d.get("insurance_code") and d.get("drug_name")
    ]
    if not rows:
        return
    try:
        requests.post(
            _api_url("drugs"),
            headers=_headers(),
            json=rows,
            timeout=10,
        )
    except Exception:
        pass


def fetch_drug(insurance_code: str) -> dict | None:
    """서버에서 약품 정보를 조회한다.

    Returns:
        {"drug_name": str, "spec": str} 또는 None
    """
    if not is_enabled() or not insurance_code:
        return None
    try:
        resp = requests.get(
            _api_url("drugs"),
            headers=_headers(),
            params={"insurance_code": f"eq.{insurance_code}", "select": "drug_name,spec"},
            timeout=5,
        )
        rows = resp.json()
        if rows:
            return rows[0]
    except Exception:
        pass
    return None


# ────────────────────── 약품 규격 (drug_units) ──────────────────────

def upload_units(insurance_code: str, pack_sizes: list[int],
                 wholesaler_domain: str = "common"):
    """약품 규격을 서버에 기여한다 (upsert)."""
    if not is_enabled() or not insurance_code or not pack_sizes:
        return
    try:
        requests.post(
            _api_url("drug_units"),
            headers=_headers(),
            json={
                "insurance_code": insurance_code,
                "wholesaler_domain": wholesaler_domain,
                "pack_sizes": sorted(set(pack_sizes)),
                "updated_at": datetime.utcnow().isoformat(),
            },
            timeout=5,
        )
    except Exception:
        pass


def fetch_units(insurance_code: str) -> list[int]:
    """서버에서 약품 규격을 조회한다. 모든 도매상 데이터를 합쳐서 반환."""
    if not is_enabled() or not insurance_code:
        return []
    try:
        resp = requests.get(
            _api_url("drug_units"),
            headers=_headers(),
            params={
                "insurance_code": f"eq.{insurance_code}",
                "select": "pack_sizes",
            },
            timeout=5,
        )
        rows = resp.json()
        merged = set()
        for row in rows:
            merged.update(row.get("pack_sizes", []))
        return sorted(merged) if merged else []
    except Exception:
        return []


# ────────────────────── 도매상 셀렉터 (wholesaler_selectors) ──────────────────────

def upload_selectors(domain: str, name: str, selectors: dict):
    """도매상 셀렉터를 서버에 기여한다 (upsert)."""
    if not is_enabled() or not domain:
        return
    try:
        requests.post(
            _api_url("wholesaler_selectors"),
            headers=_headers(),
            json={
                "domain": domain,
                "name": name,
                "login_sel": selectors.get("login", {}),
                "search_sel": selectors.get("search", {}),
                "table_sel": selectors.get("table", {}),
                "confirm_sel": selectors.get("confirm", {}),
                "auto_detected": selectors.get("auto_detected", False),
                "updated_at": datetime.utcnow().isoformat(),
            },
            timeout=5,
        )
    except Exception:
        pass


def fetch_selectors(domain: str) -> dict | None:
    """서버에서 도매상 셀렉터를 조회한다.

    Returns:
        셀렉터 dict (로컬 저장 형식과 동일) 또는 None
    """
    if not is_enabled() or not domain:
        return None
    try:
        resp = requests.get(
            _api_url("wholesaler_selectors"),
            headers=_headers(),
            params={"domain": f"eq.{domain}"},
            timeout=5,
        )
        rows = resp.json()
        if not rows:
            return None
        row = rows[0]
        return {
            "login": row.get("login_sel", {}),
            "search": row.get("search_sel", {}),
            "table": row.get("table_sel", {}),
            "confirm": row.get("confirm_sel", {}),
            "auto_detected": row.get("auto_detected", False),
        }
    except Exception:
        return None


# ────────────────────── 백그라운드 동기화 ──────────────────────

def sync_local_to_cloud():
    """로컬 캐시 데이터를 서버에 일괄 업로드한다 (앱 시작 시 1회)."""
    if not is_enabled():
        return

    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    config_dir = os.path.join(os.path.dirname(__file__), "..", "config")

    # 1) 약품 캐시 업로드
    drug_cache_path = os.path.join(data_dir, "drug_cache.json")
    if os.path.exists(drug_cache_path):
        try:
            with open(drug_cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            drugs = [
                {
                    "insurance_code": code,
                    "drug_name": info.get("drug_name", ""),
                    "spec": info.get("spec", ""),
                }
                for code, info in cache.items()
                if info.get("drug_name")
            ]
            upload_drugs_bulk(drugs)
        except Exception:
            pass

    # 2) 규격 캐시 업로드
    unit_cache_path = os.path.join(data_dir, "unit_cache.json")
    if os.path.exists(unit_cache_path):
        try:
            with open(unit_cache_path, "r", encoding="utf-8") as f:
                units = json.load(f)
            for code, sizes in units.items():
                upload_units(code, sizes)
        except Exception:
            pass

    # 3) 셀렉터 업로드
    sel_dir = os.path.join(config_dir, "selectors")
    if os.path.exists(sel_dir):
        try:
            for fname in os.listdir(sel_dir):
                if not fname.endswith(".json"):
                    continue
                with open(os.path.join(sel_dir, fname), "r", encoding="utf-8") as f:
                    sel = json.load(f)
                wid = fname.replace(".json", "")
                # domain 추출: URL에서 가져오거나 wid 사용
                domain = sel.get("url", wid)
                name = sel.get("name", wid)
                upload_selectors(domain, name, sel)
        except Exception:
            pass


def sync_cloud_to_local():
    """서버에서 최신 데이터를 로컬로 동기화한다 (앱 시작 시 1회)."""
    if not is_enabled():
        return

    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")

    # 1) 약품 캐시 보강 — 서버에만 있는 약품을 로컬에 추가
    drug_cache_path = os.path.join(data_dir, "drug_cache.json")
    try:
        local_cache = {}
        if os.path.exists(drug_cache_path):
            with open(drug_cache_path, "r", encoding="utf-8") as f:
                local_cache = json.load(f)

        resp = requests.get(
            _api_url("drugs"),
            headers=_headers(),
            params={"select": "insurance_code,drug_name,spec", "limit": "5000"},
            timeout=10,
        )
        server_drugs = resp.json()

        added = 0
        for row in server_drugs:
            code = row["insurance_code"]
            if code not in local_cache:
                local_cache[code] = {
                    "drug_name": row["drug_name"],
                    "spec": row.get("spec", ""),
                }
                added += 1

        if added > 0:
            os.makedirs(data_dir, exist_ok=True)
            with open(drug_cache_path, "w", encoding="utf-8") as f:
                json.dump(local_cache, f, ensure_ascii=False, indent=2)
            print(f"[클라우드] 약품 정보 {added}건 동기화")

    except Exception as e:
        print(f"[클라우드] 약품 동기화 실패: {e}")

    # 2) 규격 캐시 보강
    unit_cache_path = os.path.join(data_dir, "unit_cache.json")
    try:
        local_units = {}
        if os.path.exists(unit_cache_path):
            with open(unit_cache_path, "r", encoding="utf-8") as f:
                local_units = json.load(f)

        resp = requests.get(
            _api_url("drug_units"),
            headers=_headers(),
            params={"select": "insurance_code,pack_sizes", "limit": "5000"},
            timeout=10,
        )
        server_units = resp.json()

        updated = 0
        for row in server_units:
            code = row["insurance_code"]
            server_sizes = set(row.get("pack_sizes", []))
            local_sizes = set(local_units.get(code, []))
            merged = sorted(local_sizes | server_sizes)
            if merged != local_units.get(code, []):
                local_units[code] = merged
                updated += 1

        if updated > 0:
            os.makedirs(data_dir, exist_ok=True)
            with open(unit_cache_path, "w", encoding="utf-8") as f:
                json.dump(local_units, f, ensure_ascii=False, indent=2)
            print(f"[클라우드] 규격 정보 {updated}건 동기화")

    except Exception as e:
        print(f"[클라우드] 규격 동기화 실패: {e}")


def start_background_sync():
    """앱 시작 시 백그라운드에서 양방향 동기화 실행."""
    if not is_enabled():
        return
    t = threading.Thread(target=_background_sync, daemon=True)
    t.start()


def _background_sync():
    """업로드 → 다운로드 순서로 동기화."""
    try:
        sync_local_to_cloud()
        sync_cloud_to_local()
        print("[클라우드] 동기화 완료")
    except Exception as e:
        print(f"[클라우드] 동기화 실패: {e}")
