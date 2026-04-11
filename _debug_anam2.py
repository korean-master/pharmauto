"""
아남약품 WOS 장바구니담기 버튼 + 수량 입력 셀렉터 정밀 분석
"""
import asyncio
import sys
sys.path.insert(0, '.')

from playwright.async_api import async_playwright

URL = 'http://anampharm.co.kr/HomePage/Contents/Intro/Default.asp'
USER_ID = 'pds2110'
PASSWORD = 'qkreotlr1!'

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

        await page.goto(URL, wait_until='domcontentloaded')
        await page.wait_for_timeout(3000)

        # 로그인
        id_f = await page.query_selector('input[type="text"]:not([readonly])')
        pw_f = await page.query_selector('input[type="password"]')
        await id_f.fill(USER_ID)
        await pw_f.fill(PASSWORD)
        await page.press('input[type="password"]', 'Enter')
        await page.wait_for_timeout(4000)

        # "정" 검색
        await page.fill('input#tx_physic', '정')
        await page.wait_for_timeout(300)
        await page.click('#btn_search2')
        await page.wait_for_timeout(4000)

        rows = await page.query_selector_all('table tbody tr')
        print(f"결과 행 수: {len(rows)}")

        if not rows:
            print("결과 없음!")
            await browser.close()
            return

        first_row = rows[0]
        tds = await first_row.query_selector_all('td')
        print(f"첫 번째 행 td 개수: {len(tds)}")
        for i, td in enumerate(tds):
            text = (await td.inner_text()).strip()
            html = await td.inner_html()
            print(f"  td[{i}] text={repr(text)} | html={html[:100]}")
        
        print("\n=== 수량 입력 필드 탐색 ===")
        qty_sels = [
            'input[type="text"][size]',
            'input[type="number"]',
            'input.qty',
            'input[name*="qty"]',
            'input[name*="cnt"]',
            'input[name*="amount"]',
            'td:last-child input',
            'td > input[type="text"]',
        ]
        for sel in qty_sels:
            els = await page.query_selector_all(sel)
            if els:
                print(f"  [{sel}] → {len(els)}개")
                for el in els[:2]:
                    attrs = {}
                    for attr in ['id','name','type','size','class']:
                        v = await el.get_attribute(attr)
                        if v: attrs[attr] = v
                    print(f"    attrs: {attrs}, visible: {await el.is_visible()}")

        print("\n=== 장바구니담기 버튼 정밀 탐색 ===")
        cart_sels = [
            '#btn_saveBag',
            'input[value*="장바구니"]',
            'button:has-text("장바구니담기")',
            'a:has-text("장바구니담기")',
            'input[onclick*="saveBag"]',
            'input[onclick*="cart"]',
            'button[onclick*="saveBag"]',
            '[id*="saveBag"]',
            '[id*="cart"]',
            '[id*="Cart"]',
        ]
        for sel in cart_sels:
            try:
                els = await page.query_selector_all(sel)
                if els:
                    print(f"  [{sel}] → {len(els)}개")
                    for el in els[:2]:
                        attrs = {}
                        for attr in ['id','name','type','value','onclick']:
                            v = await el.get_attribute(attr)
                            if v: attrs[attr] = v
                        print(f"    attrs: {attrs}, visible: {await el.is_visible()}")
            except Exception as e:
                print(f"  [{sel}] error: {e}")

        print("\n=== HTML 내 onClick saveBag 탐색 ===")
        result = await page.evaluate("""() => {
            const all = document.querySelectorAll('[onclick]');
            const matches = [];
            for(const el of all) {
                const oc = el.getAttribute('onclick') || '';
                if(oc.toLowerCase().includes('bag') || oc.toLowerCase().includes('cart') || oc.toLowerCase().includes('order')) {
                    matches.push({tag: el.tagName, id: el.id, value: el.value || el.innerText, onclick: oc.substring(0, 100)});
                }
            }
            return matches;
        }""")
        for r in result:
            print(f"  {r}")

        print("\n=== 완료 → 10초 후 닫힘 ===")
        await page.screenshot(path='screenshots/_debug_06_selector.png')
        await page.wait_for_timeout(10000)
        await browser.close()

asyncio.run(run())
