# Dac ta envelope

Dung chung giua ban native va ban web. Moi thu chay tren bus deu la mot envelope.

```python
{"src": "sik", "topic": "position", "data": {...}, "ts": 1721000000.123}
```

| Truong | Kieu | Y nghia |
|---|---|---|
| `src` | str | Nguon: `sik`, `remote`. Them duong thu ba thi them chuoi moi |
| `topic` | str | Xem bang duoi |
| `data` | dict | Da doi don vi va da chuan hoa ve ENU |
| `ts` | float | Unix epoch giay, dat luc adapter nhan goi |

Nho co `src`, UI hien `Lat 10.762 (sik)` canh `Lat 10.763 (remote)` ma khong nham.

## Quy uoc don vi

| | |
|---|---|
| Goc | radian (tru `heading`: **do**, 0–360 tinh tu huong bac) |
| Khoang cach, do cao | met |
| Van toc | m/s |
| Toa do | **ENU** — x dong, y bac, z **len** |
| lat/lon | do thap phan |
| Khong co du lieu | `None`, khong phai `0` va khong phai `65535` |

> Chuan hoa NED -> ENU lam ngay tai `core/adapters/sik.py`. Tang UI khong duoc
> biet ben duoi la NED hay ENU (Phu luc 7.3 cua ke hoach).

## Topic

| Topic | Field | Tu message |
|---|---|---|
| `position` | `lat` `lon` `alt_msl` `alt_rel` `v_e` `v_n` `v_u` `heading` | GLOBAL_POSITION_INT |
| `attitude` | `roll` `pitch` `yaw` `heading` `rollspeed` `pitchspeed` | ATTITUDE |
| `local` | `x_e` `y_n` `z_u` | LOCAL_POSITION_NED |
| `vfr` | `airspeed` `groundspeed` `throttle` `climb` | VFR_HUD |
| `battery` | `voltage` `current` `remaining` | SYS_STATUS |
| `gps` | `fix_type` `sats` `hdop` | GPS_RAW_INT |
| `text` | `severity` `text` | STATUSTEXT |
| `heartbeat` | `armed` `mode` `type` | HEARTBEAT |
| `home` | `lat` `lon` `alt_msl` | HOME_POSITION |
| `fence` | `FENCE_*` (tham so), `items` (dinh da giac), `err` | PARAM_VALUE + MISSION_ITEM_INT |
| `wp` | `items` (duong bay), `total` (so muc FC co), `seq` (dang bay toi) | MISSION_COUNT + MISSION_ITEM_INT + MISSION_CURRENT |
| `ack` | `command` `result` (MAV_RESULT) | COMMAND_ACK |
| `status` | `{"MSG.field": so}` — moi field so cua **moi** message | tat ca |
| `cmd` | `action` `args` — lenh vua gui di | adapter tu sinh |
| `link` | `bps` `mode`, va `eof` khi het file REPLAY | adapter tu sinh |

Nua ROS2 (`src: "remote"`) gui envelope JSON y het dinh dang tren qua WebSocket.
Truong `src` cua no bi ghi de thanh `"remote"` khi vao app: companion khong duoc
tu xung la nguon khac, neu khong thi trong tai da nguon va widget Link status
deu bi danh lua.

> ⚠️ `ack` la duong duy nhat biet FC co **tu choi** lenh hay khong. "Da gui"
> khong co nghia la "da lam".

`yaw` la goc ENU (0 = huong dong, nguoc chieu kim dong ho). `heading` la do tu
huong bac theo chieu kim dong ho — dung cho la ban, khong phu thuoc he toa do.

> ⚠️ `home` va `fence` khong phai dai luong lien tuc: FC **khong tu gui**, adapter
> phai hoi (xem `_fence_ask`) va chung ve mot lan roi thoi. Ben nhan phai nghe bus
> truc tiep, dung doc qua `core/field.py` — o do qua 2 giay la coi nhu het tuoi.
> `items` la `[(command, param1, lat, lon)]`: `5001/5002` la dinh da giac
> trong/cam, `5003/5004` la vong tron (`param1` = ban kinh met).

> ⚠️ `wp` cung phai hoi nhu `fence`, va ve lam **hai nhip khac han nhau**:
> `items` = `[(seq, command, lat, lon, alt)]` ve dung mot lan sau khi tai xong,
> con `seq` (waypoint dang bay TOI) ve deu deu suot chuyen. Ben nhan phai **gop**
> vao cung mot dict, dung thay the — nhan mot goi `MISSION_CURRENT` ma xoa mat
> danh sach diem thi duong bay bien khoi ban do giua chuyen AUTO.
>
> Adapter cat o **`WP_MAX` = 50 muc**: nhiem vu dai hon thi `total` (so FC bao)
> lon hon `len(items)`, va ban do phai noi ro la da cat. Muc khong mang toa do
> (`DO_*`, `NAV_TAKEOFF` de trong) co `lat = lon = 0` — ve chung thi duong bay
> keo mot net ra dao Null; xem `map_widget.wp_points()`.
>
> Do that tren ArduCopter SITL (loopback TCP, 11/08/2026): nap 50 muc roi mo
> cong, adapter tai du 50 muc trong **0,6 s** (2474 B/s); nhiem vu 80 muc thi
> tai 50 muc trong **0,5 s** va bao `total = 80`. Day la so cua **TCP loopback**,
> khong phai SiK — tren radio 57600 that thi phai do lai.

> ⚠️ `link` do adapter **tu sinh moi giay**, khong phai bang chung link con song.
> Widget nao do "lan cuoi thay du lieu" phai bo qua topic nay, neu khong se khong
> bao gio phat hien mat song.

## Ra drone

