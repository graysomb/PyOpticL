"""Portable schematic documents and lossless undo/redo history."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json
import math
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from .registry import SYMBOLS, default_turn, legacy_port

VERSION = 6


def new_id():
    return str(uuid4())


@dataclass
class Node:
    id: str
    reference: str
    kind: str
    preset: str
    parameters: dict = field(default_factory=dict)
    # Legacy drawing seeds; physical XYZ/yaw free values live in Schematic.layout.
    position: tuple[float, float] = (0, 0)
    rotation: float = 0
    physical: dict = field(default_factory=dict)
    mirror_role: str = "turning"


@dataclass(frozen=True, order=True)
class Endpoint:
    node_id: str
    port_id: str
    pass_id: str = ""

    @property
    def visit_id(self):
        return self.pass_id or self.node_id


@dataclass
class OpticalPass:
    id: str
    component_id: str
    mode: str = "pass"
    turn: float | None = None
    direction: float | None = None
    centered: bool = True


@dataclass
class Connection:
    """An undirected connection; bends run from a to b in storage order."""

    id: str
    a: Endpoint
    b: Endpoint
    bends: list = field(default_factory=list)
    length: float | None = None  # physical separation in mm; None uses the document default
    turns: dict[str, float] = field(
        default_factory=dict
    )  # legacy beam angles; physical editor edits use OpticalPass.turn
    allow_folding: bool = False


@dataclass
class PathLengthConstraint:
    id: str
    component_a: str
    component_b: str
    length_mm: float
    pass_a: str = ""
    pass_b: str = ""


@dataclass
class Schematic:
    title: str = "Optical schematic"
    nodes: list[Node] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)
    settings: dict = field(
        default_factory=lambda: {
            "grid": 20,
            "angle": 45,
            "snap_grid": True,
            "snap_angle": True,
            "spacing": 50,
            "open_length": 50,
            "show_bounds": False,
            "bounds_scale": 4.0,
        }
    )
    version: int = VERSION
    optimization: dict | None = None
    optimized_layout: dict | None = None
    path_constraints: list[PathLengthConstraint] = field(default_factory=list)
    passes: list[OpticalPass] = field(default_factory=list)
    layout: dict | None = None

    def optical_passes(self):
        explicit = {item.id: item for item in self.passes}
        return [
            explicit.get(
                node.id,
                OpticalPass(
                    node.id,
                    node.id,
                    (
                        "emit"
                        if SYMBOLS[node.kind].role == "source"
                        else "receive" if SYMBOLS[node.kind].role == "terminal" else "pass"
                    ),
                ),
            )
            for node in self.nodes
        ] + [item for item in self.passes if item.id != item.component_id]

    def optical_pass(self, pass_id):
        return next(item for item in self.optical_passes() if item.id == pass_id)

    def add_pass(self, component_id, mode="pass"):
        node = self.node(component_id)
        if node.kind in ("source", "output", "stop"):
            raise ValueError("This endpoint has only one optical interaction")
        if SYMBOLS[node.kind].role in ("source", "terminal"):
            mode = "receive"
        item = OpticalPass(new_id(), component_id, mode)
        self.passes.append(item)
        return item

    def remove_pass(self, pass_id):
        item = self.optical_pass(pass_id)
        if item.id == item.component_id:
            raise ValueError("The primary pass belongs to the component; delete the component to remove it")
        self.passes[:] = [p for p in self.passes if p.id != pass_id]
        self.connections[:] = [e for e in self.connections if pass_id not in (e.a.visit_id, e.b.visit_id)]
        self.path_constraints[:] = [c for c in self.path_constraints if pass_id not in (c.pass_a, c.pass_b)]

    def node(self, node_id):
        return next(node for node in self.nodes if node.id == node_id)

    def connection(self, connection_id):
        return next(edge for edge in self.connections if edge.id == connection_id)

    def add_node(self, kind, position=(0, 0)):
        symbol = SYMBOLS[kind]
        used = {node.reference for node in self.nodes}
        number = 1
        while f"{symbol.prefix}{number}" in used:
            number += 1
        node = Node(new_id(), f"{symbol.prefix}{number}", kind, symbol.presets[0], position=tuple(position))
        self.nodes.append(node)
        return node

    def remove_nodes(self, ids):
        ids = set(ids)
        self.nodes[:] = [node for node in self.nodes if node.id not in ids]
        self.connections[:] = [
            edge for edge in self.connections if edge.a.node_id not in ids and edge.b.node_id not in ids
        ]
        self.path_constraints[:] = [
            constraint
            for constraint in self.path_constraints
            if constraint.component_a not in ids and constraint.component_b not in ids
        ]
        self.passes[:] = [item for item in self.passes if item.component_id not in ids]
        if self.layout:
            for node_id in ids:
                self.layout.get("poses", {}).pop(node_id, None)

    def duplicate_nodes(self, ids):
        copies = []
        for original in list(self.nodes):
            if original.id in ids:
                node = self.add_node(original.kind, (original.position[0] + 40, original.position[1] + 40))
                node.preset = original.preset
                node.parameters = deepcopy(original.parameters)
                node.physical = deepcopy(original.physical)
                node.rotation = original.rotation
                node.mirror_role = original.mirror_role
                copies.append(node)
        return copies

    def to_dict(self):
        return asdict(self)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(map(_finite, value))


def document_from_dict(data, *, migrate_lengths=True):
    """Reject malformed files before they can reach Qt or the compiler."""
    try:
        if (
            not isinstance(data, dict)
            or type(data.get("version")) is not int
            or data["version"] not in (1, 2, 3, 4, 5, VERSION)
        ):
            raise ValueError("Unsupported schematic version (expected version 1 through 6)")
        if not isinstance(data.get("title"), str):
            raise ValueError("Schematic title must be text")
        if not isinstance(data.get("nodes"), list) or not isinstance(data.get("connections"), list):
            raise ValueError("Schematic nodes and connections must be lists")
        settings = Schematic().settings
        if not isinstance(data.get("settings", {}), dict):
            raise ValueError("Invalid schematic settings")
        settings.update(data.get("settings", {}))
        for key in ("grid", "spacing", "open_length", "bounds_scale"):
            if not _finite(settings[key]) or settings[key] <= 0:
                raise ValueError(f"{key} must be positive")
        if settings["angle"] not in (45, 90):
            raise ValueError("Angle snap must be 45 or 90 degrees")
        for key in ("snap_grid", "snap_angle", "show_bounds"):
            if not isinstance(settings[key], bool):
                raise ValueError(f"{key} must be true or false")
        document = Schematic(data["title"], settings=settings)
        ids, references = set(), set()
        for value in data["nodes"]:
            node = Node(**deepcopy(value))
            if data["version"] < 5:
                node.mirror_role = "turning"
            if node.mirror_role not in ("turning", "folding") or (
                node.kind != "mirror" and node.mirror_role != "turning"
            ):
                raise ValueError("Only mirrors can have the Folding role")
            if not all(isinstance(x, str) and x for x in (node.id, node.reference, node.kind, node.preset)):
                raise ValueError("Component identifiers must be nonempty text")
            if node.id in ids or node.reference in references:
                raise ValueError("Duplicate component identity or reference")
            ids.add(node.id)
            references.add(node.reference)
            if node.kind not in SYMBOLS or node.preset not in SYMBOLS[node.kind].presets:
                raise ValueError(f"Unknown symbol or preset for {node.reference}")
            if not _point(node.position) or not _finite(node.rotation):
                raise ValueError(f"Invalid drawing position for {node.reference}")
            if not isinstance(node.parameters, dict) or not isinstance(node.physical, dict):
                raise ValueError(f"Invalid component properties for {node.reference}")
            if not all(
                isinstance(key, str) and _finite(v)
                for key, v in list(node.parameters.items()) + list(node.physical.items())
            ):
                raise ValueError(f"Properties must be finite numbers for {node.reference}")
            node.position = tuple(node.position)
            document.nodes.append(node)
        pass_ids = set(ids)
        if data["version"] >= 6:
            explicit_ids = set()
            for value in data.get("passes", []):
                item = OpticalPass(**deepcopy(value))
                if not isinstance(item.id, str) or not item.id or item.id in explicit_ids:
                    raise ValueError("Optical pass identities must be unique nonempty text")
                if item.component_id not in ids or (item.id in ids and item.id != item.component_id):
                    raise ValueError("Optical pass refers to an invalid component")
                if item.mode not in ("pass", "emit", "receive") or any(
                    v is not None and not _finite(v) for v in (item.turn, item.direction)
                ) or type(item.centered) is not bool:
                    raise ValueError("Invalid optical pass properties")
                node = document.node(item.component_id)
                if item.mode == "emit" and SYMBOLS[node.kind].role != "source":
                    raise ValueError("Only a source can emit")
                if item.id != item.component_id and item.mode == "emit":
                    raise ValueError("Additional source passes must receive")
                if item.mode == "receive" and node.kind not in (
                    "source",
                    "output",
                    "stop",
                    "fiber_source",
                    "fiber_output",
                ):
                    raise ValueError("This optical component cannot absorb a receiving pass")
                explicit_ids.add(item.id)
                pass_ids.add(item.id)
                document.passes.append(item)
            stored_layout = deepcopy(data.get("layout"))
            if stored_layout is not None:
                if not isinstance(stored_layout, dict) or not isinstance(stored_layout.get("poses"), dict):
                    raise ValueError("Invalid physical layout")
                for node_id, pose in stored_layout["poses"].items():
                    if (
                        not isinstance(node_id, str)
                        or not isinstance(pose, (tuple, list))
                        or len(pose) != 4
                        or not all(map(_finite, pose))
                    ):
                        raise ValueError("Physical poses must contain finite XYZ and yaw")
                if stored_layout.get("projection", "XY") not in ("XY", "XZ"):
                    raise ValueError("Invalid physical view projection")
                if not isinstance(stored_layout.get("splitters", {}), dict) or any(
                    type(v) is not bool for v in stored_layout.get("splitters", {}).values()
                ):
                    raise ValueError("Invalid splitter configuration")
                document.layout = stored_layout
        edge_ids = set()
        for value in data["connections"]:
            if data["version"] == 1:
                a_node, b_node = document.node(value["source"]), document.node(value["target"])
                edge = Connection(
                    value["id"],
                    Endpoint(a_node.id, legacy_port(a_node.kind, value["source_port"])),
                    Endpoint(b_node.id, legacy_port(b_node.kind, value.get("target_port", "in"))),
                    deepcopy(value.get("bends", [])),
                )
            else:
                edge = Connection(
                    value["id"],
                    Endpoint(**value["a"]),
                    Endpoint(**value["b"]),
                    deepcopy(value.get("bends", [])),
                    value.get("length"),
                    deepcopy(value.get("turns", {})),
                )
            if not all(
                isinstance(x, str) and x
                for x in (edge.id, edge.a.node_id, edge.a.port_id, edge.b.node_id, edge.b.port_id)
            ):
                raise ValueError("Connection identifiers must be nonempty text")
            if edge.id in edge_ids:
                raise ValueError("Duplicate connection identity")
            edge_ids.add(edge.id)
            if edge.a.node_id not in ids or edge.b.node_id not in ids:
                raise ValueError("Connection refers to a missing component")
            for endpoint in (edge.a, edge.b):
                if not isinstance(endpoint.pass_id, str):
                    raise ValueError("Optical pass ID must be text")
                if (
                    endpoint.visit_id not in pass_ids
                    or document.optical_pass(endpoint.visit_id).component_id != endpoint.node_id
                ):
                    raise ValueError("Connection refers to an invalid optical pass")
            if (
                edge.a.port_id not in SYMBOLS[document.node(edge.a.node_id).kind].ports
                or edge.b.port_id not in SYMBOLS[document.node(edge.b.node_id).kind].ports
            ):
                raise ValueError("Connection refers to an invalid port")
            if not isinstance(edge.bends, list) or not all(_point(p) for p in edge.bends):
                raise ValueError("Connection bends must be finite coordinate pairs")
            if edge.length is not None and not _finite(edge.length):
                raise ValueError("Beam length must be a finite number or null")
            if not isinstance(edge.turns, dict) or not all(
                isinstance(key, str) and key in (edge.a.node_id, edge.b.node_id) and _finite(turn)
                for key, turn in edge.turns.items()
            ):
                raise ValueError("Beam turns must map connected component IDs to finite angles")
            edge.allow_folding = value.get("allow_folding", False) if data["version"] >= 5 else False
            if type(edge.allow_folding) is not bool:
                raise ValueError("Allow folding must be true or false")
            edge.bends = [tuple(p) for p in edge.bends]
            document.connections.append(edge)
        values = data.get("path_constraints", []) if data["version"] >= 5 else []
        if not isinstance(values, list):
            raise ValueError("Path constraints must be a list")
        constraint_ids, pairs = set(), set()
        for value in values:
            constraint = PathLengthConstraint(**deepcopy(value))
            if not isinstance(constraint.id, str) or not constraint.id or constraint.id in constraint_ids:
                raise ValueError("Path constraint identities must be unique nonempty text")
            if (
                not isinstance(constraint.component_a, str)
                or not isinstance(constraint.component_b, str)
                or constraint.component_a not in ids
                or constraint.component_b not in ids
                or (
                    (constraint.pass_a or constraint.component_a)
                    == (constraint.pass_b or constraint.component_b)
                )
            ):
                raise ValueError("Path constraint needs two existing, different components")
            for node_id, pass_id in (
                (constraint.component_a, constraint.pass_a),
                (constraint.component_b, constraint.pass_b),
            ):
                if (pass_id or node_id) not in pass_ids or document.optical_pass(
                    pass_id or node_id
                ).component_id != node_id:
                    raise ValueError("Path constraint refers to an invalid optical pass")
            if not _finite(constraint.length_mm) or constraint.length_mm <= 0:
                raise ValueError("Total path length must be a positive finite number")
            pair = tuple(
                sorted(
                    (constraint.pass_a or constraint.component_a, constraint.pass_b or constraint.component_b)
                )
            )
            if pair in pairs:
                raise ValueError("Only one path constraint is allowed per component pair")
            pairs.add(pair)
            constraint_ids.add(constraint.id)
            document.path_constraints.append(constraint)
        if migrate_lengths:
            migrate_legacy_lengths(document)
        if data["version"] >= 4:
            from .optimization import validate_saved_optimization

            document.optimization = deepcopy(data.get("optimization"))
            document.optimized_layout = deepcopy(data.get("optimized_layout"))
            validate_saved_optimization(document.optimization, document.optimized_layout)
            if data["version"] < 5 and document.optimized_layout is not None:
                # Keep the old snapshot for history/save, but require revalidation
                # under the new physical graph and path-constraint semantics.
                for key in ("graph", "input_version", "folding_radius"):
                    document.optimized_layout.pop(key, None)
        return document
    except (TypeError, KeyError, AttributeError, StopIteration) as error:
        raise ValueError(f"Malformed schematic: {error}") from error


def load_schematic(path):
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    document = document_from_dict(data)
    if data["version"] < 6:
        from .scene_layout import initialize_layout

        initialize_layout(document, legacy=True)
    return document


def connection_length(document, edge):
    """Physical length of an undirected beam, independent of drawing geometry."""
    if edge.length is not None:
        return edge.length
    is_open = any(document.node(endpoint.node_id).kind == "output" for endpoint in (edge.a, edge.b))
    return document.settings["open_length" if is_open else "spacing"]


def interface_turn(document, node, topology):
    """Return the optic's constrained turn, or the resolved port default.

    Retain legacy beam angles until the optic is edited, preserving saved
    drawings. Validation rejects conflicts, which the optic inspector can fix.
    """
    turns = [edge.turns[node.id] for edge in document.connections if node.id in edge.turns]
    if turns:
        return min(turns)  # deterministic even for matching values within validation tolerance
    visit = document.optical_pass(node.id)
    return (
        visit.turn
        if visit.turn is not None
        else node.physical.get("turn", default_turn(node.kind, topology.incident_ports.get(node.id)))
    )


def migrate_legacy_lengths(document):
    """Move old node distances to incident beams once direction is unambiguous.

    Unresolved legacy values stay on their node until the source is connected;
    unfinished drawings can therefore be saved without losing constraints.
    """
    if not any("distance" in node.physical for node in document.nodes):
        return
    from .topology import resolve_topology

    topology = resolve_topology(document)
    incoming = {edge.target.node_id: edge.id for edge in topology.edges.values()}
    for node in document.nodes:
        if "distance" not in node.physical:
            continue
        if node.kind == "output":
            # Version 1/2 used open_length for these, ignoring a node distance.
            node.physical.pop("distance")
        elif node.id in incoming:
            edge = document.connection(incoming[node.id])
            if edge.length is None:
                edge.length = node.physical["distance"]
            node.physical.pop("distance")


def save_schematic(document, path):
    # Validate structure, but allow unfinished/disconnected drawings to be saved.
    canonical = document_from_dict(document.to_dict())
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary = stream.name
            json.dump(canonical.to_dict(), stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class History:
    """Document snapshots keep compound edits atomic and restore stable identities."""

    def __init__(self, document):
        self.states = [deepcopy(document.to_dict())]
        self.index = 0
        self.saved = deepcopy(self.states[0])

    @property
    def dirty(self):
        return self.states[self.index] != self.saved

    def commit(self, document):
        state = document.to_dict()
        if state != self.states[self.index]:
            del self.states[self.index + 1 :]
            self.states.append(deepcopy(state))
            self.index += 1

    def undo(self):
        self.index = max(0, self.index - 1)
        return document_from_dict(deepcopy(self.states[self.index]))

    def redo(self):
        self.index = min(len(self.states) - 1, self.index + 1)
        return document_from_dict(deepcopy(self.states[self.index]))

    def mark_saved(self):
        self.saved = deepcopy(self.states[self.index])
