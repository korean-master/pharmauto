"""셀렉터 레코딩 엔진 — Playwright 브라우저에서 클릭된 요소의 CSS selector 를 자동 추출.

사용 흐름:
    recorder = SelectorRecorder(url, progress_cb)
    await recorder.start()
    sel = await recorder.capture_click("로그인 ID 입력창을 클릭하세요")
    await recorder.close()
"""
from __future__ import annotations

import asyncio
import re
from typing import Callable

# JS: 클릭된 요소 → 고유 CSS selector 생성 + 시각 하이라이트
_JS_INJECT = """
(function() {
  if (window.__pharmAutoRecorder) return;
  window.__pharmAutoRecorder = true;

  function buildSelector(el) {
    if (!el || el === document.body) return 'body';

    // 1. id
    if (el.id && !/[\\s:]/.test(el.id)) return '#' + el.id;

    // 2. name 속성
    if (el.name) {
      var tag = el.tagName.toLowerCase();
      return tag + '[name="' + el.name + '"]';
    }

    // 3. 고유 data-* 속성
    var attrs = ['data-id','data-key','data-code','data-value'];
    for (var i=0; i<attrs.length; i++) {
      var v = el.getAttribute(attrs[i]);
      if (v) return el.tagName.toLowerCase() + '[' + attrs[i] + '="' + v + '"]';
    }

    // 4. type + placeholder
    if (el.placeholder) {
      return el.tagName.toLowerCase() + '[placeholder="' + el.placeholder + '"]';
    }
    if (el.type && el.tagName.toLowerCase() === 'input') {
      var typeStr = 'input[type="' + el.type + '"]';
      // not-readonly 변형
      if (!el.readOnly) typeStr += ':not([readonly])';
      var same = document.querySelectorAll(typeStr);
      if (same.length === 1) return typeStr;
    }

    // 5. 텍스트 내용 (버튼류)
    var text = (el.textContent || '').trim().replace(/\\s+/g,' ').substring(0,20);
    if (text && ['BUTTON','A','SPAN'].includes(el.tagName)) {
      return el.tagName.toLowerCase() + ':has-text("' + text + '")';
    }

    // 6. class 조합 (공백 없는 클래스만)
    var classes = Array.from(el.classList).filter(function(c){ return !/[\\s:]/.test(c); });
    if (classes.length > 0) {
      var sel = el.tagName.toLowerCase() + '.' + classes.slice(0,2).join('.');
      var matches = document.querySelectorAll(sel);
      if (matches.length === 1) return sel;
    }

    // 7. 부모 기준 nth-child (최후)
    var parent = el.parentElement;
    if (parent) {
      var siblings = Array.from(parent.children);
      var idx = siblings.indexOf(el) + 1;
      return buildSelector(parent) + ' > ' + el.tagName.toLowerCase() + ':nth-child(' + idx + ')';
    }
    return el.tagName.toLowerCase();
  }

  function highlight(el) {
    var prev = el.style.cssText;
    el.style.outline = '3px solid #2563EB';
    el.style.outlineOffset = '2px';
    el.style.backgroundColor = 'rgba(37,99,235,0.15)';
    setTimeout(function(){ el.style.cssText = prev; }, 1200);
  }

  document.addEventListener('click', function(e) {
    if (!window.__pharmAutoCapturing) return;
    e.stopPropagation();
    e.preventDefault();
    var el = e.target;
    highlight(el);
    var sel = buildSelector(el);
    var info = {
      selector: sel,
      tag: el.tagName.toLowerCase(),
      text: (el.textContent||'').trim().substring(0,40),
      type: el.type || '',
      id: el.id || '',
      classes: Array.from(el.classList).join(' ')
    };
    if (window.__pharmAutoCallback) {
      window.__pharmAutoCallback(JSON.stringify(info));
    }
  }, true);
})();
"""

_JS_START_CAPTURE = "window.__pharmAutoCapturing = true;"
_JS_STOP_CAPTURE  = "window.__pharmAutoCapturing = false;"


class SelectorRecorder:
    def __init__(self, url: str, progress: Callable[[str], None] | None = None):
        self.url = url
        self._progress = progress or (lambda msg: None)
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None
        self._pending: asyncio.Future | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self, headless: bool = False):
        import json as _json
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=headless)
        self._context = await self._browser.new_context()
        self.page = await self._context.new_page()

        # 모든 페이지 탐색 시 JS 자동 inject
        await self._context.add_init_script(_JS_INJECT)
        self._loop = asyncio.get_event_loop()

        # expose_function 은 한 번만 등록 — Future 교체 방식으로 다중 호출 지원
        def _on_click(payload: str):
            try:
                info = _json.loads(payload)
            except Exception:
                info = {"selector": payload}
            if self._pending and not self._pending.done():
                self._loop.call_soon_threadsafe(self._pending.set_result, info)

        await self.page.expose_function("__pharmAutoCallback", _on_click)

        self._progress(f"브라우저 열림 → {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
        await self.page.add_script_tag(content=_JS_INJECT)

    async def capture_click(self, prompt: str, timeout_ms: int = 60000) -> dict | None:
        """브라우저에서 사용자가 클릭할 때까지 대기, 클릭 정보를 반환."""
        self._progress(f"[레코더] {prompt}")
        self._pending = self._loop.create_future()
        await self.page.evaluate(_JS_START_CAPTURE)

        try:
            result = await asyncio.wait_for(self._pending, timeout=timeout_ms / 1000)
        except asyncio.TimeoutError:
            result = None
        finally:
            try:
                await self.page.evaluate(_JS_STOP_CAPTURE)
            except Exception:
                pass

        if result:
            self._progress(f"  → 셀렉터: {result.get('selector','?')}")
        return result

    async def fill_and_submit(self, id_sel: str, pw_sel: str, btn_sel: str,
                               wid: str, wpass: str):
        """로그인 정보 입력 + 제출 (테스트용)."""
        try:
            await self.page.fill(id_sel, wid, timeout=5000)
            await self.page.fill(pw_sel, wpass, timeout=5000)
            await self.page.click(btn_sel, timeout=5000)
            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception as e:
            self._progress(f"  로그인 자동 완료 실패: {e}")

    async def navigate(self, url: str):
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self.page.add_script_tag(content=_JS_INJECT)

    async def close(self):
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
