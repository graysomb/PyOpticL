"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace

PLACEMENTS = {'FM1': (98.09836945355597, 80.73205837422056, 0.0, 609.0951416280925),
 'FM2': (69.49999690355405, 20.000000000001513, 0.0, 842.392263522195)}

SOURCE = {'angle': 0,
 'polarization_angle': 0,
 'position': (20, 20, 0.0),
 'power': 1,
 'waist': 0.5,
 'wavelength': 1550}

EXPECTED_PASSES = {'a7b39d31-4852-5bf4-b985-7d881c5072ec': {'branches': {'out': {'connection': 'a7b39d31-4852-5bf4-b985-7d881c5072ec/out',
                                                               'direction': (-0.28559208823134663,
                                                                             -0.9583512712673043,
                                                                             0.0),
                                                               'length': 63.371396475437805,
                                                               'pass': 'output'}},
                                          'component': 'FM1',
                                          'entry': (98.09836945355697,
                                                    80.73205837422019,
                                                    0.0),
                                          'exit': (98.09836945355697,
                                                   80.73205837422019,
                                                   0.0),
                                          'internal_length': 0.0,
                                          'mode': 'pass',
                                          'reference': 'FM1'},
 'e685273e-dff9-58f7-b76a-05b5bc9a1b9a': {'branches': {'out': {'connection': 'a7b39d31-4852-5bf4-b985-7d881c5072ec/in',
                                                               'direction': (0.42602362821953266,
                                                                             0.9047120360637773,
                                                                             0.0),
                                                               'length': 67.12860662101207,
                                                               'pass': 'a7b39d31-4852-5bf4-b985-7d881c5072ec'}},
                                          'component': 'FM2',
                                          'entry': (69.49999690355166,
                                                    20.0,
                                                    0.0),
                                          'exit': (69.49999690355166,
                                                   20.0,
                                                   0.0),
                                          'internal_length': 0.0,
                                          'mode': 'pass',
                                          'reference': 'FM2'},
 'output': {'branches': {},
            'component': None,
            'entry': (80.00000000000009, 20.0, 0.0),
            'exit': (80.00000000000009, 20.0, 0.0),
            'internal_length': 0.0,
            'mode': 'receive',
            'reference': 'O1'},
 'source': {'branches': {'out': {'connection': 'e685273e-dff9-58f7-b76a-05b5bc9a1b9a/in',
                                 'direction': (1.0, 0.0, 0.0),
                                 'length': 49.49999690355166,
                                 'pass': 'e685273e-dff9-58f7-b76a-05b5bc9a1b9a'}},
            'component': None,
            'entry': (20, 20, 0.0),
            'exit': (20, 20, 0.0),
            'internal_length': 0,
            'mode': 'emit',
            'reference': 'S1'}}

PATH_LENGTHS = {'total': 180.00000000000153}
OPEN_SEGMENTS = [((98.09836945355697, 80.73205837422019, 0.0),
  (-0.28559208823134663, -0.9583512712673043, 0.0),
  63.371396475437805)]

def build_layout():
    layout = Layout('Two-fold physical path')
    objects = {}
    part_0 = Component('FM1', optics.Circular_Mirror(diameter=12.7, thickness=6))
    x, y, z, angle = PLACEMENTS['FM1']
    objects['FM1'] = layout.add(part_0, position=(x, y, z), rotation=angle)
    part_1 = Component('FM2', optics.Circular_Mirror(diameter=12.7, thickness=6))
    x, y, z, angle = PLACEMENTS['FM2']
    objects['FM2'] = layout.add(part_1, position=(x, y, z), rotation=angle)
    beam = layout.add(BeamPath('S1', wavelength=SOURCE["wavelength"],
        polarization=linear_polarization(SOURCE["polarization_angle"]),
        power=SOURCE["power"], waist=SOURCE["waist"],
        final_distance=50, trace_limit=5, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'source')
    return layout


if __name__ == "__main__":
    build_layout()
