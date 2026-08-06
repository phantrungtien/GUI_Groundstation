# Dựng camera trên Pi5 — checklist

Mục tiêu: webcam USB cắm vào Pi5 → GUI trên laptop xem được, ở tab **Camera** và ô
PiP trên tab **Flight**.

> ✅ **Đã chạy thật ngày 06/08/2026.** Pi5 `hoaibac@192.168.1.113`, Ubuntu 24.04.4
> aarch64, webcam Rapoo. Sau khi đưa Pi lên **5 GHz**: **16,3 fps, 5,75 Mbps**,
> p50 61 ms, p90 98 ms, đỉnh 615 ms, **0 lần ô xám** — chạy thẳng mọi khung, không
> cần `--every`. Mọi lệnh dưới đây đã chạy qua.
>
> ⚠️ **Bài học lớn nhất của ngày dựng: nghẽn nằm ở WiFi của Pi, không ở camera và
> không ở code.** Lúc Pi còn ở 2,4 GHz thì video giật, 9,1 fps, đỉnh 1,4 giây và
> thỉnh thoảng rơi vào ô xám. Camera từ đầu tới cuối vẫn chạy **16,0 fps với max
> 68 ms** — gần như không lệch. Đừng vặn tham số server trước khi đo đường truyền;
> xem mục 7.

Mã nguồn server nằm ở `~/GUI_NATIVE/tools/mjpeg_server.py`. **Không copy sang đây** —
một bản duy nhất, tránh hai bản lệch nhau. File này chỉ là quy trình dựng.

```
Pi5  /dev/video0 ──► mjpeg_server.py ──► HTTP :8080 ──┐
                                                       │ WiFi (TCP riêng)
Laptop  GUI ◄── VideoSource ◄──────────────────────────┘
```

Cổng 8080 **tách hẳn** khỏi 8765 của đường lệnh ROS2 và khỏi SiK. Video chết thì
chỉ mất video — nút đỏ đi đường SiK, không liên quan.

---

## 0. Nên chạy trong Docker hay chạy thẳng trên Pi?

**Đề xuất: chạy thẳng trên host Pi5, ít nhất cho lần thử đầu.**

Lý do cụ thể chứ không phải nguyên tắc chung: `mjpeg_server.py` hôm nay **không
dùng ROS2 gì cả** — chỉ `cv2` + `http.server` của stdlib. Và `--device` thì
**không thêm được vào container đang chạy**, muốn có camera là phải xoá đi tạo
lại container ROS2 mà bạn đã dựng xong. Đổi lấy việc gì? Không việc gì.

Docker đáng vào **khi lên RealSense**, lúc đó server mới cần `cv_bridge` và cần
sống chung với ROS2. Mục 5 để sẵn cách làm cho hôm đó.

Đã kiểm 06/08: hai image có sẵn trên Pi (`ardu_ros:rviz-camera-ready` và
`ros:humble-ros-base`) **đều chưa có `cv2`**, nên đi đường Docker hôm nay vẫn phải
build image mới — không đỡ được việc gì so với cài thẳng trên host.

---

## 1. Trên Pi5 — tìm đúng cổng camera

`v4l-utils` cần sudo để cài. Đọc thẳng sysfs thì **không cần cài gì**:

```bash
for d in /sys/class/video4linux/video*; do
  printf "%-16s %s\n" "/dev/$(basename $d)" "$(cat $d/name)"
done
```

Trên Pi5 sẽ ra rất nhiều node — đừng hoảng. `rpivid` và `pispbe-*` là ISP/codec
của chính Pi5, **không phải camera**. Máy đã dựng cho ra:

```
/dev/video0   Rapoo  camera: Rapoo  camera     <- luong anh
/dev/video1   Rapoo  camera: Rapoo  camera
/dev/video2   Rapoo  camera: Rapoo  camera
/dev/video3   Rapoo  camera: Rapoo  camera
/dev/video19  rpivid                            <- codec Pi5, bo qua
/dev/video20+ pispbe-*                          <- ISP Pi5, bo qua
```

⚠️ **Bẫy đã gặp thật:** một webcam UVC hiện ra **nhiều** node cùng tên (ở đây là
bốn), nhưng chỉ **một** cái mở được. Ba cái kia là metadata — mở vào là không bao
giờ có khung hình mà cũng không báo lỗi rõ ràng. Đừng đoán, cứ thử hết:

```bash
python3 - <<'EOF'
import cv2
for i in range(4):
    dev = f"/dev/video{i}"
    c = cv2.VideoCapture(dev)
    ok, f = (c.read() if c.isOpened() else (False, None))
    print(dev, "mo" if c.isOpened() else "KHONG mo", "| doc:", ok,
          f"{f.shape[1]}x{f.shape[0]}" if ok else "")
    c.release()
EOF
```

