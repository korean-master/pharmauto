"""PharmAuto - 약국 자동화 데스크탑 프로그램."""

import os
import sys

# 프로젝트 루트를 sys.path에 추가
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication, QDialog, QLabel, QMainWindow, QMenu,
    QProgressBar, QSystemTrayIcon, QTabWidget, QVBoxLayout,
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

    def __init__(self, download_url: str, expected_hash: str = "",
                 is_delta: bool = False):
        super().__init__()
        self._url = download_url
        self._hash = expected_hash
        self._is_delta = is_delta

    def run(self):
        from core.updater import download_and_apply
        ok = download_and_apply(
            self._url, progress_callback=self.progress.emit,
            expected_hash=self._hash, is_delta=self._is_delta,
        )
        self.finished.emit(ok)


class StartupUpdateDialog(QDialog):
    """앱 시작 시 자동 업데이트 진행 다이얼로그."""

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self._info = info
        self._success = False

        self.setWindowTitle("PharmAuto 업데이트")
        self.setMinimumSize(440, 200)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
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
            is_delta=self._info.get("is_delta", False),
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
            self._status.setText("업데이트 설치 중... 잠시 후 자동으로 시작됩니다.")
            self._status.setStyleSheet(f"font-size: 12px; color: {GREEN}; font-weight: 700;")
            self._progress_bar.setVisible(False)
            self._restart_label.setText("")
            # 설치 프로그램이 실행됐으므로 앱 종료
            QTimer.singleShot(1500, self._exit_for_install)
        else:
            self._status.setText("업데이트 실패 — 현재 버전으로 실행합니다.")
            self._status.setStyleSheet(f"font-size: 12px; color: {RED}; font-weight: 700;")
            self._progress_bar.setVisible(False)
            self._restart_label.setText("")
            QTimer.singleShot(2000, self.accept)

    def _exit_for_install(self):
        """설치 프로그램이 파일을 교체할 수 있도록 앱을 완전히 종료한다."""
        os._exit(0)

    @property
    def update_success(self) -> bool:
        return self._success


class PharmAutoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(1200, 750)
        self.resize(1400, 850)
        self._force_quit = False

        self._update_title()
        self._init_tray()
        self._init_tabs()
        self._init_scheduler()
        self.setStyleSheet(GLOBAL_STYLE)

    def _init_tray(self):
        """시스템 트레이 아이콘 + 메뉴 설정."""
        icon_path = os.path.join(ROOT_DIR, "ui", "icons", "pharmauto.ico")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("PharmAuto - 예약 자동주문 실행 중")

        tray_menu = QMenu()
        show_action = tray_menu.addAction("PharmAuto 열기")
        show_action.triggered.connect(self._show_from_tray)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("완전히 종료")
        quit_action.triggered.connect(self._quit_app)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _show_from_tray(self):
        """트레이에서 창 복원."""
        self.showNormal()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        """트레이 아이콘 더블클릭 시 창 복원."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _quit_app(self):
        """트레이 메뉴 '완전히 종료' — 확실한 프로세스 종료.

        1) 데드맨 스위치: 별도 스레드에서 3초 후 강제 os._exit
           → Qt C코드가 GIL 잡고 멈춰도 프로세스 종료 보장
        2) 정상 경로: 정리 후 즉시 os._exit
        """
        import threading
        self._force_quit = True
        threading.Timer(3.0, lambda: os._exit(1)).start()
        try:
            self._tray.hide()
        except Exception:
            pass
        try:
            if hasattr(self, '_scheduler'):
                self._scheduler.stop()
                self._scheduler.wait(2000)
        except Exception:
            pass
        os._exit(0)

    def _update_title(self):
        import json
        from core import paths
        from core.version import VERSION
        try:
            with open(paths.settings_path(), "r", encoding="utf-8") as f:
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
        self._scheduler.order_error.connect(self._on_scheduled_order_error)
        self._scheduler.unconfigured_drugs.connect(self._on_unconfigured_drugs)
        self._scheduler.oversize_confirm.connect(self._on_oversize_confirm)
        self._scheduler.start()

    def _on_scheduled_order_done(self, results, retry_results):
        # 성공/실패/품절 집계
        success_items = []
        oos_items = []
        failed_items = []
        for r in results:
            for it in r.get("success_items", []):
                success_items.append(it)
            for it in r.get("failed_items", []):
                failed_items.append(it)
            for it in r.get("oos_items", []):
                oos_items.append(it)

        retry_ok = [rr for rr in retry_results if rr.get("success")]
        retry_fail = [rr for rr in retry_results if not rr.get("success")]

        # 품절 코드 제외한 일반 실패
        oos_codes = set(it.get("insurance_code", "") for it in oos_items)
        normal_fail = [it for it in failed_items
                       if it.get("insurance_code", "") not in oos_codes]

        total_ok = len(success_items) + len(retry_ok)
        total_fail = len(normal_fail) + len(retry_fail)

        # 상태바 업데이트
        self.order_tab.status_label.setText(
            f"예약 자동 주문 완료 - 성공 {total_ok}건 / 실패 {total_fail}건"
        )
        self.order_tab._load_order_history()

        # 트레이 팝업 알림 구성
        lines = []
        if success_items:
            names = ", ".join(it.get("drug_name", "")[:8] for it in success_items[:5])
            extra = f" 외 {len(success_items) - 5}건" if len(success_items) > 5 else ""
            lines.append(f"주문 완료 {len(success_items)}건: {names}{extra}")

        if retry_ok:
            for rr in retry_ok:
                name = rr["item"].get("drug_name", "")[:8]
                lines.append(f"품절→대체 성공: {name} ({rr['original_ws']}→{rr['retry_ws']})")

        if retry_fail:
            names = ", ".join(rr["item"].get("drug_name", "")[:8] for rr in retry_fail)
            lines.append(f"전체 품절 {len(retry_fail)}건: {names}")

        if normal_fail:
            names = ", ".join(it.get("drug_name", "")[:8] for it in normal_fail[:3])
            lines.append(f"주문 실패 {len(normal_fail)}건: {names}")

        if not lines:
            lines.append("처리된 항목이 없습니다.")

        # 품절이 있으면 경고 아이콘, 아니면 정보 아이콘
        if retry_fail:
            icon_type = QSystemTrayIcon.MessageIcon.Warning
        elif normal_fail:
            icon_type = QSystemTrayIcon.MessageIcon.Warning
        else:
            icon_type = QSystemTrayIcon.MessageIcon.Information

        self._tray.showMessage(
            "PharmAuto 예약 주문 결과",
            "\n".join(lines),
            icon_type,
            10000,
        )

    def _on_scheduled_order_error(self, msg):
        self.order_tab.status_label.setText(f"예약 주문 실패: {msg}")
        self._tray.showMessage(
            "PharmAuto 예약 주문 오류",
            f"주문 처리 중 오류가 발생했습니다.\n{msg[:100]}",
            QSystemTrayIcon.MessageIcon.Critical,
            10000,
        )

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
        # X 버튼 = 트레이로 최소화 (창만 숨김, 프로세스는 계속)
        # 완전히 종료하려면 트레이 아이콘 우클릭 → "완전히 종료"
        if self._force_quit:
            event.accept()
            return
        event.ignore()
        self.hide()
        try:
            if self._tray and self._tray.supportsMessages():
                self._tray.showMessage(
                    "PharmAuto",
                    "트레이에서 계속 실행됩니다.\n완전히 종료하려면 트레이 아이콘 우클릭 → 완전히 종료.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
        except Exception:
            pass


def _check_and_apply_update(app: QApplication):
    """앱 시작 시 업데이트를 확인하고, 있으면 자동 적용 후 재시작한다."""
    from core import paths
    # 방금 업데이트 직후 마커 체크 — 이중 설치 사이클 방지
    marker_path = os.path.join(paths.get_data_dir(), "installed_version.txt")
    if os.path.exists(marker_path):
        try:
            with open(marker_path, "r", encoding="utf-8") as f:
                installed_ver = f.read().strip()
            os.remove(marker_path)
            from core.version import VERSION
            if installed_ver and installed_ver >= VERSION:
                print(f"[업데이트] 방금 {installed_ver} 설치됨 - 체크 스킵")
                return
        except Exception as e:
            print(f"[업데이트] 마커 읽기 실패: {e}")

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


_lock_handle = None  # 독점 파일 핸들 — 프로세스 종료 시 OS가 자동 해제+삭제


def _is_already_running() -> bool:
    """독점 파일 잠금으로 이미 실행 중인 인스턴스가 있는지 확인한다.

    Windows CreateFileW(share=0) + FILE_FLAG_DELETE_ON_CLOSE:
    - 프로세스가 살아있는 동안 다른 프로세스가 파일을 열 수 없음
    - 프로세스가 어떻게 죽든 (정상/crash/kill) OS가 핸들 닫고 파일 삭제
    - 명시적 해제/정리 코드 불필요
    """
    global _lock_handle
    import ctypes
    lock_path = os.path.join(os.environ.get("TEMP", "."), "PharmAuto.lock")
    GENERIC_WRITE = 0x40000000
    CREATE_ALWAYS = 2
    FILE_FLAG_DELETE_ON_CLOSE = 0x04000000
    INVALID_HANDLE = -1

    handle = ctypes.windll.kernel32.CreateFileW(
        lock_path, GENERIC_WRITE,
        0,       # dwShareMode=0 → 독점 (다른 프로세스 접근 불가)
        None,    # lpSecurityAttributes
        CREATE_ALWAYS,
        FILE_FLAG_DELETE_ON_CLOSE,
        None,
    )
    if handle == INVALID_HANDLE:
        return True  # 잠금 실패 → 이미 실행 중
    _lock_handle = handle  # 핸들을 전역에 보관 (GC 방지)
    return False


def _bring_existing_window():
    """이미 실행 중인 PharmAuto 창을 찾아서 앞으로 가져온다."""
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32

    # PharmAuto 타이틀을 가진 윈도우 찾기
    hwnd = user32.FindWindowW(None, None)
    target = None

    # EnumWindows 콜백으로 PharmAuto 창 찾기
    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )

    def callback(hwnd, _):
        nonlocal target
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if "PharmAuto" in buf.value:
                target = hwnd
                return False  # 찾으면 중단
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)

    if target:
        SW_RESTORE = 9
        user32.ShowWindow(target, SW_RESTORE)
        user32.SetForegroundWindow(target)
    else:
        # 창이 숨겨져 있어서 못 찾는 경우 — 알림만 표시
        from PyQt6.QtWidgets import QMessageBox
        _app = QApplication(sys.argv)
        QMessageBox.information(
            None, "PharmAuto",
            "PharmAuto가 트레이에서 실행 중입니다.\n"
            "시스템 트레이(▲)에서 아이콘을 더블클릭하세요."
        )
        _app.quit()


def _db_connection_broken() -> bool:
    """설정된 DB에 연결할 수 있는지 빠르게 확인한다."""
    try:
        import json
        from core import paths
        settings_path = paths.settings_path()
        if not os.path.exists(settings_path):
            return False
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
        if not settings.get("setup_complete"):
            return False
        db = settings.get("db", {})
        if not db.get("server"):
            return True
        import pyodbc
        from core.db_conn import build_conn_str
        conn_str = build_conn_str(db)
        conn = pyodbc.connect(conn_str, timeout=3, readonly=True)
        conn.close()
        return False
    except Exception:
        return True


def main():
    # DPI 스케일링 대응
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    # v1.5.35: 기존 {app}\config 데이터를 %APPDATA%\PharmAuto 로 일회성 이전
    # 로거/다른 core 모듈보다 먼저 — 모두 이 경로에 의존
    from core.paths import migrate_from_legacy_install, snapshot_config_daily
    migrate_from_legacy_install()

    # 단일 인스턴스 보장 — 이미 실행 중이면 기존 창 복원
    if _is_already_running():
        _bring_existing_window()
        sys.exit(0)

    # 일 1회 config 스냅샷 — 사용자 실수 방지 안전장치
    try:
        snapshot_config_daily()
    except Exception:
        pass

    # 로깅 시스템 초기화 — 모든 print/에러를 파일에 기록
    from core.logger import setup_global_logging, get_logger
    setup_global_logging()
    log = get_logger()
    from core.version import VERSION
    log.info(f"PharmAuto v{VERSION} 시작")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 앱 아이콘 설정 (작업표시줄 + 타이틀바)
    icon_path = os.path.join(ROOT_DIR, "ui", "icons", "pharmauto.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    font = QFont("Malgun Gothic", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    apply_palette(app)

    # 스플래시 — 콜드 스타트 동안 사용자 피드백 (메인 창 뜰 때까지 표시)
    from PyQt6.QtWidgets import QSplashScreen
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtCore import Qt as _Qt
    splash = None
    splash_png = os.path.join(ROOT_DIR, "ui", "icons", "pharmauto_256.png")
    if os.path.exists(splash_png):
        pix = QPixmap(splash_png).scaled(
            280, 280, _Qt.AspectRatioMode.KeepAspectRatio,
            _Qt.TransformationMode.SmoothTransformation,
        )
        splash = QSplashScreen(pix, _Qt.WindowType.WindowStaysOnTopHint)
        splash.showMessage(
            f"PharmAuto v{VERSION} 로딩 중...",
            _Qt.AlignmentFlag.AlignBottom | _Qt.AlignmentFlag.AlignHCenter,
            _Qt.GlobalColor.black,
        )
        splash.show()
        app.processEvents()

    def _hide_splash():
        if splash is not None:
            splash.hide()
            app.processEvents()

    # 활성화 안 됐으면 코드 입력
    from core.auth import is_activated
    if not is_activated():
        _hide_splash()
        from ui.activation_dialog import ActivationDialog
        dlg = ActivationDialog()
        dlg.exec()
        if not dlg.activated:
            sys.exit(0)

    # 메인 윈도우 뜨기 전에 업데이트 체크 & 자동 적용
    _hide_splash()
    _check_and_apply_update(app)

    # 첫 실행이거나 DB 연결 불가 시 설치 마법사
    from ui.setup_wizard import needs_setup
    if needs_setup() or _db_connection_broken():
        _hide_splash()
        from ui.setup_wizard import SetupWizard
        wizard = SetupWizard()
        wizard.exec()
        if not wizard.setup_complete:
            sys.exit(0)

    # 기존 평문 비밀번호/API키 암호화 마이그레이션
    from core.crypto import migrate_plaintext
    migrate_plaintext()

    from core.drug_api import preload_cache
    preload_cache()

    from core.cloud import start_background_sync
    start_background_sync()

    # 주문 이력 ↔ 재고 불일치 자동 보정
    from core.inventory import sync_stock_with_order_history
    sync_stock_with_order_history()

    window = PharmAutoWindow()
    window.show()
    if splash is not None:
        splash.finish(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
