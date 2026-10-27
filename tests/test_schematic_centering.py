"""Centered contacts are hard scene constraints, with explicit per-pass opt-outs."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyOpticL.schematic import compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.model import OpticalPass, document_from_dict
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_layout import trace_scene
from PyOpticL.schematic.scene_solver import solve_scene
from PyOpticL.ray_math import norm, sub
from test_schematic import chain
from test_schematic_multipass import double_pass


def coupler_scene():
    document = chain("fiber_source", "mirror", "fiber_output")
    source, mirror, receiver = document.nodes
    for node in (source, receiver):
        select_preset(node, "POLARIS-K05T6")
    select_preset(mirror, "bare")
    source.physical.update(x=0, y=0, angle=0)
    document.layout = {"poses": {
        source.id: [0, 0, 0, 0],
        mirror.id: [50, 0, 0, 135],
        receiver.id: [50, 50, 0, -90],
    }}
    return document


class CenteringTests(unittest.TestCase):
    def test_in_aperture_off_center_hits_block_validation_and_export(self):
        document = coupler_scene()
        self.assertTrue(trace_scene(document).ok)
        mirror = document.nodes[1]
        document.layout["poses"][mirror.id][1:3] = [2, 1]
        trace = trace_scene(document)
        self.assertFalse(trace.ok)
        self.assertTrue(all(r.value == 0 for r in trace.residuals if r.id.startswith("aperture/")))
        rows = [r for r in trace.residuals if r.id.startswith(f"center/{mirror.id}/")]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(abs(r.value) > 0.9 for r in rows))
        compiled = compile_schematic(document)
        self.assertFalse(compiled.ok)
        self.assertFalse(compiled.source)
        self.assertTrue(any("optical center" in d.message and d.node_id == mirror.id
                            for d in compiled.diagnostics))

    def test_solver_and_live_drag_keep_mirror_and_receiver_centered(self):
        document = coupler_scene()
        mirror = document.nodes[1]
        document.layout["poses"][mirror.id][1:3] = [2, 1]
        before = deepcopy(document.to_dict())
        solution = solve_scene(document, targets=((mirror.id, 0, 55),))
        self.assertTrue(solution.ok, solution.diagnostics)
        self.assertAlmostEqual(solution.poses[mirror.id][0], 55, delta=1e-6)
        for node in document.nodes[1:]:
            self.assertLess(norm(sub(solution.layout.visits[node.id].entry,
                                     solution.poses[node.id][:3])), 1e-6)
        self.assertEqual(document.to_dict(), before)

    def test_pins_cannot_be_satisfied_by_sliding_a_contact(self):
        document = coupler_scene()
        mirror = document.nodes[1]
        mirror.physical.update(x=50, y=2)
        solution = solve_scene(document, iterations=30)
        self.assertFalse(solution.ok)
        self.assertTrue(any("optical center" in d.message and d.node_id == mirror.id
                            for d in solution.diagnostics))
        self.assertEqual(solution.poses[mirror.id][:2], [50, 2])

    def test_intentional_return_offsets_are_explicit_and_apertures_still_apply(self):
        for vertical in (False, True):
            document = double_pass(vertical)
            self.assertTrue(trace_scene(document).ok)
            document.optical_pass("lens-return").centered = True
            self.assertFalse(trace_scene(document).ok)
            document.optical_pass("lens-return").centered = False
            self.assertTrue(compile_schematic(document).ok)
            document.node("part-1").parameters["diameter"] = 2
            self.assertFalse(trace_scene(document).ok)
            self.assertTrue(any(r.value > 0 for r in trace_scene(document).residuals
                                if r.id == "aperture/lens-return"))

    def test_centering_defaults_persist_and_reject_non_boolean_values(self):
        document = coupler_scene()
        mirror = document.nodes[1]
        self.assertTrue(document.optical_pass(mirror.id).centered)
        visit = OpticalPass(mirror.id, mirror.id, centered=False)
        document.passes.append(visit)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "centered.json"
            save_schematic(document, path)
            restored = load_schematic(path)
            self.assertFalse(restored.optical_pass(mirror.id).centered)
            self.assertEqual(restored.to_dict(), document.to_dict())
        raw = document.to_dict()
        del raw["passes"][0]["centered"]
        self.assertTrue(document_from_dict(raw).optical_pass(mirror.id).centered)
        for value in (0, 1, "false", None):
            raw["passes"][0]["centered"] = value
            with self.assertRaisesRegex(ValueError, "optical pass properties"):
                document_from_dict(raw)

    def test_changing_centering_invalidates_an_applied_optimization(self):
        from PyOpticL.schematic.optimization import (
            OptimizationOptions, PackingBox, apply_optimization, build_problem, optimize_layout,
        )

        document = coupler_scene()
        problem = build_problem(
            document, {n.id: 2 for n in document.nodes}, PackingBox(-50, -50, 200, 200),
            OptimizationOptions(starts=1, iterations=2, projection_passes=2),
        )
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        apply_optimization(document, problem, result)
        self.assertTrue(compile_schematic(document).ok)
        mirror = document.nodes[1]
        document.passes.append(OpticalPass(mirror.id, mirror.id, centered=False))
        compiled = compile_schematic(document)
        self.assertFalse(compiled.ok)
        self.assertTrue(any("stale" in d.message.lower() for d in compiled.diagnostics))
