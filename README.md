# GCS native — giao diện điều khiển drone trên laptop

Ứng dụng PySide6 chạy trên laptop Ubuntu. Nhận telemetry qua **SiK radio** bằng
pymavlink, nhận dữ liệu **ROS2** qua WebSocket từ companion.

Đặc tả envelope: [`docs/protocol.md`](docs/protocol.md) ·
Báo cáo giao diện: [`baocao/BAO_CAO_GIAO_DIEN_chi_tiet.md`](baocao/BAO_CAO_GIAO_DIEN_chi_tiet.md)

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

**Rút cáp USB rồi cắm lại — app tự nối lại** (đã thử trên FC thật 19/09). Đang có dữ liệu mà cổng biến mất
thì app **giữ nguyên profile**, banner đỏ ghi *"mất cổng /dev/ttyACM0 — cắm lại là
tự kết nối"*, và quét cổng mỗi giây. Nhận lại thiết bị theo **VID:PID:số serial**
chứ không theo tên cổng — cắm lại ra `ttyACM1` vẫn nhận, cắm một radio khác vào
thì không nối nhầm. Nối lại giữ nguyên baud/sysid/`remote`. Bấm **Ngắt** là thôi
chờ. Chỉ áp cho cổng serial: tcp/udp đã có `autoreconnect` của pymavlink, REPLAY
không có gì để cắm lại, và cổng hỏng ngay từ lần mở đầu vẫn hiện hộp lỗi như cũ.

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

**Video khi mô phỏng vẫn lấy từ Pi.** Địa chỉ video bình thường suy từ `remote`
(`ws://<máy>:8765` → `http://<máy>:8080/stream`), nhưng với SITL nửa ROS2 chạy
ngay trên laptop (`127.0.0.1`) còn camera nằm trên Pi — nên profile SITL có key
`video` riêng:

```yaml
video: "http://hoaibac-desktop.local:8080/stream"
```

Có `video` thì dùng nó, không có thì suy từ `remote` như cũ. Video chạy độc lập
với nửa ROS2 (`laptop/widgets/video.py: video_url`).

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

## Bảy tab

| Tab | Nội dung |
|---|---|
| **Bay** | **Màn cảm ứng QML kiểu DJI** (`laptop/touch/`), mở sẵn khi bật app. Bản đồ vệ tinh offline + la bàn, chân trời nhân tạo, thanh telemetry đè lên (có ô **CÒN** — thời gian bay còn lại), dòng **SẴN SÀNG ARM** + cảnh báo đứng yên (failsafe, pin, **VỀ NHÀ NGAY**), dòng lỗi nổi giữa-trên, cần ảo, waypoint bằng **giữ 2 s**. Ô camera PiP hiện khi có video; chạm vào nó là camera phóng cả tab. **Mọi lệnh phải trượt để xác nhận** — kể cả RTL/LAND; cắt động cơ cũng chỉ trượt, hậu quả (rơi tự do) ghi ngay trên thanh trượt |
| **Trạng thái** | ~350 field: mọi thứ FC gửi lên, cộng `SENSOR.*` giải mã và `PARAM.*`. Hai cột: `Field` và `Giá trị`. Field ngừng cập nhật quá `STALE` giây thì **giá trị xám đi** — đứng hình mà vẫn đen là nói dối |
| **Điều khiển** | ARM/mode/TAKEOFF · **nút đỏ** · trạng thái node ROS2 (chỉ đọc) · cùng dòng SẴN SÀNG ARM / CÒN / cảnh báo như màn Bay |
| **Thông báo** | STATUSTEXT của FC + kết quả mọi lệnh (`[APP]`). Chạm một dòng lỗi trên màn Bay là nhảy tới đúng dòng đó ở đây |
| **Camera** | Luồng MJPEG từ companion (cùng nguồn với ô PiP trên tab Bay) |
| **Phân tích** | Đọc `.tlog`/`.bin` từ đĩa hoặc kéo log thẳng từ thẻ SD của FC qua telemetry. Tối đa 4 đồ thị, quỹ đạo 3D, chế độ trực tiếp giữ 60 s gần nhất từ bus |
| **Cài đặt** | Ngôn ngữ giao diện · bật/tắt đọc cảnh báo thành tiếng |

### Ký hiệu drone trên bản đồ

Tam giác nhọn, mũi là đầu drone — cùng kiểu QGroundControl. Nó xoay theo
`attitude.heading` (không có thì lùi về `position.heading`), cùng nguồn với kim
la bàn, nên hai thứ không bao giờ chỉ hai hướng khác nhau.

