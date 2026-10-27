"""Curated schematic symbols. This module deliberately has no CAD imports."""

from dataclasses import dataclass, field, replace
from math import asin, atan2, degrees, radians, sin


@dataclass(frozen=True)
class Parameter:
    label: str
    default: float
    minimum: float | None = None
    maximum: float | None = None
    exclusive: bool = False
    integer: bool = False


@dataclass(frozen=True)
class Symbol:
    title: str
    prefix: str
    ports: dict[str, tuple[float, float]]
    presets: tuple[str, ...]
    parameters: dict[str, Parameter] = field(default_factory=dict)
    role: str = "passive"
    preset_parameters: dict[str, dict[str, Parameter]] = field(default_factory=dict)

    def port_position(self, port):
        return self.ports[port]


TWO_PORTS = {"A": (-40.0, 0.0), "B": (40.0, 0.0)}
SOURCE_PORT = {"beam": (40.0, 0.0)}
TERMINAL_PORT = {"beam": (-40.0, 0.0)}
TRANSMISSION = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
REFLECTION = {"left": "top", "top": "left", "right": "bottom", "bottom": "right"}
MIN_BEAM_TURN = 0.001  # stay above the ray tracer's parallel-plane tolerance


DIAMETER = Parameter("Diameter (mm)", 12.7, 0, exclusive=True)
SOURCE = {
    "wavelength": Parameter("Wavelength (nm)", 635, 0, exclusive=True),
    "power": Parameter("Power (W)", 1, 0, exclusive=True),
    "waist": Parameter("Beam waist radius (mm)", 0.5, 0, exclusive=True),
    "polarization_angle": Parameter("Linear polarization (deg)", 0),
}
SYMBOLS = {
    "source": Symbol("Beam source", "S", SOURCE_PORT, ("beam",), SOURCE, role="source"),
    "fiber_source": Symbol("Fiber source", "FI", SOURCE_PORT, ("paf2",), SOURCE, role="source"),
    "mirror": Symbol(
        "Mirror", "M", {"A": (-40.0, 0.0), "B": (0.0, -40.0)}, ("mounted", "bare"), {"diameter": DIAMETER}
    ),
    "lens": Symbol(
        "Spherical lens",
        "L",
        TWO_PORTS,
        ("mounted", "bare"),
        {"diameter": DIAMETER, "focal_length": Parameter("Focal length (mm)", 50)},
    ),
    "hwp": Symbol(
        "Half-wave plate",
        "HWP",
        TWO_PORTS,
        ("mounted", "bare"),
        {"diameter": DIAMETER, "fast_axis_angle": Parameter("Fast axis (deg)", 0)},
    ),
    "qwp": Symbol(
        "Quarter-wave plate",
        "QWP",
        TWO_PORTS,
        ("mounted", "bare"),
        {"diameter": DIAMETER, "fast_axis_angle": Parameter("Fast axis (deg)", 0)},
    ),
    "splitter": Symbol(
        "Cube beamsplitter",
        "BS",
        {"left": (-40.0, 0.0), "right": (40.0, 0.0), "top": (0.0, -40.0), "bottom": (0.0, 40.0)},
        ("bare", "surface_adapter"),
        {
            "side_length": Parameter("Side length (mm)", 12.7, 0, exclusive=True),
            "ref_ratio": Parameter("Reflected power fraction", 0.5, 0, 1, True),
        },
    ),
    "iris": Symbol(
        "Iris",
        "I",
        TWO_PORTS,
        ("ida12",),
        {
            "pinhole_diameter": Parameter("Pinhole diameter (mm)", 1, 0, 12.7, True),
        },
    ),
    "fiber_output": Symbol("Fiber receiver", "FO", TERMINAL_PORT, ("paf2",), role="terminal"),
    "stop": Symbol("Beam stop", "D", TERMINAL_PORT, ("absorber",), {"diameter": DIAMETER}, role="terminal"),
    "output": Symbol("Open output", "O", TERMINAL_PORT, ("open",), role="terminal"),
}

# Vendor selections extend existing symbols; old presets retain their exact
# parameter defaults and specifications, including saved optimized layouts.
MIRROR_MOUNTS = {"POLARIS-K05VS2": 12.7, "POLARIS-K1VS2": 25.4, "MHV-12.7L-R": 12.7, "MHV-25.4L-R": 25.4}
LENS_MOUNTS = {"POLARIS-L05G": 12.7, "POLARIS-L1G": 25.4}
COUPLING_MOUNTS = ("POLARIS-K05T6", "KA05TA")

for kind, mounts in (("mirror", MIRROR_MOUNTS), ("lens", LENS_MOUNTS)):
    additions = {
        name: {
            "diameter": Parameter("Diameter (mm)", diameter, diameter, diameter),
            "thickness": Parameter("Optic thickness (mm)", 3 if kind == "mirror" else 2, 0, exclusive=True),
        }
        for name, diameter in mounts.items()
    }
    if kind == "mirror":
        for name, bounds in {
            "MHV-12.7L-R": (2, 6),
            "MHV-25.4L-R": (3, 7),
            "POLARIS-K1VS2": (0.000001, 8.763),
        }.items():
            additions[name]["thickness"] = Parameter("Optic thickness (mm)", 3, *bounds)
    SYMBOLS[kind] = replace(
        SYMBOLS[kind], presets=SYMBOLS[kind].presets + tuple(mounts), preset_parameters=additions
    )
