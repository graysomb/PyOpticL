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
