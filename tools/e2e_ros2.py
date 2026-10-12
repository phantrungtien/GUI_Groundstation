#!/usr/bin/env python3
"""Nghiem thu N3 tren stack ROS2 that — khong mot manh gia lap nao.

`selfcheck.py` dung nguon MAVLink gia va WebSocket gia: no chung minh ma nguon
dung, khong chung minh he thong dung. File nay cam app vao dung cai drone ma
node ROS2 dinh bay, va do dung mot thu: node do KHONG LAI DUOC.

Truoc day bai test nay do duong NHUONG QUYEN (giao quyen cho ROS2 roi bam nut do
giat lai). Khong con duong do nua — laptop cam toan quyen, `/gcs/authority` chot
cung o "gcs" ngay luc bridge khoi dong (xem core/authority.py). Nen cau hoi doi
thanh: khoi dong node nhiem vu ra thi no co chiu dung yen khong, va laptop co bay
duoc suot trong luc no dang chay khong.

Chay SITL + MAVROS truoc, KHONG khoi dong node mission khac. Co the dung SITL
tran nhu e2e_sitl.py; bai nay khong can camera hay cua so Gazebo. Voi SITL -I0,
MAVProxy giu 5760, MAVROS noi tcp://127.0.0.1:5762 va xin stream telemetry:

    ros2 launch simtofly_mavros_sitl mavros_apm.launch.py fcu_url:=tcp://127.0.0.1:5762
    ros2 service call /mavros/set_stream_rate mavros_msgs/srv/StreamRate \
        '{stream_id: 0, message_rate: 10, on_off: true}'

roi cau noi ROS2 -> WebSocket (that ra chay tren companion; o day cung may):

    source /opt/ros/humble/setup.bash
    source ~/ros2-ardupilot-sitl-hardware/install/setup.bash
    python3 tools/ros2_bridge.py --host 127.0.0.1

roi:

    python3 tools/e2e_ros2.py [--conn tcp:127.0.0.1:5763] [--remote ws://127.0.0.1:8765]

Cong nao cam vao dau: MAVProxy giu TCP 5760, MAVROS giu TCP 5762 (hoac UDP 14550
neu chay Gazebo), nua SiK cam vao 5763. Doi --conn/--remote khi dung instance rieng.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.adapters.sik import STALE  # noqa: E402
from core.field import REGISTRY  # noqa: E402
from core.i18n import t  # noqa: E402
from laptop.app import MainWindow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--conn", default="tcp:127.0.0.1:5763")
parser.add_argument("--remote", default="ws://127.0.0.1:8765")
args = parser.parse_args()
CONN, WS = args.conn, args.remote
ROS = (
    "source /opt/ros/humble/setup.bash; "
    "source $HOME/ros2-ardupilot-sitl-hardware/install/setup.bash; "
)
AUTH_LOG = ROOT / "logs" / "e2e-authority.txt"
MISSION_LOG = ROOT / "logs" / "e2e-mission.log"

# mission_circle chu khong phai mission_simple: no stream setpoint 30 Hz suot ~31s
# roi moi tu RTL. mission_simple tu goi RTL o Step 6, nen khi FC doi sang RTL ta
# khong phan biet duoc la do nut do hay do chinh no — bai test se vo nghia.
MISSION = "mission_circle"

app = QApplication([])
import laptop.voice
laptop.voice.enabled = lambda: False
win = MainWindow([{"name": "SITL qua stack ROS2", "mode": "SIM", "conn": CONN,
                   "remote": WS, "sysid": 254}])
win.show()
assert win.panel.select("SITL qua stack ROS2")
win.panel.btn_connect.click()

ct = win.control_tab
logs = []
# log = Signal(str, int): noi thang `logs.append` thi moi dong TypeError, `logs` rong.
ct.log.connect(lambda text, _sev: logs.append(text))
procs = []


def sh(cmd, out=None):
    p = subprocess.Popen(["bash", "-c", ROS + "exec " + cmd],
                         stdout=out or subprocess.DEVNULL,
                         stderr=subprocess.STDOUT, start_new_session=True)
    procs.append(p)
    return p


def alive(src):
    seen = win.link_status.last_seen.get(src)
    return seen is not None and time.time() - seen < STALE


def val(field):
    return REGISTRY.best(field)[0]


def cleanup(recover=False):
    timer.stop()
    for p in procs:
        try:
            # Chi dung nhom do bai test tao; pkill -f giet ca mission cua phien khac.
            os.killpg(p.pid, signal.SIGTERM)
            p.wait(timeout=3)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
    if recover and val("heartbeat.armed") is True:
        print("  ..  test hong khi dang ARM -> RTL, cho disarm", flush=True)
        ct.btn_rtl.click()
        deadline = time.monotonic() + 120
        while val("heartbeat.armed") is not False and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.05)
        print(f"  ..  sau RTL: armed={val('heartbeat.armed')}", flush=True)
    win.disconnect()
    win.close()


def die(why):
    print(f"\ne2e_ros2: FAIL — {why}")
    cleanup(recover=True)
    app.exit(1)


# ---------------------------------------------------------------------------


def script():
    """Moi `yield` la (ten, dieu kien, so giay toi da cho)."""

    yield "hai nua deu co goi ve", lambda: alive("sik") and alive("remote"), 30
    print(f"  ok  SiK {win.link_status.bps.get('sik')} B/s"
          f"  ·  Remote {win.link_status.bps.get('remote')} B/s")

    # Hai duong doc cung mot drone. Lech nhieu la mot ben sai he toa do, dung
    # bay that roi moi phat hien (bay 7.3 cua ke hoach).
    yield "co du lieu vi tri tu ca hai nguon", (
        lambda: REGISTRY.position_divergence_m() is not None), 20
    div = REGISTRY.position_divergence_m()
    assert div < 5.0, f"hai nguon lech {div:.1f} m — nghi sai he toa do"
    print(f"  ok  SiK va MAVROS lech {div:.2f} m (nguong 5 m)")

    # Moi bai tu quan ly node cua minh; nguoi chay can dung mission khac truoc.
    if val("heartbeat.armed"):
        print("  ..  drone dang bay san (mission cua launch) -> RTL cho ve da")
        ct.btn_rtl.click()
    yield "drone ha canh, disarm xong", lambda: val("heartbeat.armed") is False, 180
    # PYTHONUNBUFFERED: bai test doc tien do qua log nay. Khong co no thi python
    # block-buffer 8 KB khi stdout la file, va dieu kien cho khong bao gio thay chu.
    # Topic nay TRANSIENT_LOCAL nen gia tri chot con lai cho nguoi vao sau, nhung
    # `ros2 topic echo` mac dinh subscribe VOLATILE — QoS lech thi khong nhan duoc
    # gi. Phai xin durability khop. Khong bam nut nao ca: gia tri phai co san tu
    # luc bridge khoi dong.
    sh("timeout 25 ros2 topic echo --once --qos-durability transient_local "
       "--qos-reliability reliable /gcs/authority std_msgs/msg/String",
       out=open(AUTH_LOG, "w"))
    yield "doc duoc /gcs/authority da chot", (
        lambda: "data: gcs" in AUTH_LOG.read_text()), 20
    print("  ok  /gcs/authority latch san 'gcs' — khong ai bam gi de co no")

    sh(f"env PYTHONUNBUFFERED=1 ros2 run simtofly_mavros_sitl {MISSION}",
       out=open(MISSION_LOG, "w"))
    print(f"  ..  da khoi dong {MISSION} — no phai TU DUNG, khong bay duoc")

    # --- day la ca bai test -------------------------------------------------
    # Node khoi dong ra, doc thay minh khong cam quyen, va dung yen. Kiem bang
    # HAI thu doc lap: log cua chinh no, va cai drone co nhac len khoi mat dat
    # hay khong. Chi tin mot cai thi mot ben noi doi la bai test qua.
    yield "cho node du thoi gian de cat canh neu no dinh cat", (
        lambda t0=time.time(): time.time() - t0 > 20), 30
    log = MISSION_LOG.read_text()
    assert "dung stream setpoint" in log, \
        "node khong he nhan duoc /gcs/authority — kiem tra QoS hai dau"
    assert "flying circle" not in log, "node VAN bay du khong cam quyen — kich ban hong #5"
    assert val("heartbeat.armed") is False, \
        f"drone da ARM ma khong ai o laptop bam gi (cao {val('position.alt_rel')} m)"
    print("  ok  node ROS2 nam yen: khong ARM, khong stream setpoint")

    # Va laptop van bay duoc sau khi node do da khoi dong.
    logs.clear()
    ct.mode_box.setCurrentText("GUIDED")
    ct.btn_mode.click()
    yield "FC vao GUIDED", lambda: val("heartbeat.mode") == "GUIDED", 15
    ct.btn_arm.click()
    yield "drone ARM", lambda: val("heartbeat.armed") is True, 15
    ct.alt.setValue(10)
    ct.btn_takeoff.click()
    yield "drone len toi 8 m", lambda: (val("position.alt_rel") or 0) > 8.0, 90
    alt = val("position.alt_rel")
    print(f"  ok  laptop cat canh duoc len {alt:.1f} m sau khi khoi dong node ROS2")

    logs.clear()
    ct.btn_rtl.click()
    assert logs[-1] == t("log.sent", what="RTL"), logs
    yield "FC nhan RTL", lambda: val("heartbeat.mode") == "RTL", 15
    yield "drone thuc su ha do cao", (
        lambda: (val("position.alt_rel") or 99) < alt - 1.0), 60
    yield "drone ve toi nha va disarm", lambda: val("heartbeat.armed") is False, 180
    print("  ok  RTL hoan tat — drone ve nha, disarm")

    print("\ne2e_ros2: PASS")
    cleanup()
    app.quit()


# --- vong lap chay `script()` ----------------------------------------------

steps = script()
pending = None


def tick():
    global pending
    try:
        if pending is None:
            pending = (*next(steps), time.time())
            print(f"  ..  cho: {pending[0]}")
            return
        name, cond, limit, since = pending
        if cond():
            pending = None
        elif time.time() - since > limit:
            die(f"qua {limit:.0f}s van chua: {name}")
    except StopIteration:
        pass
    except Exception as e:
        die(f"{type(e).__name__}: {e}")


timer = QTimer()
timer.timeout.connect(tick)
timer.start(500)
sys.exit(app.exec())
