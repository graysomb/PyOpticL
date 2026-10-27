"""Force-directed packing and bounded folding search for shared physical optics."""

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json
from math import acos, atan2, cos, degrees, hypot, isfinite, radians, sin, tan
import random
from time import monotonic
from .model import document_from_dict, connection_length
from .topology import resolve_topology
from .scene_layout import poses_for, trace_scene, initialize_layout
from .scene_solver import solve_scene, _rows, _face_mirrors
from .effective import (
    identity_graph,
    replay_graph,
    effective_document,
    insert_mirror,
    remove_mirror,
    can_insert,
    folding_protection,
)
from PyOpticL.ray_math import add, mul, sub, norm, dot, unit, heading, yaw


def _api():
    from . import optimization

    return optimization


def scene_document(source, graph, options, poses):
    document = effective_document(source, graph, options)
    if document.layout is None:
        document.layout = {"poses": {}}
    document.layout["poses"] = deepcopy(poses)
    original = resolve_topology(source)
    segment_ids = {segment.id for segment in graph.segments}
    document.layout["_separations"] = [
        (
            edge.id,
            original.edges[edge.id].source.visit_id,
            original.edges[edge.id].target.visit_id,
            edge.length,
        )
        for edge in source.connections
        if edge.length is not None and edge.id not in segment_ids
    ]
    return document


def make_scene_problem(source, radii, box, options, graph, poses, fingerprint, folding_radius):
    api = _api()
    derived = scene_document(source, graph, options, poses)
    topology = resolve_topology(derived)
    if not topology.ok:
        raise ValueError("; ".join(d.message for d in topology.diagnostics))
    generated = {m.id for m in graph.generated}
    indices = {n.id: i for i, n in enumerate(derived.nodes)}
    nodes = tuple(
        api.LayoutNode(
            n.id,
            n.reference,
            folding_radius if n.id in generated else radii.get(n.id),
            n.physical.get("x"),
            n.physical.get("y"),
        )
        for n in derived.nodes
    )
    preferred = {}
    for edge in source.connections:
        preferred[edge.id] = max(
            connection_length(source, edge),
            radii.get(edge.a.node_id, 0) + radii.get(edge.b.node_id, 0) + options.clearance_mm,
        )
    edges = tuple(
        api.LayoutEdge(
            segment.id,
            indices[segment.a.node_id],
            indices[segment.b.node_id],
            derived.connection(segment.id).length,
            sum(weight * preferred[key] for key, weight in segment.shares),
        )
        for segment in graph.segments
    )
    clean = deepcopy(source.to_dict())
    clean["optimized_layout"] = None
    clean["optimization"] = None
    return api.OptimizationProblem(
        nodes,
        edges,
        (),
        tuple(tuple(poses[n.id][:2]) for n in derived.nodes),
        indices[topology.passes[topology.source_id].component_id],
        source.node(topology.passes[topology.source_id].component_id).physical.get("angle"),
        box,
        options,
        json.dumps(derived.to_dict(), sort_keys=True),
        fingerprint,
        graph=graph,
        source_json=json.dumps(clean, sort_keys=True),
        source_radii=tuple(sorted(radii.items())),
        folding_radius=folding_radius,
        physical_scene=True,
    )


