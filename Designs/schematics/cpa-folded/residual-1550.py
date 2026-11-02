"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace
from PyOpticL.schematic import catalog_parts as catalog

PLACEMENTS = {'Pickoff_1550': (6.744786237412683, -139.01257307546803, 9.875, -90),
 'Residual_1550': (-213.25521376258732, -339.012573075468, 9.875, 90),
 'SHG_IR_HWP1': (-213.25521376258732, -249.01257307546803, 9.875, -90),
 'SHG_IR_M1': (-213.25521376258732, -219.01257307546803, 9.875, -45),
 'SHG_IR_PBS1': (-213.25521376258732, -279.012573075468, 9.875, -90),
 'SHG_IR_Pickoff_L1': (6.744786237412683, -169.01257307546803, 9.875, -90),
 'SHG_IR_Pickoff_M1': (6.744786237412683, -279.012573075468, 9.875, 135),
 'SHG_L2': (70.0, -220, 9.875, 0),
 'SHG_M1': (-100, -220, 9.875, -45)}

SOURCE = {'angle': 180,
 'polarization_angle': 0,
 'position': (86.3, -220, 9.875),
 'power': 0.425,
 'waist': 0.2,
 'wavelength': 1550}

EXPECTED_PASSES = {'Pickoff_1550': {'branches': {},
                  'component': 'Pickoff_1550',
                  'entry': (6.74478623741269, -139.01257307546803, 9.875),
                  'exit': (6.74478623741269, -139.01257307546803, 9.875),
                  'internal_length': 0.0,
                  'mode': 'receive',
                  'reference': 'Pickoff_1550'},
 'Residual_1550': {'branches': {},
                   'component': 'Residual_1550',
                   'entry': (-213.2552137625873, -339.012573075468, 9.875),
                   'exit': (-213.2552137625873, -339.012573075468, 9.875),
                   'internal_length': 0.0,
                   'mode': 'receive',
                   'reference': 'Residual_1550'},
 'SHG_1550_boundary': {'branches': {'out': {'connection': 'e0',
                                            'direction': (-1.0,
                                                          1.2246467991473532e-16,
                                                          0.0),
                                            'length': 16.299999999999997,
                                            'pass': 'SHG_L2'}},
                       'component': None,
                       'entry': (86.3, -220, 9.875),
                       'exit': (86.3, -220, 9.875),
                       'internal_length': 0,
                       'mode': 'emit',
                       'reference': 'SHG_1550_boundary'},
 'SHG_IR_HWP1': {'branches': {'out': {'connection': 'e4',
                                      'direction': (2.220446049250313e-16,
                                                    -1.0,
                                                    0.0),
                                      'length': 30.000000000000036,
                                      'pass': 'SHG_IR_PBS1'}},
                 'component': 'SHG_IR_HWP1',
                 'entry': (-213.2552137625873, -249.01257307546803, 9.875),
                 'exit': (-213.2552137625873, -249.01257307546803, 9.875),
                 'internal_length': 0.0,
                 'mode': 'pass',
                 'reference': 'SHG_IR_HWP1'},
 'SHG_IR_M1': {'branches': {'out': {'connection': 'e3',
                                    'direction': (2.220446049250313e-16,
                                                  -1.0,
                                                  0.0),
                                    'length': 30.00000000000003,
                                    'pass': 'SHG_IR_HWP1'}},
               'component': 'SHG_IR_M1',
               'entry': (-213.2552137625873, -219.012573075468, 9.875),
               'exit': (-213.2552137625873, -219.012573075468, 9.875),
               'internal_length': 0.0,
               'mode': 'pass',
               'reference': 'SHG_IR_M1'},
 'SHG_IR_PBS1': {'branches': {'reflected': {'connection': 'e6',
                                            'direction': (1.0, 0.0, 0.0),
                                            'length': 219.99999999999994,
                                            'pass': 'SHG_IR_Pickoff_M1'},
                              'transmitted': {'connection': 'e5',
                                              'direction': (2.220446049250313e-16,
                                                            -1.0,
                                                            0.0),
                                              'length': 59.99999999999994,
                                              'pass': 'Residual_1550'}},
                 'component': 'SHG_IR_PBS1',
                 'entry': (-213.2552137625873, -279.0125730754681, 9.875),
                 'exit': (-213.2552137625873, -279.0125730754681, 9.875),
                 'internal_length': 0.0,
                 'mode': 'pass',
                 'reference': 'SHG_IR_PBS1'},
 'SHG_IR_Pickoff_L1': {'branches': {'out': {'connection': 'e8',
                                            'direction': (3.404683942183813e-16,
                                                          1.0,
                                                          0.0),
                                            'length': 30.0,
                                            'pass': 'Pickoff_1550'}},
                       'component': 'SHG_IR_Pickoff_L1',
                       'entry': (6.744786237412679, -169.01257307546803, 9.875),
                       'exit': (6.744786237412679, -169.01257307546803, 9.875),
                       'internal_length': 0.0,
                       'mode': 'pass',
                       'reference': 'SHG_IR_Pickoff_L1'},
 'SHG_IR_Pickoff_M1': {'branches': {'out': {'connection': 'e7',
                                            'direction': (2.220446049250313e-16,
                                                          1.0,
                                                          0.0),
                                            'length': 110.00000000000006,
                                            'pass': 'SHG_IR_Pickoff_L1'}},
                       'component': 'SHG_IR_Pickoff_M1',
                       'entry': (6.744786237412654, -279.0125730754681, 9.875),
                       'exit': (6.744786237412654, -279.0125730754681, 9.875),
                       'internal_length': 0.0,
                       'mode': 'pass',
                       'reference': 'SHG_IR_Pickoff_M1'},
 'SHG_L2': {'branches': {'out': {'connection': 'e1',
                                 'direction': (-1.0,
                                               1.2246467991473532e-16,
                                               0.0),
                                 'length': 169.99999999999997,
                                 'pass': 'SHG_M1'}},
            'component': 'SHG_L2',
            'entry': (70.0, -220.0, 9.875),
            'exit': (70.0, -220.0, 9.875),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'SHG_L2'},
 'SHG_M1': {'branches': {'out': {'connection': 'e2',
                                 'direction': (-1.0,
                                               1.2246467991473532e-16,
                                               0.0),
                                 'length': 110.0,
                                 'pass': 'SHG_IR_M1'}},
            'component': 'SHG_M1',
            'entry': (-99.99999999999997, -219.99999999999997, 9.875),
            'exit': (-103.25521376258729, -219.012573075468, 9.875),
            'internal_length': 3.4016802570830444,
            'mode': 'pass',
            'reference': 'SHG_M1'}}

