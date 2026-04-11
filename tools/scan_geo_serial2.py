"""지오영 일련번호 — 날짜 넓혀서 자누메트 검색."""

import asyncio
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from playwright.async_api import async_playwright
from datetime import datetime, timedelta


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

        # 날짜 5년으로 설정
        date_from = (datetime.now() - timedelta(days=365*5)).strftime("%Y-%m-%d")
        date_to = datetime.now().strftime("%Y-%m-%d")

        await page.fill("#dtpFrom", "")
        await page.fill("#dtpFrom", date_from)
        await page.fill("#dtpTo", "")
        await page.fill("#dtpTo", date_to)
        await page.fill("#txtitem", "자누메트")
        await page.click("button.btn_search")
        await page.wait_for_timeout(5000)

        print(f"검색 완료. URL: {page.url}")

        # 테이블 분석
        tables = await page.query_selector_all("table")
        for ti, table in enumerate(tables):
            headers = await table.query_selector_all("th")
            h_texts = [(await h.inner_text()).strip() for h in headers]
            rows = await table.query_selector_all("tbody tr")
            print(f"\ntable[{ti}] headers={h_texts}")
            print(f"  rows: {len(rows)}")
            for ri, row in enumerate(rows[:5]):
                cells = await row.query_selector_all("td")
                c_texts = []
                for c in cells:
                    t = (await c.inner_text()).strip()[:25]
                    c_texts.append(t)
                print(f"  row[{ri}] ({len(cells)} cells): {c_texts}")

        # 첫 행 클릭해서 상세 확인
        first_table_rows = await tables[0].query_selector_all("tbody tr") if tables else []
        if len(first_table_rows) > 0:
            first_text = await first_table_rows[0].inner_text()
            if "없습니다" not in first_text:
                print("\n--- 첫 행 클릭 ---")
                await first_table_rows[0].click()
                await page.wait_for_timeout(3000)

                # 새로 나타난 요소 확인
                all_tables = await page.query_selector_all("table")
                print(f"클릭 후 테이블 수: {len(all_tables)}")
                for ti, table in enumerate(all_tables):
                    headers = await table.query_selector_all("th")
                    h_texts = [(await h.inner_text()).strip() for h in headers]
                    rows = await table.query_selector_all("tbody tr")
                    if h_texts:
                        print(f"\ntable[{ti}] headers={h_texts} rows={len(rows)}")
                        for ri, row in enumerate(rows[:3]):
                            cells = await row.query_selector_all("td")
                            c_texts = [(await c.inner_text()).strip()[:30] for c in cells]
                            print(f"  row[{ri}]: {c_texts}")

                # 팝업/모달 확인
                modals = await page.query_selector_all(".modal, .popup, .layerpopup, [class*='detail']")
                print(f"\n모달/팝업: {len(modals)}개")
                for m in modals:
                    text = (await m.inner_text()).strip()[:200]
                    if text:
                        print(f"  내용: {text}")

        ss = os.path.join(ROOT, "screenshots", "geo_serial_data.png")
        await page.screenshot(path=ss, full_page=True)
        print(f"\n스크린샷: {ss}")

        await page.wait_for_timeout(30000)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
