
"""Worker threads, API task queue, and API debug proxy."""

import logging
import sys
import time
import traceback
from typing import TYPE_CHECKING, Dict, Optional, Tuple

import qbittorrentapi
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from .constants import G_APP_NAME
from .types import TaskCallable, TaskCallback

if TYPE_CHECKING:
    from .main_window import MainWindow

logger = logging.getLogger(G_APP_NAME)

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

    @Slot()
    def run(self) -> None:
        """Execute the worker callable and emit result/error/cancel signals."""
        was_cancelled = False
        try:
            if self.is_cancelled:
                was_cancelled = True
                return
            result = self.fn(*self.args, **self.kwargs)
            if self.is_cancelled:
                was_cancelled = True
                return
            self.signals.result.emit(result)
        except Exception:
            if self.is_cancelled:
                was_cancelled = True
            else:
                exctype, value = sys.exc_info()[:2]
                self.signals.error.emit((exctype, value, traceback.format_exc()))
        finally:
            if was_cancelled:
                self.signals.cancelled.emit()
            self.signals.finished.emit()

class APITaskQueue(QObject):
    """Manages queued API tasks with cancellation support"""

    task_completed = Signal(str, object)  # task_name, result
    task_failed = Signal(str, str)  # task_name, error_message
    task_cancelled = Signal(str)  # task_name

    def __init__(self, parent: Optional[QObject] = None) -> None:
        """Initialize queue state and thread pool."""
        super().__init__(parent)
        self.current_worker: Optional[Worker] = None
        self.is_processing = False
        self.threadpool = QThreadPool()
        self.current_task_name: Optional[str] = None
        self.pending_task: Optional[
            Tuple[
                str,
                TaskCallable,
                Optional[TaskCallback],
                Tuple[object, ...],
                Dict[str, object],
            ]
        ] = None

    def _start_task(
        self,
        task_name: str,
        fn: TaskCallable,
        callback: Optional[TaskCallback],
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
        worker.signals.finished.connect(
            lambda _worker=worker: self._on_worker_finished(_worker)
        )
        self.threadpool.start(worker)

    def add_task(
        self,
        task_name: str,
        fn: TaskCallable,
        callback: Optional[TaskCallback],
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
        callback: Optional[TaskCallback],
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
        error: Tuple[type[BaseException], BaseException, str],
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

    def __init__(self, client: object, owner: "MainWindow") -> None:
        """Wrap one API client and route debug logs via main window hooks."""
        self._client = client
        self._owner = owner

    def __enter__(self) -> "_DebugAPIClientProxy":
        """Enter wrapped context manager while preserving proxy behavior."""
        entered = self._client.__enter__()
        if entered is self._client:
            return self
        return _DebugAPIClientProxy(entered, self._owner)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        """Delegate context-manager exit to wrapped client."""
        return self._client.__exit__(exc_type, exc, tb)

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

