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
    if not os.path.exists(DB_PATH):
        return []

    tokens = _tokenize_query(drug_name)
    if not tokens:
        return []

    conn = sqlite3.connect(DB_PATH)
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
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "wholesalers.json"
    )
    if not os.path.exists(config_path):
        return []

    with open(config_path, "r", encoding="utf-8") as f:
        ws_map = json.load(f)

    from core.crypto import load_wholesalers_secure
    secure_ws = load_wholesalers_secure()

    class_map = {
        "geo": ("wholesalers.jioeyoung", "JioeyoungWholesaler"),
        "baekje": ("wholesalers.baekje", "BaekjeWholesaler"),
    }

    result = []
    for wid in ws_map:
        config = secure_ws.get(wid, {})
        if wid in class_map:
            module_name, cls_name = class_map[wid]
            try:
                mod = importlib.import_module(module_name)
                cls = getattr(mod, cls_name)
                result.append((wid, cls, config))
            except Exception:
                continue
        else:
            # GenericWholesaler로 처리 (이력 검색 설정이 있는 도매상만)
            try:
                from wholesalers.generic import GenericWholesaler
                config["_wid"] = wid
                result.append((wid, GenericWholesaler, config))
            except Exception:
                continue
    return result


def _search_samwon_history(drug_name: str, lot_number: str = "",
                          config: dict = None,
                          progress_callback=None) -> list[dict]:
    """삼원약품 매출원장에서 입고이력을 검색한다."""
    import asyncio

    async def _search():
        results = []
        from playwright.async_api import async_playwright
        import sys

        if progress_callback:
            progress_callback(f"삼원약품 입고이력 검색: {drug_name}")

        pw_inst = await async_playwright().start()

        if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
            bundle_dir = os.path.dirname(sys.executable)
            for _bdir in [
                os.path.join(bundle_dir, "playwright_browsers"),
                os.path.join(bundle_dir, "_internal", "playwright_browsers"),
            ]:
                if os.path.exists(_bdir):
                    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _bdir
                    break

        browser = await pw_inst.chromium.launch(headless=True)
        page = await browser.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

        try:
            # 로그인
            await page.goto("https://www.pharmbox.co.kr/",
                            wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            await page.fill("#P_H_USER_ID", config.get("id", ""))
            await page.fill("#P_H_PWD", config.get("pw", ""))
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(4000)

            # 매출원장 페이지
            await page.goto(
                "https://www.pharmbox.co.kr/mypharm/sales_ledger.jsp",
                wait_until="domcontentloaded", timeout=15000,
            )
            await page.wait_for_timeout(2000)

            # 기간 5년으로 설정
            btn_5y = page.locator('button:has-text("5년")')
            if await btn_5y.count() > 0:
                await btn_5y.click()
                await page.wait_for_timeout(500)

            # 약품명 검색
            await page.fill("#P_SRH_SALES_KEY", drug_name)

            # 조회 버튼
            lookup_btn = page.locator("button.lookup-btn").first
            await lookup_btn.click()
            await page.wait_for_timeout(4000)

            # 테이블 파싱
            # 헤더: 주문일[0], 보험코드[1], 상품명[2], 입고/출고[3],
            #       단가[4], 매입액[5], 매출액[6], 잔잔액[7], 제조번호[8], 유효기한[9]
            rows = page.locator("table").nth(1).locator("tbody tr")
            count = await rows.count()

            if progress_callback:
                progress_callback(f"삼원약품 검색 결과: {count}건")

            import re
            search_keywords = [k.strip() for k in drug_name.split() if k.strip()]

            for i in range(min(count, 50)):
                try:
                    row = rows.nth(i)
                    cells = row.locator("td")
                    cell_count = await cells.count()
                    if cell_count < 8:
                        continue

                    order_date = (await cells.nth(0).inner_text()).strip()
                    drug = (await cells.nth(2).inner_text()).strip()
                    inout = (await cells.nth(3).inner_text()).strip()
                    lot = (await cells.nth(8).inner_text()).strip() if cell_count > 8 else ""
                    expiry = (await cells.nth(9).inner_text()).strip() if cell_count > 9 else ""

                    if (not drug or "없습니다" in drug or
                            "소계" in drug or "잔액" in drug or
                            drug.startswith("<") or drug.startswith("[")):
                        continue

                    # 키워드 필터링
                    drug_lower = drug.lower()
                    if not all(kw.lower() in drug_lower for kw in search_keywords):
                        continue

                    # 로트번호 매칭 확인
                    matched = False
                    if lot_number and lot:
                        matched = lot_number.lower() in lot.lower()

                    nums = re.sub(r'[^\d]', '', inout)
                    qty = int(nums) if nums else 0

                    result = {
                        "drug_name": drug,
                        "order_date": order_date,
                        "qty": qty,
                        "lot_number": lot,
                        "expiry": expiry,
                        "wholesaler_id": "삼원약품",
                        "wholesaler_name": "삼원약품",
                        "source": "삼원약품",
                        "matched": matched,
                    }
                    results.append(result)
                except Exception:
                    continue

        except Exception as e:
            if progress_callback:
                progress_callback(f"삼원약품 검색 오류: {e}")
        finally:
            await browser.close()
            await pw_inst.stop()

        return results

    return asyncio.run(_search())


def search_wholesaler_history(drug_name: str, lot_number: str = "",
                              progress_callback=None) -> list[dict]:
    """모든 등록 도매상 사이트에서 입고이력을 검색한다.

    전용 클래스(백제/지오영)에서 실패하면 GenericWholesaler 자동 탐지로 재시도.
    삼원약품은 전용 검색 함수 사용.
    """
    all_results = []
    samwon_done = False

    for wid, cls, config in _get_wholesaler_classes():
        # 삼원약품은 전용 함수로 처리
        if wid == "삼원약품" or (config.get("name", "") == "삼원약품"):
            try:
                from core.crypto import load_wholesalers_secure
                sw_config = load_wholesalers_secure().get(wid, config)
                results = _search_samwon_history(drug_name, lot_number,
                                                sw_config, progress_callback)
                all_results.extend(results)
                samwon_done = True
            except Exception as e:
                if progress_callback:
                    progress_callback(f"삼원약품 검색 실패: {e}")
                samwon_done = True
            continue
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
