"""Adaptive physical graphs and hard path/chord constraints without CAD."""

import ast
from copy import deepcopy
from dataclasses import replace
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyOpticL.schematic import (
    History,
    PathLengthConstraint,
    compile_schematic,
    load_schematic,
    save_schematic,
)
from PyOpticL.schematic.effective import (
    can_insert,
    effective_document,
    folding_protection,
    identity_graph,
    insert_mirror,
    remove_mirror,
    replay_graph,
)
from PyOpticL.schematic.optimization import (
    OptimizationOptions,
    PackingBox,
    apply_optimization,
    build_problem,
    candidate_problem,
    layout_violations,
    optimize_layout,
    path_value_gradients,
    project_constraints,
    reconstruct_candidate,
)
from PyOpticL.schematic.paths import path_length
from test_schematic import chain, connect

RADIUS = 8.736274949885678  # analytic bare 12.7 mm / 6 mm mirror envelope


def fold_span(total=120, separation=80, angle=None, box=None, starts=1, iterations=1500):
    doc = chain("source", "output")
    a, b = doc.nodes
    # Stable IDs also make repeated separately-created fixtures comparable.
    a.id, b.id = "source", "output"
    doc.connections[0].id = "span"
    from PyOpticL.schematic import Endpoint

    doc.connections[0].a, doc.connections[0].b = Endpoint(a.id, "beam"), Endpoint(b.id, "beam")
    a.physical.update(x=0, y=0)
    b.physical.update(x=separation, y=0)
    if angle is not None:
        a.physical["angle"] = angle
    doc.connections[0].length = separation
    doc.connections[0].allow_folding = True
    doc.path_constraints.append(PathLengthConstraint("path", a.id, b.id, total))
    options = OptimizationOptions(starts=starts, iterations=iterations, folding_preset="bare")
    problem = build_problem(doc, {}, box or PackingBox(-20, -60, 140, 130), options, folding_radius=RADIUS)
    return doc, problem


def folded_splitter():
    doc = chain("source", "splitter")
    a, cube = doc.nodes
    a.physical.update(x=0, y=0, angle=0)
    cube.physical.update(x=50, y=0, turn=90)
    doc.connections[0].length = 50
    straight = doc.add_node("output")
    straight.physical.update(x=150, y=0)
    transmitted = connect(doc, cube, straight, "right")
    transmitted.length = 100
    reflected = doc.add_node("output")
    reflected.physical.update(x=130, y=80)
    connection = connect(doc, cube, reflected, "top")
    connection.allow_folding = True
    doc.path_constraints.append(PathLengthConstraint("reflected-path", cube.id, reflected.id, 160))
    return doc, PackingBox(-20, -20, 220, 150)


def removable_mirror():
    doc = chain("source", "mirror", "output")
    a, m, b = doc.nodes
    m.preset, m.mirror_role = "bare", "folding"
    a.physical.update(x=0, y=0)
    b.physical.update(x=100, y=0)
    doc.path_constraints.append(PathLengthConstraint("path", a.id, b.id, 100))
    problem = build_problem(
        doc,
        {m.id: RADIUS},
        PackingBox(-15, -30, 150, 100),
        OptimizationOptions(starts=1, iterations=1500, folding_preset="bare"),
    )
    return doc, problem


