"""Physical scenes, finite return passes and independent ray/constraint checks."""

import ast
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
from PyOpticL.schematic.model import document_from_dict
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_layout import initialize_layout, trace_scene
from PyOpticL.schematic.scene_solver import solve_scene, analyze_constraints
from PyOpticL.schematic.topology import resolve_topology
from PyOpticL.ray_math import add, mul, reflect, unit, heading


def double_pass(vertical=False):
    doc = Schematic("Vertical return" if vertical else "Horizontal return")
    kinds = ("source", "lens", "qwp", "roof", "mirror", "output")
    nodes = [doc.add_node(kind) for kind in kinds]
    for i, n in enumerate(nodes):
        n.id = f"part-{i}"
    source, lens, plate, roof, pickoff, output = nodes
    for n in (lens, plate, pickoff):
        select_preset(n, "bare")
    select_preset(roof, "bare_vertical" if vertical else "bare_horizontal")
    roof.parameters["beam_separation"] = 5.0
    lens.parameters["focal_length"] = 100.0
    pickoff.parameters.update(diameter=2, thickness=0.5)
    back_plate = doc.add_pass(plate.id)
    back_plate.id = "plate-return"
    back_lens = doc.add_pass(lens.id)
    back_lens.id = "lens-return"
    visits = (source.id, lens.id, plate.id, roof.id, back_plate.id, back_lens.id, pickoff.id, output.id)
    for i, (a, b) in enumerate(zip(visits, visits[1:])):
        ap, bp = doc.optical_pass(a), doc.optical_pass(b)
        pa = "beam" if ap.mode == "emit" else "A" if a in ("plate-return", "lens-return") else "B"
        pb = "beam" if bp.mode == "receive" else "B" if b in ("plate-return", "lens-return") else "A"
        doc.connections.append(
            Connection(
                f"beam-{i}",
                Endpoint(ap.component_id, pa, "" if a == ap.component_id else a),
                Endpoint(bp.component_id, pb, "" if b == bp.component_id else b),
            )
        )
    incoming = unit((-1, 0, -0.05)) if vertical else unit((-1, 0.05, 0))
    pick = (25.0, 0.0, 3.75) if vertical else (25.0, -3.75, 0.0)
    out = reflect(incoming, unit((1, -1, 0)))
    end = add(pick, mul(out, 50))
    doc.layout = {
        "poses": {
            source.id: [0.0, 0.0, 0.0, 0.0],
            lens.id: [50.0, 0.0, 0.0, 0.0],
            plate.id: [100.0, 0.0, 0.0, 0.0],
            roof.id: [200.0, 0.0, 0.0, 0.0],
            pickoff.id: [*pick, -45.0],
            output.id: [*end, 0.0],
        },
        "projection": "XZ" if vertical else "XY",
        "splitters": {},
    }
    return doc


