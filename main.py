"""PharmAuto - 약국 자동화 데스크탑 프로그램."""

import os
import sys

# 프로젝트 루트를 sys.path에 추가
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QDialog, QLabel, QMainWindow,
    QProgressBar, QTabWidget, QVBoxLayout,
)

from tabs.board_tab import BoardTab
from tabs.job_tab import JobTab
from tabs.order_tab import OrderTab
from tabs.price_tab import PriceTab
from tabs.return_tab import ReturnTab
from tabs.settings_tab import SettingsTab
from ui.styles import GLOBAL_STYLE, apply_palette


class UpdateDownloadWorker(QThread):
    """백그라운드에서 업데이트를 다운로드/적용한다."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(self, download_url: str, expected_hash: str = ""):
        super().__init__()
        self._url = download_url
        self._hash = expected_hash

    def run(self):
        from core.updater import download_and_apply
        ok = download_and_apply(
            self._url, progress_callback=self.progress.emit,
            expected_hash=self._hash
        )
        self.finished.emit(ok)


class StartupUpdateDialog(QDialog):
    """앱 시작 시 자동 업데이트 진행 다이얼로그."""

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self._info = info
        self._success = False

        self.setWindowTitle("PharmAuto 업데이트")
        self.setFixedSize(440, 200)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setStyleSheet("QDialog { background: white; }")

        from ui.styles import BLUE, TEXT, TEXT_SEC

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(32, 28, 32, 28)

        title = QLabel("업데이트 중...")
        title.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {TEXT};")
        layout.addWidget(title)

        ver_label = QLabel(f"v{info['version']} 으로 업데이트하고 있습니다.")
        ver_label.setStyleSheet(f"font-size: 13px; color: {BLUE}; font-weight: 600;")
        layout.addWidget(ver_label)

        self._status = QLabel("다운로드 준비 중...")
        self._status.setStyleSheet(f"font-size: 12px; color: {TEXT_SEC};")
        layout.addWidget(self._status)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ border: none; background: #F2F3F5; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {BLUE}; border-radius: 3px; }}"
        )
        layout.addWidget(self._progress_bar)

        self._restart_label = QLabel("완료 후 자동으로 재시작됩니다.")
        self._restart_label.setStyleSheet(f"font-size: 11px; color: {TEXT_SEC};")
        layout.addWidget(self._restart_label)

        layout.addStretch()

    def start(self):
        """다이얼로그를 띄우고 즉시 다운로드를 시작한다."""
        self._worker = UpdateDownloadWorker(
            self._info["download_url"],
            self._info.get("expected_hash", ""),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()
        self.exec()

    def _on_progress(self, msg: str):
        self._status.setText(msg)

    def _on_finished(self, success: bool):
        from ui.styles import GREEN, RED

        if success:
            self._success = True
            self._status.setText("업데이트 완료! 재시작합니다...")
            self._status.setStyleSheet(f"font-size: 12px; color: {GREEN}; font-weight: 700;")
            self._progress_bar.setVisible(False)
            QTimer.singleShot(1500, self._do_restart)
        else:
            self._status.setText("업데이트 실패 — 현재 버전으로 실행합니다.")
            self._status.setStyleSheet(f"font-size: 12px; color: {RED}; font-weight: 700;")
            self._progress_bar.setVisible(False)
            self._restart_label.setText("")
            QTimer.singleShot(2000, self.accept)

    def _do_restart(self):
        from core.updater import restart_app
        restart_app()

    @property
    def update_success(self) -> bool:
        return self._success


class PharmAutoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(1200, 750)
        self.resize(1400, 850)

        self._update_title()
        self._init_tabs()
        self._init_scheduler()
        self.setStyleSheet(GLOBAL_STYLE)

    def _update_title(self):
        import json
        from core.version import VERSION
        settings_path = os.path.join(ROOT_DIR, "config", "settings.json")
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            name = settings.get("pharmacy_name", "")
        except Exception:
            name = ""
        base = f"PharmAuto v{VERSION}"
        if name:
            self.setWindowTitle(f"{base} - {name}")
        else:
            self.setWindowTitle(base)

    def _init_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)

        self.order_tab = OrderTab()
        self.return_tab = ReturnTab()
        self.price_tab = PriceTab()
        self.job_tab = JobTab()
        self.board_tab = BoardTab()
        self.settings_tab = SettingsTab(
            on_wholesaler_changed=self.order_tab.reload_wholesalers,
            on_schedule_changed=self.order_tab._refresh_schedule_summary,
        )

        # 자동주문 탭 → 설정 탭 연동
        def _sync_settings_tab():
            self.settings_tab._load_schedule_settings()
            self.settings_tab._load_split_settings()
        self.order_tab._on_schedule_changed_callback = _sync_settings_tab
        self.order_tab.sched_detail_btn.clicked.connect(
            self._go_to_schedule_settings
        )

        self.tabs.addTab(self.order_tab, "  자동 주문  ")
        self.tabs.addTab(self.return_tab, "  자동 반품  ")
        self.tabs.addTab(self.price_tab, "  일반약 가격비교  ")
        self.tabs.addTab(self.job_tab, "  구인구직  ")
        self.tabs.addTab(self.board_tab, "  약국 직거래  ")
        self.tabs.addTab(self.settings_tab, "  설정  ")

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

    def _go_to_schedule_settings(self):
        """'상세 설정 →' 클릭 시 설정 탭으로 이동 + 예약 설정 카드로 스크롤."""
        settings_index = self.tabs.indexOf(self.settings_tab)
        self.tabs.setCurrentIndex(settings_index)
        self.settings_tab.scroll_to_schedule()

    def _on_tab_changed(self, index: int):
        widget = self.tabs.widget(index)
        if widget is self.settings_tab:
            # 약품 목록(무거움)은 리로드 안 함. 설정값만 갱신.
            self.settings_tab._load_db_settings()
            self.settings_tab._load_schedule_settings()
            self.settings_tab._load_split_settings()
            self.settings_tab._load_exclusions()
        elif widget is self.order_tab:
            # 설정 탭에서 변경했을 수 있으니 요약 갱신
            self.order_tab._refresh_schedule_summary()

    def _init_scheduler(self):
        from core.scheduler import OrderScheduler
        self._scheduler = OrderScheduler()
        self._scheduler.order_started.connect(
            lambda: self.order_tab.status_label.setText("예약 자동 주문 시작...")
        )
        self._scheduler.order_progress.connect(
            lambda msg: self.order_tab.status_label.setText(msg)
        )
        self._scheduler.order_finished.connect(self._on_scheduled_order_done)
        self._scheduler.order_error.connect(
            lambda msg: self.order_tab.status_label.setText(f"예약 주문 실패: {msg}")
        )
        self._scheduler.unconfigured_drugs.connect(self._on_unconfigured_drugs)
        self._scheduler.oversize_confirm.connect(self._on_oversize_confirm)
        self._scheduler.start()

    def _on_scheduled_order_done(self, results):
        total = sum(len(r.get("items", [])) for r in results)
        failed = sum(len(r.get("failed_items", [])) for r in results)
        self.order_tab.status_label.setText(
            f"예약 자동 주문 완료 - {total - failed}개 성공, {failed}개 실패"
        )
        self.order_tab._load_order_history()

    def _on_oversize_confirm(self, oversize_items):
        """스케줄러에서 4배 초과 약품 확인 요청 → 다이얼로그 표시."""
        from tabs.order_tab import OversizeDialog

        dlg = OversizeDialog(oversize_items, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._scheduler.set_oversize_choices(dlg.get_choices())
        else:
            # 취소 시 선호규격 유지로 진행
            self._scheduler.set_oversize_choices({})

    def _on_unconfigured_drugs(self, drugs):
        names = ", ".join(d["drug_name"] for d in drugs[:5])
        extra = f" 외 {len(drugs) - 5}개" if len(drugs) > 5 else ""
        self.order_tab.status_label.setText(
            f"미설정 약품 {len(drugs)}건: {names}{extra} (주문탭에서 설정 필요)"
        )

    def closeEvent(self, event):
        if hasattr(self, '_scheduler'):
            self._scheduler.stop()
            self._scheduler.wait(2000)
        event.accept()


def _check_and_apply_update(app: QApplication):
    """앱 시작 시 업데이트를 확인하고, 있으면 자동 적용 후 재시작한다."""
    try:
        from core.updater import check_update
        info = check_update()
    except Exception as e:
        print(f"[업데이트] 확인 실패: {e}")
        return

    if not info:
        return

    dlg = StartupUpdateDialog(info)
    dlg.start()
    # 업데이트 성공 시 restart_app()으로 프로세스 교체되므로 여기에 도달하면 실패한 것


def _is_already_running() -> bool:
    """Named Mutex로 이미 실행 중인 인스턴스가 있는지 확인한다."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, "PharmAuto_SingleInstance_Mutex")
    # ERROR_ALREADY_EXISTS = 183
    return kernel32.GetLastError() == 183


