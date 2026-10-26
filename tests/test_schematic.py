"""Run without FreeCAD: python -m unittest discover -s tests -p 'test_schematic*.py'."""

import ast
from copy import deepcopy
import json
import math
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from PyOpticL.schematic import (
    Connection, Endpoint, History, Schematic, compile_schematic, load_schematic,
    resolve_topology, save_schematic, validate_schematic,
)
from PyOpticL.schematic.geometry import (
    apply_drawing_directions, connection_points, route_to, snap_angle, snap_point,
)
from PyOpticL.schematic.model import document_from_dict, new_id
from PyOpticL.schematic.registry import REFLECTION, TRANSMISSION, SYMBOLS
from PyOpticL.schematic.runtime import check_trace


def connect(document, source, target, port=None, bends=None, target_port=None):
    if port is None:
        port = "beam" if SYMBOLS[source.kind].role == "source" else ("right" if source.kind == "splitter" else "B")
    if target_port is None:
        target_port = "beam" if SYMBOLS[target.kind].role == "terminal" else ("left" if target.kind == "splitter" else "A")
    edge = Connection(new_id(), Endpoint(source.id, port), Endpoint(target.id, target_port), bends=bends or [])
    document.connections.append(edge)
    return edge


def chain(*kinds):
    document = Schematic()
    nodes = [document.add_node(kind, (index * 160, 0)) for index, kind in enumerate(kinds)]
    for source, target in zip(nodes, nodes[1:]):
        connect(document, source, target)
    return document


def branched(nested=False):
    document = chain("source", "lens", "splitter")
    splitter = document.nodes[-1]
    straight = document.add_node("fiber_output", (480, 0))
    connect(document, splitter, straight, "right")
    reflected = document.add_node("splitter" if nested else "stop", (320, -160))
    connect(document, splitter, reflected, "top")
    if nested:
        for port, kind, position in (("right", "stop", (320, -320)),
                                     ("top", "output", (160, -160))):
            connect(document, reflected, document.add_node(kind, position), port)
    return document


class ModelTests(unittest.TestCase):
    def test_core_import_has_no_cad_or_gui_dependencies(self):
        script = "import sys; import PyOpticL.schematic; assert not any(k.startswith(('FreeCAD', 'PySide', 'Part', 'Mesh')) for k in sys.modules)"
        subprocess.run([sys.executable, "-c", script], check=True)

    def test_round_trip_preserves_identities_and_drawing(self):
        document = branched()
        document.nodes[1].rotation = 45
        document.nodes[1].parameters["focal_length"] = -75
        document.connections[0].length = 85
        document.connections[0].bends = [(80, 0), (80, -40)]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "layout.pyopticl-schematic.json"
            save_schematic(document, path)
            restored = load_schematic(path)
            self.assertEqual(json.dumps(document.to_dict(), sort_keys=True), json.dumps(restored.to_dict(), sort_keys=True))
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_incomplete_drawing_can_be_saved(self):
        document = Schematic()
        document.add_node("mirror")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "partial.json"
            save_schematic(document, path)
            self.assertTrue(validate_schematic(load_schematic(path)))

    def test_reject_malformed_files(self):
        original = chain("source", "stop").to_dict()
        cases = []
        for update in ({"version": 100}, {"title": 42}, {"settings": {"grid": 0}},
                       {"settings": {"spacing": float("nan")}}, {"settings": {"angle": 30}}):
            cases.append({**deepcopy(original), **update})
        for field, value in (("kind", "unknown"), ("preset", "malicious()"),
                             ("position", [float("inf"), 0]), ("parameters", {"x": "code()"})):
            case = deepcopy(original)
            case["nodes"][0][field] = value
            cases.append(case)
        duplicate = deepcopy(original)
        duplicate["nodes"].append(deepcopy(duplicate["nodes"][0]))
        cases.append(duplicate)
        for field, value in (("b", {"node_id": "missing", "port_id": "beam"}),
                             ("a", {"node_id": original["nodes"][0]["id"], "port_id": "invalid"}),
                             ("bends", [[0]])):
            case = deepcopy(original)
            case["connections"][0][field] = value
            cases.append(case)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                document_from_dict(case)

    def test_duplicate_and_delete_preserve_graph_integrity(self):
        document = chain("source", "mirror", "stop")
        original = document.nodes[1]
        original.physical["turn"] = -90
        copy = document.duplicate_nodes([original.id])[0]
        self.assertNotEqual(copy.id, original.id)
        self.assertNotEqual(copy.reference, original.reference)
        copy.physical["turn"] = 45
        self.assertEqual(original.physical["turn"], -90)
        document.remove_nodes([original.id])
        self.assertEqual(document.connections, [])

    def test_history_redo_dirty_and_redo_branch(self):
        document = chain("source", "stop")
        history = History(document)
        first_id = document.nodes[0].id
        document.nodes[0].position = (80, 120)
        history.commit(document)
        self.assertTrue(history.dirty)
        document = history.undo()
        self.assertEqual(document.nodes[0].id, first_id)
        self.assertFalse(history.dirty)
        document = history.redo()
        self.assertEqual(document.nodes[0].position, (80, 120))
        history.mark_saved()
        self.assertFalse(history.dirty)
        document = history.undo()
        self.assertTrue(history.dirty)
        document.title = "Alternative"
        history.commit(document)
        self.assertEqual(history.index, len(history.states) - 1)


