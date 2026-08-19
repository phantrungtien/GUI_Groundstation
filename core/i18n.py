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
    "conn.pick_tlog": ("Chọn file .tlog", "Pick a .tlog file"),
    "conn.tlog_filter": ("Telemetry log (*.tlog)", "Telemetry log (*.tlog)"),
    "conn.no_tlog": ("Chưa chọn file .tlog nào.", "No .tlog file selected."),
    "conn.opening_msg": ("Đang nối {target}", "Connecting to {target}"),
    "conn.fail_title": ("Không kết nối được", "Cannot connect"),
    "conn.sik_lost": ("Mất kết nối SiK: {why}", "SiK link lost: {why}"),
    "conn.sik_silent": ("SiK im lặng {n}s", "SiK silent for {n}s"),
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
    "ctl.hold_kill": ("GIỮ 2s = CẮT ĐỘNG CƠ", "HOLD 2s = CUT MOTORS"),
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
    "fly.wp_overwrite": (
        "nạp đường bay: drone ĐANG BAY AUTO — ghi đè là FC nhảy sang WP1 của đường mới "
        "ngay. Mở lại menu và bấm lại trong {sec:.0f}s để xác nhận",
        "mission upload: the drone is FLYING AUTO — overwriting makes the FC jump to WP1 "
        "of the new route immediately. Reopen the menu and press again within {sec:.0f}s "
        "to confirm"),
    "menu.wp_add": ("Đặt waypoint {n} tại đây  ({alt:.0f} m)",
                    "Put waypoint {n} here  ({alt:.0f} m)"),
    "menu.wp_alt": ("Độ cao waypoint: {alt:.0f} m", "Waypoint altitude: {alt:.0f} m"),
    "menu.wp_undo": ("Bỏ điểm {n}", "Remove point {n}"),
    "menu.wp_clear": ("Xoá hết {n} điểm đang đặt", "Clear all {n} draft points"),
    "menu.wp_send": ("NẠP {n} waypoint lên FC", "UPLOAD {n} waypoint(s) to the FC"),
    "menu.wp_send_over": ("NẠP {n} waypoint ĐÈ LÊN nhiệm vụ đang bay",
                          "UPLOAD {n} waypoint(s) OVER the mission in flight"),
    "menu.wp_wipe": ("Xoá đường bay trên FC", "Wipe the mission on the FC"),
    "menu.goto": ("GUIDED + bay tới {lat:.5f}, {lon:.5f}",
                  "GUIDED + fly to {lat:.5f}, {lon:.5f}"),
    "menu.cam_hide": ("Ẩn camera", "Hide camera"),
    "menu.cam_show": ("Hiện camera", "Show camera"),
    "act.wp_wipe": ("xoá đường bay trên FC", "wipe mission on FC"),
    "act.wp_send": ("nạp {n} waypoint", "upload {n} waypoint(s)"),
    "act.resume": ("tiếp tục nhiệm vụ", "resume mission"),
    "act.land_here": ("hạ cánh tại chỗ", "land here"),

    # nhich vi tri bang ban phim
    "nudge.blocked": ("nhích vị trí: KHÔNG được — {why}", "nudge: NOT allowed — {why}"),
    "nudge.stopped": ("nhích vị trí: dừng — {why}", "nudge: stopped — {why}"),
    "nudge.hold": ("nhích vị trí: {why} -> treo tại chỗ", "nudge: {why} -> holding position"),
    "nudge.no_mode": ("chế độ này không gửi lệnh được", "this mode cannot send commands"),
    "nudge.not_armed": ("drone chưa armed", "the drone is not armed"),
    "nudge.on_ground": ("drone đang nằm dưới đất", "the drone is on the ground"),
    "nudge.wrong_mode": ("đang ở mode {mode}, phải chuyển sang GUIDED mới nhích được",
                         "currently in {mode}; switch to GUIDED to nudge"),
    "nudge.why_space": ("treo tại chỗ", "hold position"),
    "nudge.why_release": ("thả phím", "key released"),
    "nudge.why_focus": ("rời khỏi màn hình bay", "left the flight screen"),

    # --- tab Status -------------------------------------------------------
    "st.search": ("lọc theo tên field, vd: ATTITUDE hoặc volt",
                  "filter by field name, e.g. ATTITUDE or volt"),
    "st.freeze": ("Tạm dừng", "Freeze"),
    "st.read_pid": ("Đọc {n} tham số PID", "Read {n} PID parameters"),
    "st.reading": ("Đang đọc... còn {n}", "Reading... {n} left"),
    "st.pid_tip": ("FC không tự gửi tham số — bấm để hỏi. Kết quả vào hàng PARAM.*; "
                   "rê chuột lên một hàng để xem tham số đó là gì.",
                   "The FC does not push parameters — press to ask. Results land in PARAM.* "
                   "rows; hover a row to see what that parameter does."),
    "st.pid_missing": ("{n} tham số không có trên firmware này: {names}",
                       "{n} parameter(s) absent from this firmware: {names}"),
    "st.count": ("{n} field", "{n} field(s)"),
    "st.col_field": ("Field", "Field"),
    "st.col_value": ("Giá trị", "Value"),
    "st.col_src": ("Nguồn", "Source"),
    "st.col_age": ("Tuổi", "Age"),

    # --- tab Messages -----------------------------------------------------
    "msg.level": ("Mức độ:", "Level:"),
    "msg.clear": ("Xoá", "Clear"),
    "msg.f_all": ("Tất cả", "All"),
    "msg.f_notice": ("Notice trở lên", "Notice and above"),
    "msg.f_warn": ("Cảnh báo trở lên", "Warning and above"),
    "msg.f_err": ("Lỗi trở lên", "Error and above"),

    # --- thanh telemetry duoi ban do ------------------------------------
    "tlm.ALT": ("CAO", "ALT"),
    "tlm.SPD": ("TỐC", "SPD"),
    "tlm.PIN": ("PIN", "BAT"),
    "tlm.SAT": ("VỆ TINH", "SAT"),
    "tlm.MODE": ("MODE", "MODE"),

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
    "map.fence": ("rào: {bits}", "fence: {bits}"),
    "map.fence_ceil": ("trần {alt:.0f}m", "ceiling {alt:.0f}m"),
    "map.fence_poly": ("{n} đa giác", "{n} polygon(s)"),
    "map.wp_none": ("không có đường bay", "no mission"),
    "map.wp": ("đường bay {n} điểm", "mission, {n} point(s)"),
    "map.wp_cut": (" (FC có {total}, chỉ tải {got})", " (FC has {total}, only {got} loaded)"),
    "map.wp_now": (" · tới #{seq}", " · heading to #{seq}"),
    "map.draft": ("đang đặt {n} điểm @{alt:.0f}m — CHƯA NẠP",
                  "drafting {n} point(s) @{alt:.0f}m — NOT UPLOADED"),
}
