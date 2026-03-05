import logging

import qbiremo_enhanced.main_window as appmod
from PySide6.QtCore import Qt
from qbiremo_enhanced.widgets import NumericTableWidgetItem


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


def _shortcut_text(action):
    text = action.shortcut().toString().lower().replace("delete", "del")
    text = text.replace("ctrl+=", "ctrl++")
    text = text.replace("ctrl+shift+=", "ctrl+shift++")
    return text


def _tab_names(tab_widget):
    return [tab_widget.tabText(i) for i in range(tab_widget.count())]


def _table_headers(table):
    return [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]


def _table_first_cell(table):
    if table.rowCount() == 0 or table.columnCount() == 0:
        return ""
    item = table.item(0, 0)
    return item.text() if item else ""


def test_update_torrents_table_reuses_items_and_updates_numeric_sort_values(
    window, monkeypatch, make_torrent
):
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )

    name_col = window.torrent_column_index["name"]
    dlspeed_col = window.torrent_column_index["dlspeed"]
    private_col = window.torrent_column_index["private"]

    window.filtered_torrents = [
        make_torrent(hash="h1", name="Old Name", dlspeed=100, private=False),
    ]
    window._update_torrents_table()

    name_item_before = window.tbl_torrents.item(0, name_col)
    dlspeed_item_before = window.tbl_torrents.item(0, dlspeed_col)
    private_item_before = window.tbl_torrents.item(0, private_col)
    old_speed_text = dlspeed_item_before.text() if dlspeed_item_before else ""

    window.filtered_torrents = [
        make_torrent(hash="h1", name="New Name", dlspeed=250, private=True),
    ]
    window._update_torrents_table()

    name_item_after = window.tbl_torrents.item(0, name_col)
    dlspeed_item_after = window.tbl_torrents.item(0, dlspeed_col)
    private_item_after = window.tbl_torrents.item(0, private_col)

    assert name_item_after is name_item_before
    assert dlspeed_item_after is dlspeed_item_before
    assert private_item_after is private_item_before

    assert name_item_after.text() == "New Name"
    assert dlspeed_item_after.text() != old_speed_text
    assert isinstance(dlspeed_item_after, NumericTableWidgetItem)
    assert dlspeed_item_after.sort_value() == 250.0
    assert isinstance(private_item_after, NumericTableWidgetItem)
    assert private_item_after.sort_value() == 1.0


def test_toggle_debug_logging_updates_state_and_persists(window, monkeypatch):
    calls = {"count": 0}
    monkeypatch.setattr(
        window, "_save_settings", lambda: calls.__setitem__("count", calls["count"] + 1)
    )

    window._toggle_debug_logging(True)
    assert window.debug_logging_enabled is True

    window._toggle_debug_logging(False)
    assert window.debug_logging_enabled is False
    assert calls["count"] == 2


