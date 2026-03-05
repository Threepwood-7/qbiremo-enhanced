from types import SimpleNamespace

import qbiremo_enhanced.main_window as appmod
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


def _top_level_names(tree_widget):
    return [tree_widget.topLevelItem(i).text(0) for i in range(tree_widget.topLevelItemCount())]


def _find_filter_item(tree_widget, kind, value):
    for i in range(tree_widget.topLevelItemCount()):
        section = tree_widget.topLevelItem(i)
        for j in range(section.childCount()):
            item = section.child(j)
            if item.data(0, Qt.ItemDataRole.UserRole) == (kind, value):
                return item
    return None


def _find_menu_action(window, menu_text, action_text):
    for menu_action in window.menuBar().actions():
        if menu_action.text() != menu_text:
            continue
        menu = menu_action.menu()
        if menu is None:
            continue
        for action in menu.actions():
            if action.text() == action_text:
                return action
    return None


def _find_submenu_action(window, menu_text, submenu_text, action_text):
    for menu_action in window.menuBar().actions():
        if menu_action.text() != menu_text:
            continue
        menu = menu_action.menu()
        if menu is None:
            continue
        for action in menu.actions():
            submenu = action.menu()
            if submenu is None or action.text() != submenu_text:
                continue
            for submenu_action in submenu.actions():
                if submenu_action.text() == action_text:
                    return submenu_action
    return None


def _find_submenu(window, menu_text, submenu_text):
    for menu_action in window.menuBar().actions():
        if menu_action.text() != menu_text:
            continue
        menu = menu_action.menu()
        if menu is None:
            continue
        for action in menu.actions():
            submenu = action.menu()
            if submenu is not None and action.text() == submenu_text:
                return submenu
    return None


def _shortcut_text(action):
    text = action.shortcut().toString().lower().replace("delete", "del")
    text = text.replace("ctrl+=", "ctrl++")
    text = text.replace("ctrl+shift+=", "ctrl+shift++")
    return text


def _shortcut_key_text(shortcut):
    return shortcut.key().toString().lower().replace(" ", "")


def _tab_names(tab_widget):
    return [tab_widget.tabText(i) for i in range(tab_widget.count())]


def _table_headers(table):
    return [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]


def _table_first_cell(table):
    if table.rowCount() == 0 or table.columnCount() == 0:
        return ""
    item = table.item(0, 0)
    return item.text() if item else ""


def test_main_window_starts_maximized(window):
    assert bool(window.windowState() & Qt.WindowState.WindowMaximized)


def test_clear_cache_refresh_action_is_under_view_menu(window):
    action_in_view = _find_menu_action(window, "&View", "Clear Cache && &Refresh")
    action_in_file = _find_menu_action(window, "&File", "Clear Cache && &Refresh")

    assert action_in_view is not None
    assert _shortcut_text(action_in_view) == "ctrl+f5"
    assert action_in_file is None


def test_torrent_table_sort_shortcuts_are_registered(window):
    expected = {
        "ctrl+f1",
        "ctrl+alt+f1",
        "ctrl+f2",
        "ctrl+alt+f2",
        "ctrl+f3",
        "ctrl+alt+f3",
        "ctrl+f5",
        "ctrl+alt+f5",
        "ctrl+f6",
        "ctrl+alt+f6",
    }
    actual = {_shortcut_key_text(shortcut) for shortcut in window._torrent_sort_shortcuts}
    assert actual == expected
    assert all(
        shortcut.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
        and shortcut.parent() is window.tbl_torrents
        for shortcut in window._torrent_sort_shortcuts
    )


