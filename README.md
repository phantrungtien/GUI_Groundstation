# GCS native — giao diện điều khiển drone trên laptop

Ứng dụng PySide6 chạy trên laptop Ubuntu. Nhận telemetry qua **SiK radio** bằng
pymavlink, nhận dữ liệu **ROS2** qua WebSocket từ companion.

Đặc tả envelope: [`docs/protocol.md`](docs/protocol.md) ·
Báo cáo giao diện: [`baocao/BAO_CAO_GIAO_DIEN.md`](baocao/BAO_CAO_GIAO_DIEN.md)

**Ngày bay thì cầm [`docs/operating_procedure.md`](docs/operating_procedure.md)** —
checklist trước cất cánh, ngưỡng phải hành động, 12 kịch bản hỏng.

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

### Trên Windows

```cmd
py -m pip install PySide6 pymavlink pyyaml websockets pyserial
py -m laptop.app
```

Không có nhóm `dialout`; thay vào đó phải có **driver USB-serial**: FTDI VCP hoặc
Silicon Labs CP210x cho radio SiK, Pixhawk cắm thẳng thì Windows 10/11 tự nhận
(CDC). Cắm xong bấm **"Quet lai cong USB"** — cổng hiện ra là `COM3`, `COM4`…
thay vì `/dev/ttyUSB0`. Baud tự chọn theo VID của chip, không theo tên cổng.

Chạy được trên Windows: **toàn bộ giao diện** — SiK, SITL qua TCP, replay `.tlog`,
bản đồ, video MJPEG. **Không** chạy được: mọi thứ trong `tools/` cần ROS2 hoặc
`bash`/`pkill` (`ros2_bridge.py`, `e2e_ros2.py`, `hitl.py`, `compare_gcs.py`) —
những cái đó thuộc về máy Linux chạy SITL/companion, không phải máy chạy GUI.

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

## Sáu tab

| Tab | Nội dung |
|---|---|
| **Bay** | Bản đồ vệ tinh offline + la bàn, chân trời nhân tạo, thanh telemetry đè lên |
| **Trạng thái** | ~350 field: mọi thứ FC gửi lên, cộng `SENSOR.*` giải mã và `PARAM.*`. Hai cột: `Field` và `Giá trị`. Field ngừng cập nhật quá `STALE` giây thì **giá trị xám đi** — đứng hình mà vẫn đen là nói dối |
| **Điều khiển** | ARM/mode/TAKEOFF · **nút đỏ** · trạng thái node ROS2 (chỉ đọc) |
| **Thông báo** | STATUSTEXT của FC + kết quả mọi lệnh (`[APP]`) |
| **Camera** | Luồng MJPEG từ companion (cùng nguồn với ô PiP trên tab Bay) |
| **Cài đặt** | Ngôn ngữ giao diện |

### Thanh telemetry — ba ô tự đổi màu

`ARM · CAO · TỐC · PIN · VỆ TINH · MODE`. Ô **ARM** đứng đầu vì đó là thứ phải
liếc một cái là thấy: `MODE = GUIDED` không nói gì về chuyện cánh quạt đang quay
hay đứng yên. Đã ARM thì ô đỏ — đỏ ở đây **không** nghĩa là hỏng, nghĩa là đứng
lại gần.

**PIN đổi màu theo phần trăm FC báo, không theo điện áp.** Điện áp một mình không
nói lên còn bao nhiêu nếu không biết số cell, mà số cell thì đổi thật: ba chuyến
bay gần đây đo được 16,8 V / 15,2 V / 11,7 V — 4S và 3S xen kẽ nhau, một ngưỡng
điện áp cứng sẽ sai ở ít nhất một chuyến. FC biết `BATT_CAPACITY` và số cell nên
phần trăm của nó mới là con số có nghĩa (ba chuyến đó FC báo 98%, 99%, 77–81%).
≤30% vàng, ≤20% đỏ — khớp đúng bảng ngưỡng ở mục F của `docs/operating_procedure.md`, và selfcheck đọc chính file đó để chốt hai con số không trôi khỏi nhau. Sửa ở `laptop/widgets/telemetry_bar.py`.

FC **không** báo phần trăm (`BATT_CAPACITY` chưa đặt) thì ô này **không có ngưỡng**
và tooltip nói thẳng ra như vậy, chứ không bịa một ngưỡng rồi để người bay tin.

