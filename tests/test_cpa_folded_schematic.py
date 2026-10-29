"""Folded CPA geometry, shared optics and independent editable exports."""
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
                if name in ("output-775", "residual-1550"):
                    original = load_schematic(FOLDER.parent / "cpa" / filename)
                    for pose in original.layout["poses"].values():
                        pose[2] -= 2.825
                    original.layout["poses"]["SHG_L2"][0] = 70
                    original.connections[0].length = 16.3
                    if name == "residual-1550":
                        original = generator.add_rear_pickoff(original)
                    self.assertEqual(document.to_dict(), original.to_dict())
        self.assertEqual(
            before,
            {
                p.name: p.read_bytes()
                for p in (FOLDER.parent / "cpa").iterdir()
                if p.is_file()
            },
        )

    def test_shg_spacing_is_sixty_mm_with_the_crystal_at_the_midpoint(self):
        documents = generator.documents()
        constraint = generator.validate_shg_spacing(documents)
        self.assertEqual(constraint["lens_spacing_mm"], 60)
        self.assertEqual(constraint["lens_to_crystal_center_mm"], [30, 30])
        self.assertEqual(constraint["crystal_center_mm"], [100, -220, 9.875])
        for name in ("compressor", "output-775", "residual-1550"):
            document = documents[name]
            expected = 30 if name == "compressor" else 16.3
            constrained = [
                edge for edge in document.connections if edge.length is not None
                and edge.b.node_id in ("SHG_Crystal", "SHG_L2")
            ]
            self.assertEqual(len(constrained), 1)
            self.assertAlmostEqual(constrained[0].length, expected)
            ref = "SHG_L1" if name == "compressor" else "SHG_L2"
            document.layout["poses"][ref][0] += 1
            self.assertFalse(compile_schematic(document).ok)
            with self.assertRaisesRegex(ValueError, "SHG"):
                generator.validate_shg_spacing(documents)
            document.layout["poses"][ref][0] -= 1
        documents["compressor"].layout["poses"]["SHG_Crystal"][0] += 0.5
        self.assertFalse(compile_schematic(documents["compressor"]).ok)
        with self.assertRaisesRegex(ValueError, "midpoint"):
            generator.validate_shg_spacing(documents)

    def test_rear_waveplate_and_pbs_feed_coupler_and_separate_pickoff(self):
        document = generator.documents()["residual-1550"]
        compiled = compile_schematic(document)
        self.assertTrue(compiled.ok, compiled.diagnostics)
        visits = compiled.geometry.visits
        self.assertEqual(document.node("SHG_IR_HWP1").preset, "FBR")
        self.assertEqual(document.node("SHG_IR_PBS1").preset, "displacement_pbs")
        self.assertEqual(parameter_values(document.node("SHG_IR_HWP1"))["fast_axis_angle"], 22.5)
        self.assertEqual(set(visits["SHG_IR_PBS1"].outputs), {"transmitted", "reflected"})
        self.assertLess(norm(sub(visits["SHG_IR_PBS1"].outputs["transmitted"], (0,-1,0))), 1e-8)
        self.assertLess(norm(sub(visits["SHG_IR_PBS1"].outputs["reflected"], (1,0,0))), 1e-8)
        poses = document.layout["poses"]
        for a, b, spacing in (("SHG_IR_M1", "SHG_IR_HWP1", 30),
                              ("SHG_IR_HWP1", "SHG_IR_PBS1", 30),
                              ("SHG_IR_PBS1", "Residual_1550", 60)):
            self.assertAlmostEqual(dist(poses[a][:3], poses[b][:3]), spacing)
        self.assertAlmostEqual(dist(visits["SHG_IR_PBS1"].exit,
                                    visits["Pickoff_1550"].entry), 100)
        with patch.object(generator, "REAR_HWP_ANGLE_DEG", 10), patch.object(
            generator, "REAR_PBS_TO_COUPLER_MM", 50
        ):
            edited = generator.documents()["residual-1550"]
            self.assertTrue(compile_schematic(edited).ok)
            self.assertEqual(parameter_values(edited.node("SHG_IR_HWP1"))["fast_axis_angle"], 10)
            self.assertAlmostEqual(dist(edited.layout["poses"]["SHG_IR_PBS1"][:3],
                                        edited.layout["poses"]["Residual_1550"][:3]), 50)

    def test_one_grating_one_lens_and_three_upright_one_inch_mirrors(self):
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
        for ref in ("ST_Bend", "ST_Fold", "ST_M1"):
            self.assertEqual(document.node(ref).preset, "POLARIS-K1VS2")
            self.assertEqual(parameter_values(document.node(ref))["diameter"], 25.4)
        self.assertEqual(document.node("ST_Pickoff").preset, "KM05DR")
        self.assertEqual(document.node("ST_Iris").preset, "VA100")
        poses = document.layout["poses"]
        self.assertAlmostEqual(dist(poses["ST_G2"][:3], poses["ST_L2"][:3]), 70)
        self.assertAlmostEqual(dist(poses["ST_L2"][:3], poses["ST_Bend"][:3]), 325)
        self.assertAlmostEqual(dist(poses["ST_Bend"][:3], poses["ST_Fold"][:3]), 175)
        self.assertAlmostEqual(
            dot(
                sub(poses["ST_Bend"][:3], poses["ST_L2"][:3]),
                sub(poses["ST_Fold"][:3], poses["ST_Bend"][:3]),
            ),
            0,
        )
        bends = [p for p in topology.passes.values() if p.component_id == "ST_Bend"]
        self.assertEqual(len(bends), 4)
        self.assertTrue(all(not p.centered for p in bends))
        compressor = generator.compressor().layout["poses"]
        self.assertAlmostEqual(poses["To_EDFA"][1], compressor["From_EDFA"][1])
        self.assertAlmostEqual(poses["To_EDFA"][0] - compressor["From_EDFA"][0], 270)
        self.assertEqual(poses["ST_G2"][:2], [950, -75])

    def test_upper_lower_lower_upper_lens_hits_and_complete_retrace(self):
        document = generator.stretcher()
        trace = trace_scene(document)
        self.assertTrue(trace.ok, trace.diagnostics)
        visits = trace.layout.visits
        ids = ("ST_L2", "ST_L2_lower", "ST_L2_lower_return", "ST_L2_return")
        for ref, height in zip(ids, (15.525, 9.875, 9.875, 15.525)):
            self.assertAlmostEqual(visits[ref].entry[2], height)
        for ref in ("ST_L2_lower", "ST_L2_return"):
            self.assertAlmostEqual(visits[ref].outputs["out"][2], 0, delta=1e-12)
        for ref in (
            "ST_G2",
            "ST_L2",
            "ST_Bend",
            "ST_Bend_lower",
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
        self.assertEqual(len(resolve_topology(document).order), 25)
        # Captured before adding the extra mirror: preserve the finite chief
        # ray length, including slopes, rather than just nominal axial spans.
        self.assertAlmostEqual(sum(trace.layout.lengths.values()), 3540.031922245243)

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
                    dist(poses["ST_L2"][:3], poses["ST_Bend"][:3])
                    + dist(poses["ST_Bend"][:3], poses["ST_Fold"][:3]),
                    focal,
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

    def test_bend_position_and_direction_preserve_the_complete_optical_length(self):
        for distance, angle in ((225, 90), (325, 90), (375, -90)):
            with self.subTest(distance=distance, angle=angle), patch.object(
                generator, "STRETCHER_LENS_TO_BEND_MM", distance
            ), patch.object(generator, "STRETCHER_BEND_ANGLE_DEG", angle):
                trace = trace_scene(generator.stretcher())
                self.assertTrue(trace.ok, trace.diagnostics)
                self.assertAlmostEqual(
                    sum(trace.layout.lengths.values()), 3540.031922245243
                )
        for distance in (0, generator.FOCAL_LENGTH_MM):
            with patch.object(generator, "STRETCHER_LENS_TO_BEND_MM", distance):
                with self.assertRaisesRegex(
                    ValueError, "between the lens and end mirror"
                ):
                    generator.stretcher()

    def test_compressor_shared_hardware_and_ordered_four_passes(self):
        document = generator.compressor()
        topology = resolve_topology(document)
        self.assertTrue(topology.ok, topology.diagnostics)
        self.assertEqual(
            [n.id for n in document.nodes if n.kind == "grating"], ["CP_G1"]
        )
        self.assertEqual(
            {n.id for n in document.nodes if n.kind == "roof"}, {"CP_HRoof", "CP_VRoof"}
        )
        self.assertFalse({"CP_G2", "CP_Roof", "CP_M2"} & {n.id for n in document.nodes})
        self.assertEqual(
            topology.order,
            [
                "From_EDFA",
                "CP_HWP1",
                "CP_M1",
                "CP_G1",
                "CP_HRoof",
                "CP_G1_2",
                "CP_VRoof",
                "CP_G1_3",
                "CP_HRoof_return",
                "CP_G1_4",
                "CP_Pickoff",
                "SHG_HWP1",
                "SHG_L1",
                "SHG_Crystal",
                "Crystal_1550_exit",
            ],
        )
        self.assertEqual(topology.incident_ports["CP_HRoof"], "B")
        self.assertEqual(topology.incident_ports["CP_HRoof_return"], "A")
        self.assertEqual(topology.incident_ports["CP_VRoof"], "B")
        self.assertEqual(document.node("CP_Pickoff").preset, "KM05DL")
        self.assertEqual(document.node("CP_M1").preset, "POLARIS-K05VS2")
        self.assertTrue(topology.passes["CP_M1"].centered)
        self.assertFalse(topology.passes["CP_VRoof"].centered)
        self.assertEqual(
            parameter_values(document.node("CP_HRoof"))["beam_separation"],
            9.538700742686107,
        )
        self.assertEqual(
            parameter_values(document.node("CP_VRoof"))["beam_separation"], 5.65
        )

    def test_compressor_roof_offsets_four_spots_and_output_height(self):
        document = generator.compressor()
        trace = trace_scene(document)
        self.assertTrue(trace.ok, trace.diagnostics)
        visits = trace.layout.visits
        spots = [visits[v].entry for v in ("CP_G1", "CP_G1_2", "CP_G1_3", "CP_G1_4")]
        for point, height in zip(spots, (15.525, 15.525, 9.875, 9.875)):
            self.assertAlmostEqual(point[2], height)
        for a, b in ((spots[0], spots[3]), (spots[1], spots[2])):
            self.assertLess(norm(sub(a[:2], b[:2])), 1e-8)
        center = document.layout["poses"]["CP_G1"]
        for axis in (0, 1):
            self.assertAlmostEqual((spots[0][axis] + spots[1][axis]) / 2, center[axis])
        # Geometric targets are independent of the roof-separation parameter.
        self.assertAlmostEqual(dist(spots[0], spots[1]), 15.4)
        for point in spots:
            self.assertAlmostEqual(dist(point[:2], center[:2]), 7.7)
            self.assertAlmostEqual(abs(point[2] - center[2]), 2.825)
        stretcher = trace_scene(generator.stretcher())
        self.assertTrue(stretcher.ok, stretcher.diagnostics)
        for lens_pass, point in (("ST_L2", spots[0]), ("ST_L2_lower", spots[2])):
            self.assertAlmostEqual(
                stretcher.layout.visits[lens_pass].entry[2], point[2]
            )
        horizontal = yaw((0, -1, 0), document.layout["poses"]["CP_HRoof"][3])
        for ref, expected in (
            ("CP_HRoof", -9.538700742686107),
            ("CP_HRoof_return", 9.538700742686107),
        ):
            state = visits[ref]
            self.assertAlmostEqual(
                dot(sub(state.exit, state.entry), horizontal), expected
            )
            self.assertAlmostEqual(state.internal_length, 25.4)
        vertical = visits["CP_VRoof"]
        self.assertAlmostEqual(vertical.exit[2] - vertical.entry[2], -5.65)
        self.assertAlmostEqual(visits["Crystal_1550_exit"].entry[2], 9.875)
        poses = document.layout["poses"]
        self.assertAlmostEqual(norm(sub(poses["CP_HRoof"][:2], spots[0][:2])), 417.3)
        self.assertEqual(poses["From_EDFA"][1], -300)
        self.assertEqual(poses["CP_VRoof"][1], -100)
        self.assertAlmostEqual(poses["CP_VRoof"][0], vertical.entry[0] - 5)
        for actual, expected in zip(poses["CP_M1"][:3], (320, -300, 15.525)):
            self.assertAlmostEqual(actual, expected)
        for ref, point in (
            ("CP_M1", (320, -300, 15.525)),
            ("CP_Pickoff", (320, -220, 9.875)),
        ):
            for actual, expected in zip(visits[ref].entry, point):
                self.assertAlmostEqual(actual, expected)

    def test_compressor_and_both_output_wavelengths_share_lower_shg_boundary(self):
        docs = generator.documents()
        before = docs["compressor"].layout["poses"]["Crystal_1550_exit"][:3]
        for name, source in (
            ("output-775", "SHG_775_boundary"),
            ("residual-1550", "SHG_1550_boundary"),
        ):
            document = docs[name]
            self.assertEqual(document.layout["poses"][source][:3], before)
            self.assertTrue(
                all(abs(p[2] - 9.875) < 1e-8 for p in document.layout["poses"].values())
            )
        for ref in ("SHG_L2", "SHG_M1"):
            self.assertEqual(
                docs["output-775"].layout["poses"][ref],
                docs["residual-1550"].layout["poses"][ref],
            )

    def test_shared_roof_wrong_port_and_tilt_are_still_rejected(self):
        document = generator.compressor()
        for edge in document.connections:
            for endpoint in ("a", "b"):
                value = getattr(edge, endpoint)
                if value.visit_id == "CP_HRoof_return":
                    from PyOpticL.schematic import Endpoint

                    setattr(
                        edge,
                        endpoint,
                        Endpoint(
                            value.node_id,
                            "A" if value.port_id == "B" else "B",
                            value.pass_id,
                        ),
                    )
        self.assertFalse(compile_schematic(document).ok)
        document = generator.compressor()
        document.layout["poses"]["CP_HRoof"][3] += 1
        self.assertFalse(compile_schematic(document).ok)


if __name__ == "__main__":
    unittest.main()
