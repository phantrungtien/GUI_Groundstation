"""Lenh xuong drone va cac chot chan cua no — KHONG co giao dien nao o day.

Tach ra tu tab Dieu khien de hai giao dien dung CHUNG mot ban: tab Dieu khien
cua app laptop (`laptop/tabs/control.py`) va man bay cam ung (`touch/`). Chot an
toan viet hai lan la hai cho de lech nhau; lech o day la lech tren may bay that.

Giao dien lo phan XAC NHAN (bam lai 3 s, giu 2 s, thanh truot). Cai o day chi lo:
lenh co duoc gui khong, gui gi, va FC tra loi ra sao.

Doc nguyen tac 2.1 truoc khi sua: RTL/LAND/DISARM di `escape()` -> nhanh ESCAPE
cua `authority.dispatch()` -> `SikAdapter.send()`, khong qua companion, khong
qua WebSocket.
"""

import time

from PySide6.QtCore import QObject, QTimer, Signal

from core import authority, bus
from core.field import REGISTRY, STALE
from core.i18n import t

MODES = ["STABILIZE", "ALT_HOLD", "LOITER", "GUIDED", "AUTO", "POSHOLD", "BRAKE"]

# MAV_RESULT — chu nam trong bang chu (core/i18n.py), key "ack.<so>"
ACK_CMD = {400: "ARM/DISARM", 22: "TAKEOFF", 20: "RTL", 21: "LAND", 176: "cmd.mode",
           16: "goto"}
ACK_TIMEOUT = 3.0  # giay cho FC tra loi truoc khi coi la khong co phan hoi

# Nguong ga (PWM) coi la "o min" khi cho phep ARM. Khung dang bay: RC3_MIN = 989,
# THR_DZ = 100 -> het vung chet o 1089; 1150 la con so do cong them mot chut du.
# Doi radio hay doi khung thi doc lai hai tham so do va sua o day.
THR_ARM_MAX = 1150

CLIMB_CHECK_S = 6.0  # giay sau TAKEOFF moi doi chieu do cao that
# Cam bien khoang cach duoi muc nay (cm) thi coi la con o duoi dat. Khung dang
# dung: RNGFND1_TYPE = 24, dai 5-400 cm. Doi cam bien thi xem lai con so nay.
RNG_GROUND_CM = 100

# --- nhich vi tri ---------------------------------------------------------
#
# Gui VAN TOC chu khong toa do — ly do va so do nam o `sik.py`, action "nudge".
# Quang duong = tich phan van toc, nen giu lau thi di xa. Do lech cua ngon tay
# tren can ao CHINH LA do lon, nen khong co ramp theo thoi gian: cham nhe =
# NUDGE_V0, day het = NUDGE_VMAX.
NUDGE_V0 = 1.0     # m/s ngay khi cham
NUDGE_VMAX = 5.0   # tran toc do
# Nhip gui lai. Lenh van toc GUIDED cua ArduPilot het han sau ~3 s, va do trung vi
# cua duong SiK la 132 ms — 5 Hz vua du day de mot goi roi khong thanh mot khoang
# khung, ma van chi ~115 B/s tren chieu len dang trong.
NUDGE_HZ = 5

# --- duong bay ------------------------------------------------------------
#
# Do cao chon duoc cho waypoint dat bang tay. Danh sach chu khong o nhap so: hop
# thoai nhap lieu lam nut do chet trong vai giay (xem ControlTab._takeoff).
WP_ALTS = (10, 15, 20, 30, 50, 80)
# Nap de len nhiem vu trong luc drone dang bay AUTO theo chinh nhiem vu do: FC
# nhay sang WP1 cua duong bay moi ngay lap tuc. Bam lai trong ngan nay de xac
# nhan — cung cach TAKEOFF o che do REAL dang lam.
WP_CONFIRM_S = 3.0