**VỆ TINH đổi màu theo `fix_type`, không theo số vệ tinh.** Đo thật trên bàn:
`fix_type=1, sats=0` — đếm vệ tinh một mình thì ô đó hiện số `0` trắng tinh như
mọi số khác. Dưới 2D fix là đỏ, đúng 2D fix (không có độ cao GPS) là vàng. Rê
chuột lên ô để biết fix loại nào.

### Tham số PID — rê chuột là biết nó là gì

Nút **Đọc 63 tham số PID** ở tab **Trạng thái** hỏi FC từng nhóm rồi đổ vào các
hàng `PARAM.*`. **Rê chuột lên một hàng** là ra một dòng giải thích tham số đó
làm gì — không phải mở tài liệu ArduPilot ở tab khác.

Chữ nằm ở [`core/param_doc.py`](core/param_doc.py), theo cả hai ngôn ngữ. Họ
`ATC_RAT_{RLL,PIT,YAW}_{P,I,D,IMAX,FLTT,FLTE,FLTD,SMAX}` và `PSC_*` **ghép** từ
hai bảng mảnh (trục nào × hệ số nào) chứ không viết tay từng cái: 24 dòng na ná
nhau là 24 cơ hội gõ nhầm, và thêm một hệ số mới thì không phải thêm dòng nào.
Cái không theo khuôn (`MOT_*`, `WPNAV_*`, `ANGLE_MAX`…) ghi thẳng ở `EXPLICIT`.

Không làm cột riêng: bảng có ~350 hàng mà chỉ 63 hàng có mô tả, cột đó sẽ trống
85%. Field thường (`ATTITUDE.roll`…) **không** bịa mô tả — thiếu thì im lặng.

### Ngôn ngữ — tiếng Việt / English

Tab **Cài đặt** đổi toàn bộ chữ trên giao diện giữa tiếng Việt có dấu và tiếng
Anh. Đổi là **hiện ngay**, không khởi động lại — đổi giữa chuyến bay không được
phép làm mất kết nối. Lựa chọn nhớ bằng `QSettings` (Linux: `~/.config/GCS/`,
Windows: registry).

**Không dịch**, cố ý: tên mode của FC (`GUIDED`, `AUTO`, `LOITER`…), tên field
MAVLink, mã lệnh, và chữ trên nút `ARM`/`DISARM`/`TAKEOFF`/`RTL`/`LAND`. Đó là
từ vựng của ArduPilot — dịch ra thì không đối chiếu được với tài liệu hay với
GCS khác.

Bảng chữ nằm ở [`core/i18n.py`](core/i18n.py), một `dict` Python `key: (vi, en)`.
Thêm chữ mới thì thêm một dòng ở đó rồi gọi `t("key")`; key chưa có trong bảng
sẽ **hiện ra chính cái key** trên màn hình, không im lặng rơi về tiếng Việt.
`tools/selfcheck.py` đối chiếu từng cặp: thiếu một bản dịch, hay lệch chỗ trống
`{...}` giữa hai bản, là fail.

### Nút đỏ — RTL / LAND / DISARM

Đi thẳng qua SiK, **không qua companion**. Chỉ bị khoá duy nhất ở chế độ REPLAY.

### Laptop cầm toàn quyền

Không còn switch MANUAL/AUTO. Mọi lệnh xuống FC — kể cả nạp đường bay — đi từ
app này qua SiK. `/gcs/authority` chốt cứng ở `"gcs"` ngay lúc `ros2_bridge.py`
khởi động và không có đường nào đổi, nên **node offboard trên companion không
bao giờ được lái**. Nửa ROS2 chỉ còn là nguồn telemetry: vị trí, vận tốc, video,
tên node đang chạy. Mất nó là mất tầm nhìn, không phải mất quyền điều khiển.

### Đường bay waypoint — đọc và ghi

Chuột phải trên bản đồ: **đặt waypoint** (tối đa 50, chọn độ cao trong menu),
**nạp lên FC**, hoặc **xoá đường bay trên FC**. Nạp xong app đọc ngược lại từ FC
rồi mới vẽ — cái hiện trên bản đồ là cái FC đang thật sự giữ, không phải cái vừa
gửi đi. Đường tím liền là đường bay trên FC (số theo `seq` của FC, mục 0 là home
do ArduPilot tự giữ); đường tím nhạt đứt nét là đường **đang đặt, chưa nạp**.

