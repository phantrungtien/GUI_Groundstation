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

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget

from laptop import theme

# Tran so waypoint la mot con so cua GIAO THUC (bang thong SiK), khong phai cua
# ban do — lay tu adapter chu khong go lai o day.
from core.adapters.sik import WP_MAX

TILE = 256
from core.field import haversine_m
from core.i18n import t

ROOT = Path(__file__).resolve().parent.parent.parent
TILE_DIR = ROOT / "assets" / "tiles"

# Tai bu tile khi may co mang. Offline khong doi gi: thieu tile van ve tu muc
# gan nhat nhu cu, chi la khong co ai bu them. Dat False de tat han (vi du bay
# bang hotspot dien thoai, khong muon ton dung luong).
ONLINE_TILES = True
# Xin toi z21. Cho nao co anh that toi do thi duoc net that; cho nao het anh thi
# may chu tra ve MOT tam "khong co du lieu" giong het nhau cho moi tile — do la
# ly do co JUNK_REPEAT ben duoi.
#
# Do that tai IUH (10.8221589, 106.6868454), ba tile khac vi tri moi muc zoom:
#   Esri   z19 22/15/18 KB · z20 va z21 deu 2521 byte, CUNG md5 -> het anh goc
#   Google z19 15/12/12 KB · z20 11/8.6/8.8 KB · z21 7.6/6.1/4.8 KB -> anh that
# Tuc tran cua Esri la 29 cm/pixel, Google xuong toi 7.3 cm/pixel. Bing do truoc
# day cung het anh o z19 nhu Esri.
#
# Nen JUNK_REPEAT van phai giu du da doi sang Google: no la cai bat "may chu het
# anh" noi chung, khong rieng nguon nao.
MAX_ONLINE_Z = 21
JUNK_REPEAT = 4  # cung mot noi dung anh lap lai bay nhieu lan -> anh bao "khong co"

# Dung khi assets/tiles/SOURCE.txt chua ghi URL (chua chay fetch_tiles.py bao gio,
# hoac ban cu ghi de mat dong URL). Co mac dinh thi tinh nang khong tu tat im lang.
DEFAULT_TILE_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services"
                    "/World_Imagery/MapServer/tile/{z}/{y}/{x}")
FETCH_PAUSE = 0.1  # giay giua hai lan tai — lich su voi may chu
OFFLINE_AFTER = 5  # bay nhieu lan lien tiep thi coi nhu mat mang, nghi mot lat
OFFLINE_NAP = 30.0

GRID = QColor("#1e2c38")
BG = QColor(theme.BG_DEEP)
TRAIL = QColor(theme.INFO)
DRONE = QColor(theme.OK)
# Tam giac nhon chi huong mui, kieu QGroundControl. Toa do o he "mui len tren"
# (truc y man hinh huong xuong, nen mui la y am); ve xong moi xoay theo heading.
# Dai hon rong: cai lam nguoi ta doc ra huong tu mot cai liec la ti le do, khong
# phai kich thuoc.
DRONE_SHAPE = ((0, -13), (7, 8), (-7, 8))
HOME = QColor(theme.WARN)
TEXT = QColor(theme.MUTED)
FENCE_IN = QColor("#e8913c")       # vung duoc phep bay
FENCE_OUT = QColor(theme.CRIT)     # vung cam vao
# Rao dang TAT ve dut net, nhung phai SANG: xam toi thi chim han vao anh ve tinh
# va "rao dang tat" nhin y het "khong co rao" — hai chuyen rat khac nhau.
FENCE_OFF = QColor("#d6e0e8")
# Duong bay da nap. Mau phai khac han vet bay (xanh duong): mot cai la KE HOACH,
# cai kia la thu drone DA bay qua — nhin nham hai thu nay la hieu sai man hinh.
WP_LINE = QColor("#a96fd6")
WP_NOW = QColor("#ffffff")  # waypoint dang bay toi
# Duong bay DANG DAT tren man hinh, chua nap len FC. Cung ho mau voi duong bay
# that (cung la mot ke hoach) nhung nhat va dut net: dat xong ma tuong da nap
# roi la cat canh voi mot nhiem vu cu nam trong FC.
WP_DRAFT = QColor("#d0a8eb")
DRAFT_ALT = 20.0  # met so voi home, cho waypoint dat bang chuot. Doi o menu ban do.

