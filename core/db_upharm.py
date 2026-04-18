"""유팜(UPHARM/atpharm) 전용 DB 쿼리 모듈.

유팜 스키마는 이팜과 달리 한글 테이블/컬럼명을 사용한다.
- 처방: `tbl처방약품` (청구코드, 약품명, 약품ID)
- 조제: `tbl조제약품` (약품ID, 내방일, 소모량, 판매량, 조제판매ID)
- 처방전: `tbl처방전` (조제판매ID, 내방일)
- 약품 마스터: `CD약품정보` (약품ID, 약품코드, 약품명, 현재고)

보험코드는 `tbl처방약품.청구코드` 를 기준으로 삼는다 (이팜 SD_ISCODE 와 동일 의미).
"""

from datetime import datetime, timedelta


def _fetch_drug_names(cursor, codes: list[str]) -> dict[str, str]:
    """청구코드 → 약품명 매핑. tbl처방약품에서 최신 레코드 기준."""
    if not codes:
        return {}
    placeholders = ",".join("?" for _ in codes)
    try:
        cursor.execute(f"""
            SELECT 청구코드, 약품명
            FROM (
                SELECT 청구코드, 약품명,
                       ROW_NUMBER() OVER (PARTITION BY 청구코드 ORDER BY 최종수정일 DESC) AS rn
                FROM tbl처방약품
                WHERE 청구코드 IN ({placeholders})
                  AND 약품명 IS NOT NULL AND 약품명 != ''
            ) sub
            WHERE rn = 1
        """, codes)
        result = {str(row[0]).strip(): str(row[1]).strip() for row in cursor.fetchall()}
        print(f"[DB] 약품명 조회: {len(result)}/{len(codes)}건 (유팜 tbl처방약품)")
        return result
    except Exception as e:
        print(f"[DB] 약품명 조회 실패: {e}")
        return {}


def fetch_prescriptions(get_connection, time_range: str = "all",
                        start_time: str = "", end_time: str = ""):
    """오늘(또는 어제) 특정 시간대 출고 이력을 청구코드별 합계로 조회.

    tbl조제약품 의 소모량을 합산. 시간대 필터는 내방일의 시각 부분 사용.
    """
    now = datetime.now()
    if time_range == "yesterday":
        target = now - timedelta(days=1)
    else:
        target = now
    day_start = datetime(target.year, target.month, target.day)
    day_end = day_start + timedelta(days=1)

    print(f"[DB] 출고 조회 - 날짜: {day_start.strftime('%Y-%m-%d')}, "
          f"시간대: {time_range}, 커스텀: {start_time}~{end_time}")

    conn = get_connection()
    if conn is None:
        return []
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

    params = [day_start, day_end]
    time_filter = ""
    if t_start or t_end:
        ts = day_start.replace(
            hour=int(t_start[:2]) if t_start else 0,
            minute=int(t_start[2:4]) if t_start and len(t_start) >= 4 else 0,
        )
        te = day_start.replace(
            hour=int(t_end[:2]) if t_end else 23,
            minute=int(t_end[2:4]) if t_end and len(t_end) >= 4 else 59,
        )
        time_filter = " AND d.내방일 >= ? AND d.내방일 < ?"
        params.extend([ts, te])

    try:
        cursor.execute(f"""
            SELECT p.청구코드, SUM(d.소모량) AS total_out
            FROM tbl조제약품 d
            INNER JOIN tbl처방약품 p
                ON d.약품ID = p.약품ID AND d.조제판매ID = p.조제판매ID
            WHERE d.내방일 >= ? AND d.내방일 < ?
              AND d.소모량 > 0
              AND p.청구코드 IS NOT NULL AND p.청구코드 != ''
              {time_filter}
            GROUP BY p.청구코드
            ORDER BY total_out DESC
        """, params)
        rows = cursor.fetchall()
        results = [
            {"insurance_code": str(r[0]).strip(), "total_qty": int(r[1] or 0)}
            for r in rows
        ]
        print(f"[DB] 출고 조회 완료: {len(results)}건 (유팜 소모량 합계)")
        if results:
            print(f"[DB] 샘플: {results[0]}")
        return results
    except Exception as e:
        print(f"[DB] 출고 조회 실패: {e}")
        return []


