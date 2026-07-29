"""Thanh telemetry noi goc duoi map: toc do, do cao, pin, GPS, mode.

Moi o mang mot cham mau chi nguon du lieu (nguyen tac 2.2). Nguon het tuoi thi
so xam di — dung hinh ma van sang la noi doi.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel

SRC_COLOR = {"sik": "#27ae60", "remote": "#3498db", None: "#7f8c8d"}

CELLS = [
    ("ALT", "m"), ("SPD", "m/s"), ("PIN", "V"), ("SAT", ""), ("MODE", ""),
]


class TelemetryBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:rgba(20,23,25,210);border:1px solid #3a3f44;")
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 6, 10, 6)
        grid.setHorizontalSpacing(18)

        self._val, self._dot = {}, {}
        for col, (key, unit) in enumerate(CELLS):
            name = QLabel(f"{key}" + (f" ({unit})" if unit else ""))
            name.setStyleSheet("color:#8a9199;font-size:10px;")
            dot = QLabel("●")
            val = QLabel("--")
            val.setStyleSheet("font-size:16px;font-weight:bold;")
            # Rong toi thieu cho chu khoi bi cat: "GUIDED" dai hon "25".
            val.setMinimumWidth(72 if key == "MODE" else 52)
            grid.addWidget(name, 0, col * 2, 1, 2)
            grid.addWidget(dot, 1, col * 2, alignment=Qt.AlignVCenter)
            grid.addWidget(val, 1, col * 2 + 1)
            self._val[key], self._dot[key] = val, dot
        self.set_cell("ALT", None, None)

    def set_cell(self, key, value, src, fmt="{:.1f}"):
        val, dot = self._val[key], self._dot[key]
        if value is None:
            val.setText("--")
            val.setStyleSheet("font-size:16px;font-weight:bold;color:#7f8c8d;")
        else:
            val.setText(fmt.format(value) if isinstance(value, (int, float)) else str(value))
            val.setStyleSheet("font-size:16px;font-weight:bold;color:#dcdcdc;")
        dot.setStyleSheet(f"color:{SRC_COLOR.get(src, '#7f8c8d')};font-size:11px;")