**Chưa biết hướng thì vẽ lại hình tròn**, không vẽ tam giác chĩa lên bắc. Một
cái mũi nhọn là lời khẳng định "nó đang quay về hướng này"; chưa có heading mà
vẫn vẽ mũi là nói dối, và là kiểu nói dối không ai kiểm được bằng mắt. Hình tròn
nói đúng cái mình biết: ở đây, không biết hướng.

### Đóng app giữa lúc drone đang ARM — phải bấm hai lần

Cửa sổ đóng lúc cánh quạt đang quay là mất đường cứu sinh: hết nút đỏ, hết HUD.
Lần bấm đóng đầu tiên bị **từ chối**, banner chuyển đỏ và cho 3 giây để bấm lại.

**Không** dùng hộp thoại xác nhận. Trong lúc một `QMessageBox` modal đang mở,
`activeModalWidget()` khác `None` nên cửa sổ chính không nhận input — ba nút đỏ
vẫn báo `isEnabled() == True` nhưng **bấm không ăn**. Một câu hỏi "bạn có chắc
không" đặt đúng lúc drone trên trời mà làm chết nút đỏ thì tệ hơn chính cái nó
định ngăn. Cùng một khuôn với xác nhận TAKEOFF ở chế độ REAL.

Chỉ chặn khi `armed` **đúng** là `True`. Không biết thì không chặn: bắt bấm hai
lần mỗi lần telemetry chập chờn là đẩy người dùng vào thói quen bấm hai lần cho
xong, và thói quen đó làm cái chốt này thành vô dụng.

### Thanh telemetry — ba ô tự đổi màu

`ARM · CAO · TỐC · PIN · VỆ TINH · MODE · GIỜ BAY`. Ô **ARM** đứng đầu vì đó là thứ phải
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

**VỆ TINH gộp cả ba điều kiện của mục D.4** — `fix ≥ 3D`, `vệ tinh ≥ 8`,
`HDOP < 2` — vào một ô. Trước đây phải sang tab Trạng thái, lọc `GPS`, đọc ba
hàng, đúng lúc sắp cất cánh. Ba cái đều cần, không cái nào thay được cái nào:
`fix_type=3` với 5 vệ tinh là fix mỏng manh, còn HDOP cao là vệ tinh đông nhưng
xếp thành cụm nên vị trí nhoè ra. Đo thật trên bàn: `fix_type=1, sats=0` — đếm
vệ tinh một mình thì ô đó hiện số `0` trắng tinh như mọi số khác.

Rê chuột lên ô để biết **điều kiện nào trượt**, không chỉ biết là nó vàng.

### Ô CÒN — thời gian bay còn lại, theo dòng động cơ đang ăn

Ô **CÒN** cạnh ô `T` ở thanh dưới màn Bay, chỉ hiện khi đang ARM, có số **ngay
từ lúc ARM**:

```
CÒN = (BATT_CAPACITY − mAh đã xài − mốc failsafe) ÷ dòng điện
```

- `BATT_CAPACITY`, `BATT_LOW_MAH`, `BATT_CRT_MAH` app tự hỏi FC lúc kết nối.
  Mốc failsafe = `BATT_LOW_MAH`, không có thì `BATT_CRT_MAH`, cả hai 0 thì 20%
  dung lượng (mục F của quy trình).
- mAh đã xài lấy `BATTERY_STATUS.current_consumed` của FC (đo trên log thật: khớp
  tự tích phân dòng điện, lệch 1,2 mAh sau 716 s). Dòng điện làm mượt ~5 s.
- ≤ 3 phút vàng, ≤ 1 phút đỏ. Dòng < 0,1 A (nhiễu) thì `--`.

**Ba điều phép tính không tự đảm bảo:** FC coi pin **đầy lúc cắm** (cắm pin dùng
dở là ô CÒN báo dư — xem cảnh báo "pin không đầy" dưới đây), cảm biến dòng phải
hiệu chỉnh đúng (`BATT_AMP_PERVLT`), và failsafe **theo điện áp** có thể kích
trước mốc mAh.

**Bẫy:** tham số FC chỉ về **một lần**. Đọc qua `REGISTRY` là chết sau
`STALE = 2 s` và ô CÒN hiện `--` suốt chuyến — nên `Backend` giữ tham số riêng
(`_params`, topic `param`).

### SẴN SÀNG ARM và cảnh báo đứng yên

Dòng **SẴN SÀNG ARM** (xanh) ở giữa-trên màn Bay theo bit `PREARM_CHECK` của
`SYS_STATUS` — cùng nguồn Mission Planner/QGC dùng. Chưa sẵn sàng thì vàng
**CHƯA SẴN SÀNG ARM: <lý do>**, lý do lấy từ các dòng `PreArm:` FC nhắc mỗi
~31 s (giữ 40 s cho khỏi nháy). Đã ARM hoặc mất số liệu thì ẩn. Dòng lỗi nổi lên
**đè lên** nó.

