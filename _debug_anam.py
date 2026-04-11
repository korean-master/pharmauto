"""
아남약품 WOS 장바구니 로직 단계별 디버그 스크립트
실제 로그인 → 검색 → 결과 확인 → 담기 버튼 확인
"""
import asyncio
import sys
sys.path.insert(0, '.')

from playwright.async_api import async_playwright

WID = '아남약품'
URL = 'http://anampharm.co.kr/HomePage/Contents/Intro/Default.asp'
USER_ID = 'pds2110'
PASSWORD = 'qkreotlr1!'

SEARCH_INPUT = 'input#tx_physic'
SEARCH_BTN = '#btn_search2'
CART_BTN = '#btn_saveBag'
ROW_SEL = 'table tbody tr'

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

        print("=== 1. 사이트 접속 ===")
        await page.goto(URL, wait_until='domcontentloaded')
        await page.wait_for_timeout(3000)
        await page.screenshot(path='screenshots/_debug_01_initial.png')
        print("현재 URL:", page.url)

        print("\n=== 2. 로그인 폼 탐색 ===")
        # ID/PW 입력 필드 탐색
        id_field = await page.query_selector('input[type="text"]:not([readonly])')
        pw_field = await page.query_selector('input[type="password"]')
        print("ID field found:", id_field is not None)
        print("PW field found:", pw_field is not None)

        if id_field and pw_field:
            await id_field.fill(USER_ID)
            await pw_field.fill(PASSWORD)
            await page.press('input[type="password"]', 'Enter')
            await page.wait_for_timeout(4000)
            await page.screenshot(path='screenshots/_debug_02_after_login.png')
            print("로그인 후 URL:", page.url)

        print("\n=== 3. 주문 페이지 상태 확인 ===")
        search_in = await page.query_selector(SEARCH_INPUT)
        print(f"검색 입력창 ({SEARCH_INPUT}) 존재:", search_in is not None)
        if search_in:
            print("  visible:", await search_in.is_visible())
            print("  placeholder:", await search_in.get_attribute('placeholder'))

        search_btn = await page.query_selector(SEARCH_BTN)
        print(f"검색 버튼 ({SEARCH_BTN}) 존재:", search_btn is not None)
        if search_btn:
            print("  visible:", await search_btn.is_visible())
            print("  value/text:", await search_btn.inner_text() if await search_btn.inner_text() else await search_btn.get_attribute('value'))

        print("\n=== 4. '정' 키워드로 검색 ===")
        if search_in and await search_in.is_visible():
            await search_in.fill('')
            await page.wait_for_timeout(300)
            await search_in.fill('정')
            if search_btn and await search_btn.is_visible():
                await search_btn.click()
            else:
                await page.press(SEARCH_INPUT, 'Enter')
            await page.wait_for_timeout(4000)
            await page.screenshot(path='screenshots/_debug_04_search_jung.png')

            rows = await page.query_selector_all(ROW_SEL)
            print(f"검색 결과 행 수 (table tbody tr): {len(rows)}")

            for i, row in enumerate(rows[:3]):
                tds = await row.query_selector_all('td')
                texts = [(await td.inner_text()).strip() for td in tds]
                print(f"  행 {i}: {texts}")

        print("\n=== 5. 빈 검색 시도 ===")
        if search_in and await search_in.is_visible():
            await search_in.fill('')
            if search_btn and await search_btn.is_visible():
                await search_btn.click()
            else:
                await page.press(SEARCH_INPUT, 'Enter')
            await page.wait_for_timeout(4000)
            await page.screenshot(path='screenshots/_debug_05_search_empty.png')

            rows = await page.query_selector_all(ROW_SEL)
            print(f"빈 검색 결과 행 수: {len(rows)}")

        print("\n=== 6. 담기 버튼 상태 확인 ===")
        cart_btn_el = await page.query_selector(CART_BTN)
        print(f"담기 버튼 ({CART_BTN}) 존재:", cart_btn_el is not None)
        if cart_btn_el:
            print("  visible:", await cart_btn_el.is_visible())

        # 행 안에 있는 담기 관련 요소 전체 탐색
        print("\n=== 7. 페이지 내 담기/추가 관련 요소 전체 탐색 ===")
        for sel in ['#btn_saveBag', 'a:has-text("담기")', 'button:has-text("담기")',
                    'input[type="button"][value*="담기"]', 'img[alt*="담기"]',
                    'a:has-text("추가")', 'input[type="button"][value*="추가"]']:
            els = await page.query_selector_all(sel)
            if els:
                print(f"  [{sel}] → {len(els)}개 발견")
                for el in els[:2]:
                    try:
                        print(f"    visible={await el.is_visible()}, text={await el.inner_text()}")
                    except:
                        pass

        print("\n=== 완료 → 5초 후 닫힘 ===")
        await page.wait_for_timeout(5000)
        await browser.close()

asyncio.run(run())
