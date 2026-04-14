"""반품 탭 - 도매상 사이트 입고이력 조회 → 반품 리스트 관리."""

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.styles import (
    BLUE as _BLUE,
    BLUE_DARK as _BLUE_DARK,
    GREEN as _GREEN,
    ORANGE as _ORANGE,
    TEXT_SEC as _TEXT_SEC,
    CARD_FRAME,
    TITLE,
    SUBTITLE,
    STATUS_LABEL,
    INFO_LABEL_BLUE,
    btn_primary,
    btn_warning,
    btn_small_danger,
    btn_small_primary,
)


class HistorySearchWorker(QThread):
    """도매상 사이트 입고이력 검색 백그라운드 스레드."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, drug_name: str, lot_number: str = "",
                 search_online: bool = True):
        super().__init__()
        self.drug_name = drug_name
        self.lot_number = lot_number
        self.search_online = search_online

    def run(self):
        try:
            if self.search_online:
                from core.return_engine import search_all_sources
                results = search_all_sources(
                    self.drug_name,
                    self.lot_number,
                    progress_callback=lambda msg: self.progress.emit(msg),
                )
            else:
                from core.return_engine import find_orders_for_return
                results = find_orders_for_return(self.drug_name)
                for r in results:
                    r["source"] = "앱 주문이력"
                    r.setdefault("lot_number", "")

            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class ReturnTab(QWidget):
    def __init__(self):
        super().__init__()
        self._search_results = []
        self._selected_idx = None
        self._init_ui()
        self._load_return_list()

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

        # ━━━ 1. 이력 조회 카드 ━━━
        form_widget = QWidget()
        f_lay = QVBoxLayout(form_widget)
        f_lay.setContentsMargins(4, 4, 4, 4)
        f_lay.setSpacing(14)

        title = QLabel("반품 이력 조회")
        title.setStyleSheet(TITLE)
        f_lay.addWidget(title)

        desc = QLabel(
            "약품명과 로트번호를 입력하고 이력을 조회하세요. "
            "도매상 사이트와 앱 주문이력에서 동시에 검색합니다."
        )
        desc.setStyleSheet(STATUS_LABEL)
        f_lay.addWidget(desc)

        # 입력 행
        form = QHBoxLayout()
        form.setSpacing(10)

        drug_label = QLabel("약품명")
        drug_label.setStyleSheet(SUBTITLE)
        form.addWidget(drug_label)
        self.drug_input = QLineEdit()
        self.drug_input.setPlaceholderText("약품명 입력")
        self.drug_input.setMinimumWidth(180)
        self.drug_input.returnPressed.connect(self._on_search)
        form.addWidget(self.drug_input)

        lot_label = QLabel("로트번호")
        lot_label.setStyleSheet(SUBTITLE)
        form.addWidget(lot_label)
        self.lot_input = QLineEdit()
        self.lot_input.setPlaceholderText("로트번호 입력")
        self.lot_input.setMinimumWidth(150)
        form.addWidget(self.lot_input)

        self.search_btn = QPushButton("이력 조회")
        self.search_btn.setStyleSheet(btn_primary())
        self.search_btn.clicked.connect(self._on_search)
        form.addWidget(self.search_btn)

        self.add_btn = QPushButton("반품 리스트 추가")
        self.add_btn.setStyleSheet(btn_warning())
        self.add_btn.clicked.connect(self._on_add_to_list)
        self.add_btn.setEnabled(False)
        form.addWidget(self.add_btn)

        f_lay.addLayout(form)

        # 검색 옵션
        opt_row = QHBoxLayout()
        opt_row.setSpacing(8)
        self.online_check = QCheckBox("도매상 사이트 검색 포함")
        self.online_check.setChecked(True)
        self.online_check.setStyleSheet("QCheckBox { font-size: 12px; }")
        opt_row.addWidget(self.online_check)
        opt_row.addStretch()
        f_lay.addLayout(opt_row)

        # 상태 라벨
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(STATUS_LABEL)
        f_lay.addWidget(self.status_label)

        # 검색 결과 테이블
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(7)
        self.result_table.setHorizontalHeaderLabels(
            ["출처", "약품명", "로트번호", "수량", "도매상", "주문일", "선택"]
        )
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setShowGrid(False)
        rh = self.result_table.horizontalHeader()
        rh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        rh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        rh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        rh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        rh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        rh.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        rh.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.result_table.setColumnWidth(0, 90)
        self.result_table.setColumnWidth(2, 100)
        self.result_table.setColumnWidth(3, 70)
        self.result_table.setColumnWidth(4, 100)
        self.result_table.setColumnWidth(5, 100)
        self.result_table.setColumnWidth(6, 70)
        self.result_table.setMinimumHeight(150)
        self.result_table.setMaximumHeight(250)
        self.result_table.hide()
        f_lay.addWidget(self.result_table)

        # 선택된 항목 정보
        self.selected_label = QLabel("")
        self.selected_label.setStyleSheet(INFO_LABEL_BLUE)
        self.selected_label.setWordWrap(True)
        self.selected_label.hide()
        f_lay.addWidget(self.selected_label)

        form_card = _card(form_widget)
        layout.addWidget(form_card)

        # ━━━ 2. 반품 리스트 카드 ━━━
        list_widget = QWidget()
        l_lay = QVBoxLayout(list_widget)
        l_lay.setContentsMargins(4, 4, 4, 4)
        l_lay.setSpacing(12)

        l_top = QHBoxLayout()
        l_title = QLabel("반품 리스트")
        l_title.setStyleSheet(TITLE)
        l_top.addWidget(l_title)
        l_top.addStretch()

        # 기간 필터 (월별)
        self.list_period = QComboBox()
        self.list_period.addItems(["최근 1개월", "최근 3개월", "최근 6개월", "최근 1년"])
        self.list_period.setCurrentIndex(1)
        self.list_period.currentIndexChanged.connect(self._load_return_list)
        l_top.addWidget(self.list_period)

        # 정렬 기준
        sort_label = QLabel("정렬:")
        sort_label.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px;")
        l_top.addWidget(sort_label)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["최신순", "도매상별", "월별"])
        self.sort_combo.currentIndexChanged.connect(self._load_return_list)
        l_top.addWidget(self.sort_combo)

        refresh_btn = QPushButton("새로고침")
        refresh_btn.clicked.connect(self._load_return_list)
        l_top.addWidget(refresh_btn)
        l_lay.addLayout(l_top)

        self.list_table = QTableWidget()
        self.list_table.setColumnCount(8)
        self.list_table.setHorizontalHeaderLabels(
            ["등록일", "약품명", "로트번호", "수량", "도매상", "입고일", "상태", "삭제"]
        )
        self.list_table.verticalHeader().setVisible(False)
        self.list_table.setShowGrid(False)
        lh = self.list_table.horizontalHeader()
        lh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, w in [(0, 90), (2, 120), (3, 60), (4, 100), (5, 90), (6, 120), (7, 60)]:
            lh.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.list_table.setColumnWidth(col, w)
        self.list_table.setMinimumHeight(300)
        l_lay.addWidget(self.list_table)

        list_card = _card(list_widget)
        layout.addWidget(list_card, 1)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ─────────────── 이력 조회 ───────────────

    def _on_search(self):
        drug_name = self.drug_input.text().strip()
        if not drug_name:
            QMessageBox.warning(self, "알림", "약품명을 입력하세요.")
            return

        self.search_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self.result_table.hide()
        self.selected_label.hide()
        self._selected_idx = None
        self.status_label.setText("검색 중...")

        lot = self.lot_input.text().strip()
        search_online = self.online_check.isChecked()
        self._worker = HistorySearchWorker(drug_name, lot, search_online)
        self._worker.progress.connect(self._on_search_progress)
        self._worker.finished.connect(self._on_search_done)
        self._worker.error.connect(self._on_search_error)
        self._worker.start()

    def _on_search_progress(self, msg: str):
        self.status_label.setText(msg)

    def _on_search_done(self, results: list):
        self.search_btn.setEnabled(True)
        self._search_results = results

        if not results:
            self.status_label.setText("입고 이력을 찾을 수 없습니다.")
            self.status_label.setStyleSheet(
                "color: #EF4444; font-size: 13px; font-weight: 600;"
            )
            self.result_table.hide()
            return

        matched_count = sum(1 for r in results if r.get("matched"))
        if matched_count:
            self.status_label.setText(
                f"{len(results)}건 검색, 로트번호 매칭 {matched_count}건. "
                f"매칭된 항목을 선택하세요."
            )
            self.status_label.setStyleSheet(
                f"color: {_BLUE}; font-size: 13px; font-weight: 600;"
            )
        else:
            self.status_label.setText(
                f"{len(results)}건 검색됨. 반품할 항목을 선택하세요."
            )
            self.status_label.setStyleSheet(STATUS_LABEL)

        self.result_table.setRowCount(len(results))
        matched_bg = QColor("#EBF5FF")  # 매칭 행 배경색 (연한 파랑)

        for row, r in enumerate(results):
            is_matched = r.get("matched", False)

            source_text = r.get("source", "")
            if is_matched:
                source_text += " (매칭)"
            source_item = QTableWidgetItem(source_text)
            source_item.setFlags(source_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if is_matched:
                source_item.setForeground(QColor(_BLUE))
            self.result_table.setItem(row, 0, source_item)

            name_item = QTableWidgetItem(r.get("drug_name", ""))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.result_table.setItem(row, 1, name_item)

            lot_item = QTableWidgetItem(r.get("lot_number", ""))
            lot_item.setFlags(lot_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            lot_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.result_table.setItem(row, 2, lot_item)

            qty_item = QTableWidgetItem(str(r.get("qty", "")))
            qty_item.setFlags(qty_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.result_table.setItem(row, 3, qty_item)

            ws_item = QTableWidgetItem(r.get("wholesaler_name", ""))
            ws_item.setFlags(ws_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.result_table.setItem(row, 4, ws_item)

            date_item = QTableWidgetItem(r.get("order_date", ""))
            date_item.setFlags(date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.result_table.setItem(row, 5, date_item)

            sel_btn = QPushButton("선택")
            sel_btn.setStyleSheet(btn_small_primary())
            sel_btn.clicked.connect(lambda _, idx=row: self._on_select(idx))
            self.result_table.setCellWidget(row, 6, sel_btn)

            # matched 행 배경색 강조
            if is_matched:
                for col in range(6):
                    item = self.result_table.item(row, col)
                    if item:
                        item.setBackground(matched_bg)

            self.result_table.setRowHeight(row, 40)

        self.result_table.show()

    def _on_search_error(self, msg: str):
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"검색 오류: {msg}")
        self.status_label.setStyleSheet("color: #EF4444; font-size: 13px;")

    def _on_select(self, idx: int):
        if idx >= len(self._search_results):
            return
        self._selected_idx = idx
        order = self._search_results[idx]

        self.selected_label.setText(
            f"선택: {order['drug_name']}  |  "
            f"도매상: {order.get('wholesaler_name', '-')}  |  "
            f"주문일: {order.get('order_date', '-')}  |  "
            f"수량: {order.get('qty', '-')}"
        )
        self.selected_label.show()
        self.add_btn.setEnabled(True)

    # ─────────────── 반품 리스트 추가 ───────────────

    def _on_add_to_list(self):
        drug_name = self.drug_input.text().strip()
        lot = self.lot_input.text().strip()

        if not drug_name:
            QMessageBox.warning(self, "알림", "약품명을 입력하세요.")
            return

        if self._selected_idx is None or self._selected_idx >= len(self._search_results):
            QMessageBox.warning(self, "알림", "반품할 항목을 먼저 선택하세요.")
            return

        order = self._search_results[self._selected_idx]

        from core.return_engine import create_return
        create_return(
            drug_name=order["drug_name"],
            lot_number=lot,
            insurance_code=order.get("insurance_code", ""),
            qty=order.get("qty", 0),
            wholesaler_id=order.get("wholesaler_id", ""),
            wholesaler_name=order.get("wholesaler_name", ""),
            original_order_date=order.get("order_date", ""),
        )

        QMessageBox.information(
            self, "완료",
            f"{order['drug_name']}을(를) 반품 리스트에 추가했습니다."
        )

        # 초기화
        self.drug_input.clear()
        self.lot_input.clear()
        self.result_table.hide()
        self.selected_label.hide()
        self.status_label.clear()
        self.add_btn.setEnabled(False)
        self._search_results = []
        self._selected_idx = None
        self._load_return_list()

    # ─────────────── 반품 리스트 ───────────────

    def _load_return_list(self):
        from core.return_engine import get_return_list, RETURN_STATUS_LABELS

        period_map = {0: 1, 1: 3, 2: 6, 3: 12}
        months = period_map.get(self.list_period.currentIndex(), 3)
        items = get_return_list(months)

        # 정렬
        sort_idx = self.sort_combo.currentIndex()
        if sort_idx == 1:  # 도매상별
            items.sort(key=lambda x: (x.get("wholesaler_name", ""),
                                      x.get("return_date", "")))
        elif sort_idx == 2:  # 월별
            items.sort(key=lambda x: x.get("return_date", "")[:7], reverse=True)
        # 0 = 최신순 → 이미 created_at DESC

        # 정렬 그룹 헤더를 위한 그룹 키 계산
        group_key_fn = None
        if sort_idx == 1:
            group_key_fn = lambda x: x.get("wholesaler_name", "기타")
        elif sort_idx == 2:
            group_key_fn = lambda x: x.get("return_date", "")[:7] or "날짜없음"

        # 테이블 채우기
        if group_key_fn:
            self._populate_grouped(items, group_key_fn, RETURN_STATUS_LABELS)
        else:
            self._populate_flat(items, RETURN_STATUS_LABELS)

    def _populate_flat(self, items: list, status_labels: dict):
        """그룹 없이 플랫하게 테이블을 채운다."""
        self.list_table.setRowCount(len(items))
        for row, h in enumerate(items):
            self._fill_row(row, h, status_labels)

    def _populate_grouped(self, items: list, key_fn, status_labels: dict):
        """그룹 헤더를 넣으며 테이블을 채운다."""
        # 그룹별로 묶기
        groups = []
        current_key = None
        for item in items:
            k = key_fn(item)
            if k != current_key:
                current_key = k
                groups.append((k, []))
            groups[-1][1].append(item)

        total_rows = sum(1 + len(g[1]) for g in groups)
        self.list_table.setRowCount(total_rows)

        row = 0
        for group_name, group_items in groups:
            # 그룹 헤더 행
            header_item = QTableWidgetItem(f"  {group_name} ({len(group_items)}건)")
            header_item.setFlags(Qt.ItemFlag.NoItemFlags)
            font = header_item.font()
            font.setBold(True)
            header_item.setFont(font)
            header_item.setBackground(QColor("#F0F1F3"))
            self.list_table.setItem(row, 0, header_item)
            # 나머지 컬럼도 배경색 통일
            for col in range(1, 8):
                filler = QTableWidgetItem("")
                filler.setFlags(Qt.ItemFlag.NoItemFlags)
                filler.setBackground(QColor("#F0F1F3"))
                self.list_table.setItem(row, col, filler)
            self.list_table.setSpan(row, 0, 1, 6)  # 0~5 합치기
            self.list_table.setRowHeight(row, 32)
            row += 1

            for h in group_items:
                self._fill_row(row, h, status_labels)
                row += 1

    def _fill_row(self, row: int, h: dict, status_labels: dict):
        """단일 행을 채운다."""
        # 등록일 (월-일만)
        return_date = h.get("return_date", "")
        date_item = QTableWidgetItem(return_date)
        date_item.setFlags(date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_table.setItem(row, 0, date_item)

        # 약품명
        name_item = QTableWidgetItem(h.get("drug_name", ""))
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.list_table.setItem(row, 1, name_item)

        # 로트번호
        lot_item = QTableWidgetItem(h.get("lot_number", ""))
        lot_item.setFlags(lot_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.list_table.setItem(row, 2, lot_item)

        # 수량
        qty_item = QTableWidgetItem(str(h.get("qty", "")))
        qty_item.setFlags(qty_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_table.setItem(row, 3, qty_item)

        # 도매상
        ws_item = QTableWidgetItem(h.get("wholesaler_name", ""))
        ws_item.setFlags(ws_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.list_table.setItem(row, 4, ws_item)

        # 입고일(원주문일)
        orig_date = QTableWidgetItem(h.get("original_order_date", ""))
        orig_date.setFlags(orig_date.flags() & ~Qt.ItemFlag.ItemIsEditable)
        orig_date.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_table.setItem(row, 5, orig_date)

        # 상태 콤보박스
        return_id = h.get("id", 0)
        current_status = h.get("status", "pending")

        status_combo = QComboBox()
        for key, label in status_labels.items():
            status_combo.addItem(label, key)
        # 현재 상태 선택
        idx = list(status_labels.keys()).index(current_status) if current_status in status_labels else 0
        status_combo.setCurrentIndex(idx)

        # 상태별 색상
        self._style_status_combo(status_combo, current_status)

        status_combo.currentIndexChanged.connect(
            lambda _, rid=return_id, combo=status_combo: self._on_status_change(rid, combo)
        )
        self.list_table.setCellWidget(row, 6, status_combo)

        # 삭제 버튼
        del_btn = QPushButton("삭제")
        del_btn.setStyleSheet(btn_small_danger())
        del_btn.clicked.connect(
            lambda _, rid=return_id: self._on_delete_return(rid)
        )
        self.list_table.setCellWidget(row, 7, del_btn)

        self.list_table.setRowHeight(row, 42)

    def _style_status_combo(self, combo: QComboBox, status: str):
        """상태에 따라 콤보박스 색상을 변경한다."""
        colors = {
            "pending": f"color: {_ORANGE}; font-weight: 600;",
            "sent": f"color: {_BLUE}; font-weight: 600;",
            "completed": f"color: {_GREEN}; font-weight: 600;",
        }
        style = colors.get(status, "")
        combo.setStyleSheet(
            f"QComboBox {{ {style} font-size: 12px; padding: 2px 6px; }}"
        )

    def _on_status_change(self, return_id: int, combo: QComboBox):
        """반품 상태 변경 시 DB 업데이트."""
        new_status = combo.currentData()
        if not new_status:
            return

        from core.return_engine import update_return_status
        update_return_status(return_id, new_status)

        # 콤보 색상 업데이트
        self._style_status_combo(combo, new_status)

    def _on_delete_return(self, return_id: int):
        reply = QMessageBox.question(
            self, "삭제 확인",
            "이 항목을 반품 리스트에서 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from core.return_engine import delete_return
        delete_return(return_id)
        self._load_return_list()


def _card(widget: QWidget) -> QFrame:
    card = QFrame()
    card.setStyleSheet(CARD_FRAME)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 20, 20, 20)
    lay.addWidget(widget)
    return card