def build_scene_problem(document, radii, box=None, options=None, folding_radius=None):
    from .compiler import validate_schematic

    api = _api()
    errors = [d for d in validate_schematic(document) if d.severity == "error"]
    if errors:
        raise ValueError("\n".join(d.message for d in errors))
    options = options or api.OptimizationOptions()
    for n in document.nodes:
        if n.kind not in ("source", "output") and (
            not isinstance(radii.get(n.id), (float, int)) or not isfinite(radii[n.id]) or radii[n.id] <= 0
        ):
            raise ValueError(
                f"{n.reference}: complete physical bounds unavailable; refresh bounds or restore the vendor CAD cache"
            )
    radii = {n.id: radii[n.id] for n in document.nodes if n.kind not in ("source", "output")}
    if (
        any(e.allow_folding for e in document.connections)
        and options.max_added_mirrors
        and options.max_folds_per_beam
        and (folding_radius is None or not isfinite(folding_radius) or folding_radius <= 0)
    ):
        raise ValueError("Complete folding mirror bounds unavailable")
    initialize_layout(document)
    box = box or api.initial_box(document, radii, trace_scene(document).layout)
    graph = identity_graph(document)
    if document.optimized_layout and document.optimized_layout.get("graph"):
        try:
            graph = replay_graph(document, document.optimized_layout["graph"], options)
        except ValueError:
            pass
    poses = deepcopy(document.layout["poses"])
    for n in document.nodes:
        poses.setdefault(
            n.id,
            list(document.layout.get("legacy_manual_poses", {}).get(n.id, [*n.position, 0.0, n.rotation])),
        )
    fingerprint = api.input_fingerprint(
        document, api.configuration(box, options), radii, folding_radius=folding_radius
    )
    return make_scene_problem(document, radii, box, options, graph, poses, fingerprint, folding_radius)


def problem_beam_points(problem, positions):
    document = document_from_dict(json.loads(problem.document_json))
    poses = poses_for(document)
    for node, position in zip(problem.nodes, positions):
        poses[node.id][:2] = position
    trace = trace_scene(document, poses, check_interceptions=False)
    topology = resolve_topology(document)
    points = []
    for edge in problem.edges:
        resolved = topology.edges[edge.id]
        if (
            resolved.source.visit_id in trace.layout.visits
            and resolved.target.visit_id in trace.layout.visits
        ):
            points.append(
                (
                    trace.layout.visits[resolved.source.visit_id].exit[:2],
                    trace.layout.visits[resolved.target.visit_id].entry[:2],
                )
            )
        else:
            points.append((positions[edge.a], positions[edge.b]))
    return tuple(points)


def _radii(problem):
    return {n.id: n.radius for n in problem.nodes if n.radius is not None}


def violations(problem, document, poses):
    api = _api()
    topology = resolve_topology(document)
    rows, trace = _rows(document, poses, topology, packing=(problem.box, _radii(problem), problem.options))
    result = [
        api.Violation(
            row.id.split("/")[0],
            row.message,
            abs(row.value),
            row.unit,
            (row.node_id,) if row.node_id else (),
            (row.connection_id,) if row.connection_id else (),
            (row.id,),
        )
        for row in rows
        if abs(row.value) > 1e-6
    ]
    exact = trace_scene(document, poses, topology=topology)
    result.extend(
        api.Violation(
            "optical_trace",
            d.message,
            1.0,
            node_ids=(d.node_id,) if d.node_id else (),
            connection_ids=(d.connection_id,) if d.connection_id else (),
        )
        for d in exact.diagnostics
        if d.severity == "error"
    )
    return tuple(sorted(result, key=lambda v: (-v.residual, v.kind, v.node_ids))), exact.layout


@dataclass
class Candidate:
    problem: object
    poses: dict
    age: int = 0
    proposed: set = None
    stress: dict = None
    score: float = float("inf")
    energy: float = float("inf")
    remaining: tuple = ()
    layout: object = None

    def __post_init__(self):
        self.document = document_from_dict(json.loads(self.problem.document_json))
        self.proposed = set()
        self.stress = {e.id: 0.0 for e in self.problem.edges}
        self.velocities = {n.id: [0.0, 0.0] for n in self.problem.nodes}
        self.assess()

    @property
    def count(self):
        generated = len(self.problem.graph.generated)
        return generated + sum(
            n.kind == "mirror"
            and n.mirror_role == "folding"
            and folding_protection(self.document, n.id) is None
            for n in self.document.nodes
            if n.id not in {m.id for m in self.problem.graph.generated}
        )

    def assess(self):
        self.remaining, self.layout = violations(self.problem, self.document, self.poses)
        self.layout = replace(self.layout, graph=self.problem.graph)
        self.score = sum(v.residual**2 for v in self.remaining)
        self.energy = sum(
            (
                (self.layout.lengths.get(e.id, e.preferred_length) - e.preferred_length)
                / max(e.preferred_length, 1)
            )
            ** 2
            for e in self.problem.edges
        )

    def frame_problem(self):
        data = self.document.to_dict()
        data["layout"]["poses"] = deepcopy(self.poses)
        return replace(
            self.problem,
            document_json=json.dumps(data, sort_keys=True),
            initial_positions=tuple(tuple(self.poses[n.id][:2]) for n in self.problem.nodes),
        )


