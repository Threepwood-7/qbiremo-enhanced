"""Shared typing models and call signatures."""

from collections.abc import Callable
from typing import Generic, NotRequired, TypedDict, TypeVar, cast

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
    error: str | None = None,
    **extra: object,
) -> APITaskResult[T]:
    """Build one API-task payload with consistent envelope keys."""
    payload: dict[str, object] = {
        "data": data,
        "elapsed": float(elapsed),
        "success": bool(success),
    }
    if error:
        payload["error"] = str(error)
    if extra:
        payload.update(extra)
    return cast("APITaskResult[T]", payload)
