#!/usr/bin/env python3
"""Bo kiem tra N1-N4, khong can SITL: chuan hoa ENU, bus, trong tai da nguon,
phan quyen + nut do, cac tab, widget tu ve, REPLAY, va WebSocket.

    python3 tools/selfcheck.py
"""

import math
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # chay duoc khong can man hinh

from core import bus
from core.adapters.sik import SikAdapter, flatten_status, normalize
from core.i18n import t

PORT = 14559  # cong rieng cho self-check, khong dung vao SITL that
VIDEO_PORT = 14560  # may chu MJPEG gia cua check_video


def deadline(app, ms):
    """Timer chan treo huy duoc.

    QTimer.singleShot khong huy duoc: check truoc ket thuc som thi cai timer 15s
    cua no van con treo, no vao giua check sau va goi app.quit() nham.
    """
    from PySide6.QtCore import QTimer

    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(app.quit)
    t.start(ms)
    return t


def check_normalize():
    topic, d = normalize(
        "GLOBAL_POSITION_INT",
        {"lat": 107620000, "lon": 1066600000, "alt": 12000, "relative_alt": 5000,
         "vx": 100, "vy": 200, "vz": -50, "hdg": 9000},
    )
    assert topic == "position"
    assert abs(d["lat"] - 10.762) < 1e-6
    assert d["alt_rel"] == 5.0
    # NED (bac=1, dong=2, xuong=-0.5) -> ENU (dong=2, bac=1, len=+0.5)
    assert (d["v_e"], d["v_n"], d["v_u"]) == (2.0, 1.0, 0.5), d
    assert d["heading"] == 90.0

    topic, d = normalize("LOCAL_POSITION_NED", {"x": 3.0, "y": 4.0, "z": -10.0})
    assert (d["x_e"], d["y_n"], d["z_u"]) == (4.0, 3.0, 10.0), d

    # yaw NED 90 deg (huong dong) -> yaw ENU 0, heading 90
    topic, d = normalize("ATTITUDE", {"roll": 0.1, "pitch": 0.0, "yaw": math.pi / 2,
                                      "rollspeed": 0.0, "pitchspeed": 0.0})
    assert abs(d["yaw"]) < 1e-9, d["yaw"]
    assert abs(d["heading"] - 90.0) < 1e-9

    assert normalize("SYS_STATUS", {"voltage_battery": 12600, "current_battery": 350,
                                    "battery_remaining": 87})[1]["voltage"] == 12.6

    # landed_state: cai co quyet dinh nut DISARM gui lenh thuong hay force.
    # 0 = FC KHONG BIET -> phai ra None, khong duoc thanh False cung khong thanh
    # True. Registry bo qua None nen field het tuoi, va "het tuoi" = khong biet.
    assert normalize("EXTENDED_SYS_STATE", {"landed_state": 1})[1] == {"landed": True}
    assert normalize("EXTENDED_SYS_STATE", {"landed_state": 2})[1] == {"landed": False}
    assert normalize("EXTENDED_SYS_STATE", {"landed_state": 3})[1] == {"landed": False}
    assert normalize("EXTENDED_SYS_STATE", {"landed_state": 0})[1] == {"landed": None}
    assert normalize("KHONG_CO_MESSAGE_NAY", {}) is None
    print("  ok  normalize NED -> ENU")


def check_source_filter():
    """Chi FC moi duoc noi. Do that tren stack ROS2: FC 1/1, MAVROS 1/191 (heartbeat
    cua no bat san co ARMED), MAVProxy 255/230. Khong loc thi den ARM nhay lien tuc
    va lenh bi gui vao component 191."""
    from core.adapters.sik import from_autopilot

    class Msg:
        def __init__(self, comp, typ="HEARTBEAT"):
            self.comp, self.typ = comp, typ

        def get_srcComponent(self):
            return self.comp

        def get_type(self):
            return self.typ

    assert from_autopilot(Msg(1)), "heartbeat cua FC phai qua"
    assert from_autopilot(Msg(0)), "component 0 (log cu, nguon gui don gian) phai qua"
    assert not from_autopilot(Msg(191)), "heartbeat cua MAVROS phai bi bo"
    assert not from_autopilot(Msg(230)), "heartbeat cua MAVProxy phai bi bo"
    # RADIO_STATUS do chinh radio duoi dat chen vao, khong phai FC — nhung do la
    # nguon RSSI duy nhat khi bay that.
    assert from_autopilot(Msg(68, "RADIO_STATUS")), "RADIO_STATUS phai giu lai"
    print("  ok  chi nhan goi tu FC (bo MAVROS/MAVProxy, giu RADIO_STATUS)")


def check_flatten():
    out = flatten_status("VFR_HUD", {"mavpackettype": "VFR_HUD", "airspeed": 1.5, "throttle": 40})
    assert out == {"VFR_HUD.airspeed": 1.5, "VFR_HUD.throttle": 40}, out

    # Mang phai trai ra tung phan tu: dien ap tung cell, tung kenh RC — bo mang di
    # la giau mat dung cai nguoi bay can khi pin mot cell tut.
    out = flatten_status("BATTERY_STATUS", {"voltages": [3700, 3695, 65535], "temperature": 25})
    assert out["BATTERY_STATUS.voltages[1]"] == 3695, out
    assert out["BATTERY_STATUS.temperature"] == 25

    # Chuoi cung la trang thai (ten firmware, canh bao). bytes -> str, bo \x00 dem.
    out = flatten_status("STATUSTEXT", {"severity": 4, "text": b"PreArm: Compass\x00\x00"})
    assert out["STATUSTEXT.text"] == "PreArm: Compass", out
    assert out["STATUSTEXT.severity"] == 4

    out = flatten_status("X", {"co": True, "khong": False})
    assert out == {"X.co": 1, "X.khong": 0}, out

    # Moi tham so mot hang rieng. Neu khong, ca 1431 tham so do chung vao
    # "PARAM_VALUE.param_value" — mot con so nhay lien tuc, khong biet cua ai.
    a = flatten_status("PARAM_VALUE", {"param_id": b"ATC_RAT_RLL_P\x00", "param_value": 0.135,
                                       "param_count": 1431, "param_index": 7})
    b = flatten_status("PARAM_VALUE", {"param_id": "ATC_RAT_PIT_P", "param_value": 0.14,
                                       "param_count": 1431, "param_index": 8})
    assert a == {"PARAM.ATC_RAT_RLL_P": 0.135}, a
    assert set(a) != set(b), "hai tham so khac nhau khong duoc dung chung mot hang"
    print("  ok  flatten STATUS (so, mang, chuoi, co, tung tham so mot hang)")


def check_sensor_decode():
    """Bitmask cam bien phai doc duoc bang mat, khong phai bang may tinh."""
    from core.adapters.sik import SENSOR_BITS, decode_sensors

    gps = SENSOR_BITS["gps"]
    mag = SENSOR_BITS["3d_mag"]
    log = SENSOR_BITS["logging"]
    d = {
        "onboard_control_sensors_present": gps | mag | log,
        "onboard_control_sensors_enabled": gps | mag,   # logging co lap nhung tat
        "onboard_control_sensors_health": gps | log,    # tu ke hong
    }
    out = decode_sensors(d)
    # Adapter phat MA MAY, khong phat chu cho nguoi doc: no chay trong QThread va
    # co y khong biet ngon ngu nao dang chon. Tab Trang thai dich luc ve.
    assert out["SENSOR.gps"] == "ok", out
    assert out["SENSOR.3d_mag"] == "fail", "cam bien hong phai ra ma `fail`"
    assert out["SENSOR.logging"] == "ok_off", out
    # Cam bien khong lap tren may bay nay thi khong duoc bay ra lam nhieu bang
    assert not any(k.endswith(".rc_receiver") for k in out), out

    # Va moi ma phat ra deu phai co chu o CA HAI thu tieng — thieu mot cai thi
    # bang Trang thai hien tro ra chinh cai key ("sensor.fail_off").
    from core import i18n

    for ma in ("ok", "fail", "ok_off", "fail_off"):
        assert f"sensor.{ma}" in i18n.STR, f"chua co chu cho ma cam bien `{ma}`"
    print(f"  ok  giai ma {len(SENSOR_BITS)} bit cam bien cua SYS_STATUS (ra ma may)")


def check_usb_detect(app):
    """Tu quet cong USB. Gia lap ba cong cam cung luc — may co nhieu cong USB thi
    so thu tu ttyUSB doi moi lan cam, ghi cung mot cong la sai tu goc."""
    from serial.tools import list_ports

    from laptop import connection

    class FakePort:
        def __init__(self, device, vid, desc, product=None):
            self.device, self.vid, self.description, self.product = device, vid, desc, product

    fake = [
        FakePort("/dev/ttyS4", None, "n/a"),                       # UART main board
        FakePort("/dev/ttyUSB0", 0x0403, "FT232R USB UART", "SiK Telemetry"),
        FakePort("/dev/ttyUSB1", 0x10c4, "CP2102 USB to UART"),
        FakePort("/dev/ttyACM0", 0x1209, "Pixhawk1", "Pixhawk1"),
    ]
    orig = list_ports.comports
    list_ports.comports = lambda: fake
    try:
        out = connection.detect_serial({"baud": 57600, "sysid": 254, "name": "khuon"})
        devs = [p["conn"] for p in out]
        assert devs == ["/dev/ttyACM0", "/dev/ttyUSB0", "/dev/ttyUSB1"], devs
        assert "/dev/ttyS4" not in devs, "cong UART main board khong duoc lot vao"
        assert out[1]["name"] == "SiK Telemetry", out[1]
        assert all(p["mode"] == "REAL" for p in out), "cong USB phai la REAL (banner do)"
        assert all(p["sysid"] == 254 for p in out), "phai lay sysid tu khuon"

        # Khuon khong dat baud -> ttyACM (Pixhawk cam thang, CDC) 115200, ttyUSB 57600
        auto = connection.detect_serial({})
        assert {p["conn"]: p["baud"] for p in auto} == {
            "/dev/ttyACM0": 115200, "/dev/ttyUSB0": 57600, "/dev/ttyUSB1": 57600}, auto

        # Khuon (muc REAL khong co conn) khong duoc hien nhu mot nguon chon duoc
        panel = connection.ConnectionPanel([
            {"name": "SiK radio", "mode": "REAL", "baud": 57600, "sysid": 254},
            {"name": "SITL", "mode": "SIM", "conn": "udp:127.0.0.1:14551"},
        ])
        assert panel.list.count() == 4, [panel.list.item(i).text() for i in range(panel.list.count())]
        assert panel.profiles[0]["conn"] == "/dev/ttyACM0", panel.profiles[0]
        assert panel.list.currentRow() == -1, "khong duoc tu chon san nguon nao"
    finally:
        list_ports.comports = orig
    print("  ok  tu quet cong USB (bo cong main board, lay baud theo loai)")


def check_bus():
    got = []
    bus.on("position", got.append)
    bus.emit("sik", "position", {"lat": 1})
    bus.emit("sik", "attitude", {"roll": 0})
    assert len(got) == 1 and got[0]["src"] == "sik" and got[0]["ts"] > 0, got
    bus.off("position", got.append)
    print("  ok  bus dispatch")


def check_link_status(app):
    """Hang link phai xam khi mat goi — ke ca khi adapter van bao byte/s."""
    from laptop.link_status import LinkStatus

    ls = LinkStatus()
    ls.on_envelope({"src": "sik", "topic": "link", "data": {"bps": 800}, "ts": time.time()})
    ls._tick()
    # envelope "link" do adapter tu sinh, khong phai bang chung drone con song
    assert ls._info["sik"].text() == t("link.never"), ls._info["sik"].text()

    ls.on_envelope({"src": "sik", "topic": "position", "data": {}, "ts": time.time()})
    ls._tick()
    assert ls._info["sik"].text() == t("link.alive", bps=800, loss=0.0), ls._info["sik"].text()

    # Mat goi la thu thay cho RSSI (radio SiK nay khong chen RADIO_STATUS). Duoi
    # nguong thi chi hien so; qua nguong phai DOI MAU — con so tu no khong keo
    # duoc mat nguoi dang nhin cho khac tren man hinh.
    from laptop.link_status import WARN, WARN_LOSS

    ls.on_envelope({"src": "sik", "topic": "link",
                    "data": {"bps": 700, "loss": WARN_LOSS - 0.1}, "ts": time.time()})
    ls.last_seen["sik"] = time.time()
    ls._tick()
    assert WARN not in ls._info["sik"].styleSheet(), "chua toi nguong ma da bao dong"

    ls.on_envelope({"src": "sik", "topic": "link",
                    "data": {"bps": 700, "loss": 12.5}, "ts": time.time()})
    ls._tick()
    assert ls._info["sik"].text() == t("link.alive", bps=700, loss=12.5), ls._info["sik"].text()
    assert WARN in ls._info["sik"].styleSheet(), "mat 12,5% goi ma van hien binh thuong"

    ls.last_seen["sik"] = time.time() - 5
    ls._tick()
    assert ls._info["sik"].text().startswith("MẤT"), ls._info["sik"].text()
    print(f"  ok  Link status: xam khi mat goi, doi mau khi mat >{WARN_LOSS:g}% goi")


def check_tabs(app):
    """Tab Status + Messages: bom thang envelope vao bus, khong can socket."""
    from laptop.tabs.messages import MessagesTab
    from laptop.tabs.status import StatusTab

    st, ms = StatusTab(), MessagesTab()

    bus.emit("sik", "status", {"ATTITUDE.roll": 0.1234567, "VFR_HUD.alt": 12.0})
    st._flush()
    assert st.model.rowCount() == 2, st.model.rowCount()
    assert st.model.item(0, 1).text() == "0.123457", st.model.item(0, 1).text()

    st.proxy.setFilterFixedString("VFR")
    assert st.proxy.rowCount() == 1, st.proxy.rowCount()
    st.proxy.setFilterFixedString("")

    # tam dung: bang phai dung yen de con doc
    st.freeze.setChecked(True)
    bus.emit("sik", "status", {"ATTITUDE.roll": 9.9})
    st._flush()
    assert st.model.item(0, 1).text() == "0.123457", "tam dung ma bang van nhay"
    st.freeze.setChecked(False)

    # SENSOR.* la hang duy nhat trong bang mang CHU chu khong mang so, nen no la
    # hang duy nhat phai dich lai khi doi ngon ngu. Ma may tu adapter ("ok",
    # "fail_off") khong bao gio duoc lot thang ra man hinh.
    from core import i18n

    bus.emit("sik", "status", {"SENSOR.gps": "ok", "SENSOR.3d_mag": "fail_off"})
    st._flush()
    hang = {st.model.item(r, 0).text(): r for r in range(st.model.rowCount())}

    def gia_tri(k):
        return st.model.item(hang[k], 1).text()

    assert gia_tri("SENSOR.gps") == "TỐT", gia_tri("SENSOR.gps")
    assert gia_tri("SENSOR.3d_mag") == "HỎNG (tắt)", gia_tri("SENSOR.3d_mag")

    # Doi ngon ngu: hang DA nam trong bang phai doi theo, ke ca khi khong con goi
    # SYS_STATUS nao ve nua (mat ket noi, hay REPLAY dang tam dung).
    i18n.set_lang("en")
    assert gia_tri("SENSOR.gps") == "OK", gia_tri("SENSOR.gps")
    assert gia_tri("SENSOR.3d_mag") == "FAULT (off)", gia_tri("SENSOR.3d_mag")
    i18n.set_lang("vi")
    assert gia_tri("ATTITUDE.roll") == "0.123457", "hang so khong dinh dang gi den ngon ngu"

    # Field ngung cap nhat phai XAM DI, khong de den nhu dang song. Da bo cot
    # "Tuoi" (so giay) va cot "Nguon"; chot an toan chuyen han sang mau cua chinh
    # cot Gia tri, nen kiem dung o do — mat mau la mat canh bao, mat co that.
    from laptop.tabs.status import STALE_COLOR

    assert st.model.columnCount() == 2, st.model.columnCount()
    song = st.model.item(0, 1).foreground().color().name()
    st._seen["ATTITUDE.roll"] = time.time() - 10
    st._age()
    xam = st.model.item(0, 1).foreground().color().name()
    assert xam == STALE_COLOR and xam != song, (song, xam)

    for sev, txt in ((6, b"EKF3 IMU0 is using GPS"), (4, b"PreArm: Compass"), (2, b"battery low")):
        bus.emit("sik", "text", {"severity": sev, "text": txt})
    assert ms.list.count() == 3, ms.list.count()
    ms.filter.setCurrentIndex(2)  # canh bao tro len
    hidden = [i for i in range(3) if ms.list.item(i).isHidden()]
    assert hidden == [0], hidden
    print("  ok  tab Status (loc/tam dung/het tuoi thi xam) + Messages (loc severity)")


