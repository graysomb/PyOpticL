"""Generated physical PyOpticL schematic; component and pass IDs are stable."""
from PyOpticL.layout import Layout, Component
from PyOpticL.beam_path import BeamPath, linear_polarization
from PyOpticL.library import optics, thorlabs
from PyOpticL.schematic.runtime import check_pass_trace
from PyOpticL.schematic import catalog_parts as catalog

PLACEMENTS = {'ST_G1': (760, 400, 12.7, -90),
 'ST_G2': (1876.6038361944875, 629.7735254457186, 12.7, 11.62794830005953),
 'ST_HWP1': (1876.6038361944875, 554.7735254457186, 12.7, 90),
 'ST_Iris': (760, 475, 12.7, -90),
 'ST_L1': (828.5633934505387, 414.10890068526345, 12.7, 11.62794830005953),
 'ST_L2': (1808.0404427439487, 615.6646247604552, 12.7, 191.62794830005953),
 'ST_M1': (760, 550, 12.7, 270),
 'ST_M2': (1876.6038361944875, 479.77352544571863, 12.7, 135),
 'To_EDFA': (1696.6038361944875, 479.77352544571863, 12.7, 0)}

SOURCE = {'angle': 0,
 'polarization_angle': 0,
 'position': (1696.6038361944875, 479.77352544571863, 12.7),
 'power': 0.001,
 'waist': 0.2,
 'wavelength': 1550}

