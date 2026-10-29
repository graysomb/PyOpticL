"""Folded stretcher geometry, shared optics and independent editable exports."""
import importlib.util
from math import dist
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyOpticL.ray_math import dot, norm, sub, yaw
from PyOpticL.schematic import compile_schematic, load_schematic
from PyOpticL.schematic.registry import parameter_values
from PyOpticL.schematic.scene_layout import trace_scene
from PyOpticL.schematic.topology import resolve_topology

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "Designs/schematics/cpa-folded"
spec = importlib.util.spec_from_file_location(
    "cpa_folded_generator", FOLDER / "generate.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class FoldedCPATests(unittest.TestCase):
    def test_saved_routes_regenerate_without_changing_baseline_routes(self):
        before = {
            p.name: p.read_bytes()
            for p in (FOLDER.parent / "cpa").iterdir()
            if p.is_file()
        }
        with TemporaryDirectory() as directory:
            generator.generate(directory)
            for name, document in generator.documents().items():
                filename = name + ".pyopticl-schematic.json"
                saved = load_schematic(FOLDER / filename)
                self.assertEqual(
                    saved.to_dict(),
                    load_schematic(Path(directory) / filename).to_dict(),
                )
                compiled = compile_schematic(saved)
                self.assertTrue(compiled.ok, compiled.diagnostics)
                self.assertEqual(compiled.source, (FOLDER / (name + ".py")).read_text())
                if name != "stretcher":
                    original = load_schematic(FOLDER.parent / "cpa" / filename)
                    self.assertEqual(document.to_dict(), original.to_dict())
        self.assertEqual(
            before,
            {
                p.name: p.read_bytes()
                for p in (FOLDER.parent / "cpa").iterdir()
                if p.is_file()
            },
        )

    def test_one_grating_one_lens_and_two_upright_one_inch_mirrors(self):
        document = generator.stretcher()
        topology = resolve_topology(document)
        self.assertTrue(topology.ok, topology.diagnostics)
        for kind, ref in (("grating", "ST_G2"), ("lens", "ST_L2")):
            self.assertEqual(
                [n.reference for n in document.nodes if n.kind == kind], [ref]
            )
            visits = [p for p in topology.passes.values() if p.component_id == ref]
            self.assertEqual(len(visits), 4)
            self.assertTrue(all(not p.centered for p in visits))
        self.assertEqual(document.node("ST_L2").preset, "POLARIS-L1G")
        self.assertEqual(parameter_values(document.node("ST_L2"))["focal_length"], 500)
        for ref in ("ST_Fold", "ST_M1"):
            self.assertEqual(document.node(ref).preset, "POLARIS-K1VS2")
            self.assertEqual(parameter_values(document.node(ref))["diameter"], 25.4)
        self.assertEqual(document.node("ST_Pickoff").preset, "KM05DR")
        self.assertEqual(document.node("ST_Iris").preset, "VA100")
        poses = document.layout["poses"]
        self.assertAlmostEqual(dist(poses["ST_G2"][:3], poses["ST_L2"][:3]), 70)
        self.assertAlmostEqual(dist(poses["ST_L2"][:3], poses["ST_Fold"][:3]), 500)
        old = generator.baseline.stretcher().layout["poses"]
        for axis in range(3):
            self.assertAlmostEqual(
                poses["ST_Fold"][axis], (old["ST_G1"][axis] + old["ST_G2"][axis]) / 2
            )

    def test_upper_lower_lower_upper_lens_hits_and_complete_retrace(self):
        document = generator.stretcher()
        trace = trace_scene(document)
        self.assertTrue(trace.ok, trace.diagnostics)
        visits = trace.layout.visits
        ids = ("ST_L2", "ST_L2_lower", "ST_L2_lower_return", "ST_L2_return")
        for ref, height in zip(ids, (14.7, 10.7, 10.7, 14.7)):
            self.assertAlmostEqual(visits[ref].entry[2], height)
        for ref in ("ST_L2_lower", "ST_L2_return"):
            self.assertAlmostEqual(visits[ref].outputs["out"][2], 0, delta=1e-12)
        for ref in (
            "ST_G2",
            "ST_L2",
            "ST_Fold",
            "ST_L2_lower",
            "ST_G2_lower",
            "ST_Pickoff",
            "ST_Iris",
            "ST_HWP1",
            "ST_M2",
        ):
            a, b = visits[ref], visits[ref + "_return"]
            self.assertLess(norm(sub(a.entry, b.entry)), 1e-8)
            self.assertAlmostEqual(dot(a.incoming, b.outputs["out"]), -1, delta=1e-9)
        self.assertAlmostEqual(
            dot(visits["ST_M1"].incoming, visits["ST_M1"].outputs["out"]), -1
        )
        self.assertLess(
            norm(sub(visits["To_EDFA"].exit, visits["To_EDFA_return"].entry)), 1e-8
        )
        self.assertEqual(
            resolve_topology(document).passes["To_EDFA_return"].mode, "receive"
        )
        self.assertEqual(len(resolve_topology(document).order), 21)

    def test_offset_and_focal_length_are_editable_using_existing_lens_rule(self):
        for offset, focal in ((2, 400), (3, 500), (3.5, 600)):
            with self.subTest(offset=offset, focal=focal), patch.object(
                generator, "BEAM_OFFSET_MM", offset
            ), patch.object(generator, "FOCAL_LENGTH_MM", focal):
                document = generator.stretcher()
                compiled = compile_schematic(document)
                self.assertTrue(compiled.ok, compiled.diagnostics)
                visits = compiled.geometry.visits
                self.assertAlmostEqual(visits["ST_L2"].entry[2], 12.7 + offset)
                self.assertAlmostEqual(visits["ST_L2_lower"].entry[2], 12.7 - offset)
                poses = document.layout["poses"]
                self.assertAlmostEqual(
                    dist(poses["ST_L2"][:3], poses["ST_Fold"][:3]), focal
                )
                self.assertAlmostEqual(
                    dot(
                        visits["ST_L2_lower"].outputs["out"],
                        yaw((1, 0, 0), generator.baseline.T - 90),
                    ),
                    1,
                )

    def test_accidental_centering_rejects_the_off_axis_pass(self):
        document = generator.stretcher()
        document.optical_pass("ST_L2").centered = True
        self.assertFalse(compile_schematic(document).ok)


if __name__ == "__main__":
    unittest.main()
