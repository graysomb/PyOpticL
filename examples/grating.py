"""One native-height MK05S-mounted LightSmyth grating on a drilled baseplate.

Run with FreeCAD's Python. Optical and placement parameters are editable below.
The saved review contains static B-reps and contracts, without cache dependencies.
"""
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import FreeCAD as App
import Part

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyOpticL import attachments, lab_catalog as catalog, machined_baseplate
from PyOpticL.beam_path import BeamPath, Stop
from PyOpticL.component_contract import ComponentContract
from PyOpticL.layout import Component, Layout
from PyOpticL.grating import reference

WAVELENGTH = 1550.
INCIDENCE_ANGLE = 49.9
ORDER = 1
WAIST = .2
POWER = .001
PLACEMENT = (0.,0.)
YAW = 0.
QUALIFICATIONS = [
    'Exact imperial MK05S STEP, all 25 source solids preserved; engineering drawing TTN193112-E0W revision A.',
    'Grating envelope and clear aperture are parametric manufacturer dimensions, not a supplied grating STEP. Grooves follow its short edge.',
    'Single selected ideal transmission order. Power is preserved as a modeling convention, not a diffraction-efficiency prediction.',
    'Thin interface in air: substrate displacement and OPL, coating phase, polarization-dependent efficiency, diffraction patterns and Gaussian anamorphism are not modeled.',
    'The grating seats directly in MK05S. Its existing nylon lock retains the vendor reference pose and requires 0.55875 mm nominal advance to reach the glass edge; no articulation or clamp-force calculation.',
    'Direct seating is user specified. The selected 0.95 mm glass is below the published 2.54 mm minimum mount thickness; geometric seating/clearance is checked, while physical retention and manufactured fit remain unvalidated. The only custom mount part is the baseplate adapter.',
    'Nominal screw envelopes use cylindrical threads. Accepted overlaps are restricted to M4 plate thread annuli.',
]


class Receiver:
    def interfaces(self):
        return [Stop((0,0,0),(0,0,0),diameter=1)]


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _property(obj, name, value):
    obj.addProperty('App::PropertyString',name)
    setattr(obj,name,json.dumps(value,indent=2))
    obj.setEditorMode(name,1)


def _feature(doc, name, shape, color):
    obj = doc.addObject('Part::Feature',name)
    obj.Shape = shape.copy()
    _property(obj,'DisplayColor',color)
    if obj.ViewObject:
        obj.ViewObject.ShapeColor = color
    return obj


def _build_source(plate_thickness=30.):
    doc = App.newDocument('GratingSource')
    try:
        root = Layout('Native-height transmission grating')
        grating = root.add(catalog.create('grating','MK05S LightSmyth grating',
            design_wavelength=WAVELENGTH,incidence_angle=INCIDENCE_ANGLE,order=ORDER),
            (*PLACEMENT,reference()['assembly_height_mm']),YAW)
        grating.compute_placement()
        source = grating.get_object().Placement.multVec(App.Vector(-50,0,0))
        beam = root.add(BeamPath('Grating beam',wavelength=WAVELENGTH,waist=WAIST,
            power=POWER,bound_parent=root),tuple(source),YAW)
        receiver = beam.add(Component('Diffracted receiver',Receiver()),1,0,
                            distance=50,after_object=grating)
        plate, machining = machined_baseplate.add(root,thickness=plate_thickness,margin=20,pocket_clearance=.25)
        root.recompute();doc.recompute()
        return SimpleNamespace(document=doc,layout=root,grating=grating,beam=beam,
                               receiver=receiver,plate=plate,machining=machining)
    except Exception:
        App.closeDocument(doc.Name)
        raise


def _thread_annulus(screw, outer, inner, offset, depth):
    direction = screw.Placement.Rotation.multVec(App.Vector(0,0,-1))
    start = screw.Placement.Base+direction*offset
    return Part.makeCylinder(outer,depth,start,direction).cut(Part.makeCylinder(inner,depth,start,direction))