def test_torrent_table_sort_shortcuts_trigger_expected_columns(window, monkeypatch):
    captured = []
    monkeypatch.setattr(
        window,
        "_sort_torrents_by_column_shortcut",
        lambda column_key, default_order: captured.append((column_key, default_order)),
    )
    shortcuts_by_key = {
        _shortcut_key_text(shortcut): shortcut for shortcut in window._torrent_sort_shortcuts
    }
    expected = {
        "ctrl+f1": ("ratio", Qt.SortOrder.DescendingOrder),
        "ctrl+alt+f1": ("uploaded", Qt.SortOrder.DescendingOrder),
        "ctrl+f2": ("progress", Qt.SortOrder.DescendingOrder),
        "ctrl+alt+f2": ("eta", Qt.SortOrder.AscendingOrder),
        "ctrl+f3": ("name", Qt.SortOrder.AscendingOrder),
        "ctrl+alt+f3": ("state", Qt.SortOrder.AscendingOrder),
        "ctrl+f5": ("total_size", Qt.SortOrder.DescendingOrder),
        "ctrl+alt+f5": ("size", Qt.SortOrder.DescendingOrder),
        "ctrl+f6": ("added_on", Qt.SortOrder.DescendingOrder),
        "ctrl+alt+f6": ("completion_on", Qt.SortOrder.DescendingOrder),
    }

    assert set(shortcuts_by_key) == set(expected)
    for key_name in expected:
        shortcuts_by_key[key_name].activated.emit()
    assert captured == [expected[key_name] for key_name in expected]


def test_sort_shortcut_helper_toggles_sort_order_on_repeat(window):
    header = window.tbl_torrents.horizontalHeader()
    ratio_index = window.torrent_column_index["ratio"]

    window._sort_torrents_by_column_shortcut("ratio", Qt.SortOrder.DescendingOrder)
    assert header.sortIndicatorSection() == ratio_index
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder

    window._sort_torrents_by_column_shortcut("ratio", Qt.SortOrder.DescendingOrder)
    assert header.sortIndicatorSection() == ratio_index
    assert header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder


def test_view_menu_contains_human_readable_toggle(window):
    action = _find_menu_action(window, "&View", "&Human Readable")
    assert action is not None
    assert action.isCheckable()
    assert action.isChecked() is True


def test_view_menu_contains_fit_columns_action(window):
    action = _find_menu_action(window, "&View", "Fit &Columns")
    assert action is not None


def test_view_menu_contains_status_shortcut_actions(window):
    expected_actions = [
        ("Show &Active Torrents", "F6"),
        ("Show &Complete Torrents", "F7"),
        ("Show &All Torrents", "F8"),
    ]

    for text, shortcut in expected_actions:
        action = _find_menu_action(window, "&View", text)
        assert action is not None
        assert _shortcut_text(action) == shortcut.lower()


def test_status_shortcut_actions_clear_non_status_filters(window, monkeypatch):
    refresh_calls = {"count": 0}
    monkeypatch.setattr(
        window,
        "_refresh_torrents",
        lambda: refresh_calls.__setitem__("count", refresh_calls["count"] + 1),
    )

    expected = [
        ("Show &Active Torrents", "active"),
        ("Show &Complete Torrents", "completed"),
        ("Show &All Torrents", "all"),
    ]

    for expected_calls, (action_text, expected_status) in enumerate(expected, start=1):
        window.cmb_private.setCurrentText("Yes")
        window.txt_name_filter.setText("ubuntu")
        window.txt_file_filter.setText("*.mkv")
        window.current_private_filter = True
        window.current_category_filter = "movies"
        window.current_tag_filter = "tag1"
        window.current_size_bucket = (1, 2)
        window.current_tracker_filter = "tracker.example"

        action = _find_menu_action(window, "&View", action_text)
        assert action is not None
        action.trigger()

        assert window.current_status_filter == expected_status
        assert window.cmb_private.currentText() == "All"
        assert window.txt_name_filter.text() == ""
        assert window.txt_file_filter.text() == ""
        assert window.current_private_filter is None
        assert window.current_category_filter is None
        assert window.current_tag_filter is None
        assert window.current_size_bucket is None
        assert window.current_tracker_filter is None
        assert refresh_calls["count"] == expected_calls


