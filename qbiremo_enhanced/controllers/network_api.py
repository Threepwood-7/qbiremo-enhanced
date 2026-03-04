"""Feature controllers for MainWindow composition."""

import base64
import json
import math
import os
import time
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlparse

import qbittorrentapi
from PySide6.QtCore import QTimer

from ..constants import (
    CACHE_MAX_AGE_DAYS,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DEFAULT_REFRESH_INTERVAL,
)
from ..models.config import NormalizedConfig
from ..models.torrent import (
    PeerRow,
    TorrentCacheEntry,
    TorrentFileEntry,
    TrackerHealthRow,
    TrackerRow,
)
from ..tasking import _DebugAPIClientProxy
from ..types import APITaskResult, api_task_result
from ..utils import (
    _normalize_http_protocol_scheme,
    matches_wildcard,
)
from .base import RECOVERABLE_CONTROLLER_EXCEPTIONS, WindowControllerBase, logger


class NetworkApiController(WindowControllerBase):
    """Handle API calls, cache I/O, and queue callbacks for network data."""

    def _build_connection_info(self, config: NormalizedConfig) -> dict[str, object]:
        """Build qBittorrent connection info from TOML config with env var fallback."""
        # Host URL may contain scheme, basic-auth credentials, and port.
        raw_host = config.get("qb_host") or "localhost"
        scheme_override = _normalize_http_protocol_scheme(
            config.get("http_protocol_scheme", "http")
        )
        explicit_scheme_override = "http_protocol_scheme" in config

        extra_headers = {}
        host = raw_host

        # Parse URL to extract HTTP basic auth if embedded
        if "://" in raw_host:
            parsed = urlparse(raw_host)
            http_user = parsed.username or config.get("http_basic_auth_username", "")
            http_pass = parsed.password or config.get("http_basic_auth_password", "")
            # Rebuild host without credentials
            netloc_host = parsed.hostname or "localhost"
            if parsed.port:
                netloc_host = f"{netloc_host}:{parsed.port}"
            parsed_scheme = _normalize_http_protocol_scheme(parsed.scheme or "http")
            final_scheme = scheme_override if explicit_scheme_override else parsed_scheme
            host = f"{final_scheme}://{netloc_host}"
        else:
            http_user = config.get("http_basic_auth_username", "")
            http_pass = config.get("http_basic_auth_password", "")
            host = f"{scheme_override}://{str(raw_host).strip() or 'localhost'}"

        # Also allow standalone config keys
        if not http_user:
            http_user = os.getenv("X_HTTP_USER", "")
        if not http_pass:
            http_pass = os.getenv("X_HTTP_PASS", "")

        if http_user:
            credentials = base64.b64encode(f"{http_user}:{http_pass}".encode()).decode()
            extra_headers["Authorization"] = f"Basic {credentials}"

        # Port (only used when host is a plain hostname without scheme)
        port = self._safe_int(config.get("qb_port", 8080), 8080)
        http_timeout = self._safe_int(
            config.get("http_timeout", DEFAULT_HTTP_TIMEOUT_SECONDS),
            DEFAULT_HTTP_TIMEOUT_SECONDS,
        )
        if http_timeout <= 0:
            http_timeout = DEFAULT_HTTP_TIMEOUT_SECONDS

        conn = {
            "host": host,
            "port": port,
            "username": (config.get("qb_username") or "admin"),
            "password": (config.get("qb_password") or ""),
            "FORCE_SCHEME_FROM_HOST": True,
            "VERIFY_WEBUI_CERTIFICATE": False,
            "DISABLE_LOGGING_DEBUG_OUTPUT": False,
            "REQUESTS_ARGS": {"timeout": int(http_timeout)},
        }
        if extra_headers:
            conn["EXTRA_HEADERS"] = extra_headers

        return conn

    def _create_client(self) -> Any:
        """Create and authenticate a qBittorrent API client."""
        qb_client = qbittorrentapi.Client(**self.qb_conn_info)
        qb = (
            _DebugAPIClientProxy(qb_client, cast(Any, self))
            if self.debug_logging_enabled
            else qb_client
        )
        cast(Any, qb).auth_log_in()
        return qb

    def _remove_expired_cache_file(self) -> None:
        """Delete cache file when older than configured maximum age."""
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
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            logger.warning("Failed to remove expired content cache %s: %s", self.cache_file_path, e)

    def _load_content_cache(self) -> None:
        """Load persistent content cache from JSON file."""
        self.content_cache = {}
        try:
            if not self.cache_file_path.exists():
                return
            raw = self.cache_file_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return

            normalized: dict[str, TorrentCacheEntry] = {}
            for torrent_hash, entry in parsed.items():
                if not isinstance(entry, dict):
                    continue
                files = entry.get("files", [])
                if not isinstance(files, list):
                    files = []
                normalized_files = []
                for f in files:
                    if not isinstance(f, dict):
                        continue
                    normalized_files.append(self._normalize_cached_file(f))
                normalized[str(torrent_hash)] = {
                    "state": str(entry.get("state", "") or ""),
                    "files": normalized_files,
                }
            self.content_cache = normalized
            logger.info("Loaded content cache: %d torrents", len(self.content_cache))
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            logger.warning("Failed to load content cache from %s: %s", self.cache_file_path, e)
            self.content_cache = {}

    def _save_content_cache(self) -> None:
        """Persist content cache to disk as JSON."""
        try:
            self.cache_file_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = Path(f"{self.cache_file_path}.tmp")
            tmp_path.write_text(
                json.dumps(self.content_cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp_path.replace(self.cache_file_path)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            logger.warning("Failed to save content cache to %s: %s", self.cache_file_path, e)

    @staticmethod
    def _safe_int(value: object, default: int = 0) -> int:
        """Convert value to int and return default when conversion fails."""
        try:
            return int(cast(Any, value))
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def _safe_float(value: object, default: float = 0.0) -> float:
        """Convert value to float and return default when conversion fails."""
        try:
            return float(cast(Any, value))
        except (TypeError, ValueError, OverflowError):
            return default

    def _normalize_cached_file(self, entry: dict[str, object]) -> TorrentFileEntry:
        """Normalize one cached file entry."""
        return {
            "name": str(entry.get("name", "") or ""),
            "size": self._safe_int(entry.get("size", 0), 0),
            "progress": self._safe_float(entry.get("progress", 0.0), 0.0),
            "priority": self._safe_int(entry.get("priority", 1), 1),
        }

    def _serialize_file_for_cache(self, file_obj: object) -> TorrentFileEntry:
        """Serialize API file object to cache-safe dict."""
        return self._normalize_cached_file(
            {
                "name": getattr(file_obj, "name", "") or "",
                "size": getattr(file_obj, "size", 0),
                "progress": getattr(file_obj, "progress", 0.0),
                "priority": getattr(file_obj, "priority", 1),
            }
        )

    def _get_cached_files(self, torrent_hash: str) -> list[TorrentFileEntry]:
        """Return cached files for torrent hash, or empty list."""
        if not torrent_hash:
            return []
        entry = self.content_cache.get(torrent_hash, {})
        files = entry.get("files", []) if isinstance(entry, dict) else []
        return files if isinstance(files, list) else []

    def _get_cache_refresh_candidates(self) -> dict[str, str]:
        """Return torrent hashes that need cache refresh (new/missing/status change)."""
        candidates: dict[str, str] = {}
        for torrent in self.all_torrents:
            torrent_hash = getattr(torrent, "hash", "") or ""
            if not torrent_hash:
                continue
            state = str(getattr(torrent, "state", "") or "")
            cached = self.content_cache.get(torrent_hash)
            cached_state = str(cached.get("state", "")) if isinstance(cached, dict) else ""
            cached_files = cached.get("files") if isinstance(cached, dict) else None
            if cached_state != state or not isinstance(cached_files, list):
                candidates[torrent_hash] = state

        return candidates

    def _matches_file_filter(self, torrent_hash: str, pattern: str) -> bool:
        """Return True when any cached file name/path matches the pattern."""
        cached_files = self._get_cached_files(torrent_hash)
        if not cached_files:
            return False
        for entry in cached_files:
            name = str(entry.get("name", "") or "")
            normalized = name.replace("\\", "/")
            basename = normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized
            if matches_wildcard(basename, pattern) or matches_wildcard(normalized, pattern):
                return True
        return False

    def _fetch_categories(self, **_kw: object) -> APITaskResult:
        """Fetch categories from qBittorrent."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                result = qb.torrents_categories()
            elapsed = time.time() - start_time
            return api_task_result(data=result, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=None, elapsed=elapsed, success=False, error=str(e))

    def _fetch_tags(self, **_kw: object) -> APITaskResult:
        """Fetch tags from qBittorrent."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                result = qb.torrents_tags()
            tags = sorted(str(tag or "") for tag in list(result or []))
            elapsed = time.time() - start_time
            return api_task_result(data=tags, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=[], elapsed=elapsed, success=False, error=str(e))

    def _selected_remote_torrent_filters(self) -> dict[str, object]:
        """Build remote API filter kwargs from selected status/category/tag/private filters."""
        filters: dict[str, object] = {}

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

    def _fetch_torrents_snapshot(
        self,
        qb: qbittorrentapi.Client,
        remote_filters: dict[str, object],
        dht_nodes: int,
    ) -> tuple[list[Any], int]:
        """Fetch torrent list from either filtered API call or sync/maindata."""
        if remote_filters:
            result = list(cast(Any, qb).torrents_info(**remote_filters))
            result.sort(
                key=lambda torrent: self._safe_int(getattr(torrent, "added_on", 0), 0),
                reverse=True,
            )
            return result, dht_nodes

        maindata = qb.sync_maindata(rid=int(self._sync_rid))
        result = self._merge_sync_maindata(maindata)
        payload = self._entry_to_dict(maindata)
        server_state = self._entry_to_dict(payload.get("server_state", {}))
        if "dht_nodes" in server_state:
            dht_nodes = max(0, self._safe_int(server_state.get("dht_nodes"), dht_nodes))
        return result, dht_nodes

    def _read_alt_speed_mode(self, qb: qbittorrentapi.Client, fallback: bool) -> bool:
        """Read alternate speed mode from API when available."""
        if not hasattr(qb, "transfer_speed_limits_mode"):
            return fallback
        try:
            return self._safe_int(qb.transfer_speed_limits_mode(), 0) == 1
        except RECOVERABLE_CONTROLLER_EXCEPTIONS:
            return fallback

    def _read_dht_nodes(self, qb: qbittorrentapi.Client, fallback: int) -> int:
        """Read DHT node count from transfer info when available."""
        if not hasattr(qb, "transfer_info"):
            return fallback
        try:
            transfer_info = self._entry_to_dict(qb.transfer_info())
            if "dht_nodes" in transfer_info:
                return max(0, self._safe_int(transfer_info.get("dht_nodes"), fallback))
        except RECOVERABLE_CONTROLLER_EXCEPTIONS:
            return fallback
        return fallback

    def _read_global_download_limit(self, qb: qbittorrentapi.Client, fallback: int) -> int:
        """Read global download limit when API supports it."""
        if not hasattr(qb, "transfer_download_limit"):
            return fallback
        try:
            return max(0, self._safe_int(qb.transfer_download_limit(), 0))
        except RECOVERABLE_CONTROLLER_EXCEPTIONS:
            return fallback

    def _read_global_upload_limit(self, qb: qbittorrentapi.Client, fallback: int) -> int:
        """Read global upload limit when API supports it."""
        if not hasattr(qb, "transfer_upload_limit"):
            return fallback
        try:
            return max(0, self._safe_int(qb.transfer_upload_limit(), 0))
        except RECOVERABLE_CONTROLLER_EXCEPTIONS:
            return fallback

    def _fetch_torrents(self, **_kw: object) -> APITaskResult:
        """Fetch torrents via incremental sync/maindata and return current full list."""
        start_time = time.time()

        try:
            alt_speed_mode = bool(self._last_alt_speed_mode)
            dht_nodes = self._safe_int(self._last_dht_nodes, 0)
            global_download_limit = self._safe_int(self._last_global_download_limit, 0)
            global_upload_limit = self._safe_int(self._last_global_upload_limit, 0)
            remote_filters = self._selected_remote_torrent_filters()
            with self._create_client() as qb:
                result, dht_nodes = self._fetch_torrents_snapshot(qb, remote_filters, dht_nodes)
                alt_speed_mode = self._read_alt_speed_mode(qb, alt_speed_mode)
                dht_nodes = self._read_dht_nodes(qb, dht_nodes)
                global_download_limit = self._read_global_download_limit(qb, global_download_limit)
                global_upload_limit = self._read_global_upload_limit(qb, global_upload_limit)

            elapsed = time.time() - start_time
            return api_task_result(
                data=result,
                elapsed=elapsed,
                success=True,
                remote_filtered=bool(remote_filters),
                alt_speed_mode=bool(alt_speed_mode),
                dht_nodes=int(max(0, dht_nodes)),
                global_download_limit=int(max(0, global_download_limit)),
                global_upload_limit=int(max(0, global_upload_limit)),
            )
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=[], elapsed=elapsed, success=False, error=str(e))

    def _merge_sync_maindata(self, maindata: object) -> list[Any]:
        """Merge one sync/maindata payload into local torrent map and return ordered list."""
        payload = self._entry_to_dict(maindata)
        full_update = bool(payload.get("full_update", False))
        rid = self._safe_int(payload.get("rid", self._sync_rid), self._sync_rid)
        torrents_update = payload.get("torrents", {}) or {}
        removed_hashes = payload.get("torrents_removed", []) or []

        if full_update:
            self._sync_torrent_map = {}

        if hasattr(torrents_update, "items"):
            for raw_hash, entry in cast(Any, torrents_update).items():
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
        torrents.sort(key=lambda t: self._safe_int(getattr(t, "added_on", 0), 0), reverse=True)
        return torrents

    @staticmethod
    def _entry_to_dict(entry: object) -> dict[str, object]:
        """Convert qBittorrent API list/dict entry objects to plain dict."""
        if isinstance(entry, Mapping):
            return {str(k): v for k, v in entry.items()}
        if hasattr(cast(Any, entry), "items"):
            try:
                return {str(k): v for k, v in cast(Any, entry).items()}
            except RECOVERABLE_CONTROLLER_EXCEPTIONS:
                pass
        result: dict[str, object] = {}
        for key in dir(entry):
            if key.startswith("_"):
                continue
            try:
                value = getattr(entry, key)
            except RECOVERABLE_CONTROLLER_EXCEPTIONS:
                continue
            if callable(value):
                continue
            result[str(key)] = value
        return result

    def _fetch_selected_torrent_trackers(self, torrent_hash: str, **_kw: object) -> APITaskResult:
        """Fetch all tracker rows for one torrent."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                trackers = qb.torrents_trackers(torrent_hash=torrent_hash)

            rows: list[TrackerRow] = [
                cast(TrackerRow, self._entry_to_dict(entry)) for entry in list(trackers or [])
            ]
            elapsed = time.time() - start_time
            return api_task_result(data=rows, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=[], elapsed=elapsed, success=False, error=str(e))

    def _fetch_selected_torrent_peers(self, torrent_hash: str, **_kw: object) -> APITaskResult:
        """Fetch all peer rows for one torrent."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                peers_info = qb.sync_torrent_peers(torrent_hash=torrent_hash, rid=0)

            if isinstance(peers_info, Mapping):
                raw_peers = peers_info.get("peers", {}) or {}
            elif hasattr(cast(Any, peers_info), "get"):
                raw_peers = cast(Any, peers_info).get("peers", {}) or {}
            else:
                raw_peers = getattr(peers_info, "peers", {}) or {}
            peers_map = self._entry_to_dict(raw_peers)

            rows: list[PeerRow] = []
            for peer_id, peer_entry in peers_map.items():
                row: dict[str, object] = {"peer_id": str(peer_id)}
                row.update(self._entry_to_dict(peer_entry))
                rows.append(cast(PeerRow, row))

            elapsed = time.time() - start_time
            return api_task_result(data=rows, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=[], elapsed=elapsed, success=False, error=str(e))

    @staticmethod
    def _tracker_host_from_url(url: str) -> str:
        """Extract tracker hostname from URL where possible."""
        text = str(url or "").strip()
        if not text:
            return ""
        try:
            parsed = urlparse(text)
            return (parsed.hostname or text).lower()
        except ValueError:
            return text.lower()

    @staticmethod
    def _classify_tracker_health_status(status_code: int, message: str) -> str:
        """Classify one tracker row into working/failing/unknown buckets."""
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

    def _fetch_tracker_health_data(self, torrent_hashes: list[str], **_kw: object) -> APITaskResult:
        """Fetch and aggregate tracker health metrics across provided torrents."""
        start_time = time.time()
        try:
            stats: dict[str, dict[str, Any]] = {}
            with self._create_client() as qb:
                for torrent_hash in list(torrent_hashes or []):
                    if not torrent_hash:
                        continue
                    try:
                        tracker_rows = list(qb.torrents_trackers(torrent_hash=torrent_hash) or [])
                    except RECOVERABLE_CONTROLLER_EXCEPTIONS:
                        continue
                    for entry in tracker_rows:
                        row = self._entry_to_dict(entry)
                        tracker_host = self._tracker_host_from_url(str(row.get("url", "") or ""))
                        if not tracker_host:
                            continue
                        bucket = cast(
                            dict[str, Any],
                            stats.setdefault(
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
                            ),
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

            rows: list[TrackerHealthRow] = []
            for tracker, bucket in stats.items():
                row_count = self._safe_int(bucket.get("row_count", 0), 0)
                failing = self._safe_int(bucket.get("failing_count", 0), 0)
                working = self._safe_int(bucket.get("working_count", 0), 0)
                fail_rate = (failing * 100.0 / row_count) if row_count > 0 else 0.0
                avg_next = ""
                if self._safe_int(bucket.get("next_announce_count", 0), 0) > 0:
                    avg_next = str(
                        int(bucket["next_announce_sum"] / max(1, bucket["next_announce_count"]))
                    )
                torrent_hashes_bucket = bucket.get("torrent_hashes", set())
                if not isinstance(torrent_hashes_bucket, set):
                    torrent_hashes_bucket = set()

                dead = bool(failing > 0 and working == 0 and fail_rate >= 50.0)
                rows.append(
                    {
                        "tracker": tracker,
                        "torrent_count": len(torrent_hashes_bucket),
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
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=[], elapsed=elapsed, success=False, error=str(e))

    def _refresh_content_cache_for_torrents(
        self, torrent_states: dict[str, str], **_kw: object
    ) -> APITaskResult:
        """Refresh cached file trees for provided torrent hashes."""
        start_time = time.time()
        try:
            updates: dict[str, dict[str, object]] = {}
            errors: dict[str, str] = {}
            with self._create_client() as qb:
                for torrent_hash, state in torrent_states.items():
                    try:
                        files = qb.torrents_files(torrent_hash=torrent_hash)
                        updates[torrent_hash] = {
                            "state": str(state or ""),
                            "files": [self._serialize_file_for_cache(f) for f in files],
                        }
                    except RECOVERABLE_CONTROLLER_EXCEPTIONS as ex:
                        errors[torrent_hash] = str(ex)
            elapsed = time.time() - start_time
            return api_task_result(
                data=updates,
                elapsed=elapsed,
                success=True,
                errors=errors,
            )
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(
                data={},
                elapsed=elapsed,
                success=False,
                error=str(e),
                errors={},
            )

    def _add_torrent_api(self, torrent_data: dict, **_kw: object) -> APITaskResult:
        """Add a torrent via API."""
        start_time = time.time()
        data = dict(torrent_data)  # avoid mutating caller's dict
        try:
            with self._create_client() as qb:
                result_ok = True
                submitted_urls = 0
                added_urls = 0
                submitted_files = 0
                added_files = 0
                failed_sources: list[dict[str, str]] = []
                urls_payload = data.pop("urls", None)
                files_payload = data.pop("torrent_files", None)

                if urls_payload not in (None, "", []):
                    if isinstance(urls_payload, (list, tuple, set)):
                        url_entries = [
                            str(u or "").strip() for u in urls_payload if str(u or "").strip()
                        ]
                    else:
                        url_entries = [str(urls_payload).strip()]
                    submitted_urls = len(url_entries)
                    url_result = qb.torrents_add(urls=urls_payload, **dict(data))
                    if url_result == "Ok.":
                        added_urls = len(url_entries)
                    else:
                        result_ok = False
                        failed_sources.append(
                            {"source": "urls", "error": f"API response: {url_result!r}"}
                        )

                if files_payload not in (None, "", []):
                    if isinstance(files_payload, (list, tuple, set)):
                        file_paths = [
                            str(path or "").strip()
                            for path in files_payload
                            if str(path or "").strip()
                        ]
                    else:
                        file_paths = [str(files_payload).strip()]
                    submitted_files = len(file_paths)
                    for file_path in file_paths:
                        try:
                            with open(file_path, "rb") as f:
                                file_result = qb.torrents_add(torrent_files=f, **dict(data))
                            if file_result == "Ok.":
                                added_files += 1
                            else:
                                result_ok = False
                                failed_sources.append(
                                    {"source": file_path, "error": f"API response: {file_result!r}"}
                                )
                        except RECOVERABLE_CONTROLLER_EXCEPTIONS as ex:
                            result_ok = False
                            failed_sources.append(
                                {"source": file_path, "error": str(ex)}
                            )

                if urls_payload in (None, "", []) and files_payload in (None, "", []):
                    raise ValueError("No torrent sources provided")

            elapsed = time.time() - start_time
            details = {
                "submitted_urls": submitted_urls,
                "added_urls": added_urls,
                "submitted_files": submitted_files,
                "added_files": added_files,
                "failed_sources": failed_sources,
            }
            return api_task_result(
                data=result_ok,
                elapsed=elapsed,
                success=True,
                details=details,
            )
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_export_torrents(
        self,
        torrent_hashes: list[str],
        export_dir: str,
        name_map: dict[str, str],
        **_kw: object,
    ) -> APITaskResult:
        """Export selected torrents into .torrent files in the target directory."""
        start_time = time.time()
        try:
            destination_text = str(export_dir or "").strip()
            if not destination_text:
                raise ValueError("Missing export directory")
            destination = Path(destination_text)
            destination.mkdir(parents=True, exist_ok=True)

            normalized_hashes = [
                str(h or "").strip() for h in list(torrent_hashes or []) if str(h or "").strip()
            ]
            if not normalized_hashes:
                raise ValueError("No torrents selected for export")

            exported_files: list[str] = []
            failed: dict[str, str] = {}
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
                    except RECOVERABLE_CONTROLLER_EXCEPTIONS as ex:
                        failed[torrent_hash] = str(ex)

            elapsed = time.time() - start_time
            if failed:
                return {
                    "data": {"exported": exported_files, "failed": failed},
                    "elapsed": elapsed,
                    "success": False,
                    "error": "Some torrent exports failed",
                }
            return {
                "data": {"exported": exported_files, "failed": {}},
                "elapsed": elapsed,
                "success": True,
            }
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return {
                "data": {"exported": [], "failed": {}},
                "elapsed": elapsed,
                "success": False,
                "error": str(e),
            }

    def _api_pause_torrent(self, torrent_hashes: list[str], **_kw: object) -> APITaskResult:
        """Pause one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_pause(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_resume_torrent(self, torrent_hashes: list[str], **_kw: object) -> APITaskResult:
        """Resume one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_resume(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_force_start_torrent(self, torrent_hashes: list[str], **_kw: object) -> APITaskResult:
        """Enable force start for one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_set_force_start(enable=True, torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_recheck_torrent(self, torrent_hashes: list[str], **_kw: object) -> APITaskResult:
        """Recheck one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_recheck(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_increase_torrent_priority(
        self, torrent_hashes: list[str], **_kw: object
    ) -> APITaskResult:
        """Increase queue priority for one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_increase_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_decrease_torrent_priority(
        self, torrent_hashes: list[str], **_kw: object
    ) -> APITaskResult:
        """Decrease queue priority for one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_decrease_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_top_torrent_priority(self, torrent_hashes: list[str], **_kw: object) -> APITaskResult:
        """Move one or more torrents to top queue priority via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_top_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_minimum_torrent_priority(
        self, torrent_hashes: list[str], **_kw: object
    ) -> APITaskResult:
        """Move one or more torrents to minimum queue priority via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_bottom_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_apply_selected_torrent_edits(
        self,
        torrent_hash: str,
        updates: dict[str, object],
        **_kw: object,
    ) -> APITaskResult:
        """Apply editable properties for a single torrent."""
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
                        limit=max(0, self._safe_int(normalized_updates.get("download_limit_bytes", 0), 0)),
                    )

                if "upload_limit_bytes" in normalized_updates:
                    qb.torrents_set_upload_limit(
                        torrent_hashes=hashes,
                        limit=max(0, self._safe_int(normalized_updates.get("upload_limit_bytes", 0), 0)),
                    )

            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_set_torrent_download_limit(
        self, torrent_hashes: list[str], limit_bytes: int, **_kw: object
    ) -> APITaskResult:
        """Set per-torrent download limit (bytes/sec) for selected torrents."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_set_download_limit(
                    torrent_hashes=list(torrent_hashes), limit=max(0, int(limit_bytes))
                )
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_set_torrent_upload_limit(
        self, torrent_hashes: list[str], limit_bytes: int, **_kw: object
    ) -> APITaskResult:
        """Set per-torrent upload limit (bytes/sec) for selected torrents."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_set_upload_limit(
                    torrent_hashes=list(torrent_hashes), limit=max(0, int(limit_bytes))
                )
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_set_global_download_limit(self, limit_bytes: int, **_kw: object) -> APITaskResult:
        """Set global download limit (bytes/sec)."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.transfer_set_download_limit(limit=max(0, int(limit_bytes)))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_set_global_upload_limit(self, limit_bytes: int, **_kw: object) -> APITaskResult:
        """Set global upload limit (bytes/sec)."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.transfer_set_upload_limit(limit=max(0, int(limit_bytes)))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_toggle_alt_speed_mode(self, **_kw: object) -> APITaskResult:
        """Toggle alternative/global speed-limit mode."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.transfer_toggle_speed_limits_mode()
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_fetch_speed_limits_profile(self, **_kw: object) -> APITaskResult:
        """Fetch normal/alternative speed limits and current alt-speed mode."""
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
                "data": {
                    "normal_dl": max(0, normal_dl),
                    "normal_ul": max(0, normal_ul),
                    "alt_dl": max(0, alt_dl),
                    "alt_ul": max(0, alt_ul),
                    "alt_enabled": bool(mode == 1),
                },
                "elapsed": elapsed,
                "success": True,
            }
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data={}, elapsed=elapsed, success=False, error=str(e))

    def _api_apply_speed_limits_profile(
        self,
        normal_dl: int,
        normal_ul: int,
        alt_dl: int,
        alt_ul: int,
        alt_enabled: bool,
        **_kw: object,
    ) -> APITaskResult:
        """Apply normal/alternative speed limits and desired alt-speed mode."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.transfer_set_download_limit(limit=max(0, int(normal_dl)))
                qb.transfer_set_upload_limit(limit=max(0, int(normal_ul)))

                prefs_raw = qb.app_preferences()
                prefs_current = self._entry_to_dict(prefs_raw)
                alt_dl_key = "alt_dl_limit" if "alt_dl_limit" in prefs_current else "alt_dl"
                alt_ul_key = "alt_up_limit" if "alt_up_limit" in prefs_current else "alt_up"
                qb.app_set_preferences(
                    {
                        alt_dl_key: max(0, int(alt_dl)),
                        alt_ul_key: max(0, int(alt_ul)),
                    }
                )

                current_mode = self._safe_int(qb.transfer_speed_limits_mode(), 0)
                desired_mode = 1 if bool(alt_enabled) else 0
                if current_mode != desired_mode:
                    qb.transfer_toggle_speed_limits_mode()

            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_fetch_app_preferences(self, **_kw: object) -> APITaskResult:
        """Fetch raw qBittorrent application preferences."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                prefs_raw = qb.app_preferences()
            prefs = self._entry_to_dict(prefs_raw)
            elapsed = time.time() - start_time
            return api_task_result(data=prefs, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data={}, elapsed=elapsed, success=False, error=str(e))

    def _api_apply_app_preferences(
        self, updates: dict[str, object], **_kw: object
    ) -> APITaskResult:
        """Apply only changed application preferences."""
        start_time = time.time()
        try:
            normalized_updates = dict(updates or {})
            if not normalized_updates:
                elapsed = time.time() - start_time
                return {"data": {"applied": 0}, "elapsed": elapsed, "success": True}
            with self._create_client() as qb:
                qb.app_set_preferences(prefs=normalized_updates)
            elapsed = time.time() - start_time
            return {
                "data": {"applied": len(normalized_updates)},
                "elapsed": elapsed,
                "success": True,
            }
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return {"data": {"applied": 0}, "elapsed": elapsed, "success": False, "error": str(e)}

    def _api_set_content_priority(
        self,
        torrent_hash: str,
        relative_path: str,
        is_file: bool,
        priority: int,
        **_kw: object,
    ) -> APITaskResult:
        """Set file priority for one file or a whole folder subtree."""
        start_time = time.time()
        try:
            normalized = str(relative_path or "").replace("\\", "/").strip("/")
            if not torrent_hash or not normalized:
                raise ValueError("Missing torrent hash or content path")

            with self._create_client() as qb:
                files = list(qb.torrents_files(torrent_hash=torrent_hash) or [])
                file_ids: list[int] = []
                folder_prefix = f"{normalized}/"
                for file_obj in files:
                    file_name = (
                        str(getattr(file_obj, "name", "") or "").replace("\\", "/").strip("/")
                    )
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
                "data": {"updated_file_count": len(file_ids)},
                "elapsed": elapsed,
                "success": True,
            }
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data={}, elapsed=elapsed, success=False, error=str(e))

    def _api_rename_content_path(
        self,
        torrent_hash: str,
        old_relative_path: str,
        new_relative_path: str,
        is_file: bool,
        **_kw: object,
    ) -> APITaskResult:
        """Rename one file or folder inside a torrent."""
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
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_create_category(
        self,
        name: str,
        save_path: str,
        incomplete_path: str,
        use_incomplete_path: bool,
        **_kw: object,
    ) -> APITaskResult:
        """Create a new category."""
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
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_edit_category(
        self,
        name: str,
        save_path: str,
        incomplete_path: str,
        use_incomplete_path: bool,
        **_kw: object,
    ) -> APITaskResult:
        """Edit one existing category."""
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
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_delete_category(self, name: str, **_kw: object) -> APITaskResult:
        """Delete one category."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_remove_categories(categories=[name])
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_create_tags(self, tags: list[str], **_kw: object) -> APITaskResult:
        """Create one or more tags."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_create_tags(tags=list(tags))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_delete_tags(self, tags: list[str], **_kw: object) -> APITaskResult:
        """Delete one or more tags."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_delete_tags(tags=list(tags))
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_pause_session(self, **_kw: object) -> APITaskResult:
        """Pause all torrents in current qBittorrent session."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_pause(torrent_hashes="all")
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_resume_session(self, **_kw: object) -> APITaskResult:
        """Resume all torrents in current qBittorrent session."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_resume(torrent_hashes="all")
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_delete_torrent(
        self, torrent_hashes: list[str], delete_files: bool, **_kw: object
    ) -> APITaskResult:
        """Delete one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_delete(torrent_hashes=list(torrent_hashes), delete_files=delete_files)
            elapsed = time.time() - start_time
            return api_task_result(data=True, elapsed=elapsed, success=True)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return api_task_result(data=False, elapsed=elapsed, success=False, error=str(e))

    def _api_ban_peers(self, peers: list[str], **_kw: object) -> APITaskResult:
        """Ban one or more peer endpoints (IP:port) globally in qBittorrent."""
        start_time = time.time()
        try:
            endpoints = [
                str(peer or "").strip() for peer in list(peers or []) if str(peer or "").strip()
            ]
            if not endpoints:
                raise ValueError("No peer endpoints provided")
            with self._create_client() as qb:
                qb.transfer_ban_peers(peers=endpoints)
            elapsed = time.time() - start_time
            return {"data": {"peers": endpoints}, "elapsed": elapsed, "success": True}
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            elapsed = time.time() - start_time
            return {"data": {"peers": []}, "elapsed": elapsed, "success": False, "error": str(e)}

    def _set_categories_from_payload(self, payload: object) -> None:
        """Normalize categories payload and update category state/tree."""
        category_details: dict[str, dict[str, object]] = {}
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
        """Resolve default save path for one category from cached details."""
        details = self.category_details.get(str(category_name or ""), {})
        if not isinstance(details, dict):
            return ""
        for key in ("save_path", "savePath"):
            value = str(details.get(key, "") or "").strip()
            if value:
                return value
        return ""

    def _category_incomplete_path_by_name(self, category_name: str) -> str:
        """Resolve incomplete path for one category from cached details."""
        details = self.category_details.get(str(category_name or ""), {})
        if not isinstance(details, dict):
            return ""
        for key in ("download_path", "downloadPath"):
            value = str(details.get(key, "") or "").strip()
            if value:
                return value
        return ""

    def _category_use_incomplete_path_by_name(self, category_name: str) -> bool:
        """Resolve whether incomplete path is enabled for one category."""
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

    def _taxonomy_category_data(self) -> dict[str, dict[str, object]]:
        """Build category metadata mapping for manager dialog."""
        return {
            name: {
                "save_path": self._category_save_path_by_name(name),
                "incomplete_path": self._category_incomplete_path_by_name(name),
                "use_incomplete_path": self._category_use_incomplete_path_by_name(name),
            }
            for name in self.categories
        }

    def _sync_taxonomy_dialog_data(self) -> None:
        """Refresh taxonomy dialog data when open."""
        dialog = self._taxonomy_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_taxonomy_data(self._taxonomy_category_data(), list(self.tags))

    def _on_categories_loaded(self, result: dict) -> None:
        """Handle categories loaded."""
        try:
            if not result.get("success", False):
                error = result.get("error", "Unknown error")
                self._log("ERROR", f"Failed to load categories: {error}", result.get("elapsed", 0))
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
                self.api_queue.add_task("load_tags", self._fetch_tags, self._on_tags_loaded)
                return

            self._set_categories_from_payload(result.get("data", {}))
            self._log("INFO", f"Loaded {len(self.categories)} categories", result.get("elapsed", 0))

            # Load tags next
            self._show_progress("Loading tags...")
            self.api_queue.add_task("load_tags", self._fetch_tags, self._on_tags_loaded)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Exception in _on_categories_loaded: {e}")
            self._hide_progress()
            self._set_status(f"Error loading categories: {e}")

    def _on_tags_loaded(self, result: dict) -> None:
        """Handle tags loaded."""
        try:
            if not result.get("success", False):
                error = result.get("error", "Unknown error")
                self._log("ERROR", f"Failed to load tags: {error}", result.get("elapsed", 0))
                # Continue anyway - load torrents with empty tags
                self.tags = []
                self._update_tag_tree()
                self._sync_taxonomy_dialog_data()
                # Load torrents next
                self._show_progress("Loading torrents...")
                self.api_queue.add_task(
                    "load_torrents", self._fetch_torrents, self._on_torrents_loaded
                )
                return

            self.tags = result.get("data", [])
            self._update_tag_tree()
            self._sync_taxonomy_dialog_data()
            self._log("INFO", f"Loaded {len(self.tags)} tags", result.get("elapsed", 0))

            # Load torrents next
            self._show_progress("Loading torrents...")
            self.api_queue.add_task("load_torrents", self._fetch_torrents, self._on_torrents_loaded)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Exception in _on_tags_loaded: {e}")
            self._hide_progress()
            self._set_status(f"Error loading tags: {e}")

    def _on_torrents_loaded(self, result: dict) -> None:
        """Handle torrents loaded."""
        try:
            if not result.get("success", False):
                self._latest_torrent_fetch_remote_filtered = False
                error = result.get("error", "Unknown error")
                self._log("ERROR", f"Failed to load torrents: {error}", result.get("elapsed", 0))
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
            self._latest_torrent_fetch_remote_filtered = bool(result.get("remote_filtered", False))
            self.all_torrents = result.get("data", [])
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
            self._log("INFO", f"Loaded {len(self.all_torrents)} torrents", result.get("elapsed", 0))
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
                    "INFO", f"Refreshing content cache for {len(refresh_candidates)} torrents"
                )
                self.api_queue.add_task(
                    "refresh_content_cache",
                    self._refresh_content_cache_for_torrents,
                    self._on_content_cache_refreshed,
                    refresh_candidates,
                )
            elif self._suppress_next_cache_save:
                # Nothing to refresh (e.g., zero torrents) - clear one-shot flag.
                self._suppress_next_cache_save = False

            # Apply filters and update table
            self._apply_filters()
            self._select_first_torrent_after_refresh(previous_selected_hash)
            self._hide_progress()
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
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

    def _select_first_torrent_after_refresh(
        self, previous_selected_hash: str | None = None
    ) -> None:
        """Select/restore one row after refresh without overriding a valid existing selection."""
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

    def _on_content_cache_refreshed(self, result: dict[str, object]) -> None:
        """Handle background refresh of cached torrent content trees."""
        try:
            if not result.get("success", False):
                error = result.get("error", "Unknown error")
                self._log(
                    "ERROR", f"Content cache refresh failed: {error}", result.get("elapsed", 0)
                )
                return

            updates = result.get("data", {})
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
                    result.get("elapsed", 0),
                )

                # Re-apply current filters to include newly-cached file matches
                if self.current_file_filter:
                    self._apply_filters()

                # If selected torrent cache got updated, refresh content tab from cache
                selected = getattr(self, "_selected_torrent", None)
                selected_hash = getattr(selected, "hash", "") if selected else ""
                if selected_hash and selected_hash in updates:
                    self._show_cached_torrent_content(selected_hash)

            errors = result.get("errors", {})
            if isinstance(errors, dict) and errors:
                self._log("ERROR", f"Content cache refresh errors for {len(errors)} torrents")
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Exception in _on_content_cache_refreshed: {e}")

    def _on_add_torrent_complete(self, result: dict[str, object]) -> None:
        """Handle torrent add completion."""
        details = result.get("details", {}) if isinstance(result, dict) else {}
        if isinstance(details, dict):
            added_count = self._safe_int(details.get("added_urls", 0), 0) + self._safe_int(
                details.get("added_files", 0), 0
            )
            failed_sources = details.get("failed_sources", [])
            failed_count = len(failed_sources) if isinstance(failed_sources, list) else 0
        else:
            added_count = 0
            failed_count = 0

        final_status_text = ""
        if result.get("success") and result.get("data"):
            status_text = (
                f"Added {added_count} torrent sources"
                if added_count > 1
                else "Torrent added successfully"
            )
            self._log("INFO", status_text, result.get("elapsed", 0))
            final_status_text = status_text
            # Refresh torrent list
            QTimer.singleShot(1000, self._refresh_torrents)
        elif result.get("success") and added_count > 0 and failed_count > 0:
            status_text = f"Added {added_count} sources, {failed_count} failed"
            self._log("ERROR", status_text, result.get("elapsed", 0))
            final_status_text = status_text
            QTimer.singleShot(1000, self._refresh_torrents)
        else:
            error_msg = result.get("error", "Unknown error")
            if (error_msg == "Unknown error") and failed_count > 0:
                error_msg = f"{failed_count} source(s) failed"
            self._log("ERROR", f"Failed to add torrent: {error_msg}", result.get("elapsed", 0))
            final_status_text = f"Failed to add torrent: {error_msg}"
        self._hide_progress()
        if final_status_text:
            self._set_status(final_status_text)

    def _on_apply_selected_torrent_edits_done(self, result: dict) -> None:
        """Handle completion of selected torrent edit apply action."""
        if result.get("success"):
            self._log("INFO", "Torrent edits applied", result.get("elapsed", 0))
            self._set_status("Torrent edits applied")
            QTimer.singleShot(500, self._refresh_torrents)
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"Failed to apply torrent edits: {error}", result.get("elapsed", 0))
            self._set_status(f"Failed to apply torrent edits: {error}")
        self._hide_progress()

    def _on_task_completed(self, task_name: str, result: APITaskResult) -> None:
        """Handle task completion."""
        self._maybe_bump_auto_refresh_interval_from_api_elapsed(task_name, result)
        self._log("DEBUG", f"Task completed: {task_name}")

    def _maybe_bump_auto_refresh_interval_from_api_elapsed(
        self, task_name: str, result: object
    ) -> None:
        """Increase auto-refresh interval when one API task exceeds current interval."""
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
        """Handle task failure."""
        if task_name == "refresh_torrents":
            self._set_refresh_torrents_in_progress(False)
        self._log("ERROR", f"Task failed: {task_name} - {error_msg}")
        self._set_status(f"Error: {error_msg}")
        self._hide_progress()

    def _on_task_cancelled(self, task_name: str) -> None:
        """Handle task cancellation."""
        if task_name == "refresh_torrents":
            self._set_refresh_torrents_in_progress(False)
        self._log("INFO", f"Task cancelled: {task_name}")

    def _refresh_torrents(self) -> None:
        """Refresh torrent list."""
        if self._refresh_torrents_in_progress:
            self._log("DEBUG", "Refresh skipped: refresh_torrents already in progress")
            return

        # Avoid auto/manual refresh canceling other in-flight user/API operations.
        active_task = str(getattr(self.api_queue, "current_task_name", "") or "").strip()
        pending_task = getattr(self.api_queue, "pending_task", None)
        pending_name = (
            str(pending_task[0]).strip() if isinstance(pending_task, tuple) and pending_task else ""
        )
        queue_busy_with_non_refresh = bool(getattr(self.api_queue, "current_worker", None)) and (
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
                "refresh_torrents", self._fetch_torrents, self._on_torrents_loaded
            )
        except RECOVERABLE_CONTROLLER_EXCEPTIONS:
            self._set_refresh_torrents_in_progress(False)
            raise
