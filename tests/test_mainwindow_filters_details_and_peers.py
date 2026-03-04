import qbiremo_enhanced.main_window as appmod
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


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


def test_quick_name_and_private_filters_apply_immediately(window, qtbot, make_torrent):
    t1 = make_torrent(hash="h1", name="Ubuntu ISO", private=True, state="downloading")
    t2 = make_torrent(hash="h2", name="Arch Linux", private=False, state="seeding")
    window.all_torrents = [t1, t2]
    window.content_cache = {
        "h1": {"state": "downloading", "files": []},
        "h2": {"state": "seeding", "files": []},
    }
    window._apply_filters()
    assert [t.hash for t in window.filtered_torrents] == ["h1", "h2"]

    window.txt_name_filter.setText("ubuntu")
    qtbot.waitUntil(lambda: [t.hash for t in window.filtered_torrents] == ["h1"])

    window.cmb_private.setCurrentText("No")
    qtbot.waitUntil(lambda: window.filtered_torrents == [])

    window.cmb_private.setCurrentText("Yes")
    qtbot.waitUntil(lambda: [t.hash for t in window.filtered_torrents] == ["h1"])


def test_file_filter_uses_cached_content_and_updates_live(window, qtbot, make_torrent):
    t1 = make_torrent(hash="h1", name="Show Pack")
    t2 = make_torrent(hash="h2", name="Movie Pack")
    window.all_torrents = [t1, t2]
    window.content_cache = {
        "h1": {
            "state": "downloading",
            "files": [
                {"name": "Series/S01/episode01.mkv", "size": 1, "progress": 1.0, "priority": 1}
            ],
        },
        "h2": {
            "state": "seeding",
            "files": [{"name": "Movies/movie.mp4", "size": 1, "progress": 1.0, "priority": 1}],
        },
    }
    window._apply_filters()

    window.txt_file_filter.setText("episode")
    qtbot.waitUntil(lambda: [t.hash for t in window.filtered_torrents] == ["h1"])

    window.txt_file_filter.setText("S01")
    qtbot.waitUntil(lambda: [t.hash for t in window.filtered_torrents] == ["h1"])

    window.txt_file_filter.setText("movie")
    qtbot.waitUntil(lambda: [t.hash for t in window.filtered_torrents] == ["h2"])


def test_content_file_filter_in_content_tab(window, qtbot):
    window.content_cache = {
        "h1": {
            "state": "downloading",
            "files": [
                {"name": "readme.txt", "size": 1, "progress": 1.0, "priority": 1},
                {"name": "sample.nfo", "size": 2, "progress": 1.0, "priority": 1},
                {"name": "video.mkv", "size": 3, "progress": 0.5, "priority": 1},
            ],
        }
    }

    window._show_cached_torrent_content("h1")
    assert sorted(_top_level_names(window.tree_files)) == ["readme.txt", "sample.nfo", "video.mkv"]

    window.txt_content_filter.setText("sample")
    qtbot.waitUntil(lambda: _top_level_names(window.tree_files) == ["sample.nfo"])

    window.txt_content_filter.setText("*.txt")
    qtbot.waitUntil(lambda: _top_level_names(window.tree_files) == ["readme.txt"])

    window.txt_content_filter.setText("")
    qtbot.waitUntil(
        lambda: (
            sorted(_top_level_names(window.tree_files)) == ["readme.txt", "sample.nfo", "video.mkv"]
        )
    )


def test_details_panel_tabs_are_general_trackers_peers_content(window):
    assert _tab_names(window.detail_tabs) == ["General", "Trackers", "Peers", "Content", "Edit"]


