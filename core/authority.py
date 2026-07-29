"""Phan quyen giua laptop (qua SiK) va node offboard tren companion.

Doc ky nguyen tac 2.1 truoc khi sua file nay.

Switch MANUAL/AUTO dieu phoi dung mot ranh gioi: giua BAN (lenh tu laptop qua
SiK) va NODE OFFBOARD tren companion (stream setpoint tu hanh). No khong phai co
che an toan cua toan he thong — RC di thang xuong FC, khong xin phep ai.

Nut do di truoc moi kiem tra. Khong co nhanh nao lam no bi chan.
"""

GCS, ROS2 = "gcs", "ros2"

# Nut do. Ba lenh nay du de dua drone ve nha.
ESCAPE = {"rtl", "land", "disarm"}

# target (ten adapter) -> ai phai dang cam quyen thi lenh do moi di duoc
TARGET_OWNER = {"sik": GCS, "remote": ROS2}

AUTHORITY = GCS
ADAPTERS = {}


def register(name, adapter):
    ADAPTERS[name] = adapter


def unregister(name):
    ADAPTERS.pop(name, None)


def set_authority(who):
    global AUTHORITY
    assert who in (GCS, ROS2), who
    AUTHORITY = who
    # Node offboard tren companion subscribe /gcs/authority de biet luc nao phai
    # tu dung stream setpoint. Khong gui duoc thi khong sao: nut do van di duong
    # SiK, va bam bat ky nut do nao cung la mot tin hieu nhuong quyen.
    remote = ADAPTERS.get("remote")
    if remote:
        remote.send("authority", {"value": who})
    return AUTHORITY


def dispatch(msg):
    """msg = {"target": "sik", "action": "rtl", "args": {}}"""
    action = msg["action"]

    if action in ESCAPE:
        sik = ADAPTERS.get("sik")
        if sik is None:
            return {"error": "chua co duong SiK"}
        r = sik.send(action, msg.get("args", {}))  # KHONG kiem tra quyen
        # Bam nut do LA mot tin hieu nhuong quyen (2.4). Khong lam buoc nay thi
        # node offboard van stream setpoint va giang co voi lenh vua gui —
        # dung kich ban hong #5. Lam SAU khi gui de khong gi chen duoc vao
        # truoc nut do: set_authority() cham WebSocket, ma WebSocket thi treo duoc.
        set_authority(GCS)
        return r

    target = msg.get("target", "sik")
    owner = TARGET_OWNER.get(target, GCS)
    if owner != AUTHORITY:
        return {"error": f"quyen dang thuoc ve {AUTHORITY}"}

    adapter = ADAPTERS.get(target)
    if adapter is None:
        return {"error": f"chua co adapter {target}"}
    return adapter.send(action, msg.get("args", {}))
