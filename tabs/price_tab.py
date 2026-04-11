"""일반약 가격비교 탭 - 크라우드소싱 기반 OTC 약품 시세 비교."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QLinearGradient
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.styles import (
    BLUE as _BLUE,
    GREEN as _GREEN,
    RED as _RED,
    ORANGE as _ORANGE,
    TEXT as _TEXT,
    TEXT_SEC as _TEXT_SEC,
    BORDER as _BORDER,
    CARD as _CARD,
)

# ━━━━━━━━━━━━━━━━━━━ 색상 토큰 ━━━━━━━━━━━━━━━━━━━

_PRIMARY = "#1D9E75"
_PRIMARY_DARK = "#178A66"
_PRIMARY_LIGHT = "#E8F7F1"

_STAT_NEARBY = "#1D9E75"     # 반경 1km
_STAT_GU = "#0EA5E9"         # 구
_STAT_CITY = _BLUE           # 시/도
_STAT_NATION = _ORANGE       # 전국
_STAT_MY = "#8B5CF6"         # 내 가격

_BAR_NORMAL = "#D1FAE5"
_BAR_HIGHLIGHT = "#1D9E75"

# ━━━━━━━━━━━━━━━━━━━ 지역 데이터 ━━━━━━━━━━━━━━━━━━━

REGIONS: dict[str, list[str]] = {
    "서울특별시": [
        "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구",
        "금천구", "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구",
        "서초구", "성동구", "성북구", "송파구", "양천구", "영등포구", "용산구",
        "은평구", "종로구", "중구", "중랑구",
    ],
    "부산광역시": [
        "강서구", "금정구", "기장군", "남구", "동구", "동래구", "부산진구",
        "북구", "사상구", "사하구", "서구", "수영구", "연제구", "영도구",
        "중구", "해운대구",
    ],
    "대구광역시": [
        "남구", "달서구", "달성군", "동구", "북구", "서구", "수성구", "중구",
    ],
    "인천광역시": [
        "강화군", "계양구", "남동구", "동구", "미추홀구", "부평구", "서구",
        "연수구", "옹진군", "중구",
    ],
    "광주광역시": ["광산구", "남구", "동구", "북구", "서구"],
    "대전광역시": ["대덕구", "동구", "서구", "유성구", "중구"],
    "울산광역시": ["남구", "동구", "북구", "울주군", "중구"],
    "세종특별자치시": ["세종시"],
    "경기도": [
        "가평군", "고양시", "과천시", "광명시", "광주시", "구리시", "군포시",
        "김포시", "남양주시", "동두천시", "부천시", "성남시", "수원시", "시흥시",
        "안산시", "안성시", "안양시", "양주시", "양평군", "여주시", "연천군",
        "오산시", "용인시", "의왕시", "의정부시", "이천시", "파주시", "평택시",
        "포천시", "하남시", "화성시",
    ],
    "강원특별자치도": [
        "강릉시", "고성군", "동해시", "삼척시", "속초시", "양구군", "양양군",
        "영월군", "원주시", "인제군", "정선군", "철원군", "춘천시", "태백시",
        "평창군", "홍천군", "화천군", "횡성군",
    ],
    "충청북도": [
        "괴산군", "단양군", "보은군", "영동군", "옥천군", "음성군", "제천시",
        "증평군", "진천군", "청주시", "충주시",
    ],
    "충청남도": [
        "계룡시", "공주시", "금산군", "논산시", "당진시", "보령시", "부여군",
        "서산시", "서천군", "아산시", "예산군", "천안시", "청양군", "태안군",
        "홍성군",
    ],
    "전북특별자치도": [
        "고창군", "군산시", "김제시", "남원시", "무주군", "부안군", "순창군",
        "완주군", "익산시", "임실군", "장수군", "전주시", "정읍시", "진안군",
    ],
    "전라남도": [
        "강진군", "고흥군", "곡성군", "광양시", "구례군", "나주시", "담양군",
        "목포시", "무안군", "보성군", "순천시", "신안군", "여수시", "영광군",
        "영암군", "완도군", "장성군", "장흥군", "진도군", "함평군", "해남군",
        "화순군",
    ],
    "경상북도": [
        "경산시", "경주시", "고령군", "구미시", "군위군", "김천시", "문경시",
        "봉화군", "상주시", "성주군", "안동시", "영덕군", "영양군", "영주시",
        "영천시", "예천군", "울릉군", "울진군", "의성군", "청도군", "청송군",
        "칠곡군", "포항시",
    ],
    "경상남도": [
        "거제시", "거창군", "고성군", "김해시", "남해군", "밀양시", "사천시",
        "산청군", "양산시", "의령군", "진주시", "창녕군", "창원시", "통영시",
        "하동군", "함안군", "함양군", "합천군",
    ],
    "제주특별자치도": ["제주시", "서귀포시"],
}


# ━━━━━━━━━━━━━━━━━━━ 데모 데이터 ━━━━━━━━━━━━━━━━━━━

def _make_sub_dist(base: list[int], ratio: float, jitter: int = 200) -> list[int]:
    """base 분포에서 일부를 추출해 작은 분포를 만든다."""
    import random
    r = random.Random(42)
    n = max(3, int(len(base) * ratio))
    sample = r.sample(base, min(n, len(base)))
    return sorted([p + r.randint(-jitter, jitter) for p in sample])


def _build_demo_prices(national: list[int]) -> dict:
    """전국 분포에서 시/구/1km 분포를 파생한다."""
    city = _make_sub_dist(national, 0.5, 150)
    gu = _make_sub_dist(city, 0.5, 100)
    nearby = _make_sub_dist(gu, 0.6, 50)
    return {
        "nearby_avg": sum(nearby) // len(nearby) if nearby else 0,
        "nearby_count": len(nearby),
        "nearby_dist": nearby,
        "gu_avg": sum(gu) // len(gu) if gu else 0,
        "gu_count": len(gu),
        "gu_dist": gu,
        "city_avg": sum(city) // len(city) if city else 0,
        "city_count": len(city),
        "city_dist": city,
        "national_avg": sum(national) // len(national) if national else 0,
        "national_count": len(national),
        "national_dist": national,
    }


DEMO_DRUGS = {
    "둘코락스": {
        "specs": ["20정", "40정", "좌제 10개"],
        "prices": {
            "20정": _build_demo_prices(
                [7000, 7200, 7500, 7500, 7800, 7900, 8000, 8000,
                 8200, 8200, 8300, 8500, 8500, 8700, 9000, 9200,
                 9500, 9800, 10000, 10500]),
            "40정": _build_demo_prices(
                [12000, 12500, 13000, 13000, 13200, 13500, 13500,
                 13800, 14000, 14000, 14200, 14500, 15000, 15500,
                 16000, 16500]),
            "좌제 10개": _build_demo_prices(
                [9500, 10000, 10000, 10500, 10500, 11000, 11000,
                 11500, 12000, 12500]),
        },
    },
    "타이레놀": {
        "specs": ["10정", "20정", "ER 서방정 24정"],
        "prices": {
            "10정": _build_demo_prices(
                [3000, 3200, 3500, 3500, 3800, 3800, 4000, 4000,
                 4000, 4200, 4200, 4500, 4500, 4800, 5000, 5500]),
            "20정": _build_demo_prices(
                [5500, 6000, 6000, 6500, 6500, 6700, 6700, 7000,
                 7000, 7200, 7200, 7500, 7500, 8000, 8500, 9000]),
            "ER 서방정 24정": _build_demo_prices(
                [10000, 10500, 11000, 11500, 11800, 12000, 12000,
                 12500, 13000, 13500, 14000, 14500]),
        },
    },
    "게보린": {
        "specs": ["10정", "20정"],
        "prices": {
            "10정": _build_demo_prices(
                [2800, 3000, 3000, 3200, 3200, 3500, 3500, 3500,
                 3800, 3800, 3800, 4000, 4000, 4200, 4500, 5000]),
            "20정": _build_demo_prices(
                [5000, 5200, 5500, 5500, 5800, 6000, 6000, 6200,
                 6200, 6500, 6500, 6800, 7000, 7500, 8000]),
        },
    },
}


# ━━━━━━━━━━━━━━━━━━━ 위젯 헬퍼 ━━━━━━━━━━━━━━━━━━━

def _card(radius: int = 16) -> str:
    return f"QFrame {{ background: {_CARD}; border-radius: {radius}px; border: none; }}"


def _shadow(widget: QWidget, blur: int = 20, dy: int = 4, opacity: int = 25):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(0, 0, 0, opacity))
    widget.setGraphicsEffect(eff)


_COMBO_STYLE = f"""
    QComboBox {{
        padding: 10px 14px; border: 2px solid {_BORDER};
        border-radius: 10px; font-size: 13px; background: {_CARD};
        font-family: 'Malgun Gothic'; min-width: 140px;
    }}
    QComboBox:focus {{ border-color: {_PRIMARY}; }}
    QComboBox::drop-down {{ border: none; padding-right: 8px; }}
    QComboBox QAbstractItemView {{
        border: 1px solid {_BORDER}; border-radius: 6px;
        background: {_CARD}; selection-background-color: {_PRIMARY_LIGHT};
        selection-color: {_PRIMARY}; padding: 4px; outline: none;
    }}
