"""약품 주문 방식 설정 팝업."""

import json
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QRadioButton,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ui.styles import (
    BLUE as _BLUE, TEXT, TEXT_SEC as _TEXT_SEC,
    DIALOG_BG, RADIO_BUTTON, COMBO_MALGUN,
    btn_primary, btn_outline, btn_small_primary,
)

UNIT_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "unit_cache.json")


def _load_unit_cache() -> dict:
    if os.path.exists(UNIT_CACHE_PATH):
        with open(UNIT_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_unit_cache(cache: dict):
    os.makedirs(os.path.dirname(UNIT_CACHE_PATH), exist_ok=True)
    with open(UNIT_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


class UnitFetchWorker(QThread):
    """규격 조회 워커.

    조회 순서:
      1. 클라우드 (Supabase) — 0.5초 이내
      2. 지오영 사이트 (Playwright) — 6초+ (폴백)
    성공하면 로컬 캐시 + 클라우드에 저장.
    """
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, insurance_code: str):
        super().__init__()
        self._code = insurance_code

    def run(self):
        # 1단계: 클라우드 조회 (빠름)
        units = self._fetch_from_cloud()
        if units:
            self.finished.emit(units)
            return

        # 2단계: 지오영 사이트 조회 (느림, 폴백)
        units = self._fetch_from_geoyoung()
        if units:
            self._upload_to_cloud(units)
            self.finished.emit(units)
        # _fetch_from_geoyoung에서 에러 시 self.error.emit 호출됨

    def _fetch_from_cloud(self) -> list[int]:
        try:
            from core.cloud import fetch_units
            units = fetch_units(self._code)
            if units:
                print(f"[규격조회] {self._code} 클라우드 히트: {units}")
                return units
        except Exception:
            pass
        return []

    def _upload_to_cloud(self, units: list[int]):
        try:
            from core.cloud import upload_units
            upload_units(self._code, units)
        except Exception:
            pass

    def _fetch_from_geoyoung(self) -> list[int]:
        import re
        from playwright.sync_api import sync_playwright

        def _parse_pack(text):
            m = re.search(r'(\d+)\s*[TtCcPp]', text)
            return int(m.group(1)) if m else 0

        try:
            config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
            ws_path = os.path.join(config_dir, "wholesalers.json")
            with open(ws_path, "r", encoding="utf-8") as f:
                ws = json.load(f).get("geo", {})

            # 지오영 계정 없으면 스킵
            if not ws.get("id") or not ws.get("pw"):
                self.error.emit("지오영 계정 미설정 (클라우드에도 데이터 없음)")
                return []

            # 암호화된 ID/PW 복호화
            uid = ws.get("id", "")
            upw = ws.get("pw", "")
            if uid.startswith("ENC:") or upw.startswith("ENC:"):
                from core.crypto import decrypt
                uid = decrypt(uid)
                upw = decrypt(upw)

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto("https://bpm.geoweb.kr/", wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                page.fill('#LoginID', uid)
                page.fill('#Password', upw)
                page.click('button.btn_login')
                page.wait_for_timeout(2500)
                page.fill('#txt_product', self._code)
                page.click('button.btn_search')
                page.wait_for_timeout(2000)
                rows = page.query_selector_all(
                    '#tbodySearchProduct tr.tr-product-list'
                )
                units = []
                for row in rows:
                    std_el = row.query_selector('td.standard')
                    if std_el:
                        text = std_el.inner_text().strip()
                        size = _parse_pack(text)
                        if size > 0:
                            units.append(size)
                browser.close()

            result = sorted(set(units))
            if not result:
                self.error.emit("검색 결과 없음")
            return result

        except Exception as e:
            self.error.emit(str(e))
            return []


# 제형 키워드 → 단위 매핑 (긴 키워드부터 매칭)
_FORM_TO_UNIT = [
    # 점안/점이/점비 (액보다 먼저)
    ("점안", "병"), ("점이", "병"), ("점비", "병"),
    # 현탁 (액보다 먼저)
    ("현탁", "포"),
    # 고체 경구
    ("정", "정"), ("캡슐", "캡슐"), ("캅셀", "캡슐"),
    ("과립", "포"), ("산제", "포"), ("트로키", "정"),
    ("츄어블", "정"), ("추어블", "정"), ("환", "정"),
    # 액제
    ("시럽", "포"), ("내용액", "포"), ("드라이시럽", "포"),
    ("용액", "병"), ("액제", "포"), ("액", "포"),
    # 외용
    ("연고", "개"), ("크림", "개"), ("겔", "개"), ("젤", "개"),
    ("로션", "병"), ("스프레이", "병"), ("분무", "병"),
    # 패치/좌제
    ("패치", "매"), ("첩부", "매"), ("좌제", "개"), ("좌약", "개"),
    # 주사
    ("주사", "개"), ("프리필드", "개"),
    # 흡입
    ("흡입", "개"), ("에어로졸", "개"), ("네뷸", "개"),
    # 안과/이비인후
    ("안연고", "개"),
]


def _guess_unit(drug_name: str) -> str:
    """약품명에서 제형 키워드를 찾아 단위를 추측한다."""
    for keyword, unit in _FORM_TO_UNIT:
        idx = drug_name.find(keyword)
        if idx < 0:
            continue
        # "정", "액" 같은 1글자 키워드는 제형 위치에 있을 때만 매칭
        # (뒤에 숫자, 괄호, 끝 등이 와야 함 - 약품명 중간 글자 방지)
        if len(keyword) == 1:
            after = idx + 1
            if after < len(drug_name) and drug_name[after] not in "0123456789(_(, ·":
                continue
        return unit
    return "정"


class DrugSetupDialog(QDialog):
    """약품 첫 등장 시 or 설정 변경 시 뜨는 팝업.

    결과:
        self.result_config: dict or None (취소 시)
    """

    def __init__(self, drug_name: str, insurance_code: str,
                 today_qty: int = 0,
                 unit_options: list[int] | None = None,
                 current_config: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("약품 주문 설정")
        self.setMinimumWidth(400)
        self.setStyleSheet(DIALOG_BG)

        self.result_config = None
        cfg = current_config or {}

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        # 약품명
        title = QLabel(f"{drug_name}")
        title.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {TEXT};")
        title.setWordWrap(True)
        layout.addWidget(title)

        # unit이 명시적으로 설정된 경우만 사용, 아니면 약품명에서 추측
        saved_unit = cfg.get("unit", "")
        guessed = _guess_unit(drug_name)
        self._drug_unit = saved_unit if (saved_unit and saved_unit != "정") else guessed

        sub = QLabel(f"보험코드: {insurance_code}    오늘 사용량: {today_qty}{self._drug_unit}")
        sub.setStyleSheet(f"font-size: 12px; color: {_TEXT_SEC};")
        layout.addWidget(sub)

        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #E5E8EB;")
        layout.addWidget(line)

        # ── 주문 방식 ──
        type_label = QLabel("주문 방식")
        type_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {TEXT};")
        layout.addWidget(type_label)

        self._type_group = QButtonGroup(self)

        # 즉시 주문
        self._radio_immediate = QRadioButton("즉시 주문")
        self._radio_immediate.setStyleSheet(RADIO_BUTTON)
        desc1 = QLabel("  오늘 나간 만큼 자동 주문")
        desc1.setStyleSheet(f"font-size: 11px; color: {_TEXT_SEC}; margin-left: 20px;")
        self._type_group.addButton(self._radio_immediate, 0)
        layout.addWidget(self._radio_immediate)
        layout.addWidget(desc1)

        # 적정재고 유지
        self._radio_stock = QRadioButton("적정재고 유지")
        self._radio_stock.setStyleSheet(RADIO_BUTTON)
        self._type_group.addButton(self._radio_stock, 1)
        layout.addWidget(self._radio_stock)

        desc2 = QLabel("  설정한 재고량이 유지되도록 부족분만 자동 주문")
        desc2.setStyleSheet(f"font-size: 11px; color: {_TEXT_SEC}; margin-left: 20px;")
        layout.addWidget(desc2)

        stock_row = QHBoxLayout()
        stock_row.setContentsMargins(24, 0, 0, 0)
        stock_row.setSpacing(8)
        stock_row.addWidget(QLabel("적정재고량:"))
        self._target_spin = QSpinBox()
        self._target_spin.setRange(0, 99999)
        self._target_spin.setValue(cfg.get("target_stock", 300))
        self._target_spin.setSuffix(f" {self._drug_unit}")
        self._target_spin.setMinimumWidth(120)
        self._target_spin.valueChanged.connect(self._on_target_changed)
        stock_row.addWidget(self._target_spin)
        stock_row.addStretch()
        layout.addLayout(stock_row)

        # 수동 주문
        self._radio_manual = QRadioButton("수동 주문")
        self._radio_manual.setStyleSheet(RADIO_BUTTON)
        desc3 = QLabel("  자동 주문 안 함, 수량 직접 입력")
        desc3.setStyleSheet(f"font-size: 11px; color: {_TEXT_SEC}; margin-left: 20px;")
        self._type_group.addButton(self._radio_manual, 2)
        layout.addWidget(self._radio_manual)
        layout.addWidget(desc3)

        # 자동주문 제외
        self._radio_exclude = QRadioButton("자동주문 제외")
        self._radio_exclude.setStyleSheet(RADIO_BUTTON)
        desc4 = QLabel("  주문 목록에서 영구 제외")
        desc4.setStyleSheet(f"font-size: 11px; color: {_TEXT_SEC}; margin-left: 20px;")
        self._type_group.addButton(self._radio_exclude, 3)
        layout.addWidget(self._radio_exclude)
        layout.addWidget(desc4)

        # 기본 선택
        order_type = cfg.get("order_type", "immediate")
        if order_type == "stock":
            self._radio_stock.setChecked(True)
        elif order_type == "manual":
            self._radio_manual.setChecked(True)
        elif order_type == "exclude":
            self._radio_exclude.setChecked(True)
        else:
            self._radio_immediate.setChecked(True)

        # 구분선
        line2 = QLabel()
        line2.setFixedHeight(1)
        line2.setStyleSheet("background: #E5E8EB;")
        layout.addWidget(line2)

        # ── 단위 ──
        unit_type_row = QHBoxLayout()
        unit_type_row.setSpacing(8)
        unit_type_lbl = QLabel("단위:")
        unit_type_lbl.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {TEXT};")
        unit_type_row.addWidget(unit_type_lbl)

        self._unit_type_combo = QComboBox()
        self._unit_type_combo.setMinimumWidth(100)
        self._unit_type_combo.setStyleSheet(COMBO_MALGUN)
        for u in ["정", "포", "캡슐", "병", "매", "개", "mL"]:
            self._unit_type_combo.addItem(u)
        idx = self._unit_type_combo.findText(self._drug_unit)
        if idx >= 0:
            self._unit_type_combo.setCurrentIndex(idx)
        unit_type_row.addStretch()
        layout.addLayout(unit_type_row)

        # ── 선호 규격 (직접 입력) ──
        unit_row = QHBoxLayout()
        unit_row.setSpacing(8)
        unit_lbl = QLabel("선호 규격:")
        unit_lbl.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {TEXT};")
        unit_row.addWidget(unit_lbl)

        current_pref = cfg.get("preferred_unit", 0)
        self._pref_spin = QSpinBox()
        self._pref_spin.setRange(0, 99999)
        self._pref_spin.setValue(current_pref)
        self._pref_spin.setSuffix(f" {self._drug_unit}")
        self._pref_spin.setSpecialValueText("자동")
        self._pref_spin.setMinimumWidth(120)
        unit_row.addWidget(self._pref_spin)

        self._insurance_code = insurance_code
        self._fetch_btn = QPushButton("규격 조회")
        self._fetch_btn.setStyleSheet(btn_small_primary())
        self._fetch_btn.clicked.connect(self._on_fetch_units)
        unit_row.addWidget(self._fetch_btn)

        unit_row.addStretch()
        layout.addLayout(unit_row)

        # 규격 안내 문구
        pref_hint = QLabel(
            "단종된 규격이 나올 수 있으니 수기 입력을 추천드립니다.\n"
            "한 번만 입력해두면 자동 저장됩니다."
        )
        pref_hint.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px; line-height: 1.3;")
        pref_hint.setWordWrap(True)
        layout.addWidget(pref_hint)

        # 규격 조회 결과 표시 영역
        self._fetch_result_label = QLabel("")
        self._fetch_result_label.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px;")
        self._fetch_result_label.setWordWrap(True)
        self._fetch_result_label.hide()
        layout.addWidget(self._fetch_result_label)

        self._fetch_worker = None

        # ── 현재 재고 (직접 입력 가능) ──
        from core.inventory import get_current_stock
        self._initial_stock = get_current_stock(insurance_code) if cfg else 0

        inv_row = QHBoxLayout()
        inv_row.setSpacing(8)
        inv_lbl = QLabel("현재 재고:")
        inv_lbl.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {TEXT};")
        inv_row.addWidget(inv_lbl)

        self._stock_spin = QSpinBox()
        self._stock_spin.setRange(0, 99999)
        self._stock_spin.setValue(self._initial_stock)
        self._stock_spin.setSuffix(f" {self._drug_unit}")
        self._stock_spin.setMinimumWidth(120)
        inv_row.addWidget(self._stock_spin)

        stock_hint = QLabel("직접 입력하면 자동 반영됩니다")
        stock_hint.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px;")
        inv_row.addWidget(stock_hint)
        inv_row.addStretch()
        layout.addLayout(inv_row)

        # ── 버튼 ──
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

    def _on_fetch_units(self):
        """규격 조회. 로컬캐시 → 클라우드 → 지오영 순서."""
        cache = _load_unit_cache()
        cached = cache.get(self._insurance_code)
        if cached:
            self._show_fetch_result(cached)
            return

        if self._fetch_worker and self._fetch_worker.isRunning():
            return

        self._fetch_btn.setEnabled(False)
        self._fetch_btn.setText("조회 중...")
        self._fetch_result_label.setText("규격 조회 중... 잠시만 기다려주세요.")
        self._fetch_result_label.setStyleSheet(f"color: {_BLUE}; font-size: 12px;")
        self._fetch_result_label.show()

        from ui.spinner import SpinnerOverlay
        if not hasattr(self, '_spinner'):
            self._spinner = SpinnerOverlay(self)
        self._spinner.show_with_message("규격 조회 중...")

        self._fetch_worker = UnitFetchWorker(self._insurance_code)
        self._fetch_worker.finished.connect(self._on_fetch_done)
        self._fetch_worker.error.connect(self._on_fetch_error)
        self._fetch_worker.start()

    def _on_fetch_done(self, units: list):
        self._fetch_btn.setEnabled(True)
        self._fetch_btn.setText("규격 조회")
        if hasattr(self, '_spinner'):
            self._spinner.hide_spinner()

        if not units:
            self._fetch_result_label.setText("규격 정보를 찾을 수 없습니다.")
            self._fetch_result_label.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px;")
            return

        # 로컬 캐시 저장
        cache = _load_unit_cache()
        cache[self._insurance_code] = units
        _save_unit_cache(cache)

        self._show_fetch_result(units)

    def _on_fetch_error(self, msg: str):
        self._fetch_btn.setEnabled(True)
        self._fetch_btn.setText("규격 조회")
        if hasattr(self, '_spinner'):
            self._spinner.hide_spinner()
        self._fetch_result_label.setText(f"조회 실패: {msg}")
        self._fetch_result_label.setStyleSheet(f"color: #F45452; font-size: 12px;")

    def _show_fetch_result(self, units: list[int]):
        drug_unit = self._unit_type_combo.currentText()
        text = "  |  ".join(f"{u}{drug_unit}" for u in units)
        self._fetch_result_label.setText(f"조회 결과: {text}")
        self._fetch_result_label.setStyleSheet(
            f"color: {_BLUE}; font-size: 12px; font-weight: 600;"
        )
        self._fetch_result_label.show()

        # 선호 규격이 아직 0(자동)이면 첫 번째 규격으로 설정
        if self._pref_spin.value() == 0 and units:
            self._pref_spin.setValue(units[0])

    def _on_target_changed(self, value: int):
        if value > 0:
            self._radio_stock.setChecked(True)

    def _on_ok(self):
        checked_id = self._type_group.checkedId()
        order_type = ["immediate", "stock", "manual", "exclude"][checked_id]

        pref_unit = self._pref_spin.value()

        # 재고가 변경됐으면 저장
        new_stock = self._stock_spin.value()
        if new_stock != self._initial_stock:
            from core.inventory import set_current_stock
            set_current_stock(self._insurance_code, new_stock)

        self.result_config = {
            "order_type": order_type,
            "preferred_unit": pref_unit,
            "unit_options": [pref_unit] if pref_unit > 0 else [],
            "target_stock": self._target_spin.value(),
            "unit": self._unit_type_combo.currentText(),
            "stock_changed": new_stock != self._initial_stock,
        }
        self.accept()
