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
        return load_selectors(self._wid)

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
        """약품 검색 관련 셀렉터를 자동 탐지한다."""
        page = self._page
        selectors = {}

        # 검색 입력 필드
        search_candidates = [
            'input#txt_product',
            'input#P_SRH_KEY',
            'input[placeholder*="보험코드"]',
            'input[placeholder*="품목명"]',
            'input[placeholder*="약품"]',
            'input[placeholder*="상품"]',
            'input[placeholder*="검색"]',
            'input.search-input', 'input.product-input',
            'input[name="searchWord"]', 'input[name="keyword"]',
        ]
        for sel in search_candidates:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                selectors["search_input"] = sel
                self._progress(f"  검색 필드 탐지: {sel}")
                break

        # 검색 버튼 — 아이콘 버튼(텍스트 없음)을 우선 탐지
        btn_candidates = [
            'button.btn_search', 'button.search-btn',
            'button[onclick*="Srh"]', 'button[onclick*="search"]',
            'button:has-text("조회")',
            'input[type="submit"]',
        ]
        for sel in btn_candidates:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                selectors["search_btn"] = sel
                self._progress(f"  검색 버튼 탐지: {sel}")
                break

        return selectors

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

        # 4. 담기/추가 버튼 — 행 내부 먼저
        cart_candidates = [
            'button:has-text("추가")',
            'button:has-text("담기")',
            'button:has-text("장바구니")',
            'a:has-text("추가")',
            'a:has-text("담기")',
            'input[type="button"][value*="추가"]',
            'input[type="button"][value*="담기"]',
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

        # 5. 가격 컬럼이 있으면 기록
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

    # ────── 전체 사이트 분석 ──────

    async def analyze_site(self, test_code: str = "646201260",
                           headless: bool = True) -> dict:
        """사이트 구조를 분석하고 셀렉터를 캐시한다.

        Args:
            test_code: 검색 테스트용 보험코드
            headless: 브라우저 표시 여부
        """
        self._progress(f"사이트 분석 시작: {self.url}")
        all_selectors = {"url": self.url, "name": self.name}

        try:
            await self._launch(headless=headless)
            page = self._page

            # 다이얼로그 자동 수락
            page.on("dialog", lambda d: d.accept())

            # 1. 로그인 페이지 분석
            self._progress("1/4 로그인 폼 분석 중...")
            await page.goto(self.url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            await self._screenshot(f"generic_{self._wid}_01_before_login.png")

            login_sel = await self._detect_login()
            all_selectors["login"] = login_sel

            if not login_sel.get("id_input") or not login_sel.get("pw_input"):
                self._progress("로그인 폼 탐지 실패")
                return all_selectors

            # 2. 로그인 시도
            self._progress("2/4 로그인 시도 중...")
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
            await self._screenshot(f"generic_{self._wid}_02_after_login.png")

            # 3. 검색 분석
            self._progress("3/4 검색 기능 분석 중...")
            search_sel = await self._detect_search()
            all_selectors["search"] = search_sel

            if search_sel.get("search_input"):
                await page.fill(search_sel["search_input"], test_code)
                if search_sel.get("search_btn"):
                    await page.click(search_sel["search_btn"])
                await page.wait_for_timeout(3000)
                await self._screenshot(f"generic_{self._wid}_03_search_result.png")

                # 결과 테이블 분석
                table_sel = await self._detect_result_table(test_code)
                all_selectors["table"] = table_sel

            # 4. 주문확정 버튼 분석
            self._progress("4/4 주문확정 버튼 분석 중...")
            confirm_sel = await self._detect_confirm()
            all_selectors["confirm"] = confirm_sel

            # 분석 완료 여부 판정
            required = [
                login_sel.get("id_input"),
                login_sel.get("pw_input"),
                search_sel.get("search_input"),
            ]
            all_selectors["auto_detected"] = all(required)
            status = "성공" if all_selectors["auto_detected"] else "일부 실패"
            self._progress(f"사이트 분석 {status}")

        except Exception as e:
            self._progress(f"사이트 분석 오류: {e}")
            all_selectors["error"] = str(e)
        finally:
            await self._close()

        self._save_selectors(all_selectors)
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

            # 검색 셀렉터가 없으면 탐지
            if not self._selectors.get("search"):
                search_sel = await self._detect_search()
                self._selectors["search"] = search_sel
                self._save_selectors(self._selectors)
        else:
            self._progress("로그인 실패")
            await self._screenshot(f"generic_{self._wid}_login_fail.png")

        return login_success

    async def _add_item_to_cart(self, insurance_code: str, quantity: int,
                                idx: int, total: int,
                                preferred_unit: int | None = None) -> dict:
        page = self._page
        result = {"success": False, "insurance_code": insurance_code,
                  "quantity": quantity, "box_qty": 0, "pack_size": 0,
                  "drug_name": "", "message": "", "unit_options": []}

        search = self._selectors.get("search", {})
        table = self._selectors.get("table", {})
        search_input = search.get("search_input")
        search_btn = search.get("search_btn")

        if not search_input:
            result["message"] = "검색 필드 셀렉터 없음"
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

        # 검색 시도: 보험코드 → 약품명(짧은) 순서
        search_terms = [insurance_code]
        if short_name and short_name != insurance_code and len(short_name) >= 2:
            search_terms.append(short_name)

        self._progress(f"  검색어 목록: {search_terms}")

        rows = []
        row_sel = table.get("result_rows", "table tbody tr")

        for term in search_terms:
            self._progress(f"  [{term}] 검색 시도 중...")
            await page.fill(search_input, '')
            await page.wait_for_timeout(300)
            await page.fill(search_input, term)

            # 검색 실행 — 버튼 클릭 + Enter 이중 시도
            if search_btn:
                try:
                    await page.click(search_btn)
                except Exception:
                    pass
            # 버튼 클릭과 무관하게 항상 Enter도 시도
            # (일부 사이트는 버튼이 탭 전환용이고 Enter가 실제 검색)
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
            # 규격 파싱 실패 — 첫 번째 행으로 폴백
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

        # 담기/추가 버튼 — 셀렉터 또는 컬럼 인덱스로
        cart_col = table.get("cart_col_idx")
        cart_clicked = False

        if cart_btn_sel:
            btn = await row_el.query_selector(cart_btn_sel)
            if btn:
                await btn.click()
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
