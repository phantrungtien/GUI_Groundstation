"""Backend cua man bay cam ung: giu trang thai, chuyen lenh, mo/dong ket noi.

Hai kieu chay:
  - NAM TRONG app laptop (mac dinh): MainWindow cam ket noi va dua vao day bang
    `attach()`; `Commands` va nguon video cung la cua MainWindow — MOT ket noi,
    MOT bo theo doi ACK (hai bo la moi ACK ghi hai dong vao tab Thong bao).
  - TU CAM ket noi (`owns_connection=True`): cho ban dong goi dien thoai sau nay,
    khi khong co MainWindow. Luc do ngan keo ket noi trong QML moi hien.

KHONG co chot an toan nao viet moi o day. Chan ARM khi ga cao, TAKEOFF phai o
GUIDED, DISARM duoi dat thi force, theo doi ACK — tat ca nam o
`laptop/commands.py`, dung chung voi tab Dieu khien cua app laptop. Thanh truot
ben QML la phan XAC NHAN; goi toi day nghia la nguoi bay da truot het.
"""

import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QPoint, QTimer, Signal, Slot

from core import authority, bus, i18n
from core.adapters.remote import RemoteAdapter
from core.adapters.sik import STALE, WP_MAX, SikAdapter
from core.field import REGISTRY, haversine_m
from core.i18n import t
from laptop.commands import (MODES, NUDGE_HZ, NUDGE_V0, NUDGE_VMAX, WP_ALT_MAX,
                             WP_ALT_MIN, WP_ALTS,
                             WP_CONFIRM_S, Commands)
from laptop.connection import ROOT, detect_serial, load_profiles
from laptop.widgets.alerts import ERR_SEV, AlertBook
from laptop.widgets.attitude import AttitudeWidget
from laptop.widgets.compass import Compass
from laptop.widgets.map_widget import MapWidget
from laptop.widgets.telemetry_bar import batt_level, gps_level
from laptop.widgets.video import VideoSource, VideoView, url_for
from laptop.touch.items import WIDGETS

LIVE = ("REAL", "SIM")
DIVERGE_M = 5.0  # hai nguon vi tri lech hon chung nay thi keu — giong tab Bay cu


def _newest(pattern):
    """REPLAY voi mau `logs/*.tlog`: lay file moi nhat.

    ponytail: chua co hop chon file tren man cam ung — them khi can xem lai chuyen
    cu hon chuyen moi nhat.
    """
    files = sorted(ROOT.glob(pattern), key=lambda p: p.stat().st_mtime)
    return str(files[-1]) if files else None


