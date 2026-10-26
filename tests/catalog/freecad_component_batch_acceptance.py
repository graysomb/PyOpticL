"""Independent source-datum, assembly, drilling and optical batch acceptance."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

import FreeCAD as App
import Part

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PyOpticL import attachments, lab_catalog as catalog, machined_baseplate
from PyOpticL.beam_path import BeamSegment, linear_polarization
from PyOpticL.component_contract import ComponentContract, connection_check
from PyOpticL.layout import Component, Layout
from PyOpticL.library import Baseplate
from PyOpticL.vendor_cad import resolve


SAMPLES = [('POLARIS-L05G', {}), ('POLARIS-L1G', {}),
           ('mirror', {'mount': 'POLARIS-K1VS2'}),
           ('mirror', {'mount': 'MHV-12.7L-R'}), ('mirror', {'mount': 'MHV-25.4L-R'}),
           ('rotation', {'mount': 'FBR'}), ('slit', {}), ('coupling', {})]


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = App.newDocument('ComponentBatchAcceptance')
        cls.addClassCleanup(App.closeDocument, cls.doc.Name)
        cls.reference = json.loads((catalog.DATA / 'batch_measurements.json').read_text())['parts']

    def test_sources_and_independent_datums(self):
        for pn, expected in self.reference.items():
            with self.subTest(part=pn):
                definition = catalog.VendorPart(pn)
                contract = definition.contract()
                self.assertEqual(contract, ComponentContract.from_dict(contract.to_dict()))
                for kind in ('step', 'pdf'):
                    record = json.loads((catalog.DATA / 'assets' / (pn + '.' + kind + '.json')).read_text())
                    self.assertEqual(record['sha256'], expected['step_sha256' if kind == 'step' else 'drawing_sha256'])
                    self.assertTrue(resolve(record).exists())
                component = catalog.create(pn, pn)
                rows = catalog.bom(component)
                self.assertEqual(rows[0]['part_number'], pn)
                if pn in ('POLARIS-L05G', 'POLARIS-L1G'):
                    self.assertEqual(rows[1]['procurement'], 'included')
                    self.assertEqual(rows[1]['catalog_id'], 'flat washer')
                source = catalog.vendor_shape(pn)
                self.assertTrue(source.isValid())
                self.assertEqual(len(source.Solids), expected['solid_count'])
                self.assertAlmostEqual(source.Volume, expected['volume_mm3'], places=5)
                frames = {f.name: f for f in contract.frames}
                self.assertAlmostEqual(-frames['mounting_face'].position[2], expected['native_optical_height_mm'], places=5)
                seat = App.Vector(*expected['mounting_face'])
                # Verify the selected physical seat in the untouched source solid.
                self.assertTrue(any(isinstance(f.Surface, Part.Plane) and
                    abs((f.CenterOfMass - seat).dot(f.normalAt(0, 0))) < .01 and
                    f.Area > 20 for f in source.Faces))
                cylinders = [f.Surface for f in source.Faces if isinstance(f.Surface, Part.Cylinder)]
                for h in expected['native_holes']:
                    centers = h.get('slot_arc_centers_native', [h['center']])
                    for center in centers:
                        axis, point = App.Vector(*h['axis']), App.Vector(*center)
                        self.assertTrue(any(abs(c.Radius - h['diameter']/2) < .01 and
                            abs(abs(c.Axis.dot(axis)) - 1) < 1e-6 and
                            (c.Center - point).cross(axis).Length < .01 for c in cylinders), (pn, h['name'], center))

    def test_mirrors_are_seated_and_size_specific(self):
        for pn, diameter in [('POLARIS-K1VS2', 25.4), ('MHV-12.7L-R', 12.7), ('MHV-25.4L-R', 25.4)]:
            obj = catalog.create('mirror', pn, mount=pn)
            obj.recompute()
            optic, mount = obj.get_object(), obj.get_object().Children[0]
            self.assertAlmostEqual(optic.Shape.BoundBox.YLength, diameter, places=5)
            self.assertLess(optic.Shape.distToShape(mount.Shape)[0], .01)
            # The MHV source plate has a documented sub-0.01 mm nominal pose error.
            self.assertLess(sum(optic.Shape.common(s).Volume for s in mount.Shape.Solids), .001)
            self.assertAlmostEqual(catalog.native_height(obj), self.reference[pn]['native_optical_height_mm'], places=5)
            interface = obj.interfaces()[0]
            obj.get_object().BasePlacement.Rotation = App.Rotation('XYZ', 0, 0, 135)
            obj.compute_placement()
            beam = self.beam(App.Vector(-20, 0, 0))
            output = interface.get_output_beams(beam)
            self.assertEqual(len(output), 1)
            self.assertLess((App.Vector(*output[0].direction) - App.Vector(0, 1, 0)).Length, 1e-7)

    def test_corrected_coupler_seating_threads_and_bom(self):
        obj = catalog.create('coupling', 'Corrected coupler')
        obj.recompute()
        col, adapter, mount = obj.get_object().Children
        self.assertEqual(mount.Proxy.part, 'POLARIS-K05T6')
        self.assertEqual(len(mount.Shape.Solids), 30)
        frames = {f.name: f for f in adapter.Proxy.contract().frames}
        self.assertAlmostEqual(frames['collimator_opening'].position[0], -2.9972, places=5)
        self.assertAlmostEqual(mount.BasePlacement.Base.x, 8.0518, places=5)
        self.assertLess(adapter.Shape.distToShape(mount.Shape)[0], 1e-7)
        for child in (adapter, mount):
            self.assertLess(sum(col.Shape.common(s).Volume for s in child.Shape.Solids), 1e-7)
        # Male/female simplified CAD threads can overlap within their engagement.
        shell = Part.makeCylinder(6.795, 3.17502, App.Vector(8.05179, 0, 0), App.Vector(1, 0, 0)).cut(
            Part.makeCylinder(6.4515, 3.17504, App.Vector(8.05178, 0, 0), App.Vector(1, 0, 0)))
        for solid in mount.Shape.Solids:
            self.assertLess(adapter.Shape.common(solid).cut(shell).Volume, 1e-5)
        pairs = catalog.connection_interfaces()
        self.assertTrue(connection_check(pairs['AD1109F-out'], pairs['POLARIS-K05T6'])[0])
        rows = catalog.bom(obj)
        rings = [r for r in rows if r['part_number'] == 'POLARIS-SM05RR']
        self.assertEqual(len(rings), 2)
        self.assertEqual(sum('uninstalled' in r['disposition'] for r in rings), 1)
        ops = attachments.operations(mount.Proxy)
        self.assertEqual([o['kind'] for o in ops].count('dowel'), 2)
        self.assertTrue(all(o['depth_mm'] == 4.699 for o in ops if o['kind'] == 'dowel'))
        legacy = catalog.create('coupling', 'Legacy coupler', mount='KA05TA')
        legacy.recompute()
        self.assertEqual(len(legacy.get_object().Children[2].Shape.Solids), 23)
        self.assertEqual([o['kind'] for o in attachments.operations(legacy.get_object().Children[2].Proxy)], ['tapped'])

    def test_fbr_seating_retaining_ring_and_polarization(self):
        for angle, expected in [(0, 0), (45, 1)]:
            obj = catalog.create('rotation', 'FBR waveplate', mount='FBR', fast_axis_angle=angle)
            obj.recompute()
            optic = obj.get_object().Children[0]
            mount = optic.Children[0]
            self.assertEqual(len(obj.get_object().Children), 1)  # No ELL16 holder.
            self.assertLess(sum(optic.Shape.common(s).Volume for s in mount.Shape.Solids), 1e-6)
            self.assertLess(optic.Shape.distToShape(mount.Shape)[0], 1e-7)
            self.assertAlmostEqual(catalog.native_height(obj), 14.3002, places=5)
            beam = self.beam(App.Vector(-20, 0, 0))
            output = optic.Proxy.interfaces()[0].get_output_beams(beam)
            self.assertEqual(len(output), 1)
            jones = output[0].polarization_jones
            self.assertAlmostEqual(abs(complex(*jones[expected])), 1, places=6)
            self.assertAlmostEqual(abs(complex(*jones[1-expected])), 0, places=6)
            profile = mount.Proxy.baseplate_profile()
            self.assertEqual(profile['dowel']['plate_diameter_mm'], 3.2)
            self.assertEqual(profile['dowel']['pin_projection_mm'], 4.7752)

    @staticmethod
    def beam(position):
        beam = BeamSegment(index=1, direction=(1, 0, 0), wavelength=1550,
                           polarization=linear_polarization(), power=.001, waist_position=0, waist=.1)
        beam.get_object().BasePlacement = App.Placement(position, App.Rotation())
        beam.compute_placement()
        beam.distance = 20
        return beam

    def test_slit_width_orientation_bracket_and_reference_cad(self):
        source_volume = self.reference['VA100']['volume_mm3']
        for width in (0, 1, 6):
            for roll in (0, 90):
                slit = catalog.create('slit', 'VA100', slit_width=width)
                slit.get_object().BasePlacement = App.Placement(App.Vector(0, 0, 0), App.Rotation('XYZ', roll, 0, 0))
                slit.recompute()
                self.assertEqual(slit.contract(), ComponentContract.from_dict(slit.contract().to_dict()))
                frames = {f.name: f for f in slit.contract().frames}
                self.assertAlmostEqual(-frames['native_mounting_face'].position[2], 17.78, places=5)
                body, bracket = slit.get_object().Children[:2]
                self.assertAlmostEqual(body.Shape.Volume, source_volume, places=5)
                self.assertTrue(bracket.Shape.isValid())
                self.assertEqual(len(bracket.Shape.Solids), 1)
                self.assertEqual(len(attachments.operations(bracket.Proxy)), 2)
                self.assertEqual(len(bracket.Proxy.contract().holes), 3)
                for offset, passes in ((0, width > 0), (width / 2 + .05, False)):
                    position = slit.get_object().Placement.multVec(App.Vector(-20, 0, offset))
                    output = body.Proxy.interfaces()[0].get_output_beams(self.beam(position))
                    self.assertEqual(len(output), int(passes))
                if roll == 0:
                    self.assertAlmostEqual(catalog.native_height(slit), 27.78, places=5)
                    for child in slit.get_object().Children[2:]:
                        self.assertLess(child.Shape.common(bracket.Shape).Volume, 1e-7)
                    self.assertLess(body.Shape.common(bracket.Shape).Volume, 1e-7)

    def test_both_plate_workflows_mixed_heights_nested_moves(self):
        root = Layout('Batch plates')
        root.get_object().BasePlacement = App.Placement(App.Vector(20, -40, 7), App.Rotation('XYZ', 0, 0, 19))
        components = []
        for i, (kind, params) in enumerate(SAMPLES):
            group = root.add(Layout('Nested group'), (30 + i*90, 60, 0), 0)
            component = group.add(catalog.create(kind, 'Sample', **params), (0, 0, 0), 31)
            component.get_object().BasePlacement.Base.z = catalog.native_height(component)
            components.append(component)
        plate, definition = machined_baseplate.add(root)
        regular = root.add(Component('Ordinary plate', Baseplate((800, 160, 12.7), optical_height=0,
            grid_offset=(0, 0)), recompute_priority=-2), (0, 0, 0), 0)
        root.recompute()
        self.assertEqual(len(definition.plan['holes']), 25)
        self.assertEqual(definition.plan['pockets'], [])
        self.assertIsNone(definition.plan['optical_height_mm'])
        self.assertEqual(len(definition.plan['optical_heights_mm']), 8)
        for target in (plate, regular):
            shape = target.get_object().Shape
            self.assertTrue(shape.isValid())
            for op in definition.plan['holes']:
                point = root.get_object().Placement.multVec(App.Vector(*op['center_mm']) - App.Vector(0, 0, 2))
                self.assertFalse(shape.isInside(point, 1e-7, False))
        old = App.Vector(*definition.plan['holes'][-1]['center_mm'])
        mover = components[-1]
        mover.get_object().BasePlacement = App.Placement(App.Vector(8, 7, 12.7), App.Rotation('XYZ', 0, 0, 90))
        root.recompute()
        self.assertEqual(len(definition.plan['holes']), 25)
        for target in (plate, regular):
            self.assertTrue(target.get_object().Shape.isInside(root.get_object().Placement.multVec(old-App.Vector(0, 0, 2)), 1e-7, False))
        before = regular.get_object().Shape.Volume, plate.get_object().Shape.Volume, len(self.doc.Objects)
        root.recompute()
        self.assertAlmostEqual(regular.get_object().Shape.Volume, before[0], places=6)
        self.assertAlmostEqual(plate.get_object().Shape.Volume, before[1], places=6)
        self.assertEqual(len(self.doc.Objects), before[2])

    def test_review_export_roundtrip(self):
        from examples.component_batch import build
        before = set(App.listDocuments())
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'batch.FCStd'
                doc, report = build(path)
                self.assertEqual(report['total_plate_operations'], 25)
                self.assertEqual(len(report['samples']), 8)
                features = [o for o in doc.Objects if o.TypeId == 'Part::Feature']
                expected = {o.Name: (o.Shape.Volume, len(o.Shape.Solids)) for o in features}
                self.assertEqual(len(features), 26)
                App.closeDocument(doc.Name)
                reopened = App.openDocument(str(path))
                for name, (volume, count) in expected.items():
                    obj = reopened.getObject(name)
                    self.assertFalse(hasattr(obj, 'Proxy'))
                    self.assertTrue(obj.Shape.isValid())
                    self.assertEqual(len(obj.Shape.Solids), count)
                    self.assertAlmostEqual(obj.Shape.Volume, volume, places=6)
                groups = [o for o in reopened.Objects if hasattr(o, 'BOM')]
                self.assertEqual(len(groups), 8)
                for group in groups:
                    ComponentContract.from_dict(json.loads(group.ComponentContract))
                    self.assertTrue(json.loads(group.BOM))
                step = Part.read(str(path.with_suffix('.step')))
                self.assertTrue(step.isValid())
                self.assertEqual(len(step.Solids), sum(c for _, c in expected.values()))
                # Compare compound integrals: OCC's adaptive spline integration
                # gives a different result when summing separate feature integrals.
                volume = Part.makeCompound([reopened.getObject(name).Shape for name in expected]).Volume
                # Imported spline integration varies slightly after STEP serialization.
                self.assertLess(abs(step.Volume - volume) / volume, 1e-6)
        finally:
            for name in set(App.listDocuments()) - before:
                App.closeDocument(name)
            App.setActiveDocument(self.doc.Name)

    def test_rejected_parameters_and_profile_isolation(self):
        for value in (-1, 6.1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                catalog.create('slit', 'Invalid', slit_width=value)
        for kind, params in [('mirror', dict(mount='FBR')), ('mirror', dict(mount='MHV-12.7L-R', thickness=1)),
                             ('rotation', dict(mount='FBR', thickness=5)), ('coupling', dict(mount='POLARIS-L05G'))]:
            with self.assertRaises(ValueError):
                catalog.create(kind, 'Invalid', **params)
        a, b = catalog.VendorPart('POLARIS-K05T6'), catalog.VendorPart('POLARIS-K05T6')
        p = a.baseplate_profile()
        p['dowels'].clear()
        self.assertEqual(len(b.baseplate_profile()['dowels']), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
