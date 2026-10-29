"""Merged catalog presets, fixed optical modules and portable export."""

import ast
from copy import deepcopy
from dataclasses import replace
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyOpticL.schematic import PathLengthConstraint, compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.model import document_from_dict
from PyOpticL.schematic.registry import SYMBOLS, parameter_values, select_preset
from PyOpticL.schematic.parts import part_spec
from PyOpticL.schematic.optimization import (
    OptimizationOptions,
    PackingBox,
    apply_optimization,
    beam_points,
    build_problem,
    optimize_layout,
    path_value_gradients,
)
from PyOpticL.schematic.topology import resolve_topology
from test_schematic import chain, branched, place_dichroic


def preset_document(kind, preset):
    if kind == "splitter":
        doc = branched()
        node = doc.nodes[2]
    elif SYMBOLS[kind].role == "source":
        doc = chain(kind, "lens", "output")
        node = doc.nodes[0]
    elif SYMBOLS[kind].role == "terminal":
        doc = chain("source", "mirror", kind)
        node = doc.nodes[-1]
    else:
        doc = chain("source", kind, "output")
        node = doc.nodes[1]
    select_preset(node, preset)
    if kind == "grating":
        doc.nodes[0].parameters["wavelength"] = 1550
    if kind == "dichroic":
        place_dichroic(doc)
    return doc, node


