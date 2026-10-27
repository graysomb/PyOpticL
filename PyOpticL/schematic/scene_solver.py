"""Deterministic damped numerical projection and constraint rank diagnostics.

Only immutable/plain numerical state enters a worker. No CAD or Qt imports.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from math import hypot, isfinite, radians
from .scene_layout import Residual, trace_scene, poses_for, source_offset
from .topology import Diagnostic, resolve_topology
from .registry import SYMBOLS, AXIS_ALIGNED_KINDS
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


def _orientation_seed(document, poses, topology, targets):
    """Aim single-pass centered parts from their connected nominal centers.

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
            if node.kind == "roof" or (visit.mode != "emit" and not visit.centered):
                return None
        delta = sub(seed[topology.passes[b].component_id][:3],
                    seed[topology.passes[a].component_id][:3])
        return unit(delta) if norm(delta) > 1e-6 else None

    for visit_id in topology.order:
        visit = topology.passes[visit_id]
        node = document.node(visit.component_id)
        key = (node.id, 3)
        if counts[node.id] != 1 or key not in free or key in requested:
            continue
        outgoing = topology.outgoing[visit_id]
        angle = None
        if visit.mode == "emit" and len(outgoing) == 1:
            direction = leg(visit_id, outgoing[0].target.visit_id)
            if direction is not None:
                angle = heading(direction) + source_offset(node)
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
        elif node.kind in AXIS_ALIGNED_KINDS:
            direction = leg(incoming[visit_id].source.visit_id, visit_id)
            if direction is not None:
                # Transmission works from either side; retain the nearer body
                # orientation instead of turning its mount by 180 degrees.
                angle = seed[node.id][3] + wrap_axis_angle(heading(direction) - seed[node.id][3])
        if angle is not None:
            seed[node.id][3] += wrap_angle(angle - seed[node.id][3])
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
