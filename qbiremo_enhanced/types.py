
"""Shared typing models and call signatures."""

from typing import Any, Callable, Dict, Optional, NotRequired, TypedDict, cast


TaskCallable = Callable[..., Any]
TaskCallback = Callable[[Any], None]

class APITaskResult(TypedDict):
    """Standard task payload envelope used by API queue workers."""

    data: Any
    elapsed: float
    success: bool
    error: NotRequired[str]

def api_task_result(
    *,
    data: Any,
    elapsed: float,
    success: bool,
    error: Optional[str] = None,
    **extra: Any,
) -> APITaskResult:
    """Create one API-task payload with consistent success/error/data/elapsed keys.

    Side effects: None.
    Failure modes: None.
    """
    payload: Dict[str, Any] = {
        "data": data,
        "elapsed": float(elapsed),
        "success": bool(success),
    }
    if error:
        payload["error"] = str(error)
    if extra:
        payload.update(extra)
    return cast(APITaskResult, payload)