class CatalogPresetTests(unittest.TestCase):
    def test_catalog_examples_are_editable_and_match_generated_python(self):
        folder = Path(__file__).resolve().parents[1] / "Designs/schematics/catalog"
        for path in folder.glob("*.pyopticl-schematic.json"):
            document = load_schematic(path)
            compiled = compile_schematic(document)
            self.assertTrue(compiled.ok, compiled.diagnostics)
            self.assertEqual(
                compiled.source,
                path.with_name(path.name.removesuffix(".pyopticl-schematic.json") + ".py").read_text(),
            )

    def test_every_symbol_and_preset_compiles_without_importing_cad(self):
        for kind, symbol in SYMBOLS.items():
            for preset in symbol.presets:
                with self.subTest(kind=kind, preset=preset):
                    doc, node = preset_document(kind, preset)
                    compiled = compile_schematic(doc)
                    self.assertTrue(compiled.ok, compiled.diagnostics)
                    ast.parse(compiled.source)
                    spec = part_spec(doc, node, resolve_topology(doc))
                    if spec is not None and "catalog" in spec.modules:
                        self.assertIn("catalog_parts as catalog", compiled.source)
                    self.assertEqual(document_from_dict(doc.to_dict()).to_dict(), doc.to_dict())

    def test_mount_presets_set_sizes_and_validate_thickness(self):
        doc, node = preset_document("mirror", "MHV-25.4L-R")
        self.assertEqual(parameter_values(node)["diameter"], 25.4)
        for thickness in (2.9, 7.1):
            node.parameters["thickness"] = thickness
            self.assertFalse(compile_schematic(doc).ok)
        node.parameters["thickness"] = 5
        self.assertTrue(compile_schematic(doc).ok)
        select_preset(node, "POLARIS-K05VS2")
        self.assertEqual(parameter_values(node)["diameter"], 12.7)
        select_preset(node, "bare")
        self.assertEqual(node.parameters["thickness"], 5)
        self.assertTrue(compile_schematic(doc).ok)
        doc, node = preset_document("lens", "POLARIS-L1G")
        self.assertEqual(parameter_values(node)["diameter"], 25.4)
        self.assertEqual(
            dict(part_spec(doc, node, resolve_topology(doc)).after)["mount_offset"], (-1.0, 0, 0)
        )
        doc, node = preset_document("qwp", "FBR")
        spec = part_spec(doc, node, resolve_topology(doc))
        self.assertEqual(dict(spec.before)["retardance"], 0.25)
        node.parameters["thickness"] = 4.1
        self.assertFalse(compile_schematic(doc).ok)
        node.parameters["thickness"] = 4
        self.assertTrue(compile_schematic(doc).ok)

    def test_polarization_and_iris_parameters_reach_export(self):
        doc, node = preset_document("splitter", "displacement_pbs")
        doc.nodes[0].parameters["polarization_angle"] = 45
        node.parameters["ref_polarization"] = 0
        compiled = compile_schematic(doc)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        self.assertIn("polarization=linear_polarization(SOURCE['polarization_angle'])", compiled.source)
        self.assertEqual(parameter_values(node)["ref_polarization"], 0)
        self.assertNotIn("ref_ratio", parameter_values(node))
        doc, node = preset_document("iris", "alignment")
        self.assertNotIn("pinhole_diameter", parameter_values(node))
        node.parameters["aperture_diameter"] = 1.5
        self.assertIn("'aperture_diameter': 1.5", compile_schematic(doc).source)

    def test_old_applied_examples_preserve_snapshot_but_require_revalidation(self):
        folder = Path(__file__).resolve().parents[1] / "Designs/schematics/optimization"
        for path in folder.glob("*-after.pyopticl-schematic.json"):
            document=load_schematic(path)
            self.assertIsNotNone(document.optimized_layout)
            self.assertIsNotNone(document.layout)
            compiled=compile_schematic(document)
            self.assertFalse(compiled.ok)
            self.assertIn("stale", compiled.diagnostics[0].message.lower())

    def test_grating_direction_depends_on_wavelength_and_resolved_port(self):
        for incident in ("A", "B"):
            doc, node = preset_document("grating", "MK05S")
            if incident == "B":
                from PyOpticL.schematic import Endpoint

                doc.connections[0].b = Endpoint(node.id, "B")
                doc.connections[1].a = Endpoint(node.id, "A")
            for wavelength in (635, 1550):
                doc.nodes[0].parameters["wavelength"] = wavelength
                compiled = compile_schematic(doc)
                self.assertTrue(compiled.ok, compiled.diagnostics)
                angle = 49.9 + math.degrees(math.asin(wavelength * 0.001 - math.sin(math.radians(49.9))))
                if incident == "B":
                    angle = -angle
                self.assertAlmostEqual(compiled.geometry.headings[doc.connections[1].id], angle, places=7)
                problem = build_problem(
                    doc,
                    {node.id: 20},
                    PackingBox(-100, -100, 400, 400),
                    OptimizationOptions(starts=1, iterations=100),
                )
                result = optimize_layout(problem)
                self.assertEqual(result.status, "feasible", result.violations)
                self.assertAlmostEqual(result.problem.angles[0].turn, angle, places=7)
        doc, node = preset_document("grating", "MK05S")
        node.parameters["incidence_angle"] = 0
        self.assertIn("nonpropagating", compile_schematic(doc).diagnostics[0].message)
        node.parameters["incidence_angle"] = 49.9
        node.parameters["order"] = 1.0
        self.assertFalse(compile_schematic(doc).ok)


