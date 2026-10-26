#!/usr/bin/env python3
"""Cau noi ROS2 -> WebSocket. Chay tren COMPANION, khong phai tren laptop.

    source /opt/ros/humble/setup.bash
    python3 tools/ros2_bridge.py [--port 8765]

Subscribe topic MAVROS roi day envelope JSON (docs/protocol.md) qua WebSocket
cho `RemoteAdapter` cua laptop.

`/gcs/authority` publish DUNG MOT LAN luc khoi dong, gia tri "gcs", va khong co
duong nao doi duoc no nua: laptop cam toan quyen (xem core/authority.py). Node
offboard doc topic nay se thay minh khong bao gio duoc lai. Chot cung o day chu
khong bo han topic la co y — bo han thi node roi vao mac dinh cua chinh no, ma
mac dinh do khong nam trong repo nay.

Vi sao can file nay: MAVROS phat topic ROS2, no khong mo WebSocket nao. Khong co
mieng ghep nay thi laptop khong the noi chuyen voi nua ROS2 — va laptop thi
KHONG cai ROS2 (nguyen tac muc 1.4).

MAVROS da tra du lieu o he ENU nen khong phai doi he toa do o day. Doi chieu voi
`normalize()` ben `core/adapters/sik.py`: cung ten field, cung don vi.
"""

import argparse
import json
import math
import os
import signal
import subprocess
import threading
import time

import rclpy
from geometry_msgs.msg import PoseStamped, TwistStamped
from mavros_msgs.msg import HomePosition, State
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import BatteryState, NavSatFix
from std_msgs.msg import Float64, String
from websockets.sync.server import serve

# Node nhiem vu ma bridge duoc phep khoi dong. DANH SACH TRANG, khong phai loc:
# bridge nhan lenh qua WebSocket tu ngoai mang, cho chay ten tuy y la mo cua cho
# bat ky ai vao WiFi bai bay chay lenh tren companion. Them mission moi thi them
# ten vao day — mot dong, va la mot lan can nhac co y thuc.
# Ten node -> package ROS2 chua no. Dict LITERAL: tools/selfcheck.py doc no bang
# ast.literal_eval de khoi import rclpy.
#
# fire_mission = task Chua chay (~/fire_drone_ws): node tu lai sau khi nguoi bay
# bat task va chi diem chay — ngoai le co y cua nguyen tac 2.1, xem
# core/authority.py. Bridge phai chay trong moi truong da
# `source ~/fire_drone_ws/setup.bash` thi `ros2 run fire_drone ...` moi thay goi.
MISSIONS_OK = {
    "mission_simple": "simtofly_mavros_sitl",
    "mission_circle": "simtofly_mavros_sitl",
    "mission_gates": "simtofly_mavros_sitl",
    "trackinghuman": "simtofly_mavros_sitl",
    "verify_frame": "simtofly_mavros_sitl",
    "fire_mission": "fire_drone",
}

# MAVROS phat telemetry o BEST_EFFORT; dat RELIABLE la khong nhan duoc goi nao.

SENSOR_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    durability=QoSDurabilityPolicy.VOLATILE,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=10,
)


# Task dung ngang (Huy task / node chet) ma drone con arm + GUIDED: FC giu setpoint cuoi,
# KHONG AI LAI. User chot 27/10/2026: treo + bao len GUI, bridge KHONG doi mode (bridge chi
# la nguon telemetry, core/authority.py) - lay lai la viec nguoi bay qua SiK.
# Man bay chi giu dong do 10 s (laptop/widgets/alerts.py TTL_ERR) -> nhac moi 5 s.
HANG_EVERY = 5.0
# ponytail: nhac toi da 30 s - sau Huy task nguoi bay co the dung "bay toi day" (cung GUIDED,
# lenh di SiK) ma bridge khong phan biet duoc. Muon nhac toi luc lay lai that thi phai nhin
# thay lenh goto do.
HANG_FOR = 30.0


def hang_step(hang, armed, mode, running, now):
    """-> (hang moi, chu can day len hoac None). hang = (ly do, luc bat dau, lan nhac cuoi)."""
    if not hang:
        return None, None
    why, t0, last = hang
    if not armed or mode != "GUIDED" or running or now - t0 > HANG_FOR:
        return None, None  # da lay lai (doi mode / disarm), co task moi, hoac het han nhac
    if now - last < HANG_EVERY:
        return hang, None
    return (why, t0, now), f"{why}: drone TREO o GUIDED, khong ai lai - doi mode / RC de lay lai"


