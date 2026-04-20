"""Supabase 클라우드 동기화 - 약품 정보, 규격, 셀렉터 공유.

사용자가 늘수록 데이터가 쌓여 전체 시스템이 개선되는 구조.
서버 장애 시에도 로컬 데이터로 정상 동작한다.
"""

import json
import os
import threading
from datetime import datetime
from urllib.parse import quote

import requests

from core import paths

# ────────────────────── 설정 ──────────────────────

# 기본 Supabase 설정 — settings.json에 없어도 클라우드 기능이 동작하도록
_DEFAULT_URL = "https://bvxcdgnuslxobcaqdtds.supabase.co"
_DEFAULT_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ2eGNkZ251c2x4b2JjYXFkdGRzIiwi"
    "cm9sZSI6ImFub24iLCJpYXQiOjE3NzU2MDE3MTYsImV4cCI6MjA5MTE3NzcxNn0."
    "_1KW_PBoHcW2nKyNQlkO-QngtaKKusAqZpi2XxZpHt0"
)


def _load_cloud_config() -> tuple[str, str]:
    """settings.json에서 Supabase URL과 anon key를 읽는다."""
    try:
        with open(paths.settings_path(), "r", encoding="utf-8") as f:
            s = json.load(f)
        return (s.get("supabase_url") or _DEFAULT_URL,
                s.get("supabase_key") or _DEFAULT_KEY)
    except Exception:
        return _DEFAULT_URL, _DEFAULT_KEY


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

def normalize_domain(url_or_domain: str) -> str:
    """URL이나 도메인에서 핵심 식별자를 추출한다.

    어떤 형태로 입력하든 같은 사이트면 같은 값을 반환.
    www.ibjp.kr -> ibjp, ibjp.co.kr -> ibjp, https://ibjp.co.kr/login -> ibjp
    www.pharmbox.co.kr -> pharmbox, esehwa.co.kr -> esehwa
    bpm.geoweb.kr -> geoweb
    """
    import re
    s = url_or_domain.strip()
    if not s:
        return ""

    # URL이면 도메인만 추출
    if "/" in s or ":" in s:
        from urllib.parse import urlparse
        parsed = urlparse(s if "://" in s else f"http://{s}")
        s = parsed.netloc or s
    # 포트 제거
    s = s.split(":")[0]
    # www. 제거
    s = re.sub(r"^www\.", "", s)
    # 도메인 파트 분리
    parts = s.split(".")
    # TLD 제거: .kr, .com, .co.kr, .or.kr 등
    tld_parts = {"kr", "com", "net", "org", "co", "or", "go", "ac", "pe"}
    while len(parts) > 1 and parts[-1] in tld_parts:
        parts.pop()
    # 남은 것 중 마지막이 핵심 도메인 (bpm.geoweb -> geoweb)
    return parts[-1] if parts else s


