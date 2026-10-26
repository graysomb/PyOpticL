"""Modal physical preview. CAD resolution stays here; the worker is numerical."""

from threading import Event

from .bounds import resolve_layout_bounds
from .compiler import validate_schematic
from .model import document_from_dict
from .optimization import OptimizationOptions, PackingBox, build_problem, initial_box, optimize_layout
from .qt import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt


class LayoutWorker(QtCore.QThread):
    progressed = QtCore.Signal(object)
    completed = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, problem, parent=None):
        super().__init__(parent)
        self.problem = problem
        self.cancelled = Event()

    def run(self):
        try:
            result = optimize_layout(
                self.problem, progress=self.progressed.emit, cancelled=self.cancelled.is_set
            )
            self.completed.emit(result)
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")


class PhysicalPreview(QtWidgets.QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self.setMinimumSize(480, 320)
        self.setBackgroundBrush(QtGui.QColor("#f9fafc"))

    def show_layout(self, problem, positions, violations=()):
        scene = self.scene()
        scene.clear()
        bad_nodes = {node_id for item in violations for node_id in item.node_ids}
        bad_edges = {edge_id for item in violations for edge_id in item.connection_ids}
        box = problem.box
        scene.addRect(
            box.x, -box.y - box.height, box.width, box.height, QtGui.QPen(QtGui.QColor("#46556b"), 0)
        )
        for edge in problem.edges:
            a, b = positions[edge.a], positions[edge.b]
            color = QtGui.QColor("#d83939" if edge.id in bad_edges else "#d58e24")
            pen = QtGui.QPen(color, problem.options.beam_diameter_mm)
            pen.setCapStyle(Qt.RoundCap)
            scene.addLine(a[0], -a[1], b[0], -b[1], pen).setZValue(0)
        for node, (x, y) in zip(problem.nodes, positions):
            color = QtGui.QColor("#d83939" if node.id in bad_nodes else "#3878a7")
            radius = node.radius
            if radius is not None:
                fill = QtGui.QColor(color)
                fill.setAlpha(50)
                scene.addEllipse(
                    x - radius, -y - radius, 2 * radius, 2 * radius, QtGui.QPen(color, 0), QtGui.QBrush(fill)
                ).setZValue(1)
            else:
                # Virtual optical endpoints have markers, not physical disks.
                scene.addLine(x - 1, -y, x + 1, -y, QtGui.QPen(color, 0)).setZValue(1)
                scene.addLine(x, -y - 1, x, -y + 1, QtGui.QPen(color, 0)).setZValue(1)
            generated = (
                {mirror.id for mirror in problem.graph.generated} if problem.graph is not None else set()
            )
            label = scene.addSimpleText(node.reference + (" (added)" if node.id in generated else ""))
            label.setBrush(color)
            label.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
            label.setPos(x + (radius or 0) + 1, -y)
            label.setZValue(2)
        frame = QtCore.QRectF(box.x, -box.y - box.height, box.width, box.height)
        self.setSceneRect(frame.adjusted(-10, -10, 10, 10))
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)


