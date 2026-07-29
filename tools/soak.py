#!/usr/bin/env python3
"""Bai chay lien tuc — rui ro #2: ghep pymavlink/WebSocket voi Qt sinh crash
ngau nhien sau vai phut. Ke hoach bat chay o cuoi MOI phase, khong chi N5.

    python3 tools/soak.py [phut] [chuoi_ket_noi]

Do ba thu moi phut: envelope co con chay khong, RAM co phinh khong, va vong lap
Qt co con nhip khong (UI dung hinh la hong, du chua crash).
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
CONN = sys.argv[2] if len(sys.argv) > 2 else "tcp:127.0.0.1:5760"


def rss_mb():
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6


app = QApplication([])
win = MainWindow([{"name": "soak", "mode": "SIM", "conn": CONN, "sysid": 254}])
win.show()
win.panel.list.setCurrentRow(0)
win.panel.btn_connect.click()

n = {"env": 0, "tick": 0, "last_env": 0}
bus.on("*", lambda e: n.__setitem__("env", n["env"] + 1))
beat = QTimer()
beat.timeout.connect(lambda: n.__setitem__("tick", n["tick"] + 1))
beat.start(100)

t0 = time.time()
rss0 = rss_mb()
print(f"bat dau: {CONN}, {MINUTES:g} phut, RSS {rss0:.1f} MB", flush=True)


def sample():
    el = (time.time() - t0) / 60
    env = n["env"] - n["last_env"]
    n["last_env"] = n["env"]
    ok = "OK " if env > 0 else "IM LANG"
    print(
        f"[{el:5.1f} phut] {ok} {env / 60:6.1f} env/s  RSS {rss_mb():6.1f} MB "
        f"(+{rss_mb() - rss0:+.1f})  tick {n['tick']}  {win.banner.text()[:34]}",
        flush=True,
    )
    if el >= MINUTES:
        done()


def done():
    el = (time.time() - t0) / 60
    grow = rss_mb() - rss0
    print(f"\nket thuc sau {el:.1f} phut", flush=True)
    print(f"  envelope : {n['env']}  ({n['env'] / (el * 60):.0f}/s)", flush=True)
    print(f"  RAM      : {rss0:.1f} -> {rss_mb():.1f} MB  ({grow:+.1f})", flush=True)
    print(f"  Qt tick  : {n['tick']} (ky vong ~{int(el * 600)})", flush=True)
    assert n["env"] > 0, "khong nhan duoc envelope nao"
    assert n["tick"] > el * 600 * 0.9, "vong lap Qt bi treo"
    assert grow < 60, f"RAM phinh {grow:.1f} MB — nghi ro ri"
    print("SOAK PASS", flush=True)
    win.disconnect()
    app.quit()


timer = QTimer()
timer.timeout.connect(sample)
timer.start(60_000)
sys.exit(app.exec())
