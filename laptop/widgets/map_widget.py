"""Map nen — tile OSM offline + vet duong bay, ve bang QPainter.

Chon tile offline chu khong nhung Leaflet qua QtWebEngine: laptop ngoai bai bay
khong co internet, va QtWebEngine keo theo ca Chromium.

Tile nam o assets/tiles/{z}/{x}/{y}.png (chuan slippy map, giong moi nguon OSM).
Thieu tile thi ve luoi toa do — khong bao gio de man hinh trang roi de nguoi
dung tu doan la mat ban do hay mat vi tri.
"""

import hashlib
import math
import queue
import threading
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

TILE = 256
ROOT = Path(__file__).resolve().parent.parent.parent
TILE_DIR = ROOT / "assets" / "tiles"

# Tai bu tile khi may co mang. Offline khong doi gi: thieu tile van ve tu muc
# gan nhat nhu cu, chi la khong co ai bu them. Dat False de tat han (vi du bay
# bang hotspot dien thoai, khong muon ton dung luong).
ONLINE_TILES = True
# Xin toi z21. Cho nao co anh that toi do thi duoc net that; cho nao het anh thi
# may chu tra ve MOT tam "khong co du lieu" giong het nhau cho moi tile — do la
# ly do co JUNK_REPEAT ben duoi. Do that o TP.HCM: Esri va Bing deu het anh goc
# o z19, z20-23 chi la mot anh 2.5 KB lap lai.
MAX_ONLINE_Z = 21
JUNK_REPEAT = 4  # cung mot noi dung anh lap lai bay nhieu lan -> anh bao "khong co"

# Dung khi assets/tiles/SOURCE.txt chua ghi URL (chua chay fetch_tiles.py bao gio,
# hoac ban cu ghi de mat dong URL). Co mac dinh thi tinh nang khong tu tat im lang.
DEFAULT_TILE_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services"
                    "/World_Imagery/MapServer/tile/{z}/{y}/{x}")
FETCH_PAUSE = 0.1  # giay giua hai lan tai — lich su voi may chu
OFFLINE_AFTER = 5  # bay nhieu lan lien tiep thi coi nhu mat mang, nghi mot lat
OFFLINE_NAP = 30.0

GRID = QColor(45, 52, 58)
BG = QColor(26, 29, 32)
TRAIL = QColor(52, 152, 219)
DRONE = QColor(46, 204, 113)
HOME = QColor(241, 196, 15)
TEXT = QColor(130, 140, 150)


def deg2num(lat, lon, z):
    """lat/lon -> toa do tile (so thuc, phan le la vi tri trong tile)."""
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2.0**z
    x = (lon + 180.0) / 360.0 * n
    r = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * n
    return x, y


def pick_tile_zoom(view_zoom, available, up=8, down=2):
    """Muc zoom tile de ve khung nhin o `view_zoom`. None = khong co gi de ve.

    `available` phai la cac muc CO TILE NGAY TAI DAY, khong phai cac muc ton tai
    o dau do tren the gioi — xem MapWidget._levels_here().

    `up`: phong to toi da may bac. Rong tay (8) vi day la duong cuu canh: dung
    giua TP.HCM ma chi co tile z10 thi mot mang mo con hon man hinh den.
    `down`: thu nho toi da may bac — moi bac la gap bon so tile phai ve, thu nho
    qua thi mot tile con vai pixel ma phai ve hang tram cai, khong dang.
    """
    if not available:
        return None
    tz = min(available, key=lambda z: abs(z - view_zoom))
    if tz - view_zoom > down or view_zoom - tz > up:
        return None
    return tz


def num2deg(x, y, z):
    n = 2.0**z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


