"""Tab Control — ARM/mode/takeoff va NHOM NUT DO.

Doc nguyen tac 2.1 truoc khi sua file nay.

Khong con switch MANUAL/AUTO: laptop cam toan quyen, khong nhuong cho ai (xem
core/authority.py). Nhiem vu ROS2 vi the cung khong con nut bam — node offboard
tren companion khong duoc lai nua, nen mot nut gui lenh cho no la nut noi doi.
Cai con lai la MOT DONG TRANG THAI: companion bao node nao dang chay, de con
biet ma tat neu no chay ngoai y muon.

Nhom nut do (RTL/LAND/DISARM) tach rieng ve mat ma nguon: chung goi thang
`authority.dispatch()` vao nhanh ESCAPE -> `SikAdapter.send()`, khong di qua
companion, khong di qua WebSocket.

Ngoai le duy nhat lam nut do bi khoa: che do REPLAY — luc do khong co gi o dau
kia de ma gui lenh toi.
"""

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import authority, bus, i18n
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

# Ten node nhiem vu ben repo ROS2 -> ten doc duoc. Chi con dung de dich mot chuoi
# trang thai companion bao len; laptop khong khoi dong nhiem vu nao nua.
MISSIONS = [
    ("mission.circle", "mission_circle"),
    ("mission.gates", "mission_gates"),
    ("mission.human", "trackinghuman"),
    ("mission.simple", "mission_simple"),
]
CLIMB_CHECK_S = 6.0  # giay sau TAKEOFF moi doi chieu do cao that
CONFIRM_S = 3.0  # cua so bam lai de xac nhan TAKEOFF o che do REAL
# Cam bien khoang cach duoi muc nay (cm) thi coi la con o duoi dat. Khung dang
# dung: RNGFND1_TYPE = 24, dai 5-400 cm. Doi cam bien thi xem lai con so nay.
RNG_GROUND_CM = 100

RED_QSS = """
QPushButton {
    background:#b03a2e; color:#fff; font-size:15px; font-weight:bold;
    padding:16px 8px; border:1px solid #7b2318;
}
QPushButton:hover { background:#c0392b; }
QPushButton:disabled { background:#4a2a25; color:#8a7a76; }
"""


