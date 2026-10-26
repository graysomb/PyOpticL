"""Measured HRS1015-P01 optics and user-corrected integral baseplate supports.

The cavity is air. Optical spacing chooses input/output alignment datums, not
the physical facet separation and not a forced displacement of arbitrary rays.
"""
import json
import math
import numpy as np
import FreeCAD as App
import Part

from PyOpticL import attachments
from PyOpticL.beam_path import Interface, Reflection
from PyOpticL.component_contract import ComponentContract, Frame, Hole, MechanicalInterface, Provenance
from PyOpticL.lab_catalog import (DATA, Assembly, NominalScrew, _blind_bore,
                                 asset_record, profile, transform, vendor_shape)

PART = 'HRS1015-P01'
URL = 'https://www.thorlabs.com/item/' + PART


def reference():
    return json.loads((DATA / 'roof_mirror_reference.json').read_text())


class RoofGeometry:
    """One source of facet planes, bounds, datums and orientation transforms."""
    def __init__(self, orientation='horizontal', beam_separation=12.7):
        if orientation not in ('horizontal', 'vertical'):
            raise ValueError('orientation must be horizontal or vertical')
        if not math.isfinite(beam_separation) or beam_separation <= 0:
            raise ValueError('beam_separation must be finite and positive')
        self.orientation, self.separation = orientation, float(beam_separation)
        self.roll = 0 if orientation == 'horizontal' else -90
        self.rotation = App.Rotation('XYZ', self.roll, 0, 0)
        self.matrix = np.array([list(self.rotation.multVec(App.Vector(*v)))
                                for v in np.eye(3)]).T
        self.center = np.array((0., -self.separation/2, 0.) if self.roll == 0
                               else (0., 0., self.separation/2))
        self.output = 2 * self.center
        model = reference()['facet_model']
        self.centers = np.array(model['center_mm'])
        self.normals = np.array([(-1, -1, 0), (-1, 1, 0)]) / math.sqrt(2)
        self.transverses = np.array([(1, -1, 0), (1, 1, 0)]) / math.sqrt(2)
        self.width, self.height = model['physical_width_mm'], model['physical_height_mm']
        self.clear_fraction = model['clear_fraction']
        if self.trace((0,0,0), (1,0,0)) is None:
            raise ValueError('Nominal beam spacing lies outside the modeled clear aperture')

    def point(self, canonical):
        return self.center + self.matrix @ np.asarray(canonical)

    def canonical(self, point):
        return self.matrix.T @ (np.asarray(point) - self.center)

    def inside_face(self, point, index, clear=True):
        delta = np.asarray(point) - self.centers[index]
        fraction = self.clear_fraction if clear else 1.
        return (abs(delta @ self.transverses[index]) < self.width * fraction / 2 - 1e-8
                and abs(delta[2]) < self.height * fraction / 2 - 1e-8)

    def trace(self, origin, direction):
        """Validate an actual ray from the front plane through both finite faces.

        Used to guard the entrance. Actual BeamPath propagation still traverses
        each reflection and each free-space segment independently.
        """
        p = self.canonical(origin)
        d = self.matrix.T @ np.asarray(direction, dtype=float)
        norm = np.linalg.norm(d)
        if not np.isfinite(norm) or norm < 1e-12:
            return None
        d = d / norm
        if abs(p[0]) > 1e-6 or d[0] <= 1e-8:
            return None
        hits, order = [], []
        for _ in range(2):
            candidates = []
            for i, n in enumerate(self.normals):
                denom = d @ n
                if denom >= -1e-8:
                    continue
                distance = (self.centers[i] - p) @ n / denom
                q = p + distance * d
                if distance > 1e-6 and self.inside_face(q, i, clear=False):
                    candidates.append((distance, i, q))
            if not candidates:
                return None
            _, i, q = min(candidates, key=lambda item: item[0])
            if i in order or not self.inside_face(q, i):
                return None
            hits.append(self.point(q)); order.append(i)
            n = self.normals[i]
            d = d - 2 * (d @ n) * n
            p = q
        if d[0] >= -1e-8:
            return None
        distance = -p[0] / d[0]
        exit_point = p + distance * d
        if distance <= 1e-6 or max(abs(exit_point[1]), abs(exit_point[2])) >= 12.7:
            return None
        return dict(hits=hits, exit=self.point(exit_point), direction=self.matrix @ d)

    @property
    def input_height(self):
        return 12.7 - float(self.center[2])

    def frames(self, mounted=False):
        frames = [Frame('origin'), Frame('optical'), Frame('input'),
                  Frame('output', tuple(self.output), (0,0,180)),
                  Frame('roof_front_center', tuple(self.center)),
                  Frame('roof_edge', tuple(self.point((12.7,0,0))), (self.roll,0,0))]
        for i, c in enumerate(self.centers):
            n = self.matrix @ self.normals[i]
            u = self.matrix @ self.transverses[i]
            angles = App.Rotation(App.Vector(*n), App.Vector(*u),
                App.Vector(*np.cross(n, u)), 'XYZ').toEulerAngles('XYZ')
            frames.append(Frame('facet_' + str(i+1), tuple(self.point(c)), tuple(angles)))
        frames.append(Frame('optic_bottom', tuple(self.center + (0,0,-12.7))))
        frames.append(Frame('mounting_face', tuple(self.center + (0,0,-12.7)), (180,0,0)))
        if mounted:
            frames.extend((Frame('plate_top', tuple(self.center + (0,0,-12.7)), (180,0,0)),
                           Frame('stock_bottom', tuple(self.center + (0,0,-25.4)), (180,0,0))))
        return frames


