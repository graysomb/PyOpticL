"""Deterministic damped numerical projection and constraint rank diagnostics.

Only immutable/plain numerical state enters a worker. No CAD or Qt imports.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from math import hypot, isfinite, radians
from .scene_layout import Residual, trace_scene, poses_for, source_offset
from .topology import Diagnostic, resolve_topology
from .registry import (
    SYMBOLS, AXIS_ALIGNED_KINDS, MIN_BEAM_TURN, grating_input_heading, grating_turn, default_turn,
)
from .model import connection_length
from .physical import wrap_angle, wrap_axis_angle
from PyOpticL.ray_math import norm, sub, unit, heading, dot, yaw


@dataclass
class ConstraintReport:
    degrees_of_freedom: int = 0
    rank: int = 0
    redundant_ids: tuple = ()
    diagnostics: list = field(default_factory=list)


@dataclass
class SceneSolution:
    status: str
    layout: object
    poses: dict
    diagnostics: list
    report: ConstraintReport | None = None
    iterations: int = 0

    @property
    def ok(self):
        return self.status == "feasible"


def variables(document, *, pins=True):
    result = []
    for node in document.nodes:
        for axis in range(4 if node.kind != "output" else 3):
            if pins and axis < 2 and ("x", "y")[axis] in node.physical:
                continue
            if pins and axis == 3 and SYMBOLS[node.kind].role == "source" and "angle" in node.physical:
                continue
            result.append((node.id, axis))
    return result


def _place_on_ray(document, poses, baseline, edge, origin, direction, free, requested):
    """Place free coordinates on a ray without replacing pins or drag targets."""
    target_id = edge.target.node_id
    point = poses[target_id][:3]
    connection = document.connection(edge.id)
    distance = connection.length
    if distance is None:
        distance = norm(sub(baseline[target_id][:3], baseline[edge.source.node_id][:3]))
        distance = distance or connection_length(document, connection)
        for axis in range(3):
            key = (target_id, axis)
            if (key not in free or key in requested) and abs(direction[axis]) > 1e-8:
                distance = (point[axis] - origin[axis]) / direction[axis]
                break
    for axis in range(3):
        key = (target_id, axis)
        if key in free and key not in requested:
            poses[target_id][axis] = origin[axis] + distance * direction[axis]


def _orientation_seed(document, poses, topology, targets):
    """Estimate primary poses and follow displaced returns through shared parts.

    Plane intersections are singular at grazing incidence, and a mirror's
    equivalent back-facing normal is separated from its coating by 180 degrees.
    Starting on the geometric reflection branch avoids asking a local gradient
    to cross either barrier. This is only a candidate; all constraints and the
    exact finite ray trace still decide whether it can be accepted.
    """
    seed = deepcopy(poses)
    free = set(variables(document))
    requested = {(node_id, axis) for node_id, axis, _ in targets}
    for node_id, axis, value in targets:
        if (node_id, axis) in free:
            seed[node_id][axis] = value
    incoming = {edge.target.visit_id: edge for edge in topology.edges.values()}
    counts = {}
    for visit in topology.passes.values():
        counts[visit.component_id] = counts.get(visit.component_id, 0) + 1

    def leg(a, b):
        # Roof exits and deliberate off-center visits need their traced ports,
        # rather than the component origins used by this initial estimate.
        for visit_id in (a, b):
            visit = topology.passes[visit_id]
            node = document.node(visit.component_id)
            if (node.kind == "roof" and visit_id == a) or (visit.mode != "emit" and not visit.centered):
                return None
        delta = sub(seed[topology.passes[b].component_id][:3],
                    seed[topology.passes[a].component_id][:3])
        return unit(delta) if norm(delta) > 1e-6 else None

    def follow_grating(edge, direction):
        """Reflow a free downstream chain, retaining its preferred leg lengths."""
        while True:
            target = topology.passes[edge.target.visit_id]
            if counts[target.component_id] != 1 or not target.centered:
                return
            target_node = document.node(target.component_id)
            _place_on_ray(document, seed, poses, edge, seed[edge.source.node_id][:3],
                          direction, free, requested)
            exits = topology.outgoing[target.id]
            if len(exits) != 1 or target.mode != "pass":
                return
            next_edge = exits[0]
            if target_node.kind == "mirror":
                next_id = next_edge.target.node_id
                if any((next_id, axis) not in free or (next_id, axis) in requested for axis in range(3)):
                    return  # A free mirror can instead aim at a pinned next part.
                turn = target.turn
                if turn is None:
                    turn = target_node.physical.get("turn")
                    legacy = [e.turns[target.component_id] for e in document.connections
                              if target.component_id in e.turns]
                    if legacy:
                        turn = legacy[0]
                if turn is None:
                    before = sub(poses[target.component_id][:3], poses[edge.source.node_id][:3])
                    after = sub(poses[next_id][:3], poses[target.component_id][:3])
                    turn = wrap_angle(heading(after) - heading(before))
                    if norm(before) < 1e-6 or norm(after) < 1e-6 or not MIN_BEAM_TURN < abs(turn) < 180 - MIN_BEAM_TURN:
                        turn = default_turn("mirror", topology.incident_ports.get(target.id))
                direction = yaw(direction, turn)
            elif target_node.kind not in ("lens", "hwp", "qwp", "iris", "slit"):
                return  # Other deflectors need their own optical trace/frame.
            edge = next_edge

    for visit_id in topology.order:
        visit = topology.passes[visit_id]
        node = document.node(visit.component_id)
        key = (node.id, 3)
        shared_primary = (visit_id == node.id and visit.centered
                          and (node.kind in ("mirror", "lens", "qwp") or node.kind in AXIS_ALIGNED_KINDS))
        if (counts[node.id] != 1 and not shared_primary) or key not in free or key in requested:
            continue
        outgoing = topology.outgoing[visit_id]
        angle = None
        if visit.mode == "emit" and len(outgoing) == 1:
            direction = leg(visit_id, outgoing[0].target.visit_id)
            if direction is not None:
                angle = heading(direction) + source_offset(node)
        elif node.kind == "grating" and len(outgoing) == 1:
            before = leg(incoming[visit_id].source.visit_id, visit_id)
            if before is not None:
                try:
                    angle = heading(before) - grating_input_heading(document, node, topology, visit_id)
                    turn = grating_turn(document, node, topology, visit_id)
                except ValueError:
                    continue  # Invalid nominal orders remain validation errors.
                follow_grating(outgoing[0], yaw((1, 0, 0), heading(before) + turn))
        elif node.kind == "mirror" and visit.mode == "pass" and len(outgoing) == 1:
            before = leg(incoming[visit_id].source.visit_id, visit_id)
            after = leg(visit_id, outgoing[0].target.visit_id)
            if before is not None and after is not None:
                normal = sub(after, before)
                if hypot(normal[0], normal[1]) > 1e-6:
                    # out - in chooses the coated face: in dot normal < 0.
                    angle = heading(normal)
        elif visit.mode == "receive" and node.kind in ("fiber_output", "stop"):
            direction = leg(incoming[visit_id].source.visit_id, visit_id)
            if direction is not None:
                angle = heading(direction) + 180
        elif node.kind in AXIS_ALIGNED_KINDS or node.kind in ("lens", "qwp"):
            direction = leg(incoming[visit_id].source.visit_id, visit_id)
            if direction is not None:
                # Transmission works from either side; retain the nearer body
                # orientation instead of turning its mount by 180 degrees.
                angle = seed[node.id][3] + wrap_axis_angle(heading(direction) - seed[node.id][3])
        elif node.kind == "roof":
            direction = leg(incoming[visit_id].source.visit_id, visit_id)
            if direction is not None:
                angle = heading(direction)
        if angle is not None:
            seed[node.id][3] += wrap_angle(angle - seed[node.id][3])
    # The roof's exit and a shared return's contact are not component centers.
    # Trace those actual points before placing free downstream receiving parts.
    active = set()
    for visit_id in topology.order:
        visit = topology.passes[visit_id]
        node = document.node(visit.component_id)
        if node.kind != "roof" and visit_id not in active:
            continue
        trace = trace_scene(document, seed, check_interceptions=False, topology=topology)
        if visit_id in active:
            edge = incoming[visit_id]
            previous = trace.layout.visits[edge.source.visit_id]
            direction = previous.outputs[edge.interaction]
            if counts[node.id] == 1 and visit.centered:
                _place_on_ray(document, seed, poses, edge, previous.exit, direction, free, requested)
                key = (node.id, 3)
                if key in free and key not in requested:
                    if node.kind in ("fiber_output", "stop"):
                        seed[node.id][3] += wrap_angle(heading(direction) + 180 - seed[node.id][3])
                    elif node.kind in AXIS_ALIGNED_KINDS:
                        seed[node.id][3] += wrap_axis_angle(heading(direction) - seed[node.id][3])
                trace = trace_scene(document, seed, check_interceptions=False, topology=topology)
        state = trace.layout.visits[visit_id]
        if (node.kind == "roof" and state.path) or (visit_id in active and node.kind != "roof"):
            active.update(edge.target.visit_id for edge in topology.outgoing[visit_id])
    return seed


def _face_mirrors(document, poses, topology=None, targets=()):
    """Select the coated face without changing a mirror's reflection plane."""
    requested = {(node_id, axis) for node_id, axis, _ in targets}
    trace = trace_scene(document, poses, check_interceptions=False, topology=topology)
    for node in document.nodes:
        if node.kind != "mirror" or (node.id, 3) in requested:
            continue
        states = [state for key, state in trace.layout.visits.items()
                  if document.optical_pass(key).component_id == node.id]
        normal = yaw((1.0, 0.0, 0.0), poses[node.id][3])
        if states and all(dot(state.incoming, normal) > 1e-8 for state in states):
            # n and -n reflect identically, but only one faces the incoming ray.
            # All visits must agree before flipping a shared physical mirror.
            poses[node.id][3] = wrap_angle(poses[node.id][3] + 180)


