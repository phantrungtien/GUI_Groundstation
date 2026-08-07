#!/usr/bin/env python3
"""So tung con so tren GUI voi mot GCS khac, tren CUNG mot luong MAVLink.

Nghiem thu phase N2: "chay SITL, so tung con so voi Mission Planner — sai lech
chi do lam tron". Mission Planner la app C#/Windows; tren Linux GCS doi chieu la
MAVProxy, GCS tham chieu cua chinh ArduPilot. Module console cua MAVProxy tu
scale lai raw MAVLink bang code rieng cua no, khong dung chung mot dong nao voi
core/adapters/sik.py — nen no la nhan chung doc lap that.

Hai muc doi chieu, vi console cua MAVProxy lam tron ve so nguyen:

  1. GUI vs MAVProxy console — bat loi sai don vi. Loai loi nay luon lech >=100
     lan (mm doc thanh m, cdeg thanh deg), so nguyen thua suc bat.
  2. GUI vs raw MAVLink — bat loi lam tron. He so quy doi KHONG go tay ma lay tu
     `fieldunits_by_name`, tuc tu chinh XML MAVLink chinh thuc.

So o hai trang thai TINH (tren dat, va treo 10 m) de lech thoi gian giua hai ben
khong tro thanh lech so lieu.

    python3 tools/compare_gcs.py            # SITL phai dang chay o tcp:5760

Duong ong:  SITL 5760 -> MAVProxy -+-> udp:14551  GUI (khong cua so)
                                   +-> udp:14552  nghe raw
                                   +-> udp:14553  lai SITL cat canh
"""

import ctypes
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pymavlink import mavutil  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.field import REGISTRY, haversine_m  # noqa: E402
from laptop.app import MainWindow  # noqa: E402

MASTER = os.environ.get("CMP_MASTER", "tcp:127.0.0.1:5760")
# ARM + cat canh CHI khi duoc bao thang bang --takeoff. Cam FC that vao ma cong
# cu tu nang drone len 10 m thi khong con la bai do, la tai nan. Khong suy doan
# "chac day la SITL" — mot chuoi ket noi noi bo van co the la cau sang FC that.
TAKEOFF_OK = "--takeoff" in sys.argv
# Tranh xa 14550/14551: Mission Planner tu mo nghe ca hai cong do ngay khi khoi
# dong, khong doi ai bao. Trung cong thi GUI cua minh khong bind duoc.
GUI_PORT, RAW_PORT, DRV_PORT = 14561, 14562, 14563
# Cho GCS thu ba cam vao (Mission Planner, QGC). Khong ai nghe thi thoi, MAVProxy
# ban vao cong trong khong ton gi.
MP_PORT = 14550
HOVER_ALT = 10.0

# Nhan chung thu ba cho toa do, va la nhan chung duy nhat khong di qua MAVLink:
# cho dung cua SITL, lay tu Tools/autotest/locations.txt (CMAC). Ca hai GCS deu
# doc chung mot goi tin, nen neu goi tin sai thi ca hai cung sai giong nhau —
# chi co hang so nay moi bat duoc kieu sai do.
SITL_HOME = (-35.363261, 149.165230)
HOME_TOL_M = 3.0


def truth_point():
    """Diem chuan de soi toa do. Mac dinh la cho SITL dat drone.

    Bay tren FC that thi truyen --home <vi do>,<kinh do> — do mot lan bang dien
    thoai o ngay cho dat drone la du (sai so ~5 m, van bat duoc moi loai sai that).
    """
    for i, a in enumerate(sys.argv):
        if a == "--home" and i + 1 < len(sys.argv):
            lat, lon = sys.argv[i + 1].split(",")
            return float(lat), float(lon), float(os.environ.get("CMP_HOME_TOL", 10))
    return SITL_HOME[0], SITL_HOME[1], HOME_TOL_M