class Commands(QObject):
    # (chu da dich, muc do MAV_SEVERITY). Muc do di kem chu KHONG duoc suy tu chu:
    # truoc day app.py bat chuoi "TU CHOI"/"KHONG" trong text de to mau, va cach do
    # chet ngay khi giao dien noi tieng Anh.
    log = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Lenh gui di ma FC khong he tra loi: khong duoc de im. "Da gui" khong
        # co nghia la "da lam" — day la ca de nham nhat vi giao dien trong nhu
        # thanh cong.
        self._pending = {}  # action -> deadline
        self._ack_timer = QTimer(self)
        self._ack_timer.timeout.connect(self._check_pending)
        self._ack_timer.start(500)

        # Vi tri can ga, de chan ARM khi ga chua ve min. Doc thang tu bus: topic
        # `status` nam trong SKIP_TOPICS cua REGISTRY nen khong hoi qua do duoc.
        self._thr = None  # (pwm, ts)
        self._rng = None  # (cm, min_cm, max_cm, ts)
        bus.on("status", self._on_status)
        bus.on("ack", self._on_ack)

    def say(self, key, sev=5, **kw):
        self.log.emit(t(key, **kw), sev)

    def _on_status(self, env):
        pwm = env["data"].get("RC_CHANNELS.chan3_raw")
        if pwm is not None:
            self._thr = (pwm, env["ts"])
        cm = env["data"].get("DISTANCE_SENSOR.current_distance")
        if cm is not None:
            lo = env["data"].get("DISTANCE_SENSOR.min_distance", 0)
            hi = env["data"].get("DISTANCE_SENSOR.max_distance", 10_000)
            self._rng = (cm, lo, hi, env["ts"])

    # ---- lenh thuong: di qua kiem tra quyen ------------------------------

    def arm(self):
        """ARM, nhung chan khi can ga chua ve min.

        FC KHONG chan viec nay: `AP_Arming.cpp:81-115` chi kiem ga co THAP hon
        nguong failsafe khong, khong he kiem ga cao — kiem "ga qua cao" chi ap cho
        arm bang can lai. Do that luc 22:35 tren MicoAir743: ga 1496 -> `ack=0` ->
        dong co vot thang len 1654/1506/1347/1080. Thao canh thi do la tieng on;
        lap canh thi khong.
        """
        thr = self._thr
        if thr is None:
            self.say("log.arm_no_rc", 4)
        elif time.time() - thr[1] > STALE:
            self.say("log.arm_rc_old", 4, age=time.time() - thr[1])
        elif thr[0] > THR_ARM_MAX:
            self.say("log.arm_blocked", 3, pwm=thr[0], max=THR_ARM_MAX)
            return
        self.cmd("arm")

    def disarm(self):
        """DISARM thuong, cung quy tac nhu nut do: duoi dat thi force, nen ga o muc
        nao cung ngat duoc. Khac o cho no van di qua kiem tra quyen."""
        self.cmd("disarm", {"force": True} if self.on_ground() else None)

    def mode(self, name):
        self.cmd("mode", {"name": name})

    def takeoff(self, alt):
        """TAKEOFF. Xac nhan (bam lai / truot) la viec cua giao dien goi vao day.

        Tra True neu lenh da gui, False neu bi chan.
        """
        # ArduCopter chi that su cat canh bang MAV_CMD_NAV_TAKEOFF khi dang o
        # GUIDED. O STABILIZE no tra ve THAT BAI; o LOITER no tra ve CHAP NHAN
        # roi khong lam gi — kieu hong te nhat, giao dien trong nhu thanh cong.
        # Noi thang ly do o day con hon de nguoi bay doan qua chu "THAT BAI".
        fc = REGISTRY.value("heartbeat.mode")
        if fc and fc != "GUIDED":
            self.say("log.takeoff_need_guided", 4, mode=fc)
            return False
        self.cmd("takeoff", {"alt": alt})
        # "FC chap nhan" != "drone dang len". Neu mot node ROS2 dang stream setpoint
        # vao GUIDED thi lenh takeoff bi chinh cai stream do de len ngay sau do:
        # ACK ve result=0, dong co giu ga khong tai, drone nam im roi auto-disarm
        # sau DISARM_DELAY. Khong doi chieu do cao thi giao dien trong y het thanh cong.
        QTimer.singleShot(
            CLIMB_CHECK_S * 1000,
            lambda a0=REGISTRY.value("position.alt_rel", 0.0): self.check_climb(a0))
        return True

    def check_climb(self, alt0):
        alt = REGISTRY.value("position.alt_rel")
        if alt is None or alt - alt0 >= 1.0:
            return
        self.say("log.takeoff_no_climb", 3, sec=CLIMB_CHECK_S)

    def cmd(self, action, args=None):
        r = authority.dispatch({"target": "sik", "action": action, "args": args or {}})
        # Force phai hien trong log: doc lai sau su co, "disarm" va "disarm FORCE"
        # la hai su kien khac han nhau.
        self._report(action + (" FORCE" if args and args.get("force") else ""), r)

    # ---- duong bay -------------------------------------------------------
    #
    # Nap duong bay la mot LENH: no phai de lai vet o tab Thong bao va o
    # logs/commands.log y nhu ARM/TAKEOFF. Nhung no KHONG di qua `_report()`:
    # FC tra loi bang MISSION_ACK (-> topic "wp", truong `write`) chu khong bang
    # COMMAND_ACK, nen xep vao `_pending` la chac chan an mot dong "khong co phan
    # hoi" sau ACK_TIMEOUT du lenh da xong.

    def wp_write(self, items):
        self._soft(t("act.wp_send", n=len(items)), authority.dispatch(
            {"target": "sik", "action": "wp_write", "args": {"items": items}}))

    def wp_clear(self):
        self._soft(t("act.wp_wipe"),
                   authority.dispatch({"target": "sik", "action": "wp_clear"}))

    def goto(self, lat, lon, alt):
        """Bay toi mot diem. Phai o GUIDED, nen doi mode truoc — khac han `nudge`:
        o do dang bay AUTO ma lo tay keo sang GUIDED la bo ngang nhiem vu, con o
        day nguoi bay vua chi dich den, tuc la da chon roi.

        `alt` la do cao SO VOI HOME (met), va nguoi goi PHAI dua vao: day khong
        phai lenh "bay ngang toi do", FC se leo hay tut xuong dung so nay. Giao
        dien dua vao chinh o do cao dang hien canh nut, de so tren man hinh va so
        xuong FC luon la mot.

        Khong di qua `_report()`: FC tra loi mission item bang MISSION_ACK chu
        khong bang COMMAND_ACK — xem chu thich o `wp_write`.
        """
        authority.dispatch({"target": "sik", "action": "mode", "args": {"name": "GUIDED"}})
        self._soft(t("act.goto", lat=lat, lon=lon, alt=float(alt)), authority.dispatch(
            {"target": "sik", "action": "goto",
             "args": {"lat": lat, "lon": lon, "alt": float(alt)}}))

    # ---- nhich vi tri ----------------------------------------------------

    def nudge_block(self, live):
        """Ly do KHONG duoc nhich, hay None neu duoc. Bon chot, khong bot cai nao.

        `live` = co duong xuong drone that khong (REAL/SIM va adapter con song).
        Ban phim o tab Bay va can ao o man cam ung cung hoi qua day.
        """
        if not live:
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

    def nudge(self, vn, ve, vd):
        """Mot goi van toc. KHONG bao cao: 5 Hz ma ghi log la lap day tab Thong bao."""
        authority.dispatch({"target": "sik", "action": "nudge",
                            "args": {"vn": vn, "ve": ve, "vd": vd}})

    # ---- nut do: KHONG qua kiem tra nao ---------------------------------

    def escape(self, action, args=None):
        """Nut do. Khong hoi lai, khong qua kiem tra nao — goi la di."""
        r = authority.dispatch({"action": action, "args": args or {}})
        self._report(action.upper() + (" FORCE" if args and args.get("force") else ""), r)

    def kill(self):
        """DISARM do, mot phat.

        Duoi dat: gui thang force, nen VI TRI CAN GA khong con anh huong gi —
        FC tu choi lenh disarm thuong bat cu khi nao no tin la dang bay, va no tin
        the ngay khi ga roi khoi min (do that: ga 1496 -> ack=4, 3/3 lan).

        Tren troi hoac khong biet do cao: van la lenh thuong. Muon cat dong co
        that thi `force_disarm()` — giao dien phai bat mot dong tac co chu y (giu
        2 s), mot cu bam nham khong duoc phep lam roi may bay.
        """
        self.escape("disarm", {"force": True} if self.on_ground() else None)

    def force_disarm(self):
        self.escape("disarm", {"force": True})

    def on_ground(self):
        """Dang o duoi dat? True / False / None (= khong biet).

        Hai nguon doc lap, cai nao noi "duoi dat" cung du:

        1. `EXTENDED_SYS_STATE.landed_state` — chinh la `land_complete` cua FC.
           Dung nhung KHONG DU: do that, ga len giua tam la no thanh IN_AIR ngay
           ca khi may bay dang treo tren thanh, vi FC chi thay dong co quay. Bam
           theo mot minh no thi lenh thuong lai bi tu choi dung luc ga cao.
        2. Cam bien khoang cach — thu duy nhat do toi nay KHONG doi khi ga len:
           60 cm suot ca buoi, ke ca luc dong co quay. Chi tin khi so nam trong
           dai hop le cua chinh cam bien: hong ma tra 0 cm thi khong duoc coi la
           "sat dat".

        KHONG dung `position.alt_rel`: GPS fix 0 thi no doc -8.5 m trong khi may
        bay nam yen — lech theo chieu am nghia la o 7 m van "duoi 1 m".

        Doi lai: bay that o duoi 1 m thi mot cu bam la cat dong co. O do cao do
        thi do la ha canh, khong phai roi.
        """
        landed = REGISTRY.value("heartbeat.landed")
        if landed is True:
            return True
        rng = self._rng
        if rng and time.time() - rng[3] < STALE:
            cm, lo, hi = rng[0], max(rng[1], 1), rng[2]
            if lo <= cm <= min(hi, RNG_GROUND_CM):
                return True
        return landed  # False neu FC bao dang bay, None neu khong ai biet

    # ---- FC tra loi ------------------------------------------------------

    def _check_pending(self):
        now = time.time()
        for action, deadline in list(self._pending.items()):
            if now > deadline:
                del self._pending[action]
                self.say("log.no_ack", 4, action=action, sec=ACK_TIMEOUT)

    def _on_ack(self, env):
        """FC tra loi lenh. Bi tu choi ma im lang la kieu hong nguy hiem nhat."""
        cmd = env["data"]["command"]
        res = env["data"]["result"]
        if cmd not in ACK_CMD:
            # Ack cua lenh KHONG phai tu nut nao o day (app tu xin HOME_POSITION,
            # hay mot GCS khac tren cung duong truyen). Xoa `_pending` theo no la
            # nuot mat canh bao "khong co phan hoi" cua lenh nguoi dung vua bam.
            return
        name = t(ACK_CMD[cmd])  # ten khong co trong bang chu thi t() tra lai chinh no
        self._pending.clear()  # FC da tra loi -> khong con cho gi nua
        if res != 0:
            self.say("log.fc_denied", 3, name=name, why=t(f"ack.{res}"))
        else:
            self.say("log.fc_ok", 5, name=name)

    def _soft(self, what, result):
        """Bao cao mot lenh co duong xac nhan RIENG (xem `wp_write`).

        Giong `_report()` tru mot cho: khong xep vao `_pending`, vi cai xac nhan
        no cho khong phai COMMAND_ACK.
        """
        if "error" in result:
            self.say("log.refused", 3, what=what, why=result["error"])
        elif "stale" in result:
            self.say("log.queued_stale", 4, what=what, how=t("log.silent_never"))
        else:
            self.say("log.sent_wait", 5, what=what)

    def _report(self, action, result):
        if "error" in result:
            self.say("log.refused", 3, what=action, why=result["error"])
            return
        self._pending[action] = time.time() + ACK_TIMEOUT
        if "stale" in result:
            silent = result["stale"]
            how = (t("log.silent_never") if silent is None
                   else t("log.silent_for", sec=silent))
            self.say("log.queued_stale", 4, what=action, how=how)
        else:
            self.say("log.sent", 5, what=action)
