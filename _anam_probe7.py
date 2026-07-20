"""non-headless 로 띄워서 실제 동작 확인 + form 전체 input 덤프."""

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
        # non-headless — 실제 브라우저 UI 뜸
        browser = await p.chromium.launch(headless=False, slow_mo=300)
        page = await browser.new_page()
        page.on("dialog", lambda d: d.accept())

        # 네트워크 요청 로그 수집 — BagOrder.asp 로 어떤 요청이 가는지
        def on_req(req):
            if "BagOrder" in req.url or "saveNum" in req.url:
                print(f"\n>>> REQ {req.method} {req.url}")
                if req.method == "POST":
                    try:
                        print(f"    post_data: {(req.post_data or '')[:500]}")
                    except Exception:
                        pass
        page.on("request", on_req)

        def on_resp(resp):
            if "BagOrder" in resp.url or "saveNum" in resp.url:
                print(f"<<< RESP {resp.status} {resp.url}")
        page.on("response", on_resp)

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

        # frmOrder 의 모든 input 덤프
        print("\n=== frmOrder 전체 elements 덤프 ===")
        elems = await page.evaluate("""
            () => {
                const f = document.forms['frmOrder'];
                if (!f) return 'NO';
                return Array.from(f.elements).map(e => ({
                    tag: e.tagName, type: e.type, name: e.name, id: e.id,
                    value: (e.value || '').substring(0, 50)
                })).slice(0, 40);
            }""")
        for el in elems:
            print(f"  {el}")

        # 수량 입력
        print("\n=== 수량 입력 + Tab ===")
        await page.fill("tr.ln_physic input[id^='qty']", "1")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(1000)

        # 담기 click — 사용자가 화면에서 보는 것 그대로
        print("\n=== 담기 버튼 click (non-headless, 화면에 떠 있음) ===")
        await page.click("input[type=image][src*='saveBag']")
        await page.wait_for_timeout(15000)  # 충분히 기다림

        count = await page.frame_locator(
            "#ifrm_bag").locator("tr[id^='bagLine']").count()
        print(f"\n최종 count: {count}")
        print(f"최종 url: {page.url}")

        # 5초 더 대기 (사용자가 화면 볼 시간)
        await page.wait_for_timeout(5000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
