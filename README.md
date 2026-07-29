# GCS native — giao diện điều khiển drone trên laptop

Ứng dụng PySide6 chạy trên laptop Ubuntu. Nhận telemetry qua **SiK radio** bằng
pymavlink, nhận dữ liệu **ROS2** qua WebSocket từ companion.

Kế hoạch đầy đủ: [`KE_HOACH_GUI_NATIVE(3).md`](KE_HOACH_GUI_NATIVE\(3\).md) ·
Đặc tả envelope: [`docs/protocol.md`](docs/protocol.md)

---

## Chạy giao diện

```bash
cd ~/GUI_NATIVE
python3 -m laptop.app
```

App **không tự kết nối**. Mở ra là banner xám; chọn nguồn ở dock **"Ket noi"** bên
phải rồi bấm **Ket noi**. Mặc định im lặng an toàn hơn mặc định đoán sai.

### Cài phụ thuộc (một lần)

```bash
pip install --user PySide6 pymavlink pyyaml websockets pyserial
sudo usermod -aG dialout $USER      # quyen doc cong serial — DANG XUAT/DANG NHAP lai
```

Không dùng virtualenv: giữ thói quen `pip --user` để sau này đổi sang `rclpy`
trực tiếp thì `import rclpy` không hỏng.

---

## Ba nguồn kết nối

| Chế độ | Banner | Nguồn | Nút điều khiển |
|---|---|---|---|
| **REAL** | 🔴 đỏ | cổng USB tự quét | đầy đủ |
| **SIM** | 🔵 xanh | SITL qua TCP | đầy đủ + dock mô phỏng lỗi |
| **REPLAY** | ⚫ xám | file `.tlog` | **khoá hết, kể cả nút đỏ** |

`mode` trong `config/connections.yaml` là nguồn sự thật quyết định màu banner —
không suy từ chuỗi kết nối. Cắm SiK thật mà chọn profile SIM thì banner vẫn xanh.

### REAL — cắm radio vào USB

App **tự quét** mọi cổng USB-serial đang cắm (`ttyUSB*`, `ttyACM*`) và tạo một
dòng cho từng cổng, tên lấy từ chính thiết bị. Cắm sang cổng khác thì bấm
**"Quet lai cong USB"**, không sửa file.

Baud tự chọn: `ttyUSB*` → 57600 (radio SiK) · `ttyACM*` → 115200 (Pixhawk cắm thẳng).

Thiếu quyền thì dòng đó hiện `⚠ khong co quyen` kèm lệnh cần chạy.

### SIM — chạy với SITL + ROS2

Ba terminal:

```bash
# 1. Gazebo + SITL + MAVROS + mission (mo 4 cua so rieng)
cd ~/ros2-ardupilot-sitl-hardware
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch simtofly_mavros_sitl sitl_mission.launch.py

# 2. Cau noi ROS2 -> WebSocket (that ra chay tren companion)
source /opt/ros/humble/setup.bash
source ~/ros2-ardupilot-sitl-hardware/install/setup.bash
python3 ~/GUI_NATIVE/tools/ros2_bridge.py --host 127.0.0.1

# 3. Giao dien
cd ~/GUI_NATIVE && python3 -m laptop.app
```

Rồi chọn profile **`SITL + ROS2 (sitl_mission.launch.py)`**.

**Cổng nào cắm vào đâu:** MAVProxy giữ TCP 5760, MAVROS giữ UDP 14550. SITL còn
mở sẵn **5762/5763** — app cắm vào 5763, không phải sửa launch file bên ROS2.

Home của SITL mặc định đặt ở ĐH Công nghiệp TP.HCM để trùng với tile bản đồ
offline. Đổi chỗ bay:

```bash
ros2 launch simtofly_mavros_sitl sitl_mission.launch.py location:=<lat>,<lon>,10,0
```

### REPLAY — xem lại chuyến bay

Chọn profile `.tlog`, không cần drone hay SITL. Mọi nút điều khiển bị khoá —
không có gì ở đầu kia để gửi lệnh tới. App tự ghi `.tlog` ở **mọi** chế độ, kể cả
REAL; sau sự cố đó thường là thứ duy nhất cho biết chuyện gì đã xảy ra.

---

## Bốn tab

| Tab | Nội dung |
|---|---|
| **Bay** | Bản đồ vệ tinh offline + la bàn, chân trời nhân tạo, thanh telemetry đè lên |
| **Trạng thái** | ~350 field: mọi thứ FC gửi lên, cộng `SENSOR.*` giải mã và `PARAM.*` |
| **Điều khiển** | Phân quyền · ARM/mode/TAKEOFF · **nút đỏ** · nhiệm vụ ROS2 |
| **Thông báo** | STATUSTEXT của FC + kết quả mọi lệnh (`[APP]`) |

### Nút đỏ — RTL / LAND / DISARM

Đi thẳng qua SiK, **không qua companion, không kiểm tra quyền**. Bấm là tự kéo
quyền về GCS và gạt switch về MANUAL. Chỉ bị khoá duy nhất ở chế độ REPLAY.

### Phân quyền MANUAL ↔ AUTO

- **MANUAL**: bạn lái, lệnh thường (ARM/mode/TAKEOFF) đi được
- **AUTO**: giao cho node ROS2, lệnh thường bị từ chối, nút nhiệm vụ mở ra

Bấm nút đỏ là cách giành lại quyền nhanh nhất.

### Nhiệm vụ ROS2

Nút chọn nhiệm vụ gửi lệnh sang companion qua WebSocket — **laptop không gửi
setpoint**, nên không tranh luồng 30 Hz với node offboard. Muốn bridge tự khởi
động node thì chạy nó với `--spawn` (chỉ chạy tên trong danh sách trắng).

