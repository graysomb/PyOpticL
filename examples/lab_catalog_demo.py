"""Run in FreeCAD, or its bundled Python with FreeCAD's lib on PYTHONPATH.

Writes a static FCStd with ordinary Part features, so reopening needs no proxy
classes or vendor cache. The source layout remains available in the session.
"""
import json
from pathlib import Path
import FreeCAD as App
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyOpticL import lab_catalog
from PyOpticL.layout import Layout


def build(output):
    source = App.newDocument('LabCatalogSource')
    layout = Layout('Lab catalog')
    assemblies = []
    for kind, position in zip(lab_catalog.CATALOG_IDS,
                             [(0,0,0),(80,0,0),(0,100,0),(90,100,0),(220,50,0)]):
        assemblies.append(layout.add(lab_catalog.create(kind, kind), position, 0))
    layout.recompute()
    source.recompute()
    static = App.newDocument('LabCatalogNominal')
    for assembly in assemblies:
        group = static.addObject('App::DocumentObjectGroup', assembly.object_id)
        group.Label = assembly.get_object().Label
        group.addProperty('App::PropertyString', 'AvailableDOFs')
        group.AvailableDOFs = assembly.contract().summary()
        group.setEditorMode('AvailableDOFs', 1)
        group.addProperty('App::PropertyString', 'ComponentContract')
        group.ComponentContract = json.dumps(assembly.contract().to_dict(), sort_keys=True)
        group.setEditorMode('ComponentContract', 1)
        group.addProperty('App::PropertyString', 'BOM')
        group.BOM = json.dumps(lab_catalog.bom(assembly), sort_keys=True)
        group.setEditorMode('BOM', 1)
        def copy_part(obj):
            if hasattr(obj, 'Shape') and not obj.Shape.isNull():
                target = static.addObject('Part::Feature', obj.Name)
                target.Label = obj.Label
                target.Shape = obj.Shape.copy()
                if hasattr(obj, 'ComponentContract'):
                    for name in ('ComponentContract', 'AvailableDOFs'):
                        target.addProperty('App::PropertyString', name)
                        setattr(target, name, getattr(obj, name))
                        target.setEditorMode(name, 1)
                if target.ViewObject:
                    target.ViewObject.ShapeColor = obj.Proxy.object_color
                group.addObject(target)
            for child in obj.Children:
                copy_part(child)
        copy_part(assembly.get_object())
    static.recompute()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    static.saveAs(str(output))
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
    return static


if __name__ == '__main__':
    build(Path(__file__).resolve().parents[1] / 'artifacts' / 'lab_catalog.FCStd')
