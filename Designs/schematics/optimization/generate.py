"""Reproduce before/after examples from the repository root.

    python Designs/schematics/optimization/generate.py
    QT_QPA_PLATFORM=offscreen python Designs/schematics/optimization/generate.py --render

Default bounds are analytical envelopes of the bare primitives in
PyOpticL/library/optics.py: Circular_Mirror (6 mm thick) and Beamsplitter_Cube.
They include the complete modeled parts because these presets have no mounts or
children. These bounds have NOT been evaluated by FreeCAD. --cad instead resolves
actual CAD bounds through BoundsProvider, and executes each exported build_layout
including its runtime check_trace, in isolated FreeCAD documents.

--render additionally exercises the real Qt dialog's Run and Apply buttons and
renders its physical preview alongside the unchanged schematic. It needs Qt,
but does not need FreeCAD unless --cad is also specified.
"""

from dataclasses import asdict
from copy import deepcopy
import argparse
import ast
import json
from math import atan2, cos, degrees, hypot, radians, sin, sqrt
from pathlib import Path
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from PyOpticL.bounds import BoundingCircleXY
from PyOpticL.schematic import (
    Connection,
    Endpoint,
    PathLengthConstraint,
    Schematic,
    compile_schematic,
    load_schematic,
    save_schematic,
)
from PyOpticL.schematic.bounds import BoundsProvider, resolve_layout_bounds
from PyOpticL.schematic.effective import effective_document
from PyOpticL.schematic.parts import folding_part_spec
from PyOpticL.schematic.paths import component_path, path_length
from PyOpticL.schematic.optimization import (
    OptimizationOptions,
    PackingBox,
    apply_optimization,
    build_problem,
    layout_violations,
    optimize_layout,
)
from PyOpticL.schematic.topology import resolve_topology

DESTINATION = Path(__file__).resolve().parent


def primitive_circle(spec):
    """Analytical shape-bounding-box corner radii; reject every other factory."""
    parameters = dict(spec.parameters)
    if spec.after:
        raise ValueError("Analytical example bounds only support bare parts")
    if spec.factory == "Circular_Mirror":
        return BoundingCircleXY(hypot(6.0, parameters["diameter"] / 2))
    if spec.factory == "Beamsplitter_Cube":
        return BoundingCircleXY(parameters["side_length"] / sqrt(2))
    raise ValueError(f"No analytical envelope provided for {spec.factory}")


def fixtures():
    def create(name):
        doc = Schematic(name)

        def node(kind, position, rotation=0):
            item = doc.add_node(kind, position)
            item.id = f"{name}-{item.reference}"
            item.rotation = rotation
            if kind == "mirror":
                item.preset = "bare"
            return item

        def beam(a, b, port="B", target="A", length=None):
            edge = Connection(
                f"{name}-{a.reference}-{b.reference}",
                Endpoint(a.id, port),
                Endpoint(b.id, target),
                length=length,
            )
            doc.connections.append(edge)
            return edge

        return doc, node, beam

    doc, node, beam = create("pinned-mirror")
    source = node("source", (-200, 0))
    mirror = node("mirror", (0, 0))
    output = node("output", (0, -160), -90)
    source.physical.update(x=0, y=0, angle=0)
    output.physical.update(x=80, y=40)
    beam(source, mirror, "beam", length=50)
    beam(mirror, output, target="beam")
    yield doc, PackingBox(-10, -10, 110, 52), OptimizationOptions()

    doc, node, beam = create("splitter-fold")
    source = node("source", (-320, 0))
    first = node("mirror", (0, 0))
    cube = node("splitter", (0, -160), -90)
    cube.physical["turn"] = 90  # Keep the cube's reflected branch at a right angle.
    transmitted = node("mirror", (0, -320), -90)
    output1 = node("output", (-160, -320), 180)
    reflected = node("mirror", (-160, -160), 180)
    output2 = node("output", (-160, -40), 90)
    source.physical.update(x=0, y=0, angle=0)
    beam(source, first, "beam", length=50)
    beam(first, cube, target="left")
    beam(cube, transmitted, "right")
    beam(transmitted, output1, target="beam")
    beam(cube, reflected, "top")
    beam(reflected, output2, target="beam")
    yield doc, PackingBox(-10, -10, 110, 85), OptimizationOptions()

    doc, node, beam = create("adaptive-multiple-folds")
    source = node("source", (-160, 0))
    output = node("output", (160, 0))
    source.physical.update(x=0, y=0, angle=0)
    output.physical.update(x=100, y=0)
    span = beam(source, output, "beam", "beam", length=100)
    span.allow_folding = True
    doc.path_constraints.append(PathLengthConstraint("long-path", source.id, output.id, 180))
    yield doc, PackingBox(-15, -15, 130, 110), OptimizationOptions(
        folding_preset="bare", starts=2, iterations=3000
    )

    doc, node, beam = create("adaptive-remove-fold")
    source = node("source", (-160, 0))
    mirror = node("mirror", (0, 0))
    mirror.mirror_role = "folding"
    output = node("output", (0, -160), -90)
    source.physical.update(x=0, y=0)
    output.physical.update(x=100, y=0)
    beam(source, mirror, "beam")
    beam(mirror, output, target="beam")
    doc.path_constraints.append(PathLengthConstraint("straight-path", source.id, output.id, 100))
    yield doc, PackingBox(-15, -30, 150, 100), OptimizationOptions(
        folding_preset="bare", starts=1, iterations=1500
    )

    doc, node, beam = create("adaptive-splitter-90")
    source = node("source", (-160, 0))
    cube = node("splitter", (0, 0))
    transmitted = node("output", (160, 0))
    reflected = node("output", (0, -160), -90)
    source.physical.update(x=0, y=0, angle=0)
    cube.physical.update(x=50, y=0, turn=90)
    transmitted.physical.update(x=150, y=0)
    reflected.physical.update(x=130, y=80)
    beam(source, cube, "beam", "left", length=50)
    beam(cube, transmitted, "right", "beam", length=100)
    span = beam(cube, reflected, "top", "beam")
    span.allow_folding = True
    doc.path_constraints.append(PathLengthConstraint("reflected-path", cube.id, reflected.id, 160))
    yield doc, PackingBox(-20, -20, 220, 150), OptimizationOptions(
        folding_preset="bare", starts=1, iterations=1800
    )