class RoofFacet(Reflection):
    role = 'reflection'
    output_boundary = False

    def __init__(self, geometry, index):
        self.geometry, self.index = geometry, index
        self.name = 'facet_' + str(index+1)
        super().__init__(tuple(geometry.point(geometry.centers[index])), (0,0,0),
                         diameter=100, single_sided=True)
        self.normal = geometry.matrix @ geometry.normals[index]
        self.transverse = geometry.matrix @ geometry.transverses[index]

    def get_intercept(self, beam):
        point = super().get_intercept(beam)
        if point is None:
            return None
        local = self.parent.get_object().Placement.inverse().multVec(App.Vector(*point))
        return point if self.geometry.inside_face(self.geometry.canonical(local), self.index) else None


class RoofBoundary(Interface):
    def __init__(self, geometry, role):
        self.geometry, self.role, self.name = geometry, role, role
        self.output_boundary = role == 'exit'
        position = tuple(geometry.output) if role == 'exit' else (0,0,0)
        super().__init__(position, (0,0,180 if role == 'entry' else 0),
                         diameter=100, single_sided=True)

    def get_intercept(self, beam):
        point = super().get_intercept(beam)
        if point is None:
            return None
        local = self.parent.get_object().Placement.inverse().multVec(App.Vector(*point))
        p = self.geometry.canonical(local)
        return point if max(abs(p[1]), abs(p[2])) <= 12.7 else None

    def get_output_beams(self, beam):
        if self.role == 'entry':
            point = self.get_intercept(beam)
            if point is None:
                return []
            inverse = self.parent.get_object().Placement.inverse()
            local = inverse.multVec(App.Vector(*point))
            direction = inverse.Rotation.multVec(App.Vector(*beam.get_global_direction()))
            if self.geometry.trace(local, direction) is None:
                return []
        return super().get_output_beams(beam)


def optical_interfaces(geometry):
    return [RoofBoundary(geometry, 'entry'), RoofFacet(geometry, 0),
            RoofFacet(geometry, 1), RoofBoundary(geometry, 'exit')]


def provenance():
    r = reference()
    return (Provenance(URL, 'cad_verified', r['step_sha256'],
        'Original three solids preserved; nominal 90 degree hollow roof. '
        'TTN048987-E0W drawing B; centered 80% trimmed-face clear rectangle is a modeling assumption. '
        'Air path; ideal reflection without coating phase, dispersion or diffraction.'),
        Provenance('TTN048987-E0W revision B', 'documented', r['drawing_sha256']))


class RoofOptic:
    preserve_topology = True
    apply_drilling = False
    object_group = 'optics'
    object_color = (.72,.76,.8)
    part_numbers = [PART]

    def __init__(self, geometry, optical=True):
        self.geometry, self.optical = geometry, optical

    def shape(self):
        r = reference()
        if asset_record(PART)['sha256'] != r['step_sha256']:
            raise ValueError('Roof CAD revision requires new datum verification')
        shape = transform(vendor_shape(PART), **r['normalization'])
        shape = transform(shape, rotation=(self.geometry.roll,0,0))
        return transform(shape, origin=tuple(-self.geometry.center))

    def interfaces(self):
        return optical_interfaces(self.geometry) if self.optical else []

    def contract(self):
        return ComponentContract(PART, '1', 'Thorlabs', PART, 'purchased',
            frames=tuple(self.geometry.frames()), optical_reference='input', provenance=provenance())


def support_reference(geometry):
    return json.loads((DATA / 'roof_support_reference.json').read_text())['orientations'][geometry.orientation]


def support_point(geometry, point):
    """The user files already contain the chosen roof orientation."""
    x, y, z = point
    return geometry.center + (18.7-y, x, z)


def support_shape(geometry, shape):
    shape = transform(shape, (0,18.7,0), (0,0,90))
    return transform(shape, origin=tuple(-geometry.center))


def support_provenance(geometry):
    spec = support_reference(geometry)
    return (Provenance(spec['source'], 'cad_verified', spec['sha256'],
        'User-corrected integral baseplate support and removable clamp. Native profiles rebuilt; '
        'blind hole adapted to M2 x 0.4, 1.6 mm tap drill with 118 degree tip; '
        'slot widened to 2.2 mm for M2 clearance. No carrier, M4 attachments or dowels.'),)


def capsule(ends, diameter, bottom, height):
    a, b = [App.Vector(p[0], p[1], bottom) for p in ends]
    direction = b-a
    perpendicular = App.Vector(-direction.y, direction.x, 0)
    perpendicular.normalize()
    perpendicular *= diameter/2
    points = [a+perpendicular, b+perpendicular, b-perpendicular, a-perpendicular]
    body = Part.Face(Part.makePolygon(points + [points[0]])).extrude(App.Vector(0,0,height))
    return body.fuse(Part.makeCylinder(diameter/2,height,a)).fuse(Part.makeCylinder(diameter/2,height,b))


