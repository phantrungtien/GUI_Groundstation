#!/usr/bin/env python3
"""Nghiem thu man bay cam ung tren SITL that — moi tinh nang, mot chuyen bay.

`selfcheck.py` do MA NGUON: no dung adapter gia, bus gia, khong co FC nao o dau
kia. Cai no khong bao gio bat duoc la loai loi "ma nguon dung ma drone khong
lam" — do cao bi dien mac dinh, lenh gui dung nhung FC tu choi, mode chua kip
doi da ban lenh ke tiep. Ba loi dat nhat cua du an nay deu thuoc loai do.

File nay cam thang vao ArduCopter SITL va di dung duong ma ngon tay di:

    Backend.act()/addWp()/stick()  ->  Commands  ->  authority  ->  SikAdapter

KHONG mot buoc nao goi tat xuong pymavlink. Cai gi man hinh khong lam duoc thi o
day cung khong lam duoc.

Chay SITL truoc (khong can Gazebo, khong can ROS2):

    ~/ardupilot/build/sitl/bin/arducopter -S -I0 --model + --speedup 1 \
        --defaults ~/ardupilot/Tools/autotest/default_params/copter.parm \
        --home 10.8221589,106.6868454,10,0

SITL chi mo SERIAL1/2 (5762/5763) SAU khi co ai do cam vao SERIAL0 (5760) — nen
can mot MAVProxy giu cong do:

    mavproxy.py --master tcp:127.0.0.1:5760 --daemon

Roi:  python3 tools/e2e_sitl.py  [--conn tcp:127.0.0.1:5762]

Mat khoang 5 phut o toc do that. KHONG dung --speedup: bai nay do ca nhip giao
dien (timer 200 ms, ACK_TIMEOUT 3 s), tang toc la do sai chinh cai can do.
"""

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import bus, i18n  # noqa: E402
from core.adapters.sik import WP_MAX  # noqa: E402
from core.field import REGISTRY, haversine_m  # noqa: E402
from laptop.touch.backend import Backend  # noqa: E402

# Khoa ma QML doc tung cai mot. Thieu mot khoa la mot o tren man hinh thanh
# "undefined" — khong crash, chi im lang sai, nen phai diem danh.
STATE_KEYS = (
    "connected live mode profile status statusLevel fcMode armed alt dist hs vs "
    "heading flightTime battPct volt battLevel sats gpsLevel hasVideo alerts "
    "draftN draftFull wpAlt hasWp wpOver nudgeWhy diverge"
).split()

app = QApplication([])
fails, done = [], []
logs = []       # (muc, chu) — dung cai Commands ban ra, khong phai chu tu che
acks = []       # MISSION_ACK cua phien nap
arm_noise = [0, 0]  # khoang dong log cua vong bam ARM lai — xem muc D


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def v(field):
    return REGISTRY.value(field)


def alt():
    return v("position.alt_rel")


def check(name, ok, note=""):
    (done if ok else fails).append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{note}]" if note else ""),
          flush=True)
    return ok


def until(name, cond, secs, note=lambda: ""):
    """Doi mot dieu kien THAT tren FC. Het gio la FAIL, khong phai canh bao."""
    t0 = time.time()
    while time.time() - t0 < secs:
        wait(200)
        if cond():
            return check(name, True, f"{time.time() - t0:.1f}s {note()}".strip())
    return check(name, False, f"qua {secs}s, alt={alt()} mode={v('heartbeat.mode')} "
                              f"armed={v('heartbeat.armed')}")


def said(*bits):
    """Dong log gan nhat co chua tat ca cac manh chu nay khong?"""
    return any(all(b.lower() in s.lower() for b in bits) for _, s in logs[-6:])


