"""Tab Phan tich: ve do thi field va quy dao 3D — tu file log, hoac truc tiep.

Hai nguon, mot bo do thi:

  * FILE (mac dinh): doc THANG tu .tlog HAY .bin (xem core/logdata.py). bus chi
    mang gia tri dang chay va core/field.py chi giu gia tri moi nhat, ma do thi
    thi can ca lich su.
  * TRUC TIEP: nghe topic "status" tren bus, giu LIVE_WINDOW giay gan nhat trong
    core/logdata.LiveData. Cung names()/series() nen phan ve khong doi mot dong.

Tab luon nghe bus ke ca khi dang xem file: bat cong tac len la co ngay mot phut
vua roi, khong phai bat truoc roi ngoi doi do thi day len tu con so khong.

Nhieu do thi, moi cai mot danh sach field rieng (class Plot). Mot do thi thi moi
duong phai dung chung mot truc dung — dien ap 12 V ve chung voi do cao 30 m thi
duong dien ap bep thanh mot vach. Chuan hoa 0-1 giai quyet duoc HINH DANG nhung
mat con so; tach ra hai do thi thi giu ca hai. Tick field o cot trai la them vao
do thi DANG CHON (vien sang), bam vao mot do thi khac de doi.

Cung cong viec ma MAVExplorer.py lam (no da co san trong ~/.local/bin, cai kem
pymavlink). Dung o day de khoi phai roi app khi muon xem lai chuyen bay vua roi;
can dao sau — FFT, so hai log, loc theo che do bay — thi van nen mo MAVExplorer.
"""

import time
from pathlib import Path

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QMargins, QPointF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core import bus, i18n, logdata
from core.field import REGISTRY
from core.i18n import t
from laptop import theme
from laptop.widgets.trajectory3d import Trajectory3D

ROOT = Path(__file__).resolve().parent.parent.parent

# Tran duong tren mot do thi. Qua sau duong thi khong con doc duoc mau nao ra mau
# nao, va do thi log thi de doi chieu vai duong voi nhau chu khong de xem tat ca.
MAX_SERIES = 6

# Tran so do thi. Bon cai tren mot man hinh 1080p da con ~200 px moi cai — them
# nua thi khong con doc duoc truc dung, ma khong doc duoc truc thi do thi chi con
# la hinh trang tri.
MAX_PLOTS = 4

# Nhip ve lai o che do truc tiep. 20 Hz.
#
# Day tung la nut that lon nhat cua do tre: o 250 ms, mot mau ATTITUDE mat toi
# 100 ms (nhip stream) + 250 ms (nhip ve) moi len duoc man hinh. Gio la 20 + 50.
#
# 50 ms co du de ve khong: do 26/08/2026 voi 6 duong x 3000 diem (50 Hz x cua so
# 60 s) — 16.3 ms mot nhip khi giu lai series, 23.7 ms neu xoa het roi dung lai.
# Vua khit trong 50 ms, va chi ton khi tab dang hien (xem _live_tick).
LIVE_MS = 50

# Quy dao 3D ve lai moi TRACK_EVERY nhip, tuc 4 Hz. Do thi 2D thi cang nhanh cang
# tot — do la cai nguoi ta nhin de bat mot cu giat. Quy dao 3D thi nguoc lai: no
# la mot duong dai vai tram met, them 50 ms du lieu khong doi duoc mot pixel nao,
# ma ve lai thi phai chieu lai toan bo diem. Do 26/08/2026: bo tu 20 Hz xuong 4 Hz
# cat duoc ~7% CPU ma khong nhin ra khac biet.
TRACK_EVERY = 5

# Mau cac duong — lay tu bang mau, phan biet duoc tren nen toi.
SERIES_COLORS = [theme.ACCENT, theme.OK, theme.WARN, theme.INFO,
                 theme.CRIT, "#c58af9"]


