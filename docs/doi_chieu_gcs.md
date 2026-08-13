# Đối chiếu số liệu với GCS khác

Nghiệm thu phase N2:

> Chạy SITL, so từng con số với Mission Planner — sai lệch chỉ do làm tròn

```bash
# cửa sổ 1 — SITL
cd ~/ardupilot/ArduCopter && ~/ardupilot/Tools/autotest/sim_vehicle.py \
    -v ArduCopter -f quad --no-mavproxy --no-rebuild -N
# cửa sổ 2
cd ~/GUI_NATIVE && python3 tools/compare_gcs.py --takeoff
```

`--selftest` chạy riêng phần tự kiểm của bảng số, không cần SITL.

> ⚠️ **`--takeoff` thật sự nâng drone lên 10 m.** Không có cờ đó thì công cụ chỉ
> đo trạng thái đang có, không ARM, không chạm vào drone. Xem mục 8 trước khi cắm
> FC thật.

---

## 1. GCS đối chiếu là MAVProxy

Mission Planner là ứng dụng C#/Windows (xem mục 7 — đã thử, chưa đọc được số).
GCS đối chiếu thực tế là **MAVProxy, GCS tham chiếu của chính ArduPilot**. Điều
quan trọng không phải nó tên gì, mà là **nó scale raw MAVLink bằng code riêng**,
không dùng chung một dòng nào với `core/adapters/sik.py`.

Hai chỗ trong MAVProxy làm việc scale đó, và cả hai đều vẽ ra cửa sổ wx. Cách cạo
số ra thành text:

| Lấy gì | Ở đâu | Vá chỗ nào |
|---|---|---|
| Alt, Hdg, GPSSpeed, Battery, GPS, Mode, Roll, Pitch | `mavproxy_console.py` | `textconsole.SimpleConsole.set_status()` in ra stdout, rồi ép `wxconsole.MessageConsole = SimpleConsole` |
| **lat/lon** | `mavproxy_map/__init__.py` (`m.lat*1.0e-7` rồi `map.set_position()`) | thay `mp_slipmap.MPSlipMap` bằng lớp giữ chỗ chỉ biết in |

Console **không có ô nào cho toạ độ** — đó là lý do lat/lon phải đi vòng qua
module `map`.

> Lớp giữ chỗ bắt buộc phải có `is_alive()` trả `True`. Module `map` mỗi vòng
> idle đều hỏi cửa sổ còn sống không; trả `None` là nó tự gỡ mình ra
> (`Unloaded module map`) mà không báo một tiếng.

## 2. Đường ống

Điểm mấu chốt: cả hai GCS đọc **cùng một luồng gói tin**, không phải hai phiên
riêng. Hai phiên riêng thì số lệch nhau là bình thường, chẳng chứng minh gì.

```
SITL / FC thật ──> MAVProxy ─┬── udp:14561 → GUI (QT_QPA_PLATFORM=offscreen)
                             ├── udp:14562 → tai nghe raw
                             ├── udp:14563 → lái cất/hạ cánh
                             └── udp:14550 → chừa cho GCS thứ ba (MP, QGC)
```

Đo ở **hai trạng thái tĩnh** — trên đất, và treo 10 m — để lệch thời gian giữa
hai bên không hoá thành lệch số liệu.

> Cổng của mình để ở dải **1456x** chứ không phải 1455x: Mission Planner tự mở
> nghe cả 14550 lẫn 14551 ngay khi khởi động, không đợi ai bảo.

## 3. Ba mức đối chiếu

Console MAVProxy làm tròn về số nguyên (`"%um"`), nên một mức là không đủ:

| Mức | So với | Bắt được loại lỗi nào |
|---|---|---|
| 1 | MAVProxy (console + map) | **Sai đơn vị.** Loại này luôn lệch ≥100 lần (mm đọc thành m, cdeg thành deg) — số nguyên thừa sức bắt. Riêng lat/lon từ module `map` là đủ chữ số. |
| 2 | Raw MAVLink | **Sai làm tròn.** Hệ số quy đổi không gõ tay mà lấy từ `fieldunits_by_name`, tức từ chính XML MAVLink chính thức. |
| 3 | Điểm chuẩn ngoài | **Cả hai GCS cùng đọc sai giống nhau.** Trên SITL là chỗ đặt drone (`CMAC` trong `locations.txt`) — nhân chứng duy nhất không đi qua MAVLink. |

