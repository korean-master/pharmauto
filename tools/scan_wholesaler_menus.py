"""도매상 사이트 메뉴 구조 탐색 스크립트.

로그인 후 모든 링크/메뉴를 스캔해서 주문이력/입고이력 관련 페이지를 찾는다.
"""

import asyncio
import json
import os
import sys

# 프로젝트 루트 추가
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from playwright.async_api import async_playwright


# 이력 관련 키워드
HISTORY_KEYWORDS = [
    "주문", "이력", "거래", "입고", "매입", "구매", "내역",
    "반품", "출고", "납품", "order", "history", "purchase",
    "transaction", "delivery", "return",
]


async def scan_site(name: str, login_url: str, user_id: str, password: str,
                    login_selectors: dict):
    """도매상 사이트에 로그인 후 메뉴 구조를 스캔한다."""
    print(f"\n{'='*60}")
    print(f"  {name} 사이트 메뉴 탐색")
    print(f"{'='*60}")

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    page = await browser.new_page()

    # 다이얼로그 자동 수락
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

    try:
        # 1. 로그인
        print(f"\n[1] 로그인: {login_url}")
        await page.goto(login_url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        await page.fill(login_selectors["id"], user_id)
        await page.fill(login_selectors["pw"], password)
        await page.click(login_selectors["btn"])
        await page.wait_for_timeout(4000)

        current_url = page.url
        print(f"    로그인 후 URL: {current_url}")

        # 2. 현재 페이지의 모든 링크 수집
        print(f"\n[2] 메인 페이지 링크 스캔...")
        all_links = await _collect_links(page)
        print(f"    총 {len(all_links)}개 링크 발견")

        # 3. 메뉴 요소 스캔 (nav, sidebar, header 등)
        print(f"\n[3] 메뉴/네비게이션 요소 스캔...")
        menu_items = await _collect_menu_items(page)
        print(f"    총 {len(menu_items)}개 메뉴 항목 발견")

        # 4. 이력 관련 링크 필터링
        print(f"\n[4] 이력 관련 항목 필터링...")
        history_links = _filter_history_items(all_links + menu_items)

        if history_links:
            print(f"\n    === 이력 관련 항목 {len(history_links)}건 ===")
            for item in history_links:
                print(f"    [{item['type']}] {item['text']}")
                print(f"        URL: {item['href']}")
                if item.get("onclick"):
                    print(f"        onclick: {item['onclick']}")
        else:
            print("    이력 관련 항목을 찾지 못했습니다.")

        # 5. 전체 링크 덤프
        print(f"\n[5] 전체 링크 목록 (텍스트 있는 것만)...")
        text_links = [l for l in all_links + menu_items if l["text"].strip()]
        for item in text_links:
            print(f"    {item['text'][:40]:40s} → {item['href'][:60]}")

        # 6. 이력 관련 페이지 자동 탐색
        if history_links:
            print(f"\n[6] 이력 페이지 자동 탐색...")
            for item in history_links[:3]:  # 상위 3개만
                href = item["href"]
                if not href or href == "#" or href.startswith("javascript:"):
                    # onclick이 있으면 클릭 시도
                    if item.get("selector"):
                        print(f"\n    클릭: {item['text']}")
                        try:
                            await page.click(item["selector"])
                            await page.wait_for_timeout(3000)
                            new_url = page.url
                            print(f"    → 이동 URL: {new_url}")

                            # 이 페이지의 구조 분석
                            sub_info = await _analyze_page(page)
                            print(f"    → 테이블: {sub_info['tables']}개, "
                                  f"검색폼: {sub_info['search_forms']}개, "
                                  f"날짜선택: {sub_info['date_selects']}개")

                            await page.go_back()
                            await page.wait_for_timeout(1000)
                        except Exception as e:
                            print(f"    → 클릭 실패: {e}")
                    continue

                if href.startswith("http"):
                    target = href
                elif href.startswith("/"):
                    from urllib.parse import urljoin
                    target = urljoin(current_url, href)
                else:
                    continue

                print(f"\n    방문: {item['text']} → {target}")
                try:
                    await page.goto(target, wait_until="domcontentloaded",
                                    timeout=10000)
                    await page.wait_for_timeout(2000)

                    sub_info = await _analyze_page(page)
                    print(f"    → 최종 URL: {page.url}")
                    print(f"    → 테이블: {sub_info['tables']}개, "
                          f"검색폼: {sub_info['search_forms']}개, "
                          f"날짜선택: {sub_info['date_selects']}개")

                    if sub_info["tables"] > 0:
                        headers = sub_info.get("table_headers", [])
                        if headers:
                            print(f"    → 테이블 헤더: {headers[:10]}")
                except Exception as e:
                    print(f"    → 방문 실패: {e}")

        # 결과 저장
        result = {
            "name": name,
            "login_url": login_url,
            "main_url": current_url,
            "all_links": text_links,
            "history_links": history_links,
        }
        return result

    finally:
        print(f"\n브라우저를 열어두겠습니다. 직접 탐색 후 Ctrl+C로 종료하세요.")
        try:
            # 사용자가 직접 볼 수 있게 30초 대기
            await page.wait_for_timeout(30000)
        except Exception:
            pass
        await browser.close()
        await pw.stop()


async def _collect_links(page) -> list[dict]:
    """페이지의 모든 <a> 태그를 수집한다."""
    links = []
    elements = await page.query_selector_all("a")
    for el in elements:
        try:
            href = await el.get_attribute("href") or ""
            text = (await el.inner_text()).strip().replace("\n", " ")[:80]
            onclick = await el.get_attribute("onclick") or ""
            links.append({
                "type": "link",
                "href": href,
                "text": text,
                "onclick": onclick,
                "selector": None,
            })
        except Exception:
            continue
    return links


async def _collect_menu_items(page) -> list[dict]:
    """메뉴/네비게이션 요소를 수집한다."""
    items = []

    # 다양한 메뉴 셀렉터로 시도
    selectors = [
        "nav a", "nav li", ".menu a", ".nav a", ".sidebar a",
        "#menu a", "#nav a", "#sidebar a",
        "[class*='menu'] a", "[class*='nav'] a", "[class*='side'] a",
        "header a", ".header a", "#header a",
        ".gnb a", ".lnb a", ".snb a",  # 한국 사이트 일반적 패턴
        "[class*='gnb'] a", "[class*='lnb'] a",
        "button[onclick]", "li[onclick]", "div[onclick]",
    ]

    seen_texts = set()
    for selector in selectors:
        try:
            elements = await page.query_selector_all(selector)
            for i, el in enumerate(elements):
                try:
                    text = (await el.inner_text()).strip().replace("\n", " ")[:80]
                    if not text or text in seen_texts:
                        continue
                    seen_texts.add(text)

                    href = await el.get_attribute("href") or ""
                    onclick = await el.get_attribute("onclick") or ""
                    items.append({
                        "type": "menu",
                        "href": href,
                        "text": text,
                        "onclick": onclick,
                        "selector": f"{selector}:nth-of-type({i+1})" if not href or href == "#" else None,
                    })
                except Exception:
                    continue
        except Exception:
            continue
    return items


def _filter_history_items(items: list[dict]) -> list[dict]:
    """이력 관련 키워드가 포함된 항목을 필터링한다."""
    result = []
    for item in items:
        text_lower = (item["text"] + item["href"] + item.get("onclick", "")).lower()
        score = sum(1 for kw in HISTORY_KEYWORDS if kw in text_lower)
        if score > 0:
            item["score"] = score
            result.append(item)
    result.sort(key=lambda x: x["score"], reverse=True)
    return result


async def _analyze_page(page) -> dict:
    """페이지의 구조를 분석한다 (테이블, 검색폼, 날짜선택 등)."""
    info = {"tables": 0, "search_forms": 0, "date_selects": 0, "table_headers": []}

    try:
        tables = await page.query_selector_all("table")
        info["tables"] = len(tables)

        # 첫 번째 테이블의 헤더 추출
        if tables:
            headers = await tables[0].query_selector_all("th")
            for h in headers:
                text = (await h.inner_text()).strip()
                if text:
                    info["table_headers"].append(text)
    except Exception:
        pass

    try:
        forms = await page.query_selector_all(
            'input[type="search"], input[placeholder*="검색"], '
            'input[placeholder*="조회"], input[placeholder*="품목"], '
            'input[placeholder*="약품"]'
        )
        info["search_forms"] = len(forms)
    except Exception:
        pass

    try:
        dates = await page.query_selector_all(
            'input[type="date"], input[class*="date"], '
            'select:has(option:has-text("전체")), '
            'select:has(option:has-text("1년")), '
            'select:has(option:has-text("개월"))'
        )
        info["date_selects"] = len(dates)
    except Exception:
        pass

    return info


async def main():
    from core.crypto import load_wholesalers_secure

    ws = load_wholesalers_secure()

    results = {}

    # 지오영
    geo = ws.get("geo", {})
    if geo.get("id") and geo.get("pw"):
        results["geo"] = await scan_site(
            name="지오영",
            login_url="https://bpm.geoweb.kr/",
            user_id=geo["id"],
            password=geo["pw"],
            login_selectors={
                "id": "#LoginID",
                "pw": "#Password",
                "btn": "button.btn_login",
            },
        )

    # 백제약품
    baekje = ws.get("baekje", {})
    if baekje.get("id") and baekje.get("pw"):
        results["baekje"] = await scan_site(
            name="백제약품",
            login_url="http://www.ibjp.kr/dist/login",
            user_id=baekje["id"],
            password=baekje["pw"],
            login_selectors={
                "id": 'input[type="text"]',
                "pw": 'input[type="password"]',
                "btn": "button.login_btn",
            },
        )

    # 결과 저장
    out_path = os.path.join(ROOT, "data", "wholesaler_menu_scan.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