class EffectiveGraphTests(unittest.TestCase):
    def test_split_merge_preferences_and_connectivity(self):
        doc, problem = fold_span()
        first = insert_mirror(doc, problem.graph, "span", problem.options)
        second = insert_mirror(doc, first, first.segments[0].id, problem.options)
        self.assertEqual(
            sum(weight for edge in second.segments for key, weight in edge.shares if key == "span"), 1
        )
        for node in list(second.generated):
            second = remove_mirror(doc, second, node.id, problem.options)
        self.assertEqual(len(second.segments), 1)
        self.assertEqual(second.segments[0].shares, (("span", 1.0),))
        self.assertFalse(second.generated)
        self.assertEqual(replay_graph(doc, first.to_dict(), problem.options), first)
        doc.connections[0].a, doc.connections[0].b = doc.connections[0].b, doc.connections[0].a
        self.assertEqual(replay_graph(doc, first.to_dict(), problem.options), first)

    def test_permissions_limits_and_protected_mirrors(self):
        doc, problem = fold_span()
        doc.connections[0].allow_folding = False
        with self.assertRaises(ValueError):
            insert_mirror(doc, problem.graph, "span", problem.options)
        doc.connections[0].allow_folding = True
        options = replace(problem.options, max_added_mirrors=1, max_folds_per_beam=1)
        graph = insert_mirror(doc, problem.graph, "span", options)
        self.assertFalse(can_insert(doc, graph, graph.segments[0], options))
        with self.assertRaises(ValueError):
            insert_mirror(doc, graph, graph.segments[0].id, options)
        doc, problem = removable_mirror()
        mirror = doc.nodes[1]
        self.assertIsNone(folding_protection(doc, mirror.id))
        cases = [
            lambda: setattr(mirror, "mirror_role", "turning"),
            lambda: mirror.physical.update(x=50),
            lambda: mirror.physical.update(turn=90),
            lambda: setattr(doc.connections[0], "length", 50),
            lambda: doc.path_constraints.append(
                PathLengthConstraint("endpoint", mirror.id, doc.nodes[-1].id, 50)
            ),
        ]
        for mutate in cases:
            original = deepcopy(doc.to_dict())
            mutate()
            self.assertIsNotNone(folding_protection(doc, mirror.id))
            with self.assertRaises(ValueError):
                remove_mirror(doc, identity_graph(doc), mirror.id, problem.options)
            from PyOpticL.schematic.model import document_from_dict

            doc = document_from_dict(original)
            mirror = doc.nodes[1]

    def test_merged_span_needs_every_original_permission(self):
        doc, problem = removable_mirror()
        doc.connections[0].allow_folding = True
        graph = remove_mirror(doc, problem.graph, doc.nodes[1].id, problem.options)
        self.assertFalse(can_insert(doc, graph, graph.segments[0], problem.options))
        doc.connections[1].allow_folding = True
        self.assertTrue(can_insert(doc, graph, graph.segments[0], problem.options))
        candidate = candidate_problem(problem, graph, {})
        self.assertEqual(candidate.edges[0].preferred_length, 100)

    def test_snapshot_replay_rejects_unpermitted_edits(self):
        doc, problem = fold_span()
        graph = insert_mirror(doc, problem.graph, "span", problem.options)
        doc.connections[0].allow_folding = False
        with self.assertRaises(ValueError):
            replay_graph(doc, graph.to_dict(), problem.options)
        doc, problem = removable_mirror()
        graph = remove_mirror(doc, problem.graph, doc.nodes[1].id, problem.options)
        doc.nodes[1].physical["x"] = 50
        with self.assertRaises(ValueError):
            replay_graph(doc, graph.to_dict(), problem.options)


