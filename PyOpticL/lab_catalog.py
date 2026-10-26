"""Small nominal-position lab catalog, extending the ordinary component API.

No DOF is a placement input. Cached vendor files are verified before import.
"""
from functools import lru_cache
from dataclasses import replace
import json
import math
from pathlib import Path
import FreeCAD as App
import Part
from PyOpticL.component_contract import ComponentContract, DOF, Frame, Hole, MechanicalInterface, Provenance, Thread
from PyOpticL.layout import Component, Subcomponent
from PyOpticL.vendor_cad import resolve
from PyOpticL.library import optics
from PyOpticL.beam_path import Interface, Stop
from PyOpticL.library.adapters import Surface_Adapter
from PyOpticL import attachments

DATA = Path(__file__).with_name('catalog_data')
VENDOR_IDS = ('POLARIS-L05G', 'POLARIS-L1G', 'POLARIS-K1VS2',
              'MHV-12.7L-R', 'MHV-25.4L-R', 'FBR', 'VA100', 'POLARIS-K05T6')
CATALOG_IDS = ('mirror', 'coupling', 'pbs', 'rotation', 'translation', 'iris', 'slit', 'roof')


def asset_record(part):
    return json.loads((DATA / 'assets' / (part + '.step.json')).read_text())


@lru_cache(maxsize=16)
def _read_shape(path, digest):
    shape = Part.read(path)
    if shape.isNull() or not shape.Solids or not shape.isValid():
        raise ValueError('Vendor STEP did not import as valid solids: ' + path)
    return shape


def vendor_shape(part):
    record = asset_record(part)
    path = resolve(record)  # Always check the pin, even on a shape-cache hit.
    return _read_shape(str(path), record['sha256']).copy()


def transform(shape, origin=(0, 0, 0), rotation=(0, 0, 0)):
    """Map a vendor datum to the origin without editing the cached source."""
    rotation = App.Rotation('XYZ', *rotation)
    shape = shape.copy()
    shape.Placement = App.Placement(-rotation.multVec(App.Vector(*origin)), rotation) * shape.Placement
    # Bake only the working copy so Component can assign its own Placement.
    return Part.makeCompound([shape])


def profile(name):
    """Rebuild editable rational sketch curves, not an imported opaque solid."""
    wires = []
    for wire in json.loads((DATA / 'profiles' / (name + '.json')).read_text()):
        edges = []
        for item in wire:
            curve = Part.BSplineCurve()
            curve.buildFromPolesMultsKnots([App.Vector(*p) for p in item['poles']],
                item['multiplicities'], item['knots'], item['periodic'], item['degree'], item['weights'])
            edge = curve.toShape(item['first'], item['last'])
            if item['orientation'] == 'Reversed':
                edge.reverse()
            edges.append(edge)
        wires.append(Part.Wire(edges))
    return Part.Face(wires, 'Part::FaceMakerBullseye')


