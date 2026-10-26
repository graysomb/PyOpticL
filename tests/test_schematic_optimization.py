"""Numerical layout, canonical verification, persistence and export (no CAD)."""

import ast
from copy import deepcopy
from dataclasses import replace
import math
import runpy
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from PyOpticL.schematic import History, compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.model import document_from_dict
from PyOpticL.schematic.optimization import (
    OptimizationOptions,
    PackingBox,
    apply_optimization,
    build_problem,
    capsule_distance,
    forces,
    initial_box,
    layout_violations,
    optimize_layout,
    project_constraints,
    reconstruct_candidate,
    signed_turn,
    turn_gradients,
)
from PyOpticL.schematic.physical import wrap_angle
from test_schematic import chain, branched


def bounds(document, radius=5):
    return {n.id: radius for n in document.nodes if n.kind not in ("source", "output")}


def problem(document, box=None, **options):
    return build_problem(
        document,
        bounds(document),
        box or PackingBox(-10, -10, 240, 180),
        OptimizationOptions(starts=2, iterations=300, **options),
    )


def folding_fixture():
    document = chain("source", "mirror", "stop")
    document.nodes[0].physical.update(x=0, y=0, angle=0)
    document.connections[0].length = 50
    document.nodes[-1].physical.update(x=80, y=40)
    return document


