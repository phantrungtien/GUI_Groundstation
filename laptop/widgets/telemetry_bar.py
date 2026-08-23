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
from laptop import theme

SRC_COLOR = {"sik": theme.OK, "remote": theme.INFO, None: theme.MUTED}

# Mau theo muc do cua chinh gia tri. "crit" khong phai luc nao cung la HONG —
# o ARM no la "canh quat co the quay", mot trang thai binh thuong nhung tuyet doi
# khong duoc lot mat.
LEVEL_COLOR = {None: theme.TEXT, "warn": theme.WARN, "crit": theme.CRIT}
UNKNOWN_COLOR = theme.MUTED

# --- NUM CHINH ------------------------------------------------------------
# Nguong pin tinh theo PHAN TRAM FC bao, khong theo dien ap. Dien ap mot minh
# khong noi len con bao nhieu neu khong biet so cell — va so cell doi that:
# ba chuyen bay that gan day do duoc 16,8 V / 15,2 V / 11,7 V, tuc 4S va 3S xen
# ke nhau. Dat nguong dien ap cung la sai o it nhat mot trong ba chuyen do.
# FC thi biet BATT_CAPACITY va so cell nen phan tram cua no moi la con so co
# nghia (ba chuyen tren FC bao 98%, 99%, 77-81% — co bao that).
# Hai con so nay KHONG duoc tu nghi ra: chung phai khop voi bang nguong o muc F
# cua docs/operating_procedure.md ("< 30% goi ve", "< 20% RTL ngay, khong thuong
# luong"). Giao dien to mau o mot nguong khac voi quy trinh la day nguoi bay ra
# hai quyet dinh khac nhau cho cung mot con so.
BATT_WARN_PCT = 30
BATT_CRIT_PCT = 20
# GPS: ba dieu kien, giong het muc D.4 cua docs/operating_procedure.md
# ("Fix >= 3D, so ve tinh >= 8, HDOP < 2"). Truoc day muon doc du ba thu phai
# sang tab Trang thai loc "GPS" va doc ba hang — dung luc sap cat canh.
#
# Ba cai deu can, khong cai nao thay duoc cai nao: fix_type=3 voi 5 ve tinh la
# fix mong manh, con HDOP cao la ve tinh dong nhung xep thanh mot cum tren troi
# nen giao diem nhoe ra. Do that tren ban: fix_type=1, sats=0 — dem ve tinh mot
# minh thi o do hien so 0 trang tinh nhu moi so khac.
GPS_MIN_FIX = 3  # 3 = 3D fix. 2 = chi 2D (khong co do cao GPS) -> canh bao.
GPS_MIN_SATS = 8
GPS_MAX_HDOP = 2.0

# (khoa tra cuu, don vi). Khoa la thu set_cell() goi toi, KHONG doi theo ngon
# ngu; chu hien ra lay o bang chu duoi key "tlm.<khoa>" — "PIN" doc sang tieng
# Anh la mot tu khac han, de nguyen la sai nghia chu khong phai giu nguyen goc.
#
# ARM dung dau: no la thu phai liec mot cai la thay, va mat trai la cho mat quet
# toi truoc.
CELLS = [
    ("ARM", ""), ("ALT", "m"), ("SPD", "m/s"), ("PIN", "V"), ("SAT", ""), ("MODE", ""),
    ("BAY", ""),
]
WIDE = {"MODE": 72, "ARM": 88}  # "DISARMED" dai hon "GUIDED", ca hai dai hon "25"


def batt_level(pct):
    """Muc canh bao pin tu phan tram FC bao. None = FC khong bao -> khong doan."""
    if pct is None:
        return None
    if pct <= BATT_CRIT_PCT:
        return "crit"
    return "warn" if pct <= BATT_WARN_PCT else None


def gps_level(fix, sats=None, hdop=None):
    """Muc canh bao GPS. Tra (muc, ly_do) — ly_do la key trong bang chu, hay None.

    Ly do phai tra ra ngoai chu khong nuot: o chi rong bang mot con so, nen thu
    duy nhat noi duoc "vi sao vang" la tooltip, ma tooltip thi phai biet dieu
    kien nao truot. Bao vang ma khong noi vi sao thi nguoi bay lai phai sang tab
    Trang thai doc tay — dung cai vong lap muc D.4 dang bat ho lam.
    """
    if fix is None:
        return None, None
    if fix < 2:
        return "crit", f"tlm.fix{int(fix)}"  # 0 khong co GPS, 1 chua bat duoc fix
    if fix < GPS_MIN_FIX:
        return "warn", f"tlm.fix{int(fix)}"
    if sats is not None and sats < GPS_MIN_SATS:
        return "warn", "tlm.few_sats"
    if hdop is not None and hdop >= GPS_MAX_HDOP:
        return "warn", "tlm.bad_hdop"
    return None, f"tlm.fix{int(fix)}"


class TelemetryBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        # QLabel trong suot: khong co dong nay thi moi o bi nen QWidget chung
        # to de len, thanh ra mot day mieng vuong thay vi mot tam kinh lien.
        self.setStyleSheet(
            f"QFrame{{background:{theme.SURFACE};border:1.5px solid {theme.DIVIDER};"
            f"border-radius:{theme.RADIUS_PANEL}px;}}"
            "QLabel{background:transparent;border:none;}"
        )
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 6, 10, 6)
        grid.setHorizontalSpacing(18)

        self._val, self._dot, self._name = {}, {}, {}
        for col, (key, unit) in enumerate(CELLS):
            name = QLabel()
            name.setStyleSheet(f"color:{theme.MUTED};font-size:10px;")
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
        dot.setStyleSheet(f"color:{SRC_COLOR.get(src, theme.MUTED)};font-size:11px;")
