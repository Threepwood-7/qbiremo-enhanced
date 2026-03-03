import logging
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

import qbiremo_enhanced.main_window as appmod


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
            "files": [{"name": "Series/S01/episode01.mkv", "size": 1, "progress": 1.0, "priority": 1}],
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
    qtbot.waitUntil(lambda: sorted(_top_level_names(window.tree_files)) == ["readme.txt", "sample.nfo", "video.mkv"])


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

    monkeypatch.setattr(window, "_load_selected_torrent_network_details", _fake_network_details_loader)
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
    monkeypatch.setattr(window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None)
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
    assert (
        window.tbl_peers.contextMenuPolicy()
        == appmod.Qt.ContextMenuPolicy.CustomContextMenu
    )


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


def test_cache_refresh_candidates_only_include_state_changes_without_pruning(window, make_torrent):
    window.all_torrents = [
        make_torrent(hash="h1", state="downloading"),
        make_torrent(hash="h2", state="seeding"),
    ]
    window.content_cache = {
        "h1": {"state": "downloading", "files": []},
        "h2": {"state": "paused", "files": []},
        "stale": {"state": "seeding", "files": []},
    }

    candidates = window._get_cache_refresh_candidates()
    assert candidates == {"h2": "seeding"}
    assert "stale" in window.content_cache


