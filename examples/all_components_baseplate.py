"""One folded 1550 nm path, all new mounts, and a recessed 12.7 mm beam plane.

Run with FreeCAD's Python. The editable source remains open; static FreeCAD,
hardware STEP, plate STEP, machining/BOM JSON and a report are exported.
"""
import json
import math
from pathlib import Path
from types import SimpleNamespace
import sys

import FreeCAD as App
import Part

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyOpticL import attachments, lab_catalog as catalog, machined_baseplate
from PyOpticL.beam_path import BeamPath, Stop
from PyOpticL.component_contract import ComponentContract, Frame, Provenance
from PyOpticL.layout import Component, Layout
from PyOpticL.library.optics import Spherical_Lens

BEAM_HEIGHT = 12.7
IRIS_DIAMETER = 2.
SLIT_WIDTH = 2.
WAVELENGTH = 1550.
WAIST = .2
POWER = .001
# ID, preset, descriptive label, X, Y, yaw (degrees), construction parameters.
PLACEMENTS = [
    ('input', 'coupling', 'Input K05T6 coupling', 0, 0, 0, {}),
    ('half_lens', 'lens', 'POLARIS-L05G lens', 60, 0, 0,
     dict(mount='POLARIS-L05G', diameter=12.7, focal_length=100.)),
    ('iris', 'iris', 'Fixed alignment iris', 100, 0, 0, dict(aperture_diameter=IRIS_DIAMETER)),
    ('half_mirror', 'mirror', 'MHV-12.7L-R mirror', 180, 0, 135, dict(mount='MHV-12.7L-R')),
    ('waveplate', 'rotation', 'FBR half-wave plate', 180, 70, 90,
     dict(mount='FBR', thickness=1., retardance=.5, fast_axis_angle=22.5)),
    ('polaris_mirror', 'mirror', 'POLARIS-K1VS2 mirror', 180, 150, -135, dict(mount='POLARIS-K1VS2')),
    ('one_lens', 'lens', 'POLARIS-L1G lens', 90, 150, 180,
     dict(mount='POLARIS-L1G', diameter=25.4, focal_length=150.)),
    ('slit', 'slit', 'VA100 slit and bracket', 0, 150, 180, dict(slit_width=SLIT_WIDTH)),
    ('one_mirror', 'mirror', 'MHV-25.4L-R mirror', -100, 150, -45, dict(mount='MHV-25.4L-R')),
    ('output', 'coupling', 'Output K05T6 coupling', -100, 0, 90, {}),
]
# Start XY, propagation direction, distance, and next optical component.
EXPECTED_ROUTE = [
    ((0, 0), (1, 0, 0), 60, 'half_lens'),
    ((60, 0), (1, 0, 0), 40, 'iris'),
    ((100, 0), (1, 0, 0), 80, 'half_mirror'),
    ((180, 0), (0, 1, 0), 70, 'waveplate'),
    ((180, 70), (0, 1, 0), 80, 'polaris_mirror'),
    ((180, 150), (-1, 0, 0), 90, 'one_lens'),
    ((90, 150), (-1, 0, 0), 90, 'slit'),
    ((0, 150), (-1, 0, 0), 100, 'one_mirror'),
    ((-100, 150), (0, -1, 0), 150, 'receiver'),
]
QUALIFICATIONS = [
    'Generic lenses use cylindrical envelopes and ideal thin-lens behavior; no vendor optic, coating or fiber coupling efficiency is specified.',
    'VA100 slit_width controls the ideal optical aperture; mechanical solids retain the supplier reference opening of 5.8928 mm.',
    'K05T6/AD1109F simplified SM05 envelopes overlap about 4.0825 mm3 inside the nominal thread region only. Physical thread phase, torque and fit under load remain unverified.',
    'FBR retains its supplied 1/8 inch pins. Receiving bores are custom nominal 3.20 x 5 mm clearances; no vendor mating-fit tolerance is available.',
    'MHV-12.7L-R retains its small source pose deviation, with about 0.00036 mm3 nominal mirror contact overlap within the 0.01 mm / 0.01 degree source comparison boundary.',
    'External 2 x 5 mm pins are nominal cylinders. The MHV mating fits remain a custom selection, not a physical fit certification.',
    'VA100 screw geometry is nominal. Other M4 mounting screws are BOM requirements; installation lengths and manufacturer head geometry remain unselected.',
    'Pockets are nominal rectangular clearance geometry, not a CAM toolpath or a cutting-tool/adjustment-access certification. Install the VA100 underside screw before fitting the bracket to the plate.',
]


