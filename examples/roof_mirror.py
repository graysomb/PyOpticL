"""Both roof orientations, 12.7 mm input beams and integral baseplate supports.

Run with FreeCAD's Python. Returns a cache-independent static review and report;
the editable source remains open. All dimensions below are millimeters.
"""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import FreeCAD as App
import Part

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyOpticL import attachments, lab_catalog as catalog, machined_baseplate
from PyOpticL.beam_path import BeamPath, Stop
from PyOpticL.layout import Component, Layout
from PyOpticL.roof_mirror import reference, support_reference

INPUT_HEIGHT=12.7
SPACING=12.7
WAVELENGTH=1550.
WAIST=.2
POWER=.001
PLACEMENTS=[('horizontal',(0,0,INPUT_HEIGHT),0),
            ('vertical',(0,80,INPUT_HEIGHT),0)]
QUALIFICATIONS=[
    'Exact HRS1015-P01 three-solid vendor geometry; drawing TTN048987-E0W revision B. Nominal ideal 90 degree roof.',
    'Clear aperture is modeled as the centered 80% rectangle of each measured trimmed face. The drawing does not specify its exact boundary.',
    'Explicit air-path reflections; homogeneous index 1.0 for reported OPL. No substrate traversal, coating phase, dispersion, diffraction or coupling-efficiency claim.',
    'User-corrected integral supports and separate slotted clamps; no mounting bracket. Nominal aluminum parts: clamp force, manufactured fits and repeatability require physical validation.',
    'M2 x 0.4 screws have nominal cylindrical thread envelopes. Overlap is accepted only within the annotated tap-drill thread annuli; no helical thread or torque model.',
    'User blind holes are adapted to 1.6 mm M2 tap drills with 118 degree tips; clamp slots use 2.2 mm M2 clearance. No roof dowels, M4 attachments or recesses.',
]


class Receiver:
    def interfaces(self):
        return [Stop((0,0,0),(0,0,0),diameter=1)]


def _require(condition,message):
    if not condition:
        raise ValueError(message)


def _property(obj,name,value):
    obj.addProperty('App::PropertyString',name)
    setattr(obj,name,json.dumps(value,indent=2))
    obj.setEditorMode(name,1)


def _feature(doc,name,shape,color):
    obj=doc.addObject('Part::Feature',name)
    obj.Shape=shape.copy()
    _property(obj,'DisplayColor',color)
    if obj.ViewObject:obj.ViewObject.ShapeColor=color
    return obj


def _build_source(plate_thickness=30.):
    doc=App.newDocument('RoofMirrorSource')
    try:
        root=Layout('Two roof orientations')
        parts,beams={},{}
        for orientation,position,yaw in PLACEMENTS:
            part=root.add(catalog.create('roof',orientation+' roof',orientation=orientation,
                beam_separation=SPACING),position,yaw)
            part.compute_placement()
            p=part.get_object().Placement
            output=next(f for f in part.contract().frames if f.name=='output')
            source=p.multVec(App.Vector(-50,0,0))
            target=p.multVec(App.Vector(*output.position)+App.Vector(-50,0,0))
            root.add(Component(orientation+' receiver',Receiver()),tuple(target),yaw)
            beam=root.add(BeamPath(f'{orientation} {WAVELENGTH:g} nm beam',wavelength=WAVELENGTH,
                waist=WAIST,power=POWER,bound_parent=root),tuple(source),yaw)
            parts[orientation],beams[orientation]=part,beam
        plate,machining=machined_baseplate.add(root,thickness=plate_thickness,margin=20,pocket_clearance=.25)
        root.recompute();doc.recompute()
        return SimpleNamespace(document=doc,layout=root,parts=parts,beams=beams,
                               plate=plate,machining=machining)
    except Exception:
        App.closeDocument(doc.Name)
        raise


