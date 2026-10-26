"""Total routed lengths, including ordinary non-optimizer generation."""

from copy import deepcopy
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
from PyOpticL.schematic.model import document_from_dict
from PyOpticL.schematic.paths import component_path, path_length
from test_schematic import branched, chain


class PathLengthTests(unittest.TestCase):
    def test_ordinary_export_adjusts_free_lengths_and_keeps_fixed_lengths(self):
        doc = chain("source", "mirror", "lens", "output")
        doc.connections[0].length = 30
        doc.path_constraints.append(PathLengthConstraint("p", doc.nodes[0].id, doc.nodes[-1].id, 150))
        before = deepcopy(doc.to_dict())
        result = compile_schematic(doc)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(result.lengths[doc.connections[0].id], 30)
        self.assertEqual([result.lengths[edge.id] for edge in doc.connections[1:]], [60, 60])
        self.assertEqual(result.path_lengths, {"p": 150})
        self.assertEqual(doc.to_dict(), before)
        self.assertIsNone(doc.connections[1].length)

    def test_overlapping_paths_and_position_pins(self):
        doc = chain("source", "lens", "lens", "output")
        a, b, c, d = doc.nodes
        doc.path_constraints = [
            PathLengthConstraint("ac", a.id, c.id, 100),
            PathLengthConstraint("bd", b.id, d.id, 120),
        ]
        b.physical["x"] = 30
        result = compile_schematic(doc)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual([result.lengths[edge.id] for edge in doc.connections], [30, 70, 50])
        self.assertEqual(result.path_lengths, {"ac": 100, "bd": 120})
        doc.connections[1].length = 80
        result = compile_schematic(doc)
        self.assertFalse(result.ok)
        self.assertTrue(any(item.constraint_id for item in result.diagnostics))

    def test_cross_branch_route_is_direction_independent_and_excludes_shared_trunk(self):
        doc = branched()
        a, b = doc.nodes[-2:]
        route = component_path(doc, a.id, b.id)
        self.assertEqual(route, tuple(edge.id for edge in doc.connections[-2:]))
        doc.path_constraints = [PathLengthConstraint("p", b.id, a.id, 120)]
        result = compile_schematic(doc)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(result.path_lengths["p"], 120)
        self.assertEqual(result.lengths[doc.connections[0].id], 50)
        self.assertEqual(result.lengths[doc.connections[1].id], 50)
        for edge in doc.connections:
            edge.a, edge.b = edge.b, edge.a
        doc.connections.reverse()
        for node in doc.nodes:
            node.reference += "renamed"
        self.assertEqual(compile_schematic(doc).path_lengths, {"p": 120})

    def test_disconnected_constraint_is_saveable_and_diagnostic_locates_constraint(self):
        doc = chain("source", "lens", "output")
        doc.path_constraints.append(PathLengthConstraint("p", doc.nodes[0].id, doc.nodes[-1].id, 150))
        doc.connections.pop()
        self.assertFalse(compile_schematic(doc).ok)
        self.assertTrue(any(item.constraint_id == "p" for item in compile_schematic(doc).diagnostics))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unfinished.json"
            save_schematic(doc, path)
            self.assertEqual(load_schematic(path).path_constraints, doc.path_constraints)
        with self.assertRaisesRegex(ValueError, "No connected path"):
            component_path(doc, doc.nodes[0].id, doc.nodes[-1].id)

    def test_conflicting_fixed_and_path_lengths_are_not_relaxed(self):
        doc = chain("source", "output")
        doc.connections[0].length = 100
        doc.path_constraints.append(PathLengthConstraint("p", doc.nodes[0].id, doc.nodes[1].id, 120))
        result = compile_schematic(doc)
        self.assertFalse(result.ok)
        self.assertEqual(result.diagnostics[0].constraint_id, "p")
        self.assertEqual(doc.connections[0].length, 100)

    def test_validation_deletion_and_history(self):
        doc = chain("source", "mirror", "output")
        doc.nodes[1].mirror_role = "folding"
        doc.connections[0].allow_folding = True
        doc.path_constraints.append(PathLengthConstraint("p", doc.nodes[0].id, doc.nodes[-1].id, 120))
        history = History(doc)
        doc.remove_nodes([doc.nodes[-1].id])
        self.assertFalse(doc.path_constraints)
        history.commit(doc)
        restored = history.undo()
        self.assertEqual(restored.path_constraints[0].length_mm, 120)
        self.assertEqual(restored.nodes[1].mirror_role, "folding")
        self.assertTrue(restored.connections[0].allow_folding)
        original = restored.to_dict()
        for key, value in (
            ("length_mm", 0),
            ("length_mm", True),
            ("length_mm", float("nan")),
            ("component_a", "missing"),
            ("component_a", restored.nodes[-1].id),
            ("id", False),
        ):
            data = deepcopy(original)
            data["path_constraints"][0][key] = value
            with self.assertRaises(ValueError):
                document_from_dict(data)
        duplicate = deepcopy(original)
        duplicate["path_constraints"].append({**duplicate["path_constraints"][0], "id": "another"})
        with self.assertRaises(ValueError):
            document_from_dict(duplicate)
        for version in (1, 2, 3, 4):
            # v1 endpoint migration is already covered by the legacy fixtures.
            if version == 1:
                continue
            data = deepcopy(original)
            data["version"] = version
            loaded = document_from_dict(data)
            self.assertEqual(loaded.version, 5)
            self.assertFalse(loaded.path_constraints)
            self.assertEqual(loaded.nodes[1].mirror_role, "turning")
            self.assertFalse(any(edge.allow_folding for edge in loaded.connections))


if __name__ == "__main__":
    unittest.main()
