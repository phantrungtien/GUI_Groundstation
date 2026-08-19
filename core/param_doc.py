"""Tham so ArduCopter la gi — mot dong giai thich cho moi cai, hai thu tieng.

Tab Trang thai lam tooltip tu day: re chuot len hang `PARAM.*` la biet minh dang
nhin cai gi, khoi phai mo tai lieu ArduPilot o tab khac.

Ho PID KHONG viet tay tung cai. `ATC_RAT_{RLL,PIT,YAW}_{P,I,D,IMAX,FLTT,FLTE,
FLTD,SMAX}` la 24 cai chi khac nhau o hai manh — truc nao, he so nao — nen o day
ghep tu hai bang nho. Viet tay 24 dong giong nhau thi 24 co hoi go nham mot chu,
va them mot he so moi (ATC_RAT_RLL_FF chang han) la lai phai them ba dong nua.

Cai KHONG theo khuon (MOT_*, WPNAV_*, ANGLE_MAX...) thi ghi thang o EXPLICIT.

So lieu cu the (mac dinh, dai gia tri) co y KHONG ghi o day: chung doi theo
firmware va theo khung, ma dong chu nay thi khong. Muon con so thi nhin chinh
cot Gia tri ben canh.
"""

from core import i18n

# --- manh de ghep ho PID ---------------------------------------------------

AXIS = {
    "RLL": ("trục lăn (roll)", "roll axis"),
    "PIT": ("trục chúc (pitch)", "pitch axis"),
    "YAW": ("trục xoay (yaw)", "yaw axis"),
}

GAIN = {
    "P": ("hệ số P: sai số nhân thẳng ra lệnh. Tăng thì bám nhanh hơn, quá tay là rung",
          "P gain: error goes straight to the output. Higher tracks faster; too high oscillates"),
    "I": ("hệ số I: dồn sai số kéo dài, bù lệch trọng tâm và gió thổi một chiều",
          "I gain: accumulates steady error, trims out CG offset and steady wind"),
    "D": ("hệ số D: hãm theo tốc độ biến thiên, dập vọt lố. Quá tay là khuếch đại rung máy",
          "D gain: damps by rate of change, kills overshoot. Too high amplifies frame vibration"),
    "IMAX": ("trần của phần I: chặn không cho nó dồn vô hạn khi lệch lâu",
             "cap on the I term: stops it winding up without limit during a long error"),
    "FLTT": ("lọc thông thấp trên tín hiệu ĐẶT (Hz): làm mượt lệnh vào, tránh giật",
             "low-pass on the TARGET (Hz): smooths the demand so it does not step"),
    "FLTE": ("lọc thông thấp trên SAI SỐ (Hz): bớt nhiễu trước khi vào P và I",
             "low-pass on the ERROR (Hz): de-noises before it reaches P and I"),
    "FLTD": ("lọc thông thấp riêng cho khâu D (Hz): khâu D nhạy nhiễu nhất nên lọc riêng",
             "low-pass for the D term only (Hz): D is the noisiest term, so it filters separately"),
    "SMAX": ("trần tốc độ bẻ lái (slew): chặn PID đòi động cơ đổi nhanh hơn nó theo kịp",
             "slew-rate limit: stops the PID demanding faster motor changes than it can follow"),
}

PSC_GROUP = {
    "POSXY": ("Vòng VỊ TRÍ ngang", "Horizontal POSITION loop"),
    "POSZ": ("Vòng VỊ TRÍ đứng (độ cao)", "Vertical POSITION loop (altitude)"),
    "VELXY": ("Vòng TỐC ĐỘ ngang", "Horizontal VELOCITY loop"),
    "VELZ": ("Vòng TỐC ĐỘ đứng (lên/xuống)", "Vertical VELOCITY loop (climb/descend)"),
    "ACCZ": ("Vòng GIA TỐC đứng (khâu trong cùng, ra thẳng ga)",
             "Vertical ACCELERATION loop (innermost, feeds throttle directly)"),
}

# --- cai khong theo khuon --------------------------------------------------

