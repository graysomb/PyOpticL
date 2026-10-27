"""Keep numerical threads alive independently of their editor or dialog."""

from threading import Event

from .qt import QtCore


_running = set()


def _shutdown():
    workers = tuple(_running)
    for worker in workers:
        worker.cancelled.set()
    for worker in workers:
        worker.wait()


class ManagedWorker(QtCore.QThread):
    def __init__(self, owner=None):
        # A QWidget parent deletes its children immediately, even while a
        # QThread is running. Retain the thread until its own finished signal.
        super().__init__()
        self.cancelled = Event()
        if owner is not None:
            token = self.cancelled
            owner.destroyed.connect(lambda *_: token.set())
        self.finished.connect(self._retire)

    def start(self, *args, **kwargs):
        app = QtCore.QCoreApplication.instance()
        if app is not None and not getattr(app, "_pyopticl_worker_shutdown", False):
            app.aboutToQuit.connect(_shutdown)
            app._pyopticl_worker_shutdown = True
        _running.add(self)
        try:
            super().start(*args, **kwargs)
        except Exception:
            _running.discard(self)
            raise

    @QtCore.Slot()
    def _retire(self):
        _running.discard(self)
        self.deleteLater()
