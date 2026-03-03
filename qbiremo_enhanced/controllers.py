
"""Feature controllers for MainWindow composition."""

import argparse
import base64
import copy
import html
import json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple, Callable, TYPE_CHECKING
from urllib.parse import quote, urlparse

import qbittorrentapi
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)

from .constants import *
from .dialogs import *
from .tasking import _DebugAPIClientProxy
from .types import APITaskResult, api_task_result
from .utils import *

if TYPE_CHECKING:
    from .main_window import MainWindow


logger = logging.getLogger(G_APP_NAME)


class WindowControllerBase:
    """Proxy unknown attribute access/assignment to the owning MainWindow."""

    def __init__(self, window: "MainWindow") -> None:
        object.__setattr__(self, "window", window)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.window, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "window":
            object.__setattr__(self, name, value)
            return
        setattr(self.window, name, value)


class NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem variant that sorts by one numeric key."""

    def __init__(self, display_text: str, sort_value: float = 0.0) -> None:
        super().__init__(display_text)
        self._sort_value = sort_value

    def __lt__(self, other) -> bool:
        if isinstance(other, NumericTableWidgetItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


class NetworkApiController(WindowControllerBase):
    def _build_connection_info(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Build qBittorrent connection info from TOML config with env var fallback.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        # Host URL ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â may contain scheme, basic-auth credentials, and port
        raw_host = (
            config.get('qb_host')
            or "localhost"
        )
        scheme_override = _normalize_http_protocol_scheme(
            config.get("http_protocol_scheme", "http")
        )
        explicit_scheme_override = "http_protocol_scheme" in config

        extra_headers = {}
        host = raw_host

        # Parse URL to extract HTTP basic auth if embedded
        if '://' in raw_host:
            parsed = urlparse(raw_host)
            http_user = (
                parsed.username
                or config.get('http_basic_auth_username', '')
            )
            http_pass = (
                parsed.password
                or config.get('http_basic_auth_password', '')
            )
            # Rebuild host without credentials
            netloc_host = parsed.hostname or 'localhost'
            if parsed.port:
                netloc_host = f"{netloc_host}:{parsed.port}"
            parsed_scheme = _normalize_http_protocol_scheme(parsed.scheme or "http")
            final_scheme = scheme_override if explicit_scheme_override else parsed_scheme
            host = f"{final_scheme}://{netloc_host}"
        else:
            http_user = (
                config.get('http_basic_auth_username', '')
            )
            http_pass = (
                config.get('http_basic_auth_password', '')
            )
            host = f"{scheme_override}://{str(raw_host).strip() or 'localhost'}"

        # Also allow standalone config keys
        if not http_user:
            http_user = os.getenv("X_HTTP_USER", "")
        if not http_pass:
            http_pass = os.getenv("X_HTTP_PASS", "")

        if http_user:
            credentials = base64.b64encode(
                f"{http_user}:{http_pass}".encode()
            ).decode()
            extra_headers['Authorization'] = f"Basic {credentials}"

        # Port (only used when host is a plain hostname without scheme)
        try:
            port = int(
                config.get('qb_port')
            )
        except (ValueError, TypeError):
            port = 8080
        try:
            http_timeout = int(config.get("http_timeout", DEFAULT_HTTP_TIMEOUT_SECONDS))
        except (ValueError, TypeError):
            http_timeout = DEFAULT_HTTP_TIMEOUT_SECONDS
        if http_timeout <= 0:
            http_timeout = DEFAULT_HTTP_TIMEOUT_SECONDS

        conn = {
            'host': host,
            'port': port,
            'username': (
                config.get('qb_username')
                or "admin"
            ),
            'password': (
                config.get('qb_password')
                or ""
            ),
            'FORCE_SCHEME_FROM_HOST': True,
            'VERIFY_WEBUI_CERTIFICATE': False,
            'DISABLE_LOGGING_DEBUG_OUTPUT': False,
            'REQUESTS_ARGS': {'timeout': int(http_timeout)},
        }
        if extra_headers:
            conn['EXTRA_HEADERS'] = extra_headers

        return conn

    def _create_client(self) -> qbittorrentapi.Client:
        """Create and authenticate a qBittorrent API client.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        qb_client = qbittorrentapi.Client(**self.qb_conn_info)
        qb = (
            _DebugAPIClientProxy(qb_client, self)
            if self.debug_logging_enabled
            else qb_client
        )
        qb.auth_log_in()
        return qb

    def _remove_expired_cache_file(self) -> None:
        """Delete cache file when older than configured maximum age.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            if not self.cache_file_path.exists():
                return
            max_age_seconds = max(1, int(CACHE_MAX_AGE_DAYS)) * 24 * 60 * 60
            age_seconds = time.time() - float(self.cache_file_path.stat().st_mtime)
            if age_seconds <= max_age_seconds:
                return
            self.cache_file_path.unlink()
            cache_tmp = Path(f"{self.cache_file_path}.tmp")
            if cache_tmp.exists():
                cache_tmp.unlink()
            logger.info(
                "Deleted expired content cache file: %s (age %.1f days)",
                self.cache_file_path,
                age_seconds / (24 * 60 * 60),
            )
        except Exception as e:
            logger.warning("Failed to remove expired content cache %s: %s", self.cache_file_path, e)

    def _load_content_cache(self) -> None:
        """Load persistent content cache from JSON file.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        self.content_cache = {}
        try:
            if not self.cache_file_path.exists():
                return
            raw = self.cache_file_path.read_text(encoding='utf-8')
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return

            normalized: Dict[str, Dict[str, Any]] = {}
            for torrent_hash, entry in parsed.items():
                if not isinstance(entry, dict):
                    continue
                files = entry.get('files', [])
                if not isinstance(files, list):
                    files = []
                normalized_files = []
                for f in files:
                    if not isinstance(f, dict):
                        continue
                    normalized_files.append(self._normalize_cached_file(f))
                normalized[str(torrent_hash)] = {
                    'state': str(entry.get('state', '') or ''),
                    'files': normalized_files,
                }
            self.content_cache = normalized
            logger.info("Loaded content cache: %d torrents", len(self.content_cache))
        except Exception as e:
            logger.warning("Failed to load content cache from %s: %s", self.cache_file_path, e)
            self.content_cache = {}

    def _save_content_cache(self) -> None:
        """Persist content cache to disk as JSON.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            self.cache_file_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = Path(f"{self.cache_file_path}.tmp")
            tmp_path.write_text(
                json.dumps(self.content_cache, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            tmp_path.replace(self.cache_file_path)
        except Exception as e:
            logger.warning("Failed to save content cache to %s: %s", self.cache_file_path, e)

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        """Convert value to int and return default when conversion fails.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        """Convert value to float and return default when conversion fails.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            return float(value)
        except Exception:
            return default

    def _normalize_cached_file(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize one cached file entry.

        Side effects: None.
        Failure modes: None.
        """
        return {
            'name': str(entry.get('name', '') or ''),
            'size': self._safe_int(entry.get('size', 0), 0),
            'progress': self._safe_float(entry.get('progress', 0.0), 0.0),
            'priority': self._safe_int(entry.get('priority', 1), 1),
        }

    def _serialize_file_for_cache(self, file_obj) -> Dict[str, Any]:
        """Serialize API file object to cache-safe dict.

        Side effects: None.
        Failure modes: None.
        """
        return self._normalize_cached_file({
            'name': getattr(file_obj, 'name', '') or '',
            'size': getattr(file_obj, 'size', 0),
            'progress': getattr(file_obj, 'progress', 0.0),
            'priority': getattr(file_obj, 'priority', 1),
        })

    def _get_cached_files(self, torrent_hash: str) -> List[Dict[str, Any]]:
        """Return cached files for torrent hash, or empty list.

        Side effects: None.
        Failure modes: None.
        """
        if not torrent_hash:
            return []
        entry = self.content_cache.get(torrent_hash, {})
        files = entry.get('files', []) if isinstance(entry, dict) else []
        return files if isinstance(files, list) else []

    def _get_cache_refresh_candidates(self) -> Dict[str, str]:
        """Return torrent hashes that need cache refresh (new/missing/status change).

        Side effects: None.
        Failure modes: None.
        """
        candidates: Dict[str, str] = {}
        for torrent in self.all_torrents:
            torrent_hash = getattr(torrent, 'hash', '') or ''
            if not torrent_hash:
                continue
            state = str(getattr(torrent, 'state', '') or '')
            cached = self.content_cache.get(torrent_hash)
            cached_state = str(cached.get('state', '')) if isinstance(cached, dict) else ''
            cached_files = cached.get('files') if isinstance(cached, dict) else None
            if cached_state != state or not isinstance(cached_files, list):
                candidates[torrent_hash] = state

        return candidates

    def _matches_file_filter(self, torrent_hash: str, pattern: str) -> bool:
        """Return True when any cached file name/path matches the pattern.

        Side effects: None.
        Failure modes: None.
        """
        cached_files = self._get_cached_files(torrent_hash)
        if not cached_files:
            return False
        for entry in cached_files:
            name = str(entry.get('name', '') or '')
            normalized = name.replace('\\', '/')
            basename = normalized.rsplit('/', 1)[-1] if '/' in normalized else normalized
            if matches_wildcard(basename, pattern) or matches_wildcard(normalized, pattern):
                return True
        return False

    def _fetch_categories(self, **_kw) -> APITaskResult:
        """Fetch categories from qBittorrent.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                result = qb.torrents_categories()
            elapsed = time.time() - start_time
            return api_task_result(data=result, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=None, elapsed=elapsed, success=False, error=str(e))

    def _fetch_tags(self, **_kw) -> APITaskResult:
        """Fetch tags from qBittorrent.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                result = qb.torrents_tags()
            elapsed = time.time() - start_time
            return api_task_result(data=sorted(result), elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=[], elapsed=elapsed, success=False, error=str(e))

    def _selected_remote_torrent_filters(self) -> Dict[str, Any]:
        """Build remote API filter kwargs from selected status/category/tag/private filters.

        Side effects: None.
        Failure modes: None.
        """
        filters: Dict[str, Any] = {}

        status = str(self.current_status_filter or "").strip()
        if status and status.lower() != "all":
            filters["status_filter"] = status

        if self.current_category_filter is not None:
            filters["category"] = str(self.current_category_filter or "")

        if self.current_tag_filter is not None:
            filters["tag"] = str(self.current_tag_filter or "")

        if self.current_private_filter is not None:
            filters["private"] = bool(self.current_private_filter)

        return filters

    def _fetch_torrents(self, **_kw) -> APITaskResult:
        """Fetch torrents via incremental sync/maindata and return current full list.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()

        try:
            alt_speed_mode = bool(self._last_alt_speed_mode)
            dht_nodes = self._safe_int(self._last_dht_nodes, 0)
            global_download_limit = self._safe_int(self._last_global_download_limit, 0)
            global_upload_limit = self._safe_int(self._last_global_upload_limit, 0)
            remote_filters = self._selected_remote_torrent_filters()
            with self._create_client() as qb:
                if remote_filters:
                    result = list(qb.torrents_info(**remote_filters))
                    result.sort(
                        key=lambda t: self._safe_int(getattr(t, "added_on", 0), 0),
                        reverse=True
                    )
                else:
                    maindata = qb.sync_maindata(rid=int(self._sync_rid))
                    result = self._merge_sync_maindata(maindata)
                    payload = self._entry_to_dict(maindata)
                    server_state = self._entry_to_dict(payload.get("server_state", {}))
                    if "dht_nodes" in server_state:
                        dht_nodes = max(
                            0,
                            self._safe_int(server_state.get("dht_nodes"), dht_nodes),
                        )
                if hasattr(qb, "transfer_speed_limits_mode"):
                    try:
                        alt_speed_mode = self._safe_int(qb.transfer_speed_limits_mode(), 0) == 1
                    except Exception:
                        pass
                if hasattr(qb, "transfer_info"):
                    try:
                        transfer_info = self._entry_to_dict(qb.transfer_info())
                        if "dht_nodes" in transfer_info:
                            dht_nodes = max(
                                0,
                                self._safe_int(transfer_info.get("dht_nodes"), dht_nodes),
                            )
                    except Exception:
                        pass
                if hasattr(qb, "transfer_download_limit"):
                    try:
                        global_download_limit = max(
                            0, self._safe_int(qb.transfer_download_limit(), 0)
                        )
                    except Exception:
                        pass
                if hasattr(qb, "transfer_upload_limit"):
                    try:
                        global_upload_limit = max(
                            0, self._safe_int(qb.transfer_upload_limit(), 0)
                        )
                    except Exception:
                        pass

            elapsed = time.time() - start_time
            return {
                'data': result,
                'remote_filtered': bool(remote_filters),
                'alt_speed_mode': bool(alt_speed_mode),
                'dht_nodes': int(max(0, dht_nodes)),
                'global_download_limit': int(max(0, global_download_limit)),
                'global_upload_limit': int(max(0, global_upload_limit)),
                'elapsed': elapsed,
                'success': True
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=[], elapsed=elapsed, success=False, error=str(e))

    def _merge_sync_maindata(self, maindata: Any) -> List[Any]:
        """Merge one sync/maindata payload into local torrent map and return ordered list.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        payload = self._entry_to_dict(maindata)
        full_update = bool(payload.get("full_update", False))
        rid = self._safe_int(payload.get("rid", self._sync_rid), self._sync_rid)
        torrents_update = payload.get("torrents", {}) or {}
        removed_hashes = payload.get("torrents_removed", []) or []

        if full_update:
            self._sync_torrent_map = {}

        if hasattr(torrents_update, "items"):
            for raw_hash, entry in torrents_update.items():
                entry_dict = self._entry_to_dict(entry)
                torrent_hash = str(entry_dict.get("hash") or raw_hash or "").strip()
                if not torrent_hash:
                    continue

                merged = dict(self._sync_torrent_map.get(torrent_hash, {}))
                merged.update(entry_dict)
                merged["hash"] = torrent_hash
                self._sync_torrent_map[torrent_hash] = merged

        if isinstance(removed_hashes, (list, tuple, set)):
            for raw_hash in removed_hashes:
                torrent_hash = str(raw_hash or "").strip()
                if torrent_hash:
                    self._sync_torrent_map.pop(torrent_hash, None)

        self._sync_rid = rid

        torrents = [
            SimpleNamespace(**entry)
            for entry in self._sync_torrent_map.values()
            if isinstance(entry, dict)
        ]
        torrents.sort(
            key=lambda t: self._safe_int(getattr(t, "added_on", 0), 0),
            reverse=True
        )
        return torrents

    @staticmethod
    def _entry_to_dict(entry: Any) -> Dict[str, Any]:
        """Convert qBittorrent API list/dict entry objects to plain dict.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        if isinstance(entry, dict):
            return dict(entry)
        if hasattr(entry, "items"):
            try:
                return {str(k): v for k, v in entry.items()}
            except Exception:
                pass
        result: Dict[str, Any] = {}
        for key in dir(entry):
            if key.startswith("_"):
                continue
            try:
                value = getattr(entry, key)
            except Exception:
                continue
            if callable(value):
                continue
            result[str(key)] = value
        return result

    def _fetch_selected_torrent_trackers(self, torrent_hash: str, **_kw) -> APITaskResult:
        """Fetch all tracker rows for one torrent.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                trackers = qb.torrents_trackers(torrent_hash=torrent_hash)

            rows = [self._entry_to_dict(entry) for entry in list(trackers or [])]
            elapsed = time.time() - start_time
            return api_task_result(data=rows, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=[], elapsed=elapsed, success=False, error=str(e))

    def _fetch_selected_torrent_peers(self, torrent_hash: str, **_kw) -> APITaskResult:
        """Fetch all peer rows for one torrent.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                peers_info = qb.sync_torrent_peers(torrent_hash=torrent_hash, rid=0)

            peers_map = {}
            if isinstance(peers_info, dict):
                peers_map = peers_info.get('peers', {}) or {}
            elif hasattr(peers_info, "get"):
                peers_map = peers_info.get('peers', {}) or {}
            else:
                peers_map = getattr(peers_info, 'peers', {}) or {}

            rows: List[Dict[str, Any]] = []
            if hasattr(peers_map, "items"):
                for peer_id, peer_entry in peers_map.items():
                    row = {'peer_id': str(peer_id)}
                    row.update(self._entry_to_dict(peer_entry))
                    rows.append(row)

            elapsed = time.time() - start_time
            return api_task_result(data=rows, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=[], elapsed=elapsed, success=False, error=str(e))

    @staticmethod
    def _tracker_host_from_url(url: str) -> str:
        """Extract tracker hostname from URL where possible.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        text = str(url or "").strip()
        if not text:
            return ""
        try:
            parsed = urlparse(text)
            return (parsed.hostname or text).lower()
        except Exception:
            return text.lower()

    @staticmethod
    def _classify_tracker_health_status(status_code: int, message: str) -> str:
        """Classify one tracker row into working/failing/unknown buckets.

        Side effects: None.
        Failure modes: None.
        """
        msg = str(message or "").strip().lower()
        if status_code in {2, 3, 5}:
            return "working"
        if status_code == 4:
            return "failing"
        failure_terms = (
            "timed out",
            "timeout",
            "error",
            "unreachable",
            "refused",
            "not working",
            "failure",
            "offline",
        )
        if any(term in msg for term in failure_terms):
            return "failing"
        return "unknown"

    def _fetch_tracker_health_data(self, torrent_hashes: List[str], **_kw) -> APITaskResult:
        """Fetch and aggregate tracker health metrics across provided torrents.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            stats: Dict[str, Dict[str, Any]] = {}
            with self._create_client() as qb:
                for torrent_hash in list(torrent_hashes or []):
                    if not torrent_hash:
                        continue
                    try:
                        tracker_rows = list(qb.torrents_trackers(torrent_hash=torrent_hash) or [])
                    except Exception:
                        continue
                    for entry in tracker_rows:
                        row = self._entry_to_dict(entry)
                        tracker_host = self._tracker_host_from_url(row.get("url", ""))
                        if not tracker_host:
                            continue
                        bucket = stats.setdefault(
                            tracker_host,
                            {
                                "tracker": tracker_host,
                                "torrent_hashes": set(),
                                "row_count": 0,
                                "working_count": 0,
                                "failing_count": 0,
                                "unknown_count": 0,
                                "next_announce_sum": 0,
                                "next_announce_count": 0,
                                "last_error": "",
                            },
                        )
                        bucket["torrent_hashes"].add(str(torrent_hash))
                        bucket["row_count"] += 1

                        status_code = self._safe_int(row.get("status", -1), -1)
                        message = str(row.get("msg", "") or "").strip()
                        status_kind = self._classify_tracker_health_status(status_code, message)
                        if status_kind == "working":
                            bucket["working_count"] += 1
                        elif status_kind == "failing":
                            bucket["failing_count"] += 1
                            if message:
                                bucket["last_error"] = message
                        else:
                            bucket["unknown_count"] += 1

                        next_announce = self._safe_int(row.get("next_announce", -1), -1)
                        if next_announce >= 0:
                            bucket["next_announce_sum"] += next_announce
                            bucket["next_announce_count"] += 1

            rows: List[Dict[str, Any]] = []
            for tracker, bucket in stats.items():
                row_count = self._safe_int(bucket.get("row_count", 0), 0)
                failing = self._safe_int(bucket.get("failing_count", 0), 0)
                working = self._safe_int(bucket.get("working_count", 0), 0)
                fail_rate = (failing * 100.0 / row_count) if row_count > 0 else 0.0
                avg_next = ""
                if self._safe_int(bucket.get("next_announce_count", 0), 0) > 0:
                    avg_next = str(
                        int(
                            bucket["next_announce_sum"]
                            / max(1, bucket["next_announce_count"])
                        )
                    )

                dead = bool(failing > 0 and working == 0 and fail_rate >= 50.0)
                rows.append(
                    {
                        "tracker": tracker,
                        "torrent_count": len(bucket.get("torrent_hashes", set())),
                        "row_count": row_count,
                        "working_count": working,
                        "failing_count": failing,
                        "fail_rate": fail_rate,
                        "dead": dead,
                        "avg_next_announce": avg_next,
                        "last_error": str(bucket.get("last_error", "") or ""),
                    }
                )

            rows.sort(
                key=lambda row: (
                    not bool(row.get("dead", False)),
                    -float(row.get("fail_rate", 0.0)),
                    str(row.get("tracker", "")),
                )
            )
            elapsed = time.time() - start_time
            return api_task_result(data=rows, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=[], elapsed=elapsed, success=False, error=str(e))

    def _refresh_content_cache_for_torrents(self, torrent_states: Dict[str, str], **_kw) -> APITaskResult:
        """Refresh cached file trees for provided torrent hashes.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        start_time = time.time()
        try:
            updates: Dict[str, Dict[str, Any]] = {}
            errors: Dict[str, str] = {}
            with self._create_client() as qb:
                for torrent_hash, state in torrent_states.items():
                    try:
                        files = qb.torrents_files(torrent_hash=torrent_hash)
                        updates[torrent_hash] = {
                            'state': str(state or ''),
                            'files': [self._serialize_file_for_cache(f) for f in files],
                        }
                    except Exception as ex:
                        errors[torrent_hash] = str(ex)
            elapsed = time.time() - start_time
            return {
                'data': updates,
                'errors': errors,
                'elapsed': elapsed,
                'success': True
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': {}, 'errors': {}, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _add_torrent_api(self, torrent_data: Dict, **_kw) -> APITaskResult:
        """Add a torrent via API.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        start_time = time.time()
        data = dict(torrent_data)  # avoid mutating caller's dict
        try:
            with self._create_client() as qb:
                result_ok = True
                details: Dict[str, Any] = {
                    "submitted_urls": 0,
                    "added_urls": 0,
                    "submitted_files": 0,
                    "added_files": 0,
                    "failed_sources": [],
                }
                urls_payload = data.pop('urls', None)
                files_payload = data.pop('torrent_files', None)

                if urls_payload not in (None, "", []):
                    if isinstance(urls_payload, (list, tuple, set)):
                        url_entries = [str(u or "").strip() for u in urls_payload if str(u or "").strip()]
                    else:
                        url_entries = [str(urls_payload).strip()]
                    details["submitted_urls"] = len(url_entries)
                    url_result = qb.torrents_add(urls=urls_payload, **dict(data))
                    if url_result == "Ok.":
                        details["added_urls"] = len(url_entries)
                    else:
                        result_ok = False
                        details["failed_sources"].append(
                            {"source": "urls", "error": f"API response: {url_result!r}"}
                        )

                if files_payload not in (None, "", []):
                    if isinstance(files_payload, (list, tuple, set)):
                        file_paths = [str(path or "").strip() for path in files_payload if str(path or "").strip()]
                    else:
                        file_paths = [str(files_payload).strip()]
                    details["submitted_files"] = len(file_paths)
                    for file_path in file_paths:
                        try:
                            with open(file_path, 'rb') as f:
                                file_result = qb.torrents_add(torrent_files=f, **dict(data))
                            if file_result == "Ok.":
                                details["added_files"] += 1
                            else:
                                result_ok = False
                                details["failed_sources"].append(
                                    {"source": file_path, "error": f"API response: {file_result!r}"}
                                )
                        except Exception as ex:
                            result_ok = False
                            details["failed_sources"].append(
                                {"source": file_path, "error": str(ex)}
                            )

                if urls_payload in (None, "", []) and files_payload in (None, "", []):
                    raise ValueError("No torrent sources provided")

            elapsed = time.time() - start_time
            return {
                'data': result_ok,
                'elapsed': elapsed,
                'success': True,
                'details': details,
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_export_torrents(
        self,
        torrent_hashes: List[str],
        export_dir: str,
        name_map: Dict[str, str],
        **_kw,
    ) -> APITaskResult:
        """Export selected torrents into .torrent files in the target directory.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            destination_text = str(export_dir or "").strip()
            if not destination_text:
                raise ValueError("Missing export directory")
            destination = Path(destination_text)
            destination.mkdir(parents=True, exist_ok=True)

            normalized_hashes = [str(h or "").strip() for h in list(torrent_hashes or []) if str(h or "").strip()]
            if not normalized_hashes:
                raise ValueError("No torrents selected for export")

            exported_files: List[str] = []
            failed: Dict[str, str] = {}
            used_names: set = set()
            with self._create_client() as qb:
                for torrent_hash in normalized_hashes:
                    try:
                        payload = qb.torrents_export(torrent_hash=torrent_hash)
                        file_path = self._unique_export_file_path(
                            destination,
                            str((name_map or {}).get(torrent_hash, "") or torrent_hash),
                            torrent_hash,
                            used_names,
                        )
                        with open(file_path, "wb") as handle:
                            handle.write(bytes(payload or b""))
                        exported_files.append(str(file_path))
                    except Exception as ex:
                        failed[torrent_hash] = str(ex)

            elapsed = time.time() - start_time
            if failed:
                return {
                    'data': {'exported': exported_files, 'failed': failed},
                    'elapsed': elapsed,
                    'success': False,
                    'error': "Some torrent exports failed",
                }
            return {
                'data': {'exported': exported_files, 'failed': {}},
                'elapsed': elapsed,
                'success': True,
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return {
                'data': {'exported': [], 'failed': {}},
                'elapsed': elapsed,
                'success': False,
                'error': str(e),
            }

    def _api_pause_torrent(self, torrent_hashes: List[str], **_kw) -> APITaskResult:
        """Pause one or more torrents via API.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_pause(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_resume_torrent(self, torrent_hashes: List[str], **_kw) -> APITaskResult:
        """Resume one or more torrents via API.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_resume(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_force_start_torrent(self, torrent_hashes: List[str], **_kw) -> APITaskResult:
        """Enable force start for one or more torrents via API.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_set_force_start(enable=True, torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_recheck_torrent(self, torrent_hashes: List[str], **_kw) -> APITaskResult:
        """Recheck one or more torrents via API.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_recheck(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_increase_torrent_priority(self, torrent_hashes: List[str], **_kw) -> APITaskResult:
        """Increase queue priority for one or more torrents via API.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_increase_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_decrease_torrent_priority(self, torrent_hashes: List[str], **_kw) -> APITaskResult:
        """Decrease queue priority for one or more torrents via API.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_decrease_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_top_torrent_priority(self, torrent_hashes: List[str], **_kw) -> APITaskResult:
        """Move one or more torrents to top queue priority via API.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_top_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_minimum_torrent_priority(self, torrent_hashes: List[str], **_kw) -> APITaskResult:
        """Move one or more torrents to minimum queue priority via API.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_bottom_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_apply_selected_torrent_edits(
        self,
        torrent_hash: str,
        updates: Dict[str, Any],
        **_kw,
    ) -> APITaskResult:
        """Apply editable properties for a single torrent.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            normalized_hash = str(torrent_hash or "").strip()
            if not normalized_hash:
                raise ValueError("Missing torrent hash")
            normalized_updates = dict(updates or {})
            hashes = [normalized_hash]

            with self._create_client() as qb:
                if "name" in normalized_updates:
                    torrent_name = str(normalized_updates.get("name", "") or "").strip()
                    if not torrent_name:
                        raise ValueError("Torrent name cannot be empty")
                    qb.torrents_rename(
                        torrent_hash=normalized_hash,
                        new_torrent_name=torrent_name,
                    )

                if "auto_tmm" in normalized_updates:
                    qb.torrents_set_auto_management(
                        enable=bool(normalized_updates["auto_tmm"]),
                        torrent_hashes=hashes,
                    )

                if "category" in normalized_updates:
                    qb.torrents_set_category(
                        torrent_hashes=hashes,
                        category=str(normalized_updates.get("category", "") or ""),
                    )

                if "tags" in normalized_updates:
                    tags_text = str(normalized_updates.get("tags", "") or "")
                    qb.torrents_remove_tags(torrent_hashes=hashes)
                    if tags_text:
                        qb.torrents_add_tags(
                            torrent_hashes=hashes,
                            tags=tags_text,
                        )

                if "save_path" in normalized_updates:
                    save_path = str(normalized_updates.get("save_path", "") or "")
                    if hasattr(qb, "torrents_set_save_path"):
                        qb.torrents_set_save_path(
                            torrent_hashes=hashes,
                            save_path=save_path,
                        )
                    elif save_path:
                        qb.torrents_set_location(
                            torrent_hashes=hashes,
                            location=save_path,
                        )
                    else:
                        raise RuntimeError(
                            "Clearing save path is not supported by this qBittorrent version."
                        )

                if "download_path" in normalized_updates:
                    download_path = str(normalized_updates.get("download_path", "") or "")
                    if hasattr(qb, "torrents_set_download_path"):
                        qb.torrents_set_download_path(
                            torrent_hashes=hashes,
                            download_path=download_path,
                        )
                    else:
                        raise RuntimeError(
                            "Editing incomplete save path is not supported by this qBittorrent version."
                        )

                if "download_limit_bytes" in normalized_updates:
                    qb.torrents_set_download_limit(
                        torrent_hashes=hashes,
                        limit=max(0, int(normalized_updates.get("download_limit_bytes", 0))),
                    )

                if "upload_limit_bytes" in normalized_updates:
                    qb.torrents_set_upload_limit(
                        torrent_hashes=hashes,
                        limit=max(0, int(normalized_updates.get("upload_limit_bytes", 0))),
                    )

            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_set_torrent_download_limit(self, torrent_hashes: List[str], limit_bytes: int, **_kw) -> APITaskResult:
        """Set per-torrent download limit (bytes/sec) for selected torrents.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_set_download_limit(
                    torrent_hashes=list(torrent_hashes),
                    limit=max(0, int(limit_bytes))
                )
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_set_torrent_upload_limit(self, torrent_hashes: List[str], limit_bytes: int, **_kw) -> APITaskResult:
        """Set per-torrent upload limit (bytes/sec) for selected torrents.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_set_upload_limit(
                    torrent_hashes=list(torrent_hashes),
                    limit=max(0, int(limit_bytes))
                )
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_set_global_download_limit(self, limit_bytes: int, **_kw) -> APITaskResult:
        """Set global download limit (bytes/sec).

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.transfer_set_download_limit(limit=max(0, int(limit_bytes)))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_set_global_upload_limit(self, limit_bytes: int, **_kw) -> APITaskResult:
        """Set global upload limit (bytes/sec).

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.transfer_set_upload_limit(limit=max(0, int(limit_bytes)))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_toggle_alt_speed_mode(self, **_kw) -> APITaskResult:
        """Toggle alternative/global speed-limit mode.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.transfer_toggle_speed_limits_mode()
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_fetch_speed_limits_profile(self, **_kw) -> APITaskResult:
        """Fetch normal/alternative speed limits and current alt-speed mode.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                normal_dl = self._safe_int(qb.transfer_download_limit(), 0)
                normal_ul = self._safe_int(qb.transfer_upload_limit(), 0)
                mode = self._safe_int(qb.transfer_speed_limits_mode(), 0)
                prefs_raw = qb.app_preferences()

            prefs = self._entry_to_dict(prefs_raw)
            alt_dl = 0
            alt_ul = 0
            for key in ("alt_dl_limit", "alt_dl", "alt_download_limit"):
                if key in prefs:
                    alt_dl = self._safe_int(prefs.get(key), 0)
                    break
            for key in ("alt_up_limit", "alt_up", "alt_upload_limit"):
                if key in prefs:
                    alt_ul = self._safe_int(prefs.get(key), 0)
                    break

            elapsed = time.time() - start_time
            return {
                'data': {
                    'normal_dl': max(0, normal_dl),
                    'normal_ul': max(0, normal_ul),
                    'alt_dl': max(0, alt_dl),
                    'alt_ul': max(0, alt_ul),
                    'alt_enabled': bool(mode == 1),
                },
                'elapsed': elapsed,
                'success': True,
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data={}, elapsed=elapsed, success=False, error=str(e))

    def _api_apply_speed_limits_profile(
        self,
        normal_dl: int,
        normal_ul: int,
        alt_dl: int,
        alt_ul: int,
        alt_enabled: bool,
        **_kw,
    ) -> APITaskResult:
        """Apply normal/alternative speed limits and desired alt-speed mode.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.transfer_set_download_limit(limit=max(0, int(normal_dl)))
                qb.transfer_set_upload_limit(limit=max(0, int(normal_ul)))

                prefs_raw = qb.app_preferences()
                prefs_current = self._entry_to_dict(prefs_raw)
                alt_dl_key = "alt_dl_limit" if "alt_dl_limit" in prefs_current else "alt_dl"
                alt_ul_key = "alt_up_limit" if "alt_up_limit" in prefs_current else "alt_up"
                qb.app_set_preferences({
                    alt_dl_key: max(0, int(alt_dl)),
                    alt_ul_key: max(0, int(alt_ul)),
                })

                current_mode = self._safe_int(qb.transfer_speed_limits_mode(), 0)
                desired_mode = 1 if bool(alt_enabled) else 0
                if current_mode != desired_mode:
                    qb.transfer_toggle_speed_limits_mode()

            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_fetch_app_preferences(self, **_kw) -> APITaskResult:
        """Fetch raw qBittorrent application preferences.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                prefs_raw = qb.app_preferences()
            prefs = self._entry_to_dict(prefs_raw)
            elapsed = time.time() - start_time
            return api_task_result(data=prefs, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data={}, elapsed=elapsed, success=False, error=str(e))

    def _api_apply_app_preferences(self, updates: Dict[str, Any], **_kw) -> APITaskResult:
        """Apply only changed application preferences.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            normalized_updates = dict(updates or {})
            if not normalized_updates:
                elapsed = time.time() - start_time
                return {'data': {'applied': 0}, 'elapsed': elapsed, 'success': True}
            with self._create_client() as qb:
                qb.app_set_preferences(prefs=normalized_updates)
            elapsed = time.time() - start_time
            return {
                'data': {'applied': len(normalized_updates)},
                'elapsed': elapsed,
                'success': True,
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': {'applied': 0}, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_set_content_priority(
        self,
        torrent_hash: str,
        relative_path: str,
        is_file: bool,
        priority: int,
        **_kw,
    ) -> APITaskResult:
        """Set file priority for one file or a whole folder subtree.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            normalized = str(relative_path or "").replace("\\", "/").strip("/")
            if not torrent_hash or not normalized:
                raise ValueError("Missing torrent hash or content path")

            with self._create_client() as qb:
                files = list(qb.torrents_files(torrent_hash=torrent_hash) or [])
                file_ids: List[int] = []
                folder_prefix = f"{normalized}/"
                for file_obj in files:
                    file_name = str(getattr(file_obj, "name", "") or "").replace("\\", "/").strip("/")
                    file_id = self._safe_int(getattr(file_obj, "index", -1), -1)
                    if file_id < 0:
                        continue
                    if is_file:
                        if file_name == normalized:
                            file_ids.append(file_id)
                            break
                    elif file_name == normalized or file_name.startswith(folder_prefix):
                        file_ids.append(file_id)

                if not file_ids:
                    raise ValueError("No matching files found for selected content path")

                qb.torrents_file_priority(
                    torrent_hash=torrent_hash,
                    file_ids=file_ids,
                    priority=int(priority),
                )

            elapsed = time.time() - start_time
            return {
                'data': {'updated_file_count': len(file_ids)},
                'elapsed': elapsed,
                'success': True
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data={}, elapsed=elapsed, success=False, error=str(e))

    def _api_rename_content_path(
        self,
        torrent_hash: str,
        old_relative_path: str,
        new_relative_path: str,
        is_file: bool,
        **_kw,
    ) -> APITaskResult:
        """Rename one file or folder inside a torrent.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            old_path = str(old_relative_path or "").replace("\\", "/").strip("/")
            new_path = str(new_relative_path or "").replace("\\", "/").strip("/")
            if not torrent_hash or not old_path or not new_path:
                raise ValueError("Missing torrent hash or rename paths")

            with self._create_client() as qb:
                if is_file:
                    qb.torrents_rename_file(
                        torrent_hash=torrent_hash,
                        old_path=old_path,
                        new_path=new_path,
                    )
                else:
                    qb.torrents_rename_folder(
                        torrent_hash=torrent_hash,
                        old_path=old_path,
                        new_path=new_path,
                    )
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_create_category(
        self,
        name: str,
        save_path: str,
        incomplete_path: str,
        use_incomplete_path: bool,
        **_kw,
    ) -> APITaskResult:
        """Create a new category.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            normalized_save = str(save_path or "").strip()
            normalized_incomplete = str(incomplete_path or "").strip()
            enable_download_path = bool(use_incomplete_path and normalized_incomplete)
            with self._create_client() as qb:
                qb.torrents_create_category(
                    name=name,
                    save_path=normalized_save or None,
                    download_path=normalized_incomplete or None,
                    enable_download_path=enable_download_path,
                )
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_edit_category(
        self,
        name: str,
        save_path: str,
        incomplete_path: str,
        use_incomplete_path: bool,
        **_kw,
    ) -> APITaskResult:
        """Edit one existing category.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            normalized_save = str(save_path or "").strip()
            normalized_incomplete = str(incomplete_path or "").strip()
            enable_download_path = bool(use_incomplete_path and normalized_incomplete)
            with self._create_client() as qb:
                qb.torrents_edit_category(
                    name=name,
                    save_path=normalized_save or None,
                    download_path=normalized_incomplete or None,
                    enable_download_path=enable_download_path,
                )
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_delete_category(self, name: str, **_kw) -> APITaskResult:
        """Delete one category.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_remove_categories(categories=[name])
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_create_tags(self, tags: List[str], **_kw) -> APITaskResult:
        """Create one or more tags.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_create_tags(tags=list(tags))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_delete_tags(self, tags: List[str], **_kw) -> APITaskResult:
        """Delete one or more tags.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_delete_tags(tags=list(tags))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_pause_session(self, **_kw) -> APITaskResult:
        """Pause all torrents in current qBittorrent session.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_pause(torrent_hashes="all")
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_resume_session(self, **_kw) -> APITaskResult:
        """Resume all torrents in current qBittorrent session.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_resume(torrent_hashes="all")
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_delete_torrent(self, torrent_hashes: List[str], delete_files: bool, **_kw) -> APITaskResult:
        """Delete one or more torrents via API.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_delete(torrent_hashes=list(torrent_hashes), delete_files=delete_files)
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except Exception as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_ban_peers(self, peers: List[str], **_kw) -> APITaskResult:
        """Ban one or more peer endpoints (IP:port) globally in qBittorrent.

        Side effects: Performs qBittorrent API/network I/O and returns normalized task payload data.
        Failure modes: Captures runtime/API exceptions and returns failure payloads with error details.
        """
        start_time = time.time()
        try:
            endpoints = [
                str(peer or "").strip()
                for peer in list(peers or [])
                if str(peer or "").strip()
            ]
            if not endpoints:
                raise ValueError("No peer endpoints provided")
            with self._create_client() as qb:
                qb.transfer_ban_peers(peers=endpoints)
            elapsed = time.time() - start_time
            return {'data': {'peers': endpoints}, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': {'peers': []}, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _set_categories_from_payload(self, payload: Any) -> None:
        """Normalize categories payload and update category state/tree.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        category_details: Dict[str, Dict[str, Any]] = {}
        if isinstance(payload, dict):
            for raw_name, raw_entry in payload.items():
                name = str(raw_name or "").strip()
                if not name:
                    continue
                entry = self._entry_to_dict(raw_entry)
                category_details[name] = entry

        self.category_details = category_details
        self.categories = sorted(category_details.keys())
        self._update_category_tree()
        self._refresh_torrent_edit_categories()
        self._sync_taxonomy_dialog_data()

    def _category_save_path_by_name(self, category_name: str) -> str:
        """Resolve default save path for one category from cached details.

        Side effects: None.
        Failure modes: None.
        """
        details = self.category_details.get(str(category_name or ""), {})
        if not isinstance(details, dict):
            return ""
        for key in ("save_path", "savePath"):
            value = str(details.get(key, "") or "").strip()
            if value:
                return value
        return ""

    def _category_incomplete_path_by_name(self, category_name: str) -> str:
        """Resolve incomplete path for one category from cached details.

        Side effects: None.
        Failure modes: None.
        """
        details = self.category_details.get(str(category_name or ""), {})
        if not isinstance(details, dict):
            return ""
        for key in ("download_path", "downloadPath"):
            value = str(details.get(key, "") or "").strip()
            if value:
                return value
        return ""

    def _category_use_incomplete_path_by_name(self, category_name: str) -> bool:
        """Resolve whether incomplete path is enabled for one category.

        Side effects: None.
        Failure modes: None.
        """
        details = self.category_details.get(str(category_name or ""), {})
        if not isinstance(details, dict):
            return False
        for key in (
            "enable_download_path",
            "enableDownloadPath",
            "use_download_path",
            "useDownloadPath",
        ):
            if key in details:
                return self._to_bool(details.get(key), False)
        return bool(self._category_incomplete_path_by_name(category_name))

    def _taxonomy_category_data(self) -> Dict[str, Dict[str, Any]]:
        """Build category metadata mapping for manager dialog.

        Side effects: None.
        Failure modes: None.
        """
        return {
            name: {
                "save_path": self._category_save_path_by_name(name),
                "incomplete_path": self._category_incomplete_path_by_name(name),
                "use_incomplete_path": self._category_use_incomplete_path_by_name(name),
            }
            for name in self.categories
        }

    def _sync_taxonomy_dialog_data(self) -> None:
        """Refresh taxonomy dialog data when open.

        Side effects: None.
        Failure modes: None.
        """
        dialog = self._taxonomy_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_taxonomy_data(self._taxonomy_category_data(), list(self.tags))

    def _on_categories_loaded(self, result: Dict) -> None:
        """Handle categories loaded.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            if not result.get('success', False):
                error = result.get('error', 'Unknown error')
                self._log("ERROR", f"Failed to load categories: {error}", result.get('elapsed', 0))
                self._set_status(f"Connection error: {error}")
                self.txt_general_details.setPlainText(
                    f"Failed to connect to qBittorrent:\n\n{error}\n\n"
                    f"Host: {self.qb_conn_info.get('host')}:{self.qb_conn_info.get('port')}\n"
                    f"Check your configuration and ensure qBittorrent WebUI is accessible."
                )
                # Continue anyway - load tags with empty categories
                self.category_details = {}
                self.categories = []
                self._update_category_tree()
                self._sync_taxonomy_dialog_data()
                # Load tags next
                self._show_progress("Loading tags...")
                self.api_queue.add_task(
                    "load_tags",
                    self._fetch_tags,
                    self._on_tags_loaded
                )
                return

            self._set_categories_from_payload(result.get('data', {}))
            self._log("INFO", f"Loaded {len(self.categories)} categories", result.get('elapsed', 0))

            # Load tags next
            self._show_progress("Loading tags...")
            self.api_queue.add_task(
                "load_tags",
                self._fetch_tags,
                self._on_tags_loaded
            )
        except Exception as e:
            self._log("ERROR", f"Exception in _on_categories_loaded: {e}")
            self._hide_progress()
            self._set_status(f"Error loading categories: {e}")

    def _on_tags_loaded(self, result: Dict) -> None:
        """Handle tags loaded.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            if not result.get('success', False):
                error = result.get('error', 'Unknown error')
                self._log("ERROR", f"Failed to load tags: {error}", result.get('elapsed', 0))
                # Continue anyway - load torrents with empty tags
                self.tags = []
                self._update_tag_tree()
                self._sync_taxonomy_dialog_data()
                # Load torrents next
                self._show_progress("Loading torrents...")
                self.api_queue.add_task(
                    "load_torrents",
                    self._fetch_torrents,
                    self._on_torrents_loaded
                )
                return

            self.tags = result.get('data', [])
            self._update_tag_tree()
            self._sync_taxonomy_dialog_data()
            self._log("INFO", f"Loaded {len(self.tags)} tags", result.get('elapsed', 0))

            # Load torrents next
            self._show_progress("Loading torrents...")
            self.api_queue.add_task(
                "load_torrents",
                self._fetch_torrents,
                self._on_torrents_loaded
            )
        except Exception as e:
            self._log("ERROR", f"Exception in _on_tags_loaded: {e}")
            self._hide_progress()
            self._set_status(f"Error loading tags: {e}")

    def _on_torrents_loaded(self, result: Dict) -> None:
        """Handle torrents loaded.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            if not result.get('success', False):
                self._latest_torrent_fetch_remote_filtered = False
                error = result.get('error', 'Unknown error')
                self._log("ERROR", f"Failed to load torrents: {error}", result.get('elapsed', 0))
                self._hide_progress()
                self._set_status(f"Error: {error}")
                # Show empty table
                self.all_torrents = []
                self._update_filter_tree_count_labels()
                self.filtered_torrents = []
                self._update_window_title_speeds()
                self._update_statusbar_transfer_summary()
                self._update_torrents_table()
                return

            previous_selected_hash = self._get_selected_torrent_hash()
            self._latest_torrent_fetch_remote_filtered = bool(
                result.get("remote_filtered", False)
            )
            self.all_torrents = result.get('data', [])
            self._update_filter_tree_count_labels()
            if "alt_speed_mode" in result:
                self._last_alt_speed_mode = bool(result.get("alt_speed_mode"))
            if "dht_nodes" in result:
                self._last_dht_nodes = max(
                    0,
                    self._safe_int(result.get("dht_nodes"), 0),
                )
            if "global_download_limit" in result:
                self._last_global_download_limit = max(
                    0,
                    self._safe_int(result.get("global_download_limit"), 0),
                )
            if "global_upload_limit" in result:
                self._last_global_upload_limit = max(
                    0,
                    self._safe_int(result.get("global_upload_limit"), 0),
                )
            self._record_session_timeline_sample(self._last_alt_speed_mode)
            self._log("INFO", f"Loaded {len(self.all_torrents)} torrents", result.get('elapsed', 0))
            self._update_window_title_speeds()
            self._update_statusbar_transfer_summary()

            # Calculate size buckets
            self._calculate_size_buckets()
            self._update_size_tree()

            # Extract tracker hostnames
            self._extract_trackers()
            self._update_tracker_tree()

            # Refresh cache only for new torrents or torrents with changed status
            refresh_candidates = self._get_cache_refresh_candidates()
            if refresh_candidates:
                self._log(
                    "INFO",
                    f"Refreshing content cache for {len(refresh_candidates)} torrents"
                )
                self.api_queue.add_task(
                    "refresh_content_cache",
                    self._refresh_content_cache_for_torrents,
                    self._on_content_cache_refreshed,
                    refresh_candidates
                )
            elif self._suppress_next_cache_save:
                # Nothing to refresh (e.g., zero torrents) - clear one-shot flag.
                self._suppress_next_cache_save = False

            # Apply filters and update table
            self._apply_filters()
            self._select_first_torrent_after_refresh(previous_selected_hash)
            self._hide_progress()
        except Exception as e:
            self._latest_torrent_fetch_remote_filtered = False
            self._log("ERROR", f"Exception in _on_torrents_loaded: {e}")
            self._hide_progress()
            self._set_status(f"Error loading torrents: {e}")
            # Show empty table
            self.all_torrents = []
            self._update_filter_tree_count_labels()
            self.filtered_torrents = []
            self._update_window_title_speeds()
            self._update_statusbar_transfer_summary()
            self._update_torrents_table()
        finally:
            self._set_refresh_torrents_in_progress(False)

    def _select_first_torrent_after_refresh(self, previous_selected_hash: Optional[str] = None) -> None:
        """Select/restore one row after refresh without overriding a valid existing selection.

        Side effects: None.
        Failure modes: None.
        """
        if self.tbl_torrents.rowCount() <= 0:
            return

        current_hash = self._get_selected_torrent_hash()
        previous_hash = str(previous_selected_hash or "").strip()
        previous_row = -1
        if previous_hash:
            for row in range(self.tbl_torrents.rowCount()):
                item = self.tbl_torrents.item(row, 0)
                row_hash = item.text().strip() if item else ""
                if row_hash == previous_hash:
                    previous_row = row
                    break

        # No prior selection: keep any current selection, otherwise select first.
        if not previous_hash:
            if current_hash:
                return
            self.tbl_torrents.selectRow(0)
            return

        # Prior selection vanished: always select first row.
        if previous_row < 0:
            self.tbl_torrents.clearSelection()
            self.tbl_torrents.selectRow(0)
            return

        # Prior selection still present: keep if already selected, otherwise restore by hash.
        if current_hash == previous_hash:
            return
        self.tbl_torrents.clearSelection()
        self.tbl_torrents.selectRow(previous_row)

    def _on_content_cache_refreshed(self, result: Dict) -> None:
        """Handle background refresh of cached torrent content trees.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            if not result.get('success', False):
                error = result.get('error', 'Unknown error')
                self._log("ERROR", f"Content cache refresh failed: {error}", result.get('elapsed', 0))
                return

            updates = result.get('data', {})
            if not isinstance(updates, dict):
                updates = {}
            if updates:
                self.content_cache.update(updates)
                if self._suppress_next_cache_save:
                    self._suppress_next_cache_save = False
                    self._log("INFO", "Cache save skipped once after Clear Cache & Refresh")
                else:
                    self._save_content_cache()
                self._log(
                    "INFO",
                    f"Content cache refreshed for {len(updates)} torrents",
                    result.get('elapsed', 0)
                )

                # Re-apply current filters to include newly-cached file matches
                if self.current_file_filter:
                    self._apply_filters()

                # If selected torrent cache got updated, refresh content tab from cache
                selected = getattr(self, '_selected_torrent', None)
                selected_hash = getattr(selected, 'hash', '') if selected else ''
                if selected_hash and selected_hash in updates:
                    self._show_cached_torrent_content(selected_hash)

            errors = result.get('errors', {})
            if isinstance(errors, dict) and errors:
                self._log("ERROR", f"Content cache refresh errors for {len(errors)} torrents")
        except Exception as e:
            self._log("ERROR", f"Exception in _on_content_cache_refreshed: {e}")

    def _on_add_torrent_complete(self, result: Dict) -> None:
        """Handle torrent add completion.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        details = result.get("details", {}) if isinstance(result, dict) else {}
        if isinstance(details, dict):
            added_count = (
                self._safe_int(details.get("added_urls", 0), 0)
                + self._safe_int(details.get("added_files", 0), 0)
            )
            failed_sources = details.get("failed_sources", [])
            failed_count = len(failed_sources) if isinstance(failed_sources, list) else 0
        else:
            added_count = 0
            failed_count = 0

        final_status_text = ""
        if result.get('success') and result.get('data'):
            status_text = (
                f"Added {added_count} torrent sources"
                if added_count > 1
                else "Torrent added successfully"
            )
            self._log("INFO", status_text, result.get('elapsed', 0))
            final_status_text = status_text
            # Refresh torrent list
            QTimer.singleShot(1000, self._refresh_torrents)
        elif result.get('success') and added_count > 0 and failed_count > 0:
            status_text = f"Added {added_count} sources, {failed_count} failed"
            self._log("ERROR", status_text, result.get('elapsed', 0))
            final_status_text = status_text
            QTimer.singleShot(1000, self._refresh_torrents)
        else:
            error_msg = result.get('error', 'Unknown error')
            if (error_msg == 'Unknown error') and failed_count > 0:
                error_msg = f"{failed_count} source(s) failed"
            self._log("ERROR", f"Failed to add torrent: {error_msg}", result.get('elapsed', 0))
            final_status_text = f"Failed to add torrent: {error_msg}"
        self._hide_progress()
        if final_status_text:
            self._set_status(final_status_text)

    def _on_apply_selected_torrent_edits_done(self, result: Dict) -> None:
        """Handle completion of selected torrent edit apply action.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get("success"):
            self._log("INFO", "Torrent edits applied", result.get("elapsed", 0))
            self._set_status("Torrent edits applied")
            QTimer.singleShot(500, self._refresh_torrents)
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"Failed to apply torrent edits: {error}", result.get("elapsed", 0))
            self._set_status(f"Failed to apply torrent edits: {error}")
        self._hide_progress()

    def _on_task_completed(self, task_name: str, result) -> None:
        """Handle task completion.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._maybe_bump_auto_refresh_interval_from_api_elapsed(task_name, result)
        self._log("DEBUG", f"Task completed: {task_name}")

    def _maybe_bump_auto_refresh_interval_from_api_elapsed(self, task_name: str, result: Any) -> None:
        """Increase auto-refresh interval when one API task exceeds current interval.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if not isinstance(result, dict):
            return
        elapsed_seconds = self._safe_float(result.get("elapsed", 0.0), 0.0)
        if elapsed_seconds <= 0:
            return

        current_interval = max(1, self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL))
        if elapsed_seconds <= float(current_interval):
            return

        new_interval = max(current_interval, int(math.ceil(elapsed_seconds * 4.0)))
        if new_interval <= current_interval:
            return

        self.refresh_interval = new_interval
        self._update_auto_refresh_action_text()
        self._sync_auto_refresh_timer_state()
        self._save_refresh_settings()
        self._log(
            "INFO",
            (
                "Auto-refresh interval bumped to "
                f"{new_interval}s after slow API task {task_name} "
                f"({elapsed_seconds:.2f}s)"
            ),
        )

    def _on_task_failed(self, task_name: str, error_msg: str) -> None:
        """Handle task failure.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if task_name == "refresh_torrents":
            self._set_refresh_torrents_in_progress(False)
        self._log("ERROR", f"Task failed: {task_name} - {error_msg}")
        self._set_status(f"Error: {error_msg}")
        self._hide_progress()

    def _on_task_cancelled(self, task_name: str) -> None:
        """Handle task cancellation.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if task_name == "refresh_torrents":
            self._set_refresh_torrents_in_progress(False)
        self._log("INFO", f"Task cancelled: {task_name}")

    def _refresh_torrents(self) -> None:
        """Refresh torrent list.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        if self._refresh_torrents_in_progress:
            self._log("DEBUG", "Refresh skipped: refresh_torrents already in progress")
            return

        # Avoid auto/manual refresh canceling other in-flight user/API operations.
        active_task = str(getattr(self.api_queue, "current_task_name", "") or "").strip()
        pending_task = getattr(self.api_queue, "pending_task", None)
        pending_name = (
            str(pending_task[0]).strip()
            if isinstance(pending_task, tuple) and pending_task
            else ""
        )
        queue_busy_with_non_refresh = bool(
            getattr(self.api_queue, "current_worker", None)
        ) and (
            (active_task and active_task != "refresh_torrents")
            or (pending_name and pending_name != "refresh_torrents")
        )
        if queue_busy_with_non_refresh:
            self._log(
                "DEBUG",
                (
                    "Refresh skipped: API queue busy "
                    f"(active={active_task or 'none'}, pending={pending_name or 'none'})"
                ),
            )
            return

        self._set_refresh_torrents_in_progress(True)
        self._log("INFO", "Refreshing torrents...")
        self._show_progress("Refreshing torrents...")

        try:
            self.api_queue.add_task(
                "refresh_torrents",
                self._fetch_torrents,
                self._on_torrents_loaded
            )
        except Exception:
            self._set_refresh_torrents_in_progress(False)
            raise

class FilterTableController(WindowControllerBase):
    def _is_filter_item_active(self, kind: str, value) -> bool:
        """Return whether a filter tree item is currently active.

        Side effects: None.
        Failure modes: None.
        """
        if kind == 'status':
            return value == self.current_status_filter
        if kind == 'category':
            return value == self.current_category_filter
        if kind == 'tag':
            return value == self.current_tag_filter
        if kind == 'size':
            return value == self.current_size_bucket
        if kind == 'tracker':
            return value == self.current_tracker_filter
        return False

    def _refresh_filter_tree_highlights(self) -> None:
        """Highlight all currently active filters in the unified tree.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if not hasattr(self, 'tree_filters'):
            return

        active_brush = QBrush(QColor(64, 130, 255, 80))
        clear_brush = QBrush()

        for i in range(self.tree_filters.topLevelItemCount()):
            section = self.tree_filters.topLevelItem(i)
            if section is None:
                continue

            # Keep section headers bold.
            section_font = section.font(0)
            section_font.setBold(True)
            section.setFont(0, section_font)

            for j in range(section.childCount()):
                item = section.child(j)
                if item is None:
                    continue
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(data, tuple) or len(data) != 2:
                    continue
                kind, value = data
                is_active = self._is_filter_item_active(kind, value)

                item.setBackground(0, active_brush if is_active else clear_brush)
                font = item.font(0)
                font.setBold(bool(is_active))
                item.setFont(0, font)

    def _create_torrent_columns_menu(self, parent_menu: QMenu) -> None:
        """Create View -> Torrent Columns submenu with per-column visibility toggles.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        columns_menu = parent_menu.addMenu("Torrent &Columns")
        action_basic_view = QAction("Basic View", self)
        action_basic_view.triggered.connect(self._apply_basic_torrent_view)
        columns_menu.addAction(action_basic_view)

        action_medium_view = QAction("Medium View", self)
        action_medium_view.triggered.connect(self._apply_medium_torrent_view)
        columns_menu.addAction(action_medium_view)

        action_save_current = QAction("Save Current View..", self)
        action_save_current.triggered.connect(self._save_current_torrent_view)
        columns_menu.addAction(action_save_current)

        self.saved_torrent_views_menu = columns_menu.addMenu("Saved Views")
        self._refresh_saved_torrent_views_menu()

        columns_menu.addSeparator()
        self.column_visibility_actions = {}

        for idx, column in enumerate(self.torrent_columns):
            key = column["key"]
            action = QAction(column["label"], self)
            action.setCheckable(True)
            action.setChecked(not self.tbl_torrents.isColumnHidden(idx))
            action.toggled.connect(
                lambda checked, column_key=key: self._set_torrent_column_visible(column_key, checked)
            )
            columns_menu.addAction(action)
            self.column_visibility_actions[key] = action

        columns_menu.addSeparator()
        action_show_all = QAction("&Show All Columns", self)
        action_show_all.triggered.connect(self._show_all_torrent_columns)
        columns_menu.addAction(action_show_all)

    def _set_torrent_column_visible(self, column_key: str, visible: bool) -> None:
        """Show or hide one torrent-table column by stable column key.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        idx = self.torrent_column_index.get(column_key)
        if idx is None:
            return
        self.tbl_torrents.setColumnHidden(idx, not bool(visible))
        self._sync_torrent_column_actions()
        self._save_settings()

    def _show_all_torrent_columns(self) -> None:
        """Make every torrent-table column visible.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        for idx in range(self.tbl_torrents.columnCount()):
            self.tbl_torrents.setColumnHidden(idx, False)
        self._sync_torrent_column_actions()
        self._save_settings()

    def _sync_torrent_column_actions(self) -> None:
        """Refresh column visibility action checked states from current table state.

        Side effects: None.
        Failure modes: None.
        """
        if not getattr(self, "column_visibility_actions", None):
            return
        for key, action in self.column_visibility_actions.items():
            idx = self.torrent_column_index.get(key)
            if idx is None:
                continue
            state = not self.tbl_torrents.isColumnHidden(idx)
            prev = action.blockSignals(True)
            action.setChecked(state)
            action.blockSignals(prev)

    def _apply_hidden_columns_by_keys(self, hidden_keys: List[str]) -> None:
        """Apply hidden column state from stable key list.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        hidden = {str(k) for k in hidden_keys}
        for idx, col in enumerate(self.torrent_columns):
            self.tbl_torrents.setColumnHidden(idx, col["key"] in hidden)
        self._sync_torrent_column_actions()

    def _apply_torrent_view(
        self,
        visible_keys: List[str],
        widths: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Apply a torrent-table view by visible column keys and optional widths.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        visible_set = {str(key) for key in list(visible_keys or [])}
        known_keys = set(self.torrent_column_index.keys())
        visible_set = {key for key in visible_set if key in known_keys}

        for idx, column in enumerate(self.torrent_columns):
            key = column["key"]
            self.tbl_torrents.setColumnHidden(idx, key not in visible_set)

        if isinstance(widths, dict):
            for key, raw_width in widths.items():
                column_key = str(key)
                idx = self.torrent_column_index.get(column_key)
                if idx is None or self.tbl_torrents.isColumnHidden(idx):
                    continue
                width = self._safe_int(raw_width, 0)
                if width > 0:
                    self.tbl_torrents.setColumnWidth(idx, width)

        self._sync_torrent_column_actions()
        self._save_settings()

    def _current_torrent_view_payload(self) -> Dict[str, Any]:
        """Return visible columns + widths for the current torrent-table view.

        Side effects: None.
        Failure modes: None.
        """
        visible_columns: List[str] = []
        widths: Dict[str, int] = {}
        for idx, column in enumerate(self.torrent_columns):
            key = column["key"]
            if self.tbl_torrents.isColumnHidden(idx):
                continue
            visible_columns.append(key)
            widths[key] = int(self._safe_int(self.tbl_torrents.columnWidth(idx), 0))
        return {
            "visible_columns": visible_columns,
            "widths": widths,
        }

    def _saved_torrent_views(self) -> Dict[str, Dict[str, Any]]:
        """Load named torrent-table views from QSettings.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        settings = self._new_settings()
        raw_json = settings.value("torrentColumnNamedViewsJson", "")
        if isinstance(raw_json, (bytes, bytearray)):
            raw_json = raw_json.decode("utf-8", errors="ignore")
        text = str(raw_json or "").strip()
        if not text:
            return {}

        try:
            parsed = json.loads(text)
        except Exception:
            return {}

        if not isinstance(parsed, dict):
            return {}

        known_keys = set(self.torrent_column_index.keys())
        cleaned: Dict[str, Dict[str, Any]] = {}
        for raw_name, payload in parsed.items():
            view_name = str(raw_name or "").strip()
            if not view_name or not isinstance(payload, dict):
                continue

            raw_visible = payload.get("visible_columns", [])
            visible_columns: List[str] = []
            if isinstance(raw_visible, str):
                raw_visible = [raw_visible]
            if isinstance(raw_visible, (list, tuple, set)):
                for raw_key in raw_visible:
                    key = str(raw_key or "").strip()
                    if key in known_keys:
                        visible_columns.append(key)

            raw_widths = payload.get("widths", {})
            widths: Dict[str, int] = {}
            if isinstance(raw_widths, dict):
                for raw_key, raw_width in raw_widths.items():
                    key = str(raw_key or "").strip()
                    if key not in known_keys:
                        continue
                    width = self._safe_int(raw_width, 0)
                    if width > 0:
                        widths[key] = width

            cleaned[view_name] = {
                "visible_columns": visible_columns,
                "widths": widths,
            }

        return cleaned

    def _store_saved_torrent_views(self, views: Dict[str, Dict[str, Any]]) -> None:
        """Store named torrent-table views into QSettings.

        Side effects: None.
        Failure modes: None.
        """
        settings = self._new_settings()
        payload = views if isinstance(views, dict) else {}
        settings.setValue(
            "torrentColumnNamedViewsJson",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        )
        settings.sync()

    def _refresh_saved_torrent_views_menu(self) -> None:
        """Rebuild the Saved Views submenu from QSettings.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        menu = getattr(self, "saved_torrent_views_menu", None)
        if menu is None:
            return

        menu.clear()
        views = self._saved_torrent_views()
        if not views:
            empty_action = QAction("(No saved views)", self)
            empty_action.setEnabled(False)
            menu.addAction(empty_action)
            return

        for view_name in sorted(views.keys(), key=lambda name: name.lower()):
            action = QAction(view_name, self)
            action.triggered.connect(
                lambda _checked=False, name=view_name: self._apply_saved_torrent_view(name)
            )
            menu.addAction(action)

    def _apply_saved_torrent_view(self, view_name: str) -> None:
        """Apply one named saved torrent-table view.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        name = str(view_name or "").strip()
        if not name:
            return
        views = self._saved_torrent_views()
        payload = views.get(name, {})
        visible_columns = payload.get("visible_columns", []) if isinstance(payload, dict) else []
        widths = payload.get("widths", {}) if isinstance(payload, dict) else {}
        if not isinstance(visible_columns, list):
            self._set_status(f"Saved view is invalid: {name}")
            return
        self._apply_torrent_view(visible_columns, widths=widths if isinstance(widths, dict) else {})
        self._set_status(f"Applied view: {name}")

    def _save_current_torrent_view(self) -> None:
        """Prompt for a name and save current column visibility/widths as a named view.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        name, ok = QInputDialog.getText(
            self,
            "Save Torrent View",
            "View name:",
        )
        if not ok:
            return
        view_name = str(name or "").strip()
        if not view_name:
            self._set_status("View name cannot be empty")
            return

        payload = self._current_torrent_view_payload()
        if not payload.get("visible_columns"):
            self._set_status("Cannot save a view with no visible columns")
            return

        views = self._saved_torrent_views()
        views[view_name] = payload
        self._store_saved_torrent_views(views)
        self._refresh_saved_torrent_views_menu()
        self._set_status(f"Saved view: {view_name}")

    def _apply_basic_torrent_view(self) -> None:
        """Apply built-in Basic torrent-table view preset.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._apply_torrent_view(list(BASIC_TORRENT_VIEW_KEYS))
        self._set_status("Applied view: Basic")

    def _apply_medium_torrent_view(self) -> None:
        """Apply built-in Medium torrent-table view preset.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._apply_torrent_view(list(MEDIUM_TORRENT_VIEW_KEYS))
        self._set_status("Applied view: Medium")

    def _fit_torrent_columns(self) -> None:
        """Resize visible torrent table columns to fit their contents.

        Side effects: None.
        Failure modes: None.
        """
        self.tbl_torrents.resizeColumnsToContents()

    def _count_status_filter_matches(self, status_filter: str) -> int:
        """Count torrents matching one status filter using current in-memory torrent list.

        Side effects: None.
        Failure modes: None.
        """
        torrents = list(self.all_torrents or [])
        if not torrents:
            return 0
        status = str(status_filter or "all").strip().lower()
        if status == "all":
            return len(torrents)
        return sum(1 for torrent in torrents if self._torrent_matches_status_filter(torrent, status))

    def _count_category_filter_matches(self, category_filter: Any) -> int:
        """Count torrents matching one category filter using current in-memory torrent list.

        Side effects: None.
        Failure modes: None.
        """
        torrents = list(self.all_torrents or [])
        if not torrents:
            return 0
        if category_filter is None:
            return len(torrents)
        return sum(
            1
            for torrent in torrents
            if self._torrent_matches_category_filter(torrent, category_filter)
        )

    def _count_tag_filter_matches(self, tag_filter: Any) -> int:
        """Count torrents matching one tag filter using current in-memory torrent list.

        Side effects: None.
        Failure modes: None.
        """
        torrents = list(self.all_torrents or [])
        if not torrents:
            return 0
        if tag_filter is None:
            return len(torrents)
        return sum(1 for torrent in torrents if self._torrent_matches_tag_filter(torrent, tag_filter))

    def _status_filter_item_text(self, status_filter: str) -> str:
        """Build display text for one status filter row with live torrent count.

        Side effects: None.
        Failure modes: None.
        """
        status = str(status_filter or "all").strip().lower() or "all"
        label = status.replace("_", " ").title()
        count = self._count_status_filter_matches(status)
        return f"{label} ({count})"

    def _category_filter_item_text(self, category_filter: Any) -> str:
        """Build display text for one category filter row with live torrent count.

        Side effects: None.
        Failure modes: None.
        """
        if category_filter is None:
            label = "All"
        else:
            category_text = str(category_filter or "")
            label = category_text if category_text else "Uncategorized"
        count = self._count_category_filter_matches(category_filter)
        return f"{label} ({count})"

    def _tag_filter_item_text(self, tag_filter: Any) -> str:
        """Build display text for one tag filter row with live torrent count.

        Side effects: None.
        Failure modes: None.
        """
        if tag_filter is None:
            label = "All"
        else:
            tag_text = str(tag_filter or "")
            label = tag_text if tag_text else "Untagged"
        count = self._count_tag_filter_matches(tag_filter)
        return f"{label} ({count})"

    def _update_filter_tree_count_labels(self) -> None:
        """Refresh status/category/tag tree labels using latest in-memory torrent snapshot.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        if not hasattr(self, "tree_filters"):
            return
        try:
            for top_idx in range(self.tree_filters.topLevelItemCount()):
                section = self.tree_filters.topLevelItem(top_idx)
                if section is None:
                    continue
                for child_idx in range(section.childCount()):
                    item = section.child(child_idx)
                    if item is None:
                        continue
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(data, tuple) or len(data) != 2:
                        continue
                    kind, value = data
                    if kind == "status":
                        item.setText(0, self._status_filter_item_text(str(value or "all")))
                    elif kind == "category":
                        item.setText(0, self._category_filter_item_text(value))
                    elif kind == "tag":
                        item.setText(0, self._tag_filter_item_text(value))
        except Exception as e:
            self._log("ERROR", f"Error updating filter tree counts: {e}")

    def _update_category_tree(self) -> None:
        """Update category section in the unified filter tree.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            # Remove existing children
            while self._section_category.childCount():
                self._section_category.removeChild(self._section_category.child(0))

            all_item = QTreeWidgetItem([self._category_filter_item_text(None)])
            all_item.setData(0, Qt.ItemDataRole.UserRole, ('category', None))
            self._section_category.addChild(all_item)

            uncategorized = QTreeWidgetItem([self._category_filter_item_text("")])
            uncategorized.setData(0, Qt.ItemDataRole.UserRole, ('category', ""))
            self._section_category.addChild(uncategorized)

            for category in self.categories:
                item = QTreeWidgetItem([self._category_filter_item_text(category)])
                item.setData(0, Qt.ItemDataRole.UserRole, ('category', category))
                self._section_category.addChild(item)

            self._section_category.setExpanded(True)
            self._refresh_filter_tree_highlights()
        except Exception as e:
            self._log("ERROR", f"Error updating category tree: {e}")

    def _update_tag_tree(self) -> None:
        """Update tag section in the unified filter tree.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            while self._section_tag.childCount():
                self._section_tag.removeChild(self._section_tag.child(0))

            all_item = QTreeWidgetItem([self._tag_filter_item_text(None)])
            all_item.setData(0, Qt.ItemDataRole.UserRole, ('tag', None))
            self._section_tag.addChild(all_item)

            untagged = QTreeWidgetItem([self._tag_filter_item_text("")])
            untagged.setData(0, Qt.ItemDataRole.UserRole, ('tag', ""))
            self._section_tag.addChild(untagged)

            for tag in self.tags:
                item = QTreeWidgetItem([self._tag_filter_item_text(tag)])
                item.setData(0, Qt.ItemDataRole.UserRole, ('tag', tag))
                self._section_tag.addChild(item)

            self._section_tag.setExpanded(True)
            self._refresh_filter_tree_highlights()
        except Exception as e:
            self._log("ERROR", f"Error updating tag tree: {e}")

    def _calculate_size_buckets(self) -> None:
        """Calculate dynamic size buckets.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            if not self.all_torrents:
                self.size_buckets = []
                return

            sizes = [getattr(t, 'size', 0) for t in self.all_torrents if getattr(t, 'size', 0) > 0]
            if not sizes:
                self.size_buckets = []
                return

            min_size = min(sizes)
            max_size = max(sizes)
            self.size_buckets = calculate_size_buckets(min_size, max_size, SIZE_BUCKET_COUNT)
        except Exception as e:
            self._log("ERROR", f"Error calculating size buckets: {e}")
            self.size_buckets = []

    def _update_size_tree(self) -> None:
        """Update size section in the unified filter tree.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            while self._section_size.childCount():
                self._section_size.removeChild(self._section_size.child(0))

            all_item = QTreeWidgetItem(["All"])
            all_item.setData(0, Qt.ItemDataRole.UserRole, ('size', None))
            self._section_size.addChild(all_item)

            for start, end in self.size_buckets:
                label = (
                    f"{format_size_mode(start, self.display_size_mode)} - "
                    f"{format_size_mode(end, self.display_size_mode)}"
                )
                item = QTreeWidgetItem([label])
                item.setData(0, Qt.ItemDataRole.UserRole, ('size', (start, end)))
                self._section_size.addChild(item)

            self._section_size.setExpanded(True)
            self._refresh_filter_tree_highlights()
        except Exception as e:
            self._log("ERROR", f"Error updating size tree: {e}")

    def _extract_trackers(self) -> None:
        """Extract unique tracker hostnames from loaded torrents.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            tracker_set = set()
            for t in self.all_torrents:
                tracker_url = getattr(t, 'tracker', '') or ''
                if tracker_url:
                    try:
                        parsed = urlparse(tracker_url)
                        hostname = parsed.hostname or tracker_url
                        tracker_set.add(hostname)
                    except Exception:
                        tracker_set.add(tracker_url)
            self.trackers = sorted(tracker_set)
        except Exception as e:
            self._log("ERROR", f"Error extracting trackers: {e}")
            self.trackers = []

    def _update_tracker_tree(self) -> None:
        """Update tracker section in the unified filter tree.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            while self._section_tracker.childCount():
                self._section_tracker.removeChild(self._section_tracker.child(0))

            all_item = QTreeWidgetItem(["All"])
            all_item.setData(0, Qt.ItemDataRole.UserRole, ('tracker', None))
            self._section_tracker.addChild(all_item)

            for tracker in self.trackers:
                item = QTreeWidgetItem([str(tracker)])
                item.setData(0, Qt.ItemDataRole.UserRole, ('tracker', tracker))
                self._section_tracker.addChild(item)

            self._section_tracker.setExpanded(True)
            self._refresh_filter_tree_highlights()
        except Exception as e:
            self._log("ERROR", f"Error updating tracker tree: {e}")

    def _on_quick_filter_changed(self, *_args) -> None:
        """Apply filter-bar changes immediately.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._apply_filters()

    def _on_filter_changed(self) -> None:
        """Handle filter change from filter bar.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        # Store current filter values
        private_text = self.cmb_private.currentText()
        if private_text == "Yes":
            self.current_private_filter = True
        elif private_text == "No":
            self.current_private_filter = False
        else:
            self.current_private_filter = None

        self.current_text_filter = normalize_filter_pattern(self.txt_name_filter.text())
        self.current_file_filter = normalize_filter_pattern(self.txt_file_filter.text())

    def _apply_filters(self) -> None:
        """Apply all current filters to torrents.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            self._on_filter_changed()

            filtered = self.all_torrents[:]  # Make a copy

            # Apply API-equivalent filters locally when using sync/maindata.
            if (
                self._sync_torrent_map
                and not bool(self._latest_torrent_fetch_remote_filtered)
            ):
                if self.current_status_filter and self.current_status_filter != "all":
                    filtered = [
                        t for t in filtered
                        if self._torrent_matches_status_filter(t, self.current_status_filter)
                    ]
                if self.current_category_filter is not None:
                    filtered = [
                        t for t in filtered
                        if self._torrent_matches_category_filter(t, self.current_category_filter)
                    ]
                if self.current_tag_filter is not None:
                    filtered = [
                        t for t in filtered
                        if self._torrent_matches_tag_filter(t, self.current_tag_filter)
                    ]

            # Apply text filter
            if self.current_text_filter:
                try:
                    filtered = [
                        t for t in filtered
                        if matches_wildcard(getattr(t, 'name', ''), self.current_text_filter)
                    ]
                except Exception as e:
                    self._log("ERROR", f"Error applying text filter: {e}")

            # Apply private filter
            if self.current_private_filter is not None:
                try:
                    filtered = [
                        t for t in filtered
                        if bool(getattr(t, "private", False)) == self.current_private_filter
                    ]
                except Exception as e:
                    self._log("ERROR", f"Error applying private filter: {e}")

            # Apply tracker filter
            if self.current_tracker_filter is not None:
                try:
                    filtered = [
                        t for t in filtered
                        if self._torrent_matches_tracker(t, self.current_tracker_filter)
                    ]
                except Exception as e:
                    self._log("ERROR", f"Error applying tracker filter: {e}")

            # Apply size bucket filter
            if self.current_size_bucket:
                try:
                    start, end = self.current_size_bucket
                    filtered = [
                        t for t in filtered
                        if start <= getattr(t, 'size', 0) <= end
                    ]
                except Exception as e:
                    self._log("ERROR", f"Error applying size filter: {e}")

            # Apply file-name filter (local cache only)
            if self.current_file_filter:
                filtered = [
                    t for t in filtered
                    if self._matches_file_filter(getattr(t, 'hash', ''), self.current_file_filter)
                ]

            self.filtered_torrents = filtered
            self._update_torrents_table()
            self._log("INFO", f"Filters applied: {len(self.filtered_torrents)} torrents match")
        except Exception as e:
            self._log("ERROR", f"Error applying filters: {e}")
            self.filtered_torrents = []
            self._update_torrents_table()

    def _torrent_matches_status_filter(self, torrent, status_filter: str) -> bool:
        """Approximate qBittorrent status filters from torrent state/speeds.

        Side effects: None.
        Failure modes: None.
        """
        state = str(getattr(torrent, "state", "") or "").strip().lower()
        status = str(status_filter or "").strip().lower()

        is_paused = state.startswith("paused")
        is_active = (
            self._safe_int(getattr(torrent, "dlspeed", 0), 0) > 0
            or self._safe_int(getattr(torrent, "upspeed", 0), 0) > 0
        )
        is_complete = self._safe_float(getattr(torrent, "progress", 0.0), 0.0) >= 1.0

        if status == "all":
            return True
        if status == "downloading":
            return state in {
                "downloading", "metadl", "forcedmetadl", "queueddl", "stalleddl",
                "checkingdl", "forceddl", "allocating"
            }
        if status == "seeding":
            return state in {
                "uploading", "stalledup", "queuedup", "checkingup", "forcedup"
            }
        if status == "completed":
            return is_complete
        if status in {"paused", "stopped"}:
            return is_paused
        if status == "active":
            return is_active
        if status == "inactive":
            return not is_active
        if status in {"resumed", "running"}:
            return not is_paused
        if status == "stalled":
            return "stalled" in state
        if status == "stalled_uploading":
            return state == "stalledup"
        if status == "stalled_downloading":
            return state == "stalleddl"
        if status == "checking":
            return "checking" in state
        if status == "moving":
            return "moving" in state
        if status == "errored":
            return state in {"error", "missingfiles", "unknown"}
        return True

    @staticmethod
    def _torrent_matches_category_filter(torrent, category_filter: Any) -> bool:
        """Match one torrent against selected category filter.

        Side effects: None.
        Failure modes: None.
        """
        torrent_category = str(getattr(torrent, "category", "") or "")
        return torrent_category == str(category_filter or "")

    def _torrent_matches_tag_filter(self, torrent, tag_filter: Any) -> bool:
        """Match one torrent against selected tag filter.

        Side effects: None.
        Failure modes: None.
        """
        tag = str(tag_filter or "")
        tags = parse_tags(getattr(torrent, "tags", None))
        if tag == "":
            return len(tags) == 0
        return tag in tags

    def _clear_filters(self) -> None:
        """Clear all filters.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self.current_status_filter = 'all'
        self._clear_non_status_filters()

        # Clear tree selection
        self.tree_filters.clearSelection()
        self._refresh_filter_tree_highlights()

        self._refresh_torrents()

    def _clear_non_status_filters(self) -> None:
        """Clear non-status torrent filters from quick bar and tree sections.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        private_signals = self.cmb_private.blockSignals(True)
        self.cmb_private.setCurrentIndex(0)
        self.cmb_private.blockSignals(private_signals)
        self.current_private_filter = None

        name_signals = self.txt_name_filter.blockSignals(True)
        self.txt_name_filter.clear()
        self.txt_name_filter.blockSignals(name_signals)

        file_signals = self.txt_file_filter.blockSignals(True)
        self.txt_file_filter.clear()
        self.txt_file_filter.blockSignals(file_signals)

        self.current_category_filter = None
        self.current_tag_filter = None
        self.current_size_bucket = None
        self.current_tracker_filter = None

    def _show_status_filter_only(self, status_filter: str) -> None:
        """Show one status bucket and clear all other torrent filters.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        status = str(status_filter or "all").strip().lower()
        if status not in STATUS_FILTERS:
            status = "all"
        self.current_status_filter = status
        self._clear_non_status_filters()

        # Clear tree selection
        self.tree_filters.clearSelection()
        self._refresh_filter_tree_highlights()

        self._refresh_torrents()

    def _show_active_torrents_only(self) -> None:
        """Show only active torrents and clear all non-status filters.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._show_status_filter_only("active")

    def _show_completed_torrents_only(self) -> None:
        """Show only completed torrents and clear all non-status filters.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._show_status_filter_only("completed")

    def _show_all_torrents_only(self) -> None:
        """Show all torrents and clear all non-status filters.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._show_status_filter_only("all")

    def _on_filter_tree_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Handle click on the unified filter tree.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None and item.childCount() > 0:
            # Section header clicked ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â just toggle expand/collapse
            return
        try:
            if not isinstance(data, tuple):
                return
            kind, value = data
            if kind == 'status':
                self.current_status_filter = value
                self._log("INFO", f"Status filter changed to: {value}")
                self._refresh_filter_tree_highlights()
                self._refresh_torrents()
            elif kind == 'category':
                self.current_category_filter = value
                self._log("INFO", f"Category filter changed to: {value}")
                self._refresh_filter_tree_highlights()
                self._refresh_torrents()
            elif kind == 'tag':
                self.current_tag_filter = value
                self._log("INFO", f"Tag filter changed to: {value}")
                self._refresh_filter_tree_highlights()
                self._refresh_torrents()
            elif kind == 'size':
                self.current_size_bucket = value
                self._log("INFO", "Size filter changed")
                self._refresh_filter_tree_highlights()
                self._apply_filters()
            elif kind == 'tracker':
                self.current_tracker_filter = value
                self._log("INFO", f"Tracker filter selected: {value}")
                self._refresh_filter_tree_highlights()
                self._apply_filters()
        except Exception as e:
            self._log("ERROR", f"Error handling filter click: {e}")

    @staticmethod
    def _torrent_matches_tracker(torrent, tracker_hostname: str) -> bool:
        """Check if a torrent's tracker matches the given hostname.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        tracker_url = getattr(torrent, 'tracker', '') or ''
        if not tracker_url:
            return False
        try:
            parsed = urlparse(tracker_url)
            return (parsed.hostname or tracker_url) == tracker_hostname
        except Exception:
            return tracker_url == tracker_hostname

    def _tracker_display_text(self, tracker_url: str) -> str:
        """Render tracker URL as hostname where possible.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        text = str(tracker_url or "")
        if not text:
            return ""
        try:
            parsed = urlparse(text)
            return parsed.hostname or text
        except Exception:
            return text

    def _format_torrent_table_cell(
        self,
        torrent: Any,
        column_key: str,
    ) -> Tuple[str, Qt.AlignmentFlag, Optional[float]]:
        """Return display text, alignment, and optional numeric sort value.

        Side effects: None.
        Failure modes: None.
        """
        align_left = Qt.AlignmentFlag.AlignLeft
        align_right = Qt.AlignmentFlag.AlignRight
        align_center = Qt.AlignmentFlag.AlignCenter

        def _raw_value(key: str, default: Any = None) -> Any:
            """Read one attribute from torrent object with fallback.

            Side effects: None.
            Failure modes: None.
            """
            return getattr(torrent, key, default)

        def _as_bool(value: Any) -> Optional[bool]:
            """Normalize bool-like values, returning None when undecidable.

            Side effects: None.
            Failure modes: None.
            """
            if value is None:
                return None
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
            return None

        if column_key in {"hash", "name", "state", "category", "save_path", "content_path", "magnet_uri"}:
            return str(_raw_value(column_key, "") or ""), align_left, None
        if column_key in {
            "size",
            "total_size",
            "downloaded",
            "uploaded",
            "amount_left",
            "completed",
            "downloaded_session",
            "uploaded_session",
        }:
            raw = self._safe_int(_raw_value(column_key, 0), 0)
            return format_size_mode(raw, self.display_size_mode), align_right, float(raw)
        if column_key == "progress":
            raw = self._safe_float(_raw_value("progress", 0), 0.0)
            return f"{raw * 100:.1f}%", align_right, float(raw)
        if column_key in {"dlspeed", "upspeed", "dl_limit", "up_limit"}:
            raw = self._safe_int(_raw_value(column_key, 0), 0)
            return format_speed_mode(raw, self.display_speed_mode), align_right, float(raw)
        if column_key in {"ratio", "availability", "max_ratio", "ratio_limit"}:
            raw = self._safe_float(_raw_value(column_key, 0), 0.0)
            return format_float(raw), align_right, float(raw)
        if column_key in {
            "num_seeds",
            "num_leechs",
            "num_complete",
            "num_incomplete",
            "num_files",
            "priority",
        }:
            raw = self._safe_int(_raw_value(column_key, 0), 0)
            return format_int(raw), align_right, float(raw)
        if column_key in {"eta", "reannounce", "seeding_time", "time_active"}:
            raw = self._safe_int(_raw_value(column_key, 0), 0)
            return format_eta(raw), align_right, float(raw)
        if column_key in {"seeding_time_limit", "max_seeding_time"}:
            raw = self._safe_int(_raw_value(column_key, 0), 0)
            if raw < 0:
                return "Unlimited", align_right, float(raw)
            return format_eta(raw), align_right, float(raw)
        if column_key in {"added_on", "completion_on", "last_activity", "seen_complete"}:
            raw = self._safe_int(_raw_value(column_key, 0), 0)
            return format_datetime(raw), align_left, float(raw)
        if column_key == "tags":
            tags_text = ", ".join(parse_tags(_raw_value("tags", None)))
            return tags_text, align_left, None
        if column_key == "tracker":
            tracker_text = self._tracker_display_text(_raw_value("tracker", ""))
            return tracker_text, align_left, None
        if column_key in {"auto_tmm", "force_start", "seq_dl", "f_l_piece_prio", "super_seeding", "private"}:
            bool_value = _as_bool(_raw_value(column_key, None))
            if bool_value is True:
                return "Yes", align_center, 1.0
            if bool_value is False:
                return "No", align_center, 0.0
            return "", align_center, -1.0

        return str(_raw_value(column_key, "") or ""), align_left, None

    def _update_torrents_table(self) -> None:
        """Update the torrents table with filtered data.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            self.tbl_torrents.setSortingEnabled(False)
            self.tbl_torrents.setRowCount(len(self.filtered_torrents))

            for row, torrent in enumerate(self.filtered_torrents):
                try:
                    for col_idx, column in enumerate(self.torrent_columns):
                        text, align, sort_value = self._format_torrent_table_cell(
                            torrent, column["key"]
                        )
                        self._set_table_item(
                            row, col_idx, text, align=align, sort_value=sort_value
                        )
                except Exception as e:
                    self._log("ERROR", f"Error updating row {row}: {e}")
                    continue

            self.tbl_torrents.setSortingEnabled(True)
            self.lbl_count.setText(f"{len(self.filtered_torrents)} torrents")
        except Exception as e:
            self._log("ERROR", f"Error updating torrents table: {e}")
            self.lbl_count.setText("0 torrents")

class DetailsContentController(WindowControllerBase):
    def _populate_content_tree(self, files: List[Dict[str, Any]]) -> None:
        """Populate the content tab from cached/serialized file entries.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            self.tree_files.clear()

            PRIORITY_NAMES = {0: "Skip", 1: "Normal", 6: "High", 7: "Maximum"}

            # Build a nested dict for directory structure
            dir_nodes: Dict[str, QTreeWidgetItem] = {}
            for f in files:
                if isinstance(f, dict):
                    name = str(f.get('name', '') or '')
                    size = self._safe_int(f.get('size', 0), 0)
                    progress = self._safe_float(f.get('progress', 0.0), 0.0)
                    priority = self._safe_int(f.get('priority', 1), 1)
                else:
                    name = getattr(f, 'name', '') or ''
                    size = getattr(f, 'size', 0)
                    progress = getattr(f, 'progress', 0)
                    priority = getattr(f, 'priority', 1)

                if not name:
                    continue

                parts = name.replace('\\', '/').split('/')
                parent = None
                for i, part in enumerate(parts[:-1]):
                    dir_key = '/'.join(parts[:i + 1])
                    if dir_key not in dir_nodes:
                        node = QTreeWidgetItem([part, '', '', ''])
                        node.setData(
                            0,
                            Qt.ItemDataRole.UserRole,
                            {"relative_path": dir_key, "is_file": False},
                        )
                        if parent:
                            parent.addChild(node)
                        else:
                            self.tree_files.addTopLevelItem(node)
                        dir_nodes[dir_key] = node
                    parent = dir_nodes[dir_key]

                file_item = QTreeWidgetItem([
                    parts[-1],
                    format_size_mode(size, self.display_size_mode),
                    f"{progress * 100:.1f}%",
                    PRIORITY_NAMES.get(priority, str(priority))
                ])
                file_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {"relative_path": name.replace("\\", "/"), "is_file": True},
                )
                if parent:
                    parent.addChild(file_item)
                else:
                    self.tree_files.addTopLevelItem(file_item)

            self.tree_files.expandAll()
        except Exception as e:
            self._log("ERROR", f"Error populating file tree: {e}")

    def _on_content_filter_changed(self, text: str) -> None:
        """Apply in-tab content filter for selected torrent files.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self.current_content_filter = normalize_filter_pattern(text)
        self._apply_content_filter()

    def _apply_content_filter(self) -> None:
        """Apply content-file filter to currently loaded selected torrent files.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            files = self.current_content_files or []
            pattern = self.current_content_filter

            if not files:
                self.tree_files.clear()
                self.tree_files.addTopLevelItem(
                    QTreeWidgetItem(["(Content cache not available yet)", "", "", ""])
                )
                return

            if pattern:
                filtered_files = []
                for entry in files:
                    name = str(entry.get('name', '') or '')
                    normalized = name.replace('\\', '/')
                    basename = normalized.rsplit('/', 1)[-1] if '/' in normalized else normalized
                    if matches_wildcard(basename, pattern) or matches_wildcard(normalized, pattern):
                        filtered_files.append(entry)
            else:
                filtered_files = files

            if not filtered_files:
                self.tree_files.clear()
                self.tree_files.addTopLevelItem(
                    QTreeWidgetItem(["(No files match current content filter)", "", "", ""])
                )
                return

            self._populate_content_tree(filtered_files)
        except Exception as e:
            self._log("ERROR", f"Error applying content filter: {e}")

    def _show_cached_torrent_content(self, torrent_hash: str) -> None:
        """Display content tree from local cache for selected torrent.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self.current_content_files = self._get_cached_files(torrent_hash)
        self._apply_content_filter()

    def _set_table_item(self, row: int, col: int, text: str,
                        align=Qt.AlignmentFlag.AlignLeft,
                        sort_value: Optional[float] = None) -> None:
        """Helper to set table item with alignment and optional numeric sort.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if sort_value is not None:
            item = NumericTableWidgetItem(str(text), sort_value)
        else:
            item = QTableWidgetItem(str(text))
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        self.tbl_torrents.setItem(row, col, item)

    def _copy_general_details(self) -> None:
        """Copy general details panel content to clipboard.

        Side effects: None.
        Failure modes: None.
        """
        text = self.txt_general_details.toPlainText().strip()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._set_status("General details copied to clipboard")

    @staticmethod
    def _details_table_has_data_rows(table: QTableWidget) -> bool:
        """Return True when details table contains actual data rows (not info placeholder).

        Side effects: None.
        Failure modes: None.
        """
        if table.rowCount() <= 0 or table.columnCount() <= 0:
            return False
        if table.columnCount() == 1:
            header = table.horizontalHeaderItem(0)
            if header and str(header.text() or "").strip().lower() == "info":
                return False
        return True

    @staticmethod
    def _details_table_column_index(table: QTableWidget, column_name: str) -> int:
        """Find one details-table column index by header name (case-insensitive).

        Side effects: None.
        Failure modes: None.
        """
        target = str(column_name or "").strip().lower()
        if not target:
            return -1
        for col_idx in range(table.columnCount()):
            header = table.horizontalHeaderItem(col_idx)
            if not header:
                continue
            if str(header.text() or "").strip().lower() == target:
                return col_idx
        return -1

    @staticmethod
    def _selected_table_row(table: QTableWidget) -> Optional[int]:
        """Return first selected row index for table, if any.

        Side effects: None.
        Failure modes: None.
        """
        sel_model = table.selectionModel()
        if sel_model:
            selected_rows = sel_model.selectedRows()
            if selected_rows:
                return selected_rows[0].row()
        current = table.currentRow()
        return current if current >= 0 else None

    def _details_table_to_tsv(self, table: QTableWidget, row_indexes: Optional[List[int]] = None) -> str:
        """Serialize one details table subset to TSV (header + rows).

        Side effects: None.
        Failure modes: None.
        """
        headers: List[str] = []
        for col_idx in range(table.columnCount()):
            header = table.horizontalHeaderItem(col_idx)
            headers.append(str(header.text() if header else f"column_{col_idx}"))

        rows = list(row_indexes) if row_indexes is not None else list(range(table.rowCount()))
        lines = ["\t".join(headers)]
        for row_idx in rows:
            values: List[str] = []
            for col_idx in range(table.columnCount()):
                item = table.item(row_idx, col_idx)
                values.append(str(item.text() if item else ""))
            lines.append("\t".join(values))
        return "\n".join(lines)

    def _selected_peer_endpoint(self) -> str:
        """Return selected peer endpoint as IP:port.

        Side effects: None.
        Failure modes: None.
        """
        if not self._details_table_has_data_rows(self.tbl_peers):
            return ""
        row_idx = self._selected_table_row(self.tbl_peers)
        if row_idx is None:
            return ""
        ip_col = self._details_table_column_index(self.tbl_peers, "ip")
        port_col = self._details_table_column_index(self.tbl_peers, "port")
        if ip_col < 0 or port_col < 0:
            return ""

        ip_item = self.tbl_peers.item(row_idx, ip_col)
        port_item = self.tbl_peers.item(row_idx, port_col)
        ip_text = str(ip_item.text() if ip_item else "").strip()
        port_text = str(port_item.text() if port_item else "").strip()
        if not ip_text or not port_text:
            return ""
        return f"{ip_text}:{port_text}"

    def _copy_all_peers_info(self) -> None:
        """Copy all currently visible peers rows (including headers) to clipboard.

        Side effects: None.
        Failure modes: None.
        """
        if not self._details_table_has_data_rows(self.tbl_peers):
            self._set_status("No peers info to copy")
            return
        text = self._details_table_to_tsv(self.tbl_peers)
        QApplication.clipboard().setText(text)
        self._set_status("All peers info copied to clipboard")

    def _copy_selected_peer_info(self) -> None:
        """Copy selected peer row (including headers) to clipboard.

        Side effects: None.
        Failure modes: None.
        """
        if not self._details_table_has_data_rows(self.tbl_peers):
            self._set_status("No peers info to copy")
            return
        row_idx = self._selected_table_row(self.tbl_peers)
        if row_idx is None:
            self._set_status("Select one peer first")
            return
        text = self._details_table_to_tsv(self.tbl_peers, [row_idx])
        QApplication.clipboard().setText(text)
        self._set_status("Peer info copied to clipboard")

    def _copy_selected_peer_ip_port(self) -> None:
        """Copy selected peer endpoint to clipboard.

        Side effects: None.
        Failure modes: None.
        """
        endpoint = self._selected_peer_endpoint()
        if not endpoint:
            self._set_status("Select one peer with valid IP and port")
            return
        QApplication.clipboard().setText(endpoint)
        self._set_status("Peer IP:port copied to clipboard")

    def _build_peers_context_menu(self) -> QMenu:
        """Build context menu for peers table.

        Side effects: None.
        Failure modes: None.
        """
        menu = QMenu(self)
        has_data = self._details_table_has_data_rows(self.tbl_peers)
        has_selection = has_data and self._selected_table_row(self.tbl_peers) is not None
        endpoint = self._selected_peer_endpoint()
        has_endpoint = bool(endpoint)

        action_copy_all = menu.addAction("Copy All Peers Info")
        action_copy_all.triggered.connect(self._copy_all_peers_info)
        action_copy_all.setEnabled(has_data)

        action_copy_peer = menu.addAction("Copy Peer Info")
        action_copy_peer.triggered.connect(self._copy_selected_peer_info)
        action_copy_peer.setEnabled(has_selection)

        action_copy_ip_port = menu.addAction("Copy Peer IP:port")
        action_copy_ip_port.triggered.connect(self._copy_selected_peer_ip_port)
        action_copy_ip_port.setEnabled(has_endpoint)

        menu.addSeparator()

        action_ban = menu.addAction("Ban Peer")
        action_ban.triggered.connect(self._ban_selected_peer)
        action_ban.setEnabled(has_endpoint)
        return menu

    def _show_peers_context_menu(self, pos) -> None:
        """Show peers context menu and keep right-clicked row selected.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        row_idx = self.tbl_peers.rowAt(pos.y())
        if row_idx >= 0:
            self.tbl_peers.selectRow(row_idx)
        menu = self._build_peers_context_menu()
        menu.exec(self.tbl_peers.viewport().mapToGlobal(pos))

    def _ban_selected_peer(self) -> None:
        """Ban selected peer endpoint via qBittorrent API.

        Side effects: None.
        Failure modes: None.
        """
        endpoint = self._selected_peer_endpoint()
        if not endpoint:
            self._set_status("Select one peer with valid IP and port")
            return

        reply = QMessageBox.question(
            self,
            "Ban Peer",
            f"Ban peer {endpoint}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._show_progress("Banning peer...")
        self.api_queue.add_task(
            "ban_peer",
            self._api_ban_peers,
            lambda r, peer=endpoint: self._on_ban_peer_done(peer, r),
            [endpoint],
        )

    @staticmethod
    def _display_detail_value(value: Any, fallback: str = "N/A") -> str:
        """Normalize one detail value for display.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if value is None:
            return fallback
        if isinstance(value, str):
            text = value.strip()
            return text if text else fallback
        return str(value)

    def _build_general_details_html(self, sections: List[Tuple[str, List[Tuple[str, Any]]]]) -> str:
        """Build rich read-only HTML layout for the General details panel.

        Side effects: None.
        Failure modes: None.
        """
        chunks = ["<html><body>"]
        for title, rows in sections:
            chunks.append(f"<h3>{html.escape(str(title))}</h3>")
            chunks.append("<table>")
            for key, value in rows:
                key_text = html.escape(str(key))
                value_text = html.escape(self._display_detail_value(value))
                chunks.append(
                    f"<tr><td class=\"key\">{key_text}</td><td class=\"value\">{value_text}</td></tr>"
                )
            chunks.append("</table>")
        chunks.append("</body></html>")
        return "".join(chunks)

    def _set_torrent_edit_enabled(self, enabled: bool, message: str) -> None:
        """Enable/disable torrent edit controls and update state message.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self.lbl_torrent_edit_state.setText(str(message or ""))
        enabled_flag = bool(enabled)
        self.txt_torrent_edit_name.setEnabled(enabled_flag)
        self.chk_torrent_edit_auto_tmm.setEnabled(enabled_flag)
        self.cmb_torrent_edit_category.setEnabled(enabled_flag)
        self.txt_torrent_edit_tags.setEnabled(enabled_flag)
        self.btn_torrent_edit_add_tags.setEnabled(enabled_flag)
        self.spn_torrent_edit_download_limit.setEnabled(enabled_flag)
        self.spn_torrent_edit_upload_limit.setEnabled(enabled_flag)
        self.txt_torrent_edit_save_path.setEnabled(enabled_flag)
        self.btn_torrent_edit_browse_save_path.setEnabled(enabled_flag)
        self.txt_torrent_edit_incomplete_path.setEnabled(enabled_flag)
        self.btn_torrent_edit_browse_incomplete_path.setEnabled(enabled_flag)
        self.btn_torrent_edit_apply.setEnabled(enabled_flag)
        self._update_torrent_edit_path_browse_buttons()

    def _clear_torrent_edit_panel(self, message: str) -> None:
        """Reset editable torrent fields.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._torrent_edit_original = {}
        self.txt_torrent_edit_name.clear()
        self.chk_torrent_edit_auto_tmm.setCheckState(Qt.CheckState.PartiallyChecked)
        self.cmb_torrent_edit_category.blockSignals(True)
        self.cmb_torrent_edit_category.clear()
        self.cmb_torrent_edit_category.addItems([""] + self.categories)
        self.cmb_torrent_edit_category.blockSignals(False)
        self.txt_torrent_edit_tags.clear()
        self.spn_torrent_edit_download_limit.setValue(0)
        self.spn_torrent_edit_upload_limit.setValue(0)
        self.txt_torrent_edit_save_path.clear()
        self.txt_torrent_edit_incomplete_path.clear()
        self._set_torrent_edit_enabled(False, message)

    def _refresh_torrent_edit_categories(self, current_category: str = "") -> None:
        """Refresh category combo options while preserving text selection.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        current_text = str(current_category or self.cmb_torrent_edit_category.currentText() or "").strip()
        self.cmb_torrent_edit_category.blockSignals(True)
        self.cmb_torrent_edit_category.clear()
        self.cmb_torrent_edit_category.addItems([""] + self.categories)
        idx = self.cmb_torrent_edit_category.findText(current_text)
        if idx >= 0:
            self.cmb_torrent_edit_category.setCurrentIndex(idx)
        else:
            self.cmb_torrent_edit_category.setEditText(current_text)
        self.cmb_torrent_edit_category.blockSignals(False)

    @staticmethod
    def _torrent_auto_management_value(torrent: Any) -> Optional[bool]:
        """Extract automatic torrent management state when available.

        Side effects: None.
        Failure modes: None.
        """
        for key in (
            "auto_tmm",
            "auto_management",
            "automatic_torrent_management",
            "use_auto_torrent_management",
        ):
            raw = getattr(torrent, key, None)
            if raw is None:
                continue
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, (int, float)):
                return bool(raw)
            text = str(raw).strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
        return None

    def _populate_torrent_edit_panel(self, torrent: Any) -> None:
        """Populate the editable torrent panel from selected torrent data.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        torrent_name = str(getattr(torrent, "name", "") or "").strip()
        auto_tmm = self._torrent_auto_management_value(torrent)
        category = str(getattr(torrent, "category", "") or "").strip()
        tags = parse_tags(getattr(torrent, "tags", None))
        save_path = str(getattr(torrent, "save_path", "") or "").strip()
        download_path = str(getattr(torrent, "download_path", "") or "").strip()
        download_limit_kib = self._bytes_to_kib(getattr(torrent, "dl_limit", 0))
        upload_limit_kib = self._bytes_to_kib(getattr(torrent, "up_limit", 0))

        self._torrent_edit_original = {
            "hash": str(getattr(torrent, "hash", "") or ""),
            "name": torrent_name,
            "auto_tmm": auto_tmm,
            "category": category,
            "tags": ",".join(tags),
            "save_path": save_path,
            "download_path": download_path,
            "download_limit_kib": download_limit_kib,
            "upload_limit_kib": upload_limit_kib,
        }

        if auto_tmm is None:
            self.chk_torrent_edit_auto_tmm.setCheckState(Qt.CheckState.PartiallyChecked)
        elif auto_tmm:
            self.chk_torrent_edit_auto_tmm.setCheckState(Qt.CheckState.Checked)
        else:
            self.chk_torrent_edit_auto_tmm.setCheckState(Qt.CheckState.Unchecked)

        self.txt_torrent_edit_name.setText(torrent_name)
        self._refresh_torrent_edit_categories(category)
        self.txt_torrent_edit_tags.setText(", ".join(tags))
        self.spn_torrent_edit_download_limit.setValue(download_limit_kib)
        self.spn_torrent_edit_upload_limit.setValue(upload_limit_kib)
        self.txt_torrent_edit_save_path.setText(save_path)
        self.txt_torrent_edit_incomplete_path.setText(download_path)

        if torrent_name:
            self._set_torrent_edit_enabled(True, f"Editing [ {torrent_name} ]")
        else:
            self._set_torrent_edit_enabled(True, "Editing selected torrent")

    @staticmethod
    def _normalize_tags_csv(value: str) -> str:
        """Normalize tag CSV to comma-separated string without extra spaces.

        Side effects: None.
        Failure modes: None.
        """
        return ",".join(parse_tags(value))

    def _add_tags_to_torrent_edit(self) -> None:
        """Append selected tags from a multi-select dialog into edit tags field.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        available_tags = sorted(
            {str(tag).strip() for tag in list(self.tags or []) if str(tag).strip()},
            key=lambda value: value.lower(),
        )
        if not available_tags:
            self._set_status("No tags available to add")
            return

        current_tags = parse_tags(self.txt_torrent_edit_tags.text())
        selected_tags = self._pick_tags_for_torrent_edit(available_tags, current_tags)
        if selected_tags is None:
            return

        merged_tags = list(current_tags)
        for tag in selected_tags:
            normalized_tag = str(tag).strip()
            if normalized_tag and normalized_tag not in merged_tags:
                merged_tags.append(normalized_tag)
        self.txt_torrent_edit_tags.setText(", ".join(merged_tags))

    def _pick_tags_for_torrent_edit(self, available_tags: List[str], selected_tags: List[str]) -> Optional[List[str]]:
        """Show multi-select picker for known tags and return selected values.

        Side effects: None.
        Failure modes: None.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Tags")
        parent_rect = self.frameGeometry()
        parent_width = parent_rect.width() if parent_rect.width() > 0 else max(1, self.width())
        parent_height = parent_rect.height() if parent_rect.height() > 0 else max(1, self.height())
        dialog_width = 212
        dialog_height = max(1, int(parent_height * 0.90))
        dialog_x = parent_rect.x() + int(parent_width * 0.70)
        dialog_y = parent_rect.y() + max(0, (parent_height - dialog_height) // 2)
        dialog.setGeometry(dialog_x, dialog_y, dialog_width, dialog_height)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Select tags to add:"))

        list_widget = QListWidget(dialog)
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        selected_set = {str(tag).strip() for tag in list(selected_tags or []) if str(tag).strip()}
        for tag in available_tags:
            item = QListWidgetItem(tag)
            item.setSelected(tag in selected_set)
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return [item.text().strip() for item in list_widget.selectedItems() if item.text().strip()]

    def _path_exists_on_local_machine(self, raw_path: Any) -> bool:
        """Return True when a provided path exists on this machine.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        candidate = self._expand_local_path(raw_path)
        if candidate is None:
            return False
        try:
            return candidate.exists()
        except Exception:
            return False

    def _update_torrent_edit_path_browse_buttons(self) -> None:
        """Show browse buttons only for paths that exist on this machine.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        save_exists = self._path_exists_on_local_machine(self.txt_torrent_edit_save_path.text())
        incomplete_exists = self._path_exists_on_local_machine(self.txt_torrent_edit_incomplete_path.text())
        self.btn_torrent_edit_browse_save_path.setVisible(save_exists)
        self.btn_torrent_edit_browse_incomplete_path.setVisible(incomplete_exists)

    def _on_detail_tab_changed(self, _index: int) -> None:
        """React to details tab switches that affect auto-refresh policy.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._sync_auto_refresh_timer_state()

    def _is_torrent_edit_tab_active(self) -> bool:
        """Return True when Edit tab is selected and active for editing.

        Side effects: None.
        Failure modes: None.
        """
        if not self.detail_tabs.isEnabled():
            return False
        if self.tab_torrent_edit is None:
            return False
        if self.detail_tabs.currentWidget() is not self.tab_torrent_edit:
            return False
        return self.btn_torrent_edit_apply.isEnabled()

    @staticmethod
    def _detail_cell_text(value: Any) -> str:
        """Render one trackers/peers cell value to text.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple, set)):
            try:
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            except Exception:
                return str(value)
        return str(value)

    @staticmethod
    def _detail_sort_value(value: Any) -> Optional[float]:
        """Return numeric sort value when possible.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip().replace(",", "")
            if not text:
                return None
            try:
                return float(text)
            except Exception:
                return None
        return None

    @staticmethod
    def _build_details_columns(rows: List[Dict[str, Any]], preferred: List[str]) -> List[str]:
        """Build ordered column list with preferred first, then remaining keys.

        Side effects: None.
        Failure modes: None.
        """
        key_set = set()
        for row in rows:
            key_set.update(str(k) for k in row.keys())

        ordered = [k for k in preferred if k in key_set]
        remainder = sorted(k for k in key_set if k not in ordered)
        return ordered + remainder

    def _set_details_table_message(self, table: QTableWidget, message: str) -> None:
        """Show one-line status message inside details table.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        table.setSortingEnabled(False)
        table.clearContents()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["Info"])
        item = QTableWidgetItem(message)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(0, 0, item)
        table.horizontalHeader().setStretchLastSection(True)

    def _populate_details_table(self, table: QTableWidget, rows: List[Dict[str, Any]],
                                preferred_columns: List[str]) -> None:
        """Populate one details table (trackers/peers) with dynamic columns.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if not rows:
            self._set_details_table_message(table, "No data available.")
            return

        columns = self._build_details_columns(rows, preferred_columns)

        table.setSortingEnabled(False)
        table.clearContents()
        table.setRowCount(len(rows))
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)

        for row_idx, row in enumerate(rows):
            for col_idx, key in enumerate(columns):
                raw_value = row.get(key)
                text = self._detail_cell_text(raw_value)
                sort_value = self._detail_sort_value(raw_value)
                if sort_value is not None:
                    item = NumericTableWidgetItem(text, sort_value)
                    align = Qt.AlignmentFlag.AlignRight
                else:
                    item = QTableWidgetItem(text)
                    align = Qt.AlignmentFlag.AlignLeft
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_idx, col_idx, item)

        table.setSortingEnabled(True)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)

    def _selected_torrent_hash(self) -> str:
        """Return selected torrent hash, or empty string when none selected.

        Side effects: None.
        Failure modes: None.
        """
        selected = getattr(self, "_selected_torrent", None)
        return str(getattr(selected, "hash", "") or "")

    def _load_selected_torrent_network_details(self, torrent_hash: str) -> None:
        """Load full trackers and peers information for selected torrent.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._set_details_table_message(self.tbl_trackers, "Loading trackers...")
        self._set_details_table_message(self.tbl_peers, "Loading peers...")

        self.details_api_queue.add_task(
            "load_selected_trackers",
            self._fetch_selected_torrent_trackers,
            lambda r, h=torrent_hash: self._on_selected_trackers_loaded(h, r),
            torrent_hash
        )

    def _on_selected_trackers_loaded(self, torrent_hash: str, result: Dict) -> None:
        """Populate Trackers table and then load Peers for same selection.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if self._selected_torrent_hash() != torrent_hash:
            return

        if result.get('success'):
            rows = result.get('data', []) or []
            self._populate_details_table(
                self.tbl_trackers,
                rows,
                ["url", "status", "tier", "num_peers", "num_seeds", "num_leeches", "num_downloaded", "msg"]
            )
        else:
            error = result.get('error', 'Unknown error')
            self._set_details_table_message(self.tbl_trackers, f"Failed to load trackers: {error}")

        self.details_api_queue.add_task(
            "load_selected_peers",
            self._fetch_selected_torrent_peers,
            lambda r, h=torrent_hash: self._on_selected_peers_loaded(h, r),
            torrent_hash
        )

    def _on_selected_peers_loaded(self, torrent_hash: str, result: Dict) -> None:
        """Populate Peers table for currently selected torrent.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if self._selected_torrent_hash() != torrent_hash:
            return

        if result.get('success'):
            rows = result.get('data', []) or []
            self._populate_details_table(
                self.tbl_peers,
                rows,
                [
                    "peer_id", "ip", "port", "client", "connection",
                    "country", "country_code", "flags", "flags_desc",
                    "progress", "dl_speed", "up_speed",
                    "downloaded", "uploaded", "relevance", "files"
                ]
            )
        else:
            error = result.get('error', 'Unknown error')
            self._set_details_table_message(self.tbl_peers, f"Failed to load peers: {error}")

    def _set_details_panels_enabled(self, enabled: bool) -> None:
        """Enable/disable bottom details tabs.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self.detail_tabs.setEnabled(bool(enabled))
        self._sync_auto_refresh_timer_state()

    def _clear_details_panels(self, reason: str) -> None:
        """Clear all details panels with a reason message for trackers/peers.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self.txt_general_details.clear()
        self._set_details_table_message(self.tbl_trackers, reason)
        self._set_details_table_message(self.tbl_peers, reason)
        self._clear_torrent_edit_panel(reason)
        self.current_content_files = []
        self.current_content_filter = ""
        self.tree_files.clear()
        previous = self.txt_content_filter.blockSignals(True)
        self.txt_content_filter.clear()
        self.txt_content_filter.blockSignals(previous)

    def _on_torrent_selected(self) -> None:
        """Handle torrent selection in table.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        selected_hashes = self._get_selected_torrent_hashes()
        if not selected_hashes:
            self._selected_torrent = None
            self._set_details_panels_enabled(True)
            self._clear_details_panels("No torrent selected.")
            return

        if len(selected_hashes) > 1:
            self._selected_torrent = None
            self._clear_details_panels("Multiple torrents selected.")
            self._set_details_panels_enabled(False)
            self._set_status(f"{len(selected_hashes)} torrents selected")
            return

        self._set_details_panels_enabled(True)
        torrent_hash = selected_hashes[0]

        # Find torrent in filtered list
        torrent = None
        for t in self.filtered_torrents:
            if t.hash == torrent_hash:
                torrent = t
                break

        if torrent:
            self._display_torrent_details(torrent)

    def _display_torrent_details(self, torrent: Any) -> None:
        """Display detailed information about selected torrent.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        self._selected_torrent = torrent
        self._set_details_panels_enabled(True)
        try:
            tags_list = parse_tags(getattr(torrent, 'tags', None))
            tags_str = ', '.join(tags_list) if tags_list else 'None'

            completion_on = getattr(torrent, 'completion_on', 0)
            last_activity = getattr(torrent, 'last_activity', 0)
            private_value = getattr(torrent, 'private', None)
            private_str = 'Yes' if private_value else ('No' if private_value is False else 'N/A')
            num_files = getattr(torrent, 'num_files', 'N/A')
            content_path = self._display_detail_value(getattr(torrent, 'content_path', None))
            tracker_url = getattr(torrent, 'tracker', '') or ''
            tracker_host = self._tracker_display_text(tracker_url) or 'N/A'
            eta = self._safe_int(getattr(torrent, 'eta', 0), 0)
            eta_str = format_eta(eta) if eta > 0 else 'N/A'
            progress_pct = self._safe_float(getattr(torrent, 'progress', 0.0), 0.0) * 100.0
            ratio = self._safe_float(getattr(torrent, 'ratio', 0.0), 0.0)

            sections = [
                ("GENERAL", [
                    ("Name", getattr(torrent, 'name', None)),
                    ("Hash", getattr(torrent, 'hash', None)),
                    ("State", getattr(torrent, 'state', None)),
                    ("Size", format_size_mode(getattr(torrent, 'size', 0), self.display_size_mode)),
                    ("Total Size", format_size_mode(getattr(torrent, 'total_size', 0), self.display_size_mode)),
                    ("Progress", f"{progress_pct:.2f}%"),
                    ("Private", private_str),
                    ("Files", num_files),
                ]),
                ("TRANSFER", [
                    ("Downloaded", format_size_mode(getattr(torrent, 'downloaded', 0), self.display_size_mode)),
                    ("Uploaded", format_size_mode(getattr(torrent, 'uploaded', 0), self.display_size_mode)),
                    ("Download Speed", format_speed_mode(getattr(torrent, 'dlspeed', 0), self.display_speed_mode)),
                    ("Upload Speed", format_speed_mode(getattr(torrent, 'upspeed', 0), self.display_speed_mode)),
                    ("Ratio", f"{ratio:.3f}"),
                    ("ETA", eta_str),
                ]),
                ("PEERS", [
                    ("Seeds", f"{getattr(torrent, 'num_seeds', 0)} ({getattr(torrent, 'num_complete', 0)})"),
                    ("Peers", f"{getattr(torrent, 'num_leechs', 0)} ({getattr(torrent, 'num_incomplete', 0)})"),
                ]),
                ("METADATA", [
                    ("Tracker Host", tracker_host),
                    ("Tracker URL", tracker_url or 'N/A'),
                    ("Category", getattr(torrent, 'category', '') or 'None'),
                    ("Tags", tags_str),
                    ("Added On", format_datetime(getattr(torrent, 'added_on', 0))),
                    ("Completion On", format_datetime(completion_on) if completion_on > 0 else 'N/A'),
                    ("Last Activity", format_datetime(last_activity) if last_activity > 0 else 'N/A'),
                    ("Save Path", getattr(torrent, 'save_path', None)),
                    ("Content Path", content_path),
                ]),
            ]
            self.txt_general_details.setHtml(self._build_general_details_html(sections))
            self._load_selected_torrent_network_details(str(torrent.hash))
            self._populate_torrent_edit_panel(torrent)

            # Show file content from local cache
            self._show_cached_torrent_content(torrent.hash)
        except Exception as e:
            self._log("ERROR", f"Error displaying torrent details: {e}")
            self.txt_general_details.setPlainText(f"Error displaying details: {e}")
            self._set_details_table_message(self.tbl_trackers, "Failed to render trackers.")
            self._set_details_table_message(self.tbl_peers, "Failed to render peers.")
            self._clear_torrent_edit_panel("Failed to load torrent for editing.")

    def _copy_torrent_hash(self) -> None:
        """Copy selected torrent hash to clipboard.

        Side effects: None.
        Failure modes: None.
        """
        hashes = self._get_selected_torrent_hashes()
        if hashes:
            QApplication.clipboard().setText("\n".join(hashes))
            if len(hashes) == 1:
                self._set_status("Hash copied to clipboard")
            else:
                self._set_status(f"{len(hashes)} hashes copied to clipboard")

    def _browse_torrent_edit_save_path(self) -> None:
        """Browse for a new torrent save path.

        Side effects: None.
        Failure modes: None.
        """
        initial = self.txt_torrent_edit_save_path.text().strip()
        selected = QFileDialog.getExistingDirectory(self, "Select Save Path", initial)
        if selected:
            self.txt_torrent_edit_save_path.setText(selected)

    def _browse_torrent_edit_incomplete_path(self) -> None:
        """Browse for a new torrent incomplete save path.

        Side effects: None.
        Failure modes: None.
        """
        initial = self.txt_torrent_edit_incomplete_path.text().strip()
        selected = QFileDialog.getExistingDirectory(self, "Select Incomplete Save Path", initial)
        if selected:
            self.txt_torrent_edit_incomplete_path.setText(selected)

    def _collect_selected_torrent_edit_updates(self) -> Dict[str, Any]:
        """Collect changed edit fields for currently selected torrent.

        Side effects: None.
        Failure modes: None.
        """
        original = dict(self._torrent_edit_original or {})
        updates: Dict[str, Any] = {}

        new_name = str(self.txt_torrent_edit_name.text() or "").strip()
        if new_name != str(original.get("name", "") or "").strip():
            updates["name"] = new_name

        auto_state = self.chk_torrent_edit_auto_tmm.checkState()
        new_auto: Optional[bool]
        if auto_state == Qt.CheckState.PartiallyChecked:
            new_auto = None
        else:
            new_auto = auto_state == Qt.CheckState.Checked
        old_auto = original.get("auto_tmm")
        if new_auto is not None and new_auto != old_auto:
            updates["auto_tmm"] = new_auto

        new_category = str(self.cmb_torrent_edit_category.currentText() or "").strip()
        if new_category != str(original.get("category", "") or ""):
            updates["category"] = new_category

        new_tags = self._normalize_tags_csv(self.txt_torrent_edit_tags.text())
        if new_tags != str(original.get("tags", "") or ""):
            updates["tags"] = new_tags

        new_download_limit_kib = self._safe_int(self.spn_torrent_edit_download_limit.value(), 0)
        old_download_limit_kib = self._safe_int(original.get("download_limit_kib", 0), 0)
        if new_download_limit_kib != old_download_limit_kib:
            updates["download_limit_bytes"] = self._kib_to_bytes(new_download_limit_kib)

        new_upload_limit_kib = self._safe_int(self.spn_torrent_edit_upload_limit.value(), 0)
        old_upload_limit_kib = self._safe_int(original.get("upload_limit_kib", 0), 0)
        if new_upload_limit_kib != old_upload_limit_kib:
            updates["upload_limit_bytes"] = self._kib_to_bytes(new_upload_limit_kib)

        new_save_path = str(self.txt_torrent_edit_save_path.text() or "").strip()
        if new_save_path != str(original.get("save_path", "") or ""):
            updates["save_path"] = new_save_path

        new_download_path = str(self.txt_torrent_edit_incomplete_path.text() or "").strip()
        if new_download_path != str(original.get("download_path", "") or ""):
            updates["download_path"] = new_download_path

        return updates

    def _apply_selected_torrent_edits(self) -> None:
        """Apply torrent edits for exactly one selected torrent.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        selected_hashes = self._get_selected_torrent_hashes()
        if len(selected_hashes) != 1:
            self._set_status("Select exactly one torrent to apply edits")
            return

        torrent_hash = selected_hashes[0]
        selected = getattr(self, "_selected_torrent", None)
        selected_hash = str(getattr(selected, "hash", "") or "")
        if not selected_hash or selected_hash != torrent_hash:
            selected = self._find_torrent_by_hash(torrent_hash)
            if selected is None:
                self._set_status("Selected torrent is no longer available")
                return
            self._selected_torrent = selected

        current_name = str(self.txt_torrent_edit_name.text() or "").strip()
        original_name = str(self._torrent_edit_original.get("name", "") or "").strip()
        if current_name != original_name and not current_name:
            self._set_status("Torrent name cannot be empty")
            return

        updates = self._collect_selected_torrent_edit_updates()
        if not updates:
            self._set_status("No changes to apply")
            return

        self._log("INFO", f"Applying edits for {torrent_hash}: {list(updates.keys())}")
        self._show_progress("Applying torrent edits...")
        self.api_queue.add_task(
            "apply_selected_torrent_edits",
            self._api_apply_selected_torrent_edits,
            self._on_apply_selected_torrent_edits_done,
            torrent_hash,
            updates,
        )

class ActionsTaxonomyController(WindowControllerBase):
    @staticmethod
    def _build_new_instance_command(config_file_path: str, instance_counter: Optional[int] = None) -> List[str]:
        """Build command line used to spawn one new application instance.

        Side effects: None.
        Failure modes: None.
        """
        config_path = str(Path(str(config_file_path)).expanduser().resolve())
        command = [
            sys.executable,
            "-m",
            "qbiremo_enhanced",
            "--config-file",
            config_path,
        ]
        if instance_counter is not None:
            command.extend(
                ["--instance_counter", str(_normalize_instance_counter(instance_counter))]
            )
        return command

    def _launch_new_instance_with_config_path(
        self,
        config_file_path: str,
        instance_counter: Optional[int] = None,
    ) -> None:
        """Spawn one new process instance with the provided config path.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            command = self._build_new_instance_command(config_file_path, instance_counter)
            subprocess.Popen(command)
            self._log("INFO", f"Launched new instance: {' '.join(command)}")
            self._set_status(f"Launched new instance: {Path(config_file_path).name}")
        except Exception as e:
            self._log("ERROR", f"Failed to launch new instance: {e}")
            self._set_status(f"Failed to launch new instance: {e}")

    def _launch_new_instance_current_config(self) -> None:
        """Launch a new app instance using the currently loaded config file.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        raw_config_path = str(
            (self.config.get("_config_file_path") if isinstance(self.config, dict) else "")
            or ""
        ).strip()
        config_path = (
            raw_config_path
            if raw_config_path
            else str(Path("qbiremo_enhanced_config.toml").resolve())
        )
        counter = _normalize_instance_counter(
            self.config.get("_instance_counter", 1) if isinstance(self.config, dict) else 1
        )
        self._launch_new_instance_with_config_path(config_path, counter)

    def _launch_new_instance_from_config(self) -> None:
        """Launch a new app instance after selecting a .toml config file.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        current_config_path = str(
            (self.config.get("_config_file_path") if isinstance(self.config, dict) else "")
            or ""
        ).strip()
        if current_config_path:
            initial_dir = str(Path(current_config_path).expanduser().resolve().parent)
        else:
            initial_dir = str(Path.cwd())
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Config File",
            initial_dir,
            "TOML files (*.toml);;All files (*.*)",
        )
        if not selected_path:
            return
        self._launch_new_instance_with_config_path(selected_path, 1)

    def _show_add_torrent_dialog(self) -> None:
        """Show add torrent dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if self._add_torrent_dialog is not None and self._add_torrent_dialog.isVisible():
            self._add_torrent_dialog.raise_()
            self._add_torrent_dialog.activateWindow()
            return

        # Use a standalone top-level window so it appears in the taskbar.
        dialog = AddTorrentDialog(self.categories, self.tags, None)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setWindowFlag(Qt.WindowType.Window, True)
        dialog.setWindowFlag(Qt.WindowType.Tool, False)
        dialog.accepted.connect(self._on_add_torrent_dialog_accepted)
        dialog.finished.connect(self._on_add_torrent_dialog_closed)
        self._add_torrent_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_add_torrent_dialog_closed(self, _result: int) -> None:
        """Clear cached Add Torrent dialog reference.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._add_torrent_dialog = None

    def _on_add_torrent_dialog_accepted(self) -> None:
        """Queue torrent add task when Add Torrent dialog is accepted.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        dialog = self._add_torrent_dialog
        if dialog is None:
            return
        torrent_data = dict(getattr(dialog, "torrent_data", {}) or {})
        dialog.torrent_data = None
        if torrent_data:
            self._log("INFO", "Adding torrent...")
            self._show_progress("Adding torrent...")
            self.api_queue.add_task(
                "add_torrent",
                self._add_torrent_api,
                self._on_add_torrent_complete,
                torrent_data
            )

    @staticmethod
    def _sanitize_export_filename(name: Any, fallback: str = "torrent") -> str:
        """Sanitize one torrent name for safe local .torrent filenames.

        Side effects: None.
        Failure modes: None.
        """
        text = str(name or "").strip()
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
        text = text.strip().strip(".")
        text = re.sub(r"\s+", " ", text)
        return text or fallback

    @staticmethod
    def _unique_export_file_path(export_dir: Path, base_name: str, torrent_hash: str, used_names: set) -> Path:
        """Return a unique destination file path for one exported torrent file.

        Side effects: None.
        Failure modes: None.
        """
        sanitized_base = ActionsTaxonomyController._sanitize_export_filename(
            base_name,
            fallback=torrent_hash[:12] or "torrent",
        )
        candidate_name = f"{sanitized_base}.torrent"
        candidate_path = export_dir / candidate_name
        if candidate_name not in used_names and not candidate_path.exists():
            used_names.add(candidate_name)
            return candidate_path

        suffix = str(torrent_hash or "")[:8] or "dup"
        candidate_name = f"{sanitized_base}-{suffix}.torrent"
        candidate_path = export_dir / candidate_name
        counter = 2
        while candidate_name in used_names or candidate_path.exists():
            candidate_name = f"{sanitized_base}-{suffix}-{counter}.torrent"
            candidate_path = export_dir / candidate_name
            counter += 1
        used_names.add(candidate_name)
        return candidate_path

    def _build_selected_torrent_name_map(self, torrent_hashes: List[str]) -> Dict[str, str]:
        """Build hash->name mapping for selected torrents to name exported files.

        Side effects: None.
        Failure modes: None.
        """
        name_map: Dict[str, str] = {}
        for torrent_hash in list(torrent_hashes or []):
            torrent = self._find_torrent_by_hash(str(torrent_hash or ""))
            name_map[str(torrent_hash or "")] = str(getattr(torrent, "name", "") or "")
        return name_map

    def _export_selected_torrents(self) -> None:
        """Prompt destination directory and export selected torrents as .torrent files.

        Side effects: None.
        Failure modes: None.
        """
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            self._set_status("Select at least one torrent to export")
            return

        initial_dir = str(Path.home())
        export_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Export Directory",
            initial_dir,
        )
        if not export_dir:
            return

        name_map = self._build_selected_torrent_name_map(torrent_hashes)
        count = len(torrent_hashes)
        progress_text = (
            "Exporting torrent..."
            if count == 1
            else f"Exporting {count} torrents..."
        )
        self._show_progress(progress_text)
        self.api_queue.add_task(
            "export_selected_torrents",
            self._api_export_torrents,
            self._on_export_selected_torrents_done,
            torrent_hashes,
            export_dir,
            name_map,
        )

    def _on_export_selected_torrents_done(self, result: Dict) -> None:
        """Handle completion of selected-torrent export action.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        data = result.get("data", {}) or {}
        exported = list(data.get("exported", []) or [])
        failed = dict(data.get("failed", {}) or {})
        exported_count = len(exported)
        failed_count = len(failed)
        if result.get("success"):
            self._log("INFO", f"Export Torrent succeeded ({exported_count} file(s))", result.get("elapsed", 0))
            self._set_status(
                "Exported 1 torrent file"
                if exported_count == 1
                else f"Exported {exported_count} torrent files"
            )
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"Export Torrent failed: {error}", result.get("elapsed", 0))
            if exported_count > 0:
                self._set_status(
                    f"Exported {exported_count} torrent files, {failed_count} failed"
                )
            else:
                self._set_status(f"Export Torrent failed: {error}")
        self._hide_progress()

    def _find_torrent_by_hash(self, torrent_hash: str) -> Optional[Any]:
        """Find one torrent object by hash, preferring the currently filtered list.

        Side effects: None.
        Failure modes: None.
        """
        if not torrent_hash:
            return None

        for torrent in self.filtered_torrents:
            if str(getattr(torrent, "hash", "")) == torrent_hash:
                return torrent
        for torrent in self.all_torrents:
            if str(getattr(torrent, "hash", "")) == torrent_hash:
                return torrent
        return None

    @staticmethod
    def _expand_local_path(raw_path: Any) -> Optional[Path]:
        """Expand user/env vars for a local path string.

        Side effects: None.
        Failure modes: None.
        """
        text = str(raw_path or "").strip().strip('"').strip("'")
        if not text:
            return None
        expanded = os.path.expandvars(os.path.expanduser(text))
        if not expanded:
            return None
        return Path(expanded)

    def _resolve_local_torrent_directory(self, torrent) -> Optional[Path]:
        """Return an existing local directory for a torrent, if available.

        Side effects: None.
        Failure modes: None.
        """
        if torrent is None:
            return None

        content_path = self._expand_local_path(getattr(torrent, "content_path", ""))
        if content_path is not None:
            if content_path.is_dir():
                return content_path
            parent_dir = content_path.parent
            if parent_dir and parent_dir.is_dir():
                return parent_dir

        save_path = self._expand_local_path(getattr(torrent, "save_path", ""))
        if save_path is not None:
            if save_path.is_dir():
                return save_path

        return None

    def _open_selected_torrent_location(self) -> None:
        """Open selected torrent local directory when it exists on this machine.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        selected_hashes = self._get_selected_torrent_hashes()
        if len(selected_hashes) != 1:
            if selected_hashes:
                self._set_status("Select one torrent to open its local directory")
            return

        self._open_torrent_location_by_hash(selected_hashes[0])

    def _open_torrent_location_by_hash(self, torrent_hash: str) -> None:
        """Open local torrent directory for one hash when available.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if not torrent_hash:
            self._set_status("Selected torrent was not found")
            return

        torrent = self._find_torrent_by_hash(torrent_hash)
        if torrent is None:
            self._set_status("Selected torrent was not found")
            return

        local_dir = self._resolve_local_torrent_directory(torrent)
        if local_dir is None:
            self._set_status("No local directory found for selected torrent")
            return

        self._open_file_in_default_app(str(local_dir))
        self._set_status(f"Opened local directory: {local_dir}")

    def _on_torrent_table_item_double_clicked(self, item: QTableWidgetItem) -> None:
        """Open local torrent directory for the row that was double-clicked.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if item is None:
            return
        hash_item = self.tbl_torrents.item(item.row(), 0)
        torrent_hash = hash_item.text().strip() if hash_item else ""
        self._open_torrent_location_by_hash(torrent_hash)

    def _on_content_tree_item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        """Open activated content-tree item (Enter/double-click behavior).

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._open_selected_content_path(item=item)

    def _open_selected_content_path(self, item: Optional[QTreeWidgetItem] = None) -> None:
        """Open selected content-tree item in the local filesystem when available.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if item is None:
            item = self.tree_files.currentItem()
        if item is None:
            selected = self.tree_files.selectedItems()
            if selected:
                item = selected[0]
        if item is None:
            return

        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(item_data, dict):
            return

        relative_path = str(item_data.get("relative_path", "") or "").strip()
        is_file = bool(item_data.get("is_file", False))
        if not relative_path:
            return

        torrent = getattr(self, "_selected_torrent", None)
        if torrent is None:
            self._set_status("No torrent selected")
            return

        base_dir = self._resolve_local_torrent_directory(torrent)
        if base_dir is None:
            self._set_status("No local directory found for selected torrent")
            return

        normalized_rel = relative_path.replace("\\", "/").lstrip("/")
        rel_path = Path(*[part for part in normalized_rel.split("/") if part not in ("", ".", "..")])
        candidate = base_dir / rel_path
        if not candidate.exists():
            torrent_content_path = self._expand_local_path(getattr(torrent, "content_path", ""))
            lower_rel = normalized_rel.casefold()
            content_name = (
                str(torrent_content_path.name).casefold()
                if torrent_content_path is not None and torrent_content_path.name
                else ""
            )
            if (
                torrent_content_path is not None
                and torrent_content_path.is_dir()
                and content_name
                and lower_rel.startswith(f"{content_name}/")
            ):
                candidate = torrent_content_path.parent / rel_path
            elif (
                is_file
                and torrent_content_path is not None
                and torrent_content_path.is_file()
                and (not rel_path.parts or rel_path.name.casefold() == content_name)
            ):
                candidate = torrent_content_path

        if is_file:
            if not candidate.is_file():
                self._set_status("Selected file does not exist locally")
                return
        else:
            if not candidate.is_dir():
                self._set_status("Selected directory does not exist locally")
                return

        self._open_file_in_default_app(str(candidate))
        target_type = "file" if is_file else "directory"
        self._set_status(f"Opened local {target_type}: {candidate}")

    def _get_selected_torrent_hash(self) -> Optional[str]:
        """Get the hash of the currently selected torrent, or None.

        Side effects: None.
        Failure modes: None.
        """
        hashes = self._get_selected_torrent_hashes()
        if not hashes:
            return None
        return hashes[0]

    def _get_selected_torrent_hashes(self) -> List[str]:
        """Get unique selected torrent hashes preserving current row order.

        Side effects: None.
        Failure modes: None.
        """
        hashes: List[str] = []
        seen = set()

        sel_model = self.tbl_torrents.selectionModel()
        if sel_model:
            for idx in sel_model.selectedRows(0):
                item = self.tbl_torrents.item(idx.row(), 0)
                torrent_hash = item.text() if item else ""
                if torrent_hash and torrent_hash not in seen:
                    seen.add(torrent_hash)
                    hashes.append(torrent_hash)
        return hashes

    def _on_torrent_action_done(self, action_name: str, result: Dict) -> None:
        """Generic callback for pause/resume/delete actions.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get('success'):
            self._log("INFO", f"{action_name} succeeded", result.get('elapsed', 0))
            QTimer.singleShot(500, self._refresh_torrents)
        else:
            error = result.get('error', 'Unknown error')
            self._log("ERROR", f"{action_name} failed: {error}", result.get('elapsed', 0))
            self._set_status(f"{action_name} failed: {error}")
        self._hide_progress()

    def _on_ban_peer_done(self, endpoint: str, result: Dict) -> None:
        """Callback for peer ban action.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get("success"):
            self._log("INFO", f"Ban Peer succeeded: {endpoint}", result.get("elapsed", 0))
            self._set_status(f"Banned peer: {endpoint}")
            torrent_hash = self._selected_torrent_hash().strip()
            if torrent_hash:
                QTimer.singleShot(
                    300,
                    lambda h=torrent_hash: self._load_selected_torrent_network_details(h),
                )
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"Ban Peer failed: {error}", result.get("elapsed", 0))
            self._set_status(f"Ban Peer failed: {error}")
        self._hide_progress()

    def _queue_bulk_torrent_action(
        self,
        task_name: str,
        api_method: Callable[..., APITaskResult],
        action_name: str,
        singular_progress: str,
        plural_progress: str,
    ) -> None:
        """Queue a bulk action for currently selected torrents.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        count = len(torrent_hashes)
        self._log("INFO", f"{action_name}: {count} torrent(s)")
        self._show_progress(singular_progress if count == 1 else plural_progress.format(count=count))
        self.api_queue.add_task(
            task_name,
            api_method,
            lambda r: self._on_torrent_action_done(action_name, r),
            torrent_hashes
        )

    def _pause_torrent(self) -> None:
        """Pause selected torrent(s).

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._queue_bulk_torrent_action(
            "pause_torrent",
            self._api_pause_torrent,
            "Pause",
            "Pausing torrent...",
            "Pausing {count} torrents...",
        )

    def _resume_torrent(self) -> None:
        """Resume selected torrent(s).

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._queue_bulk_torrent_action(
            "resume_torrent",
            self._api_resume_torrent,
            "Resume",
            "Resuming torrent...",
            "Resuming {count} torrents...",
        )

    def _force_start_torrent(self) -> None:
        """Force-start selected torrent(s).

        Side effects: None.
        Failure modes: None.
        """
        self._queue_bulk_torrent_action(
            "force_start_torrent",
            self._api_force_start_torrent,
            "Force Start",
            "Force-starting torrent...",
            "Force-starting {count} torrents...",
        )

    def _recheck_torrent(self) -> None:
        """Recheck selected torrent(s).

        Side effects: None.
        Failure modes: None.
        """
        self._queue_bulk_torrent_action(
            "recheck_torrent",
            self._api_recheck_torrent,
            "Recheck",
            "Rechecking torrent...",
            "Rechecking {count} torrents...",
        )

    def _increase_torrent_priority(self) -> None:
        """Increase queue priority for selected torrent(s).

        Side effects: None.
        Failure modes: None.
        """
        self._queue_bulk_torrent_action(
            "increase_torrent_priority",
            self._api_increase_torrent_priority,
            "Increase Priority",
            "Increasing queue priority...",
            "Increasing queue priority for {count} torrents...",
        )

    def _decrease_torrent_priority(self) -> None:
        """Decrease queue priority for selected torrent(s).

        Side effects: None.
        Failure modes: None.
        """
        self._queue_bulk_torrent_action(
            "decrease_torrent_priority",
            self._api_decrease_torrent_priority,
            "Decrease Priority",
            "Decreasing queue priority...",
            "Decreasing queue priority for {count} torrents...",
        )

    def _top_torrent_priority(self) -> None:
        """Set top queue priority for selected torrent(s).

        Side effects: None.
        Failure modes: None.
        """
        self._queue_bulk_torrent_action(
            "top_torrent_priority",
            self._api_top_torrent_priority,
            "Top Priority",
            "Setting top queue priority...",
            "Setting top queue priority for {count} torrents...",
        )

    def _minimum_torrent_priority(self) -> None:
        """Set minimum queue priority for selected torrent(s).

        Side effects: None.
        Failure modes: None.
        """
        self._queue_bulk_torrent_action(
            "minimum_torrent_priority",
            self._api_minimum_torrent_priority,
            "Minimum Priority",
            "Setting minimum queue priority...",
            "Setting minimum queue priority for {count} torrents...",
        )

    @staticmethod
    def _kib_to_bytes(limit_kib: int) -> int:
        """Convert KiB/s to bytes/s for API calls.

        Side effects: None.
        Failure modes: None.
        """
        return max(0, int(limit_kib)) * 1024

    @staticmethod
    def _bytes_to_kib(limit_bytes: Any) -> int:
        """Convert bytes/s to KiB/s for UI controls.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            return max(0, int(limit_bytes)) // 1024
        except Exception:
            return 0

    def _prompt_limit_kib(self, title: str, label: str) -> Optional[int]:
        """Prompt for a speed limit in KiB/s (0 means unlimited).

        Side effects: None.
        Failure modes: None.
        """
        value, ok = QInputDialog.getInt(
            self,
            title,
            label,
            value=0,
            minValue=0,
            maxValue=10_000_000,
            step=1,
        )
        if not ok:
            return None
        return int(value)

    def _set_torrent_download_limit(self) -> None:
        """Prompt and set download limit for selected torrents.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        limit_kib = self._prompt_limit_kib(
            "Set Torrent Download Limit",
            "Download limit (KiB/s, 0 = unlimited):",
        )
        if limit_kib is None:
            return

        limit_bytes = self._kib_to_bytes(limit_kib)
        count = len(torrent_hashes)
        self._show_progress("Setting torrent download limit...")
        self.api_queue.add_task(
            "set_torrent_download_limit",
            self._api_set_torrent_download_limit,
            lambda r: self._on_torrent_action_done("Set Torrent Download Limit", r),
            torrent_hashes,
            limit_bytes,
        )
        self._log(
            "INFO",
            f"Setting download limit for {count} torrent(s) to {limit_kib} KiB/s"
        )

    def _set_torrent_upload_limit(self) -> None:
        """Prompt and set upload limit for selected torrents.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        limit_kib = self._prompt_limit_kib(
            "Set Torrent Upload Limit",
            "Upload limit (KiB/s, 0 = unlimited):",
        )
        if limit_kib is None:
            return

        limit_bytes = self._kib_to_bytes(limit_kib)
        count = len(torrent_hashes)
        self._show_progress("Setting torrent upload limit...")
        self.api_queue.add_task(
            "set_torrent_upload_limit",
            self._api_set_torrent_upload_limit,
            lambda r: self._on_torrent_action_done("Set Torrent Upload Limit", r),
            torrent_hashes,
            limit_bytes,
        )
        self._log(
            "INFO",
            f"Setting upload limit for {count} torrent(s) to {limit_kib} KiB/s"
        )

    def _on_global_bandwidth_action_done(self, action_name: str, result: Dict) -> None:
        """Handle global bandwidth action completion.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get("success"):
            self._log("INFO", f"{action_name} succeeded", result.get("elapsed", 0))
            self._set_status(f"{action_name} applied")
            QTimer.singleShot(500, self._refresh_torrents)
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"{action_name} failed: {error}", result.get("elapsed", 0))
            self._set_status(f"{action_name} failed: {error}")
        self._hide_progress()

    def _show_app_preferences_editor(self) -> None:
        """Open application preferences editor dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if self._app_preferences_dialog is not None and self._app_preferences_dialog.isVisible():
            self._app_preferences_dialog.raise_()
            self._app_preferences_dialog.activateWindow()
            self._request_app_preferences_refresh()
            return

        dialog = AppPreferencesDialog(self)
        dialog.apply_requested.connect(self._on_app_preferences_apply_requested)
        dialog.finished.connect(self._on_app_preferences_dialog_closed)
        self._app_preferences_dialog = dialog
        dialog.show()
        self._request_app_preferences_refresh()

    def _on_app_preferences_dialog_closed(self, _result: int) -> None:
        """Clear cached app-preferences dialog reference.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._app_preferences_dialog = None

    def _set_app_preferences_dialog_busy(self, busy: bool, message: str = "") -> None:
        """Set app-preferences dialog busy state when open.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        dialog = self._app_preferences_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _request_app_preferences_refresh(self) -> None:
        """Load raw app preferences into editor dialog.

        Side effects: None.
        Failure modes: None.
        """
        self._show_progress("Loading app preferences...")
        self._set_app_preferences_dialog_busy(True, "Loading application preferences...")
        self.api_queue.add_task(
            "fetch_app_preferences",
            self._api_fetch_app_preferences,
            self._on_app_preferences_loaded,
        )

    def _on_app_preferences_loaded(self, result: Dict) -> None:
        """Populate app-preferences dialog from API response.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        dialog = self._app_preferences_dialog
        if result.get("success"):
            data = result.get("data", {}) or {}
            if dialog is not None and dialog.isVisible():
                dialog.set_preferences(data if isinstance(data, dict) else {})
                dialog.set_busy(False, "Loaded")
            self._set_status("App preferences loaded")
        else:
            error = result.get("error", "Unknown error")
            if dialog is not None and dialog.isVisible():
                dialog.set_busy(False, f"Failed: {error}")
            self._set_status(f"Failed to load app preferences: {error}")
        self._hide_progress()

    def _on_app_preferences_apply_requested(self, changed_preferences: Dict[str, Any]) -> None:
        """Queue changed app preferences from editor dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        updates = dict(changed_preferences or {})
        if not updates:
            self._set_status("No app preference changes to apply")
            self._set_app_preferences_dialog_busy(False, "No changed preferences to apply.")
            return
        self._show_progress("Applying app preferences...")
        self._set_app_preferences_dialog_busy(True, "Applying application preferences...")
        self.api_queue.add_task(
            "apply_app_preferences",
            self._api_apply_app_preferences,
            self._on_app_preferences_applied,
            updates,
        )

    def _on_app_preferences_applied(self, result: Dict) -> None:
        """Handle completion of app preferences apply.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get("success"):
            self._set_status("App preferences applied")
            self._set_app_preferences_dialog_busy(False, "Applied")
            self._request_app_preferences_refresh()
            return
        error = result.get("error", "Unknown error")
        self._set_status(f"Failed to apply app preferences: {error}")
        self._set_app_preferences_dialog_busy(False, f"Failed: {error}")
        self._hide_progress()

    def _show_friendly_add_preferences_editor(self) -> None:
        """Open friendly editor for commonly used app preferences.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if (
            self._friendly_add_preferences_dialog is not None
            and self._friendly_add_preferences_dialog.isVisible()
        ):
            self._friendly_add_preferences_dialog.raise_()
            self._friendly_add_preferences_dialog.activateWindow()
            self._request_friendly_add_preferences_refresh()
            return

        dialog = FriendlyAddPreferencesDialog(self)
        dialog.apply_requested.connect(self._on_friendly_add_preferences_apply_requested)
        dialog.finished.connect(self._on_friendly_add_preferences_dialog_closed)
        self._friendly_add_preferences_dialog = dialog
        dialog.show()
        self._request_friendly_add_preferences_refresh()

    def _on_friendly_add_preferences_dialog_closed(self, _result: int) -> None:
        """Clear cached friendly add-preferences dialog reference.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._friendly_add_preferences_dialog = None

    def _set_friendly_add_preferences_dialog_busy(self, busy: bool, message: str = "") -> None:
        """Set busy state for friendly add-preferences dialog when open.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        dialog = self._friendly_add_preferences_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _request_friendly_add_preferences_refresh(self) -> None:
        """Load app preferences into friendly add-preferences editor.

        Side effects: None.
        Failure modes: None.
        """
        self._show_progress("Loading add preferences...")
        self._set_friendly_add_preferences_dialog_busy(True, "Loading add preferences...")
        self.api_queue.add_task(
            "fetch_friendly_add_preferences",
            self._api_fetch_app_preferences,
            self._on_friendly_add_preferences_loaded,
        )

    def _on_friendly_add_preferences_loaded(self, result: Dict) -> None:
        """Populate friendly add-preferences dialog from API response.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        dialog = self._friendly_add_preferences_dialog
        if result.get("success"):
            data = result.get("data", {}) or {}
            if dialog is not None and dialog.isVisible():
                dialog.set_preferences(data if isinstance(data, dict) else {})
                dialog.set_busy(False, "Loaded")
            self._set_status("Add preferences loaded")
        else:
            error = result.get("error", "Unknown error")
            if dialog is not None and dialog.isVisible():
                dialog.set_busy(False, f"Failed: {error}")
            self._set_status(f"Failed to load add preferences: {error}")
        self._hide_progress()

    def _on_friendly_add_preferences_apply_requested(self, changed_preferences: Dict[str, Any]) -> None:
        """Queue changed friendly add-preferences values for API apply.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        updates = dict(changed_preferences or {})
        if not updates:
            self._set_status("No add preference changes to apply")
            self._set_friendly_add_preferences_dialog_busy(False, "No changed preferences to apply.")
            return
        self._show_progress("Applying add preferences...")
        self._set_friendly_add_preferences_dialog_busy(True, "Applying add preferences...")
        self.api_queue.add_task(
            "apply_friendly_add_preferences",
            self._api_apply_app_preferences,
            self._on_friendly_add_preferences_applied,
            updates,
        )

    def _on_friendly_add_preferences_applied(self, result: Dict) -> None:
        """Handle completion of friendly add-preferences apply.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get("success"):
            self._set_status("Add preferences applied")
            self._set_friendly_add_preferences_dialog_busy(False, "Applied")
            self._request_friendly_add_preferences_refresh()
            return
        error = result.get("error", "Unknown error")
        self._set_status(f"Failed to apply add preferences: {error}")
        self._set_friendly_add_preferences_dialog_busy(False, f"Failed: {error}")
        self._hide_progress()

    def _show_speed_limits_manager(self) -> None:
        """Open speed limits manager dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if self._speed_limits_dialog is not None and self._speed_limits_dialog.isVisible():
            self._speed_limits_dialog.raise_()
            self._speed_limits_dialog.activateWindow()
            self._request_speed_limits_profile()
            return

        dialog = SpeedLimitsDialog(self)
        dialog.refresh_requested.connect(self._request_speed_limits_profile)
        dialog.apply_requested.connect(self._on_speed_limits_apply_requested)
        dialog.finished.connect(self._on_speed_limits_dialog_closed)
        self._speed_limits_dialog = dialog
        dialog.show()
        self._request_speed_limits_profile()

    def _on_speed_limits_dialog_closed(self, _result: int) -> None:
        """Clear cached speed limits dialog reference.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._speed_limits_dialog = None

    def _set_speed_limits_dialog_busy(self, busy: bool, message: str = "") -> None:
        """Set speed dialog controls busy state when dialog is open.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        dialog = self._speed_limits_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _request_speed_limits_profile(self) -> None:
        """Load current speed limits into manager dialog.

        Side effects: None.
        Failure modes: None.
        """
        self._show_progress("Loading speed limits...")
        self._set_speed_limits_dialog_busy(True, "Loading speed limits...")
        self.api_queue.add_task(
            "fetch_speed_limits_profile",
            self._api_fetch_speed_limits_profile,
            self._on_speed_limits_profile_loaded,
        )

    def _on_speed_limits_profile_loaded(self, result: Dict) -> None:
        """Populate speed limits dialog from API response.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get("success"):
            data = result.get("data", {}) or {}
            self._last_alt_speed_mode = bool(data.get("alt_enabled", self._last_alt_speed_mode))
            if self._last_alt_speed_mode:
                self._last_global_download_limit = max(
                    0, self._safe_int(data.get("alt_dl", self._last_global_download_limit), 0)
                )
                self._last_global_upload_limit = max(
                    0, self._safe_int(data.get("alt_ul", self._last_global_upload_limit), 0)
                )
            else:
                self._last_global_download_limit = max(
                    0, self._safe_int(data.get("normal_dl", self._last_global_download_limit), 0)
                )
                self._last_global_upload_limit = max(
                    0, self._safe_int(data.get("normal_ul", self._last_global_upload_limit), 0)
                )
            self._record_session_timeline_sample(self._last_alt_speed_mode)
            dialog = self._speed_limits_dialog
            if dialog is not None and dialog.isVisible():
                dialog.set_values(
                    self._safe_int(data.get("normal_dl", 0), 0),
                    self._safe_int(data.get("normal_ul", 0), 0),
                    self._safe_int(data.get("alt_dl", 0), 0),
                    self._safe_int(data.get("alt_ul", 0), 0),
                    bool(data.get("alt_enabled", False)),
                )
            self._set_status("Speed limits loaded")
            self._set_speed_limits_dialog_busy(False, "Loaded")
            self._update_statusbar_transfer_summary()
        else:
            error = result.get("error", "Unknown error")
            self._set_status(f"Failed to load speed limits: {error}")
            self._set_speed_limits_dialog_busy(False, f"Failed: {error}")
        self._hide_progress()

    def _on_speed_limits_apply_requested(
        self,
        normal_dl_kib: int,
        normal_ul_kib: int,
        alt_dl_kib: int,
        alt_ul_kib: int,
        alt_enabled: bool,
    ) -> None:
        """Queue apply operation from speed limits dialog values.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._show_progress("Applying speed limits...")
        self._set_speed_limits_dialog_busy(True, "Applying speed limits...")
        self.api_queue.add_task(
            "apply_speed_limits_profile",
            self._api_apply_speed_limits_profile,
            self._on_speed_limits_profile_applied,
            self._kib_to_bytes(normal_dl_kib),
            self._kib_to_bytes(normal_ul_kib),
            self._kib_to_bytes(alt_dl_kib),
            self._kib_to_bytes(alt_ul_kib),
            bool(alt_enabled),
        )

    def _on_speed_limits_profile_applied(self, result: Dict) -> None:
        """Handle completion of speed limits apply.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get("success"):
            self._set_status("Speed limits applied")
            self._set_speed_limits_dialog_busy(False, "Applied")
            self._request_speed_limits_profile()
            return
        error = result.get("error", "Unknown error")
        self._set_status(f"Failed to apply speed limits: {error}")
        self._set_speed_limits_dialog_busy(False, f"Failed: {error}")
        self._hide_progress()

    def _set_global_download_limit(self) -> None:
        """Prompt and set global download limit.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        limit_kib = self._prompt_limit_kib(
            "Set Global Download Limit",
            "Global download limit (KiB/s, 0 = unlimited):",
        )
        if limit_kib is None:
            return
        limit_bytes = self._kib_to_bytes(limit_kib)
        self._show_progress("Setting global download limit...")
        self.api_queue.add_task(
            "set_global_download_limit",
            self._api_set_global_download_limit,
            lambda r: self._on_global_bandwidth_action_done("Set Global Download Limit", r),
            limit_bytes,
        )

    def _set_global_upload_limit(self) -> None:
        """Prompt and set global upload limit.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        limit_kib = self._prompt_limit_kib(
            "Set Global Upload Limit",
            "Global upload limit (KiB/s, 0 = unlimited):",
        )
        if limit_kib is None:
            return
        limit_bytes = self._kib_to_bytes(limit_kib)
        self._show_progress("Setting global upload limit...")
        self.api_queue.add_task(
            "set_global_upload_limit",
            self._api_set_global_upload_limit,
            lambda r: self._on_global_bandwidth_action_done("Set Global Upload Limit", r),
            limit_bytes,
        )

    def _toggle_alt_speed_mode(self) -> None:
        """Toggle alternative speed mode.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._show_progress("Toggling alternative speed mode...")
        self.api_queue.add_task(
            "toggle_alt_speed_mode",
            self._api_toggle_alt_speed_mode,
            lambda r: self._on_global_bandwidth_action_done("Toggle Alternative Speed Mode", r),
        )

    def _get_selected_content_item_info(self) -> Optional[Dict[str, Any]]:
        """Return selected content tree item metadata.

        Side effects: None.
        Failure modes: None.
        """
        item = self.tree_files.currentItem()
        if item is None:
            selected = self.tree_files.selectedItems()
            if selected:
                item = selected[0]
        if item is None:
            self._set_status("No content item selected")
            return None

        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(item_data, dict):
            self._set_status("No content item selected")
            return None

        relative_path = str(item_data.get("relative_path", "") or "").replace("\\", "/").strip("/")
        if not relative_path:
            self._set_status("No content item selected")
            return None

        return {
            "item": item,
            "relative_path": relative_path,
            "is_file": bool(item_data.get("is_file", False)),
        }

    def _selected_torrent_hash_for_content_action(self) -> Optional[str]:
        """Return currently selected torrent hash for content actions.

        Side effects: None.
        Failure modes: None.
        """
        torrent = getattr(self, "_selected_torrent", None)
        torrent_hash = str(getattr(torrent, "hash", "") or "").strip() if torrent else ""
        if not torrent_hash:
            self._set_status("Select exactly one torrent first")
            return None
        return torrent_hash

    def _on_content_action_done(self, action_name: str, result: Dict) -> None:
        """Callback for content actions (priority/rename).

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get("success"):
            self._log("INFO", f"{action_name} succeeded", result.get("elapsed", 0))
            QTimer.singleShot(500, self._refresh_torrents)
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"{action_name} failed: {error}", result.get("elapsed", 0))
            self._set_status(f"{action_name} failed: {error}")
        self._hide_progress()

    def _set_selected_content_priority(self, priority: int) -> None:
        """Set priority for selected content item (file/folder).

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        torrent_hash = self._selected_torrent_hash_for_content_action()
        if not torrent_hash:
            return
        info = self._get_selected_content_item_info()
        if not info:
            return

        priority_name = {0: "Skip", 1: "Normal", 6: "High", 7: "Maximum"}.get(priority, str(priority))
        self._show_progress(f"Setting content priority: {priority_name}...")
        self.api_queue.add_task(
            "set_content_priority",
            self._api_set_content_priority,
            lambda r: self._on_content_action_done("Set Content Priority", r),
            torrent_hash,
            info["relative_path"],
            info["is_file"],
            int(priority),
        )

    def _rename_selected_content_item(self) -> None:
        """Rename selected file/folder in content tree via API.

        Side effects: None.
        Failure modes: None.
        """
        torrent_hash = self._selected_torrent_hash_for_content_action()
        if not torrent_hash:
            return
        info = self._get_selected_content_item_info()
        if not info:
            return

        old_rel = str(info["relative_path"])
        old_name = old_rel.rsplit("/", 1)[-1]
        label = "file" if info["is_file"] else "folder"
        new_name, ok = self._prompt_content_rename_name(label, old_name)
        if not ok:
            return

        new_name = str(new_name or "").strip()
        if not new_name:
            self._set_status("New name cannot be empty")
            return
        if "/" in new_name or "\\" in new_name:
            self._set_status("New name cannot contain path separators")
            return
        if new_name == old_name:
            return

        parent = old_rel.rsplit("/", 1)[0] if "/" in old_rel else ""
        new_rel = f"{parent}/{new_name}" if parent else new_name

        self._show_progress(f"Renaming {label}...")
        self.api_queue.add_task(
            "rename_content_path",
            self._api_rename_content_path,
            lambda r: self._on_content_action_done("Rename Content", r),
            torrent_hash,
            old_rel,
            new_rel,
            bool(info["is_file"]),
        )

    def _prompt_content_rename_name(self, label: str, old_name: str) -> Tuple[str, bool]:
        """Prompt for a new content file/folder name with persistent dialog size.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Rename {str(label or '').title()}")
        dialog.setMinimumWidth(600)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"New {label} name:"))
        txt_name = QLineEdit(dialog)
        txt_name.setText(str(old_name or ""))
        txt_name.selectAll()
        layout.addWidget(txt_name)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        settings = self._new_settings()
        geometry = settings.value("contentRenameDialogGeometry")
        restored = False
        if geometry:
            try:
                restored = bool(dialog.restoreGeometry(geometry))
            except Exception:
                restored = False
        if not restored:
            default_height = max(140, dialog.sizeHint().height())
            dialog.resize(600, default_height)
        if dialog.width() < 600:
            dialog.resize(600, dialog.height())

        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        try:
            settings.setValue("contentRenameDialogGeometry", dialog.saveGeometry())
            settings.sync()
        except Exception:
            pass

        if not accepted:
            return "", False
        return str(txt_name.text() or ""), True

    def _on_taxonomy_action_done(self, action_name: str, result: Dict) -> None:
        """Callback for create/edit/delete category/tag actions.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get("success"):
            self._log("INFO", f"{action_name} succeeded", result.get("elapsed", 0))
            self._reload_taxonomy_data(action_name)
            return
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"{action_name} failed: {error}", result.get("elapsed", 0))
            self._set_status(f"{action_name} failed: {error}")
            self._set_taxonomy_dialog_busy(False, f"{action_name} failed: {error}")
        self._hide_progress()

    def _set_taxonomy_dialog_busy(self, busy: bool, message: str = "") -> None:
        """Set taxonomy dialog busy state when open.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        dialog = self._taxonomy_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _reload_taxonomy_data(self, action_name: str) -> None:
        """Reload categories+tags after taxonomy mutation.

        Side effects: None.
        Failure modes: None.
        """
        self.api_queue.add_task(
            "reload_categories_for_taxonomy",
            self._fetch_categories,
            lambda r: self._on_taxonomy_categories_reloaded(action_name, r),
        )

    def _on_taxonomy_categories_reloaded(self, action_name: str, result: Dict) -> None:
        """Handle category reload in taxonomy post-action chain.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get("success"):
            self._set_categories_from_payload(result.get("data", {}))
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"Reload categories failed after {action_name}: {error}")

        self.api_queue.add_task(
            "reload_tags_for_taxonomy",
            self._fetch_tags,
            lambda r: self._on_taxonomy_tags_reloaded(action_name, r),
        )

    def _on_taxonomy_tags_reloaded(self, action_name: str, result: Dict) -> None:
        """Finalize taxonomy reload and update UI/dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if result.get("success"):
            self.tags = result.get("data", [])
            self._update_tag_tree()
            self._sync_taxonomy_dialog_data()
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"Reload tags failed after {action_name}: {error}")

        self._set_taxonomy_dialog_busy(False, f"{action_name} succeeded")
        self._hide_progress()
        self._set_status(f"{action_name} succeeded")

    def _queue_taxonomy_action(
        self,
        task_name: str,
        api_method: Callable[..., APITaskResult],
        action_name: str,
        *args: Any,
    ) -> None:
        """Queue taxonomy mutation from manager dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._show_progress(f"{action_name}...")
        self._set_taxonomy_dialog_busy(True, f"{action_name}...")
        self.api_queue.add_task(
            task_name,
            api_method,
            lambda r: self._on_taxonomy_action_done(action_name, r),
            *args,
        )

    def _show_taxonomy_manager(self) -> None:
        """Open taxonomy manager dialog (categories + tags).

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if self._taxonomy_dialog is not None and self._taxonomy_dialog.isVisible():
            self._sync_taxonomy_dialog_data()
            self._taxonomy_dialog.raise_()
            self._taxonomy_dialog.activateWindow()
            return

        dialog = TaxonomyManagerDialog(self)
        dialog.set_taxonomy_data(self._taxonomy_category_data(), list(self.tags))
        dialog.create_category_requested.connect(self._on_taxonomy_create_category_requested)
        dialog.edit_category_requested.connect(self._on_taxonomy_edit_category_requested)
        dialog.delete_category_requested.connect(self._on_taxonomy_delete_category_requested)
        dialog.create_tags_requested.connect(self._on_taxonomy_create_tags_requested)
        dialog.delete_tags_requested.connect(self._on_taxonomy_delete_tags_requested)
        dialog.finished.connect(self._on_taxonomy_dialog_closed)
        self._taxonomy_dialog = dialog
        dialog.show()

    def _on_taxonomy_dialog_closed(self, _result: int) -> None:
        """Clear dialog reference when closed.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._taxonomy_dialog = None

    def _on_taxonomy_create_category_requested(
        self,
        name: str,
        save_path: str,
        incomplete_path: str,
        use_incomplete_path: bool,
    ) -> None:
        """Handle create-category request from manager dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        normalized_name = str(name or "").strip()
        normalized_save = str(save_path or "").strip()
        normalized_incomplete = str(incomplete_path or "").strip()
        use_incomplete = bool(use_incomplete_path)
        if not normalized_name:
            self._set_taxonomy_dialog_busy(False, "Category name cannot be empty.")
            return
        if use_incomplete and not normalized_incomplete:
            self._set_taxonomy_dialog_busy(False, "Incomplete path is enabled but empty.")
            return
        self._queue_taxonomy_action(
            "create_category",
            self._api_create_category,
            "Create Category",
            normalized_name,
            normalized_save,
            normalized_incomplete,
            use_incomplete,
        )

    def _on_taxonomy_edit_category_requested(
        self,
        name: str,
        save_path: str,
        incomplete_path: str,
        use_incomplete_path: bool,
    ) -> None:
        """Handle edit-category request from manager dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        normalized_name = str(name or "").strip()
        normalized_save = str(save_path or "").strip()
        normalized_incomplete = str(incomplete_path or "").strip()
        use_incomplete = bool(use_incomplete_path)
        if not normalized_name:
            self._set_taxonomy_dialog_busy(False, "Select a category to update.")
            return
        if use_incomplete and not normalized_incomplete:
            self._set_taxonomy_dialog_busy(False, "Incomplete path is enabled but empty.")
            return
        self._queue_taxonomy_action(
            "edit_category",
            self._api_edit_category,
            "Edit Category",
            normalized_name,
            normalized_save,
            normalized_incomplete,
            use_incomplete,
        )

    def _on_taxonomy_delete_category_requested(self, name: str) -> None:
        """Handle delete-category request from manager dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        normalized_name = str(name or "").strip()
        if not normalized_name:
            self._set_taxonomy_dialog_busy(False, "Select a category to delete.")
            return

        confirm = QMessageBox.question(
            self,
            "Delete Category",
            f"Delete category '{normalized_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._queue_taxonomy_action(
            "delete_category",
            self._api_delete_category,
            "Delete Category",
            normalized_name,
        )

    def _on_taxonomy_create_tags_requested(self, tags: List[str]) -> None:
        """Handle create-tags request from manager dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        normalized = [str(tag).strip() for tag in list(tags or []) if str(tag).strip()]
        if not normalized:
            self._set_taxonomy_dialog_busy(False, "Enter at least one tag.")
            return
        self._queue_taxonomy_action(
            "create_tags",
            self._api_create_tags,
            "Create Tag",
            normalized,
        )

    def _on_taxonomy_delete_tags_requested(self, tags: List[str]) -> None:
        """Handle delete-tags request from manager dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        normalized = [str(tag).strip() for tag in list(tags or []) if str(tag).strip()]
        if not normalized:
            self._set_taxonomy_dialog_busy(False, "Select at least one tag to delete.")
            return

        tag_text = ", ".join(normalized)
        confirm = QMessageBox.question(
            self,
            "Delete Tag(s)",
            f"Delete selected tag(s): {tag_text} ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._queue_taxonomy_action(
            "delete_tags",
            self._api_delete_tags,
            "Delete Tag",
            normalized,
        )

    def _pause_session(self) -> None:
        """Pause all torrents in current session.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._log("INFO", "Pausing session")
        self._show_progress("Pausing session...")
        self.api_queue.add_task(
            "pause_session",
            self._api_pause_session,
            lambda r: self._on_torrent_action_done("Pause Session", r),
        )

    def _resume_session(self) -> None:
        """Resume all torrents in current session.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._log("INFO", "Resuming session")
        self._show_progress("Resuming session...")
        self.api_queue.add_task(
            "resume_session",
            self._api_resume_session,
            lambda r: self._on_torrent_action_done("Resume Session", r),
        )

    def _queue_delete_torrents(self, torrent_hashes: List[str], delete_files: bool,
                               action_name: str, progress_text: str) -> None:
        """Queue deletion for selected torrent(s) with explicit delete-files mode.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._log(
            "INFO",
            f"{action_name}: {len(torrent_hashes)} torrent(s) (files={delete_files})"
        )
        self._show_progress(progress_text)
        task_name = "delete_torrent_with_data" if delete_files else "delete_torrent"
        self.api_queue.add_task(
            task_name,
            self._api_delete_torrent,
            lambda r: self._on_torrent_action_done(action_name, r),
            torrent_hashes, delete_files
        )

    def _remove_torrent(self) -> None:
        """Remove selected torrent(s) and keep data on disk.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        reply = QMessageBox.question(
            self,
            "Remove Torrent(s)",
            f"Remove {len(torrent_hashes)} selected torrent(s) from qBittorrent and keep data on disk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._queue_delete_torrents(
            torrent_hashes,
            delete_files=False,
            action_name="Remove",
            progress_text="Removing torrent..." if len(torrent_hashes) == 1 else f"Removing {len(torrent_hashes)} torrents..."
        )

    def _remove_torrent_and_delete_data(self) -> None:
        """Remove selected torrent(s) and delete data from disk.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        reply = QMessageBox.question(
            self,
            "Remove And Delete Data",
            f"Remove {len(torrent_hashes)} selected torrent(s) and delete data from disk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._queue_delete_torrents(
            torrent_hashes,
            delete_files=True,
            action_name="Remove + Delete Data",
            progress_text=(
                "Removing torrent and deleting data..."
                if len(torrent_hashes) == 1
                else f"Removing {len(torrent_hashes)} torrents and deleting data..."
            )
        )

    def _remove_torrent_no_confirmation(self) -> None:
        """Remove selected torrent(s) and keep data on disk, without confirmation.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        self._queue_delete_torrents(
            torrent_hashes,
            delete_files=False,
            action_name="Remove (No Confirmation)",
            progress_text="Removing torrent..." if len(torrent_hashes) == 1 else f"Removing {len(torrent_hashes)} torrents...",
        )

    def _remove_torrent_and_delete_data_no_confirmation(self) -> None:
        """Remove selected torrent(s) and delete data, without confirmation.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        self._queue_delete_torrents(
            torrent_hashes,
            delete_files=True,
            action_name="Remove + Delete Data (No Confirmation)",
            progress_text=(
                "Removing torrent and deleting data..."
                if len(torrent_hashes) == 1
                else f"Removing {len(torrent_hashes)} torrents and deleting data..."
            ),
        )

    def _delete_torrent(self) -> None:
        """Delete selected torrent(s) with confirmation.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        reply = QMessageBox.question(
            self, "Delete Torrent(s)",
            f"Delete {len(torrent_hashes)} selected torrent(s) and their files from disk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return
        delete_files = (reply == QMessageBox.StandardButton.Yes)
        self._queue_delete_torrents(
            torrent_hashes,
            delete_files=delete_files,
            action_name="Delete",
            progress_text="Deleting torrent..." if len(torrent_hashes) == 1 else f"Deleting {len(torrent_hashes)} torrents..."
        )

    def _clear_cache_and_refresh(self) -> None:
        """Clear local content cache and refresh torrents.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            self._suppress_next_cache_save = True
            self.content_cache = {}
            self.current_content_files = []
            self.tree_files.clear()

            if self.cache_file_path.exists():
                self.cache_file_path.unlink()

            cache_tmp = Path(f"{self.cache_file_path}.tmp")
            if cache_tmp.exists():
                cache_tmp.unlink()

            self._log("INFO", "Content cache cleared")
            self._set_status("Content cache cleared")
        except Exception as e:
            self._log("ERROR", f"Failed to clear cache: {e}")
            self._set_status(f"Failed to clear cache: {e}")

        self._refresh_torrents()

    def _reset_view_defaults(self) -> None:
        """Reset view/layout/filter/refresh options back to startup defaults.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        reply = QMessageBox.question(
            self,
            "Reset View",
            "Reset view to defaults?\n\n"
            "This resets column widths, splitter positions, refresh interval, "
            "auto-refresh, status/category/tag filters, and sort order.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._set_status("Reset view cancelled")
            return

        try:
            # Reset splitter positions, table columns, order and sort indicator.
            self._restore_default_view_state()
            # Enforce deterministic header restoration for tests/platform quirks.
            if getattr(self, "_default_torrent_header_state", None):
                self.tbl_torrents.horizontalHeader().restoreState(
                    self._default_torrent_header_state
                )

            # Reset quick filters (UI + cached values).
            private_signals = self.cmb_private.blockSignals(True)
            self.cmb_private.setCurrentIndex(0)
            self.cmb_private.blockSignals(private_signals)

            name_signals = self.txt_name_filter.blockSignals(True)
            self.txt_name_filter.clear()
            self.txt_name_filter.blockSignals(name_signals)

            file_signals = self.txt_file_filter.blockSignals(True)
            self.txt_file_filter.clear()
            self.txt_file_filter.blockSignals(file_signals)

            content_signals = self.txt_content_filter.blockSignals(True)
            self.txt_content_filter.clear()
            self.txt_content_filter.blockSignals(content_signals)

            self.current_private_filter = None
            self.current_text_filter = ""
            self.current_file_filter = ""
            self.current_content_filter = ""
            self._apply_content_filter()

            # Reset API-backed filters.
            self.current_status_filter = self.default_status_filter
            self.current_category_filter = None
            self.current_tag_filter = None
            self.current_size_bucket = None
            self.current_tracker_filter = None
            self.tree_filters.clearSelection()
            self._refresh_filter_tree_highlights()

            # Reset refresh behavior.
            self.refresh_interval = max(1, int(self.default_refresh_interval))
            self.auto_refresh_enabled = bool(self.default_auto_refresh_enabled)

            if hasattr(self, "action_auto_refresh"):
                action_signals = self.action_auto_refresh.blockSignals(True)
                self.action_auto_refresh.setChecked(self.auto_refresh_enabled)
                self.action_auto_refresh.blockSignals(action_signals)
                self._update_auto_refresh_action_text()

            self._sync_auto_refresh_timer_state()

            # Persist and refresh data using default status/category/tag filters.
            self._save_settings()
            self._save_refresh_settings()
            self._log(
                "INFO",
                "View reset to defaults "
                f"(status={self.current_status_filter}, "
                f"auto_refresh={self.auto_refresh_enabled}, "
                f"interval={self.refresh_interval}s)"
            )
            self._set_status("View reset to defaults")
            self._refresh_torrents()
        except Exception as e:
            self._log("ERROR", f"Failed to reset view defaults: {e}")
            self._set_status(f"Failed to reset view: {e}")

    def _open_log_file(self) -> None:
        """Open the log file in the OS default application.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        log_path = os.path.abspath(self.log_file_path)
        try:
            if not self._open_file_in_default_app(log_path):
                raise RuntimeError("OS failed to open log file")
        except Exception as e:
            self._log("ERROR", f"Failed to open log file: {e}")
            self._set_status(f"Failed to open log file: {e}")

    def _set_auto_refresh_interval(self) -> None:
        """Prompt user to set auto-refresh frequency in seconds.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            current = self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL)
            if current < 1:
                current = DEFAULT_REFRESH_INTERVAL

            seconds, ok = QInputDialog.getInt(
                self,
                "Auto-Refresh Interval",
                "Refresh every (seconds):",
                value=current,
                minValue=1,
                maxValue=86400,
                step=1,
            )
            if not ok:
                return

            self.refresh_interval = int(seconds)
            self._update_auto_refresh_action_text()
            self._sync_auto_refresh_timer_state()

            self._log("INFO", f"Auto-refresh interval set to {self.refresh_interval}s")
            self._set_status(f"Auto-refresh interval: {self.refresh_interval}s")
            self._save_refresh_settings()
        except Exception as e:
            self._log("ERROR", f"Failed to set auto-refresh interval: {e}")
            self._set_status(f"Failed to set auto-refresh interval: {e}")

    def _toggle_auto_refresh(self, checked: bool) -> None:
        """Toggle auto-refresh.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self.auto_refresh_enabled = checked
        if checked:
            self._sync_auto_refresh_timer_state()
            if self.refresh_timer.isActive():
                self._log("INFO", f"Auto-refresh enabled ({self.refresh_interval}s)")
            else:
                self._log("INFO", "Auto-refresh enabled and paused on Edit tab")
        else:
            self._sync_auto_refresh_timer_state()
            self._log("INFO", "Auto-refresh disabled")
        self._save_refresh_settings()

    def _toggle_debug_logging(self, checked: bool) -> None:
        """Enable/disable comprehensive debug logging including API calls/responses.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self.debug_logging_enabled = bool(checked)
        if self.debug_logging_enabled:
            self._log("INFO", "Debug logging enabled (API calls/responses)")
            self._set_status("Debug logging enabled")
        else:
            self._log("INFO", "Debug logging disabled")
            self._set_status("Debug logging disabled")
        self._save_settings()

    def _toggle_human_readable(self, checked: bool) -> None:
        """Toggle display of size/speed values between human-readable and bytes.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        mode = "human_readable" if checked else "bytes"
        self.display_size_mode = mode
        self.display_speed_mode = mode

        # Re-render UI that depends on display units.
        self._update_window_title_speeds()
        self._update_statusbar_transfer_summary()
        self._calculate_size_buckets()
        self._update_size_tree()
        self._update_torrents_table()
        self._apply_content_filter()

        selected = getattr(self, "_selected_torrent", None)
        if selected is not None and self.detail_tabs.isEnabled():
            self._display_torrent_details(selected)

        self._save_settings()
        mode_label = "human readable" if checked else "bytes"
        self._log("INFO", f"Display mode set to {mode_label}")
        self._set_status(f"Display mode: {mode_label}")

    def _about_dialog_text(self) -> str:
        """Build full about dialog text including runtime file paths.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        instance_text = str(getattr(self, "instance_id", "") or "").strip()
        if not instance_text:
            instance_text = "N/A"

        try:
            ini_path = str(self._settings_ini_path())
        except Exception:
            ini_path = "N/A"

        cache_path = str(getattr(self, "cache_file_path", "") or "N/A")
        cache_tmp_path = (
            str(Path(f"{cache_path}.tmp"))
            if cache_path and cache_path != "N/A"
            else "N/A"
        )
        instance_counter = _normalize_instance_counter(
            getattr(self, "config", {}).get("_instance_counter", 1)
            if isinstance(getattr(self, "config", None), dict)
            else 1
        )
        lock_path = str(
            getattr(self, "config", {}).get("_instance_lock_file_path", "")
            if isinstance(getattr(self, "config", None), dict)
            else ""
        ).strip()
        if not lock_path:
            lock_path = str(
                resolve_instance_lock_file_path(instance_text, instance_counter)
            )

        return (
            "qBiremo Enhanced v2.0\n\n"
            "Advanced qBittorrent GUI Client\n"
            "Built with PySide6\n"
            f"Instance ID: {instance_text}\n"
            f"Settings INI: {ini_path}\n"
            f"Cache file: {cache_path}\n"
            f"Cache temp file: {cache_tmp_path}\n\n"
            f"Lock file: {lock_path}\n\n"
            "(c) 2025"
        )

    def _show_about(self) -> None:
        """Show about dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("About qBiremo Enhanced")
        dialog.resize(1100, 360)

        layout = QVBoxLayout(dialog)
        txt_about = QTextEdit(dialog)
        txt_about.setReadOnly(True)
        txt_about.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        txt_about.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        txt_about.setPlainText(self._about_dialog_text())
        layout.addWidget(txt_about, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

class SessionUiController(WindowControllerBase):
    def _sync_auto_refresh_timer_state(self) -> None:
        """Start/stop refresh timer based on settings and current details context.

        Side effects: None.
        Failure modes: None.
        """
        if not hasattr(self, "refresh_timer"):
            return
        should_run = (
            bool(self.auto_refresh_enabled)
            and not self._is_torrent_edit_tab_active()
            and not bool(self._refresh_torrents_in_progress)
        )
        interval_seconds = max(1, self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL))
        if should_run:
            self.refresh_timer.start(interval_seconds * 1000)
        else:
            self.refresh_timer.stop()

    def _set_refresh_torrents_in_progress(self, in_progress: bool) -> None:
        """Set refresh-in-progress state and re-evaluate auto-refresh timer.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        active = bool(in_progress)
        if self._refresh_torrents_in_progress == active:
            return
        self._refresh_torrents_in_progress = active
        self._sync_auto_refresh_timer_state()

    def _update_auto_refresh_action_text(self) -> None:
        """Refresh auto-refresh menu label to include current interval.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if not hasattr(self, "action_auto_refresh"):
            return
        interval_seconds = max(1, self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL))
        self.action_auto_refresh.setText(f"Enable &Auto-Refresh ({interval_seconds})")

    def _record_session_timeline_sample(self, alt_enabled: Optional[bool] = None) -> None:
        """Record one session timeline sample from current torrent list.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        total_down = 0
        total_up = 0
        active_count = 0
        for torrent in self.all_torrents:
            down = self._safe_int(getattr(torrent, "dlspeed", 0), 0)
            up = self._safe_int(getattr(torrent, "upspeed", 0), 0)
            total_down += down
            total_up += up
            if down > 0 or up > 0:
                active_count += 1

        alt_mode = self._last_alt_speed_mode if alt_enabled is None else bool(alt_enabled)
        sample = {
            "ts": time.time(),
            "down_bps": int(total_down),
            "up_bps": int(total_up),
            "active_count": int(active_count),
            "alt_enabled": bool(alt_mode),
        }
        self.session_timeline_history.append(sample)

        dialog = self._session_timeline_dialog
        if dialog is not None and dialog.isVisible():
            dialog.set_samples(list(self.session_timeline_history))

    def _show_session_timeline(self) -> None:
        """Open session timeline dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if self._session_timeline_dialog is not None and self._session_timeline_dialog.isVisible():
            self._session_timeline_dialog.raise_()
            self._session_timeline_dialog.activateWindow()
            self._session_timeline_dialog.set_samples(list(self.session_timeline_history))
            return

        dialog = SessionTimelineDialog(self)
        dialog.refresh_requested.connect(self._refresh_torrents)
        dialog.clear_requested.connect(self._clear_session_timeline_history)
        dialog.finished.connect(self._on_session_timeline_dialog_closed)
        dialog.set_samples(list(self.session_timeline_history))
        self._session_timeline_dialog = dialog
        dialog.show()

    def _on_session_timeline_dialog_closed(self, _result: int) -> None:
        """Clear timeline dialog reference on close.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._session_timeline_dialog = None

    def _clear_session_timeline_history(self) -> None:
        """Clear stored session timeline samples.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self.session_timeline_history.clear()
        dialog = self._session_timeline_dialog
        if dialog is not None and dialog.isVisible():
            dialog.set_samples([])

    def _show_tracker_health_dashboard(self) -> None:
        """Open tracker health dashboard dialog.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if self._tracker_health_dialog is not None and self._tracker_health_dialog.isVisible():
            self._tracker_health_dialog.raise_()
            self._tracker_health_dialog.activateWindow()
            self._request_tracker_health_refresh()
            return

        dialog = TrackerHealthDialog(self)
        dialog.refresh_requested.connect(self._request_tracker_health_refresh)
        dialog.finished.connect(self._on_tracker_health_dialog_closed)
        self._tracker_health_dialog = dialog
        dialog.show()
        self._request_tracker_health_refresh()

    def _on_tracker_health_dialog_closed(self, _result: int) -> None:
        """Clear tracker-health dialog reference on close.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self._tracker_health_dialog = None

    def _set_tracker_health_dialog_busy(self, busy: bool, message: str = "") -> None:
        """Set tracker-health dialog busy state.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        dialog = self._tracker_health_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _request_tracker_health_refresh(self) -> None:
        """Queue tracker health aggregation for all currently known torrents.

        Side effects: None.
        Failure modes: None.
        """
        torrent_hashes = [
            str(getattr(torrent, "hash", "") or "").strip()
            for torrent in self.all_torrents
            if str(getattr(torrent, "hash", "") or "").strip()
        ]
        self._show_progress("Loading tracker health dashboard...")
        self._set_tracker_health_dialog_busy(True, "Loading tracker health...")
        self.analytics_api_queue.add_task(
            "tracker_health_dashboard",
            self._fetch_tracker_health_data,
            self._on_tracker_health_loaded,
            torrent_hashes,
        )

    def _on_tracker_health_loaded(self, result: Dict) -> None:
        """Render tracker health dashboard data.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        dialog = self._tracker_health_dialog
        if result.get("success"):
            rows = result.get("data", [])
            if dialog is not None and dialog.isVisible():
                dialog.set_rows(rows if isinstance(rows, list) else [])
                dialog.set_busy(False)
            self._set_status("Tracker health loaded")
        else:
            error = result.get("error", "Unknown error")
            if dialog is not None and dialog.isVisible():
                dialog.set_busy(False, f"Failed: {error}")
            self._set_status(f"Tracker health failed: {error}")
        self._hide_progress()

    def _show_progress(self, message: str) -> None:
        """Show progress indicator.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self._set_status(message)

    def _hide_progress(self) -> None:
        """Hide progress indicator.

        Side effects: None.
        Failure modes: None.
        """
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self._set_status("Ready")

    def _set_status(self, message: str) -> None:
        """Set status bar message.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        self.lbl_status.setText(message)

    def _update_statusbar_transfer_summary(self) -> None:
        """Render aggregate transfer summary in the status bar.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        dht_label = getattr(self, "lbl_dht_nodes", None)
        down_label = getattr(self, "lbl_download_summary", None)
        up_label = getattr(self, "lbl_upload_summary", None)
        if dht_label is None or down_label is None or up_label is None:
            return

        total_down_speed = 0
        total_up_speed = 0
        total_session_download = 0
        total_session_upload = 0
        for torrent in self.all_torrents:
            total_down_speed += self._safe_int(getattr(torrent, "dlspeed", 0), 0)
            total_up_speed += self._safe_int(getattr(torrent, "upspeed", 0), 0)
            total_session_download += self._safe_int(
                getattr(torrent, "downloaded_session", 0), 0
            )
            total_session_upload += self._safe_int(
                getattr(torrent, "uploaded_session", 0), 0
            )

        down_speed_text = format_speed_mode(total_down_speed, self.display_speed_mode) or "0"
        up_speed_text = format_speed_mode(total_up_speed, self.display_speed_mode) or "0"

        down_limit_raw = max(0, self._safe_int(self._last_global_download_limit, 0))
        up_limit_raw = max(0, self._safe_int(self._last_global_upload_limit, 0))
        down_limit_text = (
            "Unlimited"
            if down_limit_raw <= 0
            else (format_speed_mode(down_limit_raw, self.display_speed_mode) or "0")
        )
        up_limit_text = (
            "Unlimited"
            if up_limit_raw <= 0
            else (format_speed_mode(up_limit_raw, self.display_speed_mode) or "0")
        )

        session_down_text = format_size_mode(total_session_download, self.display_size_mode)
        session_up_text = format_size_mode(total_session_upload, self.display_size_mode)
        dht_label.setText(
            f"DHT: {max(0, self._safe_int(self._last_dht_nodes, 0))}"
        )
        down_label.setText(
            f"D: {down_speed_text} [{down_limit_text}] ({session_down_text})"
        )
        up_label.setText(
            f"U: {up_speed_text} [{up_limit_text}] ({session_up_text})"
        )

    def _bring_to_front_startup(self) -> None:
        """Bring the main window to front shortly after startup.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Handle Enter in content tree consistently across Qt styles/platforms.

        Side effects: None.
        Failure modes: None.
        """
        if (
            watched is getattr(self, "tree_files", None)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self._open_selected_content_path()
            return True
        return QMainWindow.eventFilter(self, watched, event)

    def _update_window_title_speeds(self) -> None:
        """Show aggregate up/down speeds in the window title.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            total_down = 0
            total_up = 0
            for torrent in self.all_torrents:
                total_down += self._safe_int(getattr(torrent, 'dlspeed', 0), 0)
                total_up += self._safe_int(getattr(torrent, 'upspeed', 0), 0)

            up_text = format_speed_mode(total_up, self.display_speed_mode) or "0"
            down_text = format_speed_mode(total_down, self.display_speed_mode) or "0"
            self.setWindowTitle(
                self.title_bar_speed_format.format(
                    up_text=up_text,
                    down_text=down_text,
                )
            )
        except Exception:
            # Keep title stable even if malformed data appears.
            self.setWindowTitle(
                DEFAULT_TITLE_BAR_SPEED_FORMAT.format(
                    up_text="0",
                    down_text="0",
                )
            )

    @staticmethod
    def _safe_debug_repr(value: Any, max_len: Optional[int] = 2000) -> str:
        """Build bounded repr for debug log messages.

        Side effects: None.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        try:
            text = repr(value)
        except Exception:
            text = f"<unrepr {type(value).__name__}>"
        if isinstance(max_len, int) and max_len > 0 and len(text) > max_len:
            return text[:max_len] + "...<truncated>"
        return text

    def _debug_log_api_call(self, method_name: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> None:
        """Log one qBittorrent API call invocation when debug logging is enabled.

        Side effects: None.
        Failure modes: None.
        """
        if not self.debug_logging_enabled:
            return
        logger.debug(
            "[API CALL] %s args=%s kwargs=%s",
            str(method_name),
            self._safe_debug_repr(args),
            self._safe_debug_repr(kwargs),
        )

    def _debug_log_api_response(self, method_name: str, result: Any, elapsed: float) -> None:
        """Log one qBittorrent API call response when debug logging is enabled.

        Side effects: None.
        Failure modes: None.
        """
        if not self.debug_logging_enabled:
            return
        logger.debug(
            "[API RESP] %s elapsed=%.3fs result=%s",
            str(method_name),
            float(elapsed),
            self._safe_debug_repr(result, max_len=None),
        )

    def _debug_log_api_error(self, method_name: str, error: Exception, elapsed: float) -> None:
        """Log one qBittorrent API call failure when debug logging is enabled.

        Side effects: None.
        Failure modes: None.
        """
        if not self.debug_logging_enabled:
            return
        logger.debug(
            "[API ERR] %s elapsed=%.3fs error=%s",
            str(method_name),
            float(elapsed),
            self._safe_debug_repr(error),
        )

    def _log(self, level: str, message: str, elapsed: Optional[float] = None) -> None:
        """Write to Python file logger.

        Side effects: None.
        Failure modes: None.
        """
        elapsed_str = f" [{elapsed:.3f}s]" if elapsed is not None else ""
        log_msg = f"{message}{elapsed_str}"
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, log_msg)

    def closeEvent(self, event) -> None:
        """Handle window close event.

        Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
        Failure modes: None.
        """
        if self._add_torrent_dialog is not None and self._add_torrent_dialog.isVisible():
            self._add_torrent_dialog.close()
        self._save_settings()
        self._save_content_cache()
        event.accept()