class CompilerTests(unittest.TestCase):
    def assert_valid(self, document):
        result = compile_schematic(document)
        self.assertTrue(result.ok, [item.message for item in result.diagnostics])
        ast.parse(result.source)
        return result

    def test_all_curated_presets_export_valid_python(self):
        for kind, symbol in SYMBOLS.items():
            for preset in symbol.presets:
                with self.subTest(kind=kind, preset=preset):
                    if kind in ("source", "fiber_source"):
                        document = chain(kind, "stop")
                        node = document.nodes[0]
                    elif kind == "splitter":
                        document = branched()
                        node = document.nodes[2]
                    elif symbol.role == "terminal":
                        document = chain("source", kind)
                        node = document.nodes[-1]
                    else:
                        document = chain("source", kind, "stop")
                        node = document.nodes[1]
                    node.preset = preset
                    self.assert_valid(document)

    def test_generation_is_deterministic_and_independent_of_drawing(self):
        document = branched(nested=True)
        expected = self.assert_valid(document).source
        document.nodes.reverse()
        document.connections.reverse()
        for node in document.nodes:
            node.position = (-1000, 800)
            node.rotation = 315
        for edge in document.connections:
            edge.bends = [(0, -200), (80, 90)]
        self.assertEqual(self.assert_valid(document).source, expected)

    def test_reference_text_cannot_inject_python(self):
        document = chain("source", "stop")
        document.title = "'\nraise Exception('injected')\n#"
        document.nodes[-1].reference = "D'\nraise Exception('injected')\n#"
        result = self.assert_valid(document)
        tree = ast.parse(result.source)
        self.assertFalse(any(isinstance(node, ast.Raise) for node in ast.walk(tree)))

    def test_mirror_normals_face_incident_beam_and_reflect_correctly(self):
        for turn in (-135, -90, -45, 45, 90, 135):
            for heading in (0, 45, 180, -90):
                document = chain("source", "mirror", "stop")
                document.nodes[0].physical["angle"] = heading
                document.nodes[1].physical["turn"] = turn
                result = self.assert_valid(document)
                normal_angle = result.placements["M1"][2]
                incident = (math.cos(math.radians(heading)), math.sin(math.radians(heading)))
                normal = (math.cos(math.radians(normal_angle)), math.sin(math.radians(normal_angle)))
                dot = sum(x * y for x, y in zip(incident, normal))
                self.assertLess(dot, 0)
                reflected = tuple(x - 2 * dot * n for x, n in zip(incident, normal))
                for value, expected in zip(reflected, (math.cos(math.radians(heading + turn)), math.sin(math.radians(heading + turn)))):
                    self.assertAlmostEqual(value, expected)
                mx, my, _ = result.placements["M1"]
                dx, dy, _ = result.placements["D1"]
                self.assertAlmostEqual(dx, mx + 50 * reflected[0])
                self.assertAlmostEqual(dy, my + 50 * reflected[1])

    def test_splitter_left_and_right_routing(self):
        for turn in (-90, 90):
            document = branched()
            document.nodes[2].physical["turn"] = turn
            result = self.assert_valid(document)
            self.assertEqual(result.placements["FO1"][:2], (150.0, 0.0))
            self.assertEqual(result.placements["D1"][:2], (100.0, 50.0 if turn > 0 else -50.0))
            self.assertIn(f"rotate_cube={turn < 0}", result.source)

    def test_physical_overrides_and_parameters(self):
        document = chain("source", "lens", "stop")
        document.nodes[0].physical.update(x=10, y=20, angle=90)
        document.connections[0].length = 75
        document.nodes[1].parameters["focal_length"] = -100
        result = self.assert_valid(document)
        self.assertEqual(result.placements["L1"][:2], (10.0, 95.0))
        self.assertIn("'focal_length': -100", result.source)

    def test_virtual_terminals_do_not_emit_unused_placement_controls(self):
        document = chain("source", "output")
        result = self.assert_valid(document)
        self.assertIn("PLACEMENTS = {}", result.source)
        document = chain("fiber_source", "stop")
        result = self.assert_valid(document)
        self.assertIn("x, y, angle = SOURCE['x'], SOURCE['y'], SOURCE['angle'] + 180", result.source)

    def test_generated_factories_match_existing_library_signatures(self):
        # Inspect the real definitions without importing their FreeCAD dependencies.
        library = Path(__file__).resolve().parents[1] / "PyOpticL" / "library"
        modules = {name: {node.name: node for node in ast.parse((library / f"{name}.py").read_text()).body
                          if isinstance(node, ast.ClassDef)} for name in ("optics", "thorlabs")}
        def initializer(module, name):
            cls = modules[module][name]
            own = next((node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"), None)
            if own:
                return own
            for base in cls.bases:
                if isinstance(base, ast.Name) and base.id in modules[module]:
                    return initializer(module, base.id)
            return None
        for kind, symbol in SYMBOLS.items():
            if kind in ("source", "output"):
                continue
            for preset in symbol.presets:
                if kind == "splitter":
                    document = branched()
                    document.nodes[2].preset = preset
                elif kind == "fiber_source":
                    document = chain(kind, "stop")
                else:
                    document = chain("source", kind, "stop") if symbol.role == "passive" else chain("source", kind)
                    document.nodes[1].preset = preset
                result = self.assert_valid(document)
                tree = ast.parse(result.source)
                parameters = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                                  and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "PARAMETERS")
                for call in ast.walk(tree):
                    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and
                            isinstance(call.func.value, ast.Name) and call.func.value.id in modules):
                        continue
                    init = initializer(call.func.value.id, call.func.attr)
                    keys = set()
                    for keyword in call.keywords:
                        if keyword.arg is None:
                            keys.update(parameters[ast.literal_eval(keyword.value.slice)])
                        else:
                            keys.add(keyword.arg)
                    if init:
                        accepted = {arg.arg for arg in [*init.args.args, *init.args.kwonlyargs]}
                        self.assertTrue(keys <= accepted or init.args.kwarg, (kind, preset, keys - accepted))
                    else:
                        self.assertFalse(keys, (kind, preset, keys))

    def test_export_rejects_invalid_topology_and_settings(self):
        documents = []
        partial = chain("source", "mirror")
        documents.append(partial)
        multiple = chain("source", "stop")
        multiple.add_node("source")
        documents.append(multiple)
        merge = branched()
        merge.connections[-1].b = Endpoint(merge.nodes[3].id, "beam")
        documents.append(merge)
        cycle = chain("source", "mirror", "mirror")
        connect(cycle, cycle.nodes[-1], cycle.nodes[1])
        documents.append(cycle)
        disconnected = chain("source", "stop")
        disconnected.add_node("stop")
        documents.append(disconnected)
        invalid = chain("source", "mirror", "stop")
        invalid.nodes[1].physical["turn"] = 0
        documents.append(invalid)
        invalid = chain("source", "mirror", "stop")
        invalid.connections[0].length = 0
        documents.append(invalid)
        for value in (0, 1, -0.1, 1.1):
            invalid = branched()
            invalid.nodes[2].parameters["ref_ratio"] = value
            documents.append(invalid)
        incompatible = chain("source", "lens", "stop")
        incompatible.nodes[1].parameters["diameter"] = 25.4
        documents.append(incompatible)
        for document in documents:
            result = compile_schematic(document)
            self.assertFalse(result.ok)
            self.assertFalse(result.source)

    def test_overlapping_physical_origins_block_export(self):
        document = chain("source", "mirror", "mirror", "mirror", "mirror", "stop")
        self.assertFalse(compile_schematic(document).ok)


