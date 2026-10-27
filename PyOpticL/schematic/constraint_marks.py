"""Read-only descriptions of geometry constraints for canvas marks."""

from dataclasses import dataclass

from .paths import component_path
from .registry import AXIS_ALIGNED_KINDS, parameter_values


MARK_TYPES = (
    ("position", "P", "Position"),
    ("angle", "∠", "Pass angle"),
    ("direction", "→", "Beam direction"),
    ("center", "⊙", "Centered hit"),
    ("offset", "↔", "Roof offset"),
    ("incidence", "i", "Grating incidence"),
    ("alignment", "∥", "Straight-through alignment"),
    ("length", "L", "Beam endpoint separation"),
    ("path_length", "Σ", "Total routed path length"),
)
LEGEND = "Constraint marks: " + " · ".join(f"{mark} {label.lower()}" for _, mark, label in MARK_TYPES)


@dataclass(frozen=True)
class ConstraintMark:
    kind: str
    mark: str
    tooltip: str


def _marks(notes):
    return tuple(ConstraintMark(kind, mark, label + "\n" + "\n".join(dict.fromkeys(notes[kind])))
                 for kind, mark, label in MARK_TYPES if notes.get(kind))


def _visit_label(document, visit_id):
    visit = document.optical_pass(visit_id)
    node = document.node(visit.component_id)
    visits = [p for p in document.optical_passes() if p.component_id == node.id]
    index = next(i + 1 for i, p in enumerate(visits) if p.id == visit.id)
    return f"{node.reference} · pass {index}"


def _path_note(document, constraint):
    a = _visit_label(document, constraint.pass_a or constraint.component_a)
    b = _visit_label(document, constraint.pass_b or constraint.component_b)
    return f"{a} → {b}: {constraint.length_mm:g} mm (total route, including roof internal paths)"


def component_marks(document, node_id):
    node = document.node(node_id)
    notes = {}

    def add(kind, text):
        notes.setdefault(kind, []).append(text)

    pins = [f"{axis.upper()} = {node.physical[axis]:g} mm" for axis in ("x", "y") if axis in node.physical]
    if pins:
        add("position", node.reference + ": " + ", ".join(pins))
    if "angle" in node.physical:
        add("direction", f"{node.reference}: beam travel heading {node.physical['angle']:g}° in XY")
    for visit in document.optical_passes():
        if visit.component_id != node_id:
            continue
        label = _visit_label(document, visit.id)
        if visit.centered and visit.mode != "emit" and node.kind != "output":
            add("center", label + (": roof entrance centered" if node.kind == "roof" else ": optical center"))
        if visit.turn is not None:
            add("angle", f"{label}: signed turn {visit.turn:g}°")
        if visit.direction is not None:
            add("direction", f"{label}: beam travel heading {visit.direction:g}° in XY")
    if "turn" in node.physical:
        add("angle", f"{node.reference} · pass 1: signed turn {node.physical['turn']:g}°")
    for edge in document.connections:
        if node_id in edge.turns:
            add("angle", f"{node.reference}: legacy turn {edge.turns[node_id]:g}° on beam {edge.id}")
    if node.kind == "roof":
        add("offset", f"{node.reference}: transverse return separation {parameter_values(node)['beam_separation']:g} mm")
    if node.kind == "grating":
        add("incidence", f"{node.reference}: incidence {parameter_values(node)['incidence_angle']:g}° relative to the beam")
    if node.kind in AXIS_ALIGNED_KINDS:
        add("alignment", f"{node.reference}: optical axis automatically follows the beam")
    for constraint in document.path_constraints:
        if node_id in (constraint.component_a, constraint.component_b):
            add("path_length", _path_note(document, constraint))
    return _marks(notes)


def beam_marks(document, logical_ids):
    logical_ids = set(logical_ids)
    notes = {}
    for edge in document.connections:
        if edge.id in logical_ids and edge.length is not None:
            a, b = _visit_label(document, edge.a.visit_id), _visit_label(document, edge.b.visit_id)
            notes.setdefault("length", []).append(f"{a} ↔ {b}: endpoint separation {edge.length:g} mm")
    for constraint in document.path_constraints:
        try:
            route = component_path(document, constraint.pass_a or constraint.component_a,
                                   constraint.pass_b or constraint.component_b)
        except ValueError:
            continue  # Endpoint marks still identify a constraint on a broken route.
        if logical_ids.intersection(route):
            notes.setdefault("path_length", []).append(_path_note(document, constraint))
    return _marks(notes)
