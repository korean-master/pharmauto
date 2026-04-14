"""주문 처리 엔진 - 도매상별 묶음 주문 및 재주문 로직."""

import json
import os
import sqlite3
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DB_PATH = os.path.join(DATA_DIR, "order_history.db")
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "settings.json")
WHOLESALERS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "wholesalers.json")


def is_cart_only_mode() -> bool:
    """주문 확정 방식이 '장바구니만 담기'인지 확인한다."""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
        return settings.get("order_confirm_mode") == "cart_only"
    except Exception:
        return False


def _get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS order_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_date TEXT NOT NULL,
            insurance_code TEXT NOT NULL,
            drug_name TEXT NOT NULL,
            spec TEXT DEFAULT '',
            qty INTEGER NOT NULL,
            pack_size INTEGER DEFAULT 0,
            box_qty INTEGER DEFAULT 0,
            wholesaler_id TEXT NOT NULL,
            wholesaler_name TEXT NOT NULL,
            status TEXT DEFAULT 'ordered',
            created_at TEXT NOT NULL
        )
    """)
    # 기존 테이블에 컬럼 없으면 추가
    try:
        conn.execute("ALTER TABLE order_history ADD COLUMN pack_size INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE order_history ADD COLUMN box_qty INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE order_history ADD COLUMN unit_price INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE order_history ADD COLUMN total_price INTEGER DEFAULT 0")
    except Exception:
        pass
    conn.commit()
    return conn


def _load_wholesalers():
    from core.crypto import load_wholesalers_secure
    return load_wholesalers_secure()


def _update_ws_status(wid: str, status: str):
    """도매상 연결 상태를 wholesalers.json에 저장한다."""
    try:
        with open(WHOLESALERS_PATH, "r", encoding="utf-8") as f:
            ws = json.load(f)
        if wid in ws:
            ws[wid]["connection_status"] = status
            with open(WHOLESALERS_PATH, "w", encoding="utf-8") as f:
                json.dump(ws, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_split_settings() -> dict:
    """주문 분배 설정을 읽는다."""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
        return {
            "mode": settings.get("order_split_mode", "single"),
            "wholesalers": settings.get("order_split_wholesalers", []),
            "ratios": settings.get("order_split_ratios", {}),
        }
    except Exception:
        return {"mode": "single", "wholesalers": [], "ratios": {}}


def _distribute_items(order_items: list[dict], wholesaler_ids: list[str],
                      ratios: dict = None) -> list[dict]:
    """주문 항목을 여러 도매상에 비율 기준으로 분배한다.

    가격 캐시가 있으면 금액 기준, 없으면 수량 기준.
    비율에 맞춰 각 도매상의 목표 금액을 계산하고,
    목표 대비 부족한 도매상에 우선 배정한다.
    """
    if not wholesaler_ids or len(wholesaler_ids) < 2:
        return order_items

    if ratios is None:
        ratios = {}

    # 각 도매상의 비율 (기본 5)
    ws_ratios = {wid: ratios.get(wid, 5) for wid in wholesaler_ids}
    total_ratio = sum(ws_ratios.values())

    # 가격 캐시에서 단가 조회
    from core.price_cache import get_prices_bulk
    codes = [item.get("insurance_code", "") for item in order_items]
    prices = get_prices_bulk(codes)
    has_prices = any(p > 0 for p in prices.values())

    def _item_value(item):
        code = item.get("insurance_code", "")
        qty = item.get("qty", 0)
        unit_price = prices.get(code, 0)
        if unit_price > 0:
            return unit_price * qty
        return qty

    # 전체 주문 가치
    total_value = sum(_item_value(item) for item in order_items)

    # 각 도매상의 목표값
    ws_targets = {
        wid: total_value * ws_ratios[wid] / total_ratio
        for wid in wholesaler_ids
    }

    # 기준값 큰 순으로 정렬 → 큰 것부터 목표 대비 가장 부족한 쪽에 배정
    sorted_items = sorted(order_items, key=_item_value, reverse=True)
    ws_totals = {wid: 0 for wid in wholesaler_ids}

    for item in sorted_items:
        # 목표 대비 가장 부족한 도매상 선택
        min_wid = min(
            wholesaler_ids,
            key=lambda wid: ws_totals[wid] / ws_targets[wid] if ws_targets[wid] > 0 else float('inf'),
        )
        item["wholesaler_id"] = min_wid
        ws_totals[min_wid] += _item_value(item)

    basis = "금액" if has_prices else "수량"
    ratio_str = ":".join(str(ws_ratios[wid]) for wid in wholesaler_ids)
    for wid, total in ws_totals.items():
        target = ws_targets[wid]
        print(f"[분배] {wid}: {total:,.0f} (목표 {target:,.0f}){'원' if has_prices else '정'}")
    print(f"[분배] 비율: {ratio_str} / 기준: {basis}")

    return sorted_items


def group_by_wholesaler(order_items: list[dict]) -> dict[str, list[dict]]:
    """주문 항목을 도매상별로 그룹핑한다."""
    groups = {}
    for item in order_items:
        wid = item["wholesaler_id"]
        groups.setdefault(wid, []).append(item)
    return groups


def place_orders(order_items: list[dict], progress_callback=None,
                 dry_run=False) -> list[dict]:
    """도매상별로 묶어서 주문을 실행하고 이력을 저장한다.

    주문 분배 설정이 '균등 분배'면 아이템을 자동으로 재배분한다.

    Returns:
        [{"wholesaler_id", "wholesaler_name", "items", "success", "message",
          "failed_items"}, ...]
    """
    # 주문 분배 적용
    split = _get_split_settings()
    if split["mode"] == "even" and len(split["wholesalers"]) >= 2:
        order_items = _distribute_items(
            order_items, split["wholesalers"], split.get("ratios", {})
        )

    wholesalers = _load_wholesalers()
    groups = group_by_wholesaler(order_items)
    results = []

    for wid, items in groups.items():
        ws = wholesalers.get(wid, {})
        ws_name = ws.get("name", wid)

        ws_config = {**ws, "id": ws.get("id", ""), "pw": ws.get("pw", "")}
        order_result = _execute_wholesaler_order(
            wid, ws_config, items, progress_callback, dry_run
        )

        success = order_result.get("success", False) if isinstance(order_result, dict) else order_result
        message = order_result.get("message", "") if isinstance(order_result, dict) else ""
        failed = order_result.get("failed_items", []) if isinstance(order_result, dict) else []

        # 도매상이 리턴한 실제 주문 결과(pack_size, box_qty)를 items에 반영
        ws_results = order_result.get("results", []) if isinstance(order_result, dict) else []
        if ws_results:
            # results와 items는 같은 순서 (insurance_code 기준 매칭)
            result_map = {}
            for r in ws_results:
                if r.get("success") and r.get("insurance_code"):
                    result_map[r["insurance_code"]] = r
            price_updates = []
            for item in items:
                r = result_map.get(item.get("insurance_code", ""))
                if r:
                    item["pack_size"] = r.get("pack_size", 0)
                    item["box_qty"] = r.get("box_qty", 0)
                    item["unit_price"] = r.get("unit_price", 0)
                    item["pack_price"] = r.get("pack_price", 0)
                    # 가격 캐시 수집
                    if r.get("unit_price", 0) > 0:
                        price_updates.append({
                            "insurance_code": r["insurance_code"],
                            "wholesaler_id": wid,
                            "unit_price": r["unit_price"],
                            "pack_price": r.get("pack_price", 0),
                            "pack_size": r.get("pack_size", 0),
                        })

            # 가격 캐시 일괄 저장
            if price_updates:
                try:
                    from core.price_cache import save_prices_bulk
                    save_prices_bulk(price_updates)
                except Exception:
                    pass

        # 성공/실패 분리 — 품절(out_of_stock)과 일반 실패 구분
        failed_codes = set(
            f.get("insurance_code", "") for f in failed
        )

        # ws_results에서 품절 여부 확인
        oos_codes = set()
        for r in ws_results:
            if r.get("out_of_stock") and r.get("insurance_code"):
                oos_codes.add(r["insurance_code"])

        success_items = [
            it for it in items
            if it.get("insurance_code", "") not in failed_codes
        ]
        failed_items_detail = [
            it for it in items
            if it.get("insurance_code", "") in failed_codes
        ]
        oos_items = [
            it for it in failed_items_detail
            if it.get("insurance_code", "") in oos_codes
        ]

        if success:
            ok_status = "cart_only" if dry_run else "ordered"
            if success_items:
                _save_order_history(success_items, wid, ws_name, status=ok_status)

        # 실패한 아이템 이력 기록 — 품절은 out_of_stock, 나머지는 failed
        if failed_items_detail:
            normal_fail = [it for it in failed_items_detail
                           if it.get("insurance_code", "") not in oos_codes]
            if oos_items:
                _save_order_history(oos_items, wid, ws_name, status="out_of_stock")
            if normal_fail:
                _save_order_history(normal_fail, wid, ws_name, status="failed")
        elif not success:
            _save_order_history(items, wid, ws_name, status="failed")

        # 도매상 연결 상태 갱신
        _update_ws_status(wid, "정상" if success else "연동 오류")

        results.append({
            "wholesaler_id": wid,
            "wholesaler_name": ws_name,
            "items": items,
            "success": success,
            "success_items": success_items if success else [],
            "message": message or ("주문 완료" if success else "주문 실패"),
            "failed_items": failed,
            "oos_items": oos_items,
        })

    # ── 품절 항목 자동 재주문 (다른 도매상으로) ──
    all_oos = []
    for r in results:
        for it in r.get("oos_items", []):
            it["_original_wholesaler"] = r["wholesaler_id"]
            it["_original_ws_name"] = r["wholesaler_name"]
            all_oos.append(it)

    retry_results = []
    if all_oos:
        if progress_callback:
            progress_callback(f"품절 {len(all_oos)}건 → 대체 도매상 재주문 시도...")
        retry_results = _retry_oos_items(all_oos, wholesalers, progress_callback,
                                         dry_run=dry_run)

    return results, retry_results


# 도매상 ID → 클래스 매핑 (자동 탐색)
_WHOLESALER_CLASSES = {
    "geo": ("wholesalers.jioeyoung", "JioeyoungWholesaler"),
    "baekje": ("wholesalers.baekje", "BaekjeWholesaler"),
}


def _get_wholesaler_class(wid: str):
    """도매상 ID에 해당하는 클래스를 반환한다. 없으면 None."""
    import importlib
    entry = _WHOLESALER_CLASSES.get(wid)
    if entry:
        module = importlib.import_module(entry[0])
        return getattr(module, entry[1])
    return None


def register_wholesaler(wid: str, module_path: str, class_name: str):
    """새 도매상 클래스를 등록한다.

    예: register_wholesaler("samwon", "wholesalers.samwon", "SamwonWholesaler")
    """
    _WHOLESALER_CLASSES[wid] = (module_path, class_name)


def _execute_wholesaler_order(wid: str, ws_config: dict, items: list[dict],
                              progress_callback=None, dry_run=False) -> dict:
    """도매상 주문 실행. 등록된 도매상 클래스를 자동으로 찾아 실행한다.

    Returns:
        {"success": bool, "message": str, "results": list, "failed_items": list}
    """
    import asyncio

    ws_class = _get_wholesaler_class(wid)
    if not ws_class:
        # 전용 클래스가 없으면 범용 자동화 클래스 사용
        from wholesalers.generic import GenericWholesaler
        ws_class = GenericWholesaler
        ws_config["_wid"] = wid  # 셀렉터 캐시 식별용

    ws = ws_class(ws_config)
    if progress_callback:
        ws.set_progress_callback(progress_callback)

    order_items = [
        {
            "insurance_code": it["insurance_code"],
            "quantity": it.get("qty", 1),
            "preferred_unit": it.get("preferred_unit", 0),
        }
        for it in items
    ]

    return asyncio.run(
        ws.place_order_async(order_items, headless=True, dry_run=dry_run)
    )


def _retry_oos_items(oos_items: list[dict], wholesalers: dict,
                     progress_callback=None, dry_run: bool = False) -> list[dict]:
    """품절 항목을 다른 도매상으로 자동 재주문한다.

    Args:
        oos_items: 품절된 주문 항목 리스트 (_original_wholesaler 키 포함)
        wholesalers: 전체 도매상 설정 dict
        progress_callback: 진행 상황 콜백
        dry_run: True면 장바구니만 담기

    Returns:
        [{"item": dict, "original_ws": str, "retry_ws": str, "success": bool}, ...]
    """
    sorted_ws = sorted(wholesalers.items(), key=lambda x: x[1].get("priority", 99))

    results = []
    for item in oos_items:
        original_wid = item.get("_original_wholesaler", "")
        drug_name = item.get("drug_name", item.get("insurance_code", ""))
        ordered = False

        for wid, ws in sorted_ws:
            if wid == original_wid:
                continue

            ws_name = ws.get("name", wid)
            if progress_callback:
                progress_callback(f"  품절 재주문: {drug_name} → {ws_name}")

            ws_config = {**ws, "id": ws.get("id", ""), "pw": ws.get("pw", "")}
            order_result = _execute_wholesaler_order(
                wid, ws_config, [item], progress_callback, dry_run=dry_run
            )

            ws_success = (order_result.get("success", False)
                          if isinstance(order_result, dict) else order_result)
            ws_results = (order_result.get("results", [])
                          if isinstance(order_result, dict) else [])

            if ws_success:
                # 실제 주문 결과 반영
                for r in ws_results:
                    if r.get("success") and r.get("insurance_code"):
                        item["pack_size"] = r.get("pack_size", 0)
                        item["box_qty"] = r.get("box_qty", 0)

                ok_status = "cart_only" if dry_run else "ordered"
                _save_order_history([item], wid, ws_name, status=ok_status)
                results.append({
                    "item": item,
                    "original_ws": item.get("_original_ws_name", original_wid),
                    "retry_ws": ws_name,
                    "success": True,
                    "message": f"{ws_name} 장바구니 담기 완료" if dry_run else f"{ws_name} 주문 완료",
                })
                ordered = True
                break

        if not ordered:
            results.append({
                "item": item,
                "original_ws": item.get("_original_ws_name", original_wid),
                "retry_ws": "",
                "success": False,
            })

    return results


def _save_order_history(items: list[dict], wid: str, ws_name: str,
                        status: str = "ordered"):
    import math
    from core.inventory import get_drug_config

    conn = _get_db()
    now = datetime.now()
    for item in items:
        code = item.get("insurance_code", "")
        qty = item.get("qty", 0)

        # 도매상 실제 주문 결과 우선, 없으면 preferred_unit으로 계산
        pack_size = item.get("pack_size", 0)
        box_qty = item.get("box_qty", 0)

        if not pack_size:
            pref = item.get("preferred_unit", 0)
            if not pref:
                cfg = get_drug_config(code)
                pref = cfg.get("preferred_unit", 0) if cfg else 0
            pack_size = pref
            box_qty = math.ceil(qty / pack_size) if pack_size > 0 else 0

        # 금액 계산
        unit_price = item.get("unit_price", 0)
        if not unit_price:
            from core.price_cache import get_price
            unit_price = get_price(code, wid)
        total_price = unit_price * qty if unit_price else 0

        conn.execute(
            """INSERT INTO order_history
               (order_date, insurance_code, drug_name, spec, qty,
                pack_size, box_qty, unit_price, total_price,
                wholesaler_id, wholesaler_name, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now.strftime("%Y-%m-%d"),
                code,
                item.get("drug_name", ""),
                item.get("spec", ""),
                qty,
                pack_size,
                box_qty,
                unit_price,
                total_price,
                wid,
                ws_name,
                status,
                now.isoformat(),
            ),
        )
    conn.commit()
    conn.close()


