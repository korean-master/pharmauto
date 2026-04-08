"""도매상 연동 베이스 클래스 — Playwright 공통 로직 포함."""

import asyncio
import math
import os
import re
import sys
from abc import ABC, abstractmethod

from playwright.async_api import async_playwright

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "screenshots")


# ────────────────────── 공통 유틸 ──────────────────────

def parse_pack_size(std_text: str) -> int:
    """규격 텍스트에서 포장 수량을 추출한다. 예: '30T' → 30, '500C' → 500."""
    m = re.search(r'(\d+)\s*[TtCc]', std_text)
    return int(m.group(1)) if m else 0


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

    # 선호규격 미설정(0 또는 None)이면 최소 단위를 기본으로 선택
    if not preferred_unit:
        chosen = min(candidates, key=lambda c: c["pack_size"])
    else:
        # 선호규격이 있었지만 매칭 실패(해당 규격 없음) 시, 낭비 최소화 규격 선택
        chosen = min(
            candidates,
            key=lambda c: (
                math.ceil(quantity / c["pack_size"]) * c["pack_size"] - quantity,
                math.ceil(quantity / c["pack_size"]),
            ),
        )
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
        # PyInstaller 패키징 시 번들된 Chromium 경로 설정
        if getattr(sys, 'frozen', False):
            bundle_dir = os.path.dirname(sys.executable)
            browsers_dir = os.path.join(bundle_dir, "playwright_browsers")
            if os.path.exists(browsers_dir):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_dir

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=headless)
        self._page = await self._browser.new_page()

    async def _close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._page = None
        self._playwright = None

    async def _screenshot(self, filename: str) -> str:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        path = os.path.join(SCREENSHOT_DIR, filename)
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

                result = await self._add_item_to_cart(
                    code, qty, idx, total, preferred_unit=preferred
                )
                order_result["results"].append(result)
                if not result["success"]:
                    order_result["failed_items"].append(item)

                # 발견된 규격을 클라우드에 기여
                if result.get("unit_options"):
                    _cloud_upload_units(code, result["unit_options"])

            # 장바구니 최종 스크린샷
            await self._screenshot(f"{prefix}_cart_final.png")

            success_count = sum(1 for r in order_result["results"] if r["success"])
            if success_count == 0:
                order_result["message"] = "장바구니에 담긴 약품 없음"
                self._progress("장바구니에 담긴 약품이 없습니다")
                return order_result

            # 3. 주문확정
            if dry_run:
                self._progress(
                    f"테스트 모드 - {success_count}건 장바구니 담기 완료 (주문확정 안함)"
                )
                order_result["success"] = True
                order_result["message"] = (
                    f"테스트 완료 - {success_count}건 (주문확정 안함)"
                )
            else:
                self._progress("주문확정 중...")
                await self._confirm_order()
                await self._screenshot(f"{prefix}_order_confirmed.png")
                order_result["success"] = True
                order_result["message"] = f"주문 완료! {success_count}개 품목"
                self._progress(f"주문 완료! {success_count}개 품목")

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

            # 3. 장바구니 비우기 시도 (실패해도 OK - 사이트마다 다름)
            self._progress("연동 테스트: 장바구니 정리 중...")
            try:
                await self._clear_cart()
            except Exception:
                pass  # 장바구니 비우기는 실패해도 테스트 성공

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
                    # 확인 팝업
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

    # ────── 동기 래퍼 ──────

    def login(self) -> bool:
        return asyncio.run(self.login_async())

    def place_order(self, items: list[dict]) -> dict:
        return asyncio.run(self.place_order_async(items, dry_run=True))

    def check_stock(self, insurance_code: str) -> bool:
        return False

    def request_return(self, drug_name: str, lot_number: str, qty: int) -> dict:
        return {"success": False, "message": "미구현"}
