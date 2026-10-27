"""Neutral-port propagation and compatibility regressions."""

import ast
from copy import deepcopy
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyOpticL.schematic import (
    Endpoint, compile_schematic, load_schematic, resolve_topology, save_schematic,
)
from PyOpticL.schematic.geometry import apply_drawing_directions, connection_points, port_position
from PyOpticL.schematic.model import document_from_dict
from PyOpticL.schematic.registry import REFLECTION, TRANSMISSION, SYMBOLS
from test_schematic import branched, chain, connect


class TopologyTests(unittest.TestCase):
    def test_every_two_port_optic_accepts_incidence_at_either_port(self):
        for kind in ("lens", "hwp", "qwp", "iris", "mirror"):
            for incident, exit_port in (("A", "B"), ("B", "A")):
                with self.subTest(kind=kind, incident=incident):
                    document = chain("source", kind, "stop")
                    optic = document.nodes[1]
                    document.connections[0].b = Endpoint(optic.id, incident)
                    document.connections[1].a = Endpoint(optic.id, exit_port)
                    topology = resolve_topology(document)
                    self.assertTrue(topology.ok, topology.diagnostics)
                    self.assertEqual(topology.incident_ports[optic.id], incident)
                    self.assertEqual(topology.outgoing[optic.id][0].source.port_id, exit_port)
                    result = compile_schematic(document)
                    self.assertTrue(result.ok, result.diagnostics)
                    if kind == "mirror":
                        expected_y = 50 if incident == "A" else -50
                        self.assertEqual(result.placements["D1"][:2], (50.0, expected_y))
                        normal = math.radians(result.placements["M1"][2])
                        self.assertLess(math.cos(normal), 0, "Mirror must face its actual incident ray")
                    else:
                        self.assertEqual(result.placements[optic.reference][2], 0 if incident == "A" else -180)

    def test_click_order_and_storage_order_do_not_affect_propagation(self):
        document = branched(nested=True)
        for index, edge in enumerate(document.connections):
            edge.bends = [(index * 20, 40), (index * 20, -80)]
        reverse = document_from_dict(document.to_dict())
        for edge in reverse.connections:
            edge.a, edge.b = edge.b, edge.a
            edge.bends.reverse()
        reverse.connections.reverse()
        before = compile_schematic(document)
        after = compile_schematic(reverse)
        self.assertTrue(before.ok, before.diagnostics)
        self.assertEqual(before.source, after.source)
        self.assertEqual(before.placements, after.placements)
        self.assertEqual(resolve_topology(document).edges, resolve_topology(reverse).edges)
        reverse_edges = {edge.id: edge for edge in reverse.connections}
        for edge in document.connections:
            self.assertEqual(connection_points(document, edge),
                             list(reversed(connection_points(reverse, reverse_edges[edge.id]))))
        apply_drawing_directions(document)
        apply_drawing_directions(reverse)
        self.assertEqual({n.id: n.physical for n in document.nodes}, {n.id: n.physical for n in reverse.nodes})

    def test_splitter_roles_and_physical_reflection_from_all_faces(self):
        for face in ("left", "right", "top", "bottom"):
            for heading in (0, 45, 180):
                with self.subTest(face=face, heading=heading):
                    document = chain("source", "splitter")
                    source, splitter = document.nodes
                    source.physical["angle"] = heading
                    document.connections[0].b = Endpoint(splitter.id, face)
                    transmitted = document.add_node("fiber_output")
                    reflected = document.add_node("stop")
                    connect(document, splitter, transmitted, TRANSMISSION[face])
                    connect(document, splitter, reflected, REFLECTION[face])
                    topology = resolve_topology(document)
                    self.assertTrue(topology.ok, topology.diagnostics)
                    outputs = topology.outgoing[splitter.id]
                    self.assertEqual([(edge.source.port_id, edge.interaction) for edge in outputs],
                                     [(TRANSMISSION[face], "transmitted"), (REFLECTION[face], "reflected")])
                    result = compile_schematic(document)
                    self.assertTrue(result.ok, result.diagnostics)
                    bx, by, angle = result.placements["BS1"]
                    tx, ty, _ = result.placements["FO1"]
                    rx, ry, _ = result.placements["D1"]
                    self.assertAlmostEqual(tx - bx, 50 * math.cos(math.radians(heading)))
                    self.assertAlmostEqual(ty - by, 50 * math.sin(math.radians(heading)))
                    self.assertEqual(angle, heading + {"left": 0, "right": -180, "top": 90, "bottom": -90}[face])
                    self.assertIn("rotate_cube=False", result.source)
                    normal = math.radians(angle - 45)
                    incident = (math.cos(math.radians(heading)), math.sin(math.radians(heading)))
                    n = (math.cos(normal), math.sin(normal))
                    dot = sum(a * b for a, b in zip(incident, n))
                    reflected_ray = tuple(a - 2 * dot * b for a, b in zip(incident, n))
                    self.assertAlmostEqual(rx - bx, 50 * reflected_ray[0])
                    self.assertAlmostEqual(ry - by, 50 * reflected_ray[1])
                    expected = next(ast.literal_eval(node.value) for node in ast.parse(result.source).body
                                    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                                    and node.targets[0].id == "EXPECTED")
                    self.assertIn(("BS1", "transmitted", "FO1"), expected)
                    self.assertIn(("BS1", "reflected", "D1"), expected)

    def test_explicit_turn_overrides_are_preserved_on_reversed_ports(self):
        document = chain("source", "mirror", "stop")
        optic = document.nodes[1]
        document.connections[0].b = Endpoint(optic.id, "B")
        document.connections[1].a = Endpoint(optic.id, "A")
        optic.physical["turn"] = 45
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertAlmostEqual(result.placements["D1"][1], 50 / math.sqrt(2))
        self.assertEqual(optic.physical["turn"], 45)

    def test_splitter_turn_overrides_work_for_every_incident_face(self):
        for face in ("left", "right", "top", "bottom"):
            for turn in (-90, 90):
                with self.subTest(face=face, turn=turn):
                    document = chain("source", "splitter")
                    cube = document.nodes[-1]
                    cube.physical["turn"] = turn
                    document.connections[0].b = Endpoint(cube.id, face)
                    for port in (TRANSMISSION[face], REFLECTION[face]):
                        connect(document, cube, document.add_node("stop"), port)
                    result = compile_schematic(document)
                    self.assertTrue(result.ok, result.diagnostics)
                    canonical = 90 if face in ("left", "right") else -90
                    rotated = turn != canonical
                    self.assertIn(f"rotate_cube={rotated}", result.source)
                    bx, by, angle = result.placements["BS1"]
                    rx, ry, _ = result.placements["D2"]
                    normal = math.radians(angle + (45 if rotated else -45))
                    self.assertAlmostEqual(-2 * math.cos(normal) * math.sin(normal), 1 if turn > 0 else -1)
                    self.assertAlmostEqual(rx, bx)
                    self.assertAlmostEqual(ry, by + (50 if turn > 0 else -50))

    def test_drawing_hints_follow_reverse_incidence_and_reversed_bends(self):
        document = chain("source", "mirror", "stop")
        source, mirror, stop = document.nodes
        source.position, source.rotation = (0, -160), 90
        mirror.position = (0, 0)
        stop.position, stop.rotation = (-160, 0), 180
        document.connections[0].b = Endpoint(mirror.id, "B")
        document.connections[1].a = Endpoint(mirror.id, "A")
        for edge in document.connections:
            edge.a, edge.b = edge.b, edge.a
            edge.bends.reverse()
        self.assertFalse(apply_drawing_directions(document))
        self.assertAlmostEqual(source.physical["angle"], -90)
        self.assertEqual(mirror.physical["turn"], -90)
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(result.placements["D1"][:2], (-50.0, -50.0))

    def test_incomplete_tree_has_directions_but_cannot_export(self):
        document = chain("source", "lens")
        topology = resolve_topology(document)
        self.assertFalse(topology.ok)
        self.assertEqual(len(topology.edges), 1)
        self.assertEqual(topology.edges[document.connections[0].id].source.node_id, document.nodes[0].id)
        self.assertFalse(compile_schematic(document).ok)

    def test_ambiguous_graphs_have_no_arrows_and_block_export(self):
        documents = []
        no_source = chain("lens", "stop")
        documents.append(no_source)
        multiple = chain("source", "lens", "stop")
        second_source = multiple.add_node("source")
        connect(multiple, second_source, multiple.nodes[1], target_port="B")
        documents.append(multiple)
        duplicate = chain("source", "lens", "stop")
        connect(duplicate, duplicate.nodes[0], duplicate.add_node("stop"))
        documents.append(duplicate)
        cycle = chain("source", "splitter")
        cube = cycle.nodes[1]
        lens, mirror = cycle.add_node("lens"), cycle.add_node("mirror")
        connect(cycle, cube, lens, "right")
        connect(cycle, lens, mirror)
        connect(cycle, mirror, cube, target_port="top")
        documents.append(cycle)
        for document in documents:
            with self.subTest(kinds=[n.kind for n in document.nodes]):
                topology = resolve_topology(document)
                self.assertFalse(topology.ok)
                self.assertFalse(topology.edges)
                self.assertFalse(compile_schematic(document).ok)

    def test_invalid_splitter_faces_are_identified(self):
        document = branched()
        splitter = document.nodes[2]
        edge = document.connections[-1]
        edge.a = Endpoint(splitter.id, "bottom")  # left incidence must reflect through top
        topology = resolve_topology(document)
        self.assertFalse(topology.edges)
        self.assertTrue(any(item.connection_id == edge.id for item in topology.diagnostics))
        self.assertTrue(any("top" in item.message for item in topology.diagnostics))
        self.assertFalse(compile_schematic(document).ok)
        document = branched()
        connect(document, document.nodes[2], document.add_node("stop"), "bottom")
        self.assertFalse(compile_schematic(document).ok)

    def test_terminals_cannot_transmit_even_when_wires_are_undirected(self):
        document = chain("source", "stop")
        stop, receiver = document.nodes[-1], document.add_node("fiber_output")
        connect(document, stop, receiver, port="beam")
        result = resolve_topology(document)
        self.assertFalse(result.ok)
        self.assertFalse(result.edges)

    def test_resolver_does_not_mutate_the_document(self):
        document = branched()
        original = deepcopy(document.to_dict())
        resolve_topology(document)
        self.assertEqual(original, document.to_dict())


