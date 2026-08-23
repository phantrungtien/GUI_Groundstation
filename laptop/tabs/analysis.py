"""Tab Phan tich: doc mot .tlog roi ve do thi field va quy dao 3D.

Doc THANG tu file chu khong lay tu bus — bus chi mang gia tri dang chay, con
core/field.py chi giu gia tri moi nhat. Do thi thi can ca lich su.

Cung cong viec ma MAVExplorer.py lam (no da co san trong ~/.local/bin, cai kem
pymavlink). Dung o day de khoi phai roi app khi muon xem lai chuyen bay vua roi;
can dao sau — FFT, so hai log, loc theo che do bay — thi van nen mo MAVExplorer.
"""

from pathlib import Path

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QMargins, QPointF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core import i18n, logdata
from core.i18n import t
from laptop import theme
from laptop.widgets.trajectory3d import Trajectory3D

ROOT = Path(__file__).resolve().parent.parent.parent

# Tran duong tren mot do thi. Qua sau duong thi khong con doc duoc mau nao ra mau
# nao, va do thi log thi de doi chieu vai duong voi nhau chu khong de xem tat ca.
MAX_SERIES = 6

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


class AnalysisTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log = None
        self._loader = None
        # Ten field dang ve. Giu rieng chu khong hoi QListWidget: go vao o loc la
        # nhung muc dang chon bi an di, ma hoi danh sach thi cai an = cai khong
        # chon, do thi trang bang trong luc nguoi dung chi dinh tim them mot field.
        self._picked = []

        # --- hang chon file ---
        self.picker = QComboBox()
        self.picker.setMinimumWidth(320)
        self.btn_browse = QPushButton()
        self.btn_browse.clicked.connect(self._browse)
        self.btn_load = QPushButton()
        self.btn_load.clicked.connect(self._load)
        self.summary = QLabel()
        self.summary.setStyleSheet(f"color:{theme.MUTED};")

        top = QHBoxLayout()
        top.addWidget(self.picker, 1)
        top.addWidget(self.btn_browse)
        top.addWidget(self.btn_load)
        top.addWidget(self.summary, 2)

        # --- cot trai: loc + danh sach field ---
        self.filter = QLineEdit()
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._refilter)
        self.norm = QCheckBox()
        self.norm.toggled.connect(self._replot)
        self.fields = QListWidget()
        self.fields.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.fields.itemSelectionChanged.connect(self._on_pick)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.filter)
        left.addWidget(self.norm)
        left.addWidget(self.fields, 1)
        left_box = QWidget()
        left_box.setLayout(left)
        left_box.setMinimumWidth(230)

        # --- do thi 2D ---
        self.chart = QChart()
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

        self.view = QChartView(self.chart)
        self.view.setRenderHint(QPainter.Antialiasing)
        # Keo chuot khoanh mot vung de phong to — cach zoom cua MAVExplorer.
        # Nhay doi de ve lai toan bo, xem mouseDoubleClickEvent ben duoi.
        self.view.setRubberBand(QChartView.RectangleRubberBand)
        self.view.mouseDoubleClickEvent = self._unzoom
        self.view.setMinimumHeight(200)

        # --- quy dao 3D ---
        self.traj = Trajectory3D()

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.view)
        right.addWidget(self.traj)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left_box)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(split, 1)

        self._scan_logs()
        i18n.on_change(self._retext)

    # ------------------------------------------------------------------ chu

    def _retext(self):
        self.btn_browse.setText(t("an.browse"))
        self.btn_load.setText(t("an.load"))
        self.filter.setPlaceholderText(t("an.filter"))
        self.norm.setText(t("an.normalize"))
        self.norm.setToolTip(t("an.normalize_tip"))
        if self.log is None:
            self.summary.setText(t("an.nothing"))
        else:
            self._show_summary()
        self.traj.update()

    def _show_summary(self):
        d = self.log
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
        """Liet ke logs/*.tlog, moi nhat len dau — thu hay mo lai nhat la chuyen vua bay."""
        keep = self.picker.currentData()
        self.picker.clear()
        for p in sorted((ROOT / "logs").glob("*.tlog"),
                        key=lambda q: q.stat().st_mtime, reverse=True):
            self.picker.addItem(f"{p.name}  ({p.stat().st_size // 1024} KB)", str(p))
        if keep:  # dang chon file nao thi giu nguyen, khong nhay ve dau danh sach
            i = self.picker.findData(keep)
            if i >= 0:
                self.picker.setCurrentIndex(i)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("conn.pick_tlog"), str(ROOT / "logs"), t("conn.tlog_filter"))
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
        self.log = log
        self._picked = []  # log khac thi ten field cung khac, giu lai la vo nghia
        # pymavlink KHONG nem loi khi file khong phai .tlog — no chi khong doc ra
        # goi nao. Khong noi ro thi man hinh giong het mot log doc thanh cong ma
        # ben trong rong, va nguoi dung ngoi doi mot do thi khong bao gio hien.
        self._show_summary()
        self._refilter()
        self._show_track()

    # ------------------------------------------------------------------ ve

    def _show_track(self):
        if not self.log.parsed:
            self.traj.set_track([], [], [], note=t("an.empty_note"))
            return
        _, e, n, u = self.log.local_track()
        if len(e) < 2:
            # Khong bia mot duong thang dung roi de nguoi doc tuong la quy dao:
            # noi thang ra la log nay khong co dinh vi. Log bay trong nha deu vay.
            self.traj.set_track([], [], [], note=t("an.no_fix"))
        else:
            self.traj.set_track(e, n, u)

    def _on_pick(self):
        """Nguoi dung doi lua chon: cap nhat danh sach dang ve.

        Chi dung nhung muc DANG HIEN de sua — field dang chon ma bo loc giau di
        thi van giu nguyen, khong coi la vua bo chon.
        """
        shown = {self.fields.item(r).text() for r in range(self.fields.count())}
        chosen = {i.text() for i in self.fields.selectedItems()}
        self._picked = [n for n in self._picked if n not in shown or n in chosen]
        self._picked += [n for n in sorted(chosen) if n not in self._picked]
        self._replot()

    def _refilter(self):
        """Loc theo chuoi con, khong phan biet hoa thuong — nhu o tab Trang thai."""
        if self.log is None:
            return
        keep = set(self._picked)
        q = self.filter.text().strip().lower()
        self.fields.blockSignals(True)
        self.fields.clear()
        for name in self.log.names():
            if q and q not in name.lower():
                continue
            self.fields.addItem(name)
            if name in keep:
                self.fields.item(self.fields.count() - 1).setSelected(True)
        self.fields.blockSignals(False)
        self._replot()

    def _unzoom(self, _ev):
        self.chart.zoomReset()

    def _replot(self):
        self.chart.removeAllSeries()
        if self.log is None:
            return

        picked = self._picked[:MAX_SERIES]
        if not picked:
            self.chart.setTitle(t("an.pick_field"))
            self.ax.setRange(0, 1)
            self.ay.setRange(0, 1)
            return
        self.chart.setTitle("")

        normalize = self.norm.isChecked()
        ymin, ymax, tmax = None, None, 0.0
        for idx, name in enumerate(picked):
            ts, vs = self.log.series(name)
            if not ts:
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

            s = QLineSeries()
            s.setName(label)
            s.setPen(QPen(QColor(SERIES_COLORS[idx % len(SERIES_COLORS)]), 1.6))
            # replace() mot lan nhanh hon append() tung diem — vai chuc nghin diem
            # thi khac nhau ro.
            s.replace([QPointF(a, b) for a, b in zip(ts, vs)])
            self.chart.addSeries(s)
            s.attachAxis(self.ax)
            s.attachAxis(self.ay)
            ymin = lo if ymin is None else min(ymin, lo)
            ymax = hi if ymax is None else max(ymax, hi)
            tmax = max(tmax, ts[-1])

        if ymin is None:
            return
        self.ax.setTitleText(t("an.axis_time"))
        self.ay.setTitleText(t("an.axis_norm") if normalize else t("an.axis_value"))
        pad = (ymax - ymin) * 0.05 or 1.0
        self.ax.setRange(0, max(tmax, 1.0))
        self.ay.setRange(ymin - pad, ymax + pad)
