"""Run numerical optimization outside the FreeCAD/Qt interpreter.

The private pipe protocol carries trusted local Python records. Preview and
result records are decoded on the GUI thread, never in a numerical thread.
"""

import os
from pathlib import Path
import pickle
from queue import Empty, Queue
import struct
import subprocess
import sys
from tempfile import TemporaryFile
from threading import Thread


def decode(payload):
    return pickle.loads(payload) if isinstance(payload, bytes) else payload


def _write(stream, kind, value):
    payload = kind + pickle.dumps(value, protocol=4)
    stream.write(struct.pack("!I", len(payload)))
    stream.write(payload)
    stream.flush()


def _read(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError("Incomplete optimizer message header")
    length = struct.unpack("!I", header)[0]
    if not 1 <= length <= 128 * 1024 * 1024:
        raise ValueError("Invalid optimizer message length")
    payload = stream.read(length)
    if len(payload) != length:
        raise ValueError("Incomplete optimizer message")
    return payload[:1], payload[1:]


def _python():
    executable = Path(sys.executable)
    if executable.name.lower().startswith("python"):
        return str(executable)
    # In the desktop application sys.executable may be FreeCAD itself.
    for folder in (executable.parent, Path(sys.prefix) / "bin"):
        for name in ("python", "python3", "python.exe"):
            candidate = folder / name
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError("Cannot locate FreeCAD's bundled Python interpreter")


def _stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _cancelled_result(problem):
    from .optimization import OptimizationResult

    return pickle.dumps(OptimizationResult(
        "cancelled", None, tuple(problem.initial_positions), (), 0, 0, problem,
    ), protocol=4)


def run_optimizer(problem, *, progress=None, cancelled=None):
    """Return a serialized result; a failed child becomes a recoverable error."""
    cancelled = cancelled or (lambda: False)
    if cancelled():
        return _cancelled_result(problem)
    environment = dict(os.environ)
    root = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = root + os.pathsep + environment.get("PYTHONPATH", "")
    messages = Queue()

    def receive(stream):
        try:
            while True:
                message = _read(stream)
                if message is None:
                    break
                messages.put(message)
        except (OSError, ValueError) as error:
            messages.put((b"E", pickle.dumps(str(error), protocol=4)))
        finally:
            messages.put((b"X", b""))

    with TemporaryFile() as errors:
        process = subprocess.Popen(
            [_python(), "-m", "PyOpticL.schematic.optimizer_process"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
            env=environment,
        )
        reader = Thread(target=receive, args=(process.stdout,), daemon=True)
        reader.start()
        try:
            _write(process.stdin, b"Q", problem)
            process.stdin.close()
            while True:
                if cancelled():
                    return _cancelled_result(problem)
                try:
                    kind, payload = messages.get(timeout=0.05)
                except Empty:
                    continue
                if kind == b"P" and progress is not None:
                    progress(payload)
                elif kind == b"R":
                    return payload
                elif kind == b"E":
                    raise RuntimeError("Optimizer process: " + decode(payload))
                elif kind == b"X":
                    try:
                        code = process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        _stop(process)
                        code = process.returncode
                    errors.seek(0)
                    detail = errors.read().decode("utf-8", errors="replace")[-4000:].strip()
                    raise RuntimeError(
                        f"Optimizer process exited unexpectedly (exit {code}). "
                        "The schematic was not changed."
                        + ("\n" + detail if detail else "")
                    )
        finally:
            _stop(process)
            reader.join(timeout=2)
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()


def main():
    import faulthandler
    import traceback
    from .optimization import optimize_layout

    faulthandler.enable()
    try:
        request = _read(sys.stdin.buffer)
        if request is None or request[0] != b"Q":
            raise ValueError("Missing optimizer request")
        problem = decode(request[1])
        result = optimize_layout(problem, progress=lambda frame: _write(sys.stdout.buffer, b"P", frame))
        _write(sys.stdout.buffer, b"R", result)
    except Exception:
        _write(sys.stdout.buffer, b"E", traceback.format_exc())


if __name__ == "__main__":
    main()
