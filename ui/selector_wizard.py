"""셀렉터 레코딩 마법사 — 고객이 직접 도매상 사이트에서 클릭해 셀렉터를 자동 생성.

흐름:
  도매상명/URL 입력 → 브라우저 열림 → 단계별 클릭 안내 →
  JSON 생성 → Supabase 업로드 → 전체 고객 즉시 배포
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Callable

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

from ui.styles import btn_primary, BLUE, GREEN, RED, BORDER, BG, TEXT, TEXT_SEC


# ──────────────────────────────────────────────────────────────────────────────
# 단계 정의
# ──────────────────────────────────────────────────────────────────────────────

STEPS = [
    {"key": "id_input",    "label": "로그인 ID 입력창",   "hint": "아이디를 입력하는 칸을 클릭하세요"},
    {"key": "pw_input",    "label": "로그인 PW 입력창",   "hint": "비밀번호를 입력하는 칸을 클릭하세요"},
    {"key": "login_btn",   "label": "로그인 버튼",        "hint": "로그인 버튼을 클릭하세요 (로그인이 진행됩니다)"},
    {"key": "search_input","label": "검색창",             "hint": "약품명을 검색하는 입력창을 클릭하세요"},
    {"key": "cart_btn",    "label": "담기 버튼",          "hint": "장바구니에 담기 버튼을 클릭하세요 (약품 행에 있는 버튼)"},
]


# ──────────────────────────────────────────────────────────────────────────────
# 레코딩 워커 (별도 스레드 + asyncio 루프)
# ──────────────────────────────────────────────────────────────────────────────

class RecorderWorker(QThread):
    log_signal   = pyqtSignal(str)          # 로그 라인
    step_done    = pyqtSignal(int, dict)    # (step_idx, click_info)
    step_prompt  = pyqtSignal(int)          # 다음 단계 안내 시작
    finished_ok  = pyqtSignal(dict)         # 최종 셀렉터 dict
    error_signal = pyqtSignal(str)          # 에러 메시지

    def __init__(self, url: str, wid_name: str, ws_id: str,
                 credentials: dict | None = None, parent=None):
        super().__init__(parent)
        self.url         = url
        self.wid_name    = wid_name
        self.ws_id       = ws_id
        self.credentials = credentials or {}  # {"id": ..., "pw": ...}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._recorder = None
        self._captured: dict[str, dict] = {}
        self._step_futures: list[asyncio.Future] = []
        self._current_step = 0
        self._stop_requested = False

    def advance(self):
        """UI 에서 '다음' 버튼 클릭 시 현재 단계를 완료 처리."""
        if self._loop and self._step_futures:
            fut = self._step_futures[0] if self._step_futures else None
            if fut and not fut.done():
                self._loop.call_soon_threadsafe(fut.set_result, None)

    def stop(self):
        self._stop_requested = True
        self.advance()

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._record())
        except Exception as e:
            self.error_signal.emit(str(e))
        finally:
            self._loop.close()

    async def _record(self):
        from wholesalers.recorder import SelectorRecorder
        rec = SelectorRecorder(self.url, progress=lambda m: self.log_signal.emit(m))
        self._recorder = rec
        try:
            await rec.start(headless=False)
            captured = {}

            for idx, step in enumerate(STEPS):
                if self._stop_requested:
                    break
                self._current_step = idx
                self.step_prompt.emit(idx)

                # 로그인 버튼 단계: 클릭 후 자동 로그인 수행
                if step["key"] == "login_btn" and captured.get("id_input") and captured.get("pw_input"):
                    info = await rec.capture_click(step["hint"])
                    if not info:
                        break
                    captured[step["key"]] = info
                    self.step_done.emit(idx, info)
                    # 자격증명이 있으면 실제 로그인 진행
                    cred_id = self.credentials.get("id", "")
                    cred_pw = self.credentials.get("pw", "")
                    if cred_id and cred_pw:
                        self.log_signal.emit("  → 자동 로그인 시도 중...")
                        await rec.fill_and_submit(
                            captured["id_input"]["selector"],
                            captured["pw_input"]["selector"],
                            info["selector"],
                            cred_id, cred_pw,
                        )
                        await asyncio.sleep(2)
                        # 로그인 후 검색 페이지 JS 재주입
                        try:
                            from wholesalers.recorder import _JS_INJECT
                            await rec.page.add_script_tag(content=_JS_INJECT)
                        except Exception:
                            pass
                    continue

                info = await rec.capture_click(step["hint"])
                if not info or self._stop_requested:
                    break
                captured[step["key"]] = info
                self.step_done.emit(idx, info)

            if not self._stop_requested and len(captured) >= 4:
                self.finished_ok.emit(captured)
        finally:
            await rec.close()


# ──────────────────────────────────────────────────────────────────────────────
# 메인 다이얼로그
# ──────────────────────────────────────────────────────────────────────────────

class SelectorWizardDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("도매상 셀렉터 녹화 마법사")
        self.setMinimumSize(620, 560)
        self.setStyleSheet(f"background: {BG};")
        self._worker: RecorderWorker | None = None
        self._captured: dict[str, dict] = {}
        self._current_step = -1
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(24, 20, 24, 20)

        # ── 헤더 ──
        title = QLabel("도매상 셀렉터 녹화 마법사")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        root.addWidget(title)

        desc = QLabel(
            "브라우저가 열리면 안내에 따라 클릭해 주세요.\n"
            "팜오토가 셀렉터를 자동으로 기록합니다."
        )
        desc.setStyleSheet(f"color: {TEXT_SEC}; font-size: 13px;")
        root.addWidget(desc)

        # ── 입력 폼 ──
        form_card = QWidget()
        form_card.setStyleSheet(f"background: white; border: 1px solid {BORDER}; border-radius: 8px;")
        form_lay = QVBoxLayout(form_card)
        form_lay.setSpacing(10)
        form_lay.setContentsMargins(16, 14, 16, 14)

        def _row(label_text, widget):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(100)
            lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 13px;")
            row.addWidget(lbl)
            row.addWidget(widget)
            form_lay.addLayout(row)

        self.ws_name_input = QLineEdit()
        self.ws_name_input.setPlaceholderText("예: 세화약품")
        self.ws_name_input.setStyleSheet("padding: 8px; border: 1px solid #DFE1E6; border-radius: 6px; font-size: 13px;")
        _row("도매상명", self.ws_name_input)

        self.ws_id_input = QLineEdit()
        self.ws_id_input.setPlaceholderText("예: esehwa  (영문 소문자, 공백 없이)")
        self.ws_id_input.setStyleSheet("padding: 8px; border: 1px solid #DFE1E6; border-radius: 6px; font-size: 13px;")
        _row("도매상 ID", self.ws_id_input)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("예: https://www.esehwa.co.kr/contents/order/order.asp")
        self.url_input.setStyleSheet("padding: 8px; border: 1px solid #DFE1E6; border-radius: 6px; font-size: 13px;")
        _row("사이트 URL", self.url_input)

        self.cred_id_input = QLineEdit()
        self.cred_id_input.setPlaceholderText("도매상 로그인 아이디 (선택 — 입력 시 자동 로그인)")
        self.cred_id_input.setStyleSheet("padding: 8px; border: 1px solid #DFE1E6; border-radius: 6px; font-size: 13px;")
        _row("로그인 ID", self.cred_id_input)

        self.cred_pw_input = QLineEdit()
        self.cred_pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.cred_pw_input.setPlaceholderText("도매상 로그인 비밀번호 (선택)")
        self.cred_pw_input.setStyleSheet("padding: 8px; border: 1px solid #DFE1E6; border-radius: 6px; font-size: 13px;")
        _row("로그인 PW", self.cred_pw_input)

        root.addWidget(form_card)

        # ── 진행 상태 ──
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, len(STEPS))
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{ background: #E5E7EB; border-radius: 4px; height: 8px; border: none; }}
            QProgressBar::chunk {{ background: {BLUE}; border-radius: 4px; }}
        """)
        root.addWidget(self._progress_bar)

        # ── 단계 안내 라벨 ──
        self._step_label = QLabel("시작 버튼을 눌러 녹화를 시작하세요.")
        self._step_label.setStyleSheet(
            f"background: white; border: 1px solid {BORDER}; border-radius: 8px;"
            f"padding: 14px; font-size: 14px; color: {TEXT}; font-weight: 600;"
        )
        self._step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._step_label.setMinimumHeight(60)
        root.addWidget(self._step_label)

        # ── 셀렉터 미리보기 ──
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(120)
        self._preview.setStyleSheet(
            f"background: #1E1E2E; color: #A6E3A1; font-family: 'Consolas','D2Coding',monospace;"
            f"font-size: 12px; border-radius: 6px; padding: 8px; border: none;"
        )
        self._preview.setPlaceholderText("녹화된 셀렉터가 여기 표시됩니다...")
        root.addWidget(self._preview)

        # ── 로그 ──
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(80)
        self._log.setStyleSheet(
            f"background: #F9FAFB; color: {TEXT_SEC}; font-size: 11px;"
            f"border: 1px solid {BORDER}; border-radius: 6px; padding: 6px;"
        )
        root.addWidget(self._log)

        # ── 버튼 ──
        btn_row = QHBoxLayout()

        self._start_btn = QPushButton("녹화 시작")
        self._start_btn.setStyleSheet(btn_primary())
        self._start_btn.clicked.connect(self._start)
        btn_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("중단")
        self._stop_btn.setStyleSheet(btn_primary(bg="#6B7280", hover="#4B5563"))
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self._stop_btn)

        self._upload_btn = QPushButton("Supabase 업로드")
        self._upload_btn.setStyleSheet(btn_primary(bg="#059669", hover="#047857"))
        self._upload_btn.setEnabled(False)
        self._upload_btn.clicked.connect(self._upload)
        btn_row.addWidget(self._upload_btn)

        root.addLayout(btn_row)

    # ──────────────────── 이벤트 핸들러 ────────────────────

    def _start(self):
        name = self.ws_name_input.text().strip()
        ws_id = self.ws_id_input.text().strip().lower().replace(" ", "_")
        url = self.url_input.text().strip()
        if not name or not url:
            QMessageBox.warning(self, "입력 필요", "도매상명과 사이트 URL을 입력해 주세요.")
            return
        if not url.startswith("http"):
            url = "https://" + url

        self._captured = {}
        self._preview.clear()
        self._log.clear()
        self._progress_bar.setValue(0)
        self._upload_btn.setEnabled(False)
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._step_label.setText("브라우저 열리는 중...")
        self._step_label.setStyleSheet(
            f"background: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 8px;"
            f"padding: 14px; font-size: 14px; color: #1D4ED8; font-weight: 600;"
        )

        cred = {
            "id": self.cred_id_input.text().strip(),
            "pw": self.cred_pw_input.text(),
        }

        self._worker = RecorderWorker(url, name, ws_id, cred)
        self._worker.log_signal.connect(self._on_log)
        self._worker.step_prompt.connect(self._on_step_prompt)
        self._worker.step_done.connect(self._on_step_done)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.error_signal.connect(self._on_error)
        self._worker.start()

    def _stop(self):
        if self._worker:
            self._worker.stop()
        self._stop_btn.setEnabled(False)
        self._start_btn.setEnabled(True)
        self._step_label.setText("녹화가 중단되었습니다.")

    def _on_log(self, msg: str):
        self._log.append(msg)

    def _on_step_prompt(self, idx: int):
        step = STEPS[idx]
        self._step_label.setText(
            f"[{idx+1}/{len(STEPS)}] {step['label']}\n\n{step['hint']}"
        )
        self._step_label.setStyleSheet(
            f"background: #FFFBEB; border: 2px solid #FCD34D; border-radius: 8px;"
            f"padding: 14px; font-size: 14px; color: #92400E; font-weight: 600;"
        )

    def _on_step_done(self, idx: int, info: dict):
        step = STEPS[idx]
        sel = info.get("selector", "?")
        self._captured[step["key"]] = sel
        self._progress_bar.setValue(idx + 1)
        self._preview.append(f'"{step["key"]}": "{sel}"')
        self._step_label.setText(
            f"[{idx+1}/{len(STEPS)}] {step['label']} ✓\n\n셀렉터: {sel}"
        )
        self._step_label.setStyleSheet(
            f"background: #F0FDF4; border: 2px solid #86EFAC; border-radius: 8px;"
            f"padding: 14px; font-size: 14px; color: #166534; font-weight: 600;"
        )

    def _on_finished(self, captured: dict):
        self._stop_btn.setEnabled(False)
        self._start_btn.setEnabled(True)
        self._step_label.setText("녹화 완료! Supabase 업로드 버튼을 누르세요.")
        self._step_label.setStyleSheet(
            f"background: #F0FDF4; border: 2px solid {GREEN}; border-radius: 8px;"
            f"padding: 14px; font-size: 14px; color: #166534; font-weight: 600;"
        )
        self._upload_btn.setEnabled(True)
        # captured 를 selector key → css string 으로 변환
        for step in STEPS:
            k = step["key"]
            if k in captured:
                info = captured[k]
                self._captured[k] = info.get("selector", "") if isinstance(info, dict) else str(info)

    def _on_error(self, msg: str):
        self._stop_btn.setEnabled(False)
        self._start_btn.setEnabled(True)
        self._step_label.setText(f"오류 발생: {msg}")
        QMessageBox.critical(self, "레코딩 오류", msg)

    def _upload(self):
        name = self.ws_name_input.text().strip()
        ws_id = self.ws_id_input.text().strip().lower().replace(" ", "_")
        url = self.url_input.text().strip()
        if not url.startswith("http"):
            url = "https://" + url

        cart_sel = self._captured.get("cart_btn", "")
        selector_json = {
            "wid": ws_id,
            "name": name,
            "url": url,
            "login": {
                "id_input": self._captured.get("id_input", ""),
                "pw_input": self._captured.get("pw_input", ""),
                "login_btn": self._captured.get("login_btn", ""),
            },
            "search": {
                "search_input": self._captured.get("search_input", ""),
                "search_btn": "",
            },
            "table": {
                "layout_mode": "row_cart_btn",
                "result_rows": "",
                "cart_btn_in_row": cart_sel,
                "global_cart_btn": "",
                "row_checkbox_in_row": "",
                "qty_input_in_row": "",
                "cart_rows_sel": "",
                "schema_version": "v1.5.46",
                "auto_detected": False,
                "recorded_by_wizard": True,
            },
            "confirm": {
                "confirm_btn": "",
            },
        }

        # 빈 필드 경고
        missing = [k for k, v in self._captured.items() if not v]
        if missing:
            ans = QMessageBox.question(
                self, "미완성 셀렉터",
                f"다음 항목이 비어 있습니다: {', '.join(missing)}\n그래도 업로드하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans == QMessageBox.StandardButton.No:
                return

        # JSON 미리보기
        preview = json.dumps(selector_json, ensure_ascii=False, indent=2)
        ans = QMessageBox.question(
            self, "업로드 확인",
            f"아래 셀렉터를 Supabase에 업로드합니다.\n\n{preview[:400]}...\n\n계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.No:
            return

        try:
            from core.cloud import _api_url, _headers
            import requests
            # 기존 항목 upsert
            resp = requests.post(
                _api_url("wholesaler_selectors"),
                headers={**_headers(), "Prefer": "resolution=merge-duplicates"},
                json=selector_json,
                timeout=15,
            )
            if 200 <= resp.status_code < 300:
                QMessageBox.information(
                    self, "업로드 완료",
                    f"{name} 셀렉터가 Supabase에 저장되었습니다.\n"
                    "팜오토를 재시작하면 모든 고객에게 즉시 적용됩니다."
                )
                self._upload_btn.setEnabled(False)
            else:
                QMessageBox.warning(self, "업로드 실패", f"HTTP {resp.status_code}\n{resp.text[:200]}")
        except Exception as e:
            QMessageBox.critical(self, "업로드 오류", str(e))

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        super().closeEvent(event)
