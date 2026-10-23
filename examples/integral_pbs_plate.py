"""Small demonstration of the PBS support united with the machined plate."""
import json
from pathlib import Path
import sys
import FreeCAD as App
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyOpticL import lab_catalog, machined_baseplate
from PyOpticL.layout import Layout


def build():
    App.newDocument('IntegralPBSSource')
    layout = Layout('PBS layout')
    pbs = layout.add(lab_catalog.create('pbs','PBS'),
                     (0,0,machined_baseplate.optical_height()),0)
    plate,machining = machined_baseplate.add(layout)
    layout.recompute()
    doc = App.newDocument('IntegralPBSPlate')
    solid = doc.addObject('Part::Feature','BaseplateWithPBSRegisters')
    solid.Label = 'Baseplate with integral PBS seat and clamp bore'
    solid.Shape = plate.get_object().Shape.copy()
    solid.addProperty('App::PropertyString','MachiningPlan')
    solid.MachiningPlan = json.dumps(machining.plan,indent=2)
    solid.setEditorMode('MachiningPlan',1)
    optic = doc.addObject('Part::Feature','PBSCube')
    optic.Label = '12.7 mm PBS'
    optic.Shape = pbs.get_object().Children[0].Shape.copy()
    if solid.ViewObject:
        solid.ViewObject.ShapeColor = (.7,.72,.75)
        optic.ViewObject.ShapeColor = (.4,.7,.9)
        optic.ViewObject.Transparency = 50
    doc.recompute()
    output = Path(__file__).resolve().parents[1]/'artifacts'/'integral_pbs_plate.FCStd'
    output.parent.mkdir(parents=True,exist_ok=True)
    doc.saveAs(str(output))
    solid.Shape.exportStep(str(output.with_suffix('.step')))
    assert len(solid.Shape.Solids) == 1 and solid.Shape.isValid()
    return doc


if __name__ == '__main__':build()
