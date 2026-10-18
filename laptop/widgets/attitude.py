"""Dong ho tu the — chan troi (roll + pitch) nam trong vong la ban (yaw), kieu QGC.

Mot dong ho thay hai widget cu (chan troi + la ban rieng): tren dien thoai khong du
cho cho hai cai, va ca hai deu co dinh kich thuoc nen ve vao o nho hon la bi CAT
(do 19/10: la ban 120 px trong o ~50 dp chi con mot cung tron o goc). Cai nay ve
theo kich thuoc that cua o — moi net, moi co chu tinh tu ban kinh.

roll/pitch: goc than may bay, giong nhau o NED lan ENU. heading: do tu bac theo
chieu kim dong ho. Vong la ban QUAY (huong dang bay luon o dinh, duoi mui ten vang).
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from laptop import theme

SKY = QColor("#4b91d5")
GROUND = QColor("#7a5534")
LINE = QColor(theme.TEXT)
FRAME = QColor(theme.BORDER_HI)
MARK = QColor("#ffe04b")  # ky hieu may bay + mui huong — vang, khong trung mau trang thai
RING = QColor(theme.SURFACE)
RING.setAlpha(225)
TICK = QColor(theme.TEXT_DIM)
NORTH = QColor(theme.ACCENT)
DEG_SPAN = 40.0  # pitch +-40 do cham mep chan troi


def _font(px):
    f = QFont()
    f.setPixelSize(max(7, int(px)))
    f.setBold(True)
    return f


class AttitudeDial(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(48, 48)
        self.setAttribute(Qt.WA_TranslucentBackground)  # tron, khong to nen o vuong
        self._roll = 0.0  # radian
        self._pitch = 0.0
        self._heading = None  # chua co thi ghi "--", khong gia vo la 0 = huong Bac

    def set_attitude(self, roll, pitch):
        if roll is None or pitch is None:
            return
        if abs(roll - self._roll) > 0.002 or abs(pitch - self._pitch) > 0.002:
            self._roll, self._pitch = float(roll), float(pitch)
            self.update()

    def set_heading(self, deg):
        if deg is None:
            return
        deg = float(deg) % 360.0
        if self._heading is None or abs(deg - self._heading) > 0.2:
            self._heading = deg
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        c = QPointF(self.width() / 2, self.height() / 2)
        R = side / 2 - 1
        rw = max(9.0, R * 0.24)  # be day vong la ban
        r = R - rw               # ban kinh chan troi

        # ---- vong la ban, quay theo heading
        p.setPen(Qt.NoPen)
        p.setBrush(RING)
        p.drawEllipse(c, R, R)
        p.save()
        p.translate(c)
        p.rotate(-(self._heading or 0.0))
        p.setFont(_font(rw * 0.7))
        for deg in range(0, 360, 30):
            p.save()
            p.rotate(deg)
            label = {0: "N", 90: "E", 180: "S", 270: "W"}.get(deg)
            if label:
                p.setPen(NORTH if label == "N" else LINE)
                p.drawText(QRectF(-rw, -R, 2 * rw, rw), Qt.AlignCenter, label)
            else:
                p.setPen(QPen(TICK, max(1.0, side / 90)))
                p.drawLine(QPointF(0, -R + rw * 0.25), QPointF(0, -R + rw * 0.65))
            p.restore()
        p.restore()

        # ---- chan troi: xoay theo roll, dich theo pitch
        clip = QPainterPath()
        clip.addEllipse(c, r, r)
        p.save()
        p.setClipPath(clip)
        p.translate(c)
        p.rotate(-math.degrees(self._roll))
        ppd = r / DEG_SPAN
        off = math.degrees(self._pitch) * ppd
        big = r * 3
        p.setPen(Qt.NoPen)
        p.setBrush(SKY)
        p.drawRect(QRectF(-big, -big + off, 2 * big, big))
        p.setBrush(GROUND)
        p.drawRect(QRectF(-big, off, 2 * big, big))
        p.setPen(QPen(LINE, max(1.0, side / 80)))
        p.drawLine(QPointF(-big, off), QPointF(big, off))
        p.setPen(QPen(LINE, max(1.0, side / 140)))
        for deg in (-20, -10, 10, 20):  # thang pitch
            y = off - deg * ppd
            half = r * (0.35 if deg % 20 == 0 else 0.2)
            p.drawLine(QPointF(-half, y), QPointF(half, y))
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(FRAME, max(1.0, side / 100)))
        p.drawEllipse(c, r, r)

        # ---- co dinh: may bay o giua, mui ten huong o dinh vong
        p.setPen(QPen(MARK, max(1.5, side / 45)))
        a, b = r * 0.55, r * 0.18
        p.drawLine(QPointF(c.x() - a, c.y()), QPointF(c.x() - b, c.y()))
        p.drawLine(QPointF(c.x() + b, c.y()), QPointF(c.x() + a, c.y()))
        p.drawPoint(c)
        t = rw * 0.38
        p.setPen(Qt.NoPen)
        p.setBrush(MARK)
        p.drawPolygon(QPolygonF([QPointF(c.x(), c.y() - r + 1),
                                 QPointF(c.x() - t, c.y() - r - t * 1.3),
                                 QPointF(c.x() + t, c.y() - r - t * 1.3)]))

        # ---- so heading, nen toi cho doc duoc tren ca troi lan dat
        box = QRectF(c.x() - r * 0.55, c.y() + r * 0.30, r * 1.1, r * 0.42)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(box, 3, 3)
        p.setPen(LINE)
        p.setFont(_font(r * 0.32))
        p.drawText(box, Qt.AlignCenter, "--" if self._heading is None else f"{self._heading:.0f}°")
