"""Feature controllers for MainWindow composition."""

import logging
import time
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import (
    QCloseEvent,
    QKeyEvent,
)
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
)
from threep_commons.formatters import (
    format_size_mode,
    format_speed_mode,
)

from ..constants import (
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_TITLE_BAR_SPEED_FORMAT,
)
from ..dialogs import (
    SessionTimelineDialog,
    TrackerHealthDialog,
)
from .base import RECOVERABLE_CONTROLLER_EXCEPTIONS, WindowControllerBase, logger

if TYPE_CHECKING:
    from ..models.torrent import (
        SessionTimelineSample,
    )


class SessionUiController(WindowControllerBase):
    """Manage status/progress UI, timeline widgets, and lifecycle hooks."""

    def _sync_auto_refresh_timer_state(self) -> None:
        """Start/stop refresh timer based on settings and current details context."""
        if not hasattr(self, "refresh_timer"):
            return
        should_run = (
            bool(self.auto_refresh_enabled)
            and not self._is_torrent_edit_tab_active()
            and not bool(self._refresh_torrents_in_progress)
        )
        interval_seconds = max(
            1, self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL)
        )
        if should_run:
            self.refresh_timer.start(interval_seconds * 1000)
        else:
            self.refresh_timer.stop()

    def _set_refresh_torrents_in_progress(self, in_progress: bool) -> None:
        """Set refresh-in-progress state and re-evaluate auto-refresh timer."""
        active = bool(in_progress)
        if self._refresh_torrents_in_progress == active:
            return
        self._refresh_torrents_in_progress = active
        self._sync_auto_refresh_timer_state()

    def _update_auto_refresh_action_text(self) -> None:
        """Refresh auto-refresh menu label to include current interval."""
        if not hasattr(self, "action_auto_refresh"):
            return
        interval_seconds = max(
            1, self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL)
        )
        self.action_auto_refresh.setText(f"Enable A&uto-Refresh ({interval_seconds})")

    def _record_session_timeline_sample(self, alt_enabled: bool | None = None) -> None:
        """Record one session timeline sample from current torrent list."""
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

        alt_mode = (
            self._last_alt_speed_mode if alt_enabled is None else bool(alt_enabled)
        )
        sample: SessionTimelineSample = {
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
        """Open session timeline dialog."""
        if (
            self._session_timeline_dialog is not None
            and self._session_timeline_dialog.isVisible()
        ):
            self._session_timeline_dialog.raise_()
            self._session_timeline_dialog.activateWindow()
            self._session_timeline_dialog.set_samples(
                list(self.session_timeline_history)
            )
            return

        dialog = SessionTimelineDialog(cast("QWidget | None", self))
        dialog.refresh_requested.connect(self._refresh_torrents)
        dialog.clear_requested.connect(self._clear_session_timeline_history)
        dialog.finished.connect(self._on_session_timeline_dialog_closed)
        dialog.set_samples(list(self.session_timeline_history))
        self._session_timeline_dialog = cast("SessionTimelineDialog | None", dialog)
        dialog.show()

    def _on_session_timeline_dialog_closed(self, _result: int) -> None:
        """Clear timeline dialog reference on close."""
        self._session_timeline_dialog = None

    def _clear_session_timeline_history(self) -> None:
        """Clear stored session timeline samples."""
        self.session_timeline_history.clear()
        dialog = self._session_timeline_dialog
        if dialog is not None and dialog.isVisible():
            dialog.set_samples([])

    def _show_tracker_health_dashboard(self) -> None:
        """Open tracker health dashboard dialog."""
        if (
            self._tracker_health_dialog is not None
            and self._tracker_health_dialog.isVisible()
        ):
            self._tracker_health_dialog.raise_()
            self._tracker_health_dialog.activateWindow()
            self._request_tracker_health_refresh()
            return

        dialog = TrackerHealthDialog(cast("QWidget | None", self))
        dialog.refresh_requested.connect(self._request_tracker_health_refresh)
        dialog.finished.connect(self._on_tracker_health_dialog_closed)
        self._tracker_health_dialog = cast("TrackerHealthDialog | None", dialog)
        dialog.show()
        self._request_tracker_health_refresh()

    def _on_tracker_health_dialog_closed(self, _result: int) -> None:
        """Clear tracker-health dialog reference on close."""
        self._tracker_health_dialog = None

    def _set_tracker_health_dialog_busy(self, busy: bool, message: str = "") -> None:
        """Set tracker-health dialog busy state."""
        dialog = self._tracker_health_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _request_tracker_health_refresh(self) -> None:
        """Queue tracker health aggregation for all currently known torrents."""
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

    def _on_tracker_health_loaded(self, result: dict[str, object]) -> None:
        """Render tracker health dashboard data."""
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
        """Show progress indicator."""
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self._set_status(message)

    def _hide_progress(self) -> None:
        """Hide progress indicator."""
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self._set_status("Ready")

    def _set_status(self, message: str) -> None:
        """Set status bar message."""
        self.lbl_status.setText(message)

    def _update_statusbar_transfer_summary(self) -> None:
        """Render aggregate transfer summary in the status bar."""
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

        down_speed_text = (
            format_speed_mode(total_down_speed, self.display_speed_mode) or "0"
        )
        up_speed_text = (
            format_speed_mode(total_up_speed, self.display_speed_mode) or "0"
        )

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

        session_down_text = format_size_mode(
            total_session_download, self.display_size_mode
        )
        session_up_text = format_size_mode(total_session_upload, self.display_size_mode)
        dht_label.setText(f"DHT: {max(0, self._safe_int(self._last_dht_nodes, 0))}")
        down_label.setText(
            f"D: {down_speed_text} [{down_limit_text}] ({session_down_text})"
        )
        up_label.setText(f"U: {up_speed_text} [{up_limit_text}] ({session_up_text})")

    def _bring_to_front_startup(self) -> None:
        """Bring the main window to front shortly after startup."""
        try:
            self.raise_()
            self.activateWindow()
        except RuntimeError:
            pass

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Handle Enter in content tree consistently across Qt styles/platforms."""
        key_event = cast("QKeyEvent", event)
        if (
            watched is getattr(self, "tree_files", None)
            and event.type() == QEvent.Type.KeyPress
            and key_event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self._open_selected_content_path()
            return True
        return QMainWindow.eventFilter(self, watched, event)

    def _update_window_title_speeds(self) -> None:
        """Show aggregate up/down speeds in the window title."""
        try:
            total_down = 0
            total_up = 0
            for torrent in self.all_torrents:
                total_down += self._safe_int(getattr(torrent, "dlspeed", 0), 0)
                total_up += self._safe_int(getattr(torrent, "upspeed", 0), 0)

            up_text = format_speed_mode(total_up, self.display_speed_mode) or "0"
            down_text = format_speed_mode(total_down, self.display_speed_mode) or "0"
            self.setWindowTitle(
                self.title_bar_speed_format.format(
                    up_text=up_text,
                    down_text=down_text,
                )
            )
        except (AttributeError, TypeError, ValueError, KeyError, IndexError):
            # Keep title stable even if malformed data appears.
            self.setWindowTitle(
                DEFAULT_TITLE_BAR_SPEED_FORMAT.format(
                    up_text="0",
                    down_text="0",
                )
            )

    @staticmethod
    def _safe_debug_repr(value: object, max_len: int | None = 2000) -> str:
        """Build bounded repr for debug log messages."""
        try:
            text = repr(value)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS:
            text = f"<unrepr {type(value).__name__}>"
        if isinstance(max_len, int) and max_len > 0 and len(text) > max_len:
            return text[:max_len] + "...<truncated>"
        return text

    def _debug_log_api_call(
        self, method_name: str, args: tuple[object, ...], kwargs: dict[str, object]
    ) -> None:
        """Log one qBittorrent API call invocation when debug logging is enabled."""
        if not self.debug_logging_enabled:
            return
        logger.debug(
            "[API CALL] %s args=%s kwargs=%s",
            str(method_name),
            self._safe_debug_repr(args),
            self._safe_debug_repr(kwargs),
        )

    def _debug_log_api_response(
        self, method_name: str, result: object, elapsed: float
    ) -> None:
        """Log one qBittorrent API call response when debug logging is enabled."""
        if not self.debug_logging_enabled:
            return
        logger.debug(
            "[API RESP] %s elapsed=%.3fs result=%s",
            str(method_name),
            float(elapsed),
            self._safe_debug_repr(result, max_len=None),
        )

    def _debug_log_api_error(
        self, method_name: str, error: Exception, elapsed: float
    ) -> None:
        """Log one qBittorrent API call failure when debug logging is enabled."""
        if not self.debug_logging_enabled:
            return
        logger.debug(
            "[API ERR] %s elapsed=%.3fs error=%s",
            str(method_name),
            float(elapsed),
            self._safe_debug_repr(error),
        )

    def _log(self, level: str, message: str, elapsed: float | None = None) -> None:
        """Write to Python file logger."""
        elapsed_str = f" [{elapsed:.3f}s]" if elapsed is not None else ""
        log_msg = f"{message}{elapsed_str}"
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, log_msg)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event."""
        if (
            self._add_torrent_dialog is not None
            and self._add_torrent_dialog.isVisible()
        ):
            self._add_torrent_dialog.close()
        self._save_settings()
        self._save_content_cache()
        event.accept()