def test_debug_logging_logs_api_calls_and_responses(window, monkeypatch, caplog):
    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def auth_log_in(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def torrents_info(self, **kwargs):
            return {"ok": True, "kwargs": dict(kwargs)}

    monkeypatch.setattr(appmod.qbittorrentapi, "Client", FakeClient)
    window.debug_logging_enabled = True
    caplog.set_level(logging.DEBUG, logger=appmod.G_APP_NAME)

    with window._create_client() as qb:
        result = qb.torrents_info(status_filter="all")

    assert result["ok"] is True
    log_text = caplog.text
    assert "[API CALL] auth_log_in" in log_text
    assert "[API RESP] auth_log_in" in log_text
    assert "[API CALL] torrents_info" in log_text
    assert "[API RESP] torrents_info" in log_text


def test_debug_logging_does_not_truncate_api_responses(window, monkeypatch, caplog):
    payload = "x" * 3005

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def auth_log_in(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def torrents_info(self, **_kwargs):
            return {"payload": payload}

    monkeypatch.setattr(appmod.qbittorrentapi, "Client", FakeClient)
    window.debug_logging_enabled = True
    caplog.set_level(logging.DEBUG, logger=appmod.G_APP_NAME)

    with window._create_client() as qb:
        result = qb.torrents_info()

    assert result["payload"] == payload
    response_lines = [
        line for line in caplog.text.splitlines() if "[API RESP] torrents_info" in line
    ]
    assert response_lines
    assert payload in response_lines[0]
    assert "...<truncated>" not in response_lines[0]


def test_qsettings_are_forced_to_ini_backend(window):
    appmod.QSettings.setDefaultFormat(appmod.QSettings.Format.NativeFormat)
    settings = window._new_settings()
    assert settings.format() == appmod.QSettings.Format.IniFormat
    assert settings.fileName().lower().endswith(".ini")


def test_edit_ini_file_action_opens_settings_file(window, monkeypatch, tmp_path):
    opened = {"path": None}
    monkeypatch.setattr(
        appmod, "_open_file_in_default_app", lambda p: opened.__setitem__("path", p)
    )
    monkeypatch.setattr(window, "_settings_ini_path", lambda: tmp_path / "qBiremoEnhanced.ini")

    window._edit_settings_ini_file()

    assert opened["path"] is not None
    assert opened["path"].lower().endswith(".ini")


def test_edit_menu_contains_requested_actions_and_shortcuts(window):
    expected_actions = [
        ("&Start", "Ctrl+S"),
        ("Sto&p", "Ctrl+P"),
        ("&Force Start", "Ctrl+M"),
        ("Re&check", "Ctrl+R"),
        ("&Increase Priority in Queue", "Ctrl++"),
        ("&Decrease Priority in Queue", "Ctrl+-"),
        ("&Top Priority in Queue", "Ctrl+Shift++"),
        ("Mi&nimum Priority in Queue", "Ctrl+Shift+-"),
        ("Remo&ve", "Del"),
        ("Remove and De&lete Data", "Shift+Del"),
        ("Remove (no confirmation)", "Ctrl+Del"),
        ("Remove and Delete Data (no confirmation)", "Ctrl+Shift+Del"),
        ("Pause Sessio&n", "Ctrl+Shift+P"),
        ("Resu&me Session", "Ctrl+Shift+S"),
    ]

    for text, shortcut in expected_actions:
        action = _find_menu_action(window, "&Edit", text)
        assert action is not None
        assert _shortcut_text(action) == shortcut.lower().replace("delete", "del")

    assert _find_menu_action(window, "&Edit", "Set Torrent &Download Limit...") is None
    assert _find_menu_action(window, "&Edit", "Set Torrent &Upload Limit...") is None


def test_edit_menu_remove_actions_use_expected_delete_mode(window, monkeypatch):
    monkeypatch.setattr(window, "_get_selected_torrent_hashes", lambda: ["h1", "h2"])
    monkeypatch.setattr(
        appmod.QMessageBox,
        "question",
        lambda *args, **kwargs: appmod.QMessageBox.StandardButton.Yes,
    )

    calls = []
    monkeypatch.setattr(
        window,
        "_queue_delete_torrents",
        lambda torrent_hashes, delete_files, action_name, progress_text: calls.append(
            (torrent_hashes, delete_files, action_name, progress_text)
        ),
    )

    window._remove_torrent()
    window._remove_torrent_and_delete_data()

    assert calls == [
        (["h1", "h2"], False, "Remove", "Removing 2 torrents..."),
        (["h1", "h2"], True, "Remove + Delete Data", "Removing 2 torrents and deleting data..."),
    ]


def test_edit_menu_no_confirmation_remove_actions_skip_prompt(window, monkeypatch):
    monkeypatch.setattr(window, "_get_selected_torrent_hashes", lambda: ["h1", "h2"])
    monkeypatch.setattr(
        appmod.QMessageBox,
        "question",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("confirmation should not be called")
        ),
    )

    calls = []
    monkeypatch.setattr(
        window,
        "_queue_delete_torrents",
        lambda torrent_hashes, delete_files, action_name, progress_text: calls.append(
            (torrent_hashes, delete_files, action_name, progress_text)
        ),
    )

    window._remove_torrent_no_confirmation()
    window._remove_torrent_and_delete_data_no_confirmation()

    assert calls == [
        (["h1", "h2"], False, "Remove (No Confirmation)", "Removing 2 torrents..."),
        (
            ["h1", "h2"],
            True,
            "Remove + Delete Data (No Confirmation)",
            "Removing 2 torrents and deleting data...",
        ),
    ]


def test_edit_menu_pause_resume_session_queue_tasks(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, fn)),
    )

    window._pause_session()
    window._resume_session()

    assert calls[0][0] == "pause_session"
    assert calls[0][1] == window._api_pause_session
    assert calls[1][0] == "resume_session"
    assert calls[1][1] == window._api_resume_session


def test_pause_resume_actions_apply_to_all_selected_hashes(window, monkeypatch):
    monkeypatch.setattr(window, "_get_selected_torrent_hashes", lambda: ["h1", "h2", "h3"])
    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, fn, args)),
    )

    window._pause_torrent()
    window._resume_torrent()

    assert calls[0][0] == "pause_torrent"
    assert calls[0][1] == window._api_pause_torrent
    assert calls[0][2][0] == ["h1", "h2", "h3"]
    assert calls[1][0] == "resume_torrent"
    assert calls[1][1] == window._api_resume_torrent
    assert calls[1][2][0] == ["h1", "h2", "h3"]