Đang bay AUTO mà nạp đè thì phải bấm hai lần — FC nhảy sang WP1 của đường mới
ngay khi nhận.

### Bản đồ

Tile offline ở `assets/tiles/{z}/{x}/{y}.png`. Hiện có sẵn nền thế giới z0–6,
cả Việt Nam z7–10, TP.HCM z11–14, hai bãi bay z13–19, riêng IUH thêm z20–21
(**21 038 tile, 265 MB**). Trong đó 7757 tile quanh IUH là Google, phần còn lại
vẫn là Esri cũ — zoom ra khỏi bán kính 2 km sẽ thấy tông ảnh đổi.

```bash
# Tai truoc cho mot bai bay (~12 phut)
python3 tools/fetch_tiles.py --lat 10.8221 --lon 106.6868 --km 2 --zoom 13-19 \
    --source google --max 6000

# Doi nguon anh: --refetch de GHI DE tile cu, khong thi no bo qua ("co roi")
# va man hinh tron hai kieu anh
python3 tools/fetch_tiles.py ... --source esri --refetch

# Xem muc zoom nao ve duoc, muc nao trong
python3 tools/fetch_tiles.py --coverage
```

Nguồn ghi ở `assets/tiles/SOURCE.txt` (dòng 1 tên nguồn để ghi công trên map,
dòng 2 URL template để app tải bù đúng nguồn đã prefetch).

**Vì sao dùng `--source google`.** Đo tại IUH, ba tile khác vị trí mỗi mức zoom:
Esri cho z19 22/15/18 KB rồi **z20 và z21 đều là 2521 byte cùng md5** — tấm "no
data" lặp lại; Google cho z21 vẫn 7,6/6,1/4,8 KB, tức ảnh gốc thật. Quy ra
**Esri trần ở 29 cm/pixel, Google xuống tới 7,3 cm/pixel**.

Đổi lại: `mt1.google.com/vt` là **endpoint không chính thức**, Google có thể chặn
IP hoặc đổi endpoint bất cứ lúc nào. Nên **luôn prefetch khu bay trước**, coi
online chỉ là phần bù — mất mạng hay bị chặn giữa buổi bay thì map vẫn vẽ từ đĩa.
`DEFAULT_TILE_URL` trong `map_widget.py` vẫn để Esri làm dự phòng khi `SOURCE.txt`
mất.

Có mạng thì app **tự tải bù** tile còn thiếu và lưu lại cho lần bay offline sau.
Tắt bằng `ONLINE_TILES = False` trong `laptop/widgets/map_widget.py`.

---

## Kiểm thử

```bash
python3 tools/selfcheck.py      # 32 check, khong can SITL  (~90 giay)
python3 tools/check_halves.py   # hai nua hong doc lap, nguon gia
python3 tools/e2e_ros2.py       # nghiem thu tren stack ROS2 that
python3 tools/soak.py 30        # chay lien tuc 30 phut, do RAM + nhip Qt
python3 tools/compare_gcs.py --takeoff   # so tung con so voi MAVProxy, cung mot luong
```

`compare_gcs.py` là nghiệm thu N2: nó cho GUI và một GCS khác **đọc chung một
luồng gói tin**, rồi so từng con số ở hai trạng thái tĩnh (trên đất, treo 10 m).
Số đo và cái nó *chưa* chứng minh được: [`docs/doi_chieu_gcs.md`](docs/doi_chieu_gcs.md).

⚠️ **`--takeoff` nâng drone lên thật.** Không có cờ đó thì nó chỉ đo trạng thái
đang có, không ARM. Cắm FC thật thì đọc mục 8 của tài liệu trên trước:

```bash
CMP_MASTER=/dev/ttyUSB0 CMP_BAUD=57600 \
    python3 tools/compare_gcs.py --home 10.8221,106.6868
```

Hai kịch bản hỏng chỉ đo được trên phần cứng thật — **tháo cánh quạt trước**:

```bash
python3 tools/hitl.py 12              # profile SIM cam vao FC that -> banner van SIM
python3 tools/hitl.py 7               # SIGKILL app -> FC giu nguyen mode
python3 tools/hitl.py 7 --arm         # nhu tren nhung ARM truoc (cho ha ga ve min)
python3 tools/hitl.py armcycle        # ARM/DISARM: do tre, tu ngat, chan ga cao, lenh thua
python3 tools/hitl.py disarm          # nut do DISARM hai bac tren FC that
python3 tools/measure_bandwidth.py    # byte/s that theo tung loai message
```

`selfcheck.py` là hàng rào chính: chuẩn hoá NED→ENU, lọc nguồn MAVLink, trọng tài
đa nguồn, nút đỏ đi trước kiểm tra quyền, REPLAY khoá nút, quét USB, chốt chặn
TAKEOFF, tải tile.

---

## Bẫy đã gặp — đọc trước khi mất một tiếng

**Hộp thoại chặn làm nút đỏ chết trong khi vẫn báo là đang bật.** Đo: lúc một
`QMessageBox` đang mở, `QApplication.activeModalWidget()` khác `None` nên cửa sổ
chính không nhận input — ba nút đỏ vẫn trả `isEnabled() == True` nhưng bấm không
ăn. Xác nhận TAKEOFF ở chế độ REAL vì thế đổi sang **bấm lại trong 3 giây**
(`CONFIRM_S`), không dùng dialog. Hai `QMessageBox` còn lại trong app đều chỉ bật
khi **chưa** kết nối (`app.py:253` chỉ hiện khi chưa từng nhận được byte nào,
`connection.py:272` khi chưa chọn file `.tlog`) — không có drone trên trời thì
không có gì để cứu.

**FC không kiểm cần ga khi nhận lệnh ARM.** `AP_Arming.cpp:81-115` chỉ kiểm ga có
**thấp hơn** ngưỡng failsafe không; kiểm "ga quá cao" chỉ áp cho arm bằng cần lái.
Đo được: ga 1496 → `ack = 0` → động cơ ra 1654/1506/1347/1080 ngay lập tức. Tháo
cánh thì đó là tiếng ồn, lắp cánh thì không. **App tự chặn** — `THR_ARM_MAX` trong
`laptop/tabs/control.py`, đặt theo `RC3_MIN` + `THR_DZ` của khung; đổi radio thì
đọc lại hai tham số đó. Không thấy `RC_CHANNELS` thì vẫn gửi và nói rõ là không
biết cần ga ở đâu — mất telemetry mà khoá luôn nút ARM là đổi một kiểu hỏng lấy
một kiểu hỏng khác.

**Lệnh DISARM thường ngừng ăn ngay khi cần nó nhất.** ArduCopter chặn mọi lệnh
disarm đến từ GCS khi nó chưa tin là đã hạ cánh (`ArduCopter/AP_Arming.cpp:788`).
Đo trên MicoAir743, tháo cánh:

| Trạng thái FC | Lệnh DISARM thường |
|---|---|
| ga min, motor 1000 (idle) | **chấp nhận** — `armed=False` ngay |
| ga giữa tầm, motor 1654/1506/1347/1080 | **`ack = 4`, 3/3 lần từ chối** |

Dãy motor chênh nhau ở hàng hai là FC đang ổn định tư thế — nó tin là đang bay,
nên `land_complete` sai. `force = 21196` ăn ngay lần đầu ở cả hai trạng thái.

Nghĩa là **vị trí cần ga quyết định nút DISARM có ăn hay không** — thứ không ai
đoán được lúc cần ngắt gấp. Nên cả hai nút DISARM (nút đỏ và nút thường) chia
theo **đang ở dưới đất hay không**, không theo cần ga:

| Đang ở dưới đất? | Bấm một phát | Giữ 2 giây |
|---|---|---|
| **có** | **force ngay** — ga ở mức nào cũng ngắt được | — |
| **không** (FC báo đang bay) | lệnh thường (FC từ chối nếu nó tin là đang bay) | force |
| **không biết** (mất telemetry, số liệu quá 2 s) | lệnh thường | force |

Hàng cuối là chỗ dễ làm sai nhất: không có số liệu thì **không được đoán là đang
dưới đất**. Đoán bừa hướng đó là cho một cú bấm nhầm tắt động cơ giữa không
trung. Đang bay mà giữ đủ 2 giây thì drone rơi — đó là chủ ý, không phải tác
dụng phụ.

