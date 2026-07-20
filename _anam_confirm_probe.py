"""아남 장바구니 bagLine 상태 + 주문전송 form 구조 분석.
실제 주문 전송은 하지 않음 (submit 호출 X)."""

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

        # === 1. iframe 내부 전체 상태 덤프 ===
        print("=== 1. ifrm_bag 내부 상태 ===")
        bag_info = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                const doc = fr.contentDocument;
                const lines = doc.querySelectorAll('tr[id^="bagLine"]');
                const result = {
                    line_count: lines.length,
                    lines: [],
                    summary: doc.body.innerText.substring(0, 300),
                };
                for (const r of lines) {
                    const chk = r.querySelector('input[type=checkbox]');
                    const pc = r.querySelector('input[name^="pc_"]');
                    const qty = r.querySelector('input[name^="qty_"]');
                    result.lines.push({
                        id: r.id,
                        className: r.className,
                        chk_name: chk ? chk.name : null,
                        chk_checked: chk ? chk.checked : null,
                        pc_value: pc ? pc.value : null,
                        qty_value: qty ? qty.value : null,
                        row_text: r.innerText.replace(/\\s+/g, ' ').substring(0, 150),
                    });
                }
                return result;
            }""")
        print(json.dumps(bag_info, ensure_ascii=False, indent=2))

        # === 2. iframe 내 form 구조 (주문전송 form) ===
        print("\n=== 2. ifrm_bag 안의 form 들 ===")
        forms_info = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                return Array.from(fr.contentDocument.forms).map(f => ({
                    id: f.id, name: f.name, method: f.method,
                    action: f.action.substring(0, 100),
                    target: f.target,
                    input_count: f.elements.length,
                }));
            }""")
        print(json.dumps(forms_info, ensure_ascii=False, indent=2))

        # === 3. 주문전송 버튼 정보 ===
        print("\n=== 3. 주문전송 버튼 (btn_order) ===")
        btn_info = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                const btn = fr.contentDocument.querySelector(
                    'input[type=image][src*="btn_order"]');
                if (!btn) {
                    const all = fr.contentDocument.querySelectorAll(
                        'input[type=image]');
                    return {found: false,
                            all_images: Array.from(all).map(
                                b => ({id: b.id, src: b.src, alt: b.alt}))};
                }
                const f = btn.form;
                return {
                    outerHTML: btn.outerHTML.substring(0, 300),
                    onclick: btn.getAttribute('onclick'),
                    form_id: f ? f.id : null,
                    form_name: f ? f.name : null,
                    form_action: f ? f.action : null,
                    form_method: f ? f.method : null,
                    form_onsubmit: f ? f.getAttribute('onsubmit') : null,
                };
            }""")
        print(json.dumps(btn_info, ensure_ascii=False, indent=2))

        # === 4. 주문전송 form 의 elements 덤프 ===
        print("\n=== 4. 주문전송 form elements ===")
        order_form_dump = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                const btn = fr.contentDocument.querySelector(
                    'input[type=image][src*="btn_order"]');
                if (!btn || !btn.form) return 'NO_FORM';
                const f = btn.form;
                return Array.from(f.elements).map(e => ({
                    tag: e.tagName, type: e.type, name: e.name, id: e.id,
                    value: (e.value || '').substring(0, 60),
                    checked: e.checked,
                })).slice(0, 50);
            }""")
        if isinstance(order_form_dump, list):
            for el in order_form_dump:
                print(f"  {el}")
        else:
            print(order_form_dump)

        # === 5. 관련 JS 함수 탐색 (iframe window level) ===
        print("\n=== 5. iframe window 의 주문 관련 함수 ===")
        iframe_funcs = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentWindow) return 'NO';
                const w = fr.contentWindow;
                const matches = [];
                for (const k in w) {
                    try {
                        if (typeof w[k] === 'function' && k.length < 40) {
                            const low = k.toLowerCase();
                            if (low.includes('order') || low.includes('send')
                                || low.includes('submit')
                                || low.includes('cancel')) {
                                matches.push({
                                    name: k,
                                    src: w[k].toString().substring(0, 300)
                                });
                            }
                        }
                    } catch(e) {}
                }
                return matches;
            }""")
        for fn in iframe_funcs[:10]:
            print(f"\n--- {fn['name']} ---")
            print(fn['src'])

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