def test_fit_columns_action_triggers_fit_method(window, monkeypatch):
    calls = {"count": 0}
    monkeypatch.setattr(
        window, "_fit_torrent_columns", lambda: calls.__setitem__("count", calls["count"] + 1)
    )

    action = _find_menu_action(window, "&View", "Fit &Columns")
    assert action is not None

    action.trigger()
    assert calls["count"] == 1


def test_torrent_table_includes_extended_columns(window):
    labels = [
        window.tbl_torrents.horizontalHeaderItem(i).text()
        for i in range(window.tbl_torrents.columnCount())
    ]

    for required in [
        "Total Size",
        "Downloaded",
        "Uploaded",
        "Complete",
        "Incomplete",
        "ETA",
        "Completed On",
        "Last Activity",
        "Tracker",
        "Private",
        "Files",
        "Save Path",
        "Content Path",
    ]:
        assert required in labels


def test_torrent_columns_include_all_torrents_info_api_fields(window):
    expected_keys = {
        "added_on",
        "amount_left",
        "auto_tmm",
        "availability",
        "category",
        "completed",
        "completion_on",
        "content_path",
        "dl_limit",
        "dlspeed",
        "downloaded",
        "downloaded_session",
        "eta",
        "f_l_piece_prio",
        "force_start",
        "hash",
        "private",
        "last_activity",
        "magnet_uri",
        "max_ratio",
        "max_seeding_time",
        "name",
        "num_complete",
        "num_incomplete",
        "num_leechs",
        "num_seeds",
        "priority",
        "progress",
        "ratio",
        "ratio_limit",
        "reannounce",
        "save_path",
        "seeding_time",
        "seeding_time_limit",
        "seen_complete",
        "seq_dl",
        "size",
        "state",
        "super_seeding",
        "tags",
        "time_active",
        "total_size",
        "tracker",
        "up_limit",
        "uploaded",
        "uploaded_session",
        "upspeed",
    }
    present_keys = {col["key"] for col in window.torrent_columns}
    assert expected_keys.issubset(present_keys)


def test_torrent_table_defaults_to_medium_view_columns(window):
    visible = {
        col["key"]
        for idx, col in enumerate(window.torrent_columns)
        if not window.tbl_torrents.isColumnHidden(idx)
    }
    assert visible == set(appmod.MEDIUM_TORRENT_VIEW_KEYS)


def test_view_menu_column_toggles_hide_and_show_columns(window):
    tracker_index = window.torrent_column_index["tracker"]
    assert not window.tbl_torrents.isColumnHidden(tracker_index)

    tracker_action = _find_submenu_action(window, "&View", "Torrent &Columns", "Tracker")
    assert tracker_action is not None
    assert tracker_action.isCheckable()
    assert tracker_action.isChecked() is True

    tracker_action.setChecked(False)
    assert window.tbl_torrents.isColumnHidden(tracker_index)

    tracker_action.setChecked(True)
    assert not window.tbl_torrents.isColumnHidden(tracker_index)


def test_torrent_columns_menu_stays_open_when_toggling_column(window, qtbot):
    columns_menu = _find_submenu(window, "&View", "Torrent &Columns")
    tracker_action = _find_submenu_action(window, "&View", "Torrent &Columns", "Tracker")

    assert columns_menu is not None
    assert tracker_action is not None

    columns_menu.popup(window.mapToGlobal(window.rect().center()))
    qtbot.waitUntil(columns_menu.isVisible)

    prev_checked = tracker_action.isChecked()
    action_rect = columns_menu.actionGeometry(tracker_action)
    QTest.mouseClick(
        columns_menu,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        action_rect.center(),
    )

    assert tracker_action.isChecked() is (not prev_checked)
    assert columns_menu.isVisible()
    columns_menu.hide()


def test_torrent_columns_menu_contains_view_management_actions(window):
    assert _find_submenu_action(window, "&View", "Torrent &Columns", "Basic View") is not None
    assert _find_submenu_action(window, "&View", "Torrent &Columns", "Medium View") is not None
    assert (
        _find_submenu_action(window, "&View", "Torrent &Columns", "Save Current View..") is not None
    )
    saved_views_action = _find_submenu_action(window, "&View", "Torrent &Columns", "Saved Views")
    assert saved_views_action is not None
    assert saved_views_action.menu() is not None


