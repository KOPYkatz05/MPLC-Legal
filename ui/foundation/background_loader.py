"""Reusable Qt background loading with latest-request-wins semantics.

The operation passed to :class:`LatestRequestLoader` runs on a ``QThreadPool``
thread and must not read or mutate widgets. Results are delivered back through
this QObject, so callbacks and public signals run on the loader's Qt thread
(normally the UI thread).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal, Slot


logger = logging.getLogger(__name__)

Operation = Callable[[], Any]
SuccessCallback = Callable[[Any], None]
ErrorCallback = Callable[[Exception], None]


class _LoadSignals(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, object)


class _LoadTask(QRunnable):
    def __init__(self, generation: int, operation: Operation):
        super().__init__()
        self.generation = generation
        self.operation = operation
        self.signals = _LoadSignals()

    @Slot()
    def run(self):
        try:
            result = self.operation()
        except Exception as exc:
            self.signals.failed.emit(self.generation, exc)
        else:
            self.signals.succeeded.emit(self.generation, result)


@dataclass(frozen=True)
class _Request:
    generation: int
    operation: Operation
    on_success: SuccessCallback | None
    on_error: ErrorCallback | None


class LatestRequestLoader(QObject):
    """Run one background operation at a time and retain only the newest retry.

    Calling :meth:`request` while an operation is running replaces any queued
    request. The running operation is allowed to finish, but its stale result is
    ignored before the newest queued request starts.

    ``thread_pool`` is injectable for focused tests. A synchronous test pool
    only needs a ``start(task)`` method that calls ``task.run()``.
    """

    busy_changed = Signal(bool)
    started = Signal(int)
    succeeded = Signal(int, object)
    failed = Signal(int, object)
    settled = Signal(int)

    def __init__(self, parent: QObject | None = None, *, thread_pool=None):
        super().__init__(parent)
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._generation = 0
        self._busy = False
        self._active_request: _Request | None = None
        self._active_task: _LoadTask | None = None
        self._pending_request: _Request | None = None

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def generation(self) -> int:
        return self._generation

    def request(
        self,
        operation: Operation,
        *,
        on_success: SuccessCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> int:
        """Queue ``operation`` and return its monotonically increasing ID."""

        self._require_owner_thread()
        if not callable(operation):
            raise TypeError("operation must be callable")
        if on_success is not None and not callable(on_success):
            raise TypeError("on_success must be callable")
        if on_error is not None and not callable(on_error):
            raise TypeError("on_error must be callable")

        self._generation += 1
        request = _Request(
            self._generation,
            operation,
            on_success,
            on_error,
        )
        if self._active_request is not None:
            self._pending_request = request
        else:
            self._set_busy(True)
            self._start(request)
        return request.generation

    def cancel(self) -> int:
        """Invalidate in-flight output and discard queued work.

        Python/HTTP operations cannot be safely interrupted, so a running task
        is allowed to finish. Its result will not be delivered.
        """

        self._require_owner_thread()
        self._generation += 1
        self._pending_request = None
        if self._active_request is None:
            self._set_busy(False)
        return self._generation

    def _start(self, request: _Request):
        task = _LoadTask(request.generation, request.operation)
        task.signals.succeeded.connect(self._handle_success)
        task.signals.failed.connect(self._handle_failure)
        self._active_request = request
        self._active_task = task
        self.started.emit(request.generation)
        self._thread_pool.start(task)

    @Slot(int, object)
    def _handle_success(self, generation: int, result: object):
        request = self._active_request
        if request is None or request.generation != generation:
            return
        if generation == self._generation and self._pending_request is None:
            self._invoke_callback(request.on_success, result)
            self.succeeded.emit(generation, result)
            self.settled.emit(generation)
        self._finish(generation)

    @Slot(int, object)
    def _handle_failure(self, generation: int, error: object):
        request = self._active_request
        if request is None or request.generation != generation:
            return
        if not isinstance(error, Exception):
            error = RuntimeError(str(error))
        if generation == self._generation and self._pending_request is None:
            self._invoke_callback(request.on_error, error)
            self.failed.emit(generation, error)
            self.settled.emit(generation)
        self._finish(generation)

    def _finish(self, generation: int):
        request = self._active_request
        if request is None or request.generation != generation:
            return
        self._active_request = None
        self._active_task = None

        pending = self._pending_request
        self._pending_request = None
        if pending is not None:
            self._start(pending)
        else:
            self._set_busy(False)

    def _set_busy(self, busy: bool):
        busy = bool(busy)
        if self._busy == busy:
            return
        self._busy = busy
        self.busy_changed.emit(busy)

    @staticmethod
    def _invoke_callback(callback, value):
        if callback is None:
            return
        try:
            callback(value)
        except Exception:
            logger.exception("A background-loader UI callback failed")

    def _require_owner_thread(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError(
                "LatestRequestLoader requests must be made from its owning Qt thread"
            )


__all__ = ["LatestRequestLoader"]
