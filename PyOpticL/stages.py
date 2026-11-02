"""Receiver-owned machining and an editable, rigid-carriage XR25C stage.

Only manufactured adapters are drilled. Purchased parts retain their source CAD.
Coordinates in an adapter report are local to its bottom face (top = thickness).
"""
from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import FreeCAD as App
import Part
from . import attachments, lab_catalog
from .component_contract import ComponentContract, Frame, Hole, DOF, Provenance
from .layout import Layout
from .stage_contract import LinearStageSpec
from .vendor_cad import resolve

DATA = Path(__file__).with_name('catalog_data')


def reference():
    return json.loads((DATA/'xr25c_stage_reference.json').read_text())


@lru_cache(maxsize=1)
def _source():
    r = reference()
    for kind in ('step','pdf'):
        asset = json.loads((DATA/'assets'/f'XR25C.{kind}.json').read_text())
        if asset['sha256'] != r['step_sha256' if kind=='step' else 'drawing_sha256']:
            raise ValueError('XR25C source changed; reverify stage datums and body classification')
        resolve(asset)
    shape = lab_catalog.VendorPart('XR25C').shape()
    if len(shape.Solids) != len(r['solids']):
        raise ValueError('XR25C solid count changed')
    for solid, row in zip(shape.Solids,r['solids']):
        b = solid.optimalBoundingBox(False)
        actual = [b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]
        if (abs(solid.Volume-row['volume_mm3']) > .01 or
                max(abs(a-b) for a,b in zip(actual,row['bounds_mm'])) > .01):
            raise ValueError('XR25C body fingerprint changed')
    # Four open slot ends and their counterbores must exist in the base solid.
    cylinders = [f.Surface for f in shape.Solids[0].Faces if isinstance(f.Surface,Part.Cylinder)]
    for slot in r['mounting_slots']:
        p = App.Vector(*slot['center_mm'])
        for radius in (slot['radius_mm'], 6.731):
            if not any(abs(c.Radius-radius)<.01 and abs(c.Axis.z)>.999
                       and (c.Center-p).cross(App.Vector(0,0,1)).Length<.01 for c in cylinders):
                raise ValueError('XR25C mounting slot differs from verified source')
    return shape


@dataclass(frozen=True)
class AdapterSpec:
    thickness_mm: float
    width_mm: float
    depth_mm: float
    platform_holes: tuple
    screw_length_mm: float
    counterbore_depth_mm: float = 6.5
    clearance_diameter_mm: float = 6.8
    counterbore_diameter_mm: float = 10.5
    edge_margin_mm: float = 3.

    def __post_init__(self):
        for name in ('thickness_mm','width_mm','depth_mm','screw_length_mm',
                     'counterbore_depth_mm','clearance_diameter_mm','counterbore_diameter_mm','edge_margin_mm'):
            if not math.isfinite(getattr(self,name)) or getattr(self,name)<=0:
                raise ValueError('Adapter dimensions must be positive and finite')
        if (not all(isinstance(name,str) for name in self.platform_holes)
                or len(self.platform_holes)<2 or len(set(self.platform_holes))!=len(self.platform_holes)
                or self.counterbore_depth_mm<6.35 or self.counterbore_depth_mm>=self.thickness_mm
                or self.clearance_diameter_mm<6.35 or self.counterbore_diameter_mm<9.525
                or self.counterbore_diameter_mm<=self.clearance_diameter_mm):
            raise ValueError('Adapter needs distinct platform holes and accessible 1/4-20 cap-screw counterbores')
        engagement=self.screw_length_mm-(self.thickness_mm-self.counterbore_depth_mm)
        if not 6.35<=engagement<=7.1:
            raise ValueError('Platform screw engagement must be 6.35–7.1 mm (7.6 mm available, 0.5 mm tip allowance)')