def _verify(scene):
    plate=scene.plate.get_object().Shape
    plan=scene.machining.plan
    _require(plate.isValid() and len(plate.Solids)==1,'Plate must be one valid solid')
    _require(len(plan['holes'])==2,'Expected one M2 clamp tap per roof')
    _require(plan['pockets']==[],'Integral supports do not need carrier recesses')
    _require(len(plan['integrated_holders'])==2,'Both support patches must be part of the plate')
    passes={}
    thread_overlaps=[]
    minimum_stock=[]
    for orientation,part in scene.parts.items():
        spec=support_reference(part.geometry)
        measured=scene.beams[orientation].measure_component_pass(part)
        p=part.get_object().Placement
        target=next(f for f in part.contract().frames if f.name=='output')
        expected=p.multVec(App.Vector(*target.position))
        _require((App.Vector(*measured['exit_mm'])-expected).Length<1e-7,'Incorrect roof displacement')
        _require(abs(measured['geometric_length_mm']-25.4)<1e-7,'Incorrect roof path length')
        _require(len(measured['reflection_points_mm'])==2,'Expected exactly two roof reflections')
        segments=scene.beams[orientation].get_object().BeamSegments
        _require(len(segments)==5,'Expected entrance, two reflections, exit and receiver')
        _require(abs(sum(s.Proxy.distance for s in segments)-125.4)<1e-7,'Incorrect complete path length')
        _require(all(segment.Shape.common(plate).Volume<1e-6 for segment in segments),
            'Beam envelope intersects an integral support or plate')
        objects=list(part.get_object().Children)
        support=next(o for o in objects if o.Proxy.contract().catalog_id=='roof-integral-support')
        seat=next(f for f in support.Proxy.contract().frames if f.name=='plate_top')
        pedestal=support.Placement.multVec(App.Vector(*seat.position)).z
        _require(support.Shape.cut(plate).Volume<1e-6,'Support material missing from unioned plate')
        for obj in objects:
            _require(obj.Shape.isValid(),'Invalid roof assembly solid')
            if obj is support:
                continue
            if obj.Label.startswith('M2 clamp screw'):
                engagement=spec['screw_length_mm']-spec['clamp_thickness_mm']
                bottom=obj.Placement.Base-App.Vector(0,0,spec['screw_length_mm'])
                allowed=Part.makeCylinder(1,engagement,bottom).cut(Part.makeCylinder(.8,engagement,bottom))
                overlap=obj.Shape.common(plate)
                _require(overlap.cut(allowed).Volume<1e-6,'M2 screw collides outside thread annulus')
                _require(engagement<=spec['usable_thread_mm'],'M2 screw exceeds usable thread')
                thread_overlaps.append(dict(part=orientation,thread='M2 x 0.4',volume_mm3=overlap.Volume,
                    nominal_engagement_mm=engagement))
            else:
                _require(obj.Shape.common(plate).Volume<1e-6,'Optic or removable clamp intersects plate')
        for i,a in enumerate(objects):
            for b in objects[i+1:]:
                if (a is support and b.Label.startswith('M2 clamp screw')
                        or b is support and a.Label.startswith('M2 clamp screw')):
                    continue  # The thread annulus was checked against the full plate.
                _require(a.Shape.common(b.Shape).Volume<1e-6,'Unintended component interference: '+a.Label+', '+b.Label)
        measured.update(native_input_height_mm=catalog.native_height(part),
            installed_input_height_mm=p.Base.z,installed_output_height_mm=expected.z,
            pedestal_height_mm=pedestal,baseplate_integration='direct_union',
            reference_stock_thickness_mm=12.7,
            complete_path_length_mm=sum(s.Proxy.distance for s in segments),
            complete_optical_path_length_mm=sum(s.Proxy.distance for s in segments))
        passes[orientation]=measured
    for op in plan['holes']:
        center=App.Vector(*op['center_mm'])
        _require(op['thread']=='M2 x 0.4' and op['diameter_mm']==1.6,'Unexpected roof hole contract')
        _require(not plate.isInside(center+App.Vector(0,0,-1),1e-7,False),'Missing physical M2 bore')
        remaining=plan['thickness_mm']+center.z-op['depth_mm']-attachments.tip_height(op['diameter_mm'])
        _require(remaining>=.5,'Insufficient stock below drill tip')
        minimum_stock.append(remaining)
    before=(len(scene.document.Objects),plate.Volume)
    scene.layout.recompute()
    _require(len(scene.document.Objects)==before[0] and abs(scene.plate.get_object().Shape.Volume-before[1])<1e-6,
        'Repeated recompute duplicated objects or changed plate')
    return dict(passes=passes,physical_bores_checked=2,plate_valid=True,recompute_stable=True,
        integrated_supports=2,minimum_stock_below_drill_tip_mm=min(minimum_stock),
        thread_envelope_overlaps=thread_overlaps)