def test_refresh_content_cache_uses_mocked_client(window, monkeypatch):
    files_by_hash = {
        "h1": [SimpleNamespace(name="a.bin", size=10, progress=0.5, priority=1)],
        "h2": [SimpleNamespace(name="b.bin", size=20, progress=1.0, priority=6)],
    }

    class FakeClient:
        def auth_log_in(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def torrents_files(self, torrent_hash):
            return files_by_hash[torrent_hash]

    fake_client = FakeClient()
    monkeypatch.setattr(window, "_create_client", lambda: fake_client)

    result = window._refresh_content_cache_for_torrents({"h1": "downloading", "h2": "seeding"})
    assert result["success"] is True
    assert set(result["data"].keys()) == {"h1", "h2"}
    assert result["data"]["h1"]["state"] == "downloading"
    assert result["data"]["h1"]["files"][0]["name"] == "a.bin"
    assert result["data"]["h2"]["files"][0]["priority"] == 6


def test_status_category_tag_filters_still_trigger_api_refresh(window, monkeypatch):
    calls = {"count": 0}

    def _fake_refresh():
        calls["count"] += 1

    monkeypatch.setattr(window, "_refresh_torrents", _fake_refresh)

    for kind, value in [("status", "downloading"), ("category", "movies"), ("tag", "tag1")]:
        item = QTreeWidgetItem([value])
        item.setData(0, Qt.ItemDataRole.UserRole, (kind, value))
        window._on_filter_tree_clicked(item, 0)

    assert calls["count"] == 3


def test_fetch_torrents_uses_sync_maindata_and_updates_rid(window, monkeypatch):
    class FakeClient:
        def __init__(self):
            self.last_rid = None

        def auth_log_in(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def sync_maindata(self, rid=0):
            self.last_rid = rid
            return {
                "rid": 7,
                "full_update": True,
                "torrents": {
                    "h1": {"name": "First", "added_on": 10, "state": "downloading"},
                    "h2": {"name": "Second", "added_on": 20, "state": "seeding"},
                },
                "torrents_removed": [],
            }

        def transfer_speed_limits_mode(self):
            return 1

    fake_client = FakeClient()
    monkeypatch.setattr(window, "_create_client", lambda: fake_client)
    window.current_status_filter = "all"
    window.current_category_filter = None
    window.current_tag_filter = None
    window._sync_rid = 3

    result = window._fetch_torrents()
    assert result["success"] is True
    assert fake_client.last_rid == 3
    assert window._sync_rid == 7
    assert result["alt_speed_mode"] is True
    assert [t.hash for t in result["data"]] == ["h2", "h1"]


def test_fetch_torrents_passes_selected_status_category_and_tag_filters(window, monkeypatch):
    class FakeClient:
        def __init__(self):
            self.kwargs = None

        def auth_log_in(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def sync_maindata(self, rid=0):
            raise AssertionError("sync_maindata should not be used when remote filters are selected")

        def torrents_info(self, **kwargs):
            self.kwargs = kwargs
            return [
                SimpleNamespace(hash="h1", name="One", added_on=10, state="downloading"),
                SimpleNamespace(hash="h2", name="Two", added_on=20, state="downloading"),
            ]

        def transfer_speed_limits_mode(self):
            return 0

    fake_client = FakeClient()
    monkeypatch.setattr(window, "_create_client", lambda: fake_client)
    window.current_status_filter = "downloading"
    window.current_category_filter = "movies"
    window.current_tag_filter = "tag1"

    result = window._fetch_torrents()

    assert result["success"] is True
    assert result["remote_filtered"] is True
    assert fake_client.kwargs == {
        "status_filter": "downloading",
        "category": "movies",
        "tag": "tag1",
    }
    assert [t.hash for t in result["data"]] == ["h2", "h1"]


def test_fetch_torrents_passes_empty_category_and_tag_when_selected(window, monkeypatch):
    class FakeClient:
        def __init__(self):
            self.kwargs = None

        def auth_log_in(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def sync_maindata(self, rid=0):
            raise AssertionError("sync_maindata should not be used when category/tag are selected")

        def torrents_info(self, **kwargs):
            self.kwargs = kwargs
            return [SimpleNamespace(hash="h1", name="One", added_on=10, state="stalledDL")]

        def transfer_speed_limits_mode(self):
            return 0

    fake_client = FakeClient()
    monkeypatch.setattr(window, "_create_client", lambda: fake_client)
    window.current_status_filter = window.default_status_filter
    window.current_category_filter = ""
    window.current_tag_filter = ""

    result = window._fetch_torrents()

    assert result["success"] is True
    assert result["remote_filtered"] is True
    assert fake_client.kwargs == {
        "status_filter": "active",
        "category": "",
        "tag": "",
    }


def test_fetch_torrents_passes_private_true_filter(window, monkeypatch):
    class FakeClient:
        def __init__(self):
            self.kwargs = None

        def auth_log_in(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def sync_maindata(self, rid=0):
            raise AssertionError("sync_maindata should not be used when private filter is selected")

        def torrents_info(self, **kwargs):
            self.kwargs = kwargs
            return [SimpleNamespace(hash="h1", name="One", added_on=10, state="downloading", private=True)]

        def transfer_speed_limits_mode(self):
            return 0

    fake_client = FakeClient()
    monkeypatch.setattr(window, "_create_client", lambda: fake_client)
    window.current_status_filter = "all"
    window.current_category_filter = None
    window.current_tag_filter = None
    window.current_private_filter = True

    result = window._fetch_torrents()

    assert result["success"] is True
    assert result["remote_filtered"] is True
    assert fake_client.kwargs == {"private": True}


def test_fetch_torrents_passes_private_false_filter(window, monkeypatch):
    class FakeClient:
        def __init__(self):
            self.kwargs = None

        def auth_log_in(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def sync_maindata(self, rid=0):
            raise AssertionError("sync_maindata should not be used when private filter is selected")

        def torrents_info(self, **kwargs):
            self.kwargs = kwargs
            return [SimpleNamespace(hash="h2", name="Two", added_on=20, state="downloading", private=False)]

        def transfer_speed_limits_mode(self):
            return 0

    fake_client = FakeClient()
    monkeypatch.setattr(window, "_create_client", lambda: fake_client)
    window.current_status_filter = "all"
    window.current_category_filter = None
    window.current_tag_filter = None
    window.current_private_filter = False

    result = window._fetch_torrents()

    assert result["success"] is True
    assert result["remote_filtered"] is True
    assert fake_client.kwargs == {"private": False}


def test_merge_sync_maindata_applies_updates_and_removals(window):
    first = {
        "rid": 2,
        "full_update": True,
        "torrents": {
            "h1": {"name": "One", "added_on": 10, "state": "downloading"},
            "h2": {"name": "Two", "added_on": 20, "state": "seeding"},
        },
        "torrents_removed": [],
    }
    second = {
        "rid": 3,
        "full_update": False,
        "torrents": {
            "h1": {"state": "pausedDL"},
            "h3": {"name": "Three", "added_on": 30, "state": "downloading"},
        },
        "torrents_removed": ["h2"],
    }

    merged_first = window._merge_sync_maindata(first)
    merged_second = window._merge_sync_maindata(second)

    assert [t.hash for t in merged_first] == ["h2", "h1"]
    assert [t.hash for t in merged_second] == ["h3", "h1"]
    h1 = next(t for t in merged_second if t.hash == "h1")
    assert h1.state == "pausedDL"


def test_fetch_tracker_health_data_aggregates_by_tracker(window, monkeypatch):
    trackers_by_hash = {
        "h1": [
            {"url": "udp://tracker.one:6969/announce", "status": 4, "msg": "timed out", "next_announce": 10},
            {"url": "udp://tracker.two:6969/announce", "status": 2, "msg": "", "next_announce": 20},
        ],
        "h2": [
            {"url": "udp://tracker.one:6969/announce", "status": 4, "msg": "connection refused", "next_announce": 30},
        ],
    }

    class FakeClient:
        def auth_log_in(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def torrents_trackers(self, torrent_hash):
            return trackers_by_hash.get(torrent_hash, [])

    monkeypatch.setattr(window, "_create_client", lambda: FakeClient())
    result = window._fetch_tracker_health_data(["h1", "h2"])

    assert result["success"] is True
    rows = result["data"]
    first = rows[0]
    assert first["tracker"] == "tracker.one"
    assert first["torrent_count"] == 2
    assert first["failing_count"] == 2
    assert first["dead"] is True


def test_record_session_timeline_sample_adds_entry(window, make_torrent):
    window.all_torrents = [
        make_torrent(hash="h1", dlspeed=100, upspeed=50),
        make_torrent(hash="h2", dlspeed=0, upspeed=0),
    ]
    window.session_timeline_history.clear()

    window._record_session_timeline_sample(True)
    assert len(window.session_timeline_history) == 1
    sample = window.session_timeline_history[-1]
    assert sample["down_bps"] == 100
    assert sample["up_bps"] == 50
    assert sample["active_count"] == 1
    assert sample["alt_enabled"] is True


def test_apply_filters_includes_status_category_and_tag_filters(window, make_torrent):
    window.current_status_filter = "downloading"
    window.current_category_filter = "movies"
    window.current_tag_filter = "tag1"
    window._sync_torrent_map = {"enabled": {}}
    window.all_torrents = [
        make_torrent(hash="h1", state="downloading", category="movies", tags="tag1"),
        make_torrent(hash="h2", state="seeding", category="movies", tags="tag1"),
        make_torrent(hash="h3", state="downloading", category="tv", tags="tag1"),
        make_torrent(hash="h4", state="downloading", category="movies", tags="tag2"),
    ]

    window._apply_filters()
    assert [t.hash for t in window.filtered_torrents] == ["h1"]


def test_apply_filters_skips_local_remote_equivalent_filters_when_remote_filtered(
    window, monkeypatch, make_torrent
):
    window.current_status_filter = "active"
    window.current_category_filter = "movies"
    window.current_tag_filter = "tag1"
    window._sync_torrent_map = {"enabled": {}}
    window._latest_torrent_fetch_remote_filtered = True
    window.all_torrents = [
        make_torrent(hash="h1", state="stalleddl", category="movies", tags="tag1"),
    ]

    monkeypatch.setattr(window, "_torrent_matches_status_filter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(window, "_torrent_matches_category_filter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(window, "_torrent_matches_tag_filter", lambda *_args, **_kwargs: False)

    window._apply_filters()
    assert [t.hash for t in window.filtered_torrents] == ["h1"]

    window._latest_torrent_fetch_remote_filtered = False
    window._apply_filters()
    assert [t.hash for t in window.filtered_torrents] == []


def test_on_torrents_loaded_tracks_remote_filtered_flag(window, monkeypatch, make_torrent):
    monkeypatch.setattr(window, "_get_cache_refresh_candidates", lambda **_kwargs: {})
    monkeypatch.setattr(window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None)

    torrents = [make_torrent(hash="h1", name="One")]
    window._on_torrents_loaded(
        {"success": True, "data": torrents, "elapsed": 0.01, "remote_filtered": True}
    )
    assert window._latest_torrent_fetch_remote_filtered is True

    window._on_torrents_loaded(
        {"success": True, "data": torrents, "elapsed": 0.01, "remote_filtered": False}
    )
    assert window._latest_torrent_fetch_remote_filtered is False


def test_refresh_selects_first_torrent_row(window, monkeypatch, make_torrent):
    monkeypatch.setattr(window, "_get_cache_refresh_candidates", lambda **_kwargs: {})
    monkeypatch.setattr(window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None)

    torrents = [
        make_torrent(hash="h_first", name="First"),
        make_torrent(hash="h_second", name="Second"),
    ]
    window._on_torrents_loaded({"success": True, "data": torrents, "elapsed": 0.01})

    assert window._get_selected_torrent_hashes() == ["h_first"]


def test_refresh_keeps_previously_selected_torrent_when_still_present(window, monkeypatch, make_torrent):
    monkeypatch.setattr(window, "_get_cache_refresh_candidates", lambda **_kwargs: {})
    monkeypatch.setattr(window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None)

    initial = [
        make_torrent(hash="h_first", name="First"),
        make_torrent(hash="h_keep", name="Keep"),
    ]
    window.filtered_torrents = initial
    window._update_torrents_table()
    window.tbl_torrents.selectRow(1)
    assert window._get_selected_torrent_hashes() == ["h_keep"]

    refreshed = [
        make_torrent(hash="h_new", name="New"),
        make_torrent(hash="h_keep", name="Keep"),
        make_torrent(hash="h_other", name="Other"),
    ]
    window._on_torrents_loaded({"success": True, "data": refreshed, "elapsed": 0.01})

    assert window._get_selected_torrent_hashes() == ["h_keep"]


def test_refresh_selects_first_when_previous_selection_is_missing(window, monkeypatch, make_torrent):
    monkeypatch.setattr(window, "_get_cache_refresh_candidates", lambda **_kwargs: {})
    monkeypatch.setattr(window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None)

    initial = [
        make_torrent(hash="h_first", name="First"),
        make_torrent(hash="h_old", name="Old"),
    ]
    window.filtered_torrents = initial
    window._update_torrents_table()
    window.tbl_torrents.selectRow(1)
    assert window._get_selected_torrent_hashes() == ["h_old"]

    refreshed = [
        make_torrent(hash="h_first", name="First"),
        make_torrent(hash="h_second", name="Second"),
    ]
    window._on_torrents_loaded({"success": True, "data": refreshed, "elapsed": 0.01})

    first_row_item = window.tbl_torrents.item(0, 0)
    expected_first_hash = first_row_item.text() if first_row_item else ""
    assert window._get_selected_torrent_hashes() == [expected_first_hash]


def test_build_connection_info_uses_new_config_keys(window):
    conn = window._build_connection_info(
        {
            "qb_host": "127.0.0.1",
            "qb_port": 12000,
            "qb_username": "new_user",
            "qb_password": "new_pass",
            "http_basic_auth_username": "http_user",
            "http_basic_auth_password": "http_pass",
        }
    )
    assert conn["host"] == "http://127.0.0.1"
    assert conn["port"] == 12000
    assert conn["username"] == "new_user"
    assert conn["password"] == "new_pass"
    assert conn["FORCE_SCHEME_FROM_HOST"] is True
    assert conn["REQUESTS_ARGS"]["timeout"] == appmod.DEFAULT_HTTP_TIMEOUT_SECONDS
    assert "EXTRA_HEADERS" in conn
    assert conn["EXTRA_HEADERS"]["Authorization"].startswith("Basic ")


def test_build_connection_info_uses_https_scheme_override(window):
    conn = window._build_connection_info(
        {
            "qb_host": "127.0.0.1",
            "qb_port": 12000,
            "qb_username": "new_user",
            "qb_password": "new_pass",
            "http_protocol_scheme": "https",
        }
    )
    assert conn["host"] == "https://127.0.0.1"
    assert conn["FORCE_SCHEME_FROM_HOST"] is True


def test_build_connection_info_uses_custom_http_timeout(window):
    conn = window._build_connection_info(
        {
            "qb_host": "127.0.0.1",
            "qb_port": 12000,
            "qb_username": "new_user",
            "qb_password": "new_pass",
            "http_timeout": 45,
        }
    )
    assert conn["REQUESTS_ARGS"]["timeout"] == 45


def test_window_title_shows_aggregate_up_down_speeds(window, make_torrent):
    window.all_torrents = [
        make_torrent(hash="h1", dlspeed=1000, upspeed=2000),
        make_torrent(hash="h2", dlspeed=2500, upspeed=500),
    ]
    window.display_speed_mode = "bytes"
    window._update_window_title_speeds()

    title = window.windowTitle()
    assert title == "[D: 3,500, U: 2,500]"


def test_window_title_uses_custom_speed_format(window, make_torrent):
    window.all_torrents = [
        make_torrent(hash="h1", dlspeed=1000, upspeed=2000),
        make_torrent(hash="h2", dlspeed=2500, upspeed=500),
    ]
    window.display_speed_mode = "bytes"
    window.title_bar_speed_format = "U:{up_text} D:{down_text}"
    window._update_window_title_speeds()

    assert window.windowTitle() == "U:2,500 D:3,500"


def test_about_dialog_shows_computed_instance_id_and_paths(window, monkeypatch, tmp_path):
    captured = {}

    def _fake_exec(dialog):
        captured["title"] = dialog.windowTitle()
        captured["width"] = dialog.width()
        text_widgets = dialog.findChildren(appmod.QTextEdit)
        captured["text"] = text_widgets[0].toPlainText() if text_widgets else ""
        captured["wrap"] = (
            text_widgets[0].lineWrapMode()
            if text_widgets
            else appmod.QTextEdit.LineWrapMode.WidgetWidth
        )
        captured["font_family"] = (
            text_widgets[0].font().family()
            if text_widgets
            else ""
        )
        return appmod.QDialog.DialogCode.Accepted

    monkeypatch.setattr(appmod.QDialog, "exec", _fake_exec)
    ini_path = tmp_path / "qBiremoEnhanced_test.ini"
    cache_path = tmp_path / "qbiremo_enhanced.cache"
    lock_path = tmp_path / "qbiremo_enhanced_lock_test.lck"
    monkeypatch.setattr(window, "_settings_ini_path", lambda: ini_path)
    window.cache_file_path = cache_path
    window.config["_instance_lock_file_path"] = str(lock_path)

    window._show_about()

    assert captured["title"] == "About qBiremo Enhanced"
    assert f"Instance ID: {window.instance_id}" in captured["text"]
    assert f"Settings INI: {ini_path}" in captured["text"]
    assert f"Cache file: {cache_path}" in captured["text"]
    assert f"Cache temp file: {cache_path}.tmp" in captured["text"]
    assert f"Lock file: {lock_path}" in captured["text"]
    assert captured["width"] >= 1100
    assert captured["wrap"] == appmod.QTextEdit.LineWrapMode.NoWrap
    assert captured["font_family"] == appmod.QFontDatabase.systemFont(
        appmod.QFontDatabase.SystemFont.FixedFont
    ).family()


def test_statusbar_transfer_summary_shows_speeds_limits_and_session_totals(window, make_torrent):
    window.all_torrents = [
        make_torrent(
            hash="h1",
            dlspeed=1024,
            upspeed=2048,
            downloaded_session=3 * 1024,
            uploaded_session=4 * 1024,
        ),
        make_torrent(
            hash="h2",
            dlspeed=2048,
            upspeed=3 * 1024,
            downloaded_session=5 * 1024,
            uploaded_session=8 * 1024,
        ),
    ]
    window.display_speed_mode = "bytes"
    window.display_size_mode = "bytes"
    window._last_dht_nodes = 321
    window._last_global_download_limit = 10 * 1024
    window._last_global_upload_limit = 0

    window._update_statusbar_transfer_summary()

    assert window.lbl_dht_nodes.text() == "DHT: 321"
    assert window.lbl_download_summary.text() == "D: 3,072 [10,240] (8,192)"
    assert window.lbl_upload_summary.text() == "U: 5,120 [Unlimited] (12,288)"


def test_statusbar_identity_label_shows_user_host_port_and_instance_counter(window):
    assert window.lbl_instance_identity.text() == "admin@localhost:8080 [1]"


def test_statusbar_transfer_summary_follows_human_readable_mode(window, make_torrent):
    window.all_torrents = [
        make_torrent(
            hash="h1",
            dlspeed=1024,
            upspeed=2048,
            downloaded_session=3 * 1024,
            uploaded_session=4 * 1024,
        ),
        make_torrent(
            hash="h2",
            dlspeed=2048,
            upspeed=3 * 1024,
            downloaded_session=5 * 1024,
            uploaded_session=8 * 1024,
        ),
    ]
    window.display_speed_mode = "human_readable"
    window.display_size_mode = "human_readable"
    window._last_dht_nodes = 42
    window._last_global_download_limit = 2 * 1024 * 1024
    window._last_global_upload_limit = 512 * 1024

    window._update_statusbar_transfer_summary()

    assert window.lbl_dht_nodes.text() == "DHT: 42"
    assert window.lbl_download_summary.text() == "D: 3.00 KB/s [2.00 MB/s] (8.00 KB)"
    assert window.lbl_upload_summary.text() == "U: 5.00 KB/s [512.00 KB/s] (12.00 KB)"


def test_filter_tree_highlights_all_active_filters(window):
    window.current_status_filter = "downloading"
    window.current_category_filter = "movies"
    window.current_tag_filter = "tag1"
    window.current_size_bucket = (100, 200)
    window.current_tracker_filter = "tracker.example"

    window.categories = ["movies"]
    window.tags = ["tag1"]
    window.size_buckets = [(100, 200)]
    window.trackers = ["tracker.example"]

    window._update_category_tree()
    window._update_tag_tree()
    window._update_size_tree()
    window._update_tracker_tree()
    window._refresh_filter_tree_highlights()

    assert _find_filter_item(window.tree_filters, "status", "downloading").font(0).bold()
    assert _find_filter_item(window.tree_filters, "category", "movies").font(0).bold()
    assert _find_filter_item(window.tree_filters, "tag", "tag1").font(0).bold()
    assert _find_filter_item(window.tree_filters, "size", (100, 200)).font(0).bold()
    assert _find_filter_item(window.tree_filters, "tracker", "tracker.example").font(0).bold()

    # Non-active status should not be highlighted.
    assert not _find_filter_item(window.tree_filters, "status", "all").font(0).bold()


def test_filter_tree_status_category_tag_labels_include_latest_snapshot_counts(window, make_torrent):
    window.categories = ["movies", "tv"]
    window.tags = ["tag1", "tag2"]
    window._update_category_tree()
    window._update_tag_tree()

    t1 = make_torrent(
        hash="h1",
        state="downloading",
        dlspeed=200,
        upspeed=0,
        category="movies",
        tags="tag1",
    )
    t2 = make_torrent(
        hash="h2",
        state="uploading",
        dlspeed=0,
        upspeed=150,
        category="movies",
        tags="tag2",
    )
    t3 = make_torrent(
        hash="h3",
        state="pausedDL",
        dlspeed=0,
        upspeed=0,
        category="",
        tags="",
    )
    window.all_torrents = [t1, t2, t3]
    window._update_filter_tree_count_labels()

    assert _find_filter_item(window.tree_filters, "status", "all").text(0) == "All (3)"
    assert _find_filter_item(window.tree_filters, "status", "active").text(0) == "Active (2)"
    assert _find_filter_item(window.tree_filters, "status", "paused").text(0) == "Paused (1)"
    assert _find_filter_item(window.tree_filters, "category", None).text(0) == "All (3)"
    assert _find_filter_item(window.tree_filters, "category", "movies").text(0) == "movies (2)"
    assert _find_filter_item(window.tree_filters, "category", "").text(0) == "Uncategorized (1)"
    assert _find_filter_item(window.tree_filters, "tag", None).text(0) == "All (3)"
    assert _find_filter_item(window.tree_filters, "tag", "tag1").text(0) == "tag1 (1)"
    assert _find_filter_item(window.tree_filters, "tag", "").text(0) == "Untagged (1)"


def test_filter_tree_count_labels_do_not_invoke_api(window, make_torrent, monkeypatch):
    window.categories = ["movies"]
    window.tags = ["tag1"]
    window._update_category_tree()
    window._update_tag_tree()
    window.all_torrents = [
        make_torrent(hash="h1", state="downloading", dlspeed=100, category="movies", tags="tag1")
    ]

    def _forbidden_client_call():
        raise AssertionError("API client must not be used for filter counts")

    monkeypatch.setattr(window, "_create_client", _forbidden_client_call)
    window._update_filter_tree_count_labels()

    assert _find_filter_item(window.tree_filters, "status", "all").text(0) == "All (1)"
    assert _find_filter_item(window.tree_filters, "category", "movies").text(0) == "movies (1)"
    assert _find_filter_item(window.tree_filters, "tag", "tag1").text(0) == "tag1 (1)"


def test_set_auto_refresh_interval_from_menu(window, monkeypatch):
    monkeypatch.setattr(appmod.QInputDialog, "getInt", lambda *args, **kwargs: (60, True))
    window.auto_refresh_enabled = True
    window.refresh_timer.stop()

    window._set_auto_refresh_interval()

    assert window.refresh_interval == 60
    assert window.refresh_timer.isActive()
    assert window.refresh_timer.interval() == 60000
    assert window.action_auto_refresh.text() == "Enable &Auto-Refresh (60)"


def test_auto_refresh_menu_label_includes_current_interval(window):
    assert window.action_auto_refresh.text() == f"Enable &Auto-Refresh ({window.refresh_interval})"


def test_api_task_queue_ignores_stale_worker_completion(window):
    queue = window.api_queue
    active_worker = appmod.Worker(lambda **_kwargs: None)
    stale_worker = appmod.Worker(lambda **_kwargs: None)
    queue.current_worker = active_worker
    queue.current_task_name = "active"
    queue.is_processing = True

    callback_calls = {"count": 0}
    queue._on_task_complete(
        stale_worker,
        "stale",
        lambda _result: callback_calls.__setitem__("count", callback_calls["count"] + 1),
        {"success": True},
    )

    assert callback_calls["count"] == 0
    assert queue.current_worker is active_worker
    assert queue.current_task_name == "active"
    assert queue.is_processing is True


def test_api_task_queue_ignores_stale_worker_error(window):
    queue = window.api_queue
    active_worker = appmod.Worker(lambda **_kwargs: None)
    stale_worker = appmod.Worker(lambda **_kwargs: None)
    queue.current_worker = active_worker
    queue.current_task_name = "active"
    queue.is_processing = True

    queue._on_task_error(
        stale_worker,
        "stale",
        (RuntimeError, RuntimeError("boom"), "trace"),
    )

    assert queue.current_worker is active_worker
    assert queue.current_task_name == "active"
    assert queue.is_processing is True


def test_api_task_queue_ignores_cancelled_worker_completion(window):
    queue = window.api_queue
    active_worker = appmod.Worker(lambda **_kwargs: None)
    active_worker.is_cancelled = True
    queue.current_worker = active_worker
    queue.current_task_name = "active"
    queue.is_processing = True

    callback_calls = {"count": 0}
    completed_signals = {"count": 0}
    queue.task_completed.connect(
        lambda _task_name, _result: completed_signals.__setitem__(
            "count", completed_signals["count"] + 1
        )
    )

    queue._on_task_complete(
        active_worker,
        "active",
        lambda _result: callback_calls.__setitem__("count", callback_calls["count"] + 1),
        {"success": True},
    )

    assert callback_calls["count"] == 0
    assert completed_signals["count"] == 0


def test_api_task_queue_ignores_cancelled_worker_error(window):
    queue = window.api_queue
    active_worker = appmod.Worker(lambda **_kwargs: None)
    active_worker.is_cancelled = True
    queue.current_worker = active_worker
    queue.current_task_name = "active"
    queue.is_processing = True

    failed_signals = {"count": 0}
    queue.task_failed.connect(
        lambda _task_name, _error: failed_signals.__setitem__(
            "count", failed_signals["count"] + 1
        )
    )

    queue._on_task_error(
        active_worker,
        "active",
        (RuntimeError, RuntimeError("boom"), "trace"),
    )

    assert failed_signals["count"] == 0


def test_api_task_queue_coalesces_latest_task_while_worker_running(window, monkeypatch):
    queue = window.api_queue
    active_worker = appmod.Worker(lambda **_kwargs: None)
    queue.current_worker = active_worker
    queue.current_task_name = "active"
    queue.is_processing = True

    cancelled_calls = {"count": 0}
    monkeypatch.setattr(
        active_worker,
        "cancel",
        lambda: cancelled_calls.__setitem__("count", cancelled_calls["count"] + 1),
    )

    started_calls = {"count": 0}
    monkeypatch.setattr(
        queue.threadpool,
        "start",
        lambda _worker: started_calls.__setitem__("count", started_calls["count"] + 1),
    )

    cancelled_signals = {"count": 0}
    queue.task_cancelled.connect(
        lambda _task_name: cancelled_signals.__setitem__(
            "count", cancelled_signals["count"] + 1
        )
    )

    queue.add_task("next_task", lambda **_kwargs: None, lambda _result: None)

    assert cancelled_calls["count"] == 1
    assert queue.current_worker is active_worker
    assert queue.pending_task is not None
    assert queue.pending_task[0] == "next_task"
    assert started_calls["count"] == 0
    assert cancelled_signals["count"] == 0


def test_api_task_queue_starts_pending_task_when_current_worker_finishes(window, monkeypatch):
    queue = window.api_queue
    active_worker = appmod.Worker(lambda **_kwargs: None)
    queue.current_worker = active_worker
    queue.current_task_name = "active"
    queue.is_processing = True
    queue.pending_task = ("next_task", lambda **_kwargs: None, lambda _result: None, (), {})

    started = {"task_name": None}
    monkeypatch.setattr(
        queue,
        "_start_task",
        lambda task_name, fn, callback, *args, **kwargs: started.__setitem__(
            "task_name", task_name
        ),
    )

    queue._on_worker_finished(active_worker)

    assert started["task_name"] == "next_task"
    assert queue.pending_task is None


def test_refresh_torrents_skips_when_api_queue_busy_with_non_refresh_task(window, monkeypatch):
    queue = window.api_queue
    queue.current_worker = appmod.Worker(lambda **_kwargs: None)
    queue.current_task_name = "pause_torrent"
    queue.pending_task = None
    window._refresh_torrents_in_progress = False

    add_calls = {"count": 0}
    monkeypatch.setattr(
        queue,
        "add_task",
        lambda *args, **kwargs: add_calls.__setitem__("count", add_calls["count"] + 1),
    )

    window._refresh_torrents()

    assert add_calls["count"] == 0
    assert window._refresh_torrents_in_progress is False


def test_refresh_torrents_skips_when_pending_task_is_non_refresh(window, monkeypatch):
    queue = window.api_queue
    queue.current_worker = appmod.Worker(lambda **_kwargs: None)
    queue.current_task_name = "refresh_torrents"
    queue.pending_task = ("pause_torrent", lambda **_kwargs: None, None, (), {})
    window._refresh_torrents_in_progress = False

    add_calls = {"count": 0}
    monkeypatch.setattr(
        queue,
        "add_task",
        lambda *args, **kwargs: add_calls.__setitem__("count", add_calls["count"] + 1),
    )

    window._refresh_torrents()

    assert add_calls["count"] == 0
    assert window._refresh_torrents_in_progress is False


def test_auto_refresh_pauses_while_edit_tab_is_selected(window):
    window.auto_refresh_enabled = True
    window.refresh_interval = 9
    window._set_torrent_edit_enabled(True, "Editing torrent")

    window.detail_tabs.setCurrentIndex(0)
    window._sync_auto_refresh_timer_state()
    assert window.refresh_timer.isActive() is True

    window.detail_tabs.setCurrentWidget(window.tab_torrent_edit)
    assert window.refresh_timer.isActive() is False

    window.detail_tabs.setCurrentIndex(0)
    assert window.refresh_timer.isActive() is True
    assert window.refresh_timer.interval() == 9000


def test_task_completion_bumps_auto_refresh_interval_when_elapsed_exceeds_current(window, monkeypatch):
    window.auto_refresh_enabled = True
    window.refresh_interval = 5
    window._sync_auto_refresh_timer_state()
    assert window.refresh_timer.isActive() is True
    assert window.refresh_timer.interval() == 5000

    save_calls = {"count": 0}
    monkeypatch.setattr(
        window,
        "_save_refresh_settings",
        lambda: save_calls.__setitem__("count", save_calls["count"] + 1),
    )

    window._on_task_completed("refresh_torrents", {"success": True, "elapsed": 6.2})

    assert window.refresh_interval == 25
    assert window.action_auto_refresh.text() == "Enable &Auto-Refresh (25)"
    assert window.refresh_timer.isActive() is True
    assert window.refresh_timer.interval() == 25000
    assert save_calls["count"] == 1


def test_task_completion_does_not_bump_auto_refresh_interval_when_elapsed_is_not_longer(window, monkeypatch):
    window.auto_refresh_enabled = True
    window.refresh_interval = 7
    window._update_auto_refresh_action_text()
    window._sync_auto_refresh_timer_state()

    save_calls = {"count": 0}
    monkeypatch.setattr(
        window,
        "_save_refresh_settings",
        lambda: save_calls.__setitem__("count", save_calls["count"] + 1),
    )

    window._on_task_completed("refresh_torrents", {"success": True, "elapsed": 7.0})
    window._on_task_completed("refresh_torrents", {"success": True})
    window._on_task_completed("refresh_torrents", None)

    assert window.refresh_interval == 7
    assert window.action_auto_refresh.text() == "Enable &Auto-Refresh (7)"
    assert window.refresh_timer.interval() == 7000
    assert save_calls["count"] == 0


def test_refresh_torrents_skips_reentry_while_request_is_in_progress(window, monkeypatch):
    calls = {"count": 0}
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda *args, **kwargs: calls.__setitem__("count", calls["count"] + 1),
    )
    window._refresh_torrents_in_progress = True

    window._refresh_torrents()

    assert calls["count"] == 0


def test_refresh_torrents_pauses_auto_refresh_timer_until_load_finishes(
    window, monkeypatch, make_torrent
):
    window.auto_refresh_enabled = True
    window.refresh_interval = 5
    window._update_auto_refresh_action_text()
    window._sync_auto_refresh_timer_state()
    assert window.refresh_timer.isActive() is True

    captured = {"task_name": None}
    monkeypatch.setattr(
        window.api_queue,
        "add_task",
        lambda task_name, fn, callback, *args, **kwargs: captured.__setitem__(
            "task_name", task_name
        ),
    )

    window._refresh_torrents()

    assert captured["task_name"] == "refresh_torrents"
    assert window._refresh_torrents_in_progress is True
    assert window.refresh_timer.isActive() is False

    monkeypatch.setattr(window, "_get_cache_refresh_candidates", lambda **_kwargs: {})
    monkeypatch.setattr(window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None)
    window._on_torrents_loaded(
        {"success": True, "data": [make_torrent(hash="h1", name="One")], "elapsed": 0.01}
    )

    assert window._refresh_torrents_in_progress is False
    assert window.refresh_timer.isActive() is True
    assert window.refresh_timer.interval() == 5000


def test_refresh_torrents_failure_resumes_auto_refresh_timer(window):
    window.auto_refresh_enabled = True
    window.refresh_interval = 4
    window._sync_auto_refresh_timer_state()
    assert window.refresh_timer.isActive() is True

    window._set_refresh_torrents_in_progress(True)
    assert window.refresh_timer.isActive() is False

    window._on_task_failed("refresh_torrents", "boom")

    assert window._refresh_torrents_in_progress is False
    assert window.refresh_timer.isActive() is True
    assert window.refresh_timer.interval() == 4000


def test_clear_cache_and_refresh_action(window, monkeypatch):
    window.content_cache = {"h1": {"state": "downloading", "files": [{"name": "a.bin"}]}}
    window.current_content_files = [{"name": "a.bin"}]
    window.cache_file_path.write_text("{}", encoding="utf-8")
    assert window.cache_file_path.exists()

    calls = {"count": 0}
    monkeypatch.setattr(window, "_refresh_torrents", lambda: calls.__setitem__("count", calls["count"] + 1))

    window._clear_cache_and_refresh()

    assert window.content_cache == {}
    assert window.current_content_files == []
    assert calls["count"] == 1
    assert not window.cache_file_path.exists()
    assert window._suppress_next_cache_save is True


def test_clear_cache_suppresses_next_cache_file_write(window, monkeypatch, tmp_path):
    # Simulate Clear Cache action having been used.
    window._suppress_next_cache_save = True
    window.cache_file_path = tmp_path / "qbiremo_enhanced.cache"

    save_calls = {"count": 0}
    monkeypatch.setattr(window, "_save_content_cache", lambda: save_calls.__setitem__("count", save_calls["count"] + 1))
    monkeypatch.setattr(window, "_apply_filters", lambda: None)

    window._on_content_cache_refreshed(
        {
            "success": True,
            "data": {"h1": {"state": "downloading", "files": [{"name": "x.bin", "size": 1, "progress": 0.1, "priority": 1}]}},
            "errors": {},
            "elapsed": 0.01,
        }
    )

    assert save_calls["count"] == 0
    assert window._suppress_next_cache_save is False
    assert "h1" in window.content_cache


def test_reset_view_restores_layout_filters_and_refresh_defaults(window, monkeypatch):
    refresh_calls = {"count": 0}
    monkeypatch.setattr(
        window,
        "_refresh_torrents",
        lambda: refresh_calls.__setitem__("count", refresh_calls["count"] + 1),
    )
    monkeypatch.setattr(window, "_save_refresh_settings", lambda: None)
    monkeypatch.setattr(
        appmod.QMessageBox,
        "question",
        lambda *args, **kwargs: appmod.QMessageBox.StandardButton.Yes,
    )

    # Disturb splitters/columns/order/sort.
    window.main_splitter.setSizes([700, 400])
    window.right_splitter.setSizes([250, 650])
    header = window.tbl_torrents.horizontalHeader()
    header.moveSection(header.visualIndex(12), 1)
    window.tbl_torrents.setColumnWidth(1, 111)
    window.tbl_torrents.sortItems(1, Qt.SortOrder.AscendingOrder)

    # Disturb quick filters/content filter.
    window.cmb_private.setCurrentText("Yes")
    window.txt_name_filter.setText("ubuntu")
    window.txt_file_filter.setText("*.mkv")
    window.txt_content_filter.setText("sample")

    # Disturb API-backed filters.
    window.current_status_filter = "paused"
    window.current_category_filter = "movies"
    window.current_tag_filter = "tag1"
    window.current_size_bucket = (1, 2)
    window.current_tracker_filter = "tracker.example"

    # Disturb refresh settings.
    window.auto_refresh_enabled = True
    window.refresh_interval = 5
    window.refresh_timer.start(5000)
    window.action_auto_refresh.setChecked(True)

    window._reset_view_defaults()

    main_sizes = window.main_splitter.sizes()
    assert main_sizes
    assert main_sizes != [700, 400]
    assert window.right_splitter.saveState() == window._default_right_splitter_state
    assert window.tbl_torrents.horizontalHeader().saveState() == window._default_torrent_header_state

    assert window.cmb_private.currentText() == "All"
    assert window.txt_name_filter.text() == ""
    assert window.txt_file_filter.text() == ""
    assert window.txt_content_filter.text() == ""

    assert window.current_status_filter == window.default_status_filter
    assert window.current_category_filter is None
    assert window.current_tag_filter is None
    assert window.current_size_bucket is None
    assert window.current_tracker_filter is None

    assert window.refresh_interval == window.default_refresh_interval
    assert window.auto_refresh_enabled == window.default_auto_refresh_enabled
    assert window.action_auto_refresh.isChecked() == window.default_auto_refresh_enabled
    assert window.refresh_timer.isActive() == window.default_auto_refresh_enabled

    assert refresh_calls["count"] == 1


def test_reset_view_cancel_keeps_current_state(window, monkeypatch):
    monkeypatch.setattr(
        appmod.QMessageBox,
        "question",
        lambda *args, **kwargs: appmod.QMessageBox.StandardButton.No,
    )

    window.current_status_filter = "paused"
    window.refresh_interval = 77
    window.auto_refresh_enabled = True
    window.action_auto_refresh.setChecked(True)
    window.txt_name_filter.setText("keepme")

    window._reset_view_defaults()

    assert window.current_status_filter == "paused"
    assert window.refresh_interval == 77
    assert window.auto_refresh_enabled is True
    assert window.action_auto_refresh.isChecked() is True
    assert window.txt_name_filter.text() == "keepme"


def test_reset_view_invokes_default_left_panel_width_logic(window, monkeypatch):
    calls = {"count": 0}
    original = window._apply_default_main_splitter_width

    def _wrapped():
        calls["count"] += 1
        original()

    monkeypatch.setattr(window, "_apply_default_main_splitter_width", _wrapped)
    monkeypatch.setattr(window, "_save_refresh_settings", lambda: None)
    monkeypatch.setattr(
        appmod.QMessageBox,
        "question",
        lambda *args, **kwargs: appmod.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(window, "_refresh_torrents", lambda: None)

    window._reset_view_defaults()

    assert calls["count"] == 1


def test_main_window_starts_maximized(window):
    assert bool(window.windowState() & Qt.WindowState.WindowMaximized)


def test_clear_cache_refresh_action_is_under_view_menu(window):
    action_in_view = _find_menu_action(window, "&View", "Clear Cache && &Refresh")
    action_in_file = _find_menu_action(window, "&File", "Clear Cache && &Refresh")

    assert action_in_view is not None
    assert _shortcut_text(action_in_view) == "ctrl+f5"
    assert action_in_file is None


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
    monkeypatch.setattr(window, "_fit_torrent_columns", lambda: calls.__setitem__("count", calls["count"] + 1))

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

    tracker_action = _find_submenu_action(
        window, "&View", "Torrent &Columns", "Tracker"
    )
    assert tracker_action is not None
    assert tracker_action.isCheckable()
    assert tracker_action.isChecked() is True

    tracker_action.setChecked(False)
    assert window.tbl_torrents.isColumnHidden(tracker_index)

    tracker_action.setChecked(True)
    assert not window.tbl_torrents.isColumnHidden(tracker_index)


def test_torrent_columns_menu_contains_view_management_actions(window):
    assert _find_submenu_action(window, "&View", "Torrent &Columns", "Basic View") is not None
    assert _find_submenu_action(window, "&View", "Torrent &Columns", "Medium View") is not None
    assert _find_submenu_action(window, "&View", "Torrent &Columns", "Save Current View..") is not None
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
    assert (
        window.tbl_torrents.contextMenuPolicy()
        == appmod.Qt.ContextMenuPolicy.DefaultContextMenu
    )


def test_torrent_table_cells_are_not_editable(window):
    assert (
        window.tbl_torrents.editTriggers()
        == appmod.QAbstractItemView.EditTrigger.NoEditTriggers
    )


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
        lambda config_path, instance_counter=None: calls.append(
            (config_path, instance_counter)
        ),
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
        lambda config_path, instance_counter=None: calls.append(
            (config_path, instance_counter)
        ),
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
            return f"payload-{torrent_hash}".encode("utf-8")

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


def test_toggle_debug_logging_updates_state_and_persists(window, monkeypatch):
    calls = {"count": 0}
    monkeypatch.setattr(window, "_save_settings", lambda: calls.__setitem__("count", calls["count"] + 1))

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
    response_lines = [line for line in caplog.text.splitlines() if "[API RESP] torrents_info" in line]
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
    monkeypatch.setattr(appmod, "_open_file_in_default_app", lambda p: opened.__setitem__("path", p))
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
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("confirmation should not be called")),
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


def test_set_selected_content_priority_queues_expected_api_payload(window, monkeypatch, make_torrent):
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


def test_rename_selected_content_item_queues_expected_api_payload(window, monkeypatch, make_torrent):
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
    monkeypatch.setattr(window, "_display_torrent_details", lambda torrent: (_ for _ in ()).throw(AssertionError("should not display")))

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
    monkeypatch.setattr(window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None)
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


def test_enter_with_missing_local_directory_does_not_open(window, monkeypatch, make_torrent, tmp_path):
    missing_dir = tmp_path / "missing" / "Torrent B"
    torrent = make_torrent(hash="h2", name="Torrent B", content_path=str(missing_dir), save_path=str(missing_dir))
    window.all_torrents = [torrent]
    window.filtered_torrents = [torrent]
    monkeypatch.setattr(window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None)
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


def test_double_click_in_torrent_table_opens_local_directory(window, monkeypatch, make_torrent, tmp_path):
    local_dir = tmp_path / "downloads_dblclick"
    local_dir.mkdir(parents=True)

    torrent = make_torrent(hash="h_dbl", name="Double Click", content_path=str(local_dir))
    window.all_torrents = [torrent]
    window.filtered_torrents = [torrent]
    monkeypatch.setattr(window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None)
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


def test_enter_in_content_tree_opens_selected_local_file(window, monkeypatch, make_torrent, tmp_path):
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


def test_enter_in_content_tree_with_missing_file_does_not_open(window, monkeypatch, make_torrent, tmp_path):
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


def test_enter_on_torrent_expands_env_var_directory_path(window, monkeypatch, make_torrent, tmp_path):
    local_dir = tmp_path / "downloads_env"
    local_dir.mkdir(parents=True)
    monkeypatch.setenv("QBIREMO_TEST_DIR", str(local_dir))

    torrent = make_torrent(hash="h_env", name="Env Torrent", save_path="%QBIREMO_TEST_DIR%")
    window.all_torrents = [torrent]
    window.filtered_torrents = [torrent]
    monkeypatch.setattr(window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None)
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


def test_content_tree_event_filter_handles_enter_and_opens_file(window, monkeypatch, make_torrent, tmp_path):
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