def main():
    # DPI 스케일링 대응
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    # 단일 인스턴스 보장
    if _is_already_running():
        from PyQt6.QtWidgets import QApplication, QMessageBox
        _app = QApplication(sys.argv)
        QMessageBox.warning(None, "PharmAuto", "이미 실행 중입니다.")
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    font = QFont("Malgun Gothic", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    apply_palette(app)

    # 활성화 안 됐으면 코드 입력
    from core.auth import is_activated
    if not is_activated():
        from ui.activation_dialog import ActivationDialog
        dlg = ActivationDialog()
        dlg.exec()
        if not dlg.activated:
            sys.exit(0)

    # 첫 실행이면 설치 마법사
    from ui.setup_wizard import needs_setup
    if needs_setup():
        from ui.setup_wizard import SetupWizard
        wizard = SetupWizard()
        wizard.exec()
        if not wizard.setup_complete:
            sys.exit(0)

    # 기존 평문 비밀번호/API키 암호화 마이그레이션
    from core.crypto import migrate_plaintext
    migrate_plaintext()

    # 메인 윈도우 뜨기 전에 업데이트 체크 & 자동 적용
    _check_and_apply_update(app)

    from core.drug_api import preload_cache
    preload_cache()

    from core.cloud import start_background_sync
    start_background_sync()

    # 주문 이력 ↔ 재고 불일치 자동 보정
    from core.inventory import sync_stock_with_order_history
    sync_stock_with_order_history()

    window = PharmAutoWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
