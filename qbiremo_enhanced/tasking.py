
"""Worker threads, API task queue, and API debug proxy."""

import logging
import sys
import time
import traceback
from typing import Any, Callable, Dict, Optional, Tuple, TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Slot, Signal, QThreadPool

from .constants import G_APP_NAME

if TYPE_CHECKING:
    from .main_window import MainWindow


logger = logging.getLogger(G_APP_NAME)

class WorkerSignals(QObject):
    """Signals available from a running worker thread"""
    finished = Signal()
    error = Signal(tuple)
    result = Signal(object)
    progress = Signal(int)
    cancelled = Signal()

class Worker(QRunnable):
    """Worker thread for background tasks with cancellation support"""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Store callable and arguments for execution in a worker thread.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: None.
        """
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.kwargs["progress_callback"] = self.signals.progress
        self.is_cancelled = False

    def cancel(self) -> None:
        """Cancel this worker.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: None.
        """
        self.is_cancelled = True

    @Slot()
    def run(self) -> None:
        """Execute the worker function.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
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
        """Initialize queue state and threadpool used for API tasks.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: None.
        """
        super().__init__(parent)
        self.current_worker: Optional[Worker] = None
        self.is_processing = False
        self.threadpool = QThreadPool()
        self.current_task_name: Optional[str] = None
        self.pending_task: Optional[
            Tuple[
                str,
                Callable[..., Any],
                Optional[Callable[[Any], None]],
                Tuple[Any, ...],
                Dict[str, Any],
            ]
        ] = None

    def _start_task(
        self,
        task_name: str,
        fn: Callable[..., Any],
        callback: Optional[Callable[[Any], None]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Create one worker and start processing.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: None.
        """
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
        fn: Callable[..., Any],
        callback: Optional[Callable[[Any], None]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Add a task to the queue, coalescing to latest while one is running.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: None.
        """
        if self.current_worker:
            self.current_worker.cancel()
            self.pending_task = (task_name, fn, callback, args, kwargs)
            self.is_processing = True
            return

        self._start_task(task_name, fn, callback, *args, **kwargs)

    def clear_queue(self) -> None:
        """Cancel current task and drop any queued replacement task.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: None.
        """
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
        callback: Optional[Callable[[Any], None]],
        result: Any,
    ) -> None:
        """Handle successful task completion.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
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
        except Exception as e:
            self.task_failed.emit(task_name, str(e))

    def _on_task_error(self, worker: Worker, task_name: str, error: Tuple[Any, Any, str]) -> None:
        """Handle task failure.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
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
        except Exception as e:
            logger.error("Error in _on_task_error for %s: %s", task_name, e)
            self.task_failed.emit(task_name, str(e))

    def _on_task_cancelled(self, worker: Worker, task_name: str) -> None:
        """Handle task cancellation.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        if worker is not self.current_worker:
            return
        try:
            self.task_cancelled.emit(task_name)
        except Exception as e:
            logger.error("Error in _on_task_cancelled for %s: %s", task_name, e)

    def _on_worker_finished(self, worker: Worker) -> None:
        """Finalize worker lifecycle and start latest pending task, if any.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: None.
        """
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

    def __init__(self, client: Any, owner: "MainWindow") -> None:
        """Wrap one API client and route log events through the main window.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: None.
        """
        self._client = client
        self._owner = owner

    def __enter__(self) -> "_DebugAPIClientProxy":
        """Enter wrapped context manager and preserve proxy behavior.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: Propagates unexpected exceptions unless explicitly handled by caller or runtime.
        """
        entered = self._client.__enter__()
        if entered is self._client:
            return self
        return _DebugAPIClientProxy(entered, self._owner)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        """Delegate context-manager exit to wrapped client.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: Propagates unexpected exceptions unless explicitly handled by caller or runtime.
        """
        return self._client.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str) -> Any:
        """Intercept callable attributes to add call/response/error logging.

        Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            """Execute one proxied API call with debug timing logs.

            Side effects: Coordinates worker lifecycle, callbacks, and/or debug logging side effects.
            Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
            """
            self._owner._debug_log_api_call(name, args, kwargs)
            start_time = time.time()
            try:
                result = attr(*args, **kwargs)
            except Exception as e:
                elapsed = time.time() - start_time
                self._owner._debug_log_api_error(name, e, elapsed)
                raise
            elapsed = time.time() - start_time
            self._owner._debug_log_api_response(name, result, elapsed)
            return result

        return _wrapped