def _length_seed(document, poses, topology, targets):
    """Extend a beam by moving its free downstream branch as a whole.

    A local projection can otherwise squash following legs against their
    forward-travel limit, or exhaust its small steps before moving them past
    their previous positions. Rigid translation preserves every other leg,
    optical orientation and roof offset. Shared bodies spanning the cut and
    explicit position pins prevent that translation.
    """
    from .paths import component_path

    seed = deepcopy(poses)
    free = set(variables(document))
    requested = {(node_id, axis) for node_id, axis, _ in targets}
    visits_by_node = {}
    for visit_id, visit in topology.passes.items():
        visits_by_node.setdefault(visit.component_id, set()).add(visit_id)
    all_visits = set(topology.passes)
    adjacency = {v: set() for v in all_visits}
    for edge in topology.edges.values():
        adjacency[edge.source.visit_id].add(edge.target.visit_id)
        adjacency[edge.target.visit_id].add(edge.source.visit_id)

    def change_length(edge, difference):
        if abs(difference) <= 1e-6 or not isfinite(difference):
            return False
        trace = trace_scene(document, seed, check_interceptions=False, topology=topology)
        source = trace.layout.visits[edge.source.visit_id]
        direction = source.outputs[edge.interaction]
        delta = tuple(difference * value for value in direction)
        downstream, pending = set(), [edge.target.visit_id]
        while pending:
            visit_id = pending.pop()
            if visit_id in downstream:
                continue
            downstream.add(visit_id)
            pending.extend(e.target.visit_id for e in topology.outgoing[visit_id])
        # Translate the opposite partition if the downstream side is pinned.
        partitions = ((downstream, 1, edge.target.visit_id),
                      (all_visits - downstream, -1, edge.source.visit_id))
        for selected, sign, _ in partitions:
            nodes = {topology.passes[v].component_id for v in selected}
            if any(not visits_by_node[n].issubset(selected) for n in nodes):
                continue
            if any(abs(delta[axis]) > 1e-9 and
                   ((node_id, axis) not in free or (node_id, axis) in requested)
                   for node_id in nodes for axis in range(3)):
                continue
            for node_id in nodes:
                for axis in range(3):
                    if abs(delta[axis]) > 1e-9:
                        seed[node_id][axis] += sign * delta[axis]
            return True
        # A fixed/shared body can anchor the far end of a free run. Move only
        # up to that boundary, leaving parts beyond it in place, and accept
        # this estimate only if all optical equations and fixed beams hold.
        for selected, sign, start in partitions:
            movable = {n for n, visits in visits_by_node.items() if visits.issubset(selected)
                       and all(abs(delta[axis]) <= 1e-9 or
                               ((n, axis) in free and (n, axis) not in requested)
                               for axis in range(3))}
            moved, seen, pending = set(), set(), [start]
            while pending:
                visit_id = pending.pop()
                node_id = topology.passes[visit_id].component_id
                if visit_id in seen or visit_id not in selected or node_id not in movable:
                    continue
                seen.add(visit_id)
                moved.add(node_id)
                pending.extend(adjacency[visit_id] | visits_by_node[node_id])
            if not moved:
                continue
            candidate = deepcopy(seed)
            for node_id in moved:
                for axis in range(3):
                    if abs(delta[axis]) > 1e-9:
                        candidate[node_id][axis] += sign * delta[axis]
            checked = trace_scene(document, candidate, check_interceptions=False, topology=topology)
            path_ids = {c.id for c in document.path_constraints}
            if (not any(d.severity == "error" for d in checked.diagnostics)
                    and all(abs(row.value) <= 1e-6 for row in checked.residuals if row.id not in path_ids)):
                seed.update(candidate)
                return True
        return False

    for edge in topology.edges.values():
        target = document.connection(edge.id).length
        if target is not None:
            trace = trace_scene(document, seed, check_interceptions=False, topology=topology)
            change_length(edge, target - trace.layout.lengths[edge.id])
    for constraint in document.path_constraints:
        try:
            route = component_path(document, constraint.pass_a or constraint.component_a,
                                   constraint.pass_b or constraint.component_b)
        except ValueError:
            continue
        trace = trace_scene(document, seed, check_interceptions=False, topology=topology)
        routed = set(route)
        total = sum(trace.layout.lengths[e] for e in route) + sum(
            trace.layout.internal_lengths.get(v, 0) for v in topology.order
            if any(e.id in routed for e in topology.outgoing[v])
        )
        remaining = constraint.length_mm - total
        for edge_id in reversed(route):
            if abs(remaining) <= 1e-6:
                break
            if document.connection(edge_id).length is not None:
                continue
            trace = trace_scene(document, seed, check_interceptions=False, topology=topology)
            # A shortening may need several free legs; never reverse one.
            change = max(remaining, 0.001 - trace.layout.lengths[edge_id])
            if change_length(topology.edges[edge_id], change):
                remaining -= change
    return seed