def test_basic_view_action_applies_expected_columns(window):
    action = _find_submenu_action(window, "&View", "Torrent &Columns", "Basic View")
    assert action is not None

    action.trigger()
    visible = {
        col["key"]
        for idx, col in enumerate(window.torrent_columns)
        if not window.tbl_torrents.isColumnHidden(idx)
    }
    assert visible == set(appmod.BASIC_TORRENT_VIEW_KEYS)


def test_medium_view_action_applies_expected_columns(window):
    action = _find_submenu_action(window, "&View", "Torrent &Columns", "Medium View")
    assert action is not None

    action.trigger()
    visible = {
        col["key"]
        for idx, col in enumerate(window.torrent_columns)
        if not window.tbl_torrents.isColumnHidden(idx)
    }
    assert visible == set(appmod.MEDIUM_TORRENT_VIEW_KEYS)


def test_save_current_view_persists_only_visible_columns_and_widths(window, monkeypatch, tmp_path):
    appmod.QSettings.setDefaultFormat(appmod.QSettings.Format.IniFormat)
    appmod.QSettings.setPath(
        appmod.QSettings.Format.IniFormat,
        appmod.QSettings.Scope.UserScope,
        str(tmp_path / "qsettings"),
    )
    settings = window._new_settings()
    settings.clear()
    settings.sync()

    window._set_torrent_column_visible("tracker", False)
    name_idx = window.torrent_column_index["name"]
    window.tbl_torrents.setColumnWidth(name_idx, 333)
    monkeypatch.setattr(appmod.QInputDialog, "getText", lambda *args, **kwargs: ("My View", True))

    window._save_current_torrent_view()

    settings = window._new_settings()
    raw_json = str(settings.value("torrentColumnNamedViewsJson", "") or "")
    payload = appmod.json.loads(raw_json)["My View"]
    assert set(payload.keys()) == {"visible_columns", "widths"}
    assert "tracker" not in payload["visible_columns"]
    assert "tracker" not in payload["widths"]
    assert payload["widths"]["name"] == 333

    window._show_all_torrent_columns()
    window.tbl_torrents.setColumnWidth(name_idx, 120)
    window._apply_saved_torrent_view("My View")

    assert window.tbl_torrents.isColumnHidden(window.torrent_column_index["tracker"])
    assert window.tbl_torrents.columnWidth(name_idx) == 333

    assert window.saved_torrent_views_menu is not None
    assert any(action.text() == "My View" for action in window.saved_torrent_views_menu.actions())


def test_torrent_table_allows_multi_selection(window):
    assert (
        window.tbl_torrents.selectionMode()
        == appmod.QAbstractItemView.SelectionMode.ExtendedSelection
    )


def test_torrent_table_has_no_custom_context_menu(window):
    assert window.tbl_torrents.contextMenuPolicy() == appmod.Qt.ContextMenuPolicy.DefaultContextMenu


def test_torrent_table_cells_are_not_editable(window):
    assert window.tbl_torrents.editTriggers() == appmod.QAbstractItemView.EditTrigger.NoEditTriggers


def test_tools_menu_contains_clipboard_monitor_toggle(window):
    action_clipboard = _find_menu_action(window, "&Tools", "Enable &Clipboard Monitor")
    action_debug_logging = _find_menu_action(window, "&Tools", "Enable &Debug logging")
    action_edit_ini = _find_menu_action(window, "&Tools", "&Edit .ini file")
    action_edit_app_preferences = _find_menu_action(window, "&Tools", "Edit App Preferences")
    action_edit_add_preferences_friendly = _find_menu_action(
        window, "&Tools", "Edit Add Preferences (friendly)"
    )
    action_open_web_ui = _find_menu_action(window, "&Tools", "Open Web UI in browser")
    action_speed_limits = _find_menu_action(window, "&Tools", "Manage &Speed Limits...")
    action_manage_taxonomy = _find_menu_action(window, "&Tools", "Manage Tags and Categories")
    action_tracker_health = _find_menu_action(window, "&Tools", "Tracker &Health Dashboard...")
    action_session_timeline = _find_menu_action(window, "&Tools", "Session &Timeline...")
    assert action_clipboard is not None
    assert action_clipboard.isCheckable()
    assert action_debug_logging is not None
    assert action_debug_logging.isCheckable()
    assert action_edit_ini is not None
    assert action_edit_app_preferences is not None
    assert action_edit_add_preferences_friendly is not None
    assert action_open_web_ui is not None
    assert action_speed_limits is not None
    assert action_manage_taxonomy is not None
    assert action_tracker_health is not None
    assert action_session_timeline is not None


