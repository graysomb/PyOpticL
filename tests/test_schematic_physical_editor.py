"""Default physical canvas workflows; legacy canvas tests remain separate."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PyOpticL.bounds import BoundingCircleXY
from PyOpticL.schematic import compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.bounds import BoundsProvider
from test_schematic_multipass import double_pass
from test_schematic import chain
from test_schematic_editor import QT_AVAILABLE

if QT_AVAILABLE:
    from PyOpticL.schematic.editor import SchematicEditor
    from PyOpticL.schematic.physical_editor import PhysicalSchematicEditor
    from PyOpticL.schematic.qt import QtCore, QtGui, QtWidgets
    from test_schematic_editor import QtTest


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable")
class PhysicalEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.editor = None

    def tearDown(self):
        if self.editor:
            self.editor.history.mark_saved()
            self.editor.close()
        self.app.processEvents()

    def open(self, doc=None):
        self.editor = SchematicEditor(
            doc or double_pass(), bounds_provider=BoundsProvider(lambda spec: BoundingCircleXY(20))
        )
        self.editor.resize(1100, 700)
        self.editor.show()
        self.settle()
        return self.editor

    def settle(self):
        for _ in range(120):
            self.app.processEvents()
            if not self.editor.workers:
                break
            QtTest.QTest.qWait(10)
        self.app.processEvents()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.assertFalse(any(w.isRunning() for w in self.editor.workers))

    def select(self, node_id):
        self.editor.scene.clearSelection()
        self.editor.scene.symbols[node_id].setSelected(True)
        self.app.processEvents()

    def test_default_editor_is_physical_and_has_one_symbol_per_component(self):
        e = self.open()
        self.assertIsInstance(e, PhysicalSchematicEditor)
        self.assertEqual(len(e.scene.symbols), 6)
        self.assertEqual(len(e.document.optical_passes()), 8)
        self.assertTrue(compile_schematic(e.document).ok)
        self.assertFalse(e.bounds_toggle.isChecked())

    def test_optic_body_dimensions_and_common_circle_scale(self):
        e = self.open()
        lens = e.scene.symbols["part-1"]
        self.assertAlmostEqual(lens.outline.boundingRect().height(), 12.7)
        e.bounds_toggle.setChecked(True)
        self.settle()
        self.app.processEvents()
        lens = e.scene.symbols["part-1"]
        self.assertAlmostEqual(lens.bounds_circle.rect().width(), 40.0)
        self.assertTrue(lens.bounds_circle.isVisible())
        e.projection_choice.setCurrentText("XZ")
        self.settle()
        self.assertFalse(e.scene.symbols["part-1"].bounds_circle.isVisible())

    def test_escape_cancels_wiring_in_the_current_physical_scene(self):
        from PyOpticL.schematic import Endpoint

        e = self.open(chain("source", "lens", "output"))
        endpoint = Endpoint(e.document.nodes[0].id, "beam")
        e.scene.wire(endpoint)
        self.assertIsNotNone(e.scene.pending)
        e.view.setFocus()
        QtTest.QTest.keyClick(e.view, QtCore.Qt.Key_Escape)
        self.app.processEvents()
        self.assertIsNone(e.scene.pending)

    def test_pass_selector_add_remove_and_undo_do_not_duplicate_parts(self):
        e = self.open(chain("source", "lens", "output"))
        node = e.document.nodes[1]
        self.select(node.id)
        e.findChild(QtWidgets.QPushButton, "addOpticalPass").click()
        self.settle()
        self.assertEqual(len(e.document.nodes), 3)
        self.assertEqual(len(e.document.optical_passes()), 4)
        self.assertEqual(e.findChild(QtWidgets.QComboBox, "opticalPass").count(), 2)
        e.findChild(QtWidgets.QPushButton, "removeOpticalPass").click()
        self.settle()
        self.assertEqual(len(e.document.optical_passes()), 3)
        e.undo()
        self.settle()
        self.assertEqual(len(e.document.optical_passes()), 4)
        e.redo()
        self.settle()
        self.assertEqual(len(e.document.optical_passes()), 3)

    def test_angle_checkbox_belongs_to_selected_pass(self):
        e = self.open()
        self.select("part-4")
        p = e.add_optical_pass("part-4")
        self.settle()
        toggle = e.findChild(QtWidgets.QCheckBox, "opticAngleConstrained")
        toggle.setChecked(True)
        self.settle()
        self.assertIsNotNone(e.document.optical_pass(p.id).turn)
        self.assertIsNone(e.document.optical_pass("part-4").turn)
        self.assertNotIn("turn", e.document.node("part-4").physical)

    def test_successful_drag_is_one_undoable_edit_and_preserves_constraints(self):
        e = self.open()
        before = deepcopy(e.document.to_dict())
        index = e.history.index
        e.begin_drag()
        e.start_solve((("part-3", 0, 210.0),), True)
        self.settle()
        self.assertEqual(e.history.index, index + 1)
        self.assertAlmostEqual(e.document.layout["poses"]["part-3"][0], 210, delta=1e-6)
        self.assertEqual([n.physical for n in e.document.nodes], [n["physical"] for n in before["nodes"]])
        e.undo()
        self.settle()
        self.assertAlmostEqual(e.document.layout["poses"]["part-3"][0], 200, delta=1e-6)

    def test_pinned_drag_is_rejected_and_reports_residual(self):
        doc = double_pass()
        doc.nodes[3].physical["x"] = 200
        e = self.open(doc)
        index = e.history.index
        e.begin_drag()
        e.start_solve((("part-3", 0, 210.0),), True)
        self.settle()
        self.assertEqual(e.history.index, index)
        self.assertEqual(e.document.layout["poses"]["part-3"][0], 200)
        self.assertTrue(
            any("Requested drag position" in e.messages.item(i).text() for i in range(e.messages.count()))
        )

    def test_projection_and_save_load_preserve_shared_geometry(self):
        e = self.open(double_pass(True))
        e.projection_choice.setCurrentText("XZ")
        self.settle()
        before = deepcopy(e.document.layout["poses"])
        e.projection_choice.setCurrentText("XY")
        self.settle()
        self.assertEqual(e.document.layout["poses"], before)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "passes.json"
            save_schematic(e.document, path)
            d = load_schematic(path)
            self.assertEqual(d.to_dict(), e.document.to_dict())
            self.assertTrue(compile_schematic(d).ok)

    def test_redundant_warning_keeps_export_enabled(self):
        doc = chain("source", "lens", "output")
        e = self.open(doc)
        doc.nodes[0].physical.update(x=0, y=0, angle=0)
        doc.nodes[1].physical["x"] = 50
        doc.connections[0].length = 50
        e.commit()
        self.settle()
        result = e.validate()
        self.assertTrue(result.ok, result.diagnostics)
        self.assertTrue(any(d.severity == "warning" for d in result.diagnostics))

    def test_body_mouse_drag_runs_solver_without_adding_position_pin(self):
        e = self.open()
        e.fit()
        self.app.processEvents()
        item = e.scene.symbols["part-3"]
        self.select("part-3")
        start = e.view.mapFromScene(item.scenePos() + QtCore.QPointF(5, 5))
        end = start + QtCore.QPoint(15, 0)
        viewport = e.view.viewport()
        QtTest.QTest.mousePress(viewport, QtCore.Qt.LeftButton, pos=start)
        QtTest.QTest.mouseMove(viewport, end)
        QtTest.QTest.mouseRelease(viewport, QtCore.Qt.LeftButton, pos=end)
        self.settle()
        self.assertNotIn("x", e.document.node("part-3").physical)
        self.assertTrue(compile_schematic(e.document).ok)


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable")
class PhysicalApplicationTests(unittest.TestCase):
    setUpClass = classmethod(PhysicalEditorTests.setUpClass.__func__)
    setUp = PhysicalEditorTests.setUp
    tearDown = PhysicalEditorTests.tearDown
    open = PhysicalEditorTests.open
    settle = PhysicalEditorTests.settle
    select = PhysicalEditorTests.select

    def test_optimizer_worker_apply_undo_redo_and_clear_update_physical_canvas(self):
        from dataclasses import replace
        from PyOpticL.schematic.optimize_dialog import OptimizeLayoutDialog

        doc = chain("source", "lens", "output")
        doc.nodes[1].preset = "bare"
        e = self.open(doc)
        before = deepcopy(doc.layout["poses"])
        constraints = deepcopy([n.physical for n in doc.nodes])
        dialog = OptimizeLayoutDialog(doc, BoundsProvider(lambda spec: BoundingCircleXY(8)), e)
        dialog.options = replace(dialog.options, starts=1, iterations=2, projection_passes=2)
        frames = []
        dialog.start_search()
        dialog.worker.progressed.connect(frames.append)
        for _ in range(400):
            self.app.processEvents()
            if dialog.worker is None:
                break
            QtTest.QTest.qWait(5)
        self.assertIsNotNone(dialog.solution)
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertTrue(frames)
        self.assertTrue(e.apply_optimized_result(dialog.problem, dialog.solution))
        self.settle()
        self.assertIsNotNone(e.document.optimized_layout)
        self.assertEqual([n.physical for n in e.document.nodes], constraints)
        e.undo()
        self.settle()
        self.assertIsNone(e.document.optimized_layout)
        e.redo()
        self.settle()
        self.assertIsNotNone(e.document.optimized_layout)
        e.clear_optimized_layout()
        self.settle()
        self.assertIsNone(e.document.optimized_layout)
        self.assertEqual(e.document.layout["poses"], before)
        dialog.deleteLater()

    def test_generated_mirrors_read_only_and_folded_beams_select_original_constraints(self):
        doc = load_schematic(
            Path(__file__).resolve().parents[1]
            / "Designs/schematics/multipass/folding-after.pyopticl-schematic.json"
        )
        e = self.open(doc)
        original_ids = {n.id for n in doc.nodes}
        added = [item for key, item in e.scene.symbols.items() if key not in original_ids]
        self.assertEqual(len(added), 2)
        self.assertTrue(all(not item.flags() & QtWidgets.QGraphicsItem.ItemIsMovable for item in added))
        beam = next(iter(e.scene.connections.values()))
        beam.setSelected(True)
        self.app.processEvents()
        self.assertEqual(beam.connection.id, "span")
        self.assertAlmostEqual(e.findChild(QtWidgets.QDoubleSpinBox, "beamLengthMm").value(), 60, delta=1e-6)
        labels = [label.text() for label in e.properties.findChildren(QtWidgets.QLabel)]
        self.assertTrue(any("180.000000" in label for label in labels), labels)

    def test_omitted_part_has_no_position_readout_and_new_constraint_invalidates_snapshot(self):
        from test_schematic_scene_optimization import removable_scene
        from PyOpticL.schematic.optimization import (
            OptimizationOptions,
            PackingBox,
            build_problem,
            optimize_layout,
            apply_optimization,
        )

        doc = removable_scene()
        mirror = doc.nodes[1]
        problem = build_problem(
            doc,
            {mirror.id: 9},
            PackingBox(0, 0, 200, 100),
            OptimizationOptions(starts=1, iterations=600, projection_passes=2),
        )
        apply_optimization(doc, problem, optimize_layout(problem))
        e = self.open(doc)
        self.assertNotIn(mirror.id, e.scene.symbols)
        e.inspect_omitted(mirror.id)
        labels = [label.text() for label in e.properties.findChildren(QtWidgets.QLabel)]
        self.assertTrue(any("No current physical position" in text for text in labels), labels)
        self.assertIsNone(e.findChild(QtWidgets.QDoubleSpinBox, "opticPositionX"))
        e.set_optic_position(mirror.id, (70, 20))
        self.settle()
        self.assertFalse(compile_schematic(e.document).ok)
        self.assertNotIn(mirror.id, e.scene.symbols)
        e.undo()
        self.settle()
        self.assertTrue(compile_schematic(e.document).ok)
        e.clear_optimized_layout()
        self.settle()
        self.assertIn(mirror.id, e.scene.symbols)

    def test_cancel_optimizer_keeps_physical_document_unchanged(self):
        from PyOpticL.schematic.optimize_dialog import OptimizeLayoutDialog

        e = self.open(chain("source", "lens", "output"))
        before = deepcopy(e.document.to_dict())
        dialog = OptimizeLayoutDialog(e.document, BoundsProvider(lambda spec: BoundingCircleXY(8)), e)
        dialog.start_search()
        dialog.reject()
        for _ in range(400):
            self.app.processEvents()
            if dialog.worker is None:
                break
            QtTest.QTest.qWait(5)
        self.assertEqual(e.document.to_dict(), before)
        self.assertEqual(dialog.result(), QtWidgets.QDialog.Rejected)
        dialog.deleteLater()

    def test_path_dialog_can_select_two_passes_of_the_same_component(self):
        from PyOpticL.schematic.path_dialog import PathLengthsDialog

        e = self.open()
        dialog = PathLengthsDialog(e.document)
        dialog.a.setCurrentIndex(dialog.a.findData("part-1"))
        dialog.b.setCurrentIndex(dialog.b.findData("lens-return"))
        self.assertTrue(dialog.add_button.isEnabled())
        self.assertAlmostEqual(dialog.target.value(), 325.4, delta=1e-6)
        dialog.add_constraint()
        constraint = dialog.constraints[-1]
        self.assertEqual(constraint.component_a, constraint.component_b)
        self.assertEqual(constraint.pass_b, "lens-return")
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
