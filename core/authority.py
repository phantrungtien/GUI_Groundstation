"""Duong ra drone. Laptop cam TOAN QUYEN — khong nhuong cho ai.

Doc ky nguyen tac 2.1 truoc khi sua file nay.

Truoc day o day co mot switch MANUAL/AUTO: quyen lai chuyen qua chuyen lai giua
laptop va node offboard tren companion. Bo han. Ly do: lai la mot viec, va no
thuoc ve nguoi ngoi truoc man hinh nay. Mot ranh gioi di chuyen duoc la mot ranh
gioi phai theo doi — giua chuyen bay, cau hoi "gio ai dang lai" khong duoc phep
ton tai.

Hau qua, noi thang ra de khong ai bat ngo:

  - node offboard tren companion khong bao gio nhan duoc quyen nua. `/gcs/authority`
    chot cung o "gcs" ngay luc bridge khoi dong (tools/ros2_bridge.py) va khong
    co duong nao doi. Node co chay cung khong duoc stream setpoint.
  - nua ROS2 chi con la NGUON TELEMETRY: vi tri, van toc, video, trang thai node.
    Mat no la mat tam nhin, khong phai mat quyen dieu khien.
  - moi lenh xuong FC — ke ca nap duong bay — di duong SiK tu chinh app nay.

Nut do di truoc moi thu khac. Khong co nhanh nao lam no bi chan.
"""

GCS = "gcs"

# Nut do. Ba lenh nay du de dua drone ve nha.
ESCAPE = {"rtl", "land", "disarm"}

# Ai dang cam quyen. Con lai o day de cho nao con hoi thi doc duoc mot cau tra
# loi that — nhung khong co ham nao doi duoc no nua.
AUTHORITY = GCS
ADAPTERS = {}


def register(name, adapter):
    ADAPTERS[name] = adapter


def unregister(name):
    ADAPTERS.pop(name, None)


def dispatch(msg):
    """msg = {"target": "sik", "action": "rtl", "args": {}}

    Khong con kiem tra quyen: khong con quyen nao de kiem. Cai duy nhat con
    dac biet o nhanh ESCAPE la no khong quan tam `target` — nut do luon xuong
    thang SiK, khong bao gio di vong qua companion.
    """
    action = msg["action"]

    if action in ESCAPE:
        sik = ADAPTERS.get("sik")
        if sik is None:
            return {"error": "chua co duong SiK"}
        return sik.send(action, msg.get("args", {}))

    target = msg.get("target", "sik")
    adapter = ADAPTERS.get(target)
    if adapter is None:
        return {"error": f"chua co adapter {target}"}
    return adapter.send(action, msg.get("args", {}))
