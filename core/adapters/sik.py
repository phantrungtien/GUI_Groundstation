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

# Hang rao la mot "nhiem vu" rieng trong MAVLink, khong phai waypoint (type 0).
FENCE = mavutil.mavlink.MAV_MISSION_TYPE_FENCE  # = 1
WP = mavutil.mavlink.MAV_MISSION_TYPE_MISSION   # = 0 — duong bay waypoint
WAYPOINT = mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
TAKEOFF = mavutil.mavlink.MAV_CMD_NAV_TAKEOFF
LAND = mavutil.mavlink.MAV_CMD_NAV_LAND
# Tran so waypoint. 50 muc la ~2,5 kB chieu xuong + 50 goi xin ~0,7 kB chieu len:
# duoi mot giay tren duong SiK 57600 (~4-5 kB/s that, Phu luc 7.1). Nhiem vu dai
# hon thi tai 50 diem dau va noi RO la da cat — chiem duong truyen hang chuc giay
# de ve het duong bay thi HUD dung hinh dung luc can no nhat, ma muc 7.1 da xep
# "mission nhieu waypoint" vao loai bulk transfer khong hop SiK.
WP_MAX = 50
# ArduPilot LUON giu muc 0 la home va tu ghi de toa do cua no. Cong them TAKEOFF
# mo dau va LAND ket thuc (xem _wp_upload), mot nhiem vu 50 waypoint nam tren day
# la 53 muc. Tran tai ve phai la 53, neu khong app tu cat cut chinh cai nhiem vu
# no vua nap va bao "FC co 53, chi tai 51".
WP_ITEMS_MAX = WP_MAX + 3
WP_UP_RETRY = 2.0  # giay cho FC xin muc dau tien truoc khi gui lai MISSION_COUNT
WP_UP_TRIES = 5
# Bon tham so quyet dinh hinh cua rao. Ban kinh va tran do cao khong nam trong
# danh sach nhiem vu ma la tham so — phai hoi rieng.
FENCE_PARAMS = ("FENCE_ENABLE", "FENCE_TYPE", "FENCE_RADIUS", "FENCE_ALT_MAX")
ASK_EVERY = 3.0  # giay giua hai lan hoi lai cai con thieu (rao + duong bay)
ASK_MAX = 8      # bo cuoc sau ~24s: firmware khong co rao thi hoi mai vo ich


