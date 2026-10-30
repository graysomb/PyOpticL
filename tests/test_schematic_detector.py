"""Newport receiver presets, acceptance cone and portable physical export."""

import math
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import unittest

from PyOpticL.schematic import compile_schematic, load_schematic, save_schematic
from PyOpticL.schematic.model import OpticalPass
from PyOpticL.schematic.parts import part_spec
from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_layout import trace_scene
from PyOpticL.schematic.scene_solver import solve_scene
from PyOpticL.schematic.topology import resolve_topology
from test_schematic import chain
from test_schematic_editor import QT_AVAILABLE

if QT_AVAILABLE:
    from PyOpticL.schematic.editor import SchematicEditor, Palette
    from PyOpticL.schematic.qt import QtCore, QtWidgets
    from test_schematic_editor import QtTest


def detector_scene(preset='bracketed', incidence=0):
    document = chain('source', 'detector')
    source, detector = document.nodes
    select_preset(detector, preset)
    a = math.radians(incidence)
    source.physical.update(x=60 * math.cos(a), y=60 * math.sin(a), angle=180 + incidence)
    document.layout = {'poses': {
        source.id: [source.physical['x'], source.physical['y'], 0, 180 + incidence],
        detector.id: [0, 0, 0, 0],
    }}
    return document


class DetectorTests(unittest.TestCase):
    def test_bare_and_bracketed_round_trip_and_export(self):
        for preset in ('bracketed', 'bare'):
            with self.subTest(preset=preset):
                document = detector_scene(preset)
                node = document.nodes[1]
                if preset == 'bracketed':
                    node.parameters['optical_height'] = 50.8
                compiled = compile_schematic(document)
                self.assertTrue(compiled.ok, compiled.diagnostics)
                self.assertIn('catalog.detector(', compiled.source)
                spec = part_spec(document, node, resolve_topology(document))
                self.assertEqual(dict(spec.before)['mounted'], preset == 'bracketed')
                with TemporaryDirectory() as folder:
                    path = Path(folder) / 'detector.json'
                    save_schematic(document, path)
                    restored = load_schematic(path)
                    self.assertEqual(restored.to_dict(), document.to_dict())
                    self.assertEqual(compile_schematic(restored).source, compiled.source)
        document = detector_scene()
        document.nodes[1].parameters['optical_height'] = 25
        self.assertFalse(compile_schematic(document).ok)

    def test_active_area_front_face_and_acceptance_half_angle(self):
        for angle, valid in ((0, True), (19, True), (21, False), (180, False)):
            with self.subTest(angle=angle):
                document = detector_scene(incidence=angle)
                self.assertEqual(trace_scene(document).ok, valid)
        document = detector_scene()
        node = document.nodes[1]
        document.passes.append(OpticalPass(node.id, node.id, 'receive', centered=False))
        source = document.nodes[0]
        for offset, valid in ((.04, True), (.06, False)):
            source.physical['y'] = offset
            document.layout['poses'][source.id][1] = offset
            self.assertEqual(trace_scene(document).ok, valid)

    def test_drag_turns_free_receiver_and_preserves_centered_hit(self):
        document = detector_scene()
        source, node = document.nodes
        source.physical.pop('angle')
        result = solve_scene(document, targets=((node.id, 0, 5), (node.id, 1, 10)))
        self.assertTrue(result.ok, result.diagnostics)
        self.assertAlmostEqual(result.poses[node.id][0], 5, places=6)
        self.assertAlmostEqual(result.poses[node.id][1], 10, places=6)
        self.assertTrue(trace_scene(document, result.poses).ok)


@unittest.skipUnless(QT_AVAILABLE, 'Qt unavailable')
class DetectorEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def settle(self):
        deadline = monotonic() + 15
        while self.editor.workers and monotonic() < deadline:
            self.app.processEvents()
            QtTest.QTest.qWait(5)
        self.app.processEvents()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.assertFalse(self.editor.workers)

    def test_palette_height_control_and_bare_selection(self):
        self.editor = SchematicEditor(detector_scene())
        try:
            self.editor.show()
            self.settle()
            palette = self.editor.findChild(Palette)
            self.assertIn('detector', [palette.item(i).data(QtCore.Qt.UserRole) for i in range(palette.count())])
            node = self.editor.document.nodes[1]
            self.editor.scene.symbols[node.id].setSelected(True)
            self.settle()
            direction = self.editor.findChild(QtWidgets.QDoubleSpinBox, 'outputDirectionDeg')
            self.assertAlmostEqual(abs(direction.value()), 180)
            self.editor.findChild(QtWidgets.QCheckBox, 'outputDirectionConstrained').setChecked(True)
            self.settle()
            self.assertTrue(self.editor.display_trace.ok)
            field = self.editor.findChild(QtWidgets.QDoubleSpinBox, 'componentParameter_optical_height')
            self.assertEqual(field.value(), 25.4)
            field.setValue(38.1)
            self.settle()
            self.assertTrue(compile_schematic(self.editor.document).ok)
            combo = self.editor.findChild(QtWidgets.QComboBox, 'partPreset')
            combo.setCurrentIndex(combo.findData('bare'))
            self.settle()
            self.assertNotIn('optical_height', self.editor.document.node(node.id).parameters)
            self.editor.undo()
            self.settle()
            self.assertEqual(self.editor.document.node(node.id).parameters['optical_height'], 38.1)
        finally:
            self.editor.history.mark_saved()
            self.editor.close()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
