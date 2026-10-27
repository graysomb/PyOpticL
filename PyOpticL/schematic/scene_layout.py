"""Physical scene state, finite ray visits, and exact shared-component tracing."""

from copy import deepcopy
from dataclasses import dataclass, field
from math import acos, atan2, cos, degrees, hypot, radians, sin
from PyOpticL.ray_math import (
    add,
    sub,
    mul,
    dot,
    norm,
    unit,
    yaw,
    heading,
    reflect,
    lens_direction,
    grating_direction,
)
from .optic_geometry import element_spec, aperture_excess, roof_trace
from .registry import SYMBOLS, COUPLING_MOUNTS, parameter_values, default_turn
from .physical import PhysicalLayout, wrap_angle
from .topology import Diagnostic, resolve_topology
from .paths import component_path


@dataclass(frozen=True)
class PassState:
    entry: tuple
    exit: tuple
    incoming: tuple
    outputs: dict
    path: tuple = ()
    internal_length: float = 0


@dataclass(frozen=True)
class Residual:
    id: str
    value: float
    message: str
    node_id: str | None = None
    pass_id: str | None = None
    connection_id: str | None = None
    unit: str = "mm"
    equality: bool = True


@dataclass
class SceneTrace:
    layout: PhysicalLayout
    residuals: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)

    @property
    def ok(self):
        return not any(d.severity == "error" for d in self.diagnostics) and not any(
            abs(r.value) > 1e-6 for r in self.residuals
        )


def is_physical(document):
    return document.layout is not None or any(p.id != p.component_id for p in document.passes)


def source_offset(node):
    return 180 if node.kind == "fiber_source" and node.preset not in COUPLING_MOUNTS else 0


def initialize_layout(document, legacy=False):
    if document.layout is not None:
        return
    poses = {n.id: [*n.position, 0.0, n.rotation] for n in document.nodes}
    notes = []
    geometry = None
    if legacy and document.optimized_layout is not None:
        try:
            from .optimization import _saved_candidate

            geometry = _saved_candidate(document, document.optimized_layout, document.optimization)
        except (ValueError, KeyError, TypeError):
            pass
    if not any(p.id != p.component_id for p in document.passes) and geometry is None:
        from .compiler import compile_schematic

        compiled = compile_schematic(document)
        geometry = compiled.geometry
    if geometry is not None:
        poses = {
            key: [*point, geometry.heights.get(key, 0), geometry.orientations[key]]
            for key, point in geometry.positions.items()
        }
    elif legacy:
        poses = {n.id: [n.position[0] / 4, n.position[1] / 4, 0.0, n.rotation] for n in document.nodes}
        notes.append("Previous layout could not be resolved; physical poses are editable estimates.")
    if legacy and any(e.bends for e in document.connections):
        notes.append("Decorative drawing bends were removed; physical beam turns require an optic.")
        for edge in document.connections:
            edge.bends = []
    document.layout = {"poses": poses, "projection": "XY", "notes": notes, "splitters": {}}
    if legacy:
        document.settings["grid"] = 1.0
    if legacy:
        from .model import OpticalPass

        for node in document.nodes:
            values = [edge.turns[node.id] for edge in document.connections if node.id in edge.turns]
            target = node.physical.get("turn")
            if target is not None and any(abs(value - target) > 1e-6 for value in values):
                continue  # Preserve conflicting legacy equations for an actionable diagnostic.
            if values and max(values) - min(values) <= 1e-6:
                target = values[0]
            if target is not None and not any(p.id == node.id for p in document.passes):
                document.passes.append(OpticalPass(node.id, node.id, turn=target))
                node.physical.pop("turn", None)
                if values and max(values) - min(values) <= 1e-6:
                    for edge in document.connections:
                        edge.turns.pop(node.id, None)
        if document.optimized_layout is not None:
            from .model import document_from_dict

            raw = document.to_dict()
            raw["layout"] = None
            raw["optimized_layout"] = None
            raw["optimization"] = None
            clean = document_from_dict(raw)
            from .compiler import compile_schematic

            initial = compile_schematic(clean).geometry
            if initial is not None:
                document.layout["legacy_manual_poses"] = {
                    key: [*point, initial.heights.get(key, 0), initial.orientations[key]]
                    for key, point in initial.positions.items()
                }
    # Poses are effective free values, never hard constraints.
    topology = resolve_topology(document)
    for node in document.nodes:
        if node.kind == "splitter":
            canonical = default_turn(node.kind, topology.incident_ports.get(node.id))
            p = document.optical_pass(node.id)
            turn = p.turn if p.turn is not None else node.physical.get("turn", canonical)
            document.layout["splitters"][node.id] = (turn > 0) != (canonical > 0)


