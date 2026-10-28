"""Source preservation, fastener fit, transformed drilling and crystal export."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import FreeCAD as App
import Part

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyOpticL import attachments, lab_catalog as catalog, machined_baseplate
from PyOpticL.beam_path import BeamPath
from PyOpticL.component_contract import ComponentContract
from PyOpticL.crystal_holder import CrystalBracket, CrystalHolder, HolderWasher, reference, source_shape
from PyOpticL.layout import Component, Layout
from PyOpticL.library import Baseplate
from PyOpticL.schematic import compile_schematic
from PyOpticL.schematic.bounds import BoundsProvider
from PyOpticL.schematic.cad import add_baseplate
from PyOpticL.schematic.parts import part_spec
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.topology import resolve_topology
from PyOpticL.vendor_cad import resolve_reference
from test_schematic import chain


class CrystalTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('CrystalAcceptance')
        self.addCleanup(App.closeDocument, self.doc.Name)

    def test_exact_six_source_solids_and_crystal_frame(self):
        r = reference()
        with patch('PyOpticL.vendor_cad.cache_root', side_effect=AssertionError('Bundled source required')):
            path = resolve_reference('crystal-holder')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), r['source_sha256'])
            for i, record in enumerate(r['parts']):
                shape = source_shape(i)
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids), 1)
                self.assertAlmostEqual(shape.Volume, record['volume_mm3'], places=6)
        b = source_shape(1).optimalBoundingBox()
        for a, e in zip((b.XLength, b.YLength, b.ZLength), (27.4, 4, 1)):
            self.assertAlmostEqual(a, e, places=6)
        self.assertLess(source_shape(1).Solids[0].CenterOfMass.Length, 1e-7)
        with self.assertRaises(TypeError): catalog.definition('crystal_holder', temperature=80)

    def test_bracket_contract_holes_are_distinct_from_mating_plate_operations(self):
        b = CrystalBracket()
        shape = b.shape()
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertEqual(len(b.contract().holes), 8)
        holder_taps = [h for h in b.contract().holes if h.name.startswith('holder_')]
        self.assertEqual(len(holder_taps), 4)
        self.assertTrue(all(h.thread == 'M1.6 x 0.35' for h in holder_taps))
        frames = {f.name: f for f in b.contract().frames}
        self.assertEqual({frames[h.frame].position[:2] for h in holder_taps},
                         {(-10.5, 8.5), (10.5, 8.5), (-10, -8.5), (10.5, -8.5)})
        restored = ComponentContract.from_dict(b.contract().to_dict())
        self.assertEqual(restored.to_dict(), b.contract().to_dict())
        ops = attachments.operations(b)
        self.assertEqual({o['interface'] for o in ops}, {'plate_1', 'plate_2', 'pin_1', 'pin_2'})
        self.assertEqual(sum(o.get('thread') == 'M4 x 0.7' for o in ops), 2)
        self.assertEqual(len(b.drill().Solids), 4)
        for op in ops:
            self.assertEqual(op['axis'], [0, 0, -1])
            self.assertAlmostEqual(op['center_mm'][2], -12.7)
        # All four source bores must clear the shank through their full depth.
        plate = source_shape(3)
        for (x, y), h in zip(reference()['bracket']['holder_xy_mm'], reference()['source_mounting_holes']):
            for fraction in (.01, .5, .99):
                z = -3.5 + fraction*h['depth_mm']
                for dx, dy in ((0, 0), (.8, 0), (-.8, 0), (0, .8), (0, -.8)):
                    self.assertFalse(plate.isInside(App.Vector(x+dx, y+dy, z), 1e-7, False))
            self.assertFalse(shape.isInside(App.Vector(x, y, -4), 1e-7, False))
            self.assertTrue(shape.isInside(App.Vector(x, y, -10), 1e-7, False))

    def test_source_seating_washers_and_fastener_access(self):
        bracket = CrystalBracket().shape()
        source = [source_shape(i) for i in range(6)]
        for part in source:
            self.assertLess(part.common(bracket).Volume, 1e-7)
        self.assertLess(source[3].distToShape(bracket)[0], 1e-7)
        for label, definition, pos, angles in CrystalHolder().children[7:]:
            shape = Part.makeCompound([definition.shape()])
            shape.Placement = App.Placement(App.Vector(*pos), App.Rotation('XYZ', *angles))
            for part in source:
                self.assertLess(part.common(shape).Volume, 1e-7, label)
            # Thread-major cylinders deliberately overlap tap-drill annuli only.
            if label == 'M1.6 holder screw':
                allowed = Part.makeCylinder(.8, 4.5, App.Vector(pos[0], pos[1], -8.))
                self.assertLess(shape.common(bracket).cut(allowed).Volume, 1e-7)
                tool = Part.makeCylinder(1.5, 20, App.Vector(pos[0], pos[1], pos[2] + 1.6))
                self.assertLess(sum(tool.common(part).Volume for part in source), 1e-7)
            else:
                self.assertLess(shape.common(bracket).Volume, 1e-7, label)
            if isinstance(definition, HolderWasher):
                self.assertLess(min(shape.distToShape(part)[0] for part in (source[0], source[3])), 1e-7)

    def test_both_drilling_workflows_follow_nested_placement_and_recompute(self):
        root = Layout('Plate scene')
        root.get_object().BasePlacement = App.Placement(App.Vector(20, 30, 4), App.Rotation('XYZ', 0, 0, 17))
        nested = root.add(Layout('Nested'), (100, 100, 0), 29)
        holder = nested.add(catalog.create('crystal_holder', 'Holder'), (0, 0, 12.7), 13)
        regular = root.add(Component('Ordinary plate', Baseplate((240, 240, 30), optical_height=0,
            grid_offset=(0, 0)), recompute_priority=-2), (0, 0, 0), 0)
        plate, machining = machined_baseplate.add(root, thickness=30)
        root.recompute()
        self.assertEqual(catalog.native_height(holder), 12.7)
        self.assertEqual(len(holder.get_object().Children), 19)
        bom = catalog.bom(holder)
        self.assertEqual(sum(row['part_number'] == 'M1.6 x 0.35 x 10 mm' for row in bom), 3)
        self.assertEqual(sum(row['part_number'] == 'M1.6 x 0.35 x 8 mm' for row in bom), 1)
        self.assertEqual(sum(row['catalog_id'] == 'crystal-holder-washer' for row in bom), 4)
        for move in (0, 7):
            if move:
                holder.get_object().BasePlacement.Base += App.Vector(7, 3, 0)
                root.recompute()
            self.assertEqual(len(machining.plan['holes']), 4)
            self.assertEqual(machining.plan['pockets'], [])
            mounting = holder.get_object().Children[6]
            expected = attachments.operations(mounting.Proxy, root.get_object().Placement.inverse() * mounting.Placement)
            for actual, desired in zip(machining.plan['holes'], expected):
                self.assertLess((App.Vector(*actual['center_mm']) - App.Vector(*desired['center_mm'])).Length, 1e-7)
                for target in (regular, plate):
                    p = root.get_object().Placement.multVec(App.Vector(*actual['center_mm']) + App.Vector(0, 0, -1))
                    self.assertFalse(target.get_object().Shape.isInside(p, 1e-7, False))
                    p = root.get_object().Placement.multVec(App.Vector(*actual['center_mm']) + App.Vector(0, 0, -12))
                    self.assertTrue(target.get_object().Shape.isInside(p, 1e-7, False))
            # Internal M1.6 taps must not appear as extra baseplate drilling.
            for x, y in reference()['bracket']['holder_xy_mm']:
                p = mounting.Placement.multVec(App.Vector(x, y, -13.7))
                self.assertTrue(plate.get_object().Shape.isInside(p, 1e-7, False))
            count, volume = len(self.doc.Objects), plate.get_object().Shape.Volume
            root.recompute()
            self.assertEqual(count, len(self.doc.Objects))
            self.assertAlmostEqual(volume, plate.get_object().Shape.Volume, places=6)

    def test_ray_pass_and_full_length_aperture(self):
        for y, z, slope, hit in ((0, 0, 0, True), (1.8, .4, 0, True), (0, .6, 0, False),
                                  (0, 0, .05, False)):
            root = Layout('Ray scene')
            holder = root.add(catalog.create('crystal_holder', 'Holder'), (0, 0, 0), 0)
            direction = App.Vector(1, 0, slope); direction.normalize()
            start = App.Vector(0, y, z) - 50 * direction
            beam = root.add(BeamPath('Test beam', wavelength=1550, waist=.1, power=.01,
                bound_parent=root), tuple(start), tuple(App.Rotation(App.Vector(1, 0, 0), direction).toEulerAngles('XYZ')))
            root.recompute()
            outputs = beam.get_output_indices(holder)
            self.assertEqual(bool(outputs), hit)
            if hit:
                incoming, outgoing = beam.get_object().BeamSegments
                self.assertAlmostEqual(outgoing.Proxy.wavelength, 1550)
                self.assertAlmostEqual(outgoing.Proxy.power, .01)
                self.assertLess((App.Vector(*outgoing.Proxy.get_global_direction()) - direction).Length, 1e-7)

    def test_schematic_export_bounds_and_baseplate(self):
        for preset in ('bracketed', 'bare'):
            doc = chain('source', 'crystal', 'output')
            select_preset(doc.nodes[1], preset)
            doc.nodes[0].parameters['waist'] = .1
            compiled = compile_schematic(doc)
            self.assertTrue(compiled.ok, compiled.diagnostics)
            namespace = {'__name__': 'test_export'}
            exec(compiled.source, namespace)
            layout = namespace['build_layout']()
            result = BoundsProvider().get(part_spec(doc, doc.nodes[1], resolve_topology(doc)))
            self.assertIsNone(result.error)
            self.assertGreater(result.circle.radius_mm, 0)
            if preset == 'bracketed':
                plate = add_baseplate(layout)
                self.assertEqual(len(json.loads(plate.get_object().MachiningPlan)['holes']), 4)
            else:
                with self.assertRaisesRegex(ValueError, 'no supported baseplate attachment'):
                    add_baseplate(layout)

    def test_static_demo_reopens_without_source_access(self):
        from examples.crystal_holder import build
        before = {d.Name for d in App.listDocuments().values()}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'crystal.FCStd'
            document = build(path)
            self.assertEqual(len([o for o in document.Objects if o.TypeId == 'Part::Feature']), 20)
            App.closeDocument(document.Name)
            with patch('PyOpticL.crystal_holder.resolve_reference', side_effect=AssertionError('Static file must be portable')):
                reopened = App.openDocument(str(path))
                self.assertTrue(all(o.Shape.isValid() for o in reopened.Objects if hasattr(o, 'Shape')))
                App.closeDocument(reopened.Name)
            self.assertTrue(path.with_name('crystal_bracket.step').exists())
            self.assertEqual(len(json.loads(path.with_suffix('.machining.json').read_text())['holes']), 4)
        for name in set(App.listDocuments()) - before:
            App.closeDocument(name)


if __name__ == '__main__':
    unittest.main()
