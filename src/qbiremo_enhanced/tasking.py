"""Worker threads, API task queue, and API debug proxy."""

import logging
import sys
import time
import traceback
from typing import Protocol, cast

import qbittorrentapi
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from .constants import SETTINGS_APP_NAME
from .types import TaskCallable, TaskCallback

logger = logging.getLogger(SETTINGS_APP_NAME)

RECOVERABLE_TASK_QUEUE_EXCEPTIONS = (
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)

RECOVERABLE_API_CALL_EXCEPTIONS = (
    ConnectionError,
    OSError,
    qbittorrentapi.APIError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


class _ContextManagedClient(Protocol):
    """Protocol for API clients that can be used as context managers."""

    def __enter__(self) -> object: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool | None: ...


class _DebugLogOwner(Protocol):
    """Protocol for objects that expose API debug logging hooks."""

    def _debug_log_api_call(
        self, method_name: str, args: tuple[object, ...], kwargs: dict[str, object]
    ) -> None: ...

    def _debug_log_api_error(self, method_name: str, error: Exception, elapsed: float) -> None: ...

    def _debug_log_api_response(self, method_name: str, result: object, elapsed: float) -> None: ...


class _EmittableSignal(Protocol):
    """Protocol for Qt-style signal objects exposing `emit`."""

    def emit(self, *args: object) -> None: ...


class WorkerSignals(QObject):
    """Signals available from a running worker thread"""

    finished = Signal()
    error = Signal(tuple)
    result = Signal(object)
    progress = Signal(int)
    cancelled = Signal()


class Worker(QRunnable):
    """Worker thread for background tasks with cancellation support"""

    def __init__(self, fn: TaskCallable, *args: object, **kwargs: object) -> None:
        """Store callable and arguments for one worker execution."""
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.kwargs["progress_callback"] = self.signals.progress
        self.is_cancelled = False

    def cancel(self) -> None:
        """Mark this worker as cancelled."""
        self.is_cancelled = True

    def _is_cancelled_now(self) -> bool:
        """Read cancellation state with a callable boundary for thread-driven updates."""
        return bool(self.is_cancelled)

    def _safe_emit(self, signal: _EmittableSignal, *args: object) -> None:
        """Emit one Qt signal and ignore deleted-source runtime teardown races."""
        try:
            signal.emit(*args)
        except RuntimeError:
            logger.debug("Skipped worker signal emit because signal source was deleted.")

    @Slot()
    def run(self) -> None:
        """Execute the worker callable and emit result/error/cancel signals."""
        was_cancelled = False
        try:
            if self._is_cancelled_now():
                was_cancelled = True
                return
            result = self.fn(*self.args, **self.kwargs)
            if self._is_cancelled_now():
                was_cancelled = True
                return
            self._safe_emit(self.signals.result, result)
        except Exception:
            if self._is_cancelled_now():
                was_cancelled = True
            else:
                exctype, value = sys.exc_info()[:2]
                self._safe_emit(self.signals.error, (exctype, value, traceback.format_exc()))
        finally:
            if was_cancelled:
                self._safe_emit(self.signals.cancelled)
            self._safe_emit(self.signals.finished)


class APITaskQueue(QObject):
    """Manages queued API tasks with cancellation support"""

    task_completed = Signal(str, object)  # task_name, result
    task_failed = Signal(str, str)  # task_name, error_message
    task_cancelled = Signal(str)  # task_name

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize queue state and thread pool."""
        super().__init__(parent)
        self.current_worker: Worker | None = None
        self.is_processing = False
        self.threadpool = QThreadPool()
        self.current_task_name: str | None = None
        self.pending_task: (
            tuple[str, TaskCallable, TaskCallback | None, tuple[object, ...], dict[str, object]]
            | None
        ) = None

    def _start_task(
        self,
        task_name: str,
        fn: TaskCallable,
        callback: TaskCallback | None,
        *args: object,
        **kwargs: object,
    ) -> None:
        """Create one worker and start processing it."""
        self.is_processing = True
        self.current_task_name = task_name

        worker = Worker(fn, *args, **kwargs)
        self.current_worker = worker

        worker.signals.result.connect(
            lambda result, _worker=worker: self._on_task_complete(
                _worker,
                task_name,
                callback,
                result,
            )
        )
        worker.signals.error.connect(
            lambda error, _worker=worker: self._on_task_error(
                _worker,
                task_name,
                error,
            )
        )
        worker.signals.cancelled.connect(
            lambda _worker=worker: self._on_task_cancelled(_worker, task_name)
        )
        worker.signals.finished.connect(lambda _worker=worker: self._on_worker_finished(_worker))
        self.threadpool.start(worker)

    def add_task(
        self,
        task_name: str,
        fn: TaskCallable,
        callback: TaskCallback | None,
        *args: object,
        **kwargs: object,
    ) -> None:
        """Queue a task, coalescing to the latest one while busy."""
        if self.current_worker:
            self.current_worker.cancel()
            self.pending_task = (task_name, fn, callback, args, kwargs)
            self.is_processing = True
            return

        self._start_task(task_name, fn, callback, *args, **kwargs)

    def clear_queue(self) -> None:
        """Cancel the current task and clear any pending replacement."""
        if self.current_worker:
            self.current_worker.cancel()
        self.pending_task = None
        if not self.current_worker:
            self.is_processing = False
            self.current_task_name = None

    def _on_task_complete(
        self,
        worker: Worker,
        task_name: str,
        callback: TaskCallback | None,
        result: object,
    ) -> None:
        """Handle successful task completion for the active worker."""
        if worker is not self.current_worker:
            logger.debug("Ignoring stale task completion: %s", task_name)
            return
        if getattr(worker, "is_cancelled", False):
            logger.debug("Ignoring cancelled task completion: %s", task_name)
            return
        try:
            if callback:
                callback(result)
            self.task_completed.emit(task_name, result)
        except RECOVERABLE_TASK_QUEUE_EXCEPTIONS as e:
            self.task_failed.emit(task_name, str(e))

    def _on_task_error(
        self,
        worker: Worker,
        task_name: str,
        error: tuple[type[BaseException], BaseException, str],
    ) -> None:
        """Handle task failure for the active worker."""
        if worker is not self.current_worker:
            logger.debug("Ignoring stale task error: %s", task_name)
            return
        if getattr(worker, "is_cancelled", False):
            logger.debug("Ignoring cancelled task error: %s", task_name)
            return
        try:
            exctype, value, trace = error
            error_msg = f"{exctype.__name__}: {value}"
            logger.error("Task %s failed:\n%s", task_name, trace)
            self.task_failed.emit(task_name, error_msg)
        except RECOVERABLE_TASK_QUEUE_EXCEPTIONS as e:
            logger.error("Error in _on_task_error for %s: %s", task_name, e)
            self.task_failed.emit(task_name, str(e))

    def _on_task_cancelled(self, worker: Worker, task_name: str) -> None:
        """Handle task cancellation for the active worker."""
        if worker is not self.current_worker:
            return
        try:
            self.task_cancelled.emit(task_name)
        except RECOVERABLE_TASK_QUEUE_EXCEPTIONS as e:
            logger.error("Error in _on_task_cancelled for %s: %s", task_name, e)

    def _on_worker_finished(self, worker: Worker) -> None:
        """Finalize worker state and start the latest pending task."""
        if worker is not self.current_worker:
            return

        self.current_worker = None
        self.current_task_name = None
        self.is_processing = False

        pending = self.pending_task
        self.pending_task = None
        if pending:
            task_name, fn, callback, args, kwargs = pending
            self._start_task(task_name, fn, callback, *args, **kwargs)


class _DebugAPIClientProxy:
    """Proxy that logs qBittorrent API calls and responses."""

    def __init__(self, client: object, owner: _DebugLogOwner) -> None:
        """Wrap one API client and route debug logs via main window hooks."""
        self._client = client
        self._owner = owner

    def __enter__(self) -> "_DebugAPIClientProxy":
        """Enter wrapped context manager while preserving proxy behavior."""
        entered = cast("_ContextManagedClient", self._client).__enter__()
        if entered is self._client:
            return self
        return _DebugAPIClientProxy(entered, self._owner)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        """Delegate context-manager exit to wrapped client."""
        return bool(cast("_ContextManagedClient", self._client).__exit__(exc_type, exc, tb))

    def __getattr__(self, name: str) -> object:
        """Intercept callable attributes to add debug call/response/error logs."""
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def _wrapped(*args: object, **kwargs: object) -> object:
            """Execute one proxied API call with debug timing logs."""
            self._owner._debug_log_api_call(name, args, kwargs)
            start_time = time.time()
            try:
                result = attr(*args, **kwargs)
            except RECOVERABLE_API_CALL_EXCEPTIONS as e:
                elapsed = time.time() - start_time
                self._owner._debug_log_api_error(name, e, elapsed)
                raise
            elapsed = time.time() - start_time
            self._owner._debug_log_api_response(name, result, elapsed)
            return result

        return _wrapped
