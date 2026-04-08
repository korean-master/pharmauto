"""반품 처리 엔진."""

import os
import sqlite3
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DB_PATH = os.path.join(DATA_DIR, "order_history.db")


def _get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS return_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_date TEXT NOT NULL,
            drug_name TEXT NOT NULL,
            lot_number TEXT NOT NULL,
            wholesaler_id TEXT NOT NULL,
            wholesaler_name TEXT NOT NULL,
            original_order_date TEXT,
            status TEXT DEFAULT 'requested',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def find_order_for_return(drug_name: str, lot_number: str) -> dict | None:
    """약품명으로 주문 이력에서 입고 도매상/날짜를 찾는다."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT * FROM order_history
           WHERE drug_name LIKE ?
           ORDER BY order_date DESC LIMIT 1""",
        (f"%{drug_name}%",),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_return(drug_name: str, lot_number: str, wholesaler_id: str,
                  wholesaler_name: str, original_order_date: str = "") -> int:
    """반품 신청을 생성한다."""
    conn = _get_db()
    now = datetime.now()
    cursor = conn.execute(
        """INSERT INTO return_history
           (return_date, drug_name, lot_number, wholesaler_id,
            wholesaler_name, original_order_date, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'requested', ?)""",
        (
            now.strftime("%Y-%m-%d"),
            drug_name,
            lot_number,
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


def get_return_history(days: int = 90) -> list[dict]:
    """반품 이력을 조회한다."""
    conn = _get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT * FROM return_history
           WHERE return_date >= date('now', ?)
           ORDER BY created_at DESC""",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
