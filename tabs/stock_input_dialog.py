"""현재 재고 입력 팝업 - 규격 × 수량으로 입력."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ui.styles import (
    BLUE, TEXT, TEXT_SEC,
    DIALOG_BG, COMBO_MALGUN,
    btn_primary, btn_outline,
)


class StockInputDialog(QDialog):
    """현재 재고를 규격 × 수량으로 입력하는 팝업.

    결과: self.result_stock (정 수량) or None
    """

    def __init__(self, drug_name: str, insurance_code: str,
                 current_stock: int = 0,
                 unit_options: list[int] | None = None,
                 preferred_unit: int = 0,
                 unit: str = "정",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("현재 재고 입력")
        self.setMinimumWidth(380)
        self.setStyleSheet(DIALOG_BG)

        self.result_stock = None
        self._unit = unit

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        # 약품명
        title = QLabel(drug_name)
        title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {TEXT};")
        title.setWordWrap(True)
        layout.addWidget(title)

        sub = QLabel(f"보험코드: {insurance_code}")
        sub.setStyleSheet(f"font-size: 12px; color: {TEXT_SEC};")
        layout.addWidget(sub)

        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #E5E8EB;")
        layout.addWidget(line)

        # 안내 문구
        desc = QLabel(
            "수동 입력 시 입력 시점을 기준으로 이후 주문/처방 수량이\n"
            "자동 반영됩니다. 입력하지 않으면 재고 0에서 시작합니다."
        )
        desc.setStyleSheet(f"font-size: 11px; color: {TEXT_SEC}; line-height: 1.4;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 규격 × 수량 입력
        calc_label = QLabel("규격 × 수량으로 입력")
        calc_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {TEXT};")
        layout.addWidget(calc_label)

        calc_row = QHBoxLayout()
        calc_row.setSpacing(8)

        self._unit_spin = QSpinBox()
        self._unit_spin.setRange(1, 99999)
        self._unit_spin.setValue(preferred_unit if preferred_unit > 0 else 1)
        self._unit_spin.setSuffix(f" {self._unit}")
        self._unit_spin.setMinimumWidth(110)
        self._unit_spin.setMinimumHeight(34)
        calc_row.addWidget(self._unit_spin)

        x_label = QLabel("×")
        x_label.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {TEXT};")
        calc_row.addWidget(x_label)

        self._qty_spin = QSpinBox()
        self._qty_spin.setRange(0, 9999)
        self._qty_spin.setValue(0)
        self._qty_spin.setMinimumWidth(80)
        self._qty_spin.setMinimumHeight(34)
        calc_row.addWidget(self._qty_spin)

        eq_label = QLabel("=")
        eq_label.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {TEXT};")
        calc_row.addWidget(eq_label)

        self._total_label = QLabel(f"0{self._unit}")
        self._total_label.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {BLUE};"
        )
        self._total_label.setMinimumWidth(80)
        calc_row.addWidget(self._total_label)

        calc_row.addStretch()
        layout.addLayout(calc_row)

        # 계산 자동 업데이트
        self._unit_spin.valueChanged.connect(self._update_total)
        self._qty_spin.valueChanged.connect(self._update_total)

        # 또는 직접 입력
        line2 = QLabel()
        line2.setFixedHeight(1)
        line2.setStyleSheet("background: #E5E8EB;")
        layout.addWidget(line2)

        direct_label = QLabel("또는 직접 입력")
        direct_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {TEXT};")
        layout.addWidget(direct_label)

        direct_row = QHBoxLayout()
        direct_row.setSpacing(8)
        self._direct_spin = QSpinBox()
        self._direct_spin.setRange(0, 99999)
        self._direct_spin.setValue(current_stock)
        self._direct_spin.setSuffix(f" {self._unit}")
        self._direct_spin.setMinimumWidth(140)
        self._direct_spin.setMinimumHeight(34)
        direct_row.addWidget(self._direct_spin)
        direct_row.addStretch()
        layout.addLayout(direct_row)

        # 규격×수량 변경 시 직접입력도 동기화
        self._syncing = False
        self._unit_spin.valueChanged.connect(self._sync_to_direct)
        self._qty_spin.valueChanged.connect(self._sync_to_direct)
        self._direct_spin.valueChanged.connect(self._sync_from_direct)

        # 현재 재고를 규격×수량으로 역계산
        pack = self._unit_spin.value()
        if current_stock > 0 and pack > 0:
            boxes = current_stock // pack
            remainder = current_stock % pack
            if remainder == 0 and boxes > 0:
                self._qty_spin.setValue(boxes)

        # 버튼
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

    def _calc_total(self) -> int:
        return self._unit_spin.value() * self._qty_spin.value()

    def _update_total(self):
        total = self._calc_total()
        self._total_label.setText(f"{total}{self._unit}")

    def _sync_to_direct(self):
        if self._syncing:
            return
        self._syncing = True
        self._direct_spin.setValue(self._calc_total())
        self._syncing = False

    def _sync_from_direct(self):
        if self._syncing:
            return
        # 직접입력 변경 시 규격×수량 역계산은 안 함 (복잡해짐)

    def _on_ok(self):
        self.result_stock = self._direct_spin.value()
        self.accept()