class VendorPart:
    preserve_topology = True
    object_group = 'mounts'
    apply_drilling = False
    object_color = (0.27, 0.28, 0.3)
    drill_groups = ('baseplate',)

    def __init__(self, part, contract=None, exclude_solids=(), optic_thickness=None):
        self.part = part
        self.part_numbers = [part]
        specification = json.loads((DATA / 'normalization.json').read_text())[part]
        self.origin, self.rotation = specification['origin'], specification['rotation']
        self._contract = contract
        self.exclude_solids = tuple(exclude_solids)
        self.optic_thickness = optic_thickness

    def baseplate_profile(self):
        specification = json.loads((DATA / 'baseplate_interfaces.json').read_text()).get(self.part)
        if specification is None:
            specification = json.loads((DATA / 'batch_mounting_profiles.json').read_text()).get(self.part)
        if specification and asset_record(self.part)['sha256'] != specification['step_sha256']:
            raise ValueError('Mounting profile must be reverified for revised CAD: ' + self.part)
        return specification

    def drill(self):
        return attachments.footprint(self)

    def shape(self):
        shape = vendor_shape(self.part)
        if self.part == 'FBR' and self.optic_thickness is not None:
            # Configure the included ring as one static working compound.
            specification = json.loads((DATA / 'normalization.json').read_text())[self.part]
            ring = specification['included_retaining_rings']
            solids = [s.copy() for s in shape.Solids]
            solids[ring['solid']].translate(App.Vector(0, 0,
                ring['optic_seat_z'] + self.optic_thickness - ring['native_contact_z']))
            shape = Part.makeCompound(solids)
        if self.exclude_solids:
            shape = Part.makeCompound([s for i, s in enumerate(shape.Solids) if i not in self.exclude_solids])
        return transform(shape, self.origin, self.rotation)

    def contract(self):
        if self._contract:
            return self._contract
        record = asset_record(self.part)
        specification = json.loads((DATA / 'normalization.json').read_text())[self.part]
        rot = App.Rotation('XYZ', *self.rotation)
        def point(p):
            return tuple(rot.multVec(App.Vector(*p) - App.Vector(*self.origin)))
        frames = [Frame('origin'), Frame('optical')]
        frames.extend(Frame(name, point(p), specification.get('datum_rotations', {}).get(name, (0,0,0))) for name, p in specification['datums'].items())
        holes = []
        for h in specification['holes']:
            direction = rot.multVec(App.Vector(*h['axis']))
            # Frame's local Z is the hole axis; XYZ angles follow FreeCAD.
            angles = App.Rotation(App.Vector(0,0,1), direction).toEulerAngles('XYZ')
            frames.append(Frame(h['name'], point(h['center']), tuple(angles)))
            holes.append(Hole(h['name'], h['name'], h['diameter'], h['depth'], h['thread'],
                              source=record['product_url']))
        pairs = connection_interfaces()
        interfaces = {'F260FC-1550': (replace(pairs['F260FC-1550'], frame='thread_end', seating='Barrel front datum; M11 thread-end datum aligned with adapter opening, 2.9972 mm from barrel front; user-specified nominal convention.'), pairs['fiber']),
                      'AD1109F': (replace(pairs['AD1109F-in'], frame='collimator_opening', seating='M11 end faces the collimator; opposed to mount end.'), replace(pairs['AD1109F-out'], frame='mount_seat', engagement_mm=3.175, seating='Shoulder against selected SM05 mount front; remove its front retaining ring as specified by the assembly.')),
                      'KA05TA': (replace(pairs['KA05TA'], frame='adapter_seat', seating='Front plate plane; adapter enters along local +X.'),)}.get(self.part, ())
        if self.part == 'POLARIS-K05VS2':
            interfaces += (MechanicalInterface('dowel_slot', 'dowel_slot', 'slot',
                seating='2.00914 mm wide alignment slot at native X=+5 mm; mates to one round 2 mm pin. Round feature at X=-5 mm.'),)
        if self.part == 'POLARIS-K05T6':
            interfaces += (replace(pairs['POLARIS-K05T6'], frame='adapter_seat'),)
        names = specification.get('dofs', {'POLARIS-K05VS2': ('tip','tilt'),
            'KA05TA': ('tip','tilt','axial'), 'ELL16': ('rotation',)}.get(self.part, ()))
        if self.part == 'XR25C':
            frames.append(Frame('stage'))
            names = ('translation',)
        return ComponentContract(self.part, '1', 'OptoSigma' if record['vendor'] == 'optosigma' else 'Thorlabs', self.part, 'purchased',
            frames=tuple(frames), interfaces=interfaces, holes=tuple(holes),
            dofs=_dofs(names, 'attached optic' if self.part != 'XR25C' else 'payload', record['product_url']),
            optical_reference='optical' if self.part in VENDOR_IDS else None,
            provenance=(Provenance(record['product_url'], 'documented', record['sha256'],
                'Vendor nominal compound; see normalization and independent reference measurements.'),))



class AlignmentIris:
    """Fixed aperture plate, with its optical center at the component origin.

    Dimensions are in mm. The mounting surface is 12.7 mm below the origin;
    drill() describes the two mating plate bores, not the holes in the iris.
    """
    object_group = 'mounts'
    object_color = (.25, .25, .25)
    apply_drilling = False
    drill_groups = ('baseplate',)
    part_numbers = []
    optical_height = 12.7
    width = 20.
    thickness = 4.
    pin_positions = ((0., -5., -12.7), (0., 5., -12.7))

    def __init__(self, aperture_diameter=0.5):
        if not math.isfinite(aperture_diameter) or not 0 < aperture_diameter < self.width:
            raise ValueError('Aperture diameter must be finite and strictly between 0 and 20 mm')
        self.aperture_diameter = float(aperture_diameter)

    def baseplate_profile(self):
        """Fresh mounting profile; the STEP hash identifies the design reference."""
        return json.loads((DATA / 'alignment_iris_reference.json').read_text())['mounting_profile']

    def contract(self):
        profile = self.baseplate_profile()
        frames = [Frame('origin'), Frame('optical'),
                  Frame('mounting_face', (0, 0, -self.optical_height), (180, 0, 0))]
        holes = []
        for name, position in zip(profile['dowels'], self.pin_positions):
            # Local +Z enters the iris from its bottom face.
            frames.append(Frame(name, position))
            holes.append(Hole(name, name, profile['dowel']['mount_diameter_mm'],
                              profile['dowel']['mount_depth_mm'], source=profile['source']))
        return ComponentContract('iris', '1', 'Lab', '', 'fabricated',
            frames=tuple(frames), holes=tuple(holes), optical_reference='optical',
            provenance=(Provenance(profile['source'], 'documented', profile['step_sha256'],
                'Adapted design: one centered aperture, shortened rounded body, two round dowel holes. '
                'STEP hash identifies the original reference, not an exact geometry match.'),))

    def shape(self):
        # A semicircular cap above straight sides, extruded along the beam axis.
        x, r, bottom = -self.thickness / 2, self.width / 2, -self.optical_height
        a, b = App.Vector(x, -r, bottom), App.Vector(x, r, bottom)
        c, d = App.Vector(x, r, 0), App.Vector(x, -r, 0)
        outline = Part.Wire([Part.makeLine(a, b), Part.makeLine(b, c),
            Part.Arc(c, App.Vector(x, 0, r), d).toShape(), Part.makeLine(d, a)])
        shape = Part.Face(outline).extrude(App.Vector(self.thickness, 0, 0))
        shape = shape.cut(Part.makeCylinder(self.aperture_diameter / 2,
            self.thickness + .02, App.Vector(x - .01, 0, 0), App.Vector(1, 0, 0)))
        profile = self.baseplate_profile()
        for position in self.pin_positions:
            shape = shape.cut(_blind_bore(position, profile['dowel']['mount_diameter_mm'],
                                         profile['dowel']['mount_depth_mm'], (0, 0, 1)))
        return shape.removeSplitter()

    def drill(self):
        return attachments.footprint(self)

    def interfaces(self):
        # Same ideal aperture-stop behavior as the existing Thorlabs iris.
        return [Stop(position=(0, 0, 0), rotation=(0, 0, 0), diameter=self.width,
                     pinhole_diameter=self.aperture_diameter)]


