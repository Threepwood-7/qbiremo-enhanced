#!/usr/bin/env python3
"""
qBiremo Enhanced - Advanced qBittorrent GUI Client
A feature-rich PySide6-based GUI for managing qBittorrent remotely
"""

import os
import sys
import argparse
import atexit
import copy
import html
import hashlib
import json
import logging
import math
import traceback
import tempfile
import base64
import re
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, Dict, List, Any, Tuple
from urllib.parse import quote, urlparse
import time
import fnmatch
from collections import deque

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QTextEdit, QFrame, QStatusBar,
    QAbstractItemView, QHeaderView, QFormLayout, QSpinBox, QDoubleSpinBox, QGroupBox,
    QProgressBar, QMenu, QMessageBox, QTabWidget, QListWidget, QListWidgetItem,
    QInputDialog,
    QSizePolicy
)
from PySide6.QtCore import (
    Qt, QTimer, QRunnable, Slot, Signal, QObject, QThreadPool, QSettings, QEvent
)
from PySide6.QtGui import (
    QAction,
    QIcon,
    QColor,
    QBrush,
    QShortcut,
    QKeySequence,
    QPainter,
    QPen,
    QFontDatabase,
)

import qbittorrentapi


# ============================================================================
# Configuration and Constants
# ============================================================================

G_ORG_NAME = "qBiremo"
G_APP_NAME = "qBiremoEnhanced"
DEFAULT_REFRESH_INTERVAL = 60  # seconds
DEFAULT_AUTO_REFRESH = True
DEFAULT_STATUS_FILTER = 'active'
DEFAULT_WINDOW_WIDTH = 1400
DEFAULT_WINDOW_HEIGHT = 800
DEFAULT_LEFT_PANEL_WIDTH = 220
DEFAULT_DISPLAY_SIZE_MODE = 'bytes'
DEFAULT_DISPLAY_SPEED_MODE = 'bytes'
DEFAULT_TITLE_BAR_SPEED_FORMAT = "[D: {down_text}, U: {up_text}]"
CACHE_TEMP_SUBDIR = "qbiremo_enhanced_temp"
CACHE_FILE_NAME = "qbiremo_enhanced.cache"
CACHE_MAX_AGE_DAYS = 3
INSTANCE_ID_LENGTH = 8
CLIPBOARD_SEEN_LIMIT = 256

logger = logging.getLogger(G_APP_NAME)

# Status filters as per qBittorrent API
STATUS_FILTERS = [
    'all', 'downloading', 'seeding', 'completed', 'paused', 'stopped',
    'active', 'inactive', 'resumed', 'running', 'stalled',
    'stalled_uploading', 'stalled_downloading', 'checking', 'moving', 'errored'
]

# Size buckets in bytes (will be dynamically calculated)
SIZE_BUCKET_COUNT = 5

TORRENT_COLUMNS = [
    {"key": "hash", "label": "Hash", "width": 240, "default_visible": True},
    {"key": "name", "label": "Name", "width": 360, "default_visible": True},
    {"key": "size", "label": "Size", "width": 110, "default_visible": True},
    {"key": "total_size", "label": "Total Size", "width": 110, "default_visible": True},
    {"key": "progress", "label": "Progress", "width": 80, "default_visible": True},
    {"key": "state", "label": "Status", "width": 110, "default_visible": True},
    {"key": "dlspeed", "label": "DL Speed", "width": 100, "default_visible": True},
    {"key": "upspeed", "label": "UP Speed", "width": 100, "default_visible": True},
    {"key": "dl_limit", "label": "Download Speed Limit", "width": 150, "default_visible": True},
    {"key": "up_limit", "label": "Upload Speed Limit", "width": 150, "default_visible": True},
    {"key": "downloaded", "label": "Downloaded", "width": 110, "default_visible": True},
    {"key": "uploaded", "label": "Uploaded", "width": 110, "default_visible": True},
    {"key": "amount_left", "label": "Amount Left", "width": 120, "default_visible": True},
    {"key": "completed", "label": "Completed", "width": 110, "default_visible": True},
    {"key": "downloaded_session", "label": "Downloaded Session", "width": 160, "default_visible": True},
    {"key": "uploaded_session", "label": "Uploaded Session", "width": 160, "default_visible": True},
    {"key": "ratio", "label": "Ratio", "width": 70, "default_visible": True},
    {"key": "ratio_limit", "label": "Ratio Limit", "width": 100, "default_visible": True},
    {"key": "max_ratio", "label": "Max Ratio", "width": 90, "default_visible": True},
    {"key": "availability", "label": "Availability", "width": 110, "default_visible": True},
    {"key": "num_seeds", "label": "Seeds", "width": 70, "default_visible": True},
    {"key": "num_leechs", "label": "Peers", "width": 70, "default_visible": True},
    {"key": "num_complete", "label": "Complete", "width": 80, "default_visible": True},
    {"key": "num_incomplete", "label": "Incomplete", "width": 90, "default_visible": True},
    {"key": "priority", "label": "Priority", "width": 80, "default_visible": True},
    {"key": "eta", "label": "ETA", "width": 90, "default_visible": True},
    {"key": "reannounce", "label": "Reannounce", "width": 110, "default_visible": True},
    {"key": "seeding_time", "label": "Seeding Time", "width": 120, "default_visible": True},
    {"key": "seeding_time_limit", "label": "Seeding Time Limit", "width": 140, "default_visible": True},
    {"key": "max_seeding_time", "label": "Max Seeding Time", "width": 130, "default_visible": True},
    {"key": "time_active", "label": "Time Active", "width": 120, "default_visible": True},
    {"key": "added_on", "label": "Added On", "width": 150, "default_visible": True},
    {"key": "completion_on", "label": "Completed On", "width": 150, "default_visible": True},
    {"key": "last_activity", "label": "Last Activity", "width": 150, "default_visible": True},
    {"key": "seen_complete", "label": "Seen Complete", "width": 150, "default_visible": True},
    {"key": "auto_tmm", "label": "Auto TMM", "width": 100, "default_visible": True},
    {"key": "force_start", "label": "Force Start", "width": 100, "default_visible": True},
    {"key": "seq_dl", "label": "Sequential Download", "width": 150, "default_visible": True},
    {"key": "f_l_piece_prio", "label": "First/Last Piece Prio", "width": 160, "default_visible": True},
    {"key": "super_seeding", "label": "Super Seeding", "width": 120, "default_visible": True},
    {"key": "private", "label": "Private", "width": 80, "default_visible": True},
    {"key": "category", "label": "Category", "width": 120, "default_visible": True},
    {"key": "tags", "label": "Tags", "width": 150, "default_visible": True},
    {"key": "tracker", "label": "Tracker", "width": 170, "default_visible": True},
    {"key": "save_path", "label": "Save Path", "width": 220, "default_visible": True},
    {"key": "content_path", "label": "Content Path", "width": 260, "default_visible": True},
    {"key": "magnet_uri", "label": "Magnet URI", "width": 280, "default_visible": True},
    {"key": "num_files", "label": "Files", "width": 70, "default_visible": True},
]

BASIC_TORRENT_VIEW_KEYS = (
    "name",
    "state",
    "progress",
    "size",
    "dlspeed",
    "upspeed",
    "ratio",
    "eta",
    "num_seeds",
    "num_leechs",
    "category",
    "tags",
)

MEDIUM_TORRENT_VIEW_KEYS = (
    "name",
    "state",
    "progress",
    "size",
    "total_size",
    "dlspeed",
    "upspeed",
    "dl_limit",
    "up_limit",
    "downloaded",
    "uploaded",
    "ratio",
    "eta",
    "num_seeds",
    "num_leechs",
    "num_complete",
    "num_incomplete",
    "category",
    "tags",
    "tracker",
    "private",
    "added_on",
    "last_activity",
    "save_path",
)

_medium_default_keys = set(MEDIUM_TORRENT_VIEW_KEYS)
for _column in TORRENT_COLUMNS:
    _column["default_visible"] = _column["key"] in _medium_default_keys


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
        was_cancelled = False
        try:
            if self.is_cancelled:
                was_cancelled = True
                return
            result = self.fn(*self.args, **self.kwargs)
            if self.is_cancelled:
                was_cancelled = True
                return
            self.signals.result.emit(result)
        except Exception:
            if self.is_cancelled:
                was_cancelled = True
            else:
                exctype, value = sys.exc_info()[:2]
                self.signals.error.emit((exctype, value, traceback.format_exc()))
        finally:
            if was_cancelled:
                self.signals.cancelled.emit()
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
        self.pending_task = None

    def _start_task(self, task_name: str, fn, callback, *args, **kwargs):
        """Create one worker and start processing."""
        self.is_processing = True
        self.current_task_name = task_name

        worker = Worker(fn, *args, **kwargs)
        self.current_worker = worker

        worker.signals.result.connect(
            lambda result, _worker=worker: self._on_task_complete(
                _worker,
                task_name,
                callback,
                result,
            )
        )
        worker.signals.error.connect(
            lambda error, _worker=worker: self._on_task_error(
                _worker,
                task_name,
                error,
            )
        )
        worker.signals.cancelled.connect(
            lambda _worker=worker: self._on_task_cancelled(_worker, task_name)
        )
        worker.signals.finished.connect(
            lambda _worker=worker: self._on_worker_finished(_worker)
        )
        self.threadpool.start(worker)

    def add_task(self, task_name: str, fn, callback, *args, **kwargs):
        """Add a task to the queue, coalescing to latest while one is running."""
        if self.current_worker:
            self.current_worker.cancel()
            self.pending_task = (task_name, fn, callback, args, kwargs)
            self.is_processing = True
            return

        self._start_task(task_name, fn, callback, *args, **kwargs)

    def clear_queue(self):
        """Cancel current task and drop any queued replacement task."""
        if self.current_worker:
            self.current_worker.cancel()
        self.pending_task = None
        if not self.current_worker:
            self.is_processing = False
            self.current_task_name = None

    def _on_task_complete(self, worker: Worker, task_name: str, callback, result):
        """Handle successful task completion"""
        if worker is not self.current_worker:
            logger.debug("Ignoring stale task completion: %s", task_name)
            return
        try:
            if callback:
                callback(result)
            self.task_completed.emit(task_name, result)
        except Exception as e:
            self.task_failed.emit(task_name, str(e))

    def _on_task_error(self, worker: Worker, task_name: str, error):
        """Handle task failure"""
        if worker is not self.current_worker:
            logger.debug("Ignoring stale task error: %s", task_name)
            return
        try:
            exctype, value, trace = error
            error_msg = f"{exctype.__name__}: {value}"
            logger.error("Task %s failed:\n%s", task_name, trace)
            self.task_failed.emit(task_name, error_msg)
        except Exception as e:
            logger.error("Error in _on_task_error for %s: %s", task_name, e)
            self.task_failed.emit(task_name, str(e))

    def _on_task_cancelled(self, worker: Worker, task_name: str):
        """Handle task cancellation"""
        if worker is not self.current_worker:
            return
        try:
            self.task_cancelled.emit(task_name)
        except Exception as e:
            logger.error("Error in _on_task_cancelled for %s: %s", task_name, e)

    def _on_worker_finished(self, worker: Worker):
        """Finalize worker lifecycle and start latest pending task, if any."""
        if worker is not self.current_worker:
            return

        self.current_worker = None
        self.current_task_name = None
        self.is_processing = False

        pending = self.pending_task
        self.pending_task = None
        if pending:
            task_name, fn, callback, args, kwargs = pending
            self._start_task(task_name, fn, callback, *args, **kwargs)


