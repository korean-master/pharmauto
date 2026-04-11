"""PharmAuto 디자인 시스템 - 색상, 글로벌 QSS, 컴포넌트 스타일.

이 파일만 수정하면 전체 앱의 디자인이 바뀝니다.
다른 파일에서는 from ui.styles import ... 으로 사용합니다.
"""

import os as _os

# 아이콘 경로 (QSS url()에 사용 — 슬래시 통일)
_ICON_DIR = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "icons"
).replace("\\", "/")

# ━━━━━━━━━━━━━━━━━━━ 색상 팔레트 ━━━━━━━━━━━━━━━━━━━

BLUE = "#4B6BFB"
BLUE_DARK = "#3A56D4"
GREEN = "#22C55E"
GREEN_DARK = "#16A34A"
RED = "#EF4444"
RED_DARK = "#DC2626"
ORANGE = "#F59E0B"
ORANGE_DARK = "#D97706"

BG = "#F5F6F8"
CARD = "#FFFFFF"
BORDER = "#DFE1E6"

TEXT = "#1A1A2E"
TEXT_SEC = "#6B7280"
TEXT_DISABLED = "#C4C4CC"

# 내부용
_INDICATOR_BG = "#FFFFFF"
_INDICATOR_BORDER = "#C0C4CC"
_INDICATOR_CHECKED = BLUE


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
        border: none;
        border-bottom: 1px solid {BORDER};
    }}
    QTabBar::tab {{
        padding: 14px 32px;
        margin: 0;
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        color: {TEXT_SEC};
        font-size: 14px;
        font-weight: 500;
    }}
    QTabBar::tab:selected {{
        color: {BLUE};
        font-weight: 700;
        border-bottom: 2px solid {BLUE};
    }}
    QTabBar::tab:hover:!selected {{
        color: {TEXT};
        background: #EDEEF2;
    }}

    /* ─── 카드 (QGroupBox) ─── */
    QGroupBox {{
        background: {CARD};
        border: none;
        border-radius: 12px;
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
        padding: 8px 12px;
        border: 1px solid {BORDER};
        border-radius: 6px;
        background: {CARD};
        font-size: 13px;
        color: {TEXT};
        selection-background-color: #DDE4FF;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {{
        border-color: {BLUE};
    }}
    QLineEdit::placeholder {{
        color: {TEXT_SEC};
    }}
    QComboBox::drop-down {{
        border: none;
        padding-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        border: 1px solid {BORDER};
        border-radius: 6px;
        background: {CARD};
        selection-background-color: #EEF1FF;
        selection-color: {BLUE};
        padding: 4px;
        outline: none;
    }}

    /* ─── 기본 버튼 ─── */
    QPushButton {{
        padding: 8px 20px;
        border: none;
        border-radius: 6px;
        background: #EBEBEF;
        color: {TEXT};
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: #DFDFE5;
    }}
    QPushButton:pressed {{
        background: #D2D2DA;
    }}

    /* ─── 테이블 ─── */
    QTableWidget {{
        border: none;
        border-radius: 10px;
        background: {CARD};
        gridline-color: #F0F0F4;
        selection-background-color: #EEF1FF;
        selection-color: {TEXT};
        font-size: 13px;
        outline: none;
    }}
    QTableWidget::item {{
        padding: 10px 8px;
        border-bottom: 1px solid #F0F0F4;
    }}
    QHeaderView::section {{
        background: #FAFAFB;
        padding: 11px 8px;
        border: none;
        border-bottom: 1px solid {BORDER};
        font-size: 12px;
        font-weight: 700;
        color: {TEXT_SEC};
    }}

    /* ─── 라벨 ─── */
    QLabel {{
        color: {TEXT};
        font-size: 13px;
        background: transparent;
    }}

    /* ─── 체크박스 ─── */
    QCheckBox {{
        background: transparent;
        spacing: 8px;
        font-size: 13px;
        color: {TEXT};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 2px solid {_INDICATOR_BORDER};
        border-radius: 3px;
        background: {_INDICATOR_BG};
    }}
    QCheckBox::indicator:hover {{
        border-color: {BLUE};
    }}
    QCheckBox::indicator:checked {{
        border: none;
        image: url({_ICON_DIR}/check.svg);
    }}
    QCheckBox::indicator:checked:hover {{
        image: url({_ICON_DIR}/check_hover.svg);
    }}
    QCheckBox::indicator:checked:disabled {{
        image: url({_ICON_DIR}/check_disabled.svg);
    }}
    QCheckBox::indicator:disabled {{
        border-color: {TEXT_DISABLED};
        background: #F0F0F2;
    }}

    /* ─── 라디오 버튼 ─── */
    QRadioButton {{
        background: transparent;
        spacing: 8px;
        font-size: 13px;
        color: {TEXT};
    }}
    QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        border: 2px solid {_INDICATOR_BORDER};
        border-radius: 9px;
        background: {_INDICATOR_BG};
    }}
    QRadioButton::indicator:hover {{
        border-color: {BLUE};
    }}
    QRadioButton::indicator:checked {{
        border: none;
        image: url({_ICON_DIR}/radio.svg);
    }}
    QRadioButton::indicator:checked:hover {{
        image: url({_ICON_DIR}/radio_hover.svg);
    }}
    QRadioButton::indicator:checked:disabled {{
        image: url({_ICON_DIR}/radio_disabled.svg);
    }}
    QRadioButton::indicator:disabled {{
        border-color: {TEXT_DISABLED};
        background: #F0F0F2;
    }}

    /* ─── 프레임 ─── */
    QFrame {{
        border: none;
        background: transparent;
    }}

    /* ─── 스크롤바 ─── */
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: #CDCDD4;
        border-radius: 3px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #A8A8B2;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 6px;
    }}
    QScrollBar::handle:horizontal {{
        background: #CDCDD4;
        border-radius: 3px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* ─── 다이얼로그 ─── */
    QDialog {{
        background: {CARD};
    }}
    QMessageBox {{
        background: {CARD};
    }}
    QMessageBox QLabel {{
        font-size: 13px;
        color: {TEXT};
        padding: 4px 0;
    }}
    QMessageBox QPushButton {{
        min-width: 90px;
        padding: 9px 28px;
        background: {BLUE};
        color: white;
        border: none;
        border-radius: 6px;
        font-weight: 600;
    }}
    QMessageBox QPushButton:hover {{
        background: {BLUE_DARK};
    }}

    /* ─── 툴팁 ─── */
    QToolTip {{
        background: {TEXT};
        color: white;
        border: none;
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 12px;
    }}
"""


# ━━━━━━━━━━━━━━━━━━━ 버튼 스타일 ━━━━━━━━━━━━━━━━━━━

def btn_primary(bg=BLUE, hover=BLUE_DARK):
    """Primary 버튼 — 채움."""
    return f"""
        QPushButton {{
            background-color: {bg}; color: white; padding: 10px 28px;
            border-radius: 6px; font-weight: 700; font-size: 13px;
            border: none;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:disabled {{ background-color: #B0BAD8; color: #E8E8F0; }}
    """


def btn_success(bg=GREEN, hover=GREEN_DARK):
    """초록색 성공/저장 버튼."""
    return f"""
        QPushButton {{
            background-color: {bg}; color: white; padding: 10px 28px;
            border-radius: 6px; font-weight: 700; border: none;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
    """


def btn_danger(bg=RED, hover=RED_DARK):
    """빨간색 삭제/위험 버튼."""
    return f"""
        QPushButton {{
            background-color: {bg}; color: white; padding: 10px 22px;
            border-radius: 6px; font-weight: 700; border: none;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
    """


def btn_warning(bg=ORANGE, hover=ORANGE_DARK):
    """주황색 경고/주의 버튼."""
    return f"""
        QPushButton {{
            background-color: {bg}; color: white; padding: 10px 22px;
            border-radius: 6px; font-weight: 700; border: none;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
    """


def btn_accent(bg="#4B6BFB", hover="#3A56D4"):
    """강조색 버튼."""
    return f"""
        QPushButton {{
            background-color: {bg}; color: white; padding: 10px 28px;
            border-radius: 6px; font-weight: 700; font-size: 13px;
            border: none;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:disabled {{ background-color: #C4C4CC; }}
    """


def btn_order():
    """큰 주문 버튼."""
    return f"""
        QPushButton {{
            background-color: {BLUE}; color: white; padding: 14px 40px;
            border-radius: 8px; font-size: 15px; font-weight: 700;
            border: none;
        }}
        QPushButton:hover {{ background-color: {BLUE_DARK}; }}
    """


def btn_outline():
    """Secondary 버튼 — 테두리만, 배경 투명."""
    return f"""
        QPushButton {{
            padding: 10px 24px; border-radius: 6px;
            border: 1px solid {BORDER}; background: transparent;
            font-weight: 600; color: {TEXT};
        }}
        QPushButton:hover {{ background: #F0F0F4; border-color: #CDCDD4; }}
    """


def btn_small_danger():
    """작은 빨간 버튼 (행 내 해제 등)."""
    return f"""
        QPushButton {{
            background-color: {RED}; color: white; padding: 4px 14px;
            border-radius: 4px; font-weight: 600; font-size: 12px;
            border: none;
        }}
        QPushButton:hover {{ background-color: {RED_DARK}; }}
    """


def btn_small_primary():
    """작은 파란 버튼 (규격 조회 등)."""
    return f"""
        QPushButton {{
            padding: 6px 16px; border-radius: 4px;
            background: {BLUE}; color: white; border: none;
            font-size: 11px; font-weight: 600;
        }}
        QPushButton:hover {{ background: {BLUE_DARK}; }}
    """


# ━━━━━━━━━━━━━━━━━━━ 컴포넌트 스타일 ━━━━━━━━━━━━━━━━━━━

CARD_FRAME = f"""
    QFrame {{
        background: {CARD};
        border: none;
        border-radius: 12px;
    }}
"""

SCROLL_AREA = "QScrollArea { background: transparent; border: none; }"

TITLE = f"font-size: 18px; font-weight: 700; color: {TEXT}; background: transparent;"

SUBTITLE = f"color: {TEXT_SEC}; font-weight: 600; font-size: 12px; background: transparent;"

DESCRIPTION = f"color: {TEXT_SEC}; font-size: 12px; background: transparent;"

STATUS_LABEL = f"color: {TEXT_SEC}; font-size: 13px; background: transparent;"

PROGRESS_BAR = f"""
    QProgressBar {{
        border: none; border-radius: 5px;
        background: #EBEBEF; text-align: center;
    }}
    QProgressBar::chunk {{ background: {BLUE}; border-radius: 5px; }}
"""

COMBO_MALGUN = f"""
    QComboBox {{
        font-family: 'Malgun Gothic'; font-size: 13px;
        padding: 6px 10px; border-radius: 6px;
        border: 1px solid {BORDER}; background: {CARD};
    }}
"""

COMBO_SMALL = f"""
    QComboBox {{
        font-family: 'Malgun Gothic'; font-size: 12px;
        padding: 4px 8px; border-radius: 5px;
        border: 1px solid {BORDER}; background: {CARD};
    }}
"""

SPIN_BOX = f"""
    QSpinBox {{
        font-size: 14px; padding: 6px 10px;
        border-radius: 6px; border: 1px solid {BORDER};
        background: {CARD};
    }}
"""

SPIN_BOX_SMALL = f"""
    QSpinBox {{
        font-size: 13px; padding: 4px 8px;
        border-radius: 5px; border: 1px solid {BORDER};
        background: {CARD};
    }}
"""

RADIO_BUTTON = f"""
    QRadioButton {{
        font-size: 14px; padding: 4px 0;
        font-family: 'Malgun Gothic'; color: {TEXT};
        background: transparent;
    }}
"""

CHECKBOX_MALGUN = f"""
    QCheckBox {{
        font-size: 13px; color: {TEXT}; padding: 8px 0;
        font-family: 'Malgun Gothic';
        background: transparent;
    }}
"""

DIALOG_BG = f"QDialog {{ background: {CARD}; }}"

INFO_LABEL_BLUE = f"color: {BLUE}; font-weight: 700; padding: 8px 0; background: transparent;"

INFO_LABEL_RED = f"color: {RED}; font-weight: 600; padding: 8px 0; background: transparent;"


# ━━━━━━━━━━━━━━━━━━━ 팔레트 설정 ━━━━━━━━━━━━━━━━━━━

def apply_palette(app):
    """QApplication에 팔레트를 적용한다."""
    from PyQt6.QtGui import QColor, QPalette

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.Base, QColor(CARD))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(BLUE))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#EBEBEF"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Mid, QColor(BORDER))
    app.setPalette(palette)
