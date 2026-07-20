"""마우스 휠 스크롤 시 QComboBox/QSpinBox 값이 실수로 바뀌는 문제 차단.

문제: 테이블/스크롤 영역을 마우스 휠로 내릴 때,
QComboBox/QSpinBox 위에 커서가 걸치면 값이 바뀌어 버린다.
특히 처방 데이터 조회에서 행마다 있는 "추천주문량/도매상/자동제외"
위젯 위에서 이 현상이 심함.

app-level eventFilter 는 QTableWidget 의 cellWidget 에는 도달 못한다
(테이블이 먼저 가로챔). 따라서 서브클래스로 wheelEvent 를 직접 차단.

사용:
    from ui.wheel_filter import NoWheelComboBox, NoWheelSpinBox
    combo = NoWheelComboBox()
    spin = NoWheelSpinBox()
"""

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox


class NoWheelComboBox(QComboBox):
    """휠 이벤트를 항상 무시해서 부모 스크롤에 전달. 선택은 드롭다운으로."""

    def wheelEvent(self, e) -> None:
        e.ignore()


class NoWheelSpinBox(QSpinBox):
    """휠 이벤트를 항상 무시. 값 변경은 +/- 버튼 또는 키보드로."""

    def wheelEvent(self, e) -> None:
        e.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, e) -> None:
        e.ignore()


class WheelBlocker(QObject):
    """앱 전역 fallback — 테이블 밖 일반 combo/spin 용.
    cellWidget 은 위 subclass 로만 처리 가능."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Wheel:
            if isinstance(obj, (QComboBox, QSpinBox, QDoubleSpinBox)):
                if not obj.hasFocus():
                    event.ignore()
                    return True
        return super().eventFilter(obj, event)