def _contact_area(a, b):
    # OCCT solid/solid common intentionally omits zero-volume touching faces.
    # Intersect coincident planar faces explicitly to measure seating contact.
    area = 0.
    for face in a.Faces:
        if not isinstance(face.Surface,Part.Plane):
            continue
        n = face.normalAt(0,0)
        for other in b.Faces:
            if (isinstance(other.Surface,Part.Plane)
                    and abs(abs(n.dot(other.normalAt(0,0)))-1)<1e-8
                    and abs((face.CenterOfMass-other.CenterOfMass).dot(n))<1e-7):
                area += face.common(other).Area
    return area


def _verify(scene):
    grating, beam, plate = scene.grating, scene.beam, scene.plate.get_object().Shape
    objects = list(grating.get_object().Children)
    plan = scene.machining.plan
    _require(plate.isValid() and len(plate.Solids)==1,'Plate must be one valid solid')
    _require(len(plan['holes'])==4 and sum(o['kind']=='dowel' for o in plan['holes'])==2,
             'Expected two tapped holes and two pin bores')
    _require(plan['pockets']==[],'Native-height assembly should not require a recess')
    segments = list(beam.get_object().BeamSegments)
    _require(len(segments)==2,'Expected one incident and one diffracted segment')
    _require(segments[0].EndObject==grating.get_object() and segments[1].EndObject==scene.receiver.get_object(),
             'Incorrect interaction order')
    measured = beam.measure_properties(grating)
    _require(measured is not None and beam.get_output_indices(grating)==[1],'Missing diffracted output')
    expected = grating.get_object().Placement.Rotation.multVec(App.Vector(
        math.cos(math.radians(grating.angles['deflection_angle_deg'])),
        math.sin(math.radians(grating.angles['deflection_angle_deg'])),0))
    _require((App.Vector(*segments[1].Proxy.get_global_direction())-expected).Length<1e-8,'Incorrect diffraction direction')
    _require(abs(sum(o.Proxy.distance for o in segments)-100)<1e-7,'Incorrect total traced length')
    for obj in objects:
        _require(obj.Shape.isValid(),'Invalid solid: '+obj.Label)
        overlap = obj.Shape.common(plate)
        if obj.Label.startswith('M4 plate screw'):
            _require(overlap.cut(_thread_annulus(obj,2,1.65,5.6,6.4)).Volume<1e-6,
                     'Plate screw collision outside allowed thread annulus')
        else:
            _require(overlap.Volume<1e-6,'Component intersects plate: '+obj.Label)
        if obj.Proxy.contract().catalog_id != 'LightSmyth-1336552':
            for segment in segments:
                _require(segment.Shape.common(obj.Shape).Volume<1e-6,'Beam envelope hits hardware: '+obj.Label)
    for i,a in enumerate(objects):
        for b in objects[i+1:]:
            _require(a.Shape.common(b.Shape).Volume<1e-6,
                     'Unintended component interference: '+a.Label+', '+b.Label)
    glass = next(o for o in objects if o.Proxy.contract().catalog_id=='LightSmyth-1336552')
    mount = next(o for o in objects if o.Proxy.contract().catalog_id=='MK05S')
    _require(_contact_area(glass.Shape,mount.Shape)>7.,'Grating edge is not seated directly against MK05S')
    _require(glass.Shape.distToShape(mount.Shape)[0]<1e-7,'Grating does not contact MK05S')
    r = reference()
    native_rotation = App.Rotation('XYZ',*r['normalization']['rotation'])
    normalization = App.Placement(-native_rotation.multVec(App.Vector(*r['normalization']['origin'])),native_rotation)
    installation = (grating.get_object().Placement*
        App.Placement(App.Vector(),App.Rotation('XYZ',*grating.optical_rotation))*normalization)
    for access in r['tool_access_native']:
        tool = Part.makeCylinder(1,20,installation.multVec(App.Vector(*access['start_mm'])),
            installation.Rotation.multVec(App.Vector(*access['direction'])))
        _require(tool.common(plate).Volume<1e-6,'Tool approach intersects plate')
        for obj in objects:
            _require(tool.common(obj.Shape).Volume<1e-6,'Tool approach blocked: '+access['name']+' / '+obj.Label)
    for segment in segments:
        _require(segment.Shape.common(plate).Volume<1e-6,'Beam envelope intersects plate')
    minimum_stock = []
    for operation in plan['holes']:
        center,axis = App.Vector(*operation['center_mm']),App.Vector(*operation['axis'])
        _require(not plate.isInside(center+axis,1e-7,False),'Missing physical plate bore')
        remaining = plan['thickness_mm']+center.z-operation['depth_mm']-attachments.tip_height(operation['diameter_mm'])
        _require(remaining>=.5,'Insufficient stock beneath drill tips')
        minimum_stock.append(remaining)
    state = len(scene.document.Objects),plate.Volume
    scene.layout.recompute()
    _require(len(scene.document.Objects)==state[0] and abs(scene.plate.get_object().Shape.Volume-state[1])<1e-6,
             'Repeated recomputation changed geometry or duplicated objects')
    return dict(angles=grating.angles,native_mount_height_mm=reference()['native_height_mm'],
        assembly_height_mm=catalog.native_height(grating),physical_bores_checked=4,
        beam_segments=2,complete_path_length_mm=100.,beam_hardware_clear=True,
        plate_valid=True,recompute_stable=True,thread_envelope_overlaps=[],
        direct_mount_contacts_checked=True,
        direct_mount_contact_area_mm2=_contact_area(glass.Shape,mount.Shape),
        adjuster_access_checked=True,
        minimum_stock_below_drill_tip_mm=min(minimum_stock),
        post_screw_insertion_mm=reference()['adapter']['post_engagement_mm'],
        post_screw_engagement_mm=reference()['adapter']['post_straight_engagement_mm'],
        m4_plate_engagement_mm=6.4,
        reference_lock_gap_mm=reference()['direct_seating']['reference_lock_gap_mm'])


