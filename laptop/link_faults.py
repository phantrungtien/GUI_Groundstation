"""Mo phong DUT DUONG TRUYEN — chi hien khi mode == SIM.

Khac han voi tiem loi vao drone (mat GPS, tut pin, chet dong co): nhung thu do
sua o world hoac go thang `param set` trong console MAVProxy la xong. Con dut
duong truyen la loi cua CHINH DUONG DAY giua laptop va drone — khong mo phong
duoc bang cach sua may bay.

Hai nua hong doc lap va hau qua khac han nhau (muc 1.3 cua ke hoach), nen o day
la hai o rieng, khong gop:

    Ngat ROS2       -> kieu hong A: WiFi rot, companion CON SONG.
                       Task tu hanh VAN DANG CHAY tren drone, ban chi mat kha nang
                       nhin va can thiep. Nguy hiem hon kieu B.
    Ngat telemetry  -> mat duong cuu sinh. Nut do khong toi noi.
    Ngat ca hai     -> kich ban #4: chi con RC.

Khong dung toi socket — chi bit luong envelope hai chieu, nen bo tick la co du
lieu lai tuc thi, khac han tat WiFi that (phai cho ket noi lai).
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QVBoxLayout, QWidget


def _hint(text, color="#8a939b"):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color:{color};")
    return lbl


class LinkFaults(QWidget):
    log = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.adapter = None
        self.remote = None

        self.cut_remote = QCheckBox("Ngat ket noi ROS2")
        self.cut_remote.toggled.connect(self._apply)
        ros2 = QGroupBox("Nua ROS2 — WebSocket toi companion")
        r = QVBoxLayout(ros2)
        r.addWidget(self.cut_remote)
        r.addWidget(_hint(
            "Kich ban #1. Mat vision/SLAM/task, tab lien quan xam. Nhung task tu hanh "
            "VAN CHAY tren drone — banner phai noi ro dieu do.", "#e59866"))

        self.cut_sik = QCheckBox("Ngat telemetry")
        self.cut_sik.toggled.connect(self._apply)
        sik = QGroupBox("Nua telemetry — MAVLink qua SiK")
        s = QVBoxLayout(sik)
        s.addWidget(self.cut_sik)
        s.addWidget(_hint(
            "Kich ban #3. Mat duong cuu sinh: khong con HUD, va nut do khong toi noi. "
            "Day la loi nang nhat, bat ke nua ROS2 con song hay khong.", "#e74c3c"))

        lay = QVBoxLayout(self)
        lay.addWidget(ros2)
        lay.addWidget(sik)
        lay.addWidget(_hint(
            "Tick ca hai = kich ban #4: khong con duong nao xuong drone, chi con RC.\n"
            "Bo tick la co du lieu lai ngay — khong phai cho ket noi lai nhu rut day that."))
        lay.addStretch(1)

    def attach(self, adapter, remote):
        """app.py goi khi ket noi/ngat. adapter=None nghia la da ngat."""
        self.adapter = adapter
        self.remote = remote
        self.cut_sik.setEnabled(adapter is not None)
        self.cut_remote.setEnabled(remote is not None)
        if adapter is None:
            # Con giu tick sau khi ngat thi lan ket noi sau link bi cam san, va
            # nguoi dung se di tim loi trong SITL.
            for cb in (self.cut_sik, self.cut_remote):
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)

    def _apply(self):
        if self.adapter:
            self.adapter.muted = self.cut_sik.isChecked()
        if self.remote:
            self.remote.muted = self.cut_remote.isChecked()
        cut = [n for n, c in (("telemetry", self.cut_sik), ("ROS2", self.cut_remote))
               if c.isChecked()]
        self.log.emit(f"MO PHONG: dang ngat {', '.join(cut)}" if cut
                      else "MO PHONG: da noi lai ca hai nua")
