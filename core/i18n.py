"""Chuyen ngon ngu giao dien: tieng Viet co dau <-> tieng Anh.

Ba thu trong file nay:

    t(key, **kw)    tra chuoi theo ngon ngu dang chon, .format(**kw)
    on_change(fn)   dang ky mot ham DAT LAI chu; goi ngay mot lan roi goi lai
                    moi lan doi ngon ngu
    set_lang(l)     doi ngon ngu, luu bang QSettings, chay het cac fn da dang ky

Vi sao khong dung QTranslator + file .ts: no can them lupdate/lrelease vao vong
build va van phai tu viet retranslateUi cho tung widget viet tay — tuc la dung
luong cong viec, cong them mot chuoi cong cu. Bang chu o day la mot file Python,
`git diff` doc duoc, va tools/selfcheck.py doi chieu duoc.

Chuoi CHUA co trong bang thi t() tra ve chinh cai key — thieu ban dich se hien
ra ngay tren man hinh chu khong im lang roi ve tieng Viet.

Chu KHONG dich: ten mode cua FC (GUIDED, AUTO...), ten field MAVLink, ma lenh.
Do la tu vung cua ArduPilot, dich ra la khong doi chieu duoc voi tai lieu hay
voi GCS khac.
"""

from PySide6.QtCore import QObject, QSettings, Signal

LANGS = {"vi": "Tiếng Việt", "en": "English"}
DEFAULT = "vi"
_ORG, _APP = "GCS", "native"


class _Signals(QObject):
    changed = Signal(str)


signals = _Signals()

_lang = DEFAULT
# ponytail: giu tham chieu manh toi bound method -> widget khong bao gio duoc thu
# hoi. Moi widget dang ky o day deu song bang tuoi tho app (tab, dock, banner),
# nen doi lay su don gian. Doi neu co widget tao/xoa lien tuc thi chuyen weakref.
_hooks = []


def lang():
    return _lang


def t(key, **kw):
    row = STR.get(key)
    if row is None:
        return key
    s = row[0] if _lang == "vi" else row[1]
    return s.format(**kw) if kw else s


def on_change(fn):
    """Dang ky ham dat lai chu. Goi ngay de widget co chu ngay tu luc dung."""
    _hooks.append(fn)
    fn()
    return fn


def set_lang(new):
    global _lang
    if new not in LANGS or new == _lang:
        return
    _lang = new
    QSettings(_ORG, _APP).setValue("lang", new)
    for fn in list(_hooks):
        try:
            fn()
        except RuntimeError:
            _hooks.remove(fn)  # widget da bi Qt xoa ben C++
    signals.changed.emit(new)


def load():
    """Doc ngon ngu da luu. Goi mot lan trong main() TRUOC khi dung cua so."""
    global _lang
    saved = QSettings(_ORG, _APP).value("lang")
    if saved in LANGS:
        _lang = saved
    return _lang


# ---------------------------------------------------------------------------
# Bang chu.  key: (tieng Viet co dau, English)
# ---------------------------------------------------------------------------