class StagePart(Layout):
    """Importable proxy: CAD shapes and contracts persist in document properties."""
    object_group='hardware'
    object_color=(.6,.65,.7)
    apply_drilling=False

    def __init__(self,label,shape,contract,profile=None,moving=False):
        super().__init__(label)
        self.stage_moving=moving
        obj=self.get_object();obj.Shape=shape
        self.make_property('ComponentContract','App::PropertyString',visible=True)
        obj.ComponentContract=json.dumps(contract.to_dict())
        self.make_property('MountingProfile','App::PropertyString',visible=True)
        obj.MountingProfile=json.dumps(profile)
        self.make_property('MachiningPlan','App::PropertyString',visible=True)
        self.part_numbers=[contract.part_number] if contract.procurement=='purchased' else []

    def contract(self):
        return ComponentContract.from_dict(json.loads(self.get_object().ComponentContract))

    def baseplate_profile(self):
        return json.loads(self.get_object().MountingProfile)

    def drill(self):
        return attachments.footprint(self)

    def onDocumentRestored(self,obj):
        self.document_id,self.object_id=obj.Document.Name,obj.Name


class AdapterPlate(StagePart):
    object_group='hardware'
    def machine(self):
        obj=self.get_object()
        parent=obj.Parent
        while parent is not None and not isinstance(parent.Proxy,LinearStage):
            parent=parent.Parent
        if parent is None:raise ValueError('Adapter must belong to a linear stage')
        stage=parent.Proxy
        spec=AdapterSpec(**json.loads(obj.AdapterSpec))
        t,w,d=spec.thickness_mm,spec.width_mm,spec.depth_mm
        blank=Part.makeBox(w,d,t,App.Vector(-w/2,-d/2,0))
        cuts=[];holes=[];pockets=[];reliefs=[];seats=[]
        # A support declared integral with its receiver is machined into this
        # adapter, rather than duplicated as a loose mount or baseplate feature.
        blank,integral_ops,integral_parts=attachments.fuse_integrated(blank,obj.Parent,obj,top_z=t)
        self.integrated_names=[part.Name for part in integral_parts]
        for op in integral_ops:
            x,y,_=op['center_mm']
            if min(w/2-abs(x),d/2-abs(y))<op['diameter_mm']/2+spec.edge_margin_mm:
                raise ValueError('Integral payload hole violates adapter edge margin')
            op.update(receiving_part=obj.Name,source_part=op['mount_object'])
            holes.append(op);cuts.append(attachments.bore(op))
        payload_contract=ComponentContract.from_dict(json.loads(stage.get_object().PayloadContract))
        platform={h.name:h for h in payload_contract.holes}
        frames={f.name:f for f in payload_contract.frames}
        frame=stage.spec.payload_frame
        payload_inverse=App.Placement(App.Vector(*frame.position),App.Rotation('XYZ',*frame.rotation)).inverse()
        for name in spec.platform_holes:
            if name not in platform:
                raise ValueError('Unknown existing XR25C platform hole: '+name)
            hole=platform[name];f=frames[hole.frame]
            point=payload_inverse.multVec(App.Vector(*f.position));x,y,z=point
            engagement=spec.screw_length_mm-t+spec.counterbore_depth_mm
            axis=payload_inverse.Rotation.multVec(App.Rotation('XYZ',*f.rotation).multVec(App.Vector(0,0,1)))
            if (hole.thread!='1/4-20 UNC' or hole.depth_mm is None or engagement>hole.depth_mm-.5
                    or abs(z)>.01 or abs(abs(axis.z)-1)>1e-7):
                raise ValueError('Adapter requires verified top-face 1/4-20 platform holes with sufficient thread depth')
            radius=spec.counterbore_diameter_mm/2
            if min(w/2-abs(x),d/2-abs(y))<radius+spec.edge_margin_mm:
                raise ValueError('Adapter platform counterbore violates edge margin')
            cut=Part.makeCylinder(spec.clearance_diameter_mm/2,t+.02,App.Vector(x,y,-.01))
            cut=cut.fuse(Part.makeCylinder(radius,spec.counterbore_depth_mm+.01,
                App.Vector(x,y,t-spec.counterbore_depth_mm)))
            holes.append(dict(kind='platform_clearance',interface=name,center_mm=[x,y,t],axis=[0,0,-1],
                diameter_mm=spec.clearance_diameter_mm,depth_mm=t,
                counterbore_diameter_mm=spec.counterbore_diameter_mm,
                counterbore_depth_mm=spec.counterbore_depth_mm,thread_in_stage='1/4-20 UNC',
                screw_length_mm=spec.screw_length_mm,
                engagement_mm=spec.screw_length_mm-t+spec.counterbore_depth_mm,
                receiving_part=obj.Name,source_part=payload_contract.part_number,source_frame=stage.spec.payload_frame.name))
            cuts.append(cut)
        for mount in attachments.descendants(obj.Parent):
            if not attachments.profile(mount.Proxy) or not attachments.belongs_to(mount,obj):continue
            placement=obj.Placement.inverse()*mount.Placement
            profile=attachments.profile(mount.Proxy)
            fs={f.name:f for f in mount.Proxy.contract().frames}
            seat=placement.multVec(App.Vector(*fs[profile['seat_frame']].position))
            if abs(seat.z-t)>.01 or (placement.Rotation.multVec(App.Vector(0,0,1))-App.Vector(0,0,1)).Length>1e-7:
                raise ValueError('Payload mount must sit upright on adapter top')
            local=mount.Shape.copy();local.Placement=placement
            # Actual planar seat contact, rather than whole adjuster envelope.
            contact=0.;supported=0.
            for face in local.Faces:
                b=face.optimalBoundingBox(False)
                if b.ZLength<1e-6 and abs(b.ZMin-t)<1e-5 and face.normalAt(0,0).z<-.99:
                    patch=face.extrude(App.Vector(0,0,-.1));contact+=patch.Volume
                    supported+=patch.common(blank).Volume
                    seats.append(patch)
            if contact<=0 or supported/contact<.999:
                raise ValueError('Payload mounting seat is not fully supported by adapter')
            for op in attachments.operations(mount.Proxy,placement):
                center=App.Vector(*op['center_mm']);rad=op['diameter_mm']/2
                if min(w/2-abs(center.x),d/2-abs(center.y))<rad+spec.edge_margin_mm:
                    raise ValueError('Payload hole violates adapter edge margin')
                if center.z-op['depth_mm']-attachments.tip_height(op['diameter_mm'])<.5:
                    raise ValueError('Payload drill tip breaks through adapter')
                cut=attachments.bore(op)
                op.update(receiving_part=obj.Name,source_part=mount.Name,mount=mount.Label,
                          mount_object=mount.Name,assembly=mount.Parent.Label)
                holes.append(op);cuts.append(cut)
            for record,pocket in attachments.clearance_pockets(mount.Proxy,placement):
                if pocket.optimalBoundingBox(False).ZMin<.5:
                    raise ValueError('Payload relief breaks through adapter')
                pockets.append(dict(record,receiving_part=obj.Name,source_part=mount.Name))
                reliefs.append(pocket)
                blank=blank.cut(pocket)
        for i,cut in enumerate(cuts):
            if any(cut.common(other).Volume>1e-6 for other in cuts[:i]):
                raise ValueError('Adapter machining operations intersect')
            if any(cut.common(relief).Volume>1e-6 for relief in reliefs):
                raise ValueError('Hardware relief intersects adapter attachment bore')
            blank=blank.cut(cut)
        for patch in seats:
            if patch.common(blank).Volume/patch.Volume<.999:
                raise ValueError('Adapter machining removes payload mounting support')
        if not blank.isValid() or len(blank.Solids)!=1:
            raise ValueError('Adapter must be one valid solid')
        # Top access must remain open above every platform counterbore.
        for h in holes:
            if h['kind']!='platform_clearance':continue
            x,y,_=h['center_mm']
            tool=Part.makeCylinder(spec.counterbore_diameter_mm/2,100,App.Vector(x,y,t+.01))
            tool.Placement=obj.Placement*tool.Placement
            for part in attachments.descendants(obj.Parent):
                if part==obj or not hasattr(part,'Shape') or part.Shape.isNull():continue
                if tool.common(part.Shape).Volume>1e-5:
                    raise ValueError('Payload blocks platform screw access')
        blank.Placement=obj.Placement
        obj.Shape=blank
        obj.MachiningPlan=json.dumps(dict(units='mm',receiving_part=obj.Name,
            coordinate_frame='adapter bottom; top at thickness_mm',thickness_mm=t,
            integrated_holders=self.integrated_names,
            stock_bounds=[-w/2,-d/2,w,d],holes=holes,pockets=pockets),indent=2)

    def recompute(self):
        super().recompute()
        obj=self.get_object()
        key=[obj.AdapterSpec]
        for part in attachments.descendants(obj.Parent):
            if (attachments.profile(part.Proxy) or attachments.integration_profile(part.Proxy)) and attachments.belongs_to(part,obj):
                local=obj.Placement.inverse()*part.Placement
                key.append((part.Name,tuple((round(v,8) or 0.) for v in local.toMatrix().A),
                            json.dumps(attachments.profile(part.Proxy) or attachments.integration_profile(part.Proxy),sort_keys=True)))
        key=repr(key)
        if key!=getattr(self,'_machining_key',None):
            self.machine()
            self._machining_key=key