# Tham so cua fire_mission -> ten field GUI doc (topic `mission`, laptop/touch/backend.py).
FIRE_ALT_KEYS = {"alt_min": "min_alt", "alt_max": "max_alt",
                 "alt_search": "search_alt", "alt_drop": "drop_alt",
                 "radius_def": "search_radius", "radius_max": "max_search_radius"}


def fire_alt_limits(params_file):
    """Gioi han do cao / pham vi tim cua task Chua chay doc tu CUNG file --mission-params node
    dung, de GUI dua nut chon do cao bay / ha cach lua / pham vi tim theo drone dang noi (drone
    that 2-5 m) ma khong chep so sang GUI. Khong co file (sim) = {} -> GUI dung so mac dinh cua node."""
    if not params_file:
        return {}
    import yaml  # PyYAML di kem ROS; chi can khi co file
    with open(params_file) as f:
        p = (yaml.safe_load(f) or {}).get("fire_mission", {}).get("ros__parameters", {})
    return {k: float(p[n]) for k, n in FIRE_ALT_KEYS.items() if n in p}


def quat_to_euler(x, y, z, w):
    """Quaternion -> (roll, pitch, yaw) radian, he ENU."""
    sinr = 2 * (w * x + y * z)
    cosr = 1 - 2 * (x * x + y * y)
    roll = math.atan2(sinr, cosr)
    sinp = 2 * (w * y - z * x)
    pitch = math.asin(max(-1.0, min(1.0, sinp)))
    siny = 2 * (w * z + x * y)
    cosy = 1 - 2 * (y * y + z * z)
    return roll, pitch, math.atan2(siny, cosy)


