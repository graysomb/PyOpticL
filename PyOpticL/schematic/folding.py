"""Bounded adaptive topology search around the pure numerical layout kernel."""

from dataclasses import dataclass, field
import json
from math import degrees, hypot, atan2, cos, sin, radians
import random
from statistics import median
from time import monotonic

from .effective import can_insert, folding_protection, insert_mirror, remove_mirror
from .model import document_from_dict
from .optimization import (
    OptimizationProgress,
    OptimizationResult,
    candidate_problem,
    beam_points,
    forces,
    project_constraints,
    reconstruct_candidate,
)
from .topology import resolve_topology

BATCH = 200


@dataclass
class Candidate:
    problem: object
    positions: list
    tag: tuple = ()
    age: int = 0
    velocity: list = field(default_factory=list)
    stress: dict = field(default_factory=dict)
    cooldown: dict = field(default_factory=dict)
    proposed: set = field(default_factory=set)
    layout: object = None
    exact: tuple = ()
    violations: tuple = ()
    score: float = float("inf")
    energy: float = float("inf")

    def __post_init__(self):
        self.positions = [list(point) for point in self.positions]
        self.velocity = [[0.0, 0.0] for _ in self.positions]
        self.document = document_from_dict(json.loads(self.problem.document_json))
        self.topology = resolve_topology(self.document)
        self.scale = median(edge.preferred_length for edge in self.problem.edges)
        self.mobility = [
            (float(node.pin_x is None), float(node.pin_y is None)) for node in self.problem.nodes
        ]
        for i, node in enumerate(self.problem.nodes):
            for axis, pin in enumerate((node.pin_x, node.pin_y)):
                if pin is not None:
                    self.positions[i][axis] = pin
        self.optional_count = sum(
            node.kind == "mirror" and node.mirror_role == "folding" for node in self.document.nodes
        )
        self.assess()

    def assess(self):
        self.layout, self.exact, self.violations = reconstruct_candidate(
            self.problem, self.positions, self.document, self.topology
        )
        self.score = sum(
            (item.residual / (90 if item.unit == "°" else self.scale)) ** 2 for item in self.violations
        )
        self.energy = sum(
            ((self.layout.lengths[edge.id] - edge.preferred_length) / max(edge.preferred_length, 1)) ** 2
            for edge in self.problem.edges
        )

    @property
    def rank(self):
        return self.score, self.energy, self.tag

    @property
    def key(self):
        return self.problem.graph.edits, self.tag


def _initial_positions(problem, rng, start):
    positions = [list(point) for point in problem.initial_positions]
    for axis, origin, size in ((0, problem.box.x, problem.box.width), (1, problem.box.y, problem.box.height)):
        if start:
            for i, node in enumerate(problem.nodes):
                if (node.pin_x, node.pin_y)[axis] is None:
                    positions[i][axis] = origin + rng.uniform(0.1, 0.9) * size
        elif all((node.pin_x, node.pin_y)[axis] is None for node in problem.nodes):
            offset = (
                origin
                + size / 2
                - (min(point[axis] for point in positions) + max(point[axis] for point in positions)) / 2
            )
            for point in positions:
                point[axis] += offset
    return positions


def _step(candidate, cancelled):
    problem = candidate.problem
    before = [point[:] for point in candidate.positions]
    force = forces(problem, candidate.positions)
    anneal = max(0.0, 1 - candidate.age / 800) ** 3
    cap = candidate.scale * 0.08
    for i in range(len(before)):
        for axis in (0, 1):
            candidate.velocity[i][axis] = candidate.mobility[i][axis] * (
                0.8 * candidate.velocity[i][axis] + 0.04 * anneal * force[i][axis]
            )
        speed = hypot(*candidate.velocity[i])
        if speed > cap:
            candidate.velocity[i] = [value * cap / speed for value in candidate.velocity[i]]
        for axis in (0, 1):
            candidate.positions[i][axis] += candidate.velocity[i][axis]
    correction = [0.0] * len(before)
    for _ in range(problem.options.projection_passes):
        if cancelled():
            return False
        old = [point[:] for point in candidate.positions]
        project_constraints(
            problem, candidate.positions, min(1.0, (candidate.age + 1) / 100), candidate.mobility
        )
        for i, point in enumerate(candidate.positions):
            correction[i] += hypot(point[0] - old[i][0], point[1] - old[i][1])
    candidate.velocity = [
        [(point[axis] - old[axis]) * 0.5 for axis in (0, 1)]
        for point, old in zip(candidate.positions, before)
    ]
    candidate.age += 1
    candidate.assess()
    bad_nodes = {node_id for violation in candidate.violations for node_id in violation.node_ids}
    for edge,(a,b) in zip(problem.edges,beam_points(problem,candidate.positions)):
        stretch = abs(hypot(b[0] - a[0], b[1] - a[1]) - edge.preferred_length)
        value = (stretch + correction[edge.a] + correction[edge.b]) / max(edge.preferred_length, 1)
        for violation in candidate.violations:
            if (
                edge.id in violation.connection_ids
                or problem.nodes[edge.a].id in bad_nodes
                or problem.nodes[edge.b].id in bad_nodes
            ):
                value += violation.residual / (90 if violation.unit == "°" else candidate.scale)
        candidate.stress[edge.id] = 0.95 * candidate.stress.get(edge.id, 0) + 0.05 * value
    return True


