"""아남 주문서검색 페이지에서 오늘 주문 확인. 매출원장 보다 빨리 반영됨."""

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

        # 로그인
        await page.goto(
            "http://anampharm.co.kr/HomePage/Contents/Intro/Default.asp",
            wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        await page.fill("#tbID", config["id"])
        await page.fill("#tbPW", config["pw"])
        await page.press("#tbPW", "Enter")
        await page.wait_for_timeout(3500)

        # 메인 페이지에서 "주문서검색" 링크/경로 찾기
        print("=== 1. 주문서검색 링크 탐색 ===")
        links = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a')).map(a => ({
                text: (a.innerText || '').trim(),
                href: a.href
            })).filter(l => l.text.includes('주문서')
                         || l.text.includes('주문검색')
                         || l.href.includes('OrderList')
                         || l.href.includes('OrderSearch'))""")
        print(json.dumps(links, ensure_ascii=False, indent=2))

        # 직접 예상 URL 시도 (흔한 네이밍)
        candidates = [
            "http://anampharm.co.kr/Service/Order/OrderList.asp",
            "http://anampharm.co.kr/Service/Order/OrderSearch.asp",
            "http://anampharm.co.kr/Service/OrderList/OrderList.asp",
            "http://anampharm.co.kr/Service/Order/Order_List.asp",
        ]
        if links:
            # 링크로 찾은 것 우선
            for lk in links:
                if lk['href']:
                    candidates.insert(0, lk['href'])

        for url in candidates:
            print(f"\n=== 2. 시도: {url} ===")
            try:
                await page.goto(url, wait_until="domcontentloaded",
                                timeout=10000)
                await page.wait_for_timeout(2500)
                title = await page.title()
                body_preview = await page.evaluate(
                    "() => document.body.innerText.substring(0, 600)")
                print(f"title: {title}")
                print(f"body_preview:\n{body_preview}")
                if "404" in body_preview or "찾을 수 없" in body_preview:
                    continue
                # 오늘 날짜 포함 행 검색
                today_rows = await page.evaluate("""
                    () => {
                        const today = new Date();
                        const y = today.getFullYear();
                        const m = String(today.getMonth()+1).padStart(2,'0');
                        const d = String(today.getDate()).padStart(2,'0');
                        const formats = [
                            `${y}-${m}-${d}`,
                            `${y}${m}${d}`,
                            `${y}.${m}.${d}`,
                            `${y}/${m}/${d}`,
                        ];
                        const rows = document.querySelectorAll('tr');
                        const matches = [];
                        for (const r of rows) {
                            const txt = r.innerText || '';
                            for (const f of formats) {
                                if (txt.includes(f)) {
                                    matches.push(txt.substring(0, 250).replace(/\\s+/g,' '));
                                    break;
                                }
                            }
                        }
                        return matches.slice(0, 10);
                    }""")
                if today_rows:
                    print(f"\n>>> 오늘 행 {len(today_rows)} 발견:")
                    for r in today_rows:
                        print(f"  {r}")
                    break
            except Exception as e:
                print(f"err: {e}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
