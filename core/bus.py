"""Bus envelope — dung chung voi ban web.

Envelope: {"src": str, "topic": str, "data": dict, "ts": float}   (xem docs/protocol.md)

Module nay KHONG import Qt. Adapter chay o thread rieng thi phat Qt signal;
main thread nhan signal roi moi goi emit(). Nho vay ranh gioi thread nam gon
o mep adapter, con core/ thi backend nao cung dung duoc.
"""

import time
from collections import defaultdict

# ponytail: state module-level, khong phai class Bus. Mot app = mot bus.
_subs = defaultdict(list)


def on(topic, fn):
    """Dang ky subscriber. topic "*" nhan moi envelope."""
    _subs[topic].append(fn)


def off(topic, fn):
    if fn in _subs[topic]:
        _subs[topic].remove(fn)


def emit(src, topic, data, ts=None):
    """Phat envelope toi subscriber cua topic va cua "*". Tra ve envelope."""
    env = {"src": src, "topic": topic, "data": data, "ts": ts if ts is not None else time.time()}
    for fn in _subs[topic] + _subs["*"]:
        fn(env)
    return env


def emit_envelope(env):
    """Phat mot envelope da dung dinh dang (adapter gui sang qua Qt signal)."""
    return emit(env["src"], env["topic"], env["data"], env.get("ts"))
