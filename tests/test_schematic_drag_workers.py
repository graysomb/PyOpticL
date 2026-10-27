"""Drag responsiveness and thread lifetime regressions from an 11-part layout."""

from copy import deepcopy
from threading import Event
from time import monotonic
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

from PyOpticL.schematic.registry import select_preset
from PyOpticL.schematic.scene_layout import trace_scene
from PyOpticL.schematic.scene_solver import solve_scene
from test_schematic import chain
from test_schematic_editor import QT_AVAILABLE

if QT_AVAILABLE:
    import test_schematic_physical_editor as physical_tests
    from test_schematic_editor import QtTest


def optics_layout():
    document = chain("fiber_source", "hwp", "mirror", "mirror", "grating", "lens",
                     "lens", "grating", "mirror", "mirror", "fiber_output")
    points = (
        (3.971818, -73.694202, -98.0007880487067),
        (1.573898526977804, -90.75458301785866, 81.9992119512933),
        (-2.9986369725414095, -123.28661702363969, 400.8222455264652),
        (32.21007723646984, -123.50459863433314, 501.0277635384269),
        (26.054781482770398, -95.53256439475368, 102.4102479752167),
        (64.00004961924328, -95.01443869749924, 0.7822996751571545),
        (102.04980989989708, -94.49488620666236, 0.7822996751571738),
        (146.05706975330426, -93.89398671864723, 360.78229967515716),
        (139.48208767735514, -64.0147362143098, 334.42836970917995),
        (158.30575766758855, -54.65153974628748, 246.48448413153915),
        (166.8611680084086, -83.49256874839124, 106.52247681993516),
    )
    for node in document.nodes:
        preset = {"fiber_source": "POLARIS-K05T6", "fiber_output": "POLARIS-K05T6",
                  "mirror": "POLARIS-K05VS2", "hwp": "FBR", "grating": "MK05S",
                  "lens": "POLARIS-L1G"}[node.kind]
        select_preset(node, preset)
        if node.kind == "lens":
            node.parameters["diameter"] = 25.4
    document.nodes[4].parameters["mirrored"] = 1
    document.layout = {"poses": {node.id: [x, y, 0, angle]
                                for node, (x, y, angle) in zip(document.nodes, points)}}
    document.nodes[0].physical.update(x=points[0][0], y=points[0][1])
    return document


