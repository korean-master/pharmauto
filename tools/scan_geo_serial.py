"""지오영 일련번호(/MyPage/Serial) 페이지 구조 분석."""

import asyncio
import os
import sys

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
        # 로그인
        await page.goto("https://bpm.geoweb.kr/", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await page.fill("#LoginID", geo["id"])
        await page.fill("#Password", geo["pw"])
        await page.click("button.btn_login")
        await page.wait_for_timeout(3000)
        print(f"로그인 후: {page.url}")

        # 일련번호 페이지
        await page.goto("https://bpm.geoweb.kr/MyPage/Serial",
                        wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)
        print(f"일련번호 페이지: {page.url}")

        # 검색 요소 분석
        print("\n--- 검색 요소 ---")
        inputs = await page.query_selector_all("input:visible")
        for i, inp in enumerate(inputs):
            inp_id = await inp.get_attribute("id") or ""
            inp_name = await inp.get_attribute("name") or ""
            inp_type = await inp.get_attribute("type") or ""
            inp_ph = await inp.get_attribute("placeholder") or ""
            inp_class = await inp.get_attribute("class") or ""
            print(f"  input[{i}] id={inp_id} name={inp_name} type={inp_type} ph={inp_ph} class={inp_class[:30]}")

        selects = await page.query_selector_all("select:visible")
        for i, sel in enumerate(selects):
            sel_id = await sel.get_attribute("id") or ""
            sel_name = await sel.get_attribute("name") or ""
            options = await sel.query_selector_all("option")
            opt_texts = [(await o.inner_text()).strip() for o in options[:10]]
            print(f"  select[{i}] id={sel_id} name={sel_name} opts={opt_texts}")

        buttons = await page.query_selector_all("button:visible")
        for i, btn in enumerate(buttons):
            text = (await btn.inner_text()).strip()[:40]
            btn_id = await btn.get_attribute("id") or ""
            btn_class = await btn.get_attribute("class") or ""
            onclick = await btn.get_attribute("onclick") or ""
            if text:
                print(f"  button[{i}] text={text} id={btn_id} class={btn_class[:30]} onclick={onclick[:40]}")

        # 테이블
        print("\n--- 테이블 ---")
        tables = await page.query_selector_all("table")
        for ti, table in enumerate(tables):
            headers = await table.query_selector_all("th")
            h_texts = [(await h.inner_text()).strip() for h in headers]
            rows = await table.query_selector_all("tbody tr")
            print(f"  table[{ti}] headers={h_texts} rows={len(rows)}")

        # 자누메트로 검색 테스트
        print("\n--- 자누메트 검색 테스트 ---")
        search_input = page.locator(
            '#txtitem, input[name="txtitem"], '
            'input[placeholder*="제품"], input[placeholder*="상품"], '
            'input[placeholder*="검색"]'
        ).first
        if await search_input.count() > 0:
            await search_input.fill("자누메트")
            print("  검색어 입력: 자누메트")
        else:
            # 모든 input에 시도
            for inp in inputs:
                inp_type = await inp.get_attribute("type") or ""
                if inp_type == "text":
                    await inp.fill("자누메트")
                    print(f"  input에 검색어 입력")
                    break

        # 검색 버튼 클릭
        search_btn = page.locator(
            'button:has-text("검색"), button:has-text("조회"), '
            'button.btn_search, #btnSearch'
        ).first
        if await search_btn.count() > 0:
            await search_btn.click()
            print("  검색 버튼 클릭")
            await page.wait_for_timeout(4000)

        # 검색 결과 테이블 확인
        print("\n--- 검색 결과 ---")
        tables = await page.query_selector_all("table")
        for ti, table in enumerate(tables):
            headers = await table.query_selector_all("th")
            h_texts = [(await h.inner_text()).strip() for h in headers]
            rows = await table.query_selector_all("tbody tr")
            print(f"  table[{ti}] headers={h_texts} rows={len(rows)}")
            for ri, row in enumerate(rows[:5]):
                cells = await row.query_selector_all("td")
                c_texts = [(await c.inner_text()).strip()[:25] for c in cells]
                print(f"    row[{ri}]: {c_texts}")

        # 첫 번째 결과 클릭해서 상세 보기
        first_rows = await tables[0].query_selector_all("tbody tr") if tables else []
        if first_rows:
            print("\n--- 첫 번째 행 클릭 ---")
            await first_rows[0].click()
            await page.wait_for_timeout(3000)

            # 새로 열린 상세 정보 분석
            print("  현재 URL:", page.url)

            # 상세 테이블 or 팝업
            detail_tables = await page.query_selector_all("table")
            for ti, table in enumerate(detail_tables):
                headers = await table.query_selector_all("th")
                h_texts = [(await h.inner_text()).strip() for h in headers]
                rows = await table.query_selector_all("tbody tr")
                if h_texts and h_texts != [(await h.inner_text()).strip() for h in (await tables[0].query_selector_all("th")) if tables]:
                    print(f"  상세 table[{ti}] headers={h_texts} rows={len(rows)}")
                    for ri, row in enumerate(rows[:5]):
                        cells = await row.query_selector_all("td")
                        c_texts = [(await c.inner_text()).strip()[:25] for c in cells]
                        print(f"    row[{ri}]: {c_texts}")

        ss_path = os.path.join(ROOT, "screenshots", "geo_serial.png")
        await page.screenshot(path=ss_path, full_page=True)
        print(f"\n스크린샷: {ss_path}")

        print("\n30초 대기...")
        await page.wait_for_timeout(30000)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