def _proposals(root, candidate, source, elapsed, cancelled):
    graph, options = candidate.problem.graph, root.options
    positions = {node.id: tuple(candidate.positions[i]) for i, node in enumerate(candidate.problem.nodes)}
    # Pruning is a proposal, never permission to discard a hard constraint.
    for node in sorted(candidate.document.nodes, key=lambda node: node.id):
        if cancelled():
            return
        if node.kind != "mirror" or node.mirror_role != "folding":
            continue
        if node.id not in {item.id for item in graph.generated} and folding_protection(source, node.id):
            continue
        if 180 - abs(candidate.layout.turns[node.id]) <= options.removal_angle_deg + 1e-6:
            continue
        incident = [
            segment for segment in graph.segments if node.id in (segment.a.node_id, segment.b.node_id)
        ]
        logical_ids = {key for segment in incident for key in segment.logical_ids}
        if any(candidate.cooldown.get(key, 0) > elapsed for key in logical_ids):
            continue
        if ("remove", node.id) in candidate.proposed:
            continue
        candidate.proposed.add(("remove", node.id))
        changed = remove_mirror(source, graph, node.id, options)
        problem = candidate_problem(root, changed, positions)
        child = Candidate(problem, problem.initial_positions, candidate.tag + ("remove:" + node.id,))
        child.cooldown = {**candidate.cooldown, **{key: elapsed + BATCH for key in logical_ids}}
        yield child
    if not candidate.violations:
        return
    spans = [
        segment
        for segment in graph.segments
        if can_insert(source, graph, segment, options)
        and ("insert", segment.id) not in candidate.proposed
        and all(candidate.cooldown.get(key, 0) <= elapsed for key in segment.logical_ids)
    ]
    spans.sort(key=lambda segment: (-candidate.stress.get(segment.id, 0), segment.id))
    if not spans:
        return
    segment = spans[0]
    candidate.proposed.add(("insert", segment.id))
    edge = candidate.topology.edges[segment.id]
    index = next(i for i,e in enumerate(candidate.problem.edges) if e.id == segment.id)
    a,b = beam_points(candidate.problem,candidate.positions)[index]
    dx, dy = b[0] - a[0], b[1] - a[1]
    distance = hypot(dx, dy)
    if distance < 1e-9:
        dx, dy, distance = candidate.scale, 0, candidate.scale
    normal = (-dy / distance, dx / distance)
    baseline = max(distance / 2, (root.folding_radius or 0) + options.clearance_mm)
    changed = insert_mirror(source, graph, segment.id, options)
    mirror_id = changed.generated[-1].id
    for magnitude in (1.0, 1.5, 2.0):
        interior = 180 - degrees(2 * atan2(baseline * magnitude, distance / 2))
        if interior > options.removal_angle_deg - 10:
            continue
        for sign in (1, -1):
            if cancelled():
                return
            point = (
                (a[0] + b[0]) / 2 + sign * baseline * magnitude * normal[0],
                (a[1] + b[1]) / 2 + sign * baseline * magnitude * normal[1],
            )
            seeded = {**positions, mirror_id: point}
            source_node = candidate.document.node(edge.source.node_id)
            target_node = candidate.document.node(edge.target.node_id)
            locked_heading = (
                edge.source.node_id == candidate.problem.nodes[candidate.problem.source_index].id
                and candidate.problem.source_direction is not None
            )
            locked_heading = locked_heading or (
                source_node.kind not in ("source", "fiber_source", "mirror", "splitter")
            )
            locked_heading = locked_heading or (
                "turn" in source_node.physical
                and (source_node.kind == "mirror" or edge.interaction == "reflected")
            )
            locked_heading = locked_heading or (
                source_node.kind == "splitter" and edge.interaction == "transmitted"
            )
            if (
                locked_heading
                and target_node.kind == "mirror"
                and not any(key in target_node.physical for key in ("x", "y"))
            ):
                # Preserve the source optic's outgoing direction while seeding
                # the existing free mirror off axis. This lets a second fold
                # escape the collinear singularity of a fixed source heading.
                heading = radians(candidate.layout.headings[segment.id])
                seeded[mirror_id] = (
                    a[0] + distance * 0.5 * cos(heading),
                    a[1] + distance * 0.5 * sin(heading),
                )
                seeded[target_node.id] = (
                    b[0] + sign * baseline * magnitude * normal[0],
                    b[1] + sign * baseline * magnitude * normal[1],
                )
            problem = candidate_problem(root, changed, seeded)
            child = Candidate(
                problem,
                problem.initial_positions,
                candidate.tag + (f"insert:{segment.id}:{magnitude}:{sign}",),
            )
            child.cooldown = {**candidate.cooldown, **{key: elapsed + BATCH for key in segment.logical_ids}}
            yield child


