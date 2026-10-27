"""Shared physical scenes remain exact through packing, application and storage."""

from copy import deepcopy
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PyOpticL.schematic import (
    Connection,
    Endpoint,
    PathLengthConstraint,
    Schematic,
    compile_schematic,
    load_schematic,
    save_schematic,
)
from PyOpticL.schematic.model import History, document_from_dict
from PyOpticL.schematic.optimization import (
    OptimizationOptions,
    PackingBox,
    build_problem,
    optimize_layout,
    apply_optimization,
    optimized_physical_layout,
)
from PyOpticL.schematic.scene_layout import initialize_layout
from PyOpticL.schematic.scene_solver import solve_scene
from PyOpticL.schematic.effective import folding_protection
from test_schematic import chain
from test_schematic_multipass import double_pass


def folding_scene():
    d = Schematic("Two-fold physical path")
    a, b = d.add_node("source"), d.add_node("output")
    a.id = "source"
    b.id = "output"
    a.physical.update(x=20, y=20, angle=0)
    b.physical.update(x=80, y=20)
    d.connections = [
        Connection("span", Endpoint(a.id, "beam"), Endpoint(b.id, "beam"), length=60, allow_folding=True)
    ]
    d.path_constraints = [PathLengthConstraint("total", a.id, b.id, 180)]
    d.layout = {"poses": {a.id: [20, 20, 0, 0], b.id: [80, 20, 0, 0]}, "splitters": {}, "projection": "XY"}
    return d


def removable_scene(role="folding"):
    d = chain("source", "mirror", "output")
    source, mirror, output = d.nodes
    mirror.preset = "bare"
    mirror.mirror_role = role
    source.physical.update(x=20, y=20, angle=0)
    d.layout = {
        "poses": {
            source.id: [20, 20, 0, 0],
            mirror.id: [70, 20, 0, 100],
            output.id: [70 + 50 * math.cos(math.radians(20)), 20 + 50 * math.sin(math.radians(20)), 0, 0],
        },
        "projection": "XY",
        "splitters": {},
    }
    return d


def splitter_fold_scene():
    from dataclasses import replace

    path = (
        Path(__file__).resolve().parents[1]
        / "Designs/schematics/optimization/adaptive-splitter-90-after.pyopticl-schematic.json"
    )
    document = load_schematic(path)
    saved = document.optimized_layout
    problem = build_problem(
        document,
        saved["radii"],
        PackingBox(**document.optimization["box"]),
        replace(
            OptimizationOptions(**document.optimization["options"]),
            starts=1,
            iterations=2,
            projection_passes=2,
        ),
        folding_radius=saved["folding_radius"],
    )
    result = optimize_layout(problem)
    if result.status != "feasible":
        raise AssertionError(result.violations)
    apply_optimization(document, problem, result)
    return document


