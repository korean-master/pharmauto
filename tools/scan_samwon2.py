"""삼원약품 사이트 — 정확한 로그인 + 매출원장 분석."""

import asyncio
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from playwright.async_api import async_playwright


async def main():
    from core.crypto import load_wholesalers_secure
    ws = load_wholesalers_secure()
    samwon = ws.get("삼원약품", {})

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    page = await browser.new_page()
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

    try:
        await page.goto("https://www.pharmbox.co.kr/", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # 정확한 셀렉터로 로그인
        await page.fill("#P_H_USER_ID", samwon["id"])
        await page.fill("#P_H_PWD", samwon["pw"])

        # 로그인 버튼 찾기
        login_btn = page.locator('button:has-text("로그인"), a:has-text("로그인"), input[value="로그인"]').first
        if await login_btn.count() > 0:
            await login_btn.click()
            print("로그인 버튼 클릭 (텍스트)")
        else:
            # 폼 제출 시도
            await page.keyboard.press("Enter")
            print("Enter로 로그인 시도")

        await page.wait_for_timeout(4000)
        print(f"로그인 후 URL: {page.url}")

        # 로그인 확인
        content = await page.content()
        if "로그아웃" in content or "logout" in content.lower():
            print("로그인 성공!")
        else:
            print("로그인 실패 가능성 — 수동 확인 필요")
            # 다른 버튼 시도
            all_btns = await page.query_selector_all("button, a, input[type='button'], input[type='submit']")
            for btn in all_btns:
                text = ""
                try:
                    tag = await btn.evaluate("el => el.tagName")
                    if tag == "INPUT":
                        text = await btn.get_attribute("value") or ""
                    else:
                        text = (await btn.inner_text()).strip()
                except:
                    pass
                onclick = await btn.get_attribute("onclick") or ""
                if "login" in (text + onclick).lower() or "로그인" in text:
                    print(f"  발견: {text} onclick={onclick[:50]}")

        # 매출원장 페이지
        print(f"\n매출원장 페이지로 이동...")
        await page.goto("https://www.pharmbox.co.kr/mypharm/sales_ledger.jsp",
                        wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)
        print(f"URL: {page.url}")

        # 페이지 분석
        print("\n--- 검색 요소 ---")
        inputs = await page.query_selector_all("input:visible")
        for i, inp in enumerate(inputs):
            inp_id = await inp.get_attribute("id") or ""
            inp_name = await inp.get_attribute("name") or ""
            inp_type = await inp.get_attribute("type") or ""
            inp_ph = await inp.get_attribute("placeholder") or ""
            print(f"  input[{i}] id={inp_id} name={inp_name} type={inp_type} ph={inp_ph}")

        selects = await page.query_selector_all("select:visible")
        for i, sel in enumerate(selects):
            sel_id = await sel.get_attribute("id") or ""
            sel_name = await sel.get_attribute("name") or ""
            options = await sel.query_selector_all("option")
            opt_texts = []
            for opt in options[:8]:
                opt_texts.append((await opt.inner_text()).strip())
            print(f"  select[{i}] id={sel_id} name={sel_name} options={opt_texts}")

        buttons = await page.query_selector_all("button:visible")
        for i, btn in enumerate(buttons):
            text = (await btn.inner_text()).strip()[:40]
            btn_id = await btn.get_attribute("id") or ""
            btn_class = await btn.get_attribute("class") or ""
            if text:
                print(f"  button[{i}] text={text} id={btn_id} class={btn_class[:40]}")

        print("\n--- 테이블 ---")
        tables = await page.query_selector_all("table")
        for ti, table in enumerate(tables):
            headers = await table.query_selector_all("th")
            h_texts = []
            for h in headers:
                h_texts.append((await h.inner_text()).strip())
            rows = await table.query_selector_all("tbody tr")
            if h_texts:
                print(f"  table[{ti}] headers={h_texts} rows={len(rows)}")

        # 다른 페이지도 탐색
        print("\n--- 추가 메뉴 탐색 ---")
        links = await page.query_selector_all("a")
        for el in links:
            try:
                href = await el.get_attribute("href") or ""
                text = (await el.inner_text()).strip()[:40]
                if text and ("주문" in text or "이력" in text or "내역" in text or
                            "반품" in text or "입고" in text or "거래" in text or "매출" in text):
                    print(f"  {text:30s} → {href}")
            except:
                continue

        ss_path = os.path.join(ROOT, "screenshots", "samwon_sales.png")
        await page.screenshot(path=ss_path, full_page=True)
        print(f"\n스크린샷: {ss_path}")

        print("\n30초 대기...")
        await page.wait_for_timeout(30000)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