@dataclass(frozen=True)
class StageDefinition:
    spec: LinearStageSpec
    fixed_shape: object
    moving_shape: object
    fixed_contract: ComponentContract
    baseplate_profile: dict
    payload_contract: ComponentContract


def xr25c_definition():
    r=reference()
    # Check pins even when the expensive imported geometry is cached.
    for kind,key in (('step','step_sha256'),('pdf','drawing_sha256')):
        asset=json.loads((DATA/'assets'/f'XR25C.{kind}.json').read_text())
        if asset['sha256']!=r[key]:raise ValueError('XR25C source changed; reverify stage')
        resolve(asset)
    source=_source(); moving=set(r['moving_solids'])
    fixed_shape=Part.makeCompound([s for i,s in enumerate(source.Solids) if i not in moving])
    moving_shape=Part.makeCompound([s for i,s in enumerate(source.Solids) if i in moving])
    frames=[Frame('origin'),Frame('mounting_face'),Frame('payload',(0,0,23))]
    frames.extend(Frame(s['name'],s['center_mm']) for s in r['mounting_slots'])
    contract=ComponentContract('xr25c-fixed','1','Thorlabs','XR25C','purchased',frames=tuple(frames),
        holes=tuple(Hole(s['name'],s['name'],6.731,thread=None) for s in r['mounting_slots']),
        provenance=(Provenance('XR25C drawing E and pinned STEP','cad_verified',r['step_sha256'],r['reference_note']),))
    profile=dict(seat_frame='mounting_face',recess_by_solid=True,screws=[s['name'] for s in r['mounting_slots']],dowels=[],
        screw=dict(thread='1/4-20 UNC',diameter_mm=5.1054,depth_mm=12.,thread_depth_mm=10.),
        step_sha256=r['step_sha256'],drawing_sha256=r['drawing_sha256'],
        source='XR25C E four open slot ends; selected 1/4-20 x 5/8 in screws and 1.6 mm washers',
        mounting_hardware=dict(screw_length_mm=15.875,washer_thickness_mm=1.6,slot_head_seat_mm=5.715,
                               washer_inner_diameter_mm=6.8,washer_outer_diameter_mm=12.7,
                               plate_engagement_mm=15.875-5.715-1.6))
    spec=LinearStageSpec(Frame('mounting_face'),Frame('payload',(0,0,23)),(1,0,0),r['limits_mm'])
    return StageDefinition(spec,fixed_shape,moving_shape,contract,profile,lab_catalog.VendorPart('XR25C').contract())


