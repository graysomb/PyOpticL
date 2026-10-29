"""Native folded CPA traces, supported seats and D-pickoff clearance."""
from pathlib import Path
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part

from examples.chirped_pulse_amplification import (
    center_ray_shape,
    compound,
    overlap_volume,
)
from PyOpticL import machined_baseplate
from PyOpticL.beam_path import BeamSegment
from PyOpticL.schematic import compile_schematic, load_schematic

FOLDER = Path(__file__).resolve().parents[1] / "Designs/schematics/cpa-folded"


class FoldedStretcherTests(unittest.TestCase):
    def test_vendor_compound_interference_is_checked_per_solid(self):
        from PyOpticL import lab_catalog
        from PyOpticL.layout import Component, Layout

        cad = App.newDocument("VendorSolidProbeAcceptance")
        try:
            layout = Layout("Interference regression")
            mount = layout.add(
                Component(
                    "Pickoff", lab_catalog.definition("d_mirror", mount="KM05DL")
                ),
                (320, -220, 10.7),
                135,
            )
            layout.recompute()
            guide = Part.makeCylinder(
                1, 411.2, App.Vector(329.359297, -400, 10.7), App.Vector(0, 1, 0)
            )
            # This deliberately blocked corridor can return zero if tested
            # against the entire overlapping vendor compound in one boolean.
            self.assertGreater(overlap_volume(guide, compound(mount.get_object())), 30)
        finally:
            App.closeDocument(cad.Name)

    def test_four_pass_compressor_roofs_pickoff_and_plate(self):
        from PyOpticL import lab_catalog

        cad = App.newDocument("FoldedCompressorAcceptance")
        try:
            result = compile_schematic(
                load_schematic(FOLDER / "compressor.pyopticl-schematic.json")
            )
            self.assertTrue(result.ok, result.diagnostics)
            ns = {"__name__": "compressor_acceptance"}
            exec(result.source, ns)
            with patch.object(BeamSegment, "compute_shape", center_ray_shape):
                layout = ns["build_layout"]()
                plate, machining = machined_baseplate.add(
                    layout, position=(0, 0, 3), thickness=33
                )
                layout.recompute()
            objects = {o.Label: o for o in layout.get_object().Children}
            beam = next(o for o in objects.values() if hasattr(o, "BeamSegments"))

            def owner(obj):
                while obj is not None:
                    if obj in objects.values():
                        return obj.Label
                    obj = getattr(obj, "Parent", None)
                return None

            grating = objects["CP_G1"]
            hits = [s for s in beam.BeamSegments if s.EndObject == grating]
            self.assertEqual(len(hits), 4)
            for s, height in zip(hits, (15.525, 15.525, 9.875, 9.875)):
                p = (
                    s.Proxy.get_global_position()
                    + s.Proxy.distance * s.Proxy.get_global_direction()
                )
                self.assertAlmostEqual(p[2], height)
            points = [
                s.Proxy.get_global_position()
                + s.Proxy.distance * s.Proxy.get_global_direction()
                for s in hits
            ]
            self.assertAlmostEqual(
                (App.Vector(*points[0]) - App.Vector(*points[1])).Length, 15.4
            )
            for point in points:
                local = grating.Placement.inverse().multVec(App.Vector(*point))
                self.assertAlmostEqual(abs(local.z), 2.825)
            for ref, count in (("CP_HRoof", 2), ("CP_VRoof", 1)):
                entries = [
                    s
                    for s in beam.BeamSegments
                    if s.EndObject == objects[ref] and s.EndInterfaceRole == "entry"
                ]
                self.assertEqual(len(entries), count)
            self.assertEqual(len(beam.BeamSegments), 23)
            end = beam.BeamSegments[-1].Proxy
            self.assertAlmostEqual(
                (end.get_global_position() + end.distance * end.get_global_direction())[
                    2
                ],
                9.875,
            )
            for start, target, checked in (
                ("CP_M1", "CP_G1", ("CP_Pickoff", "CP_VRoof")),
                ("CP_G1", "CP_VRoof", ("CP_Pickoff", "CP_M1")),
                ("CP_VRoof", "CP_G1", ("CP_Pickoff", "CP_M1")),
                ("CP_G1", "CP_Pickoff", ("CP_VRoof", "CP_M1")),
            ):
                s = next(
                    s
                    for s in beam.BeamSegments
                    if owner(s.StartObject) == start and owner(s.EndObject) == target
                )
                p = s.Proxy
                guide = Part.makeCylinder(
                    1,
                    p.distance,
                    App.Vector(*p.get_global_position()),
                    App.Vector(*p.get_global_direction()),
                )
                for ref in checked:
                    self.assertLess(
                        overlap_volume(guide, compound(objects[ref])),
                        1e-5,
                        (start, target, ref),
                    )
            self.assertTrue(plate.get_object().Shape.isValid())
            self.assertEqual(len(plate.get_object().Shape.Solids), 1)
            for ref in ("CP_HRoof", "CP_VRoof"):
                optic = next(
                    o
                    for o in objects[ref].Children
                    if o.Proxy.contract().part_number == "HRS1015-P01"
                )
                self.assertLess(
                    overlap_volume(plate.get_object().Shape, optic.Shape), 1e-5
                )
                self.assertTrue(
                    any(
                        p.get("assembly") == ref
                        and p.get("kind") == "integral_support_recess"
                        for p in machining.plan["pockets"]
                    )
                )
            rows = [
                r
                for o in objects.values()
                if not hasattr(o, "BeamSegments") and o != plate.get_object()
                for r in lab_catalog.bom(o.Proxy)
            ]
            self.assertEqual(
                sum(r["quantity"] for r in rows if r["part_number"] == "HRS1015-P01"), 2
            )
            self.assertEqual(
                {r["path"].split("/")[0] for r in rows if r["catalog_id"] == "MK05S"},
                {"CP_G1"},
            )
            drilled = {r["assembly"] for r in machining.plan["holes"]}
            self.assertTrue({"CP_G1", "CP_HRoof", "CP_VRoof", "CP_Pickoff"} <= drilled)
            self.assertFalse({"CP_G2", "CP_Roof", "CP_M2"} & drilled)
        finally:
            App.closeDocument(cad.Name)

    def test_raised_plate_exposes_unchanged_compressor_roof_optic_seat(self):
        from PyOpticL.layout import Component, Layout
        from PyOpticL.roof_mirror import MountedRoof, RoofGeometry

        cad = App.newDocument("RaisedRoofSeatAcceptance")
        try:
            layout = Layout("Unchanged compressor roof")
            roof = layout.add(
                Component("CP_Roof", MountedRoof(RoofGeometry("horizontal", 9))),
                (0, 0, 12.7),
                90,
            )
            plate, machining = machined_baseplate.add(
                layout, position=(0, 0, 3), thickness=33
            )
            layout.recompute()
            shape = plate.get_object().Shape
            self.assertTrue(shape.isValid())
            self.assertEqual(len(shape.Solids), 1)
            recess = next(
                p
                for p in machining.plan["pockets"]
                if p.get("kind") == "integral_support_recess"
            )
            self.assertAlmostEqual(recess["depth_mm"], 3)
            optic = next(
                o
                for o in roof.get_object().Children
                if o.Proxy.contract().part_number == "HRS1015-P01"
            )
            self.assertLess(overlap_volume(shape, optic.Shape), 1e-5)
            self.assertAlmostEqual(roof.get_object().Placement.Base.z, 12.7)
        finally:
            App.closeDocument(cad.Name)

    def test_native_retrace_pickoff_clearance_and_supported_machining(self):
        cad = App.newDocument("FoldedStretcherAcceptance")
        try:
            result = compile_schematic(
                load_schematic(FOLDER / "stretcher.pyopticl-schematic.json")
            )
            self.assertTrue(result.ok, result.diagnostics)
            namespace = {"__name__": "folded_acceptance"}
            exec(result.source, namespace)
            with patch.object(BeamSegment, "compute_shape", center_ray_shape):
                layout = namespace["build_layout"]()
                plate, machining = machined_baseplate.add(
                    layout, position=(0, 0, 3), thickness=33
                )
                layout.recompute()
            objects = {o.Label: o for o in layout.get_object().Children}
            beam = next(o for o in objects.values() if hasattr(o, "BeamSegments"))
            lens_hits = [
                s for s in beam.BeamSegments if s.EndObject == objects["ST_L2"]
            ]
            self.assertEqual(len(lens_hits), 4)
            for segment, height in zip(lens_hits, (15.525, 9.875, 9.875, 15.525)):
                p = segment.Proxy
                self.assertAlmostEqual(
                    (p.get_global_position() + p.distance * p.get_global_direction())[
                        2
                    ],
                    height,
                )
            last = beam.BeamSegments[-1]
            self.assertEqual(last.EndObject, objects["To_EDFA"])
            self.assertEqual(len(beam.BeamSegments), 20)

            def owner(obj):
                while obj is not None:
                    if obj in objects.values():
                        return obj
                    obj = getattr(obj, "Parent", None)
                return None

            upper = next(
                s
                for s in beam.BeamSegments
                if owner(s.StartObject) == objects["ST_HWP1"]
                and owner(s.EndObject) == objects["ST_G2"]
            )
            p = upper.Proxy
            guide = Part.makeCylinder(
                1,
                p.distance,
                App.Vector(*p.get_global_position()),
                App.Vector(*p.get_global_direction()),
            )
            self.assertLess(
                overlap_volume(guide, compound(objects["ST_Pickoff"])), 1e-5
            )
            shape = plate.get_object().Shape
            self.assertTrue(shape.isValid())
            self.assertEqual(len(shape.Solids), 1)
            self.assertAlmostEqual(shape.BoundBox.ZMax, 3)
            self.assertAlmostEqual(shape.BoundBox.ZMin, -30)
            self.assertEqual(machining.plan["plate_position_mm"], [0, 0, 3])
            self.assertEqual(machining.plan["thickness_mm"], 33)
            drilled = {h["assembly"] for h in machining.plan["holes"]}
            self.assertTrue(
                {"ST_G2", "ST_L2", "ST_Fold", "ST_Pickoff", "ST_M1", "To_EDFA"}
                <= drilled
            )
        finally:
            App.closeDocument(cad.Name)


if __name__ == "__main__":
    unittest.main()
