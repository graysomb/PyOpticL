"""Run inside FreeCAD's Python console:

    exec(open('/path/to/PyOpticL/tests/schematic_freecad.py').read())

Creates and closes its own test documents; existing designs are preserved.
"""

import math
import unittest
import FreeCAD as App

from PyOpticL.bounds import BoundsUnavailable
from PyOpticL.layout import Component
from PyOpticL.schematic import Connection, Endpoint, Schematic, compile_schematic
from PyOpticL.schematic.bounds import BoundsProvider
from PyOpticL.schematic.model import new_id
from PyOpticL.schematic.parts import part_spec
from PyOpticL.schematic.registry import REFLECTION, TRANSMISSION, SYMBOLS
from PyOpticL.schematic.topology import resolve_topology


def connect(document, source, target, port=None, target_port=None):
    port = port or ("beam" if SYMBOLS[source.kind].role == "source" else "B")
    target_port = target_port or ("beam" if SYMBOLS[target.kind].role == "terminal" else
                                  "left" if target.kind == "splitter" else "A")
    document.connections.append(Connection(new_id(), Endpoint(source.id, port), Endpoint(target.id, target_port)))


def chain(*kinds):
    document = Schematic()
    nodes = [document.add_node(kind) for kind in kinds]
    for source, target in zip(nodes, nodes[1:]):
        connect(document, source, target)
    return document


def branched(nested=False):
    document = chain("source", "lens", "splitter")
    splitter = document.nodes[-1]
    for port, kind in (("right", "fiber_output"), ("top", "splitter" if nested else "stop")):
        target = document.add_node(kind)
        connect(document, splitter, target, port)
    if nested:
        splitter = document.nodes[-1]
        for port, kind in (("right", "stop"), ("top", "output")):
            target = document.add_node(kind)
            connect(document, splitter, target, port)
    return document