class LinearStage(Layout):
    """One moving payload coordinate system; no stage stacking in v1."""
    object_group='layout'

    def __init__(self,label='XR25C stage',travel_limits=None,*,definition=None):
        definition=definition or xr25c_definition()
        spec=definition.spec
        limits=tuple(spec.limits_mm if travel_limits is None else travel_limits)
        if len(limits)!=2 or limits[0]<spec.limits_mm[0] or limits[1]>spec.limits_mm[1]:
            raise ValueError('Configured travel exceeds verified stage stroke')
        LinearStageSpec(spec.mounting_frame,spec.payload_frame,spec.axis,limits,spec.reference_mm)
        super().__init__(label)
        self._updating=True
        self.make_property('Travel','App::PropertyDistance',visible=True,editable=True)
        self.make_property('TravelLimits','App::PropertyFloatList',visible=True)
        self.make_property('StageSpecification','App::PropertyString',visible=True)
        self.make_property('PayloadContract','App::PropertyString',visible=True)
        self.make_property('MotionError','App::PropertyString',visible=True)
        self.make_property('Payload','App::PropertyLinkHidden')
        from dataclasses import asdict
        obj=self.get_object();obj.StageSpecification=json.dumps(asdict(spec))
        obj.PayloadContract=json.dumps(definition.payload_contract.to_dict())
        obj.TravelLimits=list(limits);obj.Travel=spec.reference_mm
        self.add(StagePart(label+' fixed base',definition.fixed_shape,definition.fixed_contract,
                           definition.baseplate_profile),(0,0,0),0)
        self.add(StagePart(label+' carriage',definition.moving_shape,
            ComponentContract('stage-carriage','1','','','assembly'),moving=True),(0,0,0),0)
        payload=self.add(Layout(label+' payload'),spec.payload_frame.position,spec.payload_frame.rotation)
        obj.Payload=payload.get_object()
        self._last_travel=spec.reference_mm;self._updating=False
        self.recompute()

    @property
    def spec(self):
        obj=self.get_object();data=json.loads(obj.StageSpecification)
        limits=tuple(obj.TravelLimits)
        if len(limits)!=2 or limits[0]<data['limits_mm'][0] or limits[1]>data['limits_mm'][1]:
            raise ValueError('Configured travel exceeds verified stage stroke')
        return LinearStageSpec(Frame(**data['mounting_frame']),Frame(**data['payload_frame']),
                               data['axis'],limits,data['reference_mm'])

    def contract(self):
        fixed=self.get_object().Children[0].Proxy.contract()
        return ComponentContract('translation','1',fixed.manufacturer,fixed.part_number,'assembly',
            frames=(Frame('origin'),Frame('stage'),self.spec.payload_frame),
            dofs=(DOF('translation','translation','stage',self.spec.axis,'payload',
                      'Declared linear stage definition',self.spec.limits_mm),))

    def mount_payload(self,component,*,adapter,mounting_component=None,offset=(0,0),yaw=0):
        if not isinstance(adapter,AdapterSpec):raise ValueError('An explicit AdapterSpec is required')
        root=component.get_object()
        if root.Document != self.get_object().Document:
            raise ValueError('Stage and payload must belong to the same document')
        if root.Parent is not None:raise ValueError('Payload component already has a parent')
        candidates=[o for o in [root,*attachments.descendants(root)] if attachments.profile(o.Proxy) or attachments.integration_profile(o.Proxy)]
        if any(isinstance(o.Proxy,LinearStage) for o in [root,*attachments.descendants(root)]):
            raise ValueError('Stacked stages are not supported')
        if mounting_component is None:
            if len(candidates)!=1:raise ValueError('Choose mounting_component explicitly: ambiguous or missing payload mount')
            mount=candidates[0]
        else:
            mount=mounting_component.get_object() if hasattr(mounting_component,'get_object') else mounting_component
            if mount not in candidates:raise ValueError('Mounting component must belong to payload and have a drilling profile')
        if self.get_object().Payload.Children:
            raise ValueError('One adapter per stage in v1; assemble multiple mounts into one payload')
        if len(offset)!=2 or not all(math.isfinite(v) for v in (*offset,yaw)):
            raise ValueError('Payload offset and yaw must be finite')
        component.recompute()
        profile=attachments.profile(mount.Proxy) or attachments.integration_profile(mount.Proxy);frames={f.name:f for f in mount.Proxy.contract().frames}
        seat=(root.Placement.inverse()*mount.Placement).multVec(App.Vector(*frames[profile['seat_frame']].position))
        payload=self.get_object().Payload.Proxy
        group=payload.add(Layout(root.Label+' attachment'),(0,0,0),0)
        plate=AdapterPlate(root.Label+' adapter',Part.makeBox(adapter.width_mm,adapter.depth_mm,adapter.thickness_mm),
            ComponentContract('stage-adapter','1','Lab',
                (self.get_object().Children[0].Proxy.contract().part_number or 'STAGE')+'-PAYLOAD-ADAPTER','fabricated'))
        plate.make_property('AdapterSpec','App::PropertyString',visible=True)
        from dataclasses import asdict
        plate.get_object().AdapterSpec=json.dumps(asdict(adapter))
        group.add(plate,(0,0,0),0)
        rotation=App.Rotation(App.Vector(0,0,1),yaw)
        position=App.Vector(offset[0],offset[1],adapter.thickness_mm)-rotation.multVec(seat)
        group.add(component,tuple(position),yaw)
        attachments.set_target(component,plate)
        # Machine after the payload's shapes and placements have recomputed.
        plate.recompute_priority=-1
        try:self.recompute()
        except Exception:
            # Failed attachments are removed, leaving the caller's component reusable.
            group.get_object().Children=[o for o in group.get_object().Children if o!=root]
            root.Parent=None
            doc=root.Document; payload.get_object().Children=[o for o in payload.get_object().Children if o!=group.get_object()]
            doc.removeObject(plate.object_id);doc.removeObject(group.object_id)
            root.AttachmentTarget=None
            raise
        return plate

    def set_travel(self,value):
        value=self.spec.validate_travel(value)
        # Invoke refresh directly so Python callers receive recompute failures;
        # FreeCAD property callbacks otherwise report them only to its console.
        previous=self._updating
        self._updating=True
        try:self.get_object().Travel=value
        finally:self._updating=previous
        self.refresh()

    def recompute(self):
        obj=self.get_object();value=self.spec.validate_travel(obj.Travel.Value)
        self.compute_placement()
        # The fixed base remains at the stage origin. Only the carriage and
        # payload roots receive the translation, exactly once.
        children=obj.Children
        children[1].BasePlacement=App.Placement(
            App.Vector(*self.spec.axis)*(value-self.spec.reference_mm),App.Rotation())
        frame=self.spec.payload_at(value)
        obj.Payload.BasePlacement=App.Placement(App.Vector(*frame.position),App.Rotation('XYZ',*frame.rotation))
        super().recompute()
        self._last_travel=value

    def refresh(self):
        if getattr(self,'_updating',False):return
        self._updating=True
        try:
            root=self.get_object()
            while root.Parent is not None:root=root.Parent
            for child in attachments.descendants(root):
                if hasattr(child.Proxy,'invalidate_trace'):
                    child.Proxy.invalidate_trace()
            root.Proxy.recompute()
            self.get_object().MotionError=''
        finally:self._updating=False

    def _properties_restored(self,obj):
        # GUI restore can notify Travel before the remaining XML properties
        # and links exist. onDocumentRestored binds the completed assembly.
        return (all(hasattr(obj,name) for name in ('Travel','TravelLimits','StageSpecification','Payload'))
                and obj.Payload is not None)

    def onChanged(self,obj,name):
        if name!='Travel' or getattr(self,'_updating',True) or not self._properties_restored(obj):return
        try:self.spec.validate_travel(obj.Travel.Value)
        except ValueError as e:
            self._updating=True;obj.Travel=self._last_travel;self._updating=False
            obj.MotionError=str(e);return
        try:self.refresh()
        except Exception as error:
            obj.MotionError=str(error)
            raise

    def execute(self,obj):
        if not getattr(self,'_updating',True) and self._properties_restored(obj):self.refresh()

    def onDocumentRestored(self,obj):
        self.document_id,self.object_id=obj.Document.Name,obj.Name
        self._updating=False;self._last_travel=obj.Travel.Value

    def motion_envelopes(self,relative_to):
        obj=self.get_object();inv=relative_to.Placement.inverse()
        # Each local AABB swept along a linear axis is conservative throughout
        # the interval; endpoint boxes alone would leave the middle unreserved.
        for part in [obj.Children[1],*attachments.descendants(obj.Payload)]:
            if getattr(part.Proxy,'object_group',None)=='beam_path':continue
            if not hasattr(part,'Shape') or part.Shape.isNull():continue
            local=part.Shape.copy();local.Placement=App.Placement()
            profile=attachments.profile(part.Proxy)
            pieces=local.Solids if getattr(part.Proxy,"stage_moving",False) else [local]
            for piece in pieces:
                access=attachments.access_envelope(piece,profile)
                access.Placement=obj.Placement.inverse()*part.Placement*access.Placement
                b=access.optimalBoundingBox(False)
                padding=0.
                start=self.spec.limits_mm[0]-obj.Travel.Value
                end=self.spec.limits_mm[1]-obj.Travel.Value
                delta0=App.Vector(*self.spec.axis)*start
                delta1=App.Vector(*self.spec.axis)*end
                lo=[v+min(a,c)-padding for v,a,c in zip((b.XMin,b.YMin,b.ZMin),delta0,delta1)]
                lengths=[v+abs(c-a)+2*padding for v,a,c in zip((b.XLength,b.YLength,b.ZLength),delta0,delta1)]
                box=Part.makeBox(*lengths,App.Vector(*lo))
                box.Placement=inv*obj.Placement*box.Placement
                yield obj,box