def test_force_recheck_and_priority_actions_apply_to_all_selected_hashes(window, monkeypatch):
    monkeypatch.setattr(window, "_get_selected_torrent_hashes", lambda: ["h1", "h2"])
    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, fn, args)),
    )

    window._force_start_torrent()
    window._recheck_torrent()
    window._increase_torrent_priority()
    window._decrease_torrent_priority()
    window._top_torrent_priority()
    window._minimum_torrent_priority()

    expected = [
        ("force_start_torrent", window._api_force_start_torrent),
        ("recheck_torrent", window._api_recheck_torrent),
        ("increase_torrent_priority", window._api_increase_torrent_priority),
        ("decrease_torrent_priority", window._api_decrease_torrent_priority),
        ("top_torrent_priority", window._api_top_torrent_priority),
        ("minimum_torrent_priority", window._api_minimum_torrent_priority),
    ]
    assert [(name, fn) for name, fn, _ in calls] == expected
    assert all(args[0] == ["h1", "h2"] for _, _, args in calls)


def test_content_panel_contains_priority_and_rename_actions(window, qtbot, monkeypatch):
    assert _find_submenu_action(window, "&Edit", "Con&tent", "&Skip") is None

    assert window.btn_content_skip.text() == "Skip"
    assert window.btn_content_normal.text() == "Normal Priority"
    assert window.btn_content_high.text() == "High Priority"
    assert window.btn_content_max.text() == "Maximum Priority"
    assert window.btn_content_rename.text() == "Rename..."

    priority_calls = []
    rename_calls = {"count": 0}
    monkeypatch.setattr(
        window,
        "_set_selected_content_priority",
        lambda priority: priority_calls.append(int(priority)),
    )
    monkeypatch.setattr(
        window,
        "_rename_selected_content_item",
        lambda: rename_calls.__setitem__("count", rename_calls["count"] + 1),
    )

    qtbot.mouseClick(window.btn_content_skip, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.btn_content_normal, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.btn_content_high, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.btn_content_max, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.btn_content_rename, Qt.MouseButton.LeftButton)

    assert priority_calls == [0, 1, 6, 7]
    assert rename_calls["count"] == 1


def test_set_torrent_download_limit_queues_selected_hashes_and_converts_kib(window, monkeypatch):
    monkeypatch.setattr(window, "_get_selected_torrent_hashes", lambda: ["h1", "h2"])
    monkeypatch.setattr(appmod.QInputDialog, "getInt", lambda *args, **kwargs: (128, True))

    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, fn, args)),
    )

    window._set_torrent_download_limit()

    assert calls[0][0] == "set_torrent_download_limit"
    assert calls[0][1] == window._api_set_torrent_download_limit
    assert calls[0][2][0] == ["h1", "h2"]
    assert calls[0][2][1] == 128 * 1024


def test_set_torrent_upload_limit_queues_selected_hashes_and_converts_kib(window, monkeypatch):
    monkeypatch.setattr(window, "_get_selected_torrent_hashes", lambda: ["h1"])
    monkeypatch.setattr(appmod.QInputDialog, "getInt", lambda *args, **kwargs: (64, True))

    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, fn, args)),
    )

    window._set_torrent_upload_limit()

    assert calls[0][0] == "set_torrent_upload_limit"
    assert calls[0][1] == window._api_set_torrent_upload_limit
    assert calls[0][2][0] == ["h1"]
    assert calls[0][2][1] == 64 * 1024


def test_show_speed_limits_manager_dialog_queues_profile_load(window, monkeypatch, qtbot):
    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, fn, args)),
    )

    window._show_speed_limits_manager()
    dialog = window._speed_limits_dialog
    assert dialog is not None
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Manage Speed Limits"

    assert calls[0][0] == "fetch_speed_limits_profile"
    assert calls[0][1] == window._api_fetch_speed_limits_profile


def test_show_friendly_add_preferences_dialog_queues_preferences_load(window, monkeypatch, qtbot):
    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, fn, args)),
    )

    window._show_friendly_add_preferences_editor()
    dialog = window._friendly_add_preferences_dialog
    assert dialog is not None
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Edit Add Preferences (friendly)"

    assert calls[0][0] == "fetch_friendly_add_preferences"
    assert calls[0][1] == window._api_fetch_app_preferences


