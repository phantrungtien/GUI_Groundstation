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

import functools
import json
from pathlib import Path

from core import i18n

# Mo ta MOI tham so, tieng Anh, tu metadata cua ArduPilot — xem
# tools/build_param_meta.py. Dung khi tham so khong co dong tieng Viet o duoi.
META = Path(__file__).with_name("param_meta.json")

# --- manh de ghep ho PID ---------------------------------------------------

AXIS = {
    "RLL": ("trục lăn (roll)", "roll axis"),
    "PIT": ("trục chúc (pitch)", "pitch axis"),
    "YAW": ("trục xoay (yaw)", "yaw axis"),
}

# Ten he so co trong firmware 4.7-dev ma bang cu chua co. Do tren MicoAir743
# 23/08/2026: moi vong PID day du 13 he so, bang cu chi biet 8.
GAIN = {
    "P": ("hệ số P: sai số nhân thẳng ra lệnh. Tăng thì bám nhanh hơn, quá tay là rung",
          "P gain: error goes straight to the output. Higher tracks faster; too high oscillates"),
    "I": ("hệ số I: dồn sai số kéo dài, bù lệch trọng tâm và gió thổi một chiều",
          "I gain: accumulates steady error, trims out CG offset and steady wind"),
    "D": ("hệ số D: hãm theo tốc độ biến thiên, dập vọt lố. Quá tay là khuếch đại rung máy",
          "D gain: damps by rate of change, kills overshoot. Too high amplifies frame vibration"),
    "IMAX": ("trần của phần I: chặn không cho nó dồn vô hạn khi lệch lâu",
             "cap on the I term: stops it winding up without limit during a long error"),
    "FF": ("hệ số truyền thẳng: lệnh đặt đi tắt ra đầu ra, không đợi sinh ra sai số. "
           "Bám nhanh hơn mà không phải tăng P",
           "feed-forward: the demand goes straight to the output without waiting for an "
           "error to build. Faster tracking without raising P"),
    "D_FF": ("truyền thẳng theo TỐC ĐỘ BIẾN THIÊN của lệnh đặt — bù lúc cần đảo hướng gấp",
             "feed-forward on the RATE OF CHANGE of the demand — helps on sharp reversals"),
    "PDMX": ("trần cho tổng phần P và D: chặn hai khâu này cộng lại đòi quá lực",
             "cap on the combined P and D output: stops the pair demanding more than the "
             "airframe has"),
    "NEF": ("tần số bộ lọc chặn dải trên SAI SỐ (Hz): cắt đúng tần số rung của khung",
            "error notch filter frequency (Hz): cuts the frame's own vibration frequency"),
    "NTF": ("tần số bộ lọc chặn dải trên ĐẦU RA (Hz): chặn vòng điều khiển tự nuôi rung",
            "target notch filter frequency (Hz): stops the loop feeding its own vibration"),
    "FLTT": ("lọc thông thấp trên tín hiệu ĐẶT (Hz): làm mượt lệnh vào, tránh giật",
             "low-pass on the TARGET (Hz): smooths the demand so it does not step"),
    "FLTE": ("lọc thông thấp trên SAI SỐ (Hz): bớt nhiễu trước khi vào P và I",
             "low-pass on the ERROR (Hz): de-noises before it reaches P and I"),
    "FLTD": ("lọc thông thấp riêng cho khâu D (Hz): khâu D nhạy nhiễu nhất nên lọc riêng",
             "low-pass for the D term only (Hz): D is the noisiest term, so it filters separately"),
    "SMAX": ("trần tốc độ bẻ lái (slew): chặn PID đòi động cơ đổi nhanh hơn nó theo kịp",
             "slew-rate limit: stops the PID demanding faster motor changes than it can follow"),
}