Ngay dưới là **cảnh báo đứng yên** — không tự tắt, còn đúng thì còn hiện
(`laptop/safety.py`):

| Lúc | Cảnh báo | Điều kiện |
|---|---|---|
| chưa ARM | Failsafe pin TẮT | `BATT_FS_LOW_ACT = BATT_FS_CRT_ACT = 0` |
| chưa ARM | Failsafe mất RC / mất GCS TẮT | `FS_THR_ENABLE = 0` / `FS_GCS_ENABLE = 0` |
| chưa ARM | `BATT_LOW_VOLT` sai số cell | ngoài 3,3–3,9 V/cell (số cell = ⌈V / 4,25⌉) |
| chưa ARM | Pin có thể KHÔNG đầy lúc cắm | % theo điện áp nghỉ (đường LiPo) thấp hơn % FC ≥ 25 điểm, dòng < 1 A |
| đang bay | **VỀ NHÀ NGAY** (đỏ) / Sắp phải về (vàng) | CÒN ≤ thời gian RTL + 30 s / + 90 s |

Thời gian RTL tính theo đúng chuỗi bước ArduCopter: leo tới `RTL_ALT`, bay ngang
về (`RTL_SPEED`, 0 = `WP_SPD`), lơ lửng `RTL_LOIT_TIME`, hạ nhanh tới
`LAND_ALT_LOW`, hạ chậm `LAND_SPEED`. App hỏi **cả tên cũ lẫn tên SI** của
4.7-dev (`RTL_ALT` cm ↔ `RTL_ALT_M` m…). Thiếu tham số nào thì im lặng — không
nói "tắt" thay cho "chưa biết".

Chạy với tham số MicoAir743 lấy ngày 07/09 (và pin 19/09) thì **cả bốn** cảnh
báo chưa-ARM đều bật: failsafe pin và GCS tắt, `BATT_LOW_VOLT = 10,8 V` là
2,70 V/cell trên pin 4S, và pin 3,82 V/cell ≈ 45% trong khi FC báo 99%. Cũng với
số đó, `WP_SPD = 1 m/s` nên **RTL từ 500 m mất ~8 phút 51 giây**. Từ 19/09 FC đã
bật đủ failsafe — app đọc tham số **mỗi lần kết nối**, nên cảnh báo tự tắt theo;
bảng trên là để biết khi nào nó sẽ bật lại.

### Đọc cảnh báo thành tiếng

`laptop/voice.py` (Qt TextToSpeech — speech-dispatcher/espeak-ng trên Linux,
SAPI trên Windows). Đọc **khi trạng thái đổi**, không đọc lại mỗi nhịp: "Sẵn
sàng arm", "Mất tín hiệu", "Sắp phải về", "Pin yếu/rất yếu, còn N phần trăm";
riêng **"Về nhà ngay" nhắc lại mỗi 30 s** còn đúng. Ngôn ngữ theo tab Cài đặt
(`vi_VN` / `en_US`, đổi giữa chuyến là câu sau đổi theo). Giọng nữ, cao: biến thể
`+Annie` (không có thì `female3`, `female2`), pitch 0,5, rate 0,1 — ba hằng số
đầu file. Không có engine TTS thì im lặng, app vẫn chạy. Tắt ở tab Cài đặt.

**ARM / DISARM / đổi mode cũng được đọc**: "Đã arm", "Đã disarm", "Chế độ LOITER"
— chỉ khi giá trị **đổi** từ một giá trị đã biết. Vừa kết nối (hay telemetry
chập chờn, giá trị chưa biết) thì không đọc, nên nối vào drone đang nằm đất
không nghe "Đã disarm" như thể có ai vừa tắt máy. Tên mode giữ nguyên chữ của FC.

**Dòng lỗi đỏ cũng được đọc**: `"Lỗi: <câu của FC>"`, mỗi dòng một lần lúc nó
hiện (hết hạn 10 s rồi quay lại thì đọc lại), xếp hàng sau câu đang đọc chứ không
cắt ngang, tối đa 3 câu mỗi nhịp. Bỏ `PreArm:` — dòng SẴN SÀNG ARM đã nói, và FC
nhắc PreArm mỗi ~31 s. Câu của FC là tiếng Anh nên giọng Việt đọc theo phiên âm Việt.

### Chạm đúp — về drone, phóng tới z20

