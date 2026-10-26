"""Optional desktop tests: QT_QPA_PLATFORM=offscreen python -m unittest ..."""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyOpticL.schematic.editor import (
        BendItem, SchematicEditor, SchematicWindow, open_editor,
    )
    from PyOpticL.schematic.qt import QtCore, QtWidgets
    try:
        from PySide import QtTest
    except ImportError:
        try:
            from PySide6 import QtTest
        except ImportError:
            from PySide2 import QtTest
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

from PyOpticL.schematic import Endpoint, compile_schematic, load_schematic, save_schematic
from test_schematic import branched, chain


@unittest.skipUnless(QT_AVAILABLE, "Qt is supplied by FreeCAD; no Qt runtime available here")
class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.editor = SchematicEditor(branched())
        self.editor.show()
        self.editor.fit()
        self.app.processEvents()

    def tearDown(self):
        self.editor.history.mark_saved()
        self.editor.close()
        self.app.processEvents()

    def test_place_duplicate_rotate_delete_undo_and_redo(self):
        count = len(self.editor.document.nodes)
        self.editor.add_symbol("mirror", (19, 43))
        mirror = self.editor.document.nodes[-1]
        self.assertEqual(mirror.position, (20, 40))
        self.editor.rotate()
        self.assertEqual(mirror.rotation, 45)
        self.editor.duplicate()
        self.assertEqual(len(self.editor.document.nodes), count + 2)
        self.assertNotEqual(self.editor.document.nodes[-1].id, mirror.id)
        self.editor.delete_selected()
        self.assertEqual(len(self.editor.document.nodes), count + 1)
        self.editor.undo()
        self.assertEqual(len(self.editor.document.nodes), count + 2)
        self.editor.redo()
        self.assertEqual(len(self.editor.document.nodes), count + 1)

    def test_ports_connect_with_mouse_and_reject_reused_port(self):
        self.editor.document = chain("source", "mirror", "stop")
        self.editor.document.connections.clear()
        self.editor.document.nodes[-1].position = (200, -160)
        self.editor.history = self.editor.history.__class__(self.editor.document)
        self.editor.restore()
        self.editor.fit()
        self.app.processEvents()
        source, mirror, stop = self.editor.document.nodes
        for start, port, target, target_port in ((source, "beam", mirror, "A"), (mirror, "B", stop, "beam")):
            item = self.editor.scene.symbols[start.id].ports[port]
            QtTest.QTest.mouseClick(self.editor.view.viewport(), QtCore.Qt.LeftButton,
                                    pos=self.editor.view.mapFromScene(item.scenePos()))
            self.assertIsNotNone(self.editor.scene.pending)
            item = self.editor.scene.symbols[target.id].ports[target_port]
            QtTest.QTest.mouseClick(self.editor.view.viewport(), QtCore.Qt.LeftButton,
                                    pos=self.editor.view.mapFromScene(item.scenePos()))
            self.app.processEvents()
        self.assertEqual(len(self.editor.document.connections), 2)
        self.assertTrue(self.editor.validate().ok)
        self.assertFalse(self.editor.connect_ports(source.id, "beam", stop.id, "beam"))
        self.assertEqual(len(self.editor.document.connections), 2)

    def test_drawing_edits_do_not_change_exported_placements(self):
        before = compile_schematic(self.editor.document).source
        node = self.editor.document.nodes[1]
        item = self.editor.scene.symbols[node.id]
        item.setSelected(True)
        item.setPos(500, 700)
        node.position = (500, 700)
        self.editor.rotate()
        self.assertEqual(compile_schematic(self.editor.document).source, before)

    def test_properties_edit_optical_values_and_export_without_running(self):
        node = self.editor.document.nodes[1]
        self.editor.scene.symbols[node.id].setSelected(True)
        self.editor.set_node_dict(node.id, "parameters", "focal_length", 75)
        self.assertEqual(node.parameters["focal_length"], 75)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "layout.py"
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(output), "")):
                self.assertTrue(self.editor.export_python())
            self.assertIn("'focal_length': 75", output.read_text())
            self.assertIn("Run it", self.editor.status.text())

    def test_save_and_close_cancel_preserve_work(self):
        self.editor.add_symbol("mirror", (400, 400))
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Cancel):
            self.assertFalse(self.editor.close())
        self.assertTrue(self.editor.isVisible())
        with TemporaryDirectory() as directory:
            output = Path(directory) / "drawing.pyopticl-schematic.json"
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(output), "")):
                self.assertTrue(self.editor.save())
            self.assertFalse(self.editor.history.dirty)
            self.assertEqual(len(load_schematic(output).nodes), len(self.editor.document.nodes))

    def test_workspace_close_respects_cancel(self):
        mdi = QtWidgets.QMdiArea()
        window = SchematicWindow(mdi)
        other = SchematicEditor(chain("source", "stop"))
        window.setWidget(other)
        mdi.addSubWindow(window)
        mdi.show()
        window.show()
        other.add_symbol("mirror")
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Cancel):
            self.assertFalse(window.close())
        other.history.mark_saved()
        window.close()
        mdi.close()

    def test_bend_deletion_and_snap_settings_are_undoable(self):
        self.editor.document.connections[0].bends = [(80, 40)]
        self.editor.commit()
        bend = next(item for item in self.editor.scene.items() if isinstance(item, BendItem))
        bend.setSelected(True)
        self.editor.delete_selected()
        self.assertEqual(self.editor.document.connections[0].bends, [])
        self.editor.undo()
        self.assertEqual(self.editor.document.connections[0].bends, [(80, 40)])
        self.editor.change_setting("angle", 90)
        self.editor.undo()
        self.assertEqual(self.editor.angle_choice.currentText(), "45°")

    def test_invalid_export_does_not_open_file_dialog(self):
        self.editor.add_symbol("mirror")
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName") as dialog:
            self.assertFalse(self.editor.export_python())
            dialog.assert_not_called()
        self.assertGreater(self.editor.messages.count(), 0)

    def test_open_editor_attaches_and_reuses_workspace_tab(self):
        main = QtWidgets.QMainWindow()
        mdi = QtWidgets.QMdiArea()
        main.setCentralWidget(mdi)
        main.show()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "design.pyopticl-schematic.json"
            save_schematic(branched(), path)
            with patch.dict(sys.modules, {"FreeCADGui": SimpleNamespace(getMainWindow=lambda: main)}):
                editor = open_editor(path)
                self.assertIs(editor, open_editor(path))
                self.assertEqual(len(mdi.subWindowList()), 1)
                self.assertIs(editor.parentWidget(), mdi.subWindowList()[0])
                editor.parentWidget().close()
        main.close()

    def test_dragging_parts_and_bends_commits_one_undo_step(self):
        self.editor.document.connections[0].bends = [(-40, 100)]
        self.editor.commit()
        item = self.editor.scene.symbols[self.editor.document.nodes[0].id]
        self.editor.fit()
        self.app.processEvents()
        viewport = self.editor.view.viewport()
        origin = self.editor.view.mapFromScene(item.scenePos())
        target = origin + QtCore.QPoint(40, 40)
        index = self.editor.history.index
        QtTest.QTest.mousePress(viewport, QtCore.Qt.LeftButton, pos=origin)
        QtTest.QTest.mouseMove(viewport, target)
        QtTest.QTest.mouseRelease(viewport, QtCore.Qt.LeftButton, pos=target)
        self.assertEqual(self.editor.history.index, index + 1)
        self.editor.undo()
        self.assertEqual(self.editor.document.nodes[0].position, (0, 0))
        bend = next(item for item in self.editor.scene.items() if isinstance(item, BendItem))
        origin = self.editor.view.mapFromScene(bend.scenePos())
        index = self.editor.history.index
        QtTest.QTest.mousePress(viewport, QtCore.Qt.LeftButton, pos=origin)
        QtTest.QTest.mouseMove(viewport, origin + QtCore.QPoint(50, 0))
        QtTest.QTest.mouseRelease(viewport, QtCore.Qt.LeftButton, pos=origin + QtCore.QPoint(50, 0))
        self.assertEqual(self.editor.history.index, index + 1)
        self.editor.undo()
        self.assertEqual(self.editor.document.connections[0].bends, [(-40, 100)])

    def test_neutral_ports_can_be_wired_backwards_and_arrows_follow_source(self):
        self.editor.document = chain("source", "lens", "stop")
        source, lens, stop = self.editor.document.nodes
        source.position, source.rotation = (320, 0), 180
        stop.position, stop.rotation = (0, 0), 180
        self.editor.document.connections.clear()
        self.editor.history = self.editor.history.__class__(self.editor.document)
        self.editor.restore()
        self.editor.fit()
        self.app.processEvents()
        colors = {port.brush().color().name() for item in self.editor.scene.symbols.values()
                  for port in item.ports.values()}
        self.assertEqual(len(colors), 1)
        for start, port, target, target_port in ((lens, "B", source, "beam"), (stop, "beam", lens, "A")):
            for node, name in ((start, port), (target, target_port)):
                item = self.editor.scene.symbols[node.id].ports[name]
                self.assertNotIn("(input)", item.toolTip())
                self.assertNotIn("(output)", item.toolTip())
                QtTest.QTest.mouseClick(self.editor.view.viewport(), QtCore.Qt.LeftButton,
                                        pos=self.editor.view.mapFromScene(item.scenePos()))
                self.app.processEvents()
        self.assertTrue(self.editor.validate().ok)
        self.assertEqual(self.editor.scene.topology.incident_ports[lens.id], "B")
        for edge in self.editor.document.connections:
            resolved = self.editor.scene.topology.edges[edge.id]
            self.assertEqual(resolved.source, edge.b)
            item = self.editor.scene.connections[edge.id]
            arrow_tip = item.path().elementAt(item.path().elementCount() - 2)
            target = self.editor.scene.symbols[resolved.target.node_id].ports[resolved.target.port_id].scenePos()
            distance = ((arrow_tip.x - target.x()) ** 2 + (arrow_tip.y - target.y()) ** 2) ** 0.5
            self.assertAlmostEqual(distance, 10)
        self.assertFalse(self.editor.connect_ports(source.id, "beam", stop.id, "beam"))
        self.assertTrue(self.editor.port_connected(Endpoint(source.id, "beam")))
        self.editor.undo()
        self.assertEqual(len(self.editor.document.connections), 1)
        self.editor.redo()
        self.assertEqual(self.editor.scene.topology.incident_ports[lens.id], "B")

    def test_ambiguous_graph_hides_arrows_and_four_splitter_ports_are_visible(self):
        splitter = next(item for item in self.editor.scene.symbols.values() if item.node.kind == "splitter")
        self.assertEqual(set(splitter.ports), {"left", "right", "top", "bottom"})
        first = self.editor.document.connections[0]
        directed_count = self.editor.scene.connections[first.id].path().elementCount()
        self.assertGreater(directed_count, 2)
        self.editor.add_symbol("source", (-160, -160))
        self.assertFalse(self.editor.scene.topology.edges)
        self.assertEqual(self.editor.scene.connections[first.id].path().elementCount(), 2)
        self.assertFalse(self.editor.validate().ok)

    def test_turn_inspector_displays_the_resolved_default(self):
        for incident, expected in (("A", "90"), ("B", "-90")):
            document = chain("source", "mirror", "stop")
            mirror = document.nodes[1]
            document.connections[0].b = Endpoint(mirror.id, incident)
            document.connections[1].a = Endpoint(mirror.id, "B" if incident == "A" else "A")
            self.editor.document = document
            self.editor.history = self.editor.history.__class__(document)
            self.editor.restore()
            self.editor.scene.symbols[mirror.id].setSelected(True)
            self.app.processEvents()
            fields = [widget for widget in self.editor.properties.findChildren(QtWidgets.QComboBox)
                      if widget.isVisible() and self.editor.form.labelForField(widget) is not None and
                      self.editor.form.labelForField(widget).text() == "Reflected turn (deg)"]
            self.assertEqual(len(fields), 1)
            self.assertEqual(fields[0].currentText(), expected)
            self.assertNotIn("turn", mirror.physical)


if __name__ == "__main__":
    unittest.main()
