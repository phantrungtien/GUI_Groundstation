"""Tab Messages — log STATUSTEXT tu FC, loc theo muc do nghiem trong.

Day thuong la cho duy nhat FC noi ro no tu choi lenh vi ly do gi ("PreArm: ...").
"""

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import bus
from core import i18n
from core.i18n import t

# MAV_SEVERITY
SEVERITY = {
    0: "EMERGENCY", 1: "ALERT", 2: "CRITICAL", 3: "ERROR",
    4: "WARNING", 5: "NOTICE", 6: "INFO", 7: "DEBUG",
}
SEV_COLOR = {
    0: "#ff5252", 1: "#ff5252", 2: "#ff7043", 3: "#ff7043",
    4: "#ffb300", 5: "#dcdcdc", 6: "#dcdcdc", 7: "#8a9199",
}
# Bay dai vo han se an het RAM trong chuyen bay dai — chuyen do soak test do duoc.
MAX_ROWS = 2000

FILTERS = [("msg.f_all", 7), ("msg.f_notice", 5), ("msg.f_warn", 4), ("msg.f_err", 3)]


class MessagesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.filter = QComboBox()
        self.filter.addItems([""] * len(FILTERS))
        self.filter.currentIndexChanged.connect(self._apply_filter)

        self.clear_btn = QPushButton()
        self.clear_btn.clicked.connect(self._clear)
        self.count = QLabel("0")
        self.count.setStyleSheet("color:#8a9199;")

        self.list = QListWidget()
        self.list.setWordWrap(True)

        self.lbl_level = QLabel()
        top = QHBoxLayout()
        top.addWidget(self.lbl_level)
        top.addWidget(self.filter)
        top.addStretch(1)
        top.addWidget(self.count)
        top.addWidget(self.clear_btn)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.list)

        bus.on("text", self._on_text)
        i18n.on_change(self._retext)

    def _retext(self):
        self.lbl_level.setText(t("msg.level"))
        self.clear_btn.setText(t("msg.clear"))
        # Dong da nam trong danh sach KHONG dich lai: chung la ban ghi cua mot thoi
        # diem da qua (FC noi gi, app bao gi), viet lai la sua lich su.
        for i, (key, _) in enumerate(FILTERS):
            self.filter.setItemText(i, t(key))

    def _threshold(self):
        return FILTERS[self.filter.currentIndex()][1]

    def add_local(self, text, sev=5):
        """Dong do CHINH APP sinh ra (ket qua bam nut), khong phai FC noi.

        Truoc day chung chi hien 6 giay o thanh trang thai roi bien mat — bam nut
        xong khong dong y, hoi lai "vi sao" thi khong con gi de doc. Ghi vao day
        (va vao logs/commands.log) de con truy nguoc duoc.
        """
        self._on_text({"src": "app", "topic": "text", "ts": time.time(),
                       "data": {"severity": sev, "text": f"[APP] {text}"}})

    def _on_text(self, env):
        sev = env["data"].get("severity", 6)
        text = env["data"].get("text", "")
        if isinstance(text, bytes):
            text = text.decode("utf-8", "replace")
        text = text.rstrip("\x00").strip()
        if not text:
            return

        stamp = time.strftime("%H:%M:%S", time.localtime(env["ts"]))
        item = QListWidgetItem(f"{stamp}  [{SEVERITY.get(sev, sev)}]  {text}")
        item.setForeground(QColor(SEV_COLOR.get(sev, "#dcdcdc")))
        item.setData(Qt.UserRole, sev)
        item.setHidden(sev > self._threshold())

        # cuon theo chi khi dang o day — nguoi dung keo len doc thi de yen
        bar = self.list.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4

        self.list.addItem(item)
        while self.list.count() > MAX_ROWS:
            self.list.takeItem(0)
        self.count.setText(str(self.list.count()))
        if at_bottom:
            self.list.scrollToBottom()

    def _apply_filter(self):
        t = self._threshold()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(item.data(Qt.UserRole) > t)

    def _clear(self):
        self.list.clear()
        self.count.setText("0")
