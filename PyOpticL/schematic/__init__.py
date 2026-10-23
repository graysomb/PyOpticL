"""FreeCAD-independent optical schematics. Import .editor only inside FreeCAD."""

from .compiler import Compilation, Diagnostic, compile_schematic, validate_schematic
from .model import Connection, History, Node, Schematic, load_schematic, save_schematic

__all__ = [
    "Compilation", "Connection", "Diagnostic", "History", "Node", "Schematic",
    "compile_schematic", "validate_schematic", "load_schematic", "save_schematic",
]
