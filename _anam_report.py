"""아남 Report.asp 에서 오늘 날짜로 조회."""

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

    today = datetime.now().strftime("%Y-%m-%d")

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
            "http://anampharm.co.kr/Service/Report/Report.asp",
            wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2500)

        # 날짜 입력 필드 찾기
        inputs = await page.evaluate("""
            () => Array.from(
                document.querySelectorAll('input[type=text]')).map(i => ({
                    name: i.name, id: i.id,
                    value: i.value, placeholder: i.placeholder
                }))""")
        print("=== Report.asp 의 input[type=text] ===")
        print(json.dumps(inputs, ensure_ascii=False, indent=2))

        # 흔한 네이밍으로 오늘 날짜 채워보기
        date_candidates = [
            ("#sDate", "#eDate"),
            ("#dtpFrom", "#dtpTo"),
            ("#fromDate", "#toDate"),
            ("input[name='sDate']", "input[name='eDate']"),
        ]
        filled = False
        for from_sel, to_sel in date_candidates:
            try:
                await page.fill(from_sel, today)
                await page.fill(to_sel, today)
                filled = True
                print(f"\n날짜 채움: {from_sel}={today}, {to_sel}={today}")
                break
            except Exception:
                continue
        if not filled:
            print("날짜 input 못 찾음 — 기본값으로 검색 시도")

        # 검색 버튼 찾기 (일반적으로 조회/검색 등)
        btn_clicked = False
        for sel in ['button:has-text("조회")',
                    'button:has-text("검색")',
                    'input[type=button][value*="조회"]',
                    'input[type=submit]',
                    'input[type=image][src*="search"]']:
            try:
                await page.click(sel, timeout=3000)
                btn_clicked = True
                print(f"검색 버튼 클릭: {sel}")
                break
            except Exception:
                continue
        if not btn_clicked:
            # 엔터 키
            try:
                await page.press("body", "Enter")
            except Exception:
                pass

        await page.wait_for_timeout(3000)

        # 결과 확인
        body = await page.evaluate(
            "() => document.body.innerText.substring(0, 2500)")
        print("\n=== 검색 후 본문 ===")
        print(body)

        # 오늘 건 테이블 행
        today_rows = await page.evaluate(f"""
            () => {{
                const rows = document.querySelectorAll('table tr');
                const matches = [];
                for (const r of rows) {{
                    const txt = (r.innerText || '').replace(/\\s+/g, ' ');
                    if (txt.includes('{today}') ||
                        txt.includes('{today.replace("-","")}') ||
                        txt.includes('{today[5:].replace("-","")}')) {{
                        matches.push(txt.substring(0, 250));
                    }}
                }}
                return matches;
            }}""")
        print(f"\n=== 오늘 관련 행 {len(today_rows)}개 ===")
        for r in today_rows:
            print(f"  {r}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
