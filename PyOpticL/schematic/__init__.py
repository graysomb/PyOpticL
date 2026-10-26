"""FreeCAD-independent optical schematics. Import .editor only inside FreeCAD."""

from .compiler import Compilation, Diagnostic, compile_schematic, validate_schematic
from .model import Connection, Endpoint, History, Node, Schematic, load_schematic, save_schematic
from .topology import ResolvedConnection, ResolvedTopology, resolve_topology

__all__ = [
    "Compilation", "Connection", "Diagnostic", "Endpoint", "History", "Node", "Schematic",
    "compile_schematic", "validate_schematic", "load_schematic", "save_schematic",
    "ResolvedConnection", "ResolvedTopology", "resolve_topology",
]
