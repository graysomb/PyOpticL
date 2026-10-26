"""Compile source-resolved optical topology into ordinary PyOpticL Python."""

from dataclasses import dataclass, field
from math import hypot
from pprint import pformat

from .constraints import POSITION_TOLERANCE, resolve_position_lengths
from .model import connection_length, document_from_dict, _finite
from .parts import part_spec
from .physical import PhysicalLayout, physical_layout
from .paths import component_path, path_length
from .registry import MIN_BEAM_TURN, SYMBOLS, parameter_values, supports_beam_turn
from .topology import Diagnostic, resolve_topology


@dataclass
class Compilation:
    source: str
    diagnostics: list[Diagnostic]
    object_map: dict[str, str] = field(default_factory=dict)
    placements: dict = field(default_factory=dict)
    lengths: dict[str, float] = field(default_factory=dict)
    geometry: PhysicalLayout | None = None
    path_lengths: dict[str, float] = field(default_factory=dict)
    routed_lengths: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self):
        return not any(item.severity == "error" for item in self.diagnostics)


def validate_schematic(document):
    diagnostics = []
    try:
        document = document_from_dict(document.to_dict())
    except ValueError as error:
        return [Diagnostic(str(error))]
    topology = resolve_topology(document)
    diagnostics.extend(topology.diagnostics)
    for constraint in document.path_constraints:
        try:
            component_path(document, constraint.component_a, constraint.component_b)
        except ValueError as error:
            diagnostics.append(Diagnostic(str(error), constraint.component_a, constraint_id=constraint.id))
    constrained_nodes = {node_id for edge in document.connections for node_id in edge.turns}
    for node in document.nodes:
        symbol = SYMBOLS[node.kind]
        for name in node.parameters:
            if name not in symbol.parameters:
                diagnostics.append(Diagnostic(f"{node.reference}: unsupported parameter {name}", node.id))
        for name, spec in symbol.parameters.items():
            value = parameter_values(node)[name]
            lower_bad = spec.minimum is not None and (value <= spec.minimum if spec.exclusive else value < spec.minimum)
            upper_bad = spec.maximum is not None and (value >= spec.maximum if spec.exclusive else value > spec.maximum)
            if not _finite(value) or lower_bad or upper_bad or (name == "focal_length" and value == 0):
                diagnostics.append(Diagnostic(f"{node.reference}: invalid {spec.label}", node.id))
        if node.preset == "mounted" and parameter_values(node).get("diameter") != 12.7:
            diagnostics.append(Diagnostic(f"{node.reference}: the mounted preset requires a 12.7 mm optic; choose bare for another diameter", node.id))
        allowed = {"x", "y", "angle"} if symbol.role == "source" else {"x", "y"}
        if node.kind in ("mirror", "splitter"):
            allowed.add("turn")
        for name, value in node.physical.items():
            if name == "distance":
                diagnostics.append(Diagnostic(f"{node.reference}: legacy distance awaits an unambiguous incoming beam; connect the source to migrate it", node.id))
            elif name not in allowed or not _finite(value):
                diagnostics.append(Diagnostic(f"{node.reference}: invalid physical setting {name}", node.id))
        turn = node.physical.get("turn")
        if (node.kind in ("mirror", "splitter") and node.id not in constrained_nodes and
                turn is not None and not MIN_BEAM_TURN <= abs(turn) < 180):
            diagnostics.append(Diagnostic(f"{node.reference}: absolute turn must be at least {MIN_BEAM_TURN:g}° and less than 180°; straight/grazing and retracing paths are unsupported", node.id))

    constrained_turns = {}
    for edge in document.connections:
        if edge.length is not None and (not _finite(edge.length) or edge.length <= 0):
            diagnostics.append(Diagnostic("Beam length must be a positive finite number in mm", connection_id=edge.id))
        for node_id, turn in edge.turns.items():
            node = document.node(node_id)
            endpoint = edge.a if edge.a.node_id == node_id else edge.b
            if not supports_beam_turn(node.kind, endpoint.port_id, topology.incident_ports.get(node_id)):
                diagnostics.append(Diagnostic(f"{node.reference}: this interface cannot turn the beam; set angle constraints on a mirror or beamsplitter", node_id))
            if not MIN_BEAM_TURN <= abs(turn) < 180:
                diagnostics.append(Diagnostic(f"{node.reference}: absolute beam turn must be at least {MIN_BEAM_TURN:g}° and less than 180°; straight/grazing and retracing paths are unsupported", node_id))
            constrained_turns.setdefault(node_id, []).append((edge.id, turn))
    for node_id, constraints in constrained_turns.items():
        if max(turn for _, turn in constraints) - min(turn for _, turn in constraints) > 1e-6:
            node = document.node(node_id)
            diagnostics.append(Diagnostic(f"{node.reference}: conflicting legacy angle constraints; set or clear the angle on this optical element", node_id))
    return diagnostics


