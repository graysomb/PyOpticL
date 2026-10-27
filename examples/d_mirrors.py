"""Two exact D-mirror/holder pairs on one flat plate, at native beam heights."""
import json
from pathlib import Path
import sys
import FreeCAD as App
import Part

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyOpticL import attachments, lab_catalog as catalog, machined_baseplate
from PyOpticL.beam_path import BeamPath, Stop
from PyOpticL.layout import Component, Layout

SAMPLES = [('KM05DR', (0, 0)), ('KM100D', (120, 80))]
WAVELENGTH, WAIST, POWER, YAW = 1550., .2, .001, 135.
QUALIFICATIONS = [
    'Source STEP and drawings are versioned. PFD10 closed shell is promoted using unchanged faces.',
    'Optical datum is 1 mm below the straight edge; native beam heights are 16.526 and 31.004 mm.',
    'KM100D example optic is excluded because it is not supplied; exact PFD10-03-P01 replaces it.',
    'KM05DR is rear loaded: S1 faces its front opening; nylon screws retract 0.44375 mm to contact rear S2.',
    'KM100D knob requires one 0.885 mm plate clearance relief; mounting face stays at plate top.',
    'One M4 cap screw for KM100D and one 8-32 x 1/4 in stud for KM05DR are BOM requirements. No dowels.',
    'Ideal single-sided reflection with conservative 90%-diameter semicircular clear aperture and 0.1 mm edge exclusion. No coating efficiency, edge diffraction, or clamp-force model.',
    'Nominal CAD fit and engagement are checked; manufacturing fit and physical retention require validation.',
]


class Receiver:
    def interfaces(self):
        return [Stop((0, 0, 0), (0, 0, 0), diameter=1)]


def _property(obj, name, value):
    obj.addProperty('App::PropertyString', name)
    setattr(obj, name, json.dumps(value, indent=2))
    obj.setEditorMode(name, 1)


def build(output=None, plate_thickness=30.):
    source = App.newDocument('DMirrorsSource')
    root = Layout('D-mirror pairs at native heights')
    samples = []
    for mount, (x, y) in SAMPLES:
        component = root.add(catalog.create('d_mirror', mount, mount=mount), (x, y, 0), YAW)
        height = catalog.native_height(component)
        component.get_object().BasePlacement.Base.z = height
        beam = root.add(BeamPath(mount + ' beam', wavelength=WAVELENGTH, waist=WAIST,
            power=POWER, bound_parent=root), (x - 50, y, height), 0)
        receiver = beam.add(Component(mount + ' receiver', Receiver()), 1, 0,
                            distance=40, after_object=component)
        samples.append((component, beam, receiver, height))
    plate, machining = machined_baseplate.add(root, thickness=plate_thickness, margin=20)
    root.recompute(); source.recompute()
    checks = []
    for component, beam, receiver, height in samples:
        optic, holder = component.get_object().Children
        segments = beam.get_object().BeamSegments
        if len(segments) != 2 or abs(sum(s.Proxy.distance for s in segments) - 90) > 1e-6:
            raise ValueError('Expected one reflection and a 90 mm traced path')
        for obj in (optic, holder):
            if not obj.Shape.isValid() or sum(plate.get_object().Shape.common(s).Volume for s in obj.Shape.Solids) > 1e-6:
                raise ValueError('Invalid solid or plate/component interference')
        if sum(optic.Shape.common(s).Volume for s in holder.Shape.Solids) > 1e-6:
            raise ValueError('Optic/holder interference')
        if optic.Shape.distToShape(holder.Shape)[0] > 1e-6:
            raise ValueError('Mirror is not seated')
        for segment in segments:
            direction = App.Vector(*segment.Proxy.get_global_direction())
            envelope = Part.makeCylinder(.25, segment.Proxy.distance-.02,
                segment.Placement.Base+.01*direction, direction)
            if sum(envelope.common(s).Volume for s in holder.Shape.Solids) > 1e-6:
                raise ValueError('Illustrative beam envelope clips its holder')
        checks.append(dict(mount=holder.Proxy.part, optic=optic.Proxy.part,
            native_beam_height_mm=height, segments=2, reflections=1,
            path_length_mm=sum(s.Proxy.distance for s in segments),
            contracts=[o.Proxy.contract().to_dict() for o in (optic, holder)],
            bom=catalog.bom(component), solids_valid=True, nominal_fit_passed=True))
    if len(machining.plan['holes']) != 2 or len(machining.plan['pockets']) != 1:
        raise ValueError('Expected two tapped bores and one knob clearance pocket')
    static = App.newDocument('DMirrorsReview')
    physical = []
    for obj in attachments.descendants(root.get_object()):
        if not hasattr(obj, 'Shape') or obj.Shape.isNull():
            continue
        target = static.addObject('Part::Feature', obj.Name)
        target.Label, target.Shape = obj.Label, obj.Shape.copy()
        is_beam = getattr(obj.Proxy, 'object_group', '') == 'beam_path'
        color = (1., .15, .05) if is_beam else obj.Proxy.object_color
        if target.ViewObject:
            target.ViewObject.ShapeColor = color
        if hasattr(obj.Proxy, 'contract'):
            _property(target, 'ComponentContract', obj.Proxy.contract().to_dict())
        if obj is plate.get_object():
            _property(target, 'MachiningPlan', machining.plan)
        if not is_beam:
            physical.append(target)
    report = dict(samples=checks, machining=machining.plan, qualifications=QUALIFICATIONS,
                  bom=[row for c, _, _, _ in samples for row in catalog.bom(c)])
    report['bom'].append(dict(catalog_id='baseplate', procurement='fabricated', quantity=1))
    metadata = static.addObject('App::DocumentObjectGroup', 'ReviewMetadata')
    _property(metadata, 'VerificationReport', report)
    output = Path(output or Path(__file__).resolve().parents[1]/'artifacts/d_mirrors.FCStd').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    static.recompute(); static.saveAs(str(output))
    compound = Part.makeCompound([o.Shape for o in physical])
    compound.exportStep(str(output.with_suffix('.step')))
    plate.get_object().Shape.exportStep(str(output.with_name(output.stem+'_baseplate.step')))
    imported = Part.read(str(output.with_suffix('.step')))
    if not imported.isValid() or len(imported.Solids) != len(compound.Solids):
        raise ValueError('STEP export lost valid solids')
    if abs(imported.Volume - compound.Volume)/compound.Volume > 1e-6:
        raise ValueError('STEP roundtrip changed volume')
    report['export'] = dict(solids=len(imported.Solids), step_roundtrip_passed=True)
    output.with_suffix('.report.json').write_text(json.dumps(report, indent=2)+'\n')
    output.with_suffix('.machining.json').write_text(json.dumps(machining.plan, indent=2)+'\n')
    output.with_suffix('.bom.json').write_text(json.dumps(report['bom'], indent=2)+'\n')
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
    return static, report


if __name__ == '__main__':
    document, report = build()
    print('Built both native-height D-mirror pairs with two plate bores and one knob relief.')
