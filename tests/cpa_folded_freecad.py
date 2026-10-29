"""Native off-axis folded stretcher, supported seats and D-pickoff clearance."""
from pathlib import Path
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part

from examples.chirped_pulse_amplification import center_ray_shape, compound
from PyOpticL import machined_baseplate
from PyOpticL.beam_path import BeamSegment
from PyOpticL.schematic import compile_schematic, load_schematic

FOLDER = Path(__file__).resolve().parents[1] / "Designs/schematics/cpa-folded"


class FoldedStretcherTests(unittest.TestCase):
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
                o for o in roof.get_object().Children if o.Label == "HRS1015-P01"
            )
            self.assertLess(shape.common(optic.Shape).Volume, 1e-5)
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
            for segment, height in zip(lens_hits, (14.7, 10.7, 10.7, 14.7)):
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
            self.assertLess(guide.common(compound(objects["ST_Pickoff"])).Volume, 1e-5)
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