def upload_selectors(domain: str, name: str, selectors: dict):
    """도매상 셀렉터를 서버에 기여한다 (upsert).

    domain은 정규화하여 저장 - 같은 사이트는 항상 같은 키로 저장.
    업로드 전 보안 검증 필수.
    """
    if not is_enabled():
        return
    # 도메인 정규화
    normalized = normalize_domain(domain)
    if not normalized:
        print(f"[클라우드] 도메인 추출 실패 - 업로드 취소 ({domain})")
        return
    # 업로드 전 보안 필터
    try:
        from core.selector_validator import validate_selectors
        if not validate_selectors(selectors):
            print(f"[클라우드] 셀렉터 보안 검증 실패 - 업로드 취소 ({normalized})")
            return
    except Exception:
        pass
    try:
        resp = requests.post(
            _api_url("wholesaler_selectors"),
            headers=_headers(),
            json={
                "domain": normalized,
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
        print(f"[클라우드] 셀렉터 업로드: {normalized} ({name}) - {resp.status_code}")
    except Exception as e:
        print(f"[클라우드] 셀렉터 업로드 실패: {normalized} - {e}")


def fetch_selectors(domain: str) -> dict | None:
    """서버에서 도매상 셀렉터를 조회한다.

    입력 도메인을 정규화하여 조회 - 같은 사이트면 항상 매칭됨.
    다운로드 후 보안 필터 필수.

    Returns:
        셀렉터 dict (로컬 저장 형식과 동일) 또는 None
    """
    if not is_enabled() or not domain:
        return None

    normalized = normalize_domain(domain)
    if not normalized or len(normalized) < 3:
        return None

    try:
        resp = requests.get(
            _api_url("wholesaler_selectors"),
            headers=_headers(),
            params={"domain": f"eq.{normalized}"},
            timeout=5,
        )
        rows = resp.json()
        if not rows:
            return None
        row = rows[0]
        result = {
            "login": row.get("login_sel", {}),
            "search": row.get("search_sel", {}),
            "table": row.get("table_sel", {}),
            "confirm": row.get("confirm_sel", {}),
            "auto_detected": row.get("auto_detected", False),
            "confidence": row.get("confidence", "provisional"),
        }
        # 다운로드 후 보안 필터 (서버 오염 시나리오 차단 - 가장 중요)
        try:
            from core.selector_validator import validate_selectors
            if not validate_selectors(result):
                print(f"[클라우드] 다운로드 셀렉터 보안 검증 실패 - 폐기 ({domain})")
                return None
        except Exception:
            pass
        return result
    except Exception:
        return None



# ────────── 도매상 이력 검색 설정 (wholesaler_history_config) ──────────

def upload_history_config(wholesaler_id: str, name: str, config: dict):
    """도매상 이력 검색 설정을 서버에 업로드한다 (upsert).

    config 예시:
    {
        "history_url": "/MyPage/Serial",
        "search_selectors": {"date_from": "#dtpFrom", "keyword": "#txtitem", ...},
        "table_columns": {"drug_name": 4, "date": 0, "qty": 5, "lot": 2, ...},
        "modal": {"has_modal": True, "close_btn": ".ui-dialog button:has-text('닫기')"},
        "period_buttons": {"3년": "button:has-text('3년')"},
        "notes": "행 클릭 시 모달에서 LOT 확인 가능",
    }
    """
    if not is_enabled() or not wholesaler_id:
        return
    try:
        requests.post(
            _api_url("wholesaler_history_config"),
            headers=_headers(),
            json={
                "wholesaler_id": wholesaler_id,
                "name": name,
                "config": json.dumps(config, ensure_ascii=False),
                "updated_at": datetime.utcnow().isoformat(),
            },
            timeout=5,
        )
    except Exception:
        pass


def fetch_history_config(wholesaler_id: str) -> dict | None:
    """서버에서 도매상 이력 검색 설정을 조회한다."""
    if not is_enabled() or not wholesaler_id:
        return None
    try:
        resp = requests.get(
            _api_url("wholesaler_history_config"),
            headers=_headers(),
            params={"wholesaler_id": f"eq.{wholesaler_id}"},
            timeout=5,
        )
        rows = resp.json()
        if not rows:
            return None
        return json.loads(rows[0].get("config", "{}"))
    except Exception:
        return None


def fetch_all_history_configs() -> list[dict]:
    """서버에 등록된 모든 도매상 이력 검색 설정을 조회한다."""
    if not is_enabled():
        return []
    try:
        resp = requests.get(
            _api_url("wholesaler_history_config"),
            headers=_headers(),
            params={"order": "updated_at.desc"},
            timeout=5,
        )
        rows = resp.json()
        result = []
        for row in rows:
            item = {
                "wholesaler_id": row.get("wholesaler_id", ""),
                "name": row.get("name", ""),
            }
            item.update(json.loads(row.get("config", "{}")))
            result.append(item)
        return result
    except Exception:
        return []


# ────────────────────── 백그라운드 동기화 ──────────────────────

def sync_local_to_cloud():
    """로컬 캐시 데이터를 서버에 일괄 업로드한다 (앱 시작 시 1회)."""
    if not is_enabled():
        return

    data_dir = paths.get_data_dir()

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

    # 3) 셀렉터 업로드 — v1.5.38 부터 제거됨
    # 기존: 앱 시작 시 로컬 셀렉터를 전부 서버에 upsert 했음
    # 문제: 클라이언트마다 옛 로컬 캐시로 서버를 덮어써 개발자가 수정한
    #       최신 셀렉터가 롤백되는 현상 발생 (세화 2026-04-20 사례)
    # 방침: 셀렉터 기여는 "진단 버튼" / "AI 분석 성공" 등 명시적 경로만 허용.
    #       주기적 대량 upsert 는 제거.


def sync_cloud_to_local():
    """서버에서 최신 데이터를 로컬로 동기화한다 (앱 시작 시 1회)."""
    if not is_enabled():
        return

    data_dir = paths.get_data_dir()

    # 1) 약품 캐시 보강 - 서버에만 있는 약품을 로컬에 추가
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
    """Upload then download sync."""
    try:
        sync_local_to_cloud()
        sync_cloud_to_local()
        print("[클라우드] 동기화 완료")
    except Exception as e:
        print(f"[클라우드] 동기화 실패: {e}")


# ────────────────────── 구조 진단 업로드 ──────────────────────

def upload_structure_analysis(
    wid: str, name: str, url: str, analysis: dict
) -> bool:
    """도매상 주문 페이지 DOM 구조 진단 결과를 error_logs에 업로드한다.

    Claude가 Supabase에서 읽어 수동 셀렉터 주입에 활용한다.
    """
    if not is_enabled():
        return False
    try:
        from core.version import VERSION
        pharmacy_code = ""
        try:
            from core.auth import get_activation_code
            pharmacy_code = get_activation_code() or ""
        except Exception:
            pass

        analysis_json = json.dumps(analysis, ensure_ascii=False)
        # log_tail 컬럼이 큰 JSON 받도록 제한을 넉넉히 (30k char)
        payload = {
            "pharmacy_code": pharmacy_code,
            "version": VERSION,
            "level": "STRUCTURE_ANALYSIS",
            "message": f"{name} ({wid}) 구조 진단",
            "context": {"wid": wid, "name": name, "url": url},
            "log_tail": analysis_json[:500000],
        }
        r = requests.post(
            _api_url("error_logs"),
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        return 200 <= r.status_code < 300
    except Exception as e:
        print(f"[구조 진단] 업로드 실패: {e}")
        return False
