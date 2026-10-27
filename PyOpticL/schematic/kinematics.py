"""CAD-independent fixed offsets and internal air paths of catalog assemblies."""

from math import cos, radians, sin
from .registry import parameter_values

ROOF_AIR_PATH_MM = 25.4


def roof_shift(node, topology):
    separation = parameter_values(node)["beam_separation"]
    reverse = topology.incident_ports.get(node.id) == "B"
    direction = -1 if reverse else 1
    return (
        (0.0, 0.0, direction * separation)
        if "vertical" in node.preset
        else (0.0, -direction * separation, 0.0)
    )


def rotate_xy(vector, angle):
    c, s = cos(radians(angle)), sin(radians(angle))
    return vector[0] * c - vector[1] * s, vector[0] * s + vector[1] * c


def internal_path(document, route):
    from .topology import resolve_topology

    topology = resolve_topology(document)
    routed = set(route)
    return sum(
        ROOF_AIR_PATH_MM
        for node in document.nodes
        if node.kind == "roof" and any(edge.id in routed for edge in topology.outgoing.get(node.id, ()))
    )