Chạm đúp bản đồ: tâm về drone, bật bám theo, và **zoom 20** (`FOLLOW_ZOOM`) dù
đang ở z5. Ngón tay rung vài px không làm hỏng — bản đồ chỉ bắt đầu kéo khi đi
quá `startDragDistance` (trước đây rung 2 px ở lần chạm thứ hai là tắt bám, bản
đồ đứng im). Chưa có vị trí GPS thì giữ nguyên zoom và nói ra.

### Dấu X home có thể là home GIẢ — dải chữ nói rõ

Khi chưa nhận `HOME_POSITION` từ FC, tab Bay lấy **điểm định vị đầu tiên** làm
home tạm (`laptop/touch/backend.py:167`). Nó vẽ ra dấu X **y hệt** home thật, nên người bay
nhìn thấy X và tin là home đã đặt — trong khi RTL sẽ bay về home thật của FC, ở
chỗ khác. Một dấu X sai chỗ còn tệ hơn không có dấu X nào, và đó đúng là thứ mục
D.6 bắt kiểm (*"Home đã đặt, **đúng chỗ đứng**"*).

Dải chữ giờ nói thẳng: `⚠ HOME TẠM (điểm định vị đầu) — chưa nhận HOME_POSITION
từ FC, RTL KHÔNG về đây`. Có `HOME_POSITION` rồi thì đổi thành `về nhà 56 m`.

### Rào: FC quyết định, không phải app

`FENCE_TYPE` của FC là **nguồn sự thật duy nhất** cho việc rào nào đang chặn —
không phải sự có mặt của tham số. `FENCE_RADIUS` vẫn giữ nguyên giá trị cũ sau
khi tắt rào tròn, danh sách đỉnh đa giác vẫn còn trong nhiệm vụ sau khi tắt rào
đa giác. Vẽ hay đo một rào FC không chặn là đẩy người bay tránh một bức tường
không tồn tại, và làm thế một lần thì lần sau họ không tin con số đó nữa.

| Bit | Rào | Vẽ trên map | Số mét |
|---|---|---|---|
| 1 | Trần độ cao `FENCE_ALT_MAX` | (không vẽ được) | `còn 80m tới trần` |
| 2 | Vòng tròn `FENCE_RADIUS` quanh home | ✓ | `còn 94m tới rào` |
| 4 | Mọi hình tải từ nhiệm vụ FENCE — đa giác **và** vòng tròn rời | ✓ | `còn 144m tới rào` |

`FENCE_ENABLE = 1` mà `FENCE_TYPE = 0` thì FC **không chặn gì cả** — dải chữ nói
thẳng `⚠ rào BẬT nhưng FENCE_TYPE=0`, chứ không hiện "rào BẬT" như trước.

`FENCE_ENABLE = 0` (FC không bật rào) thì bản đồ **không vẽ rào nào** — trước
đây vẽ xám đứt nét, vẫn bị đọc nhầm thành "có rào". Dải chữ cũng không nhắc tới rào.

**Dải chữ dưới bản đồ chỉ còn cảnh báo** (rào, HOME TẠM, đường bay, CHƯA NẠP);
zoom, toạ độ tâm, "nháy đôi để bám lại" và tên nguồn ảnh đã bỏ. Không có gì
để nói thì dải chữ ẩn hẳn.

Chỉ hiện **một** số: cái **gần nhất**. Liệt kê cả ba thì dải chữ dài ra mà người
bay vẫn phải tự so xem cái nào sắp chạm — đúng cái việc đang muốn làm hộ. Vùng
**cấm vào** nói ngược lại: `cách vùng cấm 22m`.

Số mét tới vòng tròn chỉ hiện khi home là home **thật** (xem mục trên): tâm vòng
rào của ArduCopter là home của FC, đo từ một home đoán ra thì con số đó là bịa.

### Lỗi hiện ngay trên màn bay — kiểu DJI

Trước đây PreArm, failsafe, crash chỉ vào tab Thông báo: phải rời bản đồ mới
đọc được. Giờ chúng nổi thành dòng màu ở giữa-trên tab Bay
(`laptop/widgets/alerts.py`):

| Mức `severity` | Màu | Tự tắt sau lần cuối thấy |
|---|---|---|
| 0–3 (EMERGENCY … ERROR) | đỏ | 10 s (`TTL_ERR`) |
| 4 (WARNING) | vàng | 5 s (`TTL_WARN`) |
| 5–7 | không lên màn bay, chỉ vào tab Thông báo | — |