Máy đã dựng: chỉ `/dev/video0` cho `doc: True 640x480`.

Xem camera có sẵn MJPG không (có thì webcam tự nén, Pi đỡ tốn CPU):

```bash
v4l2-ctl -d /dev/video0 --list-formats-ext | head -30
```

Thử đọc một khung, chưa cần server:

```bash
python3 -c "import cv2; c=cv2.VideoCapture('/dev/video0'); print('mo duoc:', c.isOpened(), '| doc duoc:', c.read()[0])"
```

Phải in ra `True True`. Chưa được thì dừng ở đây, mục 6 có cách gỡ.

---

## 2. Chạy server

Cần OpenCV. `sudo apt install python3-opencv` là cách sạch nhất **nếu bạn gõ được
mật khẩu sudo**. Không có sudo thì pip cũng xong, có wheel aarch64 sẵn nên không
phải build:

```bash
python3 -m pip install --user --break-system-packages opencv-python-headless
```

`--break-system-packages` là bắt buộc trên Ubuntu 24.04 (PEP 668). Dùng bản
`headless` vì server không cần `imshow` — nhẹ hơn, vẫn đủ `VideoCapture` +
`imencode`. Máy đã dựng ra `opencv-python-headless 5.0.0.93` + `numpy 2.5.1`.

Chép server từ laptop sang:

```bash
# CHAY TREN LAPTOP
scp ~/GUI_NATIVE/tools/mjpeg_server.py <user>@<ip-pi>:~/
```

Chạy:

```bash
# CHAY TREN PI
python3 ~/mjpeg_server.py --device /dev/video0
```

Chạy nền, không chết khi đóng SSH:

```bash
setsid nohup python3 ~/mjpeg_server.py --device /dev/video0 \
  </dev/null >~/mjpeg.log 2>&1 &
```

⚠️ **Bẫy đã cắn thật:** muốn tắt server thì **đừng** `pkill -f mjpeg_server` qua
SSH — chuỗi lệnh SSH cũng chứa chữ đó nên `pkill` giết luôn chính nó, và bạn nhận
được `exit 255` không hiểu vì sao. Neo đầu dòng:

```bash
pkill -f "^python3 /home/<user>/mjpeg_server.py"
```

Phải thấy:

```
[mjpeg] http://0.0.0.0:8080/stream
[mjpeg] mo /dev/video0 640x480, gui 1/1 khung
```

Tham số: `--width --height --every --quality --port`.

**`--every` thưa nhịp theo SỐ ĐẾM khung, cố ý không theo đồng hồ.** Chỗ này đã
sai một lần và đáng ghi lại: bản đầu thưa nhịp bằng `time.monotonic()` với chu kỳ
100 ms, trong khi camera trả khung mỗi 67 ms — hai nhịp đập nhau sinh phách, khung
đến sớm 1 ms bị vứt rồi phải đợi trọn chu kỳ sau. Đo được **9,1 fps tụt còn 2,5
fps**, p90 từ 250 ms vọt lên 939 ms, đỉnh **4,5 giây** — đủ để GUI lật sang ô xám
ba lần trong 25 giây. Đếm khung thì khoảng cách luôn là bội số chu kỳ camera, không
thể có phách.

Cũng **đừng đặt `CAP_PROP_FPS`**: đo trên Rapoo/Pi5, để mặc định được 16,0 fps
(p50 67 ms, max 68 ms); ép xuống 10 thì driver trả 7,0 fps và p90 vọt lên 200 ms.

Số đo cuối, 5 GHz `--every 1` q70: **16,3 fps, 5,75 Mbps**, khung ~43 KB, p50 61 ms,
p90 98 ms. Trên 2,4 GHz phải hạ xuống `--every 2` mới hết ô xám (7,2 fps, 2,49 Mbps)
— tức `--every` là **cái nạng cho đường truyền yếu**, sửa được mạng thì bỏ nó đi.
Thử `--quality 45` gần như vô dụng: khung chỉ nhẹ từ 40 xuống 36 KB mà p90 còn xấu
hơn, vì cảnh nhiều chi tiết thì JPEG không nén thêm được.

---

## 3. Kiểm chứng, theo đúng thứ tự này

Đừng nhảy cóc — sai ở bước nào thì biết ngay bước đó.

**a) Ngay trên Pi** (loại trừ mạng):

```bash
curl -s -m 3 http://127.0.0.1:8080/stream | head -c 200 | xxd | head -5
```

Phải thấy `--frame`, `Content-Type: image/jpeg`, rồi byte `ff d8` (mở đầu JPEG).

**b) Từ laptop** (loại trừ firewall / WiFi):

