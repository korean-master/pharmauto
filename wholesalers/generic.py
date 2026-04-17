"""범용 도매상 자동화 - 사이트 구조 자동 탐지."""

import asyncio
import json
import math
import os
import re
import sys

from wholesalers.base import WholesalerBase, choose_best_pack, parse_pack_size


class GenericWholesaler(WholesalerBase):
    """사이트 구조를 자동 탐지하여 주문하는 범용 도매상 클래스.

    첫 실행 시 로그인/검색/장바구니 셀렉터를 자동 탐지하고
    selector_store를 통해 캐시한다.
    이후엔 캐시된 셀렉터로 바로 동작한다.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self._wid = config.get("_wid", self.name)
        self._selectors = self._load_selectors()

    # ────── 셀렉터 캐시 (selector_store 경유) ──────

    def _load_selectors(self) -> dict:
        from core.selector_store import load_selectors
        return load_selectors(self._wid, url=self.url)

    def _save_selectors(self, selectors: dict):
        from core.selector_store import save_selectors
        self._selectors = selectors
        save_selectors(self._wid, selectors)
        self._progress("셀렉터 저장 완료")

    # ────── 자동 탐지: 로그인 ──────

    async def _navigate_to_login(self):
        """로그인 폼이 현재 페이지에 없으면 로그인 페이지로 이동한다."""
        page = self._page

        # 이미 로그인 폼이 있는지 체크
        pw_field = await page.query_selector('input[type="password"]')
        if pw_field and await pw_field.is_visible():
            return  # 이미 로그인 폼 있음

        # 로그인 링크/버튼 클릭 시도
        login_links = [
            'a:has-text("로그인")',
            'a:has-text("LOGIN")',
            'a:has-text("Log in")',
            'button:has-text("로그인")',
            'a[href*="login"]',
            'a[href*="Login"]',
            'a[href*="signin"]',
        ]
        for sel in login_links:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    await page.wait_for_timeout(3000)
                    self._progress("  로그인 페이지로 이동")
                    return
            except Exception:
                continue

    async def _detect_login(self) -> dict:
        """로그인 폼 셀렉터를 자동 탐지한다."""
        page = self._page
        selectors = {}

        # 로그인 폼이 없으면 로그인 페이지로 이동
        await self._navigate_to_login()

        # ID 입력 필드 탐지
        id_candidates = [
            'input#LoginID',
            'input#userId', 'input#user_id', 'input#username',
            'input[name="userId"]', 'input[name="user_id"]',
            'input[name="username"]', 'input[name="id"]',
            'input[placeholder*="아이디"]', 'input[placeholder*="ID"]',
            'input[type="text"]:not([readonly])',
        ]
        for sel in id_candidates:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                selectors["id_input"] = sel
                self._progress(f"  ID 필드 탐지: {sel}")
                break

        # PW 입력 필드 탐지
        pw_candidates = [
            'input#Password', 'input#password', 'input#userPw',
            'input[name="password"]', 'input[name="userPw"]',
            'input[name="pw"]',
            'input[type="password"]',
        ]
        for sel in pw_candidates:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                selectors["pw_input"] = sel
                self._progress(f"  PW 필드 탐지: {sel}")
                break

        # 로그인 버튼 탐지
        btn_candidates = [
            'button.btn_login', 'button.login_btn',
            'button:has-text("로그인")', 'button:has-text("LOGIN")',
            'input[type="submit"]',
            'button[type="submit"]',
            'a:has-text("로그인")',
        ]
        for sel in btn_candidates:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                selectors["login_btn"] = sel
                self._progress(f"  로그인 버튼 탐지: {sel}")
                break

        return selectors

    # ────── 자동 탐지: 검색 ──────

    async def _detect_search(self) -> dict:
        """약품 검색 관련 셀렉터를 자동 탐지한다.

        1단계: 알려진 패턴으로 탐지
        2단계: 조회/검색 버튼 주변 input 탐지 (폴백)
        3단계: label 텍스트 기반 탐지 (폴백)
        """
        page = self._page
        selectors = {}

        # ── 1단계: 알려진 패턴 ──
        search_candidates = [
            'input#txt_product',
            'input#P_SRH_KEY',
            'input#tx_physic',
            'input#srchTxt',
            'input#searchKeyword',
            'input#prodNm',
            'input[placeholder*="보험코드"]',
            'input[placeholder*="품목명"]',
            'input[placeholder*="약품"]',
            'input[placeholder*="상품"]',
            'input[placeholder*="검색"]',
            'input[placeholder*="KD코드"]',
            'input[placeholder*="제품명"]',
            'input.search-input', 'input.product-input',
            'input[name="searchWord"]', 'input[name="keyword"]',
            'input[name="tx_physic"]', 'input[name="srchText"]',
        ]
        for sel in search_candidates:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                selectors["search_input"] = sel
                self._progress(f"  검색 필드 탐지: {sel}")
                break

        # ── 2단계: 조회/검색 버튼 주변 input 탐지 (1단계 실패 시) ──
        if not selectors.get("search_input"):
            btn_labels = [
                'input[type="submit"][value*="조회"]',
                'input[type="button"][value*="조회"]',
                'button:has-text("조회")',
                'button:has-text("검색")',
                'a:has-text("조회")',
            ]
            for btn_sel in btn_labels:
                btn = await page.query_selector(btn_sel)
                if not btn or not await btn.is_visible():
                    continue
                try:
                    # 같은 form/table/div 안의 텍스트 input 탐색
                    container = await btn.evaluate_handle(
                        'el => el.closest("form") || el.closest("table") || el.parentElement'
                    )
                    inputs = await container.query_selector_all(
                        'input[type="text"], input:not([type]), input[type="search"]'
                    )
                    for inp in inputs:
                        if not await inp.is_visible():
                            continue
                        inp_id = await inp.get_attribute("id") or ""
                        inp_name = await inp.get_attribute("name") or ""
                        if inp_id:
                            sel = f"#{inp_id}"
                        elif inp_name:
                            sel = f'input[name="{inp_name}"]'
                        else:
                            sel = 'input[type="text"]'
                        selectors["search_input"] = sel
                        selectors["search_btn"] = btn_sel
                        self._progress(f"  검색 필드 탐지(버튼 근처): {sel}")
                        break
                except Exception:
                    pass
                if selectors.get("search_input"):
                    break

        # ── 3단계: label 텍스트 기반 input 탐지 (여전히 없을 때) ──
        if not selectors.get("search_input"):
            for label_text in ["제품명", "품목명", "약품명", "KD코드", "검색어", "보험코드"]:
                try:
                    label = await page.query_selector(
                        f'label:has-text("{label_text}"), td:has-text("{label_text}")'
                    )
                    if not label:
                        continue
                    for_attr = await label.get_attribute("for") or ""
                    if for_attr:
                        inp = await page.query_selector(f"#{for_attr}")
                        if inp and await inp.is_visible():
                            selectors["search_input"] = f"#{for_attr}"
                            self._progress(f"  검색 필드 탐지(label): #{for_attr}")
                            break
                    # label 다음 sibling input 탐색
                    sibling_inp = await label.evaluate_handle(
                        'el => el.nextElementSibling'
                    )
                    if sibling_inp:
                        tag = await sibling_inp.evaluate('el => el.tagName')
                        if tag and tag.upper() == "INPUT":
                            inp_id = await sibling_inp.get_attribute("id") or ""
                            inp_name = await sibling_inp.get_attribute("name") or ""
                            sel = f"#{inp_id}" if inp_id else f'input[name="{inp_name}"]' if inp_name else None
                            if sel:
                                selectors["search_input"] = sel
                                self._progress(f"  검색 필드 탐지(label sibling): {sel}")
                                break
                except Exception:
                    continue

        # ── 검색 버튼 탐지 ──
        if not selectors.get("search_btn"):
            btn_candidates = [
                '#btn_search', '#btnSearch', '#btn_search2', '#searchBtn',
                'button.btn_search', 'button.search-btn',
                'button[onclick*="Srh"]', 'button[onclick*="search"]',
                'input[type="submit"][value*="조회"]',
                'input[type="button"][value*="조회"]',
                'input[type="submit"]',
                'img[alt*="조회"]', 'img[alt*="검색"]', 'img[src*="search"]',
                'button:has-text("조회")',
                'button:has-text("검색")',
                'a:has(img[alt*="조회"])', 'a:has(img[alt*="검색"])',
                'a:has-text("조회")', # 최후의 수단
            ]
            for sel in btn_candidates:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    selectors["search_btn"] = sel
                    self._progress(f"  검색 버튼 탐지: {sel}")
                    break

        return selectors

    # ────── 자동 탐지: 주문 가능 페이지 탐색 ──────

    async def _is_orderable_page(self) -> bool:
        """현재 페이지가 약품 주문/장바구니 담기가 가능한 페이지인지 판단한다.

        기준:
        - 검색 input + 약품 관련 키워드가 있거나
        - 장바구니/담기/추가 버튼이 있거나
        - 제품 테이블 + 수량 input이 있으면 True
        """
        page = self._page

        # 검색 input 있으면 — 단, 거래처/비약품 페이지가 아닌지 확인
        search = await self._detect_search()
        if search.get("search_input"):
            # 페이지에 약품 관련 키워드가 있는지 확인
            body_text = await page.inner_text("body")
            drug_keywords = ["보험코드", "약품", "제품", "품목", "장바구니", "담기",
                             "주문", "규격", "포장", "단가"]
            non_drug_keywords = ["거래처코드", "거래처명", "사업자번호"]
            drug_score = sum(1 for kw in drug_keywords if kw in body_text)
            non_drug_score = sum(1 for kw in non_drug_keywords if kw in body_text)
            if drug_score >= 2 and non_drug_score < 2:
                return True
            if non_drug_score >= 2 and drug_score < 2:
                return False
            # 점수가 애매하면 검색 input 존재만으로 True
            return True

        # 장바구니/담기 버튼 있으면 OK
        cart_btn_sels = [
            'button:has-text("담기")',
            'button:has-text("추가")',
            'button:has-text("장바구니")',
            'input[type="button"][value*="담기"]',
            'input[type="button"][value*="추가"]',
            'a:has-text("담기")',
            'a:has-text("추가")',
        ]
        for sel in cart_btn_sels:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                return True

        # 테이블 + 수량 input 조합
        rows = await page.query_selector_all('table tbody tr')
        if rows:
            qty_inp = await page.query_selector(
                'input[type="number"], input[name*="qty"], input[name*="cnt"]'
            )
            if qty_inp:
                return True

        return False

    async def _find_order_page(self) -> dict:
        """로그인 후 실제 약품 주문이 가능한 페이지를 전체 메뉴 탐색으로 자동 발견한다.

        - 모든 nav 링크 시도 (키워드 필터 없음)
        - 각 페이지에서 search_input OR 장바구니 버튼 기준으로 판단
        - order_url + search 셀렉터를 반환

        Returns:
            {"order_url": str, "search": dict} 또는 빈 dict
        """
        page = self._page
        current_url = page.url
        from urllib.parse import urljoin

        self._progress("주문 페이지 전체 메뉴 탐색 중...")

        # ── 1단계: 현재 페이지가 이미 주문 가능한지 확인 ──
        if await self._is_orderable_page():
            search = await self._detect_search()
            self._progress(f"  ✅ 현재 페이지가 주문 가능: {current_url}")
            return {"order_url": current_url, "search": search}

        # ── 2단계: 모든 링크 수집 (키워드 필터 없음) ──
        try:
            links = await page.query_selector_all("a")
            all_links = []
            seen_hrefs = set()

            for link in links:
                try:
                    text = (await link.inner_text()).strip().replace("\n", " ")[:40]
                    href = await link.get_attribute("href") or ""
                    if not href or href in ("#", "javascript:void(0)", "") or href in seen_hrefs:
                        continue
                    if href.startswith("javascript:"):
                        continue
                    seen_hrefs.add(href)
                    all_links.append({"text": text, "href": href})
                except Exception:
                    continue

            self._progress(f"  전체 링크 {len(all_links)}개 발견 → 순차 탐색")
        except Exception as e:
            self._progress(f"  링크 수집 오류: {e}")
            return {}

        # ── 3단계: 모든 링크 방문 → 주문 가능 판단 ──
        for cand in all_links[:15]:  # 최대 15개 링크 시도
            href = cand["href"]
            target = href if href.startswith("http") else urljoin(current_url, href)

            # 현재 URL과 같으면 스킵
            if target == current_url:
                continue

            self._progress(f"  [{cand['text']}] 시도: {target}")
            try:
                await page.goto(target, wait_until="domcontentloaded", timeout=10000)
                await page.wait_for_timeout(2000)
            except Exception:
                continue

            if await self._is_orderable_page():
                search = await self._detect_search()
                self._progress(f"  ✅ 주문 페이지 발견: {target}")
                # 원래 페이지로 복귀
                try:
                    await page.goto(current_url, wait_until="domcontentloaded", timeout=8000)
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass
                return {"order_url": target, "search": search}

        # ── 4단계: 복귀 후 실패 반환 ──
        try:
            await page.goto(current_url, wait_until="domcontentloaded", timeout=8000)
            await page.wait_for_timeout(1000)
        except Exception:
            pass

        self._progress("  전체 메뉴 탐색 실패 - 주문 페이지 찾지 못함")
        return {}

    # ────── 자동 탐지: 결과 테이블 ──────

    # 테이블 헤더 → 컬럼 타입 매핑 (한글/영문 도매상 공통)
    HEADER_MAP = {
        "code": ["보험코드", "보험", "코드", "code", "보험CD"],
        "name": ["제품명", "약품명", "품목명", "상품명", "product", "name"],
        "unit": ["규격", "포장", "단위", "standard", "unit", "spec"],
        "price": ["단가", "가격", "금액", "price", "공급가"],
        "stock": ["재고", "재고량", "stock", "잔량"],
        "qty": ["수량", "주문수량", "qty", "quantity"],
        "cart": ["추가", "담기", "장바구니", "cart", "주문"],
    }

    # 약품 테이블이 아닌 것을 구분하기 위한 거부 키워드
    _NON_DRUG_HEADERS = ["거래처코드", "거래처명", "사업자번호", "거래처주소",
                         "거래처구분", "회원명", "회원코드", "게시판", "공지"]

    async def _detect_result_table(self, insurance_code: str) -> dict:
        """검색 결과 테이블 구조를 헤더 텍스트 기반으로 탐지한다."""
        page = self._page
        selectors = {}

        # 테이블 행 탐지
        row_candidates = [
            'table tbody tr',
            'tr.tr-product-list',
            '.product-list tr',
            '.search-result tr',
        ]
        for sel in row_candidates:
            rows = await page.query_selector_all(sel)
            if rows:
                selectors["result_rows"] = sel
                self._progress(f"  결과 행 탐지: {sel} ({len(rows)}행)")
                break

        if not selectors.get("result_rows"):
            return selectors

        # 1. 테이블 헤더(th) 읽기 → 컬럼 매핑
        # 검색 결과 행이 속한 테이블의 헤더만 가져옴
        first_table = await rows[0].evaluate_handle('el => el.closest("table")')
        headers = await first_table.query_selector_all('thead th')
        if not headers:
            headers = await first_table.query_selector_all('tr:first-child th')
        header_texts = []
        for th in headers:
            text = (await th.inner_text()).strip().replace("\n", " ")
            header_texts.append(text)

        if header_texts:
            self._progress(f"  테이블 헤더: {header_texts}")

            # 거래처/비약품 테이블 감지 → 거부
            joined = " ".join(header_texts)
            non_drug_count = sum(1 for kw in self._NON_DRUG_HEADERS if kw in joined)
            if non_drug_count >= 2:
                self._progress(f"  ⚠ 약품 테이블 아님 (거래처/기타) → 무시")
                return {}
            for i, header in enumerate(header_texts):
                header_lower = header.lower()
                for col_type, keywords in self.HEADER_MAP.items():
                    for kw in keywords:
                        if kw.lower() in header_lower:
                            key = f"{col_type}_col_idx"
                            if key not in selectors:
                                selectors[key] = i
                                self._progress(f"  {col_type} 컬럼: {i}번째 ({header})")
                            break

        # 2. 헤더로 못 찾은 컬럼은 데이터 행에서 추정
        first_row = rows[0]
        cells = await first_row.query_selector_all('td')

        if "code_col_idx" not in selectors:
            for i, cell in enumerate(cells):
                text = (await cell.inner_text()).strip()
                if insurance_code in text:
                    selectors["code_col_idx"] = i
                    break

        if "unit_col_idx" not in selectors:
            for i, cell in enumerate(cells):
                text = (await cell.inner_text()).strip()
                if parse_pack_size(text) > 0:
                    selectors["unit_col_idx"] = i
                    break

        if "name_col_idx" not in selectors:
            max_len = 0
            max_idx = -1
            skip = {selectors.get("code_col_idx"), selectors.get("unit_col_idx"),
                    selectors.get("price_col_idx"), selectors.get("stock_col_idx")}
            for i, cell in enumerate(cells):
                if i in skip:
                    continue
                text = (await cell.inner_text()).strip()
                if len(text) > max_len:
                    max_len = len(text)
                    max_idx = i
            if max_idx >= 0:
                selectors["name_col_idx"] = max_idx

        # 3. 수량 입력 필드
        qty_candidates = [
            'input[type="number"]',
            'input.qty', 'input.quantity',
            '.td-qty input', 'td input[size]',
            'input[name*="qty"]', 'input[name*="quantity"]',
            'input[type="text"]',
        ]
        for cell in cells:
            for sel in qty_candidates:
                el = await cell.query_selector(sel)
                if el:
                    selectors["qty_input"] = sel
                    selectors["qty_input_in_row"] = True
                    self._progress(f"  수량 입력: {sel}")
                    break
            if "qty_input" in selectors:
                break

        # 4. 행 체크박스 탐지 (페이지 레벨 담기 버튼일 때 필요)
        chk_candidates = [
            'input[type="checkbox"]',
            'input[name^="chk"]', 'input[name^="check"]',
            'input[id^="chk"]', 'input[id^="check"]',
        ]
        for sel in chk_candidates:
            el = await first_row.query_selector(sel)
            if el:
                selectors["row_checkbox"] = sel
                self._progress(f"  행 체크박스: {sel}")
                break

        # 5. 담기/추가 버튼 — 행 내부 먼저  (※ 행 체크박스가 있으면 페이지 레벨 버튼과 함께 사용)
        cart_candidates = [
            '#btn_saveBag', '#btn_cart', '#btnCart', '#addCart',
            'button.btn_cart', '.btn-cart',
            'img[alt*="담기"]', 'img[alt*="장바구니"]',
            'button:has-text("추가")',
            'button:has-text("담기")',
            'button:has-text("장바구니")',
            'a:has-text("추가")',
            'a:has-text("담기")',
            'a:has-text("장바구니 담기")',
            'a:has(img[alt*="담기"])',
            'td:last-child a',
            'input[type="button"][value*="추가"]',
            'input[type="button"][value*="담기"]',
            'span:has-text("추가")',
        ]
        for sel in cart_candidates:
            el = await first_row.query_selector(sel)
            if el:
                selectors["cart_btn"] = sel
                selectors["cart_btn_in_row"] = True
                self._progress(f"  담기 버튼 (행 내부): {sel}")
                break

        # 행 내부에 없으면 페이지에서
        if "cart_btn" not in selectors:
            for sel in cart_candidates:
                el = await page.query_selector(sel)
                if el:
                    selectors["cart_btn"] = sel
                    selectors["cart_btn_in_row"] = False
                    self._progress(f"  담기 버튼 (페이지): {sel}")
                    break

        # 6. 가격 컬럼이 있으면 기록
        if "price_col_idx" in selectors:
            self._progress(f"  가격 컬럼: {selectors['price_col_idx']}번째")

        return selectors

    # ────── 자동 탐지: 주문확정 ──────

    async def _detect_confirm(self) -> dict:
        """주문확정 버튼을 탐지한다."""
        page = self._page
        selectors = {}

        confirm_candidates = [
            'button:has-text("주문확정")',
            'button:has-text("주문등록")',
            'button:has-text("주문하기")',
            'button:has-text("결제")',
            'button:has-text("발주")',
            '#section_cart_total_btn_order',
            'button.order-btn',
        ]
        for sel in confirm_candidates:
            el = await page.query_selector(sel)
            if el:
                selectors["confirm_btn"] = sel
                self._progress(f"  주문확정 버튼 탐지: {sel}")
                break

        return selectors

    # ────── 자동 탐지: 이력/반품 페이지 ──────

    _HISTORY_KEYWORDS = [
        "주문", "이력", "거래", "입고", "매입", "내역",
        "반품", "출고", "납품", "매출", "원장", "일련",
        "구매", "발주", "배송", "조회",
    ]
    _HISTORY_TABLE_KEYWORDS = [
        "제조번호", "로트", "lot", "유효기한", "유효", "만료",
        "주문일", "입고일", "출고일", "배송일", "거래일", "납품일",
        "품명", "약품명", "상품명", "제품명",
        "수량", "단가", "금액",
    ]
    # 테이블 필수 키워드 — 이 중 1개 이상이면 이력 테이블 후보
    _HISTORY_TABLE_REQUIRED = [
        "제조번호", "로트", "lot", "유효기한", "유효", "만료",
        "주문일", "입고일", "출고일", "배송일", "거래일", "납품일",
    ]

    async def _detect_history_page(self) -> dict | None:
        """로그인 상태에서 이력/반품 관련 페이지를 탐색한다.

        analyze_site 이후 호출 시 주문 페이지에 있을 수 있으므로
        반드시 메인(홈) 페이지로 이동 후 메뉴를 스캔한다.
        """
        page = self._page
        return_url = page.url

        try:
            # ── 1) 메인 페이지로 이동해서 전체 네비게이션 스캔 ──
            await page.goto(self.url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            await self._close_popup()

            # ── 2) 모든 클릭 가능한 요소에서 이력 관련 링크 찾기 ──
            candidates = await self._scan_history_links(page)

            if not candidates:
                self._progress("  이력 관련 메뉴 없음")
                return None

            candidates.sort(key=lambda x: x["score"], reverse=True)
            self._progress(f"  이력 후보 {len(candidates)}개: "
                           f"{', '.join(c['text'] for c in candidates[:3])}")

            # ── 3) 상위 후보 페이지 방문 → 테이블 분석 ──
            from urllib.parse import urljoin

            for cand in candidates[:5]:
                href = cand["href"]

                # JS 링크는 클릭으로 접근
                if not href or href in ("#", "javascript:void(0)"):
                    try:
                        el = cand.get("element")
                        if el:
                            await el.click(force=True)
                            await page.wait_for_timeout(3000)
                            await self._close_popup()
                    except Exception:
                        continue
                else:
                    target = urljoin(self.url, href) if not href.startswith("http") else href
                    try:
                        await page.goto(target, wait_until="domcontentloaded",
                                        timeout=10000)
                        await page.wait_for_timeout(2000)
                        await self._close_popup()
                    except Exception:
                        continue

                # 현재 페이지에서 이력 테이블 분석
                config = await self._analyze_history_table(page, cand)
                if config:
                    # 성공 — 원래 페이지로 복귀
                    try:
                        await page.goto(return_url, wait_until="domcontentloaded",
                                        timeout=10000)
                    except Exception:
                        pass
                    return config

                # 실패 — 메인 페이지로 돌아가서 다음 후보
                try:
                    await page.goto(self.url, wait_until="domcontentloaded",
                                    timeout=10000)
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass

            # 원래 페이지로 복귀
            try:
                await page.goto(return_url, wait_until="domcontentloaded",
                                timeout=10000)
            except Exception:
                pass

        except Exception as e:
            self._progress(f"  이력 페이지 탐색 오류: {e}")

        return None

    async def _scan_history_links(self, page) -> list[dict]:
        """페이지에서 이력 관련 링크/메뉴를 모두 수집한다."""
        candidates = []
        seen = set()

        # a 태그 + onclick 클릭 가능한 요소까지 스캔
        selectors = ["a", "[onclick]", "li[class*='menu']", "span[class*='menu']"]
        for sel in selectors:
            try:
                elements = await page.query_selector_all(sel)
            except Exception:
                continue

            for el in elements:
                try:
                    href = await el.get_attribute("href") or ""
                    onclick = await el.get_attribute("onclick") or ""
                    text = (await el.inner_text()).strip().replace("\n", " ")[:60]
                    if not text or len(text) < 2 or text in seen:
                        continue
                    seen.add(text)

                    text_lower = text.lower()
                    href_lower = (href + " " + onclick).lower()

                    score = sum(1 for kw in self._HISTORY_KEYWORDS
                                if kw in text_lower or kw in href_lower)
                    if score > 0:
                        candidates.append({
                            "text": text,
                            "href": href if href and href != "#" else "",
                            "onclick": onclick,
                            "score": score,
                            "element": el,
                        })
                except Exception:
                    continue

        return candidates

    async def _analyze_history_table(self, page, cand: dict) -> dict | None:
        """현재 페이지에서 이력 테이블을 분석하여 config를 반환한다."""
        # 테이블 헤더에서 이력 관련 컬럼 찾기
        tables = await page.query_selector_all("table")
        for ti, table in enumerate(tables):
            headers = await table.query_selector_all("th")
            h_texts = []
            for h in headers:
                h_texts.append((await h.inner_text()).strip().lower())

            if not h_texts or len(h_texts) < 3:
                continue

            h_joined = " ".join(h_texts)

            # 필수 키워드 1개 이상 + 전체 키워드 2개 이상
            required_score = sum(1 for kw in self._HISTORY_TABLE_REQUIRED
                                 if kw in h_joined)
            total_score = sum(1 for kw in self._HISTORY_TABLE_KEYWORDS
                              if kw in h_joined)

            if required_score >= 1 and total_score >= 2:
                self._progress(f"  이력 테이블 발견: {cand['text']} (table[{ti}])")

                # 컬럼 매핑
                col_map = {}
                for idx, ht in enumerate(h_texts):
                    if any(k in ht for k in ["제품", "상품", "품명", "약품"]):
                        col_map.setdefault("drug_name", idx)
                    elif any(k in ht for k in ["주문일", "입고일", "출고일",
                                                "배송일", "거래일", "납품일", "날짜"]):
                        col_map.setdefault("date", idx)
                    elif any(k in ht for k in ["수량", "납입"]):
                        col_map.setdefault("qty", idx)
                    elif any(k in ht for k in ["제조번호", "로트", "lot"]):
                        col_map.setdefault("lot_number", idx)
                    elif any(k in ht for k in ["유효기한", "유효", "만료"]):
                        col_map.setdefault("expiry", idx)

                # 검색 필드 탐색
                search_fields = await self._detect_history_search_fields(page)

                href = cand.get("href") or page.url
                # 상대 경로면 그대로 유지
                if href.startswith("http"):
                    from urllib.parse import urlparse
                    parsed = urlparse(href)
                    href = parsed.path + ("?" + parsed.query if parsed.query else "")

                return {
                    "history_url": href,
                    "history_page_name": cand["text"],
                    "search": search_fields,
                    "table": {
                        "index": ti,
                        "columns": col_map,
                        "headers": [h.strip() for h in h_texts],
                    },
                    "auto_detected": True,
                }

        # 테이블이 없어도 검색 가능한 페이지면 기본 config 반환
        search_fields = await self._detect_history_search_fields(page)
        if search_fields.get("keyword"):
            href = cand.get("href") or page.url
            if href.startswith("http"):
                from urllib.parse import urlparse
                parsed = urlparse(href)
                href = parsed.path + ("?" + parsed.query if parsed.query else "")

            self._progress(f"  이력 검색 필드만 발견: {cand['text']} (테이블은 검색 후 생성될 수 있음)")
            return {
                "history_url": href,
                "history_page_name": cand["text"],
                "search": search_fields,
                "table": {"index": 0, "columns": {}, "headers": []},
                "auto_detected": True,
                "table_after_search": True,
            }

        return None

    async def _detect_history_search_fields(self, page) -> dict:
        """이력 페이지에서 검색 필드(약품명, 로트번호, 검색 버튼)를 탐지한다."""
        search_fields = {}

        try:
            inputs = await page.query_selector_all("input[type='text'], input:not([type])")
            for inp in inputs:
                try:
                    if not await inp.is_visible():
                        continue
                except Exception:
                    continue

                ph = (await inp.get_attribute("placeholder") or "").lower()
                name = (await inp.get_attribute("name") or "").lower()
                inp_id = await inp.get_attribute("id") or ""
                combined = ph + " " + name

                if any(k in combined for k in ["품목", "약품", "상품", "검색",
                                                 "제품", "품명", "keyword", "item"]):
                    sel = f"#{inp_id}" if inp_id else f'input[placeholder*="{ph[:10]}"]' if ph else f'input[name*="{name[:10]}"]'
                    search_fields.setdefault("keyword", sel)
                elif any(k in combined for k in ["제조번호", "로트", "lot"]):
                    sel = f"#{inp_id}" if inp_id else f'input[placeholder*="{ph[:10]}"]' if ph else f'input[name*="{name[:10]}"]'
                    search_fields.setdefault("lot_number", sel)
        except Exception:
            pass

        # 검색/조회 버튼
        for sel in ['button:has-text("검색")', 'button:has-text("조회")',
                    'input[type="submit"]', 'input[type="button"][value*="검색"]',
                    'input[type="button"][value*="조회"]',
                    "button.btn_search", "button.lookup-btn",
                    'a:has-text("검색")', 'a:has-text("조회")']:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    search_fields["search_btn"] = sel
                    break
            except Exception:
                continue

        # 기간 설정 버튼 (5년/3년/1년)
        for period in ['button:has-text("5년")', 'button:has-text("3년")',
                       'button:has-text("1년")', 'button:has-text("전체")']:
            try:
                btn = await page.query_selector(period)
                if btn and await btn.is_visible():
                    search_fields["period_btn"] = period
                    break
            except Exception:
                continue

        return search_fields

    # ────── 전체 사이트 분석 ──────

    async def analyze_site(self, test_code: str = "646201260",
                           headless: bool = True) -> dict:
        """사이트 구조를 AI 시각 에이전트로 분석하고 셀렉터를 캐시한다.

        스크린샷 + DOM을 Claude AI에 보내서 셀렉터를 찾는다.
        휴리스틱 패턴 대입 없이 AI가 직접 판단한다.

        Args:
            test_code: 검색 테스트용 보험코드
            headless: 브라우저 표시 여부
        """
        self._progress(f"사이트 분석 시작: {self.url}")
        all_selectors = {"url": self.url, "name": self.name}

        try:
            from core.visual_agent import VisualAgent
            from core.ai_analyzer import _load_api_key

            api_key = _load_api_key()
            agent = VisualAgent(api_key=api_key, wid=self._wid)

            if not agent._can_call_ai():
                self._progress("AI 분석 불가 (Edge Function/API 키 모두 없음)")
                return all_selectors

            # AI 시각 에이전트로 전체 분석 (로그인→검색→테이블→주문확정)
            await self._launch(headless=headless)
            page = self._page
            page.on("dialog", lambda d: d.accept())

            ai_selectors = await agent.run(
                page, self.url, self.user_id, self.password,
                progress=self._progress,
            )

            if ai_selectors:
                for key in ["login", "search", "table", "confirm"]:
                    ai_part = ai_selectors.get(key, {})
                    if ai_part:
                        all_selectors[key] = ai_part
                all_selectors["auto_detected"] = True
                all_selectors["ai_agent_used"] = True
                self._progress("AI 사이트 분석 완료")
            else:
                self._progress("AI 분석 실패 — 셀렉터를 찾지 못함")

            # 이력/반품 페이지 탐색 (별도 네비게이션 필요)
            self._progress("이력/반품 페이지 탐색 중...")
            try:
                history_config = await self._detect_history_page()
                if history_config:
                    all_selectors["history"] = history_config
            except Exception:
                pass

        except Exception as e:
            self._progress(f"사이트 분석 오류: {e}")
            all_selectors["error"] = str(e)
        finally:
            await self._close()

        self._save_selectors(all_selectors)

        # 이력 검색 설정 서버 업로드
        if all_selectors.get("history"):
            try:
                from core.history_config import save_config
                h_cfg = all_selectors["history"]
                h_cfg["name"] = self.name
                h_cfg["base_url"] = self.url
                h_cfg["login"] = all_selectors.get("login", {})
                save_config(self._wid, h_cfg, upload=True)
                self._progress("이력 검색 설정 서버 업로드 완료")
            except Exception:
                pass

        return all_selectors

    # ────── WholesalerBase 구현 ──────

    async def login_async(self, headless: bool = True) -> bool:
        if not self._page:
            await self._launch(headless=headless)
        page = self._page
        page.on("dialog", lambda d: d.accept())

        login = self._selectors.get("login", {})
        id_input = login.get("id_input")
        pw_input = login.get("pw_input")
        login_btn = login.get("login_btn")

        if not id_input or not pw_input:
            # 셀렉터 없으면 자동 탐지 시도
            self._progress("셀렉터 없음 - 사이트 분석 중...")
            await page.goto(self.url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            await self._navigate_to_login()
            detected = await self._detect_login()
            id_input = detected.get("id_input")
            pw_input = detected.get("pw_input")
            login_btn = detected.get("login_btn")
            if not id_input or not pw_input:
                self._progress("로그인 폼 탐지 실패")
                return False
            # 캐시 업데이트
            self._selectors.setdefault("login", {}).update(detected)
            self._save_selectors(self._selectors)
        else:
            await page.goto(self.url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

        self._progress("로그인 중...")
        await page.fill(id_input, self.user_id)
        await page.fill(pw_input, self.password)

        if login_btn:
            try:
                await page.click(login_btn)
            except Exception:
                # 버튼 클릭 실패 시 Enter로 폴백
                await page.press(pw_input, "Enter")
        else:
            # 로그인 버튼 못 찾으면 Enter로 제출
            await page.press(pw_input, "Enter")

        await page.wait_for_timeout(4000)

        # 로그인 성공 판단: 여러 방법으로 체크
        before_url = self.url
        current_url = page.url
        url_changed = current_url != before_url and "login" not in current_url.lower()

        id_field = await page.query_selector(id_input)
        form_gone = not id_field or not await id_field.is_visible()

        # 로그아웃 버튼이 있으면 로그인 성공
        logout_el = None
        for sel in ['a:has-text("로그아웃")', 'a:has-text("LOGOUT")', 'button:has-text("로그아웃")']:
            logout_el = await page.query_selector(sel)
            if logout_el:
                break

        login_success = url_changed or form_gone or (logout_el is not None)

        if login_success:
            self._progress("로그인 성공")
            await self._screenshot(f"generic_{self._wid}_login_ok.png")

            # ── Step 1: 저장된 order_url이 있으면 해당 페이지로 이동 ──
            order_url = self._selectors.get("order_url", "")
            if order_url and order_url != page.url:
                self._progress(f"주문 페이지로 이동: {order_url}")
                try:
                    await page.goto(order_url, wait_until="domcontentloaded", timeout=10000)
                    await page.wait_for_timeout(2000)
                except Exception as e:
                    self._progress(f"주문 페이지 이동 실패: {e} → order_url 초기화")
                    self._selectors.pop("order_url", None)
                    self._save_selectors(self._selectors)

            # ── Step 2: 검색 셀렉터 탐지 (현재 페이지 기준) ──
            if not self._selectors.get("search"):
                search_sel = await self._detect_search()
                self._selectors["search"] = search_sel
                self._save_selectors(self._selectors)

            # ── Step 3: 여전히 검색창 없으면 → 주문 페이지 메뉴 자동 탐색 ──
            if not self._selectors.get("search", {}).get("search_input"):
                self._progress("검색창 없음 → 주문 페이지 메뉴 탐색 중...")
                order_info = await self._find_order_page()
                if order_info.get("search", {}).get("search_input"):
                    self._selectors["order_url"] = order_info["order_url"]
                    self._selectors["search"] = order_info["search"]
                    self._selectors["confidence"] = "provisional"
                    self._save_selectors(self._selectors)
                    self._progress(f"주문 페이지 탐색 성공 → {order_info['order_url']}")

            # ── Step 4: 그래도 없으면 → Claude AI DOM 분석 (최후 수단) ──
            if not self._selectors.get("search", {}).get("search_input"):
                self._progress("메뉴 탐색 실패 → Claude AI 분석 시도 중...")
                try:
                    from core.ai_analyzer import analyze_selectors, is_available
                    if is_available():
                        ai_result = await analyze_selectors(
                            page, site_url=self.url, wid=self._wid
                        )
                        if ai_result:
                            self._selectors.setdefault("search", {}).update(
                                {k: v for k, v in ai_result.items()
                                 if k in ("search_input", "search_btn")}
                            )
                            if ai_result.get("result_rows"):
                                self._selectors.setdefault("table", {})["result_rows"] = ai_result["result_rows"]
                            if ai_result.get("cart_btn"):
                                self._selectors.setdefault("table", {})["cart_btn"] = ai_result["cart_btn"]
                            if ai_result.get("qty_input"):
                                self._selectors.setdefault("table", {})["qty_input"] = ai_result["qty_input"]
                            self._selectors["confidence"] = "provisional"
                            self._save_selectors(self._selectors)
                            self._progress("Claude AI 분석 완료 → 셀렉터 임시 저장")
                    else:
                        self._progress("Claude API 키 없음 - settings.json에 claude_api_key 추가 필요")
                except Exception as e:
                    self._progress(f"Claude AI 분석 오류: {e}")
        else:
            self._progress("로그인 실패")
            await self._screenshot(f"generic_{self._wid}_login_fail.png")

        return login_success

    # ────── test_connection 오버라이드 ──────

    async def test_connection(self, headless: bool = True) -> dict:
        """Generic 도매상 전용 연동 테스트.

        base.py의 test_connection과 다른 점:
        - 하드코딩 테스트 코드가 해당 도매상에 없을 수 있음
        - 1단계: 표준 테스트 코드로 검색 시도
        - 2단계: 전부 실패하면 빈 검색으로 재고 내 임의 약품을 꺼내 장바구니 기능 검증
        → 이 방식은 "장바구니 담기 기능이 작동하는가"를 검증하며,
          특정 약품 코드 존재 여부에 의존하지 않는다.
        """
        TEST_CODES = ["645601261", "643501890", "646201260"]

        try:
            # 1. 로그인
            self._progress("연동 테스트: 로그인 중...")
            if not await self.login_async(headless=headless):
                return {"success": False, "stage": "login", "message": "로그인 실패"}

            page = self._page
            search = self._selectors.get("search", {})
            table = self._selectors.get("table", {})
            search_input = search.get("search_input")
            search_btn = search.get("search_btn")

            if not search_input:
                return {"success": False, "stage": "cart",
                        "message": "검색 셀렉터 없음 - 사이트 분석 필요"}

            # 로그인 직후 URL 저장 (step 2 실패 시 페이지 복구용)
            order_page_url = page.url

            # 2. 표준 테스트 코드로 장바구니 시도
            self._progress("연동 테스트: 표준 코드로 장바구니 테스트...")
            for i, code in enumerate(TEST_CODES):
                try:
                    # 두 번째 코드부터는 페이지 복구 (검색 후 리로드로 꼬일 수 있음)
                    if i > 0:
                        try:
                            await page.goto(order_page_url, wait_until="domcontentloaded")
                            await page.wait_for_timeout(1500)
                        except Exception:
                            pass
                    r = await self._add_item_to_cart(code, 1, 1, 1)
                    if r.get("success"):
                        self._progress(f"연동 테스트: 성공 ({r.get('drug_name', code)})")
                        try:
                            await self._clear_cart()
                        except Exception:
                            pass
                        return {"success": True, "stage": "done", "message": "연동 정상"}
                except Exception:
                    continue

            # 3. 표준 코드 모두 실패 → 페이지 복구 후 광범위 검색으로 장바구니 테스트
            self._progress("연동 테스트: 표준 코드 없음 → 페이지 복구 후 광범위 검색...")
            try:
                # step 2의 반복 검색으로 페이지 상태가 꼬일 수 있으므로 주문 페이지 재접속
                await page.goto(order_page_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                # 검색어 시도 목록 (1글자는 일부 사이트에서 안 될 수 있으므로 여러 개)
                search_words = ["정", "타이레놀", "아스피린"]
                valid_rows = []

                for word in search_words:
                    # 검색 필드가 페이지 리로드로 사라질 수 있으므로 대기
                    try:
                        await page.wait_for_selector(search_input, state="visible", timeout=5000)
                    except Exception:
                        try:
                            await page.goto(order_page_url, wait_until="domcontentloaded")
                            await page.wait_for_timeout(2000)
                            await page.wait_for_selector(search_input, state="visible", timeout=8000)
                        except Exception:
                            self._progress(f"  [{word}] 검색 필드 복구 실패")
                            continue
                    await page.fill(search_input, "")
                    await page.wait_for_timeout(200)
                    await page.fill(search_input, word)
                    await page.wait_for_timeout(200)

                    # 버튼 클릭 또는 Enter (둘 중 하나만 — 더블 포스트백 방지)
                    searched = False
                    if search_btn:
                        try:
                            await page.click(search_btn)
                            searched = True
                        except Exception:
                            pass
                    if not searched:
                        await page.press(search_input, "Enter")

                    await page.wait_for_timeout(3000)

                    row_sel = table.get("result_rows", "table tbody tr")
                    rows = await page.query_selector_all(row_sel)

                    for r in rows:
                        tds = await r.query_selector_all("td")
                        filled = 0
                        for td in tds:
                            if (await td.inner_text()).strip():
                                filled += 1
                        if filled >= 3:
                            valid_rows.append(r)

                    if valid_rows:
                        self._progress(f"  [{word}] 검색 성공 ({len(valid_rows)}행)")
                        break
                    self._progress(f"  [{word}] 결과 없음")

                if not valid_rows:
                    return {"success": False, "stage": "cart",
                            "message": "재고 없음 - 검색 결과 0건"}

                self._progress(f"연동 테스트: 재고 {len(valid_rows)}건 발견 → 첫 번째 항목으로 장바구니 테스트")

                # 첫 번째 행으로 수량 입력 + 담기 버튼 실행
                first_row = valid_rows[0]
                cells = await first_row.query_selector_all("td")
                drug_name = ""
                name_col = table.get("name_col_idx")
                if name_col is not None and name_col < len(cells):
                    drug_name = (await cells[name_col].inner_text()).strip()

                # ── 수량 입력 ──
                qty_el = None
                try:
                    # 1) 저장된 qty_input 셀렉터
                    qty_sel = table.get("qty_input")
                    if qty_sel:
                        qty_el = await first_row.query_selector(qty_sel)
                    # 2) qty_col_idx 컬럼 안의 input
                    if not qty_el:
                        qty_col = table.get("qty_col_idx")
                        if qty_col is not None and qty_col < len(cells):
                            qty_el = await cells[qty_col].query_selector('input')
                    # 3) 폴백 — 행 내 input[type="text"] 중 name에 qty/cnt 포함
                    if not qty_el:
                        for sel in ['input[name*="qty"]', 'input[name*="cnt"]',
                                    'input[type="text"][size]', 'input[type="number"]']:
                            qty_el = await first_row.query_selector(sel)
                            if qty_el:
                                break
                    if qty_el:
                        await qty_el.click()
                        await qty_el.select_text()
                        await qty_el.type("1")
                        await page.wait_for_timeout(300)
                        self._progress("  수량 1 입력 완료")
                    else:
                        self._progress("  수량 입력 필드 없음 (무시)")
                except Exception as e:
                    self._progress(f"  수량 입력 실패 (무시): {e}")

                # ── 행 체크박스 체크 (페이지 레벨 담기 버튼일 때 필수) ──
                cart_in_row = table.get("cart_btn_in_row", False)
                if not cart_in_row:
                    chk_sel = table.get("row_checkbox")
                    chk = None
                    if chk_sel:
                        chk = await first_row.query_selector(chk_sel)
                    if not chk:
                        for sel in ['input[type="checkbox"]', 'input[name^="chk"]']:
                            chk = await first_row.query_selector(sel)
                            if chk:
                                break
                    if chk:
                        try:
                            checked = await chk.is_checked()
                            if not checked:
                                await chk.click(force=True)
                                await page.wait_for_timeout(300)
                                self._progress("  행 체크박스 체크 완료")
                        except Exception as e:
                            self._progress(f"  체크박스 체크 실패: {e}")

                # ── dialog(alert) 메시지 캡처 준비 ──
                _dialog_messages = []

                def _capture_dialog(dialog):
                    _dialog_messages.append(dialog.message)
                    # 기존 핸들러가 accept 하므로 여기서는 캡처만

                page.on("dialog", _capture_dialog)

                # ── 담기 버튼 클릭 ──
                # type=image 버튼은 is_visible() False일 수 있으므로 query 후 바로 click
                cart_clicked = False
                cart_btn_sel = table.get("cart_btn")
                cart_in_row = table.get("cart_btn_in_row", False)

                # 먼저 저장된 셀렉터 시도
                if cart_btn_sel:
                    try:
                        if cart_in_row:
                            btn = await first_row.query_selector(cart_btn_sel)
                        else:
                            btn = await page.query_selector(cart_btn_sel)
                        if btn:
                            await btn.click(force=True)
                            await page.wait_for_timeout(2500)
                            cart_clicked = True
                            self._progress(f"  담기 버튼 클릭 ({cart_btn_sel})")
                    except Exception as e:
                        self._progress(f"  저장된 담기 버튼 실패: {e}")

                # 폴백: 텍스트 기반 담기 버튼
                if not cart_clicked:
                    for sel in [
                        'input[type="image"][id*="saveBag"]',
                        'input[type="image"][id*="cart"]',
                        'input[value*="담기"]',
                        'button:has-text("담기")',
                        'button:has-text("장바구니")',
                        'a:has-text("추가")',
                        'a:has-text("담기")',
                        'span:has-text("추가")',
                    ]:
                        try:
                            btn = await page.query_selector(sel)
                            if btn:
                                await btn.click(force=True)
                                await page.wait_for_timeout(2500)
                                cart_clicked = True
                                self._progress(f"  담기 버튼 클릭 (폴백 {sel})")
                                break
                        except Exception:
                            continue

                page.remove_listener("dialog", _capture_dialog)

                if not cart_clicked:
                    return {"success": False, "stage": "cart",
                            "message": "담기 버튼 클릭 실패 - 버튼을 찾을 수 없음"}

                # ── 장바구니 담김 여부 검증 ──
                # 방법 1: alert 팝업 메시지에 성공 키워드 포함 여부
                _SUCCESS_KEYWORDS = ["담겼습니다", "담았습니다", "추가되었",
                                     "추가했", "저장되었", "완료"]
                _FAIL_KEYWORDS = ["실패", "오류", "에러", "불가", "품절",
                                  "재고", "선택"]
                dialog_success = False
                dialog_fail = False
                for msg in _dialog_messages:
                    self._progress(f"  팝업 메시지: {msg}")
                    if any(kw in msg for kw in _SUCCESS_KEYWORDS):
                        dialog_success = True
                    if any(kw in msg for kw in _FAIL_KEYWORDS):
                        dialog_fail = True

                if dialog_success and not dialog_fail:
                    self._progress(f"연동 테스트: 장바구니 담기 성공 - 팝업 확인 ({drug_name})")
                    try:
                        await self._clear_cart()
                    except Exception:
                        pass
                    return {"success": True, "stage": "done",
                            "message": "연동 정상 (팝업 검증)"}

                if dialog_fail and not dialog_success:
                    fail_msgs = "; ".join(_dialog_messages[:3])
                    return {"success": False, "stage": "cart",
                            "message": f"담기 실패 팝업: {fail_msgs}"}

                # 방법 2: 장바구니 영역에 "비어있음" 텍스트 확인
                await page.wait_for_timeout(1000)
                cart_empty_texts = ["장바구니에 담긴 제품이 없습니다", "담긴 제품이 없습니다"]
                cart_empty = False
                for txt in cart_empty_texts:
                    try:
                        el = await page.query_selector(f'text="{txt}"')
                        if el and await el.is_visible():
                            cart_empty = True
                            break
                    except Exception:
                        continue

                if cart_empty and not dialog_success:
                    return {"success": False, "stage": "cart",
                            "message": f"담기 클릭 했으나 장바구니가 비어있음 ({drug_name})"}

                # 방법 3: 팝업도 없고 빈 텍스트도 없으면 → 담기 성공으로 간주
                # (많은 사이트가 별다른 피드백 없이 장바구니에 추가됨)
                self._progress(f"연동 테스트: 장바구니 담기 성공 ({drug_name})")
                try:
                    await self._clear_cart()
                except Exception:
                    pass

                return {"success": True, "stage": "done", "message": "연동 정상 (빈검색 검증)"}

            except Exception as e:
                return {"success": False, "stage": "cart",
                        "message": f"빈 검색 테스트 오류: {e}"}

        except Exception as e:
            return {"success": False, "stage": "error", "message": str(e)}
        finally:
            await self._close()

    async def _add_item_to_cart(self, insurance_code: str, quantity: int,
                                idx: int, total: int,
                                preferred_unit: int | None = None) -> dict:
        page = self._page
        result = {"success": False, "insurance_code": insurance_code,
                  "quantity": quantity, "box_qty": 0, "pack_size": 0,
                  "drug_name": "", "message": "", "unit_options": []}

        # 검색 전 현재 URL 저장 (페이지 복구용)
        _order_url = page.url

        search = self._selectors.get("search", {})
        table = self._selectors.get("table", {})
        search_input = search.get("search_input")
        search_btn = search.get("search_btn")

        if not search_input:
            # AI Fallback: Claude로 셀렉터 재분석 시도
            self._progress(f"  검색 필드 셀렉터 없음 → Claude AI 재분석 시도...")
            try:
                from core.ai_analyzer import analyze_selectors, is_available
                if is_available() and self._page:
                    ai_result = await analyze_selectors(
                        self._page, site_url=self.url, wid=self._wid
                    )
                    if ai_result and ai_result.get("search_input"):
                        self._selectors.setdefault("search", {}).update(
                            {k: v for k, v in ai_result.items()
                             if k in ("search_input", "search_btn")}
                        )
                        if ai_result.get("cart_btn"):
                            self._selectors.setdefault("table", {})["cart_btn"] = ai_result["cart_btn"]
                        if ai_result.get("qty_input"):
                            self._selectors.setdefault("table", {})["qty_input"] = ai_result["qty_input"]
                        self._selectors["confidence"] = "provisional"
                        self._save_selectors(self._selectors)
                        # 재분석 결과로 재시도
                        search_input = ai_result["search_input"]
                        search_btn = ai_result.get("search_btn")
                        self._progress(f"  Claude AI 분석 성공 → {search_input}")
                    else:
                        result["message"] = "검색 필드 셀렉터 없음 (AI 분석 실패)"
                        return result
                else:
                    result["message"] = "검색 필드 셀렉터 없음 (Claude API 키 미설정)"
                    return result
            except Exception as e:
                result["message"] = f"검색 필드 셀렉터 없음 (AI 오류: {e})"
                return result

        # 약품명 조회 (보험코드 검색 실패 시 약품명으로 재검색용)
        from core.drug_api import get_drug_name
        drug_name_for_search = get_drug_name(insurance_code)
        if drug_name_for_search == insurance_code:
            # drug_api에서 못 찾으면 인벤토리에서 시도
            try:
                from core.inventory import load_inventory
                inv_name = load_inventory().get(insurance_code, {}).get("drug_name", "")
                if inv_name:
                    drug_name_for_search = inv_name
            except Exception:
                pass

        # 약품명에서 핵심 이름만 추출 (제형/용량 제거)
        # "타이레놀정500밀리그램" → "타이레놀", "아세젠정" → "아세젠"
        import re as _re
        short_name = _re.split(
            r'(정|캡슐|캡|시럽|액|산|환|주|크림|연고|점안|점이|패치|필름|과립'
            r'|밀리|미리|그램|mg|ML|ml|\d|[()\s])',
            drug_name_for_search, flags=_re.IGNORECASE
        )[0].strip()

        # 검색 시도: 약품명(짧은) → 보험코드 순서
        search_terms = []
        if short_name and short_name != insurance_code and len(short_name) >= 2:
            search_terms.append(short_name)
        search_terms.append(insurance_code)

        self._progress(f"  검색어 목록: {search_terms}")

        rows = []
        row_sel = table.get("result_rows", "table tbody tr")

        for term in search_terms:
            self._progress(f"  [{term}] 검색 시도 중...")
            # 검색 필드가 페이지 리로드로 사라질 수 있으므로 대기
            try:
                await page.wait_for_selector(search_input, state="visible", timeout=5000)
            except Exception:
                # 페이지 리로드 후 요소가 사라짐 → 주문 페이지 재접속
                try:
                    await page.goto(_order_url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(2000)
                    await page.wait_for_selector(search_input, state="visible", timeout=8000)
                except Exception:
                    self._progress(f"  [{term}] 검색 필드 복구 실패")
                    continue
            await page.fill(search_input, '')
            await page.wait_for_timeout(300)
            await page.fill(search_input, term)

            # 검색 실행 — 버튼 클릭 또는 Enter (더블 포스트백 방지)
            searched = False
            if search_btn:
                try:
                    await page.click(search_btn)
                    searched = True
                except Exception:
                    pass
            if not searched:
                await page.press(search_input, "Enter")

            await page.wait_for_timeout(3000)

            rows = await page.query_selector_all(row_sel)
            # 행이 있고, 실제 데이터가 있는지 확인
            valid_rows = []
            for r in rows:
                tds = await r.query_selector_all('td')
                if not tds:
                    continue
                # 실제 텍스트가 있는 셀이 3개 이상이면 유효한 행
                filled = 0
                for td in tds:
                    t = (await td.inner_text()).strip()
                    if t and len(t) > 0:
                        filled += 1
                if filled >= 3:
                    valid_rows.append(r)

            if valid_rows:
                rows = valid_rows
                self._progress(f"  [{term}] 검색 성공 ({len(rows)}행)")
                break
            self._progress(f"  [{term}] 결과 없음")
            rows = []  # 유효한 행 없으면 다음 검색어 시도

        if not rows:
            result["message"] = "검색 결과 없음"
            result["out_of_stock"] = True
            self._progress(f"  [{insurance_code}] 검색 결과 없음 ({idx}/{total})")
            return result

        # 셀렉터 캐시 없으면 첫 검색 시 테이블 구조 탐지
        if not table:
            self._progress("  테이블 구조 탐지 중...")
            table = await self._detect_result_table(insurance_code)
            self._selectors["table"] = table
            self._save_selectors(self._selectors)
            # 행 다시 조회
            row_sel = table.get("result_rows", "table tbody tr")
            rows = await page.query_selector_all(row_sel)

        # stock_col 등 누락 시 헤더 재탐지
        if "stock_col_idx" not in table and rows:
            try:
                first_table = await rows[0].evaluate_handle('el => el.closest("table")')
                headers = await first_table.query_selector_all('thead th')
                if not headers:
                    headers = await first_table.query_selector_all('tr:first-child th')
                header_texts = []
                for th in headers:
                    text = (await th.inner_text()).strip().replace("\n", " ")
                    header_texts.append(text)
                if header_texts:
                    for i, header in enumerate(header_texts):
                        header_lower = header.lower()
                        for col_type, keywords in self.HEADER_MAP.items():
                            for kw in keywords:
                                if kw.lower() in header_lower:
                                    key = f"{col_type}_col_idx"
                                    if key not in table:
                                        table[key] = i
                                    break
                    self._selectors["table"] = table
                    self._save_selectors(self._selectors)
            except Exception:
                pass

        unit_col = table.get("unit_col_idx")
        name_col = table.get("name_col_idx")
        stock_col = table.get("stock_col_idx")
        code_col = table.get("code_col_idx")
        price_col = table.get("price_col_idx")
        qty_input_sel = table.get("qty_input")
        cart_btn_sel = table.get("cart_btn")
        cart_in_row = table.get("cart_btn_in_row", False)

        # 각 행에서 candidates 수집
        candidates = []
        for row in rows:
            cells = await row.query_selector_all('td')
            if not cells:
                continue

            # 보험코드 확인 (해당 약품 행인지)
            if code_col is not None and code_col < len(cells):
                code_text = (await cells[code_col].inner_text()).strip()
                if insurance_code not in code_text:
                    continue

            # 약품명
            drug_name = ""
            if name_col is not None and name_col < len(cells):
                drug_name = (await cells[name_col].inner_text()).strip()

            # 규격
            pack_size = 0
            std_text = ""
            if unit_col is not None and unit_col < len(cells):
                std_text = (await cells[unit_col].inner_text()).strip()
                pack_size = parse_pack_size(std_text)

            # 규격 컬럼 못 찾았으면 전체 셀에서 규격 패턴 탐색
            if pack_size == 0:
                for cell in cells:
                    text = (await cell.inner_text()).strip()
                    ps = parse_pack_size(text)
                    if ps > 0:
                        pack_size = ps
                        std_text = text
                        break

            # 가격
            pack_price = 0
            if price_col is not None and price_col < len(cells):
                price_text = (await cells[price_col].inner_text()).strip()
                price_text = re.sub(r'[^\d]', '', price_text)
                pack_price = int(price_text) if price_text else 0

            # 재고 확인
            stock = 999  # 재고 컬럼 없으면 있다고 간주
            if stock_col is not None and stock_col < len(cells):
                stock_text = (await cells[stock_col].inner_text()).strip()
                stock_text = re.sub(r'[^\d]', '', stock_text)
                stock = int(stock_text) if stock_text else 0

            if pack_size > 0 and stock > 0:
                candidates.append({
                    "row": row, "pack_size": pack_size,
                    "drug_name": drug_name, "std_text": std_text,
                    "stock": stock, "pack_price": pack_price,
                })

        if not candidates:
            # 재고 컬럼이 있고 전부 재고 0이면 → 품절
            if stock_col is not None:
                drug_name = ""
                if name_col is not None and len(await rows[0].query_selector_all('td')) > name_col:
                    cells = await rows[0].query_selector_all('td')
                    drug_name = (await cells[name_col].inner_text()).strip()
                result["drug_name"] = drug_name
                result["message"] = "재고 없음"
                result["out_of_stock"] = True
                self._progress(f"  [{insurance_code}] 재고 없음 ({idx}/{total})")
                return result

            # 재고 컬럼 없으면 규격 파싱 실패 — 첫 번째 행으로 폴백
            pack_size = preferred_unit or 1
            drug_name = ""
            if name_col is not None and len(await rows[0].query_selector_all('td')) > name_col:
                cells = await rows[0].query_selector_all('td')
                drug_name = (await cells[name_col].inner_text()).strip()
            result["drug_name"] = drug_name
            result["pack_size"] = pack_size
            result["box_qty"] = max(1, math.ceil(quantity / pack_size))
            result["unit_options"] = [pack_size]
            chosen = {"row": rows[0], "pack_size": pack_size,
                      "drug_name": drug_name, "std_text": ""}
            box_qty = result["box_qty"]
        else:
            unit_options = sorted(set(c["pack_size"] for c in candidates))
            result["unit_options"] = unit_options

            chosen = choose_best_pack(candidates, quantity, preferred_unit)
            box_qty = chosen["box_qty"]
            result["drug_name"] = chosen["drug_name"]
            result["pack_size"] = chosen["pack_size"]
            result["box_qty"] = box_qty
            result["pack_price"] = chosen.get("pack_price", 0)
            result["unit_price"] = (
                chosen["pack_price"] // chosen["pack_size"]
                if chosen.get("pack_price") and chosen["pack_size"] > 0
                else 0
            )

        self._progress(
            f"  {result['drug_name'] or insurance_code} "
            f"{chosen['pack_size']}T x{box_qty} 장바구니 담는 중... ({idx}/{total})"
        )

        row_el = chosen["row"]
        cells = await row_el.query_selector_all('td')

        # 수량 입력 — 셀렉터 또는 컬럼 인덱스로
        qty_col = table.get("qty_col_idx")
        qty_filled = False

        if qty_input_sel:
            qty_el = await row_el.query_selector(qty_input_sel)
            if qty_el:
                await qty_el.click()
                await qty_el.fill(str(box_qty))
                qty_filled = True

        if not qty_filled and qty_col is not None and qty_col < len(cells):
            # 수량 컬럼 안의 input 찾기
            qty_el = await cells[qty_col].query_selector('input')
            if qty_el:
                await qty_el.click()
                await qty_el.fill(str(box_qty))
                qty_filled = True

        if qty_filled:
            await page.wait_for_timeout(300)

        # 행 체크박스 — 페이지 레벨 담기 버튼일 때 필수
        if not cart_in_row:
            chk_sel = table.get("row_checkbox")
            if chk_sel:
                chk = await row_el.query_selector(chk_sel)
                if chk:
                    checked = await chk.is_checked()
                    if not checked:
                        await chk.click(force=True)
                        await page.wait_for_timeout(300)
            else:
                # 체크박스 셀렉터 미저장 — 자동 탐지
                for sel in ['input[type="checkbox"]', 'input[name^="chk"]']:
                    chk = await row_el.query_selector(sel)
                    if chk:
                        checked = await chk.is_checked()
                        if not checked:
                            await chk.click(force=True)
                            await page.wait_for_timeout(300)
                        break

        # 담기/추가 버튼 — 셀렉터 또는 컬럼 인덱스로
        cart_col = table.get("cart_col_idx")
        cart_clicked = False

        if cart_btn_sel:
            if cart_in_row:
                btn = await row_el.query_selector(cart_btn_sel)
            else:
                btn = await page.query_selector(cart_btn_sel)
            if btn:
                await btn.click(force=True)
                cart_clicked = True

        if not cart_clicked and cart_col is not None and cart_col < len(cells):
            # 해당 컬럼 안의 버튼/링크 찾기
            btn = await cells[cart_col].query_selector('button, a, input[type="button"]')
            if btn:
                await btn.click()
                cart_clicked = True

        if not cart_clicked:
            # 행 전체에서 추가/담기 버튼 마지막 시도
            for sel in ['button:has-text("추가")', 'button:has-text("담기")',
                        'a:has-text("추가")', 'a:has-text("담기")']:
                btn = await row_el.query_selector(sel)
                if btn:
                    await btn.click()
                    cart_clicked = True
                    break

        if cart_clicked:
            await page.wait_for_timeout(2000)

            # 페이지 레벨 담기 후 체크박스 해제 (다음 약품 중복 담기 방지)
            if not cart_in_row:
                try:
                    chk_sel = table.get("row_checkbox", 'input[type="checkbox"]')
                    chk = await row_el.query_selector(chk_sel)
                    if chk and await chk.is_checked():
                        await chk.click(force=True)
                        await page.wait_for_timeout(200)
                except Exception:
                    pass

        # 팝업 닫기 (공통 패턴)
        for popup_sel in [
            '.layerpopup .btn_basic',
            '.q-dialog button:has-text("확인")',
            'button:has-text("확인")',
            '.modal button:has-text("확인")',
        ]:
            try:
                popup = await page.query_selector(popup_sel)
                if popup and await popup.is_visible():
                    await popup.click()
                    await page.wait_for_timeout(500)
                    break
            except Exception:
                pass

        await self._screenshot(
            f"generic_{self._wid}_cart_{idx:02d}_{insurance_code}.png"
        )

        result["success"] = cart_clicked
        if cart_clicked:
            result["message"] = f"{chosen.get('std_text', '')} x{box_qty} 담기 완료"
        else:
            result["message"] = "담기 버튼을 찾을 수 없음"
        return result

    async def _confirm_order(self) -> None:
        confirm = self._selectors.get("confirm", {})
        btn_sel = confirm.get("confirm_btn")

        if not btn_sel:
            # 캐시 없으면 탐지
            detected = await self._detect_confirm()
            btn_sel = detected.get("confirm_btn")
            if detected:
                self._selectors["confirm"] = detected
                self._save_selectors(self._selectors)

        if btn_sel:
            btn = self._page.locator(btn_sel)
            await btn.click(force=True)
            await self._page.wait_for_timeout(5000)
        else:
            self._progress("주문확정 버튼을 찾을 수 없음")
            raise RuntimeError("주문확정 버튼 탐지 실패")

    # ────── 자동 재분석: 주문 중 전체 실패 시 셀렉터 리셋 후 1회 재시도 ──────

    async def place_order_async(
        self, items: list[dict], headless: bool = True, dry_run: bool = True
    ) -> dict:
        result = await super().place_order_async(items, headless=headless, dry_run=dry_run)

        # 전체 실패 + 실패 사유가 셀렉터 관련일 때만 재분석
        if result["success"]:
            return result

        results = result.get("results", [])
        success_count = sum(1 for r in results if r.get("success"))
        if success_count > 0:
            return result  # 일부 성공 → 셀렉터 문제 아님

        # 품절/재고 관련 실패면 재분석 불필요
        all_oos = all(r.get("out_of_stock") for r in results if not r.get("success"))
        if all_oos and results:
            return result

        # 사유 분석: 셀렉터/구조 관련 실패인지 판별
        fail_msgs = " ".join(r.get("message", "") for r in results)
        selector_issue = any(kw in fail_msgs for kw in [
            "셀렉터", "버튼을 찾을 수 없음",
            "장바구니에 추가되지 않음", "담기 버튼",
        ])
        if not selector_issue:
            return result  # 품절/재고 문제 → 재분석 불필요

        self._progress("전체 실패 → 셀렉터 자동 재분석 시도 (1회)")

        try:
            # 셀렉터 초기화 후 재분석
            from core.selector_store import delete_selectors
            delete_selectors(self._wid)
            self._selectors = {}

            analyzer = GenericWholesaler({
                "name": self.name, "url": self.url,
                "id": self.user_id, "pw": self.password,
                "_wid": self._wid,
            })
            await analyzer.analyze_site(headless=headless)

            # 새 셀렉터로 재시도
            self._selectors = self._load_selectors()
            retry_result = await super().place_order_async(
                items, headless=headless, dry_run=dry_run
            )

            if retry_result["success"]:
                self._progress("자동 재분석 후 주문 성공!")
            else:
                self._progress("자동 재분석 후에도 실패")

            return retry_result

        except Exception as e:
            self._progress(f"자동 재분석 오류: {e}")
            return result

    # ────── 이력 검색 (history_config 기반) ──────

    async def _ensure_history_config(self, headless: bool = True):
        """이력 검색 설정이 없으면 로그인 → 이력 페이지 탐지 → 저장한다."""
        from core.history_config import get_config, save_config

        cfg = get_config(self._wid)
        if cfg and cfg.get("history_url"):
            return  # 이미 있음

        self._progress(f"{self.name} 이력 페이지 탐지 중...")
        ok = await self.login_async(headless=headless)
        if not ok:
            self._progress(f"{self.name} 로그인 실패 - 이력 탐지 건너뜀")
            return

        detected = await self._detect_history_page()
        if detected and detected.get("history_url"):
            detected["name"] = self.name
            detected["base_url"] = self.url
            detected["login"] = self._selectors.get("login", {})
            save_config(self._wid, detected, upload=True)
            self._progress(f"{self.name} 이력 페이지 탐지 완료: {detected.get('history_page_name', '')}")
        else:
            self._progress(f"{self.name} 이력 페이지 없음")

        try:
            await self._close()
        except Exception:
            pass

    async def _set_date_range_5years(self, page, search: dict):
        """이력 검색 기간을 최소 5년 전으로 설정한다.

        1) config에 date_from 셀렉터가 있으면 직접 값 설정
        2) 기간 버튼(5년/3년/1년 등)이 있으면 가장 긴 것 클릭
        3) 둘 다 없으면 페이지의 날짜 input을 자동 탐지해서 설정
        """
        from datetime import datetime, timedelta
        five_years_ago = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y.%m.%d")

        # 1) config에 명시된 date_from 셀렉터
        date_from_sel = search.get("date_from")
        if date_from_sel:
            try:
                await page.evaluate(
                    f'document.querySelector("{date_from_sel}").value = "{five_years_ago}"'
                )
                return
            except Exception:
                pass

        # 2) 기간 버튼 — 긴 순서대로 시도
        period_btn = search.get("period_btn")
        if period_btn:
            try:
                btn = page.locator(period_btn)
                if await btn.count() > 0:
                    await btn.first.click(force=True)
                    await page.wait_for_timeout(500)
                    return
            except Exception:
                pass

        for label in ["5년", "3년", "전체", "1년", "12개월"]:
            try:
                btn = page.locator(f'button:has-text("{label}")').first
                if await btn.count() > 0:
                    await btn.click(force=True)
                    await page.wait_for_timeout(500)
                    return
            except Exception:
                continue

        # 3) 날짜 input 자동 탐지 — id/name에 date, from, start 포함
        try:
            date_input = await page.evaluate('''() => {
                const inputs = document.querySelectorAll('input[type="text"], input[type="date"]');
                for (const inp of inputs) {
                    const key = (inp.id + inp.name).toLowerCase();
                    if ((key.includes('date') || key.includes('from') || key.includes('start'))
                        && !key.includes('to') && !key.includes('end') && !key.includes('_t')) {
                        return inp.id ? '#' + inp.id : (inp.name ? `input[name="${inp.name}"]` : null);
                    }
                }
                return null;
            }''')
            if date_input:
                await page.evaluate(
                    f'document.querySelector(\'{date_input}\').value = "{five_years_ago}"'
                )
        except Exception:
            pass

    async def search_history_async(self, drug_name: str,
                                   lot_number: str = "",
                                   headless: bool = True) -> list[dict]:
        """history_config 기반으로 도매상 사이트에서 입고이력을 검색한다.

        config가 없으면 로그인 후 이력 페이지를 자동 탐지하고 저장한 뒤 검색한다.
        """
        from core.history_config import get_config, save_config

        cfg = get_config(self._wid)

        results = []
        try:
            self._progress(f"{self.name} 입고이력 검색: {drug_name}")
            ok = await self.login_async(headless=headless)
            if not ok:
                self._progress(f"{self.name} 로그인 실패")
                return results

            page = self._page

            # history_config 없으면 자동 탐지
            if not cfg or not cfg.get("history_url"):
                self._progress(f"{self.name} 이력 페이지 자동 탐지 중...")
                detected = await self._detect_history_page()
                if not detected or not detected.get("history_url"):
                    self._progress(f"{self.name} 이력 페이지 없음 - 건너뜀")
                    return results
                # 탐지 성공 → 저장
                detected["name"] = self.name
                detected["base_url"] = self.url
                detected["login"] = self._selectors.get("login", {})
                save_config(self._wid, detected, upload=True)
                cfg = detected
                self._progress(f"{self.name} 이력 페이지 탐지 완료: {cfg.get('history_page_name', '')}")

            from urllib.parse import urljoin

            # 이력 페이지 이동
            history_url = cfg["history_url"]
            base_url = cfg.get("base_url", self.url)
            if not history_url.startswith("http"):
                history_url = urljoin(base_url, history_url)
            await page.goto(history_url, wait_until="domcontentloaded",
                            timeout=15000)
            await page.wait_for_timeout(2000)

            # 팝업 닫기
            await self._close_popup()

            search = cfg.get("search", {})

            # 기간 설정: 항상 최소 5년 전부터 검색
            await self._set_date_range_5years(page, search)

            # 약품명 입력
            keyword_sel = search.get("keyword")
            if keyword_sel:
                try:
                    await page.fill(keyword_sel, drug_name)
                except Exception:
                    self._progress(f"  검색어 입력 실패: {keyword_sel}")
                    return results

            # 로트번호 입력 (필드 있으면)
            if lot_number:
                lot_sel = search.get("lot_number")
                if lot_sel:
                    try:
                        await page.fill(lot_sel, lot_number)
                    except Exception:
                        pass

            # 검색 실행: JS 함수 직접 호출 또는 버튼 클릭
            search_fn = search.get("search_fn")
            search_btn = search.get("search_btn")
            if search_fn:
                try:
                    await page.evaluate(search_fn)
                    await page.wait_for_timeout(4000)
                except Exception:
                    if search_btn:
                        btn = page.locator(search_btn).first
                        await btn.click(force=True)
                        await page.wait_for_timeout(4000)
            elif search_btn:
                try:
                    btn = page.locator(search_btn).first
                    await btn.click(force=True)
                    await page.wait_for_timeout(4000)
                except Exception:
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(4000)

            # 테이블 파싱
            results = await self._parse_history_table(page, cfg, drug_name,
                                                       lot_number)

        except Exception as e:
            self._progress(f"{self.name} 이력 검색 오류: {e}")
        finally:
            try:
                await self._close()
            except Exception:
                pass

        return results

    async def _parse_history_table(self, page, cfg: dict, drug_name: str,
                                   lot_number: str = "") -> list[dict]:
        """이력 테이블을 파싱하여 결과를 반환한다."""
        results = []
        table_cfg = cfg.get("table", {})
        table_idx = table_cfg.get("index", 0)
        columns = dict(table_cfg.get("columns", {}))

        tables = page.locator("table")
        table_count = await tables.count()

        # table_after_search: 검색 전에는 테이블이 없던 사이트
        # 검색 후 나타난 테이블에서 동적으로 컬럼 매핑
        if table_count == 0:
            self._progress(f"  테이블 없음 (발견: 0개)")
            return results

        if table_idx >= table_count:
            table_idx = 0  # 폴백: 첫 번째 테이블 사용

        target_table = tables.nth(table_idx)

        # 컬럼 매핑이 없으면 헤더에서 동적 탐지
        if not columns:
            try:
                headers = target_table.locator("th")
                h_count = await headers.count()
                for idx in range(h_count):
                    ht = (await headers.nth(idx).inner_text()).strip().lower()
                    if any(k in ht for k in ["제품", "상품", "품명", "약품"]):
                        columns.setdefault("drug_name", idx)
                    elif any(k in ht for k in ["주문일", "입고일", "출고일",
                                                "배송일", "거래일", "납품일", "날짜"]):
                        columns.setdefault("date", idx)
                    elif any(k in ht for k in ["수량", "납입"]):
                        columns.setdefault("qty", idx)
                    elif any(k in ht for k in ["제조번호", "로트", "lot"]):
                        columns.setdefault("lot_number", idx)
                    elif any(k in ht for k in ["유효기한", "유효", "만료"]):
                        columns.setdefault("expiry", idx)
                if columns:
                    self._progress(f"  동적 컬럼 매핑: {columns}")
            except Exception:
                pass
        rows = target_table.locator("tbody tr")
        row_count = await rows.count()
        self._progress(f"{self.name} 검색 결과: {row_count}건")

        search_keywords = [k.strip() for k in drug_name.split() if k.strip()]

        for i in range(min(row_count, 50)):
            try:
                row = rows.nth(i)
                cells = row.locator("td")
                cell_count = await cells.count()
                if cell_count < 3:
                    continue

                drug = ""
                order_date = ""
                qty = 0
                lot = ""
                expiry = ""

                if "drug_name" in columns and columns["drug_name"] < cell_count:
                    drug = (await cells.nth(columns["drug_name"]).inner_text()).strip()
                if "date" in columns and columns["date"] < cell_count:
                    order_date = (await cells.nth(columns["date"]).inner_text()).strip()
                if "qty" in columns and columns["qty"] < cell_count:
                    qty_text = (await cells.nth(columns["qty"]).inner_text()).strip()
                    nums = re.sub(r'[^\d]', '', qty_text)
                    qty = int(nums) if nums else 0
                if "lot_number" in columns and columns["lot_number"] < cell_count:
                    lot = (await cells.nth(columns["lot_number"]).inner_text()).strip()
                if "expiry" in columns and columns["expiry"] < cell_count:
                    expiry = (await cells.nth(columns["expiry"]).inner_text()).strip()

                if not drug or "없습니다" in drug or "조회" in drug:
                    continue

                drug_lower = drug.lower()
                if not all(kw.lower() in drug_lower for kw in search_keywords):
                    continue

                matched = bool(lot_number and lot and lot_number in lot)

                results.append({
                    "drug_name": drug,
                    "order_date": order_date,
                    "qty": qty,
                    "lot_number": lot,
                    "expiry": expiry,
                    "wholesaler_id": self._wid,
                    "wholesaler_name": self.name,
                    "source": self.name,
                    "matched": matched,
                })
            except Exception:
                continue

        return results
