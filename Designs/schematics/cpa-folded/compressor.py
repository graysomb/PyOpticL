"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace
from PyOpticL.schematic import catalog_parts as catalog

PLACEMENTS = {'CP_G1': (315.0402480508373, -5.889894787071917, 12.7, 90),
 'CP_HRoof': (-88.73577267013997,
              -84.10920365657746,
              12.7,
              -168.37205169994047),
 'CP_HWP1': (420, -300.0, 15.524999999999999, 180),
 'CP_M1': (320, -300.0, 15.524999999999999, 45),
 'CP_Pickoff': (320, -220.0, 9.875, 135),
 'CP_VRoof': (305.0804961016746, -100.0, 15.524999999999999, -90),
 'From_EDFA': (500, -300.0, 15.524999999999999, 180),
 'SHG_Crystal': (100, -220, 9.875, 180),
 'SHG_HWP1': (260, -220, 9.875, 180),
 'SHG_L1': (200, -220, 9.875, 180)}

SOURCE = {'angle': 180,
 'polarization_angle': 0,
 'position': (500, -300.0, 15.524999999999999),
 'power': 0.5,
 'waist': 0.2,
 'wavelength': 1550}

EXPECTED_PASSES = {'CP_G1': {'branches': {'out': {'connection': 'e3',
                                'direction': (-0.97947704929341,
                                              -0.20155572407519162,
                                              0.0),
                                'length': 417.30000000000007,
                                'pass': 'CP_HRoof'}},
           'component': 'CP_G1',
           'entry': (320.0, 0.0, 15.524999999999999),
           'exit': (320.0, 0.0, 15.524999999999999),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'CP_G1'},
 'CP_G1_2': {'branches': {'out': {'connection': 'e5',
                                  'direction': (1.1102230246251565e-16,
                                                -1.0,
                                                0.0),
                                  'length': 88.22021042585612,
                                  'pass': 'CP_VRoof'}},
             'component': 'CP_G1',
             'entry': (310.0804961016746,
                       -11.779789574143877,
                       15.524999999999999),
             'exit': (310.0804961016746,
                      -11.779789574143877,
                      15.524999999999999),
             'internal_length': 0.0,
             'mode': 'pass',
             'reference': 'CP_G1'},
 'CP_G1_3': {'branches': {'out': {'connection': 'e7',
                                  'direction': (-0.97947704929341,
                                                -0.20155572407519162,
                                                0.0),
                                  'length': 405.2097895741439,
                                  'pass': 'CP_HRoof_return'}},
             'component': 'CP_G1',
             'entry': (310.0804961016746,
                       -11.779789574143848,
                       9.874999999999996),
             'exit': (310.0804961016746,
                      -11.779789574143848,
                      9.874999999999996),
             'internal_length': 0.0,
             'mode': 'pass',
             'reference': 'CP_G1'},
 'CP_G1_4': {'branches': {'out': {'connection': 'e9',
                                  'direction': (1.1102230246251565e-16,
                                                -1.0,
                                                0.0),
                                  'length': 219.99999999999997,
                                  'pass': 'CP_Pickoff'}},
             'component': 'CP_G1',
             'entry': (319.99999999999994,
                       -4.263256414560601e-14,
                       9.874999999999996),
             'exit': (319.99999999999994,
                      -4.263256414560601e-14,
                      9.874999999999996),
             'internal_length': 0.0,
             'mode': 'pass',
             'reference': 'CP_G1'},
 'CP_HRoof': {'branches': {'out': {'connection': 'e4',
                                   'direction': (0.9794770492934096,
                                                 0.20155572407519168,
                                                 0.0),
                                   'length': 405.20978957414394,
                                   'pass': 'CP_G1_2'}},
              'component': 'CP_HRoof',
              'entry': (-88.73577267014002,
                        -84.10920365657748,
                        15.524999999999999),
              'exit': (-86.81319293521129,
                       -93.45214211411651,
                       15.524999999999999),
              'internal_length': 25.39999999999994,
              'mode': 'pass',
              'reference': 'CP_HRoof'},
 'CP_HRoof_return': {'branches': {'out': {'connection': 'e8',
                                          'direction': (0.9794770492934096,
                                                        0.20155572407519168,
                                                        0.0),
                                          'length': 417.30000000000007,
                                          'pass': 'CP_G1_4'}},
                     'component': 'CP_HRoof',
                     'entry': (-86.81319293521142,
                               -93.45214211411646,
                               9.874999999999996),
                     'exit': (-88.73577267013995,
                              -84.10920365657755,
                              9.874999999999996),
                     'internal_length': 25.399999999999892,
                     'mode': 'pass',
                     'reference': 'CP_HRoof'},
 'CP_HWP1': {'branches': {'out': {'connection': 'e1',
                                  'direction': (-1.0,
                                                1.2246467991473532e-16,
                                                0.0),
                                  'length': 100.00000000000001,
                                  'pass': 'CP_M1'}},
             'component': 'CP_HWP1',
             'entry': (420.0, -300.0, 15.524999999999999),
             'exit': (420.0, -300.0, 15.524999999999999),
             'internal_length': 0.0,
             'mode': 'pass',
             'reference': 'CP_HWP1'},
 'CP_M1': {'branches': {'out': {'connection': 'e2',
                                'direction': (0.0, 0.9999999999999999, 0.0),
                                'length': 300.00000000000006,
                                'pass': 'CP_G1'}},
           'component': 'CP_M1',
           'entry': (320.0, -300.0, 15.524999999999999),
           'exit': (320.0, -300.0, 15.524999999999999),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'CP_M1'},
 'CP_Pickoff': {'branches': {'out': {'connection': 'e10',
                                     'direction': (-1.0,
                                                   2.220446049250313e-16,
                                                   0.0),
                                     'length': 59.99999999999994,
                                     'pass': 'SHG_HWP1'}},
                'component': 'CP_Pickoff',
                'entry': (319.99999999999994, -220.0, 9.874999999999996),
                'exit': (319.99999999999994, -220.0, 9.874999999999996),
                'internal_length': 0.0,
                'mode': 'pass',
                'reference': 'CP_Pickoff'},
 'CP_VRoof': {'branches': {'out': {'connection': 'e6',
                                   'direction': (-1.1442377452219642e-17,
                                                 0.9999999999999996,
                                                 -0.0),
                                   'length': 88.2202104258562,
                                   'pass': 'CP_G1_3'}},
              'component': 'CP_VRoof',
              'entry': (310.0804961016746, -100.0, 15.524999999999999),
              'exit': (310.0804961016746, -100.0, 9.874999999999996),
              'internal_length': 25.4,
              'mode': 'pass',
              'reference': 'CP_VRoof'},
 'Crystal_1550_exit': {'branches': {},
                       'component': None,
                       'entry': (86.3, -219.99999999999997, 9.87500000000001),
                       'exit': (86.3, -219.99999999999997, 9.87500000000001),
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
               'entry': (500, -300.0, 15.524999999999999),
               'exit': (500, -300.0, 15.524999999999999),
               'internal_length': 0,
               'mode': 'emit',
               'reference': 'From_EDFA'},
 'SHG_Crystal': {'branches': {'out': {'connection': 'e13',
                                      'direction': (-1.0,
                                                    2.220446049250313e-16,
                                                    1.1842378929335003e-16),
                                      'length': 13.700000000000003,
                                      'pass': 'Crystal_1550_exit'}},
                 'component': 'SHG_Crystal',
                 'entry': (100.0, -219.99999999999997, 9.875000000000009),
                 'exit': (100.0, -219.99999999999997, 9.875000000000009),
                 'internal_length': 0.0,
                 'mode': 'pass',
                 'reference': 'SHG_Crystal'},
 'SHG_HWP1': {'branches': {'out': {'connection': 'e11',
                                   'direction': (-1.0,
                                                 2.220446049250313e-16,
                                                 0.0),
                                   'length': 60.0,
                                   'pass': 'SHG_L1'}},
              'component': 'SHG_HWP1',
              'entry': (260.0, -220.0, 9.874999999999996),
              'exit': (260.0, -220.0, 9.874999999999996),
              'internal_length': 0.0,
              'mode': 'pass',
              'reference': 'SHG_HWP1'},
 'SHG_L1': {'branches': {'out': {'connection': 'e12',
                                 'direction': (-1.0,
                                               2.220446049250313e-16,
                                               1.1842378929335003e-16),
                                 'length': 100.0,
                                 'pass': 'SHG_Crystal'}},
            'component': 'SHG_L1',
            'entry': (200.0, -220.0, 9.874999999999996),
            'exit': (200.0, -220.0, 9.874999999999996),
            'internal_length': 0.0,
            'mode': 'pass',
            'reference': 'SHG_L1'}}