def _rows(document, poses, topology, targets=(), packing=None):
    trace = trace_scene(document, poses, check_interceptions=False, topology=topology)
    rows = list(trace.residuals)
    for node_id, axis, value in targets:
        rows.append(
            Residual(
                f"drag/{node_id}/{axis}",
                poses[node_id][axis] - value,
                "Requested drag position",
                node_id,
                unit="°" if axis == 3 else "mm",
            )
        )
    for identity, a, b, target in (document.layout or {}).get("_separations", []):
        if a in trace.layout.visits and b in trace.layout.visits:
            value = norm(sub(trace.layout.visits[b].entry, trace.layout.visits[a].exit))
            rows.append(
                Residual(
                    "separation/" + identity,
                    value - target,
                    "Constrained original beam endpoint separation",
                    connection_id=identity,
                )
            )
    if packing:
        from .optimization import capsule_distance

        box, radii, options = packing[:3]
        collision_weight = packing[3] if len(packing) > 3 else 1.0
        physical = [node for node in document.nodes if node.id in radii]
        gap, half = options.clearance_mm, options.beam_diameter_mm / 2
        for node in document.nodes:
            margin = max(radii.get(node.id, 0), half) + gap
            p = poses[node.id]
            for axis, lo, hi in (
                (0, box.x + margin, box.x + box.width - margin),
                (1, box.y + margin, box.y + box.height - margin),
            ):
                rows.append(
                    Residual(
                        f"box/{node.id}/{axis}",
                        max(lo - p[axis], p[axis] - hi, 0),
                        "Outside packing rectangle",
                        node.id,
                        equality=False,
                    )
                )
        for i, a in enumerate(physical):
            for b in physical[:i]:
                distance = hypot(poses[a.id][0] - poses[b.id][0], poses[a.id][1] - poses[b.id][1])
                rows.append(
                    Residual(
                        f"collision/{a.id}/{b.id}",
                        collision_weight * max(0, radii[a.id] + radii[b.id] + gap - distance),
                        f"{a.reference}/{b.reference}: assembly clearance",
                        a.id,
                        equality=False,
                    )
                )
        for edge in topology.edges.values():
            if (
                edge.source.visit_id not in trace.layout.visits
                or edge.target.visit_id not in trace.layout.visits
            ):
                continue
            a, b = (
                trace.layout.visits[edge.source.visit_id].exit,
                trace.layout.visits[edge.target.visit_id].entry,
            )
            for node in physical:
                if node.id in (edge.source.node_id, edge.target.node_id):
                    continue
                _, dx, dy = capsule_distance(poses[node.id], a, b)
                rows.append(
                    Residual(
                        f"beam_clearance/{edge.id}/{node.id}",
                        collision_weight * max(0, radii[node.id] + gap + half - hypot(dx, dy)),
                        f"{node.reference}: unrelated beam clearance",
                        node.id,
                        connection_id=edge.id,
                        equality=False,
                    )
                )
    return rows, trace


