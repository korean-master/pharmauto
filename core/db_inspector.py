"""DB 구조 자동 수집 — 신규 약국 프로그램 연동용.

베타 테스터 PC에서 실행하면 DB 테이블/컬럼 구조를 JSON으로 추출한다.
이 파일을 개발자에게 보내면 해당 약국 프로그램 연동을 구현할 수 있다.

사용법:
  설정 탭 → "DB 구조 내보내기" 버튼
  → db_structure_{프로그램명}.json 파일 생성
  → 이 파일을 개발자에게 전달
"""

import json
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def inspect_database(server: str, database: str, driver: str = "SQL Server") -> dict:
    """DB의 테이블/컬럼 구조를 읽기 전용으로 수집한다.

    개인정보(환자명, 주민번호 등)는 수집하지 않는다.
    테이블명, 컬럼명, 데이터 타입, 행 수만 수집한다.
    """
    import pyodbc

    result = {
        "collected_at": datetime.now().isoformat(),
        "server": server,
        "database": database,
        "tables": [],
    }

    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"Trusted_Connection=yes;"
        f"ApplicationIntent=ReadOnly;"
    )

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
            # 각 테이블의 컬럼 정보
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

            # 샘플 데이터 (컬럼명만 확인용, 개인정보 제외)
            # 처방/출고 관련 테이블의 컬럼명 패턴 확인에 사용
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


def export_structure(server: str, database: str, program_name: str,
                     driver: str = "SQL Server") -> str:
    """DB 구조를 JSON 파일로 내보낸다.

    Returns:
        저장된 파일 경로
    """
    structure = inspect_database(server, database, driver)
    structure["program"] = program_name

    os.makedirs(DATA_DIR, exist_ok=True)
    filename = f"db_structure_{program_name}.json"
    path = os.path.join(DATA_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(structure, f, ensure_ascii=False, indent=2)

    return path
