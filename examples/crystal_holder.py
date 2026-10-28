"""Supplied crystal holder, separate bracket, fasteners and drilled baseplate.

Run with FreeCAD's Python. Exports a portable static document plus editable
bracket STEP, assembly STEP, component contracts, and machining JSON.
"""
import json
from pathlib import Path
import sys
import FreeCAD as App
import Part

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyOpticL import lab_catalog, machined_baseplate
from PyOpticL.layout import Layout


def build(output=None):
    source = App.newDocument('CrystalHolderSource')
    layout = Layout('Crystal holder on plate')
    holder = layout.add(lab_catalog.create('crystal_holder', 'Crystal holder'), (0, 0, 12.7), 0)
    plate, machining = machined_baseplate.add(layout)
    layout.recompute()
    source.recompute()
    if len(machining.plan['holes']) != 4:
        raise ValueError('Crystal baseplate must receive exactly two M4 taps and two dowel bores')

    static = App.newDocument('CrystalHolderOnPlate')
    features, report = [], []
    bracket = None
    for obj in [*holder.get_object().Children, plate.get_object()]:
        feature = static.addObject('Part::Feature', obj.Name)
        feature.Label = obj.Label
        feature.Shape = obj.Shape.copy()
        contract = obj.Proxy.contract().to_dict() if hasattr(obj.Proxy, 'contract') else None
        if contract:
            feature.addProperty('App::PropertyString', 'ComponentContract')
            feature.ComponentContract = json.dumps(contract, indent=2)
            feature.setEditorMode('ComponentContract', 1)
        if feature.ViewObject:
            feature.ViewObject.ShapeColor = obj.Proxy.object_color
            feature.ViewObject.LineColor = (.15, .17, .2)
        if obj is plate.get_object():
            feature.addProperty('App::PropertyString', 'MachiningPlan')
            feature.MachiningPlan = json.dumps(machining.plan, indent=2)
            feature.setEditorMode('MachiningPlan', 1)
        if contract and contract['catalog_id'] == 'crystal-bracket':
            bracket = feature
        features.append(feature)
        report.append(dict(label=feature.Label, volume_mm3=feature.Shape.Volume,
                           contract=contract))
    group = static.addObject('App::DocumentObjectGroup', 'Design')
    group.addObjects(features)
    group.addProperty('App::PropertyString', 'BOM')
    group.BOM = json.dumps(lab_catalog.bom(holder), indent=2)
    group.addProperty('App::PropertyString', 'AssemblyContract')
    group.AssemblyContract = json.dumps(holder.contract().to_dict(), indent=2)
    static.recompute()
    output = Path(output or Path(__file__).resolve().parents[1] / 'artifacts' /
                  'crystal_holder.FCStd').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    static.saveAs(str(output))
    Part.makeCompound([f.Shape for f in features]).exportStep(str(output.with_suffix('.step')))
    bracket.Shape.exportStep(str(output.with_name('crystal_bracket.step')))
    output.with_suffix('.machining.json').write_text(json.dumps(machining.plan, indent=2) + '\n')
    output.with_suffix('.components.json').write_text(json.dumps(report, indent=2) + '\n')
    output.with_suffix('.bom.json').write_text(group.BOM + '\n')
    if App.GuiUp:
        import FreeCADGui as Gui
        if Gui.activeDocument() is not None:
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.activeDocument().activeView().fitAll()
    return static


if __name__ == '__main__':
    build()
