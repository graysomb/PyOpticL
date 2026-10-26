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

VERSION = 3


def new_id():
    return str(uuid4())


@dataclass
class Node:
    id: str
    reference: str
    kind: str
    preset: str
    parameters: dict = field(default_factory=dict)
    position: tuple[float, float] = (0, 0)
    rotation: float = 0
    physical: dict = field(default_factory=dict)


@dataclass(frozen=True, order=True)
class Endpoint:
    node_id: str
    port_id: str


@dataclass
class Connection:
    """An undirected connection; bends run from a to b in storage order."""

    id: str
    a: Endpoint
    b: Endpoint
    bends: list = field(default_factory=list)
    length: float | None = None  # physical separation in mm; None uses the document default
    turns: dict[str, float] = field(default_factory=dict)  # legacy beam angles; new edits use Node.physical["turn"]


@dataclass
class Schematic:
    title: str = "Optical schematic"
    nodes: list[Node] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)
    settings: dict = field(default_factory=lambda: {
        "grid": 20, "angle": 45, "snap_grid": True, "snap_angle": True,
        "spacing": 50, "open_length": 50,
    })
    version: int = VERSION

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
        node = Node(new_id(), f"{symbol.prefix}{number}", kind, symbol.presets[0],
                    position=tuple(position))
        self.nodes.append(node)
        return node

    def remove_nodes(self, ids):
        ids = set(ids)
        self.nodes[:] = [node for node in self.nodes if node.id not in ids]
        self.connections[:] = [edge for edge in self.connections
                               if edge.a.node_id not in ids and edge.b.node_id not in ids]

    def duplicate_nodes(self, ids):
        copies = []
        for original in list(self.nodes):
            if original.id in ids:
                node = self.add_node(original.kind,
                                     (original.position[0] + 40, original.position[1] + 40))
                node.preset = original.preset
                node.parameters = deepcopy(original.parameters)
                node.physical = deepcopy(original.physical)
                node.rotation = original.rotation
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
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] not in (1, 2, VERSION):
            raise ValueError("Unsupported schematic version (expected version 1, 2, or 3)")
        if not isinstance(data.get("title"), str):
            raise ValueError("Schematic title must be text")
        if not isinstance(data.get("nodes"), list) or not isinstance(data.get("connections"), list):
            raise ValueError("Schematic nodes and connections must be lists")
        settings = Schematic().settings
        if not isinstance(data.get("settings", {}), dict):
            raise ValueError("Invalid schematic settings")
        settings.update(data.get("settings", {}))
        for key in ("grid", "spacing", "open_length"):
            if not _finite(settings[key]) or settings[key] <= 0:
                raise ValueError(f"{key} must be positive")
        if settings["angle"] not in (45, 90):
            raise ValueError("Angle snap must be 45 or 90 degrees")
        for key in ("snap_grid", "snap_angle"):
            if not isinstance(settings[key], bool):
                raise ValueError(f"{key} must be true or false")
        document = Schematic(data["title"], settings=settings)
        ids, references = set(), set()
        for value in data["nodes"]:
            node = Node(**deepcopy(value))
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
            if not all(isinstance(key, str) and _finite(v) for key, v in
                       list(node.parameters.items()) + list(node.physical.items())):
                raise ValueError(f"Properties must be finite numbers for {node.reference}")
            node.position = tuple(node.position)
            document.nodes.append(node)
        edge_ids = set()
        for value in data["connections"]:
            if data["version"] == 1:
                a_node, b_node = document.node(value["source"]), document.node(value["target"])
                edge = Connection(value["id"], Endpoint(a_node.id, legacy_port(a_node.kind, value["source_port"])),
                                  Endpoint(b_node.id, legacy_port(b_node.kind, value.get("target_port", "in"))),
                                  deepcopy(value.get("bends", [])))
            else:
                edge = Connection(value["id"], Endpoint(**value["a"]), Endpoint(**value["b"]),
                                  deepcopy(value.get("bends", [])), value.get("length"),
                                  deepcopy(value.get("turns", {})))
            if not all(isinstance(x, str) and x for x in (edge.id, edge.a.node_id, edge.a.port_id,
                                                         edge.b.node_id, edge.b.port_id)):
                raise ValueError("Connection identifiers must be nonempty text")
            if edge.id in edge_ids:
                raise ValueError("Duplicate connection identity")
            edge_ids.add(edge.id)
            if edge.a.node_id not in ids or edge.b.node_id not in ids:
                raise ValueError("Connection refers to a missing component")
            if (edge.a.port_id not in SYMBOLS[document.node(edge.a.node_id).kind].ports or
                    edge.b.port_id not in SYMBOLS[document.node(edge.b.node_id).kind].ports):
                raise ValueError("Connection refers to an invalid port")
            if not isinstance(edge.bends, list) or not all(_point(p) for p in edge.bends):
                raise ValueError("Connection bends must be finite coordinate pairs")
            if edge.length is not None and not _finite(edge.length):
                raise ValueError("Beam length must be a finite number or null")
            if not isinstance(edge.turns, dict) or not all(
                    isinstance(key, str) and key in (edge.a.node_id, edge.b.node_id) and _finite(turn)
                    for key, turn in edge.turns.items()):
                raise ValueError("Beam turns must map connected component IDs to finite angles")
            edge.bends = [tuple(p) for p in edge.bends]
            document.connections.append(edge)
        if migrate_lengths:
            migrate_legacy_lengths(document)
        return document
    except (TypeError, KeyError, AttributeError, StopIteration) as error:
        raise ValueError(f"Malformed schematic: {error}") from error


def load_schematic(path):
    with open(path, encoding="utf-8") as stream:
        return document_from_dict(json.load(stream))


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
    return node.physical.get("turn", default_turn(node.kind, topology.incident_ports.get(node.id)))


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
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as stream:
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
            del self.states[self.index + 1:]
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
