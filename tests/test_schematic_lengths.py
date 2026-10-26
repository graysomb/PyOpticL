"""Physical length constraints belong to connections, independently of direction."""

import ast
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PyOpticL.schematic import compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.model import connection_length, document_from_dict, migrate_legacy_lengths
from PyOpticL.schematic.runtime import check_trace
from test_schematic import branched, chain, connect


class BeamLengthTests(unittest.TestCase):
    def test_length_moves_downstream_parts_and_clearing_restores_default(self):
        document = chain("source", "lens", "stop")
        document.connections[0].length = 75
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(result.placements["L1"][:2], (75, 0))
        self.assertEqual(result.placements["D1"][:2], (125, 0))
        self.assertFalse(document.nodes[1].physical)
        document.connections[0].length = None
        self.assertEqual(compile_schematic(document).placements["L1"][:2], (50, 0))
        document.settings["spacing"] = 90
        self.assertEqual(connection_length(document, document.connections[0]), 90)
        self.assertEqual(compile_schematic(document).placements["D1"][:2], (180, 0))

    def test_constraint_survives_endpoint_reversal_bends_and_drawing_edits(self):
        document = chain("source", "mirror", "stop")
        document.connections[0].length = 75
        document.connections[1].length = 120
        before = compile_schematic(document)
        for edge in document.connections:
            edge.a, edge.b = edge.b, edge.a
            edge.bends = [(20, 60), (140, -90)]
        for node in document.nodes:
            node.position = (400, 600)
            node.rotation = 180
        after = compile_schematic(document)
        self.assertEqual(before.source, after.source)
        self.assertEqual(after.placements["D1"][:2], (75, 120))

    def test_splitter_branches_have_independent_constraints(self):
        document = branched()
        document.connections[-2].length = 80
        document.connections[-1].length = 120
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(result.placements["FO1"][:2], (180, 0))
        self.assertEqual(result.placements["D1"][:2], (100, 120))

    def test_invalid_lengths_block_export_with_connection_diagnostic(self):
        for value in (0, -10):
            document = chain("source", "stop")
            document.connections[0].length = value
            result = compile_schematic(document)
            self.assertFalse(result.ok)
            self.assertTrue(any(item.connection_id == document.connections[0].id for item in result.diagnostics))
        for value in ("75", True, float("nan"), float("inf")):
            document = chain("source", "stop")
            document.connections[0].length = value
            self.assertFalse(compile_schematic(document).ok)

    def test_save_load_and_history_keep_optional_beam_lengths(self):
        from PyOpticL.schematic import History

        document = chain("source", "lens", "stop")
        history = History(document)
        document.connections[0].length = 85
        history.commit(document)
        self.assertIsNone(history.undo().connections[0].length)
        self.assertEqual(history.redo().connections[0].length, 85)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "beam.json"
            save_schematic(document, path)
            loaded = load_schematic(path)
            self.assertEqual(loaded.to_dict(), document.to_dict())
            self.assertEqual(loaded.connections[0].length, 85)
            self.assertIsNone(loaded.connections[1].length)

    def test_v2_node_distance_migrates_to_resolved_beam_in_either_storage_order(self):
        for reverse in (False, True):
            document = chain("source", "mirror", "stop")
            document.nodes[1].physical.update(distance=75, turn=-90)
            document.nodes[-1].physical["distance"] = 120
            if reverse:
                for edge in document.connections:
                    edge.a, edge.b = edge.b, edge.a
            data = document.to_dict()
            data["version"] = 2
            for edge in data["connections"]:
                edge.pop("length")
            original = deepcopy(data)
            migrated = document_from_dict(data)
            self.assertEqual(data, original, "Migration must not mutate the original file data")
            self.assertEqual(migrated.version, 3)
            self.assertEqual([edge.length for edge in migrated.connections], [75, 120])
            self.assertEqual(migrated.nodes[1].physical, {"turn": -90})
            self.assertEqual(compile_schematic(migrated).placements["D1"][:2], (75, -120))

    def test_unresolved_legacy_distance_is_preserved_until_source_is_connected(self):
        document = chain("lens", "stop")
        document.nodes[0].physical["distance"] = 80
        data = document.to_dict()
        data["version"] = 2
        loaded = document_from_dict(data)
        self.assertEqual(loaded.nodes[0].physical["distance"], 80)
        self.assertIsNone(loaded.connections[0].length)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unfinished.json"
            save_schematic(loaded, path)
            loaded = load_schematic(path)
            self.assertEqual(loaded.nodes[0].physical["distance"], 80)
        source = loaded.add_node("source")
        edge = connect(loaded, source, loaded.nodes[0])
        migrate_legacy_lengths(loaded)
        self.assertEqual(edge.length, 80)
        self.assertNotIn("distance", loaded.nodes[0].physical)
        self.assertTrue(compile_schematic(loaded).ok)

    def test_explicit_beam_constraint_takes_precedence_over_legacy_node_distance(self):
        document = chain("source", "stop")
        document.connections[0].length = 90
        document.nodes[-1].physical["distance"] = 75
        migrated = document_from_dict(document.to_dict())
        self.assertEqual(migrated.connections[0].length, 90)
        self.assertNotIn("distance", migrated.nodes[-1].physical)

    def test_open_lengths_use_constraints_and_export_runtime_settings(self):
        document = branched()
        document.nodes[-2].kind = "output"
        document.nodes[-2].preset = "open"
        document.nodes[-1].kind = "output"
        document.nodes[-1].preset = "open"
        document.connections[-2].length = 80
        document.connections[-1].length = 120
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        lengths = next(ast.literal_eval(node.value) for node in ast.parse(result.source).body
                       if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                       and node.targets[0].id == "OPEN_LENGTHS")
        self.assertEqual(lengths, {("BS1", "transmitted"): 80, ("BS1", "reflected"): 120})
        document.connections[-2].length = None
        document.settings["open_length"] = 65
        self.assertEqual(connection_length(document, document.connections[-2]), 65)


class OpenLengthRuntimeTests(unittest.TestCase):
    def test_open_branch_lengths_are_applied_independently_after_trace_validation(self):
        cube = SimpleNamespace(Name="cube", Label="BS1")
        objects = {"BS1": SimpleNamespace(get_object=lambda: cube)}
        proxies = []
        segments = []
        for start, end, direction in ((None, cube, (1, 0, 0)), (cube, None, (1, 0, 0)), (cube, None, (0, 1, 0))):
            proxy = SimpleNamespace(get_global_direction=lambda d=direction: d, distance=50, recompute=Mock())
            proxies.append(proxy)
            segments.append(SimpleNamespace(StartObject=start, EndObject=end, Proxy=proxy))
        beam = SimpleNamespace(get_object=lambda: SimpleNamespace(BeamSegments=segments))
        expected = [("S1", "out", "BS1"), ("BS1", "transmitted", None), ("BS1", "reflected", None)]
        self.assertTrue(check_trace(beam, objects, expected, "S1", ["BS1"],
                                    {("BS1", "transmitted"): 80, ("BS1", "reflected"): 120}))
        self.assertEqual([proxy.distance for proxy in proxies], [50, 80, 120])
        proxies[0].recompute.assert_not_called()
        proxies[1].recompute.assert_called_once()
        proxies[2].recompute.assert_called_once()
        for invalid in (0, -5, float("nan")):
            with self.assertRaises(ValueError):
                check_trace(beam, objects, expected, "S1", ["BS1"], {("BS1", "reflected"): invalid})


if __name__ == "__main__":
    unittest.main()