class RoofSupport:
    """Reference stock patch and raised stops, fused directly into the plate."""
    object_group = 'adapters'
    object_color = (.55,.62,.68)
    apply_drilling = False
    drill_groups = ('baseplate',)
    part_numbers = []

    def __init__(self, geometry):
        self.geometry = geometry
        self.spec = support_reference(geometry)

    def shape(self):
        shape = Part.makeBox(38.1,38.1,12.7,App.Vector(-19.05,-13.3,-25.4))
        for name in self.spec['stop_profiles']:
            shape = shape.fuse(profile(name).extrude(App.Vector(0,0,-self.spec['stop_height_mm'])))
        shape = shape.cut(_blind_bore(self.spec['hole_center_mm'],self.spec['tap_drill_mm'],
            self.spec['hole_depth_mm'],(0,0,-1)))
        return support_shape(self.geometry,shape.removeSplitter())

    def contract(self):
        frames = self.geometry.frames(mounted=True)
        frames.append(Frame('clamp_tap',tuple(support_point(self.geometry,self.spec['hole_center_mm'])),(180,0,0)))
        return ComponentContract('roof-integral-support','2','Lab',
            'HRS-INTEGRAL-'+self.geometry.orientation.upper(),'fabricated',
            frames=tuple(frames),
            holes=(Hole('clamp_tap','clamp_tap',self.spec['tap_drill_mm'],self.spec['hole_depth_mm'],
                self.spec['thread'],source='User-corrected design; M2 tap drill, 118 degree tip; '
                +str(self.spec['usable_thread_mm'])+' mm usable thread'),),
            interfaces=(MechanicalInterface('optic_seat','optic_bottom','seating',
                seating='User-corrected stops integral with baseplate; separate slotted clamp.'),),
            optical_reference='input',provenance=support_provenance(self.geometry))

    def baseplate_integration(self):
        return dict(seat_frame='plate_top',holes=['clamp_tap'],source=self.spec['source'],
                    thread_depth_mm=self.spec['usable_thread_mm'],source_sha256=self.spec['sha256'])

    def drill(self):
        return Part.makeCompound([attachments.bore(op) for op in attachments.integration_operations(self)])


class RoofClamp:
    object_group = 'adapters'
    object_color = (.55,.62,.68)
    apply_drilling = False
    part_numbers = []

    def __init__(self, geometry):
        self.geometry = geometry
        self.spec = support_reference(geometry)

    def shape(self):
        shape = profile(self.spec['clamp_profile']).extrude(App.Vector(0,0,self.spec['clamp_thickness_mm']))
        slot = capsule(self.spec['slot_end_centers_mm'],self.spec['clamp_slot_width_mm'],
                       -12.71,self.spec['clamp_thickness_mm']+.02)
        return support_shape(self.geometry,shape.cut(slot).removeSplitter())

    def contract(self):
        center = App.Vector(*self.spec['hole_center_mm']) + App.Vector(0,0,self.spec['clamp_thickness_mm'])
        frames = [Frame('origin'), Frame('clamp_slot',tuple(support_point(self.geometry,center)),(180,0,0))]
        frames.extend(Frame('slot_end_'+str(i+1),tuple(support_point(self.geometry,p)))
                      for i,p in enumerate(self.spec['slot_end_centers_mm']))
        return ComponentContract('roof-clamp','2','Lab',
            'HRS-CLAMP-'+self.geometry.orientation.upper(),'fabricated',frames=tuple(frames),
            holes=(Hole('clamp_slot','clamp_slot',self.spec['clamp_slot_width_mm'],
                self.spec['clamp_thickness_mm'],source='M2 clearance capsule; centers in slot_end_1/2 frames'),),
            provenance=support_provenance(self.geometry))


class MountedRoof(Assembly):
    def __init__(self, geometry):
        self.geometry = geometry
        spec = support_reference(geometry)
        contract = ComponentContract('roof','2','Lab','','assembly',
            frames=tuple(geometry.frames(mounted=True)),optical_reference='input',
            provenance=provenance()+support_provenance(geometry))
        center = App.Vector(*spec['hole_center_mm']) + App.Vector(0,0,spec['clamp_thickness_mm'])
        screw = NominalScrew('M2 x 0.4 x '+str(int(spec['screw_length_mm']))+' mm',
                            2,.4,spec['screw_length_mm'],3.8,2)
        children = [('HRS1015-P01',RoofOptic(geometry,optical=False),(0,0,0),(0,0,0)),
                    ('Integral roof supports',RoofSupport(geometry),(0,0,0),(0,0,0)),
                    ('Removable slotted clamp',RoofClamp(geometry),(0,0,0),(0,0,0)),
                    ('M2 clamp screw',screw,tuple(support_point(geometry,center)),(0,0,0))]
        super().__init__(contract,children)

    def interfaces(self):
        return optical_interfaces(self.geometry)
