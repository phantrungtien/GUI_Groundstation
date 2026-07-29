"""Attitude indicator — duong chan troi theo roll + pitch (QPainter).

roll/pitch la goc than may bay, giong nhau o ca NED lan ENU nen khong phai doi
he toa do o day.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

SKY = QColor(52, 122, 183)
GROUND = QColor(120, 85, 52)
LINE = QColor(235, 240, 245)
FRAME = QColor(120, 130, 140)
MARK = QColor(241, 196, 15)

PX_PER_DEG = 2.2  # do dich cua duong chan troi tren moi do pitch


class AttitudeWidget(QWidget):
    def __init__(self, parent=None, size=140):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._roll = 0.0  # radian
        self._pitch = 0.0

    def set_attitude(self, roll, pitch):
        if roll is None or pitch is None:
            return
        if abs(roll - self._roll) > 0.002 or abs(pitch - self._pitch) > 0.002:
            self._roll, self._pitch = float(roll), float(pitch)
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        r = w / 2 - 4
        c = QPointF(w / 2, w / 2)

        clip = QPainterPath()
        clip.addEllipse(c, r, r)
        p.save()
        p.setClipPath(clip)
        p.translate(c)
        p.rotate(-math.degrees(self._roll))
        off = math.degrees(self._pitch) * PX_PER_DEG

        big = r * 3
        p.setPen(Qt.NoPen)
        p.setBrush(SKY)
        p.drawRect(QRectF(-big, -big + off, 2 * big, big))
        p.setBrush(GROUND)
        p.drawRect(QRectF(-big, off, 2 * big, big))
        p.setPen(QPen(LINE, 1.6))
        p.drawLine(int(-big), int(off), int(big), int(off))

        # vach pitch moi 10 do
        p.setFont(QFont("", 7))
        for deg in (-30, -20, -10, 10, 20, 30):
            y = off - deg * PX_PER_DEG
            half = 16 if deg % 20 == 0 else 9
            p.setPen(QPen(LINE, 1))
            p.drawLine(int(-half), int(y), int(half), int(y))
            if deg % 20 == 0:
                p.drawText(QRectF(half + 2, y - 6, 18, 12), Qt.AlignLeft, f"{abs(deg)}")
        p.restore()

        # vong ngoai che goc vuong
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self.palette().window().color(), 8))
        p.drawEllipse(c, r + 4, r + 4)
        p.setPen(QPen(FRAME, 1.5))
        p.drawEllipse(c, r, r)

        # ky hieu may bay co dinh
        p.setPen(QPen(MARK, 2.5))
        p.drawLine(int(c.x() - 24), int(c.y()), int(c.x() - 8), int(c.y()))
        p.drawLine(int(c.x() + 8), int(c.y()), int(c.x() + 24), int(c.y()))
        p.drawPoint(c)

        p.setPen(LINE)
        p.setFont(QFont("", 8))
        p.drawText(
            QRectF(0, w - 18, w, 16), Qt.AlignCenter,
            f"R {math.degrees(self._roll):+.0f}°  P {math.degrees(self._pitch):+.0f}°",
        )
