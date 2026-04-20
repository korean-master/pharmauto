"""도매상 연동 베이스 클래스 — Playwright 공통 로직 포함."""

import asyncio
import math
import os
import re
import sys
from abc import ABC, abstractmethod

from playwright.async_api import async_playwright

from core import paths


# ────────────────────── 공통 유틸 ──────────────────────

def parse_pack_size(std_text: str) -> int:
    """규격 텍스트에서 포장 수량을 추출한다.

    예: '30T' → 30, '500C' → 500, '30정' → 30, '100캡슐' → 100,
        '30T/Box' → 30, '60mg/1정*30' → 30, '30tab' → 30
    """
    if not std_text:
        return 0
    s = std_text.strip()

    # 1) "30T", "500C", "30Tab" 패턴
    m = re.search(r'(\d+)\s*[TtCc](?:ab|ap)?', s)
    if m:
        return int(m.group(1))

    # 2) "30정", "100캡슐", "30포", "30매" 패턴
    m = re.search(r'(\d+)\s*(?:정|캡슐|포|캡|매|병|개)', s)
    if m:
        return int(m.group(1))

    # 3) "*30" 또는 "x30" 패턴 (예: "60mg/1정*30")
    m = re.search(r'[*xX×]\s*(\d+)', s)
    if m:
        return int(m.group(1))

    # 4) 마지막 숫자 (예: "록소탄 30")
    m = re.findall(r'(\d+)', s)
    if m:
        val = int(m[-1])
        if val >= 5:  # 5 미만은 용량일 가능성 높음
            return val

    return 0


def choose_best_pack(candidates: list[dict], quantity: int,
                     preferred_unit: int | None = None) -> dict:
    """필요 수량에 가장 적합한 규격을 선택한다.

    Args:
        candidates: [{"pack_size": int, ...}, ...] — pack_size > 0인 항목만
        quantity: 필요한 총 수량 (정 단위)
        preferred_unit: 선호 규격. 있으면 정확히 매칭 시도.

    Returns:
        선택된 candidate dict. box_qty 키가 추가됨.
    """
    if not candidates:
        raise ValueError("candidates가 비어 있음")

    if preferred_unit:
        # 선호규격이 설정되어 있으면 항상 존중 (4배 초과 판단은 UI에서 사전 처리)
        for c in candidates:
            if c["pack_size"] == preferred_unit:
                c["box_qty"] = max(1, math.ceil(quantity / c["pack_size"]))
                return c

        # 정확한 매칭 실패 → 선호규격보다 작거나 같은 것 중 가장 가까운 규격
        smaller = [c for c in candidates if c["pack_size"] <= preferred_unit]
        if smaller:
            chosen = max(smaller, key=lambda c: c["pack_size"])
        else:
            # 선호규격보다 작은 게 없으면 가장 작은 규격
            chosen = min(candidates, key=lambda c: c["pack_size"])
        chosen["box_qty"] = max(1, math.ceil(quantity / chosen["pack_size"]))
        return chosen

    # 선호규격 미설정(0 또는 None)이면 최소 단위를 기본으로 선택
    chosen = min(candidates, key=lambda c: c["pack_size"])
    chosen["box_qty"] = max(1, math.ceil(quantity / chosen["pack_size"]))
    return chosen


def _cloud_upload_units(insurance_code: str, pack_sizes: list[int]):
    """발견된 규격을 클라우드에 백그라운드 업로드."""
    import threading
    def _upload():
        try:
            from core.cloud import upload_units
            upload_units(insurance_code, pack_sizes)
        except Exception:
            pass
    threading.Thread(target=_upload, daemon=True).start()


# ────────────────────── 베이스 클래스 ──────────────────────