class OptimizationMathTests(unittest.TestCase):
    def test_angle_gradient_matches_central_difference_of_travel_turn(self):
        points = [[-13.0, 7.0], [20.0, -9.0], [31.0, 24.0]]
        gradients = turn_gradients(*points)
        for i in range(3):
            for axis in (0, 1):
                plus, minus = deepcopy(points), deepcopy(points)
                plus[i][axis] += 1e-5
                minus[i][axis] -= 1e-5
                numerical = math.radians(wrap_angle(signed_turn(*plus) - signed_turn(*minus))) / (2e-5)
                self.assertAlmostEqual(gradients[i][axis], numerical, places=8)
        self.assertEqual(signed_turn((0, 0), (10, 0), (10, 10)), 90)
        self.assertEqual(signed_turn((0, 0), (10, 0), (10, -10)), -90)
        self.assertEqual(signed_turn((0, 0), (10, 0), (20, 0)), 0)

    def test_inverse_square_repulsion_and_hooke_force_balance(self):
        p = problem(chain("source", "output"))
        # Isolate repulsion by removing edges, then compare separation doubling.
        isolated = replace(p, edges=())
        first = forces(isolated, ((0, 0), (50, 0)))
        second = forces(isolated, ((0, 0), (100, 0)))
        self.assertAlmostEqual(first[1][0], 4 * second[1][0])
        self.assertEqual(first[0][0], -first[1][0])
        self.assertGreater(first[1][0], 0)
        spring = forces(p, ((0, 0), (100, 0)))
        self.assertGreater(spring[0][0], 0)
        self.assertEqual(spring[0][0], -spring[1][0])

    def test_projection_keeps_partial_pins_and_exact_lengths(self):
        d = chain("source", "output")
        d.nodes[0].physical["x"] = 10
        d.nodes[1].physical["y"] = 40
        d.connections[0].length = 50
        p = problem(d)
        positions = [[10.0, 10.0], [90.0, 40.0]]
        for _ in range(100):
            project_constraints(p, positions)
        self.assertEqual(positions[0][0], 10)
        self.assertEqual(positions[1][1], 40)
        self.assertAlmostEqual(math.dist(*positions), 50, places=6)
        self.assertFalse(layout_violations(p, positions))

    def test_projection_signed_turn_source_heading_and_straight_optics(self):
        for kind, turn in (("mirror", -60), ("lens", 0), ("hwp", 0), ("qwp", 0), ("iris", 0)):
            with self.subTest(kind=kind):
                d = chain("source", kind, "output")
                d.nodes[0].physical.update(x=20, y=20, angle=10)
                if kind == "mirror":
                    d.nodes[1].physical["turn"] = turn
                p = problem(d, PackingBox(-200, -200, 500, 500))
                positions = [[20.0, 20.0], [70.0, 30.0], [115.0, 60.0]]
                for _ in range(250):
                    project_constraints(p, positions)
                self.assertFalse(layout_violations(p, positions))
                self.assertAlmostEqual(signed_turn(*positions), turn, places=6)

    def test_disk_and_beam_endpoint_exemptions_and_capsule_containment(self):
        d = chain("source", "mirror", "stop")
        p = problem(d, PackingBox(0, 0, 100, 100), clearance_mm=2, beam_diameter_mm=4)
        positions = ((4, 20), (40, 20), (40, 60))
        self.assertFalse(layout_violations(p, positions))
        # A physical part is never tested against either of its own beams.
        self.assertFalse(any(v.kind == "beam_clearance" for v in layout_violations(p, positions)))
        outside = ((3, 20), (40, 20), (40, 60))  # virtual source's capsule needs 4 mm margin
        self.assertTrue(any(v.kind == "boundary" for v in layout_violations(p, outside)))
        on_other_beam = ((4, 20), (50, 20), (30, 20))
        self.assertTrue(any(v.kind == "beam_clearance" for v in layout_violations(p, on_other_beam)))
        self.assertEqual(capsule_distance((5, 3), (0, 0), (10, 0)), (0.5, 0, 3))

    def test_capsule_gradient_projection_and_nonfinite_rejection(self):
        p = problem(chain("source", "mirror", "stop"), PackingBox(-100, -100, 300, 300))
        p = replace(p, edges=(p.edges[0],), angles=())
        positions = [[0.0, 0.0], [100.0, 0.0], [50.0, 5.0]]
        project_constraints(p, positions)
        _, dx, dy = capsule_distance(positions[2], positions[0], positions[1])
        self.assertAlmostEqual(math.hypot(dx, dy), 6.5, places=8)
        self.assertAlmostEqual(sum(point[1] for point in positions), 5)
        # Point/endpoint distance gradients, including the closest-point weights.
        point, a, b = [4.0, 3.0], [0.0, 0.0], [10.0, 0.0]
        t, dx, dy = capsule_distance(point, a, b)
        d = math.hypot(dx, dy)
        normal = (dx / d, dy / d)
        gradients = (normal, tuple(-(1 - t) * v for v in normal), tuple(-t * v for v in normal))
        for index in range(3):
            for axis in (0, 1):
                plus, minus = [point[:], a[:], b[:]], [point[:], a[:], b[:]]
                plus[index][axis] += 1e-5
                minus[index][axis] -= 1e-5
                numerical = (
                    math.hypot(*capsule_distance(*plus)[1:]) - math.hypot(*capsule_distance(*minus)[1:])
                ) / 2e-5
                self.assertAlmostEqual(numerical, gradients[index][axis], places=7)
        positions[0][0] = float("nan")
        self.assertEqual(layout_violations(p, positions)[0].kind, "nonfinite")

    def test_beam_crossings_are_allowed(self):
        p = problem(chain("source", "mirror", "mirror", "output"), PackingBox(-20, -20, 140, 140))
        crossing = ((0, 0), (100, 100), (0, 100), (100, 0))
        self.assertFalse(layout_violations(p, crossing))
        _, _, violations = reconstruct_candidate(p, crossing)
        self.assertFalse(violations)

    def test_collision_projection_and_coincident_points_are_finite_deterministic(self):
        p = problem(chain("source", "mirror", "stop"), PackingBox(-100, -100, 300, 300))
        a = [[20.0, 20.0] for _ in p.nodes]
        b = deepcopy(a)
        for _ in range(80):
            project_constraints(p, a)
            project_constraints(p, b)
        self.assertEqual(a, b)
        self.assertTrue(all(math.isfinite(v) for point in a for v in point))
        self.assertGreater(math.dist(a[1], a[2]), 10.99999)
        f = forces(p, [(0, 0)] * len(p.nodes))
        self.assertTrue(all(math.isfinite(v) for point in f for v in point))


