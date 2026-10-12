#!/usr/bin/env python3
"""Hai nua hong doc lap — tai hien dung hai trieu chung gap khi bay SITL:

  1. Link SiK chet nhung app van bao lenh "da gui"
  2. Mat mot nua thi app bao "mat ket noi" chung chung, va giet luon nua kia

Khong can SITL: dung nguon MAVLink gia va WebSocket server gia.

    python3 tools/check_halves.py
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from pymavlink import mavutil  # noqa: E402
from websockets.sync.server import serve  # noqa: E402

from core.i18n import t  # noqa: E402
from laptop.app import MainWindow  # noqa: E402

MAV_PORT, WS_PORT = 14571, 8791

app = QApplication([])
stop_mav = threading.Event()
stop_ws = threading.Event()


def mav_sender():
    out = mavutil.mavlink_connection(f"udpout:127.0.0.1:{MAV_PORT}", source_system=1)
    while not stop_mav.is_set():
        out.mav.heartbeat_send(2, 3, 0, 0, 4)
        out.mav.global_position_int_send(0, 107620000, 1066600000, 12000, 5000,
                                         0, 0, 0, 9000)
        time.sleep(0.1)


def ws_handler(ws):
    while not stop_ws.is_set():
        try:
            ws.send(json.dumps({"src": "remote", "topic": "position",
                                "data": {"lat": 10.762, "lon": 106.66}, "ts": time.time()}))
            time.sleep(0.1)
        except Exception:
            return


server = serve(ws_handler, "127.0.0.1", WS_PORT)
threading.Thread(target=server.serve_forever, daemon=True).start()
threading.Thread(target=mav_sender, daemon=True).start()

win = MainWindow([{"name": "hai nua", "mode": "SIM", "conn": f"udp:127.0.0.1:{MAV_PORT}",
                   "remote": f"ws://127.0.0.1:{WS_PORT}"}])
win.show()
assert win.panel.select("hai nua")
win.panel.btn_connect.click()
ct = win.control_tab
logs = []
# log = Signal(str, int): noi thang `logs.append` thi moi dong TypeError, `logs` rong.
ct.log.connect(lambda text, _sev: logs.append(text))


def step(fn):
    """Assert hong trong slot cua QTimer KHONG lam app dung: no chi in traceback
    roi app chay tiep toi han 45 s va thoat ma 0 — bai hong ma trong nhu qua. Bat
    o day de thoat ma 1."""
    def run():
        try:
            fn()
        except Exception:
            import traceback
            traceback.print_exc()
            print("check_halves: FAIL")
            win.disconnect()  # khong thi QThread adapter con chay luc thoat -> abort 134
            app.exit(1)
    return run


def step1():
    """Ca hai nua song."""
    assert "B/s" in win.link_status._info["sik"].text(), win.link_status._info["sik"].text()
    assert "B/s" in win.link_status._info["remote"].text()
    assert t("mode.SIM") in win.banner.text(), win.banner.text()
    print("  ok  hai nua song -> banner binh thuong")

    logs.clear()
    ct.btn_arm.click()
    assert logs[-1] == t("log.sent", what="arm"), logs
    print(f"  ok  link song -> \"{logs[-1]}\"")

    stop_ws.set()  # cat nua ROS2, giu nua SiK
    QTimer.singleShot(4000, step(step2))


def step2():
    """Kieu hong A: mat ROS2, SiK con. Tu khi laptop cam toan quyen, day la mat
    TAM NHIN (video, nguon vi tri thu hai) chu khong con la mat quyen lai."""
    print("  banner:", win.banner.text()[:78])
    assert t("conn.degraded") in win.banner.text(), win.banner.text()
    assert win.adapter is not None, "mat ROS2 KHONG duoc lam chet nua SiK"
    assert "B/s" in win.link_status._info["sik"].text(), "nua SiK phai con nguyen"

    logs.clear()
    ct.btn_rtl.click()
    assert logs[-1] == t("log.sent", what="RTL"), logs  # nut do van an
    print("  ok  mat ROS2 -> SiK con nguyen, nut do van an")

    stop_mav.set()  # cat not nua SiK
    QTimer.singleShot(4000, step(step3))


def step3():
    """Mat not SiK: mat duong cuu sinh."""
    print("  banner:", win.banner.text()[:78])
    lost = t("banner.lost", name="hai nua", why="")
    assert win.banner.text().startswith(lost.strip()), win.banner.text()

    logs.clear()
    ct.btn_rtl.click()
    stale = t("log.queued_stale", what="RTL", how="")
    assert logs[-1].endswith(stale.split("—")[-1].strip()), logs
    print(f"  ok  link chet -> \"{logs[-1]}\"")
    QTimer.singleShot(4000, step(step4))


def step4():
    """Khong co COMMAND_ACK nao ve -> phai canh bao, khong duoc im."""
    no_ack = t("log.no_ack", action="RTL", sec=3)
    assert no_ack in logs, logs
    print(f"  ok  khong co ack -> \"{no_ack}\"")
    print("check_halves: PASS")
    win.disconnect()
    win.close()
    server.shutdown()
    app.quit()


QTimer.singleShot(4000, step(step1))
QTimer.singleShot(45000, lambda: (print("check_halves: FAIL — qua 45 s"), app.exit(1)))
sys.exit(app.exec())
