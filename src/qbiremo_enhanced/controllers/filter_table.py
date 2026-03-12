"""Feature controllers for MainWindow composition."""

import json
from typing import cast
from urllib.parse import urlparse

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QKeyEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QInputDialog,
    QMenu,
    QTreeWidgetItem,
)
from threep_commons.formatters import (
    format_datetime,
    format_eta,
    format_float,
    format_int,
    format_size_mode,
    format_speed_mode,
)

from ..constants import (
    BASIC_TORRENT_VIEW_KEYS,
    MEDIUM_TORRENT_VIEW_KEYS,
    SIZE_BUCKET_COUNT,
    STATUS_FILTERS,
)
from ..helpers import (
    calculate_size_buckets,
    matches_wildcard,
    normalize_filter_pattern,
    parse_tags,
)
from .base import RECOVERABLE_CONTROLLER_EXCEPTIONS, WindowControllerBase


class _StayOpenOnToggleMenu(QMenu):
    """QMenu variant that does not close after toggling checkable actions."""

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        action = self.actionAt(event.position().toPoint())
        if action is not None and action.isCheckable() and action.isEnabled():
            action.setChecked(not action.isChecked())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            action = self.activeAction()
            if action is not None and action.isCheckable() and action.isEnabled():
                action.setChecked(not action.isChecked())
                event.accept()
                return
        super().keyPressEvent(event)


