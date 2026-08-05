"""Tab Flight — map nen + overlay HUD (Phu luc 7.7).

Qt Designer xep widget bang layout: chung nam canh nhau, khong de len nhau. Man
hinh bay can la ban/telemetry NOI DE len map, nen phan nay lam bang code: overlay
la con truc tiep cua tab, KHONG nam trong layout nao, toa do tinh tay trong
resizeEvent va goi .raise_() de noi len tren map.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QLabel, QMenu, QWidget

from core import authority, bus
from core.field import REGISTRY
from laptop.widgets.attitude import AttitudeWidget
from laptop.widgets.compass import Compass
from laptop.widgets.map_widget import MapWidget
from laptop.widgets.telemetry_bar import TelemetryBar

MARGIN = 12


class FlightTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = None

        self.map = MapWidget(self)
        self.compass = Compass(self)
        self.attitude = AttitudeWidget(self)
        self.telemetry = TelemetryBar(self)

        self.warn = QLabel(self)
        self.warn.setAlignment(Qt.AlignCenter)
        self.warn.setStyleSheet(
            "background:rgba(192,57,43,220);color:#fff;font-weight:bold;padding:5px;"
        )
        self.warn.hide()

        for w in (self.compass, self.attitude, self.telemetry, self.warn):
            w.raise_()
            # Click xuyen qua overlay xuong map (de con click-to-goto).
            w.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.map.setContextMenuPolicy(Qt.CustomContextMenu)
        self.map.customContextMenuRequested.connect(self._menu)

        # Home va rao khong phai dai luong lien tuc, chung ve mot lan roi thoi —
        # nen doc thang tu bus, khong qua REGISTRY (o do qua 2 giay la het tuoi).
        bus.on("home", lambda e: self.map.set_home(e["data"]["lat"], e["data"]["lon"]))
        bus.on("fence", lambda e: self.map.set_fence(e["data"]))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(200)

    def set_mode(self, mode):
        self.mode = mode
        if mode is None:
            self.map.reset()

    # ------------------------------------------------------------------

    def refresh(self):
        """Doc tu trong tai da nguon, khong doc thang tu adapter."""
        lat, src = REGISTRY.best("position.lat")
        lon, _ = REGISTRY.best("position.lon")
        if lat is not None and lon is not None:
            self.map.set_position(lat, lon)
            if self.map.home is None:
                # Tam thoi thoi: HOME_POSITION cua FC ve toi la de len (topic
                # "home" o tren). Noi vao giua chuyen bay thi diem dinh vi dau
                # tien KHONG phai home — vong rao lay tam la home nen phai doi.
                self.map.set_home(lat, lon)

        hdg, _ = REGISTRY.best("attitude.heading")
        if hdg is None:
            hdg, _ = REGISTRY.best("position.heading")
        self.compass.set_heading(hdg)

        roll, _ = REGISTRY.best("attitude.roll")
        pitch, _ = REGISTRY.best("attitude.pitch")
        self.attitude.set_attitude(roll, pitch)

        alt, asrc = REGISTRY.best("position.alt_rel")
        spd, ssrc = REGISTRY.best("vfr.groundspeed")
        volt, vsrc = REGISTRY.best("battery.voltage")
        sats, gsrc = REGISTRY.best("gps.sats")
        mode, msrc = REGISTRY.best("heartbeat.mode")
        self.telemetry.set_cell("ALT", alt, asrc)
        self.telemetry.set_cell("SPD", spd, ssrc)
        self.telemetry.set_cell("PIN", volt, vsrc, "{:.2f}")
        self.telemetry.set_cell("SAT", sats, gsrc, "{:.0f}")
        self.telemetry.set_cell("MODE", mode, msrc)
        # Gia tri dai ra thi bar phai rong ra theo, khong duoc cat chu.
        if self.telemetry.sizeHint() != self.telemetry.size():
            self._place_telemetry()

        # Kich ban #8: hai nguon lech vi tri qua nguong
        div = REGISTRY.position_divergence_m()
        if div is not None and div > 5.0:
            self.warn.setText(f"⚠ HAI NGUON LECH VI TRI {div:.0f} m")
            self.warn.show()
        else:
            self.warn.hide()

    def _menu(self, point):
        """Click phai tren map -> GUIDED + bay toi (chi khi cam quyen MANUAL)."""
        if self.mode not in ("REAL", "SIM"):
            return
        lat, lon = self.map.latlon_at(point)
        menu = QMenu(self)
        act = menu.addAction(f"GUIDED + bay toi {lat:.5f}, {lon:.5f}")
        if authority.AUTHORITY != authority.GCS:
            act.setEnabled(False)
            menu.addAction("(quyen dang thuoc ve ROS2)").setEnabled(False)
        if menu.exec(QCursor.pos()) is act:
            authority.dispatch({"target": "sik", "action": "mode", "args": {"name": "GUIDED"}})
            authority.dispatch(
                {"target": "sik", "action": "goto", "args": {"lat": lat, "lon": lon}}
            )

    def resizeEvent(self, e):
        w, h = self.width(), self.height()
        self.map.setGeometry(0, 0, w, h)

        m = MARGIN
        self.compass.move(w - self.compass.width() - m, m)
        self.attitude.move(w - self.attitude.width() - m,
                           h - self.attitude.height() - m)
        self._place_telemetry()
        self.warn.setGeometry(m, m, max(240, w // 2), 28)
        super().resizeEvent(e)

    def _place_telemetry(self):
        self.telemetry.adjustSize()
        self.telemetry.move(MARGIN, self.height() - self.telemetry.height() - MARGIN)
