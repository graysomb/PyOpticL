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
        for incident, expected in (("A", 90), ("B", -90)):
            document = chain("source", "mirror", "stop")
            mirror = document.nodes[1]
            document.connections[0].b = Endpoint(mirror.id, incident)
            document.connections[1].a = Endpoint(mirror.id, "B" if incident == "A" else "A")
            self.editor.document = document
            self.editor.history = self.editor.history.__class__(document)
            self.editor.restore()
            self.editor.scene.symbols[mirror.id].setSelected(True)
            self.app.processEvents()
            fields = [widget for widget in self.editor.properties.findChildren(QtWidgets.QDoubleSpinBox)
                      if widget.isVisible() and widget.objectName() == "opticAngleDeg"]
            self.assertEqual(len(fields), 1)
            self.assertEqual(fields[0].value(), expected)
            self.assertFalse(fields[0].isEnabled())
            self.assertNotIn("turn", mirror.physical)

    def test_selecting_beam_edits_optional_length_and_undo_redo(self):
        edge = self.editor.document.connections[0]
        QtTest.QTest.mouseClick(self.editor.view.viewport(), QtCore.Qt.LeftButton,
                                pos=self.editor.view.mapFromScene(QtCore.QPointF(80, 0)))
        self.app.processEvents()
        checkbox = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QCheckBox)
                        if widget.objectName() == "beamLengthConstrained" and widget.isVisible())
        length = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QDoubleSpinBox)
                      if widget.objectName() == "beamLengthMm" and widget.isVisible())
        self.assertFalse(checkbox.isChecked())
        self.assertFalse(length.isEnabled())
        self.assertEqual(length.value(), 50)
        checkbox.setChecked(True)
        length.setValue(75)
        self.assertEqual(edge.length, 75)
        self.assertTrue(self.editor.scene.connections[edge.id].isSelected())
        self.assertIn("75 mm", self.editor.scene.connections[edge.id].toolTip())
        self.assertEqual(compile_schematic(self.editor.document).placements["L1"][:2], (75, 0))
        self.assertNotIn("distance", self.editor.document.nodes[1].physical)
        checkbox.setChecked(False)
        self.assertIsNone(edge.length)
        self.assertFalse(length.isEnabled())
        self.assertEqual(length.value(), 50)
        self.editor.undo()
        self.assertEqual(self.editor.document.connection(edge.id).length, 75)
        self.editor.redo()
        self.assertIsNone(self.editor.document.connection(edge.id).length)

    def test_component_inspector_has_no_distance_field(self):
        node = self.editor.document.nodes[1]
        self.editor.scene.symbols[node.id].setSelected(True)
        self.app.processEvents()
        labels = [self.editor.form.itemAt(index).widget().text() for index in range(self.editor.form.count())
                  if isinstance(self.editor.form.itemAt(index).widget(), QtWidgets.QLabel)]
        self.assertNotIn("From previous part (mm)", labels)
        self.assertTrue(any("connecting beam" in label for label in labels))
        self.assertFalse(any(widget.isVisible() and widget.objectName() == "opticAngleConstrained"
                             for widget in self.editor.properties.findChildren(QtWidgets.QCheckBox)))

    def test_optic_position_inspector_toggle_edit_undo_and_reset(self):
        node = self.editor.document.nodes[1]  # Lens, initially at physical (50, 0).
        self.editor.scene.symbols[node.id].setSelected(True)
        self.app.processEvents()
        control = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QCheckBox)
                       if widget.objectName() == "opticPositionConstrained" and widget.isVisible())
        x = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QDoubleSpinBox)
                 if widget.objectName() == "opticPositionX" and widget.isVisible())
        y = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QDoubleSpinBox)
                 if widget.objectName() == "opticPositionY" and widget.isVisible())
        self.assertFalse(control.isChecked())
        self.assertFalse(x.isEnabled())
        self.assertFalse(y.isEnabled())
        self.assertEqual((x.value(), y.value()), (50, 0))
        control.setChecked(True)
        x.setValue(75)
        self.assertEqual(node.physical, {"x": 75, "y": 0})
        self.assertEqual(compile_schematic(self.editor.document).placements["L1"][:2], (75, 0))
        self.assertTrue(self.editor.scene.symbols[node.id].isSelected())
        control.setChecked(False)
        self.assertFalse(node.physical)
        self.assertEqual((x.value(), y.value()), (50, 0))
        self.editor.undo()
        self.assertEqual(self.editor.document.node(node.id).physical, {"x": 75, "y": 0})
        self.editor.redo()
        self.assertFalse(self.editor.document.node(node.id).physical)

    def test_beam_inspector_shows_position_solved_length_and_freezes_it(self):
        node = self.editor.document.nodes[1]
        self.editor.set_optic_position(node.id, (80, 0))
        edge = self.editor.document.connections[0]
        self.editor.scene.connections[edge.id].setSelected(True)
        self.app.processEvents()
        length = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QDoubleSpinBox)
                      if widget.objectName() == "beamLengthMm" and widget.isVisible())
        control = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QCheckBox)
                       if widget.objectName() == "beamLengthConstrained" and widget.isVisible())
        self.assertEqual(length.value(), 80)
        control.setChecked(True)
        self.assertEqual(edge.length, 80)
        self.assertTrue(self.editor.validate().ok)

    def test_source_position_constraint_can_be_cleared_without_changing_direction(self):
        source = self.editor.document.nodes[0]
        source.physical.update(x=20, y=-30, angle=90)
        self.editor.commit()
        self.editor.scene.symbols[source.id].setSelected(True)
        self.app.processEvents()
        control = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QCheckBox)
                       if widget.objectName() == "opticPositionConstrained" and widget.isVisible())
        self.assertTrue(control.isChecked())
        control.setChecked(False)
        self.assertEqual(source.physical, {"angle": 90})
        self.assertEqual(compile_schematic(self.editor.document).placements[source.reference][:2], (0, 0))

    def test_incompatible_position_diagnostic_selects_optic(self):
        lens = self.editor.document.nodes[1]
        self.editor.set_optic_position(lens.id, (50, 10))
        self.assertFalse(self.editor.validate().ok)
        item = next(self.editor.messages.item(index) for index in range(self.editor.messages.count())
                    if "position" in self.editor.messages.item(index).text())
        self.editor.focus_diagnostic(item)
        self.assertTrue(self.editor.scene.symbols[lens.id].isSelected())

    def test_optic_angle_inspector_edits_clears_and_undoes(self):
        document = chain("source", "mirror", "stop")
        mirror = document.nodes[1]
        self.editor.document = document
        self.editor.history = self.editor.history.__class__(document)
        self.editor.restore()
        self.editor.scene.symbols[mirror.id].setSelected(True)
        self.app.processEvents()
        checkbox = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QCheckBox)
                        if widget.objectName() == "opticAngleConstrained" and widget.isVisible())
        angle = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QDoubleSpinBox)
                     if widget.objectName() == "opticAngleDeg" and widget.isVisible())
        self.assertFalse(checkbox.isChecked())
        self.assertFalse(angle.isEnabled())
        self.assertEqual(angle.value(), 90)
        checkbox.setChecked(True)
        angle.setValue(-62.5)
        self.assertEqual(mirror.physical["turn"], -62.5)
        self.assertTrue(compile_schematic(document).ok)
        self.assertTrue(all(not edge.turns for edge in document.connections))
        self.assertTrue(self.editor.scene.symbols[mirror.id].isSelected())
        checkbox.setChecked(False)
        self.assertNotIn("turn", mirror.physical)
        self.assertEqual(angle.value(), 90)
        self.editor.undo()
        self.assertEqual(self.editor.document.node(mirror.id).physical["turn"], -62.5)
        self.editor.redo()
        self.assertNotIn("turn", self.editor.document.node(mirror.id).physical)

    def test_beam_inspector_has_length_controls_but_no_angle_controls(self):
        for edge in self.editor.document.connections:
            self.editor.scene.clearSelection()
            self.editor.scene.connections[edge.id].setSelected(True)
            self.app.processEvents()
            controls = [widget for widget in self.editor.properties.findChildren(QtWidgets.QCheckBox) if widget.isVisible()]
            self.assertEqual([control.objectName() for control in controls], ["beamAllowFolding", "beamLengthConstrained"])

    def test_each_mirror_has_its_own_angle_control(self):
        document = chain("source", "mirror", "mirror", "stop")
        self.editor.document = document
        self.editor.history = self.editor.history.__class__(document)
        self.editor.restore()
        for node, value in zip(document.nodes[1:3], (60, -30)):
            self.editor.scene.clearSelection()
            self.editor.scene.symbols[node.id].setSelected(True)
            self.app.processEvents()
            control = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QCheckBox)
                           if widget.objectName() == "opticAngleConstrained" and widget.isVisible())
            angle = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QDoubleSpinBox)
                         if widget.objectName() == "opticAngleDeg" and widget.isVisible())
            control.setChecked(True)
            angle.setValue(value)
        self.assertEqual([node.physical["turn"] for node in document.nodes[1:3]], [60, -30])
        self.assertTrue(compile_schematic(document).ok)

    def test_legacy_angle_diagnostic_selects_optic_and_edit_resolves_conflict(self):
        document = chain("source", "mirror", "stop")
        mirror = document.nodes[1]
        for edge, angle in zip(document.connections, (60, -60)):
            edge.turns[mirror.id] = angle
        self.editor.document = document
        self.editor.history = self.editor.history.__class__(document)
        self.editor.restore()
        self.assertFalse(self.editor.validate().ok)
        item = next(self.editor.messages.item(index) for index in range(self.editor.messages.count())
                    if "conflicting" in self.editor.messages.item(index).text())
        self.editor.focus_diagnostic(item)
        self.assertTrue(self.editor.scene.symbols[mirror.id].isSelected())
        self.app.processEvents()
        angle = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QDoubleSpinBox)
                     if widget.objectName() == "opticAngleDeg" and widget.isVisible())
        angle.setValue(37.5)
        self.assertEqual(mirror.physical["turn"], 37.5)
        self.assertTrue(all(not edge.turns for edge in document.connections))
        self.assertTrue(self.editor.validate().ok)

    def test_splitter_angle_and_legacy_toggle_are_edited_on_the_optic(self):
        cube = self.editor.document.nodes[2]
        self.editor.document.connections[1].turns[cube.id] = -62.5
        self.editor.commit()
        self.editor.scene.symbols[cube.id].setSelected(True)
        self.app.processEvents()
        control = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QCheckBox)
                       if widget.objectName() == "opticAngleConstrained" and widget.isVisible())
        angle = next(widget for widget in self.editor.properties.findChildren(QtWidgets.QDoubleSpinBox)
                     if widget.objectName() == "opticAngleDeg" and widget.isVisible())
        self.assertTrue(control.isChecked())
        self.assertEqual(angle.value(), -62.5)
        control.setChecked(False)
        self.assertFalse(angle.isEnabled())
        self.assertNotIn("turn", cube.physical)
        self.assertTrue(all(cube.id not in edge.turns for edge in self.editor.document.connections))
        control.setChecked(True)
        angle.setValue(117.25)
        self.assertEqual(cube.physical["turn"], 117.25)
        self.assertTrue(self.editor.validate().ok)

    def test_completing_legacy_drawing_migrates_length_as_one_undoable_edit(self):
        document = chain("lens", "stop")
        lens = document.nodes[0]
        lens.physical["distance"] = 75
        self.editor.document = document
        self.editor.history = self.editor.history.__class__(document)
        self.editor.restore()
        self.editor.add_symbol("source", (-160, 0))
        source = self.editor.document.nodes[-1]
        self.assertEqual(self.editor.document.node(lens.id).physical["distance"], 75)
        self.assertTrue(self.editor.connect_ports(source.id, "beam", lens.id, "A"))
        self.editor.commit()
        self.assertNotIn("distance", self.editor.document.node(lens.id).physical)
        self.assertEqual(self.editor.document.connections[-1].length, 75)
        self.editor.undo()
        self.assertEqual(self.editor.document.node(lens.id).physical["distance"], 75)
        self.assertEqual(len(self.editor.document.connections), 1)
        self.editor.redo()
        self.assertNotIn("distance", self.editor.document.node(lens.id).physical)
        self.assertEqual(self.editor.document.connections[-1].length, 75)


if __name__ == "__main__":
    unittest.main()