def create(part='XR25C',label='XR25C stage',**parameters):
    if part!='XR25C':raise ValueError('Only the verified XR25C is supported initially')
    return LinearStage(label,**parameters)


def validate_clearance(stage,root):
    """Reject external interceptions using conservative full-stroke volumes.

    Vendor rail/bearing contacts within the stage are intentional and excluded.
    This checks other assemblies and the already machined baseplate, not a
    simulation of the stage's internal contact mechanics.
    """
    stage_obj=stage.get_object();own={o.Name for o in [stage_obj,*attachments.descendants(stage_obj)]}
    for _,envelope in stage.motion_envelopes(root.get_object()):
        envelope.Placement=root.get_object().Placement*envelope.Placement
        for obj in attachments.descendants(root.get_object()):
            if obj.Name in own or getattr(getattr(obj,'Proxy',None),'object_group',None)=='beam_path':continue
            if not hasattr(obj,'Shape') or obj.Shape.isNull():continue
            if not envelope.BoundBox.intersect(obj.Shape.BoundBox):continue
            if envelope.common(obj.Shape).Volume>1e-5:
                raise ValueError('Full-travel envelope intersects '+obj.Label)
    return dict(limits_mm=list(stage.spec.limits_mm),method='conservative per-body AABB linear sweeps',
                external_intersections=[],internal_contacts='Vendor reference; rail/bearing actuation not simulated')


