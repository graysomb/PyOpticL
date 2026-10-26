"""Full folded-path demo, recessed stock, physical attachments and export checks."""
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
from examples import all_components_baseplate as demo
from PyOpticL import lab_catalog as catalog, machined_baseplate
from PyOpticL.component_contract import ComponentContract


class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = set(App.listDocuments())
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        cls.addClassCleanup(cls.close_documents)
        cls.path = Path(cls.folder.name) / 'all_components_baseplate.FCStd'
        cls.static, cls.report = demo.build(cls.path)
        cls.source = App.getDocument(cls.report['source_document'])
        cls.layout = cls.source.getObject(cls.report['source_layout']).Proxy
        cls.beam = cls.source.getObject(cls.report['source_beam'])
        cls.parts = {c['id']: cls.source.getObject(c['source_object']) for c in cls.report['components']}
        cls.plate = next(o for o in cls.source.Objects if hasattr(o, 'MachiningPlan'))

    @classmethod
    def close_documents(cls):
        for name in set(App.listDocuments()) - cls.before:
            App.closeDocument(name)

    def test_continuous_beam_and_all_parts(self):
        segments = self.beam.BeamSegments
        self.assertEqual(len(segments), 9)
        self.assertAlmostEqual(sum(s.Proxy.distance for s in segments), 760., places=6)
        starts = [(0, 0), (60, 0), (100, 0), (180, 0), (180, 70),
                  (180, 150), (90, 150), (0, 150), (-100, 150)]
        for segment, xy in zip(segments, starts):
            self.assertLess((segment.Placement.Base - App.Vector(*xy, 12.7)).Length, .01)
            self.assertAlmostEqual(segment.Proxy.get_global_direction()[2], 0., places=8)
        self.assertEqual(segments[-1].EndObject.Label, 'Output receiver datum')
        actual = {o.Proxy.contract().part_number for o in self.source.Objects if hasattr(o.Proxy, 'contract')}
        self.assertTrue(set(catalog.VENDOR_IDS).issubset(actual))
        self.assertEqual(sum(o.Proxy.contract().part_number == 'POLARIS-K05T6'
                             for o in self.source.Objects if hasattr(o.Proxy, 'contract')), 2)
        self.assertEqual(len(self.parts), 10)
        self.assertEqual(self.parts['iris'].Proxy.contract().catalog_id, 'iris')
        native = {s['component']: s['native_height_mm'] for s in self.report['verification']['seats']}
        for key, height in dict(input=12.7, output=12.7, half_lens=12.7, one_lens=19.05,
            half_mirror=12.7, polaris_mirror=25.4, one_mirror=25.4, waveplate=14.3002,
            slit=27.78, iris=12.7).items():
            self.assertAlmostEqual(native[key], height, places=5)
            self.assertAlmostEqual(self.parts[key].Placement.Base.z, 12.7, places=6)

    def test_lens_seating_and_waveplate(self):
        for key, diameter, focal in [('half_lens', 12.7, 100), ('one_lens', 25.4, 150)]:
            optic = self.parts[key]
            self.assertAlmostEqual(optic.Proxy.diameter, diameter)
            self.assertAlmostEqual(optic.Proxy.focal_length, focal)
            self.assertEqual(optic.Children[0].BasePlacement.Base.x, -1)
            self.assertLess(optic.Shape.distToShape(optic.Children[0].Shape)[0], .01)
            self.assertLess(sum(optic.Shape.common(s).Volume for s in optic.Children[0].Shape.Solids), 1e-6)
        before = [complex(*v) for v in self.beam.BeamSegments[3].Proxy.polarization_jones]
        after = [complex(*v) for v in self.beam.BeamSegments[4].Proxy.polarization_jones]
        self.assertAlmostEqual(abs(before[0]), 1, places=6)
        self.assertAlmostEqual(abs(before[1]), 0, places=6)
        self.assertAlmostEqual(abs(after[0]), math.sqrt(.5), places=6)
        self.assertLess(abs(after[0] - after[1]), 1e-7)
        self.assertLess(self.report['verification']['route'][1]['final_radius_mm'], 1.)
        self.assertLess(self.report['verification']['route'][6]['final_radius_mm'], 1.)

    def test_recesses_and_physical_bores(self):
        plan = self.report['machining']
        self.assertEqual(plan['stock_bounds'], [-155, -45, 395, 255])
        self.assertEqual(plan['thickness_mm'], 30)
        self.assertEqual(len(plan['pockets']), 5)
        actual = {r['component']: r['recess_depth_mm'] for r in self.report['verification']['seats']}
        for key, depth in [('waveplate', 1.6002), ('one_lens', 6.35), ('polaris_mirror', 12.7),
                           ('one_mirror', 12.7), ('slit', 15.08)]:
            self.assertAlmostEqual(actual[key], depth, places=5)
        self.assertEqual(len(plan['holes']), 30)
        self.assertEqual(sum(h['kind'] == 'tapped' for h in plan['holes']), 12)
        self.assertEqual(sum(h['kind'] == 'dowel' for h in plan['holes']), 18)
        self.assertTrue(self.plate.Shape.isValid())
        self.assertEqual(len(self.plate.Shape.Solids), 1)
        for op in plan['holes']:
            center = App.Vector(*op['center_mm'])
            axis = App.Vector(*op['axis'])
            self.assertFalse(self.plate.Shape.isInside(center + axis * 1., 1e-7, False))
            outside = center + axis + App.Vector(op['diameter_mm']/2+.1, 0, 0)
            self.assertTrue(self.plate.Shape.isInside(outside, 1e-7, False))
        expected = 30 - 15.08 - 10 - (3.3/2)/math.tan(math.radians(59))
        self.assertAlmostEqual(self.report['verification']['minimum_stock_below_drill_tip_mm'], expected, places=6)

    def test_pin_models_and_bom(self):
        pins = self.static.ExternalPins.Group
        self.assertEqual(len(pins), 16)
        self.assertEqual(sum(h['part'] == 'FBR' for h in self.report['machining']['holes']), 2)
        for pin in pins:
            op = json.loads(pin.AttachmentOperation)
            self.assertNotEqual(op['part'], 'FBR')
            self.assertAlmostEqual(pin.Shape.Volume, math.pi*5, places=6)
            center = App.Vector(*op['center_mm'])
            self.assertLess((pin.Shape.CenterOfMass - (center + App.Vector(0, 0, 2.5-op['depth_mm']))).Length, 1e-6)
            self.assertLess(pin.Shape.common(self.plate.Shape).Volume, 1e-7)
        rows = self.report['bom']
        external = next(r for r in rows if r.get('label') == 'Nominal diameter 2 x 5 mm alignment dowel')
        self.assertEqual(external['quantity'], 16)
        screws = next(r for r in rows if r.get('label') == 'Additional M4 mounting screw requirements')
        self.assertEqual(screws['quantity'], 10)
        self.assertFalse(screws['modeled'])
        self.assertEqual(sum(r['part_number'] == 'POLARIS-K05T6' for r in rows if 'part_number' in r), 2)
        rings = [r for r in rows if r.get('part_number') == 'POLARIS-SM05RR']
        self.assertEqual(len(rings), 4)
        self.assertEqual(sum('uninstalled' in r['disposition'] for r in rings), 2)
        slit = next(s for s in self.report['verification']['seats'] if s['component'] == 'slit')
        self.assertAlmostEqual(slit['native_component_height_mm'], 17.78)
        self.assertAlmostEqual(slit['bracket_height_mm'], 10.)

    def test_contracts_and_sidecars(self):
        for obj in self.static.Objects:
            if hasattr(obj, 'ComponentContract'):
                c = ComponentContract.from_dict(json.loads(obj.ComponentContract))
                self.assertEqual(c, ComponentContract.from_dict(c.to_dict()))
        for suffix, field in [('.machining.json', 'machining'), ('.bom.json', 'bom')]:
            self.assertEqual(json.loads(self.path.with_suffix(suffix).read_text()), self.report[field])
        self.assertEqual(json.loads(self.path.with_suffix('.report.json').read_text()), self.report)
        self.assertTrue(self.path.with_suffix('.report.md').exists())
        self.assertIn('reference opening', self.path.with_suffix('.report.md').read_text())

    def test_export_reopen_without_vendor_cache(self):
        names = [o.Name for o in self.static.Objects if o.TypeId == 'Part::Feature']
        self.assertEqual(len(names), 50)  # 41 physical features plus nine beam segments.
        filename = self.static.FileName
        App.closeDocument(self.static.Name)
        with patch.object(catalog, 'vendor_shape', side_effect=AssertionError('Must not load assets')):
            type(self).static = App.openDocument(filename)
            for name in names:
                obj = self.static.getObject(name)
                self.assertTrue(obj.Shape.isValid())
                self.assertFalse(hasattr(obj, 'Proxy'))
        step = Part.read(str(self.path.with_suffix('.step')))
        plate = Part.read(str(self.path.with_name(self.path.stem + '_baseplate.step')))
        self.assertTrue(step.isValid())
        self.assertEqual(len(step.Solids), self.report['verification']['hardware_solid_count'])
        self.assertTrue(plate.isValid())
        self.assertEqual(len(plate.Solids), 1)
        self.assertAlmostEqual(plate.Volume, self.plate.Shape.Volume, delta=.01)

    def test_recompute_and_instance_isolation(self):
        count, volume = len(self.source.Objects), self.plate.Shape.Volume
        self.layout.recompute()
        self.assertEqual(len(self.source.Objects), count)
        self.assertAlmostEqual(self.plate.Shape.Volume, volume, places=6)
        self.assertEqual(len(self.beam.BeamSegments), 9)
        original = self.parts['input'].BasePlacement
        original = App.Placement(original.Base, original.Rotation)
        output_before = self.parts['output'].Placement
        output_before = App.Placement(output_before.Base, output_before.Rotation)
        try:
            self.parts['input'].BasePlacement = App.Placement(original.Base+App.Vector(1, 0, 0), original.Rotation)
            self.layout.recompute()
            self.assertLess((self.parts['output'].Placement.Base-output_before.Base).Length, 1e-9)
            self.assertAlmostEqual(self.parts['input'].Placement.Base.x, 1.)
        finally:
            self.parts['input'].BasePlacement = original
            self.layout.recompute()
        self.assertEqual(len(self.source.Objects), count)
        self.assertAlmostEqual(self.plate.Shape.Volume, volume, places=6)
        a = self.parts['input'].Children[2].Proxy.baseplate_profile()
        a['dowels'].clear()
        self.assertEqual(len(self.parts['output'].Children[2].Proxy.baseplate_profile()['dowels']), 2)

    def test_reject_insufficient_stock_before_export(self):
        for thickness in (20., 26.):
            before = set(App.listDocuments())
            path = Path(self.folder.name) / ('too_thin_' + str(thickness) + '.FCStd')
            with self.assertRaisesRegex(ValueError, 'Insufficient stock|Blind hole'):
                demo.build(path, plate_thickness=thickness)
            self.assertEqual(set(App.listDocuments()), before)
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
