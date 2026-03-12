import os
import time

from PySide6.QtCore import QSettings

import qbiremo_enhanced.main_window as appmod


def _default_instance_id() -> str:
    return appmod.compute_instance_id_from_config({})


def _default_settings_app_name() -> str:
    return appmod.build_instance_app_name(
        appmod.SETTINGS_APP_NAME, _default_instance_id()
    )


def _make_window(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "qsettings"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    cache_path = tmp_path / "qbiremo_enhanced.cache"
    monkeypatch.setattr(appmod, "CACHE_FILE_NAME", str(cache_path))
    monkeypatch.setattr(appmod.MainWindow, "_initial_load", lambda self: None)
    monkeypatch.setattr(appmod.MainWindow, "show", lambda self: None)

    win = appmod.MainWindow(
        {
            "auto_refresh": False,
            "refresh_interval": 60,
            "_instance_id": _default_instance_id(),
        }
    )
    qtbot.addWidget(win)
    return win


def test_auto_refresh_toggle_and_interval_are_persisted(qtbot, monkeypatch, tmp_path):
    settings_root = tmp_path / "qsettings"
    settings_root.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_root)
    )

    # Start with clean app settings.
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        appmod.SETTINGS_ORG_NAME,
        _default_settings_app_name(),
    )
    settings.clear()
    settings.sync()

    w1 = _make_window(qtbot, monkeypatch, tmp_path)
    w1.refresh_interval = 37
    w1.auto_refresh_enabled = True
    w1.refresh_timer.start(w1.refresh_interval * 1000)
    w1._save_settings()
    w1.close()
    w1.deleteLater()

    # New instance should restore both values from QSettings.
    w2 = _make_window(qtbot, monkeypatch, tmp_path)
    assert w2.auto_refresh_enabled is True
    assert w2.refresh_interval == 37
    assert w2.action_auto_refresh.isChecked() is True
    assert w2.action_auto_refresh.text() == "Enable A&uto-Refresh (37)"
    assert w2.refresh_timer.isActive()
    assert w2.refresh_timer.interval() == 37000


def test_hidden_torrent_columns_are_persisted(qtbot, monkeypatch, tmp_path):
    settings_root = tmp_path / "qsettings"
    settings_root.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_root)
    )

    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        appmod.SETTINGS_ORG_NAME,
        _default_settings_app_name(),
    )
    settings.clear()
    settings.sync()

    w1 = _make_window(qtbot, monkeypatch, tmp_path)
    w1._set_torrent_column_visible("tracker", False)
    w1._set_torrent_column_visible("uploaded", False)
    w1._save_settings()
    w1.close()
    w1.deleteLater()

    w2 = _make_window(qtbot, monkeypatch, tmp_path)
    assert w2.tbl_torrents.isColumnHidden(w2.torrent_column_index["tracker"])
    assert w2.tbl_torrents.isColumnHidden(w2.torrent_column_index["uploaded"])
    assert not w2.tbl_torrents.isColumnHidden(w2.torrent_column_index["name"])


def test_display_mode_toggle_is_persisted_via_qsettings(qtbot, monkeypatch, tmp_path):
    settings_root = tmp_path / "qsettings"
    settings_root.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_root)
    )

    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        appmod.SETTINGS_ORG_NAME,
        _default_settings_app_name(),
    )
    settings.clear()
    settings.sync()

    w1 = _make_window(qtbot, monkeypatch, tmp_path)
    w1.display_size_mode = "bytes"
    w1.display_speed_mode = "bytes"
    w1.action_human_readable.setChecked(False)
    w1._save_settings()
    w1.close()
    w1.deleteLater()

    w2 = _make_window(qtbot, monkeypatch, tmp_path)
    assert w2.display_size_mode == "bytes"
    assert w2.display_speed_mode == "bytes"
    assert w2.action_human_readable.isChecked() is False


def test_old_display_mode_keys_are_ignored_on_load(qtbot, monkeypatch, tmp_path):
    settings_root = tmp_path / "qsettings"
    settings_root.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_root)
    )

    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        appmod.SETTINGS_ORG_NAME,
        _default_settings_app_name(),
    )
    settings.clear()
    settings.setValue("displaySizeMode", "human_readable")
    settings.setValue("displaySpeedMode", "human_readable")
    settings.sync()

    window = _make_window(qtbot, monkeypatch, tmp_path)

    assert window.display_size_mode == appmod.DEFAULT_DISPLAY_SIZE_MODE
    assert window.display_speed_mode == appmod.DEFAULT_DISPLAY_SPEED_MODE
    assert window.action_human_readable.isChecked() is False


def test_default_cache_path_uses_data_dir(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(appmod, "CACHE_FILE_NAME", "qbiremo_enhanced.cache")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "qsettings"))
    monkeypatch.setattr(appmod.MainWindow, "_initial_load", lambda self: None)
    monkeypatch.setattr(appmod.MainWindow, "_load_settings", lambda self: None)
    monkeypatch.setattr(appmod.MainWindow, "_save_settings", lambda self: None)
    monkeypatch.setattr(appmod.MainWindow, "show", lambda self: None)

    win = appmod.MainWindow(
        {
            "auto_refresh": False,
            "refresh_interval": 60,
            "_instance_id": _default_instance_id(),
        }
    )
    qtbot.addWidget(win)

    expected = appmod.resolve_cache_file_path(
        appmod.APP_IDENTITY,
        "qbiremo_enhanced.cache",
        instance_id=_default_instance_id(),
    )
    assert win.cache_file_path == expected

    win.content_cache = {"h1": {"state": "downloading", "files": []}}
    win._save_content_cache()
    assert expected.exists()


def test_startup_deletes_cache_file_older_than_three_days(qtbot, monkeypatch, tmp_path):
    cache_path = appmod.resolve_cache_file_path(
        appmod.APP_IDENTITY,
        str(tmp_path / "qbiremo_enhanced.cache"),
        instance_id=_default_instance_id(),
    )
    cache_path.write_text('{"h1":{"state":"downloading","files":[]}}', encoding="utf-8")
    old_mtime = time.time() - ((3 * 24 * 60 * 60) + 60)
    os.utime(cache_path, (old_mtime, old_mtime))

    win = _make_window(qtbot, monkeypatch, tmp_path)

    assert not cache_path.exists()
    assert win.content_cache == {}


def test_startup_keeps_recent_cache_file(qtbot, monkeypatch, tmp_path):
    cache_path = appmod.resolve_cache_file_path(
        appmod.APP_IDENTITY,
        str(tmp_path / "qbiremo_enhanced.cache"),
        instance_id=_default_instance_id(),
    )
    cache_path.write_text('{"h1":{"state":"downloading","files":[]}}', encoding="utf-8")
    recent_mtime = time.time() - (2 * 24 * 60 * 60)
    os.utime(cache_path, (recent_mtime, recent_mtime))

    win = _make_window(qtbot, monkeypatch, tmp_path)

    assert cache_path.exists()
    assert "h1" in win.content_cache