def poses_for(document):
    return {
        n.id: list((document.layout or {}).get("poses", {}).get(n.id, (*n.position, 0.0, n.rotation)))
        for n in document.nodes
    }


def splitter_flip(document, node):
    if document.layout and node.id in document.layout.get("splitters", {}):
        return document.layout["splitters"][node.id]
    topo = resolve_topology(document)
    canonical = default_turn(node.kind, topo.incident_ports.get(node.id))
    visit = document.optical_pass(node.id)
    turn = visit.turn if visit.turn is not None else node.physical.get("turn", canonical)
    return (turn > 0) != (canonical > 0)


def interface_angle(document, node, spec):
    return (45 if splitter_flip(document, node) else -45) if node.kind == "splitter" else spec.normal_angle


def intersect(document, node, pose, origin, direction, topology, finite=False):
    spec = element_spec(node, topology)
    if spec is None:
        return None
    angle = pose[3] + interface_angle(document, node, spec)
    normal = yaw((1.0, 0.0, 0.0), angle)
    den = dot(direction, normal)
    if finite and (abs(den) < 1e-6 or (spec.single_sided and den >= 0)):
        return None
    safe = den if abs(den) > 1e-5 else (1e-5 if den >= 0 else -1e-5)
    distance = dot(sub(pose[:3], origin), normal) / safe
    hit = add(origin, mul(direction, distance))
    local = yaw(sub(hit, pose[:3]), -angle)
    if finite:
        aperture = spec.aperture
        if node.kind == "iris":
            aperture = ("circle", 10 if node.preset == "alignment" else 6.35)
        if node.kind == "slit":
            aperture = ("circle", 13.589 / 2)
        from dataclasses import replace

        if aperture_excess(replace(spec, aperture=aperture), local) > 1e-8 or distance <= 1e-6:
            return None
        if node.kind == "roof":
            entry = yaw(sub(hit, pose[:3]), -pose[3])
            d = yaw(direction, -pose[3])
            if (
                roof_trace(
                    entry,
                    d,
                    parameter_values(node)["beam_separation"],
                    "vertical" in node.preset,
                    topology.incident_ports.get(node.id) == "B",
                )
                is None
            ):
                return None
    return distance, hit, normal, local, spec


