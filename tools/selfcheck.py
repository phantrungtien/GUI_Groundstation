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

PORT = 14559  # cong rieng cho self-check, khong dung vao SITL that


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
    assert out["SENSOR.gps"] == "TOT", out
    assert out["SENSOR.3d_mag"] == "HONG", "cam bien hong phai doc ra chu HONG"
    assert out["SENSOR.logging"] == "TOT (tat)", out
    # Cam bien khong lap tren may bay nay thi khong duoc bay ra lam nhieu bang
    assert not any(k.endswith(".rc_receiver") for k in out), out
    print(f"  ok  giai ma {len(SENSOR_BITS)} bit cam bien cua SYS_STATUS")


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
    assert ls._info["sik"].text() == "chua ket noi", ls._info["sik"].text()

    ls.on_envelope({"src": "sik", "topic": "position", "data": {}, "ts": time.time()})
    ls._tick()
    assert ls._info["sik"].text() == "800 B/s", ls._info["sik"].text()

    ls.last_seen["sik"] = time.time() - 5
    ls._tick()
    assert ls._info["sik"].text().startswith("MAT"), ls._info["sik"].text()
    print("  ok  Link status xam khi mat goi")


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

    # field ngung cap nhat -> danh dau tuoi, khong de den nhu dang song
    st._seen["ATTITUDE.roll"] = time.time() - 10
    st._age()
    assert st.model.item(0, 3).text() == "10s", st.model.item(0, 3).text()

    for sev, txt in ((6, b"EKF3 IMU0 is using GPS"), (4, b"PreArm: Compass"), (2, b"battery low")):
        bus.emit("sik", "text", {"severity": sev, "text": txt})
    assert ms.list.count() == 3, ms.list.count()
    ms.filter.setCurrentIndex(2)  # canh bao tro len
    hidden = [i for i in range(3) if ms.list.item(i).isHidden()]
    assert hidden == [0], hidden
    print("  ok  tab Status (loc/tam dung/tuoi) + Messages (loc severity)")


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
    """Nut do phai di truoc moi kiem tra quyen."""
    from core import authority

    sent = []

    class FakeAdapter:
        def send(self, action, args=None):
            sent.append(action)
            return {"ok": action}

    authority.register("sik", FakeAdapter())
    try:
        authority.set_authority(authority.ROS2)
        assert "error" in authority.dispatch({"target": "sik", "action": "arm"})
        assert "error" in authority.dispatch({"target": "sik", "action": "takeoff"})
        for esc in ("rtl", "land", "disarm"):
            authority.set_authority(authority.ROS2)
            assert "ok" in authority.dispatch({"action": esc}), esc
            # Bam nut do la tin hieu nhuong quyen (2.4): khong keo quyen ve GCS
            # thi node offboard van stream setpoint -> kich ban hong #5.
            assert authority.AUTHORITY == authority.GCS, esc
        assert sent == ["rtl", "land", "disarm"], sent

        authority.set_authority(authority.GCS)
        assert "ok" in authority.dispatch({"target": "sik", "action": "arm"})
    finally:
        authority.unregister("sik")
        authority.set_authority(authority.GCS)
    print("  ok  nut do di duoc trong luc quyen thuoc ve ROS2")


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
    ct.log.connect(logs.append)
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
        assert "do cao khong doi" in logs[-1], logs
        # Con leo len that thi im lang
        logs.clear()
        REGISTRY.feed({"src": "sik", "topic": "position", "data": {"alt_rel": 4.0},
                       "ts": time.time()})
        ct._check_climb(0.0)
        assert not logs, logs
    finally:
        authority_mod.unregister("sik")
        REGISTRY.fields.clear()
        ct.close()
    print("  ok  TAKEOFF: chan khi khong o GUIDED, keu khi nhan lenh ma khong len")


