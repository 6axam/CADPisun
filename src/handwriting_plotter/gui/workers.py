"""Background generation jobs; UI state remains on the main thread."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .backend import GuiBackend
from .document import ProjectSnapshot


class WorkerSignals(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, str, str)


class GenerationWorker(QRunnable):
    def __init__(self, backend: GuiBackend, snapshot: ProjectSnapshot, revision: int) -> None:
        super().__init__()
        self.backend = backend
        self.snapshot = snapshot
        self.revision = revision
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self.backend.build(self.snapshot)
        except Exception as exc:
            self.signals.failed.emit(self.revision, str(exc), traceback.format_exc())
        else:
            self.signals.succeeded.emit(self.revision, result)
