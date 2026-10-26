"""A 2D optical schematic workspace. Export never executes generated code."""

from math import ceil, floor
from pathlib import Path

from .compiler import compile_schematic
from .geometry import apply_drawing_directions, route_to, snap_angle, snap_point
from .model import Connection, History, Schematic, load_schematic, new_id, save_schematic
from .qt import Action, QtCore, QtGui, QtWidgets
from .registry import SYMBOLS, parameter_values

Qt = QtCore.Qt
MIME = "application/x-pyopticl-schematic-symbol"


def point(value):
    return QtCore.QPointF(*value)


def pair(value):
    return (value.x(), value.y())


class Palette(QtWidgets.QListWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setDragEnabled(True)
        self.setMaximumWidth(190)
        self.setToolTip("Drag a symbol to the canvas, or double-click to place it")
        for kind, symbol in SYMBOLS.items():
            item = QtWidgets.QListWidgetItem(symbol.title)
            item.setData(Qt.UserRole, kind)
            self.addItem(item)
        self.itemDoubleClicked.connect(lambda item: editor.add_symbol(item.data(Qt.UserRole)))

    def startDrag(self, actions):
        item = self.currentItem()
        if item:
            mime = QtCore.QMimeData()
            mime.setData(MIME, item.data(Qt.UserRole).encode())
            drag = QtGui.QDrag(self)
            drag.setMimeData(mime)
            method = getattr(drag, "exec", None) or drag.exec_
            method(Qt.CopyAction)


class PortItem(QtWidgets.QGraphicsEllipseItem):
    def __init__(self, symbol, name, is_output):
        super().__init__(-6, -6, 12, 12, symbol)
        self.symbol, self.name, self.is_output = symbol, name, is_output
        self.setPos(point(SYMBOLS[symbol.node.kind].port_position(name)))
        self.setBrush(QtGui.QColor("#e79b36" if is_output else "#438cc2"))
        self.setPen(QtGui.QPen(QtGui.QColor("#1f2937"), 1))
        self.setZValue(3)
        self.setToolTip(f"{symbol.node.reference}.{name} ({'output' if is_output else 'input'})")


class SymbolItem(QtWidgets.QGraphicsObject):
    def __init__(self, node, editor):
        super().__init__()
        self.node, self.editor = node, editor
        self.setFlags(QtWidgets.QGraphicsItem.ItemIsMovable | QtWidgets.QGraphicsItem.ItemIsSelectable |
                      QtWidgets.QGraphicsItem.ItemSendsGeometryChanges)
        self.setPos(point(node.position))
        self.setRotation(node.rotation)
        self.setZValue(1)
        self.ports = {}
        spec = SYMBOLS[node.kind]
        for name in (*spec.inputs, *spec.outputs):
            self.ports[name] = PortItem(self, name, name in spec.outputs)
        label = QtWidgets.QGraphicsSimpleTextItem(node.reference, self)
        label.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
        label.setBrush(QtGui.QColor("#163c54"))
        label.setPos(-16, 32)
        self.setToolTip(f"{node.reference}: {spec.title}\nClick a port to draw a connection")

    def boundingRect(self):
        return QtCore.QRectF(-48, -49, 96, 106)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        ink = QtGui.QColor("#163c54")
        painter.setPen(QtGui.QPen(ink, 2))
        painter.setBrush(QtGui.QColor("#eff7fc"))
        if self.isSelected():
            painter.fillRect(self.boundingRect(), QtGui.QColor(110, 170, 220, 65))
        # Draw leads behind the opaque symbol so they meet its actual outline.
        for port in self.ports.values():
            painter.drawLine(QtCore.QPointF(0, 0), port.pos())
        kind = self.node.kind
        if kind == "mirror":
            painter.save()
            painter.rotate(45)
            painter.drawRect(QtCore.QRectF(-6, -25, 8, 50))
            for offset in (-16, 0, 16):
                painter.drawLine(-6, offset - 4, 2, offset + 4)
            painter.restore()
        elif kind == "lens":
            painter.drawEllipse(QtCore.QRectF(-9, -24, 18, 48))
        elif kind in ("hwp", "qwp"):
            painter.drawRect(QtCore.QRectF(-9, -24, 18, 48))
            painter.drawText(QtCore.QRectF(-28, -10, 56, 20), Qt.AlignCenter,
                             "λ/2" if kind == "hwp" else "λ/4")
        elif kind == "splitter":
            painter.drawRect(QtCore.QRectF(-23, -23, 46, 46))
            painter.drawLine(-23, 23, 23, -23)
        elif kind == "iris":
            painter.drawLine(0, -25, 0, -6)
            painter.drawLine(0, 6, 0, 25)
            painter.drawEllipse(QtCore.QRectF(-15, -15, 30, 30))
        elif kind == "stop":
            painter.fillRect(QtCore.QRectF(-6, -23, 12, 46), ink)
        elif kind in ("fiber_source", "fiber_output"):
            painter.drawRoundedRect(QtCore.QRectF(-22, -16, 44, 32), 5, 5)
            painter.drawText(QtCore.QRectF(-22, -10, 44, 20), Qt.AlignCenter, "Fiber")
        else:
            painter.drawEllipse(QtCore.QRectF(-18, -18, 36, 36))
            painter.drawLine(-10, 0, 12, 0)
            painter.drawLine(5, -7, 12, 0)
            painter.drawLine(5, 7, 12, 0)

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionChange and self.scene() is not None:
            settings = self.editor.document.settings
            return point(snap_point(pair(value), settings["grid"], settings["snap_grid"]))
        if change in (QtWidgets.QGraphicsItem.ItemPositionHasChanged,
                      QtWidgets.QGraphicsItem.ItemRotationHasChanged) and self.scene() is not None:
            self.editor.scene.update_connections()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # Commit all selected items as a single undo operation after a group drag.
        changed = False
        for item in self.scene().selectedItems():
            if isinstance(item, SymbolItem) and tuple(item.node.position) != pair(item.pos()):
                item.node.position = pair(item.pos())
                changed = True
        if changed:
            self.editor.commit(rebuild=False)


class BendItem(QtWidgets.QGraphicsEllipseItem):
    def __init__(self, connection, index, editor):
        super().__init__(-5, -5, 10, 10)
        self.connection, self.index, self.editor = connection, index, editor
        self.setBrush(QtGui.QColor("#e79b36"))
        self.setFlags(QtWidgets.QGraphicsItem.ItemIsMovable | QtWidgets.QGraphicsItem.ItemIsSelectable)
        self.setPos(point(connection.bends[index]))
        self.setZValue(4)
        self.setToolTip("Drag bend; select and Delete to remove")

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        settings = self.editor.document.settings
        self.setPos(point(snap_point(pair(self.pos()), settings["grid"], settings["snap_grid"])))
        self.connection.bends[self.index] = pair(self.pos())
        self.editor.scene.update_connections()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.editor.commit(rebuild=False)


class ConnectionItem(QtWidgets.QGraphicsPathItem):
    def __init__(self, connection, editor):
        super().__init__()
        self.connection, self.editor = connection, editor
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable)
        self.setZValue(-1)
        self.setPen(QtGui.QPen(QtGui.QColor("#bd3c43"), 2))
        self.setToolTip("Double-click to add a bend; select and Delete to disconnect")
        self.refresh()

    def refresh(self):
        symbols = self.editor.scene.symbols
        edge = self.connection
        if edge.source not in symbols or edge.target not in symbols:
            return
        start = symbols[edge.source].ports[edge.source_port].scenePos()
        end = symbols[edge.target].ports[edge.target_port].scenePos()
        path = QtGui.QPainterPath(start)
        positions = [pair(start), *edge.bends, pair(end)]
        settings = self.editor.document.settings
        # Automatic finishing segments retain angle snapping after parts move.
        routed = [positions[0]]
        for target in positions[1:]:
            routed.extend(route_to(routed[-1], target, settings["angle"], settings["snap_angle"]))
        for position in routed[1:]:
            path.lineTo(point(position))
        # Direction arrow on the final nonzero segment.
        if len(routed) > 1:
            a, b = point(routed[-2]), point(routed[-1])
            delta = b - a
            length = (delta.x() ** 2 + delta.y() ** 2) ** 0.5
            if length > 1:
                unit = delta / length
                tip = b - unit * 10
                perpendicular = QtCore.QPointF(-unit.y(), unit.x()) * 4
                path.moveTo(tip - unit * 8 + perpendicular)
                path.lineTo(tip)
                path.lineTo(tip - unit * 8 - perpendicular)
        self.setPath(path)
        self.setPen(QtGui.QPen(QtGui.QColor("#e79b36" if self.isSelected() else "#bd3c43"), 3 if self.isSelected() else 2))

    def mouseDoubleClickEvent(self, event):
        position = pair(event.scenePos())
        symbols = self.editor.scene.symbols
        starts = [pair(symbols[self.connection.source].ports[self.connection.source_port].scenePos()), *self.connection.bends]
        ends = [*self.connection.bends, pair(symbols[self.connection.target].ports[self.connection.target_port].scenePos())]
        def distance(index):
            a, b = starts[index], ends[index]
            dx, dy = b[0] - a[0], b[1] - a[1]
            scale = dx * dx + dy * dy
            t = max(0, min(1, ((position[0] - a[0]) * dx + (position[1] - a[1]) * dy) / scale)) if scale else 0
            return (position[0] - a[0] - t * dx) ** 2 + (position[1] - a[1] - t * dy) ** 2
        index = min(range(len(starts)), key=distance)
        settings = self.editor.document.settings
        self.connection.bends.insert(index, snap_point(position, settings["grid"], settings["snap_grid"]))
        self.editor.commit()
        event.accept()


