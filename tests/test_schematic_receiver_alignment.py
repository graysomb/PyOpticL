"""Fiber receiving axes follow the ray independently of heading constraints."""

from copy import deepcopy
import unittest

from PyOpticL.ray_math import heading, norm, sub
from PyOpticL.schematic import compile_schematic
from PyOpticL.schematic.model import OpticalPass
from PyOpticL.schematic.physical import wrap_angle
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_layout import trace_scene
from PyOpticL.schematic.scene_solver import solve_scene
from test_schematic import chain


def fiber_pair(preset="paf2"):
    document = chain("fiber_source", "fiber_output")
    source, receiver = document.nodes
    for node in document.nodes:
        select_preset(node, preset)
    document.layout = {"poses": {
        source.id: [0, 0, 0, 180 if preset == "paf2" else 0],
        receiver.id: [50, 0, 0, 135],
    }}
    return document


class ReceiverAlignmentTests(unittest.TestCase):
    def assert_aligned(self, solution, receiver):
        self.assertTrue(solution.ok, solution.diagnostics)
        state = solution.layout.visits[receiver.id]
        pose = solution.poses[receiver.id]
        self.assertAlmostEqual(wrap_angle(heading(state.incoming) - pose[3] - 180),
                               0, delta=1e-6)
        self.assertLess(norm(sub(state.entry, pose[:3])), 1e-6)

    def test_centered_but_oblique_receiver_blocks_validation_and_export(self):
        for preset in ("paf2", "POLARIS-K05T6", "KA05TA"):
            with self.subTest(preset=preset):
                document = fiber_pair(preset)
                receiver = document.nodes[1]
                trace = trace_scene(document)
                self.assertFalse(trace.ok)
                self.assertTrue(all(abs(r.value) < 1e-6 for r in trace.residuals
                                    if r.id.startswith("center/")))
                compiled = compile_schematic(document)
                self.assertFalse(compiled.ok)
                self.assertFalse(compiled.source)
                self.assertTrue(any("fiber receiver must face" in d.message
                                    and d.node_id == receiver.id for d in compiled.diagnostics))

    def test_free_source_and_receiver_follow_rotations_in_both_directions(self):
        for preset in ("paf2", "POLARIS-K05T6", "KA05TA"):
            for rotated in (0, 1):
                with self.subTest(preset=preset, rotated=rotated):
                    document = fiber_pair(preset)
                    source, receiver = document.nodes
                    document.layout["poses"][receiver.id][3] = 180
                    before = deepcopy(document.to_dict())
                    node = document.nodes[rotated]
                    target = document.layout["poses"][node.id][3] + 30
                    solution = solve_scene(document, targets=((node.id, 3, target),))
                    self.assert_aligned(solution, receiver)
                    self.assertAlmostEqual(solution.poses[node.id][3], target, delta=1e-6)
                    self.assertEqual(document.to_dict(), before)
                    document.layout["poses"] = solution.poses
                    self.assertTrue(compile_schematic(document).ok)
                    self.assertNotIn("angle", source.physical)
                    self.assertNotIn("angle", receiver.physical)

    def test_misaligned_saved_receiver_is_solved_even_with_fixed_positions(self):
        document = fiber_pair()
        source, receiver = document.nodes
        source.physical.update(x=0, y=0)
        receiver.physical.update(x=50, y=0)
        solution = solve_scene(document)
        self.assert_aligned(solution, receiver)
        self.assertAlmostEqual(solution.poses[receiver.id][3], 180, delta=1e-6)
        self.assertEqual(solution.poses[source.id][:2], [0, 0])
        self.assertEqual(solution.poses[receiver.id][:2], [50, 0])

    def test_fixed_arriving_heading_also_turns_receiver_body(self):
        document = fiber_pair("POLARIS-K05T6")
        receiver = document.nodes[1]
        receiver.physical["angle"] = 60
        solution = solve_scene(document)
        self.assert_aligned(solution, receiver)
        self.assertAlmostEqual(heading(solution.layout.visits[receiver.id].incoming), 60, delta=1e-6)
        self.assertAlmostEqual(wrap_angle(solution.poses[receiver.id][3] - 240), 0, delta=1e-6)

    def test_off_center_opt_out_does_not_disable_fiber_axis_alignment(self):
        document = fiber_pair()
        receiver = document.nodes[1]
        document.passes.append(OpticalPass(receiver.id, receiver.id, "receive", centered=False))
        self.assertFalse(trace_scene(document).ok)
        self.assertTrue(any(r.id == f"fiber_axis/{receiver.id}" and abs(r.value) > 1
                            for r in trace_scene(document).residuals))