def _scale(row):
    return radians(1) * 50 if row.unit == "°" else 1.0


def jacobian(document, poses, rows, keys, topology, targets=(), packing=None, cancelled=None):
    keys_by_id = {row.id: i for i, row in enumerate(rows)}
    matrix = [[0.0] * len(keys) for _ in rows]
    for column, (node_id, axis) in enumerate(keys):
        if cancelled and cancelled():
            return None
        original = poses[node_id][axis]
        h = 1e-4
        poses[node_id][axis] = original + h
        plus, _ = _rows(document, poses, topology, targets, packing)
        poses[node_id][axis] = original - h
        minus, _ = _rows(document, poses, topology, targets, packing)
        poses[node_id][axis] = original
        left = {row.id: row.value for row in plus}
        right = {row.id: row.value for row in minus}
        for row in rows:
            matrix[keys_by_id[row.id]][column] = (
                (left.get(row.id, 0) - right.get(row.id, 0)) / (2 * h) * _scale(row)
            )
    return matrix


def _linear(matrix, rhs):
    """Pivoted Gaussian solve; damping makes the Gram matrix positive definite."""
    a = [list(row) + [value] for row, value in zip(matrix, rhs)]
    n = len(a)
    for k in range(n):
        pivot = max(range(k, n), key=lambda i: abs(a[i][k]))
        a[k], a[pivot] = a[pivot], a[k]
        if abs(a[k][k]) < 1e-18:
            continue
        for i in range(k + 1, n):
            factor = a[i][k] / a[k][k]
            if abs(factor) < 1e-20:
                continue
            for j in range(k + 1, n + 1):
                a[i][j] -= factor * a[k][j]
            a[i][k] = 0.0
    x = [0.0] * n
    for i in reversed(range(n)):
        if abs(a[i][i]) > 1e-18:
            x[i] = (a[i][n] - sum(a[i][j] * x[j] for j in range(i + 1, n))) / a[i][i]
    return x


