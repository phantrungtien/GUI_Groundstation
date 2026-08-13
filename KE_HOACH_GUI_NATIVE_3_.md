# Kế hoạch chi tiết — GUI native trên laptop

> Ứng dụng PySide6 chạy trên laptop Ubuntu. Nhận telemetry qua SiK radio bằng
> pymavlink, nhận dữ liệu ROS2 qua WebSocket từ companion. **Đây là đường cứu sinh
> của toàn hệ thống.**

Tài liệu song hành: `KE_HOACH_GUI_WEB.md`

---

## Mục lục

- [1. Vai trò và ranh giới phụ thuộc](#1-vai-trò-và-ranh-giới-phụ-thuộc)
- [2. Nguyên tắc thiết kế](#2-nguyên-tắc-thiết-kế)
- [3. Lộ trình 6 giai đoạn](#3-lộ-trình-6-giai-đoạn)
- [4. Cấu trúc mã nguồn](#4-cấu-trúc-mã-nguồn)
- [5. Rủi ro và thứ tự ưu tiên](#5-rủi-ro-và-thứ-tự-ưu-tiên)
- [6. Hướng dẫn build và chạy](#6-hướng-dẫn-build-và-chạy)
- [7. Phụ lục kỹ thuật](#7-phụ-lục-kỹ-thuật)

---

## 1. Vai trò và ranh giới phụ thuộc

### 1.1. App này là hai nửa, không phải một khối

Đây là điều quan trọng nhất phải hiểu đúng trước khi code.

| | **Nửa SiK** | **Nửa ROS2** |
|---|---|---|
| Đường vào | pymavlink qua SiK radio | WebSocket tới companion |
| Tầm | Kilomet | Vài trăm mét (WiFi) |
| Nội dung | Telemetry bay, ARM/mode/takeoff, **nút đỏ** | Vision, SLAM, task ROS2, param, mission |
| Companion chết | ✅ Vẫn chạy | ❌ Chết theo |
| WiFi rớt | ✅ Vẫn chạy | ❌ Mất |

> **Nửa ROS2 phụ thuộc companion 100%.** Không có cách nào khác, và đó không phải
> lỗi thiết kế: các node ROS2 (vision, SLAM, offboard) **chạy vật lý trên
> companion**. Companion chết thì không còn ROS2 nào tồn tại để mà điều khiển.
> "Điều khiển ROS2 mà không cần companion" là thứ không thể tồn tại.

### 1.2. Cái app này bảo toàn được

Không phải mọi chức năng — mà là **an toàn bay**:

- Nhìn thấy drone ở đâu, cao bao nhiêu, pin còn bao nhiêu
- ARM / DISARM, đổi mode
- **RTL / LAND / DISARM**

Ba thứ đó đủ để đưa drone về nhà. **Ranh giới suy giảm chức năng trùng khớp với
ranh giới an toàn** — đó là điểm đáng nói, không phải "không phụ thuộc gì cả".

### 1.3. Hai kiểu hỏng khác nhau — đừng gộp

**Kiểu A — WiFi rớt, companion còn sống.**
ROS2 vẫn chạy bình thường trên drone. Task tự hành **vẫn tiếp tục thực thi** —
drone vẫn bay theo mission vision của nó. Bạn chỉ mất khả năng *quan sát và can
thiệp*. Bấm RTL qua SiK → FC chuyển mode → node offboard mất quyền → drone về nhà.

**Kiểu B — companion chết hẳn.**
ROS2 dừng, không còn setpoint gửi xuống. FC giữ nguyên mode cuối và bay theo
failsafe. Laptop qua SiK vẫn lái được.

> ⚠️ **Kiểu A nguy hiểm hơn** — drone vẫn đang *chủ động bay theo lệnh của một hệ
> thống bạn không nhìn thấy nữa*. Đây chính là lý do nút đỏ phải đi đường SiK.

### 1.4. Môi trường

| Hạng mục | Lựa chọn |
|---|---|
| OS | Ubuntu 22.04 |
| Python | 3.10 system — **không dùng venv** |
| GUI | PySide6 (Qt6) |
| MAVLink | pymavlink |
| Bản đồ | `QGraphicsView` + tile OSM offline |
| **ROS2 trên laptop** | **Không cần cài** |

---

## 2. Nguyên tắc thiết kế

### 2.1. Nút đỏ là bất khả xâm phạm

```
RTL · LAND · DISARM
   → luôn đi thẳng qua SiK bằng pymavlink
   → không qua companion
   → không qua WebSocket
   → không phụ thuộc WiFi
   → không bao giờ bị xám, bất kể chuyện gì xảy ra
   → không cần xin quyền từ cơ chế phân quyền
```

Vì đã bỏ Mission Planner khỏi kiến trúc, **code này là thiết bị an toàn**, không
còn là sản phẩm trình bày. Bug ở đây không phải bug giao diện.

### 2.2. Giao diện phải hiện rõ nửa nào đang sống

Không để người dùng nhìn số liệu đông cứng mà tưởng vẫn ổn:

- Widget **Link status** hai hàng riêng biệt: `SiK` và `Remote`, kèm byte/s thật
- Mất `Remote` → tab ROS2 / Parameter / Mission **xám hẳn**, chú thích
  "mất kết nối companion"
- Mỗi ô số mang **chấm màu nhỏ chỉ nguồn dữ liệu**
- Mất `Remote` → số liệu **không đứng hình**, tụt xuống nguồn SiK và đổi màu chấm

### 2.3. Ràng buộc an toàn nằm ở firmware, không nằm ở app

Geofence, trần độ cao, failsafe — đặt trên FC. Chúng cưỡng chế mọi đường lệnh, kể
cả đường bạn chưa nghĩ tới. Giới hạn viết trong Python thì chỉ là UX.

Đặt **System ID riêng** cho laptop (khác với companion) để log bay ghi lại được
lệnh nào đến từ đâu. Rẻ, làm ngay Phase N1.

### 2.4. Switch MANUAL/AUTO điều phối với node offboard, không phải với web

Bản web là **chỉ đọc** — nó không gửi bất kỳ lệnh nào xuống drone. Nên không có
chuyện "hai giao diện tranh quyền", và không cần đồng bộ `AUTHORITY` qua WebSocket.

Switch **MANUAL ↔ AUTO** trên app này điều phối đúng một ranh giới: giữa **bạn**
(lệnh từ laptop qua SiK) và **node offboard trên companion** (stream setpoint tự
hành). Đặt AUTO thì app publish `/gcs/authority`, node offboard tiếp tục lái. Đặt
MANUAL — hoặc bấm bất kỳ nút đỏ nào — thì node offboard nhận tín hiệu và **tự dừng
stream setpoint**, nhường lại cho bạn.

> **RC đi thẳng xuống FC, không xin phép ai** — đó là lý do RC là cứu cánh thật.
> Switch phần mềm chỉ là thỏa thuận giữa laptop và node offboard, không phải cơ
> chế an toàn của toàn hệ thống.

⚠️ Lưu ý một chỗ dễ nói tắt thành sai: **laptop không cài ROS2 nên không tự
`publish` được gì cả.** Câu "app publish `/gcs/authority`" ở trên là nói gọn — thực
tế app gửi envelope qua WebSocket, và một **bridge node trên companion** mới là
thứ publish lên topic đó. Toàn bộ đường lệnh ROS2 đi theo cơ chế này, đặc tả đầy
đủ ở **Phụ lục 7.8**.

### 2.5. Chế độ mô phỏng phải không thể nhầm lẫn

App hỗ trợ **ba nguồn kết nối**, tất cả đi qua cùng một `SikAdapter` vì đều là
MAVLink:

| Chế độ | Chuỗi kết nối | Dùng khi |
|---|---|---|
| **REAL** | `/dev/ttyUSB0` @ 57600 | Bay thật qua SiK radio |
| **SIM** | `udp:127.0.0.1:14551` hoặc `tcp:127.0.0.1:5760` | Phát triển và test với SITL |
| **REPLAY** | file `.tlog` | Debug giao diện không cần drone |

> ⚠️ **Rủi ro an toàn nghiêm trọng:** nếu ba chế độ trông giống nhau, bạn sẽ có
> lúc tưởng đang ở SIM mà thực ra đang nối drone thật — rồi bấm ARM. Hoặc ngược
> lại: tưởng đang điều khiển drone thật mà đang gõ vào mô phỏng.

Bắt buộc:

- **Banner toàn chiều ngang** ở đỉnh cửa sổ, màu khác nhau rõ rệt:
  `REAL` đỏ · `SIM` xanh dương · `REPLAY` xám
- **Đổi luôn tiêu đề cửa sổ**: `[SIM] GCS — ArduCopter`
- Chế độ **REPLAY vô hiệu hóa toàn bộ nút điều khiển**, kể cả nút đỏ — không có
  gì để gửi lệnh tới
- **Không tự động kết nối lúc khởi động.** Bắt buộc người dùng chọn nguồn. Mặc
  định im lặng an toàn hơn mặc định đoán sai

---

## 3. Lộ trình 6 giai đoạn

### Phase N0 — Môi trường laptop

#### Ba cái bẫy

**Bẫy 1 — venv và rclpy.** Nếu sau này bạn đổi sang phương án `rclpy` trực tiếp,
virtualenv sẽ làm `import rclpy` hỏng. Tập thói quen ngay từ đầu:
```bash
pip install --user PySide6 pymavlink
```

**Bẫy 2 — quyền cổng serial.**
```bash
sudo usermod -aG dialout $USER    # roi dang xuat / dang nhap lai
```

**Bẫy 3 — cặp SiK chưa bind.** Module trên drone và module mặt đất phải cùng
NetID, cùng dải tần. Mua theo cặp thì thường có sẵn; mua lẻ phải cấu hình lại.

#### Việc cần làm

- [x] `ls /dev/ttyUSB0` nhận diện được SiK @ 57600
      → 13/08/2026: `usb-FTDI_FT231X_USB_UART_DU0ENXW7` → `ttyUSB0`. Cặp Holybro
      433 MHz, `RFD SiK 2.0 on HM-TRP`, hai đầu trùng `AIR_SPEED=64 NETID=25
      TXPOWER=20` (=100 mW), `ECC=0`
- [x] SITL ArduCopter chạy được *(dùng chung với bản web — làm một lần)*
- [x] **Đo băng thông SiK thật** (xem Phụ lục 7.1) — đừng tin ước lượng
      → 13/08/2026, trên chính radio SiK, đúng bộ `STREAMS` của app, 30 s:
      **1762 B/s** — gấp **2,2×** ước lượng 800 B/s của Phụ lục 7.1. Sức chở một
      chiều ~3900 B/s (tính từ `ATI6`: cửa sổ 7140 µs @ 64 kbps × 67,6 lần/s),
      tức đang dùng **44%**. Link sạch: 0 khung hỏng, 0 lỗi giải mã, `txe=0 rxe=0`.
      **Hết chặn bàn hai cần**: TDM cấp cửa sổ riêng mỗi chiều, chiều lên còn
      trống (~20 B/s), nên lệnh điều khiển 10 Hz chỉ ăn ~8% cửa sổ lên
- [x] Cài Mission Planner để đối chiếu *(không nằm trong kiến trúc, chỉ để test)*
      → `mono-complete` 6.8 + MP 1.3.83 chạy được, nhưng **việc đối chiếu làm bằng
      MAVProxy** (`tools/compare_gcs.py`). Lý do MP không đọc được số: `docs/doi_chieu_gcs.md` mục 7

#### Nghiệm thu

Kết nối SITL hoặc FC thật qua SiK bằng script pymavlink 10 dòng, in ra được
lat/lon/alt/battery/mode.

> **Đạt một nửa.** SITL thì xong từ lâu. **Qua SiK thì chưa** — chưa từng có
> `/dev/ttyUSB*` cắm vào máy này. Đó là món chặn duy nhất còn lại của N0.

---

### Phase N1 — Lõi + hai adapter + vỏ app

**Phase quan trọng nhất.** Mọi phase sau chỉ là vẽ widget lên trên nó.

> 📌 Thư mục `core/` **dùng chung với bản web**. Viết một lần, hai backend cùng
> dùng — nếu đã làm bản web trước thì phần lõi coi như xong.

#### Hạng mục

| File | Dùng chung? | Nội dung |
|---|---|---|
| `core/bus.py` | ✅ | Envelope `{src, topic, data, ts}`, `emit()` |
| `core/field.py` | ✅ | Trọng tài đa nguồn, `best()` trả `(value, src)`, `divergence()` |
| `core/authority.py` | ✅ | `AUTHORITY`, tập `ESCAPE`, `dispatch()` |
| `core/adapters/sik.py` | riêng | pymavlink trong `QThread`, chuẩn hóa **NED → ENU** |
| `core/adapters/remote.py` | riêng | WebSocket client → nhận envelope từ companion |
| `laptop/app.py` | riêng | `QMainWindow`, khung tab rỗng |
| `laptop/link_status.py` | riêng | Widget hai hàng SiK / Remote |
| `laptop/connection.py` | riêng | **Hộp thoại chọn nguồn + banner chế độ** |
| `laptop/replay.py` | riêng | **Đọc `.tlog`, phát lại theo timestamp** |
| `config/connections.yaml` | riêng | **Profile kết nối lưu sẵn** |
| `docs/protocol.md` | ✅ | Đặc tả envelope — **viết ngay bây giờ** |

#### Connection manager — làm ngay Phase này

Không để cuối dự án. Bạn cần SIM để phát triển toàn bộ N2–N4, nên nó phải có từ
đầu. Chi phí thấp vì `mavutil.mavlink_connection()` nhận mọi chuỗi kết nối.

```yaml
# config/connections.yaml
- name: "SiK radio (that)"
  mode: REAL
  conn: "/dev/ttyUSB0"
  baud: 57600

- name: "SITL localhost"
  mode: SIM
  conn: "udp:127.0.0.1:14551"

- name: "Phat lai chuyen bay"
  mode: REPLAY
  path: "logs/*.tlog"
```

Hộp thoại khởi động liệt kê profile, người dùng chọn. `mode` quyết định màu
banner và việc có khóa nút điều khiển hay không — **`mode` là nguồn sự thật, không
phải suy ra từ chuỗi kết nối**.

`replay.py` đọc `.tlog` (chính là chuỗi MAVLink thô kèm timestamp) và bơm message
vào bus theo đúng nhịp thời gian gốc, có nút tạm dừng và thanh tua. Nó cho bạn
debug giao diện trên chuyến bay đã xảy ra — kể cả chuyến bay hỏng.

#### Hai kho dữ liệu song song

- **`STATE`** — gõ tay, đúng tên đúng đơn vị, phục vụ HUD
- **`STATUS`** — generic, trải phẳng từ `msg.to_dict()`, phục vụ tab Status

```python
# Thay cho chuoi if/elif dai — tu dong co MOI field FC gui len
d = msg.to_dict()
name = d.pop("mavpackettype")
for k, v in d.items():
    if isinstance(v, (int, float)):
        STATUS[f"{name}.{k}"] = v
```

#### Ba quy tắc không được vi phạm

> ⚠️ **Không chạm widget Qt từ thread pymavlink hoặc thread WebSocket.**
> Luôn đi qua Qt signal. Vi phạm gây **crash ngẫu nhiên sau vài phút** — cực khó truy.

> ⚠️ **`QThread` cho mỗi adapter.** Adapter phát signal, main thread nhận và vẽ.

> ⚠️ **Chuẩn hóa NED → ENU ngay tại `sik.py`.** Không để tầng UI biết chuyện này
> (xem Phụ lục 7.3).

#### Nghiệm thu

- [x] Khởi động → hiện hộp thoại chọn nguồn, **không tự nối gì cả**
- [x] Chọn `SITL localhost` → banner xanh dương, tiêu đề `[SIM] ...`, dữ liệu chảy
- [x] Chọn `SiK radio` → banner đỏ, tiêu đề `[REAL] ...`
- [x] Chọn `.tlog` → banner xám, dữ liệu phát lại đúng nhịp, tua được
- [x] Widget Link status hiện **hai hàng** với byte/s thật
- [x] Rút WiFi → hàng `Remote` xám trong 2 giây, hàng `SiK` vẫn xanh, app không treo

Cả sáu dòng nằm trong `tools/selfcheck.py` (**25/25 PASS**) và `tools/check_halves.py`.
- Tắt SITL → hàng `SiK` xám, app không treo

---

### Phase N2 — Nội dung các tab

#### Bộ khung: 4 tab

Cửa sổ chính là một `QTabWidget` với đúng bốn tab. **Map không phải tab riêng** —
nó là nền của tab Flight, có overlay đè lên (xem dưới).

| objectName | Nhãn | Nội dung |
|---|---|---|
| `Flight` | Bay | Map nền (offline) + overlay HUD/la bàn/telemetry |
| `Status` | Trạng thái | Bảng số liệu tra cứu, debug |
| `Control` | Điều khiển | ARM / mode / takeoff + nút đỏ |
| `Messages` | Thông báo | Log `STATUSTEXT` |

> **SITL không phải một tab.** Nó là một *nguồn kết nối* — chọn ở hộp thoại khởi
> động (REAL / SIM / REPLAY), rồi dữ liệu chảy vào đúng bốn tab trên y như dữ liệu
> thật. Banner đổi màu cho biết đang ở chế độ nào (xem nguyên tắc 2.5), không cần
> tab riêng.

#### Thứ tự làm — tab đọc trước

Làm đúng thứ tự này; mỗi tab tái sử dụng hạ tầng của tab trước. **Tab Flight làm
sau cùng** vì nó là phần khó nhất (map + overlay + widget tự vẽ).

| # | Tab | Công nghệ | Nguồn | Ghi chú |
|---|---|---|---|---|
| 1 | **Status** | `QTableView` + ô search | `STATUS` | Làm trước — dễ nhất, thành công cụ debug cho mọi phase sau |
| 2 | **Messages** | `QListView` lọc severity | `STATUSTEXT` | Log cuộn |
| 3 | **Control** | Nút Designer | lệnh → adapter | Nút đỏ tách riêng về mã nguồn |
| 4 | **Flight** | Map + `QPainter` overlay | `Field` | Map nền + la bàn/attitude tự vẽ đè lên |

**Vì sao Status trước:** không hardcode từng field, nên bạn có ngay **mọi** thông
số FC gửi lên — kể cả message chưa nghĩ tới — và không phải sửa code khi đổi
firmware. Nó cũng là công cụ để kiểm chứng mọi tab còn lại.

> 📌 **Tab Flight là phần nặng nhất.** Map làm nền, còn la bàn + attitude
> indicator + thanh telemetry **nổi đè lên** map — đây là *overlay*, không phải
> *layout*. Qt Designer không dựng overlay được; phải đặt widget con bằng code với
> tọa độ tuyệt đối, gọi `.raise_()` cho nổi lên, và xử lý lại vị trí khi cửa sổ
> đổi kích thước. Xem Phụ lục 7.7.

#### Công cụ dựng giao diện

Dùng **Qt Designer** (`pyside6-designer` hoặc Qt Creator, đều đúng Qt 6) cho phần
bố cục tĩnh, viết tay cho phần vẽ động và overlay:

| Thành phần | Cách làm |
|---|---|
| Khung cửa sổ, 4 tab | ✅ Qt Designer |
| Tab Status (bảng + search) | ✅ Qt Designer |
| Tab Control (nút ARM / mode / nút đỏ) | ✅ Qt Designer |
| Tab Messages (log cuộn) | ✅ Qt Designer |
| **La bàn, attitude indicator** | ❌ Tự vẽ `QPainter` |
| **Map nền** | ❌ `QGraphicsView` + tile offline |
| **Xếp overlay lên map** | ❌ Code, không phải Designer |

Cách ghép: Designer dựng khung cửa sổ và bốn tab, chừa ô trống trong tab Flight
rồi **promote** thành widget tự viết (chuột phải → Promote to → `AttitudeWidget`).
Designer lưu `.ui`, `pyside6-uic` dịch sang Python.

> **Về vẻ ngoài:** thứ làm giao diện GCS trông chuyên nghiệp không phải bố cục mà
> là **theme tối + widget vẽ khéo**. Nền tối là chuẩn de facto của mọi GCS (Mission
> Planner, QGC, Cockpit) vì dùng ngoài nắng đỡ chói và nhìn lâu đỡ mỏi. Áp một
> stylesheet tối cho toàn app ngay từ đầu — nâng vẻ ngoài nhiều nhất với công sức
> ít nhất.

#### Nghiệm thu

- [x] Chạy SITL, so từng con số với Mission Planner — sai lệch chỉ do làm tròn
      → **ĐẠT 07/08/2026** bằng `tools/compare_gcs.py`, đối chiếu với MAVProxy.
      Treo 10 m: độ cao lệch 0.000 m, điện áp 0 V, **toạ độ lệch 0**; trên đất
      toạ độ lệch 0,70 m so với chỗ SITL đặt drone. Số đo: `docs/doi_chieu_gcs.md`
- [x] Rút WiFi giữa chừng → số liệu **không đứng hình**, tụt xuống SiK, đổi màu chấm
      → `tools/check_halves.py` PASS
- [x] Chạy liên tục 30 phút không crash
      → **ĐẠT 07/08/2026**: 178 413 envelope (99/s), RAM 109,3 → 119,8 MB và
      **đứng yên từ phút 1 tới phút 30**, nhịp Qt 17999/18000

---

### Phase N3 — Điều khiển, phân quyền, nút đỏ

> Đây là phase **an toàn bay**.

#### Hạng mục

- [x] Thanh trên: switch **MANUAL (GCS)** ↔ **AUTO (ROS2)**, hiện rõ ai cầm quyền
      → `laptop/tabs/control.py:82`
- [x] Nút thường: ARM / DISARM / chọn mode / TAKEOFF
      → TAKEOFF ở REAL xác nhận bằng bấm lại trong 3 s, không dùng hộp thoại
- [x] **Nhóm nút đỏ tách riêng về mặt mã nguồn** — gọi thẳng `SikAdapter`,
      không đi qua `dispatch()` → `core/authority.py:15` `ESCAPE`
- [x] System ID riêng cho laptop → `sysid: 254` trong `config/connections.yaml`
- [x] Node offboard trên companion subscribe `/gcs/authority`, tự dừng stream
      setpoint khi mất quyền → repo `ros2-ardupilot-sitl-hardware`; QoS phải
      **TRANSIENT_LOCAL** cả hai đầu, lệch durability là DDS bỏ qua cặp ghép mà
      **không một lỗi nào**. `tools/e2e_ros2.py` assert cứng
- [x] **`bridge_node.py` trên companion** — WebSocket server dịch envelope thành
      lời gọi ROS2 (Phụ lục 7.8) → `tools/ros2_bridge.py`, `--spawn` chỉ chạy tên
      trong danh sách trắng
- [x] **Bảng lệnh chờ + timeout 3 giây** — không có nó thì nút bấm hỏng sẽ treo
      mãi mà không ai biết → `laptop/tabs/control.py:204` `_pending`, **nằm ở
      control.py chứ không phải `remote.py`** như kế hoạch dự định
- [x] Nút đường ROS2 tự khóa khi đang chờ ack; **nút đỏ không bao giờ khóa**
      → `tools/selfcheck.py` có check riêng cho điều này

#### Mã nguồn — chỗ dễ sai nhất

```python
ESCAPE = {"rtl", "land", "disarm"}

def dispatch(msg):
    action = msg["action"]
    if action in ESCAPE:
        return SIK.send(action, msg.get("args", {}))   # KHONG kiem tra quyen
    if msg["target"] != AUTHORITY:
        return {"error": f"quyen dang thuoc ve {AUTHORITY}"}
    return ADAPTERS[msg["target"]].send(action, msg.get("args", {}))
```

Nút đỏ đi trước mọi kiểm tra. Không có nhánh nào làm nó bị chặn.

#### Nghiệm thu

- [x] Trên SITL: ARM → TAKEOFF 5 m → RTL hoàn chỉnh chỉ bằng app này
- [x] **Tắt hẳn companion giữa lúc drone đang bay**, bấm RTL → drone vẫn về nhà
      → `tools/check_halves.py`
- [x] Rút WiFi (kiểu hỏng A), bấm RTL → drone về nhà, node offboard mất quyền
- [x] Set authority sang `ros2`, bấm TAKEOFF → bị từ chối; bấm RTL → vẫn ăn
      → `tools/e2e_ros2.py` trên stack ROS2 thật: mission stream 30 Hz ở 10,2 m,
      bấm RTL → **không thêm một vòng `laps` nào**, node dừng hẳn

> **ARM/DISARM đã đạt trên phần cứng thật — 13/08/2026**, qua radio SiK 433 MHz,
> bằng chứng `logs/20260813-181529-real.tlog`:
>
> | mốc | sự kiện |
> |---|---|
> | 4,2 s | `COMMAND_ACK` 400 → **từ chối**, FC nói `Arm: GPS 1: Bad fix` (đang ở mode cần vị trí, GPS 0 vệ tinh) |
> | 27,8 s | đổi sang STABILIZE → `COMMAND_ACK` 400 → **chấp nhận** |
> | 28,0 s | heartbeat lật sang **ARMED**, mode STABILIZE |
> | 43,0 s | `COMMAND_ACK` 400 → chấp nhận → **DISARMED** |
>
> `COMMAND_ACK` lệnh 400 chứng minh lệnh đến từ MAVLink, tức nút trên app — arm
> bằng cần lái không sinh ack này. Đường từ chối cũng đạt: FC nêu lý do và app
> hiện nguyên văn ở tab Messages, không nuốt mất.
>
> **Còn nợ: TAKEOFF → RTL trên phần cứng thật** (cần GPS fix ngoài trời), ba dòng
> kịch bản companion, và chặng ga-giữa-tầm của `tools/hitl.py disarm` — phải in
> `landed = False` mà vẫn gửi FORCE, chứng minh rangefinder gánh được lúc
> `landed_state` lật sang IN_AIR. Hai tlog 04/08 đều chỉ có `landed_state = 1`.

---

### Phase N4 — Tab Flight (map nền + overlay)

> ⚠️ **Phase rủi ro nhất của bản native.** Gồm ba việc khó chồng lên nhau: map
> offline, widget tự vẽ (`QPainter`), và xếp overlay bằng code.

#### Bước 1 — Map nền

Chốt hướng dựa trên prototype đã làm ở cuối Phase N2:

| Phương án | Ưu | Nhược |
|---|---|---|
| `QGraphicsView` + tile OSM offline | Nhẹ, **chạy ngoài đồng không cần mạng** | Tự viết pan/zoom |
| `QtWebEngine` nhúng Leaflet | Nhanh làm | Kéo theo cả Chromium, app nặng lên đáng kể |

**Với drone bay ngoài hiện trường, tile offline gần như chắc chắn là lựa chọn
đúng** — laptop ngoài bãi bay không có internet.

- [x] Vẽ tile offline, pan/zoom → `map_widget.py:348` `wheelEvent`, `:359` kéo map
- [x] Vị trí realtime + vệt đường bay → `map_widget.py:279` `trail`, cắt bớt theo `MAX_TRAIL`
- [x] Home position, geofence → `set_home`, `set_fence`; đã test rào 4 điểm trên SITL
- [x] Tải sẵn tile cho khu vực bay trước khi ra hiện trường
      → `tools/fetch_tiles.py`, hiện có **21 038 tile / 265 MB**. Nguồn đổi Esri →
      **Google** vì Esri trần ở 29 cm/pixel còn Google xuống 7,3 cm/pixel; đổi nguồn
      **phải kèm `--refetch`** không thì màn hình trộn hai kiểu ảnh
- [x] Click bản đồ → GUIDED + goto **(chỉ khi cầm quyền MANUAL)**
      → `laptop/tabs/flight.py:130` — quyền thuộc ROS2 thì mục này xám đi

#### Bước 2 — Widget tự vẽ đè lên map

Làm từng widget riêng lẻ trước, test trên cửa sổ trống với dữ liệu giả, rồi mới
ghép lên map. **Thứ tự học `QPainter`: la bàn trước (một phép xoay), attitude sau
(xoay + dịch chồng nhau).**

- [x] La bàn — xoay theo heading → `laptop/widgets/compass.py`
- [x] Attitude indicator — đường chân trời theo roll + pitch → `laptop/widgets/attitude.py`
- [x] Thanh telemetry (tốc độ, độ cao, pin) — overlay góc dưới
      → `laptop/widgets/telemetry_bar.py`; mỗi ô mang một chấm màu chỉ nguồn dữ
      liệu, nguồn hết tươi thì số xám đi (nguyên tắc 2.2)

#### Bước 3 — Xếp overlay

Đây là phần Qt Designer không làm được. Xem Phụ lục 7.7 cho khung code. Các widget
ở bước 2 đặt làm **con của tab Flight**, tọa độ tuyệt đối, `.raise_()` để nổi lên
trên map, và cập nhật lại vị trí trong `resizeEvent`.

#### Nghiệm thu

- [x] Tab Flight hiện map offline, la bàn quay theo heading thật từ SITL
      → heading lấy `attitude.heading` trước, tụt về `position.heading` sau. FC gửi
      **hai** hướng mũi khác nhau, lệch ~1° là thật — xem `docs/doi_chieu_gcs.md` mục 6
- [x] Attitude indicator nghiêng đúng theo roll/pitch
- [x] Phóng to/thu nhỏ cửa sổ → overlay giữ đúng vị trí góc, không trôi
- [x] Ngắt mạng hoàn toàn → map vẫn hiện (tile offline)

---

### Phase N5 — Kiểm thử

#### Thứ tự không được đảo

1. **SITL** — hết mọi kịch bản, đặc biệt kịch bản hỏng
2. **HITL** — Pixhawk thật, **tháo cánh quạt**, kiểm tra motor quay đúng lệnh
3. **Bay thật** — khu vực trống, **luôn có người cầm RC sẵn sàng giành quyền**

> 💡 Mở sẵn Mission Planner ở màn hình bên cạnh trong những chuyến bay đầu.
> Bảo hiểm miễn phí, và là công cụ đối chiếu xem app hiển thị đúng chưa.

#### Công cụ mô phỏng — chỉ hiện ở chế độ SIM

Một **panel Sim** (cửa sổ phụ hoặc dock, **không phải một tab thứ năm**) chỉ xuất
hiện khi `mode == SIM`, phục vụ đúng bảng kịch bản bên dưới. Không có nó thì việc
tái hiện lỗi rất thủ công.

- [x] ~~**Tiêm lỗi** — đặt các tham số `SIM_*` của ArduPilot SITL để giả lập nhiễu
      GPS, mất GPS, tụt điện áp pin. Mỗi lỗi một nút~~
      → **bỏ có chủ ý.** Panel này đã viết rồi xoá: chỉnh world hoặc `param set`
      trong MAVProxy là đủ, không đáng có một giao diện riêng trong app bay
- [x] **Cắt link** — dừng gửi/nhận trên `SikAdapter` hoặc `RemoteAdapter` theo yêu
      cầu, để tái hiện kịch bản #1–#4 **mà không phải rút dây**
      → `laptop/link_faults.py`. Đây là phần **giữ lại** khi xoá panel tiêm lỗi:
      lỗi phía app thì world không mô phỏng được
- [x] **Ghi `.tlog`** — bật ở mọi chế độ, kể cả REAL. Đây là đầu vào cho REPLAY
      → `core/adapters/sik.py:267`. Không dùng `master.setup_logfile()`: nó ghi đè
      `mavudp.recv_msg` và bỏ mất gói
- [ ] **Hệ số tăng tốc** — SITL chạy nhanh hơn thời gian thực để rút ngắn bài test
      dài. Lưu ý: **không dùng tăng tốc khi đo hiệu năng giao diện**, kết quả sẽ sai
      → **chưa dùng bao giờ**, mọi bài đều chạy `--speedup 1`. Bài dài nhất là
      `soak.py 30` và nó *đo hiệu năng giao diện*, tức đúng chỗ cấm tăng tốc

> ⚠️ Tên và ý nghĩa tham số `SIM_*` **khác nhau giữa các phiên bản ArduPilot**.
> Tra trên đúng bản SITL đang chạy, đừng chép từ hướng dẫn cũ.

#### Kịch bản hỏng bắt buộc

*Kịch bản #1–#4 tái hiện được bằng nút "Cắt link" ở panel Sim trước, rồi mới làm
lại bằng cách rút dây thật.*

| # | Kịch bản | Kỳ vọng |
|---|---|---|
| 1 | **WiFi rớt, companion còn sống** (kiểu A) | Tab ROS2 xám; số liệu tụt về SiK; task tự hành **vẫn đang chạy trên drone** — app phải cảnh báo rõ điều này |
| 2 | **Companion chết hẳn** (kiểu B) | Tab ROS2 xám; nút đỏ vẫn ăn; FC giữ mode cuối |
| 3 | Rút SiK khỏi laptop | **Cảnh báo nặng** — đã mất đường cứu sinh |
| 4 | Mất cả SiK và WiFi | Báo động rõ ràng, không giả vờ còn kết nối; RC vẫn lái được |
| 5 | RTL trong lúc ROS2 stream setpoint | Drone về nhà, không giằng co |
| 6 | Set authority sang ROS2 rồi bấm nút thường | Bị từ chối, có thông báo |
| 7 | App crash | Drone giữ nguyên mode, không rơi |
| 8 | Hai nguồn lệch vị trí > 5 m | Cảnh báo divergence |
| 9 | Ra xa dần tới khi rớt WiFi | SiK vẫn nắm được drone |
| 10 | Chạy liên tục 30 phút | Không crash *(bài test cố định cho lỗi Qt/thread)* |
| 11 | **Mở app ở chế độ REPLAY, bấm mọi nút** | Toàn bộ nút điều khiển bị khóa, kể cả nút đỏ |
| 12 | **Cắm SiK thật nhưng chọn profile SIM** | Banner đỏ/xanh phải phản ánh đúng `mode` đã chọn, không đoán từ chuỗi kết nối |

---

## 4. Cấu trúc mã nguồn

```
telemetry_control_realtime/
├── core/                      # DUNG CHUNG voi ban web
│   ├── bus.py
│   ├── field.py
│   ├── authority.py
│   └── adapters/
│       ├── sik.py             # pymavlink        (chi ban native)
│       └── remote.py          # websocket client (chi ban native)
│
├── laptop/
│   ├── app.py                 # QMainWindow
│   ├── link_status.py
│   ├── connection.py          # chon nguon + banner che do
│   ├── replay.py              # doc va phat lai .tlog
│   ├── tabs/
│   │   ├── flight.py          # map nen + xep overlay
│   │   ├── status.py
│   │   ├── control.py         # + nut do
│   │   └── messages.py
│   ├── widgets/               # widget tu ve, dung trong tab Flight
│   │   ├── map_widget.py      # QGraphicsView + tile offline
│   │   ├── compass.py         # QPainter
│   │   ├── attitude.py        # QPainter
│   │   └── telemetry_bar.py
│   └── sim_panel.py           # cong cu tiem loi, CHI hien khi mode == SIM
│
├── config/
│   └── connections.yaml       # profile REAL / SIM / REPLAY
│
├── assets/
│   └── tiles/                 # tile OSM offline
│
├── logs/                      # .tlog ghi tu moi chuyen bay
│
├── tools/
│   ├── run_sitl.sh
│   └── measure_sik_bandwidth.py
│
└── docs/
    ├── protocol.md            # dac ta envelope
    ├── operating_procedure.md # quy trinh bay
    └── KE_HOACH_GUI_NATIVE.md # file nay
```

> 📌 **Một file nằm ngoài cây này nhưng không thể thiếu:** `bridge_node.py` chạy
> trên **companion**, không phải laptop. Nó là đầu bên kia của `remote.py` — dịch
> envelope WebSocket thành lời gọi ROS2. Đặt nó trong ROS2 workspace của
> companion, và giữ `docs/protocol.md` là nguồn sự thật chung cho cả hai đầu
> (xem Phụ lục 7.8).

---

## 5. Rủi ro và thứ tự ưu tiên

### 5.1. Ba rủi ro

**#1 — Tab Flight vượt dự toán.** Ẩn số lớn nhất: map offline không có Leaflet,
cộng thêm widget tự vẽ và xếp overlay bằng code.
→ *Giảm thiểu:* làm prototype map ở **cuối Phase N2**; học `QPainter` bằng widget
la bàn riêng lẻ trước khi ghép. Đừng để cả ba việc khó dồn vào Phase N4 cùng lúc.

**#2 — Ghép pymavlink/WebSocket với Qt sinh crash ngẫu nhiên.** Triệu chứng: chết
sau vài phút, rất khó truy.
→ *Giảm thiểu:* kỷ luật tuyệt đối về Qt signal; chạy bài test 30 phút ở cuối
**mỗi** phase, không chỉ Phase N5.

**#3 — Băng thông SiK không như ước lượng.** Radio nhiễu, tầm xa, mất gói.
→ *Giảm thiểu:* đo thật ở Phase N0. Nếu hẹp, giảm tần số `ATTITUDE` xuống 5 Hz —
HUD vẫn dùng được.

### 5.2. Nếu bị dồn deadline, cắt theo thứ tự

1. Overlay trên map rút gọn còn một chấm vị trí, bỏ la bàn/attitude
2. Tab Messages

> 🚫 **Không bao giờ cắt:** `SikAdapter`, nhóm nút đỏ, widget Link status,
> cơ chế phân quyền. Đó là **an toàn bay**.

---

## 6. Hướng dẫn build và chạy

Toàn bộ chạy trên **laptop Ubuntu 22.04**. Laptop **không cần cài ROS2** —
`RemoteAdapter` chỉ nói WebSocket, không dùng rclpy.

### 6.1. Cài phụ thuộc hệ thống

```bash
sudo apt update
sudo apt install -y python3-pip git

# Quyen doc cong serial cho SiK radio
sudo usermod -aG dialout $USER
# -> DANG XUAT / DANG NHAP lai de co hieu luc
```

> ⚠️ **Không tạo virtualenv.** Dự án này không cần ROS2 trên laptop, nhưng giữ
> thói quen dùng `pip --user` để nếu sau này đổi sang phương án `rclpy` trực tiếp
> thì `import rclpy` không hỏng (venv che khuất gói ROS2 của hệ thống).

### 6.2. Cài thư viện Python

```bash
pip install --user PySide6 pymavlink pyyaml websockets
```

| Gói | Dùng cho |
|---|---|
| `PySide6` | Toàn bộ giao diện, kèm sẵn `pyside6-designer` và `pyside6-uic` |
| `pymavlink` | `SikAdapter` — đọc/gửi MAVLink qua SiK radio |
| `pyyaml` | Đọc `config/connections.yaml` |
| `websockets` | `RemoteAdapter` — nhận envelope từ companion |

Kiểm tra:
```bash
python3 -c "import PySide6, pymavlink, yaml, websockets; print('OK')"
pyside6-designer --version      # xac nhan Designer co san
```

### 6.3. Lấy mã nguồn

```bash
git clone <repo-cua-ban> gcs
cd gcs
```

### 6.4. Quy trình dựng giao diện (Qt Designer → Python)

Bước này chỉ chạy lại khi **sửa file `.ui`**, không phải mỗi lần chạy app.

```bash
# 1. Mo Designer de sua bo cuc (thanh tren, cac tab, o promote cho HUD/Map)
pyside6-designer laptop/ui/main_window.ui

# 2. Dich .ui -> .py sau khi luu
pyside6-uic laptop/ui/main_window.ui -o laptop/ui/main_window_ui.py
```

> Widget tự vẽ (HUD, Map) **không** nằm trong `.ui`. Trong Designer, chuột phải ô
> trống → *Promote to* → nhập tên class (ví dụ `AttitudeWidget`) và đường dẫn
> module. `pyside6-uic` sẽ sinh mã tham chiếu tới class đó; bạn viết class riêng
> trong `laptop/tabs/`.

Có thể tự động hóa bằng một script:
```bash
# tools/build_ui.sh
for f in laptop/ui/*.ui; do
    pyside6-uic "$f" -o "${f%.ui}_ui.py"
done
```

### 6.5. Chạy app

App **không tự kết nối** — khởi động sẽ hiện hộp thoại chọn nguồn (REAL / SIM /
REPLAY) từ `config/connections.yaml`.

```bash
python3 -m laptop.app
```

**Chế độ SIM** cần SITL chạy trước ở một terminal khác:
```bash
# Terminal 1 — SITL
sim_vehicle.py -v ArduCopter --console --map --out=udp:127.0.0.1:14551

# Terminal 2 — app, roi chon profile "SITL localhost"
python3 -m laptop.app
```

**Chế độ REAL:** cắm SiK radio, chọn profile `SiK radio`. Kiểm tra `/dev/ttyUSB0`
tồn tại và bạn đã ở nhóm `dialout`.

**Chế độ REPLAY:** chọn file `.tlog`, không cần drone hay SITL.

### 6.6. Đóng gói (tùy chọn)

Chỉ cần khi muốn đưa cho máy khác chạy mà không cài Python. Vì laptop không dùng
ROS2, `PyInstaller` gói được sạch:

```bash
pip install --user pyinstaller
pyinstaller --onefile --windowed \
    --add-data "config:config" \
    --add-data "assets/tiles:assets/tiles" \
    -n gcs laptop/app.py
# Ket qua: dist/gcs
```

> Test file đóng gói trên một máy Ubuntu **sạch chưa cài Python** — đó là mục
> đích duy nhất của bước này. Trên máy phát triển thì cứ chạy thẳng bằng
> `python3 -m laptop.app`.

### 6.7. Sự cố thường gặp

| Triệu chứng | Nguyên nhân · cách xử lý |
|---|---|
| `Permission denied: /dev/ttyUSB0` | Chưa vào nhóm `dialout`, hoặc chưa đăng nhập lại |
| Không thấy `/dev/ttyUSB0` | Sai driver USB-serial, hoặc cặp SiK chưa bind |
| `pyside6-designer: command not found` | PySide6 cài bằng `--user`; thêm `~/.local/bin` vào `PATH` |
| App mở nhưng số liệu đứng im ở SIM | SITL chưa chạy, hoặc sai cổng trong `connections.yaml` |
| Bản đồ trắng khi offline | Chưa tải tile vào `assets/tiles/` |
| Crash sau vài phút | Đang chạm widget Qt từ thread — xem lại nguyên tắc Qt signal ở N1 |

---

## 7. Phụ lục kỹ thuật

### 7.1. Băng thông SiK — streaming được, bulk thì không

Tính ở 57600 baud, MAVLink v2, overhead ~12 byte/message:

| Message | Tần số | Băng thông |
|---|---|---|
| `HEARTBEAT` | 1 Hz | ~21 B/s |
| `SYS_STATUS` | 2 Hz | ~86 B/s |
| `GLOBAL_POSITION_INT` | 3 Hz | ~120 B/s |
| `ATTITUDE` | 10 Hz | ~400 B/s |
| `VFR_HUD` | 4 Hz | ~128 B/s |
| `GPS_RAW_INT` | 1 Hz | ~42 B/s |
| **Tổng** | | **~800 B/s** |

Băng thông khả dụng thực khoảng **4–5 KB/s** — thừa gấp năm lần. **Đường SiK chở
nổi một HUD đầy đủ, mượt, 10 Hz.**

- ✅ **Streaming** — attitude, position, pin, tốc độ, GPS
- ❌ **Bulk transfer** — parameter list (**hàng phút**), mission nhiều waypoint,
  log bay, ảnh → những thứ này chỉ có trên **bản web**

### 7.2. Yêu cầu stream rate từ FC

```python
for stream_id, rate_hz in [
    (mavutil.mavlink.MAV_DATA_STREAM_EXTENDED_STATUS, 2),
    (mavutil.mavlink.MAV_DATA_STREAM_POSITION, 3),
    (mavutil.mavlink.MAV_DATA_STREAM_EXTRA1, 10),   # ATTITUDE
    (mavutil.mavlink.MAV_DATA_STREAM_EXTRA2, 4),    # VFR_HUD
]:
    master.mav.request_data_stream_send(
        master.target_system, master.target_component, stream_id, rate_hz, 1)
```

### 7.3. Bẫy hệ tọa độ — NED vs ENU

- **pymavlink** đọc thẳng MAVLink → **NED**: x bắc, y đông, z **xuống**
- **Dữ liệu từ companion** (qua MAVROS) → **ENU**: x đông, y bắc, z **lên**

App này có **cả hai nguồn cho cùng một đại lượng**. Không cẩn thận thì hai giá trị
`z` trái dấu và bạn tưởng có bug.

> **Quy ước: chuẩn hóa hết về ENU ngay tại `sik.py`.**

### 7.4. Trọng tài đa nguồn (`Field`)

```python
PRIORITY = {'remote': 2, 'sik': 1}   # remote uu tien vi tan so cao hon
STALE    = 2.0                       # giay
```

- `best()` trả về **cả giá trị lẫn nguồn**, không chỉ giá trị
- `divergence()` so hai nguồn, vượt ngưỡng thì cảnh báo — EKF có vấn đề hoặc một
  link đang trễ nặng
- Lớp này không biết gì về MAVLink hay WebSocket, chỉ biết `src` là một chuỗi.
  Thêm đường thứ ba (LTE, LoRa) thì chỉ thêm một dòng vào `PRIORITY`

### 7.5. Envelope

```python
# Vao app
{"src": "sik",    "topic": "position", "data": {...}, "ts": 1721...}
{"src": "remote", "topic": "position", "data": {...}, "ts": 1721...}

# Ra drone
{"id": "c17", "target": "sik",  "action": "rtl",      "args": {},                  "ts": 1721...}
{"id": "c18", "target": "ros2", "action": "set_task", "args": {"task": "WAYPOINT"}, "ts": 1721...}

# Ack tra ve (chi duong ros2)
{"id": "c18", "ok": true, "message": "Da chuyen sang WAYPOINT"}
```

Nhờ trường `src`, UI hiển thị `Lat 10.762 (sik)` và `Lat 10.763 (remote)` cạnh
nhau mà không nhầm.

Trường `id` là bắt buộc với mọi envelope đi ra — nó là thứ duy nhất ghép được ack
về với nút đã bấm. Chi tiết ở Phụ lục 7.8.

### 7.6. Chuỗi kết nối và SITL

`mavutil.mavlink_connection()` nhận mọi dạng dưới đây — **cùng một `SikAdapter`,
không phải viết hai đường code**:

```python
mavutil.mavlink_connection("/dev/ttyUSB0", baud=57600)   # SiK that
mavutil.mavlink_connection("udp:127.0.0.1:14551")        # SITL
mavutil.mavlink_connection("tcp:127.0.0.1:5760")         # SITL, cong mac dinh
mavutil.mavlink_connection("logs/flight.tlog")           # phat lai
```

Khởi động SITL kèm sẵn cổng cho app:

```bash
sim_vehicle.py -v ArduCopter --console --map \
    --out=udp:127.0.0.1:14551
```

Nếu muốn mở Mission Planner song song để đối chiếu, thêm một `--out` nữa —
SITL tự chia được, **không cần mavlink-router** như khi dùng SiK thật:

```bash
sim_vehicle.py -v ArduCopter --console --map \
    --out=udp:127.0.0.1:14550 \
    --out=udp:127.0.0.1:14551
```

**Về `.tlog`:** đây là chuỗi MAVLink thô kèm timestamp, chính là định dạng
Mission Planner ghi. Nghĩa là REPLAY của bạn đọc được cả log do Mission Planner
tạo ra, không chỉ log của app mình.

> **Nên bật ghi `.tlog` ở mọi chế độ, kể cả REAL.** Sau sự cố, đây thường là thứ
> duy nhất cho biết chuyện gì đã xảy ra.

### 7.7. Xếp overlay lên map trong tab Flight

Qt Designer sắp widget bằng layout — chúng nằm cạnh nhau, không đè lên nhau. Màn
hình bay cần la bàn/telemetry **nổi đè** lên map, nên phần này làm bằng code.

Nguyên tắc: các widget overlay là **con trực tiếp** của tab Flight (không nằm
trong layout), đặt tọa độ tay, gọi `.raise_()` để nổi lên trên map, và tính lại
vị trí mỗi khi cửa sổ đổi kích thước.

```python
class FlightTab(QWidget):
    def __init__(self):
        super().__init__()

        # Map lap day ca tab, nam duoi cung
        self.map = MapWidget(self)

        # Cac overlay — con cua tab, KHONG cho vao layout nao
        self.compass  = Compass(self)
        self.attitude = AttitudeWidget(self)
        self.telemetry = TelemetryBar(self)

        for w in (self.compass, self.attitude, self.telemetry):
            w.raise_()               # noi len tren map

    def resizeEvent(self, e):
        # Map phu kin
        self.map.setGeometry(0, 0, self.width(), self.height())

        # Overlay bam theo goc — tinh lai moi khi resize
        m = 12
        self.compass.move(self.width() - self.compass.width() - m, m)
        self.telemetry.move(m, self.height() - self.telemetry.height() - m)
        self.attitude.move(self.width() - self.attitude.width() - m,
                           self.height() - self.attitude.height() - m)
        super().resizeEvent(e)
```

Điểm dễ quên: overlay phải đặt `setAttribute(Qt.WA_TransparentForMouseEvents)` nếu
bạn muốn click **xuyên qua** chúng tới map (ví dụ click map để goto). Nếu overlay
cần nhận click riêng thì để mặc định.

---

### 7.8. Cơ chế gửi lệnh — hai đường, hai kiểu hoàn toàn khác nhau

Đây là phần dễ viết sai nhất vì hai đường lệnh **trông giống nhau ở tầng UI**
(đều là một cái nút) nhưng cơ chế bên dưới khác hẳn nhau.

| | **Đường SiK** | **Đường Remote** |
|---|---|---|
| Giao thức | MAVLink qua serial | Envelope JSON qua WebSocket |
| Kiểu gọi | Đồng bộ — ghi xong là xong | Bất đồng bộ — phải đợi ack |
| Chặng trung gian | Không | `bridge_node` trên companion |
| Biết lệnh có ăn không? | `COMMAND_ACK` về sau, rời rạc | Ack kèm `id` trong cùng envelope |
| Mất WiFi giữa chừng | Không ảnh hưởng | Lệnh treo → timeout |
| Dùng cho | ARM, mode, takeoff, **nút đỏ** | Đổi task ROS2, authority, param |

> ⚠️ **`dispatch()` ở Phase N3 trả về kết quả ngay — điều đó chỉ đúng với đường
> SiK.** Đường ROS2 không thể trả kết quả ngay được, vì kết quả nằm bên kia sóng
> WiFi. Đừng viết `dispatch()` như thể hai đường giống nhau; hãy để nó trả về
> `id` của lệnh, còn kết quả đến sau bằng Qt signal.

#### 7.8.1. Chuỗi đầy đủ của một lần đổi task

```
[Nut WAYPOINT]                                    GUI thread
   |
   +-> dispatch()                    kiem tra AUTHORITY, sinh id = "c18"
   +-> RemoteAdapter.send(env)       dat vao hang doi, TRA VE NGAY
   +-> nut tu khoa, hien "dang gui..."
          |
          |  QThread + asyncio loop
          v
       WebSocket  {"id":"c18","target":"ros2","action":"set_task",
                   "args":{"task":"WAYPOINT"}}
- - - - - - - - - - - - -  WiFi  - - - - - - - - - - - - -
[bridge_node]                                     companion, rclpy
   |
   +-> tra bang ACTIONS -> service /mission/set_task
   +-> cli.call_async(SetTask)
   +-> task_manager doi active_task, bat dau stream setpoint moi
   |
   <-- {"id":"c18","ok":true,"message":"Da chuyen sang WAYPOINT"}
- - - - - - - - - - - - -  WiFi  - - - - - - - - - - - - -
       RemoteAdapter nhan, tra bang PENDING theo id
   +-> phat Qt signal ack_received(id, ok, message)
   +-> nut mo khoa, hien ket qua
```

Bảy chặng, ba tiến trình, hai lần qua sóng WiFi. **Chỗ nào cũng có thể đứt** — đó
là lý do phải có `id` và timeout, không thể "gửi rồi tin là xong".

#### 7.8.2. Vì sao bắt buộc phải có `id`

Bấm `WAYPOINT` rồi đổi ý bấm `HOVER` ngay sau đó. Hai lệnh cùng bay trên dây. Ack
về không theo thứ tự (bridge xử lý song song, hoặc gói bị gửi lại). Không có `id`
thì bạn ghép ack đầu tiên vào lệnh thứ hai — GUI báo "HOVER thành công" trong khi
thứ thực sự thành công là `WAYPOINT`.

`id` chỉ cần là số đếm tăng dần trong phiên: `c1`, `c2`, `c3`. Không cần UUID.

#### 7.8.3. Bảng lệnh chờ và timeout

`remote.py` giữ một dict lệnh đang bay:

```python
PENDING = {}          # id -> {"action": str, "deadline": float}
TIMEOUT = 3.0         # giay

def send(self, env):
    env["id"] = self._next_id()
    env["ts"] = time.time()
    PENDING[env["id"]] = {"action": env["action"],
                          "deadline": time.time() + TIMEOUT}
    asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(env)), self._loop)
    return env["id"]

def _sweep(self):                      # QTimer 200 ms tren main thread
    now = time.time()
    for cid in [c for c, p in PENDING.items() if p["deadline"] < now]:
        p = PENDING.pop(cid)
        self.ack_received.emit(cid, False, f"Qua han: {p['action']}")
```

> 🚫 **Không tự động gửi lại.** Timeout nghĩa là *không biết* lệnh đã tới hay
> chưa, không phải *biết là chưa tới*. Gửi lại `set_task` thì vô hại vì nó
> idempotent, nhưng gửi lại `takeoff` thì có thể cất cánh hai lần. Quy tắc chung:
> báo lỗi cho người dùng, để họ quyết định bấm lại.

#### 7.8.4. Bẫy Qt × asyncio — chỗ sinh crash ngẫu nhiên

Đây là biến thể của rủi ro #2 trong mục 5.1, nhưng nguy hiểm hơn vì nó xảy ra ở
**cả hai chiều**:

| Chiều | Sai | Đúng |
|---|---|---|
| GUI → WebSocket | Gọi thẳng `ws.send()` từ slot của nút | `asyncio.run_coroutine_threadsafe(..., loop)` |
| WebSocket → GUI | Gọi `label.setText()` trong callback WebSocket | Phát Qt signal, main thread nhận |

`websockets` chạy trên asyncio loop của riêng nó trong `QThread`. Đụng vào loop đó
từ GUI thread mà không qua `run_coroutine_threadsafe` sẽ hỏng theo kiểu không tái
hiện được — đúng triệu chứng "crash sau vài phút" đã ghi ở mục 6.7.

#### 7.8.5. `bridge_node.py` trên companion

Node này là thứ **duy nhất** ở phía drone được phép nhận lệnh từ laptop. Nó chỉ
làm một việc: tra bảng và gọi tiếp. Không có logic bay nào ở đây.

```python
ACTIONS = {
    "set_task":      ("service", "/mission/set_task", SetTask),
    "set_authority": ("topic",   "/gcs/authority",    String),
}

async def handle(self, raw):
    env = json.loads(raw)
    kind = ACTIONS.get(env["action"])
    if kind is None:
        return {"id": env["id"], "ok": False, "message": "Lenh khong biet"}

    if kind[0] == "topic":
        self._pubs[env["action"]].publish(String(data=env["args"]["owner"]))
        return {"id": env["id"], "ok": True, "message": "Da publish"}

    fut = self._clis[env["action"]].call_async(self._build_req(env))
    try:
        res = await asyncio.wait_for(_wrap(fut), timeout=2.0)
    except asyncio.TimeoutError:
        return {"id": env["id"], "ok": False, "message": "Service khong tra loi"}
    return {"id": env["id"], "ok": res.success, "message": res.message}
```

Ba điều bắt buộc ở node này:

- **Bảng trắng, không phải bảng đen.** `ACTIONS` liệt kê thứ được phép; mọi thứ
  khác bị từ chối. Đừng bao giờ để bridge nhận tên topic/service tuỳ ý từ dây —
  đó là lỗ hổng cho phép laptop (hoặc bất kỳ ai vào được WiFi) gọi mọi thứ trong
  ROS graph.
- **Timeout riêng ở phía companion** (2 s). Nếu `task_manager` chết, bridge phải
  trả lời "không tra lời" thay vì để laptop đợi tới hết 3 s của nó.
- **Chạy `MultiThreadedExecutor`,** hoặc đặt client vào `ReentrantCallbackGroup`.
  Gọi service từ trong callback của một `SingleThreadedExecutor` sẽ deadlock.

#### 7.8.6. Vì sao service, không phải topic

Cho việc đổi task, service là lựa chọn đúng:

| | Topic | Service |
|---|---|---|
| Biết bên kia đã nhận? | Không | Có |
| Từ chối được tên task sai? | Không | Có |
| Lệnh gửi trước khi discovery xong | **Mất im lặng** | Báo lỗi rõ |

Cái bẫy ở hàng cuối là thứ tốn nhiều giờ debug nhất: publish ngay sau khi tạo
publisher thì gói đầu tiên biến mất, vì DDS chưa bắt tay xong với subscriber.
Service không có vấn đề này — nó báo lỗi thay vì im lặng.

**Khi nào cần Action thay vì Service:** khi lệnh chạy lâu và bạn muốn xem tiến độ
(bay hết một mission 12 waypoint) hoặc muốn huỷ giữa chừng. Hiện tại `set_task`
trả lời tức thì — nó chỉ đổi một biến — nên service là đủ và đơn giản hơn nhiều.

#### 7.8.7. Nút bấm trong lúc chờ

- Khoá **đúng nút vừa bấm**, không khoá cả tab. Người dùng vẫn phải bấm được nút
  khác trong khi một lệnh đang bay
- **Không dùng `QMessageBox` hay bất cứ dialog chặn nào** trong lúc chờ — nó đóng
  băng vòng lặp sự kiện, và bạn sẽ không bấm được nút đỏ
- Ack trễ về sau khi đã timeout thì **bỏ qua, chỉ ghi log**. Đừng mở lại nút hay
  đổi trạng thái theo một ack đã hết hạn

#### 7.8.8. Ranh giới an toàn của cơ chế này

Toàn bộ mục 7.8 nói về **đường Remote**. Nút đỏ không dính dáng gì tới nó: không
có `id`, không có bảng chờ, không có bridge, không có timeout — ghi thẳng MAVLink
xuống serial (mục 2.1).

Còn một câu hỏi thiết kế phải trả lời dứt khoát, vì nó quyết định drone làm gì khi
WiFi rớt:

> **Có nên cho `task_manager` tự chuyển về `IDLE` khi mất heartbeat từ GCS không?**

Hai lựa chọn, đều có lý:

- **Không (mặc định).** Task tự hành chạy tiếp đúng như kịch bản hỏng kiểu A ở mục
  1.3. Mission vision hoàn thành được dù bạn mất quan sát. Việc kéo drone về là
  của nút đỏ qua SiK — đường không bao giờ chết.
- **Có.** An toàn hơn theo nghĩa "mất liên lạc thì dừng", nhưng biến một sự cố
  mạng thành **thay đổi hành vi bay**. Với mission tự hành bay xa khỏi vùng WiFi
  thì đây là hành vi sai — drone sẽ tự dừng ngay chỗ nó vừa ra khỏi tầm sóng.

Chốt: **mặc định không bật**, vì kiến trúc này đã có đường SiK độc lập làm nhiệm
vụ đó. Nếu sau này bật, phải ghi rõ vào `docs/operating_procedure.md` và thêm một
kịch bản hỏng vào bảng mục Phase N5 — người bay phải biết trước drone sẽ làm gì.

---

*Tài liệu sống — cập nhật sau mỗi phase khi thực tế khác dự toán.*
