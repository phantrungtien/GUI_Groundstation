#!/usr/bin/env python3
"""Bai "rut radio SiK -> sang 4G" chay tren laptop, khong can phan cung.

App THAT (MainWindow.connect_to + DualLink + man bay cam ung + VideoSource), chi
FC la gia, phat tren hai duong y nhu tren may tinh bang:
  SiK = TCP, giong SikBridge.java: rut radio thi GIU socket, chi im
  4G  = UDP toi `udpin`, giong MAVROS tren Jetson day toi IP Tailscale may tinh bang
        (kem heartbeat cua MAVROS 1/191 — no van den khi FC da mat)

    python3 tools/e2e_sik_4g.py

Bon pha:
  A chua cam radio  4G co FC  -> KHONG dung 4G, chua mo video, "Dang cho du lieu tu FC"
  B cam radio                 -> di SiK, mo video
  C rut radio                 -> tu sang 4G truoc nguong mat link, KHONG doc "Mat tin hieu"
  D rut FC (ca hai im)        -> "MAT TIN HIEU SiK", video van chay

Do 24/10: truoc khi DualLink doi o SWITCH_S = 1 s (bang STALE 2 s cua man hinh),
4/5 lan pha C loa doc "Mat tin hieu" roi 0,5 s sau 4G moi nhan.
Con lai phai thu tren may that: SikBridge khi rut radio that, MAVROS Jetson.
"""

import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from pymavlink.dialects.v20 import ardupilotmega as mav2  # noqa: E402

app = QApplication([])
import laptop.app as appmod  # noqa: E402
from core.field import REGISTRY  # noqa: E402

P_SIK, P_4G, P_VID = 47760, 47550, 47600
PHASES = [("A chua cam radio", 3.0), ("B cam radio", 4.0), ("C rut radio", 5.0), ("D rut FC", 4.0)]
phase = [0]


def enc(comp):
    m = mav2.MAVLink(None, srcSystem=1, srcComponent=comp)
    m.robust_parsing = True
    return m


def fc_packets(m, lat_deg):
    """Heartbeat + vi tri. lat 1 = goi di SiK, lat 2 = goi di 4G: nhin la biet duong nao."""
    hb = m.heartbeat_encode(mav2.MAV_TYPE_QUADROTOR, mav2.MAV_AUTOPILOT_ARDUPILOTMEGA,
                            mav2.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 0, mav2.MAV_STATE_STANDBY)
    pos = m.global_position_int_encode(0, int(lat_deg * 1e7), int(106.6 * 1e7), 0, 0, 0, 0, 0, 0)
    return hb.pack(m) + pos.pack(m)


def sik_bridge(stop):
    m = enc(1)
    ss = socket.socket()
    ss.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ss.bind(("127.0.0.1", P_SIK))
    ss.listen(1)
    s, _ = ss.accept()
    s.settimeout(0.01)
    while not stop.is_set():
        try:
            s.recv(65536)  # lenh cua app: Java bo goi khi chua co radio
        except (socket.timeout, BlockingIOError):
            pass
        if phase[0] == 1:
            s.sendall(fc_packets(m, 1.0))
        time.sleep(0.1)


def mavros(stop):
    fc, ros = enc(1), enc(191)
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while not stop.is_set():
        if phase[0] < 3:
            u.sendto(fc_packets(fc, 2.0), ("127.0.0.1", P_4G))
        hb = ros.heartbeat_encode(mav2.MAV_TYPE_ONBOARD_CONTROLLER, mav2.MAV_AUTOPILOT_INVALID,
                                  0, 0, 0)
        u.sendto(hb.pack(ros), ("127.0.0.1", P_4G))
        time.sleep(0.1)


