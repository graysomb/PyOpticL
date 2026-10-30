"""Build a Newport 818-BB-30, removable bracket and drilled baseplate."""

import json
from pathlib import Path
import FreeCAD as App
import Part

from PyOpticL import lab_catalog as catalog
from PyOpticL.beam_path import BeamPath
from PyOpticL.layout import Layout
from PyOpticL.schematic.cad import add_baseplate


def build(output=None, optical_height=25.4):
    output = Path(output or Path(__file__).resolve().parents[1] / 'artifacts/newport-818-bb-30.FCStd')
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = App.newDocument('Newport818BB30')
    root = Layout('Newport 818-BB-30 detector and bracket')
    detector = root.add(catalog.create('photodetector', 'PD1', optical_height=optical_height),
                        (0, 0, optical_height), 0)
    beam = root.add(BeamPath('1550 nm alignment ray', wavelength=1550, waist=.02, power=.001,
                             bound_parent=root), (60, 0, optical_height), 180)
    root.recompute()
    if beam.get_object().BeamSegments[0].EndObject != detector.get_object():
        raise RuntimeError('Nominal alignment ray did not reach detector')
    plate = add_baseplate(root, thickness=12.7, margin=10)
    root.recompute()
    bracket = detector.get_object().Children[1]
    document.saveAs(str(output))
    Part.export([bracket], str(output.with_name(output.stem + '-bracket.step')))
    report = {'optical_height_mm': optical_height,
              'machining': json.loads(plate.get_object().MachiningPlan),
              'detector_contract': detector.get_object().Children[0].Proxy.contract().to_dict(),
              'bracket_contract': bracket.Proxy.contract().to_dict(),
              'bracket_step_placement': {'position_mm': list(bracket.Placement.Base),
                                         'rotation_xyz_deg': list(bracket.Placement.Rotation.toEulerAngles('XYZ'))},
              'note': 'Nominal 2 mm detector-screw insertion; physically confirm usable thread depth/retention.'}
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    return document, root


if __name__ == '__main__':
    build()