class _DebugAPIClientProxy:
    """Proxy that logs qBittorrent API calls and responses."""

    def __init__(self, client: Any, owner: "MainWindow"):
        self._client = client
        self._owner = owner

    def __enter__(self):
        entered = self._client.__enter__()
        if entered is self._client:
            return self
        return _DebugAPIClientProxy(entered, self._owner)

    def __exit__(self, exc_type, exc, tb):
        return self._client.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str):
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def _wrapped(*args, **kwargs):
            self._owner._debug_log_api_call(name, args, kwargs)
            start_time = time.time()
            try:
                result = attr(*args, **kwargs)
            except Exception as e:
                elapsed = time.time() - start_time
                self._owner._debug_log_api_error(name, e, elapsed)
                raise
            elapsed = time.time() - start_time
            self._owner._debug_log_api_response(name, result, elapsed)
            return result

        return _wrapped


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
        grp_source = QGroupBox("Torrent Sources")
        src_layout = QVBoxLayout(grp_source)

        file_layout = QHBoxLayout()
        self.txt_torrent_files = QTextEdit()
        self.txt_torrent_files.setPlaceholderText(
            "Torrent files (one path per line)."
        )
        self.txt_torrent_files.setFixedHeight(86)
        btn_browse_files = QPushButton("Browse Files...")
        btn_browse_files.clicked.connect(self._browse_files)
        file_layout.addWidget(self.txt_torrent_files, 1)
        file_layout.addWidget(btn_browse_files)
        src_layout.addLayout(file_layout)

        url_layout = QHBoxLayout()
        self.txt_source_urls = QTextEdit()
        self.txt_source_urls.setPlaceholderText(
            "Magnet links / URLs (one per line)."
        )
        self.txt_source_urls.setFixedHeight(86)
        url_layout.addWidget(self.txt_source_urls, 1)
        src_layout.addLayout(url_layout)

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

    def accept(self):
        """Validate and cache torrent payload before closing the dialog."""
        payload = self.get_torrent_data()
        if not payload:
            return
        self.torrent_data = payload
        super().accept()

    def _browse_files(self):
        """Browse and append one or more torrent files."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Torrent Files", "", "Torrent Files (*.torrent);;All Files (*)"
        )
        if file_paths:
            self._append_multiline_entries(self.txt_torrent_files, file_paths)

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

    @staticmethod
    def _split_multiline(text: str) -> List[str]:
        return [line.strip() for line in str(text or "").splitlines() if line.strip()]

    def _append_multiline_entries(self, editor: QTextEdit, entries: List[str]):
        existing = self._split_multiline(editor.toPlainText())
        combined = existing + [str(entry).strip() for entry in (entries or []) if str(entry).strip()]
        # Preserve order while removing duplicates.
        deduped = list(dict.fromkeys(combined))
        editor.setPlainText("\n".join(deduped))

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
    def _parse_url_sources(lines: List[str]):
        # Accept one URL per line for convenience.
        if not lines:
            return ""
        if len(lines) == 1:
            return lines[0]
        return lines

    def get_torrent_data(self) -> Optional[Dict[str, Any]]:
        """Get the torrent data from the dialog"""
        source_files = self._split_multiline(self.txt_torrent_files.toPlainText())
        source_urls = self._split_multiline(self.txt_source_urls.toPlainText())
        if not source_files and not source_urls:
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

        # Sources
        if source_files:
            missing_files = [path for path in source_files if not os.path.exists(path)]
            if missing_files:
                QMessageBox.warning(
                    self,
                    "Torrent File Not Found",
                    "File does not exist:\n" + "\n".join(missing_files),
                )
                return None
            data['torrent_files'] = source_files[0] if len(source_files) == 1 else source_files

        if source_urls:
            invalid_urls = [url for url in source_urls if not self._is_url_source(url)]
            if invalid_urls:
                QMessageBox.warning(
                    self,
                    "Invalid Magnet/URL",
                    "These entries are not valid magnet links or URLs:\n"
                    + "\n".join(invalid_urls),
                )
                return None
            data['urls'] = self._parse_url_sources(source_urls)

        return data


# ============================================================================
# Taxonomy Manager Dialog
# ============================================================================

class TaxonomyManagerDialog(QDialog):
    """Dialog to manage categories and tags in one place."""

    create_category_requested = Signal(str, str, str, bool)
    edit_category_requested = Signal(str, str, str, bool)
    delete_category_requested = Signal(str)
    create_tags_requested = Signal(list)
    delete_tags_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Tags and Categories")
        self.resize(760, 520)

        self._category_data: Dict[str, Dict[str, Any]] = {}
        self._build_ui()
        self._set_category_create_mode()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Categories tab
        category_widget = QWidget()
        category_layout = QHBoxLayout(category_widget)
        category_layout.setContentsMargins(4, 4, 4, 4)

        self.lst_categories = QListWidget()
        self.lst_categories.currentItemChanged.connect(self._on_category_selection_changed)
        category_layout.addWidget(self.lst_categories, 1)

        category_editor = QWidget()
        editor_layout = QVBoxLayout(category_editor)
        form = QFormLayout()

        self.txt_category_name = QLineEdit()
        form.addRow("Name:", self.txt_category_name)

        path_row = QHBoxLayout()
        self.txt_category_save_path = QLineEdit()
        btn_browse_path = QPushButton("Browse")
        btn_browse_path.clicked.connect(self._browse_category_save_path)
        path_row.addWidget(self.txt_category_save_path, 1)
        path_row.addWidget(btn_browse_path)
        form.addRow("Save Path:", path_row)

        self.chk_category_use_incomplete = QCheckBox("Use incomplete save path")
        self.chk_category_use_incomplete.toggled.connect(self._update_incomplete_path_enabled_state)
        form.addRow("", self.chk_category_use_incomplete)

        inc_row = QHBoxLayout()
        self.txt_category_incomplete_path = QLineEdit()
        self.txt_category_incomplete_path.setPlaceholderText("Optional incomplete path")
        self.btn_category_browse_incomplete = QPushButton("Browse")
        self.btn_category_browse_incomplete.clicked.connect(self._browse_category_incomplete_path)
        inc_row.addWidget(self.txt_category_incomplete_path, 1)
        inc_row.addWidget(self.btn_category_browse_incomplete)
        form.addRow("Incomplete Path:", inc_row)
        editor_layout.addLayout(form)

        category_actions = QHBoxLayout()
        self.btn_category_new = QPushButton("New")
        self.btn_category_new.clicked.connect(self._set_category_create_mode)
        category_actions.addWidget(self.btn_category_new)

        self.btn_category_apply = QPushButton("Create Category")
        self.btn_category_apply.clicked.connect(self._apply_category_changes)
        category_actions.addWidget(self.btn_category_apply)

        self.btn_category_delete = QPushButton("Delete Category")
        self.btn_category_delete.clicked.connect(self._delete_selected_category)
        category_actions.addWidget(self.btn_category_delete)
        editor_layout.addLayout(category_actions)
        editor_layout.addStretch(1)
        category_layout.addWidget(category_editor, 2)

        self.tabs.addTab(category_widget, "Categories")

        # Tags tab
        tags_widget = QWidget()
        tags_layout = QVBoxLayout(tags_widget)
        tags_layout.setContentsMargins(4, 4, 4, 4)

        self.lst_tags_manage = QListWidget()
        self.lst_tags_manage.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tags_layout.addWidget(self.lst_tags_manage, 1)

        add_tags_row = QHBoxLayout()
        self.txt_new_tags = QLineEdit()
        self.txt_new_tags.setPlaceholderText("Enter tag(s), comma-separated")
        add_tags_row.addWidget(self.txt_new_tags, 1)
        btn_add_tags = QPushButton("Add")
        btn_add_tags.clicked.connect(self._add_tags)
        add_tags_row.addWidget(btn_add_tags)
        tags_layout.addLayout(add_tags_row)

        btn_delete_tags = QPushButton("Delete Selected")
        btn_delete_tags.clicked.connect(self._delete_selected_tags)
        tags_layout.addWidget(btn_delete_tags)
        self.btn_add_tags = btn_add_tags
        self.btn_delete_tags = btn_delete_tags

        self.tabs.addTab(tags_widget, "Tags")

        self.lbl_message = QLabel("")
        layout.addWidget(self.lbl_message)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def _browse_category_save_path(self):
        """Browse for category default save path."""
        initial = self.txt_category_save_path.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self, "Select Category Save Path", initial
        )
        if selected:
            self.txt_category_save_path.setText(selected)

    def _browse_category_incomplete_path(self):
        """Browse for category incomplete save path."""
        initial = self.txt_category_incomplete_path.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self, "Select Category Incomplete Path", initial
        )
        if selected:
            self.txt_category_incomplete_path.setText(selected)

    def _update_incomplete_path_enabled_state(self, *_args):
        """Enable/disable incomplete path controls based on checkbox."""
        enabled = bool(self.chk_category_use_incomplete.isChecked())
        self.txt_category_incomplete_path.setEnabled(enabled)
        self.btn_category_browse_incomplete.setEnabled(enabled)

    def set_busy(self, busy: bool, message: str = ""):
        """Enable/disable editor controls while an API operation runs."""
        enabled = not bool(busy)
        self.tabs.setEnabled(enabled)
        self.btn_category_new.setEnabled(enabled)
        self.btn_category_apply.setEnabled(enabled)
        self.btn_category_delete.setEnabled(enabled and self.lst_categories.currentItem() is not None)
        self.chk_category_use_incomplete.setEnabled(enabled)
        self.txt_category_incomplete_path.setEnabled(enabled and self.chk_category_use_incomplete.isChecked())
        self.btn_category_browse_incomplete.setEnabled(enabled and self.chk_category_use_incomplete.isChecked())
        self.btn_add_tags.setEnabled(enabled)
        self.btn_delete_tags.setEnabled(enabled)
        self.lbl_message.setText(str(message or ""))

    def set_taxonomy_data(self, category_data: Dict[str, Dict[str, Any]], tags: List[str]):
        """Refresh dialog contents from latest category/tag lists."""
        current_category = self.selected_category_name()
        selected_tags = {
            item.text() for item in self.lst_tags_manage.selectedItems()
        }

        self._category_data = dict(category_data or {})
        self.lst_categories.clear()
        for name in sorted(self._category_data.keys()):
            self.lst_categories.addItem(name)

        if current_category:
            matches = self.lst_categories.findItems(current_category, Qt.MatchFlag.MatchExactly)
            if matches:
                self.lst_categories.setCurrentItem(matches[0])
            else:
                self._set_category_create_mode()
        elif self.lst_categories.currentItem() is None:
            self._set_category_create_mode()

        self.lst_tags_manage.clear()
        for tag in sorted(str(t) for t in tags):
            item = QListWidgetItem(tag)
            item.setSelected(tag in selected_tags)
            self.lst_tags_manage.addItem(item)

    def selected_category_name(self) -> str:
        """Return selected category name, or empty string."""
        item = self.lst_categories.currentItem()
        return item.text().strip() if item else ""

    def _on_category_selection_changed(self, current: Optional[QListWidgetItem], _previous):
        """Load selected category into the editor."""
        if current is None:
            self._set_category_create_mode()
            return

        name = current.text().strip()
        details = self._category_data.get(name, {}) if isinstance(self._category_data, dict) else {}
        self.txt_category_name.setReadOnly(True)
        self.txt_category_name.setText(name)
        self.txt_category_save_path.setText(str(details.get("save_path", "") or ""))
        use_incomplete = bool(details.get("use_incomplete_path", False))
        self.chk_category_use_incomplete.setChecked(use_incomplete)
        self.txt_category_incomplete_path.setText(str(details.get("incomplete_path", "") or ""))
        self._update_incomplete_path_enabled_state()
        self.btn_category_apply.setText("Update Category")
        self.btn_category_delete.setEnabled(True)

    def _set_category_create_mode(self):
        """Prepare editor for creating a new category."""
        if self.lst_categories.currentItem() is not None:
            prev = self.lst_categories.blockSignals(True)
            self.lst_categories.clearSelection()
            self.lst_categories.setCurrentItem(None)
            self.lst_categories.blockSignals(prev)
        self.txt_category_name.setReadOnly(False)
        self.txt_category_name.clear()
        self.txt_category_save_path.clear()
        self.chk_category_use_incomplete.setChecked(False)
        self.txt_category_incomplete_path.clear()
        self._update_incomplete_path_enabled_state()
        self.btn_category_apply.setText("Create Category")
        self.btn_category_delete.setEnabled(False)

    def _apply_category_changes(self):
        """Emit create/update category request."""
        name = self.txt_category_name.text().strip()
        save_path = self.txt_category_save_path.text().strip()
        incomplete_path = self.txt_category_incomplete_path.text().strip()
        use_incomplete = bool(self.chk_category_use_incomplete.isChecked())
        if not name:
            self.lbl_message.setText("Category name cannot be empty.")
            return

        if use_incomplete and not incomplete_path:
            self.lbl_message.setText("Incomplete path is enabled but empty.")
            return

        selected_name = self.selected_category_name()
        if selected_name:
            self.edit_category_requested.emit(selected_name, save_path, incomplete_path, use_incomplete)
        else:
            self.create_category_requested.emit(name, save_path, incomplete_path, use_incomplete)

    def _delete_selected_category(self):
        """Emit delete request for selected category."""
        name = self.selected_category_name()
        if not name:
            self.lbl_message.setText("Select a category to delete.")
            return
        self.delete_category_requested.emit(name)

    @staticmethod
    def _parse_csv_entries(raw_text: str) -> List[str]:
        values: List[str] = []
        seen = set()
        for part in str(raw_text or "").split(","):
            value = part.strip()
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        return values

    def _add_tags(self):
        """Emit create-tags request from entry field."""
        tags = self._parse_csv_entries(self.txt_new_tags.text())
        if not tags:
            self.lbl_message.setText("Enter at least one tag.")
            return
        self.create_tags_requested.emit(tags)
        self.txt_new_tags.clear()

    def _delete_selected_tags(self):
        """Emit delete-tags request for selected tags."""
        tags = [item.text().strip() for item in self.lst_tags_manage.selectedItems() if item.text().strip()]
        if not tags:
            self.lbl_message.setText("Select at least one tag to delete.")
            return
        self.delete_tags_requested.emit(tags)


# ============================================================================
# Speed Limits Manager Dialog
# ============================================================================

class SpeedLimitsDialog(QDialog):
    """Dialog to manage global and alternative speed limits."""

    refresh_requested = Signal()
    apply_requested = Signal(int, int, int, int, bool)  # normal_dl_kib, normal_ul_kib, alt_dl_kib, alt_ul_kib, alt_enabled

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Speed Limits")
        self.resize(520, 320)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        normal_group = QGroupBox("Normal Speed Limits (KiB/s)")
        normal_form = QFormLayout(normal_group)
        self.spn_normal_dl = QSpinBox()
        self.spn_normal_ul = QSpinBox()
        for spin in (self.spn_normal_dl, self.spn_normal_ul):
            spin.setRange(0, 10_000_000)
            spin.setSingleStep(10)
        normal_form.addRow("Download:", self.spn_normal_dl)
        normal_form.addRow("Upload:", self.spn_normal_ul)
        layout.addWidget(normal_group)

        alt_group = QGroupBox("Alternative Speed Limits (KiB/s)")
        alt_form = QFormLayout(alt_group)
        self.spn_alt_dl = QSpinBox()
        self.spn_alt_ul = QSpinBox()
        for spin in (self.spn_alt_dl, self.spn_alt_ul):
            spin.setRange(0, 10_000_000)
            spin.setSingleStep(10)
        alt_form.addRow("Download:", self.spn_alt_dl)
        alt_form.addRow("Upload:", self.spn_alt_ul)
        layout.addWidget(alt_group)

        self.chk_alt_enabled = QCheckBox("Alternative speed mode enabled")
        layout.addWidget(self.chk_alt_enabled)

        self.lbl_message = QLabel("")
        layout.addWidget(self.lbl_message)

        buttons_row = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_apply = QPushButton("Apply")
        self.btn_close = QPushButton("Close")
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        self.btn_apply.clicked.connect(self._emit_apply)
        self.btn_close.clicked.connect(self.close)
        buttons_row.addWidget(self.btn_refresh)
        buttons_row.addStretch(1)
        buttons_row.addWidget(self.btn_apply)
        buttons_row.addWidget(self.btn_close)
        layout.addLayout(buttons_row)

    def _emit_apply(self):
        """Emit apply signal with current dialog values."""
        self.apply_requested.emit(
            int(self.spn_normal_dl.value()),
            int(self.spn_normal_ul.value()),
            int(self.spn_alt_dl.value()),
            int(self.spn_alt_ul.value()),
            bool(self.chk_alt_enabled.isChecked()),
        )

    def set_values(self, normal_dl_bytes: int, normal_ul_bytes: int,
                   alt_dl_bytes: int, alt_ul_bytes: int, alt_enabled: bool):
        """Update dialog controls from bytes/sec values."""
        self.spn_normal_dl.setValue(max(0, int(normal_dl_bytes)) // 1024)
        self.spn_normal_ul.setValue(max(0, int(normal_ul_bytes)) // 1024)
        self.spn_alt_dl.setValue(max(0, int(alt_dl_bytes)) // 1024)
        self.spn_alt_ul.setValue(max(0, int(alt_ul_bytes)) // 1024)
        self.chk_alt_enabled.setChecked(bool(alt_enabled))

    def set_busy(self, busy: bool, message: str = ""):
        """Enable/disable controls while async operation runs."""
        enabled = not bool(busy)
        for widget in (
            self.spn_normal_dl,
            self.spn_normal_ul,
            self.spn_alt_dl,
            self.spn_alt_ul,
            self.chk_alt_enabled,
            self.btn_refresh,
            self.btn_apply,
        ):
            widget.setEnabled(enabled)
        self.lbl_message.setText(str(message or ""))


# ============================================================================
# Application Preferences Editor Dialog
# ============================================================================

class AppPreferencesDialog(QDialog):
    """Dialog to edit raw qBittorrent application preferences in a tree view."""

    apply_requested = Signal(dict)

    ROLE_PATH = int(Qt.ItemDataRole.UserRole) + 200
    ROLE_IS_LEAF = int(Qt.ItemDataRole.UserRole) + 201

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit App Preferences")
        self.resize(980, 640)
        self._updating_tree = False
        self._original_preferences: Dict[str, Any] = {}
        self._edited_preferences: Dict[str, Any] = {}
        self._path_items: Dict[Tuple[Any, ...], QTreeWidgetItem] = {}
        self._leaf_original_values: Dict[Tuple[Any, ...], Any] = {}
        self._leaf_current_values: Dict[Tuple[Any, ...], Any] = {}
        self._leaf_items: Dict[Tuple[Any, ...], QTreeWidgetItem] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.tree_preferences = QTreeWidget()
        self.tree_preferences.setAlternatingRowColors(True)
        self.tree_preferences.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.tree_preferences.setColumnCount(3)
        self.tree_preferences.setHeaderLabels(["Preference", "Value", "Type"])
        header = self.tree_preferences.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree_preferences.itemChanged.connect(self._on_tree_item_changed)
        layout.addWidget(self.tree_preferences, 1)

        self.lbl_message = QLabel("No preferences loaded.")
        layout.addWidget(self.lbl_message)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        self.btn_apply = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.btn_apply.clicked.connect(self._emit_apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_busy(self, busy: bool, message: str = ""):
        """Enable/disable dialog controls while API operation runs."""
        enabled = not bool(busy)
        self.tree_preferences.setEnabled(enabled)
        self.btn_apply.setEnabled(enabled)
        self.lbl_message.setText(str(message or ""))

    def set_preferences(self, preferences: Dict[str, Any]):
        """Load preferences into editable tree and reset change tracking."""
        self._updating_tree = True
        try:
            source = dict(preferences or {}) if isinstance(preferences, dict) else {}
            self._original_preferences = copy.deepcopy(source)
            self._edited_preferences = copy.deepcopy(source)
            self._path_items.clear()
            self._leaf_original_values.clear()
            self._leaf_current_values.clear()
            self._leaf_items.clear()
            self.tree_preferences.clear()

            for key in sorted(self._edited_preferences.keys(), key=lambda v: str(v)):
                self._add_pref_item(
                    parent_item=None,
                    path=(key,),
                    label=str(key),
                    value=self._edited_preferences.get(key),
                )
            self.tree_preferences.expandToDepth(0)
            self._refresh_changed_highlights()
            self.lbl_message.setText(f"Loaded {len(self._edited_preferences)} preferences.")
        finally:
            self._updating_tree = False

    @staticmethod
    def _is_container(value: Any) -> bool:
        return isinstance(value, (dict, list))

    @staticmethod
    def _value_type_name(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "str"
        if isinstance(value, list):
            return "list"
        if isinstance(value, dict):
            return "dict"
        return type(value).__name__

    @staticmethod
    def _value_to_text(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            except Exception:
                return str(value)
        return str(value)

    @staticmethod
    def _container_summary(value: Any) -> str:
        if isinstance(value, dict):
            count = len(value)
            suffix = "key" if count == 1 else "keys"
            return f"{{{count} {suffix}}}"
        if isinstance(value, list):
            count = len(value)
            suffix = "item" if count == 1 else "items"
            return f"[{count} {suffix}]"
        return AppPreferencesDialog._value_to_text(value)

    def _add_pref_item(
        self,
        parent_item: Optional[QTreeWidgetItem],
        path: Tuple[Any, ...],
        label: str,
        value: Any,
    ):
        item = QTreeWidgetItem([str(label), "", self._value_type_name(value)])
        item.setData(0, self.ROLE_PATH, path)
        item.setData(0, self.ROLE_IS_LEAF, False)
        if parent_item is None:
            self.tree_preferences.addTopLevelItem(item)
        else:
            parent_item.addChild(item)
        self._path_items[path] = item

        if isinstance(value, dict) and value:
            item.setText(1, self._container_summary(value))
            for child_key in sorted(value.keys(), key=lambda v: str(v)):
                child_path = path + (child_key,)
                self._add_pref_item(item, child_path, str(child_key), value.get(child_key))
            return

        if isinstance(value, list) and value:
            item.setText(1, self._container_summary(value))
            for index, child_value in enumerate(value):
                child_path = path + (index,)
                self._add_pref_item(item, child_path, f"[{index}]", child_value)
            return

        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setData(0, self.ROLE_IS_LEAF, True)
        item.setText(1, self._value_to_text(value))
        self._leaf_original_values[path] = copy.deepcopy(value)
        self._leaf_current_values[path] = copy.deepcopy(value)
        self._leaf_items[path] = item

    @staticmethod
    def _normalize_item_path(path_data: Any) -> Tuple[Any, ...]:
        if isinstance(path_data, tuple):
            return path_data
        if isinstance(path_data, list):
            return tuple(path_data)
        return tuple()

    @staticmethod
    def _path_label(path: Tuple[Any, ...]) -> str:
        if not path:
            return ""
        parts: List[str] = []
        for part in path:
            if isinstance(part, int):
                parts.append(f"[{part}]")
            else:
                if parts:
                    parts.append(".")
                parts.append(str(part))
        return "".join(parts)

    @staticmethod
    def _set_path_value(container: Any, path: Tuple[Any, ...], value: Any):
        target = container
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    @staticmethod
    def _get_path_value(container: Any, path: Tuple[Any, ...]) -> Any:
        target = container
        for key in path:
            target = target[key]
        return target

    @staticmethod
    def _parse_bool(text: str) -> bool:
        token = str(text or "").strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
        raise ValueError("expected boolean (true/false)")

    @staticmethod
    def _parse_value_by_example(text: str, example: Any) -> Any:
        raw = str(text or "")
        stripped = raw.strip()

        if isinstance(example, bool):
            return AppPreferencesDialog._parse_bool(stripped)
        if isinstance(example, int) and not isinstance(example, bool):
            if not stripped:
                raise ValueError("expected integer")
            return int(stripped, 10)
        if isinstance(example, float):
            if not stripped:
                raise ValueError("expected float")
            return float(stripped)
        if isinstance(example, dict):
            if not stripped:
                return {}
            parsed = json.loads(stripped)
            if not isinstance(parsed, dict):
                raise ValueError("expected JSON object")
            return parsed
        if isinstance(example, list):
            if not stripped:
                return []
            parsed = json.loads(stripped)
            if not isinstance(parsed, list):
                raise ValueError("expected JSON array")
            return parsed
        if example is None:
            if stripped.lower() in {"", "null", "none"}:
                return None
            try:
                return json.loads(stripped)
            except Exception:
                return raw
        if isinstance(example, str):
            return raw
        try:
            return json.loads(stripped)
        except Exception:
            return raw

    def _refresh_changed_highlights(self):
        coral_brush = QBrush(QColor("coral"))
        clear_brush = QBrush()
        for path, item in self._leaf_items.items():
            original = self._leaf_original_values.get(path)
            current = self._leaf_current_values.get(path)
            changed = current != original
            item.setBackground(1, coral_brush if changed else clear_brush)

    def changed_preferences(self) -> Dict[str, Any]:
        """Return only top-level preferences changed by the user."""
        changes: Dict[str, Any] = {}
        for key, edited_value in self._edited_preferences.items():
            original_value = self._original_preferences.get(key, None)
            if key not in self._original_preferences or edited_value != original_value:
                changes[str(key)] = copy.deepcopy(edited_value)
        return changes

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._updating_tree:
            return
        if column != 1:
            return

        path = self._normalize_item_path(item.data(0, self.ROLE_PATH))
        if not path:
            return
        if not bool(item.data(0, self.ROLE_IS_LEAF)):
            return

        current_value = self._leaf_current_values.get(path)
        original_value = self._leaf_original_values.get(path)
        try:
            parsed = self._parse_value_by_example(item.text(1), original_value)
        except Exception as e:
            self._updating_tree = True
            try:
                item.setText(1, self._value_to_text(current_value))
            finally:
                self._updating_tree = False
            self.lbl_message.setText(f"{self._path_label(path)}: {e}")
            return

        self._leaf_current_values[path] = copy.deepcopy(parsed)
        self._set_path_value(self._edited_preferences, path, copy.deepcopy(parsed))

        self._updating_tree = True
        try:
            item.setText(2, self._value_type_name(parsed))
            for depth in range(len(path) - 1, 0, -1):
                ancestor_path = path[:depth]
                ancestor_item = self._path_items.get(ancestor_path)
                if ancestor_item is None:
                    continue
                ancestor_value = self._get_path_value(self._edited_preferences, ancestor_path)
                ancestor_item.setText(1, self._container_summary(ancestor_value))
                ancestor_item.setText(2, self._value_type_name(ancestor_value))
        finally:
            self._updating_tree = False

        self._refresh_changed_highlights()
        change_count = len(self.changed_preferences())
        if change_count <= 0:
            self.lbl_message.setText("No changed preferences.")
        else:
            self.lbl_message.setText(f"Changed preferences: {change_count}")

    def _emit_apply(self):
        changes = self.changed_preferences()
        if not changes:
            self.lbl_message.setText("No changed preferences to apply.")
            return
        self.apply_requested.emit(changes)


# ============================================================================
# Tracker Health Dashboard Dialog
# ============================================================================

class TrackerHealthDialog(QDialog):
    """Dialog to display aggregated tracker health metrics."""

    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tracker Health Dashboard")
        self.resize(980, 520)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.lbl_summary = QLabel("No tracker data loaded.")
        layout.addWidget(self.lbl_summary)

        self.tbl_health = QTableWidget()
        self.tbl_health.setAlternatingRowColors(True)
        self.tbl_health.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_health.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_health.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_health.setSortingEnabled(True)
        self.tbl_health.setColumnCount(9)
        self.tbl_health.setHorizontalHeaderLabels([
            "Tracker",
            "Torrents",
            "Rows",
            "Working",
            "Failing",
            "Fail Rate %",
            "Dead",
            "Avg Next Announce (s)",
            "Last Error",
        ])
        header = self.tbl_health.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        layout.addWidget(self.tbl_health, 1)

        controls = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_close = QPushButton("Close")
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        self.btn_close.clicked.connect(self.close)
        controls.addWidget(self.btn_refresh)
        controls.addStretch(1)
        controls.addWidget(self.btn_close)
        layout.addLayout(controls)

    def set_busy(self, busy: bool, message: str = ""):
        """Set dialog busy state."""
        self.btn_refresh.setEnabled(not bool(busy))
        if message:
            self.lbl_summary.setText(message)

    def set_rows(self, rows: List[Dict[str, Any]]):
        """Render aggregated tracker-health rows."""
        self.tbl_health.setSortingEnabled(False)
        self.tbl_health.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            values = [
                str(row.get("tracker", "")),
                str(row.get("torrent_count", 0)),
                str(row.get("row_count", 0)),
                str(row.get("working_count", 0)),
                str(row.get("failing_count", 0)),
                f"{float(row.get('fail_rate', 0.0)):.1f}",
                "Yes" if bool(row.get("dead", False)) else "No",
                str(row.get("avg_next_announce", "")),
                str(row.get("last_error", "")),
            ]
            for col_idx, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col_idx in {1, 2, 3, 4, 5, 7}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tbl_health.setItem(row_idx, col_idx, item)

        self.tbl_health.setSortingEnabled(True)

        total_trackers = len(rows)
        dead_count = sum(1 for row in rows if bool(row.get("dead", False)))
        self.lbl_summary.setText(
            f"Trackers: {total_trackers}   Dead: {dead_count}"
        )


# ============================================================================
# Session Timeline Dialog
# ============================================================================

class TimelineGraphWidget(QWidget):
    """Simple custom graph for session timeline samples."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._samples: List[Dict[str, Any]] = []
        self.setMinimumHeight(260)

    def set_samples(self, samples: List[Dict[str, Any]]):
        """Set timeline samples and trigger repaint."""
        self._samples = list(samples or [])
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(16, 18, 22))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        samples = self._samples[-240:]
        if len(samples) < 2:
            painter.setPen(QColor(180, 180, 180))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Timeline waiting for samples...")
            return

        left, top, right, bottom = 48, 24, 14, 32
        chart_w = max(10, self.width() - left - right)
        chart_h = max(10, self.height() - top - bottom)

        # Alt-speed mode background bands.
        painter.setPen(Qt.PenStyle.NoPen)
        band_color = QColor(255, 196, 0, 40)
        for i in range(len(samples) - 1):
            if not bool(samples[i].get("alt_enabled", False)):
                continue
            x1 = left + int(i * chart_w / max(1, len(samples) - 1))
            x2 = left + int((i + 1) * chart_w / max(1, len(samples) - 1))
            painter.fillRect(x1, top, max(1, x2 - x1), chart_h, band_color)

        # Grid
        painter.setPen(QPen(QColor(80, 86, 96), 1))
        for idx in range(5):
            y = top + int(idx * chart_h / 4)
            painter.drawLine(left, y, left + chart_w, y)

        max_speed = max(
            1,
            max(int(s.get("down_bps", 0)) for s in samples),
            max(int(s.get("up_bps", 0)) for s in samples),
        )
        max_active = max(1, max(int(s.get("active_count", 0)) for s in samples))

        def x_for(i: int) -> int:
            return left + int(i * chart_w / max(1, len(samples) - 1))

        def y_for_speed(value: int) -> int:
            return top + chart_h - int(max(0, int(value)) * chart_h / max_speed)

        def y_for_active(value: int) -> int:
            return top + chart_h - int(max(0, int(value)) * chart_h / max_active)

        # Down line
        down_pen = QPen(QColor(80, 160, 255), 2)
        painter.setPen(down_pen)
        for i in range(len(samples) - 1):
            painter.drawLine(
                x_for(i), y_for_speed(samples[i].get("down_bps", 0)),
                x_for(i + 1), y_for_speed(samples[i + 1].get("down_bps", 0)),
            )

        # Up line
        up_pen = QPen(QColor(255, 140, 80), 2)
        painter.setPen(up_pen)
        for i in range(len(samples) - 1):
            painter.drawLine(
                x_for(i), y_for_speed(samples[i].get("up_bps", 0)),
                x_for(i + 1), y_for_speed(samples[i + 1].get("up_bps", 0)),
            )

        # Active torrents line
        active_pen = QPen(QColor(120, 220, 120), 1)
        active_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(active_pen)
        for i in range(len(samples) - 1):
            painter.drawLine(
                x_for(i), y_for_active(samples[i].get("active_count", 0)),
                x_for(i + 1), y_for_active(samples[i + 1].get("active_count", 0)),
            )

        painter.setPen(QColor(220, 220, 220))
        painter.drawText(8, top + 10, f"{max_speed:,} B/s")
        painter.drawText(8, top + chart_h, "0")

        legend_y = 16
        painter.setPen(QColor(80, 160, 255))
        painter.drawText(left, legend_y, "DL")
        painter.setPen(QColor(255, 140, 80))
        painter.drawText(left + 40, legend_y, "UL")
        painter.setPen(QColor(120, 220, 120))
        painter.drawText(left + 80, legend_y, "Active Torrents")
        painter.setPen(QColor(255, 196, 0))
        painter.drawText(left + 210, legend_y, "Alt Mode")