class MigrationTests(unittest.TestCase):
    fixture = Path(__file__).parent / "fixtures" / "schematic_v1.json"

    def test_v1_load_preserves_identity_geometry_and_physical_layout(self):
        original_bytes = self.fixture.read_bytes()
        old = json.loads(original_bytes)
        document = load_schematic(self.fixture)
        self.assertEqual(self.fixture.read_bytes(), original_bytes)
        self.assertEqual(document.version, 6)
        for before, after in zip(old["nodes"], document.nodes):
            self.assertEqual(before["id"], after.id)
            self.assertEqual(before["reference"], after.reference)
            self.assertEqual(tuple(before["position"]), after.position)
            self.assertEqual(before["rotation"], after.rotation)
            self.assertEqual(before["physical"], after.physical)
        for before, after in zip(old["connections"], document.connections):
            self.assertEqual(before["id"], after.id)
            self.assertEqual(before["bends"], after.bends)
            for old_id, old_port, endpoint in ((before["source"], before["source_port"], after.a),
                                               (before["target"], before["target_port"], after.b)):
                node = document.node(old_id)
                if old_port == "in":
                    x, y = -40, 0
                elif old_port == "reflected" or (node.kind == "mirror" and old_port == "out"):
                    x, y = 0, -40
                else:
                    x, y = 40, 0
                rotation = math.radians(node.rotation)
                expected = (node.position[0] + x * math.cos(rotation) - y * math.sin(rotation),
                            node.position[1] + x * math.sin(rotation) + y * math.cos(rotation))
                for actual, value in zip(port_position(node, endpoint.port_id), expected):
                    self.assertAlmostEqual(actual, value)
        result = compile_schematic(document)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertEqual(result.placements, {
            "S1": (0.0, 0.0, 0.0), "M1": (50.0, 0.0, 135.0), "L1": (50.0, 50.0, 90.0),
            "BS1": (50.0, 100.0, 90.0), "FO1": (50.0, 150.0, 270.0), "D1": (0.0, 100.0, 360.0),
        })

    def test_migrated_bends_and_physical_overrides_survive_save_and_reopen(self):
        old = json.loads(self.fixture.read_text())
        old["connections"][0]["bends"] = [[0, 40], [80, 40]]
        old["nodes"][1]["physical"] = {"turn": -90, "distance": 75}
        document = document_from_dict(old)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "migrated.json"
            save_schematic(document, path)
            saved = json.loads(path.read_text())
            self.assertEqual(saved["version"], 6)
            self.assertNotIn("source", saved["connections"][0])
            reopened = load_schematic(path)
            self.assertEqual(document.to_dict(), reopened.to_dict())
            self.assertEqual(reopened.connections[0].bends, [(0, 40), (80, 40)])
            self.assertEqual(reopened.nodes[1].physical, {"turn": -90})
            self.assertEqual(reopened.connections[0].length, 75)


if __name__ == "__main__":
    unittest.main()
