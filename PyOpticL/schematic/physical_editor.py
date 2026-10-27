"""Millimetre scene with shared optics, explicit passes and cancellable live solves."""

from copy import deepcopy
from itertools import product
from math import sin, cos, pi
from threading import Event
from .qt import Action, QtCore, QtGui, QtWidgets, exec_menu
from .editor import (
    SchematicEditor as BaseEditor,
    SymbolItem,
    PortItem,
    ConnectionItem,
    SchematicScene,
    SchematicView,
    point,
    pair,
)
from .model import Schematic, History, Endpoint, Connection, OpticalPass, new_id, document_from_dict
from .registry import SYMBOLS, parameter_values
from .topology import resolve_topology
from .scene_layout import initialize_layout, trace_scene, poses_for, source_offset
from .scene_solver import solve_scene, apply_scene_solution
from .optic_geometry import element_spec
from .geometry import snap_point
from PyOpticL.ray_math import add, yaw, heading

Qt = QtCore.Qt


def project(p, plane):
    return QtCore.QPointF(p[0], -p[1 if plane == "XY" else 2])


def hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo = []
    hi = []
    for p in pts:
        while len(lo) > 1 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) > 1 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


class PhysicalPort(PortItem):
    def __init__(self, symbol, visit, name):
        QtWidgets.QGraphicsEllipseItem.__init__(self, -4, -4, 8, 8, symbol)
        self.symbol, self.name, self.visit = symbol, name, visit
        self.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
        self.setBrush(QtGui.QColor("#8199aa"))
        self.setPen(QtGui.QPen(QtGui.QColor("#163c54"), 1))
        self.setZValue(4)
        self.setToolTip(f"{symbol.node.reference} · {visit}: {name}. Right-click for pass/port choices.")

    @property
    def endpoint(self):
        return Endpoint(
            self.symbol.node.id, self.name, "" if self.visit == self.symbol.node.id else self.visit
        )


