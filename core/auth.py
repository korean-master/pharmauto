"""인증 모듈 — 활성화 코드 검증 + 향후 로그인 확장 지점.

모든 인증 로직은 이 모듈을 통해서만 한다.
나중에 서버 로그인으로 전환할 때 이 파일만 수정하면 된다.

현재: 활성화 코드 방식 (오프라인 검증 + 온라인 검증 옵션)
향후: 서버 로그인 방식 (회원가입 → 관리자 승인 → 로그인)
"""

import hashlib
import json
import os
from datetime import datetime

from core import paths

# 활성화 코드 시드 (이 값으로 코드를 생성/검증)
# 코드 형식: PHARMA-XXXX-XXXX (대문자+숫자 8자리)
_CODE_SECRET = "PharmAuto2026BetaKey"


# ────────────────────── 코드 생성 (개발자용) ──────────────────────

def generate_code(pharmacy_name: str = "", memo: str = "") -> str:
    """활성화 코드를 생성한다 (개발자가 테스터에게 발급할 때 사용).

    Args:
        pharmacy_name: 약국명 (메모용)
        memo: 추가 메모

    Returns:
        "PHARMA-XXXX-XXXX" 형식의 활성화 코드
    """
    # 유니크한 시드 생성
    seed = f"{_CODE_SECRET}:{pharmacy_name}:{memo}:{datetime.now().isoformat()}"
    h = hashlib.sha256(seed.encode()).hexdigest().upper()

    # 코드 형식: PHARMA-XXXX-XXXX
    code = f"PHARMA-{h[:4]}-{h[4:8]}"
    return code


def generate_codes(count: int = 10) -> list[dict]:
    """여러 개의 활성화 코드를 일괄 생성한다.

    Returns:
        [{"code": "PHARMA-XXXX-XXXX", "created_at": "...", "used": False}, ...]
    """
    codes = []
    for i in range(count):
        seed = f"{_CODE_SECRET}:batch:{i}:{datetime.now().isoformat()}"
        h = hashlib.sha256(seed.encode()).hexdigest().upper()
        codes.append({
            "code": f"PHARMA-{h[:4]}-{h[4:8]}",
            "created_at": datetime.now().isoformat(),
            "used": False,
        })
    return codes


# ────────────────────── 코드 검증 ──────────────────────

_VALID_CODES = {"00001234"}  # 유효한 접속 코드 목록


def verify_code(code: str) -> dict:
    """접속 코드를 검증한다.

    Returns:
        {"valid": bool, "message": str}
    """
    code = code.strip()

    if not code:
        return {"valid": False, "message": "접속 코드를 입력하세요"}

    if code in _VALID_CODES:
        return {"valid": True, "message": "인증 성공"}

    return {"valid": False, "message": "접속 코드가 올바르지 않습니다"}


# ────────────────────── 활성화 상태 관리 ──────────────────────

def is_activated() -> bool:
    """앱이 활성화되었는지 확인한다."""
    p = paths.auth_path()
    if not os.path.exists(p):
        return False
    try:
        with open(p, "r", encoding="utf-8") as f:
            auth = json.load(f)
        return auth.get("activated", False)
    except Exception:
        return False


def get_auth_info() -> dict:
    """현재 인증 정보를 반환한다."""
    p = paths.auth_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def activate(code: str) -> dict:
    """활성화 코드로 앱을 활성화한다.

    Returns:
        {"success": bool, "message": str}
    """
    result = verify_code(code)
    if not result["valid"]:
        return {"success": False, "message": result["message"]}

    auth = {
        "activated": True,
        "code": code.strip(),
        "activated_at": datetime.now().isoformat(),
        "license_type": "beta",
    }

    with open(paths.auth_path(), "w", encoding="utf-8") as f:
        json.dump(auth, f, ensure_ascii=False, indent=2)

    return {"success": True, "message": "활성화 성공"}


def deactivate():
    """활성화를 해제한다."""
    p = paths.auth_path()
    if os.path.exists(p):
        os.remove(p)


# ────────────────────── 향후 서버 로그인 확장 지점 ──────────────────────

# def _verify_online(code: str) -> dict | None:
#     """서버에서 활성화 코드를 검증한다.
#
#     Returns:
#         {"valid": bool, "message": str} or None (서버 연결 실패 시)
#     """
#     try:
#         import requests
#         resp = requests.post(
#             "https://api.pharmauto.kr/auth/verify",
#             json={"code": code},
#             timeout=5,
#         )
#         data = resp.json()
#         return {"valid": data["valid"], "message": data["message"]}
#     except Exception:
#         return None  # 오프라인 폴백
#
#
# def login(user_id: str, password: str) -> dict:
#     """서버 로그인 (향후 구현).
#
#     Returns:
#         {"success": bool, "message": str, "token": str}
#     """
#     try:
#         import requests
#         resp = requests.post(
#             "https://api.pharmauto.kr/auth/login",
#             json={"user_id": user_id, "password": password},
#             timeout=5,
#         )
#         data = resp.json()
#         if data.get("success"):
#             auth = {
#                 "activated": True,
#                 "user_id": user_id,
#                 "user_name": data.get("user_name", ""),
#                 "token": data.get("token", ""),
#                 "license_type": data.get("license_type", "standard"),
#                 "activated_at": datetime.now().isoformat(),
#             }
#             with open(AUTH_PATH, "w", encoding="utf-8") as f:
#                 json.dump(auth, f, ensure_ascii=False, indent=2)
#         return data
#     except Exception as e:
#         return {"success": False, "message": f"서버 연결 실패: {e}"}
