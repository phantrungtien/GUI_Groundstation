"""Video MJPEG tu camera tren companion.

MOT nguon, NHIEU cho ve. `VideoSource` giu dung mot ket noi HTTP toi Pi va giai
ma mot lan; tab Camera va o PiP tren tab Flight cung doc lai ket qua do. Hai
`VideoView` khong co nghia la hai ket noi — Pi chi phai phuc vu mot luong.

Thread thuong (daemon) chu khong QThread, cung ly do da ghi o `map_widget.py:145`:
"QThread: Destroyed while thread is still running" la abort ca tien trinh, va mot
GCS khong duoc chet vi cai thread xem video.

Khac tile o ba cho, va ca ba deu la cho de sai:

1. Tile la request ngan roi dong; video la ket noi mo mai. Nen timeout phai nam
   o TUNG LAN DOC — WiFi rot thi `read()` treo im lang, khong nem loi bao gio.
2. Luon ve khung MOI NHAT, khong xep hang. GUI cham hon camera thi hang doi day
   dan va do tre troi thanh vai giay.
3. Mat ket noi thi hien O XAM, TUYET DOI khong dong bang khung cuoi. Nhin mot
   khung hinh cu ma tuong drone dang o do la kieu nguy hiem nhat cua giao dien.
"""

import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

# Cong rieng cho video, khong dung chung 8765 cua duong lenh (nguyen tac 2.1).
VIDEO_PORT = 8080
READ_TIMEOUT_S = 4.0  # khong co byte nao trong ngan nay -> coi nhu dut, noi lai
RETRY_S = 2.0
STALE_S = 2.0  # khong co khung moi qua ngan nay -> o xam
MAX_FRAME_B = 8_000_000  # chan may chu hong bao Content-Length khong lo


def url_for(remote_url):
    """Suy dia chi video tu `remote` da co trong connections.yaml.

    Video chi chay tren nua WiFi/ROS2 — dung cai dieu kien de co video cung la
    dieu kien da biet IP companion. Nen khong them key config, va cung khong di
    do IP: cai gi dang cam trong tay thi khong phai di tim.
    """
    host = urlparse(remote_url).hostname
    return f"http://{host}:{VIDEO_PORT}/stream" if host else None


def _read_frame(resp):
    """Doc mot phan multipart/x-mixed-replace, tra ve byte JPEG."""
    while True:  # nhay toi dong boundary
        line = resp.readline()
        if not line:
            raise EOFError("may chu dong ket noi")
        if line.startswith(b"--"):
            break

    length = None
    while True:  # header cua phan nay, ket thuc bang dong trong
        line = resp.readline()
        if not line:
            raise EOFError("dut giua header")
        if line in (b"\r\n", b"\n"):
            break
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1])

    if length is None or not 0 < length < MAX_FRAME_B:
        raise ValueError(f"Content-Length khong dung: {length}")
    data = resp.read(length)
    if len(data) != length:
        raise EOFError("dut giua khung")
    return data


class VideoSource(QObject):
    """Mot ket noi MJPEG, tu noi lai, phat `updated` moi khi co khung moi."""

    _arrived = Signal(bytes)  # thread -> main. KHONG cham QPixmap tu thread phu.
    updated = Signal()  # main -> cac VideoView

    def __init__(self, parent=None):
        super().__init__(parent)
        self.url = None
        self.pixmap = None
        self.alive = False
        self.note = "chua ket noi"
        self._gen = 0  # doi doi thi thread cu tu biet minh het viec
        self._last = 0.0

        self._arrived.connect(self._decode)
        self._watch = QTimer(self)
        self._watch.timeout.connect(self._check_stale)
        self._watch.start(500)

    # ------------------------------------------------------------------ dieu khien

    def start(self, url):
        self.stop()
        self.url = url
        self.note = "dang noi..."
        self._gen += 1
        threading.Thread(target=self._run, args=(url, self._gen), daemon=True).start()

    def stop(self):
        self._gen += 1  # thread dang chay se thay _gen lech va tu thoat
        self.url = None
        self.pixmap = None
        self.alive = False
        self.note = "chua ket noi"
        self.updated.emit()

    # ------------------------------------------------------------------ main thread

    def _decode(self, jpeg):
        pm = QPixmap()
        if pm.loadFromData(jpeg, "JPEG"):
            self.pixmap = pm
            self.alive = True
            self._last = time.monotonic()
            self.updated.emit()

    def _check_stale(self):
        if self.alive and time.monotonic() - self._last > STALE_S:
            # Het khung moi. Bo khung cu di chu khong giu lai cho dep man hinh.
            self.alive = False
            self.pixmap = None
            self.note = "mat video"
            self.updated.emit()

    # ------------------------------------------------------------------ thread phu

    def _run(self, url, gen):
        while gen == self._gen:
            try:
                # timeout nay di theo socket nen ap cho ca cac lan read() sau,
                # khong chi rieng luc bat tay.
                resp = urllib.request.urlopen(url, timeout=READ_TIMEOUT_S)
                while gen == self._gen:
                    self._arrived.emit(_read_frame(resp))
                resp.close()
            except (urllib.error.URLError, OSError, EOFError, ValueError) as e:
                # Rot WiFi, Pi chua bat server, camera rut ra — deu la chuyen
                # binh thuong ngoai bai bay. Cho roi thu lai, khong keu ca.
                if gen == self._gen:
                    self.note = f"khong co video ({type(e).__name__})"
                    time.sleep(RETRY_S)


class VideoView(QWidget):
    """Ve khung moi nhat cua mot `VideoSource`. Nhieu view dung chung mot source."""

    def __init__(self, source=None, parent=None):
        super().__init__(parent)
        self.source = None
        self.setMinimumSize(160, 120)
        if source is not None:
            self.set_source(source)

    def set_source(self, source):
        if self.source is not None:
            self.source.updated.disconnect(self.update)
        self.source = source
        if source is not None:
            source.updated.connect(self.update)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        src = self.source

        if src is None or not src.alive or src.pixmap is None:
            p.fillRect(0, 0, w, h, QColor("#25292c"))
            p.setPen(QColor("#8a939b"))
            text = src.note if src is not None else "chua co nguon"
            if src is not None and src.url:
                text += f"\n{src.url}"
            p.drawText(0, 0, w, h, Qt.AlignCenter | Qt.TextWordWrap, text)
        else:
            p.fillRect(0, 0, w, h, QColor("#101214"))
            pm = src.pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((w - pm.width()) // 2, (h - pm.height()) // 2, pm)

        p.setPen(QColor("#3a3f44"))
        p.drawRect(0, 0, w - 1, h - 1)
