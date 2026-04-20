"""도매상 CSS 셀렉터 자동 분석 모듈.

Supabase Edge Function을 통해 Claude API를 호출하여
검색창/검색버튼/장바구니버튼/수량입력창의 CSS 셀렉터를 자동으로 찾아낸다.
API 키는 서버에만 존재하며 앱에 포함되지 않는다.

사용법:
    from core.ai_analyzer import analyze_selectors
    result = await analyze_selectors(page, site_url="http://anampharm.co.kr", wid="아남약품")
"""

import asyncio
import json
import re

from core import paths


def _load_cloud_config() -> tuple[str, str]:
    """settings.json에서 Supabase 설정을 읽는다."""
    try:
        with open(paths.settings_path(), "r", encoding="utf-8") as f:
            s = json.load(f)
        return s.get("supabase_url", ""), s.get("supabase_key", "")
    except Exception:
        return "", ""


def _load_api_key() -> str:
    """settings.json에서 Claude API 키를 읽는다 (로컬 폴백용)."""
    try:
        with open(paths.settings_path(), "r", encoding="utf-8") as f:
            s = json.load(f)
        return s.get("claude_api_key", "")
    except Exception:
        return ""


def is_available() -> bool:
    """AI 분석이 가능한지 확인 (Supabase 또는 로컬 API 키)."""
    url, key = _load_cloud_config()
    if url and key:
        return True
    return bool(_load_api_key())


async def analyze_selectors(page, site_url: str, wid: str) -> dict | None:
    """도매상 페이지를 Claude로 분석하여 CSS 셀렉터를 반환한다.

    Args:
        page: Playwright Page 객체 (로그인된 상태)
        site_url: 도매상 사이트 URL (예: http://anampharm.co.kr)
        wid: 도매상 ID/이름 (예: 아남약품)

    Returns:
        셀렉터 dict 또는 None (분석 실패 시)
        예: {
            "search_input": "#srhText",
            "search_btn": "button.btnSearch",
            "cart_btn": "button:has-text('담기')",
            "qty_input": "input[name='qty']",
            "result_rows": "table tbody tr",
        }
    """
    # 1. DOM 뼈대 추출
    from core.dom_extractor import extract_form_skeleton
    print(f"[AI 분석] {wid} DOM 추출 중...")
    skeleton = await extract_form_skeleton(page)

    if not skeleton or skeleton.startswith("<!--"):
        print(f"[AI 분석] {wid} DOM 추출 실패: {skeleton}")
        return None

    # 2. Claude에게 질의 (Supabase 프록시 우선 → 로컬 API 키 폴백)
    print(f"[AI 분석] {wid} 셀렉터 분석 요청 중...")
    raw_response = await _call_via_supabase(site_url, wid, skeleton)
    if not raw_response:
        api_key = _load_api_key()
        if api_key:
            print(f"[AI 분석] {wid} 로컬 API 키로 재시도...")
            raw_response = await _call_claude_api(api_key, site_url, wid, skeleton)
    if not raw_response:
        print(f"[AI 분석] {wid} AI 분석 불가")
        return None

    # 3. JSON 파싱
    selectors = _parse_response(raw_response)
    if not selectors:
        print(f"[AI 분석] {wid} 응답 파싱 실패: {raw_response[:200]}")
        return None

    # 4. 보안 검증
    from core.selector_validator import validate_selectors
    if not validate_selectors(selectors):
        print(f"[AI 분석] {wid} 보안 검증 실패 — 셀렉터 폐기")
        return None

    print(f"[AI 분석] {wid} 분석 성공: {list(selectors.keys())}")
    return selectors


async def _call_via_supabase(site_url: str, wid: str, skeleton: str) -> str | None:
    """Supabase Edge Function을 통해 Claude API를 호출한다."""
    url, key = _load_cloud_config()
    if not url or not key:
        return None

    endpoint = f"{url}/functions/v1/analyze-selectors"
    payload = {
        "site_url": site_url,
        "wid": wid,
        "skeleton": skeleton,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    try:
        import httpx
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            if resp.status_code != 200:
                print(f"[AI 분석] Supabase 프록시 오류 {resp.status_code}")
                return None
            data = resp.json()
            return data.get("result", "")
    except ImportError:
        try:
            import requests
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=45)
            if resp.status_code != 200:
                return None
            return resp.json().get("result", "")
        except Exception as e:
            print(f"[AI 분석] Supabase 프록시 호출 실패: {e}")
            return None
    except Exception as e:
        print(f"[AI 분석] Supabase 프록시 호출 실패: {e}")
        return None


async def _call_claude_api(api_key: str, site_url: str, wid: str, skeleton: str) -> str | None:
    """Claude API를 비동기로 호출한다."""
    prompt = f"""당신은 웹 스크래핑 전문가입니다. 아래는 한국 약품 도매상 사이트({site_url})의 HTML 폼 요소 목록입니다.

이 사이트에서 약품을 주문하는 자동화 프로그램을 만들어야 합니다.
다음 4가지 요소의 CSS 셀렉터를 찾아주세요:
1. 약품명 또는 보험코드를 입력하는 **검색 입력창** (search_input)
2. 검색을 실행하는 **검색 버튼** (search_btn)
3. 약품을 장바구니에 담는 **담기/추가 버튼** (cart_btn)
4. 주문 **수량을 입력**하는 필드 (qty_input)
5. 검색 결과가 표시되는 **테이블 행** CSS 셀렉터 (result_rows, 예: "table tbody tr")

반드시 JSON 형식으로만 응답하고, 다른 설명은 절대 포함하지 마세요.
찾을 수 없는 항목은 null로 표시하세요.

응답 형식:
{{"search_input": "...", "search_btn": "...", "cart_btn": "...", "qty_input": "...", "result_rows": "..."}}

HTML 폼 요소 목록 ({wid}):
{skeleton}"""

    try:
        import httpx
    except ImportError:
        # httpx 없으면 requests로 폴백 (동기 → 스레드에서 실행)
        return await asyncio.get_event_loop().run_in_executor(
            None, _call_claude_sync, api_key, prompt
        )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",  # 빠르고 저렴한 모델
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            if response.status_code != 200:
                print(f"[AI 분석] Claude API 오류 {response.status_code}: {response.text[:200]}")
                return None
            data = response.json()
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"[AI 분석] Claude API 호출 실패: {e}")
        return None


def _call_claude_sync(api_key: str, prompt: str) -> str | None:
    """requests를 이용한 동기 Claude API 호출 (httpx 없을 때 폴백)."""
    try:
        import requests
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        if response.status_code != 200:
            print(f"[AI 분석] Claude API 오류 {response.status_code}")
            return None
        return response.json()["content"][0]["text"].strip()
    except Exception as e:
        print(f"[AI 분석] Claude API 호출 실패: {e}")
        return None


def _parse_response(text: str) -> dict | None:
    """Claude 응답에서 JSON 셀렉터를 추출한다."""
    # JSON 블록 추출 (마크다운 코드블록 처리)
    json_match = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if not json_match:
        return None

    try:
        data = json.loads(json_match.group())
        # null 값 제거
        return {k: v for k, v in data.items() if v is not None}
    except json.JSONDecodeError:
        return None
