from types import SimpleNamespace

import qbiremo_enhanced.main_window as appmod
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem


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
            raise AssertionError(
                "sync_maindata should not be used when remote filters are selected"
            )

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
            return [
                SimpleNamespace(
                    hash="h1", name="One", added_on=10, state="downloading", private=True
                )
            ]

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
            return [
                SimpleNamespace(
                    hash="h2", name="Two", added_on=20, state="downloading", private=False
                )
            ]

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
            {
                "url": "udp://tracker.one:6969/announce",
                "status": 4,
                "msg": "timed out",
                "next_announce": 10,
            },
            {"url": "udp://tracker.two:6969/announce", "status": 2, "msg": "", "next_announce": 20},
        ],
        "h2": [
            {
                "url": "udp://tracker.one:6969/announce",
                "status": 4,
                "msg": "connection refused",
                "next_announce": 30,
            },
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
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )

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
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )

    torrents = [
        make_torrent(hash="h_first", name="First"),
        make_torrent(hash="h_second", name="Second"),
    ]
    window._on_torrents_loaded({"success": True, "data": torrents, "elapsed": 0.01})

    assert window._get_selected_torrent_hashes() == ["h_first"]


def test_refresh_keeps_previously_selected_torrent_when_still_present(
    window, monkeypatch, make_torrent
):
    monkeypatch.setattr(window, "_get_cache_refresh_candidates", lambda **_kwargs: {})
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )

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


def test_refresh_selects_first_when_previous_selection_is_missing(
    window, monkeypatch, make_torrent
):
    monkeypatch.setattr(window, "_get_cache_refresh_candidates", lambda **_kwargs: {})
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )

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
        captured["font_family"] = text_widgets[0].font().family() if text_widgets else ""
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
    assert (
        captured["font_family"]
        == appmod.QFontDatabase.systemFont(appmod.QFontDatabase.SystemFont.FixedFont).family()
    )


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


def test_filter_tree_status_category_tag_labels_include_latest_snapshot_counts(
    window, make_torrent
):
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


def test_filter_tree_count_cache_updates_when_torrent_snapshot_is_replaced(window, make_torrent):
    window.categories = ["movies"]
    window.tags = ["tag1"]
    window._update_category_tree()
    window._update_tag_tree()

    window.all_torrents = [
        make_torrent(hash="h1", state="downloading", dlspeed=100, category="movies", tags="tag1")
    ]
    window._update_filter_tree_count_labels()
    assert _find_filter_item(window.tree_filters, "category", "movies").text(0) == "movies (1)"
    assert _find_filter_item(window.tree_filters, "tag", "tag1").text(0) == "tag1 (1)"

    window.all_torrents = [make_torrent(hash="h2", state="pausedDL", category="", tags="")]
    window._update_filter_tree_count_labels()
    assert _find_filter_item(window.tree_filters, "category", "movies").text(0) == "movies (0)"
    assert _find_filter_item(window.tree_filters, "tag", "tag1").text(0) == "tag1 (0)"
