"""아남약품 도매상 — 수동 셀렉터 기반 step-by-step 직진 플로우 (v1.5.46+).

셀렉터 JSON(`tools/wholesaler_data/v146/anam_order.json`) 에 수집된 셀렉터를
정해진 순서대로 실행한다. AI 자동 탐지 / 휴리스틱 폴백 없음.
각 step 마다 stage 를 기록하므로, 실패 시 어디서 깨졌는지 바로 보인다.

아남 특이점:
- login_url (`/HomePage/Contents/Intro/Default.asp`) ≠ url (`/Service/Order/Order.asp`).
- 장바구니와 주문전송이 `iframe#ifrm_bag` 내부.
- layout_mode = global_cart_btn 변종 (체크박스 없음 — 수량 입력이 선택 역할).
"""

from datetime import datetime

from wholesalers.base import WholesalerBase, choose_best_pack, parse_pack_size


class AnamWholesaler(WholesalerBase):
    """아남약품 — 수동 셀렉터 JSON 을 step 1~10 로 직진 실행."""

    WID = "anam"
    # URL 고정 — 사용자 등록(wholesalers.json)에 로그인 URL 만 있거나
    # 서버 셀렉터에 url/login_url 필드가 빠져도 이 상수를 진리로 사용.
    LOGIN_URL = "http://anampharm.co.kr/HomePage/Contents/Intro/Default.asp"
    ORDER_URL = "http://anampharm.co.kr/Service/Order/Order.asp"

    def __init__(self, config: dict):
        # URL 은 클래스 상수로 덮어씀 (등록값이 로그인/주문 중 무엇이든 상관없이 정답으로).
        config["login_url"] = self.LOGIN_URL
        config["url"] = self.ORDER_URL

        # 셀렉터 로드 — wholesalers.json 등록 wid 가 한글일 수 있어
        # 여러 후보 key 로 시도. v1.5.46 schema 가 붙은 것만 채택
        # (legacy 로컬 캐시가 남아있으면 스킵).
        from core.selector_store import load_selectors
        sel = {}
        tried = []
        candidates = [
            self.WID,                          # "anam"
            config.get("name"),                # "아남약품"
            config.get("wid"),
        ]
        for key in candidates:
            if not key or key in tried:
                continue
            tried.append(key)
            cand = load_selectors(key, url=self.ORDER_URL) or {}
            schema = (cand.get("table") or {}).get("schema_version", "")
            if cand and schema in ("v1.5.45", "v1.5.46"):
                sel = cand
                break
            # schema 없는 (legacy 잔존) 캐시는 무시. 다음 후보 진행.

        super().__init__(config)
        self._selectors = sel

    # ────────────────────── 연동 테스트 (settings_tab 진입점) ──────────────────────

    async def full_onboard(self, probe_term: str = "타이레놀",
                           headless: bool = True) -> dict:
        """수동 셀렉터 기반 직진 연동 검증.

        Step 1 로그인 페이지 이동 → 2 ID/PW → 3 제출 → 4 로그인 검증
        → 5 주문 페이지 이동 → 6 검색 → 7 결과 행 → 8 수량 → 9 담기 → 10 담김 검증.

        각 step 실패 시 stage + 셀렉터 + 사유를 message 에 박고 즉시 return.
        AI 폴백 없음. report 구조는 generic.full_onboard 와 호환.
        """
        report = {
            "wid": self.WID,
            "site_url": self.url,
            "success": False,
            "stage": "start",
            "message": "",
            "confirmed_selectors": {},
            "onboard_log": {"stages": []},
        }

        def _mark(stage: str, ok: bool, detail: str = ""):
            report["onboard_log"]["stages"].append({
                "stage": stage, "ok": ok, "detail": detail,
                "ts": datetime.now().isoformat(),
            })

        def _fail(stage: str, message: str) -> dict:
            report["stage"] = stage
            report["message"] = message
            _mark(stage, False, message)
            return report

        sel = self._selectors
        if not sel:
            return _fail("selectors", "셀렉터 없음 — 로컬/서버에 아남 JSON 미존재")

        login_cfg = sel.get("login", {}) or {}
        search_cfg = sel.get("search", {}) or {}
        table_cfg = sel.get("table", {}) or {}

        id_input = login_cfg.get("id_input")
        pw_input = login_cfg.get("pw_input")
        login_btn = login_cfg.get("login_btn", "")

        s_input = search_cfg.get("search_input")
        s_btn = search_cfg.get("search_btn", "")

        result_rows = table_cfg.get("result_rows")
        qty_in_row = table_cfg.get("qty_input_in_row")
        row_chk = table_cfg.get("row_checkbox_in_row", "")
        global_cart_btn = table_cfg.get("global_cart_btn")
        cart_iframe = table_cfg.get("cart_iframe", "")
        cart_rows_sel = table_cfg.get("cart_rows_sel", "")

        # v1.5.46 옵션 필드 — 사이트 습성은 JSON 으로 분리 (코드 재빌드 없이 조정).
        # 아남 기본값: Tab + form_post (HTML 중첩 form 문제로 native click 동작 안 함,
        # probe 로 확정)
        qty_commit = table_cfg.get("qty_commit", "tab")
        # native | js | native_then_js | form_post
        cart_btn_click = table_cfg.get("cart_btn_click", "form_post")
        cart_verify_timeout_ms = int(
            table_cfg.get("cart_verify_timeout_ms", 12000)
        )
        post_click_wait_ms = int(
            table_cfg.get("post_click_wait_ms", 500)
        )
        # form_post 전략용 — 아남 form name 이 frmOrder (확정)
        form_name = table_cfg.get("form_name", "frmOrder")

        missing = []
        if not id_input:
            missing.append("login.id_input")
        if not pw_input:
            missing.append("login.pw_input")
        if not s_input:
            missing.append("search.search_input")
        if not result_rows:
            missing.append("table.result_rows")
        if not qty_in_row:
            missing.append("table.qty_input_in_row")
        if not global_cart_btn:
            missing.append("table.global_cart_btn")
        if missing:
            return _fail("selectors",
                         f"필수 셀렉터 누락: {', '.join(missing)}")

        try:
            await self._launch(headless=headless)
            page = self._page
            page.on("dialog", lambda d: d.accept())

            # Step 1: 로그인 페이지 이동
            self._progress(f"[1/10] 로그인 페이지: {self.login_url}")
            try:
                await page.goto(self.login_url,
                                wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
                _mark("navigate_login", True, self.login_url)
            except Exception as e:
                return _fail("navigate_login",
                             f"로그인 페이지 접속 실패 ({self.login_url}): "
                             f"{str(e)[:120]}")

            # Step 2: ID / PW 입력
            self._progress("[2/10] ID/PW 입력")
            try:
                await page.fill(id_input, self.user_id)
                await page.fill(pw_input, self.password)
                _mark("fill_credentials", True)
            except Exception as e:
                return _fail("fill_credentials",
                             f"ID/PW 입력 실패 — id={id_input}, "
                             f"pw={pw_input}: {str(e)[:120]}")

            # Step 3: 로그인 제출
            self._progress("[3/10] 로그인 제출")
            try:
                if login_btn:
                    try:
                        await page.click(login_btn, timeout=5000)
                    except Exception:
                        await page.press(pw_input, "Enter")
                else:
                    await page.press(pw_input, "Enter")
                await page.wait_for_timeout(3500)
                _mark("login_submit", True, login_btn or "enter")
            except Exception as e:
                return _fail("login_submit",
                             f"로그인 제출 실패: {str(e)[:120]}")

            # Step 4: 로그인 성공 검증
            current_url = page.url
            login_ok = False
            reason = []
            if current_url != self.login_url and "login" not in current_url.lower():
                login_ok = True
                reason.append(f"url→{current_url[:80]}")
            if not login_ok:
                try:
                    el = await page.query_selector(id_input)
                    if not el or not await el.is_visible():
                        login_ok = True
                        reason.append("id_input 사라짐")
                except Exception:
                    pass
            if not login_ok:
                for sel_try in ('a:has-text("로그아웃")',
                                'button:has-text("로그아웃")',
                                'a:has-text("LOGOUT")'):
                    try:
                        el = await page.query_selector(sel_try)
                        if el and await el.is_visible():
                            login_ok = True
                            reason.append(f"{sel_try} 발견")
                            break
                    except Exception:
                        pass
            if not login_ok:
                try:
                    await self._screenshot("anam_login_fail.png")
                except Exception:
                    pass
                return _fail("login_verify",
                             "로그인 성공 확인 실패 — URL 미변경 + id_input 유지"
                             " + 로그아웃 버튼 없음. ID/PW 확인 필요")
            _mark("login_verify", True, " / ".join(reason))

            # Step 5: 주문 페이지 이동
            self._progress(f"[5/10] 주문 페이지: {self.url}")
            if page.url != self.url:
                try:
                    await page.goto(self.url,
                                    wait_until="domcontentloaded",
                                    timeout=15000)
                    await page.wait_for_timeout(2000)
                    _mark("navigate_order", True, self.url)
                except Exception as e:
                    return _fail("navigate_order",
                                 f"주문 페이지 접속 실패 ({self.url}): "
                                 f"{str(e)[:120]}")
            else:
                _mark("navigate_order", True, "이미 주문 페이지")

            # Step 5.5: 기존 장바구니 비우기 (연동 테스트 중복 방지)
            # 아남 서버는 fnPhysicExistsBag 로 중복 체크 — 이미 같은 품목
            # 있으면 담기 거부. 테스트 시작 시점에 기존 품목 비워서 깨끗한 상태.
            # 사용자 실제 주문 중 품목이 남아있어도 연동 테스트 목적상 비우기 수행.
            clear_btn = table_cfg.get("clear_all_btn", "")
            if clear_btn and cart_iframe:
                try:
                    await page.frame_locator(cart_iframe).locator(
                        clear_btn).click(timeout=5000)
                    await page.wait_for_timeout(2500)
                    _mark("clear_cart", True, clear_btn)
                except Exception as e:
                    _mark("clear_cart", False,
                          f"비우기 버튼 없거나 비활성 ({str(e)[:60]})")

            # Step 6: 검색 입력 + 실행
            self._progress(f"[6/10] '{probe_term}' 검색")
            try:
                # search_input 존재 확인 (없으면 페이지 이동이 잘못됐거나 셀렉터 변경)
                try:
                    await page.wait_for_selector(s_input, timeout=5000)
                except Exception:
                    return _fail("search",
                                 f"검색 입력창 없음 ({s_input}) — 주문 페이지 "
                                 "아닌 곳에 있거나 사이트 변경")
                await page.fill(s_input, "")
                await page.wait_for_timeout(200)
                await page.fill(s_input, probe_term)
                await page.wait_for_timeout(200)
                if s_btn:
                    try:
                        await page.click(s_btn, timeout=5000)
                    except Exception:
                        await page.press(s_input, "Enter")
                else:
                    await page.press(s_input, "Enter")
                await page.wait_for_timeout(3000)
                _mark("search", True, f"{probe_term} → {s_input}")
            except Exception as e:
                return _fail("search",
                             f"검색 실행 실패 ({s_input}): {str(e)[:120]}")

            # Step 7: 결과 행 확인 — 메인 프레임 먼저, 실패 시 iframe 전수 순회
            try:
                row_count = await page.locator(result_rows).count()
            except Exception as e:
                return _fail("result_rows",
                             f"result_rows 셀렉터 오류 ({result_rows}): "
                             f"{str(e)[:120]}")

            result_frame_info = ""
            if row_count == 0:
                # iframe 안에 있는지 전수 조회. 아남/구형 ASP 는 frameset 구조 흔함.
                found_frames = []
                frame_dump = []
                for fr in page.frames:
                    if fr is page.main_frame:
                        continue
                    try:
                        fc = await fr.locator(result_rows).count()
                        frame_dump.append(
                            f"{fr.name or '(unnamed)'}@{fr.url[:60]}→{fc}"
                        )
                        if fc > 0:
                            found_frames.append((fr, fc))
                    except Exception as fe:
                        frame_dump.append(
                            f"{fr.name or '(unnamed)'}@{fr.url[:60]}→ERR:"
                            f"{str(fe)[:30]}"
                        )
                if found_frames:
                    # 첫 번째 매칭 iframe 사용. 셀렉터 JSON 에
                    # result_iframe 필드 추가 권장 메시지로 상세 안내.
                    fr, fc = found_frames[0]
                    return _fail(
                        "result_rows_iframe",
                        f"검색 결과가 iframe 안에 있음 — "
                        f"frame='{fr.name or fr.url[:50]}' "
                        f"에서 '{result_rows}' {fc}행 발견. "
                        f"셀렉터 JSON table 에 "
                        f"\"result_iframe\": \"<iframe selector>\" 추가 필요. "
                        f"frames_scanned: {frame_dump}"
                    )
                return _fail(
                    "result_rows",
                    f"검색 결과 0행 — '{result_rows}' 미매칭. "
                    f"page_url={page.url[:80]}, "
                    f"iframes_scanned: {frame_dump if frame_dump else '없음'}"
                )
            _mark("result_rows", True, f"{row_count}행{result_frame_info}")

            # Step 8: 첫 행 수량 입력 (+ 체크박스 있으면 체크)
            self._progress("[8/10] 수량 입력")
            try:
                first_row = page.locator(result_rows).first
                qty_el = first_row.locator(qty_in_row).first
                await qty_el.wait_for(state="visible", timeout=5000)
                await qty_el.fill("1")
                if row_chk:
                    try:
                        await first_row.locator(row_chk).first.check()
                    except Exception:
                        pass
                _mark("fill_qty", True, qty_in_row)
            except Exception as e:
                return _fail("fill_qty",
                             f"수량 입력 실패 ({qty_in_row}): {str(e)[:120]}")

            # Step 9: 담기 전 cart count 스냅샷 (iframe 고려)
            async def _cart_count() -> int:
                try:
                    if cart_iframe:
                        return await page.frame_locator(
                            cart_iframe).locator(cart_rows_sel).count()
                    return await page.locator(cart_rows_sel).count()
                except Exception:
                    return -1

            cart_before = await _cart_count() if cart_rows_sel else 0

            # qty 입력 후 commit 방식 (JSON 옵션 qty_commit 에 따라 분기)
            if qty_commit == "tab":
                try:
                    await page.keyboard.press("Tab")
                    await page.wait_for_timeout(300)
                except Exception:
                    pass
            elif qty_commit == "change":
                try:
                    await first_row.locator(qty_in_row).first.dispatch_event(
                        "change")
                    await page.wait_for_timeout(300)
                except Exception:
                    pass
            # qty_commit == "none" 은 아무것도 안 함

            # Step 9: 담기 버튼 클릭 (JSON 옵션 cart_btn_click 에 따라 분기)
            self._progress("[9/10] 담기")

            async def _click_native() -> tuple[bool, str]:
                try:
                    await page.click(global_cart_btn, timeout=5000,
                                     no_wait_after=True)
                    return True, ""
                except Exception as e:
                    return False, str(e)[:60]

            async def _click_js() -> tuple[bool, str]:
                try:
                    await page.evaluate(
                        "(sel) => { const el = document.querySelector(sel); "
                        "if (el) el.click(); }", global_cart_btn)
                    return True, ""
                except Exception as e:
                    return False, str(e)[:60]

            async def _form_post() -> tuple[bool, str]:
                """form 의 FormData 를 action 에 fetch POST (우회).
                아남의 HTML 중첩 form 이슈로 native click 이 frmOrder 를 제대로
                submit 못 하는 경우 이 경로가 유일하게 작동한다 (probe 로 확정).
                """
                try:
                    res = await page.evaluate(
                        """
                        async (formName) => {
                            const f = document.forms[formName];
                            if (!f) return {ok: false, err: 'NO_FORM'};
                            const fd = new FormData(f);
                            const params = new URLSearchParams();
                            for (const [k, v] of fd.entries()) {
                                params.append(k, v);
                            }
                            try {
                                const r = await fetch(f.action, {
                                    method: 'POST',
                                    headers: {'Content-Type':
                                        'application/x-www-form-urlencoded'},
                                    body: params.toString(),
                                    credentials: 'include',
                                });
                                return {ok: r.ok, status: r.status,
                                        url: r.url};
                            } catch(e) {
                                return {ok: false, err: String(e)};
                            }
                        }
                        """, form_name
                    )
                    if not res.get("ok"):
                        return False, str(res)[:120]
                    # 서버 담기 후 iframe 내용 갱신이 자동으로 안 되면
                    # 강제 reload — 그래야 클라이언트가 담김 확인 가능.
                    if cart_iframe:
                        try:
                            await page.evaluate(
                                "(sel) => { const fr = "
                                "document.querySelector(sel); "
                                "if (fr && fr.contentWindow) "
                                "fr.contentWindow.location.reload(); }",
                                cart_iframe)
                        except Exception:
                            pass
                    return True, f"status={res.get('status')}"
                except Exception as e:
                    return False, str(e)[:120]

            click_strategy = ""
            click_err = ""
            if cart_btn_click == "form_post":
                ok, click_err = await _form_post()
                click_strategy = "form_post" if ok else ""
            elif cart_btn_click == "native":
                ok, click_err = await _click_native()
                click_strategy = "native" if ok else ""
            elif cart_btn_click == "js":
                ok, click_err = await _click_js()
                click_strategy = "js" if ok else ""
            else:  # native_then_js
                ok, e1 = await _click_native()
                if ok:
                    click_strategy = "native"
                else:
                    ok, e2 = await _click_js()
                    click_strategy = "js" if ok else ""
                    click_err = f"native={e1} / js={e2}"

            if not click_strategy:
                try:
                    await self._screenshot("anam_cart_click_fail.png")
                except Exception:
                    pass
                return _fail(
                    "cart_click",
                    f"담기 실패 (전략={cart_btn_click}): {click_err}")
            _mark("cart_click", True,
                  f"{click_strategy} {click_err if click_err else ''}")

            # post_click_wait_ms 만큼 대기 (Ajax 시작 유예)
            if post_click_wait_ms > 0:
                await page.wait_for_timeout(post_click_wait_ms)

            # Step 10: 담김 검증 — 폴링 (JSON 옵션 cart_verify_timeout_ms)
            if cart_rows_sel:
                cart_after = cart_before
                poll_interval_ms = 500
                max_iter = max(1, cart_verify_timeout_ms // poll_interval_ms)
                for _ in range(max_iter):
                    await page.wait_for_timeout(poll_interval_ms)
                    cart_after = await _cart_count()
                    if cart_after > cart_before:
                        break

                # 1차 실패 시 JS click 재시도 (native 전략이었을 때만, 그리고
                # 기본 native_then_js 는 이미 fallback 함)
                if (cart_after <= cart_before
                        and click_strategy == "native"
                        and cart_btn_click == "native"):
                    try:
                        await page.evaluate(
                            "(sel) => { const el = document.querySelector(sel); "
                            "if (el) el.click(); }", global_cart_btn)
                        _mark("cart_click_retry", True,
                              "native 실패 → JS click 재시도")
                        retry_iter = max(1, (cart_verify_timeout_ms // 2)
                                         // poll_interval_ms)
                        for _ in range(retry_iter):
                            await page.wait_for_timeout(poll_interval_ms)
                            cart_after = await _cart_count()
                            if cart_after > cart_before:
                                break
                    except Exception:
                        pass

                if cart_after <= cart_before:
                    # 디버깅 덤프 — iframe 수, 현재 URL, qty input 상태
                    dump_parts = [
                        f"before={cart_before}", f"after={cart_after}",
                        f"click={click_strategy}", f"page_url={page.url[:60]}",
                    ]
                    try:
                        qty_val = await first_row.locator(
                            qty_in_row).first.input_value()
                        dump_parts.append(f"qty_val='{qty_val}'")
                    except Exception:
                        dump_parts.append("qty_val=ERR")
                    try:
                        btn_count = await page.locator(global_cart_btn).count()
                        dump_parts.append(f"btn_found={btn_count}")
                    except Exception:
                        pass
                    try:
                        iframe_count = len(page.frames) - 1
                        dump_parts.append(f"iframes={iframe_count}")
                    except Exception:
                        pass
                    try:
                        await self._screenshot("anam_cart_verify_fail.png")
                    except Exception:
                        pass
                    return _fail(
                        "cart_verify",
                        "장바구니 행 증가 없음 (폴링 7초+JS재시도 5초). " +
                        " ".join(dump_parts)
                    )
                _mark("cart_verify", True,
                      f"{cart_before}→{cart_after} ({click_strategy})")

            # 성공
            report["success"] = True
            report["stage"] = "done"
            report["message"] = (
                f"연동 정상 (검색 {row_count}행 + 담기 확인)"
            )
            report["confirmed_selectors"] = self._selectors
            _mark("done", True)
            return report

        except Exception as e:
            return _fail("exception", f"예외: {str(e)[:200]}")

        finally:
            try:
                await self._close()
            except Exception:
                pass

    # ────────────────────── 주문 흐름 (place_order_async 용 abstract 구현) ──────────────────────

    async def login_async(self, headless: bool = True) -> bool:
        """주문 흐름용 로그인. full_onboard step 1~5 축약."""
        if not self._page:
            await self._launch(headless=headless)
        page = self._page
        page.on("dialog", lambda d: d.accept())

        sel = self._selectors or {}
        login_cfg = sel.get("login", {}) or {}
        id_input = login_cfg.get("id_input")
        pw_input = login_cfg.get("pw_input")
        login_btn = login_cfg.get("login_btn", "")
        if not id_input or not pw_input:
            self._progress("로그인 셀렉터 없음")
            return False

        try:
            await page.goto(self.login_url,
                            wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            await page.fill(id_input, self.user_id)
            await page.fill(pw_input, self.password)
            if login_btn:
                try:
                    await page.click(login_btn, timeout=5000)
                except Exception:
                    await page.press(pw_input, "Enter")
            else:
                await page.press(pw_input, "Enter")
            await page.wait_for_timeout(3500)
        except Exception as e:
            self._progress(f"로그인 오류: {e}")
            return False

        # 로그인 성공 판정
        if page.url != self.login_url and "login" not in page.url.lower():
            ok = True
        else:
            ok = False
            try:
                el = await page.query_selector(id_input)
                if not el or not await el.is_visible():
                    ok = True
            except Exception:
                pass

        if ok:
            # 주문 페이지 이동
            if page.url != self.url:
                try:
                    await page.goto(self.url,
                                    wait_until="domcontentloaded",
                                    timeout=15000)
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass
            self._progress("로그인 성공")
            return True
        self._progress("로그인 실패")
        return False

    async def _add_item_to_cart(self, insurance_code: str, quantity: int,
                                idx: int, total: int,
                                preferred_unit: int | None = None) -> dict:
        """약품을 검색해 첫 행 수량 입력 후 전역 담기 버튼 클릭."""
        page = self._page
        sel = self._selectors or {}
        search_cfg = sel.get("search", {}) or {}
        table_cfg = sel.get("table", {}) or {}

        s_input = search_cfg.get("search_input")
        s_btn = search_cfg.get("search_btn", "")
        result_rows = table_cfg.get("result_rows")
        qty_in_row = table_cfg.get("qty_input_in_row")
        row_chk = table_cfg.get("row_checkbox_in_row", "")
        global_cart_btn = table_cfg.get("global_cart_btn")
        name_col_idx = table_cfg.get("name_col_idx")
        unit_col_idx = table_cfg.get("unit_col_idx")

        base_result = {
            "success": False,
            "insurance_code": insurance_code,
            "quantity": quantity,
            "box_qty": 0,
            "pack_size": 0,
            "drug_name": "",
            "message": "",
            "unit_options": [],
        }

        try:
            # 검색 (보험코드로)
            await page.fill(s_input, "")
            await page.wait_for_timeout(200)
            await page.fill(s_input, insurance_code)
            await page.wait_for_timeout(200)
            if s_btn:
                try:
                    await page.click(s_btn, timeout=5000)
                except Exception:
                    await page.press(s_input, "Enter")
            else:
                await page.press(s_input, "Enter")
            await page.wait_for_timeout(2500)

            row_count = await page.locator(result_rows).count()
            if row_count == 0:
                base_result["message"] = "검색 결과 없음"
                base_result["retryable"] = True
                return base_result

            # 첫 행에서 약품명, 규격 추출
            first_row = page.locator(result_rows).first
            cells = first_row.locator("td")
            try:
                if name_col_idx is not None:
                    base_result["drug_name"] = (await cells.nth(
                        name_col_idx).inner_text()).strip()
            except Exception:
                pass

            pack_sizes = []
            if unit_col_idx is not None:
                try:
                    unit_text = (await cells.nth(
                        unit_col_idx).inner_text()).strip()
                    pack = parse_pack_size(unit_text)
                    if pack:
                        pack_sizes.append(pack)
                except Exception:
                    pass
            base_result["unit_options"] = pack_sizes

            # 재고 사전 체크 — 아남은 재고 0 품목이 섞이면
            # 주문 전체를 거부하므로 담기 전에 걸러낸다.
            stock_col_idx = table_cfg.get("stock_col_idx")
            if stock_col_idx is not None:
                try:
                    import re as _re
                    stock_text = (await cells.nth(
                        stock_col_idx).inner_text()).strip()
                    m = _re.search(r"\d+", stock_text.replace(",", ""))
                    stock_num = int(m.group()) if m else 0
                    if stock_num <= 0:
                        base_result["message"] = (
                            f"재고 없음 (stock={stock_text!r}) — 아남에서 "
                            "구매 불가. 다른 도매상 재시도."
                        )
                        base_result["out_of_stock"] = True
                        base_result["retryable"] = True
                        return base_result
                except Exception:
                    pass

            # 수량 계산 — box_qty 최소 1
            pack_size = pack_sizes[0] if pack_sizes else 0
            if pack_size > 0:
                chosen = choose_best_pack(
                    [{"pack_size": pack_size}],
                    quantity,
                    preferred_unit or None,
                )
                box_qty = chosen.get("box_qty", 1)
                base_result["pack_size"] = pack_size
            else:
                box_qty = max(1, quantity)
            base_result["box_qty"] = box_qty

            # 수량 입력 (JSON 옵션 qty_commit 에 따라 commit)
            qty_el = first_row.locator(qty_in_row).first
            await qty_el.fill(str(box_qty))
            if row_chk:
                try:
                    await first_row.locator(row_chk).first.check()
                except Exception:
                    pass
            qty_commit = table_cfg.get("qty_commit", "tab")
            if qty_commit == "tab":
                try:
                    await page.keyboard.press("Tab")
                    await page.wait_for_timeout(300)
                except Exception:
                    pass

            # 담기 — form_post 우선 (아남 HTML 중첩 form 이슈 우회)
            cart_btn_click = table_cfg.get("cart_btn_click", "form_post")
            form_name = table_cfg.get("form_name", "frmOrder")
            cart_iframe = table_cfg.get("cart_iframe", "")

            if cart_btn_click == "form_post":
                res = await page.evaluate(
                    """
                    async (formName) => {
                        const f = document.forms[formName];
                        if (!f) return {ok: false, err: 'NO_FORM'};
                        const fd = new FormData(f);
                        const params = new URLSearchParams();
                        for (const [k, v] of fd.entries()) {
                            params.append(k, v);
                        }
                        try {
                            const r = await fetch(f.action, {
                                method: 'POST',
                                headers: {'Content-Type':
                                    'application/x-www-form-urlencoded'},
                                body: params.toString(),
                                credentials: 'include',
                            });
                            return {ok: r.ok, status: r.status};
                        } catch(e) {
                            return {ok: false, err: String(e)};
                        }
                    }
                    """, form_name
                )
                if not res.get("ok"):
                    base_result["message"] = (
                        f"담기 form POST 실패: {str(res)[:160]}"
                    )
                    return base_result
                # iframe reload — 서버 반영 후 클라이언트 확인 가능하도록
                if cart_iframe:
                    try:
                        await page.evaluate(
                            "(sel) => { const fr = "
                            "document.querySelector(sel); "
                            "if (fr && fr.contentWindow) "
                            "fr.contentWindow.location.reload(); }",
                            cart_iframe)
                    except Exception:
                        pass
                await page.wait_for_timeout(1800)
            else:
                # 기본 폴백 — native click
                await page.click(global_cart_btn, timeout=5000)
                await page.wait_for_timeout(1500)

            base_result["success"] = True
            base_result["message"] = "담기 성공"
            return base_result

        except Exception as e:
            base_result["message"] = f"담기 예외: {str(e)[:200]}"
            return base_result

    async def _confirm_order(self) -> None:
        """아남 주문전송 — iframe 내 frmBag 을 form_post 로 직접 전송.

        핵심:
        1. 모든 chk_N (건별취소 체크박스) uncheck → 주문 요청으로 전송
        2. frmBag.action(OrderEnd.asp) 으로 FormData fetch POST
        3. 응답 body 파싱 — alert(...) 메시지 있으면 RuntimeError 발생시켜
           상위 (base.py) 에서 주문 실패 처리되게 함.

        서버 응답 예시:
        - 성공: 정상 redirect 또는 빈 응답
        - 실패: `alert("...재고 부족...")` + closeWindowByMask()
        """
        page = self._page
        sel = self._selectors or {}
        confirm_cfg = sel.get("confirm", {}) or {}
        table_cfg = sel.get("table", {}) or {}
        frame_sel = confirm_cfg.get("iframe", "") or table_cfg.get(
            "cart_iframe", "")
        form_name = confirm_cfg.get("form_name") or table_cfg.get(
            "form_name", "frmBag")

        if not frame_sel:
            # 폴백 — 예상 밖 구조. native click.
            btn = confirm_cfg.get("confirm_btn")
            if btn:
                await page.click(btn, timeout=10000)
            await page.wait_for_timeout(2500)
            return

        result = await page.evaluate(
            """
            async ({frameSel, formName}) => {
                const fr = document.querySelector(frameSel);
                if (!fr || !fr.contentDocument) {
                    return {ok: false, err: 'NO_IFRAME'};
                }
                const doc = fr.contentDocument;
                // 1. 모든 건별취소 chk 해제
                const chks = doc.querySelectorAll(
                    'input[type=checkbox][name^="chk_"]');
                for (const c of chks) {
                    if (c.checked) c.checked = false;
                }
                // 2. frmBag form_post
                const f = doc.forms[formName];
                if (!f) return {ok: false, err: 'NO_FORM'};
                const fd = new FormData(f);
                const params = new URLSearchParams();
                for (const [k, v] of fd.entries()) {
                    params.append(k, v);
                }
                try {
                    const r = await fetch(f.action, {
                        method: 'POST',
                        headers: {'Content-Type':
                            'application/x-www-form-urlencoded'},
                        body: params.toString(),
                        credentials: 'include',
                    });
                    const text = await r.text();
                    return {
                        ok: r.ok, status: r.status,
                        body: text.substring(0, 3000)
                    };
                } catch(e) { return {ok: false, err: String(e)}; }
            }
            """,
            {"frameSel": frame_sel, "formName": form_name}
        )

        if not result.get("ok"):
            raise RuntimeError(
                f"주문전송 실패: {result.get('err', result)}"
            )

        # 응답 body 에서 alert 메시지 추출 — 있으면 서버가 주문 거부한 것
        body = result.get("body", "") or ""
        import re as _re
        alerts = _re.findall(r'alert\(["\'](.+?)["\']\)', body)
        if alerts:
            # 여러 alert 중 첫 번째를 에러로. 재고/수량/한도 등 실패 원인.
            raise RuntimeError(
                f"아남 주문 거부 — {alerts[0][:150]}"
            )

        # iframe reload 로 UI 동기화 (실주문 후 다음 담기에 영향 없도록)
        try:
            await page.evaluate(
                "(sel) => { const fr = document.querySelector(sel); "
                "if (fr && fr.contentWindow) "
                "fr.contentWindow.location.reload(); }", frame_sel)
        except Exception:
            pass
        await page.wait_for_timeout(2500)

    async def _get_cart_count(self) -> int:
        """iframe 내 cart_rows_sel 로 카운트."""
        if not self._page:
            return -1
        sel = self._selectors or {}
        table_cfg = sel.get("table", {}) or {}
        cart_rows_sel = table_cfg.get("cart_rows_sel", "")
        cart_iframe = table_cfg.get("cart_iframe", "")
        if not cart_rows_sel:
            return -1
        try:
            if cart_iframe:
                return await self._page.frame_locator(
                    cart_iframe).locator(cart_rows_sel).count()
            return await self._page.locator(cart_rows_sel).count()
        except Exception:
            return -1
