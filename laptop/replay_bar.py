"""Thanh dieu khien REPLAY: tam dung + thanh tua.

Chi hien khi mode == REPLAY. Cho phep debug giao dien tren chuyen bay da xay ra
— ke ca chuyen bay hong.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

from core import i18n
from core.i18n import t


class ReplayBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.adapter = None

        self.btn = QPushButton()
        self.btn.setFixedWidth(120)
        self._paused = False
        self.btn.clicked.connect(self._toggle)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderReleased.connect(self._seek)

        self.pct = QLabel("0%")
        self.pct.setFixedWidth(44)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.addWidget(QLabel("REPLAY"))
        lay.addWidget(self.btn)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.pct)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(300)
        i18n.on_change(self._retext)

    def _retext(self):
        self.btn.setText(t("rep.resume") if self._paused else t("rep.pause"))

    def attach(self, adapter):
        self.adapter = adapter
        self._paused = False
        self._retext()
        self.setVisible(adapter is not None)

    def _toggle(self):
        if not self.adapter:
            return
        # Trang thai lay o co rieng, KHONG doc lai chu tren nut: chu doi theo ngon
        # ngu, doc no la nut dung lam sau lan doi ngon ngu dau tien.
        self._paused = not self._paused
        self.adapter.pause(self._paused)
        self._retext()

    def _seek(self):
        if self.adapter:
            self.adapter.seek(self.slider.value() / 1000.0)

    def _tick(self):
        if not self.adapter or self.slider.isSliderDown():
            return
        pct = self.adapter.percent
        self.slider.setValue(int(pct * 10))
        self.pct.setText(f"{pct:.0f}%")