class GeometryTests(unittest.TestCase):
    def test_grid_and_angle_snapping(self):
        self.assertEqual(snap_point((19, 43)), (20, 40))
        self.assertEqual(snap_point((19, 43), enabled=False), (19, 43))
        x, y = snap_angle((50, 40), (0, 0))
        self.assertAlmostEqual(x, y)
        self.assertEqual(snap_angle((50, 40), (0, 0), enabled=False), (50, 40))

    def test_routes_reach_exact_endpoint_with_legal_angles(self):
        for step in (45, 90):
            for endpoint in ((80, 40), (-20, 80), (80, -40), (-20, -80), (0, 0)):
                start = (0, 0)
                path = route_to(start, endpoint, step)
                self.assertEqual(path[-1], endpoint)
                for end in path:
                    dx, dy = end[0] - start[0], end[1] - start[1]
                    self.assertTrue(dx == 0 or dy == 0 or (step == 45 and abs(dx) == abs(dy)))
                    start = end

    def test_apply_directions_is_explicit_and_converts_canvas_y(self):
        document = chain("source", "mirror", "stop")
        document.nodes[-1].position = (200, -160)
        result = compile_schematic(document).source
        self.assertEqual(document.nodes[1].physical, {})
        apply_drawing_directions(document)
        self.assertEqual(document.nodes[1].physical["turn"], 90)
        self.assertEqual(document.nodes[0].physical["angle"], 0)
        self.assertEqual(compile_schematic(document).source, result)
        self.assertTrue(connection_points(document, document.connections[1]))


