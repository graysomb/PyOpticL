"""Mirror solving must not depend on the initial normal's angular branch."""

from copy import deepcopy
from math import cos, radians, sin
import unittest

from PyOpticL.ray_math import dot, heading, norm, sub, yaw
from PyOpticL.schematic import compile_schematic
from PyOpticL.schematic.physical import wrap_angle
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_solver import solve_scene
from test_schematic import chain


def mirror_scene(incoming=0, turn=90, mirror_yaw=135):
    document = chain("fiber_source", "mirror", "fiber_output")
    source, mirror, receiver = document.nodes
    for node in (source, receiver):
        select_preset(node, "POLARIS-K05T6")
    select_preset(mirror, "bare")
    document.layout = {"poses": {
        source.id: [-70 * cos(radians(incoming)), -70 * sin(radians(incoming)), 0, 0],
        mirror.id: [0, 0, 0, mirror_yaw],
        receiver.id: [70 * cos(radians(incoming + turn)),
                      70 * sin(radians(incoming + turn)), 0, 180],
    }}
    return document


class MirrorOrientationTests(unittest.TestCase):
    def check_solution(self, document, solution, incoming, turn):
        self.assertTrue(solution.ok, solution.diagnostics)
        source, mirror, receiver = document.nodes
        state = solution.layout.visits[mirror.id]
        self.assertAlmostEqual(wrap_angle(heading(state.incoming) - incoming), 0, delta=1e-6)
        self.assertAlmostEqual(wrap_angle(heading(state.outputs["out"]) - incoming - turn),
                               0, delta=1e-6)
        normal = yaw((1, 0, 0), solution.poses[mirror.id][3])
        self.assertLess(dot(state.incoming, normal), 0)
        for node in (mirror, receiver):
            self.assertLess(norm(sub(solution.layout.visits[node.id].entry,
                                     solution.poses[node.id][:3])), 1e-6)
        for node in document.nodes:
            self.assertEqual(solution.poses[node.id][:3], document.layout["poses"][node.id][:3])
        document.layout["poses"] = solution.poses
        compiled = compile_schematic(document)
        self.assertTrue(compiled.ok, compiled.diagnostics)

    def test_all_quadrants_and_turn_signs_solve_without_moving_free_parts(self):
        for incoming in range(-180, 180, 30):
            for turn in (-150, -90, -30, 1, 30, 90, 150):
                with self.subTest(incoming=incoming, turn=turn):
                    document = mirror_scene(incoming, turn)
                    if turn < 0:
                        for edge in document.connections:
                            edge.a, edge.b = edge.b, edge.a
                    before = deepcopy(document.to_dict())
                    solution = solve_scene(document, iterations=40, report=False)
                    self.assertEqual(document.to_dict(), before)
                    self.check_solution(document, solution, incoming, turn)

    def test_exact_back_face_and_grazing_starts_choose_the_coated_face(self):
        for mirror_yaw in (-45, 90, 270, 495):
            with self.subTest(mirror_yaw=mirror_yaw):
                document = mirror_scene(mirror_yaw=mirror_yaw)
                source, mirror, receiver = document.nodes
                for node in document.nodes:
                    pose = document.layout["poses"][node.id]
                    node.physical.update(x=pose[0], y=pose[1])
                source.physical["angle"] = 0
                mirror.physical["turn"] = 90
                receiver.physical["angle"] = 90
                self.check_solution(document, solve_scene(document, iterations=40), 0, 90)

    def test_mirror_drag_across_the_old_face_preserves_requested_position(self):
        document = mirror_scene(0, 90)
        source, mirror, receiver = document.nodes
        # Keep endpoints fixed while moving the mirror beyond their joining line.
        for node in (source, receiver):
            pose = document.layout["poses"][node.id]
            node.physical.update(x=pose[0], y=pose[1])
        solution = solve_scene(document, targets=((mirror.id, 0, -100), (mirror.id, 1, 100)),
                               iterations=40)
        self.assertTrue(solution.ok, solution.diagnostics)
        self.assertEqual(solution.poses[mirror.id][:2], [-100, 100])
        self.assertEqual(solution.poses[source.id][:2], document.layout["poses"][source.id][:2])
        self.assertEqual(solution.poses[receiver.id][:2], document.layout["poses"][receiver.id][:2])
        document.layout["poses"] = solution.poses
        self.assertTrue(compile_schematic(document).ok)

    def test_seeding_cannot_override_an_incompatible_source_direction_or_turn(self):
        for constraint in ("source", "turn", "drag"):
            with self.subTest(constraint=constraint):
                document = mirror_scene(mirror_yaw=-45)
                source, mirror, receiver = document.nodes
                for node in document.nodes:
                    pose = document.layout["poses"][node.id]
                    node.physical.update(x=pose[0], y=pose[1])
                targets = ()
                if constraint == "source":
                    source.physical["angle"] = 30
                elif constraint == "turn":
                    mirror.physical["turn"] = -90
                else:
                    targets = ((mirror.id, 3, -45),)
                before = deepcopy(document.to_dict())
                solution = solve_scene(document, targets=targets, iterations=40)
                self.assertFalse(solution.ok)
                self.assertEqual(document.to_dict(), before)
                for node in document.nodes:
                    self.assertEqual(solution.poses[node.id][:2], document.layout["poses"][node.id][:2])
                if constraint == "source":
                    self.assertEqual(solution.poses[source.id][3], 30)

    def test_changing_constrained_turn_can_cross_to_the_opposite_side(self):
        for turn in (-150, -90, -30, 30, 90, 150):
            with self.subTest(turn=turn):
                document = mirror_scene()
                source, mirror, receiver = document.nodes
                for node in (source, mirror):
                    pose = document.layout["poses"][node.id]
                    node.physical.update(x=pose[0], y=pose[1])
                source.physical["angle"] = 0
                mirror.physical["turn"] = turn
                before = deepcopy(document.to_dict())
                solution = solve_scene(document, iterations=40)
                self.assertTrue(solution.ok, solution.diagnostics)
                self.assertEqual(document.to_dict(), before)
                self.assertAlmostEqual(solution.layout.turns[mirror.id], turn, delta=1e-6)
                self.assertGreater(solution.layout.lengths[document.connections[1].id], 0)
                for node in (source, mirror):
                    self.assertEqual(solution.poses[node.id][:2], document.layout["poses"][node.id][:2])
                document.layout["poses"] = solution.poses
                self.assertTrue(compile_schematic(document).ok)