# Hai bo ten cho CUNG mot vong: 4.7-dev doi XY/Z thanh NE/D (bac-dong / xuong)
# cho khop he toa do NED. Giu ca hai vi mot bai bay cu doc bang log cu van con
# ten XY/Z, ma FC dang cam thi tra ve ten NE/D.
PSC_GROUP = {
    "POSXY": ("Vòng VỊ TRÍ ngang", "Horizontal POSITION loop"),
    "POSZ": ("Vòng VỊ TRÍ đứng (độ cao)", "Vertical POSITION loop (altitude)"),
    "VELXY": ("Vòng TỐC ĐỘ ngang", "Horizontal VELOCITY loop"),
    "VELZ": ("Vòng TỐC ĐỘ đứng (lên/xuống)", "Vertical VELOCITY loop (climb/descend)"),
    "ACCZ": ("Vòng GIA TỐC đứng (khâu trong cùng, ra thẳng ga)",
             "Vertical ACCELERATION loop (innermost, feeds throttle directly)"),
    "NE_POS": ("Vòng VỊ TRÍ ngang", "Horizontal POSITION loop"),
    "D_POS": ("Vòng VỊ TRÍ đứng (độ cao)", "Vertical POSITION loop (altitude)"),
    "NE_VEL": ("Vòng TỐC ĐỘ ngang", "Horizontal VELOCITY loop"),
    "D_VEL": ("Vòng TỐC ĐỘ đứng (lên/xuống)", "Vertical VELOCITY loop (climb/descend)"),
    "D_ACC": ("Vòng GIA TỐC đứng (khâu trong cùng, ra thẳng ga)",
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

    # --- ten SI cua firmware 4.7-dev -------------------------------------
    # Cung nhung tham so tren nhung DON VI DA DOI: cm/s -> m/s, centi-do -> do,
    # cm -> m. Doc tren MicoAir743 23/08/2026 de chac don vi, khong doan: WP_SPD
    # tra ve 10.0 (khong phai 1000), ATC_ANGLE_MAX 20.0, RTL_ALT_M 15.0.
    "WP_SPD": ("Tốc độ ngang khi bay AUTO theo đường bay (m/s).",
               "Horizontal speed along a mission in AUTO (m/s)."),
    "WP_SPD_UP": ("Tốc độ LÊN khi bay AUTO (m/s).", "Climb speed in AUTO (m/s)."),
    "WP_SPD_DN": (
        "Tốc độ XUỐNG khi bay AUTO (m/s). Thường đặt thấp hơn tốc độ lên: xuống nhanh là "
        "rơi vào luồng khí xoáy của chính mình.",
        "Descent speed in AUTO (m/s). Usually lower than the climb speed: descending fast "
        "drops the aircraft into its own vortex ring."),
    "WP_ACC": (
        "Gia tốc ngang khi vào/ra waypoint (m/s²) — quyết định cua gắt hay cua mềm.",
        "Horizontal acceleration entering and leaving waypoints (m/s²) — sharp or soft turns."),
    "WP_ACC_Z": ("Gia tốc đứng khi đổi độ cao giữa các waypoint (m/s²).",
                 "Vertical acceleration when changing altitude between waypoints (m/s²)."),
    "WP_JERK": (
        "Độ giật cho phép (m/s³) — tốc độ đổi của gia tốc. Thấp thì chuyển động mượt, "
        "cao thì bám đường bay sát hơn nhưng xóc.",
        "Allowed jerk (m/s³) — how fast acceleration may change. Low is smooth, high "
        "tracks the path tighter but jolts."),
    "WP_RADIUS_M": (
        "Bán kính coi như đã tới waypoint (m). Nhỏ quá thì máy bay phải phanh hẳn ở mỗi "
        "điểm; lớn quá thì nó cắt góc.",
        "Radius counting a waypoint as reached (m). Too small forces a full stop at every "
        "point; too large cuts corners."),
    "WP_YAW_BEHAVIOR": (
        "Cách quay mũi trong nhiệm vụ AUTO: giữ nguyên, hướng theo đường bay, hay hướng "
        "về waypoint kế tiếp.",
        "Yaw behaviour during an AUTO mission: hold, follow the track, or point at the "
        "next waypoint."),
    "LOIT_SPEED_MS": (
        "Tốc độ ngang tối đa ở mode LOITER khi người bay đẩy cần (m/s).",
        "Maximum horizontal speed in LOITER when the pilot pushes the stick (m/s)."),
    "LOIT_ACC_MAX_M": (
        "Gia tốc tối đa ở LOITER (m/s²) — cao thì phản ứng gắt, thấp thì trôi mượt.",
        "Maximum acceleration in LOITER (m/s²) — high feels sharp, low feels floaty."),
    "LOIT_BRK_ACC_M": (
        "Gia tốc phanh khi buông cần ở LOITER (m/s²): cao thì dừng gấp, ngửa mũi mạnh.",
        "Braking acceleration when the stick is released in LOITER (m/s²): high stops "
        "abruptly with a sharp pitch-back."),
    "LOIT_BRK_DELAY": ("Trễ trước khi bắt đầu phanh sau khi buông cần (giây).",
                       "Delay before braking starts after the stick is released (s)."),
    "ATC_ANGLE_MAX": (
        "Góc nghiêng tối đa cho phép (độ). Chốt an toàn: nghiêng càng nhiều thì lực nâng "
        "theo phương đứng càng ít.",
        "Maximum lean angle (degrees). A safety stop: the more it leans, the less vertical "
        "lift is left."),
    "PSC_ANGLE_MAX": (
        "Góc nghiêng tối đa cho riêng bộ điều khiển vị trí (độ). Để 0 nghĩa là dùng chung "
        "ATC_ANGLE_MAX — đặt thấp hơn nếu muốn bay tự động hiền hơn bay tay.",
        "Lean-angle limit for the position controller alone (degrees). 0 means fall back to "
        "ATC_ANGLE_MAX — set it lower to make autonomous flight gentler than manual."),
    "PSC_JERK_NE": ("Độ giật ngang cho phép của bộ điều khiển vị trí (m/s³).",
                    "Allowed horizontal jerk in the position controller (m/s³)."),
    "PSC_JERK_D": ("Độ giật đứng cho phép của bộ điều khiển vị trí (m/s³).",
                   "Allowed vertical jerk in the position controller (m/s³)."),
    "PILOT_SPD_UP": (
        "Tốc độ LÊN tối đa khi người bay đẩy cần ga ở các mode giữ độ cao (m/s).",
        "Maximum climb rate on pilot throttle stick in altitude-holding modes (m/s)."),
    "PILOT_SPD_DN": (
        "Tốc độ XUỐNG tối đa khi người bay hạ cần ga (m/s). Để 0 là dùng chung số của "
        "chiều lên.",
        "Maximum descent rate on pilot throttle stick (m/s). 0 means reuse the climb figure."),
    "PILOT_ACC_Z": ("Gia tốc đứng theo cần ga (m/s²) — cần ga đổi thì lên/xuống gấp cỡ nào.",
                    "Vertical acceleration from the throttle stick (m/s²) — how sharply it "
                    "starts climbing or descending."),
    "PILOT_TKO_ALT_M": (
        "Độ cao tự leo tới khi cất cánh ở mode có người lái (m). 0 nghĩa là không tự leo.",
        "Altitude the aircraft climbs to on takeoff in piloted modes (m). 0 disables it."),
    "RTL_ALT_M": (
        "Độ cao bay về nhà (m). Máy bay leo tới đây trước khi bay ngang — đặt cao hơn mọi "
        "thứ trên đường về.",
        "Return-to-launch altitude (m). The aircraft climbs to this before flying home — set "
        "it above everything on the way back."),
    "RTL_ALT_FINAL_M": (
        "Độ cao dừng lại ở cuối chặng RTL (m). 0 nghĩa là hạ hẳn xuống đất.",
        "Altitude to stop at when the RTL ends (m). 0 means land all the way down."),
    "RTL_SPEED_MS": ("Tốc độ ngang khi bay về nhà (m/s). 0 là dùng tốc độ của AUTO.",
                     "Horizontal speed while returning home (m/s). 0 reuses the AUTO speed."),
    "RTL_CLIMB_MIN_M": (
        "Phần leo tối thiểu khi bắt đầu RTL (m) — leo lên chừng này đã, kể cả khi đang ở "
        "trên độ cao về nhà.",
        "Minimum climb when RTL starts (m) — go up at least this much even if already above "
        "the return altitude."),
    "RTL_LOIT_TIME": ("Thời gian treo tại điểm nhà trước khi hạ (mili-giây).",
                      "Time to hover over home before descending (ms)."),

    # --- phan con lai cua ho ATC_* (khong theo khuon PID) -----------------
    "ATC_ACC_R_MAX": (
        "Gia tốc góc tối đa quanh trục lăn (độ/s²). Hạ xuống thì máy bay đảo hiền hơn; "
        "khung to nặng phải hạ, không thì lệnh vượt quá sức động cơ.",
        "Maximum angular acceleration about the roll axis (deg/s²). Lower makes it gentler; "
        "big heavy frames need it lowered or the demand exceeds what the motors can give."),
    "ATC_ACC_P_MAX": ("Gia tốc góc tối đa quanh trục chúc (độ/s²).",
                      "Maximum angular acceleration about the pitch axis (deg/s²)."),
    "ATC_ACC_Y_MAX": (
        "Gia tốc góc tối đa quanh trục xoay (độ/s²). Thường thấp hơn hai trục kia nhiều: "
        "xoay mũi chỉ dựa vào chênh lệch mô-men của cánh quạt.",
        "Maximum angular acceleration about the yaw axis (deg/s²). Usually far lower than "
        "the other two: yaw only has propeller torque difference to work with."),
    "ATC_INPUT_TC": (
        "Hằng số thời gian đáp ứng cần lái (giây). Nhỏ thì bám cần gắt như máy đua, lớn "
        "thì mềm và dễ bay bằng.",
        "Stick response time constant (s). Small feels racy and direct, large feels soft "
        "and easy to fly smoothly."),
    "ATC_ANGLE_BOOST": (
        "Tự tăng ga khi máy bay nghiêng, bù phần lực nâng mất đi. Tắt thì cua gấp là tụt "
        "độ cao.",
        "Automatically raise throttle as the aircraft leans, replacing the vertical lift "
        "lost. Off means it sinks in hard turns."),
    "ATC_ANG_LIM_TC": (
        "Hằng số thời gian của khâu chặn góc nghiêng (giây) — góc bị kéo về giới hạn nhanh "
        "hay chậm.",
        "Time constant of the lean-angle limiter (s) — how fast the angle is pulled back "
        "to the limit."),
    "ATC_THR_MIX_MIN": (
        "Mức ưu tiên tối thiểu dành cho giữ thăng bằng so với giữ ga, lúc đang ở dưới đất "
        "hay ga thấp. Cao quá thì máy bay lật lọc khi vừa ARM.",
        "Minimum priority given to attitude control over throttle, on the ground or at low "
        "throttle. Too high and it tips over right after ARM."),
    "ATC_THR_MIX_MAX": (
        "Mức ưu tiên tối đa dành cho giữ thăng bằng khi đang bay. Cao thì giữ tư thế bằng "
        "mọi giá, kể cả tụt độ cao.",
        "Maximum priority given to attitude control while flying. High holds attitude at "
        "any cost, including losing altitude."),
    "ATC_THR_MIX_MAN": ("Mức ưu tiên thăng bằng/ga ở các mode người bay tự giữ ga.",
                        "Attitude-versus-throttle priority in modes where the pilot holds "
                        "the throttle."),
    "ATC_THR_G_BOOST": (
        "Tăng hệ số vòng trong theo mức ga — cho khung có đáp ứng đổi hẳn giữa ga thấp và "
        "ga cao. 0 là tắt.",
        "Scale the inner-loop gains with throttle — for frames whose response differs a lot "
        "between low and high throttle. 0 disables it."),
    "ATC_LAND_R_MULT": (
        "Hệ số nhân cho vòng trục lăn khi đã phát hiện chạm đất: hạ hệ số xuống để càng "
        "chạm đất không thành cần bẩy làm máy bay lật.",
        "Roll-loop gain multiplier once ground contact is detected: lower gains so the legs "
        "on the ground do not become a lever that tips the aircraft."),
    "ATC_LAND_P_MULT": ("Hệ số nhân cho vòng trục chúc khi đã chạm đất.",
                        "Pitch-loop gain multiplier once on the ground."),
    "ATC_LAND_Y_MULT": ("Hệ số nhân cho vòng trục xoay khi đã chạm đất.",
                        "Yaw-loop gain multiplier once on the ground."),
    "ATC_RATE_R_MAX": (
        "Tốc độ góc tối đa quanh trục lăn (độ/s). 0 là không chặn — chỉ giới hạn góc "
        "nghiêng mới có tác dụng.",
        "Maximum roll rate (deg/s). 0 means no limit — only the lean-angle limit applies."),
    "ATC_RATE_P_MAX": ("Tốc độ góc tối đa quanh trục chúc (độ/s). 0 là không chặn.",
                       "Maximum pitch rate (deg/s). 0 means no limit."),
    "ATC_RATE_Y_MAX": ("Tốc độ xoay mũi tối đa (độ/s). 0 là không chặn.",
                       "Maximum yaw rate (deg/s). 0 means no limit."),
    "ATC_RATE_WPY_MAX": (
        "Tốc độ xoay mũi tối đa khi bay tự động theo đường bay (độ/s) — tách riêng để "
        "nhiệm vụ AUTO quay mũi hiền hơn lúc bay tay.",
        "Maximum yaw rate while flying a mission automatically (deg/s) — separate so AUTO "
        "turns the nose more gently than manual flight."),
    "ATC_RATE_FF_ENAB": (
        "Bật khâu truyền thẳng của vòng tốc độ góc. Tắt là quay về kiểu điều khiển cũ, "
        "chậm hơn hẳn — bình thường không có lý do gì để tắt.",
        "Enable rate-loop feed-forward. Off reverts to the old, markedly slower control "
        "scheme — normally there is no reason to disable it."),

    # --- phan con lai cua WP_* / RTL_* / LOIT_* / PILOT_* -----------------
    "WP_ACC_CNR": (
        "Gia tốc riêng khi VÀO CUA giữa hai chặng (m/s²). 0 là dùng chung WP_ACC.",
        "Acceleration used specifically for CORNERING between legs (m/s²). 0 reuses WP_ACC."),
    "WP_RFND_USE": (
        "Dùng cảm biến khoảng cách để bám địa hình trong nhiệm vụ. Bật mà cảm biến hỏng "
        "thì độ cao bám theo một con số sai.",
        "Use the rangefinder for terrain following during a mission. Enabled with a faulty "
        "sensor means the altitude follows a wrong number."),
    "WP_TER_MARGIN": (
        "Sai lệch địa hình cho phép khi bám địa hình (m): lệch quá chừng này thì nhiệm vụ "
        "dừng lại thay vì bay tiếp theo số liệu đáng ngờ.",
        "Allowed terrain-following error (m): beyond this the mission stops rather than "
        "flying on suspect data."),
    "WP_NAVALT_MIN": (
        "Độ cao tối thiểu phải đạt trước khi bắt đầu bay ngang sau cất cánh (m). 0 là "
        "không đợi.",
        "Minimum altitude to reach before moving horizontally after takeoff (m). 0 means "
        "no wait."),
    "RTL_ALT_TYPE": (
        "Độ cao RTL tính so với điểm cất cánh hay so với địa hình bên dưới.",
        "Whether the RTL altitude is measured from the launch point or above the terrain."),
    "RTL_CONE_SLOPE": (
        "Độ dốc của hình nón quanh điểm nhà: đang ở gần nhà thì không leo cao vô ích, độ "
        "cao về nhà bị cắt theo khoảng cách.",
        "Slope of the cone around home: close to home it does not climb pointlessly, the "
        "return altitude is clipped by distance."),
    "RTL_OPTIONS": ("Các tuỳ chọn phụ của RTL, mỗi bit một tuỳ chọn.",
                    "Extra RTL options, one per bit."),
    "LOIT_ANG_MAX": (
        "Góc nghiêng tối đa riêng cho LOITER (độ). 0 là dùng chung giới hạn góc chung.",
        "Lean-angle limit for LOITER alone (degrees). 0 reuses the general angle limit."),
    "LOIT_BRK_JRK_M": ("Độ giật cho phép trong lúc phanh ở LOITER (m/s³).",
                       "Allowed jerk while braking in LOITER (m/s³)."),
    "LOIT_OPTIONS": ("Các tuỳ chọn phụ của LOITER, mỗi bit một tuỳ chọn.",
                     "Extra LOITER options, one per bit."),
    "PILOT_THR_FILT": (
        "Lọc thông thấp trên cần ga (Hz). 0 là không lọc; đặt vài Hz khi tay lái rung "
        "hoặc cần ga nhiễu.",
        "Low-pass on the throttle stick (Hz). 0 is no filter; a few Hz helps with a shaky "
        "hand or a noisy stick."),
    "PILOT_THR_BHV": (
        "Cách hiểu cần ga: có lò xo về giữa hay không, và có bù ga khi nghiêng không.",
        "How the throttle stick is interpreted: spring-centred or not, and whether it "
        "compensates for lean angle."),
    "PILOT_Y_RATE": ("Tốc độ xoay mũi tối đa theo cần lái (độ/s).",
                     "Maximum yaw rate from the stick (deg/s)."),
    "PILOT_Y_EXPO": (
        "Độ cong đáp ứng cần xoay (0–1): giữa cần thì hiền, đẩy hết cần vẫn đủ tốc độ.",
        "Expo on the yaw stick (0–1): gentle around centre, still full rate at the stops."),
    "PILOT_Y_RATE_TC": ("Hằng số thời gian đáp ứng cần xoay (giây). 0 là dùng ATC_INPUT_TC.",
                        "Yaw stick response time constant (s). 0 reuses ATC_INPUT_TC."),
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
        # Ten nhom dai mot manh (PSC_VELXY_P) hay hai manh (PSC_NE_VEL_P) deu phai
        # doc duoc — cat thu ca hai cho.
        for cut in (2, 3):
            grp, gain = PSC_GROUP.get("_".join(parts[1:cut])), GAIN.get("_".join(parts[cut:]))
            if grp and gain:
                return (f"{grp[0]} — {gain[0]}", f"{grp[1]} — {gain[1]}")
    return None


@functools.lru_cache(maxsize=1)
def _meta():
    try:
        return json.loads(META.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # thieu file: chi con mo ta viet tay, khong phai loi
        return {}


def doc(name):
    """Mot dong giai thich cho tham so `name`, theo ngon ngu dang chon.

    Uu tien dong viet tay (co tieng Viet); khong co thi lay mo ta cua ArduPilot
    (tieng Anh) kem don vi. Tra ve "" neu ca hai deu khong co — nguoi goi tu
    quyet dinh im lang chu khong hien mot o rong gia vo la co.
    """
    pair = EXPLICIT.get(name) or _compose(name)
    if pair:
        return pair[0] if i18n.lang() == "vi" else pair[1]
    m = _meta().get(name)
    if not m:
        return ""
    human, text, units, _ = m
    s = f"{human} — {text}" if human and text else human or text
    return f"{s} [{units}]" if units else s


def values(name):
    """"0: Disabled, 1: Enabled..." cho tham so kieu liet ke, "" neu khong co."""
    m = _meta().get(name)
    return m[3] if m else ""
