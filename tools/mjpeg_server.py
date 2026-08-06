#!/usr/bin/env python3
"""May chu MJPEG cho camera companion. CHAY TREN PI, khong phai tren laptop.

    python3 mjpeg_server.py                       # /dev/video0, cong 8080
    python3 mjpeg_server.py --device /dev/video2 --fps 5

Trong Docker phai cho container thay camera va mo cong:

    docker run --device=/dev/video0 -p 8080:8080 ...

Vi sao mot cong HTTP RIENG chu khong nhet chung WebSocket 8765: mot khung hinh
40 KB xep hang truoc mot lenh se lam tre duong lenh ROS2 (nguyen tac 2.1). Video
la thu dep-thi-co, no khong duoc chen vao hang doi lenh. Cong nay chet thi mat
video, het — nut do di duong SiK, khong dinh dang gi toi day.

MOT luong doc camera duy nhat, N client cung xem khung moi nhat. Khong xep hang
khung cu: GUI cham hon camera thi do tre troi dan thanh vai giay: tha khung con
hon tra khung qua date.

Doi sang RealSense sau nay: `cv_bridge` vao dung o ham `grab()` (imgmsg -> numpy),
tu do tro xuong khong doi gi, va GUI khong sua mot ky tu nao. Do la ly do ranh
gioi dat o HTTP chu khong dat o DDS.
"""

import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

BOUNDARY = "frame"

_lock = threading.Lock()
_latest = None  # JPEG byte moi nhat
_seq = 0  # tang moi khung — de client biet co khung moi chua


def grab(device, width, height, every, quality):
    """Doc camera mai mai. Camera rut ra hay loi thi cho roi mo lai, khong chet."""
    global _latest, _seq
    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    cap = None
    idx = 0
    while True:
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            cap = cv2.VideoCapture(device)
            # MJPG: webcam tu nen JPEG, USB2 do nghen hon nhieu so voi YUYV tho.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            # Khong co dong nay thi driver dem san vai khung, va do tre bat dau
            # troi: cai ban thay la qua khu chu khong phai hien tai.
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                print(f"[mjpeg] khong mo duoc {device}, thu lai sau 2s", flush=True)
                time.sleep(2.0)
                continue
            # KHONG dat CAP_PROP_FPS. Do tren Rapoo/Pi5: de mac dinh duoc 16,0 fps
            # voi p50=67ms, max=68ms — deu den muc gan nhu khong lech. Ep xuong 10
            # thi driver tra 7,0 fps va p90 vot len 200ms. Driver tu chay la tot
            # nhat, dung day no.
            print(f"[mjpeg] mo {device} {width}x{height}, gui 1/{every} khung", flush=True)

        ok, frame = cap.read()
        if not ok:
            print("[mjpeg] mat khung, mo lai camera", flush=True)
            cap.release()
            cap = None
            continue

        # Thua nhip theo SO DEM khung, khong theo dong ho. Day la cho da sai mot
        # lan va phai ghi lai: thua nhip bang `time.monotonic()` voi chu ky 100 ms
        # trong khi camera tra khung moi 67 ms thi hai nhip danh nhau sinh phach —
        # khung den som 1 ms bi vut di roi phai doi tron mot chu ky nua. Do duoc:
        # 9,1 fps tut xuong 2,5 fps, p90 250ms vot len 939ms, dinh 4,5 GIAY, du de
        # ben GUI lat sang o xam ba lan trong 25 giay.
        #
        # Dem khung thi khoang cach luon la boi so cua chu ky camera, khong the co
        # phach. `cap.read()` chan theo driver nen vong nay cung khong quay tit.
        idx += 1
        if idx % every:
            continue

        ok, jpg = cv2.imencode(".jpg", frame, params)
        if ok:
            with _lock:
                _latest = jpg.tobytes()
                _seq += 1


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self):
        if self.path not in ("/stream", "/"):
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        last = -1
        try:
            while True:
                with _lock:
                    jpg, seq = _latest, _seq
                if jpg is None or seq == last:
                    time.sleep(0.005)  # chua co khung moi — dung gui lai khung cu
                    continue
                last = seq
                self.wfile.write(
                    f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpg)}\r\n\r\n".encode()
                )
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass  # GUI dong tab hay rot WiFi — chuyen binh thuong, khong phai loi

    def log_message(self, fmt, *args):
        pass  # mot ket noi keo dai ca chuyen bay, khong co gi de log moi dong


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--device", default="/dev/video0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--every", type=int, default=1,
                   help="gui 1 trong N khung (1 = moi khung). Rapoo/Pi5 native 16 fps, "
                        "nen --every 2 ra 8 fps. Thua nhip theo dem, khong theo dong ho.")
    p.add_argument("--quality", type=int, default=70, help="chat luong JPEG 1-100")
    a = p.parse_args()

    threading.Thread(
        target=grab,
        args=(a.device, a.width, a.height, max(1, a.every), a.quality),
        daemon=True,
    ).start()

    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    print(f"[mjpeg] http://0.0.0.0:{a.port}/stream", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
