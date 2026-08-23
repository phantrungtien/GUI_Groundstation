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

from core import i18n
from core.i18n import t
from laptop import theme


def _hint(text, color=theme.MUTED):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color:{color};")
    return lbl


class LinkFaults(QWidget):
    log = Signal(str, int)   # (chu da dich, muc do) — xem ControlTab.log

    def __init__(self, parent=None):
        super().__init__(parent)
        self.adapter = None
        self.remote = None

        self.cut_remote = QCheckBox()
        self.cut_remote.toggled.connect(self._apply)
        self.ros2_box = QGroupBox()
        r = QVBoxLayout(self.ros2_box)
        r.addWidget(self.cut_remote)
        self.ros2_hint = _hint("", theme.WARN)
        r.addWidget(self.ros2_hint)

        self.cut_sik = QCheckBox()
        self.cut_sik.toggled.connect(self._apply)
        self.sik_box = QGroupBox()
        s = QVBoxLayout(self.sik_box)
        s.addWidget(self.cut_sik)
        self.sik_hint = _hint("", theme.CRIT)
        s.addWidget(self.sik_hint)

        self.both_hint = _hint("")
        lay = QVBoxLayout(self)
        lay.addWidget(self.ros2_box)
        lay.addWidget(self.sik_box)
        lay.addWidget(self.both_hint)
        lay.addStretch(1)
        i18n.on_change(self._retext)

    def _retext(self):
        self.ros2_box.setTitle(t("flt.ros2_box"))
        self.cut_remote.setText(t("flt.cut_ros2"))
        self.ros2_hint.setText(t("flt.ros2_hint"))
        self.sik_box.setTitle(t("flt.sik_box"))
        self.cut_sik.setText(t("flt.cut_sik"))
        self.sik_hint.setText(t("flt.sik_hint"))
        self.both_hint.setText(t("flt.both_hint"))

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
        self.log.emit(t("flt.cutting", what=", ".join(cut)) if cut
                      else t("flt.restored"), 4 if cut else 5)
