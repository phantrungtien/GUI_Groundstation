"""Bang mau va QSS dung chung cho ca app.

Moi mau cua giao dien nam o day, khong rai trong tung file nua. Widget tu ve
(chan troi, la ban, ban do) cung lay tu day — neu chrome doi sang nen xanh than
ma ban do van xam trung tinh thi nhin nhu hai app dan vao nhau.

Nen xanh than + nhan cyan chu khong phai xam trung tinh: tren buong lai ngoai
troi, mot mau nhan DUY NHAT va sang han nen la thu keo duoc mat: cai gi vien
cyan la cai dang nhan hoac dang chon. Xam tren xam thi khong co gi keo ca.

QUY TAC khi sua bang mau: cac mau NGU NGHIA (WARN, CRIT, OK, INFO, MUTED va
bang MODE_COLOR ben duoi) phai giu KHAC NHAU ro rang. Chung khong phai trang tri
— tools/selfcheck.py doi chieu chung de biet giao dien co that su doi trang thai
khong. Doi sac do thi duoc, gop hai mau lam mot thi hong ca kiem tra lan y nghia.
"""

# --- NEN ------------------------------------------------------------------
BG_DEEP = "#08111a"     # sau nhat: nen cua so, khoang ngoai panel
BG = "#0d1722"          # nen chung cua widget
SURFACE = "#111a22"     # o nhap lieu, bang, vung chim
SURFACE_HI = "#27313a"  # mat nut (dau gradient)
HOVER = "#354550"
DOWN = "#0b1117"        # nut dang bam

# --- VIEN -----------------------------------------------------------------
BORDER = "#39505f"
BORDER_HI = "#71818d"
DIVIDER = "#2c7188"

# --- CHU ------------------------------------------------------------------
TEXT = "#f4f8fb"
TEXT_DIM = "#b8c5d0"
MUTED = "#71818d"       # chu phu, va cung la mau "nguon het tuoi"

# --- NHAN / NGU NGHIA -----------------------------------------------------
ACCENT = "#35d7ff"      # cyan: tieu diem, vien active, muc dang chon
OK = "#63f29a"
INFO = "#47a7ff"
WARN = "#f4d35e"
CRIT = "#ff5a52"

RADIUS = 8              # nut, o nhap
RADIUS_PANEL = 14       # khung, the

# Banner che do. Tam mau khac nhau la CO Y: nguoi bay phai phan biet duoc bang
# mot cai liec tu goc mat, khong doc chu. REAL/CLOSING/LOST deu la ho do nhung
# ba sac khac nhau vi ba tinh huong khac nhau.
MODE_COLOR = {
    "REAL": "#b33a32",       # dang cam FC that
    "SIM": "#1f6e9c",        # SITL
    "REPLAY": "#4a5a68",     # phat lai log, khong cham drone
    None: "#1a2530",         # chua chon nguon
    "WAIT": "#b98a1e",       # da mo nguon, chua co byte nao ve
    "DEGRADED": "#8e5bb5",   # mat nua ROS2, SiK con
    "LOST": "#ff5a52",       # mat SiK — nang nhat
    "CLOSING": "#c0392b",    # dang ARM ma bam dong cua so
}


def danger_button(size=15, pad="16px 8px"):
    """QSS cho nut do (RTL / LAND / DISARM). To, ro, khong lan voi nut thuong."""
    return f"""
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #8e2b22, stop:1 #6b1f18);
    color: #ffffff; font-size: {size}px; font-weight: bold;
    padding: {pad}; border: 1.5px solid {CRIT}; border-radius: {RADIUS}px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #a83428, stop:1 #7e241b);
    border-color: #ff8078;
}}
QPushButton:pressed {{ background: #5c1a14; }}
QPushButton:disabled {{
    background: #2a1e1c; color: #6e5a56; border-color: #4a2f2a;
}}
"""


QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
}}
QMainWindow, QDialog {{ background: {BG_DEEP}; }}