def test_speed_limits_apply_requested_queues_profile_apply(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, fn, args)),
    )

    window._on_speed_limits_apply_requested(512, 256, 128, 64, True)

    assert calls[0][0] == "apply_speed_limits_profile"
    assert calls[0][1] == window._api_apply_speed_limits_profile
    assert calls[0][2] == (512 * 1024, 256 * 1024, 128 * 1024, 64 * 1024, True)


def test_show_tracker_health_dashboard_queues_refresh(window, monkeypatch, qtbot):
    calls = []
    monkeypatch.setattr(
        window.analytics_api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, fn, args)),
    )
    window.all_torrents = []

    window._show_tracker_health_dashboard()
    dialog = window._tracker_health_dialog
    assert dialog is not None
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Tracker Health Dashboard"
    assert calls[0][0] == "tracker_health_dashboard"
    assert calls[0][1] == window._fetch_tracker_health_data


def test_show_session_timeline_opens_dialog(window, qtbot):
    window._show_session_timeline()
    dialog = window._session_timeline_dialog
    assert dialog is not None
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Session Timeline"


def test_set_selected_content_priority_queues_expected_api_payload(
    window, monkeypatch, make_torrent
):
    window._selected_torrent = make_torrent(hash="hprio")
    window.current_content_files = [
        {"name": "folder/movie.mkv", "size": 1, "progress": 0.0, "priority": 1}
    ]
    window._apply_content_filter()
    folder_item = window.tree_files.topLevelItem(0)
    file_item = folder_item.child(0)
    window.tree_files.setCurrentItem(file_item)

    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, fn, args)),
    )

    window._set_selected_content_priority(6)

    assert calls[0][0] == "set_content_priority"
    assert calls[0][1] == window._api_set_content_priority
    assert calls[0][2][0] == "hprio"
    assert calls[0][2][1] == "folder/movie.mkv"
    assert calls[0][2][2] is True
    assert calls[0][2][3] == 6


def test_rename_selected_content_item_queues_expected_api_payload(
    window, monkeypatch, make_torrent
):
    window._selected_torrent = make_torrent(hash="hren")
    window.current_content_files = [
        {"name": "folder/old_name.mkv", "size": 1, "progress": 0.0, "priority": 1}
    ]
    window._apply_content_filter()
    folder_item = window.tree_files.topLevelItem(0)
    file_item = folder_item.child(0)
    window.tree_files.setCurrentItem(file_item)
    monkeypatch.setattr(
        window,
        "_prompt_content_rename_name",
        lambda *args, **kwargs: ("new_name.mkv", True),
    )

    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, fn, args)),
    )

    window._rename_selected_content_item()

    assert calls[0][0] == "rename_content_path"
    assert calls[0][1] == window._api_rename_content_path
    assert calls[0][2][0] == "hren"
    assert calls[0][2][1] == "folder/old_name.mkv"
    assert calls[0][2][2] == "folder/new_name.mkv"
    assert calls[0][2][3] is True


def test_clipboard_monitor_queues_add_from_magnet(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, args)),
    )

    added = window._process_clipboard_text(
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=ubuntu"
    )

    assert added is True
    assert calls[0][0] == "add_torrent_from_clipboard"
    payload = calls[0][1][0]
    assert payload["urls"][0].startswith("magnet:?xt=urn:btih:")


def test_clipboard_monitor_queues_add_from_hash(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, args)),
    )

    added = window._process_clipboard_text("0123456789abcdef0123456789abcdef01234567")
    assert added is True
    assert calls[0][0] == "add_torrent_from_clipboard"
    payload = calls[0][1][0]
    assert payload["urls"][0] == "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"


def test_clipboard_monitor_deduplicates_same_payload(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: calls.append((task_name, args)),
    )

    first = window._process_clipboard_text("abcdef0123456789abcdef0123456789abcdef01")
    second = window._process_clipboard_text("abcdef0123456789abcdef0123456789abcdef01")

    assert first is True
    assert second is False
    assert len(calls) == 1


