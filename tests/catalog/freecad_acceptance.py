"""Integration checks; run with the FreeCAD 1.1.4 Python interpreter."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import FreeCAD as App
import Part
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PyOpticL import lab_catalog as catalog
from PyOpticL.component_contract import ComponentContract, rotate, connection_check
from PyOpticL.layout import Component, Layout
from PyOpticL.library import optics

class FreeCADTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = App.newDocument('CatalogAcceptance')
        cls.root = Layout('root')
        cls.parts = {name: cls.root.add(catalog.create(name,name), (i*160,0,0), (0,0,0))
                     for i,name in enumerate(catalog.CATALOG_IDS)}
        cls.root.recompute()

    def test_five_assemblies_and_pins(self):
        reference=json.loads((catalog.DATA/'reference_measurements.json').read_text())
        for pn,expected in reference['vendor'].items():
            shape=catalog.vendor_shape(pn)
            self.assertTrue(shape.isValid(),pn)
            self.assertEqual(len(shape.Solids),expected['solid_count'])
            self.assertAlmostEqual(shape.Volume,expected['volume_mm3'],places=4)
        for name,component in self.parts.items():
            self.assertEqual(component.contract().catalog_id,name)
            for obj in [component.get_object(),*component.get_object().Children]:
                if hasattr(obj.Proxy,'shape'):
                    self.assertFalse(obj.Shape.isNull(), obj.Label)

    def test_nominal_frames(self):
        ka=self.parts['coupling'].get_object().Children[2].Proxy
        frames={f.name:f for f in ka.contract().frames}
        self.assertAlmostEqual(frames['adapter_seat'].position[0],0,places=5)
        self.assertAlmostEqual(frames['mounting_face'].position[2],-12.7,places=5)
        xr=self.parts['translation'].get_object().Children[0].Proxy
        self.assertAlmostEqual({f.name:f for f in xr.contract().frames}['payload'].position[2],23,places=5)
        mirror=self.parts['mirror'].get_object().Children[0].Proxy
        self.assertAlmostEqual({f.name:f for f in mirror.contract().frames}['optic_seat'].position[0],0,places=5)
        self.assertEqual(len(mirror.contract().holes),2)

    def test_measured_vendor_hole_axes(self):
        reference=json.loads((catalog.DATA/'reference_measurements.json').read_text())
        for pn,specification in reference['datums'].items():
            cylinders=[f.Surface for f in catalog.vendor_shape(pn).Faces if isinstance(f.Surface,Part.Cylinder)]
            for hole in specification['holes']:
                center,axis=App.Vector(*hole['center']),App.Vector(*hole['axis'])
                matches=[c for c in cylinders if abs(c.Radius-hole['diameter']/2)<=.01
                    and abs(abs(c.Axis.dot(axis))-1)<1e-8
                    and (c.Center-center).cross(axis).Length<=.01]
                self.assertTrue(matches, (pn,hole['name']))

    def test_coupling_thread_end_convention(self):
        collimator,adapter,mount=self.parts['coupling'].get_object().Children
        def frame_x(obj,name):
            frame=next(f for f in obj.Proxy.contract().frames if f.name==name)
            return obj.BasePlacement.Base.x+frame.position[0]
        self.assertAlmostEqual(frame_x(collimator,'thread_end'),-2.9972,places=5)
        self.assertAlmostEqual(frame_x(adapter,'collimator_opening'),frame_x(collimator,'thread_end'),places=5)
        self.assertAlmostEqual(frame_x(adapter,'mount_seat'),mount.BasePlacement.Base.x,places=5)
        def normal(obj,name):
            f=next(f for f in obj.Proxy.contract().frames if f.name==name)
            return App.Rotation('XYZ',*f.rotation).multVec(App.Vector(0,0,1))
        self.assertAlmostEqual(normal(collimator,'thread_end').dot(normal(adapter,'collimator_opening')),-1,places=8)
        self.assertAlmostEqual(normal(adapter,'mount_seat').dot(normal(mount,'adapter_seat')),-1,places=8)
        planes=[f for f in catalog.vendor_shape('F260FC-1550').Faces if isinstance(f.Surface,Part.Plane)]
        self.assertTrue(any(abs(f.CenterOfMass.z-6.5532)<.01 and abs(f.normalAt(0,0).z)>.99999 for f in planes))

    def test_connections_and_bom(self):
        pairs=catalog.connection_interfaces()
        for a,b in [('F260FC-1550','AD1109F-in'),('AD1109F-out','KA05TA')]:
            self.assertTrue(connection_check(pairs[a],pairs[b])[0])
        rows=catalog.bom(self.parts['coupling'])
        self.assertEqual({r['part_number'] for r in rows},{'F260FC-1550','AD1109F','KA05TA','SM05KRR'})
        self.assertEqual(sum(r['quantity'] for r in rows if r['part_number']=='SM05KRR'),2)
        mount=self.parts['coupling'].get_object().Children[2]
        self.assertEqual(len(mount.Shape.Solids),23) # one supplied ring removed

    def test_metadata_and_recompute_are_inert(self):
        before={o.Name:(tuple(o.Placement.Base),o.Shape.Volume if hasattr(o,'Shape') and not o.Shape.isNull() else 0)
                for o in self.document.Objects}
        count=len(self.document.Objects)
        for component in self.parts.values():
            obj=component.get_object()
            self.assertEqual(obj.getEditorMode('AvailableDOFs'),['ReadOnly'])
            obj.AvailableDOFs='descriptive metadata changed for test'
            ComponentContract.from_dict(json.loads(obj.ComponentContract))
            catalog.report_dofs(component)
        for _ in range(3):self.root.recompute();self.document.recompute()
        self.assertEqual(count,len(self.document.Objects))
        for o in self.document.Objects:
            self.assertEqual(tuple(o.Placement.Base),before[o.Name][0])
            if hasattr(o,'Shape') and not o.Shape.isNull():self.assertAlmostEqual(o.Shape.Volume,before[o.Name][1],places=5)

    def test_dof_rotation_and_isolation(self):
        a=catalog.create('mirror','independentA');b=catalog.create('mirror','independentB')
        a.get_object().BasePlacement=App.Placement(App.Vector(0,50,0),App.Rotation('XYZ',20,30,40))
        a.recompute();b.recompute()
        axis=catalog.report_dofs(a)[0]['axis']
        for actual,expected in zip(axis,rotate((0,1,0),(20,30,40))):self.assertAlmostEqual(actual,expected,places=10)
        before=b.get_object().Shape.BoundBox.XMin
        a.get_object().BasePlacement.Base=App.Vector(40,50,0);a.recompute()
        self.assertAlmostEqual(b.get_object().Shape.BoundBox.XMin,before,places=8)
        self.assertAlmostEqual(a.get_object().Shape.Solids[0].Volume,b.get_object().Shape.Solids[0].Volume,places=8)

    def test_existing_optics_api(self):
        mirror=Component('legacyMirror',optics.Circular_Mirror(diameter=12.7,thickness=3))
        mirror.recompute()
        self.assertEqual(len(mirror.interfaces()),1)
        self.assertIs(mirror.interfaces()[0].parent,mirror)
        self.assertAlmostEqual(mirror.get_object().Shape.BoundBox.XLength,3)
        self.assertGreater(mirror.drill().Volume,mirror.shape().Volume)

if __name__=='__main__':unittest.main(verbosity=2)