class FoldingMathTests(unittest.TestCase):
    def test_path_gradient_accumulates_shared_nodes_and_matches_finite_difference(self):
        doc, problem = fold_span()
        graph = insert_mirror(doc, problem.graph, "span", problem.options)
        candidate = candidate_problem(
            problem, graph, {"source": (0, 0), "output": (80, 0), graph.generated[0].id: (30, 45)}
        )
        points = [list(point) for point in candidate.initial_positions]
        value, indices, gradients = path_value_gradients(candidate, points, candidate.path_lengths[0])
        for i, gradient in zip(indices, gradients):
            for axis in (0, 1):
                plus, minus = deepcopy(points), deepcopy(points)
                plus[i][axis] += 1e-5
                minus[i][axis] -= 1e-5
                numerical = (
                    path_value_gradients(candidate, plus, candidate.path_lengths[0])[0]
                    - path_value_gradients(candidate, minus, candidate.path_lengths[0])[0]
                ) / 2e-5
                self.assertAlmostEqual(numerical, gradient[axis], places=7)
        for _ in range(200):
            project_constraints(candidate, points)
        self.assertFalse(layout_violations(candidate, points))
        self.assertEqual(tuple(points[candidate.source_index]), (0, 0))
        self.assertAlmostEqual(
            math.dist(points[candidate.separations[0].a], points[candidate.separations[0].b]), 80, places=6
        )
        self.assertAlmostEqual(
            path_value_gradients(candidate, points, candidate.path_lengths[0])[0], 120, places=6
        )

    def test_overlapping_paths_with_partial_pins(self):
        doc = chain("source", "mirror", "mirror", "output")
        doc.nodes[0].physical["x"] = 10
        doc.nodes[-1].physical["y"] = 60
        doc.path_constraints = [
            PathLengthConstraint("ac", doc.nodes[0].id, doc.nodes[2].id, 100),
            PathLengthConstraint("bd", doc.nodes[1].id, doc.nodes[3].id, 110),
        ]
        problem = build_problem(
            doc,
            {node.id: 5 for node in doc.nodes if node.kind == "mirror"},
            PackingBox(-100, -100, 400, 400),
            OptimizationOptions(starts=1, iterations=800),
        )
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        self.assertEqual(result.positions[0][0], 10)
        self.assertAlmostEqual(result.layout.positions[doc.nodes[-1].id][1], 60, delta=1e-6)