def _relax(candidate, cancelled):
    api = _api()
    problem = candidate.problem
    poses = deepcopy(candidate.poses)
    # Use geometric leg springs and inverse-square component repulsion. Physical
    # ray/pose projection then restores all hard constraints, including returns.
    forces = {n.id: [0.0, 0.0] for n in problem.nodes}
    topology = resolve_topology(candidate.document)
    coincident_directions = {}
    for edge in problem.edges:
        resolved = topology.edges[edge.id]
        a = candidate.layout.visits.get(resolved.source.visit_id)
        b = candidate.layout.visits.get(resolved.target.visit_id)
        if not a or not b:
            continue
        dx, dy = b.entry[0] - a.exit[0], b.entry[1] - a.exit[1]
        distance = hypot(dx, dy)
        nx, ny, _ = api._direction(dx, dy, edge.a + edge.b)
        if distance < 1e-12:
            # Separate connected centered optics along their propagation order.
            # An arbitrary transverse direction can trap the hard center and
            # forward-travel constraints when two bodies start coincident.
            direction = a.outputs.get(resolved.interaction, b.incoming)
            planar = hypot(direction[0], direction[1])
            if planar > 1e-12:
                nx, ny = direction[0] / planar, direction[1] / planar
                coincident_directions[(resolved.source.node_id, resolved.target.node_id)] = (nx, ny)
        stress = (distance - edge.preferred_length) / max(edge.preferred_length, 1)
        candidate.stress[edge.id] = 0.95 * candidate.stress.get(edge.id, 0) + 0.05 * abs(stress)
        for axis, d in enumerate((nx, ny)):
            forces[resolved.source.node_id][axis] += stress * d
            forces[resolved.target.node_id][axis] -= stress * d
    for i, node in enumerate(problem.nodes):
        for other in problem.nodes[:i]:
            dx, dy = poses[other.id][0] - poses[node.id][0], poses[other.id][1] - poses[node.id][1]
            nx, ny, distance = api._direction(dx, dy, i * 31 + problem.nodes.index(other))
            if distance < 1e-12:
                forward = coincident_directions.get((other.id, node.id))
                reverse = coincident_directions.get((node.id, other.id))
                if forward:
                    nx, ny = -forward[0], -forward[1]
                elif reverse:
                    nx, ny = reverse
            force = 10 / max(distance, 1) ** 2
            for axis, d in enumerate((nx, ny)):
                forces[node.id][axis] -= force * d
                forces[other.id][axis] += force * d
    ramp = min(1.0, (candidate.age + 1) / 200)
    for node in problem.nodes:
        for axis, pin in enumerate((node.pin_x, node.pin_y)):
            if pin is None:
                poses[node.id][axis] += max(
                    -1, min(1, 0.65 * candidate.velocities[node.id][axis] + forces[node.id][axis] * ramp)
                )
    _face_mirrors(candidate.document, poses)
    solved = solve_scene(
        candidate.document,
        poses=poses,
        packing=(problem.box, _radii(problem), problem.options, max(0.05, ramp)),
        iterations=problem.options.projection_passes,
        cancelled=cancelled,
        report=False,
    )
    _face_mirrors(candidate.document, solved.poses)
    corrections = {
        n.id: hypot(*(solved.poses[n.id][axis] - poses[n.id][axis] for axis in (0, 1))) for n in problem.nodes
    }
    for node in problem.nodes:
        for axis in (0, 1):
            candidate.velocities[node.id][axis] = max(
                -1, min(1, solved.poses[node.id][axis] - candidate.poses[node.id][axis])
            )
    for edge in problem.edges:
        correction = (corrections[problem.nodes[edge.a].id] + corrections[problem.nodes[edge.b].id]) / max(
            edge.preferred_length, 1
        )
        violation = sum(
            v.residual
            for v in candidate.remaining
            if edge.id in v.connection_ids or any(problem.nodes[i].id in v.node_ids for i in (edge.a, edge.b))
        )
        candidate.stress[edge.id] += 0.05 * (correction + violation / max(edge.preferred_length, 1))
    candidate.poses = solved.poses
    candidate.age += 1
    candidate.assess()


