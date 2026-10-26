"""Deterministic, CAD-independent constrained particle layout.

The worker receives only frozen records and JSON. Collision projection uses full
assembly disks and constant-radius beam capsules; beam crossings are allowed.
Every accepted result is reconstructed through physical_layout before validation.
"""

from dataclasses import asdict, dataclass, replace
from copy import deepcopy
import hashlib
import json
from math import atan2, cos, degrees, hypot, isfinite, pi, radians, sin
import random
from statistics import median
from time import monotonic

from .model import connection_length, document_from_dict, interface_turn
from .paths import component_path
from .effective import EffectiveGraph, identity_graph, effective_document, parse_graph_edits, replay_graph
from .physical import PhysicalLayout, physical_layout, wrap_angle
from .registry import MIN_BEAM_TURN
from .topology import resolve_topology

LINEAR_TOLERANCE = 1e-6
ANGULAR_TOLERANCE = 1e-6


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


@dataclass(frozen=True)
class PackingBox:
    x: float = 0
    y: float = 0
    width: float = 300
    height: float = 200

    def __post_init__(self):
        if not all(_finite(v) for v in asdict(self).values()) or self.width <= 0 or self.height <= 0:
            raise ValueError("Rectangle coordinates must be finite and its dimensions positive")


@dataclass(frozen=True)
class OptimizationOptions:
    clearance_mm: float = 1
    beam_diameter_mm: float = 1
    seed: int = 0
    starts: int = 8
    iterations: int = 5000
    projection_passes: int = 20
    folding_preset: str = "mounted"
    folding_diameter_mm: float = 12.7
    max_added_mirrors: int = 8
    max_folds_per_beam: int = 4
    removal_angle_deg: float = 110

    def __post_init__(self):
        if not _finite(self.clearance_mm) or self.clearance_mm < 0:
            raise ValueError("Clearance must be a finite nonnegative distance")
        if not _finite(self.beam_diameter_mm) or self.beam_diameter_mm <= 0:
            raise ValueError("Beam keep-out diameter must be positive")
        for key in ("seed", "starts", "iterations", "projection_passes"):
            value = getattr(self, key)
            if type(value) is not int or (key != "seed" and value < 1):
                raise ValueError(
                    f"{key} must be an integer" + ("" if key == "seed" else " greater than zero")
                )
        if self.folding_preset not in ("mounted", "bare"):
            raise ValueError("Folding mirror preset must be mounted or bare")
        if not _finite(self.folding_diameter_mm) or self.folding_diameter_mm <= 0:
            raise ValueError("Folding mirror diameter must be positive")
        if self.folding_preset == "mounted" and self.folding_diameter_mm != 12.7:
            raise ValueError("Mounted folding mirrors require a 12.7 mm diameter")
        for key in ("max_added_mirrors", "max_folds_per_beam"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 0:
                raise ValueError(f"{key} must be a nonnegative integer")
        if not _finite(self.removal_angle_deg) or not 0 < self.removal_angle_deg < 180:
            raise ValueError("Folding removal angle must be between 0 and 180 degrees")
        if self.starts > 8:
            raise ValueError("At most 8 starts are supported")


@dataclass(frozen=True)
class LayoutNode:
    id: str
    reference: str
    radius: float | None
    pin_x: float | None
    pin_y: float | None


@dataclass(frozen=True)
class LayoutEdge:
    id: str
    a: int
    b: int
    fixed_length: float | None
    preferred_length: float


@dataclass(frozen=True)
class TurnConstraint:
    incoming: int
    node: int
    outgoing: int
    connection_id: str
    turn: float | None  # None permits either supported reflecting turn


@dataclass(frozen=True)
class DirectionConstraint:
    a: int
    b: int
    angle: float
    node_id: str
    connection_id: str


@dataclass(frozen=True)
class PathProjection:
    id: str
    edges: tuple[int, ...]
    target: float
    a: int
    b: int


@dataclass(frozen=True)
class SeparationConstraint:
    id: str
    a: int
    b: int
    target: float
    edges: tuple[int, ...] = ()


@dataclass(frozen=True)
class OptimizationProblem:
    nodes: tuple[LayoutNode, ...]
    edges: tuple[LayoutEdge, ...]
    angles: tuple[TurnConstraint, ...]
    initial_positions: tuple[tuple[float, float], ...]
    source_index: int
    source_direction: float | None
    box: PackingBox
    options: OptimizationOptions
    document_json: str
    fingerprint: str
    path_lengths: tuple[PathProjection, ...] = ()
    separations: tuple[SeparationConstraint, ...] = ()
    graph: EffectiveGraph | None = None
    source_json: str = ""
    source_radii: tuple[tuple[str, float], ...] = ()
    folding_radius: float | None = None
    output_directions: tuple[DirectionConstraint, ...] = ()


@dataclass(frozen=True)
class Violation:
    kind: str
    message: str
    residual: float
    unit: str = "mm"
    node_ids: tuple[str, ...] = ()
    connection_ids: tuple[str, ...] = ()
    constraint_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class OptimizationProgress:
    start: int
    iteration: int
    total_iterations: int
    positions: tuple[tuple[float, float], ...]
    violations: tuple[Violation, ...]
    feasible: bool = False
    problem: OptimizationProblem | None = None


@dataclass(frozen=True)
class OptimizationResult:
    status: str
    layout: PhysicalLayout | None
    positions: tuple[tuple[float, float], ...]
    violations: tuple[Violation, ...]
    iterations: int
    starts: int
    problem: OptimizationProblem | None = None


def geometry_settings():
    from PyOpticL import settings

    return {
        "measurement_system": settings.get_measurement_system(),
        "minimum_thread_engagement": settings.get_minimum_thread_engagement(),
        "extra_drill_depth": settings.get_default_extra_drill_depth(),
    }


def configuration(box, options):
    return {"box": asdict(box), "options": asdict(options)}


def input_fingerprint(document, config, radii, geometry=None, folding_radius=None):
    # References, canvas geometry and display settings deliberately do not enter.
    from .parts import part_spec

    topology = resolve_topology(document)
    nodes = []
    for node in document.nodes:
        spec = part_spec(document, node, topology)
        nodes.append(
            {
                "id": node.id,
                "kind": node.kind,
                "preset": node.preset,
                "parameters": node.parameters,
                "physical": node.physical,
                "mirror_role": node.mirror_role,
                "part_specification": asdict(spec) if spec is not None else None,
            }
        )
    edges = [
        {
            "id": e.id,
            "ends": sorted([(e.a.node_id, e.a.port_id), (e.b.node_id, e.b.port_id)]),
            "length": e.length,
            "turns": e.turns,
            "allow_folding": e.allow_folding,
        }
        for e in document.connections
    ]
    payload = {
        "nodes": sorted(nodes, key=lambda n: n["id"]),
        "edges": sorted(edges, key=lambda e: e["id"]),
        "defaults": {key: document.settings[key] for key in ("spacing", "open_length")},
        "packing": config,
        "path_constraints": sorted(
            [asdict(item) for item in document.path_constraints], key=lambda item: item["id"]
        ),
        "folding_radius": folding_radius,
        "radii": radii,
        "geometry": geometry_settings() if geometry is None else geometry,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def validate_saved_optimization(config, saved):
    """Validate storage without requiring it to match an unfinished schematic."""
    try:
        if config is not None:
            if not isinstance(config, dict) or set(config) != {"box", "options"}:
                raise ValueError("Invalid optimizer configuration")
            PackingBox(**config["box"])
            OptimizationOptions(**config["options"])
        if saved is None:
            return
        if config is None or not isinstance(saved, dict):
            raise ValueError("Invalid optimized layout")
        legacy_keys = {"fingerprint", "geometry", "radii"}
        current_keys = legacy_keys | {"graph", "input_version", "folding_radius"}
        if set(saved) not in (legacy_keys, current_keys):
            raise ValueError("Invalid optimized layout")
        if set(saved) == current_keys:
            if type(saved["input_version"]) is not int or saved["input_version"] != 5:
                raise ValueError("Invalid optimized layout input version")
            parse_graph_edits(saved["graph"])
            radius = saved["folding_radius"]
            if radius is not None and (not _finite(radius) or radius <= 0):
                raise ValueError("Invalid folding mirror bounds")
        digest = saved["fingerprint"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("Invalid optimized layout fingerprint")
        geometry = saved["geometry"]
        if not isinstance(geometry, dict) or set(geometry) != {"source_pose", "lengths", "turns"}:
            raise ValueError("Invalid optimized optical geometry")
        if (
            not isinstance(geometry["source_pose"], (list, tuple))
            or len(geometry["source_pose"]) != 3
            or not all(map(_finite, geometry["source_pose"]))
        ):
            raise ValueError("Invalid optimized source pose")
        for key in ("lengths", "turns"):
            values = geometry[key]
            if not isinstance(values, dict) or not all(
                isinstance(k, str) and k and _finite(v) for k, v in values.items()
            ):
                raise ValueError(f"Invalid optimized {key}")
        if any(v <= 0 for v in geometry["lengths"].values()):
            raise ValueError("Optimized lengths must be positive")
        if any(not MIN_BEAM_TURN <= abs(v) < 180 for v in geometry["turns"].values()):
            raise ValueError("Invalid optimized reflecting turn")
        if not isinstance(saved["radii"], dict) or not all(
            isinstance(k, str) and k and _finite(v) and v >= 0 for k, v in saved["radii"].items()
        ):
            raise ValueError("Invalid optimized part bounds")
    except (TypeError, KeyError, AttributeError) as error:
        raise ValueError(f"Invalid optimized layout: {error}") from error


def build_problem(document, radii, box=None, options=None, folding_radius=None):
    """Build an immutable snapshot after GUI-thread CAD bounds resolution."""
    from .compiler import validate_schematic

    document = document_from_dict(document.to_dict())
    errors = validate_schematic(document)
    if errors:
        raise ValueError("\n".join(e.message for e in errors))
    options = options or OptimizationOptions()
    for node in document.nodes:
        if node.kind not in ("source", "output") and (not _finite(radii.get(node.id)) or radii[node.id] < 0):
            raise ValueError(
                f"{node.reference}: complete physical bounds unavailable. Refresh bounds or select a modeled part/preset."
            )
    needs_folding_bounds = (
        any(edge.allow_folding for edge in document.connections)
        and options.max_added_mirrors
        and options.max_folds_per_beam
    )
    if needs_folding_bounds and (not _finite(folding_radius) or folding_radius <= 0):
        raise ValueError(
            "Complete folding mirror bounds unavailable. Refresh bounds or choose a modeled folding mirror preset."
        )
    topology = resolve_topology(document)
    initial = physical_layout(document, topology)
    if document.optimized_layout:
        try:
            previous = optimized_physical_layout(document, topology)
            if not previous.graph.edits:
                initial = previous
        except ValueError:
            pass
    box = box or initial_box(document, radii, initial)
    radii = {node.id: radii[node.id] for node in document.nodes if node.kind not in ("source", "output")}
    clean = deepcopy(document.to_dict())
    clean["optimized_layout"] = clean["optimization"] = None
    source_json = json.dumps(clean, sort_keys=True)
    fingerprint = input_fingerprint(
        document, configuration(box, options), radii, folding_radius=folding_radius
    )
    return _numeric_problem(
        document,
        radii,
        box,
        options,
        identity_graph(document),
        initial.positions,
        source_json,
        fingerprint,
        folding_radius,
    )


def _numeric_problem(
    document, radii, box, options, graph, positions, source_json, fingerprint, folding_radius
):
    derived = effective_document(document, graph, options)
    topology = resolve_topology(derived)
    if not topology.ok:
        raise ValueError(
            "Invalid effective topology: " + "; ".join(item.message for item in topology.diagnostics)
        )
    indices = {node_id: i for i, node_id in enumerate(topology.order)}
    nodes = []
    generated = {mirror.id for mirror in graph.generated}
    for node_id in topology.order:
        node = derived.node(node_id)
        radius = (
            None
            if node.kind in ("source", "output")
            else (folding_radius if node_id in generated else radii[node_id])
        )
        if node_id in generated and (not _finite(radius) or radius <= 0):
            raise ValueError("Folding mirror bounds unavailable")
        nodes.append(
            LayoutNode(node.id, node.reference, radius, node.physical.get("x"), node.physical.get("y"))
        )
    preferred = {}
    for edge in document.connections:
        length = connection_length(document, edge)
        a, b = radii.get(edge.a.node_id), radii.get(edge.b.node_id)
        if a is not None and b is not None:
            length = max(length, a + b + options.clearance_mm)
        preferred[edge.id] = length
    edges, angles, incoming = [], [], {}
    for node_id in topology.order:
        for edge in topology.outgoing[node_id]:
            a, b = indices[node_id], indices[edge.target.node_id]
            length = derived.connection(edge.id).length
            target = sum(weight * preferred[key] for key, weight in graph.segment(edge.id).shares)
            edges.append(LayoutEdge(edge.id, a, b, length, target))
            incoming[b] = a
            if a in incoming:
                node = derived.node(node_id)
                reflecting = node.kind == "mirror" or edge.interaction == "reflected"
                constrained = "turn" in node.physical
                turn = (
                    (interface_turn(derived, node, topology) if constrained else None) if reflecting else 0.0
                )
                angles.append(TurnConstraint(incoming[a], a, b, edge.id, turn))
    edge_indices = {edge.id: i for i, edge in enumerate(edges)}
    path_lengths = tuple(
        PathProjection(
            item.id,
            tuple(edge_indices[key] for key in component_path(derived, item.component_a, item.component_b)),
            item.length_mm,
            indices[item.component_a],
            indices[item.component_b],
        )
        for item in document.path_constraints
    )
    separations = tuple(
        SeparationConstraint(
            edge.id,
            indices[edge.a.node_id],
            indices[edge.b.node_id],
            edge.length,
            tuple(edge_indices[key] for key in component_path(derived, edge.a.node_id, edge.b.node_id)),
        )
        for edge in document.connections
        if edge.length is not None and edge.id not in edge_indices
    )
    source = derived.node(topology.source_id)
    output_directions = tuple(
        DirectionConstraint(
            indices[edge.source.node_id],
            indices[edge.target.node_id],
            derived.node(edge.target.node_id).physical["angle"],
            edge.target.node_id,
            edge.id,
        )
        for edge in topology.edges.values()
        if derived.node(edge.target.node_id).kind in ("output", "fiber_output", "stop")
        and "angle" in derived.node(edge.target.node_id).physical
    )
    initial = physical_layout(derived, topology)
    return OptimizationProblem(
        tuple(nodes),
        tuple(edges),
        tuple(angles),
        tuple(tuple(positions.get(node.id, initial.positions[node.id])) for node in nodes),
        indices[source.id],
        source.physical.get("angle"),
        box,
        options,
        json.dumps(derived.to_dict(), sort_keys=True),
        fingerprint,
        path_lengths,
        separations,
        graph,
        source_json,
        tuple(sorted(radii.items())),
        folding_radius,
        output_directions,
    )


def candidate_problem(root, graph, positions):
    """Worker-safe topology snapshot construction: no CAD or settings access."""
    source = document_from_dict(json.loads(root.source_json))
    return _numeric_problem(
        source,
        dict(root.source_radii),
        root.box,
        root.options,
        graph,
        positions,
        root.source_json,
        root.fingerprint,
        root.folding_radius,
    )


def initial_box(document, radii, layout=None):
    if document.optimization:
        return PackingBox(**document.optimization["box"])
    if layout is None:
        from .compiler import compile_schematic

        compiled = compile_schematic(document)
        layout = compiled.geometry if compiled.ok else None
    missing_bounds = any(
        n.kind not in ("source", "output") and not _finite(radii.get(n.id)) for n in document.nodes
    )
    if layout is None or not layout.positions or missing_bounds:
        sources = [n for n in document.nodes if n.kind in ("source", "fiber_source")]
        source = sources[0] if len(sources) == 1 else None
        x = source.physical.get("x", 0) if source else 0
        y = source.physical.get("y", 0) if source else 0
        return PackingBox(x - 150, y - 100, 300, 200)
    points = [(x, y, radii.get(node_id, 0)) for node_id, (x, y) in layout.positions.items()]
    left, bottom = min(x - r for x, y, r in points) - 10, min(y - r for x, y, r in points) - 10
    right, top = max(x + r for x, y, r in points) + 10, max(y + r for x, y, r in points) + 10
    return PackingBox(left, bottom, right - left, top - bottom)


def _direction(dx, dy, salt=0):
    distance = hypot(dx, dy)
    if distance > 1e-12:
        return dx / distance, dy / distance, distance
    angle = (salt * 2.399963229728653 + 0.731) % (2 * pi)
    return cos(angle), sin(angle), 0.0


def signed_turn(a, b, c):
    return degrees(
        atan2(
            (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]),
            (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]),
        )
    )


def turn_gradients(a, b, c):
    ax, ay, bx, by = b[0] - a[0], b[1] - a[1], c[0] - b[0], c[1] - b[1]
    aa, bb = max(ax * ax + ay * ay, 1e-18), max(bx * bx + by * by, 1e-18)
    ga, gc = (-ay / aa, ax / aa), (-by / bb, bx / bb)
    return ga, (-ga[0] - gc[0], -ga[1] - gc[1]), gc


def capsule_distance(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    squared = dx * dx + dy * dy
    t = max(0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / squared)) if squared else 0.5
    return t, point[0] - a[0] - t * dx, point[1] - a[1] - t * dy


def _mobility(problem):
    return [(float(n.pin_x is None), float(n.pin_y is None)) for n in problem.nodes]


def _correct(positions, mobility, indices, gradients, residual, strength=1):
    denominator = sum(mobility[i][axis] * g[axis] ** 2 for i, g in zip(indices, gradients) for axis in (0, 1))
    if denominator < 1e-20:
        return
    factor = -strength * residual / denominator
    for i, g in zip(indices, gradients):
        for axis in (0, 1):
            positions[i][axis] += factor * mobility[i][axis] * g[axis]


def path_value_gradients(problem, positions, constraint):
    value, gradients = 0.0, {}
    for index in constraint.edges:
        edge = problem.edges[index]
        a, b = positions[edge.a], positions[edge.b]
        nx, ny, distance = _direction(b[0] - a[0], b[1] - a[1], edge.a + edge.b)
        value += distance
        for i, sign in ((edge.a, -1), (edge.b, 1)):
            gradient = gradients.setdefault(i, [0.0, 0.0])
            gradient[0] += sign * nx
            gradient[1] += sign * ny
    indices = tuple(sorted(gradients))
    return value, indices, tuple(tuple(gradients[i]) for i in indices)


def project_constraints(problem, positions, collision_strength=1, mobility=None):
    """One in-place projection pass. Pinned axes always have zero mobility."""
    mobility = mobility or _mobility(problem)
    for edge in problem.edges:
        a, b = positions[edge.a], positions[edge.b]
        nx, ny, distance = _direction(b[0] - a[0], b[1] - a[1], edge.a + edge.b)
        target = edge.fixed_length if edge.fixed_length is not None else 0.001
        if edge.fixed_length is not None or distance < target:
            _correct(positions, mobility, (edge.a, edge.b), ((-nx, -ny), (nx, ny)), distance - target)
    for constraint in problem.separations:
        a, b = positions[constraint.a], positions[constraint.b]
        nx, ny, distance = _direction(b[0] - a[0], b[1] - a[1], constraint.a + constraint.b)
        _correct(
            positions,
            mobility,
            (constraint.a, constraint.b),
            ((-nx, -ny), (nx, ny)),
            distance - constraint.target,
        )
    for constraint in problem.path_lengths:
        value, indices, gradients = path_value_gradients(problem, positions, constraint)
        _correct(positions, mobility, indices, gradients, value - constraint.target)
    for angle in problem.angles:
        a, b, c = (positions[i] for i in (angle.incoming, angle.node, angle.outgoing))
        value = signed_turn(a, b, c)
        target = angle.turn
        if target is None:
            if abs(value) < MIN_BEAM_TURN:
                target = MIN_BEAM_TURN if value >= 0 else -MIN_BEAM_TURN
            elif abs(value) >= 179.9999999:
                target = 179.9999999 if value > 0 else -179.9999999
            else:
                continue
        _correct(
            positions,
            mobility,
            (angle.incoming, angle.node, angle.outgoing),
            turn_gradients(a, b, c),
            radians(wrap_angle(value - target)),
        )
    if problem.source_direction is not None:
        for edge in problem.edges:
            if edge.a != problem.source_index:
                continue
            a, b = positions[edge.a], positions[edge.b]
            dx, dy = b[0] - a[0], b[1] - a[1]
            squared = max(dx * dx + dy * dy, 1e-18)
            value = degrees(atan2(dy, dx))
            _correct(
                positions,
                mobility,
                (edge.a, edge.b),
                ((dy / squared, -dx / squared), (-dy / squared, dx / squared)),
                radians(wrap_angle(value - problem.source_direction)),
            )
    for constraint in problem.output_directions:
        a, b = positions[constraint.a], positions[constraint.b]
        dx, dy = b[0] - a[0], b[1] - a[1]
        squared = max(dx * dx + dy * dy, 1e-18)
        value = degrees(atan2(dy, dx))
        _correct(
            positions,
            mobility,
            (constraint.a, constraint.b),
            ((dy / squared, -dx / squared), (-dy / squared, dx / squared)),
            radians(wrap_angle(value - constraint.angle)),
        )
    clearance = problem.options.clearance_mm
    physical = [i for i, n in enumerate(problem.nodes) if n.radius is not None]
    for offset, i in enumerate(physical):
        for j in physical[:offset]:
            nx, ny, distance = _direction(
                positions[j][0] - positions[i][0], positions[j][1] - positions[i][1], i * 31 + j
            )
            required = problem.nodes[i].radius + problem.nodes[j].radius + clearance
            if distance < required:
                _correct(
                    positions,
                    mobility,
                    (i, j),
                    ((-nx, -ny), (nx, ny)),
                    distance - required,
                    collision_strength,
                )
    half = problem.options.beam_diameter_mm / 2
    for edge in problem.edges:
        for i in physical:
            if i in (edge.a, edge.b):
                continue
            t, dx, dy = capsule_distance(positions[i], positions[edge.a], positions[edge.b])
            nx, ny, distance = _direction(dx, dy, i * 17 + edge.a + edge.b)
            # At exact coincidence use a perpendicular to the beam, so the
            # correction separates an interior disk rather than sliding along it.
            if distance == 0:
                vx, vy, _ = _direction(
                    positions[edge.b][0] - positions[edge.a][0], positions[edge.b][1] - positions[edge.a][1]
                )
                nx, ny = -vy, vx
            required = problem.nodes[i].radius + half + clearance
            if distance < required:
                _correct(
                    positions,
                    mobility,
                    (i, edge.a, edge.b),
                    ((nx, ny), (-(1 - t) * nx, -(1 - t) * ny), (-t * nx, -t * ny)),
                    distance - required,
                    collision_strength,
                )
    box = problem.box
    for i, node in enumerate(problem.nodes):
        margin = max(node.radius or 0, half) + clearance
        for axis, lower, upper in (
            (0, box.x + margin, box.x + box.width - margin),
            (1, box.y + margin, box.y + box.height - margin),
        ):
            if mobility[i][axis]:
                target = max(lower, min(upper, positions[i][axis])) if lower <= upper else (lower + upper) / 2
                positions[i][axis] += collision_strength * (target - positions[i][axis])
        if node.pin_x is not None:
            positions[i][0] = node.pin_x
        if node.pin_y is not None:
            positions[i][1] = node.pin_y


def layout_violations(problem, positions):
    nonfinite = tuple(
        Violation(
            "nonfinite", f"{node.reference}: nonfinite numerical geometry", float("inf"), node_ids=(node.id,)
        )
        for node, point in zip(problem.nodes, positions)
        if not all(map(_finite, point))
    )
    if nonfinite:
        return nonfinite
    result = []

    def add(kind, message, residual, node_indices=(), edges=(), unit="mm", constraints=()):
        tolerance = ANGULAR_TOLERANCE if unit == "°" else LINEAR_TOLERANCE
        if residual > tolerance:
            result.append(
                Violation(
                    kind,
                    message,
                    residual,
                    unit,
                    tuple(problem.nodes[i].id for i in node_indices),
                    tuple(edges),
                    tuple(constraints),
                )
            )

    gap, half, box = problem.options.clearance_mm, problem.options.beam_diameter_mm / 2, problem.box
    for i, node in enumerate(problem.nodes):
        x, y = positions[i]
        for axis, pin in enumerate((node.pin_x, node.pin_y)):
            if pin is not None:
                add(
                    "position",
                    f"{node.reference}: pinned {'XY'[axis]} coordinate",
                    abs(positions[i][axis] - pin),
                    (i,),
                )
        margin = max(node.radius or 0, half) + gap
        excess = max(
            box.x + margin - x,
            x + margin - box.x - box.width,
            box.y + margin - y,
            y + margin - box.y - box.height,
            0,
        )
        add("boundary", f"{node.reference}: outside rectangle margin", excess, (i,))
    physical = [i for i, n in enumerate(problem.nodes) if n.radius is not None]
    for offset, i in enumerate(physical):
        for j in physical[:offset]:
            residual = (
                problem.nodes[i].radius
                + problem.nodes[j].radius
                + gap
                - hypot(positions[i][0] - positions[j][0], positions[i][1] - positions[j][1])
            )
            add(
                "part_clearance",
                f"{problem.nodes[i].reference} / {problem.nodes[j].reference}: part clearance",
                residual,
                (i, j),
            )
    for edge in problem.edges:
        a, b = positions[edge.a], positions[edge.b]
        distance = hypot(b[0] - a[0], b[1] - a[1])
        add(
            "length",
            f"{problem.nodes[edge.a].reference} → {problem.nodes[edge.b].reference}: beam length",
            abs(distance - edge.fixed_length) if edge.fixed_length is not None else max(0, 0.001 - distance),
            (edge.a, edge.b),
            (edge.id,),
        )
        for i in physical:
            if i in (edge.a, edge.b):
                continue
            _, dx, dy = capsule_distance(positions[i], a, b)
            add(
                "beam_clearance",
                f"{problem.nodes[i].reference}: beam clearance",
                problem.nodes[i].radius + half + gap - hypot(dx, dy),
                (i,),
                (edge.id,),
            )
        if edge.a == problem.source_index and problem.source_direction is not None:
            error = abs(wrap_angle(degrees(atan2(b[1] - a[1], b[0] - a[0])) - problem.source_direction))
            add("source_direction", "Source direction", error, (edge.a,), (edge.id,), "°")
    for constraint in problem.output_directions:
        a, b = positions[constraint.a], positions[constraint.b]
        value = degrees(atan2(b[1] - a[1], b[0] - a[0]))
        add(
            "output_direction",
            f"{problem.nodes[constraint.b].reference}: output direction",
            abs(wrap_angle(value - constraint.angle)),
            (constraint.b,),
            (constraint.connection_id,),
            "°",
        )
    for constraint in problem.separations:
        a, b = positions[constraint.a], positions[constraint.b]
        add(
            "separation",
            "Constrained beam endpoint separation",
            abs(hypot(b[0] - a[0], b[1] - a[1]) - constraint.target),
            (constraint.a, constraint.b),
            tuple(problem.edges[i].id for i in constraint.edges),
        )
    for constraint in problem.path_lengths:
        value, _, _ = path_value_gradients(problem, positions, constraint)
        add(
            "path_length",
            "Total path length",
            abs(value - constraint.target),
            (constraint.a, constraint.b),
            tuple(problem.edges[i].id for i in constraint.edges),
            constraints=(constraint.id,),
        )
    for constraint in problem.angles:
        a, b, c = (positions[i] for i in (constraint.incoming, constraint.node, constraint.outgoing))
        value = signed_turn(a, b, c)
        residual = (
            abs(wrap_angle(value - constraint.turn))
            if constraint.turn is not None
            else max(MIN_BEAM_TURN - abs(value), abs(value) - 179.9999999, 0)
        )
        add(
            "turn",
            f"{problem.nodes[constraint.node].reference}: beam turn",
            residual,
            (constraint.node,),
            (constraint.connection_id,),
            "°",
        )
    return tuple(sorted(result, key=lambda v: (-v.residual, v.kind, v.node_ids, v.connection_ids)))


def forces(problem, positions):
    """Hooke attraction and inverse-square repulsion, in characteristic units."""
    scale = median(e.preferred_length for e in problem.edges) if problem.edges else 50
    result = [[0.0, 0.0] for _ in positions]
    for edge in problem.edges:
        nx, ny, distance = _direction(
            positions[edge.b][0] - positions[edge.a][0],
            positions[edge.b][1] - positions[edge.a][1],
            edge.a + edge.b,
        )
        target = edge.fixed_length if edge.fixed_length is not None else edge.preferred_length
        force = distance - target
        for axis, n in enumerate((nx, ny)):
            result[edge.a][axis] += force * n
            result[edge.b][axis] -= force * n
    for i in range(len(positions)):
        for j in range(i):
            nx, ny, distance = _direction(
                positions[j][0] - positions[i][0], positions[j][1] - positions[i][1], i * 31 + j
            )
            force = 0.01 * scale**3 / max(distance, 0.1 * scale) ** 2
            for axis, n in enumerate((nx, ny)):
                result[i][axis] -= force * n
                result[j][axis] += force * n
    return result


def reconstruct_candidate(problem, positions, document=None, topology=None):
    document = document or document_from_dict(json.loads(problem.document_json))
    topology = topology or resolve_topology(document)
    lengths = {
        e.id: (
            e.fixed_length
            if e.fixed_length is not None
            else max(
                0.001, hypot(positions[e.b][0] - positions[e.a][0], positions[e.b][1] - positions[e.a][1])
            )
        )
        for e in problem.edges
    }
    turns = {
        n.id: interface_turn(document, n, topology)
        for n in document.nodes
        if n.kind in ("mirror", "splitter")
    }
    for angle in problem.angles:
        node_id = problem.nodes[angle.node].id
        node = document.node(node_id)
        edge = topology.edges[angle.connection_id]
        if node.kind == "mirror" or edge.interaction == "reflected":
            value = signed_turn(positions[angle.incoming], positions[angle.node], positions[angle.outgoing])
            turns[node_id] = (
                angle.turn
                if angle.turn is not None
                else (1 if value >= 0 else -1) * max(MIN_BEAM_TURN, min(179.9999999, abs(value)))
            )
    source = problem.source_index
    first = next(e for e in problem.edges if e.a == source)
    a, b = positions[source], positions[first.b]
    direction = (
        problem.source_direction
        if problem.source_direction is not None
        else degrees(atan2(b[1] - a[1], b[0] - a[0]))
    )
    layout = replace(
        physical_layout(document, topology, lengths, turns, (*a, direction)), graph=problem.graph
    )
    exact = tuple(layout.positions[n.id] for n in problem.nodes)
    return layout, exact, layout_violations(problem, exact)


def _optimize_fixed(problem, options=None, progress=None, cancelled=None):
    """Pure numerical search. Callbacks run in the calling worker thread.

    A cancelled search never offers Apply, even if an earlier start was feasible.
    Absence of a result is a budget exhaustion, not a proof of infeasibility.
    """
    options = options or problem.options
    if options != problem.options:
        from dataclasses import replace

        if (options.clearance_mm, options.beam_diameter_mm) != (
            problem.options.clearance_mm,
            problem.options.beam_diameter_mm,
        ):
            raise ValueError("Packing settings changed; build a new problem snapshot before optimization")
        problem = replace(problem, options=options)
    cancelled = cancelled or (lambda: False)
    rng = random.Random(options.seed)
    mobility = _mobility(problem)
    document = document_from_dict(json.loads(problem.document_json))
    topology = resolve_topology(document)
    best, best_score = None, float("inf")
    closest = problem.initial_positions
    closest_violations = layout_violations(problem, closest)
    closest_score = float("inf")
    count = 0
    last_update = -float("inf")
    scale = median(e.preferred_length for e in problem.edges)
    for start in range(options.starts):
        positions = [list(p) for p in problem.initial_positions]
        if start:
            for i, node in enumerate(problem.nodes):
                for axis, origin, size in (
                    (0, problem.box.x, problem.box.width),
                    (1, problem.box.y, problem.box.height),
                ):
                    if mobility[i][axis]:
                        positions[i][axis] = origin + rng.uniform(0.1, 0.9) * size
        else:
            # Translate the initial geometry into the box when axes are free.
            for axis, origin, size in (
                (0, problem.box.x, problem.box.width),
                (1, problem.box.y, problem.box.height),
            ):
                if all(m[axis] for m in mobility):
                    offset = (
                        origin
                        + size / 2
                        - (min(p[axis] for p in positions) + max(p[axis] for p in positions)) / 2
                    )
                    for p in positions:
                        p[axis] += offset
        for i, n in enumerate(problem.nodes):
            for axis, pin in enumerate((n.pin_x, n.pin_y)):
                if pin is not None:
                    positions[i][axis] = pin
        # Do not discard an already feasible warm start while forces explore.
        layout, exact, violations = reconstruct_candidate(problem, positions, document, topology)
        score = sum(v.residual**2 for v in violations)
        if score < closest_score:
            closest_score, closest, closest_violations = score, exact, violations
        if not violations:
            energy = sum((layout.lengths[e.id] - e.preferred_length) ** 2 for e in problem.edges)
            if energy < best_score:
                best, best_score = layout, energy
        velocity = [[0.0, 0.0] for _ in positions]
        feasible_streak = 0
        for iteration in range(options.iterations):
            if cancelled():
                return OptimizationResult(
                    "cancelled", None, closest, closest_violations, count, start + 1, problem
                )
            count += 1
            before = [p[:] for p in positions]
            force = forces(problem, positions)
            # Forces decay late in each start to permit strict projection convergence.
            anneal = max(0.0, 1 - iteration / max(1, 0.8 * options.iterations)) ** 3
            cap = scale * 0.08
            for i in range(len(positions)):
                for axis in (0, 1):
                    velocity[i][axis] = mobility[i][axis] * (
                        0.8 * velocity[i][axis] + 0.04 * anneal * force[i][axis]
                    )
                speed = hypot(*velocity[i])
                if speed > cap:
                    velocity[i] = [v * cap / speed for v in velocity[i]]
                for axis in (0, 1):
                    positions[i][axis] += velocity[i][axis]
            ramp = min(1.0, (iteration + 1) / min(100, max(1, options.iterations // 10)))
            for _ in range(options.projection_passes):
                if cancelled():
                    return OptimizationResult(
                        "cancelled", None, closest, closest_violations, count, start + 1, problem
                    )
                project_constraints(problem, positions, ramp, mobility)
            velocity = [[(p[a] - old[a]) * 0.5 for a in (0, 1)] for p, old in zip(positions, before)]
            layout, exact, violations = reconstruct_candidate(problem, positions, document, topology)
            score = sum(v.residual**2 for v in violations)
            if score < closest_score:
                closest_score, closest, closest_violations = score, exact, violations
            if not violations:
                energy = sum((layout.lengths[e.id] - e.preferred_length) ** 2 for e in problem.edges)
                if energy < best_score:
                    best, best_score = layout, energy
                feasible_streak += 1
            else:
                feasible_streak = 0
            now = monotonic()
            if progress and (now - last_update >= 0.1 or iteration == options.iterations - 1):
                progress(
                    OptimizationProgress(
                        start + 1, iteration + 1, count, exact, violations, not violations, problem
                    )
                )
                last_update = now
            if feasible_streak >= 40:
                break
        # Exact zero spring error cannot be improved by another start.
        if best is not None and best_score < 1e-12:
            break
    if cancelled():
        return OptimizationResult("cancelled", None, closest, closest_violations, count, start + 1, problem)
    if best is not None:
        positions = tuple(best.positions[n.id] for n in problem.nodes)
        return OptimizationResult("feasible", best, positions, (), count, start + 1, problem)
    return OptimizationResult(
        "no_feasible_layout", None, closest, closest_violations, count, start + 1, problem
    )


def optimize_layout(problem, options=None, progress=None, cancelled=None):
    """Optimize geometry and permitted topology; CAD-independent and cancellable."""
    options = options or problem.options
    if options != problem.options:
        if (
            options.clearance_mm,
            options.beam_diameter_mm,
            options.folding_preset,
            options.folding_diameter_mm,
        ) != (
            problem.options.clearance_mm,
            problem.options.beam_diameter_mm,
            problem.options.folding_preset,
            problem.options.folding_diameter_mm,
        ):
            raise ValueError("Packing or part settings changed; build a new problem snapshot")
        problem = replace(problem, options=options)
    source = document_from_dict(json.loads(problem.source_json or problem.document_json))
    from .effective import folding_protection

    adaptive = (
        any(edge.allow_folding for edge in source.connections)
        and options.max_added_mirrors > 0
        and options.max_folds_per_beam > 0
    ) or any(node.kind == "mirror" and folding_protection(source, node.id) is None for node in source.nodes)
    if adaptive:
        from .folding import adaptive_layout

        return adaptive_layout(problem, progress, cancelled)
    return _optimize_fixed(problem, progress=progress, cancelled=cancelled)


def _saved_candidate(document, saved, config):
    options = OptimizationOptions(**config["options"])
    if set(saved["radii"]) != {node.id for node in document.nodes if node.kind not in ("source", "output")}:
        raise ValueError("Optimized layout has incomplete physical bounds; rerun or clear it")
    graph = replay_graph(document, saved["graph"], options)
    derived = effective_document(document, graph, options)
    topology = resolve_topology(derived)
    geometry = saved["geometry"]
    turns = {node.id for node in derived.nodes if node.kind in ("mirror", "splitter")}
    if set(geometry["lengths"]) != set(topology.edges) or set(geometry["turns"]) != turns:
        raise ValueError("Optimized layout has incomplete optical geometry; rerun or clear it")
    layout = replace(physical_layout(derived, topology, **geometry), graph=graph)
    clean = deepcopy(document.to_dict())
    clean["optimized_layout"] = clean["optimization"] = None
    source_json = json.dumps(clean, sort_keys=True)
    problem = _numeric_problem(
        document_from_dict(clean),
        saved["radii"],
        PackingBox(**config["box"]),
        options,
        graph,
        layout.positions,
        source_json,
        saved["fingerprint"],
        saved["folding_radius"],
    )
    violations = layout_violations(problem, tuple(layout.positions[node.id] for node in problem.nodes))
    if violations:
        raise ValueError("Saved optimized layout failed verification: " + violations[0].message)
    return layout


def optimized_physical_layout(document, topology=None):
    saved = document.optimized_layout
    if saved is None:
        return None
    validate_saved_optimization(document.optimization, saved)
    if saved.get("input_version") != 5:
        raise ValueError(
            "Optimized layout is stale after the format upgrade. Rerun Optimize physical layout or Clear optimized layout."
        )
    if (
        input_fingerprint(
            document, document.optimization, saved["radii"], folding_radius=saved["folding_radius"]
        )
        != saved["fingerprint"]
    ):
        raise ValueError(
            "Optimized layout is stale. Rerun Optimize physical layout or Clear optimized layout before export."
        )
    return _saved_candidate(document, saved, document.optimization)


def apply_optimization(document, problem, result):
    if result.status != "feasible" or result.layout is None:
        raise ValueError("Only a verified feasible layout can be applied")
    config = configuration(problem.box, problem.options)
    radii = dict(problem.source_radii)
    if (
        input_fingerprint(document, config, radii, folding_radius=problem.folding_radius)
        != problem.fingerprint
    ):
        raise ValueError("Schematic changed during optimization. Run the optimizer again.")
    graph = result.layout.graph or identity_graph(document)
    saved = {
        "fingerprint": problem.fingerprint,
        "geometry": result.layout.snapshot(problem.nodes[problem.source_index].id),
        "radii": radii,
        "graph": graph.to_dict(),
        "input_version": 5,
        "folding_radius": problem.folding_radius,
    }
    validate_saved_optimization(config, saved)
    _saved_candidate(document, saved, config)
    document.optimization = config
    document.optimized_layout = saved
