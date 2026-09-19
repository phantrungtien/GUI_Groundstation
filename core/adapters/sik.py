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

from core.adapters import join

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
# Tham so cho man bay: pin (thoi gian con lai), failsafe (kiem luc ket noi), RTL
# (uoc thoi gian ve nha). FC khong tu gui, phai hoi nhu rao. Moi NHOM la cac ten
# thay the nhau: ArduCopter 4.7-dev doi sang SI (RTL_ALT cm -> RTL_ALT_M m), co
# mot ten trong nhom la du — FC im lang voi ten no khong co.
WATCH_PARAMS = (
    ("BATT_CAPACITY",), ("BATT_LOW_MAH",), ("BATT_CRT_MAH",),
    ("BATT_FS_LOW_ACT",), ("BATT_FS_CRT_ACT",), ("BATT_LOW_VOLT",),
    ("FS_THR_ENABLE",), ("FS_GCS_ENABLE",),
    ("RTL_ALT_M", "RTL_ALT"), ("RTL_SPEED_MS", "RTL_SPEED"), ("WP_SPD", "WPNAV_SPEED"),
    ("WP_SPD_UP", "WPNAV_SPEED_UP"), ("WP_SPD_DN", "WPNAV_SPEED_DN"),
    ("LAND_SPD_MS", "LAND_SPEED"), ("LAND_SPD_HIGH_MS", "LAND_SPEED_HIGH"),
    ("LAND_ALT_LOW_M", "LAND_ALT_LOW"), ("RTL_LOIT_TIME",),
)
WATCH_NAMES = {n for g in WATCH_PARAMS for n in g}
ASK_EVERY = 3.0  # giay giua hai lan hoi lai cai con thieu (rao + duong bay)
ASK_MAX = 8      # bo cuoc sau ~24s: firmware khong co rao thi hoi mai vo ich

# --- tai log dataflash tu FC ---
# FC cat log thanh khoi 90 byte (do la kich thuoc truong `data` cua LOG_DATA,
# khong phai con so tu chon). Chi hoi lai o boi cua 90 de moi khoi ve deu roi
# dung mot o trong bang `have` — hoi lech mot byte la ca phan sau lech theo.
LOG_BLOCK = 90
LOG_STALL = 2.0   # giay im lang truoc khi hoi lai tu cho con thieu
LOG_TRIES = 10    # bo cuoc sau ~20s im lang; SiK rot goi la chuyen thuong


def _is_df(master):
    """Duong dang mo la log dataflash (.bin) chu khong phai luong MAVLink?

    `mav` la bo dong/giai goi MAVLink. DFReader doc ban ghi dataflash da giai
    san nen khong co no — va do cung la thu vong lap doc dung de biet minh phai
    di nhanh nao. Hoi bang `hasattr` chu khong bang duoi file: mot ngay nao do
    pymavlink nhan them duoi khac thi cau hoi nay van dung.
    """
    return not hasattr(master, "mav")


def _upgrade_v2(master, msg):
    """Thay khung MAVLink2 dau tien thi nang ca chieu GUI len v2.

    pymavlink co san `auto_mavlink_version()`, nhung tren cong NOI TIEP no gan
    nhu khong bao gio chay: no chi soi khi mieng byte doc duoc BAT DAU bang byte
    mo dau, ma cam vao giua luong thi mieng dau roi vao giua goi. Do that tren
    MicoAir743 qua USB 23/08/2026: nhan 292 goi v2 lien tuc ma
    `WIRE_PROTOCOL_VERSION` van la "1.0".

    Hau qua khong nam o chieu DOC (thu vien v1 van doc duoc khung v2) ma o chieu
    GUI: `mission_request_list_send(..., mission_type=...)` la truong mo rong cua
    v2, goi bang lop v1 thi ném TypeError -> app tuong FC bi ep MAVLink1 va bao
    sai nhu vay, trong khi ca 496/496 khung deu la 0xFD.

    Khong ep v2 ngay tu luc mo cong: FC dat SERIALn_PROTOCOL=1 that su chi doc
    duoc v1, ep v2 la moi lenh gui di deu roi vao thung rac mot cach im lang.
    Chi nang khi chinh FC da noi v2 truoc.
    """
    if master.WIRE_PROTOCOL_VERSION == "2.0":
        return
    buf = msg.get_msgbuf()
    if buf and buf[0] == 253:  # 0xFD
        master.auto_mavlink_version(buf)


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

