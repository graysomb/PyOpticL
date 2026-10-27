"""Constraint annotations describe the model without adding geometry constraints."""

from copy import deepcopy
import unittest

from PyOpticL.schematic import PathLengthConstraint
from PyOpticL.schematic.constraint_marks import component_marks, beam_marks, MARK_TYPES
from test_schematic import chain
from test_schematic_roof_return import shared_mirror_roof_scene
from test_schematic_editor import QT_AVAILABLE

if QT_AVAILABLE:
    import test_schematic_physical_editor as physical_tests
    from PyOpticL.schematic.qt import QtWidgets, QtCore


def by_kind(marks):
    return {mark.kind: mark for mark in marks}


class ConstraintDescriptionTests(unittest.TestCase):
    def test_shared_component_marks_aggregate_passes_and_preserve_the_document(self):
        document = shared_mirror_roof_scene()
        source, mirror, roof, receiver = document.nodes
        returning = document.optical_pass("mirror-return")
        returning.turn = -90
        returning.centered = True
        before = deepcopy(document.to_dict())
        marks = by_kind(component_marks(document, mirror.id))
        self.assertEqual(set(marks), {"position", "angle", "center"})
        self.assertIn("X = 50 mm", marks["position"].tooltip)
        self.assertIn("pass 1", marks["angle"].tooltip)
        self.assertIn("pass 2", marks["angle"].tooltip)
        self.assertIn("-90°", marks["angle"].tooltip)
        self.assertIn("pass 2", marks["center"].tooltip)
        self.assertIn("direction", by_kind(component_marks(document, source.id)))
        self.assertIn("4 mm", by_kind(component_marks(document, roof.id))["offset"].tooltip)
        self.assertNotIn("position", by_kind(component_marks(document, receiver.id)))
        self.assertEqual(document.to_dict(), before)

    def test_automatic_geometry_rules_have_distinct_marks_without_false_pins(self):
        document = chain("source", "lens", "hwp", "iris", "grating", "roof", "output")
        source, lens, plate, iris, grating, roof, output = document.nodes
        self.assertFalse(component_marks(document, source.id))
        self.assertFalse(component_marks(document, output.id))
        self.assertEqual(set(by_kind(component_marks(document, lens.id))), {"center"})
        for node in (plate, iris):
            self.assertEqual(set(by_kind(component_marks(document, node.id))), {"center", "alignment"})
        self.assertEqual(set(by_kind(component_marks(document, grating.id))), {"center", "incidence"})
        self.assertEqual(set(by_kind(component_marks(document, roof.id))), {"center", "offset", "alignment"})
        self.assertEqual(len({mark for _, mark, _ in MARK_TYPES}), len(MARK_TYPES))

    def test_overlapping_total_paths_and_original_lengths_follow_their_beam_routes(self):
        document = chain("source", "lens", "lens", "output")
        a, b, c, d = document.nodes
        first, shared, last = document.connections
        shared.length = 100
        document.path_constraints = [PathLengthConstraint("ac", a.id, c.id, 150),
                                     PathLengthConstraint("bd", b.id, d.id, 200)]
        marks = by_kind(beam_marks(document, (shared.id,)))
        self.assertEqual(set(marks), {"length", "path_length"})
        self.assertIn("100 mm", marks["length"].tooltip)
        self.assertIn("150 mm", marks["path_length"].tooltip)
        self.assertIn("200 mm", marks["path_length"].tooltip)
        self.assertNotIn("200 mm", by_kind(beam_marks(document, (first.id,)))["path_length"].tooltip)
        self.assertNotIn("150 mm", by_kind(beam_marks(document, (last.id,)))["path_length"].tooltip)
        # A merged/folded segment retains annotations for its original beams.
        merged = by_kind(beam_marks(document, (shared.id, last.id)))
        self.assertEqual(set(merged), {"length", "path_length"})
        self.assertIn("path_length", by_kind(component_marks(document, c.id)))
        document.connections.remove(shared)
        self.assertFalse(beam_marks(document, (first.id,)))
        self.assertIn("path_length", by_kind(component_marks(document, c.id)))


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable")
class ConstraintCanvasTests(unittest.TestCase):
    if QT_AVAILABLE:
        setUpClass = classmethod(physical_tests.PhysicalEditorTests.setUpClass.__func__)
        setUp = physical_tests.PhysicalEditorTests.setUp
        tearDown = physical_tests.PhysicalEditorTests.tearDown
        open = physical_tests.PhysicalEditorTests.open
        settle = physical_tests.PhysicalEditorTests.settle

    def test_component_and_beam_marks_update_with_edits_and_undo_redo(self):
        e = self.open(shared_mirror_roof_scene())
        mirror = e.document.nodes[1]
        self.assertIn("angle", by_kind(e.scene.symbols[mirror.id].constraint_marks.specs))
        e.set_optic_turn(mirror.id, None)
        self.settle()
        self.assertNotIn("angle", by_kind(e.scene.symbols[mirror.id].constraint_marks.specs))
        e.undo()
        self.settle()
        self.assertIn("angle", by_kind(e.scene.symbols[mirror.id].constraint_marks.specs))
        e.redo()
        self.settle()
        self.assertNotIn("angle", by_kind(e.scene.symbols[mirror.id].constraint_marks.specs))
        edge = e.document.connections[0]
        e.set_connection_length(edge.id, 50)
        self.settle()
        e.document.path_constraints.append(PathLengthConstraint("sum", edge.a.node_id, edge.b.node_id, 50))
        e.commit()
        self.settle()
        marks = by_kind(e.scene.connections[edge.id].constraint_marks.specs)
        self.assertEqual(set(marks), {"length", "path_length"})
        e.undo()
        self.settle()
        self.assertEqual(set(by_kind(e.scene.connections[edge.id].constraint_marks.specs)), {"length"})
        e.redo()
        self.settle()
        self.assertEqual(set(by_kind(e.scene.connections[edge.id].constraint_marks.specs)), {"length", "path_length"})

    def test_unresolved_pass_constraints_are_visible_and_marks_stay_readable_when_zooming(self):
        document = shared_mirror_roof_scene()
        document.optical_pass("mirror-return").centered = True
        e = self.open(document)
        mirror_id = document.nodes[1].id
        row = e.scene.symbols[mirror_id].constraint_marks
        self.assertIn("pass 2", by_kind(row.specs)["center"].tooltip)
        badge = row.badges["center"]
        self.assertTrue(badge.isVisible())
        self.assertEqual(badge.acceptedMouseButtons(), QtCore.Qt.NoButton)
        before = badge.deviceTransform(e.view.viewportTransform()).mapRect(badge.boundingRect()).size()
        e.view.scale(3, 3)
        self.app.processEvents()
        after = badge.deviceTransform(e.view.viewportTransform()).mapRect(badge.boundingRect()).size()
        self.assertAlmostEqual(before.width(), after.width())
        self.assertAlmostEqual(before.height(), after.height())
        self.assertEqual(e.document.node(mirror_id).physical, document.node(mirror_id).physical)


if __name__ == "__main__":
    unittest.main()