def test_multiple_selection_disables_and_clears_details_panels(window, monkeypatch):
    window.txt_general_details.setPlainText("some details")
    window._set_details_table_message(window.tbl_trackers, "temp")
    window._set_details_table_message(window.tbl_peers, "temp")
    window.current_content_files = [{"name": "a.bin"}]
    window.txt_torrent_edit_name.setText("Name")
    window.txt_torrent_edit_tags.setText("a,b")
    window.spn_torrent_edit_download_limit.setValue(100)
    window.spn_torrent_edit_upload_limit.setValue(50)
    window.txt_torrent_edit_save_path.setText("C:/downloads")
    window._set_torrent_edit_enabled(True, "Editing something")

    monkeypatch.setattr(window, "_get_selected_torrent_hashes", lambda: ["h1", "h2"])
    monkeypatch.setattr(
        window,
        "_display_torrent_details",
        lambda torrent: (_ for _ in ()).throw(AssertionError("should not display")),
    )

    window._on_torrent_selected()

    assert window._selected_torrent is None
    assert window.detail_tabs.isEnabled() is False
    assert window.txt_general_details.toPlainText() == ""
    assert _table_first_cell(window.tbl_trackers) == "Multiple torrents selected."
    assert _table_first_cell(window.tbl_peers) == "Multiple torrents selected."
    assert window.lbl_torrent_edit_state.text() == "Multiple torrents selected."
    assert window.txt_torrent_edit_name.text() == ""
    assert window.txt_torrent_edit_tags.text() == ""
    assert window.spn_torrent_edit_download_limit.value() == 0
    assert window.spn_torrent_edit_upload_limit.value() == 0
    assert window.txt_torrent_edit_save_path.text() == ""
    assert window.btn_torrent_edit_apply.isEnabled() is False


def test_single_selection_reenables_details_panels(window, monkeypatch, make_torrent):
    window.detail_tabs.setEnabled(False)
    window.filtered_torrents = [make_torrent(hash="h1", name="Torrent A")]
    monkeypatch.setattr(window, "_get_selected_torrent_hashes", lambda: ["h1"])

    called = {"ok": False}

    def _fake_display(_torrent):
        called["ok"] = True

    monkeypatch.setattr(window, "_display_torrent_details", _fake_display)
    window._on_torrent_selected()

    assert window.detail_tabs.isEnabled() is True
    assert called["ok"] is True


def test_apply_selected_torrent_edits_requires_one_selected(window, monkeypatch):
    called = {"queued": False}
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda *args, **kwargs: called.__setitem__("queued", True),
    )
    monkeypatch.setattr(window, "_get_selected_torrent_hashes", lambda: ["h1", "h2"])

    window._apply_selected_torrent_edits()

    assert called["queued"] is False


def test_apply_selected_torrent_edits_queues_only_changed_fields(window, make_torrent, monkeypatch):
    torrent = make_torrent(
        hash="h1",
        name="Torrent A",
        category="catA",
        tags="tagA",
        save_path="C:/downloads",
        download_path="C:/incomplete",
        dl_limit=128 * 1024,
        up_limit=64 * 1024,
        auto_tmm=False,
    )
    window._selected_torrent = torrent
    window._populate_torrent_edit_panel(torrent)
    monkeypatch.setattr(window, "_get_selected_torrent_hashes", lambda: ["h1"])

    window.txt_torrent_edit_name.setText("Torrent B")
    window.chk_torrent_edit_auto_tmm.setCheckState(Qt.CheckState.Checked)
    window.cmb_torrent_edit_category.setEditText("catB")
    window.txt_torrent_edit_tags.setText("tag1, tag2")
    window.spn_torrent_edit_download_limit.setValue(640)
    window.spn_torrent_edit_upload_limit.setValue(320)
    window.txt_torrent_edit_save_path.setText("C:/new")
    window.txt_torrent_edit_incomplete_path.setText("")

    queued = {}

    def _capture(task_name, fn, callback, *args, **kwargs):
        queued["task_name"] = task_name
        queued["fn"] = fn
        queued["args"] = args

    monkeypatch.setattr(window.api_queue, "add_task", _capture)
    monkeypatch.setattr(window, "_show_progress", lambda *_args, **_kwargs: None)

    window._apply_selected_torrent_edits()

    assert queued["task_name"] == "apply_selected_torrent_edits"
    assert queued["fn"] == window._api_apply_selected_torrent_edits
    assert queued["args"][0] == "h1"
    updates = queued["args"][1]
    assert updates["name"] == "Torrent B"
    assert updates["auto_tmm"] is True
    assert updates["category"] == "catB"
    assert updates["tags"] == "tag1,tag2"
    assert updates["download_limit_bytes"] == 640 * 1024
    assert updates["upload_limit_bytes"] == 320 * 1024
    assert updates["save_path"] == "C:/new"
    assert updates["download_path"] == ""


