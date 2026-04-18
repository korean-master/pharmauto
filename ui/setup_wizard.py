"""첫 실행 설치 마법사 - 약국 프로그램 선택만 하면 자동 세팅."""

import json
import os
import subprocess

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

# 약국 프로그램별 기본 DB명
PHARMACY_PROGRAMS = {
    "epharm": {"label": "이팜 (EPHARM)", "db": "eP_PHARM", "driver": "SQL Server"},
    "upharm": {"label": "유팜 (UPHARM)", "db": "", "driver": "SQL Server"},
    "it3000": {"label": "IT3000", "db": "", "driver": "SQL Server"},
    "custom": {"label": "기타 (직접 입력)", "db": "", "driver": "SQL Server"},
}

# IT3000 DB명 후보 (정확한 DB명이 공개되지 않아 자동 탐색)
IT3000_DB_HINTS = ["IT3000", "it3000", "InfoTech", "infotech", "PHARM", "pharm"]

# 유팜 DB명 우선순위 — 실측 기반 (2026-04-18): atpharm 이 메인, upharmLog/Resources 는 보조
# exact match 순서대로 시도 (Log/Resources 등 보조 DB 제외)
UPHARM_DB_CANDIDATES = ["atpharm", "upharm", "UPHARM"]

# 유팜 SQL 읽기전용 자격증명 — 각 약국 배포 시 Plan B로 동일 계정 생성
# 사용자 UI에 노출 없이 자동 적용. 바이너리에서 추출 가능하므로 추후
# 활성화 코드 연계 원격 발급 방식으로 강화 예정.
_UPHARM_SQL_USER = "pharmauto_ro"
_UPHARM_SQL_PASS = "PharmAuto2026Ro!"


LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
LOG_PATH = os.path.join(LOG_DIR, "setup_log.txt")


def _get_version() -> str:
    try:
        from core.version import VERSION
        return VERSION
    except Exception:
        return "unknown"


def _log(msg: str):
    """설치 마법사 로그를 파일에 기록한다."""
    from datetime import datetime
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}\n"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


