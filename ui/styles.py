"""PharmAuto 디자인 시스템 - 색상, 글로벌 QSS, 컴포넌트 스타일.

이 파일만 수정하면 전체 앱의 디자인이 바뀝니다.
다른 파일에서는 from ui.styles import ... 으로 사용합니다.
"""

# ━━━━━━━━━━━━━━━━━━━ 색상 팔레트 ━━━━━━━━━━━━━━━━━━━

BLUE = "#3182F6"
BLUE_DARK = "#1B64DA"
GREEN = "#30D158"
GREEN_DARK = "#28B84C"
RED = "#F45452"
RED_DARK = "#D43D3B"
ORANGE = "#F5A623"
ORANGE_DARK = "#E09500"

BG = "#F4F5F7"
CARD = "#FFFFFF"
BORDER = "#E5E8EB"

TEXT = "#191F28"
TEXT_SEC = "#8B95A1"
TEXT_DISABLED = "#CCCCCC"


# ━━━━━━━━━━━━━━━━━━━ 글로벌 QSS ━━━━━━━━━━━━━━━━━━━

GLOBAL_STYLE = f"""
    * {{
        font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
    }}
    QMainWindow {{
        background-color: {BG};
    }}

    /* ─── 탭 위젯 ─── */
    QTabWidget::pane {{
        border: none;
        background: {BG};
        margin-top: -1px;
    }}
    QTabBar {{
        background: {CARD};
        border-bottom: 1px solid {BORDER};
    }}
    QTabBar::tab {{
        padding: 14px 28px;
        margin: 0;
        background: transparent;
        border: none;
        border-bottom: 3px solid transparent;
        color: {TEXT_SEC};
        font-size: 14px;
        font-weight: 500;
    }}
    QTabBar::tab:selected {{
        color: {BLUE};
        font-weight: 700;
        border-bottom: 3px solid {BLUE};
    }}
    QTabBar::tab:hover:!selected {{
        color: {TEXT};
        background: #F8F9FA;
    }}

    /* ─── 카드 (QGroupBox) ─── */
    QGroupBox {{
        background: {CARD};
        border: none;
        border-radius: 16px;
        margin-top: 8px;
        padding: 24px 20px 16px 20px;
        font-size: 15px;
        font-weight: 700;
        color: {TEXT};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 20px;
        top: 8px;
        padding: 0 4px;
    }}

    /* ─── 입력 필드 ─── */
    QLineEdit, QComboBox, QSpinBox, QTimeEdit {{
        padding: 10px 14px;
        border: 1.5px solid {BORDER};
        border-radius: 12px;
        background: {CARD};
        font-size: 13px;
        color: {TEXT};
        selection-background-color: #D4E4FD;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {{
        border-color: {BLUE};
    }}
    QLineEdit::placeholder {{
        color: {TEXT_SEC};
    }}
    QComboBox::drop-down {{
        border: none;
        padding-right: 10px;
    }}
    QComboBox QAbstractItemView {{
        border: 1px solid {BORDER};
        border-radius: 8px;
        background: {CARD};
        selection-background-color: #EBF2FE;
        selection-color: {BLUE};
        padding: 4px;
    }}

    /* ─── 기본 버튼 ─── */
    QPushButton {{
        padding: 10px 20px;
        border: none;
        border-radius: 12px;
        background: #F2F3F5;
        color: {TEXT};
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: #E5E8EB;
    }}
    QPushButton:pressed {{
        background: #D1D5D9;
    }}

    /* ─── 테이블 ─── */
    QTableWidget {{
        border: none;
        border-radius: 12px;
        background: {CARD};
        gridline-color: #F2F3F5;
        selection-background-color: #EBF2FE;
        selection-color: {TEXT};
        font-size: 13px;
    }}
    QTableWidget::item {{
        padding: 10px 8px;
        border-bottom: 1px solid #F2F3F5;
    }}
    QHeaderView::section {{
        background: {CARD};
        padding: 12px 8px;
        border: none;
        border-bottom: 2px solid {BORDER};
        font-size: 12px;
        font-weight: 700;
        color: {TEXT_SEC};
        text-transform: uppercase;
    }}
    QHeaderView::section:first {{
        border-top-left-radius: 12px;
    }}
    QHeaderView::section:last {{
        border-top-right-radius: 12px;
    }}

    /* ─── 라벨 ─── */
    QLabel {{
        color: {TEXT};
        font-size: 13px;
    }}

    /* ─── 스크롤바 ─── */
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: #D1D5D9;
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {TEXT_SEC};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
    }}
    QScrollBar::handle:horizontal {{
        background: #D1D5D9;
        border-radius: 4px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
"""


# ━━━━━━━━━━━━━━━━━━━ 버튼 스타일 ━━━━━━━━━━━━━━━━━━━

def btn_primary(bg=BLUE, hover=BLUE_DARK):
    """파란색 주요 버튼."""
    return f"""
        QPushButton {{
            background-color: {bg}; color: white; padding: 10px 24px;
            border-radius: 12px; font-weight: 700; font-size: 13px; border: none;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:disabled {{ background-color: #B0C4DE; }}
    """