# MAV_CMD_NAV_FENCE_* — dinh da giac va tam vong tron
VERTEX_IN, VERTEX_OUT, CIRCLE_IN, CIRCLE_OUT = 5001, 5002, 5003, 5004
# Bit cua FENCE_TYPE. FC la nguon su that DUY NHAT quyet dinh rao nao dang chan:
# co FENCE_RADIUS trong tham so KHONG co nghia la rao tron dang bat. Ve hay do mot
# rao ma FC khong chan la noi doi ve phia nguy hiem — nguoi bay tuong minh duoc
# chan lai o do.
FENCE_TYPE_ALT_MAX = 1   # tran do cao
FENCE_TYPE_CIRCLE = 2    # vong tron quanh home, ban kinh FENCE_RADIUS
FENCE_TYPE_POLYGON = 4   # moi hinh tai tu nhiem vu FENCE (da giac VA vong tron roi)
FENCE_TYPE_ALT_MIN = 8   # san do cao (firmware moi)


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


def meters_per_px(lat, zoom):
    """Do phan giai Web Mercator o vi do nay. Doi ban kinh rao (met) sang pixel."""
    return 156543.03392804097 * math.cos(math.radians(lat)) / 2.0**zoom


def _seg_dist_m(p, a, b):
    """Khoang cach tu diem p (lat, lon) toi doan thang a-b, don vi met.

    Chieu sang mat phang met quanh CHINH p roi tinh 2D: o vai tram met thi sai so
    cua phep chieu nho hon nhieu so voi sai so cua GPS, va cong thuc phang thi doc
    duoc. Haversine khong dung thang duoc vi diem gan nhat nam GIUA doan, khong
    phai o mot trong hai dinh.
    """
    mlon = 111320.0 * math.cos(math.radians(p[0]))
    ax, ay = (a[1] - p[1]) * mlon, (a[0] - p[0]) * 110540.0
    bx, by = (b[1] - p[1]) * mlon, (b[0] - p[0]) * 110540.0
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(ax, ay)
    # t = vi tri hinh chieu tren doan, kep ve [0, 1] de khong ra ngoai hai dinh
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    return math.hypot(ax + t * dx, ay + t * dy)


def fence_shapes(items):
    """Muc nhiem vu FENCE -> [("poly", cam?, [(lat, lon), ...])] va [("circle", cam?, tam, r)].

    Cac dinh cua mot da giac nam lien tiep nhau trong danh sach, va `param1` cua
    moi dinh la TONG so dinh cua da giac do — do la duong duy nhat biet hai da
    giac ke nhau ket thuc/bat dau o dau. Vong tron thi param1 la ban kinh (met).
    """
    out = []
    cur, cur_cmd = [], None

    def flush():
        nonlocal cur, cur_cmd
        if len(cur) >= 3:  # duoi 3 dinh khong thanh hinh — bo, khong ve nua voi
            out.append(("poly", cur_cmd == VERTEX_OUT, cur))
        cur, cur_cmd = [], None

    for cmd, p1, lat, lon in items:
        if cmd in (CIRCLE_IN, CIRCLE_OUT):
            flush()
            out.append(("circle", cmd == CIRCLE_OUT, (lat, lon), p1))
        elif cmd in (VERTEX_IN, VERTEX_OUT):
            if cmd != cur_cmd:
                flush()
            cur_cmd = cmd
            cur.append((lat, lon))
            if len(cur) >= int(p1 or 0):
                flush()
        else:
            flush()  # muc la khong phai rao: cat da giac dang do
    flush()
    return out


