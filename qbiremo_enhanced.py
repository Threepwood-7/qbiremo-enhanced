#!/usr/bin/env python3
"""
qBiremo Enhanced - Advanced qBittorrent GUI Client
A feature-rich PySide6-based GUI for managing qBittorrent remotely
"""

import os
import sys
import argparse
import atexit
import json
import logging
import traceback
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from urllib.parse import urlparse
import time
import fnmatch
from collections import deque

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QTextEdit, QFrame, QToolBar, QStatusBar,
    QAbstractItemView, QHeaderView, QFormLayout, QSpinBox, QDoubleSpinBox, QGroupBox,
    QProgressBar, QMenu, QMessageBox, QTabWidget, QListWidget, QListWidgetItem,
    QInputDialog,
    QSizePolicy
)
from PySide6.QtCore import (
    Qt, QTimer, QRunnable, Slot, Signal, QObject, QThreadPool, QSettings,
    QSize
)
from PySide6.QtGui import QAction, QFont, QIcon, QColor, QBrush

import qbittorrentapi


# ============================================================================
# Configuration and Constants
# ============================================================================

G_ORG_NAME = "qBiremo"
G_APP_NAME = "qBiremoEnhanced"
DEFAULT_REFRESH_INTERVAL = 60  # seconds
DEFAULT_AUTO_REFRESH = False
DEFAULT_STATUS_FILTER = 'active'
DEFAULT_DISPLAY_SIZE_MODE = 'human_readable'
DEFAULT_DISPLAY_SPEED_MODE = 'human_readable'
CACHE_FILE_NAME = "qbiremo_enhanced.cache"

logger = logging.getLogger(G_APP_NAME)

# Status filters as per qBittorrent API
STATUS_FILTERS = [
    'all', 'downloading', 'seeding', 'completed', 'paused', 'stopped',
    'active', 'inactive', 'resumed', 'running', 'stalled',
    'stalled_uploading', 'stalled_downloading', 'checking', 'moving', 'errored'
]

# Size buckets in bytes (will be dynamically calculated)
SIZE_BUCKET_COUNT = 5


# ============================================================================
# Worker Thread Components
# ============================================================================

class WorkerSignals(QObject):
    """Signals available from a running worker thread"""
    finished = Signal()
    error = Signal(tuple)
    result = Signal(object)
    progress = Signal(int)
    cancelled = Signal()


class Worker(QRunnable):
    """Worker thread for background tasks with cancellation support"""

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.kwargs["progress_callback"] = self.signals.progress
        self.is_cancelled = False

    def cancel(self):
        """Cancel this worker"""
        self.is_cancelled = True

    @Slot()
    def run(self):
        """Execute the worker function"""
        if self.is_cancelled:
            self.signals.cancelled.emit()
            return

        try:
            result = self.fn(*self.args, **self.kwargs)
            if not self.is_cancelled:
                self.signals.result.emit(result)
        except Exception:
            if not self.is_cancelled:
                exctype, value = sys.exc_info()[:2]
                self.signals.error.emit((exctype, value, traceback.format_exc()))
        finally:
            self.signals.finished.emit()


# ============================================================================
# API Task Queue Manager with Cancellation
# ============================================================================

class APITaskQueue(QObject):
    """Manages queued API tasks with cancellation support"""

    task_completed = Signal(str, object)  # task_name, result
    task_failed = Signal(str, str)  # task_name, error_message
    task_cancelled = Signal(str)  # task_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_worker = None
        self.is_processing = False
        self.threadpool = QThreadPool()
        self.current_task_name = None

    def add_task(self, task_name: str, fn, callback, *args, **kwargs):
        """Add a task to the queue, cancelling any current task"""
        # Cancel current task if running
        if self.current_worker:
            self.current_worker.cancel()
            if self.current_task_name:
                self.task_cancelled.emit(self.current_task_name)

        self.is_processing = True
        self.current_task_name = task_name

        worker = Worker(fn, *args, **kwargs)
        self.current_worker = worker

        worker.signals.result.connect(
            lambda result: self._on_task_complete(task_name, callback, result)
        )
        worker.signals.error.connect(
            lambda error: self._on_task_error(task_name, error)
        )
        worker.signals.cancelled.connect(
            lambda: self._on_task_cancelled(task_name)
        )

        self.threadpool.start(worker)

    def clear_queue(self):
        """Clear current task"""
        if self.current_worker:
            self.current_worker.cancel()
        self.is_processing = False
        self.current_task_name = None

    def _on_task_complete(self, task_name: str, callback, result):
        """Handle successful task completion"""
        prev_worker = self.current_worker
        try:
            if callback:
                callback(result)
            self.task_completed.emit(task_name, result)
        except Exception as e:
            self.task_failed.emit(task_name, str(e))
        finally:
            # Only clear state if the callback did NOT chain a new task
            # via add_task (which would have replaced current_worker).
            if self.current_worker is prev_worker:
                self.current_worker = None
                self.is_processing = False
                self.current_task_name = None

    def _on_task_error(self, task_name: str, error):
        """Handle task failure"""
        prev_worker = self.current_worker
        try:
            exctype, value, trace = error
            error_msg = f"{exctype.__name__}: {value}"
            logger.error("Task %s failed:\n%s", task_name, trace)
            self.task_failed.emit(task_name, error_msg)
        except Exception as e:
            logger.error("Error in _on_task_error for %s: %s", task_name, e)
            self.task_failed.emit(task_name, str(e))
        finally:
            if self.current_worker is prev_worker:
                self.current_worker = None
                self.is_processing = False
                self.current_task_name = None

    def _on_task_cancelled(self, task_name: str):
        """Handle task cancellation"""
        try:
            self.task_cancelled.emit(task_name)
        except Exception as e:
            logger.error("Error in _on_task_cancelled for %s: %s", task_name, e)


# ============================================================================
# Add Torrent Dialog
# ============================================================================

