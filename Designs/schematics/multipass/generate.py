"""Reproduce the shared-optic scenes and numerical folding verification.

Use --render with PySide6/PySide2 to capture the real schematic editor.
The fixtures come from the portable regression tests. No CAD cache is needed;
packing radii in the folding example are explicitly analytical fixture values.
"""

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from test_schematic_multipass import double_pass
from test_schematic_scene_optimization import folding_scene, splitter_fold_scene
from PyOpticL.schematic import compile_schematic, save_schematic
from PyOpticL.schematic.optimization import (
    OptimizationOptions,
    PackingBox,
    build_problem,
    optimize_layout,
    apply_optimization,
)
from PyOpticL.schematic.scene_layout import trace_scene


def render(doc, path):
    from PyOpticL.schematic.qt import QtCore, QtWidgets
    from PyOpticL.schematic.editor import SchematicEditor
    from PyOpticL.schematic.bounds import BoundsProvider

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    editor = SchematicEditor(doc, bounds_provider=BoundsProvider(lambda spec: None))
    editor.resize(1400, 850)
    editor.show()
    deadline = time.monotonic() + 15
    while editor.workers and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    editor.fit()
    app.processEvents()
    editor.grab().save(str(path))
    editor.history.mark_saved()
    editor.close()
    app.processEvents()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--render", action="store_true")
    args = args.parse_args()
    folder = Path(__file__).parent
    report = {
        "bounds": "Analytical 9 mm generated-mirror fixture disks; no vendor CAD resolution.",
        "examples": {},
    }
    for name, vertical in (("shared-horizontal", False), ("shared-vertical", True)):
        doc = double_pass(vertical)
        save_schematic(doc, folder / (name + ".pyopticl-schematic.json"))
        compiled = compile_schematic(doc)
        if not compiled.ok:
            raise RuntimeError(compiled.diagnostics)
        (folder / (name + ".py")).write_text(compiled.source)
        report["examples"][name] = {
            "parts": len(doc.nodes),
            "passes": len(doc.optical_passes()),
            "native_like_trace_valid": trace_scene(doc).ok,
            "roof_internal_air_length_mm": compiled.geometry.internal_lengths["part-3"],
        }
        if args.render:
            render(doc, folder / (name + ".png"))
    splitter = splitter_fold_scene()
    save_schematic(splitter, folder / "splitter-fold.pyopticl-schematic.json")
    compiled = compile_schematic(splitter)
    (folder / "splitter-fold.py").write_text(compiled.source)
    report["examples"]["splitter-fold"] = {
        "constrained_reflected_turn_deg": compiled.geometry.turns["adaptive-splitter-90-BS1"],
        "generated_mirrors": len(compiled.geometry.graph.generated),
    }
    if args.render:
        render(splitter, folder / "splitter-fold.png")
    before = folding_scene()
    save_schematic(before, folder / "folding-before.pyopticl-schematic.json")
    problem = build_problem(
        before,
        {},
        PackingBox(0, 0, 100, 100),
        OptimizationOptions(
            starts=1, iterations=2400, projection_passes=5, folding_preset="bare", max_added_mirrors=2
        ),
        folding_radius=9,
    )
    result = optimize_layout(problem)
    if result.status != "feasible":
        raise RuntimeError(result.violations)
    after = folding_scene()
    apply_optimization(after, problem, result)
    save_schematic(after, folder / "folding-after.pyopticl-schematic.json")
    compiled = compile_schematic(after)
    if not compiled.ok:
        raise RuntimeError(compiled.diagnostics)
    (folder / "folding-after.py").write_text(compiled.source)
    report["examples"]["folding"] = {
        "status": result.status,
        "iterations": result.iterations,
        "generated_mirrors": len(result.layout.graph.generated),
        "endpoint_separation_mm": 60,
        "measured_routed_length_mm": sum(result.layout.lengths.values()),
        "path_target_mm": 180,
        "violations": len(result.violations),
        "unchanged_hard_constraints": before.connections == after.connections
        and [n.physical for n in before.nodes] == [n.physical for n in after.nodes],
    }
    if args.render:
        render(before, folder / "folding-before.png")
        render(after, folder / "folding-after.png")
    (folder / "verification.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