"""


# ━━━━━━━━━━━━━━━━━━━ 분포 차트 위젯 ━━━━━━━━━━━━━━━━━━━

class DistributionChart(QWidget):
    """히스토그램 형태의 가격 분포 차트 (타이틀·색상 커스텀)."""

    def __init__(self, title: str = "", bar_color: str = _BAR_HIGHLIGHT,
                 bar_bg: str = _BAR_NORMAL, parent=None):
        super().__init__(parent)
        self._title = title
        self._bar_color = bar_color
        self._bar_bg = bar_bg
        self._prices: list[int] = []
        self._my_price: int | None = None
        self._bins: list[int] = []
        self._counts: list[int] = []
        self._avg: int | None = None
        self._avg_label: str = "평균"
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, prices: list[int], my_price: int | None = None,
                 avg: int | None = None, avg_label: str = "평균"):
        self._prices = sorted(prices)
        self._my_price = my_price
        self._avg = avg
        self._avg_label = avg_label
        self._compute_bins()
        self.update()

    def clear(self):
        self._prices, self._bins, self._counts = [], [], []
        self._my_price = None
        self._avg = None
        self.update()

    def _compute_bins(self):
        if not self._prices:
            self._bins, self._counts = [], []
            return
        lo, hi = self._prices[0], self._prices[-1]
        if lo == hi:
            self._bins, self._counts = [lo], [len(self._prices)]
            return
        n_bins = min(10, max(4, len(self._prices) // 3))
        step = max(1, (hi - lo) // n_bins + 1)
        self._bins, self._counts = [], []
        edge = lo
        while edge <= hi:
            upper = edge + step
            cnt = sum(1 for p in self._prices if edge <= p < upper)
            self._bins.append(edge)
            self._counts.append(cnt)
            edge = upper
        if self._counts:
            self._counts[-1] += sum(
                1 for p in self._prices if p == hi and hi >= edge - step
            )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        margin_l, margin_r, margin_t, margin_b = 50, 16, 28, 32
        chart_w = w - margin_l - margin_r
        chart_h = h - margin_t - margin_b

        # 타이틀
        if self._title:
            painter.setPen(QColor(_TEXT))
            painter.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
            painter.drawText(8, 16, self._title)

        if not self._counts:
            painter.setPen(QColor(_TEXT_SEC))
            painter.setFont(QFont("Malgun Gothic", 10))
            painter.drawText(w // 2 - 30, h // 2, "데이터 없음")
            painter.end()
            return

        max_count = max(self._counts) or 1
        n = len(self._counts)
        bar_gap = 2
        bar_w = max(6, (chart_w - bar_gap * (n - 1)) // n)

        for i, cnt in enumerate(self._counts):
            bar_h = int(chart_h * cnt / max_count) if max_count > 0 else 0
            x = margin_l + i * (bar_w + bar_gap)
            y = margin_t + chart_h - bar_h

            is_my_bin = False
            if self._my_price is not None and i < len(self._bins):
                step = self._bins[1] - self._bins[0] if len(self._bins) > 1 else 1
                if self._bins[i] <= self._my_price < self._bins[i] + step:
                    is_my_bin = True
                elif i == n - 1 and self._my_price >= self._bins[i]:
                    is_my_bin = True

            if is_my_bin:
                grad = QLinearGradient(x, y, x, y + bar_h)
                grad.setColorAt(0, QColor(_STAT_MY))
                grad.setColorAt(1, QColor("#A78BFA"))
                painter.setBrush(QBrush(grad))
            else:
                grad = QLinearGradient(x, y, x, y + bar_h)
                grad.setColorAt(0, QColor(self._bar_color))
                grad.setColorAt(1, QColor(self._bar_bg))
                painter.setBrush(QBrush(grad))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(x, y, bar_w, bar_h, 2, 2)

        # X축 라벨
        painter.setPen(QPen(QColor(_TEXT_SEC)))
        painter.setFont(QFont("Malgun Gothic", 8))
        label_y = margin_t + chart_h + 14
        for i in ([0, n // 2, n - 1] if n > 2 else [0, n - 1] if n > 1 else [0]):
            x = margin_l + i * (bar_w + bar_gap)
            painter.drawText(x, label_y, f"{self._bins[i]:,}")

        # Y축 가이드
        for ratio in [0, 0.5, 1.0]:
            y = int(margin_t + chart_h * ratio)
            painter.setPen(QPen(QColor(_BORDER), 1, Qt.PenStyle.DotLine))
            painter.drawLine(margin_l, y, w - margin_r, y)

        # 내 가격 마커
        if self._my_price is not None and len(self._bins) > 0:
            lo = self._bins[0]
            step = self._bins[1] - self._bins[0] if len(self._bins) > 1 else 1
            hi_edge = self._bins[-1] + step
            total_range = hi_edge - lo
            if total_range > 0:
                ratio = (self._my_price - lo) / total_range
                mx = margin_l + int(chart_w * ratio)
                painter.setPen(QPen(QColor(_STAT_MY), 2, Qt.PenStyle.DashLine))
                painter.drawLine(mx, margin_t, mx, margin_t + chart_h)
                painter.setPen(QColor(_STAT_MY))
                painter.setFont(QFont("Malgun Gothic", 8, QFont.Weight.Bold))
                painter.drawText(mx - 16, margin_t - 4, "내 가격")

        # 평균 마커
        if self._avg is not None and len(self._bins) > 0:
            lo = self._bins[0]
            step = self._bins[1] - self._bins[0] if len(self._bins) > 1 else 1
            hi_edge = self._bins[-1] + step
            total_range = hi_edge - lo
            if total_range > 0:
                ratio = (self._avg - lo) / total_range
                ax = margin_l + int(chart_w * ratio)
                painter.setPen(QPen(QColor(self._bar_color), 2, Qt.PenStyle.DashDotLine))
                painter.drawLine(ax, margin_t, ax, margin_t + chart_h)
                # 평균 라벨
                painter.setPen(QColor(self._bar_color))
                painter.setFont(QFont("Malgun Gothic", 8, QFont.Weight.Bold))
                label_text = f"{self._avg_label} {self._avg:,}원"
                # 오른쪽 넘치면 왼쪽에 표시
                text_w = len(label_text) * 7
                lx = ax + 4 if ax + text_w < w - margin_r else ax - text_w - 4
                painter.drawText(lx, margin_t + chart_h + 26, label_text)

        # 데이터 건수
        painter.setPen(QColor(_TEXT_SEC))
        painter.setFont(QFont("Malgun Gothic", 8))
        painter.drawText(w - margin_r - 50, h - 4, f"{len(self._prices)}건")

        painter.end()


# ━━━━━━━━━━━━━━━━━━━ 스탯 카드 위젯 ━━━━━━━━━━━━━━━━━━━

class _StatCard(QFrame):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setStyleSheet(f"""
            QFrame {{
                background: {_CARD};
                border: 1px solid {_BORDER};
                border-radius: 12px;
                border-left: 4px solid {color};
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(2)

        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"font-size: 11px; color: {_TEXT_SEC}; font-weight: 600; border: none;"
        )
        lay.addWidget(self._label)

        self._price = QLabel("-")
        self._price.setStyleSheet(
            f"font-size: 20px; font-weight: 800; color: {color}; border: none;"
        )
        lay.addWidget(self._price)

        self._count = QLabel("")
        self._count.setStyleSheet(
            f"font-size: 10px; color: {_TEXT_SEC}; border: none;"
        )
        lay.addWidget(self._count)

    def set_value(self, price: int, count: int):
        self._price.setText(f"{price:,}원")
        self._count.setText(f"{count}건")

    def clear_value(self):
        self._price.setText("-")
        self._count.setText("")


# ━━━━━━━━━━━━━━━━━━━ 백분위 바 ━━━━━━━━━━━━━━━━━━━

class _PercentileBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pct: float | None = None
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_percentile(self, pct: float):
        self._pct = pct
        self.update()

    def clear(self):
        self._pct = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        bar_h, bar_y, margin = 14, 28, 20

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#E5E7EB"))
        painter.drawRoundedRect(margin, bar_y, w - margin * 2, bar_h, 7, 7)

        if self._pct is not None:
            fill_w = max(1, int((w - margin * 2) * self._pct / 100))
            grad = QLinearGradient(margin, 0, margin + fill_w, 0)
            grad.setColorAt(0, QColor(_GREEN))
            grad.setColorAt(0.5, QColor(_ORANGE))
            grad.setColorAt(1, QColor(_RED))
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(margin, bar_y, fill_w, bar_h, 7, 7)

            mx = margin + fill_w
            painter.setBrush(QColor(_STAT_MY))
            painter.drawEllipse(mx - 8, bar_y - 3, 16, bar_h + 6)

            painter.setPen(QColor("white"))
            painter.setFont(QFont("Malgun Gothic", 8, QFont.Weight.Bold))
            txt = f"{int(self._pct)}"
            painter.drawText(mx - (len(txt) * 3), bar_y + bar_h - 2, txt)

            painter.setPen(QColor(_TEXT))
            painter.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
            label = (f"상위 {int(self._pct)}%" if self._pct <= 50
                     else f"하위 {int(100 - self._pct)}%")
            painter.drawText(margin, 18, label)

        painter.setPen(QColor(_TEXT_SEC))
        painter.setFont(QFont("Malgun Gothic", 9))
        painter.drawText(margin, h - 2, "저렴")
        painter.drawText(w - margin - 24, h - 2, "비쌈")
        painter.end()


# ━━━━━━━━━━━━━━━━━━━ 규격 토글 버튼 ━━━━━━━━━━━━━━━━━━━

class _SpecToggle(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setMinimumWidth(70)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()
        self.toggled.connect(lambda: self._update_style())

    def _update_style(self):
        if self.isChecked():
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {_PRIMARY}; color: white;
                    padding: 8px 20px; border-radius: 20px;
                    font-weight: 700; font-size: 13px; border: none;
                }}
                QPushButton:hover {{ background: {_PRIMARY_DARK}; }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {_PRIMARY_LIGHT}; color: {_PRIMARY};
                    padding: 8px 20px; border-radius: 20px;
                    font-weight: 600; font-size: 13px; border: none;
                }}
                QPushButton:hover {{ background: #D1F0E4; }}
            """)


# ━━━━━━━━━━━━━━━━━━━ 메인 탭 ━━━━━━━━━━━━━━━━━━━

class PriceTab(QWidget):
    def __init__(self):
        super().__init__()
        self._current_drug: str | None = None
        self._current_spec: str | None = None
        self._my_price: int | None = None
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        outer.addWidget(scroll)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        layout.addWidget(self._build_search_card())

        self._spec_card = self._build_spec_card()
        self._spec_card.setVisible(False)
        layout.addWidget(self._spec_card)

        self._input_card = self._build_input_card()
        self._input_card.setVisible(False)
        layout.addWidget(self._input_card)

        self._result_card = self._build_result_card()
        self._result_card.setVisible(False)
        layout.addWidget(self._result_card)

        self._empty_guide = self._build_empty_guide()
        layout.addWidget(self._empty_guide)

        layout.addStretch()

    # ── 1. 검색 카드 ──

    def _build_search_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(_card())
        _shadow(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        # 타이틀
        title_row = QHBoxLayout()
        title = QLabel("일반약 가격비교")
        title.setStyleSheet(
            f"font-size: 20px; font-weight: 800; color: {_TEXT}; background: transparent;"
        )
        title_row.addWidget(title)
        title_row.addStretch()
        lay.addLayout(title_row)

        sub = QLabel("약품과 지역을 선택하면 주변 시세와 비교합니다")
        sub.setStyleSheet(
            f"color: {_TEXT_SEC}; font-size: 13px; background: transparent;"
        )
        lay.addWidget(sub)

        # 검색 + 지역 선택 행
        input_row = QHBoxLayout()
        input_row.setSpacing(10)

        # 약품명 입력
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("약품명 (예: 둘코락스, 타이레놀)")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                padding: 10px 14px; border: 2px solid {_BORDER};
                border-radius: 10px; font-size: 14px; background: {_CARD};
            }}
            QLineEdit:focus {{ border-color: {_PRIMARY}; }}
        """)
        self.search_input.returnPressed.connect(self._on_search)
        input_row.addWidget(self.search_input, 3)

        # 시/도 콤보
        self._city_combo = QComboBox()
        self._city_combo.setStyleSheet(_COMBO_STYLE)
        self._city_combo.addItem("시/도 선택")
        for city in REGIONS:
            self._city_combo.addItem(city)
        self._city_combo.currentIndexChanged.connect(self._on_city_changed)
        input_row.addWidget(self._city_combo, 2)

        # 구/군 콤보
        self._gu_combo = QComboBox()
        self._gu_combo.setStyleSheet(_COMBO_STYLE)
        self._gu_combo.addItem("구/군 선택")
        self._gu_combo.setEnabled(False)
        input_row.addWidget(self._gu_combo, 2)

        # 검색 버튼
        search_btn = QPushButton("검색")
        search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        search_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_PRIMARY}; color: white; padding: 10px 28px;
                border-radius: 10px; font-weight: 700; font-size: 14px; border: none;
            }}
            QPushButton:hover {{ background: {_PRIMARY_DARK}; }}
        """)
        search_btn.clicked.connect(self._on_search)
        input_row.addWidget(search_btn)

        lay.addLayout(input_row)

        # 선택된 지역 뱃지
        self._location_badge = QLabel("")
        self._location_badge.setStyleSheet(f"""
            background: {_PRIMARY_LIGHT}; color: {_PRIMARY};
            padding: 4px 14px; border-radius: 10px;
            font-size: 11px; font-weight: 600;
        """)
        self._location_badge.setVisible(False)
        lay.addWidget(self._location_badge)

        # 검색 상태
        self._search_status = QLabel("")
        self._search_status.setStyleSheet(
            f"color: {_TEXT_SEC}; font-size: 12px; background: transparent;"
        )
        self._search_status.setVisible(False)
        lay.addWidget(self._search_status)

        return card

    def _on_city_changed(self, index: int):
        self._gu_combo.clear()
        self._gu_combo.addItem("구/군 선택")
        if index <= 0:
            self._gu_combo.setEnabled(False)
            self._location_badge.setVisible(False)
            return
        city = self._city_combo.currentText()
        gus = REGIONS.get(city, [])
        for g in gus:
            self._gu_combo.addItem(g)
        self._gu_combo.setEnabled(True)
        self._update_location_badge()

    def _update_location_badge(self):
        city = self._city_combo.currentText() if self._city_combo.currentIndex() > 0 else ""
        gu = self._gu_combo.currentText() if self._gu_combo.currentIndex() > 0 else ""
        if city:
            # 긴 이름 축약
            short = city.replace("특별시", "").replace("광역시", "").replace("특별자치시", "").replace("특별자치도", "")
            text = f"  {short} {gu}  " if gu else f"  {short}  "
            self._location_badge.setText(text)
            self._location_badge.setVisible(True)
        else:
            self._location_badge.setVisible(False)

    # ── 2. 규격 선택 카드 ──

    def _build_spec_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(_card())
        _shadow(card, blur=15, dy=3, opacity=20)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 20, 28, 20)
        lay.setSpacing(12)

        self._drug_name_label = QLabel("")
        self._drug_name_label.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {_TEXT}; background: transparent;"
        )
        lay.addWidget(self._drug_name_label)

        spec_label = QLabel("규격 선택")
        spec_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {_TEXT_SEC}; background: transparent;"
        )
        lay.addWidget(spec_label)

        self._spec_row = QHBoxLayout()
        self._spec_row.setSpacing(8)
        self._spec_group = QButtonGroup(self)
        self._spec_group.setExclusive(True)
        lay.addLayout(self._spec_row)

        self._spec_buttons: list[_SpecToggle] = []
        return card

    # ── 3. 가격 입력 카드 ──

    def _build_input_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(_card())
        _shadow(card, blur=15, dy=3, opacity=20)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 20, 28, 20)
        lay.setSpacing(12)

        input_title = QLabel("내 약국 판매가")
        input_title.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {_TEXT}; background: transparent;"
        )
        lay.addWidget(input_title)

        price_row = QHBoxLayout()
        price_row.setSpacing(10)

        self._price_input = QLineEdit()
        self._price_input.setPlaceholderText("판매가 입력 (원)")
        self._price_input.setStyleSheet(f"""
            QLineEdit {{
                padding: 12px 16px; border: 2px solid {_BORDER};
                border-radius: 12px; font-size: 16px; font-weight: 700;
                background: {_CARD};
            }}
            QLineEdit:focus {{ border-color: {_PRIMARY}; }}
        """)
        self._price_input.setMaximumWidth(240)
        self._price_input.returnPressed.connect(self._on_price_submit)
        price_row.addWidget(self._price_input)

        won_label = QLabel("원")
        won_label.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {_TEXT_SEC}; background: transparent;"
        )
        price_row.addWidget(won_label)

        submit_btn = QPushButton("비교하기")
        submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        submit_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_PRIMARY}; color: white; padding: 12px 28px;
                border-radius: 12px; font-weight: 700; font-size: 14px; border: none;
            }}
            QPushButton:hover {{ background: {_PRIMARY_DARK}; }}
        """)
        submit_btn.clicked.connect(self._on_price_submit)
        price_row.addWidget(submit_btn)
        price_row.addStretch()
        lay.addLayout(price_row)

        privacy = QLabel("정확한 약국 위치는 저장되지 않으며, 가격 비교에만 이용됩니다")
        privacy.setStyleSheet(
            f"color: {_TEXT_SEC}; font-size: 11px; background: transparent; padding: 4px 0;"
        )
        lay.addWidget(privacy)
        return card

    # ── 4. 비교 결과 카드 ──

    def _build_result_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(_card())
        _shadow(card, blur=20, dy=4, opacity=25)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        # 헤더
        header = QHBoxLayout()
        result_title = QLabel("비교 결과")
        result_title.setStyleSheet(
            f"font-size: 17px; font-weight: 800; color: {_TEXT}; background: transparent;"
        )
        header.addWidget(result_title)
        header.addStretch()

        self._result_spec_label = QLabel("")
        self._result_spec_label.setStyleSheet(f"""
            background: {_PRIMARY_LIGHT}; color: {_PRIMARY};
            padding: 4px 14px; border-radius: 10px;
            font-size: 12px; font-weight: 600;
        """)
        header.addWidget(self._result_spec_label)
        lay.addLayout(header)

        # 내 가격 + 백분위
        self._my_price_label = QLabel("")
        self._my_price_label.setStyleSheet(f"""
            font-size: 28px; font-weight: 800; color: {_STAT_MY};
            background: transparent; padding: 4px 0;
        """)
        lay.addWidget(self._my_price_label)

        self._pct_bar = _PercentileBar()
        lay.addWidget(self._pct_bar)

        # 구분선
        sep1 = QFrame()
        sep1.setFixedHeight(1)
        sep1.setStyleSheet(f"background: {_BORDER};")
        lay.addWidget(sep1)

        # 평균 가격 4개 카드
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self._stat_nearby = _StatCard("반경 1km", _STAT_NEARBY)
        self._stat_gu = _StatCard("구 평균", _STAT_GU)
        self._stat_city = _StatCard("시/도 평균", _STAT_CITY)
        self._stat_nation = _StatCard("전국 평균", _STAT_NATION)
        stats_row.addWidget(self._stat_nearby)
        stats_row.addWidget(self._stat_gu)
        stats_row.addWidget(self._stat_city)
        stats_row.addWidget(self._stat_nation)
        lay.addLayout(stats_row)

        # 구분선
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {_BORDER};")
        lay.addWidget(sep2)

        # 분포 차트 4개 (2×2 그리드, 개별 카드)
        chart_section_label = QLabel("가격 분포")
        chart_section_label.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {_TEXT}; background: transparent;"
        )
        lay.addWidget(chart_section_label)

        self._chart_nearby = DistributionChart(
            "", bar_color=_STAT_NEARBY, bar_bg="#D1FAE5")
        self._chart_gu = DistributionChart(
            "", bar_color=_STAT_GU, bar_bg="#E0F2FE")
        self._chart_city = DistributionChart(
            "", bar_color=_STAT_CITY, bar_bg="#DDE4FF")
        self._chart_nation = DistributionChart(
            "", bar_color=_STAT_NATION, bar_bg="#FEF3C7")

        self._chart_titles: dict[str, QLabel] = {}
        chart_info = [
            ("nearby", "반경 1km 분포", _STAT_NEARBY, self._chart_nearby),
            ("gu", "구 분포", _STAT_GU, self._chart_gu),
            ("city", "시/도 분포", _STAT_CITY, self._chart_city),
            ("nation", "전국 분포", _STAT_NATION, self._chart_nation),
        ]

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(24)

        for idx, (key, title_text, color, chart) in enumerate(chart_info):
            wrapper = QFrame()
            wrapper.setStyleSheet(f"""
                QFrame {{
                    background: #FAFBFC;
                    border: 1px solid {_BORDER};
                    border-radius: 12px;
                    border-top: 3px solid {color};
                }}
            """)
            w_lay = QVBoxLayout(wrapper)
            w_lay.setContentsMargins(16, 14, 16, 12)
            w_lay.setSpacing(8)

            title_label = QLabel(title_text)
            title_label.setStyleSheet(f"""
                font-size: 13px; font-weight: 700; color: {color};
                background: transparent; border: none;
            """)
            self._chart_titles[key] = title_label
            w_lay.addWidget(title_label)

            chart.setStyleSheet("background: transparent;")
            w_lay.addWidget(chart)

            row, col = divmod(idx, 2)
            grid.addWidget(wrapper, row, col)

        lay.addLayout(grid)

        return card

    # ── 5. 빈 상태 안내 ──

    def _build_empty_guide(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(_card())
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 40, 28, 40)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        guide_title = QLabel("약품을 검색해보세요")
        guide_title.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {_TEXT}; background: transparent;"
        )
        guide_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(guide_title)

        guide_desc = QLabel(
            "약품명과 지역을 선택한 뒤 내 가격을 입력하면\n주변 시세와 비교할 수 있습니다"
        )
        guide_desc.setStyleSheet(
            f"color: {_TEXT_SEC}; font-size: 13px; background: transparent;"
        )
        guide_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(guide_desc)

        hot_label = QLabel("인기 검색")
        hot_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {_TEXT_SEC};"
            f" background: transparent; padding-top: 12px;"
        )
        hot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(hot_label)

        hot_row = QHBoxLayout()
        hot_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hot_row.setSpacing(8)
        for name in ["둘코락스", "타이레놀", "게보린"]:
            btn = QPushButton(name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {_PRIMARY_LIGHT}; color: {_PRIMARY};
                    padding: 6px 16px; border-radius: 14px;
                    font-size: 12px; font-weight: 600; border: none;
                }}
                QPushButton:hover {{ background: #D1F0E4; }}
            """)
            btn.clicked.connect(lambda _, n=name: self._quick_search(n))
            hot_row.addWidget(btn)
        lay.addLayout(hot_row)
        return card

    # ━━━━━━━━━━━━━━━━━━━ 이벤트 핸들러 ━━━━━━━━━━━━━━━━━━━

    def _quick_search(self, name: str):
        self.search_input.setText(name)
        self._on_search()

    def _on_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        self._update_location_badge()

        found = None
        for drug_name, data in DEMO_DRUGS.items():
            if query in drug_name or drug_name in query:
                found = (drug_name, data)
                break

        if not found:
            self._search_status.setText(f"'{query}'에 대한 검색 결과가 없습니다")
            self._search_status.setStyleSheet(
                f"color: {_RED}; font-size: 12px; background: transparent;"
            )
            self._search_status.setVisible(True)
            self._spec_card.setVisible(False)
            self._input_card.setVisible(False)
            self._result_card.setVisible(False)
            self._empty_guide.setVisible(True)
            return

        drug_name, data = found
        self._current_drug = drug_name
        self._search_status.setText(f"'{drug_name}' 검색 완료")
        self._search_status.setStyleSheet(
            f"color: {_PRIMARY}; font-size: 12px; font-weight: 600; background: transparent;"
        )
        self._search_status.setVisible(True)
        self._empty_guide.setVisible(False)

        self._drug_name_label.setText(drug_name)

        for btn in self._spec_buttons:
            self._spec_group.removeButton(btn)
            self._spec_row.removeWidget(btn)
            btn.deleteLater()
        self._spec_buttons.clear()

        for i, spec in enumerate(data["specs"]):
            btn = _SpecToggle(spec)
            self._spec_group.addButton(btn, i)
            self._spec_row.addWidget(btn)
            self._spec_buttons.append(btn)
            btn.toggled.connect(
                lambda checked, s=spec: self._on_spec_selected(s) if checked else None
            )

        self._spec_row.addStretch()
        self._spec_card.setVisible(True)

        if self._spec_buttons:
            self._spec_buttons[0].setChecked(True)

    def _on_spec_selected(self, spec: str):
        self._current_spec = spec
        self._my_price = None
        self._price_input.clear()
        self._input_card.setVisible(True)
        self._result_card.setVisible(False)

    def _on_price_submit(self):
        text = self._price_input.text().strip().replace(",", "")
        if not text.isdigit():
            return
        price = int(text)
        if price <= 0:
            return
        self._my_price = price
        self._show_result()

    def _show_result(self):
        if not self._current_drug or not self._current_spec:
            return

        data = DEMO_DRUGS.get(self._current_drug, {})
        pd = data.get("prices", {}).get(self._current_spec)
        if not pd:
            return

        self._result_card.setVisible(True)

        # 선택된 지역 이름 표시
        city = self._city_combo.currentText() if self._city_combo.currentIndex() > 0 else ""
        gu = self._gu_combo.currentText() if self._gu_combo.currentIndex() > 0 else ""
        short_city = city.replace("특별시", "").replace("광역시", "").replace(
            "특별자치시", "").replace("특별자치도", "") if city else ""
        spec_text = f"{self._current_drug} {self._current_spec}"
        if short_city:
            spec_text += f" · {short_city}"
            if gu:
                spec_text += f" {gu}"
        self._result_spec_label.setText(spec_text)

        # 구 스탯 카드 라벨 업데이트
        self._stat_gu._label.setText(f"{gu} 평균" if gu else "구 평균")
        self._stat_city._label.setText(f"{short_city} 평균" if short_city else "시/도 평균")

        # 차트 카드 타이틀 업데이트
        self._chart_titles["gu"].setText(
            f"{gu} 분포" if gu else "구 분포")
        self._chart_titles["city"].setText(
            f"{short_city} 분포" if short_city else "시/도 분포")

        # 내 가격
        if self._my_price:
            self._my_price_label.setText(f"내 가격  {self._my_price:,}원")
            dist = pd["national_dist"]
            below = sum(1 for p in dist if p < self._my_price)
            pct = (below / len(dist)) * 100 if dist else 50
            self._pct_bar.set_percentile(pct)
        else:
            self._my_price_label.setText("")
            self._pct_bar.clear()

        # 스탯 카드
        self._stat_nearby.set_value(pd["nearby_avg"], pd["nearby_count"])
        self._stat_gu.set_value(pd["gu_avg"], pd["gu_count"])
        self._stat_city.set_value(pd["city_avg"], pd["city_count"])
        self._stat_nation.set_value(pd["national_avg"], pd["national_count"])

        # 차트 4개
        gu_name = gu if gu else "구"
        city_name = short_city if short_city else "시/도"
        my = self._my_price
        self._chart_nearby.set_data(pd["nearby_dist"], my, pd["nearby_avg"], "1km평균")
        self._chart_gu.set_data(pd["gu_dist"], my, pd["gu_avg"], f"{gu_name}평균")
        self._chart_city.set_data(pd["city_dist"], my, pd["city_avg"], f"{city_name}평균")
        self._chart_nation.set_data(pd["national_dist"], my, pd["national_avg"], "전국평균")
