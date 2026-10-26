"""Angle constraints belong to reflecting optics; older beam angles still load."""

from copy import deepcopy
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from PyOpticL.schematic import (
    Endpoint, History, compile_schematic, load_schematic, save_schematic,
)
from PyOpticL.schematic.geometry import apply_drawing_directions
from PyOpticL.schematic.model import document_from_dict
from PyOpticL.schematic.registry import REFLECTION, TRANSMISSION, default_turn
from PyOpticL.schematic.runtime import check_trace
from test_schematic import branched, chain, connect


class BeamAngleTests(unittest.TestCase):
    def assert_reflection(self, heading, normal, turn):
        direction = (math.cos(math.radians(heading)), math.sin(math.radians(heading)))
        normal = (math.cos(math.radians(normal)), math.sin(math.radians(normal)))
        dot = sum(d * n for d, n in zip(direction, normal))
        reflected = tuple(d - 2 * dot * n for d, n in zip(direction, normal))
        self.assertAlmostEqual(reflected[0], math.cos(math.radians(heading + turn)))
        self.assertAlmostEqual(reflected[1], math.sin(math.radians(heading + turn)))

    def test_continuous_mirror_turn_from_either_beam_and_port(self):
        for incident in ("A", "B"):
            for index in (None, 0, 1):
                for turn in (-157.25, -60, 37.5, 120.125):
                    with self.subTest(incident=incident, edge=index, turn=turn):
                        document = chain("source", "mirror", "stop")
                        source, mirror, stop = document.nodes
                        source.physical["angle"] = 23
                        document.connections[0].b = Endpoint(mirror.id, incident)
                        document.connections[1].a = Endpoint(mirror.id, "B" if incident == "A" else "A")
                        if index is None:
                            mirror.physical["turn"] = turn
                        else:
                            document.connections[index].turns[mirror.id] = turn
                        document.connections[1].length = 75
                        result = compile_schematic(document)
                        self.assertTrue(result.ok, result.diagnostics)
                        self.assert_reflection(23, result.placements[mirror.reference][2], turn)
                        mx, my, _ = result.placements[mirror.reference]
                        sx, sy, _ = result.placements[stop.reference]
                        self.assertAlmostEqual(sx - mx, 75 * math.cos(math.radians(23 + turn)), places=7)
                        self.assertAlmostEqual(sy - my, 75 * math.sin(math.radians(23 + turn)), places=7)

    def test_splitter_angles_from_all_faces_preserve_transmission(self):
        for face in TRANSMISSION:
            for turn in (-123.5, -60, 32.25, 145):
                for constrained_index in (None, 0, 2):
                    with self.subTest(face=face, turn=turn, edge=constrained_index):
                        document = chain("source", "splitter")
                        source, cube = document.nodes
                        source.physical["angle"] = -17
                        document.connections[0].b = Endpoint(cube.id, face)
                        straight = document.add_node("stop")
                        reflected = document.add_node("stop")
                        connect(document, cube, straight, TRANSMISSION[face])
                        connect(document, cube, reflected, REFLECTION[face])
                        if constrained_index is None:
                            cube.physical["turn"] = turn
                        else:
                            document.connections[constrained_index].turns[cube.id] = turn
                        result = compile_schematic(document)
                        self.assertTrue(result.ok, result.diagnostics)
                        rotated = (turn > 0) != (default_turn("splitter", face) > 0)
                        self.assertIn(f"rotate_cube={rotated}", result.source)
                        bx, by, rotation = result.placements[cube.reference]
                        normal = rotation + (45 if rotated else -45)
                        self.assert_reflection(-17, normal, turn)
                        for node, heading in ((straight, -17), (reflected, -17 + turn)):
                            x, y, _ = result.placements[node.reference]
                            self.assertAlmostEqual(x - bx, 50 * math.cos(math.radians(heading)), places=7)
                            self.assertAlmostEqual(y - by, 50 * math.sin(math.radians(heading)), places=7)

    def test_both_endpoints_can_constrain_different_interfaces(self):
        document = chain("source", "mirror", "mirror", "stop")
        first, second = document.nodes[1:3]
        first.physical["turn"] = 60
        second.physical["turn"] = -30
        before = compile_schematic(document)
        self.assertTrue(before.ok, before.diagnostics)
        self.assertAlmostEqual(before.placements["D1"][0], 75 + 50 * math.cos(math.radians(30)), places=7)
        self.assertAlmostEqual(before.placements["D1"][1], 50 * math.sin(math.radians(60)) + 25, places=7)
        for connection in document.connections:
            connection.a, connection.b = connection.b, connection.a
            connection.bends = [(1000, 2000)]
        for node in document.nodes:
            node.position = (50, 100)
            node.rotation = 135
        self.assertEqual(compile_schematic(document).source, before.source)

    def test_conflicting_legacy_constraints_locate_the_optic_and_matching_ones_work(self):
        document = chain("source", "mirror", "stop")
        mirror = document.nodes[1]
        for edge, value in zip(document.connections, (60, -60)):
            edge.turns[mirror.id] = value
        result = compile_schematic(document)
        self.assertFalse(result.ok)
        conflicts = [item for item in result.diagnostics if "conflicting" in item.message]
        self.assertEqual([item.node_id for item in conflicts], [mirror.id])
        self.assertIsNone(conflicts[0].connection_id)
        document.connections[1].turns[mirror.id] = 60
        self.assertTrue(compile_schematic(document).ok)

    def test_straight_interfaces_and_transmitted_branch_reject_turns(self):
        for kind in ("lens", "iris", "hwp", "qwp", "fiber_output", "stop", "output"):
            document = chain("source", kind, "stop") if kind in ("lens", "iris", "hwp", "qwp") else chain("source", kind)
            document.connections[0].turns[document.nodes[1].id] = 45
            result = compile_schematic(document)
            self.assertFalse(result.ok)
            self.assertTrue(any("cannot turn" in item.message and item.node_id == document.nodes[1].id
                                for item in result.diagnostics))
        document = branched()
        document.connections[-2].turns[document.nodes[2].id] = 45
        result = compile_schematic(document)
        self.assertFalse(result.ok)
        self.assertTrue(any("cannot turn" in item.message for item in result.diagnostics))

    def test_invalid_angles_and_endpoint_mappings(self):
        for value in (0, 0.00001, -180, 180, 360, True, "60", None, float("inf"), float("nan")):
            document = chain("source", "mirror", "stop")
            document.connections[0].turns[document.nodes[1].id] = value
            self.assertFalse(compile_schematic(document).ok, value)
            document.connections[0].turns.clear()
            document.nodes[1].physical["turn"] = value
            self.assertFalse(compile_schematic(document).ok, value)
        document = chain("source", "mirror", "stop")
        for turns in ([], {"missing": 60}, {document.nodes[2].id: 60}):
            data = document.to_dict()
            data["connections"][0]["turns"] = turns
            with self.assertRaises(ValueError):
                document_from_dict(data)

    def test_constraints_override_presets_and_survive_explicit_drawing_directions(self):
        document = chain("source", "mirror", "stop")
        mirror = document.nodes[1]
        mirror.physical["turn"] = -90
        document.connections[0].turns[mirror.id] = 61.25
        before = compile_schematic(document)
        apply_drawing_directions(document)
        self.assertEqual(mirror.physical["turn"], -90)
        self.assertEqual(document.connections[0].turns[mirror.id], 61.25)
        self.assertEqual(compile_schematic(document).placements, before.placements)
        document.connections[0].turns.clear()
        self.assertEqual(compile_schematic(document).placements["D1"][:2], (50, -50))
        mirror.physical["turn"] = 0  # A straight canvas route can leave this hint.
        document.connections[0].turns[mirror.id] = 61.25
        self.assertTrue(compile_schematic(document).ok)

    def test_save_load_undo_redo_and_older_files(self):
        document = chain("source", "mirror", "stop")
        history = History(document)
        document.connections[0].turns[document.nodes[1].id] = -67.5
        history.commit(document)
        self.assertEqual(history.undo().connections[0].turns, {})
        self.assertEqual(history.redo().connections[0].turns, document.connections[0].turns)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "angles.json"
            save_schematic(document, path)
            self.assertEqual(load_schematic(path).to_dict(), document.to_dict())
        old = deepcopy(document.to_dict())
        for edge in old["connections"]:
            edge.pop("turns")
        self.assertTrue(all(not edge.turns for edge in document_from_dict(old).connections))
        self.assertTrue(compile_schematic(document_from_dict(old)).ok)

    def test_optic_constraints_survive_history_save_duplicate_and_drawing_hints(self):
        for kind in ("mirror", "splitter"):
            document = chain("source", "mirror", "stop") if kind == "mirror" else branched()
            optic = next(node for node in document.nodes if node.kind == kind)
            history = History(document)
            optic.physical["turn"] = -67.5
            history.commit(document)
            self.assertNotIn("turn", history.undo().node(optic.id).physical)
            self.assertEqual(history.redo().node(optic.id).physical["turn"], -67.5)
            with TemporaryDirectory() as directory:
                path = Path(directory) / "optic.json"
                save_schematic(document, path)
                self.assertEqual(load_schematic(path).to_dict(), document.to_dict())
            before = compile_schematic(document)
            self.assertTrue(before.ok, before.diagnostics)
            apply_drawing_directions(document)
            self.assertEqual(optic.physical["turn"], -67.5)
            self.assertEqual(compile_schematic(document).placements, before.placements)
            copy = document.duplicate_nodes([optic.id])[0]
            self.assertEqual(copy.physical["turn"], -67.5)
            copy.physical["turn"] = 60
            self.assertEqual(optic.physical["turn"], -67.5)
            document.connections.clear()
            self.assertEqual(optic.physical["turn"], -67.5)

    def test_trace_distinguishes_small_reflected_turn_from_transmission(self):
        cube = SimpleNamespace(Name="cube", Label="BS1")
        straight = SimpleNamespace(Name="straight", Label="D1")
        reflected = SimpleNamespace(Name="reflected", Label="D2")
        objects = {obj.Label: SimpleNamespace(get_object=lambda obj=obj: obj)
                   for obj in (cube, straight, reflected)}
        for turn in (0.001, 0.05, -0.05, 60):
            direction = (math.cos(math.radians(turn)), math.sin(math.radians(turn)), 0)
            segments = [SimpleNamespace(StartObject=start, EndObject=end,
                                       Proxy=SimpleNamespace(get_global_direction=lambda d=d: d))
                        for start, end, d in ((None, cube, (1, 0, 0)), (cube, straight, (1, 1e-12, 0)),
                                              (cube, reflected, direction))]
            beam = SimpleNamespace(get_object=lambda: SimpleNamespace(BeamSegments=segments))
            expected = [("S1", "out", "BS1"), ("BS1", "transmitted", "D1"), ("BS1", "reflected", "D2")]
            self.assertTrue(check_trace(beam, objects, expected, "S1", ["BS1"]))


if __name__ == "__main__":
    unittest.main()