```python
{"target": "sik", "action": "rtl", "args": {}}
```

`action`: `arm` · `disarm` · `mode` (`{"name": "GUIDED"}`) · `takeoff` (`{"alt": 5}`)
· `rtl` · `land` · `goto` (`{"lat", "lon", "alt"}`) · `wp_write`
(`{"items": [[lat, lon, alt], ...]}`) · `wp_clear`.

`rtl` / `land` / `disarm` nam trong tap **ESCAPE**: chung di thang toi `sik`,
khong qua companion, khong qua nhanh nao khac. Xem `core/authority.py`.

> ⚠️ Laptop cam **toan quyen**: khong con `set_authority`, khong con MANUAL/AUTO.
> `/gcs/authority` chot o `"gcs"` ngay luc `ros2_bridge.py` khoi dong va khong doi
> duoc — node offboard tren companion khong bao gio lai duoc. Nua ROS2 chi con la
> nguon telemetry. Lenh `authority` gui sang bridge bi **tu choi to**, khong im lang.

### Nap duong bay (chieu ghi)

Chi co o ban native tren laptop. `RemoteAdapter` khong co `wp_write` — mot nhiem
vu tren FC chi den tu mot cho.

| | |
|---|---|
| Tran | `WP_MAX` = **50 waypoint**; muc 0 (home) do adapter tu chen -> 51 muc tren day |
| Nhip | FC dan: no xin tung muc (`MISSION_REQUEST[_INT]`), app tra tung muc |
| Gui lai | FC im qua `WP_UP_RETRY` = 2 s -> gui lai `MISSION_COUNT`, toi da `WP_UP_TRIES` = 5 lan |
| Xong | `MISSION_ACK` -> envelope `wp` co khoa `write`: `{ok, result, n}` (hoac `err`) |
| Doi chieu | Nap xong app **xoa danh sach cu va doc lai tu FC** — cai ve tren ban do la cai FC dang giu |

Do that tren ArduCopter SITL (loopback TCP, 11/08/2026): dat 50 waypoint roi nap
— FC nhan sau **0,4 s** (`result=0`), doc lai duoc **51 muc** sau **2,1 s** tinh
tu luc bam, ca 50 toa do va do cao khop tuyet doi. `wp_clear` -> doc lai 0 muc.

`disarm` nhan them `{"force": True}` -> gui magic 21196. Khong co no thi
ArduCopter tu choi disarm tu GCS bat cu khi nao `land_complete` sai
(`ArduCopter/AP_Arming.cpp:788`). Do tren FC that: drone nam im (ga min, motor
1000) thi lenh thuong AN; ga giua tam, motor quay lech nhau de on dinh tu the
thi `ack=4` 3/3 lan, con force an ngay lan dau.

Nen app chon `force` theo DANG O DUOI DAT HAY KHONG chu khong theo can ga: duoi
dat thi bam mot phat la force — ga o muc nao cung ngat duoc. Dang bay, hoac khong
biet (mat telemetry), bam mot phat chi ra lenh thuong; muon force thi phai giu
nut 2 giay.

Cau hoi "duoi dat chua" KHONG duoc suy tu `position.alt_rel`: GPS fix 0 thi no
doc -8.5 m suot 10 giay trong khi may bay treo yen va rangefinder noi 0.6 m.
`_on_ground()` hoi hai nguon doc lap, nguon nao noi "duoi dat" cung du:

| Nguon | Message | Gioi han |
|---|---|---|
| `heartbeat.landed` | `EXTENDED_SYS_STATE.landed_state` (245) | lat sang IN_AIR ngay khi ga roi min, ke ca luc may bay dang treo tren thanh |
| khoang cach ≤ `RNG_GROUND_CM` | `DISTANCE_SENSOR` | chi tin khi nam trong `[min_distance, max_distance]` cua chinh cam bien |

`EXTENDED_SYS_STATE` khong nam trong bo `MAV_DATA_STREAM` nao — `SikAdapter` xin
rieng bang `MAV_CMD_SET_MESSAGE_INTERVAL` @ `LANDED_HZ` = 2 Hz. Do that: 0 goi
trong 8 s truoc khi xin, 17 goi sau khi xin.

Goi 245 do ve chung topic `heartbeat`, nen moi cho lam giau topic do bang thu chi
HEARTBEAT moi co (`mode_string_v10()` doi `.autopilot`) phai bam theo TEN MESSAGE
chu khong theo topic — neu khong luong doc chet ngay goi dau tien.

## Bang thong do that

`tools/measure_bandwidth.py <cong> <giay>` — xin dung bo `STREAMS` ma
`SikAdapter` xin, roi dem byte tren day theo tung loai message.

03/08/2026, MicoAir743 qua **USB** (`/dev/ttyACM0`), hai lan do 30 giay:

| | |
|---|---|
| Tong | **1895 / 1986 B/s** (~60 msg/s) |
| Uoc luong o phu luc 7.1 cua ke hoach | ~800 B/s |
| Nang nhat | `ATTITUDE` 399 B/s (21%), `AHRS2` 280 B/s (15%) |

Gap ~2,4 lan uoc luong. Phan chenh la nhung message khong ai o tang UI doc:
`AHRS2`, `MEMINFO`, `MCU_STATUS`, `TERRAIN_REPORT`, `WIND`, `OPTICAL_FLOW` — do
`RAW_SENSORS` va `EXTRA3` keo theo ca cum.

> ⚠️ Day la so cua **USB**, khong phai SiK. USB khong chat bang thong nen no chi
> noi "FC dinh gui bay nhieu". Suc cho that cua radio 57600 phai do lai tren
> `/dev/ttyUSB*` — chua lam.
