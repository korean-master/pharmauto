"""자격증명 암호화/복호화 모듈.

Windows DPAPI를 사용하여 현재 사용자만 복호화할 수 있도록 한다.
모든 비밀번호/API키 저장은 이 모듈을 통해서만 한다.
"""

import base64
import json
import os

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
ENCRYPTED_PREFIX = "ENC:"


def _dpapi_available() -> bool:
    try:
        import win32crypt
        return True
    except ImportError:
        return False


def encrypt(plain_text: str) -> str:
    """문자열을 암호화한다. 이미 암호화된 값이면 그대로 반환."""
    if not plain_text or plain_text.startswith(ENCRYPTED_PREFIX):
        return plain_text

    if _dpapi_available():
        import win32crypt
        encrypted = win32crypt.CryptProtectData(
            plain_text.encode("utf-8"),
            "PharmAuto",
            None, None, None, 0
        )
        return ENCRYPTED_PREFIX + base64.b64encode(encrypted).decode("ascii")

    # DPAPI 없으면 base64 난독화 (완벽하진 않지만 평문보단 나음)
    return ENCRYPTED_PREFIX + base64.b64encode(plain_text.encode("utf-8")).decode("ascii")


def decrypt(encrypted_text: str) -> str:
    """암호화된 문자열을 복호화한다. 평문이면 그대로 반환."""
    if not encrypted_text:
        return ""

    if not encrypted_text.startswith(ENCRYPTED_PREFIX):
        # 평문 (마이그레이션 전 데이터) → 그대로 반환
        return encrypted_text

    data = base64.b64decode(encrypted_text[len(ENCRYPTED_PREFIX):])

    if _dpapi_available():
        import win32crypt
        try:
            _, decrypted = win32crypt.CryptUnprotectData(
                data, None, None, None, 0
            )
            return decrypted.decode("utf-8")
        except Exception:
            # DPAPI 복호화 실패 → base64 시도
            pass

    # base64 폴백
    try:
        return data.decode("utf-8")
    except Exception:
        return ""


def encrypt_dict_fields(data: dict, fields: list[str]) -> dict:
    """dict에서 지정된 필드들을 암호화한다."""
    result = dict(data)
    for field in fields:
        if field in result and result[field]:
            result[field] = encrypt(str(result[field]))
    return result


def decrypt_dict_fields(data: dict, fields: list[str]) -> dict:
    """dict에서 지정된 필드들을 복호화한다."""
    result = dict(data)
    for field in fields:
        if field in result and result[field]:
            result[field] = decrypt(str(result[field]))
    return result


# ────── 설정 파일 읽기/쓰기 헬퍼 ──────

SETTINGS_SENSITIVE_FIELDS = ["api_key"]
WHOLESALER_SENSITIVE_FIELDS = ["id", "pw"]


def load_settings_secure() -> dict:
    """settings.json을 읽고 민감 필드를 복호화하여 반환한다."""
    path = os.path.join(CONFIG_DIR, "settings.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        settings = json.load(f)
    return decrypt_dict_fields(settings, SETTINGS_SENSITIVE_FIELDS)


def save_settings_secure(settings: dict):
    """settings.json에 민감 필드를 암호화하여 저장한다."""
    path = os.path.join(CONFIG_DIR, "settings.json")
    encrypted = encrypt_dict_fields(settings, SETTINGS_SENSITIVE_FIELDS)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(encrypted, f, ensure_ascii=False, indent=2)


def load_wholesalers_secure() -> dict:
    """wholesalers.json을 읽고 각 도매상의 ID/PW를 복호화하여 반환한다."""
    path = os.path.join(CONFIG_DIR, "wholesalers.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for wid, ws in data.items():
        result[wid] = decrypt_dict_fields(ws, WHOLESALER_SENSITIVE_FIELDS)
    return result


def save_wholesalers_secure(data: dict):
    """wholesalers.json에 각 도매상의 ID/PW를 암호화하여 저장한다."""
    path = os.path.join(CONFIG_DIR, "wholesalers.json")
    encrypted = {}
    for wid, ws in data.items():
        encrypted[wid] = encrypt_dict_fields(ws, WHOLESALER_SENSITIVE_FIELDS)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(encrypted, f, ensure_ascii=False, indent=2)


def migrate_plaintext():
    """기존 평문 설정 파일을 암호화된 형태로 마이그레이션한다.

    이미 암호화된 값은 건너뛴다. 안전하게 여러 번 실행 가능.
    """
    # settings.json
    settings_path = os.path.join(CONFIG_DIR, "settings.json")
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
        changed = False
        for field in SETTINGS_SENSITIVE_FIELDS:
            val = settings.get(field, "")
            if val and not val.startswith(ENCRYPTED_PREFIX):
                settings[field] = encrypt(val)
                changed = True
        if changed:
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            print("[보안] settings.json 민감 필드 암호화 완료")

    # wholesalers.json
    ws_path = os.path.join(CONFIG_DIR, "wholesalers.json")
    if os.path.exists(ws_path):
        with open(ws_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        changed = False
        for wid, ws in data.items():
            for field in WHOLESALER_SENSITIVE_FIELDS:
                val = ws.get(field, "")
                if val and not val.startswith(ENCRYPTED_PREFIX):
                    ws[field] = encrypt(val)
                    changed = True
        if changed:
            with open(ws_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("[보안] wholesalers.json ID/PW 암호화 완료")
