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
os.environ.setdefault("QT_QUICK_BACKEND", "software")  # QML (touch/) ve khong can GPU

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


def flight(w=600, h=400):
    """Man bay dung lam vat thi cho cac bai do widget dung chung (ban do, rao,
    canh bao, duong bay).

    Truoc day cac bai nay dung `FlightTab` lam vo. Tab do da bi xoa khi hai man
    bay gop lam mot; `touch.Backend` giu dung vai tro cu — no la cho bus di qua
    de toi widget. Khong dung MainWindow: bai nao chi do mot widget thi dung ca
    cua so len la cham va keo theo ca dong thu khong lien quan.
    """
    from core.field import REGISTRY
    from laptop.touch.backend import Backend

    # "App vua mo, chua nhan goi nao": Backend.__init__ goi refresh() ngay, ma
    # refresh() doc thang REGISTRY — con so lieu cua bai TRUOC trong do la no dung
    # len mot home tam truoc ca cau assert dau tien cua bai nay.
    REGISTRY.fields.clear()
    b = Backend()
    # Gan mot profile, KHONG gan adapter — dung trang thai "SiK vua dut: khoa
    # lenh, giu man hinh". Chua gan gi thi profile = None, va o do `refresh()`
    # co y quet sach REGISTRY moi nhip (goi ve tre khong duoc dung len home gia),
    # nen bai nao bom so lieu vao REGISTRY roi doc ra se thay trong khong.
    # `_live()` van False vi adapter con None — dung nhu truoc.
    b.attach({"name": "selfcheck", "mode": "SIM"}, None)
    b.map.resize(w, h)
    # Tat nhip tu ve 200 ms: bai nao cung tu goi `refresh()` o dung cho no muon do,
    # con de timer chay thi no doc so lieu con sot cua bai TRUOC va dung len mot
    # home tam ngay truoc cau assert dau tien.
    b._timer.stop()
    return b


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


def check_join_text():
    """3 manh that tu logs/20261011-112025-real.tlog: manh 2, 3 tung bi giong doc
    doc to vi khong mo dau bang "PreArm"."""
    from core.adapters.sik import join_text
    parts = ["PreArm: SERIAL2_OPTIONS bit 10 ('no forward mavlin",
             "k') must not be set; use MAVn_OPTIONS bit 1 instea", "d"]
    pend = []
    got = [join_text(pend, {"severity": 2, "text": s, "id": 1, "chunk_seq": i})
           for i, s in enumerate(parts)]
    assert got[:2] == [None, None], got
    assert got[2]["text"] == "".join(parts) and got[2]["severity"] == 2, got[2]
    assert pend == []
    # id 0 = cau mot manh (va MAVLink1): di thang
    one = {"severity": 6, "text": "ArduPilot Ready", "id": 0, "chunk_seq": 0}
    assert join_text(pend, one) is one
    # manh cuoi cau 2 mat tren song: cau 2 (thieu duoi) ra khi cau 3 toi
    join_text(pend, {"severity": 2, "text": parts[0], "id": 2, "chunk_seq": 0})
    lost = join_text(pend, {"severity": 2, "text": parts[0], "id": 3, "chunk_seq": 0})
    assert lost["text"] == parts[0], lost
    print("  ok  ghep STATUSTEXT nhieu manh (PreArm SERIAL2_OPTIONS 3 manh)")


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
    # Node task tren companion bao "FIRE: ..." qua MAVROS -> FC chuyen tiep tu 1/191.
    assert from_autopilot(Msg(191, "STATUSTEXT")), "STATUSTEXT cua node task (qua MAVROS) bi bo"
    print("  ok  chi nhan goi tu FC (bo MAVROS/MAVProxy, giu RADIO_STATUS + STATUSTEXT)")


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


def check_replug(app):
    """Rut day USB cua FC roi cam lai: tu noi lai DUNG thiet bi do, qua cong moi.

    Ten cong doi khi cam lai (ttyACM0 -> ttyACM1) nen phai nhan theo VID/PID/so
    serial. Cam mot thiet bi KHAC vao thi khong duoc noi nham vao no.
    """
    import laptop.app as appmod
    from core.adapters.sik import SikAdapter

    win = appmod.MainWindow([])
    calls, ports, boxes = [], [], []
    orig = appmod.detect_serial
    orig_box = appmod.QMessageBox.critical
    appmod.detect_serial = lambda tpl=None: list(ports)
    appmod.QMessageBox.critical = staticmethod(lambda *a, **k: boxes.append(a[-1]))
    win.connect_to = lambda p, replug=False: calls.append(dict(p, _replug=replug))
    prof = {"name": "MicoAir743", "mode": "REAL", "conn": "/dev/ttyACM0", "baud": 115200,
            "sysid": 254, "usb_id": "1209:5741:ABC", "detected": True}
    try:
        win.profile, win.mode = prof, "REAL"
        win.link_status.last_seen[SikAdapter.SRC] = time.time()  # da tung co du lieu
        win._on_failed("device disconnected")
        assert win._reconnect.isActive(), "rut day ma khong cho cam lai"
        win._refresh_banner()
        assert "cắm lại" in win.banner.text() and "ttyACM0" in win.banner.text(), \
            win.banner.text()

        win._try_reconnect()  # chua cam lai
        assert not calls and win._reconnect.isActive()

        ports[:] = [{"conn": "/dev/ttyUSB0", "usb_id": "0403:6001:X", "writable": True}]
        win._try_reconnect()  # cam mot radio khac vao
        assert not calls, f"noi nham vao thiet bi khac: {calls}"

        ports.append({"conn": "/dev/ttyACM1", "usb_id": "1209:5741:ABC", "writable": True})
        win._try_reconnect()  # FC cam lai, ten cong da doi
        assert [c["conn"] for c in calls] == ["/dev/ttyACM1"], calls
        assert calls[0]["sysid"] == 254 and calls[0]["baud"] == 115200, "mat cau hinh cu"
        # Cam lai phai GIU moc "da tung co goi": FC dang khoi dong ma mo lai hong
        # thi van la dang bay, khong duoc bat hop thoai modal che nut do.
        assert calls[0]["_replug"] is True, "cam lai di nham duong ket noi moi"
        assert not win._reconnect.isActive()

        # Bam Ngat trong luc cho: thoi cho
        win._reconnect.start()
        type(win).disconnect(win)
        assert not win._reconnect.isActive(), "bam Ngat ma van tu noi lai"

        # Nguoc lai: NGUOI DUNG tu mo mot nguon moi thi moc cua phien truoc phai mat.
        # Do that 04/10/2026: con sot lai thi mo cong hong khong ra hop thoai loi,
        # banner bao MAT KET NOI va timer cho cam lai quet mai cong khong ton tai.
        win.link_status.last_seen[SikAdapter.SRC] = time.time()  # phien truoc co goi
        type(win).connect_to(win, {"name": "sai cong", "mode": "REAL",
                                   "conn": "/dev/ttyUSB_khong_ton_tai", "baud": 57600})
        t0 = time.time()
        while win.adapter is not None and time.time() - t0 < 5:
            app.processEvents()
            time.sleep(0.01)
        assert boxes and not win._reconnect.isActive(), \
            f"mo cong hong bi coi la dut giua chuyen bay: hop thoai={boxes} " \
            f"cho cam lai={win._reconnect.isActive()}"
        type(win).disconnect(win)

        # SITL qua tcp va REPLAY: khong co gi de cam lai
        assert not win._replugable({"mode": "SIM", "conn": "tcp:127.0.0.1:5762"})
        assert not win._replugable({"mode": "REAL", "conn": "udp:0.0.0.0:14550"})
        assert not win._replugable({"mode": "REPLAY", "path": "logs/a.tlog"})
    finally:
        appmod.detect_serial = orig
        appmod.QMessageBox.critical = orig_box
        win._reconnect.stop()
        win.close()
    print("  ok  rut USB cam lai: tu noi lai dung thiet bi (nhan theo VID/PID/serial, "
          "ten cong doi van nhan), khong noi nham thiet bi khac, bam Ngat la thoi; "
          "ket noi moi khong mang moc cua phien truoc")


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


