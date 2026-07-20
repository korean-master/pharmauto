"""실제 담기 시뮬레이션 — 장바구니 비우기 전/후, 담기 전/후 비교."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.crypto import decrypt_dict_fields
from core.paths import wholesalers_path


async def main():
    with open(wholesalers_path(), "r", encoding="utf-8") as f:
        ws = json.load(f)
    anam_raw = ws.get("아남약품") or ws.get("anam")
    config = decrypt_dict_fields(dict(anam_raw), ["id", "pw"])

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.on("dialog", lambda d: d.accept())

        # 로그인 + 주문 페이지
        await page.goto(
            "http://anampharm.co.kr/HomePage/Contents/Intro/Default.asp",
            wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        await page.fill("#tbID", config["id"])
        await page.fill("#tbPW", config["pw"])
        await page.press("#tbPW", "Enter")
        await page.wait_for_timeout(3500)
        await page.goto(
            "http://anampharm.co.kr/Service/Order/Order.asp",
            wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2500)

        # 장바구니 iframe 상태 확인
        def count_cart():
            return page.frame_locator("iframe#ifrm_bag").locator(
                "tr[id^='bagLine']").count()

        print("초기 장바구니:", await count_cart())
        # iframe 내부의 담긴 항목들 코드 덤프
        bag_codes = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO_IFRAME';
                const rows = fr.contentDocument.querySelectorAll(
                    'tr[id^="bagLine"]');
                return Array.from(rows).map(r => r.outerHTML.substring(0, 200));
            }""")
        print("기존 담긴 항목:", bag_codes)

        # 타이레놀 검색
        await page.fill("#tx_physic", "타이레놀")
        await page.press("#tx_physic", "Enter")
        await page.wait_for_timeout(3000)

        # 검색 결과 약품코드 추출
        result_info = await page.evaluate("""
            () => {
                const rows = document.querySelectorAll('tr.ln_physic');
                return Array.from(rows).slice(0, 3).map(r => {
                    const tds = r.querySelectorAll('td');
                    const pc_input = r.querySelector('input[name^="pc_"]');
                    const qty_input = r.querySelector('input[id^="qty"]');
                    return {
                        code_td: tds[0] ? tds[0].innerText.trim() : '',
                        name_td: tds[2] ? tds[2].innerText.trim().substring(0, 40) : '',
                        pc_input_name: pc_input ? pc_input.name : null,
                        pc_input_value: pc_input ? pc_input.value : null,
                        qty_input_id: qty_input ? qty_input.id : null,
                    };
                });
            }""")
        print("\n검색 결과 첫 3개:")
        for r in result_info:
            print(" ", r)

        # 첫 약품의 코드가 기존 장바구니에 있는지
        if result_info:
            first_code = result_info[0].get("pc_input_value")
            exists = await page.evaluate(f"""
                () => typeof fnPhysicExistsBag === 'function'
                    ? fnPhysicExistsBag('{first_code}')
                    : 'FN_NOT_FOUND'""")
            print(f"\n첫 약품 코드({first_code}) 장바구니 중복 체크:", exists)

        # 실제 담기 시뮬레이션
        print("\n=== 담기 시도 (qty_0=1, 담기 버튼 클릭) ===")
        before = await count_cart()
        print("before:", before)

        await page.fill("tr.ln_physic input[id^='qty']", "1")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(500)

        await page.click("input[type=image][src*='saveBag']")
        # iframe 변화 폴링
        for i in range(20):
            await page.wait_for_timeout(500)
            c = await count_cart()
            if c != before:
                print(f"  +{(i+1)*0.5}s after={c}")
                break
        else:
            c = await count_cart()
        print("최종 after:", c, "page_url:", page.url)

        # 담기 후 ifrm_bag 의 HTML 일부 (오류 메시지 등)
        bag_html = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                return fr.contentDocument.body.innerText.substring(0, 500);
            }""")
        print("\nifrm_bag 본문:", bag_html)

        # 장바구니 비우기 시도
        print("\n=== 장바구니 비우기 #btn_cancel_order 시도 ===")
        try:
            # iframe 안인지 메인인지 확인
            main_btn = await page.evaluate("""
                () => !!document.querySelector('#btn_cancel_order')""")
            iframe_btn = await page.evaluate("""
                () => {
                    const fr = document.querySelector('#ifrm_bag');
                    if (!fr || !fr.contentDocument) return false;
                    return !!fr.contentDocument.querySelector(
                        '#btn_cancel_order');
                }""")
            print("#btn_cancel_order main=", main_btn, "iframe=", iframe_btn)
            if main_btn:
                await page.click("#btn_cancel_order")
                await page.wait_for_timeout(2000)
                print("비우기 후:", await count_cart())
            elif iframe_btn:
                await page.frame_locator("#ifrm_bag").locator(
                    "#btn_cancel_order").click()
                await page.wait_for_timeout(2000)
                print("비우기 후:", await count_cart())
        except Exception as e:
            print("비우기 에러:", e)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
