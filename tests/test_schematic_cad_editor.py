"""CAD generation uses the current schematic and preserves work on cancellation/failure."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PyOpticL.schematic import Schematic, compile_schematic
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
            source = compile_schematic(editor.document).source
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
            self.assertEqual(python_path.read_text(), compile_schematic(editor.document).source)

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
