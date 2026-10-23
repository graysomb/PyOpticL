"""Validate directed optical topology and export ordinary PyOpticL Python."""

from collections import Counter, deque
from dataclasses import dataclass, field
from math import atan2, cos, degrees, hypot, radians, sin
from pprint import pformat

from .model import document_from_dict, _finite
from .registry import SYMBOLS, parameter_values


@dataclass(frozen=True)
class Diagnostic:
    message: str
    node_id: str | None = None
    connection_id: str | None = None
    severity: str = "error"


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
        document_from_dict(document.to_dict())
    except ValueError as error:
        return [Diagnostic(str(error))]
    nodes = {node.id: node for node in document.nodes}
    sources = [node for node in document.nodes if node.kind in ("source", "fiber_source")]
    if len(sources) != 1:
        diagnostics.append(Diagnostic("Exactly one beam source or fiber input is required"))
    inputs, outputs = Counter(), Counter()
    for edge in document.connections:
        inputs[(edge.target, edge.target_port)] += 1
        outputs[(edge.source, edge.source_port)] += 1
    for node in document.nodes:
        symbol = SYMBOLS[node.kind]
        for port in symbol.inputs:
            count = inputs[(node.id, port)]
            if count != 1:
                diagnostics.append(Diagnostic(f"{node.reference}.{port}: expected one incoming connection, found {count}", node.id))
        for port in symbol.outputs:
            count = outputs[(node.id, port)]
            if count != 1:
                diagnostics.append(Diagnostic(f"{node.reference}.{port}: expected one outgoing connection, found {count}. Use an output or stop terminal.", node.id))
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
        allowed = {"x", "y", "angle"} if not symbol.inputs else {"distance"}
        if node.kind in ("mirror", "splitter"):
            allowed.add("turn")
        for name, value in node.physical.items():
            if name not in allowed or not _finite(value):
                diagnostics.append(Diagnostic(f"{node.reference}: invalid physical setting {name}", node.id))
        if node.physical.get("distance", document.settings["spacing"]) <= 0:
            diagnostics.append(Diagnostic(f"{node.reference}: physical distance must be positive", node.id))
        turn = node.physical.get("turn", 90)
        if node.kind == "mirror" and turn not in (-135, -90, -45, 45, 90, 135):
            diagnostics.append(Diagnostic(f"{node.reference}: mirror turn must be ±45, ±90, or ±135 degrees", node.id))
        if node.kind == "splitter" and turn not in (-90, 90):
            diagnostics.append(Diagnostic(f"{node.reference}: cube reflected branch must turn ±90 degrees", node.id))

    # Kahn's algorithm catches cycles even in disconnected or invalid graphs.
    degree = Counter(edge.target for edge in document.connections)
    adjacency = {key: [] for key in nodes}
    for edge in document.connections:
        adjacency[edge.source].append(edge.target)
    queue = deque(key for key in nodes if not degree[key])
    visited = set()
    while queue:
        current = queue.popleft()
        visited.add(current)
        for target in adjacency[current]:
            degree[target] -= 1
            if degree[target] == 0:
                queue.append(target)
    if len(visited) != len(nodes):
        for key in sorted(set(nodes) - visited):
            diagnostics.append(Diagnostic(f"{nodes[key].reference}: cycle or repeated-pass topology is unsupported", key))
    if len(sources) == 1:
        reachable, queue = set(), [sources[0].id]
        while queue:
            current = queue.pop()
            if current not in reachable:
                reachable.add(current)
                queue.extend(adjacency[current])
        for key in set(nodes) - reachable:
            diagnostics.append(Diagnostic(f"{nodes[key].reference}: disconnected from source", key))
    return diagnostics


def _number(value):
    result = round(float(value), 9)
    return 0.0 if abs(result) < 1e-9 else result


def _placements(document):
    nodes = {node.id: node for node in document.nodes}
    source = next(node for node in document.nodes if node.kind in ("source", "fiber_source"))
    outgoing = {(edge.source, edge.source_port): edge for edge in document.connections}
    positions, order = {}, []
    queue = deque([(source.id, source.physical.get("x", 0), source.physical.get("y", 0), source.physical.get("angle", 0))])
    while queue:
        node_id, x, y, incoming = queue.popleft()
        node = nodes[node_id]
        angle = incoming
        if node.kind == "mirror":
            leaving = incoming + node.physical.get("turn", 90)
            angle = degrees(atan2(sin(radians(leaving)) - sin(radians(incoming)),
                                  cos(radians(leaving)) - cos(radians(incoming))))
        if node.kind in ("fiber_source", "fiber_output", "stop"):
            angle = incoming + 180
        positions[node.reference] = tuple(map(_number, (x, y, angle)))
        order.append(node)
        for port in SYMBOLS[node.kind].outputs:
            heading = incoming
            if node.kind == "mirror" or port == "reflected":
                heading += node.physical.get("turn", 90)
            edge = outgoing[(node_id, port)]
            target = nodes[edge.target]
            distance = (document.settings["open_length"] if target.kind == "output" else
                        target.physical.get("distance", document.settings["spacing"]))
            queue.append((target.id, x + distance * cos(radians(heading)),
                          y + distance * sin(radians(heading)), heading))
    return source, order, positions


def _definition(node):
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
        return f"optics.{factory}(rotate_cube={node.physical.get('turn', 90) < 0!r}, **{p})"
    if node.kind == "iris":
        return f"thorlabs.Iris_IDA12(**{p})"
    if node.kind in ("fiber_source", "fiber_output"):
        return "thorlabs.Fiberport_PAF2A4A()"
    if node.kind == "stop":
        return f"optics.Beam_Stop(**{p})"
    raise ValueError(node.kind)


def compile_schematic(document):
    diagnostics = validate_schematic(document)
    if diagnostics:
        return Compilation("", diagnostics)
    source, order, placements = _placements(document)
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
    expected = [(nodes[edge.source].reference, edge.source_port,
                 None if nodes[edge.target].kind == "output" else nodes[edge.target].reference)
                for edge in sorted(document.connections, key=lambda e: (nodes[e.source].reference, e.source_port))]
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
        "", "", "def build_layout():",
        f"    layout = Layout({document.title!r})", "    objects = {}",
    ]
    for index, node in enumerate(physical_nodes):
        variable = f"part_{index + 1}"
        lines.extend([
            f"    # {node.reference!r}: {SYMBOLS[node.kind].title} ({node.preset})",
            f"    {variable} = Component(label={node.reference!r}, definition={_definition(node)})",
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
        f"    check_trace(beam, objects, EXPECTED, source_reference={source.reference!r}, splitters={splitters!r})",
        "    return layout", "", "", "if __name__ == '__main__':", "    build_layout()", "",
    ])
    return Compilation("\n".join(lines), [], object_map, placements)