class SchematicScene(QtWidgets.QGraphicsScene):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.symbols, self.connections = {}, {}
        self.pending = None
        self.bends = []
        self.preview = None
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self.selectionChanged.connect(self.selection_changed)

    def rebuild(self, selected=()):
        self.blockSignals(True)
        self.pending, self.preview, self.bends = None, None, []
        self.symbols, self.connections = {}, {}
        self.clear()
        for node in self.editor.document.nodes:
            item = SymbolItem(node, self.editor)
            self.symbols[node.id] = item
            self.addItem(item)
            item.setSelected(node.id in selected)
        for edge in self.editor.document.connections:
            item = ConnectionItem(edge, self.editor)
            self.connections[edge.id] = item
            self.addItem(item)
            for index in range(len(edge.bends)):
                self.addItem(BendItem(edge, index, self.editor))
        self.blockSignals(False)
        self.selection_changed()
        self.update()

    def selection_changed(self):
        for item in self.connections.values():
            item.refresh()
        self.editor.show_properties()

    def update_connections(self):
        for item in self.connections.values():
            item.refresh()

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QtGui.QColor("#ffffff"))
        grid = self.editor.document.settings["grid"]
        # Coarsen the visible grid when zoomed out to avoid drawing millions of dots.
        scale = self.editor.view.transform().m11() if hasattr(self.editor, "view") else 1
        while grid * scale < 10:
            grid *= 2
        painter.setPen(QtGui.QPen(QtGui.QColor("#d6dfe5"), 0))
        for x in range(floor(rect.left() / grid), ceil(rect.right() / grid) + 1):
            for y in range(floor(rect.top() / grid), ceil(rect.bottom() / grid) + 1):
                painter.drawPoint(point((x * grid, y * grid)))

    def cancel_connection(self):
        if self.preview is not None:
            self.removeItem(self.preview)
        self.preview, self.pending, self.bends = None, None, []

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            hit = self.itemAt(event.scenePos(), QtGui.QTransform())
            if isinstance(hit, PortItem):
                if hit.is_output:
                    self.cancel_connection()
                    self.pending = (hit.symbol.node.id, hit.name)
                    self.preview = self.addPath(QtGui.QPainterPath(), QtGui.QPen(QtGui.QColor("#e79b36"), 2, Qt.DashLine))
                    self.editor.status.setText("Click to add bends; click an input port to connect; Esc cancels")
                elif self.pending:
                    source, port = self.pending
                    if self.editor.connect_ports(source, port, hit.symbol.node.id, hit.name, list(self.bends)):
                        self.cancel_connection()
                        self.editor.commit()
                event.accept()
                return
            if self.pending:
                self.bends.append(self.snapped_mouse(event.scenePos()))
                event.accept()
                return
        super().mousePressEvent(event)

    def snapped_mouse(self, location):
        settings = self.editor.document.settings
        location = snap_point(pair(location), settings["grid"], settings["snap_grid"])
        source, port = self.pending
        origin = self.bends[-1] if self.bends else pair(self.symbols[source].ports[port].scenePos())
        if settings["snap_grid"] and settings["snap_angle"]:
            # Axis/diagonal endpoints remain on the drawing grid.
            route = route_to(origin, location, settings["angle"], True)
            return route[0]
        return snap_angle(location, origin, settings["angle"], settings["snap_angle"])

    def mouseMoveEvent(self, event):
        if self.pending:
            source, port = self.pending
            path = QtGui.QPainterPath(self.symbols[source].ports[port].scenePos())
            for bend in [*self.bends, self.snapped_mouse(event.scenePos())]:
                path.lineTo(point(bend))
            self.preview.setPath(path)
        super().mouseMoveEvent(event)