class AddTorrentDialog(QDialog):
    """Dialog for adding a new torrent"""

    def __init__(self, categories: List[str], tags: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Torrent")
        self.resize(780, 720)

        layout = QVBoxLayout(self)

        # Source group
        grp_source = QGroupBox("Torrent Source")
        src_layout = QVBoxLayout(grp_source)

        # File/URL selection
        file_layout = QHBoxLayout()
        self.txt_source = QLineEdit()
        self.txt_source.setPlaceholderText("Torrent file path, magnet link, or URL (one per line)...")
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_file)
        file_layout.addWidget(self.txt_source)
        file_layout.addWidget(btn_browse)
        src_layout.addLayout(file_layout)

        layout.addWidget(grp_source)

        tabs = QTabWidget()

        # --------------------------------------------------------------------
        # Basic Tab
        # --------------------------------------------------------------------
        tab_basic = QWidget()
        basic_form = QFormLayout(tab_basic)

        # Save path (main path)
        save_layout = QHBoxLayout()
        self.txt_save_path = QLineEdit()
        self.txt_save_path.setPlaceholderText("Main save path (optional)")
        btn_save_browse = QPushButton("Browse...")
        btn_save_browse.clicked.connect(self._browse_save_path)
        save_layout.addWidget(self.txt_save_path)
        save_layout.addWidget(btn_save_browse)
        basic_form.addRow("Save Path:", save_layout)

        # Download path (optional secondary path in supported qB versions)
        dl_path_layout = QHBoxLayout()
        self.txt_download_path = QLineEdit()
        self.txt_download_path.setPlaceholderText("Download path (optional)")
        btn_download_browse = QPushButton("Browse...")
        btn_download_browse.clicked.connect(self._browse_download_path)
        dl_path_layout.addWidget(self.txt_download_path)
        dl_path_layout.addWidget(btn_download_browse)
        basic_form.addRow("Download Path:", dl_path_layout)

        self.chk_use_download_path = QCheckBox("Use Download Path")
        basic_form.addRow("", self.chk_use_download_path)

        # Category
        self.cmb_category = QComboBox()
        self.cmb_category.setEditable(True)
        self.cmb_category.addItems([""] + categories)
        basic_form.addRow("Category:", self.cmb_category)

        # Tags (multi-select checkable list)
        self.lst_tags = QListWidget()
        self.lst_tags.setMaximumHeight(100)
        for tag in tags:
            item = QListWidgetItem(tag)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.lst_tags.addItem(item)
        basic_form.addRow("Tags:", self.lst_tags)

        self.txt_tags_extra = QLineEdit()
        self.txt_tags_extra.setPlaceholderText("Additional tags (comma-separated)")
        basic_form.addRow("Extra Tags:", self.txt_tags_extra)

        self.txt_rename = QLineEdit()
        self.txt_rename.setPlaceholderText("Rename torrent (optional)")
        basic_form.addRow("Rename:", self.txt_rename)

        self.txt_cookie = QLineEdit()
        self.txt_cookie.setPlaceholderText("HTTP cookie(s) for URL-based torrents (optional)")
        basic_form.addRow("Cookie:", self.txt_cookie)

        tabs.addTab(tab_basic, "Basic")

        # --------------------------------------------------------------------
        # Behavior Tab
        # --------------------------------------------------------------------
        tab_behavior = QWidget()
        behavior_form = QFormLayout(tab_behavior)

        # Auto TMM
        self.chk_auto_tmm = QCheckBox("Automatic Torrent Management")
        behavior_form.addRow("", self.chk_auto_tmm)

        # Start torrent
        self.chk_paused = QCheckBox("Start torrent paused")
        behavior_form.addRow("", self.chk_paused)

        self.chk_stopped = QCheckBox("Add torrent stopped")
        behavior_form.addRow("", self.chk_stopped)

        self.chk_forced = QCheckBox("Force start")
        behavior_form.addRow("", self.chk_forced)

        self.chk_add_to_top = QCheckBox("Add to top of queue")
        behavior_form.addRow("", self.chk_add_to_top)

        # Skip hash check
        self.chk_skip_check = QCheckBox("Skip hash check")
        behavior_form.addRow("", self.chk_skip_check)

        # Sequential download
        self.chk_sequential = QCheckBox("Sequential download")
        behavior_form.addRow("", self.chk_sequential)

        # First/last piece priority
        self.chk_first_last = QCheckBox("First and last piece priority")
        behavior_form.addRow("", self.chk_first_last)

        self.chk_root_folder = QCheckBox("Create root folder")
        behavior_form.addRow("", self.chk_root_folder)

        self.cmb_content_layout = QComboBox()
        self.cmb_content_layout.addItems(["Default", "Original", "Subfolder", "NoSubfolder"])
        behavior_form.addRow("Content Layout:", self.cmb_content_layout)

        self.cmb_stop_condition = QComboBox()
        self.cmb_stop_condition.addItems(["Default", "MetadataReceived", "FilesChecked"])
        behavior_form.addRow("Stop Condition:", self.cmb_stop_condition)

        tabs.addTab(tab_behavior, "Behavior")

        # --------------------------------------------------------------------
        # Limits Tab
        # --------------------------------------------------------------------
        tab_limits = QWidget()
        limits_form = QFormLayout(tab_limits)

        self.spn_upload_limit = QSpinBox()
        self.spn_upload_limit.setRange(0, 10_000_000)
        self.spn_upload_limit.setSpecialValueText("Unlimited")
        self.spn_upload_limit.setSuffix(" KiB/s")
        limits_form.addRow("Upload Limit:", self.spn_upload_limit)

        self.spn_download_limit = QSpinBox()
        self.spn_download_limit.setRange(0, 10_000_000)
        self.spn_download_limit.setSpecialValueText("Unlimited")
        self.spn_download_limit.setSuffix(" KiB/s")
        limits_form.addRow("Download Limit:", self.spn_download_limit)

        self.spn_ratio_limit = QDoubleSpinBox()
        self.spn_ratio_limit.setRange(-1.0, 10_000.0)
        self.spn_ratio_limit.setDecimals(2)
        self.spn_ratio_limit.setSingleStep(0.1)
        self.spn_ratio_limit.setValue(-1.0)
        limits_form.addRow("Ratio Limit:", self.spn_ratio_limit)

        self.spn_seeding_time_limit = QSpinBox()
        self.spn_seeding_time_limit.setRange(-1, 10_000_000)
        self.spn_seeding_time_limit.setValue(-1)
        self.spn_seeding_time_limit.setSuffix(" min")
        limits_form.addRow("Seeding Time Limit:", self.spn_seeding_time_limit)

        self.spn_inactive_seeding_time_limit = QSpinBox()
        self.spn_inactive_seeding_time_limit.setRange(-1, 10_000_000)
        self.spn_inactive_seeding_time_limit.setValue(-1)
        self.spn_inactive_seeding_time_limit.setSuffix(" min")
        limits_form.addRow("Inactive Seeding Limit:", self.spn_inactive_seeding_time_limit)

        self.cmb_share_limit_action = QComboBox()
        self.cmb_share_limit_action.addItems(
            ["Default", "Stop", "Remove", "RemoveWithContent", "EnableSuperSeeding"]
        )
        limits_form.addRow("Share Limit Action:", self.cmb_share_limit_action)

        tabs.addTab(tab_limits, "Limits")

        layout.addWidget(tabs)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.torrent_data = None

    def _browse_file(self):
        """Browse for torrent file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Torrent File", "", "Torrent Files (*.torrent);;All Files (*)"
        )
        if file_path:
            self.txt_source.setText(file_path)

    def _browse_save_path(self):
        """Browse for save directory"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Save Directory")
        if dir_path:
            self.txt_save_path.setText(dir_path)

    def _browse_download_path(self):
        """Browse for download directory"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if dir_path:
            self.txt_download_path.setText(dir_path)

    @staticmethod
    def _split_csv(text: str) -> List[str]:
        return [p.strip() for p in (text or "").split(",") if p.strip()]

    def _get_selected_tags(self) -> str:
        """Return comma-separated string of checked tags."""
        selected = []
        for i in range(self.lst_tags.count()):
            item = self.lst_tags.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.text())
        selected.extend(self._split_csv(self.txt_tags_extra.text()))
        # preserve order but remove duplicates
        deduped = list(dict.fromkeys(selected))
        return ','.join(deduped)

    @staticmethod
    def _is_url_source(source: str) -> bool:
        lower = source.lower()
        return lower.startswith("magnet:") or lower.startswith("http://") or lower.startswith("https://") or lower.startswith("bc://")

    @staticmethod
    def _parse_url_source(source: str):
        # Accept one URL per line for convenience.
        lines = [line.strip() for line in source.splitlines() if line.strip()]
        if not lines:
            return ""
        if len(lines) == 1:
            return lines[0]
        return lines

    def get_torrent_data(self) -> Optional[Dict[str, Any]]:
        """Get the torrent data from the dialog"""
        source = self.txt_source.text().strip()
        if not source:
            return None

        data: Dict[str, Any] = {}

        save_path = self.txt_save_path.text().strip()
        if save_path:
            data['save_path'] = save_path

        download_path = self.txt_download_path.text().strip()
        if download_path:
            data['download_path'] = download_path
        if self.chk_use_download_path.isChecked():
            if not download_path:
                QMessageBox.warning(self, "Missing Download Path", "Use Download Path is enabled, but Download Path is empty.")
                return None
            data['use_download_path'] = True

        category = self.cmb_category.currentText().strip()
        if category:
            data['category'] = category

        tags = self._get_selected_tags().strip()
        if tags:
            data['tags'] = tags

        rename = self.txt_rename.text().strip()
        if rename:
            data['rename'] = rename

        cookie = self.txt_cookie.text().strip()
        if cookie:
            data['cookie'] = cookie

        # Behavior
        data['is_paused'] = self.chk_paused.isChecked()
        data['is_stopped'] = self.chk_stopped.isChecked()
        data['forced'] = self.chk_forced.isChecked()
        data['add_to_top_of_queue'] = self.chk_add_to_top.isChecked()
        data['is_skip_checking'] = self.chk_skip_check.isChecked()
        data['is_sequential_download'] = self.chk_sequential.isChecked()
        data['is_first_last_piece_priority'] = self.chk_first_last.isChecked()
        data['use_auto_torrent_management'] = self.chk_auto_tmm.isChecked()
        data['is_root_folder'] = self.chk_root_folder.isChecked()

        content_layout = self.cmb_content_layout.currentText()
        if content_layout != "Default":
            data['content_layout'] = content_layout

        stop_condition = self.cmb_stop_condition.currentText()
        if stop_condition != "Default":
            data['stop_condition'] = stop_condition

        # Limits
        up_limit_kib = self.spn_upload_limit.value()
        if up_limit_kib > 0:
            data['upload_limit'] = up_limit_kib * 1024

        down_limit_kib = self.spn_download_limit.value()
        if down_limit_kib > 0:
            data['download_limit'] = down_limit_kib * 1024

        ratio_limit = float(self.spn_ratio_limit.value())
        if ratio_limit >= 0:
            data['ratio_limit'] = ratio_limit

        seeding_time_limit = int(self.spn_seeding_time_limit.value())
        if seeding_time_limit >= 0:
            data['seeding_time_limit'] = seeding_time_limit

        inactive_seeding_limit = int(self.spn_inactive_seeding_time_limit.value())
        if inactive_seeding_limit >= 0:
            data['inactive_seeding_time_limit'] = inactive_seeding_limit

        share_limit_action = self.cmb_share_limit_action.currentText()
        if share_limit_action != "Default":
            data['share_limit_action'] = share_limit_action

        # Source
        if self._is_url_source(source):
            data['urls'] = self._parse_url_source(source)
        else:
            if not os.path.exists(source):
                QMessageBox.warning(self, "Torrent File Not Found", f"File does not exist:\n{source}")
                return None
            data['torrent_files'] = source

        return data


# ============================================================================
# Utility Functions
# ============================================================================

def format_float(value: float, decimals: int = 2) -> str:
    """Format float with specified decimals, empty if zero"""
    if value != 0:
        return f"{value:.{decimals}f}"
    return ""


def format_int(value: int) -> str:
    """Format integer with thousands separator, empty if zero"""
    if value != 0:
        return f"{value:,}"
    return ""


def format_datetime(timestamp: int) -> str:
    """Format Unix timestamp, empty if zero"""
    if timestamp > 0:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    return ""


def format_size(bytes_size: int) -> str:
    """Format bytes as human-readable size"""
    return format_size_mode(bytes_size, mode='human_readable')


def format_speed(bytes_per_sec: int) -> str:
    """Format speed in bytes/sec"""
    return format_speed_mode(bytes_per_sec, mode='human_readable')


def _normalize_display_mode(value: Any, default: str) -> str:
    """Normalize mode to 'bytes' or 'human_readable'."""
    mode = str(value or default).strip().lower()
    if mode in {'bytes', 'human_readable'}:
        return mode
    return default


def format_size_mode(bytes_size: int, mode: str = 'human_readable') -> str:
    """Format size according to display mode."""
    mode = _normalize_display_mode(mode, DEFAULT_DISPLAY_SIZE_MODE)
    size_val = int(bytes_size or 0)
    if mode == 'bytes':
        return f"{size_val:,}"

    if size_val == 0:
        return "0 B"

    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    unit_idx = 0
    size = float(size_val)

    while size >= 1024 and unit_idx < len(units) - 1:
        size /= 1024
        unit_idx += 1

    return f"{size:.2f} {units[unit_idx]}"


def format_speed_mode(bytes_per_sec: int, mode: str = 'human_readable') -> str:
    """Format speed according to display mode."""
    speed_val = int(bytes_per_sec or 0)
    if speed_val == 0:
        return ""
    mode = _normalize_display_mode(mode, DEFAULT_DISPLAY_SPEED_MODE)
    if mode == 'bytes':
        return f"{speed_val:,}"
    return f"{format_size_mode(speed_val, mode='human_readable')}/s"


def parse_tags(tags) -> List[str]:
    """Parse tags from qBittorrentAPI into a list of strings.

    qbittorrentapi may return tags as a comma-separated string or a list.
    """
    if not tags:
        return []
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(',') if t.strip()]
    if isinstance(tags, (list, tuple, set)):
        return [str(t) for t in tags]
    return []


def matches_wildcard(text: str, pattern: str) -> bool:
    """Check if text matches DOS-style wildcard pattern"""
    if not pattern:
        return True
    return fnmatch.fnmatch(text.lower(), pattern.lower())


def normalize_filter_pattern(raw_pattern: str) -> str:
    """Normalize filter input: plain text becomes a contains wildcard pattern."""
    pattern = (raw_pattern or "").strip()
    if not pattern:
        return ""
    if '*' in pattern or '?' in pattern:
        return pattern
    return f"*{pattern}*"


def calculate_size_buckets(min_size: int, max_size: int, count: int = 5) -> List[tuple]:
    """Calculate size bucket ranges"""
    if min_size >= max_size or count < 1:
        return []

    buckets = []
    range_size = (max_size - min_size) / count

    for i in range(count):
        start = int(min_size + (i * range_size))
        end = int(min_size + ((i + 1) * range_size))
        buckets.append((start, end))

    return buckets


class NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by a numeric value instead of text."""

    def __init__(self, display_text: str, sort_value: float = 0.0):
        super().__init__(display_text)
        self._sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