```bash
curl -s -m 3 http://<ip-pi>:8080/stream -o /dev/null -w "%{http_code} %{size_download} byte\n"
```

Mã `200` và số byte > 0 là đường truyền thông.

**c) Đo băng thông thật trên WiFi bãi bay** — đây mới là con số quan trọng, số
2,11 Mbps ở trên đo qua loopback nên không tính:

```bash
# CHAY TREN LAPTOP
python3 - <<'EOF'
import time, urllib.request
r = urllib.request.urlopen("http://<ip-pi>:8080/stream", timeout=5)
t0 = time.monotonic(); n = 0
while time.monotonic() - t0 < 10.0:
    b = r.read(65536)
    if not b: break
    n += len(b)
dt = time.monotonic() - t0
print(f"{n/dt/1024:.0f} KB/s = {n/dt*8/1e6:.2f} Mbps")
EOF
```

**d) Trong GUI.** Mở `~/GUI_NATIVE/config/connections.yaml`, bỏ comment và điền
IP thật của Pi ở profile `SiK radio` (**đã điền `192.168.1.113` ngày 06/08**):

```yaml
  remote: "ws://<ip-pi>:8765"
```

GUI suy địa chỉ video từ chính dòng này (`ws://x:8765` → `http://x:8080/stream`),
nên không có key config riêng cho video và không phải sửa thêm chỗ nào.

Chạy GUI, kết nối, mở tab **Camera**. Trên tab **Flight**, chuột phải lên bản đồ
→ **Hiện camera** để bật ô PiP.

> ⚠️ Dòng `remote:` bật **cả nửa ROS2**, không riêng video. Nếu lúc thử camera bạn
> chưa chạy `ros2_bridge.py` trên Pi thì banner sẽ báo `MAT ROS2` màu vàng — đúng
> chứ không phải lỗi, vì lúc đó nửa ROS2 im thật. Kệ nó, hoặc chạy bridge lên cho
> sạch màn hình.

---

## 4. Đo độ trễ đầu-cuối — không cần viết code

Mẹo cũ mà chuẩn:

1. Mở đồng hồ mili-giây trên màn hình laptop — `watch` không đủ nhanh, dùng vòng lặp:

   ```bash
   while :; do printf "\r%s" "$(date +%H:%M:%S.%3N)"; sleep 0.01; done
   ```

2. Chĩa webcam của Pi vào chính màn hình đó
3. Chụp màn hình laptop — trong ảnh sẽ có **hai** đồng hồ: cái thật, và cái nhìn
   thấy trong khung video

**Hiệu hai con số đó chính là độ trễ đầu-cuối.** Không cần đồng bộ giờ hai máy,
không cần thêm dòng code nào.

Ghi lại con số. Trên 300 ms thì hạ `--quality` hoặc tăng `--every` rồi đo lại.

---

## 5. Sau này: Docker + RealSense

Hôm lên D435i, server mới cần ROS2. Lúc đó `cv_bridge` vào đúng **một chỗ** trong
`grab()` — đổi `cap.read()` thành `bridge.imgmsg_to_cv2(msg, "bgr8")`, từ đó trở
xuống không đổi gì, và **GUI không sửa một ký tự nào**. Đó là lý do ranh giới đặt
ở HTTP chứ không đặt ở DDS.

Dockerfile tối thiểu cho hôm đó:

```dockerfile
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y python3-opencv && rm -rf /var/lib/apt/lists/*
COPY mjpeg_server.py /app/
WORKDIR /app
CMD ["python3", "mjpeg_server.py"]
```

```bash
docker build -t gcs-camera .
docker run -d --restart unless-stopped --name gcs-camera \
  --device=/dev/video0 -p 8080:8080 gcs-camera
```

Hai cờ bắt buộc, thiếu cái nào cũng hỏng im lặng: `--device=/dev/video0` (không
có thì container không thấy camera) và `-p 8080:8080` (không có thì laptop không
gọi tới được).

---

## 6. Trục trặc

