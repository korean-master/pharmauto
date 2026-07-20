"""submit 후 navigation 기다리고 새 페이지의 iframe 로드까지 기다린 후
bag count 측정."""

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

        # 비우기 + 검색
        try:
            await page.frame_locator("#ifrm_bag").locator(
                "#btn_cancel_order").click(timeout=5000)
            await page.wait_for_timeout(2500)
        except Exception:
            pass

        # 비운 후 상태
        c0 = await page.frame_locator(
            "#ifrm_bag").locator("tr[id^='bagLine']").count()
        print(f"비운 후 bag count: {c0}")

        await page.fill("#tx_physic", "타이레놀")
        await page.press("#tx_physic", "Enter")
        await page.wait_for_timeout(3000)

        # 수량 입력 + 담기 (native click)
        await page.fill("tr.ln_physic input[id^='qty']", "1")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(500)

        print("\n=== 담기 click + navigation 기다림 ===")
        # click 과 동시에 navigation 대기
        async with page.expect_navigation(
                wait_until="domcontentloaded", timeout=10000):
            await page.click("input[type=image][src*='saveBag']")
        await page.wait_for_timeout(2500)  # iframe 로드 대기

        print(f"navigation 후 url: {page.url}")
        c1 = await page.frame_locator(
            "#ifrm_bag").locator("tr[id^='bagLine']").count()
        print(f"bag count: {c1}")

        # 혹시 더 기다려야 하나 폴링
        for i in range(10):
            await page.wait_for_timeout(500)
            c = await page.frame_locator(
                "#ifrm_bag").locator("tr[id^='bagLine']").count()
            if c != c1:
                print(f"  +{(i+1)*0.5}s count 변화: {c}")
                c1 = c

        print(f"\n최종 bag count: {c1}")
        if c1 > c0:
            print("✅ 담기 성공")
        else:
            print("❌ 여전히 실패")

        bag_text = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return '';
                return fr.contentDocument.body.innerText.substring(0, 500);
            }""")
        print(f"\nifrm_bag 본문:\n{bag_text}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
