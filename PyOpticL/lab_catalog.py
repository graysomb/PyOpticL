"""Small nominal-position lab catalog, extending the ordinary component API.

No DOF is a placement input. Cached vendor files are verified before import.
"""
from functools import lru_cache
from dataclasses import replace
import json
from pathlib import Path
import FreeCAD as App
import Part
from PyOpticL.component_contract import ComponentContract, DOF, Frame, Hole, MechanicalInterface, Provenance, Thread
from PyOpticL.layout import Component, Subcomponent
from PyOpticL.vendor_cad import resolve
from PyOpticL.library import optics

DATA = Path(__file__).with_name('catalog_data')
CATALOG_IDS = ('mirror', 'coupling', 'pbs', 'rotation', 'translation')


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

    def __init__(self, part, contract=None, exclude_solids=()):
        self.part = part
        self.part_numbers = [part]
        specification = json.loads((DATA / 'normalization.json').read_text())[part]
        self.origin, self.rotation = specification['origin'], specification['rotation']
        self._contract = contract
        self.exclude_solids = tuple(exclude_solids)

    def shape(self):
        shape = vendor_shape(self.part)
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
                      'AD1109F': (replace(pairs['AD1109F-in'], frame='collimator_opening', seating='M11 end faces the collimator; opposed to mount end.'), replace(pairs['AD1109F-out'], frame='mount_seat', engagement_mm=3.175, seating='Shoulder against KA05TA front; remove front SM05KRR.')),
                      'KA05TA': (replace(pairs['KA05TA'], frame='adapter_seat', seating='Front plate plane; adapter enters along local +X.'),)}.get(self.part, ())
        if self.part == 'POLARIS-K05VS2':
            interfaces += (MechanicalInterface('dowel_slot', 'dowel_slot', 'slot',
                seating='2.00914 mm wide alignment slot at native X=+5 mm; mates to one round 2 mm pin. Round feature at X=-5 mm.'),)
        names = {'POLARIS-K05VS2': ('tip','tilt'), 'KA05TA': ('tip','tilt','axial'),
                 'ELL16': ('rotation',)}.get(self.part, ())
        if self.part == 'XR25C':
            frames.append(Frame('stage'))
            names = ('translation',)
        return ComponentContract(self.part, '1', 'Thorlabs', self.part, 'purchased',
            frames=tuple(frames), interfaces=interfaces, holes=tuple(holes),
            dofs=_dofs(names, 'attached optic' if self.part != 'XR25C' else 'payload', record['product_url']),
            provenance=(Provenance(record['product_url'], 'documented', record['sha256'],
                'Vendor nominal compound; see normalization and independent reference measurements.'),))



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


def _dofs(names, affects, source):
    axes = {'tip': (0, 1, 0), 'tilt': (0, 0, 1), 'axial': (1, 0, 0), 'rotation': (1, 0, 0), 'translation': (1, 0, 0)}
    return tuple(DOF(n, 'translation' if n in ('axial', 'translation') else 'rotation',
                     'optical' if n != 'translation' else 'stage', axes[n], affects, source) for n in names)


def _contract(kind, part, names, frames=None):
    frames = frames or (Frame('origin'), Frame('optical'))
    return ComponentContract(kind, '1', 'Lab', '', 'assembly', frames=frames,
        dofs=_dofs(names, 'optic' if kind != 'translation' else 'payload', 'https://www.thorlabs.com/item/' + part),
        optical_reference=None if kind == 'translation' else 'optical',
        provenance=(Provenance('https://www.thorlabs.com/item/' + part, 'documented'),))


def connection_interfaces():
    """Explicit commercial threads; unaffected by unit preferences."""
    return {
        'F260FC-1550': MechanicalInterface('body', 'optical', 'thread', Thread('M11 x 0.5', 'external', 11, .5)),
        'AD1109F-in': MechanicalInterface('collimator', 'optical', 'thread', Thread('M11 x 0.5', 'internal', 11, .5), engagement_mm=2.9972, seating='User-specified nominal thread-end alignment; available internal depth 6.35 mm.'),
        'AD1109F-out': MechanicalInterface('mount', 'optical', 'thread', Thread('SM05 (0.535-40)', 'external', 13.589, .635)),
        'KA05TA': MechanicalInterface('bore', 'optical', 'thread', Thread('SM05 (0.535-40)', 'internal', 13.589, .635)),
        'fiber': MechanicalInterface('fiber', 'optical', 'fiber', connector='FC/PC'),
    }


def create(catalog_id, label, **parameters):
    """Construct an ordinary Component. Recompute it using the existing API.

    Supported parameters: mirror thickness (mm), waveplate thickness (mm), and
    waveplate retardance. Unknown options fail rather than silently changing fit.
    """
    if catalog_id not in CATALOG_IDS:
        raise KeyError('Unknown lab catalog ID: ' + catalog_id)
    allowed = {'mirror': {'thickness'}, 'rotation': {'thickness', 'retardance'}}.get(catalog_id, set())
    if set(parameters) - allowed:
        raise TypeError('Unsupported parameters: ' + ', '.join(sorted(set(parameters) - allowed)))
    if 'thickness' in parameters and parameters['thickness'] <= 0:
        raise ValueError('Thickness must be positive')
    if catalog_id == 'mirror':
        thickness = parameters.get('thickness', 3.)
        mount = VendorPart('POLARIS-K05VS2')
        definition = optics.Circular_Mirror(diameter=12.7, thickness=thickness, mount_definition=mount)
        definition.contract = lambda: replace(_contract('mirror', 'POLARIS-K05VS2', ('tip', 'tilt')), procurement='generic')
        return Component(label, definition)
    if catalog_id == 'coupling':
        # Each transform is measured in the source STEP coordinate system.
        children = [
            ('collimator', VendorPart('F260FC-1550'), (0, 0, 0), (0, 0, 0)),
            ('adapter', VendorPart('AD1109F'), (0, 0, 0), (0, 0, 0)),
            ('mount', VendorPart('KA05TA', exclude_solids=(6,)), (8.0518, 0, 0), (0, 0, 0)),
        ]
        contract = replace(_contract('coupling', 'KA05TA', ('tip', 'tilt', 'axial')), provenance=(Provenance('https://www.thorlabs.com/item/AD1109F', 'cad_verified', note='User-specified nominal placement: M11 thread-end plane aligned with AD1109F opening, 2.9972 mm from barrel front. SM05 shoulder seated against KA05TA. This is a static datum convention, not a thread torque or bottoming model.'),))
    elif catalog_id == 'pbs':
        definition = optics.Beamsplitter_Cube(side_length=12.7, ref_polarization=0,
            mount_definition=DisplacementPBSHolder(), mount_offset=(0, 0, 0))
        children = [('optic', definition, (0, 0, 0), (0, 0, 0))]
        contract = ComponentContract('pbs', '2', 'Lab', '', 'assembly', frames=(Frame('optical'),), optical_reference='optical', provenance=(Provenance('Data/Displacement setup/Displacement Mount Assembly.step', 'cad_verified', note='Center-piece PBS seat with relief trenches; fixed nominal placement.'),))
    elif catalog_id == 'rotation':
        mount = VendorPart('ELL16')
        definition = optics.Circular_Waveplate(diameter=12.7, thickness=parameters.get('thickness', 1.),
            retardance=parameters.get('retardance', .5), mount_definition=mount, mount_offset=(0, 0, 0))
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
                rows.append(dict(path=path, catalog_id=c.catalog_id, part_number=c.part_number,
                                 manufacturer=c.manufacturer, procurement=c.procurement, quantity=1))
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
