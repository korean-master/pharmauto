"""SQL Server 연결 문자열 빌더 — Windows 인증 / SQL 인증 통합.

settings.json의 `db` 섹션 예:
  Windows 인증 (기본):
    {"server": "...", "database": "...", "driver": "SQL Server"}
  SQL 인증:
    {"server": "...", "database": "...", "driver": "SQL Server",
     "auth": "sql", "username": "pharmauto_ro", "password": "ENC:..."}

password는 core.crypto.encrypt 로 암호화된 문자열이어야 한다.
"""

from core.crypto import decrypt


def build_conn_str(db: dict, include_db: bool = True) -> str:
    """settings.json의 db 섹션에서 pyodbc 연결 문자열을 생성한다.

    Args:
        db: db 설정 dict
        include_db: DATABASE=... 포함 여부 (DB 탐색 단계에선 False)
    """
    driver = (db.get("driver") or "SQL Server").strip()
    server = (db.get("server") or "localhost").strip()
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
    ]
    if include_db:
        database = (db.get("database") or "").strip()
        if database:
            parts.append(f"DATABASE={database}")

    auth = (db.get("auth") or "windows").lower()
    if auth == "sql":
        username = (db.get("username") or "").strip()
        # password_plain (평문, 임시 사용)이 있으면 그대로, 없으면 password 복호화
        plain = db.get("password_plain")
        if plain is not None:
            password = plain
        else:
            password_enc = db.get("password") or ""
            password = decrypt(password_enc) if password_enc else ""
        parts.append(f"UID={username}")
        parts.append(f"PWD={password}")
    else:
        parts.append("Trusted_Connection=yes")

    parts.append("ApplicationIntent=ReadOnly")
    return ";".join(parts) + ";"
