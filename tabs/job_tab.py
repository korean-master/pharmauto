"""구인구직 탭."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.styles import TEXT_SEC as _TEXT_SEC, CARD_FRAME, TITLE, STATUS_LABEL


class JobTab(QWidget):
    def __init__(self):
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        card = QFrame()
        card.setStyleSheet("QFrame { background: #FFFFFF; border-radius: 16px; }")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(24, 24, 24, 24)
        c_lay.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("구인구직")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #191F28;")
        top.addWidget(title)
        top.addStretch()
        refresh_btn = QPushButton("새로고침")
        refresh_btn.clicked.connect(self._on_refresh)
        top.addWidget(refresh_btn)
        c_lay.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["구분", "지역", "제목", "날짜", "연락처"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        c_lay.addWidget(self.table)

        self.status_label = QLabel("구인구직 기능은 추후 연동 예정입니다")
        self.status_label.setStyleSheet(f"color: {_TEXT_SEC};")
        c_lay.addWidget(self.status_label)

        layout.addWidget(card, 1)

    def _on_refresh(self):
        self.status_label.setText("데이터 소스 연동 후 활성화됩니다")
