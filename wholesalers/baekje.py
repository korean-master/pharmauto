"""백제약품 도매상 자동화 - Playwright 기반."""

import asyncio
import json
import math
import os
import sys

from wholesalers.base import WholesalerBase, choose_best_pack, parse_pack_size


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

            # 로그인 후 팝업/다이얼로그 자동 닫기
            await self._close_popup(page)
        else:
            self._progress("로그인 실패")
            await self._screenshot("baekje_01_login_fail.png")

        return login_success

    @staticmethod
    async def _close_popup(page):
        """백제약품 q-dialog 팝업을 닫는다."""
        for _ in range(3):
            try:
                close = page.locator(
                    '.q-dialog button:has-text("닫기"), '
                    '.q-dialog button:has-text("확인"), '
                    '.q-dialog button:has-text("취소"), '
                    '.q-dialog .q-btn--flat'
                ).first
                if await close.count() > 0 and await close.is_visible():
                    await close.click(timeout=3000)
                    await page.wait_for_timeout(1000)
                else:
                    break
            except Exception:
                break

    # ------ 약품 검색 & 장바구니 담기 ------

    async def _add_item_to_cart(self, insurance_code: str, quantity: int,
                                idx: int, total: int,
                                preferred_unit: int | None = None) -> dict:
        page = self._page
        result = {"success": False, "insurance_code": insurance_code,
                  "quantity": quantity, "box_qty": 0, "pack_size": 0,
                  "drug_name": "", "message": "", "unit_options": []}

        # 팝업 닫기 후 검색
        await self._close_popup(page)

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
            result["out_of_stock"] = True
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

            print(f"[규격 파싱] '{unit_text}' → {pack_size}T ({drug_name})")

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
            print(f"[규격 선택] 선호={preferred_unit}, 후보={unit_options}, 수량={quantity}")
            chosen = choose_best_pack(candidates, quantity, preferred_unit)
            box_qty = chosen["box_qty"]
            print(f"[규격 선택] → {chosen['pack_size']}T x{box_qty}")

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

        # 팝업이 가리면 먼저 닫기
        await self._close_popup(page)

        # 해당 행 클릭하여 선택
        try:
            await chosen["row"].click(force=True)
        except Exception:
            await self._close_popup(page)
            await chosen["row"].click(force=True)
        await page.wait_for_timeout(1000)

        # 수량 input에 박스 수 입력 — 선택된 행 안에서 찾기
        qty_input = await chosen["row"].query_selector('.td-qty input')
        if not qty_input:
            # 폴백: 페이지 전체에서 찾기 (행이 1개뿐일 때)
            qty_input = await page.query_selector('.td-qty input')
        if qty_input:
            await qty_input.click(force=True)
            await qty_input.fill(str(box_qty))
            await page.wait_for_timeout(300)

        # 담기 버튼 — 선택된 행 안에서 먼저 찾기
        await self._close_popup(page)
        add_btn = await chosen["row"].query_selector('.td-add button')
        if not add_btn:
            add_btn = await page.query_selector('button:has-text("담기")')
        if add_btn:
            await add_btn.click(force=True)
            await page.wait_for_timeout(2000)

        # 팝업 닫기
        try:
            await page.wait_for_timeout(1000)
            confirm_btn = page.locator('.q-dialog button:has-text("확인")').first
            if await confirm_btn.count() > 0:
                await confirm_btn.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass

        await self._screenshot(f"baekje_cart_{idx:02d}_{insurance_code}.png")

        # 담기 성공 여부는 base._detect_cart_failure()에서 공통 판별
        result["success"] = True
        result["message"] = f"{result['pack_size']}T x{box_qty} 담기 완료"
        return result

    # ------ 장바구니 카운트 ------

    async def _get_cart_count(self) -> int:
        """백제약품 장바구니 아이템 수를 읽는다."""
        import re
        try:
            page = self._page
            # "주문 (1)" 형태 — 모든 a/span 태그에서 검색
            all_els = await page.query_selector_all('a, span')
            for el in all_els:
                try:
                    text = (await el.inner_text()).strip()
                    m = re.match(r'^주문\s*\((\d+)\)$', text)
                    if m:
                        return int(m.group(1))
                except Exception:
                    continue

            # "총 주문 품목 N 건" 형태
            content = await page.content()
            m = re.search(r'총\s*주문\s*품목\s*(\d+)', content)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return -1

    # ------ 장바구니 비우기 ------

    async def _clear_cart(self):
        """백제약품 장바구니를 비운다."""
        page = self._page
        if not page:
            return

        # 삭제 확인 다이얼로그를 accept 해야 하므로 핸들러 교체
        if hasattr(self, '_dismiss_handler'):
            page.remove_listener("dialog", self._dismiss_handler)
        _accept_handler = lambda d: d.accept()
        page.on("dialog", _accept_handler)

        try:
            # 주문 페이지로 이동 (장바구니 목록이 여기에 있음)
            await page.goto(
                "http://www.ibjp.kr/dist/order",
                wait_until="domcontentloaded",
                timeout=10000,
            )
            await page.wait_for_timeout(2000)

            # 전체 선택 체크박스
            select_all = page.locator(
                'th input[type="checkbox"], '
                'thead input[type="checkbox"], '
                '.q-checkbox:first-child'
            ).first
            if await select_all.count() > 0:
                await select_all.click(force=True)
                await page.wait_for_timeout(500)
                self._progress("장바구니 전체 선택 완료")

            # 삭제 버튼
            deleted = False
            for sel in [
                'button:has-text("삭제")',
                'button:has-text("선택삭제")',
                'button:has-text("전체삭제")',
                'a:has-text("삭제")',
            ]:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(force=True)
                    await page.wait_for_timeout(1500)

                    # Quasar 프레임워크 확인 팝업 (window.confirm이 아닌 경우)
                    confirm = page.locator(
                        '.q-dialog button:has-text("확인"), '
                        '.q-dialog button:has-text("예")'
                    ).first
                    if await confirm.count() > 0:
                        await confirm.click(force=True)
                        await page.wait_for_timeout(1000)
                    deleted = True
                    break

            if deleted:
                self._progress("장바구니 비우기 완료")
            else:
                self._progress("장바구니 삭제 버튼 못 찾음 (비어있을 수 있음)")
        except Exception as e:
            self._progress(f"장바구니 비우기 실패: {e}")
        finally:
            # 핸들러 복원
            page.remove_listener("dialog", _accept_handler)
            if hasattr(self, '_dismiss_handler'):
                page.on("dialog", self._dismiss_handler)

    # ------ 주문확정 ------

    async def _confirm_order(self) -> None:
        btn = self._page.locator('button:has-text("주문등록")')
        await btn.click(force=True)
        await self._page.wait_for_timeout(5000)

    # ------ 입고이력 검색 ------

    async def search_history_async(self, drug_name: str,
                                   lot_number: str = "",
                                   headless: bool = True) -> list[dict]:
        """백제약품 /dist/return(반품) 페이지에서 입고이력을 검색한다.

        이 페이지에는 품목명 + 제조번호(로트번호) 검색 필드가 있어서
        정확한 매칭이 가능하다.

        검색 요소:
          - input[placeholder*="품목명/보험코드"] : 약품명
          - input[placeholder*="제조번호"] : 로트번호
          - button:has-text("3년") : 기간 3년
          - button:has-text("검색") : 검색 실행
        테이블[0]: 품명, 입고, 규격, 수량, 반품, 거래회수, 단가, 이력, 반품가능수량
        테이블[1]: 주문일자, 단가, 유효기간, 제조번호, 납입수량
        """
        results = []
        try:
            self._progress(f"백제약품 입고이력 검색: {drug_name}")
            ok = await self.login_async(headless=headless)
            if not ok:
                self._progress("백제약품 로그인 실패")
                return results

            page = self._page

            # 반품 페이지 (입고이력 검색 포함)
            await page.goto(
                "http://www.ibjp.kr/dist/return",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            await page.wait_for_timeout(2000)

            # 팝업/다이얼로그가 있으면 먼저 닫기
            try:
                close_btn = page.locator(
                    '.q-dialog button:has-text("닫기"), '
                    '.q-dialog button:has-text("확인"), '
                    '.q-dialog button:has-text("취소"), '
                    '.q-dialog .q-btn--flat'
                ).first
                if await close_btn.count() > 0:
                    await close_btn.click(timeout=3000)
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            # 기간을 최대(3년)로 설정
            btn_period = page.locator('button:has-text("3년")')
            if await btn_period.count() > 0:
                await btn_period.first.click(force=True)
                await page.wait_for_timeout(500)

            # 약품명 검색
            search_input = page.locator(
                'input[placeholder*="품목명"], input[placeholder*="보험코드"]'
            ).first
            await search_input.fill(drug_name)

            # 제조번호(로트번호) 입력
            if lot_number:
                lot_input = page.locator('input[placeholder*="제조번호"]').first
                if await lot_input.count() > 0:
                    await lot_input.fill(lot_number)

            # 검색 버튼
            search_btn = page.locator('button:has-text("검색")').first
            await search_btn.click()
            await page.wait_for_timeout(4000)

            # 로트번호 검색 시 → 매칭된 결과만 나오므로 matched=True
            has_lot = bool(lot_number)

            # 모든 테이블 파싱 (메인 + 상세)
            all_tables = page.locator("table.q-table")
            table_count = await all_tables.count()
            self._progress(f"백제약품 테이블 {table_count}개 발견")

            # 키워드 필터링
            search_keywords = [k.strip() for k in drug_name.split() if k.strip()]

            # 메인 테이블 (테이블0): 품명[0], 규격[1], [2], 수량[3], 반품[4],
            #   거래처[5], 단가[6], 이력[7], 반품가능수량[8]
            if table_count > 0:
                main_rows = all_tables.nth(0).locator("tbody tr")
                main_count = await main_rows.count()

                for i in range(min(main_count, 50)):
                    try:
                        row = main_rows.nth(i)
                        cells = row.locator("td")
                        cell_count = await cells.count()
                        if cell_count < 5:
                            continue

                        drug = (await cells.nth(0).inner_text()).strip()
                        spec = (await cells.nth(1).inner_text()).strip()
                        returnable = (await cells.nth(8).inner_text()).strip() if cell_count > 8 else ""

                        if not drug or "없습니다" in drug or "검색" in drug:
                            continue

                        import re
                        if re.match(r'^\d{4}-\d{2}-\d{2}', drug):
                            continue

                        # 키워드 필터링
                        drug_lower = drug.lower()
                        if not all(kw.lower() in drug_lower for kw in search_keywords):
                            continue

                        # 행 클릭해서 상세(주문이력) 테이블 로드
                        await row.click()
                        await page.wait_for_timeout(2000)

                        # 상세 테이블의 기간도 3년으로 설정
                        detail_period = page.locator('button:has-text("3년")')
                        if await detail_period.count() > 1:
                            await detail_period.nth(1).click(force=True)
                            await page.wait_for_timeout(2000)

                        # 상세 테이블(테이블1)에서 주문일자/로트번호 파싱
                        detail_table = page.locator("table.q-table").nth(1)
                        detail_rows = detail_table.locator("tbody tr")
                        detail_count = await detail_rows.count()

                        if detail_count == 0 or "없습니다" in (await detail_rows.nth(0).inner_text()):
                            # 주문이력 없으면 메인 정보만으로 결과 추가
                            results.append({
                                "drug_name": drug,
                                "order_date": "",
                                "spec": spec,
                                "qty": 0,
                                "returnable_qty": self._extract_number(returnable),
                                "lot_number": "",
                                "wholesaler_id": "baekje",
                                "wholesaler_name": "백제약품",
                                "source": "백제약품",
                                "matched": False,
                            })
                            continue

                        for d in range(min(detail_count, 20)):
                            try:
                                d_cells = detail_rows.nth(d).locator("td")
                                d_cc = await d_cells.count()
                                if d_cc < 4:
                                    continue
                                d_date = (await d_cells.nth(0).inner_text()).strip()
                                d_expiry = (await d_cells.nth(2).inner_text()).strip() if d_cc > 2 else ""
                                d_lot = (await d_cells.nth(3).inner_text()).strip() if d_cc > 3 else ""
                                d_qty = (await d_cells.nth(4).inner_text()).strip() if d_cc > 4 else ""

                                if not d_date or "없습니다" in d_date:
                                    continue
                                if not re.match(r'^\d{4}-\d{2}-\d{2}', d_date):
                                    continue

                                lot_matched = (
                                    lot_number and d_lot and
                                    lot_number.lower() in d_lot.lower()
                                )

                                results.append({
                                    "drug_name": drug,
                                    "order_date": d_date,
                                    "spec": spec,
                                    "qty": self._extract_number(d_qty),
                                    "returnable_qty": self._extract_number(returnable),
                                    "lot_number": d_lot,
                                    "wholesaler_id": "baekje",
                                    "wholesaler_name": "백제약품",
                                    "source": "백제약품",
                                    "matched": lot_matched,
                                })
                            except Exception:
                                continue

                    except Exception:
                        continue

            # (하위 호환) 로트번호 직접 검색 — 상세 테이블에서 추가 매칭
            if table_count > 1 and has_lot:
                detail_rows = all_tables.nth(1).locator("tbody tr")
                detail_count = await detail_rows.count()

                for i in range(min(detail_count, 20)):
                    try:
                        row = detail_rows.nth(i)
                        cells = row.locator("td")
                        cell_count = await cells.count()
                        if cell_count < 4:
                            continue

                        d_date = (await cells.nth(0).inner_text()).strip()
                        d_expiry = (await cells.nth(2).inner_text()).strip() if cell_count > 2 else ""
                        d_lot = (await cells.nth(3).inner_text()).strip() if cell_count > 3 else ""
                        d_qty = (await cells.nth(4).inner_text()).strip() if cell_count > 4 else ""

                        if not d_date or "없습니다" in d_date:
                            continue

                        import re
                        if not re.match(r'^\d{4}-\d{2}-\d{2}', d_date):
                            continue

                        # 로트번호가 일치하면 해당 결과를 matched=True로
                        lot_matched = (
                            lot_number and d_lot and
                            lot_number.lower() in d_lot.lower()
                        )
                        for r in results:
                            if not r.get("detail_date"):
                                r["detail_date"] = d_date
                                r["lot_number"] = d_lot
                                r["expiry"] = d_expiry
                                r["detail_qty"] = self._extract_number(d_qty)
                                if lot_matched:
                                    r["matched"] = True
                                break
                    except Exception:
                        continue

        except Exception as e:
            self._progress(f"백제약품 이력 검색 오류: {e}")
        finally:
            await self._close()

        return results

    @staticmethod
    def _extract_number(text: str) -> int:
        import re
        nums = re.sub(r'[^\d]', '', text)
        return int(nums) if nums else 0

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
