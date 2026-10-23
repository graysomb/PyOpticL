"""Curated schematic symbols. This module deliberately has no CAD imports."""

from dataclasses import dataclass, field


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
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    presets: tuple[str, ...]
    parameters: dict[str, Parameter] = field(default_factory=dict)

    def port_position(self, port):
        if port in self.inputs:
            return (-40.0, 0.0)
        if port == "reflected" or (self.prefix == "M" and port == "out"):
            return (0.0, -40.0)
        return (40.0, 0.0)


DIAMETER = Parameter("Diameter (mm)", 12.7, 0, exclusive=True)
SOURCE = {
    "wavelength": Parameter("Wavelength (nm)", 635, 0, exclusive=True),
    "power": Parameter("Power (W)", 1, 0, exclusive=True),
    "waist": Parameter("Beam waist radius (mm)", 0.5, 0, exclusive=True),
}
SYMBOLS = {
    "source": Symbol("Beam source", "S", (), ("out",), ("beam",), SOURCE),
    "fiber_source": Symbol("Fiber input", "FI", (), ("out",), ("paf2",), SOURCE),
    "mirror": Symbol("Mirror", "M", ("in",), ("out",), ("mounted", "bare"),
                     {"diameter": DIAMETER}),
    "lens": Symbol("Spherical lens", "L", ("in",), ("out",), ("mounted", "bare"),
                   {"diameter": DIAMETER, "focal_length": Parameter("Focal length (mm)", 50)}),
    "hwp": Symbol("Half-wave plate", "HWP", ("in",), ("out",), ("mounted", "bare"),
                  {"diameter": DIAMETER, "fast_axis_angle": Parameter("Fast axis (deg)", 0)}),
    "qwp": Symbol("Quarter-wave plate", "QWP", ("in",), ("out",), ("mounted", "bare"),
                  {"diameter": DIAMETER, "fast_axis_angle": Parameter("Fast axis (deg)", 0)}),
    "splitter": Symbol("Cube beamsplitter", "BS", ("in",), ("transmitted", "reflected"),
                       ("bare", "surface_adapter"), {
                           "side_length": Parameter("Side length (mm)", 12.7, 0, exclusive=True),
                           "ref_ratio": Parameter("Reflected power fraction", 0.5, 0, 1, True),
                       }),
    "iris": Symbol("Iris", "I", ("in",), ("out",), ("ida12",), {
        "pinhole_diameter": Parameter("Pinhole diameter (mm)", 1, 0, 12.7, True),
    }),
    "fiber_output": Symbol("Fiber output", "FO", ("in",), (), ("paf2",)),
    "stop": Symbol("Beam stop", "D", ("in",), (), ("absorber",), {"diameter": DIAMETER}),
    "output": Symbol("Open output", "O", ("in",), (), ("open",)),
}


def parameter_values(node):
    return {**{key: value.default for key, value in SYMBOLS[node.kind].parameters.items()},
            **node.parameters}