- **Câu trùng gộp thành một dòng `×n`.** Log thật 84 phút chỉ có đúng 2 câu
  PreArm, mỗi câu 164 lần, cách nhau ~30,7 s. Vì thời gian tắt ngắn hơn nhịp lặp,
  dòng PreArm hiện 10 s rồi tắt ~20 s tới lần FC nhắc lại — đó là lựa chọn, không
  phải lỗi. Lịch sử đầy đủ vẫn ở tab Thông báo.
- **Tối đa 3 dòng, nặng nhất ở trên.** Ba dòng vàng mới đến không đẩy được một
  dòng đỏ ra khỏi màn hình. Thừa thì dòng cuối ghi `(+k)` — không cắt im lặng.
- Nguồn: STATUSTEXT của FC, envelope `text` của companion, và kết quả lệnh của
  chính app (từ chối = đỏ, gửi mà link câm = vàng). Ngắt kết nối là xoá sạch.
- **Chạm vào dòng lỗi** là mở tab Thông báo, chọn sẵn đúng dòng đó (bỏ đuôi
  `×n`/`(+k)` khi so), để đọc cả lịch sử quanh nó.

**Companion muốn đẩy thông báo lên đây** (phát hiện lửa, người, vật cản…) thì
gửi qua WebSocket 8765 đúng khuôn này — GUI không phải sửa gì:

```json
{"topic": "text", "data": {"severity": 4, "text": "Phát hiện lửa #3"}}
```

Thiếu `severity` là bị coi như INFO: chỉ vào tab Thông báo, **không** lên màn
bay. Gửi theo sự kiện (track mới), không theo từng khung hình; giữ nguyên câu chữ
cho mỗi track thì mới gộp `×n` được. Đường này đi trên WiFi của Pi — mất WiFi là
thông báo không tới mà không có gì báo là nó không tới. STATUSTEXT companion gửi
**qua FC** thì hiện **không** tới GUI: `from_autopilot()` bỏ mọi gói không phải
component 1.

### Bấm ô camera — camera phóng cả tab Bay, bản đồ thu vào góc

Trước đây muốn xem camera to thì phải sang tab Camera, tức là rời bản đồ. Giờ
chạm vào ô PiP (tự hiện khi có video) là **đổi chỗ kiểu DJI**:
camera chiếm cả tab, bản đồ thu vào đúng góc ô PiP cũ — vẫn thấy drone ở đâu,
rào ở đâu. La bàn, chân trời, thanh telemetry và dòng lỗi vẫn nằm trên cùng.

- **Chạm bản đồ nhỏ** để đổi lại. Chạm giữa ảnh camera lớn thì **không** đổi —
  chạm nhầm giữa lúc đang xem không được đá mình về bản đồ.
- Bản đồ nhỏ **không nhận cử chỉ**: kéo/chụm trên ô 256 px chỉ làm lệch khung
  nhìn. Đặt waypoint và bay-tới-điểm có lại khi bản đồ về lớn.
- Nhịp vẽ đổi theo chỗ: video 30 fps khi phóng cả tab, 15 fps khi nằm ở ô PiP;
  bản đồ 5 fps ở cả hai chỗ — nó chỉ đổi khi drone nhích, không cần hơn.
- Ngắt kết nối thì tự trả bản đồ về lớn: không có link thì video đã chết.

### Tab Thông báo mang số cảnh báo chưa đọc

Mục D.7 bắt đọc *"không có STATUSTEXT đỏ tồn đọng"* — nhưng phải chuyển tab mới
thấy. Tên tab giờ thành `Thông báo  (2)` khi có cảnh báo từ mức `WARNING` trở
lên đến trong lúc tab đó không mở. Mở tab ra là xoá đếm. Số này sống qua cả lần
đổi ngôn ngữ (`Messages  (2)`).

**GIỜ BAY** đếm từ lúc `armed` lật lên `True` — mốc lấy ở đó chứ không phải lúc
bấm nút, vì lệnh ARM có thể bị FC từ chối. Cùng với phần trăm pin, đây là vế thứ
hai của câu hỏi "còn bay được bao lâu", và là vế **không ai khác cung cấp**: FC
không gửi thời gian bay qua MAVLink.

Dải chữ dưới bản đồ có thêm **`về nhà 142 m`** khi đã biết cả home lẫn vị trí
drone. Nó đi liền với dấu X trên bản đồ chứ không tách ra ô riêng: thấy số mà
không thấy dấu X thì không biết nó tính từ đâu.

### `SENSOR.*` — adapter phát mã máy, giao diện mới dịch

`decode_sensors()` bóc ba bitmask 32 bit của `SYS_STATUS` thành 31 hàng
`SENSOR.3d_gyro`, `SENSOR.gps`, `SENSOR.logging`… Giá trị nó phát ra là **mã
máy** — `ok`, `fail`, `ok_off`, `fail_off` — chứ không phải chữ cho người đọc.

