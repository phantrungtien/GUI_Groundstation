#!/usr/bin/env python3
"""Bam vet lua/khoi bang YOLO11n ONNX, ve thang len khung hinh MJPEG.

    python3 fire_tracker.py --model ~/firedrop_sim/tracking/best_nano_111_640.onnx
    (tu kiem, khong can camera - xem demo() cuoi file)

Dung that thi khong goi truc tiep, ma qua may chu video:

    python3 mjpeg_server.py --ros-topic /rgb/image \
        --detect ~/firedrop_sim/tracking/best_nano_111_640.onnx

--------------------------------------------------------------------------
VI SAO VE VAO KHUNG HINH CHU KHONG GUI TOA DO QUA WEBSOCKET 8765
--------------------------------------------------------------------------
Duong lenh 8765 co san `envelope` (core/adapters/remote.py) nen gui hop bao
qua do la lam duoc. Nhung hop va khung hinh khi do di HAI duong khac nhau,
moi duong mot do tre: khung anh qua HTTP 8080, hop qua WebSocket 8765. Drone
bay 5 m/s o cao 30 m, lech 100 ms la hop tut sau ngon lua ~10 px va no LUON
tut ve mot phia - nhin ra ngay va nhin nhu thuat toan bam sai, trong khi thuat
toan dung. Ve vao chinh khung hinh vua suy dien thi hop va anh KHONG THE lech
nhau, bat ke mang tre bao nhieu.

Doi lai: GUI khong doc duoc so lieu hop (khong loc, khong bam nut). Neu sau nay
can thi them topic "vision/tracks" vao WS, NHUNG van giu hop ve san o day -
mot cai de nhin, mot cai de may doc.

--------------------------------------------------------------------------
BAM VET, KHONG PHAI CHI PHAT HIEN
--------------------------------------------------------------------------
YOLO chay doc lap tung khung: cung mot dam chay se nhay so hieu, va cu vai
khung lai mat mot khung roi hien lai - hop nhap nhay. `Tracker` ghep hop giua
cac khung bang IoU, giu so hieu, va:

  - `confirm_hits` khung lien tiep moi ve  -> nhieu mot khung khong len man hinh
  - con song them `max_miss` khung sau khi mat -> lua bi khoi che thoang qua
    khong lam mat hop

Day la bam vet DUOI DAT thi kem (khong co du doan chuyen dong), nhung o day
camera nadir va lua thi DUNG YEN duoi dat - thu chuyen dong la camera, va no
cham hon nhieu so voi nhip khung. Ghep bang IoU la du. Can hon thi Kalman,
dung viet truoc khi do duoc la thieu.

--------------------------------------------------------------------------
⚠ DO TREN LUA CUA GAZEBO: MODEL NAY KHONG AN LUA MO PHONG
--------------------------------------------------------------------------
best_nano_111_640.onnx hoc tu anh CHAY THAT (Fire-Smoke-Detection-Yolov11).
Lua trong Gazebo la mot khoi phat sang mo, khong co van ngon lua. Do tren 717
khung cua tron mot chuyen bay o firedrop_city (bay thang, tha, ASSESS, RTL):

    dam chay THAT, luc gan nhat      diem Fire dinh 0.25   (4/717 khung >= 0.20)
    nen be tong xam sau khi dau      diem Fire dinh 0.607  <- DUONG TINH GIA
    moi khung con lai                diem Fire <= 0.03

Tuc la o nguong 0.35 mac dinh, thu DUY NHAT ca chuyen bay hien ra la mot dam
chay khong ton tai. Vi vay:

  1. `max_box_frac` vut hop phu qua 25% khung hinh - dung cai duong tinh gia
     tren, no phu KIN man hinh.
  2. `run_sim.sh` cham nguong xuong 0.20 CHI cho mo phong (TRACK_CONF). Mac
     dinh 0.35 o day giu nguyen cho camera that, la thu model duoc hoc.

Va nhac lai cho ro: hop nay chi de NGUOI XEM. Quyet dinh tha bong van do
`fire_detector` (nguong HSV do duoc) - dung model nay de nham muc tieu la
lay mot bo phat hien 4/717 khung thay muc tieu, thay cho mot bo dang chay dung.
Muon dung that thi phai hoc them tren chinh khung hinh Gazebo.
"""

import argparse
import time

import cv2
import numpy as np

