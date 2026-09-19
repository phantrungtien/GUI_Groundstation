"""Backend cua man bay cam ung: giu trang thai, chuyen lenh cho QML.

KHONG tu mo ket noi: MainWindow cam ket noi va dua vao day bang `attach()`;
`Commands` va nguon video cung la cua MainWindow — MOT ket noi, MOT bo theo doi
ACK (hai bo la moi ACK ghi hai dong vao tab Thong bao). Truoc 19/09 co them che
do tu cam ket noi (cho ban dien thoai) — bo di vi no la ban THU HAI cua
MainWindow.connect_to: moi thay doi phai sua hai cho, va e2e_sitl di nham vao ban
do chu khong phai ban app that dung. Lam ban dien thoai thi viet lai tu MainWindow.

KHONG co chot an toan nao viet moi o day. Chan ARM khi ga cao, TAKEOFF phai o
GUIDED, DISARM duoi dat thi force, theo doi ACK — tat ca nam o
`laptop/commands.py`, dung chung voi tab Dieu khien cua app laptop. Thanh truot
ben QML la phan XAC NHAN; goi toi day nghia la nguoi bay da truot het.
"""

import time

from PySide6.QtCore import Property, QObject, QPoint, QTimer, Signal, Slot

from core import bus, i18n
from core.adapters.sik import STALE, WP_MAX, SikAdapter
from core.field import REGISTRY, haversine_m
from core.i18n import t
from laptop.commands import (MODES, NUDGE_HZ, NUDGE_V0, NUDGE_VMAX, WP_ALT_MAX,
                             WP_ALT_MIN, WP_ALTS,
                             WP_CONFIRM_S, Commands)
from laptop.widgets.alerts import ERR_SEV, AlertBook
from laptop.widgets.attitude import AttitudeWidget
from laptop.widgets.compass import Compass
from laptop.widgets.map_widget import MapWidget
from laptop.widgets.telemetry_bar import (batt_level, gps_level, left_level, reserve_mah,
                                           time_left_s)
from laptop.widgets.video import VideoSource, VideoView, video_url
from laptop.touch.items import WIDGETS
from laptop import safety
from laptop.voice import Voice

LIVE = ("REAL", "SIM")
DIVERGE_M = 5.0  # hai nguon vi tri lech hon chung nay thi keu — giong tab Bay cu
PREARM_KEEP_S = 40.0  # FC nhac ly do PreArm moi ~31 s (do that log 144628)
AMPS_TAU_S = 5.0  # lam muot dong dien: ga nhay mot phat thi so phut khong nhay theo


def _mmss(sec):
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