class OptimizationSearchTests(unittest.TestCase):
    def test_folding_requires_changing_free_angle_and_preserves_constraints(self):
        d = folding_fixture()
        self.assertFalse(compile_schematic(d).ok)
        before = deepcopy(d.to_dict())
        p = problem(d, PackingBox(-10, -10, 110, 70))
        r = optimize_layout(p)
        self.assertEqual(r.status, "feasible", r.violations)
        self.assertAlmostEqual(r.layout.turns[d.nodes[1].id], 53.1301023542, places=6)
        self.assertEqual(r.layout.lengths[d.connections[0].id], 50)
        self.assertEqual(d.to_dict(), before)
        apply_optimization(d, p, r)
        self.assertEqual(d.nodes[1].physical, {})
        self.assertIsNone(d.connections[1].length)
        self.assertEqual(d.to_dict()["nodes"], before["nodes"])
        self.assertEqual(d.to_dict()["connections"], before["connections"])
        c = compile_schematic(d)
        self.assertTrue(c.ok, c.diagnostics)
        self.assertEqual(c.placements["D1"][:2], (80, 40))
        self.assertEqual(c.geometry, r.layout)
        self.assertIn("check_trace(beam", c.source)

    def test_seeded_repeatability_and_multiple_starts(self):
        p = problem(chain("source", "mirror", "mirror", "output"), PackingBox(0, 0, 115, 80))
        first, second = optimize_layout(p), optimize_layout(p)
        self.assertEqual(first, second)
        self.assertEqual(first.status, "feasible")
        # Conflicting pins consume every start, rather than reporting impossibility.
        d = chain("source", "stop")
        for n in d.nodes:
            n.physical.update(x=10, y=10)
        p = problem(d, PackingBox(0, 0, 40, 40))
        p = replace(p, options=replace(p.options, starts=3, iterations=7))
        r = optimize_layout(p)
        self.assertEqual((r.status, r.starts, r.iterations), ("no_feasible_layout", 3, 21))
        self.assertTrue(r.violations)

    def test_mixed_fixed_free_splitter_reconstructs_transmission_straight(self):
        d = branched()
        d.nodes[0].physical.update(x=10, y=10, angle=0)
        d.nodes[-1].physical["y"] = 80
        d.connections[0].length = 35
        p = build_problem(
            d, bounds(d), PackingBox(0, 0, 160, 110), OptimizationOptions(starts=2, iterations=1000)
        )
        r = optimize_layout(p)
        self.assertEqual(r.status, "feasible", r.violations)
        self.assertFalse(layout_violations(p, r.positions))
        self.assertEqual(r.positions[0], (10, 10))
        self.assertAlmostEqual(r.layout.positions[d.nodes[-1].id][1], 80, delta=1e-6)
        self.assertAlmostEqual(
            r.layout.headings[d.connections[1].id], r.layout.headings[d.connections[2].id], places=6
        )
        apply_optimization(d, p, r)
        self.assertTrue(compile_schematic(d).ok)

    def test_splitter_example_keeps_explicit_right_angle_when_packed(self):
        example = runpy.run_path(
            str(Path(__file__).resolve().parents[1] / "Designs/schematics/optimization/generate.py")
        )
        document, box, options = list(example["fixtures"]())[1]
        cube = next(node for node in document.nodes if node.kind == "splitter")
        self.assertEqual(cube.physical.get("turn"), 90, "The example must explicitly constrain the cube")
        from PyOpticL.schematic.bounds import BoundsProvider, resolve_layout_bounds

        radii, errors = resolve_layout_bounds(document, BoundsProvider(example["primitive_circle"]))
        self.assertFalse(errors)
        p = build_problem(document, radii, box, options)
        result = optimize_layout(p)
        self.assertEqual(result.status, "feasible", result.violations)
        self.assertFalse(layout_violations(p, result.positions))
        checks = example["verify_interfaces"](document, result.layout.positions)
        cube_checks = [check for check in checks if check["reference"] == cube.reference]
        self.assertEqual({check["constraint_deg"] for check in cube_checks}, {0, 90})
        for check in cube_checks:
            self.assertAlmostEqual(check["measured_turn_deg"], check["constraint_deg"], delta=1e-6)
        apply_optimization(document, p, result)
        compiled = compile_schematic(document)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        assignments = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in ast.parse(compiled.source).body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        }
        exported = dict(result.layout.positions)
        for node in document.nodes:
            if node.reference in assignments["PLACEMENTS"]:
                exported[node.id] = assignments["PLACEMENTS"][node.reference][:2]
        example["verify_interfaces"](document, exported)
        # A saved 'feasible' label cannot bypass final constraint verification.
        changed_layout = replace(result.layout, turns={**result.layout.turns, cube.id: 45})
        with self.assertRaises(ValueError):
            apply_optimization(document, p, replace(result, layout=changed_layout))

    def test_unconstrained_source_direction_moves_between_pinned_points(self):
        d = chain("source", "output")
        d.nodes[0].physical.update(x=10, y=10)
        d.nodes[1].physical.update(x=40, y=50)
        d.connections[0].length = 50
        p = problem(d)
        r = optimize_layout(p)
        self.assertEqual(r.status, "feasible", r.violations)
        self.assertAlmostEqual(r.layout.source_direction, 53.1301023542, places=6)
        self.assertEqual(r.positions, ((10, 10), (40, 50)))
        apply_optimization(d, p, r)
        self.assertNotIn("angle", d.nodes[0].physical)
        self.assertTrue(compile_schematic(d).ok)

    def test_folded_chain_with_fixed_lengths_and_unconstrained_source_pose(self):
        d = chain("source", "mirror", "mirror", "mirror", "output")
        for edge in d.connections:
            edge.length = 50
        p = problem(d, PackingBox(0, 0, 100, 70))
        r = optimize_layout(p)
        self.assertEqual(r.status, "feasible", r.violations)
        self.assertEqual(set(r.layout.lengths.values()), {50})
        self.assertFalse(layout_violations(p, r.positions))

    def test_cancellation_inside_projection_and_progress(self):
        p = problem(folding_fixture())
        calls = []

        def cancel():
            calls.append(1)
            return len(calls) >= 5

        r = optimize_layout(p, cancelled=cancel)
        self.assertEqual(r.status, "cancelled")
        self.assertIsNone(r.layout)
        self.assertEqual(r.iterations, 1)
        frames = []
        r = optimize_layout(p, progress=frames.append)
        self.assertTrue(frames)
        self.assertTrue(all(isinstance(f.positions, tuple) for f in frames))

    def test_missing_bounds_oversized_parts_and_iteration_limit(self):
        d = chain("source", "stop")
        with self.assertRaisesRegex(ValueError, "D1.*bounds unavailable"):
            build_problem(d, {})
        with self.assertRaises(ValueError):
            build_problem(d, {d.nodes[-1].id: float("nan")})
        p = build_problem(
            d, bounds(d, 50), PackingBox(0, 0, 20, 20), OptimizationOptions(starts=1, iterations=5)
        )
        r = optimize_layout(p)
        self.assertEqual(r.status, "no_feasible_layout")
        self.assertEqual(r.iterations, 5)
        self.assertTrue(any(v.kind == "boundary" and v.node_ids for v in r.violations))
        with self.assertRaises(ValueError):
            apply_optimization(d, p, r)

    def test_canonical_reconstruction_catches_accumulated_pin_error(self):
        d = chain("source", "lens", "output")
        d.nodes[0].physical.update(x=10, y=10, angle=0)
        d.nodes[-1].physical.update(x=110, y=10.00001)
        p = problem(d)
        layout, positions, violations = reconstruct_candidate(p, ((10, 10), (60, 10.000005), (110, 10.00001)))
        self.assertEqual(positions[-1][1], 10)
        self.assertTrue(any(v.kind == "position" for v in violations))