def check_field(app):
    """Trong tai da nguon: uu tien, het tuoi, va lech vi tri tinh bang met."""
    from core.field import Field, Registry

    f = Field("alt")
    f.put("sik", 10.0)
    f.put("remote", 10.4)
    assert f.best() == (10.4, "remote"), f.best()  # remote uu tien
    assert abs(f.divergence() - 0.4) < 1e-9

    f.by_src["remote"] = (10.4, time.time() - 10)  # remote het tuoi
    assert f.best() == (10.0, "sik"), f.best()
    assert f.divergence() is None, "mot nguon thi khong co gi de so"

    r = Registry()
    now = time.time()
    for src, lat in (("sik", 10.7620), ("remote", 10.76210)):
        r.feed({"src": src, "topic": "position", "data": {"lat": lat, "lon": 106.66}, "ts": now})
    d = r.position_divergence_m()
    assert 10 < d < 13, f"lech phai ~11 m, ra {d}"  # 1e-4 do vi do ~ 11 m

    r.feed({"src": "sik", "topic": "status", "data": {"X.y": 1}, "ts": now})
    assert "status.X.y" not in r.fields, "firehose khong duoc chui vao trong tai"
    print(f"  ok  Field uu tien/het tuoi, lech vi tri {d:.1f} m")


def check_authority(app):
    """Laptop cam toan quyen: khong con duong nao nhuong quyen di.

    Check nay canh gac mot thu de quay lai luc sua: mot ham `set_authority` moc
    lai, hay mot nhanh tu choi lenh vi "quyen dang thuoc ve ros2". Ca hai deu
    lam laptop mat lai giua chuyen bay.
    """
    from core import authority

    sent = []

    class FakeAdapter:
        def send(self, action, args=None):
            sent.append(action)
            return {"ok": action}

    assert not hasattr(authority, "set_authority"), "nhuong quyen quay lai roi"
    assert not hasattr(authority, "ROS2"), "van con khai niem ben kia cam quyen"
    assert authority.AUTHORITY == authority.GCS

    authority.register("sik", FakeAdapter())
    try:
        # Moi lenh xuong FC deu di duoc, khong co cua nao chan lai.
        for act in ("arm", "takeoff", "wp_write", "mode"):
            assert "ok" in authority.dispatch({"target": "sik", "action": act}), act
        for esc in ("rtl", "land", "disarm"):
            assert "ok" in authority.dispatch({"action": esc}), esc
        assert sent == ["arm", "takeoff", "wp_write", "mode", "rtl", "land", "disarm"], sent

        # Nut do van phai xuong SiK ke ca khi bi goi kem mot target khac.
        sent.clear()
        assert "ok" in authority.dispatch({"target": "remote", "action": "rtl"})
        assert sent == ["rtl"], "nut do di vong qua companion — cam (2.1)"
    finally:
        authority.unregister("sik")
    print("  ok  laptop toan quyen: khong con duong nhuong quyen, nut do van thang SiK")


def check_arm_throttle_guard(app):
    """ARM bi chan khi can ga chua ve min.

    Chot nay o phia app vi FC khong co: `AP_Arming.cpp:81-115` chi kiem ga THAP
    hon nguong failsafe. Do that tren MicoAir743 luc 22:35: ga 1496 -> ack=0 ->
    dong co ra 1654/1506/1347/1080. Khong biet vi tri ga thi VAN gui — mat
    RC_CHANNELS ma khoa luon nut ARM la doi mot kieu hong lay mot kieu hong khac.
    """
    from core import authority

    from laptop.tabs.control import THR_ARM_MAX, ControlTab

    sent = []

    class FakeAdapter:
        def send(self, action, args=None):
            sent.append(action)
            return {"ok": action}

    authority.register("sik", FakeAdapter())
    ct = ControlTab()
    ct.set_mode("SIM")
    logs = []
    ct.log.connect(lambda text, _sev: logs.append(text))
    try:
        # Chua thay RC bao gio: van phai gui duoc
        ct.btn_arm.click()
        assert sent == ["arm"], sent
        assert "chưa thấy RC_CHANNELS" in logs[0], logs

        bus.emit("sik", "status", {"RC_CHANNELS.chan3_raw": 1496})
        sent.clear(); logs.clear()
        ct.btn_arm.click()
        assert not sent, "ga 1496 ma van gui ARM"
        assert "CHẶN" in logs[0] and "1496" in logs[0], logs

        bus.emit("sik", "status", {"RC_CHANNELS.chan3_raw": THR_ARM_MAX + 1})
        sent.clear()
        ct.btn_arm.click()
        assert not sent, f"ga {THR_ARM_MAX + 1} (tren nguong 1 don vi) ma van gui"

        bus.emit("sik", "status", {"RC_CHANNELS.chan3_raw": 993})
        sent.clear(); logs.clear()
        ct.btn_arm.click()
        assert sent == ["arm"], f"ga 993 la o min, phai gui duoc: {logs}"

        # Ga cu qua thi khong con la bang chung: gui, nhung phai noi ra
        ct._thr = (1496, time.time() - 30)
        sent.clear(); logs.clear()
        ct.btn_arm.click()
        assert sent == ["arm"] and "quá cũ" in logs[0], (sent, logs)

        # DISARM khong bao gio bi chot nay dung toi
        bus.emit("sik", "status", {"RC_CHANNELS.chan3_raw": 1496})
        sent.clear()
        ct.btn_disarm.click()
        assert sent == ["disarm"], sent
    finally:
        authority.unregister("sik")
        ct.close()
    print(f"  ok  chan ARM khi ga > {THR_ARM_MAX} PWM (FC khong tu chan viec nay)")


def check_disarm_hold(app):
    """DISARM hai bac: bam nhanh = lenh thuong, giu 2s = force 21196.

    Vi sao duoi dat phai force ngay: do tren FC that (MicoAir743, thao canh), lenh
    disarm thuong AN khi ga o min nhung bi tu choi 3/3 lan khi ga len giua tam —
    luc do motor quay lech nhau de on dinh tu the, ArduCopter coi la dang bay va
    chan disarm tu GCS (AP_Arming.cpp:788). Tren ban thi do chi la phien; nhung no
    nghia la vi tri can ga quyet dinh nut co an hay khong, va do la dieu khong ai
    doan duoc luc can ngat gap.

    Vi sao tren troi thi khong: force luc dang bay la tat dong co giua khong
    trung. Duong ranh la do cao DO DUOC, khong phai vi tri can ga.

    Va vi sao bac force phai kho bam: force luc dang bay = tat dong co = roi.
    """
    from core import authority

    from laptop.tabs.control import ControlTab

    sent = []

    class FakeAdapter:
        def send(self, action, args=None):
            sent.append((action, dict(args or {})))
            return {"ok": action}

    from core.field import REGISTRY

    def landed(v, rng_cm=None):
        """Dat hai nguon: cai FC bao, va cam bien khoang cach (cm)."""
        REGISTRY.fields.clear()
        ct._rng = None
        if v is not None:
            REGISTRY.feed({"src": "sik", "topic": "heartbeat", "data": {"landed": v},
                           "ts": time.time()})
        if rng_cm is not None:
            ct._rng = (rng_cm, 5, 400, time.time())

    authority.register("sik", FakeAdapter())
    ct = ControlTab()
    ct.set_mode("SIM")
    try:
        # --- FC bao da ha canh: bam mot phat la force, ga o muc nao cung ngat ---
        landed(True)
        ct.btn_kill.click()
        assert sent == [("disarm", {"force": True})], sent
        sent.clear()
        ct.btn_disarm.click()  # nut thuong cung theo quy tac do
        assert sent == [("disarm", {"force": True})], sent

        # --- khong co tin: KHONG duoc doan la da ha canh ---
        landed(None)
        sent.clear()
        ct.btn_kill.click()
        assert sent == [("disarm", {})], f"mat telemetry ma van force: {sent}"
        sent.clear()
        ct.btn_disarm.click()
        assert sent == [("disarm", {})], sent

        # --- FC bao dang bay NHUNG cam bien noi 60cm: van la duoi dat ---
        # Day dung la trang thai tren ban khi ga len giua tam — do that: FC bao
        # IN_AIR, cam bien khong nhuc nhich o 60cm.
        landed(False, rng_cm=60)
        sent.clear()
        ct.btn_kill.click()
        assert sent == [("disarm", {"force": True})], sent

        # Cam bien hong tra 0 cm: NGOAI dai hop le (5-400), khong duoc tin
        landed(False, rng_cm=0)
        sent.clear()
        ct.btn_kill.click()
        assert sent == [("disarm", {})], f"tin cam bien hong: {sent}"

        # Cam bien ngoai tam (400cm = het dai) cung khong phai bang chung duoi dat
        landed(None, rng_cm=400)
        sent.clear()
        ct.btn_kill.click()
        assert sent == [("disarm", {})], sent

        # --- FC bao dang bay, cam bien cung noi tren cao: lenh thuong ---
        landed(False, rng_cm=250)
        sent.clear()
        ct.btn_kill.click()  # bam nhanh: press + release + clicked
        assert sent == [("disarm", {})], sent

        # Giu: bam xuong, cho het gio, roi moi tha
        sent.clear()
        ct.btn_kill.pressed.emit()
        assert ct._kill_hold.isActive(), "giu nut ma dong ho khong chay"
        assert "GIỮ" in ct.btn_kill.text(), ct.btn_kill.text()
        ct._kill_hold.timeout.emit()  # = 2 giay da troi qua
        assert sent == [("disarm", {"force": True})], sent
        ct.btn_kill.released.emit()
        ct.btn_kill.clicked.emit()  # tha tay: KHONG duoc gui them lenh thuong
        assert sent == [("disarm", {"force": True})], sent
        assert ct.btn_kill.text() == "DISARM", ct.btn_kill.text()

        # Tha tay som (chua du 2s) thi chi co lenh thuong, khong co force
        sent.clear()
        ct.btn_kill.pressed.emit()
        ct.btn_kill.released.emit()
        assert not ct._kill_hold.isActive(), "tha tay roi ma dong ho van chay"
        ct.btn_kill.clicked.emit()
        assert sent == [("disarm", {})], sent
    finally:
        authority.unregister("sik")
        REGISTRY.fields.clear()
        ct.close()
    print("  ok  DISARM: duoi dat bam mot phat la force (ga o dau cung ngat duoc), "
          "tren troi phai giu 2s")


def check_remote(app):
    """RemoteAdapter noi WebSocket that toi mot server gia."""
    import json
    import threading as th

    from websockets.sync.server import serve

    from core.adapters.remote import RemoteAdapter

    port = 8791
    got_cmd = []

    def handler(ws):
        ws.send(json.dumps({"src": "COMPANION_TU_XUNG", "topic": "vision",
                            "data": {"target_x": 0.4}, "ts": time.time()}))
        try:
            got_cmd.append(json.loads(ws.recv(timeout=3)))
        except Exception:
            pass

    server = serve(handler, "127.0.0.1", port)
    th.Thread(target=server.serve_forever, daemon=True).start()

    seen = []
    ad = RemoteAdapter(f"ws://127.0.0.1:{port}")
    ad.envelope.connect(seen.append)
    ad.start()
    guard = deadline(app, 2500)
    app.exec()
    guard.stop()
    ad.send("authority", {"value": "gcs"})
    time.sleep(0.4)
    ad.stop()
    server.shutdown()

    vision = [e for e in seen if e["topic"] == "vision"]
    assert vision, [e["topic"] for e in seen]
    # companion tu xung la nguon khac cung khong duoc: src luon la "remote"
    assert vision[0]["src"] == "remote", vision[0]["src"]
    assert vision[0]["data"]["target_x"] == 0.4
    assert got_cmd and got_cmd[0]["action"] == "authority", got_cmd
    print("  ok  RemoteAdapter nhan envelope + gui lenh nguoc lai")


def check_online_tiles(app):
    """Tai bu tile khi co mang, nhung mat mang thi ban do KHONG duoc hong.

    Check nay khong can mang: dung mot host khong ton tai de ep nhanh loi.
    """
    from laptop.widgets import map_widget as mw

    f = mw.TileFetcher("http://khong-co-host-nay.invalid/{z}/{x}/{y}.png")
    f.want(16, 1, 1)
    f.want(16, 1, 1)
    assert f.q.qsize() == 1, "xin hai lan cung mot tile chi duoc xep hang mot"
    f.want(mw.MAX_ONLINE_Z + 1, 0, 0)
    assert f.q.qsize() == 1, "khong xin tile sau hon muc may chu con anh goc"

    assert f._get(16, 1, 1) is False, "mat mang phai tra False, khong duoc nem loi"
    assert f._fails == 1, f._fails

    # Xin sau hon muc co anh goc: may chu tra HTTP 200 kem MOT tam "khong co du
    # lieu" giong het nhau cho moi tile (do that: Esri va Bing deu the tu z20 o
    # TP.HCM). Phai phat hien va dung, khong thi dia day ban sao cua mot tam anh.
    import tempfile

    junk = b"anh bao khong co du lieu"
    tmp = Path(tempfile.mkdtemp())
    kept = [f._keep(junk, tmp / f"{i}.png", 20, i, 0) for i in range(mw.JUNK_REPEAT + 2)]
    assert kept[0] is True and kept[-1] is False, kept
    assert sum(kept) == mw.JUNK_REPEAT - 1, f"phai dung sau {mw.JUNK_REPEAT} lan: {kept}"
    assert f._keep(b"anh ban do that", tmp / "that.png", 20, 9, 9) is True, \
        "anh khac nhau thi van phai giu"
    assert (20, 0, 0) in f._dead, "tile rac phai bi ghi so den, khong xin lai"
    # Va phai LUI muc, khong thi cu xin mai muc khong co anh: xem z21 ma nguon het
    # anh o z19 thi phai tu tut xuong xin z19, khong nam mai o anh z17 phong to.
    assert f.max_ok_z == 19, f"phai lui xuong 19, dang {f.max_ok_z}"
    f.want(20, 5, 5)
    assert f.q.qsize() == 1, "da lui muc thi khong duoc xin lai z20"

    # Tat han duong online: ban do phai chay y nhu truoc khi co tinh nang nay.
    old = mw.ONLINE_TILES
    mw.ONLINE_TILES = False
    try:
        m = mw.MapWidget()
        m.resize(200, 150)
        m.set_position(10.762, 106.660)
        assert m.fetcher is None, "ONLINE_TILES=False ma van mo thread tai"
        assert not m.grab().isNull(), "offline ma khong ve duoc ban do"
    finally:
        mw.ONLINE_TILES = old
    print("  ok  tai bu tile online (khong mang: bo qua, ban do van ve)")


