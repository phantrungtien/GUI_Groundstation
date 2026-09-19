"""Nguong canh bao cho thanh telemetry: pin can va GPS mat fix.

Chi con phan NGUONG, khong con widget: thanh telemetry duoc ve bang QML o man
bay cam ung, doc `Backend.state["battLevel"]/["gpsLevel"]`. Hai ham duoi day la
cho quyet dinh muc — mot con so dung tren nen trang khong tu keo mat ai ca.
"""

# --- NUM CHINH ------------------------------------------------------------
# Nguong pin tinh theo PHAN TRAM FC bao, khong theo dien ap. Dien ap mot minh
# khong noi len con bao nhieu neu khong biet so cell — va so cell doi that:
# ba chuyen bay that gan day do duoc 16,8 V / 15,2 V / 11,7 V, tuc 4S va 3S xen
# ke nhau. Dat nguong dien ap cung la sai o it nhat mot trong ba chuyen do.
# FC thi biet BATT_CAPACITY va so cell nen phan tram cua no moi la con so co
# nghia (ba chuyen tren FC bao 98%, 99%, 77-81% — co bao that).
# Hai con so nay KHONG duoc tu nghi ra: chung phai khop voi bang nguong o muc F
# cua docs/operating_procedure.md ("< 30% goi ve", "< 20% RTL ngay, khong thuong
# luong"). Giao dien to mau o mot nguong khac voi quy trinh la day nguoi bay ra
# hai quyet dinh khac nhau cho cung mot con so.
BATT_WARN_PCT = 30
BATT_CRIT_PCT = 20
# Thoi gian bay con lai = mAh con toi muc failsafe / dong dien dang an. Do that
# 19/09 (log 145229): theo toc do tut % thi phai cho ~3 phut moi co so, vi FC
# bao % theo buoc 1%. Theo dong dien thi co ngay tu luc ARM.
LEFT_MIN_A = 0.1  # duoi muc nay la nhieu cam bien, chia ra hang tram gio vo nghia
LEFT_WARN_S = 180
LEFT_CRIT_S = 60
# GPS: ba dieu kien, giong het muc D.4 cua docs/operating_procedure.md
# ("Fix >= 3D, so ve tinh >= 8, HDOP < 2"). Truoc day muon doc du ba thu phai
# sang tab Trang thai loc "GPS" va doc ba hang — dung luc sap cat canh.
#
# Ba cai deu can, khong cai nao thay duoc cai nao: fix_type=3 voi 5 ve tinh la
# fix mong manh, con HDOP cao la ve tinh dong nhung xep thanh mot cum tren troi
# nen giao diem nhoe ra. Do that tren ban: fix_type=1, sats=0 — dem ve tinh mot
# minh thi o do hien so 0 trang tinh nhu moi so khac.
GPS_MIN_FIX = 3  # 3 = 3D fix. 2 = chi 2D (khong co do cao GPS) -> canh bao.
GPS_MIN_SATS = 8
GPS_MAX_HDOP = 2.0

def batt_level(pct):
    """Muc canh bao pin tu phan tram FC bao. None = FC khong bao -> khong doan."""
    if pct is None:
        return None
    if pct <= BATT_CRIT_PCT:
        return "crit"
    return "warn" if pct <= BATT_WARN_PCT else None


def reserve_mah(cap, low_mah, crt_mah):
    """Muc failsafe tinh bang mAh: BATT_LOW_MAH, khong co thi BATT_CRT_MAH.

    Ca hai = 0 la FC tat failsafe theo mAh (do that tren MicoAir743 07/09: ca hai
    deu 0) — luc do lay BATT_CRIT_PCT cua dung luong, khop quy trinh muc F.
    """
    for r in (low_mah, crt_mah):
        if r:
            return r
    return cap * BATT_CRIT_PCT / 100 if cap else None


def time_left_s(cap, consumed, pct, reserve, amps):
    """Giay bay con lai toi muc failsafe, theo dong dien dang an. None = khong noi duoc.

    mAh con lai lay tu `consumed` (FC dem bang dong dien) neu co, khong thi tu %.
    """
    if not cap or reserve is None or amps is None or amps < LEFT_MIN_A:
        return None
    if consumed is not None:
        left = cap - consumed
    elif pct is not None:
        left = cap * pct / 100
    else:
        return None
    return max(0, int((left - reserve) / (amps * 1000) * 3600))


def left_level(sec):
    if sec is None:
        return None
    if sec <= LEFT_CRIT_S:
        return "crit"
    return "warn" if sec <= LEFT_WARN_S else None


def gps_level(fix, sats=None, hdop=None):
    """Muc canh bao GPS. Tra (muc, ly_do) — ly_do la key trong bang chu, hay None.

    Ly do phai tra ra ngoai chu khong nuot: o chi rong bang mot con so, nen thu
    duy nhat noi duoc "vi sao vang" la tooltip, ma tooltip thi phai biet dieu
    kien nao truot. Bao vang ma khong noi vi sao thi nguoi bay lai phai sang tab
    Trang thai doc tay — dung cai vong lap muc D.4 dang bat ho lam.
    """
    if fix is None:
        return None, None
    if fix < 2:
        return "crit", f"tlm.fix{int(fix)}"  # 0 khong co GPS, 1 chua bat duoc fix
    if fix < GPS_MIN_FIX:
        return "warn", f"tlm.fix{int(fix)}"
    if sats is not None and sats < GPS_MIN_SATS:
        return "warn", "tlm.few_sats"
    if hdop is not None and hdop >= GPS_MAX_HDOP:
        return "warn", "tlm.bad_hdop"
    return None, f"tlm.fix{int(fix)}"
