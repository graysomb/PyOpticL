"""Stage/payload ownership, motion, manufacturing and live document regression."""
import json
from dataclasses import replace
from pathlib import Path
import sys,tempfile,unittest
from types import SimpleNamespace
import FreeCAD as App
import Part
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PyOpticL import attachments,stages,lab_catalog
from PyOpticL.layout import Layout,Component
from PyOpticL.library import Baseplate
from examples.translation_stage_payload import build


class StageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory()
        cls.scene=build(Path(cls.directory.name)/'stage.FCStd')
        cls.stage=cls.scene['stage'];cls.root=cls.scene['root']
        cls.adapter=cls.scene['adapter'];cls.doc=cls.scene['document']
        cls.spec=stages.AdapterSpec(**json.loads(cls.adapter.get_object().AdapterSpec))

    @classmethod
    def tearDownClass(cls):
        if App.getDocument(cls.doc.Name):App.closeDocument(cls.doc.Name)
        cls.directory.cleanup()

    def test_01_source_and_ownership(self):
        fixed,moving=self.stage.get_object().Children[:2]
        self.assertEqual(len(fixed.Shape.Solids)+len(moving.Shape.Solids),61)
        source=stages._source();moving_ids=set(stages.reference()['moving_solids'])
        for part,indices in ((fixed,[i for i in range(61) if i not in moving_ids]),
                             (moving,sorted(moving_ids))):
            for actual,index in zip(part.Shape.Solids,indices):
                # FreeCAD copies topology into document properties. Compare
                # complete vertices and topology counts, not pointer identity
                # or numerically grouping-sensitive spline compound volumes.
                expected=source.Solids[index]
                self.assertEqual((len(actual.Faces),len(actual.Edges),len(actual.Vertexes)),
                                 (len(expected.Faces),len(expected.Edges),len(expected.Vertexes)))
                for a,b in zip(actual.Vertexes,expected.Vertexes):
                    self.assertLess((a.Point-b.Point).Length,.01,index)
        report=self.scene['machining'].plan
        self.assertEqual(len(report['holes']),4)
        self.assertTrue(all(h['part']=='XR25C' for h in report['holes']))
        a=json.loads(self.adapter.get_object().MachiningPlan)
        self.assertEqual(len(a['holes']),7)
        self.assertEqual(sum(h['kind']=='dowel' for h in a['holes']),2)
        self.assertEqual(sum(h['kind']=='tapped' for h in a['holes']),1)
        for obj in attachments.descendants(self.scene['mirror'].get_object()):
            self.assertEqual(attachments.receiving_part(obj),self.adapter.get_object())
        self.assertEqual(len(list(attachments.plate_attachments(self.root.get_object(),self.scene['plate'].get_object()))),4)

    def test_02_motion_and_invariant_machining(self):
        fixed,moving=self.stage.get_object().Children[:2]
        start=App.Vector(self.scene['mirror'].get_object().Placement.Base)
        base_start=App.Vector(fixed.Placement.Base)
        carriage=App.Vector(moving.Placement.Base)
        plate=self.scene['plate'].get_object(); volume=plate.Shape.Volume
        report=json.dumps(self.scene['machining'].plan,sort_keys=True)
        adapter_report=self.adapter.get_object().MachiningPlan
        for value in (-12.5,-5,0,5,12.5):
            self.stage.set_travel(value)
            self.assertLess((self.scene['mirror'].get_object().Placement.Base-start-App.Vector(value,0,0)).Length,1e-7)
            self.assertLess((fixed.Placement.Base-base_start).Length,1e-7)
            self.assertLess((moving.Placement.Base-carriage-App.Vector(value,0,0)).Length,1e-7)
            self.assertAlmostEqual(plate.Shape.Volume,volume,places=5)
            self.assertEqual(json.dumps(self.scene['machining'].plan,sort_keys=True),report)
            self.assertEqual(self.adapter.get_object().MachiningPlan,adapter_report)
            self.assertAlmostEqual(self.scene['beam'].get_object().BeamSegments[0].Proxy.distance,100+value,places=5)
        self.stage.set_travel(0)
        with self.assertRaises(ValueError):self.stage.set_travel(12.6)
        self.stage.get_object().Travel=13
        self.assertEqual(self.stage.get_object().Travel.Value,0)
        self.assertIn('within',self.stage.get_object().MotionError)
        self.stage.set_travel(0)

    def test_03_rotated_stage(self):
        obj=self.stage.get_object();original=obj.BasePlacement
        try:
            obj.BasePlacement=App.Placement(App.Vector(20,-10,0),App.Rotation(App.Vector(0,0,1),31))
            self.stage.refresh();start=App.Vector(self.scene['mirror'].get_object().Placement.Base)
            self.stage.set_travel(3)
            delta=obj.Placement.Rotation.multVec(App.Vector(3,0,0))
            self.assertLess((self.scene['mirror'].get_object().Placement.Base-start-delta).Length,1e-7)
        finally:
            obj.BasePlacement=original;self.stage.set_travel(0)

    def test_04_generic_baseplate_does_not_receive_payload_holes(self):
        p=self.root.add(Component('Ordinary plate',Baseplate((300,200,20),optical_height=0,grid_offset=(-100,-100))), (0,0,0),0)
        try:
            p.recompute();shape=p.get_object().Shape
            for operation in attachments.plate_attachments(self.root.get_object(),p.get_object()):
                center=App.Vector(*operation[1]['center_mm'])+App.Vector(0,0,-2)
                self.assertFalse(shape.isInside(center,1e-7,False))
            upper=next(h for h in json.loads(self.adapter.get_object().MachiningPlan)['holes'] if h['kind']=='tapped')
            point=self.adapter.get_object().Placement.multVec(App.Vector(*upper['center_mm']))
            point.z=-2
            self.assertTrue(shape.isInside(point,1e-7,False))
        finally:self.doc.removeObject(p.object_id)

    def test_05_full_stroke_clearance_includes_middle(self):
        # A swept box reserves the middle, even when neither endpoint body
        # overlaps this small obstruction above the carriage.
        boxes=list(self.stage.motion_envelopes(self.root.get_object()))
        self.assertGreater(len(boxes),2)
        mirror=self.scene['mirror'].get_object()
        box=next(box for _,box in boxes if box.BoundBox.ZMax>mirror.Placement.Base.z+2)
        self.assertTrue(box.isValid())
        obstacle=self.doc.addObject('Part::Feature','Obstruction')
        obstacle.addProperty('App::PropertyLinkList','Children');obstacle.Children=[]
        obstacle.Shape=Part.makeBox(1,1,1,mirror.Placement.Base+App.Vector(-.5,-.5,-.5))
        self.root.get_object().Children += [obstacle]
        try:
            with self.assertRaisesRegex(ValueError,'Full-travel'):stages.validate_clearance(self.stage,self.root)
        finally:self.doc.removeObject(obstacle.Name)
        stages.validate_clearance(self.stage,self.root)

    def test_06_reject_incompatible_adapters_and_ambiguous_mounts(self):
        bad=[replace(self.spec,width_mm=50),replace(self.spec,platform_holes=('missing','payload_1'))]
        for spec in bad:
            from dataclasses import asdict
            obj=self.adapter.get_object();original=obj.AdapterSpec
            try:
                obj.AdapterSpec=json.dumps(asdict(spec))
                with self.assertRaises(ValueError):self.adapter.machine()
            finally:obj.AdapterSpec=original
        group=Layout('Ambiguous assembly')
        for i in range(2):group.add(lab_catalog.create('mirror','Ambiguous mirror'),(i*30,0,0),0)
        with self.assertRaisesRegex(ValueError,'ambiguous'):self.stage.mount_payload(group,adapter=self.spec)
        for changes in (dict(thickness_mm=8),dict(screw_length_mm=30),dict(platform_holes=('payload_1','payload_1'))):
            with self.assertRaises(ValueError):replace(self.spec,**changes)

    def test_07_target_resolution(self):
        doc=object();a=SimpleNamespace(Name='a',Document=doc,Parent=None)
        b=SimpleNamespace(Name='b',Document=doc,Parent=a)
        target=SimpleNamespace(Name='adapter',Document=doc)
        self.assertIsNone(attachments.receiving_part(b))
        a.AttachmentTarget=target
        self.assertIs(attachments.receiving_part(b),target)
        b.AttachmentTarget=SimpleNamespace(Name='other',Document=doc)
        self.assertEqual(attachments.receiving_part(b).Name,'other')
        b.AttachmentTarget=None; a.Parent=b; a.AttachmentTarget=None
        with self.assertRaisesRegex(ValueError,'Cyclic'):attachments.receiving_part(b)

    def test_08_export_counts(self):
        path=self.scene['output']; report=json.loads(path.with_suffix('.drilling.json').read_text())
        self.assertEqual(sorted(len(v['holes']) for v in report['receivers'].values()),[4,7])
        bom=json.loads(path.with_suffix('.bom.json').read_text())
        self.assertEqual(sum(r['quantity'] for r in bom if r['part_number']=='XR25C'),1)
        self.assertEqual(sum(r['quantity'] for r in bom if r['part_number']=='XR25C-PAYLOAD-ADAPTER'),1)
        self.assertTrue(path.with_name(path.stem+'_baseplate.step').exists())

    def test_09_generic_definition_and_nested_frame(self):
        from PyOpticL.component_contract import ComponentContract,Frame
        from PyOpticL.stage_contract import LinearStageSpec
        doc=App.newDocument('GenericStage')
        try:
            root=Layout('Generic root')
            group=root.add(Layout('Rotated group'),(17,-11,0),90)
            spec=LinearStageSpec(Frame('mounting_face'),Frame('payload',(0,0,15)),(0,1,0),(-3,7),1)
            contract=ComponentContract('generic-stage','1','Lab','TEST-STAGE','fabricated',
                frames=(Frame('mounting_face'),Frame('optical',(0,0,15))))
            definition=stages.StageDefinition(spec,Part.makeBox(20,20,10),
                Part.makeBox(10,10,5,App.Vector(0,0,10)),contract,
                dict(seat_frame='mounting_face',screws=[],dowels=[],source='test'),
                ComponentContract('platform','1','Lab','','fabricated',frames=(Frame('payload',(0,0,15)),)))
            stage=group.add(stages.LinearStage('Generic stage',definition=definition),(3,2,0),0)
            root.recompute();before=App.Vector(stage.get_object().Payload.Placement.Base)
            stage.set_travel(4)
            self.assertLess((stage.get_object().Payload.Placement.Base-before-App.Vector(-3,0,0)).Length,1e-7)
            with self.assertRaises(ValueError):stage.mount_payload(stages.create(),adapter=self.spec)
        finally:
            App.closeDocument(doc.Name);App.setActiveDocument(self.doc.Name)

    def test_10_live_save_reopen_and_edit(self):
        import shutil
        copied=Path(self.directory.name)/'reopened.FCStd'
        shutil.copyfile(self.scene['output'],copied)
        original_name=self.doc.Name
        doc=App.openDocument(str(copied))
        try:
            self.assertTrue(all(o.Proxy is not None for o in doc.Objects))
            stage=next(o.Proxy for o in doc.Objects if isinstance(o.Proxy,stages.LinearStage))
            stage.set_travel(5)
            beam=next(o for o in doc.Objects if o.Label=='Stage beam')
            self.assertEqual(len(beam.BeamSegments),2)
            self.assertAlmostEqual(beam.BeamSegments[0].Proxy.distance,105,places=5)
            doc.recompute()
            stage.set_travel(0)
        finally:
            App.closeDocument(doc.Name);App.setActiveDocument(original_name)