## 4. Số đo — SITL ArduCopter, 07/08/2026

### Trên đất

| Đại lượng | GUI | MAVProxy | raw MAVLink | lệch GUI–MP | lệch GUI–raw |
|---|---|---|---|---|---|
| độ cao tương đối (m) | -0.0 | 0 | -0.020 | 0 | 0.020 |
| tốc độ ngang (m/s) | 0.0 | 0 | 0.0193 | 0 | 0.019 |
| điện áp pin (V) | 12.60 | 12.60 | 12.60 | 0 | 0 |
| số vệ tinh | 10 | 10 | 10 | 0 | 0 |
| hướng mũi (°) | 352.8 | 352 | 352.80 | 0.8 | 0 |
| roll (°) | 0.0 | 0 | -0.010 | 0 | 0.010 |
| pitch (°) | 0.0 | 0 | -0.026 | 0 | 0.026 |
| **vĩ độ (°)** | **-35.3632623** | **-35.3632623** | -35.3632623 | **0** | 7.1e-15 |
| **kinh độ (°)** | **149.165238** | **149.165238** | 149.165238 | **0** | 2.8e-14 |
| chế độ bay | LAND | LAND | — | khớp | — |

Toạ độ lệch **0.70 m** so với chỗ SITL đặt drone (-35.363261, 149.165230).

### Treo 10 m, GUIDED

| Đại lượng | GUI | MAVProxy | raw MAVLink | lệch GUI–MP | lệch GUI–raw |
|---|---|---|---|---|---|
| độ cao tương đối (m) | 10.0 | 10 | 10.000 | 0 | 0 |
| tốc độ ngang (m/s) | 0.0 | 0 | 0.0219 | 0 | 0.022 |
| điện áp pin (V) | 12.60 | 12.60 | 12.60 | 0 | 0 |
| số vệ tinh | 10 | 10 | 10 | 0 | 0 |
| hướng mũi (°) | 352.8 | 352 | 352.81 | 0.8 | 0.01 |
| roll (°) | 0.0 | 0 | -0.020 | 0 | 0.020 |
| pitch (°) | 0.0 | 0 | -0.042 | 0 | 0.042 |
| **vĩ độ (°)** | **-35.3632625** | **-35.3632625** | -35.3632625 | **0** | 0 |
| **kinh độ (°)** | **149.165238** | **149.165238** | 149.165238 | **0** | 0 |
| chế độ bay | GUIDED | GUIDED | — | khớp | — |

**Kết luận: không đại lượng nào lệch quá mức làm tròn của chính ô hiển thị.**
GUI hiện độ cao và tốc độ một chữ số thập phân, điện áp hai chữ số — mọi lệch đo
được đều nhỏ hơn nửa đơn vị cuối cùng đó. Toạ độ khớp **tuyệt đối** với MAVProxy.

## 5. Bảng số này có biết kêu không

Một bảng toàn OK không chứng minh gì nếu nó không bao giờ biết kêu.
`--selftest` bơm bốn kiểu sai thật vào và bắt bảng phải bắt được cả bốn:

| Bơm vào | Phải kêu ở |
|---|---|
| độ cao gấp 1000 lần (đọc mm thành m) | độ cao tương đối |
| điện áp lệch 0.2 V | điện áp pin |
| mode LOITER trong khi FC nói GUIDED | chế độ bay |
| toạ độ lệch 1.1 km | so với điểm chuẩn |

## 6. Cái này **chưa** chứng minh được

1. **Mức 1 chỉ chặt tới ±1 đơn vị** với những ô console vẽ, vì console MAVProxy
   làm tròn về số nguyên. Cái chứng minh "chỉ lệch do làm tròn" là mức 2. *(lat/lon
   không dính giới hạn này — chúng đi qua module `map`, đủ chữ số.)*
2. **Hướng mũi có hai nguồn.** FC gửi cả `ATTITUDE.yaw` lẫn
   `GLOBAL_POSITION_INT.hdg`; hai đầu ra EKF này lệch nhau ~1° là chuyện thật.
   Tab Flight ưu tiên `attitude.heading` rồi mới tụt về `position.heading`, và
   bảng số soi đúng cái nó đang dùng. Đây từng là một lần báo HỎNG giả.