### Bản đồ

Tile offline ở `assets/tiles/{z}/{x}/{y}.png`. Hiện có sẵn nền thế giới z0–6,
cả Việt Nam z7–10, TP.HCM z11–14, hai bãi bay z13–19 (**17 238 tile, 247 MB**).

```bash
# Tai truoc cho mot bai bay (~12 phut, ~47 MB)
python3 tools/fetch_tiles.py --lat 10.8221 --lon 106.6868 --km 2 --zoom 13-19 --max 6000

# Xem muc zoom nao ve duoc, muc nao trong
python3 tools/fetch_tiles.py --coverage
```

Có mạng thì app **tự tải bù** tile còn thiếu và lưu lại cho lần bay offline sau.
Tắt bằng `ONLINE_TILES = False` trong `laptop/widgets/map_widget.py`.

---

## Kiểm thử

```bash
python3 tools/selfcheck.py      # 21 check, khong can SITL  (~90 giay)
python3 tools/check_halves.py   # hai nua hong doc lap, nguon gia
python3 tools/e2e_ros2.py       # nghiem thu tren stack ROS2 that
python3 tools/soak.py 30        # chay lien tuc 30 phut, do RAM + nhip Qt
```

`selfcheck.py` là hàng rào chính: chuẩn hoá NED→ENU, lọc nguồn MAVLink, trọng tài
đa nguồn, nút đỏ đi trước kiểm tra quyền, REPLAY khoá nút, quét USB, chốt chặn
TAKEOFF, tải tile.

---

## Bẫy đã gặp — đọc trước khi mất một tiếng

**`SIM_*` là trạng thái dai dẳng.** ArduPilot lưu tham số vào `eeprom.bin`, sống
qua mọi lần khởi động lại SITL. Tiêm lỗi xong (`SIM_MAG1_FAIL`, `SIM_ENGINE_FAIL`)
mà quên trả về là lần bay sau drone hỏng "không rõ lý do". Kiểm nhanh bằng cách gõ
`SENSOR.` vào ô lọc ở tab Trạng thái — cảm biến nào `HONG` hiện ngay.

**Node ROS2 mồ côi.** `ros2 run` chỉ là vỏ; giết nó không giết node thật. Một node
`mission_circle` sót lại stream setpoint 30 Hz làm **mọi lệnh TAKEOFF sau đó
thất bại im lặng** — FC nhận rồi bị chính luồng đó đè lên. App bắt được và báo
*"FC da nhan nhung do cao khong doi sau 6s"*. Kiểm tra:

```bash
ros2 topic hz /mavros/setpoint_raw/local     # co ai dang stream khong
pgrep -af "simtofly_mavros_sitl"             # node nao con song
```

**MAVProxy sống sót một mình.** Giết stack SITL mà quên MAVProxy thì nó vẫn giữ
kết nối tới SITL cũ. Luôn kiểm `pgrep -a mavproxy` sau khi dọn.

**Sửa launch file phải build lại.** `ros2 launch` đọc bản trong `install/`, không
phải `src/`:

```bash
colcon build --packages-select simtofly_mavros_sitl
```

**`gnome-terminal` chết khi chạy từ terminal của snap VS Code** (`LOCPATH`,
`GTK_PATH` trỏ vào `/snap/code`). Chạy launch từ terminal thường, hoặc:

```bash
env -u LOCPATH -u GTK_PATH -u GTK_EXE_PREFIX -u GIO_MODULE_DIR \
    -u GSETTINGS_SCHEMA_DIR -u GTK_IM_MODULE_FILE -u XDG_DATA_HOME \
    ros2 launch simtofly_mavros_sitl sitl_mission.launch.py
```

**TAKEOFF cần mode GUIDED.** Ở STABILIZE thì FC trả THẤT BẠI; ở LOITER nó trả
CHẤP NHẬN rồi không làm gì — app chặn trước và nói rõ.

**Treo tại chỗ thì dùng BRAKE hoặc GUIDED**, đừng ép cần điều khiển về giữa bằng
RC override: ArduPilot sẽ từ chối arm với `"Throttle (RC3) is not neutral"`.

---

## Log

| File | Nội dung |
|---|---|
| `logs/*.tlog` | MAVLink thô mọi chuyến, đọc được bằng Mission Planner |
| `logs/commands.log` | Mọi lần bấm nút và kết quả — nơi trả lời "sao nó không arm được" |
| `logs/gui.log` | stdout của app |

---

## Cấu trúc

```
core/            # DUNG CHUNG voi ban web
  bus.py         # envelope {src, topic, data, ts}
  field.py       # trong tai da nguon: best() tra ca gia tri lan nguon
  authority.py   # phan quyen + nhanh ESCAPE cho nut do
  adapters/
    sik.py       # pymavlink trong QThread, chuan hoa NED -> ENU
    remote.py    # WebSocket client toi companion

laptop/
  app.py         # QMainWindow
  connection.py  # quet cong USB + banner che do
  link_faults.py # mo phong dut duong truyen (chi SIM)
  tabs/          # flight, status, control, messages
  widgets/       # map, compass, attitude, telemetry_bar

tools/
  selfcheck.py     # 21 check, khong can SITL
  e2e_ros2.py      # nghiem thu tren stack ROS2 that
  ros2_bridge.py   # chay tren COMPANION: ROS2 <-> WebSocket
  fetch_tiles.py   # tai tile ban do offline
  soak.py          # bai chay lien tuc
```

Khoảng 4 760 dòng Python.