class AccessEnvelopeTests(unittest.TestCase):
    def test_travel_notification_waits_for_remaining_restore_properties(self):
        stage=object.__new__(stages.LinearStage)
        stage._updating=False
        partially_restored=SimpleNamespace(Travel=SimpleNamespace(Value=0))
        stage.onChanged(partially_restored,'Travel')
        stage.execute(partially_restored)

    def test_cross_document_attachment_is_rejected_before_mutation(self):
        first=App.newDocument('AttachmentA')
        proxy=Layout('Stage placeholder')
        stage=object.__new__(stages.LinearStage)
        stage.document_id,stage.object_id=first.Name,proxy.object_id
        second=App.newDocument('AttachmentB')
        payload=Layout('Other payload')
        try:
            adapter=stages.AdapterSpec(16,100,70,('a','b'),15.875)
            with self.assertRaisesRegex(ValueError,'same document'):
                stage.mount_payload(payload,adapter=adapter)
            self.assertEqual(len(first.Objects),1)
            self.assertIsNone(payload.get_object().Parent)
        finally:
            App.closeDocument(second.Name);App.closeDocument(first.Name)

    def test_access_allowances_transform_with_the_mount(self):
        body=Part.makeBox(20,10,5,App.Vector(-10,-5,0))
        access=attachments.access_envelope(body,dict(recess_clearance_mm=5))
        b=access.optimalBoundingBox(False)
        self.assertAlmostEqual(b.XLength,30)
        self.assertAlmostEqual(b.YLength,20)
        access.rotate(App.Vector(),App.Vector(0,0,1),45)
        b=access.optimalBoundingBox(False)
        self.assertAlmostEqual(b.XLength,50/2**.5)

    def test_one_sided_and_remote_reliefs_are_included(self):
        body=Part.makeBox(20,10,5)
        access=attachments.access_envelope(body,dict(recess_side_scale_xy={'y_plus':1.5}))
        b=access.optimalBoundingBox(False)
        self.assertAlmostEqual(b.YMin,-.25)
        self.assertAlmostEqual(b.YLength,15.75)
        access=attachments.access_envelope(body,dict(clearance_pockets=[
            dict(size_mm=[2,2,2],origin_mm=[100,100,-1])]))
        b=access.optimalBoundingBox(False)
        self.assertAlmostEqual(b.XMax,102)
        self.assertAlmostEqual(b.ZMin,-1)



