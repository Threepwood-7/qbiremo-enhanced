"""Formatting helpers, path/instance helpers, and platform primitives."""

import fnmatch
import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, cast

from PySide6.QtGui import QIcon

from .constants import (
    APP_ICON_FILE_NAME,
    CACHE_FILE_NAME,
    DEFAULT_DISPLAY_SIZE_MODE,
    DEFAULT_DISPLAY_SPEED_MODE,
    G_APP_NAME,
    INSTANCE_ID_LENGTH,
)
from .models.config import NormalizedConfig
from .runtime_paths import resolve_app_data_dir

logger = logging.getLogger(G_APP_NAME)
_INSTANCE_LOCK_HANDLES: dict[str, BinaryIO] = {}
__all__ = [
    "_append_instance_id_to_filename",
    "_instance_lock_key",
    "_normalize_display_mode",
    "_normalize_http_protocol_scheme",
    "_normalize_instance_counter",
    "_normalize_instance_host",
    "_normalize_instance_port",
    "_release_os_file_lock",
    "_try_acquire_os_file_lock",
    "acquire_instance_lock",
    "calculate_size_buckets",
    "compute_instance_id",
    "compute_instance_id_from_config",
    "format_datetime",
    "format_eta",
    "format_float",
    "format_int",
    "format_size",
    "format_size_mode",
    "format_speed",
    "format_speed_mode",
    "load_app_icon",
    "matches_wildcard",
    "normalize_filter_pattern",
    "parse_tags",
    "release_instance_lock",
    "resolve_cache_file_path",
    "resolve_instance_lock_file_path",
    "settings_app_name_for_instance",
]


def format_float(value: float, decimals: int = 2) -> str:
    """Format float with specified decimals, empty if zero."""
    if value != 0:
        return f"{value:.{decimals}f}"
    return ""


def format_int(value: int) -> str:
    """Format integer with thousands separator, empty if zero."""
    if value != 0:
        return f"{value:,}"
    return ""


def format_datetime(timestamp: int) -> str:
    """Format Unix timestamp, empty if zero."""
    if timestamp > 0:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    return ""


def format_size(bytes_size: int) -> str:
    """Format bytes as human-readable size."""
    return format_size_mode(bytes_size, mode="human_readable")


def format_speed(bytes_per_sec: int) -> str:
    """Format speed in bytes/sec."""
    return format_speed_mode(bytes_per_sec, mode="human_readable")


def _normalize_display_mode(value: object, default: str) -> str:
    """Normalize mode to 'bytes' or 'human_readable'."""
    mode = str(value or default).strip().lower()
    if mode in {"bytes", "human_readable"}:
        return mode
    return default


def format_size_mode(bytes_size: int, mode: str = "human_readable") -> str:
    """Format size according to display mode."""
    mode = _normalize_display_mode(mode, DEFAULT_DISPLAY_SIZE_MODE)
    size_val = int(bytes_size or 0)
    if mode == "bytes":
        return f"{size_val:,}"

    if size_val == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_idx = 0
    size = float(size_val)

    while size >= 1024 and unit_idx < len(units) - 1:
        size /= 1024
        unit_idx += 1

    return f"{size:.2f} {units[unit_idx]}"


def format_speed_mode(bytes_per_sec: int, mode: str = "human_readable") -> str:
    """Format speed according to display mode."""
    speed_val = int(bytes_per_sec or 0)
    if speed_val == 0:
        return ""
    mode = _normalize_display_mode(mode, DEFAULT_DISPLAY_SPEED_MODE)
    if mode == "bytes":
        return f"{speed_val:,}"
    return f"{format_size_mode(speed_val, mode='human_readable')}/s"


def format_eta(seconds: int) -> str:
    """Format ETA seconds to compact human-readable duration."""
    try:
        eta = int(seconds)
    except (TypeError, ValueError, OverflowError):
        return ""

    if eta <= 0:
        return ""

    days, remainder = divmod(eta, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours:02d}h"
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _normalize_instance_host(raw_host: object) -> str:
    """Normalize host input used for per-instance file ID generation."""
    if raw_host is None:
        return "localhost"
    host = str(raw_host).strip()
    return host if host else "localhost"


def _normalize_instance_port(raw_port: object) -> int:
    """Normalize port input used for per-instance file ID generation."""
    if isinstance(raw_port, (int, float, str, bytes, bytearray)):
        try:
            port = int(raw_port)
        except (TypeError, ValueError, OverflowError):
            port = 8080
    else:
        port = 8080
    if port < 1 or port > 65535:
        return 8080
    return port


