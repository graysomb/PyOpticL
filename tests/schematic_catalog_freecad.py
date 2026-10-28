"""Native catalog integration; run alongside schematic_freecad.py in FreeCAD.

Missing pinned vendor assets are reported as skips here, never substituted with
similar CAD. The existing full-preset bounds acceptance test remains strict.
"""

import math
from pathlib import Path
import unittest
from unittest.mock import patch

import FreeCAD as App

from PyOpticL.lab_catalog import asset_record
from PyOpticL.schematic import Endpoint, PathLengthConstraint, compile_schematic, load_schematic
from PyOpticL.schematic.bounds import BoundsProvider
from PyOpticL.schematic.parts import part_spec
from PyOpticL.schematic.registry import SYMBOLS, D_MIRROR_PRESETS, select_preset
from PyOpticL.schematic.topology import resolve_topology
from PyOpticL.vendor_cad import resolve
from schematic_freecad import FreeCADSchematicTests, branched, chain


class CatalogFreeCADTests(unittest.TestCase):
    setUp = FreeCADSchematicTests.setUp
    tearDown = FreeCADSchematicTests.tearDown
    build = FreeCADSchematicTests.build

    def test_d_mirror_exports_use_native_datum_and_machine_matching_mounts(self):
        import json
        from PyOpticL.schematic.cad import add_baseplate
        from test_schematic_d_mirrors import d_mirror_scene

        for preset, height in (("KM05DR", 15.526), ("KM05DL", 15.526),
                               ("KM100D", 30.004), ("KM100DL", 30.004)):
            with self.subTest(preset=preset):
                document = d_mirror_scene(preset, edge_distance=2)
                layout = self.build(document)
                assembly = next(child for child in layout.get_object().Children
                                if callable(getattr(child.Proxy, "contract", None))
                                and child.Proxy.contract().catalog_id == "d_mirror")
                self.assertEqual(assembly.Proxy.contract().catalog_id, "d_mirror")
                self.assertEqual(len(assembly.Children), 2)
                optic = assembly.Children[0]
                # The nominal spot stays at Z=0; the cut edge is 2 mm above it.
                self.assertAlmostEqual(optic.Shape.BoundBox.ZMax, 2, delta=1e-5)
                plate = add_baseplate(layout, thickness=25.4).get_object()
                plan = json.loads(plate.MachiningPlan)
                self.assertTrue(plate.Shape.isValid())
                self.assertAlmostEqual(plate.Shape.BoundBox.ZMax, -height, delta=1e-5)
                self.assertEqual(len(plan["holes"]), 1)
                self.assertEqual(len(plan["pockets"]), int(preset.startswith("KM100")))

    def test_generated_grating_example(self):
        self.build(
            load_schematic(
                Path(__file__).resolve().parents[1]
                / "Designs/schematics/catalog/grating.pyopticl-schematic.json"
            )
        )

    def test_bare_grating_orders_wavelengths_and_reversed_ports(self):
        for order in (0, 1):
            for wavelength in (635, 1550):
                for reverse in (False, True):
                    with self.subTest(order=order, wavelength=wavelength, reverse=reverse):
                        document = chain("source", "grating", "output")
                        node = document.nodes[1]
                        select_preset(node, "bare")
                        node.parameters["order"] = order
                        document.nodes[0].parameters["wavelength"] = wavelength
                        if reverse:
                            document.connections[0].b = Endpoint(node.id, "B")
                            document.connections[1].a = Endpoint(node.id, "A")
                        layout = self.build(document)
                        beam = next(
                            child for child in layout.get_object().Children if hasattr(child, "BeamSegments")
                        )
                        outgoing = next(
                            segment.Proxy for segment in beam.BeamSegments if segment.EndObject is None
                        )
                        angle = math.radians(
                            compile_schematic(document).geometry.headings[document.connections[-1].id]
                        )
                        actual = outgoing.get_global_direction()
                        self.assertAlmostEqual(actual[0], math.cos(angle), delta=1e-8)
                        self.assertAlmostEqual(actual[1], math.sin(angle), delta=1e-8)

    def test_alignment_iris_trace_and_complete_bounds(self):
        document = chain("source", "iris", "output")
        node = document.nodes[1]
        select_preset(node, "alignment")
        self.build(document)
        result = BoundsProvider().get(part_spec(document, node, resolve_topology(document)))
        self.assertIsNone(result.error, result.error)
        self.assertGreater(result.circle.radius_mm, 0)

    def test_mounted_pbs_preserves_both_polarized_branches(self):
        for turn in (-90, 90):
            for incident in ("left", "right", "top", "bottom"):
                with self.subTest(turn=turn, incident=incident):
                    document = branched()
                    node = document.nodes[2]
                    select_preset(node, "displacement_pbs")
                    node.physical["turn"] = turn
                    from PyOpticL.schematic.registry import TRANSMISSION, REFLECTION

                    document.connections[1].b = Endpoint(node.id, incident)
                    document.connections[2].a = Endpoint(node.id, TRANSMISSION[incident])
                    document.connections[3].a = Endpoint(node.id, REFLECTION[incident])
                    self.build(document)

    def test_roof_trace_and_internal_air_path(self):
        try:
            resolve(asset_record("HRS1015-P01"))
        except FileNotFoundError as error:
            self.skipTest(str(error))
        self.check_roof_paths(SYMBOLS["roof"].presets)

    def test_roof_interfaces_with_analytical_body_fixture(self):
        # Exercise real FreeCAD ray propagation and finite roof interfaces while
        # CAD is unavailable. This does not verify vendor geometry or bounds.
        import Part
        from PyOpticL.roof_mirror import RoofOptic

        with patch.object(RoofOptic, "shape", lambda self: Part.makeBox(1, 1, 1)):
            self.check_roof_paths(("bare_horizontal", "bare_vertical"))

    def check_roof_paths(self, presets):
        for preset in presets:
            for reverse in (False, True):
                with self.subTest(preset=preset, reverse=reverse):
                    document = chain("source", "roof", "output")
                    node = document.nodes[1]
                    select_preset(node, preset)
                    document.connections[0].length = 80
                    document.path_constraints.append(
                        PathLengthConstraint("total", document.nodes[0].id, document.nodes[-1].id, 165.4)
                    )
                    if reverse:
                        document.connections[0].b = Endpoint(node.id, "B")
                        document.connections[1].a = Endpoint(node.id, "A")
                    layout = self.build(document)
                    beam = next(
                        child for child in layout.get_object().Children if hasattr(child, "BeamSegments")
                    )
                    distance = sum(segment.Distance.Value for segment in beam.BeamSegments)
                    self.assertAlmostEqual(distance, 165.4, delta=1e-6)
                    compiled = compile_schematic(document)
                    outgoing = next(
                        segment.Proxy for segment in beam.BeamSegments if segment.EndObject is None
                    )
                    start = outgoing.get_global_position()
                    expected = (
                        *compiled.geometry.origins[document.connections[-1].id],
                        compiled.geometry.heights[document.nodes[-1].id],
                    )
                    self.assertLess((App.Vector(*start) - App.Vector(*expected)).Length, 1e-7)
                    actual = outgoing.get_global_direction()
                    self.assertAlmostEqual(actual[0], -1, delta=1e-8)
                    self.assertAlmostEqual(actual[1], 0, delta=1e-8)
                    self.assertAlmostEqual(actual[2], 0, delta=1e-8)