def verify_interfaces(document, positions):
    """Measure travel directions from coordinates, independently of solver turns."""
    topology = resolve_topology(document)
    incoming = {edge.target.node_id: edge for edge in topology.edges.values()}
    checks = []

    def direction(edge):
        a, b = positions[edge.source.node_id], positions[edge.target.node_id]
        return b[0] - a[0], b[1] - a[1]

    for node in document.nodes:
        if node.id not in incoming:
            continue
        ax, ay = direction(incoming[node.id])
        for edge in topology.outgoing[node.id]:
            bx, by = direction(edge)
            measured = degrees(atan2(ax * by - ay * bx, ax * bx + ay * by))
            reflecting = node.kind == "mirror" or edge.interaction == "reflected"
            expected = node.physical.get("turn") if reflecting else 0
            if expected is not None:
                delta = radians(measured - expected)
                error = abs(degrees(atan2(sin(delta), cos(delta))))
                assert error <= 1e-6, f"{node.reference}: expected {expected}°, measured {measured}°"
            checks.append(
                {
                    "reference": node.reference,
                    "connection_id": edge.id,
                    "constraint_deg": expected,
                    "measured_turn_deg": measured,
                }
            )
    return checks


def cad_trace(compiled):
    import FreeCAD as App

    previous = App.ActiveDocument.Name if App.ActiveDocument else None
    temporary = None
    try:
        temporary = App.newDocument("OptimizerExampleTrace")
        namespace = {"__name__": "optimizer_example"}
        exec(compile(compiled.source, "optimized_example.py", "exec"), namespace)
        namespace["build_layout"]()  # includes generated runtime check_trace
    finally:
        if temporary is not None:
            App.closeDocument(temporary.Name)
        App.setActiveDocument(previous or "")


