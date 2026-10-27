"""Qt path editing, topology-changing previews and omitted-part inspectors."""

from copy import deepcopy
from dataclasses import asdict
from time import monotonic
import unittest
from unittest.mock import Mock

from PyOpticL.bounds import BoundingCircleXY
from PyOpticL.schematic import compile_schematic
from PyOpticL.schematic.bounds import BoundsProvider
from PyOpticL.schematic.optimization import optimize_layout
from test_schematic import chain
from test_schematic_editor import QT_AVAILABLE
from test_schematic_folding import fold_span, removable_mirror, RADIUS

if QT_AVAILABLE:
    from PyOpticL.schematic.editor import LegacySchematicEditor as SchematicEditor
    from PyOpticL.schematic.path_dialog import PathLengthsDialog
    from PyOpticL.schematic.optimize_dialog import OptimizeLayoutDialog
    from PyOpticL.schematic.qt import QtCore, QtGui, QtWidgets
    from test_schematic_editor import QtTest


@unittest.skipUnless(QT_AVAILABLE, "Qt runtime not installed")
class FoldingEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.provider = BoundsProvider(lambda spec: BoundingCircleXY(RADIUS))
        self.editor = None
        self.dialog = None

    def tearDown(self):
        if self.dialog is not None:
            self.dialog.reject()
            if hasattr(self.dialog, "worker"):
                self.wait(lambda: self.dialog.worker is None)
            self.dialog.close()
        if self.editor is not None:
            self.editor.history.mark_saved()
            self.editor.close()
        self.app.processEvents()

    def wait(self, condition):
        deadline = monotonic() + 20
        while not condition() and monotonic() < deadline:
            self.app.processEvents()
            QtTest.QTest.qWait(5)
        self.assertTrue(condition(), "Worker timed out")

    def open_editor(self, doc):
        self.editor = SchematicEditor(doc, bounds_provider=self.provider)
        self.editor.show()
        self.app.processEvents()
        return self.editor

    def flush(self):
        self.app.processEvents()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def test_path_dialog_selection_edit_highlight_apply_and_undo(self):
        doc = chain("source", "lens", "output")
        editor = self.open_editor(doc)
        selected = [doc.nodes[0].id, doc.nodes[-1].id]
        for key in selected:
            editor.scene.symbols[key].setSelected(True)
        before = deepcopy(doc.to_dict())

        def edit_dialog():
            dialog = next(
                widget for widget in self.app.topLevelWidgets() if isinstance(widget, PathLengthsDialog)
            )
            self.assertEqual({dialog.a.currentData(), dialog.b.currentData()}, set(selected))
            dialog.target.setValue(140)
            QtTest.QTest.mouseClick(dialog.add_button, QtCore.Qt.LeftButton)
            self.assertEqual(dialog.table.rowCount(), 1)
            self.assertEqual(dialog.table.item(0, 4).text(), "Unsatisfied")
            self.assertEqual(
                {item.connection.id for item in editor.scene.selectedItems() if hasattr(item, "connection")},
                {edge.id for edge in doc.connections},
            )
            dialog.accept()

        QtCore.QTimer.singleShot(0, edit_dialog)
        editor.edit_path_lengths()
        self.assertEqual(editor.history.index, 1)
        self.assertEqual(editor.document.path_constraints[0].length_mm, 140)
        self.assertEqual(editor.document.to_dict()["nodes"], before["nodes"])
        self.assertEqual(
            compile_schematic(editor.document).path_lengths[
                next(iter([item.id for item in editor.document.path_constraints]))
            ],
            140,
        )
        editor.undo()
        self.assertFalse(editor.document.path_constraints)
        editor.redo()
        self.assertEqual(editor.document.path_constraints[0].length_mm, 140)

    def test_path_dialog_cancel_and_delete_do_not_modify_owner(self):
        doc = chain("source", "lens", "output")
        self.open_editor(doc)
        self.dialog = PathLengthsDialog(doc, [doc.nodes[0].id, doc.nodes[-1].id], self.editor)
        self.dialog.target.setValue(150)
        self.dialog.add_constraint()
        self.assertFalse(doc.path_constraints)
        self.dialog.delete_constraint()
        self.assertFalse(self.dialog.constraints)
        self.dialog.reject()
        self.assertFalse(doc.path_constraints)
        self.assertEqual(self.editor.history.index, 0)

    def test_beam_folding_and_mirror_role_controls(self):
        doc = chain("source", "mirror", "output")
        editor = self.open_editor(doc)
        edge = doc.connections[0]
        editor.scene.connections[edge.id].setSelected(True)
        self.flush()
        toggle = editor.findChild(QtWidgets.QCheckBox, "beamAllowFolding")
        self.assertFalse(toggle.isChecked())
        QtTest.QTest.mouseClick(toggle, QtCore.Qt.LeftButton, pos=QtCore.QPoint(8, 8))
        self.assertTrue(edge.allow_folding)
        editor.scene.clearSelection()
        mirror = doc.nodes[1]
        editor.scene.symbols[mirror.id].setSelected(True)
        self.flush()
        role = editor.findChild(QtWidgets.QComboBox, "mirrorRole")
        self.assertEqual(role.currentText(), "Turning")
        role.setCurrentText("Folding")
        self.assertEqual(mirror.mirror_role, "folding")
        editor.undo()
        self.assertEqual(editor.document.nodes[1].mirror_role, "turning")

    def test_worker_previews_added_mirror_and_inspector_distinguishes_path_from_chord(self):
        doc, problem = fold_span()
        doc.optimization = {"box": asdict(problem.box), "options": asdict(problem.options)}
        editor = self.open_editor(doc)
        before = deepcopy(doc.to_dict())
        self.dialog = OptimizeLayoutDialog(doc, self.provider, editor)
        self.dialog.show()
        self.assertAlmostEqual(self.dialog.folding_radius, RADIUS)
        self.dialog.start_search()
        self.wait(lambda: self.dialog.worker is None)
        self.assertEqual(self.dialog.solution.status, "feasible", self.dialog.status.text())
        self.assertIn("FM1", self.dialog.changes.text())
        labels = [
            item.text()
            for item in self.dialog.preview.scene().items()
            if isinstance(item, QtWidgets.QGraphicsSimpleTextItem)
        ]
        self.assertTrue(any("(added)" in label for label in labels))
        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.assertTrue(editor.apply_optimized_result(self.dialog.problem, self.dialog.solution))
        self.assertEqual(editor.document.to_dict()["nodes"], before["nodes"])
        self.assertEqual(editor.document.to_dict()["connections"], before["connections"])
        editor.scene.connections[doc.connections[0].id].setSelected(True)
        self.flush()
        self.assertAlmostEqual(
            editor.findChild(QtWidgets.QDoubleSpinBox, "beamLengthMm").value(), 80, places=6
        )
        notes = [item.text() for item in editor.findChildren(QtWidgets.QLabel)]
        self.assertTrue(any("120.000000" in text and "Routed" in text for text in notes))
        self.assertTrue(any("FM1: added Folding mirror" in text and "Physical XY" in text for text in notes))
        editor.set_connection_folding(doc.connections[0].id, False)
        self.assertFalse(compile_schematic(doc).ok)
        self.assertIn("stale", editor.status.text())
        editor.undo()
        self.assertTrue(compile_schematic(editor.document).ok)
        editor.clear_optimized_layout()
        self.assertIsNone(editor.document.optimized_layout)

    def test_path_diagnostic_keeps_the_whole_route_highlighted(self):
        from PyOpticL.schematic import PathLengthConstraint

        doc = chain("source", "lens", "output")
        for edge in doc.connections:
            edge.length = 50
        doc.path_constraints.append(PathLengthConstraint("conflict", doc.nodes[0].id, doc.nodes[-1].id, 120))
        editor = self.open_editor(doc)
        result = editor.validate()
        self.assertFalse(result.ok)
        editor.focus_diagnostic(editor.messages.item(0))
        selected = {
            item.connection.id for item in editor.scene.selectedItems() if hasattr(item, "connection")
        }
        self.assertEqual(selected, {edge.id for edge in doc.connections})

    def test_missing_generated_part_bounds_blocks_run_and_refresh_retries(self):
        doc, problem = fold_span()
        doc.optimization = {"box": asdict(problem.box), "options": asdict(problem.options)}
        editor = self.open_editor(doc)
        self.provider.compute = Mock(side_effect=ValueError("mirror mesh missing"))
        self.dialog = OptimizeLayoutDialog(doc, self.provider, editor)
        self.assertFalse(self.dialog.run_button.isEnabled())
        self.assertIn("Added folding mirror", self.dialog.violations.item(0).text())
        self.provider.compute = Mock(return_value=BoundingCircleXY(RADIUS))
        self.dialog.refresh_bounds()
        self.assertTrue(self.dialog.run_button.isEnabled())
        self.dialog.fields["folding_diameter"].setValue(25.4)
        self.assertAlmostEqual(self.dialog.problem.options.folding_diameter_mm, 25.4)
        self.dialog.folding_preset.setCurrentText("mounted")
        self.assertFalse(self.dialog.run_button.isEnabled())
        self.assertIn("12.7", self.dialog.violations.item(0).text())

    def test_omitted_mirror_has_no_fabricated_position_and_setting_constraint_protects_it(self):
        doc, problem = removable_mirror()
        editor = self.open_editor(doc)
        result = optimize_layout(problem)
        self.assertTrue(editor.apply_optimized_result(problem, result))
        mirror = doc.nodes[1]
        editor.scene.symbols[mirror.id].setSelected(True)
        self.flush()
        self.assertIsNone(editor.findChild(QtWidgets.QDoubleSpinBox, "opticPositionX"))
        self.assertTrue(
            any(
                "No current physical position" in widget.text()
                for widget in editor.findChildren(QtWidgets.QLabel)
            )
        )
        editor.set_optic_position(mirror.id, (50, 0))
        self.assertFalse(compile_schematic(doc).ok)
        self.assertIn("stale", editor.status.text())
        from PyOpticL.schematic.effective import folding_protection

        self.assertIn("Position", folding_protection(doc, mirror.id))


if __name__ == "__main__":
    unittest.main()
