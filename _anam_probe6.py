"""native click 후 iframe 갱신 기다림 (navigation 무관). 충분한 시간."""

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
        try:
            await page.frame_locator("#ifrm_bag").locator(
                "#btn_cancel_order").click(timeout=5000)
            await page.wait_for_timeout(2500)
        except Exception:
            pass

        # 검색
        await page.fill("#tx_physic", "타이레놀")
        await page.press("#tx_physic", "Enter")
        await page.wait_for_timeout(3000)

        # 초기 iframe 본문
        def get_bag_text():
            return page.evaluate("""
                () => {
                    const fr = document.querySelector('#ifrm_bag');
                    if (!fr || !fr.contentDocument) return 'NO';
                    return fr.contentDocument.body.innerText.substring(0, 500);
                }""")

        def get_bag_count():
            return page.frame_locator(
                "#ifrm_bag").locator("tr[id^='bagLine']").count()

        c0 = await get_bag_count()
        print(f"담기 전 count: {c0}")
        print(f"담기 전 bag text:\n{await get_bag_text()}")

        # 수량 입력
        await page.fill("tr.ln_physic input[id^='qty']", "1")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(500)

        # 담기 — 네이티브 click. navigation 은 기대하지 않고 단순 click.
        print("\n=== native click ===")
        url_before = page.url
        try:
            await page.click("input[type=image][src*='saveBag']",
                             timeout=5000, no_wait_after=True)
            print("click OK")
        except Exception as e:
            print(f"click err: {e}")

        # 15초 동안 0.5초마다 모니터링
        for i in range(30):
            await page.wait_for_timeout(500)
            try:
                c = await get_bag_count()
            except Exception:
                c = -1
            if c > c0:
                print(f"  +{(i+1)*0.5}s ✅ bag count={c}")
                break
            if i % 4 == 0:
                print(f"  +{(i+1)*0.5}s count={c} url_changed={page.url != url_before}")
        else:
            c = await get_bag_count()
            print(f"\n최종 count={c}")

        print(f"\n최종 url: {page.url}")
        print(f"최종 bag text:\n{await get_bag_text()}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
