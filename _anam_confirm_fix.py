"""_confirm_order 수정 검증: iframe 내 chk 모두 uncheck → frmBag.action 으로
fetch POST → 서버 응답 + iframe reload 후 상태 확인."""

import asyncio
import json
import os
import sys
from datetime import datetime

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

        # 요청 로그 (OrderEnd.asp POST 확인용)
        def on_req(req):
            if "OrderEnd" in req.url:
                print(f">>> REQ {req.method} {req.url}")
                try:
                    body = req.post_data or ""
                    print(f"    post[:500]: {body[:500]}")
                except Exception:
                    pass
        page.on("request", on_req)

        def on_resp(resp):
            if "OrderEnd" in resp.url:
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

        # === 전송 전 상태 ===
        before = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                return {
                    summary: fr.contentDocument.body.innerText.substring(0, 300),
                    lines: Array.from(
                        fr.contentDocument.querySelectorAll('tr[id^="bagLine"]')
                    ).map(r => ({
                        id: r.id, cls: r.className,
                        chk: r.querySelector('input[type=checkbox]')?.checked,
                    }))
                };
            }""")
        print("=== 전송 전 ===")
        print(json.dumps(before, ensure_ascii=False, indent=2))

        # === 핵심: chk 모두 uncheck + frmBag fetch POST ===
        print("\n=== chk uncheck + frmBag.action 으로 fetch POST ===")
        result = await page.evaluate("""
            async () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return {ok: false, err: 'NO_IFRAME'};
                const doc = fr.contentDocument;

                // 1. 모든 chk 해제
                const chks = doc.querySelectorAll(
                    'input[type=checkbox][name^="chk_"]');
                let unchecked_count = 0;
                for (const c of chks) {
                    if (c.checked) {
                        c.checked = false;
                        c.dispatchEvent(new Event('change', {bubbles: true}));
                        unchecked_count++;
                    }
                }

                // 2. frmBag 의 FormData (chk unchecked 는 자동 제외됨)
                const f = doc.forms['frmBag'];
                if (!f) return {ok: false, err: 'NO_FRMBAG',
                                unchecked: unchecked_count};
                const fd = new FormData(f);
                const params = new URLSearchParams();
                for (const [k, v] of fd.entries()) {
                    params.append(k, v);
                }

                // 3. fetch POST
                try {
                    const r = await fetch(f.action, {
                        method: 'POST',
                        headers: {'Content-Type':
                            'application/x-www-form-urlencoded'},
                        body: params.toString(),
                        credentials: 'include',
                    });
                    const text = await r.text();
                    return {
                        ok: r.ok, status: r.status, url: r.url,
                        unchecked: unchecked_count,
                        body_preview: text.substring(0, 400),
                        sent_params_preview: params.toString().substring(0, 400),
                    };
                } catch(e) {
                    return {ok: false, err: String(e)};
                }
            }""")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        await page.wait_for_timeout(2000)

        # iframe 강제 reload
        await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (fr && fr.contentWindow) fr.contentWindow.location.reload();
            }""")
        await page.wait_for_timeout(2500)

        # === 전송 후 iframe 상태 ===
        after = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                return {
                    summary: fr.contentDocument.body.innerText.substring(0, 400),
                    lines: Array.from(
                        fr.contentDocument.querySelectorAll('tr[id^="bagLine"]')
                    ).map(r => ({
                        id: r.id, cls: r.className,
                        chk: r.querySelector('input[type=checkbox]')?.checked,
                    }))
                };
            }""")
        print("\n=== 전송 후 (iframe reload 후) ===")
        print(json.dumps(after, ensure_ascii=False, indent=2))

        # === Report.asp 확인 ===
        await page.goto(
            "http://anampharm.co.kr/Service/Report/Report.asp",
            wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2500)

        today = datetime.now().strftime("%Y-%m-%d")
        try:
            await page.fill("#sDate", today)
            await page.fill("#eDate", today)
            await page.click('input[type=image][src*="search"]', timeout=3000)
            await page.wait_for_timeout(3000)
        except Exception:
            pass

        report_body = await page.evaluate("""
            () => document.body.innerText.substring(0, 1500)""")
        print(f"\n=== Report.asp (오늘 조회) ===")
        print(report_body)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
