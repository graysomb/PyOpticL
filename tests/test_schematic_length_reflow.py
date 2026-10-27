"""Length edits push free following parts without collapsing their beam gaps."""

from copy import deepcopy
import unittest

from PyOpticL.ray_math import yaw
from PyOpticL.schematic import PathLengthConstraint, compile_schematic
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_layout import trace_scene
from PyOpticL.schematic.scene_solver import solve_scene
from test_schematic import chain
from test_schematic_distance_editor import lens_pair
from test_schematic_roof_return import shared_mirror_roof_scene


def folded_chain(angle=0):
    document = chain("source", "lens", "lens", "hwp", "iris", "mirror", "fiber_output")
    for node in document.nodes[1:-1]:
        if node.kind != "iris":
            select_preset(node, "bare")
    select_preset(document.nodes[-1], "POLARIS-K05T6")
    points = ((0, 0, 0), (50, 0, 0), (100, 0, 0), (150, 0, 0),
              (200, 0, 0), (250, 0, 135), (250, 50, -90))
    document.layout = {"poses": {node.id: [*yaw((x, y, 0), angle), rotation + angle]
                                for node, (x, y, rotation) in zip(document.nodes, points)}}
    for node in document.nodes[:2]:
        position = document.layout["poses"][node.id]
        node.physical.update(x=position[0], y=position[1])
    document.nodes[0].physical["angle"] = angle
    document.nodes[-2].physical["turn"] = 90
    return document


class LengthReflowTests(unittest.TestCase):
    def test_large_beam_and_total_lengths_push_following_optics_and_preserve_other_gaps(self):
        for angle in (0, 37, -150):
            for mode in ("beam", "path"):
                with self.subTest(angle=angle, mode=mode):
                    document = folded_chain(angle)
                    old_lengths = trace_scene(document).layout.lengths
                    a, b = document.nodes[1:3]
                    edge = document.connections[1]
                    if mode == "beam":
                        edge.length = 500
                    else:
                        document.path_constraints.append(PathLengthConstraint("span", a.id, b.id, 500))
                    before = deepcopy(document.to_dict())
                    solution = solve_scene(document, iterations=40)
                    self.assertTrue(solution.ok, solution.diagnostics)
                    self.assertEqual(document.to_dict(), before)
                    self.assertAlmostEqual(solution.layout.lengths[edge.id], 500, delta=1e-6)
                    for key, length in old_lengths.items():
                        if key != edge.id:
                            self.assertAlmostEqual(solution.layout.lengths[key], length, delta=1e-6)
                    for node in document.nodes[:2]:
                        self.assertEqual(solution.poses[node.id], document.layout["poses"][node.id])
                    document.layout["poses"] = solution.poses
                    self.assertTrue(compile_schematic(document).ok)

    def test_long_folded_path_keeps_fixed_beams_and_translates_the_returning_arm(self):
        document = folded_chain()
        document.connections[1].length = 50
        a, b = document.nodes[1], document.nodes[-2]
        document.path_constraints.append(PathLengthConstraint("folded", a.id, b.id, 700))
        solution = solve_scene(document, iterations=40)
        self.assertTrue(solution.ok, solution.diagnostics)
        self.assertAlmostEqual(solution.layout.lengths[document.connections[1].id], 50, delta=1e-6)
        self.assertAlmostEqual(solution.layout.lengths[document.connections[-1].id], 50, delta=1e-6)
        self.assertAlmostEqual(solution.poses[b.id][0], 750, delta=1e-6)
        self.assertAlmostEqual(solution.poses[document.nodes[-1].id][0], 750, delta=1e-6)
        document.layout["poses"] = solution.poses
        compiled = compile_schematic(document)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        self.assertAlmostEqual(compiled.path_lengths["folded"], 700, delta=1e-6)

    def test_free_upstream_chain_can_move_when_downstream_positions_are_pinned(self):
        document = lens_pair()
        for node in document.nodes:
            node.physical.pop("x", None)
            node.physical.pop("y", None)
        for node in document.nodes[2:]:
            point = document.layout["poses"][node.id]
            node.physical.update(x=point[0], y=point[1])
        document.connections[1].length = 500
        solution = solve_scene(document, iterations=40)
        self.assertTrue(solution.ok, solution.diagnostics)
        for node in document.nodes[2:]:
            self.assertEqual(solution.poses[node.id], document.layout["poses"][node.id])
        self.assertAlmostEqual(solution.poses[document.nodes[1].id][0], 127.941286 - 500, delta=1e-6)
        self.assertAlmostEqual(solution.layout.lengths[document.connections[0].id], 50, delta=1e-6)

    def test_pinned_boundaries_are_not_moved_to_accept_an_impossible_length(self):
        document = lens_pair()
        for node in document.nodes[2:]:
            point = document.layout["poses"][node.id]
            node.physical.update(x=point[0], y=point[1])
        document.connections[1].length = 500
        solution = solve_scene(document, iterations=40)
        self.assertFalse(solution.ok)
        for node in document.nodes:
            self.assertEqual(solution.poses[node.id][:2], document.layout["poses"][node.id][:2])

    def test_a_free_upstream_part_can_move_between_pinned_boundaries(self):
        document = lens_pair()
        for node, x in zip(document.nodes, (0, 950, 1000, 1100)):
            document.layout["poses"][node.id][0] = x
            node.physical = {"x": x, "y": 0} if node != document.nodes[1] else {}
        document.nodes[0].physical["angle"] = 0
        document.connections[1].length = 500
        solution = solve_scene(document, iterations=40)
        self.assertTrue(solution.ok, solution.diagnostics)
        self.assertAlmostEqual(solution.poses[document.nodes[1].id][0], 500, delta=1e-6)
        for node in (document.nodes[0], *document.nodes[2:]):
            self.assertEqual(solution.poses[node.id], document.layout["poses"][node.id])

    def test_shared_mirror_is_not_translated_separately_for_its_return_visit(self):
        document = shared_mirror_roof_scene()
        source, mirror, roof, receiver = document.nodes
        roof.physical = {}
        document.connections[1].length = 500
        solution = solve_scene(document, iterations=40)
        self.assertTrue(solution.ok, solution.diagnostics)
        self.assertEqual(solution.poses[mirror.id][:2], [50, 0])
        self.assertAlmostEqual(solution.layout.lengths[document.connections[1].id], 500, delta=1e-6)


if __name__ == "__main__":
    unittest.main()
