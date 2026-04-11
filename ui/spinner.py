"""공용 로딩 오버레이 — 스피너 + 프로그레스바."""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ui.styles import BLUE, BLUE_DARK, TEXT_SEC


class SpinnerOverlay(QWidget):
    """화면 중앙 로딩 오버레이. 스피너 모드 / 프로그레스바 모드 지원."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._angle = 0
        self._message = "로딩 중..."
        self._progress = -1  # -1이면 스피너 모드, 0~100이면 프로그레스바
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self.hide()

    def show_with_message(self, msg: str = "로딩 중..."):
        self._message = msg
        self._progress = -1
        self.setGeometry(self.parent().rect())
        self._timer.start(30)
        self.show()
        self.raise_()

    def show_progress(self, msg: str = "처리 중...", percent: int = 0):
        """프로그레스바 모드로 표시."""
        self._message = msg
        self._progress = max(0, min(100, percent))
        self.setGeometry(self.parent().rect())
        if not self._timer.isActive():
            self._timer.start(30)
        self.show()
        self.raise_()

    def set_progress(self, percent: int, msg: str = ""):
        """프로그레스바 진행률 업데이트."""
        self._progress = max(0, min(100, percent))
        if msg:
            self._message = msg
        self.update()

    def hide_spinner(self):
        self._timer.stop()
        self._progress = -1
        self.hide()

    def set_message(self, msg: str):
        self._message = msg
        self.update()

    def _rotate(self):
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 반투명 배경
        painter.fillRect(self.rect(), QColor(255, 255, 255, 200))

        cx, cy = self.width() // 2, self.height() // 2

        if self._progress < 0:
            # 스피너 모드
            pen = QPen(QColor(220, 220, 224), 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(cx - 20, cy - 40, 40, 40, 0, 360 * 16)

            pen2 = QPen(QColor(BLUE), 4)
            pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen2)
            painter.drawArc(cx - 20, cy - 40, 40, 40, self._angle * 16, 90 * 16)
        else:
            # 프로그레스바 모드
            bar_w = min(300, self.width() - 80)
            bar_h = 8
            bar_x = cx - bar_w // 2
            bar_y = cy - 20

            # 배경
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(220, 220, 224))
            painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 4, 4)

            # 진행률
            fill_w = int(bar_w * self._progress / 100)
            if fill_w > 0:
                painter.setBrush(QColor(BLUE))
                painter.drawRoundedRect(bar_x, bar_y, fill_w, bar_h, 4, 4)

            # 퍼센트
            painter.setPen(QColor(BLUE_DARK))
            painter.setFont(QFont("Malgun Gothic", 14, QFont.Weight.Bold))
            painter.drawText(
                bar_x, bar_y - 30, bar_w, 25,
                Qt.AlignmentFlag.AlignCenter,
                f"{self._progress}%",
            )

        # 메시지
        painter.setPen(QColor(TEXT_SEC))
        painter.setFont(QFont("Malgun Gothic", 11))
        msg_y = cy + 10 if self._progress >= 0 else cy + 30
        painter.drawText(
            0, msg_y, self.width(), 30,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            self._message,
        )

    def resizeEvent(self, event):
        self.setGeometry(self.parent().rect())