# ============================================================================
# Main Window
# ============================================================================

class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__()

        self.config = config
        self.base_window_title = "qBiremo Enhanced"
        self.setWindowTitle(self.base_window_title)

        # Connection info from config (TOML), falling back to env vars
        self.qb_conn_info = self._build_connection_info(config)

        # State
        self.all_torrents = []
        self.filtered_torrents = []
        self.categories = []
        self.tags = []
        self.trackers = []
        self.size_buckets = []

        # Defaults from config (used by Reset View and first launch)
        cfg_default_status = str(config.get('default_status_filter', DEFAULT_STATUS_FILTER)).strip().lower()
        self.default_status_filter = cfg_default_status if cfg_default_status in STATUS_FILTERS else DEFAULT_STATUS_FILTER
        self.default_auto_refresh_enabled = self._to_bool(
            config.get('auto_refresh', DEFAULT_AUTO_REFRESH),
            DEFAULT_AUTO_REFRESH
        )
        self.default_refresh_interval = max(
            1,
            self._safe_int(config.get('refresh_interval', DEFAULT_REFRESH_INTERVAL), DEFAULT_REFRESH_INTERVAL)
        )

        # Filters
        self.current_status_filter = self.default_status_filter
        self.current_category_filter = None
        self.current_tag_filter = None
        self.current_size_bucket = None
        self.current_tracker_filter = None
        self.current_private_filter = None
        self.current_text_filter = ""
        self.current_file_filter = ""
        self.current_content_filter = ""
        self.current_content_files: List[Dict[str, Any]] = []
        self._selected_torrent = None
        self._suppress_next_cache_save = False

        # Persistent per-torrent content cache (JSON file)
        self.cache_file_path = Path(CACHE_FILE_NAME)
        self.content_cache: Dict[str, Dict[str, Any]] = {}
        self._load_content_cache()

        # API task queue
        self.api_queue = APITaskQueue(self)
        self.api_queue.task_completed.connect(self._on_task_completed)
        self.api_queue.task_failed.connect(self._on_task_failed)
        self.api_queue.task_cancelled.connect(self._on_task_cancelled)

        # Log file path (set by main() before constructing MainWindow)
        self.log_file_path = config.get('_log_file_path', 'qbiremo_enhanced.log')

        # Auto-refresh settings
        self.auto_refresh_enabled = self.default_auto_refresh_enabled
        self.refresh_interval = self.default_refresh_interval
        self.display_size_mode = _normalize_display_mode(
            config.get('display_size_mode', DEFAULT_DISPLAY_SIZE_MODE),
            DEFAULT_DISPLAY_SIZE_MODE
        )
        self.display_speed_mode = _normalize_display_mode(
            config.get('display_speed_mode', DEFAULT_DISPLAY_SPEED_MODE),
            DEFAULT_DISPLAY_SPEED_MODE
        )

        # UI Setup
        self._create_ui()
        self._create_menus()
        self._create_toolbar()
        self._create_statusbar()
        self._capture_default_view_state()

        # Timers
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_torrents)
        if self.auto_refresh_enabled:
            self.refresh_timer.start(self.refresh_interval * 1000)

        # Load settings
        self._load_settings()

        # Initial data load
        QTimer.singleShot(100, self._initial_load)

        self._update_window_title_speeds()
        # Force startup as maximized regardless of previously persisted geometry.
        self.setWindowState(
            (self.windowState() & ~Qt.WindowState.WindowMinimized)
            | Qt.WindowState.WindowMaximized
        )
        self.show()

    def _create_ui(self):
        """Create the main UI layout"""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Filter bar
        filter_bar = self._create_filter_bar()
        main_layout.addWidget(filter_bar)

        # Main splitter (horizontal)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - filters
        left_panel = self._create_left_panel()
        self.main_splitter.addWidget(left_panel)

        # Right splitter (vertical)
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)

        # Torrents table
        self.tbl_torrents = self._create_torrents_table()
        self.right_splitter.addWidget(self.tbl_torrents)

        # Details panel (tabbed)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setTabPosition(QTabWidget.TabPosition.South)

        # -- Info tab --
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(4, 4, 4, 4)

        self.txt_details = QTextEdit()
        self.txt_details.setReadOnly(True)
        self.txt_details.setFont(QFont("Courier", 9))
        info_layout.addWidget(self.txt_details)

        # Editable fields
        edit_group = QGroupBox("Edit Properties")
        edit_form = QFormLayout(edit_group)

        self.edit_name = QLineEdit()
        edit_form.addRow("Name:", self.edit_name)

        self.edit_category = QComboBox()
        self.edit_category.setEditable(True)
        edit_form.addRow("Category:", self.edit_category)

        self.edit_tags = QLineEdit()
        self.edit_tags.setPlaceholderText("Comma-separated tags")
        edit_form.addRow("Tags:", self.edit_tags)

        self.edit_save_path = QLineEdit()
        edit_form.addRow("Save Path:", self.edit_save_path)

        btn_save_props = QPushButton("Save Changes")
        btn_save_props.clicked.connect(self._save_torrent_properties)
        edit_form.addRow("", btn_save_props)

        info_layout.addWidget(edit_group)
        self.detail_tabs.addTab(info_widget, "Info")

        # -- Content tab --
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(4, 4, 4, 4)

        content_filter_layout = QHBoxLayout()
        content_filter_layout.addWidget(QLabel("Content File:"))
        self.txt_content_filter = QLineEdit()
        self.txt_content_filter.setPlaceholderText(
            "Filter selected torrent content (wildcards: *, ?)..."
        )
        self.txt_content_filter.textChanged.connect(self._on_content_filter_changed)
        content_filter_layout.addWidget(self.txt_content_filter)
        content_layout.addLayout(content_filter_layout)

        self.tree_files = QTreeWidget()
        self.tree_files.setHeaderLabels(["Name", "Size", "Progress", "Priority"])
        self.tree_files.setAlternatingRowColors(True)
        file_header = self.tree_files.header()
        file_header.setStretchLastSection(False)
        file_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        content_layout.addWidget(self.tree_files)
        self.detail_tabs.addTab(content_widget, "Content")

        self.right_splitter.addWidget(self.detail_tabs)

        self.main_splitter.addWidget(self.right_splitter)

        # Set initial sizes
        self.main_splitter.setSizes([250, 1000])
        self.right_splitter.setSizes([600, 200])

        main_layout.addWidget(self.main_splitter)

    def _create_filter_bar(self) -> QWidget:
        """Create the filter bar above the torrents table"""
        widget = QFrame()
        widget.setFrameShape(QFrame.Shape.StyledPanel)
        widget.setSizePolicy(QSizePolicy.Policy.Preferred,
                             QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)

        # Private filter
        layout.addWidget(QLabel("Private:"))
        self.cmb_private = QComboBox()
        self.cmb_private.addItems(["All", "Yes", "No"])
        self.cmb_private.currentTextChanged.connect(self._on_quick_filter_changed)
        layout.addWidget(self.cmb_private)

        # Text filter
        layout.addWidget(QLabel("Name:"))
        self.txt_name_filter = QLineEdit()
        self.txt_name_filter.setPlaceholderText("Search torrents (wildcards: *, ?)...")
        self.txt_name_filter.textChanged.connect(self._on_quick_filter_changed)
        layout.addWidget(self.txt_name_filter)

        # File filter
        layout.addWidget(QLabel("File:"))
        self.txt_file_filter = QLineEdit()
        self.txt_file_filter.setPlaceholderText("Search files (wildcards: *, ?)...")
        self.txt_file_filter.textChanged.connect(self._on_quick_filter_changed)
        layout.addWidget(self.txt_file_filter)

        # Clear button
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear_filters)
        layout.addWidget(btn_clear)

        return widget

    def _create_left_panel(self) -> QWidget:
        """Create the left filter panel as a single tree with collapsible sections."""
        self.tree_filters = QTreeWidget()
        self.tree_filters.setHeaderLabel("Filters")
        self.tree_filters.setRootIsDecorated(True)
        self.tree_filters.setAnimated(True)
        self.tree_filters.itemClicked.connect(self._on_filter_tree_clicked)

        # -- Status section --
        self._section_status = QTreeWidgetItem(["Status"])
        self._section_status.setFlags(
            self._section_status.flags() & ~Qt.ItemFlag.ItemIsSelectable
        )
        font = self._section_status.font(0)
        font.setBold(True)
        self._section_status.setFont(0, font)
        self.tree_filters.addTopLevelItem(self._section_status)

        for status in STATUS_FILTERS:
            item = QTreeWidgetItem([status.replace('_', ' ').title()])
            item.setData(0, Qt.ItemDataRole.UserRole, ('status', status))
            self._section_status.addChild(item)
        self._section_status.setExpanded(True)

        # -- Categories section --
        self._section_category = QTreeWidgetItem(["Categories"])
        self._section_category.setFlags(
            self._section_category.flags() & ~Qt.ItemFlag.ItemIsSelectable
        )
        font = self._section_category.font(0)
        font.setBold(True)
        self._section_category.setFont(0, font)
        self.tree_filters.addTopLevelItem(self._section_category)

        # -- Tags section --
        self._section_tag = QTreeWidgetItem(["Tags"])
        self._section_tag.setFlags(
            self._section_tag.flags() & ~Qt.ItemFlag.ItemIsSelectable
        )
        font = self._section_tag.font(0)
        font.setBold(True)
        self._section_tag.setFont(0, font)
        self.tree_filters.addTopLevelItem(self._section_tag)

        # -- Size Groups section --
        self._section_size = QTreeWidgetItem(["Size Groups"])
        self._section_size.setFlags(
            self._section_size.flags() & ~Qt.ItemFlag.ItemIsSelectable
        )
        font = self._section_size.font(0)
        font.setBold(True)
        self._section_size.setFont(0, font)
        self.tree_filters.addTopLevelItem(self._section_size)

        # -- Trackers section --
        self._section_tracker = QTreeWidgetItem(["Trackers"])
        self._section_tracker.setFlags(
            self._section_tracker.flags() & ~Qt.ItemFlag.ItemIsSelectable
        )
        font = self._section_tracker.font(0)
        font.setBold(True)
        self._section_tracker.setFont(0, font)
        self.tree_filters.addTopLevelItem(self._section_tracker)

        self._refresh_filter_tree_highlights()
        return self.tree_filters

    def _is_filter_item_active(self, kind: str, value) -> bool:
        """Return whether a filter tree item is currently active."""
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

    def _refresh_filter_tree_highlights(self):
        """Highlight all currently active filters in the unified tree."""
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

    def _create_torrents_table(self) -> QTableWidget:
        """Create the torrents table widget"""
        table = QTableWidget()
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.itemSelectionChanged.connect(self._on_torrent_selected)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_torrent_context_menu)

        headers = [
            "Hash", "Name", "Size", "Progress", "Status", "DL Speed", "UP Speed",
            "Ratio", "Seeds", "Peers", "Added On", "Category", "Tags"
        ]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)

        # Hide hash column
        table.setColumnHidden(0, True)

        # Make columns user-resizable and movable.
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        header.setMinimumSectionSize(40)

        # Default widths (used on first run before QSettings restore)
        table.setColumnWidth(1, 360)
        table.setColumnWidth(2, 100)
        table.setColumnWidth(3, 80)
        table.setColumnWidth(4, 100)
        table.setColumnWidth(5, 100)
        table.setColumnWidth(6, 100)
        table.setColumnWidth(7, 70)
        table.setColumnWidth(8, 60)
        table.setColumnWidth(9, 60)
        table.setColumnWidth(10, 150)
        table.setColumnWidth(11, 120)
        table.setColumnWidth(12, 150)

        return table

    def _create_menus(self):
        """Create menu bar"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        add_action = QAction("&Add Torrent...", self)
        add_action.setShortcut("Ctrl+O")
        add_action.triggered.connect(self._show_add_torrent_dialog)
        file_menu.addAction(add_action)

        clear_cache_action = QAction("Clear Cache && &Refresh", self)
        clear_cache_action.setShortcut("Ctrl+F5")
        clear_cache_action.triggered.connect(self._clear_cache_and_refresh)
        file_menu.addAction(clear_cache_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        action_open_log = QAction("Open &Log File", self)
        action_open_log.triggered.connect(self._open_log_file)
        view_menu.addAction(action_open_log)

        action_refresh = QAction("&Refresh", self)
        action_refresh.setShortcut("F5")
        action_refresh.triggered.connect(self._refresh_torrents)
        view_menu.addAction(action_refresh)

        view_menu.addSeparator()

        self.action_auto_refresh = QAction("Enable &Auto-Refresh", self)
        self.action_auto_refresh.setCheckable(True)
        self.action_auto_refresh.setChecked(self.auto_refresh_enabled)
        self.action_auto_refresh.triggered.connect(self._toggle_auto_refresh)
        view_menu.addAction(self.action_auto_refresh)

        action_set_refresh_interval = QAction("Set Auto-Refresh &Interval...", self)
        action_set_refresh_interval.triggered.connect(self._set_auto_refresh_interval)
        view_menu.addAction(action_set_refresh_interval)

        view_menu.addSeparator()
        action_reset_view = QAction("&Reset View", self)
        action_reset_view.triggered.connect(self._reset_view_defaults)
        view_menu.addAction(action_reset_view)

        # Torrent menu
        torrent_menu = menubar.addMenu("&Torrent")

        pause_action = QAction("&Pause", self)
        pause_action.triggered.connect(self._pause_torrent)
        torrent_menu.addAction(pause_action)

        resume_action = QAction("&Resume", self)
        resume_action.triggered.connect(self._resume_torrent)
        torrent_menu.addAction(resume_action)

        torrent_menu.addSeparator()

        delete_action = QAction("&Delete", self)
        delete_action.triggered.connect(self._delete_torrent)
        torrent_menu.addAction(delete_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_toolbar(self):
        """Create toolbar"""
        toolbar = self.addToolBar("Main")
        toolbar.setFloatable(False)
        toolbar.setMovable(False)

        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self._refresh_torrents)
        toolbar.addAction(refresh_action)

        toolbar.addSeparator()

        add_action = QAction("Add Torrent", self)
        add_action.triggered.connect(self._show_add_torrent_dialog)
        toolbar.addAction(add_action)

    def _create_statusbar(self):
        """Create status bar"""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)

        # Status label
        self.lbl_status = QLabel("Ready")
        self.statusbar.addWidget(self.lbl_status, 1)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.statusbar.addPermanentWidget(self.progress_bar)

        # Torrent count label
        self.lbl_count = QLabel("0 torrents")
        self.statusbar.addPermanentWidget(self.lbl_count)

    # ========================================================================
    # Connection Configuration
    # ========================================================================

    def _build_connection_info(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Build qBittorrent connection info from TOML config with env var fallback.

        Supports HTTP basic auth (separate from qBittorrent API auth) via the
        host URL (e.g. https://user:password@remote.host.com:12345) or via
        explicit http_basic_auth_username / http_basic_auth_password config keys.
        """
        # Host URL — may contain scheme, basic-auth credentials, and port
        raw_host = (
            config.get('qb_host')
            or "localhost"
        )

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
            host = f"{parsed.scheme}://{netloc_host}"
        else:
            http_user = (
                config.get('http_basic_auth_username', '')
            )
            http_pass = (
                config.get('http_basic_auth_password', '')
            )

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
        }
        if extra_headers:
            conn['EXTRA_HEADERS'] = extra_headers

        return conn

    def _create_client(self) -> qbittorrentapi.Client:
        """Create and authenticate a qBittorrent API client."""
        qb = qbittorrentapi.Client(**self.qb_conn_info)
        qb.auth_log_in()
        return qb

    # ========================================================================
    # Content Cache
    # ========================================================================

    def _load_content_cache(self):
        """Load persistent content cache from JSON file."""
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

    def _save_content_cache(self):
        """Persist content cache to disk as JSON."""
        try:
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
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _normalize_cached_file(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize one cached file entry."""
        return {
            'name': str(entry.get('name', '') or ''),
            'size': self._safe_int(entry.get('size', 0), 0),
            'progress': self._safe_float(entry.get('progress', 0.0), 0.0),
            'priority': self._safe_int(entry.get('priority', 1), 1),
        }

    def _serialize_file_for_cache(self, file_obj) -> Dict[str, Any]:
        """Serialize API file object to cache-safe dict."""
        return self._normalize_cached_file({
            'name': getattr(file_obj, 'name', '') or '',
            'size': getattr(file_obj, 'size', 0),
            'progress': getattr(file_obj, 'progress', 0.0),
            'priority': getattr(file_obj, 'priority', 1),
        })

    def _get_cached_files(self, torrent_hash: str) -> List[Dict[str, Any]]:
        """Return cached files for torrent hash, or empty list."""
        if not torrent_hash:
            return []
        entry = self.content_cache.get(torrent_hash, {})
        files = entry.get('files', []) if isinstance(entry, dict) else []
        return files if isinstance(files, list) else []

    def _get_cache_refresh_candidates(self) -> Dict[str, str]:
        """Return torrent hashes that need cache refresh (new/missing/status change)."""
        candidates: Dict[str, str] = {}
        live_hashes = set()
        for torrent in self.all_torrents:
            torrent_hash = getattr(torrent, 'hash', '') or ''
            if not torrent_hash:
                continue
            live_hashes.add(torrent_hash)
            state = str(getattr(torrent, 'state', '') or '')
            cached = self.content_cache.get(torrent_hash)
            cached_state = str(cached.get('state', '')) if isinstance(cached, dict) else ''
            cached_files = cached.get('files') if isinstance(cached, dict) else None
            if cached_state != state or not isinstance(cached_files, list):
                candidates[torrent_hash] = state

        # Prune removed torrents from cache
        stale_hashes = [h for h in self.content_cache.keys() if h not in live_hashes]
        for h in stale_hashes:
            self.content_cache.pop(h, None)
        if stale_hashes:
            self._save_content_cache()

        return candidates

    def _matches_file_filter(self, torrent_hash: str, pattern: str) -> bool:
        """Return True when any cached file name/path matches the pattern."""
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

    # ========================================================================
    # Settings Management
    # ========================================================================

    def _capture_default_view_state(self):
        """Capture baseline splitter/header states for Reset View."""
        self._default_main_splitter_state = self.main_splitter.saveState()
        self._default_right_splitter_state = self.right_splitter.saveState()
        self._default_torrent_header_state = self.tbl_torrents.horizontalHeader().saveState()

    def _apply_default_torrent_header_layout(self):
        """Apply default torrent-table column order/widths/sort indicator."""
        header = self.tbl_torrents.horizontalHeader()

        # Restore natural logical->visual order.
        for logical in range(self.tbl_torrents.columnCount()):
            visual = header.visualIndex(logical)
            if visual != logical:
                header.moveSection(visual, logical)

        self.tbl_torrents.setColumnWidth(1, 360)
        self.tbl_torrents.setColumnWidth(2, 100)
        self.tbl_torrents.setColumnWidth(3, 80)
        self.tbl_torrents.setColumnWidth(4, 100)
        self.tbl_torrents.setColumnWidth(5, 100)
        self.tbl_torrents.setColumnWidth(6, 100)
        self.tbl_torrents.setColumnWidth(7, 70)
        self.tbl_torrents.setColumnWidth(8, 60)
        self.tbl_torrents.setColumnWidth(9, 60)
        self.tbl_torrents.setColumnWidth(10, 150)
        self.tbl_torrents.setColumnWidth(11, 120)
        self.tbl_torrents.setColumnWidth(12, 150)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

    def _restore_default_view_state(self):
        """Restore baseline splitter/header states for Reset View."""
        try:
            if getattr(self, "_default_main_splitter_state", None):
                self.main_splitter.restoreState(self._default_main_splitter_state)
            else:
                self.main_splitter.setSizes([250, 1000])
        except Exception:
            self.main_splitter.setSizes([250, 1000])

        try:
            if getattr(self, "_default_right_splitter_state", None):
                self.right_splitter.restoreState(self._default_right_splitter_state)
            else:
                self.right_splitter.setSizes([600, 200])
        except Exception:
            self.right_splitter.setSizes([600, 200])

        try:
            if getattr(self, "_default_torrent_header_state", None):
                self.tbl_torrents.horizontalHeader().restoreState(self._default_torrent_header_state)
            else:
                self._apply_default_torrent_header_layout()
        except Exception:
            # Fall back to explicit defaults.
            self._apply_default_torrent_header_layout()

    @staticmethod
    def _to_bool(value, default: bool = False) -> bool:
        """Convert QSettings-like values to bool."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return default

    def _save_refresh_settings(self):
        """Persist only auto-refresh runtime settings."""
        settings = QSettings(G_ORG_NAME, G_APP_NAME)
        settings.setValue("autoRefreshEnabled", bool(self.auto_refresh_enabled))
        settings.setValue("refreshIntervalSec", int(self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL)))

    def _load_settings(self):
        """Load window geometry, splitter sizes, column widths, sort order,
        and filter selection from QSettings."""
        settings = QSettings(G_ORG_NAME, G_APP_NAME)

        # Window geometry
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            default_width = self._safe_int(self.config.get('default_window_width', 1400), 1400)
            default_height = self._safe_int(self.config.get('default_window_height', 800), 800)
            default_width = max(600, default_width)
            default_height = max(400, default_height)
            self.resize(default_width, default_height)

        state = settings.value("windowState")
        if state:
            self.restoreState(state)

        # Splitter sizes
        main_sizes = settings.value("mainSplitter")
        if main_sizes:
            self.main_splitter.restoreState(main_sizes)
        right_sizes = settings.value("rightSplitter")
        if right_sizes:
            self.right_splitter.restoreState(right_sizes)

        # Torrent table header (column widths, order, sort)
        header_state = settings.value("torrentTableHeader")
        if header_state:
            self.tbl_torrents.horizontalHeader().restoreState(header_state)

        # Filter selection
        status = settings.value("filterStatus")
        if status and status in STATUS_FILTERS:
            self.current_status_filter = status
        self._refresh_filter_tree_highlights()

        # Auto-refresh settings
        self.auto_refresh_enabled = self._to_bool(
            settings.value("autoRefreshEnabled"),
            self.auto_refresh_enabled
        )
        loaded_interval = self._safe_int(
            settings.value("refreshIntervalSec"),
            self.refresh_interval
        )
        self.refresh_interval = max(1, loaded_interval)
        if hasattr(self, "action_auto_refresh"):
            self.action_auto_refresh.setChecked(self.auto_refresh_enabled)
        if self.auto_refresh_enabled:
            self.refresh_timer.start(self.refresh_interval * 1000)
        else:
            self.refresh_timer.stop()

    def _save_settings(self):
        """Save window geometry, splitter sizes, column widths, sort order,
        and filter selection to QSettings."""
        settings = QSettings(G_ORG_NAME, G_APP_NAME)

        # Window geometry
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())

        # Splitter sizes
        settings.setValue("mainSplitter", self.main_splitter.saveState())
        settings.setValue("rightSplitter", self.right_splitter.saveState())

        # Torrent table header (column widths, order, sort)
        settings.setValue("torrentTableHeader",
                          self.tbl_torrents.horizontalHeader().saveState())

        # Filter selection
        settings.setValue("filterStatus", self.current_status_filter)
        settings.setValue("autoRefreshEnabled", bool(self.auto_refresh_enabled))
        settings.setValue("refreshIntervalSec", int(self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL)))

    # ========================================================================
    # Initial Data Loading
    # ========================================================================

    def _initial_load(self):
        """Initial data load on startup"""
        try:
            self._log("INFO", "Starting initial data load...")
            self._log("INFO", f"Connecting to qBittorrent at {self.qb_conn_info['host']}:{self.qb_conn_info['port']}")
            self._show_progress("Loading categories...")

            # Load categories first
            self.api_queue.add_task(
                "load_categories",
                self._fetch_categories,
                self._on_categories_loaded
            )
        except Exception as e:
            self._log("ERROR", f"Failed to start initial load: {e}")
            self._hide_progress()
            self._set_status(f"Error: {e}")

    # ========================================================================
    # API Fetch Functions
    # ========================================================================

    def _fetch_categories(self, **_kw) -> Dict:
        """Fetch categories from qBittorrent"""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                result = qb.torrents_categories()
            elapsed = time.time() - start_time
            return {'data': result, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': None, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _fetch_tags(self, **_kw) -> List[str]:
        """Fetch tags from qBittorrent"""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                result = qb.torrents_tags()
            elapsed = time.time() - start_time
            return {'data': sorted(result), 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': [], 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _fetch_torrents(self, **_kw) -> List:
        """Fetch torrents from qBittorrent with current filters"""
        start_time = time.time()

        try:
            # Build API filter parameters
            params = {
                'sort': 'added_on',
                'reverse': True
            }

            # Apply status filter
            if self.current_status_filter and self.current_status_filter != 'all':
                params['status_filter'] = self.current_status_filter

            # Apply category filter
            if self.current_category_filter is not None:
                params['category'] = self.current_category_filter

            # Apply tag filter
            if self.current_tag_filter is not None:
                params['tag'] = self.current_tag_filter

            with self._create_client() as qb:
                result = qb.torrents_info(**params)

            elapsed = time.time() - start_time
            return {'data': list(result), 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': [], 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _refresh_content_cache_for_torrents(self, torrent_states: Dict[str, str], **_kw) -> Dict:
        """Refresh cached file trees for provided torrent hashes."""
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

    def _add_torrent_api(self, torrent_data: Dict, **_kw) -> bool:
        """Add a torrent via API"""
        start_time = time.time()
        data = dict(torrent_data)  # avoid mutating caller's dict
        try:
            with self._create_client() as qb:
                if 'torrent_files' in data:
                    # File-based torrent
                    file_path = data.pop('torrent_files')
                    with open(file_path, 'rb') as f:
                        result = qb.torrents_add(torrent_files=f, **data)
                else:
                    # URL/magnet
                    result = qb.torrents_add(**data)

            elapsed = time.time() - start_time
            return {'data': result == "Ok.", 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_pause_torrent(self, torrent_hash: str, **_kw) -> Dict:
        """Pause a torrent via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_pause(torrent_hashes=[torrent_hash])
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_resume_torrent(self, torrent_hash: str, **_kw) -> Dict:
        """Resume a torrent via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_resume(torrent_hashes=[torrent_hash])
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_delete_torrent(self, torrent_hash: str, delete_files: bool, **_kw) -> Dict:
        """Delete a torrent via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_delete(torrent_hashes=[torrent_hash], delete_files=delete_files)
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_save_torrent_properties(self, torrent_hash: str,
                                     props: Dict[str, Any], **_kw) -> Dict:
        """Save changed torrent properties via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                if 'name' in props:
                    qb.torrents_rename(torrent_hash=torrent_hash, new_torrent_name=props['name'])
                if 'category' in props:
                    qb.torrents_set_category(torrent_hashes=[torrent_hash], category=props['category'])
                if 'tags' in props:
                    # Remove all existing tags then add new ones
                    qb.torrents_remove_tags(torrent_hashes=[torrent_hash])
                    if props['tags']:
                        qb.torrents_add_tags(torrent_hashes=[torrent_hash], tags=props['tags'])
                if 'save_path' in props:
                    qb.torrents_set_location(torrent_hashes=[torrent_hash], location=props['save_path'])
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    # ========================================================================
    # API Callbacks
    # ========================================================================

    def _on_categories_loaded(self, result: Dict):
        """Handle categories loaded"""
        try:
            if not result.get('success', False):
                error = result.get('error', 'Unknown error')
                self._log("ERROR", f"Failed to load categories: {error}", result.get('elapsed', 0))
                self._set_status(f"Connection error: {error}")
                self.txt_details.setPlainText(
                    f"Failed to connect to qBittorrent:\n\n{error}\n\n"
                    f"Host: {self.qb_conn_info.get('host')}:{self.qb_conn_info.get('port')}\n"
                    f"Check your configuration and ensure qBittorrent WebUI is accessible."
                )
                # Continue anyway - load tags with empty categories
                self.categories = []
                self._update_category_tree()
                # Load tags next
                self._show_progress("Loading tags...")
                self.api_queue.add_task(
                    "load_tags",
                    self._fetch_tags,
                    self._on_tags_loaded
                )
                return

            self.categories = list(result.get('data', {}).keys()) if result.get('data') else []
            self._update_category_tree()
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

    def _on_tags_loaded(self, result: Dict):
        """Handle tags loaded"""
        try:
            if not result.get('success', False):
                error = result.get('error', 'Unknown error')
                self._log("ERROR", f"Failed to load tags: {error}", result.get('elapsed', 0))
                # Continue anyway - load torrents with empty tags
                self.tags = []
                self._update_tag_tree()
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

    def _on_torrents_loaded(self, result: Dict):
        """Handle torrents loaded"""
        try:
            if not result.get('success', False):
                error = result.get('error', 'Unknown error')
                self._log("ERROR", f"Failed to load torrents: {error}", result.get('elapsed', 0))
                self._hide_progress()
                self._set_status(f"Error: {error}")
                # Show empty table
                self.all_torrents = []
                self.filtered_torrents = []
                self._update_window_title_speeds()
                self._update_torrents_table()
                return

            self.all_torrents = result.get('data', [])
            self._log("INFO", f"Loaded {len(self.all_torrents)} torrents", result.get('elapsed', 0))
            self._update_window_title_speeds()

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
            self._hide_progress()
        except Exception as e:
            self._log("ERROR", f"Exception in _on_torrents_loaded: {e}")
            self._hide_progress()
            self._set_status(f"Error loading torrents: {e}")
            # Show empty table
            self.all_torrents = []
            self.filtered_torrents = []
            self._update_window_title_speeds()
            self._update_torrents_table()

    def _on_content_cache_refreshed(self, result: Dict):
        """Handle background refresh of cached torrent content trees."""
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

    def _on_add_torrent_complete(self, result: Dict):
        """Handle torrent add completion"""
        if result.get('success') and result.get('data'):
            self._log("INFO", "Torrent added successfully", result.get('elapsed', 0))
            self._set_status("Torrent added successfully")
            # Refresh torrent list
            QTimer.singleShot(1000, self._refresh_torrents)
        else:
            error_msg = result.get('error', 'Unknown error')
            self._log("ERROR", f"Failed to add torrent: {error_msg}", result.get('elapsed', 0))
            self._set_status(f"Failed to add torrent: {error_msg}")
        self._hide_progress()

    def _populate_content_tree(self, files: List[Dict[str, Any]]):
        """Populate the content tab from cached/serialized file entries."""
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
                if parent:
                    parent.addChild(file_item)
                else:
                    self.tree_files.addTopLevelItem(file_item)

            self.tree_files.expandAll()
        except Exception as e:
            self._log("ERROR", f"Error populating file tree: {e}")

    def _on_content_filter_changed(self, text: str):
        """Apply in-tab content filter for selected torrent files."""
        self.current_content_filter = normalize_filter_pattern(text)
        self._apply_content_filter()

    def _apply_content_filter(self):
        """Apply content-file filter to currently loaded selected torrent files."""
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

    def _show_cached_torrent_content(self, torrent_hash: str):
        """Display content tree from local cache for selected torrent."""
        self.current_content_files = self._get_cached_files(torrent_hash)
        self._apply_content_filter()

    def _on_save_properties_done(self, result: Dict):
        """Handle save-properties completion."""
        if result.get('success'):
            self._log("INFO", "Torrent properties saved", result.get('elapsed', 0))
            self._set_status("Properties saved")
            QTimer.singleShot(500, self._refresh_torrents)
        else:
            error = result.get('error', 'Unknown error')
            self._log("ERROR", f"Failed to save properties: {error}", result.get('elapsed', 0))
            self._set_status(f"Failed to save properties: {error}")
        self._hide_progress()

    # ========================================================================
    # Task Queue Event Handlers
    # ========================================================================

    def _on_task_completed(self, task_name: str, result):
        """Handle task completion"""
        self._log("DEBUG", f"Task completed: {task_name}")

    def _on_task_failed(self, task_name: str, error_msg: str):
        """Handle task failure"""
        self._log("ERROR", f"Task failed: {task_name} - {error_msg}")
        self._set_status(f"Error: {error_msg}")
        self._hide_progress()

    def _on_task_cancelled(self, task_name: str):
        """Handle task cancellation"""
        self._log("INFO", f"Task cancelled: {task_name}")

    # ========================================================================
    # Filter Updates
    # ========================================================================

    def _update_category_tree(self):
        """Update category section in the unified filter tree."""
        try:
            # Remove existing children
            while self._section_category.childCount():
                self._section_category.removeChild(self._section_category.child(0))

            all_item = QTreeWidgetItem(["All"])
            all_item.setData(0, Qt.ItemDataRole.UserRole, ('category', None))
            self._section_category.addChild(all_item)

            uncategorized = QTreeWidgetItem(["Uncategorized"])
            uncategorized.setData(0, Qt.ItemDataRole.UserRole, ('category', ""))
            self._section_category.addChild(uncategorized)

            for category in self.categories:
                item = QTreeWidgetItem([str(category)])
                item.setData(0, Qt.ItemDataRole.UserRole, ('category', category))
                self._section_category.addChild(item)

            self._section_category.setExpanded(True)
            self._refresh_filter_tree_highlights()
        except Exception as e:
            self._log("ERROR", f"Error updating category tree: {e}")

    def _update_tag_tree(self):
        """Update tag section in the unified filter tree."""
        try:
            while self._section_tag.childCount():
                self._section_tag.removeChild(self._section_tag.child(0))

            all_item = QTreeWidgetItem(["All"])
            all_item.setData(0, Qt.ItemDataRole.UserRole, ('tag', None))
            self._section_tag.addChild(all_item)

            untagged = QTreeWidgetItem(["Untagged"])
            untagged.setData(0, Qt.ItemDataRole.UserRole, ('tag', ""))
            self._section_tag.addChild(untagged)

            for tag in self.tags:
                item = QTreeWidgetItem([str(tag)])
                item.setData(0, Qt.ItemDataRole.UserRole, ('tag', tag))
                self._section_tag.addChild(item)

            self._section_tag.setExpanded(True)
            self._refresh_filter_tree_highlights()
        except Exception as e:
            self._log("ERROR", f"Error updating tag tree: {e}")

    def _calculate_size_buckets(self):
        """Calculate dynamic size buckets"""
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

    def _update_size_tree(self):
        """Update size section in the unified filter tree."""
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

    def _extract_trackers(self):
        """Extract unique tracker hostnames from loaded torrents."""
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

    def _update_tracker_tree(self):
        """Update tracker section in the unified filter tree."""
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

    # ========================================================================
    # Filter Application
    # ========================================================================

    def _on_quick_filter_changed(self, *_args):
        """Apply filter-bar changes immediately."""
        self._apply_filters()

    def _on_filter_changed(self):
        """Handle filter change from filter bar"""
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

    def _apply_filters(self):
        """Apply all current filters to torrents"""
        try:
            self._on_filter_changed()

            filtered = self.all_torrents[:]  # Make a copy

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
                        if bool(getattr(t, 'is_private', False)) == self.current_private_filter
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

    def _clear_filters(self):
        """Clear all filters"""
        self.cmb_private.setCurrentIndex(0)
        self.txt_name_filter.clear()
        self.txt_file_filter.clear()
        self.current_status_filter = 'all'
        self.current_category_filter = None
        self.current_tag_filter = None
        self.current_size_bucket = None
        self.current_tracker_filter = None

        # Clear tree selection
        self.tree_filters.clearSelection()
        self._refresh_filter_tree_highlights()

        self._refresh_torrents()

    def _on_filter_tree_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle click on the unified filter tree."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None and item.childCount() > 0:
            # Section header clicked — just toggle expand/collapse
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
        """Check if a torrent's tracker matches the given hostname."""
        tracker_url = getattr(torrent, 'tracker', '') or ''
        if not tracker_url:
            return False
        try:
            parsed = urlparse(tracker_url)
            return (parsed.hostname or tracker_url) == tracker_hostname
        except Exception:
            return tracker_url == tracker_hostname

    # ========================================================================
    # Table Updates
    # ========================================================================

    def _update_torrents_table(self):
        """Update the torrents table with filtered data"""
        try:
            self.tbl_torrents.setSortingEnabled(False)
            self.tbl_torrents.setRowCount(len(self.filtered_torrents))

            for row, torrent in enumerate(self.filtered_torrents):
                try:
                    size = getattr(torrent, 'size', 0)
                    progress = getattr(torrent, 'progress', 0)
                    dlspeed = getattr(torrent, 'dlspeed', 0)
                    upspeed = getattr(torrent, 'upspeed', 0)
                    ratio = getattr(torrent, 'ratio', 0)
                    seeds = getattr(torrent, 'num_seeds', 0)
                    peers = getattr(torrent, 'num_leechs', 0)
                    added_on = getattr(torrent, 'added_on', 0)

                    self._set_table_item(row, 0, getattr(torrent, 'hash', ''))
                    self._set_table_item(row, 1, getattr(torrent, 'name', ''))
                    self._set_table_item(
                        row, 2, format_size_mode(size, self.display_size_mode),
                        align=Qt.AlignmentFlag.AlignRight, sort_value=float(size)
                    )
                    self._set_table_item(row, 3, f"{progress * 100:.1f}%", align=Qt.AlignmentFlag.AlignRight, sort_value=float(progress))
                    self._set_table_item(row, 4, getattr(torrent, 'state', ''))
                    self._set_table_item(
                        row, 5, format_speed_mode(dlspeed, self.display_speed_mode),
                        align=Qt.AlignmentFlag.AlignRight, sort_value=float(dlspeed)
                    )
                    self._set_table_item(
                        row, 6, format_speed_mode(upspeed, self.display_speed_mode),
                        align=Qt.AlignmentFlag.AlignRight, sort_value=float(upspeed)
                    )
                    self._set_table_item(row, 7, format_float(ratio), align=Qt.AlignmentFlag.AlignRight, sort_value=float(ratio))
                    self._set_table_item(row, 8, format_int(seeds), align=Qt.AlignmentFlag.AlignRight, sort_value=float(seeds))
                    self._set_table_item(row, 9, format_int(peers), align=Qt.AlignmentFlag.AlignRight, sort_value=float(peers))
                    self._set_table_item(row, 10, format_datetime(added_on), sort_value=float(added_on))
                    self._set_table_item(row, 11, getattr(torrent, 'category', ''))

                    tags_str = ", ".join(parse_tags(getattr(torrent, 'tags', None)))
                    self._set_table_item(row, 12, tags_str, align=Qt.AlignmentFlag.AlignLeft)
                except Exception as e:
                    self._log("ERROR", f"Error updating row {row}: {e}")
                    continue

            self.tbl_torrents.setSortingEnabled(True)
            self.lbl_count.setText(f"{len(self.filtered_torrents)} torrents")
        except Exception as e:
            self._log("ERROR", f"Error updating torrents table: {e}")
            self.lbl_count.setText("0 torrents")

    def _set_table_item(self, row: int, col: int, text: str,
                        align=Qt.AlignmentFlag.AlignLeft,
                        sort_value: Optional[float] = None):
        """Helper to set table item with alignment and optional numeric sort."""
        if sort_value is not None:
            item = NumericTableWidgetItem(str(text), sort_value)
        else:
            item = QTableWidgetItem(str(text))
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        self.tbl_torrents.setItem(row, col, item)

    def _on_torrent_selected(self):
        """Handle torrent selection in table"""
        selected = self.tbl_torrents.selectedItems()
        if not selected:
            self._selected_torrent = None
            self.txt_details.clear()
            self.current_content_files = []
            self.tree_files.clear()
            return

        row = selected[0].row()
        torrent_hash = self.tbl_torrents.item(row, 0).text()

        # Find torrent in filtered list
        torrent = None
        for t in self.filtered_torrents:
            if t.hash == torrent_hash:
                torrent = t
                break

        if torrent:
            self._display_torrent_details(torrent)

    def _display_torrent_details(self, torrent):
        """Display detailed information about selected torrent."""
        self._selected_torrent = torrent
        try:
            tags_list = parse_tags(getattr(torrent, 'tags', None))
            tags_str = ', '.join(tags_list) if tags_list else 'None'

            completion_on = getattr(torrent, 'completion_on', 0)
            last_activity = getattr(torrent, 'last_activity', 0)
            is_private = getattr(torrent, 'is_private', None)
            private_str = 'Yes' if is_private else ('No' if is_private is False else 'N/A')
            num_files = getattr(torrent, 'num_files', 'N/A')
            content_path = getattr(torrent, 'content_path', 'N/A')

            details = f"""TORRENT DETAILS
{'=' * 80}

Name:           {getattr(torrent, 'name', 'N/A')}
Hash:           {getattr(torrent, 'hash', 'N/A')}
State:          {getattr(torrent, 'state', 'N/A')}
Size:           {format_size_mode(getattr(torrent, 'size', 0), self.display_size_mode)}
Total Size:     {format_size_mode(getattr(torrent, 'total_size', 0), self.display_size_mode)}
Progress:       {getattr(torrent, 'progress', 0) * 100:.2f}%
Private:        {private_str}
Files:          {num_files}

TRANSFER
{'=' * 80}

Downloaded:     {format_size_mode(getattr(torrent, 'downloaded', 0), self.display_size_mode)}
Uploaded:       {format_size_mode(getattr(torrent, 'uploaded', 0), self.display_size_mode)}
Download Speed: {format_speed_mode(getattr(torrent, 'dlspeed', 0), self.display_speed_mode)}
Upload Speed:   {format_speed_mode(getattr(torrent, 'upspeed', 0), self.display_speed_mode)}
Ratio:          {format_float(getattr(torrent, 'ratio', 0), 3)}

PEERS
{'=' * 80}

Seeds:          {getattr(torrent, 'num_seeds', 0)} ({getattr(torrent, 'num_complete', 0)})
Peers:          {getattr(torrent, 'num_leechs', 0)} ({getattr(torrent, 'num_incomplete', 0)})

METADATA
{'=' * 80}

Category:       {getattr(torrent, 'category', 'None')}
Tags:           {tags_str}
Added On:       {format_datetime(getattr(torrent, 'added_on', 0))}
Completion On:  {format_datetime(completion_on) if completion_on > 0 else 'N/A'}
Last Activity:  {format_datetime(last_activity) if last_activity > 0 else 'N/A'}
Save Path:      {getattr(torrent, 'save_path', 'N/A')}
Content Path:   {content_path}
"""
            self.txt_details.setPlainText(details.strip())

            # Populate editable fields
            self.edit_name.setText(getattr(torrent, 'name', ''))
            self.edit_category.clear()
            self.edit_category.addItems([''] + self.categories)
            current_cat = getattr(torrent, 'category', '')
            idx = self.edit_category.findText(current_cat)
            if idx >= 0:
                self.edit_category.setCurrentIndex(idx)
            else:
                self.edit_category.setEditText(current_cat)
            self.edit_tags.setText(', '.join(tags_list))
            self.edit_save_path.setText(getattr(torrent, 'save_path', ''))

            # Show file content from local cache
            self._show_cached_torrent_content(torrent.hash)
        except Exception as e:
            self._log("ERROR", f"Error displaying torrent details: {e}")
            self.txt_details.setPlainText(f"Error displaying details: {e}")

    # ========================================================================
    # Actions
    # ========================================================================

    def _show_torrent_context_menu(self, pos):
        """Show right-click context menu on the torrent table."""
        item = self.tbl_torrents.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        menu.addAction("Pause", self._pause_torrent)
        menu.addAction("Resume", self._resume_torrent)
        menu.addSeparator()
        menu.addAction("Delete...", self._delete_torrent)
        menu.addSeparator()
        menu.addAction("Copy Hash", self._copy_torrent_hash)
        menu.exec(self.tbl_torrents.viewport().mapToGlobal(pos))

    def _copy_torrent_hash(self):
        """Copy selected torrent hash to clipboard."""
        torrent_hash = self._get_selected_torrent_hash()
        if torrent_hash:
            QApplication.clipboard().setText(torrent_hash)
            self._set_status("Hash copied to clipboard")

    def _save_torrent_properties(self):
        """Save edited torrent properties via API."""
        torrent = getattr(self, '_selected_torrent', None)
        if not torrent:
            return
        props = {}
        new_name = self.edit_name.text().strip()
        if new_name and new_name != getattr(torrent, 'name', ''):
            props['name'] = new_name
        new_cat = self.edit_category.currentText()
        if new_cat != getattr(torrent, 'category', ''):
            props['category'] = new_cat
        new_tags = self.edit_tags.text().strip()
        old_tags = ', '.join(parse_tags(getattr(torrent, 'tags', None)))
        if new_tags != old_tags:
            props['tags'] = new_tags
        new_path = self.edit_save_path.text().strip()
        if new_path and new_path != getattr(torrent, 'save_path', ''):
            props['save_path'] = new_path
        if not props:
            self._set_status("No changes to save")
            return
        self._log("INFO", f"Saving properties for {torrent.hash}: {list(props.keys())}")
        self._show_progress("Saving properties...")
        self.api_queue.add_task(
            "save_properties",
            self._api_save_torrent_properties,
            self._on_save_properties_done,
            torrent.hash, props
        )

    def _refresh_torrents(self):
        """Refresh torrent list"""
        self._log("INFO", "Refreshing torrents...")
        self._show_progress("Refreshing torrents...")

        self.api_queue.add_task(
            "refresh_torrents",
            self._fetch_torrents,
            self._on_torrents_loaded
        )

    def _show_add_torrent_dialog(self):
        """Show add torrent dialog"""
        dialog = AddTorrentDialog(self.categories, self.tags, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            torrent_data = dialog.get_torrent_data()
            if torrent_data:
                self._log("INFO", "Adding torrent...")
                self._show_progress("Adding torrent...")

                self.api_queue.add_task(
                    "add_torrent",
                    self._add_torrent_api,
                    self._on_add_torrent_complete,
                    torrent_data
                )

    def _get_selected_torrent_hash(self) -> Optional[str]:
        """Get the hash of the currently selected torrent, or None."""
        selected = self.tbl_torrents.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self.tbl_torrents.item(row, 0)
        return item.text() if item else None

    def _on_torrent_action_done(self, action_name: str, result: Dict):
        """Generic callback for pause/resume/delete actions."""
        if result.get('success'):
            self._log("INFO", f"{action_name} succeeded", result.get('elapsed', 0))
            QTimer.singleShot(500, self._refresh_torrents)
        else:
            error = result.get('error', 'Unknown error')
            self._log("ERROR", f"{action_name} failed: {error}", result.get('elapsed', 0))
            self._set_status(f"{action_name} failed: {error}")
        self._hide_progress()

    def _pause_torrent(self):
        """Pause selected torrent"""
        torrent_hash = self._get_selected_torrent_hash()
        if torrent_hash:
            self._log("INFO", f"Pausing torrent: {torrent_hash}")
            self._show_progress("Pausing torrent...")
            self.api_queue.add_task(
                "pause_torrent",
                self._api_pause_torrent,
                lambda r: self._on_torrent_action_done("Pause", r),
                torrent_hash
            )

    def _resume_torrent(self):
        """Resume selected torrent"""
        torrent_hash = self._get_selected_torrent_hash()
        if torrent_hash:
            self._log("INFO", f"Resuming torrent: {torrent_hash}")
            self._show_progress("Resuming torrent...")
            self.api_queue.add_task(
                "resume_torrent",
                self._api_resume_torrent,
                lambda r: self._on_torrent_action_done("Resume", r),
                torrent_hash
            )

    def _delete_torrent(self):
        """Delete selected torrent with confirmation"""
        torrent_hash = self._get_selected_torrent_hash()
        if not torrent_hash:
            return
        reply = QMessageBox.question(
            self, "Delete Torrent",
            "Delete torrent and its files from disk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return
        delete_files = (reply == QMessageBox.StandardButton.Yes)
        self._log("INFO", f"Deleting torrent: {torrent_hash} (files={delete_files})")
        self._show_progress("Deleting torrent...")
        self.api_queue.add_task(
            "delete_torrent",
            self._api_delete_torrent,
            lambda r: self._on_torrent_action_done("Delete", r),
            torrent_hash, delete_files
        )

    # ========================================================================
    # Menu Actions
    # ========================================================================

    def _clear_cache_and_refresh(self):
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
        except Exception as e:
            self._log("ERROR", f"Failed to clear cache: {e}")
            self._set_status(f"Failed to clear cache: {e}")

        self._refresh_torrents()

    def _reset_view_defaults(self):
        """Reset view/layout/filter/refresh options back to startup defaults."""
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

            if self.auto_refresh_enabled:
                self.refresh_timer.start(self.refresh_interval * 1000)
            else:
                self.refresh_timer.stop()

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

    def _open_log_file(self):
        """Open the log file in the OS default application."""
        import subprocess
        log_path = os.path.abspath(self.log_file_path)
        try:
            if sys.platform == 'win32':
                os.startfile(log_path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', log_path])
            else:
                subprocess.Popen(['xdg-open', log_path])
        except Exception as e:
            self._log("ERROR", f"Failed to open log file: {e}")
            self._set_status(f"Failed to open log file: {e}")

    def _set_auto_refresh_interval(self):
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
            if self.auto_refresh_enabled:
                self.refresh_timer.start(self.refresh_interval * 1000)

            self._log("INFO", f"Auto-refresh interval set to {self.refresh_interval}s")
            self._set_status(f"Auto-refresh interval: {self.refresh_interval}s")
            self._save_refresh_settings()
        except Exception as e:
            self._log("ERROR", f"Failed to set auto-refresh interval: {e}")
            self._set_status(f"Failed to set auto-refresh interval: {e}")

    def _toggle_auto_refresh(self, checked: bool):
        """Toggle auto-refresh"""
        self.auto_refresh_enabled = checked
        if checked:
            self.refresh_timer.start(self.refresh_interval * 1000)
            self._log("INFO", f"Auto-refresh enabled ({self.refresh_interval}s)")
        else:
            self.refresh_timer.stop()
            self._log("INFO", "Auto-refresh disabled")
        self._save_refresh_settings()

    def _show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About qBiremo Enhanced",
            "qBiremo Enhanced v2.0\n\n"
            "Advanced qBittorrent GUI Client\n"
            "Built with PySide6\n\n"
            "© 2025"
        )

    # ========================================================================
    # UI Helper Methods
    # ========================================================================

    def _show_progress(self, message: str):
        """Show progress indicator"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self._set_status(message)

    def _hide_progress(self):
        """Hide progress indicator"""
        self.progress_bar.setVisible(False)
        self._set_status("Ready")

    def _set_status(self, message: str):
        """Set status bar message"""
        self.lbl_status.setText(message)

    def _update_window_title_speeds(self):
        """Show aggregate up/down speeds in the window title."""
        try:
            total_down = 0
            total_up = 0
            for torrent in self.all_torrents:
                total_down += self._safe_int(getattr(torrent, 'dlspeed', 0), 0)
                total_up += self._safe_int(getattr(torrent, 'upspeed', 0), 0)

            up_text = format_speed_mode(total_up, self.display_speed_mode) or "0"
            down_text = format_speed_mode(total_down, self.display_speed_mode) or "0"
            self.setWindowTitle(
                f"U:{up_text} D:{down_text}"
            )
        except Exception:
            # Keep title stable even if malformed data appears.
            self.setWindowTitle(f"0")

    def _log(self, level: str, message: str, elapsed: Optional[float] = None):
        """Write to Python file logger."""
        elapsed_str = f" [{elapsed:.3f}s]" if elapsed is not None else ""
        log_msg = f"{message}{elapsed_str}"
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, log_msg)

    # ========================================================================
    # Window Events
    # ========================================================================

    def closeEvent(self, event):
        """Handle window close event"""
        self._save_settings()
        self._save_content_cache()
        event.accept()


# ============================================================================
# Application Entry Point
# ============================================================================

def load_config(config_file: str) -> Dict[str, Any]:
    """Load configuration from TOML file"""
    if os.path.exists(config_file):
        try:
            import tomllib
            with open(config_file, 'rb') as f:
                return tomllib.load(f)
        except Exception as e:
            logger.error("Failed to load config file %s: %s", config_file, e)
            return {}
    return {}


def load_config_with_issues(config_file: str) -> Tuple[Dict[str, Any], List[str]]:
    """Load TOML config and collect load-time issues without requiring logging."""
    issues: List[str] = []
    if not os.path.exists(config_file):
        issues.append(
            f"Config file not found: {config_file}. Using built-in defaults and environment fallbacks."
        )
        return {}, issues

    try:
        import tomllib
        with open(config_file, 'rb') as f:
            data = tomllib.load(f)
    except Exception as e:
        issues.append(f"Failed to parse config file {config_file}: {e}. Using defaults.")
        return {}, issues

    if not isinstance(data, dict):
        issues.append(
            f"Config file {config_file} did not parse to a TOML table/object. Using defaults."
        )
        return {}, issues

    return data, issues


def validate_and_normalize_config(config: Dict[str, Any], config_file: str) -> Dict[str, Any]:
    """Validate config values, log issues, and return a sanitized config dict."""
    if not isinstance(config, dict):
        logger.warning(
            "Config validation: root config from %s is not a TOML table/object. Using defaults.",
            config_file
        )
        config = {}

    normalized = dict(config)
    known_keys = {
        "qb_host", "qb_port", "qb_username", "qb_password",
        "http_basic_auth_username", "http_basic_auth_password",
        "auto_refresh", "refresh_interval",
        "default_window_width", "default_window_height",
        "display_size_mode", "display_speed_mode",
        "default_status_filter", "log_file",
        "_log_file_path",
    }

    legacy_map = {
        "host": "qb_host",
        "port": "qb_port",
        "username": "qb_username",
        "password": "qb_password",
        "http_user": "http_basic_auth_username",
        "http_password": "http_basic_auth_password",
    }

    def _warn(msg: str):
        logger.warning("Config validation: %s", msg)

    def _coerce_bool(value: Any, default: bool) -> Tuple[bool, bool]:
        if isinstance(value, bool):
            return value, True
        if isinstance(value, (int, float)):
            if value in {0, 1}:
                return bool(value), True
            return bool(value), False
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True, True
            if text in {"0", "false", "no", "off"}:
                return False, True
        return default, False

    def _coerce_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    for old_key, new_key in legacy_map.items():
        if new_key not in normalized and old_key in normalized:
            normalized[new_key] = normalized.get(old_key)
            _warn(
                f"'{old_key}' is deprecated; use '{new_key}'. "
                f"Using '{old_key}' value for now."
            )

    # qb_host
    host_val = normalized.get("qb_host", "localhost")
    if not isinstance(host_val, str) or not host_val.strip():
        _warn(f"'qb_host' invalid ({host_val!r}); using 'localhost'.")
        normalized["qb_host"] = "localhost"
    else:
        normalized["qb_host"] = host_val.strip()

    # qb_port
    raw_port = normalized.get("qb_port", 8080)
    port = _coerce_int(raw_port, 8080)
    if port < 1 or port > 65535:
        _warn(f"'qb_port' out of range ({raw_port!r}); using 8080.")
        port = 8080
    normalized["qb_port"] = port

    # Credentials
    for key, default_value in [
        ("qb_username", "admin"),
        ("qb_password", ""),
        ("http_basic_auth_username", ""),
        ("http_basic_auth_password", ""),
    ]:
        val = normalized.get(key, default_value)
        if val is None:
            val = default_value
        if not isinstance(val, str):
            _warn(f"'{key}' should be a string; using default.")
            val = str(default_value)
        normalized[key] = val

    # auto_refresh
    raw_auto_refresh = normalized.get("auto_refresh", DEFAULT_AUTO_REFRESH)
    auto_refresh, auto_refresh_valid = _coerce_bool(
        raw_auto_refresh,
        DEFAULT_AUTO_REFRESH
    )
    if not auto_refresh_valid:
        _warn(
            f"'auto_refresh' invalid ({raw_auto_refresh!r}); using {DEFAULT_AUTO_REFRESH}."
        )
    normalized["auto_refresh"] = auto_refresh

    # refresh_interval
    raw_interval = normalized.get("refresh_interval", DEFAULT_REFRESH_INTERVAL)
    interval = _coerce_int(raw_interval, DEFAULT_REFRESH_INTERVAL)
    if interval < 1:
        _warn(
            f"'refresh_interval' must be >= 1 ({raw_interval!r}); using {DEFAULT_REFRESH_INTERVAL}."
        )
        interval = DEFAULT_REFRESH_INTERVAL
    normalized["refresh_interval"] = interval

    # window dimensions
    raw_width = normalized.get("default_window_width", 1400)
    width = _coerce_int(raw_width, 1400)
    if width < 600:
        _warn(f"'default_window_width' too small ({raw_width!r}); using 1400.")
        width = 1400
    normalized["default_window_width"] = width

    raw_height = normalized.get("default_window_height", 800)
    height = _coerce_int(raw_height, 800)
    if height < 400:
        _warn(f"'default_window_height' too small ({raw_height!r}); using 800.")
        height = 800
    normalized["default_window_height"] = height

    # display modes
    raw_size_mode = normalized.get("display_size_mode", DEFAULT_DISPLAY_SIZE_MODE)
    size_mode = _normalize_display_mode(raw_size_mode, DEFAULT_DISPLAY_SIZE_MODE)
    if size_mode != str(raw_size_mode).strip().lower():
        _warn(
            f"'display_size_mode' invalid ({raw_size_mode!r}); "
            f"using '{DEFAULT_DISPLAY_SIZE_MODE}'."
        )
    normalized["display_size_mode"] = size_mode

    raw_speed_mode = normalized.get("display_speed_mode", DEFAULT_DISPLAY_SPEED_MODE)
    speed_mode = _normalize_display_mode(raw_speed_mode, DEFAULT_DISPLAY_SPEED_MODE)
    if speed_mode != str(raw_speed_mode).strip().lower():
        _warn(
            f"'display_speed_mode' invalid ({raw_speed_mode!r}); "
            f"using '{DEFAULT_DISPLAY_SPEED_MODE}'."
        )
    normalized["display_speed_mode"] = speed_mode

    # default status filter
    raw_status = normalized.get("default_status_filter", DEFAULT_STATUS_FILTER)
    status = str(raw_status or "").strip().lower()
    if status not in STATUS_FILTERS:
        _warn(
            f"'default_status_filter' invalid ({raw_status!r}); using '{DEFAULT_STATUS_FILTER}'."
        )
        status = DEFAULT_STATUS_FILTER
    normalized["default_status_filter"] = status

    # log_file
    raw_log_file = normalized.get("log_file", "qbiremo_enhanced.log")
    if not isinstance(raw_log_file, str) or not raw_log_file.strip():
        _warn(
            f"'log_file' invalid ({raw_log_file!r}); using 'qbiremo_enhanced.log'."
        )
        normalized["log_file"] = "qbiremo_enhanced.log"
    else:
        normalized["log_file"] = raw_log_file.strip()

    # Unknown keys warning (except explicit internal keys)
    unknown_keys = sorted(
        key for key in normalized.keys()
        if key not in known_keys and key not in legacy_map
    )
    for key in unknown_keys:
        _warn(f"Unknown config key '{key}' will be ignored.")

    logger.info("Configuration validated from %s", config_file)
    return normalized


def _setup_logging(config: Dict[str, Any]) -> logging.FileHandler:
    """Configure file logging and return the handler so it can be flushed."""
    log_file = config.get('log_file', 'qbiremo_enhanced.log')
    if not isinstance(log_file, str) or not log_file.strip():
        log_file = 'qbiremo_enhanced.log'
    log_file = log_file.strip()
    config['_log_file_path'] = log_file

    try:
        log_dir = os.path.dirname(os.path.abspath(log_file))
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
    except Exception:
        # Directory creation failure will be handled by FileHandler fallback.
        pass

    try:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
    except Exception:
        # Fallback to local path if configured log path is not writable.
        fallback_log_file = 'qbiremo_enhanced.log'
        config['_log_file_path'] = fallback_log_file
        file_handler = logging.FileHandler(fallback_log_file, encoding='utf-8')

    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)-7s %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.setLevel(logging.DEBUG)
    return file_handler


def _open_file_in_default_app(path: str):
    """Open a file in the platform default application."""
    if not path:
        return

    import subprocess

    try:
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception:
        logger.exception("Failed to open file in default app: %s", path)


def _install_exception_hooks(file_handler: logging.FileHandler):
    """Install global hooks so that *every* unhandled exception is logged.

    On Windows GUI apps stderr is often /dev/null, so without this any
    exception that escapes a PySide6 slot vanishes silently.
    """
    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_tb)
        )
        file_handler.flush()

    sys.excepthook = _excepthook

    # Also flush the log file on normal exit so nothing is lost
    atexit.register(file_handler.flush)


def main():
    """Main application entry point"""
    parser = argparse.ArgumentParser(
        description="qBiremo Enhanced - Advanced qBittorrent GUI Client"
    )
    parser.add_argument(
        "-c", "--config-file",
        required=False,
        default="qbiremo_enhanced_config.toml",
        help="Path to configuration file (TOML format)"
    )

    args = parser.parse_args()

    # Load configuration (collect load-time issues before logging is configured)
    config, load_issues = load_config_with_issues(args.config_file)

    # Set up logging *first*, then install the global exception hook
    file_handler = _setup_logging(config)
    _install_exception_hooks(file_handler)
    for issue in load_issues:
        logger.warning("%s", issue)

    # Validate and normalize config values now that file logging is active.
    config = validate_and_normalize_config(config, args.config_file)

    try:
        # Create application
        app = QApplication(sys.argv)
        app.setOrganizationName(G_ORG_NAME)
        app.setApplicationName(G_APP_NAME)
        app.setApplicationDisplayName("qBiremo Enhanced")

        # Create and show main window
        window = MainWindow(config)

        # Run application
        sys.exit(app.exec())
    except SystemExit:
        raise
    except Exception:
        logger.critical("Fatal error during startup", exc_info=True)
        file_handler.flush()
        _open_file_in_default_app(config.get('_log_file_path', 'qbiremo_enhanced.log'))
        raise


if __name__ == "__main__":
    main()
