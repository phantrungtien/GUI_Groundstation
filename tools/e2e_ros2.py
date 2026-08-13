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

> ⚠️ Ban nay CHUA chay lai tren stack that sau khi doi mo hinh quyen. Con so cu
> (o docs/) la cua bai test cu.

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
assert win.panel.select("SITL qua stack ROS2")
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

    # Can mot chuyen bay MOI de con dang bay luc bam nut do, nen don bai truoc.
    # `pkill` mot mission dang bay do thi drone treo o GUIDED MAI MAI — GUIDED
    # khong tu ha canh, va khong con ai stream setpoint de bao no lam gi. Nen
    # phai chu dong goi no ve, khong thi buoc cho disarm duoi day treo het gio
    # va bai test bao FAIL trong khi chang co gi hong.
    subprocess.run(["pkill", "-f", "mission_"], check=False)
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
    sh("timeout 25 ros2 topic echo --qos-durability transient_local "
       "--qos-reliability reliable /gcs/authority", out=open(AUTH_LOG, "w"))
    yield "doc duoc /gcs/authority da chot", (
        lambda: "gcs" in AUTH_LOG.read_text()), 20
    print("  ok  /gcs/authority latch san 'gcs' — khong ai bam gi de co no")

    sh(f"PYTHONUNBUFFERED=1 ros2 run simtofly_mavros_sitl {MISSION}",
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

    # Va laptop thi bay duoc, ngay trong luc node do dang chay.
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
    print(f"  ok  laptop cat canh duoc len {alt:.1f} m trong luc node ROS2 dang chay")

    logs.clear()
    ct.btn_rtl.click()
    assert "da gui" in logs[-1], logs
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
    except AssertionError as e:
        die(str(e))


timer = QTimer()
timer.timeout.connect(tick)
timer.start(500)
sys.exit(app.exec())
