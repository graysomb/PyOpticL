"""Exact MK05S, parametric grating carrier, finite diffraction and plate cuts."""
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

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PyOpticL import attachments, lab_catalog as catalog, machined_baseplate
from PyOpticL.beam_path import BeamPath, TransmissionGrating, circular_polarization, grating_angles
from PyOpticL.component_contract import ComponentContract, Thread, MechanicalInterface, connection_check
from PyOpticL.grating import (GratingAdapter, GratingOptic, MK05SMount, reference)
from PyOpticL.layout import Component, Layout
from PyOpticL.library import Baseplate
from PyOpticL.vendor_cad import resolve
from examples import grating as demo


class GratingTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('GratingAcceptance')
        self.addCleanup(App.closeDocument,self.doc.Name)

    def assert_vector(self, actual, expected, tolerance=1e-7):
        self.assertLess((App.Vector(*actual)-App.Vector(*expected)).Length,tolerance)

    def scene(self, wavelength=1550., direction=(1,0,0), hit=(0,0,0), placement=None,
              mounted=True, order=1, incidence=49.9):
        root = Layout('Ray scene')
        # Parent transform exercises world/local aperture and direction handling.
        if placement:
            root.get_object().BasePlacement = placement
        part = root.add(catalog.create('grating' if mounted else 'LightSmyth-1336552','Grating',
            **dict(order=order,**({'incidence_angle':incidence} if mounted else {}))), (0,0,0),0)
        part.compute_placement()
        p = part.get_object().Placement
        d = App.Vector(*direction);d.normalize()
        source = App.Vector(*hit)-50*d
        angles = App.Rotation(App.Vector(1,0,0),d).toEulerAngles('XYZ')
        beam = root.add(BeamPath('Test ray',wavelength=wavelength,waist=.2,power=.001,
            polarization=circular_polarization(),bound_parent=root),tuple(source),tuple(angles))
        receiver = beam.add(Component('Receiver',demo.Receiver()),1,0,distance=50,after_object=part)
        root.recompute()
        return root,part,beam,receiver

    def test_source_pins_and_normalized_vendor_solids(self):
        r = reference()
        for kind in ('step','pdf'):
            record = json.loads((catalog.DATA/'assets'/('MK05S.'+kind+'.json')).read_text())
            self.assertEqual(hashlib.sha256(resolve(record).read_bytes()).hexdigest(),r['step_sha256' if kind=='step' else 'drawing_sha256'])
        data = (Path.home()/'.cache/pyopticl/cad'/r['grating']['datasheet_cache_path']).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),r['grating']['datasheet_sha256'])
        source = catalog.vendor_shape('MK05S')
        normalized = MK05SMount().shape()
        self.assertEqual(len(source.Solids),25)
        self.assertEqual(len(normalized.Solids),25)
        self.assertTrue(normalized.isValid())
        self.assertAlmostEqual(source.Volume,r['source_volume_mm3'],places=6)
        inverse = App.Placement(App.Vector(*r['normalization']['origin']),
            App.Rotation('XYZ',*r['normalization']['rotation']).inverted())
        recovered = normalized.copy()
        recovered.Placement = inverse*recovered.Placement
        for a,b,volume in zip(source.Solids,normalized.Solids,r['source_solid_volumes_mm3']):
            self.assertAlmostEqual(a.Volume,b.Volume,places=6)
            self.assertAlmostEqual(a.Volume,volume,places=6)
        for a,b in zip(source.Solids,recovered.Solids):
            self.assert_vector(a.CenterOfMass,b.CenterOfMass)
            self.assertAlmostEqual(a.Area,b.Area,places=5)
        bounds = source.optimalBoundingBox()
        self.assert_vector((bounds.XLength,bounds.YLength,bounds.ZLength),(20.2184,21.1836,16.1178),.01)
        for hole in r['source_mounting_holes']:
            center,axis = App.Vector(*hole['center_mm']),App.Vector(*hole['axis'])
            faces = [f for f in source.Faces if isinstance(f.Surface,Part.Cylinder)
                and abs(f.Surface.Radius-hole['diameter_mm']/2)<.01
                and abs(abs(f.Surface.Axis.dot(axis))-1)<1e-8
                and (f.Surface.Center-center).cross(axis).Length<.01]
            self.assertTrue(faces,hole['name'])
            distances = [(v.Point-center).dot(-axis) for f in faces for v in f.Vertexes]
            self.assertAlmostEqual(min(distances),hole['straight_start_mm'],places=5)
            self.assertAlmostEqual(max(distances),hole['straight_end_mm'],places=5)
            samples = [v for f in faces for v in f.tessellate(.01)[0]]
            self.assertAlmostEqual(max((v-center).dot(-axis) for v in samples),hole['trimmed_max_depth_mm'],places=4)

    def test_grating_envelope_and_direct_pocket_fit(self):
        glass,mount = GratingOptic().shape(),MK05SMount().shape()
        self.assertTrue(glass.isValid() and mount.isValid())
        b = glass.optimalBoundingBox()
        self.assert_vector((b.XLength,b.YLength,b.ZLength),(.95,31.8,12.3))
        self.assertLess(glass.common(mount).Volume,1e-7)
        self.assertLess(glass.distToShape(mount)[0],1e-7)
        r = reference()
        inverse = App.Placement(App.Vector(*r['normalization']['origin']),
            App.Rotation('XYZ',*r['normalization']['rotation']).inverted())
        glass.Placement = inverse
        bounds = glass.optimalBoundingBox()
        actual = [bounds.XMin,bounds.YMin,bounds.ZMin,bounds.XMax,bounds.YMax,bounds.ZMax]
        self.assertTrue(np.allclose(actual,r['direct_seating']['native_glass_bounds_mm'],atol=1e-7))
        # The 0.95 mm glass straddles the existing locking screw's depth axis.
        self.assertAlmostEqual((bounds.ZMin+bounds.ZMax)/2,-2.54,places=7)
        bottom = next(f for f in glass.Faces if abs(f.CenterOfMass.y+6.35)<1e-7
                      and abs(f.normalAt(0,0).y)>0.99)
        self.assertLess(catalog.vendor_shape('MK05S').distToShape(bottom)[0],1e-7)

    def test_adapter_contract_component_holes_and_plate_bores_are_distinct(self):
        adapter = GratingAdapter();shape = adapter.shape()
        self.assertTrue(shape.isValid() and len(shape.Solids)==1)
        c = adapter.contract()
        self.assertEqual(len(c.holes),5)  # Includes the internal MK05S clearance.
        ops = attachments.operations(adapter)
        self.assertEqual(len(ops),4)
        self.assertEqual({o['interface'] for o in ops},{'plate_1','plate_2','pin_1','pin_2'})
        self.assertEqual(len(adapter.drill().Solids),4)
        pins = [o for o in ops if o['kind']=='dowel']
        for p in pins:
            self.assertEqual((p['diameter_mm'],p['depth_mm'],p['projection_mm']),(2.01,4.445,.555))
            self.assertEqual(p['diameter_limits_mm'],[2.0066,2.02184])
            self.assertEqual(p['depth_tolerance_mm'],[0,.0508])
            start = App.Vector(*p['center_mm'])
            self.assertFalse(shape.isInside(start+App.Vector(0,0,1),1e-7,False))
            self.assertTrue(shape.isInside(start+App.Vector(0,0,3),1e-7,False))
        self.assertEqual(sum(o.get('thread')=='M4 x 0.7' for o in ops),2)

    def test_native_heights_and_exact_thread_standard(self):
        mount = catalog.create('MK05S','Mount')
        grating = catalog.create('grating','Assembly')
        self.assertAlmostEqual(catalog.native_height(mount),10.5061,places=6)
        self.assertAlmostEqual(catalog.native_height(grating),20.5061,places=6)
        seat = next(i for i in mount.contract().interfaces if i.name=='bottom_post')
        good = MechanicalInterface('screw','origin','thread',Thread('4-40 UNC','external',2.8448,.635))
        wrong = MechanicalInterface('screw','origin','thread',Thread('M3 x 0.5','external',3,.5))
        self.assertTrue(connection_check(seat,good)[0])
        self.assertFalse(connection_check(seat,wrong)[0])
        self.assertAlmostEqual(seat.engagement_mm,2.771,places=6)

    def test_direct_mount_contact_and_no_extra_optic_holder(self):
        root = Layout('Direct mount contact')
        part = root.add(catalog.create('grating','Grating'),(0,0,20.5061),0)
        root.recompute()
        objects = list(part.get_object().Children)
        self.assertEqual(len(objects),6)
        fabricated = [o.Proxy.contract().catalog_id for o in objects
                      if o.Proxy.contract().procurement=='fabricated']
        self.assertEqual(fabricated,['grating-adapter'])
        glass = next(o for o in objects if o.Proxy.contract().catalog_id=='LightSmyth-1336552')
        mount = next(o for o in objects if o.Proxy.contract().catalog_id=='MK05S')
        self.assertAlmostEqual(demo._contact_area(glass.Shape,mount.Shape),7.45029298,places=5)
        self.assertLess(glass.Shape.common(mount.Shape).Volume,1e-7)
        self.assertEqual(len(mount.Shape.Solids),25)
        self.assertAlmostEqual(reference()['direct_seating']['reference_lock_gap_mm'],.55875,places=7)

    def test_analytical_angles_units_zero_order_and_symmetric_condition(self):
        a = grating_angles()
        self.assertAlmostEqual(a['diffraction_angle_deg'],51.72794830005952,places=10)
        self.assertAlmostEqual(a['deflection_angle_deg'],101.62794830005953,places=10)
        self.assertEqual(a['period_mm'],.001)
        self.assertEqual(catalog.grating_angles(),a)
        self.assertAlmostEqual(grating_angles(order=0)['deflection_angle_deg'],0,places=10)
        angle = math.degrees(math.asin(1.55/2))
        self.assertAlmostEqual(grating_angles(incidence_angle_deg=angle)['diffraction_angle_deg'],angle,places=10)

    def test_invalid_parameters_and_nonpropagating_nominal_configuration(self):
        for value in (0,-1,math.nan,math.inf):
            with self.subTest(value=value),self.assertRaises(ValueError):grating_angles(wavelength_nm=value)
            with self.subTest(value=value),self.assertRaises(ValueError):TransmissionGrating(grooves_per_mm=value)
        for value in (1.5,True,math.inf):
            with self.assertRaises(ValueError):catalog.create('LightSmyth-1336552','Invalid',order=value)
        for value in (math.nan,90,-90):
            with self.assertRaises(ValueError):catalog.create('grating','Invalid',incidence_angle=value)
        with self.assertRaises(ValueError):catalog.create('grating','Invalid',incidence_angle=0)
        with self.assertRaises(ValueError):catalog.create('grating','Invalid',mount='MK05S/M')
        with self.assertRaises(TypeError):catalog.create('MK05S','Invalid',height=12.7)
        with self.assertRaises(TypeError):catalog.create('grating','Invalid',unknown=1)
        with self.assertRaises(ValueError):TransmissionGrating(clear_width=40)

    def test_nominal_trace_and_after_object_receiver(self):
        _,part,beam,receiver = self.scene()
        segments = beam.get_object().BeamSegments
        self.assertEqual(len(segments),2)
        self.assertEqual(segments[0].EndObject,part.get_object())
        self.assertEqual(segments[1].EndObject,receiver.get_object())
        a = math.radians(101.62794830005953)
        self.assert_vector(segments[1].Proxy.get_global_direction(),(math.cos(a),math.sin(a),0))
        self.assert_vector(receiver.get_object().Placement.Base,(50*math.cos(a),50*math.sin(a),0))
        self.assertEqual(beam.get_output_indices(part),[1])
        measured = beam.measure_properties(part)
        self.assertAlmostEqual(measured.beam_obj.power,.001,places=10)
        self.assertAlmostEqual(segments[1].Power.getValueAs('W').Value,.001,places=10)
        self.assert_vector(measured.position,(50,0,0))
        self.assertAlmostEqual(sum(s.Proxy.distance for s in segments),100.,places=7)

    def test_dispersion_uses_actual_wavelength_not_design_value(self):
        results = []
        for wavelength in (1525.,1550.,1565.):
            _,part,beam,_ = self.scene(wavelength=wavelength)
            direction = beam.get_object().BeamSegments[1].Proxy.get_global_direction()
            angle = math.degrees(math.atan2(direction[1],direction[0]))
            expected = 49.9+math.degrees(math.asin(wavelength*.001-math.sin(math.radians(49.9))))
            self.assertAlmostEqual(angle,expected,places=8)
            self.assertEqual(part.angles['wavelength_nm'],1550.)
            results.append(angle)
        self.assertLess(results[0],results[1]);self.assertLess(results[1],results[2])

    def test_skew_momentum_and_nested_roll_yaw_translation(self):
        p = App.Placement(App.Vector(70,-30,14),App.Rotation('XYZ',19,11,37))
        d = np.array((1,.01,.03));d/=np.linalg.norm(d)
        _,part,beam,_ = self.scene(direction=tuple(d),placement=p)
        incoming,outgoing = beam.get_object().BeamSegments
        n = part.interfaces()[0].get_global_normal()
        u = part.interfaces()[0].get_global_transverse()
        e = np.cross(n,u)
        a,b = incoming.Proxy.get_global_direction(),outgoing.Proxy.get_global_direction()
        self.assertAlmostEqual((b-a)@u,1.55,places=8)
        self.assertAlmostEqual(b@e,a@e,places=8)
        self.assertGreater((a@n)*(b@n),0)
        self.assertAlmostEqual(np.linalg.norm(b),1,places=8)
        self.assert_vector(beam.measure_properties(part).position,50*d)

    def test_actual_incidence_reciprocity_and_zeroth_order(self):
        # Use bare grating to test arbitrary actual angle and reverse direction.
        d = np.array((math.cos(math.radians(52)),-math.sin(math.radians(52)),.02));d/=np.linalg.norm(d)
        _,part,beam,_ = self.scene(mounted=False,direction=tuple(d))
        out = beam.get_object().BeamSegments[1].Proxy.get_global_direction()
        reverse = part.interfaces()[0].diffracted_direction(-out,1550.)
        self.assert_vector(reverse,-d)
        _,_,zero,_ = self.scene(mounted=False,direction=tuple(d),order=0)
        self.assert_vector(zero.get_object().BeamSegments[1].Proxy.get_global_direction(),d)

    def test_local_rectangular_aperture_edges_and_misses(self):
        alpha = math.radians(49.9)
        rotation = App.Rotation('XYZ',0,0,49.9)
        transform = App.Placement(App.Vector(15,27,8),App.Rotation('XYZ',23,-17,61))
        for face_point,transmits,interacts in [((0,15.39,5.64),True,True),
                ((0,15.6,0),False,True),((0,0,5.9),False,True),
                ((0,15.4,0),False,True),((0,16.,0),False,False)]:
            hit = rotation.multVec(App.Vector(*face_point))
            _,part,beam,_ = self.scene(hit=tuple(hit),placement=transform)
            segments = beam.get_object().BeamSegments
            self.assertEqual(len(segments),2 if transmits else 1)
            self.assertEqual(segments[0].EndObject==part.get_object(),interacts)

    def test_grazing_and_nonpropagating_actual_ray_terminate(self):
        _,_,beam,_ = self.scene(mounted=False,direction=(1,0,0))  # First order impossible at normal incidence.
        self.assertEqual(len(beam.get_object().BeamSegments),1)
        interface = TransmissionGrating()
        # Global getters normally depend on parent placement.
        interface.get_global_normal = lambda:np.array((1.,0,0))
        interface.get_global_transverse = lambda:np.array((0.,1,0))
        self.assertIsNone(interface.diffracted_direction((0,1,0),1550))
        self.assertIsNone(interface.diffracted_direction((1,0,0),1550))
        with self.assertRaises(ValueError):interface.diffracted_direction((1,0,0),math.nan)

    def test_gaussian_and_jones_transport_preserve_scalar_model(self):
        _,_,beam,_ = self.scene(direction=(1,.01,.03))
        incoming,outgoing = beam.get_object().BeamSegments
        a,b = incoming.Proxy,outgoing.Proxy
        self.assertAlmostEqual(b.rayleigh_range,a.rayleigh_range,places=9)
        self.assertAlmostEqual(b.waist_position,a.waist_position-a.distance,places=9)
        ja,jb = np.asarray(a.polarization_jones),np.asarray(b.polarization_jones)
        def complex_jones(j):return j[:,0]+1j*j[:,1] if j.shape==(2,2) else j
        ja,jb = complex_jones(ja),complex_jones(jb)
        self.assertAlmostEqual(np.vdot(jb,jb).real,1.,places=9)
        self.assertAlmostEqual(abs(jb[0]*jb[1].conjugate()).real,.5,places=8)
        self.assertAlmostEqual(b.power,a.power,places=10)
        self.assertEqual(b.wavelength,a.wavelength)

    def test_both_baseplate_workflows_nested_transform_and_recompute(self):
        root = Layout('Plate scene')
        root.get_object().BasePlacement = App.Placement(App.Vector(20,30,4),App.Rotation('XYZ',0,0,17))
        nested = root.add(Layout('Nested installation'),(120,100,0),29)
        part = nested.add(catalog.create('grating','Grating'),(0,0,20.5061),13)
        regular = root.add(Component('Ordinary plate',Baseplate((260,260,30),optical_height=0,
            grid_offset=(0,0)),recompute_priority=-2),(0,0,0),0)
        plate,definition = machined_baseplate.add(root,thickness=30)
        root.recompute()
        for dx in (0,7):
            if dx:
                part.get_object().BasePlacement.Base+=App.Vector(dx,3,0)
                root.recompute()
            self.assertEqual(len(definition.plan['holes']),4)
            self.assertEqual(definition.plan['pockets'],[])
            for target in (regular,plate):
                shape = target.get_object().Shape
                self.assertTrue(shape.isValid() and len(shape.Solids)==1)
                for op in definition.plan['holes']:
                    p = root.get_object().Placement.multVec(App.Vector(*op['center_mm'])+App.Vector(0,0,-1))
                    self.assertFalse(shape.isInside(p,1e-7,False))
                    p = root.get_object().Placement.multVec(App.Vector(*op['center_mm'])+App.Vector(0,0,-12))
                    self.assertTrue(shape.isInside(p,1e-7,False))
            before = len(self.doc.Objects),plate.get_object().Shape.Volume
            root.recompute()
            self.assertEqual(before[0],len(self.doc.Objects))
            self.assertAlmostEqual(before[1],plate.get_object().Shape.Volume,places=6)

    def test_independent_instances_contract_serialization_bom_and_drill_protection(self):
        root = Layout('Independent instances')
        a = root.add(catalog.create('grating','A'),(0,0,0),0)
        b = root.add(catalog.create('grating','B',incidence_angle=53,design_wavelength=1540),(100,0,0),15)
        root.recompute()
        original = [(o.Shape.Volume,o.Placement) for o in b.get_object().Children]
        a.get_object().BasePlacement.Base+=App.Vector(4,5,6)
        class Neighbor:
            object_group='mounts'
            apply_drilling=False
            drill_groups=('mounts','optics','adapters','fasteners')
            def shape(self):return Part.makeBox(300,300,300,App.Vector(-100,-100,-100))
            def drill(self):return self.shape()
        root.add(Component('Drilling neighbor',Neighbor()),(0,0,0),0)
        for o in b.get_object().Children:o.Proxy.computed_shape=False
        root.recompute()
        for obj,(volume,placement) in zip(b.get_object().Children,original):
            self.assertAlmostEqual(obj.Shape.Volume,volume,places=6)
            self.assertEqual(obj.Placement,placement)
            c = obj.Proxy.contract()
            self.assertEqual(c,ComponentContract.from_dict(json.loads(json.dumps(c.to_dict()))))
        rows = catalog.bom(b)
        self.assertEqual(sum(r['part_number']=='MK05S' for r in rows),1)
        self.assertEqual(sum(r['part_number']=='1336552' for r in rows),1)
        self.assertEqual([r['catalog_id'] for r in rows if r['procurement']=='fabricated'],['grating-adapter'])

    def test_insufficient_stock_rejection(self):
        root = Layout('Thin plate')
        root.add(catalog.create('grating','Grating'),(0,0,20.5061),0)
        machined_baseplate.add(root,thickness=11)
        with self.assertRaisesRegex(ValueError,'stock|breaks through'):root.recompute()

    def test_review_mechanical_fit_and_export_reopen_integrity(self):
        before = set(App.listDocuments())
        try:
            with tempfile.TemporaryDirectory() as folder:
                output = Path(folder)/'review.FCStd'
                static,report = demo.build(output)
                checks = report['verification']
                self.assertEqual(checks['physical_bores_checked'],4)
                self.assertEqual(checks['external_pins'],2)
                self.assertEqual(checks['hardware_solid_count'],33)
                self.assertEqual(len(checks['thread_envelope_overlaps']),0)
                self.assertTrue(checks['beam_hardware_clear'] and checks['step_valid'])
                self.assertTrue(checks['adjuster_access_checked'])
                for suffix in ('adapter','baseplate'):
                    shape = Part.read(str(output.with_name('review_'+suffix+'.step')))
                    self.assertTrue(shape.isValid())
                    self.assertEqual(len(shape.Solids),1)
                self.assertEqual(json.loads(output.with_suffix('.bom.json').read_text()),report['bom'])
                App.closeDocument(static.Name)
                with patch.object(catalog,'vendor_shape',side_effect=AssertionError('Static review must not need cache')):
                    reopened = App.openDocument(str(output))
                    shapes = [o for o in reopened.Objects if o.TypeId=='Part::Feature']
                    self.assertEqual(len(shapes),11)
                    self.assertTrue(all(not hasattr(o,'Proxy') and o.Shape.isValid() for o in shapes))
        finally:
            for name in set(App.listDocuments())-before:App.closeDocument(name)


if __name__=='__main__':unittest.main()
