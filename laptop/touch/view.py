"""Nhung man bay cam ung (QML) vao app laptop thanh mot tab."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuickWidgets import QQuickWidget

from laptop import theme
from laptop.touch.items import WidgetItem

QML = Path(__file__).resolve().parent / "qml" / "Main.qml"
_registered = []  # qmlRegisterType mot lan cho ca tien trinh


def make_view(backend, parent=None):
    if not _registered:
        qmlRegisterType(WidgetItem, "Gcs", 1, 0, "WidgetItem")
        _registered.append(True)
    view = QQuickWidget(parent)
    view.setResizeMode(QQuickWidget.SizeRootObjectToView)
    # View lam cha cua backend: Qt do QML trong ~QQuickWidget TRUOC roi moi huy
    # con. Nguoc lai thi luc dong cua so moi binding `backend.*` keu "of null".
    backend.setParent(view)
    ctx = view.rootContext()
    ctx.setContextProperty("backend", backend)
    # Bang mau cua app laptop, khong che lai ma hex trong QML.
    ctx.setContextProperty(
        "theme", {k: v for k, v in vars(theme).items() if k.isupper() and isinstance(v, str)})
    view.setSource(QUrl.fromLocalFile(str(QML)))
    if view.status() == QQuickWidget.Error:
        raise RuntimeError("; ".join(e.toString() for e in view.errors()))
    return view
