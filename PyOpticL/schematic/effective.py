"""Reversible, permission-checked edits to the physical realization of a schematic.

The schematic remains the source of truth. Persisted edit records are replayed,
never trusted as an arbitrary replacement optical graph. Segment shares preserve
aggregate spring preferences through any sequence of splits and merges.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass
from uuid import NAMESPACE_URL, uuid5

from .model import Connection, Endpoint, Node, Schematic, interface_turn
from .topology import resolve_topology


@dataclass(frozen=True)
class GraphEdit:
    action: str
    node_id: str
    segment_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeneratedMirror:
    id: str
    logical_ids: tuple[str, ...]


@dataclass(frozen=True)
class PhysicalSegment:
    id: str
    a: Endpoint
    b: Endpoint
    shares: tuple[tuple[str, float], ...]

    @property
    def logical_ids(self):
        return tuple(key for key, _ in self.shares)


@dataclass(frozen=True)
class EffectiveGraph:
    segments: tuple[PhysicalSegment, ...]
    generated: tuple[GeneratedMirror, ...] = ()
    bypassed: tuple[str, ...] = ()
    edits: tuple[GraphEdit, ...] = ()

    def to_dict(self):
        return {"edits": [asdict(edit) for edit in self.edits]}

    def segment(self, segment_id):
        return next(segment for segment in self.segments if segment.id == segment_id)


def identity_graph(document):
    return EffectiveGraph(
        tuple(
            PhysicalSegment(e.id, *sorted((e.a, e.b)), ((e.id, 1.0),))
            for e in sorted(document.connections, key=lambda item: item.id)
        )
    )


def parse_graph_edits(data):
    if not isinstance(data, dict) or set(data) != {"edits"} or not isinstance(data["edits"], list):
        raise ValueError("Invalid effective physical graph")
    edits = []
    for value in data["edits"]:
        if not isinstance(value, dict) or set(value) != {"action", "node_id", "segment_ids"}:
            raise ValueError("Invalid physical graph edit")
        action, node_id, segments = value["action"], value["node_id"], value["segment_ids"]
        if (
            action not in ("insert", "remove")
            or not isinstance(node_id, str)
            or not node_id
            or not isinstance(segments, (list, tuple))
            or len(segments) != (1 if action == "insert" else 2)
            or not all(isinstance(item, str) and item for item in segments)
            or len(set(segments)) != len(segments)
        ):
            raise ValueError("Invalid physical graph edit")
        edits.append(GraphEdit(action, node_id, tuple(segments)))
    return tuple(edits)


def folding_protection(document, node_id):
    node = document.node(node_id)
    if node.kind != "mirror" or node.mirror_role != "folding":
        return "Turning mirrors are retained"
    if any(key in node.physical for key in ("x", "y")):
        return "Position-constrained mirrors are retained"
    if "turn" in node.physical or any(node_id in edge.turns for edge in document.connections):
        return "Angle-constrained mirrors are retained"
    if any(
        edge.length is not None and node_id in (edge.a.node_id, edge.b.node_id)
        for edge in document.connections
    ):
        return "Mirrors at constrained beam endpoints are retained"
    if any(node_id in (item.component_a, item.component_b) for item in document.path_constraints):
        return "Path-constraint endpoints are retained"
    return None


def can_insert(document, graph, segment, options):
    if not all(document.connection(key).allow_folding for key in segment.logical_ids):
        return False
    if len(graph.generated) >= options.max_added_mirrors:
        return False
    return all(
        sum(key in mirror.logical_ids for mirror in graph.generated) < options.max_folds_per_beam
        for key in segment.logical_ids
    )


def insert_mirror(document, graph, segment_id, options, node_id=None):
    segment = graph.segment(segment_id)
    if not can_insert(document, graph, segment, options):
        raise ValueError("Folding is not permitted on this span or its mirror limit has been reached")
    if node_id is None:
        node_id = str(uuid5(NAMESPACE_URL, f"PyOpticL/fold/{segment_id}/{len(graph.edits)}"))
    if node_id in {node.id for node in document.nodes} | {mirror.id for mirror in graph.generated}:
        raise ValueError("Generated mirror identity collides with an existing component")
    derived = effective_document(document, graph, options)
    edge = resolve_topology(derived).edges[segment_id]
    shares = tuple((key, weight / 2) for key, weight in segment.shares)
    segments = tuple(item for item in graph.segments if item.id != segment_id) + (
        PhysicalSegment(node_id + "/in", edge.source, Endpoint(node_id, "A"), shares),
        PhysicalSegment(node_id + "/out", Endpoint(node_id, "B"), edge.target, shares),
    )
    return EffectiveGraph(
        segments,
        graph.generated + (GeneratedMirror(node_id, segment.logical_ids),),
        graph.bypassed,
        graph.edits + (GraphEdit("insert", node_id, (segment_id,)),),
    )


def remove_mirror(document, graph, node_id, options, segment_ids=None):
    generated = any(item.id == node_id for item in graph.generated)
    if not generated:
        reason = folding_protection(document, node_id)
        if reason:
            raise ValueError(reason)
        if node_id in graph.bypassed:
            raise ValueError("Mirror was already bypassed")
    derived = effective_document(document, graph, options)
    topology = resolve_topology(derived)
    incoming = [edge for edge in topology.edges.values() if edge.target.node_id == node_id]
    outgoing = topology.outgoing.get(node_id, [])
    if len(incoming) != 1 or len(outgoing) != 1:
        raise ValueError("Only degree-two folding mirrors can be bypassed")
    first, second = incoming[0], outgoing[0]
    actual_ids = (first.id, second.id)
    if segment_ids is not None and tuple(segment_ids) != actual_ids:
        raise ValueError("Bypass edit does not match the optical route")
    shares = {}
    for segment_id in actual_ids:
        for key, weight in graph.segment(segment_id).shares:
            shares[key] = shares.get(key, 0) + weight
    edge_id = str(uuid5(NAMESPACE_URL, "PyOpticL/bypass/" + node_id + "/" + "/".join(actual_ids)))
    segments = tuple(item for item in graph.segments if item.id not in actual_ids) + (
        PhysicalSegment(edge_id, first.source, second.target, tuple(sorted(shares.items()))),
    )
    mirrors = tuple(item for item in graph.generated if item.id != node_id)
    bypassed = graph.bypassed if generated else tuple(sorted((*graph.bypassed, node_id)))
    return EffectiveGraph(
        segments, mirrors, bypassed, graph.edits + (GraphEdit("remove", node_id, actual_ids),)
    )


def replay_graph(document, data, options):
    graph = identity_graph(document)
    try:
        for edit in parse_graph_edits(data):
            if edit.action == "insert":
                graph = insert_mirror(document, graph, edit.segment_ids[0], options, edit.node_id)
            else:
                graph = remove_mirror(document, graph, edit.node_id, options, edit.segment_ids)
    except (KeyError, StopIteration) as error:
        raise ValueError("Physical graph edit refers to an unavailable part or span") from error
    return graph


def effective_document(document, graph, options):
    """Build a private ordinary schematic for the common geometry/export code."""
    result = Schematic(document.title, settings=deepcopy(document.settings))
    result.nodes = [deepcopy(node) for node in document.nodes if node.id not in graph.bypassed]
    result.path_constraints = deepcopy(document.path_constraints)
    if any(edge.turns for edge in document.connections):
        topology = resolve_topology(document)
        for node in result.nodes:
            if any(node.id in edge.turns for edge in document.connections):
                node.physical["turn"] = interface_turn(document, node, topology)
    used = {node.reference for node in document.nodes}
    for mirror in sorted(graph.generated, key=lambda item: item.id):
        index = 1
        while f"FM{index}" in used:
            index += 1
        reference = f"FM{index}"
        used.add(reference)
        result.nodes.append(
            Node(
                mirror.id,
                reference,
                "mirror",
                options.folding_preset,
                parameters={"diameter": options.folding_diameter_mm},
                mirror_role="folding",
            )
        )
    originals = {edge.id: edge for edge in document.connections}
    for segment in graph.segments:
        original = originals.get(segment.id)
        length = original.length if original is not None else None
        result.connections.append(
            Connection(
                segment.id,
                segment.a,
                segment.b,
                length=length,
                allow_folding=all(originals[key].allow_folding for key in segment.logical_ids),
            )
        )
    return result
