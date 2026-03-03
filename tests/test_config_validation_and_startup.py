import logging

import pytest

import qbiremo_enhanced as appmod


def test_compute_instance_id_uses_length_8_and_default_counter_suffix():
    instance_id = appmod.compute_instance_id("localhost", 8080)
    base, suffix = instance_id.rsplit("_", 1)
    assert len(base) == 8
    assert suffix == "1"


def test_compute_instance_id_from_config_uses_instance_counter_suffix():
    instance_id = appmod.compute_instance_id_from_config(
        {
            "qb_host": "127.0.0.1",
            "qb_port": 8080,
            "_instance_counter": 3,
        }
    )
    base, suffix = instance_id.rsplit("_", 1)
    assert len(base) == 8
    assert suffix == "3"


def test_acquire_instance_lock_increments_counter_when_lock_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(
        appmod,
        "resolve_instance_lock_file_path",
        lambda _instance_id, counter: tmp_path / f"instance_{int(counter)}.lck",
    )
    cfg = {"qb_host": "127.0.0.1", "qb_port": 8080}
    first_counter, first_instance_id, first_lock_path = appmod.acquire_instance_lock(cfg, 1)
    assert first_counter == 1
    assert first_lock_path == tmp_path / "instance_1.lck"
    assert str(first_instance_id).endswith("_1")

    counter, instance_id, lock_path = appmod.acquire_instance_lock(cfg, 1)

    assert counter == 2
    assert lock_path == tmp_path / "instance_2.lck"
    assert lock_path.exists()
    assert str(instance_id).endswith("_2")
    appmod.release_instance_lock(lock_path)
    assert not lock_path.exists()
    appmod.release_instance_lock(first_lock_path)
    assert not first_lock_path.exists()


def test_validate_and_normalize_config_logs_invalid_values(caplog):
    caplog.set_level(logging.WARNING, logger=appmod.G_APP_NAME)
    cfg = {
        "qb_host": "",
        "qb_port": "99999",
        "http_timeout": "not-a-number",
        "qb_username": 123,
        "qb_password": None,
        "http_basic_auth_username": 1,
        "http_basic_auth_password": 2,
        "http_protocol_scheme": "ftp",
        "auto_refresh": "notabool",
        "refresh_interval": 0,
        "default_window_width": 100,
        "default_window_height": 100,
        "display_size_mode": "invalid",
        "display_speed_mode": "invalid",
        "default_status_filter": "invalid",
        "log_file": "",
        "title_bar_speed_format": 123,
        "unknown_field": True,
    }

    normalized = appmod.validate_and_normalize_config(cfg, "bad_config.toml")

    assert normalized["qb_host"] == "localhost"
    assert normalized["qb_port"] == 8080
    assert normalized["qb_username"] == "admin"
    assert normalized["qb_password"] == ""
    assert normalized["http_basic_auth_username"] == ""
    assert normalized["http_basic_auth_password"] == ""
    assert normalized["http_protocol_scheme"] == "http"
    assert normalized["http_timeout"] == appmod.DEFAULT_HTTP_TIMEOUT_SECONDS
    assert normalized["log_file"] == "qbiremo_enhanced.log"
    assert normalized["title_bar_speed_format"] == appmod.DEFAULT_TITLE_BAR_SPEED_FORMAT
    assert "auto_refresh" not in normalized
    assert "refresh_interval" not in normalized
    assert "default_window_width" not in normalized
    assert "default_window_height" not in normalized
    assert "default_status_filter" not in normalized
    assert "display_size_mode" not in normalized
    assert "display_speed_mode" not in normalized

    log_text = caplog.text
    assert "Config validation" in log_text
    assert "qb_port" in log_text
    assert "ignored in TOML; managed via QSettings" in log_text
    assert "http_protocol_scheme" in log_text
    assert "http_timeout" in log_text
    assert "title_bar_speed_format" in log_text
    assert "unknown_field" in log_text


def test_validate_and_normalize_config_maps_legacy_keys(caplog):
    caplog.set_level(logging.WARNING, logger=appmod.G_APP_NAME)
    cfg = {
        "host": "10.0.0.2",
        "port": "12345",
        "username": "legacy_user",
        "password": "legacy_pass",
        "http_user": "legacy_http_user",
        "http_password": "legacy_http_pass",
    }

    normalized = appmod.validate_and_normalize_config(cfg, "legacy_config.toml")

    assert normalized["qb_host"] == "10.0.0.2"
    assert normalized["qb_port"] == 12345
    assert normalized["qb_username"] == "legacy_user"
    assert normalized["qb_password"] == "legacy_pass"
    assert normalized["http_basic_auth_username"] == "legacy_http_user"
    assert normalized["http_basic_auth_password"] == "legacy_http_pass"
    assert "deprecated" in caplog.text


def test_validate_and_normalize_config_accepts_https_protocol_scheme():
    normalized = appmod.validate_and_normalize_config(
        {
            "qb_host": "127.0.0.1",
            "qb_port": 8080,
            "http_protocol_scheme": "https",
        },
        "scheme_config.toml",
    )
    assert normalized["http_protocol_scheme"] == "https"


def test_validate_and_normalize_config_accepts_http_timeout():
    normalized = appmod.validate_and_normalize_config(
        {
            "qb_host": "127.0.0.1",
            "qb_port": 8080,
            "http_timeout": 420,
        },
        "timeout_config.toml",
    )
    assert normalized["http_timeout"] == 420


