"""Doc mot file log thanh chuoi thoi gian de ve do thi va quy dao.

Hai dinh dang, cung mot ket qua:

  * .tlog — luong MAVLink laptop ghi lai. Chi co cai da CHAY QUA SONG.
  * .bin  — log FC tu ghi ra the SD (dataflash). Nhip vong lap, day du cac thu
    khong bao gio len duoc duong truyen: OF, RATE, PID*, XKF*, PSC*, CTUN.

Ten field khac nhau vi hai ben dat ten khac nhau — ATTITUDE.roll (MAVLink) va
ATT.Roll (dataflash), OPTICAL_FLOW.flow_rate_x va OF.flowX. KHONG doi ten cho
giong nhau: doi la bia ra mot bang tra cuu phai nuoi, va la cat duong ve tai
lieu ArduPilot ma nguoi dung dang doc song song.

Khong import Qt: doc log la viec tinh toan thuan, tach ra day thi selfcheck goi
duoc truc tiep khong can dung mot QApplication nao.

Vi sao doc thang file chu khong lay tu bus: bus chi mang gia tri DANG chay, va
core/field.py chi giu gia tri moi nhat cua tung field. Ve do thi thi phai co ca
lich su, ma lich su thi chi nam trong file.

Loc `from_autopilot` giong het duong live (nguyen tac 2.4): tren SITL co ca
MAVROS va MAVProxy phat len cung mot duong, khong loc thi do thi tron ba nguon
vao nhau va khong con doi chieu duoc voi tai lieu ArduPilot. Ban .bin khong qua
bo loc do — xem _wanted().
"""

import bisect
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
               "custom_mode", "time_boot_ms", "time_usec", "time_unix_usec",
               "TimeUS")  # TimeUS: dau thoi gian cua .bin — ve ra la mot duong doc


# Cua so cua che do truc tiep. Giu ca chuyen bay trong RAM thi 300 field x 50 Hz
# se phinh khong gioi han; mot phut du de nhin mot dao dong hay mot cu sut ap, con
# muon xem lai ca chuyen thi log da nam san trong logs/ roi.
LIVE_WINDOW = 60.0


def _wanted(msg, name):
    """Goi nay co dua vao do thi khong?

    .tlog la mot luong MAVLink dung chung: tren SITL co ca MAVROS va MAVProxy
    phat len cung duong, phai loc bang from_autopilot (nguyen tac 2.4).

    .bin thi khong. No la log FC TU ghi ra the SD, theo dinh nghia chi co du lieu
    cua chinh no — khong co nguon thu hai nao de ma loc. Va DFMessage khong co
    `get_srcComponent`: goi from_autopilot vao no la AttributeError ngay ban ghi
    dau tien, tuc ca file bi bao "khong doc duoc log" trong khi no doc duoc tron
    ven. `hasattr` chinh la cau hoi "day co phai goi MAVLink khong".
    """
    if name == "BAD_DATA" or name.startswith("UNKNOWN_"):
        return False
    if name == "LOG_DATA":
        # Mot file .bin dang duoc keo ve qua duong truyen, khong phai telemetry.
        # De lot vao thi 90 field "LOG_DATA.data[i]", moi field hang tram nghin
        # diem — vai GB RAM cho mot thu khong ai ve do thi bao gio.
        return False
    return not hasattr(msg, "get_srcComponent") or from_autopilot(msg)


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
        # Ban .bin goi la PARM, ten/gia tri o "Name"/"Value" — cung mot thu, cung
        # phai tach. Do that tren "20 1-1-1980 7-00-00 AM.bin": de mac dinh thi
        # 1078 tham so do chung vao mot duong "PARM.Value" nhay tu 120 xuong 0.
        if name in ("PARAM_VALUE", "PARM"):
            pid = d.get("param_id", d.get("Name"))
            val = d.get("param_value", d.get("Value"))
            if isinstance(pid, bytes):
                pid = pid.decode("ascii", "ignore")
            pid = str(pid or "").strip("\x00").strip()
            if pid and _numeric(val):
                self._put(f"PARAM.{pid}", t, float(val))
            return

        for k, v in d.items():
            if k == "mavpackettype" or k.endswith(SKIP_SUFFIX) or not _numeric(v):
                continue
            self._put(f"{name}.{k}", t, float(v))

        if name == "GLOBAL_POSITION_INT":
            self.track.append((t, d["lat"] / 1e7, d["lon"] / 1e7,
                               d["relative_alt"] / 1000.0))
        elif name == "POS":
            # Ban .bin. POS la vi tri EKF da hop nhat — cung thu Mission Planner
            # ve len ban do, khong phai GPS tho. DFReader da nhan he so san nen
            # Lat/Lng ra thang do va RelHomeAlt ra thang met, khong chia 1e7.
            #
            # Log bay trong nha khong co POS (do that tren file 30 MB o Downloads:
            # 0 ban ghi POS, chi co OF/RFND/SURF). `has_fix` bat duoc chuyen do va
            # tab noi "log nay khong co dinh vi" — dung duong da co san cho .tlog.
            self.track.append((t, d["Lat"], d["Lng"], d.get("RelHomeAlt", 0.0)))

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


