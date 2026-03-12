"""Main window composition root and application entrypoint."""

import argparse
import atexit
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote, urlparse

import qbittorrentapi
from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QFontDatabase,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from threep_commons.desktop import open_path_in_default_app
from threep_commons.files import (
    build_instance_app_name,
    resolve_cache_file_path,
)
from threep_commons.formatters import (
    normalize_display_mode as _normalize_display_mode,
)
from threep_commons.instance_lock import (
    acquire_instance_lock,
    compute_instance_id,
    release_instance_lock,
)
from threep_commons.instance_lock import (
    normalize_http_protocol_scheme as _normalize_http_protocol_scheme,
)
from threep_commons.instance_lock import (
    normalize_instance_counter as _normalize_instance_counter,
)
from threep_commons.instance_lock import (
    normalize_instance_port as _normalize_instance_port,
)
from threep_commons.paths import configure_qsettings

from .config_runtime import (
    DEFAULT_PROFILE_ID,
    _default_instance_log_file_path,
    _install_exception_hooks,
    _setup_logging,
    compute_instance_id_from_config,
    get_missing_required_config,
    load_config_with_issues,
    normalize_profile_id,
    save_profile_config,
    validate_and_normalize_config,
)
from .constants import (
    APP_IDENTITY,
    BASIC_TORRENT_VIEW_KEYS,
    CACHE_FILE_NAME,
    CLIPBOARD_SEEN_LIMIT,
    DEFAULT_AUTO_REFRESH,
    DEFAULT_DISPLAY_SIZE_MODE,
    DEFAULT_DISPLAY_SPEED_MODE,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DEFAULT_LEFT_PANEL_WIDTH,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_STATUS_FILTER,
    DEFAULT_TITLE_BAR_SPEED_FORMAT,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    G_APP_NAME,
    G_ORG_NAME,
    MEDIUM_TORRENT_VIEW_KEYS,
    STATUS_FILTERS,
    TORRENT_COLUMNS,
)
from .controllers import (
    ActionsTaxonomyController,
    DetailsContentController,
    FilterTableController,
    NetworkApiController,
    SessionUiController,
)
from .dialogs import (
    AddTorrentDialog,
    AppPreferencesDialog,
    FriendlyAddPreferencesDialog,
    SessionTimelineDialog,
    SpeedLimitsDialog,
    TaxonomyManagerDialog,
    TrackerHealthDialog,
)
from .helpers import load_app_icon
from .models.config import NormalizedConfig
from .profile_wizard import run_profile_setup_wizard
from .tasking import APITaskQueue, Worker

if TYPE_CHECKING:
    from .models.torrent import (
        SessionTimelineSample,
        TorrentCacheEntry,
        TorrentFileEntry,
    )

logger = logging.getLogger(G_APP_NAME)

__all__ = [
    "BASIC_TORRENT_VIEW_KEYS",
    "DEFAULT_HTTP_TIMEOUT_SECONDS",
    "APITaskQueue",
    "AddTorrentDialog",
    "AppPreferencesDialog",
    "FriendlyAddPreferencesDialog",
    "MainWindow",
    "QDialog",
    "QFileDialog",
    "QFontDatabase",
    "QInputDialog",
    "QMessageBox",
    "SessionTimelineDialog",
    "SpeedLimitsDialog",
    "TaxonomyManagerDialog",
    "TrackerHealthDialog",
    "Worker",
    "compute_instance_id",
    "json",
    "main",
    "qbittorrentapi",
    "subprocess",
    "tempfile",
]


