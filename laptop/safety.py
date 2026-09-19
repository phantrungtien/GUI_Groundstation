"""Canh bao an toan tu tham so FC: ve nha kip khong, failsafe co bat khong, pin co day khong.

Chi co logic, khong co Qt — man bay (`touch/backend.py`) goi vao va ve ra. Moi ham
nhan `params` la dict ten -> gia tri FC tra ve (xem WATCH_PARAMS trong
core/adapters/sik.py) va tra ve None khi thieu so lieu: KHONG doan.
"""

import math

# --- ve nha ------------------------------------------------------------------
# Du tru tren thoi gian RTL uoc tinh: bo qua gia toc, gio, va vong xoay mui. Con
# lai <= can + RTL_CRIT_S -> "VE NHA NGAY"; <= can + RTL_WARN_S -> "sap phai ve".
RTL_CRIT_S = 30
RTL_WARN_S = 90

# --- pin ---------------------------------------------------------------------
CELL_MAX_V = 4.25   # so cell = tran(V / 4.25): 4S day 16,8 V -> 4; 3S can 10,5 V -> 3
# LOW_VOLT moi cell ngoai khoang nay la dat cho pin KHAC so cell. Do that tren
# MicoAir743 07/09: BATT_LOW_VOLT = 10,8 V (dung cho 3S) trong khi pin 4S -> 2,7 V/cell.
LOW_CELL_MIN_V, LOW_CELL_MAX_V = 3.3, 3.9
PLUG_GAP_PCT = 25   # FC tuong % cao hon % theo dien ap bay nhieu -> pin khong day luc cam
PLUG_MAX_A = 1.0    # chi so khi dong nho: co tai thi dien ap sut, % theo dien ap sai
# Dien ap nghi -> % cua LiPo (moi cell). Bang pho bien cua cac hang pin RC; LiHV
# (4,35 V) thi lech — do la ly do nguong PLUG_GAP_PCT rong chu khong chat.
LIPO_CURVE = ((4.20, 100), (4.15, 95), (4.11, 90), (4.08, 85), (4.02, 80), (3.98, 75),
              (3.95, 70), (3.91, 65), (3.87, 60), (3.85, 55), (3.84, 50), (3.82, 45),
              (3.80, 40), (3.79, 35), (3.77, 30), (3.75, 25), (3.73, 20), (3.71, 15),
              (3.69, 10), (3.61, 5), (3.27, 0))


def _p(params, new, old=None, scale=1.0):
    """Doc tham so ten moi (SI), khong co thi ten cu nhan `scale` (cm -> m)."""
    if params.get(new) is not None:
        return params[new]
    if old and params.get(old) is not None:
        return params[old] * scale
    return None


def rtl_time_s(params, dist_m, alt_m):
    """Giay de RTL tu (dist_m, alt_m) toi luc cham dat. None = thieu tham so.

    Theo dung chuoi buoc cua ArduCopter RTL: leo toi RTL_ALT (neu dang thap hon),
    bay ngang ve, lo lung RTL_LOIT_TIME, ha nhanh toi LAND_ALT_LOW, ha cham xuong dat.
    """
    if dist_m is None or alt_m is None:
        return None
    rtl_alt = _p(params, "RTL_ALT_M", "RTL_ALT", 0.01)
    wp = _p(params, "WP_SPD", "WPNAV_SPEED", 0.01)
    speed = _p(params, "RTL_SPEED_MS", "RTL_SPEED", 0.01) or wp  # 0 = dung WP_SPD
    up = _p(params, "WP_SPD_UP", "WPNAV_SPEED_UP", 0.01)
    dn = _p(params, "LAND_SPD_HIGH_MS", "LAND_SPEED_HIGH", 0.01) or \
        _p(params, "WP_SPD_DN", "WPNAV_SPEED_DN", 0.01)
    land = _p(params, "LAND_SPD_MS", "LAND_SPEED", 0.01)
    low = _p(params, "LAND_ALT_LOW_M", "LAND_ALT_LOW", 0.01) or 0.0
    loit = (params.get("RTL_LOIT_TIME") or 0) / 1000
    if None in (rtl_alt, speed, up, dn, land) or min(speed, up, dn, land) <= 0:
        return None
    top = max(rtl_alt, alt_m)
    low = min(low, top)
    return int((top - alt_m) / up + dist_m / speed + loit + (top - low) / dn + low / land)


def rtl_level(left_s, need_s):
    """'crit' = ve ngay, 'warn' = sap phai ve, None = con du."""
    if left_s is None or need_s is None:
        return None
    if left_s <= need_s + RTL_CRIT_S:
        return "crit"
    return "warn" if left_s <= need_s + RTL_WARN_S else None


def cells(volt):
    return math.ceil(volt / CELL_MAX_V) if volt and volt > 1 else None


def volt_pct(v_cell):
    """% pin theo dien ap nghi mot cell, noi suy tuyen tinh tren LIPO_CURVE."""
    if v_cell >= LIPO_CURVE[0][0]:
        return 100
    for (v1, p1), (v2, p2) in zip(LIPO_CURVE, LIPO_CURVE[1:]):
        if v_cell >= v2:
            return p2 + (p1 - p2) * (v_cell - v2) / (v1 - v2)
    return 0


def preflight(params, volt, pct, amps):
    """Canh bao truoc khi bay: [(key, kwargs)] cho bang chu. Rong = khong co gi.

    Goi khi CHUA ARM. Moi muc chi ra khi DA doc duoc tham so lien quan — tham so
    chua ve thi im lang, khong noi "tat" thay cho "chua biet".
    """
    out = []
    lo, cr = params.get("BATT_FS_LOW_ACT"), params.get("BATT_FS_CRT_ACT")
    if lo == 0 and cr == 0:
        out.append(("safe.fs_batt_off", {}))
    if params.get("FS_THR_ENABLE") == 0:
        out.append(("safe.fs_rc_off", {}))
    if params.get("FS_GCS_ENABLE") == 0:
        out.append(("safe.fs_gcs_off", {}))
    n = cells(volt)
    low_v = params.get("BATT_LOW_VOLT")
    if n and low_v:
        per = low_v / n
        if not LOW_CELL_MIN_V <= per <= LOW_CELL_MAX_V:
            out.append(("safe.low_volt_cells", {"v": low_v, "per": per, "n": n,
                                                "want": 3.5 * n}))
    if n and pct is not None and amps is not None and amps < PLUG_MAX_A:
        vp = volt_pct(volt / n)
        if pct - vp >= PLUG_GAP_PCT:
            out.append(("safe.not_full", {"vc": volt / n, "vp": vp, "pct": pct}))
    return out
