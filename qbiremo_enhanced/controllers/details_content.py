"""Feature controllers for MainWindow composition."""

import html
import json
from typing import Any, cast

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..models.torrent import (
    TorrentFileEntry,
)
from ..utils import (
    format_datetime,
    format_eta,
    format_size_mode,
    format_speed_mode,
    matches_wildcard,
    normalize_filter_pattern,
    parse_tags,
)
from ..widgets import NumericTableWidgetItem
from .base import RECOVERABLE_CONTROLLER_EXCEPTIONS, WindowControllerBase


class DetailsContentController(WindowControllerBase):
    """Render selected torrent details, peers/trackers, and content tree."""

    def _populate_content_tree(self, files: list[TorrentFileEntry]) -> None:
        """Populate the content tab from cached/serialized file entries."""
        try:
            self.tree_files.clear()

            PRIORITY_NAMES = {0: "Skip", 1: "Normal", 6: "High", 7: "Maximum"}

            # Build a nested dict for directory structure
            dir_nodes: dict[str, QTreeWidgetItem] = {}
            for f in files:
                if isinstance(f, dict):
                    name = str(f.get("name", "") or "")
                    size = self._safe_int(f.get("size", 0), 0)
                    progress = self._safe_float(f.get("progress", 0.0), 0.0)
                    priority = self._safe_int(f.get("priority", 1), 1)
                else:
                    name = getattr(f, "name", "") or ""
                    size = getattr(f, "size", 0)
                    progress = getattr(f, "progress", 0)
                    priority = getattr(f, "priority", 1)

                if not name:
                    continue

                parts = name.replace("\\", "/").split("/")
                parent = None
                for i, part in enumerate(parts[:-1]):
                    dir_key = "/".join(parts[: i + 1])
                    if dir_key not in dir_nodes:
                        node = QTreeWidgetItem([part, "", "", ""])
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

                file_item = QTreeWidgetItem(
                    [
                        parts[-1],
                        format_size_mode(size, self.display_size_mode),
                        f"{progress * 100:.1f}%",
                        PRIORITY_NAMES.get(priority, str(priority)),
                    ]
                )
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
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error populating file tree: {e}")

    def _on_content_filter_changed(self, text: str) -> None:
        """Apply in-tab content filter for selected torrent files."""
        self.current_content_filter = normalize_filter_pattern(text)
        self._apply_content_filter()

    def _apply_content_filter(self) -> None:
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
                    name = str(entry.get("name", "") or "")
                    normalized = name.replace("\\", "/")
                    basename = normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized
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
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error applying content filter: {e}")

    def _show_cached_torrent_content(self, torrent_hash: str) -> None:
        """Display content tree from local cache for selected torrent."""
        self.current_content_files = self._get_cached_files(torrent_hash)
        self._apply_content_filter()

    def _set_table_item(
        self,
        row: int,
        col: int,
        text: str,
        align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
        sort_value: float | None = None,
    ) -> None:
        """Helper to set table item with alignment and optional numeric sort."""
        item: QTableWidgetItem
        if sort_value is not None:
            item = NumericTableWidgetItem(str(text), sort_value)
        else:
            item = QTableWidgetItem(str(text))
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        self.tbl_torrents.setItem(row, col, item)

    def _copy_general_details(self) -> None:
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
    def _selected_table_row(table: QTableWidget) -> int | None:
        """Return first selected row index for table, if any."""
        sel_model = table.selectionModel()
        if sel_model:
            selected_rows = sel_model.selectedRows()
            if selected_rows:
                return selected_rows[0].row()
        current = table.currentRow()
        return current if current >= 0 else None

    def _details_table_to_tsv(
        self, table: QTableWidget, row_indexes: list[int] | None = None
    ) -> str:
        """Serialize one details table subset to TSV (header + rows)."""
        headers: list[str] = []
        for col_idx in range(table.columnCount()):
            header = table.horizontalHeaderItem(col_idx)
            headers.append(str(header.text() if header else f"column_{col_idx}"))

        rows = list(row_indexes) if row_indexes is not None else list(range(table.rowCount()))
        lines = ["\t".join(headers)]
        for row_idx in rows:
            values: list[str] = []
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

    def _copy_all_peers_info(self) -> None:
        """Copy all currently visible peers rows (including headers) to clipboard."""
        if not self._details_table_has_data_rows(self.tbl_peers):
            self._set_status("No peers info to copy")
            return
        text = self._details_table_to_tsv(self.tbl_peers)
        QApplication.clipboard().setText(text)
        self._set_status("All peers info copied to clipboard")

    def _copy_selected_peer_info(self) -> None:
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

    def _copy_selected_peer_ip_port(self) -> None:
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

        action_copy_all = cast(QAction, menu.addAction("Copy All Peers Info"))
        action_copy_all.triggered.connect(self._copy_all_peers_info)
        action_copy_all.setEnabled(has_data)

        action_copy_peer = cast(QAction, menu.addAction("Copy Peer Info"))
        action_copy_peer.triggered.connect(self._copy_selected_peer_info)
        action_copy_peer.setEnabled(has_selection)

        action_copy_ip_port = cast(QAction, menu.addAction("Copy Peer IP:port"))
        action_copy_ip_port.triggered.connect(self._copy_selected_peer_ip_port)
        action_copy_ip_port.setEnabled(has_endpoint)

        menu.addSeparator()

        action_ban = cast(QAction, menu.addAction("Ban Peer"))
        action_ban.triggered.connect(self._ban_selected_peer)
        action_ban.setEnabled(has_endpoint)
        return menu

    def _show_peers_context_menu(self, pos: QPoint) -> None:
        """Show peers context menu and keep right-clicked row selected."""
        row_idx = self.tbl_peers.rowAt(pos.y())
        if row_idx >= 0:
            self.tbl_peers.selectRow(row_idx)
        menu = self._build_peers_context_menu()
        menu.exec(self.tbl_peers.viewport().mapToGlobal(pos))

    def _ban_selected_peer(self) -> None:
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
    def _display_detail_value(value: object, fallback: str = "N/A") -> str:
        """Normalize one detail value for display."""
        if value is None:
            return fallback
        if isinstance(value, str):
            text = value.strip()
            return text if text else fallback
        return str(value)

    def _build_general_details_html(
        self,
        sections: list[tuple[str, list[tuple[str, object]]]],
    ) -> str:
        """Build rich read-only HTML layout for the General details panel."""
        chunks = ["<html><body>"]
        for title, rows in sections:
            chunks.append(f"<h3>{html.escape(str(title))}</h3>")
            chunks.append("<table>")
            for key, value in rows:
                key_text = html.escape(str(key))
                value_text = html.escape(self._display_detail_value(value))
                chunks.append(
                    f'<tr><td class="key">{key_text}</td><td class="value">{value_text}</td></tr>'
                )
            chunks.append("</table>")
        chunks.append("</body></html>")
        return "".join(chunks)

    def _set_torrent_edit_enabled(self, enabled: bool, message: str) -> None:
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

    def _clear_torrent_edit_panel(self, message: str) -> None:
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

    def _refresh_torrent_edit_categories(self, current_category: str = "") -> None:
        """Refresh category combo options while preserving text selection."""
        current_text = str(
            current_category or self.cmb_torrent_edit_category.currentText() or ""
        ).strip()
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
    def _torrent_auto_management_value(torrent: object) -> bool | None:
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

    def _populate_torrent_edit_panel(self, torrent: object) -> None:
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

    def _add_tags_to_torrent_edit(self) -> None:
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

    def _pick_tags_for_torrent_edit(
        self, available_tags: list[str], selected_tags: list[str]
    ) -> list[str] | None:
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

    def _path_exists_on_local_machine(self, raw_path: object) -> bool:
        """Return True when a provided path exists on this machine."""
        candidate = self._expand_local_path(raw_path)
        if candidate is None:
            return False
        try:
            return candidate.exists()
        except (OSError, RuntimeError, ValueError):
            return False

    def _update_torrent_edit_path_browse_buttons(self) -> None:
        """Show browse buttons only for paths that exist on this machine."""
        save_exists = self._path_exists_on_local_machine(self.txt_torrent_edit_save_path.text())
        incomplete_exists = self._path_exists_on_local_machine(
            self.txt_torrent_edit_incomplete_path.text()
        )
        self.btn_torrent_edit_browse_save_path.setVisible(save_exists)
        self.btn_torrent_edit_browse_incomplete_path.setVisible(incomplete_exists)

    def _on_detail_tab_changed(self, _index: int) -> None:
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

    @staticmethod
    def _detail_cell_text(value: object) -> str:
        """Render one trackers/peers cell value to text."""
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple, set)):
            try:
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError, OverflowError, RecursionError):
                return str(value)
        return str(value)

    @staticmethod
    def _detail_sort_value(value: object) -> float | None:
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
            except (TypeError, ValueError, OverflowError):
                return None
        return None

    @staticmethod
    def _build_details_columns(rows: list[dict[str, object]], preferred: list[str]) -> list[str]:
        """Build ordered column list with preferred first, then remaining keys."""
        key_set = set()
        for row in rows:
            key_set.update(str(k) for k in row.keys())

        ordered = [k for k in preferred if k in key_set]
        remainder = sorted(k for k in key_set if k not in ordered)
        return ordered + remainder

    def _set_details_table_message(self, table: QTableWidget, message: str) -> None:
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

    def _populate_details_table(
        self, table: QTableWidget, rows: list[dict[str, object]], preferred_columns: list[str]
    ) -> None:
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
                item: QTableWidgetItem
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
        """Return selected torrent hash, or empty string when none selected."""
        selected = getattr(self, "_selected_torrent", None)
        return str(getattr(selected, "hash", "") or "")

    def _load_selected_torrent_network_details(self, torrent_hash: str) -> None:
        """Load full trackers and peers information for selected torrent."""
        self._set_details_table_message(self.tbl_trackers, "Loading trackers...")
        self._set_details_table_message(self.tbl_peers, "Loading peers...")

        self.details_api_queue.add_task(
            "load_selected_trackers",
            self._fetch_selected_torrent_trackers,
            lambda r, h=torrent_hash: self._on_selected_trackers_loaded(h, r),
            torrent_hash,
        )

    def _on_selected_trackers_loaded(self, torrent_hash: str, result: dict) -> None:
        """Populate Trackers table and then load Peers for same selection."""
        if self._selected_torrent_hash() != torrent_hash:
            return

        if result.get("success"):
            rows = result.get("data", []) or []
            self._populate_details_table(
                self.tbl_trackers,
                rows,
                [
                    "url",
                    "status",
                    "tier",
                    "num_peers",
                    "num_seeds",
                    "num_leeches",
                    "num_downloaded",
                    "msg",
                ],
            )
        else:
            error = result.get("error", "Unknown error")
            self._set_details_table_message(self.tbl_trackers, f"Failed to load trackers: {error}")

        self.details_api_queue.add_task(
            "load_selected_peers",
            self._fetch_selected_torrent_peers,
            lambda r, h=torrent_hash: self._on_selected_peers_loaded(h, r),
            torrent_hash,
        )

    def _on_selected_peers_loaded(self, torrent_hash: str, result: dict) -> None:
        """Populate Peers table for currently selected torrent."""
        if self._selected_torrent_hash() != torrent_hash:
            return

        if result.get("success"):
            rows = result.get("data", []) or []
            self._populate_details_table(
                self.tbl_peers,
                rows,
                [
                    "peer_id",
                    "ip",
                    "port",
                    "client",
                    "connection",
                    "country",
                    "country_code",
                    "flags",
                    "flags_desc",
                    "progress",
                    "dl_speed",
                    "up_speed",
                    "downloaded",
                    "uploaded",
                    "relevance",
                    "files",
                ],
            )
        else:
            error = result.get("error", "Unknown error")
            self._set_details_table_message(self.tbl_peers, f"Failed to load peers: {error}")

    def _set_details_panels_enabled(self, enabled: bool) -> None:
        """Enable/disable bottom details tabs."""
        self.detail_tabs.setEnabled(bool(enabled))
        self._sync_auto_refresh_timer_state()

    def _clear_details_panels(self, reason: str) -> None:
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

    def _on_torrent_selected(self) -> None:
        """Handle torrent selection in table."""
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

    def _display_torrent_details(self, torrent: object) -> None:
        """Display detailed information about selected torrent."""
        self._selected_torrent = cast(Any, torrent)
        self._set_details_panels_enabled(True)
        try:
            tags_list = parse_tags(getattr(torrent, "tags", None))
            tags_str = ", ".join(tags_list) if tags_list else "None"

            completion_on = getattr(torrent, "completion_on", 0)
            last_activity = getattr(torrent, "last_activity", 0)
            private_value = getattr(torrent, "private", None)
            private_str = "Yes" if private_value else ("No" if private_value is False else "N/A")
            num_files = getattr(torrent, "num_files", "N/A")
            content_path = self._display_detail_value(getattr(torrent, "content_path", None))
            tracker_url = getattr(torrent, "tracker", "") or ""
            tracker_host = self._tracker_display_text(tracker_url) or "N/A"
            eta = self._safe_int(getattr(torrent, "eta", 0), 0)
            eta_str = format_eta(eta) if eta > 0 else "N/A"
            progress_pct = self._safe_float(getattr(torrent, "progress", 0.0), 0.0) * 100.0
            ratio = self._safe_float(getattr(torrent, "ratio", 0.0), 0.0)

            sections: list[tuple[str, list[tuple[str, object]]]] = [
                (
                    "GENERAL",
                    [
                        ("Name", getattr(torrent, "name", None)),
                        ("Hash", getattr(torrent, "hash", None)),
                        ("State", getattr(torrent, "state", None)),
                        (
                            "Size",
                            format_size_mode(getattr(torrent, "size", 0), self.display_size_mode),
                        ),
                        (
                            "Total Size",
                            format_size_mode(
                                getattr(torrent, "total_size", 0), self.display_size_mode
                            ),
                        ),
                        ("Progress", f"{progress_pct:.2f}%"),
                        ("Private", private_str),
                        ("Files", num_files),
                    ],
                ),
                (
                    "TRANSFER",
                    [
                        (
                            "Downloaded",
                            format_size_mode(
                                getattr(torrent, "downloaded", 0), self.display_size_mode
                            ),
                        ),
                        (
                            "Uploaded",
                            format_size_mode(
                                getattr(torrent, "uploaded", 0), self.display_size_mode
                            ),
                        ),
                        (
                            "Download Speed",
                            format_speed_mode(
                                getattr(torrent, "dlspeed", 0), self.display_speed_mode
                            ),
                        ),
                        (
                            "Upload Speed",
                            format_speed_mode(
                                getattr(torrent, "upspeed", 0), self.display_speed_mode
                            ),
                        ),
                        ("Ratio", f"{ratio:.3f}"),
                        ("ETA", eta_str),
                    ],
                ),
                (
                    "PEERS",
                    [
                        (
                            "Seeds",
                            f"{getattr(torrent, 'num_seeds', 0)} ({getattr(torrent, 'num_complete', 0)})",
                        ),
                        (
                            "Peers",
                            f"{getattr(torrent, 'num_leechs', 0)} ({getattr(torrent, 'num_incomplete', 0)})",
                        ),
                    ],
                ),
                (
                    "METADATA",
                    [
                        ("Tracker Host", tracker_host),
                        ("Tracker URL", tracker_url or "N/A"),
                        ("Category", getattr(torrent, "category", "") or "None"),
                        ("Tags", tags_str),
                        ("Added On", format_datetime(getattr(torrent, "added_on", 0))),
                        (
                            "Completion On",
                            format_datetime(completion_on) if completion_on > 0 else "N/A",
                        ),
                        (
                            "Last Activity",
                            format_datetime(last_activity) if last_activity > 0 else "N/A",
                        ),
                        ("Save Path", getattr(torrent, "save_path", None)),
                        ("Content Path", content_path),
                    ],
                ),
            ]
            self.txt_general_details.setHtml(self._build_general_details_html(sections))
            torrent_hash = str(getattr(torrent, "hash", "") or "")
            self._load_selected_torrent_network_details(torrent_hash)
            self._populate_torrent_edit_panel(torrent)

            # Show file content from local cache
            self._show_cached_torrent_content(torrent_hash)
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error displaying torrent details: {e}")
            self.txt_general_details.setPlainText(f"Error displaying details: {e}")
            self._set_details_table_message(self.tbl_trackers, "Failed to render trackers.")
            self._set_details_table_message(self.tbl_peers, "Failed to render peers.")
            self._clear_torrent_edit_panel("Failed to load torrent for editing.")

    def _copy_torrent_hash(self) -> None:
        """Copy selected torrent hash to clipboard."""
        hashes = self._get_selected_torrent_hashes()
        if hashes:
            QApplication.clipboard().setText("\n".join(hashes))
            if len(hashes) == 1:
                self._set_status("Hash copied to clipboard")
            else:
                self._set_status(f"{len(hashes)} hashes copied to clipboard")

    def _browse_torrent_edit_save_path(self) -> None:
        """Browse for a new torrent save path."""
        initial = self.txt_torrent_edit_save_path.text().strip()
        selected = QFileDialog.getExistingDirectory(self, "Select Save Path", initial)
        if selected:
            self.txt_torrent_edit_save_path.setText(selected)

    def _browse_torrent_edit_incomplete_path(self) -> None:
        """Browse for a new torrent incomplete save path."""
        initial = self.txt_torrent_edit_incomplete_path.text().strip()
        selected = QFileDialog.getExistingDirectory(self, "Select Incomplete Save Path", initial)
        if selected:
            self.txt_torrent_edit_incomplete_path.setText(selected)

    def _collect_selected_torrent_edit_updates(self) -> dict[str, object]:
        """Collect changed edit fields for currently selected torrent."""
        original = dict(self._torrent_edit_original or {})
        updates: dict[str, object] = {}

        new_name = str(self.txt_torrent_edit_name.text() or "").strip()
        if new_name != str(original.get("name", "") or "").strip():
            updates["name"] = new_name

        auto_state = self.chk_torrent_edit_auto_tmm.checkState()
        new_auto: bool | None
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