def test_open_web_ui_action_opens_expected_url(window, monkeypatch):
    opened = {"url": None}
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda path: opened.__setitem__("url", path),
    )

    window.qb_conn_info["username"] = "alice"
    window.config["qb_host"] = "https://httpuser:httppass@qb.example.com:9443"
    window.config["qb_port"] = 8080

    action_open_web_ui = _find_menu_action(window, "&Tools", "Open Web UI in browser")
    assert action_open_web_ui is not None
    action_open_web_ui.trigger()

    assert opened["url"] == "https://alice@qb.example.com:9443"


def test_open_web_ui_action_uses_configured_http_protocol_scheme(window, monkeypatch):
    opened = {"url": None}
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda path: opened.__setitem__("url", path),
    )

    window.qb_conn_info["username"] = "alice"
    window.config["qb_host"] = "qb.example.com"
    window.config["qb_port"] = 38081
    window.config["http_protocol_scheme"] = "http"

    action_open_web_ui = _find_menu_action(window, "&Tools", "Open Web UI in browser")
    assert action_open_web_ui is not None
    action_open_web_ui.trigger()

    assert opened["url"] == "http://alice@qb.example.com:38081"


def test_web_ui_browser_url_encodes_username_and_brackets_ipv6_host(window):
    window.qb_conn_info["username"] = "alice+bob@example"
    window.config["qb_host"] = "2001:db8::10"
    window.config["qb_port"] = 8080
    window.config["http_protocol_scheme"] = "https"

    url = window._web_ui_browser_url()

    assert url == "https://alice%2Bbob%40example@[2001:db8::10]:8080"


def test_file_menu_exit_action_supports_alt_x_shortcut(window):
    action_exit = _find_menu_action(window, "&File", "E&xit")
    assert action_exit is not None
    shortcuts = {seq.toString().lower().replace(" ", "") for seq in action_exit.shortcuts()}
    assert "ctrl+q" in shortcuts
    assert "alt+x" in shortcuts


def test_file_menu_contains_export_torrent_action(window):
    action_export = _find_menu_action(window, "&File", "&Export Torrent...")
    assert action_export is not None


def test_show_add_torrent_dialog_is_modeless_top_level_window(window, qtbot):
    window._show_add_torrent_dialog()

    dialog = window._add_torrent_dialog
    assert dialog is not None
    assert dialog.windowModality() == appmod.Qt.WindowModality.NonModal
    assert dialog.isModal() is False
    assert bool(dialog.windowFlags() & appmod.Qt.WindowType.Window)
    assert dialog.windowType() == appmod.Qt.WindowType.Window

    dialog.close()
    qtbot.waitUntil(lambda: window._add_torrent_dialog is None)


def test_show_add_torrent_dialog_reuses_existing_visible_dialog(window, qtbot):
    window._show_add_torrent_dialog()
    first = window._add_torrent_dialog
    assert first is not None

    window._show_add_torrent_dialog()
    assert window._add_torrent_dialog is first

    first.close()
    qtbot.waitUntil(lambda: window._add_torrent_dialog is None)


