"""bagLine 체크박스 해제 시도 → 주문품목 카운트 변화로 주문 성공 여부 확정."""

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

        # 체크 해제 전 상태
        before = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                return fr.contentDocument.body.innerText.substring(0, 400);
            }""")
        print("=== 체크 해제 전 ===")
        print(before)

        # 모든 chk_N 해제 시도
        uncheck_result = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                const chks = fr.contentDocument.querySelectorAll(
                    'input[type=checkbox][name^="chk_"]');
                const log = [];
                for (const c of chks) {
                    const before = c.checked;
                    c.checked = false;
                    // change 이벤트 트리거 — 아남 JS 가 반응하는지
                    c.dispatchEvent(new Event('change', {bubbles: true}));
                    c.dispatchEvent(new Event('click', {bubbles: true}));
                    log.push({
                        name: c.name, before_checked: before,
                        after_checked: c.checked
                    });
                }
                return log;
            }""")
        print("\n=== 체크 해제 시도 결과 ===")
        print(json.dumps(uncheck_result, ensure_ascii=False, indent=2))

        await page.wait_for_timeout(2500)

        # 해제 후 상태
        after = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                return fr.contentDocument.body.innerText.substring(0, 400);
            }""")
        print("\n=== 체크 해제 후 ===")
        print(after)

        # 해제 후 각 bagLine 의 class/checked 재확인
        lines_after = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                const rows = fr.contentDocument.querySelectorAll(
                    'tr[id^="bagLine"]');
                return Array.from(rows).map(r => {
                    const chk = r.querySelector('input[type=checkbox]');
                    return {
                        id: r.id, className: r.className,
                        chk_checked: chk ? chk.checked : null,
                        text: (r.innerText || '').replace(/\\s+/g, ' ').substring(0, 80)
                    };
                });
            }""")
        print("\n=== bagLine 상태 ===")
        print(json.dumps(lines_after, ensure_ascii=False, indent=2))

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
