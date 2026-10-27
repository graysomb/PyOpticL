"""Unresolved drafts stay editable without approving invalid optical geometry."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyOpticL.schematic import compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.scene_layout import poses_for
from test_schematic import chain
from test_schematic_editor import QT_AVAILABLE
import test_schematic_physical_editor as editor_tests

if QT_AVAILABLE:
    from PyOpticL.schematic.qt import QtCore, QtWidgets
    from test_schematic_editor import QtTest


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable")
class DraftMovementTests(unittest.TestCase):
    setUpClass = classmethod(editor_tests.PhysicalEditorTests.setUpClass.__func__)
    setUp = editor_tests.PhysicalEditorTests.setUp
    tearDown = editor_tests.PhysicalEditorTests.tearDown
    open = editor_tests.PhysicalEditorTests.open
    settle = editor_tests.PhysicalEditorTests.settle
    select = editor_tests.PhysicalEditorTests.select

    def disconnect_output(self):
        document = chain("source", "lens", "output")
        document.nodes[1].preset = "bare"
        e = self.open(document)
        edge = document.connections.pop()
        e.commit()
        self.settle()
        self.assertFalse(e.scene.topology.ok)
        return e, edge

    def test_missing_output_connection_allows_live_drag_save_and_undo_redo(self):
        e, edge = self.disconnect_output()
        lens = e.document.nodes[1]
        self.select(lens.id)
        before = deepcopy(e.document.to_dict())
        index = e.history.index
        e.begin_drag()
        e.scene.symbols[lens.id].setPos(QtCore.QPointF(70, -20))
        self.assertEqual(e.display_poses()[lens.id][:2], [70, 20])
        self.assertEqual(e.document.to_dict(), before)  # Preview is not yet saved.
        e.finish_drag()
        self.settle()
        self.assertEqual(e.document.layout["poses"][lens.id][:2], [70, 20])
        self.assertEqual(e.history.index, index + 1)
        self.assertFalse(compile_schematic(e.document).ok)
        self.assertTrue(any("Error:" in e.messages.item(i).text() for i in range(e.messages.count())))
        with TemporaryDirectory() as folder:
            path = Path(folder) / "incomplete.json"
            save_schematic(e.document, path)
            self.assertEqual(load_schematic(path).to_dict(), e.document.to_dict())
        after = deepcopy(e.document.to_dict())
        e.undo()
        self.settle()
        self.assertEqual(e.document.to_dict(), before)
        e.redo()
        self.settle()
        self.assertEqual(e.document.to_dict(), after)
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName") as picker:
            self.assertFalse(e.generate_cad())
        picker.assert_not_called()

    def test_complete_but_invalid_layout_keeps_failed_move_then_can_be_repaired(self):
        document = chain("source", "lens", "output")
        document.nodes[1].preset = "bare"
        source, lens, output = document.nodes
        source.physical.update(x=0, y=0, angle=0)
        e = self.open(document)
        document.layout["poses"][lens.id][1] = 20
        e.commit(solve=False)
        self.assertFalse(e.display_trace.ok)
        index = e.history.index
        e.begin_drag()
        e.start_solve(((lens.id, 0, 60), (lens.id, 1, 20)), True)
        self.settle()
        self.assertEqual(document.layout["poses"][lens.id][:2], [60, 20])
        self.assertEqual(e.history.index, index + 1)
        self.assertFalse(compile_schematic(document).ok)
        self.assertEqual(source.physical, {"x": 0, "y": 0, "angle": 0})
        # Invalid ray intersections must not move the wire ports away from bodies.
        for item in e.scene.symbols.values():
            for port in item.ports.values():
                self.assertEqual(port.pos(), QtCore.QPointF())
        beam = e.scene.connections[document.connections[0].id]
        end = beam.path().elementAt(1)
        self.assertAlmostEqual(end.x, 60)
        self.assertAlmostEqual(end.y, -20)
        self.assertEqual(beam.pen().style(), QtCore.Qt.DashLine)
        e.begin_drag()
        e.start_solve(((lens.id, 0, 60), (lens.id, 1, 0)), True)
        self.settle()
        self.assertAlmostEqual(document.layout["poses"][lens.id][0], 60, delta=1e-6)
        self.assertAlmostEqual(document.layout["poses"][lens.id][1], 0, delta=1e-6)
        self.assertTrue(compile_schematic(document).ok)
        self.assertEqual(e.history.index, index + 2)

    def test_draft_moves_respect_pins_in_xy_and_xz(self):
        document = chain("source")
        source = document.nodes[0]
        source.physical.update(x=5, angle=30)
        document.layout = {"poses": {source.id: [5, 10, 0, 30]}}
        e = self.open(document)
        e.begin_drag()
        e.start_solve(((source.id, 0, 20), (source.id, 1, 25), (source.id, 3, 60)), True)
        self.settle()
        self.assertEqual(document.layout["poses"][source.id], [5, 25, 0, 30])
        e.change_projection("XZ")
        e.begin_drag()
        e.start_solve(((source.id, 0, 20), (source.id, 2, 15)), True)
        self.settle()
        self.assertEqual(document.layout["poses"][source.id], [5, 25, 15, 30])
        self.assertEqual(source.physical, {"x": 5, "angle": 30})

    def test_group_draft_drag_is_one_edit_and_rotation_also_works(self):
        e, edge = self.disconnect_output()
        lens, output = e.document.nodes[1:]
        for node in (lens, output):
            e.scene.symbols[node.id].setSelected(True)
        before = deepcopy(poses_for(e.document))
        index = e.history.index
        e.begin_drag()
        for node in (lens, output):
            item = e.scene.symbols[node.id]
            item.setPos(item.pos() + QtCore.QPointF(10, -15))
        e.finish_drag()
        self.settle()
        for node in (lens, output):
            self.assertEqual(e.document.layout["poses"][node.id][:2],
                             [before[node.id][0] + 10, before[node.id][1] + 15])
        self.assertEqual(e.history.index, index + 1)
        self.select(lens.id)
        old_yaw = e.document.layout["poses"][lens.id][3]
        e.rotate()
        self.settle()
        self.assertEqual(e.document.layout["poses"][lens.id][3], old_yaw + e.document.settings["angle"])
        self.assertFalse(compile_schematic(e.document).ok)

    def test_reconnecting_after_draft_moves_resumes_the_physical_solver(self):
        e, edge = self.disconnect_output()
        lens, output = e.document.nodes[1:]
        e.begin_drag()
        e.start_solve(((lens.id, 0, 60), (lens.id, 1, 20)), True)
        self.settle()
        e.add_symbol("hwp", (80, -20))
        plate = e.document.nodes[-1]
        from PyOpticL.schematic import Endpoint
        self.assertTrue(e.connect_endpoints(edge.a, Endpoint(plate.id, "A")))
        self.assertTrue(e.connect_endpoints(Endpoint(plate.id, "B"), edge.b))
        e.commit()
        self.settle()
        self.assertTrue(compile_schematic(e.document).ok)
        self.assertFalse(e.draft_drag)

    def test_actual_mouse_drag_keeps_a_disconnected_part_where_it_is_dropped(self):
        e, edge = self.disconnect_output()
        lens = e.document.nodes[1]
        self.select(lens.id)
        e.fit()
        self.app.processEvents()
        item = e.scene.symbols[lens.id]
        before = deepcopy(e.document.layout["poses"][lens.id])
        index = e.history.index
        # Pick the lens body clear of its ports at the optical center.
        start = e.view.mapFromScene(item.scenePos() + QtCore.QPointF(0, 4))
        end = start + QtCore.QPoint(30, 20)
        viewport = e.view.viewport()
        QtTest.QTest.mousePress(viewport, QtCore.Qt.LeftButton, pos=start)
        QtTest.QTest.mouseMove(viewport, end)
        QtTest.QTest.mouseRelease(viewport, QtCore.Qt.LeftButton, pos=end)
        self.settle()
        self.assertNotEqual(e.document.layout["poses"][lens.id][:2], before[:2])
        self.assertEqual(e.history.index, index + 1)
        pose = e.document.layout["poses"][lens.id]
        self.assertEqual(e.scene.symbols[lens.id].pos(), QtCore.QPointF(pose[0], -pose[1]))
        self.assertFalse(compile_schematic(e.document).ok)

    def test_editing_an_optimized_draft_preserves_graph_without_certifying_it(self):
        from PyOpticL.schematic.optimization import (
            OptimizationOptions, PackingBox, apply_optimization, build_problem, optimize_layout,
        )

        document = chain("source", "lens", "output")
        document.nodes[1].preset = "bare"
        e = self.open(document)
        problem = build_problem(document, {document.nodes[1].id: 5},
                                PackingBox(-50, -50, 250, 150),
                                OptimizationOptions(starts=1, iterations=2, projection_passes=2))
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        apply_optimization(document, problem, result)
        document.connections.pop()
        e.commit()
        self.settle()
        saved = document.optimized_layout
        before = deepcopy(saved)
        lens = document.nodes[1]
        e.begin_drag()
        e.start_solve(((lens.id, 0, 70), (lens.id, 1, 25)), True)
        self.settle()
        self.assertEqual(document.layout["poses"][lens.id][:2], [70, 25])
        self.assertEqual(saved["geometry"]["poses"][lens.id][:2], [70, 25])
        self.assertEqual(saved["graph"], before["graph"])
        self.assertEqual(saved["manual_poses"], before["manual_poses"])
        self.assertEqual(saved["fingerprint"], before["fingerprint"])
        self.assertFalse(compile_schematic(document).ok)

