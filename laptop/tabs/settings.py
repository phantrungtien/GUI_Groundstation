"""Tab Settings — hien tai chi co mot thu: ngon ngu giao dien.

Mot tab cho MOT lua chon nghe hoi thua, nhung cho khac deu sai hon: nhet vao
dock "Ket noi" thi no lan voi thao tac truoc chuyen bay, con lam menu bar thi
phai dung ca mot menu bar von dang trong.

Doi ngon ngu la HIEN NGAY, khong khoi dong lai: doi giua chuyen bay khong duoc
phep lam mat ket noi. Xem core/i18n.py.
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from core import i18n
from core.i18n import t
from laptop import theme, voice


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.box = QGroupBox()
        v = QVBoxLayout(self.box)
        self.buttons = {}
        for code, label in i18n.LANGS.items():
            # Ten ngon ngu viet bang CHINH ngon ngu do ("Tiếng Việt", "English"),
            # khong dich sang ngon ngu dang chon: nguoi khong doc duoc giao dien
            # hien tai van phai tim ra dong cua minh.
            b = QRadioButton(label)
            b.setChecked(code == i18n.lang())
            b.toggled.connect(lambda on, c=code: on and i18n.set_lang(c))
            v.addWidget(b)
            self.buttons[code] = b

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{theme.MUTED};")

        # Giong noi: mac dinh BAT. Tat o day (vd bay trong phong hop) — luu lai.
        self.voice = QCheckBox()
        self.voice.setChecked(voice.enabled())
        self.voice.toggled.connect(voice.set_enabled)

        lay = QVBoxLayout(self)
        lay.addWidget(self.box)
        lay.addWidget(self.note)
        lay.addWidget(self.voice)
        lay.addStretch(1)
        i18n.on_change(self._retext)

    def _retext(self):
        self.box.setTitle(t("set.lang_box"))
        self.note.setText(t("set.lang_note"))
        self.voice.setText(t("set.voice"))
        # Doi ngon ngu tu noi khac (hay khoi phuc tu QSettings) van phai lam nut
        # o day nhay theo — nut radio la thu HIEN trang thai, khong phai nguon.
        for code, b in self.buttons.items():
            b.blockSignals(True)
            b.setChecked(code == i18n.lang())
            b.blockSignals(False)