def test_enter_opens_selected_torrent_local_directory(window, monkeypatch, make_torrent, tmp_path):
    local_dir = tmp_path / "downloads" / "Torrent A"
    local_dir.mkdir(parents=True)

    torrent = make_torrent(hash="h1", name="Torrent A", content_path=str(local_dir))
    window.all_torrents = [torrent]
    window.filtered_torrents = [torrent]
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )
    window._update_torrents_table()
    window.tbl_torrents.selectRow(0)

    opened = {"path": None}
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda p: opened.__setitem__("path", p),
    )

    window._torrent_open_shortcuts[0].activated.emit()
    assert opened["path"] == str(local_dir)


def test_enter_with_missing_local_directory_does_not_open(
    window, monkeypatch, make_torrent, tmp_path
):
    missing_dir = tmp_path / "missing" / "Torrent B"
    torrent = make_torrent(
        hash="h2", name="Torrent B", content_path=str(missing_dir), save_path=str(missing_dir)
    )
    window.all_torrents = [torrent]
    window.filtered_torrents = [torrent]
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )
    window._update_torrents_table()
    window.tbl_torrents.selectRow(0)

    opened = {"count": 0}
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda _p: opened.__setitem__("count", opened["count"] + 1),
    )

    window._torrent_open_shortcuts[0].activated.emit()
    assert opened["count"] == 0
    assert "No local directory found" in window.lbl_status.text()


def test_double_click_in_torrent_table_opens_local_directory(
    window, monkeypatch, make_torrent, tmp_path
):
    local_dir = tmp_path / "downloads_dblclick"
    local_dir.mkdir(parents=True)

    torrent = make_torrent(hash="h_dbl", name="Double Click", content_path=str(local_dir))
    window.all_torrents = [torrent]
    window.filtered_torrents = [torrent]
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )
    window._update_torrents_table()

    opened = {"path": None}
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda p: opened.__setitem__("path", p),
    )

    row_item = window.tbl_torrents.item(0, 1)
    window.tbl_torrents.itemDoubleClicked.emit(row_item)
    assert opened["path"] == str(local_dir)


def test_enter_in_content_tree_opens_selected_local_file(
    window, monkeypatch, make_torrent, tmp_path
):
    local_root = tmp_path / "downloads"
    target_file = local_root / "folder" / "movie.mkv"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("ok", encoding="utf-8")

    window._selected_torrent = make_torrent(
        hash="h1",
        name="Torrent A",
        content_path=str(local_root),
        save_path=str(local_root),
    )
    window.current_content_files = [
        {"name": "folder/movie.mkv", "size": 1, "progress": 1.0, "priority": 1}
    ]
    window._apply_content_filter()
    folder_item = window.tree_files.topLevelItem(0)
    file_item = folder_item.child(0)
    window.tree_files.setCurrentItem(file_item)

    opened = {"path": None}
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda p: opened.__setitem__("path", p),
    )

    window._content_open_shortcuts[0].activated.emit()
    assert opened["path"] == str(target_file)


def test_enter_in_content_tree_with_missing_file_does_not_open(
    window, monkeypatch, make_torrent, tmp_path
):
    local_root = tmp_path / "downloads"
    (local_root / "folder").mkdir(parents=True)

    window._selected_torrent = make_torrent(
        hash="h2",
        name="Torrent B",
        content_path=str(local_root),
        save_path=str(local_root),
    )
    window.current_content_files = [
        {"name": "folder/missing.mkv", "size": 1, "progress": 1.0, "priority": 1}
    ]
    window._apply_content_filter()
    folder_item = window.tree_files.topLevelItem(0)
    file_item = folder_item.child(0)
    window.tree_files.setCurrentItem(file_item)

    opened = {"count": 0}
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda _p: opened.__setitem__("count", opened["count"] + 1),
    )

    window._content_open_shortcuts[0].activated.emit()
    assert opened["count"] == 0
    assert "Selected file does not exist locally" in window.lbl_status.text()


def test_enter_on_torrent_expands_env_var_directory_path(
    window, monkeypatch, make_torrent, tmp_path
):
    local_dir = tmp_path / "downloads_env"
    local_dir.mkdir(parents=True)
    monkeypatch.setenv("QBIREMO_TEST_DIR", str(local_dir))

    torrent = make_torrent(hash="h_env", name="Env Torrent", save_path="%QBIREMO_TEST_DIR%")
    window.all_torrents = [torrent]
    window.filtered_torrents = [torrent]
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )
    window._update_torrents_table()
    window.tbl_torrents.selectRow(0)

    opened = {"path": None}
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda p: opened.__setitem__("path", p),
    )

    window._torrent_open_shortcuts[0].activated.emit()
    assert opened["path"] == str(local_dir)


