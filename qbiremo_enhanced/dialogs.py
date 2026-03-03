
"""Dialog and small widget classes."""

import copy
import html
import os
from typing import Dict, List, Optional, Tuple, Union

from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
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
    QDoubleSpinBox,
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
    QFormLayout,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPaintEvent,
    QPainter,
    QPen,
    QShortcut,
)

from .models.torrent import SessionTimelineSample, TrackerHealthRow
from .utils import format_size_mode, format_speed_mode

class AddTorrentDialog(QDialog):
    """Dialog for adding a new torrent"""

    def __init__(
        self,
        categories: List[str],
        tags: List[str],
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize add-torrent dialog with source and behavior editors."""
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

    def accept(self) -> None:
        """Validate and cache torrent payload before closing the dialog.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        payload = self.get_torrent_data()
        if not payload:
            return
        self.torrent_data = payload
        super().accept()

    def _browse_files(self) -> None:
        """Browse and append one or more torrent files.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Torrent Files", "", "Torrent Files (*.torrent);;All Files (*)"
        )
        if file_paths:
            self._append_multiline_entries(self.txt_torrent_files, file_paths)

    def _browse_save_path(self) -> None:
        """Browse for save directory.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        dir_path = QFileDialog.getExistingDirectory(self, "Select Save Directory")
        if dir_path:
            self.txt_save_path.setText(dir_path)

    def _browse_download_path(self) -> None:
        """Browse for download directory.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        dir_path = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if dir_path:
            self.txt_download_path.setText(dir_path)

    @staticmethod
    def _split_csv(text: str) -> List[str]:
        """Split comma-separated text into trimmed non-empty entries.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        return [p.strip() for p in (text or "").split(",") if p.strip()]

    @staticmethod
    def _split_multiline(text: str) -> List[str]:
        """Split multiline text into trimmed non-empty lines.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        return [line.strip() for line in str(text or "").splitlines() if line.strip()]

    def _append_multiline_entries(self, editor: QTextEdit, entries: List[str]) -> None:
        """Append unique lines to one multiline editor while preserving order.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        existing = self._split_multiline(editor.toPlainText())
        combined = existing + [str(entry).strip() for entry in (entries or []) if str(entry).strip()]
        # Preserve order while removing duplicates.
        deduped = list(dict.fromkeys(combined))
        editor.setPlainText("\n".join(deduped))

    def _get_selected_tags(self) -> str:
        """Return comma-separated string of checked tags.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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
        """Return True when one source entry is a supported URL/magnet.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        lower = source.lower()
        return lower.startswith("magnet:") or lower.startswith("http://") or lower.startswith("https://") or lower.startswith("bc://")

    @staticmethod
    def _parse_url_sources(lines: List[str]) -> Union[str, List[str]]:
        """Convert URL list to qBittorrent payload format (single item or list).

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        # Accept one URL per line for convenience.
        if not lines:
            return ""
        if len(lines) == 1:
            return lines[0]
        return lines

    def get_torrent_data(self) -> Optional[Dict[str, object]]:
        """Get the torrent data from the dialog.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        source_files = self._split_multiline(self.txt_torrent_files.toPlainText())
        source_urls = self._split_multiline(self.txt_source_urls.toPlainText())
        if not source_files and not source_urls:
            return None

        data: Dict[str, object] = {}

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

class TaxonomyManagerDialog(QDialog):
    """Dialog to manage categories and tags in one place."""

    create_category_requested = Signal(str, str, str, bool)
    edit_category_requested = Signal(str, str, str, bool)
    delete_category_requested = Signal(str)
    create_tags_requested = Signal(list)
    delete_tags_requested = Signal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize category and tag management dialog state."""
        super().__init__(parent)
        self.setWindowTitle("Manage Tags and Categories")
        self.resize(760, 520)

        self._category_data: Dict[str, Dict[str, object]] = {}
        self._build_ui()
        self._set_category_create_mode()

    def _build_ui(self) -> None:
        """Create categories/tags tabs and wire user actions.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

    def _browse_category_save_path(self) -> None:
        """Browse for category default save path.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        initial = self.txt_category_save_path.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self, "Select Category Save Path", initial
        )
        if selected:
            self.txt_category_save_path.setText(selected)

    def _browse_category_incomplete_path(self) -> None:
        """Browse for category incomplete save path.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        initial = self.txt_category_incomplete_path.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self, "Select Category Incomplete Path", initial
        )
        if selected:
            self.txt_category_incomplete_path.setText(selected)

    def _update_incomplete_path_enabled_state(self, *_args: object) -> None:
        """Enable/disable incomplete path controls based on checkbox.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        enabled = bool(self.chk_category_use_incomplete.isChecked())
        self.txt_category_incomplete_path.setEnabled(enabled)
        self.btn_category_browse_incomplete.setEnabled(enabled)

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Enable/disable editor controls while an API operation runs.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

    def set_taxonomy_data(self, category_data: Dict[str, Dict[str, object]], tags: List[str]) -> None:
        """Refresh dialog contents from latest category/tag lists.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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
        """Return selected category name, or empty string.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        item = self.lst_categories.currentItem()
        return item.text().strip() if item else ""

    def _on_category_selection_changed(
        self,
        current: Optional[QListWidgetItem],
        _previous: Optional[QListWidgetItem],
    ) -> None:
        """Load selected category into the editor.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

    def _set_category_create_mode(self) -> None:
        """Prepare editor for creating a new category.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

    def _apply_category_changes(self) -> None:
        """Emit create/update category request.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

    def _delete_selected_category(self) -> None:
        """Emit delete request for selected category.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        name = self.selected_category_name()
        if not name:
            self.lbl_message.setText("Select a category to delete.")
            return
        self.delete_category_requested.emit(name)

    @staticmethod
    def _parse_csv_entries(raw_text: str) -> List[str]:
        """Parse comma-separated text into unique ordered tag values.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        values: List[str] = []
        seen = set()
        for part in str(raw_text or "").split(","):
            value = part.strip()
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        return values

    def _add_tags(self) -> None:
        """Emit create-tags request from entry field.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        tags = self._parse_csv_entries(self.txt_new_tags.text())
        if not tags:
            self.lbl_message.setText("Enter at least one tag.")
            return
        self.create_tags_requested.emit(tags)
        self.txt_new_tags.clear()

    def _delete_selected_tags(self) -> None:
        """Emit delete-tags request for selected tags.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        tags = [item.text().strip() for item in self.lst_tags_manage.selectedItems() if item.text().strip()]
        if not tags:
            self.lbl_message.setText("Select at least one tag to delete.")
            return
        self.delete_tags_requested.emit(tags)

