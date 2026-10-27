"""Regenerate portable catalog examples; no FreeCAD imports are required."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from PyOpticL.schematic import (
    Connection,
    Endpoint,
    PathLengthConstraint,
    Schematic,
    compile_schematic,
    save_schematic,
)
from PyOpticL.schematic.registry import SYMBOLS, select_preset


def chain(title, selections):
    document = Schematic(title=title)
    for index, (kind, preset) in enumerate(selections):
        node = document.add_node(kind, (index * 180, 0))
        node.id = f"node-{index}"
        select_preset(node, preset)
        if index:
            previous = document.nodes[index - 1]
            document.connections.append(
                Connection(
                    f"beam-{index}",
                    Endpoint(previous.id, "beam" if SYMBOLS[previous.kind].role == "source" else "B"),
                    Endpoint(node.id, "beam" if SYMBOLS[kind].role == "terminal" else "A"),
                    length=80,
                )
            )
    return document


def main():
    folder = Path(__file__).parent
    lab = chain(
        "Lab mount presets",
        (
            ("fiber_source", "POLARIS-K05T6"),
            ("hwp", "ELL16"),
            ("mirror", "POLARIS-K1VS2"),
            ("lens", "POLARIS-L05G"),
            ("slit", "VA100"),
            ("fiber_output", "KA05TA"),
        ),
    )
    grating = chain(
        "Grating and alignment iris",
        (("source", "beam"), ("grating", "bare"), ("iris", "alignment"), ("output", "open")),
    )
    grating.nodes[0].parameters["wavelength"] = 1550
    roof = chain(
        "Roof return with total air-path constraint",
        (("source", "beam"), ("roof", "bare_horizontal"), ("output", "open")),
    )
    roof.connections[-1].length = None
    roof.path_constraints.append(PathLengthConstraint("total", "node-0", "node-2", 165.4))
    for name, document in (("lab-presets", lab), ("grating", grating), ("roof", roof)):
        from PyOpticL.schematic.scene_layout import initialize_layout
        initialize_layout(document)
        result = compile_schematic(document)
        if not result.ok:
            raise RuntimeError([diagnostic.message for diagnostic in result.diagnostics])
        save_schematic(document, folder / f"{name}.pyopticl-schematic.json")
        (folder / f"{name}.py").write_text(result.source)


if __name__ == "__main__":
    main()
