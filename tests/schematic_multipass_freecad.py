"""Native shared-part trace parity. Roof body fixtures are explicitly analytical."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import FreeCAD as App
import Part

sys.path.insert(0, str(Path(__file__).parent))
from schematic_freecad import FreeCADSchematicTests, chain
from test_schematic_multipass import double_pass
from PyOpticL.roof_mirror import RoofOptic
from PyOpticL.schematic.scene_layout import initialize_layout


class NativeMultipassTests(unittest.TestCase):
    setUp = FreeCADSchematicTests.setUp
    tearDown = FreeCADSchematicTests.tearDown
    build = FreeCADSchematicTests.build

    def test_mirrored_grating_baseplate_and_saved_cad_keep_the_mount_upright(self):
        import json
        from tempfile import TemporaryDirectory
        from PyOpticL.layout import Component, Layout
        from PyOpticL.schematic.catalog_parts import grating
        from PyOpticL.schematic.cad import add_baseplate

        layout = Layout("Mirrored grating plate")
        part = layout.add(Component("G1", grating(mirrored=True)), (0, 0, 0), 0)
        layout.recompute()
        plate = add_baseplate(layout, thickness=30)
        obj = plate.get_object()
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)
        plan = json.loads(obj.MachiningPlan)
        self.assertEqual(len(plan["holes"]), 4)
        self.assertLess(obj.Shape.BoundBox.ZMax, 0)
        expected = obj.Shape.Volume
        part_name, plate_name = part.get_object().Name, obj.Name
        with TemporaryDirectory() as folder:
            path = Path(folder) / "mirrored.FCStd"
            self.cad.saveAs(str(path))
            App.closeDocument(self.cad.Name)
            self.cad = App.openDocument(str(path))
            self.cad.recompute()
            self.assertTrue(self.cad.getObject(plate_name).Shape.isValid())
            self.assertAlmostEqual(self.cad.getObject(plate_name).Shape.Volume, expected, delta=1e-6)
            contract = json.loads(self.cad.getObject(part_name).ComponentContract)
            surface = next(frame for frame in contract["frames"] if frame["name"] == "grating_surface")
            output = next(frame for frame in contract["frames"] if frame["name"] == "output")
            self.assertAlmostEqual(surface["rotation"][2], 180 - 49.9, delta=1e-6)
            self.assertLess(output["rotation"][2], 0)

    def test_fixed_grating_moves_free_mirror_and_receiver_and_matches_native_diffraction(self):
        from test_schematic_grating_constraints import grating_chain
        from PyOpticL.schematic.registry import grating_turn, select_preset
        from PyOpticL.schematic.scene_solver import solve_scene
        from PyOpticL.schematic.topology import resolve_topology
        from PyOpticL.schematic.physical import wrap_angle
        from PyOpticL.ray_math import heading

        heights = {}
        cases = (("bare", False, 0), ("bare", False, 1), ("MK05S", True, 0), ("MK05S", True, 1))
        for index, (preset, reverse, mirrored) in enumerate(cases):
            with self.subTest(preset=preset, reverse=reverse, mirrored=mirrored):
                if index:
                    self.tearDown()
                    self.setUp()
                document = grating_chain(reverse=reverse, transmission=("hwp", "iris") if not reverse else ())
                grating = document.nodes[2]
                select_preset(grating, preset)
                grating.parameters["mirrored"] = mirrored
                solution = solve_scene(document, iterations=40)
                self.assertTrue(solution.ok, solution.diagnostics)
                document.layout["poses"] = solution.poses
                layout = self.build(document)
                children = layout.get_object().Children
                part = next(child for child in children if child.Label == grating.reference)
                beam = next(child for child in children if hasattr(child, "BeamSegments"))
                incoming = next(segment.Proxy.get_global_direction() for segment in beam.BeamSegments
                                if segment.EndObject == part)
                outgoing = next(segment.Proxy.get_global_direction() for segment in beam.BeamSegments
                                if segment.StartObject == part)
                turn = grating_turn(document, grating, resolve_topology(document))
                self.assertAlmostEqual(wrap_angle(heading(outgoing) - heading(incoming) - turn), 0, delta=1e-6)
                if preset == "MK05S":
                    frame = next(frame for frame in part.Proxy.contract().frames if frame.name == "mounting_face")
                    self.assertLess(frame.position[2], 0)
                    if not mirrored:
                        heights[preset] = frame.position[2]
                    else:
                        self.assertAlmostEqual(frame.position[2], heights[preset], delta=1e-6)

    def test_half_wave_plate_and_iris_export_with_axes_parallel_to_the_beam(self):
        from test_schematic_transmission_alignment import transmission_scene
        from PyOpticL.schematic.registry import select_preset
        from PyOpticL.schematic.scene_solver import solve_scene

        for index, (angle, plate_preset, iris_preset) in enumerate(
            ((30, "bare", "ida12"), (-135, "FBR", "alignment"))
        ):
            with self.subTest(plate_preset=plate_preset, iris_preset=iris_preset):
                if index:
                    self.tearDown()
                    self.setUp()
                document = transmission_scene(angle, offset=90)
                plate, iris = document.nodes[1:3]
                select_preset(plate, plate_preset)
                select_preset(iris, iris_preset)
                solution = solve_scene(document, iterations=40)
                self.assertTrue(solution.ok, solution.diagnostics)
                document.layout["poses"] = solution.poses
                layout = self.build(document)
                children = layout.get_object().Children
                beam = next(child for child in children if hasattr(child, "BeamSegments"))
                for node in (plate, iris):
                    part = next(child for child in children if child.Label == node.reference)
                    owned, pending = set(), [part]
                    while pending:
                        child = pending.pop()
                        owned.add(child.Name)
                        pending.extend(getattr(child, "Children", ()))
                    incoming = next(segment.Proxy.get_global_direction() for segment in beam.BeamSegments
                                    if segment.EndObject is not None and segment.EndObject.Name in owned)
                    outgoing = next(segment.Proxy.get_global_direction() for segment in beam.BeamSegments
                                    if segment.StartObject is not None and segment.StartObject.Name in owned)
                    normal = part.getGlobalPlacement().Rotation.multVec(App.Vector(1, 0, 0))
                    self.assertAlmostEqual(abs(normal.dot(App.Vector(*incoming))), 1, delta=1e-6)
                    self.assertLess((App.Vector(*incoming) - App.Vector(*outgoing)).Length, 1e-6)

    def test_mirror_can_turn_around_and_exports_its_coated_face(self):
        from test_schematic_mirror_orientation import mirror_scene
        from PyOpticL.schematic.scene_solver import solve_scene

        for index, (incoming, turn) in enumerate(((90, 90), (-150, -90), (170, 30))):
            with self.subTest(incoming=incoming, turn=turn):
                if index:
                    self.tearDown()
                    self.setUp()
                document = mirror_scene(incoming, turn, mirror_yaw=45)
                solution = solve_scene(document, iterations=40)
                self.assertTrue(solution.ok, solution.diagnostics)
                document.layout["poses"] = solution.poses
                layout = self.build(document)
                mirror = next(child for child in layout.get_object().Children if child.Label == "M1")
                beam = next(child for child in layout.get_object().Children if hasattr(child, "BeamSegments"))
                arriving = next(segment.Proxy.get_global_direction() for segment in beam.BeamSegments
                                if segment.EndObject == mirror)
                normal = mirror.getGlobalPlacement().Rotation.multVec(App.Vector(1, 0, 0))
                self.assertLess(normal.dot(App.Vector(*arriving)), 0)

    def test_centered_coupler_mirror_contacts_match_native_trace_after_drag(self):
        from test_schematic_centering import coupler_scene
        from PyOpticL.schematic.scene_solver import solve_scene

        document = coupler_scene()
        mirror = document.nodes[1]
        document.layout["poses"][mirror.id][1:3] = [2, 1]
        solution = solve_scene(document, targets=((mirror.id, 0, 55),))
        self.assertTrue(solution.ok, solution.diagnostics)
        document.layout["poses"] = solution.poses
        # build_layout verifies native contact points against EXPECTED_PASSES.
        self.build(document)

    def test_free_receiver_rotation_matches_arriving_beam_in_generated_cad(self):
        from test_schematic_receiver_alignment import fiber_pair
        from PyOpticL.schematic.scene_solver import solve_scene

        document = fiber_pair("POLARIS-K05T6")
        source, receiver = document.nodes
        solution = solve_scene(document, targets=((source.id, 3, 35),))
        self.assertTrue(solution.ok, solution.diagnostics)
        document.layout["poses"] = solution.poses
        layout = self.build(document)
        children = layout.get_object().Children
        target = next(child for child in children if child.Label == receiver.reference)
        beam = next(child for child in children if hasattr(child, "BeamSegments"))
        incoming = next(segment.Proxy.get_global_direction() for segment in beam.BeamSegments
                        if segment.EndObject == target)
        normal = target.getGlobalPlacement().Rotation.multVec(App.Vector(1, 0, 0))
        self.assertAlmostEqual(normal.dot(App.Vector(*incoming)), -1, delta=1e-6)

    def test_shared_horizontal_and_vertical_returns_with_analytical_roof_body(self):
        for vertical in (False, True):
            if vertical:
                self.tearDown()
                self.setUp()
            with self.subTest(vertical=vertical), patch.object(
                RoofOptic, "shape", lambda self: Part.makeBox(1, 1, 1)
            ):
                doc = double_pass(vertical)
                layout = self.build(doc)
                children = layout.get_object().Children
                self.assertEqual(sum(child.Label.startswith("L1") for child in children), 1)
                self.assertEqual(sum(child.Label.startswith("QWP1") for child in children), 1)
                beam = next(child.Proxy for child in children if hasattr(child, "BeamSegments"))
                lens = next(child for child in children if child.Label.startswith("L1"))
                incoming = [s for s in beam.get_object().BeamSegments if s.EndObject == lens]
                self.assertEqual(len(incoming), 2)
                positions = [
                    s.Proxy.get_global_position() + s.Proxy.get_global_direction() * s.Proxy.distance
                    for s in incoming
                ]
                self.assertAlmostEqual(
                    abs(positions[0][2 if vertical else 1] - positions[1][2 if vertical else 1]),
                    5.0,
                    delta=1e-6,
                )

    def test_solved_shared_mirror_roof_returns_match_native_finite_hits(self):
        from test_schematic_roof_return import shared_mirror_roof_scene
        from PyOpticL.schematic.scene_solver import solve_scene
        from PyOpticL.schematic.registry import select_preset

        cases = ((False, None, "bare"), (True, None, "bare"),
                 (False, "hwp", "bare"), (False, "lens", "bare"),
                 (False, None, "POLARIS-K05VS2"))
        for index, (vertical, transmission, preset) in enumerate(cases):
            if index:
                self.tearDown()
                self.setUp()
            with self.subTest(vertical=vertical, transmission=transmission, preset=preset), patch.object(
                RoofOptic, "shape", lambda self: Part.makeBox(1, 1, 1)
            ):
                document = shared_mirror_roof_scene(vertical=vertical, transmission=transmission)
                select_preset(document.nodes[1], preset)
                solution = solve_scene(document, iterations=40)
                self.assertTrue(solution.ok, solution.diagnostics)
                document.layout["poses"] = solution.poses
                layout = self.build(document)
                children = layout.get_object().Children
                self.assertEqual(sum(child.Label == "M1" for child in children), 1)
                mirror = next(child for child in children if child.Label == "M1")
                beam = next(child for child in children if hasattr(child, "BeamSegments"))
                owned, pending = set(), [mirror]
                while pending:
                    child = pending.pop()
                    owned.add(child.Name)
                    pending.extend(getattr(child, "Children", ()))
                arrivals = [segment for segment in beam.BeamSegments
                            if segment.EndObject and segment.EndObject.Name in owned]
                self.assertEqual(len(arrivals), 2)
                hits = [App.Vector(*(segment.Proxy.get_global_position()
                        + segment.Proxy.get_global_direction() * segment.Proxy.distance))
                        for segment in arrivals]
                self.assertGreater((hits[0] - hits[1]).Length, 3)
                self.assertLess((hits[0] - hits[1]).Length, 6.35)
                for hit, visit_id in zip(hits, (document.nodes[1].id, "mirror-return")):
                    expected = App.Vector(*solution.layout.visits[visit_id].entry)
                    self.assertLess((hit - expected).Length, 1e-6)

    def test_physical_single_pass_splitter_and_reversed_grating(self):
        from schematic_freecad import branched

        doc = branched()
        initialize_layout(doc)
        self.build(doc)
        doc = chain("source", "grating", "output")
        doc.nodes[1].preset = "bare"
        doc.nodes[0].parameters["wavelength"] = 1550
        initialize_layout(doc)
        self.build(doc)

    def test_folded_splitter_has_native_zero_and_plus_ninety_branches(self):
        from test_schematic_scene_optimization import splitter_fold_scene
        import math

        layout = self.build(splitter_fold_scene())
        splitter = next(child for child in layout.get_object().Children if child.Label == "BS1")
        beam = next(child for child in layout.get_object().Children if hasattr(child, "BeamSegments"))
        incoming = next(
            segment.Proxy.get_global_direction()
            for segment in beam.BeamSegments
            if segment.EndObject == splitter
        )
        outputs = [
            segment.Proxy.get_global_direction()
            for segment in beam.BeamSegments
            if segment.StartObject == splitter
        ]
        turns = sorted(
            math.degrees(
                math.atan2(incoming[0] * d[1] - incoming[1] * d[0], incoming[0] * d[0] + incoming[1] * d[1])
            )
            for d in outputs
        )
        self.assertAlmostEqual(turns[0], 0, delta=1e-6)
        self.assertAlmostEqual(turns[1], 90, delta=1e-6)

    def test_saved_two_fold_layout_has_exact_native_air_path(self):
        from PyOpticL.schematic import load_schematic

        document = load_schematic(
            Path(__file__).resolve().parents[1]
            / "Designs/schematics/multipass/folding-after.pyopticl-schematic.json"
        )
        layout = self.build(document)
        beam = next(child.Proxy for child in layout.get_object().Children if hasattr(child, "BeamSegments"))
        lengths = [segment.Proxy.distance for segment in beam.get_object().BeamSegments]
        self.assertEqual(len(lengths), 3)
        self.assertAlmostEqual(sum(lengths), 180.0, delta=1e-6)
        self.assertEqual(
            len([child for child in layout.get_object().Children if child.Label.startswith("FM")]), 2
        )

    def test_finite_trace_budget_stops_unexpected_extra_interactions(self):
        from PyOpticL.beam_path import BeamPath

        doc = double_pass()

        def shorten(namespace):
            namespace["BeamPath"] = lambda *args, **kwargs: BeamPath(*args, **dict(kwargs, trace_limit=1))

        with patch.object(RoofOptic, "shape", lambda self: Part.makeBox(1, 1, 1)):
            with self.assertRaisesRegex(RuntimeError, "finite-pass budget"):
                self.build(doc, shorten)

    def test_open_segment_ends_before_a_later_unrelated_optic(self):
        from PyOpticL.layout import Layout, Component
        from PyOpticL.library import optics
        from PyOpticL.beam_path import BeamPath

        layout = Layout("Finite open segment")
        layout.add(Component("Later mirror", optics.Circular_Mirror()), position=(200, 0, 0), rotation=180)
        beam = layout.add(
            BeamPath("Finite beam", trace_limit=3, trace_ends=(((0, 0, 0), (1, 0, 0), 50),)),
            position=(0, 0, 0),
            rotation=0,
        )
        layout.recompute()
        segments = beam.get_object().BeamSegments
        self.assertEqual(len(segments), 1)
        self.assertIsNone(segments[0].EndObject)
        self.assertAlmostEqual(segments[0].Proxy.distance, 50)
        # Existing FCStd proxies deserialize without newly introduced attributes.
        del beam.trace_limit
        del beam.trace_ends
        beam.recompute()
        self.assertEqual(len(beam.get_object().BeamSegments), 2)


def run():
    return unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(NativeMultipassTests)
    )


if __name__ == "__main__":
    run()
