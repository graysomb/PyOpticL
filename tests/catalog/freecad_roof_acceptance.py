"""Measured roof optics, user-corrected integral supports and M2 clamps.

Run with FreeCAD's bundled Python and lib directory on PYTHONPATH.
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
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PyOpticL import attachments, lab_catalog as catalog, machined_baseplate
from PyOpticL.beam_path import BeamPath, Reflection, Stop, linear_polarization
from PyOpticL.component_contract import ComponentContract
from PyOpticL.layout import Component, Layout
from PyOpticL.library import Baseplate
from PyOpticL.roof_mirror import (RoofGeometry, RoofSupport, RoofClamp, reference,
    support_reference, support_shape, support_point, capsule)
from PyOpticL.vendor_cad import resolve, resolve_reference


class Receiver:
    def interfaces(self):
        return [Stop((0,0,0),(0,0,0),diameter=.1)]


class RoofTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('RoofAcceptance')
        self.addCleanup(App.closeDocument, self.doc.Name)

    def assert_vector(self, actual, expected, tol=1e-7):
        self.assertLess((App.Vector(*actual)-App.Vector(*expected)).Length, tol)

    def scene(self, orientation='horizontal', spacing=12.7, skew=0., shift=0.,
              transform=None, mounted=False, start_y=0., start_z=None):
        root=Layout('Scene')
        if transform:
            root.get_object().BasePlacement=transform
        roof=root.add(catalog.create('roof' if mounted else 'HRS1015-P01','Roof',
            orientation=orientation,beam_separation=spacing),(shift,0,0),0)
        # Skew runs along the roof edge, hence along Y in vertical mode.
        d=np.array([1.,0.,skew]) if orientation=='horizontal' else np.array([1.,skew,0.])
        d/=np.linalg.norm(d)
        axis=App.Rotation(App.Vector(1,0,0),App.Vector(*d)).toEulerAngles('XYZ')
        start=np.array([-50.,start_y,-50*skew if orientation=='horizontal' else 0.])
        if orientation=='vertical': start[1]=-50*skew+start_y
        if start_z is not None: start[2]=start_z
        out=np.array([-50.,-spacing,0.]) if orientation=='horizontal' else np.array([-50.,0.,spacing])
        if orientation=='horizontal': out[2]=(75.4+2*shift)*skew
        else: out[1]=(75.4+2*shift)*skew
        receiver=root.add(Component('Receiver',Receiver()),tuple(out),0)
        beam=root.add(BeamPath('Beam',wavelength=1550,waist=.2,power=.001,
            polarization=linear_polarization(23),bound_parent=root),tuple(start),tuple(axis))
        root.recompute()
        return root,roof,beam,receiver

    def test_source_assets_and_preserved_solids(self):
        r=reference()
        for kind,key in [('step','step_sha256'),('pdf','drawing_sha256')]:
            record=json.loads((catalog.DATA/'assets'/('HRS1015-P01.'+kind+'.json')).read_text())
            self.assertEqual(hashlib.sha256(resolve(record).read_bytes()).hexdigest(),r[key])
        source=catalog.vendor_shape('HRS1015-P01')
        self.assertTrue(source.isValid())
        self.assertEqual(len(source.Solids),3)
        self.assertAlmostEqual(source.Volume,r['volume_mm3'],places=6)
        for orientation in ('horizontal','vertical'):
            optic=catalog.create('HRS1015-P01',orientation,orientation=orientation)
            optic.recompute()
            shape=optic.get_object().Shape
            self.assertTrue(shape.isValid())
            self.assertEqual(len(shape.Solids),3)
            self.assertAlmostEqual(shape.Volume,source.Volume,places=6)
            self.assertEqual(optic.contract().holes,())
            self.assertAlmostEqual(catalog.native_height(optic),12.7 if orientation=='horizontal' else 6.35,places=8)
            self.assertEqual(catalog.bom(optic)[0]['part_number'],'HRS1015-P01')
            g=RoofGeometry(orientation)
            hits=g.trace((0,0,0),(1,0,0))['hits']
            for solid,hit in zip((shape.Solids[2],shape.Solids[1]),hits):
                self.assertLess(solid.Faces[1].distToShape(Part.Vertex(App.Vector(*hit)))[0],1e-7)

    def test_parameters_and_clear_aperture(self):
        for orientation in ('horizontal','vertical'):
            for spacing in (3.,8.,12.7,20.,22.):
                g=RoofGeometry(orientation,spacing)
                self.assertIsNotNone(g.trace((0,0,0),(1,0,0)))
        for value in (0,-1,math.nan,math.inf,-math.inf,1,24,25.4):
            with self.subTest(value=value),self.assertRaises(ValueError):
                catalog.create('roof','invalid',beam_separation=value)
        with self.assertRaises(ValueError): catalog.create('roof','bad',orientation='up')
        with self.assertRaises(TypeError): catalog.create('roof','bad',height=12.7)

    def test_nominal_two_reflections_both_orientations_and_spacings(self):
        for orientation in ('horizontal','vertical'):
            for spacing in (3.,12.7,20.):
                root,roof,beam,_=self.scene(orientation,spacing)
                measured=beam.measure_component_pass(roof,refractive_index=1.0003)
                expected=(0,-spacing,0) if orientation=='horizontal' else (0,0,spacing)
                self.assert_vector(measured['entry_mm'],(0,0,0))
                self.assert_vector(measured['exit_mm'],expected)
                self.assert_vector(measured['outgoing_direction'],(-1,0,0))
                self.assertEqual(len(measured['reflection_points_mm']),2)
                self.assertAlmostEqual(measured['geometric_length_mm'],25.4,places=8)
                self.assertAlmostEqual(measured['optical_path_length_mm'],25.4*1.0003,places=8)
                self.assertEqual(len(beam.get_object().BeamSegments),5)
                segments=beam.get_object().BeamSegments
                self.assertEqual([s.EndInterfaceName for s in segments],['entry','facet_1','facet_2','exit',''])
                self.assertAlmostEqual(sum(s.Proxy.distance for s in segments),125.4,places=8)
                outgoing=segments[-1].Proxy
                self.assertAlmostEqual(outgoing.waist_position,beam.waist_position-75.4,places=8)
                self.assertAlmostEqual(outgoing.rayleigh_range,beam.rayleigh_range,places=8)
                self.assertAlmostEqual(outgoing.power,.001,places=10)
                self.assertEqual(outgoing.polarization_jones,linear_polarization(23))

    def test_translated_rotated_and_nested_optics(self):
        for orientation in ('horizontal','vertical'):
            # A nested 3D assembly, not just a 2D yaw about the global origin.
            parent=Layout('Parent')
            parent.get_object().BasePlacement=App.Placement(App.Vector(70,20,30),App.Rotation('XYZ',13,17,37))
            root,roof,beam,_=self.scene(orientation)
            parent.add(root,(40,5,60),-19)
            parent.recompute()
            placement=root.get_object().Placement
            measured=beam.measure_component_pass(roof)
            self.assert_vector(measured['entry_mm'],placement.multVec(App.Vector()))
            exit_local=App.Vector(0,-12.7,0) if orientation=='horizontal' else App.Vector(0,0,12.7)
            self.assert_vector(measured['exit_mm'],placement.multVec(exit_local))
            self.assert_vector(measured['outgoing_direction'],placement.Rotation.multVec(App.Vector(-1,0,0)))
            self.assertAlmostEqual(measured['geometric_length_mm'],25.4,places=8)

    def test_skew_preserves_roof_edge_direction_component(self):
        for orientation in ('horizontal','vertical'):
            _,roof,beam,_=self.scene(orientation,skew=.02)
            measured=beam.measure_component_pass(roof)
            incoming=np.array([1,0,.02] if orientation=='horizontal' else [1,.02,0])/math.sqrt(1+.02**2)
            edge=np.array([0,0,1] if orientation=='horizontal' else [0,1,0])
            expected=-incoming+2*(incoming@edge)*edge
            self.assert_vector(measured['outgoing_direction'],expected)
            self.assertGreater(np.linalg.norm(expected+incoming),.03)
            self.assertAlmostEqual(measured['geometric_length_mm'],25.4*math.sqrt(1+.02**2),places=8)

    def test_oblique_displacement_depends_on_incident_ray(self):
        root=Layout('Oblique ray')
        roof=root.add(catalog.create('HRS1015-P01','Roof'),(0,0,0),0)
        # At X=0 this ray enters at Y=1 rather than at the nominal port.
        angle=2.
        slope=math.tan(math.radians(angle))
        exit_y=-12.7-1-25.4*slope
        receiver_y=exit_y-50*slope
        root.add(Component('Receiver',Receiver()),(-50,receiver_y,0),0)
        beam=root.add(BeamPath('Oblique',wavelength=1550,waist=.2,bound_parent=root),
            (-50,1-50*slope,0),angle)
        root.recompute()
        measured=beam.measure_component_pass(roof)
        self.assert_vector(measured['entry_mm'],(0,1,0))
        self.assert_vector(measured['exit_mm'],(0,exit_y,0))
        self.assert_vector(measured['outgoing_direction'],(-math.cos(math.radians(angle)),-math.sin(math.radians(angle)),0))
        self.assertAlmostEqual(measured['geometric_length_mm'],25.4/math.cos(math.radians(angle)),places=8)

    def test_multiple_passes_through_opposite_ports(self):
        class ReturnMirror:
            def interfaces(self):return [Reflection((0,0,0),(0,0,0),diameter=2)]
        root=Layout('Double pass')
        roof=root.add(catalog.create('HRS1015-P01','Roof'),(0,0,0),0)
        root.add(Component('Return mirror',ReturnMirror()),(-30,-12.7,0),0)
        root.add(Component('Receiver',Receiver()),(-50,0,0),0)
        beam=root.add(BeamPath('Beam',wavelength=1550,waist=.2,bound_parent=root),(-50,0,0),0)
        root.recompute()
        first=beam.measure_component_pass(roof)
        second=beam.measure_component_pass(roof,pass_index=1)
        self.assert_vector(first['exit_mm'],(0,-12.7,0))
        self.assert_vector(second['entry_mm'],(0,-12.7,0))
        self.assert_vector(second['exit_mm'],(0,0,0))
        self.assertAlmostEqual(second['geometric_length_mm'],25.4,places=8)
        self.assertAlmostEqual(sum(s.Proxy.distance for s in beam.get_object().BeamSegments),210.8,places=8)
        with self.assertRaises(ValueError):beam.measure_component_pass(roof,pass_index=2)

    def test_aperture_seam_grazing_and_miss_termination(self):
        for y,z in [(-6.35,0),(6.,0),(0,11.),(0,-11.)]:
            _,roof,beam,_=self.scene(start_y=y,start_z=z)
            self.assertEqual(len(beam.get_object().BeamSegments),1)
            with self.assertRaises(ValueError): beam.measure_component_pass(roof)
        g=RoofGeometry()
        self.assertIsNone(g.trace((0,0,0),(0,1,0)))
        self.assertIsNone(g.trace((0,0,0),(1,10,0)))
        self.assertIsNone(g.trace((0,0,0),(-1,0,0)))
        _,_,beam,_=self.scene(start_y=30)
        self.assertEqual(len(beam.get_object().BeamSegments),1)
        self.assertIsNone(beam.get_object().BeamSegments[0].EndObject)

    def test_axial_translation_changes_external_path_twice(self):
        totals=[]
        for shift in (0.,7.25):
            _,roof,beam,_=self.scene(shift=shift)
            totals.append(sum(s.Proxy.distance for s in beam.get_object().BeamSegments))
            self.assertAlmostEqual(beam.measure_component_pass(roof)['geometric_length_mm'],25.4,places=8)
        self.assertAlmostEqual(totals[1]-totals[0],14.5,places=8)

    def test_beam_driven_downstream_placement_and_measurement(self):
        root=Layout('Driven')
        beam=root.add(BeamPath('Beam',wavelength=1550,waist=.2,bound_parent=root),(-50,0,0),0)
        roof=beam.add(catalog.create('roof','Roof'),beam_index=1,rotation=0,distance=50)
        receiver=beam.add(Component('Receiver',Receiver()),beam_index=1,rotation=0,
            distance=40,after_object=roof)
        root.recompute()
        self.assert_vector(roof.get_object().Placement.Base,(0,0,0))
        self.assert_vector(receiver.get_object().Placement.Base,(-40,-12.7,0))
        self.assertEqual(beam.get_output_indices(roof),[1])
        properties=beam.measure_properties(roof)
        self.assert_vector(properties.position,(50,-12.7,0))  # Relative to beam origin.
        self.assertEqual(properties.beam_obj.get_object().StartInterfaceName,'exit')
        self.assertAlmostEqual(beam.measure_component_pass(roof)['geometric_length_mm'],25.4,places=8)
        for kwargs in ({'pass_index':-1},{'pass_index':1},{'refractive_index':0},{'refractive_index':math.nan}):
            with self.assertRaises(ValueError):beam.measure_component_pass(roof,**kwargs)

    def test_integral_support_contract_native_heights_and_fit(self):
        for orientation,height in [('horizontal',12.7),('vertical',6.35)]:
            roof=catalog.create('roof',orientation,orientation=orientation)
            roof.recompute()
            objects=roof.get_object().Children
            self.assertEqual(len(objects),4)
            self.assertTrue(all(not o.Shape.isNull() and o.Shape.isValid() for o in objects))
            support=next(o for o in objects if o.Proxy.contract().catalog_id=='roof-integral-support')
            clamp=next(o for o in objects if o.Proxy.contract().catalog_id=='roof-clamp')
            self.assertEqual(len(support.Shape.Solids),1)
            self.assertAlmostEqual(catalog.native_height(roof),height,places=8)
            self.assertEqual(len(support.Proxy.contract().holes),1)
            hole=support.Proxy.contract().holes[0]
            self.assertEqual((hole.diameter_mm,hole.thread),(1.6,'M2 x 0.4'))
            self.assertEqual(clamp.Proxy.contract().holes[0].diameter_mm,2.2)
            self.assertIsNone(attachments.profile(support.Proxy))
            self.assertEqual(len(support.Proxy.drill().Solids),1)
            self.assertEqual(support.Proxy.baseplate_integration()['holes'],['clamp_tap'])
            for o in [roof.get_object(),*objects]:
                c=o.Proxy.contract()
                self.assertEqual(ComponentContract.from_dict(json.loads(o.ComponentContract)),c)
            for i,a in enumerate(objects):
                for b in objects[i+1:]:
                    if (a is support and b.Label.startswith('M2 clamp screw')
                            or b is support and a.Label.startswith('M2 clamp screw')):
                        continue
                    self.assertLess(a.Shape.common(b.Shape).Volume,1e-6,(a.Label,b.Label))
            rows=catalog.bom(roof)
            self.assertEqual(sum(r['part_number']=='HRS1015-P01' for r in rows),1)
            self.assertEqual(sum(r['part_number'].startswith('M2') for r in rows),1)
            self.assertFalse(any(r['part_number'].startswith(('M3','M4')) for r in rows))
            self.assertFalse(next(r for r in rows if r['catalog_id']=='roof-integral-support')['separate_part'])
            profile=support.Proxy.baseplate_integration();profile['holes'].clear()
            self.assertEqual(support.Proxy.baseplate_integration()['holes'],['clamp_tap'])

    def test_user_corrected_source_geometry_and_m2_adaptations(self):
        for orientation in ('horizontal','vertical'):
            g=RoofGeometry(orientation);spec=support_reference(g)
            source=resolve_reference(spec['source_reference'])
            self.assertEqual(spec['thread'],'M2 x 0.4')
            support=RoofSupport(g).shape();clamp=RoofClamp(g).shape()
            self.assertTrue(support.isValid() and clamp.isValid())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),spec['sha256'])
            solids=Part.read(str(source)).Solids
            original_body=support_shape(g,solids[2])
            original_clamp=support_shape(g,solids[0])
            # Deliberate changes are confined to the tap drill and clearance slot.
            hole=App.Vector(*support_point(g,spec['hole_center_mm']))
            allowed=Part.makeCylinder(1.11,spec['hole_depth_mm']+.6,hole,App.Vector(0,0,-1))
            delta=original_body.cut(support).fuse(support.cut(original_body)).cut(allowed)
            self.assertLess(delta.Volume,.1)
            slot=support_shape(g,capsule(spec['slot_end_centers_mm'],2.21,-12.71,5.1))
            delta=original_clamp.cut(clamp).fuse(clamp.cut(original_clamp)).cut(slot)
            self.assertLess(delta.Volume,.1)
            for expected,actual in [(original_body,support),(original_clamp,clamp)]:
                a,b=expected.optimalBoundingBox(),actual.optimalBoundingBox()
                self.assertTrue(all(abs(getattr(a,k)-getattr(b,k))<.01 for k in ('XMin','XMax','YMin','YMax','ZMin','ZMax')))
            # The AG-labelled file is a mechanical reference, not a coating swap.
            optic=catalog.create('HRS1015-P01','P01',orientation=orientation);optic.recompute()
            original_optic=support_shape(g,solids[1])
            self.assertLess(original_optic.cut(optic.get_object().Shape).Volume,1e-5)
            self.assertLess(optic.get_object().Shape.cut(original_optic).Volume,1e-5)

    def plate_scene(self, orientation, machined, nested=True):
        root=Layout('Plate layout')
        root.get_object().BasePlacement=App.Placement(App.Vector(50,60,3),App.Rotation('XYZ',0,0,17))
        owner=root
        if nested:
            owner=root.add(Layout('Nested assembly'),(40,40,0),-11)
        height=12.7 if orientation=='horizontal' else 6.35
        roof=owner.add(catalog.create('roof','Roof',orientation=orientation),(30,30,12.7 if machined else height),37)
        if machined:
            plate,definition=machined_baseplate.add(root,thickness=30)
        else:
            definition=None
            plate=root.add(Component('Plate',Baseplate((160,160,30),grid_offset=(0,0)),recompute_priority=-2),(0,0,0),0)
        root.recompute()
        return root,roof,plate,definition

    def test_both_baseplate_workflows_nested_and_recomputed(self):
        for orientation in ('horizontal','vertical'):
            for machined in (False,True):
                root,roof,plate,definition=self.plate_scene(orientation,machined)
                support=next(o for o in roof.get_object().Children if o.Proxy.contract().catalog_id=='roof-integral-support')
                inverse=plate.get_object().Placement.inverse()
                ops=attachments.integration_operations(support.Proxy,inverse*support.Placement)
                self.assertEqual([op['kind'] for op in ops],['tapped'])
                self.assertTrue(ops[0]['integrated'])
                self.assertEqual(ops[0]['thread'],'M2 x 0.4')
                self.assertEqual(ops[0]['diameter_mm'],1.6)
                shape=plate.get_object().Shape.copy();shape.Placement=App.Placement()
                self.assertTrue(shape.isValid());self.assertEqual(len(shape.Solids),1)
                for op in ops:
                    p=App.Vector(*op['center_mm'])+App.Vector(0,0,-1)
                    self.assertFalse(shape.isInside(p,1e-7,False))
                    self.assertTrue(shape.isInside(p+App.Vector(0,0,-12),1e-7,False))
                if machined:
                    self.assertEqual(len(definition.plan['holes']),1)
                    self.assertEqual(definition.plan['pockets'],[])
                    self.assertEqual(definition.integrated_names,[support.Name])
                    self.assertAlmostEqual(next(iter(definition.plan['optical_heights_mm'].values())),12.7,places=6)
                # Purchased geometry and fabrication solids remain uncut.
                self.assertAlmostEqual(support.Shape.Volume,RoofSupport(RoofGeometry(orientation)).shape().Volume,places=6)
                before=(len(self.doc.Objects),plate.get_object().Shape.Volume)
                root.recompute()
                self.assertEqual(len(self.doc.Objects),before[0])
                self.assertAlmostEqual(plate.get_object().Shape.Volume,before[1],places=6)
                # Move the nested installation and check fresh physical bores.
                roof.get_object().BasePlacement.Base+=App.Vector(5,7,0)
                root.recompute()
                if machined:self.assertEqual(len(definition.plan['holes']),1)
                fresh=plate.get_object().Shape.copy();fresh.Placement=App.Placement()
                for op in attachments.integration_operations(support.Proxy,inverse*support.Placement):
                    self.assertFalse(fresh.isInside(App.Vector(*op['center_mm'])+App.Vector(0,0,-1),1e-7,False))

    def test_insufficient_stock_and_independent_instances(self):
        root=Layout('Thin plate')
        a=root.add(catalog.create('roof','A'),(0,0,12.7),0)
        b=root.add(catalog.create('roof','B',orientation='vertical',beam_separation=20),(80,0,12.7),0)
        root.recompute()
        before=b.get_object().Children[0].Shape.copy()
        a.get_object().BasePlacement.Base+=App.Vector(10,20,0)
        root.recompute()
        self.assertEqual(before.Placement,b.get_object().Children[0].Shape.Placement)
        self.assertAlmostEqual(before.Volume,b.get_object().Children[0].Shape.Volume,places=6)
        machined_baseplate.add(root,thickness=11)
        with self.assertRaisesRegex(ValueError,'stock|breaks through'):root.recompute()

    def test_integral_union_preserves_neighboring_mount_bores(self):
        for machined in (False,True):
            root=Layout('Integral and ordinary mount')
            root.add(catalog.create('roof','Roof'),(70,70,12.7),0)
            # One iris pin lies inside the buried reference patch and the
            # other outside. The optic itself is clear of the roof assembly.
            iris=root.add(catalog.create('iris','Iris'),(66,82,12.7),0)
            if machined:
                plate,definition=machined_baseplate.add(root,thickness=30)
            else:
                plate=root.add(Component('Plate',Baseplate((160,160,30),grid_offset=(0,0)),recompute_priority=-2),(0,0,0),0)
            root.recompute()
            inverse=plate.get_object().Placement.inverse()
            shape=plate.get_object().Shape.copy();shape.Placement=App.Placement()
            for op in attachments.operations(iris,inverse*iris.get_object().Placement):
                self.assertFalse(shape.isInside(App.Vector(*op['center_mm'])+App.Vector(0,0,-1),1e-7,False))
            if machined:
                self.assertEqual(len(definition.plan['holes']),3)
                self.assertEqual(sum(op['kind']=='dowel' for op in definition.plan['holes']),2)

    def test_neighbors_cannot_drill_the_roof_assembly(self):
        class Neighbor:
            object_group='mounts'
            apply_drilling=False
            drill_groups=('optics','adapters','fasteners')
            def shape(self):return Part.makeBox(100,100,100,App.Vector(-50,-50,-50))
            def drill(self):return self.shape()
        root=Layout('Protected assembly')
        roof=root.add(catalog.create('roof','Roof'),(0,0,0),0)
        root.recompute()
        before={o.Name:o.Shape.Volume for o in roof.get_object().Children}
        root.add(Component('Neighbor',Neighbor()),(0,0,0),0)
        for o in roof.get_object().Children:o.Proxy.computed_shape=False
        root.recompute()
        for o in roof.get_object().Children:
            self.assertAlmostEqual(o.Shape.Volume,before[o.Name],places=6)

    def test_review_export_contracts_bom_and_cache_independent_reopen(self):
        from examples import roof_mirror as demo
        before=set(App.listDocuments())
        try:
            with tempfile.TemporaryDirectory() as folder:
                output=Path(folder)/'roof.FCStd'
                static,report=demo.build(output)
                checks=report['verification']
                self.assertEqual(checks['external_pins'],0)
                self.assertEqual(checks['physical_bores_checked'],2)
                self.assertEqual(len(report['machining']['pockets']),0)
                self.assertEqual(len(report['machining']['integrated_holders']),2)
                self.assertEqual(checks['hardware_solid_count'],11)
                self.assert_vector(report['machining']['stock_envelope_mm'],(85,170,49.05),tol=1e-5)
                self.assertTrue(checks['native_reopen_valid'])
                self.assertEqual(sum(r['part_number']=='HRS1015-P01' for r in report['bom'] if 'part_number' in r),2)
                for suffix,field in [('.report.json',None),('.machining.json','machining'),('.bom.json','bom')]:
                    value=json.loads(output.with_suffix(suffix).read_text())
                    self.assertEqual(value,report if field is None else report[field])
                for obj in static.Objects:
                    if hasattr(obj,'ComponentContract'):
                        c=ComponentContract.from_dict(json.loads(obj.ComponentContract))
                        self.assertEqual(c,ComponentContract.from_dict(c.to_dict()))
                for orientation in ('horizontal','vertical'):
                    standalone=Part.read(str(output.with_name(output.stem+'_clamp_'+orientation+'.step')))
                    self.assertTrue(standalone.isValid())
                    self.assertEqual(len(standalone.Solids),1)
                App.closeDocument(static.Name)
                with patch.object(catalog,'vendor_shape',side_effect=AssertionError('No cache needed')):
                    reopened=App.openDocument(str(output))
                    features=[o for o in reopened.Objects if o.TypeId=='Part::Feature']
                    self.assertEqual(len(features),17)  # 7 physical features + 10 beam legs.
                    self.assertTrue(all(o.Shape.isValid() and not hasattr(o,'Proxy') for o in features))
                with self.assertRaisesRegex(ValueError,'stock|breaks through'):
                    demo.build(Path(folder)/'thin.FCStd',plate_thickness=11)
        finally:
            for name in set(App.listDocuments())-before:
                App.closeDocument(name)


if __name__=='__main__':unittest.main()
