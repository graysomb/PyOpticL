"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace
from PyOpticL.schematic import catalog_parts as catalog

PLACEMENTS = {'CP_G1': (320, 0, 12.7, 90),
 'CP_G2': (-522.3502623923326, -173.3379227046648, 12.7, 191.62794830005953),
 'CP_HWP1': (420, -150, 12.7, 180),
 'CP_M1': (320, -150, 12.7, 45),
 'CP_M2': (329.73293821611287, -220, 12.7, 135),
 'CP_Roof': (-522.3502623923326, -13.337922704664805, 12.7, 90),
 'From_EDFA': (500, -150, 12.7, 180),
 'SHG_Crystal': (100, -220, 12.7, 180),
 'SHG_HWP1': (260, -220, 12.7, 180),
 'SHG_L1': (200, -220, 12.7, 180)}

SOURCE = {'angle': 180,
 'polarization_angle': 0,
 'position': (500, -150, 12.7),
 'power': 0.5,
 'waist': 0.2,
 'wavelength': 1550}

EXPECTED_PASSES = {'CP_G1': {'branches': {'out': {'connection': 'e3',
                                'direction': (-0.97947704929341,
                                              -0.20155572407519162,
                                              0.0),
                                'length': 860.0000000000002,
                                'pass': 'CP_G2'}},
           'component': 'CP_G1',
           'entry': (320.0, 0.0, 12.7),
           'exit': (320.0, 0.0, 12.7),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'CP_G1'},
 'CP_G1_return': {'branches': {'out': {'connection': 'e7',
                                       'direction': (1.1102230246251565e-16,
                                                     -1.0,
                                                     0.0),
                                       'length': 231.5582357040363,
                                       'pass': 'CP_M2'}},
                  'component': 'CP_G1',
                  'entry': (329.732938216113, 11.558235704036434, 12.7),
                  'exit': (329.732938216113, 11.558235704036434, 12.7),
                  'internal_length': 0.0,
                  'mode': 'pass',
                  'reference': 'CP_G1'},
 'CP_G2': {'branches': {'out': {'connection': 'e4',
                                'direction': (-2.7755575615628914e-16,
                                              1.0,
                                              0.0),
                                'length': 160.00000000000003,
                                'pass': 'CP_Roof'}},
           'component': 'CP_G2',
           'entry': (-522.3502623923328, -173.33792270466483, 12.7),
           'exit': (-522.3502623923328, -173.33792270466483, 12.7),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'CP_G2'},
 'CP_G2_return': {'branches': {'out': {'connection': 'e6',
                                       'direction': (0.9794770492934101,
                                                     0.20155572407519173,
                                                     0.0),
                                       'length': 860.748295446679,
                                       'pass': 'CP_G1_return'}},
                  'component': 'CP_G2',
                  'entry': (-513.3502623923325, -161.930510231206, 12.7),
                  'exit': (-513.3502623923325, -161.930510231206, 12.7),
                  'internal_length': 0.0,
                  'mode': 'pass',
                  'reference': 'CP_G2'},
 'CP_HWP1': {'branches': {'out': {'connection': 'e1',
                                  'direction': (-1.0,
                                                1.2246467991473532e-16,
                                                0.0),
                                  'length': 100.00000000000001,
                                  'pass': 'CP_M1'}},
             'component': 'CP_HWP1',
             'entry': (420.0, -150.0, 12.7),
             'exit': (420.0, -150.0, 12.7),
             'internal_length': 0.0,
             'mode': 'pass',
             'reference': 'CP_HWP1'},
 'CP_M1': {'branches': {'out': {'connection': 'e2',
                                'direction': (0.0, 0.9999999999999999, 0.0),
                                'length': 150.00000000000003,
                                'pass': 'CP_G1'}},
           'component': 'CP_M1',
           'entry': (320.0, -150.0, 12.7),
           'exit': (320.0, -150.0, 12.7),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'CP_M1'},
 'CP_M2': {'branches': {'out': {'connection': 'e8',
                                'direction': (-1.0, 2.220446049250313e-16, 0.0),
                                'length': 69.73293821611298,
                                'pass': 'SHG_HWP1'}},
           'component': 'CP_M2',
           'entry': (329.732938216113, -219.99999999999986, 12.7),
           'exit': (329.732938216113, -219.99999999999986, 12.7),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'CP_M2'},
 'CP_Roof': {'branches': {'out': {'connection': 'e5',
                                  'direction': (2.718345674301793e-16,
                                                -0.9999999999999998,
                                                0.0),
                                  'length': 148.59258752654122,
                                  'pass': 'CP_G2_return'}},
             'component': 'CP_Roof',
             'entry': (-522.3502623923328, -13.337922704664805, 12.7),
             'exit': (-513.3502623923325, -13.337922704664805, 12.7),
             'internal_length': 25.4,
             'mode': 'pass',
             'reference': 'CP_Roof'},
 'Crystal_1550_exit': {'branches': {},
                       'component': None,
                       'entry': (86.3, -220.00000000000045, 12.7),
                       'exit': (86.3, -220.00000000000045, 12.7),
                       'internal_length': 0.0,
                       'mode': 'receive',
                       'reference': 'Crystal_1550_exit'},
 'From_EDFA': {'branches': {'out': {'connection': 'e0',
                                    'direction': (-1.0,
                                                  1.2246467991473532e-16,
                                                  0.0),
                                    'length': 80.0,
                                    'pass': 'CP_HWP1'}},
               'component': 'From_EDFA',
               'entry': (500, -150, 12.7),
               'exit': (500, -150, 12.7),
               'internal_length': 0,
               'mode': 'emit',
               'reference': 'From_EDFA'},
 'SHG_Crystal': {'branches': {'out': {'connection': 'e11',
                                      'direction': (-1.0,
                                                    -5.4622972811557705e-15,
                                                    0.0),
                                      'length': 13.700000000000003,
                                      'pass': 'Crystal_1550_exit'}},
                 'component': 'SHG_Crystal',
                 'entry': (100.0, -220.00000000000037, 12.7),
                 'exit': (100.0, -220.00000000000037, 12.7),
                 'internal_length': 0.0,
                 'mode': 'pass',
                 'reference': 'SHG_Crystal'},
 'SHG_HWP1': {'branches': {'out': {'connection': 'e9',
                                   'direction': (-1.0,
                                                 2.220446049250313e-16,
                                                 0.0),
                                   'length': 60.0,
                                   'pass': 'SHG_L1'}},
              'component': 'SHG_HWP1',
              'entry': (260.0, -219.99999999999983, 12.7),
              'exit': (260.0, -219.99999999999983, 12.7),
              'internal_length': 0.0,
              'mode': 'pass',
              'reference': 'SHG_HWP1'},
 'SHG_L1': {'branches': {'out': {'connection': 'e10',
                                 'direction': (-1.0,
                                               -5.4622972811557705e-15,
                                               0.0),
                                 'length': 100.0,
                                 'pass': 'SHG_Crystal'}},
            'component': 'SHG_L1',
            'entry': (200.0, -219.99999999999983, 12.7),
            'exit': (200.0, -219.99999999999983, 12.7),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'SHG_L1'}}

