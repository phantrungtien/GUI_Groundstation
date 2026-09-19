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

import collections
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from core.i18n import t
from laptop import theme

# Cong rieng cho video, khong dung chung 8765 cua duong lenh (nguyen tac 2.1).
# GCS_VIDEO_PORT chi de CHIA LUONG luc thu nghiem (chay stream thu hai o cong khac
# trong khi 8080 van la stream that). Khong phai key config: mac dinh van la 8080.
VIDEO_PORT = int(os.environ.get("GCS_VIDEO_PORT", 8080))
READ_TIMEOUT_S = 4.0  # khong co byte nao trong ngan nay -> coi nhu dut, noi lai
RETRY_S = 2.0
STALE_S = 2.0  # khong co khung moi qua ngan nay -> o xam
MAX_FRAME_B = 8_000_000  # chan may chu hong bao Content-Length khong lo

# Nhip khung toi GUI ghi ra file suot phien chay, de ghep voi journal cua Pi bang
# tools/video_timeline.sh. So fps ve tren khung chi cho biet LUC NAY; video giat
# luc 13:40 thi phai co dong log luc 13:40.
REPORT_S = 5.0  # cung chu ky voi dong `[mjpeg] nguon ...` ben Pi
LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "video.log"


def _log(msg):
    """Mot dong co moc gio dia phuong, cung dang voi `journalctl -o short-iso`."""
    try:
        LOG_PATH.parent.mkdir(exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} gui {msg}\n")
    except OSError:
        pass  # khong ghi duoc log thi video van phai chay


def url_for(remote_url):
    """Suy dia chi video tu `remote` da co trong connections.yaml.

    Video chi chay tren nua WiFi/ROS2 — dung cai dieu kien de co video cung la
    dieu kien da biet IP companion. Nen khong them key config, va cung khong di
    do IP: cai gi dang cam trong tay thi khong phai di tim.
    """
    host = urlparse(remote_url).hostname
    return f"http://{host}:{VIDEO_PORT}/stream" if host else None


