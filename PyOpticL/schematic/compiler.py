"""Compile source-resolved optical topology into ordinary PyOpticL Python."""

from collections import deque
from dataclasses import dataclass, field
from math import atan2, cos, degrees, hypot, radians, sin
from pprint import pformat

from .model import connection_length, document_from_dict, interface_turn, _finite
from .registry import MIN_BEAM_TURN, SYMBOLS, default_turn, incident_heading, parameter_values, supports_beam_turn
from .topology import Diagnostic, resolve_topology


@dataclass
class Compilation:
    source: str
    diagnostics: list[Diagnostic]
    object_map: dict[str, str] = field(default_factory=dict)
    placements: dict = field(default_factory=dict)

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
        allowed = {"x", "y", "angle"} if symbol.role == "source" else set()
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


def _placements(document, topology):
    nodes = {node.id: node for node in document.nodes}
    source = nodes[topology.source_id]
    connections = {edge.id: edge for edge in document.connections}
    positions, order = {}, []
    queue = deque([(source.id, source.physical.get("x", 0), source.physical.get("y", 0), source.physical.get("angle", 0))])
    while queue:
        node_id, x, y, incoming = queue.popleft()
        node = nodes[node_id]
        angle = incoming
        incident_port = topology.incident_ports.get(node_id)
        turn = interface_turn(document, node, topology)
        if SYMBOLS[node.kind].role == "passive" and node.kind != "mirror":
            angle -= incident_heading(node.kind, incident_port)
        if node.kind == "mirror":
            leaving = incoming + turn
            angle = degrees(atan2(sin(radians(leaving)) - sin(radians(incoming)),
                                  cos(radians(leaving)) - cos(radians(incoming))))
        if node.kind == "splitter":
            # Rotating the splitting plane by delta rotates its reflection by
            # 2*delta. Keep the existing cube preset/face mapping for the sign.
            angle += (turn - (90 if turn > 0 else -90)) / 2
        if node.kind in ("fiber_source", "fiber_output", "stop"):
            angle = incoming + 180
        positions[node.reference] = tuple(map(_number, (x, y, angle)))
        order.append(node)
        for edge in topology.outgoing[node_id]:
            heading = incoming
            if node.kind == "mirror" or edge.interaction == "reflected":
                heading += turn
            target = nodes[edge.target.node_id]
            distance = connection_length(document, connections[edge.id])
            queue.append((target.id, x + distance * cos(radians(heading)),
                          y + distance * sin(radians(heading)), heading))
    return source, order, positions


def _definition(document, node, topology):
    """Only registry-controlled identifiers become executable source."""
    p = f"PARAMETERS[{node.reference!r}]"
    mounted = node.preset == "mounted"
    if node.kind == "mirror":
        mount = ", mount_definition=thorlabs.Mirror_Mount_K05S1()" if mounted else ""
        return f"optics.Circular_Mirror(**{p}{mount})"
    if node.kind == "lens":
        mount = ", mount_definition=thorlabs.Lens_Mount_L05G()" if mounted else ""
        return f"optics.Spherical_Lens(**{p}{mount})"
    if node.kind in ("hwp", "qwp"):
        mount = ", mount_definition=thorlabs.Rotation_Mount_RSP05()" if mounted else ""
        retardance = 0.5 if node.kind == "hwp" else 0.25
        return f"optics.Circular_Waveplate(retardance={retardance}, **{p}{mount})"
    if node.kind == "splitter":
        factory = "Beamsplitter_Cube_on_Surface_Adapter" if node.preset == "surface_adapter" else "Beamsplitter_Cube"
        canonical_turn = default_turn(node.kind, topology.incident_ports.get(node.id))
        turn = interface_turn(document, node, topology)
        return f"optics.{factory}(rotate_cube={(turn > 0) != (canonical_turn > 0)!r}, **{p})"
    if node.kind == "iris":
        return f"thorlabs.Iris_IDA12(**{p})"
    if node.kind in ("fiber_source", "fiber_output"):
        return "thorlabs.Fiberport_PAF2A4A()"
    if node.kind == "stop":
        return f"optics.Beam_Stop(**{p})"
    raise ValueError(node.kind)


def compile_schematic(document):
    try:
        document = document_from_dict(document.to_dict())
    except ValueError as error:
        return Compilation("", [Diagnostic(str(error))])
    diagnostics = validate_schematic(document)
    if diagnostics:
        return Compilation("", diagnostics)
    topology = resolve_topology(document)
    source, order, placements = _placements(document, topology)
    physical_nodes = [node for node in order if node.kind not in ("source", "output")]
    for index, node in enumerate(physical_nodes):
        x, y, _ = placements[node.reference]
        for other in physical_nodes[:index]:
            ox, oy, _ = placements[other.reference]
            if hypot(x - ox, y - oy) < 1e-6:
                diagnostics.append(Diagnostic(f"{node.reference} overlaps {other.reference}; change physical distances or turns", node.id))
    if diagnostics:
        return Compilation("", diagnostics, placements=placements)
    object_map = {node.id: node.reference for node in order}
    nodes = {node.id: node for node in order}
    expected = [(nodes[edge.source.node_id].reference, edge.interaction,
                 None if nodes[edge.target.node_id].kind == "output" else nodes[edge.target.node_id].reference)
                for edge in sorted(topology.edges.values(), key=lambda e: (nodes[e.source.node_id].reference, e.interaction))]
    open_lengths = {(nodes[edge.source.node_id].reference, edge.interaction):
                    connection_length(document, document.connection(edge.id))
                    for edge in topology.edges.values() if nodes[edge.target.node_id].kind == "output"}
    parameters = {node.reference: parameter_values(node) for node in physical_nodes
                  if node.kind != "fiber_source"}
    sx = source.physical.get("x", 0)
    sy = source.physical.get("y", 0)
    source_settings = {**parameter_values(source), "x": _number(sx), "y": _number(sy),
                       "angle": _number(source.physical.get("angle", 0)),
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
    for index, node in enumerate(physical_nodes):
        variable = f"part_{index + 1}"
        lines.extend([
            f"    # {node.reference!r}: {SYMBOLS[node.kind].title} ({node.preset})",
            f"    {variable} = Component(label={node.reference!r}, definition={_definition(document, node, topology)})",
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
    return Compilation("\n".join(lines), [], object_map, placements)
