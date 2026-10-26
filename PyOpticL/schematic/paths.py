"""Direction-independent component routes and total geometric path lengths."""

from collections import deque


def component_path(document, component_a, component_b):
    """Return edge IDs on the unique undirected route, in endpoint order."""
    if component_a == component_b:
        raise ValueError("A path length needs two different components")
    adjacency = {node.id: [] for node in document.nodes}
    if component_a not in adjacency or component_b not in adjacency:
        raise ValueError("Path length refers to a missing component")
    for edge in document.connections:
        adjacency[edge.a.node_id].append((edge.b.node_id, edge.id))
        adjacency[edge.b.node_id].append((edge.a.node_id, edge.id))
    parents = {component_a: (None, None)}
    queue = deque([component_a])
    cyclic = False
    while queue:
        current = queue.popleft()
        parent, parent_edge = parents[current]
        for target, edge_id in sorted(adjacency[current]):
            if edge_id == parent_edge:
                continue
            if target in parents:
                cyclic = True
            else:
                parents[target] = (current, edge_id)
                queue.append(target)
    if cyclic:
        raise ValueError("Path length requires an unambiguous acyclic route")
    if component_b not in parents:
        a, b = document.node(component_a).reference, document.node(component_b).reference
        raise ValueError(f"No connected path between {a} and {b}")
    path, current = [], component_b
    while current != component_a:
        current, edge_id = parents[current]
        path.append(edge_id)
    return tuple(reversed(path))


def path_length(document, component_a, component_b, lengths):
    return sum(lengths[edge_id] for edge_id in component_path(document, component_a, component_b))
