"""이팜 SQL Server DB에서 처방 데이터를 읽는 모듈.

모든 쿼리는 파라미터 바인딩(?)을 사용하여 SQL Injection을 방지한다.
"""

import json
import os
from datetime import datetime, timedelta

import pyodbc

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.json")


def _load_settings():
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


_conn_cache = None


def get_connection():
    """DB 연결을 반환한다. 연결이 살아있으면 재사용한다."""
    global _conn_cache
    try:
        if _conn_cache and not _conn_cache.closed:
            _conn_cache.execute("SELECT 1")
            return _conn_cache
    except Exception:
        _conn_cache = None

    settings = _load_settings()
    db = settings.get("db", {})
    server = db.get("server", "localhost")
    database = db.get("database", "eP_PHARM")
    driver = db.get("driver", "SQL Server")

    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"Trusted_Connection=yes;"
    )
    print(f"[DB] 연결: {server}/{database}")
    _conn_cache = pyodbc.connect(conn_str, timeout=5)
    return _conn_cache


def _fetch_drug_names(cursor, codes: list[str]) -> dict[str, str]:
    """Dur2Result 테이블에서 보험코드→약품명 매핑을 가져온다."""
    if not codes:
        return {}

    placeholders = ",".join("?" for _ in codes)
    try:
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
        """, codes)
        result = {str(row[0]).strip(): str(row[1]).strip() for row in cursor.fetchall()}
        found = len(result)
        print(f"[DB] 약품명 조회: {found}/{len(codes)}건 (Dur2Result)")
        return result
    except Exception as e:
        print(f"[DB] 약품명 조회 실패: {e}")
        return {}


def fetch_prescriptions(time_range: str = "all",
                        start_time: str = "", end_time: str = ""):
    """실제 출고 데이터를 조회한다 (대체조제 반영).

    STOCKDATE 테이블에서 실제 나간 약품을 기준으로 조회한다.
    시간대 필터가 있으면 prsdrug+prescript 조인으로 해당 시간대에
    조제된 보험코드만 필터링한다.
    """
    today = datetime.now().strftime("%Y%m%d")
    print(f"[DB] 출고 조회 - 날짜: {today}, 시간대: {time_range}, "
          f"커스텀: {start_time}~{end_time}")

    conn = get_connection()
    cursor = conn.cursor()

    # 시간 범위 결정
    if start_time or end_time:
        t_start = start_time or "0000"
        t_end = end_time or "2359"
    elif time_range == "morning":
        t_start, t_end = "0900", "1300"
    elif time_range == "afternoon":
        t_start, t_end = "1300", "1900"
    else:
        t_start, t_end = "", ""

    if not t_start and not t_end:
        # 시간대 필터 없음 → STOCKDATE에서 바로 조회
        cursor.execute("""
            SELECT SD_ISCODE, SUM(SD_DAYAMT2) as total_out
            FROM STOCKDATE
            WHERE SD_DATE = ? AND SD_DAYAMT2 > 0
            GROUP BY SD_ISCODE
            ORDER BY total_out DESC
        """, (today,))
    else:
        today_prefix = today + "%"
        cursor.execute("""
            SELECT SD_ISCODE, SUM(SD_DAYAMT2) as total_out
            FROM STOCKDATE
            WHERE SD_DATE = ? AND SD_DAYAMT2 > 0
              AND SD_ISCODE IN (
                  SELECT DISTINCT d.pd_iscode
                  FROM prsdrug d
                  INNER JOIN prescript p ON d.pd_code = p.ps_code
                  WHERE d.pd_code LIKE ?
                    AND p.ps_dostime >= ?
                    AND p.ps_dostime < ?
              )
            GROUP BY SD_ISCODE
            ORDER BY total_out DESC
        """, (today, today_prefix, t_start, t_end))

    rows = cursor.fetchall()

    results = []
    for row in rows:
        code = str(row[0]).strip()
        results.append({
            "insurance_code": code,
            "total_qty": int(row[1]),
        })

    print(f"[DB] 출고 조회 완료: {len(results)}건 (대체조제 반영)")
    if results:
        print(f"[DB] 샘플: {results[0]}")
    return results


def fetch_all_prescribed_drugs(months: int = 3) -> list[dict]:
    """최근 N개월 내 출고 이력이 있는 약품의 보험코드와 약품명을 조회한다."""
    print(f"[DB] 처방 약품 목록 조회 중 (최근 {months}개월)...")
    conn = get_connection()
    cursor = conn.cursor()

    if months > 0:
        now = datetime.now()
        year = now.year
        month = now.month - months
        while month <= 0:
            month += 12
            year -= 1
        since_date = f"{year}{month:02d}01"

        cursor.execute("""
            SELECT SD_ISCODE, SUM(SD_DAYAMT2) as total_out
            FROM STOCKDATE
            WHERE SD_DAYAMT2 > 0 AND SD_DATE >= ?
            GROUP BY SD_ISCODE
            ORDER BY total_out DESC
        """, (since_date,))
    else:
        cursor.execute("""
            SELECT SD_ISCODE, SUM(SD_DAYAMT2) as total_out
            FROM STOCKDATE
            WHERE SD_DAYAMT2 > 0
            GROUP BY SD_ISCODE
            ORDER BY total_out DESC
        """)

    rows = cursor.fetchall()

    codes = [str(row[0]).strip() for row in rows]
    qty_map = {str(row[0]).strip(): int(row[1]) for row in rows}

    # 약품명 조회
    name_map = _fetch_drug_names(cursor, codes)

    results = []
    for code in codes:
        results.append({
            "insurance_code": code,
            "drug_name": name_map.get(code, ""),
            "total_qty": qty_map.get(code, 0),
        })

    print(f"[DB] 처방 약품 ({months}개월): {len(results)}건")
    return results


def fetch_last_month_usage():
    """지난달 약품별 실제 출고량을 조회한다 (STOCKDATE 기반)."""
    now = datetime.now()
    if now.month == 1:
        year, month = now.year - 1, 12
    else:
        year, month = now.year, now.month - 1

    yyyymm = f"{year}{month:02d}"
    print(f"[DB] 전월 출고량 조회 - {yyyymm}")

    yyyymm_prefix = yyyymm + "%"

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SD_ISCODE, SUM(SD_DAYAMT2) as total_out
        FROM STOCKDATE
        WHERE SD_DATE LIKE ? AND SD_DAYAMT2 > 0
        GROUP BY SD_ISCODE
    """, (yyyymm_prefix,))
    rows = cursor.fetchall()

    result = {str(row[0]).strip(): int(row[1]) for row in rows}
    print(f"[DB] 전월 출고량: {len(result)}건")
    return result