def video_url(profile):
    """Dia chi video cua mot profile: key `video` neu co, khong thi suy tu `remote`.

    Key rieng can cho SITL: nua ROS2 chay NGAY TREN laptop (ws://127.0.0.1) con
    camera van nam tren Pi — suy tu `remote` la di tim video o laptop, va man bay
    trong tron du Pi dang phat.
    """
    return profile.get("video") or (url_for(profile["remote"]) if profile.get("remote") else None)


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
        self.note = ("vid.not_connected", {})
        self._gen = 0  # doi doi thi thread cu tu biet minh het viec
        self._last = 0.0
        self._stamps = collections.deque(maxlen=30)  # moc thoi gian 30 khung gan nhat
        self._n = self._bytes = 0  # dem trong chu ky REPORT_S hien tai
        self._rep_t = time.monotonic()

        self._arrived.connect(self._decode)
        self._watch = QTimer(self)
        self._watch.timeout.connect(self._check_stale)
        self._watch.start(500)

    # ------------------------------------------------------------------ dieu khien

    def start(self, url):
        self.stop()
        self.url = url
        self.note = ("vid.connecting", {})
        self._n = self._bytes = 0
        self._rep_t = time.monotonic()
        _log(f"start {url}")
        self._gen += 1
        threading.Thread(target=self._run, args=(url, self._gen), daemon=True).start()

    def stop(self):
        self._gen += 1  # thread dang chay se thay _gen lech va tu thoat
        if self.url:
            _log("stop")
        self.url = None
        self.pixmap = None
        self.alive = False
        self.note = ("vid.not_connected", {})
        self._stamps.clear()
        self.updated.emit()

    # ------------------------------------------------------------------ main thread

    def _decode(self, jpeg):
        pm = QPixmap()
        if pm.loadFromData(jpeg, "JPEG"):
            self.pixmap = pm
            self.alive = True
            self._last = time.monotonic()
            self._stamps.append(self._last)
            self._n += 1
            self._bytes += len(jpeg)
            self.updated.emit()

    @property
    def fps(self):
        """Nhip khung THUC SU toi noi, do ben nay chu khong hoi server.

        Server bao no gui 15 fps khong noi len duoc gi: cai quyet dinh nguoi lai
        nhin thay muot hay giat la so khung ve DEN GUI sau khi qua WiFi.
        """
        s = self._stamps
        if len(s) < 2 or time.monotonic() - s[-1] > STALE_S:
            return 0.0
        return (len(s) - 1) / (s[-1] - s[0])

    def _check_stale(self):
        now = time.monotonic()
        if self.url and now - self._rep_t >= REPORT_S:
            dt = now - self._rep_t
            _log(f"fps {self._n / dt:5.1f}  {self._bytes / dt / 1000:4.0f} KB/s")
            self._n = self._bytes = 0
            self._rep_t = now
        if self.alive and now - self._last > STALE_S:
            # Het khung moi. Bo khung cu di chu khong giu lai cho dep man hinh.
            self.alive = False
            self.pixmap = None
            self._stamps.clear()
            self.note = ("vid.lost", {})
            _log(f"lost — khong co khung moi qua {STALE_S:.0f} s")
            self.updated.emit()

    # ------------------------------------------------------------------ thread phu

    def _run(self, url, gen):
        last_err = None  # Pi tat thi loi lap lai moi RETRY_S — chi ghi lan dau
        while gen == self._gen:
            try:
                # timeout nay di theo socket nen ap cho ca cac lan read() sau,
                # khong chi rieng luc bat tay.
                resp = urllib.request.urlopen(url, timeout=READ_TIMEOUT_S)
                _log("connected")
                last_err = None
                while gen == self._gen:
                    self._arrived.emit(_read_frame(resp))
                resp.close()
            except (urllib.error.URLError, OSError, EOFError, ValueError) as e:
                # Rot WiFi, Pi chua bat server, camera rut ra — deu la chuyen
                # binh thuong ngoai bai bay. Cho roi thu lai, khong keu ca.
                if gen == self._gen:
                    if type(e) is not last_err:
                        _log(f"error {type(e).__name__}: {e}")
                    last_err = type(e)
                    self.note = ("vid.error", {})  # loai loi + dia chi nam o log
                    time.sleep(RETRY_S)


class VideoView(QWidget):
    """Ve khung moi nhat cua mot `VideoSource`. Nhieu view dung chung mot source."""

    clicked = Signal(QPoint)  # tab Bay dung de doi cho ban do <-> camera

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

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(e.position().toPoint())

    def paintEvent(self, _e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        src = self.source

        if src is None or not src.alive or src.pixmap is None:
            p.fillRect(0, 0, w, h, QColor(theme.BG))
            p.setPen(QColor(theme.MUTED))
            # `note` la (key, kwargs), dich luc VE chu khong luc dat: khung ve lai
            # deu dan nen doi ngon ngu la dong chu tu doi theo, khoi dang ky hook.
            # Khong in dia chi http len man: nguoi bay khong lam gi duoc voi no, con
            # nguoi sua loi thi doc o log (`_log`: start <url>, error <loai>).
            text = t(src.note[0], **src.note[1]) if src is not None else t("vid.no_source")
            p.drawText(0, 0, w, h, Qt.AlignCenter | Qt.TextWordWrap, text)
        else:
            p.fillRect(0, 0, w, h, QColor(theme.BG_DEEP))
            pm = src.pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((w - pm.width()) // 2, (h - pm.height()) // 2, pm)

            # Ghi nhip khung LEN khung hinh. Video dep ma 3 fps thi van la video
            # hong — con so phai nam ngay canh anh, khong nam o tab khac.
            fps = src.fps
            p.setPen(QColor(theme.WARN) if fps < 8 else QColor(theme.OK))
            p.drawText(6, 4, w - 12, 18, Qt.AlignLeft | Qt.AlignTop, f"{fps:.1f} fps")

        p.setPen(QColor(theme.BORDER))
        p.drawRect(0, 0, w - 1, h - 1)
