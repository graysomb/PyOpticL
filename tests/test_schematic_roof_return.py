"""A displaced roof return reuses one mirror at two distinct finite hits."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyOpticL.ray_math import add, norm, sub, yaw, dot, mul, heading
from PyOpticL.schematic.physical import wrap_angle
from PyOpticL.schematic import Connection, Endpoint, PathLengthConstraint, Schematic, compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_layout import trace_scene
from PyOpticL.schematic.scene_solver import solve_scene


def shared_mirror_roof_scene(vertical=False, reverse=False, separation=4, angle=0, transmission=None):
    document = Schematic("Shared mirror roof return")
    source, mirror, roof, receiver = [document.add_node(kind) for kind in
                                     ("fiber_source", "mirror", "roof", "fiber_output")]
    for node in (source, receiver):
        select_preset(node, "POLARIS-K05T6")
    select_preset(mirror, "bare")
    select_preset(roof, "bare_vertical" if vertical else "bare_horizontal")
    roof.parameters["beam_separation"] = separation
    returning = document.add_pass(mirror.id)
    returning.id = "mirror-return"
    route = ((source.id, "beam", mirror.id, "A"),
             (mirror.id, "B", roof.id, "B" if reverse else "A"),
             (roof.id, "A" if reverse else "B", returning.id, "A"),
             (returning.id, "B", receiver.id, "beam"))
    optic = None
    if transmission:
        optic = document.add_node(transmission)
        if transmission != "iris":
            select_preset(optic, "bare")
        else:
            optic.parameters["pinhole_diameter"] = 10
        if transmission == "lens":
            # Keep the focused return clear of the source's incoming beam.
            optic.parameters["focal_length"] = 500
        back = document.add_pass(optic.id)
        back.id = "optic-return"
        route = (route[0], (mirror.id, "B", optic.id, "A"),
                 (optic.id, "B", roof.id, "B" if reverse else "A"),
                 (roof.id, "A" if reverse else "B", back.id, "B"),
                 (back.id, "A", returning.id, "A"), route[-1])
    for index, (a, ap, b, bp) in enumerate(route):
        first, last = document.optical_pass(a), document.optical_pass(b)
        document.connections.append(Connection(
            f"beam-{index}",
            Endpoint(first.component_id, ap, "" if first.id == first.component_id else first.id),
            Endpoint(last.component_id, bp, "" if last.id == last.component_id else last.id),
        ))
    document.layout = {"poses": {
        source.id: [0, 0, 0, 0], mirror.id: [50, 0, 0, 10],
        roof.id: [50, 70, 0, 0], receiver.id: [0, -5, 0, 120],
    }}
    if optic:
        document.layout["poses"][optic.id] = [50, 35, 0, 10]
    for pose in document.layout["poses"].values():
        pose[:3] = yaw(pose[:3], angle)
        pose[3] += angle
    for node in (source, mirror, roof):
        pose = document.layout["poses"][node.id]
        node.physical.update(x=pose[0], y=pose[1])
    source.physical["angle"] = angle
    mirror.physical["turn"] = 90
    return document


class RoofReturnTests(unittest.TestCase):
    def test_return_through_shared_transmissive_optics_keeps_one_pose_per_part(self):
        for kind in ("hwp", "qwp", "lens", "iris"):
            for vertical in (False, True):
                with self.subTest(kind=kind, vertical=vertical):
                    document = shared_mirror_roof_scene(vertical=vertical, transmission=kind)
                    solution = solve_scene(document, iterations=40)
                    self.assertTrue(solution.ok, solution.diagnostics)
                    optic = document.nodes[-1]
                    first = solution.layout.visits[optic.id]
                    returning = solution.layout.visits["optic-return"]
                    self.assertGreater(norm(sub(first.entry, returning.entry)), 3)
                    document.layout["poses"] = solution.poses
                    self.assertTrue(compile_schematic(document).ok)

    def test_shared_mirror_and_roof_seed_work_away_from_the_coordinate_axes(self):
        for angle in (-150, 37, 170):
            with self.subTest(angle=angle):
                document = shared_mirror_roof_scene(angle=angle)
                solution = solve_scene(document, iterations=40)
                self.assertTrue(solution.ok, solution.diagnostics)
                document.layout["poses"] = solution.poses
                self.assertTrue(compile_schematic(document).ok)

    def test_oversized_roof_return_cannot_shrink_its_offset_to_fit_a_small_mirror(self):
        document = shared_mirror_roof_scene(separation=12.7)
        for node in document.nodes:
            node.physical = {}
        solution = solve_scene(document, iterations=40)
        self.assertFalse(solution.ok)
        self.assertEqual(document.nodes[2].parameters["beam_separation"], 12.7)
        self.assertTrue(any(d.severity == "error" and
                            ("beam separation" in d.message or "clear aperture" in d.message)
                            for d in solution.diagnostics))

    def test_dragging_roof_preserves_offset_and_adjusts_free_yaw(self):
        for vertical in (False, True):
            for reverse in (False, True):
                with self.subTest(vertical=vertical, reverse=reverse):
                    document = shared_mirror_roof_scene(vertical=vertical, reverse=reverse)
                    mirror, roof = document.nodes[1:3]
                    mirror.physical.pop("turn")
                    roof.physical = {}
                    initial = solve_scene(document)
                    self.assertTrue(initial.ok, initial.diagnostics)
                    document.layout["poses"] = initial.poses
                    solution = solve_scene(document, targets=((roof.id, 0, 40), (roof.id, 1, 90)))
                    self.assertTrue(solution.ok, solution.diagnostics)
                    self.assertAlmostEqual(solution.poses[roof.id][0], 40, delta=1e-6)
                    self.assertAlmostEqual(solution.poses[roof.id][1], 90, delta=1e-6)
                    state = solution.layout.visits[roof.id]
                    delta = sub(state.exit, state.entry)
                    offset = norm(sub(delta, mul(state.incoming, dot(delta, state.incoming))))
                    self.assertAlmostEqual(offset, 4, delta=1e-6)
                    self.assertGreater(abs(wrap_angle(solution.poses[roof.id][3] - initial.poses[roof.id][3])), 1)
                    self.assertAlmostEqual(wrap_angle(solution.poses[roof.id][3] - heading(state.incoming)), 0, delta=1e-6)
                    self.assertNotIn("angle", roof.physical)
                    for node in document.nodes[:2]:
                        self.assertEqual(solution.poses[node.id][:2], document.layout["poses"][node.id][:2])
                    document.layout["poses"] = solution.poses
                    self.assertTrue(compile_schematic(document).ok)

    def test_tilted_roof_with_wrong_actual_offset_is_not_a_valid_layout(self):
        document = shared_mirror_roof_scene()
        mirror, roof = document.nodes[1:3]
        document.layout["poses"][mirror.id][3] = 135
        document.layout["poses"][roof.id][3] = 85
        trace = trace_scene(document)
        rows = [row for row in trace.residuals if row.id == f"roof_offset/{roof.id}"]
        self.assertEqual(len(rows), 1)
        self.assertGreater(abs(rows[0].value), 1)
        self.assertFalse(trace.ok)
        self.assertFalse(compile_schematic(document).ok)

    def test_uncentered_roof_slides_without_tilting_when_other_parts_are_pinned(self):
        for vertical, reverse, angle in ((False, False, 0), (False, True, 37),
                                         (True, False, -150), (True, True, 0)):
            with self.subTest(vertical=vertical, reverse=reverse, angle=angle):
                document = shared_mirror_roof_scene(vertical=vertical, reverse=reverse, angle=angle)
                initial = solve_scene(document)
                self.assertTrue(initial.ok, initial.diagnostics)
                document.layout["poses"] = initial.poses
                roof = document.nodes[2]
                roof.physical.clear()
                for node in (roof, document.nodes[1]):
                    visit = document.optical_pass(node.id)
                    visit.centered = False
                    document.passes.append(visit)
                for node in document.nodes:
                    if node.id != roof.id:
                        node.physical.update(zip(("x", "y"), initial.poses[node.id][:2]))
                state = initial.layout.visits[roof.id]
                for distance in (20, -15):
                    target = [initial.poses[roof.id][i] + distance * state.incoming[i] for i in range(3)]
                    solved = solve_scene(document, targets=((roof.id, 0, target[0]), (roof.id, 1, target[1])))
                    self.assertTrue(solved.ok, solved.diagnostics)
                    self.assertAlmostEqual(wrap_angle(solved.poses[roof.id][3] - initial.poses[roof.id][3]),
                                           0, delta=1e-6)
                    returning = solved.layout.visits[roof.id]
                    self.assertLess(norm(sub(returning.exit, add(returning.entry, sub(state.exit, state.entry)))),
                                    1e-6)
                    for node in document.nodes:
                        if node.id != roof.id:
                            self.assertEqual(solved.poses[node.id][:2], initial.poses[node.id][:2])
                    document.layout["poses"] = solved.poses
                    self.assertTrue(compile_schematic(document).ok)

    def test_uncentered_roof_still_requires_normal_entrance_incidence(self):
        document = shared_mirror_roof_scene()
        initial = solve_scene(document)
        self.assertTrue(initial.ok, initial.diagnostics)
        document.layout["poses"] = initial.poses
        roof = document.nodes[2]
        visit = document.optical_pass(roof.id)
        visit.centered = False
        document.passes.append(visit)
        document.layout["poses"][roof.id][3] -= 25
        trace = trace_scene(document)
        alignment = next(row for row in trace.residuals if row.id == f"axis/{roof.id}/yaw")
        self.assertAlmostEqual(alignment.value, 25, delta=1e-6)
        self.assertFalse(trace.ok)

    def test_roof_position_pin_does_not_pin_yaw_when_upstream_beam_moves(self):
        document = shared_mirror_roof_scene()
        mirror, roof = document.nodes[1:3]
        mirror.physical.pop("turn")
        mirror.physical.pop("x")
        initial = solve_scene(document)
        self.assertTrue(initial.ok, initial.diagnostics)
        document.layout["poses"] = initial.poses
        solution = solve_scene(document, targets=((mirror.id, 0, 60),))
        self.assertTrue(solution.ok, solution.diagnostics)
        self.assertEqual(solution.poses[roof.id][:2], [50, 70])
        self.assertGreater(abs(wrap_angle(solution.poses[roof.id][3] - initial.poses[roof.id][3])), 1)
        state = solution.layout.visits[roof.id]
        delta = sub(state.exit, state.entry)
        self.assertAlmostEqual(norm(sub(delta, mul(state.incoming, dot(delta, state.incoming)))), 4, delta=1e-6)
        self.assertEqual(roof.physical, {"x": 50, "y": 70})
        document.layout["poses"] = solution.poses
        self.assertTrue(compile_schematic(document).ok)

    def test_shared_mirror_return_solves_with_displaced_contacts_and_one_body(self):
        for vertical in (False, True):
            for reverse in (False, True):
                with self.subTest(vertical=vertical, reverse=reverse):
                    document = shared_mirror_roof_scene(vertical, reverse)
                    source, mirror, roof, receiver = document.nodes
                    before = deepcopy(document.to_dict())
                    solution = solve_scene(document, iterations=40)
                    self.assertTrue(solution.ok, solution.diagnostics)
                    self.assertEqual(document.to_dict(), before)
                    first = solution.layout.visits[mirror.id]
                    returning = solution.layout.visits["mirror-return"]
                    self.assertLess(norm(sub(first.entry, solution.poses[mirror.id][:3])), 1e-6)
                    self.assertGreater(norm(sub(returning.entry, first.entry)), 3)
                    self.assertLess(norm(sub(returning.entry, first.entry)), 6.35)
                    for node in (source, mirror, roof):
                        self.assertEqual(solution.poses[node.id][:2], document.layout["poses"][node.id][:2])
                    self.assertLess(norm(sub(solution.layout.visits[receiver.id].entry,
                                             solution.poses[receiver.id][:3])), 1e-6)
                    document.layout["poses"] = solution.poses
                    compiled = compile_schematic(document)
                    self.assertTrue(compiled.ok, compiled.diagnostics)
                    self.assertEqual(compiled.source.count("Component('M1',"), 1)

    def test_additional_pass_defaults_allow_return_offsets_and_preserve_centered_receivers(self):
        document = shared_mirror_roof_scene()
        source, mirror, roof, receiver = document.nodes
        self.assertTrue(document.optical_pass(mirror.id).centered)
        self.assertFalse(document.optical_pass("mirror-return").centered)
        self.assertTrue(document.add_pass(source.id).centered)
        self.assertTrue(document.add_pass(roof.id).centered)
        self.assertTrue(document.add_pass(receiver.id).centered)

    def test_existing_centered_return_reports_the_exact_constraint_to_clear(self):
        document = shared_mirror_roof_scene()
        document.optical_pass("mirror-return").centered = True
        before = deepcopy(document.to_dict())
        solution = solve_scene(document)
        self.assertFalse(solution.ok)
        self.assertEqual(solution.status, "inconsistent")
        self.assertEqual(document.to_dict(), before)
        self.assertTrue(any("uncheck Centered hit" in d.message and d.pass_id == "mirror-return"
                            for d in solution.diagnostics))
        self.assertFalse(compile_schematic(document).ok)

    def test_missed_return_aperture_remains_an_error_with_a_physical_remedy(self):
        document = shared_mirror_roof_scene(separation=12.7)
        mirror, roof = document.nodes[1:3]
        document.layout["poses"][mirror.id][3] = 135
        document.layout["poses"][roof.id][3] = 90
        trace = trace_scene(document)
        self.assertFalse(trace.ok)
        self.assertTrue(any("clear radius" in d.message and "reduce the return offset" in d.message
                            and d.pass_id == "mirror-return" for d in trace.diagnostics))
        solution = solve_scene(document, targets=((roof.id, 3, 90),), iterations=40)
        self.assertFalse(solution.ok)

    def test_path_constraint_and_saved_return_keep_both_visits(self):
        document = shared_mirror_roof_scene()
        solution = solve_scene(document)
        self.assertTrue(solution.ok, solution.diagnostics)
        document.layout["poses"] = solution.poses
        mirror = document.nodes[1]
        total = solution.layout.lengths["beam-1"] + solution.layout.lengths["beam-2"]
        total += solution.layout.internal_lengths[document.nodes[2].id]
        document.path_constraints.append(PathLengthConstraint(
            "roundtrip", mirror.id, mirror.id, total, mirror.id, "mirror-return",
        ))
        self.assertTrue(compile_schematic(document).ok)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "roof-return.json"
            save_schematic(document, path)
            restored = load_schematic(path)
            self.assertEqual(restored.to_dict(), document.to_dict())
            self.assertFalse(restored.optical_pass("mirror-return").centered)
            self.assertTrue(compile_schematic(restored).ok)