class MultipassTests(unittest.TestCase):
    def test_shared_parts_resolve_finite_pass_tree_and_actual_hits(self):
        for vertical in (False, True):
            doc = double_pass(vertical)
            topology = resolve_topology(doc)
            self.assertTrue(topology.ok, topology.diagnostics)
            self.assertEqual(len(topology.order), 8)
            trace = trace_scene(doc)
            self.assertTrue(
                trace.ok,
                [(r.id, r.value) for r in trace.residuals if abs(r.value) > 1e-6] + trace.diagnostics,
            )
            self.assertEqual(len(trace.layout.poses), 6)
            self.assertEqual(len(trace.layout.visits), 8)
            first = trace.layout.visits["part-1"]
            back = trace.layout.visits["lens-return"]
            self.assertAlmostEqual(first.entry[1 if not vertical else 2], 0.0)
            self.assertAlmostEqual(back.entry[1 if not vertical else 2], -5.0 if not vertical else 5.0)
            outgoing = back.outputs["out"]
            self.assertAlmostEqual(abs(outgoing[1 if not vertical else 2] / outgoing[0]), 0.05)
            self.assertAlmostEqual(trace.layout.visits["part-3"].internal_length, 25.4)
            result = compile_schematic(doc)
            self.assertTrue(result.ok, result.diagnostics)
            ast.parse(result.source)
            self.assertEqual(result.source.count(" = Component("), 4)

    def test_path_between_two_passes_of_one_component(self):
        doc = double_pass()
        trace = trace_scene(doc)
        target = 50 + 100 + 100 + 50 + 25.4
        doc.path_constraints.append(
            PathLengthConstraint("roundtrip", "part-1", "part-1", target, "part-1", "lens-return")
        )
        self.assertTrue(trace_scene(doc).ok)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "shared.json"
            save_schematic(doc, path)
            restored = load_schematic(path)
            self.assertEqual(restored.to_dict(), doc.to_dict())
            self.assertTrue(compile_schematic(restored).ok)

    def test_legacy_file_migration_preserves_constraints_and_does_not_rewrite_file(self):
        import json
        from test_schematic import chain

        legacy = chain("source", "mirror", "output")
        legacy.nodes[0].physical.update(x=10, y=20, angle=30)
        legacy.nodes[1].physical["turn"] = 70
        legacy.connections[0].length = 60
        legacy.connections[1].bends = [(20, 40)]
        raw = legacy.to_dict()
        raw["version"] = 5
        with TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.json"
            text = json.dumps(raw)
            path.write_text(text)
            restored = load_schematic(path)
            self.assertEqual(path.read_text(), text)
            self.assertEqual(restored.version, 6)
            self.assertEqual(restored.nodes[0].physical, legacy.nodes[0].physical)
            self.assertEqual(restored.optical_pass(restored.nodes[1].id).turn, 70)
            self.assertEqual(restored.connections[0].length, 60)
            self.assertEqual(restored.connections[1].bends, [])
            self.assertTrue(restored.layout["notes"])
            self.assertTrue(compile_schematic(restored).ok)
            raw["connections"][0]["turns"] = {legacy.nodes[1].id: 40}
            path.write_text(json.dumps(raw))
            conflict = load_schematic(path)
            self.assertEqual(conflict.nodes[1].physical["turn"], 70)
            self.assertFalse(compile_schematic(conflict).ok)
            self.assertTrue(
                any("conflicting angle" in d.message for d in compile_schematic(conflict).diagnostics)
            )

    def test_live_drag_preserves_constraints_and_shared_geometry(self):
        doc = double_pass()
        doc.nodes[0].physical.update(x=0, y=0, angle=0)
        doc.connections[0].length = 50
        before = deepcopy(doc.to_dict())
        result = solve_scene(doc, targets=(("part-3", 0, 210.0),), iterations=100)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertAlmostEqual(result.poses["part-3"][0], 210.0, delta=1e-6)
        self.assertEqual(doc.to_dict(), before)
        self.assertAlmostEqual(result.layout.lengths["beam-0"], 50.0, delta=1e-6)

    def test_redundant_constraints_warn_without_blocking_export(self):
        doc = double_pass()
        doc.nodes[0].physical.update(x=0, y=0, angle=0)
        doc.nodes[1].physical["x"] = 50
        doc.connections[0].length = 50
        result = compile_schematic(doc)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertTrue(any(d.severity == "warning" for d in result.diagnostics))

    def test_conflicts_and_unexpected_pickoff_interceptions_block_export(self):
        doc = double_pass()
        doc.connections[0].length = 70
        doc.nodes[0].physical.update(x=0, y=0, angle=0)
        doc.nodes[1].physical["x"] = 50
        result = solve_scene(doc, iterations=30)
        self.assertFalse(result.ok)
        self.assertTrue(any("beam length" in d.message for d in result.diagnostics))
        doc = double_pass()
        doc.layout["poses"]["part-4"][1] = 0
        doc.layout["poses"]["part-4"][3] = 135
        self.assertTrue(any("unexpected interception" in d.message for d in trace_scene(doc).diagnostics))

    def test_deleting_pass_does_not_delete_shared_component(self):
        doc = double_pass()
        doc.remove_pass("lens-return")
        self.assertEqual(len(doc.nodes), 6)
        self.assertEqual(len(doc.passes), 1)
        self.assertFalse(resolve_topology(doc).ok)

    def test_cycles_are_checked_on_visits_not_components(self):
        doc = double_pass()
        self.assertTrue(resolve_topology(doc).ok)
        doc.connections.append(Connection("cycle", Endpoint("part-5", "beam"), Endpoint("part-0", "beam")))
        self.assertTrue(any("Cycle" in d.message for d in resolve_topology(doc).diagnostics))


if __name__ == "__main__":
    unittest.main()