class FilterTableController(WindowControllerBase):
    """Manage filter tree state and torrent table rendering."""

    def _filter_count_snapshot_signature(self) -> tuple[int, int]:
        """Return lightweight signature for current torrent snapshot."""
        torrents = self.all_torrents if isinstance(self.all_torrents, list) else []
        return (id(torrents), len(torrents))

    def _invalidate_filter_count_cache(self) -> None:
        """Invalidate cached status/category/tag count maps."""
        self._filter_count_snapshot_signature_cached = (-1, -1)
        self._status_filter_counts = {}
        self._category_filter_counts = {}
        self._tag_filter_counts = {}

    def _ensure_filter_count_cache(self) -> None:
        """Build cached status/category/tag counts for the current torrent snapshot."""
        signature = self._filter_count_snapshot_signature()
        if signature == getattr(
            self, "_filter_count_snapshot_signature_cached", (-1, -1)
        ):
            return

        torrents = self.all_torrents if isinstance(self.all_torrents, list) else []
        status_counts = dict.fromkeys(STATUS_FILTERS, 0)
        status_counts["all"] = len(torrents)
        category_counts: dict[object, int] = {None: len(torrents)}
        tag_counts: dict[object, int] = {None: len(torrents)}

        status_filters = [status for status in STATUS_FILTERS if status != "all"]
        for torrent in torrents:
            for status in status_filters:
                if self._torrent_matches_status_filter(torrent, status):
                    status_counts[status] = status_counts.get(status, 0) + 1

            category_key = str(getattr(torrent, "category", "") or "")
            category_counts[category_key] = category_counts.get(category_key, 0) + 1

            tags = parse_tags(getattr(torrent, "tags", None))
            if not tags:
                tag_counts[""] = tag_counts.get("", 0) + 1
            else:
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

        self._filter_count_snapshot_signature_cached = signature
        self._status_filter_counts = status_counts
        self._category_filter_counts = category_counts
        self._tag_filter_counts = tag_counts

    def _is_filter_item_active(self, kind: str, value: object) -> bool:
        """Return whether a filter tree item is currently active."""
        if kind == "status":
            return value == self.current_status_filter
        if kind == "category":
            return value == self.current_category_filter
        if kind == "tag":
            return value == self.current_tag_filter
        if kind == "size":
            return value == self.current_size_bucket
        if kind == "tracker":
            return value == self.current_tracker_filter
        return False

    def _refresh_filter_tree_highlights(self) -> None:
        """Highlight all currently active filters in the unified tree."""
        if not hasattr(self, "tree_filters"):
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
        """Create View -> Torrent Columns submenu with per-column visibility toggles."""
        columns_menu = _StayOpenOnToggleMenu("Torrent Colu&mns", self)
        parent_menu.addMenu(columns_menu)
        action_basic_view = QAction("&Basic View", self)
        action_basic_view.triggered.connect(self._apply_basic_torrent_view)
        columns_menu.addAction(action_basic_view)

        action_medium_view = QAction("&Medium View", self)
        action_medium_view.triggered.connect(self._apply_medium_torrent_view)
        columns_menu.addAction(action_medium_view)

        action_save_current = QAction("&Save Current View..", self)
        action_save_current.triggered.connect(self._save_current_torrent_view)
        columns_menu.addAction(action_save_current)

        self.saved_torrent_views_menu = columns_menu.addMenu("Sa&ved Views")
        self._refresh_saved_torrent_views_menu()

        columns_menu.addSeparator()
        self.column_visibility_actions = {}

        for idx, column in enumerate(self.torrent_columns):
            key = column["key"]
            action = QAction(column["label"], self)
            action.setCheckable(True)
            action.setChecked(not self.tbl_torrents.isColumnHidden(idx))
            action.toggled.connect(
                lambda checked, column_key=key: self._set_torrent_column_visible(
                    column_key, checked
                )
            )
            columns_menu.addAction(action)
            self.column_visibility_actions[key] = action

        columns_menu.addSeparator()
        action_show_all = QAction("Show &All Columns", self)
        action_show_all.triggered.connect(self._show_all_torrent_columns)
        columns_menu.addAction(action_show_all)

    def _set_torrent_column_visible(self, column_key: str, visible: bool) -> None:
        """Show or hide one torrent-table column by stable column key."""
        idx = self.torrent_column_index.get(column_key)
        if idx is None:
            return
        self.tbl_torrents.setColumnHidden(idx, not bool(visible))
        self._sync_torrent_column_actions()
        self._save_settings()

    def _show_all_torrent_columns(self) -> None:
        """Make every torrent-table column visible."""
        for idx in range(self.tbl_torrents.columnCount()):
            self.tbl_torrents.setColumnHidden(idx, False)
        self._sync_torrent_column_actions()
        self._save_settings()

    def _sync_torrent_column_actions(self) -> None:
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

    def _apply_hidden_columns_by_keys(self, hidden_keys: list[str]) -> None:
        """Apply hidden column state from stable key list."""
        hidden = {str(k) for k in hidden_keys}
        for idx, col in enumerate(self.torrent_columns):
            self.tbl_torrents.setColumnHidden(idx, col["key"] in hidden)
        self._sync_torrent_column_actions()

    def _apply_torrent_view(
        self,
        visible_keys: list[str],
        widths: dict[str, object] | None = None,
    ) -> None:
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

    def _current_torrent_view_payload(self) -> dict[str, object]:
        """Return visible columns + widths for the current torrent-table view."""
        visible_columns: list[str] = []
        widths: dict[str, int] = {}
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

    def _saved_torrent_views(self) -> dict[str, dict[str, object]]:
        """Load named torrent-table views from the settings store."""
        settings = self._new_settings()
        raw_json = settings.value("torrentColumnNamedViewsJson", "")
        if isinstance(raw_json, (bytes, bytearray)):
            raw_json = raw_json.decode("utf-8", errors="ignore")
        text = str(raw_json or "").strip()
        if not text:
            return {}

        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}

        if not isinstance(parsed, dict):
            return {}

        known_keys = set(self.torrent_column_index.keys())
        cleaned: dict[str, dict[str, object]] = {}
        for raw_name, payload in parsed.items():
            view_name = str(raw_name or "").strip()
            if not view_name or not isinstance(payload, dict):
                continue

            raw_visible = payload.get("visible_columns", [])
            visible_columns: list[str] = []
            if isinstance(raw_visible, str):
                raw_visible = [raw_visible]
            if isinstance(raw_visible, (list, tuple, set)):
                for raw_key in raw_visible:
                    key = str(raw_key or "").strip()
                    if key in known_keys:
                        visible_columns.append(key)

            raw_widths = payload.get("widths", {})
            widths: dict[str, int] = {}
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

    def _store_saved_torrent_views(self, views: dict[str, dict[str, object]]) -> None:
        """Store named torrent-table views into the settings store."""
        settings = self._new_settings()
        payload = views if isinstance(views, dict) else {}
        settings.set_value(
            "torrentColumnNamedViewsJson",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        )
        settings.sync()

    def _refresh_saved_torrent_views_menu(self) -> None:
        """Rebuild the Saved Views submenu from the settings store."""
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
                lambda _checked=False, name=view_name: self._apply_saved_torrent_view(
                    name
                )
            )
            menu.addAction(action)

    def _apply_saved_torrent_view(self, view_name: str) -> None:
        """Apply one named saved torrent-table view."""
        name = str(view_name or "").strip()
        if not name:
            return
        views = self._saved_torrent_views()
        payload = views.get(name, {})
        visible_columns = (
            payload.get("visible_columns", []) if isinstance(payload, dict) else []
        )
        widths = payload.get("widths", {}) if isinstance(payload, dict) else {}
        if not isinstance(visible_columns, list):
            self._set_status(f"Saved view is invalid: {name}")
            return
        self._apply_torrent_view(
            visible_columns, widths=widths if isinstance(widths, dict) else {}
        )
        self._set_status(f"Applied view: {name}")

    def _save_current_torrent_view(self) -> None:
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

    def _apply_basic_torrent_view(self) -> None:
        """Apply built-in Basic torrent-table view preset."""
        self._apply_torrent_view(list(BASIC_TORRENT_VIEW_KEYS))
        self._set_status("Applied view: Basic")

    def _apply_medium_torrent_view(self) -> None:
        """Apply built-in Medium torrent-table view preset."""
        self._apply_torrent_view(list(MEDIUM_TORRENT_VIEW_KEYS))
        self._set_status("Applied view: Medium")

    def _fit_torrent_columns(self) -> None:
        """Resize visible torrent table columns to fit their contents."""
        self.tbl_torrents.resizeColumnsToContents()

    def _count_status_filter_matches(self, status_filter: str) -> int:
        """Count torrents matching one status filter using current in-memory torrent list."""
        self._ensure_filter_count_cache()
        status = str(status_filter or "all").strip().lower()
        return self._safe_int(
            getattr(self, "_status_filter_counts", {}).get(status, 0), 0
        )

    def _count_category_filter_matches(self, category_filter: object) -> int:
        """Count torrents matching one category filter using current in-memory torrent list."""
        self._ensure_filter_count_cache()
        return self._safe_int(
            getattr(self, "_category_filter_counts", {}).get(category_filter, 0),
            0,
        )

    def _count_tag_filter_matches(self, tag_filter: object) -> int:
        """Count torrents matching one tag filter using current in-memory torrent list."""
        self._ensure_filter_count_cache()
        return self._safe_int(
            getattr(self, "_tag_filter_counts", {}).get(tag_filter, 0), 0
        )

    def _status_filter_item_text(self, status_filter: str) -> str:
        """Build display text for one status filter row with live torrent count."""
        status = str(status_filter or "all").strip().lower() or "all"
        label = status.replace("_", " ").title()
        count = self._count_status_filter_matches(status)
        return f"{label} ({count})"

    def _category_filter_item_text(self, category_filter: object) -> str:
        """Build display text for one category filter row with live torrent count."""
        if category_filter is None:
            label = "All"
        else:
            category_text = str(category_filter or "")
            label = category_text if category_text else "Uncategorized"
        count = self._count_category_filter_matches(category_filter)
        return f"{label} ({count})"

    def _tag_filter_item_text(self, tag_filter: object) -> str:
        """Build display text for one tag filter row with live torrent count."""
        if tag_filter is None:
            label = "All"
        else:
            tag_text = str(tag_filter or "")
            label = tag_text if tag_text else "Untagged"
        count = self._count_tag_filter_matches(tag_filter)
        return f"{label} ({count})"

    def _update_filter_tree_count_labels(self) -> None:
        """Refresh status/category/tag tree labels using latest in-memory torrent snapshot."""
        if not hasattr(self, "tree_filters"):
            return
        try:
            self._ensure_filter_count_cache()
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
                        item.setText(
                            0, self._status_filter_item_text(str(value or "all"))
                        )
                    elif kind == "category":
                        item.setText(0, self._category_filter_item_text(value))
                    elif kind == "tag":
                        item.setText(0, self._tag_filter_item_text(value))
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error updating filter tree counts: {e}")

    def _update_category_tree(self) -> None:
        """Update category section in the unified filter tree."""
        try:
            # Remove existing children
            while self._section_category.childCount():
                self._section_category.removeChild(self._section_category.child(0))

            all_item = QTreeWidgetItem([self._category_filter_item_text(None)])
            all_item.setData(0, Qt.ItemDataRole.UserRole, ("category", None))
            self._section_category.addChild(all_item)

            uncategorized = QTreeWidgetItem([self._category_filter_item_text("")])
            uncategorized.setData(0, Qt.ItemDataRole.UserRole, ("category", ""))
            self._section_category.addChild(uncategorized)

            for category in self.categories:
                item = QTreeWidgetItem([self._category_filter_item_text(category)])
                item.setData(0, Qt.ItemDataRole.UserRole, ("category", category))
                self._section_category.addChild(item)

            self._section_category.setExpanded(True)
            self._refresh_filter_tree_highlights()
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error updating category tree: {e}")

    def _update_tag_tree(self) -> None:
        """Update tag section in the unified filter tree."""
        try:
            while self._section_tag.childCount():
                self._section_tag.removeChild(self._section_tag.child(0))

            all_item = QTreeWidgetItem([self._tag_filter_item_text(None)])
            all_item.setData(0, Qt.ItemDataRole.UserRole, ("tag", None))
            self._section_tag.addChild(all_item)

            untagged = QTreeWidgetItem([self._tag_filter_item_text("")])
            untagged.setData(0, Qt.ItemDataRole.UserRole, ("tag", ""))
            self._section_tag.addChild(untagged)

            for tag in self.tags:
                item = QTreeWidgetItem([self._tag_filter_item_text(tag)])
                item.setData(0, Qt.ItemDataRole.UserRole, ("tag", tag))
                self._section_tag.addChild(item)

            self._section_tag.setExpanded(True)
            self._refresh_filter_tree_highlights()
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error updating tag tree: {e}")

    def _calculate_size_buckets(self) -> None:
        """Calculate dynamic size buckets."""
        try:
            if not self.all_torrents:
                self.size_buckets = []
                return

            sizes = [
                getattr(t, "size", 0)
                for t in self.all_torrents
                if getattr(t, "size", 0) > 0
            ]
            if not sizes:
                self.size_buckets = []
                return

            min_size = min(sizes)
            max_size = max(sizes)
            self.size_buckets = calculate_size_buckets(
                min_size, max_size, SIZE_BUCKET_COUNT
            )
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error calculating size buckets: {e}")
            self.size_buckets = []

    def _update_size_tree(self) -> None:
        """Update size section in the unified filter tree."""
        try:
            while self._section_size.childCount():
                self._section_size.removeChild(self._section_size.child(0))

            all_item = QTreeWidgetItem(["All"])
            all_item.setData(0, Qt.ItemDataRole.UserRole, ("size", None))
            self._section_size.addChild(all_item)

            for start, end in self.size_buckets:
                label = (
                    f"{format_size_mode(start, self.display_size_mode)} - "
                    f"{format_size_mode(end, self.display_size_mode)}"
                )
                item = QTreeWidgetItem([label])
                item.setData(0, Qt.ItemDataRole.UserRole, ("size", (start, end)))
                self._section_size.addChild(item)

            self._section_size.setExpanded(True)
            self._refresh_filter_tree_highlights()
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error updating size tree: {e}")

    def _extract_trackers(self) -> None:
        """Extract unique tracker hostnames from loaded torrents."""
        try:
            tracker_set = set()
            for t in self.all_torrents:
                tracker_url = getattr(t, "tracker", "") or ""
                if tracker_url:
                    try:
                        parsed = urlparse(tracker_url)
                        hostname = parsed.hostname or tracker_url
                        tracker_set.add(hostname)
                    except ValueError:
                        tracker_set.add(tracker_url)
            self.trackers = sorted(tracker_set)
        except (TypeError, ValueError, RuntimeError, AttributeError) as e:
            self._log("ERROR", f"Error extracting trackers: {e}")
            self.trackers = []

    def _update_tracker_tree(self) -> None:
        """Update tracker section in the unified filter tree."""
        try:
            while self._section_tracker.childCount():
                self._section_tracker.removeChild(self._section_tracker.child(0))

            all_item = QTreeWidgetItem(["All"])
            all_item.setData(0, Qt.ItemDataRole.UserRole, ("tracker", None))
            self._section_tracker.addChild(all_item)

            for tracker in self.trackers:
                item = QTreeWidgetItem([str(tracker)])
                item.setData(0, Qt.ItemDataRole.UserRole, ("tracker", tracker))
                self._section_tracker.addChild(item)

            self._section_tracker.setExpanded(True)
            self._refresh_filter_tree_highlights()
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error updating tracker tree: {e}")

    def _on_quick_filter_changed(self, *_args: object) -> None:
        """Apply filter-bar changes immediately."""
        self._apply_filters()

    def _on_filter_changed(self) -> None:
        """Handle filter change from filter bar."""
        # Store current filter values
        private_text = self.cmb_private.currentText()
        if private_text == "Yes":
            self.current_private_filter = cast("bool | None", True)
        elif private_text == "No":
            self.current_private_filter = cast("bool | None", False)
        else:
            self.current_private_filter = cast("bool | None", None)

        self.current_text_filter = normalize_filter_pattern(self.txt_name_filter.text())
        self.current_file_filter = normalize_filter_pattern(self.txt_file_filter.text())

    def _apply_sync_local_filters(self, torrents: list[object]) -> list[object]:
        """Apply local status/category/tag filters when sync data is unfiltered remotely."""
        filtered = torrents
        if self.current_status_filter and self.current_status_filter != "all":
            filtered = [
                torrent
                for torrent in filtered
                if self._torrent_matches_status_filter(
                    torrent, self.current_status_filter
                )
            ]
        if self.current_category_filter is not None:
            filtered = [
                torrent
                for torrent in filtered
                if self._torrent_matches_category_filter(
                    torrent, self.current_category_filter
                )
            ]
        if self.current_tag_filter is not None:
            filtered = [
                torrent
                for torrent in filtered
                if self._torrent_matches_tag_filter(torrent, self.current_tag_filter)
            ]
        return filtered

    def _apply_text_filter_to_torrents(self, torrents: list[object]) -> list[object]:
        """Apply name wildcard filter to torrent list."""
        if not self.current_text_filter:
            return torrents
        try:
            return [
                torrent
                for torrent in torrents
                if matches_wildcard(
                    getattr(torrent, "name", ""), self.current_text_filter
                )
            ]
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error applying text filter: {e}")
            return torrents

    def _apply_private_filter_to_torrents(self, torrents: list[object]) -> list[object]:
        """Apply private/public filter to torrent list."""
        if self.current_private_filter is None:
            return torrents
        try:
            return [
                torrent
                for torrent in torrents
                if bool(getattr(torrent, "private", False))
                == self.current_private_filter
            ]
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error applying private filter: {e}")
            return torrents

    def _apply_tracker_filter_to_torrents(self, torrents: list[object]) -> list[object]:
        """Apply tracker filter to torrent list."""
        if self.current_tracker_filter is None:
            return torrents
        try:
            return [
                torrent
                for torrent in torrents
                if self._torrent_matches_tracker(torrent, self.current_tracker_filter)
            ]
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error applying tracker filter: {e}")
            return torrents

    def _apply_size_filter_to_torrents(self, torrents: list[object]) -> list[object]:
        """Apply selected size bucket filter to torrent list."""
        if not self.current_size_bucket:
            return torrents
        try:
            start, end = self.current_size_bucket
            return [
                torrent
                for torrent in torrents
                if start <= getattr(torrent, "size", 0) <= end
            ]
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error applying size filter: {e}")
            return torrents

    def _apply_file_filter_to_torrents(self, torrents: list[object]) -> list[object]:
        """Apply cached file-name wildcard filter to torrent list."""
        if not self.current_file_filter:
            return torrents
        return [
            torrent
            for torrent in torrents
            if self._matches_file_filter(
                getattr(torrent, "hash", ""), self.current_file_filter
            )
        ]

    def _apply_filters(self) -> None:
        """Apply all current filters to torrents."""
        try:
            self._on_filter_changed()
            filtered = self.all_torrents[:]

            if self._sync_torrent_map and not bool(
                self._latest_torrent_fetch_remote_filtered
            ):
                filtered = self._apply_sync_local_filters(filtered)
            filtered = self._apply_text_filter_to_torrents(filtered)
            filtered = self._apply_private_filter_to_torrents(filtered)
            filtered = self._apply_tracker_filter_to_torrents(filtered)
            filtered = self._apply_size_filter_to_torrents(filtered)
            filtered = self._apply_file_filter_to_torrents(filtered)

            self.filtered_torrents = filtered
            self._update_torrents_table()
            self._log(
                "INFO", f"Filters applied: {len(self.filtered_torrents)} torrents match"
            )
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error applying filters: {e}")
            self.filtered_torrents = []
            self._update_torrents_table()

    def _torrent_matches_status_filter(
        self, torrent: object, status_filter: str
    ) -> bool:
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
                "downloading",
                "metadl",
                "forcedmetadl",
                "queueddl",
                "stalleddl",
                "checkingdl",
                "forceddl",
                "allocating",
            }
        if status == "seeding":
            return state in {
                "uploading",
                "stalledup",
                "queuedup",
                "checkingup",
                "forcedup",
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
    def _torrent_matches_category_filter(
        torrent: object, category_filter: object
    ) -> bool:
        """Match one torrent against selected category filter."""
        torrent_category = str(getattr(torrent, "category", "") or "")
        return torrent_category == str(category_filter or "")

    def _torrent_matches_tag_filter(self, torrent: object, tag_filter: object) -> bool:
        """Match one torrent against selected tag filter."""
        tag = str(tag_filter or "")
        tags = parse_tags(getattr(torrent, "tags", None))
        if tag == "":
            return len(tags) == 0
        return tag in tags

    def _clear_filters(self) -> None:
        """Clear all filters."""
        self.current_status_filter = "all"
        self._clear_non_status_filters()

        # Clear tree selection
        self.tree_filters.clearSelection()
        self._refresh_filter_tree_highlights()

        self._refresh_torrents()

    def _clear_non_status_filters(self) -> None:
        """Clear non-status torrent filters from quick bar and tree sections."""
        private_signals = self.cmb_private.blockSignals(True)
        self.cmb_private.setCurrentIndex(0)
        self.cmb_private.blockSignals(private_signals)
        self.current_private_filter = cast("bool | None", None)

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

    def _show_active_torrents_only(self) -> None:
        """Show only active torrents and clear all non-status filters."""
        self._show_status_filter_only("active")

    def _show_completed_torrents_only(self) -> None:
        """Show only completed torrents and clear all non-status filters."""
        self._show_status_filter_only("completed")

    def _show_all_torrents_only(self) -> None:
        """Show all torrents and clear all non-status filters."""
        self._show_status_filter_only("all")

    def _on_filter_tree_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Handle click on the unified filter tree."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None and item.childCount() > 0:
            # Section header clicked: just toggle expand/collapse.
            return
        try:
            if not isinstance(data, tuple):
                return
            kind, value = data
            if kind == "status":
                self.current_status_filter = value
                self._log("INFO", f"Status filter changed to: {value}")
                self._refresh_filter_tree_highlights()
                self._refresh_torrents()
            elif kind == "category":
                self.current_category_filter = value
                self._log("INFO", f"Category filter changed to: {value}")
                self._refresh_filter_tree_highlights()
                self._refresh_torrents()
            elif kind == "tag":
                self.current_tag_filter = value
                self._log("INFO", f"Tag filter changed to: {value}")
                self._refresh_filter_tree_highlights()
                self._refresh_torrents()
            elif kind == "size":
                self.current_size_bucket = value
                self._log("INFO", "Size filter changed")
                self._refresh_filter_tree_highlights()
                self._apply_filters()
            elif kind == "tracker":
                self.current_tracker_filter = value
                self._log("INFO", f"Tracker filter selected: {value}")
                self._refresh_filter_tree_highlights()
                self._apply_filters()
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error handling filter click: {e}")

    @staticmethod
    def _torrent_matches_tracker(torrent: object, tracker_hostname: str) -> bool:
        """Check if a torrent's tracker matches the given hostname."""
        tracker_url = getattr(torrent, "tracker", "") or ""
        if not tracker_url:
            return False
        try:
            parsed = urlparse(tracker_url)
            return (parsed.hostname or tracker_url) == tracker_hostname
        except ValueError:
            return tracker_url == tracker_hostname

    def _tracker_display_text(self, tracker_url: str) -> str:
        """Render tracker URL as hostname where possible."""
        text = str(tracker_url or "")
        if not text:
            return ""
        try:
            parsed = urlparse(text)
            return parsed.hostname or text
        except ValueError:
            return text

    def _format_torrent_table_cell(  # noqa: C901 - cell formatting spans all column variants
        self,
        torrent: object,
        column_key: str,
    ) -> tuple[str, Qt.AlignmentFlag, float | None]:
        """Return display text, alignment, and optional numeric sort value."""
        align_left = Qt.AlignmentFlag.AlignLeft
        align_right = Qt.AlignmentFlag.AlignRight
        align_center = Qt.AlignmentFlag.AlignCenter

        def _raw_value(key: str, default: object = None) -> object:
            """Read one attribute from torrent object with fallback."""
            return getattr(torrent, key, default)

        def _as_bool(value: object) -> bool | None:
            """Normalize bool-like values, returning None when undecidable."""
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

        if column_key in {
            "hash",
            "name",
            "state",
            "category",
            "save_path",
            "content_path",
            "magnet_uri",
        }:
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
            return (
                format_size_mode(raw, self.display_size_mode),
                align_right,
                float(raw),
            )
        if column_key == "progress":
            raw = self._safe_float(_raw_value("progress", 0), 0.0)
            return f"{raw * 100:.1f}%", align_right, float(raw)
        if column_key in {"dlspeed", "upspeed", "dl_limit", "up_limit"}:
            raw = self._safe_int(_raw_value(column_key, 0), 0)
            return (
                format_speed_mode(raw, self.display_speed_mode),
                align_right,
                float(raw),
            )
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
        if column_key in {
            "added_on",
            "completion_on",
            "last_activity",
            "seen_complete",
        }:
            raw = self._safe_int(_raw_value(column_key, 0), 0)
            return format_datetime(raw), align_left, float(raw)
        if column_key == "tags":
            tags_text = ", ".join(parse_tags(_raw_value("tags", None)))
            return tags_text, align_left, None
        if column_key == "tracker":
            tracker_text = self._tracker_display_text(
                str(_raw_value("tracker", "") or "")
            )
            return tracker_text, align_left, None
        if column_key in {
            "auto_tmm",
            "force_start",
            "seq_dl",
            "f_l_piece_prio",
            "super_seeding",
            "private",
        }:
            bool_value = _as_bool(_raw_value(column_key, None))
            if bool_value is True:
                return "Yes", align_center, 1.0
            if bool_value is False:
                return "No", align_center, 0.0
            return "", align_center, -1.0

        return str(_raw_value(column_key, "") or ""), align_left, None

    def _update_torrents_table(self) -> None:
        """Update the torrents table with filtered data."""
        table = self.tbl_torrents
        previous_sorting = table.isSortingEnabled()
        previous_table_signals = table.blockSignals(True)
        previous_updates_enabled = table.updatesEnabled()
        table.setUpdatesEnabled(False)
        selection_model = table.selectionModel()
        previous_selection_signals = False
        if selection_model is not None:
            previous_selection_signals = selection_model.blockSignals(True)
        try:
            table.setSortingEnabled(False)
            table.setRowCount(len(self.filtered_torrents))

            for row, torrent in enumerate(self.filtered_torrents):
                try:
                    for col_idx, column in enumerate(self.torrent_columns):
                        text, align, sort_value = self._format_torrent_table_cell(
                            torrent, column["key"]
                        )
                        self._set_table_item(
                            row, col_idx, text, align=align, sort_value=sort_value
                        )
                except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
                    self._log("ERROR", f"Error updating row {row}: {e}")
                    continue

            self.lbl_count.setText(f"{len(self.filtered_torrents)} torrents")
        except RECOVERABLE_CONTROLLER_EXCEPTIONS as e:
            self._log("ERROR", f"Error updating torrents table: {e}")
            self.lbl_count.setText("0 torrents")
        finally:
            table.setSortingEnabled(previous_sorting)
            if selection_model is not None:
                selection_model.blockSignals(previous_selection_signals)
            table.setUpdatesEnabled(previous_updates_enabled)
            table.blockSignals(previous_table_signals)
