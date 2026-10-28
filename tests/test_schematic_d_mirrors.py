"""Purchased D mirrors: presets, clear semicircle, export and physical outline."""

from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import unittest

from PyOpticL.schematic import compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.optic_geometry import aperture_excess, element_spec
from PyOpticL.schematic.parts import part_spec
from PyOpticL.schematic.registry import D_MIRROR_PRESETS, d_mirror_geometry, parameter_values, select_preset
from PyOpticL.schematic.scene_layout import intersect, trace_scene
from PyOpticL.schematic.topology import resolve_topology
from test_schematic import chain
from test_schematic_editor import QT_AVAILABLE

if QT_AVAILABLE:
    from PyOpticL.schematic.editor import SchematicEditor
    from PyOpticL.schematic.qt import QtCore, QtWidgets
    from test_schematic_editor import QtTest


def d_mirror_scene(preset="KM05DR", edge_distance=1):
    document = chain("source", "mirror", "output")
    source, mirror, output = document.nodes
    select_preset(mirror, preset)
    mirror.parameters["edge_distance"] = edge_distance
    source.physical.update(x=0, y=0, angle=0)
    document.layout = {"poses": {
        source.id: [0, 0, 0, 0], mirror.id: [50, 0, 0, 135], output.id: [50, 50, 0, 0],
    }}
    return document


class DMirrorPresetTests(unittest.TestCase):
    def test_matching_mounted_and_bare_specs_export_and_round_trip(self):
        for preset, optic in D_MIRROR_PRESETS.items():
            with self.subTest(preset=preset):
                document = d_mirror_scene(preset, 2)
                mirror = document.nodes[1]
                self.assertTrue(trace_scene(document).ok)
                spec = part_spec(document, mirror, resolve_topology(document))
                self.assertEqual(spec.factory, "d_mirror")
                self.assertEqual(dict(spec.before), {
                    "optic": optic, "mount": None if preset == optic else preset,
                })
                self.assertEqual(dict(spec.parameters)["edge_distance"], 2)
                compiled = compile_schematic(document)
                self.assertTrue(compiled.ok, compiled.diagnostics)
                self.assertIn("catalog.d_mirror(", compiled.source)
                with TemporaryDirectory() as folder:
                    path = Path(folder) / "d-mirror.json"
                    save_schematic(document, path)
                    restored = load_schematic(path)
                    self.assertEqual(restored.to_dict(), document.to_dict())
                    self.assertEqual(compile_schematic(restored).source, compiled.source)

    def test_purchased_dimensions_and_valid_datum_range_are_enforced(self):
        for preset in D_MIRROR_PRESETS:
            with self.subTest(preset=preset):
                document = d_mirror_scene(preset)
                mirror = document.nodes[1]
                geometry = d_mirror_geometry(preset)
                self.assertEqual(parameter_values(mirror)["diameter"], 2 * geometry["radius_mm"])
                self.assertEqual(parameter_values(mirror)["thickness"], 6)
                for name, value in (("diameter", 20), ("thickness", 3),
                                    ("edge_distance", .1),
                                    ("edge_distance", geometry["clear_radius_mm"])):
                    old = mirror.parameters.get(name)
                    mirror.parameters[name] = value
                    self.assertFalse(compile_schematic(document).ok, (name, value))
                    if old is None:
                        mirror.parameters.pop(name)
                    else:
                        mirror.parameters[name] = old
                select_preset(mirror, "bare")
                self.assertNotIn("edge_distance", parameter_values(mirror))
                self.assertTrue(compile_schematic(document).ok)

    def test_clear_semicircle_bevel_and_open_side_use_optical_datum(self):
        for preset in D_MIRROR_PRESETS:
            for edge in (.5, 2):
                with self.subTest(preset=preset, edge=edge):
                    document = d_mirror_scene(preset, edge)
                    mirror = document.nodes[1]
                    spec = element_spec(mirror)
                    radius = d_mirror_geometry(preset)["clear_radius_mm"]
                    self.assertLess(aperture_excess(spec, (0, 0, 0)), 0)
                    self.assertLess(aperture_excess(spec, (0, 0, edge - .2)), 0)
                    for local in ((0, 0, edge + .5), (0, 0, edge - .05),
                                  (0, radius, 0), (0, 0, edge - radius - .1)):
                        self.assertGreater(aperture_excess(spec, local), 0, local)
                    # A beam above the cut edge passes this optic rather than
                    # becoming an unintended circular-mirror interception.
                    self.assertIsNone(intersect(document, mirror, [0, 0, 0, 0],
                                                (10, 0, edge + .5), (-1, 0, 0),
                                                resolve_topology(document), finite=True))
                    # The bevel and outer annulus still block other beams.
                    for y, z in ((0, edge - .05), (radius + .05, edge - .2)):
                        self.assertIsNotNone(intersect(document, mirror, [0, 0, 0, 0],
                                                       (10, y, z), (-1, 0, 0),
                                                       resolve_topology(document), finite=True))


@unittest.skipUnless(QT_AVAILABLE, "Qt runtime not installed")
class DMirrorEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def settle(self):
        deadline = monotonic() + 15
        while self.editor.workers and monotonic() < deadline:
            self.app.processEvents()
            QtTest.QTest.qWait(5)
        self.app.processEvents()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.assertFalse(self.editor.workers)

    def tearDown(self):
        self.settle()
        self.editor.history.mark_saved()
        self.editor.close()
        self.app.processEvents()

    def test_inspector_selects_pairs_locks_sizes_and_draws_half_height_body(self):
        self.editor = SchematicEditor(d_mirror_scene())
        self.editor.show()
        self.settle()
        mirror = self.editor.document.nodes[1]
        self.editor.scene.symbols[mirror.id].setSelected(True)
        self.settle()
        for preset in D_MIRROR_PRESETS:
            combo = self.editor.findChild(QtWidgets.QComboBox, "partPreset")
            index = combo.findData(preset)
            self.assertGreaterEqual(index, 0)
            self.assertIn("D-shaped", combo.itemText(index))
            combo.setCurrentIndex(index)
            self.settle()
            for name in ("diameter", "thickness"):
                field = self.editor.findChild(QtWidgets.QDoubleSpinBox, "componentParameter_" + name)
                self.assertFalse(field.isEnabled())
            edge = self.editor.findChild(QtWidgets.QDoubleSpinBox, "componentParameter_edge_distance")
            edge.setValue(2)
            self.settle()
            self.assertEqual(parameter_values(self.editor.document.node(mirror.id))["edge_distance"], 2)
            self.assertTrue(self.editor.display_trace.ok)
            self.editor.projection_choice.setCurrentText("XZ")
            self.settle()
            body = self.editor.scene.symbols[mirror.id].outline.boundingRect()
            radius = d_mirror_geometry(preset)["radius_mm"]
            self.assertAlmostEqual(body.height(), radius)
            self.assertAlmostEqual(body.top(), -2)
            self.assertAlmostEqual(body.bottom(), radius - 2)
            self.editor.projection_choice.setCurrentText("XY")
            self.settle()


if __name__ == "__main__":
    unittest.main()
