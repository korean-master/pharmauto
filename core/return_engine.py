"""반품 처리 엔진."""

import os
import sqlite3
from datetime import datetime

from core import paths


def _db_path() -> str:
    return os.path.join(paths.get_data_dir(), "order_history.db")


def _get_db():
    conn = sqlite3.connect(_db_path())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS return_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_date TEXT NOT NULL,
            drug_name TEXT NOT NULL,
            lot_number TEXT NOT NULL,
            insurance_code TEXT DEFAULT '',
            qty INTEGER DEFAULT 0,
            wholesaler_id TEXT NOT NULL,
            wholesaler_name TEXT NOT NULL,
            original_order_date TEXT,
            status TEXT DEFAULT 'completed',
            created_at TEXT NOT NULL
        )
    """)
    # 기존 테이블에 컬럼 없으면 추가
    for col, default in [
        ("insurance_code", "''"),
        ("qty", "0"),
    ]:
        try:
            conn.execute(
                f"ALTER TABLE return_history ADD COLUMN {col} TEXT DEFAULT {default}"
            )
        except Exception:
            pass
    conn.commit()
    return conn


def _tokenize_query(query: str) -> list[str]:
    """검색어를 토큰으로 분리한다.

    예: "자누메트50/1000" → ["자누메트", "50", "1000"]
        "아모잘탄 5/100"  → ["아모잘탄", "5", "100"]
    한글/영문과 숫자 경계, 슬래시, 공백 기준으로 분리.
    """
    import re
    # 한글/영문과 숫자 경계에서 분리, 슬래시도 분리
    expanded = re.sub(r'([가-힣a-zA-Z])(\d)', r'\1 \2', query)
    expanded = re.sub(r'(\d)([가-힣a-zA-Z])', r'\1 \2', expanded)
    tokens = re.split(r'[\s/]+', expanded)
    return [t for t in tokens if t]


def find_orders_for_return(drug_name: str) -> list[dict]:
    """약품명으로 주문 이력을 검색한다. 최근 주문 순으로 최대 20건.

    검색어를 토큰으로 분리하여 각 토큰이 모두 포함된 결과만 반환.
    예: "자누메트50/1000" → 자누메트, 50, 1000 모두 포함된 약품.
    """
    db_path = _db_path()
    if not os.path.exists(db_path):
        return []

    tokens = _tokenize_query(drug_name)
    if not tokens:
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 각 토큰에 대해 LIKE 조건 생성
    where_clauses = " AND ".join("drug_name LIKE ?" for _ in tokens)
    params = [f"%{t}%" for t in tokens]

    rows = conn.execute(
        f"""SELECT * FROM order_history
            WHERE {where_clauses}
            ORDER BY order_date DESC
            LIMIT 20""",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_return(drug_name: str, lot_number: str, insurance_code: str,
                  qty: int, wholesaler_id: str, wholesaler_name: str,
                  original_order_date: str = "") -> int:
    """반품 리스트에 항목을 추가한다. 초기 상태는 'pending'(반품 전)."""
    conn = _get_db()
    now = datetime.now()
    cursor = conn.execute(
        """INSERT INTO return_history
           (return_date, drug_name, lot_number, insurance_code, qty,
            wholesaler_id, wholesaler_name, original_order_date,
            status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (
            now.strftime("%Y-%m-%d"),
            drug_name,
            lot_number,
            insurance_code,
            qty,
            wholesaler_id,
            wholesaler_name,
            original_order_date,
            now.isoformat(),
        ),
    )
    conn.commit()
    return_id = cursor.lastrowid
    conn.close()
    return return_id


# 반품 상태: pending(반품 전) → sent(반품약 보냄) → completed(반품완료)
RETURN_STATUSES = ["pending", "sent", "completed"]
RETURN_STATUS_LABELS = {
    "pending": "반품 전",
    "sent": "반품약 보냄",
    "completed": "반품완료",
}


def update_return_status(return_id: int, status: str):
    """반품 항목의 상태를 변경한다."""
    if status not in RETURN_STATUSES:
        raise ValueError(f"유효하지 않은 상태: {status}")
    conn = _get_db()
    conn.execute(
        "UPDATE return_history SET status = ? WHERE id = ?",
        (status, return_id),
    )
    conn.commit()
    conn.close()


