"""CAD generation uses the current schematic and preserves work on cancellation/failure."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PyOpticL.schematic import Schematic, compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.model import document_from_dict
from PyOpticL.schematic.cad import generation_source
from test_schematic_editor import QT_AVAILABLE
import test_schematic_physical_editor as physical_editor_tests
from test_schematic import chain

if QT_AVAILABLE:
    from PyOpticL.schematic.qt import QtWidgets


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable")
class CadGenerationEditorTests(unittest.TestCase):
    setUpClass = classmethod(physical_editor_tests.PhysicalEditorTests.setUpClass.__func__)
    setUp = physical_editor_tests.PhysicalEditorTests.setUp
    tearDown = physical_editor_tests.PhysicalEditorTests.tearDown
    open = physical_editor_tests.PhysicalEditorTests.open
    settle = physical_editor_tests.PhysicalEditorTests.settle

    def test_button_saves_current_python_and_cad_without_changing_schematic(self):
        editor = self.open(chain("source", "lens", "output"))
        before = deepcopy(editor.document.to_dict())
        dirty = editor.history.dirty
        with TemporaryDirectory() as folder:
            path = Path(folder) / "assembly.FCStd"
            editor.path = Path(folder) / "assembly.pyopticl-schematic.json"
            cad = SimpleNamespace(saveAs=Mock(side_effect=lambda p: Path(p).write_bytes(b"CAD")))
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(path), "")) as dialog, \
                 patch("PyOpticL.schematic.cad.build_cad", return_value=cad) as build:
                editor.actions["generate_cad"].trigger()
            source = generation_source(compile_schematic(editor.document).source, editor.document.settings)
            build.assert_called_once_with(source, editor.document.title)
            self.assertEqual(Path(dialog.call_args.args[2]), path)
            self.assertEqual(path.read_bytes(), b"CAD")
            self.assertEqual(path.with_suffix(".py").read_text(), source)
            self.assertEqual(set(p.name for p in Path(folder).iterdir()), {"assembly.FCStd", "assembly.py"})
        self.assertEqual(editor.document.to_dict(), before)
        self.assertEqual(editor.history.dirty, dirty)
        self.assertIn("3D assembly is open", editor.status.text())
        self.assertTrue(editor.actions["generate_cad"].isEnabled())
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())

    def test_invalid_schematic_blocks_generation_before_file_dialog(self):
        editor = self.open(Schematic())
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName") as dialog, \
             patch("PyOpticL.schematic.cad.build_cad") as build:
            self.assertFalse(editor.generate_cad())
        dialog.assert_not_called()
        build.assert_not_called()
        self.assertIn("CAD generation blocked", editor.status.text())

    def test_cancel_does_not_build_or_write(self):
        editor = self.open(chain("source", "lens", "output"))
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=("", "")), \
             patch("PyOpticL.schematic.cad.build_cad") as build:
            self.assertFalse(editor.generate_cad())
        build.assert_not_called()

    def test_existing_companion_python_requires_overwrite_and_missing_extension_is_added(self):
        editor = self.open(chain("source", "lens", "output"))
        with TemporaryDirectory() as folder:
            path = Path(folder) / "assembly"
            python_path = path.with_suffix(".py")
            python_path.write_text("Existing manual Python")
            cad = SimpleNamespace(saveAs=Mock(side_effect=lambda p: Path(p).write_bytes(b"CAD")))
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(path), "")), \
                 patch("PyOpticL.schematic.cad.build_cad", return_value=cad) as build, \
                 patch.object(editor, "confirm_overwrite", return_value=False) as confirm:
                self.assertFalse(editor.generate_cad())
                build.assert_not_called()
                confirm.assert_called_once_with(python_path)
                self.assertEqual(python_path.read_text(), "Existing manual Python")
                confirm.return_value = True
                self.assertTrue(editor.generate_cad())
            self.assertTrue(path.with_suffix(".FCStd").exists())
            self.assertEqual(python_path.read_text(),
                             generation_source(compile_schematic(editor.document).source, editor.document.settings))

    def test_build_failure_preserves_existing_files_and_restores_controls(self):
        editor = self.open(chain("source", "lens", "output"))
        with TemporaryDirectory() as folder:
            path = Path(folder) / "assembly.FCStd"
            path.write_bytes(b"Original CAD")
            python_path = path.with_suffix(".py")
            python_path.write_text("Original Python")
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(path), "")), \
                 patch.object(editor, "confirm_overwrite", return_value=True), \
                 patch("PyOpticL.schematic.cad.build_cad", side_effect=RuntimeError("Trace mismatch")), \
                 patch.object(QtWidgets.QMessageBox, "warning") as warning:
                self.assertFalse(editor.generate_cad())
            self.assertIn("Trace mismatch", warning.call_args.args[2])
            self.assertEqual(path.read_bytes(), b"Original CAD")
            self.assertEqual(python_path.read_text(), "Original Python")
            self.assertEqual(len(list(Path(folder).iterdir())), 2)
        self.assertTrue(editor.actions["generate_cad"].isEnabled())
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())

    def test_save_failure_keeps_built_document_available_and_cleans_staged_python(self):
        editor = self.open(chain("source", "lens", "output"))
        with TemporaryDirectory() as folder:
            path = Path(folder) / "assembly.FCStd"
            cad = SimpleNamespace(saveAs=Mock(side_effect=OSError("Disk full")))
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(path), "")), \
                 patch("PyOpticL.schematic.cad.build_cad", return_value=cad), \
                 patch.object(QtWidgets.QMessageBox, "warning") as warning:
                self.assertFalse(editor.generate_cad())
            self.assertIn("remains open", warning.call_args.args[2])
            self.assertIn("Disk full", warning.call_args.args[2])
            self.assertFalse(list(Path(folder).iterdir()))
        self.assertTrue(editor.actions["generate_cad"].isEnabled())

    def test_unwritable_destination_does_not_create_a_document(self):
        editor = self.open(chain("source", "lens", "output"))
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=("/missing/assembly.FCStd", "")), \
             patch("PyOpticL.schematic.editor.NamedTemporaryFile", side_effect=PermissionError("Read only")), \
             patch("PyOpticL.schematic.cad.build_cad") as build, \
             patch.object(QtWidgets.QMessageBox, "warning"):
            self.assertFalse(editor.generate_cad())
        build.assert_not_called()

    def test_baseplate_settings_toggle_undo_and_save_load(self):
        editor = self.open(chain("source", "lens", "output"))
        self.assertTrue(editor.baseplate_toggle.isChecked())
        editor.change_setting("plate_thickness", 25.4)
        self.settle()
        editor.change_setting("plate_margin", 20)
        self.settle()
        source = compile_schematic(editor.document).source
        generated = generation_source(source, editor.document.settings)
        self.assertIn("BASEPLATE = {'thickness': 25.4, 'margin': 20}", generated)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "plate.pyopticl-schematic.json"
            save_schematic(editor.document, path)
            restored = load_schematic(path)
            self.assertEqual(restored.settings, editor.document.settings)
        editor.baseplate_toggle.setChecked(False)
        self.settle()
        self.assertEqual(generation_source(source, editor.document.settings), source)
        editor.undo()
        self.settle()
        self.assertTrue(editor.baseplate_toggle.isChecked())
        editor.redo()
        self.settle()
        self.assertFalse(editor.baseplate_toggle.isChecked())


class BaseplateSourceTests(unittest.TestCase):
    def test_exported_main_builds_optics_and_plate_once_with_either_guard_style(self):
        for quote in ('"', "'"):
            source = ("calls = 0\ndef build_layout():\n"
                      "    global calls\n    calls += 1\n    return 'layout'\n\n"
                      f"if __name__ == {quote}__main__{quote}:\n    build_layout()\n")
            namespace = {"__name__": "__main__"}
            with patch("PyOpticL.schematic.cad.add_baseplate") as add:
                exec(generation_source(source, Schematic().settings), namespace)
            self.assertEqual(namespace["calls"], 1)
            add.assert_called_once_with("layout", thickness=12.7, margin=15.0)

    def test_settings_have_compatible_defaults_and_reject_invalid_dimensions(self):
        raw = Schematic().to_dict()
        for name in ("generate_baseplate", "plate_thickness", "plate_margin"):
            raw["settings"].pop(name)
        self.assertTrue(document_from_dict(raw).settings["generate_baseplate"])
        for key, value in (("plate_thickness", 10), ("plate_thickness", float('nan')),
                           ("plate_margin", 2), ("generate_baseplate", 1)):
            data = deepcopy(raw)
            data["settings"][key] = value
            with self.assertRaises(ValueError):
                document_from_dict(data)
