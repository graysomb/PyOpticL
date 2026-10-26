"""Absolute incoming beam directions at open outputs, receivers and beam stops."""

import ast
from copy import deepcopy
from dataclasses import asdict
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from types import SimpleNamespace
import unittest

from PyOpticL.bounds import BoundingCircleXY
from PyOpticL.schematic import History, compile_schematic, load_schematic, save_schematic, validate_schematic
from PyOpticL.schematic.bounds import BoundsProvider
from PyOpticL.schematic.optimization import (
    OptimizationOptions,
    PackingBox,
    apply_optimization,
    build_problem,
    layout_violations,
    optimize_layout,
    project_constraints,
)
from PyOpticL.schematic.runtime import check_trace
from test_schematic import chain
from test_schematic_editor import QT_AVAILABLE
from test_schematic_folding import fold_span, folded_splitter, RADIUS

if QT_AVAILABLE:
    from PyOpticL.schematic.editor import SchematicEditor
    from PyOpticL.schematic.optimize_dialog import OptimizeLayoutDialog
    from PyOpticL.schematic.qt import QtCore, QtWidgets
    from test_schematic_editor import QtTest


def incoming_angle(document, layout, target):
    from PyOpticL.schematic.effective import effective_document
    from PyOpticL.schematic.topology import resolve_topology

    physical = (
        effective_document(document, layout.graph, OptimizationOptions(**document.optimization["options"]))
        if layout.graph
        else document
    )
    topology = resolve_topology(physical)
    edge = next(edge for edge in topology.edges.values() if edge.target.node_id == target.id)
    a, b = layout.positions[edge.source.node_id], layout.positions[target.id]
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def output_fixture(kind="output", target=-45):
    doc = chain("source", "mirror", kind)
    doc.nodes[0].physical.update(x=0, y=0, angle=0)
    doc.nodes[-1].physical["angle"] = target
    doc.nodes[1].preset = "bare"
    doc.connections[0].length = 50
    options = OptimizationOptions(starts=2, iterations=900, folding_preset="bare")
    box = PackingBox(-100, -150, 350, 350)
    return doc, build_problem(
        doc, {node.id: 5 for node in doc.nodes if node.kind not in ("source", "output")}, box, options
    )


