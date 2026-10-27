"""Batch constraint controls apply to the selection as one undoable edit."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PyOpticL.schematic import compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.constraint_marks import component_marks
from PyOpticL.schematic.effective import folding_protection
from PyOpticL.schematic.physical import wrap_angle
from PyOpticL.schematic.scene_layout import trace_scene
from PyOpticL.schematic.scene_solver import solve_scene, variables
from test_schematic_drag_workers import optics_layout
from test_schematic_editor import QT_AVAILABLE

if QT_AVAILABLE:
    import test_schematic_physical_editor as physical_tests
    from PyOpticL.schematic.qt import QtCore, QtWidgets


class RotationPinTests(unittest.TestCase):
    def test_rotation_pins_round_trip_compile_and_remove_yaw_from_free_variables(self):
        document = optics_layout()
        for node in document.nodes:
            node.physical["yaw"] = document.layout["poses"][node.id][3] + 360
        before = deepcopy(document.to_dict())
        solution = solve_scene(document)
        self.assertTrue(solution.ok, solution.diagnostics)
        self.assertFalse(any(axis == 3 for _, axis in variables(document)))
        for node in document.nodes:
            self.assertAlmostEqual(wrap_angle(solution.poses[node.id][3] - node.physical["yaw"]), 0)
        self.assertEqual(document.to_dict(), before)
        document.layout["poses"] = solution.poses
        with TemporaryDirectory() as folder:
            path = Path(folder) / "group.json"
            save_schematic(document, path)
            loaded = load_schematic(path)
        self.assertEqual(loaded.to_dict(), document.to_dict())
        compiled = compile_schematic(loaded)
        self.assertTrue(compiled.ok, compiled.diagnostics)

    def test_rotation_target_and_trace_cannot_override_a_pin(self):
        document = optics_layout()
        mirror = document.nodes[2]
        angle = document.layout["poses"][mirror.id][3]
        mirror.physical["yaw"] = angle
        result = solve_scene(document, targets=((mirror.id, 3, angle + 45),), iterations=10)
        self.assertFalse(result.ok)
        self.assertEqual(result.poses[mirror.id][3], angle)
        moved = deepcopy(document.layout["poses"])
        moved[mirror.id][3] += 10
        trace = trace_scene(document, moved)
        pin = next(row for row in trace.residuals if row.id == f"pin/{mirror.id}/yaw")
        self.assertAlmostEqual(pin.value, 10)
        mirror.mirror_role = "folding"
        self.assertEqual(folding_protection(document, mirror.id), "Rotation-constrained mirrors are retained")


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable")
class SelectionConstraintTests(unittest.TestCase):
    if QT_AVAILABLE:
        setUpClass = classmethod(physical_tests.PhysicalEditorTests.setUpClass.__func__)
        setUp = physical_tests.PhysicalEditorTests.setUp
        tearDown = physical_tests.PhysicalEditorTests.tearDown
        open = physical_tests.PhysicalEditorTests.open
        settle = physical_tests.PhysicalEditorTests.settle

    def select_group(self, *nodes):
        self.editor.scene.clearSelection()
        for node in nodes:
            self.editor.scene.symbols[node.id].setSelected(True)
        self.app.processEvents()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def test_mixed_position_group_can_be_locked_unlocked_and_undone(self):
        e = self.open(optics_layout())
        source, _, mirror = e.document.nodes[:3]
        self.select_group(source, mirror)
        before = deepcopy(e.document.to_dict())
        index = e.history.index
        toggle = e.findChild(QtWidgets.QCheckBox, "selectionPositionConstrained")
        self.assertEqual(toggle.checkState(), QtCore.Qt.PartiallyChecked)
        toggle.click()
        self.settle()
        self.assertEqual(e.history.index, index + 1)
        self.assertEqual(set(e.selected_nodes()), {source.id, mirror.id})
        for node in (source, mirror):
            current = e.document.node(node.id)
            self.assertEqual([current.physical[k] for k in ("x", "y")],
                             before["layout"]["poses"][node.id][:2])
        e.undo()
        self.settle()
        self.assertEqual(e.document.to_dict(), before)
        e.redo()
        self.settle()
        self.select_group(e.document.node(source.id), e.document.node(mirror.id))
        toggle = e.findChild(QtWidgets.QCheckBox, "selectionPositionConstrained")
        self.assertEqual(toggle.checkState(), QtCore.Qt.Checked)
        toggle.click()
        self.settle()
        for node_id in (source.id, mirror.id):
            self.assertNotIn("x", e.document.node(node_id).physical)
            self.assertNotIn("y", e.document.node(node_id).physical)
        self.assertTrue(e.display_trace.ok)

    def test_partial_position_pin_is_mixed_and_other_selected_values_are_preserved(self):
        document = optics_layout()
        source, _, mirror = document.nodes[:3]
        source.physical.pop("y")
        e = self.open(document)
        self.select_group(source, mirror)
        toggle = e.findChild(QtWidgets.QCheckBox, "selectionPositionConstrained")
        self.assertEqual(toggle.checkState(), QtCore.Qt.PartiallyChecked)
        e.set_selection_position_constrained(True)
        self.settle()
        self.assertEqual(e.document.node(source.id).physical["x"], source.physical["x"])
        self.assertIn("y", e.document.node(source.id).physical)
        self.assertEqual(e.document.nodes[1].physical, {})

    def test_group_rotation_is_independent_of_position_and_pass_turns(self):
        document = optics_layout()
        plate, mirror, grating = document.nodes[1], document.nodes[2], document.nodes[4]
        mirror.physical["yaw"] = document.layout["poses"][mirror.id][3]
        mirror.physical["turn"] = trace_scene(document).layout.turns[mirror.id]
        e = self.open(document)
        self.select_group(plate, mirror, grating)
        before = deepcopy(e.document.to_dict())
        index = e.history.index
        toggle = e.findChild(QtWidgets.QCheckBox, "selectionRotationConstrained")
        self.assertEqual(toggle.checkState(), QtCore.Qt.PartiallyChecked)
        toggle.click()
        self.settle()
        self.assertEqual(e.history.index, index + 1)
        for node in (plate, mirror, grating):
            current = e.document.node(node.id)
            self.assertEqual(current.physical["yaw"], before["layout"]["poses"][node.id][3])
            self.assertNotIn("x", current.physical)
            self.assertIn("rotation", {mark.kind for mark in component_marks(e.document, node.id)})
        turn = e.document.node(mirror.id).physical["turn"]
        toggle = e.findChild(QtWidgets.QCheckBox, "selectionRotationConstrained")
        toggle.click()
        self.settle()
        for node in (plate, mirror, grating):
            self.assertNotIn("yaw", e.document.node(node.id).physical)
        self.assertEqual(e.document.node(mirror.id).physical["turn"], turn)
        e.undo()
        self.settle()
        self.assertTrue(all("yaw" in e.document.node(n.id).physical for n in (plate, mirror, grating)))
        e.undo()
        self.settle()
        self.assertEqual(e.document.to_dict(), before)

    def test_single_part_rotation_control_and_invalid_draft_respect_the_pin(self):
        e = self.open(optics_layout())
        mirror = e.document.nodes[2]
        self.select_group(mirror)
        before = e.document.layout["poses"][mirror.id][3]
        toggle = e.findChild(QtWidgets.QCheckBox, "opticRotationConstrained")
        toggle.click()
        self.settle()
        self.assertEqual(e.document.node(mirror.id).physical["yaw"], before)
        e.document.connections.pop()
        e.commit()
        self.settle()
        self.assertFalse(e.display_trace.ok)
        e.begin_drag()
        e.start_solve(((mirror.id, 3, before + 45),), True)
        self.settle()
        self.assertEqual(e.document.layout["poses"][mirror.id][3], before)


if __name__ == "__main__":
    unittest.main()