EXPECTED_PASSES = {'ST_G1': {'branches': {'out': {'connection': 'e6',
                                'direction': (-4.440892098500626e-16, 1.0, 0.0),
                                'length': 74.9999999999996,
                                'pass': 'ST_Iris'}},
           'component': 'ST_G1',
           'entry': (760.0000000000003, 400.0000000000004, 12.7),
           'exit': (760.0000000000003, 400.0000000000004, 12.7),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'ST_G1'},
 'ST_G1_return': {'branches': {'out': {'connection': 'e10',
                                       'direction': (0.9794770492934102,
                                                     0.201555724075191,
                                                     0.0),
                                       'length': 69.99999999999984,
                                       'pass': 'ST_L1_return'}},
                  'component': 'ST_G1',
                  'entry': (760.0000000000001, 400.00000000000017, 12.7),
                  'exit': (760.0000000000001, 400.00000000000017, 12.7),
                  'internal_length': 0.0,
                  'mode': 'pass',
                  'reference': 'ST_G1'},
 'ST_G2': {'branches': {'out': {'connection': 'e3',
                                'direction': (-0.9794770492934102,
                                              -0.20155572407519146,
                                              0.0),
                                'length': 70.00000000000009,
                                'pass': 'ST_L2'}},
           'component': 'ST_G2',
           'entry': (1876.6038361944875, 629.7735254457186, 12.7),
           'exit': (1876.6038361944875, 629.7735254457186, 12.7),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'ST_G2'},
 'ST_G2_return': {'branches': {'out': {'connection': 'e13',
                                       'direction': (1.1102230246251565e-15,
                                                     -1.0,
                                                     0.0),
                                       'length': 74.99999999999909,
                                       'pass': 'ST_HWP1_return'}},
                  'component': 'ST_G2',
                  'entry': (1876.6038361944868, 629.7735254457177, 12.7),
                  'exit': (1876.6038361944868, 629.7735254457177, 12.7),
                  'internal_length': 0.0,
                  'mode': 'pass',
                  'reference': 'ST_G2'},
 'ST_HWP1': {'branches': {'out': {'connection': 'e2',
                                  'direction': (2.220446049250313e-16,
                                                1.0,
                                                0.0),
                                  'length': 75.00000000000003,
                                  'pass': 'ST_G2'}},
             'component': 'ST_HWP1',
             'entry': (1876.6038361944875, 554.7735254457186, 12.7),
             'exit': (1876.6038361944875, 554.7735254457186, 12.7),
             'internal_length': 0.0,
             'mode': 'pass',
             'reference': 'ST_HWP1'},
 'ST_HWP1_return': {'branches': {'out': {'connection': 'e14',
                                         'direction': (1.1102230246251565e-15,
                                                       -1.0,
                                                       0.0),
                                         'length': 75.0000000000006,
                                         'pass': 'ST_M2_return'}},
                    'component': 'ST_HWP1',
                    'entry': (1876.6038361944868, 554.7735254457186, 12.7),
                    'exit': (1876.6038361944868, 554.7735254457186, 12.7),
                    'internal_length': 0.0,
                    'mode': 'pass',
                    'reference': 'ST_HWP1'},
 'ST_Iris': {'branches': {'out': {'connection': 'e7',
                                  'direction': (-4.440892098500626e-16,
                                                1.0,
                                                0.0),
                                  'length': 75.0,
                                  'pass': 'ST_M1'}},
             'component': 'ST_Iris',
             'entry': (760.0000000000003, 475.0, 12.7),
             'exit': (760.0000000000003, 475.0, 12.7),
             'internal_length': 0.0,
             'mode': 'pass',
             'reference': 'ST_Iris'},
 'ST_Iris_return': {'branches': {'out': {'connection': 'e9',
                                         'direction': (-8.114832495942686e-16,
                                                       -1.0,
                                                       0.0),
                                         'length': 74.99999999999982,
                                         'pass': 'ST_G1_return'}},
                    'component': 'ST_Iris',
                    'entry': (760.0000000000002, 475.0, 12.7),
                    'exit': (760.0000000000002, 475.0, 12.7),
                    'internal_length': 0.0,
                    'mode': 'pass',
                    'reference': 'ST_Iris'},
 'ST_L1': {'branches': {'out': {'connection': 'e5',
                                'direction': (-0.9794770492934101,
                                              -0.2015557240751921,
                                              0.0),
                                'length': 69.9999999999994,
                                'pass': 'ST_G1'}},
           'component': 'ST_L1',
           'entry': (828.5633934505385, 414.10890068526373, 12.7),
           'exit': (828.5633934505385, 414.10890068526373, 12.7),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'ST_L1'},
 'ST_L1_return': {'branches': {'out': {'connection': 'e11',
                                       'direction': (0.9794770492934104,
                                                     0.20155572407519096,
                                                     0.0),
                                       'length': 999.9999999999998,
                                       'pass': 'ST_L2_return'}},
                  'component': 'ST_L1',
                  'entry': (828.5633934505387, 414.1089006852635, 12.7),
                  'exit': (828.5633934505387, 414.1089006852635, 12.7),
                  'internal_length': 0.0,
                  'mode': 'pass',
                  'reference': 'ST_L1'},
 'ST_L2': {'branches': {'out': {'connection': 'e4',
                                'direction': (-0.9794770492934102,
                                              -0.20155572407519146,
                                              0.0),
                                'length': 1000.0000000000001,
                                'pass': 'ST_L1'}},
           'component': 'ST_L2',
           'entry': (1808.0404427439487, 615.6646247604552, 12.7),
           'exit': (1808.0404427439487, 615.6646247604552, 12.7),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'ST_L2'},
 'ST_L2_return': {'branches': {'out': {'connection': 'e12',
                                       'direction': (0.9794770492934098,
                                                     0.2015557240751925,
                                                     0.0),
                                       'length': 69.99999999999918,
                                       'pass': 'ST_G2_return'}},
                  'component': 'ST_L2',
                  'entry': (1808.040442743949, 615.6646247604544, 12.7),
                  'exit': (1808.040442743949, 615.6646247604544, 12.7),
                  'internal_length': 0.0,
                  'mode': 'pass',
                  'reference': 'ST_L2'},
 'ST_M1': {'branches': {'out': {'connection': 'e8',
                                'direction': (-8.114832495942686e-16,
                                              -1.0,
                                              0.0),
                                'length': 75.0,
                                'pass': 'ST_Iris_return'}},
           'component': 'ST_M1',
           'entry': (760.0000000000003, 550.0, 12.7),
           'exit': (760.0000000000003, 550.0, 12.7),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'ST_M1'},
 'ST_M2': {'branches': {'out': {'connection': 'e1',
                                'direction': (2.220446049250313e-16, 1.0, 0.0),
                                'length': 75.0,
                                'pass': 'ST_HWP1'}},
           'component': 'ST_M2',
           'entry': (1876.6038361944875, 479.77352544571863, 12.7),
           'exit': (1876.6038361944875, 479.77352544571863, 12.7),
           'internal_length': 0.0,
           'mode': 'pass',
           'reference': 'ST_M2'},
 'ST_M2_return': {'branches': {'out': {'connection': 'e15',
                                       'direction': (-1.0,
                                                     1.3322676295501878e-15,
                                                     0.0),
                                       'length': 179.99999999999932,
                                       'pass': 'To_EDFA_return'}},
                  'component': 'ST_M2',
                  'entry': (1876.6038361944868, 479.77352544571806, 12.7),
                  'exit': (1876.6038361944868, 479.77352544571806, 12.7),
                  'internal_length': 0.0,
                  'mode': 'pass',
                  'reference': 'ST_M2'},
 'To_EDFA': {'branches': {'out': {'connection': 'e0',
                                  'direction': (1.0, 0.0, 0.0),
                                  'length': 180.0,
                                  'pass': 'ST_M2'}},
             'component': 'To_EDFA',
             'entry': (1696.6038361944875, 479.77352544571863, 12.7),
             'exit': (1696.6038361944875, 479.77352544571863, 12.7),
             'internal_length': 0,
             'mode': 'emit',
             'reference': 'To_EDFA'},
 'To_EDFA_return': {'branches': {},
                    'component': 'To_EDFA',
                    'entry': (1696.6038361944875, 479.7735254457183, 12.7),
                    'exit': (1696.6038361944875, 479.7735254457183, 12.7),
                    'internal_length': 0.0,
                    'mode': 'receive',
                    'reference': 'To_EDFA'}}

