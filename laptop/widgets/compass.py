"""La ban — QPainter, xoay theo heading.

heading la do tinh tu huong bac theo chieu kim dong ho (khong phu thuoc NED/ENU).
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

BG = QColor(20, 23, 25, 210)
RING = QColor(120, 130, 140)
TICK = QColor(200, 210, 220)
NEEDLE = QColor(231, 76, 60)


class Compass(QWidget):
    def __init__(self, parent=None, size=120):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._heading = 0.0

    def set_heading(self, deg):
        if deg is None:
            return
        deg = float(deg) % 360.0
        if abs(deg - self._heading) > 0.2:
            self._heading = deg
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        r = w / 2 - 4
        c = QPointF(w / 2, w / 2)

        p.setBrush(BG)
        p.setPen(QPen(RING, 1.5))
        p.drawEllipse(c, r, r)

        p.save()
        p.translate(c)
        # Xoay mat so nguoc chieu heading: mui bay luon chi len tren.
        p.rotate(-self._heading)
        p.setFont(QFont("", 9, QFont.Bold))
        for deg, label in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            p.save()
            p.rotate(deg)
            p.setPen(QPen(NEEDLE if label == "N" else TICK, 2))
            p.drawLine(0, int(-r + 2), 0, int(-r + 10))
            p.setPen(TICK)
            p.drawText(QRectF(-10, -r + 12, 20, 14), Qt.AlignCenter, label)
            p.restore()
        for deg in range(0, 360, 30):
            if deg % 90 == 0:
                continue
            p.save()
            p.rotate(deg)
            p.setPen(QPen(RING, 1))
            p.drawLine(0, int(-r + 2), 0, int(-r + 7))
            p.restore()
        p.restore()

        # Mui bay: tam giac co dinh o dinh
        p.setPen(Qt.NoPen)
        p.setBrush(NEEDLE)
        # QPolygonF chu khong phai ba QPointF roi: PySide6 khong nhan varargs o
        # day va cham thang vao overload sai -> segfault, khong phai TypeError.
        p.drawPolygon(QPolygonF([
            QPointF(c.x(), c.y() - r + 14),
            QPointF(c.x() - 6, c.y() - r + 26),
            QPointF(c.x() + 6, c.y() - r + 26),
        ]))
        p.setPen(TICK)
        p.setFont(QFont("", 10, QFont.Bold))
        p.drawText(self.rect(), Qt.AlignCenter, f"{self._heading:.0f}°")
