"""Curated schematic symbols. This module deliberately has no CAD imports."""

from dataclasses import dataclass, field
from math import atan2, degrees


@dataclass(frozen=True)
class Parameter:
    label: str
    default: float
    minimum: float | None = None
    maximum: float | None = None
    exclusive: bool = False


@dataclass(frozen=True)
class Symbol:
    title: str
    prefix: str
    ports: dict[str, tuple[float, float]]
    presets: tuple[str, ...]
    parameters: dict[str, Parameter] = field(default_factory=dict)
    role: str = "passive"

    def port_position(self, port):
        return self.ports[port]


TWO_PORTS = {"A": (-40.0, 0.0), "B": (40.0, 0.0)}
SOURCE_PORT = {"beam": (40.0, 0.0)}
TERMINAL_PORT = {"beam": (-40.0, 0.0)}
TRANSMISSION = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
REFLECTION = {"left": "top", "top": "left", "right": "bottom", "bottom": "right"}


DIAMETER = Parameter("Diameter (mm)", 12.7, 0, exclusive=True)
SOURCE = {
    "wavelength": Parameter("Wavelength (nm)", 635, 0, exclusive=True),
    "power": Parameter("Power (W)", 1, 0, exclusive=True),
    "waist": Parameter("Beam waist radius (mm)", 0.5, 0, exclusive=True),
}
SYMBOLS = {
    "source": Symbol("Beam source", "S", SOURCE_PORT, ("beam",), SOURCE, role="source"),
    "fiber_source": Symbol("Fiber source", "FI", SOURCE_PORT, ("paf2",), SOURCE, role="source"),
    "mirror": Symbol("Mirror", "M", {"A": (-40.0, 0.0), "B": (0.0, -40.0)}, ("mounted", "bare"),
                     {"diameter": DIAMETER}),
    "lens": Symbol("Spherical lens", "L", TWO_PORTS, ("mounted", "bare"),
                   {"diameter": DIAMETER, "focal_length": Parameter("Focal length (mm)", 50)}),
    "hwp": Symbol("Half-wave plate", "HWP", TWO_PORTS, ("mounted", "bare"),
                  {"diameter": DIAMETER, "fast_axis_angle": Parameter("Fast axis (deg)", 0)}),
    "qwp": Symbol("Quarter-wave plate", "QWP", TWO_PORTS, ("mounted", "bare"),
                  {"diameter": DIAMETER, "fast_axis_angle": Parameter("Fast axis (deg)", 0)}),
    "splitter": Symbol("Cube beamsplitter", "BS", {
                           "left": (-40.0, 0.0), "right": (40.0, 0.0),
                           "top": (0.0, -40.0), "bottom": (0.0, 40.0)},
                       ("bare", "surface_adapter"), {
                           "side_length": Parameter("Side length (mm)", 12.7, 0, exclusive=True),
                           "ref_ratio": Parameter("Reflected power fraction", 0.5, 0, 1, True),
                       }),
    "iris": Symbol("Iris", "I", TWO_PORTS, ("ida12",), {
        "pinhole_diameter": Parameter("Pinhole diameter (mm)", 1, 0, 12.7, True),
    }),
    "fiber_output": Symbol("Fiber receiver", "FO", TERMINAL_PORT, ("paf2",), role="terminal"),
    "stop": Symbol("Beam stop", "D", TERMINAL_PORT, ("absorber",), {"diameter": DIAMETER}, role="terminal"),
    "output": Symbol("Open output", "O", TERMINAL_PORT, ("open",), role="terminal"),
}


def branch_ports(kind, incident_port=None):
    """Map neutral exit ports to interaction roles for a particular incident port."""
    symbol = SYMBOLS[kind]
    if symbol.role == "source":
        return {"beam": "out"}
    if symbol.role == "terminal" or incident_port is None:
        return {}
    if kind == "splitter":
        return {TRANSMISSION[incident_port]: "transmitted", REFLECTION[incident_port]: "reflected"}
    return {port: "out" for port in symbol.ports if port != incident_port}


def incident_heading(kind, incident_port):
    """Local incoming-ray heading at a neutral port (physical Y points up)."""
    x, y = SYMBOLS[kind].port_position(incident_port)
    return degrees(atan2(y, -x))


def default_turn(kind, incident_port):
    """Default physical turn from the symbol's local port geometry, without canvas rotation."""
    if kind not in ("mirror", "splitter") or incident_port is None:
        return 90.0
    symbol = SYMBOLS[kind]
    exits = branch_ports(kind, incident_port)
    exit_port = next(port for port, role in exits.items() if role != "transmitted")
    ox, oy = symbol.port_position(exit_port)
    incoming = incident_heading(kind, incident_port)
    outgoing = degrees(atan2(-oy, ox))
    return (outgoing - incoming + 180) % 360 - 180


def legacy_port(kind, name):
    """Translate version 1 names without changing any existing port positions."""
    if SYMBOLS[kind].role == "source":
        return {"out": "beam"}[name]
    if SYMBOLS[kind].role == "terminal":
        return {"in": "beam"}[name]
    if kind == "splitter":
        return {"in": "left", "transmitted": "right", "reflected": "top"}[name]
    return {"in": "A", "out": "B"}[name]


def parameter_values(node):
    return {**{key: value.default for key, value in SYMBOLS[node.kind].parameters.items()},
            **node.parameters}