class FreeCADSchematicTests(unittest.TestCase):
    def setUp(self):
        self.previous = App.ActiveDocument.Name if App.ActiveDocument else None
        self.cad = App.newDocument("SchematicIntegrationTest")

    def tearDown(self):
        App.closeDocument(self.cad.Name)
        if self.previous:
            App.setActiveDocument(self.previous)

    def build(self, document, change=None):
        result = compile_schematic(document)
        self.assertTrue(result.ok, [diagnostic.message for diagnostic in result.diagnostics])
        namespace = {"__name__": "schematic_integration"}
        exec(compile(result.source, "schematic_generated.py", "exec"), namespace)
        if change:
            change(namespace)
        return namespace["build_layout"]()

    def test_lens_iris_chain(self):
        self.build(chain("source", "lens", "iris", "stop"))

    def test_counterclockwise_mirror(self):
        document = chain("source", "mirror", "stop")
        document.nodes[1].physical["turn"] = 90
        self.build(document)

    def test_clockwise_mirror(self):
        document = chain("source", "mirror", "stop")
        document.nodes[1].physical["turn"] = -90
        self.build(document)

    def test_splitter(self):
        self.build(branched())

    def test_nested_splitters(self):
        self.build(branched(nested=True))

    def test_fiber_source_waveplates_and_fiber_output(self):
        self.build(chain("fiber_source", "hwp", "qwp", "fiber_output"))

    def test_open_output(self):
        self.build(chain("source", "output"))

    def test_rotated_source(self):
        document = chain("source", "mirror", "stop")
        document.nodes[0].physical.update(x=20, y=30, angle=45)
        self.build(document)

    def test_accidental_interception_reports_part_references(self):
        document = chain("source", "lens", "stop")
        def change(namespace):
            namespace["PLACEMENTS"]["D1"] = (25, 0, 180)
        with self.assertRaisesRegex(RuntimeError, "Missing:.*L1"):
            self.build(document, change)

    def test_reversed_passive_ports_and_connection_click_order(self):
        for kind in ("mirror", "lens", "iris", "hwp", "qwp"):
            with self.subTest(kind=kind):
                document = chain("source", kind, "stop")
                optic = document.nodes[1]
                document.connections[0].b = Endpoint(optic.id, "B")
                document.connections[1].a = Endpoint(optic.id, "A")
                for edge in document.connections:
                    edge.a, edge.b = edge.b, edge.a
                self.build(document)

    def test_splitter_incidence_from_all_four_faces(self):
        for face in ("left", "right", "top", "bottom"):
            with self.subTest(face=face):
                document = chain("source", "splitter")
                cube = document.nodes[-1]
                document.connections[0].b = Endpoint(cube.id, face)
                for port in (TRANSMISSION[face], REFLECTION[face]):
                    connect(document, cube, document.add_node("stop"), port)
                self.build(document)

    def test_beam_lengths_control_component_positions(self):
        document = chain("source", "lens", "stop")
        document.connections[0].length = 75
        document.connections[1].length = 90
        layout = self.build(document)
        objects = {child.Label: child for child in layout.get_object().Children}
        self.assertAlmostEqual(objects["L1"].Placement.Base.x, 75)
        self.assertAlmostEqual(objects["D1"].Placement.Base.x, 165)

    def test_independent_open_branch_lengths(self):
        document = chain("source", "splitter")
        cube = document.nodes[-1]
        for port, length in (("right", 80), ("top", 120)):
            connect(document, cube, document.add_node("output"), port)
            document.connections[-1].length = length
        layout = self.build(document)
        beam = next(child for child in layout.get_object().Children if hasattr(child, "BeamSegments"))
        lengths = sorted(segment.Distance.Value for segment in beam.BeamSegments if segment.EndObject is None)
        self.assertEqual(lengths, [80, 120])

    def test_continuous_turn_at_mirror(self):
        for turn in (-62.5, 117.25):
            document = chain("source", "mirror", "stop")
            document.nodes[1].physical["turn"] = turn
            self.build(document)

    def test_pinned_positions_resolve_lengths_and_reach_the_traced_optics(self):
        document = chain("source", "mirror", "stop")
        document.nodes[-1].physical.update(x=100, y=75)
        layout = self.build(document)
        objects = {child.Label: child for child in layout.get_object().Children}
        self.assertAlmostEqual(objects["M1"].Placement.Base.x, 100)
        self.assertAlmostEqual(objects["D1"].Placement.Base.x, 100)
        self.assertAlmostEqual(objects["D1"].Placement.Base.y, 75)

    def test_continuous_splitter_turn_from_every_face(self):
        for face in TRANSMISSION:
            for turn in (-62.5, 117.25):
                document = chain("source", "splitter")
                cube = document.nodes[-1]
                document.connections[0].b = Endpoint(cube.id, face)
                cube.physical["turn"] = turn
                for port in (TRANSMISSION[face], REFLECTION[face]):
                    connect(document, cube, document.add_node("stop"), port)
                self.build(document)

    def test_optimized_layouts_export_and_trace_with_real_assembly_bounds(self):
        from PyOpticL.schematic.bounds import resolve_layout_bounds
        from PyOpticL.schematic.optimization import (
            OptimizationOptions, PackingBox, apply_optimization, build_problem, optimize_layout,
        )

        documents = [chain("source", "mirror", "mirror", "stop"), branched(),
                     chain("fiber_source", "hwp", "iris", "fiber_output")]
        folded = chain("source", "mirror", "stop")
        folded.nodes[0].physical.update(x=0, y=0, angle=0)
        folded.nodes[1].preset = "bare"
        folded.connections[0].length = 150
        folded.nodes[-1].physical.update(x=240, y=120)
        self.assertFalse(compile_schematic(folded).ok)
        documents.append(folded)
        for document in documents:
            with self.subTest(kinds=[n.kind for n in document.nodes]):
                document.settings.update(spacing=150, open_length=120)
                before = document.to_dict()
                cad_documents = set(App.listDocuments())
                radii, errors = resolve_layout_bounds(document, BoundsProvider())
                self.assertFalse(errors, errors)
                self.assertEqual(set(App.listDocuments()), cad_documents)
                self.assertEqual(App.ActiveDocument.Name, self.cad.Name)
                problem = build_problem(document, radii, PackingBox(-150, -150, 900, 700),
                                        OptimizationOptions(starts=3, iterations=1500))
                result = optimize_layout(problem)
                self.assertEqual(result.status, "feasible", result.violations)
                apply_optimization(document, problem, result)
                self.assertEqual(document.to_dict()["nodes"], before["nodes"])
                self.assertEqual(document.to_dict()["connections"], before["connections"])
                self.build(document)  # generated check_trace must verify every intended interaction

    def test_xy_circle_uses_local_bare_mirror_and_full_mounted_assembly(self):
        from PyOpticL.library import optics, thorlabs

        bare = Component("BareBounds", optics.Circular_Mirror())
        self.assertAlmostEqual(bare.get_xy_bounding_circle().radius_mm, math.hypot(6, 6.35), places=5)
        mounted = Component("MountedBounds", optics.Circular_Mirror(mount_definition=thorlabs.Mirror_Mount_K05S1()))
        full = mounted.get_xy_bounding_circle()
        self.assertGreater(full.radius_mm, mounted.get_xy_bounding_circle(include_children=False).radius_mm)
        mounted.get_object().BasePlacement = App.Placement(App.Vector(100, 200, 300), App.Rotation(App.Vector(0, 0, 1), 37))
        mounted.recompute()
        self.assertAlmostEqual(mounted.get_xy_bounding_circle().radius_mm, full.radius_mm)

    def test_xy_circle_mesh_placement_is_not_mutated_and_empty_mesh_fails(self):
        import Mesh
        import MeshPart
        import Part

        class Body:
            mesh = MeshPart.meshFromShape(Shape=Part.makeBox(3, 4, 5), LinearDeflection=0.1, AngularDeflection=0.5)

        Body.mesh.Placement = App.Placement(App.Vector(500, 600, 700), App.Rotation(App.Vector(0, 0, 1), 23))
        before = str(Body.mesh.Placement)
        part = Component("MeshBounds", Body())
        self.assertAlmostEqual(part.get_xy_bounding_circle().radius_mm, 5)
        self.assertEqual(str(Body.mesh.Placement), before)

        class Missing:
            mesh = Mesh.Mesh()

        with self.assertRaises(BoundsUnavailable):
            Component("MissingMesh", Missing()).get_xy_bounding_circle()

    def test_every_schematic_preset_resolves_bounds_without_touching_user_document(self):
        provider = BoundsProvider()
        original_objects = [obj.Name for obj in self.cad.Objects]
        documents = set(App.listDocuments())
        for kind, symbol in SYMBOLS.items():
            for preset in symbol.presets:
                with self.subTest(kind=kind, preset=preset):
                    document = Schematic()
                    node = document.add_node(kind)
                    node.preset = preset
                    spec = part_spec(document, node, resolve_topology(document))
                    if spec is None:
                        continue
                    result = provider.get(spec)
                    self.assertIsNone(result.error, result.error)
                    self.assertGreater(result.circle.radius_mm, 0)
                    self.assertEqual(App.ActiveDocument.Name, self.cad.Name)
                    self.assertEqual(set(App.listDocuments()), documents)
                    self.assertEqual([obj.Name for obj in self.cad.Objects], original_objects)


def run():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FreeCADSchematicTests)
    return unittest.TextTestRunner(verbosity=2).run(suite)


if __name__ == "__main__":
    run()