def explicit_conflicts(document):
    """Only report contradictions that follow directly from explicit equations."""
    from .paths import component_path

    conflicts = []
    topology = resolve_topology(document)
    if topology.ok:
        incoming = {edge.target.visit_id: edge for edge in topology.edges.values()}
        for visit_id, visit in topology.passes.items():
            if document.node(visit.component_id).kind != "roof":
                continue
            before = topology.passes[incoming[visit_id].source.visit_id]
            for edge in topology.outgoing[visit_id]:
                after = topology.passes[edge.target.visit_id]
                if (before.component_id == after.component_id and before.centered and after.centered):
                    node = document.node(after.component_id)
                    conflicts.append(Diagnostic(
                        f"{node.reference}: a roof return is displaced; uncheck Centered hit on the return pass",
                        node.id, edge.id, pass_id=after.id,
                    ))
    for constraint in document.path_constraints:
        try:
            route = component_path(
                document,
                constraint.pass_a or constraint.component_a,
                constraint.pass_b or constraint.component_b,
            )
        except ValueError:
            continue
        edges = [document.connection(key) for key in route]
        endpoints = {e.node_id for edge in edges for e in (edge.a, edge.b)}
        if (
            edges
            and all(edge.length is not None and not edge.allow_folding for edge in edges)
            and not any(document.node(key).kind == "roof" for key in endpoints)
        ):
            total = sum(edge.length for edge in edges)
            if abs(total - constraint.length_mm) > 1e-6:
                conflicts.append(
                    Diagnostic(
                        f"Conflicting explicit constraints: fixed beams sum to {total:g} mm but this path requires {constraint.length_mm:g} mm",
                        constraint.component_a,
                        constraint_id=constraint.id,
                    )
                )
    return conflicts