class AutoSetupWorker(QThread):
    """SQL Server 인스턴스 탐색 → DB 매칭 → 약국명 조회를 한번에 처리."""
    progress = pyqtSignal(int)  # 0~100
    finished = pyqtSignal(dict)  # {"success", "server", "database", "pharmacy_name", "error"}

    def __init__(self, program_key: str, auth_info: dict | None = None):
        super().__init__()
        self._program = program_key
        # auth_info: {"auth": "windows"|"sql", "username": str, "password": str (plain)}
        self._auth_info = auth_info or {"auth": "windows"}

    def run(self):
        import pyodbc
        from core.db_conn import build_conn_str
        from core.crypto import encrypt

        _log(f"=== 설치 마법사 시작 (프로그램: {self._program}) ===")
        auth_label = (
            "SQL 인증" if self._auth_info.get("auth") == "sql" else "Windows 인증"
        )
        _log(f"  인증 방식: {auth_label}")

        info = PHARMACY_PROGRAMS[self._program]
        target_db = info["db"]
        driver = info["driver"]
        result = {"success": False, "server": "", "database": "", "pharmacy_name": "", "error": ""}

        # SQL 인증 선택 시 자격증명 검증
        if self._auth_info.get("auth") == "sql":
            if not self._auth_info.get("username") or not self._auth_info.get("password"):
                result["error"] = "SQL 인증 선택 시 사용자명과 비밀번호를 입력해야 합니다"
                self.finished.emit(result)
                return

        # 공통 db 설정 — 서버는 각 인스턴스에서 교체됨
        base_db = {
            "driver": driver,
            "auth": self._auth_info.get("auth", "windows"),
            "username": self._auth_info.get("username", ""),
            # 검색 단계에선 평문 비번을 그대로 사용 (암호화는 저장 직전)
            "password": "",
        }
        plain_password = self._auth_info.get("password", "")

        # 1단계: SQL Server 인스턴스 탐색 (0~30%)
        self.progress.emit(10)
        instances = []

        _log("1단계: SQL Server 인스턴스 탐색")
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Microsoft SQL Server",
            )
            val, _ = winreg.QueryValueEx(key, "InstalledInstances")
            winreg.CloseKey(key)
            for inst in val:
                name = f"localhost\\{inst}" if inst.upper() != "MSSQLSERVER" else "localhost"
                if name not in instances:
                    instances.append(name)
            _log(f"  레지스트리에서 발견: {instances}")
        except Exception as e:
            _log(f"  레지스트리 탐색 실패: {e}")

        try:
            proc = subprocess.run(
                ["sqlcmd", "-L"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line and not line.startswith("Servers:") and line not in instances:
                    instances.append(line)
            _log(f"  sqlcmd 탐색 후 전체: {instances}")
        except Exception as e:
            _log(f"  sqlcmd 탐색 실패: {e}")

        if "localhost" not in instances:
            instances.insert(0, "localhost")

        _log(f"  최종 인스턴스 목록: {instances}")
        self.progress.emit(30)

        if not instances:
            _log("  실패: 인스턴스 없음")
            result["error"] = "SQL Server를 찾을 수 없습니다"
            self.finished.emit(result)
            return

        # 2단계: 각 인스턴스에서 대상 DB 찾기 (30~70%)
        _log(f"2단계: DB 탐색 (대상: {target_db or '자동'})")
        found_server = ""
        found_db = ""

        for i, server in enumerate(instances):
            pct = 30 + int((i + 1) / len(instances) * 40)
            self.progress.emit(pct)

            try:
                probe_db = dict(base_db)
                probe_db["server"] = server
                probe_db["password_plain"] = plain_password
                conn_str = build_conn_str(probe_db, include_db=False)
                conn = pyodbc.connect(conn_str, timeout=3, readonly=True)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sys.databases "
                    "WHERE name NOT IN ('master','tempdb','model','msdb') "
                    "ORDER BY name"
                )
                dbs = [row[0] for row in cursor.fetchall()]
                conn.close()
                _log(f"  서버 {server}: DB 목록 = {dbs}")

                if target_db and target_db in dbs:
                    # 이팜: 정확한 DB명 매칭
                    found_server = server
                    found_db = target_db
                    break
                elif not target_db and self._program == "upharm":
                    # 유팜: 후보 우선순위대로 exact(대소문자 무시) 매칭
                    dbs_lower = {d.lower(): d for d in dbs}
                    for cand in UPHARM_DB_CANDIDATES:
                        if cand.lower() in dbs_lower:
                            found_server = server
                            found_db = dbs_lower[cand.lower()]
                            break
                    if found_server:
                        break
                elif not target_db and self._program == "it3000":
                    # IT3000: 힌트 기반 탐색
                    for db_name in dbs:
                        for hint in IT3000_DB_HINTS:
                            if hint.lower() in db_name.lower():
                                found_server = server
                                found_db = db_name
                                break
                        if found_db:
                            break
                    # 힌트 매칭 실패 시 시스템 DB 제외 첫 번째
                    if not found_db and dbs:
                        found_server = server
                        found_db = dbs[0]
                    if found_server:
                        break
                elif not target_db and dbs:
                    # 기타: 첫 번째 DB 사용
                    found_server = server
                    found_db = dbs[0]
                    break
            except Exception as e:
                _log(f"  서버 {server}: 연결 실패 - {e}")
                continue

        if not found_server:
            _log("  실패: 대상 DB를 찾을 수 없음")
            result["error"] = f"'{target_db or '사용 가능한'}' 데이터베이스를 찾을 수 없습니다"
            self.finished.emit(result)
            return

        _log(f"  DB 매칭 성공: {found_server}/{found_db}")
        self.progress.emit(75)

        # 3단계: 약국명 자동 조회 (70~100%)
        _log("3단계: 약국명 조회")
        pharmacy_name = ""
        try:
            name_db = dict(base_db)
            name_db["server"] = found_server
            name_db["database"] = found_db
            name_db["password_plain"] = plain_password
            conn_str = build_conn_str(name_db)
            conn = pyodbc.connect(conn_str, timeout=3, readonly=True)
            cursor = conn.cursor()

            # 이팜: Pharmacy 테이블에서 약국명 조회
            name_queries = [
                "SELECT TOP 1 ph_Name FROM Pharmacy",
                "SELECT TOP 1 yakguk_name FROM yakguk_info",
                "SELECT TOP 1 pharmacy_name FROM pharmacy_info",
            ]
            for q in name_queries:
                try:
                    cursor.execute(q)
                    row = cursor.fetchone()
                    if row and row[0]:
                        pharmacy_name = str(row[0]).strip()
                        break
                except Exception:
                    continue

            conn.close()
        except Exception as e:
            _log(f"  약국명 조회 실패: {e}")

        self.progress.emit(100)

        _log(f"완료: server={found_server}, db={found_db}, "
             f"pharmacy={pharmacy_name}, program={self._program}")

        result["success"] = True
        result["server"] = found_server
        result["database"] = found_db
        result["pharmacy_name"] = pharmacy_name
        result["full_support"] = self._program == "epharm"
        # 인증 정보 전달 (저장 단계에서 암호화)
        result["auth"] = self._auth_info.get("auth", "windows")
        result["username"] = self._auth_info.get("username", "")
        # 저장 단계에서 DPAPI로 암호화할 평문 비번 (메모리 통해 전달)
        result["_password_plain"] = plain_password
        self.finished.emit(result)


class SetupWizard(QDialog):
    """첫 실행 설치 마법사 — 간결한 UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PharmAuto 초기 설정")
        self.setMinimumSize(480, 400)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet("QDialog { background: white; }")
        self._setup_complete = False
        self._init_ui()
        self.adjustSize()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.setContentsMargins(44, 40, 44, 36)

        # 제목 + 원격 지원 버튼 (상시 노출)
        title_row = QHBoxLayout()
        title_row.setSpacing(12)

        title = QLabel("PharmAuto 초기 설정")
        title.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: #1A1A2E; "
            "font-family: 'Malgun Gothic';"
        )
        title.setMinimumHeight(32)
        title_row.addWidget(title)
        title_row.addStretch()

        remote_btn = QPushButton("원격 지원")
        remote_btn.setStyleSheet(
            "QPushButton { font-size: 12px; padding: 6px 14px; "
            "background: #EF4444; color: white; border: none; "
            "border-radius: 6px; font-weight: 600; "
            "font-family: 'Malgun Gothic'; }"
            "QPushButton:hover { background: #DC2626; }"
        )
        remote_btn.setToolTip("AnyDesk 실행 + ID 복사")
        remote_btn.clicked.connect(self._on_remote_support)
        title_row.addWidget(remote_btn)

        layout.addLayout(title_row)

        safety = QLabel(
            "읽기 전용으로 DB를 탐색합니다. 기존 프로그램에 영향을 주지 않습니다."
        )
        safety.setWordWrap(True)
        safety.setMinimumHeight(44)
        safety.setStyleSheet(
            "font-size: 12px; color: #22C55E; font-weight: 600; "
            "font-family: 'Malgun Gothic'; padding: 10px 14px; "
            "background: #F0FFF4; border-radius: 6px;"
        )
        layout.addWidget(safety)

        # 구분선
        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #DFE1E6;")
        layout.addWidget(line)

        # 약국 프로그램 선택
        prog_label = QLabel("사용 중인 약국 프로그램을 선택하세요")
        prog_label.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #1A1A2E; "
            "font-family: 'Malgun Gothic';"
        )
        prog_label.setMinimumHeight(24)
        layout.addWidget(prog_label)

        self._prog_group = QButtonGroup(self)
        self._prog_radios = {}
        for key, info in PHARMACY_PROGRAMS.items():
            radio = QRadioButton(info["label"])
            radio.setStyleSheet(
                "QRadioButton { font-size: 14px; font-family: 'Malgun Gothic'; "
                "padding: 8px 0; min-height: 20px; }"
            )
            radio.toggled.connect(self._on_program_changed)
            self._prog_group.addButton(radio)
            self._prog_radios[key] = radio
            layout.addWidget(radio)
        self._prog_radios["epharm"].setChecked(True)

        layout.addStretch()

        # 프로그레스 바 (처음에 숨김)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedHeight(20)
        self._progress_bar.setStyleSheet(
            "QProgressBar { border: none; background: #F2F3F5; border-radius: 4px; "
            "font-size: 11px; color: #4B6BFB; text-align: center; }"
            "QProgressBar::chunk { background: #4B6BFB; border-radius: 4px; }"
        )
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # 상태 메시지
        self._status = QLabel("")
        self._status.setStyleSheet(
            "font-size: 12px; color: #6B7280; font-family: 'Malgun Gothic';"
        )
        self._status.setVisible(False)
        layout.addWidget(self._status)

        # 하단 버튼
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._start_btn = QPushButton("설정 시작")
        self._start_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 10px 32px; "
            "background: #4B6BFB; color: white; border: none; "
            "border-radius: 8px; font-weight: 600; font-family: 'Malgun Gothic'; }"
            "QPushButton:hover { background: #3A56D4; }"
            "QPushButton:disabled { background: #CCC; }"
        )
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)

        layout.addLayout(btn_row)

    # ────── 자동 세팅 ──────

    def _selected_program(self) -> str:
        for key, radio in self._prog_radios.items():
            if radio.isChecked():
                return key
        return "epharm"

    def _on_program_changed(self):
        """프로그램 선택 변경 시 후속 처리 (현재는 no-op, 추후 확장용)."""
        pass

    def _on_start(self):
        prog = self._selected_program()
        auth_info = {"auth": "windows"}

        # 유팜: 내부에 하드코딩된 읽기전용 SQL 계정으로 자동 인증
        if prog == "upharm":
            auth_info = {
                "auth": "sql",
                "username": _UPHARM_SQL_USER,
                "password": _UPHARM_SQL_PASS,
            }

        # UI 잠금
        self._start_btn.setEnabled(False)
        for radio in self._prog_radios.values():
            radio.setEnabled(False)

        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._status.setVisible(True)
        self._status.setText("설정 중...")

        # 백그라운드 자동 세팅
        self._worker = AutoSetupWorker(prog, auth_info=auth_info)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, pct: int):
        self._progress_bar.setValue(pct)

    def _on_finished(self, result: dict):
        if result["success"]:
            self._progress_bar.setValue(100)
            self._save_settings(result)

            if result.get("full_support"):
                # 이팜: 바로 완료
                self._status.setText("설정 완료!")
                self._status.setStyleSheet(
                    "font-size: 13px; color: #22C55E; font-weight: 700; "
                    "font-family: 'Malgun Gothic';"
                )
                QTimer.singleShot(1000, self.accept)
            else:
                # 이팜 외: DB 연결은 됐지만 연동 준비 중 안내
                self._status.setText("DB 연결 성공!")
                self._status.setStyleSheet(
                    "font-size: 13px; color: #22C55E; font-weight: 700; "
                    "font-family: 'Malgun Gothic';"
                )
                QMessageBox.information(
                    self, "연동 안내",
                    f"DB 연결에 성공했습니다.\n\n"
                    f"현재 이 프로그램은 연동 준비 중입니다.\n"
                    f"설정 탭 → 'DB 구조 내보내기' 버튼을 눌러\n"
                    f"파일을 개발자에게 보내주시면\n"
                    f"빠르게 연동을 지원해드리겠습니다."
                )
                self.accept()
        else:
            self._progress_bar.setVisible(False)
            self._status.setText(result["error"])
            self._status.setStyleSheet(
                "font-size: 12px; color: #EF4444; font-family: 'Malgun Gothic';"
            )
            self._start_btn.setEnabled(True)
            self._start_btn.setText("다시 시도")
            for radio in self._prog_radios.values():
                radio.setEnabled(True)

            # 1) 바탕화면에 오류 로그 저장 (원격 지원용)
            desktop_log = self._save_log_to_desktop(result["error"])

            # 2) 서버에 자동 전송
            self._upload_setup_log(result["error"])

            # 3) 안내 + 로그 보내기 버튼
            log_msg = f"{result['error']}\n\n"
            if desktop_log:
                log_msg += (
                    f"오류 로그가 바탕화면에 저장되었습니다.\n"
                    f"({os.path.basename(desktop_log)})\n\n"
                )
            log_msg += (
                "오류 내용이 개발팀 서버로 자동 전송되었습니다.\n"
                "우측 상단 '원격 지원' 버튼으로 즉시 지원 요청도 가능합니다."
            )
            QMessageBox.warning(self, "설정 실패", log_msg)

            if not hasattr(self, "_send_log_btn"):
                self._send_log_btn = QPushButton("오류 로그 다시 보내기")
                self._send_log_btn.setStyleSheet(
                    "QPushButton { font-size: 12px; padding: 8px 20px; "
                    "background: #EF4444; color: white; border: none; "
                    "border-radius: 6px; font-weight: 600; "
                    "font-family: 'Malgun Gothic'; }"
                    "QPushButton:hover { background: #DC2626; }"
                )
                self._send_log_btn.clicked.connect(
                    lambda: self._upload_setup_log(result["error"], manual=True))
                self.layout().addWidget(self._send_log_btn)

    def _on_remote_support(self):
        """AnyDesk 실행 + ID 복사 (초기 설정 화면 어디서나 호출 가능)."""
        from core.remote_support import request_remote_support
        request_remote_support(self)

    def _save_log_to_desktop(self, error_msg: str) -> str:
        """설치 오류 로그를 바탕화면에 저장한다. 경로를 반환."""
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            dest = os.path.join(desktop, "PharmAuto_설치오류.txt")

            with open(dest, "w", encoding="utf-8") as f:
                from datetime import datetime
                f.write(f"PharmAuto 설치 오류 로그\n")
                f.write(f"시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"버전: {_get_version()}\n")
                f.write(f"프로그램: {self._selected_program()}\n")
                f.write(f"오류: {error_msg}\n")
                f.write(f"{'=' * 50}\n\n")

                # 설치 마법사 상세 로그 복사
                if os.path.exists(LOG_PATH):
                    with open(LOG_PATH, "r", encoding="utf-8") as log_f:
                        f.write(log_f.read())

            return dest
        except Exception:
            return ""

    def _upload_setup_log(self, error_msg: str, manual: bool = False):
        """설치 실패 로그를 Supabase에 업로드한다."""
        import threading

        def _upload():
            try:
                from core.cloud import _api_url, _headers
                import requests

                log_tail = ""
                if os.path.exists(LOG_PATH):
                    with open(LOG_PATH, "r", encoding="utf-8") as f:
                        log_tail = f.read()[-5000:]

                requests.post(
                    _api_url("error_logs"),
                    headers=_headers(),
                    json={
                        "pharmacy_code": "SETUP_FAIL",
                        "version": _get_version(),
                        "level": "SETUP_FAIL",
                        "message": error_msg[:500],
                        "context": {"program": self._selected_program()},
                        "log_tail": log_tail,
                    },
                    timeout=5,
                )
                if manual:
                    from PyQt6.QtCore import QMetaObject, Q_ARG
                    # UI 스레드에서 메시지 표시
                    QMetaObject.invokeMethod(
                        self._status, "setText",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, "오류 정보가 전송되었습니다"),
                    )
            except Exception:
                pass

        threading.Thread(target=_upload, daemon=True).start()

    def _save_settings(self, result: dict):
        settings = {}
        if os.path.exists(SETTINGS_PATH):
            try:
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    settings = json.load(f)
            except Exception:
                pass

        prog = self._selected_program()
        db_conf = {
            "server": result["server"],
            "database": result["database"],
            "driver": PHARMACY_PROGRAMS[prog]["driver"],
        }
        # SQL 인증이면 자격증명 암호화 저장
        if result.get("auth") == "sql":
            from core.crypto import encrypt
            db_conf["auth"] = "sql"
            db_conf["username"] = result.get("username", "")
            plain = result.get("_password_plain", "")
            db_conf["password"] = encrypt(plain) if plain else ""
        settings["db"] = db_conf
        settings["pharmacy_program"] = prog
        if result["pharmacy_name"]:
            settings["pharmacy_name"] = result["pharmacy_name"]
        settings["setup_complete"] = True

        # Supabase 클라우드 기본값 (에러 로그/셀렉터 공유에 필요)
        settings.setdefault(
            "supabase_url", "https://bvxcdgnuslxobcaqdtds.supabase.co")
        settings.setdefault(
            "supabase_key",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ2eGNkZ251c2x4b2JjYXFkdGRzIiwi"
            "cm9sZSI6ImFub24iLCJpYXQiOjE3NzU2MDE3MTYsImV4cCI6MjA5MTE3NzcxNn0."
            "_1KW_PBoHcW2nKyNQlkO-QngtaKKusAqZpi2XxZpHt0")

        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

        self._setup_complete = True

    @property
    def setup_complete(self) -> bool:
        return self._setup_complete


def needs_setup() -> bool:
    """초기 설정이 필요한지 확인한다."""
    if not os.path.exists(SETTINGS_PATH):
        return True
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
        return not settings.get("setup_complete", False)
    except Exception:
        return True
