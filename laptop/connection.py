"""Panel chon nguon ket noi (dock ben phai) + banner che do (nguyen tac 2.5).

App vao thang cua so chinh nhung KHONG tu ket noi: chua chon nguon thi banner
xam "CHUA KET NOI" va khong co byte nao chay. `mode` cua profile — khong phai
chuoi ket noi — quyet dinh mau banner va viec khoa nut dieu khien.
"""

import glob
import os
from pathlib import Path

import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import i18n
from core.i18n import t

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "connections.yaml"

# VID cua chip cau USB-serial: FTDI, Silicon Labs, CH340, Prolific. Radio SiK di
# qua mot trong so nay -> 57600. Ten cong KHONG dung de doan duoc tren Windows
# (COM3 khong noi gi ve loai chip), VID thi giong nhau moi he dieu hanh.
BRIDGE_VIDS = {0x0403, 0x10c4, 0x1a86, 0x067b}

MODE_COLOR = {
    "REAL": "#b03a2e",
    "SIM": "#1f618d",
    "REPLAY": "#5d6d7e",
    None: "#33383d",  # chua chon nguon
    "WAIT": "#b9770e",  # da mo nguon nhung chua co byte nao ve
    "DEGRADED": "#8e44ad",  # mat nua ROS2, SiK con — suy giam chuc nang
    "LOST": "#e74c3c",  # mat SiK — mat duong cuu sinh, nang nhat
    "CLOSING": "#c0392b",  # dang ARM ma bam dong cua so
}
# Chu thich mode nam trong bang chu (core/i18n.py) duoi key "mode.<MODE>".


def load_profiles(path=CONFIG):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []


def detect_serial(template=None):
    """Quet cong USB-serial DANG CAM, tra ve profile REAL cho tung cong.

    Khong ghi cung /dev/ttyUSB0 nua: cam vao cong USB khac, hay cam SiK sau mot
    thiet bi USB khac, la so thu tu doi — ttyUSB1, ttyUSB2. Sua code moi lan cam
    lai la sai ngay tu goc.

    Loc: `list_ports` liet ke ca ~32 cong UART tren main board (/dev/ttyS*) von
    khong bao gio co drone o dau kia. Chi giu thiet bi co VID/PID USB that.

    Baud: ttyUSB* thuong la radio SiK qua chip FTDI/CP210x -> 57600. ttyACM* la
    Pixhawk cam USB truc tiep (CDC), baud khong co y nghia -> de 115200.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return []

    template = template or {}
    out = []
    for p in sorted(list_ports.comports(), key=lambda x: x.device):
        usb = p.vid is not None or "ttyUSB" in p.device or "ttyACM" in p.device
        if not usb:
            continue
        bridge = p.vid in BRIDGE_VIDS or "ttyUSB" in p.device
        prof = {k: v for k, v in template.items() if k not in ("name", "conn")}
        prof.update({
            "name": (p.product or p.description or "USB serial").strip(),
            "mode": "REAL",
            "conn": p.device,
            "baud": template.get("baud", 57600 if bridge else 115200),
            "detected": True,
            # Bay 2 cua ke hoach: khong o nhom `dialout` thi mo cong that bai voi
            # mot dong loi kho hieu. Bat o day de con noi thang phai lam gi.
            # Windows khong co khai niem nay va os.access("COM3") luon False, nen
            # bo qua — moi cong se hien ra "khong co quyen" mot cach vo co.
            "writable": os.name != "posix" or os.access(p.device, os.R_OK | os.W_OK),
        })
        out.append(prof)
    return out


class ModeBanner(QLabel):
    """Dai mau chay het chieu ngang dinh cua so. Ba mau khong the nham."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self._shown = None
        # Lan ve cuoi, giu nguyen dang "goi lai duoc": doi ngon ngu giua chuyen bay
        # phai ve lai dung trang thai dang hien, khong duoc rot ve "CHUA KET NOI".
        self._last = (self.show_disconnected, (), {})
        i18n.on_change(self._retext)

    def _retext(self):
        fn, a, kw = self._last
        self._shown = None  # buoc ve lai du text cu va moi trung mode
        fn(*a, **kw)

    def _paint(self, mode, text):
        if self._shown == (mode, text):
            return  # goi moi nua giay, dung to lai khi khong doi gi
        self._shown = (mode, text)
        self.setText(text)
        self.setStyleSheet(
            f"background:{MODE_COLOR[mode]};color:#fff;"
            "font-weight:bold;letter-spacing:1px;padding:6px;"
        )

    def show_disconnected(self):
        self._last = (self.show_disconnected, (), {})
        self._paint(None, t("banner.none"))

    def show_waiting(self, profile):
        """Da mo nguon nhung chua nhan duoc byte nao.

        Bat buoc phai co trang thai rieng: `udp:` chi bind cong chu khong noi toi
        ai ca, nen "mo duoc nguon" KHONG co nghia la co drone dau kia. Neu ve mau
        cua mode luon thi banner dang noi doi.
        """
        self._last = (self.show_waiting, (profile,), {})
        self._paint("WAIT", t("banner.waiting", mode=profile["mode"], name=profile["name"]))

    def show_profile(self, profile):
        self._last = (self.show_profile, (profile,), {})
        mode = profile["mode"]
        self._paint(mode, f"{mode}  ·  {profile['name']}  ·  {t('mode.' + mode)}")

    def show_lost(self, profile, why=""):
        """Mat duong SiK — mat duong cuu sinh. Nang nhat."""
        self._last = (self.show_lost, (profile, why), {})
        self._paint("LOST", t("banner.lost", name=profile["name"], why=why))

    def show_close_warning(self, sec):
        """Bam dong khi drone dang ARM. KHONG ghi vao `_last`: nhip 0,5 giay cua
        app se ve de len dong nay va do la dung — het cua so xac nhan thi banner
        phai tro ve noi trang thai bay, khong ke lai chuyen vua roi."""
        self._paint("CLOSING", t("close.banner", sec=sec))

    def show_degraded(self, profile, why=""):
        """Mat nua ROS2 nhung SiK con — suy giam chuc nang, chua mat an toan.

        Mau khac han LOST: nham hai cai nay la nham giua "van bay ve duoc" va
        "khong con duong nao lai drone".
        """
        self._last = (self.show_degraded, (profile, why), {})
        self._paint("DEGRADED", f"⚠  {profile['mode']}  ·  {why}")


