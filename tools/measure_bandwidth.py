#!/usr/bin/env python3
"""Do tai that cua duong truyen: byte/s va tan so tung loai message (muc N0).

    python3 tools/measure_bandwidth.py                 # 30s tren /dev/ttyACM0
    python3 tools/measure_bandwidth.py /dev/ttyUSB0 60 # radio SiK, 60s

Xin dung bo STREAMS ma SikAdapter xin — do stream mac dinh cua FC la do mot tai
khac voi tai app that su tao ra. Con so chi co nghia khi kem TEN CONG: ttyACM la
USB cam thang (mot con so tran tren, khong noi gi ve radio), ttyUSB moi la SiK.
"""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymavlink import mavutil  # noqa: E402

from core.adapters.sik import AUTOPILOT, STREAMS  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
BAUD = 57600

# 57600 baud, khung 8N1 = 10 bit/byte -> 5760 B/s tren day. Radio SiK khong dat
# duoc con so do: no con phai chia doi song cho hai chieu va chen ma sua loi.
WIRE = {"ttyACM": ("USB cam thang", None),
        "ttyUSB": ("radio SiK", 5760 * 0.7)}
kind, capacity = next((v for k, v in WIRE.items() if k in PORT), ("khong ro", None))


def main():
    m = mavutil.mavlink_connection(PORT, baud=BAUD, source_system=254)
    if not m.wait_heartbeat(timeout=15):
        sys.exit(f"khong thay heartbeat tren {PORT}")
    for sid, hz in STREAMS:
        m.mav.request_data_stream_send(m.target_system, AUTOPILOT, sid, hz, 1)
    time.sleep(2)  # cho FC doi nhip, dung tinh giai doan qua do vao ket qua
    while m.recv_match(blocking=False):
        pass

    n, size = Counter(), Counter()
    t0 = time.time()
    while time.time() - t0 < SECS:
        msg = m.recv_match(blocking=True, timeout=2)
        if msg is None or msg.get_type() == "BAD_DATA":
            continue
        n[msg.get_type()] += 1
        size[msg.get_type()] += len(msg.get_msgbuf())
    dt = time.time() - t0

    total = sum(size.values())
    print(f"\ncong {PORT}  ({kind})   do {dt:.1f}s   MAVLink v{m.WIRE_PROTOCOL_VERSION}\n")
    print(f"  {'message':<26}{'Hz':>7}{'B/s':>9}{'%':>7}")
    for name, b in size.most_common():
        print(f"  {name:<26}{n[name]/dt:>7.1f}{b/dt:>9.0f}{100*b/total:>7.1f}")
    print(f"  {'TONG':<26}{sum(n.values())/dt:>7.1f}{total/dt:>9.0f}")

    print(f"\n  uoc luong ke hoach (phu luc 7.1): ~800 B/s")
    print(f"  do that                          : {total/dt:.0f} B/s")
    if capacity:
        print(f"  suc cho {kind} 57600           : ~{capacity:.0f} B/s "
              f"-> dung {100*total/dt/capacity:.0f}%")
    else:
        print("  KHONG suy ra duoc gi ve SiK tu con so nay: USB khong gioi han bang\n"
              "  thong o day. Do lai tren /dev/ttyUSB* khi cam radio.")


if __name__ == "__main__":
    main()
