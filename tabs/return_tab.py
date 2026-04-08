"""반품 탭 - 반품 신청 및 이력 조회."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.styles import (
    BLUE as _BLUE, ORANGE as _ORANGE, TEXT_SEC as _TEXT_SEC,
    CARD_FRAME, TITLE, SUBTITLE, INFO_LABEL_BLUE, INFO_LABEL_RED,
    btn_primary, btn_warning,
)


class ReturnTab(QWidget):
    def __init__(self):
        super().__init__()
        self._found_order = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # --- 반품 신청 카드 ---
        card1 = QFrame()
        card1.setStyleSheet(CARD_FRAME)
        c1_lay = QVBoxLayout(card1)
        c1_lay.setContentsMargins(24, 24, 24, 24)
        c1_lay.setSpacing(16)

        title = QLabel("반품 신청")
        title.setStyleSheet(TITLE)
        c1_lay.addWidget(title)

        form = QHBoxLayout()
        form.setSpacing(12)

        drug_label = QLabel("약품명")
        drug_label.setStyleSheet(SUBTITLE)
        form.addWidget(drug_label)
        self.drug_input = QLineEdit()
        self.drug_input.setPlaceholderText("약품명 입력")
        form.addWidget(self.drug_input)

        lot_label = QLabel("로트번호")
        lot_label.setStyleSheet(SUBTITLE)
        form.addWidget(lot_label)
        self.lot_input = QLineEdit()
        self.lot_input.setPlaceholderText("로트번호 입력")
        form.addWidget(self.lot_input)

        self.search_btn = QPushButton("이력 조회")
        self.search_btn.setStyleSheet(btn_primary())
        self.search_btn.clicked.connect(self._on_search)
        form.addWidget(self.search_btn)

        self.return_btn = QPushButton("반품 신청")
        self.return_btn.setStyleSheet(btn_warning())
        self.return_btn.clicked.connect(self._on_return)
        form.addWidget(self.return_btn)

        c1_lay.addLayout(form)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet("padding: 8px 0;")
        c1_lay.addWidget(self.info_label)

        layout.addWidget(card1)

        # --- 반품 이력 카드 ---
        card2 = QFrame()
        card2.setStyleSheet(CARD_FRAME)
        c2_lay = QVBoxLayout(card2)
        c2_lay.setContentsMargins(24, 24, 24, 24)
        c2_lay.setSpacing(12)

        h_top = QHBoxLayout()
        h_title = QLabel("반품 이력")
        h_title.setStyleSheet(TITLE)
        h_top.addWidget(h_title)
        h_top.addStretch()
        refresh_btn = QPushButton("새로고침")
        refresh_btn.clicked.connect(self._load_history)
        h_top.addWidget(refresh_btn)
        c2_lay.addLayout(h_top)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels(
            ["날짜", "약품명", "로트번호", "도매상", "원주문일", "상태"]
        )
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setShowGrid(False)
        self.history_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        c2_lay.addWidget(self.history_table)

        layout.addWidget(card2, 1)

    def _on_search(self):
        drug_name = self.drug_input.text().strip()
        if not drug_name:
            QMessageBox.warning(self, "알림", "약품명을 입력하세요.")
            return

        from core.return_engine import find_order_for_return

        lot = self.lot_input.text().strip()
        result = find_order_for_return(drug_name, lot)

        if result:
            self._found_order = result
            self.info_label.setText(
                f"도매상: {result['wholesaler_name']}  |  "
                f"주문일: {result['order_date']}  |  "
                f"수량: {result['qty']}"
            )
            self.info_label.setStyleSheet(INFO_LABEL_BLUE)
        else:
            self._found_order = None
            self.info_label.setText("주문 이력을 찾을 수 없습니다.")
            self.info_label.setStyleSheet(INFO_LABEL_RED)

    def _on_return(self):
        drug_name = self.drug_input.text().strip()
        lot = self.lot_input.text().strip()

        if not drug_name or not lot:
            QMessageBox.warning(self, "알림", "약품명과 로트번호를 모두 입력하세요.")
            return

        from core.return_engine import create_return

        if self._found_order:
            create_return(
                drug_name, lot,
                self._found_order["wholesaler_id"],
                self._found_order["wholesaler_name"],
                self._found_order.get("order_date", ""),
            )
        else:
            create_return(drug_name, lot, "", "", "")

        # 반품 시 재고 차감
        if self._found_order:
            try:
                from core.inventory import update_stock_after_return
                code = self._found_order.get("insurance_code", "")
                qty = self._found_order.get("qty", 0)
                if code and qty:
                    update_stock_after_return(code, qty)
            except Exception:
                pass

        QMessageBox.information(self, "완료", "반품 신청이 등록되었습니다.")
        self.drug_input.clear()
        self.lot_input.clear()
        self.info_label.clear()
        self._found_order = None
        self._load_history()

    def _load_history(self):
        from core.return_engine import get_return_history

        history = get_return_history()
        self.history_table.setRowCount(len(history))
        for row, h in enumerate(history):
            self.history_table.setItem(row, 0, QTableWidgetItem(h.get("return_date", "")))
            self.history_table.setItem(row, 1, QTableWidgetItem(h.get("drug_name", "")))
            self.history_table.setItem(row, 2, QTableWidgetItem(h.get("lot_number", "")))
            self.history_table.setItem(row, 3, QTableWidgetItem(h.get("wholesaler_name", "")))
            self.history_table.setItem(row, 4, QTableWidgetItem(h.get("original_order_date", "")))
            self.history_table.setItem(row, 5, QTableWidgetItem(h.get("status", "")))
            self.history_table.setRowHeight(row, 44)
