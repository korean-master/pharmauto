"""지오영 일련번호 모달 닫기 셀렉터 파악."""

import asyncio
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from playwright.async_api import async_playwright


async def main():
    from core.crypto import load_wholesalers_secure
    ws = load_wholesalers_secure()
    geo = ws.get("geo", {})

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    page = await browser.new_page()
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

    try:
        await page.goto("https://bpm.geoweb.kr/", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await page.fill("#LoginID", geo["id"])
        await page.fill("#Password", geo["pw"])
        await page.click("button.btn_login")
        await page.wait_for_timeout(3000)

        await page.goto("https://bpm.geoweb.kr/MyPage/Serial", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        date_from = (datetime.now() - timedelta(days=365*5)).strftime("%Y-%m-%d")
        await page.fill("#dtpFrom", "")
        await page.fill("#dtpFrom", date_from)
        await page.fill("#txtitem", "자누메트")
        await page.click("button.btn_search")
        await page.wait_for_timeout(4000)

        # 첫 행 클릭
        row = page.locator("table").first.locator("tbody tr").first
        await row.click()
        await page.wait_for_timeout(2000)

        # 모달 내부 모든 요소 분석
        print("=== 모달 요소 분석 ===")

        # 모달/팝업 컨테이너
        modals = await page.query_selector_all(".modal, .popup, .layerpopup, [class*='modal'], [class*='popup'], [class*='layer'], [role='dialog']")
        print(f"모달 컨테이너: {len(modals)}개")
        for i, m in enumerate(modals):
            cls = await m.get_attribute("class") or ""
            mid = await m.get_attribute("id") or ""
            visible = await m.is_visible()
            print(f"  [{i}] id={mid} class={cls[:50]} visible={visible}")

        # X 버튼 (닫기)
        print("\n닫기 관련 요소:")
        close_candidates = await page.query_selector_all(
            "button.close, .btn-close, .modal-close, "
            "[class*='close'], [aria-label='Close'], "
            "button:has-text('X'), button:has-text('닫기'), "
            "a:has-text('X'), a.close, span.close"
        )
        for i, el in enumerate(close_candidates):
            tag = await el.evaluate("el => el.tagName")
            text = (await el.inner_text()).strip()[:20] if tag != "SPAN" else ""
            cls = await el.get_attribute("class") or ""
            visible = await el.is_visible()
            onclick = await el.get_attribute("onclick") or ""
            print(f"  [{i}] {tag} text='{text}' class={cls[:40]} visible={visible} onclick={onclick[:40]}")

        # 모달 내부의 버튼들
        print("\n모달 영역 버튼:")
        # 화면에 보이는 모든 버튼
        all_btns = await page.query_selector_all("button:visible")
        for i, btn in enumerate(all_btns):
            text = (await btn.inner_text()).strip()[:20]
            cls = await btn.get_attribute("class") or ""
            onclick = await btn.get_attribute("onclick") or ""
            if text in ["닫기", "X", "확인", "취소", "Close"] or "close" in cls.lower():
                print(f"  button[{i}] text='{text}' class={cls[:40]} onclick={onclick[:40]}")

        print("\n30초 대기 (모달을 직접 확인하세요)...")
        await page.wait_for_timeout(30000)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