def main(conn):
    prof = [{"name": "SITL e2e", "mode": "SIM", "conn": conn, "sysid": 254}]
    b = Backend(profiles=prof, owns_connection=True)
    b.cmd.log.connect(lambda s, sev: logs.append((sev, s)))
    b.map.resize(800, 600)
    b._profiles = prof
    bus.on("wp", lambda e: acks.append(e["data"]) if "write" in e["data"] else None)

    # ---- A. ket noi va telemetry ----------------------------------------
    print("\n== A. ket noi + telemetry ==", flush=True)
    b.connectTo(0)
    if not until("A1 co heartbeat va vi tri",
                 lambda: v("heartbeat.mode") and alt() is not None, 30):
        return
    # Doi chu khong chup mot phat: cac topic ve theo nhip rieng cua no, GPS_RAW_INT
    # cham hon HEARTBEAT vai giay tren SITL vua khoi dong. Chup o giay thu nhat la
    # bai test do NHIP MANG chu khong do giao dien.
    LOI = ("heartbeat.mode", "heartbeat.armed", "position.lat", "position.lon",
           "position.alt_rel", "gps.fix_type", "gps.sats", "battery.voltage",
           "vfr.groundspeed", "attitude.roll", "attitude.pitch")
    until("A2 field lo i nuoi giao dien deu co",
          lambda: not [f for f in LOI if v(f) is None], 60,
          lambda: f"thieu: {[f for f in LOI if v(f) is None]}")
    check("A3 state du khoa cho QML", not [k for k in STATE_KEYS if k not in b.state],
          f"thieu: {[k for k in STATE_KEYS if k not in b.state]}")
    until("A4 FC bao home", lambda: b.map.home_from_fc, 30)
    b.refresh()
    check("A5 GPS/pin doc ra muc, khong phai chu tron",
          b.state["gpsLevel"] in ("ok", "warn", "crit")
          and b.state["battLevel"] in ("ok", "warn", "crit"),
          f"gps={b.state['gpsLevel']} pin={b.state['battLevel']} sats={b.state['sats']}")

    # ---- B. ban do -------------------------------------------------------
    print("\n== B. ban do: keo, phong, bam theo ==", flush=True)
    b.mapFollow()
    wait(400)
    c0, z0 = b.map.center, b.map.zoom
    b.mapPan(120, 90)
    check("B1 keo thi ban do chay va thoi bam theo drone",
          b.map.center != c0 and not b.map.follow)
    b.mapZoom(1)
    b.mapZoom(-1)
    b.mapZoom(-1)
    check("B2 phong to/thu nho doi muc zoom", b.map.zoom == z0 - 1, f"{z0} -> {b.map.zoom}")
    for _ in range(40):
        b.mapZoom(1)
    check("B3 zoom co tran, khong troi tu do", b.map.zoom == 21, str(b.map.zoom))
    b.map.zoom = z0
    b.mapFollow()
    wait(400)
    check("B4 bam theo drone: tam ban do ve dung drone",
          b.map.follow and haversine_m(*b.map.center, *b.map.pos) < 1.0)
    mid = b._latlon(b.map.width() / 2, b.map.height() / 2)
    check("B5 diem giua man hinh doi nguoc lai ra dung toa do tam",
          haversine_m(*mid, *b.map.center) < 0.5)

    # ---- C. khong co duong xuong drone thi khong lenh nao di -------------
    print("\n== C. khoa lenh khi mat duong xuong drone ==", flush=True)
    keep = b.adapter
    b.adapter = None            # dung canh SiK dut ma profile con (banner do)
    b.refresh()
    n0 = len(logs)
    b.act("arm")
    b.sendWp()
    b.goto(400, 300)
    check("C1 SiK dut: ARM/NAP/bay-toi-day deu bi chan va NOI RA",
          not b.state["live"] and said("chưa kết nối") and len(logs) > n0)
    b.adapter = keep
    b.refresh()
    check("C2 co lai duong thi mo khoa", b.state["live"])

    # ---- D. mode, ARM, cat canh -----------------------------------------
    print("\n== D. chon mode, ARM, cat canh ==", flush=True)
    if v("heartbeat.armed"):
        b.act("mode", "LAND")
        until("D0 don dep: ha con drone dang bay", lambda: v("heartbeat.armed") is False, 150)
    b.act("mode", "LOITER")
    until("D1 FC doi sang LOITER", lambda: v("heartbeat.mode") == "LOITER", 20)
    n0 = len(logs)
    b.act("takeoff", "20")
    check("D2 cat canh ngoai GUIDED bi chan tai cho, noi ro mode",
          len(logs) > n0 and said("GUIDED"), logs[-1][1] if logs else "")
    b.act("mode", "GUIDED")
    until("D3 FC doi sang GUIDED", lambda: v("heartbeat.mode") == "GUIDED", 20)

    # Doi FC THAT SU arm duoc. SITL vua khoi dong thi EKF chua hoi tu va GPS chua
    # co fix, prearm tu choi — va bai nay tu no khong bao gio biet, no chi thay
    # "FC TU CHOI" roi ca phan con lai do theo day chuyen. Bon luot xanh dau tien
    # deu chay tren mot SITL da mo san tu lau: xanh vi may, khong vi he thong dung.
    until("D4 GPS co fix de arm", lambda: (v("gps.fix_type") or 0) >= 3
          and (v("gps.sats") or 0) >= 8, 180,
          lambda: f"fix={v('gps.fix_type')} sats={v('gps.sats')}")
    # Bam ARM lai vai lan: fix xong van con vai giay prearm chua thong (EKF, la ban).
    t0 = time.time()
    arm_noise[0] = len(logs)
    tries = 0
    while v("heartbeat.armed") is not True and time.time() - t0 < 60:
        b.act("arm")
        tries += 1
        wait(3000)
    arm_noise[1] = len(logs)
    check("D5 ARM", v("heartbeat.armed") is True,
          f"{time.time() - t0:.0f}s, {tries} lan bam")
    wait(2500)
    b.refresh()
    check("D6 dong ho gio bay chay tu luc ARM", b.state["flightTime"] >= 2,
          f"{b.state['flightTime']}s")
    b.act("takeoff", "25")
    until("D7 leo toi 25 m", lambda: (alt() or 0) >= 24, 90, lambda: f"alt={alt():.1f}")
    b.refresh()
    check("D8 vien trang thai doc la DANG BAY", b.state["statusLevel"] == "ok",
          f"{b.state['status']} / {b.state['statusLevel']}")

    # ---- E. bay toi day --------------------------------------------------
    print("\n== E. bay toi day (doi ca do cao) ==", flush=True)
    b.setWpAlt(12)
    b.map.center = b.map.pos
    p0 = b.map.pos
    b.goto(560, 180)
    check("E1 lenh de lai vet co kem so met", said("bay tới", "12 m"),
          logs[-1][1] if logs else "")
    until("E2 tut xuong dung 12 m", lambda: abs((alt() or 0) - 12) < 1.5, 90,
          lambda: f"alt={alt():.1f}")
    until("E3 da di ngang toi diem chi", lambda: haversine_m(*p0, *b.map.pos) > 20, 90,
          lambda: f"{haversine_m(*p0, *b.map.pos):.0f}m")
    b.refresh()
    check("E4 khoang cach ve nha tinh duoc", b.state["dist"] is not None,
          f"{b.state['dist']:.0f} m" if b.state["dist"] else "")

    # ---- F. can ao -------------------------------------------------------
    print("\n== F. can ao (nhich vi tri) ==", flush=True)
    b.refresh()
    check("F1 dang GUIDED tren troi thi can ao mo", b.state["nudgeWhy"] == "",
          b.state["nudgeWhy"])
    p0 = b.map.pos
    b.stick(0, 1, 0)                      # day het ve phia bac
    until("F2 day can thi drone chay that",
          lambda: haversine_m(*p0, *b.map.pos) > 8, 30,
          lambda: f"{haversine_m(*p0, *b.map.pos):.0f}m, "
                  f"hs={v('vfr.groundspeed'):.1f}m/s")
    b.stick(0, 0, 0)
    check("F3 buong can thi timer dung", not b._nudge_timer.isActive())
    until("F4 buong can thi drone dung lai",
          lambda: (v("vfr.groundspeed") or 9) < 0.6, 30,
          lambda: f"hs={v('vfr.groundspeed'):.2f}")

    # ---- G. duong bay ----------------------------------------------------
    print("\n== G. duong bay: dat, sua, nap, xoa ==", flush=True)
    b.clearWp()
    b.setWpAlt(30)
    b.map.center = b.map.pos
    for xy in ((560, 240), (600, 360), (420, 400)):
        b.addWp(*xy)
    check("G1 ba diem vao ban nhap, mang do cao dang chon",
          b.state["draftN"] == 3 and all(p[2] == 30.0 for p in b.map.draft))
    b.undoWp()
    check("G2 bo diem cuoi", b.state["draftN"] == 2)
    for _ in range(WP_MAX):
        b.map.add_draft(*b.map.pos)
    n0 = len(logs)
    b.addWp(500, 300)
    check("G3 tran WP_MAX chan lai va noi ra",
          b.state["draftN"] == WP_MAX and b.state["draftFull"] and len(logs) > n0,
          f"{b.state['draftN']}/{WP_MAX}")
    b.clearWp()
    check("G4 xoa nhap", b.state["draftN"] == 0)

    b.map.center = b.map.pos
    for xy in ((560, 240), (600, 360), (420, 400)):
        b.addWp(*xy)
    acks.clear()
    b.sendWp()
    until("G5 FC nhan duong bay", lambda: any(a["write"]["ok"] for a in acks), 60)
    check("G6 nhap duoc don sach sau khi FC nhan", b.state["draftN"] == 0)
    until("G7 doc lai duoc duong bay tu FC", lambda: len(b.map.wp.get("items") or []) > 0,
          60, lambda: f"{len(b.map.wp.get('items') or [])} muc")
    b.refresh()
    check("G8 giao dien biet FC dang giu duong bay", b.state["hasWp"])

    # ---- H. AUTO ---------------------------------------------------------
    print("\n== H. gat AUTO: no phai bay theo nhiem vu ==", flush=True)
    p0 = b.map.pos
    b.act("mode", "AUTO")
    until("H1 FC vao AUTO", lambda: v("heartbeat.mode") == "AUTO", 30)
    until("H2 dang bay theo duong", lambda: haversine_m(*p0, *b.map.pos) > 30, 120,
          lambda: f"alt={alt():.1f}")
    b.refresh()
    check("H3 giao dien biet dang bay AUTO (nap luc nay la GHI DE)", b.state["wpOver"])
    n0 = len(logs)
    b.addWp(500, 300)
    b.sendWp()
    check("H4 nap de giua luc AUTO: bam mot lan chi canh bao",
          len(logs) > n0 and said("AUTO"), logs[-1][1] if logs else "")
    b.sendWp()                            # bam lai trong WP_CONFIRM_S -> di
    check("H5 bam lai ngay thi moi nap", said("nạp", "waypoint"),
          logs[-1][1] if logs else "")
    b.refresh()
    check("H6 can ao KHOA khi dang AUTO (keo la bo ngang nhiem vu)",
          b.state["nudgeWhy"] != "", b.state["nudgeWhy"])

    # ---- I. ve nha va ha canh -------------------------------------------
    print("\n== I. ve nha, ha canh, cat dong co ==", flush=True)
    d0 = haversine_m(*b.map.pos, *b.map.home)
    b.act("rtl")
    until("I1 FC vao RTL", lambda: v("heartbeat.mode") == "RTL", 30)
    until("I2 dang ve gan nha", lambda: haversine_m(*b.map.pos, *b.map.home) < d0 - 10,
          120, lambda: f"{haversine_m(*b.map.pos, *b.map.home):.0f}m (tu {d0:.0f}m)")
    b.act("land")
    until("I3 ha canh va tu disarm", lambda: v("heartbeat.armed") is False, 200)
    n0 = len(logs)
    b.act("kill")
    check("I4 cat dong co duoi dat van gui duoc (force)", len(logs) > n0,
          logs[-1][1] if logs else "")

    # ---- J. xoa duong bay tren FC ---------------------------------------
    print("\n== J. xoa duong bay tren FC ==", flush=True)
    acks.clear()
    b.wipeWp()
    until("J1 FC xac nhan xoa", lambda: bool(acks), 60)
    until("J2 ban do khong con ve duong bay",
          lambda: not (b.map.wp.get("items") or []), 30)

    # ---- K. doi ngon ngu giua luc dang cam -------------------------------
    print("\n== K. doi ngon ngu ==", flush=True)
    was = i18n.lang()
    vi = b.state["status"]
    i18n.set_lang("en")
    b.refresh()
    en = b.state["status"]
    i18n.set_lang(was)
    b.refresh()
    check("K1 doi tieng thi chu tren man hinh doi theo, doi lai duoc",
          en != vi and b.state["status"] == vi, f"{vi!r} -> {en!r}")

    # ---- L. ngat ket noi --------------------------------------------------
    print("\n== L. ngat ket noi ==", flush=True)
    b.disconnect()
    wait(600)
    # Bon ve, va bai test PHAI noi ve nao hong: "L1 FAIL" tron khong cho biet la
    # nut chua khoa, home con day, hay mot canh bao ve SAU luc ngat.
    ve = {"connected": b.state["connected"], "live": b.state["live"],
          "home": b.map.home,
          "alerts": [a["text"] for a in b.state["alerts"]]}
    check("L1 ngat roi: khoa lenh, xoa ban do va canh bao cu",
          not ve["connected"] and not ve["live"]
          and ve["home"] is None and not ve["alerts"],
          f"con lai: {({k: x for k, x in ve.items() if x})}")

    # ---- M. phat lai chuyen vua bay --------------------------------------
    print("\n== M. phat lai (.tlog vua ghi) ==", flush=True)
    rep = [{"name": "Phat lai", "mode": "REPLAY", "path": "logs/*.tlog"}]
    b._profiles = rep
    REGISTRY.fields.clear()
    b.connectTo(0)
    if until("M1 doc duoc .tlog vua ghi", lambda: v("position.lat") is not None, 60):
        b.refresh()
        n0 = len(logs)
        b.act("arm")
        check("M2 REPLAY thi moi lenh bi khoa",
              not b.state["live"] and len(logs) > n0 and said("chưa kết nối"))
        check("M3 vien bao dang phat lai", b.state["statusLevel"] == "none",
              b.state["status"])
    b.disconnect()
    wait(400)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--conn", default="tcp:127.0.0.1:5762")
    a = ap.parse_args()
    t0 = time.time()
    try:
        main(a.conn)
    finally:
        # Bo cac dong "FC TU CHOI" cua vong bam ARM lai: do la prearm chua thong
        # trong luc EKF con hoi tu, khong phai su co — dem ca vao day thi bang ket
        # qua luc nao cung do lom dom va khong ai con doc no nua.
        nang = [x for i, (sev, x) in enumerate(logs)
                if sev <= 3 and not (arm_noise[0] <= i < arm_noise[1])]
        print(f"\n== KET QUA ==  {len(done)} pass / {len(fails)} fail "
              f"trong {time.time() - t0:.0f}s", flush=True)
        if fails:
            for f in fails:
                print("  FAIL  " + f, flush=True)
        print("dong loi/canh bao nang tu FC: " + (str(nang) if nang else "khong co"),
              flush=True)
    sys.exit(1 if fails else 0)