class SessionTimelineDialog(QDialog):
    """Dialog to display timeline of speeds/active torrents/alt mode."""

    refresh_requested = Signal()
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Session Timeline")
        self.resize(980, 420)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.graph = TimelineGraphWidget()
        layout.addWidget(self.graph, 1)

        self.lbl_summary = QLabel("No timeline samples yet.")
        layout.addWidget(self.lbl_summary)

        controls = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_clear = QPushButton("Clear History")
        self.btn_close = QPushButton("Close")
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        self.btn_clear.clicked.connect(self.clear_requested.emit)
        self.btn_close.clicked.connect(self.close)
        controls.addWidget(self.btn_refresh)
        controls.addWidget(self.btn_clear)
        controls.addStretch(1)
        controls.addWidget(self.btn_close)
        layout.addLayout(controls)

    def set_samples(self, samples: List[Dict[str, Any]]):
        """Update timeline graph and summary."""
        self.graph.set_samples(samples)
        if not samples:
            self.lbl_summary.setText("No timeline samples yet.")
            return
        last = samples[-1]
        summary = (
            f"Samples: {len(samples)}   "
            f"DL: {format_speed_mode(int(last.get('down_bps', 0)), mode='human_readable')}   "
            f"UL: {format_speed_mode(int(last.get('up_bps', 0)), mode='human_readable')}   "
            f"Active: {int(last.get('active_count', 0))}   "
            f"Alt Mode: {'On' if bool(last.get('alt_enabled', False)) else 'Off'}"
        )
        self.lbl_summary.setText(summary)

    def set_busy(self, busy: bool, message: str = ""):
        """Set dialog busy state."""
        enabled = not bool(busy)
        self.btn_refresh.setEnabled(enabled)
        self.btn_clear.setEnabled(enabled)
        if message:
            self.lbl_summary.setText(message)


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


def format_eta(seconds: int) -> str:
    """Format ETA seconds to compact human-readable duration."""
    try:
        eta = int(seconds)
    except Exception:
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


def _normalize_instance_host(raw_host: Any) -> str:
    """Normalize host input used for per-instance file ID generation."""
    if raw_host is None:
        return "localhost"
    host = str(raw_host).strip()
    return host if host else "localhost"


def _normalize_instance_port(raw_port: Any) -> int:
    """Normalize port input used for per-instance file ID generation."""
    try:
        port = int(raw_port)
    except Exception:
        port = 8080
    if port < 1 or port > 65535:
        return 8080
    return port


def _normalize_instance_counter(raw_counter: Any) -> int:
    """Normalize per-server instance counter used as instance ID suffix."""
    try:
        counter = int(raw_counter)
    except Exception:
        counter = 1
    return counter if counter > 0 else 1


def _normalize_http_protocol_scheme(raw_scheme: Any) -> str:
    """Normalize WebUI/API protocol scheme to http or https."""
    scheme = str(raw_scheme or "").strip().lower()
    if scheme in ("http", "https"):
        return scheme
    return "http"


def compute_instance_id(
    qb_host: Any,
    qb_port: Any,
    length: int = INSTANCE_ID_LENGTH,
    instance_counter: Any = 1,
) -> str:
    """Compute a short deterministic ID from qb_host + qb_port."""
    host = _normalize_instance_host(qb_host)
    port = _normalize_instance_port(qb_port)
    digest = hashlib.sha1(f"{host}:{port}".encode("utf-8")).hexdigest()
    try:
        max_len = max(1, int(length))
    except Exception:
        max_len = INSTANCE_ID_LENGTH
    base_id = digest[:max_len]
    counter = _normalize_instance_counter(instance_counter)
    return f"{base_id}_{counter}"


def compute_instance_id_from_config(config: Dict[str, Any]) -> str:
    """Compute instance ID from a config dict using normalized host/port values."""
    cfg = config if isinstance(config, dict) else {}
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
    """Resolve cache file path under OS temp dir unless absolute override is used."""
    raw_path = Path(str(cache_file_name))
    if instance_id:
        raw_path = Path(_append_instance_id_to_filename(str(raw_path), instance_id))
    if raw_path.is_absolute():
        return raw_path
    return Path(tempfile.gettempdir()) / CACHE_TEMP_SUBDIR / raw_path


def resolve_instance_lock_file_path(instance_id: str, instance_counter: Any) -> Path:
    """Resolve one .lck file path for a computed instance id + counter."""
    ident = str(instance_id or "").strip().lower()
    counter = _normalize_instance_counter(instance_counter)
    suffix = f"_{counter}"
    lock_key = ident if ident.endswith(suffix) else f"{ident}{suffix}"
    return resolve_cache_file_path("qbiremo_enhanced.lck", lock_key)


def acquire_instance_lock(
    config: Dict[str, Any],
    start_counter: Any,
) -> Tuple[int, str, Path]:
    """Create an exclusive .lck file; auto-increment counter when lock exists."""
    cfg = config if isinstance(config, dict) else {}
    counter = _normalize_instance_counter(start_counter)

    while True:
        cfg["_instance_counter"] = int(counter)
        instance_id = compute_instance_id_from_config(cfg)
        lock_path = resolve_instance_lock_file_path(instance_id, counter)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with lock_path.open("x", encoding="utf-8") as handle:
                handle.write(f"instance_id={instance_id}\n")
                handle.write(f"instance_counter={counter}\n")
            return int(counter), str(instance_id), lock_path
        except FileExistsError:
            counter += 1