class Backend(QObject):
    stateChanged = Signal()
    langChanged = Signal()
    openMessage = Signal(str)  # cham dong loi -> app.py mo tab Thong bao toi dong do

    def __init__(self, cmd=None, video_src=None, parent=None):
        super().__init__(parent)
        self.adapter = self.profile = self.mode = None
        self.last_seen = {}
        self._armed_at = None
        # Tham so FC gui MOT lan luc ket noi (pin, failsafe, RTL — WATCH_PARAMS
        # o sik.py). KHONG doc tu REGISTRY: o do moi gia tri qua STALE = 2 s la coi
        # nhu khong co — do that 19/09 (log 151442): BATT_CAPACITY ve o giay 0,1,
        # toi giay 2 thi o CON da thanh "--" mai.
        self._params = {}
        self._amps = None      # dong dien da lam muot (A)
        self._amps_at = 0.0
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
        self.voice = Voice()
        self._rtl_lvl = None
        # Ket qua lenh di qua MainWindow._on_cmd_log (tab Thong bao + commands.log),
        # roi MainWindow day lai vao `alerts`.
        self.cmd = cmd or Commands(self)
        bus.on("*", self._seen)
        # Home, rao, duong bay ve mot lan roi thoi — doc thang tu bus nhu FlightTab.
        bus.on("home", lambda e: self.map.set_home(e["data"]["lat"], e["data"]["lon"],
                                                   from_fc=True))
        bus.on("fence", lambda e: self.map.set_fence(e["data"]))
        bus.on("wp", self._on_wp)
        bus.on("param", lambda e: self._params.update(e["data"]))
        bus.on("text", self._on_text)
        # San sang ARM: bit PREARM_CHECK trong SYS_STATUS — cung nguon Mission
        # Planner/QGC dung. Do that 19/09 tren MicoAir743: log 144628 co loi
        # PreArm -> bit False ca phien; log 155159 khong loi -> True tu giay dau.
        # Doc tu topic `status` qua bus: REGISTRY bo qua topic nay (SKIP_TOPICS).
        self._prearm = None     # ("ok"/"fail"/..., ts)
        self._prearm_why = {}   # ly do PreArm FC vua noi -> ts
        bus.on("status", self._on_status)
        i18n.signals.changed.connect(lambda _l: self.langChanged.emit())

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(200)
        self._nudge_timer = QTimer(self)
        self._nudge_timer.timeout.connect(self._nudge_tick)
        self.refresh()

    # ---- cho QML doc -------------------------------------------------------

    def _get_state(self):
        return self._state

    def _get_lang(self):
        return i18n.lang()

    state = Property("QVariantMap", _get_state, notify=stateChanged)
    lang = Property(str, _get_lang, notify=langChanged)
    modes = Property("QVariantList", lambda self: MODES, constant=True)
    wpAlts = Property("QVariantList", lambda self: list(WP_ALTS), constant=True)
    wpAltMin = Property(int, lambda self: WP_ALT_MIN, constant=True)
    wpAltMax = Property(int, lambda self: WP_ALT_MAX, constant=True)

    @Slot(str)
    def showMessage(self, text):
        self.openMessage.emit(text)

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
        pct = v("battery.remaining")
        if armed and self._armed_at is None:
            self._armed_at = time.time()  # suon len cua armed, khong phai luc bam
        elif not armed and armed is not None:
            self._armed_at = None
        left = self._time_left(pct) if self._armed_at is not None else None

        fix, sats, hdop = v("gps.fix_type"), v("gps.sats"), v("gps.hdop")
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
            "battLeft": left, "leftLevel": left_level(left) or "ok",
            "sats": sats, "gpsLevel": gps_level(fix, sats, hdop)[0] or "ok",
            "hasVideo": bool(self.profile and video_url(self.profile)),
            "alerts": [{"text": s, "crit": sev <= ERR_SEV} for s, sev in self.alerts.shown()],
            "ready": self._ready(armed is True),
            "warns": self._warns(armed, left, dist),
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
        self._announce(key, level, pct, armed)
        self.stateChanged.emit()

    def _announce(self, status_key, status_level, pct, armed):
        """Doc thanh tieng khi trang thai DOI — xem laptop/voice.py."""
        v, s = self.voice, self._state
        v.on("lost", status_key == "touch.st_lost", "voice.lost")
        r = s["ready"]
        v.on("ready", bool(r and r["ok"]), "voice.ready")
        v.on("rtl", self._rtl_lvl, "voice.rtl_now" if self._rtl_lvl == "crit"
             else "voice.rtl_soon", repeat=self._rtl_lvl == "crit")
        lvl = batt_level(pct) if armed else None
        v.on("batt", lvl, "voice.batt_crit" if lvl == "crit" else "voice.batt_low", pct=pct)

    def _time_left(self, pct):
        """Giay bay con lai toi muc failsafe pin cua FC, theo dong dien da lam muot."""
        v = REGISTRY.value
        amps, now = v("battery.current"), time.time()
        if amps is None:
            self._amps = None
        elif self._amps is None:
            self._amps = amps
        else:
            k = min(1.0, (now - self._amps_at) / AMPS_TAU_S)
            self._amps += k * (amps - self._amps)
        self._amps_at = now
        g = self._params.get
        cap = g("BATT_CAPACITY")
        return time_left_s(cap, v("battery.consumed_mah"), pct,
                           reserve_mah(cap, g("BATT_LOW_MAH"), g("BATT_CRT_MAH")),
                           self._amps)

    def _on_text(self, env):
        text = env["data"].get("text") or ""
        if isinstance(text, bytes):
            text = text.decode("utf-8", "replace")
        self.alerts.push(text, env["data"].get("severity", 6))
        if text.startswith("PreArm:"):
            self._prearm_why[text[len("PreArm:"):].strip()] = time.time()

    def _on_status(self, env):
        s = env["data"].get("SENSOR.prearm_check")
        if s is not None:
            self._prearm = (s, time.time())

    def _ready(self, armed):
        """(key, ly do) cho dong "san sang ARM". None = khong hien.

        Chi hien khi dang ket noi, CHUA ARM va bit con tuoi. Ly do lay tu cac dong
        "PreArm: ..." FC nhac lai moi ~31 s; giu 40 s de khong nhap nhay giua hai
        lan nhac, va bo sach khi FC bao da san sang.
        """
        if not self.profile or armed or self._prearm is None \
                or time.time() - self._prearm[1] > STALE:
            return None
        if self._prearm[0].startswith("ok"):
            self._prearm_why.clear()
            return {"ok": True, "text": t("touch.ready_arm")}
        now = time.time()
        why = [w for w, ts in self._prearm_why.items() if now - ts < PREARM_KEEP_S]
        return {"ok": False, "text": t("touch.not_ready_arm") + (": " + "; ".join(why) if why else "")}

    def _warns(self, armed, left, dist):
        """Canh bao DUNG YEN (khong tu tat nhu AlertBook): [{text, crit}].

        Chua ARM: kiem tham so failsafe va pin day chua (safety.preflight).
        Dang bay: con du pin de ve nha khong (RTL uoc tu tham so FC).
        """
        self._rtl_lvl = None
        if not self.profile or self.mode == "REPLAY":
            return []
        v = REGISTRY.value
        if armed is not True:
            return [{"text": t(k, **kw), "crit": False} for k, kw in
                    safety.preflight(self._params, v("battery.voltage"),
                                     v("battery.remaining"), v("battery.current"))]
        if v("heartbeat.landed") is not False:
            return []
        need = safety.rtl_time_s(self._params, dist, v("position.alt_rel"))
        lvl = self._rtl_lvl = safety.rtl_level(left, need)
        if lvl is None:
            return []
        key = "safe.rtl_now" if lvl == "crit" else "safe.rtl_soon"
        return [{"text": t(key, left=_mmss(left), need=_mmss(need)), "crit": lvl == "crit"}]

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
            c.force_disarm()  # truot het la di; hau qua ghi ngay tren thanh truot (touch.kill_note)
        elif action == "takeoff":
            # Kep o day: o nhap QML go ra duoc bat cu gi, con so nay di thang FC.
            c.takeoff(float(max(WP_ALT_MIN, min(WP_ALT_MAX, float(arg or 5)))))
        elif action in ("land", "rtl"):
            c.escape(action)
        elif action == "mode":
            c.mode(arg)
        self.refresh()

    # ---- ban do: cu chi ngon tay ------------------------------------------

    @Slot(float, float)
    def mapPan(self, dx, dy):
        self.map.pan(dx, dy)

    @Slot(int)
    def mapZoom(self, step):
        self.map.zoom_by(step)

    @Slot()
    def mapFollow(self):
        if not self.map.recenter():
            self.cmd.say("touch.no_gps_pos", 4)  # cham dup ma khong co gi de ve

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
            self._prearm, self._prearm_why = None, {}
            # Xoa luon so lieu cu. `map.reset()` co xoa home, nhung `refresh()` chay
            # 5 Hz va no doc thang REGISTRY: con vi tri cu trong do la 200 ms sau no
            # DUNG LAI mot home moi ngay tai cho drone vua dung — X tren ban do nam
            # sai cho, "ve nha bao nhieu met" dem tu cai cho sai do. Cac o do cao,
            # pin, ve tinh cung the: ngat roi ma van hien so cua chuyen truoc, va
            # con treo sang ca chuyen sau cho toi khi drone moi kip gui goi dau.
            REGISTRY.fields.clear()
            self._params.clear()  # tham so cua drone cu khong duoc dung cho drone sau
            self.voice.reset()
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