class DragGeometryTests(unittest.TestCase):
    def test_ordinary_moves_on_eleven_part_layout_avoid_long_numerical_searches(self):
        document = optics_layout()
        self.assertTrue(trace_scene(document).ok)
        before = deepcopy(document.to_dict())
        for ref in ("M1", "HWP1", "L1", "L2", "G1", "FO1"):
            with self.subTest(ref=ref):
                node = next(n for n in document.nodes if n.reference == ref)
                pose = document.layout["poses"][node.id]
                result = solve_scene(document, targets=((node.id, 0, pose[0] + 2),
                                                       (node.id, 1, pose[1] + 1)),
                                     iterations=40, report=False)
                self.assertTrue(result.ok, result.diagnostics)
                self.assertLessEqual(result.iterations, 2)
                self.assertAlmostEqual(result.poses[node.id][0], pose[0] + 2, delta=1e-6)
                self.assertAlmostEqual(result.poses[node.id][1], pose[1] + 1, delta=1e-6)
                self.assertTrue(trace_scene(document, result.poses).ok)
        self.assertEqual(document.to_dict(), before)


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable")
class WorkerLifetimeTests(unittest.TestCase):
    def test_destroying_owner_during_scene_or_layout_solve_does_not_abort_qt(self):
        script = textwrap.dedent('''
            from threading import Event
            from time import monotonic, sleep
            from unittest.mock import patch
            from PyOpticL.schematic.qt import QtCore, QtWidgets
            from PyOpticL.schematic.physical_editor import SceneWorker
            from PyOpticL.schematic.optimize_dialog import LayoutWorker
            from PyOpticL.schematic.scene_solver import SceneSolution
            from PyOpticL.schematic.workers import _running
            from test_schematic import chain
            app = QtWidgets.QApplication([])
            for kind in ('scene', 'layout'):
                owner = QtWidgets.QWidget()
                entered = Event()
                def solve(*args, **kwargs):
                    entered.set()
                    while not kwargs['cancelled']():
                        sleep(.001)
                    sleep(.05)
                    return SceneSolution('cancelled', None, {}, [])
                name = ('PyOpticL.schematic.physical_editor.solve_scene' if kind == 'scene'
                        else 'PyOpticL.schematic.optimize_dialog.optimize_layout')
                with patch(name, side_effect=solve):
                    worker = (SceneWorker(chain('source', 'output'), 0, parent=owner)
                              if kind == 'scene' else LayoutWorker(None, owner))
                    worker.start()
                    assert entered.wait(3)
                    owner.deleteLater()
                    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
                    assert worker.parent() is None
                    assert worker.cancelled.is_set()
                    deadline = monotonic() + 5
                    while _running and monotonic() < deadline:
                        app.processEvents()
                        sleep(.001)
                    assert not _running
            owner = QtWidgets.QWidget()
            with patch('PyOpticL.schematic.physical_editor.solve_scene', side_effect=solve):
                worker = SceneWorker(chain('source', 'output'), 0, parent=owner)
                token = worker.cancelled
                entered.clear()
                worker.start()
                assert entered.wait(3)
                QtCore.QTimer.singleShot(10, app.quit)
                (getattr(app, 'exec', None) or app.exec_)()
                assert token.is_set()
                assert all(not w.isRunning() for w in _running)
            print('Owner destruction survived for both workers')
        ''')
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@unittest.skipUnless(QT_AVAILABLE, "Qt unavailable")
class DragSchedulingTests(unittest.TestCase):
    if QT_AVAILABLE:
        setUpClass = classmethod(physical_tests.PhysicalEditorTests.setUpClass.__func__)
        setUp = physical_tests.PhysicalEditorTests.setUp
        tearDown = physical_tests.PhysicalEditorTests.tearDown
        open = physical_tests.PhysicalEditorTests.open

    def settle(self):
        deadline = monotonic() + 15
        while self.editor.workers and monotonic() < deadline:
            self.app.processEvents()
            QtTest.QTest.qWait(5)
        self.app.processEvents()
        self.assertFalse(self.editor.workers)

    def test_rapid_drag_coalesces_requests_and_keeps_latest_drop_as_one_edit(self):
        e = self.open(optics_layout())
        node = e.document.nodes[2]
        pose = e.document.layout["poses"][node.id]
        before = deepcopy(e.document.to_dict())
        entered, release = Event(), Event()
        calls = []

        def solve(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                entered.set()
                release.wait(3)
            return solve_scene(*args, **kwargs)

        index = e.history.index
        with patch("PyOpticL.schematic.physical_editor.solve_scene", side_effect=solve):
            e.begin_drag()
            e.start_solve(((node.id, 0, pose[0] + 1), (node.id, 1, pose[1] + .5)))
            self.assertTrue(entered.wait(3))
            try:
                for i in range(50):
                    final = i == 49
                    e.start_solve(((node.id, 0, pose[0] + 2), (node.id, 1, pose[1] + 1)), final)
                    self.assertEqual(len(e.workers), 1)
                self.assertIsNotNone(e.pending_solve)
            finally:
                release.set()
            self.settle()
        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[0]["report"])
        self.assertTrue(calls[1]["report"])
        self.assertEqual(e.history.index, index + 1)
        self.assertAlmostEqual(e.document.layout["poses"][node.id][0], pose[0] + 2, delta=1e-6)
        self.assertTrue(e.display_trace.ok)
        e.undo()
        self.settle()
        self.assertEqual(e.document.to_dict(), before)
