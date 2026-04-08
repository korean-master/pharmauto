"""가격 비교 탭 - 도매상별 약품 가격 비교."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.styles import BLUE as _BLUE, TEXT_SEC as _TEXT_SEC, CARD_FRAME, TITLE, STATUS_LABEL, btn_primary


class PriceTab(QWidget):
    def __init__(self):
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # 검색 카드
        card1 = QFrame()
        card1.setStyleSheet("QFrame { background: #FFFFFF; border-radius: 16px; }")
        c1 = QVBoxLayout(card1)
        c1.setContentsMargins(24, 24, 24, 24)
        c1.setSpacing(12)

        title = QLabel("가격 비교")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #191F28;")
        c1.addWidget(title)

        search_row = QHBoxLayout()
        search_row.setSpacing(12)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("약품명 또는 보험코드를 입력하세요")
        self.search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_input)

        search_btn = QPushButton("검색")
        search_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_BLUE}; color: white; padding: 10px 24px;
                border-radius: 12px; font-weight: 700; border: none;
            }}
            QPushButton:hover {{ background-color: #1B64DA; }}
        """)
        search_btn.clicked.connect(self._on_search)
        search_row.addWidget(search_btn)

        c1.addLayout(search_row)
        layout.addWidget(card1)

        # 결과 테이블 카드
        card2 = QFrame()
        card2.setStyleSheet("QFrame { background: #FFFFFF; border-radius: 16px; }")
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(24, 24, 24, 24)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["약품명", "규격", "도매상", "가격", "비고"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        c2.addWidget(self.table)

        self.status_label = QLabel("약품명을 검색하면 도매상별 가격을 비교합니다")
        self.status_label.setStyleSheet(f"color: {_TEXT_SEC}; padding-top: 8px;")
        c2.addWidget(self.status_label)

        layout.addWidget(card2, 1)

    def _on_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        self.table.setRowCount(0)
        self.status_label.setText(
            f"'{query}' 검색 완료 - 도매상 가격 조회 기능은 도매상 연동 후 활성화됩니다"
        )
