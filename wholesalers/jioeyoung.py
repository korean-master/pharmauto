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
            result["out_of_stock"] = True
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
            result["out_of_stock"] = True
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

        # 담기 성공 여부는 base._detect_cart_failure()에서 공통 판별
        result["success"] = True
        result["message"] = f"{chosen['std_text']} x{box_qty} 담기 완료"
        result["box_qty"] = box_qty
        return result

    # ------ 장바구니 카운트 ------

    async def _get_cart_count(self) -> int:
        """지오영 장바구니 아이템 수를 읽는다."""
        try:
            page = self._page
            # 장바구니 테이블 행 수
            rows = page.locator('#section_cart_body tr')
            count = await rows.count()
            if count > 0:
                return count
            # 또는 배지
            badge = page.locator('.cart-badge, .cart-count, #cartItemCount')
            if await badge.count() > 0:
                import re
                text = (await badge.first.inner_text()).strip()
                nums = re.sub(r'[^\d]', '', text)
                return int(nums) if nums else 0
        except Exception:
            pass
        return -1

    # ------ 주문확정 ------

    async def _confirm_order(self) -> None:
        await self._page.click('#section_cart_total_btn_order')
        await self._page.wait_for_timeout(3000)

    # ------ 입고이력 검색 ------

    async def search_history_async(self, drug_name: str,
                                   lot_number: str = "",
                                   headless: bool = True) -> list[dict]:
        """지오영 /MyPage/Serial(일련번호)에서 입고이력을 검색한다.

        메인 테이블: 출고일자[0], 전표번호[1], 창고명[2], 상품코드[3], 상품명[4],
                     수량[5], 단가[6], 금액[7], 출고수집[8], 수집대상[9]
        상세 테이블(행 클릭 후): NO.[0], 유효기한[1], LOT번호[2], 일련번호[3]
        """
        results = []
        try:
            self._progress(f"지오영 입고이력 검색: {drug_name}")
            ok = await self.login_async(headless=headless)
            if not ok:
                self._progress("지오영 로그인 실패")
                return results

            page = self._page

            # 일련번호 페이지
            await page.goto(
                "https://bpm.geoweb.kr/MyPage/Serial",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            await page.wait_for_timeout(2000)

            # 날짜 범위 5년
            from datetime import datetime, timedelta
            date_from = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
            date_to = datetime.now().strftime("%Y-%m-%d")

            await page.fill("#dtpFrom", "")
            await page.fill("#dtpFrom", date_from)
            await page.fill("#dtpTo", "")
            await page.fill("#dtpTo", date_to)

            # 약품명 입력 + 검색
            await page.fill("#txtitem", drug_name)
            await page.click("button.btn_search")
            await page.wait_for_timeout(4000)

            # 메인 테이블 파싱
            main_table = page.locator("table").first
            rows = main_table.locator("tbody tr")
            count = await rows.count()
            self._progress(f"지오영 검색 결과: {count}건")

            import re

            # 검색어에서 키워드 추출 (예: "자누메트 50/1000" → ["자누메트", "50/1000"])
            search_keywords = [k.strip() for k in drug_name.split() if k.strip()]

            for i in range(min(count, 50)):
                try:
                    row = rows.nth(i)
                    cells = row.locator("td")
                    cell_count = await cells.count()
                    if cell_count < 6:
                        continue

                    delivery_date = (await cells.nth(0).inner_text()).strip()
                    drug = (await cells.nth(4).inner_text()).strip()
                    qty_text = (await cells.nth(5).inner_text()).strip()

                    if not drug or "없습니다" in drug or "조회" in drug:
                        continue

                    # 검색 키워드가 모두 포함된 행만 대상
                    drug_lower = drug.lower()
                    name_match = all(
                        kw.lower() in drug_lower for kw in search_keywords
                    )

                    nums = re.sub(r'[^\d]', '', qty_text)
                    result = {
                        "drug_name": drug,
                        "order_date": delivery_date,
                        "qty": int(nums) if nums else 0,
                        "lot_number": "",
                        "expiry": "",
                        "wholesaler_id": "geo",
                        "wholesaler_name": "지오영",
                        "source": "지오영",
                        "matched": False,
                    }

                    # 키워드 매칭된 행만 클릭해서 LOT 확인
                    if lot_number and name_match:
                        try:
                            await row.click()
                            await page.wait_for_timeout(2000)

                            # 모달 내 상세 테이블: NO., 유효기한, LOT번호, 일련번호
                            modal = page.locator(".ui-dialog .popup_contents table")
                            if await modal.count() > 0:
                                d_rows = modal.locator("tbody tr")
                                d_count = await d_rows.count()
                                for di in range(min(d_count, 20)):
                                    d_cells = d_rows.nth(di).locator("td")
                                    if await d_cells.count() >= 3:
                                        d_expiry = (await d_cells.nth(1).inner_text()).strip()
                                        d_lot = (await d_cells.nth(2).inner_text()).strip()
                                        if d_lot:
                                            result["lot_number"] = d_lot
                                            result["expiry"] = d_expiry
                                            if lot_number.lower() in d_lot.lower():
                                                result["matched"] = True
                                            break

                            # 모달 닫기
                            close_btn = page.locator(
                                '.ui-dialog button:has-text("닫기")'
                            ).first
                            if await close_btn.count() > 0:
                                await close_btn.click()
                            else:
                                # X 버튼
                                x_btn = page.locator(
                                    '.ui-dialog .ui-dialog-titlebar-close'
                                ).first
                                if await x_btn.count() > 0:
                                    await x_btn.click()
                            await page.wait_for_timeout(500)
                        except Exception:
                            # 모달이 남아있으면 강제 닫기
                            try:
                                await page.keyboard.press("Escape")
                                await page.wait_for_timeout(500)
                            except Exception:
                                pass

                    results.append(result)
                except Exception:
                    continue

        except Exception as e:
            self._progress(f"지오영 이력 검색 오류: {e}")
        finally:
            await self._close()

        return results

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