def analytical_export_trace(document, syntax, assignments):
    """Check exported primitive normals and open lengths without solver headings.

    This follows the library's planar mirror/cube reflection law. It checks
    center-ray directions, not CAD surface intersections or body collisions.
    """
    cube_planes = {}
    for call in ast.walk(syntax):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "Component":
            keywords = {item.arg: item.value for item in call.keywords}
            definition = keywords["definition"]
            for keyword in definition.keywords:
                if keyword.arg == "rotate_cube":
                    cube_planes[ast.literal_eval(keywords["label"])] = ast.literal_eval(keyword.value)
    topology = resolve_topology(document)
    source = assignments["SOURCE"]
    positions = {topology.source_id: (source["x"], source["y"])}
    positions.update(
        {
            node.id: assignments["PLACEMENTS"][node.reference][:2]
            for node in document.nodes
            if node.reference in assignments["PLACEMENTS"]
        }
    )
    incoming = {topology.source_id: (cos(radians(source["angle"])), sin(radians(source["angle"])))}
    lengths = {}
    for node_id in topology.order:
        node = document.node(node_id)
        a, travel = positions[node_id], incoming[node_id]
        for edge in topology.outgoing[node_id]:
            outgoing = travel
            if node.kind == "mirror" or edge.interaction == "reflected":
                normal_angle = assignments["PLACEMENTS"][node.reference][2]
                if node.kind == "splitter":
                    normal_angle += 45 if cube_planes[node.reference] else -45
                normal = (cos(radians(normal_angle)), sin(radians(normal_angle)))
                dot = sum(u * v for u, v in zip(travel, normal))
                outgoing = tuple(u - 2 * dot * n for u, n in zip(travel, normal))
            target = document.node(edge.target.node_id)
            if target.kind == "output":
                distance = assignments["OPEN_LENGTHS"][(node.reference, edge.interaction)]
                positions[target.id] = tuple(v + distance * u for v, u in zip(a, outgoing))
            else:
                b = positions[target.id]
                delta = b[0] - a[0], b[1] - a[1]
                error = abs(
                    degrees(
                        atan2(
                            outgoing[0] * delta[1] - outgoing[1] * delta[0],
                            outgoing[0] * delta[0] + outgoing[1] * delta[1],
                        )
                    )
                )
                assert (
                    error <= 1e-6
                ), f"Exported normal at {node.reference} misses {target.reference} by {error}°"
            b = positions[target.id]
            lengths[edge.id] = hypot(b[0] - a[0], b[1] - a[1])
            incoming[target.id] = outgoing
    return positions, lengths


