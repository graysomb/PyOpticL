"""Fixed grating incidence moves free downstream optics onto the diffracted ray."""

from copy import deepcopy
import unittest

from PyOpticL.ray_math import add, heading, mul, norm, sub, yaw
from PyOpticL.schematic import Endpoint, compile_schematic
from PyOpticL.schematic.physical import wrap_angle
from PyOpticL.schematic.registry import grating_input_heading, grating_turn, select_preset
from PyOpticL.schematic.scene_layout import initialize_layout, trace_scene
from PyOpticL.schematic.scene_solver import solve_scene
from PyOpticL.schematic.topology import resolve_topology
from test_schematic import chain


def grating_chain(angle=90, reverse=False, wavelength=1550, transmission=()):
    document = chain("fiber_source", "mirror", "grating", *transmission, "mirror", "fiber_output")
    source, first, grating = document.nodes[:3]
    second, receiver = document.nodes[-2:]
    for node in (source, receiver):
        select_preset(node, "POLARIS-K05T6")
    for node in document.nodes[1:-1]:
        if node.kind != "iris":
            select_preset(node, "bare")
    source.parameters["wavelength"] = wavelength
    poses = [(0, 0, 0, 0), (50, 0, 0, 135), (50, 50, 0, 0)]
    poses.extend((100 + 50 * index, 50, 0, 0) for index in range(len(transmission)))
    poses.extend(((100 + 50 * len(transmission), 50, 0, 135),
                  (100 + 50 * len(transmission), 100, 0, -90)))
    document.layout = {"poses": {
        node.id: [*yaw(pose[:3], angle - 90), pose[3] + angle - 90]
        for node, pose in zip(document.nodes, poses)
    }}
    for node in (source, first, grating):
        pose = document.layout["poses"][node.id]
        node.physical.update(x=pose[0], y=pose[1])
    source.physical["angle"] = angle - 90
    first.physical["turn"] = 90
    if reverse:
        document.connections[1].b = Endpoint(grating.id, "B")
        document.connections[2].a = Endpoint(grating.id, "A")
    return document


class GratingConstraintTests(unittest.TestCase):
    def assert_grating(self, document, solution):
        self.assertTrue(solution.ok, solution.diagnostics)
        source, first, grating = document.nodes[:3]
        second, receiver = document.nodes[-2:]
        topology = resolve_topology(document)
        state = solution.layout.visits[grating.id]
        self.assertAlmostEqual(wrap_angle(heading(state.incoming) - solution.poses[grating.id][3]
                                         - grating_input_heading(document, grating, topology)),
                               0, delta=1e-6)
        self.assertAlmostEqual(wrap_angle(heading(state.outputs["out"]) - heading(state.incoming)
                                         - grating_turn(document, grating, topology)),
                               0, delta=1e-6)
        for node in (source, first, grating):
            self.assertEqual(solution.poses[node.id][:2], document.layout["poses"][node.id][:2])
        for node in document.nodes[3:]:
            self.assertLess(norm(sub(solution.layout.visits[node.id].entry, solution.poses[node.id][:3])), 1e-6)
        self.assertEqual(second.physical, {})
        self.assertEqual(receiver.physical, {})
        self.assertGreater(solution.layout.lengths[document.connections[2].id], 1)
        document.layout["poses"] = solution.poses
        compiled = compile_schematic(document)
        self.assertTrue(compiled.ok, compiled.diagnostics)

    def test_free_waveplates_irises_and_mirrors_reflow_together_after_a_grating(self):
        for transmission in (("hwp", "iris"), ("lens",)):
            with self.subTest(transmission=transmission):
                document = grating_chain(transmission=transmission)
                self.assert_grating(document, solve_scene(document, iterations=40))

    def test_free_downstream_mirror_and_receiver_follow_fixed_grating_in_all_quadrants(self):
        for angle in (-150, -45, 0, 90, 170):
            for reverse in (False, True):
                for wavelength in (635, 1550):
                    with self.subTest(angle=angle, reverse=reverse, wavelength=wavelength):
                        document = grating_chain(angle, reverse, wavelength)
                        if angle < 0:
                            for edge in document.connections:
                                edge.a, edge.b = edge.b, edge.a
                        before = deepcopy(document.to_dict())
                        solution = solve_scene(document, iterations=40, report=False)
                        self.assertEqual(document.to_dict(), before)
                        self.assert_grating(document, solution)

    def test_changing_incidence_and_order_moves_free_optics_and_preserves_fixed_length(self):
        document = grating_chain()
        grating = document.nodes[2]
        document.connections[2].length = 80
        for incidence, order in ((40, 1), (60, 1), (49.9, 0), (-49.9, -1)):
            with self.subTest(incidence=incidence, order=order):
                grating.parameters.update(incidence_angle=incidence, order=order)
                solution = solve_scene(document, iterations=40)
                self.assert_grating(document, solution)
                self.assertAlmostEqual(solution.layout.lengths[document.connections[2].id], 80, delta=1e-6)

    def test_an_oblique_input_cannot_be_accepted_by_rotating_the_grating_off_its_nominal_angle(self):
        document = chain("source", "grating", "output")
        grating = document.nodes[1]
        select_preset(grating, "bare")
        initialize_layout(document)
        document.layout["poses"][grating.id][3] += 2
        trace = trace_scene(document)
        state = trace.layout.visits[grating.id]
        document.layout["poses"][document.nodes[2].id][:3] = add(state.exit, mul(state.outputs["out"], 50))
        trace = trace_scene(document)
        bad = [r for r in trace.residuals if abs(r.value) > 1e-6]
        self.assertEqual([r.id for r in bad], [f"incidence/{grating.id}/yaw"])
        compiled = compile_schematic(document)
        self.assertFalse(compiled.ok)
        self.assertFalse(compiled.source)
        self.assertTrue(any("constrained grating incidence" in d.message for d in compiled.diagnostics))

    def test_downstream_position_pins_are_not_overridden_to_force_a_solution(self):
        document = grating_chain()
        second = document.nodes[3]
        second.physical.update(x=100, y=50)
        before = deepcopy(document.to_dict())
        solution = solve_scene(document, iterations=40)
        self.assertFalse(solution.ok)
        self.assertEqual(solution.poses[second.id][:2], [100, 50])
        self.assertEqual(document.to_dict(), before)

    def test_nonpropagating_nominal_order_reports_an_error_instead_of_rotating_to_a_different_incidence(self):
        document = grating_chain()
        grating = document.nodes[2]
        grating.parameters["incidence_angle"] = 0
        solution = solve_scene(document, iterations=40)
        self.assertFalse(solution.ok)
        self.assertTrue(any("nonpropagating" in d.message for d in solution.diagnostics))
        self.assertFalse(compile_schematic(document).ok)
