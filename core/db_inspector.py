"""DB 구조 자동 수집 — 신규 약국 프로그램 연동용.

베타 테스터 PC에서 실행하면 DB 테이블/컬럼 구조를 JSON으로 추출한다.
생성된 JSON은 로컬 파일로도 저장되고 Supabase `error_logs` 테이블에도
`level=DB_SCHEMA_EXPORT` 로 업로드되어 개발자가 바로 분석할 수 있다.

사용법:
  설정 탭 → "DB 구조 내보내기" 버튼
"""

import json
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def inspect_database(db: dict) -> dict:
    """DB의 테이블/컬럼 구조를 읽기 전용으로 수집한다.

    개인정보(환자명, 주민번호 등)는 수집하지 않는다.
    테이블명, 컬럼명, 데이터 타입, 행 수만 수집한다.

    Args:
        db: settings.json의 db 섹션 (server, database, driver, auth 등)
    """
    import pyodbc
    from core.db_conn import build_conn_str

    server = db.get("server", "")
    database = db.get("database", "")

    result = {
        "collected_at": datetime.now().isoformat(),
        "server": server,
        "database": database,
        "auth": (db.get("auth") or "windows").lower(),
        "tables": [],
    }

    conn_str = build_conn_str(db)

    try:
        conn = pyodbc.connect(conn_str, timeout=5, readonly=True)
        cursor = conn.cursor()

        # 사용자 테이블 목록
        cursor.execute("""
            SELECT t.TABLE_NAME,
                   (SELECT SUM(p.rows)
                    FROM sys.partitions p
                    JOIN sys.tables st ON p.object_id = st.object_id
                    WHERE st.name = t.TABLE_NAME AND p.index_id IN (0,1)
                   ) as row_count
            FROM INFORMATION_SCHEMA.TABLES t
            WHERE t.TABLE_TYPE = 'BASE TABLE'
            ORDER BY t.TABLE_NAME
        """)
        tables = cursor.fetchall()

        for table_name, row_count in tables:
            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE,
                       CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
            """, (table_name,))
            columns = []
            for col_name, data_type, max_len, nullable in cursor.fetchall():
                columns.append({
                    "name": col_name,
                    "type": data_type,
                    "max_length": max_len,
                    "nullable": nullable,
                })

            sample_columns = [c["name"] for c in columns]

            result["tables"].append({
                "name": table_name,
                "row_count": int(row_count) if row_count else 0,
                "column_count": len(columns),
                "columns": columns,
                "column_names": sample_columns,
            })

        conn.close()
        result["table_count"] = len(result["tables"])

    except Exception as e:
        result["error"] = str(e)

    return result


def export_structure(db: dict, program_name: str) -> tuple[str, bool]:
    """DB 구조를 수집해 로컬 JSON 저장 + Supabase 업로드.

    Returns:
        (저장된 로컬 파일 경로, 서버 업로드 성공 여부)
    """
    structure = inspect_database(db)
    structure["program"] = program_name

    os.makedirs(DATA_DIR, exist_ok=True)
    filename = f"db_structure_{program_name}.json"
    path = os.path.join(DATA_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(structure, f, ensure_ascii=False, indent=2)

    # Supabase 업로드 (개발자 즉시 분석 가능하도록)
    uploaded = _upload_to_supabase(structure, program_name)

    return path, uploaded


def _upload_to_supabase(structure: dict, program_name: str) -> bool:
    """error_logs 테이블에 level=DB_SCHEMA_EXPORT 로 업로드."""
    try:
        from core.cloud import is_enabled, _api_url, _headers
        from core.version import VERSION
        import requests

        if not is_enabled():
            return False

        pharmacy_code = ""
        try:
            from core.auth import get_activation_code
            pharmacy_code = get_activation_code() or ""
        except Exception:
            pass

        schema_json = json.dumps(structure, ensure_ascii=False)
        payload = {
            "pharmacy_code": pharmacy_code,
            "version": VERSION,
            "level": "DB_SCHEMA_EXPORT",
            "message": f"{program_name} DB 구조 내보내기 "
                       f"({structure.get('table_count', 0)}개 테이블)",
            "context": {
                "program": program_name,
                "database": structure.get("database", ""),
                "auth": structure.get("auth", "windows"),
                "error": structure.get("error", ""),
            },
            "log_tail": schema_json[:500000],
        }
        r = requests.post(
            _api_url("error_logs"),
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        return 200 <= r.status_code < 300
    except Exception as e:
        print(f"[DB 구조] 업로드 실패: {e}")
        return False
