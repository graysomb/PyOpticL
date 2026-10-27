"""Native CAD button coverage, including saving, reopening and document isolation."""

from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import FreeCAD as App

from PyOpticL.schematic import compile_schematic
from PyOpticL.schematic.cad import add_baseplate, build_cad, generation_source
from PyOpticL.schematic.registry import select_preset
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
        select_preset(schematic.nodes[1], "POLARIS-K05VS2")
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
                self.assertEqual(path.with_suffix(".py").read_text(),
                                 generation_source(compile_schematic(schematic).source, schematic.settings))
                plate = next(obj for obj in cad.Objects if hasattr(obj, "MachiningPlan"))
                self.assertTrue(plate.Shape.isValid())
                self.assertEqual(len(plate.Shape.Solids), 1)
                plan = json.loads(plate.MachiningPlan)
                self.assertEqual(len(plan["holes"]), 9)  # three M4 holes and six dowels
                self.assertEqual(plan["pockets"], [])
                self.assertAlmostEqual(plate.Shape.BoundBox.ZMax, -12.7, delta=1e-6)
                before_recompute = plate.Shape.Volume, len(cad.Objects)
                plate.Proxy.recompute()
                self.assertAlmostEqual(plate.Shape.Volume, before_recompute[0], delta=1e-6)
                self.assertEqual(len(cad.Objects), before_recompute[1])
                local_shape = plate.Shape.copy()
                local_shape.Placement = App.Placement()
                for operation in plan["holes"]:
                    point = App.Vector(*operation["center_mm"])
                    point.z -= 2
                    self.assertFalse(local_shape.isInside(point, 1e-7, False))
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

    def test_baseplate_opt_out_and_unsupported_mount_errors(self):
        schematic = coupler_scene()  # Bare mirror has no attachment definition.
        compiled = compile_schematic(schematic).source
        with self.assertRaisesRegex(ValueError, "no supported baseplate attachment"):
            build_cad(generation_source(compiled, schematic.settings), "Unsupported mount")
        self.assertEqual(App.ActiveDocument.Name, self.original.Name)
        schematic.settings["generate_baseplate"] = False
        source = generation_source(compiled, schematic.settings)
        self.assertEqual(source, compiled)
        document = build_cad(source, "Optics only")
        self.assertFalse(any(hasattr(o, "MachiningPlan") for o in document.Objects))

    def test_integral_pbs_support_uses_its_declared_base_datum(self):
        from PyOpticL import lab_catalog
        from PyOpticL.layout import Layout

        layout = Layout("PBS with plate")
        layout.add(lab_catalog.create("pbs", "PBS"), (0, 0, 0), 0)
        layout.recompute()
        plate = add_baseplate(layout).get_object()
        plan = json.loads(plate.MachiningPlan)
        self.assertTrue(plate.Shape.isValid())
        self.assertEqual(len(plate.Shape.Solids), 1)
        self.assertAlmostEqual(plan["plate_position_mm"][2], -25.4, delta=1e-6)
        self.assertEqual(len(plan["integrated_holders"]), 1)

    def test_plate_cannot_be_raised_into_a_lower_beam(self):
        document = coupler_scene()
        select_preset(document.nodes[1], "POLARIS-K05VS2")
        cad = build_cad(compile_schematic(document).source, "Height conflict")
        root = next(obj.Proxy for obj in cad.Objects if obj.Label == document.title)
        receiver = next(obj for obj in root.get_object().Children if obj.Label == "FO1")
        receiver.BasePlacement = App.Placement(App.Vector(50, 50, 25), receiver.BasePlacement.Rotation)
        # Recompute mechanical placement without retracing the deliberately inconsistent beam.
        receiver.Proxy.recompute()
        with self.assertRaisesRegex(ValueError, "intersects the beam"):
            add_baseplate(root, thickness=40)