def wp_points(items):
    """Muc nhiem vu -> [(seq, lat, lon, alt)] ve duoc len ban do.

    Bo muc lat/lon = 0: mot nua so lenh trong nhiem vu khong mang toa do
    (`DO_CHANGE_SPEED`, `CONDITION_DELAY`, va `NAV_TAKEOFF` thuong de trong) —
    ve chung thi duong bay keo mot net thang ra dao Null (0, 0) giua Dai Tay
    Duong. Giu nguyen so `seq` cua FC lam nhan: do la con so `MISSION_CURRENT`
    dung de noi "dang bay toi diem nao", hai ben phai goi cung mot ten.
    """
    return [(seq, lat, lon, alt) for seq, _cmd, lat, lon, alt in items if lat or lon]


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
                # stop() chi ha co; luc no duoc ha thi thread nay co the dang nam
                # trong _get() — urlopen cho toi 10 giay. Trong 10 giay do widget
                # bi huy la `fetched.emit()` ban vao mot QObject da chet: PySide
                # nem RuntimeError trong thread phu, va tien trinh do CORE DUMP,
                # dung cai ma chu thich dau lop the la se khong xay ra.
                #
                # Bat duoc luc chay selfcheck 27/08/2026: mot phep thu dai o cuoi
                # bo cho event loop chay ~2 giay, du de mot TileFetcher mo coi tu
                # phep thu truoc ban len va giet ca bo kiem tra (exit 139).
                if not self._running:
                    return
                try:
                    self.fetched.emit()
                except RuntimeError:
                    return  # widget da bi huy — thread nay khong con viec gi
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
        self.heading = None  # do, 0 = bac. None = chua biet -> ve hinh tron
        self.home = None
        self.home_from_fc = False  # True = HOME_POSITION that tu FC, khong phai doan
        self.alt_rel = None  # do cao so voi home, de do khoang cach toi tran rao
        self.fence = {}  # tham so FENCE_* + "items" (cac dinh da giac), xem set_fence
        self.wp = {}  # "items" (duong bay) + "seq"/"total", xem set_wp
        self.draft = []  # [(lat, lon, alt)] dang dat bang chuot, chua nap len FC
        self.wp_alt = DRAFT_ALT
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

    def set_home(self, lat, lon, from_fc=False):
        """`from_fc` = da nhan HOME_POSITION that tu FC, khong phai doan.

        Phai phan biet, vi hai cai nay ve ra CUNG MOT dau X: khi chua co
        HOME_POSITION, tab Bay lay tam diem dinh vi dau tien lam home. Nguoi bay
        nhin thay dau X va tin la home da dat — trong khi RTL se bay ve home THAT
        cua FC, o cho khac. Mot dau X sai cho con te hon khong co dau X nao, va
        do dung la thu muc D.6 bat kiem ("Home da dat, DUNG CHO DUNG").
        """
        if lat is not None and lon is not None:
            self.home = (lat, lon)
            self.home_from_fc = from_fc
            self.update()

    def set_fence(self, data):
        """Gop tung manh mot: tham so FENCE_* ve roi rac, danh sach dinh ve sau.

        `None` = xoa han (dung khi doi drone). Xem core/adapters/sik.py: _fence_ask.
        """
        if data is None:
            self.fence = {}
        else:
            self.fence.update(data)
        self.update()

    def set_wp(self, data):
        """Duong bay da nap tren FC. Gop tung manh nhu set_fence.

        Hai nhip khac han nhau do ve cung mot cho: danh sach diem ve dung mot
        lan sau khi tai xong (MISSION_ITEM_INT), con `seq` — diem dang bay toi —
        ve deu deu suot chuyen (MISSION_CURRENT). Xem core/adapters/sik.py.
        """
        if data is None:
            self.wp = {}
        else:
            self.wp.update(data)
        self.update()

    def add_draft(self, lat, lon, alt=None):
        """Dat them mot waypoint. Tra ve False khi da cham tran WP_MAX."""
        if len(self.draft) >= WP_MAX:
            return False
        self.draft.append((lat, lon, self.wp_alt if alt is None else alt))
        self.update()
        return True

    def drop_draft(self, all_of_them=False):
        """Bo diem cuoi, hoac xoa het."""
        if all_of_them:
            self.draft.clear()
        elif self.draft:
            self.draft.pop()
        self.update()

    def reset(self):
        """Ngat ket noi: xoa vet bay, home, rao va duong bay cua chuyen truoc.

        Giu lai la ve du lieu cu de len drone moi — cai dau X va vong rao van
        nam do trong khi chung khong con dung nua.
        """
        self.trail.clear()
        self.home = None
        self.fence = {}
        self.wp = {}
        # `draft` KHONG xoa: no la thu nguoi bay dang soan, khong phai du lieu cua
        # drone cu. Rot ket noi giua chung ma mat 12 diem vua dat la mat cong that.
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

    def _draw_fence(self, p, cx, cy):
        """Rao: vong tron quanh HOME (FENCE_RADIUS) va cac da giac tai tu FC.

        FENCE_ENABLE = 0 -> ve xam, dut net. Rao co dinh nghia nhung dang TAT ma
        ve nhu dang bat la noi doi ve phia nguy hiem: nguoi bay tuong minh duoc
        chan lai o do.
        """
        f = self.fence
        on = bool(f.get("FENCE_ENABLE", 0))
        ftype = int(f.get("FENCE_TYPE", 0) or 0)
        radius = f.get("FENCE_RADIUS") or 0

        def pen(cam_vao):
            color = FENCE_OFF if not on else (FENCE_OUT if cam_vao else FENCE_IN)
            return QPen(color, 2, Qt.SolidLine if on else Qt.DashLine)

        p.setBrush(Qt.NoBrush)
        if radius > 0 and self.home and ftype & FENCE_TYPE_CIRCLE:
            # Tam vong tron cua ArduCopter la HOME, khong phai vi tri hien tai.
            r = int(radius / meters_per_px(self.home[0], self.zoom))
            p.setPen(pen(False))
            p.drawEllipse(self._to_px(*self.home, cx, cy), r, r)

        # Hinh tai tu nhiem vu FENCE nam duoi bit POLYGON. Truoc day ve vo dieu
        # kien: FC tat rao da giac ma ban do van ke duong lien, nhin ra la "co rao".
        for shape in (fence_shapes(f.get("items") or [])
                      if ftype & FENCE_TYPE_POLYGON else []):
            p.setPen(pen(shape[1]))
            if shape[0] == "poly":
                p.drawPolygon([self._to_px(a, b, cx, cy) for a, b in shape[2]])
            else:
                _, _, (lat, lon), r_m = shape
                r = int(r_m / meters_per_px(lat, self.zoom))
                p.drawEllipse(self._to_px(lat, lon, cx, cy), r, r)

    def _fence_note(self):
        """Mot dong ngan cho dai chu duoi day — trong do co thu ban do khong ve
        duoc: tran do cao."""
        f = self.fence
        if not f:
            return ""
        if f.get("err"):
            return t("map.fence_err", err=f["err"])
        if not f.get("FENCE_ENABLE", 0):
            return t("map.fence_off")
        ftype = int(f.get("FENCE_TYPE", 0) or 0)
        if not ftype:
            # FENCE_ENABLE = 1 nhung khong bat loai rao nao: FC KHONG chan gi ca.
            # Hien "rao BAT" o day la sai ve phia nguy hiem, va day la mot cau hinh
            # sai co that tren FC chu khong phai truong hop bia ra.
            return t("map.fence_notype")
        bits = []
        if ftype & FENCE_TYPE_CIRCLE and f.get("FENCE_RADIUS"):
            bits.append(f"r{f['FENCE_RADIUS']:.0f}m")
        if ftype & FENCE_TYPE_ALT_MAX and f.get("FENCE_ALT_MAX"):
            bits.append(t("map.fence_ceil", alt=f["FENCE_ALT_MAX"]))
        if ftype & FENCE_TYPE_POLYGON:
            n = sum(1 for s in fence_shapes(f.get("items") or []) if s[0] == "poly")
            if n:
                bits.append(t("map.fence_poly", n=n))

        # Muc F: "Khoang cach toi hang rao — sat thi keo ve". Chi hien MOT so: cai
        # gan nhat. Liet ke ca ba thi dai chu dai ra ma nguoi bay van phai tu so
        # xem cai nao sap cham — day chinh la viec dang muon lam ho.
        gan = self._fence_limits()
        if gan:
            m, key = min(gan)
            bits.append(t(key, m=m))
        return t("map.fence", bits=" ".join(bits)) if bits else t("map.fence_on")

    def _fence_limits(self):
        """[(so met con lai, key chu)] cho moi rao FC DANG BAT — va chi cai do.

        Nguon su that la FENCE_TYPE cua FC, khong phai su co mat cua tham so:
        FENCE_RADIUS van con gia tri cu khi rao tron da tat, va do mot rao FC
        khong chan la day nguoi bay tranh mot buc tuong khong ton tai — lan sau
        ho se khong tin con so nay nua.
        """
        f, out = self.fence, []
        if not (f and self.pos and f.get("FENCE_ENABLE", 0)):
            return out
        ftype = int(f.get("FENCE_TYPE", 0) or 0)

        # Tran do cao: ban do khong ve duoc, nen day la cho duy nhat no hien ra.
        alt_max = f.get("FENCE_ALT_MAX")
        if ftype & FENCE_TYPE_ALT_MAX and alt_max and self.alt_rel is not None:
            out.append((alt_max - self.alt_rel, "map.left_ceil"))

        # Vong tron quanh home. `home_from_fc` bat buoc: tam la home THAT cua FC,
        # do tu mot home doan ra thi con so kia la bia.
        r = f.get("FENCE_RADIUS")
        if ftype & FENCE_TYPE_CIRCLE and r and self.home and self.home_from_fc:
            out.append((r - haversine_m(*self.pos, *self.home), "map.left_fence"))

        if ftype & FENCE_TYPE_POLYGON:
            for shape in fence_shapes(f.get("items") or []):
                cam_vao = shape[1]
                if shape[0] == "poly":
                    dinh = shape[2]
                    d = min(_seg_dist_m(self.pos, a, b)
                            for a, b in zip(dinh, dinh[1:] + dinh[:1]))
                else:
                    _, _, tam, r_m = shape
                    d = abs(haversine_m(*self.pos, *tam) - r_m)
                # Cung mot khoang cach, hai cau nguoc nghia: rao BAY TRONG thi do
                # la cho con lai, vung CAM VAO thi do la cho dang het.
                out.append((d, "map.left_keepout" if cam_vao else "map.left_fence"))
        return out

    def _draw_wp(self, p, cx, cy):
        """Duong bay: noi cac diem theo thu tu seq, danh so, to dam diem dang toi.

        Ve sau rao va truoc vet bay co chu y: rao la ranh gioi cung nen nam duoi,
        duong bay la KE HOACH, vet bay la thu drone DA bay — cai that phai nam
        tren cung, khong bi ke hoach che mat.
        """
        pts = wp_points(self.wp.get("items") or [])
        if not pts:
            return
        px = [self._to_px(lat, lon, cx, cy) for _, lat, lon, _ in pts]
        p.setBrush(Qt.NoBrush)
        if len(px) > 1:
            p.setPen(QPen(WP_LINE, 2))
            p.drawPolyline(px)
        p.setFont(QFont("", 8))
        now = self.wp.get("seq")
        for (seq, *_), q in zip(pts, px):
            here = seq == now
            p.setPen(QPen(WP_NOW if here else WP_LINE, 2))
            p.drawEllipse(q, 5, 5)
            if here:
                p.drawEllipse(q, 9, 9)  # vong ngoai: thay duoc o goc mat luot qua
            # So thu tu tren anh ve tinh thi chim han — ke mot o toi phia sau,
            # cung cach dai chu duoi day dang lam. Con so nay la thu doi chieu
            # voi "toi #3" o dai chu, doc khong ra thi ca hai deu vo dung.
            box = QRect(q.x() + 7, q.y() - 17, 8 + 7 * len(str(seq)), 14)
            p.fillRect(box, QColor(0, 0, 0, 150))
            p.drawText(box, Qt.AlignCenter, str(seq))

    def _draw_draft(self, p, cx, cy):
        """Duong bay dang soan: dut net, o vuong, danh so tu 1.

        Danh so tu 1 chu khong tu 0 nhu duong bay that: muc 0 tren FC la home do
        ArduPilot tu giu, khong phai diem nguoi bay dat ra. Hai cach danh so khac
        nhau la co y — nhin so la biet dang xem cai nao.
        """
        if not self.draft:
            return
        px = [self._to_px(lat, lon, cx, cy) for lat, lon, _ in self.draft]
        p.setBrush(Qt.NoBrush)
        if len(px) > 1:
            p.setPen(QPen(WP_DRAFT, 2, Qt.DashLine))
            p.drawPolyline(px)
        p.setFont(QFont("", 8))
        p.setPen(QPen(WP_DRAFT, 2))
        for i, q in enumerate(px, 1):
            p.drawRect(q.x() - 4, q.y() - 4, 8, 8)
            box = QRect(q.x() + 7, q.y() - 17, 8 + 7 * len(str(i)), 14)
            p.fillRect(box, QColor(0, 0, 0, 150))
            p.drawText(box, Qt.AlignCenter, str(i))

    def _wp_note(self):
        """Mot doan cho dai chu duoi day. Rong khac han "chua tai duoc": chua tai
        thi khong noi gi, tai ve so 0 thi noi thang la FC khong co duong bay."""
        w = self.wp
        items = w.get("items")
        if items is None:
            return ""
        n, total = len(wp_points(items)), w.get("total")
        if not n:
            return t("map.wp_none")
        note = t("map.wp", n=n)
        if total and total > len(items):
            # Cat bot ma im lang thi nguoi bay tuong da nhin thay ca duong bay.
            note += t("map.wp_cut", total=total, got=len(items))
        if w.get("seq") is not None:
            note += t("map.wp_now", seq=w["seq"])
        return note

    def _home_note(self):
        """Con bao nhieu met ve nha.

        Muc F cua quy trinh bay bat can nhac RTL theo pin, nhung "RTL het bao lau"
        thi phu thuoc dang o cach nha bao xa — ma truoc day con so do khong nam o
        dau ca, chi co dau X tren ban do de uoc luong bang mat.

        Doi lien voi dau X chu khong tach ra o rieng: hai thu noi ve cung mot diem,
        thay so ma khong thay dau X thi khong biet no tinh tu dau.
        """
        if not self.pos:
            return ""       # chua ket noi thi khong co gi de noi, dung keu suong
        # Muc D.6: "Home da dat, DUNG CHO DUNG". Ca hai truong hop duoi day truoc
        # day deu im lang — mot cai khong ve gi, mot cai ve dau X y het home that.
        if not self.home:
            return t("map.no_home")
        if not self.home_from_fc:
            return t("map.home_guess")
        return t("map.home_dist", m=haversine_m(*self.pos, *self.home))

    def _draft_note(self):
        if not self.draft:
            return ""
        return t("map.draft", n=len(self.draft), alt=self.wp_alt)

    def _draw_drone(self, p, dp):
        """Tam giac nhon, mui la dau drone — giong QGroundControl.

        CHUA BIET HUONG thi ve lai hinh tron, khong ve tam giac chi len bac. Mot
        cai mui nhon la mot lời khẳng định "no dang quay ve huong nay"; chua co
        heading ma van ve mui la noi doi, va la kieu noi doi khong ai kiem duoc
        bang mat. Hinh tron thi noi dung cai minh biet: o day, khong biet huong.

        Vien den quanh hinh khong phai trang tri — tren anh ve tinh xanh la cay
        thi than mau xanh la cua drone chim han.
        """
        p.setPen(QPen(QColor(10, 10, 10), 2))
        p.setBrush(DRONE)
        if self.heading is None:
            p.drawEllipse(dp, 6, 6)
            return
        p.save()
        # Khu antialias VA nua pixel: canh xien cua tam giac khong bam luoi pixel,
        # thieu antialias thi no rang cua. Va tam phai la TAM O PIXEL (+0,5) —
        # xoay quanh mot goc pixel thi hinh lech mot pixel ve mot phia, va phia
        # lech doi khi quay 180 do: do duoc mui nho ra 10 px / duoi 9 px thay vi
        # 11 / 8. Chenh mot pixel thi nhin khong ra, nhung no lam bai kiem huong
        # mui nhap nhang, va thu gi khong do duoc thi som muon cung troi.
        p.setRenderHint(QPainter.Antialiasing, True)
        p.translate(dp.x() + 0.5, dp.y() + 0.5)
        # rotate() duong la thuan chieu kim dong ho, dung chieu cua heading
        # (0 bac -> 90 dong). Mui o (0, -11) quay 90 do ra (11, 0) = sang phai =
        # dong. Trung.
        p.rotate(self.heading)
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in DRONE_SHAPE]))
        p.restore()

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
            p.drawText(self.rect().adjusted(0, 8, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
                       t("map.no_tiles", z=self.zoom))
        elif self.zoom - tz > 3:
            # Phong to qua 3 bac la mang mau nhoe. Van ve — co con hon den — nhung
            # phai noi ro, khong de nguoi bay tuong vung nay dung la mot bai co trong.
            p.setFont(QFont("", 9))
            warn = t("map.upscaled", tz=tz, k=2 ** (self.zoom - tz))
            box = QRect(0, 4, w, 18)
            p.fillRect(box, QColor(0, 0, 0, 150))
            p.setPen(QColor(230, 176, 100))
            p.drawText(box, Qt.AlignCenter, warn)

        self._draw_fence(p, cx, cy)
        self._draw_wp(p, cx, cy)
        self._draw_draft(p, cx, cy)

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
            self._draw_drone(p, self._to_px(*self.pos, cx, cy))

        # Chu de tren anh ve tinh thi chim han. Ke mot dai toi mo phia sau — re hon
        # ve vien chu, va ngoai nang doc duoc that.
        p.setFont(QFont("", 8))
        note = f"z{self.zoom}  {self.center[0]:.5f}, {self.center[1]:.5f}"
        fence = self._fence_note()
        if fence:
            note += f"  ·  {fence}"
        for extra in (self._home_note(), self._wp_note(), self._draft_note()):
            if extra:
                note += f"  ·  {extra}"
        if not self.follow:
            note += f"  ·  {t('map.unfollow')}"
        if self.credit:
            note += f"  ·  {self.credit}"
        strip = QRect(0, self.height() - 16, self.width(), 16)
        p.fillRect(strip, QColor(0, 0, 0, 140))
        p.setPen(QColor(200, 208, 214))
        p.drawText(strip.adjusted(6, 0, -6, 0), Qt.AlignLeft | Qt.AlignVCenter, note)


def _far(a, b, eps=1e-6):
    return abs(a[0] - b[0]) > eps or abs(a[1] - b[1]) > eps