# Cung bay luong, nhung cho duong KHONG phai radio: cong USB CDC cua chinh FC, va
# SITL qua tcp/udp. Ca hai deu khong bi 57600 baud chan.
#
# Do that 26/08/2026 tren MicoAir743 cam USB: bang STREAMS o tren cho 61 goi/s va
# 1.8 kB/s, bang nay cho 382 goi/s va 11.8 kB/s — FC gui du dung cai duoc xin,
# khong sut goi nao. Cai mua duoc la DO TRE: mot mau ATTITUDE tu 100 ms xuong
# 20 ms, GLOBAL_POSITION_INT tu 333 ms xuong 50 ms.
#
# ponytail: van la bang co dinh chu khong do bang thong roi tu chinh. Duong USB
# thua gap tram lan nen khong co gi de do; ngay nao chay qua duong hep hon 57600
# thi moi can vong dieu chinh.
STREAMS_FAST = [
    (mavutil.mavlink.MAV_DATA_STREAM_EXTENDED_STATUS, 10),
    (mavutil.mavlink.MAV_DATA_STREAM_POSITION, 20),
    (mavutil.mavlink.MAV_DATA_STREAM_EXTRA1, 50),   # ATTITUDE
    (mavutil.mavlink.MAV_DATA_STREAM_EXTRA2, 25),   # VFR_HUD
    (mavutil.mavlink.MAV_DATA_STREAM_RAW_SENSORS, 10),
    (mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS, 10),
    (mavutil.mavlink.MAV_DATA_STREAM_EXTRA3, 10),
]


def stream_table(profile):
    """Bang stream hop voi bang thong THAT cua duong dang dung.

    Truoc day chi co mot bang, chinh cho radio SiK 57600 (~4-5 kB/s). Cam thang
    USB vao FC thi van 10 Hz ATTITUDE trong khi duong tai duoc gap tram lan — tuc
    la tra 100 ms do tre cho mot cai chat khong ton tai tren duong do.

    Khong doan tu `baud`: khuon "SiK radio" trong config/connections.yaml ep baud
    57600 cho MOI cong quet ra, con USB CDC thi bo qua baud hoan toan. Co that de
    doc la `bridge`, do luc quet cong theo VID cua chip cau USB-serial.

    Chua biet chac thi giu bang HEP: doan nham theo huong nhanh la lam nghen mot
    duong radio giua chuyen bay, doan nham theo huong cham thi chi la cham.
    """
    if ":" in str(profile.get("conn", "")):   # tcp:/udp: — SITL, khong qua radio
        return STREAMS_FAST
    if profile.get("bridge") is False:        # cong CDC cua chinh FC
        return STREAMS_FAST
    return STREAMS

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

    if name == "PARAM_VALUE" and param_id(d) in WATCH_NAMES:
        return "param", {param_id(d): d["param_value"]}

    if name == "BATTERY_STATUS":
        # mAh da xai tu luc cam pin — FC dem bang dong dien, chinh hon % (buoc 1%).
        c = d["current_consumed"]
        return "battery", {"consumed_mah": c if c >= 0 else None}

    return None