class ControlTab(QWidget):
    # (chu da dich, muc do MAV_SEVERITY). Muc do di kem chu KHONG duoc suy tu chu:
    # truoc day app.py bat chuoi "TU CHOI"/"KHONG" trong text de to mau, va cach do
    # chet ngay khi giao dien noi tieng Anh.
    log = Signal(str, int)

    def _say(self, key, sev=5, **kw):
        self.log.emit(t(key, **kw), sev)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = None  # che do ket noi hien tai (REAL/SIM/REPLAY/None)

        # --- lenh thuong ---
        self.btn_arm = QPushButton("ARM")
        self.btn_disarm = QPushButton("DISARM")
        self.mode_box = QComboBox()
        self.mode_box.addItems(MODES)
        self.btn_mode = QPushButton()
        self.alt = QDoubleSpinBox()
        self.alt.setRange(1, 120)
        self.alt.setValue(5)
        self.alt.setSuffix(" m")
        self.btn_takeoff = QPushButton("TAKEOFF")

        self.btn_arm.clicked.connect(self._arm)
        # Nut DISARM thuong theo cung quy tac nhu nut do: duoi dat thi force, nen
        # ga o muc nao cung ngat duoc. Khac o cho no van di qua kiem tra quyen.
        self.btn_disarm.clicked.connect(
            lambda: self._cmd("disarm", {"force": True} if self._on_ground() else None)
        )
        self.btn_mode.clicked.connect(
            lambda: self._cmd("mode", {"name": self.mode_box.currentText()})
        )
        self.btn_takeoff.clicked.connect(self._takeoff)

        self.normal_box = QGroupBox()
        normal = self.normal_box
        g = QGridLayout(normal)
        g.addWidget(self.btn_arm, 0, 0)
        g.addWidget(self.btn_disarm, 0, 1)
        self.lbl_mode = QLabel()
        self.lbl_alt = QLabel()
        g.addWidget(self.lbl_mode, 1, 0)
        g.addWidget(self.mode_box, 1, 1)
        g.addWidget(self.btn_mode, 1, 2)
        g.addWidget(self.lbl_alt, 2, 0)
        g.addWidget(self.alt, 2, 1)
        g.addWidget(self.btn_takeoff, 2, 2)

        # --- nhiem vu ROS2: CHI DOC ---
        # Khong con nut khoi dong. Nhung van phai nhin thay: node offboard khong
        # duoc lai nua khong co nghia la khong the co node nao dang chay tren
        # companion — biet no chay la biet co ai do dang tranh duong truyen.
        self.mission_box = QGroupBox()
        mg = QGridLayout(self.mission_box)
        self._mission_running = None  # node dang chay, de dich lai khi doi ngon ngu
        self.mission_now = QLabel()
        self.mission_now.setStyleSheet("color:#8a939b;")
        mg.addWidget(self.mission_now, 0, 0)
        bus.on("mission", self._on_mission_state)

        # --- NUT DO ---
        self.btn_rtl = QPushButton("RTL")
        self.btn_land = QPushButton("LAND")
        self.btn_kill = QPushButton("DISARM")
        self.reds = (self.btn_rtl, self.btn_land, self.btn_kill)
        for b in self.reds:
            b.setStyleSheet(RED_QSS)
            b.setMinimumHeight(64)
        self.btn_rtl.clicked.connect(lambda: self._escape("rtl"))
        self.btn_land.clicked.connect(lambda: self._escape("land"))

        # DISARM hai bac, chia theo cau tra loi cua FC chu khong theo can ga:
        #
        #   FC bao DA HA CANH  -> bam mot phat la force 21196, ngat duoc ngay du
        #                         can ga dang o dau
        #   dang bay / KHONG BIET -> bam mot phat chi ra lenh thuong; muon force
        #                         thi phai giu 2 giay
        #
        # Vi sao khong de bac thuong lo: ArduCopter/AP_Arming.cpp:788 chan disarm
        # tu GCS khi `land_complete` sai, va no sai ngay khi ga roi khoi min (do
        # that: ga 1496, motor 1654/1506/1347/1080 -> ack=4, 3/3 lan). Tuc vi tri
        # can ga quyet dinh nut co an hay khong — dieu khong ai doan duoc luc can
        # ngat gap.
        #
        # Vi sao bac force phai kho bam khi dang bay: force luc do la tat dong co
        # giua khong trung. Phai la mot dong tac co chu y, khong phai cu bam nham.
        self._forced = False
        self._kill_hold = QTimer(self)
        self._kill_hold.setSingleShot(True)
        self._kill_hold.setInterval(2000)
        self._kill_hold.timeout.connect(self._force_disarm)
        self.btn_kill.pressed.connect(self._kill_pressed)
        self.btn_kill.released.connect(self._kill_released)
        self.btn_kill.clicked.connect(self._kill_clicked)

        self.red_box = QGroupBox()
        red_box = self.red_box
        r = QHBoxLayout(red_box)
        for b in self.reds:
            r.addWidget(b)

        self.note = QLabel()
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setStyleSheet("color:#e59866;")

        lay = QVBoxLayout(self)
        lay.addWidget(normal)
        lay.addWidget(self.mission_box)
        lay.addStretch(1)
        lay.addWidget(self.note)
        lay.addWidget(red_box)

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

        # TAKEOFF o REAL doi bam hai lan. Xem chu thich trong `_takeoff`.
        self._takeoff_armed = False
        self._takeoff_confirm = QTimer(self)
        self._takeoff_confirm.setSingleShot(True)
        self._takeoff_confirm.setInterval(int(CONFIRM_S * 1000))
        self._takeoff_confirm.timeout.connect(self._takeoff_cancel)

        bus.on("ack", self._on_ack)
        self.set_mode(None)
        i18n.on_change(self._retext)

    def _retext(self):
        self.normal_box.setTitle(t("ctl.normal_box"))
        self.lbl_mode.setText(t("ctl.mode_label"))
        self.lbl_alt.setText(t("ctl.alt_label"))
        self.btn_mode.setText(t("ctl.change_mode"))
        self.mission_box.setTitle(t("ctl.mission_box"))
        self.red_box.setTitle(t("ctl.red_box"))
        # ARM/DISARM/RTL/LAND/TAKEOFF khong dich: do la ten lenh MAVLink, doi
        # chieu voi tai lieu ArduPilot va voi GCS khac deu phai dung mot chu.
        self.btn_kill.setText("DISARM")
        self.btn_takeoff.setText("TAKEOFF")
        self._show_mission(self._mission_running)
        self.set_mode(self.mode)

    def _on_status(self, env):
        pwm = env["data"].get("RC_CHANNELS.chan3_raw")
        if pwm is not None:
            self._thr = (pwm, env["ts"])
        cm = env["data"].get("DISTANCE_SENSOR.current_distance")
        if cm is not None:
            lo = env["data"].get("DISTANCE_SENSOR.min_distance", 0)
            hi = env["data"].get("DISTANCE_SENSOR.max_distance", 10_000)
            self._rng = (cm, lo, hi, env["ts"])

    def _arm(self):
        """ARM, nhung chan khi can ga chua ve min.

        FC KHONG chan viec nay: `AP_Arming.cpp:81-115` chi kiem ga co THAP hon
        nguong failsafe khong, khong he kiem ga cao — kiem "ga qua cao" chi ap cho
        arm bang can lai. Do that luc 22:35 tren MicoAir743: ga 1496 -> `ack=0` ->
        dong co vot thang len 1654/1506/1347/1080. Thao canh thi do la tieng on;
        lap canh thi khong.
        """
        thr = self._thr
        if thr is None:
            self._say("log.arm_no_rc", 4)
        elif time.time() - thr[1] > STALE:
            self._say("log.arm_rc_old", 4, age=time.time() - thr[1])
        elif thr[0] > THR_ARM_MAX:
            self._say("log.arm_blocked", 3, pwm=thr[0], max=THR_ARM_MAX)
            return
        self._cmd("arm")

    def _check_pending(self):
        now = time.time()
        for action, deadline in list(self._pending.items()):
            if now > deadline:
                del self._pending[action]
                self._say("log.no_ack", 4, action=action, sec=ACK_TIMEOUT)

    # ------------------------------------------------------------------

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
            self._say("log.fc_denied", 3, name=name, why=t(f"ack.{res}"))
        else:
            self._say("log.fc_ok", 5, name=name)

    def set_mode(self, mode):
        """mode = REAL / SIM / REPLAY / None(chua ket noi)."""
        self.mode = mode
        live = mode in ("REAL", "SIM")
        for w in (self.btn_arm, self.btn_disarm, self.btn_mode, self.btn_takeoff,
                  self.mode_box, self.alt):
            w.setEnabled(live)
        # Nut do chi xam o REPLAY. Moi truong hop khac deu phai bam duoc.
        for b in self.reds:
            b.setEnabled(live)

        if mode is None:
            self.note.setText(t("ctl.note_none"))
        elif mode == "REPLAY":
            self.note.setText(t("ctl.note_replay"))
        elif mode == "REAL":
            self.note.setText(t("ctl.note_real"))
        else:
            self.note.setText("")

    def _on_mission_state(self, env):
        """Companion bao moi giay: node nao dang chay that.

        Node chay ma khong cam quyen thi no khong lai duoc — nhung no van an CPU
        va van chiem duong truyen. Thay ten no o day la co manh moi de lan ra khi
        drone hanh xu la.
        """
        self._show_mission(env["data"].get("running") or "")

    def _show_mission(self, running):
        self._mission_running = running
        if running:
            key = next((k for k, n in MISSIONS if n == running), None)
            self.mission_now.setText(
                t("ctl.mission_run", nice=t(key) if key else running, node=running))
            self.mission_now.setStyleSheet("color:#e59866;font-weight:bold;")
        else:
            self.mission_now.setText(
                t("ctl.mission_idle") if running == "" else t("ctl.mission_none"))
            self.mission_now.setStyleSheet("color:#8a939b;")

    def _cmd(self, action, args=None):
        r = authority.dispatch({"target": "sik", "action": action, "args": args or {}})
        # Force phai hien trong log: doc lai sau su co, "disarm" va "disarm FORCE"
        # la hai su kien khac han nhau.
        self._report(action + (" FORCE" if args and args.get("force") else ""), r)

    def _escape(self, action, args=None):
        """Nut do. Khong hoi lai, khong qua kiem tra nao — bam la di."""
        r = authority.dispatch({"action": action, "args": args or {}})
        self._report(action.upper() + (" FORCE" if args and args.get("force") else ""), r)

    # --- DISARM hai bac ---
    def _kill_pressed(self):
        self._forced = False
        self.btn_kill.setText(t("ctl.hold_kill"))
        self._kill_hold.start()

    def _kill_released(self):
        self._kill_hold.stop()
        self.btn_kill.setText("DISARM")

    def _on_ground(self):
        """Dang o duoi dat? True / False / None (= khong biet).

        Hai nguon doc lap, cai nao noi "duoi dat" cung du:

        1. `EXTENDED_SYS_STATE.landed_state` — chinh la `land_complete` cua FC.
           Dung nhung KHONG DU: do that, ga len giua tam la no thanh IN_AIR ngay
           ca khi may bay dang treo tren thanh, vi FC chi thay dong co quay. Bam
           theo mot minh no thi lenh thuong lai bi tu choi dung luc ga cao.
        2. Cam bien khoang cach — thu duy nhat do tối nay KHONG doi khi ga len:
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

    def _disarm_press(self):
        """Bam mot phat.

        Duoi dat: gui thang force, nen VI TRI CAN GA khong con anh huong gi —
        FC tu choi lenh disarm thuong bat cu khi nao no tin la dang bay, va no tin
        the ngay khi ga roi khoi min (do that: ga 1496 -> ack=4, 3/3 lan).

        Tren troi hoac khong biet do cao: van la lenh thuong. Muon cat dong co
        that thi giu 2 giay — mot cu bam nham khong duoc phep lam roi may bay.
        """
        self._escape("disarm", {"force": True} if self._on_ground() else None)

    def _kill_clicked(self):
        # Tha tay sau khi da force thi KHONG gui them lenh thuong: no chi lam ban
        # log va lam nguoi doc tuong lenh force da that bai.
        if self._forced:
            self._forced = False
            return
        self._disarm_press()

    def _force_disarm(self):
        self._forced = True
        self.btn_kill.setText(t("ctl.killed"))
        self._escape("disarm", {"force": True})

    def _takeoff_cancel(self):
        """Het gio cho, hoac da bam lan hai: tra nut ve nguyen trang."""
        self._takeoff_confirm.stop()
        self._takeoff_armed = False
        self.btn_takeoff.setText("TAKEOFF")

    def _takeoff(self):
        # ArduCopter chi that su cat canh bang MAV_CMD_NAV_TAKEOFF khi dang o
        # GUIDED. O STABILIZE no tra ve THAT BAI; o LOITER no tra ve CHAP NHAN
        # roi khong lam gi — kieu hong te nhat, giao dien trong nhu thanh cong.
        # Noi thang ly do o day con hon de nguoi bay doan qua chu "THAT BAI".
        fc = REGISTRY.value("heartbeat.mode")
        if fc and fc != "GUIDED":
            self._say("log.takeoff_need_guided", 4, mode=fc)
            return
        # Xac nhan o REAL bang cach BAM LAI, khong bang hop thoai. Do that: trong
        # luc mot QMessageBox dang mo, `activeModalWidget()` khac None nen cua so
        # chinh khong nhan input — ba nut do van bao `isEnabled() == True` nhung
        # bam khong an. Mot hop thoai xac nhan lam nut do chet trong vai giay la
        # doi thang muc 2.1 lay mot lop hoi lai.
        if self.mode == "REAL" and not self._takeoff_armed:
            self._takeoff_armed = True
            self.btn_takeoff.setText(t("ctl.takeoff_confirm", alt=self.alt.value()))
            self._takeoff_confirm.start()
            self._say("log.takeoff_confirm", 4, sec=CONFIRM_S, alt=self.alt.value())
            return
        self._takeoff_cancel()
        self._cmd("takeoff", {"alt": self.alt.value()})
        # "FC chap nhan" != "drone dang len". Neu mot node ROS2 dang stream setpoint
        # vao GUIDED thi lenh takeoff bi chinh cai stream do de len ngay sau do:
        # ACK ve result=0, dong co giu ga khong tai, drone nam im roi auto-disarm
        # sau DISARM_DELAY. Khong doi chieu do cao thi giao dien trong y het thanh cong.
        QTimer.singleShot(
            CLIMB_CHECK_S * 1000, lambda a0=REGISTRY.value("position.alt_rel", 0.0): self._check_climb(a0)
        )

    def _check_climb(self, alt0):
        alt = REGISTRY.value("position.alt_rel")
        if alt is None or alt - alt0 >= 1.0:
            return
        self._say("log.takeoff_no_climb", 3, sec=CLIMB_CHECK_S)

    def _report(self, action, result):
        if "error" in result:
            self._say("log.refused", 3, what=action, why=result["error"])
            return
        self._pending[action] = time.time() + ACK_TIMEOUT
        if "stale" in result:
            silent = result["stale"]
            how = (t("log.silent_never") if silent is None
                   else t("log.silent_for", sec=silent))
            self._say("log.queued_stale", 4, what=action, how=how)
        else:
            self._say("log.sent", 5, what=action)