def _proposals(root, candidate, source, cancelled):
    p = candidate.problem
    options = p.options
    graph = p.graph
    if candidate.age < 200:
        return
    # Each proposed edit gets at least one 200-iteration relaxation batch.
    for node in candidate.document.nodes:
        if node.kind != "mirror" or ("remove", node.id) in candidate.proposed:
            continue
        generated = any(m.id == node.id for m in graph.generated)
        if not generated and folding_protection(source, node.id) is not None:
            continue
        state = candidate.layout.visits.get(node.id)
        if not state or "out" not in state.outputs:
            continue
        interior = degrees(acos(max(-1, min(1, -dot(unit(state.incoming), unit(state.outputs["out"]))))))
        if interior <= options.removal_angle_deg:
            continue
        candidate.proposed.add(("remove", node.id))
        try:
            edited = remove_mirror(source, graph, node.id, options)
        except ValueError:
            continue
        poses = {key: value for key, value in candidate.poses.items() if key != node.id}
        yield Candidate(
            make_scene_problem(
                source,
                dict(root.source_radii),
                p.box,
                options,
                edited,
                poses,
                root.fingerprint,
                root.folding_radius,
            ),
            poses,
        )
    permitted = [
        s
        for s in graph.segments
        if ("insert", s.id) not in candidate.proposed and can_insert(source, graph, s, options)
    ]
    if not permitted:
        return
    span = max(permitted, key=lambda s: (candidate.stress.get(s.id, 0), s.id))
    candidate.proposed.add(("insert", span.id))
    edge = resolve_topology(candidate.document).edges[span.id]
    a = candidate.layout.visits[edge.source.visit_id].exit
    b = candidate.layout.visits[edge.target.visit_id].entry
    dx, dy = b[0] - a[0], b[1] - a[1]
    distance = hypot(dx, dy)
    nx, ny, _ = _api()._direction(dx, dy)
    baseline = max(
        distance / 2,
        distance / 2 / tan(radians(max(1, options.removal_angle_deg - 10) / 2)),
        (root.folding_radius or 0) + options.clearance_mm,
    )
    for magnitude in (1, 1.5, 2):
        for sign in (1, -1):
            if cancelled():
                return
            edited = insert_mirror(source, graph, span.id, options)
            mirror = edited.generated[-1]
            position = (
                (a[0] + b[0]) / 2 - sign * ny * baseline * magnitude,
                (a[1] + b[1]) / 2 + sign * nx * baseline * magnitude,
                (a[2] + b[2]) / 2,
            )
            incoming = unit(sub(position, a))
            outgoing = unit(sub(b, position))
            normal = unit(sub(outgoing, incoming))
            poses = deepcopy(candidate.poses)
            poses[mirror.id] = [*position, heading(normal)]
            yield Candidate(
                make_scene_problem(
                    source,
                    dict(root.source_radii),
                    p.box,
                    options,
                    edited,
                    poses,
                    root.fingerprint,
                    root.folding_radius,
                ),
                poses,
            )


