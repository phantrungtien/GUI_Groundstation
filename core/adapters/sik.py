"""SikAdapter — pymavlink trong QThread, chuan hoa NED -> ENU.

Mot adapter cho ca ba che do (REAL / SIM / REPLAY) vi mavlink_connection() nhan
moi chuoi ket noi: /dev/ttyUSB0, udp:..., tcp:..., hay mot file .tlog.
Xem Phu luc 7.6 cua ke hoach.

Quy tac thread: run() KHONG duoc cham widget Qt. Duong duy nhat ra ngoai la
signal `envelope` / `failed`.
"""

import math
import queue
import struct
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from pymavlink import mavutil

STALE = 2.0  # giay — qua nguong nay coi nhu link chet (Phu luc 7.4)

AUTOPILOT = mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1  # = 1


def from_autopilot(msg):
    """Goi nay co phai FC noi khong?

    Duong MAVLink khong chi co FC tren do. Do tren SITL cua stack ROS2: FC (1/1),
    MAVROS (1/191, kieu ONBOARD_COMPUTER — heartbeat cua no BAT san co ARMED) va
    MAVProxy (255/230, kieu GCS). Khong loc thi:

      - den ARM nhay armed/disarmed moi nua giay vi ba nguon xen ke nhau
      - pymavlink doi `target_component` sang 191 (post_message() lay tu bat ky
        heartbeat nao khong phai GCS) -> lenh gui di dia chi vao MAVROS

    RADIO_STATUS giu lai: tren SiK that no do chinh cai radio duoi dat chen vao
    (khong phai FC), va do la nguon RSSI duy nhat.

    Component 0 (MAV_COMP_ID_ALL) cung cho qua: mot so nguon gui don gian va log
    cu ghi nhu vay. Chan no thi REPLAY mot .tlog la ra man hinh trong tron — dung
    kieu hong ma muc 2.2 cam.
    """
    return msg.get_srcComponent() in (0, AUTOPILOT) or msg.get_type() == "RADIO_STATUS"

# (stream_id, Hz) — Phu luc 7.2
#
# Bon luong dau nuoi HUD, nen tan so cao. Ba luong sau nuoi tab Status: no la bang
# TRA CUU, khong phai HUD — 1 Hz la du, va doi lai thi khong con field nao cua FC
# bi giau. Khong xin thi tab Status vinh vien khong thay chung, ma nguoi dung lai
# tuong drone khong co cam bien do.
#
# Bang thong (Phu luc 7.1): bon luong dau ~800 B/s, ba luong sau ~500 B/s o 1 Hz.
# Tong ~1.3 kB/s tren duong SiK 57600 thuc te cho ~4-5 kB/s — con thua ba lan.
STREAMS = [
    (mavutil.mavlink.MAV_DATA_STREAM_EXTENDED_STATUS, 2),
    (mavutil.mavlink.MAV_DATA_STREAM_POSITION, 3),
    (mavutil.mavlink.MAV_DATA_STREAM_EXTRA1, 10),  # ATTITUDE
    (mavutil.mavlink.MAV_DATA_STREAM_EXTRA2, 4),  # VFR_HUD
    (mavutil.mavlink.MAV_DATA_STREAM_RAW_SENSORS, 1),  # IMU, ap suat, tu ke
    (mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS, 1),  # can dieu khien, ngo ra servo
    (mavutil.mavlink.MAV_DATA_STREAM_EXTRA3, 1),  # AHRS, EKF, rung, pin chi tiet
]

# Bit cam bien trong SYS_STATUS. Lay thang tu bang enum cua pymavlink chu khong
# go tay: doi ban MAVLink co them cam bien moi thi tu co, khong phai sua code.
SENSOR_BITS = {
    e.name.replace("MAV_SYS_STATUS_SENSOR_", "").replace("MAV_SYS_STATUS_", "").lower(): bit
    for bit, e in mavutil.mavlink.enums["MAV_SYS_STATUS_SENSOR"].items()
    if bit > 0 and bin(bit).count("1") == 1 and not e.name.endswith("ENUM_END")
}


