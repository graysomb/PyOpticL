"""Exact Newport 818-BB-30 with a separate, fabricated baseplate bracket.

The optical origin is the external entrance bore center, +X outward and +Z up.
Receiver tracing terminates the nominal ray; it does not simulate photocurrent.
"""

import json
import math
import FreeCAD as App
import Part

from PyOpticL import attachments
from PyOpticL.beam_path import Stop
from PyOpticL.component_contract import ComponentContract, Frame, Hole, MechanicalInterface, Provenance, Thread
from PyOpticL.lab_catalog import DATA, Assembly, NominalScrew, asset_record, transform, vendor_shape


def reference():
    return json.loads((DATA / 'newport_818_bb_30_reference.json').read_text())


def provenance():
    r = reference()
    return (Provenance(r['product_url'], 'cad_verified', r['step_sha256'],
                       'One purchased solid preserved; ' + r['datum_note']),
            Provenance(r['drawing'], 'documented', r['drawing_sha256'],
                       r['mounting_note']))


def receiver():
    optical = reference()['optical']
    result = Stop((0, 0, 0), (0, 0, 0), diameter=optical['active_diameter_mm'],
                  max_angle=optical['acceptance_half_angle_deg'], single_sided=True)
    result.name, result.role = '818-BB-30 entrance datum', 'receiver'
    return result


class Photodetector818BB30:
    object_group = 'optics'
    object_color = (.22, .23, .25)
    preserve_topology = True
    apply_drilling = False
    part_numbers = ['818-BB-30']

    def __init__(self, optical=True):
        self.optical = optical

    def shape(self):
        r = reference()
        if asset_record('818-BB-30')['sha256'] != r['step_sha256']:
            raise ValueError('818-BB-30 CAD revision requires new datum verification')
        return transform(vendor_shape('818-BB-30'), **r['normalization'])

    def interfaces(self):
        return [receiver()] if self.optical else []

    def contract(self):
        r = reference()
        frames = [Frame('optical'), Frame('mounting_face', (-16.8656, 0, -17.1958)),
                  Frame('bnc', tuple(r['optical']['bnc_position_mm']), (-90, 0, 0))]
        holes, interfaces = [], [MechanicalInterface('bnc', 'bnc', 'electrical', connector='BNC')]
        for h in r['mounting_holes']:
            frames.append(Frame(h['name'], tuple(h['position_mm'])))
            holes.append(Hole(h['name'], h['name'], h['diameter_mm'], h['depth_mm'], h['thread'],
                              source='Drawing thread designation; STEP straight minor-diameter bore depth'))
            interfaces.append(MechanicalInterface(h['name'], h['name'], 'thread',
                Thread(h['thread'], 'internal', h['major_mm'], h['pitch_mm']),
                seating=r['mounting_note'], engagement_mm=2 if h['name'] == 'mount_m4' else None))
        return ComponentContract('818-BB-30', '1', 'Newport', '818-BB-30', 'purchased',
            frames=tuple(frames), holes=tuple(holes), interfaces=tuple(interfaces),
            optical_reference='optical', provenance=provenance())


