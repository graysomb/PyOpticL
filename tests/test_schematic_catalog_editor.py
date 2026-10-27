"""Palette, preset controls, bounds, constraints and persistence for lab optics."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PyOpticL.bounds import BoundingCircleXY
from PyOpticL.schematic import compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.registry import SYMBOLS
from PyOpticL.schematic.bounds import BoundsProvider
from test_schematic_catalog import preset_document
from test_schematic_editor import QT_AVAILABLE

if QT_AVAILABLE:
    from PyOpticL.schematic.editor import Palette, LegacySchematicEditor as SchematicEditor
    from PyOpticL.schematic.qt import QtCore, QtGui, QtWidgets
    from test_schematic_editor import QtTest


@unittest.skipUnless(QT_AVAILABLE, "Qt runtime not installed")
class CatalogEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.editor = None
        self.specs = []
        self.provider = BoundsProvider(lambda spec: self.specs.append(spec) or BoundingCircleXY(30))

    def tearDown(self):
        if self.editor is not None:
            self.editor.history.mark_saved()
            self.editor.close()
        self.flush()

    def flush(self):
        self.app.processEvents()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def open(self, kind, preset):
        doc, node = preset_document(kind, preset)
        self.editor = SchematicEditor(doc, bounds_provider=self.provider)
        self.editor.show()
        self.editor.scene.symbols[node.id].setSelected(True)
        self.flush()
        return doc, node

    def test_new_palette_symbols_and_locked_vendor_sizes(self):
        doc, node = self.open("mirror", "bare")
        palette = self.editor.findChild(Palette)
        kinds = {palette.item(i).data(QtCore.Qt.UserRole) for i in range(palette.count())}
        self.assertTrue({"roof", "grating", "slit"}.issubset(kinds))
        preset = self.editor.findChild(QtWidgets.QComboBox, "partPreset")
        preset.setCurrentIndex(preset.findData("MHV-25.4L-R"))
        self.flush()
        self.assertEqual(doc.node(node.id).preset, "MHV-25.4L-R")
        diameter = self.editor.findChild(QtWidgets.QDoubleSpinBox, "componentParameter_diameter")
        self.assertEqual(diameter.value(), 25.4)
        self.assertFalse(diameter.isEnabled())
        thickness = self.editor.findChild(QtWidgets.QDoubleSpinBox, "componentParameter_thickness")
        thickness.setValue(5)
        self.assertTrue(compile_schematic(doc).ok)
        self.editor.undo()
        self.editor.undo()
        self.assertEqual(self.editor.document.node(node.id).preset, "bare")
        self.editor.redo()
        self.assertEqual(self.editor.document.node(node.id).preset, "MHV-25.4L-R")

    def test_grating_order_is_integer_and_circles_use_the_same_specification(self):
        doc, node = self.open("grating", "MK05S")
        order = self.editor.findChild(QtWidgets.QSpinBox, "componentParameter_order")
        self.assertIsNotNone(order)
        before = deepcopy(doc.to_dict())
        self.editor.bounds_toggle.setChecked(True)
        self.flush()
        self.assertTrue(self.specs)
        spec = next(spec for spec in self.specs if spec.factory == "grating")
        self.assertEqual(dict(spec.before)["design_wavelength"], 1550)
        self.assertTrue(self.editor.scene.symbols[node.id].bounds_circle.isVisible())
        order.setValue(0)
        self.assertEqual(doc.node(node.id).parameters["order"], 0)
        self.assertIs(type(doc.node(node.id).parameters["order"]), int)
        self.assertTrue(compile_schematic(doc).ok)
        self.assertEqual(doc.to_dict()["connections"], before["connections"])

    def test_every_new_symbol_renders_and_save_load_keeps_presets_and_constraints(self):
        for kind, preset in (
            ("slit", "VA100"),
            ("roof", "vertical"),
            ("grating", "MK05S"),
            ("iris", "alignment"),
        ):
            doc, node = self.open(kind, preset)
            node.physical.update(x=50, y=0)
            image = QtGui.QImage(180, 180, QtGui.QImage.Format_ARGB32)
            image.fill(QtGui.QColor("white"))
            painter = QtGui.QPainter(image)
            self.editor.scene.render(
                painter, QtCore.QRectF(0, 0, 180, 180), self.editor.scene.symbols[node.id].sceneBoundingRect()
            )
            painter.end()
            self.assertFalse(image.isNull())
            with TemporaryDirectory() as directory:
                path = Path(directory) / "catalog.json"
                save_schematic(doc, path)
                restored = load_schematic(path)
                self.assertEqual(restored.node(node.id).preset, preset)
                self.assertEqual(restored.node(node.id).physical, node.physical)
                self.assertTrue(compile_schematic(restored).ok)
            self.editor.history.mark_saved()
            self.editor.close()


if __name__ == "__main__":
    unittest.main()
