"""도매상 주문이력/반품 페이지의 정확한 구조를 파악하는 스크립트."""

import asyncio
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from playwright.async_api import async_playwright


async def analyze_geo_mypage():
    """지오영 /MyPage (주문내역) 페이지 구조 분석."""
    from core.crypto import load_wholesalers_secure
    ws = load_wholesalers_secure()
    geo = ws.get("geo", {})

    print("=" * 60)
    print("  지오영 주문내역 (/MyPage) 구조 분석")
    print("=" * 60)

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
        print(f"로그인 완료: {page.url}")

        # 주문내역 페이지
        await page.goto("https://bpm.geoweb.kr/MyPage", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        print(f"주문내역 페이지: {page.url}")

        # 페이지 전체 구조 분석
        print("\n--- 검색 관련 요소 ---")

        # select 요소들
        selects = await page.query_selector_all("select")
        for i, sel in enumerate(selects):
            sel_id = await sel.get_attribute("id") or ""
            sel_name = await sel.get_attribute("name") or ""
            sel_class = await sel.get_attribute("class") or ""
            options = await sel.query_selector_all("option")
            opt_texts = []
            for opt in options[:8]:
                opt_texts.append((await opt.inner_text()).strip())
            print(f"  select[{i}] id={sel_id} name={sel_name} class={sel_class}")
            print(f"    options: {opt_texts}")

        # input 요소들
        inputs = await page.query_selector_all("input:visible")
        for i, inp in enumerate(inputs):
            inp_id = await inp.get_attribute("id") or ""
            inp_name = await inp.get_attribute("name") or ""
            inp_type = await inp.get_attribute("type") or ""
            inp_ph = await inp.get_attribute("placeholder") or ""
            inp_class = await inp.get_attribute("class") or ""
            print(f"  input[{i}] id={inp_id} name={inp_name} type={inp_type} placeholder={inp_ph} class={inp_class}")

        # 버튼들
        buttons = await page.query_selector_all("button:visible")
        for i, btn in enumerate(buttons):
            btn_text = (await btn.inner_text()).strip()[:40]
            btn_id = await btn.get_attribute("id") or ""
            btn_class = await btn.get_attribute("class") or ""
            btn_onclick = await btn.get_attribute("onclick") or ""
            if btn_text:
                print(f"  button[{i}] text={btn_text} id={btn_id} class={btn_class} onclick={btn_onclick}")

        # 테이블 구조
        print("\n--- 테이블 구조 ---")
        tables = await page.query_selector_all("table")
        for ti, table in enumerate(tables):
            t_id = await table.get_attribute("id") or ""
            t_class = await table.get_attribute("class") or ""
            print(f"\n  table[{ti}] id={t_id} class={t_class}")

            headers = await table.query_selector_all("th")
            h_texts = []
            for h in headers:
                h_texts.append((await h.inner_text()).strip())
            print(f"    headers: {h_texts}")

            rows = await table.query_selector_all("tbody tr")
            print(f"    rows: {len(rows)}")
            if rows:
                first_row = rows[0]
                cells = await first_row.query_selector_all("td")
                c_texts = []
                for c in cells:
                    c_texts.append((await c.inner_text()).strip()[:30])
                print(f"    first row: {c_texts}")

        # 스크린샷
        ss_path = os.path.join(ROOT, "screenshots", "geo_mypage.png")
        os.makedirs(os.path.dirname(ss_path), exist_ok=True)
        await page.screenshot(path=ss_path, full_page=True)
        print(f"\n스크린샷: {ss_path}")

        print("\n30초 동안 브라우저를 열어둡니다...")
        await page.wait_for_timeout(30000)

    finally:
        await browser.close()
        await pw.stop()


async def analyze_baekje_return():
    """백제약품 /dist/return (반품) 페이지 구조 분석."""
    from core.crypto import load_wholesalers_secure
    ws = load_wholesalers_secure()
    baekje = ws.get("baekje", {})

    print("\n" + "=" * 60)
    print("  백제약품 반품 (/dist/return) 구조 분석")
    print("=" * 60)

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    page = await browser.new_page()
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

    try:
        # 로그인
        await page.goto("http://www.ibjp.kr/dist/login", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await page.fill('input[type="text"]', baekje["id"])
        await page.fill('input[type="password"]', baekje["pw"])
        await page.click("button.login_btn")
        await page.wait_for_timeout(4000)
        print(f"로그인 완료: {page.url}")

        # 반품 페이지
        await page.goto("http://www.ibjp.kr/dist/return", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        print(f"반품 페이지: {page.url}")

        # 검색 관련 요소
        print("\n--- 검색 관련 요소 ---")

        selects = await page.query_selector_all("select")
        for i, sel in enumerate(selects):
            sel_id = await sel.get_attribute("id") or ""
            sel_name = await sel.get_attribute("name") or ""
            sel_class = await sel.get_attribute("class") or ""
            options = await sel.query_selector_all("option")
            opt_texts = []
            for opt in options[:8]:
                opt_texts.append((await opt.inner_text()).strip())
            print(f"  select[{i}] id={sel_id} name={sel_name} class={sel_class[:40]}")
            print(f"    options: {opt_texts}")

        inputs = await page.query_selector_all("input:visible")
        for i, inp in enumerate(inputs):
            inp_id = await inp.get_attribute("id") or ""
            inp_name = await inp.get_attribute("name") or ""
            inp_type = await inp.get_attribute("type") or ""
            inp_ph = await inp.get_attribute("placeholder") or ""
            print(f"  input[{i}] id={inp_id} name={inp_name} type={inp_type} placeholder={inp_ph}")

        buttons = await page.query_selector_all("button:visible")
        for i, btn in enumerate(buttons):
            btn_text = (await btn.inner_text()).strip()[:40]
            btn_id = await btn.get_attribute("id") or ""
            btn_class = await btn.get_attribute("class") or ""
            if btn_text:
                print(f"  button[{i}] text={btn_text} id={btn_id} class={btn_class[:40]}")

        # 테이블 구조
        print("\n--- 테이블 구조 ---")
        tables = await page.query_selector_all("table")
        for ti, table in enumerate(tables):
            t_id = await table.get_attribute("id") or ""
            t_class = await table.get_attribute("class") or ""
            print(f"\n  table[{ti}] id={t_id} class={t_class[:40]}")

            headers = await table.query_selector_all("th")
            h_texts = []
            for h in headers:
                h_texts.append((await h.inner_text()).strip())
            print(f"    headers: {h_texts}")

            rows = await table.query_selector_all("tbody tr")
            print(f"    rows: {len(rows)}")
            if rows:
                first_row = rows[0]
                cells = await first_row.query_selector_all("td")
                c_texts = []
                for c in cells:
                    c_texts.append((await c.inner_text()).strip()[:30])
                print(f"    first row: {c_texts}")

        # 스크린샷
        ss_path = os.path.join(ROOT, "screenshots", "baekje_return.png")
        os.makedirs(os.path.dirname(ss_path), exist_ok=True)
        await page.screenshot(path=ss_path, full_page=True)
        print(f"\n스크린샷: {ss_path}")

        print("\n30초 동안 브라우저를 열어둡니다...")
        await page.wait_for_timeout(30000)

    finally:
        await browser.close()
        await pw.stop()


async def main():
    await analyze_geo_mypage()
    await analyze_baekje_return()


if __name__ == "__main__":
    asyncio.run(main())