class RuntimeTests(unittest.TestCase):
    def test_trace_check_detects_missing_extra_and_swapped_branches(self):
        source = SimpleNamespace(Name="source", Label="S1")
        cube = SimpleNamespace(Name="cube", Label="BS1")
        transmitted = SimpleNamespace(Name="transmitted", Label="FO1")
        reflected = SimpleNamespace(Name="reflected", Label="D1")
        objects = {obj.Label: SimpleNamespace(get_object=lambda obj=obj: obj)
                   for obj in (cube, transmitted, reflected)}
        def segment(start, end, direction):
            return SimpleNamespace(StartObject=start, EndObject=end,
                                   Proxy=SimpleNamespace(get_global_direction=lambda: direction))
        segments = [segment(None, cube, (1, 0, 0)), segment(cube, transmitted, (1, 0, 0)),
                    segment(cube, reflected, (0, 1, 0))]
        beam = SimpleNamespace(get_object=lambda: SimpleNamespace(BeamSegments=segments))
        expected = [("S1", "out", "BS1"), ("BS1", "transmitted", "FO1"), ("BS1", "reflected", "D1")]
        self.assertTrue(check_trace(beam, objects, expected, "S1", ["BS1"]))
        segments[1].EndObject, segments[2].EndObject = reflected, transmitted
        with self.assertRaisesRegex(RuntimeError, "Missing: BS1.transmitted -> FO1"):
            check_trace(beam, objects, expected, "S1", ["BS1"])
        segments.pop()
        with self.assertRaisesRegex(RuntimeError, "Missing"):
            check_trace(beam, objects, expected, "S1", ["BS1"])
        segments.append(segment(transmitted, source, (1, 0, 0)))
        with self.assertRaisesRegex(RuntimeError, "unknown:S1"):
            check_trace(beam, objects, expected, "S1", ["BS1"])

    def test_open_output_is_a_real_expected_trace_endpoint(self):
        segments = [SimpleNamespace(StartObject=None, EndObject=None,
                                    Proxy=SimpleNamespace(get_global_direction=lambda: (1, 0, 0)))]
        beam = SimpleNamespace(get_object=lambda: SimpleNamespace(BeamSegments=segments))
        self.assertTrue(check_trace(beam, {}, [("S1", "out", None)], "S1"))
        with self.assertRaises(RuntimeError):
            check_trace(beam, {}, [("S1", "out", "D1")], "S1")


if __name__ == "__main__":
    unittest.main()