PATH_LENGTHS = {}
OPEN_SEGMENTS = [((100.0, -220.00000000000037, 12.7),
  (-1.0, -5.4622972811557705e-15, 0.0),
  13.700000000000003)]

def build_layout():
    layout = Layout('CPA draft — compressor and crystal')
    objects = {}
    part_0 = Component('From_EDFA', catalog.coupling(mount='POLARIS-K05T6', receiving=False))
    x, y, z, angle = PLACEMENTS['From_EDFA']
    objects['From_EDFA'] = layout.add(part_0, position=(x, y, z), rotation=angle)
    part_1 = Component('CP_HWP1', catalog.waveplate(mount='FBR', retardance=0.5, diameter=12.7, fast_axis_angle=0, thickness=1))
    x, y, z, angle = PLACEMENTS['CP_HWP1']
    objects['CP_HWP1'] = layout.add(part_1, position=(x, y, z), rotation=angle)
    part_2 = Component('CP_M1', catalog.mirror(mount='POLARIS-K05VS2', diameter=12.7, thickness=3))
    x, y, z, angle = PLACEMENTS['CP_M1']
    objects['CP_M1'] = layout.add(part_2, position=(x, y, z), rotation=angle)
    part_3 = Component('CP_G1', catalog.grating(mounted=True, design_wavelength=1550, incidence_angle=49.9, order=1, mirrored=0))
    x, y, z, angle = PLACEMENTS['CP_G1']
    objects['CP_G1'] = layout.add(part_3, position=(x, y, z), rotation=angle)
    part_4 = Component('CP_G2', catalog.grating(mounted=True, design_wavelength=1550, incidence_angle=49.9, order=1, mirrored=1))
    x, y, z, angle = PLACEMENTS['CP_G2']
    objects['CP_G2'] = layout.add(part_4, position=(x, y, z), rotation=angle)
    part_5 = Component('CP_Roof', catalog.roof(orientation='horizontal', mounted=True, reverse=False, beam_separation=9.0))
    x, y, z, angle = PLACEMENTS['CP_Roof']
    objects['CP_Roof'] = layout.add(part_5, position=(x, y, z), rotation=angle)
    part_6 = Component('CP_M2', catalog.mirror(mount='POLARIS-K05VS2', diameter=12.7, thickness=3))
    x, y, z, angle = PLACEMENTS['CP_M2']
    objects['CP_M2'] = layout.add(part_6, position=(x, y, z), rotation=angle)
    part_7 = Component('SHG_HWP1', catalog.waveplate(mount='FBR', retardance=0.5, diameter=12.7, fast_axis_angle=0, thickness=1))
    x, y, z, angle = PLACEMENTS['SHG_HWP1']
    objects['SHG_HWP1'] = layout.add(part_7, position=(x, y, z), rotation=angle)
    part_8 = Component('SHG_L1', optics.Spherical_Lens(diameter=12.7, focal_length=30.0, thickness=2, mount_definition=catalog.vendor(part='POLARIS-L05G'), mount_offset=(-1.0, 0, 0)))
    x, y, z, angle = PLACEMENTS['SHG_L1']
    objects['SHG_L1'] = layout.add(part_8, position=(x, y, z), rotation=angle)
    part_9 = Component('SHG_Crystal', catalog.crystal(mounted=True))
    x, y, z, angle = PLACEMENTS['SHG_Crystal']
    objects['SHG_Crystal'] = layout.add(part_9, position=(x, y, z), rotation=angle)
    beam = layout.add(BeamPath('From_EDFA', wavelength=SOURCE["wavelength"],
        polarization=linear_polarization(SOURCE["polarization_angle"]),
        power=SOURCE["power"], waist=SOURCE["waist"],
        final_distance=80.0, trace_limit=17, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'From_EDFA')
    return layout


if __name__ == "__main__":
    build_layout()
