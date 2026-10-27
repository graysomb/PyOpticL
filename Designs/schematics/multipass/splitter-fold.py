"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace

PLACEMENTS = {'BS1': (50, 0, 0.0, -3.492883360846785e-13),
 'FM1': (50.00001336934802, 80.00001314947124, 0.0, -44.99999992123106)}

SOURCE = {'angle': 0,
 'polarization_angle': 0,
 'position': (0, 0, 0.0),
 'power': 1,
 'waist': 0.5,
 'wavelength': 635}

EXPECTED_PASSES = {'adaptive-splitter-90-BS1': {'branches': {'reflected': {'connection': 'cfe4c1f5-2314-5dc0-a836-bdbce9513c90/in',
                                                         'direction': (1.2101430968414206e-14,
                                                                       1.0,
                                                                       0.0),
                                                         'length': 79.99999978012416,
                                                         'pass': 'cfe4c1f5-2314-5dc0-a836-bdbce9513c90'},
                                           'transmitted': {'connection': 'adaptive-splitter-90-BS1-O1',
                                                           'direction': (1.0,
                                                                         0.0,
                                                                         0.0),
                                                           'length': 100.0,
                                                           'pass': 'adaptive-splitter-90-O1'}},
                              'component': 'BS1',
                              'entry': (50.0, 0.0, 0.0),
                              'exit': (50.0, 0.0, 0.0),
                              'internal_length': 0.0,
                              'mode': 'pass',
                              'reference': 'BS1'},
 'adaptive-splitter-90-O1': {'branches': {},
                             'component': None,
                             'entry': (150.0, 0.0, 0.0),
                             'exit': (150.0, 0.0, 0.0),
                             'internal_length': 0.0,
                             'mode': 'receive',
                             'reference': 'O1'},
 'adaptive-splitter-90-O2': {'branches': {},
                             'component': None,
                             'entry': (130.0, 80.00000000008951, 0.0),
                             'exit': (130.0, 80.00000000008951, 0.0),
                             'internal_length': 0.0,
                             'mode': 'receive',
                             'reference': 'O2'},
 'adaptive-splitter-90-S1': {'branches': {'out': {'connection': 'adaptive-splitter-90-S1-BS1',
                                                  'direction': (1.0, 0.0, 0.0),
                                                  'length': 50.0,
                                                  'pass': 'adaptive-splitter-90-BS1'}},
                             'component': None,
                             'entry': (0, 0, 0.0),
                             'exit': (0, 0, 0.0),
                             'internal_length': 0,
                             'mode': 'emit',
                             'reference': 'S1'},
 'cfe4c1f5-2314-5dc0-a836-bdbce9513c90': {'branches': {'out': {'connection': 'cfe4c1f5-2314-5dc0-a836-bdbce9513c90/out',
                                                               'direction': (1.0,
                                                                             2.7495670185118115e-09,
                                                                             0.0),
                                                               'length': 79.99999999999903,
                                                               'pass': 'adaptive-splitter-90-O2'}},
                                          'component': 'FM1',
                                          'entry': (50.000000000000966,
                                                    79.99999978012416,
                                                    0.0),
                                          'exit': (50.000000000000966,
                                                   79.99999978012416,
                                                   0.0),
                                          'internal_length': 0.0,
                                          'mode': 'pass',
                                          'reference': 'FM1'}}

PATH_LENGTHS = {'reflected-path': 159.99999978012318}
OPEN_SEGMENTS = [((50.0, 0.0, 0.0), (1.0, 0.0, 0.0), 100.0),
 ((50.000000000000966, 79.99999978012416, 0.0),
  (1.0, 2.7495670185118115e-09, 0.0),
  79.99999999999903)]

def build_layout():
    layout = Layout('adaptive-splitter-90')
    objects = {}
    part_0 = Component('BS1', optics.Beamsplitter_Cube(rotate_cube=False, side_length=12.7, ref_ratio=0.5))
    x, y, z, angle = PLACEMENTS['BS1']
    objects['BS1'] = layout.add(part_0, position=(x, y, z), rotation=angle)
    part_1 = Component('FM1', optics.Circular_Mirror(diameter=12.7, thickness=6))
    x, y, z, angle = PLACEMENTS['FM1']
    objects['FM1'] = layout.add(part_1, position=(x, y, z), rotation=angle)
    beam = layout.add(BeamPath('S1', wavelength=SOURCE["wavelength"],
        polarization=linear_polarization(SOURCE["polarization_angle"]),
        power=SOURCE["power"], waist=SOURCE["waist"],
        final_distance=50, trace_limit=6, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'adaptive-splitter-90-S1')
    return layout


if __name__ == "__main__":
    build_layout()
