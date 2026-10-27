"""Native CAD button coverage, including saving, reopening and document isolation."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import FreeCAD as App

from PyOpticL.schematic import compile_schematic
from PyOpticL.schematic.cad import build_cad
from PyOpticL.schematic.editor import SchematicEditor
from PyOpticL.schematic.qt import QtCore, QtWidgets
from test_schematic_centering import coupler_scene
from test_schematic_editor import QtTest


class CadGenerationFreeCADTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.previous = App.ActiveDocument.Name if App.ActiveDocument else None
        self.before = set(App.listDocuments())
        self.original = App.newDocument("ExistingDesign")
        self.original.addObject("Part::Feature", "PreservedObject")

    def tearDown(self):
        for name in set(App.listDocuments()) - self.before:
            App.closeDocument(name)
        if self.previous:
            App.setActiveDocument(self.previous)

    def test_button_builds_saves_and_reopens_complete_coupler_assembly(self):
        schematic = coupler_scene()
        editor = SchematicEditor(schematic)
        try:
            for _ in range(200):
                self.app.processEvents()
                if not editor.workers:
                    break
                QtTest.QTest.qWait(10)
            self.assertFalse(editor.workers)
            App.setActiveDocument(self.original.Name)
            with TemporaryDirectory() as folder:
                path = Path(folder) / "couplers.FCStd"
                with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(path), "")), \
                     patch.object(QtWidgets.QMessageBox, "warning") as warning:
                    self.assertTrue(editor.generate_cad(), editor.status.text())
                warning.assert_not_called()
                cad = App.ActiveDocument
                self.assertNotEqual(cad.Name, self.original.Name)
                self.assertEqual([o.Name for o in self.original.Objects], ["PreservedObject"])
                self.assertEqual(path.with_suffix(".py").read_text(), compile_schematic(schematic).source)
                expected = {
                    obj.Name: (obj.Shape.Volume, tuple(getattr(obj.Shape.BoundBox, axis)
                               for axis in ("XMin", "XMax", "YMin", "YMax", "ZMin", "ZMax")))
                    for obj in cad.Objects if hasattr(obj, "Shape") and not obj.Shape.isNull()
                }
                self.assertGreaterEqual(len(expected), 7)  # two complete couplers, mirror and rays
                count = len(cad.Objects)
                App.closeDocument(cad.Name)
                restored = App.openDocument(str(path))
                restored.recompute()
                self.assertEqual(len(restored.Objects), count)
                for name, (volume, bounds) in expected.items():
                    shape = restored.getObject(name).Shape
                    self.assertTrue(shape.isValid(), name)
                    self.assertAlmostEqual(shape.Volume, volume, delta=1e-6)
                    for axis, value in zip(("XMin", "XMax", "YMin", "YMax", "ZMin", "ZMax"), bounds):
                        self.assertAlmostEqual(getattr(shape.BoundBox, axis), value, delta=1e-6)
        finally:
            editor.history.mark_saved()
            editor.close()
            self.app.processEvents()
            self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def test_failed_build_closes_partial_document_and_restores_existing_design(self):
        before = set(App.listDocuments())
        source = ("def build_layout():\n"
                  "    import FreeCAD as App\n"
                  "    App.ActiveDocument.addObject('Part::Feature', 'Partial')\n"
                  "    raise RuntimeError('Trace check failed')\n")
        with self.assertRaisesRegex(RuntimeError, "Trace check failed"):
            build_cad(source, "Failed design")
        self.assertEqual(set(App.listDocuments()), before)
        self.assertEqual(App.ActiveDocument.Name, self.original.Name)
        self.assertEqual([o.Name for o in self.original.Objects], ["PreservedObject"])

    def test_repeated_generation_creates_separate_documents(self):
        source = compile_schematic(coupler_scene()).source
        first = build_cad(source, "First layout")
        count = len(first.Objects)
        second = build_cad(source, "Second layout")
        self.assertNotEqual(first.Name, second.Name)
        self.assertEqual(len(first.Objects), count)
        self.assertEqual(len(second.Objects), count)
        self.assertEqual([o.Name for o in self.original.Objects], ["PreservedObject"])
