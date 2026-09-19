"""Doc canh bao thanh tieng — nguoi bay nhin drone chu khong nhin man hinh.

Chi doc khi TRANG THAI DOI (suon), khong doc lai moi nhip 5 Hz; rieng "ve nha
ngay" nhac lai moi REPEAT_S giay con dung. Khong co engine TTS (thieu module Qt,
may khong co speech-dispatcher) thi im lang — giao dien van chay nhu cu.
Bat/tat o tab Cai dat, luu QSettings cung cho voi ngon ngu.
"""

import time

from PySide6.QtCore import QLocale, QSettings

from core import i18n
from core.i18n import t

REPEAT_S = 30.0  # "ve nha ngay" con dung thi nhac lai sau chung nay
# Giong: nu, cao, trong — nguoi dung chon 19/09. Bien the espeak-ng dung chung cho
# ca vi va en; thu lan luot, cai dau tien co tren may thi lay. Tai nghe thay chua
# ung thi chinh ba so nay (pitch/rate trong khoang -1..1, 0 = mac dinh).
VOICE_VARIANTS = ("Annie", "female3", "female2")
PITCH = 0.5
RATE = 0.1


def enabled():
    return QSettings(i18n._ORG, i18n._APP).value("voice", "true") == "true"


def set_enabled(on):
    QSettings(i18n._ORG, i18n._APP).setValue("voice", "true" if on else "false")


class Voice:
    def __init__(self):
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
            self._tts = QTextToSpeech()
            self._tts.setPitch(PITCH)
            self._tts.setRate(RATE)
        except Exception:  # ponytail: khong co TTS thi thoi, khong phai loi
            self._tts = None
        self._last = {}  # ten su kien -> gia tri lan truoc
        self._said_at = {}
        self.spoken = []  # nhat ky, cho selfcheck

    def say(self, key, **kw):
        text = t(key, **kw)
        self.spoken.append(text)
        if not self._tts or not enabled():
            return
        loc = QLocale("vi_VN" if i18n.lang() == "vi" else "en_US")
        if self._tts.locale() != loc:
            self._tts.setLocale(loc)
            self._pick_voice(loc)
        self._tts.say(text)

    def _pick_voice(self, loc):
        """Giong nu (VOICE_VARIANTS) dung vung cua locale.

        Do that 19/09: espeak-ng cho en_US chon mac dinh "English (Caribbean)"
        trong khi co san "English (America)" — nen loc theo vung truoc. Khong co
        bien the nao (vd Windows/SAPI) thi lay giong nu bat ky, roi giong mac dinh.
        """
        want = QLocale.territoryToString(loc.territory())  # "United States"
        region = {"United States": "America"}.get(want, want)
        voices = self._tts.availableVoices()
        local = [v for v in voices if region in v.name()] or voices
        for var in VOICE_VARIANTS:
            for v in local:
                if v.name().endswith("+" + var):
                    self._tts.setVoice(v)
                    return
        from PySide6.QtTextToSpeech import QVoice
        for v in local:
            if v.gender() == QVoice.Gender.Female:
                self._tts.setVoice(v)
                return

    def on(self, event, value, key, repeat=False, **kw):
        """Doc `key` khi `event` vua CHUYEN sang `value` (khac None/False).

        repeat=True: con dung `value` thi nhac lai moi REPEAT_S giay.
        """
        prev = self._last.get(event)
        self._last[event] = value
        if not value:
            return
        now = time.time()
        if value != prev or (repeat and now - self._said_at.get(event, 0) >= REPEAT_S):
            self._said_at[event] = now
            self.say(key, **kw)

    def reset(self):
        self._last.clear()
        self._said_at.clear()
