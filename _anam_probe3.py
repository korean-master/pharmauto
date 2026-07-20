"""frmOrder 직접 submit 테스트."""

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

        # 로그인 + 주문 페이지 + 장바구니 비우기
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

        def count_cart():
            return page.frame_locator("iframe#ifrm_bag").locator(
                "tr[id^='bagLine']").count()

        # 1. 비우기
        initial = await count_cart()
        print(f"초기: {initial}")
        if initial > 0:
            try:
                await page.frame_locator("#ifrm_bag").locator(
                    "#btn_cancel_order").click(timeout=5000)
                await page.wait_for_timeout(2500)
                print(f"비운 후: {await count_cart()}")
            except Exception as e:
                print(f"비우기 실패: {e}")

        # jQuery 이벤트 핸들러 확인
        jq_events = await page.evaluate("""
            () => {
                if (typeof jQuery === 'undefined') return 'NO_JQUERY';
                const btn = document.querySelector('#btn_saveBag');
                if (!btn) return 'NO_BTN';
                try {
                    const data = jQuery._data(btn, 'events');
                    if (!data) return 'NO_EVENTS';
                    const result = {};
                    for (const k in data) {
                        result[k] = data[k].length;
                    }
                    return result;
                } catch(e) { return String(e); }
            }""")
        print("\njQuery btn_saveBag events:", jq_events)

        # 2. 검색 + 담기 전략 A: frmOrder.submit() 직접
        await page.fill("#tx_physic", "타이레놀")
        await page.press("#tx_physic", "Enter")
        await page.wait_for_timeout(3000)

        print("\n=== 전략 A: document.frmOrder.submit() 직접 호출 ===")
        before = await count_cart()
        print(f"before: {before}")
        await page.fill("tr.ln_physic input[id^='qty']", "1")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(500)

        submit_result = await page.evaluate("""
            () => {
                try {
                    if (!document.frmOrder) return 'NO_FRMORDER';
                    document.frmOrder.submit();
                    return 'SUBMITTED';
                } catch(e) { return String(e); }
            }""")
        print(f"submit 결과: {submit_result}")
        await page.wait_for_timeout(1500)

        for i in range(14):
            await page.wait_for_timeout(500)
            c = await count_cart()
            if c > before:
                print(f"  +{(i+1)*0.5}s after={c} ✅ 성공")
                break
        else:
            c = await count_cart()
            print(f"  최종 after={c}")

        print("page_url 담기 후:", page.url)

        # iframe 본문으로 확인
        bag_text = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return '';
                return fr.contentDocument.body.innerText.substring(0, 600);
            }""")
        print("\nifrm_bag 본문:")
        print(bag_text)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