3. **roll/pitch động ngay cả khi treo.** Dung sai 0.5° cho hai dòng đó là sai số
   *lấy mẫu không đồng thời*, không phải sai số của GUI.
4. **Mới đo trên SITL qua UDP.** Chưa đối chiếu trên FC thật qua radio SiK — xem
   mục 8.
5. **Chưa đọc được số của Mission Planner thật** — mục 7.

---

## 7. Mission Planner trên Linux — đã thử tới đâu

**`mono` chạy được MP.** Đã cài `mono-complete` 6.8.0.105, chạy
`mono ~/mp/MissionPlanner/MissionPlanner.exe` (bản 1.3.83). Nó nạp hết plugin, mở
cửa sổ chính, HUD render bằng OpenGL (`HUD 1 hz drawtime … gl True`). Hai lỗi lúc
khởi động — `libdl.so` không tìm thấy, GDAL `TypeInitializationException` — **không
chặn**, MP vẫn chạy tiếp.

**Chặn ở chỗ khác: không có màn hình ảo.** Máy này không có `Xvfb`, nên MP bật lên
là nằm đè trên desktop đang dùng. Nó cướp focus, ăn phím người dùng đang gõ (log
đầy `MainV2_KeyDown`), rồi cửa sổ chính bị đóng. Tiến trình `mono` vẫn sống nhưng
không còn form.

Đổi sang QGroundControl **không gỡ được nút này** — cũng là GUI, cũng cần đúng cái
màn hình đó.

Muốn có cột MP thì:

```bash
sudo apt install -y xvfb
Xvfb :99 -screen 0 1600x900x24 &
DISPLAY=:99 mono ~/mp/MissionPlanner/MissionPlanner.exe
```

rồi trong MP chọn **UDP**, cổng **14550**, bấm Connect trong khi
`tools/compare_gcs.py --takeoff --hold` đang giữ drone treo 10 m.

**Nhưng giá trị còn lại của MP đã nhỏ đi nhiều**: lỗ duy nhất nó vá được là
lat/lon, mà module `map` của MAVProxy đã vá xong (mục 1).

> `pgrep mono` luôn trả 0 dù MP đang chạy — tiến trình mono mang tên
> `Base Thread`. Tìm MP theo cổng (`ss -unlp | grep 1455`), đừng tìm theo tên.

## 8. Chạy trên FC thật

```bash
CMP_MASTER=/dev/ttyUSB0 CMP_BAUD=57600 \
    python3 tools/compare_gcs.py --home 10.8221,106.6868
```

| Điều khác so với SITL | Vì sao |
|---|---|
| **Không có `--takeoff`** | Mặc định là chỉ đo trạng thái đang có: không ARM, không gửi lệnh nào tới drone. Muốn bay thì phải gõ cờ đó ra, và **tháo cánh quạt trước**. |
| `--home <vĩ độ>,<kinh độ>` | Điểm chuẩn không còn là `CMAC` của SITL. Đo một lần bằng điện thoại ngay chỗ đặt drone là đủ — ngưỡng mặc định nới thành 10 m, đổi bằng `CMP_HOME_TOL`. |
| `CMP_BAUD` | `/dev/tty*` là cổng nối tiếp nên phải nói baud. `ttyUSB*` (radio SiK) 57600, `ttyACM*` (Pixhawk cắm thẳng) 115200. |
| Banner đổi sang **REAL** | Nguồn là FC thật thì mode phải là REAL (nguyên tắc 2.5), dù GUI vẫn nhận qua UDP từ MAVProxy. |

Đo trên đất với GPS thật là **đủ để đóng lỗ lat/lon một cách thuyết phục hơn
SITL**: toạ độ thật, nhiễu thật, và ba nhân chứng vẫn phải khớp. Hai dòng duy
nhất không kết luận được khi drone nằm im là tốc độ ngang và độ cao tương đối —
cả hai đều bằng 0, nên chúng chỉ chứng minh được "không sai đơn vị", không chứng
minh được thang đo. Muốn thang đo thì phải bay, tức là phải có `--takeoff` ngoài
bãi.
