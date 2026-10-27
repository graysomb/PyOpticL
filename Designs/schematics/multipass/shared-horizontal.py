"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace
from PyOpticL.schematic import catalog_parts as catalog

PLACEMENTS = {'L1': (50.0, 0.0, 0.0, 0.0),
 'M1': (25.0, -3.75, 0.0, -45.0),
 'QWP1': (100.0, 0.0, 0.0, 0.0),
 'RM1': (200.0, 0.0, 0.0, 0.0)}

SOURCE = {'angle': 0.0,
 'polarization_angle': 0,
 'position': (0.0, 0.0, 0.0),
 'power': 1,
 'waist': 0.5,
 'wavelength': 635}

EXPECTED_PASSES = {'lens-return': {'branches': {'out': {'connection': 'beam-5',
                                      'direction': (-0.9987523388778446,
                                                    0.049937616943892246,
                                                    0.0),
                                      'length': 25.03123049312598,
                                      'pass': 'part-4'}},
                 'component': 'L1',
                 'entry': (50.0, -5.000000000000001, 0.0),
                 'exit': (50.0, -5.000000000000001, 0.0),
                 'internal_length': 0.0,
                 'mode': 'pass',
                 'reference': 'L1'},
 'part-0': {'branches': {'out': {'connection': 'beam-0',
                                 'direction': (1.0, 0.0, 0.0),
                                 'length': 50.0,
                                 'pass': 'part-1'}},
            'component': None,
            'entry': (0.0, 0.0, 0.0),
            'exit': (0.0, 0.0, 0.0),
            'internal_length': 0,
            'mode': 'emit',
            'reference': 'S1'},
 'part-1': {'branches': {'out': {'connection': 'beam-1',
                                 'direction': (1.0, 0.0, 0.0),
                                 'length': 50.0,
                                 'pass': 'part-2'}},
            'component': 'L1',
            'entry': (50.0, 0.0, 0.0),
            'exit': (50.0, 0.0, 0.0),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'L1'},
 'part-2': {'branches': {'out': {'connection': 'beam-2',
                                 'direction': (1.0, 0.0, 0.0),
                                 'length': 100.0,
                                 'pass': 'part-3'}},
            'component': 'QWP1',
            'entry': (100.0, 0.0, 0.0),
            'exit': (100.0, 0.0, 0.0),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'QWP1'},
 'part-3': {'branches': {'out': {'connection': 'beam-3',
                                 'direction': (-0.9999999999999996, 0.0, 0.0),
                                 'length': 100.00000000000004,
                                 'pass': 'plate-return'}},
            'component': 'RM1',
            'entry': (200.0, 0.0, 0.0),
            'exit': (200.0, -5.000000000000001, 0.0),
            'internal_length': 25.4,
            'mode': 'pass',
            'reference': 'RM1'},
 'part-4': {'branches': {'out': {'connection': 'beam-6',
                                 'direction': (0.04993761694389243,
                                               -0.9987523388778446,
                                               0.0),
                                 'length': 49.999999999999986,
                                 'pass': 'part-5'}},
            'component': 'M1',
            'entry': (25.0, -3.750000000000001, 0.0),
            'exit': (25.0, -3.750000000000001, 0.0),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'M1'},
 'part-5': {'branches': {},
            'component': None,
            'entry': (27.49688084719462, -53.687616943892216, 0.0),
            'exit': (27.49688084719462, -53.687616943892216, 0.0),
            'internal_length': 0.0,
            'mode': 'receive',
            'reference': 'O1'},
 'plate-return': {'branches': {'out': {'connection': 'beam-4',
                                       'direction': (-0.9999999999999996,
                                                     0.0,
                                                     0.0),
                                       'length': 50.00000000000002,
                                       'pass': 'lens-return'}},
                  'component': 'QWP1',
                  'entry': (100.0, -5.000000000000001, 0.0),
                  'exit': (100.0, -5.000000000000001, 0.0),
                  'internal_length': 0.0,
                  'mode': 'pass',
                  'reference': 'QWP1'}}

PATH_LENGTHS = {}
OPEN_SEGMENTS = [((25.0, -3.750000000000001, 0.0),
  (0.04993761694389243, -0.9987523388778446, 0.0),
  49.999999999999986)]

def build_layout():
    layout = Layout('Horizontal return')
    objects = {}
    part_0 = Component('L1', optics.Spherical_Lens(diameter=12.7, focal_length=100.0, thickness=2))
    x, y, z, angle = PLACEMENTS['L1']
    objects['L1'] = layout.add(part_0, position=(x, y, z), rotation=angle)
    part_1 = Component('QWP1', optics.Circular_Waveplate(retardance=0.25, diameter=12.7, fast_axis_angle=0, thickness=1))
    x, y, z, angle = PLACEMENTS['QWP1']
    objects['QWP1'] = layout.add(part_1, position=(x, y, z), rotation=angle)
    part_2 = Component('RM1', catalog.roof(orientation='horizontal', mounted=False, reverse=False, beam_separation=5.0))
    x, y, z, angle = PLACEMENTS['RM1']
    objects['RM1'] = layout.add(part_2, position=(x, y, z), rotation=angle)
    part_3 = Component('M1', optics.Circular_Mirror(diameter=2, thickness=0.5))
    x, y, z, angle = PLACEMENTS['M1']
    objects['M1'] = layout.add(part_3, position=(x, y, z), rotation=angle)
    beam = layout.add(BeamPath('S1', wavelength=SOURCE["wavelength"],
        polarization=linear_polarization(SOURCE["polarization_angle"]),
        power=SOURCE["power"], waist=SOURCE["waist"],
        final_distance=50, trace_limit=12, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'part-0')
    return layout


if __name__ == "__main__":
    build_layout()
