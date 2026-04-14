"""PharmAuto 중앙 로깅 시스템.

1단계: 파일 로깅 (data/pharmauto.log)
2단계(미구현): Supabase 에러 자동 업로드 — upload_error() 호출부만 준비
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# 로그 파일 경로 — exe 빌드 시에도 data/ 폴더에 저장
if getattr(sys, 'frozen', False) or "__compiled__" in dir():
    _BASE = os.path.dirname(sys.executable)
    _DATA = os.path.join(_BASE, "data")
    if not os.path.exists(_DATA):
        _DATA = os.path.join(_BASE, "_internal", "data")
else:
    _DATA = os.path.join(os.path.dirname(__file__), "..", "data")

os.makedirs(_DATA, exist_ok=True)
LOG_PATH = os.path.join(_DATA, "pharmauto.log")

# 로거 설정
_logger = logging.getLogger("pharmauto")
_logger.setLevel(logging.DEBUG)

# 파일 핸들러 — 5MB x 3개 순환
_file_handler = RotatingFileHandler(
    LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3,
    encoding="utf-8"
)
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(
    "[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
_logger.addHandler(_file_handler)

# 콘솔 핸들러 — 개발 시 print 대체
_console = logging.StreamHandler(sys.stdout)
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_console)


def get_logger() -> logging.Logger:
    return _logger


def get_log_path() -> str:
    return LOG_PATH


# ── 2단계 준비: Supabase 에러 업로드 스텁 ──

def upload_error(level: str, message: str, context: dict | None = None):
    """에러를 Supabase에 업로드한다. (2단계 구현 예정)

    호출 예시:
        upload_error("ERROR", "백제약품 로그인 실패", {"wholesaler": "baekje"})

    구현 시 포함할 것:
        - 약국 활성화 코드 (식별용)
        - 앱 버전
        - 타임스탬프
        - 에러 레벨/메시지/컨텍스트
    """
    # TODO: 2단계에서 구현
    # from core.auth import get_activation_code
    # from core.version import VERSION
    # from core.cloud import get_supabase
    # supabase = get_supabase()
    # supabase.table("error_logs").insert({
    #     "pharmacy_code": get_activation_code(),
    #     "version": VERSION,
    #     "level": level,
    #     "message": message[:500],
    #     "context": context or {},
    # }).execute()
    pass


def setup_global_logging():
    """print()와 미처리 예외를 로그 파일로 리다이렉트한다."""

    class _LogWriter:
        """print() 출력을 로거로 전달하는 스트림 래퍼."""
        def __init__(self, logger, level, original):
            self._logger = logger
            self._level = level
            self._original = original
            self._buf = ""

        def write(self, msg):
            if self._original:
                try:
                    self._original.write(msg)
                except Exception:
                    pass
            if msg and msg.strip():
                self._logger.log(self._level, msg.rstrip())

        def flush(self):
            if self._original:
                try:
                    self._original.flush()
                except Exception:
                    pass

    # stdout/stderr → 로그 파일 + 원본 콘솔
    sys.stdout = _LogWriter(_logger, logging.INFO, sys.__stdout__)
    sys.stderr = _LogWriter(_logger, logging.ERROR, sys.__stderr__)

    # 미처리 예외 → 로그 파일
    def _exception_hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _logger.critical(
            "미처리 예외 발생", exc_info=(exc_type, exc_value, exc_tb)
        )
        # 2단계: 심각한 에러 자동 업로드
        # upload_error("CRITICAL", str(exc_value), {
        #     "type": exc_type.__name__,
        #     "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
        # })

    sys.excepthook = _exception_hook
