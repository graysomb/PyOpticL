"""Supplied six-part crystal holder and a separate, drilled support bracket.

Coordinates are mm, with +X along the crystal and the crystal center at zero.
The STEP is preserved; only the new bracket and nominal fasteners are generated.
"""
import json
import FreeCAD as App
import Part

from PyOpticL import attachments
from PyOpticL.beam_path import Interface
from PyOpticL.component_contract import ComponentContract, Frame, Hole, MechanicalInterface, Provenance, Thread
from PyOpticL.lab_catalog import DATA, Assembly, NominalScrew, _read_shape, transform
from PyOpticL.vendor_cad import resolve_reference


def reference():
    return json.loads((DATA / 'crystal_holder_reference.json').read_text())


def provenance():
    return (Provenance('User-supplied Crystal holder.step', 'cad_verified',
        reference()['source_sha256'],
        'Six original solids, rigidly normalized at the crystal center. '
        'New bracket and fastening selections are nominal mechanical designs; '
        'no thermal or nonlinear optical model.'),)


def source_shape(index):
    r = reference()
    records = json.loads((DATA / 'source_references.json').read_text())
    if records[r['source_reference']]['sha256'] != r['source_sha256']:
        raise ValueError('Crystal holder source revision requires new datum verification')
    path = resolve_reference(r['source_reference'])
    shape = _read_shape(str(path), r['source_sha256'])
    if len(shape.Solids) != len(r['parts']):
        raise ValueError('Crystal holder source must contain six solids')
    solid = shape.Solids[index]
    if abs(solid.Volume - r['parts'][index]['volume_mm3']) > 1e-5:
        raise ValueError('Crystal holder source solid order differs from measured reference')
    return transform(solid, **r['normalization'])


class SourcePart:
    preserve_topology = True
    apply_drilling = False
    part_numbers = []

    def __init__(self, index):
        self.index = index
        self.object_group = 'optics' if index == 1 else 'mounts'
        self.object_color = ((.54, .85, .83) if index == 1 else
                             (.76, .46, .11) if index == 3 else (.65, .65, .65))

    def shape(self):
        return source_shape(self.index)

    def contract(self):
        frames = [Frame('origin'), Frame('optical')]
        holes = []
        if self.index == 3:
            frames.append(Frame('mounting_face', (0, 0, -3.5)))
            r = reference()
            for i, ((x, y), hole) in enumerate(zip(r['bracket']['holder_xy_mm'], r['source_mounting_holes']), 1):
                name = f'holder_{i}'
                frames.append(Frame(name, (x, y, -3.5)))
                holes.append(Hole(name, name, hole['diameter_mm'], hole['depth_mm'], source=
                    f"Measured source smooth bore, mouth diameter {hole['mouth_diameter_mm']:g} mm; thread unspecified"))
        return ComponentContract(f'crystal-source-{self.index}', '2' if self.index == 3 else '1', 'Lab', '',
            'generic' if self.index == 1 else 'fabricated', frames=tuple(frames), holes=tuple(holes),
            optical_reference='optical' if self.index == 1 else None, provenance=provenance())


class CrystalPass(Interface):
    """Identity ray interface; both crystal end faces must clear the ray center."""
    def __init__(self):
        super().__init__((0, 0, 0), (0, 0, 0), width=4., height=1.)

    def get_intercept(self, beam):
        point = super().get_intercept(beam)
        if point is None:
            return None
        inverse = self.parent.get_object().Placement.inverse()
        hit = inverse.multVec(App.Vector(*point))
        direction = inverse.Rotation.multVec(App.Vector(*beam.get_global_direction()))
        if abs(direction.x) < 1e-6:
            return None
        for x in (-13.7, 13.7):
            end = hit + direction * ((x - hit.x) / direction.x)
            if abs(end.y) > 2. or abs(end.z) > .5:
                return None
        return point


