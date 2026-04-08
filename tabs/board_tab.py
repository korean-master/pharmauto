"""약국 직거래 게시판 탭."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.styles import BLUE as _BLUE, GREEN as _GREEN, TEXT_SEC as _TEXT_SEC, CARD_FRAME, TITLE, SUBTITLE, STATUS_LABEL, btn_primary, btn_success

# 데모 데이터
DEMO_POSTS = [
    {"category": "판매", "title": "레보플록사신정 500mg 2박스 판매합니다", "price": "15,000", "region": "서울 강남", "date": "2026-04-04", "author": "강남약국"},
    {"category": "구매", "title": "아목시실린캡슐 500mg 급구합니다", "price": "협의", "region": "경기 수원", "date": "2026-04-04", "author": "수원중앙약국"},
    {"category": "판매", "title": "유통기한 임박 소화제 묶음 (10박스)", "price": "50,000", "region": "부산 해운대", "date": "2026-04-03", "author": "해운대약국"},
    {"category": "판매", "title": "세팔렉신캡슐 250mg 3박스", "price": "22,000", "region": "대전 서구", "date": "2026-04-03", "author": "대전온누리약국"},
    {"category": "구매", "title": "타이레놀정 500mg 5박스 구합니다", "price": "협의", "region": "인천 남동구", "date": "2026-04-02", "author": "인천미래약국"},
]


class BoardTab(QWidget):
    def __init__(self):
        super().__init__()
        self._init_ui()
        self._load_demo()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # --- 검색/필터 카드 ---
        filter_card = QFrame()
        filter_card.setStyleSheet("QFrame { background: #FFFFFF; border-radius: 16px; }")
        f_lay = QVBoxLayout(filter_card)
        f_lay.setContentsMargins(24, 24, 24, 24)
        f_lay.setSpacing(12)

        title = QLabel("약국 직거래 게시판")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #191F28;")
        f_lay.addWidget(title)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(12)

        cat_label = QLabel("구분")
        cat_label.setStyleSheet(f"color: {_TEXT_SEC}; font-weight: 600; font-size: 12px;")
        filter_row.addWidget(cat_label)
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(["전체", "판매", "구매"])
        self.cat_combo.setMinimumWidth(100)
        filter_row.addWidget(self.cat_combo)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("약품명, 지역으로 검색")
        self.search_input.returnPressed.connect(self._on_search)
        filter_row.addWidget(self.search_input)

        search_btn = QPushButton("검색")
        search_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_BLUE}; color: white; padding: 10px 20px;
                border-radius: 12px; font-weight: 700; border: none;
            }}
            QPushButton:hover {{ background-color: #1B64DA; }}
        """)
        search_btn.clicked.connect(self._on_search)
        filter_row.addWidget(search_btn)

        filter_row.addWidget(QLabel(""))  # spacer

        write_btn = QPushButton("글쓰기")
        write_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_GREEN}; color: white; padding: 10px 20px;
                border-radius: 12px; font-weight: 700; border: none;
            }}
            QPushButton:hover {{ background-color: #28B84C; }}
        """)
        write_btn.clicked.connect(self._on_write)
        filter_row.addWidget(write_btn)

        f_lay.addLayout(filter_row)
        layout.addWidget(filter_card)

        # --- 게시글 목록 카드 ---
        list_card = QFrame()
        list_card.setStyleSheet("QFrame { background: #FFFFFF; border-radius: 16px; }")
        l_lay = QVBoxLayout(list_card)
        l_lay.setContentsMargins(24, 24, 24, 24)
        l_lay.setSpacing(8)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["구분", "제목", "가격", "지역", "날짜", "작성자"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 120)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        l_lay.addWidget(self.table)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {_TEXT_SEC};")
        l_lay.addWidget(self.status_label)

        layout.addWidget(list_card, 1)

    def _load_demo(self):
        self._display_posts(DEMO_POSTS)
        self.status_label.setText(f"{len(DEMO_POSTS)}개 게시글")

    def _display_posts(self, posts: list):
        self.table.setRowCount(len(posts))
        for row, p in enumerate(posts):
            # 구분 (판매=파란 배지, 구매=주황 배지)
            cat_item = QTableWidgetItem(p["category"])
            cat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if p["category"] == "판매":
                cat_item.setForeground(Qt.GlobalColor.white)
                cat_item.setBackground(Qt.GlobalColor.blue)
            else:
                cat_item.setForeground(Qt.GlobalColor.white)
                cat_item.setBackground(Qt.GlobalColor.darkYellow)
            self.table.setItem(row, 0, cat_item)

            for col, key in enumerate(["title", "price", "region", "date", "author"], 1):
                item = QTableWidgetItem(p.get(key, ""))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if key == "price":
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, col, item)

            self.table.setRowHeight(row, 48)

    def _on_search(self):
        query = self.search_input.text().strip().lower()
        cat_filter = self.cat_combo.currentText()

        filtered = []
        for p in DEMO_POSTS:
            if cat_filter != "전체" and p["category"] != cat_filter:
                continue
            if query and query not in p["title"].lower() and query not in p["region"].lower():
                continue
            filtered.append(p)

        self._display_posts(filtered)
        self.status_label.setText(f"검색 결과: {len(filtered)}개 게시글")

    def _on_write(self):
        QMessageBox.information(self, "알림", "글쓰기 기능은 추후 업데이트 예정입니다.")
