"""Projection for optics with displaced ports, using numerical Jacobians.

The ordinary coincident-port solver retains its analytic fast path. Here a roof's
exit depends on its incoming direction, so derivatives include that rotation and
all upstream displaced ports. No CAD objects are accessed in this module.
"""

from math import atan2, degrees, hypot, radians
from .optimization import (
    beam_points,
    angle_points,
    exit_point,
    signed_turn,
    capsule_distance,
    _correct,
    _direction,
)
from .physical import wrap_angle
from .registry import MIN_BEAM_TURN


def scalar_gradient(problem, positions, function, mobility=None):
    working = [list(point) for point in positions]
    value = function(working)
    indices, gradients = [], []
    for i in range(len(positions)):
        gradient = []
        for axis in (0, 1):
            if mobility is not None and not mobility[i][axis]:
                gradient.append(0.0)
                continue
            before = working[i][axis]
            h = 1e-5
            working[i][axis] = before + h
            plus = function(working)
            working[i][axis] = before - h
            minus = function(working)
            working[i][axis] = before
            gradient.append((plus - minus) / (2 * h))
        if any(abs(g) > 1e-12 for g in gradient):
            indices.append(i)
            gradients.append(tuple(gradient))
    return value, tuple(indices), tuple(gradients)


def project_offsets(problem, positions, strength, mobility):
    def correct(function, weight=1):
        residual = function(positions)
        if abs(residual) < 1e-10:
            return
        value, indices, gradients = scalar_gradient(problem, positions, function, mobility)
        _correct(positions, mobility, indices, gradients, value, weight)

    def distance(points, index):
        a, b = beam_points(problem, points)[index]
        return hypot(b[0] - a[0], b[1] - a[1])

    for i, edge in enumerate(problem.edges):
        target = edge.fixed_length if edge.fixed_length is not None else 0.001
        if edge.fixed_length is not None or distance(positions, i) < target:
            if distance(positions, i) < 1e-10:
                nx, ny, _ = _direction(0, 0, edge.a + edge.b)

                def directed_distance(p):
                    a, b = beam_points(problem, p)[i]
                    return (b[0] - a[0]) * nx + (b[1] - a[1]) * ny - target

                correct(directed_distance)
            else:
                correct(lambda p: distance(p, i) - target)
    for constraint in problem.separations:

        def separation(p):
            a, b = p[constraint.a], p[constraint.b]
            if constraint.source is not None:
                start = exit_point(problem, p, constraint.source)
                a, b = (start, b) if constraint.source == constraint.a else (a, start)
            return hypot(b[0] - a[0], b[1] - a[1]) - constraint.target

        correct(separation)
    for constraint in problem.path_lengths:
        correct(
            lambda p: constraint.constant + sum(distance(p, i) for i in constraint.edges) - constraint.target
        )
    for constraint in problem.angles:
        actual = signed_turn(*angle_points(problem, positions, constraint))
        target = constraint.turn
        if target is None:
            target = (1 if actual >= 0 else -1) * max(MIN_BEAM_TURN, min(179.9999999, abs(actual)))
        error = wrap_angle(actual - target)
        correct(
            lambda p: radians(error + wrap_angle(signed_turn(*angle_points(problem, p, constraint)) - actual))
        )
    directions = [
        (i, problem.source_direction)
        for i, e in enumerate(problem.edges)
        if e.a == problem.source_index and problem.source_direction is not None
    ]
    directions.extend(
        (next(i for i, e in enumerate(problem.edges) if e.id == c.connection_id), c.angle)
        for c in problem.output_directions
    )
    for index, target in directions:

        def heading(p):
            a, b = beam_points(problem, p)[index]
            return degrees(atan2(b[1] - a[1], b[0] - a[0]))

        actual = heading(positions)
        error = wrap_angle(actual - target)
        correct(lambda p: radians(error + wrap_angle(heading(p) - actual)))
    physical = [i for i, n in enumerate(problem.nodes) if n.radius is not None]
    gap, half = problem.options.clearance_mm, problem.options.beam_diameter_mm / 2
    for offset, i in enumerate(physical):
        for j in physical[:offset]:
            required = problem.nodes[i].radius + problem.nodes[j].radius + gap
            nx, ny, distance_between = _direction(
                positions[j][0] - positions[i][0], positions[j][1] - positions[i][1], i * 31 + j
            )
            if distance_between < required:
                # The norm's central difference vanishes at coincidence. Use
                # the same deterministic separating direction as the fast path.
                _correct(
                    positions, mobility, (i, j), ((-nx, -ny), (nx, ny)), distance_between - required, strength
                )
    for index, edge in enumerate(problem.edges):
        for i in physical:
            if i in (edge.a, edge.b):
                continue
            required = problem.nodes[i].radius + half + gap

            def separation(p):
                _, dx, dy = capsule_distance(p[i], *beam_points(problem, p)[index])
                return hypot(dx, dy) - required

            if separation(positions) < 0:
                a, b = beam_points(problem, positions)[index]
                _, dx, dy = capsule_distance(positions[i], a, b)
                if hypot(dx, dy) < 1e-10:
                    vx, vy, _ = _direction(b[0] - a[0], b[1] - a[1])

                    def directed_separation(p):
                        _, dx, dy = capsule_distance(p[i], *beam_points(problem, p)[index])
                        return -vy * dx + vx * dy - required

                    correct(directed_separation, strength)
                else:
                    correct(separation, strength)
    box = problem.box
    for i, node in enumerate(problem.nodes):
        margin = max(node.radius or 0, half) + gap
        for axis, lower, upper in (
            (0, box.x + margin, box.x + box.width - margin),
            (1, box.y + margin, box.y + box.height - margin),
        ):
            if mobility[i][axis]:
                target = max(lower, min(upper, positions[i][axis])) if lower <= upper else (lower + upper) / 2
                positions[i][axis] += strength * (target - positions[i][axis])
            pin = (node.pin_x, node.pin_y)[axis]
            if pin is not None:
                positions[i][axis] = pin
