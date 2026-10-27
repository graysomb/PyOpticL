"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace
from PyOpticL.schematic import catalog_parts as catalog

PLACEMENTS = {'FI1': (0, 0, 0.0, 0),
 'FO1': (160.0, 240.0, 0.0, 270.0),
 'HWP1': (80.0, 0.0, 0.0, 0.0),
 'L1': (160.0, 80.0, 0.0, 90.0),
 'M1': (160.0, 0.0, 0.0, 135.0),
 'SL1': (160.0, 160.0, 0.0, 90.0)}

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
            'component': 'FI1',
            'entry': (0, 0, 0.0),
            'exit': (0, 0, 0.0),
            'internal_length': 0,
            'mode': 'emit',
            'reference': 'FI1'},
 'node-1': {'branches': {'out': {'connection': 'beam-2',
                                 'direction': (1.0, 0.0, 0.0),
                                 'length': 80.0,
                                 'pass': 'node-2'}},
            'component': 'HWP1',
            'entry': (80.0, 0.0, 0.0),
            'exit': (80.0, 0.0, 0.0),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'HWP1'},
 'node-2': {'branches': {'out': {'connection': 'beam-3',
                                 'direction': (2.220446049250313e-16, 1.0, 0.0),
                                 'length': 80.0,
                                 'pass': 'node-3'}},
            'component': 'M1',
            'entry': (160.0, 0.0, 0.0),
            'exit': (160.0, 0.0, 0.0),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'M1'},
 'node-3': {'branches': {'out': {'connection': 'beam-4',
                                 'direction': (2.220446049250313e-16, 1.0, 0.0),
                                 'length': 80.0,
                                 'pass': 'node-4'}},
            'component': 'L1',
            'entry': (160.00000000000003, 80.0, 0.0),
            'exit': (160.00000000000003, 80.0, 0.0),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'L1'},
 'node-4': {'branches': {'out': {'connection': 'beam-5',
                                 'direction': (2.220446049250313e-16, 1.0, 0.0),
                                 'length': 80.0,
                                 'pass': 'node-5'}},
            'component': 'SL1',
            'entry': (160.00000000000006, 160.0, 0.0),
            'exit': (160.00000000000006, 160.0, 0.0),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'SL1'},
 'node-5': {'branches': {},
            'component': 'FO1',
            'entry': (160.00000000000009, 240.0, 0.0),
            'exit': (160.00000000000009, 240.0, 0.0),
            'internal_length': 0.0,
            'mode': 'receive',
            'reference': 'FO1'}}

PATH_LENGTHS = {}
OPEN_SEGMENTS = []

def build_layout():
    layout = Layout('Lab mount presets')
    objects = {}
    part_0 = Component('FI1', catalog.coupling(mount='POLARIS-K05T6', receiving=False))
    x, y, z, angle = PLACEMENTS['FI1']
    objects['FI1'] = layout.add(part_0, position=(x, y, z), rotation=angle)
    part_1 = Component('HWP1', catalog.waveplate(mount='ELL16', retardance=0.5, diameter=12.7, fast_axis_angle=0, thickness=1))
    x, y, z, angle = PLACEMENTS['HWP1']
    objects['HWP1'] = layout.add(part_1, position=(x, y, z), rotation=angle)
    part_2 = Component('M1', catalog.mirror(mount='POLARIS-K1VS2', diameter=25.4, thickness=3))
    x, y, z, angle = PLACEMENTS['M1']
    objects['M1'] = layout.add(part_2, position=(x, y, z), rotation=angle)
    part_3 = Component('L1', optics.Spherical_Lens(diameter=12.7, focal_length=50, thickness=2, mount_definition=catalog.vendor(part='POLARIS-L05G'), mount_offset=(-1.0, 0, 0)))
    x, y, z, angle = PLACEMENTS['L1']
    objects['L1'] = layout.add(part_3, position=(x, y, z), rotation=angle)
    part_4 = Component('SL1', catalog.slit(slit_width=1))
    x, y, z, angle = PLACEMENTS['SL1']
    objects['SL1'] = layout.add(part_4, position=(x, y, z), rotation=angle)
    part_5 = Component('FO1', catalog.coupling(mount='KA05TA', receiving=True))
    x, y, z, angle = PLACEMENTS['FO1']
    objects['FO1'] = layout.add(part_5, position=(x, y, z), rotation=angle)
    beam = layout.add(BeamPath('FI1', wavelength=SOURCE["wavelength"],
        polarization=linear_polarization(SOURCE["polarization_angle"]),
        power=SOURCE["power"], waist=SOURCE["waist"],
        final_distance=50, trace_limit=7, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'node-0')
    return layout


if __name__ == "__main__":
    build_layout()
