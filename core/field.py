"""Trong tai da nguon — dung chung voi ban web.

Cung mot dai luong den tu nhieu duong (SiK va companion). Lop nay chon gia tri
dung va noi ro no den tu dau. No khong biet gi ve MAVLink hay WebSocket: `src`
chi la mot chuoi. Them duong thu ba (LTE, LoRa) thi them mot dong vao PRIORITY.
"""

import math
import time

PRIORITY = {"remote": 2, "sik": 1}  # remote uu tien vi tan so cao hon
STALE = 2.0  # giay

# Nhung topic khong dua vao trong tai: firehose va so lieu ve chinh duong truyen
SKIP_TOPICS = {"status", "link", "text"}


class Field:
    """Mot dai luong, nhieu nguon."""

    def __init__(self, name):
        self.name = name
        self.by_src = {}  # src -> (value, ts)

    def put(self, src, value, ts=None):
        self.by_src[src] = (value, ts if ts is not None else time.time())

    def fresh(self, now=None):
        now = now or time.time()
        return {s: v for s, (v, ts) in self.by_src.items() if now - ts < STALE}

    def best(self, now=None):
        """Tra ve CA gia tri lan nguon. Khong co nguon nao con tuoi -> (None, None)."""
        fresh = self.fresh(now)
        if not fresh:
            return None, None
        src = max(fresh, key=lambda s: PRIORITY.get(s, 0))
        return fresh[src], src

    def divergence(self, now=None):
        """Chenh lech lon nhat giua cac nguon con tuoi. Duoi hai nguon -> None."""
        fresh = [v for v in self.fresh(now).values() if isinstance(v, (int, float))]
        if len(fresh) < 2:
            return None
        return max(fresh) - min(fresh)


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Registry:
    """Tap hop Field, an theo bus."""

    def __init__(self):
        self.fields = {}

    def feed(self, env):
        if env["topic"] in SKIP_TOPICS:
            return
        for k, v in env["data"].items():
            if v is None:
                continue
            name = f"{env['topic']}.{k}"
            self.fields.setdefault(name, Field(name)).put(env["src"], v, env["ts"])

    def best(self, name, now=None):
        f = self.fields.get(name)
        return f.best(now) if f else (None, None)

    def value(self, name, default=None):
        v, _ = self.best(name)
        return default if v is None else v

    def position_divergence_m(self, now=None):
        """Kich ban #8: hai nguon lech vi tri qua nguong thi canh bao.

        Lech vi tri phai do bang met, khong phai bang do — nen khong dung
        Field.divergence() cho lat/lon duoc.
        """
        lat, lon = self.fields.get("position.lat"), self.fields.get("position.lon")
        if not lat or not lon:
            return None
        flat, flon = lat.fresh(now), lon.fresh(now)
        common = set(flat) & set(flon)
        if len(common) < 2:
            return None
        pts = [(flat[s], flon[s]) for s in common]
        return max(
            haversine_m(*a, *b) for i, a in enumerate(pts) for b in pts[i + 1:]
        )


REGISTRY = Registry()  # ponytail: mot app = mot registry, nhu bus