def _number(value):
    result = round(float(value), 9)
    return 0.0 if abs(result) < 1e-9 else result


def _placements(document, topology, lengths=None):
    geometry = physical_layout(document, topology, lengths)
    order = [document.node(node_id) for node_id in topology.order]
    placements = {node.reference: tuple(map(_number, (*geometry.positions[node.id], geometry.orientations[node.id])))
                  for node in order}
    return document.node(topology.source_id), order, placements, geometry.headings


def _definition(document, node, topology, turns=None):
    """Render the same registry-controlled specification used for CAD bounds."""
    return part_spec(document, node, topology, turns).render(f"PARAMETERS[{node.reference!r}]")


def compile_schematic(document):
    try:
        document = document_from_dict(document.to_dict())
    except ValueError as error:
        return Compilation("", [Diagnostic(str(error))])
    diagnostics = validate_schematic(document)
    if diagnostics:
        return Compilation("", diagnostics)
    original = document
    topology = resolve_topology(document)
    source, order, placements, headings = _placements(document, topology)
    lengths = {edge.id: connection_length(document, edge) for edge in document.connections}
    geometry = None
    if document.optimized_layout is not None:
        from .optimization import optimized_physical_layout
        try:
            geometry = optimized_physical_layout(document, topology)
        except ValueError as error:
            return Compilation("", [Diagnostic(str(error))])
        from .effective import effective_document
        from .optimization import OptimizationOptions
        document = effective_document(original, geometry.graph, OptimizationOptions(**original.optimization["options"]))
        topology = resolve_topology(document)
        source = document.node(topology.source_id)
        order = [document.node(node_id) for node_id in topology.order]
        lengths = geometry.lengths
    else:
        if document.path_constraints or any(node.id != source.id and ("x" in node.physical or "y" in node.physical)
                                            for node in document.nodes):
            lengths, position_errors = resolve_position_lengths(document, topology, headings)
            if position_errors:
                return Compilation("", position_errors, placements=placements)
        geometry = physical_layout(document, topology, lengths)
    placements = {node.reference: tuple(map(_number, (*geometry.positions[node.id], geometry.orientations[node.id])))
                  for node in order}
    for node in order:
        for axis, key in enumerate(("x", "y")):
            if key in node.physical and abs(geometry.positions[node.id][axis] - node.physical[key]) > POSITION_TOLERANCE:
                diagnostics.append(Diagnostic(f"{node.reference}: position constraint could not be satisfied within {POSITION_TOLERANCE:g} mm", node.id))
    physical_nodes = [node for node in order if node.kind not in ("source", "output")]
    for index, node in enumerate(physical_nodes):
        x, y, _ = placements[node.reference]
        for other in physical_nodes[:index]:
            ox, oy, _ = placements[other.reference]
            if hypot(x - ox, y - oy) < 1e-6:
                diagnostics.append(Diagnostic(f"{node.reference} overlaps {other.reference}; change physical distances or turns", node.id))
    if diagnostics:
        return Compilation("", diagnostics, placements=placements, lengths=lengths)
    object_map = {node.id: node.reference for node in order}
    nodes = {node.id: node for node in order}
    expected = [(nodes[edge.source.node_id].reference, edge.interaction,
                 None if nodes[edge.target.node_id].kind == "output" else nodes[edge.target.node_id].reference)
                for edge in sorted(topology.edges.values(), key=lambda e: (nodes[e.source.node_id].reference, e.interaction))]
    open_lengths = {(nodes[edge.source.node_id].reference, edge.interaction):
                    lengths[edge.id]
                    for edge in topology.edges.values() if nodes[edge.target.node_id].kind == "output"}
    parameters = {node.reference: parameter_values(node) for node in physical_nodes
                  if node.kind != "fiber_source"}
    sx, sy = geometry.positions[source.id]
    source_settings = {**parameter_values(source), "x": _number(sx), "y": _number(sy),
                       "angle": _number(geometry.source_direction),
                       "open_length": document.settings["open_length"]}
    part_placements = {node.reference: placements[node.reference] for node in physical_nodes
                       if node.kind != "fiber_source"}
    lines = [
        '"""Generated by the PyOpticL optical schematic editor.',
        "Edit PLACEMENTS (millimeters/degrees) and PARAMETERS to refine this draft.",
        'Regeneration replaces this file; Python edits do not update the schematic."""',
        "", "from PyOpticL.layout import Layout, Component",
        "from PyOpticL.beam_path import BeamPath",
        "from PyOpticL.library import optics, thorlabs",
        "from PyOpticL.schematic.runtime import check_trace",
        "", f"PLACEMENTS = {pformat(part_placements, sort_dicts=True)}",
        "", f"PARAMETERS = {pformat(parameters, sort_dicts=True)}",
        "", f"SOURCE = {pformat(source_settings, sort_dicts=True)}",
        "", f"EXPECTED = {pformat(expected)}",
        "", f"OPEN_LENGTHS = {pformat(open_lengths, sort_dicts=True)}",
        "", "", "def build_layout():",
        f"    layout = Layout({document.title!r})", "    objects = {}",
    ]
    if geometry.graph is not None and geometry.graph.edits:
        added = sorted(nodes[item.id].reference for item in geometry.graph.generated)
        omitted = sorted(original.node(node_id).reference for node_id in geometry.graph.bypassed)
        lines[4:4] = [
            "# Optimizer-added Folding mirrors: " + (", ".join(map(repr, added)) or "none"),
            "# Schematic mirrors omitted by optimization: " + (", ".join(map(repr, omitted)) or "none"),
            "",
        ]
    for index, node in enumerate(physical_nodes):
        variable = f"part_{index + 1}"
        lines.extend([
            f"    # {node.reference!r}: {SYMBOLS[node.kind].title} ({node.preset})",
            f"    {variable} = Component(label={node.reference!r}, definition={_definition(document, node, topology, geometry.turns)})",
            "    x, y, angle = SOURCE['x'], SOURCE['y'], SOURCE['angle'] + 180" if node.kind == "fiber_source" else
            f"    x, y, angle = PLACEMENTS[{node.reference!r}]",
            f"    objects[{node.reference!r}] = layout.add({variable}, position=(x, y, 0), rotation=angle)",
        ])
    splitters = sorted(node.reference for node in order if node.kind == "splitter")
    lines.extend([
        "    beam = layout.add(",
        f"        BeamPath(label={source.reference!r}, wavelength=SOURCE['wavelength'],",
        "                 power=SOURCE['power'], waist=SOURCE['waist'],",
        "                 final_distance=SOURCE['open_length']),",
        "        position=(SOURCE['x'], SOURCE['y'], 0), rotation=SOURCE['angle'],",
        "    )",
        "    layout.recompute()",
        f"    check_trace(beam, objects, EXPECTED, source_reference={source.reference!r}, splitters={splitters!r}, open_lengths=OPEN_LENGTHS)",
        "    return layout", "", "", "if __name__ == '__main__':", "    build_layout()", "",
    ])
    measured_paths = {item.id: path_length(document, item.component_a, item.component_b, geometry.lengths)
                      for item in document.path_constraints}
    logical_lengths, routed_lengths = {}, {}
    for edge in original.connections:
        if edge.a.node_id in geometry.positions and edge.b.node_id in geometry.positions:
            a, b = geometry.positions[edge.a.node_id], geometry.positions[edge.b.node_id]
            logical_lengths[edge.id] = hypot(b[0]-a[0], b[1]-a[1])
            routed_lengths[edge.id] = path_length(document, edge.a.node_id, edge.b.node_id, geometry.lengths)
    if original.optimized_layout is None:
        logical_lengths = lengths
    return Compilation("\n".join(lines), [], object_map, placements, logical_lengths, geometry, measured_paths, routed_lengths)
