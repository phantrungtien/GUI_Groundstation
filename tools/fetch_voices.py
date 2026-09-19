"""Tai giong doc Piper vao assets/voices/ (~60 MB moi giong, khong nam trong git).

    pip install --user piper-tts
    python3 tools/fetch_voices.py

Thieu file thi app van chay, chi doc bang Qt TextToSpeech (espeak) — xem laptop/voice.py.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from laptop.voice import PIPER_VOICES, VOICE_DIR

if __name__ == "__main__":
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    sys.exit(subprocess.call([sys.executable, "-m", "piper.download_voices",
                              "--download-dir", str(VOICE_DIR), *PIPER_VOICES.values()]))
