"""Feature controllers for MainWindow composition."""

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QFontDatabase,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..constants import (
    DEFAULT_REFRESH_INTERVAL,
)
from ..dialogs import (
    AddTorrentDialog,
    AppPreferencesDialog,
    FriendlyAddPreferencesDialog,
    SpeedLimitsDialog,
    TaxonomyManagerDialog,
)
from ..types import APITaskResult
from ..utils import (
    _normalize_instance_counter,
    resolve_instance_lock_file_path,
)
from .base import RECOVERABLE_CONTROLLER_EXCEPTIONS, WindowControllerBase


class ActionsTaxonomyController(WindowControllerBase):
    """Handle user actions, taxonomy flows, and preference dialogs."""

    @staticmethod
    def _build_new_instance_command(
        config_file_path: str, instance_counter: int | None = None
    ) -> list[str]:
        """Build command line used to spawn one new application instance."""
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
        instance_counter: int | None = None,
    ) -> None:
        """Spawn one new process instance with the provided config path."""
        try:
            command = self._build_new_instance_command(config_file_path, instance_counter)
            subprocess.Popen(command)
            self._log("INFO", f"Launched new instance: {' '.join(command)}")
            self._set_status(f"Launched new instance: {Path(config_file_path).name}")
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as e:
            self._log("ERROR", f"Failed to launch new instance: {e}")
            self._set_status(f"Failed to launch new instance: {e}")

    def _launch_new_instance_current_config(self) -> None:
        """Launch a new app instance using the currently loaded config file."""
        raw_config_path = str(
            (self.config.get("_config_file_path") if isinstance(self.config, dict) else "") or ""
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
        """Launch a new app instance after selecting a .toml config file."""
        current_config_path = str(
            (self.config.get("_config_file_path") if isinstance(self.config, dict) else "") or ""
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
        """Show add torrent dialog."""
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
        self._add_torrent_dialog = cast(AddTorrentDialog | None, dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_add_torrent_dialog_closed(self, _result: int) -> None:
        """Clear cached Add Torrent dialog reference."""
        self._add_torrent_dialog = None

    def _on_add_torrent_dialog_accepted(self) -> None:
        """Queue torrent add task when Add Torrent dialog is accepted."""
        dialog = self._add_torrent_dialog
        if dialog is None:
            return
        torrent_data = dict(getattr(dialog, "torrent_data", {}) or {})
        dialog.torrent_data = None
        if torrent_data:
            self._log("INFO", "Adding torrent...")
            self._show_progress("Adding torrent...")
            self.api_queue.add_task(
                "add_torrent", self._add_torrent_api, self._on_add_torrent_complete, torrent_data
            )

    @staticmethod
    def _sanitize_export_filename(name: object, fallback: str = "torrent") -> str:
        """Sanitize one torrent name for safe local .torrent filenames."""
        text = str(name or "").strip()
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
        text = text.strip().strip(".")
        text = re.sub(r"\s+", " ", text)
        return text or fallback

    @staticmethod
    def _unique_export_file_path(
        export_dir: Path, base_name: str, torrent_hash: str, used_names: set
    ) -> Path:
        """Return a unique destination file path for one exported torrent file."""
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

    def _build_selected_torrent_name_map(self, torrent_hashes: list[str]) -> dict[str, str]:
        """Build hash->name mapping for selected torrents to name exported files."""
        name_map: dict[str, str] = {}
        for torrent_hash in list(torrent_hashes or []):
            torrent = self._find_torrent_by_hash(str(torrent_hash or ""))
            name_map[str(torrent_hash or "")] = str(getattr(torrent, "name", "") or "")
        return name_map

    def _export_selected_torrents(self) -> None:
        """Prompt destination directory and export selected torrents as .torrent files."""
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
        progress_text = "Exporting torrent..." if count == 1 else f"Exporting {count} torrents..."
        self._show_progress(progress_text)
        self.api_queue.add_task(
            "export_selected_torrents",
            self._api_export_torrents,
            self._on_export_selected_torrents_done,
            torrent_hashes,
            export_dir,
            name_map,
        )

    def _on_export_selected_torrents_done(self, result: dict) -> None:
        """Handle completion of selected-torrent export action."""
        data = result.get("data", {}) or {}
        exported = list(data.get("exported", []) or [])
        failed = dict(data.get("failed", {}) or {})
        exported_count = len(exported)
        failed_count = len(failed)
        if result.get("success"):
            self._log(
                "INFO",
                f"Export Torrent succeeded ({exported_count} file(s))",
                result.get("elapsed", 0),
            )
            self._set_status(
                "Exported 1 torrent file"
                if exported_count == 1
                else f"Exported {exported_count} torrent files"
            )
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"Export Torrent failed: {error}", result.get("elapsed", 0))
            if exported_count > 0:
                self._set_status(f"Exported {exported_count} torrent files, {failed_count} failed")
            else:
                self._set_status(f"Export Torrent failed: {error}")
        self._hide_progress()

    def _find_torrent_by_hash(self, torrent_hash: str) -> object | None:
        """Find one torrent object by hash, preferring the currently filtered list."""
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
    def _expand_local_path(raw_path: object) -> Path | None:
        """Expand user/env vars for a local path string."""
        text = str(raw_path or "").strip().strip('"').strip("'")
        if not text:
            return None
        expanded = os.path.expandvars(os.path.expanduser(text))
        if not expanded:
            return None
        return Path(expanded)

    def _resolve_local_torrent_directory(self, torrent: object) -> Path | None:
        """Return an existing local directory for a torrent, if available."""
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
        """Open selected torrent local directory when it exists on this machine."""
        selected_hashes = self._get_selected_torrent_hashes()
        if len(selected_hashes) != 1:
            if selected_hashes:
                self._set_status("Select one torrent to open its local directory")
            return

        self._open_torrent_location_by_hash(selected_hashes[0])

    def _open_torrent_location_by_hash(self, torrent_hash: str) -> None:
        """Open local torrent directory for one hash when available."""
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
        """Open local torrent directory for the row that was double-clicked."""
        if item is None:
            return
        hash_item = self.tbl_torrents.item(item.row(), 0)
        torrent_hash = hash_item.text().strip() if hash_item else ""
        self._open_torrent_location_by_hash(torrent_hash)

    def _on_content_tree_item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        """Open activated content-tree item (Enter/double-click behavior)."""
        self._open_selected_content_path(item=item)

    def _open_selected_content_path(self, item: QTreeWidgetItem | None = None) -> None:
        """Open selected content-tree item in the local filesystem when available."""
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
        rel_path = Path(
            *[part for part in normalized_rel.split("/") if part not in ("", ".", "..")]
        )
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

    def _get_selected_torrent_hash(self) -> str | None:
        """Get the hash of the currently selected torrent, or None."""
        hashes = self._get_selected_torrent_hashes()
        if not hashes:
            return None
        return hashes[0]

    def _get_selected_torrent_hashes(self) -> list[str]:
        """Get unique selected torrent hashes preserving current row order."""
        hashes: list[str] = []
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

    def _on_torrent_action_done(self, action_name: str, result: dict) -> None:
        """Generic callback for pause/resume/delete actions."""
        if result.get("success"):
            self._log("INFO", f"{action_name} succeeded", result.get("elapsed", 0))
            QTimer.singleShot(500, self._refresh_torrents)
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"{action_name} failed: {error}", result.get("elapsed", 0))
            self._set_status(f"{action_name} failed: {error}")
        self._hide_progress()

    def _on_ban_peer_done(self, endpoint: str, result: dict) -> None:
        """Callback for peer ban action."""
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
        """Queue a bulk action for currently selected torrents."""
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        count = len(torrent_hashes)
        self._log("INFO", f"{action_name}: {count} torrent(s)")
        self._show_progress(
            singular_progress if count == 1 else plural_progress.format(count=count)
        )
        self.api_queue.add_task(
            task_name,
            api_method,
            lambda r: self._on_torrent_action_done(action_name, r),
            torrent_hashes,
        )

    def _pause_torrent(self) -> None:
        """Pause selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "pause_torrent",
            self._api_pause_torrent,
            "Pause",
            "Pausing torrent...",
            "Pausing {count} torrents...",
        )

    def _resume_torrent(self) -> None:
        """Resume selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "resume_torrent",
            self._api_resume_torrent,
            "Resume",
            "Resuming torrent...",
            "Resuming {count} torrents...",
        )

    def _force_start_torrent(self) -> None:
        """Force-start selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "force_start_torrent",
            self._api_force_start_torrent,
            "Force Start",
            "Force-starting torrent...",
            "Force-starting {count} torrents...",
        )

    def _recheck_torrent(self) -> None:
        """Recheck selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "recheck_torrent",
            self._api_recheck_torrent,
            "Recheck",
            "Rechecking torrent...",
            "Rechecking {count} torrents...",
        )

    def _increase_torrent_priority(self) -> None:
        """Increase queue priority for selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "increase_torrent_priority",
            self._api_increase_torrent_priority,
            "Increase Priority",
            "Increasing queue priority...",
            "Increasing queue priority for {count} torrents...",
        )

    def _decrease_torrent_priority(self) -> None:
        """Decrease queue priority for selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "decrease_torrent_priority",
            self._api_decrease_torrent_priority,
            "Decrease Priority",
            "Decreasing queue priority...",
            "Decreasing queue priority for {count} torrents...",
        )

    def _top_torrent_priority(self) -> None:
        """Set top queue priority for selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "top_torrent_priority",
            self._api_top_torrent_priority,
            "Top Priority",
            "Setting top queue priority...",
            "Setting top queue priority for {count} torrents...",
        )

    def _minimum_torrent_priority(self) -> None:
        """Set minimum queue priority for selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "minimum_torrent_priority",
            self._api_minimum_torrent_priority,
            "Minimum Priority",
            "Setting minimum queue priority...",
            "Setting minimum queue priority for {count} torrents...",
        )

    @staticmethod
    def _kib_to_bytes(limit_kib: int) -> int:
        """Convert KiB/s to bytes/s for API calls."""
        return max(0, int(limit_kib)) * 1024

    @staticmethod
    def _bytes_to_kib(limit_bytes: object) -> int:
        """Convert bytes/s to KiB/s for UI controls."""
        try:
            return max(0, int(cast(Any, limit_bytes))) // 1024
        except (TypeError, ValueError, OverflowError):
            return 0

    def _prompt_limit_kib(self, title: str, label: str) -> int | None:
        """Prompt for a speed limit in KiB/s (0 means unlimited)."""
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
        """Prompt and set download limit for selected torrents."""
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
        self._log("INFO", f"Setting download limit for {count} torrent(s) to {limit_kib} KiB/s")

    def _set_torrent_upload_limit(self) -> None:
        """Prompt and set upload limit for selected torrents."""
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
        self._log("INFO", f"Setting upload limit for {count} torrent(s) to {limit_kib} KiB/s")

    def _on_global_bandwidth_action_done(self, action_name: str, result: dict) -> None:
        """Handle global bandwidth action completion."""
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
        """Open application preferences editor dialog."""
        if self._app_preferences_dialog is not None and self._app_preferences_dialog.isVisible():
            self._app_preferences_dialog.raise_()
            self._app_preferences_dialog.activateWindow()
            self._request_app_preferences_refresh()
            return

        dialog = AppPreferencesDialog(self)
        dialog.apply_requested.connect(self._on_app_preferences_apply_requested)
        dialog.finished.connect(self._on_app_preferences_dialog_closed)
        self._app_preferences_dialog = cast(AppPreferencesDialog | None, dialog)
        dialog.show()
        self._request_app_preferences_refresh()

    def _on_app_preferences_dialog_closed(self, _result: int) -> None:
        """Clear cached app-preferences dialog reference."""
        self._app_preferences_dialog = None

    def _set_app_preferences_dialog_busy(self, busy: bool, message: str = "") -> None:
        """Set app-preferences dialog busy state when open."""
        dialog = self._app_preferences_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _request_app_preferences_refresh(self) -> None:
        """Load raw app preferences into editor dialog."""
        self._show_progress("Loading app preferences...")
        self._set_app_preferences_dialog_busy(True, "Loading application preferences...")
        self.api_queue.add_task(
            "fetch_app_preferences",
            self._api_fetch_app_preferences,
            self._on_app_preferences_loaded,
        )

    def _on_app_preferences_loaded(self, result: dict) -> None:
        """Populate app-preferences dialog from API response."""
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

    def _on_app_preferences_apply_requested(self, changed_preferences: dict[str, object]) -> None:
        """Queue changed app preferences from editor dialog."""
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

    def _on_app_preferences_applied(self, result: dict) -> None:
        """Handle completion of app preferences apply."""
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
        """Open friendly editor for commonly used app preferences."""
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
        self._friendly_add_preferences_dialog = cast(FriendlyAddPreferencesDialog | None, dialog)
        dialog.show()
        self._request_friendly_add_preferences_refresh()

    def _on_friendly_add_preferences_dialog_closed(self, _result: int) -> None:
        """Clear cached friendly add-preferences dialog reference."""
        self._friendly_add_preferences_dialog = None

    def _set_friendly_add_preferences_dialog_busy(self, busy: bool, message: str = "") -> None:
        """Set busy state for friendly add-preferences dialog when open."""
        dialog = self._friendly_add_preferences_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _request_friendly_add_preferences_refresh(self) -> None:
        """Load app preferences into friendly add-preferences editor."""
        self._show_progress("Loading add preferences...")
        self._set_friendly_add_preferences_dialog_busy(True, "Loading add preferences...")
        self.api_queue.add_task(
            "fetch_friendly_add_preferences",
            self._api_fetch_app_preferences,
            self._on_friendly_add_preferences_loaded,
        )

    def _on_friendly_add_preferences_loaded(self, result: dict) -> None:
        """Populate friendly add-preferences dialog from API response."""
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

    def _on_friendly_add_preferences_apply_requested(
        self, changed_preferences: dict[str, object]
    ) -> None:
        """Queue changed friendly add-preferences values for API apply."""
        updates = dict(changed_preferences or {})
        if not updates:
            self._set_status("No add preference changes to apply")
            self._set_friendly_add_preferences_dialog_busy(
                False, "No changed preferences to apply."
            )
            return
        self._show_progress("Applying add preferences...")
        self._set_friendly_add_preferences_dialog_busy(True, "Applying add preferences...")
        self.api_queue.add_task(
            "apply_friendly_add_preferences",
            self._api_apply_app_preferences,
            self._on_friendly_add_preferences_applied,
            updates,
        )

    def _on_friendly_add_preferences_applied(self, result: dict) -> None:
        """Handle completion of friendly add-preferences apply."""
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
        """Open speed limits manager dialog."""
        if self._speed_limits_dialog is not None and self._speed_limits_dialog.isVisible():
            self._speed_limits_dialog.raise_()
            self._speed_limits_dialog.activateWindow()
            self._request_speed_limits_profile()
            return

        dialog = SpeedLimitsDialog(self)
        dialog.refresh_requested.connect(self._request_speed_limits_profile)
        dialog.apply_requested.connect(self._on_speed_limits_apply_requested)
        dialog.finished.connect(self._on_speed_limits_dialog_closed)
        self._speed_limits_dialog = cast(SpeedLimitsDialog | None, dialog)
        dialog.show()
        self._request_speed_limits_profile()

    def _on_speed_limits_dialog_closed(self, _result: int) -> None:
        """Clear cached speed limits dialog reference."""
        self._speed_limits_dialog = None

    def _set_speed_limits_dialog_busy(self, busy: bool, message: str = "") -> None:
        """Set speed dialog controls busy state when dialog is open."""
        dialog = self._speed_limits_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _request_speed_limits_profile(self) -> None:
        """Load current speed limits into manager dialog."""
        self._show_progress("Loading speed limits...")
        self._set_speed_limits_dialog_busy(True, "Loading speed limits...")
        self.api_queue.add_task(
            "fetch_speed_limits_profile",
            self._api_fetch_speed_limits_profile,
            self._on_speed_limits_profile_loaded,
        )

    def _on_speed_limits_profile_loaded(self, result: dict) -> None:
        """Populate speed limits dialog from API response."""
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
        """Queue apply operation from speed limits dialog values."""
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

    def _on_speed_limits_profile_applied(self, result: dict) -> None:
        """Handle completion of speed limits apply."""
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
        """Prompt and set global download limit."""
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
        """Prompt and set global upload limit."""
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
        """Toggle alternative speed mode."""
        self._show_progress("Toggling alternative speed mode...")
        self.api_queue.add_task(
            "toggle_alt_speed_mode",
            self._api_toggle_alt_speed_mode,
            lambda r: self._on_global_bandwidth_action_done("Toggle Alternative Speed Mode", r),
        )

    def _get_selected_content_item_info(self) -> dict[str, object] | None:
        """Return selected content tree item metadata."""
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

    def _selected_torrent_hash_for_content_action(self) -> str | None:
        """Return currently selected torrent hash for content actions."""
        torrent = getattr(self, "_selected_torrent", None)
        torrent_hash = str(getattr(torrent, "hash", "") or "").strip() if torrent else ""
        if not torrent_hash:
            self._set_status("Select exactly one torrent first")
            return None
        return torrent_hash

    def _on_content_action_done(self, action_name: str, result: dict) -> None:
        """Callback for content actions (priority/rename)."""
        if result.get("success"):
            self._log("INFO", f"{action_name} succeeded", result.get("elapsed", 0))
            QTimer.singleShot(500, self._refresh_torrents)
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"{action_name} failed: {error}", result.get("elapsed", 0))
            self._set_status(f"{action_name} failed: {error}")
        self._hide_progress()

    def _set_selected_content_priority(self, priority: int) -> None:
        """Set priority for selected content item (file/folder)."""
        torrent_hash = self._selected_torrent_hash_for_content_action()
        if not torrent_hash:
            return
        info = self._get_selected_content_item_info()
        if not info:
            return

        priority_name = {0: "Skip", 1: "Normal", 6: "High", 7: "Maximum"}.get(
            priority, str(priority)
        )
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
        """Rename selected file/folder in content tree via API."""
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

    def _prompt_content_rename_name(self, label: str, old_name: str) -> tuple[str, bool]:
        """Prompt for a new content file/folder name with persistent dialog size."""
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
            except (TypeError, RuntimeError):
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
        except (TypeError, RuntimeError):
            pass

        if not accepted:
            return "", False
        return str(txt_name.text() or ""), True

    def _on_taxonomy_action_done(self, action_name: str, result: dict) -> None:
        """Callback for create/edit/delete category/tag actions."""
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
        """Set taxonomy dialog busy state when open."""
        dialog = self._taxonomy_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _reload_taxonomy_data(self, action_name: str) -> None:
        """Reload categories+tags after taxonomy mutation."""
        self.api_queue.add_task(
            "reload_categories_for_taxonomy",
            self._fetch_categories,
            lambda r: self._on_taxonomy_categories_reloaded(action_name, r),
        )

    def _on_taxonomy_categories_reloaded(self, action_name: str, result: dict) -> None:
        """Handle category reload in taxonomy post-action chain."""
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

    def _on_taxonomy_tags_reloaded(self, action_name: str, result: dict) -> None:
        """Finalize taxonomy reload and update UI/dialog."""
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
        *args: object,
    ) -> None:
        """Queue taxonomy mutation from manager dialog."""
        self._show_progress(f"{action_name}...")
        self._set_taxonomy_dialog_busy(True, f"{action_name}...")
        self.api_queue.add_task(
            task_name,
            api_method,
            lambda r: self._on_taxonomy_action_done(action_name, r),
            *args,
        )

    def _show_taxonomy_manager(self) -> None:
        """Open taxonomy manager dialog (categories + tags)."""
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
        self._taxonomy_dialog = cast(TaxonomyManagerDialog | None, dialog)
        dialog.show()

    def _on_taxonomy_dialog_closed(self, _result: int) -> None:
        """Clear dialog reference when closed."""
        self._taxonomy_dialog = None

    def _on_taxonomy_create_category_requested(
        self,
        name: str,
        save_path: str,
        incomplete_path: str,
        use_incomplete_path: bool,
    ) -> None:
        """Handle create-category request from manager dialog."""
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
        """Handle edit-category request from manager dialog."""
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
        """Handle delete-category request from manager dialog."""
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

    def _on_taxonomy_create_tags_requested(self, tags: list[str]) -> None:
        """Handle create-tags request from manager dialog."""
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

    def _on_taxonomy_delete_tags_requested(self, tags: list[str]) -> None:
        """Handle delete-tags request from manager dialog."""
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
        """Pause all torrents in current session."""
        self._log("INFO", "Pausing session")
        self._show_progress("Pausing session...")
        self.api_queue.add_task(
            "pause_session",
            self._api_pause_session,
            lambda r: self._on_torrent_action_done("Pause Session", r),
        )

    def _resume_session(self) -> None:
        """Resume all torrents in current session."""
        self._log("INFO", "Resuming session")
        self._show_progress("Resuming session...")
        self.api_queue.add_task(
            "resume_session",
            self._api_resume_session,
            lambda r: self._on_torrent_action_done("Resume Session", r),
        )

    def _queue_delete_torrents(
        self, torrent_hashes: list[str], delete_files: bool, action_name: str, progress_text: str
    ) -> None:
        """Queue deletion for selected torrent(s) with explicit delete-files mode."""
        self._log("INFO", f"{action_name}: {len(torrent_hashes)} torrent(s) (files={delete_files})")
        self._show_progress(progress_text)
        task_name = "delete_torrent_with_data" if delete_files else "delete_torrent"
        self.api_queue.add_task(
            task_name,
            self._api_delete_torrent,
            lambda r: self._on_torrent_action_done(action_name, r),
            torrent_hashes,
            delete_files,
        )

    def _remove_torrent(self) -> None:
        """Remove selected torrent(s) and keep data on disk."""
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        reply = QMessageBox.question(
            self,
            "Remove Torrent(s)",
            f"Remove {len(torrent_hashes)} selected torrent(s) from qBittorrent and keep data on disk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._queue_delete_torrents(
            torrent_hashes,
            delete_files=False,
            action_name="Remove",
            progress_text="Removing torrent..."
            if len(torrent_hashes) == 1
            else f"Removing {len(torrent_hashes)} torrents...",
        )

    def _remove_torrent_and_delete_data(self) -> None:
        """Remove selected torrent(s) and delete data from disk."""
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        reply = QMessageBox.question(
            self,
            "Remove And Delete Data",
            f"Remove {len(torrent_hashes)} selected torrent(s) and delete data from disk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
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
            ),
        )

    def _remove_torrent_no_confirmation(self) -> None:
        """Remove selected torrent(s) and keep data on disk, without confirmation."""
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        self._queue_delete_torrents(
            torrent_hashes,
            delete_files=False,
            action_name="Remove (No Confirmation)",
            progress_text="Removing torrent..."
            if len(torrent_hashes) == 1
            else f"Removing {len(torrent_hashes)} torrents...",
        )

    def _remove_torrent_and_delete_data_no_confirmation(self) -> None:
        """Remove selected torrent(s) and delete data, without confirmation."""
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
        """Delete selected torrent(s) with confirmation."""
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        reply = QMessageBox.question(
            self,
            "Delete Torrent(s)",
            f"Delete {len(torrent_hashes)} selected torrent(s) and their files from disk?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return
        delete_files = reply == QMessageBox.StandardButton.Yes
        self._queue_delete_torrents(
            torrent_hashes,
            delete_files=delete_files,
            action_name="Delete",
            progress_text="Deleting torrent..."
            if len(torrent_hashes) == 1
            else f"Deleting {len(torrent_hashes)} torrents...",
        )

    def _clear_cache_and_refresh(self) -> None:
        """Clear local content cache and refresh torrents."""
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
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Failed to clear cache: {e}")
            self._set_status(f"Failed to clear cache: {e}")

        self._refresh_torrents()

    def _reset_view_defaults(self) -> None:
        """Reset view/layout/filter/refresh options back to startup defaults."""
        reply = QMessageBox.question(
            self,
            "Reset View",
            "Reset view to defaults?\n\n"
            "This resets column widths, splitter positions, refresh interval, "
            "auto-refresh, status/category/tag filters, and sort order.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
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
                f"interval={self.refresh_interval}s)",
            )
            self._set_status("View reset to defaults")
            self._refresh_torrents()
        except (RuntimeError, TypeError, ValueError, OSError, AttributeError) as e:
            self._log("ERROR", f"Failed to reset view defaults: {e}")
            self._set_status(f"Failed to reset view: {e}")

    def _open_log_file(self) -> None:
        """Open the log file in the OS default application."""
        log_path = os.path.abspath(self.log_file_path)
        try:
            if not self._open_file_in_default_app(log_path):
                raise RuntimeError("OS failed to open log file")
        except (RuntimeError, OSError, ValueError) as e:
            self._log("ERROR", f"Failed to open log file: {e}")
            self._set_status(f"Failed to open log file: {e}")

    def _set_auto_refresh_interval(self) -> None:
        """Prompt user to set auto-refresh frequency in seconds."""
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
        except (RuntimeError, TypeError, ValueError, AttributeError) as e:
            self._log("ERROR", f"Failed to set auto-refresh interval: {e}")
            self._set_status(f"Failed to set auto-refresh interval: {e}")

    def _toggle_auto_refresh(self, checked: bool) -> None:
        """Toggle auto-refresh."""
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
        """Enable/disable comprehensive debug logging including API calls/responses."""
        self.debug_logging_enabled = bool(checked)
        if self.debug_logging_enabled:
            self._log("INFO", "Debug logging enabled (API calls/responses)")
            self._set_status("Debug logging enabled")
        else:
            self._log("INFO", "Debug logging disabled")
            self._set_status("Debug logging disabled")
        self._save_settings()

    def _toggle_human_readable(self, checked: bool) -> None:
        """Toggle display of size/speed values between human-readable and bytes."""
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
        """Build full about dialog text including runtime file paths."""
        instance_text = str(getattr(self, "instance_id", "") or "").strip()
        if not instance_text:
            instance_text = "N/A"

        try:
            ini_path = str(self._settings_ini_path())
        except (OSError, RuntimeError, ValueError):
            ini_path = "N/A"

        cache_path = str(getattr(self, "cache_file_path", "") or "N/A")
        cache_tmp_path = (
            str(Path(f"{cache_path}.tmp")) if cache_path and cache_path != "N/A" else "N/A"
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
            lock_path = str(resolve_instance_lock_file_path(instance_text, instance_counter))

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
        """Show about dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("About qBiremo Enhanced")
        dialog.resize(1100, 360)

        layout = QVBoxLayout(dialog)
        txt_about = QTextEdit(dialog)
        txt_about.setReadOnly(True)
        txt_about.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        txt_about.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        txt_about.setPlainText(self._about_dialog_text())
        layout.addWidget(txt_about, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()