def test_general_trackers_peers_tabs_populate_on_selection(window, make_torrent, monkeypatch):
    t1 = make_torrent(
        hash="h1",
        name="Ubuntu ISO",
        tracker="https://tracker.example/announce",
        num_seeds=12,
        num_leechs=34,
        num_complete=56,
        num_incomplete=78,
    )

    def _fake_network_details_loader(_torrent_hash):
        window._populate_details_table(
            window.tbl_trackers,
            [{"url": "https://tracker.example/announce", "status": 2, "tier": 0}],
            ["url", "status", "tier"],
        )
        window._populate_details_table(
            window.tbl_peers,
            [{"peer_id": "peerA", "ip": "10.0.0.2", "port": 6881, "client": "qBittorrent"}],
            ["peer_id", "ip", "port", "client"],
        )

    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", _fake_network_details_loader
    )
    window._display_torrent_details(t1)

    general = window.txt_general_details.toPlainText()

    assert "GENERAL" in general
    assert "Ubuntu ISO" in general

    tracker_headers = _table_headers(window.tbl_trackers)
    peer_headers = _table_headers(window.tbl_peers)
    assert "url" in tracker_headers
    assert "status" in tracker_headers
    assert "peer_id" in peer_headers
    assert "ip" in peer_headers


def test_edit_tab_populates_for_single_selected_torrent(window, make_torrent, monkeypatch):
    t1 = make_torrent(
        hash="h1",
        name="Ubuntu ISO",
        category="linux",
        tags="iso,ubuntu",
        save_path="C:/downloads",
        download_path="C:/incomplete",
        dl_limit=512 * 1024,
        up_limit=256 * 1024,
        auto_tmm=True,
    )
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(window, "_show_cached_torrent_content", lambda *_args, **_kwargs: None)

    window._display_torrent_details(t1)

    assert window.lbl_torrent_edit_state.text() == "Editing [ Ubuntu ISO ]"
    assert window.txt_torrent_edit_name.text() == "Ubuntu ISO"
    assert window.chk_torrent_edit_auto_tmm.checkState() == Qt.CheckState.Checked
    assert window.cmb_torrent_edit_category.currentText() == "linux"
    assert window.txt_torrent_edit_tags.text() == "iso, ubuntu"
    assert window.spn_torrent_edit_download_limit.value() == 512
    assert window.spn_torrent_edit_upload_limit.value() == 256
    assert window.txt_torrent_edit_save_path.text() == "C:/downloads"
    assert window.txt_torrent_edit_incomplete_path.text() == "C:/incomplete"
    assert window.btn_torrent_edit_apply.isEnabled() is True


def test_torrent_edit_add_tags_button_merges_selected_tags(window, monkeypatch):
    window.tags = ["tag1", "tag2", "tag3"]
    window.txt_torrent_edit_tags.setText("tag1")
    monkeypatch.setattr(
        window,
        "_pick_tags_for_torrent_edit",
        lambda available_tags, selected_tags: ["tag2", "tag1", "tag3"],
    )

    window._add_tags_to_torrent_edit()

    assert window.txt_torrent_edit_tags.text() == "tag1, tag2, tag3"


def test_torrent_edit_path_browse_buttons_show_only_for_existing_local_paths(window, tmp_path):
    existing_dir = tmp_path / "existing"
    existing_dir.mkdir(parents=True)
    missing_dir = tmp_path / "missing"

    window._set_torrent_edit_enabled(True, "Editing")
    window.txt_torrent_edit_save_path.setText(str(existing_dir))
    window.txt_torrent_edit_incomplete_path.setText(str(missing_dir))

    assert window.btn_torrent_edit_browse_save_path.isHidden() is False
    assert window.btn_torrent_edit_browse_incomplete_path.isHidden() is True

    window.txt_torrent_edit_incomplete_path.setText(str(existing_dir))
    assert window.btn_torrent_edit_browse_incomplete_path.isHidden() is False


