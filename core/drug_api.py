"""공공 API로 약품 정보(약품명/규격)를 조회하는 모듈.

앱 시작 시 drug_cache.json을 메모리에 로드하고,
캐시 히트 시 API 호출 없이 즉시 반환한다.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.json")
CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "drug_cache.json")

# ── 메모리 캐시 (앱 수명 동안 유지) ──
_cache: dict | None = None

API_TIMEOUT = 10
API_RETRIES = 3

# ── 내장 API 키 (난독화) ──
_K = None


def _get_builtin_key() -> str:
    """난독화된 내장 API 키를 복원한다. 호출 시에만 조립."""
    global _K
    if _K:
        return _K
    import base64
    _p = [
        "3!Lb`2QLS0G4_37%J@3<ERhN)I",
        "XR-)jGo^fL4%n#8mGQ-RKIy3^Vg",
        "{cNnGB?Dp_g>)s#CU)2<7)x(XLb",
    ]
    _q = [
        "YW|ClWgIsNQ^!S8{?84NAM<MxT",
        "?&xAy{zVYBITe5d&J)mX4^p&#Nw",
        "SZcxC3IOmA3hu<&0(=E`q@jc+G;",
    ]
    _d = base64.b85decode("".join(_p).encode())
    _x = base64.b85decode("".join(_q).encode())
    _K = "".join(chr(a ^ b) for a, b in zip(_d, _x))
    return _K


def _load_settings():
    from core.crypto import load_settings_secure
    return load_settings_secure()


def _ensure_cache_loaded():
    """캐시가 메모리에 없으면 파일에서 로드한다."""
    global _cache
    if _cache is None:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        else:
            _cache = {}


def _save_cache():
    """메모리 캐시를 파일에 저장한다."""
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)


def preload_cache():
    """앱 시작 시 호출. 캐시를 메모리에 미리 로드한다."""
    _ensure_cache_loaded()
    print(f"[캐시] drug_cache.json 로드 완료: {len(_cache)}건")


def _cloud_upload_drug(insurance_code: str, drug_name: str, spec: str = ""):
    """약품 정보를 클라우드에 백그라운드 업로드."""
    import threading
    def _upload():
        try:
            from core.cloud import upload_drug
            upload_drug(insurance_code, drug_name, spec)
        except Exception:
            pass
    threading.Thread(target=_upload, daemon=True).start()


def get_cache_count() -> int:
    _ensure_cache_loaded()
    return len(_cache)


def get_drug_name(insurance_code: str) -> str:
    """보험코드로 약품명을 조회한다. (통합 조회 함수)

    조회 순서:
      1. 메모리/디스크 캐시 (drug_cache.json)
      2. DB Dur2Result 테이블
      3. 공공 API
      4. 못 찾으면 보험코드 그대로 반환

    한번 찾은 이름은 캐시에 저장하여 이후 즉시 반환.
    """
    _ensure_cache_loaded()

    # 1. 캐시
    if insurance_code in _cache:
        name = _cache[insurance_code].get("drug_name", "")
        if name and name != insurance_code:
            return name

    # 2. 클라우드
    try:
        from core.cloud import fetch_drug
        cloud = fetch_drug(insurance_code)
        if cloud and cloud.get("drug_name"):
            name = cloud["drug_name"]
            _cache[insurance_code] = {"drug_name": name, "spec": cloud.get("spec", "")}
            _save_cache()
            return name
    except Exception:
        pass

    # 3. DB Dur2Result
    try:
        from core.db_reader import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 1 dr_Drugname FROM Dur2Result
            WHERE dr_isCode = ?
              AND dr_Drugname IS NOT NULL AND dr_Drugname != ''
            ORDER BY dr_Regdate DESC
        """, (insurance_code,))
        row = cursor.fetchone()
        if row:
            name = str(row[0]).strip()
            if insurance_code not in _cache:
                _cache[insurance_code] = {"drug_name": name, "spec": ""}
            else:
                _cache[insurance_code]["drug_name"] = name
            _save_cache()
            _cloud_upload_drug(insurance_code, name)
            return name
    except Exception:
        pass

    # 4. 공공 API
    info = _fetch_from_api(insurance_code)
    if info and info.get("drug_name"):
        _cloud_upload_drug(insurance_code, info["drug_name"], info.get("spec", ""))
        return info["drug_name"]

    # 5. 못 찾음
    return insurance_code


def get_drug_names(codes: list[str]) -> dict[str, str]:
    """여러 보험코드의 약품명을 일괄 조회한다.

    get_drug_name()과 동일한 조회 순서를 사용하되,
    DB 조회를 한번에 처리하여 성능을 최적화한다.
    """
    _ensure_cache_loaded()
    result = {}
    db_needed = []

    # 1. 캐시에서 먼저
    for code in codes:
        if code in _cache:
            name = _cache[code].get("drug_name", "")
            if name and name != code:
                result[code] = name
                continue
        db_needed.append(code)

    if not db_needed:
        return result

    # 2. DB Dur2Result 일괄 조회
    api_needed = []
    try:
        from core.db_reader import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in db_needed)
        cursor.execute(f"""
            SELECT dr_isCode, dr_Drugname
            FROM (
                SELECT dr_isCode, dr_Drugname,
                       ROW_NUMBER() OVER (PARTITION BY dr_isCode ORDER BY dr_Regdate DESC) AS rn
                FROM Dur2Result
                WHERE dr_isCode IN ({placeholders})
                  AND dr_Drugname IS NOT NULL AND dr_Drugname != ''
            ) sub
            WHERE rn = 1
        """, db_needed)
        for row in cursor.fetchall():
            code = str(row[0]).strip()
            name = str(row[1]).strip()
            result[code] = name
            if code not in _cache:
                _cache[code] = {"drug_name": name, "spec": ""}
            else:
                _cache[code]["drug_name"] = name
    except Exception:
        pass

    # DB에서도 못 찾은 코드 → API 필요
    for code in db_needed:
        if code not in result:
            api_needed.append(code)

    # 3. API 병렬 호출
    if api_needed:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {
                pool.submit(_fetch_from_api, code, False): code
                for code in api_needed
            }
            for future in as_completed(futures):
                code = futures[future]
                try:
                    info = future.result()
                    if info and info.get("drug_name"):
                        result[code] = info["drug_name"]
                except Exception:
                    pass

    # 4. 캐시 저장 (DB + API 결과 한번에)
    _save_cache()

    # 못 찾은 건 코드 그대로
    for code in codes:
        if code not in result:
            result[code] = code

    return result


