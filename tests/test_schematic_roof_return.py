"""A displaced roof return reuses one mirror at two distinct finite hits."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyOpticL.ray_math import norm, sub, yaw
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

    def test_default_roof_separation_can_reflow_an_unpinned_return(self):
        document = shared_mirror_roof_scene(separation=12.7)
        for node in document.nodes:
            node.physical = {}
        solution = solve_scene(document, iterations=40)
        self.assertTrue(solution.ok, solution.diagnostics)
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