def fetch_all_prescribed_drugs(get_connection, months: int = 3) -> list[dict]:
    """최근 N개월 내 조제 이력 있는 약품을 청구코드/약품명/총소모량 순으로."""
    print(f"[DB] 처방 약품 목록 조회 중 (최근 {months}개월)...")
    conn = get_connection()
    if conn is None:
        return []
    cursor = conn.cursor()

    try:
        if months > 0:
            since = datetime.now() - timedelta(days=months * 31)
            cursor.execute("""
                SELECT p.청구코드, MAX(p.약품명) AS 약품명, SUM(d.소모량) AS total
                FROM tbl조제약품 d
                INNER JOIN tbl처방약품 p
                    ON d.약품ID = p.약품ID AND d.조제판매ID = p.조제판매ID
                WHERE d.내방일 >= ?
                  AND d.소모량 > 0
                  AND p.청구코드 IS NOT NULL AND p.청구코드 != ''
                GROUP BY p.청구코드
                ORDER BY total DESC
            """, (since,))
        else:
            cursor.execute("""
                SELECT p.청구코드, MAX(p.약품명) AS 약품명, SUM(d.소모량) AS total
                FROM tbl조제약품 d
                INNER JOIN tbl처방약품 p
                    ON d.약품ID = p.약품ID AND d.조제판매ID = p.조제판매ID
                WHERE d.소모량 > 0
                  AND p.청구코드 IS NOT NULL AND p.청구코드 != ''
                GROUP BY p.청구코드
                ORDER BY total DESC
            """)
        rows = cursor.fetchall()
        results = []
        for r in rows:
            results.append({
                "insurance_code": str(r[0]).strip(),
                "drug_name": (r[1] or "").strip(),
                "total_qty": int(r[2] or 0),
            })
        print(f"[DB] 처방 약품 ({months}개월): {len(results)}건")
        return results
    except Exception as e:
        print(f"[DB] 처방 약품 조회 실패: {e}")
        return []


def fetch_last_month_usage(get_connection):
    """지난달 청구코드별 총소모량."""
    now = datetime.now()
    if now.month == 1:
        year, month = now.year - 1, 12
    else:
        year, month = now.year, now.month - 1
    start = datetime(year, month, 1)
    end = datetime(now.year, now.month, 1)
    print(f"[DB] 전월 출고량 조회 - {year}{month:02d}")

    conn = get_connection()
    if conn is None:
        return {}
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT p.청구코드, SUM(d.소모량) AS total
            FROM tbl조제약품 d
            INNER JOIN tbl처방약품 p
                ON d.약품ID = p.약품ID AND d.조제판매ID = p.조제판매ID
            WHERE d.내방일 >= ? AND d.내방일 < ?
              AND d.소모량 > 0
              AND p.청구코드 IS NOT NULL AND p.청구코드 != ''
            GROUP BY p.청구코드
        """, (start, end))
        result = {str(r[0]).strip(): int(r[1] or 0) for r in cursor.fetchall()}
        print(f"[DB] 전월 출고량: {len(result)}건")
        return result
    except Exception as e:
        print(f"[DB] 전월 출고량 조회 실패: {e}")
        return {}


def fetch_drug_usage(get_connection, insurance_code: str) -> dict:
    """특정 약품(청구코드)의 기간별 사용량."""
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_start = datetime(week_start.year, week_start.month, week_start.day)
    month_start = datetime(now.year, now.month, 1)
    if now.month == 1:
        lm_start = datetime(now.year - 1, 12, 1)
    else:
        lm_start = datetime(now.year, now.month - 1, 1)

    conn = get_connection()
    if conn is None:
        return {"this_week": 0, "this_month": 0, "last_month": 0}
    cursor = conn.cursor()
    result = {"this_week": 0, "this_month": 0, "last_month": 0}

    def _sum(since, until=None):
        if until:
            cursor.execute("""
                SELECT ISNULL(SUM(d.소모량), 0)
                FROM tbl조제약품 d
                INNER JOIN tbl처방약품 p
                    ON d.약품ID = p.약품ID AND d.조제판매ID = p.조제판매ID
                WHERE p.청구코드 = ? AND d.내방일 >= ? AND d.내방일 < ?
                  AND d.소모량 > 0
            """, (insurance_code, since, until))
        else:
            cursor.execute("""
                SELECT ISNULL(SUM(d.소모량), 0)
                FROM tbl조제약품 d
                INNER JOIN tbl처방약품 p
                    ON d.약품ID = p.약품ID AND d.조제판매ID = p.조제판매ID
                WHERE p.청구코드 = ? AND d.내방일 >= ?
                  AND d.소모량 > 0
            """, (insurance_code, since))
        row = cursor.fetchone()
        return int(row[0] or 0) if row else 0

    try:
        result["this_week"] = _sum(week_start)
        result["this_month"] = _sum(month_start)
        result["last_month"] = _sum(lm_start, month_start)
    except Exception as e:
        print(f"[DB] 약품 사용량 조회 실패 ({insurance_code}): {e}")
    return result