PATH_LENGTHS = {}
OPEN_SEGMENTS = []

def build_layout():
    layout = Layout('CPA draft — stretcher')
    objects = {}
    part_0 = Component('ST_M1', catalog.mirror(mount='POLARIS-K1VS2', diameter=25.4, thickness=3))
    x, y, z, angle = PLACEMENTS['ST_M1']
    objects['ST_M1'] = layout.add(part_0, position=(x, y, z), rotation=angle)
    part_1 = Component('ST_Iris', catalog.slit(slit_width=1.0))
    x, y, z, angle = PLACEMENTS['ST_Iris']
    objects['ST_Iris'] = layout.add(part_1, position=(x, y, z), rotation=angle)
    part_2 = Component('ST_G1', catalog.grating(mounted=True, design_wavelength=1550, incidence_angle=49.9, order=1, mirrored=0))
    x, y, z, angle = PLACEMENTS['ST_G1']
    objects['ST_G1'] = layout.add(part_2, position=(x, y, z), rotation=angle)
    part_3 = Component('ST_L1', optics.Spherical_Lens(diameter=25.4, focal_length=500.0, thickness=2, mount_definition=catalog.vendor(part='POLARIS-L1G'), mount_offset=(-1.0, 0, 0)))
    x, y, z, angle = PLACEMENTS['ST_L1']
    objects['ST_L1'] = layout.add(part_3, position=(x, y, z), rotation=angle)
    part_4 = Component('ST_L2', optics.Spherical_Lens(diameter=25.4, focal_length=500.0, thickness=2, mount_definition=catalog.vendor(part='POLARIS-L1G'), mount_offset=(-1.0, 0, 0)))
    x, y, z, angle = PLACEMENTS['ST_L2']
    objects['ST_L2'] = layout.add(part_4, position=(x, y, z), rotation=angle)
    part_5 = Component('ST_G2', catalog.grating(mounted=True, design_wavelength=1550, incidence_angle=49.9, order=1, mirrored=1))
    x, y, z, angle = PLACEMENTS['ST_G2']
    objects['ST_G2'] = layout.add(part_5, position=(x, y, z), rotation=angle)
    part_6 = Component('ST_M2', catalog.mirror(mount='POLARIS-K05VS2', diameter=12.7, thickness=3))
    x, y, z, angle = PLACEMENTS['ST_M2']
    objects['ST_M2'] = layout.add(part_6, position=(x, y, z), rotation=angle)
    part_7 = Component('ST_HWP1', catalog.waveplate(mount='FBR', retardance=0.5, diameter=12.7, fast_axis_angle=0, thickness=1))
    x, y, z, angle = PLACEMENTS['ST_HWP1']
    objects['ST_HWP1'] = layout.add(part_7, position=(x, y, z), rotation=angle)
    part_8 = Component('To_EDFA', catalog.coupling(mount='POLARIS-K05T6', receiving=True))
    x, y, z, angle = PLACEMENTS['To_EDFA']
    objects['To_EDFA'] = layout.add(part_8, position=(x, y, z), rotation=angle)
    beam = layout.add(BeamPath('To_EDFA', wavelength=SOURCE["wavelength"],
        polarization=linear_polarization(SOURCE["polarization_angle"]),
        power=SOURCE["power"], waist=SOURCE["waist"],
        final_distance=80.0, trace_limit=18, trace_ends=OPEN_SEGMENTS),
        position=SOURCE["position"], rotation=SOURCE["angle"])
    layout.recompute()
    check_pass_trace(beam, objects, EXPECTED_PASSES, 'To_EDFA')
    return layout


if __name__ == "__main__":
    build_layout()
