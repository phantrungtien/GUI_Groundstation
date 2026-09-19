"""WidgetItem — ve mot QWidget co san (ban do, camera) len man QML.

Ban do (`MapWidget`, ~900 dong: tile offline, rao, duong bay, mui drone) va o
camera da duoc do va kiem ky. Viet lai bang QML la hai ban de lech nhau; o day
chi goi `QWidget.render()` cua chinh no vao painter cua QML.

ponytail: ve lai theo nhip `fps` chu khong theo su kien — widget an khong phat
yeu cau ve. Ban do 5 Hz (cung nhip FlightTab.refresh). Camera ve them moi khi co
khung moi (`_follow`), timer chi con lo o xam.
"""

from PySide6.QtCore import Property, QPoint, QTimer, Signal
from PySide6.QtQuick import QQuickPaintedItem

# ponytail: mot bang chung cho ca tien trinh = mot man cam ung moi tien trinh (app
# chi co mot cua so). Can nhieu cua so thi chuyen bang nay vao tung backend.
WIDGETS = {}  # ten -> QWidget; backend dang ky TRUOC khi nap QML


class WidgetItem(QQuickPaintedItem):
    nameChanged = Signal()
    fpsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._name = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._set_fps(5)

    def _get_name(self):
        return self._name

    def _set_name(self, v):
        self._follow(WIDGETS.get(self._name), False)
        self._name = v
        self._follow(WIDGETS.get(v), True)
        self.nameChanged.emit()
        self.update()

    def _follow(self, w, on):
        """Camera: ve lai DUNG LUC co khung moi, khong doi timer.

        Timer 15 Hz lay mau nguon 15 fps thi hai nhip phach nhau — khung ve hai lan,
        khung bi bo qua — hinh giat du Pi phat deu va GUI nhan du 15 fps (18/09/2026).
        Timer van chay: no ve o xam khi mat hinh, va ve lai widget khong co `source`.
        """
        sig = getattr(getattr(w, "source", None), "updated", None)
        if sig is not None:
            (sig.connect if on else sig.disconnect)(self.update)

    def _get_fps(self):
        return 1000 // max(1, self._timer.interval())

    def _set_fps(self, v):
        self._timer.start(max(1, int(1000 / max(1, v))))
        self.fpsChanged.emit()

    name = Property(str, _get_name, _set_name, notify=nameChanged)
    fps = Property(int, _get_fps, _set_fps, notify=fpsChanged)

    def paint(self, painter):
        w = WIDGETS.get(self._name)
        if w is None:
            return
        size = self.size().toSize()
        if w.size() != size:
            w.resize(size)
        w.render(painter, QPoint(0, 0))