# Console cua MAVProxy ve cua so wx. Patch de no in ra stdout thay vi ve — day la
# cach duy nhat cao duoc so DA SCALE cua no ra ma khong phai doc anh man hinh.
MP_SHIM = """
import sys, time, runpy
from MAVProxy.modules.lib import textconsole
textconsole.SimpleConsole.__init__ = lambda self, **kw: None
textconsole.SimpleConsole.set_status = (
    lambda self, name, text='', row=0, fg='black', bg='white':
    print("MP|%.3f|%s|%s" % (time.time(), name, text), flush=True))
from MAVProxy.modules.lib import wxconsole
wxconsole.MessageConsole = textconsole.SimpleConsole

# Console cua MAVProxy khong he ve lat/lon — no khong co o nao cho toa do. Nhung
# module `map` thi co: no tu scale m.lat*1.0e-7 bang code rieng roi day vao
# map.set_position(). Thay ca doi tuong ban do bang mot cai giu cho chi biet in,
# the la co toa do da scale boi MAVProxy ma khong phai mo cua so nao.
from MAVProxy.modules.mavproxy_map import mp_slipmap
class _TextMap:
    def __init__(self, **kw): pass
    def set_position(self, key, latlon, layer='', rotation=0, label=None, colour=None):
        if str(key).startswith('Pos'):
            print("MP|%.3f|_latlon|%.7f %.7f" % (time.time(), latlon[0], latlon[1]),
                  flush=True)
    # Module map moi vong idle deu hoi cua so con song khong; tra None la no tu
    # go minh ra ngay ("Unloaded module map") va khong bao mot tieng nao.
    def is_alive(self): return True
    def __getattr__(self, name):
        return lambda *a, **k: None
mp_slipmap.MPSlipMap = _TextMap

sys.argv = sys.argv[1:]
runpy.run_module("MAVProxy.mavproxy", run_name="__main__")
"""

# Don vi trong XML MAVLink -> he so ve don vi SI ma GUI hien. Chi liet ke don vi
# thuc su gap; gap don vi la thi KeyError, tot hon la doan bua mot he so.
FACTOR = {"mm": 1e-3, "cm": 1e-2, "cm/s": 1e-2, "cdeg": 1e-2, "degE7": 1e-7,
          "mV": 1e-3, "m": 1.0, "m/s": 1.0, "deg": 1.0, "%": 1.0, "": 1.0}


def si(msg, field):
    """Gia tri raw quy ve don vi SI, he so lay tu XML MAVLink chu khong go tay."""
    raw = getattr(msg, field)
    unit = type(msg).fieldunits_by_name.get(field, "")
    if unit == "rad":  # rad -> do: khong phai phep nhan he so nen tach rieng
        return math.degrees(raw)
    return raw * FACTOR[unit]


def _die_with_parent():
    """Bao kernel giet con khi cha chet.

    Khong co dong nay thi mot lan Ctrl-C hay SIGKILL vao script de lai MAVProxy
    mo coi om nguyen TCP 5760 cua SITL; lan chay sau khong vao duoc cua nao ma
    bao "khong len duoc link" — mat nua tieng moi tim ra thu pham.
    """
    ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


