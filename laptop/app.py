"""Cua so chinh. Chay: python3 -m laptop.app

Vao thang GUI, panel chon nguon nam o dock ben phai. App khong tu ket noi:
chua bam "Ket noi" thi banner xam va khong co byte nao chay.
"""

import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
)

from core import authority, bus, i18n
from core.adapters.remote import RemoteAdapter
from core.adapters.sik import STALE, SikAdapter
from core.field import REGISTRY
from core.i18n import t
from laptop.connection import ROOT, ConnectionPanel, ModeBanner, load_profiles
from laptop.link_faults import LinkFaults
from laptop.link_status import LinkStatus
from laptop.replay_bar import ReplayBar
from laptop.tabs.control import ControlTab
from laptop.tabs.flight import FlightTab
from laptop.tabs.messages import MessagesTab
from laptop.tabs.settings import SettingsTab
from laptop.tabs.status import StatusTab
from laptop.widgets.video import VideoSource, VideoView, url_for
from laptop.ui.main_window_ui import Ui_MainWindow

# Nen toi la chuan de facto cua GCS: ngoai nang do choi, nhin lau do moi.
DARK = """
QWidget { background:#232629; color:#dcdcdc; }
QTabWidget::pane { border:1px solid #3a3f44; }
QTabBar::tab { background:#2b2f33; padding:6px 14px; border:1px solid #3a3f44; }
QTabBar::tab:selected { background:#3a4048; }
QListWidget, QTableView, QTextEdit { background:#1b1e20; border:1px solid #3a3f44; }
QPushButton { background:#3a4048; border:1px solid #4a5058; padding:5px 12px; }
QPushButton:hover { background:#454c55; }
QPushButton:disabled { background:#2b2f33; color:#6b7279; }
QStatusBar { background:#1b1e20; }
QDockWidget::title { background:#2b2f33; padding:5px; }
"""

TITLE = "GCS — ArduCopter"


def mount(page, widget):
    """Nhet widget viet tay vao mot tab trong do Designer de san."""
    lay = QVBoxLayout(page)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(widget)


def placeholder(text):
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet("color:#6b7279;")
    return lbl


