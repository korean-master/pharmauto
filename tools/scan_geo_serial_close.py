"""지오영 일련번호 — 행 클릭 → 상세 → 닫기 패턴 파악."""

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

        await page.goto("https://bpm.geoweb.kr/MyPage/Serial",
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        date_from = (datetime.now() - timedelta(days=365*5)).strftime("%Y-%m-%d")
        date_to = datetime.now().strftime("%Y-%m-%d")
        await page.fill("#dtpFrom", "")
        await page.fill("#dtpFrom", date_from)
        await page.fill("#dtpTo", "")
        await page.fill("#dtpTo", date_to)
        await page.fill("#txtitem", "자누메트")
        await page.click("button.btn_search")
        await page.wait_for_timeout(4000)

        main_table = page.locator("table").first
        rows = main_table.locator("tbody tr")
        count = await rows.count()
        print(f"검색 결과: {count}건")

        # 처음 3행만 테스트 — 클릭 → 상세 읽기 → 닫기 패턴 파악
        for i in range(min(3, count)):
            row = rows.nth(i)
            drug = (await row.locator("td").nth(4).inner_text()).strip()[:30]
            print(f"\n--- row[{i}]: {drug} ---")

            # 행 클릭
            await row.click()
            await page.wait_for_timeout(2000)

            # 상세 테이블 확인
            all_tables = page.locator("table")
            t_count = await all_tables.count()
            print(f"  테이블 수: {t_count}")

            if t_count > 1:
                detail = all_tables.nth(1)
                d_rows = detail.locator("tbody tr")
                d_count = await d_rows.count()
                print(f"  상세 행: {d_count}")
                for di in range(min(d_count, 3)):
                    cells = d_rows.nth(di).locator("td")
                    c_count = await cells.count()
                    texts = []
                    for ci in range(c_count):
                        texts.append((await cells.nth(ci).inner_text()).strip()[:25])
                    print(f"    detail[{di}]: {texts}")

            # 닫기 버튼/방법 찾기
            print("  닫기 방법 탐색...")

            # 1) 닫기/X 버튼
            close_btns = page.locator(
                'button:has-text("닫기"), button:has-text("X"), '
                'button:has-text("Close"), .btn_close, .close, '
                'button.modal-close, .layerpopup button'
            )
            close_count = await close_btns.count()
            print(f"  닫기 버튼: {close_count}개")
            for ci in range(close_count):
                btn = close_btns.nth(ci)
                text = (await btn.inner_text()).strip()[:20]
                cls = await btn.get_attribute("class") or ""
                visible = await btn.is_visible()
                print(f"    [{ci}] text={text} class={cls[:30]} visible={visible}")

            # 2) 같은 행 다시 클릭하면 토글?
            # 3) ESC 키?
            # 4) 모달 바깥 클릭?

            # 스크린샷
            ss = os.path.join(ROOT, "screenshots", f"geo_serial_detail_{i}.png")
            await page.screenshot(path=ss, full_page=True)
            print(f"  스크린샷: {ss}")

            # ESC 시도
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(1000)
            t_after = await page.locator("table").count()
            print(f"  ESC 후 테이블 수: {t_after}")

            if t_after > 1:
                # 같은 행 다시 클릭 시도
                await row.click()
                await page.wait_for_timeout(1000)
                t_after2 = await page.locator("table").count()
                print(f"  재클릭 후 테이블 수: {t_after2}")

        print("\n30초 대기...")
        await page.wait_for_timeout(30000)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
