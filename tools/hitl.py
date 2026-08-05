#!/usr/bin/env python3
"""Nhung phep do CHI lam duoc tren phan cung that (muc 3, Phase N5).

Chay khi da cam FC qua USB, THAO CANH QUAT, va co RC bat san:

    python3 tools/hitl.py 12          # profile SIM cam vao FC that
    python3 tools/hitl.py 7           # app chet giua chung, FC giu nguyen mode
    python3 tools/hitl.py 7 --arm     # nhu tren nhung ARM truoc khi giet app
    python3 tools/hitl.py armcycle    # ARM/DISARM thuong: do tre, tu ngat, chan ga cao
    python3 tools/hitl.py disarm      # DISARM duoi dat: ngat duoc o moi muc ga

Bai nao co ARM deu doi nguoi bay giu ga o min, va deu tu ngat truoc khi thoat —
ke ca khi thoat vi assert. Muoi kich ban hong con lai khong can phan cung: chung
nam trong tools/selfcheck.py.
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = os.environ.get("HITL_PORT", "/dev/ttyACM0")
BAUD = int(os.environ.get("HITL_BAUD", "57600"))


def _mav(timeout=15):
    """Mo cong doc truc tiep, KHONG qua app — de doi chieu voi thu app noi."""
    from pymavlink import mavutil

    m = mavutil.mavlink_connection(PORT, baud=BAUD, source_system=254)
    if not m.wait_heartbeat(timeout=timeout):
        sys.exit(f"khong thay heartbeat tren {PORT} — cam FC vao chua?")
    return m


def armed_of(msg):
    from pymavlink import mavutil

    return bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)


# ---------------------------------------------------------------- kich ban 12
def kb12():
    """#12 — cam nguon THAT nhung chon profile SIM.

    Ky vong cua ke hoach: banner bam theo `mode` da chon, khong doan tu chuoi
    ket noi. Day la kieu hong nguy hiem theo chieu nguoc lai voi truc giac: neu
    app "thong minh" nhan ra /dev/ttyACM0 la do that roi tu ve mau do, nguoi bay
    hoc duoc rang mau banner dang tin — trong khi thu that su quyet dinh nut nao
    gui duoc di lai la `mode`. Xanh + lenh di xuong drone that la ket hop chet
    nguoi, nen no phai xanh, va phai xanh mot cach nhat quan.
    """
    from PySide6.QtWidgets import QApplication

    from laptop.app import MainWindow
    from laptop.connection import MODE_COLOR

    app = QApplication.instance() or QApplication([])
    prof = {"name": "SITL (that ra la FC that)", "mode": "SIM",
            "conn": PORT, "baud": BAUD, "sysid": 254}
    win = MainWindow([prof])
    win.panel.select(prof["name"])
    win.panel.btn_connect.click()

    t0 = time.time()
    while time.time() - t0 < 20 and win.banner._shown[0] == "WAIT":
        app.processEvents()
        time.sleep(0.05)

    mode, text = win.banner._shown
    rx = win.link_status.last_seen.get("sik")
    print(f"  banner   : mode={mode!r}  text={text!r}")
    print(f"  mau       : {MODE_COLOR[mode]}  (SIM={MODE_COLOR['SIM']}, REAL={MODE_COLOR['REAL']})")
    print(f"  byte that : co goi tu FC luc {rx and time.strftime('%H:%M:%S', time.localtime(rx))}")
    print(f"  tieu de   : {win.windowTitle()}")

    assert rx, "khong nhan duoc goi nao tu FC — bai test nay vo nghia neu link im"
    assert mode == "SIM", f"banner doan tu chuoi ket noi thay vi theo mode: {mode}"
    assert MODE_COLOR[mode] != MODE_COLOR["REAL"], "mau SIM trung mau REAL"
    assert win.windowTitle().startswith("[SIM]"), win.windowTitle()
    # Nut van song vi mode SIM la "dang chay" — do la CHU Y quan trong: chon nham
    # profile thi lenh van di xuong FC that. Banner la thu duy nhat noi ra dieu do.
    assert win.control_tab.btn_arm.isEnabled(), "SIM ma nut chet thi test sai cho"
    win.disconnect()
    win.close()
    print("  ok  #12: cam FC that + profile SIM -> banner van la SIM (theo mode, khong doan)")


# ----------------------------------------------------------------- kich ban 7
CHILD_READY = "HITL-CHILD-READY"


def _child(do_arm):
    """Chay TRONG tien trinh con: dung app that, noi that, roi cho bi giet."""
    from PySide6.QtWidgets import QApplication

    from laptop.app import MainWindow

    app = QApplication.instance() or QApplication([])
    prof = {"name": "FC that qua USB", "mode": "REAL",
            "conn": PORT, "baud": BAUD, "sysid": 254}
    win = MainWindow([prof])
    win.panel.select(prof["name"])
    win.panel.btn_connect.click()

    t0 = time.time()
    while time.time() - t0 < 20 and not win.link_status.last_seen.get("sik"):
        app.processEvents()
        time.sleep(0.05)

    if do_arm:
        r = win.control_tab._cmd("arm")  # y het nut ARM: control.py:99
        print("  con: gui ARM ->", r, flush=True)
        t0 = time.time()
        while time.time() - t0 < 6:
            app.processEvents()
            time.sleep(0.05)

    # Trang thai app NHIN THAY ngay truoc khi chet la moc so sanh dung. Lay moc
    # tu truoc khi ARM la so hai thoi diem khac nhau roi goi do la "FC tu doi".
    from core import bus

    state = {}
    bus.on("*", lambda e: state.update(e["data"]) if e["topic"] == "heartbeat" else None)
    t0 = time.time()
    while time.time() - t0 < 5 and "armed" not in state:
        app.processEvents()
        time.sleep(0.05)
    print(f"{CHILD_READY} armed={state.get('armed')}", flush=True)
    while True:  # cho cha giet — day la "app crash"
        app.processEvents()
        time.sleep(0.05)


def kb7(do_arm):
    """#7 — app chet giua chung. Ky vong: drone giu nguyen mode, khong roi.

    Giet bang SIGKILL: app khong co co hoi chay `disconnect()` hay bat ky doan
    don dep nao. Chay `win.close()` roi goi do la crash thi dang test nham thu.
    """
    m = _mav()
    hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
    before = (m.flightmode, armed_of(hb))
    print(f"  truoc  : mode={before[0]}  armed={before[1]}")
    if do_arm:
        # Doi ga ve min truoc khi ARM. KHONG phai vi FC bat buoc — do roi: FC arm
        # tuot voi ga 1496. Ma vi chinh app chan (THR_ARM_MAX), va vi arm o ga
        # giua tam la dong co quay len that.
        print("  >>> HA GA VE MIN VA GIU (~20s) — dang cho...", flush=True)
        t0 = time.time()
        while time.time() - t0 < 90:
            rc = m.recv_match(type="RC_CHANNELS", blocking=True, timeout=3)
            if rc and rc.chan3_raw < 1150:
                print(f"  ga = {rc.chan3_raw} — bat dau", flush=True)
                break
        else:
            sys.exit("ga khong ve min sau 90s — bo bai test")
    m.close()  # nhuong cong cho app con — mot cong USB chi mot tien trinh giu

    child = subprocess.Popen(
        [sys.executable, __file__, "--child"] + (["--arm"] if do_arm else []),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT,
    )
    t0 = time.time()
    child_armed = None
    for line in child.stdout:
        print("   ", line.rstrip())
        if CHILD_READY in line:
            child_armed = line.strip().split("armed=")[-1] == "True"
            break
        if time.time() - t0 > 60:
            child.kill()
            sys.exit("tien trinh con khong bao READY")
    # Con tu chet (loi import, Qt no) thi bai test do nghia khac han: dang do mot
    # vu crash khong phai vu minh dinh gay ra. Bat o day, dung de no troi qua.
    if child_armed is None:
        child.kill()
        sys.exit(f"tien trinh con chet truoc khi san sang (rc={child.poll()})")

    time.sleep(2)
    os.kill(child.pid, signal.SIGKILL)
    t_kill = time.time()
    child.wait(timeout=10)
    print(f"  ĐA GIET app (SIGKILL pid {child.pid}) luc {time.strftime('%H:%M:%S')}")

    m = _mav()
    print(f"  noi lai duoc sau {time.time() - t_kill:.1f}s — bat dau theo doi 15s")
    seen = []
    t0 = time.time()
    while time.time() - t0 < 15:
        hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=3)
        if not hb:
            continue
        now = (m.flightmode, armed_of(hb))
        if not seen or seen[-1][1:] != now:
            seen.append((round(time.time() - t_kill, 1),) + now)
    for t, mode, arm in seen:
        print(f"    +{t:4.1f}s  mode={mode:<10} armed={arm}")

    after = seen[-1][1:] if seen else None
    try:
        assert after, "khong doc duoc heartbeat nao sau khi app chet"
        assert len(seen) == 1, f"FC tu doi trang thai sau khi app chet: {seen}"
        assert after[0] == before[0], f"mode doi: {before[0]} -> {after[0]}"
        if child_armed is not None:
            assert after[1] == child_armed, f"armed doi: app thay {child_armed}, FC {after[1]}"
    finally:
        if after and after[1]:
            _disarm(m)
    m.close()
    print(f"  ok  #7: app bi SIGKILL, FC giu nguyen mode={after[0]} armed={after[1]} suot 15s")


def _disarm(m):
    """Tra FC ve disarmed. Thu duong thuong truoc — day chinh la duong nut do
    DISARM di (control.py:142 -> sik.py:342, khong co co `force`), nen ket qua
    cua no la mot phep do co gia tri, khong phai thu tuc don dep."""
    from pymavlink import mavutil

    for force in (0, 21196):
        for _ in range(3):
            m.mav.command_long_send(m.target_system, m.target_component,
                                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                                    0, 0, force, 0, 0, 0, 0, 0)
            ack = m.recv_match(type="COMMAND_ACK", blocking=True, timeout=3)
            print(f"  DISARM{' FORCE' if force else '':<6} ack = "
                  f"{ack.result if ack else 'khong co'}")
            for _ in range(6):  # FC noi ly do o STATUSTEXT, khong o ack
                t = m.recv_match(type="STATUSTEXT", blocking=False)
                if t:
                    print("    FC:", t.text)
            hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=3)
            if hb and not armed_of(hb):
                print("  -> da DISARM")
                return
    print("  !!! VAN CON ARMED — gat DISARM tren RC")


# ------------------------------------------------------ nut DISARM hai bac
def kb_disarm():
    """Bam nut DISARM that tren FC that, ca hai bac.

    Bac 1 (bam nhanh) DUOC PHEP that bai: ArduCopter tu choi disarm tu GCS khi
    `land_complete` sai. Cai phai dung la app noi ra su tu choi do — "da gui" ma
    im lang thi nguoi bay tuong dong co da tat.

    Bac 2 (giu 2 giay) thi phai that su cat duoc dong co.
    """
    from PySide6.QtWidgets import QApplication

    from core import bus
    from core.field import REGISTRY
    from laptop.app import MainWindow

    app = QApplication.instance() or QApplication([])
    prof = {"name": "FC that qua USB", "mode": "REAL",
            "conn": PORT, "baud": BAUD, "sysid": 254}
    win = MainWindow([prof])
    win.panel.select(prof["name"])
    win.panel.btn_connect.click()
    ct = win.control_tab
    logs = []
    ct.log.connect(logs.append)

    hb, rc = {}, {}
    bus.on("*", lambda e: hb.update(e["data"]) if e["topic"] == "heartbeat" else None)
    bus.on("*", lambda e: rc.update(e["data"]) if e["topic"] == "status" else None)

    def spin(secs, until=None):
        t0 = time.time()
        while time.time() - t0 < secs:
            app.processEvents()
            time.sleep(0.02)
            if until and until():
                return True
        return False

    spin(20, lambda: "armed" in hb)
    assert "armed" in hb, "khong nhan duoc heartbeat qua app"
    print(f"  ban dau: armed={hb['armed']}")

    print("  >>> HA GA VE MIN VA GIU (~25s) — dang cho...", flush=True)
    if not spin(90, lambda: (rc.get("RC_CHANNELS.chan3_raw") or 9999) < 1150):
        sys.exit("ga khong ve min sau 90s")
    print(f"  ga = {rc.get('RC_CHANNELS.chan3_raw')} — ARM", flush=True)

    logs.clear()
    ct.btn_arm.click()
    spin(6, lambda: hb.get("armed"))
    assert hb.get("armed"), f"khong ARM duoc: {logs}"
    print(f"  ARM   : armed={hb['armed']}   log={logs}")

    try:
        _disarm_body(ct, hb, rc, spin, logs, REGISTRY)
    finally:
        # Bai nay co y dua FC vao dung trang thai kho ngat nhat. Thoat ma de no
        # armed, dong co dang quay, khong con tien trinh nao trong tay — do la
        # ket cuc te nhat co the.
        if hb.get("armed"):
            print("\n  !!! FC con ARMED luc thoat — dang ngat")
            ct._escape("disarm", {"force": True})
            if not spin(5, lambda: not hb.get("armed")):
                print("  !!! KHONG NGAT DUOC — GAT DISARM TREN RC NGAY")
            print(f"  armed = {hb.get('armed')}")
        win.disconnect()
        win.close()
    print("  ok  DISARM tren FC that: duoi dat thi mot lan bam la ngat duoc, "
          "ga o muc nao cung vay")


def _disarm_body(ct, hb, rc, spin, logs, REGISTRY):
    # --- ga len giua tam, roi bam DISARM mot phat ---
    # Day la ca dang do: truoc khi sua, dung trang thai nay lam lenh disarm thuong
    # bi tu choi 3/3 lan (ack=4). Gio app tu biet la dang duoi dat nen gui thang
    # force, va vi tri can ga khong con lien quan.
    #
    # Day cung la chang duy nhat do duoc NGUON THU HAI: ga len giua tam thi FC lat
    # `landed_state` sang 2 (dang bay) du may bay van treo tren thanh, nen cai
    # quyet dinh phai la cam bien khoang cach. Hai tlog ngay 04/08 khong co chang
    # nay — `landed_state` bang 1 suot ca hai file — nen dong in duoi day la bang
    # chung con thieu: no phai cho thay landed=False MA van ra FORCE.
    print("  >>> DAY GA LEN GIUA TAM (dong co se quay) — dang cho...", flush=True)
    if not spin(90, lambda: (rc.get("RC_CHANNELS.chan3_raw") or 0) > 1400):
        print("  ga khong len — bo qua phan do quan trong nhat")
    else:
        print(f"  ga = {rc.get('RC_CHANNELS.chan3_raw')}  "
              f"FC bao landed = {REGISTRY.value('heartbeat.landed')}  "
              f"rangefinder = {ct._rng}  "
              f"(alt_rel = {REGISTRY.value('position.alt_rel')} — khong dung nua)")
        logs.clear()
        ct.btn_kill.click()
        spin(6, lambda: not hb.get("armed"))
        print(f"  bam mot phat : armed={hb['armed']}")
        for line in logs:
            print("      log:", line)
        assert any("FORCE" in x for x in logs), f"duoi dat ma khong gui force: {logs}"
        assert not hb["armed"], "bam mot phat o ga cao ma dong co van chay"
        print("  -> ngat duoc voi ga giua tam, mot lan bam")


# ------------------------------------------------- nut ARM / DISARM thuong
def kb_armcycle(cycles=3):
    """Do ky nut ARM va DISARM thuong tren FC that, qua dung duong cua app.

    Bon phan:
      A. {cycles} chu ky ARM -> DISARM o ga min, do do tre click -> ack -> armed
      B. ARM roi de yen: FC tu ngat sau DISARM_DELAY giay. Man hinh phai theo kip
      C. ARM khi ga cao: FC tu choi, va app PHAI noi ra
      D. Lenh thua (ARM luc dang armed, DISARM luc dang disarmed)
    """
    from PySide6.QtWidgets import QApplication

    from core import bus
    from laptop.app import MainWindow

    app = QApplication.instance() or QApplication([])
    prof = {"name": "FC that qua USB", "mode": "REAL",
            "conn": PORT, "baud": BAUD, "sysid": 254}
    win = MainWindow([prof])
    win.panel.select(prof["name"])
    win.panel.btn_connect.click()
    ct = win.control_tab
    logs = []
    ct.log.connect(logs.append)

    hb, rc, acks = {}, {}, []
    bus.on("*", lambda e: hb.update(e["data"]) if e["topic"] == "heartbeat" else None)
    bus.on("*", lambda e: rc.update(e["data"]) if e["topic"] == "status" else None)
    bus.on("*", lambda e: acks.append((time.time(), e["data"]))
           if e["topic"] == "ack" else None)

    def spin(secs, until=None):
        t0 = time.time()
        while time.time() - t0 < secs:
            app.processEvents()
            time.sleep(0.01)
            if until and until():
                return True
        return False

    def ga():
        return rc.get("RC_CHANNELS.chan3_raw")

    def press(btn, label):
        """Bam mot nut, do den luc FC tra ack va den luc heartbeat doi trang thai.

        Hai con so nay khac nhau ve ban chat: ack la "FC da nhan", heartbeat la
        "FC da lam". Nhip heartbeat 1 Hz nen cot sau co sai so ~1s, dung doc no
        nhu do tre that.
        """
        acks.clear()
        logs.clear()
        was = hb.get("armed")
        t0 = time.time()
        btn.click()
        spin(8, lambda: acks)
        t_ack = (acks[0][0] - t0) if acks else None
        res = acks[0][1]["result"] if acks else None
        spin(4, lambda: hb.get("armed") != was)
        t_hb = (time.time() - t0) if hb.get("armed") != was else None
        print(f"  {label:<22} ack={res}  sau {t_ack:.2f}s" if t_ack is not None
              else f"  {label:<22} KHONG CO ACK")
        print(f"  {'':<22} armed {was} -> {hb.get('armed')}"
              + (f"  (heartbeat sau {t_hb:.1f}s)" if t_hb else "  (khong doi)"))
        for x in logs:
            print("      log:", x)
        return res

    spin(20, lambda: "armed" in hb)
    assert "armed" in hb, "khong nhan duoc heartbeat qua app"
    try:
        _armcycle_body(ct, hb, rc, ga, spin, press, cycles)
    finally:
        # Bai test HITL khong duoc phep thoat ma de may bay con armed, ke ca khi
        # no thoat vi assert. Da xay ra that: mot assert sai lam FC nam armed voi
        # ga giua tam, dong co quay, khong con tien trinh nao trong tay.
        if hb.get("armed"):
            print("\n  !!! FC con ARMED luc thoat — dang ngat")
            ct._escape("disarm")
            if not spin(4, lambda: not hb.get("armed")):
                ct._escape("disarm", {"force": True})
                if not spin(4, lambda: not hb.get("armed")):
                    print("  !!! KHONG NGAT DUOC — GAT RC NGAY")
            print(f"  armed = {hb.get('armed')}")
        win.disconnect()
        win.close()


def _armcycle_body(ct, hb, status, ga, spin, press, cycles):
    print("\n--- A. chu ky ARM/DISARM o ga min ---")
    print("  >>> HA GA VE MIN VA GIU — dang cho...", flush=True)
    if not spin(90, lambda: (ga() or 9999) < 1150):
        sys.exit("ga khong ve min sau 90s")
    print(f"  ga = {ga()}\n")
    for i in range(cycles):
        print(f"  [chu ky {i+1}/{cycles}]")
        assert press(ct.btn_arm, "ARM") == 0, "FC tu choi ARM"
        assert hb["armed"], "ack=0 ma FC khong armed"
        # DISARM_DELAY = 10s: cham hon la khong biet ai ngat, minh hay FC
        assert press(ct.btn_disarm, "DISARM") == 0, "FC tu choi DISARM"
        assert not hb["armed"], "ack=0 ma FC van armed"
        spin(1)

    print("\n--- B. de yen sau khi ARM: FC tu ngat (DISARM_DELAY) ---")
    # auto_disarm_check (motors.cpp:122) chi dem gio khi CA HAI dung: ga thap VA
    # `land_complete`. Nen khi no khong ngat, cau hoi la FC dang nghi minh o dau —
    # EXTENDED_SYS_STATE.landed_state la cho FC tu tra loi cau do.
    #   1 = tren mat dat, 2 = tren khong, 3 = dang cat canh, 4 = dang ha
    def land():
        return status.get("EXTENDED_SYS_STATE.landed_state")
    press(ct.btn_arm, "ARM")
    t0 = time.time()
    seen = []
    while time.time() - t0 < 25 and hb.get("armed"):
        spin(0.5)
        s = (round(time.time() - t0), land(), ga())
        if not seen or seen[-1][1:] != s[1:]:
            seen.append(s)
    for t, ls, g in seen:
        print(f"    +{t:2}s  landed_state={ls}  ga={g}")
    if not hb.get("armed"):
        print(f"  FC tu disarm sau {time.time() - t0:.1f}s (DISARM_DELAY = 10s)")
    else:
        print(f"  KHONG tu disarm sau 25s — dong ho bi reset lien tuc")
        press(ct.btn_disarm, "DISARM don dep")

    print("\n--- C. ARM khi ga cao: app phai chan, FC thi khong ---")
    # Truoc khi co chot chan nay, chay chang C la dong co quay that: do luc 22:35,
    # ga 1496 -> ack=0 -> motor 1654/1506/1347/1080, vi ArduCopter chi kiem ga THAP
    # hon nguong failsafe (AP_Arming.cpp:81-115). Gio app chan tu tren nen chang
    # nay khong con byte nao di xuong FC — an toan de chay moi lan.
    print("  >>> DAY GA LEN GIUA TAM — dang cho...", flush=True)
    if spin(90, lambda: (ga() or 0) > 1400):
        print(f"  ga = {ga()}")
        res = press(ct.btn_arm, "ARM (ga cao)")
        assert res is None, f"co ack tuc la lenh DA di xuong FC: {res}"
        assert not hb["armed"], "FC armed — chot chan khong giu"
        print("  -> khong co ack: lenh dung lai o app, khong xuong FC")
    else:
        print("  bo qua chang C: ga khong len")

    print("\n--- D. lenh thua ---")
    print("  >>> HA GA VE MIN VA GIU — dang cho...", flush=True)
    if not spin(90, lambda: (ga() or 9999) < 1150):
        sys.exit("ga khong ve min")
    press(ct.btn_disarm, "DISARM luc da disarm")
    press(ct.btn_arm, "ARM")
    press(ct.btn_arm, "ARM luc da armed")
    press(ct.btn_disarm, "DISARM")
    assert not hb["armed"], "ket thuc ma FC van armed"
    # Dong ket noi la viec cua khoi `finally` ben kb_armcycle — no chay ca khi
    # ham nay chet giua chung, con o day thi khong.
    print("\n  ok  ARM/DISARM thuong: an dung, tra ack dung, va app khong nuot loi tu choi")


if __name__ == "__main__":
    if "--child" in sys.argv:
        _child("--arm" in sys.argv)
    elif "12" in sys.argv:
        kb12()
    elif "7" in sys.argv:
        kb7("--arm" in sys.argv)
    elif "disarm" in sys.argv:
        kb_disarm()
    elif "armcycle" in sys.argv:
        kb_armcycle()
    else:
        sys.exit(__doc__)
