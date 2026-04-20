"""시각 피드백 에이전트 — 도매상 사이트를 단계별로 보면서 셀렉터를 찾는다.

매 단계(로그인→검색→테이블→담기→확정)마다:
1. 스크린샷 + DOM 추출 → Claude Vision에 전송
2. AI가 셀렉터/액션 응답
3. 실행 → 확인 스크린샷 → AI가 성공 여부 판단
4. 실패 시 AI 피드백을 다음 시도에 반영

사용법:
    agent = VisualAgent(api_key, wid)
    selectors = await agent.run(page, url, user_id, password, progress)
"""

import asyncio
import base64
import json
import os
import re
from dataclasses import dataclass, field

from core import paths

MAX_RETRIES = 3  # 단계별 최대 재시도
SEARCH_TERMS = [
    ("645601261", "아세젠"),
    ("643501890", "타이레놀"),
    ("646201260", "아스피린"),
]

SYSTEM_PROMPT = """당신은 한국 약품 도매상 웹사이트 자동화 전문가입니다.
스크린샷과 DOM 뼈대를 보고 Playwright용 CSS 셀렉터를 찾아야 합니다.

규칙:
- 반드시 JSON만 응답. 다른 텍스트 금지.
- Playwright CSS 셀렉터 문법 사용: :has-text("텍스트"), :nth-child() 등
- :contains()는 사용 금지! 대신 :has-text() 사용
- onclick, javascript: 등 JS 속성을 셀렉터 값에 포함하지 마세요
- 가장 안정적인 셀렉터 선택: id > name > class > :has-text()
- 한국어 사이트임을 감안
- 찾을 수 없으면 null"""


@dataclass
class StepResult:
    success: bool = False
    selectors: dict = field(default_factory=dict)
    observation: str = ""
    error: str = ""
    retry_hint: str = ""


