"""Pinned detector, bracket fit, receiver trace and both plate drill workflows."""

import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

import FreeCAD as App
import Part

from PyOpticL import attachments, lab_catalog as catalog, machined_baseplate
from PyOpticL.beam_path import BeamPath
from PyOpticL.component_contract import ComponentContract
from PyOpticL.layout import Component, Layout
from PyOpticL.library import Baseplate
from PyOpticL.newport_detector import DetectorBracket, MountedPhotodetector, Photodetector818BB30, reference
from PyOpticL.schematic import compile_schematic
from PyOpticL.schematic.bounds import BoundsProvider
from PyOpticL.schematic.cad import add_baseplate
from PyOpticL.schematic.parts import part_spec
from PyOpticL.schematic.topology import resolve_topology
from PyOpticL.vendor_cad import resolve
from test_schematic_detector import detector_scene


class NewportDetectorTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('NewportDetectorAcceptance')
        self.addCleanup(lambda name=self.doc.Name: App.closeDocument(name) if name in App.listDocuments() else None)

    def test_purchased_source_and_optical_mounting_datums(self):
        r = reference()
        path = resolve(catalog.asset_record('818-BB-30'))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), r['step_sha256'])
        detector = Photodetector818BB30()
        shape = detector.shape()
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), r['source']['solids'])
        self.assertAlmostEqual(shape.Volume, r['source']['volume'], places=6)
        bounds = shape.optimalBoundingBox(False)
        for actual, expected in ((bounds.XMin, -33.7312), (bounds.XMax, 0),
                                 (bounds.YMax, 29.5656), (bounds.ZMin, -17.1958),
                                 (bounds.ZMax, 36.7792)):
            self.assertAlmostEqual(actual, expected, delta=.00001)
        contract = detector.contract()
        self.assertEqual({hole.thread for hole in contract.holes}, {'M4 x 0.7', '8-32 UNC'})
        self.assertEqual(ComponentContract.from_dict(contract.to_dict()).to_dict(), contract.to_dict())
        for h in r['mounting_holes']:
            p = App.Vector(*h['position_mm'])
            self.assertFalse(shape.isInside(p + App.Vector(0, 0, 1), 1e-7, False))
            self.assertTrue(shape.isInside(p + App.Vector(h['diameter_mm'] / 2 + .4, 0, 1), 1e-7, False))

    def test_bracket_fit_hardware_and_tool_clearance_at_supported_heights(self):
        self.assertEqual(DetectorBracket().optical_height, 25.4)
        self.assertEqual(catalog.native_height(catalog.create('photodetector', 'Default detector')), 25.4)
        detector = Photodetector818BB30().shape()
        for height in (25.4, 38.1, 50.8):
            with self.subTest(height=height):
                definition = MountedPhotodetector(height)
                bracket = DetectorBracket(height).shape()
                self.assertTrue(bracket.isValid())
                self.assertEqual(len(bracket.Solids), 1)
                self.assertLess(detector.common(bracket).Volume, 1e-7)
                self.assertLess(detector.distToShape(bracket)[0], 1e-7)
                self.assertEqual(len(definition.children), 7)
                for label, hardware, position, rotation in definition.children[2:]:
                    shape = transform_shape(hardware.shape(), position, rotation)
                    self.assertLess(shape.common(bracket).Volume, 1e-7, label)
                    common = shape.common(detector)
                    if label == 'M4 detector screw':
                        x, y, z = reference()['mounting_holes'][0]['position_mm']
                        threaded = Part.makeCylinder(2.001, 2.001, App.Vector(x, y, z))
                        self.assertLess(common.cut(threaded).Volume, 1e-7)
                        self.assertAlmostEqual(shape.BoundBox.ZMax, z + 2, delta=1e-6)
                    else:
                        self.assertLess(common.Volume, 1e-7, label)
                    if label == 'M4 plate screw':
                        tool = Part.makeCylinder(2, 100, App.Vector(*position))
                        self.assertLess(tool.common(detector).Volume, 1e-7)
                contract = DetectorBracket(height).contract()
                self.assertEqual(len(contract.holes), 5)
                self.assertEqual(ComponentContract.from_dict(contract.to_dict()).to_dict(), contract.to_dict())
        for bad in (25.3, 0, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                DetectorBracket(bad)

    def test_attachment_contract_and_both_transformed_drilling_workflows(self):
        root = Layout('Detector plate scene')
        root.get_object().BasePlacement = App.Placement(App.Vector(20, 30, 4), App.Rotation('XYZ', 0, 0, 17))
        nested = root.add(Layout('Nested detector'), (100, 100, 0), 29)
        detector = nested.add(catalog.create('photodetector', 'PD', optical_height=25.4), (0, 0, 25.4), 13)
        regular = root.add(Component('Ordinary plate', Baseplate((240, 240, 20), optical_height=0,
            grid_offset=(0, 0)), recompute_priority=-2), (0, 0, 0), 0)
        plate, machining = machined_baseplate.add(root, thickness=20)
        root.recompute()
        self.assertEqual(catalog.native_height(detector), 25.4)
        bracket = detector.get_object().Children[1]
        expected = attachments.operations(bracket.Proxy, root.get_object().Placement.inverse() * bracket.Placement)
        self.assertEqual(len(expected), 4)
        self.assertEqual({o['interface'] for o in expected}, {'plate_1', 'plate_2', 'pin_1', 'pin_2'})
        self.assertEqual(sum(o['kind'] == 'tapped' for o in expected), 2)
        self.assertEqual(len(machining.plan['holes']), 4)
        for actual, desired in zip(machining.plan['holes'], expected):
            self.assertLess((App.Vector(*actual['center_mm']) - App.Vector(*desired['center_mm'])).Length, 1e-7)
            point = root.get_object().Placement.multVec(App.Vector(*desired['center_mm']) - App.Vector(0, 0, 1))
            self.assertFalse(regular.get_object().Shape.isInside(point, 1e-7, False))
            self.assertFalse(plate.get_object().Shape.isInside(point, 1e-7, False))
        count, volume = len(self.doc.Objects), plate.get_object().Shape.Volume
        root.recompute()
        self.assertEqual(len(self.doc.Objects), count)
        self.assertAlmostEqual(plate.get_object().Shape.Volume, volume, places=6)

    def test_recess_widens_only_the_bnc_side_in_nested_rotated_placements(self):
        root = Layout('Recessed detector access')
        root.get_object().BasePlacement = App.Placement(App.Vector(20,30,4),
                                                       App.Rotation('XYZ',0,0,17))
        nested = root.add(Layout('Rotated detector'), (100,100,0), 29)
        detector = nested.add(catalog.create('photodetector', 'PD'), (0,0,9.875), 13)
        plate, machining = machined_baseplate.add(root, position=(0,0,3), thickness=36, margin=100)
        root.recompute()
        bracket = detector.get_object().Children[1]
        local = bracket.Shape.copy(); local.Placement = App.Placement()
        bounds = local.optimalBoundingBox(False)
        relative = plate.get_object().Placement.inverse()*bracket.Placement
        pocket = machining.plan['pockets'][0]
        origin = relative.inverse().multVec(App.Vector(*pocket['origin_mm']))
        self.assertEqual(pocket['orientation'], 'mount')
        self.assertEqual(pocket['recess_side_scale_xy'], {'y_plus': 1.5})
        self.assertAlmostEqual(pocket['size_mm'][0], bounds.XLength+.5)
        self.assertAlmostEqual(pocket['size_mm'][1], 1.5*(bounds.YLength+.5))
        self.assertAlmostEqual(origin.x, bounds.XMin-.25)
        self.assertAlmostEqual(origin.y, bounds.YMin-.25)
        self.assertAlmostEqual(origin.z, -25.4)
        # The new BNC access area is open above the unchanged supporting floor.
        probe = App.Vector(bounds.Center.x, bounds.YMax+.25+(bounds.YLength+.5)/4, -23.4)
        shape = plate.get_object().Shape
        self.assertFalse(shape.isInside(bracket.Placement.multVec(probe),1e-7,False))
        probe.z = -25.5
        self.assertTrue(shape.isInside(bracket.Placement.multVec(probe),1e-7,False))
        trimmed = App.Vector(bounds.Center.x, bounds.YMax+.25+.75*(bounds.YLength+.5), -23.4)
        self.assertTrue(shape.isInside(bracket.Placement.multVec(trimmed),1e-7,False))
        for x,y in ((bounds.Center.x,bounds.YMin-1.25),
                    (bounds.XMin-1.25,bounds.Center.y), (bounds.XMax+1.25,bounds.Center.y)):
            self.assertTrue(shape.isInside(bracket.Placement.multVec(App.Vector(x,y,-23.4)),1e-7,False))
        expected = attachments.operations(bracket.Proxy, relative)
        self.assertEqual(len(machining.plan['holes']),4)
        for actual, desired in zip(machining.plan['holes'],expected):
            self.assertLess((App.Vector(*actual['center_mm'])-App.Vector(*desired['center_mm'])).Length,1e-7)
        volume = shape.Volume
        root.recompute()
        self.assertAlmostEqual(plate.get_object().Shape.Volume,volume,places=6)

    def test_receiver_active_area_and_acceptance_cone(self):
        for offset, angle, expected_hit in ((0, 0, True), (.04, 0, True), (.06, 0, False),
                                             (0, 19, True), (0, 21, False), (0, 180, False)):
            with self.subTest(offset=offset, angle=angle):
                root = Layout('Receiver trace')
                detector = root.add(catalog.create('818-BB-30', 'PD'), (0, 0, 0), 0)
                a = math.radians(angle)
                source = (30 * math.cos(a), 30 * math.sin(a) + offset, 0)
                beam = root.add(BeamPath('Receiver beam', wavelength=1550, waist=.02, bound_parent=root),
                                source, 180 + angle)
                root.recompute()
                self.assertEqual(beam.get_object().BeamSegments[0].EndObject == detector.get_object(), expected_hit)

    def test_schematic_export_complete_bounds_plate_and_reopen(self):
        for preset in ('bare', 'bracketed'):
            with self.subTest(preset=preset):
                document = detector_scene(preset)
                spec = part_spec(document, document.nodes[1], resolve_topology(document))
                bounds = BoundsProvider().get(spec)
                self.assertIsNone(bounds.error, bounds.error)
                self.assertGreater(bounds.circle.radius_mm, 16)
                compiled = compile_schematic(document)
                self.assertTrue(compiled.ok, compiled.diagnostics)
                namespace = {'__name__': 'detector_test'}
                exec(compiled.source, namespace)
                layout = namespace['build_layout']()
                if preset == 'bracketed':
                    plate = add_baseplate(layout, thickness=12.7).get_object()
                    self.assertEqual(len(json.loads(plate.MachiningPlan)['holes']), 4)
                    with tempfile.TemporaryDirectory() as folder:
                        path = Path(folder) / 'detector.FCStd'
                        self.doc.saveAs(str(path))
                        plate_name, machining = plate.Name, json.loads(plate.MachiningPlan)
                        App.closeDocument(self.doc.Name)
                        reopened = App.openDocument(str(path))
                        try:
                            restored = reopened.getObject(plate_name)
                            self.assertTrue(restored.Shape.isValid())
                            self.assertEqual(json.loads(restored.MachiningPlan), machining)
                        finally:
                            App.closeDocument(reopened.Name)


def transform_shape(shape, position, rotation):
    result = Part.makeCompound([shape])
    result.Placement = App.Placement(App.Vector(*position), App.Rotation('XYZ', *rotation))
    return result


if __name__ == '__main__':
    unittest.main()