class BodyRecessTests(unittest.TestCase):
    def test_remote_handle_does_not_clear_stock_below_neighbor(self):
        from PyOpticL.component_contract import ComponentContract,Frame
        definition=SimpleNamespace(
            baseplate_profile=lambda:dict(recess_by_solid=True,seat_frame='mounting_face'),
            contract=lambda:ComponentContract('test','1','Lab','','fabricated',frames=(Frame('mounting_face'),)))
        body=Part.makeBox(40,40,10,App.Vector(-20,-20,0))
        handle=Part.makeBox(60,10,5,App.Vector(20,-5,5))
        obj=SimpleNamespace(Proxy=definition,Shape=Part.makeCompound([body,handle]),
                            Name='Stage',Label='Stage',Parent=SimpleNamespace(Label='Root'))
        pose=App.Placement(App.Vector(11,-3,-20),App.Rotation(App.Vector(0,0,1),27))
        pockets=list(attachments.body_recesses(obj,pose))
        self.assertEqual(len(pockets),2)
        empty_corner=pose.multVec(App.Vector(60,18,10))
        occupied_handle=pose.multVec(App.Vector(60,0,10))
        self.assertFalse(any(pocket.isInside(empty_corner,1e-7,False) for _,pocket in pockets))
        self.assertTrue(any(pocket.isInside(occupied_handle,1e-7,False) for _,pocket in pockets))