class SceneOptimizationTests(unittest.TestCase):
    def test_shared_component_has_one_disk_and_all_passes_survive_apply(self):
        doc = double_pass()
        radii = {
            n.id: 1.2 if n.kind == "mirror" else 8 for n in doc.nodes if n.kind not in ("source", "output")
        }
        options = OptimizationOptions(starts=1, iterations=2, projection_passes=2, max_added_mirrors=0)
        problem = build_problem(doc, radii, PackingBox(-50, -100, 400, 250), options)
        self.assertEqual(len(problem.nodes), 6)
        before = deepcopy([(n.position, n.physical) for n in doc.nodes])
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        self.assertEqual(len(result.layout.visits), 8)
        apply_optimization(doc, problem, result)
        self.assertEqual([(n.position, n.physical) for n in doc.nodes], before)
        self.assertTrue(compile_schematic(doc).ok)
        self.assertEqual(len(optimized_physical_layout(doc).visits), 8)
        doc.node("part-1").reference = "sharedLens"
        doc.layout["projection"] = "XZ"
        doc.settings["show_bounds"] = True
        self.assertTrue(compile_schematic(doc).ok)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "shared.json"
            save_schematic(doc, path)
            restored = load_schematic(path)
            self.assertEqual(restored.to_dict(), doc.to_dict())
            self.assertTrue(compile_schematic(restored).ok)
        rewired = document_from_dict(doc.to_dict())
        for edge in rewired.connections:
            for name in ("a", "b"):
                endpoint = getattr(edge, name)
                if endpoint.node_id == "part-1":
                    setattr(
                        edge,
                        name,
                        Endpoint(
                            endpoint.node_id, endpoint.port_id, "" if endpoint.pass_id else "lens-return"
                        ),
                    )
        self.assertIn("stale", compile_schematic(rewired).diagnostics[0].message.lower())
        doc.node("part-1").parameters["diameter"] = 25.4
        self.assertFalse(compile_schematic(doc).ok)
        self.assertIn("stale", compile_schematic(doc).diagnostics[0].message.lower())

    def test_repeatability_and_cancellation_without_cad(self):
        doc = chain("source", "lens", "output")
        doc.nodes[1].preset = "bare"
        initialize_layout(doc)
        problem = build_problem(
            doc,
            {doc.nodes[1].id: 8},
            PackingBox(-50, -50, 200, 200),
            OptimizationOptions(starts=1, iterations=2, projection_passes=2),
        )
        first, second = optimize_layout(problem), optimize_layout(problem)
        self.assertEqual(first.layout, second.layout)
        cancelled = optimize_layout(problem, cancelled=lambda: True)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertIsNone(cancelled.layout)

    def test_missing_bounds_and_explicit_conflicts_have_actionable_diagnostics(self):
        doc = double_pass()
        with self.assertRaisesRegex(ValueError, "bounds unavailable"):
            build_problem(doc, {})
        d = chain("source", "lens", "output")
        initialize_layout(d)
        for c in d.connections:
            c.length = 50
        d.path_constraints = [PathLengthConstraint("conflict", d.nodes[0].id, d.nodes[-1].id, 150)]
        result = solve_scene(d)
        self.assertEqual(result.status, "inconsistent")
        self.assertIn("Conflicting explicit constraints", result.diagnostics[0].message)

    def test_shared_mirror_is_protected_from_removal(self):
        d = double_pass()
        mirror = d.node("part-4")
        mirror.mirror_role = "folding"
        d.add_pass(mirror.id)
        self.assertIn("multiple optical passes", folding_protection(d, mirror.id))

    def test_migrated_splitter_fold_reruns_with_exact_plus_ninety_turn(self):
        document = splitter_fold_scene()
        compiled = compile_schematic(document)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        state = compiled.geometry.visits["adaptive-splitter-90-BS1"]
        from PyOpticL.ray_math import heading

        self.assertAlmostEqual(heading(state.outputs["transmitted"]) - heading(state.incoming), 0, delta=1e-6)
        self.assertAlmostEqual(heading(state.outputs["reflected"]) - heading(state.incoming), 90, delta=1e-6)
        self.assertEqual(len(compiled.geometry.graph.generated), 1)

    def test_removal_omits_only_unprotected_folding_mirror(self):
        for role in ("folding", "turning"):
            d = removable_scene(role)
            mirror = d.nodes[1]
            p = build_problem(
                d,
                {mirror.id: 9},
                PackingBox(0, 0, 200, 100),
                OptimizationOptions(
                    starts=1, iterations=600 if role == "folding" else 2, projection_passes=2
                ),
            )
            result = optimize_layout(p)
            self.assertEqual(result.status, "feasible", result.violations)
            self.assertEqual(mirror.id in result.layout.graph.bypassed, role == "folding")
            apply_optimization(d, p, result)
            self.assertTrue(compile_schematic(d).ok)
            if role == "folding":
                self.assertNotIn(mirror.id, result.layout.poses)
                d.nodes[1].physical["x"] = 70
                self.assertIn("stale", compile_schematic(d).diagnostics[0].message.lower())

    def test_coincident_shared_scene_disks_separate_deterministically(self):
        d = chain("source", "lens", "qwp", "output")
        initialize_layout(d)
        d.layout["poses"][d.nodes[2].id] = list(d.layout["poses"][d.nodes[1].id])
        p = build_problem(
            d,
            {d.nodes[1].id: 8, d.nodes[2].id: 8},
            PackingBox(-30, -50, 250, 100),
            OptimizationOptions(starts=1, iterations=20, projection_passes=5),
        )
        a, b = optimize_layout(p), optimize_layout(p)
        self.assertEqual(a.status, "feasible", a.violations)
        self.assertEqual(a.layout, b.layout)
        self.assertGreaterEqual(math.dist(a.positions[1], a.positions[2]), 17 - 1e-6)

    def test_two_fold_search_keeps_chord_and_total_length_and_exports_once(self):
        d = folding_scene()
        before = deepcopy(d.to_dict())
        frames = []
        problem = build_problem(
            d,
            {},
            PackingBox(0, 0, 100, 100),
            OptimizationOptions(
                starts=1, iterations=2400, projection_passes=5, folding_preset="bare", max_added_mirrors=2
            ),
            folding_radius=9,
        )
        result = optimize_layout(problem, progress=frames.append)
        self.assertEqual(result.status, "feasible", result.violations)
        self.assertEqual(d.to_dict(), before)
        self.assertEqual(len(result.layout.graph.generated), 2)
        self.assertAlmostEqual(sum(result.layout.lengths.values()), 180, delta=1e-6)
        self.assertAlmostEqual(
            math.dist(result.layout.poses["source"][:3], result.layout.poses["output"][:3]), 60, delta=1e-6
        )
        self.assertTrue(any(f.problem.graph.generated for f in frames))
        history = History(d)
        apply_optimization(d, problem, result)
        history.commit(d)
        compiled = compile_schematic(d)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        self.assertEqual(compiled.source.count(" = Component("), 2)
        self.assertAlmostEqual(compiled.path_lengths["total"], 180, delta=1e-6)
        restored = history.undo()
        self.assertIsNone(restored.optimized_layout)
        restored = history.redo()
        self.assertTrue(compile_schematic(restored).ok)


if __name__ == "__main__":
    unittest.main()