**Không được suy "dưới đất" từ độ cao.** `position.alt_rel` đọc ra **-8,5 m suốt
10 giây** khi MicoAir743 treo yên và rangefinder nói 0,6 m — GPS fix 0 thì độ cao
tương đối là rác. Lệch 8,5 m theo chiều âm nghĩa là máy bay ở 7 m vẫn ra "dưới
1 m", đúng hướng hỏng tệ nhất. `_on_ground()` (`laptop/tabs/control.py`) hỏi hai
nguồn độc lập, nguồn nào nói "dưới đất" cũng đủ:

1. `EXTENDED_SYS_STATE.landed_state` — chính là `land_complete` của FC, tức đúng
   cái cờ quyết định lệnh thường có ăn hay không. Message này **không nằm trong
   bộ stream cũ nào**, phải xin riêng bằng `MAV_CMD_SET_MESSAGE_INTERVAL` (đo
   thật: 0 gói trong 8 s trước khi xin, 17 gói sau khi xin).
2. Cảm biến khoảng cách ≤ `RNG_GROUND_CM` (1 m) — thứ duy nhất **không đổi khi
   đẩy ga lên**: 60 cm suốt cả buổi kể cả lúc động cơ quay, trong khi
   `landed_state` lật sang IN_AIR ngay khi ga rời khỏi min. Chỉ tin khi số nằm
   trong dải hợp lệ của chính cảm biến — hỏng mà trả 0 cm thì không được coi là
   sát đất (tlog 04/08 có gói 0 cm thật).

**Công cụ tự động không được chọn nguồn theo số thứ tự dòng.** `ConnectionPanel`
xếp cổng USB tự quét **lên đầu** danh sách, nên `setCurrentRow(0)` trỏ vào FC
thật ngay khi có dây cắm. Đã xảy ra: bài test REPLAY nối thẳng vào máy bay thật.
Dùng `win.panel.select("<ten profile>")`, nó trả `False` nếu không tìm thấy.

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

**Geofence phải hỏi mới có.** FC không tự gửi hàng rào: bán kính và trần độ cao là
tham số (`FENCE_RADIUS`, `FENCE_ALT_MAX`), còn đa giác nằm trong một "nhiệm vụ"
riêng (`mission_type = 1`), tải về như tải waypoint. Tâm vòng tròn là **home của
FC**, không phải vị trí hiện tại — nên app xin luôn `HOME_POSITION` bằng
`MAV_CMD_REQUEST_MESSAGE`. Đa giác cần MAVLink2; pymavlink tự nâng lên v2 ngay khi
nhận gói v2 đầu tiên, nên chỉ khi FC bị ép MAVLink1 (`SERIALn_PROTOCOL=1`) mới
mất phần đa giác — lúc đó dải chữ dưới bản đồ nói thẳng.

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
  i18n.py        # bang chu vi/en + doi ngon ngu ngay tai cho
  param_doc.py   # tham so ArduCopter la gi, hai thu tieng (tooltip tab Trang thai)
  field.py       # trong tai da nguon: best() tra ca gia tri lan nguon
  authority.py   # duong ra drone + nhanh ESCAPE cho nut do
  adapters/
    sik.py       # pymavlink trong QThread, chuan hoa NED -> ENU
    remote.py    # WebSocket client toi companion

laptop/
  app.py         # QMainWindow
  connection.py  # quet cong USB + banner che do
  link_faults.py # mo phong dut duong truyen (chi SIM)
  tabs/          # flight, status, control, messages, settings
  widgets/       # map, compass, attitude, telemetry_bar

tools/
  selfcheck.py     # 32 check, khong can SITL
  hitl.py          # kich ban #7 va #12: can FC that, thao canh quat
  measure_bandwidth.py  # do byte/s that tren cong dang cam
  e2e_ros2.py      # nghiem thu tren stack ROS2 that
  ros2_bridge.py   # chay tren COMPANION: ROS2 <-> WebSocket
  fetch_tiles.py   # tai tile ban do offline
  soak.py          # bai chay lien tuc
```

Khoảng 4 970 dòng Python trong `core/` + `laptop/`, 4 490 nữa trong `tools/`.
(`find core laptop -name '*.py' | xargs wc -l`)
