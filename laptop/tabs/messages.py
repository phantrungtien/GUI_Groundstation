"""Tab Messages — log STATUSTEXT tu FC, loc theo muc do nghiem trong.

Day thuong la cho duy nhat FC noi ro no tu choi lenh vi ly do gi ("PreArm: ...").
"""

import re
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from laptop import theme

# MAV_SEVERITY
SEVERITY = {
    0: "EMERGENCY", 1: "ALERT", 2: "CRITICAL", 3: "ERROR",
    4: "WARNING", 5: "NOTICE", 6: "INFO", 7: "DEBUG",
}
SEV_COLOR = {
    0: theme.CRIT, 1: theme.CRIT, 2: "#ff8a5c", 3: "#ff8a5c",
    4: theme.WARN, 5: theme.TEXT, 6: theme.TEXT, 7: theme.MUTED,
}
# Bay dai vo han se an het RAM trong chuyen bay dai — chuyen do soak test do duoc.
MAX_ROWS = 2000

FILTERS = [("msg.f_all", 7), ("msg.f_notice", 5), ("msg.f_warn", 4), ("msg.f_err", 3)]


# Tu muc nay tro len (so CANG NHO cang nang) thi tinh la canh bao chua doc.
# 4 = WARNING; PreArm cua FC ve o muc nay.
WARN_SEV = 4


class MessagesTab(QWidget):
    #: So canh bao den trong luc tab nay khong hien. app.py gan len ten tab.
    unread = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._unread = 0
        self._current = False

        self.filter = QComboBox()
        self.filter.addItems([""] * len(FILTERS))
        self.filter.currentIndexChanged.connect(self._apply_filter)

        self.clear_btn = QPushButton()
        self.clear_btn.clicked.connect(self._clear)
        self.count = QLabel("0")
        self.count.setStyleSheet(f"color:{theme.MUTED};")

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

        # Muc D.7 bat doc "khong co STATUSTEXT do ton dong" — nhung phai CHUYEN
        # TAB moi thay. Dem len ten tab de biet co gi phai doc ma khong phai roi
        # man hinh bay di kiem tra.
        if sev <= WARN_SEV and not self._current:
            self._unread += 1
            self.unread.emit(self._unread)

        stamp = time.strftime("%H:%M:%S", time.localtime(env["ts"]))
        item = QListWidgetItem(f"{stamp}  [{SEVERITY.get(sev, sev)}]  {text}")
        item.setForeground(QColor(SEV_COLOR.get(sev, theme.TEXT)))
        item.setData(Qt.UserRole, sev)
        item.setHidden(sev > self._threshold())

        # Moi nhat nam tren cung. Dang o dinh thi dong moi hien ngay; nguoi dung
        # keo xuong doc dong cu thi ghim dong dang doc, khong de bi day troi xuong.
        anchor = self.list.itemAt(0, 0) if self.list.verticalScrollBar().value() else None

        self.list.insertItem(0, item)
        if anchor is not None:
            self.list.scrollToItem(anchor, QAbstractItemView.PositionAtTop)
        # cat SAU khi ghim: dong bi cat co the chinh la anchor
        while self.list.count() > MAX_ROWS:
            self.list.takeItem(self.list.count() - 1)
        self.count.setText(str(self.list.count()))

    def show_text(self, text):
        """Cham dong loi tren man bay -> nhay toi dong do o day (moi nhat khop truoc).

        Bo duoi AlertBook gan them ("  ×N" khi gop dong trung, "  (+k)" khi cat
        bot) roi so 40 ky tu dau. Dong dang bi bo loc an thi hien rieng no ra —
        nguoi ta cham vao de doc, khong phai de doi bo loc.
        """
        needle = re.sub(r"(  ×\d+)?(  \(\+\d+\))?$", "", text).strip()[:40]
        for i in range(self.list.count()):
            item = self.list.item(i)
            if needle and needle in item.text():
                item.setHidden(False)
                self.list.setCurrentItem(item)
                self.list.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                return True
        return False

    def _apply_filter(self):
        t = self._threshold()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(item.data(Qt.UserRole) > t)

    def set_current(self, on):
        """app.py goi khi doi tab. Mo tab nay ra = da doc, xoa dem.

        Khong dung isVisible(): no chi dung khi cua so DA duoc show(), nen bai
        kiem se phai bat mot cua so that len man hinh nguoi dung giua luc chay
        selfcheck. Mot co tuong minh thi kiem duoc ma khong cuop focus cua ai.
        """
        self._current = on
        if on and self._unread:
            self._unread = 0
            self.unread.emit(0)

    def _clear(self):
        self.list.clear()
        self.count.setText("0")
