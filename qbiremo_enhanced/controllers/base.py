"""Base controller primitives and shared exception policy."""

import json
import logging
import subprocess
from typing import TYPE_CHECKING

import qbittorrentapi

from ..constants import G_APP_NAME

if TYPE_CHECKING:
    from ..main_window import MainWindow


logger = logging.getLogger(G_APP_NAME)

RECOVERABLE_CONTROLLER_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    json.JSONDecodeError,
    KeyError,
    LookupError,
    OSError,
    qbittorrentapi.APIError,
    RuntimeError,
    subprocess.SubprocessError,
    TimeoutError,
    TypeError,
    ValueError,
)


class WindowControllerBase:
    """Proxy unknown attribute access/assignment to the owning MainWindow."""

    def __init__(self, window: "MainWindow") -> None:
        object.__setattr__(self, "window", window)

    def __getattr__(self, name: str) -> object:
        return getattr(self.window, name)

    def __setattr__(self, name: str, value: object) -> None:
        if name == "window":
            object.__setattr__(self, name, value)
            return
        setattr(self.window, name, value)