EXPLICIT = {
    "MOT_THST_HOVER": (
        "Mức ga treo lơ lửng (0–1). FC tự học trong lúc bay và ghi lại; lệch nhiều so với "
        "0,3–0,5 nghĩa là khung quá nặng hoặc quá dư lực.",
        "Hover throttle (0–1). The FC learns this in flight and saves it; far outside 0.3–0.5 "
        "means the frame is overloaded or badly over-powered."),
    "MOT_SPIN_ARM": (
        "Mức ga cánh quay khi vừa ARM — chỉ để nhìn thấy là đã armed, chưa được sinh lực nâng.",
        "Motor output right after ARM — just enough to see it is armed, not enough to lift."),
    "MOT_SPIN_MIN": (
        "Ga tối thiểu khi ĐANG BAY. Đặt thấp quá thì động cơ tắt giữa không trung lúc hạ ga.",
        "Minimum motor output while FLYING. Too low and a motor stops mid-air on a throttle cut."),
    "MOT_SPIN_MAX": (
        "Ga tối đa dùng tới. Chừa phần đỉnh để FC còn chỗ điều chỉnh khi đã ga hết.",
        "Maximum motor output used. Leaves headroom so the FC can still correct at full throttle."),
    "INS_GYRO_FILTER": (
        "Lọc thông thấp con quay (Hz). Hạ xuống thì bớt nhiễu rung khung, nhưng thêm trễ — "
        "đây là núm đầu tiên nên chỉnh khi máy rung.",
        "Gyro low-pass (Hz). Lower cuts frame vibration noise but adds lag — the first knob to "
        "reach for when the airframe is vibrating."),
    "INS_ACCEL_FILTER": (
        "Lọc thông thấp gia tốc kế (Hz). Ảnh hưởng tới ước lượng độ cao và tốc độ đứng.",
        "Accelerometer low-pass (Hz). Feeds the altitude and climb-rate estimates."),
    "WPNAV_SPEED": (
        "Tốc độ ngang khi bay AUTO theo đường bay (cm/s).",
        "Horizontal speed along a mission in AUTO (cm/s)."),
    "WPNAV_SPEED_UP": ("Tốc độ LÊN khi bay AUTO (cm/s).", "Climb speed in AUTO (cm/s)."),
    "WPNAV_SPEED_DN": (
        "Tốc độ XUỐNG khi bay AUTO (cm/s). Thường đặt thấp hơn tốc độ lên: xuống nhanh là "
        "rơi vào luồng khí xoáy của chính mình.",
        "Descent speed in AUTO (cm/s). Usually lower than the climb speed: descending fast "
        "drops the aircraft into its own vortex ring."),
    "WPNAV_ACCEL": (
        "Gia tốc ngang khi vào/ra waypoint (cm/s²) — quyết định cua gắt hay cua mềm.",
        "Horizontal acceleration entering and leaving waypoints (cm/s²) — sharp or soft turns."),
    "LOIT_SPEED": (
        "Tốc độ ngang tối đa ở mode LOITER khi người bay đẩy cần (cm/s).",
        "Maximum horizontal speed in LOITER when the pilot pushes the stick (cm/s)."),
    "LOIT_ACC_MAX": (
        "Gia tốc tối đa ở LOITER (cm/s²) — cao thì phản ứng gắt, thấp thì trôi mượt.",
        "Maximum acceleration in LOITER (cm/s²) — high feels sharp, low feels floaty."),
    "ANGLE_MAX": (
        "Góc nghiêng tối đa cho phép (centi-độ; 3000 = 30°). Chốt an toàn: nghiêng càng "
        "nhiều thì lực nâng theo phương đứng càng ít.",
        "Maximum lean angle (centi-degrees; 3000 = 30°). A safety stop: the more it leans, "
        "the less vertical lift is left."),
    "PILOT_SPEED_UP": (
        "Tốc độ LÊN tối đa khi người bay đẩy cần ga ở các mode giữ độ cao (cm/s).",
        "Maximum climb rate on pilot throttle stick in altitude-holding modes (cm/s)."),
}


def _compose(name):
    """Ghep mo ta cho ho PID. Tra None neu ten khong theo khuon nao."""
    parts = name.split("_")
    if parts[:2] == ["ATC", "RAT"] and len(parts) >= 4:
        axis, gain = AXIS.get(parts[2]), GAIN.get("_".join(parts[3:]))
        if axis and gain:
            return (f"Vòng TỐC ĐỘ GÓC {axis[0]} — {gain[0]}",
                    f"Angular RATE loop, {axis[1]} — {gain[1]}")
    if parts[:2] == ["ATC", "ANG"] and parts[3:] == ["P"]:
        axis = AXIS.get(parts[2])
        if axis:
            return (f"Vòng GÓC {axis[0]} — hệ số P: sai số góc đổi thành tốc độ góc đặt cho "
                    "vòng trong. Đây là khâu ngoài, chỉnh sau khi vòng tốc độ góc đã ổn.",
                    f"ANGLE loop, {axis[1]} — P gain: angle error becomes the rate demand for "
                    "the inner loop. Outer loop; tune it after the rate loop is settled.")
    if parts[:1] == ["PSC"] and len(parts) >= 3:
        grp, gain = PSC_GROUP.get(parts[1]), GAIN.get("_".join(parts[2:]))
        if grp and gain:
            return (f"{grp[0]} — {gain[0]}", f"{grp[1]} — {gain[1]}")
    return None


def doc(name):
    """Mot dong giai thich cho tham so `name`, theo ngon ngu dang chon.

    Tra ve "" neu chua co mo ta — nguoi goi tu quyet dinh im lang (khong gan
    tooltip) chu khong hien ra mot cai tooltip rong.
    """
    pair = EXPLICIT.get(name) or _compose(name)
    if not pair:
        return ""
    return pair[0] if i18n.lang() == "vi" else pair[1]