def optimize_scene_layout(problem, options=None, progress=None, cancelled=None):
    api = _api()
    options = options or problem.options
    if options != problem.options:
        if any(
            getattr(options, key) != getattr(problem.options, key)
            for key in ("clearance_mm", "beam_diameter_mm", "folding_preset", "folding_diameter_mm")
        ):
            raise ValueError("Packing settings changed; rebuild the problem")
        problem = replace(problem, options=options)
    cancelled = cancelled or (lambda: False)
    source = document_from_dict(json.loads(problem.source_json))
    rng = random.Random(options.seed)
    best = None
    best_rank = (float("inf"), float("inf"))
    closest = None
    used = 0
    starts = 0
    last = -float("inf")

    def assess(candidate):
        nonlocal best, best_rank, closest, last
        rank = (candidate.count, candidate.energy)
        if closest is None or candidate.score < closest.score:
            closest = deepcopy(candidate)
        if not candidate.remaining and rank < best_rank:
            best = deepcopy(candidate)
            best_rank = rank
        if progress and monotonic() - last >= 0.1:
            frame = candidate.frame_problem()
            positions = tuple(tuple(candidate.poses[n.id][:2]) for n in frame.nodes)
            progress(
                api.OptimizationProgress(
                    starts,
                    used - (starts - 1) * options.iterations,
                    used,
                    positions,
                    candidate.remaining,
                    not candidate.remaining,
                    frame,
                )
            )
            last = monotonic()

    initial = Candidate(problem, poses_for(document_from_dict(json.loads(problem.document_json))))
    for start in range(options.starts):
        starts = start + 1
        candidate = deepcopy(initial)
        if start:
            for node in problem.nodes:
                for axis, pin in enumerate((node.pin_x, node.pin_y)):
                    if pin is None:
                        candidate.poses[node.id][axis] += rng.uniform(-10, 10)
            candidate.assess()
        groups = {candidate.count: [candidate]}
        assess(candidate)
        spent = 0
        while spent < options.iterations:
            for count in sorted(tuple(groups)):
                for candidate in list(groups.get(count, ())):
                    batch = min(200, options.iterations - spent)
                    for _ in range(batch):
                        if cancelled():
                            return api.OptimizationResult(
                                "cancelled", None, tuple(problem.initial_positions), (), used, starts, problem
                            )
                        _relax(candidate, cancelled)
                        spent += 1
                        used += 1
                        assess(candidate)
                        if spent >= options.iterations:
                            break
                    proposals = list(_proposals(problem, candidate, source, cancelled))
                    for proposal in proposals:
                        assess(proposal)
                        pool = groups.setdefault(proposal.count, [])
                        pool.append(proposal)
                        pool.sort(
                            key=lambda c: (
                                c.score,
                                c.energy,
                                tuple(
                                    c.problem.graph.edits[i].node_id
                                    for i in range(len(c.problem.graph.edits))
                                ),
                            )
                        )
                        del pool[2:]
                    if spent >= options.iterations:
                        break
                if spent >= options.iterations:
                    break
            if best is not None and best_rank[0] == 0 and best_rank[1] < 1e-10:
                break
        if best is not None and best_rank[0] == 0 and best_rank[1] < 1e-10:
            break
    candidate = best or closest or initial
    frame = candidate.frame_problem()
    return api.OptimizationResult(
        "feasible" if best else "no_feasible_layout",
        best.layout if best else None,
        tuple(tuple(candidate.poses[n.id][:2]) for n in frame.nodes),
        () if best else candidate.remaining,
        used,
        starts,
        frame,
    )


def validate_saved_scene(config, saved):
    api = _api()
    try:
        if not isinstance(config, dict) or set(config) != {"box", "options"}:
            raise ValueError("Invalid optimizer configuration")
        api.PackingBox(**config["box"])
        api.OptimizationOptions(**config["options"])
        required = {
            "fingerprint",
            "geometry",
            "radii",
            "graph",
            "input_version",
            "folding_radius",
            "manual_poses",
        }
        if set(saved) != required:
            raise ValueError("Invalid physical optimization snapshot")
        digest = saved["fingerprint"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("Invalid optimizer fingerprint")
        if not isinstance(saved["geometry"], dict) or set(saved["geometry"]) != {"poses"}:
            raise ValueError("Invalid physical optimization geometry")
        for poses in (saved["geometry"]["poses"], saved["manual_poses"]):
            if not isinstance(poses, dict) or not all(
                isinstance(key, str)
                and isinstance(p, (list, tuple))
                and len(p) == 4
                and all(api._finite(v) for v in p)
                for key, p in poses.items()
            ):
                raise ValueError("Invalid physical poses")
        if not isinstance(saved["radii"], dict) or not all(
            isinstance(k, str) and api._finite(v) and v > 0 for k, v in saved["radii"].items()
        ):
            raise ValueError("Invalid assembly radii")
        radius = saved["folding_radius"]
        if radius is not None and (not api._finite(radius) or radius <= 0):
            raise ValueError("Invalid folding mirror radius")
        from .effective import parse_graph_edits

        parse_graph_edits(saved["graph"])
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"Invalid physical optimization snapshot: {error}") from error