def test_main_opens_log_file_on_startup_crash(monkeypatch, tmp_path):
    log_path = tmp_path / "startup_crash.log"
    opened = {"path": None}

    class DummyHandler:
        def __init__(self):
            self.flushed = False

        def flush(self):
            self.flushed = True

    dummy_handler = DummyHandler()

    monkeypatch.setattr(
        appmod,
        "load_config_with_issues",
        lambda _path: ({"_log_file_path": str(log_path), "log_file": str(log_path)}, []),
    )
    monkeypatch.setattr(
        appmod,
        "acquire_instance_lock",
        lambda cfg, start_counter: (
            int(start_counter),
            appmod.compute_instance_id_from_config(
                {**cfg, "_instance_counter": int(start_counter)}
            ),
            tmp_path / "instance_1.lck",
        ),
    )
    monkeypatch.setattr(appmod.atexit, "register", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(appmod, "_setup_logging", lambda _config: dummy_handler)
    monkeypatch.setattr(appmod, "_install_exception_hooks", lambda _handler: None)
    monkeypatch.setattr(
        appmod,
        "_open_file_in_default_app",
        lambda path: opened.__setitem__("path", path),
    )

    class FakeApplication:
        def __init__(self, _argv):
            pass

        def setOrganizationName(self, *_args):
            pass

        def setApplicationName(self, *_args):
            pass

        def setApplicationDisplayName(self, *_args):
            pass

        def exec(self):
            return 0

    class StartupCrashWindow:
        def __init__(self, _config):
            raise RuntimeError("startup boom")

    monkeypatch.setattr(appmod, "QApplication", FakeApplication)
    monkeypatch.setattr(appmod, "MainWindow", StartupCrashWindow)
    monkeypatch.setattr(appmod.sys, "argv", ["qbiremo_enhanced.py"])

    with pytest.raises(RuntimeError, match="startup boom"):
        appmod.main()

    assert dummy_handler.flushed is True
    assert opened["path"] == str(log_path)


def test_main_accepts_instance_counter_cli_argument(monkeypatch):
    captured = {"config": None}

    class DummyHandler:
        def flush(self):
            return None

    monkeypatch.setattr(appmod, "load_config_with_issues", lambda _path: ({}, []))
    monkeypatch.setattr(
        appmod,
        "acquire_instance_lock",
        lambda cfg, start_counter: (
            int(start_counter),
            appmod.compute_instance_id_from_config(
                {**cfg, "_instance_counter": int(start_counter)}
            ),
            appmod.Path("dummy_instance_5.lck"),
        ),
    )
    monkeypatch.setattr(appmod.atexit, "register", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(appmod, "_setup_logging", lambda _config: DummyHandler())
    monkeypatch.setattr(appmod, "_install_exception_hooks", lambda _handler: None)

    class FakeApplication:
        def __init__(self, _argv):
            pass

        def setOrganizationName(self, *_args):
            pass

        def setApplicationName(self, *_args):
            pass

        def setApplicationDisplayName(self, *_args):
            pass

        def exec(self):
            return 0

    class FakeWindow:
        def __init__(self, config):
            captured["config"] = dict(config)

    monkeypatch.setattr(appmod, "QApplication", FakeApplication)
    monkeypatch.setattr(appmod, "MainWindow", FakeWindow)
    monkeypatch.setattr(
        appmod.sys,
        "argv",
        ["qbiremo_enhanced.py", "--instance_counter", "5"],
    )

    with pytest.raises(SystemExit) as exc:
        appmod.main()

    assert int(exc.value.code) == 0
    assert captured["config"] is not None
    assert captured["config"]["_instance_counter"] == 5
    assert str(captured["config"]["_instance_id"]).endswith("_5")


def test_main_uses_incremented_instance_counter_when_lock_exists(monkeypatch):
    captured = {"config": None}

    class DummyHandler:
        def flush(self):
            return None

    monkeypatch.setattr(appmod, "load_config_with_issues", lambda _path: ({}, []))
    monkeypatch.setattr(
        appmod,
        "acquire_instance_lock",
        lambda _cfg, _start_counter: (6, "deadbeef_6", appmod.Path("dummy_instance_6.lck")),
    )
    monkeypatch.setattr(appmod.atexit, "register", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(appmod, "_setup_logging", lambda _config: DummyHandler())
    monkeypatch.setattr(appmod, "_install_exception_hooks", lambda _handler: None)

    class FakeApplication:
        def __init__(self, _argv):
            pass

        def setOrganizationName(self, *_args):
            pass

        def setApplicationName(self, *_args):
            pass

        def setApplicationDisplayName(self, *_args):
            pass

        def exec(self):
            return 0

    class FakeWindow:
        def __init__(self, config):
            captured["config"] = dict(config)

    monkeypatch.setattr(appmod, "QApplication", FakeApplication)
    monkeypatch.setattr(appmod, "MainWindow", FakeWindow)
    monkeypatch.setattr(
        appmod.sys,
        "argv",
        ["qbiremo_enhanced.py", "--instance_counter", "5"],
    )

    with pytest.raises(SystemExit) as exc:
        appmod.main()

    assert int(exc.value.code) == 0
    assert captured["config"] is not None
    assert captured["config"]["_instance_counter"] == 6
    assert captured["config"]["_instance_id"] == "deadbeef_6"
