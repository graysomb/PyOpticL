"""Exact source, seating, finite D aperture, drilling and export acceptance."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
import FreeCAD as App
import Part

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PyOpticL import attachments, lab_catalog as catalog, machined_baseplate
from PyOpticL.beam_path import BeamPath, BeamSegment, circular_polarization
from PyOpticL.component_contract import ComponentContract
from PyOpticL.d_mirror import reference
from PyOpticL.layout import Component, Layout
from PyOpticL.library import Baseplate
from PyOpticL.vendor_cad import resolve
from examples import d_mirrors as demo

MOUNTS = ('KM05DR', 'KM100D', 'KM05DL', 'KM100DL')

# Datum checks use exact surfaces: cached display triangulations can expand
# bounding boxes by hundredths of a millimetre after the GUI meshes a shape.


class DMirrorTests(unittest.TestCase):
    def setUp(self):
        self.before = set(App.listDocuments())
        self.doc = App.newDocument('DMirrorAcceptance')
        self.addCleanup(self.close_documents)

    def close_documents(self):
        for name in set(App.listDocuments()) - self.before:
            App.closeDocument(name)

    def assert_vector(self, actual, expected):
        self.assertLess((App.Vector(*actual) - App.Vector(*expected)).Length, 1e-7)

    def test_exact_sources_and_closed_shell_promotion(self):
        for part, expected in reference()['parts'].items():
            with self.subTest(part=part):
                for kind in ('step', 'pdf'):
                    record = json.loads((catalog.DATA/'assets'/f'{part}.{kind}.json').read_text())
                    self.assertEqual(hashlib.sha256(resolve(record).read_bytes()).hexdigest(),
                                     expected['source_'+('step' if kind=='step' else 'drawing')+'_sha256'])
                raw = Part.read(str(resolve(catalog.asset_record(part))))
                self.assertTrue(raw.isValid())
                self.assertEqual(len(raw.Solids), expected['source_solid_count'])
                source = catalog.vendor_shape(part)
                self.assertTrue(source.isValid())
                self.assertAlmostEqual(source.Volume, expected['source_volume_mm3'], places=5)
                self.assertEqual(len(source.Faces), len(raw.Faces))
                self.assertAlmostEqual(source.Area, raw.Area, places=7)
                for a,b in zip(source.Faces, raw.Faces):
                    self.assertAlmostEqual(a.Area,b.Area,places=7)
                    self.assert_vector(a.CenterOfMass,b.CenterOfMass)
                if part == 'PFD10-03-P01':
                    self.assertEqual(len(raw.Solids), 0)
                    self.assertTrue(raw.Shells[0].isClosed())
                    self.assertEqual(len(source.Solids), 1)
                    self.assertAlmostEqual(source.Area, raw.Area, places=8)
                copy = catalog.vendor_shape(part)
                copy.translate(App.Vector(300, 0, 0))
                self.assertAlmostEqual(catalog.vendor_shape(part).optimalBoundingBox(False).XMin,
                                       source.optimalBoundingBox(False).XMin)

    def test_mount_contracts_and_source_attachment_axes(self):
        for mount in MOUNTS:
            definition = catalog.VendorPart(mount)
            contract = definition.contract()
            self.assertEqual(contract, ComponentContract.from_dict(contract.to_dict()))
            self.assertEqual(len(contract.holes), 2)
            self.assertEqual({h.thread for h in contract.holes}, {'8-32 UNC'} if mount.startswith('KM05') else {None})
            self.assertEqual(len(attachments.operations(definition)), 1)
            self.assertEqual(definition.baseplate_profile()['dowels'], [])
            cylinders = [f.Surface for f in catalog.vendor_shape(mount).Faces if isinstance(f.Surface, Part.Cylinder)]
            for hole in reference()['parts'][mount]['physical_mounting_features']:
                axis, center = App.Vector(*hole['axis']), App.Vector(*hole['center'])
                self.assertTrue(any(abs(c.Radius-hole['diameter']/2)<1e-6 and
                    abs(abs(c.Axis.dot(axis))-1)<1e-7 and
                    (c.Center-center).cross(axis).Length<1e-6 for c in cylinders))

    def test_native_heights_seating_clamps_and_bom(self):
        for mount in MOUNTS:
            height = reference()['pairs'][mount]['native_beam_height_mm']
            component = catalog.create('d_mirror', mount, mount=mount)
            component.recompute()
            optic, holder = component.get_object().Children
            self.assertAlmostEqual(catalog.native_height(component), height, places=6)
            self.assertEqual(len(optic.Shape.Solids), 1)
            self.assertEqual(len(holder.Shape.Solids), 26 if mount.startswith('KM05') else 22)
            self.assertLess(sum(optic.Shape.common(s).Volume for s in holder.Shape.Solids), 1e-6)
            self.assertLess(optic.Shape.distToShape(holder.Shape)[0], 1e-7)
            self.assertLess(optic.Shape.distToShape(holder.Shape.Solids[reference()['parts'][mount]['seating_solid']])[0], 1e-7)
            for a,b in zip(holder.Shape.Solids, catalog.VendorPart(mount).shape().Solids):
                self.assertAlmostEqual(a.Volume, b.Volume, places=6)
            if mount.startswith('KM05'):
                for index in reference()['pairs'][mount]['seated_clamp_offsets_mm']:
                    i = int(index)
                    self.assertLess(optic.Shape.distToShape(holder.Shape.Solids[i])[0], 1e-7)
            rows = catalog.bom(component)
            self.assertEqual(len(rows), 2)
            self.assertEqual({r['procurement'] for r in rows}, {'purchased'})
            hardware = rows[1]['mounting_hardware']
            self.assertEqual(len(hardware), 1)
            self.assertIn('8-32' if mount.startswith('KM05') else 'M4', hardware[0]['kind'])
            b = optic.Shape.optimalBoundingBox(False)
            r = reference()['pairs'][mount]['radius_mm']
            self.assertAlmostEqual(b.XMin, -6, places=5)
            self.assertAlmostEqual(b.XMax, 0, places=5)
            self.assertAlmostEqual(b.ZMax, 1, places=5)
            self.assertAlmostEqual(b.ZMin, 1-r, places=5)

    def test_coated_face_orientation_and_left_right_hardware(self):
        # Independent native S1 planes/normals; zero overlap alone also permits
        # a backwards optic. KM05DL's semicircle opens along native -X.
        source_fronts = {'KM05DR': (14.6558, (0,0,1)),
                         'KM05DL': (2.032, (0,0,1)),
                         'KM100D': (6.35, (0,0,1)),
                         'KM100DL': (-6.35, (0,0,-1))}
        for mount, (z, normal) in source_fronts.items():
            with self.subTest(mount=mount):
                component = catalog.create('d_mirror', mount, mount=mount)
                component.recompute()
                optic, holder = component.get_object().Children
                definition = holder.Proxy
                rotation = App.Rotation('XYZ', *definition.rotation)
                native_to_component = App.Placement(-rotation.multVec(App.Vector(*definition.origin)), rotation)
                component_to_native = native_to_component.inverse()
                fronts = [f for f in optic.Shape.Faces if isinstance(f.Surface, Part.Plane)
                          and f.normalAt(0,0).x > .999999 and abs(f.CenterOfMass.x) < 1e-7]
                self.assertEqual(len(fronts), 1)
                front = fronts[0]
                self.assertAlmostEqual(component_to_native.multVec(front.CenterOfMass).z,z,places=6)
                self.assert_vector(component_to_native.Rotation.multVec(front.normalAt(0,0)), normal)
                self.assert_vector(component_to_native.Rotation.multVec(
                    App.Vector(*component.interfaces()[0].normal)), normal)
                for index in reference()['pairs'][mount].get('seated_clamp_offsets_mm', {}):
                    self.assertAlmostEqual(holder.Shape.Solids[int(index)].optimalBoundingBox(False).XMax,-6,places=6)
                # Above the open edge only the upright arm remains. Its side
                # must reverse for the exact left-handed source, with no
                # reflection/negative scale applied to purchased geometry.
                upper = holder.Shape.common(Part.makeBox(200,200,100,
                    App.Vector(-100,-100,6 if mount.startswith('KM05') else 13)))
                self.assertGreater(len(upper.Solids),0)
                sign = -1 if mount in ('KM05DL','KM100DL') else 1
                center_y = sum(s.Volume * s.CenterOfMass.y for s in upper.Solids) / upper.Volume
                self.assertGreater(sign * center_y, 1)

    def ray(self, optic, hit, direction=(-1,0,0)):
        optic.compute_placement()
        placement = optic.get_object().Placement
        d = App.Vector(*direction); d.normalize()
        beam = BeamSegment(index=1, direction=direction, wavelength=1550,
            polarization=circular_polarization(), power=.001, waist=.2, waist_position=10)
        beam.get_object().BasePlacement = placement * App.Placement(App.Vector(*hit)-50*d, App.Rotation())
        beam.compute_placement(); beam.distance = 50
        interface = optic.get_interfaces()[0] if hasattr(optic, 'get_interfaces') else optic.get_object().Proxy.interfaces()[0]
        interface.parent = optic
        return beam, interface

    def test_finite_d_aperture_edge_and_grazing(self):
        for part in ('PFD05-03-P01', 'PFD10-03-P01'):
            optic = catalog.create(part, part); optic.recompute()
            r = reference()['parts'][part]['radius_mm']
            for hit, physical, reflects in [((0,0,0),True,True),
                    ((0,0,1+.01),False,False), ((0,1.1*r,0),False,False),
                    ((0,0,1-.05),True,False), ((0,.95*r,1-.5),True,False)]:
                with self.subTest(part=part, hit=hit):
                    beam, interface = self.ray(optic, hit)
                    self.assertEqual(interface.get_intercept(beam) is not None, physical)
                    self.assertEqual(len(interface.get_output_beams(beam)), int(reflects))
            beam, interface = self.ray(optic, (0,0,0), (0,1,0))
            self.assertIsNone(interface.get_intercept(beam))
            beam, interface = self.ray(optic, (0,0,0), (1,0,0))
            self.assertIsNone(interface.get_intercept(beam))

    def test_reflection_under_nested_roll_yaw_and_translation(self):
        root = Layout('Nested optical transforms')
        root.get_object().BasePlacement = App.Placement(App.Vector(11,-23,7), App.Rotation('XYZ',19,-13,37))
        optic = root.add(catalog.create('PFD10-03-P01', 'Mirror'), (31,17,4), (31,0,27))
        root.recompute()
        direction = np.array([-.96,.2,.1]); direction /= np.linalg.norm(direction)
        beam, interface = self.ray(optic, (0,1,0), direction)
        output = interface.get_output_beams(beam)
        self.assertEqual(len(output), 1)
        output[0].compute_placement()
        expected = direction.copy(); expected[0] *= -1
        expected = optic.get_object().Placement.Rotation.multVec(App.Vector(*expected))
        self.assert_vector(output[0].get_global_direction(), expected)
        self.assertAlmostEqual(output[0].power, beam.power)
        self.assertAlmostEqual(output[0].waist_position, beam.waist_position-50, places=8)
        self.assertAlmostEqual(output[0].rayleigh_range, beam.rayleigh_range, places=8)
        self.assertTrue(np.allclose(output[0].polarization_jones, beam.polarization_jones))

    def test_actual_beam_path_and_downstream_placement(self):
        for mount in MOUNTS:
            root = Layout('Optical '+mount)
            component = root.add(catalog.create('d_mirror', mount, mount=mount), (0,0,0), 135)
            beam = root.add(BeamPath('Incident', wavelength=1550, waist=.2, power=.001,
                bound_parent=root), (-50,0,0), 0)
            receiver = beam.add(Component('Receiver',demo.Receiver()),1,0,distance=40,after_object=component)
            root.recompute()
            segments = beam.get_object().BeamSegments
            self.assertEqual(len(segments),2)
            self.assert_vector(segments[1].Proxy.get_global_direction(), (0,1,0))
            self.assertAlmostEqual(sum(s.Proxy.distance for s in segments),90,places=7)
            self.assert_vector(receiver.get_object().Placement.Base, (0,40,0))
            self.assertEqual(beam.get_output_indices(component), [1])
            self.assert_vector(beam.measure_properties(component).position, (50,0,0))

    def test_open_half_transmits_past_mirror_and_border_terminates(self):
        for mount in MOUNTS:
            radius = reference()['pairs'][mount]['radius_mm']
            for z, blocked in ((1+.5, False), (1-.05, True)):
                root = Layout('Knife edge ray')
                component = root.add(catalog.create('d_mirror',mount,mount=mount),(0,0,0),135)
                receiver = root.add(Component('Straight receiver',demo.Receiver()),(50,0,z),0)
                beam = root.add(BeamPath('Ray',wavelength=1550,waist=.2,bound_parent=root),(-50,0,z),0)
                root.recompute()
                segments = beam.get_object().BeamSegments
                self.assertEqual(len(segments),1)
                self.assertEqual(segments[0].EndObject,component.get_object() if blocked else receiver.get_object())
                self.assertAlmostEqual(segments[0].Proxy.distance,50 if blocked else 100,places=6)
                self.assertEqual(beam.get_output_indices(component),[])

    def test_both_plate_workflows_nested_transforms_recompute_and_moves(self):
        root = Layout('Nested plate')
        root.get_object().BasePlacement = App.Placement(App.Vector(21,-17,6), App.Rotation('XYZ',0,0,19))
        components = []
        for i,mount in enumerate(MOUNTS):
            group = root.add(Layout('Group'), (60+i*140,70,0), 17)
            component = group.add(catalog.create('d_mirror',mount,mount=mount),(0,0,0),31)
            component.get_object().BasePlacement.Base.z = catalog.native_height(component)
            components.append(component)
        plate, machining = machined_baseplate.add(root, thickness=30)
        ordinary = root.add(Component('Ordinary',Baseplate((650,160,30),optical_height=0,
            grid_offset=(0,0)),recompute_priority=-2),(0,0,0),0)
        root.recompute()
        self.assertEqual(len(machining.plan['holes']),len(MOUNTS))
        self.assertEqual(len(machining.plan['pockets']),2)
        self.assertIsNone(machining.plan['optical_height_mm'])
        for target in (plate,ordinary):
            shape = target.get_object().Shape
            self.assertTrue(shape.isValid())
            for op in machining.plan['holes']:
                point = root.get_object().Placement.multVec(App.Vector(*op['center_mm'])-App.Vector(0,0,2))
                self.assertFalse(shape.isInside(point,1e-7,False))
            for component in components:
                for child in component.get_object().Children:
                    self.assertLess(sum(shape.common(s).Volume for s in child.Shape.Solids),1e-5)
        old = App.Vector(*machining.plan['holes'][0]['center_mm'])
        components[0].get_object().BasePlacement.Base.x += 17
        root.recompute()
        for target in (plate,ordinary):
            self.assertTrue(target.get_object().Shape.isInside(
                root.get_object().Placement.multVec(old-App.Vector(0,0,2)),1e-7,False))
        volumes = [t.get_object().Shape.Volume for t in (plate,ordinary)]
        count = len(self.doc.Objects); root.recompute()
        self.assertEqual(len(self.doc.Objects),count)
        for target,volume in zip((plate,ordinary),volumes):
            self.assertAlmostEqual(target.get_object().Shape.Volume,volume,places=6)

    def test_profiles_footprints_and_rejected_stock(self):
        for mount in MOUNTS:
            definition = catalog.VendorPart(mount)
            op = attachments.operations(definition)[0]
            self.assertEqual(op['kind'],'tapped')
            self.assertEqual(op['thread'],'8-32 UNC' if mount.startswith('KM05') else 'M4 x 0.7')
            self.assertAlmostEqual(op['diameter_mm'],3.4544 if mount.startswith('KM05') else 3.3)
            footprint = definition.drill()
            self.assertTrue(footprint.isValid())
            self.assertEqual(len(footprint.Solids),1 if mount.startswith('KM05') else 2)
            root = Layout('Thin '+mount)
            component = root.add(catalog.create('d_mirror',mount,mount=mount),(0,0,0),0)
            component.get_object().BasePlacement.Base.z = catalog.native_height(component)
            _,md = machined_baseplate.add(root,thickness=10.5)
            with self.assertRaisesRegex(ValueError,'stock|Blind hole'):
                root.recompute()

    def test_nominal_mounting_screw_and_stud_engagement(self):
        for mount in MOUNTS:
            component = catalog.create('d_mirror',mount,mount=mount)
            component.get_object().BasePlacement.Base.z = catalog.native_height(component)
            component.recompute()
            optic,holder = component.get_object().Children
            center = App.Vector(*attachments.operations(holder.Proxy,holder.Placement)[0]['center_mm'])
            if mount.startswith('KM05'):
                hardware = Part.makeCylinder(4.1656/2,6.35,center-App.Vector(0,0,3.175))
                self.assertAlmostEqual(hardware.optimalBoundingBox(False).ZMax,3.175,places=6)
                self.assertAlmostEqual(hardware.optimalBoundingBox(False).ZMin,-3.175,places=6)
            else:
                hardware = catalog.NominalScrew('M4 x 12',4,.7,12,7,4).shape()
                hardware.translate(center+App.Vector(0,0,4.31801))
                self.assertAlmostEqual(hardware.optimalBoundingBox(False).ZMin,-7.68199,places=5)
            self.assertLess(sum(hardware.common(s).Volume for s in holder.Shape.Solids),1e-5)
            self.assertLess(hardware.common(optic.Shape).Volume,1e-6)

    def test_common_factory_returns_definitions_without_creating_components(self):
        from PyOpticL.d_mirror import DMirror, MountedDMirror
        before = {obj.Name for obj in self.doc.Objects}
        for mount in MOUNTS:
            definition = catalog.definition('d_mirror', mount=mount)
            self.assertIsInstance(definition, MountedDMirror)
            self.assertIsInstance(catalog.definition('mirror', mount=mount, thickness=6), MountedDMirror)
        for part in ('PFD05-03-P01', 'PFD10-03-P01'):
            self.assertIsInstance(catalog.definition(part), DMirror)
        self.assertEqual({obj.Name for obj in self.doc.Objects}, before)

    def test_api_validation_and_instance_isolation(self):
        for part in (*MOUNTS,'PFD05-03-P01','PFD10-03-P01'):
            component = catalog.create(part,part); component.recompute()
            self.assertTrue(component.get_object().Shape.isValid())
        for mount in MOUNTS:
            a,b = [catalog.create('mirror', 'D',mount=mount,thickness=6) for _ in range(2)]
            a.recompute();b.recompute()
            self.assertNotEqual(a.get_object().Name,b.get_object().Name)
            a.children.clear()
            self.assertEqual(len(b.children),2)
        with self.assertRaises(ValueError):catalog.create('d_mirror','Bad',mount='KM100D',optic='PFD05-03-P01')
        with self.assertRaises(ValueError):catalog.create('d_mirror','Bad',mount='KM05DR/M')
        with self.assertRaises(TypeError):catalog.create('mirror','Bad',mount='KM05DR',thickness=3)
        with self.assertRaises(TypeError):catalog.create('PFD05-03-P01','Bad',diameter=12.7)

    def test_edge_distance_selects_datum_without_resizing_parts(self):
        for mount in MOUNTS:
            circle_height = reference()['parts'][mount]['native_circle_center_height_mm']
            last = None
            for distance in (.5,1.,2.):
                root = Layout('Selectable edge distance')
                component = root.add(catalog.create('d_mirror',mount,mount=mount,
                    edge_distance=distance),(0,0,circle_height-distance),0)
                root.recompute()
                optic,holder = component.get_object().Children
                self.assertAlmostEqual(catalog.native_height(component),circle_height-distance)
                self.assertAlmostEqual(holder.Proxy.baseplate_profile()['optical_height_mm'],circle_height-distance)
                self.assertAlmostEqual(optic.Shape.optimalBoundingBox(False).ZMax,circle_height,places=5)
                self.assertAlmostEqual(attachments.operations(holder.Proxy,holder.Placement)[0]['center_mm'][2],0,places=5)
                if last:
                    self.assertAlmostEqual(optic.Shape.Volume,last[0],places=6)
                    self.assertAlmostEqual(holder.Shape.Volume,last[1],places=6)
                last = optic.Shape.Volume,holder.Shape.Volume
            for value in (-1,0,.1,float('nan'),float('inf'),20):
                with self.assertRaises(ValueError):
                    catalog.create('d_mirror','Bad',mount=mount,edge_distance=value)

    def test_demo_export_reopen_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'d_mirrors.FCStd'
            static,report = demo.build(output)
            self.assertEqual({sample['mount'] for sample in report['samples']},set(MOUNTS))
            self.assertEqual(report['export']['solids'],101)
            expected = {o.Name:(o.Shape.Volume,len(o.Shape.Solids)) for o in static.Objects if hasattr(o,'Shape')}
            App.closeDocument(static.Name); static = App.openDocument(str(output))
            for name,(volume,count) in expected.items():
                obj = static.getObject(name)
                self.assertFalse(hasattr(obj,'Proxy'))
                self.assertTrue(obj.Shape.isValid())
                self.assertEqual(len(obj.Shape.Solids),count)
                self.assertAlmostEqual(obj.Shape.Volume,volume,places=6)
            plate = Part.read(str(output.with_name(output.stem+'_baseplate.step')))
            self.assertTrue(plate.isValid());self.assertEqual(len(plate.Solids),1)
            self.assertEqual(len(json.loads(output.with_suffix('.machining.json').read_text())['holes']),4)


if __name__ == '__main__':
    unittest.main(verbosity=2)
