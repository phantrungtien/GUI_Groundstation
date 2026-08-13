"""Widget Link status — hai hang rieng biet SiK / Remote, kem byte/s that.

Muc dich la khong bao gio de nguoi dung nhin so lieu dong cung ma tuong van on
(nguyen tac 2.2). Hang nao qua STALE giay khong co goi thi xam han.
"""

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from core.adapters.sik import STALE

ALIVE, DEAD = "#27ae60", "#7f8c8d"
WARN = "#e67e22"
# Tren 5% mat goi thi doi mau. Duong SiK khoe do duoc 0,0% (13/08/2026, 30s tren
# radio that); vai phan tram la con song nhung da bat dau an mon, va do la luc
# nguoi bay can biet — chu khong phai luc no ve 0.
WARN_LOSS = 5.0


class LinkStatus(QWidget):
    ROWS = [("sik", "SiK"), ("remote", "Remote")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.last_seen = {}  # src -> ts goi cuoi
        self.bps = {}
        self.loss = {}  # src -> % goi mat trong giay vua roi (thay cho RSSI)
        self._dots, self._info = {}, {}

        grid = QGridLayout(self)
        grid.setContentsMargins(6, 0, 6, 0)
        grid.setVerticalSpacing(0)
        for row, (src, label) in enumerate(self.ROWS):
            dot = QLabel("●")
            name = QLabel(label)
            info = QLabel("--")
            name.setMinimumWidth(52)
            info.setMinimumWidth(120)
            grid.addWidget(dot, row, 0)
            grid.addWidget(name, row, 1)
            grid.addWidget(info, row, 2)
            self._dots[src], self._info[src] = dot, info

        self._tick()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(500)

    def on_envelope(self, env):
        """Noi vao bus topic "*": envelope tu drone la bang chung link con song.

        Tru topic "link" — cai do adapter tu sinh moi giay ke ca khi khong con
        goi nao ve. Neu tinh no la con song thi hang nay khong bao gio xam.
        """
        if env["topic"] == "link":
            self.bps[env["src"]] = env["data"].get("bps", 0)
            self.loss[env["src"]] = env["data"].get("loss", 0.0)
            return
        self.last_seen[env["src"]] = env["ts"]

    def _tick(self):
        now = time.time()
        for src, _ in self.ROWS:
            seen = self.last_seen.get(src)
            alive = seen is not None and now - seen < STALE
            loss = self.loss.get(src, 0.0)
            self._dots[src].setStyleSheet(f"color:{ALIVE if alive else DEAD};font-size:14px;")
            if seen is None:
                text = "chua ket noi"
            elif alive:
                # Mat goi hien LUON, ke ca 0,0%: con so dung yen o 0 la bang chung
                # duong truyen sach, con o trong thi khong phan biet duoc "sach"
                # voi "chua do duoc" (nguyen tac 2.2).
                text = f"{self.bps.get(src, 0)} B/s · mat {loss:.1f}%"
            else:
                text = f"MAT — {now - seen:.0f}s"
            self._info[src].setText(text)
            color = DEAD if not alive else (WARN if loss >= WARN_LOSS else "#ddd")
            self._info[src].setStyleSheet(f"color:{color};")