| Hiện tượng | Nguyên nhân hay gặp |
|---|---|
| `mo duoc: False` | Sai node — thử `/dev/video1`, `/dev/video2`. Hoặc thiếu quyền: `sudo usermod -aG video $USER` rồi **đăng xuất đăng nhập lại** |
| Mở được nhưng `doc duoc: False` | Tiến trình khác đang giữ camera. `sudo fuser -v /dev/video0` |
| Trên Pi curl được, laptop không | Firewall (`sudo ufw allow 8080`), hoặc hai máy khác mạng, hoặc AP bật isolation |
| GUI hiện ô xám "khong co video" | Server chưa chạy, hoặc `remote:` trong `connections.yaml` sai IP |
| GUI hiện ô xám "mat video" | Đã từng có khung rồi mất — WiFi rớt hoặc camera tuột. Ô xám là **cố ý**, không bao giờ đóng băng khung cuối vì nhìn khung cũ tưởng đang sống là kiểu nguy hiểm nhất |
| fps thấp, khung giật | Gần như luôn là **đường truyền**, không phải camera. Đo trần thật: `ssh pi 'dd if=/dev/zero bs=1M count=20' \| dd of=/dev/null`. Dưới ~1 MB/s thì tăng `--every` cho vừa, và xem mục 7 |
| Pi biến mất khỏi mạng, máy vẫn chạy | WiFi power save. Xem mục 7 |
| Độ trễ trôi dần, càng xem càng trễ | Đáng lẽ không xảy ra — `CAP_PROP_BUFFERSIZE=1` và server luôn gửi khung mới nhất. Gặp thì báo, đó là bug thật |

---

## Ghi chú

- IP Pi muốn cố định vĩnh viễn thì làm **DHCP reservation trên router** theo MAC.
  0 dòng code, cấu hình một lần, hơn hẳn đi dò IP.
- Video **chỉ chạy trên nửa WiFi**. SiK (~470–3200 B/s) không đủ cho một khung
  JPEG 26 KB, và cũng không được phép đụng vào — đó là đường của nút đỏ.

---

## 7. WiFi của Pi — chỗ quyết định chất lượng video

Hai thứ đã cắn thật trong ngày dựng, cả hai đều ở phía mạng chứ không ở code.

**a) Power save làm Pi rụng khỏi mạng.** Ubuntu ship sẵn
`/etc/NetworkManager/conf.d/default-wifi-powersave-on.conf` với `wifi.powersave = 3`
(bật). Chip WiFi ngủ rồi không dậy: máy vẫn chạy, camera vẫn sáng đèn, nhưng biến
mất khỏi mạng và **không tự nối lại**. Đã xảy ra lúc 22:50 ngày 06/08.

Đã ghi đè bằng `/etc/NetworkManager/conf.d/zz-powersave-off.conf` (`zz` để sắp sau
file mặc định và thắng nó):

```ini
[connection]
wifi.powersave = 2
```

NetworkManager **không đổi nóng** được thiết lập này (`Can't reapply changes to
'802-11-wireless.powersave'`) — nó có hiệu lực ở lần kết nối WiFi kế tiếp hoặc sau
khi khởi động lại. Kiểm bằng:

```bash
nmcli -t -f 802-11-wireless.powersave connection show <ten-mang>   # phai la: disable
```

Với máy tính nhúng trên drone đây không phải phiền toái mà là lỗi phải diệt: rụng
WiFi giữa chuyến bay là mất video, mất telemetry ROS2, mất đường lệnh nhiệm vụ.

**b) Pi bám 2,4 GHz dù thấy 5 GHz — đây là thứ làm video giật.**

```
2,4 GHz (kenh 4) : tin hieu -55 dBm (MANH) | rx  26 / tx  52 Mbit/s
5 GHz  (5300MHz) : tin hieu -64 dBm (yeu hon 9 dB) | rx 117 / tx 175 Mbit/s
```

Bẫy ở đây: **tín hiệu mạnh hơn không có nghĩa là nhanh hơn.** Băng 2,4 GHz quét ra
**14 AP** chen nhau nên rate tụt xuống 26 Mbit/s; 5 GHz tuy yếu hơn 9 dB nhưng
vắng, cho gấp 4,5 lần.

Hai giả thuyết sai đã loại trên đường tìm ra, ghi lại để khỏi đi lại:
- *Regulatory domain chưa đặt* — sai, `iw reg get` cho `country VN` với đủ băng
  5150–5850.
- *Pi không thấy AP 5 GHz* — sai, `iw dev wlan0 scan` thấy **10 AP 5 GHz**. Lúc
  đầu nhầm vì `nmcli dev wifi list` **gộp theo SSID**, chỉ hiện một dòng 2,4 GHz.
  Muốn thấy đủ phải dùng `iw ... scan`, không dùng `nmcli`.

Ép sang 5 GHz và ghim lại (sống qua reboot):

```bash
sudo nmcli connection modify <ten-mang> 802-11-wireless.band a
sudo nmcli connection up <ten-mang>          # rot ~10s roi len lai
iw dev wlan0 link | grep -E "freq|bitrate"   # phai thay freq 5xxx
```

⚠️ Lệnh `up` **cắt mạng vài giây**. Làm qua SSH thì nên bọc trong script `setsid`
có tự lùi về `band ""` nếu 25 giây không lên được — không thì hỏng là mất luôn Pi.

Lên 5 GHz rồi thì bỏ `--every`, chạy full 16 fps.