class CrystalBracket:
    object_group = 'adapters'
    object_color = (.46, .55, .63)
    apply_drilling = False
    drill_groups = ('baseplate',)
    part_numbers = []
    top = -3.5
    floor = -12.7

    def shape(self):
        r = reference()['bracket']
        length, width, height = r['size_mm']
        body = Part.makeBox(length, width, height, App.Vector(-length/2, -width/2, self.floor))
        for x, y in r['plate_xy_mm']:
            p = App.Vector(x, y, self.top + .01)
            body = body.cut(Part.makeCylinder(2.25, height + .02, p, App.Vector(0, 0, -1)))
            body = body.cut(Part.makeCylinder(3.75, 4.41, p, App.Vector(0, 0, -1)))
        for x, y in r['holder_xy_mm']:
            operation = dict(center_mm=[x, y, self.top], axis=[0, 0, -1],
                diameter_mm=r['holder_tap_drill_mm'], depth_mm=r['holder_drill_depth_mm'])
            body = body.cut(attachments.bore(operation))
        for x, y in r['pin_xy_mm']:
            body = body.cut(attachments.bore(dict(center_mm=[x, y, self.floor], axis=[0, 0, 1],
                diameter_mm=2.05, depth_mm=2.)))
        return body.removeSplitter()

    def contract(self):
        r = reference()['bracket']
        frames = [Frame('origin'), Frame('optical'), Frame('mounting_face', (0, 0, self.floor)),
                  Frame('holder_seat', (0, 0, self.top))]
        holes, interfaces = [], [MechanicalInterface('holder_seat', 'holder_seat', 'planar',
            seating='Original crystal plate underside rests on the separate bracket top')]
        for kind, positions in (('holder', r['holder_xy_mm']), ('plate', r['plate_xy_mm']),
                                ('pin', r['pin_xy_mm'])):
            for i, (x, y) in enumerate(positions, 1):
                name = f'{kind}_{i}'
                frames.append(Frame(name, (x, y, self.top if kind == 'holder' else self.floor),
                                    (180, 0, 0) if kind == 'holder' else (0, 0, 0)))
                if kind == 'holder':
                    holes.append(Hole(name, name, r['holder_tap_drill_mm'], r['holder_drill_depth_mm'],
                        r['holder_thread'], source='New bracket tap drill; 5 mm usable thread, 118 degree drill tip'))
                    interfaces.append(MechanicalInterface(name, name, 'thread',
                        Thread(r['holder_thread'], 'internal', 1.6, .35), engagement_mm=4.5,
                        seating='M1.6 screw through original bore and flat 0.5 mm washer; length matches measured local stack'))
                else:
                    holes.append(Hole(name, name, 4.5 if kind == 'plate' else 2.05,
                        9.2 if kind == 'plate' else 2., counterbore_mm=7.5 if kind == 'plate' else None,
                        source='M4 clearance; top counterbore 4.4 mm deep' if kind == 'plate'
                        else 'Blind locating bore upward from underside, 118 degree drill tip'))
        return ComponentContract('crystal-bracket', '2', 'Lab', '', 'fabricated',
            frames=tuple(frames), holes=tuple(holes), interfaces=tuple(interfaces),
            optical_reference='optical', provenance=provenance())

    def baseplate_profile(self):
        dowel = json.loads((DATA / 'alignment_iris_reference.json').read_text())['mounting_profile']['dowel']
        return dict(seat_frame='mounting_face', screws=['plate_1', 'plate_2'],
            dowels=['pin_1', 'pin_2'], dowel=dowel, optical_height_mm=12.7,
            source='Custom crystal bracket: two M4 taps and two 2 mm locating pins',
            step_sha256=reference()['source_sha256'])

    def drill(self):
        # Only the mating baseplate pattern; holder taps stay inside the bracket.
        return attachments.footprint(self)


class HolderWasher:
    object_group = 'fasteners'
    object_color = (.7, .7, .73)
    apply_drilling = False
    part_numbers = []

    def shape(self):
        return Part.makeCylinder(2.5, .5).cut(Part.makeCylinder(.9, .52, App.Vector(0, 0, -.01)))

    def contract(self):
        return ComponentContract('crystal-holder-washer', '1', 'Unspecified', '', 'generic',
            frames=(Frame('seat'),), provenance=(Provenance('Nominal flat washer selection', 'unverified',
                note='OD5 / ID1.8 / thickness0.5 mm; seats on the plate top or lateral clip above the selected through hole.'),))


class BracketDowel:
    object_group = 'fasteners'
    object_color = (.7, .7, .73)
    apply_drilling = False
    part_numbers = []

    def shape(self):
        return Part.makeCylinder(1., 5.)

    def contract(self):
        return ComponentContract('crystal-bracket-dowel', '1', 'Unspecified',
            '2 mm x 5 mm DIN 7-m6 / ISO 2338', 'generic', frames=(Frame('pin_end'),),
            provenance=(Provenance('Existing catalog locating-pin convention', 'documented',
                note='Nominal smooth envelope; 4.445 mm in plate, 0.555 mm in bracket.'),))


class CrystalHolder(Assembly):
    def __init__(self, mounted=True):
        r = reference()
        children = [(p['label'], SourcePart(i), (0, 0, 0), (0, 0, 0)) for i, p in enumerate(r['parts'])]
        frames = [Frame('origin'), Frame('optical'), Frame('input', (-13.7, 0, 0)),
                  Frame('output', (13.7, 0, 0)), Frame('native_mounting_face', (0, 0, -3.5)),
                  Frame('mounting_face', (0, 0, -12.7 if mounted else -3.5))]
        if mounted:
            children.append(('Crystal support bracket', CrystalBracket(), (0, 0, 0), (0, 0, 0)))
            for (x, y), fastener in zip(r['bracket']['holder_xy_mm'], r['bracket']['holder_fasteners']):
                seat, length = fastener['washer_seat_z_mm'], fastener['screw_length_mm']
                children.append(('Holder flat washer', HolderWasher(), (x, y, seat), (0, 0, 0)))
                children.append(('M1.6 holder screw', NominalScrew(f'M1.6 x 0.35 x {length:g} mm',
                    1.6, .35, length, 3., 1.6), (x, y, seat + .5), (0, 0, 0)))
            for x, y in r['bracket']['plate_xy_mm']:
                children.append(('M4 plate screw', NominalScrew('M4 x 0.7 x 12 mm', 4., .7, 12., 7., 4.),
                    (x, y, -7.9), (0, 0, 0)))
            for x, y in r['bracket']['pin_xy_mm']:
                children.append(('Bracket locating pin', BracketDowel(), (x, y, -17.145), (0, 0, 0)))
        super().__init__(ComponentContract('crystal_holder' if mounted else 'crystal_holder_bare',
            '2', 'Lab', '', 'assembly', frames=tuple(frames), optical_reference='optical',
            provenance=provenance()), children)

    def interfaces(self):
        return [CrystalPass()]
