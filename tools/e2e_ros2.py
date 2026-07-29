#!/usr/bin/env python3
"""Nghiem thu N3 tren stack ROS2 that — khong mot manh gia lap nao.

`selfcheck.py` dung nguon MAVLink gia va WebSocket gia: no chung minh ma nguon
dung, khong chung minh he thong dung. File nay cam app vao dung cai drone ma
node ROS2 dang bay, roi bam nut do — kich ban hong #5.

Chay stack truoc (moi cua so mot terminal):

    ros2 launch simtofly_mavros_sitl sitl_mission.launch.py

roi cau noi ROS2 -> WebSocket (that ra chay tren companion; o day cung may):

    source /opt/ros/humble/setup.bash
    source ~/ros2-ardupilot-sitl-hardware/install/setup.bash
    python3 tools/ros2_bridge.py --host 127.0.0.1

roi:

    python3 tools/e2e_ros2.py

Cong nao cam vao dau: MAVProxy giu TCP 5760, MAVROS giu UDP 14550. SITL con mo
san 5762/5763 — nua SiK cam vao 5763. Khong phai sua launch file cua ben ROS2.
"""

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import authority  # noqa: E402
from core.adapters.sik import STALE  # noqa: E402
from core.field import REGISTRY  # noqa: E402
from laptop.app import MainWindow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONN = "tcp:127.0.0.1:5763"
WS = "ws://127.0.0.1:8765"
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
win = MainWindow([{"name": "SITL qua stack ROS2", "mode": "SIM", "conn": CONN,
                   "remote": WS, "sysid": 254}])
win.show()
win.panel.list.setCurrentRow(0)
win.panel.btn_connect.click()

ct = win.control_tab
logs = []
ct.log.connect(logs.append)
procs = []


def sh(cmd, out=None):
    p = subprocess.Popen(["bash", "-c", ROS + cmd], stdout=out or subprocess.DEVNULL,
                         stderr=subprocess.STDOUT)
    procs.append(p)
    return p


def alive(src):
    seen = win.link_status.last_seen.get(src)
    return seen is not None and time.time() - seen < STALE


def val(field):
    return REGISTRY.best(field)[0]


def cleanup():
    for p in procs:
        p.terminate()
    # p.terminate() chi giet cai vo `bash -c`, node python song tiep. Va phai khop
    # dung ten mission dang chay: mot lan de sot `mission_circle`, no stream velocity
    # setpoint 30 Hz them ca tieng dong ho — moi lenh TAKEOFF sau do deu duoc FC
    # nhan roi bi chinh cai stream do de len, drone nam im tren dat.
    subprocess.run(["pkill", "-f", MISSION], check=False)
    win.disconnect()
    win.close()


def die(why):
    print(f"\ne2e_ros2: FAIL — {why}")
    cleanup()
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

    # Mission cua launch da bay xong tu truoc; can mot chuyen moi de con dang
    # bay luc bam nut do.
    subprocess.run(["pkill", "-f", "mission_"], check=False)
    yield "drone ha canh, disarm xong", lambda: val("heartbeat.armed") is False, 120
    # PYTHONUNBUFFERED: bai test doc tien do qua log nay. Khong co no thi python
    # block-buffer 8 KB khi stdout la file, va dieu kien cho khong bao gio thay chu.
    sh(f"PYTHONUNBUFFERED=1 ros2 run simtofly_mavros_sitl {MISSION}",
       out=open(MISSION_LOG, "w"))
    print(f"  ..  da khoi dong {MISSION} (ROS2 cam quyen bay)")

    yield "node ROS2 dang stream setpoint", (
        lambda: "flying circle" in MISSION_LOG.read_text()
        and (val("position.alt_rel") or 0) > 8.0), 180
    print(f"  ok  drone dang bay o {val('position.alt_rel'):.1f} m, mode "
          f"{val('heartbeat.mode')} — node ROS2 stream setpoint 30 Hz")

    # Nguoi bay giao quyen cho ROS2. Tu day lenh thuong phai bi tu choi.
    ct.auto.setChecked(True)
    logs.clear()
    ct.btn_takeoff.click()
    assert "TU CHOI" in logs[-1], logs
    print(f"  ok  quyen thuoc ROS2 -> \"{logs[-1]}\"")

    # Nghe /gcs/authority truoc khi bam: topic nay khong latch.
    sh("timeout 25 ros2 topic echo /gcs/authority", out=open(AUTH_LOG, "w"))
    # `ros2 topic echo` mat vai giay moi subscribe xong; bam som hon thi mat goi.
    yield "may nghe /gcs/authority san sang", (
        lambda t0=time.time(): time.time() - t0 > 5), 15

    alt_at_press = val("position.alt_rel")
    mode_at_press = val("heartbeat.mode")
    mission_at_press = MISSION_LOG.read_text()
    # Neu node da tu RTL truoc thi bai test khong con chung minh duoc gi.
    assert "circle complete" not in mission_at_press, "node da tu RTL truoc khi bam"
    logs.clear()
    ct.btn_rtl.click()

    # --- day la ca bai test -------------------------------------------------
    assert "da gui" in logs[-1], logs
    assert authority.AUTHORITY == authority.GCS, "nut do phai keo quyen ve GCS (2.4)"
    assert ct.manual.isChecked(), "switch phai nhay ve MANUAL theo quyen thuc te"
    print(f"  ok  bam RTL luc dang o mode {mode_at_press}, cao {alt_at_press:.1f} m"
          f" -> \"{logs[-1]}\", quyen ve GCS")

    yield "FC nhan RTL", lambda: val("heartbeat.mode") == "RTL", 15
    after = MISSION_LOG.read_text()
    assert "circle complete" not in after, "node tu RTL trong luc do — khong ket luan duoc"
    still = after.count("laps ") - mission_at_press.count("laps ")
    print(f"  ok  FC doi sang RTL, va node ROS2 van in them {still} dong 'laps'"
          " sau khi bam -> no VAN DANG stream setpoint")
    if still > 0:
        print("  !!  node offboard KHONG nhuong quyen theo /gcs/authority"
              " (hang muc N3 con lai ben companion). FC bo qua setpoint o mode RTL"
              " nen drone van ve nha — nhung do la ArduPilot cuu, khong phai thoa thuan.")

    yield "drone thuc su ha do cao", (
        lambda: (val("position.alt_rel") or 99) < alt_at_press - 1.0), 60
    print(f"  ok  do cao tut tu {alt_at_press:.1f} m xuong {val('position.alt_rel'):.1f} m")

    yield "drone ve toi nha va disarm", lambda: val("heartbeat.armed") is False, 180
    print("  ok  RTL hoan tat — drone ve nha, disarm")

    heard = AUTH_LOG.read_text()
    if "gcs" in heard:
        print("  ok  /gcs/authority nhan duoc 'gcs'")
    else:
        print("  !!  /gcs/authority KHONG thay 'gcs' — kiem tra lai ros2_bridge")

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
    except AssertionError as e:
        die(str(e))


timer = QTimer()
timer.timeout.connect(tick)
timer.start(500)
sys.exit(app.exec())
