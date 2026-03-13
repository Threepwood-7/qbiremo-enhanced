"""Dialog and small widget classes."""

import copy
import json
import os
from typing import Any, cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .dialogs_telemetry import (
    SessionTimelineDialog,
    TimelineGraphWidget,
    TrackerHealthDialog,
)

__all__ = [
    "AddTorrentDialog",
    "AppPreferencesDialog",
    "FriendlyAddPreferencesDialog",
    "SessionTimelineDialog",
    "SpeedLimitsDialog",
    "TaxonomyManagerDialog",
    "TimelineGraphWidget",
    "TrackerHealthDialog",
]


class AddTorrentDialog(QDialog):
    """Dialog for adding a new torrent"""

    def __init__(
        self,
        categories: list[str],
        tags: list[str],
        parent: QWidget | None = None,
    ) -> None:
        """Initialize add-torrent dialog with source and behavior editors."""
        super().__init__(parent)
        self.setWindowTitle("Add Torrent")
        self.resize(780, 720)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_source_group())
        tabs = QTabWidget()
        tabs.addTab(self._build_basic_tab(categories, tags), "Basic")
        tabs.addTab(self._build_behavior_tab(), "Behavior")
        tabs.addTab(self._build_limits_tab(), "Limits")
        layout.addWidget(tabs)
        layout.addWidget(self._build_dialog_button_box())
        self.torrent_data: dict[str, object] | None = None

    def _build_source_group(self) -> QGroupBox:
        """Create source editors for file and URL torrent inputs."""
        group = QGroupBox("Torrent Sources")
        layout = QVBoxLayout(group)

        file_row = QHBoxLayout()
        self.txt_torrent_files = QTextEdit()
        self.txt_torrent_files.setPlaceholderText("Torrent files (one path per line).")
        self.txt_torrent_files.setFixedHeight(86)
        btn_browse_files = QPushButton("Browse Files...")
        btn_browse_files.clicked.connect(self._browse_files)
        file_row.addWidget(self.txt_torrent_files, 1)
        file_row.addWidget(btn_browse_files)
        layout.addLayout(file_row)

        url_row = QHBoxLayout()
        self.txt_source_urls = QTextEdit()
        self.txt_source_urls.setPlaceholderText("Magnet links / URLs (one per line).")
        self.txt_source_urls.setFixedHeight(86)
        url_row.addWidget(self.txt_source_urls, 1)
        layout.addLayout(url_row)
        return group

    def _build_basic_tab(self, categories: list[str], tags: list[str]) -> QWidget:
        """Create basic add-torrent options tab."""
        tab = QWidget()
        form = QFormLayout(tab)

        save_layout = QHBoxLayout()
        self.txt_save_path = QLineEdit()
        self.txt_save_path.setPlaceholderText("Main save path (optional)")
        btn_save_browse = QPushButton("Browse...")
        btn_save_browse.clicked.connect(self._browse_save_path)
        save_layout.addWidget(self.txt_save_path)
        save_layout.addWidget(btn_save_browse)
        form.addRow("Save Path:", save_layout)

        download_layout = QHBoxLayout()
        self.txt_download_path = QLineEdit()
        self.txt_download_path.setPlaceholderText("Download path (optional)")
        btn_download_browse = QPushButton("Browse...")
        btn_download_browse.clicked.connect(self._browse_download_path)
        download_layout.addWidget(self.txt_download_path)
        download_layout.addWidget(btn_download_browse)
        form.addRow("Download Path:", download_layout)

        self.chk_use_download_path = QCheckBox("Use Download Path")
        form.addRow("", self.chk_use_download_path)

        self.cmb_category = QComboBox()
        self.cmb_category.setEditable(True)
        self.cmb_category.addItems(["", *categories])
        form.addRow("Category:", self.cmb_category)

        self.lst_tags = QListWidget()
        self.lst_tags.setMaximumHeight(100)
        for tag in tags:
            item = QListWidgetItem(tag)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.lst_tags.addItem(item)
        form.addRow("Tags:", self.lst_tags)

        self.txt_tags_extra = QLineEdit()
        self.txt_tags_extra.setPlaceholderText("Additional tags (comma-separated)")
        form.addRow("Extra Tags:", self.txt_tags_extra)

        self.txt_rename = QLineEdit()
        self.txt_rename.setPlaceholderText("Rename torrent (optional)")
        form.addRow("Rename:", self.txt_rename)

        self.txt_cookie = QLineEdit()
        self.txt_cookie.setPlaceholderText(
            "HTTP cookie(s) for URL-based torrents (optional)"
        )
        form.addRow("Cookie:", self.txt_cookie)
        return tab

    def _build_behavior_tab(self) -> QWidget:
        """Create behavior options tab."""
        tab = QWidget()
        form = QFormLayout(tab)

        self.chk_auto_tmm = QCheckBox("Automatic Torrent Management")
        form.addRow("", self.chk_auto_tmm)

        self.chk_paused = QCheckBox("Start torrent paused")
        form.addRow("", self.chk_paused)

        self.chk_stopped = QCheckBox("Add torrent stopped")
        form.addRow("", self.chk_stopped)

        self.chk_forced = QCheckBox("Force start")
        form.addRow("", self.chk_forced)

        self.chk_add_to_top = QCheckBox("Add to top of queue")
        form.addRow("", self.chk_add_to_top)

        self.chk_skip_check = QCheckBox("Skip hash check")
        form.addRow("", self.chk_skip_check)

        self.chk_sequential = QCheckBox("Sequential download")
        form.addRow("", self.chk_sequential)

        self.chk_first_last = QCheckBox("First and last piece priority")
        form.addRow("", self.chk_first_last)

        self.chk_root_folder = QCheckBox("Create root folder")
        form.addRow("", self.chk_root_folder)

        self.cmb_content_layout = QComboBox()
        self.cmb_content_layout.addItems(
            ["Default", "Original", "Subfolder", "NoSubfolder"]
        )
        form.addRow("Content Layout:", self.cmb_content_layout)

        self.cmb_stop_condition = QComboBox()
        self.cmb_stop_condition.addItems(
            ["Default", "MetadataReceived", "FilesChecked"]
        )
        form.addRow("Stop Condition:", self.cmb_stop_condition)
        return tab

    def _build_limits_tab(self) -> QWidget:
        """Create transfer/share limits tab."""
        tab = QWidget()
        form = QFormLayout(tab)

        self.spn_upload_limit = QSpinBox()
        self.spn_upload_limit.setRange(0, 10_000_000)
        self.spn_upload_limit.setSpecialValueText("Unlimited")
        self.spn_upload_limit.setSuffix(" KiB/s")
        form.addRow("Upload Limit:", self.spn_upload_limit)

        self.spn_download_limit = QSpinBox()
        self.spn_download_limit.setRange(0, 10_000_000)
        self.spn_download_limit.setSpecialValueText("Unlimited")
        self.spn_download_limit.setSuffix(" KiB/s")
        form.addRow("Download Limit:", self.spn_download_limit)

        self.spn_ratio_limit = QDoubleSpinBox()
        self.spn_ratio_limit.setRange(-1.0, 10_000.0)
        self.spn_ratio_limit.setDecimals(2)
        self.spn_ratio_limit.setSingleStep(0.1)
        self.spn_ratio_limit.setValue(-1.0)
        form.addRow("Ratio Limit:", self.spn_ratio_limit)

        self.spn_seeding_time_limit = QSpinBox()
        self.spn_seeding_time_limit.setRange(-1, 10_000_000)
        self.spn_seeding_time_limit.setValue(-1)
        self.spn_seeding_time_limit.setSuffix(" min")
        form.addRow("Seeding Time Limit:", self.spn_seeding_time_limit)

        self.spn_inactive_seeding_time_limit = QSpinBox()
        self.spn_inactive_seeding_time_limit.setRange(-1, 10_000_000)
        self.spn_inactive_seeding_time_limit.setValue(-1)
        self.spn_inactive_seeding_time_limit.setSuffix(" min")
        form.addRow("Inactive Seeding Limit:", self.spn_inactive_seeding_time_limit)

        self.cmb_share_limit_action = QComboBox()
        self.cmb_share_limit_action.addItems(
            ["Default", "Stop", "Remove", "RemoveWithContent", "EnableSuperSeeding"]
        )
        form.addRow("Share Limit Action:", self.cmb_share_limit_action)
        return tab

    def _build_dialog_button_box(self) -> QDialogButtonBox:
        """Create standard accept/cancel dialog controls."""
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        return button_box

    def accept(self) -> None:
        """Validate and cache torrent payload before closing the dialog."""
        payload = self.get_torrent_data()
        if not payload:
            return
        self.torrent_data = payload
        super().accept()

    def _browse_files(self) -> None:
        """Browse and append one or more torrent files."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Torrent Files", "", "Torrent Files (*.torrent);;All Files (*)"
        )
        if file_paths:
            self._append_multiline_entries(self.txt_torrent_files, file_paths)

    def _browse_save_path(self) -> None:
        """Browse for save directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Save Directory")
        if dir_path:
            self.txt_save_path.setText(dir_path)

    def _browse_download_path(self) -> None:
        """Browse for download directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if dir_path:
            self.txt_download_path.setText(dir_path)

    @staticmethod
    def _split_csv(text: str) -> list[str]:
        """Split comma-separated text into trimmed non-empty entries."""
        return [p.strip() for p in (text or "").split(",") if p.strip()]

    @staticmethod
    def _split_multiline(text: str) -> list[str]:
        """Split multiline text into trimmed non-empty lines."""
        return [line.strip() for line in str(text or "").splitlines() if line.strip()]

    def _append_multiline_entries(self, editor: QTextEdit, entries: list[str]) -> None:
        """Append unique lines to one multiline editor while preserving order."""
        existing = self._split_multiline(editor.toPlainText())
        combined: list[str] = existing + [
            str(entry).strip() for entry in (entries or []) if str(entry).strip()
        ]
        # Preserve order while removing duplicates.
        deduped: list[str] = list(dict.fromkeys(combined))
        editor.setPlainText("\n".join(deduped))

    def _get_selected_tags(self) -> str:
        """Return comma-separated string of checked tags."""
        selected: list[str] = []
        for i in range(self.lst_tags.count()):
            item = self.lst_tags.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.text())
        selected.extend(self._split_csv(self.txt_tags_extra.text()))
        # preserve order but remove duplicates
        deduped: list[str] = list(dict.fromkeys(selected))
        return ",".join(deduped)

    @staticmethod
    def _is_url_source(source: str) -> bool:
        """Return True when one source entry is a supported URL/magnet."""
        lower = source.lower()
        return (
            lower.startswith("magnet:")
            or lower.startswith("http://")
            or lower.startswith("https://")
            or lower.startswith("bc://")
        )

    @staticmethod
    def _parse_url_sources(lines: list[str]) -> str | list[str]:
        """Convert URL list to qBittorrent payload format (single item or list)."""
        # Accept one URL per line for convenience.
        if not lines:
            return ""
        if len(lines) == 1:
            return lines[0]
        return lines

    def _apply_path_fields(self, data: dict[str, object]) -> bool:
        """Apply save/download path fields and validate required toggles."""
        save_path = self.txt_save_path.text().strip()
        if save_path:
            data["save_path"] = save_path

        download_path = self.txt_download_path.text().strip()
        if download_path:
            data["download_path"] = download_path
        if self.chk_use_download_path.isChecked():
            if not download_path:
                QMessageBox.warning(
                    self,
                    "Missing Download Path",
                    "Use Download Path is enabled, but Download Path is empty.",
                )
                return False
            data["use_download_path"] = True
        return True

    def _apply_metadata_fields(self, data: dict[str, object]) -> None:
        """Apply category, tags, rename, and cookie options."""
        category = self.cmb_category.currentText().strip()
        if category:
            data["category"] = category

        tags = self._get_selected_tags().strip()
        if tags:
            data["tags"] = tags

        rename = self.txt_rename.text().strip()
        if rename:
            data["rename"] = rename

        cookie = self.txt_cookie.text().strip()
        if cookie:
            data["cookie"] = cookie

    def _apply_behavior_fields(self, data: dict[str, object]) -> None:
        """Apply behavior flags and enum options."""
        data["is_paused"] = self.chk_paused.isChecked()
        data["is_stopped"] = self.chk_stopped.isChecked()
        data["forced"] = self.chk_forced.isChecked()
        data["add_to_top_of_queue"] = self.chk_add_to_top.isChecked()
        data["is_skip_checking"] = self.chk_skip_check.isChecked()
        data["is_sequential_download"] = self.chk_sequential.isChecked()
        data["is_first_last_piece_priority"] = self.chk_first_last.isChecked()
        data["use_auto_torrent_management"] = self.chk_auto_tmm.isChecked()
        data["is_root_folder"] = self.chk_root_folder.isChecked()

        content_layout = self.cmb_content_layout.currentText()
        if content_layout != "Default":
            data["content_layout"] = content_layout

        stop_condition = self.cmb_stop_condition.currentText()
        if stop_condition != "Default":
            data["stop_condition"] = stop_condition

    def _apply_limits_fields(self, data: dict[str, object]) -> None:
        """Apply transfer and share-limit options."""
        up_limit_kib = self.spn_upload_limit.value()
        if up_limit_kib > 0:
            data["upload_limit"] = up_limit_kib * 1024

        down_limit_kib = self.spn_download_limit.value()
        if down_limit_kib > 0:
            data["download_limit"] = down_limit_kib * 1024

        ratio_limit = float(self.spn_ratio_limit.value())
        if ratio_limit >= 0:
            data["ratio_limit"] = ratio_limit

        seeding_time_limit = int(self.spn_seeding_time_limit.value())
        if seeding_time_limit >= 0:
            data["seeding_time_limit"] = seeding_time_limit

        inactive_seeding_limit = int(self.spn_inactive_seeding_time_limit.value())
        if inactive_seeding_limit >= 0:
            data["inactive_seeding_time_limit"] = inactive_seeding_limit

        share_limit_action = self.cmb_share_limit_action.currentText()
        if share_limit_action != "Default":
            data["share_limit_action"] = share_limit_action

    def _validate_source_files(self, source_files: list[str]) -> bool:
        """Validate selected torrent file paths."""
        if not source_files:
            return True
        missing_files = [path for path in source_files if not os.path.exists(path)]
        if missing_files:
            QMessageBox.warning(
                self,
                "Torrent File Not Found",
                "File does not exist:\n" + "\n".join(missing_files),
            )
            return False
        return True

    def _validate_source_urls(self, source_urls: list[str]) -> bool:
        """Validate URL and magnet inputs."""
        if not source_urls:
            return True
        invalid_urls = [url for url in source_urls if not self._is_url_source(url)]
        if invalid_urls:
            QMessageBox.warning(
                self,
                "Invalid Magnet/URL",
                "These entries are not valid magnet links or URLs:\n"
                + "\n".join(invalid_urls),
            )
            return False
        return True

    def _apply_source_fields(
        self,
        data: dict[str, object],
        source_files: list[str],
        source_urls: list[str],
    ) -> None:
        """Apply validated source file/url inputs into payload."""
        if source_files:
            data["torrent_files"] = (
                source_files[0] if len(source_files) == 1 else source_files
            )
        if source_urls:
            data["urls"] = self._parse_url_sources(source_urls)

    def get_torrent_data(self) -> dict[str, object] | None:
        """Get the torrent data from the dialog."""
        source_files = self._split_multiline(self.txt_torrent_files.toPlainText())
        source_urls = self._split_multiline(self.txt_source_urls.toPlainText())
        if not source_files and not source_urls:
            return None

        data: dict[str, object] = {}
        if not self._apply_path_fields(data):
            return None
        self._apply_metadata_fields(data)
        self._apply_behavior_fields(data)
        self._apply_limits_fields(data)
        if not self._validate_source_files(source_files):
            return None
        if not self._validate_source_urls(source_urls):
            return None
        self._apply_source_fields(data, source_files, source_urls)

        return data


class TaxonomyManagerDialog(QDialog):
    """Dialog to manage categories and tags in one place."""

    create_category_requested = Signal(str, str, str, bool)
    edit_category_requested = Signal(str, str, str, bool)
    delete_category_requested = Signal(str)
    create_tags_requested = Signal(list)
    delete_tags_requested = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize category and tag management dialog state."""
        super().__init__(parent)
        self.setWindowTitle("Manage Tags and Categories")
        self.resize(760, 520)

        self._category_data: dict[str, dict[str, object]] = {}
        self._build_ui()
        self._set_category_create_mode()

    def _build_ui(self) -> None:
        """Create categories/tags tabs and wire user actions."""
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Categories tab
        category_widget = QWidget()
        category_layout = QHBoxLayout(category_widget)
        category_layout.setContentsMargins(4, 4, 4, 4)

        self.lst_categories = QListWidget()
        self.lst_categories.currentItemChanged.connect(
            self._on_category_selection_changed
        )
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
        self.chk_category_use_incomplete.toggled.connect(
            self._update_incomplete_path_enabled_state
        )
        form.addRow("", self.chk_category_use_incomplete)

        inc_row = QHBoxLayout()
        self.txt_category_incomplete_path = QLineEdit()
        self.txt_category_incomplete_path.setPlaceholderText("Optional incomplete path")
        self.btn_category_browse_incomplete = QPushButton("Browse")
        self.btn_category_browse_incomplete.clicked.connect(
            self._browse_category_incomplete_path
        )
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
        self.lst_tags_manage.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
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
        """Browse for category default save path."""
        initial = self.txt_category_save_path.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self, "Select Category Save Path", initial
        )
        if selected:
            self.txt_category_save_path.setText(selected)

    def _browse_category_incomplete_path(self) -> None:
        """Browse for category incomplete save path."""
        initial = self.txt_category_incomplete_path.text().strip()
        selected = QFileDialog.getExistingDirectory(
            self, "Select Category Incomplete Path", initial
        )
        if selected:
            self.txt_category_incomplete_path.setText(selected)

    def _update_incomplete_path_enabled_state(self, *_args: object) -> None:
        """Enable/disable incomplete path controls based on checkbox."""
        enabled = bool(self.chk_category_use_incomplete.isChecked())
        self.txt_category_incomplete_path.setEnabled(enabled)
        self.btn_category_browse_incomplete.setEnabled(enabled)

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Enable/disable editor controls while an API operation runs."""
        enabled = not bool(busy)
        self.tabs.setEnabled(enabled)
        self.btn_category_new.setEnabled(enabled)
        self.btn_category_apply.setEnabled(enabled)
        self.btn_category_delete.setEnabled(
            enabled and self.lst_categories.currentRow() >= 0
        )
        self.chk_category_use_incomplete.setEnabled(enabled)
        self.txt_category_incomplete_path.setEnabled(
            enabled and self.chk_category_use_incomplete.isChecked()
        )
        self.btn_category_browse_incomplete.setEnabled(
            enabled and self.chk_category_use_incomplete.isChecked()
        )
        self.btn_add_tags.setEnabled(enabled)
        self.btn_delete_tags.setEnabled(enabled)
        self.lbl_message.setText(str(message or ""))

    def set_taxonomy_data(
        self, category_data: dict[str, dict[str, object]], tags: list[str]
    ) -> None:
        """Refresh dialog contents from latest category/tag lists."""
        current_category = self.selected_category_name()
        selected_tags = {item.text() for item in self.lst_tags_manage.selectedItems()}

        self._category_data = dict(category_data or {})
        self.lst_categories.clear()
        for name in sorted(self._category_data.keys()):
            self.lst_categories.addItem(name)

        if current_category:
            matches = self.lst_categories.findItems(
                current_category, Qt.MatchFlag.MatchExactly
            )
            if matches:
                self.lst_categories.setCurrentItem(matches[0])
            else:
                self._set_category_create_mode()
        elif self.lst_categories.currentRow() < 0:
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

    def _on_category_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        """Load selected category into the editor."""
        if current is None:
            self._set_category_create_mode()
            return

        name = current.text().strip()
        details = self._category_data.get(name, {})
        self.txt_category_name.setReadOnly(True)
        self.txt_category_name.setText(name)
        self.txt_category_save_path.setText(str(details.get("save_path", "") or ""))
        use_incomplete = bool(details.get("use_incomplete_path", False))
        self.chk_category_use_incomplete.setChecked(use_incomplete)
        self.txt_category_incomplete_path.setText(
            str(details.get("incomplete_path", "") or "")
        )
        self._update_incomplete_path_enabled_state()
        self.btn_category_apply.setText("Update Category")
        self.btn_category_delete.setEnabled(True)

    def _set_category_create_mode(self) -> None:
        """Prepare editor for creating a new category."""
        if self.lst_categories.currentRow() >= 0:
            prev = self.lst_categories.blockSignals(True)
            self.lst_categories.clearSelection()
            self.lst_categories.setCurrentRow(-1)
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
            self.edit_category_requested.emit(
                selected_name, save_path, incomplete_path, use_incomplete
            )
        else:
            self.create_category_requested.emit(
                name, save_path, incomplete_path, use_incomplete
            )

    def _delete_selected_category(self) -> None:
        """Emit delete request for selected category."""
        name = self.selected_category_name()
        if not name:
            self.lbl_message.setText("Select a category to delete.")
            return
        self.delete_category_requested.emit(name)

    @staticmethod
    def _parse_csv_entries(raw_text: str) -> list[str]:
        """Parse comma-separated text into unique ordered tag values."""
        values: list[str] = []
        seen: set[str] = set()
        for part in str(raw_text or "").split(","):
            value = part.strip()
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        return values

    def _add_tags(self) -> None:
        """Emit create-tags request from entry field."""
        tags = self._parse_csv_entries(self.txt_new_tags.text())
        if not tags:
            self.lbl_message.setText("Enter at least one tag.")
            return
        self.create_tags_requested.emit(tags)
        self.txt_new_tags.clear()

    def _delete_selected_tags(self) -> None:
        """Emit delete-tags request for selected tags."""
        tags = [
            item.text().strip()
            for item in self.lst_tags_manage.selectedItems()
            if item.text().strip()
        ]
        if not tags:
            self.lbl_message.setText("Select at least one tag to delete.")
            return
        self.delete_tags_requested.emit(tags)


class SpeedLimitsDialog(QDialog):
    """Dialog to manage global and alternative speed limits."""

    refresh_requested = Signal()
    apply_requested = Signal(
        int, int, int, int, bool
    )  # normal_dl_kib, normal_ul_kib, alt_dl_kib, alt_ul_kib, alt_enabled

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize speed-limits dialog controls."""
        super().__init__(parent)
        self.setWindowTitle("Manage Speed Limits")
        self.resize(520, 320)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build normal/alternative speed controls and command buttons."""
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
        """Emit apply signal with current dialog values."""
        self.apply_requested.emit(
            int(self.spn_normal_dl.value()),
            int(self.spn_normal_ul.value()),
            int(self.spn_alt_dl.value()),
            int(self.spn_alt_ul.value()),
            bool(self.chk_alt_enabled.isChecked()),
        )

    def set_values(
        self,
        normal_dl_bytes: int,
        normal_ul_bytes: int,
        alt_dl_bytes: int,
        alt_ul_bytes: int,
        alt_enabled: bool,
    ) -> None:
        """Update dialog controls from bytes/sec values."""
        self.spn_normal_dl.setValue(max(0, int(normal_dl_bytes)) // 1024)
        self.spn_normal_ul.setValue(max(0, int(normal_ul_bytes)) // 1024)
        self.spn_alt_dl.setValue(max(0, int(alt_dl_bytes)) // 1024)
        self.spn_alt_ul.setValue(max(0, int(alt_ul_bytes)) // 1024)
        self.chk_alt_enabled.setChecked(bool(alt_enabled))

    def set_busy(self, busy: bool, message: str = "") -> None:
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


class AppPreferencesDialog(QDialog):
    """Dialog to edit raw qBittorrent application preferences in a tree view."""

    apply_requested = Signal(dict)

    ROLE_PATH = int(Qt.ItemDataRole.UserRole) + 200
    ROLE_IS_LEAF = int(Qt.ItemDataRole.UserRole) + 201

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize raw preferences editor state and tree bindings."""
        super().__init__(parent)
        self.setWindowTitle("Edit App Preferences")
        self.resize(980, 640)
        self._updating_tree = False
        self._original_preferences: dict[str, object] = {}
        self._edited_preferences: dict[str, object] = {}
        self._path_items: dict[tuple[object, ...], QTreeWidgetItem] = {}
        self._leaf_original_values: dict[tuple[object, ...], object] = {}
        self._leaf_current_values: dict[tuple[object, ...], object] = {}
        self._leaf_items: dict[tuple[object, ...], QTreeWidgetItem] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        """Build preferences tree view and apply/cancel actions."""
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
        """Enable/disable dialog controls while API operation runs."""
        enabled = not bool(busy)
        self.tree_preferences.setEnabled(enabled)
        self.btn_apply.setEnabled(enabled)
        self.lbl_message.setText(str(message or ""))

    def set_preferences(self, preferences: dict[str, object]) -> None:
        """Load preferences into editable tree and reset change tracking."""
        self._updating_tree = True
        try:
            source = dict(preferences)
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
            self.lbl_message.setText(
                f"Loaded {len(self._edited_preferences)} preferences."
            )
        finally:
            self._updating_tree = False

    @staticmethod
    def _is_container(value: object) -> bool:
        """Return True when value is a nested dict/list container."""
        return isinstance(value, (dict, list))

    @staticmethod
    def _as_object_dict(value: object) -> dict[str, object]:
        """Normalize one object to a plain string-key dict when possible."""
        if not isinstance(value, dict):
            return {}
        return {
            str(key): entry
            for key, entry in cast("dict[object, object]", value).items()
        }

    @staticmethod
    def _as_object_list(value: object) -> list[object]:
        """Normalize one object to a plain list when possible."""
        if not isinstance(value, list):
            return []
        return list(cast("list[object]", value))

    @staticmethod
    def _value_type_name(value: object) -> str:
        """Return a human-readable type name for one preference value."""
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
        """Render one preference value to editable text representation."""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        object_dict = AppPreferencesDialog._as_object_dict(value)
        object_list = AppPreferencesDialog._as_object_list(value)
        if object_dict or object_list:
            payload: object = object_dict if object_dict else object_list
            try:
                return json.dumps(payload, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                return str(payload)
        return str(value)

    @staticmethod
    def _container_summary(value: object) -> str:
        """Return compact summary label for dict/list containers."""
        object_dict = AppPreferencesDialog._as_object_dict(value)
        if object_dict:
            count = len(object_dict)
            suffix = "key" if count == 1 else "keys"
            return f"{{{count} {suffix}}}"
        object_list = AppPreferencesDialog._as_object_list(value)
        if object_list:
            count = len(object_list)
            suffix = "item" if count == 1 else "items"
            return f"[{count} {suffix}]"
        return AppPreferencesDialog._value_to_text(value)

    def _add_pref_item(
        self,
        parent_item: QTreeWidgetItem | None,
        path: tuple[object, ...],
        label: str,
        value: object,
    ) -> None:
        """Add one preference tree node and recurse for nested values."""
        item = QTreeWidgetItem([str(label), "", self._value_type_name(value)])
        item.setData(0, self.ROLE_PATH, path)
        item.setData(0, self.ROLE_IS_LEAF, False)
        if parent_item is None:
            self.tree_preferences.addTopLevelItem(item)
        else:
            parent_item.addChild(item)
        self._path_items[path] = item

        dict_value = self._as_object_dict(value)
        if dict_value:
            item.setText(1, self._container_summary(dict_value))
            for child_key in sorted(dict_value.keys(), key=str):
                child_path = (*path, child_key)
                self._add_pref_item(
                    item, child_path, str(child_key), dict_value.get(child_key)
                )
            return

        list_value = self._as_object_list(value)
        if list_value:
            item.setText(1, self._container_summary(list_value))
            for index, child_value in enumerate(list_value):
                child_path = (*path, index)
                self._add_pref_item(item, child_path, f"[{index}]", child_value)
            return

        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setData(0, self.ROLE_IS_LEAF, True)
        item.setText(1, self._value_to_text(value))
        self._leaf_original_values[path] = copy.deepcopy(value)
        self._leaf_current_values[path] = copy.deepcopy(value)
        self._leaf_items[path] = item

    @staticmethod
    def _normalize_item_path(path_data: object) -> tuple[object, ...]:
        """Normalize serialized path metadata to tuple form."""
        if isinstance(path_data, tuple):
            return cast("tuple[object, ...]", path_data)
        if isinstance(path_data, list):
            return tuple(cast("list[object]", path_data))
        return ()

    @staticmethod
    def _path_label(path: tuple[object, ...]) -> str:
        """Format one tree path tuple as dotted/bracketed label."""
        if not path:
            return ""
        parts: list[str] = []
        for part in path:
            if isinstance(part, int):
                parts.append(f"[{part}]")
            else:
                if parts:
                    parts.append(".")
                parts.append(str(part))
        return "".join(parts)

    @staticmethod
    def _set_path_value(
        container: object, path: tuple[object, ...], value: object
    ) -> None:
        """Assign one nested container value addressed by path tuple."""
        target: Any = container
        for key in path[:-1]:
            target = target[key]
        target[cast("Any", path[-1])] = value

    @staticmethod
    def _get_path_value(container: object, path: tuple[object, ...]) -> object:
        """Resolve one nested container value addressed by path tuple."""
        target: Any = container
        for key in path:
            target = target[key]
        return target

    @staticmethod
    def _parse_bool(text: str) -> bool:
        """Parse flexible bool text tokens and raise on invalid input."""
        token = str(text or "").strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
        raise ValueError("expected boolean (true/false)")

    @staticmethod
    def _parse_json_object_text(stripped: str) -> dict[str, object]:
        """Parse one JSON object payload from edited text."""
        if not stripped:
            return {}
        parsed = json.loads(stripped)
        parsed_dict = AppPreferencesDialog._as_object_dict(parsed)
        if not parsed_dict:
            raise ValueError("expected JSON object")
        return parsed_dict

    @staticmethod
    def _parse_json_array_text(stripped: str) -> list[object]:
        """Parse one JSON array payload from edited text."""
        if not stripped:
            return []
        parsed = json.loads(stripped)
        parsed_list = AppPreferencesDialog._as_object_list(parsed)
        if not parsed_list:
            raise ValueError("expected JSON array")
        return parsed_list

    @staticmethod
    def _parse_nullable_json_value(raw: str, stripped: str) -> object:
        """Parse nullable JSON values, falling back to raw text on failure."""
        if stripped.lower() in {"", "null", "none"}:
            return None
        try:
            return json.loads(stripped)
        except (TypeError, ValueError, json.JSONDecodeError):
            return raw

    @staticmethod
    def _parse_value_by_example(text: str, example: object) -> object:
        """Parse editor text using original value type as parsing guide."""
        raw = str(text or "")
        stripped = raw.strip()
        example_dict = AppPreferencesDialog._as_object_dict(example)
        example_list = AppPreferencesDialog._as_object_list(example)

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
        if example_dict:
            return AppPreferencesDialog._parse_json_object_text(stripped)
        if example_list:
            return AppPreferencesDialog._parse_json_array_text(stripped)
        if example is None:
            return AppPreferencesDialog._parse_nullable_json_value(raw, stripped)
        if isinstance(example, str):
            return raw
        try:
            return json.loads(stripped)
        except (TypeError, ValueError, json.JSONDecodeError):
            return raw

    def _refresh_changed_highlights(self) -> None:
        """Highlight changed leaf values in coral for quick scanning."""
        coral_brush = QBrush(QColor("coral"))
        clear_brush = QBrush()
        for path, item in self._leaf_items.items():
            original = self._leaf_original_values.get(path)
            current = self._leaf_current_values.get(path)
            changed = current != original
            item.setBackground(1, coral_brush if changed else clear_brush)

    def changed_preferences(self) -> dict[str, object]:
        """Return only top-level preferences changed by the user."""
        changes: dict[str, object] = {}
        for key, edited_value in self._edited_preferences.items():
            original_value = self._original_preferences.get(key, None)
            if key not in self._original_preferences or edited_value != original_value:
                changes[str(key)] = copy.deepcopy(edited_value)
        return changes

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """Validate one edited cell and propagate value/type updates upward."""
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
        except (TypeError, ValueError, json.JSONDecodeError) as e:
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
                ancestor_value = self._get_path_value(
                    self._edited_preferences, ancestor_path
                )
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
        """Emit only changed preferences for API apply."""
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

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize friendly preference editor controls and state."""
        super().__init__(parent)
        self.setWindowTitle("Edit Add Preferences (friendly)")
        self.resize(640, 560)
        self._original_values: dict[str, object] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        """Build tabbed friendly controls for common preference subsets."""
        layout = QVBoxLayout(self)

        self.lbl_summary = QLabel(
            "Friendly editor for common settings. For advanced keys, use "
            "Edit App Preferences."
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
        self.chk_create_subfolder = QCheckBox(
            "Create subfolder for torrents with multiple files"
        )
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
        queue_form.addRow(
            "Maximum connections per torrent:", self.spn_max_connec_per_torrent
        )
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
        self.chk_max_seeding_time_enabled = QCheckBox(
            "Enable default seeding time limit"
        )
        self.chk_max_seeding_time_enabled.toggled.connect(
            self._update_seeding_time_enabled_state
        )
        self.spn_max_seeding_time = QSpinBox()
        self.spn_max_seeding_time.setRange(0, 10_000_000)
        self.spn_max_seeding_time.setSingleStep(10)
        share_form.addRow("", self.chk_max_ratio_enabled)
        share_form.addRow("Default ratio limit:", self.spn_max_ratio)
        share_form.addRow("", self.chk_max_seeding_time_enabled)
        share_form.addRow(
            "Default seeding time limit (minutes):", self.spn_max_seeding_time
        )
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
        """Create integer spinbox using `-1` sentinel for unlimited values."""
        spin = QSpinBox()
        spin.setRange(-1, 10_000_000)
        spin.setSingleStep(1)
        spin.setSpecialValueText("Unlimited (-1)")
        return spin

    @staticmethod
    def _to_bool(value: object, default: bool = False) -> bool:
        """Best-effort conversion of unknown value to bool with default."""
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
        """Best-effort conversion of unknown value to int with default."""
        if isinstance(value, bool):
            return int(default)
        try:
            return int(cast("Any", value))
        except (TypeError, ValueError, OverflowError):
            return int(default)

    @staticmethod
    def _to_float(value: object, default: float = 0.0) -> float:
        """Best-effort conversion of unknown value to float with default."""
        if isinstance(value, bool):
            return float(default)
        try:
            return float(cast("Any", value))
        except (TypeError, ValueError, OverflowError):
            return float(default)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object, fallback: int = 0) -> None:
        """Select combo item by `data` value with robust fallback behavior."""
        desired = FriendlyAddPreferencesDialog._to_int(value, fallback)
        idx = combo.findData(desired)
        if idx < 0:
            idx = combo.findData(int(fallback))
        if idx < 0:
            idx = 0
        combo.setCurrentIndex(idx)

    def _update_temp_path_enabled_state(self) -> None:
        """Sync temporary-path edit enablement with its toggle checkbox."""
        enabled = bool(self.chk_temp_path_enabled.isChecked())
        self.txt_temp_path.setEnabled(enabled)

    def _update_ratio_enabled_state(self) -> None:
        """Enable ratio spinbox only when default ratio limit is enabled."""
        self.spn_max_ratio.setEnabled(bool(self.chk_max_ratio_enabled.isChecked()))

    def _update_seeding_time_enabled_state(self) -> None:
        """Enable seeding-time spinbox only when limit toggle is enabled."""
        self.spn_max_seeding_time.setEnabled(
            bool(self.chk_max_seeding_time_enabled.isChecked())
        )

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Enable/disable controls while loading/applying preferences."""
        enabled = not bool(busy)
        self.tabs.setEnabled(enabled)
        self.btn_apply.setEnabled(enabled)
        if enabled:
            self._update_temp_path_enabled_state()
            self._update_ratio_enabled_state()
            self._update_seeding_time_enabled_state()
        self.lbl_message.setText(str(message or ""))

    def _collect_values(self) -> dict[str, object]:
        """Collect current friendly form state into preference payload dict."""
        values: dict[str, object] = {
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
            "max_seeding_time_enabled": bool(
                self.chk_max_seeding_time_enabled.isChecked()
            ),
            "max_seeding_time": int(self.spn_max_seeding_time.value()),
        }
        return values

    def set_preferences(self, preferences: dict[str, object]) -> None:
        """Load selected friendly fields from raw app preferences payload."""
        prefs = dict(preferences)

        self.txt_save_path.setText(str(prefs.get("save_path", "") or ""))
        self.chk_temp_path_enabled.setChecked(
            self._to_bool(prefs.get("temp_path_enabled", False), False)
        )
        self.txt_temp_path.setText(str(prefs.get("temp_path", "") or ""))
        self.chk_start_paused.setChecked(
            self._to_bool(prefs.get("start_paused_enabled", False), False)
        )
        self.chk_create_subfolder.setChecked(
            self._to_bool(prefs.get("create_subfolder_enabled", False), False)
        )
        self.chk_auto_tmm.setChecked(
            self._to_bool(prefs.get("auto_tmm_enabled", False), False)
        )
        self.chk_incomplete_ext.setChecked(
            self._to_bool(prefs.get("incomplete_files_ext", False), False)
        )
        self.chk_preallocate.setChecked(
            self._to_bool(prefs.get("preallocate_all", False), False)
        )
        self.chk_queueing_enabled.setChecked(
            self._to_bool(prefs.get("queueing_enabled", False), False)
        )
        self.spn_max_active_downloads.setValue(
            self._to_int(prefs.get("max_active_downloads", -1), -1)
        )
        self.spn_max_active_uploads.setValue(
            self._to_int(prefs.get("max_active_uploads", -1), -1)
        )
        self.spn_max_active_torrents.setValue(
            self._to_int(prefs.get("max_active_torrents", -1), -1)
        )
        self.spn_max_connec.setValue(self._to_int(prefs.get("max_connec", -1), -1))
        self.spn_max_connec_per_torrent.setValue(
            self._to_int(prefs.get("max_connec_per_torrent", -1), -1)
        )
        self.spn_max_uploads.setValue(self._to_int(prefs.get("max_uploads", -1), -1))
        self.spn_max_uploads_per_torrent.setValue(
            self._to_int(prefs.get("max_uploads_per_torrent", -1), -1)
        )
        self.chk_dht.setChecked(self._to_bool(prefs.get("dht", True), True))
        self.chk_pex.setChecked(self._to_bool(prefs.get("pex", True), True))
        self.chk_lsd.setChecked(self._to_bool(prefs.get("lsd", True), True))
        self.chk_upnp.setChecked(self._to_bool(prefs.get("upnp", True), True))
        self.chk_anonymous_mode.setChecked(
            self._to_bool(prefs.get("anonymous_mode", False), False)
        )
        self._set_combo_data(self.cmb_encryption, prefs.get("encryption", 0), 0)
        self.chk_max_ratio_enabled.setChecked(
            self._to_bool(prefs.get("max_ratio_enabled", False), False)
        )
        self.spn_max_ratio.setValue(self._to_float(prefs.get("max_ratio", 0.0), 0.0))
        self.chk_max_seeding_time_enabled.setChecked(
            self._to_bool(prefs.get("max_seeding_time_enabled", False), False)
        )
        self.spn_max_seeding_time.setValue(
            self._to_int(prefs.get("max_seeding_time", 0), 0)
        )
        self._update_temp_path_enabled_state()
        self._update_ratio_enabled_state()
        self._update_seeding_time_enabled_state()

        self._original_values = self._collect_values()
        self.lbl_message.setText("Loaded friendly add preferences.")

    def changed_preferences(self) -> dict[str, object]:
        """Return only friendly fields changed by the user."""
        current = self._collect_values()
        changes: dict[str, object] = {}
        for key in self.FRIENDLY_PREF_KEYS:
            if current.get(key) != self._original_values.get(key):
                changes[key] = copy.deepcopy(current.get(key))
        return changes

    def _emit_apply(self) -> None:
        """Emit only changed friendly preferences for API apply."""
        changes = self.changed_preferences()
        if not changes:
            self.lbl_message.setText("No changed preferences to apply.")
            return
        self.apply_requested.emit(changes)