class _Loader(QThread):
    """Doc log o thread rieng: file that mat vai giay, dong bang giao dien la hong."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            self.done.emit(logdata.load(self.path))
        except Exception as e:  # file hong, khong phai .tlog, khong doc duoc...
            self.failed.emit(f"{type(e).__name__}: {e}")


class Plot(QChartView):
    """Mot do thi: truc rieng, bo duong dung lai, va danh sach field cua RIENG no.

    Tach ra khoi AnalysisTab de con dat duoc nhieu cai canh nhau. Cai thuoc ve
    mot do thi va chi mot do thi: truc, bo duong, va `picked`. Cai dung chung ca
    tab — nguon du lieu, o loc, cong tac chuan hoa — thi van o AnalysisTab.
    """

    clicked = Signal(object)

    def __init__(self, parent=None):
        self.chart = QChart()
        super().__init__(self.chart, parent)
        self.picked = []   # ten field do thi nay dang ve, theo thu tu tick
        self._series = []  # bo duong dung lai giua cac nhip — xem _pool()

        self.chart.legend().setVisible(True)
        self.chart.legend().setAlignment(Qt.AlignBottom)
        self.chart.legend().setLabelColor(QColor(theme.TEXT_DIM))
        self.chart.setBackgroundBrush(QColor(theme.SURFACE))
        self.chart.setPlotAreaBackgroundBrush(QColor(theme.SURFACE))
        self.chart.setPlotAreaBackgroundVisible(True)
        self.chart.setMargins(QMargins(4, 4, 4, 4))

        # Truc tao mot lan roi giu lai. Truoc day moi lan ve lai deu removeAxis()
        # roi tao truc moi — QChart van ve truc cu chong len truc moi, nhin ra hai
        # bo so lech nhau vai pixel. Giu mot bo va chi doi range thi khong co gi
        # de chong.
        self.ax, self.ay = QValueAxis(), QValueAxis()
        for a, align in ((self.ax, Qt.AlignBottom), (self.ay, Qt.AlignLeft)):
            a.setLabelsColor(QColor(theme.MUTED))
            a.setTitleBrush(QColor(theme.TEXT_DIM))
            a.setGridLineColor(QColor("#1e2c38"))
            a.setLinePenColor(QColor(theme.BORDER))
            self.chart.addAxis(a, align)

        self.setRenderHint(QPainter.Antialiasing)
        # Keo chuot khoanh mot vung de phong to — cach zoom cua MAVExplorer.
        # Nhay doi de ve lai toan bo.
        self.setRubberBand(QChartView.RectangleRubberBand)
        self.setMinimumHeight(140)
        self.set_active(False)

    # ---------------------------------------------------------------- chon

    def set_active(self, on):
        """Vien sang = do thi ma tick ben trai se do vao.

        Phai nhin ra duoc tu xa: khong co dau nay thi tick mot field xong no hien
        ra o mot do thi khac va nguoi dung khong hieu vi sao.
        """
        # Khong dung 'transparent' cho cai khong duoc chon: no de lo nen mac dinh
        # cua he thong (do duoc #efefef, sang trung tren nen toi). Vien mo cua
        # theme vua lam dau "khong chon", vua tach hai do thi xep chong len nhau.
        self.setStyleSheet(
            f"border:2px solid {theme.ACCENT if on else theme.BORDER};")

    def mousePressEvent(self, ev):
        self.clicked.emit(self)
        super().mousePressEvent(ev)  # giu nguyen viec keo khoanh vung de zoom

    def mouseDoubleClickEvent(self, _ev):
        self.chart.zoomReset()

    # ------------------------------------------------------------------ ve

    def _pool(self, n):
        """Dung dung n duong, dung lai bo cu neu so duong khong doi.

        Xoa het roi dung lai moi nhip la cach cu — do duoc 23.7 ms cho 6 duong x
        3000 diem, tuc tran nhip ve 42 Hz, khong lot duoc vao khung 50 ms. Giu
        series va chi doi diem thi con 16.3 ms. So duong chi doi khi nguoi dung
        tick, con nhip ve truc tiep thi luon di duong nhanh.

        ponytail: het nhanh thi bat setUseOpenGL(True) tren tung duong — do duoc
        10.0 ms — doi lai mat khu rang cua va lop ve nam ngoai truc.
        """
        if len(self._series) != n:
            self.chart.removeAllSeries()
            self._series = []
            for _ in range(n):
                sr = QLineSeries()
                self.chart.addSeries(sr)
                sr.attachAxis(self.ax)
                sr.attachAxis(self.ay)
                self._series.append(sr)
        return self._series

    def replot(self, src, normalize, live, number):
        """Ve lai. `number` chi de goi ten do thi khi no con trong."""
        if src is None:
            self._pool(0)
            return

        picked = self.picked[:MAX_SERIES]
        if not picked:
            self._pool(0)
            self.chart.setTitle(t("an.plot_empty", n=number))
            self.ax.setRange(0, 1)
            self.ay.setRange(0, 1)
            return
        self.chart.setTitle("")
        pool = self._pool(len(picked))

        ymin, ymax, tmin, tmax = None, None, None, 0.0
        for idx, name in enumerate(picked):
            sr = pool[idx]
            ts, vs = src.series(name)
            if not ts:
                # Duong rong chu khong bo qua: bo qua thi chi so lech di mot bac
                # va cac duong con lai doi mau, doi ten sang cua nhau.
                sr.replace([])
                sr.setName(name)
                continue
            lo, hi = min(vs), max(vs)
            label = name
            if normalize:
                # Hang so (lo == hi) ve thanh duong giua khung, khong chia cho 0.
                rng = hi - lo
                vs = [0.5 if rng == 0 else (v - lo) / rng for v in vs]
                # Thang that van phai hien: chuan hoa xong ma khong noi goc la bao
                # nhieu thi do thi dep nhung khong doc ra con so nao.
                label = t("an.series_norm", name=name, lo=lo, hi=hi)
                lo, hi = 0.0, 1.0

            if sr.name() != label:  # doi ten la QChart dung lai chu giai
                sr.setName(label)
            sr.setPen(QPen(QColor(SERIES_COLORS[idx % len(SERIES_COLORS)]), 1.6))
            # replace() mot lan nhanh hon append() tung diem — vai chuc nghin diem
            # thi khac nhau ro.
            sr.replace([QPointF(a, b) for a, b in zip(ts, vs)])
            ymin = lo if ymin is None else min(ymin, lo)
            ymax = hi if ymax is None else max(ymax, hi)
            tmin = ts[0] if tmin is None else min(tmin, ts[0])
            tmax = max(tmax, ts[-1])

        if ymin is None:
            return
        self.ax.setTitleText(t("an.axis_time_live" if live else "an.axis_time"))
        self.ay.setTitleText(t("an.axis_norm") if normalize else t("an.axis_value"))
        pad = (ymax - ymin) * 0.05 or 1.0
        if live:
            # Cua so truot: goc toa do la luc bat dau nghe chu khong phai luc nay,
            # nen phai bam theo diem cu nhat con lai. Neu ke tu 0 thi sau mot gio
            # bay ca phut du lieu bi ep vao vai pixel cuoi truc.
            self.ax.setRange(tmin, max(tmax, tmin + 1.0))
        else:
            self.ax.setRange(0, max(tmax, 1.0))
        self.ay.setRange(ymin - pad, ymax + pad)


class LogDownload(QDialog):
    """Hop thoai keo mot log .bin tu the SD cua FC ve, qua chinh duong telemetry.

    Vi sao khong bao gio tu dong tai: 13 MB qua SiK 57600 la gan 45 phut va gan
    het bang thong trong suot thoi gian do — tuc HUD dung hinh. Nguoi bay phai la
    nguoi quyet dinh danh duong truyen cho viec nay, va phai dung lai duoc.

    Dang ARM thi khoa: dang bay ma keo log la tu bit mat duong so lieu cua chinh
    minh. Khoa o day chu khong o adapter — adapter khong theo doi trang thai bay,
    con cho nay thi REGISTRY co san.
    """

    def __init__(self, adapter, parent=None):
        super().__init__(parent)
        self.adapter = adapter
        self.path = None  # duong dan file vua tai xong, None neu chua/khong xong

        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._retext)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.note = QLabel()
        self.note.setStyleSheet(f"color:{theme.MUTED};")
        self.btn_scan = QPushButton()
        self.btn_scan.clicked.connect(self._scan)
        self.btn_get = QPushButton()
        # Mot nut lam ca hai viec: dang tai thi no la nut Huy. Hai nut thi mot
        # cai luon xam, va nut Huy phai o dung cho mat vua nhin luc bam Tai.
        self.btn_get.clicked.connect(lambda: self._cancel() if self._getting else self._get())
        self.btn_close = QPushButton()
        self.btn_close.clicked.connect(self.close)

        row = QHBoxLayout()
        row.addWidget(self.btn_scan)
        row.addWidget(self.btn_get)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        lay = QVBoxLayout(self)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.bar)
        lay.addWidget(self.note)
        lay.addLayout(row)
        self.resize(460, 380)

        self._getting = False
        bus.on("log", self._on_log)
        i18n.on_change(self._retext)
        self._retext()
        self._scan()

    # ---- gui di

    def _scan(self):
        self.list.clear()
        self.note.setText(t("an.fc_scanning"))
        self.adapter.send("log_list", {})

    def _get(self):
        it = self.list.currentItem()
        if not it or self._getting:
            return
        if REGISTRY.value("heartbeat.armed") is True:
            self.note.setText(t("an.fc_armed"))
            return
        log = it.data(Qt.UserRole)
        self._getting = True
        self.bar.setValue(0)
        self.note.setText(t("an.fc_getting", mb=log["size"] / 1e6))
        self.adapter.send("log_get", {"id": log["id"], "size": log["size"]})
        self._retext()

    def _cancel(self):
        self.adapter.send("log_cancel", {})
        self._getting = False
        self._retext()

    # ---- nhan ve

    def _on_log(self, env):
        d = env["data"]
        if "list" in d:
            self._show_list(d["list"], d.get("n", 0))
        got = d.get("get")
        if got:
            self._show_progress(got)

    def _show_list(self, logs, n):
        keep = self.list.currentRow()
        self.list.clear()
        for g in sorted(logs, key=lambda g: g["id"], reverse=True):
            # time_utc = 0 tren FC khong co pin RTC — do that tren MicoAir743:
            # ca hai file trong Downloads deu ten "1-1-1980". Khong bia ngay gia
            # o day, de trong con hon de mot ngay sai.
            when = (time.strftime("%d/%m/%Y %H:%M", time.localtime(g["time_utc"]))
                    if g["time_utc"] else "")
            self.list.addItem(t("an.fc_row", id=g["id"], mb=g["size"] / 1e6, when=when))
            self.list.item(self.list.count() - 1).setData(Qt.UserRole, g)
        if not logs:
            self.note.setText(t("an.fc_none") if n == 0 else t("an.fc_scanning"))
        else:
            self.note.setText(t("an.fc_found", n=len(logs), all=n))
            self.list.setCurrentRow(max(keep, 0))

    def _show_progress(self, g):
        size = max(g["size"], 1)
        self.bar.setValue(int(100 * g["got"] / size))
        if not g.get("done"):
            self.note.setText(t("an.fc_progress", mb=g["got"] / 1e6,
                                total=size / 1e6))
            return
        self._getting = False
        self._retext()
        if g.get("err"):
            # File do dang VAN nam tren dia va van doc duoc — noi ca hai ve.
            self.note.setText(t("an.fc_partial", err=g["err"], mb=g["got"] / 1e6))
            self.path = g.get("path")
            return
        self.path = g.get("path")
        self.note.setText(t("an.fc_done", name=Path(self.path).name))
        self.accept()

    def _retext(self):
        self.setWindowTitle(t("an.fc_title"))
        self.btn_scan.setText(t("an.fc_scan"))
        self.btn_get.setText(t("an.fc_cancel") if self._getting else t("an.fc_get"))
        self.btn_close.setText(t("an.fc_close"))
        self.btn_scan.setEnabled(not self._getting)
        self.btn_get.setEnabled(self._getting or self.list.currentItem() is not None)

    def closeEvent(self, ev):
        # Dong cua so giua chung thi phai BAO FC dung gui, khong thi no bom tiep
        # 13 MB vao duong truyen ma khong con ai doc.
        if self._getting:
            self._cancel()
        bus.off("log", self._on_log)
        super().closeEvent(ev)


class AnalysisTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log = None
        self._loader = None
        # Luon gom du lieu song ke ca khi dang xem file — xem docstring dau file.
        self.live_data = logdata.LiveData()
        self._live_names = []  # ten field lan ve truoc, de biet khi nao phai dung lai danh sach
        self._ticks = 0  # dem nhip truc tiep, de ha nhip ve quy dao 3D
        self.plots = []  # cac do thi, tren xuong duoi
        self._active = None  # do thi tick se do vao

        # --- hang chon file ---
        self.picker = QComboBox()
        self.picker.setMinimumWidth(320)
        self.btn_browse = QPushButton()
        self.btn_browse.clicked.connect(self._browse)
        self.btn_load = QPushButton()
        self.btn_load.clicked.connect(self._load)
        self.btn_fc = QPushButton()
        self.btn_fc.clicked.connect(self._from_fc)
        self.btn_fc.setEnabled(False)  # bat len o attach(), khi da co adapter
        self.adapter = None
        self.live = QCheckBox()
        self.live.toggled.connect(self._on_live)
        self.summary = QLabel()
        self.summary.setStyleSheet(f"color:{theme.MUTED};")

        top = QHBoxLayout()
        top.addWidget(self.picker, 1)
        top.addWidget(self.btn_browse)
        top.addWidget(self.btn_fc)
        top.addWidget(self.btn_load)
        top.addWidget(self.live)
        top.addWidget(self.summary, 2)
        self.btn_add = QPushButton()
        self.btn_add.clicked.connect(self.add_plot)
        self.btn_del = QPushButton()
        self.btn_del.clicked.connect(self.del_plot)
        top.addWidget(self.btn_add)
        top.addWidget(self.btn_del)

        # --- cot trai: loc + danh sach field ---
        self.filter = QLineEdit()
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._refilter)
        self.norm = QCheckBox()
        self.norm.toggled.connect(self._replot)
        # Tick thay cho ctrl+click. Chon nhieu bang ctrl+click la thu phai BIET
        # moi dung duoc, va bam hut mot phat la mat sach lua chon dang co — voi
        # danh sach 254 field thi do la mot cai bay. O tick thi khong the bam nham.
        self.fields = QListWidget()
        self.fields.itemChanged.connect(self._on_tick)

        # "Bieu do 2 · 3/6 duong" — noi tick se do vao dau va con cho khong.
        self.where = QLabel()
        self.where.setStyleSheet(f"color:{theme.MUTED};")
        self.where.setWordWrap(True)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.filter)
        left.addWidget(self.norm)
        left.addWidget(self.where)
        left.addWidget(self.fields, 1)
        left_box = QWidget()
        left_box.setLayout(left)
        left_box.setMinimumWidth(230)

        # --- cac do thi 2D ---
        self.stack = QSplitter(Qt.Vertical)

        # --- quy dao 3D ---
        self.traj = Trajectory3D()

        self.stack.addWidget(self.traj)  # quy dao luon nam duoi cung
        self.stack.setStretchFactor(0, 2)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left_box)
        split.addWidget(self.stack)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(split, 1)

        self.add_plot()  # luon co it nhat mot do thi
        self._scan_logs()
        bus.on("status", self.live_data.feed)
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self._live_tick)
        self._live_timer.start(LIVE_MS)
        i18n.on_change(self._retext)

    # ------------------------------------------------------------- truc tiep

    @property
    def src(self):
        """Nguon dang ve: LiveData khi bat cong tac, khong thi la log da doc."""
        return self.live_data if self.live.isChecked() else self.log

    # ------------------------------------------------------------- cac do thi

    @property
    def plot(self):
        """Do thi dang chon — noi tick o cot trai se do vao."""
        return self._active

    # Ba loi tat de code cu va selfcheck van doc duoc "do thi dang chon".
    chart = property(lambda self: self._active.chart)
    ax = property(lambda self: self._active.ax)
    ay = property(lambda self: self._active.ay)

    def add_plot(self):
        """Them mot do thi trong o duoi cung roi chon luon no."""
        if len(self.plots) >= MAX_PLOTS:
            return
        pl = Plot()
        pl.clicked.connect(self.set_active)
        # Chen TRUOC quy dao 3D: quy dao luon o duoi cung, khong thi them mot do
        # thi la no bi day len giua dam do thi.
        self.stack.insertWidget(len(self.plots), pl)
        self.plots.append(pl)
        self.set_active(pl)
        self._sync_plot_buttons()

    def del_plot(self):
        """Bo do thi dang chon. Luon con lai it nhat mot cai."""
        if len(self.plots) <= 1:
            return
        pl = self._active
        i = self.plots.index(pl)
        self.plots.remove(pl)
        pl.setParent(None)
        pl.deleteLater()
        self.set_active(self.plots[min(i, len(self.plots) - 1)])
        self._sync_plot_buttons()

    def set_active(self, pl):
        """Doi do thi dang chon: doi vien, va doi luon o tick ben trai theo no."""
        if pl is self._active:
            return
        for other in self.plots:
            other.set_active(other is pl)
        self._active = pl
        self._refilter()  # o tick phai the hien field cua do thi VUA chon

    def _sync_plot_buttons(self):
        self.btn_add.setEnabled(len(self.plots) < MAX_PLOTS)
        self.btn_del.setEnabled(len(self.plots) > 1)
        self._show_where()

    def _show_where(self):
        """Dong "Bieu do 2 · 3/6 duong" duoi o loc."""
        if not self._active:
            return
        self.where.setText(t("an.where", n=self.plots.index(self._active) + 1,
                             k=len(self._active.picked), max=MAX_SERIES))

    def _on_live(self, _on):
        self._retext()
        self._refilter()
        self._show_track()

    def _live_tick(self):
        """Nhip cua che do truc tiep: cat duoi cua so, ve lai, dat lai chu tom tat.

        Van chay khi dang xem file — trim() phai goi deu, khong thi bat cong tac
        len la gap ca dong diem cu tu luc chua ai nhin. Con ve lai thi chi ve khi
        that su dang o che do truc tiep.
        """
        self.live_data.trim()
        # Dang o tab khac thi ve la ve cho khong ai xem — 20 Hz x 16 ms la mot
        # phan ba loi CPU dot vao mot widget bi che. trim() thi van phai chay.
        if not self.live.isChecked() or not self.isVisible():
            return
        self._show_summary()
        # Field moi chi xuat hien khi FC bat dau gui mot message chua tung gui
        # (vd doi che do bay). Dung lai ca danh sach moi nhip thi cuon den dau
        # cung bi giat ve dau, nen chi dung khi tap ten that su doi.
        names = self.src.names()
        if names is not self._live_names and names != self._live_names:
            self._live_names = names
            self._refilter()
        else:
            self._replot()
        self._ticks += 1
        if self._ticks % TRACK_EVERY == 0:
            self._show_track()

    # ------------------------------------------------------------------ chu

    def _retext(self):
        self.btn_browse.setText(t("an.browse"))
        self.btn_fc.setText(t("an.from_fc"))
        self.btn_fc.setToolTip(t("an.from_fc_tip"))
        self.btn_load.setText(t("an.load"))
        self.filter.setPlaceholderText(t("an.filter"))
        self.norm.setText(t("an.normalize"))
        self.norm.setToolTip(t("an.normalize_tip"))
        self.live.setText(t("an.live"))
        self.live.setToolTip(t("an.live_tip", sec=self.live_data.window))
        self.btn_add.setText(t("an.add_plot"))
        self.btn_add.setToolTip(t("an.add_plot_tip", max=MAX_PLOTS))
        self.btn_del.setText(t("an.del_plot"))
        self.btn_del.setToolTip(t("an.del_plot_tip"))
        self._show_where()
        self._replot()  # ten do thi trong va nhan truc deu theo ngon ngu
        if self.src is None:
            self.summary.setText(t("an.nothing"))
        else:
            self._show_summary()
        self.traj.update()

    def _show_summary(self):
        d = self.src
        if self.live.isChecked():
            hz = d.rate()
            if not d.parsed:
                # Chua he co goi nao: khong phai "0 field" ma la chua ket noi.
                self.summary.setText(t("an.live_none"))
            else:
                self.summary.setText(t(
                    "an.live_summary", fields=len(d.fields), sec=d.window, hz=hz))
                self.summary.setStyleSheet(
                    f"color:{theme.MUTED if hz else theme.WARN};")
            return
        self.summary.setStyleSheet(f"color:{theme.MUTED};")
        if not d.parsed:
            self.summary.setText(t("an.empty", name=Path(d.path).name))
            return
        self.summary.setText(t(
            "an.summary", name=Path(d.path).name, msgs=d.parsed,
            mins=d.duration / 60.0, fields=len(d.fields), sec=d.load_seconds))

    # ------------------------------------------------------------------ file

    def showEvent(self, ev):
        """Quet lai moi lan mo tab: bay xong chuyen nao la co ngay chuyen do.

        App ghi .tlog cho MOI che do ke ca REAL (xem sik.py), nen ha canh xong
        sang day la file da nam san trong logs/. Khong quet lai thi phai khoi dong
        lai app moi thay no — dung luc con dang muon biet vi sao no vua bay la.
        """
        super().showEvent(ev)
        self._scan_logs()

    def _scan_logs(self):
        """Liet ke log trong logs/, moi nhat len dau — thu hay mo lai nhat la chuyen vua bay.

        Ca .tlog (app tu ghi) lan .bin (keo tu the SD cua FC sang). Bam "Mo file..."
        thi doc duoc .bin o bat ky dau; day chi la danh sach cho tien.
        """
        keep = self.picker.currentData()
        self.picker.clear()
        files = [q for pat in ("*.tlog", "*.bin", "*.BIN")
                 for q in (ROOT / "logs").glob(pat)]
        for p in sorted(files, key=lambda q: q.stat().st_mtime, reverse=True):
            self.picker.addItem(f"{p.name}  ({p.stat().st_size // 1024} KB)", str(p))
        if keep:  # dang chon file nao thi giu nguyen, khong nhay ve dau danh sach
            i = self.picker.findData(keep)
            if i >= 0:
                self.picker.setCurrentIndex(i)

    def attach(self, adapter):
        """app.py goi khi ket noi/ngat. REPLAY thi khong co FC de ma hoi."""
        self.adapter = adapter
        self.btn_fc.setEnabled(adapter is not None and adapter.mode != "REPLAY")

    def _from_fc(self):
        """Keo log .bin tu the SD cua FC ve qua duong telemetry.

        Vi sao dang o day chu khong o tab Ket noi: file tai ve xong la doc len
        do thi ngay, cung mot cho, khong phai di tim lai trong thu muc.
        """
        if not self.adapter:
            return
        dlg = LogDownload(self.adapter, self)
        dlg.exec()
        if dlg.path:
            self._scan_logs()
            i = self.picker.findData(dlg.path)
            if i < 0:
                self.picker.insertItem(0, Path(dlg.path).name, dlg.path)
                i = 0
            self.picker.setCurrentIndex(i)
            self._load()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("an.pick_log"), str(ROOT / "logs"), t("an.log_filter"))
        if path:
            self.picker.insertItem(0, Path(path).name, path)
            self.picker.setCurrentIndex(0)
            self._load()

    def _load(self):
        path = self.picker.currentData()
        if not path or (self._loader and self._loader.isRunning()):
            return
        self.btn_load.setEnabled(False)
        self.summary.setText(t("an.loading"))
        self._loader = _Loader(path, self)
        self._loader.done.connect(self._loaded)
        self._loader.failed.connect(self._load_failed)
        self._loader.start()

    def _load_failed(self, err):
        self.btn_load.setEnabled(True)
        self.summary.setText(t("an.err", err=err))

    def _loaded(self, log):
        self.btn_load.setEnabled(True)
        # Bam "Doc log" la muon xem CAI FILE do. De truc tiep bat thi doc xong van
        # thay do thi dang chay, khong thay thu vua doc.
        self.live.setChecked(False)
        self.log = log
        for pl in self.plots:
            pl.picked = []  # log khac thi ten field cung khac, giu lai la vo nghia
        # pymavlink KHONG nem loi khi file khong phai .tlog — no chi khong doc ra
        # goi nao. Khong noi ro thi man hinh giong het mot log doc thanh cong ma
        # ben trong rong, va nguoi dung ngoi doi mot do thi khong bao gio hien.
        self._show_summary()
        self._refilter()
        self._show_track()

    # ------------------------------------------------------------------ ve

    def _show_track(self):
        if self.src is None:
            return
        # Truc tiep thi quy dao bi dat lai vai lan mot giay — giu goc nhin nguoi
        # dung dang xoay, tru lan dau khi chua co gi de ma giu.
        keep = self.live.isChecked() and len(self.traj._e) > 2
        if not self.src.parsed:
            self.traj.set_track([], [], [], note=t("an.live_none" if
                                self.live.isChecked() else "an.empty_note"))
            return
        _, e, n, u = self.src.local_track()
        if len(e) < 2:
            # Khong bia mot duong thang dung roi de nguoi doc tuong la quy dao:
            # noi thang ra la log nay khong co dinh vi. Log bay trong nha deu vay.
            self.traj.set_track([], [], [], note=t("an.no_fix"))
        else:
            self.traj.set_track(e, n, u, keep_view=keep)

    def _on_tick(self, item):
        """Tick/bo tick mot field: them/bo no khoi do thi DANG CHON.

        Chi dong den field vua bam. Truoc day (ctrl+click) phai suy ra lua chon
        moi tu ca danh sach, va phai chua rieng truong hop bo loc dang giau bot
        muc — o tick thi cai bi giau khong sinh su kien nao, nen no tu dung yen.
        """
        name = item.text()
        picked = self._active.picked
        if item.checkState() == Qt.Checked:
            if name in picked:
                return
            if len(picked) >= MAX_SERIES:
                # Bo tick lai va noi ra. Am tham nuot cai tick thi nguoi dung
                # tuong minh bam hut, bam lai lan nua, van khong ra gi.
                self.fields.blockSignals(True)
                item.setCheckState(Qt.Unchecked)
                self.fields.blockSignals(False)
                self.where.setText(t("an.plot_full", max=MAX_SERIES))
                return
            picked.append(name)
        elif name in picked:
            picked.remove(name)
        self._show_where()
        self._replot()

    def _refilter(self):
        """Loc theo chuoi con, khong phan biet hoa thuong — nhu o tab Trang thai."""
        if self.src is None:
            return
        keep = set(self._active.picked)
        q = self.filter.text().strip().lower()
        self.fields.blockSignals(True)
        self.fields.clear()
        for name in self.src.names():
            if q and q not in name.lower():
                continue
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if name in keep else Qt.Unchecked)
            self.fields.addItem(it)
        self.fields.blockSignals(False)
        self._show_where()
        self._replot()

    def _replot(self):
        """Ve lai MOI do thi.

        O che do truc tiep viec nay chay 20 lan mot giay, nen chi phi nhan len
        theo so do thi: bon do thi day 6 duong la 24 duong moi nhip. Tran
        MAX_PLOTS x MAX_SERIES la cai giu cho no khong troi di.
        """
        live = self.live.isChecked()
        normalize = self.norm.isChecked()
        for i, pl in enumerate(self.plots):
            pl.replot(self.src, normalize, live, i + 1)
