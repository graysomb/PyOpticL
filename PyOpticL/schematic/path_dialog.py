"""Edit total path constraints without changing the document until accepted."""

from copy import deepcopy

from .compiler import compile_schematic
from .model import PathLengthConstraint, connection_length, document_from_dict, new_id
from .paths import component_path, path_length
from .topology import resolve_topology
from .qt import QtCore, QtWidgets

Qt = QtCore.Qt


class PathLengthsDialog(QtWidgets.QDialog):
    route_selected = QtCore.Signal(object)

    def __init__(self, document, selected=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Total path lengths")
        self.resize(760, 430)
        self.document = document_from_dict(document.to_dict())
        self.constraints = deepcopy(document.path_constraints)
        self.worker = None
        self.solution = None
        self.pending_result = None
        self.selected_constraint = None
        self.current_document = self.document
        self.geometry = compile_schematic(document).geometry
        if document.optimized_layout and document.optimized_layout.get("input_version") == 6:
            from .scene_optimization import saved_scene_document

            try:
                self.current_document = saved_scene_document(self.document)[0]
            except ValueError:
                pass  # A stale graph remains editable; solving reports its conflict.
        elif self.geometry is not None and self.geometry.graph is not None:
            from .effective import effective_document
            from .optimization import OptimizationOptions

            self.current_document = effective_document(
                self.document, self.geometry.graph, OptimizationOptions(**document.optimization["options"])
            )
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setObjectName("pathLengthsTable")
        self.table.setHorizontalHeaderLabels(["From", "To", "Target (mm)", "Current (mm)", "Status"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.select_row)
        self.a = QtWidgets.QComboBox()
        self.b = QtWidgets.QComboBox()
        self.a.setObjectName("pathLengthFrom")
        self.b.setObjectName("pathLengthTo")
        for visit in self.document.optical_passes():
            node = self.document.node(visit.component_id)
            visits = [p for p in self.document.optical_passes() if p.component_id == node.id]
            label = (
                node.reference
                if len(visits) == 1
                else f"{node.reference} · pass {next(i+1 for i,p in enumerate(visits) if p.id==visit.id)}"
            )
            self.a.addItem(label, visit.id)
            self.b.addItem(label, visit.id)
        ids = list(selected)[:2]
        if len(ids) == 2:
            self.a.setCurrentIndex(self.a.findData(ids[0]))
            self.b.setCurrentIndex(self.b.findData(ids[1]))
        elif self.b.count() > 1:
            self.b.setCurrentIndex(1)
        self.target = QtWidgets.QDoubleSpinBox()
        self.target.setObjectName("pathLengthTarget")
        self.target.setRange(0.000001, 1e9)
        self.target.setDecimals(6)
        self.target.setKeyboardTracking(False)
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.solve_status = QtWidgets.QLabel()
        self.solve_status.setObjectName("pathLengthSolveStatus")
        self.solve_status.setWordWrap(True)
        self.add_button = QtWidgets.QPushButton("Add / update path")
        self.add_button.setObjectName("pathLengthAdd")
        self.delete_button = QtWidgets.QPushButton("Delete selected path")
        self.delete_button.setObjectName("pathLengthDelete")
        self.add_button.clicked.connect(self.add_constraint)
        self.delete_button.clicked.connect(self.delete_constraint)
        self.a.currentIndexChanged.connect(self.endpoints_changed)
        self.b.currentIndexChanged.connect(self.endpoints_changed)
        form = QtWidgets.QFormLayout()
        form.addRow("From component", self.a)
        form.addRow("To component", self.b)
        form.addRow("Total routed length (mm)", self.target)
        edit_buttons = QtWidgets.QHBoxLayout()
        edit_buttons.addWidget(self.add_button)
        edit_buttons.addWidget(self.delete_button)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(form)
        layout.addLayout(edit_buttons)
        layout.addWidget(self.note)
        layout.addWidget(self.solve_status)
        layout.addWidget(self.buttons)
        self.refresh()
        self.endpoints_changed()

    def current_length(self, a, b):
        if self.geometry is None:
            return None
        try:
            if self.geometry.visits:
                topology = resolve_topology(self.current_document)
                route = component_path(self.current_document, a, b)
                routed = set(route)
                return sum(self.geometry.lengths[key] for key in route) + sum(
                    self.geometry.internal_lengths.get(v, 0)
                    for v in topology.order
                    if any(e.id in routed for e in topology.outgoing[v])
                )
            return path_length(self.current_document, a, b, self.geometry.lengths)
        except (ValueError, KeyError):
            return None

    def refresh(self, selected_id=None):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.constraints))
        for row, item in enumerate(self.constraints):
            a, b = self.document.node(item.component_a), self.document.node(item.component_b)
            current = self.current_length(item.pass_a or a.id, item.pass_b or b.id)
            try:
                component_path(self.document, item.pass_a or a.id, item.pass_b or b.id)
                status = (
                    "Unavailable / rerun required"
                    if current is None
                    else ("Satisfied" if abs(current - item.length_mm) <= 1e-6 else "Unsatisfied")
                )
            except ValueError:
                status = "Disconnected route"
            values = (
                self.a.itemText(self.a.findData(item.pass_a or a.id)),
                self.b.itemText(self.b.findData(item.pass_b or b.id)),
                f"{item.length_mm:.6f}",
                "Unavailable" if current is None else f"{current:.6f}",
                status,
            )
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                cell.setData(Qt.UserRole, item.id)
                self.table.setItem(row, column, cell)
            if item.id == selected_id:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        self.delete_button.setEnabled(bool(self.table.selectedItems()))

    def endpoints_changed(self, *_):
        a, b = self.a.currentData(), self.b.currentData()
        try:
            route = component_path(self.document, a, b)
        except ValueError as error:
            self.note.setText(str(error))
            self.add_button.setEnabled(False)
            self.route_selected.emit(())
            return
        self.add_button.setEnabled(True)
        existing = next(
            (
                item
                for item in self.constraints
                if {item.pass_a or item.component_a, item.pass_b or item.component_b} == {a, b}
            ),
            None,
        )
        current = self.current_length(a, b)
        target = (
            existing.length_mm
            if existing
            else (
                current
                if current is not None
                else sum(connection_length(self.document, self.document.connection(key)) for key in route)
            )
        )
        self.target.setValue(target)
        self.note.setText(
            "Sum of beam lengths along the highlighted route, including folds. Refractive-index weighting is not applied."
            + (
                " Current physical length is unavailable; the proposed target uses document defaults."
                if current is None and existing is None
                else ""
            )
        )
        self.route_selected.emit(route)

    def select_row(self):
        items = self.table.selectedItems()
        self.delete_button.setEnabled(bool(items))
        if not items:
            return
        constraint = next(item for item in self.constraints if item.id == items[0].data(Qt.UserRole))
        self.a.blockSignals(True)
        self.b.blockSignals(True)
        self.a.setCurrentIndex(self.a.findData(constraint.pass_a or constraint.component_a))
        self.b.setCurrentIndex(self.b.findData(constraint.pass_b or constraint.component_b))
        self.a.blockSignals(False)
        self.b.blockSignals(False)
        self.endpoints_changed()

    def add_constraint(self):
        if self.worker is not None:
            return
        a, b = self.a.currentData(), self.b.currentData()
        component_path(self.document, a, b)
        existing = next(
            (
                item
                for item in self.constraints
                if {item.pass_a or item.component_a, item.pass_b or item.component_b} == {a, b}
            ),
            None,
        )
        if existing:
            existing.length_mm = self.target.value()
            selected = existing.id
        else:
            ap, bp = self.document.optical_pass(a), self.document.optical_pass(b)
            item = PathLengthConstraint(
                new_id(),
                ap.component_id,
                bp.component_id,
                self.target.value(),
                "" if a == ap.component_id else a,
                "" if b == bp.component_id else b,
            )
            self.constraints.append(item)
            selected = item.id
        self.solve_draft(selected)

    def delete_constraint(self):
        if self.worker is not None:
            return
        items = self.table.selectedItems()
        if items:
            key = items[0].data(Qt.UserRole)
            self.constraints[:] = [item for item in self.constraints if item.id != key]
            self.solve_draft()

    def solve_draft(self, selected_id=None):
        """Solve a private draft; OK applies its constraints and poses together."""
        from .scene_layout import is_physical, initialize_layout

        self.document.path_constraints = deepcopy(self.constraints)
        self.current_document.path_constraints = deepcopy(self.constraints)
        self.solution = None
        self.selected_constraint = selected_id
        self.refresh(selected_id)
        if not is_physical(self.current_document):
            return
        initialize_layout(self.current_document)
        from .physical_editor import SceneWorker

        packing = None
        if self.document.optimized_layout:
            parent = self.parent()
            if callable(getattr(parent, "packing", None)):
                packing = parent.packing()
        self.worker = SceneWorker(self.current_document, 0, final=True, packing=packing, parent=self)
        self.worker.completed.connect(self.solved)
        self.worker.failed.connect(self.solve_failed)
        self.worker.finished.connect(self.solve_finished)
        self.set_busy(True)
        self.solve_status.setText("Solving distance constraints; moving free components…")
        self.worker.start()

    def set_busy(self, busy):
        for widget in (self.table, self.a, self.b, self.target, self.add_button, self.delete_button):
            widget.setEnabled(not busy)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(not busy)
        if not busy:
            self.delete_button.setEnabled(bool(self.table.selectedItems()))
            self.endpoints_changed()

    def solved(self, result, revision, final):
        if self.pending_result == QtWidgets.QDialog.Rejected:
            return
        from .scene_layout import trace_scene

        # A draft may still intercept an unrelated optic. Keep that error
        # visible, but allow a distance edit whose optical equations and pins
        # are all satisfied. Optimized layouts also require verified packing.
        equations_satisfied = (
            result.status == "unresolved"
            and not self.document.optimized_layout
            and not self.current_document.layout.get("_separations")
            and trace_scene(self.current_document, result.poses, check_interceptions=False).ok
        )
        if result.ok or equations_satisfied:
            from .scene_solver import apply_scene_solution

            if self.document.optimized_layout:
                from .scene_optimization import update_scene_optimization

                try:
                    update_scene_optimization(self.document, result.poses)
                except ValueError as error:
                    self.solve_failed(str(error), revision)
                    return
            if result.ok:
                apply_scene_solution(self.current_document, result)
            else:
                self.current_document.layout["poses"] = deepcopy(result.poses)
            self.solution = result
            self.geometry = result.layout
            status = "Distances satisfied."
            if not result.ok:
                error = next(d.message for d in result.diagnostics if d.severity == "error")
                status += " Layout still needs attention: " + error
            self.solve_status.setText(status + " OK applies the component positions; Cancel discards them.")
        elif result.status != "cancelled":
            errors = [d.message for d in result.diagnostics if d.severity == "error"]
            self.solve_status.setText(
                "Could not satisfy all constraints. " + (errors[0] if errors else "Check pinned positions and other distances.")
            )
        self.refresh(self.selected_constraint)

    def solve_failed(self, message, revision):
        self.solve_status.setText("Distance solve failed: " + message)

    def solve_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.set_busy(False)
        if self.pending_result is not None:
            super().done(self.pending_result)

    def done(self, result):
        if self.worker is not None:
            self.pending_result = result
            if result == QtWidgets.QDialog.Rejected:
                self.worker.cancelled.set()
            return
        super().done(result)
