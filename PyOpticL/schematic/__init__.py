"""FreeCAD-independent optical schematics. Import .editor only inside FreeCAD."""

from .compiler import Compilation, Diagnostic, compile_schematic, validate_schematic
from .model import Connection, Endpoint, History, Node, Schematic, load_schematic, save_schematic
from .physical import PhysicalLayout, physical_layout
from .optimization import (OptimizationOptions, OptimizationProblem, OptimizationResult,
                           PackingBox, Violation, apply_optimization, build_problem, optimize_layout)
from .topology import ResolvedConnection, ResolvedTopology, resolve_topology

__all__ = [
    "Compilation", "Connection", "Diagnostic", "Endpoint", "History", "Node", "Schematic",
    "compile_schematic", "validate_schematic", "load_schematic", "save_schematic",
    "PhysicalLayout", "physical_layout", "PackingBox", "OptimizationOptions",
    "OptimizationProblem", "OptimizationResult", "Violation", "build_problem", "optimize_layout", "apply_optimization",
    "ResolvedConnection", "ResolvedTopology", "resolve_topology",
]