class ConnectionPanel(QWidget):
    """Danh sach profile + nut Ket noi / Ngat. Dat trong dock ben phai."""

    connect_requested = Signal(dict)
    disconnect_requested = Signal()

    def __init__(self, profiles, parent=None):
        super().__init__(parent)
        self.connected = False
        self._opening = None  # ten profile dang mo, de dat lai hint khi doi ngon ngu
        self._scan_hint = ("conn.none_picked", {})  # (key, kwargs) — dich lai khi doi ngon ngu
        # Muc REAL khong co `conn` la KHUON cho cong tu quet (baud, sysid, remote),
        # khong phai mot nguon chon duoc.
        self.template = next(
            (p for p in profiles if p.get("mode") == "REAL" and not p.get("conn")), {}
        )
        self.fixed = [p for p in profiles if p is not self.template]
        self.profiles = []

        self.list = QListWidget()
        self.list.setCurrentRow(-1)
        self.list.currentRowChanged.connect(self._sync_buttons)
        self.list.itemDoubleClicked.connect(self._connect)

        self.btn_connect = QPushButton()
        self.btn_disconnect = QPushButton()
        self.btn_scan = QPushButton()
        self.btn_connect.clicked.connect(self._connect)
        self.btn_disconnect.clicked.connect(self.disconnect_requested)
        self.btn_scan.clicked.connect(self.rescan)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#8a9199;")

        row = QHBoxLayout()
        row.addWidget(self.btn_connect)
        row.addWidget(self.btn_disconnect)

        self.title = QLabel()
        lay = QVBoxLayout(self)
        lay.addWidget(self.title)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.btn_scan)
        lay.addLayout(row)
        lay.addWidget(self.hint)

        self.rescan()
        self.set_connected(False)
        i18n.on_change(self._retext)

    def _retext(self):
        self.title.setText(t("conn.title"))
        self.btn_connect.setText(t("conn.connect"))
        self.btn_disconnect.setText(t("conn.disconnect"))
        self.btn_scan.setText(t("conn.scan"))
        # Danh sach mang chu "khong co quyen", va hint mang ket qua quet: ca hai
        # phai dung lai. rescan() giu dong dang chon theo TEXT, ma text vua doi
        # ngon ngu — nen tu giu lay chi so, danh sach cong khong doi luc nay.
        row = self.list.currentRow()
        self.rescan()
        self.list.setCurrentRow(row)
        if self._opening is not None:
            self.hint.setText(t("conn.opening", name=self._opening))

    def select(self, name):
        """Chon dong theo TEN profile. Tra ve True neu tim thay.

        So thu tu dong khong on dinh: `rescan` chen cong USB tu quet len dau danh
        sach, nen cam FC vao la dong 0 doi chu. Cong cu tu dong nao chon theo chi
        so se nham sang nguon REAL — da xay ra that: mot bai test REPLAY noi thang
        vao FC dang cam.
        """
        i = next((i for i, p in enumerate(self.profiles) if p["name"] == name), -1)
        self.list.setCurrentRow(i)
        return i >= 0

    def rescan(self):
        """Quet lai cong USB roi dung lai danh sach. Cong cam vao/rut ra khi app
        dang chay la chuyen binh thuong — khong bat khoi dong lai app."""
        keep = self.list.currentItem().text() if self.list.currentItem() else None
        detected = detect_serial(self.template)
        self.profiles = detected + self.fixed
        self.list.clear()
        for p in self.profiles:
            target = p.get("conn") or p.get("path", "")
            mark = ""
            if p.get("detected"):
                mark = "  ⟲" if p.get("writable") else t("conn.no_perm")
            self.list.addItem(
                QListWidgetItem(f"[{p['mode']}]  {p['name']}{mark}\n        {target}")
            )
        # Khong chon san hang nao: mac dinh im lang an toan hon mac dinh doan sai.
        self.list.setCurrentRow(-1)
        if keep:
            for i in range(self.list.count()):
                if self.list.item(i).text() == keep:
                    self.list.setCurrentRow(i)
                    break
        n = len(detected)
        if any(p.get("detected") and not p.get("writable") for p in self.profiles):
            # Bay 2 cua ke hoach — noi thang cach sua, dung de nguoi dung tu doan.
            self._scan_hint = ("conn.perm_fix", {})
        elif n:
            self._scan_hint = ("conn.found", {"n": n})
        else:
            self._scan_hint = ("conn.not_found", {})
        if not self.connected:
            self.hint.setText(t(self._scan_hint[0], **self._scan_hint[1]))

    def set_connected(self, connected, profile=None):
        self.connected = connected
        self.list.setEnabled(not connected)
        self.btn_disconnect.setEnabled(connected)
        self._sync_buttons()
        if connected:
            # "da mo nguon", khong phai "da co drone" — xem ModeBanner.show_waiting
            self._opening = profile["name"]
            self.hint.setText(t("conn.opening", name=profile["name"]))
        else:
            # Ket qua quet co gia tri hon cau chung chung: no noi vi sao danh sach
            # trong, hoac vi sao cam radio roi ma van khong ket noi duoc.
            self._opening = None
            self.hint.setText(t(self._scan_hint[0], **self._scan_hint[1])
                              if self.list.currentRow() < 0 else "")

    def _sync_buttons(self):
        self.btn_connect.setEnabled(not self.connected and self.list.currentRow() >= 0)

    def _connect(self):
        row = self.list.currentRow()
        if row < 0 or self.connected:
            return
        profile = dict(self.profiles[row])
        if profile["mode"] == "REPLAY":
            # Profile tro thang vao mot file co that thi dung luon. Chi mo hop
            # thoai khi do la mau (logs/*.tlog) hoac file khong ton tai.
            given = Path(profile.get("path", ""))
            if not given.is_absolute():
                given = ROOT / given
            if given.is_file():
                profile["path"] = str(given)
            else:
                path = self._pick_tlog(profile.get("path", "*.tlog"))
                if not path:
                    return
                profile["path"] = path
        self.connect_requested.emit(profile)

    def _pick_tlog(self, pattern):
        pattern = str(ROOT / pattern) if not Path(pattern).is_absolute() else pattern
        matches = sorted(glob.glob(pattern))
        start = str(Path(matches[-1]).parent) if matches else str(ROOT)
        path, _ = QFileDialog.getOpenFileName(self, t("conn.pick_tlog"), start,
                                              t("conn.tlog_filter"))
        if not path:
            QMessageBox.information(self, "REPLAY", t("conn.no_tlog"))
        return path