class Bridge(Node):
    def __init__(self, spawn=False, params=None, fire_alt=None):
        super().__init__("gcs_ws_bridge")
        self.spawn = spawn
        self.params = params  # --mission-params: YAML tham so cho node nhiem vu (drone that)
        self.fire_alt = fire_alt or {}  # xem fire_alt_limits
        self.ws_clients = set()
        self.lock = threading.Lock()
        self.sent = 0

        # TRANSIENT_LOCAL: quyen la TRANG THAI, khong phai luong. Nhiem vu khoi
        # dong SAU bridge van phai doc duoc — VOLATILE thi no khong nghe duoc gi
        # va stream setpoint ngay. Phai khop voi `authority_qos()` ben
        # guided_base.py, lech mot ben la DDS im het.
        self.authority_pub = self.create_publisher(
            String, "/gcs/authority",
            QoSProfile(reliability=QoSReliabilityPolicy.RELIABLE,
                       durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
                       history=QoSHistoryPolicy.KEEP_LAST, depth=1))
        # Chot mot lan, khong bao gio doi. Latch giu gia tri nay cho moi node vao
        # sau. Khong co ham nao ben duoi publish len topic nay nua — do la ca
        # dieu khoan an toan lan ly do file nay khong con nhan lenh "authority".
        self.authority_pub.publish(String(data="gcs"))
        # Moi lenh khac tu laptop di ra day nguyen dang JSON. Node nhiem vu tu doc
        # va tu quyet — laptop KHONG gui setpoint, khong tranh luong 30 Hz voi ai.
        # Doi nhiem vu la doi trang thai ben trong node dang so huu luong do; chen
        # mot lenh GUIDED tu ngoai vao thi 33 ms sau bi chinh luong do de len.
        self.command_pub = self.create_publisher(String, "/gcs/command", 10)

        # Tien trinh nhiem vu dang chay, neu bridge la nguoi khoi dong no.
        self.mission_proc = None
        self.mission_pgid = None
        self.mission_name = ""
        self.fc = None    # (armed, mode) tu /mavros/state; None = chua noi duoc FC lan nao
        self.hang = None  # xem hang_step
        self.create_timer(1.0, self._report_mission)

        self.create_subscription(NavSatFix, "/mavros/global_position/global",
                                 self._on_fix, SENSOR_QOS)
        self.create_subscription(PoseStamped, "/mavros/local_position/pose",
                                 self._on_pose, SENSOR_QOS)
        self.create_subscription(TwistStamped, "/mavros/local_position/velocity_local",
                                 self._on_vel, SENSOR_QOS)
        self.create_subscription(Float64, "/mavros/global_position/compass_hdg",
                                 self._on_hdg, SENSOR_QOS)
        # Do cao SO VOI HOME = GLOBAL_POSITION_INT.relative_alt, dung cai SiK day
        # len. KHONG lay z cua local_position/pose: do la so voi GOC EKF, va goc EKF
        # khong phai home — do that 04/10/2026 tren log bay that: lech trung vi
        # -2,8 m, co log -17,6 m (toi -24 m). Remote uu tien hon SiK, nen lay z la
        # o H tren man bay, uoc thoi gian ve nha va khoang cach toi tran rao deu sai.
        self.create_subscription(Float64, "/mavros/global_position/rel_alt",
                                 self._on_rel_alt, SENSOR_QOS)
        # ...NHUNG chi khi FC da co home. Chua co (khong GPS) thi rel_alt la baro
        # tho, con FC giu do cao bang z EKF — lay z, giong het sik.py (bay that
        # 11/10/2026: baro lech rangefinder trung vi 0,40 m, EKF 0,03 m).
        self.home_seen = False
        self.create_subscription(HomePosition, "/mavros/home_position/home",
                                 self._on_home, SENSOR_QOS)
        self.create_subscription(BatteryState, "/mavros/battery",
                                 self._on_batt, SENSOR_QOS)
        self.create_subscription(State, "/mavros/state", self._on_state, 10)


    # --- day len laptop ---------------------------------------------------

    def push(self, topic, data):
        env = json.dumps({"src": "remote", "topic": topic, "data": data, "ts": time.time()})
        with self.lock:
            dead = set()
            for ws in self.ws_clients:
                try:
                    ws.send(env)
                except Exception:
                    dead.add(ws)
            self.ws_clients -= dead
        self.sent += 1

    def _on_fix(self, m):
        if math.isnan(m.latitude):
            return
        self.push("position", {"lat": m.latitude, "lon": m.longitude, "alt_msl": m.altitude})

    def _on_pose(self, m):
        p, q = m.pose.position, m.pose.orientation
        roll, pitch, yaw = quat_to_euler(q.x, q.y, q.z, q.w)
        self.push("local", {"x_e": p.x, "y_n": p.y, "z_u": p.z})  # so voi GOC EKF
        if not self.home_seen:
            self.push("position", {"alt_rel": p.z})
        self.push("attitude", {"roll": roll, "pitch": pitch, "yaw": yaw})

    def _on_rel_alt(self, m):
        if self.home_seen:
            self.push("position", {"alt_rel": m.data})

    def _on_home(self, m):
        self.home_seen = True

    def _on_vel(self, m):
        v = m.twist.linear
        self.push("position", {"v_e": v.x, "v_n": v.y, "v_u": v.z})

    def _on_hdg(self, m):
        self.push("attitude", {"heading": m.data})

    def _on_batt(self, m):
        self.push("battery", {
            "voltage": None if math.isnan(m.voltage) else m.voltage,
            "current": None if math.isnan(m.current) else abs(m.current),
            # FC khong biet % (battery_remaining = -1, vd BATT_CAPACITY = 0) thi
            # MAVROS dua -0,01 chu khong NaN — do that 04/10/2026. Day len nguyen
            # thi man bay hien "PIN -1%" do ruc va giong doc bao pin can. -1 la
            # "khong biet", giong het cach normalize() ben SiK xu ly.
            "remaining": (None if math.isnan(m.percentage) or m.percentage < 0
                          else round(m.percentage * 100)),
        })

    def _on_state(self, m):
        if m.connected:
            first, self.fc = self.fc is None, (m.armed, m.mode)
            if first:
                # service drone-ros (Jetson) khoi dong lai CA NHOM khi MAVROS/fire_locator/bridge
                # chet: task dang bay chet theo, bridge moi sinh ra khong biet gi ve no.
                self._hung("bridge vua khoi dong lai giua luc bay")
        self.push("heartbeat", {"armed": m.armed, "mode": m.mode})

    def _hung(self, why):
        """Bat dau nhac (hang_step) neu drone dang arm + GUIDED. True = dang treo."""
        armed, mode = self.fc or (False, "")
        if not (armed and mode == "GUIDED"):
            return False
        self.get_logger().error(f"{why}: drone treo GUIDED")
        self.hang = (why, time.time(), 0.0)
        return True

    # --- nhan lenh tu laptop ----------------------------------------------

    def handle_command(self, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        action = msg.get("action")
        if not action:
            return
        if action == "authority":
            # Quyen khong con chuyen qua chuyen lai. Ai do (ban web cu, mot script)
            # van gui thi TU CHOI TO — im lang bo qua thi ben kia tuong da nhan
            # duoc quyen va bat dau stream setpoint vao FC.
            self.get_logger().error(
                "tu choi doi /gcs/authority: laptop cam toan quyen, topic chot o 'gcs'")
            return
        self.command_pub.publish(String(data=json.dumps(msg, separators=(",", ":"))))
        self.get_logger().info(f"/gcs/command -> {action} {msg.get('args', {})}")
        if action == "mission" and self.spawn:
            self._run_mission(str(msg.get("args", {}).get("name", "")))

    # --- khoi dong node nhiem vu (tuy chon, xem --spawn) ------------------

    def _run_mission(self, name):
        """Ten rong = dung nhiem vu dang chay.

        Cach nay giet roi chay lai tien trinh, nen luong setpoint DUT vai giay giua
        hai nhiem vu — drone treo tai cho (GUIDED giu vi tri cuoi, xem GUID_TIMEOUT).
        Muon doi lien mach thi ba nhiem vu phai nam trong MOT node va doi bang bien
        trang thai; day la duong nhanh, khong phai duong dep.
        """
        self._stop_mission(cancel=not name)
        if not name:
            return
        if name not in MISSIONS_OK:
            self.get_logger().warn(f"tu choi khoi dong '{name}': khong co trong danh sach trang")
            return
        # Khong shell=True, khong noi chuoi: ten da qua danh sach trang roi van
        # truyen dang mang de khong co duong nao chen them lenh.
        #
        # start_new_session: `ros2 run` chi la VO — no sinh node that roi tu thoat.
        # Theo doi rieng pid cua vo thi thay no chet va tuong nhiem vu da xong,
        # trong khi node that van dang lai drone (do that: bridge bao running=''
        # ma hai node van song). Cho ca cum mot nhom rieng roi theo doi/giet ca
        # nhom moi dung.
        cmd = ["ros2", "run", MISSIONS_OK[name], name]
        # `ros2 run` tran = tham so MAC DINH cua node = so sim (fire_mission: vong tim 24 m,
        # bay 20 m, tran 120 m). Drone that phai co file nay, khong thi bay theo so sim.
        if self.params:
            cmd += ["--ros-args", "--params-file", self.params]
        self.mission_proc = subprocess.Popen(cmd, start_new_session=True)
        self.mission_pgid = os.getpgid(self.mission_proc.pid)
        self.mission_name = name
        self.get_logger().info(f"da khoi dong {name} (nhom {self.mission_pgid})")

    def _mission_alive(self):
        if self.mission_proc is None:
            return False
        self.mission_proc.poll()  # gat xac tien trinh vo, khong de zombie giu nhom
        try:
            os.killpg(self.mission_pgid, 0)  # signal 0 = chi hoi con song khong
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def _stop_mission(self, cancel=False):
        if self.mission_proc is None:
            return
        proc, pgid, name = self.mission_proc, self.mission_pgid, self.mission_name
        self.mission_proc, self.mission_name = None, ""
        if cancel:
            self._hung(f"Huy task {name}")  # bao NGAY, khong doi nhom chet
        for sig, cho in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 1.0)):
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                break
            het = time.time() + cho
            while time.time() < het:
                # Gat xac vo `ros2 run`: zombie van tinh la nhom con song -> lan Huy nao cung
                # doi het 5 s roi SIGKILL (do 27/10/2026: node thoat ngay, bridge bao sau 6 s).
                proc.poll()
                try:
                    os.killpg(pgid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                continue
            break
        self.get_logger().info(f"da dung nhiem vu (nhom {pgid})")

    def _report_mission(self):
        """Day trang thai nguoc len laptop moi giay.

        Khong co cai nay thi giao dien chi biet "da gui lenh", khong biet node co
        that su chay khong — dung kieu im lang ma muc 2.2 cam.
        """
        if not self._mission_alive() and self.mission_name:
            code = self.mission_proc.returncode if self.mission_proc else None
            self.get_logger().info(f"nhiem vu {self.mission_name} da tu ket thuc (ma {code})")
            # Bao len laptop, dung chi ghi log tren companion. Node thoat som la
            # chuyen thuong gap — vi du no doi khoi dong tu mat dat ma drone dang
            # bay san — va nguoi bay phai doc duoc ly do o tab Thong bao.
            if not self._hung(f"task {self.mission_name} chet giua chung (ma {code})"):
                self.push("text", {"severity": 4,
                                   "text": f"nhiem vu {self.mission_name} da ket thuc (ma {code})"})
            self.mission_proc, self.mission_name = None, ""
        self.hang, text = hang_step(self.hang, *(self.fc or (False, "")),
                                    self.mission_name, time.time())
        if text:
            self.push("text", {"severity": 2, "text": text})  # CRITICAL: dong do tren man bay
        self.push("mission", {"running": self.mission_name,
                              "spawn": bool(self.spawn), **self.fire_alt})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--spawn", action="store_true",
                    help="cho phep laptop khoi dong node nhiem vu (danh sach trang MISSIONS_OK)")
    ap.add_argument("--mission-params", default=None, metavar="YAML",
                    help="file tham so ROS cho node nhiem vu (--ros-args --params-file). "
                         "Drone that: ~/jetson/fire_mission_real.yaml")
    ap.add_argument("--selfcheck", action="store_true", help="kiem hang_step roi thoat")
    args = ap.parse_args()
    if args.selfcheck:
        return _selfcheck()
    if args.mission_params and not os.path.isfile(args.mission_params):
        ap.error(f"khong thay {args.mission_params}")  # thieu file = bay so sim, dung luon
    try:
        fire_alt = fire_alt_limits(args.mission_params)
    except Exception as e:  # YAML hong thi `ros2 run --params-file` cung chet: bao ngay o day
        ap.error(f"doc {args.mission_params} loi: {e}")

    rclpy.init()
    node = Bridge(spawn=args.spawn, params=args.mission_params, fire_alt=fire_alt)

    def on_client(ws):
        node.get_logger().info("laptop noi vao")
        with node.lock:
            node.ws_clients.add(ws)
        try:
            for raw in ws:
                node.handle_command(raw)
        except Exception:
            pass
        finally:
            with node.lock:
                node.ws_clients.discard(ws)
            node.get_logger().info("laptop ngat")

    server = serve(on_client, args.host, args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    node.get_logger().info(f"WebSocket mo o ws://{args.host}:{args.port}")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._stop_mission()  # khong de node nhiem vu song mo coi khi bridge chet
        server.shutdown()
        node.destroy_node()
        # try_: Ctrl-C thi bo bat tin hieu cua rclpy da tu shutdown context roi —
        # goi `shutdown()` lan nua la RCLError, traceback va ma thoat 1.
        rclpy.try_shutdown()


def _selfcheck():
    h = ("Huy task fire_mission", 100.0, 0.0)
    h1, txt = hang_step(h, True, "GUIDED", "", 100.5)
    assert txt and "TREO" in txt and h1[2] == 100.5, "lan dau phai bao ngay"
    assert hang_step(h1, True, "GUIDED", "", 103.0) == (h1, None), "chua toi 5 s thi chua nhac"
    assert hang_step(h1, True, "GUIDED", "", 105.6)[1], "5 s sau nhac lai"
    for armed, mode, running, now in [(True, "LOITER", "", 101.0),  # nguoi bay da doi mode
                                      (False, "GUIDED", "", 101.0),  # da disarm
                                      (True, "GUIDED", "fire_mission", 101.0),  # task moi
                                      (True, "GUIDED", "", 131.0)]:  # het 30 s
        assert hang_step(h1, armed, mode, running, now) == (None, None), (armed, mode, running, now)
    assert hang_step(None, True, "GUIDED", "", 0.0) == (None, None)

    import tempfile
    assert fire_alt_limits(None) == {}, "sim khong co file: GUI dung mac dinh cua node"
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as f:
        f.write("fire_mission:\n  ros__parameters:\n    search_alt: 5.0\n    min_alt: 2\n"
                "    max_alt: 5.0\n    drop_alt: 3.0\n    ring_step: 2.0\n"
                "    search_radius: 2.0\n    max_search_radius: 10\n")
        f.flush()
        assert fire_alt_limits(f.name) == {"alt_min": 2.0, "alt_max": 5.0,
                                           "alt_search": 5.0, "alt_drop": 3.0,
                                           "radius_def": 2.0, "radius_max": 10.0}
    print("ros2_bridge selfcheck OK")


if __name__ == "__main__":
    main()
