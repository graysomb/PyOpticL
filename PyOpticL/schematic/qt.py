"""Use the Qt binding supplied by FreeCAD; optional fallbacks enable UI tests."""

try:
    from PySide import QtCore, QtGui
    try:
        from PySide import QtWidgets
    except ImportError:
        QtWidgets = QtGui
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets

Action = getattr(QtGui, "QAction", None) or QtWidgets.QAction


def exec_menu(menu, position):
    method = getattr(menu, "exec", None) or menu.exec_
    return method(position)
