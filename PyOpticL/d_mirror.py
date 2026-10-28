"""Purchased D-shaped pickoff mirrors, with matching left- and right-hand mounts.

The optical origin lies edge_distance below the straight edge (default 1 mm).
+X is the outward front normal, +Z points toward the open half.
"""
from dataclasses import replace
import json
import math
import FreeCAD as App
import Part

from PyOpticL.beam_path import Reflection
from PyOpticL.component_contract import ComponentContract, Frame
from PyOpticL.lab_catalog import Assembly, DATA, VendorPart


def reference():
    return json.loads((DATA / 'd_mirror_reference.json').read_text())


class DReflection(Reflection):
    """Finite semicircle; rays beyond the straight edge pass without interaction.

    The 90%-diameter clear semicircle and 0.1 mm straight-edge exclusion are
    conservative boundaries from the drawing. Border hits terminate. Reflection,
    Gaussian propagation, power and Jones behavior use the existing mirror.
    """
    def __init__(self, radius, clear_radius, edge_bevel, edge_distance):
        super().__init__((0, 0, 0), (0, 0, 0), diameter=3 * radius,
                         max_angle=90, single_sided=True)
        self.radius, self.clear_radius, self.edge_bevel = radius, clear_radius, edge_bevel
        self.edge_distance = edge_distance
        self.name, self.role = 'D-shaped front surface', 'reflection'

    def _coordinates(self, point):
        local = self.parent.get_object().Placement.inverse().multVec(App.Vector(*point))
        return local.y, local.z - self.edge_distance

    def get_intercept(self, incident_beam):
        point = super().get_intercept(incident_beam)
        if point is None:
            return None
        y, z = self._coordinates(point)
        return point if z <= 0 and y*y + z*z <= self.radius*self.radius else None

    def get_output_beams(self, incident_beam):
        point = self.get_intercept(incident_beam)
        if point is None:
            return []
        y, z = self._coordinates(point)
        if z >= -self.edge_bevel or y*y + z*z >= self.clear_radius*self.clear_radius:
            return []
        return super().get_output_beams(incident_beam)


class DMirror(VendorPart):
    object_group = 'optics'
    object_color = (.65, .68, .85)

    def __init__(self, part, edge_distance=1., trace=True):
        if part not in ('PFD05-03-P01', 'PFD10-03-P01'):
            raise ValueError('Unsupported D mirror: ' + str(part))
        super().__init__(part)
        self.specification = reference()['parts'][part]
        if not math.isfinite(edge_distance) or not .1 < edge_distance < self.specification['clear_radius_mm']:
            raise ValueError('edge_distance must lie inside the clear semicircle, beyond the 0.1 mm bevel')
        self.edge_distance = edge_distance
        self.origin[1] += edge_distance - 1.
        self.trace = trace

    def interface(self):
        s = self.specification
        return DReflection(s['radius_mm'], s['clear_radius_mm'], s['straight_edge_bevel_mm'], self.edge_distance)

    def interfaces(self):
        return [self.interface()] if self.trace else []

    def contract(self):
        return replace(super().contract(), optical_reference='optical')


class SeatedDMirrorMount(VendorPart):
    """Translate existing clamp screws along their axes to the 6 mm optic face."""
    def __init__(self, part, edge_distance=1.):
        super().__init__(part)
        self.edge_distance = edge_distance
        # Source frames differ between handed variants. Select the same lower
        # optical datum in the normalized frame, without moving the hardware.
        shift = App.Rotation('XYZ', *self.rotation).inverted().multVec(
            App.Vector(0, 0, -(edge_distance - 1.)))
        self.origin = list(App.Vector(*self.origin) + shift)

    def baseplate_profile(self):
        profile = super().baseplate_profile()
        profile['optical_height_mm'] -= self.edge_distance - 1.
        for pocket in profile.get('clearance_pockets', []):
            pocket['origin_mm'][2] += self.edge_distance - 1.
        return profile

    def shape(self):
        shape = super().shape()
        offsets = reference()['pairs'][self.part].get('seated_clamp_offsets_mm', {})
        if not offsets:
            return shape
        solids = [s.copy() for s in shape.Solids]
        for index, vector in offsets.items():
            solids[int(index)].translate(App.Vector(*vector))
        return Part.makeCompound(solids)


class MountedDMirror(Assembly):
    def __init__(self, mount='KM05DR', optic=None, edge_distance=1.):
        pairs = reference()['pairs']
        if mount not in pairs:
            raise ValueError('Unsupported D-mirror mount: ' + str(mount))
        expected = pairs[mount]['optic']
        optic = expected if optic is None else optic
        if optic != expected:
            raise ValueError(mount + ' requires ' + expected)
        mirror = DMirror(optic, edge_distance, trace=False)
        holder = SeatedDMirrorMount(mount, edge_distance)
        self.mirror_definition = mirror
        mounting = next(f for f in holder.contract().frames if f.name == 'mounting_face')
        contract = ComponentContract('d_mirror', '1', 'Lab', '', 'assembly',
            frames=(Frame('optical'), mounting), optical_reference='optical',
            dofs=holder.contract().dofs,
            provenance=holder.contract().provenance + mirror.contract().provenance)
        super().__init__(contract, [('mirror', mirror, (0, 0, 0), (0, 0, 0)),
                                   ('mount', holder, (0, 0, 0), (0, 0, 0))])

    def interfaces(self):
        # The assembly owns the interaction so downstream queries identify it.
        return [self.mirror_definition.interface()]