class MainWindow(QMainWindow):
    """Main application window."""

    def __getattr__(self, name: str) -> Any:
        """Keep runtime behavior while allowing statically unknown delegated members."""
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    @staticmethod
    def _coerce_int(value: object, default: int) -> int:
        """Parse int-like values safely while preserving the provided fallback."""
        try:
            return int(cast("Any", value))
        except (TypeError, ValueError, OverflowError):
            return int(default)

    def _install_controller_methods(self, controller_cls: type[object]) -> None:
        """Bind controller class methods onto this window when no local override exists."""
        for name, raw_attr in controller_cls.__dict__.items():
            descriptor = cast("Any", raw_attr)
            if name.startswith("__"):
                continue
            if name in {"eventFilter", "closeEvent"}:
                continue
            if hasattr(type(self), name):
                continue
            if name in self.__dict__:
                continue
            if isinstance(raw_attr, staticmethod):
                candidate = descriptor.__get__(None, controller_cls)
            elif isinstance(raw_attr, classmethod):
                candidate = descriptor.__get__(controller_cls, controller_cls)
            elif hasattr(raw_attr, "__get__"):
                candidate = descriptor.__get__(self, type(self))
            else:
                candidate = descriptor
            if not callable(candidate):
                continue
            setattr(self, name, candidate)

    def _initialize_controllers(self) -> None:
        """Create feature controllers and install delegated methods."""
        self._controller_classes = (
            NetworkApiController,
            FilterTableController,
            DetailsContentController,
            ActionsTaxonomyController,
            SessionUiController,
        )
        for controller_cls in self._controller_classes:
            self._install_controller_methods(controller_cls)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Delegate custom event-filter handling to session controller logic."""
        return SessionUiController.eventFilter(cast("SessionUiController", self), watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Delegate close-event cleanup to session controller logic."""
        SessionUiController.closeEvent(cast("SessionUiController", self), event)

    def __init__(self, config: NormalizedConfig) -> None:
        """Initialize UI, runtime state, queues, settings, and startup refresh."""
        super().__init__()
        configure_qsettings(APP_IDENTITY)
        self._initialize_controllers()

        normalized_config: NormalizedConfig = config if isinstance(config, dict) else {}
        self.config = normalized_config
        config = self.config
        self.instance_id = str(config.get("_instance_id", "") or "").strip().lower()
        if not self.instance_id:
            self.instance_id = compute_instance_id_from_config(config)
        self.base_window_title = "qBiremo Enhanced"
        self.setWindowTitle(self.base_window_title)
        window_icon = load_app_icon()
        if not window_icon.isNull():
            self.setWindowIcon(window_icon)

        # Connection info from profile config, falling back to env vars
        self.qb_conn_info = self._build_connection_info(config)

        # State
        self.all_torrents = []
        self.filtered_torrents = []
        self.categories = []
        self.category_details: dict[str, dict[str, object]] = {}
        self.tags = []
        self.trackers = []
        self.size_buckets = []
        self._filter_count_snapshot_signature_cached = (-1, -1)
        self._status_filter_counts: dict[str, int] = {}
        self._category_filter_counts: dict[object, int] = {}
        self._tag_filter_counts: dict[object, int] = {}
        self.torrent_columns = list(TORRENT_COLUMNS)
        self.torrent_column_index = {
            col["key"]: idx for idx, col in enumerate(self.torrent_columns)
        }
        self.column_visibility_actions: dict[str, QAction] = {}
        self.saved_torrent_views_menu: QMenu | None = None
        self._torrent_open_shortcuts: list[QShortcut] = []
        self._torrent_sort_shortcuts: list[QShortcut] = []
        self._content_open_shortcuts: list[QShortcut] = []
        self.clipboard_monitor_enabled = False
        self.debug_logging_enabled = False
        self._last_clipboard_text = ""
        self._clipboard_seen_keys = set()
        self._clipboard_seen_order = deque()
        self._clipboard = None

        # Defaults are managed by code/QSettings.
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
        self.current_content_files: list[TorrentFileEntry] = []
        self._selected_torrent = None
        self._torrent_edit_original: dict[str, object] = {}
        self.tab_torrent_edit: QWidget | None = None
        self._suppress_next_cache_save = False
        self._sync_rid = 0
        self._sync_torrent_map: dict[str, dict[str, object]] = {}
        self._latest_torrent_fetch_remote_filtered = False
        self._taxonomy_dialog: TaxonomyManagerDialog | None = None
        self._speed_limits_dialog: SpeedLimitsDialog | None = None
        self._app_preferences_dialog: AppPreferencesDialog | None = None
        self._friendly_add_preferences_dialog: FriendlyAddPreferencesDialog | None = None
        self._tracker_health_dialog: TrackerHealthDialog | None = None
        self._session_timeline_dialog: SessionTimelineDialog | None = None
        self._add_torrent_dialog: AddTorrentDialog | None = None
        self.session_timeline_history: deque[SessionTimelineSample] = deque(maxlen=720)
        self._last_alt_speed_mode = False
        self._last_dht_nodes = 0
        self._last_global_download_limit = 0
        self._last_global_upload_limit = 0

        # Persistent per-torrent content cache (JSON file)
        self.cache_file_path = resolve_cache_file_path(
            APP_IDENTITY,
            CACHE_FILE_NAME,
            instance_id=self.instance_id,
        )
        self.content_cache: dict[str, TorrentCacheEntry] = {}
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
            "_log_file_path",
            _default_instance_log_file_path(self.instance_id),
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
            (self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowMaximized
        )
        self.show()
        QTimer.singleShot(500, self._bring_to_front_startup)

    def _create_ui(self) -> None:
        """Create the main UI layout."""
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

        self._create_details_tabs()
        self.right_splitter.addWidget(self.detail_tabs)

        self.main_splitter.addWidget(self.right_splitter)

        # Set initial sizes
        self.main_splitter.setSizes([DEFAULT_LEFT_PANEL_WIDTH, 1000])
        self.right_splitter.setSizes([600, 200])

        main_layout.addWidget(self.main_splitter)

    def _create_details_tabs(self) -> None:
        """Create details tabs (General/Trackers/Peers/Content/Edit)."""
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.detail_tabs.addTab(self._build_general_details_tab(), "General")
        self.detail_tabs.addTab(self._build_trackers_details_tab(), "Trackers")
        self.detail_tabs.addTab(self._build_peers_details_tab(), "Peers")

        self._set_details_table_message(self.tbl_trackers, "No torrent selected.")
        self._set_details_table_message(self.tbl_peers, "No torrent selected.")
        self.detail_tabs.addTab(self._build_content_details_tab(), "Content")

        edit_widget = self._build_torrent_edit_tab()
        self.detail_tabs.addTab(edit_widget, "Edit")
        self.tab_torrent_edit = edit_widget
        self.detail_tabs.currentChanged.connect(self._on_detail_tab_changed)
        self._set_torrent_edit_enabled(False, "Select one torrent to edit.")

    def _build_general_details_tab(self) -> QWidget:
        """Build and return the details General tab."""
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
        return general_widget

    def _build_details_table(self) -> QTableWidget:
        """Create a read-only details table with shared visual behavior."""
        table = QTableWidget()
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _build_trackers_details_tab(self) -> QWidget:
        """Build and return the details Trackers tab."""
        trackers_widget = QWidget()
        trackers_layout = QVBoxLayout(trackers_widget)
        trackers_layout.setContentsMargins(4, 4, 4, 4)
        self.tbl_trackers = self._build_details_table()
        trackers_layout.addWidget(self.tbl_trackers)
        return trackers_widget

    def _build_peers_details_tab(self) -> QWidget:
        """Build and return the details Peers tab."""
        peers_widget = QWidget()
        peers_layout = QVBoxLayout(peers_widget)
        peers_layout.setContentsMargins(4, 4, 4, 4)
        self.tbl_peers = self._build_details_table()
        self.tbl_peers.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl_peers.customContextMenuRequested.connect(self._show_peers_context_menu)
        peers_layout.addWidget(self.tbl_peers)
        return peers_widget

    def _build_content_details_tab(self) -> QWidget:
        """Build and return the details Content tab."""
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

        content_actions_layout = QHBoxLayout()
        self.btn_content_skip = QPushButton("Skip")
        self.btn_content_skip.clicked.connect(lambda: self._set_selected_content_priority(0))
        content_actions_layout.addWidget(self.btn_content_skip)
        self.btn_content_normal = QPushButton("Normal Priority")
        self.btn_content_normal.clicked.connect(lambda: self._set_selected_content_priority(1))
        content_actions_layout.addWidget(self.btn_content_normal)
        self.btn_content_high = QPushButton("High Priority")
        self.btn_content_high.clicked.connect(lambda: self._set_selected_content_priority(6))
        content_actions_layout.addWidget(self.btn_content_high)
        self.btn_content_max = QPushButton("Maximum Priority")
        self.btn_content_max.clicked.connect(lambda: self._set_selected_content_priority(7))
        content_actions_layout.addWidget(self.btn_content_max)
        self.btn_content_rename = QPushButton("Rename...")
        self.btn_content_rename.clicked.connect(lambda: self._rename_selected_content_item())
        content_actions_layout.addWidget(self.btn_content_rename)
        content_actions_layout.addStretch(1)
        content_layout.addLayout(content_actions_layout)

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
        return content_widget

    def _build_torrent_edit_tab(self) -> QWidget:
        """Build and return the editable torrent metadata tab."""
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
        self.spn_torrent_edit_download_limit.setToolTip(
            "Per-torrent download limit (0 = unlimited)"
        )
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
        self.txt_torrent_edit_save_path.textChanged.connect(
            self._update_torrent_edit_path_browse_buttons
        )

        self.txt_torrent_edit_incomplete_path = QLineEdit()
        incomplete_path_row = QHBoxLayout()
        incomplete_path_row.addWidget(self.txt_torrent_edit_incomplete_path)
        btn_browse_incomplete_path = QPushButton("Browse")
        btn_browse_incomplete_path.clicked.connect(self._browse_torrent_edit_incomplete_path)
        incomplete_path_row.addWidget(btn_browse_incomplete_path)
        edit_form.addRow("Incomplete Path:", incomplete_path_row)
        self.btn_torrent_edit_browse_incomplete_path = btn_browse_incomplete_path
        self.txt_torrent_edit_incomplete_path.textChanged.connect(
            self._update_torrent_edit_path_browse_buttons
        )

        edit_layout.addLayout(edit_form)

        apply_row = QHBoxLayout()
        apply_row.addStretch(1)
        self.btn_torrent_edit_apply = QPushButton("Apply")
        self.btn_torrent_edit_apply.clicked.connect(self._apply_selected_torrent_edits)
        apply_row.addWidget(self.btn_torrent_edit_apply)
        edit_layout.addLayout(apply_row)
        return edit_widget

    def _create_filter_bar(self) -> QWidget:
        """Create the filter bar above the torrents table."""
        widget = QFrame()
        widget.setFrameShape(QFrame.Shape.StyledPanel)
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
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
        self._section_status.setFlags(self._section_status.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        font = self._section_status.font(0)
        font.setBold(True)
        self._section_status.setFont(0, font)
        self.tree_filters.addTopLevelItem(self._section_status)

        for status in STATUS_FILTERS:
            item = QTreeWidgetItem([self._status_filter_item_text(status)])
            item.setData(0, Qt.ItemDataRole.UserRole, ("status", status))
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
        self._section_tag.setFlags(self._section_tag.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        font = self._section_tag.font(0)
        font.setBold(True)
        self._section_tag.setFont(0, font)
        self.tree_filters.addTopLevelItem(self._section_tag)

        # -- Size Groups section --
        self._section_size = QTreeWidgetItem(["Size Groups"])
        self._section_size.setFlags(self._section_size.flags() & ~Qt.ItemFlag.ItemIsSelectable)
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

    def _create_torrents_table(self) -> QTableWidget:
        """Create the torrents table widget."""
        table = QTableWidget()
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.itemSelectionChanged.connect(self._on_torrent_selected)
        table.itemDoubleClicked.connect(self._on_torrent_table_item_double_clicked)

        headers = [str(col.get("label", "") or "") for col in self.torrent_columns]
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
            table.setColumnWidth(idx, self._coerce_int(column.get("width", 100), 100))
            table.setColumnHidden(idx, not bool(column.get("default_visible", True)))

        # Open selected torrent local directory on Enter/Return.
        self._torrent_open_shortcuts = []
        for key_name in ("Return", "Enter"):
            shortcut = QShortcut(QKeySequence(key_name), table)
            shortcut.activated.connect(self._open_selected_torrent_location)
            self._torrent_open_shortcuts.append(shortcut)
        self._install_torrent_sort_shortcuts(table)

        return table

    def _install_torrent_sort_shortcuts(self, table: QTableWidget) -> None:
        """Install torrent-table sorting shortcuts scoped to the table widget."""
        shortcut_specs: tuple[tuple[str, str, Qt.SortOrder], ...] = (
            ("Ctrl+F1", "ratio", Qt.SortOrder.DescendingOrder),
            ("Ctrl+Alt+F1", "uploaded", Qt.SortOrder.DescendingOrder),
            ("Ctrl+F2", "progress", Qt.SortOrder.DescendingOrder),
            ("Ctrl+Alt+F2", "eta", Qt.SortOrder.AscendingOrder),
            ("Ctrl+F3", "name", Qt.SortOrder.AscendingOrder),
            ("Ctrl+Alt+F3", "state", Qt.SortOrder.AscendingOrder),
            ("Ctrl+F5", "total_size", Qt.SortOrder.DescendingOrder),
            ("Ctrl+Alt+F5", "size", Qt.SortOrder.DescendingOrder),
            ("Ctrl+F6", "added_on", Qt.SortOrder.DescendingOrder),
            ("Ctrl+Alt+F6", "completion_on", Qt.SortOrder.DescendingOrder),
        )
        self._torrent_sort_shortcuts = []
        for key_name, column_key, default_order in shortcut_specs:
            shortcut = QShortcut(QKeySequence(key_name), table)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(
                lambda ck=column_key, so=default_order: self._sort_torrents_by_column_shortcut(
                    ck, so
                )
            )
            self._torrent_sort_shortcuts.append(shortcut)

    def _sort_torrents_by_column_shortcut(
        self, column_key: str, default_order: Qt.SortOrder
    ) -> None:
        """Sort the torrent table by column key, toggling order on repeated use."""
        column_index = self.torrent_column_index.get(column_key)
        if column_index is None:
            self._log("WARNING", f"Unknown torrent sort column key: {column_key}")
            return

        header = self.tbl_torrents.horizontalHeader()
        sort_order = default_order
        if header.sortIndicatorSection() == column_index:
            sort_order = (
                Qt.SortOrder.AscendingOrder
                if header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
                else Qt.SortOrder.DescendingOrder
            )

        self.tbl_torrents.sortItems(column_index, sort_order)
        self._save_settings()

    def _create_menus(self) -> None:
        """Create menu bar."""
        menubar = self.menuBar()
        self._build_file_menu(menubar)
        self._build_edit_menu(menubar)
        self._build_view_menu(menubar)
        self._build_tools_menu(menubar)
        self._build_help_menu(menubar)

    def _build_file_menu(self, menubar: QMenuBar) -> None:
        """Create File menu."""
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

        action_new_instance_from_config = QAction("New instance from pro&file...", self)
        action_new_instance_from_config.triggered.connect(self._launch_new_instance_from_config)
        file_menu.addAction(action_new_instance_from_config)

        action_new_profile = QAction("New &profile...", self)
        action_new_profile.triggered.connect(self._create_new_profile_from_current_config)
        file_menu.addAction(action_new_profile)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcuts([QKeySequence("Ctrl+Q"), QKeySequence("Alt+X")])
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _build_edit_menu(self, menubar: QMenuBar) -> None:
        """Create Edit menu."""
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

        action_remove_delete_no_confirm = QAction("Remove and Delete Data (no confirmation)", self)
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

    def _build_view_menu(self, menubar: QMenuBar) -> None:
        """Create View menu."""
        view_menu = menubar.addMenu("&View")

        action_open_log = QAction("Open &Log File", self)
        action_open_log.triggered.connect(self._open_log_file)
        view_menu.addAction(action_open_log)

        action_refresh = QAction("&Refresh", self)
        action_refresh.setShortcut("F5")
        action_refresh.triggered.connect(self._refresh_torrents)
        view_menu.addAction(action_refresh)

        clear_cache_action = QAction("&Clear Cache && Refresh", self)
        clear_cache_action.setShortcut("Ctrl+F5")
        clear_cache_action.triggered.connect(self._clear_cache_and_refresh)
        view_menu.addAction(clear_cache_action)

        action_show_active = QAction("Show &Active Torrents", self)
        action_show_active.setShortcut("F6")
        action_show_active.triggered.connect(self._show_active_torrents_only)
        view_menu.addAction(action_show_active)

        action_show_complete = QAction("Show Com&plete Torrents", self)
        action_show_complete.setShortcut("F7")
        action_show_complete.triggered.connect(self._show_completed_torrents_only)
        view_menu.addAction(action_show_complete)

        action_show_all = QAction("Show All T&orrents", self)
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

        action_fit_columns = QAction("&Fit Columns", self)
        action_fit_columns.triggered.connect(self._fit_torrent_columns)
        view_menu.addAction(action_fit_columns)

        view_menu.addSeparator()

        self.action_auto_refresh = QAction("Enable A&uto-Refresh", self)
        self.action_auto_refresh.setCheckable(True)
        self.action_auto_refresh.setChecked(self.auto_refresh_enabled)
        self.action_auto_refresh.triggered.connect(self._toggle_auto_refresh)
        self._update_auto_refresh_action_text()
        view_menu.addAction(self.action_auto_refresh)

        action_set_refresh_interval = QAction("Set Auto-Refresh &Interval...", self)
        action_set_refresh_interval.triggered.connect(self._set_auto_refresh_interval)
        view_menu.addAction(action_set_refresh_interval)

        view_menu.addSeparator()
        action_reset_view = QAction("Reset &View", self)
        action_reset_view.triggered.connect(self._reset_view_defaults)
        view_menu.addAction(action_reset_view)

    def _build_tools_menu(self, menubar: QMenuBar) -> None:
        """Create Tools menu."""
        tools_menu = menubar.addMenu("&Tools")

        self.action_clipboard_monitor = QAction("Enable &Clipboard Monitor", self)
        self.action_clipboard_monitor.setCheckable(True)
        self.action_clipboard_monitor.setChecked(self.clipboard_monitor_enabled)
        self.action_clipboard_monitor.triggered.connect(self._toggle_clipboard_monitor)
        tools_menu.addAction(self.action_clipboard_monitor)

        self.action_debug_logging = QAction("Enable &Debug Logging", self)
        self.action_debug_logging.setCheckable(True)
        self.action_debug_logging.setChecked(self.debug_logging_enabled)
        self.action_debug_logging.triggered.connect(self._toggle_debug_logging)
        tools_menu.addAction(self.action_debug_logging)

        action_edit_ini = QAction("Edit &.ini File", self)
        action_edit_ini.triggered.connect(self._edit_settings_ini_file)
        tools_menu.addAction(action_edit_ini)

        action_edit_app_preferences = QAction("Edit &App Preferences", self)
        action_edit_app_preferences.triggered.connect(self._show_app_preferences_editor)
        tools_menu.addAction(action_edit_app_preferences)

        action_edit_add_preferences_friendly = QAction("Edit Add Preferences (&Friendly)", self)
        action_edit_add_preferences_friendly.triggered.connect(
            self._show_friendly_add_preferences_editor
        )
        tools_menu.addAction(action_edit_add_preferences_friendly)

        action_open_web_ui = QAction("&Open Web UI in Browser", self)
        action_open_web_ui.triggered.connect(self._open_web_ui_in_browser)
        tools_menu.addAction(action_open_web_ui)

        tools_menu.addSeparator()

        action_manage_speed_limits = QAction("Manage &Speed Limits...", self)
        action_manage_speed_limits.triggered.connect(self._show_speed_limits_manager)
        tools_menu.addAction(action_manage_speed_limits)

        action_manage_taxonomy = QAction("Manage &Tags and Categories", self)
        action_manage_taxonomy.triggered.connect(self._show_taxonomy_manager)
        tools_menu.addAction(action_manage_taxonomy)

        tools_menu.addSeparator()

        action_tracker_health = QAction("Tracker &Health Dashboard...", self)
        action_tracker_health.triggered.connect(self._show_tracker_health_dashboard)
        tools_menu.addAction(action_tracker_health)

        action_session_timeline = QAction("Session Time&line...", self)
        action_session_timeline.triggered.connect(self._show_session_timeline)
        tools_menu.addAction(action_session_timeline)

    def _build_help_menu(self, menubar: QMenuBar) -> None:
        """Create Help menu."""
        help_menu = menubar.addMenu("&Help")

        help_action = QAction("&Help", self)
        help_action.setShortcut("F1")
        help_action.triggered.connect(self._show_about)
        help_menu.addAction(help_action)

    def _create_statusbar(self) -> None:
        """Create status bar."""
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
        user = (
            str(
                self.qb_conn_info.get("username", self.config.get("qb_username", "admin"))
                if isinstance(self.config, dict)
                else self.qb_conn_info.get("username", "admin")
            ).strip()
            or "admin"
        )
        raw_host = (
            str(
                self.config.get("qb_host", self.qb_conn_info.get("host", "localhost"))
                if isinstance(self.config, dict)
                else self.qb_conn_info.get("host", "localhost")
            ).strip()
            or "localhost"
        )
        host = raw_host
        if "://" in raw_host:
            try:
                parsed = urlparse(raw_host)
                host = str(parsed.hostname or raw_host).strip() or "localhost"
            except ValueError:
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

    def _capture_default_view_state(self) -> None:
        """Capture baseline splitter/header states for Reset View."""
        self._default_main_splitter_state = self.main_splitter.saveState()
        self._default_right_splitter_state = self.right_splitter.saveState()
        self._default_torrent_header_state = self.tbl_torrents.horizontalHeader().saveState()

    def _apply_default_main_splitter_width(self) -> None:
        """Apply default left-panel width in pixels on current splitter geometry."""
        total_width = self.main_splitter.width()
        if total_width <= 0:
            total_width = self.width()
        if total_width <= 0:
            total_width = DEFAULT_WINDOW_WIDTH

        left_width = min(max(1, int(DEFAULT_LEFT_PANEL_WIDTH)), max(1, total_width - 1))
        right_width = max(1, total_width - left_width)
        self.main_splitter.setSizes([left_width, right_width])

    def _apply_default_torrent_header_layout(self) -> None:
        """Apply default torrent-table column order/widths/sort indicator."""
        header = self.tbl_torrents.horizontalHeader()

        # Restore natural logical->visual order.
        for logical in range(self.tbl_torrents.columnCount()):
            visual = header.visualIndex(logical)
            if visual != logical:
                header.moveSection(visual, logical)

        for idx, column in enumerate(self.torrent_columns):
            self.tbl_torrents.setColumnWidth(idx, self._coerce_int(column.get("width", 100), 100))
            self.tbl_torrents.setColumnHidden(idx, not bool(column.get("default_visible", True)))
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self._sync_torrent_column_actions()

    def _restore_default_view_state(self) -> None:
        """Restore baseline splitter/header states for Reset View."""
        try:
            self._apply_default_main_splitter_width()
        except (RuntimeError, TypeError, ValueError):
            self.main_splitter.setSizes([DEFAULT_LEFT_PANEL_WIDTH, 1000])

        try:
            if getattr(self, "_default_right_splitter_state", None):
                self.right_splitter.restoreState(self._default_right_splitter_state)
            else:
                self.right_splitter.setSizes([600, 200])
        except (RuntimeError, TypeError, ValueError):
            self.right_splitter.setSizes([600, 200])

        try:
            if getattr(self, "_default_torrent_header_state", None):
                self.tbl_torrents.horizontalHeader().restoreState(
                    self._default_torrent_header_state
                )
            else:
                self._apply_default_torrent_header_layout()
        except (RuntimeError, TypeError, ValueError):
            # Fall back to explicit defaults.
            self._apply_default_torrent_header_layout()
        self._sync_torrent_column_actions()

    @staticmethod
    def _to_bool(value: object, default: bool = False) -> bool:
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
        return build_instance_app_name(G_APP_NAME, self.instance_id)

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

    def _save_refresh_settings(self) -> None:
        """Persist only auto-refresh runtime settings."""
        settings = self._new_settings()
        settings.setValue("autoRefreshEnabled", bool(self.auto_refresh_enabled))
        settings.setValue(
            "refreshIntervalSec",
            int(self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL)),
        )

    def _setup_clipboard_monitor(self) -> None:
        """Attach clipboard change listener for optional auto-add behavior."""
        try:
            self._clipboard = QApplication.clipboard()
            if self._clipboard:
                self._clipboard.dataChanged.connect(self._on_clipboard_changed)
        except (RuntimeError, AttributeError) as e:
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
        match = re.search(r"\b([A-Fa-f0-9]{40}|[A-Fa-f0-9]{64}|[A-Za-z2-7]{32})\b", text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _magnet_from_hash(torrent_hash: str) -> str:
        """Build magnet URI from torrent infohash."""
        normalized = str(torrent_hash or "").strip().lower()
        return f"magnet:?xt=urn:btih:{normalized}"

    def _remember_clipboard_key(self, key: str) -> None:
        """Remember processed clipboard key and evict oldest entries."""
        if not key or key in self._clipboard_seen_keys:
            return
        self._clipboard_seen_keys.add(key)
        self._clipboard_seen_order.append(key)
        while len(self._clipboard_seen_order) > CLIPBOARD_SEEN_LIMIT:
            evicted = self._clipboard_seen_order.popleft()
            self._clipboard_seen_keys.discard(evicted)

    def _queue_add_torrent_from_clipboard(self, magnet_url: str, source: str) -> None:
        """Queue add-torrent task for clipboard-derived magnet url."""
        self._log("INFO", f"Clipboard monitor detected {source}; adding torrent")
        self._set_status("Clipboard monitor: adding torrent...")
        self.api_queue.add_task(
            "add_torrent_from_clipboard",
            self._add_torrent_api,
            self._on_add_torrent_complete,
            {"urls": [magnet_url]},
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
                self._magnet_from_hash(normalized), "torrent hash"
            )
            return True

        return False

    def _on_clipboard_changed(self) -> None:
        """Clipboard signal handler used by monitor toggle."""
        if not self.clipboard_monitor_enabled or not self._clipboard:
            return
        try:
            text = (self._clipboard.text() or "").strip()
        except (RuntimeError, AttributeError, TypeError):
            return
        if not text or text == self._last_clipboard_text:
            return
        self._last_clipboard_text = text
        self._process_clipboard_text(text)

    def _toggle_clipboard_monitor(self, enabled: bool) -> None:
        """Enable or disable clipboard monitor."""
        self.clipboard_monitor_enabled = bool(enabled)
        self._save_settings()
        state = "enabled" if self.clipboard_monitor_enabled else "disabled"
        self._log("INFO", f"Clipboard monitor {state}")
        self._set_status(f"Clipboard monitor {state}")
        if self.clipboard_monitor_enabled:
            self._on_clipboard_changed()

    def _edit_settings_ini_file(self) -> None:
        """Open QSettings INI file in system default editor."""
        try:
            ini_path = self._settings_ini_path()
            ini_path.parent.mkdir(parents=True, exist_ok=True)
            if not ini_path.exists():
                ini_path.touch()
            if not open_path_in_default_app(str(ini_path)):
                raise RuntimeError(f"Failed to open path: {ini_path}")
            self._log("INFO", f"Opened settings INI file: {ini_path}")
            self._set_status(f"Opened INI: {ini_path}")
        except (OSError, RuntimeError, ValueError) as e:
            self._log("ERROR", f"Failed to open settings INI file: {e}")
            self._set_status(f"Failed to open INI file: {e}")

    def _web_ui_browser_url(self) -> str:
        """Build Web UI URL for the current qBittorrent connection."""
        user = (
            str(
                self.qb_conn_info.get("username", self.config.get("qb_username", "admin"))
                if isinstance(self.config, dict)
                else self.qb_conn_info.get("username", "admin")
            ).strip()
            or "admin"
        )
        configured_scheme = _normalize_http_protocol_scheme(
            self.config.get("http_protocol_scheme", "http")
            if isinstance(self.config, dict)
            else "http"
        )
        explicit_scheme_override = bool(
            isinstance(self.config, dict)
            and str(self.config.get("http_protocol_scheme", "") or "").strip()
        )
        raw_host = (
            str(
                self.config.get("qb_host", self.qb_conn_info.get("host", "localhost"))
                if isinstance(self.config, dict)
                else self.qb_conn_info.get("host", "localhost")
            ).strip()
            or "localhost"
        )
        host = raw_host
        scheme = configured_scheme
        host_port_from_url: int | None = None
        if "://" in raw_host:
            try:
                parsed = urlparse(raw_host)
                host = str(parsed.hostname or raw_host).strip() or "localhost"
                parsed_scheme = _normalize_http_protocol_scheme(parsed.scheme or "http")
                scheme = configured_scheme if explicit_scheme_override else parsed_scheme
                host_port_from_url = parsed.port
            except ValueError:
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

    def _open_web_ui_in_browser(self) -> None:
        """Open qBittorrent Web UI URL in default browser."""
        try:
            url = self._web_ui_browser_url()
            if not open_path_in_default_app(url):
                raise RuntimeError(f"Failed to open path: {url}")
            self._log("INFO", f"Opened qBittorrent Web UI: {url}")
            self._set_status(f"Opened Web UI: {url}")
        except (OSError, RuntimeError, ValueError) as e:
            self._log("ERROR", f"Failed to open qBittorrent Web UI: {e}")
            self._set_status(f"Failed to open Web UI: {e}")

    def _load_settings(self) -> None:
        """Load window geometry, splitter sizes, column widths, sort order,."""
        settings = self._new_settings()
        self._load_window_geometry_settings(settings)
        self._load_splitter_settings(settings)
        self._load_torrent_table_settings(settings)
        self._load_filter_selection_settings(settings)
        self._load_auto_refresh_settings(settings)
        self._load_display_mode_settings(settings)
        self._load_clipboard_monitor_settings(settings)
        self._load_debug_logging_settings(settings)

    def _load_window_geometry_settings(self, settings: QSettings) -> None:
        """Load and apply persisted window geometry/state."""
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

    def _load_splitter_settings(self, settings: QSettings) -> None:
        """Load and apply persisted splitter positions."""
        main_sizes = settings.value("mainSplitter")
        if main_sizes:
            self.main_splitter.restoreState(main_sizes)
        else:
            self._apply_default_main_splitter_width()
        right_sizes = settings.value("rightSplitter")
        if right_sizes:
            self.right_splitter.restoreState(right_sizes)

    def _load_torrent_table_settings(self, settings: QSettings) -> None:
        """Load persisted torrent table header and hidden column selection."""
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
                col["key"] for col in self.torrent_columns if col["key"] not in medium_keys
            ]
            self._apply_hidden_columns_by_keys(hidden_default)

    def _load_filter_selection_settings(self, settings: QSettings) -> None:
        """Load persisted filter tree status selection."""
        status = settings.value("filterStatus")
        if status and status in STATUS_FILTERS:
            self.current_status_filter = status
        self._refresh_filter_tree_highlights()

    def _load_auto_refresh_settings(self, settings: QSettings) -> None:
        """Load persisted auto-refresh toggle and interval settings."""
        self.auto_refresh_enabled = self._to_bool(
            settings.value("autoRefreshEnabled"), self.auto_refresh_enabled
        )
        loaded_interval = self._safe_int(
            settings.value("refreshIntervalSec"), self.refresh_interval
        )
        self.refresh_interval = max(1, loaded_interval)
        if hasattr(self, "action_auto_refresh"):
            self.action_auto_refresh.setChecked(self.auto_refresh_enabled)
            self._update_auto_refresh_action_text()
        self._sync_auto_refresh_timer_state()

    def _load_display_mode_settings(self, settings: QSettings) -> None:
        """Load persisted size/speed display mode settings."""
        display_human = settings.value("displayHumanReadable")
        if display_human is not None:
            use_human = self._to_bool(display_human, True)
            mode = "human_readable" if use_human else "bytes"
            self.display_size_mode = mode
            self.display_speed_mode = mode
        else:
            # Backward compatibility for older persisted keys.
            self.display_size_mode = _normalize_display_mode(
                settings.value("displaySizeMode", self.display_size_mode), DEFAULT_DISPLAY_SIZE_MODE
            )
            self.display_speed_mode = _normalize_display_mode(
                settings.value("displaySpeedMode", self.display_speed_mode),
                DEFAULT_DISPLAY_SPEED_MODE,
            )
        if hasattr(self, "action_human_readable"):
            hr_checked = (
                self.display_size_mode == "human_readable"
                and self.display_speed_mode == "human_readable"
            )
            action_signals = self.action_human_readable.blockSignals(True)
            self.action_human_readable.setChecked(hr_checked)
            self.action_human_readable.blockSignals(action_signals)

    def _load_clipboard_monitor_settings(self, settings: QSettings) -> None:
        """Load clipboard monitor enablement and trigger initial poll."""
        self.clipboard_monitor_enabled = self._to_bool(
            settings.value("clipboardMonitorEnabled"), self.clipboard_monitor_enabled
        )
        if hasattr(self, "action_clipboard_monitor"):
            self.action_clipboard_monitor.setChecked(self.clipboard_monitor_enabled)
        if self.clipboard_monitor_enabled:
            QTimer.singleShot(0, self._on_clipboard_changed)

    def _load_debug_logging_settings(self, settings: QSettings) -> None:
        """Load debug logging toggle state."""
        self.debug_logging_enabled = self._to_bool(
            settings.value("debugLoggingEnabled"),
            self.debug_logging_enabled,
        )
        if hasattr(self, "action_debug_logging"):
            self.action_debug_logging.setChecked(self.debug_logging_enabled)

    def _save_settings(self) -> None:
        """Save window geometry, splitter sizes, column widths, sort order,."""
        settings = self._new_settings()

        # Window geometry
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())

        # Splitter sizes
        settings.setValue("mainSplitter", self.main_splitter.saveState())
        settings.setValue("rightSplitter", self.right_splitter.saveState())

        # Torrent table header (column widths, order, sort)
        settings.setValue("torrentTableHeader", self.tbl_torrents.horizontalHeader().saveState())
        hidden_columns = [
            col["key"]
            for idx, col in enumerate(self.torrent_columns)
            if self.tbl_torrents.isColumnHidden(idx)
        ]
        settings.setValue("torrentTableHiddenColumns", hidden_columns)

        # Filter selection
        settings.setValue("filterStatus", self.current_status_filter)
        settings.setValue("autoRefreshEnabled", bool(self.auto_refresh_enabled))
        settings.setValue(
            "refreshIntervalSec",
            int(self._safe_int(self.refresh_interval, DEFAULT_REFRESH_INTERVAL)),
        )
        settings.setValue(
            "displayHumanReadable",
            bool(
                self.display_size_mode == "human_readable"
                and self.display_speed_mode == "human_readable"
            ),
        )
        settings.setValue("displaySizeMode", self.display_size_mode)
        settings.setValue("displaySpeedMode", self.display_speed_mode)
        settings.setValue("clipboardMonitorEnabled", bool(self.clipboard_monitor_enabled))
        settings.setValue("debugLoggingEnabled", bool(self.debug_logging_enabled))

    def _initial_load(self) -> None:
        """Initial data load on startup."""
        try:
            self._log("INFO", "Starting initial data load...")
            self._log(
                "INFO",
                f"Connecting to qBittorrent at {self.qb_conn_info['host']}:{self.qb_conn_info['port']}",
            )
            self._show_progress("Loading categories...")

            # Load categories first
            self.api_queue.add_task(
                "load_categories", self._fetch_categories, self._on_categories_loaded
            )
        except (KeyError, TypeError, RuntimeError, AttributeError) as e:
            self._log("ERROR", f"Failed to start initial load: {e}")
            self._hide_progress()
            self._set_status(f"Error: {e}")


