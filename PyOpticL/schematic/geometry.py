"""Drawing geometry only; drawing units never become millimeters implicitly."""

from math import atan2, cos, degrees, hypot, radians, sin

from .registry import SYMBOLS


def snap_point(point, grid=20, enabled=True):
    return tuple(round(value / grid) * grid for value in point) if enabled else tuple(point)


def snap_angle(point, origin, step=45, enabled=True):
    if not enabled or point == origin:
        return tuple(point)
    dx, dy = point[0] - origin[0], point[1] - origin[1]
    angle = radians(round(degrees(atan2(dy, dx)) / step) * step)
    # Project onto the snapped direction instead of increasing segment length.
    length = dx * cos(angle) + dy * sin(angle)
    return (origin[0] + length * cos(angle), origin[1] + length * sin(angle))


def route_to(start, end, angle=45, enabled=True):
    """Finish at an exact port while retaining legal snapped segments."""
    if not enabled:
        return [end]
    dx, dy = end[0] - start[0], end[1] - start[1]
    if abs(dx) < 1e-8 or abs(dy) < 1e-8 or (angle == 45 and abs(abs(dx) - abs(dy)) < 1e-8):
        return [end]
    if angle == 90:
        return [(end[0], start[1]), end]
    distance = min(abs(dx), abs(dy))
    return [(start[0] + (distance if dx > 0 else -distance),
             start[1] + (distance if dy > 0 else -distance)), end]


def port_position(node, port):
    x, y = SYMBOLS[node.kind].port_position(port)
    angle = radians(node.rotation)
    return (node.position[0] + x * cos(angle) - y * sin(angle),
            node.position[1] + x * sin(angle) + y * cos(angle))


def connection_points(document, edge):
    points = [port_position(document.node(edge.source), edge.source_port), *edge.bends,
              port_position(document.node(edge.target), edge.target_port)]
    routed = [points[0]]
    for target in points[1:]:
        routed.extend(route_to(routed[-1], target, document.settings["angle"], document.settings["snap_angle"]))
    return routed


def apply_drawing_directions(document):
    """Explicitly copy outgoing port tangents to source/mirror/splitter hints."""
    incoming, outgoing = {}, {}
    for edge in document.connections:
        points = connection_points(document, edge)
        start, end = points[0], points[-1]
        forward = next((p for p in points[1:] if hypot(p[0] - start[0], p[1] - start[1]) > 1e-6), end)
        backward = next((p for p in reversed(points[:-1]) if hypot(end[0] - p[0], end[1] - p[1]) > 1e-6), start)
        # Canvas Y points down; physical Y points up.
        outgoing[(edge.source, edge.source_port)] = degrees(atan2(start[1] - forward[1], forward[0] - start[0]))
        incoming[edge.target] = degrees(atan2(backward[1] - end[1], end[0] - backward[0]))
    for node in document.nodes:
        if node.kind in ("source", "fiber_source") and (node.id, "out") in outgoing:
            node.physical["angle"] = outgoing[(node.id, "out")]
        if node.kind in ("mirror", "splitter") and node.id in incoming:
            port = "reflected" if node.kind == "splitter" else "out"
            if (node.id, port) in outgoing:
                turn = (outgoing[(node.id, port)] - incoming[node.id] + 180) % 360 - 180
                node.physical["turn"] = (90 if turn >= 0 else -90) if node.kind == "splitter" else round(turn / 45) * 45