class IntegralPayloadTests(unittest.TestCase):
    def test_roof_support_and_clamp_bore_belong_only_to_moving_adapter(self):
        from PyOpticL import machined_baseplate
        doc=App.newDocument('IntegralStageRoof')
        try:
            root=Layout('Roof stage root')
            stage=root.add(stages.create(),(0,0,-39),27)
            roof=lab_catalog.create('roof','Moving horizontal roof',orientation='horizontal',beam_separation=9)
            adapter=stage.mount_payload(roof,adapter=stages.AdapterSpec(
                16,100,70,('payload_1','payload_2','payload_7','payload_8'),15.875))
            plate,machining=machined_baseplate.add(root,position=(0,0,3),thickness=60)
            root.recompute()
            plan=json.loads(adapter.get_object().MachiningPlan)
            self.assertEqual(len(plan['holes']),5)
            clamp=next(h for h in plan['holes'] if h.get('integrated'))
            self.assertEqual(clamp['thread'],'M2 x 0.4')
            self.assertEqual(len(plan['integrated_holders']),1)
            self.assertEqual(len(machining.plan['holes']),4)
            self.assertEqual(machining.plan['integrated_holders'],[])
            self.assertEqual(len(adapter.get_object().Shape.Solids),1)
            self.assertTrue(adapter.get_object().Shape.isValid())
            p=App.Vector(*clamp['center_mm'])+App.Vector(0,0,-1)
            local=adapter.get_object().Shape.copy();local.Placement=App.Placement()
            self.assertFalse(local.isInside(p,1e-7,False))
            rows=lab_catalog.bom(stage)
            integrated=next(r for r in rows if r.get('separate_part') is False)
            self.assertEqual(integrated['integrated_into'],adapter.get_object().Label)
            initial=App.Vector(roof.get_object().Placement.Base)
            for value in (-12.5,12.5,0):
                stage.set_travel(value)
                self.assertEqual(adapter.get_object().MachiningPlan,json.dumps(plan,indent=2))
                delta=stage.get_object().Placement.Rotation.multVec(App.Vector(value,0,0))
                self.assertLess((roof.get_object().Placement.Base-initial-delta).Length,1e-6)
            stages.validate_clearance(stage,root)
        finally:App.closeDocument(doc.Name)

if __name__=='__main__':unittest.main(verbosity=2)
