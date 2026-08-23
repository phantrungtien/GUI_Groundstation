"""Quy dao bay 3D — QPainter, phep chieu truc giao, keo chuot de xoay.

Vi sao ve tay chu khong dung QtDataVisualization: Q3DScatter chi ve DIEM roi
rac, khong noi duoc thanh duong — ma quy dao thi cai can doc la duong di, khong
phai dam may diem. Ve tay con chay duoc offscreen nen selfcheck kiem tra duoc,
giong het cach attitude.py va compass.py dang lam.

Truc giao chu khong phoi canh: nhin quy dao bay la de DO — cao bao nhieu, xa bao
nhieu. Phoi canh lam vat o xa nho di, tuc la cung mot 10 met o hai dau duong bay
ve ra hai do dai khac nhau. Duong tha xuong dat moi la thu cho biet do cao, chu
khong phai chieu sau.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from core.i18n import t
from laptop import theme

GRID = QColor("#1e2c38")
GRID_AXIS = QColor(theme.DIVIDER)
DROP = QColor(theme.BORDER)          # duong tha tu quy dao xuong dat
START = QColor(theme.OK)
END = QColor(theme.CRIT)
LABEL = QColor(theme.MUTED)

# Cao thap to mau tu lanh sang nong. Doc do cao bang MAU thi khong phai doi chieu
# voi truc dung — ma o truc giao thi truc dung deu bi phoi canh cua goc nhin lam
# lech, nen mau la thu doc nhanh hon.
COLD = QColor("#35d7ff")
HOT = QColor("#ff9f43")

NICE_STEPS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000)


def _nice_step(extent, target=8):
    """Buoc luoi tron so gan nhat de co khoang `target` o tren be rong `extent`."""
    raw = max(extent, 1.0) / target
    for s in NICE_STEPS:
        if s >= raw:
            return s
    return NICE_STEPS[-1]


class Trajectory3D(QWidget):
    """Nhan (e, n, u) tinh bang met tu LogData.local_track()."""

    MIN_PITCH, MAX_PITCH = 2.0, 89.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self._e, self._n, self._u = [], [], []
        self._yaw = math.radians(35.0)     # goc nhin ban dau: cheo, thay duoc ca ba truc
        self._pitch = math.radians(28.0)
        self._zoom = 1.0
        self._drag = None
        self._note = ""

    # ------------------------------------------------------------------ du lieu

    def set_track(self, e, n, u, note=""):
        """note: chu hien giua khung khi khong co gi de ve (vd: log khong co fix)."""
        self._e, self._n, self._u = list(e), list(n), list(u)
        self._note = note
        self.reset_view()

    def reset_view(self):
        self._yaw, self._pitch, self._zoom = self._auto_yaw(), math.radians(28.0), 1.0
        self.update()

    def _auto_yaw(self):
        """Goc nhin ban dau xoay theo huong bay chinh.

        Goc co dinh la mot cai bay: chuyen bay thang ma huong bay trung voi huong
        nhin thi ca duong bay bep thanh mot vach dung — do that tren
        logs/20260729-104857-sim.tlog, 132 m bay ra ve vai pixel. Phan lon bai bay
        thu deu la duong thang, nen truong hop xau nay khong hiem chut nao.

        Tim truc chinh cua dam diem (tri rieng cua ma tran hiep phuong sai 2x2,
        viet thang ra vi chi co 2x2), roi xoay cho truc do nam NGANG man hinh.
        Cong them 25 do de khong nhin vuong goc hoan toan — vuong goc thi mat cai
        chieu sau lam nguoi ta doc ra "day la khong gian ba chieu".
        """
        base = math.radians(25.0)
        if len(self._e) < 3:
            return base
        k = len(self._e)
        me, mn = sum(self._e) / k, sum(self._n) / k
        cee = cnn = cen = 0.0
        for e, n in zip(self._e, self._n):
            de, dn = e - me, n - mn
            cee += de * de
            cnn += dn * dn
            cen += de * dn
        if cee + cnn < 1e-9:
            return base
        theta = 0.5 * math.atan2(2 * cen, cee - cnn)
        return -theta + base

    # ------------------------------------------------------------------ chuot

    def mousePressEvent(self, ev):
        self._drag = ev.position()

    def mouseReleaseEvent(self, _):
        self._drag = None

    def mouseMoveEvent(self, ev):
        if self._drag is None:
            return
        d = ev.position() - self._drag
        self._drag = ev.position()
        self._yaw += d.x() * 0.01
        self._pitch = max(math.radians(self.MIN_PITCH),
                          min(math.radians(self.MAX_PITCH),
                              self._pitch + d.y() * 0.01))
        self.update()

    def wheelEvent(self, ev):
        self._zoom = max(0.2, min(12.0, self._zoom * (1.0015 ** ev.angleDelta().y())))
        self.update()

    def mouseDoubleClickEvent(self, _):
        self.reset_view()

    # ------------------------------------------------------------------ chieu

    def _project(self, e, n, u, sc, cx, cy):
        """(dong, bac, cao) met -> diem tren man hinh.

        Xoay quanh truc dung mot goc yaw, roi nghieng xuong mot goc pitch.
        pitch = 90 do la nhin thang tu tren xuong (thanh ban do), pitch = 0 la
        nhin ngang (thanh mat cat do cao).
        """
        ca, sa = math.cos(self._yaw), math.sin(self._yaw)
        cp, sp = math.cos(self._pitch), math.sin(self._pitch)
        xe = e * ca - n * sa
        yn = e * sa + n * ca
        return QPointF(cx + xe * sc, cy - (u * cp + yn * sp) * sc)

    def _scale(self, w, h):
        """He so met -> pixel sao cho ca quy dao lot khung, co le 12%."""
        if not self._e:
            return 1.0
        span = max(max(self._e) - min(self._e),
                   max(self._n) - min(self._n),
                   (max(self._u) - min(self._u)) * 1.6, 4.0)
        return (min(w, h) * 0.76 / span) * self._zoom

    # ------------------------------------------------------------------ ve

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(theme.SURFACE))

        if len(self._e) < 2:
            p.setPen(LABEL)
            p.setFont(QFont("", 10))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter,
                       self._note or t("an.no_track"))
            return

        # Tam khung dat o giua quy dao, khong phai goc toa do: chuyen bay lech han
        # sang mot ben thi goc toa do nam ngoai man hinh.
        mid_e = (max(self._e) + min(self._e)) / 2
        mid_n = (max(self._n) + min(self._n)) / 2
        sc = self._scale(w, h)
        cx, cy = w / 2, h / 2 + h * 0.12

        def pr(e, n, u):
            return self._project(e - mid_e, n - mid_n, u, sc, cx, cy)

        self._draw_grid(p, pr, sc)
        self._draw_drops(p, pr)
        self._draw_path(p, pr)
        self._draw_ends(p, pr)
        self._draw_legend(p, w, h, sc)

    def _draw_grid(self, p, pr, sc):
        """Luoi bam theo VUNG DU LIEU, khong phai mot tam vuong co dinh.

        Truoc day luoi ke +-10 o quanh tam bat ke duong bay rong bao nhieu: mot
        chuyen bay 10 m nam lot thom trong mot tam luoi 200 m, va hai duong truc
        goc toa do thi cat ngang man hinh nhu hai vet xuoc.
        """
        span = max(max(self._e) - min(self._e), max(self._n) - min(self._n), 4.0)
        step = _nice_step(span)
        pad = step  # them mot o moi ben cho duong bay khong dinh sat mep luoi
        e_lo = math.floor((min(self._e) - pad) / step) * step
        e_hi = math.ceil((max(self._e) + pad) / step) * step
        n_lo = math.floor((min(self._n) - pad) / step) * step
        n_hi = math.ceil((max(self._n) + pad) / step) * step

        def lines(lo, hi):
            k = lo
            while k <= hi + step / 2:
                yield k
                k += step

        for e in lines(e_lo, e_hi):
            # Truc goc toa do (diem cat canh) chi to dam khi no nam trong luoi.
            axis = abs(e) < step / 2 and n_lo <= 0 <= n_hi
            p.setPen(QPen(GRID_AXIS if axis else GRID, 1.4 if axis else 1))
            p.drawLine(pr(e, n_lo, 0), pr(e, n_hi, 0))
        for n in lines(n_lo, n_hi):
            axis = abs(n) < step / 2 and e_lo <= 0 <= e_hi
            p.setPen(QPen(GRID_AXIS if axis else GRID, 1.4 if axis else 1))
            p.drawLine(pr(e_lo, n, 0), pr(e_hi, n, 0))

        # Mui bac: khong co no thi xoay vai vong la mat phuong huong.
        mid_e = (e_lo + e_hi) / 2
        tip = pr(mid_e, n_hi + step * 0.9, 0)
        base = pr(mid_e, n_hi + step * 0.2, 0)
        p.setPen(QPen(GRID_AXIS, 1.6))
        p.drawLine(base, tip)
        p.setPen(LABEL)
        p.setFont(QFont("", 8, QFont.Bold))
        p.drawText(QRectF(tip.x() - 10, tip.y() - 16, 20, 14), Qt.AlignCenter, "N")

    def _draw_drops(self, p, pr):
        """Duong tha thang xuong dat — thu DUY NHAT lam nguoi ta doc ra do cao.

        Khong co no thi mot duong cong trong khong gian nhin y het mot duong cong
        nam bep tren mat dat.
        """
        n = len(self._e)
        every = max(1, n // 60)  # ~60 duong, day hon thi thanh mot mang den
        p.setPen(QPen(DROP, 1))
        for i in range(0, n, every):
            if self._u[i] <= 0.05:
                continue
            p.drawLine(pr(self._e[i], self._n[i], self._u[i]),
                       pr(self._e[i], self._n[i], 0))

    def _draw_path(self, p, pr):
        lo, hi = min(self._u), max(self._u)
        rng = max(hi - lo, 0.1)
        # Bong do xuong mat dat truoc, roi moi ve duong bay de no nam tren.
        p.setPen(QPen(QColor(theme.BORDER).darker(120), 1, Qt.DashLine))
        p.drawPolyline(QPolygonF([pr(e, n, 0) for e, n in zip(self._e, self._n)]))

        for i in range(len(self._e) - 1):
            k = (self._u[i] - lo) / rng
            p.setPen(QPen(QColor(
                int(COLD.red() + (HOT.red() - COLD.red()) * k),
                int(COLD.green() + (HOT.green() - COLD.green()) * k),
                int(COLD.blue() + (HOT.blue() - COLD.blue()) * k)), 2))
            p.drawLine(pr(self._e[i], self._n[i], self._u[i]),
                       pr(self._e[i + 1], self._n[i + 1], self._u[i + 1]))

    def _draw_ends(self, p, pr):
        for idx, col in ((0, START), (len(self._e) - 1, END)):
            c = pr(self._e[idx], self._n[idx], self._u[idx])
            p.setPen(QPen(col, 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, 5, 5)
            p.drawLine(c, pr(self._e[idx], self._n[idx], 0))

    def _draw_legend(self, p, w, h, sc):
        p.setFont(QFont("", 8))
        p.setPen(LABEL)
        span = max(max(self._e) - min(self._e), max(self._n) - min(self._n), 4.0)
        step = _nice_step(span)
        px = step * sc
        y = h - 14
        p.drawLine(QPointF(12, y), QPointF(12 + px, y))
        p.drawLine(QPointF(12, y - 3), QPointF(12, y + 3))
        p.drawLine(QPointF(12 + px, y - 3), QPointF(12 + px, y + 3))
        p.drawText(QRectF(12, y - 20, px + 60, 14), Qt.AlignLeft, f"{step:g} m")
        p.drawText(QRectF(w - 190, h - 20, 178, 14), Qt.AlignRight,
                   t("an.alt_range", lo=min(self._u), hi=max(self._u)))