def preset_test(kind, preset):
    def test(self):
        if kind == "splitter":
            document = branched()
            node = document.nodes[2]
        elif kind == "fiber_source":
            document = chain(kind, "lens", "output")
            node = document.nodes[0]
        elif kind == "fiber_output":
            document = chain("source", "mirror", kind)
            node = document.nodes[-1]
        else:
            document = chain("source", kind, "output")
            node = document.nodes[1]
        select_preset(node, preset)
        if kind == "grating":
            document.nodes[0].parameters["wavelength"] = 1550
        topology = resolve_topology(document)
        provider = BoundsProvider()
        previous, documents = App.ActiveDocument.Name, set(App.listDocuments())
        result = provider.get(part_spec(document, node, topology))
        self.assertEqual(App.ActiveDocument.Name, previous)
        self.assertEqual(set(App.listDocuments()), documents)
        if result.error and "Missing pinned CAD asset" in result.error:
            self.skipTest(result.error)
        self.assertIsNone(result.error, result.error)
        self.assertGreater(result.circle.radius_mm, 0)
        self.build(document)

    return test


for kind, presets in {
    "mirror": ("POLARIS-K05VS2", "POLARIS-K1VS2", "MHV-12.7L-R", "MHV-25.4L-R", *D_MIRROR_PRESETS),
    "lens": ("POLARIS-L05G", "POLARIS-L1G"),
    "hwp": ("FBR", "ELL16"),
    "qwp": ("FBR", "ELL16"),
    "fiber_source": ("POLARIS-K05T6", "KA05TA"),
    "fiber_output": ("POLARIS-K05T6", "KA05TA"),
    "splitter": ("displacement_pbs",),
    "iris": ("alignment",),
    "slit": ("VA100",),
    "grating": ("MK05S", "bare"),
    "roof": SYMBOLS["roof"].presets,
}.items():
    for preset in presets:
        setattr(
            CatalogFreeCADTests,
            "test_preset_" + kind + "_" + preset.replace("-", "_"),
            preset_test(kind, preset),
        )


def run():
    return unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CatalogFreeCADTests)
    )


if __name__ == "__main__":
    run()