PATH_LENGTHS = {}
OPEN_SEGMENTS = [((100.0, -219.99999999999997, 9.875000000000009),
  (-1.0, 2.220446049250313e-16, 1.1842378929335003e-16),
  13.700000000000003)]

def build_layout():
    layout = Layout('CPA folded draft — four-pass compressor and crystal')
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
    part_4 = Component('CP_HRoof', catalog.roof(orientation='horizontal', mounted=True, reverse=True, beam_separation=9.538700742686107))
    x, y, z, angle = PLACEMENTS['CP_HRoof']
    objects['CP_HRoof'] = layout.add(part_4, position=(x, y, z), rotation=angle)
    part_5 = Component('CP_VRoof', catalog.roof(orientation='vertical', mounted=True, reverse=True, beam_separation=5.65))
    x, y, z, angle = PLACEMENTS['CP_VRoof']
    objects['CP_VRoof'] = layout.add(part_5, position=(x, y, z), rotation=angle)
    part_6 = Component('CP_Pickoff', catalog.d_mirror(optic='PFD05-03-P01', mount='KM05DL', diameter=12.7, thickness=6.0, edge_distance=1))
    x, y, z, angle = PLACEMENTS['CP_Pickoff']
    objects['CP_Pickoff'] = layout.add(part_6, position=(x, y, z), rotation=angle)
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
        final_distance=80.0, trace_limit=25, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'From_EDFA')
    return layout


if __name__ == "__main__":
    build_layout()