def check_video_h264(app):
    """Video H.264 qua UDP (Jetson tu 11/10/2026): giai ma that, va ba kieu hong
    giong MJPEG — dung hinh, mat goi, co lai — deu phai ra dung o man hinh.

    Nguon gia la GStreamer x264 -> MPEG-TS -> UDP, dung duong Jetson dang day.
    "Camera treo" = MOT anh phuc tap dong bang (smpte + imagefreeze): x264 van ra
    khung giai ma khac nhau tung chut, chinh cai lam phep bam byte that bai.
    """
    import shutil
    import subprocess

    import socket

    import laptop.widgets.video as video_mod
    from laptop.widgets.video import VideoSource, count_loss

    # Dem goi TS mat theo continuity counter — Jetson ha bitrate theo dung so nay.
    def ts(pid, cc, payload=True):
        return bytes([0x47, pid >> 8, pid & 0xFF, (0x10 if payload else 0x20) | cc]) + bytes(184)
    last = {}
    assert count_loss(ts(256, 0) + ts(256, 1) + ts(256, 3), last) == (3, 1), "mat CC 2 ma khong dem"
    assert count_loss(ts(256, 3) + ts(0x1FFF, 9) + ts(257, 7, payload=False), last) == (1, 0), \
        "goi lap / null / khong payload bi tinh la mat"
    # Nhay 7 (mat 6 goi = 1 datagram 1128 B) van dem; nhay >= 8 = sai thu tu / ffmpeg
    # khoi dong lai -> bo qua, va goi den tre khong lam goi ke tiep bi tinh mat.
    assert count_loss(ts(256, 10), last) == (1, 6), "nhay 7 phai dem mat 6 goi"
    assert count_loss(ts(256, 9) + ts(256, 11), last) == (2, 0), "goi den tre (lui 1) bi tinh la mat"
    assert count_loss(ts(256, 3), last) == (1, 0), "nhay 8 (ffmpeg khoi dong lai) bi tinh la mat"

    gst = shutil.which("gst-launch-1.0")
    if not gst or subprocess.run(["gst-inspect-1.0", "x264enc"], capture_output=True).returncode:
        print("  --  bo qua video H.264: may nay khong co gst-launch-1.0 + x264enc")
        return
    port = VIDEO_PORT + 3

    def sender(src, to=port):
        return subprocess.Popen(
            [gst, "-q", *src.split(), "!", "video/x-raw,width=320,height=240,framerate=25/1",
             "!", "x264enc", "tune=zerolatency", "speed-preset=ultrafast", "key-int-max=25",
             "!", "mpegtsmux", "!", "udpsink", "host=127.0.0.1", f"port={to}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    moving = "videotestsrc is-live=true pattern=ball"
    frozen = "videotestsrc pattern=smpte num-buffers=1 ! imagefreeze is-live=true ! videoconvert"

    def until(pred, ms):
        t0 = time.monotonic()
        while not pred() and time.monotonic() - t0 < ms / 1000:
            app.processEvents()
            time.sleep(0.01)
        return pred()

    frozen_s, video_mod.FROZEN_S = video_mod.FROZEN_S, 1.0
    src = VideoSource()
    fb = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # dong vai Jetson :5601
    fb.bind(("127.0.0.1", 0))
    fb.setblocking(False)
    reports = []

    def heard():
        try:
            reports.append(fb.recv(64).decode())
        except BlockingIOError:
            pass
        return reports

    s = sender(moving)
    try:
        src.start(f"udp://0.0.0.0:{port}", feedback=f"127.0.0.1:{fb.getsockname()[1]}")
        assert until(lambda: src.pixmap is not None, 8000), f"H.264 khong ra khung: {src.note}"
        assert src.pixmap.width() == 320 and src.alive
        assert not until(lambda: src.frozen, 2500), "hinh dang chay ma bao dung hinh"
        # Bao cao dung dinh dang run_gui.py doc: "loss=<ti le>", localhost thi ~0.
        assert until(heard, 3000), "co goi H.264 ma khong bao mat goi ve Jetson"
        loss = float(reports[-1].split("=", 1)[1])
        assert reports[-1].startswith("loss=") and loss < 0.02, f"bao cao sai: {reports}"

        # Thu tu nhu ngoai doi: nguon tat -> o xam -> nguon len lai. Tat roi bat
        # NGAY (khong nghi) thi QMediaPlayer co luc dung them ~4,8 s vi DTS nhay
        # lui (do 11/10/2026) — server Jetson khoi dong lai mat hang chuc giay nen
        # it gap; doi het bai nay nho thoi gian cho rong (10 s).
        s.kill(); s.wait()  # mat goi UDP
        assert until(lambda: not src.alive and not src.frozen, 4000), "het goi ma khong o xam"
        assert src.pixmap is None and src.note[0] == "vid.lost", src.note
        # Het goi thi IM, khong gui "loss=0": Jetson im 5 s moi tu ha bitrate.
        reports.clear()
        assert not until(heard, 1500), f"khong co goi ma van bao cao: {reports}"

        s = sender(frozen)  # camera treo: khung van toi deu, anh dung yen
        assert until(lambda: src.frozen, 10000), "anh dong bang qua x264 ma khong bao dung hinh"
        assert src.pixmap is None and src.note[0] == "vid.frozen" and src.fps > 5, \
            f"dung hinh: pixmap={src.pixmap} note={src.note} fps={src.fps:.1f}"

        s.kill(); s.wait()
        assert until(lambda: not src.alive and not src.frozen, 4000), "het goi ma khong o xam"
        s = sender(moving)  # goi toi lai: QMediaPlayer phai tu chay tiep
        assert until(lambda: src.alive and src.pixmap is not None, 10000), \
            f"goi UDP toi lai ma hinh khong ve: {src.note}"
        assert not src.frozen

        src.stop()  # nha cong: start lai cung cong phai ra hinh
        assert src.pixmap is None and not src.alive
        src.start(f"udp://0.0.0.0:{port}")
        assert until(lambda: src.pixmap is not None, 10000), "stop() roi start() lai khong ra hinh"
    finally:
        s.kill()
        s.wait()
        src.stop()
        fb.close()
        video_mod.FROZEN_S = frozen_s

    # Khong giu khung: gui DUNG 20 khung 5 fps roi im — khung nao ket lai trong
    # duong ong (h264parse cho khung SAU de biet khung nay het) la khong bao gio ra.
    # Do 16/10/2026 voi mpegtsmux: thieu `alignment=au` -> 19/20, co -> 20/20.
    n = [0]
    src.updated.connect(lambda: n.__setitem__(0, n[0] + (src.pixmap is not None)))
    src.start(f"udp://0.0.0.0:{port + 2}")
    s = subprocess.Popen(
        [gst, "-q", "videotestsrc", "is-live=true", "pattern=ball", "num-buffers=20",
         "!", "video/x-raw,width=320,height=240,framerate=5/1", "!", "x264enc",
         "tune=zerolatency", "speed-preset=ultrafast", "key-int-max=25", "!", "mpegtsmux",
         "!", "udpsink", "host=127.0.0.1", f"port={port + 2}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert until(lambda: s.poll() is not None, 10000), "ben gui 20 khung khong xong"
        until(lambda: n[0] >= 20, 1000)
        assert n[0] == 20, f"duong ong giu khung: gui 20, ra {n[0]} (thieu = tre bay nhieu khung)"
    finally:
        s.kill()
        s.wait()
        src.stop()

    # Du phong may khong co GStreamer (Windows): QMediaPlayer van phai ra hinh
    # (tre hon ~0,9 s, xem dau video.py — nhung co hinh con hon o xam).
    gst_mod, video_mod.Gst = video_mod.Gst, None
    s = sender(moving, port + 1)  # cong khac: QMediaPlayer giu cong toi khi bi huy
    try:
        src.start(f"udp://0.0.0.0:{port + 1}")
        assert until(lambda: src.pixmap is not None and src.alive, 10000), \
            f"du phong QMediaPlayer khong ra hinh: {src.note}"
        # Im qua ~20 s thi player bao "Demuxing failed" va DUNG HAN (Lenovo 21/10) —
        # nguon con do thi phai tu mo lai, khong cho nguoi bay khoi dong lai app.
        src._player.stop()
        t_stop = time.monotonic()
        assert until(lambda: src._last > t_stop + 0.5, 10000), "player dung han ma khong mo lai"
        # Im lau ma player van "dang phat" (Jetson khoi dong lai, 19:33 21/10): cung mo lai.
        s.kill(); s.wait()
        t_kill = time.monotonic()
        assert until(lambda: src._replay_t > t_kill, (video_mod.REPLAY_S + 2) * 1000), \
            "nguon im lau ma khong mo lai player"
        # Mo lai roi thi player nam cho goi (LoadingMedia): DE YEN. Truoc day cu 0,5-2 s
        # lai huy lan mo dang cho, goi ve roi van bi huy -> do 23/10 tren luong Jetson
        # that phat lai: 4,7 s moi co hinh; de yen: 1,7 s.
        t_reopen = src._replay_t
        until(lambda: False, 3 * video_mod.RETRY_S * 1000)
        assert src._replay_t == t_reopen, "dang cho goi ma van huy lan mo player"
        s = sender(moving, port + 1)
        t_back = time.monotonic()
        assert until(lambda: src._last > t_back, 5000), "nguon len lai 5 s van chua co hinh"
        back_s = src._last - t_back
    finally:
        s.kill()
        s.wait()
        video_mod.Gst = gst_mod

    # Dien thoai: khung ve thang bang VideoOutput (QML), VideoSource chi dem nhip va
    # GPU_THUMB_HZ lan/giay so dung hinh — khong giu pixmap. Player rieng: sink co dinh.
    import tempfile
    from PySide6.QtCore import QUrl
    from PySide6.QtQuick import QQuickView
    qml = Path(tempfile.mkdtemp()) / "v.qml"
    qml.write_text("import QtQuick\nimport QtMultimedia\nVideoOutput { width: 320; height: 240 }\n")
    view = QQuickView()
    view.setSource(QUrl.fromLocalFile(str(qml)))
    gpu = VideoSource()
    gpu.set_output(view.rootObject())
    video_mod.Gst = None
    s = sender(moving, port + 2)
    try:
        gpu.start(f"udp://0.0.0.0:{port + 2}")
        assert until(lambda: gpu.alive and gpu.fps > 10, 10000), f"VideoOutput khong ra khung: {gpu.note}"
        assert gpu.on_gpu and gpu.pixmap is None, "duong GPU van giu pixmap"
        assert not until(lambda: gpu.frozen, 2500), "GPU: hinh dang chay ma bao dung hinh"
        s.kill(); s.wait()
        s = sender(frozen, port + 2)
        # doi nguon cung cong: DTS nhay lui, QMediaPlayer co luc dung ~4,8 s (xem tren)
        assert until(lambda: gpu.frozen and not gpu.alive, 12000), "GPU: dung hinh ma khong bao"
    finally:
        s.kill()
        s.wait()
        video_mod.Gst = gst_mod
    # Huy ngay tren main thread — xem cuoi check_video().
    for v in (src, gpu):
        v.stop()
        v.deleteLater()
    view.deleteLater()
    app.processEvents()
    # Dau gio `run_gui.py --stamp` (pi5/latency_stamp.py): ve dung kieu stamp() roi doc lai.
    from PySide6.QtGui import QColor as _C, QImage as _I
    t = time.time()
    img = _I(1280, 720, _I.Format.Format_RGB32)
    img.fill(_C(90, 90, 90))
    v = int(t * 1000) & video_mod.STAMP_MASK
    x = (v << 8) | (~sum(v.to_bytes(5, "big")) & 0xFF)
    for i in range(48):
        r, c = divmod(i, 24)
        for yy in range(16):
            for xx in range(16):
                img.setPixelColor(c * 16 + xx, 720 - 32 + r * 16 + yy,
                                  _C("white") if (x >> (47 - i)) & 1 else _C("black"))
    assert abs(video_mod.read_stamp(img) - t) < 0.002, "doc sai dau gio --stamp"
    img.setPixelColor(3 * 16 + 8, 720 - 32 + 8, _C("white") if not (x >> 44) & 1 else _C("black"))
    assert video_mod.read_stamp(img) is None, "o hong ma checksum khong bat"
    plain = _I(1280, 720, _I.Format.Format_RGB32)
    plain.fill(_C("black"))
    assert video_mod.read_stamp(plain) is None, "khung khong co dau gio ma doc ra gio"
    print("  ok  video H.264/UDP — giai ma that; doc dau gio --stamp; dung hinh (anh dong bang qua x264) xoa anh; "
          f"mat goi o xam; goi toi lai tu hien; du phong QMediaPlayer ra hinh, dung han / im 5 s thi tu mo lai, dang cho goi thi de yen (nguon len lai -> hinh {back_s:.1f} s); VideoOutput (dien thoai) dem nhip + bao dung hinh, khong giu pixmap; dem goi TS mat "
          "va bao \"loss=\" ve Jetson moi giay, het goi thi im; khong giu khung (20/20)")


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

    assert st.model.columnCount() == 3, st.model.columnCount()  # Field, Gia tri, Giai thich
    song = st.model.item(0, 1).foreground().color().name()
    st._seen["ATTITUDE.roll"] = time.time() - 10
    st._age()
    xam = st.model.item(0, 1).foreground().color().name()
    assert xam == STALE_COLOR and xam != song, (song, xam)

    for sev, txt in ((6, b"EKF3 IMU0 is using GPS"), (4, b"PreArm: Compass"), (2, b"battery low")):
        bus.emit("sik", "text", {"severity": sev, "text": txt})
    assert ms.list.count() == 3, ms.list.count()
    assert ms.list.item(0).text().endswith("battery low"), "dong moi nhat phai nam tren cung"
    ms.filter.setCurrentIndex(2)  # canh bao tro len
    hidden = [i for i in range(3) if ms.list.item(i).isHidden()]
    assert hidden == [2], hidden
    print("  ok  tab Status (loc/tam dung/het tuoi thi xam) + Messages (loc severity, moi nhat tren cung)")


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
        ct.cmd._thr = (1496, time.time() - 30)
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
    """DISARM hai bac: bam mot lan = lenh thuong, bam lai trong 3s = force 21196.

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
        ct.cmd._rng = None
        ct._kill_cancel()  # moi truong hop la mot lan bam MOI, khong noi tiep lan truoc
        if v is not None:
            REGISTRY.feed({"src": "sik", "topic": "heartbeat", "data": {"landed": v},
                           "ts": time.time()})
        if rng_cm is not None:
            ct.cmd._rng = (rng_cm, 5, 400, time.time())

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
        ct.btn_kill.click()
        assert sent == [("disarm", {})], sent
        # Lan mot: nut doi chu, HAU QUA hien ngay canh nut
        assert "BẤM LẠI" in ct.btn_kill.text(), ct.btn_kill.text()
        assert "RƠI" in ct.note.text(), ct.note.text()

        # Bam lai trong 3s: force ngay, khong phai giu
        sent.clear()
        ct.btn_kill.click()
        assert sent == [("disarm", {"force": True})], sent
        assert not ct._kill_confirm.isActive()
        assert "RƠI" not in ct.note.text(), ct.note.text()

        # Het 3s ma khong bam lai: bam tiep chi la lenh thuong, khong force
        ct.btn_kill.click()
        ct._kill_confirm.timeout.emit()  # = 3 giay da troi qua
        assert ct.btn_kill.text() == "DISARM", ct.btn_kill.text()
        sent.clear()
        ct.btn_kill.click()
        assert sent == [("disarm", {})], f"het gio ma van force: {sent}"
    finally:
        authority.unregister("sik")
        REGISTRY.fields.clear()
        ct.close()
    print("  ok  DISARM: duoi dat bam mot phat la force (ga o dau cung ngat duoc), "
          "tren troi bam lai trong 3s (hau qua hien canh nut)")


def check_remote(app):
    """RemoteAdapter noi WebSocket that toi mot server gia."""
    import json
    import threading as th

    from websockets.sync.server import serve

    from core.adapters.remote import RemoteAdapter

    port = 8791
    got_cmd = []

    def handler(ws):
        # Dong ho Pi chay TRUOC mot gio (ngoai bai bay khong NTP, khong pin RTC).
        ws.send(json.dumps({"src": "COMPANION_TU_XUNG", "topic": "vision",
                            "data": {"target_x": 0.4}, "ts": time.time() + 3600}))
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
    # ...va ts cung khong lay cua no: do tuoi field tinh bang dong ho LAPTOP. Lay
    # dong ho Pi thi rot WiFi ma vi tri cuoi van "tuoi" them mot gio.
    assert abs(vision[0]["ts"] - time.time()) < 10, \
        f"lay ts cua companion: lech {vision[0]['ts'] - time.time():+.0f} s"
    assert vision[0]["data"]["target_x"] == 0.4
    assert got_cmd and got_cmd[0]["action"] == "authority", got_cmd
    print("  ok  RemoteAdapter nhan envelope + gui lenh nguoc lai; src/ts do laptop dong dau")


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

    # Loi tai PHAI noi ra: 21-23/10 app Android CERTIFICATE_VERIFY_FAILED moi tile ma
    # im lang 2 ngay. SSL/HTTP -> len ban do + map.log; mat mang -> chi log; tai lai
    # duoc -> xoa canh bao.
    import ssl
    import urllib.error
    import urllib.request

    class Resp:
        headers = {"Content-Type": "image/png"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"anh png"

    def fake(result):
        def urlopen(*a, **k):
            if isinstance(result, Exception):
                raise result
            return result
        return urlopen

    real_open, real_dir, old_on = urllib.request.urlopen, mw.TILE_DIR, mw.ONLINE_TILES
    mw.TILE_DIR, mw.ONLINE_TILES = Path(tempfile.mkdtemp()), False
    try:
        g = mw.TileFetcher("https://x.invalid/{z}/{x}/{y}.png")
        urllib.request.urlopen = fake(urllib.error.URLError(OSError(7, "No address")))
        assert g._get(21, 0, 0) is False and g.err is None, f"mat mang ma keu len man hinh: {g.err}"
        urllib.request.urlopen = fake(urllib.error.URLError(ssl.SSLCertVerificationError(
            1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")))
        assert g._get(21, 0, 1) is False and "CERTIFICATE_VERIFY_FAILED" in (g.err or ""), g.err
        assert "CERTIFICATE_VERIFY_FAILED" in mw.MAP_LOG.read_text().splitlines()[-1], \
            "loi SSL khong ghi vao map.log"
        m = mw.MapWidget()
        m.fetcher = g
        assert "CERTIFICATE_VERIFY_FAILED" in m.note(), f"loi SSL khong hien tren ban do: {m.note()!r}"
        urllib.request.urlopen = fake(urllib.error.HTTPError("u", 403, "Forbidden", {}, None))
        assert g._get(21, 0, 2) is False and "403" in (g.err or ""), g.err
        urllib.request.urlopen = fake(Resp())
        assert g._get(21, 0, 3) is True and g.err is None, "tai lai duoc ma canh bao van con"
        assert mw.MAP_LOG.read_text().splitlines()[-1].endswith("tai tile OK")
    finally:
        urllib.request.urlopen, mw.TILE_DIR, mw.ONLINE_TILES = real_open, real_dir, old_on

    # Tat han duong online: ban do phai chay y nhu truoc khi co tinh nang nay.
    old = mw.ONLINE_TILES
    mw.ONLINE_TILES = False
    try:
        m = mw.MapWidget()
        m.resize(200, 150)
        m.set_position(10.762, 106.660)
        assert m.fetcher is None, "ONLINE_TILES=False ma van mo thread tai"
        assert not m.grab().isNull(), "offline ma khong ve duoc ban do"

        # Tile giua man hinh (cho drone) tai TRUOC: hang doi LIFO, xin o xa truoc.
        # FIFO thi drone hien ra o bai bay ma thread con tai not khung nhin cu.
        real_dir, mw.TILE_DIR = mw.TILE_DIR, Path(tempfile.mkdtemp())
        try:
            m.resize(800, 600)
            m.zoom, m.center = 18, (10.8716, 106.64745)
            m.fetcher = mw.TileFetcher("https://x.invalid/{z}/{x}/{y}.png")  # khong start
            m._request_viewport()
            cx, cy = mw.deg2num(*m.center, 18)
            first = m.fetcher.q.get_nowait()
            assert first == (18, int(cx), int(cy)), f"tile dau tien khong phai o giua: {first}"
        finally:
            mw.TILE_DIR = real_dir
    finally:
        mw.ONLINE_TILES = old

    # Thread tai chet / treo -> tu mo lai va ghi map.log. 23/10 21:39-21:54 o bai co
    # GPS: Wi-Fi da xac thuc, 0 tile tai ve, 0 dong log, ban do mang mau 15 phut.
    import threading

    real_log, mw.MAP_LOG = mw.MAP_LOG, Path(tempfile.mkdtemp()) / "map.log"
    h = mw.TileFetcher("https://x.invalid/{z}/{x}/{y}.png")
    try:
        def boom(*a):
            raise ValueError("thu loi")
        h._get = boom
        h.start()
        h.want(16, 2, 2)
        t0 = time.time()
        while not mw.MAP_LOG.exists() and time.time() - t0 < 3:
            time.sleep(0.05)
        log = lambda: mw.MAP_LOG.read_text()  # noqa: E731
        assert "loi thread tai tile ValueError: thu loi" in log(), "loi trong thread khong ghi map.log"
        assert h._thread.is_alive(), "mot tile loi ma thread tai chet"
        old_th = h._thread
        h._busy = time.time() - mw.STUCK_S - 1  # tile dang tai da qua han
        h.want(16, 3, 3)
        assert h._thread is not old_th and h._thread.is_alive(), "treo ma khong mo thread moi"
        assert "treo — mo thread moi" in log(), log()
        h._thread = threading.Thread(target=lambda: None)
        h._thread.start()
        h._thread.join()
        h.want(16, 4, 4)
        assert h._thread.is_alive() and "chet — mo thread moi" in log(), log()
    finally:
        h.stop()
        mw.MAP_LOG = real_log
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
        ct.cmd.check_climb(0.0)
        assert "độ cao không đổi" in logs[-1], logs
        # Con leo len that thi im lang
        logs.clear()
        REGISTRY.feed({"src": "sik", "topic": "position", "data": {"alt_rel": 4.0},
                       "ts": time.time()})
        ct.cmd.check_climb(0.0)
        assert not logs, logs

        # --- Chua ARM: noi thang "chua ARM", KHONG gui, KHONG keu do cao ------
        # Do that 19/09 16:06:46: FC TU CHOI (chua ARM), 6 s sau app van hien
        # "FC da nhan nhung do cao khong doi — nghi co node stream setpoint".
        from core import bus
        REGISTRY.feed({"src": "sik", "topic": "position", "data": {"alt_rel": 0.0},
                       "ts": time.time()})
        REGISTRY.feed({"src": "sik", "topic": "heartbeat",
                       "data": {"mode": "GUIDED", "armed": False}, "ts": time.time()})
        sent.clear(); logs.clear()
        assert ct.cmd.takeoff(5.0) is False
        assert not sent, "chua ARM ma van gui takeoff"
        assert "CHƯA ARM" in logs[-1], logs

        # FC tu choi takeoff (vi ly do nao do, ma app khong biet truoc): bo kiem
        # 6 s KHONG duoc noi "FC da nhan".
        REGISTRY.feed({"src": "sik", "topic": "heartbeat",
                       "data": {"mode": "GUIDED", "armed": None}, "ts": time.time()})
        REGISTRY.fields.pop("heartbeat.armed", None)
        sent.clear(); logs.clear()
        assert ct.cmd.takeoff(5.0) is True and sent == ["takeoff"], sent
        n = ct.cmd._climb_seq
        bus.emit_envelope({"src": "sik", "topic": "ack", "ts": time.time(),
                           "data": {"command": 22, "result": 4}})
        ct.cmd.check_climb(0.0, n)  # = 6 s sau
        assert not any("độ cao không đổi" in x for x in logs), f"FC tu choi ma van keu: {logs}"

        # FC chap nhan ma drone nam im: VAN phai keu nhu truoc
        logs.clear()
        ct.cmd.takeoff(5.0)
        n = ct.cmd._climb_seq
        bus.emit_envelope({"src": "sik", "topic": "ack", "ts": time.time(),
                           "data": {"command": 22, "result": 0}})
        ct.cmd.check_climb(0.0, n)
        assert "độ cao không đổi" in logs[-1], logs
        # Timer cua lan takeoff CU khong duoc kiem lan moi
        logs.clear()
        ct.cmd.check_climb(0.0, n - 1)
        assert not logs, logs
        # Takeoff 1 m trong nha leo 0,95 m: dang len that, KHONG duoc keu
        REGISTRY.feed({"src": "sik", "topic": "position", "data": {"alt_rel": 0.95},
                       "ts": time.time()})
        ct.cmd.check_climb(0.0, n, 1.0)
        assert not logs, f"takeoff 1 m len 0,95 m ma van keu: {logs}"
        ct.cmd.check_climb(0.0, n, 5.0)  # 5 m ma moi 0,95 m thi van keu
        assert "độ cao không đổi" in logs[-1], logs
        # DISARM trong 6 s (do that 18/10 15:38): nguoi bay tu dung, khong keu
        logs.clear()
        REGISTRY.feed({"src": "sik", "topic": "position", "data": {"alt_rel": 0.0},
                       "ts": time.time()})
        REGISTRY.feed({"src": "sik", "topic": "heartbeat",
                       "data": {"mode": "GUIDED", "armed": False}, "ts": time.time()})
        ct.cmd.check_climb(0.0, n, 5.0)
        assert not logs, f"da DISARM ma van do loi cho companion: {logs}"
        REGISTRY.fields.pop("heartbeat.armed", None)

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
    """Tab Control chi gui sang ROS2 DUNG hai lenh: bat/huy task trong TASKS.

    Ngoai le co y cua nguyen tac 2.1 (16/10/2026, xem core/authority.py). Moi nut
    khac van khong duoc ra cong `remote`: mot nut sot lai se gui lenh cho mot node
    khong co quyen lai — bam khong co gi xay ra, va khong ai biet vi sao.
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
        from laptop.tabs.control import TASKS
        ok = {("mission", n) for _, n in TASKS} | {("mission", "")}
        stray = [(a, g) for a, g in sent["remote"]
                 if a != "mission" or set(g or {}) != {"name"} or (a, g["name"]) not in ok]
        assert not stray, f"nut gui lenh sang ROS2 ngoai bat/huy task: {stray}"
        assert ("mission", {"name": ""}) in sent["remote"], "phai co nut huy task"

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
    print("  ok  ROS2: chi nut bat/huy task trong TASKS, bridge chot quyen, ten khop danh sach trang")


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

    from laptop.widgets.attitude import AttitudeDial
    from laptop.widgets.map_widget import MapWidget, deg2num, num2deg

    lat, lon, z = 10.762, 106.66, 16
    x, y = deg2num(lat, lon, z)
    back = num2deg(x, y, z)
    assert abs(back[0] - lat) < 1e-9 and abs(back[1] - lon) < 1e-9, back

    # Dong ho tu the ve theo kich thuoc o, ke ca o nho tren dien thoai: la ban cu co
    # dinh 120 px, nhet vao o 50 dp thi chi con mot goc (19/10). Vong la ban + chu N
    # phai nam trong o -> dem diem anh khac nen o ca bon goc trong vung tron.
    a = AttitudeDial()
    a.set_attitude(0.3, -0.15)
    a.set_heading(137.0)
    for side in (50, 140):
        a.resize(side, side)
        img = a.grab().toImage()
        assert not img.isNull()
        bg = img.pixelColor(0, 0)
        for x, y in ((side // 2, 3), (side // 2, side - 4), (3, side // 2), (side - 4, side // 2)):
            assert img.pixelColor(x, y) != bg, f"dong ho {side}px bi cat o ({x},{y})"

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

    # O xung quanh thieu tile o muc tz (chon theo TAM) thi ve mot goc tile cha, khong
    # de o den: 21/10 tam co tile z20, xung quanh chi z17-19 -> phong to la man den.
    import tempfile
    from PySide6.QtGui import QColor, QImage, QPainter
    from laptop.widgets import map_widget as mw
    old_dir, old_on = mw.TILE_DIR, mw.ONLINE_TILES
    mw.TILE_DIR, mw.ONLINE_TILES = Path(tempfile.mkdtemp()), False
    try:
        cha = QImage(256, 256, QImage.Format_RGB32)
        qp = QPainter(cha)
        for (qx, qy), c in {(0, 0): "red", (1, 0): "lime", (0, 1): "blue", (1, 1): "yellow"}.items():
            qp.fillRect(qx * 128, qy * 128, 128, 128, QColor(c))
        qp.end()
        (mw.TILE_DIR / "2" / "1").mkdir(parents=True)
        cha.save(str(mw.TILE_DIR / "2" / "1" / "1.png"))
        con = QImage(256, 256, QImage.Format_RGB32)
        con.fill(QColor("white"))
        (mw.TILE_DIR / "3" / "2").mkdir(parents=True)
        con.save(str(mw.TILE_DIR / "3" / "2" / "2.png"))  # chi co MOT tile z3, o tam
        m2 = mw.MapWidget()
        m2.resize(1024, 1024)
        m2.zoom, m2.center = 3, num2deg(2.5, 2.5, 3)
        img = m2.grab().toImage()
        got = {k: img.pixelColor(512 + dx, 512 + dy).name() for k, (dx, dy) in
               {"tam": (0, 0), "phai": (256, 0), "duoi": (0, 256), "cheo": (256, 256)}.items()}
        assert got == {"tam": "#ffffff", "phai": "#00ff00", "duoi": "#0000ff",
                       "cheo": "#ffff00"}, f"o thieu tile khong lay goc tile cha: {got}"
    finally:
        mw.TILE_DIR, mw.ONLINE_TILES = old_dir, old_on

    tiles = list(TILE_DIR.glob("*/*/*.png"))
    if tiles:
        z, x, y = int(tiles[0].parent.parent.name), int(tiles[0].parent.name), int(tiles[0].stem)
        pix = m._tile(z, x, y)
        assert pix is not None and not pix.isNull(), f"khong doc duoc tile {tiles[0]}"
        note = f"doc duoc tile that ({len(tiles)} tile trong assets/tiles)"
    else:
        note = "map khong co tile van ve luoi"
    print(f"  ok  dong ho tu the/telemetry/map deu ve duoc ({note})")


def check_fence(app):
    """Geofence: tu goi MAVLink toi net ve tren ban do.

    Do that tren SITL (ArduCopter stable): tai ve 4 dinh bang mission_type=FENCE,
    va FENCE_RADIUS/FENCE_ALT_MAX doc bang PARAM_VALUE. Check nay dung dung nhung
    con so do, khong bia.
    """
    from laptop.widgets.map_widget import FENCE_IN, fence_shapes, meters_per_px

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
    ft = flight(600, 400)
    ft.map.zoom = 16

    # Duong that: adapter -> bus -> man bay -> map (khong goi thang set_home/set_fence)
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
    # Kich thuoc lay tu chinh anh chu khong tu con so vua resize: lay nham thi do
    # sai cho, ma rao ve sai cho van "nhin duoc" — kieu hong te nhat.
    img = ft.map.grab().toImage()
    cx, cy = img.width() // 2, img.height() // 2
    assert img.pixel(cx + r_px, cy) == FENCE_IN.rgb(), "vanh rao khong nam o dung ban kinh"

    # FENCE_ENABLE = 0: FC khong chan -> KHONG ve rao (ve ra la bi doc nham thanh
    # "co rao"), va dai chu cung khong nhac toi rao.
    bus.emit("sik", "fence", {"FENCE_ENABLE": 0.0})
    assert ft.map._fence_note() == "", ft.map._fence_note()
    img = ft.map.grab().toImage()
    assert img.pixel(cx + r_px, cy) != FENCE_IN.rgb(), "rao TAT ma van ve vanh rao"

    # Ngat ket noi: rao, home, vet bay cua drone cu phai bien mat
    ft.attach(None, None)
    assert ft.map.fence == {} and ft.map.home is None, ft.map.fence

    # Xin home la mot command_long -> FC tra ack cho lenh 512, khong phai lenh cua
    # nut nao. Ack do ma xoa hang cho thi canh bao "khong co phan hoi" cua ARM bi
    # nuot — hong im lang, dung thu muc 2.2 cam.
    from laptop.tabs.control import ControlTab

    ct = ControlTab()
    ct.set_mode("SIM")
    logs = []
    ct.log.connect(lambda text, _sev: logs.append(text))
    ct.cmd._pending = {"arm": time.time() + 3}
    bus.emit("sik", "ack", {"command": 512, "result": 0})
    assert ct.cmd._pending and not logs, (ct.cmd._pending, logs)
    bus.emit("sik", "ack", {"command": 400, "result": 0})  # ARM: cai nay moi la cua nut
    assert not ct.cmd._pending and "chấp nhận" in logs[-1], logs
    ct.close()
    print("  ok  geofence: vong tron quanh home + da giac, FC TAT rao thi khong ve")


def check_waypoints(app):
    """Duong bay nhieu waypoint: tu goi MAVLink toi net ve tren ban do.

    Day la thu duy nhat cho biet drone bay AUTO SAP di dau — cham xanh tren ban
    do chi noi no dang o dau. Nen check nay do ca ba cho hong duoc: tran 50 muc,
    muc khong co toa do, va viec ai do nap nhiem vu khac giua chung.
    """
    from core.adapters.sik import WP_ITEMS_MAX, WP_MAX
    from laptop.widgets.map_widget import WP_LINE, wp_points

    # `total` thieu (firmware < 4.3) thi phai BIEN MAT khoi trong tai, khong duoc
    # thanh None: ben ve gop tung manh vao mot dict, None se xoa con so that.
    # total cua MISSION_CURRENT khong ke home; tren ban do thi phai cung don vi
    # voi MISSION_COUNT (co ke) vi hai ben ghi chung mot khoa.
    assert normalize("MISSION_CURRENT", {"seq": 3, "total": 8}) == ("wp", {"seq": 3, "total": 9})
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
    # vong tai lai chay hoai, chiem het duong SiK. Va ArduPilot dem `total` KHONG
    # ke home: MISSION_COUNT 80 di cung total 79 (do that: count 6 / total 5 tren
    # logs/20260919-223659-sim.tlog). Ban cu so 80 voi 80 nen bai nay xanh, con
    # SITL that thi tai lai moi 3 s.
    ad._wp_rx(master, "MISSION_CURRENT", {"seq": 3, "total": 79})
    assert ad._wp_done(), "so muc khong doi ma van tai lai"
    # Con doi that (ai do nap nhiem vu khac, ke ca chi them MOT muc) thi phai tai lai.
    ad._wp_rx(master, "MISSION_CURRENT", {"seq": 0, "total": 80})
    assert ad._wp_n is None and ad._wp_items == {}, (ad._wp_n, ad._wp_items)
    # Chua biet FC co bao nhieu muc thi chua co gi de so: dat lai `_asks` o day la
    # vong hoi khong bao gio cham ASK_MAX.
    ad._asks = 5
    ad._wp_rx(master, "MISSION_CURRENT", {"seq": 0, "total": 4})
    assert ad._asks == 5, "chua co MISSION_COUNT ma MISSION_CURRENT da dat lai luot hoi"
    # GCS khac XOA nhiem vu: FC bao total 0 + mission_state 1 (NO_MISSION) — do that
    # tren SITL 4.7-dev va FC that. Firmware cu khong co ca hai (0, 0) -> khong so.
    ad._wp_rx(master, "MISSION_COUNT", {"count": 4, "mission_type": 0})
    ad._wp_rx(master, "MISSION_CURRENT", {"seq": 0, "total": 0, "mission_state": 0})
    assert ad._wp_total == 4, "firmware cu (khong co total) ma van tai lai"
    ad._wp_rx(master, "MISSION_CURRENT", {"seq": 0, "total": 0, "mission_state": 1})
    assert ad._wp_total is None, "GCS khac xoa nhiem vu ma app van giu duong bay cu"
    ad._wp_rx(master, "MISSION_COUNT", {"count": 1, "mission_type": 0})
    ad._wp_rx(master, "MISSION_CURRENT", {"seq": 0, "total": 0, "mission_state": 1})
    assert ad._wp_total == 1, "nhiem vu rong (chi home) ma van tai lai"
    ad._wp_rx(master, "MISSION_COUNT", {"count": 0, "mission_type": 0})  # SITL sau lenh xoa
    ad._wp_rx(master, "MISSION_CURRENT", {"seq": 0, "total": 0, "mission_state": 1})
    assert ad._wp_total == 0, "count 0 sau lenh xoa ma van tai lai moi nua giay"

    # --- duong that: adapter -> bus -> tab -> net ve tren man hinh -----------
    lat, lon = 10.8221589, 106.6868454
    ft = flight(600, 400)
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
    ft.attach(None, None)
    assert ft.map.wp == {}, ft.map.wp
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

    lat, lon = 10.8221589, 106.6868454

    class FakeMav:
        srcSystem = 254  # sysid cua chinh app — MISSION_ACK gui cho ai thi so voi so nay

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

    # Khong dang nap ma FC tra MISSION_ACK ngay sau "bay toi day": do la cau tra
    # loi cua lenh do, phai ra ngoai. Do that 04/10/2026: diem ngoai rao -> type=1,
    # truoc day khong ai doc, giao dien chi co "da gui" va drone dung im.
    got.clear()
    ack = {"type": 1, "mission_type": 0, "target_system": 254}
    ad._goto_at = time.time()
    ad._wp_rx(master, "MISSION_ACK", ack)
    assert got and got[-1]["data"] == {"goto": {"ok": False, "result": 1}}, got
    # ACK cho GCS khac tren cung radio, hay ACK muon cua mot phien nap da bo cuoc
    # (khong co "bay toi day" nao vua gui), thi KHONG phai cau tra loi do.
    got.clear()
    ad._goto_at = time.time()
    ad._wp_rx(master, "MISSION_ACK", dict(ack, target_system=255))
    ad._goto_at = 0.0
    ad._wp_rx(master, "MISSION_ACK", ack)
    assert not got, f"ACK khong phai cua 'bay toi day' ma van bao: {got}"

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

    # Phan giao dien (dat nhap, nap, FC nhan/tu choi, ghi de khi dang AUTO, tran
    # WP_MAX) nam o `check_touch_flight` — do o man bay that chu khong o day nua.

    print(f"  ok  nap duong bay len FC: home + TAKEOFF dau, LAND cuoi, tran {WP_MAX}, "
          f"bo cuoc sau {WP_UP_TRIES} lan va noi ra")


def check_stream_rearm(app):
    """Im lang qua STREAM_REARM thi phai xin lai stream — va chi xin MOT lan.

    Bay do duoc tren radio SiK that (13/08/2026): FC tut xuong 21 B/s chi con
    HEARTBEAT, app xin mot lan la ve 1986 B/s. Truoc do app xin dung mot lan luc
    ket noi nen no nam im vinh vien — HUD dung hinh ma link van bao "co song".

    Cai thu hai quan trong khong kem cai thu nhat: sau khi xin phai dat lai dong
    ho. Khong dat thi dieu kien con dung o MOI vong lap, tuc ban 7 goi moi vong —
    hang nghin goi mot giay vao dung cai duong truyen dang co van de.
    """
    from core.adapters.sik import STREAM_REARM, SikAdapter, stream_table

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

    # im qua nguong -> xin lai DU ca bo, khong thieu luong nao. Doi chieu voi
    # stream_table() chu khong voi mot bang ghim cung: profile nay la SIM qua udp
    # nen no dung bang nhanh, va cai dang kiem o day la "xin lai du bo", khong
    # phai "bang nao".
    want = stream_table(ad.profile)
    ad._stream_rx = now - STREAM_REARM - 0.1
    ad._stream_tick(master, now)
    assert master.mav.asks == [(sid, hz, 1) for sid, hz in want], master.mav.asks

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
          f"{len(want)} luong, khong ban lap")


def check_alt_no_home(app):
    """Chua co home (khong GPS): do cao = z EKF, khong phai baro tho `relative_alt`.

    So that bay 11/10/2026 16:15:32 (logs/20261011-161210-real.tlog), quat quay
    duoi dat: relative_alt -8,95 m, LOCAL_POSITION_NED z = +1,31 m (xuong).
    """
    import struct
    import tempfile

    from pymavlink.dialects.v20 import ardupilotmega as mavlink

    path = Path(tempfile.gettempdir()) / "selfcheck-alt.tlog"
    mav = mavlink.MAVLink(None, srcSystem=1)
    t0 = time.time()
    msgs = (
        mav.global_position_int_encode(0, 0, 0, 0, -8950, 0, 0, 0, 0),  # chua co z EKF
        mav.local_position_ned_encode(0, 0.0, 0.0, 1.31, 0, 0, 0),
        mav.global_position_int_encode(0, 0, 0, 0, -8950, 0, 0, 0, 0),
        mav.home_position_encode(107620000, 1066600000, 5000, 0, 0, 0,
                                 [1, 0, 0, 0], 0, 0, 0),
        mav.global_position_int_encode(0, 0, 0, 0, 2000, 0, 0, 0, 0),
    )
    with open(path, "wb") as f:
        for i, m in enumerate(msgs):
            m.pack(mav)
            f.write(struct.pack(">Q", int((t0 + i * 0.05) * 1e6)) + m.get_msgbuf())

    seen = []
    adapter = SikAdapter({"name": "selfcheck", "mode": "REPLAY", "path": str(path)})
    adapter.envelope.connect(lambda e: seen.append(e))
    adapter.finished.connect(app.quit)
    adapter.start()
    guard = deadline(app, 5000)
    app.exec()
    guard.stop()
    adapter.stop()

    alt = [e["data"]["alt_rel"] for e in seen
           if e["topic"] == "position" and "alt_rel" in e["data"]]
    # z la float32 trong MAVLink: -1.31 ve thanh -1.30999994
    assert alt[0] is None and abs(alt[1] + 1.31) < 1e-6 and alt[2] == 2.0, \
        f"do cao chua co home / co home: {alt}"
    print("  ok  chua co home: do cao = z EKF (-1.31), khong phai baro (-8.95); co home: relative_alt")


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
        # .tlog bay that chua ca hoi thoai tai duong bay. Do 16/09: phat lai toi
        # MISSION_COUNT la adapter "tra loi" vao file chi doc -> chet sau 166 goi.
        m = mav.mission_count_encode(255, 190, 1, 0)
        m.pack(mav)
        f.write(struct.pack(">Q", int((t0 + 0.5) * 1e6)) + m.get_msgbuf())

    seen, fails = [], []
    adapter = SikAdapter({"name": "selfcheck", "mode": "REPLAY", "path": str(path)})
    adapter.envelope.connect(lambda e: seen.append(e))
    adapter.failed.connect(fails.append)
    started = time.time()
    adapter.finished.connect(app.quit)
    adapter.start()
    guard = deadline(app, 5000)  # chan treo
    app.exec()
    guard.stop()
    took = time.time() - started
    adapter.stop()

    assert not fails, f"REPLAY chet giua chung: {fails}"
    assert took < 4, f"REPLAY khong ket thuc o EOF ({took:.1f}s)"
    assert sum(1 for e in seen if e["topic"] == "attitude") == 5, seen
    assert any(e["topic"] == "link" and e["data"].get("eof") for e in seen), "khong bao EOF"
    assert adapter.tlog is None, "REPLAY khong duoc ghi de len log"
    print(f"  ok  REPLAY dung o EOF sau {took:.1f}s")


def check_slow_stop(app):
    """stop() qua han ma thread chua thoat -> giu song, KHONG abort ca tien trinh.

    Bay do duoc 15/09/2026: .tlog moi nhat trong logs/ nang 168 MB, rieng khau mo
    mat 4,26 s; stop() doi 3 s roi tha, thread tu huy trong chinh no -> exit 134
    giua check_tlog_roundtrip. Dung tren app that: ngat REPLAY file lon vai giay
    dau la sap.
    """
    import weakref

    from PySide6.QtCore import QThread

    from core.adapters import join

    class Slow(QThread):
        def run(self):
            time.sleep(0.5)

    t = Slow()
    t.start()
    assert join(t, 100) is False, "thread ngu 0.5s ma doi 0.1s da xong?"
    ref = weakref.ref(t)
    del t  # nhu disconnect(): setattr(self, "adapter", None)
    guard = deadline(app, 1000)
    app.exec()  # song sot toi day la khong abort
    guard.stop()
    app.processEvents()
    assert ref() is None, "thread cham da xong ma khong duoc giai phong (ro)"
    print("  ok  stop() qua han: thread duoc giu toi luc xong roi moi giai phong")


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


def check_jetson_dot(app):
    """Cham "Jetson" man dien thoai: xanh khi co BAT KY thu gi tu Jetson.

    Do 23/10: Jetson khong chay ros2_bridge (8765) ma video van 29 fps — cham chi
    tinh WebSocket nen xam mai.
    """
    from core.adapters.sik import STALE

    b = flight()
    b.profile = dict(b.profile, remote="ws://jetson.invalid:8765")
    assert b._links()[3] == "none", "chua co gi tu Jetson ma cham khong xam"
    b.video_src.alive = True
    assert b._links()[3] == "ok", "video ve ma cham Jetson khong xanh"
    b.video_src.alive = False
    b.last_seen["remote"] -= STALE + 1
    assert b._links()[3] == "crit", "mat het tin Jetson ma cham van xanh"
    b.video_src.persons = 0  # /status tra loi "0 nguoi" van la Jetson dang tra loi
    assert b._links()[3] == "ok", "/status tra loi ma cham Jetson khong xanh"
    print("  ok  cham Jetson: video hoac /status ve la xanh, im qua STALE la do")


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


def check_copy_tiles(app):
    """Android: tile chep tu assets:/tiles ra bo nho trong (main.py). O day nguon la
    thu muc thuong — QDirIterator doc ca hai nhu nhau."""
    import tempfile
    from main import copy_tiles

    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "src", Path(d) / "dst"
        for z, x, y in [(3, 1, 2), (3, 1, 3), (17, 5, 9)]:
            (src / str(z) / str(x)).mkdir(parents=True, exist_ok=True)
            (src / str(z) / str(x) / f"{y}.png").write_bytes(b"tile%d" % y)
        (src / "SOURCE.txt").write_text("Google\n")
        (dst / "3" / "1").mkdir(parents=True)
        (dst / "3" / "1" / "2.png").write_bytes(b"da tai")  # tile tai qua mang truoc do
        ticks = []
        assert copy_tiles(str(src), dst, lambda: ticks.append(1)) == 4
        assert (dst / "17" / "5" / "9.png").read_bytes() == b"tile9"
        assert (dst / "SOURCE.txt").exists(), "thieu SOURCE.txt -> tai bu tu Esri thay Google"
        assert (dst / "3" / "1" / "2.png").read_bytes() == b"da tai", "chep de len tile da co"
        assert ticks, "chep xong khong bao ban do quet lai"
        assert copy_tiles(str(src), dst) == 0, "lan mo sau van chep lai"
        # APK khong kem ban do: khong co gi de chep -> KHONG danh dau, cai ban day du sau van chep.
        empty, dst2 = Path(d) / "empty", Path(d) / "dst2"
        empty.mkdir()
        dst2.mkdir()
        assert copy_tiles(str(empty), dst2) == 0 and not (dst2 / ".copied").exists(), \
            "APK khong ban do da danh dau .copied"

        # Chung chi CA cua Android: PEM kem dong chu `openssl x509 -text` truoc/sau.
        from main import ca_bundle
        pem = "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----"
        cas = Path(d) / "cacerts"
        cas.mkdir()
        (cas / "00673b5b.0").write_text(f"{pem}\nCertificate:\n    Data: ...\n")
        (cas / "0a775a30.0").write_text(f"Certificate:\n...\n{pem}\nSHA1 Fingerprint=AB\n")
        out = Path(d) / "cacert.pem"
        assert ca_bundle(cas, out) == 2
        assert out.read_text() == f"{pem}\n{pem}\n", out.read_text()
        assert ca_bundle(Path(d) / "khong-co", out) == 0  # may la: khong goi trust()

        # Va HTTPS phai DUNG file do qua context, khong qua SSL_CERT_FILE: app Android
        # co AT_SECURE=1, OpenSSL bo qua bien moi truong (21-23/10 khong tai duoc tile).
        # Nap them CA he thong thi so CA trong context se lon hon 3 nhieu.
        import ssl
        from main import trust
        sys_ca = sorted(Path("/etc/ssl/certs").glob("*.pem"))[:3]
        if len(sys_ca) == 3:
            three = Path(d) / "three"
            three.mkdir()
            for f in sys_ca:
                (three / f.name).write_text(f.read_text())
            assert ca_bundle(three, out) == 3
            old = ssl._create_default_https_context
            try:
                trust(out)
                n = ssl._create_default_https_context().cert_store_stats()["x509_ca"]
                assert n == 3, f"context HTTPS mac dinh co {n} CA, phai dung 3 CA cua file"
            finally:
                ssl._create_default_https_context = old

    # Log chuyen bay tren dien thoai nam NGOAI files/app: p4a xoa sach no moi lan cai lai.
    from laptop.connection import ROOT, logs_dir
    assert logs_dir(False) == ROOT / "logs", "laptop doi cho ghi log"
    assert not logs_dir(True).is_relative_to(ROOT), "log dien thoai nam trong thu muc bi xoa khi cai lai"


def check_dual_link(app):
    """Profile hai duong (dien thoai: SiK OTG + mang): SiK im thi tu sang mang.

    SikAdapter that, hai nguon UDP gia cung la "FC" — lat 1 qua duong SiK, lat 2 qua
    duong mang, de biet goi nao di duong nao. 1,5 s dau ca hai noi; sau do SiK chi
    con heartbeat cua MAVROS (1/191) — no van den khi drone ra ngoai tam, khong
    duoc tinh la FC con song.
    """
    from PySide6.QtCore import QTimer
    from pymavlink import mavutil
    from core.adapters.sik import STALE, STREAMS, stream_table
    from laptop import connection

    sik_port, net_port = PORT + 20, PORT + 21
    lats, texts, paths = [], [], []
    lat_t, sik_end = [], []  # (luc toi, lat); luc FC ngung noi tren SiK
    adapter = SikAdapter({"name": "dual", "mode": "REAL", "bridge": True,
                          "conn": f"udpin:127.0.0.1:{sik_port}",
                          "conn2": f"udpin:127.0.0.1:{net_port}"})
    adapter.envelope.connect(lambda e: lats.append(e["data"]["lat"])
                             if e["topic"] == "position" else None)
    adapter.envelope.connect(lambda e: lat_t.append((time.time(), e["data"]["lat"]))
                             if e["topic"] == "position" else None)
    adapter.envelope.connect(lambda e: texts.append(e["data"]["text"])
                             if e["topic"] == "text" else None)
    adapter.envelope.connect(lambda e: paths.append(e["data"].get("path"))
                             if e["topic"] == "link" else None)
    adapter.start()
    stop = threading.Event()

    def sender():
        time.sleep(0.4)  # cho adapter bind cong
        fc = {port: mavutil.mavlink_connection(f"udpout:127.0.0.1:{port}", source_system=1,
                                               source_component=1)
              for port in (sik_port, net_port)}
        mavros = mavutil.mavlink_connection(f"udpout:127.0.0.1:{sik_port}", source_system=1,
                                            source_component=191)
        t0 = time.time()
        while not stop.is_set():
            ports = (sik_port, net_port) if time.time() - t0 < 1.5 else (net_port,)
            if len(ports) == 1 and not sik_end:
                sik_end.append(time.time())
            for port in ports:
                fc[port].mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                            mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA, 0, 0, 0)
                fc[port].mav.global_position_int_send(0, 10000000 * (1 + (port == net_port)),
                                                      0, 0, 0, 0, 0, 0, 0)
            mavros.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                                      mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
            time.sleep(0.1)

    threading.Thread(target=sender, daemon=True).start()
    QTimer.singleShot(6000, app.quit)
    app.exec()
    stop.set()
    adapter.stop()

    assert lats and lats[0] == 1.0, f"luc dau phai di duong SiK: {lats[:5]}"
    k = lats.index(2.0) if 2.0 in lats else None
    assert k is not None, f"SiK im ma khong sang duong mang: {sorted(set(lats))}"
    assert set(lats[k:]) == {2.0}, "tron goi hai duong sau khi doi"
    assert any("mang" in t for t in texts), f"doi duong ma khong bao: {texts}"
    assert paths and paths[-1] == "mang", paths
    # Doi xong TRUOC khi man hinh coi la mat link (STALE): khong thi moi lan rut
    # radio, loa doc "Mat tin hieu" roi 4G moi nhan (do 24/10: 4/5 lan).
    gap = next(ts for ts, la in lat_t if la == 2.0 and ts > sik_end[0]) - sik_end[0]
    assert gap < STALE - 0.5, f"doi sang mang sau {gap:.2f} s, sat nguong mat link {STALE} s"

    # SiK CHUA TUNG nghe FC (chua cam radio) thi khong duoc sang mang, du mang song.
    from core.adapters.sik import DualLink

    class Quiet:
        def recv_match(self, blocking=False):
            return None

    d = DualLink([Quiet(), Quiet()], stale=0.0)
    d.t0 = 0.0
    d.rx = [0.0, time.time()]
    d._pick()
    assert d.path == "SiK", "chua noi duoc SiK ma da cho bay qua LTE"
    d.rx = [time.time() - 5, time.time()]
    d._pick()
    assert d.path == "mang", "SiK da tung noi roi im ma khong sang mang"

    # Dien thoai thay DUNG mot profile ket noi, va no la profile hai duong.
    saved = connection.ANDROID
    try:
        connection.ANDROID = True
        # Khuon "SiK radio" khong co conn -> khong hien (chi cho muon baud/remote).
        conns = [p for p in connection.load_profiles() if p.get("conn")]
    finally:
        connection.ANDROID = saved
    assert len(conns) == 1 and conns[0].get("conn2"), [p["name"] for p in conns]
    assert stream_table(conns[0]) is STREAMS, "profile dien thoai xin stream nhanh qua radio"


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
    # TEN MAY, khong chi IP: connections.yaml tro toi ten may (Pi cu dung .local,
    # Jetson gio dung ten Tailscale) vi IP DHCP da doi that mot lan (.40 -> .105), hom do GUI khong
    # thay camera trong khi stream van chay tot. `urlparse().hostname` ha chu hoa,
    # nen ten viet hoa cung phai ra dung dia chi.
    assert url_for("ws://hoaibac-desktop.local:8765") \
        == "http://hoaibac-desktop.local:8080/stream"
    assert url_for("ws://Pi-Camera.local:8765") == "http://pi-camera.local:8080/stream"
    assert url_for("") is None
    # SITL: nua ROS2 tren laptop, camera tren Pi -> key `video` thang `remote`
    from laptop.widgets.video import video_url
    assert video_url({"remote": "ws://127.0.0.1:8765",
                      "video": "http://hoaibac-desktop.local:8080/stream"}) \
        == "http://hoaibac-desktop.local:8080/stream"
    assert video_url({"remote": "ws://hoaibac-desktop.local:8765"}) \
        == "http://hoaibac-desktop.local:8080/stream", "khong co `video` thi van suy tu remote"
    assert video_url({"video": "http://pi.local:8080/stream"}) == "http://pi.local:8080/stream", \
        "co video ma khong co remote cung phai chay"
    assert video_url({"conn": "tcp:127.0.0.1:5763"}) is None
    import yaml
    from laptop.connection import ROOT as _root
    # Chi ap cho profile SITL xem camera JETSON. Profile xem camera CUA SIM
    # (fire_drone_ws, MJPEG http) co y nghe nguon khac, nen khong tinh.
    sitl = [p for p in yaml.safe_load((_root / "config" / "connections.yaml").read_text())
            if p.get("mode") == "SIM" and not str(p.get("video", "")).startswith("http")]
    # Jetson DAY H.264 thang ve laptop (11/10/2026): profile SITL phai nghe dung cong
    # cua profile bay that — doi cong ben Jetson ma quen sua SITL thi bai nay keu.
    real = next(p for p in yaml.safe_load((_root / "config" / "connections.yaml").read_text())
                if p["name"] == "SiK radio")
    # Không còn profile SITL nào nghe video Jetson (18/10/2026 bỏ profile simtofly) thì
    # không có gì để so - rỗng là đạt, chứ không phải lỗi.
    assert all(video_url(p) == video_url(real) for p in sitl), \
        f"profile SITL nghe video khac profile bay that: {[video_url(p) for p in sitl]}"

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

    # Anh thu hai, khac mau: dung de chung minh dung hinh xong thi TU HOI LAI.
    pm2 = QPixmap(32, 24)
    pm2.fill(QColor("#27ae60"))
    buf2 = QBuffer()
    buf2.open(QBuffer.WriteOnly)
    pm2.save(buf2, "JPEG")
    jpeg2 = bytes(buf2.data())

    class FrozenHandler(BaseHTTPRequestHandler):
        """Camera treo: duong truyen khoe, fps dep, ma van MOT canh quay do.

        Khong phai gia dinh — `mjpeg_server.py` nen lai khung driver vua tra ve,
        nen cam bien treo la ra day nguyen si mot chuoi byte y het nhau.
        """

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            t0 = time.monotonic()
            try:
                while True:
                    # Sau `swap_after` giay thi camera song lai -> anh khac di.
                    img = jpeg if time.monotonic() - t0 < self.server.swap_after else jpeg2
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n"
                        % len(img)
                    )
                    self.wfile.write(img + b"\r\n")
                    time.sleep(0.03)  # ~30 fps: nhip dep, chi co noi dung la chet
            except OSError:
                pass  # GUI dong ket noi truoc — binh thuong, khong phai loi bai kiem

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

    # Log nhip ra file tam, khong lan vao logs/video.log cua phien bay that.
    import tempfile
    import laptop.widgets.video as video_mod
    log_path = Path(tempfile.mkdtemp()) / "video.log"
    video_mod.LOG_PATH, video_mod.REPORT_S = log_path, 0.2

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
    srv.server_close()

    # --- camera dung hinh: khung van ve deu ma anh khong doi ------------------
    #
    # Kieu hong nay KHONG lam cho `alive` tat: fps van 30, byte van chay, o video
    # van sang — chi co dieu canh quay da chet tu bao gio. Doi voi nguoi lai thi
    # no y het "dong bang khung cuoi", tuc la kieu nguy hiem nhat ma ca file
    # video.py viet ra de chan.
    video_mod.FROZEN_S = 0.6  # 2 s that qua lau cho mot bai kiem
    flips = []
    src.frozen_changed.connect(flips.append)
    srv2 = ThreadingHTTPServer(("127.0.0.1", VIDEO_PORT), FrozenHandler)
    srv2.swap_after = 1.6  # sau ngan nay camera song lai
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    src.start(f"http://127.0.0.1:{VIDEO_PORT}/stream")

    wait(src.updated, lambda: src.pixmap is not None, 6000)
    assert src.alive and not src.frozen, "moi nhan khung dau da bao dung hinh"
    wait(src.updated, lambda: src.frozen, 6000)
    assert src.frozen, "anh y het nhau suot ma khong bao dung hinh"
    assert src.pixmap is None, "dung hinh ma van ve canh cu — dung cai bay phai chan"
    assert src.note[0] == "vid.frozen", src.note
    assert src.fps > 5, f"dung hinh khong duoc lam nhip khung tut: {src.fps:.1f}"
    # Tin hieu len man bay: chi ban MOT lan cho ca chuoi khung trung, khong phai
    # moi khung mot lan (30 fps x mot dong noi = man hinh trang xoa).
    assert flips == [True], f"tin hieu dung hinh ban sai so lan: {flips}"
    # Chu tren o video phai la mau canh bao chu khong phai xam nhu "chua ket noi":
    # dem pixel gan mau WARN trong anh vua ve.
    from laptop import theme as _th
    warn = QColor(_th.WARN)
    img = view.grab().toImage()
    lit = sum(1 for x in range(img.width()) for y in range(img.height())
              if all(abs(a - b) < 40 for a, b in
                     zip(img.pixelColor(x, y).getRgb()[:3], warn.getRgb()[:3])))
    assert lit > 20, f"chu 'dung hinh' khong ve bang mau canh bao: {lit} pixel"
    c = view.grab().toImage().pixelColor(5, 5)
    assert all(abs(a - b) < 12 for a, b in zip(c.getRgb()[:3], bg.getRgb()[:3])), \
        f"dung hinh ma man hinh khong ve o nen: {c.getRgb()}"

    # ...va camera song lai thi TU hien anh tro lai, khong phai noi lai tay.
    wait(src.updated, lambda: not src.frozen, 6000)
    assert not src.frozen and src.alive and src.pixmap is not None, \
        f"camera chay lai ma van ket o o xam: frozen={src.frozen} alive={src.alive}"
    c = view.grab().toImage().pixelColor(5, 5)
    assert c.green() > 120 and c.red() < 90, f"khung moi khong len man: {c.getRgb()}"

    assert flips == [True, False], f"camera chay lai ma tin hieu khong ban: {flips}"
    src.stop()
    # May chu van phat ~30 fps: luong doc dang nam trong read() luc stop(), doc xong
    # van emit, khung toi SAU qua hang doi tin hieu. Khong loc theo `gen` thi khung
    # cuoi hien lai toi STALE_S (do 04/10/2026: 10/10 lan).
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.3:
        app.processEvents()
        assert src.pixmap is None and not src.alive, "da stop() ma khung cu hien lai"
        time.sleep(0.005)
    srv2.shutdown()
    srv2.server_close()
    assert "gui frozen" in log_path.read_text(), "dung hinh ma khong de lai vet o log"

    # Du ca vong doi tren log: tools/video_timeline.sh ghep dung cac chu nay.
    log = log_path.read_text()
    for word in ("gui start", "gui connected", "gui fps", "gui lost", "gui stop"):
        assert word in log, f"log video thieu '{word}':\n{log}"

    # --- so nguoi: GET /status moi 0,5 s, lay `total`; loi thi "--" ngay ----
    class StatusHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # dung dang tra loi cua Jetson do 11/10
            body = b'{"counts": {"person": 3}, "total": 3, "ms": null, "t": 1.0}'
            self.send_response(200 if self.path == "/status" else 404)
            self.end_headers()
            self.wfile.write(body if self.path == "/status" else b"")

        def log_message(self, *a):
            pass

    srv3 = ThreadingHTTPServer(("127.0.0.1", VIDEO_PORT), StatusHandler)
    threading.Thread(target=srv3.serve_forever, daemon=True).start()
    def until(pred, s):
        t0 = time.monotonic()
        while not pred() and time.monotonic() - t0 < s:
            app.processEvents()
            time.sleep(0.02)
        return time.monotonic() - t0

    src.start(f"http://127.0.0.1:{VIDEO_PORT}/stream", f"http://127.0.0.1:{VIDEO_PORT}/status")
    until(lambda: src.persons is not None, 5)
    assert src.persons == 3, f"khong doc duoc `total` tu /status: {src.persons}"
    # Server chet -> "--" ngay o lan hoi sau, KHONG giu so cu.
    srv3.shutdown()
    srv3.server_close()
    dt = until(lambda: src.persons is None, 5)
    assert src.persons is None, "/status loi ma van giu so nguoi cu"
    assert dt < 1.5, f"/status loi {dt:.1f} s moi xoa so nguoi (phai <= 0,5 s + timeout 1 s)"
    src.stop()

    # Huy DUT DIEM ngay tai day, tren main thread. VideoSource so huu mot QTimer
    # chay suot (`_watch`); tha cho no roi khoi tam vuc thi Python thu gom luc
    # nao khong biet — va neu luc do la mot thread khac thi Qt keu "Timers cannot
    # be stopped from another thread" roi GIET ca tien trinh.
    #
    # Truoc day khong lo vi khong phep thu nao phia sau cho event loop chay lau.
    # check_bin_log() phat lai mot .bin trong ~2 giay thi lo ra ngay: bo kiem tra
    # dumped core o exit 139, khong kem mot dong Python nao.
    view.close()
    view.deleteLater()
    src.deleteLater()
    app.processEvents()
    print("  ok  video MJPEG — giai ma khung that, mat tin hieu thi xoa khung cu; camera dung hinh "
          "(khung ve deu ma anh trung tung byte) cung xoa, chu doi sang mau canh bao, tin hieu ban "
          "mot lan moi luot, camera chay lai thi tu hien tro lai; so nguoi doc tu /status")


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
    lang khong co mo ta. Dung sinh lai dung cai khuon do roi doi chieu tung cai.

    Danh sach ten KHONG con lay tu tab Trang thai: tu 23/08/2026 tab keo thang
    bang tham so tu FC, nen khong con danh sach ten nao trong code de doi chieu.
    """
    from core import i18n, param_doc
    from laptop.tabs.status import StatusTab

    ghep = [f"ATC_RAT_{ax}_{g}" for ax in param_doc.AXIS for g in param_doc.GAIN]
    ghep += [f"ATC_ANG_{ax}_P" for ax in param_doc.AXIS]
    ghep += [f"PSC_{grp}_{g}" for grp in param_doc.PSC_GROUP for g in ("P", "I", "D")]
    ten = ghep + list(param_doc.EXPLICIT)
    was0 = i18n.lang()
    try:
        for lang in ("vi", "en"):
            i18n.set_lang(lang)
            thieu = [p for p in ten if not param_doc.doc(p)]
            assert not thieu, f"tham so khong co giai thich ({lang}): {thieu}"
    finally:
        i18n.set_lang(was0)
    n_doc = len(set(ten))
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
        # Cot Giai thich (cot 3): cung chu voi tooltip.
        assert st.model.item(row["PARAM.ATC_RAT_RLL_P"], 2).text() == tip
        # Hang telemetry: mo ta tu dinh nghia MAVLink, tieng Viet khi chon tieng Viet.
        roll = st.model.item(row["ATTITUDE.roll"], 2).text()
        assert "Góc roll" in roll and roll.endswith("[rad]"), roll
        # Tham so khong co dong viet tay: ban dich tieng Viet cua mo ta ArduPilot,
        # kem don vi; kieu liet ke thi tooltip co ca cac gia tri — cung tieng Viet.
        bus.emit("sik", "status", {"PARAM.BATT_CAPACITY": 5200.0, "PARAM.FS_THR_ENABLE": 1.0,
                                   "SENSOR.gps": "ok", "FOO.bar": 1})
        st._flush()
        row = {st.model.item(r, 0).text(): r for r in range(st.model.rowCount())}
        cap = st.model.item(row["PARAM.BATT_CAPACITY"], 2).text()
        assert "Dung lượng pin" in cap and cap.endswith("[mAh]"), cap
        fs = st.model.item(row["PARAM.FS_THR_ENABLE"], 0).toolTip()
        assert "1: Bật — luôn RTL" in fs and "Các giá trị" in fs, fs
        assert "GPS" in st.model.item(row["SENSOR.gps"], 2).text()
        assert st.model.item(row["FOO.bar"], 2).text() == "", "bia mo ta cho truong la"
        n_meta, n_vi = len(param_doc._meta()), len(param_doc._load(param_doc.META_VI))
        assert n_meta > 1000 and n_vi > 800, (n_meta, n_vi)

        # Doi ngon ngu: hang DA NAM trong bang phai doi tooltip theo, khong chi
        # hang moi them sau do.
        i18n.set_lang("en")
        tip_en = st.model.item(row["PARAM.ATC_RAT_RLL_P"], 0).toolTip()
        assert "roll axis" in tip_en and "P gain" in tip_en, tip_en
        # Doi sang English: moi cot Giai thich dang nam trong bang doi theo, khong
        # con chu Viet nao lan vao (nguoi dung bao 19/09: hai thu tieng tron nhau).
        assert "Battery capacity" in st.model.item(row["PARAM.BATT_CAPACITY"], 2).text()
        assert "Roll angle" in st.model.item(row["ATTITUDE.roll"], 2).text()
        assert "1: Enabled always RTL" in st.model.item(row["PARAM.FS_THR_ENABLE"], 0).toolTip()
    finally:
        i18n.set_lang(was)
    print(f"  ok  giai thich: {n_doc} tham so viet tay + {n_vi} dich tieng Viet + {n_meta} "
          "metadata ArduPilot, truong telemetry tu MAVLink; cot Giai thich + tooltip, doi theo ngon ngu")


def check_flight_alerts(app):
    """Loi FC noi len man hinh bay kieu DJI — ma khong nhay theo nhip PreArm.

    So do thiet ke: log that 84 phut chi co 2 cau PreArm, moi cau 164 lan, cach
    nhau ~30,7 s. Cau trung trong luc dong con song thi gop, khong chong dong.

    Do o `AlertBook` — ban logic ma man bay cam ung dung — chu khong o lop QLabel
    cu: xep hang, gop va tu tat nam o day, con QML chi ve ra.
    """
    from laptop.widgets.alerts import ROWS, TTL_ERR, TTL_WARN

    ft = flight()
    a = ft.alerts

    def shown(now=None):
        return [text for text, _sev in a.shown(now)]

    bus.emit("sik", "text", {"severity": 6, "text": "EKF3 IMU0 is using GPS"})
    assert shown() == [], "INFO khong duoc len man bay"

    for _ in range(3):  # nhip lap cua FC: cung mot cau, mot dong, co dem
        bus.emit("sik", "text", {"severity": 2, "text": b"PreArm: RC not found\x00"})
    assert shown() == ["PreArm: RC not found  ×3"], shown()

    # WARNING den SAU van nam DUOI loi nang hon, va phai doc ra la muc nhe hon
    bus.emit("sik", "text", {"severity": 4, "text": "GPS glitch"})
    assert shown() == ["PreArm: RC not found  ×3", "GPS glitch"], shown()
    ft.refresh()
    rows = ft.state["alerts"]
    assert [r["crit"] for r in rows] == [True, False], rows

    # Qua so dong: khong cat im lang
    for i in range(3):
        a.push(f"loi {i}", 3)
    assert len(shown()) == ROWS and shown()[-1].endswith(f"(+{5 - ROWS})"), shown()

    # Tu tat: WARNING truoc, loi sau
    now = time.time()
    assert "GPS glitch" not in " ".join(shown(now + TTL_WARN + 0.1)), shown()
    assert any("PreArm" in s for s in shown(now + TTL_WARN + 0.1)), \
        "loi tat cung luc voi WARNING"
    assert shown(now + TTL_ERR + 0.1) == [], shown(now + TTL_ERR + 0.1)

    a.push("PreArm: RC not found", 2)
    ft.attach(None, None)
    assert shown() == [], "ngat ket noi ma loi drone cu con treo"

    # FC doi so do moi lan nhac (bay that 11/10/2026, 6 lan bam ARM): MOT dong
    # mang so moi nhat. So hieu 1 chu so (Compass 1 / 2) van la hai loi khac nhau.
    for n in (172, 169, 169, 169, 168, 176):
        a.push(f"Arm: Check mag field:  {n}, max 875, min 185", 2)
    a.push("PreArm: Compass 1 not calibrated", 2)
    a.push("PreArm: Compass 2 not calibrated", 2)
    got = shown()
    assert "Arm: Check mag field:  176, max 875, min 185  ×6" in got, got
    assert len(got) == 3 and a.red() == {"Arm: Check mag field:  176, max 875, min 185",
                                         "PreArm: Compass 1 not calibrated",
                                         "PreArm: Compass 2 not calibrated"}, (got, a.red())
    a.clear()
    print(f"  ok  loi FC noi tren man bay: >=WARNING, gop dong trung, nang len tren, "
          f"tu tat sau {TTL_WARN:g}/{TTL_ERR:g}s, ngat ket noi la xoa")


def check_touch(app):
    """Tab "Bay cam ung" (laptop/touch/): moi lenh phai TRUOT HET moi di.

    Keo that bang chuot tren tab QML cua cua so chinh (offscreen), khong goi
    thang ham: cai can chung minh la "tha giua chung thi KHONG co lenh", va dieu
    do nam o QML. Cat dong co cung chi can truot het, khong giu them.
    """
    from PySide6.QtCore import QEventLoop, QPoint, QPointF, Qt, QTimer
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest

    from core import authority, bus
    from core.field import REGISTRY
    from laptop.app import MainWindow

    sent = []

    class FakeAdapter:
        def send(self, action, args=None):
            sent.append((action, dict(args or {})))
            return {"ok": action}

    def wait(ms):
        loop = QEventLoop()  # KHONG app.exec(): moi lan no thoat la aboutToQuit
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    win = MainWindow([])
    win.resize(1280, 760)
    win.show()
    tabs = win.ui.tabWidget
    assert tabs.currentWidget() is win.ui.Flight, "app khong mo o man bay"
    # Hai bo Commands = moi ACK ghi hai dong vao tab Thong bao.
    assert win.touch.cmd is win.control_tab.cmd, "man cam ung co bo Commands rieng"

    fake = FakeAdapter()
    authority.register("sik", fake)
    win.touch.attach({"name": "selfcheck", "mode": "SIM"}, fake)
    REGISTRY.feed({"src": "sik", "topic": "heartbeat",
                   "data": {"mode": "GUIDED", "landed": True}, "ts": time.time()})
    wait(100)
    view = win.touch_view
    root = view.rootObject()
    slider = root.findChild(QQuickItem, "slider")

    def drag(frac, hold_ms=0):
        """Keo num tu dau thanh toi `frac` chieu dai, giu `hold_ms`, roi tha."""
        h = slider.height()
        start = slider.mapToScene(QPointF(h / 2, h / 2)).toPoint()
        end = slider.mapToScene(QPointF(h / 2 + frac * (slider.width() - h), h / 2)).toPoint()
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, start)
        for i in range(1, 11):
            QTest.mouseMove(view, start + (end - start) * i / 10)
            wait(10)
        wait(hold_ms)
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, end)
        wait(250)  # num troi ve (180 ms)

    def ask(action):
        root.setProperty("pending", action)
        wait(50)

    try:
        ask("rtl")
        drag(0.6)
        assert sent == [], f"tha o 60% ma lenh da di: {sent}"
        assert root.property("pending") == "rtl", "tha giua chung ma bang xac nhan dong mat"

        drag(1.0)
        assert sent == [("rtl", {})], sent
        assert root.property("pending") == "", "truot xong ma bang van mo"

        sent.clear()
        root.setProperty("takeoffAlt", 10)
        ask("takeoff")
        drag(1.0)
        assert sent == [("takeoff", {"alt": 10.0})], sent

        # Go tay do cao cat canh vao o nhap (khong phai chip): 47 m xuong FC.
        sent.clear()
        ask("takeoff")
        box = root.findChild(QQuickItem, "takeoffAltBox")
        assert box is not None and box.isVisible(), "khong co o nhap do cao cat canh"
        box.forceActiveFocus()
        QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClicks(view, "47")
        QTest.keyClick(view, Qt.Key_Return)
        wait(50)
        assert root.property("takeoffAlt") == 47, root.property("takeoffAlt")
        drag(1.0)
        assert sent == [("takeoff", {"alt": 47.0})], sent
        # Go so ngoai tam: QML kep, va backend kep lan nua neu QML co lot
        sent.clear()
        win.touch.act("takeoff", "500")
        assert sent == [("takeoff", {"alt": 120.0})], f"do cao 500 m lot xuong FC: {sent}"
        root.setProperty("takeoffAlt", 5)

        # Cat dong co: truot nua chung -> khong co gi; truot het -> force ngay.
        sent.clear()
        ask("kill")
        drag(0.5)
        assert sent == [], f"cat dong co khi moi truot nua: {sent}"
        drag(1.0)
        assert sent == [("disarm", {"force": True})], sent

        # SiK dut (MainWindow._stop_sik): bang dang cho bi huy, act() tu choi.
        sent.clear()
        ask("land")
        win.touch.attach({"name": "selfcheck", "mode": "SIM"}, None)
        wait(50)
        assert root.property("pending") == "", "SiK dut ma thanh truot van cho"
        win.touch.act("land", "")
        assert sent == [], sent

        # --- "bay toi day" cung phai truot xac nhan ---------------------------
        #
        # Truoc day cham chip la lenh di NGAY: mot cai cham lech ngon tay la
        # drone doi cho va doi ca do cao, khong co duong lui. Va bay o cho nay:
        # diem duoc chi bang PIXEL, ma ban do BAM THEO drone — giu pixel toi luc
        # truot xong la gui drone toi mot cho khac hoan toan.
        sent.clear()
        win.touch.attach({"name": "selfcheck", "mode": "SIM"}, fake)
        m = win.touch.map
        m.follow = True
        m.set_position(10.8221589, 106.6868454)
        win.touch.setWpAlt(30)
        wait(100)
        root.setProperty("wpX", view.width() * 0.3)
        root.setProperty("wpY", view.height() * 0.3)
        root.setProperty("wpOpen", True)
        wait(100)
        chip = root.findChild(QQuickItem, "wpGoto")
        assert chip is not None and chip.isVisible(), "khong thay chip 'bay toi day'"
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                         chip.mapToScene(QPointF(chip.width() / 2,
                                                 chip.height() / 2)).toPoint())
        wait(100)
        assert root.property("pending") == "goto", "cham 'bay toi day' ma khong hoi xac nhan"
        assert sent == [], f"chua truot ma lenh da di: {sent}"
        aimed = root.property("gotoAt")
        assert aimed, "khong chot lai toa do diem vua chi"
        drag(0.5)
        assert sent == [], f"tha giua chung ma van bay toi day: {sent}"
        m.set_position(10.8240000, 106.6890000)  # ban do chay theo drone luc dang truot
        wait(100)
        drag(1.0)
        assert [a for a, _ in sent] == ["mode", "goto"], sent
        got = sent[1][1]
        assert abs(got["lat"] - aimed[0]) < 1e-6 and abs(got["lon"] - aimed[1]) < 1e-6, (
            f"ban do chay theo drone ma lenh bay toi cho khac: {got} != {aimed}")
        assert got["alt"] == 30.0, f"khong dung do cao dang hien: {got}"
        assert root.property("pending") == "", "truot xong ma bang xac nhan van mo"
        sent.clear()

        # --- task Chua chay: nut ⚑ bat/huy, chip diem chay chi khi task chay --
        #
        # Lenh task di cong `remote` (WebSocket -> ros2_bridge), KHONG qua SiK.
        # Trang thai lay tu bridge (topic `mission`, 1 lan/giay): bridge im qua
        # STALE thi coi nhu khong biet — chip khong duoc gui vao node co the da chet.
        rsent = []

        class FakeRemote:
            def send(self, action, args=None):
                rsent.append((action, dict(args or {})))
                return {"ok": action}

        def tap(item):
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                             item.mapToScene(QPointF(item.width() / 2,
                                                     item.height() / 2)).toPoint())
            wait(100)

        def bridge(running, age=0.0):
            bus.emit_envelope({"src": "remote", "topic": "mission", "ts": time.time() - age,
                               "data": {"running": running, "spawn": True}})
            wait(250)  # refresh() chay moi 200 ms

        def open_wp():
            root.setProperty("wpOpen", True)
            wait(100)

        authority.register("remote", FakeRemote())
        task_btn = root.findChild(QQuickItem, "taskBtn")
        fire = root.findChild(QQuickItem, "wpFire")
        assert task_btn is not None and task_btn.isVisible(), "khong thay nut ⚑ Chua chay"
        bridge("")
        open_wp()
        assert fire is not None and not fire.isVisible(), "task chua bat ma da co chip diem chay"
        win.touch.fireAt(10.8, 106.6, 20)
        assert rsent == [], f"task chua bat ma diem chay van gui: {rsent}"

        tap(task_btn)
        assert root.property("pending") == "taskStart", root.property("pending")
        drag(0.5)
        assert rsent == [], f"tha giua chung ma task da bat: {rsent}"
        drag(1.0)
        assert rsent == [("mission", {"name": "fire_mission"})], rsent
        assert sent == [], f"lenh task lot xuong SiK: {sent}"
        rsent.clear()

        bridge("fire_mission")
        open_wp()
        assert fire.isVisible(), "task dang chay ma khong co chip 'Chua chay tai day'"
        tap(fire)
        assert root.property("pending") == "fire", "cham diem chay ma khong hoi xac nhan"
        # Bang truot diem chay co chon do cao, va so do di thang vao lenh
        box = root.findChild(QQuickItem, "takeoffAltBox")
        assert box is not None and box.isVisible(), "bang diem chay khong co chon do cao"
        root.setProperty("fireAlt", 15)
        wait(50)
        assert box.property("value") == 15, "o do cao khong theo fireAlt"
        assert "15 m" in root.findChild(QQuickItem, "slider").property("text"), (
            "thanh truot khong hien do cao se cat canh")
        aimed = root.property("gotoAt")
        m.set_position(10.8250000, 106.6900000)  # ban do chay theo drone luc dang truot
        wait(100)
        drag(0.5)
        assert rsent == [], f"tha giua chung ma diem chay da gui: {rsent}"
        drag(1.0)
        assert [a for a, _ in rsent] == ["fire_target"], rsent
        got = rsent[0][1]
        assert abs(got["lat"] - aimed[0]) < 1e-6 and abs(got["lon"] - aimed[1]) < 1e-6, (
            f"ban do chay theo drone ma diem chay gui cho khac: {got} != {aimed}")
        assert got["alt"] == 15.0, f"diem chay khong mang dung do cao da chon: {got}"
        assert root.property("takeoffAlt") == 5, "chon do cao chua chay de len cat canh tay"
        assert sent == [], f"diem chay lot xuong SiK: {sent}"
        rsent.clear()

        # Dang chay thi cung nut do la Huy task
        tap(task_btn)
        assert root.property("pending") == "taskStop", root.property("pending")
        drag(1.0)
        assert rsent == [("mission", {"name": ""})], rsent
        rsent.clear()

        # Bridge im 3 s (WebSocket chet / bridge treo): chip an, fireAt tu choi,
        # tab Dieu khien ve "chua co tin" thay vi dung o ten task cu.
        bridge("fire_mission")
        assert win.touch._state["taskFire"] is True
        bridge("fire_mission", age=3)
        open_wp()
        assert win.touch._state["taskFire"] is False, "bridge im 3 s ma van coi task dang chay"
        assert not fire.isVisible(), "bridge im 3 s ma chip diem chay van hien"
        win.touch.fireAt(*aimed, 20)
        assert rsent == [], f"bridge im ma diem chay van gui: {rsent}"
        win.control_tab._mission_timer.timeout.emit()
        assert win.control_tab.mission_now.text() == t("ctl.mission_none"), (
            f"bridge im ma tab Dieu khien van bao: {win.control_tab.mission_now.text()}")
        authority.unregister("remote")
        root.setProperty("wpOpen", False)
        root.setProperty("pending", "")
        wait(50)

        # --- camera dung hinh phai NOI LEN man bay ----------------------------
        #
        # O video da doi mau chu, nhung o PiP nam goc duoi trai 240x135: nguoi lai
        # dang nhin ban do thi khong co gi keo mat ve do. Ban tin hieu that tu
        # VideoSource de do luon ca duong day (`app.py` co noi khong), khong goi
        # tay vao ham xu ly.
        win.video.frozen_changed.emit(True)
        wait(50)
        assert any("ĐỨNG HÌNH" in txt for txt, _ in win.touch.alerts.shown()), \
            f"camera dung hinh ma man bay im: {win.touch.alerts.shown()}"
        lst = win.messages_tab.list
        assert any("ĐỨNG HÌNH" in lst.item(r).text() for r in range(lst.count())), \
            "dung hinh ma tab Thong bao khong co dong nao"
        win.video.frozen_changed.emit(False)
        wait(50)
        # "Chay lai" la tin vui: vao tab Thong bao de doc lai, KHONG noi len man bay.
        assert not any("chạy lại" in txt for txt, _ in win.touch.alerts.shown()), \
            f"dong 'camera chay lai' khong duoc chiem cho tren man bay: {win.touch.alerts.shown()}"
        assert any("chạy lại" in lst.item(r).text() for r in range(lst.count())), \
            "camera chay lai ma khong ghi lai o tab Thong bao"
        win.touch.alerts.clear()

        # --- o camera: cham de doi cho, ngat ket noi la tra ve ban do ---------
        #
        # Truoc day bai nay do hinh hoc QWidget cua tab Bay cu. Man cam ung lam
        # cung viec do bang mot WidgetItem doi ten nguon, nen cai phai do la
        # `camBig` — va nhat la cho no TU TAT khi mat ket noi: ket o mot khung
        # camera chet trong luc drone dang bay la hong nang.
        win.touch.attach({"name": "selfcheck", "mode": "SIM",
                          "remote": "ws://127.0.0.1:1"}, fake)  # co remote -> hien o camera
        wait(100)
        assert root.property("camBig") is False, "mo len da ket o camera"
        pip = root.findChild(QQuickItem, "pip")
        assert pip is not None and pip.property("visible"), "khong thay o camera"
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                         pip.mapToScene(QPointF(pip.width() / 2, pip.height() / 2)).toPoint())
        wait(100)
        assert root.property("camBig") is True, "bam o camera ma khong phong len"
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                         pip.mapToScene(QPointF(pip.width() / 2, pip.height() / 2)).toPoint())
        wait(100)
        assert root.property("camBig") is False, "bam ban do nho ma khong doi lai"

        root.setProperty("camBig", True)
        wait(100)
        win.touch.attach(None, None)
        wait(300)
        assert root.property("camBig") is False, "ngat ket noi ma van ket o camera"

        # --- cham-giu mo bang duong bay, va no phai O YEN ---------------------
        #
        # `stateChanged` ban 5 Hz. Truoc day cai dong bang khi mat ket noi kiem
        # theo MUC chu khong theo suon, nen luc CHUA cam radio, bang vua mo la
        # 200 ms sau tu dong dong — cham-giu nhin nhu khong an gi. Doi >= 2 nhip.
        win.touch.attach(None, None)
        wait(50)
        assert root.property("wpOpen") is False
        pt = QPoint(int(view.width() * 0.4), int(view.height() * 0.5))
        ring = root.findChild(QQuickItem, "holdRing")
        # Chon diem phai GIU 2 s (nguoi dung chot 19/09): cham mot cai KHONG mo.
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, pt)
        wait(400)
        assert root.property("wpOpen") is False, "cham mot cai ma da chon diem"
        # Giu 1,2 s roi tha: vong tron co chay, nhung tha som = huy
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, pt)
        wait(1200)
        assert ring.isVisible() and 0.3 < ring.property("p") < 0.9, ring.property("p")
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, pt)
        wait(300)
        assert root.property("wpOpen") is False, "giu chua du 2 s ma da chon diem"
        assert not ring.isVisible(), "tha tay roi ma vong tron van con"
        # Giu du 2 s: mo bang, dung cho ngon tay — va O YEN khi chua ket noi
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, pt)
        wait(2300)
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, pt)
        wait(500)
        assert root.property("wpOpen") is True, "giu 2 s ma bang diem den khong mo (hay tu dong)"
        assert abs(root.property("wpX") - pt.x()) < 2, root.property("wpX")
        assert not ring.isVisible()

        # ...nhung KEO ban do thi khong: keo xong ma bang bat ra la khong dung duoc.
        root.setProperty("wpOpen", False)
        wait(250)
        center0 = win.touch.map.center
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, pt)
        for i in range(1, 11):
            QTest.mouseMove(view, pt + QPoint(6 * i, 4 * i))
            wait(10)
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, pt + QPoint(60, 40))
        wait(300)
        assert win.touch.map.center != center0, "keo ma ban do khong chay"
        assert root.property("wpOpen") is False, "keo ban do xong ma bang diem den bat ra"

        # Cham dup = quay ve dung cho drone, KE CA ngon tay rung vai px.
        # Do that: rung 2 px o lan cham thu hai -> follow=False, ban do dung im.
        m = win.touch.map
        m.set_position(10.8221, 106.6868)
        assert not m.follow and m.center != m.pos, "chua keo lech thi khong co gi de thu"
        m.zoom = 5  # dang xem ca vung rong: cham dup phai phong vao drone luon
        QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, pt)
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, pt)
        QTest.mouseMove(view, pt + QPoint(2, 1))
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, pt + QPoint(2, 1))
        wait(300)
        assert m.follow and m.center == m.pos, f"cham dup ma khong ve cho drone: {m.center} != {m.pos}"
        assert m.zoom == 20, f"cham dup o z5 ma khong phong toi z20: z{m.zoom}"
        root.setProperty("wpOpen", False)
        # Nhung VUA dut giua chung thi van phai dong (suon xuong, khong bo sot)
        win.touch.attach({"name": "selfcheck", "mode": "SIM"}, fake)
        wait(250)
        win.touch.attach(None, None)
        wait(250)
        assert root.property("wpOpen") is False, "dut ket noi ma bang duong bay van mo"
    finally:
        authority.unregister("sik")
        win.touch.attach(None, None)
        win.close()
    print("  ok  tab Bay cam ung: mo san, chung Commands, tha giua chung khong co lenh, "
          "truot het moi di, cat dong co truot het la di (khong giu), mat SiK la huy; \"bay toi day\" "
          "cung phai truot, toa do chot luc chi chu khong doc lai pixel; task Chua chay: nut ⚑ "
          "bat/huy qua `remote` (khong qua SiK), chip diem chay chi khi task chay, bridge im 3 s "
          "thi an chip + tu choi + tab Dieu khien 'chua co tin'; camera dung hinh noi len "
          "man bay + tab Thong bao, dong \"chay lai\" chi vao tab Thong bao; ban do: giu 2 s "
          "(co vong tron) moi mo bang diem den, cham mot cai/tha som thi khong, keo thi khong mo; cham dup "
          "(ke ca ngon tay rung) ve dung cho drone")


def check_touch_flight(app):
    """Man bay da gop: MOT tab bay, va waypoint + nhich deu lam duoc bang tay.

    Truoc day co hai tab bay song song, moi tab mot MapWidget rieng — dat
    waypoint chi duoc o tab cu (chuot phai) va nhich chi duoc o do (ban phim).
    Check nay do dung cai da chuyen sang man cam ung, va do o TANG BACKEND vi
    do la cho quyet dinh co gui goi hay khong; phan QML (cham-giu, keo can) chi
    la cai goi vao day.
    """
    from core import authority
    from core.adapters.sik import WP_MAX
    from core.field import REGISTRY
    from laptop.app import MainWindow
    from laptop.commands import NUDGE_V0, NUDGE_VMAX, WP_CONFIRM_S

    sent = []

    class Fake:
        def send(self, action, args=None):
            sent.append((action, dict(args or {})))
            return {"ok": action}

    def state(**kw):
        REGISTRY.feed({"src": "sik", "topic": "heartbeat", "data": kw, "ts": time.time()})

    lat, lon = 10.8221589, 106.6868454
    fake = Fake()
    authority.register("sik", fake)
    win = MainWindow([])
    win.resize(1280, 760)
    logs = []
    win.touch.cmd.log.connect(lambda text, _sev: logs.append(text))
    b = win.touch
    try:
        # --- mot man bay duy nhat, va no la man cam ung ----------------------
        assert win.touch_view.parent() is win.ui.Flight, "man cam ung khong nam trong tab Bay"
        assert not hasattr(win, "flight_tab"), "van con tab Bay thu hai"
        # Hai MapWidget la hai cai cung bam theo drone va cung tai tile.
        maps = [w for w in app.allWidgets()
                if type(w).__name__ == "MapWidget" and w.window() is win]
        assert len(maps) <= 1, f"con {len(maps)} ban do trong cua so chinh"

        b.attach({"name": "selfcheck", "mode": "SIM"}, fake)
        b.map.resize(600, 400)
        b.map.center = (lat, lon)

        # Goi "link" adapter tu phat moi giay du khong co goi nao tu drone — khong
        # duoc tinh la drone dang noi (vien "San sang" luc chua cam FC, 19/10).
        bus.emit_envelope({"src": "sik", "topic": "link", "data": {"bps": 0}, "ts": time.time()})
        # ... va dong loi lenh adapter tu sinh (mode khi chua co FC): khong tinh, khong
        # thi 2 s sau bao "MAT TIN HIEU SiK" khi SiK chua tung noi (19/10 tren dien thoai).
        bus.emit_envelope({"src": "sik", "topic": "text", "ts": time.time(),
                           "data": {"severity": 3, "text": "lenh mode loi: x", "local": True}})
        b.refresh()
        assert b.state["statusLevel"] != "ok", f"chua co goi FC ma bao: {b.state['status']}"

        # --- waypoint: cham-giu ban do --------------------------------------
        b.setWpAlt(30)
        b.addWp(300, 200)
        b.addWp(320, 180)
        assert b.state["draftN"] == 2, b.state["draftN"]
        assert b.map.draft[0][2] == 30.0, "chip do cao khong vao diem vua dat"
        # Dai chu duoi ban do phai dem dung so diem dang soan
        assert "đang đặt 2 điểm" in b.map._draft_note(), b.map._draft_note()
        b.undoWp()
        assert b.state["draftN"] == 1, "bo diem cuoi khong an"

        sent.clear()
        b.sendWp()
        assert sent == [("wp_write", {"items": [list(p) for p in b.map.draft]})], sent

        # FC nhan -> ban nhap phai bien mat (hai duong chong len nhau la khong doc duoc)
        bus.emit("sik", "wp", {"write": {"ok": True, "result": 0, "n": 1}})
        assert b.state["draftN"] == 0 and "FC nhận 1 waypoint" in logs[-1], logs[-1]
        # FC tu choi -> ban nhap CON NGUYEN de bam nap lai
        b.addWp(300, 200)
        bus.emit("sik", "wp", {"write": {"ok": False, "result": 5, "n": 1}})
        assert b.state["draftN"] == 1, "tu choi ma van xoa mat ban nhap"
        assert "THẤT BẠI" in logs[-1], logs[-1]

        # --- ngat ket noi phai bo ca lenh DANG CHO tra loi ---------------------
        #
        # Lo ra o e2e_sitl (L1, khong tai lap duoc moi lan): bam mot lenh roi ngat
        # trong vong ACK_TIMEOUT thi 3 giay sau `_check_pending` van bat canh bao
        # "FC khong tra loi" len mot man hinh VUA DON SACH — hoac len dau ket noi
        # ke tiep neu cam lai nhanh.
        b.cmd._pending.clear()
        b.alerts.clear()
        b.cmd.arm()                           # vao `_pending`, Fake khong tra ACK
        assert b.cmd._pending, "lenh bam roi ma khong ai cho FC tra loi"
        b.attach(None, None)                  # = disconnect()
        assert not b.cmd._pending, "ngat roi ma lenh cu van con cho ACK"
        b.cmd._check_pending()                # qua han: khong duoc noi gi nua
        assert not b.state["alerts"], f"canh bao ve sau luc ngat: {b.state['alerts']}"

        # ...va mot GOI VI TRI ve tre cung khong duoc dung len home gia. Adapter
        # da stop() va join(), nhung tin hieu xep hang van phat khi vong su kien
        # quay lai — do duoc o e2e_sitl L1: home hien ra o BAI DAP, khong phai o
        # cho cat canh, roi "ve nha N m" dem tu cho sai do.
        REGISTRY.feed({"src": "sik", "topic": "position",
                       "data": {"lat": lat + 0.02, "lon": lon + 0.02, "alt_rel": 7.0},
                       "ts": time.time()})
        b.refresh()
        assert b.map.home is None, f"goi tre dung len home gia: {b.map.home}"
        assert b.state["alt"] is None, f"ngat roi ma o do cao con so cu: {b.state['alt']}"
        b.attach({"name": "selfcheck", "mode": "SIM"}, fake)
        b.map.resize(600, 400)
        b.map.center = (lat, lon)

        # --- do cao waypoint: nhap tay, va bi KEP o hai dau --------------------
        #
        # O nhap so go ra duoc bat cu gi, ma con so nay di thang xuong FC. Kep o
        # backend chu khong tin vao SpinBox tu giu minh: mot ban QML khac, hay
        # mot lenh goi tu cho khac, van phai bi kep.
        from laptop.commands import WP_ALT_MAX, WP_ALT_MIN
        b.setWpAlt(42)
        assert b.map.wp_alt == 42.0, "khong nhan do cao nhap tay"
        b.setWpAlt(WP_ALT_MAX + 500)
        assert b.map.wp_alt == float(WP_ALT_MAX), f"tran khong kep: {b.map.wp_alt}"
        b.setWpAlt(0)
        assert b.map.wp_alt == float(WP_ALT_MIN), f"day khong kep: {b.map.wp_alt}"
        b.setWpAlt(-7)
        assert b.map.wp_alt == float(WP_ALT_MIN), f"so am khong kep: {b.map.wp_alt}"
        # Do cao nhap tay phai vao dung diem dat SAU do
        b.clearWp()
        b.setWpAlt(42)
        b.addWp(300, 200)
        assert b.map.draft[0][2] == 42.0, "do cao nhap tay khong vao diem vua dat"
        b.clearWp()

        # --- "bay toi day": do cao phai la SO DANG HIEN, khong phai 10 m chet -----
        #
        # Truoc day `Commands.goto` khong truyen `alt`, adapter tu dien 10 m: dang
        # bay 50 m ma bam mot cai la drone tut xuong 10, khong mot dong nao noi ra.
        sent.clear()
        logs.clear()
        b.setWpAlt(30)
        b.goto(300, 200)
        assert [a for a, _ in sent] == ["mode", "goto"], sent
        assert sent[0][1] == {"name": "GUIDED"}, sent[0]
        assert sent[1][1]["alt"] == 30.0, f"bay toi day khong dung do cao dang chon: {sent[1]}"
        assert "30 m" in logs[-1], f"lenh doi do cao ma khong de lai vet: {logs}"
        # ...va cau tra loi cua FC phai RA MAN HINH. Do that 04/10/2026 tren SITL:
        # diem ngoai rao, FC tra MISSION_ACK type=1, giao dien chi con "da gui, cho
        # FC tra loi" + "doi mode: FC chap nhan" — toan tin tot, drone dung im.
        b.alerts.clear()
        bus.emit("sik", "wp", {"goto": {"ok": False, "result": 1}})
        assert "KHÔNG đi" in logs[-1] and "=1" in logs[-1], logs[-1]
        b.refresh()
        assert any(a["crit"] and "KHÔNG đi" in a["text"] for a in b.state["alerts"]), \
            f"FC tu choi bay toi day ma man bay im lang: {b.state['alerts']}"
        assert "goto" not in b.map.wp, "ket qua lenh bi tron vao du lieu duong bay"
        bus.emit("sik", "wp", {"goto": {"ok": True, "result": 0}})
        assert "chấp nhận" in logs[-1], logs[-1]

        # Dang bay AUTO: cu bam dau tien chi canh bao, khong gui gi ca
        sent.clear()
        state(mode="AUTO", armed=True, landed=False)
        b.refresh()
        assert b.state["wpOver"] is True, "khong bao la dang ghi de nhiem vu dang bay"
        b.sendWp()
        assert not sent, "ghi de nhiem vu dang bay ma khong hoi lai"
        assert f"{WP_CONFIRM_S:.0f}s" in logs[-1] and "ĐANG BAY AUTO" in logs[-1], logs[-1]
        b.sendWp()  # bam lai trong WP_CONFIRM_S -> di
        assert sent and sent[0][0] == "wp_write", sent

        # Tran WP_MAX: cai thu 51 khong dat duoc, va phai NOI RA
        b.clearWp()
        for _ in range(WP_MAX):
            b.map.add_draft(lat, lon)
        b.addWp(300, 200)
        assert b.state["draftN"] == WP_MAX and str(WP_MAX) in logs[-1], logs[-1]
        b.clearWp()

        # --- can ao: bon chot chan giong het ban phim ------------------------
        for label, st in [
            ("chua armed", {"mode": "GUIDED", "armed": False, "landed": False}),
            ("con duoi dat", {"mode": "GUIDED", "armed": True, "landed": True}),
            ("dang o AUTO", {"mode": "AUTO", "armed": True, "landed": False}),
        ]:
            state(**st)
            sent.clear()
            b.stick(0, 1, 0)
            assert not sent, f"{label}: van gui lenh nhich"
            assert "KHÔNG được" in logs[-1], (label, logs[-1])
            assert b.state["nudgeWhy"], f"{label}: can ao khong noi ly do"

        # --- duoc phep: day het = tran toc do, cham nhe = cham --------------
        state(mode="GUIDED", armed=True, landed=False)
        b.refresh()
        assert b.state["nudgeWhy"] == "", b.state["nudgeWhy"]
        sent.clear()
        b.stick(0, 1, 0)
        act, args = sent[-1]
        assert act == "nudge" and abs(args["vn"] - NUDGE_VMAX) < 1e-6, sent
        assert args["ve"] == 0 and args["vd"] == 0, args

        b.stick(0, 0.0001, 0)
        b._nudge_tick()
        assert abs(sent[-1][1]["vn"] - NUDGE_V0) < 0.01, f"cham nhe phai di cham: {sent[-1]}"

        # Cheo khong duoc nhanh hon: hai truc van la NUDGE_VMAX, khong phai 1,41 lan
        b.stick(1, 1, 0)
        b._nudge_tick()
        a = sent[-1][1]
        assert abs((a["vn"] ** 2 + a["ve"] ** 2) ** 0.5 - NUDGE_VMAX) < 1e-6, sent[-1]

        # Leo: man hinh len la vd AM (NED)
        b.stick(0, 0, 1)
        b._nudge_tick()
        assert sent[-1][1]["vd"] < 0, f"bam leo ma vd duong: {sent[-1]}"

        # --- nhac tay -> van toc 0, va timer phai dung ----------------------
        sent.clear()
        b.stick(0, 0, 0)
        assert sent[-1] == ("nudge", {"vn": 0.0, "ve": 0.0, "vd": 0.0}), sent
        assert not b._nudge_timer.isActive(), "nhac tay roi ma timer van chay"

        # --- ngat ket noi: so lieu cua chuyen cu KHONG duoc o lai --------------
        #
        # `map.reset()` xoa home, nhung `refresh()` chay 5 Hz va doc thang REGISTRY:
        # con vi tri cu trong do la no dung lai mot home moi ngay tai cho drone vua
        # dung, roi "ve nha bao nhieu met" dem tu cai cho sai do.
        state(mode="GUIDED", armed=True, landed=False)
        REGISTRY.feed({"src": "sik", "topic": "position",
                       "data": {"lat": lat, "lon": lon, "alt_rel": 42.0}, "ts": time.time()})
        b.refresh()
        assert b.map.home is not None and b.state["alt"] == 42.0, "chua co gi de xoa"
        b.attach(None, None)   # `attach` tu goi `refresh()`, khong phai doi timer
        assert b.map.home is None, "ngat roi ma home cua chuyen cu dung lai tren ban do"
        assert b.state["alt"] is None and b.state["sats"] is None, \
            f"ngat roi ma o do cao/ve tinh van hien so cu: {b.state['alt']}"
        # Nap lai canh bay cho bai ke tiep: vua xoa sach REGISTRY o tren.
        b.attach({"name": "selfcheck", "mode": "SIM"}, fake)
        state(mode="GUIDED", armed=True, landed=False)
        b.refresh()

        # --- SAN SANG ARM: bit PREARM_CHECK cua SYS_STATUS + ly do PreArm ------
        state(mode="GUIDED", armed=False, landed=True)
        bus.emit_envelope({"src": "sik", "topic": "status", "ts": time.time(),
                           "data": {"SENSOR.prearm_check": "fail"}})
        bus.emit_envelope({"src": "sik", "topic": "text", "ts": time.time(),
                           "data": {"severity": 2, "text": "PreArm: RC not found"}})
        b.refresh()
        r = b.state["ready"]
        assert r and not r["ok"] and "RC not found" in r["text"], r
        # Vien tren cung khong duoc xanh "Sẵn sàng" ngay tren dong CHUA SAN SANG ARM
        # (anh 23/10 21:45).
        assert (b.state["status"], b.state["statusLevel"]) == ("Chưa sẵn sàng", "warn"), \
            (b.state["status"], b.state["statusLevel"])
        bus.emit_envelope({"src": "sik", "topic": "status", "ts": time.time(),
                           "data": {"SENSOR.prearm_check": "ok"}})
        b.refresh()
        assert b.state["ready"] == {"ok": True, "text": "SẴN SÀNG ARM"}, b.state["ready"]
        assert b.state["status"] == "Sẵn sàng", b.state["status"]
        assert not b._prearm_why, "da san sang ma con giu ly do PreArm cu"
        from PySide6.QtQuick import QQuickItem
        app.processEvents()
        bar = win.touch_view.rootObject().findChild(QQuickItem, "readyBar")
        assert bar is not None and bar.isVisible(), "khong thay dong SAN SANG ARM"
        state(mode="GUIDED", armed=True, landed=False)
        b.refresh()
        assert b.state["ready"] is None, "da ARM ma van hien san sang ARM"

        # --- vet bay: chi khi ARM, xoa lai moi lan ARM (nhu QGC) --------------
        # 23/10 21:40: vi tri dau (GPS 4 ve tinh) lech 88 m, chua ARM ma da co mot
        # duong thang dai tu home ra mep man hinh.
        def at(dlat):
            REGISTRY.feed({"src": "sik", "topic": "position", "ts": time.time(),
                           "data": {"lat": lat + dlat, "lon": lon}})
            b.refresh()
        state(mode="GUIDED", armed=False, landed=True)
        b.refresh()
        b.map.trail[:] = [(0.0, 0.0)]  # vet chuyen truoc
        at(0.001)
        at(0.002)
        assert b.map.trail == [(0.0, 0.0)], f"chua ARM ma van noi vet: {b.map.trail}"
        state(mode="GUIDED", armed=True, landed=False)
        at(0.003)
        at(0.004)
        assert (0.0, 0.0) not in b.map.trail, "ARM chuyen moi ma con vet chuyen truoc"
        assert b.map.trail and b.map.trail[-1] == (lat + 0.004, lon), b.map.trail

        # --- thanh NGUOI canh che do bay: theo khung video dang hien ----------
        persons = win.touch_view.rootObject().findChild(QQuickItem, "persons")
        assert persons is not None
        old_prof = b.profile
        b.profile = None  # profile khong co video -> khong co thanh
        b.refresh()
        app.processEvents()
        assert not persons.isVisible(), "khong co camera ma van hien thanh NGUOI"
        b.profile = {"name": "x", "mode": "SIM", "video": "http://127.0.0.1:9/stream"}
        b.refresh()
        app.processEvents()
        # Co camera ma chua co so: hien "--", KHONG an (an thi nguoi lai khong biet
        # bo dem da chet).
        assert persons.isVisible() and persons.property("value") == "--", \
            f"thanh NGUOI khi chua co so: {persons.isVisible()} {persons.property('value')!r}"
        # So lay tu VideoSource.persons (hoi /status, xem check_video)
        def ppl(n):
            b.video_src.persons = n
            b.refresh()
            app.processEvents()
            return persons.property("value")
        assert ppl(4) == "4"
        from laptop import theme as _th
        assert persons.property("color").name() == _th.ACCENT.lower(), \
            f"co nguoi ma thanh khong noi mau: {persons.property('color').name()}"
        b.video_src._frozen = True  # camera dung hinh: model dang dem mot canh cu
        assert ppl(4) == "--", "dung hinh ma van hien so nguoi"
        b.video_src._frozen = False
        assert ppl(None) == "--", "/status loi ma van hien so nguoi"
        b.profile = old_prof
        b.refresh()

        # --- o CON: tham so pin chi ve MOT lan, phai con dung sau STALE -------
        # Do that 19/09 (log 151442): BATT_CAPACITY ve o giay 0,1; doc tu REGISTRY
        # thi toi giay 2 no da "het tuoi" va o CON hien "--" suot chuyen bay.
        bus.emit_envelope({"src": "sik", "topic": "param", "ts": time.time() - 10,
                           "data": {"BATT_CAPACITY": 1800.0, "BATT_LOW_MAH": 540.0,
                                    "BATT_CRT_MAH": 360.0}})
        bus.emit_envelope({"src": "sik", "topic": "battery", "ts": time.time(),
                           "data": {"current": 0.63, "consumed_mah": 202, "remaining": 88}})
        b.refresh()
        # (1800 - 202 - 540) mAh / 630 mA = 6046 s
        assert b.state["battLeft"] in (6045, 6046), f"o CON sau 10 s: {b.state['battLeft']}"

        # --- VE NHA NGAY: RTL uoc tu tham so FC (so that MicoAir743 07/09) -----
        rtl = {"RTL_ALT_M": 2.0, "RTL_SPEED_MS": 0.0, "WP_SPD": 1.0, "WP_SPD_UP": 2.5,
               "WP_SPD_DN": 1.5, "LAND_SPD_MS": 0.5, "LAND_SPD_HIGH_MS": 0.0,
               "LAND_ALT_LOW_M": 10.0, "RTL_LOIT_TIME": 5000.0}
        bus.emit_envelope({"src": "sik", "topic": "param", "ts": time.time(), "data": rtl})
        b.map.set_home(lat, lon, from_fc=True)
        REGISTRY.feed({"src": "sik", "topic": "position", "ts": time.time(),
                       "data": {"lat": lat + 0.0045, "lon": lon, "alt_rel": 20.0}})
        b.refresh()
        assert b.state["warns"] == [], f"con ~100 phut ma da doi ve: {b.state['warns']}"
        b._amps = None  # bo lam muot: dong nhay len 7 A ngay
        bus.emit_envelope({"src": "sik", "topic": "battery", "ts": time.time(),
                           "data": {"current": 7.05, "consumed_mah": 202, "remaining": 88}})
        b.refresh()
        w = b.state["warns"]
        # 500 m / 1 m/s + 5 s + 10 m / 1,5 + 10 m / 0,5 = ~531 s; con ~540 s -> VE NGAY
        assert len(w) == 1 and w[0]["crit"] and "VỀ NHÀ NGAY" in w[0]["text"], w
        from laptop import safety
        assert safety.rtl_time_s(rtl, 500, 20) == 531
        # Khong home (0 ve tinh) -> khong uoc duoc RTL, nhung o CON van dem toi
        # failsafe pin. So that bay 11/10/2026: o CON do 52 s ma chu, giong im.
        b.map.home_from_fc = False
        b.voice.reset(); b.voice.spoken.clear()
        bus.emit_envelope({"src": "sik", "topic": "battery", "ts": time.time(),
                           "data": {"current": 7.05, "consumed_mah": 1160, "remaining": 36}})
        b.refresh()
        w = b.state["warns"]
        # (1800 - 1160 - 540) mAh / 7050 mA = 51 s
        assert b.state["battLeft"] == 51, b.state["battLeft"]
        assert len(w) == 1 and w[0]["crit"] and "HẠ CÁNH NGAY" in w[0]["text"] \
            and "0:51" in w[0]["text"], w
        assert "Hạ cánh ngay" in b.voice.spoken, b.voice.spoken
        b.map.home_from_fc = True

        # --- chua ARM: kiem failsafe + pin day chua (so that log 14:52 hom nay) --
        state(mode="GUIDED", armed=False, landed=True)
        bus.emit_envelope({"src": "sik", "topic": "param", "ts": time.time(),
                           "data": {"BATT_FS_LOW_ACT": 0.0, "BATT_FS_CRT_ACT": 0.0,
                                    "BATT_LOW_VOLT": 10.8, "FS_THR_ENABLE": 3.0,
                                    "FS_GCS_ENABLE": 0.0}})
        bus.emit_envelope({"src": "sik", "topic": "battery", "ts": time.time(),
                           "data": {"voltage": 15.275, "current": 0.05, "remaining": 99}})
        b.refresh()
        txt = " | ".join(x["text"] for x in b.state["warns"])
        for want in ("Failsafe pin", "FS_GCS_ENABLE", "2.70 V/cell", "KHÔNG đầy"):
            assert want in txt, f"thieu '{want}': {txt}"
        assert "FS_THR_ENABLE" not in txt, "FS_THR_ENABLE = 3 la dang BAT"
        # Tham so dung + pin day: khong con gi
        bus.emit_envelope({"src": "sik", "topic": "param", "ts": time.time(),
                           "data": {"BATT_FS_LOW_ACT": 2.0, "BATT_LOW_VOLT": 14.0,
                                    "FS_GCS_ENABLE": 1.0}})
        bus.emit_envelope({"src": "sik", "topic": "battery", "ts": time.time(),
                           "data": {"voltage": 16.7, "current": 0.05, "remaining": 99}})
        b.refresh()
        assert b.state["warns"] == [], b.state["warns"]

        # --- tab Dieu khien hien cung trang thai (tien ich) ---------------------
        b.refresh()
        win.control_tab.show_flight(b.state)
        state(mode="GUIDED", armed=False, landed=True)
        bus.emit_envelope({"src": "sik", "topic": "param", "ts": time.time(),
                           "data": {"BATT_FS_LOW_ACT": 0.0}})
        bus.emit_envelope({"src": "sik", "topic": "status", "ts": time.time(),
                           "data": {"SENSOR.prearm_check": "ok"}})
        b.refresh()
        ctl = win.control_tab.flight.text()
        assert "SẴN SÀNG ARM" in ctl and "Failsafe pin" in ctl, ctl

        # --- giong noi: doc khi DOI trang thai, khong doc lai moi nhip ---------
        b.voice.spoken.clear(); b.voice.reset()
        for _ in range(5):
            b.refresh()
        assert b.voice.spoken.count("Sẵn sàng arm") == 1, b.voice.spoken
        state(mode="GUIDED", armed=True, landed=False)
        b._amps = None
        bus.emit_envelope({"src": "sik", "topic": "battery", "ts": time.time(),
                           "data": {"current": 7.05, "consumed_mah": 202, "remaining": 88,
                                    "voltage": 16.0}})
        for _ in range(5):
            b.refresh()
        assert b.voice.spoken.count("Về nhà ngay") == 1, b.voice.spoken
        b.voice._said_at["rtl"] -= 31  # = 31 s sau, van con phai ve
        b.refresh()
        assert b.voice.spoken.count("Về nhà ngay") == 2, "VE NHA NGAY phai nhac lai moi 30 s"

        # --- giong noi doc dong loi DO: moi dong mot lan, bo PreArm, bo vang ----
        b.voice.spoken.clear()
        for sev, text in ((2, "EKF variance"), (2, "PreArm: Compass not calibrated"),
                          (4, "GPS glitch")):
            bus.emit_envelope({"src": "sik", "topic": "text", "ts": time.time(),
                               "data": {"severity": sev, "text": text}})
        for _ in range(5):
            b.refresh()
        said = [x for x in b.voice.spoken if x.startswith("Lỗi")]
        assert said == ["Lỗi: EKF variance"], b.voice.spoken

        # --- ARM / DISARM / doi mode: doc khi DOI, khong doc lan dau thay -------
        b.voice.spoken.clear()
        for _ in range(3):
            b.refresh()  # dang GUIDED + ARM tu tren: khong doi -> im
        state(mode="LOITER", armed=True, landed=False)
        for _ in range(3):
            b.refresh()
        state(mode="LOITER", armed=False, landed=True)
        for _ in range(3):
            b.refresh()
        said = [x for x in b.voice.spoken if x.startswith(("Chế độ", "Đã"))]
        assert said == ["Chế độ LOITER", "Đã disarm"], b.voice.spoken
        b.voice.reset()
        b.voice.spoken.clear()
        b.refresh()  # vua noi lai: gia tri dau tien khong duoc doc
        assert not [x for x in b.voice.spoken if x.startswith(("Chế độ", "Đã"))], b.voice.spoken
        state(mode="LOITER", armed=True, landed=True)
        b.refresh()
        assert "Đã arm" in b.voice.spoken, b.voice.spoken
        # RTL doc day du, khong doc tat — ca ten mode lan cau loi cua FC.
        state(mode="RTL", armed=True, landed=False)
        b.refresh()
        assert "Chế độ return to launch" in b.voice.spoken, b.voice.spoken
        b.voice.say("voice.alert", text="Failsafe: RTL, SmartRTL")
        assert b.voice.spoken[-1] == "Lỗi: Failsafe: return to launch, smart return to launch", \
            b.voice.spoken[-1]
        # Bay that 11/10/2026: 6 lan bam ARM, FC tra 4 so mag khac nhau -> doc 4 lan.
        # AlertBook giu tung cau rieng, nen red() lon dan qua moi lan.
        b.voice.reset(); b.voice.spoken.clear()
        red = set()
        for n in (172, 169, 169, 168, 176):
            red.add(f"Arm: Check mag field:  {n}, max 875, min 185")
            b.voice.alerts(red)
        red.add("Arm: Yaw (RC4) is not neutral")
        b.voice.alerts(red)
        assert b.voice.spoken == ["Lỗi: Arm: Check mag field:  172, max 875, min 185",
                                  "Lỗi: Arm: Yaw (RC4) is not neutral"], b.voice.spoken
        # So nguoi: doc khi VUOT muc da doc; rung 2-1-2, mat hinh, ve lai cung so
        # thi im; tut han 5 s roi co nguoi moi thi doc lai.
        b.voice.reset()
        b.voice.spoken.clear()
        for n, now in ((None, 0), (0, 0.5), (2, 1), (1, 2), (2, 3), (None, 4), (2, 9),
                       (3, 10), (0, 11), (0, 16.5), (1, 17)):
            b.voice.persons(n, now)
        assert b.voice.spoken == ["Phát hiện 2 người", "Phát hiện 3 người",
                                  "Phát hiện 1 người"], b.voice.spoken
        # ...va noi qua _announce() that: state["persons"] -> giong doc
        b.voice.reset()
        b.voice.spoken.clear()
        b.profile = {"name": "x", "mode": "SIM", "video": "http://127.0.0.1:9/stream"}
        b.video_src.persons = 2
        b.refresh()
        b.video_src.persons = None  # khong de so lai cho cac bai sau
        b.profile = old_prof
        assert "Phát hiện 2 người" in b.voice.spoken, b.voice.spoken
        # Giong Piper (neu da tai): tong hop duoc ca hai thu tieng, do dai hop ly.
        # Khong phat ra loa — enabled() da tat o dau selfcheck.
        from laptop.voice import _Piper
        if b.voice._piper is not None:
            for lang, txt in (("vi", "Về nhà ngay"), ("en", "Return now")):
                if _Piper.has(lang):
                    pcm, rate = b.voice._piper.pcm(txt, lang)
                    dur = len(pcm) / 2 / rate
                    assert 0.4 < dur < 3.0, (lang, dur)

        # --- cham dong loi tren man bay -> tab Thong bao, dung dong do ---------
        bus.emit_envelope({"src": "sik", "topic": "text", "ts": time.time(),
                           "data": {"severity": 2, "text": "PreArm: Check mag field:  168"}})
        bus.emit_envelope({"src": "sik", "topic": "text", "ts": time.time(),
                           "data": {"severity": 2, "text": "PreArm: Check mag field:  168"}})
        bus.emit_envelope({"src": "sik", "topic": "text", "ts": time.time(),
                           "data": {"severity": 6, "text": "khong lien quan"}})
        b.refresh()
        shown = [a["text"] for a in b.state["alerts"] if "mag" in a["text"]]
        assert shown and "×2" in shown[0], b.state["alerts"]
        b.showMessage(shown[0])  # = QML cham vao dong do
        assert win.ui.tabWidget.currentWidget() is win.ui.Messages, "cham loi ma khong mo tab"
        cur = win.messages_tab.list.currentItem()
        assert cur is not None and "Check mag field" in cur.text(), cur and cur.text()
        win.ui.tabWidget.setCurrentWidget(win.ui.Flight)

        b.attach(None, None)
        assert not b._params, "ngat roi ma con giu tham so cua drone cu"
        b.attach({"name": "selfcheck", "mode": "SIM"}, fake)
        state(mode="GUIDED", armed=True, landed=False)
        b.refresh()

        # --- mat SiK giua luc dang nhich: buong can, khong ban vao khoang khong
        b.stick(0, 1, 0)
        assert b._nudge_timer.isActive()
        sent.clear()
        win.profile, win.mode = b.profile, "SIM"  # nhu vua connect_to xong
        win._stop_sik()  # duong that: SikAdapter.failed -> MainWindow
        assert not b._nudge_timer.isActive(), "mat SiK ma can ao van dang nhich"
        assert not sent, "link da dut ma van con gui goi"
    finally:
        authority.unregister("sik")
        REGISTRY.fields.clear()
        b.attach(None, None)
        win.close()
    print(f"  ok  man bay gop: 1 ban do, waypoint bang cham-giu (tran {WP_MAX}, xac nhan "
          f"2 lan khi dang AUTO), can ao {NUDGE_V0:g}->{NUDGE_VMAX:g} m/s, mat SiK la buong")


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
    from laptop.widgets import telemetry_bar as tb

    # --- ham nguong, kiem thang ---
    proc = (Path(__file__).resolve().parent.parent
            / "docs" / "operating_procedure.md").read_text(encoding="utf-8")

    assert tb.batt_level(None) is None, "FC khong bao phan tram thi KHONG duoc doan"
    # Thoi gian con lai theo dong dien, toi muc failsafe cua FC.
    # 3300 mAh, da xai 300, failsafe 660 (20%) -> con 2340 mAh; 10 A -> 842 s.
    r = tb.reserve_mah(3300, 0, 0)
    assert r == 660, f"LOW/CRT_MAH = 0 (FC that) phai lui ve 20%: {r}"
    assert tb.reserve_mah(3300, 800, 500) == 800, "co BATT_LOW_MAH thi lay no"
    assert tb.reserve_mah(3300, 0, 500) == 500
    assert tb.time_left_s(3300, 300, None, 660, 10.0) == 842, tb.time_left_s(3300, 300, None, 660, 10.0)
    assert tb.time_left_s(3300, None, 50, 660, 10.0) == 356, "khong co mAh thi tinh tu %"
    assert tb.time_left_s(None, 300, 90, 660, 10.0) is None, "khong biet dung luong thi KHONG doan"
    assert tb.time_left_s(3300, 300, 90, 660, 0.02) is None, "dong ~0 la nhieu, khong chia"
    assert tb.time_left_s(3300, 3000, 9, 660, 10.0) == 0, "qua muc failsafe phai la 0, khong am"
    assert [tb.left_level(s) for s in (None, 600, 180, 60, 0)] == \
        [None, None, "warn", "crit", "crit"]
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
    ft = flight()
    try:
        i18n.set_lang("vi")

        def feed(topic, data):
            REGISTRY.feed({"src": "sik", "topic": topic, "data": data, "ts": time.time()})

        def st(key):
            ft.refresh()
            return ft.state[key]

        # --- ARM: phai doc ra duoc, khong chi nam trong logic ---
        feed("heartbeat", {"armed": False, "mode": "STABILIZE"})
        assert st("armed") is False and st("fcMode") == "STABILIZE", ft.state
        feed("heartbeat", {"armed": True, "mode": "GUIDED"})
        assert st("armed") is True, ft.state

        # --- PIN: muc theo phan tram, KHONG theo dien ap ---
        # 16,8 V (4S day) va 11,1 V (3S can) cung bao 12% -> ca hai deu phai do.
        for volt in (16.8, 11.1):
            feed("battery", {"voltage": volt, "remaining": 12})
            assert st("battLevel") == "crit", f"{volt} V @12% ma khong do: {st('battLevel')}"
            assert st("volt") == volt, st("volt")
        feed("battery", {"voltage": 11.1, "remaining": 25})
        assert st("battLevel") == "warn", st("battLevel")
        # 11,1 V voi mot pack 3S la gan can, voi pack 6S la chet han — nhung FC bao
        # 80% thi day la pack 3S dang khoe. Dung dien ap lam nguong la sai o day.
        feed("battery", {"voltage": 11.1, "remaining": 80})
        assert st("battLevel") == "ok", st("battLevel")

        # FC khong bao phan tram -> KHONG bia ra nguong. Registry co y BO QUA gia tri
        # None (field.py:65) nen khong the "gui None" de xoa cai da biet — phai bo
        # han field di, dung nhu chua tung nhan.
        REGISTRY.fields.pop("battery.remaining", None)
        feed("battery", {"voltage": 11.1})
        assert st("battPct") is None and st("battLevel") == "ok", ft.state
        # FC cam USB, KHONG pin: do that 10/10/2026 tren logs/20261010-170756-real.tlog
        # — 0,017 V ma FC bao 98% (dem coulomb tu luc khoi dong). Khong duoc hien 98%.
        feed("battery", {"voltage": 0.017, "remaining": 98})
        assert st("battPct") is None and st("volt") == 0.017, "khong cam pin ma van hien 98%"

        # --- GPS: muc theo fix_type, KHONG theo so ve tinh ---
        # Do that tren ban: fix_type=1, sats=0. Truoc day hien so 0 trang tinh.
        feed("gps", {"fix_type": 1, "sats": 0})
        assert st("sats") == 0 and st("gpsLevel") == "crit", ft.state
        feed("gps", {"fix_type": 2, "sats": 12})
        assert st("gpsLevel") == "warn", "2D fix (khong co do cao GPS) ma khong canh bao"
        # 12 ve tinh voi 3D fix moi la binh thuong; so ve tinh mot minh khong quyet dinh
        feed("gps", {"fix_type": 3, "sats": 12})
        assert st("gpsLevel") == "ok", st("gpsLevel")
    finally:
        i18n.set_lang(was)
        REGISTRY.fields.clear()
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
        # Mo o man bay (cam ung), khong phai bang 350 hang field.
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

        # Het cua so cho thi quay lai chan tu dau, khong "da hoi mot lan roi thoi".
        # Phai nap lai `armed`: lan dong vua roi da chay that qua `disconnect()`, ma
        # ngat ket noi thi xoa sach so lieu cua chuyen cu (xem Backend.attach) —
        # ngoai doi so khong bao gio mo lai dung cua so do, o day thi co.
        REGISTRY.feed({"src": "sik", "topic": "heartbeat", "data": {"armed": True},
                       "ts": time.time()})
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

    was = i18n.lang()
    try:
        i18n.set_lang("vi")
        ft = flight(600, 400)
        assert ft.map._home_note() == "", "chua co home ma da bao khoang cach"

        # 0,001 do vi do = 111,3 m. Dung con so nay lam thuoc do.
        home = (10.8221589, 106.6868454)
        bus.emit("sik", "home", {"lat": home[0], "lon": home[1], "alt_msl": 10.1})
        assert ft.map._home_note() == "", "co home nhung chua co vi tri drone"
        # Vi tri drone di qua REGISTRY roi moi vao map (Backend.refresh), khong
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

    was = i18n.lang()
    try:
        i18n.set_lang("vi")

        # --- D.6 + muc F: dai chu duoi ban do ---
        ft = flight(600, 400)
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
        ft = flight(600, 400)
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


def check_mavlink2_upgrade(app):
    """Thay khung MAVLink2 dau tien thi chieu GUI phai nang len v2.

    Do that 23/08/2026 tren MicoAir743 qua USB: pymavlink giu nguyen "1.0" sau
    292 goi v2 lien tiep vi `auto_mavlink_version()` chi soi khi mieng byte doc
    duoc bat dau bang byte mo dau — cam vao giua luong thi khong bao gio dung luc.
    Hau qua: `mission_type` (truong mo rong cua v2) ném TypeError, va app do loi
    cho FC — "dang o MAVLink1" — trong khi 496/496 khung deu la 0xFD.
    """
    from pymavlink import mavutil

    from core.adapters.sik import _upgrade_v2

    class FakeMsg:
        def __init__(self, magic):
            self._buf = bytes([magic]) + b"\x00" * 9

        def get_msgbuf(self):
            return self._buf

    class FakeMaster:
        def __init__(self):
            self.WIRE_PROTOCOL_VERSION = "1.0"
            self.calls = []

        def auto_mavlink_version(self, buf):
            self.calls.append(buf[0])
            self.WIRE_PROTOCOL_VERSION = "2.0"

    m = FakeMaster()
    _upgrade_v2(m, FakeMsg(0xFE))  # khung v1: KHONG duoc nang, FC co the chi doc v1
    assert m.WIRE_PROTOCOL_VERSION == "1.0" and not m.calls, m.calls
    _upgrade_v2(m, FakeMsg(0xFD))
    assert m.WIRE_PROTOCOL_VERSION == "2.0" and m.calls == [0xFD], m.calls
    _upgrade_v2(m, FakeMsg(0xFD))  # da v2 roi thi thoi, khong dung lai moi goi
    assert m.calls == [0xFD], m.calls

    # Va tren mot ket noi pymavlink THAT: sau khi nang, `mission_type` phai goi
    # duoc. Day moi la thu ma tab Bay can de doc rao da giac.
    real = mavutil.mavlink_connection("udp:127.0.0.1:15999", source_system=254)
    try:
        if real.WIRE_PROTOCOL_VERSION != "2.0":
            try:
                real.mav.mission_request_list_send(1, 1, mission_type=1)
                raise AssertionError("v1 ma da goi duoc mission_type — bai test sai cho")
            except TypeError:
                pass
        _upgrade_v2(real, FakeMsg(0xFD))
        assert real.WIRE_PROTOCOL_VERSION == "2.0", real.WIRE_PROTOCOL_VERSION
        real.mav.mission_request_list_send(1, 1, mission_type=1)  # khong duoc ném
    finally:
        real.close()
    print("  ok  nang MAVLink2 khi FC noi v2: goi duoc mission_type (doc rao da giac); "
          "khung v1 thi giu nguyen v1")


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

    from core import i18n, logdata
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

    from PySide6.QtCore import Qt

    def tick(text, on=True):
        """Bam o tick cua mot field, y nhu nguoi dung."""
        for i in range(tab.fields.count()):
            it = tab.fields.item(i)
            if it.text() == text:
                it.setCheckState(Qt.Checked if on else Qt.Unchecked)
                app.processEvents()
                return it
        raise AssertionError(f"khong thay field {text} trong danh sach")

    name = with_fix.names()[0]
    tick(name)
    assert len(tab.chart.series()) == 1, "tick mot field ma khong ra mot duong"

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
    # --- 3b. Nhieu do thi: moi cai mot danh sach field RIENG -----------------
    # Ca cai dat de hong nhat cua tinh nang nay: tick vao do thi nay lai hien ra
    # o do thi kia. Do la ly do co vien sang, va la ly do phep thu duoi day do
    # tung do thi mot chu khong chi dem tong so duong.
    tab.norm.setChecked(False)
    app.processEvents()
    assert len(tab.plots) == 1, "mo tab ra ma khong co san mot do thi"
    one = tab.plot
    tab.add_plot()
    app.processEvents()
    two = tab.plot
    assert two is not one, "them do thi ma cai moi khong duoc chon"
    assert len(one.picked) == 1 and not two.picked, (one.picked, two.picked)
    # O tick phai the hien do thi VUA chon, khong phai cai cu.
    assert all(tab.fields.item(i).checkState() == Qt.Unchecked
               for i in range(tab.fields.count())), "o tick con giu field cua do thi cu"

    other = [n for n in with_fix.names() if n != name][:2]
    for n in other:
        tick(n)
    assert two.picked == other, two.picked
    assert one.picked == [name], f"tick vao do thi 2 lam doi do thi 1: {one.picked}"
    assert len(one.chart.series()) == 1 and len(two.chart.series()) == 2

    # Tran duong: tick qua MAX_SERIES phai BO TICK lai va noi ra, khong duoc am
    # tham nuot — nuot thi nguoi dung tuong minh bam hut roi bam mai.
    from laptop.tabs.analysis import MAX_PLOTS, MAX_SERIES
    spare = [n for n in with_fix.names() if n not in two.picked][:MAX_SERIES]
    for n in spare:
        tick(n)
    assert len(two.picked) == MAX_SERIES, two.picked
    it = tick(spare[-1] if len(spare) < MAX_SERIES else
              [n for n in with_fix.names() if n not in two.picked][0])
    assert it.checkState() == Qt.Unchecked, "tick qua tran ma o tick van sang"
    assert len(two.picked) == MAX_SERIES, "tran duong khong chan duoc"
    assert str(MAX_SERIES) in tab.where.text(), f"tran duong ma khong noi gi: {tab.where.text()}"

    # Bo tick thi duong phai bien mat khoi dung do thi do.
    tick(two.picked[0], on=False)
    assert len(two.picked) == MAX_SERIES - 1
    assert len(one.chart.series()) == 1, "bo tick o do thi 2 lam mat duong cua do thi 1"

    # Tran so do thi, va luon con lai it nhat mot cai.
    for _ in range(MAX_PLOTS + 3):
        tab.add_plot()
    app.processEvents()
    assert len(tab.plots) == MAX_PLOTS, len(tab.plots)
    assert not tab.btn_add.isEnabled(), "day tran roi ma nut them van bam duoc"
    for _ in range(MAX_PLOTS + 3):
        tab.del_plot()
    app.processEvents()
    assert len(tab.plots) == 1, "bot het sach do thi"
    assert not tab.btn_del.isEnabled(), "con mot do thi ma nut bot van bam duoc"
    assert tab.plot is tab.plots[0] and tab.plot.picked == [name], tab.plot.picked

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

    # Bang stream phai bam theo bang thong THAT cua duong, khong theo baud: khuon
    # "SiK radio" ep baud 57600 cho moi cong quet ra, ke ca cong CDC cua FC von
    # bo qua baud hoan toan. Doan nham theo huong nhanh = lam nghen mot duong
    # radio giua chuyen bay, nen chua biet chac thi phai giu bang HEP.
    from pymavlink import mavutil

    from core.adapters.sik import STREAMS, STREAMS_FAST, stream_table
    hz = dict(STREAMS)
    hz_fast = dict(STREAMS_FAST)
    extra1 = mavutil.mavlink.MAV_DATA_STREAM_EXTRA1
    assert hz_fast[extra1] > hz[extra1], "bang nhanh khong nhanh hon bang hep"
    usb = {"mode": "REAL", "conn": "/dev/ttyACM0", "baud": 57600, "bridge": False}
    sik = {"mode": "REAL", "conn": "/dev/ttyUSB0", "baud": 57600, "bridge": True}
    assert stream_table(usb) is STREAMS_FAST, "cong CDC cua FC van bi bop theo ngan sach SiK"
    assert stream_table(sik) is STREAMS, "radio SiK bi xin stream nhanh -> nghen duong"
    assert stream_table({"mode": "SIM", "conn": "tcp:127.0.0.1:5763"}) is STREAMS_FAST
    assert stream_table({"mode": "REAL", "conn": "/dev/ttyS0"}) is STREAMS, (
        "cong serial chua ro loai ma da xin nhanh")
    assert stream_table({"mode": "REPLAY", "path": "x.tlog"}) is STREAMS
    # Radio SiK cam OTG vao dien thoai toi app qua TCP noi bo — van la radio.
    assert stream_table({"mode": "REAL", "conn": "tcp:127.0.0.1:5760", "bridge": True}) is STREAMS, (
        "cau OTG tcp: bi coi la SITL -> xin stream nhanh, nghen radio 57600")

    # Quet cong phai mang co `bridge` sang profile, khong thi stream_table() mu.
    from laptop.connection import detect_serial
    for prof in detect_serial({"baud": 57600, "sysid": 254}):
        assert "bridge" in prof, f"profile quet ra thieu co bridge: {prof['name']}"

    # --- 4. Che do TRUC TIEP: cung bo do thi, nguon la bus dang chay ---------
    # Kiem lop LiveData truoc, khong qua giao dien: cua so truot va dong ho lui
    # la hai cho de hong nhat, ma ca hai deu do duoc bang so.
    live = logdata.LiveData(window=10.0)
    base = time.time()
    for i in range(300):  # 30 giay o 10 Hz, cua so 10 giay
        bus_env = {"src": "sik", "topic": "status", "ts": base + i * 0.1,
                   "data": {"VFR_HUD.alt": float(i),
                            "VFR_HUD.time_boot_ms": i * 100,  # phai bi bo qua
                            "SENSOR.gps": "ok",               # chuoi, phai bi bo qua
                            "GLOBAL_POSITION_INT.lat": int((10.762 + i * 1e-5) * 1e7),
                            "GLOBAL_POSITION_INT.lon": int(106.66 * 1e7),
                            "GLOBAL_POSITION_INT.relative_alt": i * 100}}
        live.feed(bus_env)
    live.trim()

    ts, vs = live.series("VFR_HUD.alt")
    assert ts, "truc tiep khong giu duoc field nao"
    span = ts[-1] - ts[0]
    assert 9.0 <= span <= 11.0, f"cua so truot sai: giu {span:.1f}s, cho ~10s"
    assert vs[-1] == 299.0, f"diem moi nhat khong phai diem cuoi: {vs[-1]}"
    assert "VFR_HUD.time_boot_ms" not in live.names(), "dau thoi gian lot vao danh sach ve"
    assert "SENSOR.gps" not in live.names(), "field chuoi lot vao danh sach ve"
    assert live.track and live.track[0][0] >= span - 0.2, "quy dao khong bi cat theo cua so"
    assert len(live.local_track()[1]) > 50, "truc tiep khong ra duoc quy dao"

    # Nhip goi: hoi hai lan sat nhau phai ra cung mot so. Hoi hai lan trong mot
    # khung hinh (ve lai + doi ngon ngu) tung lam cua so do bang ~0 va man hinh
    # bao "0 goi/s" mau canh bao trong luc FC van dang gui deu.
    live._rate_mark = (time.monotonic() - 1.0, 0, 0.0)
    hz1 = live.rate()
    assert hz1 > 0, f"nhan 300 goi ma bao {hz1} goi/s"
    assert live.rate() == hz1, "hoi hai lan sat nhau ra hai so khac nhau"

    # Dong ho FC va dong ho laptop khong dong bo: goi den muon hon goi truoc thi
    # thoi gian lui lai. Chuoi lui thi bisect trong trim() cat nham va do thi ve
    # nguoc — phai kep lai chu khong duoc tin dau thoi gian.
    live.feed({"src": "sik", "topic": "status", "ts": base - 5.0,
               "data": {"VFR_HUD.alt": 1000.0}})
    ts, _ = live.series("VFR_HUD.alt")
    assert all(a <= b for a, b in zip(ts, ts[1:])), "dong ho lui lam chuoi thoi gian lui theo"

    # Qua giao dien: bat cong tac, bom vai goi qua bus THAT, roi doi mot nhip.
    tab._loaded(with_fix)
    app.processEvents()
    tab.live.setChecked(True)
    now = time.time()
    for i in range(40):
        bus.emit("sik", "status", {"VFR_HUD.alt": float(i % 7)}, ts=now + i * 0.1)
    tab.plot.picked = ["VFR_HUD.alt"]
    tab._live_tick()
    app.processEvents()
    assert "VFR_HUD.alt" in tab.src.names(), "goi tren bus khong toi duoc tab Phan tich"
    assert len(tab.chart.series()) == 1, "che do truc tiep khong ve ra duong nao"
    # `t` o day la bien cuc bo cua phep thu quy dao ben tren, khong phai i18n.t
    assert tab.summary.text() != i18n.t("an.nothing"), "truc tiep ma van bao chua doc log"

    # Doc mot file thi phai QUAY VE file do — bam "Doc log" la muon xem cai file
    # vua chon, khong phai ngoi nhin do thi dang chay.
    tab._loaded(with_fix)
    app.processEvents()
    assert not tab.live.isChecked(), "doc log xong ma van ket o che do truc tiep"
    assert tab.src is with_fix, "doc log xong ma nguon ve khong phai file vua doc"

    tab.close()
    print(f"  ok  tab Phan tich: {len(with_fix.fields)} field tu .tlog, PARAM tach theo "
          "ten, diem lat=lon=0 bi loc, bo loc khong lam mat duong dang ve, log "
          "khong fix va file khong doc duoc noi ra hai cau khac nhau; che do truc "
          f"tiep giu {span:.0f}s gan nhat tu bus va khong bi dong ho lui lam hong; "
          f"toi {MAX_PLOTS} do thi, moi cai mot danh sach tick rieng, tran "
          f"{MAX_SERIES} duong chan duoc va noi ra")


def _make_bin():
    """Ghi mot .bin dataflash tam: OF (quang luu) + POS (vi tri), gia tri biet truoc.

    Khong lay file that trong Downloads/ hay tren the SD: phep thu phai chay duoc
    tren may chua bao gio cam FC vao. Ma dinh dang .bin thi tu ghi duoc — no chi
    la 0xA3 0x95 <kieu> <than>, kem may ban ghi FMT khai bao truoc cac kieu do.

    Vi sao ghi that chu khong gia lap DFMessage: cai de vo nhat khong phai logic
    cua minh ma la duong `mavutil.mavlink_connection()` -> DFReader_binary. Doi
    ban pymavlink ma duong do doi thi chi mot file that moi bat duoc.
    """
    import struct
    import tempfile

    HEAD = b"\xa3\x95"
    FMT_TYPE = 0x80

    def fmt_rec(typ, length, name, fmt, cols):
        return HEAD + bytes([FMT_TYPE]) + struct.pack(
            "<BB4s16s64s", typ, length, name.encode(), fmt.encode(), cols.encode())

    OF_T, POS_T, ATT_T, GPS_T, BAT_T, MODE_T, ARM_T, MSG_T, ORGN_T, PARM_T = range(10, 20)
    path = Path(tempfile.mkdtemp()) / "quangluu.bin"
    with open(path, "wb") as f:
        # FMT ta chinh no truoc: 3 byte dau + B+B+4+16+64 = 89
        f.write(fmt_rec(FMT_TYPE, 89, "FMT", "BBnNZ", "Type,Length,Name,Format,Columns"))
        # Do dai = 3 byte dau + than. L = int32 nhan 1e-7, Z = chuoi 64 byte.
        f.write(fmt_rec(OF_T, 28, "OF", "QBffff", "TimeUS,Qual,flowX,flowY,bodyX,bodyY"))
        f.write(fmt_rec(POS_T, 31, "POS", "QLLfff",
                        "TimeUS,Lat,Lng,Alt,RelHomeAlt,RelOriginAlt"))
        f.write(fmt_rec(ATT_T, 36, "ATT", "QffffffB",
                        "TimeUS,DesRoll,Roll,DesPitch,Pitch,DesYaw,Yaw,AEKF"))
        # GWk/GMS bat buoc phai co: DFReader dung hai truong nay de dung DONG HO
        # cua ca file (_find_time_base). Thieu chung thi _set_time() nhan voi None
        # va MOI ban ghi phia sau ra "bad msg" — file van doc duoc mot phan, nen
        # kieu hong nay rat de tuong la binh thuong.
        f.write(fmt_rec(GPS_T, 39, "GPS", "QBIHBfLLff",
                        "TimeUS,Status,GMS,GWk,NSats,HDop,Lat,Lng,Alt,Spd"))
        f.write(fmt_rec(BAT_T, 21, "BAT", "QBffB", "TimeUS,Inst,Volt,Curr,RemPct"))
        f.write(fmt_rec(MODE_T, 14, "MODE", "QBBB", "TimeUS,Mode,ModeNum,Rsn"))
        f.write(fmt_rec(ARM_T, 15, "ARM", "QBBBB",
                        "TimeUS,ArmState,ArmChecks,Forced,Method"))
        f.write(fmt_rec(MSG_T, 75, "MSG", "QZ", "TimeUS,Message"))
        f.write(fmt_rec(ORGN_T, 24, "ORGN", "QBLLf", "TimeUS,Type,Lat,Lng,Alt"))
        # N = char[16]: ten tham so nam TRONG ban ghi, khong phai mot ma so
        f.write(fmt_rec(PARM_T, 35, "PARM", "QNff", "TimeUS,Name,Value,Default"))

        lat0, lon0 = int(10.7620 * 1e7), int(106.6600 * 1e7)
        # MODE 4 = GUIDED, ARM 1 = da arm. Dat o dau file nhu FC that.
        f.write(HEAD + bytes([MSG_T]) + struct.pack("<QZ".replace("Z", "64s"),
                0, b"ArduCopter V4.6.3 (selfcheck)"))
        f.write(HEAD + bytes([ORGN_T]) + struct.pack("<QBiif", 0, 1, lat0, lon0, 100.0))
        f.write(HEAD + bytes([MODE_T]) + struct.pack("<QBBB", 0, 4, 4, 2))
        f.write(HEAD + bytes([ARM_T]) + struct.pack("<QBBBB", 0, 1, 1, 0, 1))
        for nm, val in (("WP_SPD", 500.0), ("RTL_ALT_M", 15.0)):
            f.write(HEAD + bytes([PARM_T]) + struct.pack(
                "<Q16sff", 0, nm.encode(), val, val))
        for i in range(300):
            # 200 Hz: phat lai bam dung nhip goc, thua ra thi phep thu ngoi ngu.
            us = int(i * 5_000)
            # bodyX chay hinh rang cua trong [-1, 1] — de con doi chieu bien do
            body = (i % 100) / 50.0 - 1.0
            f.write(HEAD + bytes([OF_T]) + struct.pack(
                "<QBffff", us, 128, body * 2, -body, body, body / 2))
            # ATT ghi bang DO (dataflash), khong phai radian
            f.write(HEAD + bytes([ATT_T]) + struct.pack(
                "<QffffffB", us, 0.0, 30.0, 0.0, -15.0, 90.0, 90.0, 1))
            if i % 5 == 0:  # POS/GPS/BAT 40 Hz, di thang ve huong dong
                f.write(HEAD + bytes([POS_T]) + struct.pack(
                    "<QLLfff", us, lat0, lon0 + i * 900, 100.0, i * 0.1, i * 0.1))
                f.write(HEAD + bytes([GPS_T]) + struct.pack(
                    "<QBIHBfiiff", us, 3, 400_000_000 + us // 1000, 2300,
                    12, 0.9, lat0, lon0 + i * 900, 100.0, 4.5))
                f.write(HEAD + bytes([BAT_T]) + struct.pack(
                    "<QBffB", us, 0, 12.6, 8.0, 77))
    return path


def check_log_download(app):
    """Keo mot log .bin tu FC ve qua MAVLink, co lam rot mot khoi giua duong.

    Kiem dung cai de hong nhat: mot khoi 90 byte rot o giua. Khong co bang
    `have` thi phan sau khoi do hoac bi vut di (tai lai tu dau — 45 phut nua qua
    SiK), hoac bi ghi lech mot khoi va ca file thanh rac ma van bao "xong".

    FC gia o day tra loi dung ba goi cua giao thuc: LOG_ENTRY, LOG_DATA,
    LOG_REQUEST_END. Khong gia lap SikAdapter — cai de vo la doan ghep file lai
    tu cac manh den khong dung thu tu.
    """
    import random
    import tempfile

    from PySide6.QtCore import QTimer
    from pymavlink import mavutil

    from core.adapters.sik import LOG_BLOCK

    port = 14563
    blob = random.Random(7).randbytes(200 * LOG_BLOCK + 37)  # khoi cuoi le 37 byte
    DROP = 10  # khoi FC "danh roi" o luot dau
    served = {"passes": 0, "ended": False}
    stop = threading.Event()

    def fc():
        out = mavutil.mavlink_connection(f"udpout:127.0.0.1:{port}", source_system=1)
        last_beat = 0.0
        while not stop.is_set():
            now = time.time()
            if now - last_beat > 0.2:
                last_beat = now
                out.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                       mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                                       0, 0, 0)
            msg = out.recv_match(blocking=False)
            if msg is None:
                time.sleep(0.01)
                continue
            name = msg.get_type()
            if name == "LOG_REQUEST_LIST":
                out.mav.log_entry_send(1, 1, 1, 0, len(blob))
            elif name == "LOG_REQUEST_END":
                served["ended"] = True
            elif name == "LOG_REQUEST_DATA":
                served["passes"] += 1
                first = served["passes"] == 1
                ofs = msg.ofs
                while ofs < len(blob) and not stop.is_set():
                    idx = ofs // LOG_BLOCK
                    chunk = blob[ofs:ofs + LOG_BLOCK]
                    if not (first and idx == DROP):
                        out.mav.log_data_send(
                            1, ofs, len(chunk),
                            list(chunk) + [0] * (LOG_BLOCK - len(chunk)))
                    ofs += LOG_BLOCK
                    if idx % 20 == 0:
                        time.sleep(0.01)  # dung lam ngheo socket phia nhan

    logdir = Path(tempfile.mkdtemp())
    adapter = SikAdapter({"name": "selfcheck", "mode": "SIM",
                          "conn": f"udp:127.0.0.1:{port}"}, logdir=logdir)
    done = []
    listed = []
    adapter.envelope.connect(
        lambda e: (listed.append(e["data"]["list"]) if "list" in e["data"]
                   else done.append(e["data"]["get"]) if e["data"].get("get", {}).get("done")
                   else None) if e["topic"] == "log" else None)
    adapter.envelope.connect(lambda e: app.quit() if done else None)
    adapter.start()
    threading.Thread(target=fc, daemon=True).start()

    # Doi heartbeat dau tien (co target_system) roi hoi danh sach log
    QTimer.singleShot(800, lambda: adapter.send("log_list", {}))
    QTimer.singleShot(1600, lambda: adapter.send(
        "log_get", {"id": 1, "size": len(blob)}))
    guard = deadline(app, 20000)
    app.exec()
    guard.stop()
    # LOG_REQUEST_END di sau goi cuoi vai mili giay; cho FC gia doc no roi moi
    # ha co, khong thi phep thu bao thieu trong khi app gui dung.
    for _ in range(100):
        if served["ended"]:
            break
        time.sleep(0.01)
    stop.set()
    adapter.stop()

    assert listed and listed[-1] and listed[-1][0]["size"] == len(blob), \
        f"danh sach log tu FC khong ve toi noi: {listed}"
    assert done, "khong nhan duoc bao tai xong (hay tai qua 20s)"
    g = done[-1]
    assert not g["err"], f"tai loi: {g['err']}"
    got = Path(g["path"]).read_bytes()
    assert got == blob, \
        f"file tai ve khac ban goc: {len(got)}/{len(blob)} byte, giong nhau den byte {next((i for i, (a, b) in enumerate(zip(got, blob)) if a != b), len(got))}"
    assert served["passes"] >= 2, \
        "FC chi phuc vu mot luot — phep thu khong he lam rot khoi nao"
    assert served["ended"], "tai xong ma khong bao LOG_REQUEST_END: FC se bom tiep"

    # LOG_DATA khong duoc do vao bang Trang thai (90 hang moi goi) hay vao do thi
    from core import logdata as _ld
    from core.adapters.sik import flatten_status as _fs
    assert _fs("LOG_DATA", {"id": 1, "ofs": 0, "count": 90, "data": [1] * 90}) == {}, \
        "LOG_DATA do vao bang Trang thai"

    class _M:  # goi MAVLink gia: co get_srcComponent nhu that
        def get_srcComponent(self):
            return 1

        def get_srcSystem(self):
            return 1

    assert not _ld._wanted(_M(), "LOG_DATA"), "LOG_DATA lot vao do thi tab Phan tich"

    # --- hop thoai tai log KHONG duoc chan cua so chinh -----------------------
    # Do that 04/10/2026: mo bang exec() (modal) thi bam chuot vao RTL khong an gi
    # suot ca phien tai (~45 phut qua SiK), nut van bao isEnabled() = True. Bam qua
    # QWindow (duong cua he cua so, bi chan modal nhu chuot that): bam thang vao
    # QWidget thi QTest di vong qua bo chan, bai nay xanh oan.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from core import authority
    from laptop.app import MainWindow
    sent = []

    class _Fake:
        mode = "SIM"

        def send(self, action, args=None):
            sent.append(action)
            return {"ok": action}

    fake = _Fake()
    win = MainWindow([])
    win.show()
    authority.register("sik", fake)
    try:
        win.control_tab.set_mode("SIM")
        win.analysis_tab.attach(fake)
        win.ui.tabWidget.setCurrentWidget(win.ui.Control)
        app.processEvents()
        win.analysis_tab._from_fc()
        app.processEvents()
        assert app.activeModalWidget() is None, "hop thoai tai log chan ca cua so chinh"
        sent.clear()
        b = win.control_tab.btn_rtl
        QTest.mouseClick(win.windowHandle(), Qt.LeftButton, Qt.NoModifier,
                         b.mapTo(win, b.rect().center()))
        app.processEvents()
        assert sent == ["rtl"], f"dang mo hop thoai tai log ma nut RTL khong an: {sent}"
        win.analysis_tab.attach(None)  # ngat ket noi: hop thoai phai tu dong
        assert not win.analysis_tab._fc_dlg.isVisible(), "ngat roi ma hop thoai van mo"
    finally:
        authority.unregister("sik")
        win.close()

    print(f"  ok  tai log .bin tu FC qua MAVLink: {len(blob)} byte khop tung byte, "
          f"khoi {DROP} bi roi duoc hoi lai ({served['passes']} luot), co LOG_REQUEST_END; "
          f"LOG_DATA khong do vao bang Trang thai/do thi; hop thoai tai khong chan nut do")


def check_bin_log(app):
    """Doc log dataflash .bin cua FC, giu nguyen ten ArduPilot (OF.bodyX, ATT.Roll).

    Vi sao phai co ca hai dinh dang: .tlog chi chua cai DA CHAY QUA SONG, ma
    duong SiK 57600 thi khong cho noi RATE/PID*/XKF*/OF o nhip vong lap. Muon
    nhin nhung cai do thi phai keo the SD ra, va cho toi truoc hom nay thi tab
    Phan tich tu choi thang: `from_autopilot()` goi `msg.get_srcComponent()`,
    DFMessage khong co ham do nen nem AttributeError ngay ban ghi dau — ca file
    bao "khong doc duoc log" trong khi no doc duoc tron ven.

    KHONG doi ten cho giong MAVLink: nguoi bay doc tai lieu ArduPilot song song
    voi do thi nay, doi ten la cat mat duong doi chieu do.
    """
    import math

    from core import i18n, logdata
    from laptop.tabs.analysis import AnalysisTab

    # --- 1. Bo loc nguon: goi MAVLink phai qua from_autopilot, ban ghi .bin thi khong ---
    class FakeDF:  # DFMessage: co get_type/to_dict, KHONG co get_srcComponent
        def get_type(self):
            return "OF"

    assert logdata._wanted(FakeDF(), "OF"), \
        "ban ghi .bin bi loc mat — day dung la loi AttributeError cu"
    assert not logdata._wanted(FakeDF(), "BAD_DATA"), "BAD_DATA lot qua bo loc"
    assert not logdata._wanted(FakeDF(), "UNKNOWN_42"), "UNKNOWN_* lot qua bo loc"

    # --- 2. Doc that mot file .bin ---
    log = logdata.load(_make_bin())
    assert log.parsed > 300, f".bin chi doc ra {log.parsed} ban ghi"

    names = set(log.names())
    for want in ("OF.bodyX", "OF.bodyY", "OF.flowX", "OF.Qual"):
        assert want in names, f"thieu {want} — ten ArduPilot bi doi hoac bi nuot"
    assert "OF.TimeUS" not in names, "TimeUS vao do thi: no la dau thoi gian, ve ra mot duong doc"

    ts, vs = log.series("OF.bodyX")
    assert len(ts) == 300, f"OF.bodyX co {len(ts)} diem, cho 300"
    assert -1.05 < min(vs) < -0.95 and 0.95 < max(vs) < 1.05, \
        f"OF.bodyX bien do sai: [{min(vs):.3g} .. {max(vs):.3g}], cho [-1 .. 1]"

    # Tham so tach theo TEN. .bin goi la PARM chu khong PARAM_VALUE: do that tren
    # log 13 MB o Downloads, de mac dinh thi 1078 tham so do chung vao mot duong
    # "PARM.Value" nhay lung tung, dung cai ma nhanh PARAM_VALUE sinh ra de tranh.
    assert "PARAM.WP_SPD" in names and "PARAM.RTL_ALT_M" in names, \
        "PARM cua .bin khong tach theo ten tham so"
    assert "PARM.Value" not in names, "PARM.Value gop chung moi tham so vao mot duong"
    assert log.series("PARAM.WP_SPD")[1] == [500.0], "PARM.Value doc ra sai gia tri"

    # --- 3. POS -> quy dao 3D (GLOBAL_POSITION_INT khong co trong .bin) ---
    assert log.has_fix, "POS co toa do that ma has_fix van bao khong"
    _, e, n, u = log.local_track()
    assert len(e) == 60, f"quy dao tu POS ra {len(e)} diem, cho 60"
    assert max(e) > 500, f"POS di thang dong 900e-7 do x 60 ma be ngang chi {max(e):.0f} m"
    assert abs(max(n)) < 5, "POS khong doi vi do ma quy dao lai lech bac"

    # --- 4. Ca hai hop thoai deu nhan .bin ---
    assert ".bin" in i18n.t("an.log_filter"), "hop thoai tab Phan tich khong nhan .bin"
    assert ".bin" in i18n.t("conn.tlog_filter"), "hop thoai REPLAY khong nhan .bin"

    # --- 5. Bang dich dataflash -> topic, kiem tung cai mot ---
    from core.adapters.sik import normalize_df

    att = dict(normalize_df("ATT", {"Roll": 30.0, "Pitch": -15.0, "Yaw": 90.0}))
    assert abs(att["attitude"]["roll"] - math.radians(30.0)) < 1e-9, \
        "ATT.Roll khong doi tu DO sang RADIAN — chan troi se nam ngang o moi tu the"
    assert abs(att["attitude"]["pitch"] - math.radians(-15.0)) < 1e-9
    assert abs(att["attitude"]["heading"] - 90.0) < 1e-6, "heading phai giu don vi DO"

    gps = dict(normalize_df("GPS", {"Status": 3, "NSats": 12, "HDop": 0.9, "Spd": 4.5}))
    assert gps["gps"] == {"fix_type": 3, "sats": 12, "hdop": 0.9}
    assert gps["vfr"]["groundspeed"] == 4.5, "GPS phai nuoi ca toc do mat dat"

    assert dict(normalize_df("ARM", {"ArmState": 1}))["heartbeat"]["armed"] is True
    assert dict(normalize_df("ARM", {"ArmState": 0}))["heartbeat"]["armed"] is False
    assert dict(normalize_df("MODE", {"Mode": 4}))["heartbeat"]["mode"] == "GUIDED"
    assert normalize_df("BAT", {"Inst": 1, "Volt": 9.9}) == [], \
        "pin thu hai lot vao: dai chu se nhay qua lai giua hai dien ap"
    assert normalize_df("RATE", {"R": 1.0}) == [], "message la ma van sinh topic"

    # --- 6. Phat lai THAT mot .bin qua SikAdapter ---
    # Day moi la phep thu co gia tri: no di qua dung vong lap ma ngay bay that
    # dung, ke ca cho DFReader.recv_match() KHONG nhan tham so `timeout` — truyen
    # vao la TypeError ngay ban ghi dau va ca phien chet im lang.
    from core import bus
    from core.adapters.sik import SikAdapter
    from core.field import REGISTRY

    # bus giu subscriber o bien module-level, va cac phep thu phia truoc dang ky
    # widget cua chung vao "*" roi dong widget ma khong go dang ky. Ban 800
    # envelope qua do la goi vao mot dam QObject da chet — tien trinh segfault
    # ngay trong processEvents(), khong kem mot dong Python nao.
    #
    # Trong app that khong co chuyen do: widget dang ky mot lan luc khoi dong va
    # song bang doi cua tien trinh. Day thuan tuy la ve sinh cua bo kiem tra, nen
    # phep thu nay muon mot bus SACH rieng cho no roi tra lai nguyen trang.
    saved_subs = dict(bus._subs)
    bus._subs.clear()

    got, failed = {}, []
    tap = lambda env: got.__setitem__(env["topic"], got.get(env["topic"], 0) + 1)
    bus.on("*", tap)
    bus.on("*", REGISTRY.feed)

    a = SikAdapter({"name": "bin", "mode": "REPLAY", "path": str(_make_bin())},
                   logdir=None)
    a.envelope.connect(bus.emit_envelope)
    a.failed.connect(failed.append)
    a.start()
    t0 = time.time()
    while time.time() - t0 < 20 and a.isRunning():
        app.processEvents()
        time.sleep(0.01)
    a.stop()
    app.processEvents()
    bus._subs.clear()
    bus._subs.update(saved_subs)

    assert not failed, f"phat lai .bin bao loi: {failed}"
    for topic in ("attitude", "position", "gps", "battery", "heartbeat", "vfr", "home"):
        assert got.get(topic), f"phat lai .bin ma khong co topic {topic}: {got}"
    assert a.tlog is None, ".bin phat lai ma van ghi ra .tlog — file do khong ai doc duoc"

    # Dung 14 field nuoi giao dien phai co mat, khong thieu cai nao.
    for f in ("attitude.roll", "attitude.pitch", "attitude.heading",
              "position.lat", "position.lon", "position.alt_rel",
              "vfr.groundspeed", "battery.voltage", "battery.remaining",
              "gps.fix_type", "gps.sats", "gps.hdop",
              "heartbeat.armed", "heartbeat.mode"):
        assert REGISTRY.value(f) is not None, f"phat lai .bin ma {f} van trong"
    # .bin ghi MODE/ARM MOT lan luc doi, con Field het tuoi sau STALE=2s. Adapter
    # phai nhac lai moi giay giong HEARTBEAT that, neu khong nhan che do bay tat
    # ngom giua chuyen phat lai. Hai ban ghi nay nam o dau file, con vong phat lai
    # o tren chay vai giay — doc duoc tuc la da co nhac lai.
    assert REGISTRY.value("heartbeat.mode") == "GUIDED", \
        "che do bay het tuoi: .bin chi ghi MODE luc doi, adapter phai nhac lai"
    assert REGISTRY.value("heartbeat.armed") is True, "trang thai ARM het tuoi"

    # --- 5. Vao that trong tab ---
    tab = AnalysisTab()
    tab._loaded(log)
    app.processEvents()
    assert tab.src is log
    of = [n for n in tab.src.names() if n.startswith("OF.")]
    tab.close()

    print(f"  ok  log .bin cua FC: {len(names)} field giu nguyen ten ArduPilot "
          f"({', '.join(sorted(of))}), TimeUS bi loai, quy dao tu POS; REPLAY phat "
          f"lai duoc ({len(got)} topic), goc doi DO->RADIAN, 14 field nuoi giao dien "
          "deu co, khong ghi de ra .tlog")


def check_soak():
    """Nap giong luc khoi dong khong phai ro ri; van bat RAM tang sau do.

    Soak tu tao QApplication khi import. Lay dung ba ham do/ket luan cua no
    de dieu khien dong ho va RSS, khong can cho 30 phut cho moi duong loi.
    """
    import ast
    from types import SimpleNamespace
    from unittest.mock import Mock

    path = Path(__file__).with_name("soak.py")
    tree = ast.parse(path.read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in ("start", "sample", "done")]
    code = compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec")

    def run(growth=2.7, ticks=1200, silence=False):
        clock, rss = [0.0], [189.6]
        app, win = Mock(), Mock()
        win.banner.text.return_value = "SIM"
        n = dict(env=0, tick=0, last_env=0, quiet=False)
        ns = dict(time=SimpleNamespace(monotonic=lambda: clock[0], time=lambda: clock[0]),
                  rss_mb=lambda: rss[0], rss0=rss[0], t0=0.0, last_sample=0.0,
                  n=n, MINUTES=2, QTimer=Mock(), timer=Mock(), app=app, win=win,
                  print=lambda *a, **kw: None)
        exec(code, ns)
        clock[0], rss[0] = 60, 371.1
        if "start" in ns:
            ns["start"]()
        if silence:
            clock[0] = 120
            n.update(env=0, tick=600)
            ns["sample"]()
        clock[0], rss[0] = 180, 371.1 + growth
        n.update(env=70000, tick=ticks)
        ns["done"]()
        win.disconnect.assert_called_once()
        return app.exit.call_args.args[0]

    assert run() == 0, "RAM on dinh sau khoi dong ma soak bao ro ri"
    assert run(growth=75) == 1, "RAM tang sau khoi dong ma soak van PASS"
    assert run(ticks=100) == 1, "Qt treo ma soak van PASS"
    assert run(silence=True) == 1, "mat telemetry roi co lai ma soak van PASS"
    print("  ok  soak: tach RAM khoi dong; tang RAM, treo Qt, mat telemetry deu exit 1")


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    # Selfcheck KHONG duoc phat tieng that ra loa (va khong doc/ghi QSettings
    # cua nguoi dung cho viec nay): Voice van ghi vao `.spoken` de bai kiem doc.
    import laptop.voice
    laptop.voice.enabled = lambda: False
    check_normalize()
    check_join_text()
    check_source_filter()
    check_flatten()
    check_sensor_decode()
    check_bus()
    check_usb_detect(app)
    check_replug(app)
    check_link_status(app)
    check_video_h264(app)
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
    check_stream_rearm(app)
    check_replay(app)
    check_alt_no_home(app)
    check_slow_stop(app)
    check_tlog_roundtrip(app)
    check_dead_socket(app)
    check_banner_health(app)
    check_jetson_dot(app)
    check_adapter_live(app)
    check_dual_link(app)
    check_copy_tiles(app)
    check_video(app)
    check_i18n(app)
    check_param_doc(app)
    check_telemetry_warn(app)
    check_flight_alerts(app)
    check_close_guard(app)
    check_home_note(app)
    check_drone_marker(app)
    check_preflight_reads(app)
    check_fence_follows_fc(app)
    check_mavlink2_upgrade(app)
    check_analysis(app)
    check_bin_log(app)
    check_log_download(app)
    check_touch(app)
    check_touch_flight(app)
    check_soak()
    print("selfcheck: PASS")