def build(output=None,plate_thickness=30.):
    scene = _build_source(plate_thickness)
    checks = _verify(scene)
    static = App.newDocument('GratingReview')
    physical = []
    plate = _feature(static,'Baseplate',scene.plate.get_object().Shape,(.7,.72,.75))
    physical.append(plate)
    _property(plate,'MachiningPlan',scene.machining.plan)
    group = static.addObject('App::DocumentObjectGroup','GratingAssembly')
    _property(group,'ComponentContract',scene.grating.contract().to_dict())
    for obj in scene.grating.get_object().Children:
        target = _feature(static,obj.Name,obj.Shape,obj.Proxy.object_color)
        target.Label = obj.Label
        _property(target,'ComponentContract',obj.Proxy.contract().to_dict())
        group.addObject(target);physical.append(target)
    for operation in scene.machining.plan['holes']:
        if operation['kind'] != 'dowel':
            continue
        center,axis = App.Vector(*operation['center_mm']),App.Vector(*operation['axis'])
        shape = Part.makeCylinder(1,5,center+axis*operation['depth_mm'],-axis)
        _require(shape.common(plate.Shape).Volume<1e-6,'Pin intersects plate')
        for obj in scene.grating.get_object().Children:
            _require(shape.common(obj.Shape).Volume<1e-6,'Pin intersects component')
        pin = _feature(static,'Dowel',shape,(.8,.8,.85))
        _property(pin,'AttachmentOperation',operation)
        group.addObject(pin);physical.append(pin)
    paths = static.addObject('App::DocumentObjectGroup','OpticalPath')
    for segment in scene.beam.get_object().BeamSegments:
        target = _feature(static,'Beam',segment.Shape,(1.,.12,.05))
        _property(target,'Trace',dict(start_mm=list(segment.Placement.Base),
            direction=list(segment.Proxy.get_global_direction()),distance_mm=segment.Proxy.distance))
        paths.addObject(target)
    bom = catalog.bom(scene.grating)
    bom.extend([dict(catalog_id='dowel',part_number='2 mm x 5 mm DIN 7-m6 / ISO 2338',
                     procurement='generic',quantity=2),
                dict(catalog_id='baseplate',procurement='fabricated',quantity=1,
                     dimensions_mm=scene.machining.plan['stock_bounds'][2:]+[plate_thickness])])
    _property(group,'BOM',bom)
    _property(plate,'Qualifications',QUALIFICATIONS)
    output = Path(output or Path(__file__).resolve().parents[1]/'artifacts/grating.FCStd').resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    static.recompute();static.saveAs(str(output))
    compound = Part.makeCompound([obj.Shape for obj in physical])
    compound.exportStep(str(output.with_suffix('.step')))
    plate.Shape.exportStep(str(output.with_name(output.stem+'_baseplate.step')))
    for catalog_id,suffix in (('grating-adapter','adapter'),):
        obj = next(o for o in scene.grating.get_object().Children if o.Proxy.contract().catalog_id==catalog_id)
        shape = obj.Shape.copy();shape.Placement = App.Placement()
        shape.exportStep(str(output.with_name(output.stem+'_'+suffix+'.step')))
    imported = Part.read(str(output.with_suffix('.step')))
    imported_plate = Part.read(str(output.with_name(output.stem+'_baseplate.step')))
    _require(imported.isValid() and len(imported.Solids)==len(compound.Solids),'Hardware STEP lost solids')
    _require(abs(imported.Volume-compound.Volume)/compound.Volume<1e-6,'Hardware STEP volume changed')
    _require(imported_plate.isValid() and len(imported_plate.Solids)==1 and
        abs(imported_plate.Volume-plate.Shape.Volume)<.01,'Plate STEP roundtrip failed')
    a,b = compound.optimalBoundingBox(),imported.optimalBoundingBox()
    _require(all(abs(getattr(a,k)-getattr(b,k))<.01 for k in ('XMin','XMax','YMin','YMax','ZMin','ZMax')),
             'Hardware STEP bounds changed')
    expected = {o.Name:(o.Shape.Volume,len(o.Shape.Solids)) for o in static.Objects if o.TypeId=='Part::Feature'}
    App.closeDocument(static.Name);static = App.openDocument(str(output))
    for name,(volume,count) in expected.items():
        obj = static.getObject(name)
        _require(not hasattr(obj,'Proxy') and obj.Shape.isValid() and len(obj.Shape.Solids)==count
                 and abs(obj.Shape.Volume-volume)<1e-6,'Static FreeCAD reopen failed')
        if hasattr(obj,'ComponentContract'):
            ComponentContract.from_dict(json.loads(obj.ComponentContract))
    checks.update(hardware_solid_count=len(imported.Solids),external_pins=2,step_valid=True,native_reopen_valid=True)
    report = dict(units='mm',source_document=scene.document.Name,source_layout=scene.layout.object_id,
        source_grating=scene.grating.object_id,source_beam=scene.beam.object_id,
        reference=reference(),verification=checks,machining=scene.machining.plan,bom=bom,
        optical_parameters=dict(wavelength_nm=WAVELENGTH,waist_radius_mm=WAIST,power_w=POWER),
        qualifications=QUALIFICATIONS)
    for suffix,value in (('.report.json',report),('.machining.json',scene.machining.plan),
                          ('.bom.json',bom),('.verification.json',checks)):
        output.with_suffix(suffix).write_text(json.dumps(value,indent=2)+'\n')
    output.with_suffix('.report.md').write_text('\n'.join([
        '# MK05S LightSmyth grating verification','',
        f'{WAVELENGTH:g} nm: {checks["angles"]["incidence_angle_deg"]:.5f} deg incidence, '
        f'{checks["angles"]["diffraction_angle_deg"]:.5f} deg diffraction, '
        f'{checks["angles"]["deflection_angle_deg"]:.5f} deg beam deflection.',
        'Native mount height 10.5061 mm; assembly height 20.5061 mm; no recess or height-compensating spacer.',
        'Two incident/output legs, 100 mm total; Gaussian envelopes clear hardware and plate.',
        'Two M4 taps and two pin bores; two external 2 x 5 mm pins. The internal 4-40 screw does not drill the plate.',
        f'Export/reopen checks pass: {checks["hardware_solid_count"]} hardware solids, one baseplate solid.',
        f'Minimum stock below drill tips {checks["minimum_stock_below_drill_tip_mm"]:.4f} mm.',
        '', '## Qualifications','',*('- '+q for q in QUALIFICATIONS),'',
        'Rebuild: run examples/grating.py with FreeCAD Python. Saved review is static; source document remains editable.','']))
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
    return static,report


if __name__=='__main__':
    document,report = build()
    print('Verified native-height grating and four plate bores; saved',document.FileName)
