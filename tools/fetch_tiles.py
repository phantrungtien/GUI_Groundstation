#!/usr/bin/env python3
"""Tai truoc tile ban do cho mot khu vuc -> assets/tiles/{z}/{x}/{y}.png

    python3 tools/fetch_tiles.py --lat -35.36326 --lon 149.16524 --km 2
    python3 tools/fetch_tiles.py --lat 10.762 --lon 106.660 --km 3 --zoom 13-18

Chay o NHA, truoc khi ra hien truong. Laptop ngoai bai bay khong co internet —
khong tai truoc thi tab Flight chi con luoi toa do.

Nguon mac dinh la anh ve tinh Esri. KHONG dung tile.openstreetmap.org: may chu
tinh nguyen cua ho cam prefetch hang loat va tra ve anh "Access blocked" kem ma
200 — tai 400 tile ve deu la anh bao loi, trong y nhu tai thanh cong. Do la ly do
ham fetch() duoi day so sanh byte cac tile dau tien (xem `_blocked_guard`).

Tile luu duoi duoi .png du Esri tra JPEG — QPixmap doc theo noi dung file chu
khong theo duoi ten, va MapWidget chi tim {z}/{x}/{y}.png.
"""

import argparse
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # de --coverage dung chung pick_tile_zoom voi MapWidget
TILE_DIR = ROOT / "assets" / "tiles"
UA = "GUI_NATIVE-GCS/1.0 (ground control station, offline tile prefetch)"
PAUSE = 0.1  # giay giua hai lan goi

SOURCES = {
    # ten: (url template, ghi chu attribution)
    "esri": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery"
             "/MapServer/tile/{z}/{y}/{x}", "Esri World Imagery"),
    "topo": ("https://a.tile.opentopomap.org/{z}/{x}/{y}.png", "OpenTopoMap (SRTM + OSM)"),
    # `lyrs=y` = anh ve tinh + ten duong de len. Doi sang `lyrs=s` neu muon anh tran.
    #
    # Vi sao co nguon nay du no la endpoint KHONG CHINH THUC cua Google: do that
    # tai IUH (10.8221589, 106.6868454), ba tile khac vi tri moi muc zoom —
    #   Esri   z19 22/15/18 KB · z20 va z21 deu la 2521 byte, CUNG md5 -> het anh
    #   Google z19 15/12/12 KB · z20 11/8.6/8.8 KB · z21 7.6/6.1/4.8 KB -> anh that
    # Tuc Esri tran o 29 cm/pixel, Google xuong toi 7.3 cm/pixel.
    #
    # Doi lai: Google co the chan IP hoac doi endpoint bat cu luc nao. Nen PHAI
    # prefetch san khu bay — online chi la phan bu. Mat mang hay bi chan giua buoi
    # bay thi map van ve tu dia, dung nhu thiet ke san co.
    "google": ("https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
               "Google Hybrid (anh ve tinh + nhan)"),
}


def deg2num(lat, lon, z):
    n = 2.0**z
    lat = max(min(lat, 85.05112878), -85.05112878)
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def bbox(lat, lon, km):
    """Hinh vuong canh 2*km quanh tam -> (lat_bac, lat_nam, lon_tay, lon_dong)."""
    dlat = km / 111.32
    dlon = km / (111.32 * math.cos(math.radians(lat)) or 1e-9)
    return lat + dlat, lat - dlat, lon - dlon, lon + dlon


def plan_world(zooms):
    """Toan cau, nhung chi o zoom thap.

    So tile la 4^z: z6 la 5.461 cai (~60 MB), z12 da la 22 trieu (~246 GB) va z17
    — muc nhin ro duong bang — la 23 ti (~250 TB). Nen nen the gioi chi de biet
    minh dang o dau tren qua dat; chi tiet van phai tai theo vung bay.
    """
    for z in zooms:
        n = 2**z
        for x in range(n):
            for y in range(n):
                yield z, x, y


def plan(lat, lon, km, zooms):
    north, south, west, east = bbox(lat, lon, km)
    for z in zooms:
        x0, y0 = deg2num(north, west, z)   # goc tren-trai
        x1, y1 = deg2num(south, east, z)   # goc duoi-phai
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                yield z, x, y


def fetch(url_tpl, z, x, y, refetch=False):
    """(trang thai, byte anh) — byte de ben ngoai phat hien tile bi chan."""
    path = TILE_DIR / str(z) / str(x) / f"{y}.png"
    if path.exists() and path.stat().st_size > 0 and not refetch:
        return "co roi", None
    req = urllib.request.Request(url_tpl.format(z=z, x=x, y=y), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ctype = r.headers.get("Content-Type", "")
            data = r.read()
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}", None
    except Exception as e:
        return str(e), None
    if not ctype.startswith("image/"):
        return f"khong phai anh ({ctype})", None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    time.sleep(PAUSE)
    return "tai ve", data


