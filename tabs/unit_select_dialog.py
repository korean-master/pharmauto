"""약품 규격 선택 팝업 다이얼로그."""

import math

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QPushButton,
    QVBoxLayout,
)

from ui.styles import (
    BLUE as _BLUE, TEXT_SEC, TEXT,
    DIALOG_BG, RADIO_BUTTON, CHECKBOX_MALGUN,
    btn_primary, btn_outline,
)


class UnitSelectDialog(QDialog):
    """규격 선택 팝업.

    Args:
        drug_name: 약품명
        insurance_code: 보험코드
        today_qty: 오늘 사용량 (정 단위)
        unit_options: 가능한 규격 목록 (예: [30, 300, 500])
        current_preferred: 현재 선호 규격 (없으면 None)
    """

    def __init__(self, drug_name: str, insurance_code: str,
                 today_qty: int, unit_options: list[int],
                 current_preferred: int | None = None,
                 unit: str = "정",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("규격 선택")
        self.setMinimumWidth(420)
        self.setStyleSheet(DIALOG_BG)

        self.selected_unit = current_preferred
        self.save_preference = False

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # 약품 정보
        title = QLabel(drug_name)
        title.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {TEXT};")
        title.setWordWrap(True)
        layout.addWidget(title)

        self._unit = unit
        info = QLabel(f"보험코드: {insurance_code}    오늘 사용량: {today_qty}{unit}")
        info.setStyleSheet(f"font-size: 13px; color: {TEXT_SEC};")
        layout.addWidget(info)

        # 구분선
        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #E5E8EB;")
        layout.addWidget(line)

        # 규격 옵션들
        options_label = QLabel("주문 규격 선택")
        options_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {TEXT};")
        layout.addWidget(options_label)

        self._radio_group = QButtonGroup(self)
        sorted_options = sorted(unit_options)

        for i, unit in enumerate(sorted_options):
            box_qty = math.ceil(today_qty / unit) if unit > 0 else 0
            total = box_qty * unit
            surplus = total - today_qty

            if surplus == 0:
                note = "딱 맞음"
            else:
                note = f"{surplus}{self._unit} 잉여"

            text = f"{unit}{self._unit} x {box_qty}박스 ({note})"

            radio = QRadioButton(text)
            radio.setStyleSheet(RADIO_BUTTON)
            radio.unit_value = unit
            self._radio_group.addButton(radio, i)

            if current_preferred is not None and unit == current_preferred:
                radio.setChecked(True)
            elif current_preferred is None and i == 0:
                radio.setChecked(True)

            layout.addWidget(radio)

        # 항상 이 규격으로 주문 체크박스
        self._always_cb = QCheckBox("이 약품은 항상 이 규격으로 주문")
        self._always_cb.setStyleSheet(CHECKBOX_MALGUN)
        if current_preferred is not None:
            self._always_cb.setChecked(True)
        layout.addWidget(self._always_cb)

        # 버튼 행
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()

        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet(btn_outline())
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton("확인")
        ok_btn.setStyleSheet(btn_primary())
        ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)

    def _on_ok(self):
        checked = self._radio_group.checkedButton()
        if checked:
            self.selected_unit = checked.unit_value
        self.save_preference = self._always_cb.isChecked()
        self.accept()
