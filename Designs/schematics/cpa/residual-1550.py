"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace
from PyOpticL.schematic import catalog_parts as catalog

PLACEMENTS = {'SHG_L2': (0, -220, 12.7, 0), 'SHG_M1': (-100, -220, 12.7, -45)}

SOURCE = {'angle': 180,
 'polarization_angle': 0,
 'position': (86.3, -220, 12.7),
 'power': 0.425,
 'waist': 0.2,
 'wavelength': 1550}

EXPECTED_PASSES = {'Residual_1550': {'branches': {},
                   'component': None,
                   'entry': (-213.25521376258732, -219.01257307546803, 12.7),
                   'exit': (-213.25521376258732, -219.01257307546803, 12.7),
                   'internal_length': 0.0,
                   'mode': 'receive',
                   'reference': 'Residual_1550'},
 'SHG_1550_boundary': {'branches': {'out': {'connection': 'e0',
                                            'direction': (-1.0,
                                                          1.2246467991473532e-16,
                                                          0.0),
                                            'length': 86.3,
                                            'pass': 'SHG_L2'}},
                       'component': None,
                       'entry': (86.3, -220, 12.7),
                       'exit': (86.3, -220, 12.7),
                       'internal_length': 0,
                       'mode': 'emit',
                       'reference': 'SHG_1550_boundary'},
 'SHG_L2': {'branches': {'out': {'connection': 'e1',
                                 'direction': (-1.0,
                                               1.2246467991473532e-16,
                                               0.0),
                                 'length': 99.99999999999999,
                                 'pass': 'SHG_M1'}},
            'component': 'SHG_L2',
            'entry': (0.0, -220.0, 12.7),
            'exit': (0.0, -220.0, 12.7),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'SHG_L2'},
 'SHG_M1': {'branches': {'out': {'connection': 'e2',
                                 'direction': (-1.0,
                                               1.2246467991473532e-16,
                                               0.0),
                                 'length': 110.00000000000001,
                                 'pass': 'Residual_1550'}},
            'component': 'SHG_M1',
            'entry': (-99.99999999999999, -220.0, 12.7),
            'exit': (-103.2552137625873, -219.01257307546803, 12.7),
            'internal_length': 3.4016802570830444,
            'mode': 'pass',
            'reference': 'SHG_M1'}}

PATH_LENGTHS = {}
OPEN_SEGMENTS = [((-103.2552137625873, -219.01257307546803, 12.7),
  (-1.0, 1.2246467991473532e-16, 0.0),
  110.00000000000001)]

def build_layout():
    layout = Layout('CPA draft — residual 1550 nm transmitted output')
    objects = {}
    part_0 = Component('SHG_L2', optics.Spherical_Lens(diameter=12.7, focal_length=30.0, thickness=2, mount_definition=catalog.vendor(part='POLARIS-L05G'), mount_offset=(-1.0, 0, 0)))
    x, y, z, angle = PLACEMENTS['SHG_L2']
    objects['SHG_L2'] = layout.add(part_0, position=(x, y, z), rotation=angle)
    part_1 = Component('SHG_M1', catalog.dichroic(mount='MHV-12.7L-R', diameter=12.7, thickness=3, reflect_min=700, reflect_max=850, refractive_index=1.5))
    x, y, z, angle = PLACEMENTS['SHG_M1']
    objects['SHG_M1'] = layout.add(part_1, position=(x, y, z), rotation=angle)
    beam = layout.add(BeamPath('SHG_1550_boundary', wavelength=SOURCE["wavelength"],
        polarization=linear_polarization(SOURCE["polarization_angle"]),
        power=SOURCE["power"], waist=SOURCE["waist"],
        final_distance=80.0, trace_limit=6, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'SHG_1550_boundary')
    return layout


if __name__ == "__main__":
    build_layout()