def test_enter_in_content_tree_expands_env_var_path(window, monkeypatch, make_torrent, tmp_path):
    local_root = tmp_path / "downloads_content_env"
    target_file = local_root / "folder" / "env_movie.mkv"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("ok", encoding="utf-8")
    monkeypatch.setenv("QBIREMO_TEST_CONTENT_DIR", str(local_root))

    window._selected_torrent = make_torrent(
        hash="h_env_content",
        name="Env Content",
        content_path="%QBIREMO_TEST_CONTENT_DIR%",
        save_path="%QBIREMO_TEST_CONTENT_DIR%",
    )
    window.current_content_files = [
        {"name": "folder/env_movie.mkv", "size": 1, "progress": 1.0, "priority": 1}
    ]
    window._apply_content_filter()
    folder_item = window.tree_files.topLevelItem(0)
    file_item = folder_item.child(0)
    window.tree_files.setCurrentItem(file_item)

    opened = {"path": None}
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda p: opened.__setitem__("path", p),
    )

    window._content_open_shortcuts[0].activated.emit()
    assert opened["path"] == str(target_file)


def test_content_tree_item_activated_opens_local_file(window, monkeypatch, make_torrent, tmp_path):
    local_root = tmp_path / "downloads_activate"
    target_file = local_root / "folder" / "activate_movie.mkv"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("ok", encoding="utf-8")

    window._selected_torrent = make_torrent(
        hash="h_activate",
        name="Activate Content",
        content_path=str(local_root),
        save_path=str(local_root),
    )
    window.current_content_files = [
        {"name": "folder/activate_movie.mkv", "size": 1, "progress": 1.0, "priority": 1}
    ]
    window._apply_content_filter()
    folder_item = window.tree_files.topLevelItem(0)
    file_item = folder_item.child(0)
    window.tree_files.setCurrentItem(file_item)

    opened = {"path": None}
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda p: opened.__setitem__("path", p),
    )

    window.tree_files.itemActivated.emit(file_item, 0)
    assert opened["path"] == str(target_file)


def test_content_tree_event_filter_handles_enter_and_opens_file(
    window, monkeypatch, make_torrent, tmp_path
):
    local_root = tmp_path / "downloads_eventfilter"
    target_file = local_root / "folder" / "eventfilter_movie.mkv"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("ok", encoding="utf-8")

    window._selected_torrent = make_torrent(
        hash="h_eventfilter",
        name="EventFilter Content",
        content_path=str(local_root),
        save_path=str(local_root),
    )
    window.current_content_files = [
        {"name": "folder/eventfilter_movie.mkv", "size": 1, "progress": 1.0, "priority": 1}
    ]
    window._apply_content_filter()
    folder_item = window.tree_files.topLevelItem(0)
    file_item = folder_item.child(0)
    window.tree_files.setCurrentItem(file_item)

    opened = {"path": None}
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda p: opened.__setitem__("path", p),
    )

    class _FakeEnterEvent:
        def type(self):
            return appmod.QEvent.Type.KeyPress

        def key(self):
            return appmod.Qt.Key.Key_Return

    handled = window.eventFilter(window.tree_files, _FakeEnterEvent())
    assert handled is True
    assert opened["path"] == str(target_file)


def test_show_taxonomy_manager_dialog(window, qtbot):
    window.categories = ["movies"]
    window.category_details = {
        "movies": {
            "savePath": "D:/downloads/movies",
            "downloadPath": "D:/downloads/incomplete",
            "enableDownloadPath": True,
        }
    }
    window.tags = ["tag1", "tag2"]

    window._show_taxonomy_manager()
    dialog = window._taxonomy_dialog
    assert dialog is not None
    qtbot.addWidget(dialog)
    assert dialog.tabs.count() == 2
    assert dialog.tabs.tabText(0) == "Categories"
    assert dialog.tabs.tabText(1) == "Tags"
    assert dialog.lst_categories.count() == 1
    assert dialog.lst_tags_manage.count() == 2
    assert hasattr(dialog, "txt_category_incomplete_path")
    assert hasattr(dialog, "chk_category_use_incomplete")


