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

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "connections.yaml"

MODE_COLOR = {
    "REAL": "#b03a2e",
    "SIM": "#1f618d",
    "REPLAY": "#5d6d7e",
    None: "#33383d",  # chua chon nguon
    "WAIT": "#b9770e",  # da mo nguon nhung chua co byte nao ve
    "DEGRADED": "#8e44ad",  # mat nua ROS2, SiK con — suy giam chuc nang
    "LOST": "#e74c3c",  # mat SiK — mat duong cuu sinh, nang nhat
}
MODE_NOTE = {
    "REAL": "DRONE THAT — moi lenh deu di xuong may bay",
    "SIM": "mo phong SITL",
    "REPLAY": "phat lai — moi nut dieu khien bi khoa",
}


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
        prof = {k: v for k, v in template.items() if k not in ("name", "conn")}
        prof.update({
            "name": (p.product or p.description or "USB serial").strip(),
            "mode": "REAL",
            "conn": p.device,
            "baud": template.get("baud", 115200 if "ttyACM" in p.device else 57600),
            "detected": True,
            # Bay 2 cua ke hoach: khong o nhom `dialout` thi mo cong that bai voi
            # mot dong loi kho hieu. Bat o day de con noi thang phai lam gi.
            "writable": os.access(p.device, os.R_OK | os.W_OK),
        })
        out.append(prof)
    return out


class ModeBanner(QLabel):
    """Dai mau chay het chieu ngang dinh cua so. Ba mau khong the nham."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self._shown = None
        self.show_disconnected()

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
        self._paint(None, "CHUA KET NOI  ·  chon nguon o panel ben phai")

    def show_waiting(self, profile):
        """Da mo nguon nhung chua nhan duoc byte nao.

        Bat buoc phai co trang thai rieng: `udp:` chi bind cong chu khong noi toi
        ai ca, nen "mo duoc nguon" KHONG co nghia la co drone dau kia. Neu ve mau
        cua mode luon thi banner dang noi doi.
        """
        self._paint("WAIT", f"{profile['mode']}  ·  {profile['name']}  ·  dang cho du lieu…")

    def show_profile(self, profile):
        mode = profile["mode"]
        self._paint(mode, f"{mode}  ·  {profile['name']}  ·  {MODE_NOTE.get(mode, '')}")

    def show_lost(self, profile, why=""):
        """Mat duong SiK — mat duong cuu sinh. Nang nhat."""
        self._paint("LOST", f"⚠  MAT KET NOI  ·  {profile['name']}  ·  {why}")

    def show_degraded(self, profile, why=""):
        """Mat nua ROS2 nhung SiK con — suy giam chuc nang, chua mat an toan.

        Mau khac han LOST: nham hai cai nay la nham giua "van bay ve duoc" va
        "khong con duong nao lai drone".
        """
        self._paint("DEGRADED", f"⚠  {profile['mode']}  ·  {why}")


class ConnectionPanel(QWidget):
    """Danh sach profile + nut Ket noi / Ngat. Dat trong dock ben phai."""

    connect_requested = Signal(dict)
    disconnect_requested = Signal()

    def __init__(self, profiles, parent=None):
        super().__init__(parent)
        self.connected = False
        self._scan_hint = "Chua chon nguon nao."
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

        self.btn_connect = QPushButton("Ket noi")
        self.btn_disconnect = QPushButton("Ngat")
        self.btn_scan = QPushButton("Quet lai cong USB")
        self.btn_connect.clicked.connect(self._connect)
        self.btn_disconnect.clicked.connect(self.disconnect_requested)
        self.btn_scan.clicked.connect(self.rescan)

        self.hint = QLabel("Chua chon nguon nao.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#8a9199;")

        row = QHBoxLayout()
        row.addWidget(self.btn_connect)
        row.addWidget(self.btn_disconnect)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Nguon ket noi"))
        lay.addWidget(self.list, 1)
        lay.addWidget(self.btn_scan)
        lay.addLayout(row)
        lay.addWidget(self.hint)

        self.rescan()
        self.set_connected(False)

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
                mark = "  ⟲" if p.get("writable") else "  ⚠ khong co quyen"
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
            self._scan_hint = ("Co cong USB nhung KHONG CO QUYEN mo. Chay:\n"
                               "sudo usermod -aG dialout $USER\nroi DANG XUAT / DANG NHAP lai.")
        elif n:
            self._scan_hint = f"Tim thay {n} cong USB."
        else:
            self._scan_hint = "Khong thay cong USB nao — cam radio roi bam Quet lai."
        if not self.connected:
            self.hint.setText(self._scan_hint)

    def set_connected(self, connected, profile=None):
        self.connected = connected
        self.list.setEnabled(not connected)
        self.btn_disconnect.setEnabled(connected)
        self._sync_buttons()
        if connected:
            # "da mo nguon", khong phai "da co drone" — xem ModeBanner.show_waiting
            self.hint.setText(f"Dang mo: {profile['name']}")
        else:
            # Ket qua quet co gia tri hon cau chung chung: no noi vi sao danh sach
            # trong, hoac vi sao cam radio roi ma van khong ket noi duoc.
            self.hint.setText(self._scan_hint if self.list.currentRow() < 0 else "")

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
        path, _ = QFileDialog.getOpenFileName(self, "Chon file .tlog", start, "Telemetry log (*.tlog)")
        if not path:
            QMessageBox.information(self, "REPLAY", "Chua chon file .tlog nao.")
        return path
