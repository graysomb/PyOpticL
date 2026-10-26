"""Worker lifecycle and physical-preview GUI using deterministic fake CAD bounds."""

from copy import deepcopy
from dataclasses import replace
from threading import get_ident
from time import monotonic
import unittest
from unittest.mock import Mock

from PyOpticL.bounds import BoundingCircleXY
from PyOpticL.schematic import compile_schematic
from PyOpticL.schematic.bounds import BoundsProvider, resolve_layout_bounds
from test_schematic import branched, chain
from test_schematic_optimization import folding_fixture
from test_schematic_editor import QT_AVAILABLE

if QT_AVAILABLE:
    from PyOpticL.schematic.editor import SchematicEditor
    from PyOpticL.schematic.optimize_dialog import OptimizeLayoutDialog
    from PyOpticL.schematic.qt import QtCore, QtWidgets
    from test_schematic_editor import QtTest


@unittest.skipUnless(QT_AVAILABLE, "Qt runtime not installed")
class OptimizationEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.gui_thread = get_ident()
        self.calls = []

        def compute(spec):
            self.calls.append(get_ident())
            return BoundingCircleXY(5)

        self.provider = BoundsProvider(compute)
        self.editor = SchematicEditor(folding_fixture(), bounds_provider=self.provider)
        self.editor.show()
        self.app.processEvents()
        self.dialog = None

    def tearDown(self):
        if self.dialog is not None:
            self.dialog.reject()
            self.wait_until(lambda: self.dialog.worker is None)
            self.dialog.close()
        self.editor.history.mark_saved()
        self.editor.close()
        self.app.processEvents()

    def wait_until(self, predicate, seconds=10):
        deadline = monotonic() + seconds
        while not predicate() and monotonic() < deadline:
            self.app.processEvents()
            QtTest.QTest.qWait(5)
        self.assertTrue(predicate(), "Worker did not finish in time")

    def open_dialog(self):
        self.dialog = OptimizeLayoutDialog(self.editor.document, self.provider, self.editor)
        self.dialog.options = replace(self.dialog.options, starts=2, iterations=300)
        self.dialog.show()
        self.app.processEvents()
        return self.dialog

    def test_worker_progress_apply_gating_and_gui_thread_bounds(self):
        before = deepcopy(self.editor.document.to_dict())
        dialog = self.open_dialog()
        self.assertTrue(dialog.isModal())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertTrue(dialog.run_button.isEnabled())
        self.assertFalse(self.editor.bounds_toggle.isChecked())
        QtTest.QTest.mouseClick(dialog.run_button, QtCore.Qt.LeftButton)
        self.assertFalse(dialog.run_button.isEnabled())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertTrue(all(not f.isEnabled() for f in dialog.fields.values()))
        self.wait_until(lambda: dialog.worker is None)
        self.assertEqual(dialog.solution.status, "feasible")
        self.assertGreater(dialog.progress.value(), 0)
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertEqual(self.calls, [self.gui_thread] * len(self.calls))
        self.assertEqual(self.editor.document.to_dict(), before)
        self.assertTrue(dialog.preview.scene().items())
        QtTest.QTest.mouseClick(dialog.apply_button, QtCore.Qt.LeftButton)
        self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
        self.assertTrue(self.editor.apply_optimized_result(dialog.problem, dialog.solution))
        self.assertEqual(self.editor.document.to_dict()["nodes"], before["nodes"])
        self.assertEqual(self.editor.document.to_dict()["connections"], before["connections"])
        self.assertEqual(self.editor.history.index, 1)
        self.assertTrue(compile_schematic(self.editor.document).ok)
        self.assertTrue(self.editor.actions["clear_optimized"].isEnabled())
        self.editor.undo()
        self.assertIsNone(self.editor.document.optimized_layout)
        self.editor.redo()
        self.assertIsNotNone(self.editor.document.optimized_layout)
        self.editor.clear_optimized_layout()
        self.assertIsNone(self.editor.document.optimized_layout)
        self.editor.undo()
        self.assertIsNotNone(self.editor.document.optimized_layout)

    def test_cancel_stops_worker_and_leaves_document_unchanged(self):
        dialog = self.open_dialog()
        for n in dialog.document.nodes:
            n.physical.update(x=10, y=10)
        dialog.options = replace(dialog.options, iterations=5000, starts=8)
        before = deepcopy(self.editor.document.to_dict())
        dialog.start_search()
        self.app.processEvents()
        dialog.reject()
        self.wait_until(lambda: dialog.worker is None)
        self.assertEqual(dialog.solution.status, "cancelled")
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(self.editor.document.to_dict(), before)
        self.assertEqual(QtWidgets.QDialog.result(dialog), QtWidgets.QDialog.Rejected)

    def test_missing_geometry_blocks_run_with_actionable_error_and_refresh(self):
        self.provider.compute = Mock(side_effect=ValueError("mesh unavailable"))
        dialog = self.open_dialog()
        self.assertFalse(dialog.run_button.isEnabled())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.fields["width"].value(), 300)
        self.assertEqual(dialog.fields["height"].value(), 200)
        self.assertIn("geometry", dialog.status.text())
        self.assertIn("mesh unavailable", dialog.violations.item(0).text())
        self.provider.compute = Mock(return_value=BoundingCircleXY(5))
        dialog.refresh_bounds()
        self.assertTrue(dialog.run_button.isEnabled())
        self.assertFalse(dialog.bounds_errors)

    def test_inspectors_show_effective_free_values_without_constraint_checks(self):
        dialog = self.open_dialog()
        dialog.start_search()
        self.wait_until(lambda: dialog.worker is None)
        self.assertTrue(self.editor.apply_optimized_result(dialog.problem, dialog.solution))
        doc = self.editor.document
        mirror = doc.nodes[1]
        self.editor.scene.symbols[mirror.id].setSelected(True)
        self.app.processEvents()
        angle = self.editor.findChild(QtWidgets.QDoubleSpinBox, "opticAngleDeg")
        # Cleared inspectors are deleteLater'd; flush before resolving fields.
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        angle = self.editor.findChild(QtWidgets.QDoubleSpinBox, "opticAngleDeg")
        self.assertAlmostEqual(angle.value(), 53.130102, places=6)
        self.assertFalse(angle.isEnabled())
        check = self.editor.findChild(QtWidgets.QCheckBox, "opticAngleConstrained")
        self.assertFalse(check.isChecked())
        self.assertFalse(self.editor.findChild(QtWidgets.QCheckBox, "opticPositionConstrained").isChecked())
        self.assertEqual(self.editor.findChild(QtWidgets.QDoubleSpinBox, "opticPositionX").value(), 50)
        self.editor.scene.clearSelection()
        self.editor.scene.connections[doc.connections[-1].id].setSelected(True)
        self.app.processEvents()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.assertFalse(self.editor.findChild(QtWidgets.QCheckBox, "beamLengthConstrained").isChecked())
        self.assertAlmostEqual(
            self.editor.findChild(QtWidgets.QDoubleSpinBox, "beamLengthMm").value(), 50, places=6
        )

    def test_free_source_inspector_shows_applied_direction(self):
        source = self.editor.document.nodes[0]
        self.editor.set_source_direction(source.id, None)
        dialog = self.open_dialog()
        dialog.start_search()
        self.wait_until(lambda: dialog.worker is None)
        self.assertTrue(self.editor.apply_optimized_result(dialog.problem, dialog.solution))
        self.editor.scene.symbols[source.id].setSelected(True)
        self.app.processEvents()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        field = self.editor.findChild(QtWidgets.QDoubleSpinBox, "sourceDirectionDeg")
        self.assertAlmostEqual(field.value(), dialog.solution.layout.source_direction, places=6)
        self.assertFalse(field.isEnabled())
        self.assertFalse(self.editor.findChild(QtWidgets.QCheckBox, "sourceDirectionConstrained").isChecked())

    def test_source_direction_checkbox_preserves_old_explicit_angles(self):
        source = self.editor.document.nodes[0]
        self.editor.scene.symbols[source.id].setSelected(True)
        self.app.processEvents()
        check = self.editor.findChild(QtWidgets.QCheckBox, "sourceDirectionConstrained")
        self.assertTrue(check.isChecked())
        check.setChecked(False)
        self.assertNotIn("angle", source.physical)
        field = self.editor.findChild(QtWidgets.QDoubleSpinBox, "sourceDirectionDeg")
        self.assertFalse(field.isEnabled())
        check.setChecked(True)
        field.setValue(25)
        self.assertEqual(source.physical["angle"], 25)

    def test_failed_search_lists_violations_and_config_edit_revokes_apply(self):
        dialog = self.open_dialog()
        dialog.fields["width"].setValue(2)
        dialog.options = replace(dialog.options, iterations=3)
        dialog.start_search()
        self.wait_until(lambda: dialog.worker is None)
        self.assertIn("No feasible layout found", dialog.status.text())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertGreater(dialog.violations.count(), 0)
        dialog.fields["width"].setValue(240)
        self.assertIsNone(dialog.solution)
        self.assertFalse(dialog.apply_button.isEnabled())

    def test_splitter_bounds_resolve_both_free_plane_signs(self):
        d = branched()
        specs = []
        provider = BoundsProvider(
            lambda spec: specs.append(spec)
            or BoundingCircleXY(8 if dict(spec.before).get("rotate_cube") else 5)
        )
        radii, errors = resolve_layout_bounds(d, provider)
        self.assertFalse(errors)
        self.assertEqual(radii[d.nodes[2].id], 8)
        self.assertEqual(
            {dict(s.before)["rotate_cube"] for s in specs if s.factory == "Beamsplitter_Cube"}, {False, True}
        )


if __name__ == "__main__":
    unittest.main()
