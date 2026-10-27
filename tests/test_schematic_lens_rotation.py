"""A fixed telescope separation must not lock the beam's direction during a drag."""

from copy import deepcopy
from time import monotonic
import unittest

from PyOpticL.ray_math import heading, yaw
from PyOpticL.schematic import PathLengthConstraint, compile_schematic
from PyOpticL.schematic.physical import wrap_angle
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_layout import trace_scene
from PyOpticL.schematic.scene_solver import solve_scene
from test_schematic import chain
from test_schematic_editor import QT_AVAILABLE

if QT_AVAILABLE:
    import test_schematic_physical_editor as physical_tests
    from test_schematic_editor import QtTest


def telescope(mode="beam", angle=0):
    document = chain("fiber_source", "mirror", "lens", "lens", "mirror", "fiber_output")
    for node in document.nodes:
        select_preset(node, "POLARIS-K05T6" if node.kind.startswith("fiber_") else "bare")
    points = ((0, 0, 0), (50, 0, 135), (50, 50, 90), (50, 150, 90),
              (50, 200, -45), (100, 200, 180))
    document.layout = {"poses": {node.id: [*yaw((x, y, 0), angle), rotation + angle]
                                for node, (x, y, rotation) in zip(document.nodes, points)}}
    document.nodes[0].physical.update(x=0, y=0, angle=angle)
    if mode == "beam":
        document.connections[2].length = 100
    else:
        a, b = document.nodes[2:4]
        document.path_constraints.append(PathLengthConstraint("lenses", a.id, b.id, 100))
    return document


class LensRotationTests(unittest.TestCase):
    def test_large_drag_rotates_beam_while_preserving_lens_separation_and_source_pins(self):
        for mode, angle in (("beam", 0), ("path", 0), ("beam", 37)):
            with self.subTest(mode=mode, angle=angle):
                document = telescope(mode, angle)
                self.assertTrue(trace_scene(document).ok)
                before = deepcopy(document.to_dict())
                lens = document.nodes[3]
                x, y, _ = yaw((150, 50, 0), angle)
                solution = solve_scene(document, targets=((lens.id, 0, x), (lens.id, 1, y)), iterations=40)
                self.assertTrue(solution.ok, solution.diagnostics)
                self.assertEqual(document.to_dict(), before)
                self.assertAlmostEqual(solution.poses[lens.id][0], x, delta=1e-6)
                self.assertAlmostEqual(solution.poses[lens.id][1], y, delta=1e-6)
                self.assertAlmostEqual(solution.layout.lengths[document.connections[2].id], 100, delta=1e-6)
                for index in (1, 3, 4):
                    self.assertAlmostEqual(solution.layout.lengths[document.connections[index].id],
                                           50, delta=1e-6)
                beam_angle = heading(solution.layout.visits[lens.id].incoming)
                self.assertGreater(abs(wrap_angle(beam_angle - angle - 90)), 30)
                source = document.nodes[0]
                self.assertEqual(solution.poses[source.id][:2], [0, 0])
                self.assertEqual(solution.poses[source.id][3], angle)
                document.layout["poses"] = solution.poses
                self.assertTrue(compile_schematic(document).ok)

    def test_impossible_drag_preserves_direction_and_position_pins(self):
        document = telescope()
        lens = document.nodes[3]
        lens.physical.update(x=50, y=150)
        solution = solve_scene(document, targets=((lens.id, 0, 150), (lens.id, 1, 50)), iterations=40)
        self.assertFalse(solution.ok)
        self.assertEqual(solution.poses[lens.id][:2], [50, 150])
        self.assertEqual(document.connections[2].length, 100)

    def test_drag_can_be_cancelled_without_mutating_the_document(self):
        document = telescope()
        before = deepcopy(document.to_dict())
        lens = document.nodes[3]
        solution = solve_scene(document, targets=((lens.id, 0, 150), (lens.id, 1, 50)),
                               iterations=40, cancelled=lambda: True)
        self.assertEqual(solution.status, "cancelled")
        self.assertEqual(document.to_dict(), before)


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable")
class LensDragEditorTests(unittest.TestCase):
    if QT_AVAILABLE:
        setUpClass = classmethod(physical_tests.PhysicalEditorTests.setUpClass.__func__)
        setUp = physical_tests.PhysicalEditorTests.setUp
        tearDown = physical_tests.PhysicalEditorTests.tearDown
        open = physical_tests.PhysicalEditorTests.open

    def settle(self):
        deadline = monotonic() + 30
        while self.editor.workers and monotonic() < deadline:
            self.app.processEvents()
            QtTest.QTest.qWait(10)
        self.app.processEvents()
        self.assertFalse(self.editor.workers, "Drag solve timed out")

    def test_live_drag_uses_last_preview_and_commits_rotation_as_one_undoable_edit(self):
        e = self.open(telescope())
        before = deepcopy(e.document.to_dict())
        index = e.history.index
        lens = e.document.nodes[3]
        e.begin_drag()
        e.start_solve(((lens.id, 0, 60), (lens.id, 1, 140)))
        self.settle()
        self.assertIsNotNone(e.preview_poses)
        self.assertEqual(e.document.to_dict(), before)
        preview = deepcopy(e.preview_poses)
        e.start_solve(((lens.id, 0, 70), (lens.id, 1, 130)))
        worker = next(iter(e.workers))
        self.assertEqual(worker.document.layout["poses"], preview)
        self.settle()
        e.start_solve(((lens.id, 0, 150), (lens.id, 1, 50)), True)
        self.settle()
        self.assertEqual(e.history.index, index + 1)
        result = compile_schematic(e.document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertAlmostEqual(result.lengths[e.document.connections[2].id], 100, delta=1e-6)
        self.assertAlmostEqual(e.document.layout["poses"][lens.id][0], 150, delta=1e-6)
        self.assertAlmostEqual(e.document.layout["poses"][lens.id][1], 50, delta=1e-6)
        after = deepcopy(e.document.to_dict())
        e.undo()
        self.settle()
        self.assertEqual(e.document.to_dict(), before)
        e.redo()
        self.settle()
        self.assertEqual(e.document.to_dict(), after)


if __name__ == "__main__":
    unittest.main()
