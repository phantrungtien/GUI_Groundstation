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
from core import i18n, param_doc
from core.i18n import t
from laptop import theme

STALE_COLOR = theme.MUTED

# Bang tham so keo THANG tu FC (PARAM_REQUEST_LIST), khong con danh sach ten
# ghim cung trong code: ten tham so doi theo firmware. ArduCopter 4.7-dev doi
# hang loat sang don vi SI — WPNAV_SPEED -> WP_SPD, PSC_VELXY_* -> PSC_NE_VEL_*,
# RTL_ALT -> RTL_ALT_M — va do that ngay 23/08/2026 tren MicoAir743 thi 30/63
# ten cu khong con ton tai. FC khong bao sai voi ten la, no chi im lang, nen bang
# ten cung tao ra dung kieu hong te nhat: giao dien trong ma khong noi vi sao.
QUIET_TICKS = 10  # 10 nhip 400 ms khong them tham so nao -> coi nhu FC gui xong

def fmt(key, v):
    """Chuoi hien trong cot Gia tri.

    Rieng hang SENSOR.* mang ma may tu adapter ("ok", "fail_off"...) chu khong
    mang chu doc duoc — xem `decode_sensors` trong core/adapters/sik.py. Doi sang
    chu o day, tuc la o dung noi biet ngon ngu nao dang chon.
    """
    if key.startswith("SENSOR."):
        return t(f"sensor.{v}")
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


class StatusTab(QWidget):
    FLUSH_MS = 200  # gom lai roi ve mot the: 50 msg/s x nhieu field, ve tung cai la phi

    def __init__(self, parent=None):
        super().__init__(parent)

        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.freeze = QCheckBox()
        self.btn_pid = QPushButton()
        self.btn_pid.clicked.connect(self.read_pid)
        self.btn_pid.setEnabled(False)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{theme.MUTED};")
        self.adapter = None

        self.model = QStandardItemModel(0, 3, self)
        self.model.setHorizontalHeaderLabels(["", "", ""])
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
        self.view.setColumnWidth(0, 320)
        self.view.setColumnWidth(1, 160)
        self.view.horizontalHeader().setStretchLastSection(True)  # cot giai thich an het phan con lai

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
        self._pending = {}  # ten field -> (gia tri, ts)
        self._sensor = {}  # SENSOR.* -> ma may, de dich lai khi doi ngon ngu

        bus.on("status", self._on_status)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush)
        self._timer.start(self.FLUSH_MS)

        self._pid_n = self._pid_quiet = 0  # dem tham so da ve, va so nhip im lang
        self._pid_timer = QTimer(self)
        self._pid_timer.timeout.connect(self._pid_tick)
        i18n.on_change(self._retext)

    def _retext(self):
        self.search.setPlaceholderText(t("st.search"))
        self.freeze.setText(t("st.freeze"))
        self.btn_pid.setToolTip(t("st.pid_tip"))
        self.count.setText(t("st.count", n=len(self._rows)))
        self.model.setHorizontalHeaderLabels(
            [t("st.col_field"), t("st.col_value"), t("st.col_doc")])
        for key, row in self._rows.items():
            self._tip([self.model.item(row, c) for c in range(3)], key)
        # Hang SENSOR.* mang chu chu khong mang so, nen phai dich lai tai cho —
        # doi voi hang so thi doi ngon ngu khong lam gi ca.
        for key, ma in self._sensor.items():
            self.model.item(self._rows[key], 1).setText(fmt(key, ma))
        if self._pid_timer.isActive():
            return  # dang doc: nhan tiep theo (400 ms nua) tu viet lai nut
        self.btn_pid.setText(t("st.read_param"))
        if self._pid_n:
            self.btn_pid.setToolTip(t("st.param_done", n=self._pid_n))

    def attach(self, adapter):
        """app.py goi khi ket noi/ngat. REPLAY khong hoi duoc gi — nut phai xam."""
        self.adapter = adapter
        self.btn_pid.setEnabled(adapter is not None and adapter.mode != "REPLAY")

    def read_pid(self):
        """Xin FC gui ca bang tham so, roi dem cai ve duoc.

        Mot yeu cau duy nhat, khong xin lai tung cai: FC tu bom het danh sach.
        Cai phai theo doi vi vay khong con la "con thieu ten nao" ma la "no con
        gui nua khong" — het im lang QUIET_TICKS nhip thi coi nhu xong.
        """
        if not self.adapter:
            return
        self._pid_n = self._pid_quiet = 0
        self.search.setText("PARAM.")  # loc san cho de nhin ket qua nho ve
        self.adapter.send("param_all", {})
        self._pid_timer.start(400)

    def _pid_tick(self):
        n = sum(1 for k in self._rows if k.startswith("PARAM."))
        self._pid_quiet = 0 if n > self._pid_n else self._pid_quiet + 1
        self._pid_n = n
        if self._pid_quiet >= QUIET_TICKS or not self.adapter:
            self._pid_timer.stop()
            self._retext()
            return
        self.btn_pid.setText(t("st.reading", n=n))

    def _on_status(self, env):
        """Chay o main thread (adapter da di qua Qt signal roi)."""
        if self.freeze.isChecked():
            return  # dang doc thi dung cho bang nhay
        for k, v in env["data"].items():
            self._pending[k] = (v, env["ts"])

    def _flush(self):
        for key, (value, ts) in self._pending.items():
            self._seen[key] = ts
            if key.startswith("SENSOR."):
                self._sensor[key] = value  # giu ma may de ve lai khi doi ngon ngu
            row = self._rows.get(key)
            if row is None:
                self._add_row(key, value)
            else:
                self.model.item(row, 1).setText(fmt(key, value))
        self._pending.clear()
        self._age()

    def _add_row(self, key, value):
        items = [QStandardItem(key), QStandardItem(fmt(key, value)), QStandardItem()]
        self._tip(items, key)
        self.model.appendRow(items)
        self._rows[key] = items[0].row()
        self.count.setText(t("st.count", n=len(self._rows)))

    def _tip(self, items, key):
        """Tham so nay la gi: cot Giai thich (nguoi dung chon 19/09 — re chuot
        moi thay la khong ai biet ma re), kem tooltip day du ca cac gia tri.

        Hang telemetry lay mo ta tu dinh nghia MAVLink (param_doc.field) — khong
        co thi de trong, khong bia.
        """
        text = tip = param_doc.field(key)
        if key.startswith("PARAM."):
            name = key.split(".", 1)[-1]
            text = tip = param_doc.doc(name)
            if vals := param_doc.values(name):
                tip = f"{text}\n\n{t('st.values')}: {vals}"
        items[2].setText(text)
        for it in items:
            it.setToolTip(tip)

    def _age(self):
        """Field ngung cap nhat phai xam di — dung hinh ma van den la noi doi.

        Da bo cot "Tuoi" (so giay ke tu goi cuoi) va cot "Nguon". Chot an toan
        van con nguyen va nam o chinh cot Gia tri: qua STALE giay khong co goi moi
        thi so xam di. Cai mat la CON SO bao nhieu giay, khong phai canh bao.
        """
        now = time.time()
        for key, row in self._rows.items():
            stale = now - self._seen.get(key, 0) > STALE
            self.model.item(row, 1).setForeground(
                QColor(STALE_COLOR) if stale else QColor(theme.TEXT)
            )