def btn_success(bg=GREEN, hover=GREEN_DARK):
    """초록색 성공/저장 버튼."""
    return f"""
        QPushButton {{
            background-color: {bg}; color: white; padding: 10px 28px;
            border-radius: 12px; font-weight: 700; border: none;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
    """


def btn_danger(bg=RED, hover=RED_DARK):
    """빨간색 삭제/위험 버튼."""
    return f"""
        QPushButton {{
            background-color: {bg}; color: white; padding: 10px 20px;
            border-radius: 12px; font-weight: 700; border: none;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
    """


def btn_warning(bg=ORANGE, hover=ORANGE_DARK):
    """주황색 경고/주의 버튼."""
    return f"""
        QPushButton {{
            background-color: {bg}; color: white; padding: 10px 20px;
            border-radius: 12px; font-weight: 700; border: none;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
    """


def btn_accent(bg="#FF6B35", hover="#E55A2B"):
    """강조색 버튼 (자동주문 등)."""
    return f"""
        QPushButton {{
            background-color: {bg}; color: white; padding: 10px 24px;
            border-radius: 12px; font-weight: 700; font-size: 13px; border: none;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:disabled {{ background-color: #CCCCCC; }}
    """


def btn_order():
    """큰 주문 버튼."""
    return f"""
        QPushButton {{
            background-color: {GREEN}; color: white; padding: 12px 36px;
            border-radius: 12px; font-size: 15px; font-weight: 700; border: none;
        }}
        QPushButton:hover {{ background-color: {GREEN_DARK}; }}
    """


def btn_outline():
    """테두리 버튼 (취소 등)."""
    return """
        QPushButton {
            padding: 10px 24px; border-radius: 10px;
            border: 1px solid #DDD; background: white;
            font-weight: 600; color: #333D4B;
        }
        QPushButton:hover { background: #F5F5F5; }
    """


def btn_small_danger():
    """작은 빨간 버튼 (행 내 해제 등)."""
    return f"""
        QPushButton {{
            background-color: {RED}; color: white; padding: 4px 12px;
            border-radius: 8px; font-weight: 600; font-size: 12px; border: none;
        }}
        QPushButton:hover {{ background-color: {RED_DARK}; }}
    """


def btn_small_primary():
    """작은 파란 버튼 (규격 조회 등)."""
    return f"""
        QPushButton {{
            padding: 6px 14px; border-radius: 8px;
            background: {BLUE}; color: white; border: none;
            font-size: 11px; font-weight: 600;
        }}
        QPushButton:hover {{ background: {BLUE_DARK}; }}
    """


# ━━━━━━━━━━━━━━━━━━━ 컴포넌트 스타일 ━━━━━━━━━━━━━━━━━━━

CARD_FRAME = f"QFrame {{ background: {CARD}; border-radius: 16px; }}"

SCROLL_AREA = "QScrollArea { background: transparent; border: none; }"

TITLE = f"font-size: 18px; font-weight: 700; color: {TEXT};"

SUBTITLE = f"color: {TEXT_SEC}; font-weight: 600; font-size: 12px;"

DESCRIPTION = f"color: {TEXT_SEC}; font-size: 12px;"

STATUS_LABEL = f"color: {TEXT_SEC}; font-size: 13px;"

PROGRESS_BAR = f"""
    QProgressBar {{ border: 1px solid #DDD; border-radius: 10px; background: #F5F5F5; }}
    QProgressBar::chunk {{ background: {BLUE}; border-radius: 10px; }}
"""

COMBO_MALGUN = "QComboBox { font-family: 'Malgun Gothic'; font-size: 13px; padding: 4px 8px; }"

COMBO_SMALL = "QComboBox { font-family: 'Malgun Gothic'; font-size: 12px; padding: 2px 6px; }"

SPIN_BOX = "QSpinBox { font-size: 14px; padding: 4px 8px; }"

SPIN_BOX_SMALL = "QSpinBox { font-size: 13px; padding: 2px 6px; }"

RADIO_BUTTON = "QRadioButton { font-size: 14px; padding: 4px 0; font-family: 'Malgun Gothic'; }"

CHECKBOX_MALGUN = """
    QCheckBox {
        font-size: 13px; color: #333D4B; padding: 8px 0;
        font-family: 'Malgun Gothic';
    }
"""

DIALOG_BG = f"QDialog {{ background: {BG}; }}"

INFO_LABEL_BLUE = f"color: {BLUE}; font-weight: 700; padding: 8px 0;"

INFO_LABEL_RED = f"color: {RED}; font-weight: 600; padding: 8px 0;"


# ━━━━━━━━━━━━━━━━━━━ 팔레트 설정 ━━━━━━━━━━━━━━━━━━━

def apply_palette(app):
    """QApplication에 토스 팔레트를 적용한다."""
    from PyQt6.QtGui import QColor, QPalette

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.Base, QColor(CARD))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(BLUE))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)