class MainWindow(QMainWindow):
    def __init__(self, profiles):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.resize(1100, 700)

        self.adapter = None
        self.remote = None
        self.profile = None
        self.mode = None  # N3 doc cai nay de khoa nut o che do REPLAY
        self.setWindowTitle(TITLE)

        # Banner chiem het chieu ngang, day tabWidget xuong mot hang.
        self.banner = ModeBanner()
        self.ui.gridLayout.addWidget(self.banner, 0, 0)
        self.ui.gridLayout.addWidget(self.ui.tabWidget, 1, 0)
        # ponytail: mo o Status vi tab Flight con rong. Doi ve Flight khi N4 xong.
        self.ui.tabWidget.setCurrentWidget(self.ui.Status)

        self.status_tab = StatusTab()
        self.messages_tab = MessagesTab()
        self.control_tab = ControlTab()
        self.flight_tab = FlightTab()
        mount(self.ui.Status, self.status_tab)
        mount(self.ui.Messages, self.messages_tab)
        mount(self.ui.Control, self.control_tab)
        mount(self.ui.Flight, self.flight_tab)
        self.control_tab.log.connect(self._on_cmd_log)
        # Nap duong bay cung la lenh xuong FC — vao chung mot duong log voi
        # ARM/TAKEOFF, khong lam duong rieng.
        self.flight_tab.log.connect(self._on_cmd_log)

        # Mot nguon video, hai cho ve: tab Camera de xem ky, o PiP tren tab Flight
        # de phi cong theo doi ma khong roi ban do. Pi chi phai phuc vu mot luong.
        # ponytail: addTab bang code, khoi phai sua .ui roi chay lai build_ui.sh.
        self.video = VideoSource(self)
        self.camera_tab = VideoView(self.video)
        self.ui.tabWidget.addTab(self.camera_tab, "")
        self.flight_tab.set_video_source(self.video)

        self.settings_tab = SettingsTab()
        self.ui.tabWidget.addTab(self.settings_tab, "")

        # Trong tai da nguon an theo bus, tab Flight doc lai tu no.
        bus.on("*", REGISTRY.feed)

        self.replay_bar = ReplayBar()
        self.replay_bar.hide()
        self.ui.gridLayout.addWidget(self.replay_bar, 2, 0)

        self.panel = ConnectionPanel(profiles)
        self.panel.connect_requested.connect(self.connect_to)
        self.panel.disconnect_requested.connect(self.disconnect)
        self.conn_dock = dock = QDockWidget(self)
        dock.setWidget(self.panel)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

        # Mo phong dut duong truyen: CHI o SIM. O REAL, mot o tick lam cam telemetry
        # ngay canh nut do la thu khong duoc phep ton tai.
        self.link_faults = LinkFaults()
        self.link_faults.log.connect(lambda s, _sev: self.ui.statusbar.showMessage(s, 6000))
        self.faults_dock = QDockWidget(self)
        self.faults_dock.setWidget(self.link_faults)
        self.faults_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.faults_dock)
        self.faults_dock.hide()

        self.link_status = LinkStatus()
        self.ui.statusbar.addPermanentWidget(self.link_status)
        bus.on("*", self.link_status.on_envelope)

        # Banner phai bam theo suc khoe link, khong phai theo mode da chon.
        self._health = QTimer(self)
        self._health.timeout.connect(self._refresh_banner)
        self._health.start(500)

        i18n.on_change(self._retext)

    def _retext(self):
        tabs = self.ui.tabWidget
        for w, key in ((self.ui.Flight, "tab.flight"), (self.ui.Status, "tab.status"),
                       (self.ui.Control, "tab.control"), (self.ui.Messages, "tab.messages"),
                       (self.camera_tab, "tab.camera"), (self.settings_tab, "tab.settings")):
            tabs.setTabText(tabs.indexOf(w), t(key))
        self.conn_dock.setWindowTitle(t("dock.conn"))
        self.faults_dock.setWindowTitle(t("dock.faults"))

    def _on_cmd_log(self, text, sev=5):
        """Ket qua moi lan bam nut: thanh trang thai + tab Thong bao + file.

        Ba cho vi ba muc dich khac nhau. Thanh trang thai de thay ngay; tab Thong
        bao de doc lai trong chuyen bay; file de sau chuyen bay con truy duoc vi
        sao mot lenh khong di. Thieu file thi cau hoi "sao no khong arm duoc" chi
        con cach doan.
        """
        self.ui.statusbar.showMessage(text, 6000)
        self.messages_tab.add_local(text, sev=sev)
        try:
            line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  [{self.mode or '-'}]  {text}\n"
            (ROOT / "logs" / "commands.log").open("a", encoding="utf-8").write(line)
        except OSError:
            pass  # het dia hay khong ghi duoc thi cung khong duoc lam chet giao dien

    def connect_to(self, profile):
        self.disconnect()
        self.profile = profile
        self.mode = profile["mode"]
        self.setWindowTitle(f"[{self.mode}] {TITLE}")  # nguon da ghi ro o banner
        self.banner.show_waiting(profile)  # chua byte nao ve thi chua duoc noi la da noi
        self.panel.set_connected(True, profile)

        self.adapter = SikAdapter(profile, logdir=ROOT / "logs")
        # Signal la ranh gioi thread duy nhat: slot nay chay o main thread.
        self.adapter.envelope.connect(bus.emit_envelope)
        self.adapter.failed.connect(self._on_failed)
        self.adapter.start()
        authority.register("sik", self.adapter)

        # Nua ROS2: chi noi khi profile khai bao. Mat no thi nua SiK van chay.
        if profile.get("remote"):
            self.remote = RemoteAdapter(profile["remote"])
            self.remote.envelope.connect(bus.emit_envelope)
            self.remote.failed.connect(self._on_remote_failed)
            self.remote.start()
            authority.register("remote", self.remote)

            # Video di cung nua WiFi va chi nua do — SiK (~470-3200 B/s) khong du
            # cho noi mot khung JPEG. Khong co `remote` thi khong co video, dung.
            url = url_for(profile["remote"])
            if url:
                self.video.start(url)

        self.control_tab.set_mode(self.mode)
        self.flight_tab.set_mode(self.mode)
        self.status_tab.attach(self.adapter)
        self.replay_bar.attach(self.adapter if self.mode == "REPLAY" else None)
        self.link_faults.attach(self.adapter if self.mode == "SIM" else None,
                                self.remote if self.mode == "SIM" else None)
        self.faults_dock.setVisible(self.mode == "SIM")
        self.ui.statusbar.showMessage(
            t("conn.opening_msg", target=profile.get("conn") or profile.get("path")), 5000)

    def _refresh_banner(self):
        """Hai nua hong theo hai kieu khac nhau — banner phai noi ro nua nao.

        Gop chung lai thanh mot dong "MAT KET NOI" la sai ca ve muc do nghiem
        trong lan ve viec phai lam gi tiep (muc 1.2 va 1.3 cua ke hoach).

        Nguon su that la lan cuoi co goi tu drone, lay tu LinkStatus. Khong duoc
        suy tu "adapter dang chay": `udp:` mo bao gio cung thanh cong.
        """
        if not self.profile:
            return
        now = time.time()

        def age(src):
            seen = self.link_status.last_seen.get(src)
            return None if seen is None else now - seen

        sik = age(SikAdapter.SRC)
        remote = age(RemoteAdapter.SRC)
        has_remote = bool(self.profile.get("remote"))

        if sik is None:
            self.banner.show_waiting(self.profile)
        elif sik > STALE:
            # Mat duong cuu sinh. Nang nhat, bat ke nua ROS2 con song hay khong.
            self.banner.show_lost(self.profile, t("conn.sik_silent", n=int(sik)))
        elif has_remote and (remote is None or remote > STALE):
            # Kieu hong A: WiFi rot nhung companion con song. Tu khi laptop cam
            # toan quyen thi day khong con la mat quyen dieu khien — node offboard
            # khong lai duoc dau ma so. Mat la mat TAM NHIN: video, vi tri nguon
            # thu hai, trang thai node. Van phai bao, chi la bao dung muc do.
            self.banner.show_degraded(self.profile, t("conn.degraded"))
        else:
            self.banner.show_profile(self.profile)

    def disconnect(self):
        for name, attr in (("sik", "adapter"), ("remote", "remote")):
            a = getattr(self, attr, None)
            if a:
                a.stop()
                setattr(self, attr, None)
            authority.unregister(name)
        self.video.stop()
        self.profile = self.mode = None
        self.setWindowTitle(TITLE)
        self.banner.show_disconnected()
        self.panel.set_connected(False)
        self.control_tab.set_mode(None)
        self.flight_tab.set_mode(None)
        self.status_tab.attach(None)
        self.replay_bar.attach(None)
        self.link_faults.attach(None, None)
        self.faults_dock.hide()

    def _on_remote_failed(self, why):
        """Nua ROS2 dut. TUYET DOI khong duoc dung nua SiK theo.

        RemoteAdapter tu noi lai deu dan, nen day chi la thong bao. Mat WiFi la
        chuyen binh thuong ngoai bai bay; mat no khong duoc lam mat duong cuu sinh.
        """
        self.ui.statusbar.showMessage(f"ROS2: {why}", 4000)

    def _on_failed(self, why):
        # Da tung co du lieu roi moi dut != khong noi duoc ngay tu dau.
        # Truong hop dau: drone dang bay, KHONG duoc bat hop thoai modal chan het
        # man hinh (che map, che nut do). Bao bang banner do + status bar.
        was_flying = self.link_status.last_seen.get(SikAdapter.SRC) is not None
        profile = self.profile
        self.ui.statusbar.showMessage(t("conn.sik_lost", why=why))
        # Chi ha nua SiK. Nua ROS2 con song thi de no chay tiep — no van cho biet
        # drone dang lam gi, va van co the noi lai.
        self._stop_sik()
        if was_flying:
            self.banner.show_lost(profile, why)
        else:
            QMessageBox.critical(self, t("conn.fail_title"), why)

    def _stop_sik(self):
        if self.adapter:
            self.adapter.stop()
            self.adapter = None
        authority.unregister("sik")
        self.control_tab.set_mode(None)
        self.replay_bar.attach(None)

    def closeEvent(self, e):
        self.disconnect()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK)
    i18n.load()  # phai truoc MainWindow: widget lay chu ngay trong __init__
    win = MainWindow(load_profiles())
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
