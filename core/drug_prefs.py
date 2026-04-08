"""약품별 선호 규격 관리."""

import json
import os

PREFS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "drug_preferences.json")


def load_preferences() -> dict:
    if os.path.exists(PREFS_PATH):
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_preferences(prefs: dict):
    os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
    with open(PREFS_PATH, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


def get_preferred_unit(insurance_code: str) -> int | None:
    """선호 규격을 반환한다. 없으면 None."""
    prefs = load_preferences()
    entry = prefs.get(insurance_code)
    if entry:
        return entry.get("preferred_unit")
    return None


def set_preferred_unit(insurance_code: str, preferred_unit: int,
                       unit_options: list[int], drug_name: str = ""):
    """선호 규격을 저장한다."""
    prefs = load_preferences()
    prefs[insurance_code] = {
        "preferred_unit": preferred_unit,
        "unit_options": sorted(set(unit_options)),
        "drug_name": drug_name,
    }
    save_preferences(prefs)


def remove_preferred_unit(insurance_code: str):
    """선호 규격을 삭제한다."""
    prefs = load_preferences()
    prefs.pop(insurance_code, None)
    save_preferences(prefs)