class Backend(QObject):
    stateChanged = Signal()
    profilesChanged = Signal()
    langChanged = Signal()

    def __init__(self, profiles=None, cmd=None, video_src=None, owns_connection=False,
                 parent=None):
        super().__init__(parent)
        self.owns = owns_connection
        profiles = load_profiles() if profiles is None else profiles
        # Muc REAL khong co `conn` la KHUON cho cong tu quet — xem ConnectionPanel.
        self._template = next(
            (p for p in profiles if p.get("mode") == "REAL" and not p.get("conn")), {})
        self._fixed = [p for p in profiles if p is not self._template]
        self._profiles = []

        self.adapter = self.remote = self.profile = self.mode = None
        self.last_seen = {}
        self._armed_at = None
        self._state = {}
        self._wp_confirm = 0.0   # lan bam "nap" dau khi dang bay AUTO
        self._stick = (0.0, 0.0, 0.0)  # can ao: (dong, bac, len), tam [-1, 1]

        # Ban do, camera, la ban va chan troi la widget CU, ve len QML qua
        # WidgetItem. Viet lai bang QML la hai ban de lech nhau — xem items.py.
        self.map = MapWidget()
        self.video_src = video_src or VideoSource(self)
        self.video = VideoView(self.video_src)
        self.compass = Compass()
        self.attitude = AttitudeWidget()
        WIDGETS.update(map=self.map, video=self.video,
                       compass=self.compass, attitude=self.attitude)

        self.alerts = AlertBook()
        self.cmd = cmd or Commands(self)
        if self.owns:
            # Nam trong app laptop thi ket qua lenh di qua MainWindow._on_cmd_log
            # (tab Thong bao + commands.log), roi MainWindow day lai vao `alerts`.
            self.cmd.log.connect(self._on_log)
            bus.on("*", REGISTRY.feed)  # app laptop da tu dang ky cai nay
        bus.on("*", self._seen)
        # Home, rao, duong bay ve mot lan roi thoi — doc thang tu bus nhu FlightTab.
        bus.on("home", lambda e: self.map.set_home(e["data"]["lat"], e["data"]["lon"],
                                                   from_fc=True))
        bus.on("fence", lambda e: self.map.set_fence(e["data"]))
        bus.on("wp", self._on_wp)
        bus.on("text", lambda e: self.alerts.push(e["data"].get("text"),
                                                  e["data"].get("severity", 6)))
        i18n.signals.changed.connect(lambda _l: self.langChanged.emit())

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(200)
        self._nudge_timer = QTimer(self)
        self._nudge_timer.timeout.connect(self._nudge_tick)
        self.rescan()
        self.refresh()

    # ---- cho QML doc -------------------------------------------------------

    def _get_state(self):
        return self._state

    def _get_profiles(self):
        return [{"name": p["name"], "mode": p["mode"],
                 "target": p.get("conn") or p.get("path", ""),
                 "noperm": bool(p.get("detected") and not p.get("writable"))}
                for p in self._profiles]

    def _get_lang(self):
        return i18n.lang()

    state = Property("QVariantMap", _get_state, notify=stateChanged)
    profiles = Property("QVariantList", _get_profiles, notify=profilesChanged)
    lang = Property(str, _get_lang, notify=langChanged)
    ownsConnection = Property(bool, lambda self: self.owns, constant=True)
    modes = Property("QVariantList", lambda self: MODES, constant=True)
    wpAlts = Property("QVariantList", lambda self: list(WP_ALTS), constant=True)
    wpAltMin = Property(int, lambda self: WP_ALT_MIN, constant=True)
    wpAltMax = Property(int, lambda self: WP_ALT_MAX, constant=True)

    @Slot(str, "QVariantMap", str, result=str)
    def tf(self, key, args, _lang=""):
        """Chu da dich. `_lang` chi de QML danh lai khi doi ngon ngu."""
        return t(key, **(args or {}))

    # ---- trang thai --------------------------------------------------------

    def _seen(self, env):
        self.last_seen[env["src"]] = time.time()

    def _status(self, armed, fix):
        """(key, kwargs, muc) cho vien trang thai tren cung — giong banner app laptop."""
        if not self.profile:
            return "touch.st_none", {}, "none"
        if self.mode == "REPLAY":
            return "touch.st_replay", {}, "none"
        seen = self.last_seen.get(SikAdapter.SRC)
        if seen is None:
            return "touch.st_wait", {}, "warn"
        age = time.time() - seen
        if age > STALE:
            return "touch.st_lost", {"n": int(age)}, "crit"
        if armed:
            landed = REGISTRY.value("heartbeat.landed")
            return ("touch.st_armed", {}, "crit") if landed in (True, None) \
                else ("touch.st_flying", {}, "ok")
        if fix is not None and fix < 3:
            return "touch.st_nogps", {}, "warn"
        return "touch.st_ready", {}, "ok"

    def refresh(self):
        """Doc tu trong tai da nguon (nhu FlightTab.refresh), day ra QML."""
        # Da ngat ket noi thi man bay KHONG doc gi trong REGISTRY nua.
        #
        # `attach(None)` co xoa mot lan, nhung goi cuoi cung cua adapter ve SAU
        # do: QThread da join xong, con tin hieu xep hang thi den luc vong su
        # kien quay lai moi phat. Mot goi vi tri lot qua khe do la 200 ms sau
        # `refresh()` dung len mot home GIA ngay tai cho drone vua dung — do duoc
        # o e2e_sitl L1: `(10,8244209 / 106,6900736)`, tuc BAI DAP chu khong phai
        # cho cat canh, roi "ve nha bao nhieu met" dem tu cai cho sai do.
        #
        # Bit o cho DOC chu khong xoa REGISTRY moi nhip: REGISTRY la cua chung
        # (tab Trang thai, tab Phan tich che do truc tiep cung doc no), mot widget
        # quet sach kho chung theo nhip 5 Hz cua rieng no la tac dung phu di rat xa.
        v = REGISTRY.value if self.profile is not None else lambda *a, **k: None
        lat, lon = v("position.lat"), v("position.lon")
        if lat is not None and lon is not None:
            self.map.set_position(lat, lon)
            if self.map.home is None:
                self.map.set_home(lat, lon)  # home TAM — xem README "dau X home co the la GIA"
        hdg = v("attitude.heading")
        if hdg is None:
            hdg = v("position.heading")
        self.map.heading = hdg  # mui tam giac tren ban do quay cung kim la ban
        self.map.alt_rel = v("position.alt_rel")
        self.compass.set_heading(hdg)
        self.attitude.set_attitude(v("attitude.roll"), v("attitude.pitch"))

        armed = v("heartbeat.armed")
        if armed and self._armed_at is None:
            self._armed_at = time.time()  # suon len cua armed, khong phai luc bam
        elif not armed and armed is not None:
            self._armed_at = None

        fix, sats, hdop = v("gps.fix_type"), v("gps.sats"), v("gps.hdop")
        pct = v("battery.remaining")
        div = REGISTRY.position_divergence_m()
        dist = None
        if self.map.pos and self.map.home and self.map.home_from_fc:
            dist = haversine_m(*self.map.pos, *self.map.home)
        key, kw, level = self._status(armed, fix)

        self._state = {
            "connected": self.profile is not None,
            "live": self._live(),
            "mode": self.mode or "",
            "profile": self.profile["name"] if self.profile else "",
            "status": t(key, **kw), "statusLevel": level,
            "fcMode": v("heartbeat.mode") or "",
            "armed": armed is True,
            "alt": v("position.alt_rel"),
            "dist": dist,
            "hs": v("vfr.groundspeed"),
            "vs": v("vfr.climb"),
            "heading": hdg,
            "flightTime": 0 if self._armed_at is None else int(time.time() - self._armed_at),
            "battPct": pct, "volt": v("battery.voltage"),
            "battLevel": batt_level(pct) or "ok",
            "sats": sats, "gpsLevel": gps_level(fix, sats, hdop)[0] or "ok",
            "hasVideo": bool(self.profile and self.profile.get("remote")),
            "alerts": [{"text": s, "crit": sev <= ERR_SEV} for s, sev in self.alerts.shown()],
            # --- duong bay -----------------------------------------------
            "draftN": len(self.map.draft),
            "draftFull": len(self.map.draft) >= WP_MAX,
            "wpAlt": self.map.wp_alt,
            "hasWp": bool(self.map.wp.get("items")),
            "wpOver": self._auto_flying(),  # nap bay gio la GHI DE nhiem vu dang bay
            # --- nhich vi tri --------------------------------------------
            # Ly do KHONG nhich duoc, "" neu duoc: can ao mo di va noi ro vi sao,
            # chu khong nam do im lang cho nguoi bay keo mai khong hieu.
            "nudgeWhy": self.cmd.nudge_block(self._live()) or "",
            # Kich ban #8: hai nguon lech vi tri qua nguong. Dong rieng chu khong
            # day vao `alerts`: no lap lai 5 Hz, vao do la dem "xN" chay loan.
            "diverge": div if div is not None and div > DIVERGE_M else None,
        }
        self.stateChanged.emit()

    def _auto_flying(self):
        """Dang bay theo chinh nhiem vu sap bi ghi de? True/False."""
        return (REGISTRY.value("heartbeat.mode") == "AUTO"
                and REGISTRY.value("heartbeat.armed") is True)

    # ---- lenh (QML goi SAU khi thanh truot da truot het) -------------------

    def _live(self):
        """Co duong xuong drone: REAL/SIM va adapter SiK con song."""
        return self.mode in LIVE and self.adapter is not None

    @Slot(str, str)
    def act(self, action, arg=""):
        if not self._live():
            self.cmd.say("touch.locked", 4)
            return
        c = self.cmd
        if action == "arm":
            c.arm()
        elif action == "disarm":
            c.kill()          # duoi dat -> force, tren troi -> lenh thuong (nhu nut do)
        elif action == "kill":
            c.force_disarm()  # QML bat truot roi GIU 2 s — xem SlideConfirm.holdMs
        elif action == "takeoff":
            c.takeoff(float(arg or 5))
        elif action in ("land", "rtl"):
            c.escape(action)
        elif action == "mode":
            c.mode(arg)
        self.refresh()

    def _on_log(self, text, sev=5):
        """Ket qua lenh: len man bay neu la loi, va ghi logs/commands.log nhu app laptop."""
        self.alerts.push(text, sev)
        try:
            line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  [{self.mode or '-'}]  {text}\n"
            (ROOT / "logs" / "commands.log").open("a", encoding="utf-8").write(line)
        except OSError:
            pass  # het dia thi cung khong duoc lam chet giao dien

    # ---- ban do: cu chi ngon tay ------------------------------------------

    @Slot(float, float)
    def mapPan(self, dx, dy):
        self.map.pan(dx, dy)

    @Slot(int)
    def mapZoom(self, step):
        self.map.zoom_by(step)

    @Slot()
    def mapFollow(self):
        self.map.follow = True
        if self.map.pos:
            self.map.center = self.map.pos

    # ---- duong bay: cham-giu de dat diem ----------------------------------
    #
    # Tab Bay cu dat waypoint bang menu chuot phai. Tren man cam ung khong co
    # chuot phai, nen cham-giu mo bang waypoint; con lai (tran WP_MAX, xac nhan
    # hai lan khi dang bay AUTO, bo ban nhap khi FC nhan) la CUNG mot duong o
    # `laptop/commands.py` va `MapWidget`, khong viet lai.

    def _latlon(self, x, y):
        return self.map.latlon_at(QPoint(int(x), int(y)))

    def _on_wp(self, env):
        """Duong bay tu FC ve. Rieng ket qua NAP thi phai ra log, khong ve ban do."""
        w = env["data"].get("write")
        if w is None:
            self.map.set_wp(env["data"])
            return
        if w["ok"]:
            # Bo ban nhap di: giu lai hai duong chong len nhau tren ban do, mot
            # cai la ke hoach cu, khong ai phan biet duoc nua.
            self.map.drop_draft(all_of_them=True)
            self.cmd.say("fly.wp_ok", 5, n=w["n"])
        else:
            why = w.get("err") or t("fly.wp_fc_denied", code=w["result"])
            self.cmd.say("fly.wp_fail", 3, why=why)
        self.refresh()

    @Slot(float, float)
    def addWp(self, x, y):
        if not self.map.add_draft(*self._latlon(x, y)):
            self.cmd.say("touch.wp_full", 4, n=WP_MAX)
        self.refresh()

    @Slot(int)
    def setWpAlt(self, alt):
        """Do cao cho cac waypoint dat TIEP theo (va cho "bay toi day").

        Kep o day chu khong o QML: o nhap so co the go ra bat cu gi, va con so
        nay di thang xuong FC. Kep o tang duoi cung ma moi duong deu di qua thi
        khong phai tin vao viec tung o nhap tu giu minh.
        """
        alt = max(WP_ALT_MIN, min(WP_ALT_MAX, int(alt)))
        if alt == self.map.wp_alt:
            return
        self.map.wp_alt = float(alt)
        self.map.update()
        self.refresh()

    @Slot()
    def undoWp(self):
        self.map.drop_draft()
        self.refresh()

    @Slot()
    def clearWp(self):
        self.map.drop_draft(all_of_them=True)
        self.refresh()

    @Slot()
    def sendWp(self):
        if not self._live():
            self.cmd.say("touch.locked", 4)
            return
        if self._auto_flying() and time.time() - self._wp_confirm > WP_CONFIRM_S:
            self._wp_confirm = time.time()
            self.cmd.say("touch.wp_overwrite", 4, sec=WP_CONFIRM_S)
            return
        self._wp_confirm = 0.0
        self.cmd.wp_write([list(p) for p in self.map.draft])

    @Slot()
    def wipeWp(self):
        if self._live():
            self.cmd.wp_clear()

    @Slot(float, float)
    def goto(self, x, y):
        if not self._live():
            self.cmd.say("touch.locked", 4)
            return
        self.cmd.goto(*self._latlon(x, y), self.map.wp_alt)

    # ---- nhich vi tri: can ao ---------------------------------------------
    #
    # Ban phim cua tab Bay cu tang toc theo THOI GIAN giu phim (phim chi co
    # dong/tat). Can ao thi do lech cua ngon tay CHINH LA do lon, nen khong can
    # ramp: cham nhe = NUDGE_V0 nhu go mot phat, day het = NUDGE_VMAX.

    @Slot(float, float, float)
    def stick(self, dx, dy, dz):
        """(dong, bac, len) trong tam [-1, 1]. Nhac tay = goi (0, 0, 0)."""
        self._stick = (dx, dy, dz)
        if not (dx or dy or dz):
            self._nudge_stop(t("nudge.why_release"))
            return
        if self._nudge_timer.isActive():
            return
        if why := self.cmd.nudge_block(self._live()):
            self._stick = (0.0, 0.0, 0.0)
            self.cmd.say("nudge.blocked", 4, why=why)
            return
        self._nudge_timer.start(int(1000 / NUDGE_HZ))
        self._nudge_tick()

    def _nudge_tick(self):
        dx, dy, dz = self._stick
        if why := self.cmd.nudge_block(self._live()):  # mode/armed doi giua chung
            self._nudge_stop(None)
            self.cmd.say("nudge.stopped", 4, why=why)
            return
        mag = (dx * dx + dy * dy + dz * dz) ** 0.5
        if not mag:
            return
        v = NUDGE_V0 + (NUDGE_VMAX - NUDGE_V0) * min(1.0, mag)
        # Man hinh: len la bac. NED: len la vd AM.
        self.cmd.nudge(v * dy / mag, v * dx / mag, -v * dz / mag)

    def _nudge_stop(self, why):
        """Van toc 0 = dung ngay tai cho drone dang o.

        Moc lay o timer chu KHONG o `_stick`: nguoi goi da dat no ve 0 truoc khi
        vao day, nen doc `_stick` thi luon thay rong va lenh dung khong bao gio
        di — drone giu nguyen van toc cuoi cho toi khi lenh GUIDED het han 3 s sau.
        """
        active = self._nudge_timer.isActive()
        self._stick = (0.0, 0.0, 0.0)
        self._nudge_timer.stop()
        if not active or not self._live():
            return
        self.cmd.nudge(0.0, 0.0, 0.0)
        if why:
            self.cmd.say("nudge.hold", 5, why=why)

    # ---- ket noi -----------------------------------------------------------

    def attach(self, profile, adapter):
        """MainWindow bao: dang noi profile nao, adapter SiK con song khong.

        adapter=None ma profile con = SiK vua dut (banner do) -> khoa lenh, giu
        man hinh. profile=None = da ngat -> xoa sach nhu disconnect().
        """
        # Truoc moi thu khac: het duong xuong drone thi can ao phai buong. Khong
        # co dong nay thi timer nhich van chay va ban vao khoang khong.
        self._nudge_stop(None)
        if profile is None:
            self.profile = self.mode = self.adapter = None
            self.last_seen.clear()
            # Xoa luon so lieu cu. `map.reset()` co xoa home, nhung `refresh()` chay
            # 5 Hz va no doc thang REGISTRY: con vi tri cu trong do la 200 ms sau no
            # DUNG LAI mot home moi ngay tai cho drone vua dung — X tren ban do nam
            # sai cho, "ve nha bao nhieu met" dem tu cai cho sai do. Cac o do cao,
            # pin, ve tinh cung the: ngat roi ma van hien so cua chuyen truoc, va
            # con treo sang ca chuyen sau cho toi khi drone moi kip gui goi dau.
            REGISTRY.fields.clear()
            self.map.reset()
            self.alerts.clear()  # loi cua drone cu khong duoc treo sang ket noi sau
            # Lenh dang cho COMMAND_ACK cung phai bo. Khong bo thi toi 3 s SAU khi
            # da ngat, `_check_pending` van bat "<lenh>: FC khong tra loi" len mot
            # man hinh vua don sach — hoac te hon, len dau ket noi KE TIEP neu cam
            # lai nhanh. Dut SiK giua chung thi KHAC: o do canh bao la tin that,
            # nen `_on_failed` co y khong goi vao day.
            self.cmd._pending.clear()
        else:
            if profile is not self.profile:
                self.last_seen.clear()
            self.profile, self.mode, self.adapter = profile, profile["mode"], adapter
        self.refresh()

    @Slot()
    def rescan(self):
        if not self.owns:
            return  # nam trong app laptop: MainWindow cam ket noi
        self._profiles = detect_serial(self._template) + self._fixed
        self.profilesChanged.emit()

    @Slot(int)
    def connectTo(self, i):
        """Giong MainWindow.connect_to cua app laptop, bot phan noi day tab."""
        if not self.owns:
            return  # nam trong app laptop: MainWindow cam ket noi
        if not 0 <= i < len(self._profiles):
            return
        profile = dict(self._profiles[i])
        if profile["mode"] == "REPLAY":
            path = Path(profile.get("path", ""))
            path = path if path.is_absolute() else ROOT / path
            profile["path"] = str(path) if path.is_file() else _newest(profile.get("path", ""))
            if not profile["path"]:
                self._on_log(t("conn.fail_title") + ": " + profile.get("path", ""), 3)
                return
        self.disconnect()
        self.profile, self.mode = profile, profile["mode"]

        self.adapter = SikAdapter(profile, logdir=ROOT / "logs")
        self.adapter.envelope.connect(bus.emit_envelope)
        self.adapter.failed.connect(self._on_failed)
        self.adapter.start()
        authority.register("sik", self.adapter)
        if profile.get("remote"):
            self.remote = RemoteAdapter(profile["remote"])
            self.remote.envelope.connect(bus.emit_envelope)
            self.remote.start()
            authority.register("remote", self.remote)
            url = url_for(profile["remote"])
            if url:
                self.video_src.start(url)
        self.refresh()

    @Slot()
    def disconnect(self):
        if not self.owns:
            return  # nam trong app laptop: MainWindow cam ket noi
        self._nudge_stop(None)
        for name, attr in (("sik", "adapter"), ("remote", "remote")):
            a = getattr(self, attr)
            if a:
                a.stop()
                setattr(self, attr, None)
            authority.unregister(name)
        self.video_src.stop()
        self.attach(None, None)  # don dep chi co MOT ban, nam o `attach`

    def _on_failed(self, why):
        # KHONG hop thoai modal: drone co the dang bay (xem MainWindow._on_failed).
        self._nudge_stop(None)  # het duong xuong drone thi can ao phai buong
        self._on_log(t("conn.sik_lost", why=why), 2)
        if self.adapter:
            self.adapter.stop()
            self.adapter = None
        authority.unregister("sik")
