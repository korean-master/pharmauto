"""설정 탭 - 도매상 계정, 제외 약품, 알림 설정."""

import json
import os

from PyQt6.QtCore import QTime, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ui.styles import (
    BLUE as _BLUE, GREEN as _GREEN, RED as _RED, TEXT_SEC as _TEXT_SEC,
    CARD_FRAME, TITLE, SUBTITLE, DESCRIPTION, SCROLL_AREA,
    COMBO_MALGUN,
    btn_primary, btn_success, btn_danger, btn_small_primary, btn_small_danger,
)

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")


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


class SettingsTab(QWidget):
    def __init__(self, on_wholesaler_changed=None, on_schedule_changed=None):
        super().__init__()
        self._on_wholesaler_changed = on_wholesaler_changed
        self._on_schedule_changed = on_schedule_changed
        self._inventory_loaded = False
        self._init_ui()
        self._load_all()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(SCROLL_AREA)
        scroll = self._scroll

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # === 약국 정보 카드 ===
        db_card = QFrame()
        db_card.setStyleSheet(CARD_FRAME)
        db_lay = QVBoxLayout(db_card)
        db_lay.setContentsMargins(24, 24, 24, 24)
        db_lay.setSpacing(12)

        db_title = QLabel("약국 정보")
        db_title.setStyleSheet(TITLE)
        db_lay.addWidget(db_title)

        db_form = QFormLayout()
        db_form.setSpacing(12)
        db_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.pharmacy_name_input = QLineEdit()
        self.pharmacy_name_input.setPlaceholderText("약국 이름")
        db_form.addRow("약국명", self.pharmacy_name_input)

        # 내부용 — UI 숨김
        self.db_server_input = QLineEdit()
        self.db_name_input = QLineEdit()
        self.db_driver_input = QLineEdit()

        db_lay.addLayout(db_form)

        db_btn_row = QHBoxLayout()
        db_btn_row.setSpacing(8)
        db_btn_row.addStretch()

        self.db_status_label = QLabel("")
        self.db_status_label.setStyleSheet(DESCRIPTION)

        save_db_btn = QPushButton("저장")
        save_db_btn.setStyleSheet(btn_success())
        save_db_btn.clicked.connect(self._save_db_settings)
        db_btn_row.addWidget(save_db_btn)

        db_lay.addLayout(db_btn_row)
        # === 도매상 계정 관리 카드 ===
        ws_card = QFrame()
        ws_card.setStyleSheet(CARD_FRAME)
        ws_lay = QVBoxLayout(ws_card)
        ws_lay.setContentsMargins(24, 24, 24, 24)
        ws_lay.setSpacing(12)

        ws_title = QLabel("도매상 계정 관리")
        ws_title.setStyleSheet(TITLE)
        ws_lay.addWidget(ws_title)

        self.ws_table = QTableWidget()
        self.ws_table.setColumnCount(8)
        self.ws_table.setHorizontalHeaderLabels([
            "도매상명", "URL", "ID", "PW", "우선순위", "상태", "", "",
        ])
        self.ws_table.verticalHeader().setVisible(False)
        self.ws_table.setShowGrid(False)
        self.ws_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        ws_hdr = self.ws_table.horizontalHeader()
        ws_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        ws_hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ws_hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        ws_hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        ws_hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        ws_hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        ws_hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        ws_hdr.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.ws_table.setColumnWidth(0, 100)
        self.ws_table.setColumnWidth(2, 100)
        self.ws_table.setColumnWidth(3, 100)
        self.ws_table.setColumnWidth(4, 70)
        self.ws_table.setColumnWidth(5, 200)
        self.ws_table.setColumnWidth(6, 70)
        self.ws_table.setColumnWidth(7, 70)
        self.ws_table.setStyleSheet(
            "QTableWidget { font-family: 'Malgun Gothic'; font-size: 13px; }"
        )
        self.ws_table.setMinimumHeight(200)
        ws_lay.addWidget(self.ws_table)

        ws_btn_row = QHBoxLayout()
        ws_btn_row.setSpacing(8)

        add_ws_btn = QPushButton("+ 도매상 추가")
        add_ws_btn.setStyleSheet(btn_primary())
        add_ws_btn.clicked.connect(self._add_wholesaler_row)
        ws_btn_row.addWidget(add_ws_btn)

        ws_btn_row.addStretch()

        save_ws_btn = QPushButton("저장")
        save_ws_btn.setStyleSheet(btn_success())
        save_ws_btn.clicked.connect(self._save_wholesalers)
        ws_btn_row.addWidget(save_ws_btn)

        ws_lay.addLayout(ws_btn_row)
        layout.addWidget(ws_card)

        # === 영구 제외 약품 카드 ===
        exc_card = QFrame()
        exc_card.setStyleSheet(CARD_FRAME)
        exc_lay = QVBoxLayout(exc_card)
        exc_lay.setContentsMargins(24, 24, 24, 24)
        exc_lay.setSpacing(12)

        exc_title = QLabel("제외 약품 관리")
        exc_title.setStyleSheet(TITLE)
        exc_lay.addWidget(exc_title)

        self.exc_search = QLineEdit()
        self.exc_search.setPlaceholderText("약품명 또는 보험코드 검색...")
        self.exc_search.textChanged.connect(self._filter_exc_table)
        exc_lay.addWidget(self.exc_search)

        self.exc_table = QTableWidget()
        self.exc_table.setColumnCount(4)
        self.exc_table.setHorizontalHeaderLabels(["보험코드", "약품명", "사유", ""])
        self.exc_table.verticalHeader().setVisible(False)
        self.exc_table.setShowGrid(False)
        self.exc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.exc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.exc_table.setColumnWidth(0, 120)
        self.exc_table.setColumnWidth(3, 80)
        self.exc_table.setMinimumHeight(350)
        exc_lay.addWidget(self.exc_table)

        # === 약품 재고/주문 관리 카드 ===
        inv_card = QFrame()
        inv_card.setStyleSheet(CARD_FRAME)
        inv_lay = QVBoxLayout(inv_card)
        inv_lay.setContentsMargins(24, 24, 24, 24)
        inv_lay.setSpacing(12)

        inv_title = QLabel("약품 재고/주문 관리")
        inv_title.setStyleSheet(TITLE)
        inv_lay.addWidget(inv_title)

        inv_desc = QLabel("약품별 주문 방식, 선호 규격, 적정재고, 현재 재고를 관리합니다.")
        inv_desc.setStyleSheet(DESCRIPTION)
        inv_lay.addWidget(inv_desc)

        self.inv_search = QLineEdit()
        self.inv_search.setPlaceholderText("약품명 또는 보험코드 검색...")
        self.inv_search.textChanged.connect(self._filter_inv_table)
        inv_lay.addWidget(self.inv_search)

        self.inv_table = QTableWidget()
        self.inv_table.setColumnCount(8)
        self.inv_table.setHorizontalHeaderLabels([
            "보험코드", "약품명", "주문방식", "선호규격", "적정재고", "현재재고", "", "",
        ])
        self.inv_table.verticalHeader().setVisible(False)
        self.inv_table.setShowGrid(False)
        self.inv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.inv_table.setColumnWidth(6, 70)
        self.inv_table.setColumnWidth(7, 70)
        self.inv_table.setMinimumHeight(400)
        inv_lay.addWidget(self.inv_table)

        inv_btn_row = QHBoxLayout()
        inv_btn_row.setSpacing(8)

        reload_inv_btn = QPushButton("새로고침")
        reload_inv_btn.setStyleSheet(btn_primary())
        reload_inv_btn.clicked.connect(self._load_inventory)
        inv_btn_row.addWidget(reload_inv_btn)

        inv_btn_row.addStretch()
        inv_lay.addLayout(inv_btn_row)
        layout.addWidget(inv_card)

        layout.addWidget(exc_card)

        # === 예약 자동 주문 카드 ===
        # === 주문 확정 방식 카드 ===
        confirm_card = QFrame()
        confirm_card.setStyleSheet(CARD_FRAME)
        confirm_lay = QVBoxLayout(confirm_card)
        confirm_lay.setContentsMargins(24, 24, 24, 24)
        confirm_lay.setSpacing(12)

        confirm_title = QLabel("주문 확정 방식")
        confirm_title.setStyleSheet(TITLE)
        confirm_lay.addWidget(confirm_title)

        from PyQt6.QtWidgets import QRadioButton, QButtonGroup

        self._confirm_group = QButtonGroup(self)

        self._confirm_auto = QRadioButton("자동 주문 확정 — 장바구니 담기 + 주문까지 자동 완료")
        self._confirm_auto.setStyleSheet(
            "QRadioButton { font-size: 13px; font-family: 'Malgun Gothic'; padding: 4px 0; }"
        )
        self._confirm_group.addButton(self._confirm_auto, 0)
        confirm_lay.addWidget(self._confirm_auto)

        auto_desc = QLabel("  처방 조회 후 바로 주문이 들어갑니다. 빠르지만 확인 없이 진행됩니다.")
        auto_desc.setStyleSheet(DESCRIPTION)
        confirm_lay.addWidget(auto_desc)

        self._confirm_cart = QRadioButton("장바구니만 담기 — 약사가 직접 확인 후 주문 확정")
        self._confirm_cart.setStyleSheet(
            "QRadioButton { font-size: 13px; font-family: 'Malgun Gothic'; padding: 4px 0; }"
        )
        self._confirm_group.addButton(self._confirm_cart, 1)
        confirm_lay.addWidget(self._confirm_cart)

        cart_desc = QLabel("  도매상 사이트 장바구니에 담기까지만 자동으로 하고, 최종 주문은 약사가 직접 확인합니다.")
        cart_desc.setStyleSheet(DESCRIPTION)
        confirm_lay.addWidget(cart_desc)

        self._confirm_auto.setChecked(True)

        save_confirm_btn = QPushButton("저장")
        save_confirm_btn.setStyleSheet(btn_success())
        save_confirm_btn.clicked.connect(self._save_confirm_settings)
        confirm_lay.addWidget(save_confirm_btn, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addWidget(confirm_card)

        # === 주문 분배 카드 ===
        split_card = QFrame()
        split_card.setStyleSheet(CARD_FRAME)
        split_lay = QVBoxLayout(split_card)
        split_lay.setContentsMargins(24, 24, 24, 24)
        split_lay.setSpacing(12)

        split_title = QLabel("주문 분배")
        split_title.setStyleSheet(TITLE)
        split_lay.addWidget(split_title)

        self._split_group = QButtonGroup(self)

        self._split_single = QRadioButton("단일 도매상 — 모든 약품을 하나의 도매상에 주문")
        self._split_single.setStyleSheet(
            "QRadioButton { font-size: 13px; font-family: 'Malgun Gothic'; padding: 4px 0; }"
        )
        self._split_group.addButton(self._split_single, 0)
        split_lay.addWidget(self._split_single)

        # 기본 도매상 선택 (단일 도매상 + 예약 자동주문 공용)
        default_ws_row = QHBoxLayout()
        default_ws_row.setSpacing(8)
        default_ws_row.setContentsMargins(24, 0, 0, 0)
        default_ws_label = QLabel("기본 도매상:")
        default_ws_label.setStyleSheet(
            "font-size: 13px; font-family: 'Malgun Gothic'; font-weight: 600;"
        )
        default_ws_row.addWidget(default_ws_label)
        self._default_ws_combo = QComboBox()
        self._default_ws_combo.setMinimumWidth(150)
        self._default_ws_combo.setStyleSheet(COMBO_MALGUN)
        ws_all = _load_json("wholesalers.json")
        for wid, w in ws_all.items():
            self._default_ws_combo.addItem(w["name"], wid)
        default_ws_row.addWidget(self._default_ws_combo)
        default_ws_row.addStretch()
        split_lay.addLayout(default_ws_row)

        self._split_even = QRadioButton("비율 분배 — 선택한 도매상들에 금액 기준으로 분배")
        self._split_even.setStyleSheet(
            "QRadioButton { font-size: 13px; font-family: 'Malgun Gothic'; padding: 4px 0; }"
        )
        self._split_group.addButton(self._split_even, 1)
        split_lay.addWidget(self._split_even)

        self._split_single.setChecked(True)
        self._split_single.toggled.connect(self._on_split_mode_changed)

        # 분배 도매상 선택 (체크박스 + 비율 스핀박스)
        split_ws_label = QLabel("분배할 도매상과 비율:")
        split_ws_label.setStyleSheet(DESCRIPTION)
        split_lay.addWidget(split_ws_label)

        from PyQt6.QtWidgets import QCheckBox
        self._split_ws_rows = {}  # {wid: (checkbox, spinbox)}
        self._split_ws_layout = QVBoxLayout()
        self._split_ws_layout.setSpacing(6)
        split_lay.addLayout(self._split_ws_layout)

        save_split_btn = QPushButton("저장")
        save_split_btn.setStyleSheet(btn_success())
        save_split_btn.clicked.connect(self._save_split_settings)
        split_lay.addWidget(save_split_btn, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addWidget(split_card)

        # === 예약 자동 주문 카드 ===
        self.sched_card = QFrame()
        self.sched_card.setStyleSheet(CARD_FRAME)
        sched_card = self.sched_card
        sched_lay = QVBoxLayout(sched_card)
        sched_lay.setContentsMargins(24, 24, 24, 24)
        sched_lay.setSpacing(12)

        sched_title = QLabel("예약 자동 주문")
        sched_title.setStyleSheet(TITLE)
        sched_lay.addWidget(sched_title)

        sched_desc = QLabel("설정한 시간에 자동으로 처방 조회 → 주문을 실행합니다. (프로그램이 켜져 있어야 합니다)")
        sched_desc.setStyleSheet(DESCRIPTION)
        sched_lay.addWidget(sched_desc)

        # 켜기/끄기 토글
        from PyQt6.QtWidgets import QCheckBox, QRadioButton, QButtonGroup
        self.sched_enabled_cb = QCheckBox("예약 자동 주문 사용")
        self.sched_enabled_cb.setStyleSheet(
            "QCheckBox { font-size: 14px; font-weight: 600; font-family: 'Malgun Gothic'; padding: 4px 0; }"
        )
        self.sched_enabled_cb.toggled.connect(self._on_sched_enabled_toggled)
        sched_lay.addWidget(self.sched_enabled_cb)

        # 모드 선택
        self._sched_mode_group = QButtonGroup(self)
        self._sched_radio_multi = QRadioButton("일 2회 이상 주문 (시간대별 분리)")
        self._sched_radio_multi.setStyleSheet(
            "QRadioButton { font-size: 13px; font-family: 'Malgun Gothic'; padding: 2px 0; }"
        )
        self._sched_radio_once = QRadioButton("일 1회 주문 (하루 전체)")
        self._sched_radio_once.setStyleSheet(
            "QRadioButton { font-size: 13px; font-family: 'Malgun Gothic'; padding: 2px 0; }"
        )
        self._sched_mode_group.addButton(self._sched_radio_multi, 0)
        self._sched_mode_group.addButton(self._sched_radio_once, 1)
        self._sched_radio_multi.setChecked(True)
        sched_lay.addWidget(self._sched_radio_multi)

        multi_desc = QLabel("  각 시간에 이전 예약 시간 이후 처방만 주문합니다.")
        multi_desc.setStyleSheet(DESCRIPTION)
        sched_lay.addWidget(multi_desc)

        # 일 2회+ 시간 목록
        self.sched_time_list = QVBoxLayout()
        self.sched_time_list.setSpacing(6)
        sched_lay.addLayout(self.sched_time_list)
        self._sched_time_rows = []

        add_time_btn = QPushButton("+ 시간 추가")
        add_time_btn.setStyleSheet(btn_primary())
        add_time_btn.clicked.connect(lambda: self._add_schedule_time_row(QTime(12, 0)))
        sched_lay.addWidget(add_time_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # 구분
        sched_lay.addWidget(self._sched_radio_once)

        once_desc = QLabel("  설정한 시간에 09:00부터의 전체 처방을 한번에 주문합니다.")
        once_desc.setStyleSheet(DESCRIPTION)
        sched_lay.addWidget(once_desc)

        once_row = QHBoxLayout()
        once_row.setSpacing(8)
        once_row.addWidget(QLabel("예약 시간:"))
        self._sched_once_time = QTimeEdit()
        self._sched_once_time.setDisplayFormat("HH:mm")
        self._sched_once_time.setTime(QTime(18, 30))
        self._sched_once_time.setMinimumWidth(100)
        once_row.addWidget(self._sched_once_time)
        self._sched_once_desc = QLabel("")
        self._sched_once_desc.setStyleSheet(DESCRIPTION)
        once_row.addWidget(self._sched_once_desc)
        once_row.addStretch()
        sched_lay.addLayout(once_row)

        # 시간 변경 시 설명 업데이트
        self._sched_once_time.timeChanged.connect(self._update_once_desc)
        self._update_once_desc()

        # 기본 도매상 안내
        sched_line = QLabel()
        sched_line.setFixedHeight(1)
        sched_line.setStyleSheet("background: #DFE1E6;")
        sched_lay.addWidget(sched_line)

        sched_ws_note = QLabel("기본 도매상은 위 '주문 분배' 설정에서 변경할 수 있습니다.")
        sched_ws_note.setStyleSheet(DESCRIPTION)
        sched_lay.addWidget(sched_ws_note)

        save_sched_btn = QPushButton("예약 설정 저장")
        save_sched_btn.setStyleSheet(btn_success())
        save_sched_btn.clicked.connect(self._save_schedule_settings)
        sched_lay.addWidget(save_sched_btn, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addWidget(sched_card)

        # === 알림 설정 카드 ===
        noti_card = QFrame()
        noti_card.setStyleSheet(CARD_FRAME)
        noti_lay = QVBoxLayout(noti_card)
        noti_lay.setContentsMargins(24, 24, 24, 24)
        noti_lay.setSpacing(16)

        noti_title = QLabel("알림 설정")
        noti_title.setStyleSheet(TITLE)
        noti_lay.addWidget(noti_title)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.noti_time = QTimeEdit()
        self.noti_time.setDisplayFormat("HH:mm")
        self.noti_time.setTime(QTime(9, 0))
        form.addRow("알림 시간", self.noti_time)

        self.kakao_key_input = QLineEdit()
        self.kakao_key_input.setPlaceholderText("카카오 API 키")
        self.kakao_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("카카오 API 키", self.kakao_key_input)

        self.kakao_sender_input = QLineEdit()
        self.kakao_sender_input.setPlaceholderText("발신 프로필 키")
        form.addRow("발신 프로필", self.kakao_sender_input)

        noti_lay.addLayout(form)

        save_noti_btn = QPushButton("알림 설정 저장")
        save_noti_btn.setStyleSheet(btn_success())
        save_noti_btn.clicked.connect(self._save_notification_settings)
        noti_lay.addWidget(save_noti_btn, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addWidget(noti_card)

        # === 업데이트 설정 카드 ===
        upd_card = QFrame()
        upd_card.setStyleSheet(CARD_FRAME)
        upd_lay = QVBoxLayout(upd_card)
        upd_lay.setContentsMargins(24, 24, 24, 24)
        upd_lay.setSpacing(12)

        upd_title = QLabel("자동 업데이트")
        upd_title.setStyleSheet(TITLE)
        upd_lay.addWidget(upd_title)

        from core.version import VERSION
        ver_label = QLabel(f"현재 버전: v{VERSION}")
        ver_label.setStyleSheet(SUBTITLE)
        upd_lay.addWidget(ver_label)

        upd_desc = QLabel("프로그램 시작 시 자동으로 최신 버전을 확인합니다.")
        upd_desc.setStyleSheet(DESCRIPTION)
        upd_lay.addWidget(upd_desc)

        # 저장소 — 내부용, UI 숨김
        self.repo_input = QLineEdit()

        upd_btn_row = QHBoxLayout()
        upd_btn_row.setSpacing(8)

        check_upd_btn = QPushButton("업데이트 확인")
        check_upd_btn.setStyleSheet(btn_primary())
        check_upd_btn.clicked.connect(self._manual_check_update)
        upd_btn_row.addWidget(check_upd_btn)

        self.upd_status_label = QLabel("")
        self.upd_status_label.setStyleSheet(DESCRIPTION)
        upd_btn_row.addWidget(self.upd_status_label)

        upd_btn_row.addStretch()
        upd_lay.addLayout(upd_btn_row)
        layout.addWidget(db_card)
        layout.addWidget(upd_card)

        # === DB 구조 내보내기 카드 (이팜 외 프로그램용) ===
        inspect_card = QFrame()
        inspect_card.setStyleSheet(CARD_FRAME)
        inspect_lay = QVBoxLayout(inspect_card)
        inspect_lay.setContentsMargins(24, 24, 24, 24)
        inspect_lay.setSpacing(12)

        inspect_title = QLabel("DB 구조 내보내기")
        inspect_title.setStyleSheet(TITLE)
        inspect_lay.addWidget(inspect_title)

        inspect_desc = QLabel(
            "환자 등 개인정보는 포함되지 않습니다."
        )
        inspect_desc.setStyleSheet(DESCRIPTION)
        inspect_desc.setWordWrap(True)
        inspect_lay.addWidget(inspect_desc)

        inspect_btn_row = QHBoxLayout()
        inspect_btn_row.setSpacing(12)

        export_btn = QPushButton("DB 구조 내보내기")
        export_btn.setStyleSheet(btn_primary())
        export_btn.clicked.connect(self._on_export_db_structure)
        inspect_btn_row.addWidget(export_btn)

        self._inspect_status = QLabel("")
        self._inspect_status.setStyleSheet(DESCRIPTION)
        inspect_btn_row.addWidget(self._inspect_status)
        inspect_btn_row.addStretch()
        inspect_lay.addLayout(inspect_btn_row)

        layout.addWidget(inspect_card)

        # === 원격 지원 카드 ===
        remote_card = QFrame()
        remote_card.setStyleSheet(CARD_FRAME)
        remote_lay = QVBoxLayout(remote_card)
        remote_lay.setContentsMargins(24, 24, 24, 24)
        remote_lay.setSpacing(12)

        remote_title = QLabel("원격 지원")
        remote_title.setStyleSheet(TITLE)
        remote_lay.addWidget(remote_title)

        remote_desc = QLabel(
            "문제가 있으면 원격 지원을 요청하세요. "
            "AnyDesk를 통해 원격으로 도와드립니다."
        )
        remote_desc.setStyleSheet(DESCRIPTION)
        remote_desc.setWordWrap(True)
        remote_lay.addWidget(remote_desc)

        remote_btn_row = QHBoxLayout()
        remote_btn_row.setSpacing(12)

        anydesk_btn = QPushButton("원격 지원 요청")
        anydesk_btn.setStyleSheet(
            f"QPushButton {{ font-size: 13px; padding: 10px 24px; "
            f"background: #EF4444; color: white; border: none; "
            f"border-radius: 8px; font-weight: 600; font-family: 'Malgun Gothic'; }}"
            f"QPushButton:hover {{ background: #D43D3B; }}"
        )
        anydesk_btn.clicked.connect(self._on_remote_support)
        remote_btn_row.addWidget(anydesk_btn)

        self._remote_status = QLabel("")
        self._remote_status.setStyleSheet(DESCRIPTION)
        remote_btn_row.addWidget(self._remote_status)

        log_btn = QPushButton("오류 로그 열기")
        log_btn.setStyleSheet(
            f"QPushButton {{ font-size: 13px; padding: 10px 24px; "
            f"background: #6B7280; color: white; border: none; "
            f"border-radius: 8px; font-weight: 600; font-family: 'Malgun Gothic'; }}"
            f"QPushButton:hover {{ background: #4B5563; }}"
        )
        log_btn.clicked.connect(self._on_open_log)
        remote_btn_row.addWidget(log_btn)

        send_log_btn = QPushButton("오류 로그 보내기")
        send_log_btn.setStyleSheet(
            f"QPushButton {{ font-size: 13px; padding: 10px 24px; "
            f"background: #EF4444; color: white; border: none; "
            f"border-radius: 8px; font-weight: 600; font-family: 'Malgun Gothic'; }}"
            f"QPushButton:hover {{ background: #DC2626; }}"
        )
        send_log_btn.clicked.connect(self._on_send_log)
        remote_btn_row.addWidget(send_log_btn)

        remote_btn_row.addStretch()
        remote_lay.addLayout(remote_btn_row)

        layout.addWidget(remote_card)

        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _load_all(self):
        self._load_db_settings()
        self._load_wholesalers()
        self._load_exclusions()
        self._load_confirm_settings()
        self._load_split_settings()
        self._load_schedule_settings()
        self._load_notification_settings()
        self._load_update_settings()
        # 약품 목록은 무거우므로 최초 1회만 동기 로드, 이후는 refresh_inventory()로
        if not self._inventory_loaded:
            self._load_inventory()
            self._inventory_loaded = True

    def refresh_inventory(self):
        """외부에서 약품 목록 새로고침 요청 시 (약품 설정 변경 등)."""
        self._load_inventory()

    # --- 이팜 DB ---
    def _load_db_settings(self):
        settings = _load_json("settings.json")
        self.pharmacy_name_input.setText(settings.get("pharmacy_name", ""))
        db = settings.get("db", {})
        self.db_server_input.setText(db.get("server", "localhost"))
        self.db_name_input.setText(db.get("database", "eP_PHARM"))
        self.db_driver_input.setText(db.get("driver", "SQL Server"))

    def _save_db_settings(self):
        settings = _load_json("settings.json")
        settings["pharmacy_name"] = self.pharmacy_name_input.text().strip()
        settings["db"] = {
            "server": self.db_server_input.text().strip() or "localhost",
            "database": self.db_name_input.text().strip() or "eP_PHARM",
            "driver": self.db_driver_input.text().strip() or "SQL Server",
        }
        _save_json("settings.json", settings)
        QMessageBox.information(self, "저장", "이팜 연결 설정이 저장되었습니다.")

    def _test_db_connection(self):
        self.db_status_label.setText("연결 테스트 중...")
        self.db_status_label.setStyleSheet(DESCRIPTION)
        try:
            import pyodbc
            driver = self.db_driver_input.text().strip() or "SQL Server"
            server = self.db_server_input.text().strip() or "localhost"
            database = self.db_name_input.text().strip() or "eP_PHARM"
            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={server};"
                f"DATABASE={database};"
                f"Trusted_Connection=yes;"
            )
            conn = pyodbc.connect(conn_str, timeout=3)
            conn.close()
            self.db_status_label.setText("연결 성공!")
            self.db_status_label.setStyleSheet(f"color: {_GREEN}; font-weight: 700;")
        except Exception:
            self.db_status_label.setText("연결 실패 - 서버/드라이버 확인 필요")
            self.db_status_label.setStyleSheet(f"color: {_RED}; font-weight: 700;")

    # --- 도매상 ---

    _WS_INPUT_STYLE = (
        "QLineEdit { font-family: 'Malgun Gothic'; font-size: 13px;"
        " padding: 4px 8px; min-height: 28px; border: 1px solid #DDD; border-radius: 6px; }"
        "QLineEdit:focus { border-color: #4C83FF; }"
    )
    _WS_ROW_HEIGHT = 52

    def _load_wholesalers(self):
        ws = _load_json("wholesalers.json")
        self.ws_table.setRowCount(0)
        for wid, data in ws.items():
            self._insert_ws_display_row(data, wid)

    def _insert_ws_display_row(self, data: dict, wid: str = ""):
        """읽기 전용 행을 추가한다."""
        row = self.ws_table.rowCount()
        self.ws_table.insertRow(row)

        for col, key in enumerate(["name", "url", "id", "pw"]):
            val = data.get(key, "")
            if key == "pw" and val:
                val = "*" * len(val)
            item = QTableWidgetItem(val)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.ws_table.setItem(row, col, item)

        # 우선순위
        pri_item = QTableWidgetItem(str(data.get("priority", row + 1)))
        pri_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        pri_item.setFlags(pri_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.ws_table.setItem(row, 4, pri_item)

        # 상태
        status_item = QTableWidgetItem("")
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.ws_table.setItem(row, 5, status_item)
        self._check_ws_status(row, wid, data)

        # 수정 버튼
        edit_btn = QPushButton("수정")
        edit_btn.setStyleSheet(btn_small_primary())
        edit_btn.clicked.connect(lambda _, r=row: self._edit_ws_row(r))
        self.ws_table.setCellWidget(row, 6, edit_btn)

        # 삭제 버튼
        del_btn = QPushButton("삭제")
        del_btn.setStyleSheet(btn_small_danger())
        del_btn.clicked.connect(lambda _, r=row: self._del_wholesaler_row(r))
        self.ws_table.setCellWidget(row, 7, del_btn)

        self.ws_table.setRowHeight(row, self._WS_ROW_HEIGHT)

    # ── 도매상 상태 관리 ──
    # 연동 테스트 결과를 wholesalers.json에 저장해두고,
    # 설정 탭에서는 저장된 상태만 표시한다.
    # 최초 등록 시 or 주문 실패 시에만 테스트 실행.

    _STATUS_COLORS = {
        "정상": Qt.GlobalColor.darkGreen,
        "접속 OK": Qt.GlobalColor.darkGreen,
        "로그인 실패": Qt.GlobalColor.red,
        "장바구니 실패": Qt.GlobalColor.red,
        "접속 불가": Qt.GlobalColor.red,
        "사이트 오류": Qt.GlobalColor.red,
        "연동 오류": Qt.GlobalColor.red,
    }

    def _check_ws_status(self, row: int, wid: str, data: dict):
        """도매상 상태를 표시한다. 저장된 상태가 있으면 그대로, 없으면 첫 1회 테스트."""
        status_item = self.ws_table.item(row, 5)

        if not data.get("id") or not data.get("pw"):
            status_item.setText("ID/PW 미설정")
            status_item.setForeground(Qt.GlobalColor.gray)
            return
        if not data.get("url"):
            status_item.setText("URL 미설정")
            status_item.setForeground(Qt.GlobalColor.gray)
            return

        # 저장된 상태가 있으면 표시
        saved = data.get("connection_status", "")
        if saved:
            status_item.setText(saved)
            status_item.setForeground(
                self._STATUS_COLORS.get(saved, Qt.GlobalColor.black)
            )
            # 실패 상태면 자동 재테스트 (기존 상태 유지하며 백그라운드 실행)
            _FAIL_STATUSES = {"로그인 실패", "장바구니 실패", "접속 불가",
                              "사이트 오류", "연동 오류"}
            if saved in _FAIL_STATUSES:
                status_item.setText(f"{saved} → 재확인 중...")
                status_item.setForeground(Qt.GlobalColor.blue)
                self._run_ws_test(row, wid, data)
            return

        # 저장된 상태 없음 → 첫 1회 테스트 (백그라운드)
        status_item.setText("확인 중...")
        status_item.setForeground(Qt.GlobalColor.blue)
        self._run_ws_test(row, wid, data)

    def _run_ws_test(self, row: int, wid: str, data: dict):
        """백그라운드에서 풀 연동 테스트 (로그인→장바구니) 후 결과 저장.

        Generic 도매상은 실패 시 셀렉터를 초기화하고 AI 재분석을 반복한다.
        최대 MAX_ATTEMPTS회 시도 후 결과를 반환한다.
        """
        from PyQt6.QtCore import QThread, pyqtSignal

        class _FullTester(QThread):
            done = pyqtSignal(int, str, str)  # row, wid, status_text

            def __init__(self, row, wid, data):
                super().__init__()
                self._row = row
                self._wid = wid
                self._data = data

            def _write_log(self, msg: str):
                """연동 테스트 로그를 파일에 기록한다."""
                from datetime import datetime
                log_dir = os.path.join(
                    os.path.dirname(__file__), "..", "data"
                )
                os.makedirs(log_dir, exist_ok=True)
                log_path = os.path.join(log_dir, "ws_test_log.txt")
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{timestamp}] {msg}\n")
                print(msg)

            def _upload_dedicated_selectors(self, wid, config, ws_class):
                """전용 클래스의 셀렉터 정보를 클라우드에 공유한다."""
                from urllib.parse import urlparse
                domain = urlparse(config.get("url", "")).netloc
                if not domain:
                    return
                name = config.get("name", wid)
                # 전용 클래스의 기본 정보만 업로드 (다른 사용자가 Generic으로 참고)
                selectors = {
                    "login": {},
                    "search": {},
                    "table": {},
                    "confirm": {},
                    "auto_detected": False,
                    "confidence": "verified",
                    "dedicated_class": ws_class.__name__,
                }
                try:
                    from core.cloud import upload_selectors
                    upload_selectors(domain, name, selectors)
                    self._write_log(f"  전용 클래스 정보 클라우드 공유 완료 ({domain})")
                except Exception:
                    pass

            def _upload_diagnostic(self, wid, config, status, is_generic):
                """연동 실패 시 진단 정보를 클라우드에 업로드한다."""
                try:
                    from core.cloud import is_enabled, _api_url, _headers
                    if not is_enabled():
                        return

                    from datetime import datetime
                    import requests as _req

                    # 셀렉터 정보 수집
                    selectors = {}
                    try:
                        from core.selector_store import load_selectors
                        selectors = load_selectors(wid)
                    except Exception:
                        pass

                    # 로그 파일에서 최근 50줄
                    log_tail = ""
                    try:
                        log_path = os.path.join(
                            os.path.dirname(__file__), "..", "data",
                            "ws_test_log.txt")
                        if os.path.exists(log_path):
                            with open(log_path, "r", encoding="utf-8") as f:
                                lines = f.readlines()
                            log_tail = "".join(lines[-50:])
                    except Exception:
                        pass

                    _req.post(
                        _api_url("diagnostic_reports"),
                        headers=_headers(),
                        json={
                            "wid": wid,
                            "url": config.get("url", ""),
                            "name": config.get("name", wid),
                            "status": status,
                            "is_generic": is_generic,
                            "selectors": selectors,
                            "log_tail": log_tail[:5000],
                            "created_at": datetime.utcnow().isoformat(),
                        },
                        timeout=5,
                    )
                    self._write_log(f"  진단 정보 클라우드 업로드 완료")
                except Exception as e:
                    self._write_log(f"  진단 업로드 실패: {e}")

            def run(self):
                import asyncio

                self._write_log(f"=== {self._wid} 연동 테스트 시작 ===")

                # ID/PW 복호화
                try:
                    from core.crypto import decrypt_dict_fields
                    config = decrypt_dict_fields(
                        dict(self._data), ["id", "pw"]
                    )
                    self._write_log(f"  복호화 완료")
                except Exception as e:
                    self._write_log(f"  복호화 실패: {e}")
                    self.done.emit(self._row, self._wid, "연동 오류")
                    return

                # 1단계: URL 접속 확인
                try:
                    import requests as _req
                    resp = _req.get(config["url"], timeout=5, allow_redirects=True)
                    self._write_log(f"  URL 접속: {resp.status_code}")
                    if resp.status_code >= 500:
                        self.done.emit(self._row, self._wid, "사이트 오류")
                        return
                except Exception as e:
                    self._write_log(f"  URL 접속 실패: {e}")
                    self.done.emit(self._row, self._wid, "접속 불가")
                    return

                # 2단계: 자가 치유 루프 (최대 2회 재분석→재시도)
                MAX_ATTEMPTS = 2
                last_status = "연동 오류"

                try:
                    from core.order_engine import _get_wholesaler_class
                    ws_class = _get_wholesaler_class(
                        self._wid, url=config.get("url", ""))
                    is_generic = ws_class is None

                    if is_generic:
                        from wholesalers.generic import GenericWholesaler
                        ws_class = GenericWholesaler
                        config["_wid"] = self._wid

                    self._write_log(f"  클래스: {'Generic' if is_generic else ws_class.__name__}")

                    for attempt in range(MAX_ATTEMPTS):
                        self._write_log(f"  시도 {attempt + 1}/{MAX_ATTEMPTS}")

                        if is_generic:
                            if attempt == 0:
                                # 1회차: 클라우드 조회 → 없으면 휴리스틱 분석
                                from core.selector_store import load_selectors
                                cur_sel = load_selectors(self._wid,
                                                         url=config.get("url", ""))
                                if not cur_sel or not cur_sel.get("auto_detected"):
                                    self._write_log(f"  셀렉터 없음 → 사이트 분석...")
                                    ws_analyze = ws_class(config)
                                    asyncio.run(ws_analyze.analyze_site(headless=True))
                            else:
                                # 2회차+: 셀렉터 삭제 → AI 시각 에이전트 직행
                                self._write_log(f"  셀렉터 초기화 → AI 시각 에이전트 재분석...")
                                from core.selector_store import delete_selectors
                                delete_selectors(self._wid)
                                ws_analyze = ws_class(config)
                                asyncio.run(ws_analyze.analyze_site(headless=True))

                        # 연동 테스트 실행
                        ws_test = ws_class(config)
                        result = asyncio.run(ws_test.test_connection(headless=True))

                        if result["success"]:
                            last_status = "정상"
                            self._write_log(f"  성공! (총 {attempt + 1}회 시도)")

                            # 전용 클래스도 셀렉터 정보를 클라우드에 공유
                            if not is_generic:
                                try:
                                    self._upload_dedicated_selectors(
                                        self._wid, config, ws_class)
                                except Exception:
                                    pass

                            # 이력 검색 설정이 없으면 별도 탐지 시도
                            if is_generic:
                                try:
                                    from core.history_config import get_config as _get_hcfg
                                    h_cfg = _get_hcfg(self._wid)
                                    if not h_cfg or not h_cfg.get("history_url"):
                                        self._write_log(f"  이력 페이지 탐지 시도...")
                                        ws_hist = ws_class(config)
                                        asyncio.run(ws_hist._ensure_history_config(headless=True))
                                except Exception as he:
                                    self._write_log(f"  이력 탐지 오류: {he}")

                            break

                        # 실패 처리
                        stage = result.get("stage", "")
                        message = result.get("message", "")
                        self._write_log(f"  실패 stage={stage}: {message}")

                        if stage == "login":
                            last_status = "로그인 실패"
                        elif stage == "cart":
                            last_status = "장바구니 실패"
                        else:
                            last_status = "연동 오류"

                        # 전용 클래스는 자동 재분석 불가 → 반복 중단
                        if not is_generic:
                            break

                        # 로그인 실패는 재분석해도 안 됨 → 중단
                        if stage == "login":
                            break

                except Exception as e:
                    import traceback
                    self._write_log(f"  예외 발생: {e}")
                    self._write_log(traceback.format_exc())
                    last_status = "연동 오류"

                # 연동 실패 시 진단 정보를 클라우드에 자동 업로드
                if last_status != "정상":
                    self._upload_diagnostic(
                        self._wid, config, last_status, is_generic)

                # 상세는 로그에만 남김
                self._write_log(f"  최종 결과: {last_status}")
                self.done.emit(self._row, self._wid, last_status)

        tester = _FullTester(row, wid, data)
        tester.done.connect(self._on_ws_test_done)
        tester.start()
        if not hasattr(self, '_ws_testers'):
            self._ws_testers = []
        self._ws_testers.append(tester)

    def _on_ws_test_done(self, row: int, wid: str, status_text: str):
        """테스트 결과를 표시하고 wholesalers.json에 저장한다."""
        # 이력 검색 설정 확인 — 전용 클래스(geo/baekje) 아닌 도매상만
        history_ok = True
        from core.order_engine import _WHOLESALER_CLASSES
        if wid not in _WHOLESALER_CLASSES and status_text == "정상":
            try:
                from core.history_config import get_config
                h_cfg = get_config(wid)
                history_ok = bool(h_cfg and h_cfg.get("history_url"))
            except Exception:
                history_ok = False

        # UI 업데이트
        display_text = status_text
        if status_text == "정상" and not history_ok:
            display_text = "정상 (이력검색 미지원)"

        if row < self.ws_table.rowCount():
            status_item = self.ws_table.item(row, 5)
            if status_item:
                status_item.setText(display_text)
                # 색상: "정상"이면 녹색, 아니면 빨간색
                if "정상" in status_text:
                    if not history_ok:
                        from PyQt6.QtGui import QColor
                        color = QColor("#F59E0B")
                    else:
                        color = Qt.GlobalColor.darkGreen
                else:
                    color = Qt.GlobalColor.red
                status_item.setForeground(color)

        # 결과를 wholesalers.json에 저장
        ws = _load_json("wholesalers.json")
        if wid in ws:
            ws[wid]["connection_status"] = status_text
            ws[wid]["history_supported"] = history_ok
            _save_json("wholesalers.json", ws)

    def _add_wholesaler_row(self):
        """인라인 입력 행을 추가한다."""
        row = self.ws_table.rowCount()
        self.ws_table.insertRow(row)

        name_input = QLineEdit()
        name_input.setPlaceholderText("도매상명")
        name_input.setStyleSheet(self._WS_INPUT_STYLE)
        self.ws_table.setCellWidget(row, 0, name_input)

        url_input = QLineEdit()
        url_input.setPlaceholderText("https://...")
        url_input.setStyleSheet(self._WS_INPUT_STYLE)
        self.ws_table.setCellWidget(row, 1, url_input)

        id_input = QLineEdit()
        id_input.setPlaceholderText("아이디")
        id_input.setStyleSheet(self._WS_INPUT_STYLE)
        self.ws_table.setCellWidget(row, 2, id_input)

        pw_input = QLineEdit()
        pw_input.setPlaceholderText("비밀번호")
        pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        pw_input.setStyleSheet(self._WS_INPUT_STYLE)
        self.ws_table.setCellWidget(row, 3, pw_input)

        pri_spin = QSpinBox()
        pri_spin.setRange(1, 99)
        pri_spin.setValue(row + 1)
        pri_spin.setStyleSheet(
            "QSpinBox { font-family: 'Malgun Gothic'; font-size: 13px; padding: 4px; }"
        )
        self.ws_table.setCellWidget(row, 4, pri_spin)

        # 상태 — 저장 전이므로 빈칸
        status_item = QTableWidgetItem("")
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.ws_table.setItem(row, 5, status_item)

        # 확인 버튼
        confirm_btn = QPushButton("확인")
        confirm_btn.setStyleSheet(btn_small_primary())
        confirm_btn.clicked.connect(lambda _, r=row: self._confirm_ws_row(r))
        self.ws_table.setCellWidget(row, 6, confirm_btn)

        # 취소 버튼
        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet(btn_small_danger())
        cancel_btn.clicked.connect(lambda _, r=row: self.ws_table.removeRow(r))
        self.ws_table.setCellWidget(row, 7, cancel_btn)

        self.ws_table.setRowHeight(row, self._WS_ROW_HEIGHT)
        self.ws_table.scrollToBottom()
        name_input.setFocus()

    # --- 도매상 추가/삭제 시 settings.json 연쇄 동기화 ---

    def _notify_wholesaler_changed(self):
        """도매상 추가/삭제/수정 후 모든 관련 UI를 갱신한다."""
        # 설정 탭 자체의 분배 UI + 기본 도매상 콤보 갱신
        self._load_split_settings()
        # 주문 탭 등 외부 콜백
        if self._on_wholesaler_changed:
            self._on_wholesaler_changed()

    def _sync_settings_for_new_wholesaler(self, wid: str):
        """새 도매상을 settings.json 분배비율에 자동 등록한다."""
        settings = _load_json("settings.json")
        ratios = settings.get("order_split_ratios", {})
        if wid not in ratios:
            ratios[wid] = 0
            settings["order_split_ratios"] = ratios
            _save_json("settings.json", settings)

    def _sync_settings_rename_wholesaler(self, old_wid: str, new_wid: str):
        """도매상 ID 변경 시 settings.json의 관련 항목을 전환한다."""
        settings = _load_json("settings.json")
        changed = False

        ratios = settings.get("order_split_ratios", {})
        if old_wid in ratios:
            ratios[new_wid] = ratios.pop(old_wid)
            settings["order_split_ratios"] = ratios
            changed = True

        split_ws = settings.get("order_split_wholesalers", [])
        if old_wid in split_ws:
            split_ws[split_ws.index(old_wid)] = new_wid
            settings["order_split_wholesalers"] = split_ws
            changed = True

        if settings.get("default_wholesaler") == old_wid:
            settings["default_wholesaler"] = new_wid
            changed = True

        if changed:
            _save_json("settings.json", settings)

    def _sync_settings_remove_wholesaler(self, wid: str):
        """삭제된 도매상을 settings.json에서 제거한다."""
        settings = _load_json("settings.json")
        changed = False

        ratios = settings.get("order_split_ratios", {})
        if wid in ratios:
            del ratios[wid]
            settings["order_split_ratios"] = ratios
            changed = True

        split_ws = settings.get("order_split_wholesalers", [])
        if wid in split_ws:
            split_ws.remove(wid)
            settings["order_split_wholesalers"] = split_ws
            changed = True

        if settings.get("default_wholesaler") == wid:
            settings["default_wholesaler"] = ""
            changed = True

        if changed:
            _save_json("settings.json", settings)

    def _confirm_ws_row(self, row: int):
        """인라인 입력 행을 확정하고 저장한다."""
        name_w = self.ws_table.cellWidget(row, 0)
        url_w = self.ws_table.cellWidget(row, 1)
        id_w = self.ws_table.cellWidget(row, 2)
        pw_w = self.ws_table.cellWidget(row, 3)
        pri_w = self.ws_table.cellWidget(row, 4)

        if not name_w or not isinstance(name_w, QLineEdit):
            return

        name = name_w.text().strip()
        if not name:
            QMessageBox.warning(self, "입력 오류", "도매상명을 입력해주세요.")
            return

        data = {
            "name": name,
            "url": url_w.text().strip() if url_w else "",
            "id": id_w.text().strip() if id_w else "",
            "pw": pw_w.text().strip() if pw_w else "",
            "priority": pri_w.value() if pri_w else row + 1,
        }

        # JSON에 암호화 저장
        from core.crypto import load_wholesalers_secure, save_wholesalers_secure
        ws = load_wholesalers_secure()
        wid = name.lower().replace(" ", "_")
        ws[wid] = data
        save_wholesalers_secure(ws)

        # settings.json 분배비율에 자동 등록 (새 도매상이면 비율 0)
        self._sync_settings_for_new_wholesaler(wid)

        # 행을 읽기 전용으로 교체
        self.ws_table.removeRow(row)
        self.ws_table.insertRow(row)
        # _insert_ws_display_row는 맨 끝에 추가하므로 직접 세팅
        for col, key in enumerate(["name", "url", "id", "pw"]):
            val = data[key]
            if key == "pw" and val:
                val = "*" * len(val)
            item = QTableWidgetItem(val)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.ws_table.setItem(row, col, item)

        pri_item = QTableWidgetItem(str(data["priority"]))
        pri_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        pri_item.setFlags(pri_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.ws_table.setItem(row, 4, pri_item)

        status_item = QTableWidgetItem("")
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.ws_table.setItem(row, 5, status_item)
        self._check_ws_status(row, wid, data)

        edit_btn = QPushButton("수정")
        edit_btn.setStyleSheet(btn_small_primary())
        edit_btn.clicked.connect(lambda _, r=row: self._edit_ws_row(r))
        self.ws_table.setCellWidget(row, 6, edit_btn)

        del_btn = QPushButton("삭제")
        del_btn.setStyleSheet(btn_small_danger())
        del_btn.clicked.connect(lambda _, r=row: self._del_wholesaler_row(r))
        self.ws_table.setCellWidget(row, 7, del_btn)

        self.ws_table.setRowHeight(row, self._WS_ROW_HEIGHT)

        self._notify_wholesaler_changed()

    def _edit_ws_row(self, row: int):
        """기존 행을 인라인 편집 모드로 전환한다."""
        # 현재 값 읽기
        ws = _load_json("wholesalers.json")
        ws_list = list(ws.items())
        if row >= len(ws_list):
            return
        wid, data = ws_list[row]

        name_input = QLineEdit(data.get("name", ""))
        name_input.setStyleSheet(self._WS_INPUT_STYLE)
        self.ws_table.setCellWidget(row, 0, name_input)

        url_input = QLineEdit(data.get("url", ""))
        url_input.setStyleSheet(self._WS_INPUT_STYLE)
        self.ws_table.setCellWidget(row, 1, url_input)

        id_input = QLineEdit(data.get("id", ""))
        id_input.setStyleSheet(self._WS_INPUT_STYLE)
        self.ws_table.setCellWidget(row, 2, id_input)

        pw_input = QLineEdit(data.get("pw", ""))
        pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        pw_input.setStyleSheet(self._WS_INPUT_STYLE)
        self.ws_table.setCellWidget(row, 3, pw_input)

        pri_spin = QSpinBox()
        pri_spin.setRange(1, 99)
        pri_spin.setValue(data.get("priority", row + 1))
        pri_spin.setStyleSheet(
            "QSpinBox { font-family: 'Malgun Gothic'; font-size: 13px; padding: 4px; }"
        )
        self.ws_table.setCellWidget(row, 4, pri_spin)

        # 확인
        confirm_btn = QPushButton("확인")
        confirm_btn.setStyleSheet(btn_small_primary())
        confirm_btn.clicked.connect(lambda _, r=row, old_wid=wid: self._confirm_edit_ws(r, old_wid))
        self.ws_table.setCellWidget(row, 6, confirm_btn)

        # 취소 → 원래대로 복원
        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet(btn_small_danger())
        cancel_btn.clicked.connect(lambda _: self._load_wholesalers())
        self.ws_table.setCellWidget(row, 7, cancel_btn)

        self.ws_table.setRowHeight(row, self._WS_ROW_HEIGHT)
        name_input.setFocus()

    def _confirm_edit_ws(self, row: int, old_wid: str):
        """편집 완료 후 저장."""
        name_w = self.ws_table.cellWidget(row, 0)
        url_w = self.ws_table.cellWidget(row, 1)
        id_w = self.ws_table.cellWidget(row, 2)
        pw_w = self.ws_table.cellWidget(row, 3)
        pri_w = self.ws_table.cellWidget(row, 4)

        name = name_w.text().strip() if name_w else ""
        if not name:
            QMessageBox.warning(self, "입력 오류", "도매상명을 입력해주세요.")
            return

        data = {
            "name": name,
            "url": url_w.text().strip() if url_w else "",
            "id": id_w.text().strip() if id_w else "",
            "pw": pw_w.text().strip() if pw_w else "",
            "priority": pri_w.value() if pri_w else row + 1,
        }

        ws = _load_json("wholesalers.json")
        new_wid = name.lower().replace(" ", "_")
        if new_wid != old_wid:
            ws.pop(old_wid, None)
            # settings.json에서도 old_wid → new_wid 전환
            self._sync_settings_rename_wholesaler(old_wid, new_wid)
        ws[new_wid] = data
        _save_json("wholesalers.json", ws)

        # 새 wid가 분배비율에 없으면 추가
        self._sync_settings_for_new_wholesaler(new_wid)

        self._load_wholesalers()
        self._notify_wholesaler_changed()

    def _del_wholesaler_row(self, row: int):
        """행을 삭제하고 JSON에서도 제거."""
        ws = _load_json("wholesalers.json")
        ws_list = list(ws.keys())
        if row < len(ws_list):
            wid = ws_list[row]
            name = ws[wid].get("name", wid)
            reply = QMessageBox.question(
                self, "삭제 확인",
                f"'{name}' 도매상을 삭제하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            ws.pop(wid, None)
            _save_json("wholesalers.json", ws)
            self._sync_settings_remove_wholesaler(wid)

        self._load_wholesalers()
        self._notify_wholesaler_changed()

    def _save_wholesalers(self):
        """전체 테이블에서 인라인 편집 중인 행이 있으면 확정 후 저장."""
        # 편집 중인 행이 있는지 확인
        for row in range(self.ws_table.rowCount()):
            w = self.ws_table.cellWidget(row, 0)
            if isinstance(w, QLineEdit):
                self._confirm_ws_row(row)
                return

        QMessageBox.information(self, "저장", "도매상 정보가 저장되었습니다.")
        self._notify_wholesaler_changed()

    # --- 제외 목록 ---
    def _load_exclusions(self):
        exc = _load_json("exclusions.json")

        # 통합 약품명 조회
        from core.drug_api import get_drug_names
        codes = list(exc.keys())
        drug_names = get_drug_names(codes) if codes else {}

        self.exc_table.setRowCount(len(exc))
        for row, (code, data) in enumerate(exc.items()):
            # 보험코드
            code_item = QTableWidgetItem(code)
            code_item.setFlags(code_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.exc_table.setItem(row, 0, code_item)

            # 약품명
            name = data.get("drug_name") or drug_names.get(code, code)
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.exc_table.setItem(row, 1, name_item)

            # 사유
            reason = data.get("reason", "")
            until = data.get("exclude_until", "")
            if not reason:
                reason = "영구" if until == "permanent" else until
            reason_item = QTableWidgetItem(reason)
            reason_item.setFlags(reason_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.exc_table.setItem(row, 2, reason_item)

            # 해제 버튼
            del_btn = QPushButton("해제")
            del_btn.setStyleSheet(btn_small_danger())
            del_btn.clicked.connect(lambda _, c=code, r=row: self._del_exclusion(c))
            self.exc_table.setCellWidget(row, 3, del_btn)

            self.exc_table.setRowHeight(row, 44)

    def _filter_exc_table(self, text: str):
        text = text.strip().lower()
        for row in range(self.exc_table.rowCount()):
            match = True
            if text:
                code = (self.exc_table.item(row, 0) or QTableWidgetItem("")).text().lower()
                name = (self.exc_table.item(row, 1) or QTableWidgetItem("")).text().lower()
                match = text in code or text in name
            self.exc_table.setRowHidden(row, not match)

    def _filter_inv_table(self, text: str):
        text = text.strip().lower()
        for row in range(self.inv_table.rowCount()):
            match = True
            if text:
                code = (self.inv_table.item(row, 0) or QTableWidgetItem("")).text().lower()
                name = (self.inv_table.item(row, 1) or QTableWidgetItem("")).text().lower()
                match = text in code or text in name
            self.inv_table.setRowHidden(row, not match)

    def _del_exclusion(self, code: str = ""):
        """제외 해제 — 먼저 주문 타입을 설정하고 해제한다."""
        if not code:
            return

        exc = _load_json("exclusions.json")
        entry = exc.get(code, {})
        drug_name = entry.get("drug_name", code)

        # 해제 전에 주문 방식 설정 팝업
        from core.inventory import get_drug_config, set_drug_config
        from tabs.drug_setup_dialog import DrugSetupDialog

        cfg = get_drug_config(code) or {}

        dlg = DrugSetupDialog(
            drug_name=drug_name,
            insurance_code=code,
            today_qty=0,
            unit_options=cfg.get("unit_options", []) or None,
            current_config=cfg,
            parent=self,
        )

        if dlg.exec() != DrugSetupDialog.DialogCode.Accepted or not dlg.result_config:
            return  # 취소 시 제외 유지

        if dlg.result_config["order_type"] == "exclude":
            # 다시 제외를 선택한 경우 → 해제 안 함
            QMessageBox.information(self, "알림", "자동주문 제외가 유지됩니다.")
            return

        # dialog 내에서 재고가 변경됐을 수 있으므로 최신 cfg를 다시 읽는다
        fresh_cfg = get_drug_config(code) or cfg

        new_cfg = {
            **fresh_cfg,
            "name": drug_name,
            "order_type": dlg.result_config["order_type"],
            "preferred_unit": dlg.result_config["preferred_unit"],
            "unit_options": dlg.result_config["unit_options"] or fresh_cfg.get("unit_options", []),
            "target_stock": dlg.result_config["target_stock"],
            "unit": dlg.result_config.get("unit", "정"),
        }
        set_drug_config(code, new_cfg)

        # 제외 목록에서 제거
        exc.pop(code, None)
        _save_json("exclusions.json", exc)

        self._load_exclusions()
        self._load_inventory()

    # --- 약품 재고/주문 관리 ---
    def _load_inventory(self):
        from core.inventory import get_current_stocks_bulk, load_inventory

        inv = load_inventory()
        type_labels = {"immediate": "즉시", "stock": "적정재고", "manual": "수동"}

        # 최근 3개월 내 출고 이력이 있는 약품 조회 → inventory에 없으면 자동 등록
        recent_codes = set()
        try:
            from core.db_reader import fetch_all_prescribed_drugs
            from core.inventory import save_inventory

            recent_drugs = fetch_all_prescribed_drugs(months=3)
            recent_codes = {d["insurance_code"] for d in recent_drugs}

            changed = False
            for drug in recent_drugs:
                code = drug["insurance_code"]
                if code not in inv:
                    inv[code] = {
                        "name": drug.get("drug_name", ""),
                        "order_type": "immediate",
                        "preferred_unit": 0,
                        "target_stock": 0,
                        "unit": "정",
                        "base_stock": 0,
                        "current_stock": 0,
                        "app_order_stock": 0,
                    }
                    changed = True
                elif not inv[code].get("name") and drug.get("drug_name"):
                    inv[code]["name"] = drug["drug_name"]
                    changed = True

            if changed:
                save_inventory(inv)

        except Exception as e:
            print(f"[설정] 처방 약품 조회 실패: {e}")

        # 최근 3개월 출고 이력 있거나 사용자가 직접 설정한 약품만 표시
        sorted_items = []
        for code, data in inv.items():
            is_active = code in recent_codes
            has_custom_config = data.get("order_type") in ("stock", "manual")
            if is_active or has_custom_config:
                sorted_items.append((code, data))

        sorted_items.sort(key=lambda x: x[1].get("name", ""))

        # ── 재고 일괄 조회 (DB 쿼리 1회) ──
        bulk_input = [
            (
                code,
                data.get("stock_set_date", ""),
                data.get("base_stock", data.get("current_stock", 0)),
                data.get("app_order_stock", 0),
            )
            for code, data in sorted_items
        ]
        stock_map = get_current_stocks_bulk(bulk_input)

        # ── 테이블 렌더링 (업데이트 일시 중지로 속도 최적화) ──
        self.inv_table.setUpdatesEnabled(False)
        self.inv_table.blockSignals(True)
        self.inv_table.setRowCount(len(sorted_items))
        for row, (code, data) in enumerate(sorted_items):
            # 보험코드
            code_item = QTableWidgetItem(code)
            code_item.setFlags(code_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.inv_table.setItem(row, 0, code_item)

            # 약품명
            name_item = QTableWidgetItem(data.get("name", ""))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.inv_table.setItem(row, 1, name_item)

            # 주문방식
            order_type = data.get("order_type", "")
            type_text = type_labels.get(order_type, "미설정") if order_type else "미설정"
            type_item = QTableWidgetItem(type_text)
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.inv_table.setItem(row, 2, type_item)

            # 선호규격
            pref = data.get("preferred_unit", 0)
            drug_unit = data.get("unit", "정")
            pref_text = f"{pref}{drug_unit}" if pref else "-"
            pref_item = QTableWidgetItem(pref_text)
            pref_item.setFlags(pref_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.inv_table.setItem(row, 3, pref_item)

            # 적정재고
            target_val = data.get("target_stock", 0)
            target_text = f"{target_val} {drug_unit}" if target_val else "-"
            target_item = QTableWidgetItem(target_text)
            target_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            target_item.setFlags(target_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.inv_table.setItem(row, 4, target_item)

            # 현재재고 (일괄 조회 결과 사용)
            live_stock = stock_map.get(code, 0)
            stock_text = f"{live_stock} {drug_unit}"
            stock_item = QTableWidgetItem(stock_text)
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            stock_item.setFlags(stock_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.inv_table.setItem(row, 5, stock_item)

            # 수정 버튼
            edit_btn = QPushButton("수정")
            edit_btn.setStyleSheet(btn_small_primary())
            edit_btn.clicked.connect(lambda _, c=code: self._edit_inventory_item(c))
            self.inv_table.setCellWidget(row, 6, edit_btn)

            # 삭제 버튼
            del_btn = QPushButton("삭제")
            del_btn.setStyleSheet(btn_small_danger())
            del_btn.clicked.connect(lambda _, c=code: self._del_inventory_item(c))
            self.inv_table.setCellWidget(row, 7, del_btn)

            self.inv_table.setRowHeight(row, 44)

        self.inv_table.blockSignals(False)
        self.inv_table.setUpdatesEnabled(True)

    def _edit_inventory_item(self, code: str):
        from core.inventory import get_drug_config, set_drug_config
        from tabs.drug_setup_dialog import DrugSetupDialog

        cfg = get_drug_config(code) or {}

        # 미설정 약품이면 테이블에서 약품명 가져오기
        drug_name = cfg.get("name", "")
        if not drug_name:
            for row in range(self.inv_table.rowCount()):
                item = self.inv_table.item(row, 0)
                if item and item.text() == code:
                    name_item = self.inv_table.item(row, 1)
                    drug_name = name_item.text() if name_item else code
                    break
            if not drug_name:
                drug_name = code

        dlg = DrugSetupDialog(
            drug_name=drug_name,
            insurance_code=code,
            today_qty=0,
            unit_options=cfg.get("unit_options", []) or None,
            current_config=cfg,
            parent=self,
        )

        if dlg.exec() == DrugSetupDialog.DialogCode.Accepted and dlg.result_config:
            if dlg.result_config["order_type"] == "exclude":
                # 제외 처리
                exc = _load_json("exclusions.json")
                exc[code] = {"exclude_until": "permanent", "reason": "자동주문 제외", "drug_name": drug_name}
                _save_json("exclusions.json", exc)
                from core.inventory import remove_drug_config
                remove_drug_config(code)
                self._load_inventory()
                self._load_exclusions()
                return

            # dialog 내에서 재고가 변경됐을 수 있으므로 최신 cfg를 다시 읽는다
            fresh_cfg = get_drug_config(code) or cfg

            new_cfg = {
                **fresh_cfg,
                "name": drug_name,
                "order_type": dlg.result_config["order_type"],
                "preferred_unit": dlg.result_config["preferred_unit"],
                "unit_options": dlg.result_config["unit_options"] or fresh_cfg.get("unit_options", []),
                "target_stock": dlg.result_config["target_stock"],
                "unit": dlg.result_config.get("unit", "정"),
            }
            set_drug_config(code, new_cfg)
            self._load_inventory()

    def _del_inventory_item(self, code: str = ""):
        if not code:
            return
        from core.inventory import get_drug_config, remove_drug_config
        cfg = get_drug_config(code)
        name = cfg.get("name", code) if cfg else code
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"'{name}' 약품 설정을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            remove_drug_config(code)
            self._load_inventory()

    # --- 예약 자동 주문 ---
    def _add_schedule_time_row(self, time: QTime = None, enabled: bool = True):
        """예약 시간 행을 추가한다."""
        from PyQt6.QtWidgets import QCheckBox

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        cb = QCheckBox()
        cb.setChecked(enabled)
        row_layout.addWidget(cb)

        time_edit = QTimeEdit()
        time_edit.setDisplayFormat("HH:mm")
        time_edit.setTime(time or QTime(12, 0))
        time_edit.setMinimumWidth(100)
        row_layout.addWidget(time_edit)

        range_label = QLabel("")
        range_label.setStyleSheet(f"color: {_BLUE}; font-size: 11px;")
        row_layout.addWidget(range_label)

        del_btn = QPushButton("삭제")
        del_btn.setStyleSheet(btn_small_danger())
        del_btn.clicked.connect(lambda: self._remove_schedule_time_row(row_widget))
        row_layout.addWidget(del_btn)

        row_layout.addStretch()

        self._sched_time_rows.append((row_widget, time_edit, cb, range_label))
        self.sched_time_list.addWidget(row_widget)

        # 시간 변경 시 범위 설명 업데이트
        time_edit.timeChanged.connect(lambda: self._update_time_range_labels())
        self._update_time_range_labels()

    def _remove_schedule_time_row(self, widget):
        """예약 시간 행을 삭제한다."""
        self._sched_time_rows = [
            (w, t, c, l) for w, t, c, l in self._sched_time_rows if w is not widget
        ]
        self.sched_time_list.removeWidget(widget)
        widget.deleteLater()

    def _update_time_range_labels(self):
        """각 시간대 행의 범위 설명을 업데이트한다."""
        times_with_labels = [
            (t.time().toString("HH:mm"), l)
            for _, t, _, l in self._sched_time_rows
        ]
        sorted_times = sorted(times_with_labels, key=lambda x: x[0])

        for i, (t_str, label) in enumerate(sorted_times):
            if i == 0:
                label.setText(f"09:00 ~ {t_str} 처방 주문")
            else:
                prev = sorted_times[i - 1][0]
                label.setText(f"{prev} ~ {t_str} 처방 주문")

    def _update_once_desc(self):
        t = self._sched_once_time.time().toString("HH:mm")
        self._sched_once_desc.setText(f"→ 09:00 ~ {t} 전체 처방 주문")

    # --- 주문 분배 ---
    def _load_split_settings(self):
        settings = _load_json("settings.json")
        mode = settings.get("order_split_mode", "single")
        if mode == "even":
            self._split_even.setChecked(True)
        else:
            self._split_single.setChecked(True)

        # 기본 도매상 콤보 갱신 (도매상 추가/삭제 반영)
        ws_all = _load_json("wholesalers.json")
        default_ws = settings.get("default_wholesaler", "")
        self._default_ws_combo.blockSignals(True)
        self._default_ws_combo.clear()
        for wid, w in ws_all.items():
            self._default_ws_combo.addItem(w["name"], wid)
        idx = self._default_ws_combo.findData(default_ws)
        if idx >= 0:
            self._default_ws_combo.setCurrentIndex(idx)
        self._default_ws_combo.blockSignals(False)

        # 기존 위젯 제거
        from PyQt6.QtWidgets import QCheckBox
        for wid, (cb, spin, row_widget) in self._split_ws_rows.items():
            self._split_ws_layout.removeWidget(row_widget)
            row_widget.deleteLater()
        self._split_ws_rows.clear()

        # 기존 합계 라벨 제거
        if hasattr(self, '_split_total_label') and self._split_total_label is not None:
            self._split_ws_layout.removeWidget(self._split_total_label)
            self._split_total_label.deleteLater()
            self._split_total_label = None

        ws = _load_json("wholesalers.json")
        ratios = settings.get("order_split_ratios", {})
        selected = settings.get("order_split_wholesalers", [])

        # 도매상 추가 후 ratios에 누락된 항목 자동 보정
        missing = [wid for wid in ws if wid not in ratios]
        if missing:
            for wid in missing:
                ratios[wid] = 0
            settings["order_split_ratios"] = ratios
            _save_json("settings.json", settings)

        self._split_updating = False  # 비율 자동 조정 중 무한루프 방지

        for wid, w in ws.items():
            row_widget = QWidget()
            row_lay = QHBoxLayout(row_widget)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(8)

            cb = QCheckBox(w.get("name", wid))
            cb.setStyleSheet(
                "QCheckBox { font-size: 13px; font-family: 'Malgun Gothic'; }"
            )
            cb.setChecked(wid in selected)
            cb.stateChanged.connect(lambda _, w=wid: self._on_split_check_changed(w))
            row_lay.addWidget(cb)

            row_lay.addStretch()

            ratio_label = QLabel("비율:")
            ratio_label.setStyleSheet(
                "font-size: 12px; color: #6B7280; font-family: 'Malgun Gothic';"
            )
            row_lay.addWidget(ratio_label)

            spin = QSpinBox()
            spin.setRange(0, 10)
            spin.setValue(ratios.get(wid, 0))
            spin.setMinimumWidth(60)
            spin.setMinimumHeight(30)
            spin.setStyleSheet(
                "QSpinBox { font-size: 13px; font-family: 'Malgun Gothic'; padding: 4px; }"
            )
            spin.setEnabled(wid in selected)
            spin.valueChanged.connect(lambda _, w=wid: self._on_split_ratio_changed(w))
            row_lay.addWidget(spin)

            self._split_ws_rows[wid] = (cb, spin, row_widget)
            self._split_ws_layout.addWidget(row_widget)

        # 비율 합계 표시
        self._split_total_label = QLabel("")
        self._split_total_label.setStyleSheet(
            "font-size: 12px; font-weight: 600; font-family: 'Malgun Gothic';"
        )
        self._split_ws_layout.addWidget(self._split_total_label)
        self._update_split_total_label()

        # 단일 도매상 모드면 체크박스/스핀 비활성화
        if self._split_single.isChecked():
            self._on_split_mode_changed(True)

    def _get_checked_split_wids(self) -> list[str]:
        """체크된 도매상 ID 목록."""
        return [wid for wid, (cb, _, _) in self._split_ws_rows.items() if cb.isChecked()]

    def _on_split_mode_changed(self, single_checked: bool):
        """단일 도매상 선택 시 분배 체크박스 전부 해제 + 비활성화."""
        for wid, (cb, spin, _) in self._split_ws_rows.items():
            cb.setEnabled(not single_checked)
            spin.setEnabled(not single_checked)
            if single_checked:
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
                spin.setValue(0)
        if single_checked:
            self._update_split_total_label()

    def _on_split_check_changed(self, changed_wid: str):
        """도매상 체크 변경 시 비율을 자동 균등 배분한다."""
        if self._split_updating:
            return
        self._split_updating = True

        checked = self._get_checked_split_wids()

        # 체크 해제된 도매상 비율 0, 스핀 비활성
        for wid, (cb, spin, _) in self._split_ws_rows.items():
            if not cb.isChecked():
                spin.setValue(0)
                spin.setEnabled(False)
            else:
                spin.setEnabled(True)

        # 체크된 도매상들에 10을 균등 배분
        if checked:
            base = 10 // len(checked)
            remainder = 10 % len(checked)
            for i, wid in enumerate(checked):
                _, spin, _ = self._split_ws_rows[wid]
                val = base + (1 if i < remainder else 0)
                spin.setValue(val)

        self._update_split_total_label()
        self._split_updating = False

    def _on_split_ratio_changed(self, changed_wid: str):
        """비율 스핀박스 값 변경 시 나머지를 자동 조정해서 합 10 유지."""
        if self._split_updating:
            return
        self._split_updating = True

        checked = self._get_checked_split_wids()
        if len(checked) < 2:
            self._split_updating = False
            self._update_split_total_label()
            return

        # 변경된 도매상의 값 고정, 나머지에서 차액 분배
        changed_val = self._split_ws_rows[changed_wid][1].value()
        others = [wid for wid in checked if wid != changed_wid]
        remaining = 10 - changed_val

        if remaining < 0:
            remaining = 0
        if remaining > len(others) * 10:
            remaining = len(others) * 10

        # 나머지 도매상에 균등 분배
        if others:
            base = remaining // len(others)
            remainder_count = remaining % len(others)
            for i, wid in enumerate(others):
                _, spin, _ = self._split_ws_rows[wid]
                val = base + (1 if i < remainder_count else 0)
                spin.setValue(max(0, min(10, val)))

        self._update_split_total_label()
        self._split_updating = False

    def _update_split_total_label(self):
        """비율 합계 라벨 업데이트."""
        checked = self._get_checked_split_wids()
        if not checked:
            self._split_total_label.setText("")
            return

        total = sum(self._split_ws_rows[wid][1].value() for wid in checked)
        parts = []
        for wid in checked:
            cb, spin, _ = self._split_ws_rows[wid]
            parts.append(f"{cb.text()} {spin.value()}")

        color = "#22C55E" if total == 10 else "#EF4444"
        self._split_total_label.setText(f"비율: {' : '.join(parts)} (합계 {total}/10)")
        self._split_total_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {color}; "
            f"font-family: 'Malgun Gothic';"
        )

    def _save_split_settings(self):
        checked = self._get_checked_split_wids()

        # 합계 검증
        if self._split_even.isChecked() and checked:
            total = sum(self._split_ws_rows[wid][1].value() for wid in checked)
            if total != 10:
                QMessageBox.warning(self, "알림", f"비율 합계가 {total}입니다. 10이 되어야 합니다.")
                return
            if len(checked) < 2:
                QMessageBox.warning(self, "알림", "분배할 도매상을 2개 이상 선택하세요.")
                return

        settings = _load_json("settings.json")
        settings["order_split_mode"] = "even" if self._split_even.isChecked() else "single"

        ratios = {}
        for wid, (cb, spin, _) in self._split_ws_rows.items():
            ratios[wid] = spin.value()

        settings["order_split_wholesalers"] = checked
        settings["order_split_ratios"] = ratios
        settings["default_wholesaler"] = self._default_ws_combo.currentData() or ""
        _save_json("settings.json", settings)

        if self._split_even.isChecked() and checked:
            parts = []
            for wid in checked:
                cb, spin, _ = self._split_ws_rows[wid]
                parts.append(f"{cb.text()} {spin.value()}")
            QMessageBox.information(self, "저장", f"비율 분배: {' : '.join(parts)}")
        else:
            QMessageBox.information(self, "저장", "단일 도매상 주문")

        if self._on_schedule_changed:
            self._on_schedule_changed()

    # --- 주문 확정 방식 ---
    def _load_confirm_settings(self):
        settings = _load_json("settings.json")
        mode = settings.get("order_confirm_mode", "auto")
        if mode == "cart_only":
            self._confirm_cart.setChecked(True)
        else:
            self._confirm_auto.setChecked(True)

    def _save_confirm_settings(self):
        settings = _load_json("settings.json")
        settings["order_confirm_mode"] = "cart_only" if self._confirm_cart.isChecked() else "auto"
        _save_json("settings.json", settings)
        mode_text = "장바구니만 담기" if self._confirm_cart.isChecked() else "자동 주문 확정"
        QMessageBox.information(self, "저장", f"주문 확정 방식: {mode_text}")

        if self._on_schedule_changed:
            self._on_schedule_changed()

    def scroll_to_schedule(self):
        """예약 자동 주문 카드로 스크롤한다."""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self._scroll.ensureWidgetVisible(
            self.sched_card, 0, 20
        ))

    def _on_sched_enabled_toggled(self, enabled: bool):
        """예약 자동 주문 체크 해제 시 하위 컨트롤 전부 비활성화."""
        self._sched_radio_multi.setEnabled(enabled)
        self._sched_radio_once.setEnabled(enabled)
        self._sched_once_time.setEnabled(enabled)
        # _sched_time_rows: (row_widget, time_edit, checkbox, range_label)
        for row_widget, time_edit, cb, _ in self._sched_time_rows:
            time_edit.setEnabled(enabled)
            cb.setEnabled(enabled)
            cb.setChecked(cb.isChecked() and enabled)

    def _load_schedule_settings(self):
        settings = _load_json("settings.json")
        self.sched_enabled_cb.setChecked(settings.get("schedule_enabled", False))
        self._on_sched_enabled_toggled(self.sched_enabled_cb.isChecked())

        # 모드
        mode = settings.get("schedule_mode", "multiple")
        if mode == "once":
            self._sched_radio_once.setChecked(True)
        else:
            self._sched_radio_multi.setChecked(True)

        # 일 1회 시간
        once_time = settings.get("schedule_once_time", "18:30")
        p = once_time.split(":")
        self._sched_once_time.setTime(QTime(int(p[0]), int(p[1]) if len(p) > 1 else 0))
        self._update_once_desc()

        # 기존 시간 행 전부 제거
        for widget, _, _, _ in self._sched_time_rows:
            self.sched_time_list.removeWidget(widget)
            widget.deleteLater()
        self._sched_time_rows.clear()

        # 일 2회+ 시간 로드 (레거시 order_schedule_times 호환)
        times = settings.get("schedule_multi_times",
                             settings.get("order_schedule_times", ["13:00", "18:30"]))
        for item in times:
            if isinstance(item, dict):
                t_str = item.get("time", "12:00")
                enabled = item.get("enabled", True)
            else:
                t_str = item
                enabled = True
            parts = t_str.split(":")
            h = int(parts[0]) if parts else 12
            m = int(parts[1]) if len(parts) > 1 else 0
            self._add_schedule_time_row(QTime(h, m), enabled)

    def _save_schedule_settings(self):
        settings = _load_json("settings.json")
        settings["schedule_enabled"] = self.sched_enabled_cb.isChecked()

        if self._sched_radio_once.isChecked():
            settings["schedule_mode"] = "once"
        else:
            settings["schedule_mode"] = "multiple"

        settings["schedule_once_time"] = self._sched_once_time.time().toString("HH:mm")
        settings["schedule_multi_times"] = [
            {"time": time_edit.time().toString("HH:mm"), "enabled": cb.isChecked()}
            for _, time_edit, cb, _ in self._sched_time_rows
        ]
        # 레거시 키 제거
        settings.pop("order_schedule_times", None)
        _save_json("settings.json", settings)

        status = "켜짐" if self.sched_enabled_cb.isChecked() else "꺼짐"
        if self._sched_radio_once.isChecked():
            time_str = self._sched_once_time.time().toString("HH:mm")
            detail = f"일 1회 / {time_str}"
        else:
            enabled_times = [
                time_edit.time().toString("HH:mm")
                for _, time_edit, cb, _ in self._sched_time_rows
                if cb.isChecked()
            ]
            detail = f"일 {len(enabled_times)}회 / {', '.join(enabled_times)}" if enabled_times else "활성화된 시간 없음"
        QMessageBox.information(
            self, "저장",
            f"예약 주문 설정이 저장되었습니다.\n"
            f"자동 주문: {status} / {detail}"
        )

        # 자동주문 탭 요약 동기화
        if self._on_schedule_changed:
            self._on_schedule_changed()

    # --- 알림 설정 ---
    def _load_notification_settings(self):
        settings = _load_json("settings.json")
        time_str = settings.get("notification_time", "09:00")
        parts = time_str.split(":")
        self.noti_time.setTime(QTime(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0))
        self.kakao_key_input.setText(settings.get("kakao_api_key", ""))
        self.kakao_sender_input.setText(settings.get("kakao_sender", ""))

    def _save_notification_settings(self):
        settings = _load_json("settings.json")
        settings["notification_time"] = self.noti_time.time().toString("HH:mm")
        settings["kakao_api_key"] = self.kakao_key_input.text().strip()
        settings["kakao_sender"] = self.kakao_sender_input.text().strip()
        _save_json("settings.json", settings)
        QMessageBox.information(self, "저장", "알림 설정이 저장되었습니다.")

    # --- 업데이트 설정 ---
    def _load_update_settings(self):
        settings = _load_json("settings.json")
        self.repo_input.setText(settings.get("github_repo", ""))

    def _save_update_settings(self):
        settings = _load_json("settings.json")
        settings["github_repo"] = self.repo_input.text().strip()
        _save_json("settings.json", settings)
        QMessageBox.information(self, "저장", "업데이트 설정이 저장되었습니다.")

    def _manual_check_update(self):
        self.upd_status_label.setText("확인 중...")
        self.upd_status_label.setStyleSheet(f"color: {_BLUE}; font-weight: 600;")

        from core.updater import check_update
        try:
            result = check_update()
            if result:
                self.upd_status_label.setText(
                    f"새 버전 v{result['version']} 사용 가능!"
                )
                self.upd_status_label.setStyleSheet(f"color: {_GREEN}; font-weight: 700;")
                # 메인 윈도우의 업데이트 다이얼로그 호출
                main_window = self.window()
                if hasattr(main_window, '_on_update_available'):
                    main_window._on_update_available(result)
            else:
                self.upd_status_label.setText("최신 버전입니다.")
                self.upd_status_label.setStyleSheet(f"color: {_GREEN}; font-weight: 700;")
        except Exception as e:
            self.upd_status_label.setText(f"확인 실패: {e}")
            self.upd_status_label.setStyleSheet(f"color: {_RED}; font-weight: 700;")

    # --- 원격 지원 ---
    # --- DB 구조 내보내기 ---
    def _on_export_db_structure(self):
        settings = _load_json("settings.json")
        db = settings.get("db", {})
        server = db.get("server", "")
        database = db.get("database", "")
        program = settings.get("pharmacy_program", "unknown")

        if not server or not database:
            QMessageBox.warning(self, "알림", "DB 연결 정보가 없습니다. 초기 설정을 먼저 진행하세요.")
            return

        try:
            from core.db_inspector import export_structure
            path = export_structure(server, database, program)

            self._inspect_status.setText(f"저장 완료: {os.path.basename(path)}")
            self._inspect_status.setStyleSheet(
                f"font-size: 12px; color: {_GREEN}; font-weight: 600; "
                f"font-family: 'Malgun Gothic';"
            )

            # 파일 위치 열기
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.abspath(path)])

            QMessageBox.information(
                self, "내보내기 완료",
                f"DB 구조가 저장되었습니다.\n\n"
                f"파일: {os.path.basename(path)}\n\n"
                f"이 파일을 개발자에게 보내주세요.\n"
                f"(환자 정보 등 개인정보는 포함되지 않습니다)"
            )
        except Exception as e:
            self._inspect_status.setText(f"실패: {e}")
            self._inspect_status.setStyleSheet(
                f"font-size: 12px; color: {_RED}; font-family: 'Malgun Gothic';"
            )

    def _on_open_log(self):
        """오류 로그 파일을 메모장으로 연다."""
        from core.logger import get_log_path
        log_path = get_log_path()
        if os.path.exists(log_path):
            os.startfile(log_path)
        else:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "로그", "아직 로그 파일이 없습니다.")

    def _on_send_log(self):
        """오류 로그를 서버에 전송한다."""
        from PyQt6.QtWidgets import QMessageBox
        from core.logger import upload_error, get_log_path

        log_path = get_log_path()
        if not os.path.exists(log_path):
            QMessageBox.information(self, "로그", "아직 로그 파일이 없습니다.")
            return

        try:
            upload_error("USER_REPORT", "사용자가 오류 로그를 전송했습니다")
            QMessageBox.information(
                self, "전송 완료",
                "오류 로그가 개발팀에 전송되었습니다.\n빠르게 확인하겠습니다."
            )
        except Exception as e:
            QMessageBox.warning(
                self, "전송 실패",
                f"로그 전송에 실패했습니다.\n오류 로그 열기로 직접 확인해주세요."
            )

    def _on_remote_support(self):
        import os
        import subprocess
        import webbrowser

        # AnyDesk 경로 탐색
        anydesk_paths = [
            os.path.expandvars(r"%ProgramFiles(x86)%\AnyDesk\AnyDesk.exe"),
            os.path.expandvars(r"%ProgramFiles%\AnyDesk\AnyDesk.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\AnyDesk\AnyDesk.exe"),
            os.path.expandvars(r"%APPDATA%\AnyDesk\AnyDesk.exe"),
        ]

        anydesk_exe = None
        for path in anydesk_paths:
            if os.path.exists(path):
                anydesk_exe = path
                break

        if not anydesk_exe:
            # AnyDesk 미설치
            reply = QMessageBox.question(
                self, "AnyDesk 미설치",
                "원격 지원을 위해 AnyDesk가 필요합니다.\n"
                "다운로드 페이지를 열까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                webbrowser.open("https://anydesk.com/ko/downloads")
            return

        # AnyDesk 실행
        try:
            subprocess.Popen([anydesk_exe])
        except Exception as e:
            QMessageBox.warning(self, "오류", f"AnyDesk 실행 실패: {e}")
            return

        # AnyDesk ID 가져오기 (명령줄)
        anydesk_id = ""
        try:
            result = subprocess.run(
                [anydesk_exe, "--get-id"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            anydesk_id = result.stdout.strip()
        except Exception:
            pass

        if anydesk_id:
            # 클립보드에 복사
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(anydesk_id)

            self._remote_status.setText(f"AnyDesk ID: {anydesk_id} (복사됨)")
            self._remote_status.setStyleSheet(
                f"font-size: 12px; color: {_GREEN}; font-weight: 600; "
                f"font-family: 'Malgun Gothic';"
            )

            # 카카오톡 오픈채팅 안내
            reply = QMessageBox.information(
                self, "원격 지원 준비 완료",
                f"AnyDesk ID: {anydesk_id}\n"
                f"(클립보드에 복사되었습니다)\n\n"
                f"카카오톡 오픈채팅방에 ID를 보내주세요.",
                QMessageBox.StandardButton.Ok,
            )

            # TODO: 실제 오픈채팅방 링크로 교체
            # webbrowser.open("https://open.kakao.com/o/xxxxx")
        else:
            self._remote_status.setText("AnyDesk가 실행되었습니다. ID를 확인해주세요.")
            self._remote_status.setStyleSheet(
                f"font-size: 12px; color: {_BLUE}; font-family: 'Malgun Gothic';"
            )