def main():
    appmod.LOGS = Path(tempfile.mkdtemp())  # tlog ra cho tam, khong lan vao logs/
    fails = []
    appmod.QMessageBox.critical = staticmethod(lambda *a, **k: fails.append(a[-1]))
    win = appmod.MainWindow([])

    vid = []  # "start"/"stop" do app goi — VideoSource.start() tu goi stop() thi khong tinh
    inside = [False]
    o_start, o_stop = win.video.start, win.video.stop

    def v_start(*a, **k):
        vid.append("start")
        inside[0] = True
        try:
            return o_start(*a, **k)
        finally:
            inside[0] = False

    def v_stop(*a, **k):
        if not inside[0]:
            vid.append("stop")
        return o_stop(*a, **k)

    win.video.start, win.video.stop = v_start, v_stop
    t0 = [0.0]
    said = []
    o_say = win.touch.voice.say
    win.touch.voice.say = lambda key, **kw: (said.append((time.monotonic() - t0[0], key)),
                                             o_say(key, **kw))[1]

    stop = threading.Event()
    threading.Thread(target=sik_bridge, args=(stop,), daemon=True).start()
    threading.Thread(target=mavros, args=(stop,), daemon=True).start()
    time.sleep(0.2)
    t0[0] = time.monotonic()
    win.connect_to({"name": "e2e dien thoai", "mode": "REAL", "bridge": True, "sysid": 254,
                    "conn": f"tcp:127.0.0.1:{P_SIK}", "conn2": f"udpin:127.0.0.1:{P_4G}",
                    "video": f"udp://0.0.0.0:{P_VID}"})

    edges = [0.0]
    for _, d in PHASES:
        edges.append(edges[-1] + d)
    rows = []

    def tick():
        now = time.monotonic() - t0[0]
        while phase[0] < len(PHASES) - 1 and now >= edges[phase[0] + 1]:
            phase[0] += 1
        if now >= edges[-1]:
            app.quit()
            return
        win.touch.refresh()
        s = win.touch.state
        rows.append((now, phase[0], s["status"], s["linkPath"], REGISTRY.value("position.lat"),
                     bool(vid) and vid[-1] == "start", win.adapter is not None))

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    app.exec()
    stop.set()
    win.disconnect()

    last = None
    for r in rows:
        if r[1:] != last:
            print(f"{r[0]:5.1f}s  [{PHASES[r[1]][0]:16s}] {r[2]!r:28s} duong={r[3]:4s} "
                  f"lat={r[4]}  video={'mo' if r[5] else 'tat'}  adapter={'song' if r[6] else 'CHET'}")
            last = r[1:]
    print("loa doc:", [(round(t, 1), k) for t, k in said])

    A, B, C, D = ([r for r in rows if r[1] == i] for i in range(4))
    sw = next((r[0] - edges[2] for r in C if r[3] == "4G"), None)
    ok = [
        ("A: khong dung 4G khi SiK chua nghe FC", all(r[3] == "SiK" and r[4] != 2.0 for r in A)),
        ("A: chua mo video", not any(r[5] for r in A)),
        ("B: di SiK, so lieu tu SiK, video mo", (B[-1][3], B[-1][4], B[-1][5]) == ("SiK", 1.0, True)),
        (f"C: tu sang 4G (chi bao doi sau {sw:.1f} s)" if sw is not None else "C: tu sang 4G",
         sw is not None),
        ("C: so lieu tu 4G", C[-1][4] == 2.0),
        ("C: khong bao MAT TIN HIEU", not any("MẤT" in r[2] for r in C)),
        ("C: khong doc 'Mat tin hieu'",
         not any(k == "voice.lost" and edges[2] <= t < edges[3] for t, k in said)),
        ("C: video van chay, adapter song", all(r[5] and r[6] for r in C)),
        ("D: rut FC -> MAT TIN HIEU", "MẤT" in D[-1][2]),
        ("D: video van chay", D[-1][5]),
        ("khong hop thoai loi", not fails),
    ]
    for name, good in ok:
        print(("  ok    " if good else "  HONG  ") + name)
    sys.stdout.flush()
    os._exit(0 if all(g for _, g in ok) else 1)  # thread pymavlink cua app con treo socket


if __name__ == "__main__":
    main()
