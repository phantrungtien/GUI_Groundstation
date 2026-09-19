"""Doc canh bao thanh tieng — nguoi bay nhin drone chu khong nhin man hinh.

Chi doc khi TRANG THAI DOI (suon), khong doc lai moi nhip 5 Hz; rieng "ve nha
ngay" nhac lai moi REPEAT_S giay con dung. Bat/tat o tab Cai dat, luu QSettings
cung cho voi ngon ngu.

Hai engine, cai dau co thi dung:
  1. Piper (giong noron, chay tren may, khong can mang) — file giong o
     assets/voices/, tai bang `python3 tools/fetch_voices.py`. espeak-ng doc
     tieng Viet sai dau va nghe nhu may (nguoi dung 20/09), nen day la mac dinh.
  2. Qt TextToSpeech (speech-dispatcher/espeak-ng tren Linux, SAPI tren Windows)
     — khi thieu goi piper-tts hoac file giong.
Ca hai deu khong co thi im lang — giao dien van chay nhu cu.
"""

import re
import time
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QLocale, QSettings

from core import i18n
from core.i18n import t

REPEAT_S = 30.0  # "ve nha ngay" con dung thi nhac lai sau chung nay
# Giong: nu, cao, trong — nguoi dung chon 19/09. Bien the espeak-ng dung chung cho
# ca vi va en; thu lan luot, cai dau tien co tren may thi lay. Tai nghe thay chua
# ung thi chinh ba so nay (pitch/rate trong khoang -1..1, 0 = mac dinh).
VOICE_VARIANTS = ("Annie", "female3", "female2")
PITCH = 0.5
# Doc day du thay vi doc tat — "RTL" doc thanh "rờ tê lờ" khong ai nghe ra (nguoi
# dung 20/09). Chi doi CHU DOC, chu tren man hinh giu nguyen ten mode cua FC.
SPOKEN = ((re.compile(r"\bSMART_RTL\b|\bSmartRTL\b"), "smart return to launch"),
          (re.compile(r"\bRTL\b"), "return to launch"))
# Piper: file giong theo ngon ngu, va do keo dai (>1 = cham hon). Giong nu ca hai.
VOICE_DIR = Path(__file__).resolve().parent.parent / "assets" / "voices"
PIPER_VOICES = {"vi": "vi_VN-vais1000-medium", "en": "en_US-amy-medium"}
LENGTH_SCALE = 1.35
GAP_S = 0.25  # khoang lang sau moi cau: hai canh bao lien nhau khong dinh vao nhau
RATE = -0.4  # nguoi dung 20/09: doc cham lai (truoc 0.1). Am = cham hon


def enabled():
    return QSettings(i18n._ORG, i18n._APP).value("voice", "true") == "true"


def set_enabled(on):
    QSettings(i18n._ORG, i18n._APP).setValue("voice", "true" if on else "false")


