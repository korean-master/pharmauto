"""아남 주문 내역 페이지에서 오늘 주문 확인."""

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

        # 주문 내역 페이지 (SalesList.asp) — 과거 판매/주문 이력
        await page.goto(
            "http://anampharm.co.kr/Service/SalesList/SalesList.asp",
            wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        # 오늘 날짜로 조회 (기본값일 가능성 — 일단 페이지 본문 덤프)
        body_text = await page.evaluate("""
            () => document.body.innerText.substring(0, 3000)
        """)
        print("=== SalesList 본문 ===")
        print(body_text)
        print()

        # 오늘 날짜의 행 수
        today_count = await page.evaluate("""
            () => {
                const rows = document.querySelectorAll('table tr');
                const today = new Date().toISOString().slice(0, 10);
                const todayKr = today.replace(/-/g, '').substring(4);
                let count = 0;
                const samples = [];
                for (const r of rows) {
                    const txt = r.innerText || '';
                    if (txt.includes(today) || txt.includes(todayKr)) {
                        count++;
                        samples.push(txt.substring(0, 200));
                    }
                }
                return { count, samples: samples.slice(0, 5) };
            }
        """)
        print(f"오늘 관련 행: {today_count}")

        # 현재 장바구니 (주문 대기) 상태도 확인
        await page.goto(
            "http://anampharm.co.kr/Service/Order/Order.asp",
            wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2500)

        bag_state = await page.evaluate("""
            () => {
                const fr = document.querySelector('#ifrm_bag');
                if (!fr || !fr.contentDocument) return 'NO';
                return fr.contentDocument.body.innerText.substring(0, 500);
            }""")
        print("\n=== 현재 장바구니 상태 ===")
        print(bag_state)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
