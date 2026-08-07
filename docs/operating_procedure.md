# Quy trình bay — GCS native

Tờ giấy cầm ra bãi. README nói app **có gì**, file này nói **ngày bay làm gì**.

> ⚠️ Tính đến 07/08/2026 quy trình này đã chạy đủ trên SITL và một phần trên
> Pixhawk tháo cánh. **Chưa có chuyến bay thật nào qua radio SiK.** Mục
> [Chưa nghiệm thu](#chưa-nghiệm-thu) liệt kê đúng những chỗ còn là dự đoán.

---

## Hai người, hai việc

| Vai | Cầm gì | Trách nhiệm |
|---|---|---|
| **Người bay** | RC | Giành quyền bất cứ lúc nào, không cần hỏi. Là lớp cứu cuối cùng — không phải GCS |
| **Người vận hành** | Laptop | Đọc số liệu, bấm nút, hô to trạng thái |

Một người làm cả hai thì **không cất cánh**. Người vận hành nhìn màn hình thì
không nhìn được máy bay.

Người vận hành hô to, người bay xác nhận:
- `"ARM"` · `"CẤT CÁNH"` · `"NHIỆM VỤ CHẠY"` · `"TÔI NHẢ QUYỀN"` · `"BẤM ĐỎ"`

---

## A. Ở nhà — trước khi ra bãi

1. **Tải tile khu bay.** Mất ~12 phút, làm ở bãi bằng 4G thì lỡ buổi.
   ```bash
   python3 tools/fetch_tiles.py --lat <lat> --lon <lon> --km 2 --zoom 13-19 \
       --source google --max 6000
   python3 tools/fetch_tiles.py --coverage      # muc zoom nao trong thi thay ngay
   ```
2. **`python3 tools/selfcheck.py`** — phải PASS hết. Không cần SITL, ~90 giây.
   Đây là hàng rào: nút đỏ đi trước kiểm quyền, REPLAY khoá nút, quét USB, chốt
   TAKEOFF, trọng tài đa nguồn.
3. **Xoá `SIM_*` còn sót.** ArduPilot lưu tham số vào `eeprom.bin`, sống qua mọi
   lần khởi động lại. Tiêm lỗi hôm trước mà quên trả về là hôm nay drone hỏng
   "không rõ lý do". Gõ `SENSOR.` vào ô lọc tab Trạng thái — cảm biến nào `HONG`
   hiện ngay.
4. **Dọn tiến trình mồ côi.**
   ```bash
   pgrep -a mavproxy                            # song sot mot minh rat hay gap
   pgrep -af "simtofly_mavros_sitl"             # node stream setpoint 30 Hz
   ros2 topic hz /mavros/setpoint_raw/local     # con ai stream thi TAKEOFF se im lang that bai
   ```
5. Pin laptop, pin drone, pin RC. `logs/` còn chỗ trống.

---

## B. Tại bãi — trước khi cắm điện drone

- [ ] Khu trống, không người trong bán kính hạ cánh
- [ ] **Người bay cầm RC, đã bật, đã kiểm cần** — trước cả khi drone có điện
- [ ] Gió, mưa: không bay
- [ ] Mở sẵn Mission Planner ở màn hình bên cạnh *(những chuyến đầu — bảo hiểm
      miễn phí, và là thước đối chiếu xem app hiển thị đúng chưa)*

---

## C. Nối máy — theo đúng thứ tự này

1. **Cắm SiK vào laptop trước khi cấp điện drone.** Cắm ngược lại thì mất mấy
   chục giây đầu không có telemetry.
2. `python3 laptop/app.py`
3. Ở panel kết nối, bấm **"Quét lại cổng USB"**, chọn đúng dòng cổng vừa cắm.
   > **Không tin số thứ tự dòng.** Cổng USB tự quét được xếp **lên đầu** danh
   > sách, nên "dòng đầu tiên" hôm nay không phải dòng đầu tiên hôm qua. Công cụ
   > tự động phải gọi `win.panel.select("<tên profile>")`.
4. **Nhìn banner — phải ĐỎ, chữ REAL.** Xanh là SIM, xám là REPLAY. Banner đọc từ
   `mode` trong `connections.yaml`, không đoán từ chuỗi kết nối: **cắm SiK thật
   nhưng chọn nhầm profile SIM thì banner vẫn xanh và bạn đang lái máy bay thật
   bằng giao diện tô màu mô phỏng.** Sai màu → thoát app, chọn lại.
5. Cấp điện drone.

---

## D. Trước cất cánh — bảy thứ phải đọc trên màn hình

Không đủ bảy thì **không cất cánh**. Thứ tự này là thứ tự hỏng-thì-tệ-dần.

| # | Đọc ở đâu | Phải thấy |
|---|---|---|
| 1 | Dải trạng thái link | **SiK xanh.** Đây là đường nút đỏ. SiK xám = hết bay hôm nay |
| 2 | Tab Trạng thái | Số liệu **đang nhảy**, không đứng hình |
| 3 | Tab Bay | Chấm drone **đúng chỗ trên bản đồ**, không ở giữa biển |
| 4 | Tab Trạng thái, lọc `GPS` | Fix ≥ 3D, số vệ tinh ≥ 8, HDOP < 2 |
| 5 | Dải chữ dưới bản đồ | Geofence đã tải: bán kính + trần + đa giác. Chữ nói "chỉ có MAVLink1" nghĩa là mất phần đa giác |
| 6 | Tab Bay | **Home đã đặt, đúng chỗ đứng.** RTL bay về đây, không về chỗ bạn nghĩ |
| 7 | Tab Thông báo | Không có STATUSTEXT đỏ tồn đọng |

**Nửa ROS2 xám thì vẫn bay được** — mất vision/SLAM/task, còn bay và còn nút đỏ.
Đó là ranh giới suy giảm chức năng đã thiết kế, không phải lỗi. Nhưng phải biết
mình đang bay không có nó.

---

## E. Cất cánh

1. Người vận hành hô `"ARM"`, người bay xác nhận.
2. **Ga về min.** App tự chặn ARM khi ga quá `THR_ARM_MAX` — vì **FC không kiểm
   ga cao khi nhận lệnh ARM qua MAVLink**: đo được ga 1496 → `ack = 0` → động cơ
   ra 1654/1506/1347/1080 ngay lập tức. Tháo cánh thì đó là tiếng ồn; lắp cánh
   thì không.
   > App **vẫn cho** ARM khi mất `RC_CHANNELS` và nói rõ là không biết cần ga ở
   > đâu. Lúc đó trách nhiệm kiểm ga là của người bay.
3. **Mode GUIDED.** STABILIZE thì FC trả THẤT BẠI; LOITER thì FC trả CHẤP NHẬN
   rồi **không làm gì** — app chặn trước và nói rõ.
4. Bấm TAKEOFF, **bấm lại lần hai trong 3 giây** để xác nhận (`CONFIRM_S`).
   Không có hộp thoại — hộp thoại chặn làm nút đỏ chết trong khi vẫn báo là đang
   bật.
5. Nếu app báo *"FC đã nhận nhưng độ cao không đổi sau 6s"*: **có node ROS2 mồ
   côi đang stream setpoint 30 Hz đè lên.** Hạ xuống, dọn node, đừng bấm lại.

---

## F. Trong khi bay — đọc gì, ngưỡng nào phải hành động

| Nhìn | Ngưỡng | Làm gì |
|---|---|---|
| Pin | < 30% | Gọi về |
| Pin | < 20% | **RTL ngay**, không thương lượng |
| Dải link SiK | Chớp/xám | Xem kịch bản #3 |
| Cảnh báo divergence | Hai nguồn lệch > 5 m | Tin SiK. Nửa ROS2 đang nói sai vị trí |
| Khoảng cách tới hàng rào | Sát | Kéo về, đừng để FC tự xử |
| Tab Thông báo | STATUSTEXT đỏ | Đọc to lên, quyết định trong 5 giây |

**Nút đỏ RTL / LAND / DISARM** đi thẳng qua SiK — không qua companion, không
kiểm tra quyền, tự kéo quyền về GCS và gạt switch về MANUAL. Đây là cách giành
lại quyền nhanh nhất. Chỉ bị khoá ở chế độ REPLAY.

**Nút đỏ DISARM chia theo đang-ở-dưới-đất, không theo cần ga:**

| FC báo đang ở dưới đất? | Bấm một phát | Giữ 2 giây |
|---|---|---|
| **có** | force ngay — ga ở mức nào cũng ngắt được | — |
| **không** | lệnh thường (FC sẽ từ chối nếu nó tin là đang bay) | force |
| **không biết** (số liệu quá 2 s) | lệnh thường | force |

> **Đang bay mà giữ đủ 2 giây thì drone rơi.** Đó là chủ ý — nó là nút dành cho
> lúc rơi vẫn đỡ hơn là bay tiếp. Đừng giữ nút cho chắc.

---

## G. Bàn giao quyền cho nhiệm vụ ROS2

1. Người vận hành hô `"TÔI NHẢ QUYỀN"`, chờ người bay xác nhận.
2. Gạt sang **AUTO**. Lệnh thường (ARM/mode/TAKEOFF) từ đây bị từ chối có báo —
   đó là đúng, không phải lỗi.
3. Chọn nhiệm vụ. Laptop **không gửi setpoint**, chỉ nhắn companion; luồng 30 Hz
   nằm trên drone.
4. **Trong lúc AUTO, nút đỏ vẫn ăn nguyên.** Không cần gạt về MANUAL trước.
5. Hết nhiệm vụ: gạt về MANUAL, hô `"TÔI CẦM LẠI"`.

---

## H. Mười hai kịch bản hỏng — người vận hành làm gì

Bốn kịch bản đầu tập trước bằng nút "Cắt link" ở panel Sim, rồi mới rút dây thật.

| # | Thấy gì | Nghĩa là | Làm gì |
|---|---|---|---|
| 1 | Tab ROS2 xám, số liệu tụt về SiK, app cảnh báo | WiFi rớt, **companion còn sống — task tự hành VẪN ĐANG CHẠY trên drone** | Nút đỏ RTL. Đừng chờ WiFi lên lại |
| 2 | Tab ROS2 xám, FC giữ mode cuối | Companion chết hẳn | Bay tiếp bằng nửa SiK, hoặc RTL. Nút đỏ vẫn ăn |
| 3 | **Cảnh báo nặng** | Mất SiK — **mất đường cứu sinh** | Hô cho người bay giành quyền RC **ngay**. Cắm lại SiK trong lúc đó |
| 4 | Báo động rõ ràng, không giả vờ còn kết nối | Mất cả SiK lẫn WiFi | **RC là thứ duy nhất còn lại.** Người bay hạ cánh bằng mắt |
| 5 | Bấm RTL trong lúc ROS2 stream setpoint | — | Drone về nhà, không giằng co. Không phải bấm gì thêm |
| 6 | Bấm nút thường lúc đang AUTO | Bị từ chối, có thông báo | Gạt MANUAL hoặc bấm nút đỏ |
| 7 | App tắt ngóm | Crash | **Drone giữ nguyên mode, không rơi.** Người bay cầm RC. Mở lại app, nối lại |
| 8 | Cảnh báo divergence | Hai nguồn lệch > 5 m | Tin SiK. Về, đừng bay nhiệm vụ tiếp |
| 9 | Ra xa dần, ROS2 rụng trước | Đúng như thiết kế | SiK vẫn nắm được drone. Kéo về |
| 10 | Bay dài > 30 phút | — | Bài `tools/soak.py 30` phải PASS trước ở nhà |
| 11 | Mở REPLAY, bấm nút | — | **Mọi nút khoá, kể cả nút đỏ.** Bấm không ăn là đúng |
| 12 | Cắm SiK thật, chọn profile SIM | Banner phải theo `mode` đã chọn | Thoát app, chọn lại profile. Xem mục C.4 |

---

## I. Sau khi hạ cánh

1. DISARM (dưới đất thì một phát là force, ăn ngay).
2. **Ngắt điện drone trước, rút SiK sau.**
3. Lưu `logs/*.tlog` của chuyến — đây là đầu vào cho chế độ REPLAY và cho Mission
   Planner.
4. Có gì lạ thì mở `logs/commands.log` — nó trả lời "sao nó không arm được".
5. Có tiêm lỗi trong buổi thì **trả `SIM_*` về ngay bây giờ**, không để mai.

---

## Chưa nghiệm thu

Đọc trước khi tin quy trình này ở chỗ nào.

- **Chưa từng có chuyến bay thật qua radio SiK.** Băng thông mới chỉ đo trên USB
  (`/dev/ttyACM0`): 1895–1986 B/s, gấp ~2,4 lần ước lượng 800 B/s của kế hoạch.
  Trên radio thật con số sẽ thấp hơn — **chưa biết thấp bao nhiêu**, nên chưa
  biết tần suất cập nhật màn hình lúc bay xa sẽ ra sao. Đo bằng
  `tools/measure_bandwidth.py` ngay chuyến đầu.
- **Chặng ga-giữa-tầm của nút đỏ chưa có bằng chứng phần cứng.** Cần thấy
  `tools/hitl.py disarm` in `landed = False` mà vẫn gửi FORCE — chứng minh
  rangefinder gánh được khi `landed_state` lật sang IN_AIR. Hai tlog 04/08 đều
  chỉ có `landed_state = 1`.
- **Nửa WiFi chưa đáng tin trên Pi5.** Đo 06/08: có tải video thì mất mạng > 50%
  thời gian trong 10 phút, nghỉ hoàn toàn thì 25 phút không rung. Nghi anten mạch
  in. Lệnh ROS2 đi **chung đường đó** — nên đến khi thay module WiFi rời, coi kịch
  bản #1 là *sẽ xảy ra*, không phải *có thể*. Chi tiết ở `docs/setup_pi5.md`.
- **`task_manager` KHÔNG tự về IDLE khi mất heartbeat GCS** — cố ý. Mất WiFi thì
  nhiệm vụ chạy tiếp, kéo về là việc của nút đỏ qua SiK. Nếu sau này bật, **sửa
  mục H kịch bản #1 trước khi bay**, vì lúc đó drone sẽ tự dừng ngay chỗ nó vừa
  ra khỏi tầm sóng.
