"""form 상태 + action 강제 override + iframe submit 테스트."""

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

        # 비우기
        await page.frame_locator("#ifrm_bag").locator(
            "#btn_cancel_order").click(timeout=5000)
        await page.wait_for_timeout(2000)

        # 검색
        await page.fill("#tx_physic", "타이레놀")
        await page.press("#tx_physic", "Enter")
        await page.wait_for_timeout(3000)

        # 수량 입력 직전 form 상태
        print("=== 수량 입력 전 form 상태 ===")
        s1 = await page.evaluate("""
            () => {
                const f = document.frmOrder;
                return {
                    method: f.method, action: f.action, target: f.target,
                    input_count: f.elements.length,
                    qty_val: (f.elements['qty_0'] || {}).value,
                    pc_val: (f.elements['pc_0'] || {}).value,
                };
            }""")
        print(json.dumps(s1, ensure_ascii=False, indent=2))

        await page.fill("tr.ln_physic input[id^='qty']", "1")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(500)

        print("\n=== 수량 입력 후 / 클릭 직전 ===")
        s2 = await page.evaluate("""
            () => {
                const f = document.frmOrder;
                return {
                    method: f.method, action: f.action, target: f.target,
                    qty_val: (f.elements['qty_0'] || {}).value,
                };
            }""")
        print(json.dumps(s2, ensure_ascii=False, indent=2))

        # 전략 B: iframe 을 target 으로 강제 지정하고 submit
        print("\n=== 전략 B: action/method/target 강제 + submit ===")
        result = await page.evaluate("""
            () => {
                const f = document.frmOrder;
                f.action = 'http://anampharm.co.kr/Service/Order/BagOrder.asp';
                f.method = 'post';
                f.target = 'ifrm_bag';
                try {
                    f.submit();
                    return 'OK';
                } catch(e) { return String(e); }
            }""")
        print(f"강제 submit 결과: {result}")

        for i in range(14):
            await page.wait_for_timeout(500)
            c = await page.frame_locator(
                "iframe#ifrm_bag").locator("tr[id^='bagLine']").count()
            if c > 0:
                print(f"  +{(i+1)*0.5}s after={c} ✅")
                break
        else:
            c = await page.frame_locator(
                "iframe#ifrm_bag").locator("tr[id^='bagLine']").count()
            print(f"  최종 after={c}")
        print(f"page_url: {page.url}")

        bag_text = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return '';
                return fr.contentDocument.body.innerText.substring(0, 400);
            }""")
        print("ifrm_bag 본문:", bag_text)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
