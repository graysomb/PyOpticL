"""Verify a rebuilt folded CPA live document, including motion after reopening.

Run examples/chirped_pulse_amplification_folded.py first. An alternate live FCStd
path may be supplied on the command line. This exercises the delivered CAD.
"""
from pathlib import Path
import json
import sys
from unittest.mock import patch
import FreeCAD as App
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PyOpticL import attachments,stages
from PyOpticL.beam_path import BeamSegment
from examples.chirped_pulse_amplification import center_ray_shape


def machining_values(value):
    """Ignore sub-nanometer quaternion/coordinate roundoff on CAD reopening."""
    if isinstance(value,float):return round(value,9) or 0.
    if isinstance(value,list):return [machining_values(v) for v in value]
    if isinstance(value,dict):return {k:machining_values(v) for k,v in value.items()}
    return value


def verify(path):
    path=Path(path).resolve()
    with patch.object(BeamSegment,'compute_shape',center_ray_shape):
        doc=App.openDocument(str(path))
        try:
            assert all(hasattr(o.Proxy,'recompute_priority') for o in doc.Objects), 'Incomplete restored proxy state'
            stage=next(o.Proxy for o in doc.Objects if isinstance(o.Proxy,stages.LinearStage))
            root=stage.get_object()
            while root.Parent is not None:root=root.Parent
            roof=next(o for o in doc.Objects if o.Label=='CP_HRoof')
            plate=next(o for o in doc.Objects if o.Label=='Machined baseplate')
            adapter=next(o for o in doc.Objects if isinstance(o.Proxy,stages.AdapterPlate))
            beam=next(o for o in doc.Objects if hasattr(o,'BeamSegments') and o.Parent==stage.get_object().Parent)
            fixed=stage.get_object().Children[0]
            fixed_pose=fixed.Placement.toMatrix().A
            roof_pose=App.Vector(roof.Placement.Base)
            base_plan=plate.MachiningPlan
            adapter_plan=adapter.MachiningPlan
            machining=json.loads(base_plan);payload=json.loads(adapter_plan)
            assert machining['thickness_mm']==60
            assert len([h for h in machining['holes'] if h.get('part')=='XR25C'])==4
            assert len(payload['holes'])==5
            assert len([h for h in payload['holes'] if h.get('integrated')])==1
            assert not set(payload['integrated_holders']) & set(machining['integrated_holders'])
            assert len(adapter.Shape.Solids)==1 and adapter.Shape.isValid()
            original_segments=len(beam.BeamSegments)
            original_length=sum(s.Proxy.distance for s in beam.BeamSegments)
            base_volume=plate.Shape.Volume
            adapter_volume=adapter.Shape.Volume
            def owner(obj):
                while obj is not None:
                    if obj.Label in ('CP_G1','SHG_Crystal'):return obj.Label
                    obj=getattr(obj,'Parent',None)
            measurements=[]
            for travel in (-12.5,0,12.5,0):
                stage.set_travel(travel)
                assert len(beam.BeamSegments)==original_segments
                length=sum(s.Proxy.distance for s in beam.BeamSegments)
                # The roof is visited twice; each visit changes two external
                # legs. Positive stage travel is toward the compressor grating.
                assert abs(length-original_length+4*travel)<1e-5,(travel,length,original_length)
                hits=[s.Proxy.get_global_position()+s.Proxy.distance*s.Proxy.get_global_direction()
                      for s in beam.BeamSegments if owner(s.EndObject)=='CP_G1' and not s.InternalToComponent]
                assert len(hits)==4,len(hits)
                assert max(abs(p[2]-z) for p,z in zip(hits,(15.525,15.525,9.875,9.875)))<1e-6
                delta=stage.get_object().Placement.Rotation.multVec(App.Vector(travel,0,0))
                assert (roof.Placement.Base-roof_pose-delta).Length<1e-6
                assert fixed.Placement.toMatrix().A==fixed_pose
                if machining_values(json.loads(plate.MachiningPlan))!=machining_values(json.loads(base_plan)):
                    Path('/tmp/cpa-stage-plan-before.json').write_text(json.dumps(json.loads(base_plan),indent=2))
                    Path('/tmp/cpa-stage-plan-after.json').write_text(json.dumps(json.loads(plate.MachiningPlan),indent=2))
                    raise AssertionError('Baseplate plan changed; comparison saved in /tmp/cpa-stage-plan-*.json')
                assert machining_values(json.loads(adapter.MachiningPlan))==machining_values(json.loads(adapter_plan))
                assert abs(plate.Shape.Volume-base_volume)<1e-4
                assert abs(adapter.Shape.Volume-adapter_volume)<1e-5
                measurements.append(dict(travel_mm=travel,compressor_path_mm=length,grating_heights_mm=[p[2] for p in hits]))
                print('Verified reopened stage travel:',travel,flush=True)
            supported_seats=[]
            for part_number in ('XR25C','818-BB-30-BRACKET'):
                operation=next(h for h in json.loads(plate.MachiningPlan)['holes'] if h.get('part')==part_number)
                mount=doc.getObject(operation['mount_object'])
                seat_z=plate.Placement.multVec(App.Vector(*operation['center_mm'])).z
                contact=supported=0.
                for face in mount.Shape.Faces:
                    b=face.optimalBoundingBox(False)
                    if b.ZLength<1e-6 and abs(b.ZMin-seat_z)<1e-5 and face.normalAt(0,0).z<-.99:
                        contact_patch=face.extrude(App.Vector(0,0,-.1))
                        contact+=contact_patch.Volume;supported+=contact_patch.common(plate.Shape).Volume
                assert contact>0 and supported/contact>.999,(part_number,contact,supported)
                supported_seats.append(dict(part=part_number,supported_fraction=supported/contact))
            clearance=stages.validate_clearance(stage,root.Proxy)
            for obj in attachments.descendants(root):
                if hasattr(obj,'Shape') and not obj.Shape.isNull():assert obj.Shape.isValid(),obj.Label
            result=dict(status='verified',native_motion=measurements,clearance=clearance,
                        fixed_base_and_manufacturing_invariant=True,adapter_holes=5,stage_base_holes=4,
                        supported_seats=supported_seats)
            return result
        finally:App.closeDocument(doc.Name)


if __name__=='__main__':
    path=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[2]/'artifacts/chirped_pulse_amplification_folded_live.FCStd'
    result=verify(path)
    path.with_name(path.stem+'_validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Folded CPA stage delivery verified.',flush=True)
