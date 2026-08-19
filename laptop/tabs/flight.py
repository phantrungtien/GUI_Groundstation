"""Tab Flight — map nen + overlay HUD (Phu luc 7.7).

Qt Designer xep widget bang layout: chung nam canh nhau, khong de len nhau. Man
hinh bay can la ban/telemetry NOI DE len map, nen phan nay lam bang code: overlay
la con truc tiep cua tab, KHONG nam trong layout nao, toa do tinh tay trong
resizeEvent va goi .raise_() de noi len tren map.
"""

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QLabel, QMenu, QWidget

from core import authority, bus
from core.adapters.sik import WP_MAX
from core.field import REGISTRY
from core.i18n import t
from laptop.widgets.attitude import AttitudeWidget
from laptop.widgets.compass import Compass
from laptop.widgets.map_widget import MapWidget
from laptop.widgets.telemetry_bar import TelemetryBar, batt_level, gps_level
from laptop.widgets.video import VideoView

MARGIN = 12
PIP_W, PIP_H = 256, 192  # o camera goc tren-trai; tab Camera moi la cho xem ky

# Do cao chon duoc cho waypoint dat bang chuot. Danh sach chu khong o nhap so:
# menu la thu duy nhat o day, ma hop thoai nhap lieu thi lam nut do chet trong
# vai giay (xem ControlTab._takeoff) — doi thang muc 2.1.
ALTS = (10, 15, 20, 30, 50, 80)
# Nap de len nhiem vu trong luc drone dang bay AUTO theo chinh nhiem vu do: FC
# nhay sang WP1 cua duong bay moi ngay lap tuc. Bam lai trong ngan nay de xac
# nhan — cung cach TAKEOFF o che do REAL dang lam.
CONFIRM_S = 3.0

# --- Nhich vi tri bang ban phim -------------------------------------------
#
# Gui VAN TOC chu khong toa do — ly do va so do nam o `sik.py`, action "nudge".
# Quang duong = tich phan van toc, nen giu phim lau thi di xa: go nhe mot cai la
# nhich mot chut, giu thi cang luc cang nhanh toi tran.
NUDGE = {
    Qt.Key_Up: (1, 0, 0),        # bac (ban do ve huong bac len tren)
    Qt.Key_Down: (-1, 0, 0),
    Qt.Key_Right: (0, 1, 0),     # dong
    Qt.Key_Left: (0, -1, 0),
    Qt.Key_PageUp: (0, 0, -1),   # NED: len la vd AM
    Qt.Key_PageDown: (0, 0, 1),
}
NUDGE_V0 = 1.0     # m/s ngay khi cham phim
NUDGE_VMAX = 5.0   # tran toc do
NUDGE_RAMP = 2.0   # m/s cong them moi giay giu phim
# Nhip gui lai. Lenh van toc GUIDED cua ArduPilot het han sau ~3 s, va do trung vi
# cua duong SiK la 132 ms — 5 Hz vua du day de mot goi roi khong thanh mot khoang
# khung, ma van chi ~115 B/s tren chieu len dang trong.
NUDGE_HZ = 5


def _mmss(secs):
    return f"{int(secs) // 60}:{int(secs) % 60:02d}"


