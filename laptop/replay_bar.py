"""Thanh dieu khien REPLAY: tam dung + thanh tua.

Chi hien khi mode == REPLAY. Cho phep debug giao dien tren chuyen bay da xay ra
— ke ca chuyen bay hong.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QWidget


class ReplayBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.adapter = None

        self.btn = QPushButton("⏸ Tam dung")
        self.btn.setFixedWidth(120)
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

    def attach(self, adapter):
        self.adapter = adapter
        self.btn.setText("⏸ Tam dung")
        self.setVisible(adapter is not None)

    def _toggle(self):
        if not self.adapter:
            return
        paused = self.btn.text().startswith("⏸")
        self.adapter.pause(paused)
        self.btn.setText("▶ Chay tiep" if paused else "⏸ Tam dung")

    def _seek(self):
        if self.adapter:
            self.adapter.seek(self.slider.value() / 1000.0)

    def _tick(self):
        if not self.adapter or self.slider.isSliderDown():
            return
        pct = self.adapter.percent
        self.slider.setValue(int(pct * 10))
        self.pct.setText(f"{pct:.0f}%")