def test_add_torrent_dialog_accept_queues_api_task(window, monkeypatch, qtbot):
    captured = {}
    monkeypatch.setattr(window, "_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(window, "_show_progress", lambda *_args, **_kwargs: None)

    def _fake_add_task(task_name, api_method, callback, *args):
        captured["task_name"] = task_name
        captured["api_method_name"] = getattr(api_method, "__name__", "")
        captured["callback"] = callback
        captured["args"] = args

    monkeypatch.setattr(window.api_queue, "add_task", _fake_add_task)

    window._show_add_torrent_dialog()
    dialog = window._add_torrent_dialog
    assert dialog is not None
    monkeypatch.setattr(dialog, "get_torrent_data", lambda: {"urls": ["magnet:?xt=urn:btih:aaa"]})

    dialog.accept()

    assert captured["task_name"] == "add_torrent"
    assert captured["api_method_name"] == "_add_torrent_api"
    assert callable(captured["callback"])
    assert captured["args"] == ({"urls": ["magnet:?xt=urn:btih:aaa"]},)
    qtbot.waitUntil(lambda: window._add_torrent_dialog is None)


def test_file_menu_contains_new_instance_actions(window):
    action_new_instance = _find_menu_action(window, "&File", "New &instance")
    action_new_instance_from_config = _find_menu_action(
        window, "&File", "New instance from con&fig..."
    )

    assert action_new_instance is not None
    assert _shortcut_text(action_new_instance) == "ctrl+shift+n"
    assert action_new_instance_from_config is not None


def test_new_instance_action_uses_current_config_and_counter(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window,
        "_launch_new_instance_with_config_path",
        lambda config_path, instance_counter=None: calls.append((config_path, instance_counter)),
    )
    window.config["_config_file_path"] = "C:/cfg/current.toml"
    window.config["_instance_counter"] = 4

    action_new_instance = _find_menu_action(window, "&File", "New &instance")
    assert action_new_instance is not None
    action_new_instance.trigger()

    assert calls == [("C:/cfg/current.toml", 4)]


def test_new_instance_from_config_action_prompts_and_launches(window, monkeypatch, tmp_path):
    selected_config = tmp_path / "second.toml"
    selected_config.write_text("qb_host='localhost'\n", encoding="utf-8")
    calls = []

    monkeypatch.setattr(
        appmod.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(selected_config), "TOML files (*.toml)"),
    )
    monkeypatch.setattr(
        window,
        "_launch_new_instance_with_config_path",
        lambda config_path, instance_counter=None: calls.append((config_path, instance_counter)),
    )

    action_new_instance_from_config = _find_menu_action(
        window, "&File", "New instance from con&fig..."
    )
    assert action_new_instance_from_config is not None
    action_new_instance_from_config.trigger()

    assert calls == [(str(selected_config), 1)]


def test_launch_new_instance_with_config_path_spawns_process(window, monkeypatch, tmp_path):
    config_path = tmp_path / "launch.toml"
    config_path.write_text("qb_host='localhost'\n", encoding="utf-8")
    captured = {"cmd": None}

    monkeypatch.setattr(
        appmod.subprocess,
        "Popen",
        lambda cmd: captured.__setitem__("cmd", list(cmd)),
    )

    window._launch_new_instance_with_config_path(str(config_path), 7)

    assert captured["cmd"] is not None
    assert captured["cmd"][0] == appmod.sys.executable
    assert captured["cmd"][1:4] == ["-m", "qbiremo_enhanced", "--config-file"]
    assert captured["cmd"][4] == str(config_path.resolve())
    assert captured["cmd"][5:] == ["--instance_counter", "7"]


