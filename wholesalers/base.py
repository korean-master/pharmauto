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


def _prune_traces(traces_dir: str, keep: int = 10) -> None:
    """오래된 trace zip 파일을 keep 개만 남기고 삭제한다."""
    try:
        files = sorted(
            [f for f in os.listdir(traces_dir) if f.endswith(".zip")],
            reverse=True,
        )
        for old in files[keep:]:
            try:
                os.remove(os.path.join(traces_dir, old))
            except OSError:
                pass
    except OSError:
        pass


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
        # login_url: 로그인 페이지가 주문 페이지(url)와 다른 사이트용.
        # 없으면 url 로 폴백. (아남/백제/지오영 등)
        self.login_url = config.get("login_url") or self.url
        self.user_id = config.get("id", "")
        self.password = config.get("pw", "")
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self._progress_callback = None
        self._trace_path = None

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
            from datetime import datetime
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=headless)
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            # trace 시작 (오류 시에만 저장, 정상 완료 시 _close에서 폐기)
            ws_slug = self.name.replace(" ", "_") or "ws"
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._trace_path = os.path.join(
                paths.get_traces_dir(), f"{ws_slug}_{ts}.zip"
            )
            await self._context.tracing.start(screenshots=True, snapshots=True)
        except Exception as e:
            print(f"[Playwright 오류] {e}")
            raise RuntimeError("브라우저 연결에 실패했습니다. 프로그램을 재시작해 주세요.")

    async def _close(self, keep_trace: bool = False):
        if self._context:
            try:
                if keep_trace and self._trace_path:
                    await self._context.tracing.stop(path=self._trace_path)
                    self._progress(f"[Trace] 저장됨 → {self._trace_path}")
                    _prune_traces(os.path.dirname(self._trace_path))
                    # 백그라운드로 Supabase 업로드
                    try:
                        from core.cloud import upload_trace_async
                        upload_trace_async(
                            self._trace_path,
                            wid=getattr(self, "WID", "") or getattr(self, "_wid", "") or "",
                            wholesaler_name=self.name,
                        )
                    except Exception:
                        pass
                else:
                    await self._context.tracing.stop()
            except Exception:
                pass
            try:
                await self._context.close()
            except Exception:
                pass
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._context = None
        self._browser = None
        self._page = None
        self._playwright = None
        self._trace_path = None

    async def _close_popup(self):
        """공통 팝업/알림/모달 닫기. 페이지에 떠 있는 팝업을 자동 처리한다."""
        if not self._page:
            return
        try:
            # alert/confirm 다이얼로그 — accept 가 기본 (v1.5.47).
            # 자동화 중 뜨는 confirm 은 우리 자동화 흐름에서 발생한 거라 동의가 맞음.
            # dismiss 는 "정말 비우시겠습니까?" 같은 사용자 동의 필요 confirm 에서
            # 자동화를 중단시켜 담기/비우기 실패의 원인이 됨 (세화 사례).
            self._dismiss_handler = lambda d: d.accept()
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
        _has_error = False

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

                # 장바구니 담기 전: DOM 스냅샷 + (폴백용) 카운트
                cart_before_snapshot = await self._snapshot_tables()
                cart_before_count = await self._get_cart_count()

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

                # 1) 팝업/에러 메시지 감지
                if result["success"]:
                    fail_reason, is_oos = await self._detect_cart_failure()
                    if fail_reason:
                        result["success"] = False
                        result["message"] = fail_reason
                        if is_oos:
                            result["out_of_stock"] = True

                # 2) DOM diff 로 실제 담김 검증 (성공/실패 이분화)
                if result["success"]:
                    await self._page.wait_for_timeout(700)
                    verify = await self._verify_cart_added(
                        drug_name=result.get("drug_name", "") or "",
                        insurance_code=code,
                        before=cart_before_snapshot,
                    )
                    if verify.get("verified"):
                        result["verified"] = True
                        result["verify_match"] = verify.get("match", [])
                    else:
                        # 폴백: cart_count 증가했으면 provisional 성공 허용
                        cart_after_count = await self._get_cart_count()
                        if (
                            cart_before_count >= 0
                            and cart_after_count > cart_before_count
                        ):
                            result["verified"] = False
                            result["verify_fallback"] = "count_increased"
                        else:
                            # 실제로 담김 확인 안 됨 — 실패 처리
                            result["success"] = False
                            result["verified"] = False
                            result["message"] = (
                                f"장바구니 담김 확인 실패 "
                                f"({verify.get('reason', 'no row change')})"
                            )
                            # 품절일 수도 — 재주문 경로 타도록 표시
                            if cart_before_count >= 0 and cart_after_count == cart_before_count:
                                result["out_of_stock"] = True

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
                self._progress("주문확정 중...")
                await self._confirm_order()
                await self._screenshot(f"{prefix}_order_confirmed.png")
                order_result["success"] = True
                order_result["message"] = f"주문 완료! {success_count}개 품목{suffix}"
                self._progress(f"주문 완료! {success_count}개 품목{suffix}")

        except Exception as e:
            _has_error = True
            order_result["message"] = f"오류 발생: {e}"
            self._progress(f"오류: {e}")
            try:
                await self._screenshot(f"{prefix}_error.png")
            except Exception:
                pass

        finally:
            await self._close(keep_trace=_has_error)

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
        _has_error = False

        try:
            # 1. 로그인
            self._progress("연동 테스트: 로그인 중...")
            if not await self.login_async(headless=headless):
                _has_error = True
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
                _has_error = True
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
            _has_error = True
            return {"success": False, "stage": "error", "message": str(e)}
        finally:
            await self._close(keep_trace=_has_error)

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
            # v1.5.47: JSON 의 명시 셀렉터 (clear_all_btn) 우선 시도.
            # 도매상별 정확한 비우기 버튼이 명시돼 있으면 공통 패턴보다 안전.
            explicit_clear = ""
            try:
                sel_root = getattr(self, "_selectors", {}) or {}
                tbl_cfg = sel_root.get("table") or sel_root.get("table_sel") or {}
                if isinstance(tbl_cfg, dict):
                    explicit_clear = (tbl_cfg.get("clear_all_btn") or "").strip()
            except Exception:
                explicit_clear = ""

            # 공통 패턴 — JSON 명시가 있으면 그게 1순위, 그 다음 휴리스틱
            clear_selectors = []
            if explicit_clear:
                clear_selectors.append(explicit_clear)
            clear_selectors.extend([
                'button:has-text("전체삭제")',
                'button:has-text("비우기")',
                'button:has-text("전체 삭제")',
                'button:has-text("장바구니 비우기")',
                'a:has-text("전체삭제")',
                'span:has-text("전체삭제")',
                'span:has-text("비우기")',
            ])
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

    # ────── 장바구니 담김 DOM diff 검증 (공통) ──────

    _TABLE_SNAPSHOT_JS = r"""
    () => Array.from(document.querySelectorAll('table')).map((tbl, i) => {
      let text = '';
      try { text = (tbl.innerText || '').slice(0, 20000); } catch (_) {}
      return {
        idx: i,
        row_count: tbl.querySelectorAll('tbody tr, tr').length,
        text: text,
      };
    })
    """

    async def _snapshot_tables(self) -> list:
        """페이지의 모든 <table> 의 (idx, row_count, innerText) 스냅샷.

        v1.5.46: cart_iframe 셀렉터 설정돼있으면 iframe 내부 테이블도 포함.
        """
        if not self._page:
            return []
        try:
            snap = await self._page.evaluate(self._TABLE_SNAPSHOT_JS)
        except Exception:
            snap = []
        # v1.5.46: cart_iframe 안 테이블도 스냅샷에 포함
        try:
            table_cfg = (
                self._selectors.get("table", {})
                if hasattr(self, "_selectors") and self._selectors
                else {}
            )
            cart_iframe = table_cfg.get("cart_iframe", "") if table_cfg else ""
            if cart_iframe:
                iframe_el = await self._page.query_selector(cart_iframe)
                if iframe_el:
                    frame = await iframe_el.content_frame()
                    if frame:
                        iframe_snap = await frame.evaluate(
                            self._TABLE_SNAPSHOT_JS
                        )
                        if iframe_snap:
                            snap.extend(iframe_snap)
        except Exception:
            pass
        return snap

    async def _capture_screenshot_b64(self, max_bytes: int = 300_000) -> str:
        """현재 뷰포트 JPEG 스크린샷을 base64 문자열로 반환 (v1.5.41).

        실패 진단 업로드 용도. 300KB 넘으면 품질을 순차적으로 낮춰 재시도.
        캡처 불가 또는 끝까지 크면 빈 문자열.
        """
        import base64
        if not self._page:
            return ""
        for quality in (45, 25, 12):
            try:
                png = await self._page.screenshot(
                    type="jpeg", quality=quality, full_page=False
                )
                if png and len(png) <= max_bytes:
                    return base64.b64encode(png).decode("ascii")
            except Exception:
                continue
        return ""

    async def _verify_cart_added(
        self,
        drug_name: str,
        insurance_code: str,
        before: list,
        after: list | None = None,
    ) -> dict:
        """담기 전후 테이블 스냅샷 비교로 실제 담김 여부 검증.

        판정 기준:
            1. 어느 테이블의 row_count 가 증가했고
            2. 증가 부분의 텍스트에 보험코드 OR 약품명 토큰 다수 포함

        Returns:
            {'verified': bool, 'cart_table_idx': int, 'match': list,
             'rows_added': int} 또는 {'verified': False, 'reason': str}
        """
        import re

        if not before:
            return {"verified": False, "reason": "before snapshot empty"}

        if after is None:
            after = await self._snapshot_tables()
        if not after:
            return {"verified": False, "reason": "after snapshot empty"}

        # 약품명 주요 토큰 (2자 이상만) — 절반 이상 매칭되면 인정
        name_tokens = []
        if drug_name:
            name_tokens = [
                t for t in re.split(r'[\s()\[\]/\-]+', drug_name) if len(t) >= 2
            ]

        def _match(new_text: str) -> list[str]:
            hits = []
            if insurance_code and insurance_code in new_text:
                hits.append("code")
            if name_tokens:
                matched = sum(1 for t in name_tokens if t in new_text)
                if matched >= max(1, len(name_tokens) // 2):
                    hits.append(f"name({matched}/{len(name_tokens)})")
            return hits

        # 1차: 같은 인덱스 테이블끼리 비교
        for i in range(min(len(before), len(after))):
            b, a = before[i], after[i]
            if a["row_count"] <= b["row_count"]:
                continue
            new_text = (
                a["text"].replace(b["text"], "", 1)
                if b["text"] and b["text"] in a["text"]
                else a["text"]
            )
            hits = _match(new_text)
            if hits:
                return {
                    "verified": True,
                    "cart_table_idx": i,
                    "match": hits,
                    "rows_added": a["row_count"] - b["row_count"],
                }

        # 2차: 테이블 개수/순서가 바뀐 경우 — 전체 after 텍스트에 코드 있는지만
        if insurance_code:
            whole_after = "\n".join(a["text"] for a in after)
            whole_before = "\n".join(b["text"] for b in before)
            if insurance_code in whole_after and insurance_code not in whole_before:
                return {
                    "verified": True,
                    "cart_table_idx": -1,
                    "match": ["code(global)"],
                    "rows_added": 0,
                }

        return {"verified": False, "reason": "no table added matching row"}

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
