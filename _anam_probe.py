"""아남 주문 페이지 구조 직접 분석. 담기 버튼/수량 input 의 form 관계
+ onclick JS 함수 이름 확인."""

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
    if not anam_raw:
        print("NO_ANAM_ENTRY")
        return
    config = decrypt_dict_fields(dict(anam_raw), ["id", "pw"])
    print("id_len:", len(config.get("id", "")),
          "pw_len:", len(config.get("pw", "")))

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.on("dialog", lambda d: d.accept())

        # 로그인
        print("\n=== 1. 로그인 페이지 ===")
        await page.goto(
            "http://anampharm.co.kr/HomePage/Contents/Intro/Default.asp",
            wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        await page.fill("#tbID", config["id"])
        await page.fill("#tbPW", config["pw"])
        await page.press("#tbPW", "Enter")
        await page.wait_for_timeout(3500)
        print("after_login_url:", page.url)

        # 주문 페이지
        print("\n=== 2. 주문 페이지 이동 ===")
        await page.goto(
            "http://anampharm.co.kr/Service/Order/Order.asp",
            wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2500)

        # 검색
        print("\n=== 3. 타이레놀 검색 ===")
        await page.fill("#tx_physic", "타이레놀")
        await page.press("#tx_physic", "Enter")
        await page.wait_for_timeout(3000)

        # 담기 버튼 구조
        print("\n=== 4. 담기 버튼 ===")
        btn = await page.evaluate("""
            () => {
                const b = document.querySelector(
                    'input[type=image][src*="saveBag"]');
                if (!b) return 'NO_BTN';
                const f = b.form;
                return {
                    outerHTML: b.outerHTML.substring(0, 300),
                    onclick: b.getAttribute('onclick'),
                    onclick_prop: b.onclick ? b.onclick.toString().substring(0, 200) : null,
                    name: b.name,
                    form_id: f ? f.id : null,
                    form_name: f ? f.name : null,
                    form_action: f ? f.action : null,
                    form_method: f ? f.method : null,
                    form_onsubmit: f ? f.getAttribute('onsubmit') : null,
                };
            }""")
        print(json.dumps(btn, ensure_ascii=False, indent=2))

        # 수량 input 구조
        print("\n=== 5. 수량 input ===")
        qty = await page.evaluate("""
            () => {
                const q = document.querySelector(
                    'tr.ln_physic input[id^="qty"]');
                if (!q) return 'NO_QTY';
                const f = q.form;
                return {
                    outerHTML: q.outerHTML.substring(0, 300),
                    name: q.name,
                    id: q.id,
                    onchange: q.getAttribute('onchange'),
                    oninput: q.getAttribute('oninput'),
                    onblur: q.getAttribute('onblur'),
                    onkeyup: q.getAttribute('onkeyup'),
                    form_id: f ? f.id : null,
                    form_name: f ? f.name : null,
                };
            }""")
        print(json.dumps(qty, ensure_ascii=False, indent=2))

        # 페이지 모든 form
        print("\n=== 6. 페이지 모든 form ===")
        forms = await page.evaluate("""
            () => Array.from(document.forms).map(f => ({
                id: f.id, name: f.name, method: f.method,
                action: f.action.substring(0, 80),
                input_count: f.elements.length,
                onsubmit: f.getAttribute('onsubmit')
            }))""")
        print(json.dumps(forms, ensure_ascii=False, indent=2))

        # 관련 JS 함수
        print("\n=== 7. window 의 담기 관련 JS 함수 ===")
        funcs = await page.evaluate("""
            () => {
                const matches = [];
                for (const k in window) {
                    try {
                        if (typeof window[k] === 'function' && k.length < 40) {
                            const low = k.toLowerCase();
                            if (low.includes('save') || low.includes('bag')
                                || low.includes('cart') || low.includes('send')
                                || low.includes('order') || low.includes('add')) {
                                matches.push({
                                    name: k,
                                    src: window[k].toString().substring(0, 300)
                                });
                            }
                        }
                    } catch(e) {}
                }
                return matches;
            }""")
        for fn in funcs:
            print(f"\n--- {fn['name']} ---")
            print(fn['src'])

        # 담기 버튼 주변 HTML (앞뒤 500자)
        print("\n=== 8. 담기 버튼 주변 HTML ===")
        around = await page.evaluate("""
            () => {
                const b = document.querySelector(
                    'input[type=image][src*="saveBag"]');
                if (!b) return 'NO_BTN';
                let el = b;
                for (let i = 0; i < 3 && el.parentElement; i++) {
                    el = el.parentElement;
                }
                return el.outerHTML.substring(0, 1500);
            }""")
        print(around)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
