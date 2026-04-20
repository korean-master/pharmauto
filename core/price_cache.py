"""약품 가격 캐시 — 도매상별 약품 가격을 저장/조회한다.

가격은 주문 시 도매상 사이트에서 자동 수집되어 캐시된다.
1년간 유효하며, 만료 시 다음 주문 때 자동 갱신된다.
"""

import json
import os
from datetime import datetime, timedelta

from core import paths

CACHE_EXPIRY_DAYS = 365


def _cache_path() -> str:
    return os.path.join(paths.get_data_dir(), "price_cache.json")


def _load_cache() -> dict:
    p = _cache_path()
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict):
    with open(_cache_path(), "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def get_price(insurance_code: str, wholesaler_id: str = "") -> int:
    """약품의 캐시된 단가를 반환한다 (정 단위).

    wholesaler_id가 있으면 해당 도매상 가격, 없으면 아무 도매상 가격.
    없으면 0 반환.
    """
    cache = _load_cache()
    drug = cache.get(insurance_code, {})

    if wholesaler_id and wholesaler_id in drug:
        entry = drug[wholesaler_id]
        if _is_valid(entry):
            return entry.get("unit_price", 0)

    # 아무 도매상 가격이라도
    for wid, entry in drug.items():
        if _is_valid(entry) and entry.get("unit_price", 0) > 0:
            return entry["unit_price"]

    return 0


def get_prices_bulk(codes: list[str], wholesaler_id: str = "") -> dict[str, int]:
    """여러 약품의 단가를 한번에 조회한다.

    Returns:
        {insurance_code: unit_price, ...}
    """
    cache = _load_cache()
    result = {}
    for code in codes:
        drug = cache.get(code, {})
        price = 0

        if wholesaler_id and wholesaler_id in drug:
            entry = drug[wholesaler_id]
            if _is_valid(entry):
                price = entry.get("unit_price", 0)

        if not price:
            for wid, entry in drug.items():
                if _is_valid(entry) and entry.get("unit_price", 0) > 0:
                    price = entry["unit_price"]
                    break

        result[code] = price
    return result


def save_price(insurance_code: str, wholesaler_id: str,
               unit_price: int, pack_price: int = 0, pack_size: int = 0):
    """약품 가격을 캐시에 저장한다.

    Args:
        insurance_code: 보험코드
        wholesaler_id: 도매상 ID
        unit_price: 정당 단가 (원)
        pack_price: 포장 단위 가격 (원)
        pack_size: 포장 수량 (정)
    """
    cache = _load_cache()
    if insurance_code not in cache:
        cache[insurance_code] = {}

    cache[insurance_code][wholesaler_id] = {
        "unit_price": unit_price,
        "pack_price": pack_price,
        "pack_size": pack_size,
        "updated_at": datetime.now().isoformat(),
    }
    _save_cache(cache)


def save_prices_bulk(prices: list[dict]):
    """여러 약품의 가격을 일괄 저장한다.

    Args:
        prices: [{"insurance_code", "wholesaler_id", "unit_price",
                  "pack_price", "pack_size"}, ...]
    """
    cache = _load_cache()
    now = datetime.now().isoformat()

    for p in prices:
        code = p["insurance_code"]
        wid = p["wholesaler_id"]
        if code not in cache:
            cache[code] = {}
        cache[code][wid] = {
            "unit_price": p.get("unit_price", 0),
            "pack_price": p.get("pack_price", 0),
            "pack_size": p.get("pack_size", 0),
            "updated_at": now,
        }

    _save_cache(cache)


def _is_valid(entry: dict) -> bool:
    """캐시 항목이 유효한지 확인한다 (1년 이내)."""
    updated = entry.get("updated_at", "")
    if not updated:
        return False
    try:
        dt = datetime.fromisoformat(updated)
        return datetime.now() - dt < timedelta(days=CACHE_EXPIRY_DAYS)
    except Exception:
        return False


def estimate_order_amount(insurance_code: str, qty: int,
                          wholesaler_id: str = "") -> int:
    """주문 예상 금액을 계산한다.

    Returns:
        예상 금액 (원). 가격 정보 없으면 0.
    """
    price = get_price(insurance_code, wholesaler_id)
    return price * qty


def get_cache_stats() -> dict:
    """가격 캐시 통계를 반환한다."""
    cache = _load_cache()
    total = len(cache)
    valid = sum(
        1 for drug in cache.values()
        for entry in drug.values()
        if _is_valid(entry)
    )
    return {"total_drugs": total, "valid_entries": valid}