def _normalize_instance_counter(raw_counter: object) -> int:
    """Normalize per-server instance counter used as instance ID suffix."""
    if isinstance(raw_counter, (int, float, str, bytes, bytearray)):
        try:
            counter = int(raw_counter)
        except (TypeError, ValueError, OverflowError):
            counter = 1
    else:
        counter = 1
    return counter if counter > 0 else 1


def _normalize_http_protocol_scheme(raw_scheme: object) -> str:
    """Normalize WebUI/API protocol scheme to http or https."""
    scheme = str(raw_scheme or "").strip().lower()
    if scheme in ("http", "https"):
        return scheme
    return "http"


def compute_instance_id(
    qb_host: object,
    qb_port: object,
    length: int = INSTANCE_ID_LENGTH,
    instance_counter: object = 1,
) -> str:
    """Compute a short deterministic ID from qb_host + qb_port."""
    host = _normalize_instance_host(qb_host)
    port = _normalize_instance_port(qb_port)
    digest = hashlib.sha1(f"{host}:{port}".encode()).hexdigest()
    try:
        max_len = max(1, int(length))
    except (TypeError, ValueError, OverflowError):
        max_len = INSTANCE_ID_LENGTH
    base_id = digest[:max_len]
    counter = _normalize_instance_counter(instance_counter)
    return f"{base_id}_{counter}"


def compute_instance_id_from_config(config: NormalizedConfig) -> str:
    """Compute instance ID from a config dict using normalized host/port values."""
    cfg: dict[str, object] = dict(config)
    host = cfg.get("qb_host", cfg.get("host", "localhost"))
    port = cfg.get("qb_port", cfg.get("port", 8080))
    counter = cfg.get("_instance_counter", 1)
    return compute_instance_id(host, port, instance_counter=counter)


def _append_instance_id_to_filename(path_value: str, instance_id: str) -> str:
    """Append _<instance_id> before file extension, preserving directory."""
    raw = str(path_value or "").strip()
    if not raw:
        return raw
    ident = str(instance_id or "").strip().lower()
    if not ident:
        return raw
    path_obj = Path(raw)
    suffix_marker = f"_{ident}"
    stem = path_obj.stem
    if stem.lower().endswith(suffix_marker):
        return str(path_obj)
    if path_obj.suffix:
        new_name = f"{stem}{suffix_marker}{path_obj.suffix}"
    else:
        new_name = f"{path_obj.name}{suffix_marker}"
    return str(path_obj.with_name(new_name))


def settings_app_name_for_instance(instance_id: str) -> str:
    """Build QSettings app name for a given instance ID."""
    ident = str(instance_id or "").strip().lower()
    if not ident:
        return G_APP_NAME
    return f"{G_APP_NAME}_{ident}"


def resolve_cache_file_path(
    cache_file_name: str = CACHE_FILE_NAME,
    instance_id: str = "",
) -> Path:
    """Resolve cache file path under app data dir unless absolute override is used."""
    raw_path = Path(str(cache_file_name))
    if instance_id:
        raw_path = Path(_append_instance_id_to_filename(str(raw_path), instance_id))
    if raw_path.is_absolute():
        return raw_path
    return resolve_app_data_dir() / raw_path


def resolve_instance_lock_file_path(instance_id: str, instance_counter: object) -> Path:
    """Resolve one .lck file path for a computed instance id + counter."""
    ident = str(instance_id or "").strip().lower()
    counter = _normalize_instance_counter(instance_counter)
    suffix = f"_{counter}"
    lock_key = ident if ident.endswith(suffix) else f"{ident}{suffix}"
    return resolve_cache_file_path("qbiremo_enhanced.lck", lock_key)


def load_app_icon() -> QIcon:
    """Load the application icon from the script directory when available."""
    module_dir = Path(__file__).resolve().parent
    candidates = (
        module_dir / APP_ICON_FILE_NAME,
        module_dir.parent / APP_ICON_FILE_NAME,
    )
    for icon_path in candidates:
        if icon_path.exists():
            return QIcon(str(icon_path))
    return QIcon()


def _instance_lock_key(lock_path: Path) -> str:
    """Build a stable dictionary key for one lock file path."""
    try:
        return str(Path(lock_path).resolve())
    except (TypeError, ValueError, OSError, RuntimeError):
        return str(Path(lock_path))