class DemoLens(Spherical_Lens):
    """Existing generic lens with its rear face on the measured mount contact."""
    def __init__(self, mount, diameter, focal_length):
        super().__init__(diameter=diameter, thickness=2., focal_length=focal_length,
                         mount_definition=catalog.VendorPart(mount), mount_offset=(-1., 0, 0))

    def contract(self):
        return ComponentContract('demo-lens', '1', '', '', 'generic',
            frames=(Frame('optical'), Frame('mount_contact', (-1, 0, 0))),
            optical_reference='optical', provenance=(Provenance('PyOpticL Spherical_Lens', 'documented',
                note=f'Generic diameter {self.diameter:g} mm, thickness 2 mm, focal length {self.focal_length:g} mm. Rear face at mount contact; no selected vendor optic.'),))


class ReceiverPlane:
    """Optical-only termination at the output barrel front; no extra hardware."""
    object_group = 'optics'

    def interfaces(self):
        return [Stop(position=(0, 0, 0), rotation=(0, 0, 0), diameter=5)]


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _physical_objects(component):
    return [o for o in [component.get_object(), *attachments.descendants(component.get_object())]
            if hasattr(o, 'Shape') and not o.Shape.isNull()]


def _build_source(plate_thickness=30.):
    if not math.isfinite(plate_thickness) or plate_thickness <= 10:
        raise ValueError('Plate thickness must be finite and greater than 10 mm')
    document = App.newDocument('AllComponentsSource')
    try:
        layout = Layout('All components on one plate')
        components = {}
        for key, kind, label, x, y, yaw, parameters in PLACEMENTS:
            obj = Component(label, DemoLens(**parameters)) if kind == 'lens' else catalog.create(kind, label, **parameters)
            components[key] = layout.add(obj, (x, y, BEAM_HEIGHT), yaw)
        receiver = layout.add(Component('Output receiver datum', ReceiverPlane()),
                              (-100, 0, BEAM_HEIGHT), 90)
        beam = layout.add(BeamPath('1550 nm folded beam', wavelength=WAVELENGTH, waist=WAIST,
            power=POWER, bound_parent=layout), (0, 0, BEAM_HEIGHT), 0)
        plate, machining = machined_baseplate.add(layout, thickness=plate_thickness,
                                                  margin=20., pocket_clearance=.25)
        layout.recompute()
        document.recompute()
        return SimpleNamespace(document=document, layout=layout, components=components,
                               receiver=receiver, beam=beam, plate=plate, machining=machining)
    except Exception:
        App.closeDocument(document.Name)
        raise