class OptimizeLayoutDialog(QtWidgets.QDialog):
    def __init__(self, document, bounds_provider, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Optimize physical layout")
        self.setModal(True)
        self.resize(1050, 700)
        self.document = document_from_dict(document.to_dict())
        self.bounds_provider = bounds_provider
        self.worker = None
        self.problem = None
        self.solution = None
        self.closing = False
        self.fields = {}
        self.preview = PhysicalPreview(self)
        self.status = QtWidgets.QLabel("Resolve physical bounds, then run the numerical search.")
        self.status.setWordWrap(True)
        self.violations = QtWidgets.QListWidget()
        self.violations.setMaximumHeight(150)
        self.progress = QtWidgets.QProgressBar()
        self.run_button = QtWidgets.QPushButton("Run")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.apply_button.setEnabled(False)
        self.refresh_button = QtWidgets.QPushButton("Refresh bounds")
        self.run_button.setObjectName("optimizerRun")
        self.cancel_button.setObjectName("optimizerCancel")
        self.apply_button.setObjectName("optimizerApply")
        self.run_button.clicked.connect(self.start_search)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.accept_result)
        self.refresh_button.clicked.connect(self.refresh_bounds)
        controls = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(controls)
        previous = self.document.optimization
        options = OptimizationOptions(**previous["options"]) if previous else OptimizationOptions()
        self.options = options
        self.folding_radius = None
        # Resolve CAD before the thread is created. Keep the schematic MDI active.
        self.radii, self.bounds_errors = self.resolve_bounds()
        box = initial_box(self.document, self.radii)
        for key, label, value, minimum in (
            ("x", "Rectangle X (mm)", box.x, -1e6),
            ("y", "Rectangle Y (mm)", box.y, -1e6),
            ("width", "Width (mm)", box.width, 0.001),
            ("height", "Height (mm)", box.height, 0.001),
            ("clearance", "Clearance (mm)", options.clearance_mm, 0),
            ("diameter", "Beam keep-out diameter (mm)", options.beam_diameter_mm, 0.001),
        ):
            field = QtWidgets.QDoubleSpinBox()
            field.setObjectName("optimizer" + key.title())
            field.setRange(minimum, 1e6)
            field.setDecimals(6)
            field.setValue(value)
            field.setKeyboardTracking(False)
            field.valueChanged.connect(self.configuration_changed)
            self.fields[key] = field
            form.addRow(label, field)
        self.folding_preset = QtWidgets.QComboBox()
        self.folding_preset.setObjectName("optimizerFoldingPreset")
        self.folding_preset.addItems(["mounted", "bare"])
        self.folding_preset.setCurrentText(options.folding_preset)
        form.addRow("Added mirror preset", self.folding_preset)
        for key, label, value, minimum, maximum, integer in (
            (
                "folding_diameter",
                "Added mirror diameter (mm)",
                options.folding_diameter_mm,
                0.001,
                1e6,
                False,
            ),
            ("max_added", "Maximum added mirrors", options.max_added_mirrors, 0, 1000, True),
            ("max_per_beam", "Maximum added per original beam", options.max_folds_per_beam, 0, 1000, True),
            (
                "removal_angle",
                "Remove above interior angle (deg)",
                options.removal_angle_deg,
                0.001,
                179.999,
                False,
            ),
        ):
            field = QtWidgets.QSpinBox() if integer else QtWidgets.QDoubleSpinBox()
            field.setObjectName("optimizer" + key.title().replace("_", ""))
            field.setRange(int(minimum) if integer else minimum, int(maximum) if integer else maximum)
            if not integer:
                field.setDecimals(6)
            field.setValue(value)
            field.setKeyboardTracking(False)
            self.fields[key] = field
            field.valueChanged.connect(self.folding_settings_changed)
            form.addRow(label, field)
        self.folding_preset.currentTextChanged.connect(self.folding_settings_changed)
        form.addRow(self.refresh_button)
        note = QtWidgets.QLabel(
            "Physical XY preview in millimetres. Disks include mounts and hardware. Beam crossings are allowed. Applying preserves the topological drawing and your constraint checkboxes."
        )
        note.setWordWrap(True)
        form.addRow(note)
        content = QtWidgets.QHBoxLayout()
        content.addWidget(controls)
        content.addWidget(self.preview, 1)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        for button in (self.run_button, self.cancel_button, self.apply_button):
            buttons.addWidget(button)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(content, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        self.changes = QtWidgets.QLabel()
        self.changes.setWordWrap(True)
        self.changes.hide()
        layout.addWidget(self.changes)
        layout.addWidget(self.violations)
        layout.addLayout(buttons)
        self.configuration_changed()

    def resolve_bounds(self):
        parent = self.parentWidget()
        window = parent.parentWidget() if parent is not None else None
        area = window.mdiArea() if isinstance(window, QtWidgets.QMdiSubWindow) else None
        previous = area.activeSubWindow() if area is not None else None
        try:
            errors = validate_schematic(self.document)
            if errors:
                return {}, [item.message for item in errors]
            radii, errors = resolve_layout_bounds(self.document, self.bounds_provider)
            self.folding_radius = None
            options = self.current_options()
            if (
                any(edge.allow_folding for edge in self.document.connections)
                and options.max_added_mirrors
                and options.max_folds_per_beam
            ):
                from .parts import folding_part_spec

                result = self.bounds_provider.get(folding_part_spec(options))
                if result.circle is None:
                    errors.append(
                        "Added folding mirror bounds unavailable: "
                        + str(result.error)
                        + ". Refresh bounds or choose a modeled mirror preset."
                    )
                else:
                    self.folding_radius = result.circle.radius_mm
            return radii, errors
        finally:
            if area is not None and previous is not None:
                area.setActiveSubWindow(previous)

    def current_options(self):
        from dataclasses import replace

        if not hasattr(self, "folding_preset"):
            return self.options
        return replace(
            self.options,
            clearance_mm=self.fields["clearance"].value(),
            beam_diameter_mm=self.fields["diameter"].value(),
            folding_preset=self.folding_preset.currentText(),
            folding_diameter_mm=self.fields["folding_diameter"].value(),
            max_added_mirrors=self.fields["max_added"].value(),
            max_folds_per_beam=self.fields["max_per_beam"].value(),
            removal_angle_deg=self.fields["removal_angle"].value(),
        )

    def make_problem(self):
        values = {key: field.value() for key, field in self.fields.items()}
        return build_problem(
            self.document,
            self.radii,
            PackingBox(**{key: values[key] for key in ("x", "y", "width", "height")}),
            self.current_options(),
            folding_radius=self.folding_radius,
        )

    def folding_settings_changed(self, *_):
        try:
            self.radii, self.bounds_errors = self.resolve_bounds()
        except ValueError as error:
            self.bounds_errors = [str(error)]
        self.configuration_changed()

    def configuration_changed(self, *_):
        self.solution = None
        self.apply_button.setEnabled(False)
        self.violations.clear()
        self.run_button.setEnabled(not self.bounds_errors)
        if self.bounds_errors:
            self.status.setText("Optimization blocked: complete physical geometry is required.")
            self.violations.addItems(self.bounds_errors)
            return
        try:
            self.problem = self.make_problem()
            from .optimization import layout_violations

            items = layout_violations(self.problem, self.problem.initial_positions)
            self.preview.show_layout(self.problem, self.problem.initial_positions, items)
            self.status.setText(
                "Ready. Search uses up to 8 deterministic starts and verifies exact optical geometry before Apply."
            )
        except ValueError as error:
            self.status.setText(str(error))
            self.run_button.setEnabled(False)

    def refresh_bounds(self):
        self.bounds_provider.clear()
        self.radii, self.bounds_errors = self.resolve_bounds()
        self.configuration_changed()

    def set_running(self, running):
        self.run_button.setEnabled(not running and not self.bounds_errors)
        self.refresh_button.setEnabled(not running)
        self.folding_preset.setEnabled(not running)
        for field in self.fields.values():
            field.setEnabled(not running)
        self.apply_button.setEnabled(
            not running and self.solution is not None and self.solution.status == "feasible"
        )

    def start_search(self):
        if self.worker is not None:
            return
        self.problem = self.make_problem()
        self.solution = None
        self.progress.setRange(0, self.problem.options.starts * self.problem.options.iterations)
        self.progress.setValue(0)
        self.violations.clear()
        self.status.setText("Searching…")
        self.set_running(True)
        self.worker = LayoutWorker(self.problem, self)
        self.worker.progressed.connect(self.update_progress)
        self.worker.completed.connect(self.search_completed)
        self.worker.failed.connect(self.search_failed)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def update_progress(self, frame):
        if self.closing:
            return
        self.progress.setValue(frame.total_iterations)
        self.status.setText(
            f"Start {frame.start}/{self.problem.options.starts}, iteration {frame.iteration} — "
            + (
                "verified feasible candidate"
                if frame.feasible
                else f"{len(frame.violations)} remaining violations"
            )
        )
        self.show_violations(frame.violations)
        preview_problem = frame.problem or self.problem
        self.preview.show_layout(preview_problem, frame.positions, frame.violations)
        self.show_changes(preview_problem)

    def show_changes(self, problem):
        graph = problem.graph
        if graph is None or not graph.edits:
            self.changes.hide()
            return
        added = [node.reference for node in problem.nodes if node.id in {item.id for item in graph.generated}]
        omitted = [node.reference for node in self.document.nodes if node.id in graph.bypassed]
        self.changes.setText(
            "Added: " + (", ".join(added) or "none") + "; omitted: " + (", ".join(omitted) or "none")
        )
        self.changes.show()

    def show_violations(self, items):
        self.violations.clear()
        for item in items[:30]:
            self.violations.addItem(f"{item.message}: {item.residual:.6g} {item.unit}")

    def search_completed(self, result):
        self.solution = result
        if self.closing:
            return
        preview_problem = result.problem or self.problem
        self.preview.show_layout(preview_problem, result.positions, result.violations)
        self.show_changes(preview_problem)
        self.show_violations(result.violations)
        if result.status != "cancelled":
            self.progress.setValue(self.progress.maximum())
        if result.status == "feasible":
            self.status.setText(
                f"Verified feasible layout found in {result.iterations} iterations across {result.starts} starts. Apply to use it for export."
            )
        elif result.status == "cancelled":
            self.status.setText("Search cancelled.")
        else:
            self.status.setText(
                "No feasible layout found. Search budget exhausted; largest remaining violations are listed below."
            )

    def search_failed(self, message):
        self.solution = None
        self.status.setText("Search failed: " + message)

    def worker_finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.set_running(False)
        if self.closing:
            super().reject()

    def accept_result(self):
        if self.worker is None and self.solution is not None and self.solution.status == "feasible":
            super().accept()

    def reject(self):
        if self.worker is not None:
            self.closing = True
            self.worker.cancelled.set()
            self.status.setText("Cancelling…")
            self.cancel_button.setEnabled(False)
        else:
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)
