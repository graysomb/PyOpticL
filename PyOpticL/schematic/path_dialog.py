"""Edit total path constraints without changing the document until accepted."""

from copy import deepcopy

from .compiler import compile_schematic
from .model import PathLengthConstraint, connection_length, document_from_dict, new_id
from .paths import component_path, path_length
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
        self.current_document = self.document
        self.geometry = compile_schematic(document).geometry
        if self.geometry is not None and self.geometry.graph is not None:
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
        for node in self.document.nodes:
            self.a.addItem(node.reference, node.id)
            self.b.addItem(node.reference, node.id)
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
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(form)
        layout.addLayout(edit_buttons)
        layout.addWidget(self.note)
        layout.addWidget(buttons)
        self.refresh()
        self.endpoints_changed()

    def current_length(self, a, b):
        if self.geometry is None or a not in self.geometry.positions or b not in self.geometry.positions:
            return None
        try:
            return path_length(self.current_document, a, b, self.geometry.lengths)
        except ValueError:
            return None

    def refresh(self, selected_id=None):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.constraints))
        for row, item in enumerate(self.constraints):
            a, b = self.document.node(item.component_a), self.document.node(item.component_b)
            current = self.current_length(a.id, b.id)
            try:
                component_path(self.document, a.id, b.id)
                status = (
                    "Unavailable / rerun required"
                    if current is None
                    else ("Satisfied" if abs(current - item.length_mm) <= 1e-6 else "Unsatisfied")
                )
            except ValueError:
                status = "Disconnected route"
            values = (
                a.reference,
                b.reference,
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
            (item for item in self.constraints if {item.component_a, item.component_b} == {a, b}), None
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
        self.a.setCurrentIndex(self.a.findData(constraint.component_a))
        self.b.setCurrentIndex(self.b.findData(constraint.component_b))
        self.a.blockSignals(False)
        self.b.blockSignals(False)
        self.endpoints_changed()

    def add_constraint(self):
        a, b = self.a.currentData(), self.b.currentData()
        component_path(self.document, a, b)
        existing = next(
            (item for item in self.constraints if {item.component_a, item.component_b} == {a, b}), None
        )
        if existing:
            existing.length_mm = self.target.value()
            selected = existing.id
        else:
            item = PathLengthConstraint(new_id(), a, b, self.target.value())
            self.constraints.append(item)
            selected = item.id
        self.refresh(selected)

    def delete_constraint(self):
        items = self.table.selectedItems()
        if items:
            key = items[0].data(Qt.UserRole)
            self.constraints[:] = [item for item in self.constraints if item.id != key]
            self.refresh()
