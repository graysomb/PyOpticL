"""A 2D workspace with Python export and explicit FreeCAD generation."""

from math import ceil, floor
from pathlib import Path
from tempfile import NamedTemporaryFile

from .bounds import BoundsProvider
from .compiler import compile_schematic
from .geometry import apply_drawing_directions, route_connection, route_to, snap_angle, snap_point
from .model import (
    Connection, Endpoint, History, Schematic, connection_length, load_schematic,
    interface_turn, migrate_legacy_lengths, new_id, save_schematic,
)
from .qt import Action, QtCore, QtGui, QtWidgets
from .parts import part_spec
from .registry import SYMBOLS, D_MIRROR_PRESETS, parameter_specs, parameter_values, select_preset
from .topology import resolve_topology

Qt = QtCore.Qt
MIME = "application/x-pyopticl-schematic-symbol"
_open_editors = {}


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
            item = QtWidgets.QListWidgetItem(symbol.title.partition(" (")[0])
            item.setToolTip(symbol.title)
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
    def __init__(self, symbol, name):
        super().__init__(-6, -6, 12, 12, symbol)
        self.symbol, self.name = symbol, name
        self.setPos(point(SYMBOLS[symbol.node.kind].port_position(name)))
        self.setBrush(QtGui.QColor("#8199aa"))
        self.setPen(QtGui.QPen(QtGui.QColor("#1f2937"), 1))
        self.setZValue(3)
        self.setToolTip(f"{symbol.node.reference}.{name} — connect in either order")


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
        for name in spec.ports:
            self.ports[name] = PortItem(self, name)
        label = QtWidgets.QGraphicsSimpleTextItem(node.reference, self)
        label.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
        label.setBrush(QtGui.QColor("#163c54"))
        label.setPos(-16, 32)
        self.setToolTip(f"{node.reference}: {spec.title}\nAny free port can start a connection")
        self.bounds_circle = QtWidgets.QGraphicsEllipseItem(self)
        self.bounds_circle.setFlag(QtWidgets.QGraphicsItem.ItemStacksBehindParent)
        self.bounds_circle.setAcceptedMouseButtons(Qt.NoButton)
        self.bounds_circle.setAcceptHoverEvents(False)
        self.bounds_circle.setPen(QtGui.QPen(QtGui.QColor("#8b9eac"), 1, Qt.DashLine))
        self.bounds_circle.setBrush(QtGui.QBrush(Qt.NoBrush))
        self.bounds_circle.hide()

    def show_bounds(self, circle, scale):
        radius = circle.radius_mm * scale
        self.bounds_circle.setRect(-radius, -radius, 2 * radius, 2 * radius)
        self.bounds_circle.show()

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
        elif kind == "slit":
            for y in (-23,7):
                painter.drawRect(QtCore.QRectF(-10,y,20,16))
        elif kind == "grating":
            painter.drawRect(QtCore.QRectF(-9,-25,18,50))
            for y in range(-20,24,7):
                painter.drawLine(-9,y,9,y-5)
        elif kind == "roof":
            path = QtGui.QPainterPath(QtCore.QPointF(-20,-22))
            path.lineTo(20,0)
            path.lineTo(-20,22)
            painter.drawPath(path)
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
        if edge.a.node_id not in symbols or edge.b.node_id not in symbols:
            return
        start = symbols[edge.a.node_id].ports[edge.a.port_id].scenePos()
        end = symbols[edge.b.node_id].ports[edge.b.port_id].scenePos()
        path = QtGui.QPainterPath(start)
        settings = self.editor.document.settings
        resolved = self.editor.scene.topology.edges.get(edge.id)
        forward = resolved.source == edge.a if resolved else edge.a <= edge.b
        routed = route_connection(pair(start), pair(end), edge.bends, settings, forward)
        for position in routed[1:]:
            path.lineTo(point(position))
        # Arrows follow the source, independently of the connection's click order.
        directed = routed if forward else list(reversed(routed))
        if resolved and len(directed) > 1:
            a, b = point(directed[-2]), point(directed[-1])
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
        description = f"Constrained length: {edge.length:g} mm" if edge.length is not None else f"Default length: {connection_length(self.editor.document, edge):g} mm"
        if edge.length is None and any("x" in node.physical or "y" in node.physical for node in self.editor.document.nodes):
            description += " (adjusts for pinned positions)"
        self.setToolTip(f"{description}\nSelect to edit beam length; select an optic for position and angle constraints; double-click to add a bend")

    def mouseDoubleClickEvent(self, event):
        position = pair(event.scenePos())
        symbols = self.editor.scene.symbols
        starts = [pair(symbols[self.connection.a.node_id].ports[self.connection.a.port_id].scenePos()), *self.connection.bends]
        ends = [*self.connection.bends, pair(symbols[self.connection.b.node_id].ports[self.connection.b.port_id].scenePos())]
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
        self.topology = resolve_topology(editor.document)
        self.pending = None
        self.bends = []
        self.preview = None
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self.selectionChanged.connect(self.selection_changed)

    def rebuild(self, selected=()):
        self.blockSignals(True)
        self.pending, self.preview, self.bends = None, None, []
        self.symbols, self.connections = {}, {}
        self.topology = resolve_topology(self.editor.document)
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
        self.editor.schedule_bounds_refresh()

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
                if self.pending is None:
                    if self.editor.port_connected(Endpoint(hit.symbol.node.id, hit.name)):
                        self.editor.status.setText("That port is already connected. Delete its connection first.")
                        event.accept()
                        return
                    self.pending = (hit.symbol.node.id, hit.name)
                    self.preview = self.addPath(QtGui.QPainterPath(), QtGui.QPen(QtGui.QColor("#e79b36"), 2, Qt.DashLine))
                    self.editor.status.setText("Click to add bends; click any other free port to connect; Esc cancels")
                else:
                    source, port = self.pending
                    if self.pending == (hit.symbol.node.id, hit.name):
                        self.cancel_connection()
                    elif self.editor.connect_ports(source, port, hit.symbol.node.id, hit.name, list(self.bends)):
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
    def __new__(cls,*args,**kwargs):
        if cls is SchematicEditor:
            from .physical_editor import PhysicalSchematicEditor
            return QtWidgets.QWidget.__new__(PhysicalSchematicEditor)
        return QtWidgets.QWidget.__new__(cls)

    def __init__(self, document=None, path=None, parent=None, bounds_provider=None):
        super().__init__(parent)
        self.document = document or Schematic()
        migrate_legacy_lengths(self.document)
        self.path = Path(path) if path else None
        self.history = History(self.document)
        self.bounds_provider = bounds_provider or BoundsProvider()
        self.bounds_info = None
        self.bounds_timer = QtCore.QTimer(self)
        self.bounds_timer.setSingleShot(True)
        self.bounds_timer.timeout.connect(self.update_part_bounds)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.scene = SchematicScene(self)
        self.view = SchematicView(self.scene, self)
        self.status = QtWidgets.QLabel("Connect any two free ports. Beam direction is inferred from the source.")
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
            ("refresh_bounds", "Refresh bounds", self.refresh_part_bounds, ""),
            ("directions", "Apply Drawing Directions", self.apply_directions, ""),
            ("path_lengths", "Path lengths…", self.edit_path_lengths, ""),
            ("optimize", "Optimize physical layout…", self.optimize_physical_layout, ""),
            ("clear_optimized", "Clear optimized layout", self.clear_optimized_layout, ""),
            ("validate", "Validate", self.validate, ""),
            ("export", "Export Python…", self.export_python, ""),
            ("generate_cad", "Generate CAD…", self.generate_cad, ""),
        ):
            action = Action(text, self)
            if shortcut:
                action.setShortcut(shortcut)
                action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            action.triggered.connect(lambda checked=False, callback=callback: callback())
            self.addAction(action)
            self.toolbar.addAction(action)
            self.actions[name] = action
        self.actions["generate_cad"].setToolTip(
            "Build a new 3D assembly and save a FreeCAD file with its generated Python."
        )
        self.toolbar.addSeparator()
        self.baseplate_toggle = QtWidgets.QCheckBox("Baseplate")
        self.baseplate_toggle.setObjectName("generateBaseplate")
        self.baseplate_toggle.setChecked(self.document.settings["generate_baseplate"])
        self.baseplate_toggle.setToolTip("Include a machined plate beneath supported mounted components.")
        self.baseplate_toggle.toggled.connect(lambda value: self.change_setting("generate_baseplate", value))
        self.toolbar.addWidget(self.baseplate_toggle)
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
        self.bounds_toggle = QtWidgets.QCheckBox("Part bounds")
        self.bounds_toggle.setObjectName("partBoundsToggle")
        self.bounds_toggle.setChecked(self.document.settings["show_bounds"])
        self.bounds_toggle.setToolTip("Show physical assembly circles. Their common size scale is independent of topological drawing positions.")
        self.bounds_toggle.toggled.connect(lambda value: self.change_setting("show_bounds", value))
        self.toolbar.insertWidget(self.actions["refresh_bounds"], self.bounds_toggle)
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
        cancel.triggered.connect(lambda:self.scene.cancel_connection())
        self.addAction(cancel)
        self.scene.rebuild()
        self.update_title()

    def selected_nodes(self):
        return [item.node.id for item in self.scene.selectedItems() if isinstance(item, SymbolItem)]

    def commit(self, rebuild=True, selected=None):
        if selected is None:
            selected = self.selected_nodes()
        migrate_legacy_lengths(self.document)
        self.history.commit(self.document)
        self.messages.clear()
        if rebuild:
            self.scene.rebuild(selected)
        else:
            self.schedule_bounds_refresh()
        self.update_title()
        saved = self.document.optimized_layout
        if saved is not None:
            from .optimization import input_fingerprint
            current = saved.get("input_version") == (6 if self.document.layout is not None else 5) and input_fingerprint(
                self.document,self.document.optimization,saved["radii"],folding_radius=saved.get("folding_radius")) == saved["fingerprint"]
            if not current:
                self.status.setText("Optimized layout is stale. Rerun Optimize physical layout or Clear optimized layout before export.")

    def update_title(self):
        name = self.path.name if self.path else self.document.title
        self.setWindowTitle(f"{'* ' if self.history.dirty else ''}{name} — Optical Schematic")
        parent = self.parentWidget()
        if isinstance(parent, QtWidgets.QMdiSubWindow):
            parent.setWindowTitle(self.windowTitle())
        self.actions["undo"].setEnabled(self.history.index > 0)
        self.actions["redo"].setEnabled(self.history.index < len(self.history.states) - 1)
        self.actions["refresh_bounds"].setEnabled(self.document.settings["show_bounds"] or self.document.optimized_layout is not None)
        self.actions["clear_optimized"].setEnabled(self.document.optimized_layout is not None)

    def add_symbol(self, kind, position=None):
        if position is None:
            position = pair(self.view.mapToScene(self.view.viewport().rect().center()))
        settings = self.document.settings
        node = self.document.add_node(kind, snap_point(position, settings["grid"], settings["snap_grid"]))
        self.commit(selected=[node.id])

    def port_connected(self, endpoint):
        return any(endpoint in (edge.a, edge.b) for edge in self.document.connections)

    def connect_ports(self, source, port, target, target_port, bends=None):
        if source == target:
            self.status.setText("A component cannot connect to itself in the first release")
            return False
        a, b = Endpoint(source, port), Endpoint(target, target_port)
        for endpoint in (a, b):
            try:
                valid = endpoint.port_id in SYMBOLS[self.document.node(endpoint.node_id).kind].ports
            except StopIteration:
                valid = False
            if not valid:
                self.status.setText("The connection refers to an invalid component or port")
                return False
            if self.port_connected(endpoint):
                self.status.setText("That port is already connected. Delete its connection first.")
                return False
        self.document.connections.append(Connection(new_id(), a, b, bends or []))
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
                              (self.baseplate_toggle, self.document.settings["generate_baseplate"]),
                              (self.angle_toggle, self.document.settings["snap_angle"]),
                              (self.bounds_toggle, self.document.settings["show_bounds"])):
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
        bounds = QtCore.QRectF()
        for item in self.scene.items():
            if item.isVisible():
                bounds = bounds.united(item.sceneBoundingRect())
        if not bounds.isEmpty():
            self.view.fitInView(bounds.adjusted(-60, -60, 60, 60), Qt.KeepAspectRatio)

    def change_setting(self, key, value):
        self.document.settings[key] = value
        # Display-only edits keep the current symbol/beam selection and widgets.
        self.commit(rebuild=key not in ("show_bounds", "bounds_scale"))

    def schedule_bounds_refresh(self):
        if self.document.settings["show_bounds"]:
            if not self.bounds_timer.isActive():
                self.bounds_timer.start(0)
        else:
            self.bounds_timer.stop()
            for item in self.scene.symbols.values():
                item.bounds_circle.hide()
        self.update_bounds_info()

    def refresh_part_bounds(self):
        self.bounds_provider.clear()
        self.schedule_bounds_refresh()

    def update_part_bounds(self):
        if not self.document.settings["show_bounds"]:
            return
        # FreeCAD may activate its temporary document's view. Keep this
        # schematic workspace active when the batch completes, even on error.
        parent = self.parentWidget()
        area = parent.mdiArea() if isinstance(parent, QtWidgets.QMdiSubWindow) else None
        previous = area.activeSubWindow() if area is not None else None
        try:
            for node in self.document.nodes:
                item = self.scene.symbols[node.id]
                spec = part_spec(self.document, node, self.scene.topology)
                if spec is None:
                    item.bounds_circle.hide()
                    continue
                result = self.bounds_provider.get(spec)
                if result.circle is not None:
                    item.show_bounds(result.circle, self.document.settings["bounds_scale"])
                else:
                    item.bounds_circle.hide()
        finally:
            if area is not None and previous is not None:
                area.setActiveSubWindow(previous)
        self.update_bounds_info()

    def update_bounds_info(self):
        if self.bounds_info is None:
            return
        ids = self.selected_nodes()
        if len(ids) != 1:
            return
        node = self.document.node(ids[0])
        spec = part_spec(self.document, node, self.scene.topology)
        result = self.bounds_provider.peek(spec) if spec is not None else None
        if result is not None and result.circle is not None:
            circle = result.circle
            self.bounds_info.setText(f"Physical XY bounds: radius {circle.radius_mm:.3f} mm; diameter {circle.diameter_mm:.3f} mm. Includes the modeled assembly.")
        elif result is not None:
            self.bounds_info.setText(f"Physical bounds unavailable: {result.error}")
        elif self.document.settings["show_bounds"]:
            self.bounds_info.setText("Calculating physical XY bounds…")
        else:
            self.bounds_info.setText("Enable Part bounds to calculate the physical assembly circle.")

    def edit_path_lengths(self):
        from .path_dialog import PathLengthsDialog
        selected = self.selected_nodes()
        dialog = PathLengthsDialog(self.document, selected, self)

        def highlight(route):
            self.scene.clearSelection()
            for key in route:
                if key in self.scene.connections:
                    self.scene.connections[key].setSelected(True)
        dialog.route_selected.connect(highlight)
        dialog.endpoints_changed()
        method = getattr(dialog, "exec", None) or dialog.exec_
        if method() == QtWidgets.QDialog.Accepted:
            self.document.path_constraints = dialog.constraints
            if dialog.solution is not None:
                from copy import deepcopy

                self.document.layout = deepcopy(dialog.document.layout)
                self.document.optimized_layout = deepcopy(dialog.document.optimized_layout)
            self.commit(selected=selected)
        else:
            self.scene.clearSelection()
            for key in selected:
                if key in self.scene.symbols:
                    self.scene.symbols[key].setSelected(True)
        dialog.deleteLater()

    def omitted_mirrors(self):
        saved = self.document.optimized_layout
        if not saved or "graph" not in saved:
            return set()
        original_ids = {node.id for node in self.document.nodes}
        return {edit["node_id"] for edit in saved["graph"]["edits"]
                if edit["action"] == "remove" and edit["node_id"] in original_ids}

    def optimize_physical_layout(self):
        from .optimize_dialog import OptimizeLayoutDialog

        dialog = OptimizeLayoutDialog(self.document, self.bounds_provider, self)
        method = getattr(dialog, "exec", None) or dialog.exec_
        if method() == QtWidgets.QDialog.Accepted:
            self.apply_optimized_result(dialog.problem, dialog.solution)
        dialog.deleteLater()

    def apply_optimized_result(self, problem, result):
        from .optimization import apply_optimization

        try:
            apply_optimization(self.document, problem, result)
        except ValueError as error:
            self.status.setText(str(error))
            return False
        self.commit()
        self.status.setText("Optimized physical layout applied for export. Drawing positions and explicit constraints are preserved.")
        return True

    def clear_optimized_layout(self):
        if self.document.optimized_layout is not None:
            self.document.optimized_layout = None
            self.commit()
            self.status.setText("Optimized layout cleared. Export uses deterministic default geometry again.")

    def apply_directions(self):
        diagnostics = apply_drawing_directions(self.document)
        self.commit()
        self.display_diagnostics(diagnostics)
        self.status.setText("Copied source-resolved tangents where available. Resolve any topology errors before exporting.")

    def clear_form(self):
        self.bounds_info = None
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
        return label

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
        if self.document.optimized_layout is not None:
            from .optimization import input_fingerprint

            saved = self.document.optimized_layout
            current = saved.get("input_version") == (6 if self.document.layout is not None else 5) and input_fingerprint(self.document, self.document.optimization, saved["radii"], folding_radius=saved.get("folding_radius")) == saved["fingerprint"]
            self.note("Optimized physical values are shown below; free values remain unconstrained." if current else
                      "Optimized layout is stale. Rerun Optimize physical layout or Clear optimized layout before export.")
        selected = self.scene.selectedItems()
        if len(selected) == 1 and isinstance(selected[0], ConnectionItem):
            self.show_beam_properties(selected[0].connection)
            return
        ids = self.selected_nodes()
        if len(ids) != 1:
            title = QtWidgets.QLineEdit(self.document.title)
            title.editingFinished.connect(lambda: self.set_title(title.text()))
            self.form.addRow("Schematic title", title)
            self.number_field("Plate thickness (mm)", self.document.settings["plate_thickness"],
                              lambda value: self.change_setting("plate_thickness", value), 10.001)
            self.number_field("Plate edge margin (mm)", self.document.settings["plate_margin"],
                              lambda value: self.change_setting("plate_margin", value), 3)
            for key, label in (("grid", "Drawing grid"), ("spacing", "Default beam length (mm)"),
                               ("open_length", "Default open beam length (mm)"),
                               ("bounds_scale", "Bounds scale (canvas units/mm)")):
                self.number_field(label, self.document.settings[key],
                                  lambda value, key=key: self.change_setting(key, value), minimum=0.001)
            self.note("Select an optical element for optical parameters, position, and supported angle constraints, or a beam to constrain its length. Drawing positions have no physical scale.")
            self.note("Part bounds enclose modeled physical assemblies at a shared display scale. Circle overlaps on this topological drawing are not physical collision checks.")
            return
        node = self.document.node(ids[0])
        symbol = SYMBOLS[node.kind]
        self.form.addRow(QtWidgets.QLabel(symbol.title))
        reference = QtWidgets.QLineEdit(node.reference)
        reference.editingFinished.connect(lambda: self.set_reference(node.id, reference.text()))
        self.form.addRow("Reference", reference)
        presets = QtWidgets.QComboBox()
        labels = {("splitter","displacement_pbs"):"Displacement PBS + integral seat",
                  ("iris","alignment"):"Fixed alignment iris",
                  ("grating","MK05S"):"MK05S + plate adapter",
                  ("roof","horizontal"):"Horizontal + supports",
                  ("roof","vertical"):"Vertical + supports",
                  ("roof","bare_horizontal"):"Horizontal, bare",
                  ("roof","bare_vertical"):"Vertical, bare"}
        for preset, optic in D_MIRROR_PRESETS.items():
            labels[("mirror", preset)] = (f"{preset} · D-shaped, bare" if preset == optic
                                         else f"{preset} + {optic} · D-shaped")
        presets.setObjectName("partPreset")
        for preset in symbol.presets:
            presets.addItem(labels.get((node.kind,preset),preset),preset)
        presets.setCurrentIndex(presets.findData(node.preset))
        presets.currentIndexChanged.connect(lambda index: self.set_node_value(node.id,"preset",presets.itemData(index)))
        self.form.addRow("Part preset", presets)
        for name, value in parameter_values(node).items():
            spec = parameter_specs(node)[name]
            callback = lambda value, name=name: self.set_node_dict(node.id,"parameters",name,value)
            if node.kind == "grating" and name == "mirrored":
                field = QtWidgets.QCheckBox(spec.label)
                field.setChecked(bool(value))
                field.toggled.connect(lambda checked, callback=callback: callback(int(checked)))
                self.form.addRow(field)
            elif spec.integer:
                field = QtWidgets.QSpinBox()
                field.setRange(int(spec.minimum if spec.minimum is not None else -1000000),
                               int(spec.maximum if spec.maximum is not None else 1000000))
                field.setValue(int(value))
                field.setKeyboardTracking(False)
                field.valueChanged.connect(callback)
                self.form.addRow(spec.label,field)
            else:
                field = self.number_field(spec.label,value,callback)
            if spec.minimum is not None and spec.minimum == spec.maximum:
                field.setEnabled(False)
            field.setObjectName("componentParameter_"+name)
        if node.kind == "roof":
            self.note("Fixed two-reflection return with separate entry/exit points. Vertical presets change beam height; packing uses conservative XY bounds.")
        elif node.kind == "grating":
            self.note("Diffraction direction follows source wavelength, incidence and order. These are fixed optical relationships during optimization.")
        if node.kind not in ("source", "output"):
            self.bounds_info = self.note("")
            self.update_bounds_info()
        if node.kind == "mirror":
            role = QtWidgets.QComboBox()
            role.setObjectName("mirrorRole")
            role.addItems(["Turning", "Folding"])
            role.setCurrentIndex(1 if node.mirror_role == "folding" else 0)
            role.currentIndexChanged.connect(lambda index: self.set_node_value(node.id, "mirror_role", "folding" if index else "turning"))
            self.form.addRow("Mirror role", role)
            from .effective import folding_protection
            self.note(folding_protection(self.document, node.id) or "Eligible for removal when its interior arm angle exceeds the optimizer threshold.")
            self.note("The Turning role prevents removal; angle constraints are controlled separately.")
        self.form.addRow(QtWidgets.QLabel("Physical layout (independent of canvas)"))
        if node.id in self.omitted_mirrors():
            self.note("Omitted from the last optimized physical layout. No current physical position is available. Adding a constraint protects this mirror on the next run.")
            position_button = QtWidgets.QPushButton("Set position constraint…")
            position_button.clicked.connect(lambda: self.constrain_omitted_position(node.id))
            angle_button = QtWidgets.QPushButton("Set angle constraint…")
            angle_button.clicked.connect(lambda: self.constrain_omitted_angle(node.id))
            self.form.addRow(position_button)
            self.form.addRow(angle_button)
            return
        self.show_position_property(node)
        if node.kind in ("source", "fiber_source"):
            self.show_source_direction_property(node)
        elif symbol.role == "terminal":
            self.show_endpoint_direction_property(node, source=False)
        if node.kind in ("mirror", "splitter"):
            self.show_angle_property(node)
        if "distance" in node.physical:
            self.note(f"Legacy length {node.physical['distance']:g} mm will transfer to the incoming beam when source direction is resolved.")
        self.note("Select a connecting beam to constrain its length. Rotate with R. Drawing edits do not change physical layout.")

    def show_beam_properties(self, edge):
        self.note("Beam connection")
        a, b = self.document.node(edge.a.node_id), self.document.node(edge.b.node_id)
        self.note(f"{a.reference}.{edge.a.port_id} ↔ {b.reference}.{edge.b.port_id}")
        folding = QtWidgets.QCheckBox("Allow folding")
        folding.setObjectName("beamAllowFolding")
        folding.setChecked(edge.allow_folding)
        folding.toggled.connect(lambda value: self.set_connection_folding(edge.id, value))
        self.form.addRow(folding)
        compiled = compile_schematic(self.document)
        omitted = bool({edge.a.node_id, edge.b.node_id} & self.omitted_mirrors())
        if omitted:
            self.note("This beam belongs to a merged physical span. Its original endpoint separation is unavailable. Enabling its length constraint retains the omitted endpoint on the next run.")
            if compiled.geometry is not None:
                included = {edge.id}
                while True:
                    expanded = included | {key for segment in compiled.geometry.graph.segments
                                           if included.intersection(segment.logical_ids) for key in segment.logical_ids}
                    if expanded == included:
                        break
                    included = expanded
                merged = sum(compiled.geometry.lengths[segment.id] for segment in compiled.geometry.graph.segments
                             if included.intersection(segment.logical_ids))
                self.note(f"Merged physical path: {merged:.6f} mm")
        elif edge.id in compiled.routed_lengths:
            self.note(f"Routed length including folds: {compiled.routed_lengths[edge.id]:.6f} mm")
        if compiled.geometry is not None and compiled.geometry.graph is not None:
            from .effective import effective_document
            from .optimization import OptimizationOptions
            added = [item for item in compiled.geometry.graph.generated if edge.id in item.logical_ids]
            if added:
                physical = effective_document(self.document, compiled.geometry.graph,
                                              OptimizationOptions(**self.document.optimization["options"]))
                for item in added:
                    mirror = physical.node(item.id)
                    x, y = compiled.geometry.positions[item.id]
                    self.note(f"{mirror.reference}: added Folding mirror ({mirror.preset}, "
                              f"{mirror.parameters['diameter']:g} mm). Physical XY: ({x:.6f}, {y:.6f}) mm.")
        constrained = QtWidgets.QCheckBox("Constrain beam length")
        constrained.setObjectName("beamLengthConstrained")
        constrained.setChecked(edge.length is not None)
        self.form.addRow(constrained)
        length = self.number_field("Length target (mm)" if omitted else "Endpoint separation (mm)", self.effective_beam_length(edge),
                                   lambda value: self.set_connection_length(edge.id, value)
                                   if edge.length is not None else None, minimum=0.001)
        length.setObjectName("beamLengthMm")
        length.setEnabled(constrained.isChecked())

        def toggle(checked):
            length.setEnabled(checked)
            self.set_connection_length(edge.id, length.value() if checked else None)
            if not checked:
                length.setValue(self.effective_beam_length(edge))

        constrained.toggled.connect(toggle)
        self.note("Physical separation between the connected optical interaction points. Free lengths use the applied optimization when available; otherwise they use defaults and adjust to pinned positions. Drawn bends and spacing have no physical scale.")
        self.note("Select a mirror or beamsplitter to enable or edit its angle constraint.")

    def effective_beam_length(self, edge):
        return compile_schematic(self.document).lengths.get(edge.id, connection_length(self.document, edge))

    def effective_turn(self, node):
        geometry = compile_schematic(self.document).geometry
        return geometry.turns[node.id] if geometry is not None else interface_turn(self.document, node, self.scene.topology)

    def show_source_direction_property(self, node):
        self.show_endpoint_direction_property(node, source=True)

    def effective_endpoint_direction(self, node):
        from .physical import physical_layout, wrap_angle
        geometry = compile_schematic(self.document).geometry
        if geometry is None and self.scene.topology.ok:
            geometry = physical_layout(self.document, self.scene.topology)
        if geometry is None:
            return 0
        if SYMBOLS[node.kind].role == "source":
            return wrap_angle(geometry.source_direction)
        # A receiving part faces against the arriving beam. The constraint
        # always describes travel direction, including virtual open outputs.
        return wrap_angle(geometry.orientations[node.id] - (180 if node.kind in ("fiber_output", "stop") else 0))

    def show_endpoint_direction_property(self, node, source):
        label = "source" if source else "output"
        constrained = QtWidgets.QCheckBox(f"Constrain {label} direction")
        constrained.setObjectName(label + "DirectionConstrained")
        constrained.setChecked("angle" in node.physical)
        self.form.addRow(constrained)
        value = node.physical.get("angle", self.effective_endpoint_direction(node))
        angle = self.number_field(f"{label.title()} direction (deg)", value,
                                  lambda value: self.set_endpoint_direction(node.id, value)
                                  if constrained.isChecked() else None)
        angle.setObjectName(label + "DirectionDeg")
        angle.setEnabled(constrained.isChecked())

        def toggle(checked):
            angle.setEnabled(checked)
            self.set_endpoint_direction(node.id, angle.value() if checked else None)
            if not checked:
                angle.setValue(self.effective_endpoint_direction(node))

        constrained.toggled.connect(toggle)
        if not source:
            self.note("Absolute XY direction of the beam arriving at this output: 0° is right, +90° is up. This is independent of the drawn symbol rotation. Optimization can adjust free upstream optics to satisfy it.")

    def set_source_direction(self, node_id, value):
        self.set_endpoint_direction(node_id, value)

    def set_endpoint_direction(self, node_id, value):
        node = self.document.node(node_id)
        if value is None:
            node.physical.pop("angle", None)
        else:
            node.physical["angle"] = value
        self.commit(rebuild=False)

    def show_position_property(self, node):
        def current_position():
            placement = compile_schematic(self.document).placements.get(node.reference, (0, 0, 0))
            return tuple(node.physical.get(key, placement[axis]) for axis, key in enumerate(("x", "y")))

        constrained = QtWidgets.QCheckBox("Constrain position")
        constrained.setObjectName("opticPositionConstrained")
        constrained.setChecked("x" in node.physical or "y" in node.physical)
        self.form.addRow(constrained)
        initial = current_position()

        def update_position(_value):
            if constrained.isChecked():
                self.set_optic_position(node.id, (x.value(), y.value()))

        x = self.number_field("X (mm)", initial[0], update_position)
        y = self.number_field("Y (mm)", initial[1], update_position)
        x.setObjectName("opticPositionX")
        y.setObjectName("opticPositionY")
        for field in (x, y):
            field.setEnabled(constrained.isChecked())

        def toggle(checked):
            for field in (x, y):
                field.setEnabled(checked)
            self.set_optic_position(node.id, (x.value(), y.value()) if checked else None)
            if not checked:
                px, py = current_position()
                x.setValue(px)
                y.setValue(py)

        constrained.toggled.connect(toggle)
        self.note("Physical X/Y of the optical interaction point, in mm. Free beam lengths adjust along the current beam directions to reach it. Conflicting constraints block export; drawing positions are independent.")

    def set_optic_position(self, node_id, position):
        node = self.document.node(node_id)
        if position is None:
            node.physical.pop("x", None)
            node.physical.pop("y", None)
        else:
            node.physical.update(x=position[0], y=position[1])
        self.commit(rebuild=False)

    def show_angle_property(self, node):
        legacy = [edge.turns[node.id] for edge in self.document.connections if node.id in edge.turns]
        constrained = QtWidgets.QCheckBox("Constrain angle")
        constrained.setObjectName("opticAngleConstrained")
        constrained.setChecked("turn" in node.physical or bool(legacy))
        self.form.addRow(constrained)
        label = "Reflected turn (deg)" if node.kind == "splitter" else "Turn (deg)"
        angle = self.number_field(label, self.effective_turn(node),
                                  lambda value: self.set_optic_turn(node.id, value)
                                  if constrained.isChecked() else None,
                                  minimum=-179.999999, maximum=179.999999)
        angle.setObjectName("opticAngleDeg")
        angle.setEnabled(constrained.isChecked())
        angle.setToolTip("Signed direction change in degrees; absolute value must be at least 0.001° and less than 180°.")

        def toggle(checked):
            angle.setEnabled(checked)
            self.set_optic_turn(node.id, angle.value() if checked else None)
            if not checked:
                angle.setValue(self.effective_turn(node))

        constrained.toggled.connect(toggle)
        if legacy:
            angle.editingFinished.connect(lambda: self.set_optic_turn(node.id, angle.value())
                                          if constrained.isChecked() else None)
        if legacy and max(legacy) - min(legacy) > 1e-6:
            self.note("This optic has conflicting angles from an older drawing. Enter the desired angle here, or turn the constraint off, to resolve them.")
        self.note("Turn is the change in beam direction at this optic. Positive is counterclockwise; negative is clockwise. 90° is a right-angle bend. Free turns may change during optimization; otherwise they use the resolved port's default turn. Drawn bends do not set this angle.")
        if node.kind == "splitter":
            self.note("The angle controls the reflected branch; transmission continues straight.")

    def set_optic_turn(self, node_id, value):
        node = self.document.node(node_id)
        # Older angle constraints were stored on adjacent beams. Editing the
        # optic consolidates them into one setting, including conflicting ones.
        for edge in self.document.connections:
            edge.turns.pop(node_id, None)
        if value is None:
            node.physical.pop("turn", None)
        else:
            node.physical["turn"] = value
        self.commit(rebuild=False)

    def constrain_omitted_position(self, node_id):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Set physical position target")
        form = QtWidgets.QFormLayout(dialog)
        fields = []
        for axis in ("x", "y"):
            field = QtWidgets.QDoubleSpinBox()
            field.setRange(-1e6, 1e6)
            field.setDecimals(6)
            field.setValue(self.document.node(node_id).physical.get(axis, 0))
            form.addRow(axis.upper()+" target (mm)", field)
            fields.append(field)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        method = getattr(dialog, "exec", None) or dialog.exec_
        if method() == QtWidgets.QDialog.Accepted:
            self.set_optic_position(node_id, tuple(field.value() for field in fields))
            self.show_properties()

    def constrain_omitted_angle(self, node_id):
        angle, ok = QtWidgets.QInputDialog.getDouble(self, "Set angle target", "Signed direction change (deg)",
                                                     interface_turn(self.document, self.document.node(node_id), self.scene.topology),
                                                     -179.999999, 179.999999, 6)
        if ok:
            self.set_optic_turn(node_id, angle)
            self.show_properties()

    def set_connection_folding(self, connection_id, value):
        self.document.connection(connection_id).allow_folding = value
        self.commit(rebuild=False)

    def set_connection_length(self, connection_id, value):
        self.document.connection(connection_id).length = value
        self.scene.connections[connection_id].refresh()
        self.commit(rebuild=False)

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
        if key == "preset":
            select_preset(self.document.node(node_id),value)
        else:
            setattr(self.document.node(node_id), key, value)
        self.commit()

    def set_node_dict(self, node_id, group, key, value):
        getattr(self.document.node(node_id), group)[key] = value
        self.commit(rebuild=False)

    def display_diagnostics(self, diagnostics):
        self.messages.clear()
        for diagnostic in diagnostics:
            item = QtWidgets.QListWidgetItem(diagnostic.message)
            item.setData(Qt.UserRole, (diagnostic.node_id, diagnostic.connection_id, diagnostic.constraint_id))
            self.messages.addItem(item)
        if not diagnostics:
            self.messages.addItem("Directions are resolved from the source. Physical placement is checked when the exported Python runs.")

    def validate(self):
        result = compile_schematic(self.document)
        self.display_diagnostics(result.diagnostics)
        return result

    def focus_diagnostic(self, item):
        value = item.data(Qt.UserRole)
        if value:
            node_id, edge_id, constraint_id = value
            if constraint_id:
                from .paths import component_path
                constraint = next((item for item in self.document.path_constraints if item.id == constraint_id), None)
                if constraint is not None:
                    try:
                        route = component_path(self.document, constraint.component_a, constraint.component_b)
                    except ValueError:
                        route = ()
                    self.scene.clearSelection()
                    for key in route:
                        self.scene.connections[key].setSelected(True)
                    if route:
                        self.view.centerOn(self.scene.connections[route[len(route) // 2]])
                        return
            target = self.scene.connections.get(edge_id) or self.scene.symbols.get(node_id)
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
            from .cad import generation_source

            path.write_text(generation_source(result.source, self.document.settings), encoding="utf-8")
        except OSError as error:
            QtWidgets.QMessageBox.warning(self, "Cannot export Python", str(error))
            return False
        self.status.setText(f"Exported {path}. Run it using the existing PyOpticL macro workflow.")
        return True

    def generate_cad(self):
        result = self.validate()
        if not result.ok:
            self.status.setText("CAD generation blocked. Select a validation message to locate the part.")
            return False
        default = (self.path.with_name(self.path.name.removesuffix(".pyopticl-schematic.json") + ".FCStd")
                   if self.path else Path("optics.FCStd"))
        name, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Generate CAD and Python", str(default), "FreeCAD document (*.FCStd)"
        )
        if not name:
            return False
        path = Path(name)
        if path.suffix.lower() != ".fcstd":
            path = Path(str(path) + ".FCStd")
            if path.exists() and not self.confirm_overwrite(path):
                return False
        python_path = path.with_suffix(".py")
        if python_path.exists() and not self.confirm_overwrite(python_path):
            return False
        document = None
        temporary = None
        self.actions["generate_cad"].setEnabled(False)
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from .cad import build_cad, generation_source

            source = generation_source(result.source, self.document.settings)

            # Stage the source first so an unwritable destination cannot leave
            # a freshly built document or overwrite an existing Python file.
            with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".py", dir=path.parent,
                                    delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(source)
            document = build_cad(source, self.document.title)
            document.saveAs(str(path))
            temporary.replace(python_path)
        except Exception as error:
            message = ("CAD was built and remains open, but its files could not both be saved. "
                       if document is not None else "CAD generation failed. ") + str(error)
            self.status.setText(message)
            QtWidgets.QMessageBox.warning(self, "Cannot generate CAD", message)
            return False
        finally:
            try:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
                self.actions["generate_cad"].setEnabled(True)
        self.status.setText(f"Generated {path} and {python_path}. The 3D assembly is open in FreeCAD.")
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


class LegacySchematicEditor(SchematicEditor):
    """Compatibility canvas for historical document/rendering regression tests."""
    pass


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
    from .physical_editor import PhysicalSchematicEditor
    editor = PhysicalSchematicEditor(document, path)
    window = SchematicWindow(mdi)
    window.setAttribute(Qt.WA_DeleteOnClose)
    window.setWidget(editor)
    mdi.addSubWindow(window)
    # Keep Python-created tabs and the host wrappers reachable while open.
    # Numerical work can otherwise trigger cyclic collection of Qt wrappers.
    editor._workspace_refs = (main, mdi, window)
    key = id(editor)
    _open_editors[key] = editor
    editor.destroyed.connect(lambda *_: _open_editors.pop(key, None))
    editor.update_title()
    window.showMaximized()
    editor.fit()
    return editor