def _backfill_pack_sizes():
    """pack_size가 0인 기존 레코드를 약품 설정에서 보완한다."""
    from core.inventory import get_drug_config
    import math

    conn = _get_db()
    rows = conn.execute(
        "SELECT id, insurance_code, qty FROM order_history WHERE pack_size = 0 OR pack_size IS NULL"
    ).fetchall()

    for row_id, code, qty in rows:
        cfg = get_drug_config(code)
        pref = cfg.get("preferred_unit", 0) if cfg else 0
        if pref > 0:
            box_qty = math.ceil(qty / pref) if qty else 0
            conn.execute(
                "UPDATE order_history SET pack_size = ?, box_qty = ? WHERE id = ?",
                (pref, box_qty, row_id),
            )
    conn.commit()
    conn.close()


def get_order_history(days: int = 30) -> list[dict]:
    """최근 주문 이력을 조회한다."""
    _backfill_pack_sizes()
    conn = _get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT * FROM order_history
           WHERE order_date >= date('now', ?)
           ORDER BY created_at DESC""",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_monthly_summary(months: int = 6) -> list[dict]:
    """도매상별 월별 주문 금액 요약을 반환한다.

    Returns:
        [{"month": "2026-04", "wholesaler_id": "geo",
          "wholesaler_name": "지오영", "total_amount": 150000,
          "item_count": 12}, ...]
    """
    conn = _get_db()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT
               strftime('%Y-%m', order_date) as month,
               wholesaler_id,
               wholesaler_name,
               SUM(COALESCE(total_price, 0)) as total_amount,
               COUNT(*) as item_count,
               SUM(qty) as total_qty
           FROM order_history
           WHERE order_date >= date('now', ?)
           GROUP BY month, wholesaler_id
           ORDER BY month DESC, total_amount DESC""",
        (f"-{months} months",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
