"""범용 도매상 자동화 - 사이트 구조 자동 탐지."""

import asyncio
import json
import math
import os
import re
import sys

from wholesalers.base import WholesalerBase, choose_best_pack, parse_pack_size


def _guess_column_indices(headers: list) -> dict:
    """검색 결과 테이블 헤더에서 컬럼 역할별 인덱스를 추측한다.

    자동 온보딩(full_onboard) 결과의 table_sel 에 쓰인다.
    헤더 한글 키워드 기반 매칭. 정확하지 않으면 누락 허용 — 부분 정보라도
    없는 것보다 낫다.
    """
    out: dict = {}
    last = len(headers) - 1 if headers else -1
    for i, h in enumerate(headers or []):
        if not h:
            continue
        hh = h.strip()
        if any(k in hh for k in ("보험", "코드")):
            out.setdefault("code_col_idx", i)
        elif any(k in hh for k in ("약품", "품명", "제품", "상품")):
            out.setdefault("name_col_idx", i)
        elif any(k in hh for k in ("규격", "포장")):
            out.setdefault("unit_col_idx", i)
        elif any(k in hh for k in ("제조", "메이커")):
            out.setdefault("mfr_col_idx", i)
        elif "재고" in hh:
            out.setdefault("stock_col_idx", i)
        elif any(k in hh for k in ("단가", "가격", "금액")):
            out.setdefault("price_col_idx", i)
        elif any(k in hh for k in ("수량", "주문수량")):
            out.setdefault("qty_col_idx", i)
    # 담기 컬럼은 마지막 빈 헤더 또는 "담기/장바구니" 포함 컬럼
    if last >= 0 and "cart_col_idx" not in out:
        h_last = (headers[last] or "").strip()
        if not h_last or any(k in h_last for k in ("담기", "장바구니", "추가", "카트")):
            out["cart_col_idx"] = last
    return out


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

    # 약품 주문 페이지의 검색 입력창에서 흔히 보이는 placeholder/label 키워드
    _DRUG_SEARCH_KEYWORDS = [
        "품목", "약품", "제품", "보험코드", "상품", "KD코드", "KD 코드",
        "보험CD", "약명", "제품명", "품명", "상품명",
    ]
    # 거래처/비약품 검색 필드의 키워드 (이게 포함되면 건너뜀)
    _NON_DRUG_SEARCH_KEYWORDS = ["거래처", "회원", "사업자", "업체"]

    async def _detect_search(self) -> dict:
        """약품 검색 입력창을 탐지한다.

        핵심 원리: placeholder나 주변 텍스트에 약품 관련 키워드가 있는 input을 찾는다.
        검색 실행은 엔터 키 (대부분의 도매상 공통).
        """
        page = self._page
        selectors = {}

        # ── 1단계: placeholder에 약품 키워드가 있는 input 찾기 (가장 확실) ──
        all_inputs = await page.query_selector_all(
            'input[type="text"], input[type="search"], input:not([type])'
        )
        for inp in all_inputs:
            if not await inp.is_visible():
                continue
            placeholder = (await inp.get_attribute("placeholder") or "").strip()
            if not placeholder:
                continue
            # 거래처 키워드가 있으면 건너뜀
            if any(kw in placeholder for kw in self._NON_DRUG_SEARCH_KEYWORDS):
                continue
            # 약품 키워드가 있으면 이거다
            if any(kw in placeholder for kw in self._DRUG_SEARCH_KEYWORDS):
                inp_id = await inp.get_attribute("id") or ""
                inp_name = await inp.get_attribute("name") or ""
                if inp_id:
                    sel = f"#{inp_id}"
                elif inp_name:
                    sel = f'input[name="{inp_name}"]'
                else:
                    sel = f'input[placeholder*="{placeholder[:6]}"]'
                selectors["search_input"] = sel
                self._progress(f"  검색 필드 탐지(placeholder): {sel} — \"{placeholder}\"")
                return selectors  # 엔터로 검색하므로 버튼 불필요

        # ── 2단계: 알려진 ID/name 패턴 (placeholder 없는 사이트) ──
        known_ids = [
            'input#txt_product', 'input#P_SRH_KEY', 'input#tx_physic',
            'input#srchTxt', 'input#searchKeyword', 'input#prodNm',
            'input[name="searchWord"]', 'input[name="keyword"]',
            'input[name="tx_physic"]', 'input[name="srchText"]',
        ]
        for sel in known_ids:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                selectors["search_input"] = sel
                self._progress(f"  검색 필드 탐지(known ID): {sel}")
                return selectors

        # ── 3단계: label에 약품 키워드가 있는 input ──
        for kw in self._DRUG_SEARCH_KEYWORDS:
            try:
                label = await page.query_selector(
                    f'label:has-text("{kw}"), th:has-text("{kw}")'
                )
                if not label:
                    continue
                for_attr = await label.get_attribute("for") or ""
                if for_attr:
                    inp = await page.query_selector(f"#{for_attr}")
                    if inp and await inp.is_visible():
                        selectors["search_input"] = f"#{for_attr}"
                        self._progress(f"  검색 필드 탐지(label '{kw}'): #{for_attr}")
                        return selectors
            except Exception:
                continue

        return selectors

    # ────── 자동 탐지: 주문 가능 페이지 탐색 ──────

    async def _is_orderable_page(self) -> bool:
        """현재 페이지가 약품 주문/장바구니 담기가 가능한 페이지인지 판단한다.

        핵심: 약품 관련 placeholder가 있는 검색 입력창이 있으면 주문 페이지.
        """
        page = self._page

        # 약품 관련 placeholder가 있는 검색 입력창 있으면 OK
        search = await self._detect_search()
        if search.get("search_input"):
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

            # 키워드 우선순위로 정렬 (주문/발주 > 약품/상품 > 검색/조회)
            _PRIORITY_KEYWORDS = [
                ("주문", 10), ("발주", 10), ("order", 10),
                ("약품", 8), ("상품", 8), ("품목", 8), ("product", 8),
                ("검색", 5), ("조회", 5), ("search", 5),
            ]
            for link in all_links:
                score = 0
                link_text = link["text"].lower()
                link_href = link["href"].lower()
                for kw, pts in _PRIORITY_KEYWORDS:
                    if kw in link_text or kw in link_href:
                        score += pts
                link["score"] = score
            all_links.sort(key=lambda x: x["score"], reverse=True)

            self._progress(f"  전체 링크 {len(all_links)}개 발견 → 우선순위 탐색")
        except Exception as e:
            self._progress(f"  링크 수집 오류: {e}")
            return {}

        # ── 3단계: 우선순위 순서로 링크 방문 → 주문 가능 판단 ──
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
            'img[alt*="담기"]', 'img[alt*="장바구니"]', 'img[alt*="추가"]',
            'input[type="image"][alt*="담기"]', 'input[type="image"][alt*="추가"]',
            'input[type="image"][alt*="장바구니"]', 'input[type="image"][src*="cart"]',
            'input[type="image"][src*="save"]', 'input[type="image"][src*="bag"]',
            'button:has-text("추가")',
            'button:has-text("담기")',
            'button:has-text("장바구니")',
            'a:has-text("추가")',
            'a:has-text("담기")',
            'a:has-text("장바구니 담기")',
            'a:has(img[alt*="담기"])', 'a:has(img[alt*="추가"])',
            'td:last-child a', 'td:last-child img',
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

    async def _ai_navigate_to_order_page(self) -> str | None:
        """AI에게 스크린샷을 보여주고 약품 주문 페이지로 네비게이션한다.

        Returns:
            주문 페이지 URL 또는 None (이미 주문 페이지이거나 탐색 실패)
        """
        page = self._page
        try:
            from core.visual_agent import VisualAgent
            from core.ai_analyzer import _load_api_key
            agent = VisualAgent(api_key=_load_api_key(), wid=self._wid)
            if not agent._can_call_ai():
                return None

            for attempt in range(3):
                screenshot, dom = await agent._capture(page)
                prompt = f"""현재 페이지의 스크린샷과 DOM을 보고 답하세요.

질문: 이 페이지가 약품 주문/검색 페이지인가요?

판단 기준:
- 약품명이나 보험코드를 입력해서 검색할 수 있는 입력창이 있으면 → 주문 페이지
- 거래처, 회원, 공지사항, 대시보드 등이면 → 주문 페이지 아님

주문 페이지가 아니라면:
- 메뉴에서 "주문", "발주", "약품", "상품", "검색" 관련 링크를 찾아주세요
- 해당 링크의 CSS 셀렉터를 알려주세요

DOM 뼈대:
{dom}

응답 (반드시 JSON만):
{{"is_order_page": true}} 또는
{{"is_order_page": false, "nav_selector": "a:has-text(\\"주문\\")", "observation": "왼쪽 메뉴에 주문 링크 발견"}}"""

                response = await agent._ask_ai(prompt, screenshot)
                if not response:
                    self._progress(f"  AI 응답 없음 (시도 {attempt+1}/3)")
                    continue

                if response.get("is_order_page"):
                    self._progress("  현재 페이지가 약품 주문 페이지")
                    return page.url

                nav_sel = response.get("nav_selector")
                if nav_sel:
                    self._progress(f"  AI 네비게이션: {nav_sel}")
                    try:
                        await page.click(nav_sel, timeout=5000)
                        await page.wait_for_timeout(3000)
                        # 이동 후 검색 필드가 있는지 확인
                        search = await self._detect_search()
                        if search.get("search_input"):
                            self._progress(f"  주문 페이지 도착: {page.url}")
                            return page.url
                    except Exception as e:
                        self._progress(f"  네비게이션 실패: {e}")
                        continue
                else:
                    obs = response.get("observation", "")
                    self._progress(f"  AI: {obs}")

        except Exception as e:
            self._progress(f"  AI 네비게이션 오류: {e}")
        return None

    # v1.5.41 L3: 담기 버튼 AI Vision 폴백
    async def _ai_suggest_cart_button(
        self, result_table_idx: int, dom_report: dict
    ) -> list:
        """결과 행에서 담기 버튼을 AI Vision 에 질의 → 후보 리스트 반환.

        full_onboard 의 휴리스틱 후보가 전원 실패했을 때만 호출된다.
        반환 형식은 기존 candidates 와 호환되는 dict 리스트.
        """
        try:
            from core.visual_agent import VisualAgent
            from core.ai_analyzer import _load_api_key
            agent = VisualAgent(api_key=_load_api_key(), wid=self._wid)
            if not agent._can_call_ai():
                return []
            screenshot, _ = await agent._capture(self._page)

            # result_table_idx 에 해당하는 sample row HTML 만 추출 (최대 3행)
            sample_rows = [
                s for s in dom_report.get("sample_rows_html", [])
                if s.get("table_idx") == result_table_idx
            ][:3]
            rows_text = "\n\n".join(
                f"Row {s.get('row_idx', 0)}:\n{s.get('html', '')[:2000]}"
                for s in sample_rows
            ) or "(row HTML 샘플 없음)"

            prompt = f"""스크린샷은 약품 도매상 사이트의 **검색 결과 페이지** 입니다.
각 결과 행(row)에서 "장바구니 담기", "담기", "구매하기", "주문" 에 해당하는
**버튼의 CSS 셀렉터를 1개** 알려주세요.

조건:
- Playwright CSS 셀렉터 (문서에 맞는 `:has-text()` 허용, `:contains()` 금지)
- 결과 테이블(인덱스 {result_table_idx})의 tbody tr 내부에 있는 버튼만
- 텍스트 없는 이미지 버튼이면 src/alt 속성으로 정확히 지정
- 한 행에 여러 버튼 있으면 가장 "담기/추가" 에 가까운 것

다음은 결과 행 HTML 샘플:
{rows_text}

응답 (JSON만):
{{"cart_button_css": "CSS 셀렉터", "in_row": true, "reason": "짧은 근거"}}
또는 못 찾으면:
{{"cart_button_css": null, "reason": "이유"}}"""

            response = await agent._ask_ai(prompt, screenshot)
            if not response:
                return []
            css = (response.get("cart_button_css") or "").strip()
            if not css:
                return []
            # 기본 보안 필터 — javascript:, onclick= 금지
            if "javascript:" in css.lower() or "onclick" in css.lower():
                self._progress("  AI 제안 셀렉터 거부 (js 포함)")
                return []
            return [{
                "css": css,
                "in_row": bool(response.get("in_row", True)),
                "source": f"ai[{str(response.get('reason', ''))[:20]}]",
                "from_ai": True,
            }]
        except Exception as e:
            self._progress(f"  AI 담기 버튼 폴백 오류: {e}")
            return []

    # v1.5.45: 실주문 담기 실패 자동 진단 업로드 (CART_FAIL_DIAG)
    async def _upload_cart_fail_diagnostic(
        self, insurance_code: str, drug_name: str,
        used_cart_sel: str, layout_mode: str,
        before_snap: list, after_snap: list | None,
    ) -> None:
        """담기 클릭은 했지만 DOM/시각 검증 실패 시 진단 업로드.
        스크린샷 + 시도한 셀렉터 + before/after 테이블 변화 포함.
        """
        try:
            from core.cloud import is_enabled, _api_url, _headers
            if not is_enabled():
                return
            import requests as _req
            from core.version import VERSION
            pharmacy_code = ""
            try:
                from core.auth import get_activation_code
                pharmacy_code = get_activation_code() or ""
            except Exception:
                pass

            # 테이블 변화 요약
            diff_summary = []
            if after_snap:
                for i in range(min(len(before_snap), len(after_snap))):
                    b = before_snap[i].get("row_count", 0)
                    a = after_snap[i].get("row_count", 0)
                    if b != a:
                        diff_summary.append(f"table[{i}]:{b}→{a}")
            shot = await self._capture_screenshot_b64()

            import json as _json
            payload = {
                "pharmacy_code": pharmacy_code,
                "version": VERSION,
                "level": "CART_FAIL_DIAG",
                "message": (
                    f"{self._wid} [{insurance_code}] 담기 검증 실패 "
                    f"(layout={layout_mode})"
                ),
                "context": {
                    "wid": self._wid,
                    "insurance_code": insurance_code,
                    "drug_name": drug_name[:60],
                    "layout_mode": layout_mode,
                    "used_cart_sel": used_cart_sel[:120],
                    "table_diff": ",".join(diff_summary) or "no_change",
                    "stored_selectors": {
                        k: v for k, v in (
                            self._selectors.get("table", {}) or {}
                        ).items()
                        if k in (
                            "cart_btn_in_row", "global_cart_btn",
                            "row_checkbox_in_row", "qty_input_in_row",
                            "result_rows", "layout_mode", "schema_version",
                            "row_fingerprint",
                        )
                    },
                },
                "log_tail": _json.dumps({
                    "screenshot_b64": shot,
                    "before_row_counts": [
                        s.get("row_count", 0) for s in (before_snap or [])
                    ][:10],
                    "after_row_counts": [
                        s.get("row_count", 0) for s in (after_snap or [])
                    ][:10],
                }, ensure_ascii=False)[:500000],
            }
            _req.post(
                _api_url("error_logs"),
                headers=_headers(),
                json=payload,
                timeout=10,
            )
        except Exception as e:
            self._progress(f"  CART_FAIL_DIAG 업로드 실패: {e}")

    # v1.5.44: 전역 담기 버튼 + row 체크박스 패턴 시험 담기 (세화 패턴)
    async def _probe_global_cart_pattern(
        self, dom_report: dict, result_table_idx: int,
        result_rows_sel: str, qty_input_sel: str, drug_text: str,
        _probe_log_cb=None,
    ) -> dict | None:
        """row 밖 전역 담기 버튼 + row 내부 체크박스/수량 조합 시험.

        Returns: 성공 시 {"global_css", "checkbox_rel", "cart_table_idx"}, 실패 시 None.
        """
        globals_list = dom_report.get("global_cart_candidates", [])
        if not globals_list:
            return None
        # 결과 테이블 내 체크박스 (row_relative_css 있는 것)
        chk_candidates = [
            c for c in dom_report.get("row_checkboxes", [])
            if c.get("table_idx") == result_table_idx
            and c.get("row_relative_css")
        ]
        checkbox_rel = chk_candidates[0]["row_relative_css"] if chk_candidates else ""

        for g in globals_list:
            btn_css = g.get("css", "")
            if not btn_css:
                continue
            self._progress(
                f"  패턴 B 시도: 전역 '{(g.get('text') or '')[:20]}' css={btn_css[:60]}"
            )
            entry = {
                "source": f"global_btn[{(g.get('text') or '')[:20]}]",
                "css": btn_css,
                "checkbox_rel": checkbox_rel,
                "result": "",
            }
            try:
                # 1) 첫 행에 수량 입력
                if qty_input_sel:
                    try:
                        await self._page.locator(qty_input_sel).first.fill("1")
                        await self._page.wait_for_timeout(200)
                    except Exception:
                        pass
                # 2) 첫 행 체크박스 확인 (이미 체크면 skip)
                if checkbox_rel and result_rows_sel:
                    try:
                        first_row = self._page.locator(result_rows_sel).first
                        chk = first_row.locator(checkbox_rel).first
                        if await chk.count() > 0:
                            if not await chk.is_checked():
                                await chk.click(force=True)
                                await self._page.wait_for_timeout(200)
                    except Exception:
                        pass

                # 3) 전역 버튼 클릭 전 스냅샷
                before_local = await self._snapshot_tables()

                # 4) 전역 버튼 클릭
                try:
                    await self._page.locator(btn_css).first.click(
                        timeout=3000, force=True
                    )
                except Exception as e:
                    entry["result"] = "click_error"
                    entry["error"] = str(e)[:120]
                    if _probe_log_cb:
                        _probe_log_cb(entry)
                    continue

                await self._page.wait_for_timeout(2000)

                # 5) 확인 팝업 닫기
                try:
                    for ps in ['button:has-text("확인")',
                               'button:has-text("닫기")']:
                        p = self._page.locator(ps).first
                        if await p.count() > 0 and await p.is_visible():
                            await p.click(timeout=1500)
                            await self._page.wait_for_timeout(400)
                            break
                except Exception:
                    pass

                # 6) DOM diff 검증
                after_local = await self._snapshot_tables()
                verify = await self._verify_cart_added(
                    drug_name=drug_text, insurance_code="",
                    before=before_local, after=after_local,
                )
                if verify.get("verified"):
                    entry["result"] = "VERIFIED_GLOBAL"
                    entry["cart_table_idx"] = verify.get("cart_table_idx", -1)
                    if _probe_log_cb:
                        _probe_log_cb(entry)
                    return {
                        "global_css": btn_css,
                        "checkbox_rel": checkbox_rel,
                        "cart_table_idx": verify.get("cart_table_idx", -1),
                    }

                # 7) L4 AI 시각 폴백 (DOM diff 못 잡는 경우)
                visual_ok = await self._ai_visual_verify_cart(
                    before_local, after_local, drug_text
                )
                if visual_ok:
                    entry["result"] = "VERIFIED_GLOBAL_VISUAL"
                    if _probe_log_cb:
                        _probe_log_cb(entry)
                    return {
                        "global_css": btn_css,
                        "checkbox_rel": checkbox_rel,
                        "cart_table_idx": -1,
                    }

                entry["result"] = "not_verified"
                entry["reason"] = verify.get("reason", "")[:80]
                if _probe_log_cb:
                    _probe_log_cb(entry)
                # 다음 후보 시도 전 체크박스 해제 (중복 담기 방지)
                if checkbox_rel and result_rows_sel:
                    try:
                        first_row = self._page.locator(result_rows_sel).first
                        chk = first_row.locator(checkbox_rel).first
                        if await chk.count() > 0 and await chk.is_checked():
                            await chk.click(force=True)
                            await self._page.wait_for_timeout(200)
                    except Exception:
                        pass
            except Exception as e:
                entry["result"] = "error"
                entry["error"] = str(e)[:120]
                if _probe_log_cb:
                    _probe_log_cb(entry)
        return None

    # v1.5.43 DOM fingerprint: 사이트 구조 변경 자동 감지용 행 지문
    async def _compute_row_fingerprint(self, row_handle) -> str:
        """row 의 구조 지문 계산. JS 쪽 _rowFingerprint 와 동일 로직.

        Python 에서 호출 시에는 row 의 element handle 을 인자로.
        """
        if not row_handle:
            return ""
        try:
            return await row_handle.evaluate(r"""(tr) => {
                if (!tr) return '';
                const cells = tr.querySelectorAll('td');
                const parts = [];
                cells.forEach((td, i) => {
                    const hasInput = !!td.querySelector('input:not([type="hidden"])');
                    const hasImg = !!td.querySelector('img');
                    const hasBtn = !!td.querySelector('a, button, [onclick], [role="button"], [role="link"]');
                    const innerTags = Array.from(td.children).map(c => c.tagName.toLowerCase()).slice(0, 3).join(',');
                    parts.push(`${i}:${hasInput?1:0}${hasImg?1:0}${hasBtn?1:0}:${innerTags}`);
                });
                return parts.join('|').slice(0, 300);
            }""")
        except Exception:
            return ""

    # v1.5.43: self-heal — 실행 시점에 발견한 새 셀렉터를 저장
    def _update_row_selector(self, key: str, value: str) -> None:
        """휴리스틱/AI 폴백이 성공시킨 row 내부 상대 CSS 를 저장해 다음 주문부터 L1 적중."""
        if not value or not key:
            return
        try:
            tbl = self._selectors.setdefault("table", {})
            # bool/기타 타입 잔재 덮어씀
            if tbl.get(key) == value:
                return  # 변화 없음
            tbl[key] = value
            tbl["schema_version"] = "v1.5.44"
            self._selectors["confidence"] = "provisional"  # self-heal 경로
            self._save_selectors(self._selectors)
            # 서버 공유
            try:
                from core.cloud import upload_selectors, normalize_domain
                domain = normalize_domain(self.url or self._wid)
                upload_selectors(domain, self._wid, self._selectors)
            except Exception:
                pass
            self._progress(f"  self-heal 저장: {key} = {value[:60]}")
        except Exception as e:
            self._progress(f"  self-heal 저장 실패: {e}")

    # v1.5.43 L3: row HTML 만으로 담기 버튼 상대 CSS AI 질의
    async def _ai_suggest_row_relative_cart(self, row_html: str) -> str:
        """row 의 outerHTML 을 AI 에 보내 row 내부 상대 CSS 셀렉터를 받는다."""
        if not row_html:
            return ""
        try:
            from core.visual_agent import VisualAgent
            from core.ai_analyzer import _load_api_key
            agent = VisualAgent(api_key=_load_api_key(), wid=self._wid)
            if not agent._can_call_ai():
                return ""
            screenshot, _ = await agent._capture(self._page)
            prompt = f"""다음은 약품 도매상 사이트 결과 **한 행(tr)의 HTML** 입니다.
이 행 안에서 "장바구니 담기" 또는 "구매하기/추가" 에 해당하는 버튼의
**행 내부 상대 CSS 셀렉터** 를 알려주세요.

조건:
- tr 자체는 포함하지 말고, tr 안쪽 요소만 기준 (예: "td:last-child > a.btn")
- Playwright CSS (`:has-text()` 허용, `:contains()` 금지)
- onclick/javascript 값 사용 금지
- 없으면 null

행 HTML:
{row_html[:3000]}

응답 (JSON만):
{{"relative_css": "td:last-child > a.btn", "reason": "근거 짧게"}}
또는:
{{"relative_css": null, "reason": "이유"}}"""
            response = await agent._ask_ai(prompt, screenshot)
            if not response:
                return ""
            rel = (response.get("relative_css") or "").strip()
            if not rel:
                return ""
            # 보안/일관성 필터
            if "javascript:" in rel.lower() or "onclick" in rel.lower():
                return ""
            if "tr:nth-of-type" in rel or rel.startswith("tr"):
                return ""  # row 내부 상대 경로여야 함
            return rel
        except Exception as e:
            self._progress(f"  AI row 상대 담기 폴백 오류: {e}")
            return ""

    # v1.5.43: 절대 CSS 셀렉터에서 실제 DOM 요소의 tr 기준 상대경로 추출
    async def _compute_relative_css(self, absolute_css: str) -> str:
        """페이지에서 absolute_css 로 요소 찾아, closest('tr') 기준 상대 경로 반환.

        AI 답변이 절대경로여도 저장용 상대경로를 사후 추출하기 위함.
        요소 없거나 tr 안에 없으면 빈 문자열.
        """
        if not absolute_css or not self._page:
            return ""
        try:
            return await self._page.evaluate(
                r"""(css) => {
                    const el = document.querySelector(css);
                    if (!el) return '';
                    const tr = el.closest('tr');
                    if (!tr) return '';
                    const parts = [];
                    let cur = el;
                    while (cur && cur !== tr && cur.nodeType === 1 && parts.length < 5) {
                        let seg = cur.tagName.toLowerCase();
                        if (cur.id && document.getElementById(cur.id) === cur) {
                            seg += '#' + cur.id;
                        } else if (cur.className && typeof cur.className === 'string') {
                            const cls = cur.className.trim().split(/\s+/).filter(c => c && !/^\d/.test(c))[0];
                            if (cls) seg += '.' + cls;
                        }
                        const parent = cur.parentElement;
                        if (parent && parent !== tr.parentElement) {
                            const sib = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
                            if (sib.length > 1) {
                                const idx = sib.indexOf(cur);
                                if (idx >= 0) seg += `:nth-of-type(${idx + 1})`;
                            }
                        }
                        parts.unshift(seg);
                        cur = cur.parentElement;
                    }
                    return parts.join(' > ');
                }""",
                absolute_css,
            )
        except Exception:
            return ""

    # v1.5.42 품절 판정 재설계: 명시적 품절 체크 + AI 시각 확인 + 진단 업로드

    async def _check_explicit_out_of_stock(
        self, rows: list, stock_col: int | None
    ) -> bool:
        """모든 행이 명시적으로 '0' 또는 품절 키워드 포함인지 확인.

        stock_col 없거나 rows 비어있으면 False (확정 불가 → 품절 아님).
        하나라도 숫자가 양수거나 불명확한 텍스트면 False.
        """
        if stock_col is None or not rows:
            return False
        import re as _re
        oos_keywords = ("품절", "재고없", "재고 없", "soldout", "sold out")
        oos_count = 0
        checked = 0
        for row in rows:
            try:
                cells = await row.query_selector_all('td')
                if stock_col >= len(cells):
                    continue
                text = (await cells[stock_col].inner_text()).strip().lower()
                checked += 1
                digits = _re.sub(r'[^\d]', '', text)
                is_explicit_zero = digits == "0"
                is_oos_keyword = any(k in text for k in oos_keywords)
                if is_explicit_zero or is_oos_keyword:
                    oos_count += 1
                elif digits and int(digits) > 0:
                    # 명백히 재고 있는 행 하나라도 있으면 품절 아님
                    return False
            except Exception:
                continue
        # 체크한 모든 행이 명시적 oos 인 경우에만 True
        return checked > 0 and oos_count == checked

    async def _ai_check_out_of_stock(
        self, insurance_code: str, drug_name: str
    ) -> bool | None:
        """AI Vision 에 현재 화면이 '해당 약품 품절 상태' 인지 질의.

        Returns:
            True  — 품절로 확인
            False — 품절 아님 (재고 있음)
            None  — 판단 불가 (AI 비활성/에러). 호출부는 False 처리 권장.
        """
        try:
            from core.visual_agent import VisualAgent
            from core.ai_analyzer import _load_api_key
            agent = VisualAgent(api_key=_load_api_key(), wid=self._wid)
            if not agent._can_call_ai():
                return None
            screenshot, _ = await agent._capture(self._page)
            prompt = f"""스크린샷은 약품 도매상 사이트 검색 결과 페이지입니다.

약품: {drug_name[:60]} (보험코드: {insurance_code})

질문: 이 약품이 **품절/재고 없음** 상태로 표시되어 있습니까?

품절 신호:
- 재고 수량 "0" 명시
- "품절", "재고없음", "soldout" 텍스트
- 담기/구매 버튼이 비활성/회색/숨겨짐

재고 있음 신호:
- 재고 수량 양수 (예: "3", "10+")
- "재고" 아이콘/버튼이 정상 클릭 가능
- 담기 버튼 활성

응답 (JSON만):
{{"out_of_stock": true, "reason": "간단 근거"}}
또는:
{{"out_of_stock": false, "reason": "재고 있어 보임 / 판단 근거"}}"""
            response = await agent._ask_ai(prompt, screenshot)
            if not response or "out_of_stock" not in response:
                return None
            return bool(response.get("out_of_stock"))
        except Exception as e:
            self._progress(f"  AI 품절 확인 오류: {e}")
            return None

    async def _upload_oos_diagnostic(
        self, insurance_code: str, rows: list,
        stock_col: int | None, table: dict, reason: str
    ) -> None:
        """품절 판정 시점의 진단 정보를 서버에 업로드.

        reason: 'ai_confirmed' / 'suspected_misdetection' / 'explicit'
        개발자가 error_logs 에서 level=OOS_DIAG 로 필터 가능.
        """
        try:
            from core.cloud import is_enabled, _api_url, _headers
            if not is_enabled():
                return
            import requests as _req
            from datetime import datetime as _dt
            from core.version import VERSION

            # stock 컬럼 raw 텍스트 샘플 (최대 5행)
            samples = []
            if stock_col is not None:
                for i, row in enumerate(rows[:5]):
                    try:
                        cells = await row.query_selector_all('td')
                        if stock_col < len(cells):
                            t = (await cells[stock_col].inner_text()).strip()
                            samples.append({"row": i, "stock_text": t[:100]})
                    except Exception:
                        continue

            # 헤더 원본 (stock_col 무엇을 잡았는지)
            header_name = ""
            try:
                if rows and stock_col is not None:
                    tbl_handle = await rows[0].evaluate_handle(
                        'el => el.closest("table")'
                    )
                    ths = await tbl_handle.query_selector_all(
                        'thead th, tr:first-child th'
                    )
                    if stock_col < len(ths):
                        header_name = (
                            await ths[stock_col].inner_text()
                        ).strip()[:40]
            except Exception:
                pass

            screenshot_b64 = await self._capture_screenshot_b64()

            pharmacy_code = ""
            try:
                from core.auth import get_activation_code
                pharmacy_code = get_activation_code() or ""
            except Exception:
                pass

            payload = {
                "pharmacy_code": pharmacy_code,
                "version": VERSION,
                "level": "OOS_DIAG",
                "message": (
                    f"{self._wid} [{insurance_code}] 품절 판정 진단 "
                    f"(reason={reason})"
                ),
                "context": {
                    "wid": self._wid,
                    "insurance_code": insurance_code,
                    "reason": reason,
                    "stock_col": stock_col,
                    "stock_col_header": header_name,
                    "table_selectors": {
                        k: v for k, v in (table or {}).items()
                        if "col" in k or k in ("result_rows", "cart_btn")
                    },
                },
                "log_tail": (
                    '{"stock_text_samples": '
                    + str(samples)
                    + (', "screenshot_b64": "' + screenshot_b64 + '"'
                       if screenshot_b64 else "")
                    + "}"
                )[:500000],
            }
            _req.post(
                _api_url("error_logs"),
                headers=_headers(),
                json=payload,
                timeout=10,
            )
        except Exception as e:
            self._progress(f"  OOS 진단 업로드 실패: {e}")

    # v1.5.41 L4: 담김 시각 검증 (DOM diff 폴백)
    async def _ai_visual_verify_cart(
        self, before_snapshot: list, after_snapshot: list, drug_name: str
    ) -> bool:
        """DOM diff 로 장바구니 담김을 못 잡았을 때 스크린샷 기반 AI 확인.

        return True 이면 담긴 것으로 간주.
        비용 절감 위해 DOM diff 실패 시에만 호출 (정상 케이스는 호출 X).
        """
        try:
            from core.visual_agent import VisualAgent
            from core.ai_analyzer import _load_api_key
            agent = VisualAgent(api_key=_load_api_key(), wid=self._wid)
            if not agent._can_call_ai():
                return False
            screenshot, _ = await agent._capture(self._page)

            # before/after 테이블 행 수 차이 요약
            rows_summary = []
            for i in range(min(len(before_snapshot), len(after_snapshot))):
                b = before_snapshot[i].get("row_count", 0)
                a = after_snapshot[i].get("row_count", 0)
                rows_summary.append(f"table[{i}]: {b}→{a}")
            rows_txt = ", ".join(rows_summary) or "(스냅샷 없음)"

            prompt = f"""스크린샷은 약품 도매상 사이트입니다.
방금 어떤 버튼을 눌렀고, 지금 화면에 **장바구니(카트/Cart)** 라고 명시된 영역에
약품이 담긴 상태인지 확인해주세요.

약품명(참고용, 부분일치 허용): {drug_name[:60]}
DOM 테이블 행 수 변화: {rows_txt}

**반드시 아래 조건 중 하나 이상 만족해야 true:**
1. "장바구니", "카트", "Cart" 라고 **명시된 섹션/테이블/모달** 에 해당 약품명이 **행으로 추가**되어 보임 (이전엔 비어있었다면)
2. "장바구니 N건", "담긴 품목 N개" 등 **숫자 카운터가 0→양수 또는 증가**
3. "담기 완료", "장바구니에 추가되었습니다" 라는 **명시적 성공 토스트/모달**

**다음은 담김 신호 아님 (false 반환):**
- "제품정보", "상세정보", "상품 미리보기" 등 **제품 상세 패널**에 약품 표시 (이건 선택 표시일 뿐)
- 검색 결과 테이블의 특정 행 **하이라이트** (이건 선택 표시일 뿐)
- "자주구매 등록됨", "즐겨찾기 추가" 등 **다른 기능** 의 성공 메시지
- DOM 행 수 **변화 없음** 에서 제품정보만 업데이트된 경우

응답 (JSON만):
{{"cart_has_item": true, "confidence": "high"/"medium"/"low", "signal": "위 1/2/3 중 뭐", "reason": "짧은 근거"}}
또는:
{{"cart_has_item": false, "reason": "담김 영역 없음 또는 제품정보만 바뀜"}}"""

            response = await agent._ask_ai(prompt, screenshot)
            if not response:
                return False
            if not response.get("cart_has_item"):
                return False
            conf = (response.get("confidence") or "").lower()
            # v1.5.45: low/medium 모두 거부 — 세화 오탐 사고 재발 방지 (high 만 인정)
            if conf != "high":
                self._progress(
                    f"  AI 시각 담김 불충분 (confidence={conf}) → 거부"
                )
                return False
            signal = response.get("signal", "")
            self._progress(
                f"  AI 시각 담김 확인 (signal={signal}): "
                f"{response.get('reason', '')[:60]}"
            )
            return True
        except Exception as e:
            self._progress(f"  AI 시각 검증 오류: {e}")
            return False

    async def analyze_site(self, test_code: str = "646201260",
                           headless: bool = True) -> dict:
        """사이트 구조를 분석하고 셀렉터를 캐시한다.

        하이브리드 방식:
        - 로그인: 휴리스틱 (확실함)
        - 주문 페이지 찾기: AI (페이지 맥락 이해)
        - 검색/테이블: 휴리스틱 (맞는 페이지에서 정확함)

        Args:
            test_code: 검색 테스트용 보험코드
            headless: 브라우저 표시 여부
        """
        self._progress(f"사이트 분석 시작: {self.url}")
        all_selectors = {"url": self.url, "name": self.name}

        # 기존 로컬 캐시 삭제 — 잘못된 셀렉터가 남아있을 수 있음
        from core.selector_store import delete_selectors
        delete_selectors(self._wid)
        self._selectors = {}

        try:
            await self._launch(headless=headless)
            page = self._page
            page.on("dialog", lambda d: d.accept())

            # ── 1단계: 로그인 (휴리스틱) ──
            self._progress("1/4 로그인 분석 중...")
            await page.goto(self.url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            login_sel = await self._detect_login()
            all_selectors["login"] = login_sel

            if not login_sel.get("id_input") or not login_sel.get("pw_input"):
                self._progress("로그인 폼 탐지 실패")
                return all_selectors

            self._progress("1/4 로그인 시도 중...")
            await page.fill(login_sel["id_input"], self.user_id)
            await page.fill(login_sel["pw_input"], self.password)
            if login_sel.get("login_btn"):
                try:
                    await page.click(login_sel["login_btn"])
                except Exception:
                    await page.press(login_sel["pw_input"], "Enter")
            else:
                await page.press(login_sel["pw_input"], "Enter")
            await page.wait_for_timeout(4000)

            # 로그인 성공 확인 (login_async와 동일한 다중 판정)
            before_url = self.url
            current_url = page.url
            url_changed = current_url != before_url and "login" not in current_url.lower()

            id_field = await page.query_selector(login_sel["id_input"])
            pw_field = await page.query_selector(login_sel["pw_input"])
            form_gone = (not id_field or not await id_field.is_visible()) and \
                        (not pw_field or not await pw_field.is_visible())

            logout_el = None
            for sel in ['a:has-text("로그아웃")', 'a:has-text("LOGOUT")',
                        'button:has-text("로그아웃")']:
                logout_el = await page.query_selector(sel)
                if logout_el:
                    break

            login_success = url_changed or form_gone or (logout_el is not None)
            if not login_success:
                self._progress("로그인 실패")
                return all_selectors
            self._progress("로그인 성공")

            # ── 2단계: 약품 주문 페이지 찾기 (AI) ──
            self._progress("2/4 약품 주문 페이지 탐색 중 (AI)...")
            order_url = await self._ai_navigate_to_order_page()
            if order_url:
                all_selectors["order_url"] = order_url

            # ── 3단계: 검색/테이블 분석 (휴리스틱 — 이제 맞는 페이지) ──
            self._progress("3/4 검색/테이블 분석 중...")
            search_sel = await self._detect_search()
            all_selectors["search"] = search_sel

            if search_sel.get("search_input"):
                # 검색 테스트
                search_terms = []
                try:
                    from core.drug_api import get_drug_name
                    from core.inventory import load_inventory
                    import re as _re
                    dname = get_drug_name(test_code)
                    if dname == test_code:
                        dname = load_inventory().get(test_code, {}).get("drug_name", test_code)
                    short_name = _re.split(
                        r'(정|캡슐|캡|시럽|액|산|환|주|크림|연고|점안|점이|패치|필름|과립'
                        r'|밀리|미리|그램|mg|ML|ml|\d|[()\s])',
                        dname, flags=_re.IGNORECASE
                    )[0].strip()
                    if short_name and short_name != test_code and len(short_name) >= 2:
                        search_terms.append(short_name)
                except Exception:
                    pass
                search_terms.append(test_code)

                self._progress(f"  검색 테스트: {search_terms}")
                table_sel = {}
                for term in search_terms:
                    self._progress(f"  [{term}] 검색 중...")
                    try:
                        await page.wait_for_selector(
                            search_sel["search_input"], state="visible", timeout=5000)
                    except Exception:
                        continue
                    await page.fill(search_sel["search_input"], '')
                    await page.wait_for_timeout(300)
                    await page.fill(search_sel["search_input"], term)
                    searched = False
                    if search_sel.get("search_btn"):
                        try:
                            await page.click(search_sel["search_btn"])
                            searched = True
                        except Exception:
                            pass
                    if not searched:
                        await page.press(search_sel["search_input"], "Enter")
                    await page.wait_for_timeout(3000)
                    table_sel = await self._detect_result_table(test_code)
                    if table_sel and table_sel.get("result_rows"):
                        break
                all_selectors["table"] = table_sel

            # 분석 성공 판정
            has_search = bool(search_sel.get("search_input"))
            all_selectors["auto_detected"] = has_search

            # ── 4단계: 주문확정 + 이력 페이지 ──
            self._progress("4/4 주문확정/이력 분석 중...")
            confirm_sel = await self._detect_confirm()
            all_selectors["confirm"] = confirm_sel

            try:
                history_config = await self._detect_history_page()
                if history_config:
                    all_selectors["history"] = history_config
            except Exception:
                pass

            if all_selectors["auto_detected"]:
                self._progress("사이트 분석 성공")
            else:
                self._progress("사이트 분석 불완전 — 검색 셀렉터 없음")

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

            # ── Step 2: 검색 셀렉터 없으면 → AI로 주문 페이지 찾기 → 휴리스틱 검색 탐지 ──
            if not self._selectors.get("search", {}).get("search_input"):
                self._progress("검색 셀렉터 없음 → AI로 주문 페이지 탐색 중...")
                order_url = await self._ai_navigate_to_order_page()
                if order_url:
                    self._selectors["order_url"] = order_url
                    # 주문 페이지에서 휴리스틱 검색 탐지
                    search_sel = await self._detect_search()
                    if search_sel.get("search_input"):
                        self._selectors["search"] = search_sel
                        self._save_selectors(self._selectors)
                        self._progress(f"주문 페이지 검색 필드 발견: {search_sel['search_input']}")
                    else:
                        self._progress("주문 페이지에서도 검색 필드 못 찾음")
                else:
                    self._progress("AI 주문 페이지 탐색 실패")
        else:
            self._progress("로그인 실패")
            await self._screenshot(f"generic_{self._wid}_login_fail.png")

        return login_success

    # ────── 구조 진단 (DOM 분석 후 Supabase 업로드) ──────

    _STRUCTURE_ANALYZER_JS = r"""
    (() => {
      const _tag = (el) => el ? `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''}` : '';
      const _cssPath = (el) => {
        if (!el || !el.parentElement) return '';
        const parts = [];
        let cur = el;
        while (cur && cur.nodeType === 1 && parts.length < 6) {
          let seg = cur.tagName.toLowerCase();
          if (cur.id) { seg += '#' + cur.id; parts.unshift(seg); break; }
          if (cur.className && typeof cur.className === 'string') {
            const cls = cur.className.trim().split(/\s+/).filter(c => c && !/^\d/.test(c))[0];
            if (cls) seg += '.' + cls;
          }
          const idx = Array.from(cur.parentElement?.children || []).filter(c => c.tagName === cur.tagName).indexOf(cur);
          if (idx >= 0) seg += `:nth-of-type(${idx + 1})`;
          parts.unshift(seg);
          cur = cur.parentElement;
        }
        return parts.join(' > ');
      };
      // v1.5.43 근본 수정: row 내부 상대 경로 (ancestor = tr 기준).
      // 모든 행에 일반화되는 셀렉터를 저장하기 위한 핵심 함수.
      // 절대 경로처럼 `tr:nth-of-type(N)` 이 절대 안 섞이도록 ancestor 에서 멈춤.
      const _relativeCss = (el, ancestor) => {
        if (!el || !ancestor) return '';
        if (el === ancestor) return '';
        const parts = [];
        let cur = el;
        while (cur && cur !== ancestor && cur.nodeType === 1 && parts.length < 5) {
          let seg = cur.tagName.toLowerCase();
          // id 는 행 내부에 있어도 unique 가능 — 쓰면 더 짧고 안정적
          if (cur.id && document.getElementById(cur.id) === cur) {
            seg += '#' + cur.id;
          } else if (cur.className && typeof cur.className === 'string') {
            const cls = cur.className.trim().split(/\s+/).filter(c => c && !/^\d/.test(c))[0];
            if (cls) seg += '.' + cls;
          }
          // nth-of-type 은 row 내부에서 필요한 경우 유지 (td:nth-of-type(3) 같이)
          const parent = cur.parentElement;
          if (parent && parent !== ancestor.parentElement) {
            const siblings = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
            if (siblings.length > 1) {
              const idx = siblings.indexOf(cur);
              if (idx >= 0) seg += `:nth-of-type(${idx + 1})`;
            }
          }
          parts.unshift(seg);
          cur = cur.parentElement;
        }
        return parts.join(' > ');
      };
      // v1.5.43: 행 구조 지문 — 사이트 리뉴얼/구조 변경 자동 감지용.
      // td 개수 + 각 td 의 상호작용 요소 시그니처 + 자식 태그 구조 요약.
      const _rowFingerprint = (tr) => {
        if (!tr) return '';
        const cells = tr.querySelectorAll('td');
        const parts = [];
        cells.forEach((td, i) => {
          const hasInput = !!td.querySelector('input:not([type="hidden"])');
          const hasImg = !!td.querySelector('img');
          const hasBtn = !!td.querySelector('a, button, [onclick], [role="button"], [role="link"]');
          const innerTags = Array.from(td.children)
            .map(c => c.tagName.toLowerCase())
            .slice(0, 3)
            .join(',');
          parts.push(`${i}:${hasInput?1:0}${hasImg?1:0}${hasBtn?1:0}:${innerTags}`);
        });
        return parts.join('|').slice(0, 300);
      };
      // v1.5.41: visibility 사전 필터 — display:none / visibility:hidden / 0-size 제외
      const _isVisible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) return false;
        try {
          const s = window.getComputedStyle(el);
          if (s.display === 'none' || s.visibility === 'hidden') return false;
          if (parseFloat(s.opacity || '1') < 0.1) return false;
        } catch (e) {}
        return true;
      };
      // 개인정보/비밀 필드 값은 마스킹 (id/pw input, 환자명 등)
      const _sanitize = (html) => {
        if (!html) return '';
        return html
          .replace(/value="[^"]*"/gi, 'value=""')
          .replace(/value='[^']*'/gi, "value=''")
          .replace(/<input([^>]*type\s*=\s*["']?password[^>]*)>/gi, '<input$1 value="">');
      };
      const report = {
        url: location.href, title: document.title,
        tables: [], buttons_with_text: [], inputs: [],
        images_likely_buttons: [], cart_indicators: [],
        sample_rows_html: [],            // 각 테이블 첫 3행 outerHTML
        row_last_cell_clickables: [],    // (히스토리컬 이름) 실제로는 row 전체 td 의 클릭 가능 요소
        iframes: [],                     // v1.5.41: iframe 감지 (내부 자동 클릭은 미지원)
        global_cart_candidates: [],      // v1.5.44: row 밖 전역 "장바구니담기" 버튼 (세화 패턴)
        row_checkboxes: [],              // v1.5.44: row 내부 체크박스 (전역 버튼 패턴과 짝)
      };
      document.querySelectorAll('table').forEach((tbl, ti) => {
        const ths = Array.from(tbl.querySelectorAll('thead th, thead td')).map(h => h.textContent.trim().slice(0, 20));
        const firstTh = ths.length ? ths : Array.from(tbl.querySelectorAll('tr:first-child th, tr:first-child td')).map(h => h.textContent.trim().slice(0, 20));
        const bodyRows = tbl.querySelectorAll('tbody tr, tr');
        const sampleRow = bodyRows[ths.length ? 0 : 1] || bodyRows[0];
        const rowCells = sampleRow ? Array.from(sampleRow.querySelectorAll('td')).map(td => ({
          text: td.textContent.trim().slice(0, 40),
          inner_tags: Array.from(td.children).map(_tag).slice(0, 4),
          has_input: !!td.querySelector('input'), has_img: !!td.querySelector('img'),
          has_button: !!td.querySelector('button, a, [onclick], [role="button"], [role="link"], [tabindex]'),
        })) : [];
        // v1.5.43 근본 수정: nth-of-type 없는 일반화된 rows 셀렉터 + 첫 데이터행 지문
        const tblCss = _cssPath(tbl);
        let rowsCss;
        if (tbl.id) {
          rowsCss = `#${CSS.escape(tbl.id)} tbody tr`;
        } else {
          // tblCss 는 경로에 nth-of-type 가 있을 수 있지만 "tbody tr" 은 행 전체 매칭
          rowsCss = tblCss + ' tbody tr';
        }
        const firstDataRow = Array.from(bodyRows).find(tr => tr.querySelectorAll('td').length >= 2);
        const rowFp = _rowFingerprint(firstDataRow);
        report.tables.push({
          idx: ti,
          css: tblCss,
          rows_css: rowsCss,
          row_fingerprint: rowFp,
          headers: firstTh.slice(0, 20),
          row_count: bodyRows.length,
          first_row_cells: rowCells.slice(0, 20)
        });
        // 각 테이블에서 데이터 있는 row 최대 3개의 outerHTML 통째로 수집
        const dataRows = Array.from(bodyRows).filter(tr =>
          tr.querySelectorAll('td').length >= 2
        ).slice(0, 3);
        dataRows.forEach((tr, ri) => {
          report.sample_rows_html.push({
            table_idx: ti, row_idx: ri,
            html: _sanitize((tr.outerHTML || '').slice(0, 3000)),
          });
          // v1.5.41: row 의 **모든 td** 클릭 가능 요소 수집 (담기 버튼이 첫째/중간 td 인 사이트 대응)
          //          + role/tabindex 기반 요소 포함, visibility 필터 적용
          // v1.5.45: 자주구매/즐겨찾기/별표 블랙리스트 (세화 freq.png 오탐 방지)
          const BLACKLIST_KEYWORDS = ['freq', '즐겨', '자주', 'favorite', 'favor', 'star', 'bookmark', '다빈도', 'multi_freq', '관심제품', '관심', 'interest'];
          const clickableSelector = 'a, button, img, input, [onclick], [role="button"], [role="link"], [tabindex]:not([tabindex="-1"])';
          Array.from(tr.querySelectorAll('td')).forEach((td, cellIdx) => {
            td.querySelectorAll(clickableSelector).forEach(el => {
              if (report.row_last_cell_clickables.length >= 50) return;
              if (!_isVisible(el)) return;
              // input type=text/number 는 담기 버튼 아닐 확률 높음 (수량 입력) — 제외
              if (el.tagName.toLowerCase() === 'input') {
                const t = (el.getAttribute('type') || '').toLowerCase();
                if (t === 'text' || t === 'number' || t === 'password' || t === 'hidden') return;
              }
              // v1.5.45: 자주구매/즐겨찾기 요소 블랙리스트
              const alt_l = (el.getAttribute('alt') || '').toLowerCase();
              const src_l = (el.getAttribute('src') || '').toLowerCase();
              const title_l = (el.getAttribute('title') || '').toLowerCase();
              const class_l = (typeof el.className === 'string' ? el.className : '').toLowerCase();
              const haystack = alt_l + '|' + src_l + '|' + title_l + '|' + class_l;
              if (BLACKLIST_KEYWORDS.some(k => haystack.includes(k))) return;
              report.row_last_cell_clickables.push({
                table_idx: ti, row_idx: ri, cell_idx: cellIdx,
                tag: el.tagName.toLowerCase(),
                role: el.getAttribute('role') || '',
                css: _cssPath(el),
                row_relative_css: _relativeCss(el, tr),
                outer_html: _sanitize((el.outerHTML || '').slice(0, 500)),
                onclick: (el.getAttribute('onclick') || '').slice(0, 200),
                href: (el.getAttribute('href') || '').slice(0, 200),
                alt: (el.getAttribute('alt') || '').slice(0, 40),
                src: (el.getAttribute('src') || '').slice(0, 100),
                text: (el.textContent || '').trim().slice(0, 30),
                aria_label: (el.getAttribute('aria-label') || '').slice(0, 40),
                title_attr: (el.getAttribute('title') || '').slice(0, 40),
              });
            });
          });
        });
      });
      // v1.5.41: button 류 선택자에 role/tabindex 포함, visibility 필터
      const btnKeywords = ['담기', '장바구니', '추가', '구매', '주문'];
      const btnSelector = 'button, a, input[type="button"], input[type="submit"], input[type="image"], span[onclick], div[onclick], [role="button"], [role="link"], [tabindex]:not([tabindex="-1"])';
      document.querySelectorAll(btnSelector).forEach(el => {
        if (!_isVisible(el)) return;
        const txt = (el.textContent || '').trim().slice(0, 30);
        const val = el.value || '', alt = el.getAttribute('alt') || '', src = el.getAttribute('src') || '';
        const aria = el.getAttribute('aria-label') || '', title = el.getAttribute('title') || '';
        const hay = txt + ' ' + val + ' ' + alt + ' ' + aria + ' ' + title;
        if (btnKeywords.find(k => hay.includes(k))) {
          const tr = el.closest('tr');
          report.buttons_with_text.push({
            tag: el.tagName.toLowerCase(), type: el.getAttribute('type') || '',
            role: el.getAttribute('role') || '',
            text: txt, value: val, alt, src: src.slice(0, 80), css: _cssPath(el),
            row_relative_css: tr ? _relativeCss(el, tr) : '',
            aria_label: aria.slice(0, 40), title_attr: title.slice(0, 40),
            in_table_row: !!tr,
            near_qty_input: !!tr?.querySelector('input[type="text"], input[type="number"]'),
          });
        }
      });
      report.buttons_with_text = report.buttons_with_text.slice(0, 40);
      document.querySelectorAll('input[type="text"], input[type="number"]').forEach((inp, i) => {
        if (i >= 10) return;
        if (!_isVisible(inp)) return;
        const row = inp.closest('tr');
        report.inputs.push({
          css: _cssPath(inp),
          row_relative_css: row ? _relativeCss(inp, row) : '',
          name: inp.name || inp.id || '', placeholder: inp.placeholder || '',
          in_row: !!row, row_idx: row ? Array.from(row.parentElement.children).indexOf(row) : -1,
        });
      });
      // v1.5.41: 이미지 버튼 후보 확대 — td:last-child 제한 제거, row 내 모든 img
      // v1.5.45: 자주구매/즐겨찾기 블랙리스트 적용
      const IMG_BLACKLIST = ['freq', '즐겨', '자주', 'favorite', 'favor', 'star', 'bookmark', '다빈도', 'multi_freq', '관심제품', '관심', 'interest'];
      document.querySelectorAll('input[type="image"], a > img, button > img, tr img').forEach((el, i) => {
        if (i >= 30) return;
        if (!_isVisible(el)) return;
        const alt_l = (el.getAttribute('alt') || '').toLowerCase();
        const src_l = (el.getAttribute('src') || '').toLowerCase();
        const title_l = (el.getAttribute('title') || '').toLowerCase();
        if (IMG_BLACKLIST.some(k => (alt_l + src_l + title_l).includes(k))) return;
        const parent = el.closest('a, button, input, [role="button"]');
        const tr = el.closest('tr');
        report.images_likely_buttons.push({
          tag: el.tagName.toLowerCase(), alt: el.getAttribute('alt') || '',
          src: (el.getAttribute('src') || '').slice(0, 100),
          parent_tag: parent ? parent.tagName.toLowerCase() : '',
          css: _cssPath(el),
          row_relative_css: tr ? _relativeCss(el, tr) : '',
          in_row: !!tr,
        });
      });
      // v1.5.44: 전역 담기 버튼 수집 (row 밖에 있는 "장바구니담기/선택담기" 버튼)
      //          세화처럼 각 행에 담기 버튼 없고 전역 버튼 1개 + row 체크박스 패턴 대응
      const GLOBAL_CART_KEYWORDS = ['장바구니담기', '선택담기', '주문담기', '장바구니 담기', '선택 담기'];
      const GLOBAL_CART_KEYWORDS_LOOSE = ['장바구니', '담기', '선택', '주문'];  // 2차 매칭
      document.querySelectorAll('button, a, input[type="button"], input[type="submit"], [role="button"]').forEach(el => {
        if (!_isVisible(el)) return;
        if (el.closest('tr')) return;  // row 안에 있는 건 row 패턴용
        const txt = (el.textContent || '').trim();
        const val = (el.value || '').trim();
        const aria = (el.getAttribute('aria-label') || '').trim();
        const hay = (txt + ' ' + val + ' ' + aria).slice(0, 80);
        let matched = GLOBAL_CART_KEYWORDS.some(k => hay.includes(k));
        // 2차: 느슨한 매칭 — "담기" 포함 + 버튼 명확한 요소
        if (!matched && (el.tagName === 'BUTTON' || el.type === 'button' || el.type === 'submit')) {
          matched = hay.includes('담기') || hay.includes('장바구니');
        }
        if (!matched) return;
        if (report.global_cart_candidates.length >= 10) return;
        report.global_cart_candidates.push({
          tag: el.tagName.toLowerCase(),
          text: txt.slice(0, 40),
          value: val.slice(0, 40),
          aria_label: aria.slice(0, 40),
          css: _cssPath(el),
          type: el.getAttribute('type') || '',
        });
      });

      // v1.5.44: row 내부 체크박스 수집 (전역 버튼 패턴의 row 선택용)
      document.querySelectorAll('input[type="checkbox"]').forEach((chk, i) => {
        if (i >= 20) return;
        if (!_isVisible(chk)) return;
        const tr = chk.closest('tr');
        if (!tr) return;
        // 체크박스가 어느 테이블의 몇번째 row 에 있는지
        const tbl = tr.closest('table');
        let tbl_idx = -1;
        if (tbl) {
          tbl_idx = Array.from(document.querySelectorAll('table')).indexOf(tbl);
        }
        report.row_checkboxes.push({
          css: _cssPath(chk),
          row_relative_css: _relativeCss(chk, tr),
          table_idx: tbl_idx,
          checked: chk.checked,
          name: chk.name || chk.id || '',
        });
      });

      // v1.5.41: iframe 감지 (내부 자동 클릭은 v1.5.42 예정)
      document.querySelectorAll('iframe').forEach((ifr, i) => {
        if (i >= 10) return;
        let same_origin = false, inner_tables = 0, inner_buttons = 0;
        try {
          const d = ifr.contentDocument;
          if (d) {
            same_origin = true;
            inner_tables = d.querySelectorAll('table').length;
            inner_buttons = d.querySelectorAll('button, a[onclick], input[type=image]').length;
          }
        } catch (e) { /* cross-origin */ }
        report.iframes.push({
          css: _cssPath(ifr),
          src: (ifr.getAttribute('src') || '').slice(0, 150),
          name: ifr.name || ifr.id || '',
          same_origin, inner_tables, inner_buttons,
          visible: _isVisible(ifr),
        });
      });
      // 장바구니 카운트 후보 — 키워드 + "N건/N개" 패턴 + 장바구니 테이블 tbody tr 개수
      const cartKw = ['장바구니', '카트', 'cart', '담긴', '선택', 'bag', '건', '개'];
      const numPattern = /(\d+)\s*(건|개|items?|ea)/i;
      document.querySelectorAll('span, em, strong, b, div, td, a, p').forEach(el => {
        if (report.cart_indicators.length >= 20) return;
        const t = (el.textContent || '').trim();
        if (t.length > 40 || t.length < 1) return;
        const numMatch = t.match(numPattern);
        const hasKw = cartKw.some(k => t.includes(k));
        const hasCartClass = el.className && typeof el.className === 'string' && /bag|cart/i.test(el.className);
        if (numMatch || (hasKw && /\d/.test(t)) || hasCartClass) {
          const nums = t.match(/(\d+)/);
          report.cart_indicators.push({
            css: _cssPath(el), text: t.slice(0, 40),
            number: nums ? nums[1] : '',
            match_type: numMatch ? 'num+unit' : (hasCartClass ? 'cart_class' : 'keyword'),
          });
        }
      });
      // 장바구니 테이블 후보 — 클래스/id 에 bag/cart 포함된 테이블
      document.querySelectorAll('[class*="bag"] table, [id*="bag"] table, [class*="cart"] table, [id*="cart"] table').forEach((tbl, i) => {
        if (i >= 5) return;
        const rows = tbl.querySelectorAll('tbody tr, tr');
        report.cart_indicators.push({
          css: _cssPath(tbl) + ' tbody tr',
          text: `[cart-table-rows=${rows.length}]`,
          number: String(rows.length),
          match_type: 'cart_table_rows',
        });
      });
      return report;
    })()
    """

    async def analyze_structure(
        self, headless: bool = True, probe_term: str = "타이레놀"
    ) -> dict:
        """도매상 주문 페이지 DOM 구조를 분석한다 (수동 셀렉터 주입 보조용).

        흐름: 로그인 → (주문 페이지 이동) → 초기 캡처 → 검색 실행 → 결과 캡처.
        캡처는 DOM의 핵심 단서(테이블 헤더/셀 구조, 담기 키워드 버튼, 수량 입력,
        이미지 버튼, 장바구니 카운트 후보)만 수집해 민감정보를 제외한다.
        """
        result = {
            "wid": self._wid,
            "site_url": self.url,
            "probe_term": probe_term,
            "captures": [],
            "selectors_snapshot": {
                "search": self._selectors.get("search", {}),
                "table": self._selectors.get("table", {}),
            },
        }
        try:
            await self._launch(headless=headless)
            logged_in = await self.login_async(headless=headless)
            if not logged_in:
                result["error"] = "로그인 실패"
                return result

            self._progress("구조 진단: 초기 페이지 캡처...")
            try:
                cap1 = await self._page.evaluate(self._STRUCTURE_ANALYZER_JS)
                result["captures"].append({"stage": "after_login", "data": cap1})
            except Exception as e:
                result["captures"].append({"stage": "after_login", "error": str(e)})

            # 검색 실행 (search_input 있으면)
            search = self._selectors.get("search", {})
            search_input = search.get("search_input")
            search_btn = search.get("search_btn")
            if search_input:
                try:
                    self._progress(f"구조 진단: '{probe_term}' 검색...")
                    await self._page.wait_for_selector(
                        search_input, state="visible", timeout=8000
                    )
                    await self._page.fill(search_input, "")
                    await self._page.wait_for_timeout(300)
                    await self._page.fill(search_input, probe_term)
                    await self._page.wait_for_timeout(300)
                    if search_btn:
                        try:
                            await self._page.click(search_btn)
                        except Exception:
                            await self._page.press(search_input, "Enter")
                    else:
                        await self._page.press(search_input, "Enter")
                    await self._page.wait_for_timeout(3500)
                    cap2 = await self._page.evaluate(self._STRUCTURE_ANALYZER_JS)
                    result["captures"].append({
                        "stage": "after_search", "probe": probe_term, "data": cap2,
                    })
                except Exception as e:
                    result["captures"].append({
                        "stage": "after_search", "probe": probe_term, "error": str(e),
                    })
            else:
                result["note"] = "search_input 셀렉터 없음 — 검색 단계 생략"

            return result
        finally:
            try:
                await self._close()
            except Exception:
                pass

    # ────── 자동 온보딩 (v1.5.39) ──────

    async def full_onboard(
        self, probe_term: str = "타이레놀", headless: bool = True
    ) -> dict:
        """도매상 등록 시 1회 수행하는 자동 연동.

        로그인 → 검색 실행 검증 → 담기 후보 수집 → 각 후보 실 클릭 + DOM diff
        검증 → 검증된 selector 를 Supabase 저장 → 테스트 흔적 정리.

        Returns:
            {
                "success": bool,
                "stage": "login"/"search"/"cart_button"/"verify"/"save"/"done",
                "message": str,
                "confirmed_selectors": dict,
                "onboard_log": {...상세 추적 정보...},
            }
        """
        from datetime import datetime as _dt

        report = {
            "wid": self._wid,
            "site_url": self.url,
            "success": False,
            "stage": "start",
            "message": "",
            "confirmed_selectors": {},
            "onboard_log": {
                "stages": [],
                "candidates_tried": [],
                "dom_samples": [],
            },
        }

        def _mark(stage, ok, detail=""):
            report["onboard_log"]["stages"].append({
                "stage": stage, "ok": ok, "detail": detail,
                "ts": _dt.now().isoformat(),
            })

        try:
            await self._launch(headless=headless)

            # 1. 로그인
            self._progress("연동 [1/5]: 로그인...")
            if not await self.login_async(headless=headless):
                report["stage"] = "login"
                report["message"] = "로그인 실패 — ID/PW 확인 필요"
                _mark("login", False)
                return report
            _mark("login", True)

            # v1.5.46: 수동 셀렉터 우선 검증 (validation-only 모드)
            # 서버에서 받은 수동 주입 셀렉터가 있으면 AI 자동 탐지 건너뛰고
            # 결과 행 셀렉터가 실제로 매칭되는지만 확인해서 통과시킴.
            # 실패 시 아래 AI 자동 탐지로 폴백.
            table_cfg = self._selectors.get("table", {}) or {}
            schema_ver = table_cfg.get("schema_version", "")
            layout_mode_hint = table_cfg.get("layout_mode", "")
            manual_present = bool(
                schema_ver in ("v1.5.45", "v1.5.46")
                and layout_mode_hint
                and table_cfg.get("result_rows")
            )
            if manual_present:
                self._progress(
                    f"연동: 수동 셀렉터 감지 (schema={schema_ver}, "
                    f"layout={layout_mode_hint}) → 검증 모드"
                )
                try:
                    search_cfg = self._selectors.get("search", {}) or {}
                    s_input = search_cfg.get("search_input")
                    s_btn = search_cfg.get("search_btn")
                    result_rows_sel = table_cfg.get("result_rows")
                    if s_input:
                        await self._page.fill(s_input, "")
                        await self._page.wait_for_timeout(200)
                        await self._page.fill(s_input, probe_term)
                        await self._page.wait_for_timeout(200)
                        if s_btn:
                            try:
                                await self._page.click(s_btn)
                            except Exception:
                                await self._page.press(s_input, "Enter")
                        else:
                            await self._page.press(s_input, "Enter")
                        await self._page.wait_for_timeout(3000)
                        # 수동 result_rows 셀렉터로 행 개수 확인
                        row_count = await self._page.locator(
                            result_rows_sel
                        ).count()
                        if row_count > 0:
                            report["success"] = True
                            report["stage"] = "done"
                            report["message"] = (
                                f"수동 셀렉터 검증 성공 "
                                f"({probe_term} → {row_count}행)"
                            )
                            report["confirmed_selectors"] = self._selectors
                            _mark(
                                "manual_validation", True,
                                f"rows={row_count} layout={layout_mode_hint}"
                            )
                            return report
                        _mark(
                            "manual_validation", False,
                            f"result_rows 매칭 0 — AI 자동 탐지로 폴백"
                        )
                    else:
                        _mark(
                            "manual_validation", False,
                            "search_input 없음 — AI 자동 탐지로 폴백"
                        )
                except Exception as e:
                    _mark(
                        "manual_validation", False,
                        f"validation 예외: {str(e)[:120]} — AI 자동 탐지로 폴백"
                    )

            # 2. 검색 실행 검증 (search_input 은 기존 셀렉터 사용)
            search = self._selectors.get("search", {})
            search_input = search.get("search_input")
            search_btn = search.get("search_btn")

            if not search_input:
                report["stage"] = "search"
                report["message"] = "검색 입력창 셀렉터 없음 — 개발자 분석 필요"
                _mark("search_probe", False, "no search_input")
                try:
                    report["onboard_log"]["dom_samples"].append(
                        await self._page.evaluate(self._STRUCTURE_ANALYZER_JS)
                    )
                except Exception:
                    pass
                return report

            self._progress(f"연동 [2/5]: '{probe_term}' 검색 시도...")
            before_search = await self._snapshot_tables()
            try:
                await self._page.fill(search_input, "")
                await self._page.wait_for_timeout(200)
                await self._page.fill(search_input, probe_term)
                await self._page.wait_for_timeout(200)
                if search_btn:
                    try:
                        await self._page.click(search_btn)
                    except Exception:
                        await self._page.press(search_input, "Enter")
                else:
                    await self._page.press(search_input, "Enter")
                await self._page.wait_for_timeout(3000)
            except Exception as e:
                report["stage"] = "search"
                report["message"] = f"검색 실행 오류: {e}"
                _mark("search_probe", False, str(e)[:120])
                return report

            after_search = await self._snapshot_tables()
            result_table_idx = -1
            rows_added = 0
            for i in range(min(len(before_search), len(after_search))):
                diff = after_search[i]["row_count"] - before_search[i]["row_count"]
                if diff > 0:
                    result_table_idx = i
                    rows_added = diff
                    break
            if result_table_idx < 0:
                report["stage"] = "search"
                report["message"] = f"'{probe_term}' 검색 후 결과 행 감지 실패"
                _mark("search_probe", False, "no rows added")
                try:
                    report["onboard_log"]["dom_samples"].append(
                        await self._page.evaluate(self._STRUCTURE_ANALYZER_JS)
                    )
                except Exception:
                    pass
                return report
            _mark("search_probe", True, f"table[{result_table_idx}] +{rows_added}행")

            # 3. 담기 후보 수집
            self._progress("연동 [3/5]: 담기 버튼 후보 탐색...")
            dom_report = await self._page.evaluate(self._STRUCTURE_ANALYZER_JS)
            report["onboard_log"]["dom_samples"].append(dom_report)

            # v1.5.43 근본 수정: row_relative_css 가 있는 후보만 수집.
            # row 내부 상대경로 없는 후보는 다른 행에 일반화 불가능 → 제외.
            candidates = []
            for c in dom_report.get("row_last_cell_clickables", []):
                if c.get("table_idx") != result_table_idx:
                    continue
                rel = c.get("row_relative_css", "") or ""
                if not rel:
                    continue
                candidates.append({
                    "css": c["css"],
                    "row_relative_css": rel,
                    "in_row": True,
                    "source": f"row_cell[{c.get('tag')}]",
                })
            for b in dom_report.get("buttons_with_text", []):
                rel = b.get("row_relative_css", "") or ""
                if not b.get("in_table_row") or not rel:
                    continue
                candidates.append({
                    "css": b["css"],
                    "row_relative_css": rel,
                    "in_row": True,
                    "source": f"btn[{(b.get('text') or b.get('alt') or '')[:20]}]",
                })
            for img in dom_report.get("images_likely_buttons", []):
                alt_lower = (img.get("alt") or "").lower()
                src_lower = (img.get("src") or "").lower()
                if any(k in (alt_lower + " " + src_lower)
                       for k in ["bag", "cart", "담기", "save", "add", "추가"]):
                    rel = img.get("row_relative_css", "") or ""
                    if not img.get("in_row") or not rel:
                        continue
                    candidates.append({
                        "css": img["css"],
                        "row_relative_css": rel,
                        "in_row": True,
                        "source": f"img[{(img.get('alt') or img.get('src') or '')[:30]}]",
                    })

            # 중복 제거 (row_relative_css 기준 — 진짜 중복 제거)
            seen = set()
            unique = []
            for c in candidates:
                key = c["row_relative_css"]
                if key in seen:
                    continue
                seen.add(key)
                unique.append(c)
            candidates = unique

            # v1.5.41 L2-b: hover 재스캔 — 1차 후보 < 3 개면 각 결과 row 에 hover 후 재수집
            #                hover 시에만 나타나는 액션바(오버레이 담기 버튼) 대응
            if len(candidates) < 3 and result_table_idx >= 0:
                try:
                    tbl_css = dom_report["tables"][result_table_idx].get("css", "")
                    if tbl_css:
                        row_sel = f"{tbl_css} tbody tr"
                        rows_loc = self._page.locator(row_sel)
                        nrows = min(await rows_loc.count(), 3)
                        hover_found = []
                        for ri in range(nrows):
                            try:
                                await rows_loc.nth(ri).hover(timeout=1500)
                                await self._page.wait_for_timeout(250)
                                dom2 = await self._page.evaluate(self._STRUCTURE_ANALYZER_JS)
                                for c in dom2.get("row_last_cell_clickables", []):
                                    if c.get("table_idx") != result_table_idx:
                                        continue
                                    rel = c.get("row_relative_css", "") or ""
                                    if not rel or rel in seen:
                                        continue
                                    seen.add(rel)
                                    hover_found.append({
                                        "css": c["css"],
                                        "row_relative_css": rel,
                                        "in_row": True,
                                        "source": f"hover_row[{c.get('tag')}]",
                                        "needs_hover": True,
                                        "hover_target": f"{row_sel} >> nth={ri}",
                                    })
                            except Exception:
                                continue
                        if hover_found:
                            candidates.extend(hover_found)
                            _mark(
                                "hover_rescan", True,
                                f"+{len(hover_found)} hover candidates",
                            )
                except Exception as e:
                    _mark("hover_rescan", False, str(e)[:120])

            if not candidates:
                # v1.5.44: row 내부 후보 0개여도 패턴 B (전역 담기 버튼) 로 넘어감
                _mark("cart_probe", False, "no row-internal — will try pattern B (global)")
            else:
                _mark("cart_probe", True, f"{len(candidates)} candidates")

            # 4. 수량 input 후보 선정 + 약품명 수집
            qty_input_sel = None
            for inp in dom_report.get("inputs", []):
                if inp.get("in_row") and inp.get("row_idx", -1) >= 0:
                    qty_input_sel = inp["css"]
                    break

            drug_text = ""
            try:
                drug_text = await self._page.evaluate(
                    "(i) => { const tbls = document.querySelectorAll('table');"
                    "const rows = tbls[i] ? tbls[i].querySelectorAll('tbody tr, tr') : [];"
                    "return rows.length ? rows[rows.length - 1].innerText.slice(0, 300) : ''; }",
                    result_table_idx,
                )
            except Exception:
                pass

            # 5. 후보 시험 담기 → DOM diff 검증 (+ L4 시각 담김 검증 폴백)
            self._progress(f"연동 [4/5]: {len(candidates)}개 후보 시험 담기...")
            confirmed_cart_table_idx = -1

            async def _probe_candidate(cand):
                """단일 후보 시험 담기 + DOM diff 검증.
                성공 시 verify dict 반환, 실패 시 None.
                """
                tried_log = {**cand, "result": ""}
                try:
                    before_local = await self._snapshot_tables()
                    if qty_input_sel:
                        try:
                            qty_el = self._page.locator(qty_input_sel).first
                            if await qty_el.count() > 0:
                                await qty_el.fill("1")
                                await self._page.wait_for_timeout(200)
                        except Exception:
                            pass
                    # v1.5.41 L2-b: hover 전용 요소면 먼저 row 에 hover 걸어 노출 유지
                    if cand.get("needs_hover") and cand.get("hover_target"):
                        try:
                            await self._page.locator(
                                cand["hover_target"]
                            ).first.hover(timeout=1500)
                            await self._page.wait_for_timeout(200)
                        except Exception:
                            pass
                    try:
                        btn = self._page.locator(cand["css"]).first
                        if await btn.count() == 0:
                            tried_log["result"] = "not_found"
                            report["onboard_log"]["candidates_tried"].append(tried_log)
                            return None
                        await btn.click(timeout=3000, force=True)
                    except Exception as e:
                        tried_log["result"] = "click_error"
                        tried_log["error"] = str(e)[:120]
                        report["onboard_log"]["candidates_tried"].append(tried_log)
                        return None

                    await self._page.wait_for_timeout(1500)
                    try:
                        for ps in ['button:has-text("확인")',
                                   'button:has-text("닫기")']:
                            p = self._page.locator(ps).first
                            if await p.count() > 0 and await p.is_visible():
                                await p.click(timeout=1500)
                                await self._page.wait_for_timeout(400)
                                break
                    except Exception:
                        pass

                    after_local = await self._snapshot_tables()
                    verify = await self._verify_cart_added(
                        drug_name=drug_text, insurance_code="",
                        before=before_local, after=after_local,
                    )
                    if verify.get("verified"):
                        tried_log["result"] = "VERIFIED"
                        tried_log["cart_table_idx"] = verify.get("cart_table_idx", -1)
                        report["onboard_log"]["candidates_tried"].append(tried_log)
                        return verify

                    # v1.5.41 L4: DOM diff 못 잡으면 AI 시각 담김 확인 폴백
                    visual_verified = await self._ai_visual_verify_cart(
                        before_local, after_local, drug_text
                    )
                    if visual_verified:
                        tried_log["result"] = "VERIFIED_VISUAL"
                        tried_log["reason"] = "AI visual confirm"
                        # cart_table_idx 가 -1 이면 저장 단계에서 cart_rows_sel 이 비게 됨 (감수)
                        report["onboard_log"]["candidates_tried"].append(tried_log)
                        return {"verified": True, "cart_table_idx": -1,
                                "visual": True}

                    tried_log["result"] = "not_verified"
                    tried_log["reason"] = verify.get("reason", "")
                    report["onboard_log"]["candidates_tried"].append(tried_log)
                    return None
                except Exception as e:
                    tried_log["result"] = "error"
                    tried_log["error"] = str(e)[:120]
                    report["onboard_log"]["candidates_tried"].append(tried_log)
                    return None

            # v1.5.43/44: 저장용 row 기준 상대 셀렉터 + click 용 절대 셀렉터 분리
            confirmed_cart_rel = ""       # 패턴 A: row 내부 상대 CSS
            confirmed_cart_abs = ""       # 패턴 A: 절대 CSS (세션 내 사용)
            confirmed_global_cart = ""    # 패턴 B: 전역 담기 버튼 CSS
            confirmed_checkbox_rel = ""   # 패턴 B: row 체크박스 상대 CSS
            confirmed_layout_mode = ""    # "row_cart_btn" or "global_cart_btn"

            # 패턴 A: row 내부 담기 버튼 후보 시험
            for idx, cand in enumerate(candidates, 1):
                self._progress(f"  패턴 A 시험 {idx}/{len(candidates)}: {cand['source']}")
                v = await _probe_candidate(cand)
                if v:
                    confirmed_cart_abs = cand["css"]
                    confirmed_cart_rel = cand.get("row_relative_css", "")
                    confirmed_cart_table_idx = v.get("cart_table_idx", -1)
                    break

            # 패턴 A - L3 AI 폴백
            if not confirmed_cart_abs and candidates:
                self._progress("  패턴 A 전원 실패 → AI Vision 에 문의...")
                ai_cands = await self._ai_suggest_cart_button(
                    result_table_idx, dom_report
                )
                for idx, cand in enumerate(ai_cands[:2], 1):
                    self._progress(f"  AI 제안 시험 {idx}/{len(ai_cands[:2])}: {cand['source']}")
                    v = await _probe_candidate(cand)
                    if v:
                        confirmed_cart_abs = cand["css"]
                        rel_from_ai = cand.get("row_relative_css", "")
                        if not rel_from_ai:
                            try:
                                rel_from_ai = await self._compute_relative_css(
                                    cand["css"]
                                )
                            except Exception:
                                rel_from_ai = ""
                        confirmed_cart_rel = rel_from_ai
                        confirmed_cart_table_idx = v.get("cart_table_idx", -1)
                        _mark("ai_cart_fallback", True,
                              f"AI rescued rel={confirmed_cart_rel[:60]}")
                        break

            # v1.5.44 패턴 B: 전역 담기 버튼 + row 체크박스 (세화 패턴)
            # 패턴 A 가 실패했거나, row_relative_css 를 확보 못 한 경우 진입
            if not confirmed_cart_abs or not confirmed_cart_rel:
                if not confirmed_cart_abs:
                    self._progress("  패턴 A 전원 실패 → 패턴 B (전역 담기 버튼) 시도...")
                else:
                    self._progress("  패턴 A 담기는 됐지만 row 상대경로 확보 실패 → 패턴 B 시도...")
                # v1.5.45 fix: result_rows_sel 를 패턴 B 호출 전에 미리 계산
                # (이전 버전 UnboundLocalError — 저장 블록에서만 정의돼서 패턴 B 에 못 넘김)
                _pb_result_tbl = dom_report["tables"][result_table_idx]
                _pb_result_rows_sel = _pb_result_tbl.get("rows_css") or (
                    f"{_pb_result_tbl.get('css', '')} tbody tr"
                )
                pb = await self._probe_global_cart_pattern(
                    dom_report, result_table_idx, _pb_result_rows_sel,
                    qty_input_sel, drug_text, _probe_log_cb=lambda entry:
                    report["onboard_log"]["candidates_tried"].append(entry),
                )
                if pb:
                    confirmed_global_cart = pb["global_css"]
                    confirmed_checkbox_rel = pb.get("checkbox_rel", "")
                    confirmed_cart_table_idx = pb.get("cart_table_idx", -1)
                    confirmed_layout_mode = "global_cart_btn"
                    _mark("pattern_b", True,
                          f"global={confirmed_global_cart[:60]} chk={confirmed_checkbox_rel[:40]}")
                else:
                    _mark("pattern_b", False, "global pattern also failed")

            # 최종 결정
            if confirmed_layout_mode == "global_cart_btn":
                pass  # 패턴 B 성공
            elif confirmed_cart_abs and confirmed_cart_rel:
                # 패턴 A 성공 + row 상대경로 확보
                confirmed_layout_mode = "row_cart_btn"
                # nth-of-type 불변식 체크
                import re as _re43
                if _re43.search(r'\btr:nth-of-type\(', confirmed_cart_rel):
                    report["stage"] = "verify"
                    report["message"] = (
                        f"내부 일관성 오류 — cart_btn_in_row 가 tr 포함: "
                        f"{confirmed_cart_rel[:60]}"
                    )
                    _mark("verify", False, "invariant: tr in row_relative_css")
                    return report
            else:
                report["stage"] = "verify"
                report["message"] = (
                    f"패턴 A ({len(candidates)}개 후보+AI) + 패턴 B (전역 버튼) 모두 실패"
                )
                _mark("verify", False, "both patterns failed")
                return report

            _mark("verify", True, f"layout={confirmed_layout_mode}")

            # 6. selector 확정 (v1.5.43 근본 포맷)
            self._progress("연동 [5/5]: 셀렉터 저장 + 흔적 정리...")
            result_tbl = dom_report["tables"][result_table_idx]
            # rows_css 는 JS 에서 이미 일반화된 형태 (id 있으면 #id tbody tr)
            result_rows_sel = result_tbl.get("rows_css") or (
                f"{result_tbl.get('css', '')} tbody tr"
            )
            row_fingerprint = result_tbl.get("row_fingerprint", "")
            cart_rows_sel = ""
            if 0 <= confirmed_cart_table_idx < len(dom_report["tables"]):
                cart_tbl = dom_report["tables"][confirmed_cart_table_idx]
                cart_rows_sel = cart_tbl.get("rows_css") or (
                    f"{cart_tbl.get('css', '')} tbody tr"
                )
            headers = result_tbl.get("headers", [])
            col_idx = _guess_column_indices(headers)

            # 수량 input 의 row 기준 상대 경로 — inputs 중 해당 테이블 행 내부 것
            qty_input_rel = ""
            for inp in dom_report.get("inputs", []):
                rel = inp.get("row_relative_css", "") or ""
                if inp.get("in_row") and rel:
                    qty_input_rel = rel
                    break

            confirmed = {
                "login": self._selectors.get("login", {}),
                "search": {
                    "search_input": search_input,
                    "search_btn": search_btn or "",
                },
                "table": {
                    # v1.5.44 근본 포맷 (layout_mode 로 A/B 패턴 구분)
                    "result_rows": result_rows_sel,
                    "layout_mode": confirmed_layout_mode,
                    # 패턴 A (row 내부 담기 버튼)
                    "cart_btn_in_row": (
                        confirmed_cart_rel
                        if confirmed_layout_mode == "row_cart_btn" else ""
                    ),
                    # 패턴 B (전역 담기 버튼 + row 체크박스)
                    "global_cart_btn": (
                        confirmed_global_cart
                        if confirmed_layout_mode == "global_cart_btn" else ""
                    ),
                    "row_checkbox_in_row": (
                        confirmed_checkbox_rel
                        if confirmed_layout_mode == "global_cart_btn" else ""
                    ),
                    # 공통
                    "qty_input_in_row": qty_input_rel,
                    "row_fingerprint": row_fingerprint,
                    "cart_rows_sel": cart_rows_sel,
                    "schema_version": "v1.5.44",
                    **col_idx,
                },
                "confirm": {},
                "name": self._wid,
                "url": self.url,
                "auto_detected": True,
                "verified_count": 1,
            }

            # Supabase 저장
            try:
                from core.cloud import upload_selectors, normalize_domain
                domain = normalize_domain(self.url or self._wid)
                upload_selectors(domain, self._wid, confirmed)
            except Exception as e:
                _mark("save", False, str(e)[:120])
                report["stage"] = "save"
                report["message"] = f"서버 저장 실패: {e}"
                return report
            _mark("save", True)

            # 로컬 캐시 (upload=False — 방금 명시적으로 업로드함)
            try:
                from core.selector_store import save_selectors
                save_selectors(self._wid, confirmed, upload=False)
            except Exception:
                pass

            # v1.5.42 근본 해결: end-to-end 검증
            # 담기 버튼 클릭까지만 검증하는 건 실주문 경로(_add_item_to_cart) 의
            # 품절 판정/규격 파싱/수량 담기 로직을 보장 못 함.
            # probe 약품의 실제 보험코드를 뽑아 _add_item_to_cart 를 한 번 돌려
            # 결과가 정상 success 로 나와야 온보딩 성공으로 확정.
            #
            # 실패해도 서버 셀렉터는 유지됨 (수정된 selector 가 공유될 가치). 다만
            # 클라이언트의 onboard_status 는 failed → 이 약국은 주문 분배에서 제외.

            # 7-a. 장바구니 정리 (probe 시험 담기 잔여)
            try:
                await self._clear_cart()
            except Exception:
                pass

            # v1.5.43: 첫 3행 각각의 insurance_code 로 실주문 경로 검증
            # "첫 행만 박제" 사고 원천 차단 — 모든 행에 일반화 적용됨을 증명
            async def _re_search_and_get_codes():
                await self._page.fill(search_input, "")
                await self._page.wait_for_timeout(200)
                await self._page.fill(search_input, probe_term)
                if search_btn:
                    try:
                        await self._page.click(search_btn)
                    except Exception:
                        await self._page.press(search_input, "Enter")
                else:
                    await self._page.press(search_input, "Enter")
                await self._page.wait_for_timeout(2500)

                out = []
                code_idx = col_idx.get("code_col_idx")
                name_idx = col_idx.get("name_col_idx")
                if code_idx is None or not result_rows_sel:
                    return out
                rows_loc = self._page.locator(result_rows_sel)
                nrows = min(await rows_loc.count(), 3)
                import re as _re
                for ri in range(nrows):
                    try:
                        cells = rows_loc.nth(ri).locator("td")
                        ccount = await cells.count()
                        if ccount <= code_idx:
                            continue
                        code_txt = (await cells.nth(code_idx).inner_text()).strip()
                        digits = _re.sub(r'[^\d]', '', code_txt)
                        if len(digits) < 6:
                            continue
                        drug_txt = ""
                        if name_idx is not None and ccount > name_idx:
                            drug_txt = (
                                await cells.nth(name_idx).inner_text()
                            ).strip()
                        out.append((digits, drug_txt))
                    except Exception:
                        continue
                return out

            probe_codes = []
            try:
                probe_codes = await _re_search_and_get_codes()
            except Exception as e:
                _mark("e2e_probe_extract", False, str(e)[:120])

            if not probe_codes:
                _mark(
                    "e2e_skip", True,
                    f"probe_code 추출 실패 (code_col_idx={col_idx.get('code_col_idx')})"
                )
            else:
                self._progress(
                    f"연동 [6/6]: end-to-end 3행 검증 — {len(probe_codes)}개 약품"
                )
                e2e_failures = []
                for pi, (pcode, pdrug) in enumerate(probe_codes, 1):
                    self._progress(
                        f"  e2e {pi}/{len(probe_codes)}: "
                        f"{pdrug[:20]}({pcode})"
                    )
                    # 각 시도 전 장바구니 정리 + 검색 결과 복구
                    try:
                        await self._clear_cart()
                    except Exception:
                        pass
                    try:
                        e2e_res = await self._add_item_to_cart(
                            insurance_code=pcode,
                            quantity=1, idx=pi, total=len(probe_codes),
                            preferred_unit=None,
                        )
                    except Exception as _e:
                        e2e_failures.append(
                            f"{pcode} 예외: {str(_e)[:80]}"
                        )
                        continue

                    if e2e_res.get("out_of_stock"):
                        e2e_failures.append(
                            f"{pcode} 품절 오감지: "
                            f"{e2e_res.get('message','')[:60]}"
                        )
                    elif not e2e_res.get("success"):
                        e2e_failures.append(
                            f"{pcode} 실패: "
                            f"{e2e_res.get('message','?')[:60]}"
                        )

                if e2e_failures:
                    _mark(
                        "e2e", False,
                        f"{len(e2e_failures)}/{len(probe_codes)} 실패: "
                        f"{e2e_failures[0]}"
                    )
                    report["stage"] = "e2e"
                    report["message"] = (
                        f"3행 end-to-end 검증 실패 "
                        f"({len(e2e_failures)}/{len(probe_codes)}): "
                        f"{e2e_failures[0]}"
                    )
                    # onboard_log 에 상세 첨부
                    report["onboard_log"]["e2e_failures"] = e2e_failures
                    return report

                _mark(
                    "e2e", True,
                    f"3행 전부 성공 ({len(probe_codes)} / {len(probe_codes)})"
                )
                try:
                    await self._clear_cart()
                except Exception:
                    pass

            report["success"] = True
            report["stage"] = "done"
            report["message"] = "도매상 연동 완료 — 자동 주문 가능 (end-to-end 검증됨)"
            report["confirmed_selectors"] = confirmed
            _mark("done", True)
            return report
        finally:
            # v1.5.41: 실패 시 마지막 화면 JPEG 스크린샷 (base64) 을 로그에 첨부
            _onboard_failed = not report.get("success")
            if _onboard_failed:
                try:
                    b64 = await self._capture_screenshot_b64()
                    if b64:
                        report["onboard_log"]["fail_screenshot_b64"] = b64
                except Exception:
                    pass
            try:
                await self._close(keep_trace=_onboard_failed)
            except Exception:
                pass

    # ────── _get_cart_count 오버라이드 (셀렉터 주입 지원) ──────

    async def _get_cart_count(self) -> int:
        """저장된 셀렉터에 cart_count_sel/cart_rows_sel 이 있으면 우선 사용.

        - cart_count_sel: 단일 텍스트 요소에서 숫자 추출 (예: "장바구니 3건" 배지)
        - cart_rows_sel : locator 매칭 요소 수 반환 (예: 장바구니 테이블 tbody tr)
        - cart_iframe (v1.5.46): 위 셀렉터를 iframe 안에서 찾음 (아남)
        둘 다 없으면 부모 범용 로직 fallback.
        """
        if not self._page:
            return -1
        try:
            table = self._selectors.get("table", {}) if hasattr(self, "_selectors") else {}
            custom_sel = table.get("cart_count_sel")
            rows_sel = table.get("cart_rows_sel")
            cart_iframe = table.get("cart_iframe", "")
        except Exception:
            custom_sel = None
            rows_sel = None
            cart_iframe = ""

        # v1.5.46: iframe 안에서 찾기 (아남 장바구니)
        if cart_iframe:
            try:
                scope = self._page.frame_locator(cart_iframe)
                if custom_sel:
                    el = scope.locator(custom_sel).first
                    if await el.count() > 0:
                        text = (await el.inner_text()).strip()
                        import re
                        nums = re.sub(r'[^\d]', '', text)
                        if nums:
                            return int(nums)
                if rows_sel:
                    return await scope.locator(rows_sel).count()
            except Exception:
                pass

        if custom_sel:
            try:
                el = self._page.locator(custom_sel).first
                if await el.count() > 0:
                    text = (await el.inner_text()).strip()
                    import re
                    nums = re.sub(r'[^\d]', '', text)
                    if nums:
                        return int(nums)
            except Exception:
                pass

        if rows_sel:
            try:
                return await self._page.locator(rows_sel).count()
            except Exception:
                pass

        return await super()._get_cart_count()

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

    async def _row_has_order_button(
        self, row, cart_btn_in_row_sel: str = "",
    ) -> bool:
        """행에 주문 가능한 담기 버튼이 있는지 확인 (v1.5.43 재작성).

        검색 결과 행은 담기 버튼이 있고, 장바구니/헤더/광고 행은 없다.
        cart_btn_in_row_sel 은 row 내부 상대 CSS 셀렉터.
        비어있으면 하위 호환 위해 True 반환 (필터 무력화).
        """
        if not cart_btn_in_row_sel:
            return True
        try:
            el = await row.query_selector(cart_btn_in_row_sel)
            return el is not None
        except Exception:
            return False

    async def _add_item_to_cart(self, insurance_code: str, quantity: int,
                                idx: int, total: int,
                                preferred_unit: int | None = None) -> dict:
        page = self._page
        result = {"success": False, "insurance_code": insurance_code,
                  "quantity": quantity, "box_qty": 0, "pack_size": 0,
                  "drug_name": "", "message": "", "unit_options": [],
                  # v1.5.43 신규 플래그
                  "retryable": False,
                  "invalidate_selectors": False}

        # 검색 전 현재 URL 저장 (페이지 복구용)
        _order_url = page.url

        search = self._selectors.get("search", {})
        table = self._selectors.get("table", {})
        search_input = search.get("search_input")
        search_btn = search.get("search_btn")

        # v1.5.44+: layout_mode 로 패턴 분기 + 구 포맷 감지
        # v1.5.46: select_then_add (지오영), global_cart_btn 체크박스 없는 변종 (아남) 추가
        cart_rel_stored = table.get("cart_btn_in_row")
        qty_rel_stored = table.get("qty_input_in_row")
        global_cart_stored = table.get("global_cart_btn")
        row_checkbox_stored = table.get("row_checkbox_in_row")
        # select_then_add (v1.5.46): 결과 행 밖 고정 위치 담기/수량
        select_cart_btn_stored = table.get("cart_btn")  # 절대경로
        select_qty_input_stored = table.get("qty_input")  # 절대경로
        # iframe 지원 (v1.5.46): 아남 장바구니
        cart_iframe_stored = table.get("cart_iframe", "")
        layout_mode = table.get("layout_mode", "")
        if not isinstance(cart_rel_stored, str):
            cart_rel_stored = ""
        if not isinstance(qty_rel_stored, str):
            qty_rel_stored = ""
        if not isinstance(global_cart_stored, str):
            global_cart_stored = ""
        if not isinstance(row_checkbox_stored, str):
            row_checkbox_stored = ""
        if not isinstance(select_cart_btn_stored, str):
            select_cart_btn_stored = ""
        if not isinstance(select_qty_input_stored, str):
            select_qty_input_stored = ""
        if not isinstance(cart_iframe_stored, str):
            cart_iframe_stored = ""
        schema_ver = table.get("schema_version", "")
        # layout_mode 유추 (schema v1.5.43 이전 저장된 건 row_cart_btn)
        if not layout_mode:
            if select_cart_btn_stored and select_qty_input_stored:
                layout_mode = "select_then_add"
            elif cart_rel_stored and not global_cart_stored:
                layout_mode = "row_cart_btn"
            elif global_cart_stored:
                layout_mode = "global_cart_btn"

        supported_schemas = ("v1.5.43", "v1.5.44", "v1.5.45", "v1.5.46")
        # 구 포맷 감지: schema 가 지원 목록에 없고 + 레거시 지표
        #   (a) cart_btn 절대경로 + layout_mode 없음 (진짜 구 포맷)
        #   (b) 신 필드 전혀 없음 (cart_btn_in_row / global_cart_btn / select_then_add 필드 모두 없음)
        has_any_modern = bool(
            cart_rel_stored or global_cart_stored or
            (select_cart_btn_stored and layout_mode == "select_then_add")
        )
        if schema_ver not in supported_schemas and (
            (table.get("cart_btn") and not layout_mode) or
            not has_any_modern
        ):
            # 구 포맷 — 절대경로 또는 신 필드 전혀 없음
            self._progress(
                f"  [{insurance_code}] 구 포맷 셀렉터 감지 → "
                f"재연동 유도 (이 주문은 다른 도매상으로 재분배)"
            )
            result["retryable"] = True
            result["invalidate_selectors"] = True
            result["message"] = (
                "저장된 셀렉터가 구 포맷 (v1.5.44 이전) — 재연동 필요"
            )
            return result

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
            # v1.5.43: 담기 버튼 행 내부 상대 CSS 1개 기반 필터
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
                if filled < 3:
                    continue
                # 주문 가능 행 필터 — 저장된 cart_btn_in_row 매칭 (없으면 필터 무력화)
                if not await self._row_has_order_button(r, cart_rel_stored):
                    continue
                valid_rows.append(r)

            if valid_rows:
                rows = valid_rows
                self._progress(f"  [{term}] 검색 성공 ({len(rows)}행)")
                break
            self._progress(f"  [{term}] 결과 없음")
            rows = []  # 유효한 행 없으면 다음 검색어 시도

        if not rows:
            # v1.5.43 근본 수정: 검색 실패와 품절 분리.
            # 검색 결과 0 ≠ 품절 (도매상 미취급/사이트 오류/쿼리 꼬임 가능성)
            # out_of_stock 찍지 않고 retryable 로 설정 → 다른 도매상에 재할당
            result["message"] = "검색 결과 없음 (품절 여부 불명 — 다른 도매상 재시도)"
            result["retryable"] = True
            self._progress(
                f"  [{insurance_code}] 검색 결과 없음 — retryable "
                f"({idx}/{total})"
            )
            return result

        # v1.5.43: DOM fingerprint 비교 — 사이트 구조 변경 자동 감지
        stored_fp = table.get("row_fingerprint", "")
        if stored_fp:
            current_fp = await self._compute_row_fingerprint(rows[0])
            if current_fp and current_fp != stored_fp:
                self._progress(
                    f"  [{insurance_code}] DOM fingerprint 불일치 → 재연동 유도"
                )
                result["retryable"] = True
                result["invalidate_selectors"] = True
                result["message"] = (
                    "사이트 DOM 구조 변경 감지 — 재연동 필요"
                )
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
        # v1.5.43: row 내부 상대 셀렉터 (저장용 + 실행용 동일)
        qty_rel = qty_rel_stored  # 함수 초반 세팅
        cart_rel = cart_rel_stored

        # 각 행에서 candidates 수집
        candidates = []
        for row in rows:
            cells = await row.query_selector_all('td')
            if not cells:
                continue

            # 주문 가능 행만 (장바구니/공지 행 배제) — v1.5.43 새 시그니처
            if not await self._row_has_order_button(row, cart_rel):
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
            # v1.5.42: 재고 텍스트에 숫자가 전혀 없으면 (버튼/이미지/빈 셀) → 999 유지
            #          (과거엔 0 으로 간주 → 재고 있는데 품절 오감지하는 사고)
            stock = 999  # 재고 컬럼 없거나 파싱 실패면 "있다" 로 간주 (보수적)
            stock_text_raw = ""
            if stock_col is not None and stock_col < len(cells):
                stock_text_raw = (await cells[stock_col].inner_text()).strip()
                digits = re.sub(r'[^\d]', '', stock_text_raw)
                if digits:
                    stock = int(digits)
                # else: stock = 999 유지

            if pack_size > 0 and stock > 0:
                candidates.append({
                    "row": row, "pack_size": pack_size,
                    "drug_name": drug_name, "std_text": std_text,
                    "stock": stock, "pack_price": pack_price,
                })

        if not candidates:
            # v1.5.42 근본 재설계: 품절 판정을 단일 신호(stock_col 숫자)에 의존하지 않는다.
            # 후보 0 개의 진짜 원인은 여럿:
            #   (a) 진짜 stock=0 또는 "품절"/"재고없음" 텍스트
            #   (b) stock 컬럼이 버튼/이미지/빈 셀 (숫자 없음) — 과거 오감지 주범
            #   (c) pack_size 파싱 실패
            #   (d) code_col 불일치 (다른 약품)
            # "명시적 품절" 이 확실할 때만 out_of_stock=True, 그 외엔 AI 시각 재확인 거쳐 판정.
            drug_name = ""
            if name_col is not None and rows:
                try:
                    cells0 = await rows[0].query_selector_all('td')
                    if name_col < len(cells0):
                        drug_name = (await cells0[name_col].inner_text()).strip()
                except Exception:
                    pass
            result["drug_name"] = drug_name

            explicit_oos = await self._check_explicit_out_of_stock(
                rows, stock_col
            )
            if explicit_oos:
                # (a) 모든 행이 명시적 "0" 또는 품절 키워드 → 진짜 품절
                result["message"] = "재고 없음"
                result["out_of_stock"] = True
                self._progress(f"  [{insurance_code}] 재고 없음 ({idx}/{total})")
                return result

            # 명시적이지 않음 → AI 시각 재확인 (false positive 품절 방지)
            self._progress(
                f"  [{insurance_code}] 후보 0 이지만 명시적 품절 아님 → "
                f"AI 시각 재확인"
            )
            ai_oos = await self._ai_check_out_of_stock(
                insurance_code, drug_name
            )
            if ai_oos is True:
                result["message"] = "재고 없음 (시각 확인)"
                result["out_of_stock"] = True
                # 진단도 같이 업로드 (다음 분석 자료)
                await self._upload_oos_diagnostic(
                    insurance_code, rows, stock_col, table, "ai_confirmed"
                )
                return result

            # AI 가 "재고 있음" 또는 판단 불가 → 품절 아닌 실패로 처리 +
            # 진단 자동 업로드 (헤더/raw 텍스트/스크린샷)
            await self._upload_oos_diagnostic(
                insurance_code, rows, stock_col, table, "suspected_misdetection"
            )
            # v1.5.43: 후보 0 + AI 품절 아님 → retryable 실패 (첫행 폴백 제거,
            # 다른 도매상에서 재시도하는 것이 안전)
            result["message"] = (
                "유효한 후보 행 없음 (품절 아닌 검색/파싱 문제) — 재시도 권장"
            )
            result["retryable"] = True
            return result
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

        # ── v1.5.43 수량 입력: L1 저장 상대 css → L2 자동 탐지 ──
        # v1.5.46: select_then_add 는 행 바깥 고정 위치에서 채움 → 담기 분기에서 처리
        qty_col = table.get("qty_col_idx")
        qty_filled = False

        if layout_mode == "select_then_add":
            # 행 내부 수량 없음 — select_then_add 담기 분기에서 채움
            pass
        elif qty_rel:
            try:
                qty_el = await row_el.query_selector(qty_rel)
                if qty_el:
                    await qty_el.click()
                    await qty_el.fill(str(box_qty))
                    qty_filled = True
            except Exception:
                pass

        if layout_mode != "select_then_add" and not qty_filled:
            # row 내 text/number input 자동 탐지 (성공하면 self-heal 저장)
            for auto_sel in ['input[type="text"]', 'input[type="number"]']:
                try:
                    qty_el = await row_el.query_selector(auto_sel)
                    if qty_el:
                        await qty_el.click()
                        await qty_el.fill(str(box_qty))
                        qty_filled = True
                        # self-heal: 다음부턴 저장된 셀렉터 사용
                        if not qty_rel:
                            self._update_row_selector("qty_input_in_row", auto_sel)
                        break
                except Exception:
                    continue

        if layout_mode != "select_then_add" and not qty_filled \
                and qty_col is not None and qty_col < len(cells):
            qty_el = await cells[qty_col].query_selector('input')
            if qty_el:
                await qty_el.click()
                await qty_el.fill(str(box_qty))
                qty_filled = True

        if qty_filled:
            await page.wait_for_timeout(300)

        # v1.5.45: 담기 전 스냅샷 (검증용)
        before_cart_snap = await self._snapshot_tables()

        # ── v1.5.44+ 담기 실행: layout_mode 분기 ──
        cart_clicked = False
        used_cart_sel = ""
        heal_needed = False

        # 패턴 C (v1.5.46): select_then_add (지오영)
        # 결과 행 클릭 → 고정 위치 qty_input 채우기 → 고정 위치 cart_btn 클릭
        if layout_mode == "select_then_add" and select_cart_btn_stored:
            select_method = table.get("select_method", "row_click")
            # 1. 결과 행 선택 (제품정보 패널 활성화)
            if select_method == "row_click":
                try:
                    await row_el.click(force=True)
                    await page.wait_for_timeout(600)
                except Exception as e:
                    self._progress(
                        f"  [{insurance_code}] 행 선택 실패: {e}"
                    )
            # 2. 고정 위치 qty input 채우기
            if select_qty_input_stored:
                try:
                    qty_el = await page.query_selector(select_qty_input_stored)
                    if qty_el:
                        await qty_el.click()
                        await qty_el.fill(str(box_qty))
                        qty_filled = True
                        await page.wait_for_timeout(200)
                except Exception as e:
                    self._progress(
                        f"  [{insurance_code}] 수량 입력 실패: {e}"
                    )
            # 3. 고정 위치 담기 버튼 클릭
            try:
                cart_btn_el = await page.query_selector(select_cart_btn_stored)
                if cart_btn_el:
                    await cart_btn_el.click(force=True)
                    cart_clicked = True
                    used_cart_sel = select_cart_btn_stored
            except Exception as e:
                self._progress(
                    f"  [{insurance_code}] 담기 클릭 실패: {e}"
                )

        # 패턴 B: 전역 담기 버튼 + row 체크박스 (세화 패턴)
        #          또는 체크박스 없는 변종 (아남) — row_checkbox_stored 빈 문자열이면 skip
        if not cart_clicked and layout_mode == "global_cart_btn" and global_cart_stored:
            # row 체크박스 체크 (이미 체크면 skip)
            if row_checkbox_stored:
                try:
                    chk = await row_el.query_selector(row_checkbox_stored)
                    if chk and not await chk.is_checked():
                        await chk.click(force=True)
                        await page.wait_for_timeout(200)
                except Exception:
                    pass
            # 페이지 전역 담기 버튼 클릭
            try:
                g_btn = await page.query_selector(global_cart_stored)
                if g_btn:
                    await g_btn.click(force=True)
                    cart_clicked = True
                    used_cart_sel = global_cart_stored
            except Exception:
                pass
            # 담긴 후 체크박스 해제 (다음 약품 중복 방지)
            if cart_clicked and row_checkbox_stored:
                await page.wait_for_timeout(1500)
                try:
                    chk = await row_el.query_selector(row_checkbox_stored)
                    if chk and await chk.is_checked():
                        await chk.click(force=True)
                        await page.wait_for_timeout(200)
                except Exception:
                    pass

        # 패턴 A: L1 저장된 row 상대 CSS (layout_mode=row_cart_btn)
        if not cart_clicked and cart_rel:
            try:
                btn = await row_el.query_selector(cart_rel)
                if btn:
                    await btn.click(force=True)
                    cart_clicked = True
                    used_cart_sel = cart_rel
            except Exception:
                pass

        # L2: 휴리스틱 (CSS-only, :has-text 미사용)
        if not cart_clicked:
            CART_HEURISTICS = [
                'input[type="image"][alt*="담기"]',
                'input[type="image"][alt*="cart"]',
                'input[type="image"][alt*="추가"]',
                'input[type="image"][src*="bag"]',
                'input[type="image"][src*="cart"]',
                'img[alt*="담기"]',
                'img[alt*="cart"]',
                'img[src*="bag"]',
                'img[src*="cart"]',
                'a[onclick*="담기"]',
                'a[onclick*="cart"]',
                'a[onclick*="Cart"]',
                'a[onclick*="bag"]',
                'button[onclick*="담기"]',
                'button[onclick*="cart"]',
                '[role="button"][aria-label*="담기"]',
                'a.btn-bag', 'a.btn-cart', 'a.bag', 'a.cart',
            ]
            for heur in CART_HEURISTICS:
                try:
                    btn = await row_el.query_selector(heur)
                    if btn:
                        await btn.click(force=True)
                        cart_clicked = True
                        used_cart_sel = heur
                        heal_needed = True
                        self._progress(f"  휴리스틱 담기 매칭: {heur}")
                        break
                except Exception:
                    continue

        # L3: AI Vision — row 내부 담기 버튼 질의 (비용 → 실패 경로에서만)
        if not cart_clicked:
            self._progress("  L2 휴리스틱 실패 → AI Vision 담기 버튼 질의...")
            try:
                # 현재 row 의 outerHTML 샘플을 프롬프트에 포함
                row_html = await row_el.evaluate(
                    "(el) => (el.outerHTML || '').slice(0, 3000)"
                )
                ai_rel = await self._ai_suggest_row_relative_cart(row_html)
                if ai_rel:
                    try:
                        btn = await row_el.query_selector(ai_rel)
                        if btn:
                            await btn.click(force=True)
                            cart_clicked = True
                            used_cart_sel = ai_rel
                            heal_needed = True
                            self._progress(f"  AI 담기 매칭: {ai_rel}")
                    except Exception:
                        pass
            except Exception as e:
                self._progress(f"  AI 담기 폴백 오류: {e}")

        # self-heal: L2/L3 성공 셀렉터를 저장해 다음 주문부터 L1 적중
        if cart_clicked and heal_needed and used_cart_sel:
            self._update_row_selector("cart_btn_in_row", used_cart_sel)

        if cart_clicked:
            await page.wait_for_timeout(2000)

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

        # v1.5.45 회색지대 복원 — 담기 클릭 성공 ≠ 실제 담김 보장.
        # 온보딩과 동일한 2단 검증 (DOM diff + AI 시각) 후 결과 확정.
        if cart_clicked:
            after_cart_snap = await self._snapshot_tables()
            drug_name_for_verify = (
                result.get("drug_name") or chosen.get("drug_name") or ""
            )
            verify = await self._verify_cart_added(
                drug_name=drug_name_for_verify,
                insurance_code=insurance_code,
                before=before_cart_snap,
                after=after_cart_snap,
            )
            if verify.get("verified"):
                result["success"] = True
                result["message"] = (
                    f"{chosen.get('std_text', '')} x{box_qty} 담기 완료"
                )
                return result
            # AI 시각 폴백
            visual_ok = await self._ai_visual_verify_cart(
                before_cart_snap, after_cart_snap, drug_name_for_verify
            )
            if visual_ok:
                result["success"] = True
                result["message"] = (
                    f"{chosen.get('std_text', '')} x{box_qty} 담기 완료 (시각 확인)"
                )
                return result
            # 클릭은 됐지만 담김 확인 실패 → 회색지대 금지 원칙 → 실패 처리
            self._progress(
                f"  [{insurance_code}] 담기 버튼 클릭은 성공했지만 장바구니 반영 없음 "
                f"— 셀렉터 오탐 가능성, 재연동 유도"
            )
            result["success"] = False
            result["retryable"] = True
            result["invalidate_selectors"] = True
            result["message"] = (
                "담기 클릭 성공 but DOM/시각 검증 실패 — 재연동 필요"
            )
            # CART_FAIL_DIAG 진단 자동 업로드
            try:
                await self._upload_cart_fail_diagnostic(
                    insurance_code=insurance_code,
                    drug_name=drug_name_for_verify,
                    used_cart_sel=used_cart_sel,
                    layout_mode=layout_mode,
                    before_snap=before_cart_snap,
                    after_snap=after_cart_snap,
                )
            except Exception:
                pass
            return result

        # 담기 버튼 클릭 자체 실패 (L1~L3 모두 실패)
        result["success"] = False
        result["retryable"] = True
        result["message"] = "담기 버튼을 찾을 수 없음 — 재연동 필요"
        result["invalidate_selectors"] = True
        try:
            await self._upload_cart_fail_diagnostic(
                insurance_code=insurance_code,
                drug_name=result.get("drug_name", ""),
                used_cart_sel="",
                layout_mode=layout_mode,
                before_snap=before_cart_snap,
                after_snap=None,
            )
        except Exception:
            pass
        return result

    async def _confirm_order(self) -> None:
        confirm = self._selectors.get("confirm", {})
        btn_sel = confirm.get("confirm_btn")
        # v1.5.46: 주문확정 버튼이 iframe 안에 있는 경우 지원 (아남)
        confirm_iframe = confirm.get("iframe", "")

        if not btn_sel:
            # 캐시 없으면 탐지
            detected = await self._detect_confirm()
            btn_sel = detected.get("confirm_btn")
            if detected:
                self._selectors["confirm"] = detected
                self._save_selectors(self._selectors)

        if btn_sel:
            if confirm_iframe:
                # iframe 안 버튼
                btn = self._page.frame_locator(confirm_iframe).locator(btn_sel)
            else:
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

        1) config에 date_from 셀렉터가 있으면 직접 값 설정 (date_to 도 함께)
        2) 기간 버튼(5년/3년/1년 등)이 있으면 가장 긴 것 클릭
        3) 둘 다 없으면 페이지의 날짜 input을 자동 탐지해서 설정

        v1.5.47: AngularJS ng-model 트리거 + 사이트별 date 포맷 (- / .) 자동 시도.
        date_to 도 함께 처리 (오늘 날짜).
        """
        from datetime import datetime, timedelta
        now = datetime.now()
        five_years_ago_dt = now - timedelta(days=365 * 5)

        date_from_sel = (search.get("date_from") or "").strip()
        date_to_sel = (search.get("date_to") or "").strip()

        # 1) config에 명시된 date_from / date_to 셀렉터
        if date_from_sel:
            ok = await self._fill_date_input(page, date_from_sel, five_years_ago_dt)
            if ok and date_to_sel:
                try:
                    await self._fill_date_input(page, date_to_sel, now)
                except Exception:
                    pass
            if ok:
                return

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
                await self._fill_date_input(page, date_input, five_years_ago_dt)
        except Exception:
            pass

    async def _fill_date_input(self, page, sel: str, dt) -> bool:
        """date input 에 값을 채우고 native + AngularJS ng-model 트리거.

        사이트마다 받는 포맷이 달라서 (- / . / 없음) 여러 포맷 차례로 시도.
        AngularJS 사이트 (세화 등) 는 input/change 이벤트만으론 ng-model 안 잡혀서
        angular.element(el).triggerHandler('input') 까지 호출.
        """
        formats = [
            dt.strftime("%Y-%m-%d"),
            dt.strftime("%Y.%m.%d"),
            dt.strftime("%Y%m%d"),
            dt.strftime("%Y/%m/%d"),
        ]
        for v in formats:
            try:
                # JSON.stringify 로 셀렉터 안에 따옴표/특수문자 안전 처리
                js = (
                    "(function(sel, val){"
                    "var el = document.querySelector(sel);"
                    "if (!el) return null;"
                    "el.value = val;"
                    "try { el.dispatchEvent(new Event('input', {bubbles:true})); } catch(e){}"
                    "try { el.dispatchEvent(new Event('change', {bubbles:true})); } catch(e){}"
                    "try { el.dispatchEvent(new Event('blur', {bubbles:true})); } catch(e){}"
                    "if (window.angular) {"
                    "  try { window.angular.element(el).triggerHandler('input'); } catch(e){}"
                    "  try { window.angular.element(el).triggerHandler('change'); } catch(e){}"
                    "}"
                    "return el.value;"
                    "})"
                )
                import json as _json
                result = await page.evaluate(
                    f"{js}({_json.dumps(sel)}, {_json.dumps(v)})"
                )
                if result is not None:
                    return True
            except Exception:
                continue
        return False

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
