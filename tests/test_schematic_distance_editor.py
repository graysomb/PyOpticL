"""Distance edits solve a private physical draft before applying it as one edit."""

from copy import deepcopy
from time import monotonic
import unittest

from PyOpticL.schematic import compile_schematic
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_layout import initialize_layout
from PyOpticL.schematic.scene_solver import solve_scene
from test_schematic import chain
from test_schematic_editor import QT_AVAILABLE

if QT_AVAILABLE:
    from PyOpticL.schematic.path_dialog import PathLengthsDialog
    from PyOpticL.schematic.qt import QtCore, QtWidgets
    from test_schematic_editor import QtTest
    import test_schematic_physical_editor as physical_editor_tests


def lens_pair():
    document = chain("source", "lens", "lens", "output")
    for node in document.nodes[1:3]:
        select_preset(node, "bare")
    initialize_layout(document)
    for node, x in zip(document.nodes, (0, 50, 127.941286, 200)):
        document.layout["poses"][node.id] = [x, 0, 0, 0]
    document.nodes[0].physical.update(x=0, y=0, angle=0)
    document.nodes[1].physical.update(x=50, y=0)
    return document


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable")
class DistanceDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.dialog = None

    def wait(self):
        deadline = monotonic() + 20
        while self.dialog.worker is not None and monotonic() < deadline:
            self.app.processEvents()
            QtTest.QTest.qWait(5)
        self.assertIsNone(self.dialog.worker, "Distance solve timed out")

    def tearDown(self):
        if self.dialog is not None:
            self.dialog.reject()
            self.wait()
            self.dialog.deleteLater()
        self.app.processEvents()

    def open(self, document, a=None, b=None):
        a = a or document.nodes[1].id
        b = b or document.nodes[2].id
        self.dialog = PathLengthsDialog(document, (a, b))
        return self.dialog

    def assert_satisfied(self, target):
        self.assertIsNotNone(self.dialog.solution, self.dialog.solve_status.text())
        self.assertTrue(self.dialog.solution.ok)
        self.assertEqual(self.dialog.table.item(0, 4).text(), "Satisfied")
        self.assertAlmostEqual(float(self.dialog.table.item(0, 3).text()), target, delta=1e-6)
        compiled = compile_schematic(self.dialog.current_document)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        self.assertAlmostEqual(compiled.path_lengths[self.dialog.constraints[0].id], target, delta=1e-6)

    def test_add_update_and_reverse_endpoints_move_free_lens_to_target(self):
        document = lens_pair()
        before = deepcopy(document.to_dict())
        dialog = self.open(document)
        self.assertAlmostEqual(dialog.target.value(), 77.941286)
        dialog.target.setValue(100)
        dialog.add_constraint()
        self.assertFalse(dialog.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled())
        self.wait()
        self.assert_satisfied(100)
        self.assertAlmostEqual(dialog.document.layout["poses"][document.nodes[2].id][0], 150, delta=1e-6)
        self.assertEqual(dialog.document.layout["poses"][document.nodes[1].id][:2], [50, 0])
        self.assertEqual(document.to_dict(), before)
        dialog.a.setCurrentIndex(dialog.a.findData(document.nodes[2].id))
        dialog.b.setCurrentIndex(dialog.b.findData(document.nodes[1].id))
        dialog.target.setValue(125)
        dialog.add_constraint()
        self.wait()
        self.assertEqual(len(dialog.constraints), 1)
        self.assert_satisfied(125)
        self.assertEqual(document.to_dict(), before)

    def test_fixed_beam_conflict_is_reported_without_moving_or_relaxing_it(self):
        document = lens_pair()
        document.connections[1].length = 77.941286
        before = deepcopy(document.to_dict())
        dialog = self.open(document)
        dialog.target.setValue(100)
        dialog.add_constraint()
        self.wait()
        self.assertIsNone(dialog.solution)
        self.assertEqual(dialog.table.item(0, 4).text(), "Unsatisfied")
        self.assertIn("fixed beams sum", dialog.solve_status.text())
        self.assertEqual(dialog.document.layout, document.layout)
        self.assertEqual(document.to_dict(), before)

    def test_cancel_during_solve_waits_for_worker_and_discards_positions(self):
        document = lens_pair()
        before = deepcopy(document.to_dict())
        dialog = self.open(document)
        dialog.target.setValue(100)
        dialog.add_constraint()
        dialog.reject()
        self.wait()
        self.assertEqual(dialog.result(), QtWidgets.QDialog.Rejected)
        self.assertEqual(document.to_dict(), before)

    def test_distance_reflows_a_folded_grating_and_lens_chain(self):
        from test_schematic_grating_constraints import grating_chain

        document = grating_chain(transmission=("lens", "lens"))
        initial = solve_scene(document)
        self.assertTrue(initial.ok, initial.diagnostics)
        document.layout["poses"] = initial.poses
        before = deepcopy(document.to_dict())
        dialog = self.open(document, document.nodes[3].id, document.nodes[4].id)
        dialog.target.setValue(100)
        dialog.add_constraint()
        self.wait()
        self.assert_satisfied(100)
        for node in document.nodes[:3]:
            self.assertEqual(dialog.document.layout["poses"][node.id][:2], document.layout["poses"][node.id][:2])
        self.assertEqual(document.to_dict(), before)

    def test_total_length_larger_than_next_component_position_pushes_the_receiver(self):
        document = lens_pair()
        before = deepcopy(document.to_dict())
        dialog = self.open(document)
        old_gap = document.layout["poses"][document.nodes[-1].id][0] - document.layout["poses"][document.nodes[2].id][0]
        dialog.target.setValue(500)
        dialog.add_constraint()
        self.wait()
        self.assert_satisfied(500)
        poses = dialog.document.layout["poses"]
        self.assertAlmostEqual(poses[document.nodes[2].id][0], 550, delta=1e-6)
        self.assertAlmostEqual(poses[document.nodes[-1].id][0] - poses[document.nodes[2].id][0], old_gap, delta=1e-6)
        self.assertEqual(document.to_dict(), before)

    def test_distance_edit_remains_available_in_a_draft_with_an_unrelated_interception(self):
        document = chain("fiber_source", "hwp", "mirror", "mirror", "grating", "lens", "lens",
                         "grating", "mirror", "mirror", "fiber_output")
        for node in document.nodes:
            select_preset(node, "POLARIS-K05T6" if node.kind.startswith("fiber_") else "bare")
        positions = ((0, 20, 0), (0, 0, 90), (0, -30, 135), (30, -30, 45), (30, 0, 135),
                     (55, 0, 0), (132.941286, 0, 0), (165, 0, 135), (165, 25, 30),
                     (190, 35, 80), (210, 10, 150))
        document.layout = {"poses": {node.id: [x, y, 0, angle]
                                    for node, (x, y, angle) in zip(document.nodes, positions)}}
        document.nodes[7].parameters["mirrored"] = 1
        before = deepcopy(document.to_dict())
        dialog = self.open(document, document.nodes[5].id, document.nodes[6].id)
        dialog.target.setValue(100)
        dialog.add_constraint()
        self.wait()
        self.assertIsNotNone(dialog.solution, dialog.solve_status.text())
        self.assertEqual(dialog.table.item(0, 4).text(), "Satisfied")
        self.assertAlmostEqual(float(dialog.table.item(0, 3).text()), 100, delta=1e-6)
        self.assertIn("unexpected interception", dialog.solve_status.text())
        self.assertFalse(compile_schematic(dialog.document).ok)
        self.assertEqual(document.to_dict(), before)


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable")
class DistanceEditorTests(unittest.TestCase):
    if QT_AVAILABLE:
        setUpClass = physical_editor_tests.PhysicalEditorTests.__dict__["setUpClass"]
        setUp = physical_editor_tests.PhysicalEditorTests.setUp
        tearDown = physical_editor_tests.PhysicalEditorTests.tearDown
        open = physical_editor_tests.PhysicalEditorTests.open
        settle = physical_editor_tests.PhysicalEditorTests.settle

    def test_distance_edit_preserves_a_verified_optimized_layout(self):
        from PyOpticL.schematic.optimization import (
            OptimizationOptions, PackingBox, build_problem, optimize_layout, apply_optimization,
        )

        document = lens_pair()
        radii = {node.id: 8 for node in document.nodes[1:3]}
        problem = build_problem(document, radii, PackingBox(-50, -100, 400, 250),
                                OptimizationOptions(starts=1, iterations=2, projection_passes=2,
                                                    max_added_mirrors=0))
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        apply_optimization(document, problem, result)
        self.check_edit(document)

    def test_accept_applies_distance_and_positions_as_one_undoable_edit(self):
        self.check_edit(lens_pair())

    def check_edit(self, document):
        e = self.open(document)
        before = deepcopy(e.document.to_dict())
        history_index = e.history.index
        for node in e.document.nodes[1:3]:
            e.scene.symbols[node.id].setSelected(True)

        def edit():
            dialog = next(widget for widget in self.app.topLevelWidgets()
                          if isinstance(widget, PathLengthsDialog))
            dialog.target.setValue(100)
            dialog.add_constraint()
            dialog.worker.finished.connect(lambda: QtCore.QTimer.singleShot(0, dialog.accept))

        QtCore.QTimer.singleShot(0, edit)
        e.edit_path_lengths()
        self.settle()
        self.assertEqual(e.history.index, history_index + 1)
        result = compile_schematic(e.document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertAlmostEqual(next(iter(result.path_lengths.values())), 100, delta=1e-6)
        after = deepcopy(e.document.to_dict())
        e.undo()
        self.settle()
        self.assertEqual(e.document.to_dict(), before)
        e.redo()
        self.settle()
        self.assertEqual(e.document.to_dict(), after)


if __name__ == "__main__":
    unittest.main()
