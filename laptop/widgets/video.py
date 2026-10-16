"""Video tu camera tren companion: MJPEG qua HTTP, hoac H.264 Jetson day qua UDP.

H.264 (11/10/2026): Jetson day MPEG-TS/H.264 960x540 25 fps toi UDP 5600 cua laptop,
~235 KB/s — nhe ~12 lan MJPEG cung do phan giai. Dia chi `udp://...` trong key
`video` cua profile la chon nhanh nay; `http://...` van la MJPEG nhu cu.

Giai ma bang GStreamer (appsink sync=false), KHONG bang QMediaPlayer: do cung luong
Jetson, cung canh quay, so tin hieu do sang voi MJPEG — GStreamer tre hon MJPEG
~20 ms, QMediaPlayer tre ~900-990 ms vi tu dem de phat muot. Lai drone nhin hinh
cham 1 giay la khong duoc. May khong co GStreamer (Windows) moi roi ve QMediaPlayer.

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
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QWidget

from core.i18n import t
from laptop import theme

try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
except (ImportError, ValueError):
    Gst = None  # ponytail: khong co GStreamer -> QMediaPlayer, tre ~0,9 s (xem dau file)

# Cong rieng cho video, khong dung chung 8765 cua duong lenh (nguyen tac 2.1).
# GCS_VIDEO_PORT chi de CHIA LUONG luc thu nghiem (chay stream thu hai o cong khac
# trong khi 8080 van la stream that). Khong phai key config: mac dinh van la 8080.
VIDEO_PORT = int(os.environ.get("GCS_VIDEO_PORT", 8080))
READ_TIMEOUT_S = 4.0  # khong co byte nao trong ngan nay -> coi nhu dut, noi lai
RETRY_S = 2.0
STALE_S = 2.0  # khong co khung moi qua ngan nay -> o xam
# Khung VAN VE DEU ma anh khong doi mot byte qua ngan nay -> camera dung hinh.
# Do duoc bang cach bam byte JPEG: may anh that luon co nhieu cam bien, hai khung
# lien tiep khong bao gio trung tung byte du canh quay dung yen va drone dau dat.
# Trung byte nghia la duong hinh dut o dau do TRUOC luc nen — cam bien treo, driver
# tra lai dung buffer cu — chu khong phai canh quay tinh. Ben Pi cung khong bao gio
# gui lai khung cu (`mjpeg_server.py`: `seq == last` thi bo qua).
# Doi camera khac thi do lai: cam bien nao lam min manh qua co the cho ra khung
# trung that, luc do nang so nay len chu dung bo han phep bam.
FROZEN_S = 2.0
# H.264 thi phep bam KHONG dung duoc: do 11/10/2026, mot khung camera that dong
# bang dua qua x264 (ultrafast, zerolatency) giai ma ra 126/159 anh khac nhau, doan
# trung dai nhat 0,16 s — bo ma hoa cu tinh chinh mai. Nen so ANH THU NHO 64x36 xam
# voi anh moc: lech diem lon nhat > STILL_DIFF muc xam moi tinh la "doi".
# Do cung ngay: camera treo lech toi da 2 muc (147 khung, 0 lan doi); Jetson song
# trung vi 42, 551/551 khung deu doi. Ton ~2,8 ms/khung.
THUMB_W, THUMB_H = 64, 36
STILL_DIFF = 4
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


def count_loss(data, last):
    """(goi TS nhan, goi mat) trong mot datagram MPEG-TS; `last` = {pid: cc} giu giua
    cac lan. Goc la `count_loss` cua h264_feedback.py tren Jetson (~/pi5) — run_gui.py
    tinh nguong ha/tang bitrate theo dung con so nay.

    Buoc nhay CC >= 8 (nguoi dung 15/10/2026): coi la goi den sai thu tu (lui lai =
    nhay 15) hoac ffmpeg vua khoi dong lai (CC ve 0) -> BO QUA, khong tinh mat va khong
    doi moc, nen goi den tre khong lam goi sau no bi tinh mat oan.
    ponytail: tran — mat lien >= 7 goi tren mot PID (>= 2 datagram 1128 B = 6 goi TS
    lien nhau) cung ra buoc nhay >= 8 nen KHONG duoc dem; mat chum tren LTE bi bo sot.
    """
    got = lost = 0
    for i in range(0, len(data) - 187, 188):
        if data[i] != 0x47:
            continue
        pid = ((data[i + 1] & 0x1F) << 8) | data[i + 2]
        if pid == 0x1FFF or not data[i + 3] & 0x10:  # null / khong co payload: CC dung yen
            continue
        cc = data[i + 3] & 0x0F
        got += 1
        if pid in last and cc != last[pid]:  # cc trung = goi lap, hop le
            step = (cc - last[pid]) & 0x0F
            if step >= 8:
                continue  # sai thu tu / ffmpeg khoi dong lai: khong dem, giu moc cu
            lost += step - 1
        last[pid] = cc
    return got, lost


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
    """Mot nguon video (MJPEG HTTP hoac H.264 UDP), tu noi lai, phat `updated`
    moi khi co khung moi."""

    _arrived = Signal(bytes, int)  # (jpeg, gen) thread -> main. KHONG cham QPixmap tu thread phu.
    _image = Signal(QImage, int)   # (anh, gen) luong GStreamer -> main
    updated = Signal()  # main -> cac VideoView
    # Chi ban luc DOI: bat dau dung hinh (True) va co khung khac byte tro lai
    # (False). Dut han giua luc dang dung hinh thi KHONG ban False — no khong
    # chay lai, no chuyen sang mat tin hieu, va man bay khong duoc bao "da on".
    frozen_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.url = None
        self.pixmap = None
        self.alive = False
        self.note = ("vid.not_connected", {})
        self._gen = 0  # doi doi thi thread cu tu biet minh het viec
        self._last = 0.0
        self._hash = None   # MJPEG: bam khung vua ve; H.264: anh thu nho moc
        self._moved = 0.0   # lan cuoi ANH THAT SU doi
        self._frozen = False
        self._stamps = collections.deque(maxlen=30)  # moc thoi gian 30 khung gan nhat
        self._n = self._bytes = 0  # dem trong chu ky REPORT_S hien tai
        self._rep_t = time.monotonic()
        self._player = None   # du phong khong co GStreamer: tao lan dau, roi giu mai
        self._pipe = None     # pipeline GStreamer cua nguon H.264 dang chay
        self.status = None    # url /status (key `status` cua profile), hoi moi nhip _watch
        self.persons = None   # `total` cua lan tra loi moi nhat; loi/het gio = None
        self._net = None
        self._seq = self._seen = 0  # tra loi ve lon xon thi bo cai cu hon cai da hien
        self.feedback = None  # (host, port) Jetson nhan "loss=..." (key `feedback`)
        self._loss = None     # ti le mat goi giay vua qua, ghi vao dong log fps

        self._arrived.connect(self._decode)
        self._image.connect(self._on_image)
        self._watch = QTimer(self)
        self._watch.timeout.connect(self._check_stale)
        self._watch.start(500)

    # ------------------------------------------------------------------ dieu khien

    def start(self, url, status=None, feedback=None):
        self.stop()
        self.url = url
        self.status = status
        host, _, port = (feedback or "").rpartition(":")
        self.feedback = (host, int(port)) if host else None
        self._loss = None
        self.note = ("vid.connecting", {})
        self._hash, self._frozen = None, False
        self._n = self._bytes = 0
        self._rep_t = time.monotonic()
        _log(f"start {url}")
        self._gen += 1
        if url.startswith("http"):
            threading.Thread(target=self._run, args=(url, self._gen), daemon=True).start()
            return
        if Gst is not None:
            self._gst_start(url, self._gen)
            return
        # H.264: QMediaPlayer tu nghe UDP va tu chay tiep khi goi toi lai (do 11/10:
        # ngat 0,3-7 s, noi lai ~0,07 s la chay deu) — khong can vong noi lai.
        # MOT player cho ca doi VideoSource: huy di tao moi thi socket cu chua nha
        # cong, player moi "bind failed: Address already in use" va khong bao gio
        # ra hinh (do 11/10). Khong dung `?reuse=1`: hai GUI se cung nghe mot cong
        # va chia nhau goi tin trong im lang.
        if self._player is None:
            self._player = QMediaPlayer(self)
            sink = QVideoSink(self._player)
            self._player.setVideoSink(sink)
            sink.videoFrameChanged.connect(self._on_vframe)
            self._player.errorOccurred.connect(self._on_player_error)
        self._player.setSource(QUrl())  # mo lai tu dau: do lai luong sau khi Jetson khoi dong lai
        self._player.setSource(QUrl(url))
        self._player.play()

    def stop(self):
        self._gen += 1  # thread dang chay se thay _gen lech va tu thoat
        if self._pipe:
            self._pipe.set_state(Gst.State.NULL)  # NULL dong socket ngay: start() lai cung cong duoc
            self._pipe = None
        if self._player:
            self._player.stop()  # giu player lai cho lan start() sau, xem start()
        if self.url:
            _log("stop")
        self.url = self.status = self.persons = None
        self.pixmap = None
        self.alive = False
        self._hash, self._frozen = None, False
        self.note = ("vid.not_connected", {})
        self._stamps.clear()
        self.updated.emit()

    # ------------------------------------------------------------------ main thread

    def _decode(self, jpeg, gen):
        if gen != self._gen:
            # Khung cua luong CU: no dang nam trong read() luc stop() doi _gen, doc
            # xong van emit, va tin hieu xep hang toi sau. Do that 04/10/2026: 10/10
            # lan stop() thi khung cuoi hien lai (alive=True) toi ~2 s — dung cai
            # "dong bang khung cuoi" ca file nay viet ra de chan.
            return
        pm = QPixmap()
        if not pm.loadFromData(jpeg, "JPEG"):
            return
        changed = hash(jpeg) != self._hash
        self._hash = hash(jpeg)
        self._show(pm, changed, len(jpeg))

    def _gst_start(self, url, gen):
        """udpsrc -> MPEG-TS -> H.264 -> RGBx -> appsink. sync=false + 1 buffer, bo
        khung cu: luon ve khung MOI NHAT, khong co dong ho phat nao giu khung lai.
        GStreamer tu chay tiep khi goi UDP toi lai, ke ca Jetson khoi dong lai luong.

        `alignment=au` sau tsdemux: moi PES la TRON mot khung (ffmpeg/mpegtsmux deu
        vay), noi ro thi h264parse nha khung ngay thay vi cho khung SAU de biet khung
        nay het. Do 16/10/2026, 40 khung 5 fps cau hinh x264 cua Jetson: khong co ->
        38/40 khung ra, tre 2 khung; co -> 39/40, tre 1 khung (khung con lai la
        tsdemux cho PES ke tiep vi ffmpeg bo do dai PES — Jetson them
        `-omit_video_pes_length 0` thi 40/40, tre 4 ms). Doi `avdec_h264` sang
        `max-threads=1` / `thread-type=slice` (kieu ffmpeg low_delay): khong doi gi."""
        u = urlparse(url)
        self._pipe = Gst.parse_launch(
            f"udpsrc name=u address={u.hostname or '0.0.0.0'} port={u.port} "
            "caps=video/mpegts,systemstream=true ! tsdemux "
            "! video/x-h264,stream-format=byte-stream,alignment=au ! h264parse ! avdec_h264 "
            "! videoconvert ! video/x-raw,format=RGBx "
            "! appsink name=s emit-signals=true sync=false max-buffers=1 drop=true")
        self._pipe.get_by_name("s").connect("new-sample", self._on_sample, gen)
        if self.feedback:
            # Bao mat goi ve Jetson moi giay -> run_gui.py --h264-fb-port tu ha/tang
            # bitrate. Chay tren luong GStreamer, ngay khi goi vua toi, truoc demux.
            st = {"cc": {}, "got": 0, "lost": 0, "t": time.monotonic(), "to": self.feedback,
                  "sock": socket.socket(socket.AF_INET, socket.SOCK_DGRAM)}
            self._pipe.get_by_name("u").get_static_pad("src").add_probe(
                Gst.PadProbeType.BUFFER, self._on_udp, st)
        self._pipe.set_state(Gst.State.PLAYING)

    def _on_udp(self, _pad, info, st):
        """Luong GStreamer: dem goi TS mat (count_loss), moi giay gui "loss=0.0123".
        Khong co goi nao thi IM — Jetson im 5 s tu coi la mat het va ha bitrate."""
        buf = info.get_buffer()
        ok, m = buf.map(Gst.MapFlags.READ)
        if ok:
            try:
                g, lost = count_loss(m.data, st["cc"])
            finally:
                buf.unmap(m)
            st["got"] += g
            st["lost"] += lost
        now = time.monotonic()
        if now - st["t"] >= 1.0:
            if st["got"]:
                self._loss = st["lost"] / (st["got"] + st["lost"])
                try:
                    st["sock"].sendto(f"loss={self._loss:.4f}".encode(), st["to"])
                except OSError:
                    pass  # mang dang rot: lan sau gui tiep, Jetson tu xu ly im lang
            st["got"] = st["lost"] = 0
            st["t"] = now
        return Gst.PadProbeReturn.OK

    def _on_sample(self, sink, gen):
        """Luong GStreamer: chep khung ra QImage (QImage dung o thread phu duoc,
        QPixmap thi khong) roi day ve main."""
        s = sink.emit("pull-sample")
        st = s.get_caps().get_structure(0)
        w, h = st.get_value("width"), st.get_value("height")
        buf = s.get_buffer()
        ok, m = buf.map(Gst.MapFlags.READ)
        if ok:
            try:
                self._image.emit(QImage(bytes(m.data), w, h, w * 4,
                                        QImage.Format.Format_RGBX8888).copy(), gen)
            finally:
                buf.unmap(m)
        return Gst.FlowReturn.OK

    def _on_image(self, img, gen):
        if gen == self._gen and self.url:  # khung cua pipeline cu sau stop(): bo
            self._from_image(img)

    def _on_vframe(self, frame):
        """Khung H.264 da giai ma bang QMediaPlayer (du phong khong co GStreamer)."""
        if not self.url or self.url.startswith("http") or not frame.isValid():
            return  # khung con xep hang sau stop(), hoac nguon dang la MJPEG
        img = frame.toImage()
        if not img.isNull():
            self._from_image(img)

    def _from_image(self, img):
        """Anh H.264 da giai ma -> man hinh. So anh thu nho voi moc, xem STILL_DIFF."""
        g = img.scaled(THUMB_W, THUMB_H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation) \
               .convertToFormat(QImage.Format.Format_Grayscale8)
        raw, bpl = bytes(g.constBits()), g.bytesPerLine()  # moi dong co the co byte dem
        th = b"".join(raw[r * bpl:r * bpl + THUMB_W] for r in range(THUMB_H))
        changed = self._hash is None or max(abs(a - b) for a, b in zip(th, self._hash)) > STILL_DIFF
        if changed:
            self._hash = th
        self._show(QPixmap.fromImage(img), changed, 0)

    def _on_player_error(self, err, msg):
        _log(f"error {err.name}: {msg}")
        self.note = ("vid.error", {})

    def _show(self, pm, changed, nbytes):
        """Chung cho hai nguon: nhip khung, dung hinh, ve. changed = anh co doi."""
        self._last = time.monotonic()
        self._stamps.append(self._last)
        self._n += 1
        self._bytes += nbytes

        if changed:
            self._moved = self._last
        frozen = self._last - self._moved >= FROZEN_S
        if frozen:
            # Duong truyen con song, fps van dep, ma canh quay da chet tu bao gio.
            # Day chinh la cai "dong bang khung cuoi" ma ca file nay viet ra de
            # chan — chi khac la lan nay khung cu do CAMERA gui den chu khong phai
            # do GUI giu lai. Nen xu ly y het mat tin hieu: XOA anh di.
            self.pixmap = None
            self.note = ("vid.frozen", {})
        else:
            self.pixmap = pm
        self.alive = not frozen
        if frozen != self._frozen:
            self._frozen = frozen
            if frozen:
                _log(f"frozen — anh khong doi mot byte qua {FROZEN_S:.0f}s")
            else:
                _log("frozen het — anh doi tro lai")
            self.frozen_changed.emit(frozen)
        self.updated.emit()

    @property
    def frozen(self):
        """Khung van ve deu nhung anh dung hinh. Khac `not alive` o cho: mat tin
        hieu la khong con gi ve, con day la van co ma toan la mot canh cu."""
        return self._frozen

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

    def _ask_status(self):
        """So nguoi: `GET /status` moi 0,5 s, lay `total`, timeout 1 s.

        Doc thang server camera chu khong qua ros2_bridge: nhe hon, khong can ROS2
        tren Jetson. Loi hay het gio thi `persons = None` (man bay hien "--") NGAY,
        khong giu so cu — so cu tren giao dien cuu ho la nguoi lai tin nham."""
        if not self.status:
            return
        if self._net is None:
            self._net = QNetworkAccessManager(self)
        req = QNetworkRequest(QUrl(self.status))
        req.setTransferTimeout(1000)
        rep = self._net.get(req)
        self._seq += 1
        rep.finished.connect(lambda r=rep, g=self._gen, q=self._seq: self._on_status(r, g, q))

    def _on_status(self, rep, gen, seq):
        rep.deleteLater()
        if gen != self._gen or seq < self._seen:
            return  # cua lan start() truoc, hoac ve sau mot tra loi moi hon
        self._seen = seq
        n = None
        if rep.error() == QNetworkReply.NetworkError.NoError:
            try:
                n = int(json.loads(bytes(rep.readAll()))["total"])
            except (ValueError, KeyError, TypeError):
                pass
        self.persons = n

    def _check_stale(self):
        self._ask_status()
        if self._pipe:  # vd "bind failed": cong 5600 dang bi tien trinh khac giu
            msg = self._pipe.get_bus().pop_filtered(Gst.MessageType.ERROR)
            if msg:
                err, _dbg = msg.parse_error()
                _log(f"error gstreamer: {err.message}")
                self.note = ("vid.error", {})
        now = time.monotonic()
        if self.url and now - self._rep_t >= REPORT_S:
            dt = now - self._rep_t
            kb = f"  {self._bytes / dt / 1000:4.0f} KB/s" if self._bytes else ""  # H.264: khong dem
            if self._loss is not None:
                kb += f"  mat {self._loss:.1%}"
            _log(f"fps {self._n / dt:5.1f}{kb}")
            self._n = self._bytes = 0
            self._rep_t = now
        if (self.alive or self._frozen) and now - self._last > STALE_S:
            # Het khung moi. Bo khung cu di chu khong giu lai cho dep man hinh.
            self.alive = False
            self._frozen = False
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
                    self._arrived.emit(_read_frame(resp), gen)
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
            # Xam la mau cua trang thai binh thuong ("chua ket noi", "dang noi").
            # Dung hinh la SU CO: no phai khac mau, khong thi nguoi lai doc qua.
            p.setPen(QColor(theme.WARN if src is not None and src.note[0] == "vid.frozen"
                            else theme.MUTED))
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
