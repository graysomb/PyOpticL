"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace

PLACEMENTS = {'FM1': (88.54627417392314, 26.113743763708477, 0.0, 524.3219917070566),
 'FM2': (33.07428479593884, 46.36312253043163, 0.0, 1766.7474771500015)}

SOURCE = {'angle': 0,
 'polarization_angle': 0,
 'position': (20, 20, 0.0),
 'power': 1,
 'waist': 0.5,
 'wavelength': 635}

EXPECTED_PASSES = {'137c56da-2be9-5f02-8cfa-9d7c2714714b': {'branches': {'out': {'connection': '137c56da-2be9-5f02-8cfa-9d7c2714714b/out',
                                                               'direction': (-0.8539505015929822,
                                                                             0.5203542455184679,
                                                                             0.0),
                                                               'length': 59.44237464082634,
                                                               'pass': 'e685273e-dff9-58f7-b76a-05b5bc9a1b9a'}},
                                          'component': 'FM1',
                                          'entry': (86.83031006337959,
                                                    20.0,
                                                    0.0),
                                          'exit': (86.83031006337959,
                                                   20.0,
                                                   0.0),
                                          'internal_length': 0.0,
                                          'mode': 'pass',
                                          'reference': 'FM1'},
 'e685273e-dff9-58f7-b76a-05b5bc9a1b9a': {'branches': {'out': {'connection': 'e685273e-dff9-58f7-b76a-05b5bc9a1b9a/out',
                                                               'direction': (0.8176573747478022,
                                                                             -0.5757051480754117,
                                                                             0.0),
                                                               'length': 53.727315295811444,
                                                               'pass': 'output'}},
                                          'component': 'FM2',
                                          'entry': (36.06946442296797,
                                                    50.9310920080533,
                                                    0.0),
                                          'exit': (36.06946442296797,
                                                   50.9310920080533,
                                                   0.0),
                                          'internal_length': 0.0,
                                          'mode': 'pass',
                                          'reference': 'FM2'},
 'output': {'branches': {},
            'component': None,
            'entry': (79.99999999998859, 19.99999999998384, 0.0),
            'exit': (79.99999999998859, 19.99999999998384, 0.0),
            'internal_length': 0.0,
            'mode': 'receive',
            'reference': 'O1'},
 'source': {'branches': {'out': {'connection': '137c56da-2be9-5f02-8cfa-9d7c2714714b/in',
                                 'direction': (1.0, 0.0, 0.0),
                                 'length': 66.83031006337959,
                                 'pass': '137c56da-2be9-5f02-8cfa-9d7c2714714b'}},
            'component': None,
            'entry': (20, 20, 0.0),
            'exit': (20, 20, 0.0),
            'internal_length': 0,
            'mode': 'emit',
            'reference': 'S1'}}

PATH_LENGTHS = {'total': 180.00000000001737}
OPEN_SEGMENTS = [((36.06946442296797, 50.9310920080533, 0.0),
  (0.8176573747478022, -0.5757051480754117, 0.0),
  53.727315295811444)]

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