class PhysicalSymbol(SymbolItem):
    def __init__(self, node, editor):
        QtWidgets.QGraphicsObject.__init__(self)
        self.node, self.editor = node, editor
        self.setFlags(
            QtWidgets.QGraphicsItem.ItemIsMovable
            | QtWidgets.QGraphicsItem.ItemIsSelectable
            | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(2)
        self.ports = {}
        self.outline = QtGui.QPainterPath()
        self.rectangle = QtCore.QRectF(-1, -1, 2, 2)
        if node.id not in {n.id for n in editor.document.nodes}:
            self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, False)
        self.label = QtWidgets.QGraphicsSimpleTextItem(node.reference, self)
        self.label.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
        self.bounds_circle = QtWidgets.QGraphicsEllipseItem(self)
        self.bounds_circle.setFlag(QtWidgets.QGraphicsItem.ItemStacksBehindParent)
        self.bounds_circle.setAcceptedMouseButtons(Qt.NoButton)
        self.bounds_circle.setPen(QtGui.QPen(QtGui.QColor("#8b9eac"), 0, Qt.DashLine))
        self.bounds_circle.hide()
        for visit in editor.document.optical_passes():
            if visit.component_id == node.id:
                for name in SYMBOLS[node.kind].ports:
                    self.ports[(visit.id, name)] = PhysicalPort(self, visit.id, name)
        self.refresh()

    def refresh(self):
        editor = self.editor
        plane = editor.projection
        pose = editor.display_poses().get(self.node.id, [0, 0, 0, 0])
        self.prepareGeometryChange()
        self.setPos(project(pose, plane))
        spec = element_spec(self.node, editor.scene.topology)
        self.outline = QtGui.QPainterPath()
        if spec:
            extra = spec.normal_angle if self.node.kind == "grating" else 0
            corners = []
            points = [
                tuple(spec.corner[i] + bits[i] * spec.size[i] for i in range(3))
                for bits in product((0, 1), repeat=3)
            ]
            if self.node.kind in ("mirror", "lens", "hwp", "qwp", "stop", "fiber_source", "fiber_output") or (
                self.node.kind == "iris" and self.node.preset != "alignment"
            ):
                radius = spec.size[1] / 2
                points = [
                    (
                        spec.corner[0] + end * spec.size[0],
                        radius * cos(i * pi / 16),
                        radius * sin(i * pi / 16),
                    )
                    for end in (0, 1)
                    for i in range(32)
                ]
            for p in points:
                q = project(yaw(p, pose[3] + extra), plane)
                corners.append((q.x(), q.y()))
            points = hull(corners)
            if points:
                self.outline.moveTo(*points[0])
                for p in points[1:]:
                    self.outline.lineTo(*p)
                self.outline.closeSubpath()
            self.rectangle = self.outline.boundingRect().adjusted(-0.8, -0.8, 0.8, 0.8)
        else:
            self.rectangle = QtCore.QRectF(-1, -1, 2, 2)
            self.outline.addEllipse(self.rectangle)
        active = editor.active_pass(self.node.id)
        geometry = editor.display_trace.layout if editor.display_trace else None
        for (visit, name), port in self.ports.items():
            state = geometry.visits.get(visit) if geometry else None
            local = QtCore.QPointF()
            if state:
                incident = editor.scene.topology.incident_ports.get(visit)
                hit = (
                    state.entry
                    if name == incident or editor.document.optical_pass(visit).mode == "receive"
                    else state.exit
                )
                local = project(hit, plane) - project(pose, plane)
            port.setPos(local)
            port.setVisible(visit == active)
        self.label.setPos(self.rectangle.left(), self.rectangle.bottom() + 1)
        self.setToolTip(
            f"{self.node.reference}: {SYMBOLS[self.node.kind].title}\nPhysical XYZ: {tuple(round(v,4) for v in pose[:3])} mm"
        )
        self.update()

    def boundingRect(self):
        return self.rectangle

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor("#163c54"), 0))
        painter.setBrush(QtGui.QColor("#eff7fc"))
        if self.isSelected():
            painter.fillRect(self.rectangle, QtGui.QColor(110, 170, 220, 65))
        painter.drawPath(self.outline)

    def show_bounds(self, circle, scale=1):
        radius = circle.radius_mm
        self.bounds_circle.setRect(-radius, -radius, 2 * radius, 2 * radius)
        self.bounds_circle.setVisible(self.editor.projection == "XY")

    def itemChange(self, change, value):
        if (
            change == QtWidgets.QGraphicsItem.ItemPositionChange
            and self.scene() is not None
            and not self.editor.placing
        ):
            x, y = snap_point(
                pair(value), self.editor.document.settings["grid"], self.editor.document.settings["snap_grid"]
            )
            node = self.node
            if "x" in node.physical:
                x = node.physical["x"]
            if self.editor.projection == "XY" and "y" in node.physical:
                y = -node.physical["y"]
            return QtCore.QPointF(x, y)
        if (
            change == QtWidgets.QGraphicsItem.ItemPositionHasChanged
            and self.scene() is not None
            and self.editor.dragging
            and not self.editor.placing
        ):
            self.editor.queue_drag()
        return QtWidgets.QGraphicsObject.itemChange(self, change, value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.flags() & QtWidgets.QGraphicsItem.ItemIsMovable:
            self.editor.begin_drag()
        super(SymbolItem, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super(SymbolItem, self).mouseReleaseEvent(event)
        self.editor.finish_drag()


class PhysicalBeam(ConnectionItem):
    def __init__(self, connection, editor):
        QtWidgets.QGraphicsPathItem.__init__(self)
        self.segment_connection = connection
        self.connection, self.editor = connection, editor
        if connection.id not in {e.id for e in editor.document.connections}:
            saved = editor.document.optimized_layout
            if saved and saved.get("input_version") == 6:
                from .scene_optimization import saved_scene_document

                try:
                    graph = saved_scene_document(editor.document)[1]
                    logical = graph.segment(connection.id).logical_ids
                    self.connection = editor.document.connection(logical[0])
                except (ValueError, StopIteration):
                    pass
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable)
        self.setZValue(0)
        self.refresh()

    def refresh(self):
        edge = self.segment_connection
        editor = self.editor
        trace = editor.display_trace
        a = trace.layout.visits.get(edge.a.visit_id) if trace else None
        b = trace.layout.visits.get(edge.b.visit_id) if trace else None
        resolved = editor.scene.topology.edges.get(edge.id)
        if resolved and a and b:
            start = trace.layout.visits[resolved.source.visit_id].exit
            end = trace.layout.visits[resolved.target.visit_id].entry
            valid = trace.ok
        else:
            poses = editor.display_poses()
            start = poses.get(edge.a.node_id, (0, 0, 0))
            end = poses.get(edge.b.node_id, (0, 0, 0))
            valid = False
        first, last = project(start, editor.projection), project(end, editor.projection)
        p = QtGui.QPainterPath(first)
        p.lineTo(last)
        delta = last - first
        length = (delta.x() ** 2 + delta.y() ** 2) ** 0.5
        if resolved and length > 3:
            u = delta / length
            normal = QtCore.QPointF(-u.y(), u.x()) * 0.5
            tip = last - u
            p.moveTo(tip - u + normal)
            p.lineTo(tip)
            p.lineTo(tip - u - normal)
        self.setPath(p)
        pen = QtGui.QPen(QtGui.QColor("#e79b36" if self.isSelected() else "#bd3c43"), 0)
        if not valid:
            pen.setStyle(Qt.DashLine)
        self.setPen(pen)
        self.setToolTip(
            f"Physical beam · {edge.id}\nSelect to edit endpoint separation or folding permission"
        )

    def mouseDoubleClickEvent(self, event):
        self.editor.status.setText("Physical rays are straight. Add a mirror to turn this beam.")
        event.accept()


class PhysicalScene(SchematicScene):
    def rebuild(self, selected=()):
        self.editor.placing = True
        self.blockSignals(True)
        self.clear()
        self.symbols = {}
        self.connections = {}
        self.pending = None
        self.preview = None
        self.bends = []
        self.topology = resolve_topology(self.editor.scene_document())
        self.editor.refresh_trace()
        for node in self.editor.scene_document().nodes:
            item = PhysicalSymbol(node, self.editor)
            self.symbols[node.id] = item
            self.addItem(item)
            item.setSelected(node.id in selected)
        for edge in self.editor.scene_document().connections:
            item = PhysicalBeam(edge, self.editor)
            self.connections[edge.id] = item
            self.addItem(item)
        self.blockSignals(False)
        self.editor.placing = False
        self.selection_changed()
        self.editor.schedule_bounds_refresh()

    def selection_changed(self):
        if self.selectedItems():
            self.editor.inspected_omitted = None
        super().selection_changed()

    def refresh(self):
        self.editor.placing = True
        self.editor.refresh_trace()
        for item in self.symbols.values():
            item.refresh()
        for item in self.connections.values():
            item.refresh()
        self.editor.placing = False

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)

    def choose_ports(self, position):
        ports = [item for item in self.items(position) if isinstance(item, PhysicalPort)]
        return [p for p in ports if not self.editor.port_connected(p.endpoint)]

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            ports = self.choose_ports(event.scenePos())
            if ports:
                port = sorted(ports, key=lambda p: p.name)[0]
                self.wire(port.endpoint)
                event.accept()
                return
            if self.pending:
                self.editor.status.setText(
                    "Click a free port to finish this straight physical beam, or Esc to cancel."
                )
                event.accept()
                return
        QtWidgets.QGraphicsScene.mousePressEvent(self, event)

    def wire(self, endpoint):
        if self.pending is None:
            self.pending = endpoint
            self.preview = self.addPath(
                QtGui.QPainterPath(), QtGui.QPen(QtGui.QColor("#e79b36"), 0, Qt.DashLine)
            )
            self.editor.status.setText(
                "Click a free port; use the pass selector or right-click to choose another pass."
            )
        elif endpoint == self.pending:
            self.cancel_connection()
        elif self.editor.connect_endpoints(self.pending, endpoint):
            self.cancel_connection()
            self.editor.commit()

    def mouseMoveEvent(self, event):
        if self.pending:
            item = self.symbols[self.pending.node_id].ports[(self.pending.visit_id, self.pending.port_id)]
            path = QtGui.QPainterPath(item.scenePos())
            path.lineTo(event.scenePos())
            self.preview.setPath(path)
        QtWidgets.QGraphicsScene.mouseMoveEvent(self, event)

    def contextMenuEvent(self, event):
        items = self.items(event.scenePos())
        symbol = next((i for i in items if isinstance(i, PhysicalSymbol)), None)
        if symbol is None:
            port = next((i for i in items if isinstance(i, PhysicalPort)), None)
            symbol = port.symbol if port else None
        if not symbol:
            return
        menu = QtWidgets.QMenu()
        node = symbol.node
        for p in self.editor.document.optical_passes():
            if p.component_id != node.id:
                continue
            for port in SYMBOLS[node.kind].ports:
                endpoint = Endpoint(node.id, port, "" if p.id == node.id else p.id)
                action = menu.addAction(f"{self.editor.pass_label(p.id)} · {port}")
                action.setEnabled(not self.editor.port_connected(endpoint))
                action.triggered.connect(lambda checked=False, e=endpoint: self.wire(e))
        exec_menu(menu, event.screenPos())