def check_takeoff_guard(app):
    """TAKEOFF: hai kieu hong im lang deu phai thanh mot dong chu.

    Do that tren SITL: o STABILIZE thi FC tra THAT BAI; o GUIDED nhung co node
    ROS2 dang stream setpoint thi FC tra CHAP NHAN roi drone nam im tren dat.
    Ca hai deu khong duoc de giao dien trong nhu thanh cong (nguyen tac 2.2).
    """
    from core.field import REGISTRY
    from laptop.tabs.control import ControlTab

    ct = ControlTab()
    ct.set_mode("SIM")
    logs = []
    ct.log.connect(lambda text, _sev: logs.append(text))
    sent = []
    authority_mod = __import__("core.authority", fromlist=["x"])

    class FakeAdapter:
        def send(self, action, args=None):
            sent.append(action)
            return {"ok": action}

    authority_mod.register("sik", FakeAdapter())
    try:
        REGISTRY.fields.clear()
        REGISTRY.feed({"src": "sik", "topic": "heartbeat", "data": {"mode": "STABILIZE"},
                       "ts": time.time()})
        ct.btn_takeoff.click()
        assert not sent, "khong duoc gui takeoff khi FC khong o GUIDED"
        assert "GUIDED" in logs[-1], logs

        REGISTRY.feed({"src": "sik", "topic": "heartbeat", "data": {"mode": "GUIDED"},
                       "ts": time.time()})
        REGISTRY.feed({"src": "sik", "topic": "position", "data": {"alt_rel": 0.0},
                       "ts": time.time()})
        ct.btn_takeoff.click()
        assert sent == ["takeoff"], sent
        # Do cao khong nhuc nhich -> phai keu, du FC da tra CHAP NHAN
        logs.clear()
        ct._check_climb(0.0)
        assert "độ cao không đổi" in logs[-1], logs
        # Con leo len that thi im lang
        logs.clear()
        REGISTRY.feed({"src": "sik", "topic": "position", "data": {"alt_rel": 4.0},
                       "ts": time.time()})
        ct._check_climb(0.0)
        assert not logs, logs

        # O REAL phai xac nhan — nhung KHONG duoc xac nhan bang hop thoai chan.
        # Do that: trong luc mot QMessageBox mo, activeModalWidget() khac None nen
        # cua so chinh khong nhan input, tuc ba nut do bam khong an du chung bao
        # `isEnabled() == True`. Doi mot lop hoi lai lay nut do la doi nguoc.
        from PySide6.QtWidgets import QApplication

        ct.set_mode("REAL")
        sent.clear(); logs.clear()
        ct.btn_takeoff.click()
        assert QApplication.activeModalWidget() is None, "hop thoai chan mo ra -> nut do chet"
        assert not sent, "lan bam dau o REAL phai la hoi lai, khong duoc cat canh"
        assert "BẤM LẠI" in ct.btn_takeoff.text(), ct.btn_takeoff.text()
        ct.btn_takeoff.click()
        assert sent == ["takeoff"], sent
        assert ct.btn_takeoff.text() == "TAKEOFF", ct.btn_takeoff.text()

        # Het gio cho thi quen di, khong duoc de danh lan bam cu
        sent.clear()
        ct.btn_takeoff.click()
        ct._takeoff_confirm.timeout.emit()  # = qua CONFIRM_S giay
        assert ct.btn_takeoff.text() == "TAKEOFF", ct.btn_takeoff.text()
        ct.btn_takeoff.click()
        assert not sent, "bam lai sau khi het gio ma van cat canh"
    finally:
        authority_mod.unregister("sik")
        REGISTRY.fields.clear()
        ct.close()
    print("  ok  TAKEOFF: chan khi khong o GUIDED, keu khi nhan lenh ma khong len, "
          "xac nhan REAL bang bam lai (khong hop thoai)")