/* --- Tab: muc dang chon co gach cyan duoi chan --- */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS_PANEL}px;
    top: -1px;
}}
QTabBar::tab {{
    background: {SURFACE};
    color: {TEXT_DIM};
    padding: 7px 16px;
    margin-right: 2px;
    border: 1px solid {BORDER};
    border-bottom: 3px solid transparent;
    border-top-left-radius: {RADIUS}px;
    border-top-right-radius: {RADIUS}px;
}}
QTabBar::tab:hover {{ background: {HOVER}; color: {TEXT}; }}
QTabBar::tab:selected {{
    background: {SURFACE_HI};
    color: {TEXT};
    border-bottom: 3px solid {ACCENT};
}}

/* --- Nut: gradient ngang, vien sang len khi tro chuot --- */
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {SURFACE_HI}, stop:1 {SURFACE});
    color: {TEXT};
    font-weight: 600;
    padding: 6px 14px;
    border: 1.5px solid {BORDER_HI};
    border-radius: {RADIUS}px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {HOVER}, stop:1 #1c2a35);
    border-color: {ACCENT};
}}
QPushButton:pressed {{ background: {DOWN}; border-color: {ACCENT}; }}
QPushButton:checked {{ border-color: {OK}; color: {OK}; }}
QPushButton:disabled {{
    background: #1a2028; color: #5a666f; border-color: #2e3840;
}}

/* --- O nhap lieu --- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {SURFACE};
    color: {TEXT};
    padding: 4px 8px;
    border: 1.5px solid {BORDER};
    border-radius: {RADIUS}px;
    selection-background-color: {ACCENT};
    selection-color: {BG_DEEP};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1.5px solid {ACCENT};
    selection-background-color: {HOVER};
    outline: none;
}}

/* --- Danh sach, bang, log --- */
QListWidget, QTableView, QTreeView, QTextEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    gridline-color: #1e2a34;
    selection-background-color: {HOVER};
    selection-color: {TEXT};
    alternate-background-color: #0e1720;
}}
QHeaderView {{ background: {SURFACE}; border: none; }}
QHeaderView::section {{
    background: {SURFACE_HI};
    color: {TEXT_DIM};
    padding: 5px 8px;
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {DIVIDER};
    font-weight: 600;
}}
QTableView::item:selected, QListWidget::item:selected {{
    background: {HOVER};
}}

/* --- Khung, dock, thanh trang thai --- */
QGroupBox {{
    border: 1.5px solid {BORDER};
    border-radius: {RADIUS_PANEL}px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {ACCENT};
    /* Nen cung mau khung: khong co dong nay thi duong vien chay xuyen qua chu. */
    background: {BG};
}}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{
    background: {SURFACE_HI};
    color: {ACCENT};
    padding: 6px 10px;
    border-bottom: 1px solid {DIVIDER};
    font-weight: 600;
}}
QStatusBar {{ background: {BG_DEEP}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}
QMenuBar {{ background: {BG_DEEP}; }}
QMenuBar::item:selected {{ background: {HOVER}; }}
QMenu {{ background: {SURFACE}; border: 1.5px solid {ACCENT}; }}
QMenu::item:selected {{ background: {HOVER}; }}

/* --- Thanh cuon mong --- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: #33434f;
    border-radius: 5px;
    min-height: 28px;
    min-width: 28px;
}}
QScrollBar::handle:hover {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* --- Con lai --- */
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px;
    background: {SURFACE};
    border: 1.5px solid {BORDER_HI};
    border-radius: 3px;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
}}
QRadioButton::indicator {{ border-radius: 7px; }}
QProgressBar {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 5px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{ background: {OK}; border-radius: 4px; }}
QToolTip {{
    background: {BG_DEEP};
    color: {TEXT};
    border: 1.5px solid {ACCENT};
    padding: 5px 8px;
}}
QSplitter::handle {{ background: {BORDER}; }}
"""
