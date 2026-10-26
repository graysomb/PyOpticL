"""Physical position pins coexist with hard lengths and routing angles."""

import ast
from copy import deepcopy
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyOpticL.schematic import History, compile_schematic, load_schematic, save_schematic
from test_schematic import branched, chain


class PositionTests(unittest.TestCase):
    def test_pinned_optic_adjusts_free_length_and_downstream_positions(self):
        document = chain("source", "mirror", "stop")
        mirror = document.nodes[1]
        mirror.physical.update(x=75, y=0)
        before = deepcopy(document.to_dict())
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(result.placements["M1"][:2], (75, 0))
        self.assertEqual(result.placements["D1"][:2], (75, 50))
        self.assertEqual(result.lengths[document.connections[0].id], 75)
        self.assertEqual(document.to_dict(), before)
        mirror.physical.clear()
        self.assertEqual(compile_schematic(document).placements["M1"][:2], (50, 0))

    def test_downstream_anchor_resolves_multiple_upstream_lengths(self):
        document = chain("source", "mirror", "stop")
        document.nodes[-1].physical.update(x=120, y=80)
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(result.placements["M1"][:2], (120, 0))
        self.assertEqual(result.placements["D1"][:2], (120, 80))
        self.assertEqual([result.lengths[edge.id] for edge in document.connections], [120, 80])

    def test_shared_splitter_trunk_and_both_pinned_branches(self):
        document = branched()
        document.nodes[-1].physical.update(x=120, y=80)
        document.nodes[-2].physical.update(x=200, y=0)
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(result.placements["BS1"][:2], (120, 0))
        self.assertEqual(result.placements["FO1"][:2], (200, 0))
        self.assertEqual(result.placements["D1"][:2], (120, 80))
        for edge, expected in zip(document.connections, (60, 60, 80, 80)):
            self.assertAlmostEqual(result.lengths[edge.id], expected)
        document.nodes[2].physical.update(x=120, y=0)  # Redundant, compatible pin.
        self.assertTrue(compile_schematic(document).ok)

    def test_fixed_lengths_are_preserved_and_conflicts_locate_the_optic(self):
        document = chain("source", "lens", "stop")
        lens = document.nodes[1]
        document.connections[0].length = 75
        lens.physical.update(x=75, y=0)
        self.assertTrue(compile_schematic(document).ok)
        lens.physical["x"] = 80
        result = compile_schematic(document)
        self.assertFalse(result.ok)
        self.assertFalse(result.source)
        self.assertTrue(any(item.node_id == lens.id and "conflicts" in item.message for item in result.diagnostics))
        self.assertEqual(document.connections[0].length, 75)

    def test_off_ray_and_inconsistent_pins_block_export(self):
        document = chain("source", "lens", "stop")
        document.nodes[1].physical.update(x=50, y=10)
        self.assertFalse(compile_schematic(document).ok)
        document.nodes[1].physical.update(x=100, y=0)
        document.nodes[-1].physical.update(x=50, y=0)
        result = compile_schematic(document)
        self.assertFalse(result.ok)
        self.assertTrue(any("positive beam lengths" in item.message for item in result.diagnostics))

    def test_fractional_turn_and_rotated_source_are_respected(self):
        document = chain("source", "mirror", "stop")
        document.nodes[1].physical["turn"] = 60
        document.nodes[-1].physical.update(x=100, y=50)
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertAlmostEqual(result.placements["M1"][0], 100 - 50 / math.sqrt(3), places=7)
        self.assertAlmostEqual(result.placements["D1"][0], 100, places=7)
        self.assertAlmostEqual(result.placements["D1"][1], 50, places=7)
        document = chain("fiber_source", "mirror", "stop")
        document.nodes[0].physical.update(x=10, y=20, angle=90)
        document.nodes[1].physical.update(x=10, y=95)
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(result.placements["FI1"][:2], (10, 20))
        self.assertEqual(result.placements["M1"][:2], (10, 95))
        self.assertEqual(result.placements["D1"][:2], (-40, 95))

    def test_positive_solution_when_nearest_unbounded_solution_is_negative(self):
        document = chain("source", "lens", "output")
        document.settings["open_length"] = 100
        document.nodes[-1].physical.update(x=10, y=0)
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertAlmostEqual(result.placements["O1"][0], 10, places=6)
        self.assertTrue(all(value > 0 for value in result.lengths.values()))
        self.assertAlmostEqual(sum(result.lengths.values()), 10, places=6)
        document.nodes[-1].physical["x"] = -1
        self.assertFalse(compile_schematic(document).ok)

    def test_open_output_exports_solved_length_for_runtime(self):
        document = chain("source", "output")
        document.nodes[-1].physical.update(x=125, y=0)
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        lengths = next(ast.literal_eval(node.value) for node in ast.parse(result.source).body
                       if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                       and node.targets[0].id == "OPEN_LENGTHS")
        self.assertEqual(lengths, {("S1", "out"): 125})

    def test_positions_ignore_drawing_and_connection_storage_order(self):
        document = chain("source", "mirror", "stop")
        document.nodes[-1].physical.update(x=75, y=120)
        before = compile_schematic(document)
        for edge in document.connections:
            edge.a, edge.b = edge.b, edge.a
            edge.bends = [(100, 200), (200, 400)]
        for node in document.nodes:
            node.position = (1000, 1000)
            node.rotation = 90
        document.connections.reverse()
        self.assertEqual(compile_schematic(document).source, before.source)

    def test_persistence_history_duplicate_and_unfinished_drawing(self):
        document = chain("source", "lens", "stop")
        lens = document.nodes[1]
        history = History(document)
        lens.physical.update(x=80, y=0)
        history.commit(document)
        self.assertFalse(history.undo().node(lens.id).physical)
        self.assertEqual(history.redo().node(lens.id).physical, {"x": 80, "y": 0})
        with TemporaryDirectory() as directory:
            path = Path(directory) / "position.json"
            save_schematic(document, path)
            self.assertEqual(load_schematic(path).to_dict(), document.to_dict())
            document.connections.clear()
            save_schematic(document, path)
            self.assertEqual(load_schematic(path).node(lens.id).physical, lens.physical)
        duplicate = document.duplicate_nodes([lens.id])[0]
        duplicate.physical["x"] = 100
        self.assertEqual(lens.physical["x"], 80)

    def test_partial_axis_pins_and_invalid_coordinates(self):
        document = chain("source", "mirror", "stop")
        document.nodes[-1].physical["x"] = 75
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(result.placements["D1"][:2], (75, 50))
        for value in (True, "75", float("nan"), float("inf")):
            document.nodes[-1].physical["x"] = value
            self.assertFalse(compile_schematic(document).ok)


if __name__ == "__main__":
    unittest.main()
