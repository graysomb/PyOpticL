"""Editable CPA draft, shared compressor optics and explicit wavelength boundary."""
import importlib.util
from math import dist
from PyOpticL.ray_math import dot, yaw
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyOpticL.schematic import compile_schematic, load_schematic
from PyOpticL.schematic.registry import parameter_values
from PyOpticL.schematic.scene_layout import trace_scene
from PyOpticL.schematic.topology import resolve_topology

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "Designs/schematics/cpa"
spec = importlib.util.spec_from_file_location("cpa_generator", FOLDER / "generate.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class CPAStarterTests(unittest.TestCase):
    def test_saved_routes_regenerate_and_compile(self):
        with TemporaryDirectory() as directory:
            generator.generate(directory)
            for name in generator.documents():
                filename = name + ".pyopticl-schematic.json"
                original = load_schematic(FOLDER / filename)
                regenerated = load_schematic(Path(directory) / filename)
                self.assertEqual(original.to_dict(), regenerated.to_dict())
                compilation = compile_schematic(original)
                self.assertTrue(compilation.ok, compilation.diagnostics)
                self.assertEqual(
                    compilation.source, (FOLDER / (name + ".py")).read_text()
                )
                self.assertTrue(trace_scene(original).ok)

    def test_stretcher_lenses_are_500_mm_and_shg_lenses_remain_30_mm(self):
        lenses = [
            n
            for d in generator.documents().values()
            for n in d.nodes
            if n.kind == "lens"
        ]
        self.assertEqual(
            {n.reference for n in lenses}, {"ST_L1", "ST_L2", "SHG_L1", "SHG_L2"}
        )
        for n in lenses:
            stretcher = n.reference.startswith("ST_")
            expected = 500 if stretcher else 30
            self.assertEqual(parameter_values(n)["focal_length"], expected)
            self.assertEqual(parameter_values(n)["diameter"], 25.4 if stretcher else 12.7)
            self.assertEqual(n.preset, "POLARIS-L1G" if stretcher else "POLARIS-L05G")
        poses = generator.stretcher().layout["poses"]
        for first, second in (("ST_G1", "ST_L1"), ("ST_L2", "ST_G2")):
            self.assertAlmostEqual(dist(poses[first][:3], poses[second][:3]), 70, delta=1e-6)
        self.assertAlmostEqual(dist(poses["ST_L1"][:3], poses["ST_L2"][:3]), 1000, delta=1e-6)
        first = yaw((1, 0, 0), poses["ST_L1"][3])
        second = yaw((1, 0, 0), poses["ST_L2"][3])
        self.assertAlmostEqual(dot(first, second), -1, delta=1e-9)
        shg_in = generator.compressor().layout["poses"]["SHG_L1"]
        shg_out = generator.output775().layout["poses"]["SHG_L2"]
        self.assertAlmostEqual(
            dot(yaw((1, 0, 0), shg_in[3]), yaw((1, 0, 0), shg_out[3])), -1, delta=1e-9
        )

    def test_compressor_reuses_two_gratings_and_feeds_shg_without_lo_pickoff(self):
        document = generator.compressor()
        topology = resolve_topology(document)
        self.assertTrue(topology.ok, topology.diagnostics)
        self.assertEqual(len([n for n in document.nodes if n.kind == "grating"]), 2)
        poses = document.layout["poses"]
        self.assertAlmostEqual(dist(poses["CP_G1"][:3], poses["CP_G2"][:3]), 860, delta=1e-6)
        between = next(e for e in document.connections if e.a.node_id == "CP_G1" and e.b.node_id == "CP_G2")
        self.assertEqual(between.length, 860)
        visits = [
            v
            for v in topology.passes.values()
            if document.node(v.component_id).kind == "grating"
        ]
        self.assertEqual(len(visits), 4)
        self.assertEqual({v.component_id for v in visits}, {"CP_G1", "CP_G2"})
        self.assertTrue(all(not v.centered for v in visits if v.id.endswith("_return")))
        self.assertFalse({"LO_Pickoff", "Local_Oscillator"} & {n.id for n in document.nodes})
        self.assertTrue(all(len(edges) <= 1 for edges in topology.outgoing.values()))
        self.assertEqual([e.target.visit_id for e in topology.outgoing["CP_G1_return"]], ["CP_M2"])
        self.assertEqual(document.node("SHG_Crystal").preset, "bracketed")
        self.assertEqual(document.node("CP_M2").preset, "POLARIS-K05VS2")
        self.assertEqual(parameter_values(document.node("CP_M2"))["diameter"], 12.7)
        order = topology.order
        self.assertEqual(order[:3], ["From_EDFA", "CP_HWP1", "CP_M1"])
        for first, second in (("CP_M2", "SHG_HWP1"), ("SHG_HWP1", "SHG_L1")):
            self.assertEqual([e.target.visit_id for e in topology.outgoing[first]], [second])
        for ref in ("CP_HWP1", "SHG_HWP1"):
            self.assertEqual(document.node(ref).kind, "hwp")
            self.assertEqual(document.node(ref).preset, "FBR")

    def test_stretcher_retroreflects_through_shared_optics_to_launching_coupler(self):
        document = generator.stretcher()
        trace = trace_scene(document)
        self.assertTrue(trace.ok, trace.diagnostics)
        visits = trace.layout.visits
        mirror = visits["ST_M1"]
        self.assertEqual(document.node("ST_M1").preset, "POLARIS-K1VS2")
        self.assertEqual(parameter_values(document.node("ST_M1"))["diameter"], 25.4)
        for incoming, outgoing in zip(mirror.incoming, mirror.outputs["out"]):
            self.assertAlmostEqual(incoming, -outgoing, delta=1e-9)
        for ref in ("ST_Iris", "ST_G1", "ST_L1", "ST_L2", "ST_G2", "ST_HWP1", "ST_M2"):
            forward, returning = visits[ref], visits[ref + "_return"]
            for a, b in zip(forward.entry, returning.entry):
                self.assertAlmostEqual(a, b, delta=1e-6)
            for a, b in zip(forward.incoming, returning.outputs["out"]):
                self.assertAlmostEqual(a, -b, delta=1e-9)
        self.assertEqual(document.optical_pass("To_EDFA").mode, "emit")
        receiver = document.optical_pass("To_EDFA_return")
        self.assertEqual(receiver.mode, "receive")
        self.assertEqual(receiver.component_id, "To_EDFA")
        for a, b in zip(visits["To_EDFA"].exit, visits[receiver.id].entry):
            self.assertAlmostEqual(a, b, delta=1e-6)
        self.assertAlmostEqual(sum(trace.layout.lengths.values()), 3240, delta=1e-6)
        self.assertEqual(len([n for n in document.nodes if n.kind == "mirror"]), 2)
        topology = resolve_topology(document)
        self.assertEqual(topology.order[:4], ["To_EDFA", "ST_M2", "ST_HWP1", "ST_G2"])
        self.assertEqual(document.node("ST_HWP1").preset, "FBR")
        self.assertEqual([e.target.visit_id for e in topology.outgoing["ST_HWP1_return"]], ["ST_M2_return"])

    def test_external_interfaces_and_wavelength_boundary(self):
        docs = generator.documents()
        fibers = [
            n for d in docs.values() for n in d.nodes if n.kind.startswith("fiber_")
        ]
        self.assertEqual(len(fibers), 3)
        self.assertEqual({n.reference for n in fibers}, {"To_EDFA", "From_EDFA", "Residual_1550"})
        before = docs["compressor"].layout["poses"]["Crystal_1550_exit"][:3]
        after = docs["output-775"].layout["poses"]["SHG_775_boundary"][:3]
        self.assertEqual(before, after)
        self.assertEqual(
            parameter_values(docs["compressor"].node("From_EDFA"))["wavelength"], 1550
        )
        self.assertEqual(
            parameter_values(docs["output-775"].node("SHG_775_boundary"))["wavelength"],
            775,
        )

    def test_dichroic_reflects_775_and_transmits_1550_through_one_shared_pair(self):
        reflected, transmitted = generator.output775(), generator.residual1550()
        for ref in ("SHG_L2", "SHG_M1"):
            self.assertEqual(reflected.node(ref).parameters, transmitted.node(ref).parameters)
            self.assertEqual(reflected.node(ref).preset, transmitted.node(ref).preset)
            self.assertEqual(reflected.layout["poses"][ref], transmitted.layout["poses"][ref])
        self.assertEqual(reflected.node("SHG_M1").kind, "dichroic")
        first, second = trace_scene(reflected), trace_scene(transmitted)
        self.assertTrue(first.ok, first.diagnostics)
        self.assertTrue(second.ok, second.diagnostics)
        a, b = first.layout.visits["SHG_M1"], second.layout.visits["SHG_M1"]
        for actual, expected in zip(a.outputs["out"], (0, -1, 0)):
            self.assertAlmostEqual(actual, expected, delta=1e-9)
        for actual, expected in zip(b.outputs["out"], (-1, 0, 0)):
            self.assertAlmostEqual(actual, expected, delta=1e-9)
        self.assertEqual(a.internal_length, 0)
        self.assertAlmostEqual(b.internal_length, 3.401680257, delta=1e-6)
        self.assertAlmostEqual(b.exit[1] - b.entry[1], .9874269245, delta=1e-6)
        transmitted.node("SHG_M1").parameters.update(reflect_min=900, reflect_max=800)
        self.assertFalse(compile_schematic(transmitted).ok)

    def test_rear_1550_mirror_feeds_integral_lens_fiber_coupler(self):
        document = generator.residual1550()
        mirror, coupler = document.node("SHG_IR_M1"), document.node("Residual_1550")
        self.assertEqual(mirror.preset, "POLARIS-K05VS2")
        self.assertEqual(parameter_values(mirror)["diameter"], 12.7)
        self.assertEqual(coupler.kind, "fiber_output")
        self.assertEqual(coupler.preset, "POLARIS-K05T6")
        self.assertEqual([n.reference for n in document.nodes if n.kind == "lens"], ["SHG_L2"])
        topology = resolve_topology(document)
        self.assertEqual(topology.order, ["SHG_1550_boundary", "SHG_L2", "SHG_M1", "SHG_IR_M1", "Residual_1550"])
        trace = trace_scene(document)
        self.assertTrue(trace.ok, trace.diagnostics)
        self.assertAlmostEqual(trace.layout.lengths["e2"], generator.REAR_DICHROIC_TO_MIRROR_MM)
        self.assertAlmostEqual(trace.layout.lengths["e3"], generator.REAR_MIRROR_TO_COUPLER_MM)
        for actual, expected in zip(trace.layout.visits[mirror.id].outputs["out"], (0, -1, 0)):
            self.assertAlmostEqual(actual, expected, delta=1e-9)


if __name__ == "__main__":
    unittest.main()
