"""Half-wave plates and irises automatically align their transmission axes."""

from copy import deepcopy
import unittest

from PyOpticL.ray_math import dot, norm, sub, yaw
from PyOpticL.schematic import compile_schematic
from PyOpticL.schematic.model import OpticalPass
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_layout import trace_scene
from PyOpticL.schematic.scene_solver import solve_scene
from test_schematic import chain
from test_schematic_multipass import double_pass


def transmission_scene(angle=30, offset=45):
    document = chain("source", "hwp", "iris", "output")
    source, plate, iris, output = document.nodes
    select_preset(plate, "bare")
    plate.parameters["fast_axis_angle"] = 27
    source.physical["angle"] = angle
    document.layout = {"poses": {
        node.id: [*yaw((50 * index, 0, 0), angle), angle + (offset if index in (1, 2) else 0)]
        for index, node in enumerate(document.nodes)
    }}
    return document


class TransmissionAlignmentTests(unittest.TestCase):
    def assert_aligned(self, document, layout):
        for node in document.nodes:
            if node.kind not in ("hwp", "iris"):
                continue
            normal = yaw((1, 0, 0), layout.poses[node.id][3])
            for visit in document.optical_passes():
                if visit.component_id != node.id:
                    continue
                state = layout.visits[visit.id]
                self.assertAlmostEqual(abs(dot(normal, state.incoming)), 1, delta=1e-6)
                self.assertLess(norm(sub(state.incoming, state.outputs["out"])), 1e-6)

    def test_centered_but_oblique_parts_block_validation_and_export(self):
        document = transmission_scene()
        trace = trace_scene(document)
        self.assertFalse(trace.ok)
        self.assertTrue(all(abs(r.value) < 1e-6 for r in trace.residuals
                            if r.id.startswith(("center/", "aperture/"))))
        compiled = compile_schematic(document)
        self.assertFalse(compiled.ok)
        self.assertFalse(compiled.source)
        for node in document.nodes[1:3]:
            self.assertTrue(any("optical axis must align" in d.message and d.node_id == node.id
                                for d in compiled.diagnostics))

    def test_all_beam_directions_and_initial_orientations_align_without_sliding(self):
        for angle in range(-180, 180, 45):
            for offset in (-90, 35, 90, 180):
                with self.subTest(angle=angle, offset=offset):
                    document = transmission_scene(angle, offset)
                    if angle < 0:
                        for edge in document.connections:
                            edge.a, edge.b = edge.b, edge.a
                    before = deepcopy(document.to_dict())
                    solution = solve_scene(document, iterations=40)
                    self.assertTrue(solution.ok, solution.diagnostics)
                    self.assertEqual(document.to_dict(), before)
                    self.assert_aligned(document, solution.layout)
                    for node in document.nodes:
                        self.assertEqual(solution.poses[node.id][:3],
                                         document.layout["poses"][node.id][:3])
                    if offset == 180:
                        for node in document.nodes[1:3]:
                            self.assertEqual(solution.poses[node.id][3], angle + 180)
                    document.layout["poses"] = solution.poses
                    self.assertTrue(compile_schematic(document).ok)
                    self.assertEqual(document.nodes[1].parameters["fast_axis_angle"], 27)

    def test_off_center_opt_out_preserves_axis_alignment_requirement(self):
        document = transmission_scene()
        for node in document.nodes[1:3]:
            document.passes.append(OpticalPass(node.id, node.id, centered=False))
        trace = trace_scene(document)
        self.assertFalse(trace.ok)
        for node in document.nodes[1:3]:
            self.assertTrue(any(r.id == f"axis/{node.id}/yaw" and abs(r.value) > 1
                                for r in trace.residuals))

    def test_shared_plate_can_transmit_in_both_directions_with_one_orientation(self):
        for vertical in (False, True):
            document = double_pass(vertical)
            plate = document.node("part-2")
            plate.kind = "hwp"
            solution = solve_scene(document)
            self.assertTrue(solution.ok, solution.diagnostics)
            self.assert_aligned(document, solution.layout)
            self.assertEqual(solution.poses[plate.id][3], 0)
            self.assertTrue(compile_schematic(document).ok)

    def test_shared_plate_rejects_nonparallel_return_in_yaw_and_pitch(self):
        for vertical, axis in ((False, "yaw"), (True, "pitch")):
            document = double_pass(vertical)
            # Put the shared plate after the powered lens on the return path:
            # that return now reaches it at a different angle from the first pass.
            plate, lens = document.node("part-1"), document.node("part-2")
            for node, kind in ((plate, "hwp"), (lens, "lens")):
                node.kind = kind
                node.parameters.clear()
                select_preset(node, "bare")
            lens.parameters["focal_length"] = 100
            trace = trace_scene(document)
            self.assertFalse(trace.ok)
            self.assertTrue(any(r.id == f"axis/lens-return/{axis}" and abs(r.value) > 1
                                for r in trace.residuals))
            self.assertFalse(compile_schematic(document).ok)
