"""Resolve beam propagation from a source through direction-neutral connections."""

from collections import Counter, deque
from dataclasses import dataclass, field

from .model import Endpoint, document_from_dict
from .registry import SYMBOLS, branch_ports


@dataclass(frozen=True)
class Diagnostic:
    message: str
    node_id: str | None = None
    connection_id: str | None = None
    severity: str = "error"


@dataclass(frozen=True)
class ResolvedConnection:
    id: str
    source: Endpoint
    target: Endpoint
    interaction: str


@dataclass
class ResolvedTopology:
    source_id: str | None = None
    edges: dict[str, ResolvedConnection] = field(default_factory=dict)
    incident_ports: dict[str, str] = field(default_factory=dict)
    outgoing: dict[str, list[ResolvedConnection]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self):
        return not self.diagnostics


def resolve_topology(document):
    """Infer directions without mutating endpoints, bends, or physical settings.

    Incomplete trees still have useful directions. Ambiguous graphs and invalid
    optical paths have no arrows; their diagnostics block compilation.
    """
    result = ResolvedTopology()
    diagnostics = result.diagnostics
    try:
        document_from_dict(document.to_dict(), migrate_lengths=False)
    except ValueError as error:
        diagnostics.append(Diagnostic(str(error)))
        return result
    nodes = {node.id: node for node in document.nodes}
    adjacency = {key: [] for key in nodes}
    occupied = Counter()
    parents = {key: key for key in nodes}
    ambiguous = False

    def root(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    for edge in document.connections:
        a, b = edge.a, edge.b
        adjacency[a.node_id].append((edge, a, b))
        adjacency[b.node_id].append((edge, b, a))
        for endpoint in (a, b):
            occupied[endpoint] += 1
            if occupied[endpoint] > 1:
                diagnostics.append(Diagnostic(f"{nodes[endpoint.node_id].reference}.{endpoint.port_id}: port already connected",
                                              endpoint.node_id, edge.id))
                ambiguous = True
        a_root, b_root = root(a.node_id), root(b.node_id)
        if a_root == b_root:
            diagnostics.append(Diagnostic("Cycle or repeated-pass topology is unsupported", a.node_id, edge.id))
            ambiguous = True
        else:
            parents[a_root] = b_root

    sources = [node for node in document.nodes if SYMBOLS[node.kind].role == "source"]
    if len(sources) != 1:
        diagnostics.append(Diagnostic("Exactly one beam source or fiber source is required to infer direction"))
        ambiguous = True
    else:
        result.source_id = sources[0].id

    for node in document.nodes:
        role = SYMBOLS[node.kind].role
        required = 3 if node.kind == "splitter" else (2 if role == "passive" else 1)
        count = len(adjacency[node.id])
        if count != required:
            diagnostics.append(Diagnostic(f"{node.reference}: expected {required} connected ports, found {count}. "
                                          "End each branch with a receiver, stop, or open output.", node.id))

    if result.source_id is None:
        return result
    reachable, stack = set(), [result.source_id]
    while stack:
        current = stack.pop()
        if current not in reachable:
            reachable.add(current)
            stack.extend(target.node_id for _, _, target in adjacency[current])
    for node in document.nodes:
        if node.id not in reachable:
            diagnostics.append(Diagnostic(f"{node.reference}: disconnected from source", node.id))
    if ambiguous:
        return result

    queue = deque([(result.source_id, None)])
    invalid_path = False
    while queue:
        current, parent_edge = queue.popleft()
        node = nodes[current]
        result.order.append(current)
        incident = result.incident_ports.get(current)
        branches = branch_ports(node.kind, incident)
        exits = [(edge, local, other) for edge, local, other in adjacency[current] if edge.id != parent_edge]
        exits.sort(key=lambda item: (
            {"out": 0, "transmitted": 0, "reflected": 1}.get(branches.get(item[1].port_id), 2),
            item[1].port_id, nodes[item[2].node_id].reference))
        result.outgoing[current] = []
        used_ports = {local.port_id for _, local, _ in exits}
        for port, interaction in branches.items():
            if port not in used_ports:
                diagnostics.append(Diagnostic(f"{node.reference}.{port}: missing {interaction} branch; connect a part or explicit terminal", current))
        for edge, local, other in exits:
            interaction = branches.get(local.port_id)
            if interaction is None:
                diagnostics.append(Diagnostic(f"{node.reference}.{local.port_id}: this port cannot transmit for the resolved incident beam",
                                              current, edge.id))
                invalid_path = True
            else:
                resolved = ResolvedConnection(edge.id, local, other, interaction)
                result.edges[edge.id] = resolved
                result.outgoing[current].append(resolved)
            result.incident_ports[other.node_id] = other.port_id
            queue.append((other.node_id, edge.id))
    if invalid_path:
        result.edges.clear()
        result.outgoing.clear()
    return result