def render_and_exercise(before, problem, expected, provider, path, cad=False):
    """Actual production Qt renderers and worker, not an imitation of the GUI."""
    from PyOpticL.schematic.editor import SchematicEditor
    from PyOpticL.schematic.optimize_dialog import OptimizeLayoutDialog, PhysicalPreview
    from PyOpticL.schematic.qt import QtCore, QtGui, QtWidgets

    try:
        from PySide import QtTest
    except ImportError:
        try:
            from PySide6 import QtTest
        except ImportError:
            from PySide2 import QtTest

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    editor = SchematicEditor(deepcopy(before), bounds_provider=provider)
    editor.show()
    dialog = OptimizeLayoutDialog(editor.document, provider, editor)
    for key, value in asdict(problem.box).items():
        dialog.fields[key].setValue(value)
    dialog.show()
    app.processEvents()
    assert not dialog.apply_button.isEnabled()
    QtTest.QTest.mouseClick(dialog.run_button, QtCore.Qt.LeftButton)
    deadline = monotonic() + 90
    while dialog.worker is not None and monotonic() < deadline:
        app.processEvents()
        QtTest.QTest.qWait(5)
    if dialog.worker is not None:
        dialog.reject()
        while dialog.worker is not None:
            app.processEvents()
            QtTest.QTest.qWait(5)
        raise RuntimeError("GUI example exceeded its time budget")
    assert dialog.solution.status == "feasible", dialog.solution.violations
    assert dialog.solution.layout == expected.layout, "Worker and API differ"
    assert dialog.apply_button.isEnabled()
    dialog.grab().save(str(path.with_name(path.stem + "-dialog.png")))

    # Capture both schematic scenes separately to verify rendering is unchanged.
    def schematic_image():
        image = QtGui.QImage(420, 400, QtGui.QImage.Format_ARGB32)
        image.fill(QtGui.QColor("#ffffff"))
        painter = QtGui.QPainter(image)
        editor.scene.render(
            painter,
            QtCore.QRectF(10, 10, 400, 380),
            editor.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20),
        )
        painter.end()
        return image

    drawing_before = schematic_image()
    QtTest.QTest.mouseClick(dialog.apply_button, QtCore.Qt.LeftButton)
    assert dialog.result() == QtWidgets.QDialog.Accepted
    assert editor.apply_optimized_result(dialog.problem, dialog.solution)
    assert editor.history.index == 1
    assert schematic_image() == drawing_before
    assert compile_schematic(editor.document).ok
    editor.undo()
    assert editor.document.optimized_layout is None
    editor.redo()
    assert compile_schematic(editor.document).geometry == expected.layout

    # Same camera for before/after, including geometry outside the target box.
    previews = []
    for preview_problem, positions in (
        (problem, problem.initial_positions),
        (expected.problem, expected.positions),
    ):
        view = PhysicalPreview()
        view.show_layout(preview_problem, positions, layout_violations(preview_problem, positions))
        previews.append(view)
    camera = previews[0].scene().itemsBoundingRect().united(previews[1].scene().itemsBoundingRect())
    camera = camera.adjusted(-10, -10, 10, 10)
    image = QtGui.QImage(1350, 600, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor("#ffffff"))
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtGui.QColor("#163c54"))
    painter.setFont(QtGui.QFont("Arial", 20))
    painter.drawText(25, 35, before.title)
    painter.setFont(QtGui.QFont("Arial", 12))
    painter.drawText(
        25,
        65,
        "Actual editor renderers · "
        + (
            "CAD-derived bounds; trace status: verification.json"
            if cad
            else "analytical bare-part bounds · native CAD results: native-verification.json"
        ),
    )
    fixed_turns = [
        f"{node.reference}: {node.physical['turn']:+g}° constrained; actual {expected.layout.turns[node.id]:+.6f}°"
        for node in before.nodes
        if "turn" in node.physical
    ]
    if expected.problem.graph.edits:
        fixed_turns.append(
            "Added: "
            + (
                ", ".join(
                    node.reference
                    for node in expected.problem.nodes
                    if node.id in {item.id for item in expected.problem.graph.generated}
                )
                or "none"
            )
            + "; omitted: "
            + (", ".join(before.node(key).reference for key in expected.problem.graph.bypassed) or "none")
        )
    if fixed_turns:
        painter.drawText(25, 88, "; ".join(fixed_turns))
    for x, title in (
        (20, "Topological drawing — unchanged"),
        (460, "Physical before (mm)"),
        (900, "Physical after (mm)"),
    ):
        painter.drawText(x, 110, title)
    painter.drawImage(QtCore.QPointF(20, 130), drawing_before)
    for x, preview in zip((460, 900), previews):
        preview.scene().render(painter, QtCore.QRectF(x, 130, 420, 400), camera)
    painter.setFont(QtGui.QFont("Arial", 11))
    painter.drawText(
        25,
        560,
        f"Region: {problem.box.width:g} × {problem.box.height:g} mm. Clearance: 1 mm. Beam keep-out diameter: 1 mm.",
    )
    painter.drawText(
        25,
        585,
        "Red marks violations before optimization. Blue disks enclose physical parts; virtual endpoints have no disk.",
    )
    painter.end()
    assert image.save(str(path))
    editor.history.mark_saved()
    editor.close()
    dialog.close()
    app.processEvents()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", action="store_true")
    parser.add_argument(
        "--cad", action="store_true", help="Resolve real bounds and check exported traces; requires FreeCAD"
    )
    args = parser.parse_args()
    provider = BoundsProvider() if args.cad else BoundsProvider(primitive_circle)
    reports = []
    for document, box, options in fixtures():
        document.optimization = {"box": asdict(box), "options": asdict(options)}
        baseline = document.to_dict()
        radii, errors = resolve_layout_bounds(document, provider)
        assert not errors, errors
        folding_radius = None
        if any(edge.allow_folding for edge in document.connections):
            bounds = provider.get(folding_part_spec(options))
            assert bounds.circle is not None, bounds.error
            folding_radius = bounds.circle.radius_mm
        problem = build_problem(document, radii, box, options, folding_radius=folding_radius)
        before = compile_schematic(document)
        result = optimize_layout(problem)
        assert result.status == "feasible", result.violations
        assert result == optimize_layout(problem), "Seeded search is not repeatable"
        before_violations = layout_violations(problem, problem.initial_positions)
        assert before_violations, "Example should demonstrate a real violation"
        assert not layout_violations(result.problem, result.positions)
        save_schematic(document, DESTINATION / f"{document.title}-before.pyopticl-schematic.json")
        if before.ok:
            (DESTINATION / f"{document.title}-before.py").write_text(before.source)
        if args.render:
            render_and_exercise(
                document, problem, result, provider, DESTINATION / f"{document.title}.png", cad=args.cad
            )
        apply_optimization(document, problem, result)
        assert document.to_dict()["nodes"] == baseline["nodes"]
        assert document.to_dict()["connections"] == baseline["connections"]
        after = compile_schematic(document)
        assert after.ok, after.diagnostics
        syntax = ast.parse(after.source)
        assignments = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in syntax.body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        }
        physical = effective_document(document, result.layout.graph, options)
        interfaces = verify_interfaces(physical, result.layout.positions)
        # Independently trace exported normals, placements and open lengths.
        export_positions, exported_lengths = analytical_export_trace(physical, syntax, assignments)
        for node in physical.nodes:
            for axis, key in enumerate(("x", "y")):
                if key in node.physical:
                    assert abs(export_positions[node.id][axis] - node.physical[key]) <= 1e-6
        exported_interfaces = verify_interfaces(physical, export_positions)
        separation_checks = []
        for beam in document.connections:
            if beam.length is not None:
                a, b = export_positions[beam.a.node_id], export_positions[beam.b.node_id]
                separation = hypot(b[0] - a[0], b[1] - a[1])
                assert abs(separation - beam.length) <= 1e-6
                separation_checks.append(
                    {
                        "id": beam.id,
                        "target_mm": beam.length,
                        "exported_mm": separation,
                        "routed_mm": after.routed_lengths[beam.id],
                    }
                )
        path_checks = []
        for constraint in document.path_constraints:
            route = component_path(physical, constraint.component_a, constraint.component_b)
            exported_total = path_length(
                physical, constraint.component_a, constraint.component_b, exported_lengths
            )
            assert abs(exported_total - constraint.length_mm) <= 1e-6
            path_checks.append(
                {
                    "id": constraint.id,
                    "route": route,
                    "target_mm": constraint.length_mm,
                    "optimized_mm": after.path_lengths[constraint.id],
                    "exported_mm": exported_total,
                }
            )
        path = DESTINATION / f"{document.title}-after.pyopticl-schematic.json"
        save_schematic(document, path)
        assert compile_schematic(load_schematic(path)).source == after.source
        (DESTINATION / f"{document.title}-after.py").write_text(after.source)
        if args.cad:
            cad_trace(after)
        references = {node.id: node.reference for node in document.nodes + physical.nodes}
        report = {
            "example": document.title,
            "box_mm": asdict(box),
            "options": asdict(problem.options),
            "bounds_source": (
                "FreeCAD full assembly geometry"
                if args.cad
                else "analytical bare primitive shape bounding boxes (not evaluated in FreeCAD)"
            ),
            "radii_mm": {references[k]: v for k, v in radii.items()},
            "before_export_ok": before.ok,
            "before_diagnostics": [d.message for d in before.diagnostics],
            "before_violations": [asdict(v) for v in before_violations],
            "after_status": result.status,
            "after_violations": [asdict(v) for v in result.violations],
            "iterations": result.iterations,
            "starts": result.starts,
            "before_positions_mm": {
                node.reference: problem.initial_positions[i] for i, node in enumerate(problem.nodes)
            },
            "after_positions_mm": {references[k]: v for k, v in result.layout.positions.items()},
            "after_turns_deg": {references[k]: v for k, v in result.layout.turns.items()},
            "interface_angle_checks": interfaces,
            "exported_interface_angle_checks": exported_interfaces,
            "analytical_export_reflection_and_open_lengths_verified": True,
            "path_length_checks": path_checks,
            "beam_separation_checks": separation_checks,
            "original_beam_endpoint_separations_mm": after.lengths,
            "original_beam_routed_lengths_mm": after.routed_lengths,
            "added_mirrors": [references[mirror.id] for mirror in result.layout.graph.generated],
            "omitted_mirrors": [references[node_id] for node_id in result.layout.graph.bypassed],
            "retained_turning_mirrors": [
                node.reference
                for node in document.nodes
                if node.kind == "mirror"
                and node.mirror_role == "turning"
                and node.id in result.layout.positions
            ],
            "drawing_and_constraints_unchanged": True,
            "seeded_repeatability_verified": True,
            "save_load_export_verified": True,
            "qt_run_apply_undo_redo_verified": args.render,
            "freecad_runtime_trace_verified": args.cad,
        }
        reports.append(report)
        print(
            f"{document.title}: {len(before_violations)} → 0 violations; {result.iterations} iterations; export OK"
        )
    (DESTINATION / "verification.json").write_text(json.dumps(reports, indent=2) + "\n")


if __name__ == "__main__":
    main()