class FoldingSearchTests(unittest.TestCase):
    def test_insertion_hysteresis_cooldown_and_shared_iteration_budget(self):
        from PyOpticL.schematic.folding import Candidate, _proposals

        doc, problem = fold_span()
        candidate = Candidate(problem, problem.initial_positions)
        children = list(_proposals(problem, candidate, doc, 200, lambda: False))
        self.assertEqual(len(children), 6)
        for child in children:
            mirror = child.problem.graph.generated[0]
            interior = 180 - abs(child.layout.turns[mirror.id])
            self.assertLessEqual(interior, problem.options.removal_angle_deg - 10)
            self.assertFalse(list(_proposals(problem, child, doc, 399, lambda: False)))
        # An infeasible pinned path/chord pair consumes its shared budget even
        # after topology proposals; no candidate receives a fresh 5,000 steps.
        doc.path_constraints[0].length_mm = 70
        limited = build_problem(
            doc, {}, problem.box, replace(problem.options, starts=2, iterations=450), folding_radius=RADIUS
        )
        result = optimize_layout(limited)
        self.assertEqual(result.status, "no_feasible_layout")
        self.assertEqual(result.iterations, 900)
        self.assertIsNone(result.layout)
        self.assertTrue(result.violations)

    def test_addition_preserves_chord_and_path_and_exports_real_mirror(self):
        doc, problem = fold_span()
        before = deepcopy(doc.to_dict())
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        self.assertEqual(len(result.layout.graph.generated), 1)
        self.assertEqual(doc.to_dict(), before)
        self.assertEqual(result, optimize_layout(problem))
        apply_optimization(doc, problem, result)
        compiled = compile_schematic(doc)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        self.assertAlmostEqual(compiled.lengths["span"], 80, delta=1e-6)
        self.assertAlmostEqual(compiled.routed_lengths["span"], 120, delta=1e-6)
        self.assertAlmostEqual(compiled.path_lengths["path"], 120, delta=1e-6)
        self.assertIn("Circular_Mirror", compiled.source)
        self.assertIn("FM1", compiled.source)
        self.assertIn("# Optimizer-added Folding mirrors: 'FM1'", compiled.source)
        self.assertEqual(doc.to_dict()["nodes"], before["nodes"])
        self.assertEqual(doc.to_dict()["connections"], before["connections"])
        assignments = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in ast.parse(compiled.source).body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        }
        self.assertEqual(len(assignments["PLACEMENTS"]), 1)
        self.assertAlmostEqual(sum(result.layout.lengths.values()), 120, delta=1e-6)
        self.assertLess(next(iter(assignments["OPEN_LENGTHS"].values())), 120)
        # Unmarked spans cannot silently receive the same topology edits.
        doc.optimized_layout = None
        doc.connections[0].allow_folding = False
        fixed = build_problem(doc, {}, problem.box, replace(problem.options, iterations=5))
        self.assertEqual(optimize_layout(fixed).status, "no_feasible_layout")

    def test_multiple_folds_with_pinned_source_direction(self):
        doc, problem = fold_span(
            total=180, separation=100, angle=0, box=PackingBox(-15, -15, 130, 110), starts=2, iterations=3000
        )
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        self.assertGreaterEqual(len(result.layout.graph.generated), 2)
        self.assertLessEqual(len(result.layout.graph.generated), 4)
        self.assertFalse(layout_violations(result.problem, result.positions))
        self.assertEqual(result.layout.source_direction, 0)
        self.assertLessEqual(result.iterations, problem.options.starts * problem.options.iterations)
        apply_optimization(doc, problem, result)
        self.assertTrue(compile_schematic(doc).ok)

    def test_splitter_stays_at_ninety_degrees_while_its_reflected_path_folds(self):
        doc, box = folded_splitter()
        cube = doc.nodes[1]
        problem = build_problem(
            doc,
            {cube.id: 12.7 / math.sqrt(2)},
            box,
            OptimizationOptions(starts=1, iterations=1800, folding_preset="bare"),
            folding_radius=RADIUS,
        )
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        self.assertEqual(len(result.layout.graph.generated), 1)
        apply_optimization(doc, problem, result)
        compiled = compile_schematic(doc)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        self.assertAlmostEqual(compiled.path_lengths["reflected-path"], 160, delta=1e-6)
        effective = effective_document(doc, result.layout.graph, problem.options)
        topology = __import__("PyOpticL.schematic", fromlist=["resolve_topology"]).resolve_topology(effective)
        assignments = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in ast.parse(compiled.source).body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        }
        positions = dict(result.layout.positions)
        for node in effective.nodes:
            if node.reference in assignments["PLACEMENTS"]:
                positions[node.id] = assignments["PLACEMENTS"][node.reference][:2]
        incoming = next(edge for edge in topology.edges.values() if edge.target.node_id == cube.id)
        a, b = positions[incoming.source.node_id], positions[cube.id]
        ax, ay = b[0] - a[0], b[1] - a[1]
        for edge in topology.outgoing[cube.id]:
            c = positions[edge.target.node_id]
            bx, by = c[0] - b[0], c[1] - b[1]
            measured = math.degrees(math.atan2(ax * by - ay * bx, ax * bx + ay * by))
            self.assertAlmostEqual(measured, 90 if edge.interaction == "reflected" else 0, delta=1e-6)

    def test_removal_uses_interior_angle_and_does_not_remove_turning_mirrors(self):
        doc, problem = removable_mirror()
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        self.assertEqual(result.layout.graph.bypassed, (doc.nodes[1].id,))
        self.assertNotIn(doc.nodes[1].id, result.layout.positions)
        apply_optimization(doc, problem, result)
        compiled = compile_schematic(doc)
        self.assertTrue(compiled.ok)
        self.assertNotIn("Circular_Mirror", compiled.source)
        self.assertIn("# Schematic mirrors omitted by optimization: 'M1'", compiled.source)
        self.assertAlmostEqual(compiled.path_lengths["path"], 100, delta=1e-6)
        doc.optimized_layout = None
        doc.nodes[1].mirror_role = "turning"
        # Preserve an ordinary feasible right-angle turn with no path target.
        doc.path_constraints.clear()
        doc.nodes[-1].physical.update(x=50, y=50)
        fixed = build_problem(doc, {doc.nodes[1].id: RADIUS}, problem.box, problem.options)
        result = optimize_layout(fixed)
        self.assertEqual(result.status, "feasible", result.violations)
        self.assertFalse(result.layout.graph.bypassed)
        self.assertIn(doc.nodes[1].id, result.layout.positions)

    def test_removal_threshold_is_not_the_direction_change(self):
        doc = chain("source", "mirror", "output")
        mirror = doc.nodes[1]
        mirror.mirror_role = "folding"
        problem = build_problem(
            doc,
            {mirror.id: 5},
            PackingBox(-100, -100, 300, 300),
            OptimizationOptions(starts=1, iterations=1000),
        )
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible")
        self.assertFalse(result.layout.graph.bypassed)  # a 90° interior angle is below 110°

    def test_cancellation_missing_bounds_and_progress_topology(self):
        doc, problem = fold_span()
        with self.assertRaisesRegex(ValueError, "folding mirror bounds"):
            build_problem(doc, {}, problem.box, problem.options)
        frames = []
        result = optimize_layout(problem, progress=frames.append)
        self.assertTrue(any(frame.problem.graph.generated for frame in frames))
        self.assertTrue(all(len(frame.positions) == len(frame.problem.nodes) for frame in frames))
        calls = []

        def cancelled():
            calls.append(True)
            return len(calls) > 12

        cancelled_result = optimize_layout(problem, cancelled=cancelled)
        self.assertEqual(cancelled_result.status, "cancelled")
        self.assertIsNone(cancelled_result.layout)

    def test_save_load_staleness_and_constraint_protects_omitted_endpoint(self):
        doc, problem = removable_mirror()
        history = History(doc)
        result = optimize_layout(problem)
        apply_optimization(doc, problem, result)
        history.commit(doc)
        self.assertIsNone(history.undo().optimized_layout)
        restored = history.redo()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "folded.json"
            save_schematic(restored, path)
            self.assertEqual(compile_schematic(load_schematic(path)).source, compile_schematic(doc).source)
        omitted = doc.nodes[1]
        doc.path_constraints.append(PathLengthConstraint("endpoint", doc.nodes[0].id, omitted.id, 50))
        self.assertFalse(compile_schematic(doc).ok)
        self.assertIn("stale", compile_schematic(doc).diagnostics[0].message)
        self.assertIsNotNone(folding_protection(doc, omitted.id))
        doc.optimized_layout = None
        self.assertFalse(any("stale" in item.message for item in compile_schematic(doc).diagnostics))
        self.assertEqual(len(doc.nodes), 3)

    def test_legacy_optimization_is_preserved_but_stale(self):
        doc, problem = fold_span()
        apply_optimization(doc, problem, optimize_layout(problem))
        data = doc.to_dict()
        for key in ("graph", "input_version", "folding_radius"):
            data["optimized_layout"].pop(key)
        from PyOpticL.schematic.model import document_from_dict

        loaded = document_from_dict(data)
        self.assertIsNotNone(loaded.optimized_layout)
        self.assertIn("format upgrade", compile_schematic(loaded).diagnostics[0].message)

    def test_version_four_snapshot_requires_revalidation_even_with_new_fields(self):
        doc = chain("source", "output")
        problem = build_problem(
            doc, {}, PackingBox(-20, -20, 150, 100), OptimizationOptions(starts=1, iterations=5)
        )
        apply_optimization(doc, problem, optimize_layout(problem))
        data = doc.to_dict()
        data["version"] = 4
        from PyOpticL.schematic.model import document_from_dict

        loaded = document_from_dict(data)
        self.assertEqual(loaded.optimized_layout["geometry"], data["optimized_layout"]["geometry"])
        self.assertIn("format upgrade", compile_schematic(loaded).diagnostics[0].message)


if __name__ == "__main__":
    unittest.main()