def decode_sensors(d):
    """SYS_STATUS -> mot hang cho moi cam bien, doc duoc bang mat.

    Ba truong `onboard_control_sensors_*` la ba bitmask 32 bit. De nguyen thi tab
    Status hien "1467007" — dung ky thuat, vo dung voi nguoi bay. Cam bien nao
    HONG la thu phai doc duoc trong mot giay truoc khi cat canh.
    """
    present = d.get("onboard_control_sensors_present", 0)
    enabled = d.get("onboard_control_sensors_enabled", 0)
    health = d.get("onboard_control_sensors_health", 0)
    out = {}
    for name, bit in SENSOR_BITS.items():
        if not present & bit:
            continue  # khong lap tren may bay nay
        state = "TOT" if health & bit else "HONG"
        if not enabled & bit:
            state += " (tat)"
        out[f"SENSOR.{name}"] = state
    return out


def normalize(name, d):
    """MAVLink msg.to_dict() -> (topic, data) da doi don vi va ve ENU.

    Tra ve None voi message chua quan tam — chung van vao STATUS generic.
    Quy uoc ENU: x dong, y bac, z len (Phu luc 7.3).
    """
    if name == "GLOBAL_POSITION_INT":
        return "position", {
            "lat": d["lat"] / 1e7,
            "lon": d["lon"] / 1e7,
            "alt_msl": d["alt"] / 1000.0,
            "alt_rel": d["relative_alt"] / 1000.0,
            # NED cm/s -> ENU m/s
            "v_e": d["vy"] / 100.0,
            "v_n": d["vx"] / 100.0,
            "v_u": -d["vz"] / 100.0,
            "heading": d["hdg"] / 100.0 if d["hdg"] != 65535 else None,
        }

    if name == "ATTITUDE":
        # roll/pitch la goc than may bay, khong doi giua NED va ENU.
        # yaw NED do tu huong bac theo chieu kim dong ho; ENU do tu huong dong
        # nguoc chieu kim dong ho.
        return "attitude", {
            "roll": d["roll"],
            "pitch": d["pitch"],
            "yaw": (math.pi / 2 - d["yaw"] + math.pi) % (2 * math.pi) - math.pi,
            "heading": math.degrees(d["yaw"]) % 360.0,
            "rollspeed": d["rollspeed"],
            "pitchspeed": d["pitchspeed"],
        }

    if name == "LOCAL_POSITION_NED":
        return "local", {"x_e": d["y"], "y_n": d["x"], "z_u": -d["z"]}

    if name == "VFR_HUD":
        return "vfr", {
            "airspeed": d["airspeed"],
            "groundspeed": d["groundspeed"],
            "throttle": d["throttle"],
            "climb": d["climb"],
        }

    if name == "SYS_STATUS":
        v = d["voltage_battery"]
        c = d["current_battery"]
        return "battery", {
            "voltage": v / 1000.0 if v != 65535 else None,
            "current": c / 100.0 if c != -1 else None,
            "remaining": d["battery_remaining"] if d["battery_remaining"] != -1 else None,
        }

    if name == "GPS_RAW_INT":
        return "gps", {
            "fix_type": d["fix_type"],
            "sats": d["satellites_visible"],
            "hdop": d["eph"] / 100.0 if d["eph"] != 65535 else None,
        }

    if name == "STATUSTEXT":
        return "text", {"severity": d["severity"], "text": d["text"]}

    if name == "COMMAND_ACK":
        # Thieu cai nay thi app bao "da gui" trong khi FC da tu choi thang thung.
        return "ack", {"command": d["command"], "result": d["result"]}

    if name == "HEARTBEAT":
        armed = bool(d["base_mode"] & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        return "heartbeat", {"armed": armed, "type": d["type"]}

    return None


def flatten_status(name, d):
    """Moi field cua moi message -> STATUS["MSG.field"]. Khong hardcode gi ca.

    Truoc day chi giu int/float, tuc am tham nuot mat: mang (dien ap tung cell
    trong BATTERY_STATUS.voltages, tung kenh RC), chuoi (ten firmware, STATUSTEXT),
    va cac bitmask cam bien. "Doc duoc het trang thai" thi khong duoc bo thu nao.
    """
    d = dict(d)
    d.pop("mavpackettype", None)
    out = {}
    if name == "SYS_STATUS":
        out.update(decode_sensors(d))
    if name == "PARAM_VALUE":
        # Moi tham so mot hang rieng. De mac dinh thi ca 1431 tham so deu do vao
        # dung mot hang "PARAM_VALUE.param_value", cai sau de len cai truoc — nhin
        # thay mot con so nhay lien tuc ma khong biet la cua tham so nao.
        pid = d.get("param_id", "")
        if isinstance(pid, bytes):
            pid = pid.decode("utf-8", "replace")
        pid = pid.replace("\x00", "").strip()
        if pid:
            return {f"PARAM.{pid}": d.get("param_value")}
    for k, v in d.items():
        key = f"{name}.{k}"
        if isinstance(v, bool):
            out[key] = int(v)
        elif isinstance(v, (int, float)):
            out[key] = v
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                if isinstance(x, (int, float)):
                    out[f"{key}[{i}]"] = x
        elif isinstance(v, (str, bytes)):
            s = v.decode("utf-8", "replace") if isinstance(v, bytes) else v
            s = s.replace("\x00", "").strip()
            if s:
                out[key] = s
    return out


class SikAdapter(QThread):
    envelope = Signal(dict)  # {src, topic, data, ts} — noi vao bus o main thread
    failed = Signal(str)

    SRC = "sik"

    def __init__(self, profile, logdir=None, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.mode = profile["mode"]
        self.logdir = logdir
        self.tlog = None  # duong dan .tlog dang ghi, None neu khong ghi
        self._tlog_f = None
        self._running = True

        # Lenh di qua hang doi, khong ghi thang vao socket tu thread khac:
        # pymavlink dem seq trong mav.send(), hai thread cung ghi la hong goi.
        # Vong lap doc xong moi goi la vet ngay, nen do tre thuc te ~vai ms.
        self._cmds = queue.Queue()
        self._paused = threading.Event()  # chi dung o REPLAY
        self._seek = None  # 0..1, dat tu UI khi tua
        self.last_rx = 0.0  # lan cuoi thuc su nhan duoc goi tu drone
        self.percent = 0.0  # REPLAY: da phat den dau
        # Mo phong dut telemetry ma khong phai rut day: bo goi ca hai chieu, y nhu
        # radio ra ngoai tam song. Socket van mo, nen bo len la co du lieu ngay.
        self.muted = False

    def stop(self):
        self._running = False
        self._paused.clear()  # dang tam dung ma bam thoat thi phai thoat duoc
        self.wait(3000)

    # ---- dieu khien ------------------------------------------------------

    def send(self, action, args=None):
        """Xep lenh vao hang doi. Goi tu main thread.

        REPLAY khong co gi de gui lenh toi — tu choi thang, khong im lang bo qua.

        Link im lang thi VAN gui (nut do khong duoc phep bi chan), nhung phai bao
        `stale` len tren: "da xep lenh" khac "lenh da toi noi". Bang chung duy nhat
        lenh toi noi la COMMAND_ACK.
        """
        if self.mode == "REPLAY":
            return {"error": "che do REPLAY khong gui duoc lenh"}
        if not self.isRunning():
            return {"error": "duong SiK chua ket noi"}
        self._cmds.put((action, args or {}))
        silent = time.time() - self.last_rx if self.last_rx else None
        if silent is None or silent > STALE:
            return {"ok": action, "stale": silent}
        return {"ok": action}

    def pause(self, on=True):
        self._paused.set() if on else self._paused.clear()

    def seek(self, fraction):
        self._seek = max(0.0, min(1.0, fraction))

    def _maybe_seek(self, master):
        """Nhay toi vi tri fraction trong file .tlog.

        Nhay theo byte thi roi vao giua goi — bo phan tich MAVLink tu dong bo lai
        o header ke tiep, may goi rac dau tien ra BAD_DATA va bi bo qua.
        """
        if self._seek is None or self.mode != "REPLAY":
            return
        frac, self._seek = self._seek, None
        try:
            master.offset = int(frac * master.data_len)
            master.f.seek(master.offset)
        except AttributeError:
            return  # dinh dang log khong ho tro tua

    def _run_commands(self, master):
        while True:
            try:
                action, args = self._cmds.get_nowait()
            except queue.Empty:
                return
            try:
                self._exec(master, action, args)
            except Exception as e:
                self._emit("text", {"severity": 3, "text": f"lenh {action} loi: {e}"})

    def _exec(self, master, action, args):
        m = master.mav
        # compid ghim cung: `master.target_component` bi heartbeat cua MAVROS keo
        # sang 191 (xem from_autopilot). Lenh phai den FC, khong den companion.
        sysid, compid = master.target_system, AUTOPILOT

        if self.muted:
            return  # dut link la dut ca hai chieu, lenh cung khong di duoc

        if action == "param_read":
            # Hoi tung ten mot, khong PARAM_REQUEST_LIST: ca 1431 tham so qua SiK
            # 57600 la vai chuc giay chiem het duong truyen — trong luc do HUD dung.
            for pname in args["names"]:
                m.param_request_read_send(sysid, compid, pname.encode(), -1)
        elif action in ("arm", "disarm"):
            m.command_long_send(
                sysid, compid, mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0,
                1 if action == "arm" else 0,
                21196 if args.get("force") else 0, 0, 0, 0, 0, 0,
            )
        elif action == "takeoff":
            m.command_long_send(
                sysid, compid, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0,
                0, 0, 0, 0, 0, 0, float(args.get("alt", 5)),
            )
        elif action in ("rtl", "land", "mode"):
            # ArduCopter doi mode bang set_mode la duong chac an nhat
            name = {"rtl": "RTL", "land": "LAND"}.get(action) or args["name"]
            master.set_mode(name)
        elif action == "goto":
            m.mission_item_send(
                sysid, compid, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                mavutil.mavlink.MAV_CMD_NAV_WAYPOINT, 2, 0, 0, 0, 0, 0,
                float(args["lat"]), float(args["lon"]), float(args.get("alt", 10)),
            )
        else:
            raise ValueError(f"khong biet lenh {action!r}")
        self._emit("cmd", {"action": action, "args": args})

    def _emit(self, topic, data, ts=None):
        if self.muted:
            return  # dang mo phong dut telemetry — xem self.muted
        self.envelope.emit(
            {"src": self.SRC, "topic": topic, "data": data, "ts": ts or time.time()}
        )

    def _open(self):
        p = self.profile
        # autoreconnect: neu dau kia bien mat (SITL tat, TCP dut), pymavlink tu
        # noi lai, that bai 3 lan thi nem loi -> run() bao `failed`. Khong bat thi
        # mavtcp.reconnect() la no-op, recv() goi mai vao socket chet: quay tit
        # 100% CPU va in "EOF on TCP socket" khong ngung (do duoc ~1.1 trieu dong
        # trong 4 giay). Cong serial im lang KHONG kich hoat duong nay, nen radio
        # SiK ra ngoai tam song mot lat van giu nguyen ket noi.
        kw = {"source_system": p.get("sysid", 254), "autoreconnect": True}  # sysid rieng (2.3)
        if p["mode"] == "REPLAY":
            return mavutil.mavlink_connection(p["path"])
        if p.get("baud"):
            kw["baud"] = p["baud"]
        master = mavutil.mavlink_connection(p["conn"], **kw)

        # Ghi .tlog o moi che do, ke ca REAL — sau su co day thuong la thu duy
        # nhat cho biet chuyen gi da xay ra (Phu luc 7.6). Cung la dau vao REPLAY.
        #
        # KHONG dung master.setup_logfile(): mavudp.recv_msg ghi de ham goc va bo
        # mat doan ghi log, nen link UDP tao ra file 0 byte ma khong bao gi. Tu ghi
        # o vong lap thi serial/UDP/TCP deu giong nhau.
        if self.logdir:
            d = Path(self.logdir)
            d.mkdir(parents=True, exist_ok=True)
            self.tlog = d / f"{time.strftime('%Y%m%d-%H%M%S')}-{p['mode'].lower()}.tlog"
            self._tlog_f = open(self.tlog, "wb")
        return master

    def run(self):
        try:
            master = self._open()
        except Exception as e:  # cong khong ton tai, thieu quyen, file hong...
            self.failed.emit(f"{self.profile['name']}: {e}")
            return

        streams_sent = False
        last_bps_at = time.time()
        last_bytes = 0
        prev_log_ts = None

        # File .tlog mo ra thanh mavmmaplog: recv_match(blocking=True) cua no
        # TREO han o EOF thay vi tra None. Doc file thi non-blocking moi dung —
        # None nghia la het file, nhip phat lai do minh tu ngu ben duoi.
        blocking = self.mode != "REPLAY"

        try:
            while self._running:
                if self._paused.is_set():
                    time.sleep(0.05)
                    self._maybe_seek(master)
                    continue
                self._maybe_seek(master)

                msg = master.recv_match(blocking=blocking, timeout=0.5 if blocking else None)
                self._run_commands(master)

                if msg is not None:
                    name = msg.get_type()
                    if name == "BAD_DATA" or not from_autopilot(msg):
                        continue

                    # REPLAY: phat lai dung nhip goc. Khoang trong > 1 s thi
                    # nhay qua, khong ngoi doi.
                    if self.mode == "REPLAY":
                        log_ts = getattr(msg, "_timestamp", None)
                        if log_ts and prev_log_ts:
                            time.sleep(max(0.0, min(log_ts - prev_log_ts, 1.0)))
                        prev_log_ts = log_ts
                        self.percent = getattr(master, "percent", 0.0)

                    d = msg.to_dict()
                    ts = time.time()
                    self.last_rx = ts

                    if self._tlog_f:
                        # dinh dang .tlog: 8 byte timestamp micro-giay big-endian
                        # + goi MAVLink tho. Doc duoc bang Mission Planner.
                        self._tlog_f.write(struct.pack(">Q", int(ts * 1e6)) + msg.get_msgbuf())

                    out = normalize(name, d)
                    if out:
                        topic, data = out
                        if topic == "heartbeat":
                            # Tinh mode tu CHINH goi nay, khong lay master.flightmode:
                            # pymavlink cap nhat flightmode tu BAT KY heartbeat nao
                            # khong phai GCS, ke ca cua MAVROS (comp 191, custom_mode
                            # = 0) — nen gia tri do nhay qua lai giua mode that va
                            # mot mode rac, moi giay mot lan. Da loc goi o
                            # from_autopilot() roi thi msg nay chac chan la cua FC.
                            data["mode"] = mavutil.mode_string_v10(msg)
                        self._emit(topic, data, ts)

                    self._emit("status", flatten_status(name, d), ts)

                    # Xin stream rate ngay sau heartbeat dau tien (luc do moi biet
                    # target_system). REPLAY khong gui gi ca.
                    if name == "HEARTBEAT" and not streams_sent and self.mode != "REPLAY":
                        for sid, hz in STREAMS:
                            master.mav.request_data_stream_send(
                                master.target_system, AUTOPILOT, sid, hz, 1
                            )
                        streams_sent = True

                elif self.mode == "REPLAY":
                    self._emit("link", {"bps": 0, "eof": True})
                    break

                # Byte/s that, 1 Hz — nguon cho widget Link status
                now = time.time()
                if now - last_bps_at >= 1.0:
                    total = master.mav.total_bytes_received
                    self._emit(
                        "link",
                        {"bps": int((total - last_bytes) / (now - last_bps_at)), "mode": self.mode},
                        now,
                    )
                    last_bytes, last_bps_at = total, now
                    if self._tlog_f:
                        # App crash thi phan con nam trong buffer se mat — ma do
                        # dung la doan cuoi truoc su co, doan quan trong nhat.
                        self._tlog_f.flush()
        except Exception as e:
            self.failed.emit(f"{self.profile['name']}: {e}")
        finally:
            if self._tlog_f:
                self._tlog_f.close()
                self._tlog_f = None
            try:
                master.close()
            except Exception:
                pass


# ponytail: chua co send() — nut do va ARM la Phase N3, them vao day khi toi do.