def _try_acquire_os_file_lock(handle: BinaryIO) -> bool:
    """Try to acquire a non-blocking exclusive lock on one open file handle."""
    try:
        if os.name == "nt":
            import msvcrt

            locking = getattr(msvcrt, "locking", None)
            lock_non_blocking = getattr(msvcrt, "LK_NBLCK", None)
            if not callable(locking) or not isinstance(lock_non_blocking, int):
                return False
            handle.seek(0)
            locking(handle.fileno(), lock_non_blocking, 1)
            return True

        import fcntl

        flock = getattr(fcntl, "flock", None)
        lock_ex = getattr(fcntl, "LOCK_EX", None)
        lock_nb = getattr(fcntl, "LOCK_NB", None)
        if not callable(flock) or not isinstance(lock_ex, int) or not isinstance(lock_nb, int):
            return False
        flock(handle.fileno(), lock_ex | lock_nb)
        return True
    except (AttributeError, ImportError, OSError, ValueError):
        return False


def _release_os_file_lock(handle: BinaryIO) -> None:
    """Best-effort release of an OS-level file lock."""
    try:
        if os.name == "nt":
            import msvcrt

            locking = getattr(msvcrt, "locking", None)
            lock_unlock = getattr(msvcrt, "LK_UNLCK", None)
            if not callable(locking) or not isinstance(lock_unlock, int):
                return
            handle.seek(0)
            locking(handle.fileno(), lock_unlock, 1)
            return

        import fcntl

        flock = getattr(fcntl, "flock", None)
        lock_un = getattr(fcntl, "LOCK_UN", None)
        if callable(flock) and isinstance(lock_un, int):
            flock(handle.fileno(), lock_un)
    except (AttributeError, ImportError, OSError, ValueError):
        logger.debug("Failed to release OS file lock", exc_info=True)


def acquire_instance_lock(
    config: NormalizedConfig,
    start_counter: object,
) -> tuple[int, str, Path]:
    """Acquire an exclusive .lck file lock; auto-increment counter when in use."""
    cfg = cast("NormalizedConfig", dict(config))
    counter = _normalize_instance_counter(start_counter)

    while True:
        cfg["_instance_counter"] = int(counter)
        instance_id = compute_instance_id_from_config(cfg)
        lock_path = resolve_instance_lock_file_path(instance_id, counter)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = lock_path.open("a+b")
        except OSError as e:
            raise RuntimeError(f"Failed to open lock file {lock_path}: {e}") from e

        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                # Ensure one lockable byte exists for Windows byte-range locking.
                handle.write(b"\n")
                handle.flush()
            handle.seek(0)
            if not _try_acquire_os_file_lock(handle):
                handle.close()
                counter += 1
                continue

            payload = (f"instance_id={instance_id}\ninstance_counter={counter}\n").encode()
            handle.seek(0)
            handle.truncate(0)
            handle.write(payload)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass

            _INSTANCE_LOCK_HANDLES[_instance_lock_key(lock_path)] = handle
            return int(counter), str(instance_id), lock_path
        except (OSError, ValueError, RuntimeError):
            try:
                handle.close()
            except OSError:
                pass
            raise


def release_instance_lock(lock_path: Path) -> None:
    """Best-effort release/removal of an instance .lck file on shutdown."""
    key = _instance_lock_key(Path(lock_path))
    handle = _INSTANCE_LOCK_HANDLES.pop(key, None)
    if handle is not None:
        try:
            _release_os_file_lock(handle)
        finally:
            try:
                handle.close()
            except OSError:
                pass
    try:
        Path(lock_path).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.debug("Failed to remove lock file: %s", lock_path, exc_info=True)


def parse_tags(tags: object) -> list[str]:
    """Parse tags from qBittorrentAPI into a list of strings."""
    if not tags:
        return []
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    if isinstance(tags, (list, tuple, set)):
        return [str(t) for t in tags]
    return []


def matches_wildcard(text: str, pattern: str) -> bool:
    """Check if text matches DOS-style wildcard pattern."""
    if not pattern:
        return True
    return fnmatch.fnmatch(text.lower(), pattern.lower())


def normalize_filter_pattern(raw_pattern: str) -> str:
    """Normalize filter input: plain text becomes a contains wildcard pattern."""
    pattern = (raw_pattern or "").strip()
    if not pattern:
        return ""
    if "*" in pattern or "?" in pattern:
        return pattern
    return f"*{pattern}*"


def calculate_size_buckets(min_size: int, max_size: int, count: int = 5) -> list[tuple]:
    """Calculate size bucket ranges."""
    if min_size >= max_size or count < 1:
        return []

    buckets = []
    range_size = (max_size - min_size) / count

    for i in range(count):
        start = int(min_size + (i * range_size))
        end = int(min_size + ((i + 1) * range_size))
        buckets.append((start, end))

    return buckets
