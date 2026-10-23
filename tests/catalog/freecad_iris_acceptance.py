"""Fixed iris geometry, two-pin drilling, tracing and export acceptance.

Run with FreeCAD's bundled Python and its lib directory on PYTHONPATH.
"""
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PyOpticL import lab_catalog as catalog, machined_baseplate as machining
from PyOpticL.beam_path import BeamSegment, linear_polarization
from PyOpticL.component_contract import ComponentContract
from PyOpticL.layout import Component, Layout
from PyOpticL.library import Baseplate
from PyOpticL.settings import get_measurement_system, set_measurement_system


class IrisTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('IrisAcceptance')
        self.addCleanup(App.closeDocument, self.doc.Name)

    def assert_inside(self, shape, point, expected):
        self.assertEqual(shape.isInside(App.Vector(*point), 1e-7, False), expected, point)

    def test_geometry_and_blind_mount_holes(self):
        shape = catalog.AlignmentIris().shape()
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        bounds = shape.optimalBoundingBox()
        for actual, expected in zip((bounds.XMin, bounds.XMax, bounds.YMin, bounds.YMax,
                                     bounds.ZMin, bounds.ZMax), (-2, 2, -10, 10, -12.7, 10)):
            self.assertAlmostEqual(actual, expected, places=5)
        for x in (-1.99, 0, 1.99):
            self.assert_inside(shape, (x, 0, 0), False)
            self.assert_inside(shape, (x, .3, 0), True)
        self.assert_inside(shape, (0, 8, 8), False)  # Rounded, not rectangular cap.
        self.assert_inside(shape, (0, 8, 5), True)
        for y in (-5, 5):
            self.assert_inside(shape, (0, y, -11), False)  # Straight bore.
            self.assert_inside(shape, (0, y, -10.4), False)  # Drill tip.
            self.assert_inside(shape, (0, y, -10), True)  # Blind floor.
            self.assert_inside(shape, (1.1, y, -11), True)
            self.assert_inside(shape, (.9, y, -11), False)
        self.assert_inside(shape, (0, 0, -11), True)  # No extra mounting bore.

    def test_parameters_and_instance_isolation(self):
        a = catalog.create('iris', 'Small')
        b = catalog.create('iris', 'Large', aperture_diameter=1.2)
        a.recompute()
        b.recompute()
        self.assert_inside(a.get_object().Shape, (0, .4, 0), True)
        self.assert_inside(b.get_object().Shape, (0, .4, 0), False)
        self.assertAlmostEqual(a.drill().Volume, b.drill().Volume, places=8)
        profile = a.baseplate_profile()
        profile['dowel']['plate_diameter_mm'] = 9
        self.assertEqual(a.baseplate_profile()['dowel']['plate_diameter_mm'], 2.01)
        for value in (0, -1, 20, 21, math.inf, -math.inf, math.nan):
            with self.subTest(value=value), self.assertRaises(ValueError):
                catalog.create('iris', 'Invalid', aperture_diameter=value)
        with self.assertRaises(TypeError):
            catalog.create('iris', 'Unknown option', optical_height=25.4)

    def test_contract_and_reference(self):
        iris = catalog.create('iris', 'Contract')
        contract = iris.contract()
        self.assertEqual(contract, ComponentContract.from_dict(json.loads(
            iris.get_object().ComponentContract)))
        self.assertEqual(contract.procurement, 'fabricated')
        self.assertEqual(contract.optical_reference, 'optical')
        self.assertEqual(contract.dofs, ())
        self.assertEqual(len(contract.holes), 2)
        frames = {f.name: f for f in contract.frames}
        self.assertEqual(frames['mounting_face'].position, (0, 0, -12.7))
        self.assertEqual({frames[h.frame].position for h in contract.holes},
                         {(0, -5, -12.7), (0, 5, -12.7)})
        self.assertTrue(all((h.diameter_mm, h.depth_mm, h.thread) == (2.05, 2, None)
                            for h in contract.holes))
        self.assertEqual(iris.get_object().getEditorMode('ComponentContract'), ['ReadOnly'])
        self.assertIn('Adapted design', contract.provenance[0].note)
        rows = catalog.bom(iris)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['procurement'], 'fabricated')
        record = json.loads((catalog.DATA / 'alignment_iris_reference.json').read_text())
        self.assertEqual(record['sha256'], contract.provenance[0].sha256)
        source = Path(__file__).resolve().parents[3] / record['source']
        if source.exists():
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), record['sha256'])

    def test_drill_contains_only_two_blind_bores(self):
        drill = catalog.AlignmentIris().drill()
        self.assertTrue(drill.isValid())
        self.assertEqual(len(drill.Solids), 2)
        radius, depth = 1.005, 4.445
        tip = radius / math.tan(math.radians(59))
        self.assertAlmostEqual(drill.BoundBox.ZMin, -12.7 - depth - tip, places=6)
        for y in (-5, 5):
            self.assert_inside(drill, (0, y, -15), True)
            self.assert_inside(drill, (1.01, y, -15), False)
            self.assert_inside(drill, (0, y, -17.4), True)
            self.assert_inside(drill, (.9, y, -17.4), False)  # Cone, not full diameter.
            self.assert_inside(drill, (0, y, -17.8), False)
        self.assert_inside(drill, (0, 0, -15), False)
        self.assertAlmostEqual(drill.Volume, 2 * math.pi * radius**2 * (depth + .01 + tip / 3), places=6)

    def test_ordinary_baseplate_transforms_and_drill_filter(self):
        layout = Layout('Ordinary plate layout')
        layout.get_object().BasePlacement = App.Placement(App.Vector(20, 30, 5),
                                                         App.Rotation('XYZ', 0, 0, 17))
        iris = layout.add(catalog.create('iris', 'Iris'), (20, 20, 0), 37)
        plate = layout.add(Component('Plate', Baseplate((60, 60, 12.7), grid_offset=(0, 0)),
                                     recompute_priority=-2), (0, 0, 0), 0)
        # A peer that could cut the iris must neither damage it nor be cut by it.
        class Peer:
            object_group = 'mounts'
            def shape(self):
                return Part.makeBox(4, 20, 22.7, App.Vector(-2, -10, -12.7))
            def drill(self):
                return self.shape()
            drill_groups = ('mounts',)
        peer = layout.add(Component('Peer', Peer()), (20, 20, 0), 37)
        layout.recompute()
        shape = plate.get_object().Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        expected_removed = 2 * math.pi * 1.005**2 * (
            4.445 + 1.005 / math.tan(math.radians(59)) / 3)
        self.assertAlmostEqual(shape.Volume, 60 * 60 * 12.7 - expected_removed, places=5)
        for y in (-5, 5):
            point = iris.get_object().Placement.multVec(App.Vector(0, y, -14.7))
            self.assert_inside(shape, point, False)
            floor = iris.get_object().Placement.multVec(App.Vector(0, y, -17.8))
            self.assert_inside(shape, floor, True)
        self.assertAlmostEqual(iris.get_object().Shape.Volume, catalog.AlignmentIris().shape().Volume, places=6)
        self.assertAlmostEqual(peer.get_object().Shape.Volume, 4 * 20 * 22.7, places=6)
        before = shape.Volume, len(self.doc.Objects)
        layout.recompute()
        self.assertEqual(len(self.doc.Objects), before[1])
        self.assertAlmostEqual(plate.get_object().Shape.Volume, before[0], places=6)

    def test_machined_iris_only_moves_recomputes_and_needs_no_cad_cache(self):
        with patch.object(catalog, 'vendor_shape', side_effect=AssertionError('No vendor CAD needed')):
            layout = Layout('Machined iris layout')
            layout.get_object().BasePlacement = App.Placement(App.Vector(80, 10, 3),
                                                             App.Rotation('XYZ', 0, 0, 22))
            iris = layout.add(catalog.create('iris', 'Iris'), (20, 30, 12.7), 43)
            plate, definition = machining.add(layout)
            layout.recompute()
            for pos, angle in (((20, 30, 12.7), 43), ((35, 40, 12.7), 90)):
                iris.get_object().BasePlacement = App.Placement(App.Vector(*pos),
                                                               App.Rotation('XYZ', 0, 0, angle))
                layout.recompute()
                plan = definition.plan
                self.assertEqual(len(plan['holes']), 2)
                self.assertEqual(plan['pockets'], [])
                self.assertTrue(all(h['kind'] == 'dowel' for h in plan['holes']))
                self.assertTrue(all('thread' not in h for h in plan['holes']))
                local_shape = plate.get_object().Shape.copy()
                local_shape.Placement = App.Placement()
                self.assertTrue(local_shape.isValid())
                self.assertEqual(len(local_shape.Solids), 1)
                expected = [iris.get_object().BasePlacement.multVec(App.Vector(0, y, -12.7))
                            for y in (-5, 5)]
                for op, point in zip(plan['holes'], expected):
                    self.assertLess((App.Vector(*op['center_mm']) - point).Length, 1e-7)
                    self.assertEqual((op['diameter_mm'], op['depth_mm']), (2.01, 4.445))
                    self.assertEqual(op['diameter_limits_mm'], [2.0066, 2.02184])
                    self.assertEqual(op['depth_tolerance_mm'], [0, .0508])
                    self.assertEqual(op['projection_mm'], .555)
                    self.assert_inside(local_shape, (point.x, point.y, -2), False)
                    self.assert_inside(local_shape, (point.x, point.y, -5.1), True)
                self.assertLess(plate.get_object().Shape.common(iris.get_object().Shape).Volume, 1e-7)
            before = plate.get_object().Shape.Volume, len(self.doc.Objects)
            layout.recompute()
            self.assertEqual(len(self.doc.Objects), before[1])
            self.assertAlmostEqual(plate.get_object().Shape.Volume, before[0], places=6)

    def test_machined_rejects_floating_and_tilted_iris(self):
        layout = Layout('Invalid seating')
        iris = layout.add(catalog.create('iris', 'Iris'), (0, 0, 13.7), 0)
        machining.add(layout)
        with self.assertRaisesRegex(ValueError, 'float above plate'):
            layout.recompute()
        iris.get_object().BasePlacement = App.Placement(App.Vector(0, 0, 12.7),
                                                       App.Rotation('XYZ', 10, 0, 0))
        with self.assertRaisesRegex(ValueError, 'stand upright'):
            layout.recompute()

    def test_stop_transmission_and_blocking_with_placement(self):
        layout = Layout('Beam test')
        iris = layout.add(catalog.create('iris', 'Iris'), (10, 20, 12.7), 90)
        layout.recompute()
        interface = iris.interfaces()[0]
        self.assertIs(interface.parent, iris)
        for offset, transmitted in ((0, True), (.24, True), (.26, False), (1, False)):
            beam = BeamSegment(index=1, direction=(0, 1, 0), wavelength=1550,
                polarization=linear_polarization(), power=.001, waist_position=0, waist=.1)
            beam.get_object().BasePlacement = App.Placement(App.Vector(10 + offset, 0, 12.7),
                                                            App.Rotation())
            beam.compute_placement()
            beam.distance = 20
            self.assertIsNotNone(interface.get_intercept(beam))
            output = interface.get_output_beams(beam)
            self.assertEqual(len(output), int(transmitted))
            if output:
                self.assertEqual(output[0].power, beam.power)
                self.assertEqual(output[0].direction, beam.direction)

    def test_dimensions_do_not_follow_unit_preferences(self):
        original = get_measurement_system()
        self.addCleanup(set_measurement_system, original)
        volumes = []
        for system in ('metric', 'imperial'):
            set_measurement_system(system)
            volumes.append(catalog.AlignmentIris().shape().Volume)
        self.assertAlmostEqual(*volumes, places=7)

    def test_example_exports_and_reopens(self):
        from examples.iris_on_baseplate import build
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'iris_on_baseplate.FCStd'
            before = set(App.listDocuments())
            try:
                doc = build(path)
                self.assertEqual(len(json.loads(doc.Baseplate.MachiningPlan)['holes']), 2)
                App.closeDocument(doc.Name)
                reopened = App.openDocument(str(path))
                for name in ('Iris', 'Baseplate', 'DowelLeft', 'DowelRight'):
                    self.assertTrue(reopened.getObject(name).Shape.isValid())
                self.assertEqual(len(Part.read(str(path.with_suffix('.step'))).Solids), 4)
                self.assertEqual(len(Part.read(str(path.with_name('alignment_iris.step'))).Solids), 1)
            finally:
                for name in set(App.listDocuments()) - before:
                    App.closeDocument(name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