class VisualAgent:
    """단계별 시각 피드백으로 도매상 셀렉터를 탐지하는 에이전트."""

    def __init__(self, api_key: str = "", wid: str = ""):
        self._api_key = api_key  # 로컬 API 키 (없으면 Edge Function 사용)
        self._wid = wid
        self._step_history: list[str] = []  # 이전 단계 요약
        # Supabase Edge Function 설정 로드
        self._cloud_url = ""
        self._cloud_key = ""
        try:
            from core.cloud import _load_cloud_config
            self._cloud_url, self._cloud_key = _load_cloud_config()
        except Exception:
            pass

    async def run(self, page, url: str, user_id: str, password: str,
                  progress=None) -> dict:
        """전체 분석 루프를 실행한다.

        Returns:
            완성된 셀렉터 dict. 실패한 단계는 빈 dict.
        """
        self._page = page
        self._progress = progress or (lambda msg: print(f"[VisualAgent] {msg}"))
        all_selectors = {}

        # 1단계: 로그인
        self._log("1/5 로그인 분석 중...")
        login_result = await self._step_login(url, user_id, password)
        all_selectors["login"] = login_result.selectors
        if not login_result.success:
            self._log(f"로그인 실패: {login_result.error}")
            return all_selectors

        # 2단계: 검색
        self._log("2/5 검색 기능 분석 중...")
        search_result = await self._step_search()
        all_selectors["search"] = search_result.selectors
        if not search_result.success:
            self._log(f"검색 분석 실패: {search_result.error}")
            return all_selectors

        # 3단계: 테이블 구조
        self._log("3/5 검색 결과 테이블 분석 중...")
        table_result = await self._step_table(search_result.selectors)
        all_selectors["table"] = table_result.selectors
        if not table_result.success:
            self._log(f"테이블 분석 실패: {table_result.error}")
            # 부분 성공이라도 반환

        # 4단계: 주문확정 버튼 (장바구니 페이지에서)
        self._log("4/5 주문확정 버튼 분석 중...")
        confirm_result = await self._step_confirm()
        all_selectors["confirm"] = confirm_result.selectors

        self._log("분석 완료!")
        return all_selectors

    # ────── 단계별 구현 ──────

    async def _step_login(self, url: str, user_id: str, password: str) -> StepResult:
        """1단계: 로그인 폼 탐지 → 로그인 실행 → 검증."""
        page = self._page

        # 페이지 이동
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        retry_hint = ""
        for attempt in range(MAX_RETRIES):
            # AI에게 로그인 폼 찾기 요청
            screenshot, dom = await self._capture(page)
            prompt = f"""현재 단계: 로그인 폼 탐지
목표: 이 페이지에서 로그인 폼의 CSS 셀렉터를 찾으세요.
{f"이전 시도 피드백: {retry_hint}" if retry_hint else ""}

중요 규칙:
- DOM 뼈대에 실제 존재하는 요소만 사용하세요. 존재하지 않는 클래스명을 지어내지 마세요.
- 로그인 버튼은 button:has-text("로그인") 또는 input[type="submit"] 형태가 일반적입니다.
- id가 있으면 #id, 없으면 :has-text() 사용

찾아야 할 셀렉터:
- id_input: 아이디/ID 입력 필드
- pw_input: 비밀번호 입력 필드
- login_btn: 로그인 버튼 (없으면 null — Enter 키로 대체)

DOM 뼈대:
{dom}

응답 형식:
{{"observation": "페이지 상태 설명", "selectors": {{"id_input": "...", "pw_input": "...", "login_btn": null}}, "confidence": 0.9}}"""

            response = await self._ask_ai(prompt, screenshot)
            if not response:
                retry_hint = "AI 응답 없음"
                continue

            selectors = response.get("selectors", {})
            if not selectors.get("id_input") or not selectors.get("pw_input"):
                retry_hint = f"AI 관찰: {response.get('observation', '셀렉터 못 찾음')}"
                continue

            # 보안 검증
            if not self._validate(selectors):
                retry_hint = "보안 검증 실패"
                continue

            # 로그인 실행
            try:
                await page.fill(selectors["id_input"], user_id)
                await page.fill(selectors["pw_input"], password)
                if selectors.get("login_btn"):
                    await page.click(selectors["login_btn"])
                else:
                    await page.press(selectors["pw_input"], "Enter")
                await page.wait_for_timeout(4000)
            except Exception as e:
                retry_hint = f"로그인 실행 오류: {str(e)[:100]}"
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
                continue

            # 로그인 성공 검증
            verify_screenshot, verify_dom = await self._capture(page)
            verify_prompt = f"""이전 액션: 로그인 폼에 ID/PW를 입력하고 제출했습니다.
목표: 로그인이 성공했는지 확인하세요.

확인 사항:
- 페이지가 변경되었는가?
- 로그아웃 버튼이 보이는가?
- 에러 메시지가 보이는가?

DOM 뼈대:
{verify_dom}

응답 형식:
{{"success": true, "observation": "로그인 성공, 메인 페이지로 이동함"}}"""

            verify = await self._ask_ai(verify_prompt, verify_screenshot)
            if verify and verify.get("success"):
                self._step_history.append("로그인 성공")
                return StepResult(success=True, selectors=selectors,
                                  observation=verify.get("observation", ""))
            else:
                obs = verify.get("observation", "") if verify else "검증 응답 없음"
                retry_hint = f"로그인 검증 실패: {obs}"
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)

        return StepResult(success=False, error=retry_hint)

    async def _step_search(self) -> StepResult:
        """2단계: 검색 폼 탐지."""
        page = self._page
        retry_hint = ""

        for attempt in range(MAX_RETRIES):
            screenshot, dom = await self._capture(page)
            history = " → ".join(self._step_history)
            prompt = f"""현재 단계: 약품 검색 기능 탐지
이전 단계: {history}
목표: 약품을 검색할 수 있는 입력 필드와 버튼을 찾으세요.
{f"이전 시도 피드백: {retry_hint}" if retry_hint else ""}

중요 규칙:
- DOM 뼈대에 실제 존재하는 요소만 사용하세요. 존재하지 않는 클래스명을 지어내지 마세요.
- 약품 검색 필드를 찾으세요. 거래처/회원 검색이 아닙니다.
- 현재 페이지가 약품 주문 페이지가 아닌 경우(거래처 관리, 메인 대시보드 등), needs_navigation으로 주문/검색 페이지 링크를 찾으세요.
- "주문", "약품", "상품", "발주" 관련 메뉴가 약품 주문 페이지입니다.

찾아야 할 셀렉터:
- search_input: 약품명 또는 보험코드 검색 입력 필드
- search_btn: 검색 버튼 (없으면 null — Enter 키로 대체)

현재 페이지에 약품 검색 기능이 없으면:
- needs_navigation: 약품 주문/검색 페이지로 이동할 링크나 메뉴의 셀렉터

DOM 뼈대:
{dom}

응답 형식:
{{"observation": "...", "selectors": {{"search_input": "...", "search_btn": null}}, "needs_navigation": null, "confidence": 0.9}}"""

            response = await self._ask_ai(prompt, screenshot)
            if not response:
                retry_hint = "AI 응답 없음"
                continue

            # 네비게이션 필요
            nav = response.get("needs_navigation")
            if nav and not response.get("selectors", {}).get("search_input"):
                try:
                    await page.click(nav)
                    await page.wait_for_timeout(3000)
                    retry_hint = f"'{nav}' 클릭 후 재탐지"
                    continue
                except Exception as e:
                    retry_hint = f"네비게이션 실패: {e}"
                    continue

            selectors = response.get("selectors", {})
            if not selectors.get("search_input"):
                retry_hint = f"AI 관찰: {response.get('observation', '')}"
                continue

            if not self._validate(selectors):
                retry_hint = "보안 검증 실패"
                continue

            # 검색 작동 테스트
            test_ok = await self._verify_search(selectors)
            if test_ok:
                self._step_history.append("검색 기능 확인")
                return StepResult(success=True, selectors=selectors)
            else:
                retry_hint = "검색 실행 실패 — 셀렉터가 틀렸을 수 있음"

        return StepResult(success=False, error=retry_hint)

    async def _verify_search(self, search_sel: dict) -> bool:
        """검색 셀렉터로 실제 검색이 되는지 확인."""
        page = self._page
        for code, name in SEARCH_TERMS:
            for term in [name, code]:
                try:
                    await page.fill(search_sel["search_input"], "")
                    await page.wait_for_timeout(200)
                    await page.fill(search_sel["search_input"], term)
                    if search_sel.get("search_btn"):
                        await page.click(search_sel["search_btn"])
                    else:
                        await page.press(search_sel["search_input"], "Enter")
                    await page.wait_for_timeout(3000)

                    # 결과 행이 있는지 간단 체크
                    rows = await page.query_selector_all("table tbody tr")
                    if rows and len(rows) >= 1:
                        return True
                except Exception:
                    continue
        return False

    async def _step_table(self, search_sel: dict) -> StepResult:
        """3단계: 검색 결과 테이블 구조 분석."""
        page = self._page
        retry_hint = ""

        # 먼저 검색 결과가 있는 상태 만들기
        searched = False
        for code, name in SEARCH_TERMS:
            for term in [name, code]:
                try:
                    await page.fill(search_sel["search_input"], "")
                    await page.wait_for_timeout(200)
                    await page.fill(search_sel["search_input"], term)
                    if search_sel.get("search_btn"):
                        await page.click(search_sel["search_btn"])
                    else:
                        await page.press(search_sel["search_input"], "Enter")
                    await page.wait_for_timeout(3000)
                    rows = await page.query_selector_all("table tbody tr")
                    if rows and len(rows) >= 1:
                        searched = True
                        self._log(f"  테스트 검색 '{term}' → {len(rows)}행")
                        break
                except Exception:
                    continue
            if searched:
                break

        if not searched:
            return StepResult(success=False, error="테스트 검색 결과 0건")

        for attempt in range(MAX_RETRIES):
            screenshot, dom = await self._capture(page)
            history = " → ".join(self._step_history)
            prompt = f"""현재 단계: 검색 결과 테이블 구조 분석
이전 단계: {history}
목표: 검색 결과 테이블의 구조를 분석하세요.
{f"이전 시도 피드백: {retry_hint}" if retry_hint else ""}

찾아야 할 정보:
- result_rows: 결과 행 CSS 셀렉터 (예: "table tbody tr")
- code_col_idx: 보험코드 컬럼 인덱스 (0부터)
- name_col_idx: 약품명 컬럼 인덱스
- unit_col_idx: 규격/포장 컬럼 인덱스
- price_col_idx: 단가 컬럼 인덱스 (없으면 null)
- stock_col_idx: 재고 컬럼 인덱스 (없으면 null)
- qty_col_idx: 수량 입력 컬럼 인덱스 (없으면 null)
- cart_btn: 장바구니 담기/추가 버튼 CSS 셀렉터
- cart_btn_in_row: 담기 버튼이 각 행 안에 있으면 true, 페이지 레벨이면 false
- row_checkbox: 행 체크박스 셀렉터 (페이지 레벨 버튼과 같이 쓸 때, 없으면 null)

테이블 헤더와 데이터를 보고 각 컬럼이 무엇인지 판별하세요.
스크린샷에서 보이는 테이블 헤더 텍스트를 기준으로 판단하세요.

DOM 뼈대:
{dom}

응답 형식:
{{"observation": "테이블 구조 설명", "selectors": {{"result_rows": "table tbody tr", "code_col_idx": 0, "name_col_idx": 2, "unit_col_idx": 3, "price_col_idx": 5, "stock_col_idx": 6, "qty_col_idx": null, "cart_btn": "a:has-text(\\"추가\\")", "cart_btn_in_row": true, "row_checkbox": null}}, "confidence": 0.8}}"""

            response = await self._ask_ai(prompt, screenshot)
            if not response:
                retry_hint = "AI 응답 없음"
                continue

            selectors = response.get("selectors", {})
            if not selectors.get("result_rows"):
                retry_hint = f"AI 관찰: {response.get('observation', '')}"
                continue

            if not self._validate(selectors):
                retry_hint = "보안 검증 실패"
                continue

            # 결과 행이 실제로 잡히는지 확인
            try:
                rows = await page.query_selector_all(selectors["result_rows"])
                if rows:
                    self._step_history.append(f"테이블 구조 파악 ({len(rows)}행)")
                    return StepResult(success=True, selectors=selectors,
                                      observation=response.get("observation", ""))
                else:
                    retry_hint = f"'{selectors['result_rows']}'로 행을 찾을 수 없음"
            except Exception as e:
                retry_hint = f"셀렉터 실행 오류: {e}"

        return StepResult(success=False, error=retry_hint)

    async def _step_confirm(self) -> StepResult:
        """4단계: 주문확정 버튼 탐지."""
        page = self._page

        screenshot, dom = await self._capture(page)
        prompt = f"""현재 단계: 주문확정 버튼 탐지
이전 단계: {" → ".join(self._step_history)}
목표: 장바구니 또는 주문 페이지에서 최종 주문확정/결제 버튼을 찾으세요.

찾아야 할 셀렉터:
- confirm_btn: 주문확정/주문접수/결제하기 버튼

DOM 뼈대:
{dom}

응답 형식:
{{"observation": "...", "selectors": {{"confirm_btn": "..."}}, "confidence": 0.8}}"""

        response = await self._ask_ai(prompt, screenshot)
        if response and response.get("selectors", {}).get("confirm_btn"):
            selectors = response["selectors"]
            if self._validate(selectors):
                return StepResult(success=True, selectors=selectors)

        return StepResult(success=False, error="주문확정 버튼 못 찾음")

    # ────── AI 통신 ──────

    def _can_call_ai(self) -> bool:
        """AI 호출이 가능한지 확인 (Edge Function 또는 로컬 API 키)."""
        return bool(self._cloud_url and self._cloud_key) or bool(self._api_key)

    async def _ask_ai(self, prompt: str, screenshot_b64: str) -> dict | None:
        """Claude Vision API에 스크린샷 + 프롬프트를 보내고 JSON 응답을 받는다.

        우선순위: Supabase Edge Function → 로컬 API 키
        """
        # 1순위: Supabase Edge Function 프록시
        if self._cloud_url and self._cloud_key:
            result = await self._ask_via_edge_function(prompt, screenshot_b64)
            if result is not None:
                return result

        # 2순위: 로컬 API 키 직접 호출
        if self._api_key:
            return await self._ask_direct(prompt, screenshot_b64)

        self._log("  AI 호출 불가 (Edge Function/API 키 모두 없음)")
        return None

    async def _ask_via_edge_function(self, prompt: str, screenshot_b64: str) -> dict | None:
        """Supabase Edge Function을 통해 Claude Vision을 호출한다."""
        endpoint = f"{self._cloud_url}/functions/v1/analyze-selectors"
        payload = {
            "mode": "vision",
            "prompt": prompt,
            "screenshot_b64": screenshot_b64,
            "system_prompt": SYSTEM_PROMPT,
        }
        headers = {
            "Authorization": f"Bearer {self._cloud_key}",
            "Content-Type": "application/json",
        }

        try:
            import httpx
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                if resp.status_code != 200:
                    self._log(f"  Edge Function 오류 {resp.status_code}: {resp.text[:100]}")
                    return None
                text = resp.json().get("result", "")
                parsed = self._parse_json(text)
                if parsed and "selectors" in parsed:
                    parsed["selectors"] = self._sanitize_selectors(parsed["selectors"])
                return parsed
        except ImportError:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._ask_edge_function_sync, prompt, screenshot_b64
            )
        except Exception as e:
            self._log(f"  Edge Function 호출 실패: {e}")
            return None

    def _ask_edge_function_sync(self, prompt: str, screenshot_b64: str) -> dict | None:
        """requests를 이용한 동기 Edge Function 호출."""
        try:
            import requests
            resp = requests.post(
                f"{self._cloud_url}/functions/v1/analyze-selectors",
                json={
                    "mode": "vision",
                    "prompt": prompt,
                    "screenshot_b64": screenshot_b64,
                    "system_prompt": SYSTEM_PROMPT,
                },
                headers={
                    "Authorization": f"Bearer {self._cloud_key}",
                    "Content-Type": "application/json",
                },
                timeout=45,
            )
            if resp.status_code != 200:
                return None
            text = resp.json().get("result", "")
            parsed = self._parse_json(text)
            if parsed and "selectors" in parsed:
                parsed["selectors"] = self._sanitize_selectors(parsed["selectors"])
            return parsed
        except Exception as e:
            self._log(f"  Edge Function 동기 호출 실패: {e}")
            return None

    async def _ask_direct(self, prompt: str, screenshot_b64: str) -> dict | None:
        """로컬 API 키로 Claude Vision API를 직접 호출한다."""
        messages = [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }]

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 1024,
                        "system": SYSTEM_PROMPT,
                        "messages": messages,
                    },
                )
                if resp.status_code != 200:
                    self._log(f"  AI API 오류 {resp.status_code}: {resp.text[:100]}")
                    return None
                text = resp.json()["content"][0]["text"].strip()
                parsed = self._parse_json(text)
                if parsed and "selectors" in parsed:
                    parsed["selectors"] = self._sanitize_selectors(parsed["selectors"])
                return parsed
        except ImportError:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._ask_direct_sync, prompt, screenshot_b64
            )
        except Exception as e:
            self._log(f"  AI 호출 실패: {e}")
            return None

    def _ask_direct_sync(self, prompt: str, screenshot_b64: str) -> dict | None:
        """requests를 이용한 동기 Claude Vision 호출."""
        try:
            import requests
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1024,
                    "system": SYSTEM_PROMPT,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": screenshot_b64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }],
                },
                timeout=30,
            )
            if resp.status_code != 200:
                return None
            text = resp.json()["content"][0]["text"].strip()
            parsed = self._parse_json(text)
            if parsed and "selectors" in parsed:
                parsed["selectors"] = self._sanitize_selectors(parsed["selectors"])
            return parsed
        except Exception as e:
            self._log(f"  AI 동기 호출 실패: {e}")
            return None

    # ────── 유틸 ──────

    async def _capture(self, page) -> tuple[str, str]:
        """스크린샷(base64) + DOM 뼈대를 캡처한다."""
        # 스크린샷 (뷰포트만, full_page=False로 크기 제한)
        png_bytes = await page.screenshot(type="png")
        b64 = base64.b64encode(png_bytes).decode("ascii")

        # 디버그용 저장
        step_num = len(self._step_history) + 1
        path = os.path.join(paths.get_screenshots_dir(), f"agent_{self._wid}_{step_num:02d}.png")
        with open(path, "wb") as f:
            f.write(png_bytes)

        # DOM 뼈대
        from core.dom_extractor import extract_form_skeleton
        dom = await extract_form_skeleton(page)

        return b64, dom

    def _parse_json(self, text: str) -> dict | None:
        """AI 응답에서 JSON을 추출한다."""
        # 코드블록 안의 JSON
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()

        # 중첩 JSON 파싱
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 첫 번째 {...} 블록 추출
            depth = 0
            start = -1
            for i, ch in enumerate(text):
                if ch == "{":
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and start >= 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            return None
        return None

    def _sanitize_selectors(self, data: dict) -> dict:
        """AI 응답의 셀렉터를 Playwright 호환으로 정리한다."""
        if not isinstance(data, dict):
            return data
        result = {}
        for k, v in data.items():
            if isinstance(v, str):
                # :contains() → :has-text()
                v = re.sub(r':contains\(', ':has-text(', v)
                # onclick= 등 JS 속성이 포함된 셀렉터 제거
                if re.search(r'on\w+=', v):
                    v = None
            elif isinstance(v, dict):
                v = self._sanitize_selectors(v)
            if v is not None:
                result[k] = v
        return result

    def _validate(self, selectors: dict) -> bool:
        """셀렉터 보안 검증."""
        from core.selector_validator import validate_selectors
        return validate_selectors(selectors)

    def _log(self, msg: str):
        """진행 메시지 출력."""
        full = f"[AI에이전트] {msg}"
        print(full)
        if self._progress:
            self._progress(full)