# Ten trong log dataflash (.bin) khac han ten MAVLink: ATT chu khong phai
# ATTITUDE, POS chu khong phai GLOBAL_POSITION_INT. Bang duoi chi dich dung
# nhung thu NUOI GIAO DIEN — 16 field ma REGISTRY thuc su duoc doc ra. Con lai
# (RATE, XKF*, OF, CTUN, VIBE...) van vao bang Trang thai qua flatten_status y
# nhu cu, khong hardcode gi ca.
#
# Mot ban ghi co the sinh HAI topic (GPS nuoi ca `gps` lan toc do mat dat cua
# `vfr`), nen ham nay tra ve DANH SACH chu khong mot cap nhu normalize().
def normalize_df(name, d):
    """Ban ghi dataflash -> [(topic, data)] dung chuan cua docs/protocol.md."""
    if name == "ATT":
        # Dataflash ghi goc bang DO, con topic `attitude` cua app la RADIAN (dung
        # quy uoc cua ATTITUDE trong MAVLink). Quen doi don vi thi chan troi nam
        # ngang o moi tu the — hong ma trong nhu chay dung.
        yaw_ned = math.radians(d["Yaw"])
        return [("attitude", {
            "roll": math.radians(d["Roll"]),
            "pitch": math.radians(d["Pitch"]),
            "yaw": (math.pi / 2 - yaw_ned + math.pi) % (2 * math.pi) - math.pi,
            "heading": d["Yaw"] % 360.0,
        })]

    if name == "POS":
        # Vi tri EKF da hop nhat — cung thu Mission Planner ve len ban do, khong
        # phai GPS tho. DFReader nhan he so san nen do va met ra thang, khong /1e7.
        return [("position", {
            "lat": d["Lat"], "lon": d["Lng"],
            "alt_msl": d["Alt"], "alt_rel": d["RelHomeAlt"],
        })]

    if name == "GPS":
        return [("gps", {"fix_type": d["Status"], "sats": d["NSats"],
                         "hdop": d["HDop"]}),
                ("vfr", {"groundspeed": d["Spd"]})]

    if name == "BAT":
        if d.get("Inst", 0) != 0:
            return []  # chi pin thu nhat: nhieu pin thi dai chu nhay qua lai
        return [("battery", {"voltage": d["Volt"], "current": d.get("Curr"),
                             "remaining": d.get("RemPct")})]

    if name == "MODE":
        return [("heartbeat", {"mode": mavutil.mode_string_acm(d["Mode"])})]

    if name == "ARM":
        # ArduPilot ghi hai thu: ARM (kem ca `Forced` lan ly do) va EV Id=10/11.
        # Lay ARM vi no noi THANG trang thai, khong phai mot ma su kien phai tra.
        return [("heartbeat", {"armed": bool(d["ArmState"])})]

    if name == "MSG":
        # Chu FC in ra: phien ban firmware, canh bao truoc cat canh, ly do
        # failsafe. Dataflash KHONG ghi muc do nghiem trong nen de INFO — doan
        # muc do bang cach bat chu trong dong log la loi da go bo o app.py.
        return [("text", {"severity": 6, "text": d["Message"]})]

    if name == "ORGN":
        # Type 0 = goc EKF, 1 = home cua AHRS. Nhan ca hai: ArduPilot ghi goc
        # truoc roi ghi home sau, nen ban ghi sau de len va cuoi cung ra dung
        # home. Hai diem nay cach nhau vai met o ngay cho cat canh.
        return [("home", {"lat": d["Lat"], "lon": d["Lng"], "alt_msl": d["Alt"]})]

    return []


