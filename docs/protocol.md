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

> ⚠️ `link` do adapter **tu sinh moi giay**, khong phai bang chung link con song.
> Widget nao do "lan cuoi thay du lieu" phai bo qua topic nay, neu khong se khong
> bao gio phat hien mat song.

## Ra drone

```python
{"target": "sik", "action": "rtl", "args": {}}
```

`action`: `arm` · `disarm` · `mode` (`{"name": "GUIDED"}`) · `takeoff` (`{"alt": 5}`)
· `rtl` · `land` · `goto` (`{"lat", "lon", "alt"}`).

`rtl` / `land` / `disarm` nam trong tap **ESCAPE**: chung di thang toi `sik`,
khong qua kiem tra quyen, khong qua companion. Xem `core/authority.py`.
