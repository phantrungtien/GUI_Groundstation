"""Thong bao loi noi tren man hinh bay, kieu DJI: dong mau giua-tren, tu tat.

Chi con phan logic, khong co Qt: man bay cam ung ve cac dong nay bang QML, doc
qua `Backend.state["alerts"]`.

Tab Thong bao giu HET lich su; day chi la cai phi cong phai thay NGAY ma khong
roi ban do. Nen chi lay WARNING tro len, va gop dong trung: FC that lap lai
PreArm moi ~30,7 s (do 15/09/2026 tren log 84 phut: dung 2 cau x 164 lan, khong
co STATUSTEXT nao khac). Moi lan lap ma bat mot dong moi thi man hinh nhay suot.
"""

import time

MAX_SEV = 4  # MAV_SEVERITY: WARNING tro len (so nho = nang) — giong WARN_SEV tab Thong bao
ERR_SEV = 3  # ERROR tro len: nen do, song lau
ROWS = 3
# Song bao lau sau lan cuoi thay — nguoi dung chot 15/09/2026. Ngan hon nhip lap
# 30,7 s cua PreArm nen dong PreArm hien 10 s roi tat ~20 s, toi lan FC nhac lai.
TTL_ERR = 10.0
TTL_WARN = 5.0


class AlertBook:
    """Phan logic, khong co Qt: gop, xep, tu tat. Man bay cam ung (`touch/`) dung
    chung dung ban nay — hai ban logic la hai cho de lech nhau."""

    def __init__(self):
        self._items = {}  # chu -> [muc nang nhat, so lan, lan cuoi thay]

    def push(self, text, sev):
        """True neu co dong duoc them/cap nhat."""
        if isinstance(text, bytes):  # cung phong nhu tab Thong bao
            text = text.decode("utf-8", "replace")
        text = (text or "").rstrip("\x00").strip()
        if sev > MAX_SEV or not text:
            return False
        now = time.time()
        it = self._items.get(text)
        if it:
            it[0], it[1], it[2] = min(it[0], sev), it[1] + 1, now
        else:
            self._items[text] = [sev, 1, now]
        return True

    def clear(self):
        self._items.clear()

    def red(self):
        """Chu cac dong DO dang con song (goi sau shown(), no moi don dong het han)."""
        return {k for k, v in self._items.items() if v[0] <= ERR_SEV}

    def shown(self, now=None):
        """Bo dong het han, tra toi da ROWS dong [(chu da kem xn/(+k), muc)]."""
        now = now or time.time()
        self._items = {k: v for k, v in self._items.items()
                       if now - v[2] < (TTL_ERR if v[0] <= ERR_SEV else TTL_WARN)}
        # Nang nhat len tren, cung muc thi moi nhat len tren: ba dong WARNING moi
        # khong duoc day mot dong CRITICAL ra khoi man hinh.
        top = sorted(self._items.items(), key=lambda kv: (kv[1][0], -kv[1][2]))[:ROWS]
        out = []
        for i, (text, (sev, n, _)) in enumerate(top):
            if n > 1:
                text += f"  ×{n}"
            if i == ROWS - 1 and len(self._items) > ROWS:
                text += f"  (+{len(self._items) - ROWS})"  # cat ma im lang = tuong la het
            out.append((text, sev))
        return out
