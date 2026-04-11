"""삼원약품 사이트 메뉴 구조 탐색."""

import asyncio
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from playwright.async_api import async_playwright


HISTORY_KEYWORDS = [
    "주문", "이력", "거래", "입고", "매입", "구매", "내역",
    "반품", "출고", "납품", "order", "history", "purchase",
    "transaction", "return",
]


async def main():
    from core.crypto import load_wholesalers_secure
    ws = load_wholesalers_secure()
    samwon = ws.get("삼원약품", {})

    if not samwon.get("id"):
        print("삼원약품 계정 없음")
        return

    print("=" * 60)
    print("  삼원약품 사이트 메뉴 탐색")
    print("=" * 60)

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    page = await browser.new_page()
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

    try:
        # 로그인
        url = samwon.get("url", "https://www.pharmbox.co.kr/")
        print(f"\n[1] 로그인: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        # 로그인 폼 탐색
        print("\n--- 로그인 폼 탐색 ---")
        inputs = await page.query_selector_all("input:visible")
        for i, inp in enumerate(inputs):
            inp_id = await inp.get_attribute("id") or ""
            inp_name = await inp.get_attribute("name") or ""
            inp_type = await inp.get_attribute("type") or ""
            inp_ph = await inp.get_attribute("placeholder") or ""
            print(f"  input[{i}] id={inp_id} name={inp_name} type={inp_type} ph={inp_ph}")

        buttons = await page.query_selector_all("button:visible, input[type='submit']:visible, a.login:visible, a.btn:visible")
        for i, btn in enumerate(buttons):
            tag = await btn.evaluate("el => el.tagName")
            text = (await btn.inner_text()).strip()[:40] if tag != "INPUT" else await btn.get_attribute("value") or ""
            btn_id = await btn.get_attribute("id") or ""
            btn_class = await btn.get_attribute("class") or ""
            print(f"  {tag}[{i}] text={text} id={btn_id} class={btn_class[:40]}")

        # 로그인 시도
        print("\n[2] 로그인 시도...")
        # 일반적인 패턴 시도
        id_selectors = [
            'input[name="userId"]', 'input[name="id"]', 'input[name="loginId"]',
            'input[name="user_id"]', 'input[name="mb_id"]',
            'input[type="text"]:visible',
        ]
        pw_selectors = [
            'input[name="userPw"]', 'input[name="pw"]', 'input[name="password"]',
            'input[name="loginPw"]', 'input[name="user_pw"]', 'input[name="mb_password"]',
            'input[type="password"]:visible',
        ]
        btn_selectors = [
            'button:has-text("로그인")', 'input[type="submit"]',
            'a:has-text("로그인")', 'button.login', '.btn_login',
        ]

        id_filled = False
        for sel in id_selectors:
            el = await page.query_selector(sel)
            if el:
                await el.fill(samwon["id"])
                print(f"  ID 입력: {sel}")
                id_filled = True
                break

        pw_filled = False
        for sel in pw_selectors:
            el = await page.query_selector(sel)
            if el:
                await el.fill(samwon["pw"])
                print(f"  PW 입력: {sel}")
                pw_filled = True
                break

        if id_filled and pw_filled:
            for sel in btn_selectors:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    print(f"  로그인 클릭: {sel}")
                    break
            await page.wait_for_timeout(4000)
            print(f"  로그인 후 URL: {page.url}")
        else:
            print("  로그인 폼을 찾지 못함")

        # 메인 페이지 링크 스캔
        print(f"\n[3] 메인 페이지 링크 스캔...")
        elements = await page.query_selector_all("a")
        seen = set()
        history_items = []
        all_items = []

        for el in elements:
            try:
                href = await el.get_attribute("href") or ""
                text = (await el.inner_text()).strip().replace("\n", " ")[:60]
                if not text or text in seen:
                    continue
                seen.add(text)
                all_items.append({"text": text, "href": href})

                text_lower = (text + href).lower()
                score = sum(1 for kw in HISTORY_KEYWORDS if kw in text_lower)
                if score > 0:
                    history_items.append({"text": text, "href": href, "score": score})
            except Exception:
                continue

        print(f"  총 {len(all_items)}개 링크")

        if history_items:
            history_items.sort(key=lambda x: x["score"], reverse=True)
            print(f"\n  === 이력 관련 {len(history_items)}건 ===")
            for item in history_items:
                print(f"  {item['text']:40s} → {item['href']}")

        print(f"\n  === 전체 링크 ===")
        for item in all_items:
            print(f"  {item['text']:40s} → {item['href']}")

        # 이력 관련 페이지 방문
        for item in history_items[:3]:
            href = item["href"]
            if not href or href == "#" or href.startswith("javascript:"):
                continue
            from urllib.parse import urljoin
            target = urljoin(page.url, href) if not href.startswith("http") else href

            print(f"\n[4] 방문: {item['text']} → {target}")
            try:
                await page.goto(target, wait_until="domcontentloaded", timeout=10000)
                await page.wait_for_timeout(2000)
                print(f"  → URL: {page.url}")

                # 테이블 분석
                tables = await page.query_selector_all("table")
                print(f"  → 테이블: {len(tables)}개")
                for ti, table in enumerate(tables):
                    headers = await table.query_selector_all("th")
                    h_texts = []
                    for h in headers:
                        h_texts.append((await h.inner_text()).strip())
                    if h_texts:
                        print(f"  → table[{ti}] 헤더: {h_texts}")

                # 검색 필드
                search_inputs = await page.query_selector_all("input:visible")
                for inp in search_inputs:
                    ph = await inp.get_attribute("placeholder") or ""
                    name = await inp.get_attribute("name") or ""
                    if ph or name:
                        print(f"  → input: name={name} ph={ph}")

            except Exception as e:
                print(f"  → 실패: {e}")

        # 스크린샷
        ss_path = os.path.join(ROOT, "screenshots", "samwon_main.png")
        os.makedirs(os.path.dirname(ss_path), exist_ok=True)
        await page.screenshot(path=ss_path, full_page=True)

        print(f"\n30초 동안 브라우저를 열어둡니다...")
        await page.wait_for_timeout(30000)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