class OptimizationStorageTests(unittest.TestCase):
    def setUp(self):
        self.document = folding_fixture()
        self.problem = problem(self.document)
        self.result = optimize_layout(self.problem)
        self.assertEqual(self.result.status, "feasible")
        self.history = History(self.document)
        apply_optimization(self.document, self.problem, self.result)
        self.history.commit(self.document)

    def test_round_trip_undo_redo_and_older_versions(self):
        self.assertIsNone(self.history.undo().optimized_layout)
        restored = self.history.redo()
        self.assertEqual(restored.to_dict(), self.document.to_dict())
        with TemporaryDirectory() as directory:
            path = Path(directory) / "optimized.json"
            save_schematic(restored, path)
            self.assertEqual(load_schematic(path).to_dict(), restored.to_dict())
        for version in (1, 2, 3, 4):
            old = chain("source", "output").to_dict()
            old["version"] = version
            if version == 1:
                edge = old["connections"][0]
                old["connections"] = [
                    {
                        "id": edge["id"],
                        "source": edge["a"]["node_id"],
                        "source_port": "out",
                        "target": edge["b"]["node_id"],
                        "target_port": "in",
                    }
                ]
            loaded = document_from_dict(old)
            self.assertEqual(loaded.version, 5)
            self.assertIsNone(loaded.optimized_layout)

    def test_drawing_reference_and_display_edits_preserve_solution(self):
        d = self.document
        for n in d.nodes:
            n.reference += "renamed"
            n.position = (1000, -1000)
            n.rotation = 45
        for e in d.connections:
            e.bends = [(500, 500)]
            e.a, e.b = e.b, e.a
        d.settings.update(show_bounds=True, bounds_scale=9, grid=30)
        d.title = "New title"
        self.assertTrue(compile_schematic(d).ok)
        c = compile_schematic(d)
        self.assertEqual(c.geometry, self.result.layout)

    def test_part_constraints_defaults_and_configuration_invalidate_export(self):
        original = self.document.to_dict()
        mutations = [
            lambda d: d.nodes[1].parameters.update(diameter=12),
            lambda d: setattr(d.nodes[1], "preset", "bare"),
            lambda d: d.nodes[1].physical.update(turn=60),
            lambda d: setattr(d.connections[-1], "length", 60),
            lambda d: d.settings.update(spacing=55),
            lambda d: d.optimization["box"].update(width=500),
        ]
        for mutate in mutations:
            d = document_from_dict(original)
            mutate(d)
            self.assertFalse(compile_schematic(d).ok)
            # Stale results remain saveable, even after graph edits.
            self.assertIsNotNone(document_from_dict(d.to_dict()).optimized_layout)
        d = document_from_dict(original)
        d.remove_nodes([d.nodes[-1].id])
        self.assertIsNotNone(document_from_dict(d.to_dict()).optimized_layout)
        d = document_from_dict(original)
        d.settings["spacing"] = 55
        d.optimized_layout = None
        # This fixture's fixed-angle pins conflict even without optimization.
        d.nodes[-1].physical.clear()
        self.assertTrue(compile_schematic(d).ok)

    def test_geometry_settings_and_library_specification_changes_invalidate(self):
        with patch("PyOpticL.schematic.optimization.geometry_settings", return_value={"changed": True}):
            result = compile_schematic(self.document)
            self.assertFalse(result.ok)
            self.assertIn("stale", result.diagnostics[0].message)
        from PyOpticL.schematic.parts import part_spec

        def changed_spec(document, node, topology):
            spec = part_spec(document, node, topology)
            return replace(spec, factory="ChangedPart") if spec is not None else None

        with patch("PyOpticL.schematic.parts.part_spec", side_effect=changed_spec):
            self.assertFalse(compile_schematic(self.document).ok)

    def test_invalid_storage_and_tampered_geometry_are_rejected(self):
        for value in (float("nan"), True, "12"):
            data = deepcopy(self.document.to_dict())
            data["optimized_layout"]["geometry"]["source_pose"][0] = value
            with self.assertRaises(ValueError):
                document_from_dict(data)
        d = document_from_dict(self.document.to_dict())
        d.optimized_layout["geometry"]["source_pose"][0] += 0.001
        self.assertFalse(compile_schematic(d).ok)
        d = document_from_dict(self.document.to_dict())
        d.optimized_layout["geometry"]["lengths"].clear()
        self.assertFalse(compile_schematic(d).ok)

    def test_effective_source_open_lengths_and_splitter_configuration_export(self):
        d = chain("source", "mirror", "output")
        p = problem(d, PackingBox(100, 200, 130, 120))
        r = optimize_layout(p)
        apply_optimization(d, p, r)
        c = compile_schematic(d)
        assignments = {
            n.targets[0].id: ast.literal_eval(n.value)
            for n in ast.parse(c.source).body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
        }
        self.assertEqual(assignments["SOURCE"]["x"], round(r.layout.positions[d.nodes[0].id][0], 9))
        self.assertEqual(assignments["SOURCE"]["angle"], round(r.layout.source_direction, 9))
        self.assertEqual(assignments["OPEN_LENGTHS"][("M1", "out")], r.layout.lengths[d.connections[-1].id])
        d = branched()
        d.nodes[2].physical["turn"] = -75
        p = problem(d, PackingBox(-50, -100, 300, 300))
        r = optimize_layout(p)
        self.assertEqual(r.status, "feasible")
        apply_optimization(d, p, r)
        self.assertIn("rotate_cube=True", compile_schematic(d).source)

    def test_initial_box_prefers_saved_region_and_has_ten_mm_padding(self):
        d = chain("source", "stop")
        box = initial_box(d, bounds(d))
        self.assertEqual(box, PackingBox(-10, -15, 75, 30))
        self.assertEqual(initial_box(self.document, bounds(self.document)), self.problem.box)
        d.nodes[-1].physical.update(x=1, y=1)
        self.assertEqual(initial_box(d, bounds(d)), PackingBox(-150, -100, 300, 200))

    def test_pure_optimizer_imports_no_qt_or_freecad(self):
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from PyOpticL.schematic import optimize_layout; assert not any(n.startswith(('FreeCAD','PySide','Part','Mesh')) for n in sys.modules)",
            ],
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
