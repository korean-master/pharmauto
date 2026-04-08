"""지오영 도매상 자동화 - Playwright 기반."""

import asyncio
import json
import os
import sys

from wholesalers.base import WholesalerBase, choose_best_pack, parse_pack_size

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "wholesalers.json")


def _load_geo_config() -> dict:
    from core.crypto import load_wholesalers_secure
    return load_wholesalers_secure().get("geo", {})


class JioeyoungWholesaler(WholesalerBase):
    """지오영(GEO) 도매상 Playwright 자동화."""

    LOGIN_URL = "https://bpm.geoweb.kr/"

    def __init__(self, config: dict | None = None):
        if config is None:
            config = _load_geo_config()
        super().__init__(config)

    # ------ 로그인 ------

    async def login_async(self, headless: bool = True) -> bool:
        if not self._page:
            await self._launch(headless=headless)
        page = self._page

        self._progress("로그인 중...")

        await page.goto(self.LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        await page.fill('#LoginID', self.user_id)
        await page.fill('#Password', self.password)
        await page.click('button.btn_login')
        await page.wait_for_timeout(3000)

        login_success = not await page.query_selector('#LoginID')

        if login_success:
            self._progress("로그인 성공")
            await self._screenshot("jioeyoung_01_login.png")
        else:
            self._progress("로그인 실패")
            await self._screenshot("jioeyoung_01_login_fail.png")

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
        await page.fill('#txt_product', '')
        await page.wait_for_timeout(300)
        await page.fill('#txt_product', insurance_code)
        await page.click('button.btn_search')
        await page.wait_for_timeout(2000)

        # 검색 결과 행들 수집
        rows = await page.query_selector_all('#tbodySearchProduct tr.tr-product-list')
        if not rows:
            result["message"] = "검색 결과 없음"
            self._progress(f"  [{insurance_code}] 검색 결과 없음 ({idx}/{total})")
            return result

        # 재고 있는 행들을 규격별로 수집
        candidates = []
        for row in rows:
            stock_el = await row.query_selector('td.stock span')
            std_el = await row.query_selector('td.standard')
            name_el = await row.query_selector('td.proName')
            price_el = await row.query_selector('td.price')

            stock = 0
            if stock_el:
                stock_text = (await stock_el.inner_text()).strip()
                stock = int(stock_text) if stock_text.isdigit() else 0

            std_text = (await std_el.inner_text()).strip() if std_el else ""
            pack_size = parse_pack_size(std_text)
            drug_name = (await name_el.inner_text()).strip() if name_el else ""

            # 가격 수집
            pack_price = 0
            if price_el:
                price_text = (await price_el.inner_text()).strip()
                price_text = price_text.replace(",", "").replace("원", "")
                try:
                    pack_price = int(price_text)
                except ValueError:
                    pass

            if stock > 0 and pack_size > 0:
                candidates.append({
                    "row": row, "stock": stock, "pack_size": pack_size,
                    "drug_name": drug_name, "std_text": std_text,
                    "pack_price": pack_price,
                })

        if not candidates:
            result["message"] = "재고 없음"
            self._progress(f"  [{insurance_code}] 재고 없음 ({idx}/{total})")
            return result

        # 사용 가능한 규격 목록
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
            f"  {chosen['drug_name']} 장바구니 담는 중... ({idx}/{total})"
        )

        # 행 클릭
        await chosen["row"].click()
        await page.wait_for_timeout(1000)

        # 수량 입력
        await page.fill('#product-detail-qty', str(box_qty))
        await page.wait_for_timeout(300)

        # 담기 버튼 클릭
        await page.click('#product-detail-btn-add-product')
        await page.wait_for_timeout(1500)

        # 팝업 처리 (중복 상품 등)
        try:
            dialog_btn = await page.query_selector('.layerpopup .btn_basic')
            if dialog_btn:
                await dialog_btn.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass

        await self._screenshot(f"jioeyoung_cart_{idx:02d}_{insurance_code}.png")

        result["success"] = True
        result["message"] = f"{chosen['std_text']} x{box_qty} 담기 완료"
        return result

    # ------ 주문확정 ------

    async def _confirm_order(self) -> None:
        await self._page.click('#section_cart_total_btn_order')
        await self._page.wait_for_timeout(3000)

    # ------ 테스트 ------

    async def test_run(self, headless: bool = True):
        try:
            print("=" * 50)
            print("지오영 자동화 테스트 시작")
            print("=" * 50)
            success = await self.login_async(headless=headless)
            if success:
                await self._screenshot("jioeyoung_main.png")
                print("테스트 완료!")
            else:
                print("로그인 실패로 테스트 중단")
        finally:
            await self._close()

    async def test_order(self, headless: bool = True):
        order_list = [
            {"insurance_code": "646201260", "quantity": 45},
            {"insurance_code": "643501890", "quantity": 14},
        ]

        print("=" * 50)
        print("지오영 주문 테스트 (dry_run)")
        for item in order_list:
            print(f"  보험코드: {item['insurance_code']}, 나간수량: {item['quantity']}정")
        print("=" * 50)

        result = await self.place_order_async(order_list, headless=headless, dry_run=True)

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

    geo = JioeyoungWholesaler()
    headless = "--visible" not in sys.argv

    if "--order" in sys.argv:
        asyncio.run(geo.test_order(headless=headless))
    else:
        asyncio.run(geo.test_run(headless=headless))