def _blind_bore(position, diameter, depth, axis):
    """Straight-depth blind bore with a 118-degree tip and entry overrun."""
    center, direction = App.Vector(*position), App.Vector(*axis)
    radius = diameter / 2
    bore = Part.makeCylinder(radius, depth + .01, center - direction * .01, direction)
    tip = Part.makeCone(radius, 0, radius / math.tan(math.radians(59)),
                        center + direction * depth, direction)
    return bore.fuse(tip)


class HOMHolder:
    object_group = 'mounts'
    apply_drilling = False
    object_color = (0.72, 0.72, 0.75)
    part_numbers = []

    def __init__(self, kind):
        self.kind = kind

    def shape(self):
        if self.kind == 'pbs-clamp':
            s = profile('pbs_clamp').extrude(App.Vector(0, 0, 5))
            return transform(s, (0, 0, 50.8))
        if self.kind == 'pbs-holder':
            s = profile('pbs_base').extrude(App.Vector(0, 0, 19.05))
            for i in range(1, 5):
                s = s.fuse(profile('pbs_pad' + str(i)).extrude(App.Vector(0, 0, -3)))
            # Blind M3 tap-drill in the original integral base support.
            s = s.cut(Part.makeCylinder(1.25, 5, App.Vector(-14.5215728752538, 9.5215728752538, 39.45)))
            s = s.cut(Part.makeCone(0, 1.25, 0.75108, App.Vector(-14.5215728752538, 9.5215728752538, 38.69892)))
            return transform(s, (0, 0, 50.8))
        base = profile('rotation_base')
        s = base.extrude(App.Vector(0, 0, 7))
        for name in ('left', 'middle', 'right'):
            s = s.fuse(profile('rotation_pin_' + name).extrude(App.Vector(0, 0, 3.5)))
        # The rounded base outline continues up the sides of the upright.
        envelope = Part.Face(base.OuterWire).extrude(App.Vector(0, 0, 44.4))
        wall = profile('rotation_wall').extrude(App.Vector(0, -3, 0)).common(envelope)
        s = s.fuse(wall)
        for x in (-18.5, 18.5):
            a = Part.makeCylinder(2, 37.4, App.Vector(x, -26.1, 32.4))
            b = Part.makeCylinder(2, 37.4, App.Vector(x, -27.1, 32.4))
            s = s.fuse(a.common(b))
        # HOM optical center is (0,-38.1,50.8); rotate beam +Y to +X.
        return transform(s, (0, -38.1, 50.8), (0, 0, -90))

    def contract(self):
        frames = [Frame('origin'), Frame('optical')]
        holes = []
        interfaces = []
        if self.kind == 'pbs-holder':
            frames.extend((Frame('optic_seat', (0,0,-6.35)), Frame('attachment', (0,0,-25.4)),
                           Frame('clamp_tap', (-14.5215728752538,9.5215728752538,-6.35))))
            holes.append(Hole('clamp_tap', 'clamp_tap', 2.5, 5, 'M3 x 0.5', source='HOM setup.step; modeled tap-drill depth'))
        elif self.kind == 'pbs-clamp':
            frames.append(Frame('seating', (0,0,-6.35)))
            interfaces.append(MechanicalInterface('clamp_slot', 'seating', 'slot', seating='3 mm wide diagonal slot, source sketch profile.'))
        else:
            frames.extend((Frame('attachment',(0,0,-25.4)),Frame('cage_face',(10,0,0),(0,-90,0))))
            for y in (-15,15):
                for z in (-15,15):
                    name = f'cage_slot_{y}_{z}'
                    frames.append(Frame(name,(10,y,z),(0,90,0)))
                    interfaces.append(MechanicalInterface(name,name,'slot',seating='Through slot for 4-40 attachment; 2.2 mm center travel, 3.4544 mm end diameter.'))
            for y in (-25.25,25.25):
                frames.append(Frame(f'base_slot_{y}',(0,y,-25.4)))
                interfaces.append(MechanicalInterface(f'base_slot_{y}',f'base_slot_{y}','slot',seating='4.2 mm wide base slot for M4 fastener.'))
        return ComponentContract('hom-' + self.kind, '1', 'Lab', '', 'fabricated',
            frames=tuple(frames), interfaces=tuple(interfaces), holes=tuple(holes),
            provenance=(Provenance('Data/HOM Mount/HOM setup.step', 'cad_verified',
                note='Parametric extrusion of reference sketch profiles; sampled deviations in hom_verification.json.'),))