def from_autopilot(msg):
    """Goi nay co phai FC noi khong?

    Duong MAVLink khong chi co FC tren do. Do tren SITL cua stack ROS2: FC (1/1),
    MAVROS (1/191, kieu ONBOARD_COMPUTER — heartbeat cua no BAT san co ARMED) va
    MAVProxy (255/230, kieu GCS). Khong loc thi:

      - den ARM nhay armed/disarmed moi nua giay vi ba nguon xen ke nhau
      - pymavlink doi `target_component` sang 191 (post_message() lay tu bat ky
        heartbeat nao khong phai GCS) -> lenh gui di dia chi vao MAVROS

    RADIO_STATUS giu lai: tren SiK that no do chinh cai radio duoi dat chen vao,
    khong phai FC. Rieng cap Holybro 433 dang dung thi KHONG bao gio den — do
    13/08/2026: 0 goi trong 30s, quet byte tho thay 22 khung v2 va 0 khung v1,
    nghia la firmware radio khong doc noi khung MAVLink2 nen khong chen duoc.
    Chat luong link vi vay lay tu ti le mat goi (xem cho phat topic "link"), con
    dong nay giu de radio nao chen duoc thi van dung.

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

# Nhip xin EXTENDED_SYS_STATE. 2 Hz la du: no chi doi trang thai khi cat/ha canh,
# va cang thua thi cang ton bang thong tren duong SiK 57600.
LANDED_HZ = 2

# Im lang bao nhieu giay (khong ke HEARTBEAT/TIMESYNC) thi xin lai ca bo stream.
# 5s: du dai de khong xin lai vi mot lo hong ngan, du ngan de HUD khong dung hinh
# lau. Moi lan xin lai ton 7 goi ~140 byte tren chieu len — chieu len dang trong.
STREAM_REARM = 5.0

# Bit cam bien trong SYS_STATUS. Lay thang tu bang enum cua pymavlink chu khong
# go tay: doi ban MAVLink co them cam bien moi thi tu co, khong phai sua code.
SENSOR_BITS = {
    e.name.replace("MAV_SYS_STATUS_SENSOR_", "").replace("MAV_SYS_STATUS_", "").lower(): bit
    for bit, e in mavutil.mavlink.enums["MAV_SYS_STATUS_SENSOR"].items()
    if bit > 0 and bin(bit).count("1") == 1 and not e.name.endswith("ENUM_END")
}


def decode_sensors(d):
    """SYS_STATUS -> mot hang cho moi cam bien.

    Ba truong `onboard_control_sensors_*` la ba bitmask 32 bit. De nguyen thi tab
    Status hien "1467007" — dung ky thuat, vo dung voi nguoi bay. Cam bien nao
    hong la thu phai doc duoc trong mot giay truoc khi cat canh.

    Gia tri tra ve la MA MAY ("ok", "fail", "ok_off", "fail_off"), khong phai chu
    cho nguoi doc. Adapter chay trong QThread va co y khong biet gi ve ngon ngu
    dang chon; de no sinh chu thi giao dien tieng Anh se co "TOT"/"HONG" lot vao
    giua — va ai muon dich lai se phai doi chuoi mot cach nguy hiem, dung kieu
    loi da gap o app.py khi no doan muc do nghiem trong bang cach bat chu trong
    dong log. Tab Trang thai dich luc ve (`laptop/tabs/status.py`).
    """
    present = d.get("onboard_control_sensors_present", 0)
    enabled = d.get("onboard_control_sensors_enabled", 0)
    health = d.get("onboard_control_sensors_health", 0)
    out = {}
    for name, bit in SENSOR_BITS.items():
        if not present & bit:
            continue  # khong lap tren may bay nay
        state = "ok" if health & bit else "fail"
        if not enabled & bit:
            state += "_off"
        out[f"SENSOR.{name}"] = state
    return out


def param_id(d):
    """Ten tham so trong PARAM_VALUE — bytes hay str tuy ban pymavlink, co dem \\x00."""
    pid = d.get("param_id", "")
    if isinstance(pid, bytes):
        pid = pid.decode("utf-8", "replace")
    return pid.replace("\x00", "").strip()


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

    if name == "EXTENDED_SYS_STATE":
        # `landed_state` chinh la `land_complete` cua FC — dung cai co quyet dinh
        # lenh disarm thuong co duoc chap nhan hay khong (ArduCopter/AP_Arming.cpp:788).
        #
        # Khong duoc thay bang do cao: do that tren MicoAir743 treo yen, GPS fix 0,
        # `relative_alt` doc ra -8.5 m suot 10 giay trong khi rangefinder noi 0.6 m.
        # Lech 8.5 m theo chieu am thi may bay dang o 7 m cung "duoi 1 m".
        #
        # 0 = FC khong biet -> KHONG emit gi, de field het tuoi thanh "khong biet".
        # Doan bua o day la doan ra huong nguy hiem.
        return "heartbeat", {"landed": {
            mavutil.mavlink.MAV_LANDED_STATE_ON_GROUND: True,
            mavutil.mavlink.MAV_LANDED_STATE_IN_AIR: False,
            mavutil.mavlink.MAV_LANDED_STATE_TAKEOFF: False,
            mavutil.mavlink.MAV_LANDED_STATE_LANDING: False,
        }.get(d["landed_state"])}

    if name == "HOME_POSITION":
        # Home THAT cua FC. Truoc day tab Flight lay diem dinh vi dau tien lam
        # home — noi vao ma drone dang bay thi cai dau X ve sai cho, va vong tron
        # geofence (tam la home) cung ve sai theo.
        return "home", {
            "lat": d["latitude"] / 1e7,
            "lon": d["longitude"] / 1e7,
            "alt_msl": d["altitude"] / 1000.0,
        }

    if name == "MISSION_CURRENT":
        # Waypoint FC dang bay TOI (khong phai cai vua qua). Day la thu duy nhat
        # phan biet "duong bay da nap" voi "drone dang di den dau tren duong do".
        #
        # `total` la truong mo rong, chi co tu ArduPilot 4.3 — thieu thi pymavlink
        # tra 0. Bo han key thay vi de None: ben ve gop tung manh vao cung mot
        # dict (nhu topic `fence`), nen mot so 0 hay None se xoa mat con so that
        # ma MISSION_COUNT vua dat vao.
        out = {"seq": d["seq"]}
        if d.get("total"):
            out["total"] = d["total"]
        return "wp", out

    if name == "PARAM_VALUE" and param_id(d).startswith("FENCE_"):
        # Rao di chung mot topic voi cac dinh da giac: ben ve chi phai nghe mot cho.
        return "fence", {param_id(d): d["param_value"]}

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
        pid = param_id(d)
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

        # Geofence + home: FC khong tu gui, phai hoi. Xem _fence_ask().
        self._fence = {}        # ten tham so FENCE_* -> gia tri da nhan
        self._fence_items = {}  # seq -> (command, param1, lat, lon)
        self._fence_n = None    # so muc FC bao co; None = chua hoi duoc
        self._home_seen = False
        self._ask_at = 0.0
        self._asks = 0

        # Duong bay (nhiem vu type 0). Cung co che hoi nhu rao. Xem _wp_ask().
        self._wp_items = {}  # seq -> (command, lat, lon, alt)
        self._wp_n = None    # so muc SE tai (da cat theo WP_ITEMS_MAX); None = chua hoi
        self._wp_total = None  # so muc FC BAO CO — de con biet la da cat hay chua
        self._home = None    # (lat, lon) that cua FC — muc 0 cua nhiem vu nap len

        # Dang nap duong bay len FC: danh sach muc cho FC xin, None = khong nap.
        self._up = None
        self._up_at = 0.0
        self._up_tries = 0
        self._up_n = 0  # so waypoint nguoi bay dat trong phien nap dang chay
        self._stream_rx = 0.0  # lan cuoi nhan goi CUA STREAM — xem _stream_tick()

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
        elif action == "wp_write":
            self._wp_upload(master, args.get("items") or [])
        elif action == "wp_clear":
            self._wp_upload(master, [])
        elif action == "nudge":
            # Nhich bang VAN TOC, khong bang toa do. Ly do la con so do 13/08/2026:
            # vi tri tren man hinh gia ~387 ms (3 Hz + 66 ms mot chieu), nen bay
            # 5 m/s la drone da di qua cham xanh 1,9 m. Gui "ve toa do vua nhin
            # thay" tuc bat no quay NGUOC lai 1,9 m moi lan tha phim.
            #
            # Van toc khong co cai benh do: 0 m/s nghia la "dung ngay tai cho
            # anh dang o", khong can biet cho do o dau. Va quang duong van ti le
            # voi thoi gian de phim vi do la tich phan cua van toc.
            #
            # Lenh van toc GUIDED cua ArduPilot tu het han sau ~3 s: mat link
            # giua chung thi drone DUNG VA TREO, khong phai roi vao failsafe nhu
            # RC_CHANNELS_OVERRIDE. Do la ly do chon duong nay chu khong gia lap
            # can lai. Nguoi goi phai lap lai lenh trong khi phim con giu.
            #
            # Frame LOCAL_NED (bac/dong) chu khong BODY_NED: ban do ve huong bac
            # len tren, nen phim mui ten trung voi cai mat nhin thay.
            m.set_position_target_local_ned_send(
                0, sysid, compid, mavutil.mavlink.MAV_FRAME_LOCAL_NED,
                0b0000111111000111,  # chi dung van toc, bo qua vi tri/gia toc/yaw
                0, 0, 0,
                float(args.get("vn", 0.0)), float(args.get("ve", 0.0)),
                float(args.get("vd", 0.0)),  # NED: vd duong la XUONG
                0, 0, 0, 0, 0,
            )
        elif action == "goto":
            m.mission_item_send(
                sysid, compid, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                mavutil.mavlink.MAV_CMD_NAV_WAYPOINT, 2, 0, 0, 0, 0, 0,
                float(args["lat"]), float(args["lon"]), float(args.get("alt", 10)),
            )
        else:
            raise ValueError(f"khong biet lenh {action!r}")
        self._emit("cmd", {"action": action, "args": args})

    # ---- geofence --------------------------------------------------------

    def _fence_done(self):
        return (
            self._home_seen
            and all(n in self._fence for n in FENCE_PARAMS)
            and self._fence_n is not None
            and len(self._fence_items) >= self._fence_n
        )

    def _fence_ask(self, master):
        """Hoi FC ve home va hang rao. Chi hoi cai CON THIEU, va hoi lai vai lan.

        Khong hoi thi ban do khong ve gi — ma man hinh trong lai giong het "khong
        co rao nao", dung kieu noi doi nguy hiem nhat truoc gio cat canh. Mot lan
        hoi khong du: SiK 57600 mat goi la chuyen thuong ngay.
        """
        m, sysid = master.mav, master.target_system
        for n in FENCE_PARAMS:
            if n not in self._fence:
                m.param_request_read_send(sysid, AUTOPILOT, n.encode(), -1)
        if not self._home_seen:
            m.command_long_send(
                sysid, AUTOPILOT, mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, 0,
                mavutil.mavlink.MAVLINK_MSG_ID_HOME_POSITION, 0, 0, 0, 0, 0, 0,
            )
        if self._fence_n is not None:
            self._fence_ask_items(master)
            return
        try:
            m.mission_request_list_send(sysid, AUTOPILOT, mission_type=FENCE)
        except TypeError:
            # `mission_type` la truong mo rong cua MAVLink2. pymavlink tu nang len
            # v2 khi nhan duoc goi v2 dau tien, nen duong nay chi xay ra khi FC bi
            # ep MAVLink1 (SERIALn_PROTOCOL=1). Vong tron + tran do cao van ve
            # duoc tu tham so; rieng da giac thi chiu — va phai noi ra.
            self._fence_n = 0
            self._emit("fence", {"items": [], "err": "FC dang o MAVLink1 — khong doc duoc da giac"})

    def _fence_ask_items(self, master):
        """Xin cac dinh CON THIEU. Tach rieng de goi duoc ngay khi biet so luong:
        doi het nhip 3s moi xin thi rao hien ra cham hon can thiet."""
        for i in range(self._fence_n or 0):
            if i not in self._fence_items:
                master.mav.mission_request_int_send(
                    master.target_system, AUTOPILOT, i, mission_type=FENCE
                )

    def _fence_rx(self, master, name, d):
        """Goi lien quan den rao/home vua ve. True neu vua nhan du bo dinh."""
        if self.muted:
            return False  # dang mo phong mat song: goi nay coi nhu chua tung toi
        if name == "HOME_POSITION":
            self._home_seen = True
            # Giu lai toa do: muc 0 cua nhiem vu nap len phai la home (xem _wp_upload).
            self._home = (d["latitude"] / 1e7, d["longitude"] / 1e7)
        elif name == "PARAM_VALUE" and param_id(d).startswith("FENCE_"):
            self._fence[param_id(d)] = d["param_value"]
        elif name == "MISSION_COUNT" and d.get("mission_type") == FENCE:
            # Dem lai tu dau: FC vua noi hien co bao nhieu muc.
            self._fence_n = d["count"]
            self._fence_items.clear()
            self._fence_ask_items(master)
            return self._fence_n == 0  # khong co da giac nao -> bao ngay, ve rong
        elif name == "MISSION_ITEM_INT" and d.get("mission_type") == FENCE:
            # mission_type phai khop: `goto` cung dung mission item (type 0), gop
            # chung vao la mot waypoint hoa thanh mot dinh hang rao.
            self._fence_items[d["seq"]] = (d["command"], d["param1"],
                                           d["x"] / 1e7, d["y"] / 1e7)
            return self._fence_n is not None and len(self._fence_items) >= self._fence_n
        return False

    def _fence_emit(self, master):
        self._emit("fence", {"items": [self._fence_items[i] for i in sorted(self._fence_items)]})
        if self.mode == "REPLAY":
            return  # log co ghi lai rao thi van ve duoc, nhung khong gui gi ca
        try:  # dong giao dich cho FC khoi cho — thieu cai nay no giu trang thai
            master.mav.mission_ack_send(master.target_system, AUTOPILOT, 0, mission_type=FENCE)
        except TypeError:
            pass

    # ---- duong bay waypoint ----------------------------------------------

    def _wp_done(self):
        return self._wp_n is not None and len(self._wp_items) >= self._wp_n

    def _wp_ask(self, master):
        """Hoi FC danh sach waypoint. Cung nhip, cung ly do voi _fence_ask.

        Khong hoi thi tab Flight chi co mot cham xanh troi tren ban do: nhin thay
        drone dang o dau, khong thay no SAP di dau. Trong bay AUTO thi day la
        thong tin quan trong hon ca vi tri hien tai.

        `mission_type` la truong mo rong cua MAVLink2. FC bi ep MAVLink1 thi bo
        no di, khong sao: MAVLink1 chi co dung mot loai nhiem vu la waypoint.
        """
        if self._up is not None:
            return  # dang nap len: chen mot phien tai ve vao giua la hong ca hai
        m, sysid = master.mav, master.target_system
        if self._wp_n is None:
            try:
                m.mission_request_list_send(sysid, AUTOPILOT, mission_type=WP)
            except TypeError:
                m.mission_request_list_send(sysid, AUTOPILOT)
            return
        for i in range(self._wp_n):
            if i not in self._wp_items:
                try:
                    m.mission_request_int_send(sysid, AUTOPILOT, i, mission_type=WP)
                except TypeError:
                    m.mission_request_int_send(sysid, AUTOPILOT, i)

    def _wp_rx(self, master, name, d):
        """Goi lien quan den duong bay vua ve. True neu vua nhan du danh sach."""
        if self.muted:
            return False
        if name == "MISSION_COUNT" and d.get("mission_type", 0) == WP:
            self._wp_total = d["count"]
            self._wp_n = min(d["count"], WP_ITEMS_MAX)
            self._wp_items.clear()
            self._wp_ask(master)
            return self._wp_n == 0  # nhiem vu rong -> bao ngay de ben ve xoa duong cu
        if name == "MISSION_ITEM_INT" and d.get("mission_type", 0) == WP:
            # x/y la 1e7 do; z la met so voi frame cua chinh muc do (thuong la
            # GLOBAL_RELATIVE_ALT, tuc so voi home).
            if d["seq"] < WP_ITEMS_MAX:
                self._wp_items[d["seq"]] = (d["command"], d["x"] / 1e7, d["y"] / 1e7, d["z"])
            return self._wp_done()
        if name == "MISSION_CURRENT" and d.get("total") and d["total"] != self._wp_total:
            # Ai do nap nhiem vu khac trong luc app dang chay (MAVProxy, ban web):
            # FC khong bao cho GCS thu hai biet. `total` trong MISSION_CURRENT la
            # duong duy nhat phat hien, va no chi co tu ArduPilot 4.3 tro len —
            # firmware cu hon thi duong bay cu nam lai toi khi noi lai.
            #
            # So sanh voi _wp_total (so FC bao) chu khong _wp_n (so da cat): nhiem
            # vu 80 diem thi _wp_n = 50 mai mai khac 80, va vong tai lai chay hoai.
            self._wp_n = self._wp_total = None
            self._wp_items, self._asks = {}, 0
        return False

    def _wp_emit(self, master):
        self._emit("wp", {
            "items": [(i, *self._wp_items[i]) for i in sorted(self._wp_items)],
            "total": self._wp_total,  # lech voi len(items) = da cat theo WP_MAX
        })
        if self.mode == "REPLAY":
            return  # log co ghi lai duong bay thi van ve duoc, nhung khong gui gi ca
        try:  # dong giao dich cho FC khoi giu trang thai cho — nhu ben rao
            master.mav.mission_ack_send(master.target_system, AUTOPILOT, 0, mission_type=WP)
        except TypeError:
            master.mav.mission_ack_send(master.target_system, AUTOPILOT, 0)

    # ---- nap duong bay len FC (chieu ghi) --------------------------------
    #
    # Chieu ghi CHI co o app nay. Nua ROS2 khong nap duoc duong bay: no khong
    # cam quyen nua (core/authority.py), va lenh `wp_write` khong ton tai o
    # RemoteAdapter. Mot nhiem vu tren FC chi den tu mot cho — cho nay.

    def _wp_upload(self, master, points):
        """Bat dau nap. `points` = [(lat, lon, alt)]; rong = xoa sach duong bay.

        Muc 0 do minh tu chen: ArduPilot danh muc 0 lam HOME va tu ghi de toa do
        cua no khi luu. Khong chen thi waypoint dau tien cua nguoi bay bi nuot
        mat lam home — dat 5 diem, drone bay 4.

        Hai muc nua cung do minh chen, va thieu chung thi nhiem vu nap len TRONG
        NHU THAT ma khong bay duoc:

          TAKEOFF mo dau — ArduCopter dung duoi dat vao AUTO ma lenh nav dau tien
          khong phai NAV_TAKEOFF thi no khong leo. Nguoi bay nap xong, gat AUTO,
          arm, va drone nam im tren bai: hong ma khong mot dong canh bao nao.

          LAND ket thuc — bay het waypoint cuoi la FC giu nguyen vi tri do cho
          den khi het pin. Ha tai chinh diem cuoi (2026-08-13: nguoi dung chon
          LAND chu khong RTL).
        """
        pts = [(float(a), float(b), float(c)) for a, b, c in points][:WP_MAX]
        self._up_n = len(pts)  # so waypoint CUA NGUOI BAY, khong ke 3 muc tu chen
        if not pts:
            self._up = []  # MISSION_COUNT = 0 la cach xoa nhiem vu trong MAVLink
        else:
            home = self._home or pts[0][:2]
            self._up = [
                (WAYPOINT, home[0], home[1], 0.0),
                # lat/lon = 0: ArduCopter cat canh thang len tu cho no dang dung,
                # va ben ve ban do bo qua muc khong co toa do (wp_points) nen
                # duong bay khong keo mot net ra dao Null giua Dai Tay Duong.
                (TAKEOFF, 0.0, 0.0, pts[0][2]),
                *[(WAYPOINT, *p) for p in pts],
                (LAND, pts[-1][0], pts[-1][1], 0.0),
            ]
        self._up_tries = 0
        self._wp_up_count(master)

    def _wp_up_count(self, master):
        """Gui MISSION_COUNT — mo phien nap, va cung la cach gui lai khi FC im."""
        self._up_at, self._up_tries = time.time(), self._up_tries + 1
        if self.muted:
            # Dang mo phong mat song: goi nay khong ra khoi radio. Van dem mot
            # luot — dung cai muon do la "nap giua luc rot link thi ra sao".
            return
        n = len(self._up)
        try:
            master.mav.mission_count_send(master.target_system, AUTOPILOT, n, mission_type=WP)
        except TypeError:
            master.mav.mission_count_send(master.target_system, AUTOPILOT, n)

    def _wp_up_rx(self, master, name, d):
        """Goi cua phien NAP. True neu phien vua ket thuc (thanh cong hay khong).

        FC dan nhip: no xin tung muc mot, minh tra loi tung muc. Khong tu ban ca
        loat: qua SiK 57600 thi ban loat la tran bo dem cua radio, mat goi, va FC
        xin lai tu dau — cham hon la de no dan.
        """
        if self.muted or self._up is None or d.get("mission_type", 0) != WP:
            return False  # muted: goi nay coi nhu chua tung toi (nhu _fence_rx)

        if name in ("MISSION_REQUEST", "MISSION_REQUEST_INT"):
            seq = d["seq"]
            if seq >= len(self._up):
                return False  # FC xin muc khong co: bo qua, no se xin lai cai dung
            cmd, lat, lon, alt = self._up[seq]
            # Ca muc 0 cung gui frame RELATIVE_ALT: FC ghi de toa do home vao do
            # ngay khi luu, nen frame cua rieng muc do khong anh huong gi.
            args = (master.target_system, AUTOPILOT, seq,
                    mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                    cmd, 0, 1, 0, 0, 0, 0,
                    int(lat * 1e7), int(lon * 1e7), alt)
            try:
                master.mav.mission_item_int_send(*args, mission_type=WP)
            except TypeError:
                master.mav.mission_item_int_send(*args)
            self._up_at = time.time()  # FC con noi chuyen -> chua phai gui lai
            return False

        if name == "MISSION_ACK":
            n = self._up_n  # so waypoint nguoi bay dat, khong ke home/TAKEOFF/LAND
            self._up = None
            self._emit("wp", {"write": {"ok": d["type"] == 0, "result": d["type"], "n": n}})
            # Doc lai ngay tu FC. "Da gui" khong phai "FC da luu" — thu duy nhat
            # chung minh duoc la chinh danh sach doc nguoc ve, va no cung la thu
            # ve len ban do.
            self._wp_n = self._wp_total = None
            self._wp_items, self._asks = {}, 0
            return True
        return False

    def _stream_tick(self, master, now):
        """FC ngung bom stream nhung VAN heartbeat -> xin lai ca bo.

        Do that tren radio SiK ngay 13/08/2026: sau vai phut FC tut xuong con
        21 B/s chi con HEARTBEAT, xin lai mot lan la ve 1986 B/s ngay lap tuc.
        Radio vo can — dem cua no `txe=0 rxe=0 ecc=0/0` suot luc do.

        Xin duy nhat mot lan luc ket noi thi khong du: dut giua chuyen bay la HUD
        dung hinh trong khi link van bao "co song" va nhiem vu AUTO van chay tiep
        — nguoi bay khong con so lieu nao de biet. Day la kieu hong muc 1.3 xep
        vao loai nguy hiem nhat: im lang ma trong nhu binh thuong.

        HEARTBEAT/TIMESYNC khong tinh la dau hieu song: FC gui chung ma khong can
        ai xin, nen chung van deu dan dung luc moi thu khac da tat.
        """
        if (self.mode == "REPLAY" or self.muted
                or now - self._stream_rx < STREAM_REARM):
            return
        self._stream_rx = now  # dat lai truoc khi gui: hong cach may cung khong ban
        for sid, hz in STREAMS:
            master.mav.request_data_stream_send(master.target_system, AUTOPILOT, sid, hz, 1)

    def _wp_up_tick(self, master, now):
        """FC im giua phien nap thi gui lai MISSION_COUNT, roi bo cuoc va NOI RA.

        Bo cuoc im lang o day la kieu hong te nhat: nguoi bay dat 12 diem, thay
        duong bay tren ban do, va khong bao gio biet FC chua he nhan duoc no.
        """
        if self._up is None or now - self._up_at < WP_UP_RETRY:
            return
        if self._up_tries >= WP_UP_TRIES:
            self._up = None
            self._emit("wp", {"write": {
                "ok": False, "result": None, "n": self._up_n,
                "err": f"FC khong tra loi sau {WP_UP_TRIES} lan gui MISSION_COUNT",
            }})
            return
        self._wp_up_count(master)

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
        elif ":" not in p["conn"]:   # cong serial: /dev/ttyUSB0, COM3 — mang thi co "tcp:"/"udp:"
            # mavlink_connection() mac dinh 115200. Doc radio SiK 57600 bang so do
            # thi KHONG im lang — no ra mot luong UNKNOWN_* deu dan, app bao "da
            # ket noi" va ve status tu rac (do that: 1156/1156 khung la UNKNOWN).
            # Quy tac giong laptop/connection.py:78, dat o day vi profile dung tay
            # (tools/soak.py) khong di qua duong do.
            kw["baud"] = 115200 if "ttyACM" in p["conn"] else 57600
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
        last_loss = last_count = 0  # so goi mat/nhan cua lan phat "link" truoc
        self._stream_rx = time.time()
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
                    # UNKNOWN_*: msgid khong co trong dialect. Khung nhieu trung CRC
                    # ra kieu nay, va no la thu duy nhat lam mot duong truyen hong
                    # trong giong duong truyen song — bo di thi sai baud/nhieu nang
                    # thanh IM LANG, dung kieu hong ma banner bat duoc.
                    if (name == "BAD_DATA" or name.startswith("UNKNOWN_")
                            or not from_autopilot(msg)):
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
                    # HEARTBEAT/TIMESYNC den khong can xin, nen chung KHONG chung
                    # minh stream con song — dem rieng, xem _stream_tick().
                    if name not in ("HEARTBEAT", "TIMESYNC"):
                        self._stream_rx = ts

                    if self._tlog_f:
                        # dinh dang .tlog: 8 byte timestamp micro-giay big-endian
                        # + goi MAVLink tho. Doc duoc bang Mission Planner.
                        self._tlog_f.write(struct.pack(">Q", int(ts * 1e6)) + msg.get_msgbuf())

                    out = normalize(name, d)
                    if out:
                        topic, data = out
                        # Dieu kien phai bam theo TEN MESSAGE, khong theo topic:
                        # EXTENDED_SYS_STATE cung do ve topic `heartbeat`, va
                        # mode_string_v10() doi `.autopilot` — goi do khong co,
                        # nen luong doc chet ngay goi dau tien.
                        if name == "HEARTBEAT":
                            # Tinh mode tu CHINH goi nay, khong lay master.flightmode:
                            # pymavlink cap nhat flightmode tu BAT KY heartbeat nao
                            # khong phai GCS, ke ca cua MAVROS (comp 191, custom_mode
                            # = 0) — nen gia tri do nhay qua lai giua mode that va
                            # mot mode rac, moi giay mot lan. Da loc goi o
                            # from_autopilot() roi thi msg nay chac chan la cua FC.
                            data["mode"] = mavutil.mode_string_v10(msg)
                        self._emit(topic, data, ts)

                    self._emit("status", flatten_status(name, d), ts)

                    if self._fence_rx(master, name, d):
                        self._fence_emit(master)

                    # Phien nap di truoc: dang nap thi MISSION_ACK la cua no,
                    # khong phai cua mot phien tai ve nao.
                    if not self._wp_up_rx(master, name, d) and self._wp_rx(master, name, d):
                        self._wp_emit(master)

                    # Xin stream rate ngay sau heartbeat dau tien (luc do moi biet
                    # target_system). REPLAY khong gui gi ca.
                    if name == "HEARTBEAT" and not streams_sent and self.mode != "REPLAY":
                        for sid, hz in STREAMS:
                            master.mav.request_data_stream_send(
                                master.target_system, AUTOPILOT, sid, hz, 1
                            )
                        # EXTENDED_SYS_STATE khong nam trong bo stream cu nao —
                        # phai xin rieng, neu khong FC khong gui goi nao (do that:
                        # 0 goi trong 8s truoc khi xin, 17 goi sau khi xin).
                        master.mav.command_long_send(
                            master.target_system, AUTOPILOT,
                            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                            mavutil.mavlink.MAVLINK_MSG_ID_EXTENDED_SYS_STATE,
                            int(1e6 / LANDED_HZ), 0, 0, 0, 0, 0,
                        )
                        streams_sent = True

                elif self.mode == "REPLAY":
                    self._emit("link", {"bps": 0, "eof": True})
                    break

                now = time.time()

                if self.mode != "REPLAY":
                    self._wp_up_tick(master, now)
                    if streams_sent:
                        self._stream_tick(master, now)

                # Rao, home va duong bay: hoi sau khi da co target_system (tuc sau
                # heartbeat dau), roi hoi lai cai con thieu cho toi khi du hoac
                # het luot. Ba thu nay FC khong tu gui bao gio.
                if (streams_sent and not self.muted
                        and not (self._fence_done() and self._wp_done())
                        and self._asks < ASK_MAX
                        and now - self._ask_at >= ASK_EVERY):
                    self._ask_at, self._asks = now, self._asks + 1
                    if not self._fence_done():
                        self._fence_ask(master)
                    if not self._wp_done():
                        self._wp_ask(master)

                # Byte/s + ti le mat goi, 1 Hz — nguon cho widget Link status
                if now - last_bps_at >= 1.0:
                    total = master.mav.total_bytes_received
                    # Radio SiK nay KHONG chen RADIO_STATUS (do 13/08/2026: 0 goi
                    # trong 30s, va quet byte tho thay 0 khung mang chu ky 51/68).
                    # Firmware no chi nhan biet khung MAVLink1 nen khong tim duoc
                    # ranh gioi goi trong luong v2 cua FC. Ep FC noi v1 thi co RSSI
                    # nhung mat geofence (`mission_type` la truong cua v2) — doi
                    # nhu vay la lo, nen chat luong link doi tu chinh luong dang
                    # nhan: MAVLink danh so thu tu tung goi, thung so la mat goi.
                    # Khong bang RSSI o cho bao truoc, nhung hon o cho no do dung
                    # thu can biet — bao nhieu phan tram KHONG toi noi.
                    lost = master.mav_loss - last_loss
                    good = master.mav_count - last_count
                    self._emit(
                        "link",
                        {"bps": int((total - last_bytes) / (now - last_bps_at)),
                         "loss": round(100.0 * lost / (lost + good), 1) if lost + good else 0.0,
                         "mode": self.mode},
                        now,
                    )
                    last_bytes, last_bps_at = total, now
                    last_loss, last_count = master.mav_loss, master.mav_count
                    if self._tlog_f:
                        # App crash thi phan con nam trong buffer se mat — ma do
                        # dung la doan cuoi truoc su co, doan quan trong nhat.
                        self._tlog_f.flush()
        except Exception as e:
            self.failed.emit(f"{self.profile['name']}: {e}")
        finally:
            if self._tlog_f:
                # Mo nguon xong ma khong nhan duoc goi nao (cong sai, radio chua
                # bat) thi de lai mot file 0 byte: no khong phai chuyen bay, chi
                # lam ban thu muc log va lam hop thoai REPLAY chon nham file rong.
                empty = self._tlog_f.tell() == 0
                self._tlog_f.close()
                self._tlog_f = None
                if empty:
                    self.tlog.unlink(missing_ok=True)
                    self.tlog = None
            try:
                master.close()
            except Exception:
                pass

