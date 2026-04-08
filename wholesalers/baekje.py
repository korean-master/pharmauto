"""백제약품 도매상 자동화 - Playwright 기반."""

import asyncio
import json
import math
import os
import sys

from wholesalers.base import WholesalerBase, choose_best_pack, parse_pack_size

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "wholesalers.json")


def _load_baekje_config() -> dict:
    from core.crypto import load_wholesalers_secure
    return load_wholesalers_secure().get("baekje", {})


class BaekjeWholesaler(WholesalerBase):
    """백제약품 Playwright 자동화."""

    LOGIN_URL = "http://www.ibjp.kr/dist/login"

    def __init__(self, config: dict | None = None):
        if config is None:
            config = _load_baekje_config()
        super().__init__(config)

    # ------ 로그인 ------

    async def login_async(self, headless: bool = True) -> bool:
        if not self._page:
            await self._launch(headless=headless)
        page = self._page

        # 브라우저 confirm/alert 자동 수락
        page.on("dialog", lambda d: d.accept())

        self._progress("로그인 중...")

        await page.goto(self.LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        await page.fill('input[type="text"]', self.user_id)
        await page.fill('input[type="password"]', self.password)
        await page.click('button.login_btn')
        await page.wait_for_timeout(4000)

        login_success = 'login' not in page.url
        if login_success:
            self._progress("로그인 성공")
            await self._screenshot("baekje_01_login.png")
        else:
            self._progress("로그인 실패")
            await self._screenshot("baekje_01_login_fail.png")

        return login_success

    # ------ 약품 검색 & 장바구니 담기 ------

    async def _add_item_to_cart(self, insurance_code: str, quantity: int,
                                idx: int, total: int,
                                preferred_unit: int | None = None) -> dict:
        page = self._page
        result = {"success": False, "insurance_code": insurance_code,
                  "quantity": quantity, "box_qty": 0, "pack_size": 0,
                  "drug_name": "", "message": "", "unit_options": []}

        # 검색
        search_input = await page.query_selector('input[placeholder*="품목명"]')
        if not search_input:
            search_input = await page.query_selector('input[placeholder*="보험코드"]')
        if not search_input:
            result["message"] = "검색 필드 없음"
            return result

        await search_input.click()
        await search_input.fill(insurance_code)
        await page.click('button:has-text("검색")')
        await page.wait_for_timeout(3000)

        # 검색 결과 확인 - 모든 매칭 행 수집
        result_cells = await page.query_selector_all(
            f'td.td-code:has-text("{insurance_code}")'
        )
        if not result_cells:
            result["message"] = "검색 결과 없음"
            self._progress(f"  [{insurance_code}] 검색 결과 없음 ({idx}/{total})")
            return result

        # 각 행에서 규격/약품명 수집
        candidates = []
        for cell in result_cells:
            row_el = await cell.evaluate_handle('el => el.closest("tr")')

            name_el = await row_el.query_selector('.td-prd_name')
            drug_name = (await name_el.inner_text()).strip() if name_el else ""

            unit_el = await row_el.query_selector('.td-unit')
            unit_text = (await unit_el.inner_text()).strip() if unit_el else ""
            pack_size = parse_pack_size(unit_text)

            # 가격 수집
            pack_price = 0
            price_el = await row_el.query_selector('.td-price')
            if price_el:
                price_text = (await price_el.inner_text()).strip()
                price_text = price_text.replace(",", "").replace("원", "")
                try:
                    pack_price = int(price_text)
                except ValueError:
                    pass

            if pack_size > 0:
                candidates.append({
                    "row": row_el, "pack_size": pack_size,
                    "drug_name": drug_name, "unit_text": unit_text,
                    "pack_price": pack_price,
                })

        if not candidates:
            # 규격 파싱 실패 시 첫 번째 행 사용
            row_el = await result_cells[0].evaluate_handle('el => el.closest("tr")')
            name_el = await row_el.query_selector('.td-prd_name')
            result["drug_name"] = (
                (await name_el.inner_text()).strip() if name_el else ""
            )
            pack_size = preferred_unit or 1
            result["pack_size"] = pack_size
            result["unit_options"] = [pack_size]
            box_qty = max(1, math.ceil(quantity / pack_size))
            result["box_qty"] = box_qty
            chosen = {"row": row_el, "pack_size": pack_size,
                      "drug_name": result["drug_name"], "unit_text": ""}
        else:
            unit_options = sorted(set(c["pack_size"] for c in candidates))
            result["unit_options"] = unit_options

            # 최적 규격 선택 (공통 로직)
            chosen = choose_best_pack(candidates, quantity, preferred_unit)
            box_qty = chosen["box_qty"]

            result["drug_name"] = chosen["drug_name"]
            result["pack_size"] = chosen["pack_size"]
            result["box_qty"] = box_qty
            result["pack_price"] = chosen.get("pack_price", 0)
            result["unit_price"] = (
                chosen["pack_price"] // chosen["pack_size"]
                if chosen.get("pack_price") and chosen["pack_size"] > 0
                else 0
            )

        self._progress(
            f"  {result['drug_name']} 장바구니 담는 중... ({idx}/{total})"
        )

        # 해당 행 클릭하여 선택
        await chosen["row"].click()
        await page.wait_for_timeout(1000)

        # 수량 input에 박스 수 입력
        qty_input = await page.query_selector('.td-qty input')
        if qty_input:
            await qty_input.click()
            await qty_input.fill(str(box_qty))
            await page.wait_for_timeout(300)

        # 담기 버튼 클릭
        add_btn = await page.query_selector('button:has-text("담기")')
        if add_btn:
            await add_btn.click()
            await page.wait_for_timeout(2000)

        # 팝업/토스트 닫기
        try:
            confirm_btn = await page.query_selector(
                '.q-dialog button:has-text("확인")'
            )
            if confirm_btn:
                await confirm_btn.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass

        await self._screenshot(f"baekje_cart_{idx:02d}_{insurance_code}.png")

        result["success"] = True
        result["message"] = f"{result['pack_size']}T x{box_qty} 담기 완료"
        return result

    # ------ 주문확정 ------

    async def _confirm_order(self) -> None:
        btn = self._page.locator('button:has-text("주문등록")')
        await btn.click(force=True)
        await self._page.wait_for_timeout(5000)

    # ------ 테스트 ------

    async def test_order(self, headless: bool = True):
        order_list = [
            {"insurance_code": "646201260", "quantity": 45},
            {"insurance_code": "643501890", "quantity": 14},
        ]

        print("=" * 50)
        print("백제약품 주문 테스트 (dry_run)")
        for item in order_list:
            print(f"  보험코드: {item['insurance_code']}, 나간수량: {item['quantity']}정")
        print("=" * 50)

        result = await self.place_order_async(
            order_list, headless=headless, dry_run=True
        )

        print()
        print("=" * 50)
        print("주문 테스트 결과")
        print(f"  성공: {result['success']}")
        print(f"  메시지: {result['message']}")
        for r in result["results"]:
            status = "OK" if r["success"] else "FAIL"
            print(f"  [{status}] {r['insurance_code']} {r['drug_name']}"
                  f" - {r['pack_size']}T x{r['box_qty']}박스 ({r['message']})")
        print("=" * 50)


# === 직접 실행 ===
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    bj = BaekjeWholesaler()
    headless = "--visible" not in sys.argv
    asyncio.run(bj.test_order(headless=headless))
