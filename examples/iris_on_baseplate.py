"""Fixed 12.7 mm iris on a plate with exactly two dowel bores.

Run in FreeCAD or its bundled Python. Static exports reopen without proxies,
vendor assets, or the original reference STEP. All dimensions are millimeters.
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
    source = App.newDocument('IrisPlateSource')
    layout = Layout('Iris on baseplate')
    iris = layout.add(lab_catalog.create('iris', 'Alignment iris', aperture_diameter=.5),
                      (0, 0, 12.7), 0)
    plate, machining = machined_baseplate.add(layout)
    layout.recompute()
    source.recompute()
    assert len(machining.plan['holes']) == 2
    assert all(h['kind'] == 'dowel' for h in machining.plan['holes'])

    static = App.newDocument('IrisOnBaseplate')
    iris_feature = static.addObject('Part::Feature', 'Iris')
    iris_feature.Label = 'Fixed iris — aperture Ø0.5 at 12.7 mm'
    iris_feature.Shape = iris.get_object().Shape.copy()
    iris_feature.addProperty('App::PropertyString', 'ComponentContract')
    iris_feature.ComponentContract = json.dumps(iris.contract().to_dict(), indent=2)
    iris_feature.setEditorMode('ComponentContract', 1)
    iris_feature.addProperty('App::PropertyLength', 'ApertureDiameter')
    iris_feature.ApertureDiameter = .5
    iris_feature.setEditorMode('ApertureDiameter', 1)
    plate_feature = static.addObject('Part::Feature', 'Baseplate')
    plate_feature.Label = 'Baseplate — two Ø2.01 × 4.445 mm dowel bores'
    plate_feature.Shape = plate.get_object().Shape.copy()
    plate_feature.addProperty('App::PropertyString', 'MachiningPlan')
    plate_feature.MachiningPlan = json.dumps(machining.plan, indent=2)
    plate_feature.setEditorMode('MachiningPlan', 1)
    features = [iris_feature, plate_feature]
    for name, operation in zip(('DowelLeft', 'DowelRight'), machining.plan['holes']):
        x, y, z = operation['center_mm']
        pin = static.addObject('Part::Feature', name)
        pin.Label = 'Ø2 × 5 mm dowel pin'
        pin.Shape = Part.makeCylinder(1, 5, App.Vector(x, y, z - operation['depth_mm']))
        features.append(pin)
        assert pin.Shape.common(iris_feature.Shape).Volume < 1e-7
        assert pin.Shape.common(plate_feature.Shape).Volume < 1e-7
    static.addObject('App::DocumentObjectGroup', 'Design').addObjects(features)
    static.Design.addProperty('App::PropertyString', 'BOM')
    static.Design.BOM = json.dumps(lab_catalog.bom(iris) + [
        dict(label='Machined baseplate', procurement='fabricated', quantity=1),
        dict(label='2 mm x 5 mm DIN 7-m6 / ISO 2338 dowel pin',
             procurement='generic', quantity=2)], indent=2)
    if iris_feature.ViewObject:
        iris_feature.ViewObject.ShapeColor = (.25, .25, .25)
        plate_feature.ViewObject.ShapeColor = (.7, .72, .75)
        for pin in features[2:]:
            pin.ViewObject.ShapeColor = (.8, .8, .85)
    static.recompute()
    output = Path(output or Path(__file__).resolve().parents[1] / 'artifacts' /
                  'iris_on_baseplate.FCStd').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    static.saveAs(str(output))
    Part.makeCompound([f.Shape for f in features]).exportStep(str(output.with_suffix('.step')))
    iris_feature.Shape.exportStep(str(output.with_name('alignment_iris.step')))
    output.with_suffix('.machining.json').write_text(json.dumps(machining.plan, indent=2) + '\n')
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
    return static


if __name__ == '__main__':
    build()