class _blocked_guard:
    """May chu chan thi tra ve CUNG MOT anh bao loi cho moi tile, kem ma 200.

    Bat sau vai tile dau thay vi de chay het roi moi phat hien ca thu muc la rac.
    """

    def __init__(self, need=6):
        self.seen = []
        self.need = need

    def check(self, data):
        if data is None or len(self.seen) >= self.need:
            return
        self.seen.append(data)
        if len(self.seen) == self.need and len(set(self.seen)) == 1:
            raise SystemExit(
                f"{self.need} tile dau giong het nhau tung byte -> may chu dang tra anh"
                " chan, khong phai ban do. Doi --source khac.\n"
                "Da xoa cac tile vua tai."
            )


def coverage():
    """Muc zoom nao ve duoc, muc nao trong. Chay sau moi lan tai.

    Ban do bien mat luc cuon zoom la loi da gap that: co tile z13-17 nhung cuon
    toi z19 la trong tron. Gio MapWidget phong ti le tu muc gan nhat, nhung cung
    chi trong pham vi cua pick_tile_zoom() — nen van co the con lo hong.
    """
    from laptop.widgets.map_widget import pick_tile_zoom

    avail = sorted(int(d.name) for d in TILE_DIR.glob("*")
                   if d.is_dir() and d.name.isdigit())
    if not avail:
        print("chua co tile nao trong assets/tiles")
        return
    print(f"muc zoom co tile: {avail}")
    for z in range(0, 22):
        tz = pick_tile_zoom(z, avail)
        if tz is None:
            print(f"  z{z:<2d} TRONG — tai them zoom quanh {z}")
        elif tz != z:
            print(f"  z{z:<2d} ve tu z{tz} ({'phong to' if tz < z else 'thu nho'})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", action="store_true",
                    help="chi bao cao muc zoom nao ve duoc, khong tai gi")
    ap.add_argument("--world", action="store_true",
                    help="tai nen the gioi (mac dinh zoom 0-6, ~5.500 tile ~60 MB)")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--km", type=float, default=2.0, help="ban kinh vung tai (km)")
    ap.add_argument("--zoom", help="dai zoom, vi du 13-17 (mac dinh 0-6 voi --world)")
    ap.add_argument("--max", type=int, default=1500, help="tran so tile, chan tay truot")
    ap.add_argument("--source", default="esri",
                    help=f"{'/'.join(SOURCES)} hoac mot URL template co {{z}}/{{x}}/{{y}}")
    # Doi nguon anh thi tile cu van nam do va bi bo qua ("co roi") — man hinh se
    # tron hai kieu anh. Ghi de tai cho, KHONG xoa thu muc truoc: dut mang giua
    # chung ma da xoa la mat trang ban do offline, dung luc sap ra bai bay.
    ap.add_argument("--refetch", action="store_true",
                    help="tai lai ca tile da co (dung khi doi --source)")
    args = ap.parse_args()
    if args.coverage:
        return coverage()
    if not args.world and (args.lat is None or args.lon is None):
        ap.error("can --lat/--lon, hoac --world de tai nen toan cau")

    url_tpl, credit = SOURCES.get(args.source, (args.source, args.source))
    lo, _, hi = (args.zoom or ("0-6" if args.world else "13-17")).partition("-")
    zooms = range(int(lo), int(hi or lo) + 1)

    if args.world:
        tiles = list(plan_world(zooms))
        where = "toan cau"
        args.max = max(args.max, len(tiles))  # da doc canh bao 4^z o ham plan_world
    else:
        tiles = list(plan(args.lat, args.lon, args.km, zooms))
        where = f"quanh {args.lat}, {args.lon} (ban kinh {args.km} km)"
    if len(tiles) > args.max:
        raise SystemExit(
            f"{len(tiles)} tile vuot tran {args.max}. Giam --km hoac --zoom "
            "(moi muc zoom la gap bon)."
        )

    print(f"{len(tiles)} tile {where}, zoom {zooms.start}-{zooms.stop - 1} tu {credit}")
    guard = _blocked_guard()
    stat = {}
    fresh = []
    try:
        for i, (z, x, y) in enumerate(tiles, 1):
            r, data = fetch(url_tpl, z, x, y, args.refetch)
            if data is not None:
                fresh.append(TILE_DIR / str(z) / str(x) / f"{y}.png")
            guard.check(data)
            stat[r] = stat.get(r, 0) + 1
            if i % 50 == 0 or i == len(tiles):
                print(f"  {i}/{len(tiles)}  {stat}")
    except SystemExit:
        for f in fresh:
            f.unlink(missing_ok=True)
        raise
    if any(k not in ("tai ve", "co roi") for k in stat):
        print("Co tile hong — chay lai lenh nay, no bo qua tile da co.")
    # Dong 1: ten nguon, MapWidget ghi len goc ban do (Esri va OpenTopoMap deu doi
    # ghi cong, va ai xem log bay sau nay cung can biet anh nen tu dau).
    # Dong 2: URL template, de MapWidget tai bu tile con thieu khi may co mang —
    # tai bang DUNG nguon ban da prefetch, khong tron hai kieu anh tren mot man hinh.
    (TILE_DIR / "SOURCE.txt").write_text(f"{credit}\n{url_tpl}\n")
    size = sum(f.stat().st_size for f in TILE_DIR.rglob("*.png"))
    print(f"xong. {TILE_DIR} hien co {size / 1e6:.1f} MB  ·  nguon: {credit}")


if __name__ == "__main__":
    main()