class SchematicView(QtWidgets.QGraphicsView):
    def __init__(self, scene, editor):
        super().__init__(scene)
        self.editor = editor
        self.setAcceptDrops(True)
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)
        self.centerOn(0, 0)
        self.panning = None

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        if 0.08 <= self.transform().m11() * factor <= 8:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.panning = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.panning is not None:
            delta = event.pos() - self.panning
            self.panning = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.panning = None
            self.unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            kind = bytes(event.mimeData().data(MIME)).decode()
            if kind in SYMBOLS:
                self.editor.add_symbol(kind, pair(self.mapToScene(event.pos())))
                event.acceptProposedAction()
        else:
            super().dropEvent(event)


class SchematicEditor(QtWidgets.QWidget):
    def __init__(self, document=None, path=None, parent=None):
        super().__init__(parent)
        self.document = document or Schematic()
        self.path = Path(path) if path else None
        self.history = History(self.document)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.scene = SchematicScene(self)
        self.view = SchematicView(self.scene, self)
        self.status = QtWidgets.QLabel("Drag parts from the library. Connect an output port to an input port.")
        self.status.setWordWrap(True)
        self.properties = QtWidgets.QWidget()
        self.form = QtWidgets.QFormLayout(self.properties)
        self.form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapAllRows)
        self.form.setSpacing(8)
        self.inspector = QtWidgets.QScrollArea()
        self.inspector.setWidgetResizable(True)
        self.inspector.setWidget(self.properties)
        self.inspector.setMinimumWidth(300)
        self.messages = QtWidgets.QListWidget()
        self.messages.setMaximumHeight(125)
        self.messages.itemClicked.connect(self.focus_diagnostic)
        self.toolbar = QtWidgets.QToolBar()
        self.actions = {}
        for name, text, callback, shortcut in (
            ("save", "Save", self.save, "Ctrl+S"),
            ("save_as", "Save As", lambda: self.save(save_as=True), "Ctrl+Shift+S"),
            ("undo", "Undo", self.undo, "Ctrl+Z"),
            ("redo", "Redo", self.redo, "Ctrl+Shift+Z"),
            ("duplicate", "Duplicate", self.duplicate, "Ctrl+D"),
            ("rotate", "Rotate 45°", self.rotate, "R"),
            ("delete", "Delete", self.delete_selected, "Delete"),
            ("fit", "Fit", self.fit, "F"),
            ("directions", "Apply Drawing Directions", self.apply_directions, ""),
            ("validate", "Validate", self.validate, ""),
            ("export", "Export Python…", self.export_python, ""),
        ):
            action = Action(text, self)
            if shortcut:
                action.setShortcut(shortcut)
                action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            action.triggered.connect(lambda checked=False, callback=callback: callback())
            self.addAction(action)
            self.toolbar.addAction(action)
            self.actions[name] = action
        self.toolbar.addSeparator()
        self.grid_toggle = QtWidgets.QCheckBox("Grid snap")
        self.grid_toggle.setChecked(self.document.settings["snap_grid"])
        self.grid_toggle.toggled.connect(lambda value: self.change_setting("snap_grid", value))
        self.toolbar.addWidget(self.grid_toggle)
        self.angle_toggle = QtWidgets.QCheckBox("Angle snap")
        self.angle_toggle.setChecked(self.document.settings["snap_angle"])
        self.angle_toggle.toggled.connect(lambda value: self.change_setting("snap_angle", value))
        self.toolbar.addWidget(self.angle_toggle)
        self.angle_choice = QtWidgets.QComboBox()
        self.angle_choice.addItems(["45°", "90°"])
        self.angle_choice.setCurrentIndex(0 if self.document.settings["angle"] == 45 else 1)
        self.angle_choice.currentIndexChanged.connect(lambda index: self.change_setting("angle", 45 if index == 0 else 90))
        self.toolbar.addWidget(self.angle_choice)
        split = QtWidgets.QSplitter()
        split.addWidget(Palette(self))
        split.addWidget(self.view)
        split.addWidget(self.inspector)
        split.setStretchFactor(1, 1)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.toolbar)
        layout.addWidget(split, 1)
        layout.addWidget(self.messages)
        layout.addWidget(self.status)
        self.resize(1200, 750)
        cancel = Action(self)
        cancel.setShortcut("Esc")
        cancel.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        cancel.triggered.connect(self.scene.cancel_connection)
        self.addAction(cancel)
        self.scene.rebuild()
        self.update_title()

    def selected_nodes(self):
        return [item.node.id for item in self.scene.selectedItems() if isinstance(item, SymbolItem)]

    def commit(self, rebuild=True, selected=None):
        if selected is None:
            selected = self.selected_nodes()
        self.history.commit(self.document)
        self.messages.clear()
        if rebuild:
            self.scene.rebuild(selected)
        self.update_title()

    def update_title(self):
        name = self.path.name if self.path else self.document.title
        self.setWindowTitle(f"{'* ' if self.history.dirty else ''}{name} — Optical Schematic")
        parent = self.parentWidget()
        if isinstance(parent, QtWidgets.QMdiSubWindow):
            parent.setWindowTitle(self.windowTitle())
        self.actions["undo"].setEnabled(self.history.index > 0)
        self.actions["redo"].setEnabled(self.history.index < len(self.history.states) - 1)

    def add_symbol(self, kind, position=None):
        if position is None:
            position = pair(self.view.mapToScene(self.view.viewport().rect().center()))
        settings = self.document.settings
        node = self.document.add_node(kind, snap_point(position, settings["grid"], settings["snap_grid"]))
        self.commit(selected=[node.id])

    def connect_ports(self, source, port, target, target_port="in", bends=None):
        if source == target:
            self.status.setText("A component cannot connect to itself in the first release")
            return False
        for edge in self.document.connections:
            if (edge.source, edge.source_port) == (source, port) or (edge.target, edge.target_port) == (target, target_port):
                self.status.setText("That port is already connected. Delete its connection first.")
                return False
        self.document.connections.append(Connection(new_id(), source, port, target, target_port, bends or []))
        self.status.setText("Connected. Use Validate to check the complete optical topology.")
        return True

    def undo(self):
        self.document = self.history.undo()
        self.restore()

    def redo(self):
        self.document = self.history.redo()
        self.restore()

    def restore(self):
        for widget, value in ((self.grid_toggle, self.document.settings["snap_grid"]),
                              (self.angle_toggle, self.document.settings["snap_angle"])):
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)
        self.angle_choice.blockSignals(True)
        self.angle_choice.setCurrentIndex(0 if self.document.settings["angle"] == 45 else 1)
        self.angle_choice.blockSignals(False)
        self.messages.clear()
        self.scene.rebuild()
        self.update_title()

    def duplicate(self):
        nodes = self.document.duplicate_nodes(self.selected_nodes())
        self.commit(selected=[node.id for node in nodes])

    def rotate(self):
        for node_id in self.selected_nodes():
            node = self.document.node(node_id)
            node.rotation = (node.rotation + 45) % 360
        self.commit()

    def delete_selected(self):
        selected = self.scene.selectedItems()
        edge_ids = {item.connection.id for item in selected if isinstance(item, ConnectionItem)}
        bends = [(item.connection, item.index) for item in selected if isinstance(item, BendItem)]
        for edge, index in sorted(bends, key=lambda item: item[1], reverse=True):
            del edge.bends[index]
        self.document.remove_nodes(self.selected_nodes())
        self.document.connections[:] = [edge for edge in self.document.connections if edge.id not in edge_ids]
        self.commit()

    def fit(self):
        bounds = self.scene.itemsBoundingRect()
        if not bounds.isEmpty():
            self.view.fitInView(bounds.adjusted(-60, -60, 60, 60), Qt.KeepAspectRatio)

    def change_setting(self, key, value):
        self.document.settings[key] = value
        self.commit()

    def apply_directions(self):
        apply_drawing_directions(self.document)
        self.commit()
        self.status.setText("Copied drawing tangents to physical routing hints. Validate mirror turns before exporting.")

    def clear_form(self):
        while self.form.count():
            item = self.form.takeAt(0)
            if item.widget():
                item.widget().blockSignals(True)
                item.widget().hide()
                item.widget().deleteLater()

    def note(self, text):
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        self.form.addRow(label)

    def number_field(self, label, value, callback, minimum=-1000000, maximum=1000000):
        field = QtWidgets.QDoubleSpinBox()
        field.setRange(minimum, maximum)
        field.setDecimals(6)
        field.setValue(value)
        field.setKeyboardTracking(False)
        field.valueChanged.connect(callback)
        self.form.addRow(label, field)
        return field

    def show_properties(self):
        self.clear_form()
        ids = self.selected_nodes()
        if len(ids) != 1:
            title = QtWidgets.QLineEdit(self.document.title)
            title.editingFinished.connect(lambda: self.set_title(title.text()))
            self.form.addRow("Schematic title", title)
            for key, label in (("grid", "Drawing grid"), ("spacing", "Default distance (mm)"),
                               ("open_length", "Open beam length (mm)")):
                self.number_field(label, self.document.settings[key],
                                  lambda value, key=key: self.change_setting(key, value), minimum=0.001)
            self.note("Select one part to edit optical parameters. Drawing positions have no physical scale.")
            return
        node = self.document.node(ids[0])
        symbol = SYMBOLS[node.kind]
        self.form.addRow(QtWidgets.QLabel(symbol.title))
        reference = QtWidgets.QLineEdit(node.reference)
        reference.editingFinished.connect(lambda: self.set_reference(node.id, reference.text()))
        self.form.addRow("Reference", reference)
        presets = QtWidgets.QComboBox()
        presets.addItems(symbol.presets)
        presets.setCurrentText(node.preset)
        presets.currentTextChanged.connect(lambda value: self.set_node_value(node.id, "preset", value))
        self.form.addRow("Part preset", presets)
        for name, value in parameter_values(node).items():
            spec = symbol.parameters[name]
            self.number_field(spec.label, value,
                              lambda value, name=name: self.set_node_dict(node.id, "parameters", name, value))
        self.form.addRow(QtWidgets.QLabel("Physical layout (independent of canvas)"))
        if node.kind in ("source", "fiber_source"):
            for key, label in (("x", "Source X (mm)"), ("y", "Source Y (mm)"), ("angle", "Source direction (deg)")):
                self.number_field(label, node.physical.get(key, 0),
                                  lambda value, key=key: self.set_node_dict(node.id, "physical", key, value))
        elif node.kind != "output":
            self.number_field("From previous part (mm)", node.physical.get("distance", self.document.settings["spacing"]),
                              lambda value: self.set_node_dict(node.id, "physical", "distance", value), minimum=0.001)
        if node.kind in ("mirror", "splitter"):
            turns = (-135, -90, -45, 45, 90, 135) if node.kind == "mirror" else (-90, 90)
            turn = QtWidgets.QComboBox()
            turn.addItems([str(value) for value in turns])
            value = node.physical.get("turn", 90)
            if value not in turns:
                turn.addItem(str(value))
            turn.setCurrentText(str(value))
            turn.currentTextChanged.connect(lambda value: self.set_node_dict(node.id, "physical", "turn", float(value)))
            self.form.addRow("Reflected turn (deg)", turn)
        self.note("Rotate with R. Drawing edits do not change physical layout.")

    def set_title(self, value):
        self.document.title = value or "Optical schematic"
        self.commit(rebuild=False)

    def set_reference(self, node_id, value):
        if not value.strip() or any(node.reference == value and node.id != node_id for node in self.document.nodes):
            self.status.setText("References must be nonempty and unique")
            self.show_properties()
            return
        self.set_node_value(node_id, "reference", value)

    def set_node_value(self, node_id, key, value):
        setattr(self.document.node(node_id), key, value)
        self.commit()

    def set_node_dict(self, node_id, group, key, value):
        getattr(self.document.node(node_id), group)[key] = value
        self.commit(rebuild=False)

    def display_diagnostics(self, diagnostics):
        self.messages.clear()
        for diagnostic in diagnostics:
            item = QtWidgets.QListWidgetItem(diagnostic.message)
            item.setData(Qt.UserRole, (diagnostic.node_id, diagnostic.connection_id))
            self.messages.addItem(item)
        if not diagnostics:
            self.messages.addItem("Topology is valid. Physical placement is checked when the exported Python runs.")

    def validate(self):
        result = compile_schematic(self.document)
        self.display_diagnostics(result.diagnostics)
        return result

    def focus_diagnostic(self, item):
        value = item.data(Qt.UserRole)
        if value:
            node_id, edge_id = value
            target = self.scene.symbols.get(node_id) or self.scene.connections.get(edge_id)
            if target is not None:
                self.scene.clearSelection()
                target.setSelected(True)
                self.view.centerOn(target)

    def save(self, save_as=False):
        path = self.path
        if save_as or path is None:
            name, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save optical schematic", str(path or "optics.pyopticl-schematic.json"),
                "Optical schematic (*.pyopticl-schematic.json)")
            if not name:
                return False
            path = Path(name)
            if not str(path).endswith(".pyopticl-schematic.json"):
                path = Path(str(path) + ".pyopticl-schematic.json")
                if path.exists() and not self.confirm_overwrite(path):
                    return False
        try:
            save_schematic(self.document, path)
        except (OSError, ValueError) as error:
            QtWidgets.QMessageBox.warning(self, "Cannot save schematic", str(error))
            return False
        self.path = path
        self.history.mark_saved()
        self.update_title()
        return True

    def confirm_overwrite(self, path):
        return QtWidgets.QMessageBox.question(self, "Replace file?", f"Replace {path}?",
                                              QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                              QtWidgets.QMessageBox.No) == QtWidgets.QMessageBox.Yes

    def export_python(self):
        result = self.validate()
        if not result.ok:
            self.status.setText("Export blocked. Select a validation message to locate the part.")
            return False
        default = self.path.with_name(self.path.name.removesuffix(".pyopticl-schematic.json") + ".py") if self.path else Path("optics.py")
        name, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export PyOpticL Python", str(default), "Python (*.py)")
        if not name:
            return False
        path = Path(name)
        if path.suffix != ".py":
            path = Path(str(path) + ".py")
            if path.exists() and not self.confirm_overwrite(path):
                return False
        try:
            path.write_text(result.source, encoding="utf-8")
        except OSError as error:
            QtWidgets.QMessageBox.warning(self, "Cannot export Python", str(error))
            return False
        self.status.setText(f"Exported {path}. Run it using the existing PyOpticL macro workflow.")
        return True

    def closeEvent(self, event):
        if self.history.dirty:
            choice = QtWidgets.QMessageBox.question(
                self, "Unsaved schematic", "Save changes before closing?",
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Save)
            if choice == QtWidgets.QMessageBox.Cancel or (choice == QtWidgets.QMessageBox.Save and not self.save()):
                event.ignore()
                return
        event.accept()


