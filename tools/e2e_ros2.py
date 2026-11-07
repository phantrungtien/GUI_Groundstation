#!/usr/bin/env python3
"""Nghiem thu tren stack ROS2 that: task Chua chay qua bridge, va duong SiK/4G theo task.

`selfcheck.py` dung nguon MAVLink gia va WebSocket gia; `e2e_sik_4g.py` gia ca bridge.
File nay cam app vao SITL + MAVROS + ros2_bridge --spawn + node fire_mission THAT, voi
profile hai duong nhu may tinh bang:

  SiK  = tcp:127.0.0.1:5763 (SERIAL2 cua SITL)
  4G   = MAVROS fcu tcp:5762, gcs_url udp://@127.0.0.1:14550 -> app udpin 14550
  bridge ws://127.0.0.1:8765, --spawn

Kiem: bat task qua app -> bridge sinh fire_mission -> `mission.running` -> app sang 4G,
giu suot task; chua giao diem chay thi drone KHONG ARM; huy task -> ve SiK.
(Truoc 07/11/2026 bai nay dung mission_circle cua simtofly_mavros_sitl — node do van tu
ARM + cat canh khi laptop cam quyen, chi ngung stream setpoint. Da bo khoi bridge.)

Chay SITL tran nhu e2e_sitl.py (MAVProxy giu 5760), roi:

    source /opt/ros/humble/setup.bash; source ~/fire_drone_ws/install/setup.bash
    ros2 launch fire_drone mavros.launch.py fcu_url:=tcp://127.0.0.1:5762 \\
        gcs_url:=udp://@127.0.0.1:14550 &
    python3 tools/ros2_bridge.py --host 127.0.0.1 --spawn &
    python3 tools/e2e_ros2.py

Do 07/11/2026: 10/10, bat task -> 4G 0,4 s, huy -> SiK 0,4 s.
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

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--conn", default="tcp:127.0.0.1:5763", help="duong SiK")
ap.add_argument("--conn2", default="udpin:0.0.0.0:14550", help="duong 4G (MAVROS gcs_url)")
ap.add_argument("--remote", default="ws://127.0.0.1:8765")
args = ap.parse_args()

app = QApplication([])
import laptop.voice  # noqa: E402
laptop.voice.enabled = lambda: False
from core.field import REGISTRY  # noqa: E402
from laptop.app import MainWindow  # noqa: E402

TASK = "fire_mission"
v = REGISTRY.value
fails, logs = [], []


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def until(cond, secs):
    """So giay toi khi dieu kien dung, None neu het gio."""
    t0 = time.time()
    while time.time() - t0 < secs:
        wait(200)
        if cond():
            return round(time.time() - t0, 1)
    return None


def check(name, ok, note=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{note}]" if note else ""), flush=True)
    if not ok:
        fails.append(name)


win = MainWindow([])
b = win.touch
b.cmd.log.connect(lambda s, _sev: logs.append(s))


def path():
    b.refresh()
    return b.state.get("linkPath")


win.connect_to({"name": "SITL hai duong", "mode": "SIM", "sysid": 254,
                "conn": args.conn, "conn2": args.conn2, "remote": args.remote})
dt = until(lambda: v("heartbeat.mode") and win._lte_pending is None, 60)
check("SiK nghe FC, mo nua 4G/bridge", dt is not None, f"{dt} s")
dt = until(lambda: b.cmd.fc_ready()[0] is True and v("position.lat") is not None
           and v("mission.spawn") is True, 120)
check("FC san sang (PREARM ok, co vi tri), bridge --spawn", dt is not None,
      f"prearm={b.cmd.fc_ready()} lat={v('position.lat')} spawn={v('mission.spawn')}")
dt = until(lambda: path() == "SiK", 10)
check("chua task: di SiK", dt is not None, f"duong={path()}")
wait(3000)
check("chua task, SiK khoe: van SiK sau 3 s", path() == "SiK", f"duong={path()}")

n0 = len(logs)
b.task(TASK)
dt = until(lambda: v("mission.running") == TASK, 30)
check(f"bat task qua app -> bridge sinh {TASK}", dt is not None, f"{dt} s; log={logs[n0:]}")
dt = until(lambda: path() == "4G", 10)
check("task chay -> sang 4G", dt is not None, f"{dt} s, duong={path()}")
wait(5000)
check("giu 4G suot task (5 s)", path() == "4G", f"duong={path()}")
check("chua giao diem chay: drone KHONG ARM", v("heartbeat.armed") is False,
      f"armed={v('heartbeat.armed')} mode={v('heartbeat.mode')}")

b.task("")
dt = until(lambda: v("mission.running") == "", 20)
check("huy task -> bridge bao running ''", dt is not None, f"{dt} s")
dt = until(lambda: path() == "SiK", 10)
check("task xong -> ve SiK", dt is not None, f"{dt} s, duong={path()}")

print("\ne2e_ros2:", "PASS" if not fails else f"FAIL {fails}", flush=True)
win.disconnect()
os._exit(1 if fails else 0)  # thread pymavlink/WebSocket cua app con treo socket