def _verify(scene):
    segments = list(scene.beam.get_object().BeamSegments)
    _require(len(segments) == len(EXPECTED_ROUTE), 'Expected nine beam segments')
    route = []
    for segment, (xy, direction, distance, target) in zip(segments, EXPECTED_ROUTE):
        start = App.Vector(*xy, BEAM_HEIGHT)
        expected_target = scene.receiver if target == 'receiver' else scene.components[target]
        if target in ('waveplate', 'slit'):
            expected_object = expected_target.get_object().Children[0]
        else:
            expected_object = expected_target.get_object()
        _require((segment.Placement.Base - start).Length < .01, 'Incorrect beam start')
        _require((App.Vector(*segment.Proxy.get_global_direction()) - App.Vector(*direction)).Length < 1e-8,
                 'Incorrect beam direction')
        _require(abs(segment.Proxy.distance - distance) < .01, 'Incorrect segment length')
        _require(segment.EndObject == expected_object, 'Incorrect beam interaction: ' + target)
        _require(segment.Shape.isValid(), 'Invalid beam solid')
        route.append(dict(start_mm=list(segment.Placement.Base), direction=list(segment.Proxy.get_global_direction()),
                          distance_mm=segment.Proxy.distance, target=target,
                          final_radius_mm=segment.Proxy.get_beam_radius(segment.Proxy.get_q_parameter() + segment.Proxy.distance)))
    changes = sum((App.Vector(*a['direction']) - App.Vector(*b['direction'])).Length > 1e-7
                  for a, b in zip(route, route[1:]))
    _require(changes == 3, 'Expected three mirror reflections')
    jones = [complex(*v) for v in segments[4].Proxy.polarization_jones]
    _require(abs(jones[0] - jones[1]) < 1e-7 and abs(abs(jones[0]) - math.sqrt(.5)) < 1e-7,
             'Expected linear 45 degree polarization after FBR half-wave plate')
    plan = scene.machining.plan
    _require(len(plan['holes']) == 30, 'Expected 30 attachment operations')
    _require(sum(h['kind'] == 'tapped' for h in plan['holes']) == 12, 'Expected twelve M4 tap drills')
    _require(sum(h['kind'] == 'dowel' for h in plan['holes']) == 18, 'Expected eighteen pin bores')
    _require(len({tuple(round(v, 6) for v in h['center_mm']) for h in plan['holes']}) == 30,
             'Duplicated attachment centers')
    _require(len(plan['pockets']) == 5, 'Expected five recesses')
    for actual, expected in zip(sorted(p['depth_mm'] for p in plan['pockets']), [1.6002, 6.35, 12.7, 12.7, 15.08]):
        _require(abs(actual - expected) < .01, 'Incorrect recess depth')
    _require(abs(plan['optical_height_mm'] - BEAM_HEIGHT) < .01, 'Incorrect installed optical height')
    _require(plan['stock_bounds'] == [-155, -45, 395, 255], 'Unexpected stock footprint')
    plate = scene.plate.get_object().Shape
    _require(plate.isValid() and len(plate.Solids) == 1, 'Plate must be one valid solid')
    remaining = []
    for op in plan['holes']:
        center, axis = App.Vector(*op['center_mm']), App.Vector(*op['axis'])
        for depth in (.1, op['depth_mm'] - .05):
            _require(not plate.isInside(center + axis * depth, 1e-7, False), 'Missing physical bore')
        tip_end = center + axis * (op['depth_mm'] + attachments.tip_height(op['diameter_mm']))
        remaining.append(tip_end.z + scene.machining.thickness)
        _require(plate.isInside(tip_end + axis * .1, 1e-7, False), 'No stock beneath drill tip')
        beside = center + axis * min(2., op['depth_mm']/2) + App.Vector(op['diameter_mm']/2 + .1, 0, 0)
        _require(plate.isInside(beside, 1e-7, False), 'Incorrect physical bore diameter')
    seats, shapes = [], {}
    for key, component in scene.components.items():
        _require(abs(component.get_object().Placement.Base.z - BEAM_HEIGHT) < 1e-7, 'Optic is off plane')
        ComponentContract.from_dict(component.contract().to_dict())
        objects = _physical_objects(component)
        _require(all(o.Shape.isValid() for o in objects), 'Invalid component solid')
        shapes[key] = Part.makeCompound([o.Shape for o in objects])
        for obj in objects:
            profile = attachments.profile(obj.Proxy)
            if profile:
                frames = {f.name: f for f in obj.Proxy.contract().frames}
                seat = obj.Placement.multVec(App.Vector(*frames[profile['seat_frame']].position))
                seats.append(dict(component=key, mount_object=obj.Name,
                    part=obj.Proxy.contract().part_number or obj.Proxy.contract().catalog_id,
                    native_height_mm=catalog.native_height(component), mounting_surface_z_mm=seat.z,
                    recess_depth_mm=(-seat.z if seat.z < -1e-6 else 0.), installed_optical_height_mm=BEAM_HEIGHT,
                    native_component_height_mm=17.78 if key == 'slit' else catalog.native_height(component),
                    bracket_height_mm=10. if key == 'slit' else 0.))
            if hasattr(obj.Proxy, 'contract') and obj.Proxy.contract().procurement == 'purchased':
                _require(sum(plate.common(s).Volume for s in obj.Shape.Solids) < 1e-5,
                         'Purchased part collides with plate: ' + obj.Label)
        if key in ('half_lens', 'one_lens'):
            optic, mount = component.get_object(), component.get_object().Children[0]
            _require(optic.Shape.distToShape(mount.Shape)[0] < .01, 'Lens is not seated')
            _require(sum(optic.Shape.common(s).Volume for s in mount.Shape.Solids) < 1e-6,
                     'Lens collides with mount')
    pairs_checked = 0
    keys = list(shapes)
    for i, a in enumerate(keys):
        for b in keys[i+1:]:
            if shapes[a].BoundBox.intersect(shapes[b].BoundBox):
                pairs_checked += 1
                _require(shapes[a].common(shapes[b]).Volume < 1e-5, 'Components collide: ' + a + ', ' + b)
    return dict(route=route, path_length_mm=sum(s['distance_mm'] for s in route), reflections=changes,
                seats=seats, minimum_stock_below_drill_tip_mm=min(remaining),
                plate_valid=True, physical_bores_checked=30, purchased_part_plate_interference_mm3=0.,
                intercomponent_interference_mm3=0., intercomponent_candidate_pairs=pairs_checked,
                lens_seating_checked=True, waveplate_output_linear_angle_deg=45.)


def _property(obj, name, value):
    obj.addProperty('App::PropertyString', name)
    setattr(obj, name, json.dumps(value, indent=2))
    obj.setEditorMode(name, 1)