def test_export_selected_torrents_queues_api_task(window, monkeypatch, tmp_path):
    window.all_torrents = [
        SimpleNamespace(hash="h1", name="Ubuntu ISO"),
        SimpleNamespace(hash="h2", name="Arch Linux"),
    ]
    monkeypatch.setattr(window, "_get_selected_torrent_hashes", lambda: ["h1", "h2"])
    monkeypatch.setattr(
        appmod.QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    captured = {}

    def _fake_add_task(task_name, api_method, callback, *args):
        captured["task_name"] = task_name
        captured["api_method_name"] = getattr(api_method, "__name__", "")
        captured["callback"] = callback
        captured["args"] = args

    monkeypatch.setattr(window.api_queue, "add_task", _fake_add_task)

    window._export_selected_torrents()

    assert captured["task_name"] == "export_selected_torrents"
    assert captured["api_method_name"] == "_api_export_torrents"
    assert callable(captured["callback"])
    assert captured["args"][0] == ["h1", "h2"]
    assert captured["args"][1] == str(tmp_path)
    assert captured["args"][2] == {"h1": "Ubuntu ISO", "h2": "Arch Linux"}


def test_api_export_torrents_writes_selected_torrent_files(window, monkeypatch, tmp_path):
    class FakeClient:
        def __init__(self):
            self.exported_hashes = []

        def auth_log_in(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def torrents_export(self, torrent_hash=None, **_kwargs):
            self.exported_hashes.append(torrent_hash)
            return f"payload-{torrent_hash}".encode()

    fake_client = FakeClient()
    monkeypatch.setattr(window, "_create_client", lambda: fake_client)

    result = window._api_export_torrents(
        ["h1", "h2"],
        str(tmp_path),
        {"h1": "Ubuntu ISO", "h2": "Arch Linux"},
    )

    assert result["success"] is True
    exported = result["data"]["exported"]
    assert len(exported) == 2
    assert fake_client.exported_hashes == ["h1", "h2"]
    for path_str in exported:
        path_obj = appmod.Path(path_str)
        assert path_obj.exists()
        assert path_obj.suffix == ".torrent"
        assert path_obj.read_bytes().startswith(b"payload-")


def test_add_torrent_api_supports_urls_and_multiple_file_sources(window, monkeypatch, tmp_path):
    file_one = tmp_path / "a.torrent"
    file_two = tmp_path / "b.torrent"
    file_one.write_bytes(b"one")
    file_two.write_bytes(b"two")

    class FakeClient:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def torrents_add(self, **kwargs):
            record = dict(kwargs)
            torrent_file = record.get("torrent_files")
            if torrent_file is not None:
                record["torrent_files"] = getattr(torrent_file, "name", "")
            self.calls.append(record)
            return "Ok."

    fake_client = FakeClient()
    monkeypatch.setattr(window, "_create_client", lambda: fake_client)

    result = window._add_torrent_api(
        {
            "save_path": str(tmp_path),
            "urls": ["magnet:?xt=urn:btih:aaa", "https://example.org/file.torrent"],
            "torrent_files": [str(file_one), str(file_two)],
        }
    )

    assert result["success"] is True
    assert result["data"] is True
    assert len(fake_client.calls) == 3

    url_call = fake_client.calls[0]
    assert url_call["urls"] == ["magnet:?xt=urn:btih:aaa", "https://example.org/file.torrent"]
    assert url_call["save_path"] == str(tmp_path)
    assert "torrent_files" not in url_call

    file_calls = fake_client.calls[1:]
    assert [call["torrent_files"] for call in file_calls] == [str(file_one), str(file_two)]
    assert all(call["save_path"] == str(tmp_path) for call in file_calls)
    assert all("urls" not in call for call in file_calls)


def test_on_add_torrent_complete_reports_partial_success(window, monkeypatch):
    calls = {"refresh_delay": None}
    monkeypatch.setattr(
        appmod.QTimer,
        "singleShot",
        lambda delay_ms, _fn: calls.__setitem__("refresh_delay", int(delay_ms)),
    )

    window._on_add_torrent_complete(
        {
            "success": True,
            "data": False,
            "elapsed": 0.2,
            "details": {
                "added_urls": 1,
                "added_files": 0,
                "failed_sources": [{"source": "file.torrent", "error": "boom"}],
            },
        }
    )

    assert window.lbl_status.text() == "Added 1 sources, 1 failed"
    assert calls["refresh_delay"] == 1000


def test_tools_menu_contains_manage_tags_and_categories_action(window):
    action = _find_menu_action(window, "&Tools", "Manage Tags and Categories")
    assert action is not None
