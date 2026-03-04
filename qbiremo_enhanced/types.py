
"""Shared typing models and call signatures."""

from typing import Callable, Dict, Generic, NotRequired, Optional, TypedDict, TypeVar, cast

T = TypeVar("T")

TaskCallable = Callable[..., object]
TaskCallback = Callable[[object], None]

class APITaskResult(TypedDict, Generic[T]):
    """Describe the standard API task payload envelope."""

    data: T
    elapsed: float
    success: bool
    error: NotRequired[str]

def api_task_result(
    *,
    data: T,
    elapsed: float,
    success: bool,
    error: Optional[str] = None,
    **extra: object,
) -> APITaskResult[T]:
    """Build one API-task payload with consistent envelope keys."""
    payload: Dict[str, object] = {
        "data": data,
        "elapsed": float(elapsed),
        "success": bool(success),
    }
    if error:
        payload["error"] = str(error)
    if extra:
        payload.update(extra)
    return cast(APITaskResult[T], payload)
