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

from core import bus, i18n
from core.field import REGISTRY
from core.i18n import t
from laptop import theme

from laptop.commands import (  # noqa: F401 — selfcheck import tu day
    ACK_CMD, ACK_TIMEOUT, CLIMB_CHECK_S, MODES, RNG_GROUND_CM, THR_ARM_MAX, Commands)

# Ten node nhiem vu ben repo ROS2 -> ten doc duoc. Chi con dung de dich mot chuoi
# trang thai companion bao len; laptop khong khoi dong nhiem vu nao nua.
MISSIONS = [
    ("mission.circle", "mission_circle"),
    ("mission.gates", "mission_gates"),
    ("mission.human", "trackinghuman"),
    ("mission.simple", "mission_simple"),
]
CONFIRM_S = 3.0  # cua so bam lai de xac nhan TAKEOFF o che do REAL

RED_QSS = theme.danger_button()


class ControlTab(QWidget):
    # (chu da dich, muc do MAV_SEVERITY). Muc do di kem chu KHONG duoc suy tu chu:
    # truoc day app.py bat chuoi "TU CHOI"/"KHONG" trong text de to mau, va cach do
    # chet ngay khi giao dien noi tieng Anh.
    log = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = None  # che do ket noi hien tai (REAL/SIM/REPLAY/None)
        # Moi chot chan va theo doi ACK nam o day — dung chung voi man bay cam ung.
        self.cmd = Commands(self)
        self.cmd.log.connect(self.log)
        self._say = self.cmd.say

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

        self.btn_arm.clicked.connect(self.cmd.arm)
        self.btn_disarm.clicked.connect(self.cmd.disarm)
        self.btn_mode.clicked.connect(lambda: self.cmd.mode(self.mode_box.currentText()))
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
        self.mission_now.setStyleSheet(f"color:{theme.MUTED};")
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
        self.btn_rtl.clicked.connect(lambda: self.cmd.escape("rtl"))
        self.btn_land.clicked.connect(lambda: self.cmd.escape("land"))

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
        self.note.setStyleSheet(f"color:{theme.WARN};")

        lay = QVBoxLayout(self)
        lay.addWidget(normal)
        lay.addWidget(self.mission_box)
        lay.addStretch(1)
        lay.addWidget(self.note)
        lay.addWidget(red_box)

        # TAKEOFF o REAL doi bam hai lan. Xem chu thich trong `_takeoff`.
        self._takeoff_armed = False
        self._takeoff_confirm = QTimer(self)
        self._takeoff_confirm.setSingleShot(True)
        self._takeoff_confirm.setInterval(int(CONFIRM_S * 1000))
        self._takeoff_confirm.timeout.connect(self._takeoff_cancel)

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
            self.mission_now.setStyleSheet(f"color:{theme.WARN};font-weight:bold;")
        else:
            self.mission_now.setText(
                t("ctl.mission_idle") if running == "" else t("ctl.mission_none"))
            self.mission_now.setStyleSheet(f"color:{theme.MUTED};")

    # --- DISARM hai bac ---
    def _kill_pressed(self):
        self._forced = False
        self.btn_kill.setText(t("ctl.hold_kill"))
        self._kill_hold.start()

    def _kill_released(self):
        self._kill_hold.stop()
        self.btn_kill.setText("DISARM")

    def _kill_clicked(self):
        # Tha tay sau khi da force thi KHONG gui them lenh thuong: no chi lam ban
        # log va lam nguoi doc tuong lenh force da that bai.
        if self._forced:
            self._forced = False
            return
        self.cmd.kill()

    def _force_disarm(self):
        self._forced = True
        self.btn_kill.setText(t("ctl.killed"))
        self.cmd.force_disarm()

    def _takeoff_cancel(self):
        """Het gio cho, hoac da bam lan hai: tra nut ve nguyen trang."""
        self._takeoff_confirm.stop()
        self._takeoff_armed = False
        self.btn_takeoff.setText("TAKEOFF")

    def _takeoff(self):
        # Xac nhan o REAL bang cach BAM LAI, khong bang hop thoai. Do that: trong
        # luc mot QMessageBox dang mo, `activeModalWidget()` khac None nen cua so
        # chinh khong nhan input — ba nut do van bao `isEnabled() == True` nhung
        # bam khong an. Mot hop thoai xac nhan lam nut do chet trong vai giay la
        # doi thang muc 2.1 lay mot lop hoi lai.
        # Mode sai thi chan NGAY tu lan bam dau — khong bat nguoi bay bam lai roi
        # moi noi la khong duoc.
        fc = REGISTRY.value("heartbeat.mode")
        if fc and fc != "GUIDED":
            self._say("log.takeoff_need_guided", 4, mode=fc)
            return
        if self.mode == "REAL" and not self._takeoff_armed:
            self._takeoff_armed = True
            self.btn_takeoff.setText(t("ctl.takeoff_confirm", alt=self.alt.value()))
            self._takeoff_confirm.start()
            self._say("log.takeoff_confirm", 4, sec=CONFIRM_S, alt=self.alt.value())
            return
        self._takeoff_cancel()
        self.cmd.takeoff(self.alt.value())