class OutputDirectionTests(unittest.TestCase):
    def test_ordinary_generation_checks_travel_direction_and_wraps_angles(self):
        for kind in ("output", "fiber_output", "stop"):
            with self.subTest(kind=kind):
                doc = chain("source", kind)
                doc.nodes[0].physical["angle"] = 23.5
                target = doc.nodes[-1]
                target.physical["angle"] = 383.5
                target.rotation = 135  # Drawing rotation is independent.
                compiled = compile_schematic(doc)
                self.assertTrue(compiled.ok, compiled.diagnostics)
                self.assertIn("output_directions=OUTPUT_DIRECTIONS", compiled.source)
                self.assertAlmostEqual(incoming_angle(doc, compiled.geometry, target), 23.5, places=7)
                target.physical["angle"] = -156.5  # A reversed ray is a conflict.
                self.assertFalse(validate_schematic(doc))
                rejected = compile_schematic(doc)
                self.assertFalse(rejected.ok)
                self.assertIn("output direction", rejected.diagnostics[0].message)
                self.assertEqual(rejected.diagnostics[0].node_id, target.id)
                self.assertEqual(rejected.diagnostics[0].connection_id, doc.connections[0].id)

    def test_projection_respects_partial_coordinate_pins(self):
        doc = chain("source", "output")
        doc.nodes[0].physical["x"] = 0
        doc.nodes[-1].physical.update(y=40, angle=45)
        doc.connections[0].length = 50
        problem = build_problem(doc, {}, PackingBox(-100, -100, 300, 300))
        points = [[0.0, 0.0], [50.0, 40.0]]
        for _ in range(300):
            project_constraints(problem, points)
        self.assertFalse(layout_violations(problem, points))
        self.assertEqual(points[0][0], 0)
        self.assertEqual(points[-1][1], 40)
        self.assertAlmostEqual(math.dist(*points), 50, places=6)
        self.assertAlmostEqual(
            math.degrees(math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0])), 45, places=6
        )

    def test_optimizer_changes_free_turn_and_export_rechecks_output_heading(self):
        for kind in ("output", "fiber_output", "stop"):
            with self.subTest(kind=kind):
                doc, problem = output_fixture(kind)
                self.assertFalse(compile_schematic(doc).ok)
                before = deepcopy(doc.to_dict())
                result = optimize_layout(problem)
                self.assertEqual(result.status, "feasible", result.violations)
                self.assertFalse(layout_violations(result.problem, result.positions))
                self.assertEqual(doc.to_dict(), before)
                apply_optimization(doc, problem, result)
                compiled = compile_schematic(doc)
                self.assertTrue(compiled.ok, compiled.diagnostics)
                self.assertAlmostEqual(incoming_angle(doc, compiled.geometry, doc.nodes[-1]), -45, delta=1e-6)
                self.assertNotIn("turn", doc.nodes[1].physical)
                assignments = {
                    item.targets[0].id: ast.literal_eval(item.value)
                    for item in ast.parse(compiled.source).body
                    if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name)
                }
                target = None if kind == "output" else doc.nodes[-1].reference
                self.assertEqual(assignments["OUTPUT_DIRECTIONS"], {("M1", "out", target): -45})
                history = History(doc)
                doc.nodes[-1].physical["angle"] = 60
                history.commit(doc)
                self.assertIn("stale", compile_schematic(doc).diagnostics[0].message)
                restored = history.undo()
                self.assertTrue(compile_schematic(restored).ok)
                with TemporaryDirectory() as directory:
                    path = Path(directory) / "output-direction.json"
                    save_schematic(restored, path)
                    self.assertEqual(compile_schematic(load_schematic(path)).source, compiled.source)

    def test_conflicting_pinned_endpoints_never_offer_apply(self):
        doc, problem = output_fixture()
        doc.nodes[1].physical.update(x=50, y=0)
        doc.nodes[-1].physical.update(x=100, y=50)
        problem = build_problem(
            doc, dict(problem.source_radii), problem.box, OptimizationOptions(starts=1, iterations=80)
        )
        result = optimize_layout(problem)
        self.assertEqual(result.status, "no_feasible_layout")
        self.assertTrue(result.violations)
        self.assertIsNone(result.layout)
        with self.assertRaises(ValueError):
            apply_optimization(doc, problem, result)

    def test_direction_moves_to_the_final_segment_when_a_beam_is_folded(self):
        doc, base = fold_span()
        output = doc.nodes[-1]
        output.physical["angle"] = -math.degrees(math.acos(2 / 3))
        problem = build_problem(doc, {}, base.box, base.options, folding_radius=RADIUS)
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        self.assertEqual(len(result.layout.graph.generated), 1)
        self.assertNotEqual(result.problem.output_directions[0].connection_id, "span")
        apply_optimization(doc, problem, result)
        compiled = compile_schematic(doc)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        self.assertAlmostEqual(
            incoming_angle(doc, compiled.geometry, output), output.physical["angle"], delta=1e-6
        )
        self.assertAlmostEqual(compiled.routed_lengths["span"], 120, delta=1e-6)
        self.assertAlmostEqual(compiled.lengths["span"], 80, delta=1e-6)

    def test_branched_outputs_have_independent_directions_with_folding(self):
        doc, box = folded_splitter()
        for output in doc.nodes[-2:]:
            output.physical["angle"] = 0
        options = OptimizationOptions(starts=1, iterations=1800, folding_preset="bare")
        problem = build_problem(
            doc, {doc.nodes[1].id: 12.7 / math.sqrt(2)}, box, options, folding_radius=RADIUS
        )
        self.assertEqual(len(problem.output_directions), 2)
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        apply_optimization(doc, problem, result)
        for output in doc.nodes[-2:]:
            self.assertAlmostEqual(incoming_angle(doc, result.layout, output), 0, delta=1e-6)
        self.assertEqual(result.layout.turns[doc.nodes[1].id], 90)
        self.assertTrue(compile_schematic(doc).ok)

    def test_runtime_verifies_actual_incoming_ray_including_reversed_rays(self):
        proxy = SimpleNamespace(get_global_direction=lambda: (0, 1, 0))
        beam = SimpleNamespace(
            get_object=lambda: SimpleNamespace(
                BeamSegments=[SimpleNamespace(StartObject=None, EndObject=None, Proxy=proxy)]
            )
        )
        expected = [("S1", "out", None)]
        key = ("S1", "out", None)
        for target in (90, 450, 90 + 1e-7):
            self.assertTrue(check_trace(beam, {}, expected, "S1", output_directions={key: target}))
        for target in (0, -90, 90 + 1e-4):
            with self.assertRaisesRegex(RuntimeError, "Output direction"):
                check_trace(beam, {}, expected, "S1", output_directions={key: target})
        for target in (True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                check_trace(beam, {}, expected, "S1", output_directions={key: target})


@unittest.skipUnless(QT_AVAILABLE, "Qt runtime not installed")
class OutputDirectionEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.editor = None
        self.dialog = None

    def tearDown(self):
        if self.dialog is not None:
            self.dialog.reject()
            self.wait(lambda: self.dialog.worker is None)
        if self.editor is not None:
            self.editor.history.mark_saved()
            self.editor.close()
        self.flush()

    def flush(self):
        self.app.processEvents()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def wait(self, predicate):
        deadline = monotonic() + 15
        while not predicate() and monotonic() < deadline:
            self.app.processEvents()
            QtTest.QTest.qWait(5)
        self.assertTrue(predicate(), "Worker timed out")

    def open_editor(self, doc):
        self.editor = SchematicEditor(doc, bounds_provider=BoundsProvider(lambda spec: BoundingCircleXY(5)))
        self.editor.show()
        self.flush()
        self.editor.scene.symbols[doc.nodes[-1].id].setSelected(True)
        self.flush()
        return self.editor

    def test_output_controls_default_off_edit_and_undo_for_each_terminal(self):
        for kind in ("output", "fiber_output", "stop"):
            doc = chain("source", "mirror", kind)
            editor = self.open_editor(doc)
            check = editor.findChild(QtWidgets.QCheckBox, "outputDirectionConstrained")
            angle = editor.findChild(QtWidgets.QDoubleSpinBox, "outputDirectionDeg")
            self.assertFalse(check.isChecked())
            self.assertFalse(angle.isEnabled())
            self.assertAlmostEqual(angle.value(), 90)
            QtTest.QTest.mouseClick(check, QtCore.Qt.LeftButton, pos=QtCore.QPoint(8, 8))
            self.assertEqual(doc.nodes[-1].physical["angle"], 90)
            angle.setValue(-45)
            self.assertEqual(doc.nodes[-1].physical["angle"], -45)
            self.assertFalse(compile_schematic(doc).ok)
            editor.undo()
            self.assertEqual(editor.document.nodes[-1].physical["angle"], 90)
            editor.undo()
            self.assertNotIn("angle", editor.document.nodes[-1].physical)
            self.assertTrue(compile_schematic(editor.document).ok)
            editor.history.mark_saved()
            editor.close()

    def test_worker_enforces_target_and_applies_without_changing_other_constraints(self):
        doc, problem = output_fixture()
        doc.optimization = {"box": asdict(problem.box), "options": asdict(problem.options)}
        editor = self.open_editor(doc)
        before = deepcopy(doc.to_dict())
        self.dialog = OptimizeLayoutDialog(doc, editor.bounds_provider, editor)
        self.dialog.show()
        self.dialog.start_search()
        self.wait(lambda: self.dialog.worker is None)
        self.assertEqual(self.dialog.solution.status, "feasible")
        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.assertTrue(editor.apply_optimized_result(self.dialog.problem, self.dialog.solution))
        self.assertEqual(doc.to_dict()["nodes"], before["nodes"])
        self.assertEqual(doc.to_dict()["connections"], before["connections"])
        editor.scene.symbols[doc.nodes[-1].id].setSelected(True)
        self.flush()
        self.assertTrue(editor.findChild(QtWidgets.QCheckBox, "outputDirectionConstrained").isChecked())
        self.assertEqual(editor.findChild(QtWidgets.QDoubleSpinBox, "outputDirectionDeg").value(), -45)
        editor.set_endpoint_direction(doc.nodes[-1].id, None)
        self.assertIn("stale", editor.status.text())
        editor.undo()
        self.assertTrue(compile_schematic(editor.document).ok)

    def test_free_output_inspector_uses_the_applied_final_beam_direction(self):
        doc, problem = fold_span()
        editor = self.open_editor(doc)
        result = optimize_layout(problem)
        self.assertTrue(editor.apply_optimized_result(problem, result))
        editor.scene.symbols[doc.nodes[-1].id].setSelected(True)
        self.flush()
        self.assertFalse(editor.findChild(QtWidgets.QCheckBox, "outputDirectionConstrained").isChecked())
        angle = editor.findChild(QtWidgets.QDoubleSpinBox, "outputDirectionDeg")
        self.assertFalse(angle.isEnabled())
        self.assertAlmostEqual(angle.value(), incoming_angle(doc, result.layout, doc.nodes[-1]), delta=1e-6)


if __name__ == "__main__":
    unittest.main()