class DisplacementPBSHolder:
    """Local integral-base patch from the displacement assembly's center Body.

    Four registers and three relief trenches, including their 0.2 mm rounds,
    are rebuilt from measured dimensions. No standalone fastening is inferred.
    """
    object_group = 'mounts'
    apply_drilling = False
    object_color = (0.72, 0.72, 0.75)
    part_numbers = []
    optical_origin = (0.73, -4.36943894996313, 50.8)

    def shape(self):
        support = Part.makeBox(28.5, 24.5, 19.05, App.Vector(-16, -17, 25.4))
        # Front contact planes: X=7.08 and Y=1.98056105 in source coordinates.
        registers = [
            (-9.62, 1.98056105003687, 8, 5, 'y'),
            (3.08, 1.98056105003687, 2.5, 5, 'y'),
            (7.08, -14.7194389499631, 5, 8, 'x'),
            (7.08, -2.01943894996312, 5, 2.5, 'x'),
        ]
        for x, y, width, depth, axis in registers:
            register = Part.makeBox(width, depth, 5.05, App.Vector(x, y, 44.45))
            front = x if axis == 'x' else y
            edges = [edge for edge in register.Edges
                     if all(abs(getattr(v.Point, axis) - front) < 1e-6 for v in edge.Vertexes)
                     and not all(abs(v.Point.z - 44.45) < 1e-6 for v in edge.Vertexes)]
            support = support.fuse(register.makeFillet(.2, edges))
        # Two straight reliefs and the joined corner relief. Round the vertical
        # and bottom edges, retaining the open mouth at the seating plane.
        trenches = [
            [(-10.62, 1.18056105), (-1.12, 1.18056105),
             (-1.12, 1.98056105), (-10.62, 1.98056105)],
            [(6.28, -15.71943895), (7.08, -15.71943895),
             (7.08, -6.21943895), (6.28, -6.21943895)],
            [(2.58, 1.18056105), (6.28, 1.18056105), (6.28, -2.51943895),
             (7.08, -2.51943895), (7.08, 1.98056105), (2.58, 1.98056105)],
        ]
        for points in trenches:
            vertices = [App.Vector(x, y, 43.45) for x, y in points]
            pocket = Part.Face(Part.makePolygon(vertices + [vertices[0]])).extrude(App.Vector(0, 0, 1))
            edges = [edge for edge in pocket.Edges
                     if not all(abs(v.Point.z - 44.45) < 1e-6 for v in edge.Vertexes)]
            support = support.cut(pocket.makeFillet(.2, edges))
        # Blind clamp attachment hole measured in the center-piece CAD.
        support = support.cut(Part.makeCylinder(1.25, 9,
            App.Vector(-12.942, -13.0414389499631, 35.45)))
        support = support.cut(Part.makeCone(0, 1.25, .7510757737844,
            App.Vector(-12.942, -13.0414389499631, 34.6989242262156)))
        return transform(support, self.optical_origin)

    def contract(self):
        return ComponentContract('displacement-pbs-holder', '2', 'Lab', '', 'fabricated',
            frames=(Frame('optical'), Frame('optic_seat', (0,0,-6.35)),
                    Frame('base_patch', (0,0,-25.4)),
                    Frame('clamp_hole', (-13.672,-8.672,-6.35)),
                    Frame('register_x', (6.35,0,-3.825), (0,-90,0)),
                    Frame('register_y', (0,6.35,-3.825), (90,0,0))),
            holes=(Hole('clamp_hole', 'clamp_hole', 2.5, 9,
                        source='Displacement center Body; thread designation not encoded in STEP'),),
            interfaces=(MechanicalInterface('cube_seat', 'optic_seat', 'seating',
                seating='12.7 mm cube against +X/+Y registers; 1 mm-deep relief trenches, 0.2 mm rounds.'),),
            provenance=(Provenance('Data/Displacement setup/Displacement Mount Assembly.step',
                'cad_verified', note='Center Body, upper PBS seat; measured integral-base patch. See displacement_pbs_verification.json. Clamp attachment hole preserved; plastic clamp solid absent from this STEP.'),))


class NominalScrew:
    """Static clearance envelope; threads specified explicitly, not tessellated."""
    object_group = 'fasteners'
    apply_drilling = False
    object_color = (.4,.4,.42)
    def __init__(self, designation, diameter, pitch, length, head_diameter, head_height):
        self.designation, self.diameter, self.pitch, self.length = designation, diameter, pitch, length
        self.head_diameter, self.head_height = head_diameter, head_height
        self.part_numbers = []
    def shape(self):
        return Part.makeCylinder(self.diameter/2,self.length,App.Vector(0,0,-self.length)).fuse(
            Part.makeCylinder(self.head_diameter/2,self.head_height))
    def contract(self):
        return ComponentContract('fastener-'+self.designation, '1', 'Unspecified', self.designation, 'generic',
            frames=(Frame('head_seat'),), interfaces=(MechanicalInterface('thread','head_seat','thread',
                Thread(self.designation,'external',self.diameter,self.pitch)),),
            provenance=(Provenance('Catalog nominal fastening selection', 'unverified',
                note='Nominal clearance envelope; manufacturer and head geometry not pinned. Length selected for assembly stack, not recovered from lab CAD.'),))