def flatten_status(name, d):
    """Moi field cua moi message -> STATUS["MSG.field"]. Khong hardcode gi ca.

    Truoc day chi giu int/float, tuc am tham nuot mat: mang (dien ap tung cell
    trong BATTERY_STATUS.voltages, tung kenh RC), chuoi (ten firmware, STATUSTEXT),
    va cac bitmask cam bien. "Doc duoc het trang thai" thi khong duoc bo thu nao.
    """
    if name == "LOG_DATA":
        # 90 byte noi dung log tho. Do vao bang Trang thai la 90 hang moi goi,
        # ~4500 hang mot giay trong suot phien tai — bang treo, ma khong hang
        # nao doc duoc. Tien trinh tai di bang topic "log" rieng.
        return {}
    d = dict(d)
    d.pop("mavpackettype", None)
    out = {}
    if name == "SYS_STATUS":
        out.update(decode_sensors(d))
    if name == "PARM":
        # Ban .bin: PARM la PARAM_VALUE cua ben kia. Tach theo ten vi cung ly do
        # — gop chung mot hang thi 1400 tham so de len nhau.
        return {f"PARAM.{d['Name']}": d.get("Value")}
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
        self._params = {}       # ten trong WATCH_PARAMS -> gia tri da nhan
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
        self._df_beat = {}  # .bin: mode/armed biet gan nhat — xem run()
        self._log = None       # phien tai log dataflash dang chay — xem _log_start()
        self._log_list = []    # LOG_ENTRY da nhan: [{id, size, time_utc}]

    def stop(self):
        self._running = False
        self._paused.clear()  # dang tam dung ma bam thoat thi phai thoat duoc
        join(self)

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
            master.f.seek(master.offset)  # .tlog: phai keo ca file object theo
        except AttributeError:
            # .bin: DFReader doc bang mmap, dat `offset` la du — no tu quet toi
            # ranh gioi ban ghi ke tiep. Do that tren 00000074.BIN: tua toi 50%
            # thi bo "9 bad bytes" roi doc tiep binh thuong, `percent` ra 50.0.
            pass

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
            for pname in args["names"]:
                m.param_request_read_send(sysid, compid, pname.encode(), -1)
        elif action == "param_all":
            # Keo ca bang tham so thay vi hoi theo mot danh sach ten ghim cung.
            # Ten tham so DOI theo firmware: ArduCopter 4.7-dev doi hang loat sang
            # SI — WPNAV_SPEED -> WP_SPD, PSC_VELXY_* -> PSC_NE_VEL_*, RTL_ALT ->
            # RTL_ALT_M. Do that 23/08/2026: 30/63 ten app hoi khong con ton tai,
            # va FC im lang chu khong bao sai, nen giao dien trong nhu link hong.
            #
            # Gia: 1037 tham so mat 9,4 s qua USB, uoc ~20 s qua SiK 57600 va
            # chiem gan het duong truyen trong luc do. Vi vay no la mot nut bam,
            # khong phai viec tu dong lam luc ket noi.
            m.param_request_list_send(sysid, compid)
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
        elif action == "log_list":
            # FC tra ve num_logs goi LOG_ENTRY, moi goi mot log tren the SD.
            self._log_list = []
            m.log_request_list_send(sysid, compid, 0, 0xFFFF)
        elif action == "log_get":
            self._log_start(master, int(args["id"]), int(args["size"]))
        elif action == "log_cancel":
            self._log_end(master, err="nguoi dung huy")
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
                # `alt` BAT BUOC. Truoc day cho mac dinh 10 m: dang bay 50 m ma bam
                # "bay toi day" la drone TUT xuong 10 m, khong mot dong nao noi ra.
                # Thieu thi no phai no ngay o day chu khong duoc tu doan.
                float(args["lat"]), float(args["lon"]), float(args["alt"]),
            )
        else:
            raise ValueError(f"khong biet lenh {action!r}")
        self._emit("cmd", {"action": action, "args": args})

    # ---- tai log dataflash tu the SD cua FC -------------------------------

    def _log_start(self, master, log_id, size):
        """Bat dau keo mot log .bin tu FC ve `logdir`.

        Vi sao phai co: .tlog laptop tu ghi chi chua cai DA CHAY QUA SONG — do
        that 04/09/2026, .tlog bay that lon nhat co 313 field / 57 ban ghi mot
        giay, con .bin cung chuyen bay do co 1606 field / 682 ban ghi. Nhung thu
        chi co trong .bin (OF, RATE, XKF*, PID*) la thu can nhat khi di tim vi
        sao no bay la, va chung khong bao gio du cho tren duong SiK 57600.

        Gia phai tra: dung chinh duong truyen do. 13 MB qua SiK ~4,5 kB/s la gan
        45 phut va gan het bang thong — nen day la mot nut bam co thanh tien
        trinh va nut huy, khong phai viec tu dong lam luc ket noi.
        """
        if self._log:
            raise RuntimeError("dang tai mot log khac roi")
        if not self.logdir:
            raise RuntimeError("khong co thu muc log de ghi")
        d = Path(self.logdir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{time.strftime('%Y%m%d-%H%M%S')}-fc{log_id}.bin"
        nblocks = (size + LOG_BLOCK - 1) // LOG_BLOCK
        self._log = {
            "id": log_id, "size": size, "path": path, "f": open(path, "wb"),
            "have": bytearray(nblocks), "got": 0, "scan": 0,
            "at": time.time(), "tries": 0, "said": 0.0,
        }
        self._log_ask(master, 0)

    def _log_ask(self, master, ofs):
        """Xin FC gui tu `ofs` den het file.

        count = 0xFFFFFFFF nghia la "gui tiep cho toi het": FC tu bom lien tuc
        chu khong doi hoi tung khoi. Hoi tung khoi mot thi moi khoi mat mot vong
        di-ve (~130 ms qua SiK) — 145 nghin khoi thanh 5 tieng thay vi 45 phut.
        """
        master.mav.log_request_data_send(
            master.target_system, AUTOPILOT, self._log["id"], ofs, 0xFFFFFFFF)
        self._log["at"] = time.time()

    def _log_missing(self):
        """Offset cua khoi con thieu dau tien, hay None neu da du."""
        g = self._log
        have = g["have"]
        i = g["scan"]
        while i < len(have) and have[i]:
            i += 1
        g["scan"] = i
        return None if i >= len(have) else i * LOG_BLOCK

    def _log_rx(self, master, name, d):
        """LOG_ENTRY (danh sach) va LOG_DATA (noi dung). True neu da nuot goi."""
        if name == "LOG_ENTRY":
            # num_logs = 0: the SD trong hay chua cam. FC van gui dung mot goi
            # de tra loi, nen phai phat len de giao dien thoi quay vong.
            if d.get("num_logs"):
                self._log_list.append(
                    {"id": d["id"], "size": d["size"], "time_utc": d.get("time_utc", 0)})
            self._emit("log", {"list": list(self._log_list), "n": d.get("num_logs", 0)})
            return True

        if name != "LOG_DATA" or not self._log:
            return False
        g = self._log
        if d["id"] != g["id"]:
            return True  # con sot cua phien truoc — khong ghi de len file dang mo

        ofs, count = d["ofs"], d["count"]
        # Chi hoi o boi cua 90 nen goi ve cung o boi cua 90; goi lech la dau hieu
        # firmware la, bo di con hon ghi lech ca file.
        idx, rem = divmod(ofs, LOG_BLOCK)
        if rem or idx >= len(g["have"]):
            return True
        g["at"], g["tries"] = time.time(), 0
        if not g["have"][idx]:
            g["have"][idx] = 1
            g["got"] += count
            g["f"].seek(ofs)
            g["f"].write(bytes(d["data"][:count]))

        now = time.time()
        if now - g["said"] >= 0.5:  # 2 Hz: thanh tien trinh khong can hon
            g["said"] = now
            self._emit("log", {"get": {"id": g["id"], "got": g["got"],
                                       "size": g["size"], "done": False}})
        if self._log_missing() is None:
            self._log_end(master)
        return True

    def _log_tick(self, master, now):
        """FC im giua chung -> hoi lai TU CHO CON THIEU, roi bo cuoc va noi ra.

        Khong hoi lai tu 0: mot goi rot o giua ma keo lai ca file thi qua SiK la
        them 45 phut. Bang `have` giu dung cho thung nen hoi tiep tu do.
        """
        g = self._log
        if not g or now - g["at"] < LOG_STALL:
            return
        if g["tries"] >= LOG_TRIES:
            self._log_end(master, err=f"FC im lang sau {LOG_TRIES} lan hoi lai")
            return
        g["tries"] += 1
        ofs = self._log_missing()
        if ofs is None:
            self._log_end(master)
        else:
            self._log_ask(master, ofs)

    def _log_end(self, master, err=None):
        """Dong file va bao ket qua. Thieu byte thi NOI RA, khong lang le giu file.

        File tai do dang van de lai tren dia: 90% cua mot log 13 MB van doc ra
        do thi duoc, va bat nguoi bay tai lai tu dau qua SiK la 45 phut nua.
        """
        g, self._log = self._log, None
        if not g:
            return
        g["f"].close()
        try:
            master.mav.log_request_end_send(master.target_system, AUTOPILOT)
        except Exception:
            pass  # link vua dut — file da dong roi, khong con gi de mat
        if err is None and g["got"] < g["size"]:
            err = f"thieu {g['size'] - g['got']} byte"
        self._emit("log", {"get": {
            "id": g["id"], "got": g["got"], "size": g["size"],
            "path": str(g["path"]), "done": True, "err": err,
        }})

    # ---- geofence --------------------------------------------------------

    def _params_done(self):
        return all(any(n in self._params for n in g) for g in WATCH_PARAMS)

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
        elif name == "PARAM_VALUE" and param_id(d) in WATCH_NAMES:
            self._params[param_id(d)] = d["param_value"]
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
        for sid, hz in stream_table(self.profile):
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
            master = mavutil.mavlink_connection(p["path"])
            # REPLAY khong gui gi ca — chan o day vi MOI duong gui (wp, rao, log,
            # stream) deu qua master.write. .tlog bay that chua ca hoi thoai tai
            # duong bay; phat lai toi MISSION_COUNT la _wp_rx "tra loi" vao mot file
            # chi doc -> io.UnsupportedOperation, adapter chet sau 166 goi (do
            # 16/09/2026 tren 20260915-123914-real.tlog).
            master.write = lambda _buf: None
            return master
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
        # Ban .bin phat lai thi KHONG ghi .tlog: `msg.get_msgbuf()` cua DFMessage
        # la ban ghi dataflash tho, nhet vao khuon .tlog se ra mot file khong ai
        # doc duoc — ke ca chinh app nay.
        if self.logdir and not _is_df(master):
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

        # Log dataflash: ten message khac, khong co lop MAVLink, khong xin stream.
        # Chot mot lan o day chu khong hoi lai moi goi.
        df = _is_df(master)
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

                if df:
                    # DFReader.recv_match() KHONG co tham so `timeout` — truyen
                    # vao la TypeError ngay ban ghi dau, va ca phien phat lai chet
                    # im lang truoc khi kip ve mot pixel nao.
                    msg = master.recv_match(blocking=False)
                else:
                    msg = master.recv_match(
                        blocking=blocking, timeout=0.5 if blocking else None)
                self._run_commands(master)

                if msg is not None:
                    if not df:
                        _upgrade_v2(master, msg)
                    name = msg.get_type()
                    # UNKNOWN_*: msgid khong co trong dialect. Khung nhieu trung CRC
                    # ra kieu nay, va no la thu duy nhat lam mot duong truyen hong
                    # trong giong duong truyen song — bo di thi sai baud/nhieu nang
                    # thanh IM LANG, dung kieu hong ma banner bat duoc.
                    # Ban .bin la log FC TU ghi: chi co du lieu cua chinh no,
                    # khong co nguon thu hai nao de loc — va DFMessage khong co
                    # `get_srcComponent` de ma hoi (giong core/logdata._wanted).
                    if (name == "BAD_DATA" or name.startswith("UNKNOWN_")
                            or (not df and not from_autopilot(msg))):
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

                    if self._tlog_f and name != "LOG_DATA":
                        # dinh dang .tlog: 8 byte timestamp micro-giay big-endian
                        # + goi MAVLink tho. Doc duoc bang Mission Planner.
                        #
                        # Tru LOG_DATA: tai mot log 13 MB ve la nhet dung 13 MB
                        # do vao .tlog cua chuyen bay dang ghi. No khong phai
                        # telemetry, chi la mot file dang di qua day.
                        self._tlog_f.write(struct.pack(">Q", int(ts * 1e6)) + msg.get_msgbuf())

                    if df:
                        for topic, data in normalize_df(name, d):
                            if topic == "heartbeat":
                                self._df_beat.update(data)
                            self._emit(topic, data, ts)

                    out = None if df else normalize(name, d)
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

                    # Rao, duong bay va viec xin stream deu la doi thoai MAVLink
                    # hai chieu. Ban .bin khong co dau kia de ma noi chuyen — va
                    # `master.mav` cung khong ton tai de goi. KHONG dung `continue`
                    # o day: duoi con khoi do byte/s, bo qua no thi dai trang thai
                    # trong tron trong suot phien phat lai .bin.
                    if not df:
                        # Tai log di truoc: giua phien tai, LOG_DATA la phan lon
                        # goi tren duong truyen.
                        self._log_rx(master, name, d)

                        if self._fence_rx(master, name, d):
                            self._fence_emit(master)

                        # Phien nap di truoc: dang nap thi MISSION_ACK la cua no,
                        # khong phai cua mot phien tai ve nao.
                        if (not self._wp_up_rx(master, name, d)
                                and self._wp_rx(master, name, d)):
                            self._wp_emit(master)

                        # Xin stream rate ngay sau heartbeat dau tien (luc do moi
                        # biet target_system). REPLAY khong gui gi ca.
                        if (name == "HEARTBEAT" and not streams_sent
                                and self.mode != "REPLAY"):
                            for sid, hz in stream_table(self.profile):
                                master.mav.request_data_stream_send(
                                    master.target_system, AUTOPILOT, sid, hz, 1
                                )
                            # EXTENDED_SYS_STATE khong nam trong bo stream cu nao
                            # — phai xin rieng, neu khong FC khong gui goi nao (do
                            # that: 0 goi trong 8s truoc khi xin, 17 goi sau).
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
                    self._log_tick(master, now)
                    if streams_sent:
                        self._stream_tick(master, now)

                # Rao, home va duong bay: hoi sau khi da co target_system (tuc sau
                # heartbeat dau), roi hoi lai cai con thieu cho toi khi du hoac
                # het luot. Ba thu nay FC khong tu gui bao gio.
                if (streams_sent and not self.muted
                        and not (self._fence_done() and self._wp_done() and self._params_done())
                        and self._asks < ASK_MAX
                        and now - self._ask_at >= ASK_EVERY):
                    self._ask_at, self._asks = now, self._asks + 1
                    if not self._fence_done():
                        self._fence_ask(master)
                    for g in WATCH_PARAMS:
                        if not any(n in self._params for n in g):
                            for n in g:
                                master.mav.param_request_read_send(
                                    master.target_system, AUTOPILOT, n.encode(), -1)
                    if not self._wp_done():
                        self._wp_ask(master)

                # Byte/s + ti le mat goi, 1 Hz — nguon cho widget Link status
                if now - last_bps_at >= 1.0:
                    # Ban .bin khong co lop MAVLink de hoi so byte va so goi mat.
                    # `offset` la vi tri dang doc trong file — dung no lam dong ho
                    # byte thi dai trang thai van chay, va ti le mat goi la 0 that
                    # (doc file thi khong mat goi nao, khac han duong truyen).
                    total = master.offset if df else master.mav.total_bytes_received
                    # Radio SiK nay KHONG chen RADIO_STATUS (do 13/08/2026: 0 goi
                    # trong 30s, va quet byte tho thay 0 khung mang chu ky 51/68).
                    # Firmware no chi nhan biet khung MAVLink1 nen khong tim duoc
                    # ranh gioi goi trong luong v2 cua FC. Ep FC noi v1 thi co RSSI
                    # nhung mat geofence (`mission_type` la truong cua v2) — doi
                    # nhu vay la lo, nen chat luong link doi tu chinh luong dang
                    # nhan: MAVLink danh so thu tu tung goi, thung so la mat goi.
                    # Khong bang RSSI o cho bao truoc, nhung hon o cho no do dung
                    # thu can biet — bao nhieu phan tram KHONG toi noi.
                    lost = 0 if df else master.mav_loss - last_loss
                    good = 0 if df else master.mav_count - last_count
                    self._emit(
                        "link",
                        {"bps": int((total - last_bytes) / (now - last_bps_at)),
                         "loss": round(100.0 * lost / (lost + good), 1) if lost + good else 0.0,
                         "mode": self.mode},
                        now,
                    )
                    last_bytes, last_bps_at = total, now
                    if not df:
                        last_loss, last_count = master.mav_loss, master.mav_count
                    elif self._df_beat:
                        # Ban .bin ghi MODE/ARM khi CO DOI, con duong that thi
                        # HEARTBEAT nhac lai moi giay. Khong nhac lai thi Field
                        # het tuoi sau STALE=2s va nhan che do bay tat ngom giua
                        # chuyen — trong khi FC luc do van dang o dung che do do.
                        # Do that tren log bay trong nha 30/08: ca file 17 phut
                        # chi co DUNG MOT ban ghi MODE, o giay 9,5.
                        #
                        # Day khong phai bia du lieu: no phat lai dung cai ma
                        # duong truyen SE gui neu luc do co radio cam vao.
                        self._emit("heartbeat", dict(self._df_beat), now)
                    if self._tlog_f:
                        # App crash thi phan con nam trong buffer se mat — ma do
                        # dung la doan cuoi truoc su co, doan quan trong nhat.
                        self._tlog_f.flush()
        except Exception as e:
            self.failed.emit(f"{self.profile['name']}: {e}")
        finally:
            if self._log:
                # Ngat giua chung: file dang tai phai duoc DONG, khong bo cho GC
                # nhat — phan cuoi con trong buffer la phan vua tai xong.
                self._log_end(master, err="ngat ket noi giua luc tai")
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