class _Piper:
    """Tong hop bang Piper, phat PCM qua QAudioSink. Hang doi tu quan ly.

    Do 20/09 tren laptop nay: nap moi giong ~0,5 s (mot lan, o cau dau tien cua
    ngon ngu do), tong hop 0,03–0,11 s moi cau — nen tong hop ngay tren luong
    chinh, khong can luong rieng hay file tao san.
    """
    # ponytail: tong hop tren luong chinh; cau rat dai (>1 s tong hop) thi day ra QThread.

    def __init__(self):
        from piper import PiperVoice, SynthesisConfig  # ImportError -> Voice dung Qt TTS
        self._load = PiperVoice.load
        self._cfg = SynthesisConfig(length_scale=LENGTH_SCALE)
        self._voices = {}
        self._queue = []  # [(pcm bytes, sample rate)]
        self._sink = self._buf = None
        self._rate = None

    @staticmethod
    def has(lang):
        name = PIPER_VOICES.get(lang)
        return bool(name) and (VOICE_DIR / f"{name}.onnx").exists()

    def pcm(self, text, lang):
        """(PCM int16 mono, sample rate) cho `text`. Tach rieng de selfcheck do."""
        v = self._voices.get(lang)
        if v is None:
            v = self._voices[lang] = self._load(str(VOICE_DIR / f"{PIPER_VOICES[lang]}.onnx"))
        rate = v.config.sample_rate
        pcm = b"".join(c.audio_int16_bytes for c in v.synthesize(text, self._cfg))
        return pcm + bytes(2 * int(rate * GAP_S)), rate

    def say(self, text, lang, queue):
        item = self.pcm(text, lang)
        if not queue:
            self._queue.clear()
        self._queue.append(item)
        if self._buf is None or not queue:
            self._next()  # dang ranh, hoac cat ngang cau dang doc

    def _next(self):
        from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink
        if self._sink is not None:
            self._sink.stop()
        self._buf = None
        if not self._queue:
            return
        pcm, rate = self._queue.pop(0)
        if self._sink is None or rate != self._rate:
            fmt = QAudioFormat()
            fmt.setSampleRate(rate)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            self._sink, self._rate = QAudioSink(fmt), rate
            self._sink.stateChanged.connect(self._on_state)
        self._buf = QBuffer()
        self._buf.setData(QByteArray(pcm))
        self._buf.open(QIODevice.ReadOnly)
        self._sink.start(self._buf)

    def _on_state(self, st):
        from PySide6.QtMultimedia import QAudio
        if st == QAudio.State.IdleState:  # doc het cau: sang cau ke tiep trong hang doi
            self._next()


class Voice:
    def __init__(self):
        try:
            self._piper = _Piper()
        except Exception:  # ponytail: thieu piper-tts thi dung Qt TTS, khong phai loi
            self._piper = None
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
            self._tts = QTextToSpeech()
            self._tts.setPitch(PITCH)
            self._tts.setRate(RATE)
        except Exception:  # ponytail: khong co TTS thi thoi, khong phai loi
            self._tts = None
        self._last = {}  # ten su kien -> gia tri lan truoc
        self._said_at = {}
        self._red = set()  # dong loi do da doc, xem alerts()
        self.spoken = []  # nhat ky, cho selfcheck

    def say(self, key, queue=False, **kw):
        """queue=True: xep sau cau dang doc (loi FC). Mac dinh cat ngang — "ve
        nha ngay" khong duoc doi mot cau loi dai doc xong."""
        text = t(key, **kw)
        for pat, full in SPOKEN:
            text = pat.sub(full, text)
        self.spoken.append(text)
        if not enabled():
            return
        lang = i18n.lang()
        if self._piper and _Piper.has(lang):
            self._piper.say(text, lang, queue)
            return
        if not self._tts:
            return
        loc = QLocale("vi_VN" if i18n.lang() == "vi" else "en_US")
        if self._tts.locale() != loc:
            self._tts.setLocale(loc)
            self._pick_voice(loc)
        (self._tts.enqueue if queue else self._tts.say)(text)

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

    def change(self, event, value, key, **kw):
        """Doc khi `value` DOI tu mot gia tri da biet (ARM, mode). None = chua
        biet: bo qua, khong ghi de — noi vao hay chap chon telemetry khong duoc
        doc ra "disarm" / "che do STABILIZE" nhu the vua co ai doi."""
        if value is None:
            return
        prev = self._last.get(event)
        self._last[event] = value
        if prev is not None and value != prev:
            self.say(key, **kw)

    def alerts(self, red):
        """Doc moi dong loi DO vua hien (suon: moi xuat hien, hoac het han roi
        quay lai). PreArm bo qua — dong SAN SANG ARM da noi, va FC nhac PreArm
        moi ~31 s nen doc len la lai nhai suot luc chuan bi."""
        red = {x for x in red if not x.startswith("PreArm")}
        # Toi da 3 cau moi nhip — bang cho man bay chi co 3 dong; don 10 loi mot
        # luc thi hang doi doc keo dai ca phut, cham hon ca viec nhin man hinh.
        for text in sorted(red - self._red)[:3]:
            self.say("voice.alert", queue=True, text=text)
        self._red = red

    def reset(self):
        self._last.clear()
        self._said_at.clear()
        self._red = set()
