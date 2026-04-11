"""자동 주문 탭 - 처방 데이터 조회, 약품 리스트, 일괄 주문."""

import json
import math
import os
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.styles import (
    BLUE as _BLUE, BLUE_DARK as _BLUE_DARK,
    GREEN as _GREEN, GREEN_DARK as _GREEN_DARK,
    RED as _RED, ORANGE as _ORANGE, TEXT_SEC as _TEXT_SEC, TEXT_DISABLED,
    CARD_FRAME, STATUS_LABEL, SUBTITLE,
    COMBO_SMALL, SPIN_BOX_SMALL,
    btn_primary, btn_success, btn_order,
)

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

ORDER_TYPE_LABELS = {
    "immediate": "즉시",
    "stock": "적정재고",
    "manual": "수동",
    "exclude": "자동주문 제외",
}


def _load_json(filename):
    path = os.path.join(CONFIG_DIR, filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_json(filename, data):
    path = os.path.join(CONFIG_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


from ui.spinner import SpinnerOverlay


# ────────────── 선호규격 4배 초과 확인 ──────────────

OVERSIZE_RATIO = 4  # 필요 수량이 선호규격의 N배 이상이면 확인


def _get_unit_options(insurance_code: str) -> list[int]:
    """약품의 규격 목록을 캐시에서 가져온다 (unit_cache → drug_preferences 순)."""
    import json as _json

    # 1) unit_cache.json
    cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "unit_cache.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = _json.load(f)
        if insurance_code in cache:
            return sorted(cache[insurance_code])

    # 2) drug_preferences.json
    prefs_path = os.path.join(os.path.dirname(__file__), "..", "data", "drug_preferences.json")
    if os.path.exists(prefs_path):
        with open(prefs_path, "r", encoding="utf-8") as f:
            prefs = _json.load(f)
        entry = prefs.get(insurance_code, {})
        if entry.get("unit_options"):
            return sorted(entry["unit_options"])

    return []


def _check_oversize_items(items: list[dict], parent=None) -> list[dict] | None:
    """선호규격 대비 4배 이상 주문이 필요한 약품이 있으면 사용자에게 물어본다.

    Returns:
        수정된 items 리스트. 사용자가 취소하면 None.
    """
    oversize = []
    for item in items:
        pref = item.get("preferred_unit", 0)
        if pref and item["qty"] >= pref * OVERSIZE_RATIO:
            units = _get_unit_options(item["insurance_code"])
            oversize.append({**item, "unit_options": units})

    if not oversize:
        return items

    dlg = OversizeDialog(oversize, parent=parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None  # 취소

    # 사용자가 선택한 규격을 preferred_unit에 반영
    choices = dlg.get_choices()
    for item in items:
        code = item["insurance_code"]
        if code in choices:
            item["preferred_unit"] = choices[code]

    return items


class OversizeDialog(QDialog):
    """선호규격 4배 초과 약품 — 실제 규격 옵션으로 주문 방식 선택."""

    def __init__(self, oversize_items: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("규격 확인")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "아래 약품은 필요 수량이 선호규격보다 많습니다.\n"
            "어떤 규격으로 주문할지 선택해주세요."
        ))

        self._radios = {}  # {insurance_code: [(radio, pack_size), ...]}
        for item in oversize_items:
            code = item["insurance_code"]
            name = item.get("drug_name", code)
            pref = item["preferred_unit"]
            qty = item["qty"]
            units = item.get("unit_options", [])

            # 규격 목록 구성: 선호규격 + 캐시된 규격들
            pack_sizes = sorted(set([pref] + units)) if units else [pref]

            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            fl = QVBoxLayout(frame)
            fl.addWidget(QLabel(f"<b>{name}</b>  —  필요: {qty}정"))

            radios = []
            for ps in pack_sizes:
                boxes = math.ceil(qty / ps)
                radio = QRadioButton(f"{ps}정 × {boxes}박스 주문")
                if ps == pref:
                    radio.setChecked(True)
                fl.addWidget(radio)
                radios.append((radio, ps))

            self._radios[code] = radios
            layout.addWidget(frame)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_choices(self) -> dict:
        """각 약품에 대해 사용자가 선택한 규격(pack_size)을 반환."""
        choices = {}
        for code, radios in self._radios.items():
            for radio, pack_size in radios:
                if radio.isChecked():
                    choices[code] = pack_size
                    break
        return choices


class FetchWorker(QThread):
    """처방 데이터 + API 조회를 백그라운드에서 실행."""
    finished = pyqtSignal(list)
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, time_range):
        super().__init__()
        self.time_range = time_range

    def run(self):
        try:
            from core.db_reader import fetch_last_month_usage, fetch_prescriptions
            from core.drug_api import get_drug_names

            self.progress.emit("DB 연결 중...")
            prescriptions = fetch_prescriptions(self.time_range)
            self.progress.emit(f"출고 {len(prescriptions)}건 조회 완료, 전월 데이터 조회 중...")
            last_month = fetch_last_month_usage()

            # 통합 약품명 조회 (캐시 → DB → API 순)
            codes = [rx["insurance_code"] for rx in prescriptions]
            self.progress.emit("약품명 조회 중...")
            drug_names = get_drug_names(codes)

            results = []
            for rx in prescriptions:
                code = rx["insurance_code"]
                results.append({
                    "insurance_code": code,
                    "drug_name": drug_names.get(code, code),
                    "spec": "",
                    "qty": rx["total_qty"],
                    "last_month_qty": last_month.get(code, 0),
                })

            self.finished.emit(results)
        except Exception as e:
            print(f"[주문탭] DB 조회 실패 -> 데모 전환: {e}")
            self.error.emit("DB_FALLBACK")


class OrderWorker(QThread):
    """선택 약품 주문 백그라운드 실행."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, order_items: list[dict], dry_run: bool):
        super().__init__()
        self.order_items = order_items
        self.dry_run = dry_run

    def run(self):
        try:
            from core.order_engine import place_orders

            mode_text = "장바구니 담기" if self.dry_run else "주문"
            self.progress.emit(f"{len(self.order_items)}개 약품 {mode_text} 시작...")

            results, retry_results = place_orders(
                self.order_items,
                progress_callback=lambda msg: self.progress.emit(msg),
                dry_run=self.dry_run,
            )

            # 성공한 아이템만 재고 업데이트
            from core.inventory import update_stock_after_order

            def _update_stock(item):
                code = item.get("insurance_code", "")
                pack_size = item.get("pack_size", 0)
                box_qty = item.get("box_qty", 0)
                if pack_size and box_qty:
                    actual_qty = box_qty * pack_size
                else:
                    actual_qty = item.get("qty", 0)
                if code and actual_qty > 0:
                    update_stock_after_order(code, actual_qty)

            for r in results:
                for item in r.get("success_items", []):
                    _update_stock(item)

            # 품절 재주문 성공한 아이템도 재고 반영
            for rr in retry_results:
                if rr.get("success"):
                    _update_stock(rr["item"])

            # results에 retry_results 첨부해서 UI에 전달
            self.finished.emit([results, retry_results])
        except Exception as e:
            self.error.emit(str(e))


EXCLUDE_OPTIONS = {
    "없음": None,
    "1주": 7,
    "2주": 14,
    "1달": 30,
    "3달": 90,
    "영구": -1,
}


def _card(widget: QWidget) -> QFrame:
    card = QFrame()
    card.setStyleSheet(CARD_FRAME)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 20, 20, 20)
    lay.addWidget(widget)
    return card


class OrderTab(QWidget):
    def __init__(self):
        super().__init__()
        self.drug_data = []
        self.wholesalers = _load_json("wholesalers.json")
        self.exclusions = _load_json("exclusions.json")
        self._on_schedule_changed_callback = None
        self._init_ui()
        self._spinner = SpinnerOverlay(self)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self._load_order_history()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # --- 상단 컨트�� 카드 ---
        top_widget = QWidget()
        top = QHBoxLayout(top_widget)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)

        time_label = QLabel("시간대")
        time_label.setStyleSheet(SUBTITLE)
        top.addWidget(time_label)

        self.time_combo = QComboBox()
        self.time_combo.addItems(["오늘 전체", "오전 (09~13시)", "오후 (13~19시)", "어제 전체"])
        self.time_combo.setMinimumWidth(150)
        top.addWidget(self.time_combo)

        self.fetch_btn = QPushButton("처방 데이터 조회")
        self.fetch_btn.setStyleSheet(btn_primary())
        self.fetch_btn.clicked.connect(self._on_fetch)
        top.addWidget(self.fetch_btn)

        top.addStretch()

        ws_label = QLabel("기본 도매상")
        ws_label.setStyleSheet(SUBTITLE)
        top.addWidget(ws_label)

        self.bulk_ws_combo = QComboBox()
        self._populate_ws_combo(self.bulk_ws_combo)
        self.bulk_ws_combo.setMinimumWidth(130)
        self._sync_bulk_ws_from_settings()
        self.bulk_ws_combo.currentIndexChanged.connect(
            self._on_bulk_ws_changed
        )
        top.addWidget(self.bulk_ws_combo)

        bulk_btn = QPushButton("일괄 적용")
        bulk_btn.clicked.connect(self._on_bulk_apply)
        top.addWidget(bulk_btn)

        top_card = _card(top_widget)
        layout.addWidget(top_card)

        # --- 예약 자동주문 상태 카드 ---
        sched_widget = QWidget()
        sched_outer = QVBoxLayout(sched_widget)
        sched_outer.setContentsMargins(4, 4, 4, 4)
        sched_outer.setSpacing(8)

        # 1행: 토글 + 상세설정 버튼
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        self.sched_toggle = QCheckBox("예약 자동주문")
        self.sched_toggle.setStyleSheet(
            "QCheckBox { font-size: 14px; font-weight: 700; "
            "font-family: 'Malgun Gothic'; padding: 2px 0; }"
        )
        self.sched_toggle.setMinimumHeight(28)
        self.sched_toggle.toggled.connect(self._on_sched_toggle_changed)
        row1.addWidget(self.sched_toggle)

        row1.addStretch()

        self.sched_detail_btn = QPushButton("상세 설정 →")
        self.sched_detail_btn.setStyleSheet(
            f"QPushButton {{ color: {_BLUE}; background: transparent; "
            f"border: none; font-size: 13px; font-weight: 600; "
            f"font-family: 'Malgun Gothic'; padding: 4px 8px; }}"
            f"QPushButton:hover {{ text-decoration: underline; "
            f"color: {_BLUE_DARK}; }}"
        )
        row1.addWidget(self.sched_detail_btn)
        sched_outer.addLayout(row1)

        # 2행: 설정 요약 (예약 시간 / 주문확정 / 도매상 분배)
        self.sched_summary = QLabel("")
        self.sched_summary.setStyleSheet(
            f"color: {_TEXT_SEC}; font-size: 12px; "
            f"font-family: 'Malgun Gothic'; line-height: 1.5;"
        )
        self.sched_summary.setWordWrap(True)
        sched_outer.addWidget(self.sched_summary)

        sched_card = _card(sched_widget)
        layout.addWidget(sched_card)

        self._refresh_schedule_summary()

        # --- 약품 테이블 카드 ---
        # [선택][약품명][선호규격][주문타입][오늘사용][현재재고][추천주문량][도매상][자동주문 제외]
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "선택", "약품명", "선호규격", "주문타입", "오늘사용",
            "현재재고", "추천주문량", "도매상", "자동주문 제외",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 50)

        # 헤더 "선택" 클릭 시 전체 선택/해제 토글
        self._all_checked = True
        header.sectionClicked.connect(self._on_header_clicked)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 100)
        self.table.setColumnWidth(7, 140)
        self.table.setColumnWidth(8, 140)

        self.table.setMinimumHeight(500)
        table_card = _card(self.table)
        layout.addWidget(table_card)

        # --- 하단 버튼 카드 ---
        bottom_widget = QWidget()
        bottom = QHBoxLayout(bottom_widget)
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(12)

        self.status_label = QLabel("처방 데이터를 조회하세요")
        self.status_label.setStyleSheet(STATUS_LABEL)
        bottom.addWidget(self.status_label)

        bottom.addStretch()

        self.order_btn = QPushButton("선택한 약품 주문하기")
        self.order_btn.setStyleSheet(btn_order())
        self.order_btn.clicked.connect(self._on_order)
        bottom.addWidget(self.order_btn)

        bottom_card = _card(bottom_widget)
        layout.addWidget(bottom_card)

        # --- 주문 내역 카드 ---
        history_widget = QWidget()
        history_lay = QVBoxLayout(history_widget)
        history_lay.setContentsMargins(0, 0, 0, 0)
        history_lay.setSpacing(8)

        history_top = QHBoxLayout()
        history_title = QLabel("주문 내역")
        history_title.setStyleSheet(SUBTITLE)
        history_top.addWidget(history_title)

        self.history_period_combo = QComboBox()
        self.history_period_combo.addItems(["오늘", "최근 7일", "최근 30일"])
        self.history_period_combo.setMinimumWidth(110)
        self.history_period_combo.setStyleSheet(COMBO_SMALL)
        self.history_period_combo.currentIndexChanged.connect(self._load_order_history)
        history_top.addWidget(self.history_period_combo)

        history_top.addStretch()
        history_lay.addLayout(history_top)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels([
            "주문일시", "약품명", "보험코드", "수량", "주문박스", "도매상", "상태",
        ])
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setShowGrid(False)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        h_header = self.history_table.horizontalHeader()
        h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history_table.setColumnWidth(0, 140)
        self.history_table.setColumnWidth(2, 100)
        self.history_table.setColumnWidth(3, 70)
        self.history_table.setColumnWidth(4, 100)
        self.history_table.setColumnWidth(5, 100)
        self.history_table.setColumnWidth(6, 110)
        self.history_table.setMinimumHeight(300)
        history_lay.addWidget(self.history_table)

        history_card = _card(history_widget)
        layout.addWidget(history_card)

        # --- 사용량 조회 카드 ---
        usage_widget = QWidget()
        usage_lay = QVBoxLayout(usage_widget)
        usage_lay.setContentsMargins(0, 0, 0, 0)
        usage_lay.setSpacing(8)

        usage_title = QLabel("사용량 조회")
        usage_title.setStyleSheet(SUBTITLE)
        usage_lay.addWidget(usage_title)

        search_row = QHBoxLayout()
        self.usage_search = QLineEdit()
        self.usage_search.setPlaceholderText("약품명 또는 보험코드 검색")
        self.usage_search.setMinimumWidth(250)
        self.usage_search.setMinimumHeight(34)
        self.usage_search.returnPressed.connect(self._on_usage_search)
        search_row.addWidget(self.usage_search)

        usage_btn = QPushButton("조회")
        usage_btn.setStyleSheet(btn_primary())
        usage_btn.setMinimumHeight(34)
        usage_btn.clicked.connect(self._on_usage_search)
        search_row.addWidget(usage_btn)
        search_row.addStretch()
        usage_lay.addLayout(search_row)

        self.usage_table = QTableWidget()
        self.usage_table.setColumnCount(5)
        self.usage_table.setHorizontalHeaderLabels([
            "보험코드", "약품명", "이번주", "이번달", "저번달",
        ])
        self.usage_table.verticalHeader().setVisible(False)
        self.usage_table.setShowGrid(False)
        self.usage_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        u_header = self.usage_table.horizontalHeader()
        u_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.usage_table.setColumnWidth(0, 110)
        self.usage_table.setColumnWidth(2, 80)
        self.usage_table.setColumnWidth(3, 80)
        self.usage_table.setColumnWidth(4, 80)
        self.usage_table.setMinimumHeight(200)
        usage_lay.addWidget(self.usage_table)

        usage_card = _card(usage_widget)
        layout.addWidget(usage_card)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _populate_ws_combo(self, combo: QComboBox):
        combo.clear()
        for wid, ws in self.wholesalers.items():
            combo.addItem(ws["name"], wid)

    def _time_range_key(self) -> str:
        idx = self.time_combo.currentIndex()
        return ["all", "morning", "afternoon", "yesterday"][idx]

    # ─────────────── 처방 데이터 조회 ───────────────

    def _on_fetch(self):
        self.fetch_btn.setEnabled(False)
        self._spinner.show_with_message("처방 데이터 조회 중...")

        self.worker = FetchWorker(self._time_range_key())
        self.worker.progress.connect(self._on_fetch_progress)
        self.worker.finished.connect(self._on_fetch_done)
        self.worker.error.connect(self._on_fetch_error)
        self.worker.start()

    def _on_fetch_progress(self, msg: str):
        self.status_label.setText(msg)
        self._spinner.set_message(msg)

    def _on_fetch_done(self, data: list):
        self.fetch_btn.setEnabled(True)
        self._spinner.hide_spinner()

        now = datetime.now()
        filtered = []
        for item in data:
            code = item["insurance_code"]
            exc = self.exclusions.get(code)
            if exc:
                until = exc.get("exclude_until")
                if until == "permanent":
                    continue
                if until and datetime.strptime(until, "%Y-%m-%d") > now:
                    continue
                else:
                    del self.exclusions[code]
                    _save_json("exclusions.json", self.exclusions)
            filtered.append(item)

        self.drug_data = filtered
        self._register_new_drugs(filtered)
        self._populate_table(reset_checks=True)
        self.status_label.setText(
            f"총 {len(filtered)}개 약품 조회됨 (제외 {len(data) - len(filtered)}건)"
        )

    def _on_fetch_error(self, msg: str):
        self.fetch_btn.setEnabled(True)
        self._spinner.hide_spinner()
        demo = self._get_demo_data()
        self._on_fetch_done(demo)
        self.status_label.setText(f"[데모 모드] DB 미연결 - {len(demo)}개 샘플 약품 표시")

    def _get_demo_data(self):
        return [
            {"insurance_code": "646201260", "drug_name": "아세젠정(아세클로페낙)", "spec": "정", "qty": 45, "last_month_qty": 120},
            {"insurance_code": "643501890", "drug_name": "엑소페리정50밀리그램", "spec": "정", "qty": 14, "last_month_qty": 100},
            {"insurance_code": "643503860", "drug_name": "한미파모티딘정20밀리그램", "spec": "정", "qty": 30, "last_month_qty": 80},
            {"insurance_code": "643500700", "drug_name": "리마몬정", "spec": "정", "qty": 8, "last_month_qty": 40},
            {"insurance_code": "643503470", "drug_name": "모사잘정5밀리그램", "spec": "정", "qty": 20, "last_month_qty": 35},
        ]

    # ─────────────── 신규 약품 자동 등록 ───────────────

    def _register_new_drugs(self, drugs: list[dict]):
        """처방 조회 결과에서 inventory에 없는 약품을 자동 등록한다.

        즉시주문(immediate) 타입으로 기본 등록하여,
        설정 탭의 약품 재고/주문 관리 목록에 자동으로 나타나게 한다.
        """
        from core.inventory import is_configured, set_drug_config

        new_count = 0
        for drug in drugs:
            code = drug["insurance_code"]
            if is_configured(code):
                continue

            set_drug_config(code, {
                "name": drug.get("drug_name", ""),
                "order_type": "immediate",
                "preferred_unit": 0,
                "target_stock": 0,
                "unit": "정",
                "base_stock": 0,
                "current_stock": 0,
                "app_order_stock": 0,
                "tracking_start_date": datetime.now().strftime("%Y-%m-%d"),
            })
            new_count += 1

        if new_count:
            print(f"[주문탭] 신규 약품 {new_count}건 자동 등록 (즉시주문)")

    # ─────────────── 테이블 ───────────────

    def _populate_table(self, reset_checks: bool = False):
        from core.inventory import get_current_stock, get_drug_config

        # 처방 데이터 새로 조회 시 체크 리셋, 설정 변경 등은 보존
        saved_checks = {}
        if not reset_checks:
            for row in range(self.table.rowCount()):
                widget = self.table.cellWidget(row, 0)
                if widget and row < len(self.drug_data):
                    cb = widget.findChild(QCheckBox)
                    if cb:
                        code = self.drug_data[row]["insurance_code"]
                        saved_checks[code] = cb.isChecked()

        _default_ws = _load_json("settings.json").get("default_wholesaler", "")

        # 오늘 주문 이력 — 상태별 분리
        from core.order_engine import get_order_history
        today_orders = get_order_history(1)
        order_status_map = {}  # code → "ordered" / "cart_only" / "out_of_stock" / "failed"
        for oh in today_orders:
            c = oh.get("insurance_code", "")
            s = oh.get("status", "")
            if c:
                # 같은 약품이 여러 번 있으면 성공이 우선
                existing = order_status_map.get(c, "")
                if s in ("ordered", "cart_only") or not existing:
                    order_status_map[c] = s

        self.table.setRowCount(len(self.drug_data))
        for row, item in enumerate(self.drug_data):
            code = item["insurance_code"]
            today_qty = int(item["qty"])
            cfg = get_drug_config(code)

            # 주문량 계산 (재고는 STOCKDATE 기반 실시간)
            if cfg:
                order_type = cfg.get("order_type", "immediate")
                current_stock = get_current_stock(code)
                pref_unit = cfg.get("preferred_unit", 0)
                from tabs.drug_setup_dialog import _guess_unit
                saved_unit = cfg.get("unit", "")
                drug_unit = saved_unit if (saved_unit and saved_unit != "정") else _guess_unit(item["drug_name"])
                spec_text = f"{pref_unit}{drug_unit}" if pref_unit else item.get("spec", "")

                if order_type == "immediate":
                    recommended = today_qty
                elif order_type == "stock":
                    target = cfg.get("target_stock", 0)
                    recommended = max(0, target - current_stock)
                elif order_type == "manual":
                    recommended = 0
                else:
                    recommended = today_qty
            else:
                order_type = ""
                recommended = today_qty
                current_stock = 0
                pref_unit = 0
                spec_text = item.get("spec", "")

            # 적정재고에서 재고 충분하면 주문 불필요
            stock_sufficient = (order_type == "stock" and recommended == 0)
            is_manual = (order_type == "manual")
            order_st = order_status_map.get(code, "")
            order_success = order_st in ("ordered", "cart_only")
            order_failed = order_st in ("failed", "out_of_stock")

            # 체크박스
            # 재고 충분/수동/주문완료는 항상 해제 (saved_checks보다 우선)
            cb = QCheckBox()
            if stock_sufficient or is_manual:
                cb.setChecked(False)
            elif order_success:
                cb.setChecked(False)
            elif code in saved_checks:
                cb.setChecked(saved_checks[code])
            else:
                cb.setChecked(True)
            cb.setFixedSize(20, 20)
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 0, cb_widget)

            # 약품명
            name_item = QTableWidgetItem(item["drug_name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(row, 1, name_item)

            # 선호규격 (클릭 가능)
            spec_item = QTableWidgetItem(spec_text)
            spec_item.setFlags(spec_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            spec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            spec_item.setToolTip("클릭하여 설정 변경")
            if not cfg:
                spec_item.setForeground(QColor(_BLUE))
                spec_item.setText("설정 필요")
            self.table.setItem(row, 2, spec_item)

            # 주문타입
            if order_success:
                type_text = "장바구니완료" if order_st == "cart_only" else "주문완료"
            elif order_st == "out_of_stock":
                type_text = "품절"
            elif order_failed:
                type_text = "주문실패"
            else:
                type_text = ORDER_TYPE_LABELS.get(order_type, "미설정")
            type_item = QTableWidgetItem(type_text)
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            if order_success:
                type_item.setForeground(QColor(_GREEN) if order_st == "ordered" else QColor(_BLUE))
            elif order_st == "out_of_stock":
                type_item.setForeground(QColor(_ORANGE))
            elif order_failed:
                type_item.setForeground(QColor(_RED))
            elif not cfg:
                type_item.setForeground(QColor(_RED))
            self.table.setItem(row, 3, type_item)

            # 오늘 사용
            used_item = QTableWidgetItem(str(today_qty))
            used_item.setFlags(used_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            used_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 4, used_item)

            # 현재 재고 (클릭 가능)
            stock_item = QTableWidgetItem(str(current_stock))
            stock_item.setFlags(stock_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            stock_item.setToolTip("클릭하여 재고 수동 입력")
            if cfg and order_type == "stock":
                target = cfg.get("target_stock", 0)
                if current_stock < target:
                    stock_item.setForeground(QColor(_RED))
                else:
                    stock_item.setForeground(QColor(_GREEN))
            self.table.setItem(row, 5, stock_item)

            # 추천 주문량 (스핀박스)
            qty_spin = QSpinBox()
            qty_spin.setRange(0, 9999)
            qty_spin.setValue(max(0, recommended))
            qty_spin.setMinimumWidth(80)
            qty_spin.setMinimumHeight(34)
            qty_spin.setStyleSheet(SPIN_BOX_SMALL)
            if is_manual:
                qty_spin.setValue(0)
            self.table.setCellWidget(row, 6, qty_spin)

            # 도매상
            ws_combo = QComboBox()
            ws_combo.setMinimumWidth(120)
            ws_combo.setMinimumHeight(34)
            ws_combo.setStyleSheet(COMBO_SMALL)
            self._populate_ws_combo(ws_combo)
            if _default_ws:
                idx = ws_combo.findData(_default_ws)
                if idx >= 0:
                    ws_combo.setCurrentIndex(idx)
            self.table.setCellWidget(row, 7, ws_combo)

            # 자동주문 제외
            exc_combo = QComboBox()
            exc_combo.setMinimumWidth(120)
            exc_combo.setMinimumHeight(34)
            exc_combo.setStyleSheet(COMBO_SMALL)
            for label in EXCLUDE_OPTIONS:
                exc_combo.addItem(label)
            exc_combo.currentTextChanged.connect(
                lambda text, r=row: self._on_exclude_changed(r, text)
            )
            self.table.setCellWidget(row, 8, exc_combo)

            self.table.setRowHeight(row, 48)

            # 재고 충분 시 행 회색 처리
            if stock_sufficient:
                for col in range(self.table.columnCount()):
                    it = self.table.item(row, col)
                    if it:
                        it.setForeground(QColor(TEXT_DISABLED))

    # ─────────────── 셀 클릭 → 설정 팝업 ───────────────

    def _on_cell_clicked(self, row: int, col: int):
        if row >= len(self.drug_data):
            return
        # 약품명(1) 클릭 시 수기 입력
        if col == 1:
            self._edit_drug_name(row)
        # 선호규격(2) 또는 주문타입(3) 클릭 시 설정 팝업
        elif col in (2, 3):
            self._show_drug_setup(row)
        # 현재 재고(5) 클릭 시 재고 입력 팝업
        elif col == 5:
            self._show_stock_input(row)

    def _edit_drug_name(self, row: int):
        from PyQt6.QtWidgets import QInputDialog

        item = self.drug_data[row]
        code = item["insurance_code"]
        current_name = item["drug_name"]

        name, ok = QInputDialog.getText(
            self, "약품명 입력",
            f"보험코드: {code}\n약품명을 입력하세요:",
            text=current_name,
        )
        if ok and name.strip():
            name = name.strip()
            # drug_data 업데이트
            item["drug_name"] = name
            self.table.item(row, 1).setText(name)

            # drug_cache에 저장
            # 통합 캐시에 저장
            from core.drug_api import save_drug_name
            save_drug_name(code, name)

    def _show_drug_setup(self, row: int):
        from core.inventory import get_drug_config, set_drug_config
        from tabs.drug_setup_dialog import DrugSetupDialog

        item = self.drug_data[row]
        code = item["insurance_code"]
        drug_name = item["drug_name"]
        today_qty = int(item["qty"])

        cfg = get_drug_config(code) or {}

        # 규격 옵션: 캐시에서만 가져옴 (없으면 빈 채로 팝업 - 느린 조회 안 함)
        unit_options = cfg.get("unit_options", [])

        dlg = DrugSetupDialog(
            drug_name=drug_name,
            insurance_code=code,
            today_qty=today_qty,
            unit_options=unit_options if unit_options else None,
            current_config=cfg,
            parent=self,
        )

        if dlg.exec() == DrugSetupDialog.DialogCode.Accepted and dlg.result_config:
            if dlg.result_config["order_type"] == "exclude":
                # 제외 목록에 추가하고 테이블에서 제거
                self.exclusions[code] = {"exclude_until": "permanent", "reason": "자동주문 제외", "drug_name": drug_name}
                _save_json("exclusions.json", self.exclusions)
                self.drug_data.pop(row)
                self.table.removeRow(row)
                self.status_label.setText(
                    f"'{drug_name}' 자동주문 제외 처리됨 (남은 {len(self.drug_data)}개)"
                )
                return

            # dialog 내에서 재고가 변경됐을 수 있으므로 최신 cfg를 다시 읽는다
            fresh_cfg = get_drug_config(code) or cfg

            new_cfg = {
                **fresh_cfg,
                "name": drug_name,
                "order_type": dlg.result_config["order_type"],
                "preferred_unit": dlg.result_config["preferred_unit"],
                "unit_options": dlg.result_config["unit_options"] or unit_options,
                "target_stock": dlg.result_config["target_stock"],
                "unit": dlg.result_config.get("unit", "정"),
                "tracking_start_date": fresh_cfg.get(
                    "tracking_start_date", datetime.now().strftime("%Y-%m-%d")
                ),
            }
            set_drug_config(code, new_cfg)
            self._populate_table()

    def _show_stock_input(self, row: int):
        from core.inventory import (
            get_current_stock,
            get_drug_config,
            set_current_stock,
            set_drug_config,
        )
        from tabs.stock_input_dialog import StockInputDialog

        item = self.drug_data[row]
        code = item["insurance_code"]
        drug_name = item["drug_name"]

        cfg = get_drug_config(code)
        current = get_current_stock(code) if cfg else 0
        unit_options = cfg.get("unit_options", []) if cfg else []
        pref_unit = cfg.get("preferred_unit", 0) if cfg else 0

        from tabs.drug_setup_dialog import _guess_unit
        if cfg:
            saved_unit = cfg.get("unit", "")
            drug_unit = saved_unit if (saved_unit and saved_unit != "정") else _guess_unit(drug_name)
        else:
            drug_unit = _guess_unit(drug_name)

        dlg = StockInputDialog(
            drug_name=drug_name,
            insurance_code=code,
            current_stock=current,
            unit_options=unit_options if unit_options else None,
            preferred_unit=pref_unit,
            unit=drug_unit,
            parent=self,
        )

        if dlg.exec() == StockInputDialog.DialogCode.Accepted and dlg.result_stock is not None:
            # 설정 없으면 기본 설정 자동 생성
            if not cfg:
                set_drug_config(code, {
                    "name": drug_name,
                    "order_type": "immediate",
                    "preferred_unit": 0,
                    "unit_options": [],
                    "target_stock": 0,
                    "current_stock": 0,
                    "tracking_start_date": datetime.now().strftime("%Y-%m-%d"),
                })
            set_current_stock(code, dlg.result_stock)
            self._populate_table()

    def _fetch_unit_options(self, insurance_code: str) -> list[int]:
        """지오영에서 보험코드의 가능한 규격 목록을 조회한다."""
        import asyncio
        import re

        from playwright.async_api import async_playwright

        def _parse_pack(text):
            m = re.search(r'(\d+)\s*[TtCc]', text)
            return int(m.group(1)) if m else 0

        async def _fetch():
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()

            ws = _load_json("wholesalers.json").get("geo", {})
            await page.goto("https://bpm.geoweb.kr/", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            await page.fill('#LoginID', ws.get("id", ""))
            await page.fill('#Password', ws.get("pw", ""))
            await page.click('button.btn_login')
            await page.wait_for_timeout(3000)

            await page.fill('#txt_product', insurance_code)
            await page.click('button.btn_search')
            await page.wait_for_timeout(2000)

            rows = await page.query_selector_all('#tbodySearchProduct tr.tr-product-list')
            units = []
            for row in rows:
                std_el = await row.query_selector('td.standard')
                if std_el:
                    std_text = (await std_el.inner_text()).strip()
                    size = _parse_pack(std_text)
                    if size > 0:
                        units.append(size)

            await browser.close()
            await pw.stop()
            return sorted(set(units))

        try:
            return asyncio.run(_fetch())
        except Exception as e:
            print(f"[규격조회 실패] {insurance_code}: {e}")
            return []

    # ─────────────── 제외 처리 ───────────────

    def _on_exclude_changed(self, row: int, text: str):
        days = EXCLUDE_OPTIONS.get(text)
        if days is None:
            return

        # row 인덱스가 밀릴 수 있으므로 보험코드로 실제 행을 찾는다
        combo = self.sender()
        actual_row = None
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 8) is combo:
                actual_row = r
                break
        if actual_row is None or actual_row >= len(self.drug_data):
            return

        code = self.drug_data[actual_row]["insurance_code"]
        drug_name = self.drug_data[actual_row]["drug_name"]

        # 확인 다이얼로그
        period = "영구" if days == -1 else text
        reply = QMessageBox.question(
            self, "제외 확인",
            f"'{drug_name}'을(를) {period} 자동주문 제외하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            # 취소 → 콤보박스를 "없음"으로 복원
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
            return

        if days == -1:
            self.exclusions[code] = {"exclude_until": "permanent", "reason": "영구 제외", "drug_name": drug_name}
        else:
            until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
            self.exclusions[code] = {"exclude_until": until, "reason": text, "drug_name": drug_name}

        _save_json("exclusions.json", self.exclusions)
        self.drug_data.pop(actual_row)
        self.table.removeRow(actual_row)
        self.status_label.setText(f"'{drug_name}' {period} 제외 처리됨 (남은 {len(self.drug_data)}개)")

    # ─────────────── 기본 도매상 연동 ───────────────

    def _sync_bulk_ws_from_settings(self):
        """settings.json의 default_wholesaler를 bulk_ws_combo에 반영한다."""
        settings = _load_json("settings.json")
        default_ws = settings.get("default_wholesaler", "")
        if default_ws:
            idx = self.bulk_ws_combo.findData(default_ws)
            if idx >= 0:
                self.bulk_ws_combo.blockSignals(True)
                self.bulk_ws_combo.setCurrentIndex(idx)
                self.bulk_ws_combo.blockSignals(False)

    def _on_bulk_ws_changed(self):
        """기본 도매상 콤보 변경 → settings.json 저장 + 설정 탭 동기화."""
        wid = self.bulk_ws_combo.currentData()
        if not wid:
            return
        settings = _load_json("settings.json")
        settings["default_wholesaler"] = wid
        _save_json("settings.json", settings)
        # 예약 요약도 갱신
        self._refresh_schedule_summary()
        # 설정 탭 동기화
        if self._on_schedule_changed_callback:
            self._on_schedule_changed_callback()

    def _on_bulk_apply(self):
        wid = self.bulk_ws_combo.currentData()
        if not wid:
            return
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 7)
            if isinstance(combo, QComboBox):
                idx = combo.findData(wid)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

    # ─────────────── 전체 선택/해제 ───────────────

    def _on_header_clicked(self, section: int):
        """헤더 '선택' 컬럼 클릭 시 전체 선택/해제 토글."""
        if section != 0:
            return
        self._all_checked = not self._all_checked
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb:
                    cb.setChecked(self._all_checked)

    # ─────────────── 수동 주문 ───────────────

    def _on_order(self):
        items = self._collect_selected_items()
        if not items:
            QMessageBox.information(self, "알림", "선택된 약품이 없습니다.")
            return

        summary = {}
        for item in items:
            ws_name = item["wholesaler_name"]
            summary.setdefault(ws_name, []).append(item)

        from core.order_engine import is_cart_only_mode
        order_mode = "장바구니 담기" if is_cart_only_mode() else "자동 주문 확정"
        msg = f"다음과 같이 주문하시겠습니까? ({order_mode})\n\n"
        for ws_name, ws_items in summary.items():
            msg += f"[{ws_name}]\n"
            for it in ws_items:
                msg += f"  - {it['drug_name']}\n"
            msg += "\n"

        msg += f"총 {len(items)}개 품목"

        reply = QMessageBox.question(
            self, "주문 확인", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 선호규격 4배 초과 약품 체크 → 사용자에게 선택 요청
        items = _check_oversize_items(items, parent=self)
        if items is None:
            return  # 사용자가 취소함

        from core.order_engine import is_cart_only_mode

        self.order_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self._spinner.show_progress("처리 중...", 0)
        self._order_percent = 0
        self._order_done = False
        if hasattr(self, '_pending_error'):
            del self._pending_error
        if hasattr(self, '_pending_results'):
            del self._pending_results

        # 0→95까지 일정하게 올라감
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._tick_progress)
        self._progress_timer.start(300)

        self._order_worker = OrderWorker(items, dry_run=is_cart_only_mode())
        self._order_worker.finished.connect(self._on_order_finished)
        self._order_worker.error.connect(self._on_order_error)
        self._order_worker.start()

    def _tick_progress(self):
        p = self._order_percent
        if self._order_done:
            # 완료 신호 후 100%까지 빠르게
            p = min(p + 5, 100)
        elif p < 95:
            p += 1
        self._order_percent = p
        self._spinner.set_progress(p, "처리 중...")
        if p >= 100:
            self._progress_timer.stop()
            if hasattr(self, '_pending_error'):
                QTimer.singleShot(300, self._show_order_error_final)
            else:
                QTimer.singleShot(300, self._show_order_final)

    def _on_order_finished(self, results: list):
        self._pending_results = results
        self._order_done = True

    def _show_order_final(self):
        if hasattr(self, '_progress_timer'):
            self._progress_timer.stop()
        self.order_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self._spinner.hide_spinner()
        data = getattr(self, '_pending_results', [])
        # data = [results, retry_results]
        if data and isinstance(data[0], list):
            results, retry_results = data[0], data[1] if len(data) > 1 else []
        else:
            results, retry_results = data, []
        self._show_order_results(results, retry_results)
        self._populate_table()
        self._load_order_history()

    def _on_order_error(self, msg: str):
        self._pending_error = msg
        self._order_done = True

    def _show_order_error_final(self):
        if hasattr(self, '_progress_timer'):
            self._progress_timer.stop()
        self.order_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self._spinner.hide_spinner()
        msg = getattr(self, '_pending_error', '')
        self.status_label.setText(f"주문 실패: {msg}")
        QMessageBox.critical(self, "주문 오류", f"오류가 발생했습니다:\n{msg}")

    def _collect_selected_items(self) -> list[dict]:
        items = []
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 0)
            if not widget:
                continue
            cb = widget.findChild(QCheckBox)
            if not cb or not cb.isChecked():
                continue

            qty_spin = self.table.cellWidget(row, 6)
            ws_combo = self.table.cellWidget(row, 7)

            if not qty_spin:
                continue
            qty = qty_spin.value()
            if qty == 0:
                qty = 1  # 체크했으면 최소 1개 주문

            data = self.drug_data[row]
            from core.inventory import get_drug_config as _gdc
            _cfg = _gdc(data["insurance_code"])
            items.append({
                "insurance_code": data["insurance_code"],
                "drug_name": data["drug_name"],
                "spec": data.get("spec", ""),
                "qty": qty,
                "preferred_unit": _cfg.get("preferred_unit", 0) if _cfg else 0,
                "wholesaler_id": ws_combo.currentData() if ws_combo else "",
                "wholesaler_name": ws_combo.currentText() if ws_combo else "",
            })
        return items

    def _show_order_results(self, results: list, retry_results: list):
        success_items = []
        failed_items = []
        oos_items = []
        for r in results:
            for it in r.get("success_items", []):
                success_items.append(it)
            for it in r.get("failed_items", []):
                failed_items.append(it)
            for it in r.get("oos_items", []):
                oos_items.append(it)

        msg = ""

        if success_items:
            msg += f"주문 완료 — {len(success_items)}건\n"
            for it in success_items:
                msg += f"  {it.get('drug_name', '')}\n"
            msg += "\n"

        # 품절 재주문 결과
        retry_ok = [rr for rr in retry_results if rr.get("success")]
        retry_fail = [rr for rr in retry_results if not rr.get("success")]

        if retry_ok:
            msg += f"품절 → 대체 주문 성공 — {len(retry_ok)}건\n"
            for rr in retry_ok:
                it = rr["item"]
                msg += f"  {it.get('drug_name', '')} ({rr['original_ws']} → {rr['retry_ws']})\n"
            msg += "\n"

        if retry_fail:
            msg += f"품절 → 대체 주문 실패 — {len(retry_fail)}건\n"
            for rr in retry_fail:
                it = rr["item"]
                msg += f"  {it.get('drug_name', '')} (모든 도매상 품절)\n"
            msg += "\n"

        # 일반 실패 (품절 제외)
        oos_codes = set(it.get("insurance_code", "") for it in oos_items)
        normal_fail = [it for it in failed_items
                       if it.get("insurance_code", "") not in oos_codes]
        if normal_fail:
            msg += f"주문 실패 — {len(normal_fail)}건\n"
            for it in normal_fail:
                msg += f"  {it.get('drug_name', it.get('insurance_code', ''))}\n"
            msg += "\n"

        if not success_items and not failed_items and not retry_results:
            msg = "처리된 항목이 없습니다.\n"

        total_ok = len(success_items) + len(retry_ok)
        total_fail = len(normal_fail) + len(retry_fail)
        self.status_label.setText(
            f"완료 {total_ok}건 / 실패 {total_fail}건"
        )

        # 커스텀 다이얼로그 (더 넓게)
        dlg = QMessageBox(self)
        dlg.setWindowTitle("주문 결과")
        if total_fail > 0 and total_ok == 0:
            dlg.setIcon(QMessageBox.Icon.Warning)
        elif total_fail > 0:
            dlg.setIcon(QMessageBox.Icon.Information)
        else:
            dlg.setIcon(QMessageBox.Icon.Information)
        dlg.setText(msg)
        dlg.setMinimumWidth(400)
        dlg.exec()

        self._load_order_history()

    # ─────────────── 예약 자동주문 연동 ───────────────

    def _refresh_schedule_summary(self):
        """settings.json에서 예약/주문 설정을 읽어 요약 텍스트 + 토글 상태를 갱신한다."""
        settings = _load_json("settings.json")
        ws_map = _load_json("wholesalers.json")
        enabled = settings.get("schedule_enabled", False)

        # 토글 동기화 (시그널 루프 방지)
        self.sched_toggle.blockSignals(True)
        self.sched_toggle.setChecked(enabled)
        self.sched_toggle.blockSignals(False)

        # ── 1) 예약 시간 ──
        if not enabled:
            time_text = "예약 꺼짐"
        else:
            mode = settings.get("schedule_mode", "multiple")
            if mode == "once":
                once_time = settings.get("schedule_once_time", "18:30")
                time_text = f"일 1회 {once_time}"
            else:
                times = settings.get(
                    "schedule_multi_times",
                    settings.get("order_schedule_times", ["13:00", "18:30"]),
                )
                enabled_times = []
                for t in times:
                    if isinstance(t, dict):
                        if t.get("enabled", True):
                            enabled_times.append(t.get("time", "12:00"))
                    else:
                        enabled_times.append(t)
                if enabled_times:
                    time_text = f"일 {len(enabled_times)}회 — {', '.join(enabled_times)}"
                else:
                    time_text = "활성화된 시간 없음"

        # ── 2) 주문 확정 방식 ──
        confirm_mode = settings.get("order_confirm_mode", "auto")
        confirm_text = "장바구니만 담기" if confirm_mode == "cart_only" else "자동 주문 확정"

        # ── 3) 도매상 분배 ──
        split_mode = settings.get("order_split_mode", "single")
        if split_mode == "even":
            split_ws_ids = settings.get("order_split_wholesalers", [])
            ratios = settings.get("order_split_ratios", {})
            if split_ws_ids:
                parts = []
                for wid in split_ws_ids:
                    name = ws_map.get(wid, {}).get("name", wid)
                    r = ratios.get(wid, 5)
                    parts.append(f"{name}({r})")
                split_text = f"균등 분배 — {' : '.join(parts)}"
            else:
                split_text = "균등 분배 (도매상 미지정)"
        else:
            default_ws = settings.get("default_wholesaler", "")
            ws_name = ws_map.get(default_ws, {}).get("name", default_ws) if default_ws else "미지정"
            split_text = f"단일 도매상 — {ws_name}"

        # ── 조합 ──
        summary = f"{time_text}  |  {confirm_text}  |  {split_text}"
        self.sched_summary.setText(summary)

        if enabled:
            self.sched_summary.setStyleSheet(
                f"color: {_BLUE}; font-size: 12px; font-weight: 600; "
                f"font-family: 'Malgun Gothic';"
            )
        else:
            self.sched_summary.setStyleSheet(
                f"color: {_TEXT_SEC}; font-size: 12px; "
                f"font-family: 'Malgun Gothic';"
            )

        # 기본 도매상 콤보도 동기화
        self._sync_bulk_ws_from_settings()

    def _on_sched_toggle_changed(self, checked: bool):
        """자동주문 탭에서 토글 변경 → settings.json 저장 + 요약 갱신."""
        settings = _load_json("settings.json")
        settings["schedule_enabled"] = checked
        _save_json("settings.json", settings)
        self._refresh_schedule_summary()

        if checked:
            QMessageBox.information(
                self,
                "예약 자동주문 켜짐",
                "지금부터 예약 자동주문이 실행됩니다.\n\n"
                "설정 탭에서 설정된 예약 자동주문 시간에\n"
                "설정된 주문 확정 방식으로 자동 실행됩니다.\n\n"
                "설정을 바꾸고 싶으실 경우,\n"
                "설정 탭에서 변경하시면 바로 적용됩니다.",
            )

        # 설정 탭이 이미 로드되어 있으면 거기도 동기화
        if self._on_schedule_changed_callback:
            self._on_schedule_changed_callback()

    def _load_order_history(self):
        """주문 내역을 로드한다."""
        from core.order_engine import get_order_history

        period_map = {0: 1, 1: 7, 2: 30}  # 오늘, 7일, 30일
        days = period_map.get(self.history_period_combo.currentIndex(), 1)
        history = get_order_history(days)

        self.history_table.setRowCount(len(history))
        for row, h in enumerate(history):
            # 주문일시
            created = h.get("created_at", "")
            if "T" in created:
                created = created.replace("T", " ")[:16]
            elif len(created) > 16:
                created = created[:16]

            # 주문박스 표시
            pack_size = h.get("pack_size", 0)
            box_qty = h.get("box_qty", 0)
            qty = h.get("qty", 0)
            if box_qty > 0 and pack_size > 0:
                box_text = f"{pack_size} x {box_qty}박스"
            elif pack_size > 0:
                import math
                box_text = f"{pack_size} x {math.ceil(qty / pack_size)}박스"
            else:
                box_text = "-"

            items = [
                (0, created),
                (1, h.get("drug_name", "")),
                (2, h.get("insurance_code", "")),
                (3, f"{qty}"),
                (4, box_text),
                (5, h.get("wholesaler_name", "")),
                (6, h.get("status", "")),
            ]
            for col, text in items:
                item = QTableWidgetItem(text)
                if col in (3, 4, 6):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 6:
                    status = h.get("status", "")
                    if status == "ordered":
                        item.setText("주문완료")
                        item.setForeground(QColor(_GREEN))
                    elif status == "cart_only":
                        item.setText("장바구니완료")
                        item.setForeground(QColor(_BLUE))
                    elif status == "out_of_stock":
                        item.setText("품절")
                        item.setForeground(QColor(_ORANGE))
                    elif status == "failed":
                        item.setText("주문실패")
                        item.setForeground(QColor(_RED))
                self.history_table.setItem(row, col, item)
            self.history_table.setRowHeight(row, 38)

    # ─────────────── 사용량 조회 ───────────────

    def _on_usage_search(self):
        query = self.usage_search.text().strip()
        if not query:
            return

        # 검색어로 약품 찾기: 보험코드 직접 입력 or 약품명 검색
        matches = []

        # 1) 현재 테이블에 있는 약품에서 검색
        for item in self.drug_data:
            code = item.get("insurance_code", "")
            name = item.get("drug_name", "")
            if query in code or query.lower() in name.lower():
                matches.append((code, name))

        # 2) inventory에서도 검색
        if not matches:
            from core.inventory import load_inventory
            inv = load_inventory()
            for code, data in inv.items():
                name = data.get("name", "")
                if query in code or query.lower() in name.lower():
                    matches.append((code, name))

        # 3) 보험코드 직접 입력
        if not matches and len(query) >= 6 and query.isdigit():
            from core.drug_api import get_drug_name
            name = get_drug_name(query)
            matches.append((query, name))

        if not matches:
            self.usage_table.setRowCount(1)
            item = QTableWidgetItem("검색 결과 없음")
            item.setForeground(QColor(_TEXT_SEC))
            self.usage_table.setItem(0, 1, item)
            return

        # DB에서 사용량 조회
        try:
            from core.db_reader import fetch_drug_usage
        except Exception:
            return

        self.usage_table.setRowCount(len(matches))
        for row, (code, name) in enumerate(matches):
            try:
                usage = fetch_drug_usage(code)
            except Exception:
                usage = {"this_week": 0, "this_month": 0, "last_month": 0}

            unit = "정"
            from core.inventory import get_drug_config
            cfg = get_drug_config(code)
            if cfg:
                unit = cfg.get("unit", "정")

            items = [
                (0, code),
                (1, name),
                (2, f"{usage['this_week']}{unit}"),
                (3, f"{usage['this_month']}{unit}"),
                (4, f"{usage['last_month']}{unit}"),
            ]
            for col, text in items:
                cell = QTableWidgetItem(text)
                if col >= 2:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.usage_table.setItem(row, col, cell)
            self.usage_table.setRowHeight(row, 38)

    def reload_wholesalers(self):
        self.wholesalers = _load_json("wholesalers.json")
        self._populate_ws_combo(self.bulk_ws_combo)
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 7)
            if isinstance(combo, QComboBox):
                prev = combo.currentData()
                self._populate_ws_combo(combo)
                if prev:
                    idx = combo.findData(prev)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
