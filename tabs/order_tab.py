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
    RED as _RED, TEXT_SEC as _TEXT_SEC, TEXT_DISABLED,
    CARD_FRAME, STATUS_LABEL, SUBTITLE,
    COMBO_SMALL, SPIN_BOX_SMALL,
    btn_primary, btn_success, btn_accent, btn_order,
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


class AutoOrderWorker(QThread):
    """자동 주문 백그라운드 실행."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, order_items: list[dict], wholesaler_id: str):
        super().__init__()
        self.order_items = order_items
        self.wholesaler_id = wholesaler_id

    def run(self):
        try:
            from core.order_engine import is_cart_only_mode, place_orders

            # wholesaler_id 세팅
            for item in self.order_items:
                item["wholesaler_id"] = self.wholesaler_id

            cart_only = is_cart_only_mode()
            mode_text = "장바구니 담기" if cart_only else "주문"
            self.progress.emit(f"{len(self.order_items)}개 약품 {mode_text} 시작...")

            results = place_orders(
                self.order_items,
                progress_callback=lambda msg: self.progress.emit(msg),
                dry_run=cart_only,
            )

            # 주문 성공 시 재고 업데이트
            from core.inventory import update_stock_after_order
            for r in results:
                if r.get("success"):
                    for item in r.get("items", []):
                        update_stock_after_order(
                            item["insurance_code"], item.get("qty", 0)
                        )

            self.finished.emit(results)
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
        self.time_combo.addItems(["하루 전체", "오전 (09~13시)", "오후 (13~19시)"])
        self.time_combo.setMinimumWidth(150)
        top.addWidget(self.time_combo)

        self.fetch_btn = QPushButton("처방 데이터 조회")
        self.fetch_btn.setStyleSheet(btn_primary())
        self.fetch_btn.clicked.connect(self._on_fetch)
        top.addWidget(self.fetch_btn)

        top.addStretch()

        ws_label = QLabel("일괄 도매상")
        ws_label.setStyleSheet(SUBTITLE)
        top.addWidget(ws_label)

        self.bulk_ws_combo = QComboBox()
        self._populate_ws_combo(self.bulk_ws_combo)
        self.bulk_ws_combo.setMinimumWidth(130)
        top.addWidget(self.bulk_ws_combo)

        bulk_btn = QPushButton("일괄 적용")
        bulk_btn.clicked.connect(self._on_bulk_apply)
        top.addWidget(bulk_btn)

        self.auto_order_btn = QPushButton("자동 주문")
        self.auto_order_btn.setStyleSheet(btn_accent())
        self.auto_order_btn.clicked.connect(self._on_auto_order)
        top.addWidget(self.auto_order_btn)

        top_card = _card(top_widget)
        layout.addWidget(top_card)

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
        self.table.setColumnWidth(0, 40)
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

        select_all_btn = QPushButton("전체 선택")
        select_all_btn.clicked.connect(self._on_select_all)
        bottom.addWidget(select_all_btn)

        deselect_btn = QPushButton("전체 해제")
        deselect_btn.clicked.connect(self._on_deselect_all)
        bottom.addWidget(deselect_btn)

        self.order_btn = QPushButton("모두 주문하기")
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
        self.history_table.setColumnWidth(6, 90)
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
        return ["all", "morning", "afternoon"][idx]

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
        self._populate_table()
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

    def _populate_table(self):
        from core.inventory import get_current_stock, get_drug_config

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

            # 체크박스
            cb = QCheckBox()
            cb.setChecked(not stock_sufficient and not is_manual)
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 0, cb_widget)

            # 약품명
            name_item = QTableWidgetItem(item["drug_name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, name_item)

            # 선호규격 (클릭 가능)
            spec_item = QTableWidgetItem(spec_text)
            spec_item.setFlags(spec_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            spec_item.setToolTip("클릭하여 설정 변경")
            if not cfg:
                spec_item.setForeground(QColor(_BLUE))
                spec_item.setText("설정 필요")
            self.table.setItem(row, 2, spec_item)

            # 주문타입
            type_text = ORDER_TYPE_LABELS.get(order_type, "미설정")
            type_item = QTableWidgetItem(type_text)
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if not cfg:
                type_item.setForeground(QColor(_RED))
            self.table.setItem(row, 3, type_item)

            # 오늘 사용
            used_item = QTableWidgetItem(str(today_qty))
            used_item.setFlags(used_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            used_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, used_item)

            # 현재 재고 (클릭 가능)
            stock_item = QTableWidgetItem(str(current_stock))
            stock_item.setFlags(stock_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
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

            self.table.setRowHeight(row, 44)

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

            new_cfg = {
                **cfg,
                "name": drug_name,
                "order_type": dlg.result_config["order_type"],
                "preferred_unit": dlg.result_config["preferred_unit"],
                "unit_options": dlg.result_config["unit_options"] or unit_options,
                "target_stock": dlg.result_config["target_stock"],
                "unit": dlg.result_config.get("unit", "정"),
                "tracking_start_date": cfg.get(
                    "tracking_start_date", datetime.now().strftime("%Y-%m-%d")
                ),
            }
            # current_stock, base_stock 등 재고 관련 필드는 기존 값 유지
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

    # ─────────────── 일괄 도매상 적용 ───────────────

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

    def _on_select_all(self):
        self._set_all_checked(True)

    def _on_deselect_all(self):
        self._set_all_checked(False)

    def _set_all_checked(self, checked: bool):
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 0)
            if widget:
                cb = widget.findChild(QCheckBox)
                if cb:
                    cb.setChecked(checked)

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

        msg = "다음과 같이 주문하시겠습니까?\n\n"
        for ws_name, ws_items in summary.items():
            msg += f"[{ws_name}]\n"
            for it in ws_items:
                msg += f"  - {it['drug_name']} {it['qty']}개\n"
            msg += "\n"

        total = sum(it["qty"] for it in items)
        msg += f"총 {len(items)}개 품목 / {total}개"

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

        from core.order_engine import is_cart_only_mode, place_orders

        results = place_orders(items, dry_run=is_cart_only_mode())

        failed_items = []
        for r in results:
            if not r["success"]:
                failed_items.extend(r["items"])

        self._show_order_results(results, [])

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

            if not qty_spin or qty_spin.value() == 0:
                continue

            data = self.drug_data[row]
            from core.inventory import get_drug_config as _gdc
            _cfg = _gdc(data["insurance_code"])
            items.append({
                "insurance_code": data["insurance_code"],
                "drug_name": data["drug_name"],
                "spec": data.get("spec", ""),
                "qty": qty_spin.value(),
                "preferred_unit": _cfg.get("preferred_unit", 0) if _cfg else 0,
                "wholesaler_id": ws_combo.currentData() if ws_combo else "",
                "wholesaler_name": ws_combo.currentText() if ws_combo else "",
            })
        return items

    def _show_order_results(self, results: list, retry_results: list):
        msg = "=== 주문 결과 ===\n\n"
        for r in results:
            icon = "v" if r["success"] else "X"
            msg += f"[{icon}] {r['wholesaler_name']}: {len(r['items'])}건 - {r['message']}\n"

        QMessageBox.information(self, "주문 결과", msg)
        self.status_label.setText(f"주문 완료 - {len(results)}개 도매상 처리됨")
        self._load_order_history()

    # ─────────────── 자동 주문 ───────────────

    def _on_auto_order(self):
        ws_id = self.bulk_ws_combo.currentData()
        ws_name = self.bulk_ws_combo.currentText()
        if not ws_id:
            QMessageBox.warning(self, "알림", "도매상을 선택하세요.")
            return

        # 미설정 약품 체크
        from core.inventory import is_configured
        unconfigured = [d for d in self.drug_data if not is_configured(d["insurance_code"])]
        if unconfigured:
            names = "\n".join(f"  - {d['drug_name']}" for d in unconfigured[:10])
            extra = f"\n  ... 외 {len(unconfigured) - 10}개" if len(unconfigured) > 10 else ""
            reply = QMessageBox.question(
                self, "미설정 약품 있음",
                f"설정되지 않은 약품 {len(unconfigured)}건이 있습니다.\n{names}{extra}\n\n"
                f"미설정 약품은 '즉시 주문' 방식으로 처리됩니다.\n계속하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # 주문 항목 수집
        from core.inventory import calc_order_qty, get_drug_config

        order_items = []
        for item in self.drug_data:
            code = item["insurance_code"]
            today_qty = int(item["qty"])
            order_qty = calc_order_qty(code, today_qty)

            cfg = get_drug_config(code)
            if cfg and cfg.get("order_type") == "manual":
                continue
            if order_qty <= 0:
                continue

            order_items.append({
                "insurance_code": code,
                "drug_name": item["drug_name"],
                "spec": item.get("spec", ""),
                "qty": order_qty,
                "preferred_unit": cfg.get("preferred_unit", 0) if cfg else 0,
            })

        if not order_items:
            QMessageBox.information(self, "알림", "주문할 약품이 없습니다.\n(재고 충분 또는 수동 주문만 있음)")
            return

        time_label = self.time_combo.currentText()
        reply = QMessageBox.question(
            self, "자동 주문 확인",
            f"시간대: {time_label}\n도매상: {ws_name}\n"
            f"주문 항목: {len(order_items)}개\n\n진행하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.auto_order_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self.order_btn.setEnabled(False)
        self._spinner.show_with_message("처리 중...")
        self.status_label.setText("자동 주문 준비 중...")

        self._auto_worker = AutoOrderWorker(order_items, ws_id)
        self._auto_worker.progress.connect(self._on_auto_progress)
        self._auto_worker.finished.connect(self._on_auto_finished)
        self._auto_worker.error.connect(self._on_auto_error)
        self._auto_worker.start()

    def _on_auto_progress(self, msg: str):
        self.status_label.setText(msg)
        self._spinner.set_message(msg)

    def _on_auto_finished(self, results: list):
        self.auto_order_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.order_btn.setEnabled(True)
        self._spinner.hide_spinner()

        if not results:
            self.status_label.setText("주문할 약품이 없습니다")
            return

        total_items = 0
        total_failed = 0
        failed_names = []

        for r in results:
            total_items += len(r.get("items", []))
            fails = r.get("failed_items", [])
            total_failed += len(fails)
            for f in fails:
                failed_names.append(f.get("insurance_code", ""))

        success_count = total_items - total_failed
        self.status_label.setText(f"자동 주문 완료 - {success_count}개 성공, {total_failed}개 실패")

        # 테이블 + 주문 내역 갱신
        self._populate_table()
        self._load_order_history()

        if total_failed > 0:
            fail_text = "\n".join(f"  - {n}" for n in failed_names)
            QMessageBox.warning(
                self, "자동 주문 결과",
                f"주문 완료: {success_count}개 성공\n\n"
                f"실패 항목 ({total_failed}건):\n{fail_text}",
            )
        else:
            QMessageBox.information(
                self, "자동 주문 완료",
                f"총 {success_count}개 품목 주문 완료!",
            )

    def _on_auto_error(self, msg: str):
        self.auto_order_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.order_btn.setEnabled(True)
        self._spinner.hide_spinner()
        self.status_label.setText(f"자동 주문 실패: {msg}")
        QMessageBox.critical(self, "자동 주문 오류", f"오류가 발생했습니다:\n{msg}")

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
                    elif status == "failed":
                        item.setText("실패")
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
