"""One CAD-independent part specification for code export and physical bounds."""

from dataclasses import dataclass
from importlib import import_module

from .model import interface_turn
from .registry import default_turn, parameter_values


@dataclass(frozen=True)
class PartSpec:
    module: str
    factory: str
    parameters: tuple = ()
    before: tuple = ()
    after: tuple = ()

    def render(self, parameter_expression=None):
        def value(item):
            return item.render() if isinstance(item, PartSpec) else repr(item)

        arguments = [f"{key}={value(item)}" for key, item in self.before]
        if self.parameters:
            if parameter_expression is None:
                arguments.extend(f"{key}={value(item)}" for key, item in self.parameters)
            else:
                arguments.append(f"**{parameter_expression}")
        arguments.extend(f"{key}={value(item)}" for key, item in self.after)
        return f"{self.module}.{self.factory}({', '.join(arguments)})"

    def instantiate(self):
        # All identifiers originate in the curated mapping below, never JSON.
        if self.module not in ("optics", "thorlabs") or not self.factory.isidentifier() or self.factory.startswith("_"):
            raise ValueError("Unsupported physical part factory")
        module = import_module(f"PyOpticL.library.{self.module}")
        arguments = {key: value.instantiate() if isinstance(value, PartSpec) else value
                     for key, value in (*self.before, *self.parameters, *self.after)}
        return getattr(module, self.factory)(**arguments)


def part_spec(document, node, topology, turns=None):
    """Return a hashable specification, or None for a virtual symbol."""
    parameters = tuple(parameter_values(node).items())
    mount = {
        "mirror": "Mirror_Mount_K05S1", "lens": "Lens_Mount_L05G",
        "hwp": "Rotation_Mount_RSP05", "qwp": "Rotation_Mount_RSP05",
    }.get(node.kind)
    after = (("mount_definition", PartSpec("thorlabs", mount)),) if mount and node.preset == "mounted" else ()
    if node.kind == "mirror":
        return PartSpec("optics", "Circular_Mirror", parameters, after=after)
    if node.kind == "lens":
        return PartSpec("optics", "Spherical_Lens", parameters, after=after)
    if node.kind in ("hwp", "qwp"):
        return PartSpec("optics", "Circular_Waveplate", parameters,
                        (("retardance", 0.5 if node.kind == "hwp" else 0.25),), after)
    if node.kind == "splitter":
        canonical = default_turn(node.kind, topology.incident_ports.get(node.id))
        turn = turns[node.id] if turns is not None else interface_turn(document, node, topology)
        factory = "Beamsplitter_Cube_on_Surface_Adapter" if node.preset == "surface_adapter" else "Beamsplitter_Cube"
        return PartSpec("optics", factory, parameters, (("rotate_cube", (turn > 0) != (canonical > 0)),))
    if node.kind == "iris":
        return PartSpec("thorlabs", "Iris_IDA12", parameters)
    if node.kind in ("fiber_source", "fiber_output"):
        return PartSpec("thorlabs", "Fiberport_PAF2A4A")
    if node.kind == "stop":
        return PartSpec("optics", "Beam_Stop", parameters)
    if node.kind in ("source", "output"):
        return None
    raise ValueError(f"Unknown physical symbol: {node.kind}")
