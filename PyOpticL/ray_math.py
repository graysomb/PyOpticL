"""Small CAD-independent geometric ray operations, shared with native interfaces."""

from math import atan2, cos, degrees, radians, sin, sqrt, isfinite


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def mul(a, k):
    return tuple(x * k for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return sqrt(dot(a, a))


def unit(a):
    return mul(a, 1 / max(norm(a), 1e-15))


def yaw(a, angle):
    c, s = cos(radians(angle)), sin(radians(angle))
    return (c * a[0] - s * a[1], s * a[0] + c * a[1], a[2])


def heading(a):
    return degrees(atan2(a[1], a[0]))


def reflect(direction, normal):
    return sub(direction, mul(normal, 2 * dot(direction, normal)))


def lens_direction(direction, normal, radial, focal_length):
    """Native thin-lens chief-ray rule, including reverse and off-axis passes."""
    radius = norm(radial)
    if radius < 1e-12:
        return tuple(direction)
    nc = dot(direction, normal)
    if abs(nc) < 1e-12:
        return tuple(direction)
    r = mul(radial, 1 / radius)
    t = cross(r, normal)
    ts = dot(direction, t) / nc
    rs = dot(direction, r) / nc - radius / focal_length * (1 if nc >= 0 else -1)
    return unit(add(add(mul(normal, nc), mul(t, ts * nc)), mul(r, rs * nc)))


def grating_direction(direction, normal, transverse, wavelength_nm, order, grooves_per_mm=1000):
    d = unit(direction)
    dn = dot(d, normal)
    tangent = add(sub(d, mul(normal, dn)), mul(transverse, order * wavelength_nm * 1e-6 * grooves_per_mm))
    squared = 1 - dot(tangent, tangent)
    if squared <= 1e-14 or abs(dn) < 1e-8:
        return None
    return add(tangent, mul(normal, (1 if dn > 0 else -1) * sqrt(squared)))


def trace_roof(point, direction, center, vertical, model):
    if not all(isfinite(v) for v in (*point, *direction)) or norm(direction) < 1e-12:
        return None
    direction = unit(direction)

    def canonical(p):
        p = sub(p, center)
        return (p[0], -p[2], p[1]) if vertical else p

    def world(p):
        return add(center, (p[0], p[2], -p[1]) if vertical else p)

    p = canonical(point)
    d = (direction[0], -direction[2], direction[1]) if vertical else direction
    if d[0] <= 1e-8:
        return None
    normals = (unit((-1, -1, 0)), unit((-1, 1, 0)))
    transverses = (unit((1, -1, 0)), unit((1, 1, 0)))
    hits, indices = [], []
    for _ in range(2):
        candidates = []
        for i, n in enumerate(normals):
            den = dot(d, n)
            if den >= -1e-8:
                continue
            t = dot(sub(model["center_mm"][i], p), n) / den
            q = add(p, mul(d, t))
            delta = sub(q, model["center_mm"][i])
            if (
                t > 1e-6
                and abs(dot(delta, transverses[i]))
                < model["physical_width_mm"] * model["clear_fraction"] / 2 - 1e-8
                and abs(delta[2]) < model["physical_height_mm"] * model["clear_fraction"] / 2 - 1e-8
            ):
                candidates.append((t, i, q))
        if not candidates:
            return None
        _, i, p = min(candidates)
        if i in indices:
            return None
        indices.append(i)
        hits.append(world(p))
        d = reflect(d, normals[i])
    if d[0] >= -1e-8:
        return None
    t = -p[0] / d[0]
    exit = add(p, mul(d, t))
    if t <= 1e-6 or max(abs(exit[1]), abs(exit[2])) >= 12.7:
        return None
    out = (d[0], d[2], -d[1]) if vertical else d
    points = (point, *hits, world(exit))
    return points, out, sum(norm(sub(b, a)) for a, b in zip(points, points[1:]))
