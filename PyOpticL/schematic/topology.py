"""Resolve finite beam visits while retaining shared physical component IDs."""

from collections import Counter, deque
from dataclasses import dataclass, field
from .model import document_from_dict
from .registry import SYMBOLS, branch_ports


@dataclass(frozen=True)
class Diagnostic:
    message: str
    node_id: str | None = None
    connection_id: str | None = None
    severity: str = "error"
    constraint_id: str | None = None
    pass_id: str | None = None


@dataclass(frozen=True)
class ResolvedConnection:
    id: str
    source: object
    target: object
    interaction: str


@dataclass
class ResolvedTopology:
    source_id: str | None = None
    edges: dict = field(default_factory=dict)
    incident_ports: dict = field(default_factory=dict)
    outgoing: dict = field(default_factory=dict)
    order: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    passes: dict = field(default_factory=dict)

    @property
    def ok(self):
        return not any(d.severity == "error" for d in self.diagnostics)


def resolve_topology(document):
    result = ResolvedTopology()
    try:
        document_from_dict(document.to_dict(), migrate_lengths=False)
    except ValueError as error:
        result.diagnostics.append(Diagnostic(str(error)))
        return result
    visits = result.passes = {p.id: p for p in document.optical_passes()}
    nodes = {p.id: document.node(p.component_id) for p in visits.values()}
    adjacency = {key: [] for key in visits}
    occupied, parents = Counter(), {key: key for key in visits}
    ambiguous = False

    def diagnostic(message, visit=None, edge=None):
        result.diagnostics.append(
            Diagnostic(message, nodes[visit].id if visit else None, edge, pass_id=visit)
        )

    def root(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    for edge in document.connections:
        a, b = edge.a, edge.b
        adjacency[a.visit_id].append((edge, a, b))
        adjacency[b.visit_id].append((edge, b, a))
        for endpoint in (a, b):
            key = (endpoint.visit_id, endpoint.port_id)
            occupied[key] += 1
            if occupied[key] > 1:
                diagnostic(
                    f"{nodes[endpoint.visit_id].reference}.{endpoint.port_id}: port already connected",
                    endpoint.visit_id,
                    edge.id,
                )
                ambiguous = True
        ra, rb = root(a.visit_id), root(b.visit_id)
        if ra == rb:
            diagnostic(
                "Cycle in optical passes is unsupported; add a distinct pass for each finite visit",
                a.visit_id,
                edge.id,
            )
            ambiguous = True
        else:
            parents[ra] = rb
    sources = [p.id for p in visits.values() if p.mode == "emit"]
    if len(sources) != 1:
        diagnostic("Exactly one beam source or fiber source is required to infer direction")
        ambiguous = True
    else:
        result.source_id = sources[0]
    for visit, p in visits.items():
        required = 1 if p.mode in ("emit", "receive") else (3 if nodes[visit].kind == "splitter" else 2)
        if len(adjacency[visit]) != required:
            diagnostic(
                f"{nodes[visit].reference}: expected {required} connected ports, found {len(adjacency[visit])}. End each branch with a receiver, stop, or open output.",
                visit,
            )
    if result.source_id is None:
        return result
    reachable, stack = set(), [result.source_id]
    while stack:
        current = stack.pop()
        if current not in reachable:
            reachable.add(current)
            stack.extend(other.visit_id for _, _, other in adjacency[current])
    for visit in visits:
        if visit not in reachable:
            diagnostic(f"{nodes[visit].reference}: disconnected from source", visit)
    if ambiguous:
        return result
    queue = deque([(result.source_id, None)])
    invalid = False
    while queue:
        visit, parent_edge = queue.popleft()
        node, p = nodes[visit], visits[visit]
        result.order.append(visit)
        incident = result.incident_ports.get(visit)
        branches = (
            {"beam": "out"}
            if p.mode == "emit"
            else {} if p.mode == "receive" else branch_ports(node.kind, incident)
        )
        exits = [item for item in adjacency[visit] if item[0].id != parent_edge]
        exits.sort(
            key=lambda item: (
                {"out": 0, "transmitted": 0, "reflected": 1}.get(branches.get(item[1].port_id), 2),
                item[1].port_id,
                item[2].visit_id,
            )
        )
        result.outgoing[visit] = []
        used = {local.port_id for _, local, _ in exits}
        for port, role in branches.items():
            if port not in used:
                diagnostic(
                    f"{node.reference}.{port}: missing {role} branch; connect a part or explicit terminal",
                    visit,
                )
        for edge, local, other in exits:
            role = branches.get(local.port_id)
            if role is None:
                diagnostic(
                    f"{node.reference}.{local.port_id}: this port cannot transmit for the resolved incident beam",
                    visit,
                    edge.id,
                )
                invalid = True
            else:
                resolved = ResolvedConnection(edge.id, local, other, role)
                result.edges[edge.id] = resolved
                result.outgoing[visit].append(resolved)
            result.incident_ports[other.visit_id] = other.port_id
            queue.append((other.visit_id, edge.id))
    if invalid:
        result.edges.clear()
        result.outgoing.clear()
    return result