class SpeedLimitsDialog(QDialog):
    """Dialog to manage global and alternative speed limits."""

    refresh_requested = Signal()
    apply_requested = Signal(int, int, int, int, bool)  # normal_dl_kib, normal_ul_kib, alt_dl_kib, alt_ul_kib, alt_enabled

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize speed-limits dialog controls."""
        super().__init__(parent)
        self.setWindowTitle("Manage Speed Limits")
        self.resize(520, 320)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build normal/alternative speed controls and command buttons.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

    def _emit_apply(self) -> None:
        """Emit apply signal with current dialog values.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        self.apply_requested.emit(
            int(self.spn_normal_dl.value()),
            int(self.spn_normal_ul.value()),
            int(self.spn_alt_dl.value()),
            int(self.spn_alt_ul.value()),
            bool(self.chk_alt_enabled.isChecked()),
        )

    def set_values(self, normal_dl_bytes: int, normal_ul_bytes: int,
                   alt_dl_bytes: int, alt_ul_bytes: int, alt_enabled: bool) -> None:
        """Update dialog controls from bytes/sec values.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        self.spn_normal_dl.setValue(max(0, int(normal_dl_bytes)) // 1024)
        self.spn_normal_ul.setValue(max(0, int(normal_ul_bytes)) // 1024)
        self.spn_alt_dl.setValue(max(0, int(alt_dl_bytes)) // 1024)
        self.spn_alt_ul.setValue(max(0, int(alt_ul_bytes)) // 1024)
        self.chk_alt_enabled.setChecked(bool(alt_enabled))

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Enable/disable controls while async operation runs.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

class AppPreferencesDialog(QDialog):
    """Dialog to edit raw qBittorrent application preferences in a tree view."""

    apply_requested = Signal(dict)

    ROLE_PATH = int(Qt.ItemDataRole.UserRole) + 200
    ROLE_IS_LEAF = int(Qt.ItemDataRole.UserRole) + 201

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize raw preferences editor state and tree bindings."""
        super().__init__(parent)
        self.setWindowTitle("Edit App Preferences")
        self.resize(980, 640)
        self._updating_tree = False
        self._original_preferences: Dict[str, object] = {}
        self._edited_preferences: Dict[str, object] = {}
        self._path_items: Dict[Tuple[object, ...], QTreeWidgetItem] = {}
        self._leaf_original_values: Dict[Tuple[object, ...], object] = {}
        self._leaf_current_values: Dict[Tuple[object, ...], object] = {}
        self._leaf_items: Dict[Tuple[object, ...], QTreeWidgetItem] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        """Build preferences tree view and apply/cancel actions.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

        controls = QHBoxLayout()
        self.btn_apply = QPushButton("Apply")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_apply.clicked.connect(self._emit_apply)
        self.btn_cancel.clicked.connect(self.reject)
        controls.addStretch(1)
        controls.addWidget(self.btn_apply)
        controls.addWidget(self.btn_cancel)
        layout.addLayout(controls)

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Enable/disable dialog controls while API operation runs.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        enabled = not bool(busy)
        self.tree_preferences.setEnabled(enabled)
        self.btn_apply.setEnabled(enabled)
        self.lbl_message.setText(str(message or ""))

    def set_preferences(self, preferences: Dict[str, object]) -> None:
        """Load preferences into editable tree and reset change tracking.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
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
    def _is_container(value: object) -> bool:
        """Return True when value is a nested dict/list container.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        return isinstance(value, (dict, list))

    @staticmethod
    def _value_type_name(value: object) -> str:
        """Return a human-readable type name for one preference value.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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
    def _value_to_text(value: object) -> str:
        """Render one preference value to editable text representation.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
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
    def _container_summary(value: object) -> str:
        """Return compact summary label for dict/list containers.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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
        path: Tuple[object, ...],
        label: str,
        value: object,
    ) -> None:
        """Add one preference tree node and recurse for nested values.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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
    def _normalize_item_path(path_data: object) -> Tuple[object, ...]:
        """Normalize serialized path metadata to tuple form.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        if isinstance(path_data, tuple):
            return path_data
        if isinstance(path_data, list):
            return tuple(path_data)
        return tuple()

    @staticmethod
    def _path_label(path: Tuple[object, ...]) -> str:
        """Format one tree path tuple as dotted/bracketed label.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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
    def _set_path_value(container: object, path: Tuple[object, ...], value: object) -> None:
        """Assign one nested container value addressed by path tuple.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        target = container
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    @staticmethod
    def _get_path_value(container: object, path: Tuple[object, ...]) -> object:
        """Resolve one nested container value addressed by path tuple.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        target = container
        for key in path:
            target = target[key]
        return target

    @staticmethod
    def _parse_bool(text: str) -> bool:
        """Parse flexible bool text tokens and raise on invalid input.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: Raises validation/runtime exceptions for invalid inputs or unsupported states.
        """
        token = str(text or "").strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
        raise ValueError("expected boolean (true/false)")

    @staticmethod
    def _parse_value_by_example(text: str, example: object) -> object:
        """Parse editor text using original value type as parsing guide.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
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

    def _refresh_changed_highlights(self) -> None:
        """Highlight changed leaf values in coral for quick scanning.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        coral_brush = QBrush(QColor("coral"))
        clear_brush = QBrush()
        for path, item in self._leaf_items.items():
            original = self._leaf_original_values.get(path)
            current = self._leaf_current_values.get(path)
            changed = current != original
            item.setBackground(1, coral_brush if changed else clear_brush)

    def changed_preferences(self) -> Dict[str, object]:
        """Return only top-level preferences changed by the user.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        changes: Dict[str, object] = {}
        for key, edited_value in self._edited_preferences.items():
            original_value = self._original_preferences.get(key, None)
            if key not in self._original_preferences or edited_value != original_value:
                changes[str(key)] = copy.deepcopy(edited_value)
        return changes

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """Validate one edited cell and propagate value/type updates upward.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
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

    def _emit_apply(self) -> None:
        """Emit only changed preferences for API apply.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        changes = self.changed_preferences()
        if not changes:
            self.lbl_message.setText("No changed preferences to apply.")
            return
        self.apply_requested.emit(changes)

