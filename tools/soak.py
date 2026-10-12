#!/usr/bin/env python3
"""Bai chay lien tuc — rui ro #2: ghep pymavlink/WebSocket voi Qt sinh crash
ngau nhien sau vai phut. Ke hoach bat chay o cuoi MOI phase, khong chi N5.

    python3 tools/soak.py [phut] [chuoi_ket_noi] [mode]

`mode` mac dinh SIM. Chay tren FC that thi truyen REAL — banner phai do, khong
thi bai soak lai vi pham chinh nguyen tac 2.5 ma no di kiem tra.

Do ba thu moi phut: envelope co con chay khong, RAM co phinh khong, va vong lap
Qt co con nhip khong (UI dung hinh la hong, du chua crash).

Cho 60 s khoi dong truoc khi lay moc RAM: Piper nap giong o cau dau tien,
va bo dem do thi truc tiep can mot phut de day. `phut` la thoi gian DO sau
khoi dong; `soak.py 30` chay tong cong 31 phut, khong tang nguong RAM 60 MB.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import bus  # noqa: E402
from laptop.app import MainWindow  # noqa: E402

MINUTES = float(sys.argv[1]) if len(sys.argv) > 1 else 30
if not 0 < MINUTES < float("inf"):
    sys.exit("phut phai la so duong huu han")
CONN = sys.argv[2] if len(sys.argv) > 2 else "tcp:127.0.0.1:5760"
MODE = sys.argv[3] if len(sys.argv) > 3 else "SIM"


def rss_mb():
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6


app = QApplication([])
win = MainWindow([{"name": "soak", "mode": MODE, "conn": CONN, "sysid": 254}])
win.show()
assert win.panel.select("soak")
win.panel.btn_connect.click()

n = {"env": 0, "tick": 0, "last_env": 0, "quiet": False}
bus.on("*", lambda e: n.__setitem__("env", n["env"] + 1))
beat = QTimer()
beat.timeout.connect(lambda: n.__setitem__("tick", n["tick"] + 1))
beat.start(100)

t0 = time.monotonic()
rss0 = rss_mb()
last_sample = t0
print(f"khoi dong: {CONN}, RSS {rss0:.1f} MB; cho 60 s truoc khi do", flush=True)


def start():
    global t0, rss0, last_sample
    rss0 = rss_mb()
    t0 = last_sample = time.monotonic()
    n.update(env=0, tick=0, last_env=0, quiet=False)
    print(f"bat dau do: {MINUTES:g} phut, RSS {rss0:.1f} MB", flush=True)
    timer.start(60_000)
    QTimer.singleShot(max(1, round(MINUTES * 60_000)), done)


def sample():
    global last_sample
    now = time.monotonic()
    dt = now - last_sample
    if dt < 1:
        return  # timer ket thuc co the trung nhip lay mau
    last_sample = now
    el = (now - t0) / 60
    env = n["env"] - n["last_env"]
    n["last_env"] = n["env"]
    n["quiet"] |= env <= 0
    rss = rss_mb()
    ok = "OK " if env > 0 else "IM LANG"
    print(
        f"[{el:5.1f} phut] {ok} {env / dt:6.1f} env/s  RSS {rss:6.1f} MB "
        f"({rss - rss0:+.1f})  tick {n['tick']}  {win.banner.text()[:34]}",
        flush=True,
    )


def done():
    timer.stop()
    sample()
    el = (time.monotonic() - t0) / 60
    grow = rss_mb() - rss0
    print(f"\nket thuc sau {el:.1f} phut", flush=True)
    print(f"  envelope : {n['env']}  ({n['env'] / (el * 60):.0f}/s)", flush=True)
    print(f"  RAM      : {rss0:.1f} -> {rss_mb():.1f} MB  ({grow:+.1f})", flush=True)
    print(f"  Qt tick  : {n['tick']} (ky vong ~{int(el * 600)})", flush=True)
    # Assert trong slot QTimer KHONG dung app: truoc day hong la in traceback roi
    # phut sau `sample()` goi lai `done()`, hong tiep — chay mai, khong ma loi nao.
    why = ("khong nhan duoc envelope nao" if n["env"] <= 0 else
           "co khoang do mat telemetry" if n["quiet"] else
           "vong lap Qt bi treo" if n["tick"] <= el * 600 * 0.9 else
           f"RAM phinh {grow:.1f} MB — nghi ro ri" if grow >= 60 else None)
    print(f"SOAK FAIL — {why}" if why else "SOAK PASS", flush=True)
    win.disconnect()
    app.exit(1 if why else 0)


timer = QTimer()
timer.timeout.connect(sample)
QTimer.singleShot(60_000, start)
sys.exit(app.exec())