def analyze_constraints(document, poses=None, topology=None):
    poses = deepcopy(poses or poses_for(document))
    topology = topology or resolve_topology(document)
    if not topology.ok:
        return ConstraintReport(diagnostics=list(topology.diagnostics))
    rows, trace = _rows(document, poses, topology)
    keys = variables(document, pins=False)
    matrix = jacobian(document, poses, rows, keys, topology)
    basis = []
    redundant = []
    diagnostics = []
    for row, gradient in zip(rows, matrix):
        if not row.equality:
            continue
        before = norm(gradient)
        working = list(gradient)
        for _ in range(2):
            for q in basis:
                dot = sum(a * b for a, b in zip(working, q))
                working = [a - dot * b for a, b in zip(working, q)]
        length = norm(working)
        if length > max(1e-9, before * 1e-8):
            basis.append([a / length for a in working])
        elif row.id.startswith(("length/", "turn/", "pin/", "source/", "direction/")) or any(
            c.id == row.id for c in document.path_constraints
        ):
            if abs(row.value) <= 1e-6:
                redundant.append(row.id)
                diagnostics.append(
                    Diagnostic(
                        "Locally redundant constraint: " + row.message,
                        row.node_id,
                        row.connection_id,
                        "warning",
                        row.id,
                        row.pass_id,
                    )
                )
    for row in rows:
        if abs(row.value) > 1e-6:
            diagnostics.append(
                Diagnostic(
                    f"{row.message}: remaining residual {abs(row.value):.6g} {row.unit}",
                    row.node_id,
                    row.connection_id,
                    "error",
                    row.id,
                    row.pass_id,
                )
            )
    diagnostics.extend(explicit_conflicts(document))
    diagnostics.extend(trace.diagnostics)
    return ConstraintReport(max(0, len(keys) - len(basis)), len(basis), tuple(redundant), diagnostics)