class SceneWorker(QtCore.QThread):
    completed = QtCore.Signal(object, int, bool)
    failed = QtCore.Signal(str, int)

    def __init__(self, document, revision, targets=(), final=False, packing=None, parent=None):
        super().__init__(parent)
        self.document = document_from_dict(document.to_dict())
        self.revision = revision
        self.targets = targets
        self.final = final
        self.packing = packing
        self.cancelled = Event()

    def run(self):
        try:
            result = solve_scene(
                self.document,
                targets=self.targets,
                packing=self.packing,
                iterations=200 if self.final else 40,
                cancelled=self.cancelled.is_set,
            )
            self.completed.emit(result, self.revision, self.final)
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}", self.revision)


class PhysicalSchematicEditor(BaseEditor):
    def __init__(self, document=None, path=None, parent=None, bounds_provider=None):
        self.ready = False
        self.placing = True
        self.dragging = False
        self.revision = 0
        self.workers = set()
        self.active_passes = {}
        self.inspected_omitted = None
        self.display_trace = None
        self.preview_poses = None
        self.pending_targets = ()
        self.drag_start = None
        document = document or Schematic()
        fresh = document.layout is None
        initialize_layout(document)
        if fresh and document.settings["grid"] == 20:
            document.settings["grid"] = 1.0
        document.layout.setdefault("projection", "XY")
        self.projection = document.layout["projection"]
        super().__init__(document, path, parent, bounds_provider)
        split = self.view.parentWidget()
        old = self.view
        old_scene = self.scene
        old_scene.blockSignals(True)
        self.scene = PhysicalScene(self)
        self.view = SchematicView(self.scene, self)
        split.replaceWidget(1, self.view)
        old.deleteLater()
        old_scene.deleteLater()
        self.view.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.view.scale(4, 4)
        self.scene.rebuild()
        self.placing = False
        self.ready = True
        self.drag_timer = QtCore.QTimer(self)
        self.drag_timer.setSingleShot(True)
        self.drag_timer.timeout.connect(lambda: self.start_solve(self.pending_targets))
        self.projection_choice = QtWidgets.QComboBox()
        self.projection_choice.addItems(["XY", "XZ"])
        self.projection_choice.setCurrentText(self.projection)
        self.projection_choice.setObjectName("physicalProjection")
        self.projection_choice.currentTextChanged.connect(self.change_projection)
        self.toolbar.insertWidget(self.actions["fit"], self.projection_choice)
        self.actions["directions"].setVisible(False)
        self.bounds_toggle.setToolTip(
            "Full assembly XY bounds in millimetres, at the same scale as the optical bodies."
        )
        self.status.setText("Physical schematic · millimetres · add a pass to reuse an optic.")
        self.history = History(self.document)
        self.solve_after_edit()

    def selected_nodes(self):
        selected = BaseEditor.selected_nodes(self)
        if not selected and getattr(self, "inspected_omitted", None) in {n.id for n in self.document.nodes}:
            return [self.inspected_omitted]
        return selected

    def active_pass(self, node_id):
        valid = {p.id for p in self.document.optical_passes() if p.component_id == node_id}
        return (
            self.active_passes.get(node_id, node_id)
            if self.active_passes.get(node_id, node_id) in valid
            else node_id
        )

    def pass_label(self, visit_id):
        p = self.document.optical_pass(visit_id)
        visits = [v for v in self.document.optical_passes() if v.component_id == p.component_id]
        return f"{self.document.node(p.component_id).reference} · pass {next(i+1 for i,v in enumerate(visits) if v.id==visit_id)}"

    def scene_document(self):
        saved = self.document.optimized_layout
        if saved and saved.get("input_version") == 6:
            from .scene_optimization import saved_scene_document

            try:
                return saved_scene_document(self.document)[0]
            except ValueError:
                pass
        elif saved and saved.get("graph"):
            try:
                from .effective import replay_graph
                from .scene_optimization import scene_document
                from .optimization import OptimizationOptions

                options = OptimizationOptions(**self.document.optimization["options"])
                graph = replay_graph(self.document, saved["graph"], options)
                return scene_document(self.document, graph, options, self.document.layout["poses"])
            except ValueError:
                pass
        if saved and self.omitted_mirrors():
            # A stale graph may now violate removal permissions. Keep its known
            # retained bodies visible without inventing a position for omissions.
            result = document_from_dict(self.document.to_dict())
            omitted = self.omitted_mirrors()
            result.nodes = [n for n in result.nodes if n.id not in omitted]
            result.passes = [p for p in result.passes if p.component_id not in omitted]
            result.connections = []
            result.path_constraints = []
            result.optimized_layout = None
            return result
        return self.document

    def display_poses(self):
        return self.preview_poses or poses_for(self.scene_document())

    def refresh_trace(self):
        self.display_trace = trace_scene(self.scene_document(), self.display_poses())

    def commit(self, rebuild=True, selected=None, solve=True):
        if not self.ready:
            return BaseEditor.commit(self, rebuild, selected)
        self.cancel_workers()
        self.revision += 1
        self.preview_poses = None
        self.history.commit(self.document)
        self.scene.rebuild(self.selected_nodes() if selected is None else selected)
        self.update_title()
        if solve:
            self.solve_after_edit()

    def solve_after_edit(self):
        if self.document.optimized_layout:
            from .optimization import optimized_physical_layout

            try:
                if self.document.optimized_layout.get("input_version") != 6:
                    raise ValueError(
                        "Optimized layout is stale after the physical scene upgrade. Rerun or clear it."
                    )
                optimized_physical_layout(self.document)
            except ValueError as error:
                from .topology import Diagnostic

                self.show_diagnostics([Diagnostic(str(error))])
                return
        if self.scene.topology.ok:
            self.start_solve()
        else:
            self.show_diagnostics(self.scene.topology.diagnostics)

    def cancel_workers(self):
        for worker in self.workers:
            worker.cancelled.set()

    def packing(self):
        saved = self.document.optimized_layout
        if saved and saved.get("input_version") == 6:
            from .optimization import PackingBox, OptimizationOptions

            return (
                PackingBox(**self.document.optimization["box"]),
                {
                    **saved["radii"],
                    **{
                        m["node_id"]: saved["folding_radius"]
                        for m in saved["graph"]["edits"]
                        if m["action"] == "insert"
                    },
                },
                OptimizationOptions(**self.document.optimization["options"]),
            )
        return None

    def start_solve(self, targets=(), final=False):
        self.cancel_workers()
        self.revision += 1
        worker = SceneWorker(self.scene_document(), self.revision, targets, final, self.packing(), self)
        worker.completed.connect(self.solved)
        worker.failed.connect(self.solve_failed)
        self.workers.add(worker)
        worker.finished.connect(lambda: self.release_worker(worker))
        worker.start()

    def release_worker(self, worker):
        self.workers.discard(worker)
        worker.deleteLater()

    def solve_failed(self, message, revision):
        if revision == self.revision:
            self.preview_poses = None
            self.dragging = False
            self.scene.refresh()
            self.status.setText("Physical solve failed: " + message)

    def show_diagnostics(self, diagnostics):
        from .topology import Diagnostic

        diagnostics = list(diagnostics) + [
            Diagnostic(note, severity="warning") for note in self.document.layout.get("notes", [])
        ]
        self.messages.clear()
        for d in diagnostics:
            item = QtWidgets.QListWidgetItem(f"{d.severity.title()}: {d.message}")
            item.setData(Qt.UserRole, d)
            self.messages.addItem(item)
        if diagnostics:
            self.status.setText(diagnostics[0].message)

    def solved(self, result, revision, final):
        if revision != self.revision or result.status == "cancelled":
            return
        if self.dragging or final:
            if result.ok:
                self.preview_poses = result.poses
                if final:
                    if (
                        self.document.optimized_layout
                        and self.document.optimized_layout.get("input_version") == 6
                    ):
                        from .scene_optimization import update_scene_optimization

                        update_scene_optimization(self.document, result.poses)
                    else:
                        apply_scene_solution(self.document, result)
                    self.preview_poses = None
                    self.dragging = False
                    self.commit(solve=False)
            elif final:
                self.preview_poses = None
                self.dragging = False
                self.scene.refresh()
                self.status.setText(
                    "Drop rejected: no valid placement found. Hard constraints were preserved."
                )
            self.scene.refresh()
        elif result.ok:
            if self.document.optimized_layout and self.document.optimized_layout.get("input_version") == 6:
                from .scene_optimization import update_scene_optimization

                update_scene_optimization(self.document, result.poses)
            else:
                apply_scene_solution(self.document, result)
            self.history.states[self.history.index] = deepcopy(self.document.to_dict())
            self.scene.refresh()
            self.show_properties()
            self.update_title()
        self.show_diagnostics(result.diagnostics)
        if result.ok:
            dof = result.report.degrees_of_freedom if result.report else 0
            self.status.setText(f"Physical layout valid · {dof} locally free degrees of freedom")

    def focus_diagnostic(self, item):
        value = item.data(Qt.UserRole)
        if not hasattr(value, "node_id"):
            return BaseEditor.focus_diagnostic(self, item)
        self.scene.clearSelection()
        if value.pass_id and value.node_id:
            self.active_passes[value.node_id] = value.pass_id
        if value.node_id in self.scene.symbols:
            self.scene.symbols[value.node_id].setSelected(True)
            self.view.centerOn(self.scene.symbols[value.node_id])
        if value.connection_id in self.scene.connections:
            self.scene.connections[value.connection_id].setSelected(True)
        if value.constraint_id:
            constraint = next(
                (c for c in self.document.path_constraints if c.id == value.constraint_id), None
            )
            if constraint:
                from .paths import component_path

                for edge in component_path(
                    self.scene_document(),
                    constraint.pass_a or constraint.component_a,
                    constraint.pass_b or constraint.component_b,
                ):
                    if edge in self.scene.connections:
                        self.scene.connections[edge].setSelected(True)
        self.show_properties()

    def display_diagnostics(self, diagnostics):
        self.show_diagnostics(diagnostics)

    def begin_drag(self):
        self.cancel_workers()
        self.revision += 1
        self.dragging = True
        self.drag_start = deepcopy(self.document.to_dict())

    def queue_drag(self):
        targets = []
        for node_id, item in self.scene.symbols.items():
            if not item.isSelected():
                continue
            p = item.pos()
            targets.extend(((node_id, 0, p.x()), (node_id, 1 if self.projection == "XY" else 2, -p.y())))
        self.pending_targets = tuple(targets)
        if targets and not self.drag_timer.isActive():
            self.drag_timer.start(75)

    def finish_drag(self):
        if not self.dragging:
            return
        self.drag_timer.stop()
        self.queue_drag()
        self.drag_timer.stop()
        if self.pending_targets:
            self.start_solve(self.pending_targets, True)
        else:
            self.dragging = False

    def change_projection(self, value):
        self.projection = value
        self.document.layout["projection"] = value
        self.preview_poses = None
        self.scene.rebuild(self.selected_nodes())
        self.history.commit(self.document)
        self.fit()

    def set_connection_length(self, connection_id, value):
        self.document.connection(connection_id).length = value
        self.commit()

    def set_node_value(self, node_id, key, value):
        if key == "preset":
            from .registry import select_preset

            node = self.document.node(node_id)
            previous_offset = source_offset(node)
            select_preset(node, value)
            if node.kind == "fiber_source":
                self.document.layout["poses"][node.id][3] += source_offset(node) - previous_offset
            self.commit()
        else:
            BaseEditor.set_node_value(self, node_id, key, value)

    def add_symbol(self, kind, position=None):
        if not self.ready:
            return BaseEditor.add_symbol(self, kind, position)
        if position is None:
            position = pair(self.view.mapToScene(self.view.viewport().rect().center()))
        x, v = snap_point(position, self.document.settings["grid"], self.document.settings["snap_grid"])
        node = self.document.add_node(kind)
        angle = 135 if kind == "mirror" else 180 if kind in ("fiber_source", "fiber_output", "stop") else 0
        if kind == "fiber_source" and node.preset in ("POLARIS-K05T6", "KA05TA"):
            angle = 0
        self.document.layout["poses"][node.id] = [
            x,
            -v if self.projection == "XY" else 0,
            -v if self.projection == "XZ" else 0,
            angle,
        ]
        self.commit(selected=[node.id])

    def connect_endpoints(self, a, b):
        if a.visit_id == b.visit_id:
            self.status.setText("Connect different passes; add another pass to reuse this component.")
            return False
        if any(self.port_connected(e) for e in (a, b)):
            return False
        self.document.connections.append(Connection(new_id(), a, b))
        return True

    def connect_ports(self, source, port, target, target_port, bends=None):
        return self.connect_endpoints(Endpoint(source, port), Endpoint(target, target_port))

    def port_connected(self, endpoint):
        return any(
            e.visit_id == endpoint.visit_id and e.port_id == endpoint.port_id
            for c in self.document.connections
            for e in (c.a, c.b)
        )

    def add_optical_pass(self, node_id):
        item = self.document.add_pass(node_id)
        self.active_passes[node_id] = item.id
        self.commit(selected=[node_id])
        return item

    def remove_optical_pass(self, node_id):
        try:
            self.document.remove_pass(self.active_pass(node_id))
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.active_passes[node_id] = node_id
        self.commit(selected=[node_id])

    def set_active_pass(self, node_id, visit_id):
        self.active_passes[node_id] = visit_id
        self.scene.refresh()
        self.show_properties()

    def show_properties(self):
        if not hasattr(self, "scene"):
            return
        chosen = self.selected_nodes()
        if len(chosen) == 1 and chosen[0] not in {n.id for n in self.document.nodes}:
            self.clear_form()
            node = self.scene_document().node(chosen[0])
            self.note(node.reference + " · optimizer-added Folding mirror (read-only)")
            self.note("Physical XYZ: " + str(tuple(self.display_poses()[node.id][:3])) + " mm")
            return
        BaseEditor.show_properties(self)
        ids = self.selected_nodes()
        if len(ids) == 1 and ids[0] in self.omitted_mirrors():
            return
        if not ids and self.omitted_mirrors():
            omitted = QtWidgets.QComboBox()
            omitted.setObjectName("omittedComponents")
            omitted.addItem("Inspect omitted optic…", None)
            for node_id in sorted(self.omitted_mirrors()):
                omitted.addItem(self.document.node(node_id).reference, node_id)
            omitted.currentIndexChanged.connect(lambda index: self.inspect_omitted(omitted.itemData(index)))
            self.form.addRow("Omitted components", omitted)
        if len(ids) == 1:
            node = self.document.node(ids[0])
            combo = QtWidgets.QComboBox()
            combo.setObjectName("opticalPass")
            for p in self.document.optical_passes():
                if p.component_id == node.id:
                    combo.addItem(self.pass_label(p.id), p.id)
            combo.setCurrentIndex(combo.findData(self.active_pass(node.id)))
            combo.currentIndexChanged.connect(
                lambda index: self.set_active_pass(node.id, combo.itemData(index))
            )
            self.form.insertRow(2, "Optical pass", combo)
            buttons = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(buttons)
            row.setContentsMargins(0, 0, 0, 0)
            add_button = QtWidgets.QPushButton("Add pass")
            add_button.setObjectName("addOpticalPass")
            add_button.setEnabled(node.kind not in ("source", "output", "stop"))
            remove = QtWidgets.QPushButton("Remove pass")
            remove.setObjectName("removeOpticalPass")
            remove.setEnabled(self.active_pass(node.id) != node.id)
            add_button.clicked.connect(lambda: self.add_optical_pass(node.id))
            remove.clicked.connect(lambda: self.remove_optical_pass(node.id))
            row.addWidget(add_button)
            row.addWidget(remove)
            self.form.insertRow(3, buttons)
            pose = self.display_poses().get(node.id, (0, 0, 0, 0))
            self.note(f"Physical Z: {pose[2]:.6f} mm · yaw: {pose[3]:.6f}°")
            spec = element_spec(node, self.scene.topology)
            if spec and spec.aperture_only:
                self.note("Optical aperture outline only; the full body requires vendor geometry.")
        # Retire the independent circle scale and topological-only instructions.
        physical_help_seen = False
        for label in self.properties.findChildren(QtWidgets.QLabel):
            text = label.text()
            if text == "Drawing grid":
                label.setText("Grid (mm)")
            elif "Bounds scale (canvas units/mm)" in text:
                field = self.form.itemAt(
                    self.form.getWidgetPosition(label)[0], QtWidgets.QFormLayout.FieldRole
                )
                if field and field.widget():
                    field.widget().hide()
                label.hide()
            elif "independent of canvas" in text:
                label.setText("Physical layout · millimetres")
            elif "Drawing" in text or "drawing" in text or "topological" in text:
                if "Source" not in text:
                    if physical_help_seen:
                        label.hide()
                        continue
                    physical_help_seen = True
                    label.setWordWrap(True)
                    label.setText(
                        "The canvas shows physical geometry in millimetres. Constraints remain explicit; dragging adjusts free geometry."
                    )

    def inspect_omitted(self, node_id):
        if node_id is None:
            return
        self.scene.clearSelection()
        self.inspected_omitted = node_id
        self.show_properties()

    def delete_selected(self):
        if any(node_id not in {n.id for n in self.document.nodes} for node_id in self.selected_nodes()):
            self.status.setText(
                "Added mirrors belong to the optimized solution; rerun or clear optimization to change them."
            )
            return
        BaseEditor.delete_selected(self)

    def show_position_property(self, node):
        toggle = QtWidgets.QCheckBox("Constrain position")
        toggle.setObjectName("opticPositionConstrained")
        toggle.setChecked("x" in node.physical or "y" in node.physical)
        self.form.addRow(toggle)
        pose = self.display_poses().get(node.id, (0, 0, 0, 0))
        fields = []

        def update(_value):
            if toggle.isChecked():
                self.set_optic_position(node.id, (fields[0].value(), fields[1].value()))

        for axis, key in enumerate(("x", "y")):
            field = self.number_field(key.upper() + " (mm)", node.physical.get(key, pose[axis]), update)
            field.setObjectName("opticPosition" + key.upper())
            field.setEnabled(toggle.isChecked())
            fields.append(field)

        def change(checked):
            for field in fields:
                field.setEnabled(checked)
            self.set_optic_position(node.id, (fields[0].value(), fields[1].value()) if checked else None)

        toggle.toggled.connect(change)
        self.note(
            "Position pins constrain the shared component origin. Every optical pass uses this same physical part."
        )

    def editable_pass(self, node_id):
        visit_id = self.active_pass(node_id)
        existing = next((p for p in self.document.passes if p.id == visit_id), None)
        if existing:
            return existing
        p = self.document.optical_pass(visit_id)
        self.document.passes.append(p)
        return p

    def effective_turn(self, node):
        g = self.display_trace.layout if self.display_trace else None
        return g.turns.get(self.active_pass(node.id), node.physical.get("turn", 90)) if g else 90

    def show_angle_property(self, node):
        visit = self.document.optical_pass(self.active_pass(node.id))
        checked = visit.turn is not None or (visit.id == node.id and "turn" in node.physical)
        toggle = QtWidgets.QCheckBox("Constrain angle")
        toggle.setObjectName("opticAngleConstrained")
        toggle.setChecked(checked)
        self.form.addRow(toggle)
        field = self.number_field(
            "Pass turn in XY (deg)",
            visit.turn if visit.turn is not None else self.effective_turn(node),
            lambda value: self.set_optic_turn(node.id, value) if toggle.isChecked() else None,
            minimum=-179.999999,
            maximum=179.999999,
        )
        field.setObjectName("opticAngleDeg")
        field.setEnabled(checked)
        toggle.toggled.connect(
            lambda value: (
                field.setEnabled(value),
                self.set_optic_turn(node.id, field.value() if value else None),
            )
        )
        self.note("The selected pass is constrained. Every pass shares this optic’s physical orientation.")

    def set_optic_turn(self, node_id, value):
        p = self.editable_pass(node_id)
        p.turn = value
        if p.id == node_id:
            self.document.node(node_id).physical.pop("turn", None)
            for edge in self.document.connections:
                edge.turns.pop(node_id, None)
        self.commit()

    def effective_endpoint_direction(self, node):
        p = self.document.optical_pass(self.active_pass(node.id))
        state = self.display_trace.layout.visits.get(p.id) if self.display_trace else None
        if state:
            return heading(state.incoming)
        return self.display_poses()[node.id][3] - source_offset(node)

    def show_source_direction_property(self, node):
        p = self.document.optical_pass(self.active_pass(node.id))
        self.show_endpoint_direction_property(node, p.mode == "emit")

    def show_endpoint_direction_property(self, node, source):
        if self.active_pass(node.id) == node.id:
            return BaseEditor.show_endpoint_direction_property(self, node, source)
        p = self.document.optical_pass(self.active_pass(node.id))
        toggle = QtWidgets.QCheckBox("Constrain output direction")
        toggle.setChecked(p.direction is not None)
        toggle.setObjectName("outputDirectionConstrained")
        self.form.addRow(toggle)
        field = self.number_field(
            "Output direction in XY (deg)",
            p.direction if p.direction is not None else self.effective_endpoint_direction(node),
            lambda value: self.set_endpoint_direction(node.id, value) if toggle.isChecked() else None,
        )
        field.setObjectName("outputDirectionDeg")
        field.setEnabled(toggle.isChecked())
        toggle.toggled.connect(
            lambda value: (
                field.setEnabled(value),
                self.set_endpoint_direction(node.id, field.value() if value else None),
            )
        )

    def set_endpoint_direction(self, node_id, value):
        if self.active_pass(node_id) == node_id:
            return BaseEditor.set_endpoint_direction(self, node_id, value)
        self.editable_pass(node_id).direction = value
        self.commit()

    def duplicate(self):
        originals = self.selected_nodes()
        copies = self.document.duplicate_nodes(originals)
        poses = self.display_poses()
        for original, copy in zip(originals, copies):
            p = list(poses[original])
            p[0] += 10
            p[1] -= 10
            self.document.layout["poses"][copy.id] = p
            for primary in self.document.passes:
                if primary.id == original:
                    self.document.passes.append(
                        OpticalPass(copy.id, copy.id, primary.mode, primary.turn, primary.direction)
                    )
                    break
            for visit in self.document.optical_passes():
                if visit.component_id == original and visit.id != original:
                    added = self.document.add_pass(copy.id, visit.mode)
                    added.turn = visit.turn
                    added.direction = visit.direction
        self.commit(selected=[n.id for n in copies])

    def rotate(self):
        targets = []
        for node_id in self.selected_nodes():
            targets.append((node_id, 3, self.display_poses()[node_id][3] + self.document.settings["angle"]))
        if targets:
            self.dragging = True
            self.start_solve(tuple(targets), True)

    def restore(self):
        self.cancel_workers()
        self.revision += 1
        self.preview_poses = None
        self.dragging = False
        initialize_layout(self.document)
        self.projection = self.document.layout.get("projection", "XY")
        BaseEditor.restore(self)
        if hasattr(self, "projection_choice"):
            self.projection_choice.blockSignals(True)
            self.projection_choice.setCurrentText(self.projection)
            self.projection_choice.blockSignals(False)
        self.solve_after_edit()

    def fit(self):
        if not hasattr(self, "view"):
            return
        rect = self.scene.itemsBoundingRect()
        if not rect.isEmpty():
            self.view.fitInView(rect.adjusted(-10, -10, 10, 10), Qt.KeepAspectRatio)

    def apply_optimized_result(self, problem, result):
        accepted = BaseEditor.apply_optimized_result(self, problem, result)
        if accepted:
            self.status.setText("Optimized physical geometry applied. Explicit constraints are unchanged.")
        return accepted

    def clear_optimized_layout(self):
        if self.document.optimized_layout:
            previous = self.document.optimized_layout.get(
                "manual_poses", self.document.layout.pop("legacy_manual_poses", None)
            )
            self.document.optimized_layout = None
            if previous:
                self.document.layout["poses"] = deepcopy(previous)
            self.commit()

    def closeEvent(self, event):
        self.cancel_workers()
        for worker in list(self.workers):
            worker.wait(3000)
        BaseEditor.closeEvent(self, event)