def save_drug_name(insurance_code: str, drug_name: str):
    """약품명을 수기로 저장한다. 캐시에 반영."""
    _ensure_cache_loaded()
    if insurance_code in _cache:
        _cache[insurance_code]["drug_name"] = drug_name
    else:
        _cache[insurance_code] = {"drug_name": drug_name, "spec": ""}
    _save_cache()


def lookup_drug(insurance_code: str) -> dict | None:
    """보험코드로 약품명/규격을 조회한다.

    캐시에 있으면 즉시 반환, 없으면 API 호출 (3회 재시도).

    Returns:
        {"drug_name": str, "spec": str} 또는 None
    """
    _ensure_cache_loaded()

    # 캐시 히트
    if insurance_code in _cache:
        return _cache[insurance_code]

    # API 호출
    return _fetch_from_api(insurance_code)


# API 키 없을 때 세션 내 반복 호출 방지
_api_disabled = False


def _fetch_from_api(insurance_code: str, save_to_disk: bool = True) -> dict | None:
    """API에서 약품 정보를 조회하고 캐시에 저장한다."""
    global _api_disabled
    if _api_disabled:
        return None

    import xml.etree.ElementTree as ET

    settings = _load_settings()
    api_key = settings.get("api_key", "") or _get_builtin_key()
    if not api_key:
        _api_disabled = True
        print("[API] API 키 없음 - API 조회 건너뜀")
        return None

    api_url = settings.get(
        "api_url",
        "https://apis.data.go.kr/B551182/dgamtCrtrInfoService1.2/getDgamtList",
    )
    params = {
        "serviceKey": api_key,
        "mdsCd": insurance_code,
        "numOfRows": 1,
    }

    for attempt in range(1, API_RETRIES + 1):
        try:
            resp = requests.get(api_url, params=params, timeout=API_TIMEOUT)
            # 401/403은 키 문제 — 재시도 무의미, 세션 내 전체 차단
            if resp.status_code in (401, 403):
                _api_disabled = True
                print(f"[API] 인증 실패({resp.status_code}) - 이후 API 조회 중단")
                return None

            resp.raise_for_status()

            root = ET.fromstring(resp.text)

            item = root.find(".//item")
            if item is not None:
                drug_name = item.findtext("itmNm", "")
                spec = item.findtext("unit", "")
                result = {"drug_name": drug_name, "spec": spec}

                _cache[insurance_code] = result
                if save_to_disk:
                    _save_cache()

                return result

            return None

        except Exception as e:
            if attempt < API_RETRIES:
                time.sleep(0.3)
            else:
                print(f"[API 실패] {insurance_code}: {e} ({API_RETRIES}회 시도)")

    return None


def batch_lookup(insurance_codes: list[str],
                 progress_callback=None) -> tuple[dict, int, int]:
    """여러 보험코드를 일괄 조회한다.

    Args:
        insurance_codes: 조회할 보험코드 리스트
        progress_callback: (message: str) -> None

    Returns:
        (results_dict, cache_hits, api_calls)
    """
    _ensure_cache_loaded()

    results = {}
    cache_hits = 0
    api_needed = []

    # 1단계: 캐시에서 먼저 가져오기
    for code in insurance_codes:
        if code in _cache:
            results[code] = _cache[code]
            cache_hits += 1
        else:
            api_needed.append(code)

    total = len(insurance_codes)
    api_count = len(api_needed)

    if progress_callback:
        progress_callback(
            f"약품 정보 조회 중... (캐시 {cache_hits}건 / API {api_count}건 조회 중)"
        )

    # 2단계: 캐시에 없는 것만 API 병렬 호출 (최대 5개 동시)
    api_success = 0
    if api_needed:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {
                pool.submit(_fetch_from_api, code, False): code
                for code in api_needed
            }
            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                code = futures[future]
                try:
                    info = future.result()
                    if info:
                        results[code] = info
                        api_success += 1
                except Exception:
                    pass

                if progress_callback and done_count % 3 == 0:
                    progress_callback(
                        f"약품 정보 조회 중... (API {done_count}/{api_count})"
                    )

        # 파일 저장 1회
        _save_cache()

    # 히트율 출력
    hit_rate = round(cache_hits / total * 100) if total > 0 else 0
    print(
        f"[캐시] 총 {total}건 - "
        f"캐시 {cache_hits}건({hit_rate}%) / "
        f"API {api_count}건(성공 {api_success})"
    )

    return results, cache_hits, api_count
