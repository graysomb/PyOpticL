"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace
from PyOpticL.schematic import catalog_parts as catalog

PLACEMENTS = {'RM1': (80.0, 0.0, 0.0, 0.0)}

SOURCE = {'angle': 0,
 'polarization_angle': 0,
 'position': (0, 0, 0.0),
 'power': 1,
 'waist': 0.5,
 'wavelength': 1550}

EXPECTED_PASSES = {'node-0': {'branches': {'out': {'connection': 'beam-1',
                                 'direction': (1.0, 0.0, 0.0),
                                 'length': 80.0,
                                 'pass': 'node-1'}},
            'component': None,
            'entry': (0, 0, 0.0),
            'exit': (0, 0, 0.0),
            'internal_length': 0,
            'mode': 'emit',
            'reference': 'S1'},
 'node-1': {'branches': {'out': {'connection': 'beam-2',
                                 'direction': (-0.9999999999999996, 0.0, 0.0),
                                 'length': 59.99999999999997,
                                 'pass': 'node-2'}},
            'component': 'RM1',
            'entry': (80.0, 0.0, 0.0),
            'exit': (80.0, -12.699999999999996, 0.0),
            'internal_length': 25.4,
            'mode': 'pass',
            'reference': 'RM1'},
 'node-2': {'branches': {},
            'component': None,
            'entry': (20.000000000000057, -12.699999999999996, 0.0),
            'exit': (20.000000000000057, -12.699999999999996, 0.0),
            'internal_length': 0.0,
            'mode': 'receive',
            'reference': 'O1'}}

PATH_LENGTHS = {'total': 165.39999999999998}
OPEN_SEGMENTS = [((80.0, -12.699999999999996, 0.0),
  (-0.9999999999999996, 0.0, 0.0),
  59.99999999999997)]

def build_layout():
    layout = Layout('Roof return with total air-path constraint')
    objects = {}
    part_0 = Component('RM1', catalog.roof(orientation='horizontal', mounted=False, reverse=False, beam_separation=12.7))
    x, y, z, angle = PLACEMENTS['RM1']
    objects['RM1'] = layout.add(part_0, position=(x, y, z), rotation=angle)
    beam = layout.add(BeamPath('S1', wavelength=SOURCE["wavelength"],
        polarization=linear_polarization(SOURCE["polarization_angle"]),
        power=SOURCE["power"], waist=SOURCE["waist"],
        final_distance=50, trace_limit=7, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'node-0')
    return layout


if __name__ == "__main__":
    build_layout()
