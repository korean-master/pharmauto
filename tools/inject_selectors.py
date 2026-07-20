"""수동 셀렉터 주입 CLI — 원격 세팅 시 Supabase 에 직접 셀렉터 업로드.

사용법:
    # 주문 셀렉터 (wholesaler_selectors)
    python tools/inject_selectors.py list                  # 목록
    python tools/inject_selectors.py show <domain>         # dump
    python tools/inject_selectors.py validate <json_path>  # 검증
    python tools/inject_selectors.py upload <json_path>    # 업로드

    # 이력 설정 (wholesaler_history_config) — v1.5.46 신규
    python tools/inject_selectors.py list-history          # 목록
    python tools/inject_selectors.py show-history <wid>    # dump
    python tools/inject_selectors.py validate-history <json_path>
    python tools/inject_selectors.py upload-history <wid> <json_path>

사전 조건:
    - Supabase 설정이 settings.json 에 있거나 환경변수 SUPABASE_URL / SUPABASE_KEY

주문 셀렉터 설계 원칙:
    - tr:nth-of-type(N) 포함 시 upload reject (v1.5.43 근본 원칙)
    - schema_version 강제 부여 (v1.5.45)
    - _comment / _note / _example / _instructions 로 시작하는 키는 자동 제거

이력 설정 mode (v1.5.46):
    - separate_page: 별도 URL + 검색 + 테이블 (지오영/아남)
    - inline_in_order_page: 주문 페이지에서 약품 행 클릭 → 인라인 이력 패널 (삼원/백제)

이력 설정에 lot_detail.method == "row_click_modal" 면 행 클릭 → 모달에서 LOT 추출 (지오영).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Windows cp949 콘솔에서 한글/이모지 출력 에러 방지
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 프로젝트 루트를 sys.path 에 추가 (tools/ 에서 실행될 때)
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

SCHEMA_VERSION = "v1.5.46"


def _strip_comments(d):
    """dict/list 에서 _로 시작하는 메타 키 제거 (재귀)."""
    if isinstance(d, dict):
        return {
            k: _strip_comments(v) for k, v in d.items()
            if not k.startswith("_")
        }
    if isinstance(d, list):
        return [_strip_comments(x) for x in d]
    return d


def _validate(sel: dict) -> list[str]:
    """업로드 전 검증. 에러 메시지 리스트 반환 (비었으면 OK)."""
    errors = []

    # 필수 최상위 필드
    if not sel.get("wid"):
        errors.append("wid 필드 필수")
    if not sel.get("url"):
        errors.append("url 필드 필수")

    table = sel.get("table", {}) or {}
    layout = table.get("layout_mode", "")
    valid_layouts = ("row_cart_btn", "global_cart_btn", "select_then_add")
    if layout not in valid_layouts:
        errors.append(
            f"layout_mode 는 {valid_layouts} 중 하나 (현재: {layout!r})"
        )

    # 결과 행 셀렉터 필수
    if not table.get("result_rows"):
        errors.append("table.result_rows 필수")

    # 패턴별 필수 필드
    if layout == "row_cart_btn":
        cart_rel = table.get("cart_btn_in_row", "")
        if not cart_rel:
            errors.append("row_cart_btn 패턴: cart_btn_in_row 필수")
        if cart_rel and re.search(r'\btr:nth-of-type\(', cart_rel):
            errors.append(
                f"cart_btn_in_row 에 tr:nth-of-type 포함 금지 (근본 원칙 위반): "
                f"{cart_rel[:80]}"
            )
        if cart_rel and cart_rel.strip().startswith("tr"):
            errors.append(
                f"cart_btn_in_row 가 'tr' 로 시작 금지 — row 내부 상대 경로여야 함: "
                f"{cart_rel[:80]}"
            )
    elif layout == "global_cart_btn":
        if not table.get("global_cart_btn"):
            errors.append("global_cart_btn 패턴: global_cart_btn 필수")
        # row_checkbox_in_row 는 선택 (체크박스 없는 변종 — 아남)
        # 체크박스 없으면 qty_input_in_row 가 선택 역할
        if not table.get("row_checkbox_in_row") and \
           not table.get("qty_input_in_row"):
            errors.append(
                "global_cart_btn 패턴: row_checkbox_in_row 또는 "
                "qty_input_in_row 둘 중 하나는 필수 (선택 메커니즘)"
            )
    elif layout == "select_then_add":
        if not table.get("cart_btn"):
            errors.append("select_then_add 패턴: cart_btn 필수 (행 바깥 고정 위치)")
        if not table.get("qty_input"):
            errors.append("select_then_add 패턴: qty_input 필수 (행 바깥 고정 위치)")
        if not table.get("select_method"):
            errors.append("select_then_add 패턴: select_method 필수 (보통 'row_click')")

    # qty_input_in_row 도 tr 금지
    qty_rel = table.get("qty_input_in_row", "") or ""
    if qty_rel and re.search(r'\btr:nth-of-type\(', qty_rel):
        errors.append(
            f"qty_input_in_row 에 tr:nth-of-type 포함 금지: {qty_rel[:80]}"
        )

    # row_checkbox_in_row 도 tr 금지
    chk_rel = table.get("row_checkbox_in_row", "") or ""
    if chk_rel and re.search(r'\btr:nth-of-type\(', chk_rel):
        errors.append(
            f"row_checkbox_in_row 에 tr:nth-of-type 포함 금지: {chk_rel[:80]}"
        )

    # 검색 입력창 필수
    if not sel.get("search", {}).get("search_input"):
        errors.append("search.search_input 필수")

    # v1.5.46 옵션 필드 — 사이트 습성 (이벤트/대기 방식).
    # 값이 있으면 허용 범위 체크. 없으면 엔진 기본값 사용.
    qty_commit = table.get("qty_commit")
    if qty_commit is not None and qty_commit not in (
            "tab", "change", "none"):
        errors.append(
            f"qty_commit 은 'tab'/'change'/'none' 중 하나 (현재: {qty_commit!r})"
        )
    cart_btn_click = table.get("cart_btn_click")
    if cart_btn_click is not None and cart_btn_click not in (
            "native", "js", "native_then_js", "form_post"):
        errors.append(
            f"cart_btn_click 은 "
            f"'native'/'js'/'native_then_js'/'form_post' "
            f"(현재: {cart_btn_click!r})"
        )
    # form_post 전략을 쓰려면 form_name 필요 (없으면 document.forms 이름으로 탐색)
    form_name = table.get("form_name")
    if form_name is not None and not isinstance(form_name, str):
        errors.append(f"form_name 은 문자열 (현재: {form_name!r})")
    for num_field in ("cart_verify_timeout_ms", "post_click_wait_ms"):
        val = table.get(num_field)
        if val is not None and (not isinstance(val, int) or val < 0):
            errors.append(f"{num_field} 는 0 이상 정수 (현재: {val!r})")

    return errors


def _validate_history(cfg: dict) -> list[str]:
    """이력 설정 검증 (v1.5.46). mode 별 필수 필드 체크."""
    errors = []
    mode = cfg.get("mode", "")
    if mode not in ("separate_page", "inline_in_order_page"):
        errors.append(
            f"mode 는 'separate_page' 또는 'inline_in_order_page' "
            f"(현재: {mode!r})"
        )
    if not cfg.get("name"):
        errors.append("name 필수")
    if not cfg.get("base_url"):
        errors.append("base_url 필수")

    if mode == "separate_page":
        if not cfg.get("history_url"):
            errors.append("separate_page: history_url 필수")
        search = cfg.get("search", {}) or {}
        if not search.get("keyword"):
            errors.append("separate_page: search.keyword 필수")
        table = cfg.get("table", {}) or {}
        if not table.get("selector"):
            errors.append("separate_page: table.selector 필수")
        cols = table.get("columns", {}) or {}
        if "lot" not in cols and not cfg.get("lot_detail"):
            errors.append(
                "LOT 정보가 table.columns.lot 에도 없고 lot_detail 도 없음"
            )
        lot_detail = cfg.get("lot_detail")
        if lot_detail:
            if lot_detail.get("method") != "row_click_modal":
                errors.append(
                    f"lot_detail.method 는 'row_click_modal' "
                    f"(현재: {lot_detail.get('method')!r})"
                )
            if not lot_detail.get("modal_table"):
                errors.append("lot_detail.modal_table 필수")
            lcols = lot_detail.get("columns", {}) or {}
            if "lot" not in lcols:
                errors.append("lot_detail.columns.lot 필수")
    elif mode == "inline_in_order_page":
        trig = cfg.get("trigger", {}) or {}
        if not trig.get("method"):
            errors.append("inline: trigger.method 필수 (보통 'row_click')")
        if not trig.get("target"):
            errors.append("inline: trigger.target 필수 (주문 결과 행 셀렉터)")
        panel = cfg.get("history_panel", {}) or {}
        if not panel.get("rows_selector"):
            errors.append("inline: history_panel.rows_selector 필수")
        cols = panel.get("columns", {}) or {}
        if "lot" not in cols:
            errors.append("inline: history_panel.columns.lot 필수")

    return errors


def _prepare_for_upload(raw: dict) -> dict:
    """주석 제거 + schema_version 강제 + 기본 플래그."""
    sel = _strip_comments(raw)
    tbl = sel.setdefault("table", {})
    tbl["schema_version"] = SCHEMA_VERSION
    tbl.setdefault("auto_detected", False)
    sel.setdefault("auto_detected", False)
    sel.setdefault("verified_count", 1)
    return sel


def cmd_validate(args) -> int:
    with open(args.path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    sel = _prepare_for_upload(raw)
    errors = _validate(sel)
    if errors:
        print("❌ 검증 실패:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("✅ 검증 통과")
    print()
    print("upload 될 내용 (주석 제거 + schema_version 적용):")
    print(json.dumps(sel, ensure_ascii=False, indent=2))
    return 0


def cmd_upload(args) -> int:
    with open(args.path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    sel = _prepare_for_upload(raw)
    errors = _validate(sel)
    if errors:
        print("❌ 검증 실패 — upload 중단:")
        for e in errors:
            print(f"  - {e}")
        return 1

    from core.cloud import upload_selectors, normalize_domain, is_enabled
    if not is_enabled():
        print("❌ Supabase 설정 없음 (settings.json 또는 환경변수 확인)")
        return 1

    wid = sel["wid"]
    name = sel.get("name", wid)
    url = sel["url"]
    domain = normalize_domain(url)
    print(f"업로드 대상: {name} (wid={wid}, domain={domain})")
    print(f"layout_mode: {sel['table'].get('layout_mode')}")
    print(f"schema_version: {sel['table'].get('schema_version')}")
    if not args.yes:
        confirm = input("진행? (y/N): ").strip().lower()
        if confirm != "y":
            print("취소")
            return 0

    try:
        # upload_selectors 는 print 만 하고 반환값 없음
        upload_selectors(domain, name, sel)
        print(f"✅ 업로드 완료 — domain={domain}")
        return 0
    except Exception as e:
        print(f"❌ 업로드 실패: {e}")
        return 1


def cmd_show(args) -> int:
    from core.cloud import _load_cloud_config, _headers, _api_url
    import requests as _req
    resp = _req.get(
        _api_url("wholesaler_selectors"),
        headers=_headers(),
        params={"domain": f"eq.{args.wid}"},
        timeout=10,
    )
    rows = resp.json()
    if not rows:
        # domain 으로 못 찾으면 normalize_domain 거쳐서 재시도
        from core.cloud import normalize_domain
        normalized = normalize_domain(args.wid)
        resp = _req.get(
            _api_url("wholesaler_selectors"),
            headers=_headers(),
            params={"domain": f"eq.{normalized}"},
            timeout=10,
        )
        rows = resp.json()
    if not rows:
        print(f"❌ '{args.wid}' 셀렉터 없음 (tried: {args.wid}, normalize={normalized if 'normalized' in dir() else '-'})")
        return 1
    print(json.dumps(rows[0], ensure_ascii=False, indent=2))
    return 0


def cmd_list(args) -> int:
    from core.cloud import _load_cloud_config, _headers, _api_url
    import requests as _req
    resp = _req.get(
        _api_url("wholesaler_selectors"),
        headers=_headers(),
        params={
            "select": "domain,name,updated_at,auto_detected,table_sel",
            "order": "updated_at.desc",
            "limit": "50",
        },
        timeout=10,
    )
    rows = resp.json()
    print(f"서버 저장 도매상 셀렉터 {len(rows)}건:")
    print()
    print(f"{'domain':<20} {'name':<15} {'layout':<16} {'schema':<10} {'updated':<25}")
    print("-" * 95)
    for r in rows:
        tbl = r.get("table_sel") or {}
        if isinstance(tbl, str):
            try:
                tbl = json.loads(tbl)
            except Exception:
                tbl = {}
        layout = tbl.get("layout_mode", "-") if isinstance(tbl, dict) else "-"
        schema = tbl.get("schema_version", "-") if isinstance(tbl, dict) else "-"
        print(
            f"{r.get('domain','')[:20]:<20} "
            f"{r.get('name','')[:15]:<15} "
            f"{layout[:16]:<16} "
            f"{schema[:10]:<10} "
            f"{r.get('updated_at','')[:19]:<25}"
        )
    return 0


def cmd_validate_history(args) -> int:
    with open(args.path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    cfg = _strip_comments(raw)
    errors = _validate_history(cfg)
    if errors:
        print("❌ 검증 실패:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("✅ 검증 통과")
    print()
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
    return 0


def cmd_upload_history(args) -> int:
    with open(args.path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    cfg = _strip_comments(raw)
    errors = _validate_history(cfg)
    if errors:
        print("❌ 검증 실패 — upload 중단:")
        for e in errors:
            print(f"  - {e}")
        return 1

    from core.cloud import upload_history_config, is_enabled
    if not is_enabled():
        print("❌ Supabase 설정 없음 (settings.json 또는 환경변수 확인)")
        return 1

    wid = args.wid
    name = cfg.get("name", wid)
    print(f"업로드 대상: {name} (wid={wid})")
    print(f"mode: {cfg.get('mode')}")
    if cfg.get("mode") == "separate_page":
        print(f"history_url: {cfg.get('history_url')}")
        lot_detail = cfg.get("lot_detail")
        if lot_detail:
            print(f"lot_detail.method: {lot_detail.get('method')}")
    elif cfg.get("mode") == "inline_in_order_page":
        print(f"trigger.target: {cfg.get('trigger', {}).get('target')}")
        print(f"history_panel.container: "
              f"{cfg.get('history_panel', {}).get('container')}")

    if not args.yes:
        confirm = input("진행? (y/N): ").strip().lower()
        if confirm != "y":
            print("취소")
            return 0

    try:
        upload_history_config(wid, name, cfg)
        print(f"✅ 업로드 완료 — wid={wid}")
        return 0
    except Exception as e:
        print(f"❌ 업로드 실패: {e}")
        return 1


def cmd_show_history(args) -> int:
    from core.cloud import fetch_history_config
    cfg = fetch_history_config(args.wid)
    if not cfg:
        print(f"❌ '{args.wid}' 이력 설정 없음")
        return 1
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
    return 0


def cmd_list_history(args) -> int:
    from core.cloud import fetch_all_history_configs
    configs = fetch_all_history_configs()
    print(f"서버 저장 이력 설정 {len(configs)}건:")
    print()
    print(f"{'wid':<15} {'name':<15} {'mode':<25} {'url/trigger':<35}")
    print("-" * 95)
    for c in configs:
        mode = c.get("mode", "-")
        if mode == "separate_page":
            endpoint = c.get("history_url", "-")[:35]
        elif mode == "inline_in_order_page":
            trig = c.get("trigger", {}).get("target", "-")
            endpoint = f"click:{trig}"[:35]
        else:
            endpoint = c.get("history_url", "-")[:35]
        print(
            f"{c.get('wholesaler_id','')[:15]:<15} "
            f"{c.get('name','')[:15]:<15} "
            f"{mode[:25]:<25} "
            f"{endpoint:<35}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="PharmAuto 수동 셀렉터 주입")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ─── 주문 셀렉터 (wholesaler_selectors) ───
    p_list = sub.add_parser("list", help="주문 셀렉터 목록")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="주문 셀렉터 dump")
    p_show.add_argument("wid", help="도매상 도메인 or wid")
    p_show.set_defaults(func=cmd_show)

    p_val = sub.add_parser("validate", help="주문 JSON 검증 (upload 없음)")
    p_val.add_argument("path", help="셀렉터 JSON 경로")
    p_val.set_defaults(func=cmd_validate)

    p_up = sub.add_parser("upload", help="주문 JSON 검증 + 서버 upload")
    p_up.add_argument("path", help="셀렉터 JSON 경로")
    p_up.add_argument("-y", "--yes", action="store_true", help="확인 없이 진행")
    p_up.set_defaults(func=cmd_upload)

    # ─── 이력 설정 (wholesaler_history_config) — v1.5.46 신규 ───
    p_lh = sub.add_parser("list-history", help="이력 설정 목록")
    p_lh.set_defaults(func=cmd_list_history)

    p_sh = sub.add_parser("show-history", help="이력 설정 dump")
    p_sh.add_argument("wid", help="도매상 wid (예: geo, baekje)")
    p_sh.set_defaults(func=cmd_show_history)

    p_vh = sub.add_parser("validate-history",
                          help="이력 JSON 검증 (mode 별 필수 필드)")
    p_vh.add_argument("path", help="이력 설정 JSON 경로")
    p_vh.set_defaults(func=cmd_validate_history)

    p_uh = sub.add_parser("upload-history",
                          help="이력 JSON 검증 + 서버 upload")
    p_uh.add_argument("wid", help="도매상 wid (예: geo, baekje, samwon)")
    p_uh.add_argument("path", help="이력 설정 JSON 경로")
    p_uh.add_argument("-y", "--yes", action="store_true",
                      help="확인 없이 진행")
    p_uh.set_defaults(func=cmd_upload_history)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
