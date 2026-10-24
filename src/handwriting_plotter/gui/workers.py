"""Background jobs; UI state remains on the main thread."""

from __future__ import annotations

import traceback
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .backend import GuiBackend
from .document import ProjectSnapshot
from handwriting_plotter.learning.htr import (
    HtrCancelled,
    HtrProcessClient,
    HtrProcessError,
    HtrResultRepository,
    HtrRunRecord,
    HtrWorkerRequest,
    new_htr_run,
)


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


class HtrWorkerSignals(QObject):
    progress = Signal(int, int, str)
    succeeded = Signal(object)
    cancelled = Signal(object)
    failed = Signal(object)


class HtrRecognitionWorker(QRunnable):
    """One cancellable external-provider job; no ML library enters the UI process."""

    def __init__(
        self,
        client: HtrProcessClient,
        repository: HtrResultRepository,
        request: HtrWorkerRequest,
        *,
        source_manifest_sha256: str,
        original_sha256: str,
        frame_id: str,
    ) -> None:
        super().__init__()
        self.client = client
        self.repository = repository
        self.request = request
        self.source_manifest_sha256 = source_manifest_sha256
        self.original_sha256 = original_sha256
        self.frame_id = frame_id
        self.signals = HtrWorkerSignals()
        self._cancelled = Event()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancelled.set()

    def _store(self, **values) -> HtrRunRecord:  # noqa: ANN003
        return self.repository.store(new_htr_run(
            source_manifest_sha256=self.source_manifest_sha256,
            original_sha256=self.original_sha256,
            frame_id=self.frame_id,
            request=self.request,
            **values,
        ))

    @Slot()
    def run(self) -> None:
        try:
            lines, revision, model_hash = self.client.recognize(
                self.request,
                progress=lambda completed, total, stage: self.signals.progress.emit(completed, total, stage),
                cancelled=self._cancelled.is_set,
            )
        except HtrCancelled:
            self.signals.cancelled.emit(self._store(status="cancelled", error_code="HTR_CANCELLED"))
        except HtrProcessError as exc:
            self.signals.failed.emit(self._store(
                status="failed", error_code=exc.code, error_message=str(exc),
            ))
        except Exception as exc:
            self.signals.failed.emit(self._store(
                status="failed", error_code="HTR_INTEGRATION_FAILED", error_message=str(exc),
            ))
        else:
            self.signals.succeeded.emit(self._store(
                status="succeeded", lines=lines, model_revision=revision, model_sha256=model_hash,
            ))
