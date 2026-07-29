"""Tab Control — ARM/mode/takeoff, switch phan quyen, va NHOM NUT DO.

Doc nguyen tac 2.1 truoc khi sua file nay.

Nhom nut do (RTL/LAND/DISARM) tach rieng ve mat ma nguon: chung goi thang
`authority.dispatch()` vao nhanh ESCAPE -> `SikAdapter.send()`, khong di qua
kiem tra quyen, khong di qua companion, khong di qua WebSocket.

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
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from core import authority, bus
from core.field import REGISTRY

MODES = ["STABILIZE", "ALT_HOLD", "LOITER", "GUIDED", "AUTO", "POSHOLD", "BRAKE"]

# MAV_RESULT
ACK_RESULT = {
    0: "CHAP NHAN", 1: "TAM THOI TU CHOI", 2: "TU CHOI", 3: "KHONG HO TRO",
    4: "THAT BAI", 5: "DANG CHAY", 6: "HUY",
}
ACK_CMD = {400: "ARM/DISARM", 22: "TAKEOFF", 20: "RTL", 21: "LAND", 176: "doi mode",
           16: "goto"}
ACK_TIMEOUT = 3.0  # giay cho FC tra loi truoc khi coi la khong co phan hoi

# Nhiem vu ROS2 chay TREN COMPANION. Laptop khong gui setpoint — no chi bao node
# ben kia doi trang thai. Doi nhiem vu bang cach chen lenh GUIDED tu day thi 33 ms
# sau bi chinh luong setpoint 30 Hz de len (do that o kich ban #5).
# Ten phai khop executable ben repo ROS2.
MISSIONS = [
    ("Bay vong tron", "mission_circle"),
    ("Qua vong gate", "mission_gates"),
    ("Bam theo nguoi", "trackinghuman"),
    ("Bay don gian", "mission_simple"),
]
CLIMB_CHECK_S = 6.0  # giay sau TAKEOFF moi doi chieu do cao that

RED_QSS = """
QPushButton {
    background:#b03a2e; color:#fff; font-size:15px; font-weight:bold;
    padding:16px 8px; border:1px solid #7b2318;
}
QPushButton:hover { background:#c0392b; }
QPushButton:disabled { background:#4a2a25; color:#8a7a76; }
"""


class ControlTab(QWidget):
    log = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = None  # che do ket noi hien tai (REAL/SIM/REPLAY/None)

        # --- phan quyen ---
        self.manual = QRadioButton("MANUAL (GCS)")
        self.auto = QRadioButton("AUTO (ROS2)")
        self.manual.setChecked(True)
        self.manual.toggled.connect(self._on_authority)
        self.who = QLabel()

        auth_box = QGroupBox("Ai dang cam quyen")
        row = QHBoxLayout(auth_box)
        row.addWidget(self.manual)
        row.addWidget(self.auto)
        row.addStretch(1)
        row.addWidget(self.who)

        # --- lenh thuong ---
        self.btn_arm = QPushButton("ARM")
        self.btn_disarm = QPushButton("DISARM")
        self.mode_box = QComboBox()
        self.mode_box.addItems(MODES)
        self.btn_mode = QPushButton("Doi mode")
        self.alt = QDoubleSpinBox()
        self.alt.setRange(1, 120)
        self.alt.setValue(5)
        self.alt.setSuffix(" m")
        self.btn_takeoff = QPushButton("TAKEOFF")

        self.btn_arm.clicked.connect(lambda: self._cmd("arm"))
        self.btn_disarm.clicked.connect(lambda: self._cmd("disarm"))
        self.btn_mode.clicked.connect(
            lambda: self._cmd("mode", {"name": self.mode_box.currentText()})
        )
        self.btn_takeoff.clicked.connect(self._takeoff)

        normal = QGroupBox("Lenh thuong (can quyen MANUAL)")
        g = QGridLayout(normal)
        g.addWidget(self.btn_arm, 0, 0)
        g.addWidget(self.btn_disarm, 0, 1)
        g.addWidget(QLabel("Mode:"), 1, 0)
        g.addWidget(self.mode_box, 1, 1)
        g.addWidget(self.btn_mode, 1, 2)
        g.addWidget(QLabel("Do cao:"), 2, 0)
        g.addWidget(self.alt, 2, 1)
        g.addWidget(self.btn_takeoff, 2, 2)

        # --- nhiem vu ROS2 ---
        self.mission_box = QGroupBox("Nhiem vu ROS2 — chay tren companion (can quyen AUTO)")
        mg = QGridLayout(self.mission_box)
        self.mission_btns = []
        for i, (label, name) in enumerate(MISSIONS):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, n=name, lb=label: self._mission(n, lb))
            mg.addWidget(b, i // 2, i % 2)
            self.mission_btns.append(b)
        self.btn_mission_stop = QPushButton("Dung nhiem vu")
        self.btn_mission_stop.clicked.connect(lambda: self._mission("", "dung nhiem vu"))
        mg.addWidget(self.btn_mission_stop, (len(MISSIONS) + 1) // 2, 0, 1, 2)
        self.mission_btns.append(self.btn_mission_stop)

        # Trang thai THAT do companion bao nguoc len, khong phai "da bam nut".
        self.mission_now = QLabel("nhiem vu: (chua co tin tu companion)")
        self.mission_now.setStyleSheet("color:#8a939b;")
        mg.addWidget(self.mission_now, (len(MISSIONS) + 1) // 2 + 1, 0, 1, 2)
        bus.on("mission", self._on_mission_state)

        # --- NUT DO ---
        self.btn_rtl = QPushButton("RTL")
        self.btn_land = QPushButton("LAND")
        self.btn_kill = QPushButton("DISARM")
        self.reds = (self.btn_rtl, self.btn_land, self.btn_kill)
        for b, act in zip(self.reds, ("rtl", "land", "disarm")):
            b.setStyleSheet(RED_QSS)
            b.setMinimumHeight(64)
            b.clicked.connect(lambda _=False, a=act: self._escape(a))

        red_box = QGroupBox("Nut do — di thang qua SiK, khong xin quyen")
        r = QHBoxLayout(red_box)
        for b in self.reds:
            r.addWidget(b)

        self.note = QLabel()
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setStyleSheet("color:#e59866;")

        lay = QVBoxLayout(self)
        lay.addWidget(auth_box)
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

        bus.on("ack", self._on_ack)
        self.set_mode(None)

    def _check_pending(self):
        now = time.time()
        for action, deadline in list(self._pending.items()):
            if now > deadline:
                del self._pending[action]
                self.log.emit(f"{action}: KHONG CO PHAN HOI tu FC sau {ACK_TIMEOUT:.0f}s")

    # ------------------------------------------------------------------

    def _on_ack(self, env):
        """FC tra loi lenh. Bi tu choi ma im lang la kieu hong nguy hiem nhat."""
        cmd = env["data"]["command"]
        res = env["data"]["result"]
        name = ACK_CMD.get(cmd, f"lenh {cmd}")
        self._pending.clear()  # FC da tra loi -> khong con cho gi nua
        if res != 0:
            self.log.emit(f"{name}: FC TU CHOI — {ACK_RESULT.get(res, res)}")
        else:
            self.log.emit(f"{name}: FC chap nhan")

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
            self.note.setText("Chua ket noi nguon nao.")
        elif mode == "REPLAY":
            self.note.setText("REPLAY — khong co gi o dau kia de gui lenh toi. Moi nut bi khoa.")
        elif mode == "REAL":
            self.note.setText("REAL — moi lenh duoi day di xuong may bay that.")
        else:
            self.note.setText("")
        self._on_authority()

    def _on_mission_state(self, env):
        """Companion bao moi giay: node nao dang chay that."""
        running = env["data"].get("running") or ""
        if running:
            nice = next((lb for lb, n in MISSIONS if n == running), running)
            self.mission_now.setText(f"nhiem vu dang chay: {nice}  ({running})")
            self.mission_now.setStyleSheet("color:#27ae60;font-weight:bold;")
        else:
            spawn = env["data"].get("spawn")
            self.mission_now.setText(
                "khong co nhiem vu nao chay" if spawn
                else "companion khong bat --spawn: nut chi gui lenh, khong khoi dong node"
            )
            self.mission_now.setStyleSheet("color:#8a939b;")

    def _mission(self, name, label):
        """Gui sang nua ROS2, KHONG gui xuong FC.

        Di qua dispatch nen no tu chan khi quyen dang o MANUAL: dang cam lai ma
        bam mot nhiem vu tu hanh la thu khong duoc phep xay ra im lang.
        """
        r = authority.dispatch({"target": "remote", "action": "mission", "args": {"name": name}})
        if "error" in r:
            self.log.emit(f"nhiem vu {label}: TU CHOI — {r['error']}")
        else:
            self.log.emit(f"nhiem vu: da gui '{label}' sang companion — "
                          "cho node ben do xac nhan, laptop khong tu biet no da doi hay chua")

    def _on_authority(self):
        who = authority.GCS if self.manual.isChecked() else authority.ROS2
        authority.set_authority(who)
        # Nhiem vu tu hanh chi bam duoc khi da giao quyen — de nguoi bay thay ranh
        # gioi, thay vi bam roi nhan mot dong tu choi.
        live = self.mode in ("REAL", "SIM") and who == authority.ROS2
        for b in self.mission_btns:
            b.setEnabled(live)
        self.who.setText(f"→ {who.upper()}")
        self.who.setStyleSheet(
            "color:#27ae60;font-weight:bold;" if who == authority.GCS
            else "color:#e59866;font-weight:bold;"
        )

    def _cmd(self, action, args=None):
        r = authority.dispatch({"target": "sik", "action": action, "args": args or {}})
        self._report(action, r)

    def _escape(self, action):
        """Nut do. Khong hoi lai, khong kiem tra quyen — bam la di."""
        r = authority.dispatch({"action": action})
        # dispatch() da keo quyen ve GCS; switch phai theo, khong duoc de giao
        # dien noi "AUTO" trong khi quyen thuc te da ve tay nguoi bay.
        self.manual.setChecked(True)
        self._report(action.upper(), r)

    def _takeoff(self):
        # ArduCopter chi that su cat canh bang MAV_CMD_NAV_TAKEOFF khi dang o
        # GUIDED. O STABILIZE no tra ve THAT BAI; o LOITER no tra ve CHAP NHAN
        # roi khong lam gi — kieu hong te nhat, giao dien trong nhu thanh cong.
        # Noi thang ly do o day con hon de nguoi bay doan qua chu "THAT BAI".
        fc = REGISTRY.value("heartbeat.mode")
        if fc and fc != "GUIDED":
            self.log.emit(f"takeoff: can mode GUIDED truoc, dang o {fc} — doi mode roi bam lai")
            return
        if self.mode == "REAL":
            ok = QMessageBox.question(
                self, "TAKEOFF that",
                f"Cat canh len {self.alt.value():.0f} m tren DRONE THAT?",
            )
            if ok != QMessageBox.Yes:
                return
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
        self.log.emit(
            f"takeoff: FC da nhan nhung do cao khong doi sau {CLIMB_CHECK_S:.0f}s "
            "— nghi co node dang stream setpoint vao GUIDED, kiem tra ben companion"
        )

    def _report(self, action, result):
        if "error" in result:
            self.log.emit(f"{action}: TU CHOI — {result['error']}")
            return
        self._pending[action] = time.time() + ACK_TIMEOUT
        if "stale" in result:
            silent = result["stale"]
            how_long = "chua nhan goi nao" if silent is None else f"im lang {silent:.0f}s"
            self.log.emit(f"{action}: da xep lenh nhung link {how_long} — CHUA CHAC TOI NOI")
        else:
            self.log.emit(f"{action}: da gui")
