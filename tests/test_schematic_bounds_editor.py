"""Qt behaviour for physical circles; fake geometry keeps tests CAD-independent."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from PyOpticL.bounds import BoundingCircleXY, BoundsUnavailable
from PyOpticL.schematic import compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.bounds import BoundsProvider
from test_schematic import chain
from test_schematic_editor import QT_AVAILABLE

if QT_AVAILABLE:
    from PyOpticL.schematic.editor import LegacySchematicEditor as SchematicEditor
    from PyOpticL.schematic.qt import QtCore, QtWidgets
    from test_schematic_editor import QtTest


@unittest.skipUnless(QT_AVAILABLE, "Qt runtime not installed")
class BoundsEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.compute = Mock(return_value=BoundingCircleXY(25))
        self.provider = BoundsProvider(self.compute)
        self.editor = SchematicEditor(chain("source", "mirror", "stop"), bounds_provider=self.provider)
        self.editor.resize(1800, 900)
        self.editor.show()
        self.editor.fit()
        self.app.processEvents()

    def tearDown(self):
        self.editor.history.mark_saved()
        self.editor.close()
        self.app.processEvents()

    def enable_bounds(self):
        QtTest.QTest.mouseClick(self.editor.bounds_toggle, QtCore.Qt.LeftButton)
        self.app.processEvents()
        self.assertTrue(self.editor.bounds_toggle.isChecked())

    def test_default_off_and_gui_toggle_do_not_change_physical_layout(self):
        before = compile_schematic(self.editor.document).source
        self.assertFalse(self.editor.bounds_toggle.isChecked())
        self.compute.assert_not_called()
        self.assertTrue(all(not item.bounds_circle.isVisible() for item in self.editor.scene.symbols.values()))
        positions = [node.position for node in self.editor.document.nodes]
        self.enable_bounds()
        self.assertEqual(self.compute.call_count, 2)
        source, mirror, stop = self.editor.document.nodes
        self.assertFalse(self.editor.scene.symbols[source.id].bounds_circle.isVisible())
        for node in (mirror, stop):
            item = self.editor.scene.symbols[node.id].bounds_circle
            self.assertTrue(item.isVisible())
            self.assertEqual(item.rect(), QtCore.QRectF(-100, -100, 200, 200))
        self.assertEqual([node.position for node in self.editor.document.nodes], positions)
        self.assertEqual(compile_schematic(self.editor.document).source, before)
        self.editor.bounds_toggle.setChecked(False)
        self.app.processEvents()
        self.assertTrue(all(not item.bounds_circle.isVisible() for item in self.editor.scene.symbols.values()))
        self.assertEqual(self.compute.call_count, 2)

    def test_scale_uses_cached_geometry_and_fit_excludes_hidden_circles(self):
        self.editor.fit()
        original_scale = self.editor.view.transform().m11()
        self.enable_bounds()
        self.editor.change_setting("bounds_scale", 100)
        self.app.processEvents()
        self.assertEqual(self.compute.call_count, 2)
        mirror = self.editor.document.nodes[1]
        self.assertEqual(self.editor.scene.symbols[mirror.id].bounds_circle.rect().width(), 5000)
        self.editor.fit()
        self.assertLess(self.editor.view.transform().m11(), original_scale)
        for item in self.editor.scene.symbols.values():
            item.bounds_circle.hide()
        self.editor.fit()
        self.assertAlmostEqual(self.editor.view.transform().m11(), original_scale)

    def test_toggling_bounds_preserves_selected_beam(self):
        edge = self.editor.document.connections[0]
        beam = self.editor.scene.connections[edge.id]
        beam.setSelected(True)
        self.enable_bounds()
        self.assertIs(self.editor.scene.connections[edge.id], beam)
        self.assertTrue(beam.isSelected())
        self.editor.bounds_toggle.setChecked(False)
        self.assertTrue(beam.isSelected())

    def test_parameter_preset_changes_refresh_and_inspector_values(self):
        self.compute.side_effect = lambda spec: BoundingCircleXY(dict(spec.parameters).get("diameter", 25))
        self.enable_bounds()
        mirror = self.editor.document.nodes[1]
        self.editor.scene.symbols[mirror.id].setSelected(True)
        self.app.processEvents()
        self.assertIn("radius 12.700 mm", self.editor.bounds_info.text())
        self.editor.set_node_value(mirror.id, "preset", "bare")
        self.app.processEvents()
        self.assertEqual(self.compute.call_count, 3)
        self.editor.set_node_dict(mirror.id, "parameters", "diameter", 20)
        self.app.processEvents()
        self.assertEqual(self.compute.call_count, 4)
        self.assertIn("diameter 40.000 mm", self.editor.bounds_info.text())
        self.assertEqual(self.editor.scene.symbols[mirror.id].bounds_circle.rect().width(), 160)
        self.editor.refresh_part_bounds()
        self.app.processEvents()
        self.assertEqual(self.compute.call_count, 6)
        # Hidden circles must not show stale dimensions after parameter edits.
        self.editor.bounds_toggle.setChecked(False)
        self.editor.set_node_dict(mirror.id, "parameters", "diameter", 30)
        self.assertIn("Enable Part bounds", self.editor.bounds_info.text())
        self.assertEqual(self.compute.call_count, 6)

    def test_missing_geometry_omits_circle_and_does_not_block_export(self):
        def compute(spec):
            if spec.factory == "Circular_Mirror":
                raise BoundsUnavailable("missing mount model")
            return BoundingCircleXY(25)
        self.compute.side_effect = compute
        self.enable_bounds()
        mirror = self.editor.document.nodes[1]
        self.assertFalse(self.editor.scene.symbols[mirror.id].bounds_circle.isVisible())
        self.editor.scene.symbols[mirror.id].setSelected(True)
        self.app.processEvents()
        self.assertIn("missing mount model", self.editor.bounds_info.text())
        self.assertTrue(self.editor.validate().ok)

    def test_circles_do_not_intercept_part_selection_or_port_wiring(self):
        self.editor.document.connections.clear()
        self.editor.commit()
        self.enable_bounds()
        source, mirror, _stop = self.editor.document.nodes
        self.editor.fit()
        self.app.processEvents()
        viewport = self.editor.view.viewport()
        QtTest.QTest.mouseClick(viewport, QtCore.Qt.LeftButton,
                                pos=self.editor.view.mapFromScene(QtCore.QPointF(*mirror.position)))
        self.assertTrue(self.editor.scene.symbols[mirror.id].isSelected())
        # The bottom of the halo lies outside the symbol's selectable bounds.
        QtTest.QTest.mouseClick(viewport, QtCore.Qt.LeftButton,
                                pos=self.editor.view.mapFromScene(QtCore.QPointF(mirror.position[0], mirror.position[1] + 100)))
        self.assertFalse(self.editor.scene.symbols[mirror.id].isSelected())
        for node, name in ((source, "beam"), (mirror, "A")):
            port = self.editor.scene.symbols[node.id].ports[name]
            QtTest.QTest.mouseClick(viewport, QtCore.Qt.LeftButton,
                                    pos=self.editor.view.mapFromScene(port.scenePos()))
            self.app.processEvents()
        self.assertEqual(len(self.editor.document.connections), 1)

    def test_toggle_scale_save_load_and_undo_redo(self):
        self.enable_bounds()
        self.editor.change_setting("bounds_scale", 8)
        self.editor.undo()
        self.app.processEvents()
        self.assertEqual(self.editor.document.settings["bounds_scale"], 4)
        self.assertTrue(self.editor.bounds_toggle.isChecked())
        self.editor.undo()
        self.app.processEvents()
        self.assertFalse(self.editor.bounds_toggle.isChecked())
        self.editor.redo()
        self.app.processEvents()
        self.assertTrue(self.editor.bounds_toggle.isChecked())
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bounds.json"
            save_schematic(self.editor.document, path)
            loaded = load_schematic(path)
            self.assertTrue(loaded.settings["show_bounds"])
            self.assertEqual(loaded.settings["bounds_scale"], 4)

    def test_virtual_symbols_have_no_circle_or_geometry_query(self):
        self.editor.document = chain("source", "output")
        self.editor.history = self.editor.history.__class__(self.editor.document)
        self.editor.restore()
        self.enable_bounds()
        self.compute.assert_not_called()
        self.assertTrue(all(not item.bounds_circle.isVisible() for item in self.editor.scene.symbols.values()))


if __name__ == "__main__":
    unittest.main()
