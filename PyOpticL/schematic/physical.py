"""Shared, CAD-independent physical geometry for export and optimization."""

from dataclasses import dataclass
from math import atan2, cos, degrees, radians, sin

from .model import connection_length, interface_turn
from .effective import EffectiveGraph
from .registry import SYMBOLS, incident_heading


def wrap_angle(angle):
    return (angle + 180) % 360 - 180


@dataclass(frozen=True)
class PhysicalLayout:
    positions: dict
    orientations: dict
    headings: dict
    lengths: dict
    turns: dict
    source_direction: float
    graph: EffectiveGraph | None = None

    def snapshot(self, source_id):
        return {
            "source_pose": [*self.positions[source_id], self.source_direction],
            "lengths": dict(self.lengths),
            "turns": dict(self.turns),
        }


def physical_layout(document, topology, lengths=None, turns=None, source_pose=None):
    """Reconstruct exact optical relationships from lengths and reflecting turns."""
    nodes = {node.id: node for node in document.nodes}
    source = nodes[topology.source_id]
    source_pose = (
        source_pose
        if source_pose is not None
        else (source.physical.get("x", 0), source.physical.get("y", 0), source.physical.get("angle", 0))
    )
    lengths = (
        lengths
        if lengths is not None
        else {edge.id: connection_length(document, edge) for edge in document.connections}
    )
    turns = (
        turns
        if turns is not None
        else {
            node.id: interface_turn(document, node, topology)
            for node in document.nodes
            if node.kind in ("mirror", "splitter")
        }
    )
    positions = {source.id: tuple(source_pose[:2])}
    incoming = {source.id: source_pose[2]}
    orientations, headings = {}, {}
    for node_id in topology.order:
        node, heading = nodes[node_id], incoming[node_id]
        angle = heading
        incident = topology.incident_ports.get(node_id)
        turn = turns.get(node_id, 0)
        if SYMBOLS[node.kind].role == "passive" and node.kind != "mirror":
            angle -= incident_heading(node.kind, incident)
        if node.kind == "mirror":
            angle = degrees(
                atan2(
                    sin(radians(heading + turn)) - sin(radians(heading)),
                    cos(radians(heading + turn)) - cos(radians(heading)),
                )
            )
        if node.kind == "splitter":
            angle += (turn - (90 if turn > 0 else -90)) / 2
        if node.kind in ("fiber_source", "fiber_output", "stop"):
            angle = heading + 180
        orientations[node_id] = angle
        x, y = positions[node_id]
        for edge in topology.outgoing[node_id]:
            outgoing = heading + (turn if node.kind == "mirror" or edge.interaction == "reflected" else 0)
            headings[edge.id] = outgoing
            distance = lengths[edge.id]
            positions[edge.target.node_id] = (
                x + distance * cos(radians(outgoing)),
                y + distance * sin(radians(outgoing)),
            )
            incoming[edge.target.node_id] = outgoing
    return PhysicalLayout(positions, orientations, headings, dict(lengths), dict(turns), source_pose[2])