class WholesalerBase(ABC):
    """모든 도매상 연동 클래스의 베이스.

    Playwright 브라우저 관리, 스크린샷, 진행 알림,
    place_order_async 공통 흐름(로그인→장바구니→주문확정)을 제공한다.
    서브클래스는 login_async / _add_item_to_cart / _confirm_order만 구현하면 된다.
    """

    def __init__(self, config: dict):
        self.name = config.get("name", "")
        self.url = config.get("url", "")
        self.user_id = config.get("id", "")
        self.password = config.get("pw", "")
        self._browser = None
        self._page = None
        self._playwright = None
        self._progress_callback = None

    def set_progress_callback(self, callback):
        self._progress_callback = callback

    def _progress(self, msg: str):
        print(f"[{self.name}] {msg}")
        if self._progress_callback:
            self._progress_callback(msg)

    # ────── Playwright lifecycle ──────

    async def _launch(self, headless: bool = True):
        # 번들된 Chromium 경로 설정 (PyInstaller/Nuitka/개발 공통)
        if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
            bundle_dir = os.path.dirname(sys.executable)
            candidates = [
                os.path.join(bundle_dir, "playwright_browsers"),
                os.path.join(bundle_dir, "_internal", "playwright_browsers"),
            ]
            for browsers_dir in candidates:
                if os.path.exists(browsers_dir):
                    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_dir
                    break

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=headless)
            self._page = await self._browser.new_page()
        except Exception as e:
            print(f"[Playwright 오류] {e}")
            raise RuntimeError("브라우저 연결에 실패했습니다. 프로그램을 재시작해 주세요.")

    async def _close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._page = None
        self._playwright = None

    async def _close_popup(self):
        """공통 팝업/알림/모달 닫기. 페이지에 떠 있는 팝업을 자동 처리한다."""
        if not self._page:
            return
        try:
            # alert/confirm 다이얼로그 — 핸들러 참조 저장 (나중에 교체 가능)
            self._dismiss_handler = lambda d: d.dismiss()
            self._page.on("dialog", self._dismiss_handler)
        except Exception:
            pass
        # 일반적인 닫기 버튼 패턴
        close_selectors = [
            "button.close", ".modal .close", "[aria-label='Close']",
            ".popup-close", ".btn-close", ".layer_close",
            "button:has-text('닫기')", "button:has-text('확인')",
        ]
        for sel in close_selectors:
            try:
                btn = self._page.locator(sel).first
                if await btn.is_visible(timeout=300):
                    await btn.click(force=True)
                    await self._page.wait_for_timeout(300)
            except Exception:
                pass

    async def _screenshot(self, filename: str) -> str:
        path = os.path.join(paths.get_screenshots_dir(), filename)
        await self._page.screenshot(path=path, full_page=True)
        return path

    # ────── 서브클래스가 구현할 메서드 ──────

    @abstractmethod
    async def login_async(self, headless: bool = True) -> bool:
        """도매상 사이트에 로그인한다."""
        ...

    @abstractmethod
    async def _add_item_to_cart(self, insurance_code: str, quantity: int,
                                idx: int, total: int,
                                preferred_unit: int | None = None) -> dict:
        """약품을 검색하고 장바구니에 담는다.

        Returns:
            {"success", "insurance_code", "quantity", "box_qty",
             "pack_size", "drug_name", "message", "unit_options"}
        """
        ...

    @abstractmethod
    async def _confirm_order(self) -> None:
        """장바구니의 주문을 최종 확정한다."""
        ...

    # ────── 공통 주문 흐름 ──────

    async def place_order_async(
        self, items: list[dict], headless: bool = True, dry_run: bool = True
    ) -> dict:
        """약품 주문을 실행한다 (로그인 → 장바구니 → 주문확정).

        Args:
            items: [{"insurance_code": str, "quantity": int,
                     "preferred_unit": int|None}, ...]
            headless: 브라우저 숨김 여부
            dry_run: True면 주문확정 직전에 멈춤

        Returns:
            {"success", "message", "results": list, "failed_items": list}
        """
        order_result = {
            "success": False,
            "message": "",
            "results": [],
            "failed_items": [],
        }
        prefix = self.name.replace(" ", "_").lower()

        try:
            # 1. 로그인
            if not await self.login_async(headless=headless):
                order_result["message"] = "로그인 실패"
                order_result["failed_items"] = items
                return order_result

            # 2. 각 약품을 장바구니에 담기
            from core.drug_prefs import get_preferred_unit

            total = len(items)
            for idx, item in enumerate(items, 1):
                code = item.get("insurance_code", "")
                qty = item.get("quantity", 1)
                if not code:
                    continue

                preferred = item.get("preferred_unit") or get_preferred_unit(code)

                # 장바구니 담기 전 카운트
                cart_before = await self._get_cart_count()

                try:
                    result = await self._add_item_to_cart(
                        code, qty, idx, total, preferred_unit=preferred
                    )
                except Exception as e:
                    result = {
                        "success": False,
                        "insurance_code": code,
                        "quantity": qty,
                        "message": str(e),
                        "drug_name": "",
                    }

                # 3단계 검증: 1) _add_item_to_cart 자체 판단
                if result["success"]:
                    # 2) 팝업/에러 메시지 감지
                    fail_reason, is_oos = await self._detect_cart_failure()
                    if fail_reason:
                        result["success"] = False
                        result["message"] = fail_reason
                        if is_oos:
                            result["out_of_stock"] = True

                if result["success"]:
                    # 3) 장바구니 카운트 변화 확인
                    await self._page.wait_for_timeout(500)
                    cart_after = await self._get_cart_count()
                    if cart_before >= 0 and cart_after >= 0:
                        if cart_after <= cart_before:
                            result["success"] = False
                            result["message"] = "장바구니에 추가되지 않음 (품절 가능)"
                            result["out_of_stock"] = True
                    else:
                        # 카운트 확인 불가 — 조용한 성공 방지용 미확인 플래그
                        result["unverified"] = True
                        result["message"] = (
                            "자동 확인 불가 — 도매상 사이트에서 장바구니 직접 확인 필요"
                        )
                        self._progress(
                            f"  [{code}] ⚠️ 담기 완료 표시됐으나 장바구니 카운트 "
                            f"확인 불가 — 실제 담김 수동 확인 필요"
                        )

                order_result["results"].append(result)
                if not result["success"]:
                    order_result["failed_items"].append(item)
                    self._progress(
                        f"  [{code}] 실패: {result.get('message', '')} ({idx}/{total})"
                    )

                # 발견된 규격을 클라우드에 기여
                if result.get("unit_options"):
                    _cloud_upload_units(code, result["unit_options"])

                # 도매상 차단 방지: 품목 간 딜레이
                if idx < total:
                    await self._page.wait_for_timeout(2000)

            # 장바구니 최종 스크린샷
            await self._screenshot(f"{prefix}_cart_final.png")

            success_count = sum(1 for r in order_result["results"] if r["success"])
            unverified_count = sum(
                1 for r in order_result["results"]
                if r.get("success") and r.get("unverified")
            )
            fail_count = len(order_result["results"]) - success_count
            if success_count == 0:
                fail_reasons = [r.get("message", "") for r in order_result["results"] if not r["success"]]
                reason = fail_reasons[0] if fail_reasons else "장바구니 담기 실패"
                order_result["message"] = reason
                self._progress(f"주문 실패: {reason}")
                return order_result

            # 3. 주문확정
            notes = []
            if fail_count:
                notes.append(f"실패 {fail_count}건")
            if unverified_count:
                notes.append(f"⚠️ 미확인 {unverified_count}건 (수동 확인 필요)")
            suffix = f" ({', '.join(notes)})" if notes else ""
            if dry_run:
                self._progress(
                    f"장바구니 {success_count}건 완료{suffix}"
                )
                order_result["success"] = True
                order_result["message"] = (
                    f"장바구니 {success_count}건 완료{suffix}"
                )
            else:
                if unverified_count == success_count:
                    # 전부 미확인 — 주문확정 위험, 보류
                    order_result["success"] = False
                    order_result["message"] = (
                        "⚠️ 모든 항목이 담김 확인 불가 — 주문확정 보류. "
                        "도매상 사이트에서 장바구니 직접 확인 필요"
                    )
                    self._progress(order_result["message"])
                    return order_result
                self._progress("주문확정 중...")
                await self._confirm_order()
                await self._screenshot(f"{prefix}_order_confirmed.png")
                order_result["success"] = True
                order_result["message"] = f"주문 완료! {success_count}개 품목{suffix}"
                self._progress(f"주문 완료! {success_count}개 품목{suffix}")

        except Exception as e:
            order_result["message"] = f"오류 발생: {e}"
            self._progress(f"오류: {e}")
            try:
                await self._screenshot(f"{prefix}_error.png")
            except Exception:
                pass

        finally:
            await self._close()

        return order_result

    # ────── 연동 테스트 ──────

    async def test_connection(self, headless: bool = True) -> dict:
        """도매상 연동을 단계별 테스트한다 (로그인 → 장바구니 → 삭제).

        Returns:
            {"success": bool, "stage": str, "message": str}
            stage: "login", "cart", "done" 중 어디까지 성공했는지
        """
        # 테스트용 약품 (범용 - 거의 모든 도매상에 있는 약)
        TEST_CODES = ["645601261", "643501890", "646201260"]

        try:
            # 1. 로그인
            self._progress("연동 테스트: 로그인 중...")
            if not await self.login_async(headless=headless):
                return {"success": False, "stage": "login", "message": "로그인 실패"}

            # 2. 장바구니 테스트 (테스트 약품으로 시도)
            self._progress("연동 테스트: 장바구니 테스트 중...")
            cart_ok = False
            for code in TEST_CODES:
                try:
                    result = await self._add_item_to_cart(
                        code, 1, 1, 1, preferred_unit=None
                    )
                    if result.get("success"):
                        cart_ok = True
                        self._progress(f"연동 테스트: 장바구니 담기 성공 ({result.get('drug_name', code)})")
                        break
                except Exception:
                    continue

            if not cart_ok:
                return {"success": False, "stage": "cart", "message": "장바구니 담기 실패"}

            # 3. 장바구니 비우기 — 테스트 약품이 남으면 실주문 위험
            self._progress("연동 테스트: 장바구니 정리 중...")
            cart_cleared = False
            try:
                await self._clear_cart()
                # 비우기 후 카운트 확인
                remaining = await self._get_cart_count()
                cart_cleared = remaining <= 0
            except Exception:
                pass

            if not cart_cleared:
                self._progress("연동 테스트: 완료 (장바구니 수동 확인 필요)")
                return {
                    "success": True, "stage": "done",
                    "message": "연동 정상 (테스트 약품 장바구니 수동 삭제 필요)",
                }

            self._progress("연동 테스트: 완료!")
            return {"success": True, "stage": "done", "message": "연동 정상"}

        except Exception as e:
            return {"success": False, "stage": "error", "message": str(e)}
        finally:
            await self._close()

    async def _clear_cart(self):
        """장바구니를 비운다. 서브클래스에서 오버라이드 가능."""
        page = self._page
        if not page:
            return

        # 삭제 확인 다이얼로그를 accept 해야 하므로 핸들러 교체
        if hasattr(self, '_dismiss_handler'):
            page.remove_listener("dialog", self._dismiss_handler)
        _accept_handler = lambda d: d.accept()
        page.on("dialog", _accept_handler)

        try:
            # 공통 패턴으로 장바구니 비우기 시도
            clear_selectors = [
                'button:has-text("전체삭제")',
                'button:has-text("비우기")',
                'button:has-text("전체 삭제")',
                'button:has-text("장바구니 비우기")',
                'a:has-text("전체삭제")',
            ]
            for sel in clear_selectors:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await page.wait_for_timeout(1000)
                        # 프레임워크 확인 팝업 (window.confirm이 아닌 경우)
                        for confirm_sel in ['button:has-text("확인")', 'button:has-text("예")']:
                            try:
                                confirm = await page.query_selector(confirm_sel)
                                if confirm and await confirm.is_visible():
                                    await confirm.click()
                                    await page.wait_for_timeout(1000)
                                    break
                            except Exception:
                                pass
                        return
                except Exception:
                    continue
        finally:
            # 핸들러 복원
            page.remove_listener("dialog", _accept_handler)
            if hasattr(self, '_dismiss_handler'):
                page.on("dialog", self._dismiss_handler)

    # ────── 동기 래퍼 ──────

    def login(self) -> bool:
        return asyncio.run(self.login_async())

    def place_order(self, items: list[dict]) -> dict:
        return asyncio.run(self.place_order_async(items, dry_run=True))

    def check_stock(self, insurance_code: str) -> bool:
        return False

    def request_return(self, drug_name: str, lot_number: str, qty: int) -> dict:
        return {"success": False, "message": "미구현"}

    # ────── 장바구니 카운트 확인 ──────

    async def _get_cart_count(self) -> int:
        """현재 장바구니에 담긴 아이템 수를 반환한다.

        Returns:
            아이템 수. 확인 불가하면 -1.
        서브클래스에서 오버라이드하여 각 사이트에 맞게 구현.
        """
        if not self._page:
            return -1

        # 공통 패턴: 장바구니 배지/카운트 텍스트 탐색
        page = self._page
        cart_selectors = [
            '.cart-count', '.badge', '#cartCount',
            '[class*="cart"] .count', '[class*="cart"] .badge',
        ]
        for sel in cart_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    text = (await el.inner_text()).strip()
                    import re
                    nums = re.sub(r'[^\d]', '', text)
                    if nums:
                        return int(nums)
            except Exception:
                continue

        # 장바구니 테이블 행 수로 추정
        try:
            for sel in ['#cart-table tbody tr', '.cart-list tr',
                        'table.cart tbody tr']:
                rows = page.locator(sel)
                if await rows.count() > 0:
                    return await rows.count()
        except Exception:
            pass

        return -1

    # ────── 장바구니 실패 감지 (공통) ──────

    # 품절(재고 없음)로 판단되는 키워드 — out_of_stock 플래그 설정
    _STOCKOUT_KEYWORDS = [
        "품절", "재고 부족", "재고부족", "재고가 없", "재고없",
        "공급 불가", "공급불가",
    ]

    # 기타 실패 키워드 (품절은 아니지만 담기 실패)
    _FAIL_KEYWORDS = [
        *_STOCKOUT_KEYWORDS,
        "주문 불가", "주문불가", "판매 중지", "판매중지",
        "취급 불가", "취급불가",
        "없습니다", "실패", "오류",
    ]

    async def _detect_cart_failure(self) -> tuple[str, bool]:
        """장바구니 담기 직후 에러 팝업/메시지를 공통 감지한다.

        Returns:
            (실패 사유 문자열, 품절 여부). 실패 아니면 ("", False).
        """
        if not self._page:
            return ""

        page = self._page

        # 1) 모달/다이얼로그 텍스트 확인
        dialog_selectors = [
            ".q-dialog",
            ".modal",
            ".layerpopup",
            ".popup",
            '[role="dialog"]',
            ".alert",
            ".toast",
        ]
        for sel in dialog_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    text = (await el.inner_text()).strip()
                    for kw in self._FAIL_KEYWORDS:
                        if kw in text:
                            # 팝업 닫기 시도
                            close = el.locator(
                                'button:has-text("확인"), '
                                'button:has-text("닫기"), '
                                'button:has-text("Close")'
                            ).first
                            if await close.count() > 0:
                                try:
                                    await close.click(timeout=2000)
                                except Exception:
                                    pass
                            is_oos = kw in self._STOCKOUT_KEYWORDS
                            return kw, is_oos
            except Exception:
                continue

        # 2) 페이지 전체에서 눈에 보이는 에러 메시지 (빨간색 텍스트 등)
        try:
            error_els = page.locator(
                '.error, .text-red, .text-danger, '
                '[class*="error"], [class*="alert-danger"]'
            )
            count = await error_els.count()
            for i in range(min(count, 3)):
                el = error_els.nth(i)
                if await el.is_visible():
                    text = (await el.inner_text()).strip()
                    for kw in self._FAIL_KEYWORDS:
                        if kw in text:
                            is_oos = kw in self._STOCKOUT_KEYWORDS
                            return kw, is_oos
        except Exception:
            pass

        return "", False

    # ────── 입고이력 검색 ──────

    async def search_history_async(self, drug_name: str,
                                   lot_number: str = "",
                                   headless: bool = True) -> list[dict]:
        """도매상 사이트에서 입고(주문) 이력을 검색한다.

        Args:
            drug_name: 약품명 (필수)
            lot_number: 로트번호/제조번호 (있으면 정확한 매칭)

        Returns:
            [{"drug_name", "order_date", "qty", "lot_number",
              "wholesaler_id", "wholesaler_name", "source", "matched"}, ...]
            matched=True면 로트번호까지 매칭된 확정 결과
        """
        return []

    def search_history(self, drug_name: str, lot_number: str = "",
                       headless: bool = True) -> list[dict]:
        """search_history_async 동기 래퍼."""
        return asyncio.run(
            self.search_history_async(drug_name, lot_number, headless)
        )