Adapter chạy trong `QThread` và cố ý không biết ngôn ngữ nào đang chọn. Để nó
sinh chữ thì bản tiếng Anh có `TOT`/`HONG` lọt vào giữa, và ai muốn dịch lại sẽ
phải **so chuỗi** — đúng kiểu lỗi đã gặp khi `app.py` đoán mức độ nghiêm trọng
bằng cách bắt chữ `"TU CHOI"` trong dòng log. Tab Trạng thái dịch lúc vẽ, kể cả
những hàng đã nằm sẵn trong bảng khi mất kết nối.

### Tham số PID — rê chuột là biết nó là gì

Nút **Đọc 63 tham số PID** ở tab **Trạng thái** hỏi FC từng nhóm rồi đổ vào các
hàng `PARAM.*`. **Rê chuột lên một hàng** là ra một dòng giải thích tham số đó
làm gì — không phải mở tài liệu ArduPilot ở tab khác.

Chữ nằm ở [`core/param_doc.py`](core/param_doc.py), theo cả hai ngôn ngữ. Họ
`ATC_RAT_{RLL,PIT,YAW}_{P,I,D,IMAX,FLTT,FLTE,FLTD,SMAX}` và `PSC_*` **ghép** từ
hai bảng mảnh (trục nào × hệ số nào) chứ không viết tay từng cái: 24 dòng na ná
nhau là 24 cơ hội gõ nhầm, và thêm một hệ số mới thì không phải thêm dòng nào.
Cái không theo khuôn (`MOT_*`, `WPNAV_*`, `ANGLE_MAX`…) ghi thẳng ở `EXPLICIT`.

**Cột Giải thích** (thêm 19/09 — rê chuột mới thấy là không ai biết mà rê): mọi
hàng `PARAM.*` có một dòng mô tả ngay trong bảng, tooltip thêm cả các giá trị của
tham số kiểu liệt kê (`FS_THR_ENABLE` → `1: Enabled always RTL, …`). Tham số có
dòng tiếng Việt viết tay thì dùng dòng đó; còn lại lấy mô tả **tiếng Anh** của
ArduPilot kèm đơn vị, từ `core/param_meta.json` (5 771 tham số). Đo trên log `.bin`
thật của FC (ArduCopter V4.7.0): **1 036/1 037** tham số có giải thích — thiếu
`GND_EFFECT_COMP`. File dựng từ `apm.pdef.xml` mà Mission Planner tải về (bản
master, đúng tên SI của 4.7-dev; mã nguồn `~/ardupilot` 4.6.3 thì ra tên cũ):
`python3 tools/build_param_meta.py`. Field thường (`ATTITUDE.roll`…) **không** bịa
mô tả — cột để trống.

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

**Giữ 2 s** trên bản đồ mở bảng: **đặt waypoint** (tối đa 50), **bay tới đây**,
**nạp lên FC**, hoặc **xoá đường bay trên FC**. Trong lúc giữ có vòng tròn chạy
quanh ngón tay; thả sớm hoặc kéo bản đồ là huỷ, chạm một cái không làm gì — chạm
nhầm không được thành chọn điểm. Độ cao có sáu mức bấm
nhanh (10/15/20/30/50/80 m) **và một ô nhập số** cho con số khác — ô nhập có nút
± nên ngoài bãi không phải gọi bàn phím ảo lên che màn hình. Giới hạn 1–120 m
(`WP_ALT_MIN`/`WP_ALT_MAX` trong `laptop/commands.py`), kẹp cả ở ô nhập lẫn ở
backend.
Kéo bản đồ thì không mở bảng — chốt theo `Qt.styleHints.startDragDistance`. Nạp xong app đọc ngược lại từ FC
rồi mới vẽ — cái hiện trên bản đồ là cái FC đang thật sự giữ, không phải cái vừa
gửi đi. Đường tím liền là đường bay trên FC (số theo `seq` của FC, mục 0 là home
do ArduPilot tự giữ); đường tím nhạt đứt nét là đường **đang đặt, chưa nạp**.

Đang bay AUTO mà nạp đè thì phải bấm hai lần — FC nhảy sang WP1 của đường mới
ngay khi nhận.