def solve_scene(
    document,
    *,
    poses=None,
    targets=(),
    packing=None,
    iterations=200,
    cancelled=None,
    progress=None,
    report=True,
):
    cancelled = cancelled or (lambda: False)
    topology = resolve_topology(document)
    points = deepcopy(poses or poses_for(document))
    for node in document.nodes:
        for axis, key in enumerate(("x", "y")):
            if key in node.physical:
                points[node.id][axis] = node.physical[key]
        if SYMBOLS[node.kind].role == "source" and "angle" in node.physical:
            points[node.id][3] = node.physical["angle"] + source_offset(node)
    if not topology.ok:
        return SceneSolution("unresolved", None, points, list(topology.diagnostics))
    conflicts = explicit_conflicts(document)
    if conflicts:
        return SceneSolution("inconsistent", trace_scene(document, points).layout, points, conflicts)
    if iterations > 0 and not cancelled():
        _face_mirrors(document, points, topology, targets)
        rows, _ = _rows(document, points, topology, targets, packing)
        if any(abs(row.value) > 1e-6 for row in rows):
            seed = _orientation_seed(document, points, topology, targets)
            seed = _length_seed(document, seed, topology, targets)
            _face_mirrors(document, seed, topology, targets)
            seeded_rows, _ = _rows(document, seed, topology, targets, packing)
            if sum((r.value * _scale(r)) ** 2 for r in seeded_rows) < sum(
                (r.value * _scale(r)) ** 2 for r in rows
            ):
                points = seed
    keys = variables(document)
    damping = 1e-5
    count = 0
    for count in range(iterations + 1):
        if cancelled():
            return SceneSolution("cancelled", None, points, [], iterations=count)
        rows, trace = _rows(document, points, topology, targets, packing)
        if all(abs(row.value) <= 1e-6 for row in rows):
            break
        if count == iterations or not keys:
            break
        matrix = jacobian(document, points, rows, keys, topology, targets, packing, cancelled)
        if matrix is None:
            return SceneSolution("cancelled", None, points, [], iterations=count)
        active = [
            i
            for i, (row, g) in enumerate(zip(rows, matrix))
            if abs(row.value) > 1e-10 or (row.equality and any(abs(v) > 1e-12 for v in g))
        ]
        j = [matrix[i] for i in active]
        r = [rows[i].value * _scale(rows[i]) for i in active]
        if not j:
            break
        gram = [
            [sum(a * b for a, b in zip(u, v)) + (damping if i == k else 0) for k, v in enumerate(j)]
            for i, u in enumerate(j)
        ]
        dual = _linear(gram, r)
        step = [-sum(j[i][col] * dual[i] for i in range(len(j))) for col in range(len(keys))]
        magnitude = max((abs(v) / (10 if axis < 3 else 15) for v, (_, axis) in zip(step, keys)), default=0)
        if magnitude > 1:
            step = [v / magnitude for v in step]
        old_score = sum((row.value * _scale(row)) ** 2 for row in rows)
        accepted = False
        for factor in (1.0, 0.5, 0.25, 0.125, 0.0625):
            candidate = deepcopy(points)
            for (node_id, axis), delta in zip(keys, step):
                candidate[node_id][axis] += factor * delta
            _face_mirrors(document, candidate, topology, targets)
            new_rows, _ = _rows(document, candidate, topology, targets, packing)
            score = sum((row.value * _scale(row)) ** 2 for row in new_rows)
            if isfinite(score) and score < old_score:
                points = candidate
                damping = max(1e-10, damping * 0.5)
                accepted = True
                break
        if not accepted:
            damping *= 10
            if damping > 1e10:
                break
        if progress:
            progress(count, points, trace)
    checked = trace_scene(document, points, topology=topology)
    rows, _ = _rows(document, points, topology, targets, packing)
    satisfied = all(abs(row.value) <= 1e-6 for row in rows) and checked.ok
    analysis = analyze_constraints(document, points, topology) if report else None
    diagnostics = list(checked.diagnostics)
    diagnostics.extend(
        Diagnostic(
            f"{row.message}: remaining residual {abs(row.value):.6g} {row.unit}",
            row.node_id,
            row.connection_id,
            "error",
            row.id,
            row.pass_id,
        )
        for row in rows
        if abs(row.value) > 1e-6
    )
    if analysis:
        diagnostics.extend(d for d in analysis.diagnostics if d.severity == "warning")
    return SceneSolution(
        "feasible" if satisfied else "unresolved", checked.layout, points, diagnostics, analysis, count
    )


def apply_scene_solution(document, solution):
    if not solution.ok:
        raise ValueError("Only a verified physical layout can be applied")
    document.layout["poses"] = deepcopy(solution.poses)
