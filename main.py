"""Diem vao ban Android. pyside6-android-deploy bat buoc file ten `main.py` o
thu muc goc; tren may tinh `python3 main.py` chay y het `python3 -m laptop.app`.

Ban do offline dong chung APK, nhung la Android asset (assets:/tiles), KHONG nam
trong private.tar: p4a giai nen private.tar tren luong chinh cua Android ngay trong
onCreate — them 345 MB tile la ANR, he thong dong app (do 19/10). Lan mo dau mot
thread nen chep tile ra <files>/tiles; nam ngoai files/app vi p4a xoa sach files/app
moi lan cai ban moi. Co mang thi tile tai them cung vao do.
"""
import functools
import re
import ssl
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QDir, QDirIterator, QFile, QObject, Signal, QStandardPaths
from PySide6.QtWidgets import QApplication

from laptop import app
from laptop.connection import LOGS
from laptop.widgets import map_widget

ASSET_TILES = "assets:/tiles"  # tools/build_apk.sh: android.add_assets
ANDROID_CA = "/system/etc/security/cacerts"
PEM = re.compile(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.S)


def ca_bundle(src, dst):
    """Gop chung chi CA cua Android thanh mot file PEM, tra ve so chung chi.

    OpenSSL dong trong APK tim CA o /usr/local/ssl (OPENSSLDIR luc build) — dien
    thoai khong co thu muc do, nen moi HTTPS hong ma TileFetcher nuot loi: co mang,
    co GPS ca tieng van khong co ban do (21/10). Thu muc CA cua Android dat ten theo
    subject_hash_old, OpenSSL tra theo hash moi -> khong dung thang lam SSL_CERT_DIR.
    """
    certs = [c for f in sorted(Path(src).glob("*")) if f.is_file()
             for c in PEM.findall(f.read_text(errors="ignore"))]
    dst.write_text("\n".join(certs) + "\n")
    return len(certs)


def trust(ca):
    """Moi HTTPS mac dinh trong app (urllib — TileFetcher) chi tin file CA nay.

    KHONG dung SSL_CERT_FILE: app Android sinh tu zygote co AT_SECURE=1 (do
    /proc/<pid>/auxv 23/10), OpenSSL khi do co y bo qua bien moi truong. Ban sua
    21/10 dat bien do chi dung khi chay tay bang run-as (AT_SECURE=0) — trong app
    van CERTIFICATE_VERIFY_FAILED, va tu 21/10 toi 23/10 app khong tai duoc tile nao.
    """
    ssl._create_default_https_context = functools.partial(ssl.create_default_context,
                                                          cafile=str(ca))


def copy_tiles(src, dst, tick=lambda: None):
    """Chep moi file duoi src ra dst, bo qua file da co; xong ghi dau `.copied`.

    ponytail: co dau la thoi — APK sau co them tile thi xoa `.copied` (hay go cai app).
    """
    done = dst / ".copied"
    if done.exists():
        return 0
    it = QDirIterator(src, QDir.Filter.Files, QDirIterator.IteratorFlag.Subdirectories)
    n = 0
    while it.hasNext():
        f = it.next()
        out = dst / f[len(src) + 1:]
        out.parent.mkdir(parents=True, exist_ok=True)
        QFile.copy(f, str(out))  # khong ghi de: tile da tai qua mang giu nguyen
        n += 1
        if n % 2000 == 0:
            tick()  # ban do hien dan tung phan, khong doi chep xong
    if n:  # APK khong kem ban do (NO_TILES=1): khong danh dau — cai ban day du sau van chep
        done.write_text(f"{n}\n")
    tick()
    return n


class _MapRefresh(QObject):
    """Bao ban do quet lai dia. Signal phat tu thread chep, slot chay o main thread
    (QObject nay song o main thread) — cham widget tu thread khac la hong."""
    tick = Signal()

    def __init__(self):
        super().__init__()
        self.tick.connect(self.refresh)

    def refresh(self):
        for w in QApplication.allWidgets():
            if isinstance(w, map_widget.MapWidget):
                w._zooms = None  # available_zooms() nho ket qua luc dia con trong
                w.update()


def main():
    # APK khong mang thu muc rong: thieu logs/ thi commands.log, video.log mat im lang.
    # (Dien thoai: <files>/logs, ngoai files/app — xem connection.logs_dir.)
    LOGS.mkdir(parents=True, exist_ok=True)
    # Video H.264: giai ma phan cung MediaCodec, ve bang VideoOutput (QML) — xem
    # VideoSource.set_output. Ep phan mem (QT_FFMPEG_DECODING_HW_DEVICE_TYPES=none,
    # 19-21/10) chi con la cach lui: 15-25 fps, 193 % CPU tren Lenovo.
    qapp = QApplication(sys.argv)  # truoc khi doc assets:/ — Qt dang ky no luc tao app
    if hasattr(sys, "getandroidapilevel"):  # chi Python cua Android co ham nay
        files = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        ca = Path(files) / "cacert.pem"
        if ca_bundle(ANDROID_CA, ca):
            trust(ca)
        map_widget.TILE_DIR = Path(files) / "tiles"
        map_widget.TILE_DIR.mkdir(parents=True, exist_ok=True)
        ref = _MapRefresh()
        threading.Thread(target=copy_tiles, args=(ASSET_TILES, map_widget.TILE_DIR, ref.tick.emit),
                         daemon=True).start()
    return app.main(qapp)


if __name__ == "__main__":
    sys.exit(main())