class Assembly:
    object_group = 'layout'
    def __init__(self, contract, children):
        self._contract, self.children = contract, children
    def contract(self):
        return self._contract
    def subcomponents(self):
        return [Subcomponent(Component(label, definition), position, rotation)
                for label, definition, position, rotation in self.children]


class SlitStop(Interface):
    """Finite circular entrance field clipped by a slit along local Z."""
    def __init__(self, width):
        super().__init__((0, 0, 0), (0, 0, 0), diameter=13.589)
        self.slit_width = width

    def get_output_beams(self, incident_beam):
        point = self.get_intercept(incident_beam)
        if point is None:
            return []
        local = self.parent.get_object().Placement.inverse().multVec(App.Vector(*point))
        if abs(local.z) < self.slit_width / 2:
            return super().get_output_beams(incident_beam)
        return []


class VariableSlit(VendorPart):
    """Vendor reference CAD with a separately configured optical slit width."""
    def __init__(self, slit_width=1.):
        if not math.isfinite(slit_width) or not 0 <= slit_width <= 6:
            raise ValueError('VA100 slit width must be finite and between 0 and 6 mm')
        super().__init__('VA100')
        self.slit_width = float(slit_width)

    def contract(self):
        contract = super().contract()
        return replace(contract, provenance=contract.provenance + (
            Provenance('VA100 nominal configuration', 'documented',
                note=f'Optical slit width {self.slit_width:g} mm. All mechanical CAD remains in the '
                     'supplier reference pose (measured center opening 5.8928 mm). Width does not '
                     'articulate the blades, micrometer, or linkage; no motion simulation.'),))

    def interfaces(self):
        return [SlitStop(self.slit_width)]


class VA100Bracket:
    """Surface-adapter family sized around the measured slit seating footprint."""
    object_group = 'adapters'
    object_color = (.5, .7, .5)
    apply_drilling = False
    drill_groups = ('baseplate',)
    part_numbers = []
    height = 10.
    spacing = 25.

    def __init__(self):
        specification = json.loads((DATA / 'normalization.json').read_text())['VA100']
        self.native_height = specification['native_optical_height_mm']
        rotation = App.Rotation('XYZ', *specification['rotation'])
        self.seat = rotation.multVec(App.Vector(*specification['datums']['mounting_face']) -
                                    App.Vector(*specification['origin']))
        self.surface = Surface_Adapter(height=self.height, bolt_spacing=self.spacing,
            min_length=max(12., specification['body_seating_footprint_mm'][1] + 6.),
            bolt_types=['M4'])

    def shape(self):
        shape = self.surface.shape()
        shape.rotate(App.Vector(), App.Vector(0, 0, 1), 90)
        shape.translate(self.seat)
        # Plate screws enter from above, outside the slit body's narrow X footprint.
        for dx in (-self.spacing / 2, self.spacing / 2):
            top = self.seat + App.Vector(dx, 0, .01)
            shape = shape.cut(Part.makeCylinder(2.25, self.height + .02, top, App.Vector(0, 0, -1)))
            shape = shape.cut(Part.makeCylinder(3.75, 4.41, top, App.Vector(0, 0, -1)))
        # The slit screw is fitted before the bracket is installed on the plate.
        bottom = self.seat - App.Vector(0, 0, self.height + .01)
        shape = shape.cut(Part.makeCylinder(2.25, self.height + .02, bottom))
        shape = shape.cut(Part.makeCylinder(3.75, 4.41, bottom))
        return shape.removeSplitter()

    def contract(self):
        floor = self.seat - App.Vector(0, 0, self.height)
        frames = [Frame('optical'), Frame('mounting_face', tuple(floor)),
                  Frame('slit_attachment', tuple(self.seat))]
        holes = [Hole('slit_attachment', 'slit_attachment', 4.5, self.height,
                      counterbore_mm=7.5, source='Fabricated clearance for VA100 8-32 attachment screw')]
        for name, dx in zip(('plate_left', 'plate_right'), (-self.spacing / 2, self.spacing / 2)):
            frames.append(Frame(name, tuple(floor + App.Vector(dx, 0, 0))))
            holes.append(Hole(name, name, 4.5, self.height, counterbore_mm=7.5,
                              source='Custom bracket M4 clearance, 25 mm spacing along beam axis'))
        return ComponentContract('va100-bracket', '1', 'Lab', '', 'fabricated',
            frames=tuple(frames), holes=tuple(holes), optical_reference='optical',
            provenance=(Provenance('PyOpticL Surface_Adapter; VA100 engineering drawing', 'documented',
                note='10 mm adapter; seating footprint plus 3 mm margin; three clearance bores. '
                     'Two accessible top M4 screw counterbores and one underside 8-32 screw counterbore.'),))

    def baseplate_profile(self):
        return dict(seat_frame='mounting_face', screws=['plate_left', 'plate_right'], dowels=[],
                    optical_height_mm=self.native_height + self.height,
                    source='Fabricated VA100 surface adapter, 25 mm M4 pattern; VA100 drawing M')

    def drill(self):
        return attachments.footprint(self)


