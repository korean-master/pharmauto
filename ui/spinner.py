"""공용 로딩 스피너 오버레이."""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ui.styles import BLUE, TEXT_SEC


class SpinnerOverlay(QWidget):
    """화면 중앙 로딩 스피너 오버레이."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._angle = 0
        self._message = "로딩 중..."
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self.hide()

    def show_with_message(self, msg: str = "로딩 중..."):
        self._message = msg
        self.setGeometry(self.parent().rect())
        self._timer.start(30)
        self.show()
        self.raise_()

    def hide_spinner(self):
        self._timer.stop()
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
        painter.fillRect(self.rect(), QColor(255, 255, 255, 180))

        cx, cy = self.width() // 2, self.height() // 2

        # 스피너 원
        pen = QPen(QColor(200, 200, 200), 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(cx - 20, cy - 40, 40, 40, 0, 360 * 16)

        # 회전하는 호
        pen2 = QPen(QColor(BLUE), 4)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen2)
        painter.drawArc(cx - 20, cy - 40, 40, 40, self._angle * 16, 90 * 16)

        # 메시지
        painter.setPen(QColor(TEXT_SEC))
        painter.setFont(QFont("Malgun Gothic", 11))
        painter.drawText(self.rect().adjusted(0, 30, 0, 0),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         self._message)

    def resizeEvent(self, event):
        self.setGeometry(self.parent().rect())