class RoofGeometryTests(unittest.TestCase):
    def test_coincident_parts_with_offsets_separate_deterministically(self):
        from PyOpticL.schematic.optimization import project_constraints

        doc = chain("source", "roof", "lens", "output")
        doc.nodes[0].physical.update(x=0, y=0)
        problem = build_problem(
            doc, {doc.nodes[1].id: 5, doc.nodes[2].id: 5}, PackingBox(-100, -100, 400, 400)
        )
        problem = replace(problem, angles=())
        initial = [[0.0, 0.0], [80.0, 0.0], [80.0, 0.0], [10.0, -12.7]]
        first, second = deepcopy(initial), deepcopy(initial)
        project_constraints(problem, first)
        project_constraints(problem, second)
        self.assertEqual(first, second)
        self.assertGreater(math.dist(first[1], first[2]), 1)
        self.assertEqual(first[0], [0, 0])
        self.assertTrue(all(math.isfinite(value) for point in first for value in point))

    def test_offset_height_path_lengths_and_reverse_entry(self):
        from PyOpticL.schematic import Endpoint

        for preset in SYMBOLS["roof"].presets:
            for reverse in (False, True):
                with self.subTest(preset=preset, reverse=reverse):
                    doc, node = preset_document("roof", preset)
                    if reverse:
                        doc.connections[0].b = Endpoint(node.id, "B")
                        doc.connections[1].a = Endpoint(node.id, "A")
                    doc.connections[0].length = 80
                    doc.path_constraints.append(
                        PathLengthConstraint("total", doc.nodes[0].id, doc.nodes[-1].id, 165.4)
                    )
                    compiled = compile_schematic(doc)
                    self.assertTrue(compiled.ok, compiled.diagnostics)
                    self.assertAlmostEqual(compiled.lengths[doc.connections[1].id], 60, places=6)
                    self.assertAlmostEqual(compiled.routed_lengths[doc.connections[1].id], 60, places=6)
                    self.assertAlmostEqual(compiled.path_lengths["total"], 165.4, places=6)
                    output = doc.nodes[-1]
                    if "vertical" in preset:
                        self.assertAlmostEqual(
                            compiled.geometry.heights[output.id], -12.7 if reverse else 12.7
                        )
                        self.assertAlmostEqual(compiled.geometry.positions[output.id][1], 0)
                        self.assertIn("HEIGHTS =", compiled.source)
                    else:
                        self.assertAlmostEqual(
                            compiled.geometry.positions[output.id][1], 12.7 if reverse else -12.7
                        )
                        self.assertNotIn("HEIGHTS =", compiled.source)
                    with TemporaryDirectory() as directory:
                        path = Path(directory) / "roof.json"
                        save_schematic(doc, path)
                        self.assertEqual(compile_schematic(load_schematic(path)).source, compiled.source)

    def test_offset_jacobian_contains_incoming_rotation_and_optimizer_respects_pins(self):
        doc, node = preset_document("roof", "horizontal")
        doc.nodes[0].physical.update(x=0, y=0, angle=0)
        node.physical.update(x=80, y=0)
        doc.nodes[-1].physical.update(x=20, y=-12.7, angle=180)
        doc.path_constraints.append(PathLengthConstraint("total", doc.nodes[0].id, doc.nodes[-1].id, 165.4))
        problem = build_problem(
            doc,
            {node.id: 25},
            PackingBox(-100, -100, 400, 400),
            OptimizationOptions(starts=1, iterations=100),
        )
        points = ((0.0, 0.0), (80.0, 0.0), (20.0, -12.7))
        value, indices, gradients = path_value_gradients(problem, points, problem.path_lengths[0])
        self.assertAlmostEqual(value, 165.4)
        self.assertAlmostEqual(dict(zip(indices, gradients))[1][1], 12.7 / 80, places=6)
        before = deepcopy(doc.to_dict())
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        self.assertEqual(doc.to_dict(), before)
        apply_optimization(doc, problem, result)
        self.assertTrue(compile_schematic(doc).ok)
        self.assertEqual(result.layout.positions[node.id], (80, 0))
        actual = beam_points(result.problem, result.positions)
        self.assertAlmostEqual(actual[1][0][1], -12.7, places=6)

    def test_free_roof_rotates_to_a_constrained_return_direction(self):
        doc, node = preset_document("roof", "horizontal")
        doc.nodes[0].physical.update(x=0, y=0)
        doc.nodes[-1].physical["angle"] = 135
        problem = build_problem(
            doc,
            {node.id: 20},
            PackingBox(-150, -150, 400, 400),
            OptimizationOptions(starts=1, iterations=500),
        )
        result = optimize_layout(problem)
        self.assertEqual(result.status, "feasible", result.violations)
        apply_optimization(doc, problem, result)
        compiled = compile_schematic(doc)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        self.assertAlmostEqual(compiled.geometry.headings[doc.connections[-1].id], 135, delta=1e-6)


if __name__ == "__main__":
    unittest.main()
