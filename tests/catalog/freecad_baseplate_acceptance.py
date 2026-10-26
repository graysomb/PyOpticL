"""Baseplate acceptance against vendor CAD, physical bores and integral PBS."""
import json
from pathlib import Path
import sys
import unittest
import FreeCAD as App
import Part
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PyOpticL import lab_catalog as catalog, machined_baseplate as machining
from PyOpticL.layout import Layout


class BaseplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = App.newDocument('PlateAcceptance')
        cls.layout = Layout('Plate layout')
        h = machining.optical_height()
        cls.assemblies = [cls.layout.add(catalog.create(kind,label, **({'mount':'KA05TA'} if kind == 'coupling' else {})),pos,angle)
            for kind,label,pos,angle in [
                ('coupling','input',(0,0,h),0),('mirror','first',(120,0,h),135),
                ('mirror','second',(120,100,h),-45),('coupling','output',(240,100,h),180)]]
        cls.plate,cls.definition = machining.add(cls.layout)
        cls.layout.recompute()

    def test_cad_attachment_axes(self):
        for pn,profile in machining.PROFILES.items():
            shape = catalog.vendor_shape(pn)
            cylinders = [f.Surface for f in shape.Faces if isinstance(f.Surface,Part.Cylinder)]
            for h in profile['native_holes']:
                if h['name'] not in profile['screws']+profile['dowels']:
                    continue
                centers = ([h['center']] if h['name'] != 'dowel_slot'
                           else profile['dowel']['slot_arc_centers_native'])
                for center in centers:
                    point,axis = App.Vector(*center),App.Vector(*h['axis'])
                    self.assertTrue(any(abs(c.Radius-h['diameter']/2)<.01
                        and abs(abs(c.Axis.dot(axis))-1)<1e-8
                        and (c.Center-point).cross(axis).Length<.01 for c in cylinders),(pn,h['name']))
            point = App.Vector(*profile['native_seat'])
            self.assertTrue(any(isinstance(f.Surface,Part.Plane)
                and abs(abs(f.normalAt(0,0).y)-1)<1e-8
                and abs(f.CenterOfMass.y-point.y)<.01 for f in shape.Faces))

    def test_flush_mating_and_holes(self):
        self.assertAlmostEqual(machining.optical_height(),12.7,places=6)
        plate = self.plate.get_object().Shape
        plan = self.definition.plan
        self.assertTrue(plate.isValid())
        self.assertEqual(len(plate.Solids),1)
        self.assertEqual(len(plan['holes']),8)
        self.assertEqual(plan['pockets'],[])
        self.assertEqual(sum(h['kind']=='dowel' for h in plan['holes']),4)
        self.assertEqual(sum(h.get('thread')=='M4 x 0.7' for h in plan['holes']),4)
        for op in plan['holes']:
            x,y,z = op['center_mm']
            self.assertAlmostEqual(z,0,places=5)
            self.assertFalse(plate.isInside(App.Vector(x,y,-2),1e-7,False))
            self.assertTrue(plate.isInside(App.Vector(x+op['diameter_mm']/2+.1,y,-2),1e-7,False))
        for obj in machining.descendants(self.layout.get_object()):
            if hasattr(obj.Proxy,'contract') and obj.Proxy.contract().part_number in machining.PROFILES:
                frames = {f.name:f for f in obj.Proxy.contract().frames}
                seat = obj.Placement.multVec(App.Vector(*frames['mounting_face'].position))
                self.assertAlmostEqual(seat.z,0,places=5)
                self.assertLess(sum(plate.common(solid).Volume for solid in obj.Shape.Solids),1e-5)

    def test_recess_and_recompute(self):
        # A taller effective installation produces a cut, never a spacer.
        obj = self.assemblies[0].get_object()
        original = obj.BasePlacement
        original = App.Placement(original.Base,original.Rotation)
        obj.BasePlacement = App.Placement(original.Base-App.Vector(0,0,1),original.Rotation)
        self.layout.recompute()
        self.assertEqual(len(self.definition.plan['pockets']),1)
        self.assertAlmostEqual(self.definition.plan['pockets'][0]['depth_mm'],1,places=5)
        obj.BasePlacement = original
        self.layout.recompute()
        volume,count = self.plate.get_object().Shape.Volume,len(self.doc.Objects)
        self.layout.recompute()
        self.assertEqual(len(self.doc.Objects),count)
        self.assertAlmostEqual(self.plate.get_object().Shape.Volume,volume,places=6)

    def test_pbs_union_preserves_clamp_hole(self):
        doc = App.newDocument('IntegralPBS')
        layout = Layout('PBS plate')
        pbs = layout.add(catalog.create('pbs','PBS'),(0,0,12.7),0)
        plate,definition = machining.add(layout)
        layout.recompute()
        shape = plate.get_object().Shape
        self.assertEqual(len(shape.Solids),1)
        self.assertEqual(len(definition.integrated_names),1)
        self.assertEqual([h['kind'] for h in definition.plan['holes']],['existing_clamp_bore'])
        x,y,z = definition.plan['holes'][0]['center_mm']
        self.assertFalse(shape.isInside(App.Vector(x,y,-2),1e-7,False))
        self.assertTrue(shape.isInside(App.Vector(x,y,-4),1e-7,False))
        self.assertTrue(shape.isInside(App.Vector(0,0,5),1e-7,False))
        self.assertFalse(shape.isInside(App.Vector(0,0,7),1e-7,False))


if __name__ == '__main__':unittest.main(verbosity=2)
