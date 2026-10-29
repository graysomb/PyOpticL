"""Native wavelength routing and finite-substrate ancestry acceptance tests."""
from pathlib import Path
import unittest
from unittest.mock import patch

import FreeCAD as App
import numpy as np
import Part

from examples.chirped_pulse_amplification import center_ray_shape
from PyOpticL import attachments
from PyOpticL.beam_path import BeamSegment
from PyOpticL.schematic import compile_schematic, load_schematic

FOLDER = Path(__file__).resolve().parents[1] / "Designs/schematics/cpa"


class DichroicRoutingTests(unittest.TestCase):
    def setUp(self):
        self.cad = App.newDocument("DichroicAcceptance")

    def tearDown(self):
        App.closeDocument(self.cad.Name)

    def build(self, name):
        result = compile_schematic(load_schematic(FOLDER / (name + ".pyopticl-schematic.json")))
        self.assertTrue(result.ok, result.diagnostics)
        namespace = {"__name__": "dichroic_acceptance"}
        exec(result.source, namespace)
        with patch.object(BeamSegment, "compute_shape", center_ray_shape):
            layout = namespace["build_layout"]()
        children = layout.get_object().Children
        optic = next(o for o in children if o.Label == "SHG_M1")
        beam = next(o for o in children if hasattr(o, "BeamSegments"))
        return optic, beam.BeamSegments

    def test_775_reflects_without_entering_substrate(self):
        optic, segments = self.build("output-775")
        outgoing = [s for s in segments if s.StartObject == optic]
        self.assertEqual(len(outgoing), 1)
        self.assertFalse(outgoing[0].InternalToComponent)
        np.testing.assert_allclose(outgoing[0].Proxy.get_global_direction(), (0, -1, 0), atol=1e-9)
        self.assertAlmostEqual(outgoing[0].Proxy.power, .075)

    def test_1550_exits_rear_with_plate_shift_and_mount_clearance(self):
        optic, segments = self.build("residual-1550")
        outgoing = [s for s in segments if s.StartObject == optic]
        internal = [s for s in outgoing if s.InternalToComponent]
        external = [s for s in outgoing if not s.InternalToComponent]
        self.assertEqual(len(internal), 1)
        self.assertEqual(len(external), 1)
        self.assertAlmostEqual(internal[0].Proxy.distance, 3.401680257, places=6)
        rear = external[0].Proxy
        np.testing.assert_allclose(rear.get_global_direction(), (-1, 0, 0), atol=1e-9)
        self.assertAlmostEqual(rear.get_global_position()[1], -219.012573075, places=6)
        self.assertAlmostEqual(rear.power, .425)
        guide = Part.makeCylinder(1, rear.distance, App.Vector(*rear.get_global_position()),
                                  App.Vector(*rear.get_global_direction()))
        for child in attachments.descendants(optic):
            if hasattr(child, "Shape") and not child.Shape.isNull():
                self.assertLess(guide.common(child.Shape).Volume, 1e-5, child.Label)


if __name__ == "__main__":
    unittest.main()