class DetectorBracket:
    object_group = 'adapters'
    object_color = (.46, .56, .65)
    apply_drilling = False
    drill_groups = ('baseplate',)
    part_numbers = []

    def __init__(self, optical_height=25.4):
        r = reference()['bracket']
        if not math.isfinite(optical_height) or optical_height < r['minimum_optical_height_mm']:
            raise ValueError('818-BB-30 bracket optical height must be at least 25.4 mm')
        self.optical_height = optical_height
        self.floor, self.top = -optical_height, r['detector_seat_z_mm']

    def shape(self):
        r = reference()['bracket']
        height = self.top - self.floor
        foot = r['foot_thickness_mm']
        body = Part.makeBox(*r['size_xy_mm'], foot, App.Vector(*r['corner_xy_mm'], self.floor))
        body = body.fuse(Part.makeBox(*r['pedestal_size_xy_mm'], height - foot,
            App.Vector(*r['pedestal_corner_xy_mm'], self.floor + foot)))
        for x, y in r['plate_xy_mm']:
            body = body.cut(Part.makeCylinder(2.25, height + .02,
                App.Vector(x, y, self.floor - .01)))
            body = body.cut(Part.makeCylinder(4, height - r['web_mm'] + .01,
                App.Vector(x, y, self.top + .01), App.Vector(0, 0, -1)))
        # Detector screw is installed from below before the bracket is plated.
        x, y, _ = reference()['mounting_holes'][0]['position_mm']
        body = body.cut(Part.makeCylinder(2.25, height + .02,
            App.Vector(x, y, self.floor - .01)))
        body = body.cut(Part.makeCylinder(4, height - r['web_mm'] + .01,
            App.Vector(x, y, self.floor - .01)))
        for x, y in r['pin_xy_mm']:
            body = body.cut(attachments.bore(dict(center_mm=[x, y, self.floor], axis=[0, 0, 1],
                diameter_mm=r['dowel']['mount_diameter_mm'], depth_mm=r['dowel']['mount_depth_mm'])))
        # Clearance lips limit gross rotation without modifying the housing.
        body = body.fuse(Part.makeBox(2, 33.7312, 2, App.Vector(-35.9312, -16.8656, self.top)))
        body = body.fuse(Part.makeBox(33.7312, 2, 2, App.Vector(-33.7312, -19.0656, self.top)))
        return body.removeSplitter()

    def contract(self):
        r = reference()['bracket']
        height = self.top - self.floor
        x, y, _ = reference()['mounting_holes'][0]['position_mm']
        frames = [Frame('optical'), Frame('mounting_face', (-17, 0, self.floor)),
                  Frame('detector_seat', (-16.8656, 0, self.top)),
                  Frame('detector_screw', (x, y, self.floor))]
        holes = [Hole('detector_screw', 'detector_screw', 4.5, height, counterbore_mm=8,
            source=f'Underside counterbore {height - 4:g} mm deep; 4 mm clamped web; M4 x 6 screw')]
        for kind, positions in (('plate', r['plate_xy_mm']), ('pin', r['pin_xy_mm'])):
            for i, (x, y) in enumerate(positions, 1):
                name = f'{kind}_{i}'
                frames.append(Frame(name, (x, y, self.floor)))
                holes.append(Hole(name, name, 4.5 if kind == 'plate' else r['dowel']['mount_diameter_mm'],
                    r['foot_thickness_mm'] if kind == 'plate' else r['dowel']['mount_depth_mm'],
                    counterbore_mm=8 if kind == 'plate' else None,
                    source=('Top counterbore 4 mm deep; 4 mm web; M4 x 12 screw'
                            if kind == 'plate' else 'Underside blind locating bore with 118 degree tip')))
        return ComponentContract('818-BB-30-bracket', '1', 'Lab', '818-BB-30-BRACKET', 'fabricated',
            frames=tuple(frames), holes=tuple(holes), optical_reference='optical',
            interfaces=(MechanicalInterface('detector_seat', 'detector_seat', 'planar',
                seating='Housing underside; 0.2 mm lip clearance. Single M4 retention; physical retention needs validation.'),),
            provenance=provenance())

    def baseplate_profile(self):
        r = reference()
        return dict(seat_frame='mounting_face', screws=['plate_1', 'plate_2'], dowels=['pin_1', 'pin_2'],
            screw=dict(thread='M4 x 0.7', diameter_mm=3.3, depth_mm=10., thread_depth_mm=8.),
            dowel=r['bracket']['dowel'], optical_height_mm=self.optical_height,
            recess_orientation='mount', recess_side_scale_xy={'y_plus': 1.5},
            source='Fabricated 818-BB-30 bracket; ' + r['drawing'],
            step_sha256=r['step_sha256'], drawing_sha256=r['drawing_sha256'])

    def drill(self):
        return attachments.footprint(self)


class DetectorDowel:
    object_group = 'fasteners'
    object_color = (.7, .7, .73)
    apply_drilling = False
    part_numbers = []

    def shape(self):
        return Part.makeCylinder(1, 5)

    def contract(self):
        return ComponentContract('detector-bracket-dowel', '1', 'Unspecified',
            '2 mm x 5 mm DIN 7-m6 / ISO 2338', 'generic', frames=(Frame('pin_end'),),
            provenance=(Provenance('Existing catalog locating-pin convention', 'documented',
                note='Nominal envelope; 4.445 mm in plate and 0.555 mm in bracket.'),))


class MountedPhotodetector(Assembly):
    def __init__(self, optical_height=25.4):
        bracket = DetectorBracket(optical_height)
        r = reference()
        children = [('Newport 818-BB-30', Photodetector818BB30(optical=False), (0, 0, 0), (0, 0, 0)),
                    ('Detector bracket', bracket, (0, 0, 0), (0, 0, 0))]
        x, y, _ = r['mounting_holes'][0]['position_mm']
        children.append(('M4 detector screw', NominalScrew('M4 x 0.7 x 6 mm', 4, .7, 6, 7, 4),
                         (x, y, bracket.top - 4), (180, 0, 0)))
        for x, y in r['bracket']['plate_xy_mm']:
            children.append(('M4 plate screw', NominalScrew('M4 x 0.7 x 12 mm', 4, .7, 12, 7, 4),
                             (x, y, bracket.floor + 4), (0, 0, 0)))
        for x, y in r['bracket']['pin_xy_mm']:
            children.append(('Bracket locating pin', DetectorDowel(),
                             (x, y, bracket.floor - r['bracket']['dowel']['plate_depth_mm']), (0, 0, 0)))
        super().__init__(ComponentContract('photodetector', '1', 'Lab', '', 'assembly',
            frames=(Frame('optical'), Frame('mounting_face', (-17, 0, bracket.floor))),
            optical_reference='optical', provenance=provenance()), children)

    def interfaces(self):
        return [receiver()]
