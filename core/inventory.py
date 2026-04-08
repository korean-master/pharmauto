"""재고 관리 모듈 - inventory.json / stock_history.json 관리.

재고 추적 방식:
  수동 재고 입력 시점(stock_set_date)을 기록하고,
  그 이후 STOCKDATE의 입고/출고 변동을 DB에서 실시간 계산한다.

  현재재고 = 수동입력값
           + (이후 STOCKDATE 입고 합계)
           - (이후 STOCKDATE 출고 합계)
           + (앱 주문으로 추가된 수량)
"""

import json
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
INVENTORY_PATH = os.path.join(DATA_DIR, "inventory.json")
HISTORY_PATH = os.path.join(DATA_DIR, "stock_history.json")


# ──────────────────────── inventory.json ────────────────────────

def load_inventory() -> dict:
    if os.path.exists(INVENTORY_PATH):
        with open(INVENTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_inventory(inv: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(INVENTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(inv, f, ensure_ascii=False, indent=2)


def get_drug_config(insurance_code: str) -> dict | None:
    """약품 설정을 반환한다. 없으면 None."""
    return load_inventory().get(insurance_code)


def set_drug_config(insurance_code: str, config: dict):
    """약품 설정을 저장/업데이트한다."""
    inv = load_inventory()
    inv[insurance_code] = config
    save_inventory(inv)


def remove_drug_config(insurance_code: str):
    inv = load_inventory()
    inv.pop(insurance_code, None)
    save_inventory(inv)


def is_configured(insurance_code: str) -> bool:
    return insurance_code in load_inventory()


# ──────────────────────── 수동 재고 입력 ────────────────────────

def set_current_stock(insurance_code: str, stock: int):
    """수동으로 현재 재고를 설정한다. 이 시점이 추적 기준점이 된다."""
    inv = load_inventory()
    cfg = inv.get(insurance_code)
    if not cfg:
        return

    old = cfg.get("base_stock", cfg.get("current_stock", 0))
    now = datetime.now()

    # 기준점 설정
    cfg["base_stock"] = stock
    cfg["stock_set_date"] = now.strftime("%Y%m%d")
    cfg["stock_set_datetime"] = now.strftime("%Y-%m-%d %H:%M:%S")
    cfg["app_order_stock"] = 0  # 앱 주문 누적 리셋
    cfg["current_stock"] = stock

    save_inventory(inv)
    _add_history(insurance_code, cfg.get("name", ""), "manual_set",
                 stock - old, stock)


# ──────────────────────── 실시간 재고 계산 ────────────────────────

def get_current_stock(insurance_code: str) -> int:
    """현재 재고를 실시간 계산한다.

    = 수동입력값(base_stock)
    + 수동입력 이후 STOCKDATE 입고 합계
    - 수동입력 이후 STOCKDATE 출고 합계  (수동입력 당일 제외)
    + 앱 주문 누적(app_order_stock)
    """
    cfg = get_drug_config(insurance_code)
    if not cfg:
        return 0

    base = cfg.get("base_stock", cfg.get("current_stock", 0))
    set_date = cfg.get("stock_set_date", "")
    app_orders = cfg.get("app_order_stock", 0)

    if not set_date:
        return base + app_orders

    # DB에서 set_date 이후 입출고 변동 조회
    db_delta = _fetch_stock_delta(insurance_code, set_date)

    result = base + db_delta + app_orders
    return max(0, result)


def _fetch_stock_delta(insurance_code: str, since_date: str) -> int:
    """STOCKDATE에서 since_date 이후(당일 제외)의 입고-출고 차이를 구한다."""
    try:
        from core.db_reader import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ISNULL(SUM(SD_DAYAMT1), 0) as total_in,
                   ISNULL(SUM(SD_DAYAMT2), 0) as total_out
            FROM STOCKDATE
            WHERE SD_ISCODE = ?
              AND SD_DATE > ?
        """, (insurance_code, since_date))
        row = cursor.fetchone()

        if row:
            total_in = int(row[0])
            total_out = int(row[1])
            return total_in - total_out
        return 0
    except Exception as e:
        print(f"[재고] DB 변동 조회 실패 ({insurance_code}): {e}")
        return 0


def get_current_stocks_bulk(codes_with_dates: list[tuple[str, str, int, int]]
                            ) -> dict[str, int]:
    """여러 약품의 재고를 한번의 DB 쿼리로 일괄 계산한다.

    Args:
        codes_with_dates: [(insurance_code, stock_set_date, base_stock, app_order_stock), ...]

    Returns:
        {insurance_code: current_stock}
    """
    result = {}

    # stock_set_date가 있는 약품만 DB 조회 필요
    need_db = [(code, date) for code, date, _, _ in codes_with_dates if date]

    # DB 일괄 조회
    db_deltas = {}
    if need_db:
        db_deltas = _fetch_stock_deltas_bulk(need_db)

    for code, set_date, base, app_orders in codes_with_dates:
        if not set_date:
            result[code] = max(0, base + app_orders)
        else:
            delta = db_deltas.get(code, 0)
            result[code] = max(0, base + delta + app_orders)

    return result


def _fetch_stock_deltas_bulk(items: list[tuple[str, str]]) -> dict[str, int]:
    """여러 약품의 STOCKDATE 변동을 한번에 조회한다.

    Args:
        items: [(insurance_code, since_date), ...]

    Returns:
        {insurance_code: delta(입고-출고)}
    """
    if not items:
        return {}

    try:
        from core.db_reader import get_connection
        conn = get_connection()
        cursor = conn.cursor()

        # 가장 오래된 기준일 찾기 (한번에 조회하기 위해)
        min_date = min(d for _, d in items)
        codes = [code for code, _ in items]
        date_map = {code: date for code, date in items}

        placeholders = ",".join("?" for _ in codes)
        cursor.execute(f"""
            SELECT SD_ISCODE, SD_DATE,
                   ISNULL(SD_DAYAMT1, 0) as amt_in,
                   ISNULL(SD_DAYAMT2, 0) as amt_out
            FROM STOCKDATE
            WHERE SD_ISCODE IN ({placeholders})
              AND SD_DATE > ?
        """, codes + [min_date])

        deltas = {}
        for row in cursor.fetchall():
            code = str(row[0]).strip()
            sd_date = str(row[1]).strip()
            amt_in = int(row[2])
            amt_out = int(row[3])
            # 해당 약품의 기준일 이후인지 확인
            if sd_date > date_map.get(code, ""):
                deltas[code] = deltas.get(code, 0) + amt_in - amt_out

        return deltas

    except Exception as e:
        print(f"[재고] 일괄 DB 조회 실패: {e}")
        return {}


def refresh_all_stocks():
    """모든 약품의 current_stock을 실시간 계산값으로 갱신한다."""
    inv = load_inventory()
    changed = False
    for code, cfg in inv.items():
        if cfg.get("stock_set_date"):
            new_stock = get_current_stock(code)
            if cfg.get("current_stock", 0) != new_stock:
                cfg["current_stock"] = new_stock
                changed = True
    if changed:
        save_inventory(inv)


# ──────────────────────── 주문/반품 연동 ────────────────────────

def update_stock_after_order(insurance_code: str, ordered_qty: int):
    """앱을 통한 주문 완료 후 재고 증가 (앱 주문 누적에 합산)."""
    inv = load_inventory()
    cfg = inv.get(insurance_code)
    if cfg:
        cfg["app_order_stock"] = cfg.get("app_order_stock", 0) + ordered_qty
        cfg["current_stock"] = get_current_stock(insurance_code) + ordered_qty
        save_inventory(inv)
        _add_history(insurance_code, cfg.get("name", ""), "order",
                     ordered_qty, cfg["current_stock"])


def update_stock_after_return(insurance_code: str, return_qty: int):
    """반품 완료 후 재고 감소."""
    inv = load_inventory()
    cfg = inv.get(insurance_code)
    if cfg:
        # 반품은 STOCKDATE에 안 잡히므로 직접 차감
        cfg["app_order_stock"] = cfg.get("app_order_stock", 0) - return_qty
        cfg["current_stock"] = max(0, get_current_stock(insurance_code))
        save_inventory(inv)
        _add_history(insurance_code, cfg.get("name", ""), "return",
                     -return_qty, cfg["current_stock"])


# ──────────────────────── 주문량 계산 ────────────────────────

def calc_order_qty(insurance_code: str, today_used: int) -> int:
    """주문 방식에 따라 주문량을 계산한다.

    Returns:
        주문할 정 수량 (0이면 주문 불필요).
    """
    cfg = get_drug_config(insurance_code)
    if not cfg:
        return today_used

    order_type = cfg.get("order_type", "immediate")

    if order_type == "immediate":
        return today_used

    elif order_type == "stock":
        target = cfg.get("target_stock", 0)
        current = get_current_stock(insurance_code)
        if current >= target:
            return 0
        return target - current

    elif order_type == "manual":
        return 0

    return today_used


# ──────────────────────── stock_history.json ────────────────────────

def _add_history(insurance_code: str, name: str, event_type: str,
                 delta: int, after_stock: int):
    history = load_history()
    history.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "insurance_code": insurance_code,
        "name": name,
        "type": event_type,
        "delta": delta,
        "after_stock": after_stock,
    })
    if len(history) > 5000:
        history = history[-5000:]
    _save_history(history)


def load_history() -> list:
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_history(history: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
