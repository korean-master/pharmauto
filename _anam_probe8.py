"""결정적: FormData + fetch 로 BagOrder.asp POST 직접."""

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

        await page.fill("#tx_physic", "타이레놀")
        await page.press("#tx_physic", "Enter")
        await page.wait_for_timeout(3000)

        # 수량 입력
        await page.fill("tr.ln_physic input[id^='qty']", "1")
        await page.wait_for_timeout(500)

        print("=== fetch 로 BagOrder.asp POST 직접 ===")
        result = await page.evaluate("""
            async () => {
                const f = document.forms['frmOrder'];
                if (!f) return 'NO_FORM';
                const fd = new FormData(f);
                const params = new URLSearchParams();
                for (const [k, v] of fd.entries()) {
                    params.append(k, v);
                }
                const body_str = params.toString();
                try {
                    const resp = await fetch(f.action, {
                        method: 'POST',
                        headers: {'Content-Type':
                            'application/x-www-form-urlencoded'},
                        body: body_str,
                        credentials: 'include',
                    });
                    const text = await resp.text();
                    return {
                        status: resp.status,
                        url: resp.url,
                        text_head: text.substring(0, 500),
                        body_preview: body_str.substring(0, 300)
                    };
                } catch(e) { return 'ERR:' + String(e); }
            }""")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        # 서버 저장 상태 확인 — iframe 새로고침
        await page.wait_for_timeout(1500)
        await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (fr) fr.contentWindow.location.reload();
            }""")
        await page.wait_for_timeout(3000)

        count = await page.frame_locator(
            "#ifrm_bag").locator("tr[id^='bagLine']").count()
        print(f"\niframe reload 후 count: {count}")

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