# Ten lop lay tu metadata cua chinh file .onnx (xem `names` trong metadata_props).
# KHONG viet cung o day: xuat lai model voi bo lop khac ma quen sua thi hop cu
# nhan nham ten - hong cam, kieu te nhat.
CLASS_FALLBACK = {0: "Fire", 1: "Smoke"}
COLORS = {"Fire": (40, 90, 230), "Smoke": (190, 170, 120)}  # BGR
COLOR_OTHER = (200, 200, 200)


def letterbox(img, size=640, pad=114):
    """Resize giu ti le roi dem vien - dung phep tien xu ly cua Ultralytics.

    Tra ve (anh_640, ti_le, dx, dy) de doi nguoc toa do hop ve anh goc. Resize
    thang (khong giu ti le) cung chay va cung ra hop, chi la hop lech he thong
    theo phuong bi keo gian: anh 640x480 keo thanh 640x640 la moi vat cao them
    33%, model thay mot ngon lua deo hon moi ngon lua no tung hoc.
    """
    h, w = img.shape[:2]
    r = min(size / w, size / h)
    nw, nh = round(w * r), round(h * r)
    dx, dy = (size - nw) // 2, (size - nh) // 2
    out = np.full((size, size, 3), pad, dtype=np.uint8)
    out[dy:dy + nh, dx:dx + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return out, r, dx, dy


def decode(raw, r, dx, dy, w, h, conf_min, iou_nms, max_box_frac=0.25):
    """[1, 4+nc, 8400] -> [(x1, y1, x2, y2, ten_lop, diem)] tren toa do anh goc.

    Xuat voi nms=False nen NMS phai lam o day. 8400 hop la 80x80 + 40x40 +
    20x20 o luoi ba tang; gan het la rac diem ~0, loc nguong TRUOC roi moi NMS
    thi nhanh hon hai bac.
    """
    p = raw[0].T                      # [8400, 4+nc]
    scores = p[:, 4:]
    best = scores.max(axis=1)
    keep = best >= conf_min
    if not keep.any():
        return []
    p, best = p[keep], best[keep]
    cls = scores[keep].argmax(axis=1)

    # cx,cy,w,h (he 640, da letterbox) -> x,y,w,h (he anh goc)
    cx, cy, bw, bh = p[:, 0], p[:, 1], p[:, 2], p[:, 3]
    x = (cx - bw / 2 - dx) / r
    y = (cy - bh / 2 - dy) / r
    bw, bh = bw / r, bh / r

    boxes = np.stack([x, y, bw, bh], axis=1)
    idx = cv2.dnn.NMSBoxes(boxes.tolist(), best.tolist(), conf_min, iou_nms)
    out = []
    for i in np.array(idx).flatten():
        bx, by, bwi, bhi = boxes[i]
        # Cat ve trong khung: hop trum ra ngoai mep anh la binh thuong (ngon lua
        # bi cat boi mep), nhung ve ra ngoai thi OpenCV im lang bo net.
        x1, y1 = max(0, int(bx)), max(0, int(by))
        x2, y2 = min(w - 1, int(bx + bwi)), min(h - 1, int(by + bhi))
        if x2 <= x1 or y2 <= y1:
            continue
        # VUT HOP QUA TO. Cung luat `max_blob_frac` ma fire_detector ben
        # firedrop_sim dung, va vi cung mot ly do da do duoc: diem "Fire" CAO
        # NHAT cua ca mot chuyen bay la 0.607 tren mot khung phu kin man hinh
        # nen be tong xam, luc drone da dau va camera nhin canh quat cua chinh
        # no. Dam chay THAT trong cung chuyen do chi duoc 0.25. Ha nguong de
        # thay dam chay ma khong co luat nay thi thu duy nhat GUI hien ra la cai
        # dam chay khong ton tai, voi diem cao gap doi dam chay that.
        if (x2 - x1) * (y2 - y1) > max_box_frac * w * h:
            continue
        out.append((x1, y1, x2, y2, int(cls[i]), float(best[i])))
    return out


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix = max(0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    return inter / ((ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter)


class Track:
    __slots__ = ("id", "box", "cls", "score", "hits", "miss")

    def __init__(self, tid, box, cls, score):
        self.id, self.box, self.cls, self.score = tid, box, cls, score
        self.hits, self.miss = 1, 0


class Tracker:
    """Ghep hop giua cac khung bang IoU. Xem docstring dau file ve pham vi."""

    def __init__(self, iou_min=0.2, confirm_hits=2, max_miss=5):
        self.iou_min, self.confirm_hits, self.max_miss = iou_min, confirm_hits, max_miss
        self.tracks: list[Track] = []
        self._next = 1

    def update(self, dets):
        """dets = [(x1,y1,x2,y2,cls,score)] -> danh sach Track DA XAC NHAN."""
        chua_ghep = list(self.tracks)
        # Ghep tham lam theo diem giam dan: hop chac an duoc chon truoc, nen mot
        # hop rac diem thap khong the cuop mat so hieu cua vet dang bam tot.
        for x1, y1, x2, y2, cls, score in sorted(dets, key=lambda d: -d[5]):
            box = (x1, y1, x2, y2)
            hop = [t for t in chua_ghep if t.cls == cls]
            t = max(hop, key=lambda t: iou(t.box, box), default=None)
            if t is not None and iou(t.box, box) >= self.iou_min:
                t.box, t.score, t.miss = box, score, 0
                t.hits += 1
                chua_ghep.remove(t)
            else:
                self.tracks.append(Track(self._next, box, cls, score))
                self._next += 1

        for t in chua_ghep:
            t.miss += 1
        self.tracks = [t for t in self.tracks if t.miss <= self.max_miss]
        return [t for t in self.tracks if t.hits >= self.confirm_hits and t.miss == 0]


class FireTracker:
    """Nap model mot lan, moi khung goi `draw(img)`. An toan de goi tu mot thread.

    Suy dien CHAM (YOLO11n 640 tren CPU ~40-60 ms). Goi tu dung thread dang doc
    camera la co y: no lam cham vong doc, ma vong doc thi chi giu KHUNG MOI NHAT
    (QoS depth 1 ben ROS, CAP_PROP_BUFFERSIZE 1 ben USB) - nen anh huong duy nhat
    la fps giam, khong bao gio la do tre troi. Dua sang thread rieng se cho fps
    cao hon nhung hop ve len khung KHAC voi khung da suy dien, tuc lech - dung
    cai thu ma ca file nay sinh ra de tranh.
    """

    def __init__(self, model_path, conf=0.35, iou_nms=0.45, max_box_frac=0.25,
                 providers=None):
        import onnxruntime as ort

        self.sess = ort.InferenceSession(
            str(model_path), providers=providers or ["CPUExecutionProvider"]
        )
        self.inp = self.sess.get_inputs()[0].name
        self.size = self.sess.get_inputs()[0].shape[2] or 640
        self.conf, self.iou_nms, self.max_box_frac = conf, iou_nms, max_box_frac
        self.names = self._names()
        self.tracker = Tracker()
        self.ms = 0.0  # thoi gian suy dien khung cuoi, de hien len HUD

    def _names(self):
        meta = self.sess.get_modelmeta().custom_metadata_map or {}
        try:
            return {int(k): v for k, v in eval(meta["names"]).items()}  # noqa: S307
        except Exception:
            # Model khong kem metadata (hay kem kieu la) van chay duoc, chi la
            # hop mang ten mac dinh. Bo qua trong im lang thi sai o day se doi
            # lot thanh "model phat hien nham lop" - nen phai keu.
            print("[track] khong doc duoc `names` trong model - dung ten mac dinh",
                  flush=True)
            return dict(CLASS_FALLBACK)

    def infer(self, img):
        """BGR uint8 -> danh sach Track da xac nhan cua khung nay."""
        t0 = time.monotonic()
        lb, r, dx, dy = letterbox(img, self.size)
        blob = np.ascontiguousarray(
            lb[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        )
        raw = self.sess.run(None, {self.inp: blob})[0]
        h, w = img.shape[:2]
        dets = decode(raw, r, dx, dy, w, h, self.conf, self.iou_nms, self.max_box_frac)
        self.ms = (time.monotonic() - t0) * 1000.0
        return self.tracker.update(dets)

    def draw(self, img):
        """Suy dien roi ve TAI CHO len `img`. Tra ve so vet dang bam."""
        tracks = self.infer(img)
        for t in tracks:
            name = self.names.get(t.cls, f"lop{t.cls}")
            color = COLORS.get(name, COLOR_OTHER)
            x1, y1, x2, y2 = t.box
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            _nhan(img, f"#{t.id} {name} {t.score:.2f}", x1, y1, color)
        _hud(img, f"{len(tracks)} vet | {self.ms:.0f} ms")
        return len(tracks)


def _nhan(img, text, x, y, color):
    """Nhan tren canh tren cua hop, lat xuong duoi khi hop cham mep tren anh."""
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    ty = y - th - 4 if y - th - 4 >= 0 else y + 2
    cv2.rectangle(img, (x, ty), (x + tw + 4, ty + th + 4), color, -1)
    cv2.putText(img, text, (x + 2, ty + th + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (20, 20, 20), 1, cv2.LINE_AA)


def _hud(img, text):
    """Mot dong o goc duoi-trai. KHONG co hop nao cung phai hien, no la bang
    chung "model dang chay ma khong thay gi" - khac han voi "model chet"."""
    h = img.shape[0]
    cv2.putText(img, text, (8, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, (8, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (230, 230, 230), 1, cv2.LINE_AA)


def demo(model=None):
    """Tu kiem. Phan hinh hoc chay khong can model; co model thi nap va do luon."""
    # letterbox: giu ti le, va doi nguoc toa do phai ve dung cho cu
    img = np.zeros((480, 640, 3), np.uint8)
    lb, r, dx, dy = letterbox(img, 640)
    assert lb.shape == (640, 640, 3) and (dx, dy) == (0, 80), (lb.shape, dx, dy)
    assert abs(r - 1.0) < 1e-9, r

    # mot hop giua anh 640 phai giai ma ve dung giua anh 640x480 goc
    raw = np.zeros((1, 6, 1), np.float32)
    raw[0, :4, 0] = [320, 320, 64, 64]   # cx, cy, w, h trong he 640 da letterbox
    raw[0, 4, 0] = 0.9                   # lop 0 = Fire
    (x1, y1, x2, y2, cls, score), = decode(raw, r, dx, dy, 640, 480, 0.35, 0.45)
    assert (x1, y1, x2, y2) == (288, 208, 352, 272), (x1, y1, x2, y2)
    assert cls == 0 and abs(score - 0.9) < 1e-6

    # diem duoi nguong thi khong ra hop nao
    raw[0, 4, 0] = 0.10
    assert decode(raw, r, dx, dy, 640, 480, 0.35, 0.45) == []

    # hop phu qua max_box_frac bi vut, du diem RAT cao - day la duong tinh gia
    # 0.607 tren nen be tong do duoc that (xem docstring dau file)
    to = np.zeros((1, 6, 1), np.float32)
    to[0, :4, 0] = [320, 320, 640, 640]   # phu kin ca khung
    to[0, 4, 0] = 0.99
    assert decode(to, r, dx, dy, 640, 480, 0.35, 0.45) == []
    # cung hop do nhung tat luat (frac 1.0) thi phai ra - de chac la bi vut
    # VI QUA TO, khong phai vi mot loi hinh hoc nao khac
    assert len(decode(to, r, dx, dy, 640, 480, 0.35, 0.45, max_box_frac=1.0)) == 1

    assert abs(iou((0, 0, 10, 10), (0, 0, 10, 10)) - 1.0) < 1e-9
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert abs(iou((0, 0, 10, 10), (5, 0, 15, 10)) - (50 / 150)) < 1e-9

    # Tracker: phai giu so hieu qua cac khung, va chi ve sau `confirm_hits`
    tr = Tracker(confirm_hits=2, max_miss=2)
    d = [(10, 10, 50, 50, 0, 0.9)]
    assert tr.update(d) == [], "khung dau tien chua duoc xac nhan"
    (t,) = tr.update([(12, 12, 52, 52, 0, 0.9)])
    assert t.id == 1
    (t2,) = tr.update([(14, 14, 54, 54, 0, 0.9)])
    assert t2.id == 1, "cung mot dam chay phai giu nguyen so hieu"

    # mat dau -> khong ve nua, nhung con song du `max_miss` khung roi moi xoa
    assert tr.update([]) == [] and len(tr.tracks) == 1
    assert tr.update([]) == [] and len(tr.tracks) == 1
    assert tr.update([]) == [] and tr.tracks == []

    # lop khac thi KHONG ghep, du hop trung khit
    tr2 = Tracker(confirm_hits=1)
    (a,) = tr2.update([(0, 0, 40, 40, 0, 0.9)])
    ids = {t.id for t in tr2.update([(0, 0, 40, 40, 1, 0.9)])}
    assert a.id not in ids, "Fire va Smoke chong nhau khong duoc dung chung vet"

    print("fire_tracker (hinh hoc + bam vet): TAT CA DAT")

    if model:
        ft = FireTracker(model)
        anh = np.random.randint(0, 255, (480, 640, 3), np.uint8)
        t0 = time.monotonic()
        n = ft.draw(anh)
        print(f"nap {model}")
        print(f"lop: {ft.names}")
        print(f"mot khung 640x480: {(time.monotonic()-t0)*1000:.0f} ms, {n} vet")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", default=None, help="duong dan .onnx de do luon toc do")
    demo(p.parse_args().model)