class LiveData(LogData):
    """Chuoi thoi gian DANG chay, gom tu bus topic "status".

    Cung names()/series()/local_track() nhu LogData, nen ben ve khong can biet
    nguon la file hay duong truyen — do la ly do ke thua chu khong viet lop moi.

    Khac LogData o hai cho: du lieu vao la dict da trai phang ("MSG.field" ->
    so, xem flatten_status trong core/adapters/sik.py) chu khong phai msg thô,
    va chi giu `window` giay gan nhat.
    """

    def __init__(self, window=LIVE_WINDOW):
        super().__init__("live")
        self.window = window
        self.feeds = 0  # so envelope da nhan — de do nhip goi ve
        self._rate_mark = (time.monotonic(), 0, 0.0)  # (luc do, so goi luc do, hz)
        self._names = None  # cache cua names(), None = phai sap xep lai

    def feed(self, env):
        """Nhan mot envelope topic "status". Goi o main thread, phai re."""
        ts = env["ts"]
        if self.t0 is None:
            self.t0 = ts
        t = ts - self.t0
        # Dong ho FC va dong ho laptop khong dong bo tuyet doi; goi den muon hon
        # goi truoc thi t lui lai, ma chuoi lui thi bisect trong trim() sai va do
        # thi ve nguoc. Kep lai la du: sai so vai ms, khong doc ra duoc tren man.
        t = max(t, self.duration)
        self.duration = t
        self.feeds += 1
        self.parsed += 1

        for k, v in env["data"].items():
            if k.endswith(SKIP_SUFFIX) or not _numeric(v):
                continue
            if k not in self.fields:
                self._names = None  # co ten moi -> danh sach phai sap xep lai
            self._put(k, t, float(v))

        lat = env["data"].get("GLOBAL_POSITION_INT.lat")
        lon = env["data"].get("GLOBAL_POSITION_INT.lon")
        alt = env["data"].get("GLOBAL_POSITION_INT.relative_alt")
        if lat is not None and lon is not None and alt is not None:
            self.track.append((t, lat / 1e7, lon / 1e7, alt / 1000.0))

    def names(self):
        """Nhu LogData.names() nhung dung lai ket qua.

        Ben ve hoi moi nhip (20 Hz), con danh sach thi hau nhu khong bao gio doi:
        ten moi chi xuat hien khi FC bat dau gui mot message chua tung gui. sorted()
        tren 254 ten moi 50 ms la tra tien cho mot cau tra loi khong doi.
        """
        if self._names is None:
            self._names = sorted(self.fields)
        return self._names

    def trim(self):
        """Bo diem cu hon cua so.

        Goi o NHIP VE chu khong goi moi goi: mot goi cham vao vai field, con trim
        thi phai duyet ca ~300 field — lam moi goi la 50 lan/giay duyet thua.
        """
        cut = self.duration - self.window
        if cut <= 0:
            return
        for ts, vs in self.fields.values():
            i = bisect.bisect_left(ts, cut)
            if i:
                del ts[:i]
                del vs[:i]
        if self.track and self.track[0][0] < cut:
            self.track = [p for p in self.track if p[0] >= cut]

    def rate(self):
        """Goi/giay, do tren cua so it nhat 0.5 giay. 0 = duong truyen da im.

        Hoi hai lan sat nhau phai ra CUNG mot so, khong duoc ra 0: hoi hai lan
        trong mot khung hinh (ve lai + doi ngon ngu) tung lam cua so do bang ~0
        va man hinh bao "0 goi/s" mau canh bao trong luc FC van dang gui 60 goi
        moi giay. Nen giu lai tri da tinh chu khong tinh lai tren dt ti hon.
        """
        now = time.monotonic()
        last_t, last_n, hz = self._rate_mark
        dt = now - last_t
        if dt >= 0.5:
            hz = (self.feeds - last_n) / dt
            self._rate_mark = (now, self.feeds, hz)
        return hz


def load(path, limit_seconds=None):
    """Doc het mot file log (.tlog hay .bin). limit_seconds: chi doc phan dau.

    ponytail: nap ca file vao RAM roi moi thua diem ra (_decimate o cuoi). Do that
    26/08/2026 tren .bin 30 MB / 632k ban ghi: 12,9 s va vai tram MB dinh. Du cho
    log bay that, va _Loader chay o thread rieng nen giao dien khong dong bang.
    Ngay nao mo mot .bin hang tram MB (log SITL de chay qua dem) thi phai thua
    diem NGAY TRONG vong doc — khong phai truoc do.
    """
    log = LogData(path)
    started = time.monotonic()
    master = mavutil.mavlink_connection(str(path))

    while True:
        msg = master.recv_match(blocking=False)
        if msg is None:
            break
        name = msg.get_type()
        if not _wanted(msg, name):
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
