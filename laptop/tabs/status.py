"""Tab Status — bang tra cuu MOI field so FC gui len.

Khong hardcode field nao: nguon la topic "status", von duoc trai phang tu
msg.to_dict() ngay tai adapter. Doi firmware hay bat them message la bang tu dai
ra, khong phai sua code. Day cung la cong cu de kiem chung moi tab con lai.
"""

import time

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core import bus
from core.adapters.sik import STALE

SRC_COLOR = {"sik": "#27ae60", "remote": "#3498db"}
STALE_COLOR = "#7f8c8d"

# Tham so tinh chinh (PID). FC KHONG tu gui tham so — phai hoi tung cai. Hoi ca
# 1431 cai thi chiem duong truyen vai chuc giay, nen chi hoi dung nhom nay.
# Ten theo ArduCopter 4.x; firmware khac thi cai nao khong co se im lang bo qua.
def _pid_names():
    names = []
    for axis in ("RLL", "PIT", "YAW"):
        names += [f"ATC_RAT_{axis}_{k}" for k in
                  ("P", "I", "D", "IMAX", "FLTT", "FLTE", "FLTD", "SMAX")]
        names.append(f"ATC_ANG_{axis}_P")
    for grp, keys in (
        ("PSC_POSXY", ("P",)), ("PSC_POSZ", ("P",)),
        ("PSC_VELXY", ("P", "I", "D", "IMAX", "FLTE", "FLTD")),
        ("PSC_VELZ", ("P", "I", "D", "IMAX", "FLTE", "FLTD")),
        ("PSC_ACCZ", ("P", "I", "D", "IMAX", "FLTT", "FLTE", "FLTD", "SMAX")),
    ):
        names += [f"{grp}_{k}" for k in keys]
    names += ["MOT_THST_HOVER", "MOT_SPIN_ARM", "MOT_SPIN_MIN", "MOT_SPIN_MAX",
              "INS_GYRO_FILTER", "INS_ACCEL_FILTER",
              "WPNAV_SPEED", "WPNAV_SPEED_UP", "WPNAV_SPEED_DN", "WPNAV_ACCEL",
              "LOIT_SPEED", "LOIT_ACC_MAX", "ANGLE_MAX", "PILOT_SPEED_UP"]
    return names


PID_PARAMS = _pid_names()


def fmt(v):
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


class StatusTab(QWidget):
    FLUSH_MS = 200  # gom lai roi ve mot the: 50 msg/s x nhieu field, ve tung cai la phi

    def __init__(self, parent=None):
        super().__init__(parent)

        self.search = QLineEdit()
        self.search.setPlaceholderText("loc theo ten field, vd: ATTITUDE hoac volt")
        self.search.setClearButtonEnabled(True)
        self.freeze = QCheckBox("Tam dung")
        self.btn_pid = QPushButton(f"Doc {len(PID_PARAMS)} tham so PID")
        self.btn_pid.setToolTip("FC khong tu gui tham so — bam de hoi. Ket qua vao hang PARAM.*")
        self.btn_pid.clicked.connect(self.read_pid)
        self.btn_pid.setEnabled(False)
        self.count = QLabel("0 field")
        self.count.setStyleSheet("color:#8a9199;")
        self.adapter = None

        self.model = QStandardItemModel(0, 4, self)
        self.model.setHorizontalHeaderLabels(["Field", "Gia tri", "Nguon", "Tuoi"])
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(0)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)

        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(0, Qt.AscendingOrder)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.verticalHeader().setVisible(False)
        self.view.setAlternatingRowColors(True)
        self.view.setColumnWidth(0, 260)
        self.view.setColumnWidth(1, 140)

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.btn_pid)
        top.addWidget(self.freeze)
        top.addWidget(self.count)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.view)

        self._rows = {}  # ten field -> so hang trong model goc
        self._seen = {}  # ten field -> ts cap nhat cuoi
        self._pending = {}  # ten field -> (gia tri, src, ts)

        bus.on("status", self._on_status)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush)
        self._timer.start(self.FLUSH_MS)

        self._pid_ticks = 0
        self._pid_timer = QTimer(self)
        self._pid_timer.timeout.connect(self._pid_tick)

    def attach(self, adapter):
        """app.py goi khi ket noi/ngat. REPLAY khong hoi duoc gi — nut phai xam."""
        self.adapter = adapter
        self.btn_pid.setEnabled(adapter is not None and adapter.mode != "REPLAY")

    def read_pid(self):
        """Hoi theo nhip va tu xin lai cai chua ve.

        Ban het 63 yeu cau mot luot thi FC chi tra ve ~25: hang doi gui tham so cua
        no co han, phan con lai roi im lang — va giao dien trong nhu da doc xong.
        Moi nhip xin lai dung nhung cai con thieu, nen mat goi tu lanh.
        """
        if not self.adapter:
            return
        self._pid_ticks = 0
        self.search.setText("PARAM.")  # loc san cho de nhin ket qua nho ve
        self._pid_timer.start(400)

    def _pid_tick(self):
        missing = [n for n in PID_PARAMS if f"PARAM.{n}" not in self._rows]
        self._pid_ticks += 1
        # Bo cuoc sau ~8s: ten nao khong co tren firmware nay thi FC khong bao gio
        # tra loi, xin mai la treo vong lap.
        if not missing or self._pid_ticks > 20 or not self.adapter:
            self._pid_timer.stop()
            self.btn_pid.setText(f"Doc {len(PID_PARAMS)} tham so PID")
            if missing:
                self.btn_pid.setToolTip(
                    f"{len(missing)} tham so khong co tren firmware nay: "
                    + ", ".join(missing[:6]) + ("..." if len(missing) > 6 else "")
                )
            return
        self.btn_pid.setText(f"Dang doc... con {len(missing)}")
        self.adapter.send("param_read", {"names": missing[:8]})

    def _on_status(self, env):
        """Chay o main thread (adapter da di qua Qt signal roi)."""
        if self.freeze.isChecked():
            return  # dang doc thi dung cho bang nhay
        for k, v in env["data"].items():
            self._pending[k] = (v, env["src"], env["ts"])

    def _flush(self):
        for key, (value, src, ts) in self._pending.items():
            self._seen[key] = ts
            row = self._rows.get(key)
            if row is None:
                self._add_row(key, value, src)
            else:
                self.model.item(row, 1).setText(fmt(value))
        self._pending.clear()
        self._age()

    def _add_row(self, key, value, src):
        items = [QStandardItem(key), QStandardItem(fmt(value)),
                 QStandardItem(f"● {src}"), QStandardItem("")]
        items[2].setForeground(QColor(SRC_COLOR.get(src, "#bdc3c7")))
        self.model.appendRow(items)
        self._rows[key] = items[0].row()
        self.count.setText(f"{len(self._rows)} field")

    def _age(self):
        """Field ngung cap nhat phai xam di — dung hinh ma van den la noi doi."""
        now = time.time()
        for key, row in self._rows.items():
            age = now - self._seen.get(key, 0)
            stale = age > STALE
            self.model.item(row, 3).setText(f"{age:.0f}s" if stale else "")
            self.model.item(row, 1).setForeground(
                QColor(STALE_COLOR) if stale else QColor("#dcdcdc")
            )