class FriendlyAddPreferencesDialog(QDialog):
    """Dialog to edit common qBittorrent app preferences without raw JSON editing."""

    apply_requested = Signal(dict)

    FRIENDLY_PREF_KEYS = (
        "save_path",
        "temp_path_enabled",
        "temp_path",
        "start_paused_enabled",
        "create_subfolder_enabled",
        "auto_tmm_enabled",
        "incomplete_files_ext",
        "preallocate_all",
        "queueing_enabled",
        "max_active_downloads",
        "max_active_uploads",
        "max_active_torrents",
        "max_connec",
        "max_connec_per_torrent",
        "max_uploads",
        "max_uploads_per_torrent",
        "dht",
        "pex",
        "lsd",
        "upnp",
        "anonymous_mode",
        "encryption",
        "max_ratio_enabled",
        "max_ratio",
        "max_seeding_time_enabled",
        "max_seeding_time",
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize friendly preference editor controls and state."""
        super().__init__(parent)
        self.setWindowTitle("Edit Add Preferences (friendly)")
        self.resize(640, 560)
        self._original_values: Dict[str, object] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        """Build tabbed friendly controls for common preference subsets.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        layout = QVBoxLayout(self)

        self.lbl_summary = QLabel(
            "Friendly editor for common settings. For advanced keys, use Edit App Preferences."
        )
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        tab_downloads = QWidget()
        downloads_form = QFormLayout(tab_downloads)
        self.txt_save_path = QLineEdit()
        self.chk_temp_path_enabled = QCheckBox("Use temporary/incomplete path")
        self.chk_temp_path_enabled.toggled.connect(self._update_temp_path_enabled_state)
        self.txt_temp_path = QLineEdit()
        self.chk_start_paused = QCheckBox("Start new torrents paused")
        self.chk_create_subfolder = QCheckBox("Create subfolder for torrents with multiple files")
        self.chk_auto_tmm = QCheckBox("Enable automatic torrent management")
        self.chk_incomplete_ext = QCheckBox("Append .!qB extension to incomplete files")
        self.chk_preallocate = QCheckBox("Pre-allocate all disk space")
        downloads_form.addRow("Default save path:", self.txt_save_path)
        downloads_form.addRow("", self.chk_temp_path_enabled)
        downloads_form.addRow("Temporary path:", self.txt_temp_path)
        downloads_form.addRow("", self.chk_start_paused)
        downloads_form.addRow("", self.chk_create_subfolder)
        downloads_form.addRow("", self.chk_auto_tmm)
        downloads_form.addRow("", self.chk_incomplete_ext)
        downloads_form.addRow("", self.chk_preallocate)
        self.tabs.addTab(tab_downloads, "Downloads")

        tab_queueing = QWidget()
        queue_form = QFormLayout(tab_queueing)
        self.chk_queueing_enabled = QCheckBox("Enable queueing")
        self.spn_max_active_downloads = self._make_unlimited_spinbox()
        self.spn_max_active_uploads = self._make_unlimited_spinbox()
        self.spn_max_active_torrents = self._make_unlimited_spinbox()
        self.spn_max_connec = self._make_unlimited_spinbox()
        self.spn_max_connec_per_torrent = self._make_unlimited_spinbox()
        self.spn_max_uploads = self._make_unlimited_spinbox()
        self.spn_max_uploads_per_torrent = self._make_unlimited_spinbox()
        queue_form.addRow("", self.chk_queueing_enabled)
        queue_form.addRow("Max active downloads:", self.spn_max_active_downloads)
        queue_form.addRow("Max active uploads:", self.spn_max_active_uploads)
        queue_form.addRow("Max active torrents:", self.spn_max_active_torrents)
        queue_form.addRow("Global maximum connections:", self.spn_max_connec)
        queue_form.addRow("Maximum connections per torrent:", self.spn_max_connec_per_torrent)
        queue_form.addRow("Global upload slots:", self.spn_max_uploads)
        queue_form.addRow("Upload slots per torrent:", self.spn_max_uploads_per_torrent)
        self.tabs.addTab(tab_queueing, "Queueing")

        tab_network = QWidget()
        network_form = QFormLayout(tab_network)
        self.chk_dht = QCheckBox("Enable DHT")
        self.chk_pex = QCheckBox("Enable Peer Exchange (PeX)")
        self.chk_lsd = QCheckBox("Enable Local Peer Discovery (LSD)")
        self.chk_upnp = QCheckBox("Use UPnP / NAT-PMP to forward the listening port")
        self.chk_anonymous_mode = QCheckBox("Enable anonymous mode")
        self.cmb_encryption = QComboBox()
        self.cmb_encryption.addItem("Prefer encryption", 0)
        self.cmb_encryption.addItem("Require encryption", 1)
        self.cmb_encryption.addItem("Disable encryption", 2)
        network_form.addRow("", self.chk_dht)
        network_form.addRow("", self.chk_pex)
        network_form.addRow("", self.chk_lsd)
        network_form.addRow("", self.chk_upnp)
        network_form.addRow("", self.chk_anonymous_mode)
        network_form.addRow("Encryption mode:", self.cmb_encryption)
        self.tabs.addTab(tab_network, "Network")

        tab_share_limits = QWidget()
        share_form = QFormLayout(tab_share_limits)
        self.chk_max_ratio_enabled = QCheckBox("Enable default ratio limit")
        self.chk_max_ratio_enabled.toggled.connect(self._update_ratio_enabled_state)
        self.spn_max_ratio = QDoubleSpinBox()
        self.spn_max_ratio.setDecimals(2)
        self.spn_max_ratio.setRange(0.0, 10_000.0)
        self.spn_max_ratio.setSingleStep(0.05)
        self.chk_max_seeding_time_enabled = QCheckBox("Enable default seeding time limit")
        self.chk_max_seeding_time_enabled.toggled.connect(self._update_seeding_time_enabled_state)
        self.spn_max_seeding_time = QSpinBox()
        self.spn_max_seeding_time.setRange(0, 10_000_000)
        self.spn_max_seeding_time.setSingleStep(10)
        share_form.addRow("", self.chk_max_ratio_enabled)
        share_form.addRow("Default ratio limit:", self.spn_max_ratio)
        share_form.addRow("", self.chk_max_seeding_time_enabled)
        share_form.addRow("Default seeding time limit (minutes):", self.spn_max_seeding_time)
        self.tabs.addTab(tab_share_limits, "Seeding Limits")

        self.lbl_message = QLabel("No preferences loaded.")
        layout.addWidget(self.lbl_message)

        controls = QHBoxLayout()
        self.btn_apply = QPushButton("Apply")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_apply.clicked.connect(self._emit_apply)
        self.btn_cancel.clicked.connect(self.reject)
        controls.addStretch(1)
        controls.addWidget(self.btn_apply)
        controls.addWidget(self.btn_cancel)
        layout.addLayout(controls)

        self._update_temp_path_enabled_state()
        self._update_ratio_enabled_state()
        self._update_seeding_time_enabled_state()

    @staticmethod
    def _make_unlimited_spinbox() -> QSpinBox:
        """Create integer spinbox using `-1` sentinel for unlimited values.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        spin = QSpinBox()
        spin.setRange(-1, 10_000_000)
        spin.setSingleStep(1)
        spin.setSpecialValueText("Unlimited (-1)")
        return spin

    @staticmethod
    def _to_bool(value: object, default: bool = False) -> bool:
        """Best-effort conversion of unknown value to bool with default.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            token = value.strip().lower()
            if token in {"1", "true", "yes", "on"}:
                return True
            if token in {"0", "false", "no", "off"}:
                return False
        return bool(default)

    @staticmethod
    def _to_int(value: object, default: int = -1) -> int:
        """Best-effort conversion of unknown value to int with default.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        if isinstance(value, bool):
            return int(default)
        try:
            return int(value)
        except Exception:
            return int(default)

    @staticmethod
    def _to_float(value: object, default: float = 0.0) -> float:
        """Best-effort conversion of unknown value to float with default.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
        """
        if isinstance(value, bool):
            return float(default)
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object, fallback: int = 0) -> None:
        """Select combo item by `data` value with robust fallback behavior.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        desired = FriendlyAddPreferencesDialog._to_int(value, fallback)
        idx = combo.findData(desired)
        if idx < 0:
            idx = combo.findData(int(fallback))
        if idx < 0:
            idx = 0
        combo.setCurrentIndex(idx)

    def _update_temp_path_enabled_state(self) -> None:
        """Sync temporary-path edit enablement with its toggle checkbox.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        enabled = bool(self.chk_temp_path_enabled.isChecked())
        self.txt_temp_path.setEnabled(enabled)

    def _update_ratio_enabled_state(self) -> None:
        """Enable ratio spinbox only when default ratio limit is enabled.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        self.spn_max_ratio.setEnabled(bool(self.chk_max_ratio_enabled.isChecked()))

    def _update_seeding_time_enabled_state(self) -> None:
        """Enable seeding-time spinbox only when limit toggle is enabled.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        self.spn_max_seeding_time.setEnabled(bool(self.chk_max_seeding_time_enabled.isChecked()))

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Enable/disable controls while loading/applying preferences.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        enabled = not bool(busy)
        self.tabs.setEnabled(enabled)
        self.btn_apply.setEnabled(enabled)
        if enabled:
            self._update_temp_path_enabled_state()
            self._update_ratio_enabled_state()
            self._update_seeding_time_enabled_state()
        self.lbl_message.setText(str(message or ""))

    def _collect_values(self) -> Dict[str, object]:
        """Collect current friendly form state into preference payload dict.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        values = {
            "save_path": str(self.txt_save_path.text() or "").strip(),
            "temp_path_enabled": bool(self.chk_temp_path_enabled.isChecked()),
            "temp_path": str(self.txt_temp_path.text() or "").strip(),
            "start_paused_enabled": bool(self.chk_start_paused.isChecked()),
            "create_subfolder_enabled": bool(self.chk_create_subfolder.isChecked()),
            "auto_tmm_enabled": bool(self.chk_auto_tmm.isChecked()),
            "incomplete_files_ext": bool(self.chk_incomplete_ext.isChecked()),
            "preallocate_all": bool(self.chk_preallocate.isChecked()),
            "queueing_enabled": bool(self.chk_queueing_enabled.isChecked()),
            "max_active_downloads": int(self.spn_max_active_downloads.value()),
            "max_active_uploads": int(self.spn_max_active_uploads.value()),
            "max_active_torrents": int(self.spn_max_active_torrents.value()),
            "max_connec": int(self.spn_max_connec.value()),
            "max_connec_per_torrent": int(self.spn_max_connec_per_torrent.value()),
            "max_uploads": int(self.spn_max_uploads.value()),
            "max_uploads_per_torrent": int(self.spn_max_uploads_per_torrent.value()),
            "dht": bool(self.chk_dht.isChecked()),
            "pex": bool(self.chk_pex.isChecked()),
            "lsd": bool(self.chk_lsd.isChecked()),
            "upnp": bool(self.chk_upnp.isChecked()),
            "anonymous_mode": bool(self.chk_anonymous_mode.isChecked()),
            "encryption": self._to_int(self.cmb_encryption.currentData(), 0),
            "max_ratio_enabled": bool(self.chk_max_ratio_enabled.isChecked()),
            "max_ratio": float(self.spn_max_ratio.value()),
            "max_seeding_time_enabled": bool(self.chk_max_seeding_time_enabled.isChecked()),
            "max_seeding_time": int(self.spn_max_seeding_time.value()),
        }
        return values

    def set_preferences(self, preferences: Dict[str, object]) -> None:
        """Load selected friendly fields from raw app preferences payload.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        prefs = dict(preferences or {}) if isinstance(preferences, dict) else {}

        self.txt_save_path.setText(str(prefs.get("save_path", "") or ""))
        self.chk_temp_path_enabled.setChecked(self._to_bool(prefs.get("temp_path_enabled", False), False))
        self.txt_temp_path.setText(str(prefs.get("temp_path", "") or ""))
        self.chk_start_paused.setChecked(self._to_bool(prefs.get("start_paused_enabled", False), False))
        self.chk_create_subfolder.setChecked(self._to_bool(prefs.get("create_subfolder_enabled", False), False))
        self.chk_auto_tmm.setChecked(self._to_bool(prefs.get("auto_tmm_enabled", False), False))
        self.chk_incomplete_ext.setChecked(self._to_bool(prefs.get("incomplete_files_ext", False), False))
        self.chk_preallocate.setChecked(self._to_bool(prefs.get("preallocate_all", False), False))
        self.chk_queueing_enabled.setChecked(self._to_bool(prefs.get("queueing_enabled", False), False))
        self.spn_max_active_downloads.setValue(self._to_int(prefs.get("max_active_downloads", -1), -1))
        self.spn_max_active_uploads.setValue(self._to_int(prefs.get("max_active_uploads", -1), -1))
        self.spn_max_active_torrents.setValue(self._to_int(prefs.get("max_active_torrents", -1), -1))
        self.spn_max_connec.setValue(self._to_int(prefs.get("max_connec", -1), -1))
        self.spn_max_connec_per_torrent.setValue(self._to_int(prefs.get("max_connec_per_torrent", -1), -1))
        self.spn_max_uploads.setValue(self._to_int(prefs.get("max_uploads", -1), -1))
        self.spn_max_uploads_per_torrent.setValue(self._to_int(prefs.get("max_uploads_per_torrent", -1), -1))
        self.chk_dht.setChecked(self._to_bool(prefs.get("dht", True), True))
        self.chk_pex.setChecked(self._to_bool(prefs.get("pex", True), True))
        self.chk_lsd.setChecked(self._to_bool(prefs.get("lsd", True), True))
        self.chk_upnp.setChecked(self._to_bool(prefs.get("upnp", True), True))
        self.chk_anonymous_mode.setChecked(self._to_bool(prefs.get("anonymous_mode", False), False))
        self._set_combo_data(self.cmb_encryption, prefs.get("encryption", 0), 0)
        self.chk_max_ratio_enabled.setChecked(self._to_bool(prefs.get("max_ratio_enabled", False), False))
        self.spn_max_ratio.setValue(self._to_float(prefs.get("max_ratio", 0.0), 0.0))
        self.chk_max_seeding_time_enabled.setChecked(
            self._to_bool(prefs.get("max_seeding_time_enabled", False), False)
        )
        self.spn_max_seeding_time.setValue(self._to_int(prefs.get("max_seeding_time", 0), 0))
        self._update_temp_path_enabled_state()
        self._update_ratio_enabled_state()
        self._update_seeding_time_enabled_state()

        self._original_values = self._collect_values()
        self.lbl_message.setText("Loaded friendly add preferences.")

    def changed_preferences(self) -> Dict[str, object]:
        """Return only friendly fields changed by the user.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        current = self._collect_values()
        changes: Dict[str, object] = {}
        for key in self.FRIENDLY_PREF_KEYS:
            if current.get(key) != self._original_values.get(key):
                changes[key] = copy.deepcopy(current.get(key))
        return changes

    def _emit_apply(self) -> None:
        """Emit only changed friendly preferences for API apply.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        changes = self.changed_preferences()
        if not changes:
            self.lbl_message.setText("No changed preferences to apply.")
            return
        self.apply_requested.emit(changes)

class TrackerHealthDialog(QDialog):
    """Dialog to display aggregated tracker health metrics."""

    refresh_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize tracker health dashboard widgets."""
        super().__init__(parent)
        self.setWindowTitle("Tracker Health Dashboard")
        self.resize(980, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build tracker-health table and control buttons.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Set dialog busy state.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        self.btn_refresh.setEnabled(not bool(busy))
        if message:
            self.lbl_summary.setText(message)

    def set_rows(self, rows: List[TrackerHealthRow]) -> None:
        """Render aggregated tracker-health rows.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

class TimelineGraphWidget(QWidget):
    """Simple custom graph for session timeline samples."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize timeline graph with an empty sample buffer."""
        super().__init__(parent)
        self._samples: List[SessionTimelineSample] = []
        self.setMinimumHeight(260)

    def set_samples(self, samples: List[SessionTimelineSample]) -> None:
        """Set timeline samples and trigger repaint.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        self._samples = list(samples or [])
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render timeline graph for speed, active-count, and alt-mode bands.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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
            """Map sample index to chart x coordinate.

            Side effects: Updates dialog/widget state and connected UI controls.
            Failure modes: None.
            """
            return left + int(i * chart_w / max(1, len(samples) - 1))

        def y_for_speed(value: int) -> int:
            """Map speed value to chart y coordinate.

            Side effects: Updates dialog/widget state and connected UI controls.
            Failure modes: None.
            """
            return top + chart_h - int(max(0, int(value)) * chart_h / max_speed)

        def y_for_active(value: int) -> int:
            """Map active torrent count to chart y coordinate.

            Side effects: Updates dialog/widget state and connected UI controls.
            Failure modes: None.
            """
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

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize session timeline dialog controls."""
        super().__init__(parent)
        self.setWindowTitle("Session Timeline")
        self.resize(980, 420)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build timeline graph panel, summary label, and control row.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

    def set_samples(self, samples: List[SessionTimelineSample]) -> None:
        """Update timeline graph and summary.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
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

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Set dialog busy state.

        Side effects: Updates dialog/widget state and connected UI controls.
        Failure modes: None.
        """
        enabled = not bool(busy)
        self.btn_refresh.setEnabled(enabled)
        self.btn_clear.setEnabled(enabled)
        if message:
            self.lbl_summary.setText(message)