**Cất cánh** (nút ▲ trên màn Bay): chip 3/5/10/20/30 m **và ô nhập số** 1–120 m,
kẹp cả ở QML lẫn `Backend.act`. FC phải ở GUIDED **và đã ARM** — chưa ARM thì
app nói thẳng *"drone CHƯA ARM"* và không gửi. Bộ kiểm "độ cao không đổi sau 6 s"
chỉ chạy khi FC **chấp nhận** đúng lần takeoff đó (trước đây FC từ chối vẫn bị
báo "FC đã nhận…").

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
python3 tools/selfcheck.py      # 45 check, khong can SITL  (~90 giay)
python3 tools/check_halves.py   # hai nua hong doc lap, nguon gia
python3 tools/e2e_sitl.py       # 58 bai mot chuyen bay tren ArduCopter SITL that
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
TAKEOFF, tải tile. Nó đo **mã nguồn** — adapter giả, bus giả, không có FC nào ở
đầu kia.

### `e2e_sitl.py` — cắm thẳng vào SITL, một chuyến bay

Cái `selfcheck.py` không bao giờ bắt được là loại "mã nguồn đúng mà drone không
làm": độ cao bị điền mặc định, lệnh gửi đúng nhưng FC từ chối, mode chưa kịp đổi
đã bắn lệnh kế tiếp. Ba lỗi đắt nhất của dự án đều thuộc loại đó. `e2e_sitl.py`
đi **đúng đường ngón tay đi** — `Backend.act()/addWp()/stick()` → `Commands` →
`authority` → `SikAdapter` — không một bước nào gọi tắt xuống pymavlink. Kết
nối đi qua **`MainWindow.connect_to()`** — đúng đường app thật dùng. (Trước 19/09
nó mở kết nối bằng một bản sao riêng trong `Backend`, nên không phủ được thứ chỉ
có ở `MainWindow`: tự nối lại USB, video, hỏi tham số. Bản sao đó đã xoá.)

Lần chạy 19/09 trên SITL lạnh: **58/58 PASS / 175 s**, gồm các bài mới — FC trả
17 tham số pin + RTL ở giây 0,2; chạm đúp về z20; takeoff lúc chưa ARM nói "CHƯA
ARM"; SẴN SÀNG ARM sau 13,2 s; ô CÒN 337 s ở 27,4 A khi bay; ước RTL ~34 s.
SITL chỉ mô phỏng dòng khi có tải (ARM đứng yên 0,00 A) nên ô CÒN đo **sau** cất
cánh. SITL `-I1` (cổng 5770–5773) chạy song song được với một SITL đang mở ở
`-I0`: `--conn tcp:127.0.0.1:5772`.

```bash
# 1. SITL tran (khong Gazebo, khong ROS2) — THU MUC TRONG, khong EEPROM cu
~/ardupilot/build/sitl/bin/arducopter -S -I0 --model + --speedup 1 \
    --defaults ~/ardupilot/Tools/autotest/default_params/copter.parm \
    --home 10.8221589,106.6868454,10,0

# 2. SITL chi mo 5762/5763 SAU khi co ai cam vao 5760
mavproxy.py --master tcp:127.0.0.1:5760 --daemon

# 3. Bai test
python3 tools/e2e_sitl.py
```

⚠️ **Luôn khởi động SITL lạnh.** Bốn lượt 52/52 đầu tiên xanh vì SITL đã mở sẵn
từ lâu — chạy lại trên SITL vừa bật ra **5 FAIL**, tất cả đổ từ một chỗ: ARM.
Đo được: **ARM thành công ở giây thứ 24, phải bấm 8 lần** (EKF chưa hội tụ, GPS
chưa fix thì prearm từ chối). Bài test giờ chờ `fix_type ≥ 3 && sats ≥ 8` rồi bấm
lại mỗi 3 s trong 60 s. Số đo mới nhất (17/09, SITL lạnh): **53/53 PASS / 169 s**.

⚠️ **Đừng dùng `--speedup`** — bài này đo cả nhịp giao diện (timer 200 ms,
`ACK_TIMEOUT` 3 s), tăng tốc là đo sai chính cái cần đo.

⚠️ **Đừng nối `| tail -N` vào lệnh chạy bài test.** Nó nuốt cả tiến trình lẫn
**mã thoát**: script trả 1 mà `tail` trả 0, nhìn y hệt PASS trong khi có 5 FAIL.

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

| Đang ở dưới đất? | Bấm một phát | Bấm lại trong 3 s (màn cảm ứng: trượt hết) |
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

**Thả một QThread còn chạy là Qt giết cả tiến trình.** `stop()` của adapter
chờ 3 s rồi bỏ; thread chưa thoát kịp thì chính nó giữ tham chiếu cuối, `run()`
trả về là nó tự huỷ trong thread của mình → `QThread: Destroyed while thread is
still running`, exit 134. Đo 15/09: mở REPLAY một `.tlog` 168 MB mất **4,26 s**
riêng khâu mở file — ngắt kết nối trong vài giây đầu là app sập (selfcheck sập
theo, vì `check_replay_locks` phát `.tlog` mới nhất trong `logs/`). Giờ cả hai
adapter đi qua `join()` ở `core/adapters/__init__.py`: quá hạn thì giữ thread
sống tới `finished` rồi `deleteLater()` ở main thread. Đổi lại GUI vẫn đứng 3 s
lúc ngắt giữa khâu mở file lớn.