PATH_LENGTHS = {}
OPEN_SEGMENTS = []

def build_layout():
    layout = Layout('CPA folded draft — residual 1550 nm with adjustable pickoff')
    objects = {}
    part_0 = Component('SHG_L2', optics.Spherical_Lens(diameter=12.7, focal_length=30.0, thickness=2, mount_definition=catalog.vendor(part='POLARIS-L05G'), mount_offset=(-1.0, 0, 0)))
    x, y, z, angle = PLACEMENTS['SHG_L2']
    objects['SHG_L2'] = layout.add(part_0, position=(x, y, z), rotation=angle)
    part_1 = Component('SHG_M1', catalog.dichroic(mount='MHV-12.7L-R', diameter=12.7, thickness=3, reflect_min=700, reflect_max=850, refractive_index=1.5))
    x, y, z, angle = PLACEMENTS['SHG_M1']
    objects['SHG_M1'] = layout.add(part_1, position=(x, y, z), rotation=angle)
    part_2 = Component('SHG_IR_M1', catalog.mirror(mount='POLARIS-K05VS2', diameter=12.7, thickness=3))
    x, y, z, angle = PLACEMENTS['SHG_IR_M1']
    objects['SHG_IR_M1'] = layout.add(part_2, position=(x, y, z), rotation=angle)
    part_3 = Component('Residual_1550', catalog.coupling(mount='POLARIS-K05T6', receiving=True))
    x, y, z, angle = PLACEMENTS['Residual_1550']
    objects['Residual_1550'] = layout.add(part_3, position=(x, y, z), rotation=angle)
    part_4 = Component('SHG_IR_HWP1', catalog.waveplate(mount='FBR', retardance=0.5, diameter=12.7, fast_axis_angle=22.5, thickness=1))
    x, y, z, angle = PLACEMENTS['SHG_IR_HWP1']
    objects['SHG_IR_HWP1'] = layout.add(part_4, position=(x, y, z), rotation=angle)
    part_5 = Component('SHG_IR_PBS1', catalog.pbs(rotate_cube=False, side_length=12.7, ref_polarization=0))
    x, y, z, angle = PLACEMENTS['SHG_IR_PBS1']
    objects['SHG_IR_PBS1'] = layout.add(part_5, position=(x, y, z), rotation=angle)
    part_6 = Component('SHG_IR_Pickoff_M1', catalog.mirror(mount='POLARIS-K05VS2', diameter=12.7, thickness=3))
    x, y, z, angle = PLACEMENTS['SHG_IR_Pickoff_M1']
    objects['SHG_IR_Pickoff_M1'] = layout.add(part_6, position=(x, y, z), rotation=angle)
    part_7 = Component('SHG_IR_Pickoff_L1', optics.Spherical_Lens(diameter=12.7, focal_length=30.0, thickness=2, mount_definition=catalog.vendor(part='POLARIS-L05G'), mount_offset=(-1.0, 0, 0)))
    x, y, z, angle = PLACEMENTS['SHG_IR_Pickoff_L1']
    objects['SHG_IR_Pickoff_L1'] = layout.add(part_7, position=(x, y, z), rotation=angle)
    part_8 = Component('Pickoff_1550', catalog.detector(mounted=True, optical_height=25.4))
    x, y, z, angle = PLACEMENTS['Pickoff_1550']
    objects['Pickoff_1550'] = layout.add(part_8, position=(x, y, z), rotation=angle)
    beam = layout.add(BeamPath('SHG_1550_boundary', wavelength=SOURCE["wavelength"],
        polarization=linear_polarization(SOURCE["polarization_angle"]),
        power=SOURCE["power"], waist=SOURCE["waist"],
        final_distance=80.0, trace_limit=12, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'SHG_1550_boundary')
    return layout


if __name__ == "__main__":
    build_layout()