STR = {
    # --- tab & dock -------------------------------------------------------
    "tab.flight": ("Bay", "Flight"),
    "tab.status": ("Trạng thái", "Status"),
    "tab.control": ("Điều khiển", "Control"),
    "tab.messages": ("Thông báo", "Messages"),
    "tab.camera": ("Camera", "Camera"),
    "tab.settings": ("Cài đặt", "Settings"),
    "tab.analysis": ("Phân tích", "Analysis"),
    "dock.conn": ("Kết nối", "Connection"),
    "dock.faults": ("Mô phỏng đứt đường truyền", "Link-loss simulation"),

    # --- cai dat ----------------------------------------------------------
    "set.lang_box": ("Ngôn ngữ giao diện", "Interface language"),
    "set.lang_note": (
        "Đổi là hiện ngay, không phải khởi động lại. Lựa chọn được nhớ cho lần "
        "mở sau.\n\nTên mode của FC (GUIDED, AUTO, LOITER…), tên field MAVLink và "
        "mã lệnh KHÔNG dịch: đó là từ vựng của ArduPilot, dịch ra thì không đối "
        "chiếu được với tài liệu hay với GCS khác.",
        "Changes apply immediately — no restart. Your choice is remembered.\n\n"
        "FC mode names (GUIDED, AUTO, LOITER…), MAVLink field names and command "
        "codes are NOT translated: they are ArduPilot vocabulary, and translating "
        "them would break cross-checking against the docs or another GCS."),

    # --- banner che do ----------------------------------------------------
    "banner.none": ("CHƯA KẾT NỐI  ·  chọn nguồn ở panel bên phải",
                    "NOT CONNECTED  ·  pick a source in the right-hand panel"),
    "banner.waiting": ("{mode}  ·  {name}  ·  đang chờ dữ liệu…",
                       "{mode}  ·  {name}  ·  waiting for data…"),
    "banner.lost": ("⚠  MẤT KẾT NỐI  ·  {name}  ·  {why}",
                    "⚠  LINK LOST  ·  {name}  ·  {why}"),
    "mode.REAL": ("bay thật", "live flight"),
    "mode.SIM": ("mô phỏng SITL", "SITL simulation"),
    "mode.REPLAY": ("phát lại — mọi nút điều khiển bị khoá",
                    "replay — every control is locked"),

    "close.banner": ("⚠  DRONE ĐANG ARM  ·  bấm đóng lần nữa trong {sec}s để thoát",
                     "⚠  DRONE IS ARMED  ·  press close again within {sec}s to quit"),
    "close.armed": (
        "Đóng app lúc này là mất đường cứu sinh: không còn nút đỏ, không còn HUD. "
        "Bấm đóng lần nữa trong {sec:.0f}s nếu thật sự muốn thoát.",
        "Closing now costs you the lifeline: no red buttons, no HUD. Press close "
        "again within {sec:.0f}s if you really mean it."),

    # --- panel ket noi ----------------------------------------------------
    "conn.title": ("Nguồn kết nối", "Connection source"),
    "conn.connect": ("Kết nối", "Connect"),
    "conn.disconnect": ("Ngắt", "Disconnect"),
    "conn.scan": ("Quét lại cổng USB", "Rescan USB ports"),
    "conn.none_picked": ("Chưa chọn nguồn nào.", "No source selected."),
    "conn.no_perm": ("  ⚠ không có quyền", "  ⚠ no permission"),
    "conn.opening": ("Đang mở: {name}", "Opening: {name}"),
    "conn.found": ("Tìm thấy {n} cổng USB.", "Found {n} USB port(s)."),
    "conn.not_found": ("Không thấy cổng USB nào — cắm radio rồi bấm Quét lại.",
                       "No USB port found — plug the radio in, then hit Rescan."),
    "conn.perm_fix": (
        "Có cổng USB nhưng KHÔNG CÓ QUYỀN mở. Chạy:\n"
        "sudo usermod -aG dialout $USER\nrồi ĐĂNG XUẤT / ĐĂNG NHẬP lại.",
        "USB port found but NO PERMISSION to open it. Run:\n"
        "sudo usermod -aG dialout $USER\nthen LOG OUT / LOG BACK IN."),
    "conn.pick_tlog": ("Chọn file log (.tlog hoặc .bin)",
                       "Pick a log file (.tlog or .bin)"),
    "conn.tlog_filter": ("Log bay (*.tlog *.bin *.BIN)", "Flight log (*.tlog *.bin *.BIN)"),
    "conn.no_tlog": ("Chưa chọn file log nào.", "No log file selected."),
    "conn.opening_msg": ("Đang nối {target}", "Connecting to {target}"),
    "conn.fail_title": ("Không kết nối được", "Cannot connect"),
    "conn.sik_lost": ("Mất kết nối SiK: {why}", "SiK link lost: {why}"),
    "conn.sik_silent": ("SiK im lặng {n}s", "SiK silent for {n}s"),
    "conn.replug": ("mất cổng {port} — cắm lại là tự kết nối", "port {port} gone — plug it back to reconnect"),
    "conn.replugged": ("Đã cắm lại, kết nối lại qua {port}", "Plugged back, reconnecting via {port}"),
    "conn.degraded": (
        "MẤT ROS2 — mất video và nguồn vị trí thứ hai. SiK còn, lái và nút đỏ còn.",
        "ROS2 LOST — no video, no second position source. SiK is up: steering and "
        "the red buttons still work."),

    # --- tab Control ------------------------------------------------------
    "ctl.normal_box": ("Lệnh thường", "Normal commands"),
    "ctl.mode_label": ("Mode:", "Mode:"),
    "ctl.alt_label": ("Độ cao:", "Altitude:"),
    "ctl.change_mode": ("Đổi mode", "Change mode"),
    "ctl.mission_box": ("Nhiệm vụ ROS2 trên companion (chỉ đọc)",
                        "ROS2 mission on companion (read-only)"),
    "ctl.mission_none": ("nhiệm vụ: (chưa có tin từ companion)",
                         "mission: (nothing heard from companion yet)"),
    "ctl.mission_idle": ("không có nhiệm vụ nào chạy trên companion",
                         "no mission running on companion"),
    "ctl.mission_run": ("nhiệm vụ đang chạy: {nice}  ({node})  — không cầm quyền",
                        "mission running: {nice}  ({node})  — holds no authority"),
    "ctl.red_box": ("Nút đỏ — đi thẳng qua SiK, không xin quyền",
                    "Red buttons — straight down SiK, no authority check"),
    "ctl.again_kill": ("BẤM LẠI = CẮT ĐỘNG CƠ", "PRESS AGAIN = CUT MOTORS"),
    "ctl.killed": ("ĐÃ CẮT ĐỘNG CƠ", "MOTORS CUT"),
    "ctl.note_none": ("Chưa kết nối nguồn nào.", "No source connected."),
    "ctl.note_replay": ("REPLAY — không có gì ở đầu kia để gửi lệnh tới. Mọi nút bị khoá.",
                        "REPLAY — nothing at the other end to command. Every button locked."),
    "ctl.note_real": ("REAL — mọi lệnh dưới đây đi xuống máy bay thật.",
                      "REAL — every command below goes to the real aircraft."),
    "ctl.takeoff_confirm": ("BẤM LẠI ĐỂ CẤT CÁNH {alt:.0f}m", "PRESS AGAIN TO TAKE OFF {alt:.0f}m"),
    "mission.circle": ("Bay vòng tròn", "Circle"),
    "mission.gates": ("Qua vòng gate", "Gate run"),
    "mission.human": ("Bám theo người", "Human follow"),
    "mission.simple": ("Bay đơn giản", "Simple flight"),

    # ack cua FC
    "ack.0": ("CHẤP NHẬN", "ACCEPTED"),
    "ack.1": ("TẠM THỜI TỪ CHỐI", "TEMPORARILY REJECTED"),
    "ack.2": ("TỪ CHỐI", "DENIED"),
    "ack.3": ("KHÔNG HỖ TRỢ", "UNSUPPORTED"),
    "ack.4": ("THẤT BẠI", "FAILED"),
    "ack.5": ("ĐANG CHẠY", "IN PROGRESS"),
    "ack.6": ("HUỶ", "CANCELLED"),
    "cmd.mode": ("đổi mode", "change mode"),

    # --- log ket qua lenh -------------------------------------------------
    "log.arm_no_rc": ("ARM: chưa thấy RC_CHANNELS nên không biết cần ga ở đâu — vẫn gửi",
                      "ARM: no RC_CHANNELS yet, throttle position unknown — sending anyway"),
    "log.arm_rc_old": ("ARM: vị trí ga quá cũ ({age:.0f}s) — vẫn gửi",
                       "ARM: throttle reading is {age:.0f}s old — sending anyway"),
    "log.arm_blocked": (
        "ARM: CHẶN — hạ ga về min trước (đang {pwm:.0f} PWM, cần dưới {max}). "
        "FC không tự chặn: bấm ARM lúc này là động cơ quay ngay lên đúng mức ga đó.",
        "ARM: BLOCKED — lower the throttle to min first (now {pwm:.0f} PWM, needs to be "
        "under {max}). The FC will not block this: arming now spins the motors straight "
        "up to that throttle."),
    "log.no_ack": ("{action}: KHÔNG CÓ PHẢN HỒI từ FC sau {sec:.0f}s",
                   "{action}: NO REPLY from the FC after {sec:.0f}s"),
    "log.fc_denied": ("{name}: FC TỪ CHỐI — {why}", "{name}: FC DENIED — {why}"),
    "log.fc_ok": ("{name}: FC chấp nhận", "{name}: FC accepted"),
    "log.takeoff_need_guided": (
        "takeoff: cần mode GUIDED trước, đang ở {mode} — đổi mode rồi bấm lại",
        "takeoff: GUIDED mode required, currently {mode} — switch mode then press again"),
    "log.takeoff_need_arm": (
        "takeoff: drone CHƯA ARM — ARM trước rồi mới cất cánh",
        "takeoff: drone is NOT ARMED — arm first, then take off"),
    "log.takeoff_confirm": (
        "takeoff: bấm lại trong {sec:.0f}s để cất cánh THẬT lên {alt:.0f} m",
        "takeoff: press again within {sec:.0f}s for a REAL take-off to {alt:.0f} m"),
    "log.takeoff_no_climb": (
        "takeoff: FC đã nhận nhưng độ cao không đổi sau {sec:.0f}s — nghi có node đang "
        "stream setpoint vào GUIDED, kiểm tra bên companion",
        "takeoff: FC accepted but altitude has not changed after {sec:.0f}s — a node is "
        "probably streaming setpoints into GUIDED, check the companion"),
    "log.refused": ("{what}: TỪ CHỐI — {why}", "{what}: REFUSED — {why}"),
    "log.sent": ("{what}: đã gửi", "{what}: sent"),
    "log.sent_wait": ("{what}: đã gửi, chờ FC trả lời", "{what}: sent, waiting for the FC"),
    "log.queued_stale": ("{what}: đã xếp lệnh nhưng link {how} — CHƯA CHẮC TỚI NƠI",
                         "{what}: queued but the link {how} — DELIVERY NOT CERTAIN"),
    "log.silent_never": ("chưa nhận gói nào", "has never received a packet"),
    "log.silent_for": ("im lặng {sec:.0f}s", "has been silent for {sec:.0f}s"),

    # --- tab Flight -------------------------------------------------------
    "fly.diverge": ("⚠ HAI NGUỒN LỆCH VỊ TRÍ {m:.0f} m",
                    "⚠ POSITION SOURCES DISAGREE BY {m:.0f} m"),
    "fly.wp_ok": ("nạp đường bay: FC nhận {n} waypoint — đang đọc lại để đối chiếu",
                  "mission upload: FC took {n} waypoint(s) — reading back to verify"),
    "fly.wp_fail": ("nạp đường bay: THẤT BẠI — {why}. Bản nháp còn nguyên, bấm nạp lại được",
                    "mission upload: FAILED — {why}. The draft is intact, you can retry"),
    "fly.wp_fc_denied": ("FC từ chối (MAV_MISSION_RESULT={code})",
                         "FC rejected it (MAV_MISSION_RESULT={code})"),
    "act.wp_wipe": ("xoá đường bay trên FC", "wipe mission on FC"),
    "act.wp_send": ("nạp {n} waypoint", "upload {n} waypoint(s)"),
    "act.goto": ("GUIDED + bay tới {lat:.5f}, {lon:.5f} ở {alt:.0f} m",
                 "GUIDED + fly to {lat:.5f}, {lon:.5f} at {alt:.0f} m"),
    # nhich vi tri bang ban phim
    "nudge.blocked": ("nhích vị trí: KHÔNG được — {why}", "nudge: NOT allowed — {why}"),
    "nudge.stopped": ("nhích vị trí: dừng — {why}", "nudge: stopped — {why}"),
    "nudge.hold": ("nhích vị trí: {why} -> treo tại chỗ", "nudge: {why} -> holding position"),
    "nudge.no_mode": ("chế độ này không gửi lệnh được", "this mode cannot send commands"),
    "nudge.not_armed": ("drone chưa armed", "the drone is not armed"),
    "nudge.on_ground": ("drone đang nằm dưới đất", "the drone is on the ground"),
    "nudge.wrong_mode": ("đang ở mode {mode}, phải chuyển sang GUIDED mới nhích được",
                         "currently in {mode}; switch to GUIDED to nudge"),
    "nudge.why_release": ("thả phím", "key released"),
    # --- tab Status -------------------------------------------------------
    "st.search": ("lọc theo tên field, vd: ATTITUDE hoặc volt",
                  "filter by field name, e.g. ATTITUDE or volt"),
    "st.freeze": ("Tạm dừng", "Freeze"),
    "st.read_param": ("Đọc tham số từ FC", "Read parameters from FC"),
    "st.reading": ("Đang đọc... {n} tham số", "Reading... {n} parameters"),
    "st.param_done": ("Đọc lại — lần trước về {n} tham số",
                      "Read again — {n} parameters last time"),
    "st.pid_tip": ("FC không tự gửi tham số — bấm để xin cả bảng. Kết quả vào hàng "
                   "PARAM.*; rê chuột lên một hàng để xem tham số đó là gì.\n"
                   "Khoảng 1000 tham số: qua USB mất ~10 giây, qua SiK 57600 mất "
                   "~20 giây và chiếm gần hết đường truyền trong lúc đó.",
                   "The FC does not push parameters — press to pull the whole table. "
                   "Results land in PARAM.* rows; hover a row to see what it does.\n"
                   "About 1000 parameters: ~10 s over USB, ~20 s over a 57600 SiK link, "
                   "hogging the link while it runs."),
    "st.count": ("{n} field", "{n} field(s)"),
    # Trang thai cam bien, giai ma tu ba bitmask cua SYS_STATUS.
    "sensor.ok": ("TỐT", "OK"),
    "sensor.fail": ("HỎNG", "FAULT"),
    "sensor.ok_off": ("TỐT (tắt)", "OK (off)"),
    "sensor.fail_off": ("HỎNG (tắt)", "FAULT (off)"),
    "st.col_field": ("Field", "Field"),
    "st.col_value": ("Giá trị", "Value"),

    # --- tab Messages -----------------------------------------------------
    "msg.level": ("Mức độ:", "Level:"),
    "msg.clear": ("Xoá", "Clear"),
    "msg.f_all": ("Tất cả", "All"),
    "msg.f_notice": ("Notice trở lên", "Notice and above"),
    "msg.f_warn": ("Cảnh báo trở lên", "Warning and above"),
    "msg.f_err": ("Lỗi trở lên", "Error and above"),

    # --- thanh telemetry duoi ban do ------------------------------------
    "tlm.ARM": ("ARM", "ARM"),
    # Trang thai, khong phai ten lenh — nen dich duoc, nhung giu chinh chu "ARM"
    # cua ArduPilot o giua de doi chieu voi nut ben tab Dieu khien.
    "tlm.ALT": ("CAO", "ALT"),
    "tlm.SPD": ("TỐC", "SPD"),
    "tlm.PIN": ("PIN", "BAT"),
    "tlm.SAT": ("VỆ TINH", "SAT"),
    "tlm.MODE": ("MODE", "MODE"),
    "tlm.BAY": ("GIỜ BAY", "AIRBORNE"),
    "tlm.fix0": ("KHÔNG có GPS. Số vệ tinh vô nghĩa.", "NO GPS. The satellite count is meaningless."),
    "tlm.fix1": ("Có GPS nhưng CHƯA bắt được fix — chưa có vị trí.",
                 "GPS present but NO fix yet — there is no position."),
    "tlm.fix2": ("Chỉ 2D fix — có kinh/vĩ độ nhưng KHÔNG có độ cao GPS.",
                 "2D fix only — latitude/longitude but NO GPS altitude."),
    "tlm.fix3": ("3D fix — đủ để bay.", "3D fix — good enough to fly."),
    "tlm.fix4": ("DGPS — 3D fix có hiệu chỉnh vi sai.", "DGPS — 3D fix with differential correction."),
    "tlm.fix5": ("RTK float — chính xác dưới mét, chưa khoá số nguyên.",
                 "RTK float — sub-metre, integers not yet fixed."),
    "tlm.fix6": ("RTK fixed — chính xác cỡ centimet.", "RTK fixed — centimetre-level."),
    "tlm.few_sats": ("3D fix nhưng DƯỚI {n} vệ tinh — fix mỏng manh, dễ tụt.",
                     "3D fix but FEWER than {n} satellites — a thin fix that can drop."),
    "tlm.bad_hdop": ("HDOP ≥ {h:.0f} — vệ tinh đông nhưng xếp thành cụm, vị trí nhoè ra.",
                     "HDOP ≥ {h:.0f} — plenty of satellites but clustered, so the fix is smeared."),
    "tlm.fix7": ("Vị trí cố định khai báo sẵn (static).", "Static, surveyed-in position."),
    "tlm.fix8": ("PPP — định vị điểm chính xác.", "PPP — precise point positioning."),

    # --- thanh trang thai link -------------------------------------------
    "link.never": ("chưa kết nối", "not connected"),
    "link.alive": ("{bps} B/s · mất {loss:.1f}%", "{bps} B/s · {loss:.1f}% lost"),
    "link.dead": ("MẤT — {sec:.0f}s", "LOST — {sec:.0f}s"),

    # --- mo phong dut duong truyen ---------------------------------------
    "flt.ros2_box": ("Nửa ROS2 — WebSocket tới companion",
                     "ROS2 half — WebSocket to the companion"),
    "flt.cut_ros2": ("Ngắt kết nối ROS2", "Cut the ROS2 link"),
    "flt.ros2_hint": (
        "Kịch bản #1. Mất vision/SLAM/task, tab liên quan xám. Nhưng task tự hành VẪN "
        "CHẠY trên drone — banner phải nói rõ điều đó.",
        "Scenario #1. Vision/SLAM/task go dark and their tabs grey out. But the autonomous "
        "task KEEPS RUNNING on the drone — the banner must say so."),
    "flt.sik_box": ("Nửa telemetry — MAVLink qua SiK", "Telemetry half — MAVLink over SiK"),
    "flt.cut_sik": ("Ngắt telemetry", "Cut telemetry"),
    "flt.sik_hint": (
        "Kịch bản #3. Mất đường cứu sinh: không còn HUD, và nút đỏ không tới nơi. "
        "Đây là lỗi nặng nhất, bất kể nửa ROS2 còn sống hay không.",
        "Scenario #3. The lifeline is gone: no HUD, and the red buttons do not arrive. "
        "This is the worst failure, whether or not the ROS2 half is alive."),
    "flt.both_hint": (
        "Tick cả hai = kịch bản #4: không còn đường nào xuống drone, chỉ còn RC.\n"
        "Bỏ tick là có dữ liệu lại ngay — không phải chờ kết nối lại như rút dây thật.",
        "Both ticked = scenario #4: no path down to the drone at all, only RC left.\n"
        "Unticking restores data instantly — unlike a real unplug, there is no reconnect wait."),
    "flt.cutting": ("MÔ PHỎNG: đang ngắt {what}", "SIMULATION: cutting {what}"),
    "flt.restored": ("MÔ PHỎNG: đã nối lại cả hai nửa", "SIMULATION: both halves restored"),

    # --- thanh REPLAY -----------------------------------------------------
    "rep.pause": ("⏸ Tạm dừng", "⏸ Pause"),
    "rep.resume": ("▶ Chạy tiếp", "▶ Resume"),

    # --- video ------------------------------------------------------------
    "vid.no_source": ("chưa có nguồn", "no source"),
    "vid.not_connected": ("chưa kết nối", "not connected"),
    "vid.connecting": ("đang nối...", "connecting..."),
    "vid.lost": ("mất video", "video lost"),
    "vid.error": ("không có video ({err})", "no video ({err})"),

    # --- ban do -----------------------------------------------------------
    "map.no_tiles": ("không có tile offline cho z{z} — lưới toạ độ thay thế\n"
                     "(đặt tile vào assets/tiles/{{z}}/{{x}}/{{y}}.png)",
                     "no offline tiles for z{z} — falling back to a coordinate grid\n"
                     "(put tiles in assets/tiles/{{z}}/{{x}}/{{y}}.png)"),
    "map.upscaled": ("ảnh thô z{tz} phóng to {k} lần — chưa tải chi tiết cho vùng này",
                     "coarse z{tz} imagery blown up {k}× — no detail downloaded here"),
    "map.unfollow": ("nháy đôi để bám lại theo drone", "double-click to re-follow the drone"),
    "map.fence_err": ("rào: {err}", "fence: {err}"),
    "map.fence_off": ("rào TẮT", "fence OFF"),
    "map.fence_on": ("rào BẬT", "fence ON"),
    "map.fence_notype": ("⚠ rào BẬT nhưng FENCE_TYPE=0 — FC không chặn gì cả",
                         "⚠ fence ON but FENCE_TYPE=0 — the FC blocks nothing"),
    "map.fence": ("rào: {bits}", "fence: {bits}"),
    "map.fence_ceil": ("trần {alt:.0f}m", "ceiling {alt:.0f}m"),
    "map.fence_poly": ("{n} đa giác", "{n} polygon(s)"),
    "map.wp_none": ("không có đường bay", "no mission"),
    "map.wp": ("đường bay {n} điểm", "mission, {n} point(s)"),
    "map.wp_cut": (" (FC có {total}, chỉ tải {got})", " (FC has {total}, only {got} loaded)"),
    "map.wp_now": (" · tới #{seq}", " · heading to #{seq}"),
    "map.no_home": ("⚠ CHƯA CÓ HOME — RTL không biết bay về đâu",
                    "⚠ NO HOME YET — RTL has nowhere to go"),
    "map.home_guess": ("⚠ HOME TẠM (điểm định vị đầu) — chưa nhận HOME_POSITION từ FC, "
                       "RTL KHÔNG về đây",
                       "⚠ PROVISIONAL HOME (first fix) — no HOME_POSITION from the FC yet, "
                       "RTL will NOT come here"),
    "map.left_fence": ("còn {m:.0f}m tới rào", "{m:.0f}m to the fence"),
    "map.left_keepout": ("cách vùng cấm {m:.0f}m", "{m:.0f}m from the keep-out zone"),
    "map.left_ceil": ("còn {m:.0f}m tới trần", "{m:.0f}m below the ceiling"),
    "map.home_dist": ("về nhà {m:.0f} m", "{m:.0f} m to home"),
    "map.draft": ("đang đặt {n} điểm @{alt:.0f}m — CHƯA NẠP",
                  "drafting {n} point(s) @{alt:.0f}m — NOT UPLOADED"),

    # --- tab Phan tich (doc .tlog) ----------------------------------------
    "an.browse": ("Mở file...", "Open file..."),
    # Rieng cua tab Phan tich, KHONG dung chung voi conn.pick_tlog: che do REPLAY
    # phat lai qua SikAdapter nen chi nhan .tlog, con doc de ve do thi thi nhan
    # ca .bin. Dung chung mot chuoi la mo duong cho .bin vao thang REPLAY.
    "an.pick_log": ("Chọn file log (.tlog hoặc .bin)", "Pick a log file (.tlog or .bin)"),
    "an.log_filter": ("Log bay (*.tlog *.bin *.BIN)", "Flight log (*.tlog *.bin *.BIN)"),
    "an.load": ("Đọc log", "Read log"),
    # Keo log .bin tu the SD cua FC ve qua duong telemetry — xem LogDownload.
    "an.from_fc": ("Tải từ FC", "Get from FC"),
    "an.from_fc_tip": (
        "Kéo log .bin từ thẻ SD của FC về qua đường telemetry. "
        "Log của FC đầy đủ hơn hẳn .tlog (1606 field so với 313), nhưng "
        "13 MB qua SiK 57600 mất gần 45 phút và chiếm gần hết đường truyền.",
        "Pull a .bin log off the FC's SD card over the telemetry link. The FC's "
        "own log is far richer than a .tlog (1606 fields vs 313), but 13 MB over "
        "a 57600 SiK link takes nearly 45 minutes and eats most of the bandwidth."),
    "an.fc_title": ("Log trên FC", "Logs on the FC"),
    "an.fc_scan": ("Hỏi lại danh sách", "Refresh list"),
    "an.fc_get": ("Tải về", "Download"),
    "an.fc_cancel": ("Hủy tải", "Cancel"),
    "an.fc_close": ("Đóng", "Close"),
    "an.fc_scanning": ("đang hỏi FC có những log nào...", "asking the FC what logs it has..."),
    "an.fc_none": ("FC báo không có log nào — thẻ SD trống hoặc chưa cắm.",
                   "FC reports no logs — the SD card is empty or missing."),
    "an.fc_found": ("{n}/{all} log", "{n} of {all} logs"),
    "an.fc_row": ("Log {id} — {mb:.1f} MB  {when}", "Log {id} — {mb:.1f} MB  {when}"),
    "an.fc_armed": ("Đang ARM: tải log lúc này là tự bịt mất đường số liệu của chính mình.",
                    "Armed: downloading now would choke your own telemetry link."),
    "an.fc_getting": ("đang tải {mb:.1f} MB — cứ để cửa sổ này mở",
                      "downloading {mb:.1f} MB — leave this window open"),
    "an.fc_progress": ("{mb:.2f} / {total:.1f} MB", "{mb:.2f} / {total:.1f} MB"),
    "an.fc_done": ("xong: {name}", "done: {name}"),
    "an.fc_partial": ("tải dở: {err}. {mb:.2f} MB đã lưu vẫn đọc được.",
                      "incomplete: {err}. The {mb:.2f} MB saved is still readable."),
    "an.loading": ("đang đọc log...", "reading log..."),
    "an.nothing": ("chưa đọc log nào — chọn một file rồi bấm Đọc log",
                   "no log read yet — pick a file and press Read log"),
    "an.summary": ("{name} — {msgs} gói · {mins:.1f} phút · {fields} field · đọc mất {sec:.1f}s",
                   "{name} — {msgs} packets · {mins:.1f} min · {fields} fields · read in {sec:.1f}s"),
    "an.err": ("không đọc được log: {err}", "cannot read log: {err}"),
    "an.empty": ("{name} — không có gói MAVLink nào đọc được: file rỗng, hỏng, "
                 "hoặc không phải .tlog",
                 "{name} — no readable MAVLink packet: the file is empty, corrupt, "
                 "or not a .tlog"),
    "an.empty_note": ("Log này không có gói nào đọc được.\n"
                      "Chọn một file .tlog khác.",
                      "No readable packet in this log.\n"
                      "Pick another .tlog file."),
    "an.filter": ("lọc field, vd: BATTERY hoặc PARAM.ATC",
                  "filter fields, e.g. BATTERY or PARAM.ATC"),
    "an.plot_empty": ("Biểu đồ {n} — tick field bên trái để vẽ",
                      "Chart {n} — tick fields on the left to plot"),
    "an.where": ("Biểu đồ {n} · {k}/{max} đường", "Chart {n} · {k}/{max} series"),
    "an.plot_full": ("Biểu đồ này đã đủ {max} đường. Bỏ tick một cái, hoặc "
                     "thêm biểu đồ mới.",
                     "This chart already has {max} series. Untick one, or add "
                     "another chart."),
    "an.add_plot": ("+ Biểu đồ", "+ Chart"),
    "an.add_plot_tip": ("Thêm một biểu đồ nữa, tối đa {max}.\n"
                        "Dùng khi các đại lượng khác đơn vị: điện áp 12 V vẽ chung\n"
                        "với độ cao 30 m thì đường điện áp bẹp thành một vạch.",
                        "Add another chart, up to {max}.\n"
                        "Use it for different units: 12 V plotted with 30 m\n"
                        "flattens the voltage into a straight line."),
    "an.del_plot": ("− Biểu đồ", "− Chart"),
    "an.del_plot_tip": ("Bỏ biểu đồ đang chọn (viền sáng). Luôn còn lại ít nhất một.",
                        "Remove the selected chart (highlighted border). "
                        "At least one always remains."),
    "an.normalize": ("Chuẩn hoá 0–1", "Normalise 0–1"),
    "an.normalize_tip": (
        "Kéo mọi đường về cùng thang 0–1 để so HÌNH DẠNG với nhau.\n"
        "Cần khi vẽ chung các đại lượng khác đơn vị — điện áp 12 V và độ cao 30 m\n"
        "trên cùng một trục thì đường điện áp bẹp thành một vạch.\n"
        "Giá trị thật vẫn hiện trong chú giải.",
        "Rescale every series to 0–1 to compare SHAPES.\n"
        "Needed when plotting different units together — 12 V and 30 m on one axis\n"
        "flattens the voltage into a straight line.\n"
        "The real range still shows in the legend."),
    "an.series_norm": ("{name}  [{lo:.6g} … {hi:.6g}]", "{name}  [{lo:.6g} … {hi:.6g}]"),
    "an.live": ("Trực tiếp", "Live"),
    "an.live_tip": (
        "Vẽ thẳng từ đường truyền đang chạy thay vì từ file.\n"
        "Giữ {sec:.0f} giây gần nhất — muốn xem lại cả chuyến thì tắt đi\n"
        "rồi đọc file .tlog, app ghi log cho mọi chế độ.\n"
        "Tab vẫn nghe sẵn khi đang xem file, nên bật lên là có ngay {sec:.0f} giây vừa rồi.",
        "Plot straight from the running link instead of a file.\n"
        "Keeps the last {sec:.0f} seconds — to review a whole flight, switch this off\n"
        "and read the .tlog; the app logs every mode.\n"
        "The tab listens even while showing a file, so switching on gives you\n"
        "the last {sec:.0f} seconds right away."),
    "an.live_summary": ("trực tiếp — {fields} field · {sec:.0f}s gần nhất · {hz:.0f} gói/s",
                        "live — {fields} fields · last {sec:.0f}s · {hz:.0f} packets/s"),
    "an.live_none": ("trực tiếp — chưa có gói nào: chưa kết nối, hoặc đường truyền im",
                     "live — no packet yet: not connected, or the link is silent"),
    "an.axis_time_live": ("thời gian (giây từ lúc mở app)", "time (s since app start)"),
    "an.axis_time": ("thời gian (giây từ đầu log)", "time (s from start of log)"),
    "an.axis_value": ("giá trị", "value"),
    "an.axis_norm": ("đã chuẩn hoá (0–1)", "normalised (0–1)"),

    # --- quy dao 3D --------------------------------------------------------
    "an.no_track": ("chưa có quỹ đạo", "no trajectory yet"),
    "an.no_fix": ("Log này không có định vị GPS — chỉ có độ cao.\n"
                  "FC báo lat=lon=0 khi chưa bắt được fix; vẽ ra sẽ là một\n"
                  "đường thẳng đứng chứ không phải đường bay thật.",
                  "This log has no GPS fix — altitude only.\n"
                  "The FC reports lat=lon=0 before it gets a fix; drawing that\n"
                  "would be a vertical line, not a real flight path."),
    "an.alt_range": ("cao {lo:.1f} … {hi:.1f} m", "alt {lo:.1f} … {hi:.1f} m"),

    # --- man bay cam ung (touch/) -----------------------------------------
    "touch.st_none": ("Chưa kết nối", "Not connected"),
    "touch.st_wait": ("Đang chờ dữ liệu từ FC", "Waiting for FC data"),
    "touch.st_lost": ("MẤT TÍN HIỆU SiK {n} s", "SiK SIGNAL LOST {n} s"),
    "touch.st_replay": ("Phát lại — lệnh bị khoá", "Replay — commands locked"),
    "touch.st_flying": ("Đang bay", "In flight"),
    "touch.st_armed": ("Đã ARM — cánh quạt có thể quay", "ARMED — props may spin"),
    "touch.st_ready": ("Sẵn sàng", "Ready"),
    "touch.st_nogps": ("Chưa có GPS", "No GPS"),
    "touch.slide": ("Trượt để {what}", "Slide to {what}"),
    "touch.do_arm": ("ARM", "ARM"),
    "touch.do_disarm": ("DISARM", "DISARM"),
    "touch.do_takeoff": ("cất cánh {alt:.0f} m", "take off {alt:.0f} m"),
    "touch.do_land": ("hạ cánh tại chỗ", "land here"),
    "touch.do_rtl": ("bay về nhà (RTL)", "return home (RTL)"),
    "touch.do_kill": ("CẮT ĐỘNG CƠ", "KILL MOTORS"),
    "touch.do_mode": ("đổi sang {name}", "switch to {name}"),
    "touch.btn_takeoff": ("Cất cánh", "Take off"),
    "touch.btn_land": ("Hạ cánh", "Land"),
    "touch.btn_rtl": ("Về nhà", "Home"),
    "touch.btn_mode": ("Chế độ", "Mode"),
    "touch.btn_kill": ("Cắt ĐC", "Kill"),
    "touch.left": ("CÒN", "LEFT"),
    "touch.no_gps_pos": ("Chưa có vị trí GPS của drone — chưa quay về được",
                         "No drone GPS position yet — cannot recenter"),
    "safe.fs_batt_off": ("Failsafe pin đang TẮT (BATT_FS_LOW_ACT = BATT_FS_CRT_ACT = 0) — hết pin FC không tự về",
                         "Battery failsafe is OFF (BATT_FS_LOW_ACT = BATT_FS_CRT_ACT = 0) — FC won't return on low battery"),
    "safe.fs_rc_off": ("Failsafe mất RC đang TẮT (FS_THR_ENABLE = 0)",
                       "RC-loss failsafe is OFF (FS_THR_ENABLE = 0)"),
    "safe.fs_gcs_off": ("Failsafe mất GCS đang TẮT (FS_GCS_ENABLE = 0) — mất SiK khi đang GUIDED/AUTO thì FC không tự xử lý",
                        "GCS failsafe is OFF (FS_GCS_ENABLE = 0) — losing SiK in GUIDED/AUTO triggers nothing"),
    "safe.low_volt_cells": ("BATT_LOW_VOLT = {v:.1f} V là {per:.2f} V/cell với pin {n}S — sai số cell (nên ~{want:.1f} V)",
                            "BATT_LOW_VOLT = {v:.1f} V is {per:.2f} V/cell on a {n}S pack — wrong cell count (expect ~{want:.1f} V)"),
    "safe.not_full": ("Pin có thể KHÔNG đầy lúc cắm: {vc:.2f} V/cell ≈ {vp:.0f}% nhưng FC tưởng {pct}% — ô CÒN sẽ báo dư",
                      "Battery may NOT have been full when plugged: {vc:.2f} V/cell ≈ {vp:.0f}% but FC assumes {pct}% — LEFT will overestimate"),
    "safe.rtl_now": ("VỀ NHÀ NGAY — còn {left}, về mất ~{need}", "RETURN NOW — {left} left, return takes ~{need}"),
    "safe.rtl_soon": ("Sắp phải về — còn {left}, về mất ~{need}", "Return soon — {left} left, return takes ~{need}"),
    "voice.ready": ("Sẵn sàng arm", "Ready to arm"),
    "voice.lost": ("Mất tín hiệu", "Signal lost"),
    "voice.rtl_soon": ("Sắp phải về", "Return soon"),
    "voice.rtl_now": ("Về nhà ngay", "Return now"),
    "voice.batt_low": ("Pin yếu, còn {pct} phần trăm", "Battery low, {pct} percent"),
    "voice.batt_crit": ("Pin rất yếu, còn {pct} phần trăm", "Battery critical, {pct} percent"),
    "set.voice": ("Đọc cảnh báo thành tiếng", "Speak warnings aloud"),
    "touch.ready_arm": ("SẴN SÀNG ARM", "READY TO ARM"),
    "touch.not_ready_arm": ("CHƯA SẴN SÀNG ARM", "NOT READY TO ARM"),
    "touch.kill_note": ("Cánh quạt dừng NGAY. Đang bay thì drone RƠI TỰ DO: hỏng máy, nguy hiểm "
                        "cho người bên dưới, không bật lại được giữa không trung. "
                        "Chỉ dùng khi drone mất kiểm soát.",
                        "Props stop AT ONCE. In flight the drone FREE-FALLS: it breaks, endangers "
                        "people below, and cannot restart mid-air. "
                        "Only when it is out of control."),
    "touch.locked": ("Chưa kết nối drone thật hay SITL — lệnh không đi đâu cả",
                     "Not connected to a live drone or SITL — commands go nowhere"),

    # duong bay dat bang tay: cham-giu ban do thay cho menu chuot phai
    "touch.wp_title": ("Đường bay", "Mission"),
    "touch.wp_hint": ("Chạm bản đồ để chọn chỗ, rồi bấm Đặt điểm",
                      "Tap the map to pick a spot, then Drop point"),
    "touch.wp_add": ("Đặt điểm {n}", "Drop point {n}"),
    # "Độ cao" tron: nhin y het bang do cao cua TAKEOFF, nguoi bay chinh o day
    # roi cho drone leo. No chi la do cao cua diem sap dat, va chi co tac dung
    # sau khi NAP + gat AUTO.
    "touch.wp_alt": ("Độ cao điểm", "Point altitude"),
    "touch.wp_undo": ("Bỏ điểm cuối", "Remove last point"),
    "touch.wp_clear": ("Xoá nháp", "Clear draft"),
    "touch.wp_send": ("NẠP {n} điểm", "UPLOAD {n} point(s)"),
    "touch.wp_send_over": ("NẠP ĐÈ {n} điểm", "UPLOAD {n} point(s) OVER the mission"),
    "touch.wp_wipe": ("Xoá đường bay trên FC", "Wipe mission on FC"),
    # Co {alt} trong nut: lenh nay DOI do cao, khong phai bay ngang toi do. Khong
    # ghi so ra thi nguoi bay o 50 m bam mot cai la xuong 20 m ma khong hieu vi sao.
    "touch.wp_goto": ("Bay tới đây ({alt:.0f} m)", "Fly here ({alt:.0f} m)"),
    "touch.wp_full": ("đã đủ {n} waypoint — không đặt thêm được",
                      "already {n} waypoints — cannot add more"),
    "touch.wp_overwrite": (
        "nạp đường bay: drone ĐANG BAY AUTO — ghi đè là FC nhảy sang WP1 của đường mới "
        "ngay. Bấm NẠP lại trong {sec:.0f}s để xác nhận",
        "mission upload: the drone is FLYING AUTO — overwriting makes the FC jump to WP1 "
        "of the new route immediately. Press UPLOAD again within {sec:.0f}s to confirm"),

    # can ao thay cho ban phim
    "touch.stick": ("Nhích", "Nudge"),
    "touch.stick_up": ("Lên", "Up"),
    "touch.stick_down": ("Xuống", "Down"),
}