def main() -> None:
    """Main application entry point."""

    def _positive_instance_counter(value: str) -> int:
        """Validate CLI instance counter argument as positive integer."""
        try:
            parsed = int(value)
        except (TypeError, ValueError) as e:
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
        "-p",
        "--profile",
        required=False,
        default=DEFAULT_PROFILE_ID,
        help="Runtime profile id (default: default)",
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
    parser.add_argument(
        "--config-dir",
        dest="config_dir",
        required=False,
        default=None,
        help="Override QSettings INI root directory (takes precedence over CONFIG_DIR).",
    )
    parser.add_argument(
        "--data-dir",
        dest="data_dir",
        required=False,
        default=None,
        help="Override runtime data root directory (takes precedence over DATA_DIR).",
    )

    args = parser.parse_args()
    if args.config_dir:
        os.environ["CONFIG_DIR"] = str(Path(args.config_dir).expanduser())
    if args.data_dir:
        os.environ["DATA_DIR"] = str(Path(args.data_dir).expanduser())
    configure_qsettings(APP_IDENTITY)
    selected_profile = normalize_profile_id(args.profile)

    try:
        app = QApplication(sys.argv)
        app.setOrganizationName(G_ORG_NAME)
        app.setApplicationName(G_APP_NAME)
        app.setApplicationDisplayName("qBiremo Enhanced")
        if hasattr(app, "setWindowIcon"):
            app_icon = load_app_icon()
            if not app_icon.isNull():
                app.setWindowIcon(app_icon)

        # Load profile config (collect load-time issues before logging is configured)
        config, load_issues = load_config_with_issues(selected_profile)
        config["_profile_id"] = selected_profile
        missing = get_missing_required_config(config)
        if missing:
            wizard_result = run_profile_setup_wizard(selected_profile, dict(config))
            if wizard_result is None:
                print("Profile setup wizard was cancelled; required config is missing.")
                raise SystemExit(1)
            selected_profile, payload = wizard_result
            save_profile_config(selected_profile, payload)
            config, reload_issues = load_config_with_issues(selected_profile)
            config["_profile_id"] = selected_profile
            load_issues.extend(reload_issues)

        requested_counter = int(args.instance_counter)
        config["_instance_counter"] = requested_counter
        claimed_counter, claimed_instance_id, lock_path = acquire_instance_lock(
            APP_IDENTITY,
            config,
            requested_counter,
        )
        config["_instance_counter"] = int(claimed_counter)
        config["_instance_id"] = str(claimed_instance_id)
        config["_instance_lock_file_path"] = str(lock_path)
        if claimed_counter != requested_counter:
            load_issues.append(
                "Lock file already exists; auto-incremented instance counter "
                f"from {requested_counter} to {claimed_counter} "
                f"({claimed_instance_id})."
            )
        atexit.register(release_instance_lock, lock_path)

        # Set up logging first, then install the global exception hook.
        file_handler = _setup_logging(config)
        _install_exception_hooks(file_handler)
        for issue in load_issues:
            logger.warning("%s", issue)

        # Validate and normalize config values now that file logging is active.
        config = validate_and_normalize_config(config, selected_profile)
        config["_profile_id"] = selected_profile
        config["_instance_counter"] = int(claimed_counter)
        config["_instance_id"] = str(claimed_instance_id)
        config["_instance_lock_file_path"] = str(lock_path)

        main_window = MainWindow(config)
        cast("Any", app).main_window = main_window

        sys.exit(app.exec())
    except SystemExit:
        raise
    except Exception:
        logger.critical("Fatal error during startup", exc_info=True)
        if "file_handler" in locals():
            file_handler.flush()
        open_path_in_default_app(
            config.get(
                "_log_file_path",
                _default_instance_log_file_path(str(config.get("_instance_id", "") or "")),
            )
        )
        raise