def adaptive_layout(problem, progress=None, cancelled=None):
    """Two candidates/count; fair count scheduling; all relaxation shares a budget."""
    cancelled = cancelled or (lambda: False)
    source = document_from_dict(json.loads(problem.source_json))
    rng = random.Random(problem.options.seed)
    best, best_rank = None, (float("inf"), float("inf"))
    closest, closest_score = None, float("inf")
    count, last_update = 0, -float("inf")
    for start in range(problem.options.starts):
        initial = Candidate(problem, _initial_positions(problem, rng, start))
        buckets = {initial.optional_count: [initial]}
        seen = {initial.key}
        elapsed, cursor = 0, 0

        def capture(candidate):
            nonlocal best, best_rank, closest, closest_score
            if candidate.score < closest_score:
                closest_score = candidate.score
                closest = OptimizationResult(
                    "no_feasible_layout",
                    None,
                    candidate.exact,
                    candidate.violations,
                    count,
                    start + 1,
                    candidate.problem,
                )
            if not candidate.violations and (candidate.optional_count, candidate.energy) < best_rank:
                best_rank = candidate.optional_count, candidate.energy
                best = OptimizationResult(
                    "feasible", candidate.layout, candidate.exact, (), count, start + 1, candidate.problem
                )

        capture(initial)
        while elapsed < problem.options.iterations:
            if cancelled():
                attempt = closest
                return OptimizationResult(
                    "cancelled",
                    None,
                    attempt.positions,
                    attempt.violations,
                    count,
                    start + 1,
                    attempt.problem,
                )
            groups = sorted(buckets)
            group = groups[cursor % len(groups)]
            cursor += 1
            choices = buckets[group]
            # Alternate both geometry seeds in each count bucket.
            candidate = choices[(cursor // len(groups)) % len(choices)]
            for _ in range(min(BATCH, problem.options.iterations - elapsed)):
                if not _step(candidate, cancelled):
                    return OptimizationResult(
                        "cancelled",
                        None,
                        candidate.exact,
                        candidate.violations,
                        count,
                        start + 1,
                        candidate.problem,
                    )
                elapsed += 1
                count += 1
                capture(candidate)
                now = monotonic()
                if progress and now - last_update >= 0.1:
                    progress(
                        OptimizationProgress(
                            start + 1,
                            elapsed,
                            count,
                            candidate.exact,
                            candidate.violations,
                            not candidate.violations,
                            candidate.problem,
                        )
                    )
                    last_update = now
            proposals = list(_proposals(problem, candidate, source, elapsed, cancelled))
            for child in proposals:
                if child.key in seen:
                    continue
                seen.add(child.key)
                capture(child)
                choices = buckets.setdefault(child.optional_count, [])
                choices.append(child)
                choices.sort(key=lambda item: item.rank)
                del choices[2:]
            if best is not None and best_rank[0] == 0 and best_rank[1] < 1e-12:
                break
            # A stable feasible realization with no eligible pruning can finish
            # its start early. Other starts still explore alternative geometry.
            if best is not None and not candidate.violations and not proposals and candidate.age >= 400:
                break
        if best is not None and best_rank == (0, 0):
            break
    if cancelled():
        return OptimizationResult(
            "cancelled", None, closest.positions, closest.violations, count, start + 1, closest.problem
        )
    if best is not None:
        if progress:
            progress(OptimizationProgress(start + 1, elapsed, count, best.positions, (), True, best.problem))
        return OptimizationResult("feasible", best.layout, best.positions, (), count, start + 1, best.problem)
    if progress:
        progress(
            OptimizationProgress(
                start + 1, elapsed, count, closest.positions, closest.violations, False, closest.problem
            )
        )
    return OptimizationResult(
        "no_feasible_layout", None, closest.positions, closest.violations, count, start + 1, closest.problem
    )
