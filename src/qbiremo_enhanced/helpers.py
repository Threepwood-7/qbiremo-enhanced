"""Application-specific helpers that are not shared in threep_commons."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import cast

from PySide6.QtGui import QIcon

from .constants import APP_ICON_FILE_NAME


def load_app_icon() -> QIcon:
    """Load the application icon from package-relative locations."""

    module_dir = Path(__file__).resolve().parent
    candidates = (
        module_dir / APP_ICON_FILE_NAME,
        module_dir.parent / APP_ICON_FILE_NAME,
    )
    for icon_path in candidates:
        if icon_path.exists():
            return QIcon(str(icon_path))
    return QIcon()


def parse_tags(tags: object) -> list[str]:
    """Parse qBittorrent tag payloads into a normalized string list."""

    if not tags:
        return []
    if isinstance(tags, str):
        return [token.strip() for token in tags.split(",") if token.strip()]
    if isinstance(tags, (list, tuple, set)):
        values = cast("list[object] | tuple[object, ...] | set[object]", tags)
        return [str(token) for token in values]
    return []


def matches_wildcard(text: str, pattern: str) -> bool:
    """Check whether text matches a wildcard filter pattern."""

    if not pattern:
        return True
    return fnmatch.fnmatch(text.lower(), pattern.lower())


def normalize_filter_pattern(raw_pattern: str) -> str:
    """Normalize raw text into wildcard form when explicit wildcards are missing."""

    pattern = (raw_pattern or "").strip()
    if not pattern:
        return ""
    if "*" in pattern or "?" in pattern:
        return pattern
    return f"*{pattern}*"


def calculate_size_buckets(
    min_size: int,
    max_size: int,
    count: int = 5,
) -> list[tuple[int, int]]:
    """Compute size bucket ranges used by filter UI grouping."""

    if min_size >= max_size or count < 1:
        return []
    buckets: list[tuple[int, int]] = []
    range_size = (max_size - min_size) / count
    for index in range(count):
        start = int(min_size + (index * range_size))
        end = int(min_size + ((index + 1) * range_size))
        buckets.append((start, end))
    return buckets