def check_mission_readonly(app):
    """Tab Control khong con gui duoc lenh nao sang ROS2, chi doc trang thai.

    Bo nut di roi thi phai chac la bo THAT: mot nut con sot lai se gui lenh cho
    mot node khong con quyen lai — bam khong co gi xay ra, va khong ai biet vi sao.
    """
    import ast

    from core import authority
    from laptop.tabs.control import MISSIONS, ControlTab

    sent = {"sik": [], "remote": []}

    class Fake:
        def __init__(self, who):
            self.who = who

        def send(self, action, args=None):
            sent[self.who].append((action, args))
            return {"ok": action}

    authority.register("sik", Fake("sik"))
    authority.register("remote", Fake("remote"))
    ct = ControlTab()
    try:
        ct.set_mode("SIM")
        assert not hasattr(ct, "mission_btns"), "nut nhiem vu ROS2 van con"
        assert not hasattr(ct, "manual"), "switch MANUAL/AUTO van con"
        # Bam het nut trong tab: khong duoc co lenh nao ra cong `remote`.
        for b in ct.findChildren(type(ct.btn_arm)):
            if b not in ct.reds and b is not ct.btn_kill:
                b.click()
        assert not sent["remote"], f"van con nut gui lenh sang ROS2: {sent['remote']}"

        # Trang thai companion thi VAN phai hien — day la telemetry, khong phai lai.
        bus.emit("remote", "mission", {"running": "mission_circle"})
        assert "mission_circle" in ct.mission_now.text(), ct.mission_now.text()
        bus.emit("remote", "mission", {"running": ""})
        assert "không có nhiệm vụ" in ct.mission_now.text(), ct.mission_now.text()

        # Bridge phai tu choi doi quyen, khong duoc im lang bo qua.
        src = (Path(__file__).resolve().parent / "ros2_bridge.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "handle_command")
        body = ast.unparse(fn)
        assert "authority_pub.publish" not in body, "bridge van doi duoc /gcs/authority"
        assert "tu choi doi /gcs/authority" in body, "bridge bo qua im lang lenh authority"
        # Ten node van phai khop ben bridge: cho nay chi con dung de dich ten.
        allowed = next(
            ast.literal_eval(node.value)
            for node in ast.parse(src).body
            if isinstance(node, ast.Assign) and node.targets[0].id == "MISSIONS_OK"
        )
        thieu = [n for _, n in MISSIONS if n not in allowed]
        assert not thieu, f"ten nhiem vu bridge khong biet: {thieu}"
    finally:
        authority.unregister("sik")
        authority.unregister("remote")
        ct.close()
    print("  ok  nua ROS2 chi con la nguon telemetry (khong nut, bridge chot quyen)")


def check_replay_locks(app):
    """REPLAY khoa toan bo nut dieu khien, KE CA nut do."""
    from laptop.app import MainWindow

    tlogs = sorted((Path(__file__).resolve().parent.parent / "logs").glob("*.tlog"))
    if not tlogs:
        print("  --  bo qua check REPLAY khoa nut: chua co .tlog nao trong logs/")
        return

    win = MainWindow([{"name": "replay", "mode": "REPLAY", "path": str(tlogs[-1])}])
    assert win.panel.select("replay"), "khong thay profile replay trong danh sach"
    win.panel.btn_connect.click()
    ct = win.control_tab
    try:
        assert not any(b.isEnabled() for b in ct.reds), "nut do phai bi khoa o REPLAY"
        assert not ct.btn_arm.isEnabled() and not ct.btn_takeoff.isEnabled()
        assert win.replay_bar.isVisible() or win.replay_bar.adapter is not None
        # ke ca goi thang qua API cung phai bi tu choi
        assert "error" in win.adapter.send("rtl"), "REPLAY ma van gui duoc lenh"
    finally:
        win.disconnect()
        win.close()
    print("  ok  REPLAY khoa het nut, ke ca nut do")


def check_widgets(app):
    """Widget tu ve: ep paintEvent chay that bang grab()."""
    from PySide6.QtCore import QPoint

    from laptop.widgets.attitude import AttitudeWidget
    from laptop.widgets.compass import Compass
    from laptop.widgets.map_widget import MapWidget, deg2num, num2deg
    from laptop.widgets.telemetry_bar import TelemetryBar

    lat, lon, z = 10.762, 106.66, 16
    x, y = deg2num(lat, lon, z)
    back = num2deg(x, y, z)
    assert abs(back[0] - lat) < 1e-9 and abs(back[1] - lon) < 1e-9, back

    c = Compass()
    c.set_heading(137.0)
    assert not c.grab().isNull()

    a = AttitudeWidget()
    a.set_attitude(0.3, -0.15)
    assert not a.grab().isNull()

    t = TelemetryBar()
    t.set_cell("ALT", 12.3, "sik")
    t.set_cell("PIN", None, None)
    assert not t.grab().isNull()

    m = MapWidget()
    m.resize(400, 300)
    m.set_home(lat, lon)
    for i in range(5):
        m.set_position(lat + i * 1e-4, lon + i * 1e-4)
    assert not m.grab().isNull(), "map khong ve duoc khi thieu tile"
    assert len(m.trail) == 5, m.trail
    # dung tam that (w/2, h/2): rect().center() lech 1 px, o zoom 16 la ~2e-5 do
    p = m.latlon_at(QPoint(m.width() // 2, m.height() // 2))
    assert abs(p[0] - m.center[0]) < 1e-9 and abs(p[1] - m.center[1]) < 1e-9, p

    # Co tile trong assets/tiles thi phai doc duoc that, khong chi ve luoi. Duong
    # dan sai mot bac thu muc la ra hien truong moi biet — luc do khong sua duoc.
    from laptop.widgets.map_widget import TILE_DIR, pick_tile_zoom

    # Cuon zoom ra ngoai dai da tai KHONG duoc lam ban do bien mat: lay muc gan
    # nhat roi phong ti le. Mat ban do giua luc bay la mat nhan thuc vi tri.
    avail = [13, 14, 15, 16, 17]
    assert pick_tile_zoom(17, avail) == 17
    assert pick_tile_zoom(19, avail) == 17, "zoom sau day phai phong to tile z17"
    assert pick_tile_zoom(12, avail) == 13, "zoom ra phai thu nho tile z13"
    assert pick_tile_zoom(10, avail) is None, "thu nho qua 2 bac la hang tram tile"
    assert pick_tile_zoom(16, []) is None, "khong co tile nao thi ve luoi"
    # Duong cuu canh: o cho chi co tile tho, phong to len van hon man hinh den.
    assert pick_tile_zoom(16, [10]) == 10, "chi co tile tho thi phong to no len"

    # Muc zoom co tile phai hoi tung cho, khong suy tu ten thu muc: tai z13-17 cho
    # bai Canberra roi bay o TP.HCM thi z16 "ton tai" nhung khong co tile o day.
    m.center = (10.762, 106.660)
    here = m._levels_here()
    assert all((TILE_DIR / str(z)).is_dir() for z in here), here
    assert set(here) <= set(m.available_zooms()), (here, m.available_zooms())

    tiles = list(TILE_DIR.glob("*/*/*.png"))
    if tiles:
        z, x, y = int(tiles[0].parent.parent.name), int(tiles[0].parent.name), int(tiles[0].stem)
        pix = m._tile(z, x, y)
        assert pix is not None and not pix.isNull(), f"khong doc duoc tile {tiles[0]}"
        note = f"doc duoc tile that ({len(tiles)} tile trong assets/tiles)"
    else:
        note = "map khong co tile van ve luoi"
    print(f"  ok  compass/attitude/telemetry/map deu ve duoc ({note})")


def check_fence(app):
    """Geofence: tu goi MAVLink toi net ve tren ban do.

    Do that tren SITL (ArduCopter stable): tai ve 4 dinh bang mission_type=FENCE,
    va FENCE_RADIUS/FENCE_ALT_MAX doc bang PARAM_VALUE. Check nay dung dung nhung
    con so do, khong bia.
    """
    from laptop.tabs.flight import FlightTab
    from laptop.widgets.map_widget import FENCE_IN, FENCE_OFF, fence_shapes, meters_per_px

    # PARAM_VALUE FENCE_* va HOME_POSITION phai ra topic rieng, khong chim vao STATUS
    assert normalize("PARAM_VALUE", {"param_id": "FENCE_RADIUS\x00", "param_value": 150.0}) == (
        "fence", {"FENCE_RADIUS": 150.0}), "tham so rao phai ra topic fence"
    assert normalize("PARAM_VALUE", {"param_id": "ATC_RAT_RLL_P", "param_value": 1.0}) is None
    topic, home = normalize("HOME_POSITION", {"latitude": 108221589, "longitude": 1066868454,
                                              "altitude": 10100})
    assert topic == "home" and abs(home["lat"] - 10.8221589) < 1e-7, home

    # Hai da giac ke nhau: chi co param1 (tong so dinh) noi cho biet cat o dau.
    items = [(5001, 4, 10.8231, 106.6858), (5001, 4, 10.8231, 106.6878),
             (5001, 4, 10.8211, 106.6878), (5001, 4, 10.8211, 106.6858),
             (5002, 3, 10.8225, 106.6865), (5002, 3, 10.8226, 106.6866),
             (5002, 3, 10.8224, 106.6867),
             (5004, 25.0, 10.8220, 106.6870)]
    shapes = fence_shapes(items)
    assert [s[0] for s in shapes] == ["poly", "poly", "circle"], shapes
    assert len(shapes[0][2]) == 4 and shapes[0][1] is False, shapes[0]
    assert len(shapes[1][2]) == 3 and shapes[1][1] is True, "5002 la vung CAM vao"
    assert shapes[2][3] == 25.0, shapes[2]
    # Dinh le khong du 3 cai thi bo han, khong ve mot doan thang roi goi la rao
    assert fence_shapes([(5001, 4, 10.0, 106.0)]) == []

    # 156543 m/px o xich dao muc z0 la hang so Web Mercator; z16 o vi do bai bay
    assert abs(meters_per_px(0, 0) - 156543.0339) < 1e-3
    assert abs(meters_per_px(10.822, 16) - 2.3452) < 1e-3, meters_per_px(10.822, 16)

    home = (10.8221589, 106.6868454)
    ft = FlightTab()
    ft.resize(600, 400)
    ft.map.zoom = 16

    # Duong that: adapter -> bus -> tab -> map (khong goi thang set_home/set_fence)
    bus.emit("sik", "home", {"lat": home[0], "lon": home[1], "alt_msl": 10.1})
    bus.emit("sik", "fence", {"FENCE_ENABLE": 1.0, "FENCE_TYPE": 7.0,
                              "FENCE_RADIUS": 150.0, "FENCE_ALT_MAX": 100.0})
    bus.emit("sik", "fence", {"items": items})
    assert ft.map.home == home and ft.map.fence["FENCE_RADIUS"] == 150.0, ft.map.fence
    assert "r150m" in ft.map._fence_note() and "trần 100m" in ft.map._fence_note()

    # Vanh vong tron phai roi dung cho: 150 m o z16, vi do 10.8 = 63 px tinh tu
    # tam. Sai cong thuc doi met -> pixel thi rao ve sai cho ma van "nhin duoc",
    # kieu hong te nhat: nguoi bay tin vao mot duong ve sai.
    ft.map.center = home
    r_px = int(150 / meters_per_px(home[0], 16))
    assert r_px == 63, r_px
    # Kich thuoc lay tu chinh anh: tab chua show thi map.width() con la 100 px,
    # chi den luc grab() Qt moi dan lai layout — lay nham thi do sai cho.
    img = ft.map.grab().toImage()
    cx, cy = img.width() // 2, img.height() // 2
    assert img.pixel(cx + r_px, cy) == FENCE_IN.rgb(), "vanh rao khong nam o dung ban kinh"

    # FENCE_ENABLE = 0: van ve (de biet rao nam dau) nhung phai khac han ve mau,
    # va dai chu phai noi thang la TAT.
    bus.emit("sik", "fence", {"FENCE_ENABLE": 0.0})
    assert ft.map._fence_note() == t("map.fence_off"), ft.map._fence_note()
    img = ft.map.grab().toImage()
    assert img.pixel(cx + r_px, cy) == FENCE_OFF.rgb(), "rao TAT phai doi mau, khong duoc bien mat"

    # Ngat ket noi: rao, home, vet bay cua drone cu phai bien mat
    ft.set_mode(None)
    assert ft.map.fence == {} and ft.map.home is None, ft.map.fence
    ft.close()

    # Xin home la mot command_long -> FC tra ack cho lenh 512, khong phai lenh cua
    # nut nao. Ack do ma xoa hang cho thi canh bao "khong co phan hoi" cua ARM bi
    # nuot — hong im lang, dung thu muc 2.2 cam.
    from laptop.tabs.control import ControlTab

    ct = ControlTab()
    ct.set_mode("SIM")
    logs = []
    ct.log.connect(lambda text, _sev: logs.append(text))
    ct._pending = {"arm": time.time() + 3}
    bus.emit("sik", "ack", {"command": 512, "result": 0})
    assert ct._pending and not logs, (ct._pending, logs)
    bus.emit("sik", "ack", {"command": 400, "result": 0})  # ARM: cai nay moi la cua nut
    assert not ct._pending and "chấp nhận" in logs[-1], logs
    ct.close()
    print("  ok  geofence: vong tron quanh home + da giac, TAT thi ve dut net")


def check_waypoints(app):
    """Duong bay nhieu waypoint: tu goi MAVLink toi net ve tren ban do.

    Day la thu duy nhat cho biet drone bay AUTO SAP di dau — cham xanh tren ban
    do chi noi no dang o dau. Nen check nay do ca ba cho hong duoc: tran 50 muc,
    muc khong co toa do, va viec ai do nap nhiem vu khac giua chung.
    """
    from core.adapters.sik import WP_ITEMS_MAX, WP_MAX
    from laptop.tabs.flight import FlightTab
    from laptop.widgets.map_widget import WP_LINE, wp_points

    # `total` thieu (firmware < 4.3) thi phai BIEN MAT khoi trong tai, khong duoc
    # thanh None: ben ve gop tung manh vao mot dict, None se xoa con so that.
    assert normalize("MISSION_CURRENT", {"seq": 3, "total": 8}) == ("wp", {"seq": 3, "total": 8})
    assert normalize("MISSION_CURRENT", {"seq": 3, "total": 0}) == ("wp", {"seq": 3})

    # Muc khong mang toa do (TAKEOFF de trong, DO_CHANGE_SPEED) phai bi loai.
    items = [(0, 16, 10.8221, 106.6868, 0.0), (1, 22, 0.0, 0.0, 15.0),
             (2, 16, 10.8231, 106.6868, 20.0), (3, 178, 0.0, 0.0, 0.0),
             (4, 16, 10.8241, 106.6878, 25.0)]
    assert [s for s, *_ in wp_points(items)] == [0, 2, 4], wp_points(items)

    # --- tran WP_MAX tren chinh adapter -------------------------------------
    class FakeMav:
        def __init__(self):
            self.asked = []

        def mission_request_list_send(self, *a, **k):
            pass

        def mission_request_int_send(self, sysid, comp, i, **k):
            self.asked.append(i)

        def mission_ack_send(self, *a, **k):
            pass

    class FakeMaster:
        target_system = 1

        def __init__(self):
            self.mav = FakeMav()

    ad = SikAdapter({"name": "wp", "mode": "SIM", "conn": f"udp:127.0.0.1:{PORT}"})
    master = FakeMaster()
    assert ad._wp_rx(master, "MISSION_COUNT", {"count": 80, "mission_type": 0}) is False
    assert ad._wp_n == WP_ITEMS_MAX and ad._wp_total == 80, (ad._wp_n, ad._wp_total)
    assert master.mav.asked == list(range(WP_ITEMS_MAX)), master.mav.asked[-3:]
    for i in range(WP_ITEMS_MAX):
        ad._wp_rx(master, "MISSION_ITEM_INT",
                  {"seq": i, "mission_type": 0, "command": 16,
                   "x": 108221589 + i * 1000, "y": 1066868454, "z": 20.0})
    assert ad._wp_done() and len(ad._wp_items) == WP_ITEMS_MAX, len(ad._wp_items)

    # Nhiem vu 80 muc thi _wp_n = 50 mai mai khac 80: so sanh nham cot nay la
    # vong tai lai chay hoai, chiem het duong SiK.
    ad._wp_rx(master, "MISSION_CURRENT", {"seq": 3, "total": 80})
    assert ad._wp_done(), "so muc khong doi ma van tai lai"
    # Con doi that (ai do nap nhiem vu khac) thi phai tai lai tu dau.
    ad._wp_rx(master, "MISSION_CURRENT", {"seq": 0, "total": 4})
    assert ad._wp_n is None and ad._wp_items == {}, (ad._wp_n, ad._wp_items)

    # --- duong that: adapter -> bus -> tab -> net ve tren man hinh -----------
    lat, lon = 10.8221589, 106.6868454
    ft = FlightTab()
    ft.resize(600, 400)
    ft.map.zoom = 16
    ft.map.follow = False  # khong de vi tri cu tu check khac keo tam man hinh di
    ft.map.center = (lat, lon)
    # Hai diem cung vi do, doi xung qua tam: doan thang nam dung hang giua anh.
    # 0,001 do kinh do o z16 = 2**16/360*256*0.001 = 46,6 px.
    bus.emit("sik", "wp", {"items": [(0, 16, lat, lon - 0.001, 0.0),
                                     (1, 16, lat, lon + 0.001, 20.0)], "total": 2})
    assert ft.map.wp["total"] == 2, ft.map.wp

    img = ft.map.grab().toImage()
    cx, cy = img.width() // 2, img.height() // 2
    rows = (cy - 1, cy, cy + 1)  # but 2 px: Qt dat net o hang nao la tuy no
    assert any(img.pixel(cx + 20, y) == WP_LINE.rgb() for y in rows), \
        "duong bay khong len man hinh"
    assert all(img.pixel(cx + 80, y) != WP_LINE.rgb() for y in rows), \
        "duong bay keo dai qua diem cuoi (47 px) — nghi ve nham toa do"

    # MISSION_CURRENT ve rieng, sau: no phai gop vao chu khong xoa danh sach diem.
    bus.emit("sik", "wp", {"seq": 1})
    assert len(ft.map.wp["items"]) == 2 and "tới #1" in ft.map._wp_note(), ft.map._wp_note()

    # Cat bot ma im lang thi nguoi bay tuong da nhin thay ca duong bay.
    bus.emit("sik", "wp", {"items": [(i, 16, lat, lon + i * 1e-4, 20.0)
                                     for i in range(WP_ITEMS_MAX)], "total": 80})
    assert f"FC có 80, chỉ tải {WP_ITEMS_MAX}" in ft.map._wp_note(), ft.map._wp_note()

    # Ngat ket noi: duong bay cua drone cu phai bien mat cung home va rao.
    ft.set_mode(None)
    assert ft.map.wp == {}, ft.map.wp
    ft.close()
    print(f"  ok  duong bay waypoint: ve tren ban do, cat o {WP_MAX} waypoint "
          f"({WP_ITEMS_MAX} muc ke ca home/TAKEOFF/LAND)")


def check_wp_write(app):
    """Chieu ghi: dat waypoint bang chuot roi nap len FC.

    Ba cho hong duoc, va check nay do ca ba:
      - muc 0 khong duoc chen -> ArduPilot nuot waypoint dau tien lam home
      - FC im giua chung -> phai gui lai roi BO CUOC TO, khong im lang
      - nap xong ma khong doc lai -> "da gui" bi hieu thanh "FC da luu"
    """
    from core import authority
    from core.adapters.sik import (LAND, TAKEOFF, WAYPOINT, WP_ITEMS_MAX, WP_MAX,
                                   WP_UP_TRIES)
    from core.field import REGISTRY
    from laptop.tabs.flight import FlightTab

    lat, lon = 10.8221589, 106.6868454

    class FakeMav:
        def __init__(self):
            self.counts, self.items = [], []

        def mission_count_send(self, sysid, comp, n, **k):
            self.counts.append(n)

        def mission_item_int_send(self, sysid, comp, seq, frame, cmd, cur, cont,
                                  p1, p2, p3, p4, x, y, z, **k):
            self.items.append((seq, cmd, x / 1e7, y / 1e7, z))

        def mission_request_list_send(self, *a, **k):
            pass

        def mission_request_int_send(self, *a, **k):
            pass

        def mission_ack_send(self, *a, **k):
            pass

    class FakeMaster:
        target_system = 1

        def __init__(self):
            self.mav = FakeMav()

    ad = SikAdapter({"name": "wpw", "mode": "SIM", "conn": f"udp:127.0.0.1:{PORT}"})
    got = []
    ad.envelope.connect(lambda e: got.append(e) if e["topic"] == "wp" else None)
    master = FakeMaster()
    ad._home = (lat, lon)

    pts = [(lat + 1e-4, lon, 20.0), (lat + 2e-4, lon + 1e-4, 25.0)]
    ad._wp_upload(master, pts)
    # 2 waypoint -> 5 muc: home + TAKEOFF o dau, LAND o cuoi. Thieu home la drone
    # bay 1 diem; thieu TAKEOFF la no khong roi mat dat; thieu LAND la no treo
    # tai diem cuoi cho den het pin.
    assert master.mav.counts == [5], master.mav.counts
    for i in range(5):
        ad._wp_up_rx(master, "MISSION_REQUEST_INT", {"seq": i, "mission_type": 0})
    assert [i[0] for i in master.mav.items] == [0, 1, 2, 3, 4], master.mav.items
    assert [i[1] for i in master.mav.items] == [
        WAYPOINT, TAKEOFF, WAYPOINT, WAYPOINT, LAND], master.mav.items
    assert abs(master.mav.items[0][2] - lat) < 1e-7, "muc 0 phai la home"
    # TAKEOFF: khong toa do (ArduCopter leo thang tu cho dang dung), do cao lay
    # cua waypoint dau — leo 20 m roi moi di, chu khong leo 25 m cua diem cuoi.
    assert master.mav.items[1][2:] == (0.0, 0.0, 20.0), master.mav.items[1]
    assert abs(master.mav.items[3][4] - 25.0) < 1e-6, master.mav.items[3]
    # LAND ha tai chinh waypoint cuoi, khong phai tai home.
    assert abs(master.mav.items[4][2] - pts[-1][0]) < 1e-7, master.mav.items[4]

    # Dang nap thi KHONG duoc chen mot phien tai ve vao giua.
    ad._wp_ask(master)
    assert master.mav.counts == [5], "vua tai vua nap cung luc"

    assert ad._wp_up_rx(master, "MISSION_ACK", {"type": 0, "mission_type": 0}) is True
    assert got[-1]["data"]["write"] == {"ok": True, "result": 0, "n": 2}, got[-1]
    # Nap xong phai quen danh sach cu de doc lai tu FC — bang chung, khong niem tin.
    assert ad._wp_n is None and ad._wp_items == {}, (ad._wp_n, ad._wp_items)

    # FC im: gui lai WP_UP_TRIES lan roi bo cuoc, va phai bao ra ngoai.
    got.clear()
    master.mav.counts.clear()
    ad._wp_upload(master, pts)
    for _ in range(WP_UP_TRIES + 2):
        ad._up_at = 0  # gia vo da qua WP_UP_RETRY giay
        ad._wp_up_tick(master, time.time())
    assert len(master.mav.counts) == WP_UP_TRIES, master.mav.counts
    assert ad._up is None and got[-1]["data"]["write"]["ok"] is False, got[-1]
    assert "khong tra loi" in got[-1]["data"]["write"]["err"], got[-1]

    # Tran: dat 60 diem thi chi 50 cai len duong, khong phai 60. Cong 3 muc tu
    # chen (home + TAKEOFF + LAND) = 53, va do phai bang WP_ITEMS_MAX — khong
    # bang thi chieu doc ve tu cat cut chinh nhiem vu vua nap.
    master.mav.counts.clear()
    ad._wp_upload(master, [(lat + i * 1e-4, lon, 20.0) for i in range(60)])
    assert master.mav.counts == [WP_MAX + 3] == [WP_ITEMS_MAX], master.mav.counts

    # Cat link giua phien nap (nut "Cat telemetry" o panel Sim): goi khong duoc
    # ra khoi radio, va tra loi cua FC khong duoc coi la da toi. Bo qua cho nay
    # thi bai tap "rot link giua luc nap" hien ra thanh cong ma that ra chua gui.
    master.mav.counts.clear()
    master.mav.items.clear()
    ad.muted = True
    ad._wp_upload(master, pts)
    ad._wp_up_rx(master, "MISSION_REQUEST_INT", {"seq": 0, "mission_type": 0})
    assert not master.mav.counts and not master.mav.items, "muted ma goi van di"
    ad.muted = False
    ad._up = None

    # --- duong that: menu ban do -> dispatch -> adapter ---------------------
    sent = []

    class Fake:
        def send(self, action, args=None):
            sent.append((action, args))
            return {"ok": action}

    authority.register("sik", Fake())
    ft = FlightTab()
    logs = []
    ft.log.connect(lambda text, _sev: logs.append(text))
    try:
        ft.resize(600, 400)
        ft.set_mode("SIM")
        ft.map.center = (lat, lon)
        assert ft.map.add_draft(lat + 1e-4, lon) is True
        assert ft.map.add_draft(lat + 2e-4, lon + 1e-4) is True
        assert ft.map.draft[0][2] == ft.map.wp_alt, ft.map.draft
        assert "đang đặt 2 điểm" in ft.map._draft_note(), ft.map._draft_note()

        ft._send_wp()
        assert sent == [("wp_write", {"items": [list(p) for p in ft.map.draft]})], sent

        # FC xac nhan -> ban nhap phai bien mat, neu khong hai duong chong len nhau
        bus.emit("sik", "wp", {"write": {"ok": True, "result": 0, "n": 2}})
        assert ft.map.draft == [], ft.map.draft
        assert "FC nhận 2 waypoint" in logs[-1], logs[-1]

        # FC tu choi -> ban nhap phai CON NGUYEN de bam nap lai
        ft.map.add_draft(lat, lon)
        bus.emit("sik", "wp", {"write": {"ok": False, "result": 5, "n": 1}})
        assert len(ft.map.draft) == 1, "tu choi ma van xoa mat ban nhap"
        assert "THẤT BẠI" in logs[-1], logs[-1]

        # Dang bay AUTO: cu bam dau tien chi canh bao, khong gui gi ca
        sent.clear()
        REGISTRY.feed({"src": "sik", "topic": "heartbeat",
                       "data": {"mode": "AUTO", "armed": True}, "ts": time.time()})
        ft._send_wp()
        assert not sent, "ghi de nhiem vu dang bay ma khong hoi lai"
        assert "ĐANG BAY AUTO" in logs[-1], logs[-1]
        ft._send_wp()  # bam lai trong CONFIRM_S -> di
        assert sent and sent[0][0] == "wp_write", sent

        # Tran o tang UI: 50 la 50, cai thu 51 khong dat duoc
        ft.map.drop_draft(all_of_them=True)
        for i in range(WP_MAX):
            assert ft.map.add_draft(lat + i * 1e-5, lon) is True, i
        assert ft.map.add_draft(lat, lon) is False, "dat qua tran WP_MAX"
    finally:
        authority.unregister("sik")
        REGISTRY.fields.clear()
        ft.close()
    print(f"  ok  nap duong bay len FC: home + TAKEOFF dau, LAND cuoi, tran {WP_MAX}, "
          f"bo cuoc sau {WP_UP_TRIES} lan va noi ra")


def check_nudge_keys(app):
    """Nhich vi tri bang ban phim: bon chot chan, ramp toc do, va tha la DUNG."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFocusEvent, QKeyEvent

    from core import authority
    from core.field import REGISTRY
    from laptop.tabs.flight import NUDGE_RAMP, NUDGE_V0, NUDGE_VMAX, FlightTab

    sent = []

    class Fake:
        def send(self, action, args=None):
            sent.append((action, args))
            return {"ok": action}

    def press(ft, key):
        ft.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))

    def release(ft, key):
        ft.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))

    def state(**kw):
        REGISTRY.feed({"src": "sik", "topic": "heartbeat", "data": kw, "ts": time.time()})

    authority.register("sik", Fake())
    ft = FlightTab()
    logs = []
    ft.log.connect(lambda text, _sev: logs.append(text))
    try:
        ft.set_mode("REAL")

        # --- bon chot: moi cai deu phai chan, va phai NOI RA ly do
        for label, st in [
            ("chua armed", {"mode": "GUIDED", "armed": False, "landed": False}),
            ("con duoi dat", {"mode": "GUIDED", "armed": True, "landed": True}),
            ("dang o AUTO", {"mode": "AUTO", "armed": True, "landed": False}),
        ]:
            state(**st)
            sent.clear()
            press(ft, Qt.Key_Up)
            assert not sent, f"{label}: van gui lenh nhich"
            assert "KHÔNG được" in logs[-1], (label, logs[-1])
        REGISTRY.fields.clear()

        # REPLAY khong gui gi ke ca khi trang thai dep
        ft.set_mode("REPLAY")
        state(mode="GUIDED", armed=True, landed=False)
        sent.clear()
        press(ft, Qt.Key_Up)
        assert not sent, "REPLAY ma van gui lenh nhich"
        ft.set_mode("REAL")

        # --- duoc phep: giu phim -> nhich, toc do tang theo thoi gian giu
        state(mode="GUIDED", armed=True, landed=False)
        sent.clear()
        press(ft, Qt.Key_Up)
        ft._nudge_tick()
        act, args = sent[-1]
        assert act == "nudge", sent
        assert abs(args["vn"] - NUDGE_V0) < 0.3, f"vua cham phim phai di cham: {args}"
        assert args["ve"] == 0 and args["vd"] == 0, args

        ft._nudge_since = time.time() - 60  # giu that lau
        ft._nudge_tick()
        assert abs(sent[-1][1]["vn"] - NUDGE_VMAX) < 1e-6, f"phai cham tran: {sent[-1]}"

        # duong cheo khong duoc nhanh hon: hai phim van la NUDGE_VMAX, khong phai 1,41 lan
        press(ft, Qt.Key_Right)
        ft._nudge_tick()
        a = sent[-1][1]
        mag = (a["vn"] ** 2 + a["ve"] ** 2) ** 0.5
        assert abs(mag - NUDGE_VMAX) < 1e-6, f"cheo bi nhanh hon: {mag:.2f} m/s"

        # --- tha het phim -> van toc 0 (treo tai cho)
        sent.clear()
        release(ft, Qt.Key_Up)
        assert not sent, "moi tha mot phim ma da dung"
        release(ft, Qt.Key_Right)
        assert sent[-1] == ("nudge", {"vn": 0.0, "ve": 0.0, "vd": 0.0}), sent
        assert not ft._nudge_timer.isActive(), "tha phim roi ma timer van chay"

        # --- mat focus giua luc dang giu: KHONG co keyRelease, phai tu dung
        press(ft, Qt.Key_Left)
        sent.clear()
        ft.focusOutEvent(QFocusEvent(QEvent.FocusOut, Qt.OtherFocusReason))
        assert sent[-1] == ("nudge", {"vn": 0.0, "ve": 0.0, "vd": 0.0}), \
            "alt-tab giua luc giu phim ma drone van giu van toc"

        # --- ba phim con lai
        sent.clear()
        press(ft, Qt.Key_Space)
        assert sent[-1][0] == "nudge" and sent[-1][1]["vn"] == 0.0, sent
        press(ft, Qt.Key_Return)
        assert sent[-1] == ("mode", {"name": "AUTO"}), sent
        press(ft, Qt.Key_L)
        assert sent[-1][0] == "land", sent
    finally:
        authority.unregister("sik")
        REGISTRY.fields.clear()
        ft.close()
    print(f"  ok  nhich bang ban phim: 4 chot chan, ramp {NUDGE_V0:g}->{NUDGE_VMAX:g} m/s "
          f"(+{NUDGE_RAMP:g}/s), tha phim va mat focus deu dung")


def check_stream_rearm(app):
    """Im lang qua STREAM_REARM thi phai xin lai stream — va chi xin MOT lan.

    Bay do duoc tren radio SiK that (13/08/2026): FC tut xuong 21 B/s chi con
    HEARTBEAT, app xin mot lan la ve 1986 B/s. Truoc do app xin dung mot lan luc
    ket noi nen no nam im vinh vien — HUD dung hinh ma link van bao "co song".

    Cai thu hai quan trong khong kem cai thu nhat: sau khi xin phai dat lai dong
    ho. Khong dat thi dieu kien con dung o MOI vong lap, tuc ban 7 goi moi vong —
    hang nghin goi mot giay vao dung cai duong truyen dang co van de.
    """
    from core.adapters.sik import STREAM_REARM, STREAMS, SikAdapter

    class FakeMav:
        def __init__(self):
            self.asks = []

        def request_data_stream_send(self, sysid, comp, sid, hz, on):
            self.asks.append((sid, hz, on))

    class FakeMaster:
        target_system = 1

        def __init__(self):
            self.mav = FakeMav()

    ad = SikAdapter({"name": "rearm", "mode": "SIM", "conn": f"udp:127.0.0.1:{PORT}"})
    master = FakeMaster()
    now = time.time()

    # stream con chay -> khong xin gi ca
    ad._stream_rx = now
    ad._stream_tick(master, now)
    assert master.mav.asks == [], "stream dang song ma van xin lai"

    # im qua nguong -> xin lai DU ca bo, khong thieu luong nao
    ad._stream_rx = now - STREAM_REARM - 0.1
    ad._stream_tick(master, now)
    assert master.mav.asks == [(sid, hz, 1) for sid, hz in STREAMS], master.mav.asks

    # goi lai ngay -> im, vi dong ho da dat lai
    master.mav.asks.clear()
    ad._stream_tick(master, now)
    assert master.mav.asks == [], "xin lai moi vong lap — ban ngap duong truyen"

    # dut link mo phong: khong goi nao duoc ra khoi radio
    ad.muted = True
    ad._stream_rx = now - STREAM_REARM - 0.1
    ad._stream_tick(master, now)
    assert master.mav.asks == [], "muted ma goi van di"
    ad.muted = False

    # REPLAY chi doc file, khong duoc gui gi ve phia FC
    ad.mode = "REPLAY"
    ad._stream_rx = now - STREAM_REARM - 0.1
    ad._stream_tick(master, now)
    assert master.mav.asks == [], "REPLAY ma van gui lenh"

    print(f"  ok  FC ngung stream: xin lai sau {STREAM_REARM:g}s im lang, "
          f"{len(STREAMS)} luong, khong ban lap")


def check_replay(app):
    """REPLAY phai dung han o EOF.

    Bay: file .tlog mo ra thanh mavmmaplog, ma recv_match(blocking=True) cua no
    treo vinh vien o EOF thay vi tra None. Neu pymavlink doi hanh vi, check nay
    do duoc.
    """
    import struct
    import tempfile

    from PySide6.QtCore import QTimer
    from pymavlink.dialects.v20 import ardupilotmega as mavlink

    path = Path(tempfile.gettempdir()) / "selfcheck.tlog"
    mav = mavlink.MAVLink(None, srcSystem=1)
    t0 = time.time()
    with open(path, "wb") as f:
        for i in range(5):
            m = mav.attitude_encode(i * 100, 0.1, 0.2, 0.3, 0.0, 0.0, 0.0)
            m.pack(mav)
            f.write(struct.pack(">Q", int((t0 + i * 0.1) * 1e6)) + m.get_msgbuf())

    seen = []
    adapter = SikAdapter({"name": "selfcheck", "mode": "REPLAY", "path": str(path)})
    adapter.envelope.connect(lambda e: seen.append(e))
    started = time.time()
    adapter.finished.connect(app.quit)
    adapter.start()
    guard = deadline(app, 5000)  # chan treo
    app.exec()
    guard.stop()
    took = time.time() - started
    adapter.stop()

    assert took < 4, f"REPLAY khong ket thuc o EOF ({took:.1f}s)"
    assert sum(1 for e in seen if e["topic"] == "attitude") == 5, seen
    assert any(e["topic"] == "link" and e["data"].get("eof") for e in seen), "khong bao EOF"
    assert adapter.tlog is None, "REPLAY khong duoc ghi de len log"
    print(f"  ok  REPLAY dung o EOF sau {took:.1f}s")


def check_tlog_roundtrip(app):
    """Ghi .tlog tren link UDP roi phat lai chinh file do.

    Bay: mavudp.recv_msg ghi de ham goc va bo mat doan ghi log, nen
    master.setup_logfile() tao file 0 byte ma khong bao loi — bay xong moi biet
    la khong co log.
    """
    import shutil
    import tempfile

    from PySide6.QtCore import QTimer
    from pymavlink import mavutil

    port, logdir = 14563, Path(tempfile.mkdtemp())
    rec = SikAdapter({"name": "rec", "mode": "SIM", "conn": f"udp:127.0.0.1:{port}"}, logdir=logdir)
    rec.start()

    stop = threading.Event()

    def sender():
        time.sleep(0.4)
        out = mavutil.mavlink_connection(f"udpout:127.0.0.1:{port}", source_system=1)
        while not stop.is_set():
            out.mav.attitude_send(0, 0.1, 0.2, 0.3, 0.0, 0.0, 0.0)
            time.sleep(0.05)

    threading.Thread(target=sender, daemon=True).start()
    guard = deadline(app, 3000)
    app.exec()
    guard.stop()
    stop.set()
    rec.stop()

    size = rec.tlog.stat().st_size
    assert size > 0, "tlog 0 byte — link UDP khong ghi duoc log"

    seen = []
    play = SikAdapter({"name": "play", "mode": "REPLAY", "path": str(rec.tlog)})
    play.envelope.connect(lambda e: seen.append(e["topic"]))
    play.finished.connect(app.quit)
    play.start()
    guard = deadline(app, 8000)
    app.exec()
    guard.stop()
    play.stop()
    shutil.rmtree(logdir, ignore_errors=True)

    assert seen.count("attitude") > 10, f"phat lai chi ra {seen.count('attitude')} attitude"
    print(f"  ok  ghi .tlog qua UDP ({size} byte) roi phat lai duoc")


def check_dead_socket(app):
    """Dau kia bien mat -> adapter phai bao `failed` va dung, khong quay tit.

    Bay: mavtcp.reconnect() la no-op khi autoreconnect=False, nen recv() goi mai
    vao socket chet — 100% CPU va hang trieu dong "EOF on TCP socket".
    """
    import socket

    from PySide6.QtCore import QTimer
    from pymavlink.dialects.v20 import ardupilotmega as mavlink

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 14560))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        mav = mavlink.MAVLink(None, srcSystem=1)
        m = mav.heartbeat_encode(2, 3, 0, 0, 0)
        m.pack(mav)
        conn.sendall(m.get_msgbuf())
        time.sleep(0.5)
        conn.close()  # -> phia adapter thay EOF
        srv.close()

    threading.Thread(target=serve, daemon=True).start()

    fails = []
    adapter = SikAdapter({"name": "dead", "mode": "SIM", "conn": "tcp:127.0.0.1:14560"})
    adapter.failed.connect(fails.append)
    adapter.finished.connect(app.quit)
    t0 = time.time()
    adapter.start()
    guard = deadline(app, 15000)  # chan treo
    app.exec()
    guard.stop()
    took = time.time() - t0
    adapter.stop()

    assert fails, "socket chet ma adapter khong bao failed — nhieu kha nang dang quay tit"
    assert took < 12, f"mat {took:.0f}s moi bo cuoc"
    print(f"  ok  socket chet -> bo cuoc sau {took:.1f}s, bao: {fails[0][:40]}")


def check_banner_health(app):
    """Banner phai theo suc khoe link, khong phai theo mode da chon.

    Bay: `udp:` chi bind cong nen mo bao gio cung thanh cong — khong co SITL nao
    chay ma banner van bao xanh "SIM" thi nguoi dung tuong da noi duoc.
    """
    from PySide6.QtCore import QTimer
    from pymavlink import mavutil

    from laptop.app import MainWindow

    port = 14561
    win = MainWindow([{"name": "gia", "mode": "SIM", "conn": f"udp:127.0.0.1:{port}"}])
    assert win.panel.select("gia"), "khong thay profile gia"
    win.panel.btn_connect.click()

    stop = threading.Event()

    def sender():
        out = mavutil.mavlink_connection(f"udpout:127.0.0.1:{port}", source_system=1)
        while not stop.is_set():
            out.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                   mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA, 0, 0, 0)
            time.sleep(0.1)

    states = []
    QTimer.singleShot(1500, lambda: (states.append(win.banner.text()),
                                     threading.Thread(target=sender, daemon=True).start()))
    QTimer.singleShot(4000, lambda: (states.append(win.banner.text()), stop.set()))
    QTimer.singleShot(8000, lambda: (states.append(win.banner.text()), app.quit()))
    app.exec()
    win.disconnect()
    win.close()

    assert "đang chờ dữ liệu" in states[0], states[0]
    assert "mô phỏng SITL" in states[1], states[1]
    assert "MẤT KẾT NỐI" in states[2], states[2]
    print("  ok  banner: cho du lieu -> dang chay -> mat ket noi")


def check_adapter_live(app):
    """Chay SikAdapter that voi nguon MAVLink gia tren UDP."""
    from PySide6.QtCore import QTimer
    from pymavlink import mavutil

    seen = {}
    last_landed = [None]
    adapter = SikAdapter({"name": "selfcheck", "mode": "SIM", "conn": f"udp:127.0.0.1:{PORT}"})
    adapter.envelope.connect(lambda e: seen.setdefault(e["topic"], e))
    adapter.envelope.connect(
        lambda e: last_landed.__setitem__(0, e["data"]["landed"])
        if e["topic"] == "heartbeat" and "landed" in e["data"] else None
    )
    adapter.start()

    stop = threading.Event()

    def sender():
        time.sleep(0.4)  # cho adapter bind cong
        out = mavutil.mavlink_connection(f"udpout:127.0.0.1:{PORT}", source_system=1)
        while not stop.is_set():
            out.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                   mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA, 0, 0, 0)
            out.mav.global_position_int_send(0, 107620000, 1066600000, 12000, 5000,
                                             100, 200, -50, 9000)
            # EXTENDED_SYS_STATE cung do ve topic `heartbeat`. Goi nay tung lam
            # chet ca luong doc: doan lam giau topic do goi mode_string_v10(msg),
            # ma no doi `.autopilot` — chi HEARTBEAT moi co.
            out.mav.extended_sys_state_send(mavutil.mavlink.MAV_VTOL_STATE_UNDEFINED,
                                            mavutil.mavlink.MAV_LANDED_STATE_ON_GROUND)
            time.sleep(0.1)

    t = threading.Thread(target=sender, daemon=True)
    t.start()
    QTimer.singleShot(2500, app.quit)
    app.exec()
    stop.set()
    adapter.stop()

    assert "position" in seen, f"khong nhan duoc position, chi co {list(seen)}"
    assert "heartbeat" in seen and "status" in seen, list(seen)
    assert seen["heartbeat"]["data"].get("mode"), "heartbeat phai kem mode"
    assert last_landed[0] is True, f"landed_state khong ve toi noi: {last_landed}"

    assert "link" in seen, "khong co so byte/s"
    assert seen["link"]["data"]["bps"] > 0, seen["link"]
    assert seen["position"]["src"] == "sik"
    print(f"  ok  SikAdapter live — {seen['link']['data']['bps']} B/s, topic: {sorted(seen)}")


def check_video(app):
    """Video MJPEG: suy URL, doc multipart that qua socket that, va — cho quan
    trong nhat — mat tin hieu thi phai XOA khung cu.

    Dong bang khung cuoi la kieu hong nguy hiem nhat cua man hinh nay: phi cong
    nhin mot canh quay cach day 10 giay ma tuong dang thay drone luc nay.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from PySide6.QtCore import QBuffer
    from PySide6.QtGui import QColor, QPixmap

    from laptop.widgets.video import VideoSource, VideoView, url_for

    # IP lay tu `remote` da co, khong them key config va khong di do IP.
    assert url_for("ws://192.168.1.50:8765") == "http://192.168.1.50:8080/stream"
    assert url_for("ws://127.0.0.1:8765") == "http://127.0.0.1:8080/stream"
    assert url_for("") is None

    # JPEG that chu khong phai byte rac: bat loi giai ma, khong chi bat loi truyen.
    pm = QPixmap(32, 24)
    pm.fill(QColor("#c0392b"))
    buf = QBuffer()
    buf.open(QBuffer.WriteOnly)
    pm.save(buf, "JPEG")
    jpeg = bytes(buf.data())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            for _ in range(2):
                self.wfile.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n"
                    % len(jpeg)
                )
                self.wfile.write(jpeg + b"\r\n")
                time.sleep(0.05)
            # Roi im lang, KHONG dong ket noi: dung y hinh WiFi rot am tham, kieu
            # ma `read()` treo mai chu khong nem loi.
            time.sleep(30)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", VIDEO_PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def wait(sig, pred, ms):
        t = deadline(app, ms)

        def on():
            if pred():
                app.quit()

        sig.connect(on)
        app.exec()
        sig.disconnect(on)
        t.stop()

    src = VideoSource()
    view = VideoView(src)
    view.resize(160, 120)
    src.start(f"http://127.0.0.1:{VIDEO_PORT}/stream")

    wait(src.updated, lambda: src.pixmap is not None, 6000)
    assert src.alive and src.pixmap is not None, f"khong nhan duoc khung: {src.note}"
    assert src.pixmap.width() == 32, f"giai ma sai kich thuoc: {src.pixmap.width()}"

    # Ve len that, khong chi tin vao co trang thai.
    c = view.grab().toImage().pixelColor(5, 5)
    assert c.red() > 150 and c.green() < 90, f"khung khong len man hinh: {c.getRgb()}"

    # Het khung moi -> phai lat sang o xam trong vong STALE_S.
    wait(src.updated, lambda: not src.alive, 6000)
    assert not src.alive, "van bao con song sau khi het khung"
    assert src.pixmap is None, "dong bang khung cuoi — phai xoa de hien o xam"
    c = view.grab().toImage().pixelColor(5, 5)
    # Doi chieu voi bang mau chu khong go cung ma hex: doi theme la doi mau o nen,
    # nhung y nghia cua phep thu — "da xoa khung cu, dang ve o nen" — khong doi.
    from PySide6.QtGui import QColor
    from laptop import theme
    bg = QColor(theme.BG)
    assert all(abs(a - b) < 12 for a, b in
               zip(c.getRgb()[:3], bg.getRgb()[:3])), \
        f"mat video ma khong phai o nen: {c.getRgb()} != {bg.getRgb()[:3]}"

    src.stop()
    srv.shutdown()
    print("  ok  video MJPEG — giai ma khung that, mat tin hieu thi xoa khung cu")


def check_i18n(app):
    """Doi ngon ngu: bang chu day du, va widget PHAI viet lai chu ngay tai cho.

    Cho vo y nhat khong phai la thieu ban dich (t() tra ve chinh cai key, nhin
    la thay ngay) ma la LECH CHO TRONG giua hai ban: "{n} field" ma ban tieng
    Anh viet "{count} field(s)" thi t() nem KeyError — chi o mot ngon ngu, va
    chi khi dong chu do that su duoc ve ra. Doi chieu tung cap o day thi khong
    the lot.
    """
    import string

    from PySide6.QtCore import QSettings

    from core import i18n
    from laptop.tabs.control import ControlTab
    from laptop.tabs.settings import SettingsTab

    def holes(fmt):
        return {name for _, name, _, _ in string.Formatter().parse(fmt) if name}

    for key, row in i18n.STR.items():
        assert len(row) == 2 and all(row), f"{key}: thieu mot ban dich"
        assert holes(row[0]) == holes(row[1]), (
            f"{key}: cho trong lech nhau {holes(row[0])} vs {holes(row[1])}")

    was = i18n.lang()
    try:
        i18n.set_lang("vi")
        ct = ControlTab()
        st = SettingsTab()
        vi = ct.normal_box.title()
        assert vi == "Lệnh thường", vi

        i18n.set_lang("en")
        assert ct.normal_box.title() == "Normal commands", ct.normal_box.title()
        # Nut do va ten lenh MAVLink KHONG duoc dich theo: doi chieu voi tai lieu
        # ArduPilot hay voi mot GCS khac deu phai dung mot chu.
        assert ct.btn_arm.text() == "ARM" and ct.btn_kill.text() == "DISARM"
        assert st.buttons["en"].isChecked() and not st.buttons["vi"].isChecked()

        # Bam nut o tab Settings la duong doi ngon ngu that su cua nguoi dung.
        st.buttons["vi"].setChecked(True)
        assert i18n.lang() == "vi", i18n.lang()
        assert ct.normal_box.title() == vi, ct.normal_box.title()

        # Ngon ngu phai song sot qua lan mo app sau.
        assert QSettings("GCS", "native").value("lang") == "vi"
    finally:
        i18n.set_lang(was)
    print(f"  ok  doi ngon ngu: {len(i18n.STR)} muc x {len(i18n.LANGS)} thu tieng, "
          "widget viet lai chu ngay, lua chon duoc nho")


def check_param_doc(app):
    """Tham so la gi: moi cai trong danh sach doc PID phai co mot dong giai thich,
    va dong do phai bam vao dung hang PARAM.* duoi dang tooltip.

    Ho ATC_*/PSC_* duoc GHEP tu hai bang manh chu khong viet tay tung cai, nen cho
    hong khong phai la go nham chu ma la mot ten khong lot vao khuon nao va im
    lang khong co mo ta. Doi chieu ca 63 cai o day thi khong the im lang duoc.
    """
    from core import i18n, param_doc
    from laptop.tabs.status import PID_PARAMS, StatusTab

    thieu = [p for p in PID_PARAMS if not param_doc.doc(p)]
    assert not thieu, f"tham so khong co giai thich: {thieu}"
    # Field thuong KHONG duoc bia ra mo ta — thieu thi im lang, dung doan bua.
    assert param_doc.doc("ATTITUDE.roll") == "" and param_doc.doc("FOO_BAR") == ""

    was = i18n.lang()
    try:
        i18n.set_lang("vi")
        st = StatusTab()
        bus.emit("sik", "status", {"PARAM.ATC_RAT_RLL_P": 0.135, "ATTITUDE.roll": -0.01})
        st._flush()
        row = {st.model.item(r, 0).text(): r for r in range(st.model.rowCount())}
        tip = st.model.item(row["PARAM.ATC_RAT_RLL_P"], 0).toolTip()
        assert "trục lăn" in tip and "hệ số P" in tip, tip
        # Ca hai o cua hang deu phai co: re chuot cho nao trong hang cung ra.
        assert all(st.model.item(row["PARAM.ATC_RAT_RLL_P"], c).toolTip() == tip
                   for c in range(st.model.columnCount()))
        assert st.model.item(row["ATTITUDE.roll"], 0).toolTip() == "", "bia mo ta cho field thuong"

        # Doi ngon ngu: hang DA NAM trong bang phai doi tooltip theo, khong chi
        # hang moi them sau do.
        i18n.set_lang("en")
        tip_en = st.model.item(row["PARAM.ATC_RAT_RLL_P"], 0).toolTip()
        assert "roll axis" in tip_en and "P gain" in tip_en, tip_en
    finally:
        i18n.set_lang(was)
    print(f"  ok  giai thich tham so: {len(PID_PARAMS)}/{len(PID_PARAMS)} co mo ta, "
          "vao tooltip cua hang PARAM.*, doi theo ngon ngu")


def check_telemetry_warn(app):
    """Thanh telemetry: da ARM chua, va pin/GPS phai TU KEO MAT khi xau.

    Truoc day moi o deu mot mau trang nhu nhau, nen 9,8 V trong y het 16,8 V va
    fix_type=1 (chua co vi tri) trong y het 3D fix. Con `armed` thi doc de chan
    logic ma khong hien o dau ca — boolean quan trong nhat tren man hinh bay.

    Nguong pin bam vao PHAN TRAM chu khong dien ap: ba chuyen bay that gan day do
    duoc 16,8 V / 15,2 V / 11,7 V — 4S va 3S xen ke, mot nguong dien ap cung se
    sai o it nhat mot chuyen. Bai nay chot dung dieu do bang cach cho hai dien ap
    khac han nhau ma cung mot phan tram, va doi hai o RA CUNG MOT MAU.
    """
    from core import i18n
    from core.field import REGISTRY
    from laptop.tabs.flight import FlightTab
    from laptop.widgets import telemetry_bar as tb

    OK, WARN, CRIT = (tb.LEVEL_COLOR[k] for k in (None, "warn", "crit"))

    # --- ham nguong, kiem thang ---
    proc = (Path(__file__).resolve().parent.parent
            / "docs" / "operating_procedure.md").read_text(encoding="utf-8")

    assert tb.batt_level(None) is None, "FC khong bao phan tram thi KHONG duoc doan"
    assert [tb.batt_level(p) for p in (100, 31, 30, 21, 20, 0)] == \
        [None, None, "warn", "warn", "crit", "crit"], [tb.batt_level(p) for p in (100, 30, 20)]
    # Nguong phai khop bang o muc D va F cua quy trinh bay, khong duoc troi tu do.
    assert f"| Pin | < {tb.BATT_WARN_PCT}% |" in proc, "nguong vang lech voi quy trinh bay"
    assert f"| Pin | < {tb.BATT_CRIT_PCT}% |" in proc, "nguong do lech voi quy trinh bay"
    assert tb.gps_level(None)[0] is None
    assert [tb.gps_level(f)[0] for f in (0, 1, 2, 3, 6)] == ["crit", "crit", "warn", None, None]
    # Ba dieu kien cua muc D.4, khong cai nao thay duoc cai nao: 3D fix voi 5 ve
    # tinh, hay 12 ve tinh voi HDOP 2,5, deu phai vang.
    assert tb.gps_level(3, 12, 0.8)[0] is None
    assert tb.gps_level(3, 5, 0.8)[0] == "warn", "3D fix nhung it ve tinh ma khong keu"
    assert tb.gps_level(3, 12, 2.5)[0] == "warn", "HDOP cao ma khong keu"
    assert f"số vệ tinh ≥ {tb.GPS_MIN_SATS}" in proc, "nguong ve tinh lech voi quy trinh bay"
    assert f"HDOP < {tb.GPS_MAX_HDOP:.0f}" in proc, "nguong HDOP lech voi quy trinh bay"

    was = i18n.lang()
    try:
        i18n.set_lang("vi")
        ft = FlightTab()
        ft.resize(900, 400)
        val = ft.telemetry._val

        def color(key):
            return val[key].styleSheet().split("color:")[-1].rstrip(";")

        def feed(topic, data):
            REGISTRY.feed({"src": "sik", "topic": topic, "data": data, "ts": time.time()})

        # --- ARM: phai hien ra, va phai doi mau ---
        feed("heartbeat", {"armed": False, "mode": "STABILIZE"})
        ft.refresh()
        assert val["ARM"].text() == "CHƯA ARM", val["ARM"].text()
        assert color("ARM") == OK, color("ARM")

        feed("heartbeat", {"armed": True, "mode": "GUIDED"})
        ft.refresh()
        assert val["ARM"].text() == "ĐÃ ARM", val["ARM"].text()
        assert color("ARM") == CRIT, "da ARM ma o van mau binh thuong"

        # --- PIN: mau theo phan tram, KHONG theo dien ap ---
        # 16,8 V (4S day) va 11,1 V (3S can) cung bao 12% -> ca hai deu phai do.
        for volt in (16.8, 11.1):
            feed("battery", {"voltage": volt, "remaining": 12})
            ft.refresh()
            assert color("PIN") == CRIT, f"{volt} V @12% ma khong do: {color('PIN')}"
        feed("battery", {"voltage": 11.1, "remaining": 25})
        ft.refresh()
        assert color("PIN") == WARN, color("PIN")
        # 11,1 V voi mot pack 3S la gan can, voi pack 6S la chet han — nhung FC bao
        # 80% thi day la pack 3S dang khoe. Dung dien ap lam nguong la sai o day.
        feed("battery", {"voltage": 11.1, "remaining": 80})
        ft.refresh()
        assert color("PIN") == OK, color("PIN")

        # FC khong bao phan tram -> KHONG bia ra nguong, va phai noi ro o tooltip.
        # Registry co y BO QUA gia tri None (field.py:65) nen khong the "gui None"
        # de xoa cai da biet — phai bo han field di, dung nhu chua tung nhan.
        REGISTRY.fields.pop("battery.remaining", None)
        feed("battery", {"voltage": 11.1})
        ft.refresh()
        assert color("PIN") == OK, color("PIN")
        assert "KHÔNG báo phần trăm" in val["PIN"].toolTip(), val["PIN"].toolTip()

        # --- SAT: mau theo fix_type, KHONG theo so ve tinh ---
        # Do that tren ban: fix_type=1, sats=0. Truoc day hien so 0 trang tinh.
        feed("gps", {"fix_type": 1, "sats": 0})
        ft.refresh()
        assert val["SAT"].text() == "0" and color("SAT") == CRIT, (val["SAT"].text(), color("SAT"))
        assert "CHƯA bắt được fix" in val["SAT"].toolTip(), val["SAT"].toolTip()
        feed("gps", {"fix_type": 2, "sats": 12})
        ft.refresh()
        assert color("SAT") == WARN, "2D fix (khong co do cao GPS) ma khong canh bao"
        # 12 ve tinh voi 3D fix moi la binh thuong; so ve tinh mot minh khong quyet dinh
        feed("gps", {"fix_type": 3, "sats": 12})
        ft.refresh()
        assert color("SAT") == OK, color("SAT")

        # Tooltip phai doi theo ngon ngu nhu moi chu khac
        i18n.set_lang("en")
        ft.refresh()
        assert val["ARM"].text() == "ARMED", val["ARM"].text()
        assert "3D fix" in val["SAT"].toolTip(), val["SAT"].toolTip()
    finally:
        i18n.set_lang(was)
    print(f"  ok  thanh telemetry: o ARM moi, pin doi mau theo % (<={tb.BATT_WARN_PCT} vang, "
          f"<={tb.BATT_CRIT_PCT} do), GPS theo fix_type")


def check_close_guard(app):
    """Dong cua so giua luc drone dang ARM: lan dau phai BI CHAN.

    Va chan bang cach nao moi la cai dang kiem: KHONG duoc mo hop thoai modal.
    Trong luc modal mo, activeModalWidget() khac None nen cua so chinh khong nhan
    input — ba nut do van bao isEnabled() == True nhung bam khong an. Mot cau hoi
    "ban co chac khong" dat dung luc drone tren troi ma lam chet nut do thi te hon
    chinh cai no dinh ngan.
    """
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QApplication

    from core.field import REGISTRY
    from laptop.app import CLOSE_CONFIRM_S, MainWindow

    win = MainWindow([{"name": "SITL", "mode": "SIM", "conn": "udp:127.0.0.1:14551"}])
    try:
        # Mo o tab Bay, khong phai bang 350 hang field.
        assert win.ui.tabWidget.currentWidget() is win.ui.Flight, "mo sai tab"

        def bam_dong():
            e = QCloseEvent()
            win.closeEvent(e)
            assert QApplication.activeModalWidget() is None, \
                "mo hop thoai modal -> nut do chet trong luc drone dang bay"
            return e.isAccepted()

        # Chua ARM (hoac khong biet) -> dong thang, khong hoi han gi
        REGISTRY.fields.pop("heartbeat.armed", None)
        assert bam_dong() is True, "chua ARM ma van chan"

        REGISTRY.feed({"src": "sik", "topic": "heartbeat", "data": {"armed": True},
                       "ts": time.time()})
        win._close_asked = 0.0
        assert bam_dong() is False, "drone dang ARM ma dong mot phat la xong"
        assert "ĐANG ARM" in win.banner.text(), win.banner.text()

        # Bam lan hai trong cua so xac nhan -> di
        assert bam_dong() is True, "bam lan hai roi ma van chan"

        # Het cua so cho thi quay lai chan tu dau, khong "da hoi mot lan roi thoi"
        win._close_asked = time.time() - CLOSE_CONFIRM_S - 0.1
        assert bam_dong() is False, "het cua so xac nhan ma van cho dong mot phat"
    finally:
        REGISTRY.fields.pop("heartbeat.armed", None)
        win._close_asked = 0.0
        win.close()
    print(f"  ok  dang ARM ma dong cua so: chan lan dau, bam lai trong "
          f"{CLOSE_CONFIRM_S:.0f}s moi di, khong hop thoai modal")


def check_home_note(app):
    """Con bao nhieu met ve nha — hien tren dai chu duoi ban do."""
    from core import i18n
    from core.field import REGISTRY
    from laptop.tabs.flight import FlightTab, _mmss

    assert [_mmss(s) for s in (0, 9, 60, 61, 611)] == ["0:00", "0:09", "1:00", "1:01", "10:11"]

    was = i18n.lang()
    try:
        i18n.set_lang("vi")
        ft = FlightTab()
        ft.resize(600, 400)
        assert ft.map._home_note() == "", "chua co home ma da bao khoang cach"

        # 0,001 do vi do = 111,3 m. Dung con so nay lam thuoc do.
        home = (10.8221589, 106.6868454)
        bus.emit("sik", "home", {"lat": home[0], "lon": home[1], "alt_msl": 10.1})
        assert ft.map._home_note() == "", "co home nhung chua co vi tri drone"
        # Vi tri drone di qua REGISTRY roi moi vao map (flight.py:133), khong
        # phai qua bus truc tiep nhu home.
        REGISTRY.feed({"src": "sik", "topic": "position",
                       "data": {"lat": home[0] + 0.001, "lon": home[1], "alt_rel": 5.0},
                       "ts": time.time()})
        ft.refresh()
        note = ft.map._home_note()
        assert note == "về nhà 111 m", note

        i18n.set_lang("en")
        assert ft.map._home_note() == "111 m to home", ft.map._home_note()
    finally:
        i18n.set_lang(was)
    print("  ok  khoang cach ve nha tren dai chu, va dong ho gio bay tu luc ARM")


def check_drone_marker(app):
    """Tam giac nhon tren ban do: MUI phai chia dung huong drone dang quay.

    Do bang cach chieu moi pixel cua hinh len truc huong bay roi so hai dau: phia
    mui phai nho ra xa hon han phia duoi. Kiem "co ve tam giac khong" thi khong
    bat duoc loi dang so nhat — ve tam giac nhung xoay nguoc, hoac xoay theo chieu
    kim dong ho nguoc lai. Luc do nguoi bay doc mui ra huong 180 do sai.

    Lay pixel bang cach DIFF voi khung khong co drone, khong loc theo mau: mui
    nhon bi vien den phu gan kin nen loc mau se cat mat dung cai dang do.
    """
    from laptop.widgets.map_widget import MapWidget

    m = MapWidget()
    m.resize(300, 300)
    m.zoom = 16
    m.follow = False
    m.center = (10.8, 106.68)
    cx = cy = 150

    m.pos = None
    nen = m.grab().toImage()
    m.set_position(*m.center)

    def than(hdg):
        m.heading = hdg
        img = m.grab().toImage()
        return [(x - cx, y - cy)
                for x in range(cx - 30, cx + 31) for y in range(cy - 30, cy + 31)
                if img.pixel(x, y) != nen.pixel(x, y)]

    # Chua biet huong -> HINH TRON, khong duoc ve mui. Mot cai mui nhon la loi
    # khang dinh "no dang quay ve huong nay"; chua co heading ma van ve mui la
    # noi doi, va la kieu noi doi khong ai kiem duoc bang mat.
    # Tron = nho ra deu nhau ve moi phia. Do BE RONG theo tam huong roi so cai
    # xa nhat voi cai gan nhat; do ban kinh cua tung pixel thi vo nghia vi hinh
    # dac, tam luon co pixel ban kinh 0.
    tron = than(None)
    xa = []
    for g in range(0, 360, 45):
        ux, uy = math.sin(math.radians(g)), -math.cos(math.radians(g))
        xa.append(max(qx * ux + qy * uy for qx, qy in tron))
    assert max(xa) - min(xa) < 3, f"chua biet huong ma khong phai hinh tron: {xa}"

    for hdg in (0, 45, 90, 135, 180, 225, 270, 315):
        # Truc huong bay tren man hinh: bac = len = y am.
        ux, uy = math.sin(math.radians(hdg)), -math.cos(math.radians(hdg))
        d = [qx * ux + qy * uy for qx, qy in than(hdg)]
        truoc, sau = max(d), -min(d)
        assert truoc > sau + 3, f"huong {hdg}: mui {truoc:.1f} px, duoi {sau:.1f} px"
        # Va phai nhon that, khong phai mot cuc tron xoay: dai hon rong.
        ngang = max(abs(qx * -uy + qy * ux) for qx, qy in than(hdg))
        assert truoc > ngang * 1.3, f"huong {hdg}: dai {truoc:.1f} khong nhon hon rong {ngang:.1f}"
    print("  ok  drone tren ban do: tam giac nhon, mui dung huong o ca 8 goc "
          "(chua biet huong thi ve hinh tron)")


def check_preflight_reads(app):
    """Bay thu muc D bat doc truoc cat canh — ba thu truoc day khong doc duoc tai cho.

    D.4 GPS: phai sang tab Trang thai loc "GPS" va doc ba hang, dung luc sap cat
             canh. Gio ba dieu kien do vao mot o.
    D.6 HOME: home CHUA dat truoc day chi the hien bang viec KHONG co dau X — tin
             hieu am, ma tin hieu am thi mat khong bat duoc.
    D.7 Canh bao: phai chuyen tab moi thay co STATUSTEXT do ton dong hay khong.
    """
    from core import i18n
    from core.field import REGISTRY
    from laptop.app import MainWindow
    from laptop.tabs.flight import FlightTab

    was = i18n.lang()
    try:
        i18n.set_lang("vi")

        # --- D.6 + muc F: dai chu duoi ban do ---
        ft = FlightTab()
        ft.resize(600, 400)
        home = (10.8221589, 106.6868454)
        assert ft.map._home_note() == "", "chua ket noi ma da keu suong"

        REGISTRY.feed({"src": "sik", "topic": "position",
                       "data": {"lat": home[0] + 0.0005, "lon": home[1], "alt_rel": 20.0},
                       "ts": time.time()})
        ft.refresh()
        # Chua co HOME_POSITION: tab Bay lay diem dinh vi dau lam home tam, va ve
        # ra dau X y het home that. Phai noi ro do la home TAM, khong duoc de
        # nguoi bay nhin dau X roi tin la RTL se ve day.
        assert ft.map.home is not None and ft.map.home_from_fc is False
        assert "HOME TẠM" in ft.map._home_note(), ft.map._home_note()

        # Rao lay tam la home THAT cua FC -> home con la doan thi khong duoc bia
        # ra so met toi rao.
        bus.emit("sik", "fence", {"FENCE_ENABLE": 1.0, "FENCE_TYPE": 2.0,
                                  "FENCE_RADIUS": 150.0})
        assert "tới rào" not in ft.map._fence_note(), ft.map._fence_note()

        bus.emit("sik", "home", {"lat": home[0], "lon": home[1], "alt_msl": 10.1})
        assert ft.map.home_from_fc is True
        assert "về nhà 56 m" == ft.map._home_note(), ft.map._home_note()
        # Muc F: 0,0005 do vi do = 55,7 m tu home, rao ban kinh 150 m -> con ~94 m.
        assert "còn 94m tới rào" in ft.map._fence_note(), ft.map._fence_note()

        # --- D.7: so canh bao chua doc gan len ten tab ---
        win = MainWindow([{"name": "SITL", "mode": "SIM", "conn": "udp:127.0.0.1:14551"}])
        try:
            tabs = win.ui.tabWidget
            i = tabs.indexOf(win.ui.Messages)
            assert tabs.tabText(i) == "Thông báo", tabs.tabText(i)

            # Tab dang mo la Bay, nen canh bao roi vao tab Thong bao dang an.
            for sev in (2, 4, 6):  # CRITICAL, WARNING, INFO — chi hai cai dau tinh
                bus.emit("sik", "text", {"severity": sev, "text": b"PreArm: Compass"})
            assert tabs.tabText(i) == "Thông báo  (2)", tabs.tabText(i)

            # Doi ngon ngu khong duoc nuot mat con so
            i18n.set_lang("en")
            assert tabs.tabText(i) == "Messages  (2)", tabs.tabText(i)
            i18n.set_lang("vi")

            # Mo tab ra = da doc
            tabs.setCurrentWidget(win.ui.Messages)
            assert tabs.tabText(i) == "Thông báo", tabs.tabText(i)
            # Dang mo tab thi canh bao moi khong duoc dem nua
            bus.emit("sik", "text", {"severity": 3, "text": b"EKF variance"})
            assert tabs.tabText(i) == "Thông báo", tabs.tabText(i)
        finally:
            win.close()
    finally:
        i18n.set_lang(was)
    print("  ok  muc D doc tai cho: GPS ba dieu kien mot o, CHUA CO HOME noi thanh "
          "loi, so canh bao chua doc tren ten tab; kem so met toi rao")


def check_fence_follows_fc(app):
    """Rao nao duoc VE va DO la do FENCE_TYPE cua FC quyet dinh, khong do app.

    Cho hong o day khong phai tinh sai khoang cach ma la DO NHAM MOT RAO FC KHONG
    CHAN: FENCE_RADIUS giu nguyen gia tri cu sau khi tat rao tron, danh sach dinh
    da giac van con trong nhiem vu sau khi tat rao da giac. Bay ho ra buc tuong
    khong ton tai mot lan la lan sau ho khong tin con so nay nua.

    Nen moi bai duoi day deu la: tham so VAN CO DU, chi thieu BIT.
    """
    from core import i18n
    from core.field import REGISTRY
    from laptop.tabs.flight import FlightTab
    from core.field import haversine_m
    from laptop.widgets.map_widget import (FENCE_TYPE_ALT_MAX, FENCE_TYPE_CIRCLE,
                                           FENCE_TYPE_POLYGON, _seg_dist_m)

    # Khoang cach toi doan thang: diem gan nhat nam GIUA doan, khong o hai dinh.
    # Lay dinh gan nhat bang haversine se ra 109,5 m; dung la 77,8 m — chenh 29%,
    # va chenh ve phia "con nhieu cho hon thuc te".
    a, b = (10.0, 106.0), (10.001, 106.001)
    giua = _seg_dist_m((10.001, 106.0), a, b)
    assert 77 < giua < 79, giua
    dinh = min(haversine_m(10.001, 106.0, *q) for q in (a, b))
    assert 109 < dinh < 110 and dinh > giua + 30, (dinh, giua)
    assert _seg_dist_m(a, a, b) == 0.0

    home = (10.8221589, 106.6868454)
    d = 0.0018  # ~200 m moi phia
    poly = [(5001, 4, home[0] - d, home[1] - d), (5001, 4, home[0] - d, home[1] + d),
            (5001, 4, home[0] + d, home[1] + d), (5001, 4, home[0] + d, home[1] - d)]

    was = i18n.lang()
    try:
        i18n.set_lang("vi")
        ft = FlightTab()
        ft.resize(600, 400)
        bus.emit("sik", "home", {"lat": home[0], "lon": home[1], "alt_msl": 10.1})

        def dat(ftype, alt=20.0, dlat=0.0005, items=poly):
            bus.emit("sik", "fence", {"FENCE_ENABLE": 1.0, "FENCE_TYPE": float(ftype),
                                      "FENCE_RADIUS": 150.0, "FENCE_ALT_MAX": 100.0})
            ft.map.fence["items"] = items
            REGISTRY.feed({"src": "sik", "topic": "position",
                           "data": {"lat": home[0] + dlat, "lon": home[1], "alt_rel": alt},
                           "ts": time.time()})
            ft.refresh()
            return ft.map._fence_note()

        # Du ca ba tham so ma FENCE_TYPE = 0: FC khong chan gi. Khong duoc noi
        # "rao BAT" va tuyet doi khong duoc do cai gi.
        note = dat(0)
        assert "FENCE_TYPE=0" in note and "m tới" not in note, note

        # Tung bit mot: chi cai duoc bat moi hien va moi duoc do.
        note = dat(FENCE_TYPE_ALT_MAX)
        assert "còn 80m tới trần" in note, note
        assert "r150m" not in note and "đa giác" not in note, note

        note = dat(FENCE_TYPE_CIRCLE)
        assert "r150m" in note and "còn 94m tới rào" in note, note
        assert "trần" not in note and "đa giác" not in note, note

        note = dat(FENCE_TYPE_POLYGON)
        assert "1 đa giác" in note and "còn 144m tới rào" in note, note
        assert "r150m" not in note and "trần" not in note, note

        # Bat ca ba -> chi hien MOT so: cai GAN NHAT. Doi do cao/vi tri thi con so
        # phai nhay sang rao khac, khong dinh chet vao mot loai.
        assert "còn 5m tới trần" in dat(7, alt=95.0)
        assert "còn 5m tới rào" in dat(7, dlat=0.0013)

        # Vung CAM VAO: cung mot khoang cach, cau nguoc nghia.
        cam = [(5002, 3, home[0] + 0.0030, home[1]),
               (5002, 3, home[0] + 0.0032, home[1] + 0.0002),
               (5002, 3, home[0] + 0.0030, home[1] + 0.0004)]
        note = dat(FENCE_TYPE_POLYGON, dlat=0.0028, items=cam)
        assert "cách vùng cấm" in note, note

        i18n.set_lang("en")
        assert "below the ceiling" in dat(7, alt=95.0)
    finally:
        i18n.set_lang(was)
    print("  ok  rao theo FENCE_TYPE cua FC: tham so con du ma thieu bit thi khong "
          "ve khong do; hien rao GAN NHAT; vung cam noi nguoc lai")


def _make_tlog():
    """Ghi mot .tlog tam: duong xoan oc ban kinh 40 m, cao 3->25 m, kem vai PARAM.

    Dinh dang .tlog dung y het cai SikAdapter ghi ra (xem sik.py): 8 byte moc
    thoi gian micro-giay big-endian dat truoc moi khung MAVLink tho.
    """
    import math
    import struct
    import tempfile

    from pymavlink.dialects.v20 import ardupilotmega as mavlink

    class _Sink:
        def __init__(self):
            self.buf = bytearray()

        def write(self, b):
            self.buf += b

    sink = _Sink()
    mav = mavlink.MAVLink(sink, srcSystem=1, srcComponent=1)
    path = Path(tempfile.mkdtemp()) / "xoanoc.tlog"
    lat0, lon0 = int(10.7620 * 1e7), int(106.6600 * 1e7)
    # 40 m theo vi do va kinh do o vi do 10.76 — chi can dung xap xi, phep thu
    # kiem tra be ngang trong khoang 60..100 m chu khong doi tung met.
    d_lat = 40.0 / 111320.0 * 1e7
    d_lon = 40.0 / (111320.0 * math.cos(math.radians(10.762))) * 1e7

    with open(path, "wb") as f:
        def put(msg, t):
            f.write(struct.pack(">Q", int(t * 1e6)) + msg.pack(mav))

        t0 = 1_700_000_000.0
        for i, name in enumerate((b"ATC_RAT_RLL_P", b"WPNAV_SPEED")):
            put(mavlink.MAVLink_param_value_message(
                name, 0.135 + i, mavlink.MAV_PARAM_TYPE_REAL32, 2, i), t0 + i * 0.1)

        for k in range(300):
            a = 2 * math.pi * k / 60.0
            t = t0 + 1.0 + k * 0.1
            put(mavlink.MAVLink_global_position_int_message(
                int(k * 100), int(lat0 + d_lat * math.sin(a)),
                int(lon0 + d_lon * math.cos(a)), 100000,
                int((3.0 + 22.0 * k / 299) * 1000), 0, 0, 0, 0), t)
            put(mavlink.MAVLink_vfr_hud_message(
                5.0, 5.2, int(math.degrees(a)) % 360, 40,
                3.0 + 22.0 * k / 299, 0.5), t)
    return path


def check_analysis(app):
    """Tab Phan tich: doc .tlog ra chuoi thoi gian, ve do thi va quy dao 3D.

    Diem dang de mat nhat khong phai viec ve, ma la log KHONG co dinh vi GPS.
    FC bao lat=lon=0 khi chua bat duoc fix; moi log `real` trong logs/ deu vay.
    Tron cai (0,0) do vao quy dao thi ra mot duong keo tu san bay toi giua Dai
    Tay Duong — do that: logs/20260807-150529-sim.tlog tung ra "trai rong 16.605
    km" cho mot chuyen bay quanh san.

    Chi doc VAI log chu khong quet ca thu muc: logs/ dang co hon 120 file, doc
    het mat vai phut va bien mot phep thu thanh mot bai chay.
    """
    import math

    from core import logdata
    from laptop.tabs.analysis import AnalysisTab

    # --- 1. Loc lat=lon=0, kiem tra thang tren du lieu dung san ---
    # Khong can file: dung cai bay o day la phep loc, ma phep loc thi dung mot
    # dam diem gia la do duoc, lai khong phu thuoc vao logs/ dang co gi.
    fake = logdata.LogData("khong-co-that.tlog")
    fake.track = [(0.0, 0.0, 0.0, 0.0),          # chua co fix
                  (1.0, 10.7620, 106.6600, 0.0),  # bat duoc fix
                  (2.0, 10.7621, 106.6601, 5.0),
                  (3.0, 0.0, 0.0, 6.0),           # mat fix giua chung
                  (4.0, 10.7622, 106.6602, 7.0)]
    t, e, n, u = fake.local_track()
    assert len(e) == 3, f"loc (0,0) sai: con {len(e)} diem, cho 3"
    assert max(max(e) - min(e), max(n) - min(n)) < 100, "van con diem (0,0) lot vao"
    assert fake.has_fix

    empty = logdata.LogData("rong.tlog")
    empty.track = [(0.0, 0.0, 0.0, 1.0), (1.0, 0.0, 0.0, 2.0)]
    empty.parsed = 200  # co goi, chi la khong bat duoc fix — khac han log rong
    assert not empty.has_fix, "toan diem (0,0) ma van bao co dinh vi"
    assert empty.local_track()[1] == [], "log khong fix ma van tra ra quy dao"

    # --- 2. Tu sinh mot .tlog co quy dao BIET TRUOC roi doc lai ---
    # Khong lay file trong logs/: thu muc do dang co 295 file va phinh them sau
    # moi chuyen bay, ma cai co quy dao ngang lai nam trong nhom file lon — quet
    # tim thi vua cham vua phu thuoc vao hom nay may co log gi. Tu ghi mot duong
    # xoan oc thi biet truoc dap an, va van di qua dung duong doc that.
    made = _make_tlog()
    d = logdata.load(made)
    _, e, n, u = d.local_track()
    assert len(e) > 100, f"doc lai .tlog tu sinh chi ra {len(e)} diem"
    # Xoan oc ban kinh 40 m -> be ngang ~80 m ca hai truc, cao 3..25 m.
    assert 60 < max(e) - min(e) < 100, f"be ngang dong sai: {max(e) - min(e):.0f} m"
    assert 60 < max(n) - min(n) < 100, f"be ngang bac sai: {max(n) - min(n):.0f} m"
    assert 20 < max(u) - min(u) < 25, f"do cao sai: {max(u) - min(u):.1f} m"
    # PARAM_VALUE phai tach theo TEN tham so, khong gop chung mot duong.
    assert "PARAM.ATC_RAT_RLL_P" in d.names(), [n for n in d.names() if "PARAM" in n]
    assert "PARAM.WPNAV_SPEED" in d.names()
    assert "PARAM_VALUE.param_value" not in d.names(), "tham so bi gop chung mot duong"
    assert "VFR_HUD.alt" in d.names()
    with_fix = d

    # Doc mot file that lam phep thu khoi: dinh dang tlog cua chinh app ghi ra.
    real = sorted((Path(__file__).resolve().parent.parent / "logs").glob("*.tlog"),
                  key=lambda q: q.stat().st_size)
    if real:
        smoke = logdata.load(real[len(real) // 2], limit_seconds=30)
        assert smoke.parsed > 0, f"khong doc noi goi nao tu {real[len(real) // 2]}"

    # --- 3. Tab ve duoc that, khong chi la khong bao loi ---
    tab = AnalysisTab()
    tab.resize(1000, 700)
    tab.show()
    app.processEvents()
    tab._loaded(with_fix)
    app.processEvents()
    assert tab.fields.count() > 0, "doc log xong ma danh sach field van rong"
    assert len(tab.traj._e) > 50, "quy dao khong toi duoc widget 3D"

    # Goc nhin ban dau phai xoay theo huong bay: bay thang ma nhin doc theo duong
    # bay thi 132 m bep con vai pixel — do that tren 20260729-104857-sim.tlog.
    ang = abs(math.degrees(tab.traj._yaw)) % 180
    assert 5 < ang < 175, f"goc nhin ban dau nhin doc duong bay: {ang:.0f} do"

    name = with_fix.names()[0]
    for i in range(tab.fields.count()):
        tab.fields.item(i).setSelected(tab.fields.item(i).text() == name)
    app.processEvents()
    assert len(tab.chart.series()) == 1, "chon mot field ma khong ra mot duong"

    # Chuan hoa: hang so khong duoc chia cho 0, truc phai ve dung 0..1.
    tab.norm.setChecked(True)
    app.processEvents()
    assert tab.ay.min() < 0.1 and tab.ay.max() > 0.9, (tab.ay.min(), tab.ay.max())

    # Ve lai nhieu lan KHONG duoc de lai truc cu chong len truc moi.
    for _ in range(3):
        tab._replot()
    app.processEvents()
    assert len(tab.chart.axes()) == 2, f"truc bi nhan doi: {len(tab.chart.axes())}"

    assert tab.traj.grab().toImage().width() > 10, "widget quy dao khong ve ra gi"

    # Bo loc KHONG duoc lam mat cai dang ve: go vao o loc de tim them mot field
    # thi nhung field da chon bi an di, ma an di khong co nghia la bo chon.
    tab.filter.setText("khong-co-field-nao-ten-nhu-vay")
    app.processEvents()
    assert tab.fields.count() == 0, "bo loc rac ma van con field"
    assert len(tab.chart.series()) == 1, "loc mot cai la mat luon duong dang ve"
    tab.filter.setText("")
    app.processEvents()
    assert len(tab.chart.series()) == 1, "xoa bo loc xong do thi khong ve lai"

    # Log khong fix: phai NOI RA chu khong ve mot duong thang dung.
    tab._loaded(empty)
    app.processEvents()
    assert tab.traj._e == [] and tab.traj._note, "log khong fix ma van ve quy dao"
    assert "GPS" in tab.traj._note, f"log co goi ma bao nham la log rong: {tab.traj._note}"

    # File khong phai .tlog: pymavlink khong nem loi, no doc ra 0 goi. Man hinh
    # phai noi thang la khong doc duoc gi, khong duoc hien "0 goi · 0 field" nhu
    # the vua doc thanh cong mot log rong ruot.
    nothing = logdata.LogData("rac.tlog")
    tab._loaded(nothing)
    app.processEvents()
    assert tab.fields.count() == 0 and not tab.chart.series()
    assert "0" not in tab.summary.text().split("—")[-1], (
        f"file rac bi bao nhu doc thanh cong: {tab.summary.text()}")
    assert tab.traj._note and "GPS" not in tab.traj._note, (
        f"file rac ma do loi cho GPS: {tab.traj._note}")

    tab.close()
    print(f"  ok  tab Phan tich: {len(with_fix.fields)} field tu .tlog, PARAM tach theo "
          "ten, diem lat=lon=0 bi loc, bo loc khong lam mat duong dang ve, log "
          "khong fix va file khong doc duoc noi ra hai cau khac nhau")


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    check_normalize()
    check_source_filter()
    check_flatten()
    check_sensor_decode()
    check_bus()
    check_usb_detect(app)
    check_link_status(app)
    check_tabs(app)
    check_field(app)
    check_authority(app)
    check_arm_throttle_guard(app)
    check_disarm_hold(app)
    check_widgets(app)
    check_remote(app)
    check_online_tiles(app)
    check_takeoff_guard(app)
    check_mission_readonly(app)
    check_replay_locks(app)
    check_fence(app)
    check_waypoints(app)
    check_wp_write(app)
    check_nudge_keys(app)
    check_stream_rearm(app)
    check_replay(app)
    check_tlog_roundtrip(app)
    check_dead_socket(app)
    check_banner_health(app)
    check_adapter_live(app)
    check_video(app)
    check_i18n(app)
    check_param_doc(app)
    check_telemetry_warn(app)
    check_close_guard(app)
    check_home_note(app)
    check_drone_marker(app)
    check_preflight_reads(app)
    check_fence_follows_fc(app)
    check_analysis(app)
    print("selfcheck: PASS")