def saved_scene_document(document):
    saved = document.optimized_layout
    options = _api().OptimizationOptions(**document.optimization["options"])
    graph = replay_graph(document, saved["graph"], options)
    return scene_document(document, graph, options, saved["geometry"]["poses"]), graph


def saved_scene_layout(document):
    api = _api()
    saved = document.optimized_layout
    validate_saved_scene(document.optimization, saved)
    if (
        api.input_fingerprint(
            document, document.optimization, saved["radii"], folding_radius=saved["folding_radius"]
        )
        != saved["fingerprint"]
    ):
        raise ValueError(
            "Optimized layout is stale. Rerun Optimize physical layout or Clear optimized layout before export."
        )
    expected = {n.id for n in document.nodes if n.kind not in ("source", "output")}
    if set(saved["radii"]) != expected:
        raise ValueError("Optimized layout has incomplete physical bounds")
    derived, graph = saved_scene_document(document)
    if set(saved["geometry"]["poses"]) != {n.id for n in derived.nodes}:
        raise ValueError("Optimized layout has incomplete or unknown component poses")
    problem = make_scene_problem(
        document,
        saved["radii"],
        api.PackingBox(**document.optimization["box"]),
        api.OptimizationOptions(**document.optimization["options"]),
        graph,
        saved["geometry"]["poses"],
        saved["fingerprint"],
        saved["folding_radius"],
    )
    failures, layout = violations(problem, derived, poses_for(derived))
    if failures:
        raise ValueError("Saved optimized layout failed verification: " + failures[0].message)
    return replace(layout, graph=graph)


def apply_scene_optimization(document, problem, result):
    api = _api()
    if result.status != "feasible" or result.layout is None:
        raise ValueError("Only a verified feasible layout can be applied")
    config = api.configuration(problem.box, problem.options)
    radii = dict(problem.source_radii)
    if (
        api.input_fingerprint(document, config, radii, folding_radius=problem.folding_radius)
        != problem.fingerprint
    ):
        raise ValueError("Schematic changed during optimization; run again")
    graph = result.layout.graph or identity_graph(document)
    saved = {
        "fingerprint": "0" * 64,
        "geometry": {"poses": {key: list(value) for key, value in result.layout.poses.items()}},
        "radii": radii,
        "graph": json.loads(json.dumps(graph.to_dict())),
        "input_version": 6,
        "folding_radius": problem.folding_radius,
        "manual_poses": deepcopy(
            document.optimized_layout.get("manual_poses", document.layout["poses"])
            if document.optimized_layout
            else document.layout["poses"]
        ),
    }
    candidate = document_from_dict(document.to_dict())
    candidate.layout["poses"] = {key: list(value) for key, value in result.layout.poses.items()}
    candidate.optimization = config
    candidate.optimized_layout = saved
    saved["fingerprint"] = api.input_fingerprint(
        candidate, config, radii, folding_radius=problem.folding_radius
    )
    saved_scene_layout(candidate)
    document.layout = candidate.layout
    document.optimization = config
    document.optimized_layout = saved


def update_scene_optimization(document, poses):
    """A verified manual adjustment retains the effective graph and packing rules."""
    candidate = document_from_dict(document.to_dict())
    candidate.layout["poses"] = deepcopy(poses)
    candidate.optimized_layout["geometry"]["poses"] = deepcopy(poses)
    saved = candidate.optimized_layout
    saved["fingerprint"] = _api().input_fingerprint(
        candidate, candidate.optimization, saved["radii"], folding_radius=saved["folding_radius"]
    )
    saved_scene_layout(candidate)
    document.layout = candidate.layout
    document.optimized_layout = saved
