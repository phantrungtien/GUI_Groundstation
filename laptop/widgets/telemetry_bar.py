"""Thanh telemetry noi goc duoi map: da ARM chua, do cao, toc do, pin, GPS, mode.

Moi o mang mot cham mau chi nguon du lieu (nguyen tac 2.2). Nguon het tuoi thi
so xam di — dung hinh ma van sang la noi doi.

Rieng ba o ARM / PIN / SAT con doi mau theo GIA TRI, khong chi theo tuoi. Ly do
o `LEVEL_COLOR` va o hai hang so nguong ben duoi: mot con so dung tren nen trang
khong tu keo mat ai ca, ma pin can va GPS mat fix la hai thu phai keo duoc.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel

from core import i18n
from core.i18n import t

SRC_COLOR = {"sik": "#27ae60", "remote": "#3498db", None: "#7f8c8d"}

# Mau theo muc do cua chinh gia tri. "crit" khong phai luc nao cung la HONG —
# o ARM no la "canh quat co the quay", mot trang thai binh thuong nhung tuyet doi
# khong duoc lot mat.
LEVEL_COLOR = {None: "#dcdcdc", "warn": "#f39c12", "crit": "#e74c3c"}
UNKNOWN_COLOR = "#7f8c8d"

# --- NUM CHINH ------------------------------------------------------------
# Nguong pin tinh theo PHAN TRAM FC bao, khong theo dien ap. Dien ap mot minh
# khong noi len con bao nhieu neu khong biet so cell — va so cell doi that:
# ba chuyen bay that gan day do duoc 16,8 V / 15,2 V / 11,7 V, tuc 4S va 3S xen
# ke nhau. Dat nguong dien ap cung la sai o it nhat mot trong ba chuyen do.
# FC thi biet BATT_CAPACITY va so cell nen phan tram cua no moi la con so co
# nghia (ba chuyen tren FC bao 98%, 99%, 77-81% — co bao that).
BATT_WARN_PCT = 30
BATT_CRIT_PCT = 15
# GPS: bam theo fix_type chu khong theo so ve tinh. Do that tren ban: fix_type=1,
# sats=0 — dem ve tinh mot minh thi o do hien so 0 trang tinh nhu moi so khac.
GPS_MIN_FIX = 3  # 3 = 3D fix. 2 = chi 2D (khong co do cao GPS) -> canh bao.

# (khoa tra cuu, don vi). Khoa la thu set_cell() goi toi, KHONG doi theo ngon
# ngu; chu hien ra lay o bang chu duoi key "tlm.<khoa>" — "PIN" doc sang tieng
# Anh la mot tu khac han, de nguyen la sai nghia chu khong phai giu nguyen goc.
#
# ARM dung dau: no la thu phai liec mot cai la thay, va mat trai la cho mat quet
# toi truoc.
CELLS = [
    ("ARM", ""), ("ALT", "m"), ("SPD", "m/s"), ("PIN", "V"), ("SAT", ""), ("MODE", ""),
]
WIDE = {"MODE": 72, "ARM": 88}  # "DISARMED" dai hon "GUIDED", ca hai dai hon "25"


def batt_level(pct):
    """Muc canh bao pin tu phan tram FC bao. None = FC khong bao -> khong doan."""
    if pct is None:
        return None
    if pct <= BATT_CRIT_PCT:
        return "crit"
    return "warn" if pct <= BATT_WARN_PCT else None


def gps_level(fix):
    """Muc canh bao GPS tu fix_type cua GPS_RAW_INT."""
    if fix is None:
        return None
    if fix < 2:
        return "crit"  # 0 = khong co GPS, 1 = co GPS nhung chua bat duoc fix
    return "warn" if fix < GPS_MIN_FIX else None


class TelemetryBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:rgba(20,23,25,210);border:1px solid #3a3f44;")
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 6, 10, 6)
        grid.setHorizontalSpacing(18)

        self._val, self._dot, self._name = {}, {}, {}
        for col, (key, unit) in enumerate(CELLS):
            name = QLabel()
            name.setStyleSheet("color:#8a9199;font-size:10px;")
            self._name[key] = name
            dot = QLabel("●")
            val = QLabel("--")
            val.setStyleSheet("font-size:16px;font-weight:bold;")
            # Rong toi thieu cho chu khoi bi cat: "GUIDED" dai hon "25".
            val.setMinimumWidth(WIDE.get(key, 52))
            grid.addWidget(name, 0, col * 2, 1, 2)
            grid.addWidget(dot, 1, col * 2, alignment=Qt.AlignVCenter)
            grid.addWidget(val, 1, col * 2 + 1)
            self._val[key], self._dot[key] = val, dot
        self.set_cell("ALT", None, None)
        i18n.on_change(self._retext)

    def _retext(self):
        for key, unit in CELLS:
            self._name[key].setText(t(f"tlm.{key}") + (f" ({unit})" if unit else ""))

    def set_cell(self, key, value, src, fmt="{:.1f}", level=None, tip=""):
        """level: None binh thuong · "warn" vang · "crit" do. Xem LEVEL_COLOR.

        `tip` la cho noi RA cai lam nen mau do — o hep, khong nhet duoc ca cau.
        Khong co tip thi tooltip rong va Qt khong hien gi, dung y.
        """
        val, dot = self._val[key], self._dot[key]
        if value is None:
            val.setText("--")
            color = UNKNOWN_COLOR
        else:
            val.setText(fmt.format(value) if isinstance(value, (int, float)) else str(value))
            color = LEVEL_COLOR[level]
        val.setStyleSheet(f"font-size:16px;font-weight:bold;color:{color};")
        val.setToolTip(tip)
        dot.setToolTip(tip)
        dot.setStyleSheet(f"color:{SRC_COLOR.get(src, '#7f8c8d')};font-size:11px;")