class FlightTab(QWidget):
    # Nap duong bay la mot LENH. No phai de lai vet o tab Messages va o
    # logs/commands.log y nhu ARM/TAKEOFF, khong duoc chi hien thoang tren ban do.
    log = Signal(str, int)   # (chu da dich, muc do) — xem ControlTab.log

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = None
        self._wp_confirm = 0.0  # lan bam dau cua "nap de len" khi dang bay AUTO
        self._held = set()      # phim huong dang giu
        self._nudge_since = 0.0  # luc phim dau tien xuong — goc tinh ramp toc do
        self._armed_at = None    # luc `armed` lat len True — goc dem gio bay
        # Phim chi toi tab nao dang giu focus, nen phai xin focus tuong minh.
        self.setFocusPolicy(Qt.StrongFocus)

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

        # O camera cho phi cong theo doi ma khong roi man hinh bay. Tat mac dinh:
        # ai can video thi bat, con man hinh bay mac dinh phai la ban do.
        self.video = VideoView(parent=self)
        self.video.hide()

        for w in (self.compass, self.attitude, self.telemetry, self.warn, self.video):
            w.raise_()
            # Click xuyen qua overlay xuong map (de con click-to-goto).
            w.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.map.setContextMenuPolicy(Qt.CustomContextMenu)
        self.map.customContextMenuRequested.connect(self._menu)

        # Home, rao va duong bay khong phai dai luong lien tuc, chung ve mot lan
        # roi thoi — nen doc thang tu bus, khong qua REGISTRY (o do qua 2 giay la
        # het tuoi, ma duong bay thi dung yen suot ca chuyen).
        bus.on("home", lambda e: self.map.set_home(e["data"]["lat"], e["data"]["lon"]))
        bus.on("fence", lambda e: self.map.set_fence(e["data"]))
        bus.on("wp", self._on_wp)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(200)

        self._nudge_timer = QTimer(self)
        self._nudge_timer.timeout.connect(self._nudge_tick)

    def set_mode(self, mode):
        self.mode = mode
        if mode is None:
            self.map.reset()

    def set_video_source(self, source):
        """Dung chung mot `VideoSource` voi tab Camera — mot ket noi, hai cho ve."""
        self.video.set_source(source)

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
        self.telemetry.set_cell("MODE", mode, msrc)

        # --- ARM: canh quat co the quay hay khong ------------------------
        # Do la boolean quan trong nhat tren man hinh bay, va mode KHONG thay
        # duoc cho no: "GUIDED" khong noi gi ve chuyen dong co dang quay hay dung.
        # Mau do o day khong co nghia la HONG — nghia la dung lai gan.
        armed, arsrc = REGISTRY.best("heartbeat.armed")
        self.telemetry.set_cell(
            "ARM", None if armed is None else t("tlm.armed" if armed else "tlm.disarmed"),
            arsrc, level="crit" if armed else None)

        # Dem gio tu luc ARM. Cung voi phan tram pin, day la ve thu hai cua cung
        # mot cau hoi "con bay duoc bao lau" — va la ve KHONG ai khac cung cap:
        # FC khong gui thoi gian bay qua MAVLink.
        #
        # Moc lay o suon len cua `armed`, khong phai luc bam nut: lenh ARM co the
        # bi FC tu choi, va con so phai dem tu luc dong co THAT SU song.
        if armed and self._armed_at is None:
            self._armed_at = time.time()
        elif not armed and armed is not None:
            self._armed_at = None
        self.telemetry.set_cell(
            "BAY", None if self._armed_at is None else _mmss(time.time() - self._armed_at),
            arsrc)

        # --- PIN: mau lay tu PHAN TRAM, chu khong tu dien ap -------------
        # Dien ap van la thu HIEN ra (do la con so nguoi bay quen doc), nhung
        # nguong thi bam vao phan tram FC bao — xem chu thich o telemetry_bar.py.
        pct, _ = REGISTRY.best("battery.remaining")
        self.telemetry.set_cell(
            "PIN", volt, vsrc, "{:.2f}", level=batt_level(pct),
            tip=t("tlm.batt_pct", pct=pct) if pct is not None else t("tlm.batt_nopct"))

        # --- SAT: mau lay tu fix_type, chu khong tu so ve tinh -----------
        fix, _ = REGISTRY.best("gps.fix_type")
        self.telemetry.set_cell(
            "SAT", sats, gsrc, "{:.0f}", level=gps_level(fix),
            tip=t(f"tlm.fix{int(fix)}") if fix is not None else t("tlm.fix_none"))
        # Gia tri dai ra thi bar phai rong ra theo, khong duoc cat chu.
        if self.telemetry.sizeHint() != self.telemetry.size():
            self._place_telemetry()

        # Kich ban #8: hai nguon lech vi tri qua nguong
        div = REGISTRY.position_divergence_m()
        if div is not None and div > 5.0:
            self.warn.setText(t("fly.diverge", m=div))
            self.warn.show()
        else:
            self.warn.hide()

    def _on_wp(self, env):
        """Duong bay tu FC ve. Rieng ket qua NAP thi phai ra log, khong ve ban do."""
        w = env["data"].get("write")
        if w is None:
            self.map.set_wp(env["data"])
            return
        if w["ok"]:
            # Nap xong thi bo ban nhap di: giu lai hai duong chong len nhau tren
            # ban do, mot cai la ke hoach cu, khong ai phan biet duoc nua.
            self.map.drop_draft(all_of_them=True)
            self._say("fly.wp_ok", 5, n=w["n"])
        else:
            why = w.get("err") or t("fly.wp_fc_denied", code=w["result"])
            self._say("fly.wp_fail", 3, why=why)

    def _menu(self, point):
        """Click phai tren map: dat waypoint, nap len FC, hay bay toi mot diem.

        Bat/tat camera cung nam o day chu khong lam nut rieng: o PiP de click
        xuyen qua xuong map, nen no khong tu nhan duoc cu bam nao.
        """
        menu = QMenu(self)
        live = self.mode in ("REAL", "SIM")
        lat, lon = self.map.latlon_at(point)
        n = len(self.map.draft)

        act_add = menu.addAction(t("menu.wp_add", n=n + 1, alt=self.map.wp_alt))
        act_add.setEnabled(n < WP_MAX)
        alt_menu = menu.addMenu(t("menu.wp_alt", alt=self.map.wp_alt))
        alt_acts = {alt_menu.addAction(f"{a} m"): a for a in ALTS}
        act_undo = menu.addAction(t("menu.wp_undo", n=n)) if n else None
        act_clear = menu.addAction(t("menu.wp_clear", n=n)) if n else None

        act_send = act_wipe = None
        if live:
            menu.addSeparator()
            if n:
                act_send = menu.addAction(t("menu.wp_send", n=n))
                if self._auto_flying():
                    act_send.setText(t("menu.wp_send_over", n=n))
            if self.map.wp.get("items"):
                act_wipe = menu.addAction(t("menu.wp_wipe"))
            menu.addSeparator()
            act_goto = menu.addAction(t("menu.goto", lat=lat, lon=lon))
        else:
            act_goto = None

        act_video = menu.addAction(t("menu.cam_hide") if self.video.isVisible()
                                   else t("menu.cam_show"))

        chosen = menu.exec(QCursor.pos())
        if chosen is None:
            return
        if chosen is act_video:
            self.video.setVisible(not self.video.isVisible())
        elif chosen is act_add:
            self.map.add_draft(lat, lon)
        elif chosen in alt_acts:
            self.map.wp_alt = float(alt_acts[chosen])
            self.map.update()
        elif chosen is act_undo:
            self.map.drop_draft()
        elif chosen is act_clear:
            self.map.drop_draft(all_of_them=True)
        elif chosen is act_send:
            self._send_wp()
        elif chosen is act_wipe:
            self._report(t("act.wp_wipe"),
                         authority.dispatch({"target": "sik", "action": "wp_clear"}))
        elif chosen is act_goto:
            authority.dispatch({"target": "sik", "action": "mode", "args": {"name": "GUIDED"}})
            authority.dispatch(
                {"target": "sik", "action": "goto", "args": {"lat": lat, "lon": lon}}
            )

    def _auto_flying(self):
        """Dang bay theo chinh nhiem vu sap bi ghi de? True/False."""
        return (REGISTRY.value("heartbeat.mode") == "AUTO"
                and REGISTRY.value("heartbeat.armed") is True)

    # ---- nhich vi tri bang ban phim ----------------------------------

    def _nudge_block(self):
        """Ly do KHONG duoc nhich, hay None neu duoc. Bon chot, khong bot cai nao."""
        if self.mode not in ("REAL", "SIM"):
            return t("nudge.no_mode")
        if REGISTRY.value("heartbeat.armed") is not True:
            return t("nudge.not_armed")
        if REGISTRY.value("heartbeat.landed") is True:
            return t("nudge.on_ground")
        fc = REGISTRY.value("heartbeat.mode")
        if fc != "GUIDED":
            # KHONG tu chuyen mode ho: dang bay AUTO ma mot phim lo tay keo sang
            # GUIDED la bo ngang nhiem vu giua chung. Nguoi bay tu chuyen.
            return t("nudge.wrong_mode", mode=fc)
        return None

    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return  # Qt tu ban lien tuc khi giu phim — nhip do _nudge_timer giu
        key = e.key()
        if key in NUDGE:
            why = self._nudge_block()
            if why:
                self._say("nudge.blocked", 4, why=why)
                return
            if not self._held:
                self._nudge_since = time.time()
                self._nudge_timer.start(int(1000 / NUDGE_HZ))
            self._held.add(key)
        elif key == Qt.Key_Space:
            self._nudge_stop(t("nudge.why_space"))
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self._nudge_stop(None)
            self._report(t("act.resume"), authority.dispatch(
                {"target": "sik", "action": "mode", "args": {"name": "AUTO"}}))
        elif key == Qt.Key_L:
            self._nudge_stop(None)
            self._report(t("act.land_here"), authority.dispatch(
                {"target": "sik", "action": "land"}))
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.isAutoRepeat():
            return
        if e.key() not in self._held:
            return super().keyReleaseEvent(e)
        self._held.discard(e.key())
        if not self._held:
            self._nudge_stop(t("nudge.why_release"))

    def focusOutEvent(self, e):
        """Mat focus giua luc dang giu phim (alt-tab, bam sang tab khac).

        Khong co cho nay thi keyReleaseEvent KHONG BAO GIO toi, va drone giu
        nguyen van toc cuoi cho toi khi lenh GUIDED het han — bay mu ba giay.
        """
        self._nudge_stop(t("nudge.why_focus"))
        super().focusOutEvent(e)

    def _nudge_tick(self):
        if not self._held:
            return
        if why := self._nudge_block():  # mode/armed doi giua chung thi dung ngay
            self._nudge_stop(None)
            self._say("nudge.stopped", 4, why=why)
            return
        v = min(NUDGE_VMAX, NUDGE_V0 + NUDGE_RAMP * (time.time() - self._nudge_since))
        n = sum(NUDGE[k][0] for k in self._held)
        e = sum(NUDGE[k][1] for k in self._held)
        d = sum(NUDGE[k][2] for k in self._held)
        # Chuan hoa: giu hai phim cheo nhau khong duoc nhanh hon 1,41 lan mot phim.
        mag = (n * n + e * e + d * d) ** 0.5 or 1.0
        authority.dispatch({"target": "sik", "action": "nudge", "args": {
            "vn": v * n / mag, "ve": v * e / mag, "vd": v * d / mag}})

    def _nudge_stop(self, why):
        """Van toc 0 = dung ngay tai cho drone dang o, khong can biet cho do o dau.

        Moc "dang nhich hay khong" lay o timer chu KHONG o `self._held`: nguoi goi
        (keyReleaseEvent) da xoa phim khoi `_held` truoc khi goi vao day, nen doc
        `_held` o day luon thay rong va lenh dung khong bao gio duoc gui — drone
        giu nguyen van toc cuoi cho toi khi lenh GUIDED het han ba giay sau.

        Khong hoi lai `_nudge_block()`: dung la viec luon phai lam duoc. Mode vua
        doi hay link vua chap chon deu khong phai ly do de nuot lenh dung, va mot
        goi van toc 0 thua thi vo hai.
        """
        active = self._nudge_timer.isActive()
        self._held.clear()
        self._nudge_timer.stop()
        if self.mode not in ("REAL", "SIM"):
            return
        if not active and why != t("nudge.why_space"):
            return  # khong nhich thi khong co gi de dung
        authority.dispatch({"target": "sik", "action": "nudge",
                            "args": {"vn": 0.0, "ve": 0.0, "vd": 0.0}})
        if why:
            self._say("nudge.hold", 5, why=why)

    def _send_wp(self):
        if self._auto_flying() and time.time() - self._wp_confirm > CONFIRM_S:
            self._wp_confirm = time.time()
            self._say("fly.wp_overwrite", 4, sec=CONFIRM_S)
            return
        self._wp_confirm = 0.0
        items = [list(p) for p in self.map.draft]
        self._report(t("act.wp_send", n=len(items)), authority.dispatch(
            {"target": "sik", "action": "wp_write", "args": {"items": items}}))

    def _say(self, key, sev=5, **kw):
        self.log.emit(t(key, **kw), sev)

    def _report(self, what, result):
        if "error" in result:
            self._say("log.refused", 3, what=what, why=result["error"])
        elif "stale" in result:
            self._say("log.queued_stale", 4, what=what, how=t("log.silent_never"))
        else:
            self._say("log.sent_wait", 5, what=what)

    def resizeEvent(self, e):
        w, h = self.width(), self.height()
        self.map.setGeometry(0, 0, w, h)

        m = MARGIN
        self.compass.move(w - self.compass.width() - m, m)
        self.attitude.move(w - self.attitude.width() - m,
                           h - self.attitude.height() - m)
        self._place_telemetry()
        self.warn.setGeometry(m, m, max(240, w // 2), 28)

        # Duoi cho thanh canh bao, KE CA khi no dang an: o camera dung yen mot
        # cho, khong nhay len nhay xuong theo luc hai nguon lech vi tri.
        pw = min(PIP_W, w // 3)
        self.video.setGeometry(m, m + 28 + 6, pw, pw * PIP_H // PIP_W)
        super().resizeEvent(e)

    def _place_telemetry(self):
        self.telemetry.adjustSize()
        self.telemetry.move(MARGIN, self.height() - self.telemetry.height() - MARGIN)
