"""Run inside FreeCAD's Python console:

    exec(open('/path/to/PyOpticL/tests/schematic_freecad.py').read())

Creates and closes its own test documents; existing designs are preserved.
"""

import math
from pathlib import Path
import unittest
import FreeCAD as App

from PyOpticL.bounds import BoundsUnavailable
from PyOpticL.layout import Component
from PyOpticL.schematic import Connection, Endpoint, PathLengthConstraint, Schematic, compile_schematic, load_schematic
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

    def optimize_with_real_bounds(self, document, box):
        from PyOpticL.schematic.bounds import resolve_layout_bounds
        from PyOpticL.schematic.parts import folding_part_spec
        from PyOpticL.schematic.optimization import (
            OptimizationOptions,
            build_problem,
            optimize_layout,
            apply_optimization,
        )

        provider = BoundsProvider()
        radii, errors = resolve_layout_bounds(document, provider)
        self.assertFalse(errors, errors)
        options = OptimizationOptions(starts=2, iterations=3000, folding_preset="bare")
        folding_radius = None
        if any(edge.allow_folding for edge in document.connections):
            bounds = provider.get(folding_part_spec(options))
            self.assertIsNone(bounds.error, bounds.error)
            folding_radius = bounds.circle.radius_mm
        problem = build_problem(document, radii, box, options, folding_radius=folding_radius)
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        apply_optimization(document, problem, result)
        return result

    def test_folded_path_keeps_chord_and_actual_cad_trace_length(self):
        from PyOpticL.schematic.optimization import PackingBox

        document = chain("source", "output")
        source, output = document.nodes
        source.physical.update(x=0, y=0)
        output.physical.update(x=80, y=0)
        document.connections[0].length = 80
        document.connections[0].allow_folding = True
        document.path_constraints.append(PathLengthConstraint("total", source.id, output.id, 120))
        result = self.optimize_with_real_bounds(document, PackingBox(-20, -60, 140, 130))
        self.assertEqual(len(result.layout.graph.generated), 1)
        layout = self.build(document)
        beam = next(child for child in layout.get_object().Children if hasattr(child, "BeamSegments"))
        self.assertAlmostEqual(sum(segment.Distance.Value for segment in beam.BeamSegments), 120, delta=1e-6)
        open_segment = next(segment for segment in beam.BeamSegments if segment.EndObject is None)
        end = (
            open_segment.Proxy.get_global_position()
            + open_segment.Distance.Value * open_segment.Proxy.get_global_direction()
        )
        self.assertAlmostEqual(end[0], 80, delta=1e-6)
        self.assertAlmostEqual(end[1], 0, delta=1e-6)

    def test_folded_splitter_branch_preserves_ninety_degree_trace(self):
        from PyOpticL.schematic.optimization import PackingBox

        document = chain("source", "splitter")
        source, cube = document.nodes
        source.physical.update(x=0, y=0, angle=0)
        cube.physical.update(x=50, y=0, turn=90)
        document.connections[0].length = 50
        straight = document.add_node("output")
        straight.physical.update(x=150, y=0)
        connect(document, cube, straight, "right")
        document.connections[-1].length = 100
        reflected = document.add_node("output")
        reflected.physical.update(x=130, y=80)
        connect(document, cube, reflected, "top")
        document.connections[-1].allow_folding = True
        document.path_constraints.append(PathLengthConstraint("reflected", cube.id, reflected.id, 160))
        self.optimize_with_real_bounds(document, PackingBox(-20, -20, 220, 150))
        layout = self.build(document)
        beam = next(child for child in layout.get_object().Children if hasattr(child, "BeamSegments"))
        incoming = next(
            segment
            for segment in beam.BeamSegments
            if segment.EndObject is not None and segment.EndObject.Label == cube.reference
        )
        folded = next(
            segment
            for segment in beam.BeamSegments
            if segment.StartObject is not None
            and segment.StartObject.Label == cube.reference
            and segment.EndObject is not None
        )
        tail = next(segment for segment in beam.BeamSegments if segment.StartObject == folded.EndObject)
        self.assertAlmostEqual(folded.Distance.Value + tail.Distance.Value, 160, delta=1e-6)
        a, b = incoming.Proxy.get_global_direction(), folded.Proxy.get_global_direction()
        turn = math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]))
        self.assertAlmostEqual(turn, 90, delta=1e-6)

    def test_bypassed_folding_mirror_is_absent_from_exported_cad(self):
        from PyOpticL.schematic.optimization import PackingBox

        document = chain("source", "mirror", "output")
        source, mirror, output = document.nodes
        mirror.preset, mirror.mirror_role = "bare", "folding"
        source.physical.update(x=0, y=0)
        output.physical.update(x=100, y=0)
        document.path_constraints.append(PathLengthConstraint("total", source.id, output.id, 100))
        result = self.optimize_with_real_bounds(document, PackingBox(-15, -30, 150, 100))
        self.assertIn(mirror.id, result.layout.graph.bypassed)
        layout = self.build(document)
        self.assertFalse(any(child.Label == mirror.reference for child in layout.get_object().Children))
        beam = next(child for child in layout.get_object().Children if hasattr(child, "BeamSegments"))
        self.assertAlmostEqual(sum(segment.Distance.Value for segment in beam.BeamSegments), 100, delta=1e-6)

    def test_path_length_between_splitter_branches_without_optimization(self):
        document = branched()
        a, b = document.nodes[-2:]
        document.path_constraints.append(PathLengthConstraint("cross-branch", a.id, b.id, 240))
        layout = self.build(document)
        beam = next(child for child in layout.get_object().Children if hasattr(child, "BeamSegments"))
        branches = [
            segment
            for segment in beam.BeamSegments
            if segment.EndObject is not None and segment.EndObject.Label in (a.reference, b.reference)
        ]
        self.assertEqual(len(branches), 2)
        self.assertAlmostEqual(sum(segment.Distance.Value for segment in branches), 240, delta=1e-6)

    def test_generated_example_files_build_and_reach_path_targets(self):
        from PyOpticL.schematic.effective import effective_document
        from PyOpticL.schematic.optimization import OptimizationOptions
        from PyOpticL.schematic.paths import path_length

        paths = sorted(
            (Path(__file__).resolve().parents[1] / "Designs/schematics/optimization").glob(
                "*-after.pyopticl-schematic.json"
            )
        )
        self.assertEqual(len(paths), 5)
        for path in paths:
            with self.subTest(example=path.stem):
                example_document = App.newDocument("SchematicExampleTrace")
                try:
                    document = load_schematic(path)
                    compiled = compile_schematic(document)
                    self.assertTrue(compiled.ok, compiled.diagnostics)
                    physical = effective_document(
                        document,
                        compiled.geometry.graph,
                        OptimizationOptions(**document.optimization["options"]),
                    )
                    topology = resolve_topology(physical)
                    layout = self.build(document)
                    beam = next(
                        child for child in layout.get_object().Children if hasattr(child, "BeamSegments")
                    )
                    distances = {}
                    for edge in topology.edges.values():
                        source, target = physical.node(edge.source.node_id), physical.node(
                            edge.target.node_id
                        )
                        a, b = compiled.geometry.positions[source.id], compiled.geometry.positions[target.id]
                        dx, dy = b[0] - a[0], b[1] - a[1]
                        matches = []
                        for segment in beam.BeamSegments:
                            if (segment.StartObject is None) != (source.id == topology.source_id):
                                continue
                            if (
                                segment.StartObject is not None
                                and segment.StartObject.Label != source.reference
                            ):
                                continue
                            if (segment.EndObject is None) != (target.kind == "output"):
                                continue
                            if segment.EndObject is not None and segment.EndObject.Label != target.reference:
                                continue
                            direction = segment.Proxy.get_global_direction()
                            angle = abs(
                                math.degrees(
                                    math.atan2(
                                        dx * direction[1] - dy * direction[0],
                                        dx * direction[0] + dy * direction[1],
                                    )
                                )
                            )
                            if angle <= 1e-6:
                                matches.append(segment)
                        self.assertEqual(len(matches), 1, edge.id)
                        segment = matches[0]
                        distances[edge.id] = segment.Distance.Value
                        start = segment.Proxy.get_global_position()
                        end = start + segment.Distance.Value * segment.Proxy.get_global_direction()
                        self.assertLessEqual(math.hypot(start[0] - a[0], start[1] - a[1]), 1e-6)
                        self.assertLessEqual(math.hypot(end[0] - b[0], end[1] - b[1]), 1e-6)
                    for constraint in document.path_constraints:
                        self.assertAlmostEqual(
                            path_length(physical, constraint.component_a, constraint.component_b, distances),
                            constraint.length_mm,
                            delta=1e-6,
                        )
                finally:
                    App.closeDocument(example_document.Name)
                    App.setActiveDocument(self.cad.Name)

    def test_xy_circle_uses_local_bare_mirror_and_full_mounted_assembly(self):
        from PyOpticL.library import optics, thorlabs

        bare = Component("BareBounds", optics.Circular_Mirror())
        self.assertAlmostEqual(bare.get_xy_bounding_circle().radius_mm, math.hypot(6, 6.35), places=5)
        mounted = Component(
            "MountedBounds", optics.Circular_Mirror(mount_definition=thorlabs.Mirror_Mount_K05S1())
        )
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
