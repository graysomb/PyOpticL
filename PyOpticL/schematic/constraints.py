"""Resolve physical position pins using unconstrained beam lengths.

Source direction and optic turns define ray directions. Explicit lengths and
position pins are hard constraints; document default lengths are soft targets.
This planar linear solve deliberately does not change any routing angles.
"""

from math import cos, radians, sin, sqrt

from .model import connection_length
from .paths import component_path
from .physical import physical_layout
from .kinematics import internal_path
from .topology import Diagnostic

POSITION_TOLERANCE = 1e-6  # mm; includes rounding to six decimals in the inspector
MIN_LENGTH = 1e-6


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _fit_lengths(defaults, basis):
    """Project defaults onto the intersection of linear equations and bounds.

    Dykstra's alternating projections find the nearest feasible lengths without
    requiring a numerical package in FreeCAD's schematic-only import path.
    Corrections matter: simply clamping a negative solution can violate pins.
    """
    values = defaults[:]
    affine_correction = [0.0] * len(values)
    bound_correction = [0.0] * len(values)
    for _ in range(10000):
        shifted = [v + c for v, c in zip(values, affine_correction)]
        projected = shifted[:]
        for row, target in basis:
            error = _dot(row, projected) - target
            projected = [v - error * q for v, q in zip(projected, row)]
        affine_correction = [v - p for v, p in zip(shifted, projected)]
        shifted = [p + c for p, c in zip(projected, bound_correction)]
        fitted = [max(MIN_LENGTH, value) for value in shifted]
        bound_correction = [v - p for v, p in zip(shifted, fitted)]
        if (all(abs(_dot(row, fitted) - target) <= POSITION_TOLERANCE / 100 for row, target in basis) and
                max((abs(a - b) for a, b in zip(fitted, values)), default=0) <= POSITION_TOLERANCE / 100):
            return fitted
        values = fitted
    return None


def resolve_position_lengths(document, topology, headings):
    """Return effective lengths and diagnostics, leaving the document untouched."""
    source = document.node(topology.source_id)
    geometry = physical_layout(document,topology)
    lengths = {edge.id: connection_length(document, edge) for edge in document.connections}
    free = {edge.id: index for index, edge in enumerate(
        edge for edge in document.connections if edge.length is None)}
    # Each position is an offset plus a linear combination of free lengths.
    paths = {source.id: ([source.physical.get("x", 0), source.physical.get("y", 0)],
                         [[0.0] * len(free), [0.0] * len(free)])}
    for node_id in topology.order:
        offset, rows = paths[node_id]
        for edge in topology.outgoing[node_id]:
            direction = (cos(radians(headings[edge.id])), sin(radians(headings[edge.id])))
            target_offset = offset[:]
            for axis in (0,1):
                target_offset[axis] += geometry.origins[edge.id][axis]-geometry.positions[node_id][axis]
            target_rows = [row[:] for row in rows]
            for axis in (0, 1):
                if edge.id in free:
                    target_rows[axis][free[edge.id]] += direction[axis]
                else:
                    target_offset[axis] += direction[axis] * lengths[edge.id]
            paths[edge.target.node_id] = target_offset, target_rows

    equations, diagnostics = [], []
    for node in sorted(document.nodes, key=lambda node: node.id):
        if node.id == source.id:
            continue
        offset, rows = paths[node.id]
        for axis, key in enumerate(("x", "y")):
            if key not in node.physical:
                continue
            diagnostic = Diagnostic(
                f"{node.reference}: position {key.upper()}={node.physical[key]:g} mm conflicts with other pinned positions, constrained lengths, or routing angles", node.id)
            equations.append((rows[axis][:], node.physical[key] - offset[axis], diagnostic))
            diagnostics.append(diagnostic)
    for constraint in sorted(document.path_constraints, key=lambda item: item.id):
        diagnostic = Diagnostic("Total path length conflicts with positions, beam lengths, or other path constraints",
                                constraint.component_a, constraint_id=constraint.id)
        try:
            route = component_path(document, constraint.component_a, constraint.component_b)
        except ValueError as error:
            return lengths, [Diagnostic(str(error), constraint.component_a, constraint_id=constraint.id)]
        row, target = [0.0] * len(free), constraint.length_mm-internal_path(document,route)
        for edge_id in route:
            if edge_id in free:
                row[free[edge_id]] += 1
            else:
                target -= lengths[edge_id]
        equations.append((row, target, diagnostic))
        diagnostics.append(diagnostic)
    basis = []
    for row, target, diagnostic in equations:
        # Reorthogonalization keeps redundant pins and overlapping paths stable.
        for _ in range(2):
            for previous, value in basis:
                scale = _dot(row, previous)
                row = [a - scale * b for a, b in zip(row, previous)]
                target -= scale * value
        norm = sqrt(_dot(row, row))
        if norm < 1e-10:
            if abs(target) > POSITION_TOLERANCE:
                return lengths, [diagnostic]
        else:
            basis.append(([value / norm for value in row], target / norm))
    if not basis:
        return lengths, []
    defaults = [lengths[edge_id] for edge_id in free]
    fitted = _fit_lengths(defaults, basis)
    if fitted is None:
        return lengths, [Diagnostic(
            "Constraints could not be satisfied with positive beam lengths and current routing angles: " + item.message,
            item.node_id, constraint_id=item.constraint_id) for item in diagnostics]
    lengths.update({edge_id: round(fitted[index], 9) for edge_id, index in free.items()})
    return lengths, []
