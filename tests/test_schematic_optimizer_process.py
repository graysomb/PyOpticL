"""Subprocess parity, failure containment and cancellation without CAD or Qt."""

from io import BytesIO
import math
import pickle
import subprocess
from threading import Event, Timer
from time import monotonic
import unittest
from unittest.mock import patch

from PyOpticL.schematic.optimization import (
    OptimizationOptions, PackingBox, build_problem, optimize_layout,
)
from PyOpticL.schematic.optimizer_process import _read, _write, decode, run_optimizer
from test_schematic import chain
from test_schematic_optimization import bounds, folding_fixture


def small_problem():
    document = folding_fixture()
    return build_problem(document, bounds(document), PackingBox(-10, -10, 240, 180),
                         OptimizationOptions(starts=2, iterations=5, projection_passes=2))


def child_launcher(script, processes):
    # Read the real request before failing/stalling so startup pipe timing does
    # not turn the intended runtime failure into a BrokenPipeError.
    popen = subprocess.Popen
    prelude = (
        "import sys; from PyOpticL.schematic.optimizer_process import _read; "
        "request = _read(sys.stdin.buffer); "
    )

    def launch(command, **kwargs):
        process = popen([command[0], "-c", prelude + script], **kwargs)
        processes.append(process)
        return process

    return launch


class OptimizerProcessTests(unittest.TestCase):
    def test_search_matches_direct_solver_and_preserves_snapshot(self):
        problem = small_problem()
        before = pickle.dumps(problem)
        frames = []
        result = decode(run_optimizer(problem, progress=frames.append))
        self.assertEqual(result, optimize_layout(problem))
        self.assertEqual(pickle.dumps(problem), before)
        self.assertEqual(result.status, "feasible")
        self.assertTrue(frames)
        self.assertTrue(all(isinstance(frame, bytes) for frame in frames))
        self.assertGreater(decode(frames[-1]).total_iterations, 0)

    def test_physical_scene_with_rotation_and_position_pins_matches_direct_solver(self):
        document = chain("source", "mirror", "output")
        source, mirror, output = document.nodes
        source.physical.update(x=0, y=0, angle=0)
        output.physical.update(x=80, y=40)
        document.connections[0].length = 50
        mirror.physical["yaw"] = math.degrees(math.atan2(.8, -.4))
        document.layout = {"poses": {
            source.id: [0, 0, 0, 0], mirror.id: [50, 0, 0, mirror.physical["yaw"]],
            output.id: [80, 40, 0, 0],
        }}
        problem = build_problem(document, bounds(document), PackingBox(-10, -10, 240, 180),
                                OptimizationOptions(starts=2, iterations=3, projection_passes=1))
        self.assertTrue(problem.physical_scene)
        result = decode(run_optimizer(problem))
        self.assertEqual(result, optimize_layout(problem))
        self.assertEqual(result.status, "feasible")

    def test_abnormal_exit_is_recoverable_and_child_is_reaped(self):
        processes = []
        with patch("PyOpticL.schematic.optimizer_process.subprocess.Popen",
                   side_effect=child_launcher("import os; os._exit(23)", processes)):
            with self.assertRaisesRegex(RuntimeError, "exited unexpectedly.*23"):
                run_optimizer(small_problem())
        self.assertEqual(processes[0].poll(), 23)
        self.assertEqual(decode(run_optimizer(small_problem())).status, "feasible")

    def test_cancel_terminates_stalled_child_promptly(self):
        processes = []
        cancelled = Event()
        timer = Timer(.5, cancelled.set)
        start = monotonic()
        timer.start()
        try:
            with patch("PyOpticL.schematic.optimizer_process.subprocess.Popen",
                       side_effect=child_launcher("import time; time.sleep(60)", processes)):
                result = decode(run_optimizer(small_problem(), cancelled=cancelled.is_set))
            self.assertEqual(result.status, "cancelled")
            self.assertLess(monotonic() - start, 4)
            self.assertIsNotNone(processes[0].poll())
        finally:
            timer.cancel()

    def test_cancel_before_launch_does_not_start_child(self):
        with patch("PyOpticL.schematic.optimizer_process.subprocess.Popen") as launch:
            self.assertEqual(decode(run_optimizer(small_problem(), cancelled=lambda: True)).status,
                             "cancelled")
            launch.assert_not_called()

    def test_pipe_round_trip_and_truncated_messages(self):
        stream = BytesIO()
        problem = small_problem()
        _write(stream, b"Q", problem)
        stream.seek(0)
        kind, payload = _read(stream)
        self.assertEqual(kind, b"Q")
        self.assertEqual(decode(payload), problem)
        self.assertIsNone(_read(stream))
        for data in (b"\x00", stream.getvalue()[:-1], b"\x00\x00\x00\x00"):
            with self.subTest(data=data[:4]), self.assertRaises(ValueError):
                _read(BytesIO(data))


if __name__ == "__main__":
    unittest.main()