def native_height(component):
    """Optical center above the selected seating face, including physical adapters."""
    contract = component.contract() if hasattr(component, 'contract') else None
    frames = {f.name: f for f in contract.frames} if contract else {}
    if 'mounting_face' in frames:
        return frames['optical'].position[2] - frames['mounting_face'].position[2]
    heights = []
    for child in component.get_object().Children:
        if attachments.profile(child.Proxy):
            heights.append(native_height(child.Proxy) - child.BasePlacement.Base.z)
        elif child.Children:
            heights.append(native_height(child.Proxy) - child.BasePlacement.Base.z)
    if not heights:
        raise ValueError('No selected mounting face for ' + (contract.catalog_id if contract else 'component'))
    if max(heights) - min(heights) > .01:
        raise ValueError('Assembly has inconsistent seating heights')
    return heights[0]


def _dofs(names, affects, source):
    axes = {'tip': (0, 1, 0), 'tilt': (0, 0, 1), 'axial': (1, 0, 0), 'rotation': (1, 0, 0), 'translation': (1, 0, 0)}
    return tuple(DOF(n, 'translation' if n in ('axial', 'translation') else 'rotation',
                     'optical' if n != 'translation' else 'stage', axes[n], affects, source) for n in names)


def _contract(kind, part, names, frames=None):
    frames = frames or (Frame('origin'), Frame('optical'))
    source = asset_record(part)['product_url']
    return ComponentContract(kind, '1', 'Lab', '', 'assembly', frames=frames,
        dofs=_dofs(names, 'optic' if kind != 'translation' else 'payload', source),
        optical_reference=None if kind == 'translation' else 'optical',
        provenance=(Provenance(source, 'documented'),))


def connection_interfaces():
    """Explicit commercial threads; unaffected by unit preferences."""
    return {
        'F260FC-1550': MechanicalInterface('body', 'optical', 'thread', Thread('M11 x 0.5', 'external', 11, .5)),
        'AD1109F-in': MechanicalInterface('collimator', 'optical', 'thread', Thread('M11 x 0.5', 'internal', 11, .5), engagement_mm=2.9972, seating='User-specified nominal thread-end alignment; available internal depth 6.35 mm.'),
        'AD1109F-out': MechanicalInterface('mount', 'optical', 'thread', Thread('SM05 (0.535-40)', 'external', 13.589, .635)),
        'KA05TA': MechanicalInterface('bore', 'optical', 'thread', Thread('SM05 (0.535-40)', 'internal', 13.589, .635)),
        'POLARIS-K05T6': MechanicalInterface('bore', 'optical', 'thread', Thread('SM05 (0.535-40)', 'internal', 13.589, .635),
            seating='AD1109F shoulder at front plate; remove the front POLARIS-SM05RR retaining ring.'),
        'fiber': MechanicalInterface('fiber', 'optical', 'fiber', connector='FC/PC'),
    }


