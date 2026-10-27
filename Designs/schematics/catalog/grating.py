"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace
from PyOpticL.schematic import catalog_parts as catalog

PLACEMENTS = {'G1': (80.0, 0.0, 0.0, 0.0),
 'I1': (63.87554207398466, 78.3581639434728, 0.0, 101.62794830005953)}

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
                                 'direction': (-0.2015557240751915,
                                               0.9794770492934102,
                                               0.0),
                                 'length': 80.00000000000001,
                                 'pass': 'node-2'}},
            'component': 'G1',
            'entry': (80.0, 0.0, 0.0),
            'exit': (80.0, 0.0, 0.0),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'G1'},
 'node-2': {'branches': {'out': {'connection': 'beam-3',
                                 'direction': (-0.2015557240751915,
                                               0.9794770492934102,
                                               0.0),
                                 'length': 79.99999999999999,
                                 'pass': 'node-3'}},
            'component': 'I1',
            'entry': (63.875542073984676, 78.35816394347283, 0.0),
            'exit': (63.875542073984676, 78.35816394347283, 0.0),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'I1'},
 'node-3': {'branches': {},
            'component': None,
            'entry': (47.75108414796936, 156.71632788694563, 0.0),
            'exit': (47.75108414796936, 156.71632788694563, 0.0),
            'internal_length': 0.0,
            'mode': 'receive',
            'reference': 'O1'}}

PATH_LENGTHS = {}
OPEN_SEGMENTS = [((63.875542073984676, 78.35816394347283, 0.0),
  (-0.2015557240751915, 0.9794770492934102, 0.0),
  79.99999999999999)]

def build_layout():
    layout = Layout('Grating and alignment iris')
    objects = {}
    part_0 = Component('G1', catalog.grating(mounted=False, design_wavelength=1550, incidence_angle=49.9, order=1, mirrored=0))
    x, y, z, angle = PLACEMENTS['G1']
    objects['G1'] = layout.add(part_0, position=(x, y, z), rotation=angle)
    part_1 = Component('I1', catalog.iris(aperture_diameter=0.5))
    x, y, z, angle = PLACEMENTS['I1']
    objects['I1'] = layout.add(part_1, position=(x, y, z), rotation=angle)
    beam = layout.add(BeamPath('S1', wavelength=SOURCE["wavelength"],
        polarization=linear_polarization(SOURCE["polarization_angle"]),
        power=SOURCE["power"], waist=SOURCE["waist"],
        final_distance=50, trace_limit=5, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'node-0')
    return layout


if __name__ == "__main__":
    build_layout()
