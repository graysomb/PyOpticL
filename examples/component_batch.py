"""Review the vendor-mount batch at native heights, with individual drilled plates.

Exports static FreeCAD/STEP assemblies and a JSON verification/BOM report.
The source layout remains in the session for editing.
"""
import json
from pathlib import Path
import sys

import FreeCAD as App
import Part

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyOpticL import attachments, lab_catalog, machined_baseplate
from PyOpticL.layout import Layout

SAMPLES = [
    ('POLARIS-L05G', 'Half-inch lens mount', {}),
    ('POLARIS-L1G', 'One-inch lens mount', {}),
    ('mirror', 'POLARIS-K1VS2 mirror', {'mount': 'POLARIS-K1VS2'}),
    ('mirror', 'MHV-12.7L-R mirror', {'mount': 'MHV-12.7L-R'}),
    ('mirror', 'MHV-25.4L-R mirror', {'mount': 'MHV-25.4L-R'}),
    ('rotation', 'FBR waveplate', {'mount': 'FBR'}),
    ('slit', 'VA100 slit and bracket', {'slit_width': 1.}),
    ('coupling', 'POLARIS-K05T6 output coupler', {}),
]


def build(output=None):
    source = App.newDocument('ComponentBatchSource')
    root = Layout('Component batch')
    samples = []
    for i, (kind, label, parameters) in enumerate(SAMPLES):
        layout = root.add(Layout(label), ((i % 4) * 120, (i // 4) * 120, 0), 0)
        component = layout.add(lab_catalog.create(kind, label, **parameters), (0, 0, 0), 0)
        height = lab_catalog.native_height(component)
        component.get_object().BasePlacement.Base.z = height
        plate, machining = machined_baseplate.add(layout)
        samples.append((component, plate, machining, height))
    root.recompute()
    source.recompute()
    static = App.newDocument('ComponentBatchReview')
    exported, report = [], []
    for component, plate, machining, height in samples:
        group = static.addObject('App::DocumentObjectGroup', component.object_id + 'Review')
        group.Label = component.get_object().Label
        group.addProperty('App::PropertyLength', 'OpticalHeight')
        group.OpticalHeight = height
        group.setEditorMode('OpticalHeight', 1)
        rows = lab_catalog.bom(component)
        group.addProperty('App::PropertyString', 'ComponentContract')
        group.ComponentContract = json.dumps(component.contract().to_dict(), indent=2)
        group.setEditorMode('ComponentContract', 1)
        group.addProperty('App::PropertyString', 'BOM')
        group.BOM = json.dumps(rows, indent=2)
        group.setEditorMode('BOM', 1)
        for obj in [component.get_object(), *attachments.descendants(component.get_object()), plate.get_object()]:
            if not hasattr(obj, 'Shape') or obj.Shape.isNull():
                continue
            assert obj.Shape.isValid(), obj.Label
            target = static.addObject('Part::Feature', obj.Name)
            target.Label = obj.Label
            target.Shape = obj.Shape.copy()
            for name in ('ComponentContract', 'AvailableDOFs', 'MachiningPlan'):
                if hasattr(obj, name):
                    target.addProperty('App::PropertyString', name)
                    setattr(target, name, getattr(obj, name))
                    target.setEditorMode(name, 1)
            if target.ViewObject:
                target.ViewObject.ShapeColor = obj.Proxy.object_color
            group.addObject(target)
            exported.append(target)
        assert machining.plan['pockets'] == [], component.object_id
        assert len(plate.get_object().Shape.Solids) == 1
        report.append(dict(name=group.Label, optical_height_mm=height,
                           native_component_height_mm=17.78 if component.contract().catalog_id == 'slit' else height,
                           bracket_height_mm=10. if component.contract().catalog_id == 'slit' else 0.,
                           contract=component.contract().to_dict(),
                           machining=machining.plan, bom=rows, solids_valid=True))
    static.recompute()
    output = Path(output or Path(__file__).resolve().parents[1] / 'artifacts' /
                  'component_batch.FCStd').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    static.saveAs(str(output))
    Part.makeCompound([obj.Shape for obj in exported]).exportStep(str(output.with_suffix('.step')))
    record = dict(samples=report, total_plate_operations=sum(len(r['machining']['holes']) for r in report),
        source_measurements=json.loads((lab_catalog.DATA / 'batch_measurements.json').read_text()),
        acceptance_suite='tests/catalog/freecad_component_batch_acceptance.py',
        notes=[
            'All parts sit at their native height on a flat local plate. VA100 assembly adds its real 10 mm bracket.',
            'VA100 mechanical CAD remains in supplier reference pose; slit_width configures the ideal optical interface only.',
            'FBR included retaining ring is positioned against the selected optic; the supplier source is unchanged.',
            'K05T6/AD1109F simplified SM05 thread envelopes overlap about 4.0825 mm3 only within the threaded engagement. No material interference is accepted outside that region. Thread phase is not modeled.',
            'MHV-12.7L-R source working plate has a small nominal pose error: ~0.00036 mm3 mirror contact overlap, within 0.01 mm / 0.01 degree source comparison tolerance.',
            'FBR receiving bores are a custom 3.20 mm nominal clearance selection for included 1/8 inch pins; vendor mating-fit tolerances are not specified.',
        ])
    output.with_suffix('.report.json').write_text(json.dumps(record, indent=2) + '\n')
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
    return static, record


if __name__ == '__main__':
    doc, report = build()
    print('Built', len(report['samples']), 'samples with', report['total_plate_operations'], 'plate operations')