class SchematicWindow(QtWidgets.QMdiSubWindow):
    """Let the editor veto a workspace-tab close when it has unsaved edits."""

    def closeEvent(self, event):
        if self.widget().close():
            event.accept()
        else:
            event.ignore()


def open_editor(path=None):
    import FreeCADGui as Gui

    main = Gui.getMainWindow()
    if path is True:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(main, "Open optical schematic", "",
                                                       "Optical schematic (*.pyopticl-schematic.json)")
        if not path:
            return None
    try:
        document = load_schematic(path) if path else Schematic()
    except (OSError, ValueError) as error:
        QtWidgets.QMessageBox.warning(main, "Cannot open schematic", str(error))
        return None
    mdi = main.findChild(QtWidgets.QMdiArea)
    if mdi is None:
        QtWidgets.QMessageBox.warning(main, "Cannot open schematic", "The FreeCAD workspace area is unavailable")
        return None
    if path:
        for window in mdi.subWindowList():
            widget = window.widget()
            if isinstance(widget, SchematicEditor) and widget.path and widget.path.resolve() == Path(path).resolve():
                mdi.setActiveSubWindow(window)
                return widget
    editor = SchematicEditor(document, path)
    window = SchematicWindow(mdi)
    window.setAttribute(Qt.WA_DeleteOnClose)
    window.setWidget(editor)
    mdi.addSubWindow(window)
    editor.update_title()
    window.showMaximized()
    editor.fit()
    return editor