**Treo tại chỗ thì dùng BRAKE hoặc GUIDED**, đừng ép cần điều khiển về giữa bằng
RC override: ArduPilot sẽ từ chối arm với `"Throttle (RC3) is not neutral"`.

---

## Log

| File | Nội dung |
|---|---|
| `logs/*.tlog` | MAVLink thô mọi chuyến, đọc được bằng Mission Planner |
| `logs/commands.log` | Mọi lần bấm nút và kết quả — nơi trả lời "sao nó không arm được" |
| `logs/gui.log` | stdout của app |
| `logs/video.log` | Nhịp khung video **tới GUI** mỗi 5 s + mốc start/connected/lost/error/stop |

Số fps trên khung video chỉ nói *lúc này*; video giật lúc 13:40 thì phải có dòng
log lúc 13:40. `tools/video_timeline.sh` ghép `logs/video.log` với journal
`mjpeg-stream.service` của Pi (qua ssh, IP lấy từ `connections.yaml`) lên một
trục thời gian: Pi nén cao mà GUI nhận thấp là mất trên WiFi, cả hai cùng tụt là
camera/Pi.

```bash
tools/video_timeline.sh              # tu luc GUI bat dau ghi log
tools/video_timeline.sh 13:00        # tu moc khac — cu phap `date -d`
```

---

## Cấu trúc

```
core/            # DUNG CHUNG voi ban web
  bus.py         # envelope {src, topic, data, ts}
  logdata.py     # doc .tlog tu dia cho tab Phan tich
  i18n.py        # bang chu vi/en + doi ngon ngu ngay tai cho
  param_doc.py   # tham so ArduCopter la gi, hai thu tieng (tooltip tab Trang thai)
  field.py       # trong tai da nguon: best() tra ca gia tri lan nguon
  authority.py   # duong ra drone + nhanh ESCAPE cho nut do
  adapters/
    __init__.py  # join(): dung QThread ma khong bao gio tha no khi con chay
    sik.py       # pymavlink trong QThread, chuan hoa NED -> ENU
    remote.py    # WebSocket client toi companion

laptop/
  app.py         # QMainWindow
  connection.py  # quet cong USB + banner che do
  link_faults.py # mo phong dut duong truyen (chi SIM)
  theme.py       # bang mau + QSS dung chung, widget khong tu che ma hex
  commands.py    # logic lenh (ARM/TAKEOFF/RTL/goto/waypoint) — MOT instance dung
                 # chung cho man bay cam ung va tab Dieu khien
  safety.py      # thoi gian RTL, kiem failsafe, % pin theo dien ap (khong Qt)
  voice.py       # doc canh bao thanh tieng (Qt TTS)
  touch/         # man bay cam ung kieu DJI: backend.py (state cho QML) + qml/
  tabs/          # status, control, messages, analysis, settings
  widgets/       # map, compass, attitude, video, trajectory3d, alerts
                 # telemetry_bar.py gio CHI con nguong pin/GPS, khong con widget

tools/
  selfcheck.py     # 45 check, khong can SITL
  e2e_sitl.py      # 58 bai mot chuyen bay tren ArduCopter SITL that
  compare_gcs.py   # so tung con so voi MAVProxy tren cung mot luong goi
  check_halves.py  # hai nua hong doc lap, nguon gia
  hitl.py          # kich ban #7 va #12: can FC that, thao canh quat
  measure_bandwidth.py  # do byte/s that tren cong dang cam
  e2e_ros2.py      # nghiem thu tren stack ROS2 that
  ros2_bridge.py   # chay tren COMPANION: ROS2 <-> WebSocket
  fetch_tiles.py   # tai tile ban do offline
  mjpeg_server.py  # chay tren COMPANION: /dev/video* hoac topic anh ROS2 -> MJPEG
  fire_tracker.py  # bam vet lua/khoi YOLO ONNX, ve len khung MJPEG
  video_timeline.sh  # ghep nhip video Pi + GUI len mot truc thoi gian
  soak.py          # bai chay lien tuc
```

Khoảng 9 010 dòng Python trong `core/` + `laptop/`, 1 030 dòng QML, và 7 020 nữa
trong `tools/`. (`find core laptop -name '*.py' | xargs wc -l`)
