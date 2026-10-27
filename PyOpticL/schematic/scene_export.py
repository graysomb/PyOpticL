"""Export shared physical parts once, with an ordered finite-pass trace contract."""

from pprint import pformat
from .registry import parameter_values, SYMBOLS, COUPLING_MOUNTS, default_turn
from .parts import part_spec
from .topology import Diagnostic, resolve_topology
from .scene_layout import trace_scene, source_offset, splitter_flip
from .scene_solver import analyze_constraints
from .paths import component_path


def compile_scene(document, diagnostics=()):
    from .compiler import Compilation

    original_document = document
    graph = None
    if document.optimized_layout is not None:
        from .optimization import optimized_physical_layout

        try:
            optimized_physical_layout(document)
            if document.optimized_layout.get("input_version") != 6:
                raise ValueError(
                    "Optimized layout is stale after the physical scene upgrade. Rerun or clear it."
                )
            from .scene_optimization import saved_scene_document

            document, graph = saved_scene_document(document)
        except ValueError as error:
            return Compilation("", [Diagnostic(str(error))])
    topology = resolve_topology(document)
    trace = trace_scene(document)
    report = analyze_constraints(document)
    errors = list(diagnostics) + list(trace.diagnostics) + list(report.diagnostics)
    if any(d.severity == "error" for d in errors):
        return Compilation("", errors, geometry=trace.layout, lengths=trace.layout.lengths)
    from dataclasses import replace

    geometry = replace(trace.layout, graph=graph)
    source = document.node(topology.passes[topology.source_id].component_id)
    expected = {}
    paths = {}
    for visit_id in topology.order:
        p = topology.passes[visit_id]
        node = document.node(p.component_id)
        state = geometry.visits[visit_id]
        branches = {}
        for edge in topology.outgoing[visit_id]:
            branches[edge.interaction] = {
                "pass": edge.target.visit_id,
                "connection": edge.id,
                "length": geometry.lengths[edge.id],
                "direction": state.outputs[edge.interaction],
            }
        expected[visit_id] = {
            "component": None if node.kind in ("source", "output") else node.reference,
            "reference": node.reference,
            "mode": p.mode,
            "entry": state.entry,
            "exit": state.exit,
            "internal_length": state.internal_length,
            "branches": branches,
        }
    for constraint in document.path_constraints:
        route = component_path(
            document, constraint.pass_a or constraint.component_a, constraint.pass_b or constraint.component_b
        )
        routed = set(route)
        paths[constraint.id] = sum(geometry.lengths[e] for e in route) + sum(
            geometry.internal_lengths.get(v, 0)
            for v in topology.order
            if any(e.id in routed for e in topology.outgoing[v])
        )
    open_segments = []
    for edge in topology.edges.values():
        if document.node(edge.target.node_id).kind == "output":
            state = geometry.visits[edge.source.visit_id]
            open_segments.append((state.exit, state.outputs[edge.interaction], geometry.lengths[edge.id]))
    turns = {}
    for n in document.nodes:
        if n.kind == "splitter":
            canonical = default_turn(n.kind, topology.incident_ports.get(n.id))
            turns[n.id] = -canonical if splitter_flip(document, n) else canonical
        elif n.kind == "mirror":
            turns[n.id] = geometry.turns.get(n.id, 90.0)
    physical = [n for n in document.nodes if n.kind not in ("source", "output")]
    specs = {n.id: part_spec(document, n, topology, turns) for n in physical}
    # A source assembly may also receive the returning beam.
    for n in physical:
        if (
            n.kind == "fiber_source"
            and n.preset in COUPLING_MOUNTS
            and any(p.component_id == n.id and p.mode == "receive" for p in topology.passes.values())
        ):
            from dataclasses import replace

            spec = specs[n.id]
            specs[n.id] = replace(
                spec, before=tuple((k, True if k == "receiving" else v) for k, v in spec.before)
            )
    lines = [
        '"""Generated physical PyOpticL schematic; component and pass IDs are stable."""',
        "from PyOpticL.layout import Layout, Component",
        "from PyOpticL.beam_path import BeamPath, linear_polarization",
        "from PyOpticL.library import optics, thorlabs",
        "from PyOpticL.schematic.runtime import check_pass_trace",
    ]
    if any("catalog" in spec.modules for spec in specs.values()):
        lines.append("from PyOpticL.schematic import catalog_parts as catalog")
    placements = {n.reference: geometry.poses[n.id] for n in physical}
    source_settings = {
        **parameter_values(source),
        "position": geometry.poses[source.id][:3],
        "angle": geometry.source_direction,
    }
    lines += [
        "",
        f"PLACEMENTS = {pformat(placements,sort_dicts=True)}",
        "",
        f"SOURCE = {pformat(source_settings)}",
        "",
        f"EXPECTED_PASSES = {pformat(expected,sort_dicts=True)}",
        "",
        f"PATH_LENGTHS = {pformat(paths)}",
        f"OPEN_SEGMENTS = {pformat(open_segments)}",
        "",
        "def build_layout():",
        f"    layout = Layout({document.title!r})",
        "    objects = {}",
    ]
    for i, node in enumerate(physical):
        lines += [
            f"    part_{i} = Component({node.reference!r}, {specs[node.id].render()})",
            f"    x, y, z, angle = PLACEMENTS[{node.reference!r}]",
            f"    objects[{node.reference!r}] = layout.add(part_{i}, position=(x, y, z), rotation=angle)",
        ]
    budget = (
        sum(
            4 if document.node(p.component_id).kind == "roof" else 1
            for p in topology.passes.values()
            if p.mode != "emit"
        )
        + 2
    )
    lines += [
        f'    beam = layout.add(BeamPath({source.reference!r}, wavelength=SOURCE["wavelength"],',
        '        polarization=linear_polarization(SOURCE["polarization_angle"]),',
        '        power=SOURCE["power"], waist=SOURCE["waist"],',
        f'        final_distance={document.settings["open_length"]!r}, trace_limit={budget}, trace_ends=OPEN_SEGMENTS),',
        '        position=SOURCE["position"], rotation=SOURCE["angle"])',
        "    layout.recompute()",
        f"    check_pass_trace(beam, objects, EXPECTED_PASSES, {topology.source_id!r})",
        "    return layout",
        "",
        "",
        'if __name__ == "__main__":',
        "    build_layout()",
        "",
    ]
    from PyOpticL.ray_math import norm, sub

    logical_lengths = {}
    routed_lengths = {}
    original_topology = resolve_topology(original_document)
    for edge in original_document.connections:
        resolved = original_topology.edges.get(edge.id)
        if not resolved:
            continue
        first, last = resolved.source.visit_id, resolved.target.visit_id
        if first not in geometry.visits or last not in geometry.visits:
            continue
        logical_lengths[edge.id] = norm(sub(geometry.visits[last].entry, geometry.visits[first].exit))
        routed_lengths[edge.id] = sum(geometry.lengths[key] for key in component_path(document, first, last))
    return Compilation(
        "\n".join(lines),
        errors,
        {n.id: n.reference for n in document.nodes},
        {n.reference: (*geometry.positions[n.id], geometry.orientations[n.id]) for n in document.nodes},
        logical_lengths,
        geometry,
        paths,
        routed_lengths,
    )