def _feature(doc, name, label, shape, color):
    obj = doc.addObject('Part::Feature', name)
    obj.Label, obj.Shape = label, shape.copy()
    _property(obj, 'DisplayColor', list(color))  # Retained by headless exports too.
    if obj.ViewObject:
        obj.ViewObject.ShapeColor = color
    return obj


def build(output=None, plate_thickness=30.0):
    """Build and verify the editable source, then export a cache-independent review."""
    scene = _build_source(plate_thickness)
    checks = _verify(scene)
    before = scene.plate.get_object().Shape.Volume, len(scene.document.Objects)
    scene.layout.recompute()
    scene.document.recompute()
    _require(abs(scene.plate.get_object().Shape.Volume - before[0]) < 1e-6 and
             len(scene.document.Objects) == before[1], 'Recompute changed geometry or duplicated objects')
    plan = scene.machining.plan
    static = App.newDocument('AllComponentsBaseplate')
    design = static.addObject('App::DocumentObjectGroup', 'Design')
    hardware = static.addObject('App::DocumentObjectGroup', 'Hardware')
    design.addObject(hardware)
    physical = []
    plate = _feature(static, 'Baseplate', '395 x 255 mm recessed baseplate',
                     scene.plate.get_object().Shape, (.7, .72, .75))
    _property(plate, 'MachiningPlan', plan)
    hardware.addObject(plate)
    physical.append(plate)
    components = []
    bom = []
    for key, component in scene.components.items():
        group = static.addObject('App::DocumentObjectGroup', key)
        group.Label = next(row[2] for row in PLACEMENTS if row[0] == key)
        hardware.addObject(group)
        rows = catalog.bom(component)
        _property(group, 'ComponentContract', component.contract().to_dict())
        _property(group, 'BOM', rows)
        bom.extend(rows)
        components.append(dict(id=key, label=group.Label, source_object=component.object_id,
            installed_optical_height_mm=BEAM_HEIGHT, native_height_mm=catalog.native_height(component)))
        for obj in _physical_objects(component):
            target = _feature(static, key + '_' + obj.Name, obj.Label, obj.Shape, obj.Proxy.object_color)
            for field in ('ComponentContract', 'AvailableDOFs'):
                if hasattr(obj, field):
                    target.addProperty('App::PropertyString', field)
                    setattr(target, field, getattr(obj, field))
                    target.setEditorMode(field, 1)
            group.addObject(target)
            physical.append(target)
    pins = static.addObject('App::DocumentObjectGroup', 'ExternalPins')
    hardware.addObject(pins)
    for op in plan['holes']:
        if op['kind'] != 'dowel' or op['part'] == 'FBR':
            continue
        center, axis = App.Vector(*op['center_mm']), App.Vector(*op['axis'])
        shape = Part.makeCylinder(1, 5, center + axis * op['depth_mm'], -axis)
        _require(shape.common(plate.Shape).Volume < 1e-7, 'External pin collides with plate')
        mount = scene.document.getObject(op['mount_object'])
        _require(sum(shape.common(s).Volume for s in mount.Shape.Solids) < 1e-6,
                 'External pin collides with mount')
        target = _feature(static, 'Dowel', 'Nominal diameter 2 x 5 mm alignment pin', shape, (.8, .8, .85))
        _property(target, 'AttachmentOperation', op)
        pins.addObject(target)
        physical.append(target)
    _require(len(pins.Group) == 16, 'Expected sixteen external pins; FBR pins are already supplied')
    bom.extend([
        dict(label='Recessed baseplate', procurement='fabricated', quantity=1,
             dimensions_mm=[395, 255, plate_thickness]),
        dict(label='Nominal diameter 2 x 5 mm alignment dowel', procurement='generic', quantity=16, modeled=True),
        dict(label='Additional M4 mounting screw requirements', procurement='generic', quantity=10,
             modeled=False, thread='M4 x 0.7', length='Installation-dependent; not selected',
             note='VA100 already models its two M4 plate screws. Vendor mounting_hardware fields are requirements, not extra BOM quantities.'),
    ])
    _property(design, 'BOM', bom)
    _property(design, 'Description', 'One 760 mm folded path at 12.7 mm over a recessed plate; generic lenses, three mirrors, iris, FBR, VA100 and two K05T6 couplers.')
    _property(design, 'Qualifications', QUALIFICATIONS)
    optical = static.addObject('App::DocumentObjectGroup', 'OpticalPath')
    design.addObject(optical)
    for i, segment in enumerate(scene.beam.get_object().BeamSegments, 1):
        target = _feature(static, 'BeamSegment' + str(i), '1550 nm beam: ' + str(round(segment.Proxy.distance)) + ' mm',
                          segment.Shape, (1., .15, .05))
        _property(target, 'Trace', checks['route'][i-1])
        optical.addObject(target)
    static.recompute()
    output = Path(output or Path(__file__).resolve().parents[1] / 'artifacts' /
                  'all_components_baseplate.FCStd').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    expected = {o.Name: (o.Shape.Volume, len(o.Shape.Solids))
                for o in static.Objects if o.TypeId == 'Part::Feature'}
    compound = Part.makeCompound([o.Shape for o in physical])
    reference_volume = compound.Volume
    reference_bounds = compound.optimalBoundingBox()
    static.saveAs(str(output))
    compound.exportStep(str(output.with_suffix('.step')))
    plate.Shape.exportStep(str(output.with_name(output.stem + '_baseplate.step')))
    imported = Part.read(str(output.with_suffix('.step')))
    _require(imported.isValid() and len(imported.Solids) == len(compound.Solids), 'STEP lost valid solids')
    error = abs(imported.Volume - reference_volume) / reference_volume
    _require(error < 1e-6, 'STEP compound volume changed by more than one ppm')
    bounds = imported.optimalBoundingBox()
    _require(all(abs(getattr(bounds, k) - getattr(reference_bounds, k)) < .01
                 for k in ('XMin', 'XMax', 'YMin', 'YMax', 'ZMin', 'ZMax')), 'STEP bounds changed')
    checks.update(recompute_stable=True, external_pins=16, step_valid=True,
                  hardware_solid_count=len(imported.Solids), step_volume_relative_error=error,
                  step_bounds_within_mm=.01)
    App.closeDocument(static.Name)
    static = App.openDocument(str(output))
    for name, (volume, count) in expected.items():
        obj = static.getObject(name)
        _require(obj.Shape.isValid() and len(obj.Shape.Solids) == count and not hasattr(obj, 'Proxy'),
                 'Invalid static review feature')
        _require(abs(obj.Shape.Volume - volume) < 1e-6, 'Native reopen changed feature volume')
    checks['native_reopen_valid'] = True
    report = dict(units='mm', source_document=scene.document.Name, source_layout=scene.layout.object_id,
        source_beam=scene.beam.object_id, beam_height_mm=BEAM_HEIGHT, plate_thickness_mm=plate_thickness,
        optical_parameters=dict(wavelength_nm=WAVELENGTH, waist_radius_mm=WAIST, power_w=POWER,
                                iris_diameter_mm=IRIS_DIAMETER, slit_width_mm=SLIT_WIDTH),
        components=components, verification=checks, machining=plan, bom=bom, qualifications=QUALIFICATIONS)
    for suffix, value in (('.machining.json', plan), ('.bom.json', bom), ('.report.json', report)):
        output.with_suffix(suffix).write_text(json.dumps(value, indent=2) + '\n')
    lines = ['# All-components recessed baseplate demo', '',
        f'Plate: 395 x 255 x {plate_thickness:g} mm. Optical plane: 12.7 mm above plate top.',
        'One continuous 1550 nm path: nine segments, three reflections, 760 mm total.', '',
        '## Verification', '', '30 physical bores: 12 M4 tap drills and 18 pin bores. Five recesses.',
        f'Minimum stock below a drill tip: {checks["minimum_stock_below_drill_tip_mm"]:.4f} mm.',
        'One valid plate solid; no purchased-part/plate or intercomponent interference.',
        'Both lenses seated; FBR produces linear 45 degree polarization; repeat recomputation stable.',
        f'16 external pins plus FBR\'s two supplied pins. Hardware STEP: {checks["hardware_solid_count"]} valid solids.',
        'Native reopen and STEP roundtrip pass. Beam geometry appears only in the FreeCAD review.', '',
        '| Component | Native assembly height (mm) | Recess (mm) |', '|---|---:|---:|']
    lines.extend(f'| {s["component"]} | {s["native_height_mm"]:g} | {s["recess_depth_mm"]:g} |' for s in checks['seats'])
    lines.extend(['', '## Qualifications', '', *('- ' + note for note in QUALIFICATIONS), '',
                  'Rebuild with examples/all_components_baseplate.py in FreeCAD or its bundled Python.',
                  'The source document remains open for editing; the saved review requires neither Python proxies nor the CAD cache.', ''])
    output.with_suffix('.report.md').write_text('\n'.join(lines))
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
    return static, report


if __name__ == '__main__':
    document, result = build()
    print('Verified 760 mm folded path, five recesses and 30 attachment operations; saved', document.FileName)