def trace_scene(document, poses=None, *, check_interceptions=True, topology=None):
    poses = poses_for(document) if poses is None else poses
    topo = topology or resolve_topology(document)
    states, headings, lengths, origins, turns, internal = {}, {}, {}, {}, {}, {}
    source_id = topo.source_id
    source = document.node(topo.passes[source_id].component_id) if source_id else None
    sd = (poses[source.id][3] - source_offset(source)) if source else 0.0
    layout = PhysicalLayout(
        {k: tuple(v[:2]) for k, v in poses.items()},
        {k: v[3] for k, v in poses.items()},
        headings,
        lengths,
        turns,
        sd,
        origins=origins,
        heights={k: v[2] for k, v in poses.items()},
        poses={k: tuple(v) for k, v in poses.items()},
        visits=states,
        internal_lengths=internal,
    )
    result = SceneTrace(layout, diagnostics=list(topo.diagnostics))

    def residual(key, value, message, node=None, visit=None, edge=None, unit="mm", equality=True):
        result.residuals.append(Residual(key, float(value), message, node, visit, edge, unit, equality))

    if not topo.ok:
        return result
    rays = {}
    incoming_edges = {e.target.visit_id: e for e in topo.edges.values()}
    wavelength = parameter_values(source)["wavelength"]
    for visit_id in topo.order:
        visit = topo.passes[visit_id]
        node = document.node(visit.component_id)
        pose = poses[node.id]
        if visit.mode == "emit":
            direction = yaw((1.0, 0.0, 0.0), sd)
            state = PassState(tuple(pose[:3]), tuple(pose[:3]), direction, {"out": direction})
        else:
            origin, direction = rays[visit_id]
            edge = incoming_edges[visit_id]
            if node.kind == "output":
                distance = dot(sub(pose[:3], origin), direction)
                hit = add(origin, mul(direction, distance))
                for axis in range(3):
                    residual(
                        f"output/{visit_id}/{axis}",
                        hit[axis] - pose[axis],
                        f"{node.reference}: output must lie on its ray",
                        node.id,
                        visit_id,
                        edge.id,
                    )
                normal = yaw((1.0, 0.0, 0.0), pose[3])
                local = (0.0, 0.0, 0.0)
                spec = None
            else:
                distance, hit, normal, local, spec = intersect(document, node, pose, origin, direction, topo)
                residual(
                    f"aperture/{visit_id}",
                    max(0, aperture_excess(spec, local)),
                    f"{node.reference}: pass misses clear aperture",
                    node.id,
                    visit_id,
                    edge.id,
                    equality=False,
                )
                residual(
                    f"grazing/{visit_id}",
                    max(0, 1e-5 - abs(dot(direction, normal))),
                    f"{node.reference}: grazing ray",
                    node.id,
                    visit_id,
                    edge.id,
                    equality=False,
                )
                if spec.single_sided:
                    residual(
                        f"side/{visit_id}",
                        max(0, dot(direction, normal) + 1e-8),
                        f"{node.reference}: ray reaches the back of the optic",
                        node.id,
                        visit_id,
                        edge.id,
                        equality=False,
                    )
            residual(
                f"positive/{edge.id}",
                max(0, 0.001 - distance),
                f"{node.reference}: beam must travel forward",
                node.id,
                visit_id,
                edge.id,
                equality=False,
            )
            lengths[edge.id] = distance
            headings[edge.id] = heading(direction)
            origins[edge.id] = tuple(origin[:2])
            constrained = document.connection(edge.id).length
            if constrained is not None:
                residual(
                    f"length/{edge.id}",
                    distance - constrained,
                    "Constrained beam length",
                    node.id,
                    visit_id,
                    edge.id,
                )
            outputs = {}
            exit = hit
            path = ()
            air = 0.0
            if visit.mode != "receive":
                if node.kind == "roof":
                    p = parameter_values(node)
                    traced = roof_trace(
                        yaw(sub(hit, pose[:3]), -pose[3]),
                        yaw(direction, -pose[3]),
                        p["beam_separation"],
                        "vertical" in node.preset,
                        topo.incident_ports.get(node.id) == "B",
                    )
                    if traced is None:
                        for axis in (1, 2):
                            residual(
                                f"roof/{visit_id}/{axis}",
                                local[axis],
                                f"{node.reference}: roof misses finite facets",
                                node.id,
                                visit_id,
                                edge.id,
                            )
                        residual(
                            f"roofdir/{visit_id}",
                            max(0.001, abs(yaw(direction, -pose[3])[1])),
                            f"{node.reference}: invalid roof entrance direction",
                            node.id,
                            visit_id,
                            edge.id,
                            equality=False,
                        )
                        shift = (
                            (0, 0, p["beam_separation"])
                            if "vertical" in node.preset
                            else (0, -p["beam_separation"], 0)
                        )
                        if topo.incident_ports.get(node.id) == "B":
                            shift = mul(shift, -1)
                        exit = add(hit, yaw(shift, pose[3]))
                        out = mul(direction, -1)
                        air = 25.4
                    else:
                        for axis in (1, 2):
                            residual(
                                f"roof/{visit_id}/{axis}",
                                0.0,
                                f"{node.reference}: roof misses finite facets",
                                node.id,
                                visit_id,
                                edge.id,
                            )
                        residual(
                            f"roofdir/{visit_id}",
                            0.0,
                            f"{node.reference}: invalid roof entrance direction",
                            node.id,
                            visit_id,
                            edge.id,
                            equality=False,
                        )
                        points, out, air = traced
                        path = tuple(add(pose[:3], yaw(point, pose[3])) for point in points)
                        exit = path[-1]
                        out = yaw(out, pose[3])
                    outputs = {"out": out}
                elif node.kind == "lens":
                    outputs = {
                        "out": lens_direction(
                            direction, normal, sub(hit, pose[:3]), parameter_values(node)["focal_length"]
                        )
                    }
                elif node.kind in ("mirror", "splitter"):
                    reflected = reflect(direction, normal)
                    outputs = (
                        {"out": reflected}
                        if node.kind == "mirror"
                        else {"transmitted": direction, "reflected": reflected}
                    )
                elif node.kind == "grating":
                    transverse = yaw((0, 1.0, 0), pose[3] + spec.normal_angle)
                    out = grating_direction(
                        direction, normal, transverse, wavelength, parameter_values(node)["order"]
                    )
                    residual(
                        f"order/{visit_id}",
                        0 if out else 1,
                        f"{node.reference}: nonpropagating grating order",
                        node.id,
                        visit_id,
                        equality=False,
                    )
                    outputs = {"out": out or direction}
                else:
                    outputs = {"out": direction}
            state = PassState(tuple(hit), tuple(exit), tuple(direction), outputs, path, air)
            internal[visit_id] = air
            target_turn = visit.turn
            if target_turn is None and visit_id == node.id and node.kind in ("mirror", "splitter"):
                target_turn = node.physical.get("turn")
                legacy = [e.turns[node.id] for e in document.connections if node.id in e.turns]
                if legacy:
                    target_turn = legacy[0]
            for role, out in outputs.items():
                if node.kind in ("mirror", "splitter") and role != "transmitted":
                    value = wrap_angle(heading(out) - heading(direction))
                    turns[visit_id] = value
                    if target_turn is not None:
                        residual(
                            f"turn/{visit_id}",
                            wrap_angle(value - target_turn),
                            f"{node.reference}: constrained pass turn",
                            node.id,
                            visit_id,
                            unit="°",
                        )
            target_dir = getattr(visit, "direction", None)
            if visit.mode == "receive" and target_dir is None and visit_id == node.id:
                target_dir = node.physical.get("angle")
            if target_dir is not None:
                residual(
                    f"direction/{visit_id}",
                    wrap_angle(heading(direction) - target_dir),
                    f"{node.reference}: constrained output direction",
                    node.id,
                    visit_id,
                    edge.id,
                    "°",
                )
        states[visit_id] = state
        for edge in topo.outgoing[visit_id]:
            rays[edge.target.visit_id] = (state.exit, state.outputs.get(edge.interaction, state.incoming))
    for node in document.nodes:
        for axis, key in enumerate(("x", "y")):
            if key in node.physical:
                residual(
                    f"pin/{node.id}/{key}",
                    poses[node.id][axis] - node.physical[key],
                    f"{node.reference}: pinned {key.upper()}",
                    node.id,
                )
    if "angle" in source.physical:
        residual(
            f"source/{source.id}",
            wrap_angle(sd - source.physical["angle"]),
            "Constrained source direction",
            source.id,
            source_id,
            unit="°",
        )
    for constraint in document.path_constraints:
        a, b = constraint.pass_a or constraint.component_a, constraint.pass_b or constraint.component_b
        try:
            route = component_path(document, a, b)
            routed = set(route)
            total = sum(lengths[e] for e in route) + sum(
                internal.get(v, 0) for v in topo.order if any(e.id in routed for e in topo.outgoing[v])
            )
            residual(
                constraint.id, total - constraint.length_mm, "Total path length", constraint.component_a, a
            )
        except (KeyError, ValueError) as error:
            result.diagnostics.append(
                Diagnostic(str(error), constraint.component_a, constraint_id=constraint.id)
            )
    if check_interceptions:
        for edge in topo.edges.values():
            a, b = states[edge.source.visit_id], states[edge.target.visit_id]
            d = a.outputs.get(edge.interaction, a.incoming)
            for other in document.nodes:
                if (
                    other.id in (edge.source.node_id, edge.target.node_id)
                    or element_spec(other, topo) is None
                ):
                    continue
                if (
                    other.kind == "fiber_source"
                    and other.preset in COUPLING_MOUNTS
                    and not any(
                        p.mode == "receive" and p.component_id == other.id for p in topo.passes.values()
                    )
                ):
                    continue
                found = intersect(document, other, poses[other.id], a.exit, d, topo, finite=True)
                limit = lengths[edge.id]
                if found and found[0] < limit - 1e-6:
                    result.diagnostics.append(
                        Diagnostic(
                            f"{other.reference}: unexpected interception on this beam; add an explicit pass or move the optic",
                            other.id,
                            edge.id,
                            pass_id=edge.source.visit_id,
                        )
                    )
    return result