def create(catalog_id, label, **parameters):
    """Construct an ordinary Component. Recompute it using the existing API.

    Parameters select mounts, optic thickness (mm), waveplate retardance/axis,
    iris aperture_diameter (mm), slit_width (mm), or roof orientation and
    beam_separation (mm). Unknown options fail explicitly.
    """
    if catalog_id in ('roof', 'HRS1015-P01'):
        from PyOpticL.roof_mirror import RoofGeometry, RoofOptic, MountedRoof
        unknown = set(parameters) - {'orientation', 'beam_separation'}
        if unknown:
            raise TypeError('Unsupported parameters: ' + ', '.join(sorted(unknown)))
        geometry = RoofGeometry(**parameters)
        return Component(label, MountedRoof(geometry) if catalog_id == 'roof' else RoofOptic(geometry))
    if catalog_id in VENDOR_IDS:
        if parameters:
            raise TypeError('Bare vendor mounts do not accept assembly parameters')
        return Component(label, VendorPart(catalog_id))
    if catalog_id not in CATALOG_IDS:
        raise KeyError('Unknown lab catalog ID: ' + catalog_id)
    allowed = {'mirror': {'thickness', 'mount'}, 'rotation': {'thickness', 'retardance', 'mount', 'fast_axis_angle'},
               'iris': {'aperture_diameter'}, 'coupling': {'mount'}, 'slit': {'slit_width'}}.get(catalog_id, set())
    if set(parameters) - allowed:
        raise TypeError('Unsupported parameters: ' + ', '.join(sorted(set(parameters) - allowed)))
    if 'thickness' in parameters and (not math.isfinite(parameters['thickness']) or parameters['thickness'] <= 0):
        raise ValueError('Thickness must be positive')
    if catalog_id == 'iris':
        return Component(label, AlignmentIris(**parameters))
    if catalog_id == 'mirror':
        thickness = parameters.get('thickness', 3.)
        part = parameters.get('mount', 'POLARIS-K05VS2')
        if part not in ('POLARIS-K05VS2', 'POLARIS-K1VS2', 'MHV-12.7L-R', 'MHV-25.4L-R'):
            raise ValueError('Unsupported mirror mount: ' + part)
        spec = json.loads((DATA / 'normalization.json').read_text())[part]
        bounds = spec.get('optic_thickness_range_mm', (0, math.inf))
        if not bounds[0] <= thickness <= bounds[1]:
            raise ValueError('Mirror thickness is outside the selected mount range')
        mount = VendorPart(part)
        offset = (0, 0, 0) if spec.get('mirror_loading') == 'rear' else (-thickness, 0, 0)
        definition = optics.Circular_Mirror(diameter=spec.get('optic_diameter_mm', 12.7),
            thickness=thickness, mount_definition=mount, mount_offset=offset)
        definition.contract = lambda: replace(_contract('mirror', part, ('tip', 'tilt')), procurement='generic')
        return Component(label, definition)
    if catalog_id == 'slit':
        definition = VariableSlit(parameters.get('slit_width', 1.))
        bracket = VA100Bracket()
        children = [('slit', definition, (0, 0, 0), (0, 0, 0)),
                    ('bracket', bracket, (0, 0, 0), (0, 0, 0)),
                    ('8-32 attachment screw', NominalScrew('8-32 UNC x 3/8 in', 4.1656, .79375,
                        9.525, 7.14, 4.166), tuple(bracket.seat - App.Vector(0, 0, 5.6)), (180, 0, 0))]
        children.extend((f'M4 plate screw {dx:g}', NominalScrew('M4 x 0.7 x 12 mm', 4, .7, 12, 7, 4),
                         tuple(bracket.seat + App.Vector(dx, 0, -4.4)), (0, 0, 0))
                        for dx in (-12.5, 12.5))
        contract = ComponentContract('slit', '1', 'Lab', '', 'assembly',
            frames=(Frame('optical'), Frame('native_mounting_face', tuple(bracket.seat)),
                    Frame('mounting_face', tuple(bracket.seat - App.Vector(0, 0, 10)))),
            optical_reference='optical', provenance=definition.contract().provenance)
        return Component(label, Assembly(contract, children))
    if catalog_id == 'coupling':
        part = parameters.get('mount', 'POLARIS-K05T6')
        if part not in ('KA05TA', 'POLARIS-K05T6'):
            raise ValueError('Unsupported coupling mount: ' + part)
        spec = json.loads((DATA / 'normalization.json').read_text())[part]
        exclusions = (6,) if part == 'KA05TA' else spec['coupling_excluded_solids']
        # Each transform is measured in the source STEP coordinate system.
        children = [
            ('collimator', VendorPart('F260FC-1550'), (0, 0, 0), (0, 0, 0)),
            ('adapter', VendorPart('AD1109F'), (0, 0, 0), (0, 0, 0)),
            ('mount', VendorPart(part, exclude_solids=exclusions), (8.0518, 0, 0), (0, 0, 0)),
        ]
        contract = replace(_contract('coupling', part, ('tip', 'tilt', 'axial')), provenance=(Provenance('https://www.thorlabs.com/item/AD1109F', 'documented', note='User-specified nominal placement: M11 thread-end plane aligned with AD1109F opening, 2.9972 mm from barrel front. SM05 shoulder seated against '+part+'. Front retaining ring removed. Static datum convention, not a torque or bottoming model. K05T6 simplified SM05 envelopes overlap only inside the nominal engagement annulus; physical thread phase is unverified.'),))
    elif catalog_id == 'pbs':
        definition = optics.Beamsplitter_Cube(side_length=12.7, ref_polarization=0,
            mount_definition=DisplacementPBSHolder(), mount_offset=(0, 0, 0))
        children = [('optic', definition, (0, 0, 0), (0, 0, 0))]
        contract = ComponentContract('pbs', '2', 'Lab', '', 'assembly', frames=(Frame('optical'),), optical_reference='optical', provenance=(Provenance('Data/Displacement setup/Displacement Mount Assembly.step', 'cad_verified', note='Center-piece PBS seat with relief trenches; fixed nominal placement.'),))
    elif catalog_id == 'rotation':
        part = parameters.get('mount', 'ELL16')
        if part not in ('ELL16', 'FBR'):
            raise ValueError('Unsupported rotation mount: ' + part)
        thickness = parameters.get('thickness', 1.)
        if part == 'FBR' and thickness > 4:
            raise ValueError('FBR supports optics up to 4 mm thick')
        for key in ('retardance', 'fast_axis_angle'):
            if not math.isfinite(parameters.get(key, 0)):
                raise ValueError(key + ' must be finite')
        mount = VendorPart(part, optic_thickness=thickness if part == 'FBR' else None)
        definition = optics.Circular_Waveplate(diameter=12.7, thickness=parameters.get('thickness', 1.),
            retardance=parameters.get('retardance', .5), fast_axis_angle=parameters.get('fast_axis_angle', 0),
            mount_definition=mount, mount_offset=(thickness / 2 if part == 'FBR' else 0, 0, 0))
        if part == 'FBR':
            contract = _contract('rotation', part, ('rotation',))
            return Component(label, Assembly(contract, [('optic', definition, (0, 0, 0), (0, 0, 0))]))
        children = [('optic', definition, (0, 0, 0), (0, 0, 0)),
                    ('holder', HOMHolder('rotation-holder'), (0, 0, 0), (0, 0, 0))]
        children.extend((f'cage screw {y} {z}', NominalScrew('4-40 UNC x 3/16 in',2.8448,.635,4.7625,4.76,2.84), (13,y,z),(0,90,0)) for y in (-15,15) for z in (-15,15))
        contract = _contract('rotation', 'ELL16', ('rotation',))
    else:
        children = [('stage', VendorPart('XR25C'), (0, 0, 0), (0, 0, 0))]
        contract = _contract('translation', 'XR25C', ('translation',),
            (Frame('origin'), Frame('stage'), Frame('payload', (0, 0, 23))))
    return Component(label, Assembly(contract, children))