def test_torrent_edit_tag_picker_dialog_geometry_matches_parent_ratio(window, monkeypatch):
    window.resize(1000, 800)
    window.move(120, 80)

    captured = {}

    def _fake_exec(dialog):
        geom = dialog.geometry()
        captured["x"] = geom.x()
        captured["y"] = geom.y()
        captured["width"] = geom.width()
        captured["height"] = geom.height()
        return appmod.QDialog.DialogCode.Rejected

    monkeypatch.setattr(appmod.QDialog, "exec", _fake_exec)

    result = window._pick_tags_for_torrent_edit(["tag1", "tag2"], [])

    parent = window.frameGeometry()
    expected_width = 212
    expected_height = int(parent.height() * 0.90)
    expected_x = parent.x() + int(parent.width() * 0.70)
    expected_y = parent.y() + max(0, (parent.height() - expected_height) // 2)

    assert result is None
    assert captured["width"] == expected_width
    assert captured["height"] == expected_height
    assert captured["x"] == expected_x
    assert captured["y"] == expected_y


def test_general_details_copy_to_clipboard(window):
    window.txt_general_details.setPlainText("copy-me")
    window._copy_general_details()
    assert QApplication.clipboard().text() == "copy-me"


def test_app_preferences_dialog_tracks_changes_and_highlights_coral(window):
    dialog = appmod.AppPreferencesDialog(window)
    dialog.set_preferences(
        {
            "max_active_downloads": 3,
            "use_https": False,
            "nested": {"save_path": "/tmp"},
        }
    )

    item = dialog._leaf_items[("max_active_downloads",)]
    item.setText(1, "5")

    assert dialog.changed_preferences() == {"max_active_downloads": 5}
    assert item.background(1).color().name().lower() == "#ff7f50"

    captured = {}
    dialog.apply_requested.connect(lambda changes: captured.update(changes))
    dialog._emit_apply()
    assert captured == {"max_active_downloads": 5}


def test_app_preferences_dialog_uses_apply_and_cancel_buttons(window):
    dialog = appmod.AppPreferencesDialog(window)
    assert dialog.btn_apply.text() == "Apply"
    assert dialog.btn_cancel.text() == "Cancel"


def test_on_app_preferences_apply_requested_queues_api_task(window, monkeypatch):
    captured = {}

    def _fake_add_task(task_name, api_method, callback, *args):
        captured["task_name"] = task_name
        captured["api_method_name"] = getattr(api_method, "__name__", "")
        captured["callback"] = callback
        captured["args"] = args

    monkeypatch.setattr(window.api_queue, "add_task", _fake_add_task)

    window._on_app_preferences_apply_requested({"max_active_downloads": 8})

    assert captured["task_name"] == "apply_app_preferences"
    assert captured["api_method_name"] == "_api_apply_app_preferences"
    assert callable(captured["callback"])
    assert captured["args"] == ({"max_active_downloads": 8},)


def test_friendly_add_preferences_dialog_tracks_changed_fields(window):
    dialog = appmod.FriendlyAddPreferencesDialog(window)
    dialog.set_preferences(
        {
            "save_path": "C:/downloads",
            "temp_path_enabled": True,
            "temp_path": "C:/incomplete",
            "start_paused_enabled": False,
            "create_subfolder_enabled": True,
            "auto_tmm_enabled": False,
            "incomplete_files_ext": True,
            "preallocate_all": False,
            "queueing_enabled": True,
            "max_active_downloads": 3,
            "max_active_uploads": 4,
            "max_active_torrents": 5,
            "max_connec": 600,
            "max_connec_per_torrent": 60,
            "max_uploads": 30,
            "max_uploads_per_torrent": 10,
            "dht": True,
            "pex": True,
            "lsd": False,
            "upnp": True,
            "anonymous_mode": False,
            "encryption": 0,
            "max_ratio_enabled": False,
            "max_ratio": 2.0,
            "max_seeding_time_enabled": False,
            "max_seeding_time": 120,
        }
    )

    dialog.txt_save_path.setText("D:/downloads")
    dialog.chk_start_paused.setChecked(True)
    dialog.spn_max_active_downloads.setValue(9)
    dialog.chk_dht.setChecked(False)
    dialog.cmb_encryption.setCurrentIndex(dialog.cmb_encryption.findData(1))
    dialog.chk_max_ratio_enabled.setChecked(True)
    dialog.spn_max_ratio.setValue(3.5)

    assert dialog.changed_preferences() == {
        "save_path": "D:/downloads",
        "start_paused_enabled": True,
        "max_active_downloads": 9,
        "dht": False,
        "encryption": 1,
        "max_ratio_enabled": True,
        "max_ratio": 3.5,
    }

    captured = {}
    dialog.apply_requested.connect(lambda changes: captured.update(changes))
    dialog._emit_apply()
    assert captured == {
        "save_path": "D:/downloads",
        "start_paused_enabled": True,
        "max_active_downloads": 9,
        "dht": False,
        "encryption": 1,
        "max_ratio_enabled": True,
        "max_ratio": 3.5,
    }


def test_friendly_add_preferences_dialog_uses_apply_and_cancel_buttons(window):
    dialog = appmod.FriendlyAddPreferencesDialog(window)
    assert dialog.btn_apply.text() == "Apply"
    assert dialog.btn_cancel.text() == "Cancel"


def test_friendly_add_preferences_apply_requested_queues_api_task(window, monkeypatch):
    captured = {}

    def _fake_add_task(task_name, api_method, callback, *args):
        captured["task_name"] = task_name
        captured["api_method_name"] = getattr(api_method, "__name__", "")
        captured["callback"] = callback
        captured["args"] = args

    monkeypatch.setattr(window.api_queue, "add_task", _fake_add_task)

    window._on_friendly_add_preferences_apply_requested({"save_path": "C:/downloads"})

    assert captured["task_name"] == "apply_friendly_add_preferences"
    assert captured["api_method_name"] == "_api_apply_app_preferences"
    assert callable(captured["callback"])
    assert captured["args"] == ({"save_path": "C:/downloads"},)


def test_peers_table_uses_custom_context_menu(window):
    assert window.tbl_peers.contextMenuPolicy() == appmod.Qt.ContextMenuPolicy.CustomContextMenu


def test_peers_context_menu_contains_requested_actions(window):
    window._populate_details_table(
        window.tbl_peers,
        [{"peer_id": "peerA", "ip": "10.0.0.2", "port": 6881, "client": "qBittorrent"}],
        ["peer_id", "ip", "port", "client"],
    )
    window.tbl_peers.selectRow(0)

    menu = window._build_peers_context_menu()
    action_texts = [action.text() for action in menu.actions() if not action.isSeparator()]

    assert "Copy All Peers Info" in action_texts
    assert "Copy Peer Info" in action_texts
    assert "Copy Peer IP:port" in action_texts
    assert "Ban Peer" in action_texts


def test_peers_context_copy_actions_copy_expected_values(window):
    window._populate_details_table(
        window.tbl_peers,
        [
            {"peer_id": "peerA", "ip": "10.0.0.2", "port": 6881, "client": "qBittorrent"},
            {"peer_id": "peerB", "ip": "10.0.0.3", "port": 51413, "client": "Transmission"},
        ],
        ["peer_id", "ip", "port", "client"],
    )
    window.tbl_peers.selectRow(0)

    window._copy_all_peers_info()
    all_text = QApplication.clipboard().text()
    all_lines = all_text.splitlines()
    assert all_lines[0] == "peer_id\tip\tport\tclient"
    assert "peerA\t10.0.0.2\t6881\tqBittorrent" in all_text
    assert "peerB\t10.0.0.3\t51413\tTransmission" in all_text

    window._copy_selected_peer_info()
    selected_text = QApplication.clipboard().text()
    selected_lines = selected_text.splitlines()
    assert selected_lines[0] == "peer_id\tip\tport\tclient"
    assert selected_lines[1] == "peerA\t10.0.0.2\t6881\tqBittorrent"

    window._copy_selected_peer_ip_port()
    assert QApplication.clipboard().text() == "10.0.0.2:6881"


def test_ban_selected_peer_queues_api_task(window, monkeypatch):
    window._populate_details_table(
        window.tbl_peers,
        [{"peer_id": "peerA", "ip": "10.0.0.2", "port": 6881, "client": "qBittorrent"}],
        ["peer_id", "ip", "port", "client"],
    )
    window.tbl_peers.selectRow(0)
    monkeypatch.setattr(
        appmod.QMessageBox,
        "question",
        lambda *_args, **_kwargs: appmod.QMessageBox.StandardButton.Yes,
    )

    captured = {}

    def _fake_add_task(task_name, api_method, callback, *args):
        captured["task_name"] = task_name
        captured["api_method_name"] = getattr(api_method, "__name__", "")
        captured["callback"] = callback
        captured["args"] = args

    monkeypatch.setattr(window.api_queue, "add_task", _fake_add_task)

    window._ban_selected_peer()

    assert captured["task_name"] == "ban_peer"
    assert captured["api_method_name"] == "_api_ban_peers"
    assert callable(captured["callback"])
    assert captured["args"] == (["10.0.0.2:6881"],)
