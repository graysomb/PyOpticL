"""Editable XR25C → explicit adapter → POLARIS-K05VS2 native optical example.

Run with FreeCAD's Python. Travel is in mm relative to the pinned centered pose.
The live FCStd needs this checkout on FreeCAD's Python path when reopening.
"""
from pathlib import Path
import json
import sys
import FreeCAD as App
import Part
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyOpticL import stages,lab_catalog,machined_baseplate,attachments
from PyOpticL.beam_path import BeamPath,Stop
from PyOpticL.layout import Component,Layout


class Receiver:
    def interfaces(self):
        return [Stop((0,0,0),(0,0,0),diameter=80)]


def build(output=None):
    doc=App.newDocument('TranslationStagePayload')
    root=Layout('Stage payload example')
    stage=root.add(stages.create(),(0,0,0),0)
    mirror=lab_catalog.create('mirror','Stage mirror',mount='POLARIS-K05VS2')
    adapter=stage.mount_payload(mirror,yaw=135,adapter=stages.AdapterSpec(
        thickness_mm=16,width_mm=100,depth_mm=70,
        platform_holes=('payload_1','payload_2','payload_7','payload_8'),screw_length_mm=15.875))
    x,y,z=mirror.get_object().Placement.Base
    root.add(Component('Receiver plane',Receiver()),(x,y+100,z),90)
    beam=root.add(BeamPath('Stage beam',wavelength=1550,waist=.25,power=.001,bound_parent=root),(x-100,y,z),0)
    plate,machining=machined_baseplate.add(root,thickness=20,margin=20)
    root.recompute()
    stages.validate_clearance(stage,root)
    for travel in (-12.5,0,12.5):
        stage.set_travel(travel)
        segments=beam.get_object().BeamSegments
        assert len(segments)==2
        assert abs(segments[0].Proxy.distance-(100+travel))<.01
    stage.set_travel(0)
    output=Path(output or Path(__file__).resolve().parents[1]/'artifacts/translation_stage_payload.FCStd').resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    stages.export(stage,plate,output,root=root)
    return dict(document=doc,root=root,stage=stage,mirror=mirror,adapter=adapter,
                beam=beam,plate=plate,machining=machining,output=output)


if __name__=='__main__':
    scene=build()
    print('Editable stage saved:',scene['output'],flush=True)