def get_return_list(months: int = 3) -> list[dict]:
    """반품 리스트를 월 단위로 조회한다."""
    conn = _get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT * FROM return_history
           WHERE return_date >= date('now', ?)
           ORDER BY created_at DESC""",
        (f"-{months} months",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_return(return_id: int):
    """반품 항목을 삭제한다."""
    conn = _get_db()
    conn.execute("DELETE FROM return_history WHERE id = ?", (return_id,))
    conn.commit()
    conn.close()


# ─────────────── 도매상 사이트 통합 검색 ───────────────

def _get_wholesaler_classes() -> list[tuple[str, type, dict]]:
    """등록된 모든 도매상 클래스 목록을 반환한다.

    전용 클래스가 있는 도매상은 해당 클래스, 없으면 GenericWholesaler를 사용한다.
    """
    import json
    import importlib
    from core import paths
    config_path = paths.wholesalers_path()
    if not os.path.exists(config_path):
        return []

    with open(config_path, "r", encoding="utf-8") as f:
        ws_map = json.load(f)

    from core.crypto import load_wholesalers_secure
    secure_ws = load_wholesalers_secure()

    from core.order_engine import _get_wholesaler_class

    result = []
    for wid in ws_map:
        config = secure_ws.get(wid, {})
        ws_cls = _get_wholesaler_class(wid, url=config.get("url", ""))
        if ws_cls:
            result.append((wid, ws_cls, config))
        else:
            # GenericWholesaler로 처리 (이력 검색 설정이 있는 도매상만)
            try:
                from wholesalers.generic import GenericWholesaler
                config["_wid"] = wid
                result.append((wid, GenericWholesaler, config))
            except Exception:
                continue
    return result


def search_wholesaler_history(drug_name: str, lot_number: str = "",
                              progress_callback=None) -> list[dict]:
    """모든 등록 도매상 사이트에서 입고이력을 검색한다.

    전용 클래스(백제/지오영 등)에서 실패하면 GenericWholesaler 자동 탐지로 재시도.
    전용 클래스가 없는 도매상은 처음부터 GenericWholesaler로 처리 (자가치유 적용).
    """
    all_results = []

    for wid, cls, config in _get_wholesaler_classes():
        try:
            ws = cls(config)
            if progress_callback:
                ws.set_progress_callback(progress_callback)
            results = ws.search_history(drug_name, lot_number, headless=True)
            all_results.extend(results)
        except Exception as e:
            if progress_callback:
                progress_callback(f"{wid} 검색 실패: {e}")

            # 전용 클래스 실패 → GenericWholesaler 자동 탐지로 재시도
            from wholesalers.generic import GenericWholesaler
            if cls is not GenericWholesaler:
                try:
                    if progress_callback:
                        progress_callback(f"{wid} 자동 탐지 모드로 재시도...")
                    fallback_config = dict(config)
                    fallback_config["_wid"] = wid
                    ws2 = GenericWholesaler(fallback_config)
                    if progress_callback:
                        ws2.set_progress_callback(progress_callback)
                    results2 = ws2.search_history(drug_name, lot_number,
                                                  headless=True)
                    all_results.extend(results2)
                except Exception as e2:
                    if progress_callback:
                        progress_callback(f"{wid} 자동 탐지도 실패: {e2}")

    return all_results


def _extract_drug_name_part(query: str) -> str:
    """검색어에서 한글+영문 약품명 부분만 추출한다.

    도매상 사이트에 보낼 때 사용 — 숫자/슬래시 제거.
    예: "자누메트50/1000" → "자누메트"
        "아모잘탄 5/100"  → "아모잘탄"
    """
    import re
    # 한글+영문 부분만 추출
    parts = re.findall(r'[가-힣a-zA-Z]+', query)
    return parts[0] if parts else query


def search_all_sources(drug_name: str, lot_number: str = "",
                       progress_callback=None) -> list[dict]:
    """로컬 DB + 도매상 사이트 통합 검색.

    lot_number가 있으면 도매상 사이트에서 제조번호로 정확 매칭 시도.
    결과에 source, matched 필드 포함.
    matched=True: 로트번호까지 확인된 확정 결과
    """
    all_results = []

    # 1) 로컬 주문이력 (토큰 분리 매칭)
    if progress_callback:
        progress_callback("로컬 주문이력 검색 중...")
    local = find_orders_for_return(drug_name)
    for r in local:
        r["source"] = "앱 주문이력"
        r["matched"] = False
        r.setdefault("wholesaler_name", "")
        r.setdefault("lot_number", "")
    all_results.extend(local)

    # 2) 도매상 사이트 — 약품명 부분만 추출해서 검색
    ws_query = _extract_drug_name_part(drug_name)
    if progress_callback:
        progress_callback(f"도매상 사이트 검색 중... ({ws_query})")
    ws_results = search_wholesaler_history(ws_query, lot_number,
                                           progress_callback)

    # 도매상 결과를 전체 토큰으로 필터링
    tokens = _tokenize_query(drug_name)
    if len(tokens) > 1:
        filtered = []
        for r in ws_results:
            name = r.get("drug_name", "").lower()
            if all(t.lower() in name for t in tokens):
                filtered.append(r)
        ws_results = filtered

    all_results.extend(ws_results)

    # matched=True인 결과를 먼저 정렬
    all_results.sort(key=lambda x: (not x.get("matched", False),
                                     x.get("order_date", "")),
                     reverse=False)
    # matched=True가 맨 위, 그 안에서는 날짜 오름차순
    matched = [r for r in all_results if r.get("matched")]
    unmatched = [r for r in all_results if not r.get("matched")]
    return matched + unmatched