for kind in ("hwp", "qwp"):
    additions = {
        name: {
            "diameter": Parameter("Diameter (mm)", 12.7, 12.7, 12.7),
            "thickness": (
                Parameter("Optic thickness (mm)", 1, 0.000001, 4)
                if name == "FBR"
                else Parameter("Optic thickness (mm)", 1, 0, exclusive=True)
            ),
        }
        for name in ("FBR", "ELL16")
    }
    SYMBOLS[kind] = replace(
        SYMBOLS[kind], presets=SYMBOLS[kind].presets + ("FBR", "ELL16"), preset_parameters=additions
    )
for kind in ("fiber_source", "fiber_output"):
    additions = {
        name: (
            {"wavelength": Parameter("Wavelength (nm)", 1550, 0, exclusive=True)}
            if kind == "fiber_source"
            else {}
        )
        for name in COUPLING_MOUNTS
    }
    SYMBOLS[kind] = replace(
        SYMBOLS[kind], presets=SYMBOLS[kind].presets + COUPLING_MOUNTS, preset_parameters=additions
    )
SYMBOLS["splitter"] = replace(
    SYMBOLS["splitter"],
    presets=SYMBOLS["splitter"].presets + ("displacement_pbs",),
    preset_parameters={
        "displacement_pbs": {
            "side_length": Parameter("Side length (mm)", 12.7, 12.7, 12.7),
            "ref_polarization": Parameter("Reflected polarization (deg)", 45),
        }
    },
)
SYMBOLS["iris"] = replace(
    SYMBOLS["iris"],
    presets=SYMBOLS["iris"].presets + ("alignment",),
    preset_parameters={
        "alignment": {"aperture_diameter": Parameter("Aperture diameter (mm)", 0.5, 0, 20, True)}
    },
)
SYMBOLS["slit"] = Symbol(
    "Variable slit (VA100)",
    "SL",
    TWO_PORTS,
    ("VA100",),
    {"slit_width": Parameter("Slit width (mm)", 1, 0, 6)},
)
SYMBOLS["grating"] = Symbol(
    "Transmission grating (LightSmyth)",
    "G",
    TWO_PORTS,
    ("MK05S", "bare"),
    {
        "incidence_angle": Parameter("Incidence angle (deg)", 49.9, -89.999, 89.999),
        "order": Parameter("Diffraction order", 1, -20, 20, integer=True),
    },
)
SYMBOLS["roof"] = Symbol(
    "Roof mirror (HRS1015-P01)",
    "RM",
    {"A": (-40.0, -12.0), "B": (-40.0, 12.0)},
    ("horizontal", "vertical", "bare_horizontal", "bare_vertical"),
    {"beam_separation": Parameter("Beam separation (mm)", 12.7, 3, 22)},
)

# Bare optics expose the modeled thickness so physically sized pickoffs can be
# configured without changing a mount's verified seating specification.
for kind, thickness in (("mirror",6),("lens",2),("hwp",1),("qwp",1)):
    symbol=SYMBOLS[kind]
    SYMBOLS[kind]=replace(symbol,preset_parameters={**symbol.preset_parameters,
        "bare":{"thickness":Parameter("Optic thickness (mm)",thickness,0,exclusive=True)}})


def parameter_specs(node):
    specs = {**SYMBOLS[node.kind].parameters, **SYMBOLS[node.kind].preset_parameters.get(node.preset, {})}
    if node.kind == "iris" and node.preset == "alignment":
        specs.pop("pinhole_diameter")
    if node.kind == "splitter" and node.preset == "displacement_pbs":
        specs.pop("ref_ratio")
    return specs


def select_preset(node, preset):
    node.preset = preset
    specs = parameter_specs(node)
    node.parameters = {key: value for key, value in node.parameters.items() if key in specs}
    for key, spec in specs.items():
        if spec.minimum is not None and spec.minimum == spec.maximum:
            node.parameters[key] = spec.default


def grating_turn(document, node, topology):
    p = parameter_values(node)
    source = document.node(topology.source_id)
    wavelength = parameter_values(source)["wavelength"]
    alpha, order = p["incidence_angle"], p["order"]
    if type(order) is not int:
        raise ValueError("Diffraction order must be an integer")
    sine = order * wavelength * 0.001 - sin(radians(alpha))
    if not -1 < sine < 1:
        raise ValueError("Selected grating order is nonpropagating or grazing at the source wavelength")
    turn = alpha + degrees(asin(sine))
    return -turn if topology.incident_ports.get(node.id) == "B" else turn


def fixed_turn(document, node, topology):
    if node.kind == "roof":
        return 180.0
    return grating_turn(document, node, topology) if node.kind == "grating" else 0.0


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
    if kind == "roof":
        return 0.0
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


def supports_beam_turn(kind, port, incident_port=None):
    """Only reflecting interfaces can change direction in the current library.

    A splitter's incoming and reflected connections constrain its reflected
    branch; its transmitted connection must continue straight through.
    """
    return kind == "mirror" or (
        kind == "splitter" and (incident_port is None or port != TRANSMISSION[incident_port])
    )


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
    return {**{key: value.default for key, value in parameter_specs(node).items()}, **node.parameters}