def check_mission_buttons(app):
    """Nhiem vu ROS2 di sang companion, KHONG xuong FC — va chi khi da giao quyen."""
    from core import authority
    from laptop.tabs.control import ControlTab

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
    logs = []
    ct.log.connect(logs.append)
    try:
        ct.set_mode("SIM")
        # Dang cam lai (MANUAL) ma bam mot nhiem vu tu hanh -> khong duoc phep
        assert not ct.mission_btns[0].isEnabled(), "MANUAL ma nut nhiem vu van bam duoc"
        ct.mission_btns[0].click()
        # `set_authority` cung gui qua nua remote, nen chi loc dung lenh nhiem vu
        missions = lambda: [x for x in sent["remote"] if x[0] == "mission"]
        assert not missions(), sent["remote"]

        ct.auto.setChecked(True)
        assert ct.mission_btns[0].isEnabled()
        ct.mission_btns[0].click()
        assert missions() == [("mission", {"name": "mission_circle"})], sent["remote"]
        assert not sent["sik"], "nhiem vu ROS2 khong duoc gui xuong FC"

        # Bam nut do trong luc nhiem vu dang chay: quyen ve GCS, nut nhiem vu tat theo
        ct.btn_rtl.click()
        assert authority.AUTHORITY == authority.GCS
        assert not ct.mission_btns[0].isEnabled(), "keo quyen ve roi ma nut nhiem vu con bat"

        # Ten nut ben nay phai nam trong danh sach trang ben bridge. Lech mot ky tu
        # thi bam nut khong co gi xay ra, va bridge chi ghi mot dong warn tren
        # companion — cho ma nguoi bay khong bao gio nhin thay.
        import ast

        from laptop.tabs.control import MISSIONS

        src = (Path(__file__).resolve().parent / "ros2_bridge.py").read_text()
        allowed = next(
            ast.literal_eval(node.value)
            for node in ast.parse(src).body
            if isinstance(node, ast.Assign) and node.targets[0].id == "MISSIONS_OK"
        )
        thieu = [n for _, n in MISSIONS if n not in allowed]
        assert not thieu, f"nut co ma bridge tu choi: {thieu}"
    finally:
        authority.unregister("sik")
        authority.unregister("remote")
        authority.set_authority(authority.GCS)
        ct.close()
    print("  ok  nut nhiem vu ROS2 (chan o MANUAL, gui qua nua remote)")


def check_replay_locks(app):
    """REPLAY khoa toan bo nut dieu khien, KE CA nut do."""
    from laptop.app import MainWindow

    tlogs = sorted((Path(__file__).resolve().parent.parent / "logs").glob("*.tlog"))
    if not tlogs:
        print("  --  bo qua check REPLAY khoa nut: chua co .tlog nao trong logs/")
        return

    win = MainWindow([{"name": "replay", "mode": "REPLAY", "path": str(tlogs[-1])}])
    win.panel.list.setCurrentRow(0)
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
    win.panel.list.setCurrentRow(0)
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

    assert "dang cho du lieu" in states[0], states[0]
    assert "mo phong SITL" in states[1], states[1]
    assert "MAT KET NOI" in states[2], states[2]
    print("  ok  banner: cho du lieu -> dang chay -> mat ket noi")


def check_adapter_live(app):
    """Chay SikAdapter that voi nguon MAVLink gia tren UDP."""
    from PySide6.QtCore import QTimer
    from pymavlink import mavutil

    seen = {}
    adapter = SikAdapter({"name": "selfcheck", "mode": "SIM", "conn": f"udp:127.0.0.1:{PORT}"})
    adapter.envelope.connect(lambda e: seen.setdefault(e["topic"], e))
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
            time.sleep(0.1)

    t = threading.Thread(target=sender, daemon=True)
    t.start()
    QTimer.singleShot(2500, app.quit)
    app.exec()
    stop.set()
    adapter.stop()

    assert "position" in seen, f"khong nhan duoc position, chi co {list(seen)}"
    assert "heartbeat" in seen and "status" in seen, list(seen)
    assert "link" in seen, "khong co so byte/s"
    assert seen["link"]["data"]["bps"] > 0, seen["link"]
    assert seen["position"]["src"] == "sik"
    print(f"  ok  SikAdapter live — {seen['link']['data']['bps']} B/s, topic: {sorted(seen)}")


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
    check_widgets(app)
    check_remote(app)
    check_online_tiles(app)
    check_takeoff_guard(app)
    check_mission_buttons(app)
    check_replay_locks(app)
    check_replay(app)
    check_tlog_roundtrip(app)
    check_dead_socket(app)
    check_banner_health(app)
    check_adapter_live(app)
    print("selfcheck: PASS")