def export(stage,baseplate,output,*,root):
    """Save editable CAD, separate manufactured parts, machining and BOM."""
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    stage.refresh()
    validation=validate_clearance(stage,root)
    validation['base_fasteners']=validate_base_fasteners(stage)
    base=baseplate.get_object()
    fixed=stage.get_object().Children[0].Proxy
    fixed_contract=fixed.contract()
    rows=[dict(part_number=fixed_contract.part_number,procurement=fixed_contract.procurement,quantity=1),
          dict(part_number='Machined baseplate',procurement='fabricated',quantity=1)]
    mounting=fixed.baseplate_profile() or {}
    if mounting.get('screws'):
        hardware=mounting.get('mounting_hardware',{})
        count=len(mounting['screws'])
        rows.append(dict(part_number=mounting.get('screw',{}).get('thread','M4 x 0.7')+' cap screw',
                         length_mm=hardware.get('screw_length_mm'),procurement='generic',quantity=count,
                         purpose='stage base',modeled=False))
        if hardware.get('washer_thickness_mm'):
            rows.append(dict(part_number='Stage base washer',thickness_mm=hardware['washer_thickness_mm'],
                             inner_diameter_mm=hardware.get('washer_inner_diameter_mm'),
                             outer_diameter_mm=hardware.get('washer_outer_diameter_mm'),
                             procurement='generic',quantity=count,modeled=False))
    reports={base.Name:json.loads(base.MachiningPlan)}
    solids=[]
    integrated={name for part in attachments.descendants(root.get_object())
                for name in getattr(part.Proxy,'integrated_names',())}
    for obj in attachments.descendants(root.get_object()):
        if obj.Name not in integrated and hasattr(obj,'Shape') and not obj.Shape.isNull():solids.append(obj.Shape)
        if isinstance(obj.Proxy,AdapterPlate):
            report=json.loads(obj.MachiningPlan);reports[obj.Name]=report
            obj.Shape.exportStep(str(output.with_name(output.stem+'_'+obj.Name+'.step')))
            spec=AdapterSpec(**json.loads(obj.AdapterSpec))
            rows.extend([dict(part_number=obj.Proxy.contract().part_number,procurement='fabricated',quantity=1,
                              dimensions_mm=[spec.width_mm,spec.depth_mm,spec.thickness_mm]),
                         dict(part_number='1/4-20 UNC cap screw',length_mm=spec.screw_length_mm,
                              procurement='generic',quantity=len(spec.platform_holes),purpose=obj.Name,modeled=False)])
            for child in obj.Parent.Children:
                if child==obj:continue
                rows.extend(lab_catalog.bom(child.Proxy))
            for op in report['holes']:
                if op['kind']=='dowel':rows.append(dict(part_number=op['pin'],procurement='generic',quantity=1,modeled=False))
                elif op['kind']=='tapped':rows.append(dict(part_number=op['thread']+' mounting screw',procurement='generic',quantity=1,modeled=False))
    base.Shape.exportStep(str(output.with_name(output.stem+'_baseplate.step')))
    Part.makeCompound(solids).exportStep(str(output.with_suffix('.step')))
    output.with_suffix('.drilling.json').write_text(json.dumps(dict(units='mm',receivers=reports),indent=2)+'\n')
    output.with_suffix('.bom.json').write_text(json.dumps(rows,indent=2)+'\n')
    output.with_suffix('.validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    root.document_id=stage.get_object().Document.Name
    stage.get_object().Document.recompute()
    stage.get_object().Document.saveAs(str(output))


def validate_base_fasteners(stage):
    """Continuous carriage clearance and endpoint installation access for XR25C.

    Sweep each fixed vertical bolt/head/washer oppositely through the travel
    interval. An XY capsule extruded in Z is the exact linear sweep of these
    cylinders, rather than a set of sampled carriage positions.
    """
    obj=stage.get_object()
    if obj.Children[0].Proxy.contract().part_number!='XR25C':
        return dict(status='Stage definition must supply its own base-fastener verification')
    r=reference()
    moving=obj.Children[1].Shape.copy();moving.Placement=App.Placement()
    fixed=obj.Children[0].Shape.copy();fixed.Placement=App.Placement()
    rows=[]
    for slot in r['mounting_slots']:
        x,y,_=slot['center_mm']
        # 1/4-20 x 5/8 in cap screw and 1.6 mm washer on the 5.715 mm seat.
        regions=((3.175,-8.56,15.875),(6.35,5.715,1.6),(4.7625,7.315,6.35))
        for radius,z,height in regions:
            low=x-stage.spec.limits_mm[1];high=x-stage.spec.limits_mm[0]
            capsule=Part.makeCylinder(radius,height,App.Vector(low,y,z)).fuse(
                Part.makeCylinder(radius,height,App.Vector(high,y,z)))
            capsule=capsule.fuse(Part.makeBox(high-low,2*radius,height,App.Vector(low,y-radius,z)))
            for solid in moving.Solids:
                if solid.BoundBox.intersect(capsule.BoundBox) and solid.common(capsule).Volume>1e-5:
                    raise ValueError('Carriage travel intersects base fastener '+slot['name'])
        assembly_travel=12.5 if x<0 else -12.5
        tool=Part.makeCylinder(2.5,70,App.Vector(x,y,13.665))
        shifted=moving.copy();shifted.translate(App.Vector(assembly_travel,0,0))
        for group in (fixed,shifted):
            for solid in group.Solids:
                if solid.BoundBox.intersect(tool.BoundBox) and solid.common(tool).Volume>1e-5:
                    raise ValueError('Base fastener hex access blocked at installation pose '+slot['name'])
        rows.append(dict(slot=slot['name'],plate_engagement_mm=8.56,hex_tool_radius_mm=2.5,
                         installation_travel_mm=assembly_travel,continuous_stroke_clearance=True))
    return dict(status='verified',fasteners=rows,
                note='Installation uses opposite hardware stroke endpoints before fitting the payload; fasteners are BOM items, not assembly solids.')
