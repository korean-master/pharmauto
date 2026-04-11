"""활성화 코드 입력 다이얼로그."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class ActivationDialog(QDialog):
    """활성화 코드 입력 화면 — 설치 마법사 전에 뜸."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PharmAuto 활성화")
        self.setMinimumSize(460, 380)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setStyleSheet("QDialog { background: white; }")
        self._activated = False
        self._init_ui()
        self.adjustSize()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.setContentsMargins(44, 40, 44, 36)

        title = QLabel("PharmAuto")
        title.setStyleSheet(
            "font-size: 24px; font-weight: 700; color: #4B6BFB; "
            "font-family: 'Malgun Gothic';"
        )
        title.setMinimumHeight(36)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("약국 자동화 프로그램")
        subtitle.setStyleSheet(
            "font-size: 13px; color: #6B7280; font-family: 'Malgun Gothic';"
        )
        subtitle.setMinimumHeight(22)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(12)

        # 활성화 코드 입력
        code_label = QLabel("활성화 코드를 입력하세요")
        code_label.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #1A1A2E; "
            "font-family: 'Malgun Gothic';"
        )
        code_label.setMinimumHeight(22)
        layout.addWidget(code_label)

        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("PHARMA-XXXX-XXXX")
        self._code_input.setMinimumHeight(44)
        self._code_input.setStyleSheet(
            "QLineEdit { font-size: 16px; font-family: 'Consolas'; "
            "padding: 10px; border: 2px solid #DFE1E6; border-radius: 8px; "
            "letter-spacing: 2px; min-height: 24px; }"
            "QLineEdit:focus { border-color: #4B6BFB; }"
        )
        self._code_input.setMaxLength(16)
        self._code_input.textChanged.connect(self._on_text_changed)
        self._code_input.returnPressed.connect(self._on_activate)
        layout.addWidget(self._code_input)

        # 상태 메시지
        self._status = QLabel("")
        self._status.setStyleSheet(
            "font-size: 12px; font-family: 'Malgun Gothic';"
        )
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        layout.addStretch()

        # 버튼
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._activate_btn = QPushButton("활성화")
        self._activate_btn.setMinimumHeight(42)
        self._activate_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 10px 32px; min-height: 22px; "
            "background: #4B6BFB; color: white; border: none; "
            "border-radius: 8px; font-weight: 600; font-family: 'Malgun Gothic'; }"
            "QPushButton:hover { background: #3A56D4; }"
            "QPushButton:disabled { background: #CCC; }"
        )
        self._activate_btn.setEnabled(False)
        self._activate_btn.clicked.connect(self._on_activate)
        btn_row.addWidget(self._activate_btn)

        layout.addLayout(btn_row)

    def _on_text_changed(self, text: str):
        # 자동 대문자 + 하이픈 포맷팅
        clean = text.upper().replace("-", "").replace(" ", "")
        if clean.startswith("PHARMA"):
            clean = clean[6:]

        if len(clean) >= 8:
            clean = clean[:8]

        if clean:
            formatted = f"PHARMA-{clean[:4]}"
            if len(clean) > 4:
                formatted += f"-{clean[4:8]}"
            self._code_input.blockSignals(True)
            self._code_input.setText(formatted)
            self._code_input.setCursorPosition(len(formatted))
            self._code_input.blockSignals(False)

        self._activate_btn.setEnabled(len(clean) == 8)
        self._status.setText("")

    def _on_activate(self):
        code = self._code_input.text().strip()
        if not code:
            return

        from core.auth import activate

        result = activate(code)
        if result["success"]:
            self._status.setText("활성화 성공!")
            self._status.setStyleSheet(
                "font-size: 13px; color: #22C55E; font-weight: 700; "
                "font-family: 'Malgun Gothic';"
            )
            self._activated = True

            from PyQt6.QtCore import QTimer
            QTimer.singleShot(800, self.accept)
        else:
            self._status.setText(result["message"])
            self._status.setStyleSheet(
                "font-size: 12px; color: #EF4444; font-family: 'Malgun Gothic';"
            )

    @property
    def activated(self) -> bool:
        return self._activated