def fetch_drug_usage(insurance_code: str) -> dict:
    """특정 약품의 기간별 사용량을 조회한다.

    Returns:
        {"this_week": int, "this_month": int, "last_month": int}
    """
    now = datetime.now()
    today = now.strftime("%Y%m%d")

    # 이번주 월요일
    monday = now - timedelta(days=now.weekday())
    week_start = monday.strftime("%Y%m%d")

    # 이번달
    month_start = now.strftime("%Y%m") + "01"

    # 저번달
    if now.month == 1:
        lm_year, lm_month = now.year - 1, 12
    else:
        lm_year, lm_month = now.year, now.month - 1
    last_month_prefix = f"{lm_year}{lm_month:02d}"

    conn = get_connection()
    cursor = conn.cursor()

    result = {"this_week": 0, "this_month": 0, "last_month": 0}

    # 이번주
    cursor.execute("""
        SELECT ISNULL(SUM(SD_DAYAMT2), 0)
        FROM STOCKDATE
        WHERE SD_ISCODE = ? AND SD_DATE >= ? AND SD_DAYAMT2 > 0
    """, (insurance_code, week_start))
    row = cursor.fetchone()
    if row:
        result["this_week"] = int(row[0])

    # 이번달
    cursor.execute("""
        SELECT ISNULL(SUM(SD_DAYAMT2), 0)
        FROM STOCKDATE
        WHERE SD_ISCODE = ? AND SD_DATE >= ? AND SD_DAYAMT2 > 0
    """, (insurance_code, month_start))
    row = cursor.fetchone()
    if row:
        result["this_month"] = int(row[0])

    # 저번달
    cursor.execute("""
        SELECT ISNULL(SUM(SD_DAYAMT2), 0)
        FROM STOCKDATE
        WHERE SD_ISCODE = ? AND SD_DATE LIKE ? AND SD_DAYAMT2 > 0
    """, (insurance_code, last_month_prefix + "%"))
    row = cursor.fetchone()
    if row:
        result["last_month"] = int(row[0])

    return result