class TileFetcher(QObject):
    """Tai bu tile con thieu, chay o thread rieng.

    Thread thuong (daemon) chu khong QThread: MapWidget co the bi huy ma khong qua
    closeEvent (tab dong, cua so con bi thay), va "QThread: Destroyed while thread
    is still running" la abort ca tien trinh — mot GCS khong duoc chet vi cai
    thread tai ban do. Daemon thread thi chet theo tien trinh, khong keu ca.

    Console MAVProxy net hon vi no tai tile tu internet ngay luc ban cuon. Lop nay
    lam dung the, nhung KHONG danh doi kha nang offline: tile tai ve nam lai trong
    assets/tiles nhu tile prefetch, va mat mang thi ban do van chay y nhu truoc.

    Khong cham widget Qt tu day — chi phat signal `fetched`, main thread ve lai.
    """

    fetched = Signal()

    def __init__(self, url_tpl, parent=None):
        super().__init__(parent)
        self.url_tpl = url_tpl
        self.q = queue.Queue()
        self._asked = set()   # da xep hang, khoi hoi lai
        self._dead = set()    # may chu bao khong co — dung xin mai
        self._running = True
        self._fails = 0
        self._seen = {}       # md5 -> [(duong dan, key)] da luu (phat hien anh rac)
        self._junk = set()    # md5 cua anh "khong co du lieu"
        # Muc sau nhat con anh THAT o nguon nay. Bat dau lac quan roi tu lui khi
        # gap anh rac — moi noi mot khac, thanh pho lon thuong sau hon vung que.
        self.max_ok_z = MAX_ONLINE_Z

    def want(self, z, x, y):
        """Goi tu main thread trong luc ve. Phai re, va khong duoc chan."""
        key = (z, x, y)
        if z > self.max_ok_z or key in self._asked or key in self._dead:
            return
        if self.q.qsize() > 200:  # keo ban do nhanh qua thi bo bot, khong don dong
            return
        self._asked.add(key)
        self.q.put(key)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            try:
                z, x, y = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self._fails >= OFFLINE_AFTER:
                # Nhieu kha nang dang o ngoai bai bay: nghi mot lat roi thu lai
                # dung mot cai, khong quay vong tao rac mang.
                self._asked.clear()
                time.sleep(OFFLINE_NAP)
                self._fails = 0
                continue
            if self._get(z, x, y):
                self.fetched.emit()
                time.sleep(FETCH_PAUSE)

    def _get(self, z, x, y):
        path = TILE_DIR / str(z) / str(x) / f"{y}.png"
        if path.exists():
            return False
        req = urllib.request.Request(
            self.url_tpl.format(z=z, x=x, y=y),
            headers={"User-Agent": "GUI_NATIVE-GCS/1.0 (ground control station)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                if not r.headers.get("Content-Type", "").startswith("image/"):
                    self._dead.add((z, x, y))
                    return False
                data = r.read()
        except Exception:
            self._fails += 1
            self._asked.discard((z, x, y))  # cho phep thu lai khi co mang
            return False
        self._fails = 0
        if not self._keep(data, path, z, x, y):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return True

    def _keep(self, data, path, z, x, y):
        """Anh nay co phai ban do that khong, hay la tam "khong co du lieu"?

        Xin sau hon muc anh goc thi may chu KHONG bao loi — no tra ve HTTP 200 kem
        mot tam anh bao trong, giong het nhau cho moi tile. Khong loc thi dia day
        hang nghin ban sao cua cung mot tam, va ban do trong nhu da tai xong.

        Danh doi: mot vung dong nhat that (mat bien, rung kin) cung co the trung
        byte va bi bo — nhung bo no thi ban do tut ve muc zoom nong hon, trong y het.
        """
        h = hashlib.md5(data).hexdigest()
        if h in self._junk:
            # Da biet tam nay la anh trong: lui muc ngay tu lan dau gap o do sau
            # moi, khong doi du JUNK_REPEAT lan nua cho tung muc zoom.
            self.max_ok_z = min(self.max_ok_z, z - 1)
            self._dead.add((z, x, y))
            return False
        seen = self._seen.setdefault(h, [])
        if len(seen) + 1 >= JUNK_REPEAT:
            self._junk.add(h)
            # Het anh that o muc nay -> lui xuong, de lan sau xin muc con anh that
            # thay vi xin mai mot tam trong.
            self.max_ok_z = min(self.max_ok_z, z - 1)
            for p, key in self._seen.pop(h, ()):  # don ca nhung cai da lo luu
                p.unlink(missing_ok=True)
                self._dead.add(key)
            self._dead.add((z, x, y))
            return False
        seen.append((path, (z, x, y)))
        return True


class MapWidget(QWidget):
    MAX_TRAIL = 3000  # ~15 phut o 3 Hz; chuyen bay dai khong an het RAM

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom = 16
        # Tam man hinh luc chua co du lieu: dat o bai bay (DH Cong nghiep TP.HCM),
        # trung voi home mac dinh cua SITL. Co goi dau tien la no bam theo drone.
        self.center = (10.8221589, 106.6868454)
        self.follow = True  # bam theo drone; pan tay thi tat
        self.pos = None  # (lat, lon) hien tai
        self.home = None
        self.trail = []
        self._drag = None
        self._cache = {}
        self._zooms = None  # cac muc zoom co tile; doc tu dia o available_zooms()
        # tools/fetch_tiles.py ghi vao day: dong 1 ten nguon (Esri/OpenTopoMap doi
        # ghi cong), dong 2 URL template de tai bu tile thieu khi co mang.
        src = TILE_DIR / "SOURCE.txt"
        lines = src.read_text().splitlines() if src.exists() else []
        self.credit = lines[0].strip() if lines else ""
        url = lines[1].strip() if len(lines) > 1 else DEFAULT_TILE_URL
        self.fetcher = None
        if ONLINE_TILES and url:
            self.fetcher = TileFetcher(url, self)
            self.fetcher.fetched.connect(self._on_fetched)
            self.fetcher.start()
        self.setMouseTracking(True)

    def _on_fetched(self):
        """Chay o main thread (qua signal). Tile moi ve -> co the co muc zoom moi."""
        self._zooms = None
        self.update()

    def closeEvent(self, e):
        if self.fetcher:
            self.fetcher.stop()
        super().closeEvent(e)

    # --- du lieu ------------------------------------------------------

    def set_position(self, lat, lon):
        if lat is None or lon is None:
            return
        self.pos = (lat, lon)
        if not self.trail or _far(self.trail[-1], (lat, lon)):
            self.trail.append((lat, lon))
            del self.trail[: max(0, len(self.trail) - self.MAX_TRAIL)]
        if self.follow:
            self.center = (lat, lon)
        self.update()

    def set_home(self, lat, lon):
        if lat is not None and lon is not None:
            self.home = (lat, lon)
            self.update()

    def clear_trail(self):
        self.trail.clear()
        self.update()

    # --- tuong tac ----------------------------------------------------

    def wheelEvent(self, e):
        # Tran 21 chu khong 19: co tile z17 la da xem duoc toi z20 (phong 3 bac).
        # Qua tran thi pick_tile_zoom tra None va man hinh ve luoi — khong ket.
        self.zoom = max(1, min(21, self.zoom + (1 if e.angleDelta().y() > 0 else -1)))
        self._zooms = None  # co the vua co them muc zoom moi tren dia
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.position()

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        d = e.position() - self._drag
        self._drag = e.position()
        self.follow = False  # keo tay la thoi bam theo drone
        cx, cy = deg2num(*self.center, self.zoom)
        self.center = num2deg(cx - d.x() / TILE, cy - d.y() / TILE, self.zoom)
        self.update()

    def mouseReleaseEvent(self, _):
        self._drag = None

    def mouseDoubleClickEvent(self, _):
        self.follow = True
        if self.pos:
            self.center = self.pos
        self.update()

    def latlon_at(self, point):
        """Diem tren widget -> (lat, lon). Dung cho click-to-goto."""
        cx, cy = deg2num(*self.center, self.zoom)
        x = cx + (point.x() - self.width() / 2) / TILE
        y = cy + (point.y() - self.height() / 2) / TILE
        return num2deg(x, y, self.zoom)

    def _to_px(self, lat, lon, cx, cy):
        x, y = deg2num(lat, lon, self.zoom)
        return QPoint(
            int((x - cx) * TILE + self.width() / 2),
            int((y - cy) * TILE + self.height() / 2),
        )

    # --- ve -----------------------------------------------------------

    def _tile(self, z, x, y):
        """Doc tile tu dia. Co gang thi cache anh, KHONG cache chuyen "thieu".

        Nho danh sach thieu thi tile do tools/fetch_tiles.py tai ve trong luc app
        dang chay se khong bao gio duoc nhin thay: man hinh cu mo mai cho toi khi
        khoi dong lai. Mot lan stat() cho moi tile moi lan ve la re — _levels_here()
        dang stat chung do rong hon the.
        """
        key = (z, x, y)
        if key in self._cache:
            return self._cache[key]
        path = TILE_DIR / str(z) / str(x) / f"{y}.png"
        if not path.exists():
            return None
        pix = QPixmap(str(path))
        if len(self._cache) > 400:
            self._cache.clear()
        self._cache[key] = pix
        return pix

    def available_zooms(self):
        """Cac muc zoom co tile tren dia. Doc mot lan roi nho."""
        if self._zooms is None:
            self._zooms = sorted(
                int(d.name) for d in TILE_DIR.glob("*") if d.is_dir() and d.name.isdigit()
            )
        return self._zooms

    def _levels_here(self):
        """Cac muc zoom co tile NGAY TAI TAM MAN HINH.

        Thu muc z16 ton tai khong co nghia la co tile o cho dang xem: tai z13-17
        cho bai bay Canberra roi bay o TP.HCM thi widget tuong minh co tile z16 va
        ve luoi giua thanh pho, trong khi tile z7-10 phu cho do van nam san tren
        dia. Phai hoi dia that, khong suy tu ten thu muc.
        """
        out = []
        for z in self.available_zooms():
            x, y = deg2num(*self.center, z)
            if (TILE_DIR / str(z) / str(int(x)) / f"{int(y)}.png").exists():
                out.append(z)
        return out

    def _request_viewport(self):
        """Xin tile o muc zoom dang xem — hoac muc sau nhat con anh that.

        Dang ve tu z13 phong to khong co nghia la thoi muon z16: xin z16 ve thi lan
        ve sau la net. Nhung xem o z21 trong khi nguon het anh o z19 thi phai xin
        z19, khong xin mai z21 de nhan ve mot tam trong (xem TileFetcher._keep).
        """
        rz = min(self.zoom, self.fetcher.max_ok_z)
        cx, cy = deg2num(*self.center, rz)
        w, h = self.width(), self.height()
        for tx in range(int(cx - w / (2 * TILE)) - 1, int(cx + w / (2 * TILE)) + 2):
            for ty in range(int(cy - h / (2 * TILE)) - 1, int(cy + h / (2 * TILE)) + 2):
                if not (TILE_DIR / str(rz) / str(tx) / f"{ty}.png").exists():
                    self.fetcher.want(rz, tx, ty)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), BG)
        cx, cy = deg2num(*self.center, self.zoom)
        w, h = self.width(), self.height()
        if self.fetcher:
            self._request_viewport()

        # Zoom xem va zoom tile la hai thu khac nhau. Tai tile 13-17 ma cuon toi
        # z19 thi truoc day man hinh trong tron; gio lay muc gan nhat co tren dia
        # roi phong ti le. Mo con hon mat ban do giua luc bay.
        tz = pick_tile_zoom(self.zoom, self._levels_here())
        drawn = 0
        if tz is not None:
            scale = 2.0 ** (self.zoom - tz)   # mot tile tz chiem bao nhieu tile view
            span = TILE * scale               # canh tile tinh bang pixel man hinh
            # doi khung nhin (dang toa do zoom xem) sang chi so tile o muc tz
            x0 = math.floor((cx - w / (2 * TILE)) / scale)
            x1 = math.floor((cx + w / (2 * TILE)) / scale)
            y0 = math.floor((cy - h / (2 * TILE)) / scale)
            y1 = math.floor((cy + h / (2 * TILE)) / scale)
            for tx in range(x0, x1 + 1):
                for ty in range(y0, y1 + 1):
                    px = int((tx * scale - cx) * TILE + w / 2)
                    py = int((ty * scale - cy) * TILE + h / 2)
                    pix = self._tile(tz, tx, ty)
                    if pix is not None and not pix.isNull():
                        p.drawPixmap(QRect(px, py, math.ceil(span), math.ceil(span)), pix)
                        drawn += 1
                    else:
                        p.setPen(QPen(GRID, 1))
                        p.drawRect(QRect(px, py, int(span), int(span)))
        else:
            for tx in range(int(cx - w / (2 * TILE)) - 1, int(cx + w / (2 * TILE)) + 2):
                for ty in range(int(cy - h / (2 * TILE)) - 1, int(cy + h / (2 * TILE)) + 2):
                    p.setPen(QPen(GRID, 1))
                    p.drawRect(QRect(int((tx - cx) * TILE + w / 2),
                                     int((ty - cy) * TILE + h / 2), TILE, TILE))

        if drawn == 0:
            p.setPen(TEXT)
            p.setFont(QFont("", 9))
            p.drawText(
                self.rect().adjusted(0, 8, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
                f"khong co tile offline cho z{self.zoom} — luoi toa do thay the\n"
                f"(dat tile vao assets/tiles/{{z}}/{{x}}/{{y}}.png)",
            )
        elif self.zoom - tz > 3:
            # Phong to qua 3 bac la mang mau nhoe. Van ve — co con hon den — nhung
            # phai noi ro, khong de nguoi bay tuong vung nay dung la mot bai co trong.
            p.setFont(QFont("", 9))
            warn = (f"anh tho z{tz} phong to {2 ** (self.zoom - tz)} lan — "
                    f"chua tai chi tiet cho vung nay")
            box = QRect(0, 4, w, 18)
            p.fillRect(box, QColor(0, 0, 0, 150))
            p.setPen(QColor(230, 176, 100))
            p.drawText(box, Qt.AlignCenter, warn)

        if self.home:
            hp = self._to_px(*self.home, cx, cy)
            p.setPen(QPen(HOME, 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(hp, 7, 7)
            p.drawLine(hp.x() - 10, hp.y(), hp.x() + 10, hp.y())
            p.drawLine(hp.x(), hp.y() - 10, hp.x(), hp.y() + 10)

        if len(self.trail) > 1:
            p.setPen(QPen(TRAIL, 2))
            pts = [self._to_px(a, b, cx, cy) for a, b in self.trail[-800:]]
            p.drawPolyline(pts)

        if self.pos:
            dp = self._to_px(*self.pos, cx, cy)
            p.setPen(QPen(QColor(10, 10, 10), 2))
            p.setBrush(DRONE)
            p.drawEllipse(dp, 6, 6)

        # Chu de tren anh ve tinh thi chim han. Ke mot dai toi mo phia sau — re hon
        # ve vien chu, va ngoai nang doc duoc that.
        p.setFont(QFont("", 8))
        note = f"z{self.zoom}  {self.center[0]:.5f}, {self.center[1]:.5f}"
        if not self.follow:
            note += "  ·  nhay doi de bam lai theo drone"
        if self.credit:
            note += f"  ·  {self.credit}"
        strip = QRect(0, self.height() - 16, self.width(), 16)
        p.fillRect(strip, QColor(0, 0, 0, 140))
        p.setPen(QColor(200, 208, 214))
        p.drawText(strip.adjusted(6, 0, -6, 0), Qt.AlignLeft | Qt.AlignVCenter, note)


def _far(a, b, eps=1e-6):
    return abs(a[0] - b[0]) > eps or abs(a[1] - b[1]) > eps