class Reference:
    """MAVProxy chay that, giu ban moi nhat cua moi o tren console cua no."""

    def __init__(self):
        self.status = {}
        # Radio SiK cam vao la mot cong noi tiep, phai noi baud; udp/tcp thi khong.
        baud = ["--baudrate", os.environ.get("CMP_BAUD", "57600")] \
            if MASTER.startswith("/dev/") else []
        self.proc = subprocess.Popen(
            [sys.executable, "-c", MP_SHIM, "mavproxy.py", "--master=" + MASTER] + baud + [
             f"--out=udp:127.0.0.1:{GUI_PORT}", f"--out=udp:127.0.0.1:{RAW_PORT}",
             f"--out=udp:127.0.0.1:{DRV_PORT}", f"--out=udp:127.0.0.1:{MP_PORT}",
             "--console", "--load-module=map", "--non-interactive",
             "--state-basedir=" + os.environ.get("TMPDIR", "/tmp")],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            preexec_fn=_die_with_parent,
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            if line.startswith("MP|"):
                _, _, name, text = line.rstrip("\n").split("|", 3)
                self.status[name] = text

    def stop(self):
        self.proc.terminate()


class RawSniffer:
    """Nghe cung mot luong, giu message tho moi nhat theo tung loai."""

    def __init__(self):
        self.msgs = {}
        self.texts = deque(maxlen=12)  # FC noi vi sao khong ARM duoc thi o day
        self.conn = mavutil.mavlink_connection(f"udp:127.0.0.1:{RAW_PORT}")
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            m = self.conn.recv_match(blocking=True, timeout=5)
            # Chi lay tieng cua FC (component 1). MAVProxy cung phat heartbeat
            # cua chinh no vao day, lay nham thi mode doc ra la mode cua GCS.
            if m and m.get_srcComponent() in (0, 1):
                self.msgs[m.get_type()] = m
                if m.get_type() == "STATUSTEXT":
                    self.texts.append(m.text)

    def armed(self):
        hb = self.msgs.get("HEARTBEAT")
        return bool(hb and hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)


# --------------------------------------------------------------- doc hai ben

def gui_row(win):
    """Doc dung nhung con so DANG HIEN tren GUI, khong doc tat qua adapter."""
    bar = win.flight_tab.telemetry
    txt = {k: bar._val[k].text() for k in ("ALT", "SPD", "PIN", "SAT", "MODE")}
    lat, _ = REGISTRY.best("position.lat")
    lon, _ = REGISTRY.best("position.lon")
    return {
        "alt_rel": txt["ALT"], "groundspeed": txt["SPD"], "voltage": txt["PIN"],
        "sats": txt["SAT"], "mode": txt["MODE"],
        "heading": f"{win.flight_tab.compass._heading:.1f}",
        "roll": f"{math.degrees(win.flight_tab.attitude._roll):.1f}",
        "pitch": f"{math.degrees(win.flight_tab.attitude._pitch):.1f}",
        "lat": f"{lat:.7f}" if lat is not None else "--",
        "lon": f"{lon:.7f}" if lon is not None else "--",
    }


def _num(text, pattern):
    m = re.search(pattern, text or "")
    return float(m.group(1)) if m else None


def mp_row(ref):
    """Boc so ra khoi chuoi console cua MAVProxy. None = o do MAVProxy khong ve."""
    s = ref.status
    ll = (s.get("_latlon") or "").split()  # tu module map, khong phai console
    return {
        "alt_rel": _num(s.get("Alt"), r"Alt (-?[\d.]+)m"),
        "groundspeed": _num(s.get("GPSSpeed"), r"GPSSpeed (-?[\d.]+)m/s"),
        "voltage": _num(s.get("Battery"), r"([\d.]+)V"),
        "sats": _num(s.get("GPS"), r"\((\d+)\)"),
        "mode": (s.get("Mode") or "").strip() or None,
        "heading": _num(s.get("Heading"), r"Hdg (-?[\d.]+)"),
        "roll": _num(s.get("Roll"), r"Roll (-?[\d.]+)"),
        "pitch": _num(s.get("Pitch"), r"Pitch (-?[\d.]+)"),
        "lat": float(ll[0]) if len(ll) == 2 else None,
        "lon": float(ll[1]) if len(ll) == 2 else None,
    }


def raw_row(snf):
    g, v, y, a = (snf.msgs.get(t) for t in
                  ("GLOBAL_POSITION_INT", "VFR_HUD", "GPS_RAW_INT", "ATTITUDE"))
    s = snf.msgs.get("SYS_STATUS")
    # FC gui HAI huong mui khac nhau: ATTITUDE.yaw va GLOBAL_POSITION_INT.hdg.
    # Chung lech nhau ~1 do that (hai dau ra EKF, hai nhip). Tab Flight uu tien
    # attitude.heading roi moi tut ve position.heading — phai soi dung cai no
    # dang dung, khong thi bang so bao HONG trong khi GUI khong sai gi.
    hdg = (math.degrees(a.yaw) % 360.0 if a and REGISTRY.best("attitude.heading")[0]
           is not None else (si(g, "hdg") if g else None))
    return {
        "alt_rel": si(g, "relative_alt") if g else None,
        "groundspeed": si(v, "groundspeed") if v else None,
        "voltage": si(s, "voltage_battery") if s else None,
        "sats": y.satellites_visible if y else None,
        "mode": None,  # custom_mode la so, ten mode nam trong bang cua tung hang
        "heading": si(g, "hdg") if g else None,
        "roll": si(a, "roll") if a else None,
        "pitch": si(a, "pitch") if a else None,
        "lat": si(g, "lat") if g else None,
        "lon": si(g, "lon") if g else None,
    }


# ------------------------------------------------------------------- so sanh
# (khoa, nhan, don vi, dung sai voi console MAVProxy, dung sai voi raw)
#
# Dung sai voi console rong vi console lam tron ve so nguyen ("%um"): treo 10.4 m
# thi no ghi "Alt 10m". Dung sai voi raw moi la cai chung minh "chi lech do lam
# tron" — GUI hien mot chu so thap phan nen 0.05 la nua don vi cuoi cung.
ROWS = [
    ("alt_rel", "do cao tuong doi", "m", 1.0, 0.05),
    ("groundspeed", "toc do ngang", "m/s", 1.0, 0.05),
    ("voltage", "dien ap pin", "V", 0.05, 0.005),
    ("sats", "so ve tinh", "", 0, 0),
    ("heading", "huong mui", "do", 1.0, 0.05),
    ("roll", "roll", "do", 1.0, 0.5),
    ("pitch", "pitch", "do", 1.0, 0.5),
    # 1e-5 do ~ 1.1 m: rong hon nhieu lan do trôi cua GPS SITL giua hai lan lay
    # mau, nhung van chat hon moi loai sai that (sai don vi lech 1e7 lan).
    ("lat", "vi do", "do", 1e-5, 5e-8),
    ("lon", "kinh do", "do", 1e-5, 5e-8),
    ("mode", "che do bay", "", 0, None),
]


def check_home(gui):
    """Toa do GUI hien co dung cho SITL dat drone khong (met, khong phai do)."""
    if gui["lat"] == "--" or gui["lon"] == "--":
        print("toa do   : GUI chua co so — khong ket luan duoc")
        return ["toa do (khong co so)"]
    lat0, lon0, tol = truth_point()
    d = haversine_m(float(gui["lat"]), float(gui["lon"]), lat0, lon0)
    ok = d <= tol
    print(f"toa do   : lech {d:.2f} m so voi diem chuan ({lat0}, {lon0}), "
          f"nguong {tol:.0f} m — {'OK' if ok else 'HONG'}")
    return [] if ok else ["toa do so voi SITL"]


def compare(title, gui, mp, raw):
    print(f"\n=== {title} ===")
    print(f"{'dai luong':<20}{'GUI':>16}{'MAVProxy':>14}{'raw MAVLink':>16}"
          f"{'lech GUI-MP':>13}{'lech GUI-raw':>14}  ket qua")
    fails = []
    for key, label, unit, tol_mp, tol_raw in ROWS:
        g, m, r = gui[key], mp[key], raw[key]
        cells, deltas, bad = [], [], False

        if key == "mode":  # chuoi: bang nhau hoac khong, khong co "lech"
            ok = g == m
            bad = not ok
            print(f"{label:<20}{g:>16}{str(m):>14}{'-':>16}"
                  f"{('khop' if ok else 'KHAC'):>13}{'-':>14}  {'OK' if ok else 'HONG'}")
            if bad:
                fails.append(label)
            continue

        gv = None if g in ("--", "") else float(g)
        fmt = ".9g" if key in ("lat", "lon") else ".6g"
        cells = [g if gv is None else format(gv, fmt),
                 "-" if m is None else format(m, fmt),
                 "-" if r is None else format(r, fmt)]
        for other, tol in ((m, tol_mp), (r, tol_raw)):
            if gv is None or other is None or tol is None:
                deltas.append("-")
                continue
            d = abs(gv - other)
            deltas.append(f"{d:.3g}")
            if d > tol:
                bad = True
        verdict = "HONG" if bad else ("OK" if gv is not None else "chua co")
        print(f"{label:<20}{cells[0]:>16}{cells[1]:>14}{cells[2]:>16}"
              f"{deltas[0]:>13}{deltas[1]:>14}  {verdict}")
        if bad:
            fails.append(label)
    return fails


# ------------------------------------------------------------------ dieu khien

def land(drv):
    drv.set_mode("LAND")


def arm(drv):
    drv.set_mode("GUIDED")
    drv.mav.command_long_send(drv.target_system, drv.target_component,
                              mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                              0, 1, 0, 0, 0, 0, 0, 0)


def takeoff(drv, alt):
    drv.mav.command_long_send(drv.target_system, drv.target_component,
                              mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                              0, 0, 0, 0, 0, 0, 0, alt)


def main():
    busy = [p for p in (GUI_PORT, RAW_PORT, DRV_PORT) if not port_free(p)]
    if busy:
        print(f"cong {busy} dang co nguoi giu — nhieu kha nang la MAVProxy mo coi "
              f"tu lan chay truoc.\n  tim:  ss -tnlp | grep {busy[0]}", file=sys.stderr)
        return 2

    ref, snf = Reference(), RawSniffer()
    app = QApplication([])
    # Nguyen tac 2.5: banner phai noi that. Nguon la FC that thi mode la REAL, du
    # GUI van nhan qua UDP tu MAVProxy chu khong cam thang vao cong noi tiep.
    win = MainWindow([{"name": "cmp",
                       "mode": "REAL" if MASTER.startswith("/dev/") else "SIM",
                       "conn": f"udp:127.0.0.1:{GUI_PORT}", "sysid": 254}])
    win.show()
    assert win.panel.select("cmp")
    win.panel.btn_connect.click()

    drv = mavutil.mavlink_connection(f"udp:127.0.0.1:{DRV_PORT}", source_system=252)
    state = {"step": "cho_link", "t": time.time(), "fails": [], "reports": 0,
             "held": False}

    def snap(title, home=False):
        gui = gui_row(win)
        state["fails"] += compare(title, gui, mp_row(ref), raw_row(snf))
        if home:
            state["fails"] += check_home(gui)
        state["reports"] += 1

    def tick():
        el = time.time() - state["t"]
        if state["step"] == "cho_link":
            # Doi ca hai ben cung noi va SITL co dinh vi: so sanh khi mot ben con
            # trong thi khong chung minh duoc gi.
            if raw_row(snf)["sats"] and mp_row(ref)["alt_rel"] is not None \
                    and gui_row(win)["alt_rel"] != "--":
                drv.wait_heartbeat(timeout=10)
                # SITL co the con dang bay tu lan chay truoc. Do o tren khong ma
                # ghi nhan "tren dat" thi bang so noi doi ngay dong dau.
                if (raw_row(snf)["alt_rel"] or 0) > 1.0 and TAKEOFF_OK:
                    print("dang o tren khong — cho ha canh truoc")
                    land(drv)
                    state["step"], state["t"] = "cho_ha", time.time()
                else:
                    state["step"] = "tren_dat"
            elif el > 90:
                print("khong len duoc link sau 90 giay", file=sys.stderr)
                app.exit(2)
        elif state["step"] == "cho_ha":
            if (raw_row(snf)["alt_rel"] or 0) < 0.3:
                state["step"], state["t"] = "tren_dat", time.time()
            elif el > 120:
                print("khong ha canh duoc sau 120 giay", file=sys.stderr)
                app.exit(2)
        elif state["step"] == "tren_dat":
            # Khong co --takeoff thi cong cu khong ha canh ai ca, drone dang o
            # dau do o day. Dat ten mau theo do cao DO DUOC, dung ghi "tren dat"
            # cho dep — nhan sai lam ca bang so thanh vo nghia.
            alt = raw_row(snf)["alt_rel"] or 0
            snap("TREN DAT" if alt < 1.0 else f"DANG O TREN KHONG ({alt:.1f} m)",
                 home=True)
            if not TAKEOFF_OK:
                print("\nkhong co --takeoff: chi do tren dat, khong ARM, khong "
                      "cham vao drone.")
                state["step"] = "xong"
                return
            arm(drv)
            state["step"], state["t"] = "cho_arm", time.time()
        elif state["step"] == "cho_arm":
            # Vua ha canh xong ARM lai thuong bi tu choi (EKF con lang, motor con
            # quay). Goi lai moi 3 giay thay vi tin lan dau roi doi 120 giay.
            if snf.armed():
                takeoff(drv, HOVER_ALT)
                state["step"], state["t"] = "cho_len", time.time()
            elif el > 45:
                print("khong ARM duoc sau 45 giay. FC noi:", file=sys.stderr)
                for t in snf.texts:
                    print("   " + t, file=sys.stderr)
                app.exit(2)
            elif int(el) % 3 == 0:
                arm(drv)
        elif state["step"] == "cho_len":
            alt = raw_row(snf)["alt_rel"]
            # Doi treo yen: con leo thi hai ben doc o hai thoi diem khac nhau se
            # lech that, ma cai lech do khong phai loi cua ai.
            if alt is not None and abs(alt - HOVER_ALT) < 0.3 and el > 20:
                snap(f"TREO {HOVER_ALT:.0f} m, GUIDED")
                state["step"] = "xong"
            elif el > 120:
                print("khong len duoc do cao sau 120 giay. FC noi:", file=sys.stderr)
                for t in snf.texts:
                    print("   " + t, file=sys.stderr)
                state["step"] = "xong"
        elif state["step"] == "xong":
            if "--hold" not in sys.argv:
                app.exit(0)
            elif not state["held"]:
                # Giu duong truyen song de GCS thu ba (Mission Planner, QGC) con
                # doc duoc CUNG trang thai tinh nay. Thoat luon la no mat link.
                print(f"\n--hold: drone dang treo {HOVER_ALT:.0f} m, duong truyen "
                      f"con song o udp:{MP_PORT}. Ctrl-C de dung.")
                state["held"] = True

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(1000)
    code = app.exec()

    ok = state["reports"] == (2 if TAKEOFF_OK else 1) and not state["fails"]
    print("\n" + ("DOI CHIEU PASS — moi con so khop trong dung sai"
                  if ok else f"DOI CHIEU HONG: {sorted(set(state['fails']))}"))
    if ok:
        Path("logs").mkdir(exist_ok=True)
        Path("logs/compare_gcs.json").write_text(json.dumps(
            {"ts": time.time(), "master": MASTER, "reports": state["reports"]}, indent=2))
    win.disconnect()
    ref.stop()
    return 0 if ok else (code or 1)


def selftest():
    """Bai kiem tra cua chinh bai kiem tra.

    Mot bang toan OK khong chung minh gi neu bang do khong bao gio biet keu. Bon
    truong hop duoi la bon kieu sai that: sai don vi, sai mode, sai toa do, va
    truong hop dung.
    """
    gui = {"alt_rel": "10.0", "groundspeed": "0.0", "voltage": "12.60",
           "sats": "10", "mode": "GUIDED", "heading": "353.4", "roll": "0.0",
           "pitch": "0.0", "lat": "-35.3632610", "lon": "149.1652300"}
    mp = {"alt_rel": 10.0, "groundspeed": 0.0, "voltage": 12.6, "sats": 10.0,
          "mode": "GUIDED", "heading": 353.0, "roll": 0.0, "pitch": 0.0,
          "lat": -35.363261, "lon": 149.16523}
    raw = dict(mp, heading=353.4)

    assert compare("selftest — moi thu khop", gui, mp, raw) == []
    assert check_home(gui) == []
    # doc mm thanh m: do cao gap 1000 lan. Day la kieu sai ma muc 1 phai bat.
    assert "do cao tuong doi" in compare(
        "selftest — sai don vi mm/m", dict(gui, alt_rel="10000.0"), mp, raw)
    # lech 0.2 V: qua nho de goi la sai don vi, du de qua nguong lam tron.
    assert "dien ap pin" in compare(
        "selftest — lech dien ap", dict(gui, voltage="12.80"), mp, raw)
    assert "che do bay" in compare(
        "selftest — sai mode", dict(gui, mode="LOITER"), mp, raw)
    # lech ~1.1 km: kieu sai ma ca hai GCS cung doc sai giong nhau.
    assert check_home(dict(gui, lat="-35.373261")) != []
    print("\nSELFTEST PASS — bang so biet keu khi lech")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