def release_instance_lock(lock_path: Path):
    """Best-effort removal of an instance .lck file on shutdown."""
    try:
        Path(lock_path).unlink()
    except FileNotFoundError:
        pass
    except Exception:
        logger.debug("Failed to remove lock file: %s", lock_path, exc_info=True)


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

        self.config = config if isinstance(config, dict) else {}
        config = self.config
        self.instance_id = str(config.get("_instance_id", "") or "").strip().lower()
        if not self.instance_id:
            self.instance_id = compute_instance_id_from_config(config)
        self.base_window_title = "qBiremo Enhanced"
        self.setWindowTitle(self.base_window_title)

        # Connection info from config (TOML), falling back to env vars
        self.qb_conn_info = self._build_connection_info(config)

        # State
        self.all_torrents = []
        self.filtered_torrents = []
        self.categories = []
        self.category_details: Dict[str, Dict[str, Any]] = {}
        self.tags = []
        self.trackers = []
        self.size_buckets = []
        self.torrent_columns = list(TORRENT_COLUMNS)
        self.torrent_column_index = {
            col["key"]: idx for idx, col in enumerate(self.torrent_columns)
        }
        self.column_visibility_actions: Dict[str, QAction] = {}
        self.saved_torrent_views_menu: Optional[QMenu] = None
        self._torrent_open_shortcuts: List[QShortcut] = []
        self._content_open_shortcuts: List[QShortcut] = []
        self.clipboard_monitor_enabled = False
        self.debug_logging_enabled = False
        self._last_clipboard_text = ""
        self._clipboard_seen_keys = set()
        self._clipboard_seen_order = deque()
        self._clipboard = None

        # Defaults are managed by code/QSettings (not TOML).
        self.default_status_filter = DEFAULT_STATUS_FILTER
        self.default_auto_refresh_enabled = DEFAULT_AUTO_REFRESH
        self.default_refresh_interval = DEFAULT_REFRESH_INTERVAL

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
        self._torrent_edit_original: Dict[str, Any] = {}
        self.tab_torrent_edit: Optional[QWidget] = None
        self._suppress_next_cache_save = False
        self._sync_rid = 0
        self._sync_torrent_map: Dict[str, Dict[str, Any]] = {}
        self._latest_torrent_fetch_remote_filtered = False
        self._taxonomy_dialog: Optional[TaxonomyManagerDialog] = None
        self._speed_limits_dialog: Optional[SpeedLimitsDialog] = None
        self._app_preferences_dialog: Optional[AppPreferencesDialog] = None
        self._tracker_health_dialog: Optional[TrackerHealthDialog] = None
        self._session_timeline_dialog: Optional[SessionTimelineDialog] = None
        self._add_torrent_dialog: Optional[AddTorrentDialog] = None
        self.session_timeline_history = deque(maxlen=720)
        self._last_alt_speed_mode = False
        self._last_dht_nodes = 0
        self._last_global_download_limit = 0
        self._last_global_upload_limit = 0

        # Persistent per-torrent content cache (JSON file)
        self.cache_file_path = resolve_cache_file_path(CACHE_FILE_NAME, self.instance_id)
        self.content_cache: Dict[str, Dict[str, Any]] = {}
        self._remove_expired_cache_file()
        self._load_content_cache()

        # API task queue
        self.api_queue = APITaskQueue(self)
        self.api_queue.task_completed.connect(self._on_task_completed)
        self.api_queue.task_failed.connect(self._on_task_failed)
        self.api_queue.task_cancelled.connect(self._on_task_cancelled)

        # Separate queue for selected-torrent details (trackers/peers), so
        # table refresh/actions are not interrupted by tab-level lookups.
        self.details_api_queue = APITaskQueue(self)
        self.analytics_api_queue = APITaskQueue(self)

        # Log file path (set by main() before constructing MainWindow)
        self.log_file_path = config.get(
            '_log_file_path',
            _append_instance_id_to_filename('qbiremo_enhanced.log', self.instance_id),
        )

        # Auto-refresh settings
        self.auto_refresh_enabled = self.default_auto_refresh_enabled
        self.refresh_interval = self.default_refresh_interval
        self._refresh_torrents_in_progress = False
        self.display_size_mode = DEFAULT_DISPLAY_SIZE_MODE
        self.display_speed_mode = DEFAULT_DISPLAY_SPEED_MODE
        self.title_bar_speed_format = str(
            config.get("title_bar_speed_format", DEFAULT_TITLE_BAR_SPEED_FORMAT)
            or DEFAULT_TITLE_BAR_SPEED_FORMAT
        )

        # UI Setup
        self._create_ui()
        self._create_menus()
        self._create_statusbar()
        self._setup_clipboard_monitor()
        self._capture_default_view_state()

        # Timers
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_torrents)
        self._sync_auto_refresh_timer_state()

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
        QTimer.singleShot(500, self._bring_to_front_startup)

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

        # -- General tab --
        general_widget = QWidget()
        general_layout = QVBoxLayout(general_widget)
        general_layout.setContentsMargins(4, 4, 4, 4)

        general_actions_layout = QHBoxLayout()
        general_actions_layout.addStretch(1)
        btn_copy_general = QPushButton("Copy")
        btn_copy_general.clicked.connect(self._copy_general_details)
        general_actions_layout.addWidget(btn_copy_general)
        general_layout.addLayout(general_actions_layout)

        self.txt_general_details = QTextEdit()
        self.txt_general_details.setReadOnly(True)
        self.txt_general_details.setAcceptRichText(True)
        self.txt_general_details.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.txt_general_details.setPlaceholderText("Select one torrent to see its details.")
        self.txt_general_details.document().setDefaultStyleSheet(
            "body { margin: 0; font-size: 12px; }"
            "h3 { margin: 10px 0 4px; font-size: 12px; font-weight: 700; }"
            "table { width: 100%; border-collapse: collapse; margin-bottom: 8px; }"
            "td { padding: 2px 4px; vertical-align: top; }"
            "td.key { color: #666; width: 190px; font-weight: 600; }"
            "td.value { color: #111; }"
        )
        general_layout.addWidget(self.txt_general_details)
        self.detail_tabs.addTab(general_widget, "General")

        # -- Trackers tab --
        trackers_widget = QWidget()
        trackers_layout = QVBoxLayout(trackers_widget)
        trackers_layout.setContentsMargins(4, 4, 4, 4)
        self.tbl_trackers = QTableWidget()
        self.tbl_trackers.setAlternatingRowColors(True)
        self.tbl_trackers.setSortingEnabled(True)
        self.tbl_trackers.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_trackers.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_trackers.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_trackers.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tbl_trackers.horizontalHeader().setStretchLastSection(True)
        trackers_layout.addWidget(self.tbl_trackers)
        self.detail_tabs.addTab(trackers_widget, "Trackers")

        # -- Peers tab --
        peers_widget = QWidget()
        peers_layout = QVBoxLayout(peers_widget)
        peers_layout.setContentsMargins(4, 4, 4, 4)
        self.tbl_peers = QTableWidget()
        self.tbl_peers.setAlternatingRowColors(True)
        self.tbl_peers.setSortingEnabled(True)
        self.tbl_peers.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_peers.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_peers.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_peers.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl_peers.customContextMenuRequested.connect(self._show_peers_context_menu)
        self.tbl_peers.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tbl_peers.horizontalHeader().setStretchLastSection(True)
        peers_layout.addWidget(self.tbl_peers)
        self.detail_tabs.addTab(peers_widget, "Peers")

        self._set_details_table_message(self.tbl_trackers, "No torrent selected.")
        self._set_details_table_message(self.tbl_peers, "No torrent selected.")

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
        self.tree_files.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree_files.installEventFilter(self)
        self.tree_files.itemActivated.connect(self._on_content_tree_item_activated)
        self._content_open_shortcuts = []
        for key_name in ("Return", "Enter"):
            shortcut = QShortcut(QKeySequence(key_name), self.tree_files)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._open_selected_content_path)
            self._content_open_shortcuts.append(shortcut)
        file_header = self.tree_files.header()
        file_header.setStretchLastSection(False)
        file_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        content_layout.addWidget(self.tree_files)
        self.detail_tabs.addTab(content_widget, "Content")

        # -- Edit tab --
        edit_widget = QWidget()
        edit_layout = QVBoxLayout(edit_widget)
        edit_layout.setContentsMargins(8, 8, 8, 8)

        self.lbl_torrent_edit_state = QLabel("Select one torrent to edit.")
        self.lbl_torrent_edit_state.setWordWrap(True)
        edit_layout.addWidget(self.lbl_torrent_edit_state)

        edit_form = QFormLayout()

        self.txt_torrent_edit_name = QLineEdit()
        self.txt_torrent_edit_name.setPlaceholderText("Torrent name")
        edit_form.addRow("Name:", self.txt_torrent_edit_name)

        self.chk_torrent_edit_auto_tmm = QCheckBox("Automatic Torrent Management")
        self.chk_torrent_edit_auto_tmm.setTristate(True)
        self.chk_torrent_edit_auto_tmm.setToolTip(
            "Checked: enable, Unchecked: disable, Partially checked: leave unchanged."
        )
        edit_form.addRow("Auto Management:", self.chk_torrent_edit_auto_tmm)

        self.cmb_torrent_edit_category = QComboBox()
        self.cmb_torrent_edit_category.setEditable(True)
        edit_form.addRow("Category:", self.cmb_torrent_edit_category)

        self.txt_torrent_edit_tags = QLineEdit()
        self.txt_torrent_edit_tags.setPlaceholderText("Comma-separated tags")
        tags_row = QHBoxLayout()
        tags_row.addWidget(self.txt_torrent_edit_tags)
        btn_add_tags = QPushButton("+")
        btn_add_tags.setToolTip("Add tags from known tag list")
        btn_add_tags.clicked.connect(self._add_tags_to_torrent_edit)
        tags_row.addWidget(btn_add_tags)
        edit_form.addRow("Tags:", tags_row)
        self.btn_torrent_edit_add_tags = btn_add_tags

        self.spn_torrent_edit_download_limit = QSpinBox()
        self.spn_torrent_edit_download_limit.setRange(0, 10_000_000)
        self.spn_torrent_edit_download_limit.setSpecialValueText("Unlimited")
        self.spn_torrent_edit_download_limit.setSuffix(" KiB/s")
        self.spn_torrent_edit_download_limit.setToolTip("Per-torrent download limit (0 = unlimited)")
        edit_form.addRow("Download Speed Limit:", self.spn_torrent_edit_download_limit)

        self.spn_torrent_edit_upload_limit = QSpinBox()
        self.spn_torrent_edit_upload_limit.setRange(0, 10_000_000)
        self.spn_torrent_edit_upload_limit.setSpecialValueText("Unlimited")
        self.spn_torrent_edit_upload_limit.setSuffix(" KiB/s")
        self.spn_torrent_edit_upload_limit.setToolTip("Per-torrent upload limit (0 = unlimited)")
        edit_form.addRow("Upload Speed Limit:", self.spn_torrent_edit_upload_limit)

        self.txt_torrent_edit_save_path = QLineEdit()
        save_path_row = QHBoxLayout()
        save_path_row.addWidget(self.txt_torrent_edit_save_path)
        btn_browse_save_path = QPushButton("Browse")
        btn_browse_save_path.clicked.connect(self._browse_torrent_edit_save_path)
        save_path_row.addWidget(btn_browse_save_path)
        edit_form.addRow("Save Path:", save_path_row)
        self.btn_torrent_edit_browse_save_path = btn_browse_save_path
        self.txt_torrent_edit_save_path.textChanged.connect(self._update_torrent_edit_path_browse_buttons)

        self.txt_torrent_edit_incomplete_path = QLineEdit()
        incomplete_path_row = QHBoxLayout()
        incomplete_path_row.addWidget(self.txt_torrent_edit_incomplete_path)
        btn_browse_incomplete_path = QPushButton("Browse")
        btn_browse_incomplete_path.clicked.connect(self._browse_torrent_edit_incomplete_path)
        incomplete_path_row.addWidget(btn_browse_incomplete_path)
        edit_form.addRow("Incomplete Path:", incomplete_path_row)
        self.btn_torrent_edit_browse_incomplete_path = btn_browse_incomplete_path
        self.txt_torrent_edit_incomplete_path.textChanged.connect(self._update_torrent_edit_path_browse_buttons)

        edit_layout.addLayout(edit_form)

        apply_row = QHBoxLayout()
        apply_row.addStretch(1)
        self.btn_torrent_edit_apply = QPushButton("Apply")
        self.btn_torrent_edit_apply.clicked.connect(self._apply_selected_torrent_edits)
        apply_row.addWidget(self.btn_torrent_edit_apply)
        edit_layout.addLayout(apply_row)
        self.detail_tabs.addTab(edit_widget, "Edit")
        self.tab_torrent_edit = edit_widget
        self.detail_tabs.currentChanged.connect(self._on_detail_tab_changed)

        self._set_torrent_edit_enabled(False, "Select one torrent to edit.")

        self.right_splitter.addWidget(self.detail_tabs)

        self.main_splitter.addWidget(self.right_splitter)

        # Set initial sizes
        self.main_splitter.setSizes([DEFAULT_LEFT_PANEL_WIDTH, 1000])
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
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.itemSelectionChanged.connect(self._on_torrent_selected)
        table.itemDoubleClicked.connect(self._on_torrent_table_item_double_clicked)

        headers = [col["label"] for col in self.torrent_columns]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)

        # Make columns user-resizable and movable.
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        header.setMinimumSectionSize(40)

        # Default widths and visibility (used on first run before QSettings restore)
        for idx, column in enumerate(self.torrent_columns):
            table.setColumnWidth(idx, int(column.get("width", 100)))
            table.setColumnHidden(idx, not bool(column.get("default_visible", True)))

        # Open selected torrent local directory on Enter/Return.
        self._torrent_open_shortcuts = []
        for key_name in ("Return", "Enter"):
            shortcut = QShortcut(QKeySequence(key_name), table)
            shortcut.activated.connect(self._open_selected_torrent_location)
            self._torrent_open_shortcuts.append(shortcut)

        return table

    def _create_torrent_columns_menu(self, parent_menu: QMenu):
        """Create View -> Torrent Columns submenu with per-column visibility toggles."""
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

    def _set_torrent_column_visible(self, column_key: str, visible: bool):
        """Show or hide one torrent-table column by stable column key."""
        idx = self.torrent_column_index.get(column_key)
        if idx is None:
            return
        self.tbl_torrents.setColumnHidden(idx, not bool(visible))
        self._sync_torrent_column_actions()
        self._save_settings()

    def _show_all_torrent_columns(self):
        """Make every torrent-table column visible."""
        for idx in range(self.tbl_torrents.columnCount()):
            self.tbl_torrents.setColumnHidden(idx, False)
        self._sync_torrent_column_actions()
        self._save_settings()

    def _sync_torrent_column_actions(self):
        """Refresh column visibility action checked states from current table state."""
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

    def _apply_hidden_columns_by_keys(self, hidden_keys: List[str]):
        """Apply hidden column state from stable key list."""
        hidden = {str(k) for k in hidden_keys}
        for idx, col in enumerate(self.torrent_columns):
            self.tbl_torrents.setColumnHidden(idx, col["key"] in hidden)
        self._sync_torrent_column_actions()

    def _apply_torrent_view(
        self,
        visible_keys: List[str],
        widths: Optional[Dict[str, Any]] = None,
    ):
        """Apply a torrent-table view by visible column keys and optional widths."""
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
        """Return visible columns + widths for the current torrent-table view."""
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
        """Load named torrent-table views from QSettings."""
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

    def _store_saved_torrent_views(self, views: Dict[str, Dict[str, Any]]):
        """Store named torrent-table views into QSettings."""
        settings = self._new_settings()
        payload = views if isinstance(views, dict) else {}
        settings.setValue(
            "torrentColumnNamedViewsJson",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        )
        settings.sync()

    def _refresh_saved_torrent_views_menu(self):
        """Rebuild the Saved Views submenu from QSettings."""
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

    def _apply_saved_torrent_view(self, view_name: str):
        """Apply one named saved torrent-table view."""
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

    def _save_current_torrent_view(self):
        """Prompt for a name and save current column visibility/widths as a named view."""
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

    def _apply_basic_torrent_view(self):
        """Apply built-in Basic torrent-table view preset."""
        self._apply_torrent_view(list(BASIC_TORRENT_VIEW_KEYS))
        self._set_status("Applied view: Basic")

    def _apply_medium_torrent_view(self):
        """Apply built-in Medium torrent-table view preset."""
        self._apply_torrent_view(list(MEDIUM_TORRENT_VIEW_KEYS))
        self._set_status("Applied view: Medium")

    def _fit_torrent_columns(self):
        """Resize visible torrent table columns to fit their contents."""
        self.tbl_torrents.resizeColumnsToContents()

    def _create_menus(self):
        """Create menu bar"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        add_action = QAction("&Add Torrent...", self)
        add_action.setShortcut("Ctrl+O")
        add_action.triggered.connect(self._show_add_torrent_dialog)
        file_menu.addAction(add_action)

        export_action = QAction("&Export Torrent...", self)
        export_action.triggered.connect(self._export_selected_torrents)
        file_menu.addAction(export_action)

        action_new_instance = QAction("New &instance", self)
        action_new_instance.setShortcut("Ctrl+Shift+N")
        action_new_instance.triggered.connect(self._launch_new_instance_current_config)
        file_menu.addAction(action_new_instance)

        action_new_instance_from_config = QAction("New instance from con&fig...", self)
        action_new_instance_from_config.triggered.connect(self._launch_new_instance_from_config)
        file_menu.addAction(action_new_instance_from_config)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcuts([QKeySequence("Ctrl+Q"), QKeySequence("Alt+X")])
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")

        action_start = QAction("&Start", self)
        action_start.setShortcut("Ctrl+S")
        action_start.triggered.connect(self._resume_torrent)
        edit_menu.addAction(action_start)

        action_stop = QAction("Sto&p", self)
        action_stop.setShortcut("Ctrl+P")
        action_stop.triggered.connect(self._pause_torrent)
        edit_menu.addAction(action_stop)

        action_force_start = QAction("&Force Start", self)
        action_force_start.setShortcut("Ctrl+M")
        action_force_start.triggered.connect(self._force_start_torrent)
        edit_menu.addAction(action_force_start)

        action_recheck = QAction("Re&check", self)
        action_recheck.setShortcut("Ctrl+R")
        action_recheck.triggered.connect(self._recheck_torrent)
        edit_menu.addAction(action_recheck)

        action_increase_priority = QAction("&Increase Priority in Queue", self)
        action_increase_priority.setShortcut("Ctrl++")
        action_increase_priority.triggered.connect(self._increase_torrent_priority)
        edit_menu.addAction(action_increase_priority)

        action_decrease_priority = QAction("&Decrease Priority in Queue", self)
        action_decrease_priority.setShortcut("Ctrl+-")
        action_decrease_priority.triggered.connect(self._decrease_torrent_priority)
        edit_menu.addAction(action_decrease_priority)

        action_top_priority = QAction("&Top Priority in Queue", self)
        action_top_priority.setShortcut("Ctrl+Shift++")
        action_top_priority.triggered.connect(self._top_torrent_priority)
        edit_menu.addAction(action_top_priority)

        action_bottom_priority = QAction("Mi&nimum Priority in Queue", self)
        action_bottom_priority.setShortcut("Ctrl+Shift+-")
        action_bottom_priority.triggered.connect(self._minimum_torrent_priority)
        edit_menu.addAction(action_bottom_priority)

        edit_menu.addSeparator()

        action_remove = QAction("Remo&ve", self)
        action_remove.setShortcut("Del")
        action_remove.triggered.connect(self._remove_torrent)
        edit_menu.addAction(action_remove)

        action_remove_delete = QAction("Remove and De&lete Data", self)
        action_remove_delete.setShortcut("Shift+Del")
        action_remove_delete.triggered.connect(self._remove_torrent_and_delete_data)
        edit_menu.addAction(action_remove_delete)

        action_remove_no_confirm = QAction("Remove (no confirmation)", self)
        action_remove_no_confirm.setShortcut("Ctrl+Del")
        action_remove_no_confirm.triggered.connect(self._remove_torrent_no_confirmation)
        edit_menu.addAction(action_remove_no_confirm)

        action_remove_delete_no_confirm = QAction(
            "Remove and Delete Data (no confirmation)", self
        )
        action_remove_delete_no_confirm.setShortcut("Ctrl+Shift+Del")
        action_remove_delete_no_confirm.triggered.connect(
            self._remove_torrent_and_delete_data_no_confirmation
        )
        edit_menu.addAction(action_remove_delete_no_confirm)

        edit_menu.addSeparator()

        action_pause_session = QAction("Pause Sessio&n", self)
        action_pause_session.setShortcut("Ctrl+Shift+P")
        action_pause_session.triggered.connect(self._pause_session)
        edit_menu.addAction(action_pause_session)

        action_resume_session = QAction("Resu&me Session", self)
        action_resume_session.setShortcut("Ctrl+Shift+S")
        action_resume_session.triggered.connect(self._resume_session)
        edit_menu.addAction(action_resume_session)

        edit_menu.addSeparator()
        content_menu = edit_menu.addMenu("Con&tent")

        action_content_skip = QAction("&Skip", self)
        action_content_skip.triggered.connect(lambda: self._set_selected_content_priority(0))
        content_menu.addAction(action_content_skip)

        action_content_normal = QAction("&Normal Priority", self)
        action_content_normal.triggered.connect(lambda: self._set_selected_content_priority(1))
        content_menu.addAction(action_content_normal)

        action_content_high = QAction("&High Priority", self)
        action_content_high.triggered.connect(lambda: self._set_selected_content_priority(6))
        content_menu.addAction(action_content_high)

        action_content_max = QAction("&Maximum Priority", self)
        action_content_max.triggered.connect(lambda: self._set_selected_content_priority(7))
        content_menu.addAction(action_content_max)

        content_menu.addSeparator()
        action_content_rename = QAction("&Rename...", self)
        action_content_rename.triggered.connect(self._rename_selected_content_item)
        content_menu.addAction(action_content_rename)

        # View menu
        view_menu = menubar.addMenu("&View")

        action_open_log = QAction("Open &Log File", self)
        action_open_log.triggered.connect(self._open_log_file)
        view_menu.addAction(action_open_log)

        action_refresh = QAction("&Refresh", self)
        action_refresh.setShortcut("F5")
        action_refresh.triggered.connect(self._refresh_torrents)
        view_menu.addAction(action_refresh)

        clear_cache_action = QAction("Clear Cache && &Refresh", self)
        clear_cache_action.setShortcut("Ctrl+F5")
        clear_cache_action.triggered.connect(self._clear_cache_and_refresh)
        view_menu.addAction(clear_cache_action)

        action_show_active = QAction("Show &Active Torrents", self)
        action_show_active.setShortcut("F6")
        action_show_active.triggered.connect(self._show_active_torrents_only)
        view_menu.addAction(action_show_active)

        action_show_complete = QAction("Show &Complete Torrents", self)
        action_show_complete.setShortcut("F7")
        action_show_complete.triggered.connect(self._show_completed_torrents_only)
        view_menu.addAction(action_show_complete)

        action_show_all = QAction("Show &All Torrents", self)
        action_show_all.setShortcut("F8")
        action_show_all.triggered.connect(self._show_all_torrents_only)
        view_menu.addAction(action_show_all)

        self.action_human_readable = QAction("&Human Readable", self)
        self.action_human_readable.setCheckable(True)
        self.action_human_readable.setChecked(True)
        self.action_human_readable.triggered.connect(self._toggle_human_readable)
        view_menu.addAction(self.action_human_readable)

        view_menu.addSeparator()
        self._create_torrent_columns_menu(view_menu)

        action_fit_columns = QAction("Fit &Columns", self)
        action_fit_columns.triggered.connect(self._fit_torrent_columns)
        view_menu.addAction(action_fit_columns)

        view_menu.addSeparator()

        self.action_auto_refresh = QAction("Enable &Auto-Refresh", self)
        self.action_auto_refresh.setCheckable(True)
        self.action_auto_refresh.setChecked(self.auto_refresh_enabled)
        self.action_auto_refresh.triggered.connect(self._toggle_auto_refresh)
        self._update_auto_refresh_action_text()
        view_menu.addAction(self.action_auto_refresh)

        action_set_refresh_interval = QAction("Set Auto-Refresh &Interval...", self)
        action_set_refresh_interval.triggered.connect(self._set_auto_refresh_interval)
        view_menu.addAction(action_set_refresh_interval)

        view_menu.addSeparator()
        action_reset_view = QAction("&Reset View", self)
        action_reset_view.triggered.connect(self._reset_view_defaults)
        view_menu.addAction(action_reset_view)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")

        self.action_clipboard_monitor = QAction("Enable &Clipboard Monitor", self)
        self.action_clipboard_monitor.setCheckable(True)
        self.action_clipboard_monitor.setChecked(self.clipboard_monitor_enabled)
        self.action_clipboard_monitor.triggered.connect(self._toggle_clipboard_monitor)
        tools_menu.addAction(self.action_clipboard_monitor)

        self.action_debug_logging = QAction("Enable &Debug logging", self)
        self.action_debug_logging.setCheckable(True)
        self.action_debug_logging.setChecked(self.debug_logging_enabled)
        self.action_debug_logging.triggered.connect(self._toggle_debug_logging)
        tools_menu.addAction(self.action_debug_logging)

        action_edit_ini = QAction("&Edit .ini file", self)
        action_edit_ini.triggered.connect(self._edit_settings_ini_file)
        tools_menu.addAction(action_edit_ini)

        action_edit_app_preferences = QAction("Edit App Preferences", self)
        action_edit_app_preferences.triggered.connect(self._show_app_preferences_editor)
        tools_menu.addAction(action_edit_app_preferences)

        action_open_web_ui = QAction("Open Web UI in browser", self)
        action_open_web_ui.triggered.connect(self._open_web_ui_in_browser)
        tools_menu.addAction(action_open_web_ui)

        tools_menu.addSeparator()

        action_manage_speed_limits = QAction("Manage &Speed Limits...", self)
        action_manage_speed_limits.triggered.connect(self._show_speed_limits_manager)
        tools_menu.addAction(action_manage_speed_limits)

        action_manage_taxonomy = QAction("Manage Tags and Categories", self)
        action_manage_taxonomy.triggered.connect(self._show_taxonomy_manager)
        tools_menu.addAction(action_manage_taxonomy)

        tools_menu.addSeparator()

        action_tracker_health = QAction("Tracker &Health Dashboard...", self)
        action_tracker_health.triggered.connect(self._show_tracker_health_dashboard)
        tools_menu.addAction(action_tracker_health)

        action_session_timeline = QAction("Session &Timeline...", self)
        action_session_timeline.triggered.connect(self._show_session_timeline)
        tools_menu.addAction(action_session_timeline)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_statusbar(self):
        """Create status bar"""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)

        # Status label
        self.lbl_status = QLabel("Ready")
        self.statusbar.addWidget(self.lbl_status, 1)

        self.lbl_dht_nodes = QLabel("")
        self.statusbar.addPermanentWidget(self.lbl_dht_nodes)

        self.lbl_download_summary = QLabel("")
        self.statusbar.addPermanentWidget(self.lbl_download_summary)

        self.lbl_upload_summary = QLabel("")
        self.statusbar.addPermanentWidget(self.lbl_upload_summary)

        self.lbl_instance_identity = QLabel(self._statusbar_instance_identity_text())
        self.statusbar.addPermanentWidget(self.lbl_instance_identity)

        # Torrent count label
        self.lbl_count = QLabel("0 torrents")
        self.statusbar.addPermanentWidget(self.lbl_count)

        # Progress bar (always visible at the far right)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.statusbar.addPermanentWidget(self.progress_bar)
        self._update_statusbar_transfer_summary()

    def _statusbar_instance_identity_text(self) -> str:
        """Build left-most status bar identity text for current connection/instance."""
        user = str(
            self.qb_conn_info.get("username", self.config.get("qb_username", "admin"))
            if isinstance(self.config, dict)
            else self.qb_conn_info.get("username", "admin")
        ).strip() or "admin"
        raw_host = str(
            self.config.get("qb_host", self.qb_conn_info.get("host", "localhost"))
            if isinstance(self.config, dict)
            else self.qb_conn_info.get("host", "localhost")
        ).strip() or "localhost"
        host = raw_host
        if "://" in raw_host:
            try:
                parsed = urlparse(raw_host)
                host = str(parsed.hostname or raw_host).strip() or "localhost"
            except Exception:
                host = raw_host
        port = _normalize_instance_port(
            self.config.get("qb_port", self.qb_conn_info.get("port", 8080))
            if isinstance(self.config, dict)
            else self.qb_conn_info.get("port", 8080)
        )
        counter = _normalize_instance_counter(
            self.config.get("_instance_counter", 1) if isinstance(self.config, dict) else 1
        )
        return f"{user}@{host}:{port} [{counter}]"

    # ========================================================================
    # Connection Configuration
    # ========================================================================

    def _build_connection_info(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Build qBittorrent connection info from TOML config with env var fallback.

        Supports HTTP basic auth (separate from qBittorrent API auth) via the
        host URL (e.g. https://user:password@remote.host.com:12345) or via
        explicit http_basic_auth_username / http_basic_auth_password config keys.
        Protocol scheme can be forced via optional http_protocol_scheme (http/https).
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
            'DISABLE_LOGGING_DEBUG_OUTPUT': False
        }
        if extra_headers:
            conn['EXTRA_HEADERS'] = extra_headers

        return conn

    def _create_client(self) -> qbittorrentapi.Client:
        """Create and authenticate a qBittorrent API client."""
        qb_client = qbittorrentapi.Client(**self.qb_conn_info)
        qb = (
            _DebugAPIClientProxy(qb_client, self)
            if self.debug_logging_enabled
            else qb_client
        )
        qb.auth_log_in()
        return qb

    # ========================================================================
    # Content Cache
    # ========================================================================

    def _remove_expired_cache_file(self):
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
        except Exception as e:
            logger.warning("Failed to remove expired content cache %s: %s", self.cache_file_path, e)

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

    def _apply_default_main_splitter_width(self):
        """Apply default left-panel width in pixels on current splitter geometry."""
        total_width = self.main_splitter.width()
        if total_width <= 0:
            total_width = self.width()
        if total_width <= 0:
            total_width = DEFAULT_WINDOW_WIDTH

        left_width = min(max(1, int(DEFAULT_LEFT_PANEL_WIDTH)), max(1, total_width - 1))
        right_width = max(1, total_width - left_width)
        self.main_splitter.setSizes([left_width, right_width])

    def _apply_default_torrent_header_layout(self):
        """Apply default torrent-table column order/widths/sort indicator."""
        header = self.tbl_torrents.horizontalHeader()

        # Restore natural logical->visual order.
        for logical in range(self.tbl_torrents.columnCount()):
            visual = header.visualIndex(logical)
            if visual != logical:
                header.moveSection(visual, logical)

        for idx, column in enumerate(self.torrent_columns):
            self.tbl_torrents.setColumnWidth(idx, int(column.get("width", 100)))
            self.tbl_torrents.setColumnHidden(
                idx, not bool(column.get("default_visible", True))
            )
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self._sync_torrent_column_actions()

    def _restore_default_view_state(self):
        """Restore baseline splitter/header states for Reset View."""
        try:
            self._apply_default_main_splitter_width()
        except Exception:
            self.main_splitter.setSizes([DEFAULT_LEFT_PANEL_WIDTH, 1000])

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
        self._sync_torrent_column_actions()

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

    def _settings_app_name(self) -> str:
        """Return per-instance QSettings app name."""
        return settings_app_name_for_instance(self.instance_id)

    def _new_settings(self) -> QSettings:
        """Create QSettings configured to use INI backend."""
        return QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            G_ORG_NAME,
            self._settings_app_name(),
        )

    def _settings_ini_path(self) -> Path:
        """Return the current INI file path used by QSettings."""
        settings = self._new_settings()
        settings.sync()
        file_name = str(settings.fileName() or "").strip()
        fallback_name = f"{self._settings_app_name()}.ini"
        return Path(file_name) if file_name else Path(fallback_name).resolve()

    def _save_refresh_settings(self):
        """Persist only auto-refresh runtime settings."""
        settings = self._new_settings()
        settings.setValue("autoRefreshEnabled", bool(self.auto_refresh_enabled))
        settings.setValue("refreshIntervalSec", int(self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL)))

    def _setup_clipboard_monitor(self):
        """Attach clipboard change listener for optional auto-add behavior."""
        try:
            self._clipboard = QApplication.clipboard()
            if self._clipboard:
                self._clipboard.dataChanged.connect(self._on_clipboard_changed)
        except Exception as e:
            self._log("ERROR", f"Failed to initialize clipboard monitor: {e}")

    @staticmethod
    def _extract_magnet_link(text: str) -> str:
        """Extract first magnet link from arbitrary clipboard text."""
        if not text:
            return ""
        match = re.search(r"(magnet:\?[^\s]+)", text, flags=re.IGNORECASE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_torrent_hash(text: str) -> str:
        """Extract first torrent hash (hex/base32 BTIH forms) from text."""
        if not text:
            return ""
        match = re.search(
            r"\b([A-Fa-f0-9]{40}|[A-Fa-f0-9]{64}|[A-Za-z2-7]{32})\b",
            text
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _magnet_from_hash(torrent_hash: str) -> str:
        """Build magnet URI from torrent infohash."""
        normalized = str(torrent_hash or "").strip().lower()
        return f"magnet:?xt=urn:btih:{normalized}"

    def _remember_clipboard_key(self, key: str):
        """Remember processed clipboard key and evict oldest entries."""
        if not key or key in self._clipboard_seen_keys:
            return
        self._clipboard_seen_keys.add(key)
        self._clipboard_seen_order.append(key)
        while len(self._clipboard_seen_order) > CLIPBOARD_SEEN_LIMIT:
            evicted = self._clipboard_seen_order.popleft()
            self._clipboard_seen_keys.discard(evicted)

    def _queue_add_torrent_from_clipboard(self, magnet_url: str, source: str):
        """Queue add-torrent task for clipboard-derived magnet url."""
        self._log("INFO", f"Clipboard monitor detected {source}; adding torrent")
        self._set_status("Clipboard monitor: adding torrent...")
        self.api_queue.add_task(
            "add_torrent_from_clipboard",
            self._add_torrent_api,
            self._on_add_torrent_complete,
            {'urls': [magnet_url]}
        )

    def _process_clipboard_text(self, text: str) -> bool:
        """Process clipboard text and auto-add torrent when magnet/hash appears."""
        if not text:
            return False

        magnet_url = self._extract_magnet_link(text)
        if magnet_url:
            dedupe_key = f"magnet:{magnet_url.lower()}"
            if dedupe_key in self._clipboard_seen_keys:
                return False
            self._remember_clipboard_key(dedupe_key)
            self._queue_add_torrent_from_clipboard(magnet_url, "magnet link")
            return True

        torrent_hash = self._extract_torrent_hash(text)
        if torrent_hash:
            normalized = torrent_hash.lower()
            dedupe_key = f"hash:{normalized}"
            if dedupe_key in self._clipboard_seen_keys:
                return False
            self._remember_clipboard_key(dedupe_key)
            self._queue_add_torrent_from_clipboard(
                self._magnet_from_hash(normalized),
                "torrent hash"
            )
            return True

        return False

    def _on_clipboard_changed(self):
        """Clipboard signal handler used by monitor toggle."""
        if not self.clipboard_monitor_enabled or not self._clipboard:
            return
        try:
            text = (self._clipboard.text() or "").strip()
        except Exception:
            return
        if not text or text == self._last_clipboard_text:
            return
        self._last_clipboard_text = text
        self._process_clipboard_text(text)

    def _toggle_clipboard_monitor(self, enabled: bool):
        """Enable or disable clipboard monitor."""
        self.clipboard_monitor_enabled = bool(enabled)
        self._save_settings()
        state = "enabled" if self.clipboard_monitor_enabled else "disabled"
        self._log("INFO", f"Clipboard monitor {state}")
        self._set_status(f"Clipboard monitor {state}")
        if self.clipboard_monitor_enabled:
            self._on_clipboard_changed()

    def _edit_settings_ini_file(self):
        """Open QSettings INI file in system default editor."""
        try:
            ini_path = self._settings_ini_path()
            ini_path.parent.mkdir(parents=True, exist_ok=True)
            if not ini_path.exists():
                ini_path.touch()
            _open_file_in_default_app(str(ini_path))
            self._log("INFO", f"Opened settings INI file: {ini_path}")
            self._set_status(f"Opened INI: {ini_path}")
        except Exception as e:
            self._log("ERROR", f"Failed to open settings INI file: {e}")
            self._set_status(f"Failed to open INI file: {e}")

    def _web_ui_browser_url(self) -> str:
        """Build Web UI URL for the current qBittorrent connection."""
        user = str(
            self.qb_conn_info.get("username", self.config.get("qb_username", "admin"))
            if isinstance(self.config, dict)
            else self.qb_conn_info.get("username", "admin")
        ).strip() or "admin"
        configured_scheme = _normalize_http_protocol_scheme(
            self.config.get("http_protocol_scheme", "http")
            if isinstance(self.config, dict)
            else "http"
        )
        explicit_scheme_override = bool(
            isinstance(self.config, dict)
            and str(self.config.get("http_protocol_scheme", "") or "").strip()
        )
        raw_host = str(
            self.config.get("qb_host", self.qb_conn_info.get("host", "localhost"))
            if isinstance(self.config, dict)
            else self.qb_conn_info.get("host", "localhost")
        ).strip() or "localhost"
        host = raw_host
        scheme = configured_scheme
        host_port_from_url: Optional[int] = None
        if "://" in raw_host:
            try:
                parsed = urlparse(raw_host)
                host = str(parsed.hostname or raw_host).strip() or "localhost"
                parsed_scheme = _normalize_http_protocol_scheme(parsed.scheme or "http")
                scheme = configured_scheme if explicit_scheme_override else parsed_scheme
                host_port_from_url = parsed.port
            except Exception:
                host = raw_host
                host_port_from_url = None
        else:
            scheme = configured_scheme
        port = _normalize_instance_port(
            host_port_from_url
            if host_port_from_url is not None
            else (
                self.config.get("qb_port", self.qb_conn_info.get("port", 8080))
                if isinstance(self.config, dict)
                else self.qb_conn_info.get("port", 8080)
            )
        )
        encoded_user = quote(user, safe="")
        host_text = host
        if ":" in host_text and not host_text.startswith("["):
            host_text = f"[{host_text}]"
        return f"{scheme}://{encoded_user}@{host_text}:{port}"

    def _open_web_ui_in_browser(self):
        """Open qBittorrent Web UI URL in default browser."""
        try:
            url = self._web_ui_browser_url()
            _open_file_in_default_app(url)
            self._log("INFO", f"Opened qBittorrent Web UI: {url}")
            self._set_status(f"Opened Web UI: {url}")
        except Exception as e:
            self._log("ERROR", f"Failed to open qBittorrent Web UI: {e}")
            self._set_status(f"Failed to open Web UI: {e}")

    def _load_settings(self):
        """Load window geometry, splitter sizes, column widths, sort order,
        and filter selection from QSettings."""
        settings = self._new_settings()

        # Window geometry
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            default_width = DEFAULT_WINDOW_WIDTH
            default_height = DEFAULT_WINDOW_HEIGHT
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
        else:
            self._apply_default_main_splitter_width()
        right_sizes = settings.value("rightSplitter")
        if right_sizes:
            self.right_splitter.restoreState(right_sizes)

        # Torrent table header (column widths, order, sort)
        header_state = settings.value("torrentTableHeader")
        if header_state:
            self.tbl_torrents.horizontalHeader().restoreState(header_state)
        has_hidden_columns_key = settings.contains("torrentTableHiddenColumns")
        hidden_columns = settings.value("torrentTableHiddenColumns")
        if has_hidden_columns_key:
            if isinstance(hidden_columns, str):
                hidden_list = [hidden_columns]
            elif isinstance(hidden_columns, (list, tuple, set)):
                hidden_list = [str(v) for v in hidden_columns]
            else:
                hidden_list = []
            self._apply_hidden_columns_by_keys(hidden_list)
        else:
            medium_keys = set(MEDIUM_TORRENT_VIEW_KEYS)
            hidden_default = [
                col["key"]
                for col in self.torrent_columns
                if col["key"] not in medium_keys
            ]
            self._apply_hidden_columns_by_keys(hidden_default)

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
            self._update_auto_refresh_action_text()
        self._sync_auto_refresh_timer_state()

        # Display mode settings (QSettings-only)
        display_human = settings.value("displayHumanReadable")
        if display_human is not None:
            use_human = self._to_bool(display_human, True)
            mode = "human_readable" if use_human else "bytes"
            self.display_size_mode = mode
            self.display_speed_mode = mode
        else:
            # Backward compatibility for older persisted keys.
            self.display_size_mode = _normalize_display_mode(
                settings.value("displaySizeMode", self.display_size_mode),
                DEFAULT_DISPLAY_SIZE_MODE
            )
            self.display_speed_mode = _normalize_display_mode(
                settings.value("displaySpeedMode", self.display_speed_mode),
                DEFAULT_DISPLAY_SPEED_MODE
            )
        if hasattr(self, "action_human_readable"):
            hr_checked = (
                self.display_size_mode == "human_readable"
                and self.display_speed_mode == "human_readable"
            )
            action_signals = self.action_human_readable.blockSignals(True)
            self.action_human_readable.setChecked(hr_checked)
            self.action_human_readable.blockSignals(action_signals)

        # Clipboard monitor
        self.clipboard_monitor_enabled = self._to_bool(
            settings.value("clipboardMonitorEnabled"),
            self.clipboard_monitor_enabled
        )
        if hasattr(self, "action_clipboard_monitor"):
            self.action_clipboard_monitor.setChecked(self.clipboard_monitor_enabled)
        if self.clipboard_monitor_enabled:
            QTimer.singleShot(0, self._on_clipboard_changed)

        # Debug logging
        self.debug_logging_enabled = self._to_bool(
            settings.value("debugLoggingEnabled"),
            self.debug_logging_enabled,
        )
        if hasattr(self, "action_debug_logging"):
            self.action_debug_logging.setChecked(self.debug_logging_enabled)

    def _save_settings(self):
        """Save window geometry, splitter sizes, column widths, sort order,
        and filter selection to QSettings."""
        settings = self._new_settings()

        # Window geometry
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())

        # Splitter sizes
        settings.setValue("mainSplitter", self.main_splitter.saveState())
        settings.setValue("rightSplitter", self.right_splitter.saveState())

        # Torrent table header (column widths, order, sort)
        settings.setValue("torrentTableHeader",
                          self.tbl_torrents.horizontalHeader().saveState())
        hidden_columns = [
            col["key"]
            for idx, col in enumerate(self.torrent_columns)
            if self.tbl_torrents.isColumnHidden(idx)
        ]
        settings.setValue("torrentTableHiddenColumns", hidden_columns)

        # Filter selection
        settings.setValue("filterStatus", self.current_status_filter)
        settings.setValue("autoRefreshEnabled", bool(self.auto_refresh_enabled))
        settings.setValue("refreshIntervalSec", int(self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL)))
        settings.setValue(
            "displayHumanReadable",
            bool(
                self.display_size_mode == "human_readable"
                and self.display_speed_mode == "human_readable"
            )
        )
        settings.setValue("displaySizeMode", self.display_size_mode)
        settings.setValue("displaySpeedMode", self.display_speed_mode)
        settings.setValue("clipboardMonitorEnabled", bool(self.clipboard_monitor_enabled))
        settings.setValue("debugLoggingEnabled", bool(self.debug_logging_enabled))

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

    def _selected_remote_torrent_filters(self) -> Dict[str, Any]:
        """Build remote API filter kwargs from selected status/category/tag/private filters."""
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

    def _fetch_torrents(self, **_kw) -> List:
        """Fetch torrents via incremental sync/maindata and return current full list."""
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
            return {'data': [], 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _merge_sync_maindata(self, maindata: Any) -> List[Any]:
        """Merge one sync/maindata payload into local torrent map and return ordered list."""
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
        """Convert qBittorrent API list/dict entry objects to plain dict."""
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

    def _fetch_selected_torrent_trackers(self, torrent_hash: str, **_kw) -> Dict:
        """Fetch all tracker rows for one torrent."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                trackers = qb.torrents_trackers(torrent_hash=torrent_hash)

            rows = [self._entry_to_dict(entry) for entry in list(trackers or [])]
            elapsed = time.time() - start_time
            return {'data': rows, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': [], 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _fetch_selected_torrent_peers(self, torrent_hash: str, **_kw) -> Dict:
        """Fetch all peer rows for one torrent."""
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
            return {'data': rows, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': [], 'elapsed': elapsed, 'success': False, 'error': str(e)}

    @staticmethod
    def _tracker_host_from_url(url: str) -> str:
        """Extract tracker hostname from URL where possible."""
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

    def _fetch_tracker_health_data(self, torrent_hashes: List[str], **_kw) -> Dict:
        """Fetch and aggregate tracker health metrics across provided torrents."""
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
            return {'data': rows, 'elapsed': elapsed, 'success': True}
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

    def _add_torrent_api(self, torrent_data: Dict, **_kw) -> Dict[str, Any]:
        """Add a torrent via API"""
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
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_export_torrents(
        self,
        torrent_hashes: List[str],
        export_dir: str,
        name_map: Dict[str, str],
        **_kw,
    ) -> Dict:
        """Export selected torrents into .torrent files in the target directory."""
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

    def _api_pause_torrent(self, torrent_hashes: List[str], **_kw) -> Dict:
        """Pause one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_pause(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_resume_torrent(self, torrent_hashes: List[str], **_kw) -> Dict:
        """Resume one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_resume(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_force_start_torrent(self, torrent_hashes: List[str], **_kw) -> Dict:
        """Enable force start for one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_set_force_start(enable=True, torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_recheck_torrent(self, torrent_hashes: List[str], **_kw) -> Dict:
        """Recheck one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_recheck(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_increase_torrent_priority(self, torrent_hashes: List[str], **_kw) -> Dict:
        """Increase queue priority for one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_increase_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_decrease_torrent_priority(self, torrent_hashes: List[str], **_kw) -> Dict:
        """Decrease queue priority for one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_decrease_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_top_torrent_priority(self, torrent_hashes: List[str], **_kw) -> Dict:
        """Move one or more torrents to top queue priority via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_top_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_minimum_torrent_priority(self, torrent_hashes: List[str], **_kw) -> Dict:
        """Move one or more torrents to minimum queue priority via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_bottom_priority(torrent_hashes=list(torrent_hashes))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_apply_selected_torrent_edits(
        self,
        torrent_hash: str,
        updates: Dict[str, Any],
        **_kw,
    ) -> Dict:
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
                        limit=max(0, int(normalized_updates.get("download_limit_bytes", 0))),
                    )

                if "upload_limit_bytes" in normalized_updates:
                    qb.torrents_set_upload_limit(
                        torrent_hashes=hashes,
                        limit=max(0, int(normalized_updates.get("upload_limit_bytes", 0))),
                    )

            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_set_torrent_download_limit(self, torrent_hashes: List[str], limit_bytes: int, **_kw) -> Dict:
        """Set per-torrent download limit (bytes/sec) for selected torrents."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_set_download_limit(
                    torrent_hashes=list(torrent_hashes),
                    limit=max(0, int(limit_bytes))
                )
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_set_torrent_upload_limit(self, torrent_hashes: List[str], limit_bytes: int, **_kw) -> Dict:
        """Set per-torrent upload limit (bytes/sec) for selected torrents."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_set_upload_limit(
                    torrent_hashes=list(torrent_hashes),
                    limit=max(0, int(limit_bytes))
                )
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_set_global_download_limit(self, limit_bytes: int, **_kw) -> Dict:
        """Set global download limit (bytes/sec)."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.transfer_set_download_limit(limit=max(0, int(limit_bytes)))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_set_global_upload_limit(self, limit_bytes: int, **_kw) -> Dict:
        """Set global upload limit (bytes/sec)."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.transfer_set_upload_limit(limit=max(0, int(limit_bytes)))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_toggle_alt_speed_mode(self, **_kw) -> Dict:
        """Toggle alternative/global speed-limit mode."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.transfer_toggle_speed_limits_mode()
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_fetch_speed_limits_profile(self, **_kw) -> Dict:
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
            return {'data': {}, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_apply_speed_limits_profile(
        self,
        normal_dl: int,
        normal_ul: int,
        alt_dl: int,
        alt_ul: int,
        alt_enabled: bool,
        **_kw,
    ) -> Dict:
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
                qb.app_set_preferences({
                    alt_dl_key: max(0, int(alt_dl)),
                    alt_ul_key: max(0, int(alt_ul)),
                })

                current_mode = self._safe_int(qb.transfer_speed_limits_mode(), 0)
                desired_mode = 1 if bool(alt_enabled) else 0
                if current_mode != desired_mode:
                    qb.transfer_toggle_speed_limits_mode()

            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_fetch_app_preferences(self, **_kw) -> Dict:
        """Fetch raw qBittorrent application preferences."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                prefs_raw = qb.app_preferences()
            prefs = self._entry_to_dict(prefs_raw)
            elapsed = time.time() - start_time
            return {'data': prefs, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': {}, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_apply_app_preferences(self, updates: Dict[str, Any], **_kw) -> Dict:
        """Apply only changed application preferences."""
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
    ) -> Dict:
        """Set file priority for one file or a whole folder subtree."""
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
            return {'data': {}, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_rename_content_path(
        self,
        torrent_hash: str,
        old_relative_path: str,
        new_relative_path: str,
        is_file: bool,
        **_kw,
    ) -> Dict:
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
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_create_category(
        self,
        name: str,
        save_path: str,
        incomplete_path: str,
        use_incomplete_path: bool,
        **_kw,
    ) -> Dict:
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
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_edit_category(
        self,
        name: str,
        save_path: str,
        incomplete_path: str,
        use_incomplete_path: bool,
        **_kw,
    ) -> Dict:
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
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_delete_category(self, name: str, **_kw) -> Dict:
        """Delete one category."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_remove_categories(categories=[name])
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_create_tags(self, tags: List[str], **_kw) -> Dict:
        """Create one or more tags."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_create_tags(tags=list(tags))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_delete_tags(self, tags: List[str], **_kw) -> Dict:
        """Delete one or more tags."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_delete_tags(tags=list(tags))
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_pause_session(self, **_kw) -> Dict:
        """Pause all torrents in current qBittorrent session."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_pause(torrent_hashes="all")
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_resume_session(self, **_kw) -> Dict:
        """Resume all torrents in current qBittorrent session."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_resume(torrent_hashes="all")
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_delete_torrent(self, torrent_hashes: List[str], delete_files: bool, **_kw) -> Dict:
        """Delete one or more torrents via API."""
        start_time = time.time()
        try:
            with self._create_client() as qb:
                qb.torrents_delete(torrent_hashes=list(torrent_hashes), delete_files=delete_files)
            elapsed = time.time() - start_time
            return {'data': True, 'elapsed': elapsed, 'success': True}
        except Exception as e:
            elapsed = time.time() - start_time
            return {'data': False, 'elapsed': elapsed, 'success': False, 'error': str(e)}

    def _api_ban_peers(self, peers: List[str], **_kw) -> Dict:
        """Ban one or more peer endpoints (IP:port) globally in qBittorrent."""
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

    # ========================================================================
    # API Callbacks
    # ========================================================================

    def _set_categories_from_payload(self, payload: Any):
        """Normalize categories payload and update category state/tree."""
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

    def _taxonomy_category_data(self) -> Dict[str, Dict[str, Any]]:
        """Build category metadata mapping for manager dialog."""
        return {
            name: {
                "save_path": self._category_save_path_by_name(name),
                "incomplete_path": self._category_incomplete_path_by_name(name),
                "use_incomplete_path": self._category_use_incomplete_path_by_name(name),
            }
            for name in self.categories
        }

    def _sync_taxonomy_dialog_data(self):
        """Refresh taxonomy dialog data when open."""
        dialog = self._taxonomy_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_taxonomy_data(self._taxonomy_category_data(), list(self.tags))

    def _on_categories_loaded(self, result: Dict):
        """Handle categories loaded"""
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

    def _on_tags_loaded(self, result: Dict):
        """Handle tags loaded"""
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

    def _on_torrents_loaded(self, result: Dict):
        """Handle torrents loaded"""
        try:
            if not result.get('success', False):
                self._latest_torrent_fetch_remote_filtered = False
                error = result.get('error', 'Unknown error')
                self._log("ERROR", f"Failed to load torrents: {error}", result.get('elapsed', 0))
                self._hide_progress()
                self._set_status(f"Error: {error}")
                # Show empty table
                self.all_torrents = []
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
            self.filtered_torrents = []
            self._update_window_title_speeds()
            self._update_statusbar_transfer_summary()
            self._update_torrents_table()
        finally:
            self._set_refresh_torrents_in_progress(False)

    def _select_first_torrent_after_refresh(self, previous_selected_hash: Optional[str] = None):
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

    def _on_apply_selected_torrent_edits_done(self, result: Dict):
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

    # ========================================================================
    # Task Queue Event Handlers
    # ========================================================================

    def _on_task_completed(self, task_name: str, result):
        """Handle task completion"""
        self._maybe_bump_auto_refresh_interval_from_api_elapsed(task_name, result)
        self._log("DEBUG", f"Task completed: {task_name}")

    def _maybe_bump_auto_refresh_interval_from_api_elapsed(self, task_name: str, result: Any):
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

    def _on_task_failed(self, task_name: str, error_msg: str):
        """Handle task failure"""
        if task_name == "refresh_torrents":
            self._set_refresh_torrents_in_progress(False)
        self._log("ERROR", f"Task failed: {task_name} - {error_msg}")
        self._set_status(f"Error: {error_msg}")
        self._hide_progress()

    def _on_task_cancelled(self, task_name: str):
        """Handle task cancellation"""
        if task_name == "refresh_torrents":
            self._set_refresh_torrents_in_progress(False)
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
        """Approximate qBittorrent status filters from torrent state/speeds."""
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
        """Match one torrent against selected category filter."""
        torrent_category = str(getattr(torrent, "category", "") or "")
        return torrent_category == str(category_filter or "")

    def _torrent_matches_tag_filter(self, torrent, tag_filter: Any) -> bool:
        """Match one torrent against selected tag filter."""
        tag = str(tag_filter or "")
        tags = parse_tags(getattr(torrent, "tags", None))
        if tag == "":
            return len(tags) == 0
        return tag in tags

    def _clear_filters(self):
        """Clear all filters"""
        self.current_status_filter = 'all'
        self._clear_non_status_filters()

        # Clear tree selection
        self.tree_filters.clearSelection()
        self._refresh_filter_tree_highlights()

        self._refresh_torrents()

    def _clear_non_status_filters(self):
        """Clear non-status torrent filters from quick bar and tree sections."""
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

    def _show_status_filter_only(self, status_filter: str):
        """Show one status bucket and clear all other torrent filters."""
        status = str(status_filter or "all").strip().lower()
        if status not in STATUS_FILTERS:
            status = "all"
        self.current_status_filter = status
        self._clear_non_status_filters()

        # Clear tree selection
        self.tree_filters.clearSelection()
        self._refresh_filter_tree_highlights()

        self._refresh_torrents()

    def _show_active_torrents_only(self):
        """Show only active torrents and clear all non-status filters."""
        self._show_status_filter_only("active")

    def _show_completed_torrents_only(self):
        """Show only completed torrents and clear all non-status filters."""
        self._show_status_filter_only("completed")

    def _show_all_torrents_only(self):
        """Show all torrents and clear all non-status filters."""
        self._show_status_filter_only("all")

    def _on_filter_tree_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle click on the unified filter tree."""
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

    def _tracker_display_text(self, tracker_url: str) -> str:
        """Render tracker URL as hostname where possible."""
        text = str(tracker_url or "")
        if not text:
            return ""
        try:
            parsed = urlparse(text)
            return parsed.hostname or text
        except Exception:
            return text

    def _format_torrent_table_cell(self, torrent, column_key: str) -> Tuple[str, Qt.AlignmentFlag, Optional[float]]:
        """Return display text, alignment, and optional numeric sort value."""
        align_left = Qt.AlignmentFlag.AlignLeft
        align_right = Qt.AlignmentFlag.AlignRight
        align_center = Qt.AlignmentFlag.AlignCenter

        def _raw_value(key: str, default: Any = None) -> Any:
            return getattr(torrent, key, default)

        def _as_bool(value: Any) -> Optional[bool]:
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

    def _update_torrents_table(self):
        """Update the torrents table with filtered data"""
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

    def _copy_general_details(self):
        """Copy general details panel content to clipboard."""
        text = self.txt_general_details.toPlainText().strip()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._set_status("General details copied to clipboard")

    @staticmethod
    def _details_table_has_data_rows(table: QTableWidget) -> bool:
        """Return True when details table contains actual data rows (not info placeholder)."""
        if table.rowCount() <= 0 or table.columnCount() <= 0:
            return False
        if table.columnCount() == 1:
            header = table.horizontalHeaderItem(0)
            if header and str(header.text() or "").strip().lower() == "info":
                return False
        return True

    @staticmethod
    def _details_table_column_index(table: QTableWidget, column_name: str) -> int:
        """Find one details-table column index by header name (case-insensitive)."""
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
        """Return first selected row index for table, if any."""
        sel_model = table.selectionModel()
        if sel_model:
            selected_rows = sel_model.selectedRows()
            if selected_rows:
                return selected_rows[0].row()
        current = table.currentRow()
        return current if current >= 0 else None

    def _details_table_to_tsv(self, table: QTableWidget, row_indexes: Optional[List[int]] = None) -> str:
        """Serialize one details table subset to TSV (header + rows)."""
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
        """Return selected peer endpoint as IP:port."""
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

    def _copy_all_peers_info(self):
        """Copy all currently visible peers rows (including headers) to clipboard."""
        if not self._details_table_has_data_rows(self.tbl_peers):
            self._set_status("No peers info to copy")
            return
        text = self._details_table_to_tsv(self.tbl_peers)
        QApplication.clipboard().setText(text)
        self._set_status("All peers info copied to clipboard")

    def _copy_selected_peer_info(self):
        """Copy selected peer row (including headers) to clipboard."""
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

    def _copy_selected_peer_ip_port(self):
        """Copy selected peer endpoint to clipboard."""
        endpoint = self._selected_peer_endpoint()
        if not endpoint:
            self._set_status("Select one peer with valid IP and port")
            return
        QApplication.clipboard().setText(endpoint)
        self._set_status("Peer IP:port copied to clipboard")

    def _build_peers_context_menu(self) -> QMenu:
        """Build context menu for peers table."""
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

    def _show_peers_context_menu(self, pos):
        """Show peers context menu and keep right-clicked row selected."""
        row_idx = self.tbl_peers.rowAt(pos.y())
        if row_idx >= 0:
            self.tbl_peers.selectRow(row_idx)
        menu = self._build_peers_context_menu()
        menu.exec(self.tbl_peers.viewport().mapToGlobal(pos))

    def _ban_selected_peer(self):
        """Ban selected peer endpoint via qBittorrent API."""
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
        """Normalize one detail value for display."""
        if value is None:
            return fallback
        if isinstance(value, str):
            text = value.strip()
            return text if text else fallback
        return str(value)

    def _build_general_details_html(self, sections: List[Tuple[str, List[Tuple[str, Any]]]]) -> str:
        """Build rich read-only HTML layout for the General details panel."""
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

    def _set_torrent_edit_enabled(self, enabled: bool, message: str):
        """Enable/disable torrent edit controls and update state message."""
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

    def _clear_torrent_edit_panel(self, message: str):
        """Reset editable torrent fields."""
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

    def _refresh_torrent_edit_categories(self, current_category: str = ""):
        """Refresh category combo options while preserving text selection."""
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
        """Extract automatic torrent management state when available."""
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

    def _populate_torrent_edit_panel(self, torrent: Any):
        """Populate the editable torrent panel from selected torrent data."""
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
        """Normalize tag CSV to comma-separated string without extra spaces."""
        return ",".join(parse_tags(value))

    def _add_tags_to_torrent_edit(self):
        """Append selected tags from a multi-select dialog into edit tags field."""
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
        """Show multi-select picker for known tags and return selected values."""
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
        """Return True when a provided path exists on this machine."""
        candidate = self._expand_local_path(raw_path)
        if candidate is None:
            return False
        try:
            return candidate.exists()
        except Exception:
            return False

    def _update_torrent_edit_path_browse_buttons(self):
        """Show browse buttons only for paths that exist on this machine."""
        save_exists = self._path_exists_on_local_machine(self.txt_torrent_edit_save_path.text())
        incomplete_exists = self._path_exists_on_local_machine(self.txt_torrent_edit_incomplete_path.text())
        self.btn_torrent_edit_browse_save_path.setVisible(save_exists)
        self.btn_torrent_edit_browse_incomplete_path.setVisible(incomplete_exists)

    def _on_detail_tab_changed(self, _index: int):
        """React to details tab switches that affect auto-refresh policy."""
        self._sync_auto_refresh_timer_state()

    def _is_torrent_edit_tab_active(self) -> bool:
        """Return True when Edit tab is selected and active for editing."""
        if not self.detail_tabs.isEnabled():
            return False
        if self.tab_torrent_edit is None:
            return False
        if self.detail_tabs.currentWidget() is not self.tab_torrent_edit:
            return False
        return self.btn_torrent_edit_apply.isEnabled()

    def _sync_auto_refresh_timer_state(self):
        """Start/stop refresh timer based on settings and current details context."""
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

    def _set_refresh_torrents_in_progress(self, in_progress: bool):
        """Set refresh-in-progress state and re-evaluate auto-refresh timer."""
        active = bool(in_progress)
        if self._refresh_torrents_in_progress == active:
            return
        self._refresh_torrents_in_progress = active
        self._sync_auto_refresh_timer_state()

    def _update_auto_refresh_action_text(self):
        """Refresh auto-refresh menu label to include current interval."""
        if not hasattr(self, "action_auto_refresh"):
            return
        interval_seconds = max(1, self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL))
        self.action_auto_refresh.setText(f"Enable &Auto-Refresh ({interval_seconds})")

    @staticmethod
    def _detail_cell_text(value: Any) -> str:
        """Render one trackers/peers cell value to text."""
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
        """Return numeric sort value when possible."""
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
        """Build ordered column list with preferred first, then remaining keys."""
        key_set = set()
        for row in rows:
            key_set.update(str(k) for k in row.keys())

        ordered = [k for k in preferred if k in key_set]
        remainder = sorted(k for k in key_set if k not in ordered)
        return ordered + remainder

    def _set_details_table_message(self, table: QTableWidget, message: str):
        """Show one-line status message inside details table."""
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
                                preferred_columns: List[str]):
        """Populate one details table (trackers/peers) with dynamic columns."""
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
        selected = getattr(self, "_selected_torrent", None)
        return str(getattr(selected, "hash", "") or "")

    def _load_selected_torrent_network_details(self, torrent_hash: str):
        """Load full trackers and peers information for selected torrent."""
        self._set_details_table_message(self.tbl_trackers, "Loading trackers...")
        self._set_details_table_message(self.tbl_peers, "Loading peers...")

        self.details_api_queue.add_task(
            "load_selected_trackers",
            self._fetch_selected_torrent_trackers,
            lambda r, h=torrent_hash: self._on_selected_trackers_loaded(h, r),
            torrent_hash
        )

    def _on_selected_trackers_loaded(self, torrent_hash: str, result: Dict):
        """Populate Trackers table and then load Peers for same selection."""
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

    def _on_selected_peers_loaded(self, torrent_hash: str, result: Dict):
        """Populate Peers table for currently selected torrent."""
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

    def _set_details_panels_enabled(self, enabled: bool):
        """Enable/disable bottom details tabs."""
        self.detail_tabs.setEnabled(bool(enabled))
        self._sync_auto_refresh_timer_state()

    def _clear_details_panels(self, reason: str):
        """Clear all details panels with a reason message for trackers/peers."""
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

    def _on_torrent_selected(self):
        """Handle torrent selection in table"""
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

    def _display_torrent_details(self, torrent):
        """Display detailed information about selected torrent."""
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

    # ========================================================================
    # Actions
    # ========================================================================

    def _copy_torrent_hash(self):
        """Copy selected torrent hash to clipboard."""
        hashes = self._get_selected_torrent_hashes()
        if hashes:
            QApplication.clipboard().setText("\n".join(hashes))
            if len(hashes) == 1:
                self._set_status("Hash copied to clipboard")
            else:
                self._set_status(f"{len(hashes)} hashes copied to clipboard")

    def _browse_torrent_edit_save_path(self):
        """Browse for a new torrent save path."""
        initial = self.txt_torrent_edit_save_path.text().strip()
        selected = QFileDialog.getExistingDirectory(self, "Select Save Path", initial)
        if selected:
            self.txt_torrent_edit_save_path.setText(selected)

    def _browse_torrent_edit_incomplete_path(self):
        """Browse for a new torrent incomplete save path."""
        initial = self.txt_torrent_edit_incomplete_path.text().strip()
        selected = QFileDialog.getExistingDirectory(self, "Select Incomplete Save Path", initial)
        if selected:
            self.txt_torrent_edit_incomplete_path.setText(selected)

    def _collect_selected_torrent_edit_updates(self) -> Dict[str, Any]:
        """Collect changed edit fields for currently selected torrent."""
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

    def _apply_selected_torrent_edits(self):
        """Apply torrent edits for exactly one selected torrent."""
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

    def _refresh_torrents(self):
        """Refresh torrent list"""
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

    @staticmethod
    def _build_new_instance_command(config_file_path: str, instance_counter: Optional[int] = None) -> List[str]:
        """Build command line used to spawn one new application instance."""
        config_path = str(Path(str(config_file_path)).expanduser().resolve())
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "-c",
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
    ):
        """Spawn one new process instance with the provided config path."""
        try:
            command = self._build_new_instance_command(config_file_path, instance_counter)
            subprocess.Popen(command)
            self._log("INFO", f"Launched new instance: {' '.join(command)}")
            self._set_status(f"Launched new instance: {Path(command[3]).name}")
        except Exception as e:
            self._log("ERROR", f"Failed to launch new instance: {e}")
            self._set_status(f"Failed to launch new instance: {e}")

    def _launch_new_instance_current_config(self):
        """Launch a new app instance using the currently loaded config file."""
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

    def _launch_new_instance_from_config(self):
        """Launch a new app instance after selecting a .toml config file."""
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

    def _show_add_torrent_dialog(self):
        """Show add torrent dialog"""
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

    def _on_add_torrent_dialog_closed(self, _result: int):
        """Clear cached Add Torrent dialog reference."""
        self._add_torrent_dialog = None

    def _on_add_torrent_dialog_accepted(self):
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
                "add_torrent",
                self._add_torrent_api,
                self._on_add_torrent_complete,
                torrent_data
            )

    @staticmethod
    def _sanitize_export_filename(name: Any, fallback: str = "torrent") -> str:
        """Sanitize one torrent name for safe local .torrent filenames."""
        text = str(name or "").strip()
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
        text = text.strip().strip(".")
        text = re.sub(r"\s+", " ", text)
        return text or fallback

    @staticmethod
    def _unique_export_file_path(export_dir: Path, base_name: str, torrent_hash: str, used_names: set) -> Path:
        """Return a unique destination file path for one exported torrent file."""
        sanitized_base = MainWindow._sanitize_export_filename(base_name, fallback=torrent_hash[:12] or "torrent")
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
        """Build hash->name mapping for selected torrents to name exported files."""
        name_map: Dict[str, str] = {}
        for torrent_hash in list(torrent_hashes or []):
            torrent = self._find_torrent_by_hash(str(torrent_hash or ""))
            name_map[str(torrent_hash or "")] = str(getattr(torrent, "name", "") or "")
        return name_map

    def _export_selected_torrents(self):
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

    def _on_export_selected_torrents_done(self, result: Dict):
        """Handle completion of selected-torrent export action."""
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

    def _find_torrent_by_hash(self, torrent_hash: str):
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
    def _expand_local_path(raw_path: Any) -> Optional[Path]:
        """Expand user/env vars for a local path string."""
        text = str(raw_path or "").strip().strip('"').strip("'")
        if not text:
            return None
        expanded = os.path.expandvars(os.path.expanduser(text))
        if not expanded:
            return None
        return Path(expanded)

    def _resolve_local_torrent_directory(self, torrent) -> Optional[Path]:
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

    def _open_selected_torrent_location(self):
        """Open selected torrent local directory when it exists on this machine."""
        selected_hashes = self._get_selected_torrent_hashes()
        if len(selected_hashes) != 1:
            if selected_hashes:
                self._set_status("Select one torrent to open its local directory")
            return

        self._open_torrent_location_by_hash(selected_hashes[0])

    def _open_torrent_location_by_hash(self, torrent_hash: str):
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

        _open_file_in_default_app(str(local_dir))
        self._set_status(f"Opened local directory: {local_dir}")

    def _on_torrent_table_item_double_clicked(self, item: QTableWidgetItem):
        """Open local torrent directory for the row that was double-clicked."""
        if item is None:
            return
        hash_item = self.tbl_torrents.item(item.row(), 0)
        torrent_hash = hash_item.text().strip() if hash_item else ""
        self._open_torrent_location_by_hash(torrent_hash)

    def _on_content_tree_item_activated(self, item: QTreeWidgetItem, _column: int):
        """Open activated content-tree item (Enter/double-click behavior)."""
        self._open_selected_content_path(item=item)

    def _open_selected_content_path(self, item: Optional[QTreeWidgetItem] = None):
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

        _open_file_in_default_app(str(candidate))
        target_type = "file" if is_file else "directory"
        self._set_status(f"Opened local {target_type}: {candidate}")

    def _get_selected_torrent_hash(self) -> Optional[str]:
        """Get the hash of the currently selected torrent, or None."""
        hashes = self._get_selected_torrent_hashes()
        if not hashes:
            return None
        return hashes[0]

    def _get_selected_torrent_hashes(self) -> List[str]:
        """Get unique selected torrent hashes preserving current row order."""
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

    def _on_ban_peer_done(self, endpoint: str, result: Dict):
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

    def _queue_bulk_torrent_action(self, task_name: str, api_method, action_name: str,
                                   singular_progress: str, plural_progress: str):
        """Queue a bulk action for currently selected torrents."""
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

    def _pause_torrent(self):
        """Pause selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "pause_torrent",
            self._api_pause_torrent,
            "Pause",
            "Pausing torrent...",
            "Pausing {count} torrents...",
        )

    def _resume_torrent(self):
        """Resume selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "resume_torrent",
            self._api_resume_torrent,
            "Resume",
            "Resuming torrent...",
            "Resuming {count} torrents...",
        )

    def _force_start_torrent(self):
        """Force-start selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "force_start_torrent",
            self._api_force_start_torrent,
            "Force Start",
            "Force-starting torrent...",
            "Force-starting {count} torrents...",
        )

    def _recheck_torrent(self):
        """Recheck selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "recheck_torrent",
            self._api_recheck_torrent,
            "Recheck",
            "Rechecking torrent...",
            "Rechecking {count} torrents...",
        )

    def _increase_torrent_priority(self):
        """Increase queue priority for selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "increase_torrent_priority",
            self._api_increase_torrent_priority,
            "Increase Priority",
            "Increasing queue priority...",
            "Increasing queue priority for {count} torrents...",
        )

    def _decrease_torrent_priority(self):
        """Decrease queue priority for selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "decrease_torrent_priority",
            self._api_decrease_torrent_priority,
            "Decrease Priority",
            "Decreasing queue priority...",
            "Decreasing queue priority for {count} torrents...",
        )

    def _top_torrent_priority(self):
        """Set top queue priority for selected torrent(s)."""
        self._queue_bulk_torrent_action(
            "top_torrent_priority",
            self._api_top_torrent_priority,
            "Top Priority",
            "Setting top queue priority...",
            "Setting top queue priority for {count} torrents...",
        )

    def _minimum_torrent_priority(self):
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
    def _bytes_to_kib(limit_bytes: Any) -> int:
        """Convert bytes/s to KiB/s for UI controls."""
        try:
            return max(0, int(limit_bytes)) // 1024
        except Exception:
            return 0

    def _prompt_limit_kib(self, title: str, label: str) -> Optional[int]:
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

    def _set_torrent_download_limit(self):
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
        self._log(
            "INFO",
            f"Setting download limit for {count} torrent(s) to {limit_kib} KiB/s"
        )

    def _set_torrent_upload_limit(self):
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
        self._log(
            "INFO",
            f"Setting upload limit for {count} torrent(s) to {limit_kib} KiB/s"
        )

    def _on_global_bandwidth_action_done(self, action_name: str, result: Dict):
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

    def _show_app_preferences_editor(self):
        """Open application preferences editor dialog."""
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

    def _on_app_preferences_dialog_closed(self, _result: int):
        """Clear cached app-preferences dialog reference."""
        self._app_preferences_dialog = None

    def _set_app_preferences_dialog_busy(self, busy: bool, message: str = ""):
        """Set app-preferences dialog busy state when open."""
        dialog = self._app_preferences_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _request_app_preferences_refresh(self):
        """Load raw app preferences into editor dialog."""
        self._show_progress("Loading app preferences...")
        self._set_app_preferences_dialog_busy(True, "Loading application preferences...")
        self.api_queue.add_task(
            "fetch_app_preferences",
            self._api_fetch_app_preferences,
            self._on_app_preferences_loaded,
        )

    def _on_app_preferences_loaded(self, result: Dict):
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

    def _on_app_preferences_apply_requested(self, changed_preferences: Dict[str, Any]):
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

    def _on_app_preferences_applied(self, result: Dict):
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

    def _show_speed_limits_manager(self):
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
        self._speed_limits_dialog = dialog
        dialog.show()
        self._request_speed_limits_profile()

    def _on_speed_limits_dialog_closed(self, _result: int):
        """Clear cached speed limits dialog reference."""
        self._speed_limits_dialog = None

    def _set_speed_limits_dialog_busy(self, busy: bool, message: str = ""):
        """Set speed dialog controls busy state when dialog is open."""
        dialog = self._speed_limits_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _request_speed_limits_profile(self):
        """Load current speed limits into manager dialog."""
        self._show_progress("Loading speed limits...")
        self._set_speed_limits_dialog_busy(True, "Loading speed limits...")
        self.api_queue.add_task(
            "fetch_speed_limits_profile",
            self._api_fetch_speed_limits_profile,
            self._on_speed_limits_profile_loaded,
        )

    def _on_speed_limits_profile_loaded(self, result: Dict):
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
    ):
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

    def _on_speed_limits_profile_applied(self, result: Dict):
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

    def _record_session_timeline_sample(self, alt_enabled: Optional[bool] = None):
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

    def _show_session_timeline(self):
        """Open session timeline dialog."""
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

    def _on_session_timeline_dialog_closed(self, _result: int):
        """Clear timeline dialog reference on close."""
        self._session_timeline_dialog = None

    def _clear_session_timeline_history(self):
        """Clear stored session timeline samples."""
        self.session_timeline_history.clear()
        dialog = self._session_timeline_dialog
        if dialog is not None and dialog.isVisible():
            dialog.set_samples([])

    def _show_tracker_health_dashboard(self):
        """Open tracker health dashboard dialog."""
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

    def _on_tracker_health_dialog_closed(self, _result: int):
        """Clear tracker-health dialog reference on close."""
        self._tracker_health_dialog = None

    def _set_tracker_health_dialog_busy(self, busy: bool, message: str = ""):
        """Set tracker-health dialog busy state."""
        dialog = self._tracker_health_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _request_tracker_health_refresh(self):
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

    def _on_tracker_health_loaded(self, result: Dict):
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

    def _set_global_download_limit(self):
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

    def _set_global_upload_limit(self):
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

    def _toggle_alt_speed_mode(self):
        """Toggle alternative speed mode."""
        self._show_progress("Toggling alternative speed mode...")
        self.api_queue.add_task(
            "toggle_alt_speed_mode",
            self._api_toggle_alt_speed_mode,
            lambda r: self._on_global_bandwidth_action_done("Toggle Alternative Speed Mode", r),
        )

    def _get_selected_content_item_info(self) -> Optional[Dict[str, Any]]:
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

    def _selected_torrent_hash_for_content_action(self) -> Optional[str]:
        """Return currently selected torrent hash for content actions."""
        torrent = getattr(self, "_selected_torrent", None)
        torrent_hash = str(getattr(torrent, "hash", "") or "").strip() if torrent else ""
        if not torrent_hash:
            self._set_status("Select exactly one torrent first")
            return None
        return torrent_hash

    def _on_content_action_done(self, action_name: str, result: Dict):
        """Callback for content actions (priority/rename)."""
        if result.get("success"):
            self._log("INFO", f"{action_name} succeeded", result.get("elapsed", 0))
            QTimer.singleShot(500, self._refresh_torrents)
        else:
            error = result.get("error", "Unknown error")
            self._log("ERROR", f"{action_name} failed: {error}", result.get("elapsed", 0))
            self._set_status(f"{action_name} failed: {error}")
        self._hide_progress()

    def _set_selected_content_priority(self, priority: int):
        """Set priority for selected content item (file/folder)."""
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

    def _rename_selected_content_item(self):
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
        new_name, ok = QInputDialog.getText(
            self,
            f"Rename {label.title()}",
            f"New {label} name:",
            text=old_name,
        )
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

    def _on_taxonomy_action_done(self, action_name: str, result: Dict):
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

    def _set_taxonomy_dialog_busy(self, busy: bool, message: str = ""):
        """Set taxonomy dialog busy state when open."""
        dialog = self._taxonomy_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            return
        dialog.set_busy(bool(busy), message)

    def _reload_taxonomy_data(self, action_name: str):
        """Reload categories+tags after taxonomy mutation."""
        self.api_queue.add_task(
            "reload_categories_for_taxonomy",
            self._fetch_categories,
            lambda r: self._on_taxonomy_categories_reloaded(action_name, r),
        )

    def _on_taxonomy_categories_reloaded(self, action_name: str, result: Dict):
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

    def _on_taxonomy_tags_reloaded(self, action_name: str, result: Dict):
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

    def _queue_taxonomy_action(self, task_name: str, api_method, action_name: str, *args):
        """Queue taxonomy mutation from manager dialog."""
        self._show_progress(f"{action_name}...")
        self._set_taxonomy_dialog_busy(True, f"{action_name}...")
        self.api_queue.add_task(
            task_name,
            api_method,
            lambda r: self._on_taxonomy_action_done(action_name, r),
            *args,
        )

    def _show_taxonomy_manager(self):
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
        self._taxonomy_dialog = dialog
        dialog.show()

    def _on_taxonomy_dialog_closed(self, _result: int):
        """Clear dialog reference when closed."""
        self._taxonomy_dialog = None

    def _on_taxonomy_create_category_requested(
        self,
        name: str,
        save_path: str,
        incomplete_path: str,
        use_incomplete_path: bool,
    ):
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
    ):
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

    def _on_taxonomy_delete_category_requested(self, name: str):
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

    def _on_taxonomy_create_tags_requested(self, tags: List[str]):
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

    def _on_taxonomy_delete_tags_requested(self, tags: List[str]):
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

    def _pause_session(self):
        """Pause all torrents in current session."""
        self._log("INFO", "Pausing session")
        self._show_progress("Pausing session...")
        self.api_queue.add_task(
            "pause_session",
            self._api_pause_session,
            lambda r: self._on_torrent_action_done("Pause Session", r),
        )

    def _resume_session(self):
        """Resume all torrents in current session."""
        self._log("INFO", "Resuming session")
        self._show_progress("Resuming session...")
        self.api_queue.add_task(
            "resume_session",
            self._api_resume_session,
            lambda r: self._on_torrent_action_done("Resume Session", r),
        )

    def _queue_delete_torrents(self, torrent_hashes: List[str], delete_files: bool,
                               action_name: str, progress_text: str):
        """Queue deletion for selected torrent(s) with explicit delete-files mode."""
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

    def _remove_torrent(self):
        """Remove selected torrent(s) and keep data on disk."""
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

    def _remove_torrent_and_delete_data(self):
        """Remove selected torrent(s) and delete data from disk."""
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

    def _remove_torrent_no_confirmation(self):
        """Remove selected torrent(s) and keep data on disk, without confirmation."""
        torrent_hashes = self._get_selected_torrent_hashes()
        if not torrent_hashes:
            return
        self._queue_delete_torrents(
            torrent_hashes,
            delete_files=False,
            action_name="Remove (No Confirmation)",
            progress_text="Removing torrent..." if len(torrent_hashes) == 1 else f"Removing {len(torrent_hashes)} torrents...",
        )

    def _remove_torrent_and_delete_data_no_confirmation(self):
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

    def _delete_torrent(self):
        """Delete selected torrent(s) with confirmation."""
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
            self._update_auto_refresh_action_text()
            self._sync_auto_refresh_timer_state()

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
            self._sync_auto_refresh_timer_state()
            if self.refresh_timer.isActive():
                self._log("INFO", f"Auto-refresh enabled ({self.refresh_interval}s)")
            else:
                self._log("INFO", "Auto-refresh enabled and paused on Edit tab")
        else:
            self._sync_auto_refresh_timer_state()
            self._log("INFO", "Auto-refresh disabled")
        self._save_refresh_settings()

    def _toggle_debug_logging(self, checked: bool):
        """Enable/disable comprehensive debug logging including API calls/responses."""
        self.debug_logging_enabled = bool(checked)
        if self.debug_logging_enabled:
            self._log("INFO", "Debug logging enabled (API calls/responses)")
            self._set_status("Debug logging enabled")
        else:
            self._log("INFO", "Debug logging disabled")
            self._set_status("Debug logging disabled")
        self._save_settings()

    def _toggle_human_readable(self, checked: bool):
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

    def _show_about(self):
        """Show about dialog."""
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

    # ========================================================================
    # UI Helper Methods
    # ========================================================================

    def _show_progress(self, message: str):
        """Show progress indicator"""
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self._set_status(message)

    def _hide_progress(self):
        """Hide progress indicator"""
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self._set_status("Ready")

    def _set_status(self, message: str):
        """Set status bar message"""
        self.lbl_status.setText(message)

    def _update_statusbar_transfer_summary(self):
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

    def _bring_to_front_startup(self):
        """Bring the main window to front shortly after startup."""
        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Handle Enter in content tree consistently across Qt styles/platforms."""
        if (
            watched is getattr(self, "tree_files", None)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self._open_selected_content_path()
            return True
        return super().eventFilter(watched, event)

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
        """Build bounded repr for debug log messages."""
        try:
            text = repr(value)
        except Exception:
            text = f"<unrepr {type(value).__name__}>"
        if isinstance(max_len, int) and max_len > 0 and len(text) > max_len:
            return text[:max_len] + "...<truncated>"
        return text

    def _debug_log_api_call(self, method_name: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]):
        """Log one qBittorrent API call invocation when debug logging is enabled."""
        if not self.debug_logging_enabled:
            return
        logger.debug(
            "[API CALL] %s args=%s kwargs=%s",
            str(method_name),
            self._safe_debug_repr(args),
            self._safe_debug_repr(kwargs),
        )

    def _debug_log_api_response(self, method_name: str, result: Any, elapsed: float):
        """Log one qBittorrent API call response when debug logging is enabled."""
        if not self.debug_logging_enabled:
            return
        logger.debug(
            "[API RESP] %s elapsed=%.3fs result=%s",
            str(method_name),
            float(elapsed),
            self._safe_debug_repr(result, max_len=None),
        )

    def _debug_log_api_error(self, method_name: str, error: Exception, elapsed: float):
        """Log one qBittorrent API call failure when debug logging is enabled."""
        if not self.debug_logging_enabled:
            return
        logger.debug(
            "[API ERR] %s elapsed=%.3fs error=%s",
            str(method_name),
            float(elapsed),
            self._safe_debug_repr(error),
        )

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
        if self._add_torrent_dialog is not None and self._add_torrent_dialog.isVisible():
            self._add_torrent_dialog.close()
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
        "http_protocol_scheme",
        "log_file",
        "title_bar_speed_format",
        "_config_file_path",
        "_log_file_path",
        "_instance_id",
        "_instance_counter",
        "_instance_lock_file_path",
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

    settings_managed_keys = (
        "auto_refresh",
        "refresh_interval",
        "default_window_width",
        "default_window_height",
        "default_status_filter",
        "display_size_mode",
        "display_speed_mode",
    )
    for key in settings_managed_keys:
        if key in normalized:
            _warn(f"'{key}' is ignored in TOML; managed via QSettings.")
            normalized.pop(key, None)

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

    # http_protocol_scheme (optional; defaults to http when absent)
    if "http_protocol_scheme" in normalized:
        raw_scheme = normalized.get("http_protocol_scheme")
        normalized_scheme = _normalize_http_protocol_scheme(raw_scheme)
        raw_scheme_text = (
            str(raw_scheme).strip().lower()
            if isinstance(raw_scheme, str)
            else ""
        )
        if raw_scheme_text not in ("http", "https"):
            _warn(
                f"'http_protocol_scheme' invalid ({raw_scheme!r}); using 'http'."
            )
        normalized["http_protocol_scheme"] = normalized_scheme

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

    # log_file
    raw_log_file = normalized.get("log_file", "qbiremo_enhanced.log")
    if not isinstance(raw_log_file, str) or not raw_log_file.strip():
        _warn(
            f"'log_file' invalid ({raw_log_file!r}); using 'qbiremo_enhanced.log'."
        )
        normalized["log_file"] = "qbiremo_enhanced.log"
    else:
        normalized["log_file"] = raw_log_file.strip()

    # title_bar_speed_format
    raw_title_fmt = normalized.get(
        "title_bar_speed_format",
        DEFAULT_TITLE_BAR_SPEED_FORMAT,
    )
    if not isinstance(raw_title_fmt, str) or not raw_title_fmt.strip():
        _warn(
            "'title_bar_speed_format' invalid; using default "
            f"{DEFAULT_TITLE_BAR_SPEED_FORMAT!r}."
        )
        title_fmt = DEFAULT_TITLE_BAR_SPEED_FORMAT
    else:
        title_fmt = raw_title_fmt.strip()
    try:
        title_fmt.format(up_text="0", down_text="0")
    except Exception:
        _warn(
            "'title_bar_speed_format' failed to format with {up_text}/{down_text}; "
            f"using default {DEFAULT_TITLE_BAR_SPEED_FORMAT!r}."
        )
        title_fmt = DEFAULT_TITLE_BAR_SPEED_FORMAT
    normalized["title_bar_speed_format"] = title_fmt

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
    instance_id = str(config.get("_instance_id", "") or "").strip().lower()
    if not instance_id:
        instance_id = compute_instance_id_from_config(config)
    config["_instance_id"] = instance_id

    log_file = config.get('log_file', 'qbiremo_enhanced.log')
    if not isinstance(log_file, str) or not log_file.strip():
        log_file = 'qbiremo_enhanced.log'
    log_file = log_file.strip()
    log_file = _append_instance_id_to_filename(log_file, instance_id)
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
        fallback_log_file = _append_instance_id_to_filename(
            'qbiremo_enhanced.log',
            instance_id,
        )
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
    def _positive_instance_counter(value: str) -> int:
        try:
            parsed = int(value)
        except Exception as e:
            raise argparse.ArgumentTypeError(
                f"instance_counter must be a positive integer: {value}"
            ) from e
        if parsed <= 0:
            raise argparse.ArgumentTypeError(
                f"instance_counter must be a positive integer: {value}"
            )
        return parsed

    parser = argparse.ArgumentParser(
        description="qBiremo Enhanced - Advanced qBittorrent GUI Client"
    )
    parser.add_argument(
        "-c", "--config-file",
        required=False,
        default="qbiremo_enhanced_config.toml",
        help="Path to configuration file (TOML format)"
    )
    parser.add_argument(
        "--instance_counter",
        "--instance-counter",
        dest="instance_counter",
        type=_positive_instance_counter,
        required=False,
        default=1,
        help=(
            "Positive instance counter suffix for the computed instance ID "
            "(default: 1). Use different values to run multiple instances "
            "against the same qBittorrent server."
        ),
    )

    args = parser.parse_args()
    config_file_path = str(Path(args.config_file).expanduser().resolve())

    # Load configuration (collect load-time issues before logging is configured)
    config, load_issues = load_config_with_issues(args.config_file)
    config["_config_file_path"] = config_file_path
    requested_counter = int(args.instance_counter)
    config["_instance_counter"] = requested_counter
    claimed_counter, claimed_instance_id, lock_path = acquire_instance_lock(
        config,
        requested_counter,
    )
    config["_instance_counter"] = int(claimed_counter)
    config["_instance_id"] = str(claimed_instance_id)
    config["_instance_lock_file_path"] = str(lock_path)
    if claimed_counter != requested_counter:
        load_issues.append(
            (
                "Lock file already exists; auto-incremented instance counter "
                f"from {requested_counter} to {claimed_counter} "
                f"({claimed_instance_id})."
            )
        )
    atexit.register(release_instance_lock, lock_path)

    # Set up logging *first*, then install the global exception hook
    file_handler = _setup_logging(config)
    _install_exception_hooks(file_handler)
    for issue in load_issues:
        logger.warning("%s", issue)

    # Validate and normalize config values now that file logging is active.
    config = validate_and_normalize_config(config, args.config_file)
    config["_config_file_path"] = config_file_path
    config["_instance_counter"] = int(claimed_counter)
    config["_instance_id"] = str(claimed_instance_id)
    config["_instance_lock_file_path"] = str(lock_path)

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
