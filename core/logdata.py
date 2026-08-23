"""Doc mot file .tlog thanh chuoi thoi gian de ve do thi va quy dao.

Khong import Qt: doc log la viec tinh toan thuan, tach ra day thi selfcheck goi
duoc truc tiep khong can dung mot QApplication nao.

Vi sao doc thang file chu khong lay tu bus: bus chi mang gia tri DANG chay, va
core/field.py chi giu gia tri moi nhat cua tung field. Ve do thi thi phai co ca
lich su, ma lich su thi chi nam trong file.

Loc `from_autopilot` giong het duong live (nguyen tac 2.4): tren SITL co ca
MAVROS va MAVProxy phat len cung mot duong, khong loc thi do thi tron ba nguon
vao nhau va khong con doi chieu duoc voi tai lieu ArduPilot.
"""

import time

from pymavlink import mavutil

from core.adapters.sik import from_autopilot

# Tran diem MOI FIELD. Chuyen 20 phut o 10 Hz la 12000 diem — con thua. Qua tran
# thi lay thua ra chu khong cat duoi: cat duoi la mat doan cuoi, dung doan hay
# hong nhat. Man hinh khong ve noi 20000 diem rieng biet nen khong mat gi ca.
# ponytail: lay thua deu, khong min/max theo o. Doi neu can nhin gai nhon ngan.
MAX_POINTS = 20000

# Nhung field khong co nghia khi ve: co bit, ma so, dau thoi gian.
SKIP_SUFFIX = ("_id", "type", "seq", "mavtype", "autopilot", "base_mode",
               "custom_mode", "time_boot_ms", "time_usec", "time_unix_usec")


def _numeric(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class LogData:
    """Chuoi thoi gian doc tu mot .tlog.

    fields: ten -> (t giay tinh tu dau log, gia tri). Ten dang "MSG.field",
            rieng tham so la "PARAM.<TEN>" — xem chu thich o _feed().
    track:  (t, lat, lon, alt_rel) tu GLOBAL_POSITION_INT.
    """

    def __init__(self, path):
        self.path = str(path)
        self.fields = {}
        self.track = []
        self.counts = {}
        self.t0 = None
        self.duration = 0.0
        self.parsed = 0
        self.load_seconds = 0.0

    # ------------------------------------------------------------------ doc

    def _feed(self, name, d, t):
        self.counts[name] = self.counts.get(name, 0) + 1

        # PARAM_VALUE: gop chung mot duong thi vo nghia — mot duong nhay lung
        # tung qua 1400 tham so khac nhau. Tach theo TEN tham so moi ra duoc cai
        # ArduPilot goi la "do thi tham so".
        if name == "PARAM_VALUE":
            pid = d.get("param_id")
            if isinstance(pid, bytes):
                pid = pid.decode("ascii", "ignore")
            pid = str(pid or "").strip("\x00").strip()
            if pid and _numeric(d.get("param_value")):
                self._put(f"PARAM.{pid}", t, float(d["param_value"]))
            return

        for k, v in d.items():
            if k == "mavpackettype" or k.endswith(SKIP_SUFFIX) or not _numeric(v):
                continue
            self._put(f"{name}.{k}", t, float(v))

        if name == "GLOBAL_POSITION_INT":
            self.track.append((t, d["lat"] / 1e7, d["lon"] / 1e7,
                               d["relative_alt"] / 1000.0))

    def _put(self, key, t, v):
        ts, vs = self.fields.setdefault(key, ([], []))
        ts.append(t)
        vs.append(v)

    def _decimate(self):
        for key, (ts, vs) in self.fields.items():
            if len(ts) > MAX_POINTS:
                step = len(ts) // MAX_POINTS + 1
                self.fields[key] = (ts[::step], vs[::step])

    # ------------------------------------------------------------------ hoi

    def names(self):
        return sorted(self.fields)

    def series(self, name):
        return self.fields.get(name, ([], []))

    @property
    def has_fix(self):
        """Log nay co diem nao ĐUOC dinh vi that khong?"""
        return len(self.fixed_track()) >= 2

    def fixed_track(self):
        """Chi nhung diem CO fix GPS.

        FC bao lat=lon=0 khi chua bat duoc fix, chu khong bo trong truong. Tron
        chung vao thi quy dao keo tu cho bay toi giua Dai Tay Duong: do that tren
        logs/20260807-150529-sim.tlog — "trai rong 16.605 km" cho mot chuyen bay
        SITL quanh san. Cung phep loc `if lat or lon` dang dung cho muc nhiem vu
        o map_widget.py.

        Bo diem thi KHONG duoc am tham ve 0: xem `has_fix` — giao dien phai noi
        ro "log nay khong co dinh vi" chu khong ve mot duong thang dung roi de
        nguoi doc tuong do la quy dao that.
        """
        return [p for p in self.track if p[1] or p[2]]

    def local_track(self):
        """Quy dao ra met: (t, dong, bac, cao) so voi diem co fix dau tien.

        Phep chieu mat phang tiep tuyen, khong phai haversine tung diem: o pham vi
        vai km sai so duoi mot met, va do thi 3D thi khong ai doc toi met. Doi
        sang haversine neu bao gio bay xa hang tram km.
        """
        track = self.fixed_track()
        if len(track) < 2:
            return [], [], [], []
        import math

        _, lat0, lon0, _ = track[0]
        m_per_deg_lat = 111320.0
        m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))
        t, e, n, u = [], [], [], []
        for ts, lat, lon, alt in track:
            t.append(ts)
            e.append((lon - lon0) * m_per_deg_lon)
            n.append((lat - lat0) * m_per_deg_lat)
            u.append(alt)
        return t, e, n, u


def load(path, limit_seconds=None):
    """Doc het mot .tlog. limit_seconds: chi doc phan dau, dung cho kiem tra."""
    log = LogData(path)
    started = time.monotonic()
    master = mavutil.mavlink_connection(str(path))

    while True:
        msg = master.recv_match(blocking=False)
        if msg is None:
            break
        name = msg.get_type()
        if name == "BAD_DATA" or name.startswith("UNKNOWN_") or not from_autopilot(msg):
            continue
        ts = getattr(msg, "_timestamp", None)
        if ts is None:
            continue
        if log.t0 is None:
            log.t0 = ts
        t = ts - log.t0
        if limit_seconds is not None and t > limit_seconds:
            break
        log.parsed += 1
        log._feed(name, msg.to_dict(), t)
        log.duration = t

    log._decimate()
    log.load_seconds = time.monotonic() - started
    return log