def bom(component):
    """One row per leaf part, preserving purchased compounds as single items."""
    rows = []
    def visit(obj, path):
        proxy = obj.Proxy
        if hasattr(proxy, 'contract'):
            c = proxy.contract()
            if c.procurement != 'assembly':
                row = dict(path=path, catalog_id=c.catalog_id, part_number=c.part_number,
                           manufacturer=c.manufacturer, procurement=c.procurement, quantity=1)
                if attachments.integration_profile(proxy):
                    row.update(integrated_into='baseplate', separate_part=False)
                if c.part_number in VENDOR_IDS:
                    row['excluded_vendor_solids'] = list(getattr(proxy, 'exclude_solids', ()))
                    mounting = attachments.profile(proxy)
                    if mounting:
                        row['mounting_hardware'] = []
                        if mounting['screws']:
                            row['mounting_hardware'].append(dict(kind='M4 mounting screws', quantity=len(mounting['screws']),
                                note='Length/head selected for installation stack; plate uses M4 threads.'))
                        if mounting['dowels']:
                            row['mounting_hardware'].append(dict(kind=mounting['dowel']['pin'],
                                quantity=len(mounting['dowels']), included=c.part_number == 'FBR'))
                rows.append(row)
        elif hasattr(proxy, 'shape'):
            rows.append(dict(path=path, catalog_id='', part_number='', manufacturer='', procurement='generic', quantity=1))
        for child in obj.Children:
            visit(child, path + '/' + child.Label)
    visit(component.get_object(), component.get_object().Label)
    # Included accessories are not additional purchases.
    for row in list(rows):
        if row['part_number'] == 'KA05TA':
            rows.extend([dict(path=row['path'] + '/SM05KRR', catalog_id='SM05KRR',
                part_number='SM05KRR', manufacturer='Thorlabs', procurement='included',
                quantity=1, disposition=state, included_in='KA05TA')
                for state in ('installed rear ring (in vendor compound)', 'uninstalled front ring; removed for AD1109F')])
        elif row['part_number'] == 'POLARIS-K05T6':
            spec = json.loads((DATA / 'normalization.json').read_text())['POLARIS-K05T6']['included_retaining_rings']
            rows.extend(dict(path=row['path'] + '/' + side + ' retaining ring', catalog_id=spec['part'],
                part_number=spec['part'], manufacturer='Thorlabs', procurement='included', quantity=1,
                included_in='POLARIS-K05T6', disposition=('uninstalled; removed for AD1109F' if
                    spec[side + '_solid'] in row['excluded_vendor_solids'] else 'installed in vendor compound'))
                for side in ('front', 'rear'))
        elif row['part_number'] in ('POLARIS-L05G', 'POLARIS-L1G'):
            rows.append(dict(path=row['path']+'/included washer', catalog_id='flat washer', part_number='',
                manufacturer='Thorlabs', procurement='included', quantity=1, included_in=row['part_number'],
                disposition='Included #8/M4 flat washer per drawing; not present in supplier STEP'))
        elif row['part_number'] == 'FBR':
            rows.append(dict(path=row['path']+'/SM05RR', catalog_id='SM05RR', part_number='SM05RR',
                manufacturer='Thorlabs', procurement='included', quantity=1, included_in='FBR',
                disposition='Installed retaining ring; positioned against optic when assembled'))
    return rows


def report_dofs(component, relative_to=None):
    """Report axes in world or another layout's coordinates, without recomputing."""
    contract = component.contract()
    rotation = component.get_object().Placement.Rotation
    if relative_to is not None:
        rotation = relative_to.get_object().Placement.Rotation.inverted() * rotation
    frames = {f.name: f for f in contract.frames}
    result = []
    for dof in contract.dofs:
        local = App.Rotation('XYZ', *frames[dof.frame].rotation).multVec(App.Vector(*dof.axis))
        result.append(dict(name=dof.name, kind=dof.kind, axis=tuple(rotation.multVec(local)),
                           affects=dof.affects, limits=dof.limits, source=dof.source))
    return result
