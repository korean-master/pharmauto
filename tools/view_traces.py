"""개발자용 Playwright Trace 뷰어.

고객 PC에서 자동 업로드된 오류 Trace 파일을 조회하고 로컬에서 열어볼 수 있다.

사용법:
    python tools/view_traces.py              # 최근 50개 목록
    python tools/view_traces.py <번호>       # 해당 trace 다운로드 + show-trace 실행
    python tools/view_traces.py --all        # 전체 목록 (최대 200개)
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import subprocess
import sys
import tempfile

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import requests
from core.cloud import _headers, _api_url


def fetch_traces(limit: int = 50) -> list[dict]:
    resp = requests.get(
        _api_url("error_logs"),
        headers=_headers(),
        params={
            "level": "eq.TRACE_FILE",
            "order": "created_at.desc",
            "limit": str(limit),
            "select": "id,pharmacy_code,message,context,created_at",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_trace_data(row_id: int) -> bytes:
    """log_tail (gzip+base64) 를 가져와서 원본 zip bytes 로 복원."""
    resp = requests.get(
        _api_url("error_logs"),
        headers=_headers(),
        params={"id": f"eq.{row_id}", "select": "log_tail"},
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows or not rows[0].get("log_tail"):
        raise ValueError("log_tail 없음")
    b64 = rows[0]["log_tail"]
    compressed = base64.b64decode(b64)
    return gzip.decompress(compressed)


def print_list(rows: list[dict]) -> None:
    print(f"\n{'번호':<5} {'시간':<20} {'약국코드':<18} {'약국/도매상':<30} {'크기':<8}")
    print("─" * 85)
    for i, r in enumerate(rows, 1):
        ctx = r.get("context") or {}
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except Exception:
                ctx = {}
        ts = r.get("created_at", "")[:19].replace("T", " ")
        code = (r.get("pharmacy_code") or "(없음)")[:18]
        msg = r.get("message", "")[:30]
        kb = ctx.get("raw_size_kb", "?")
        print(f"{i:<5} {ts:<20} {code:<18} {msg:<30} {kb}KB")
    print()


def open_trace(row_id: int, rows: list[dict]) -> None:
    # 해당 row 찾기
    row = next((r for r in rows if r["id"] == row_id), None)
    if not row:
        print(f"ID {row_id} 없음")
        return

    ctx = row.get("context") or {}
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except Exception:
            ctx = {}
    filename = ctx.get("trace_filename") or f"trace_{row_id}.zip"

    print(f"다운로드 중: {filename} ...")
    raw = fetch_trace_data(row_id)
    print(f"  {len(raw)//1024}KB 수신")

    out_path = os.path.join(tempfile.gettempdir(), filename)
    with open(out_path, "wb") as f:
        f.write(raw)
    print(f"  저장됨: {out_path}")

    # playwright show-trace 실행
    py = sys.executable
    venv_pw = os.path.join(_ROOT, "venv312", "Scripts", "python.exe")
    if os.path.exists(venv_pw):
        py = venv_pw
    print(f"  playwright show-trace 실행 중...")
    subprocess.Popen([py, "-m", "playwright", "show-trace", out_path])


def main():
    parser = argparse.ArgumentParser(description="PharmAuto Trace 뷰어")
    parser.add_argument("target", nargs="?", help="번호 또는 ID")
    parser.add_argument("--all", action="store_true", help="전체 목록 (최대 200개)")
    args = parser.parse_args()

    limit = 200 if args.all else 50
    print("서버에서 trace 목록 조회 중...")
    rows = fetch_traces(limit)

    if not rows:
        print("저장된 trace 없음")
        return

    print_list(rows)

    if args.target:
        try:
            n = int(args.target)
        except ValueError:
            print(f"올바른 번호를 입력하세요 (1~{len(rows)})")
            return
        if n < 1 or n > len(rows):
            print(f"번호 범위 초과 (1~{len(rows)})")
            return
        open_trace(rows[n - 1]["id"], rows)
    else:
        raw = input("열어볼 번호 입력 (Enter=종료): ").strip()
        if raw:
            try:
                n = int(raw)
                if 1 <= n <= len(rows):
                    open_trace(rows[n - 1]["id"], rows)
            except ValueError:
                pass


if __name__ == "__main__":
    main()
