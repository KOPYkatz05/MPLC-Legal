"""State and accounting for sequential upload operations."""

from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import QObject, QThread, Signal

from .workers import UploadOcrWorker, UploadSaveWorker


class UploadOperationState(Enum):
    IDLE = auto()
    OCR_RUNNING = auto()
    SAVING = auto()
    RECONCILING = auto()
    CLOSING = auto()


@dataclass
class UploadBatchCoordinator:
    """Own the non-widget state for one sequential Save All operation."""

    state: UploadOperationState = UploadOperationState.IDLE
    next_index: int = 0
    total: int = 0
    completed: int = 0
    results: list = field(default_factory=list)

    @property
    def saving(self):
        return self.state in {
            UploadOperationState.SAVING,
            UploadOperationState.RECONCILING,
        }

    def begin(self, total):
        self.state = UploadOperationState.SAVING
        self.next_index = 0
        self.total = int(total)
        self.completed = 0
        self.results = []

    def record(self, result):
        self.results.append(result)
        self.completed += 1

    def finish(self):
        self.state = UploadOperationState.IDLE
        self.next_index = 0

    def counts(self):
        return {
            "saved": sum(result.status == "saved" for result in self.results),
            "failed": sum(
                result.status not in {"saved", "skipped"}
                for result in self.results
            ),
            "skipped": sum(
                result.status == "skipped" for result in self.results
            ),
            "warnings": sum(bool(result.warnings) for result in self.results),
        }


class UploadSaveWorkerCoordinator(QObject):
    """Own the QThread/worker lifetime for sequential document saves."""

    result_ready = Signal(int, object)
    idle = Signal()

    def __init__(self, parent=None, worker_factory=None):
        super().__init__(parent)
        self._worker_factory = worker_factory or UploadSaveWorker
        self._thread = None
        self._worker = None

    @property
    def running(self):
        return self._thread is not None

    def start(self, controller, index):
        if self.running:
            return False
        thread = QThread(self)
        worker = self._worker_factory(controller, index)
        worker.moveToThread(thread)
        self._thread = thread
        self._worker = worker
        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_result)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda thread=thread: self._thread_finished(thread)
        )
        thread.start()
        return True

    def _handle_result(self, index, result):
        try:
            self.result_ready.emit(index, result)
        finally:
            if self._thread is not None:
                self._thread.quit()

    def _thread_finished(self, thread):
        if self._thread is not thread:
            return
        self._thread = None
        self._worker = None
        self.idle.emit()


class UploadOcrWorkerCoordinator(QObject):
    """Own the QThread/worker lifetime for one OCR request."""

    result_ready = Signal(int, bool, str, object, str)
    idle = Signal()

    def __init__(
        self,
        parent=None,
        *,
        thread_factory=None,
        worker_factory=None,
    ):
        super().__init__(parent)
        self._thread_factory = thread_factory or (lambda parent: QThread(parent))
        self._worker_factory = worker_factory or UploadOcrWorker
        self._thread = None
        self._worker = None

    @property
    def running(self):
        return self._thread is not None

    def start(self, controller, index, reason):
        if self.running:
            return False
        thread = self._thread_factory(self.parent())
        worker = self._worker_factory(controller, index)
        worker.moveToThread(thread)
        self._thread = thread
        self._worker = worker
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda finished_index, ok, error, result, reason=reason: (
                self._handle_result(
                    finished_index,
                    ok,
                    error,
                    result,
                    reason,
                )
            )
        )
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda thread=thread: self._thread_finished(thread)
        )
        thread.start()
        return True

    def _handle_result(self, index, ok, error, result, reason):
        try:
            self.result_ready.emit(index, ok, error, result, reason)
        finally:
            if self._thread is not None:
                self._thread.quit()

    def _thread_finished(self, thread):
        if self._thread is not thread:
            return
        self._thread = None
        self._worker = None
        self.idle.emit()
