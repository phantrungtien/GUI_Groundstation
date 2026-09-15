"""RemoteAdapter — WebSocket client toi companion.

Nhan envelope JSON tu companion (vision, SLAM, task ROS2) va gui lenh nguoc lai.
Laptop KHONG can cai ROS2: adapter nay chi noi WebSocket.

Nua nay phu thuoc companion 100%. Companion chet la khong con ROS2 nao ton tai
de ma dieu khien — do khong phai loi thiet ke. Nut do di duong SiK, khong di qua
day (nguyen tac 2.1).
"""

import json
import time

from PySide6.QtCore import QThread, Signal
from websockets.sync.client import connect

from core.adapters import join

RETRY_S = 2.0  # noi lai deu dan: WiFi ngoai bai bay rot len rot xuong la binh thuong


class RemoteAdapter(QThread):
    envelope = Signal(dict)
    failed = Signal(str)

    SRC = "remote"

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self._running = True
        self._ws = None
        # Mo phong rot WiFi (kich ban #1) ma khong phai tat WiFi that: WebSocket
        # van mo, chi la khong goi nao len toi app.
        self.muted = False

    def stop(self):
        self._running = False
        ws, self._ws = self._ws, None
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        join(self)  # connect() toi Pi mat WiFi treo toi open_timeout, sat nut 3 s

    def _emit(self, topic, data, ts=None):
        if self.muted:
            return  # dang mo phong rot WiFi — xem self.muted
        self.envelope.emit(
            {"src": self.SRC, "topic": topic, "data": data, "ts": ts or time.time()}
        )

    def send(self, action, args=None):
        """Goi tu main thread. websockets.sync co khoa rieng nen ghi duoc tu ngoai."""
        ws = self._ws
        if ws is None:
            return {"error": "chua noi duoc companion"}
        try:
            ws.send(json.dumps({"action": action, "args": args or {}}))
            return {"ok": action}
        except Exception as e:
            return {"error": str(e)}

    def run(self):
        while self._running:
            try:
                with connect(self.url, open_timeout=3) as ws:
                    self._ws = ws
                    self._pump(ws)
            except Exception as e:
                if self._running:
                    self.failed.emit(f"{self.url}: {e}")
            finally:
                self._ws = None
            # Khong bo cuoc han: mat WiFi la kieu hong A, companion van song va
            # task tu hanh van chay. Noi lai duoc thi phai nhin thay ngay.
            for _ in range(int(RETRY_S * 10)):
                if not self._running:
                    return
                time.sleep(0.1)

    def _pump(self, ws):
        last_bps_at, nbytes = time.time(), 0
        while self._running:
            try:
                raw = ws.recv(timeout=1.0)
            except TimeoutError:
                raw = None
            except Exception:
                return  # dut -> ra ngoai de noi lai

            if raw is not None:
                nbytes += len(raw)
                self._handle(raw)

            now = time.time()
            if now - last_bps_at >= 1.0:
                self._emit("link", {"bps": int(nbytes / (now - last_bps_at))}, now)
                nbytes, last_bps_at = 0, now

    def _handle(self, raw):
        try:
            env = json.loads(raw)
        except ValueError:
            return  # goi hong thi bo, khong lam chet ca duong truyen
        if not isinstance(env, dict) or "topic" not in env:
            return
        # src luon la "remote": companion khong duoc tu xung la nguon khac, neu
        # khong thi trong tai da nguon va widget Link status deu bi danh lua.
        self._emit(env["topic"], env.get("data", {}), env.get("ts"))
