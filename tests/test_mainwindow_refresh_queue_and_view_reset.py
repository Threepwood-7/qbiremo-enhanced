import qbiremo_enhanced.main_window as appmod
from PySide6.QtCore import Qt


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


def test_default_refresh_interval_uses_new_baseline(window):
    assert window.default_refresh_interval == 30
    assert window.refresh_interval == 30


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
        lambda _task_name, _error: failed_signals.__setitem__("count", failed_signals["count"] + 1)
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
        lambda _task_name: cancelled_signals.__setitem__("count", cancelled_signals["count"] + 1)
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


def test_task_completion_bumps_auto_refresh_interval_when_elapsed_exceeds_current(
    window, monkeypatch
):
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


def test_task_completion_does_not_bump_auto_refresh_interval_when_elapsed_is_not_longer(
    window, monkeypatch
):
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


def test_task_completion_bump_respects_auto_refresh_max_cap(window, monkeypatch):
    window.auto_refresh_enabled = True
    window.refresh_interval = 100
    window._sync_auto_refresh_timer_state()
    assert window.refresh_timer.interval() == 100000

    save_calls = {"count": 0}
    monkeypatch.setattr(
        window,
        "_save_refresh_settings",
        lambda: save_calls.__setitem__("count", save_calls["count"] + 1),
    )

    window._on_task_completed("refresh_torrents", {"success": True, "elapsed": 160.0})

    assert window.refresh_interval == 600
    assert window.action_auto_refresh.text() == "Enable &Auto-Refresh (600)"
    assert window.refresh_timer.interval() == 600000
    assert save_calls["count"] == 1


def test_ui_cycle_elapsed_can_bump_and_persist_auto_refresh_interval(window, monkeypatch):
    window.auto_refresh_enabled = True
    window.refresh_interval = 2
    window._sync_auto_refresh_timer_state()
    assert window.refresh_timer.interval() == 2000

    save_calls = {"count": 0}
    monkeypatch.setattr(
        window,
        "_save_refresh_settings",
        lambda: save_calls.__setitem__("count", save_calls["count"] + 1),
    )

    window._maybe_bump_auto_refresh_interval_for_elapsed(
        source="ui_refresh_cycle",
        task_name="torrents_loaded",
        elapsed_seconds=2.6,
    )

    assert window.refresh_interval == 11
    assert window.action_auto_refresh.text() == "Enable &Auto-Refresh (11)"
    assert window.refresh_timer.interval() == 11000
    assert save_calls["count"] == 1


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
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )
    window._on_torrents_loaded(
        {"success": True, "data": [make_torrent(hash="h1", name="One")], "elapsed": 0.01}
    )

    assert window._refresh_torrents_in_progress is False
    assert window.refresh_timer.isActive() is True
    assert window.refresh_timer.interval() == 5000


def test_on_torrents_loaded_reports_ui_cycle_elapsed_for_interval_bump(
    window, monkeypatch, make_torrent
):
    monkeypatch.setattr(window, "_get_cache_refresh_candidates", lambda **_kwargs: {})
    monkeypatch.setattr(
        window, "_load_selected_torrent_network_details", lambda *_args, **_kwargs: None
    )

    calls = {"source": "", "task_name": "", "elapsed_seconds": 0.0}
    monkeypatch.setattr(
        window,
        "_maybe_bump_auto_refresh_interval_for_elapsed",
        lambda source, task_name, elapsed_seconds: calls.update(
            {
                "source": source,
                "task_name": task_name,
                "elapsed_seconds": float(elapsed_seconds),
            }
        ),
    )

    window._on_torrents_loaded(
        {"success": True, "data": [make_torrent(hash="h1", name="One")], "elapsed": 0.01}
    )

    assert calls["source"] == "ui_refresh_cycle"
    assert calls["task_name"] == "torrents_loaded"
    assert calls["elapsed_seconds"] >= 0.0


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
    monkeypatch.setattr(
        window, "_refresh_torrents", lambda: calls.__setitem__("count", calls["count"] + 1)
    )

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
    monkeypatch.setattr(
        window,
        "_save_content_cache",
        lambda: save_calls.__setitem__("count", save_calls["count"] + 1),
    )
    monkeypatch.setattr(window, "_apply_filters", lambda: None)

    window._on_content_cache_refreshed(
        {
            "success": True,
            "data": {
                "h1": {
                    "state": "downloading",
                    "files": [{"name": "x.bin", "size": 1, "progress": 0.1, "priority": 1}],
                }
            },
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
    assert (
        window.tbl_torrents.horizontalHeader().saveState() == window._default_torrent_header_state
    )

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