def test_taxonomy_dialog_requests_queue_expected_api_actions(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window,
        "_queue_taxonomy_action",
        lambda task_name, fn, action_name, *args: calls.append((task_name, fn, action_name, args)),
    )
    monkeypatch.setattr(
        appmod.QMessageBox,
        "question",
        lambda *args, **kwargs: appmod.QMessageBox.StandardButton.Yes,
    )

    window._on_taxonomy_create_category_requested(
        "movies",
        "D:/downloads/movies",
        "D:/downloads/incomplete",
        True,
    )
    window._on_taxonomy_edit_category_requested(
        "movies",
        "E:/downloads/movies",
        "",
        False,
    )
    window._on_taxonomy_delete_category_requested("movies")
    window._on_taxonomy_create_tags_requested(["tag1", "tag2"])
    window._on_taxonomy_delete_tags_requested(["tag1"])

    assert calls[0] == (
        "create_category",
        window._api_create_category,
        "Create Category",
        ("movies", "D:/downloads/movies", "D:/downloads/incomplete", True),
    )
    assert calls[1] == (
        "edit_category",
        window._api_edit_category,
        "Edit Category",
        ("movies", "E:/downloads/movies", "", False),
    )
    assert calls[2] == (
        "delete_category",
        window._api_delete_category,
        "Delete Category",
        ("movies",),
    )
    assert calls[3] == (
        "create_tags",
        window._api_create_tags,
        "Create Tag",
        (["tag1", "tag2"],),
    )
    assert calls[4] == (
        "delete_tags",
        window._api_delete_tags,
        "Delete Tag",
        (["tag1"],),
    )


def test_window_controller_proxy_reads_and_writes_window_attributes(window):
    controller = appmod.NetworkApiController(window)

    window._delegation_marker = "before"
    assert controller._delegation_marker == "before"

    controller._delegation_marker = "after"
    assert window._delegation_marker == "after"


def test_delegated_controller_method_is_bound_on_mainwindow(window):
    assert "_build_connection_info" not in appmod.MainWindow.__dict__

    delegated = window._build_connection_info
    assert callable(delegated)
    assert getattr(delegated, "__self__", None) is window


def test_install_controller_methods_skips_eventfilter_and_closeevent(window):
    class DummyController:
        def eventFilter(self, _watched, _event):
            return True

        def closeEvent(self, _event):
            raise AssertionError("closeEvent should not be overwritten")

        def delegated_dummy(self):
            return "ok"

    event_filter_before = window.eventFilter
    close_event_before = window.closeEvent

    window._install_controller_methods(DummyController)

    assert window.delegated_dummy() == "ok"
    assert window.eventFilter.__func__ is event_filter_before.__func__
    assert window.closeEvent.__func__ is close_event_before.__func__


def test_mainwindow_open_file_helper_delegates_to_runtime_helper(window, monkeypatch):
    captured = {"path": None}

    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda p: captured.__setitem__("path", p) or True,
    )

    assert window._open_file_in_default_app("C:/tmp/sample.txt") is True
    assert captured["path"] == "C:/tmp/sample.txt"


def test_open_log_file_uses_open_helper_with_absolute_path(window, monkeypatch, tmp_path):
    log_path = tmp_path / "runtime.log"
    window.log_file_path = str(log_path)

    captured = {"path": None}
    monkeypatch.setattr(
        window,
        "_open_file_in_default_app",
        lambda p: captured.__setitem__("path", p) or True,
    )

    window._open_log_file()

    assert captured["path"] == str(log_path.resolve())


def test_open_log_file_reports_failure_when_helper_returns_false(window, monkeypatch, tmp_path):
    log_path = tmp_path / "cannot-open.log"
    window.log_file_path = str(log_path)

    logged = {"message": ""}
    monkeypatch.setattr(window, "_open_file_in_default_app", lambda _p: False)
    monkeypatch.setattr(
        window,
        "_log",
        lambda _level, message: logged.__setitem__("message", str(message)),
    )

    window._open_log_file()

    assert "Failed to open log file" in logged["message"]
    assert "Failed to open log file" in window.lbl_status.text()


def test_mainwindow_eventfilter_forwards_false_result_from_session_controller(window, monkeypatch):
    called = {}

    def _fake_event_filter(_self, watched, event):
        called["watched"] = watched
        called["event"] = event
        return False

    monkeypatch.setattr(appmod.SessionUiController, "eventFilter", _fake_event_filter)

    watched = window.tree_filters
    event = appmod.QEvent(appmod.QEvent.Type.None_)
    handled = window.eventFilter(watched, event)

    assert handled is False
    assert called["watched"] is watched
    assert called["event"] is event


def test_mainwindow_closeevent_forwards_to_session_controller(window, monkeypatch):
    called = {}

    def _fake_close_event(_self, event):
        called["event"] = event

    monkeypatch.setattr(appmod.SessionUiController, "closeEvent", _fake_close_event)
    event = appmod.QCloseEvent()

    window.closeEvent(event)

    assert called["event"] is event
