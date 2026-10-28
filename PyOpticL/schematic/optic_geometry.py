"""Finite optical bodies/interfaces without FreeCAD or a vendor CAD cache."""

from dataclasses import dataclass
from functools import lru_cache
import json
from math import hypot, sqrt
from pathlib import Path
from PyOpticL.ray_math import add, mul, sub, trace_roof, grating_surface_angle
from .registry import parameter_values, default_turn, COUPLING_MOUNTS, D_MIRROR_PRESETS, d_mirror_geometry


@dataclass(frozen=True)
class OpticalElementSpec:
    size: tuple
    corner: tuple
    aperture: tuple
    normal_angle: float = 0
    single_sided: bool = False
    aperture_only: bool = False
    aperture_center: tuple = (0, 0, 0)
    through_length: float = 0


def element_spec(node, topology=None):
    p = parameter_values(node)
    diameter, thickness = p.get("diameter", 12.7), p.get("thickness", 1.0)
    if node.kind == "mirror":
        if node.preset in D_MIRROR_PRESETS:
            geometry = d_mirror_geometry(node.preset)
            radius, edge = geometry["radius_mm"], p["edge_distance"]
            return OpticalElementSpec(
                (geometry["thickness_mm"], 2 * radius, radius),
                (-geometry["thickness_mm"], -radius, edge - radius),
                ("semicircle", geometry["clear_radius_mm"], geometry["straight_edge_bevel_mm"]),
                single_sided=True, aperture_center=(0, 0, edge),
            )
        return OpticalElementSpec(
            (thickness if "thickness" in p else 6, diameter, diameter),
            (-(thickness if "thickness" in p else 6), -diameter / 2, -diameter / 2),
            ("circle", diameter / 2),
            single_sided=True,
        )
    if node.kind in ("lens", "hwp", "qwp"):
        thickness = p.get("thickness", 2 if node.kind == "lens" else 1)
        return OpticalElementSpec(
            (thickness, diameter, diameter),
            (-thickness / 2, -diameter / 2, -diameter / 2),
            ("circle", diameter / 2),
        )
    if node.kind == "splitter":
        side = p["side_length"]
        return OpticalElementSpec(
            (side, side, side), (-side / 2,) * 3, ("rect", side / sqrt(2), side / 2), -45
        )
    if node.kind == "iris":
        outer = 20 if node.preset == "alignment" else 12.7
        return OpticalElementSpec(
            (4, outer, 22.7) if node.preset == "alignment" else (0, outer, outer),
            (-2, -10, -12.7) if node.preset == "alignment" else (0, -outer / 2, -outer / 2),
            ("circle", p.get("aperture_diameter", p.get("pinhole_diameter", 1)) / 2),
            aperture_only=node.preset != "alignment",
        )
    if node.kind == "slit":
        return OpticalElementSpec(
            (0, 13.589, 13.589),
            (0, -13.589 / 2, -13.589 / 2),
            ("slit", 13.589 / 2, p["slit_width"] / 2),
            aperture_only=True,
        )
    if node.kind == "crystal":
        return OpticalElementSpec((27.4, 4, 1), (-13.7, -2, -.5), ("rect", 2, .5), through_length=27.4)
    if node.kind == "grating":
        return OpticalElementSpec(
            (0.95, 31.8, 12.3), (0, -15.9, -6.15), ("rect", 15.4, 5.65),
            grating_surface_angle(p["incidence_angle"], p["mirrored"])
        )
    if node.kind == "roof":
        sep = p["beam_separation"]
        vertical = "vertical" in node.preset
        reverse = topology and topology.incident_ports.get(node.id) == "B"
        center = (0, 0, sep / 2) if vertical else (0, -sep / 2, 0)
        if reverse:
            center = mul(center, -1)
        return OpticalElementSpec(
            (18.7, 25.4, 25.4), add((0, -12.7, -12.7), center), ("rect", 12.7, 12.7), aperture_center=center
        )
    if node.kind in ("fiber_source", "fiber_output"):
        radius = 2.5 if node.preset in COUPLING_MOUNTS else 12.5
        return OpticalElementSpec(
            (0, 2 * radius, 2 * radius),
            (0, -radius, -radius),
            ("circle", radius),
            single_sided=node.preset not in COUPLING_MOUNTS,
            aperture_only=True,
        )
    if node.kind == "stop":
        return OpticalElementSpec(
            (3, diameter, diameter),
            (-3, -diameter / 2, -diameter / 2),
            ("circle", diameter / 2),
            single_sided=True,
        )
    return None


def aperture_excess(spec, local, direction=None):
    if spec.through_length and direction is not None:
        if abs(direction[0]) < 1e-6:
            return 1e6
        return max(aperture_excess(spec, add(local, mul(direction, (x-local[0])/direction[0])))
                   for x in (-spec.through_length/2, spec.through_length/2))
    local = sub(local, spec.aperture_center)
    shape, *sizes = spec.aperture
    if shape == "circle":
        return hypot(local[1], local[2]) - sizes[0]
    if shape == "semicircle":
        return max(hypot(local[1], local[2]) - sizes[0], local[2] + sizes[1])
    if shape == "slit":
        return max(hypot(local[1], local[2]) - sizes[0], abs(local[2]) - sizes[1])
    return max(abs(local[1]) - sizes[0], abs(local[2]) - sizes[1])


@lru_cache(maxsize=1)
def roof_model():
    return json.loads(
        (Path(__file__).resolve().parents[1] / "catalog_data/roof_mirror_reference.json").read_text()
    )["facet_model"]


def roof_trace(point, direction, separation, vertical=False, reverse=False):
    center = (0, 0, separation / 2) if vertical else (0, -separation / 2, 0)
    if reverse:
        center = mul(center, -1)
    return trace_roof(point, direction, center, vertical, roof_model())
