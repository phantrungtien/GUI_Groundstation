#!/usr/bin/env python3
"""Cau noi ROS2 -> WebSocket. Chay tren COMPANION, khong phai tren laptop.

    source /opt/ros/humble/setup.bash
    python3 tools/ros2_bridge.py [--port 8765]

Subscribe topic MAVROS roi day envelope JSON (docs/protocol.md) qua WebSocket
cho `RemoteAdapter` cua laptop. Chieu nguoc lai: nhan {"action": ...} tu laptop,
publish `/gcs/authority` de node offboard biet luc nao phai nhuong quyen (2.4).

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
from mavros_msgs.msg import State
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import BatteryState, NavSatFix
from std_msgs.msg import Float64, String
from websockets.sync.server import serve

# Node nhiem vu ma bridge duoc phep khoi dong. DANH SACH TRANG, khong phai loc:
# bridge nhan lenh qua WebSocket tu ngoai mang, cho chay ten tuy y la mo cua cho
# bat ky ai vao WiFi bai bay chay lenh tren companion. Them mission moi thi them
# ten vao day — mot dong, va la mot lan can nhac co y thuc.
MISSION_PKG = "simtofly_mavros_sitl"
MISSIONS_OK = {"mission_simple", "mission_circle", "mission_gates",
               "trackinghuman", "verify_frame"}

# MAVROS phat telemetry o BEST_EFFORT; dat RELIABLE la khong nhan duoc goi nao.
SENSOR_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    durability=QoSDurabilityPolicy.VOLATILE,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=10,
)


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
    def __init__(self, spawn=False):
        super().__init__("gcs_ws_bridge")
        self.spawn = spawn
        self.ws_clients = set()
        self.lock = threading.Lock()
        self.sent = 0

        self.authority_pub = self.create_publisher(String, "/gcs/authority", 10)
        # Moi lenh khac tu laptop di ra day nguyen dang JSON. Node nhiem vu tu doc
        # va tu quyet — laptop KHONG gui setpoint, khong tranh luong 30 Hz voi ai.
        # Doi nhiem vu la doi trang thai ben trong node dang so huu luong do; chen
        # mot lenh GUIDED tu ngoai vao thi 33 ms sau bi chinh luong do de len.
        self.command_pub = self.create_publisher(String, "/gcs/command", 10)

        # Tien trinh nhiem vu dang chay, neu bridge la nguoi khoi dong no.
        self.mission_proc = None
        self.mission_pgid = None
        self.mission_name = ""
        self.create_timer(1.0, self._report_mission)

        self.create_subscription(NavSatFix, "/mavros/global_position/global",
                                 self._on_fix, SENSOR_QOS)
        self.create_subscription(PoseStamped, "/mavros/local_position/pose",
                                 self._on_pose, SENSOR_QOS)
        self.create_subscription(TwistStamped, "/mavros/local_position/velocity_local",
                                 self._on_vel, SENSOR_QOS)
        self.create_subscription(Float64, "/mavros/global_position/compass_hdg",
                                 self._on_hdg, SENSOR_QOS)
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
        self.push("local", {"x_e": p.x, "y_n": p.y, "z_u": p.z})
        self.push("attitude", {"roll": roll, "pitch": pitch, "yaw": yaw})
        self.push("position", {"alt_rel": p.z})  # MAVROS: z ENU = cao so voi diem khoi

    def _on_vel(self, m):
        v = m.twist.linear
        self.push("position", {"v_e": v.x, "v_n": v.y, "v_u": v.z})

    def _on_hdg(self, m):
        self.push("attitude", {"heading": m.data})

    def _on_batt(self, m):
        self.push("battery", {
            "voltage": None if math.isnan(m.voltage) else m.voltage,
            "current": None if math.isnan(m.current) else abs(m.current),
            "remaining": None if math.isnan(m.percentage) else round(m.percentage * 100),
        })

    def _on_state(self, m):
        self.push("heartbeat", {"armed": m.armed, "mode": m.mode})

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
            # Giu topic rieng: node offboard chi can nghe mot chuoi de biet luc nao
            # phai nhuong quyen, khong phai phan tich JSON (nguyen tac 2.4).
            who = str(msg.get("args", {}).get("value", ""))
            self.authority_pub.publish(String(data=who))
            self.get_logger().info(f"/gcs/authority -> {who}")
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
        self._stop_mission()
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
        self.mission_proc = subprocess.Popen(
            ["ros2", "run", MISSION_PKG, name], start_new_session=True
        )
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

    def _stop_mission(self):
        if self.mission_proc is None:
            return
        pgid, self.mission_proc, self.mission_name = self.mission_pgid, None, ""
        for sig, cho in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 1.0)):
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                break
            het = time.time() + cho
            while time.time() < het:
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
            self.push("text", {"severity": 4,
                               "text": f"nhiem vu {self.mission_name} da ket thuc (ma {code})"})
            self.mission_proc, self.mission_name = None, ""
        self.push("mission", {"running": self.mission_name,
                              "spawn": bool(self.spawn)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--spawn", action="store_true",
                    help="cho phep laptop khoi dong node nhiem vu (danh sach trang MISSIONS_OK)")
    args = ap.parse_args()

    rclpy.init()
    node = Bridge(spawn=args.spawn)

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
        rclpy.shutdown()


if __name__ == "__main__":
    main()
