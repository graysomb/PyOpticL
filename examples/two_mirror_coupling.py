"""Catalog coupler -> two 90-degree turning mirrors -> receiving coupler.

Run in FreeCAD or its bundled Python. Distances are millimeters. The launched
1550 nm Gaussian beam is illustrative; no fiber mode/efficiency is inferred.
The receiving coupler is represented by a termination at its front datum.
"""
import json
from pathlib import Path
import sys
import FreeCAD as App
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyOpticL import lab_catalog
from PyOpticL.beam_path import BeamPath, Stop
from PyOpticL.layout import Component, Layout


class ReceiverPlane:
    """Optical-only termination; no added purchased hardware."""
    def interfaces(self):
        return [Stop(position=(0,0,0), rotation=(0,0,0), diameter=5)]


def build(output=None):
    source = App.newDocument('TwoMirrorCouplingSource')
    layout = Layout('Two mirror fiber link')
    # Coupler local +X points out of the lens, through the adapter/mount bore.
    placements = [
        ('coupling', 'Input coupler', (0,0,50.8), 0),
        ('mirror', 'Turning mirror 1', (120,0,50.8), 135),
        ('mirror', 'Turning mirror 2', (120,100,50.8), -45),
        ('coupling', 'Output coupler', (240,100,50.8), 180),
    ]
    assemblies = [layout.add(lab_catalog.create(kind, label), position, angle)
                  for kind, label, position, angle in placements]
    layout.add(Component('Receiver front datum', ReceiverPlane()), (240,100,50.8), 0)
    beam = layout.add(BeamPath('1550 nm beam', wavelength=1550, waist=.75,
                              power=.001, bound_parent=layout), (0,0,50.8), 0)
    layout.recompute()
    source.recompute()
    segments = list(beam.get_object().BeamSegments)
    # Validate the actual traced route, not just nominal object placements.
    expected = [((0,0,50.8),(1,0,0),120),
                ((120,0,50.8),(0,1,0),100),
                ((120,100,50.8),(1,0,0),120)]
    assert len(segments) == 3, 'Expected exactly two reflections and a receiver stop'
    for segment, (start,direction,distance) in zip(segments,expected):
        assert (segment.Placement.Base-App.Vector(*start)).Length < .01
        assert (App.Vector(*segment.Proxy.direction)-App.Vector(*direction)).Length < 1e-8
        assert abs(segment.Proxy.distance-distance) < .01
        assert segment.Shape.isValid()
    assert segments[-1].EndObject.Label == 'Receiver front datum'

    # Native static features reopen without Python proxies or the asset cache.
    static = App.newDocument('TwoMirrorCoupling')
    information = static.addObject('App::DocumentObjectGroup', 'Design')
    information.addProperty('App::PropertyString', 'Description')
    information.Description = ('1550 nm nominal link: 120 + 100 + 120 mm. '
        'Optical height 50.8 mm. Illustrative waist radius 0.75 mm, power 1 mW. '
        'No fiber coupling efficiency or baseplate/support design included.')
    information.addProperty('App::PropertyString', 'BOM')
    information.BOM = json.dumps([row for a in assemblies for row in lab_catalog.bom(a)], indent=2)
    for assembly in assemblies:
        group = static.addObject('App::DocumentObjectGroup', assembly.object_id)
        group.Label = assembly.get_object().Label
        for name,value in [('ComponentContract',json.dumps(assembly.contract().to_dict())),
                           ('AvailableDOFs',assembly.contract().summary())]:
            group.addProperty('App::PropertyString',name)
            setattr(group,name,value)
            group.setEditorMode(name,1)
        def copy_part(obj):
            if hasattr(obj,'Shape') and not obj.Shape.isNull():
                target = static.addObject('Part::Feature',obj.Name)
                target.Label = obj.Label
                target.Shape = obj.Shape.copy()
                for name in ('ComponentContract','AvailableDOFs'):
                    if hasattr(obj,name):
                        target.addProperty('App::PropertyString',name)
                        setattr(target,name,getattr(obj,name))
                        target.setEditorMode(name,1)
                if target.ViewObject:
                    target.ViewObject.ShapeColor = obj.Proxy.object_color
                group.addObject(target)
            for child in obj.Children:
                copy_part(child)
        copy_part(assembly.get_object())
    group = static.addObject('App::DocumentObjectGroup','OpticalPath')
    for i,segment in enumerate(segments,1):
        target = static.addObject('Part::Feature',f'BeamSegment{i}')
        target.Label = f'Beam {i}: {segment.Proxy.distance:g} mm'
        target.Shape = segment.Shape.copy()
        target.addProperty('App::PropertyLength','PathLength')
        target.PathLength = segment.Proxy.distance
        if target.ViewObject:
            # False color: 1550 nm light is infrared.
            target.ViewObject.ShapeColor = (1.,.15,.05)
        group.addObject(target)
    static.recompute()
    if output is None:
        output = Path(__file__).resolve().parents[1]/'artifacts'/'two_mirror_coupling.FCStd'
    output = Path(output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    static.saveAs(str(output))
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewTop()
        Gui.activeDocument().activeView().fitAll()
    print('Verified route: 120 mm -> 100 mm -> 120 mm; saved', output, flush=True)
    return static


if __name__ == '__main__':
    build()
