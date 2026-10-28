"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace
from PyOpticL.schematic import catalog_parts as catalog

PLACEMENTS = {'XTAL1': (80.0, 0.0, 0.0, 0.0)}

SOURCE = {'angle': 0,
 'polarization_angle': 0,
 'position': (0, 0, 0.0),
 'power': 0.01,
 'waist': 0.1,
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
                                 'direction': (1.0, 0.0, 0.0),
                                 'length': 80.0,
                                 'pass': 'node-2'}},
            'component': 'XTAL1',
            'entry': (80.0, 0.0, 0.0),
            'exit': (80.0, 0.0, 0.0),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'XTAL1'},
 'node-2': {'branches': {},
            'component': None,
            'entry': (160.0, 0.0, 0.0),
            'exit': (160.0, 0.0, 0.0),
            'internal_length': 0.0,
            'mode': 'receive',
            'reference': 'O1'}}

PATH_LENGTHS = {}
OPEN_SEGMENTS = [((80.0, 0.0, 0.0), (1.0, 0.0, 0.0), 80.0)]

def build_layout():
    layout = Layout('Crystal holder on bracket')
    objects = {}
    part_0 = Component('XTAL1', catalog.crystal(mounted=True))
    x, y, z, angle = PLACEMENTS['XTAL1']
    objects['XTAL1'] = layout.add(part_0, position=(x, y, z), rotation=angle)
    beam = layout.add(BeamPath('S1', wavelength=SOURCE["wavelength"],
        polarization=linear_polarization(SOURCE["polarization_angle"]),
        power=SOURCE["power"], waist=SOURCE["waist"],
        final_distance=50, trace_limit=4, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'node-0')
    return layout


if __name__ == "__main__":
    build_layout()
