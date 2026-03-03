import os
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import qbiremo_enhanced.main_window as appmod


@pytest.fixture
def make_torrent():
    def _make(**overrides):
        data = {
            "hash": "hash",
            "name": "Torrent",
            "size": 0,
            "total_size": 0,
            "progress": 0.0,
            "state": "downloading",
            "dlspeed": 0,
            "upspeed": 0,
            "ratio": 0.0,
            "num_seeds": 0,
            "num_leechs": 0,
            "num_complete": 0,
            "num_incomplete": 0,
            "added_on": 0,
            "category": "",
            "tags": "",
            "tracker": "",
            "private": False,
            "downloaded": 0,
            "uploaded": 0,
            "completion_on": 0,
            "last_activity": 0,
            "save_path": "",
            "content_path": "",
            "num_files": 0,
        }
        data.update(overrides)
        return SimpleNamespace(**data)

    return _make


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    cache_path = tmp_path / "qbiremo_enhanced.cache"
    monkeypatch.setattr(appmod, "CACHE_FILE_NAME", str(cache_path))
    monkeypatch.setattr(appmod.MainWindow, "_initial_load", lambda self: None)
    monkeypatch.setattr(appmod.MainWindow, "_load_settings", lambda self: None)
    monkeypatch.setattr(appmod.MainWindow, "_save_settings", lambda self: None)
    monkeypatch.setattr(appmod.MainWindow, "show", lambda self: None)

    win = appmod.MainWindow({"auto_refresh": False, "refresh_interval": 60})
    qtbot.addWidget(win)
    win.refresh_timer.stop()
    return win
