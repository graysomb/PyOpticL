"""Direction-independent component routes and total geometric path lengths."""

from collections import deque


def component_path(document, component_a, component_b):
    """Return edge IDs on the unique undirected route, in endpoint order."""
    if component_a == component_b:
        raise ValueError("A path length needs two different components")
    adjacency = {p.id: [] for p in document.optical_passes()}
    if component_a not in adjacency or component_b not in adjacency:
        raise ValueError("Path length refers to a missing component")
    for edge in document.connections:
        adjacency[edge.a.visit_id].append((edge.b.visit_id, edge.id))
        adjacency[edge.b.visit_id].append((edge.a.visit_id, edge.id))
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
        a, b = (
            document.node(document.optical_pass(component_a).component_id).reference,
            document.node(document.optical_pass(component_b).component_id).reference,
        )
        raise ValueError(f"No connected path between {a} and {b}")
    path, current = [], component_b
    while current != component_a:
        current, edge_id = parents[current]
        path.append(edge_id)
    return tuple(reversed(path))


def path_length(document, component_a, component_b, lengths):
    from .kinematics import internal_path
    from .scene_layout import is_physical, trace_scene

    if is_physical(document):
        if document.optimized_layout is not None and document.optimized_layout.get("input_version") == 6:
            from .scene_optimization import saved_scene_document

            document = saved_scene_document(document)[0]
        from .topology import resolve_topology

        topology = resolve_topology(document)
        geometry = trace_scene(document, check_interceptions=False, topology=topology).layout
        route = component_path(document, component_a, component_b)
        routed = set(route)
        return sum(lengths[key] for key in route) + sum(
            geometry.internal_lengths.get(v, 0)
            for v in topology.order
            if any(e.id in routed for e in topology.outgoing[v])
        )
    route = component_path(document, component_a, component_b)
    return sum(lengths[edge_id] for edge_id in route) + internal_path(document, route)
