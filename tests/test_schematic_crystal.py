"""Portable crystal-holder presets and full-length rectangular aperture."""
import ast
import unittest

from PyOpticL.schematic import Endpoint, compile_schematic
from PyOpticL.schematic.model import document_from_dict
from PyOpticL.schematic.optic_geometry import element_spec, aperture_excess
from PyOpticL.schematic.parts import part_spec
from PyOpticL.schematic.registry import AXIS_ALIGNED_KINDS, select_preset
from PyOpticL.schematic.topology import resolve_topology
from test_schematic import chain


class CrystalSchematicTests(unittest.TestCase):
    def test_both_presets_compile_roundtrip_and_share_the_cad_definition(self):
        for preset in ('bracketed', 'bare'):
            for reverse in (False, True):
                document = chain('source', 'crystal', 'output')
                node = document.nodes[1]
                select_preset(node, preset)
                if reverse:
                    document.connections[0].b = Endpoint(node.id, 'B')
                    document.connections[1].a = Endpoint(node.id, 'A')
                compiled = compile_schematic(document)
                self.assertTrue(compiled.ok, compiled.diagnostics)
                ast.parse(compiled.source)
                self.assertIn(f'catalog.crystal(mounted={preset == "bracketed"})', compiled.source)
                self.assertEqual(document_from_dict(document.to_dict()).to_dict(), document.to_dict())
                spec = part_spec(document, node, resolve_topology(document))
                self.assertEqual(spec.modules, {'catalog'})
                self.assertEqual(compiled.geometry.headings[document.connections[-1].id], 0)
        self.assertIn('crystal', AXIS_ALIGNED_KINDS)

    def test_rectangular_aperture_checks_both_crystal_ends(self):
        spec = element_spec(chain('source', 'crystal', 'output').nodes[1])
        self.assertEqual(spec.size, (27.4, 4, 1))
        self.assertLess(aperture_excess(spec, (0, 0, 0), (1, 0, 0)), 0)
        self.assertLess(aperture_excess(spec, (0, 1.9, .4), (-1, 0, 0)), 0)
        self.assertGreater(aperture_excess(spec, (0, 0, .6), (1, 0, 0)), 0)
        # Center hit passes, but a 0.05-radian slope walks out of the 1 mm height.
        direction = (1, 0, .05)
        self.assertLess(aperture_excess(spec, (0, 0, 0)), 0)
        self.assertAlmostEqual(aperture_excess(spec, (0, 0, 0), direction), 13.7*.05-.5)
        self.assertGreater(aperture_excess(spec, (0, 0, 0), (0, 1, 0)), 0)


if __name__ == '__main__':
    unittest.main()