def build(output=None,plate_thickness=30.):
    scene=_build_source(plate_thickness)
    checks=_verify(scene)
    plan=scene.machining.plan
    static=App.newDocument('RoofMirrorReview')
    physical=[]
    plate=_feature(static,'Baseplate',scene.plate.get_object().Shape,(.7,.72,.75))
    _property(plate,'MachiningPlan',plan)
    physical.append(plate)
    bom=[]
    for orientation,part in scene.parts.items():
        group=static.addObject('App::DocumentObjectGroup',orientation.capitalize())
        _property(group,'ComponentContract',part.contract().to_dict())
        rows=catalog.bom(part);bom.extend(rows)
        _property(group,'BOM',rows)
        for obj in part.get_object().Children:
            if obj.Shape.isNull() or attachments.integration_profile(obj.Proxy):continue
            target=_feature(static,orientation+'_'+obj.Name,obj.Shape,obj.Proxy.object_color)
            target.Label=orientation+' / '+obj.Label
            _property(target,'ComponentContract',obj.Proxy.contract().to_dict())
            group.addObject(target);physical.append(target)
    _property(plate,'IntegratedSupportContracts',[
        obj.Proxy.contract().to_dict() for part in scene.parts.values()
        for obj in part.get_object().Children if attachments.integration_profile(obj.Proxy)])
    bom.append(dict(catalog_id='baseplate',procurement='fabricated',quantity=1,
                    stock_envelope_mm=plan['stock_envelope_mm'],
                    base_slab_dimensions_mm=plan['stock_bounds'][2:]+[plate_thickness],
                    integrated_supports=2))
    optical=static.addObject('App::DocumentObjectGroup','OpticalPaths')
    for orientation,beam in scene.beams.items():
        for segment in beam.get_object().BeamSegments:
            target=_feature(static,orientation+'_beam',segment.Shape,(1.,.15,.05))
            _property(target,'Trace',dict(start_mm=list(segment.Placement.Base),
                direction=list(segment.Proxy.get_global_direction()),distance_mm=segment.Proxy.distance,
                start_interface=segment.StartInterfaceName,end_interface=segment.EndInterfaceName,
                internal=segment.InternalToComponent))
            optical.addObject(target)
    output=Path(output or Path(__file__).resolve().parents[1]/'artifacts/roof_mirror.FCStd').resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    static.recompute()
    expected={o.Name:(o.Shape.Volume,len(o.Shape.Solids)) for o in static.Objects if o.TypeId=='Part::Feature'}
    _property(plate,'BOM',bom)
    _property(plate,'Qualifications',QUALIFICATIONS)
    static.saveAs(str(output))
    compound=Part.makeCompound([o.Shape for o in physical])
    compound.exportStep(str(output.with_suffix('.step')))
    plate.Shape.exportStep(str(output.with_name(output.stem+'_baseplate.step')))
    for orientation,part in scene.parts.items():
        clamp=next(o for o in part.get_object().Children if o.Proxy.contract().catalog_id=='roof-clamp')
        clamp.Shape.exportStep(str(output.with_name(output.stem+'_clamp_'+orientation+'.step')))
    imported=Part.read(str(output.with_suffix('.step')))
    imported_plate=Part.read(str(output.with_name(output.stem+'_baseplate.step')))
    _require(imported.isValid() and len(imported.Solids)==len(compound.Solids),'STEP lost solids')
    error=abs(imported.Volume-compound.Volume)/compound.Volume
    _require(error<1e-6,'STEP volume changed by more than one ppm')
    a,b=compound.optimalBoundingBox(),imported.optimalBoundingBox()
    _require(all(abs(getattr(a,k)-getattr(b,k))<.01 for k in ('XMin','XMax','YMin','YMax','ZMin','ZMax')),
        'STEP bounds changed')
    _require(imported_plate.isValid() and len(imported_plate.Solids)==1 and abs(imported_plate.Volume-plate.Shape.Volume)<.01,
        'Plate STEP roundtrip failed')
    App.closeDocument(static.Name)
    static=App.openDocument(str(output))
    for name,(volume,count) in expected.items():
        obj=static.getObject(name)
        _require(not hasattr(obj,'Proxy') and obj.Shape.isValid() and len(obj.Shape.Solids)==count
            and abs(obj.Shape.Volume-volume)<1e-6,'Static FreeCAD reopen failed')
    checks.update(hardware_solid_count=len(imported.Solids),external_pins=0,step_valid=True,
        step_volume_relative_error=error,native_reopen_valid=True)
    report=dict(units='mm',source_document=scene.document.Name,source_layout=scene.layout.object_id,
        source_parts={k:v.object_id for k,v in scene.parts.items()},
        source_beams={k:v.object_id for k,v in scene.beams.items()},
        source_reference=reference(),
        mechanical_reference=json.loads((catalog.DATA/'roof_support_reference.json').read_text()),
        verification=checks,machining=plan,bom=bom,
        optical_parameters=dict(wavelength_nm=WAVELENGTH,waist_radius_mm=WAIST,power_w=POWER,
                                beam_separation_mm=SPACING,input_height_mm=INPUT_HEIGHT),
        qualifications=QUALIFICATIONS)
    for suffix,value in [('.machining.json',plan),('.bom.json',bom),('.report.json',report),('.verification.json',checks)]:
        output.with_suffix(suffix).write_text(json.dumps(value,indent=2)+'\n')
    horizontal=checks['passes']['horizontal']
    vertical=checks['passes']['vertical']
    lines=['# HRS1015-P01 roof mirror verification','',
        f'Two corrected support designs unioned directly into one {plate_thickness:g} mm baseplate.',
        f'Minimum bounding billet: {plan["stock_envelope_mm"][0]:g} x {plan["stock_envelope_mm"][1]:g} x {plan["stock_envelope_mm"][2]:g} mm, including raised supports.',
        f'Input heights: horizontal {horizontal["installed_input_height_mm"]:g} mm, vertical {vertical["installed_input_height_mm"]:g} mm.',
        f'Return heights: horizontal {horizontal["installed_output_height_mm"]:g} mm, vertical {vertical["installed_output_height_mm"]:g} mm.',
        'Two explicit reflections per optic; each internal air path 25.4 mm, each complete path 125.4 mm.',
        'Two M2 x 0.4 clamp taps, 1.6 mm drill diameter. No carrier, dowels, M4 attachments or recesses.',
        f'STEP: {checks["hardware_solid_count"]} valid solids. Supports are included only in the baseplate. FreeCAD and STEP reopen checks pass.',
        f'Minimum stock beneath drill tips: {checks["minimum_stock_below_drill_tip_mm"]:.4f} mm.','',
        '## Qualifications','',*('- '+q for q in QUALIFICATIONS),'',
        'Rebuild using examples/roof_mirror.py with FreeCAD\'s Python. Editable source remains open; saved review is static.','']
    output.with_suffix('.report.md').write_text('\n'.join(lines))
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
    return static,report


if __name__=='__main__':
    document,report=build()
    print('Verified both roof orientations, integral supports and two M2 clamp taps; saved',document.FileName)
