from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import pytest

import qbiremo_enhanced.main_window as appmod

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class _SignalStub:
    def __init__(self) -> None:
        self._callbacks: list[Callable[..., object]] = []

    def connect(self, callback: Callable[..., object]) -> None:
        self._callbacks.append(callback)

    def emit(self) -> None:
        for callback in list(self._callbacks):
            callback()


class _ClipboardStub:
    def __init__(self) -> None:
        self._text = ""
        self.dataChanged = _SignalStub()

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = str(text)
        self.dataChanged.emit()

    def text(self) -> str:
        return self._text


class _FakeTorrent(dict[str, object]):
    _INT_DEFAULTS: ClassVar[dict[str, int]] = {
        "added_on": 0,
        "amount_left": 0,
        "availability": 0,
        "completed": 0,
        "completion_on": 0,
        "dl_limit": 0,
        "dlspeed": 0,
        "downloaded": 0,
        "downloaded_session": 0,
        "eta": 0,
        "f_l_piece_prio": 0,
        "last_activity": 0,
        "max_ratio": 0,
        "max_seeding_time": 0,
        "num_complete": 0,
        "num_incomplete": 0,
        "num_leechs": 0,
        "num_seeds": 0,
        "priority": 0,
        "reannounce": 0,
        "seeding_time": 0,
        "seeding_time_limit": 0,
        "seen_complete": 0,
        "size": 0,
        "time_active": 0,
        "total_size": 0,
        "up_limit": 0,
        "uploaded": 0,
        "uploaded_session": 0,
        "upspeed": 0,
    }
    _FLOAT_DEFAULTS: ClassVar[dict[str, float]] = {"progress": 0.0, "ratio": 0.0}
    _BOOL_DEFAULTS: ClassVar[dict[str, bool]] = {
        "auto_tmm": False,
        "force_start": False,
        "private": False,
        "seq_dl": False,
        "super_seeding": False,
    }
    _STR_DEFAULTS: ClassVar[dict[str, str]] = {
        "category": "",
        "content_path": "",
        "download_path": "",
        "hash": "",
        "magnet_uri": "",
        "name": "",
        "save_path": "",
        "state": "pausedDL",
        "tags": "",
        "tracker": "",
    }

    def __getattr__(self, name: str) -> object:
        if name in self:
            return self[name]
        if name in self._INT_DEFAULTS:
            return self._INT_DEFAULTS[name]
        if name in self._FLOAT_DEFAULTS:
            return self._FLOAT_DEFAULTS[name]
        if name in self._BOOL_DEFAULTS:
            return self._BOOL_DEFAULTS[name]
        if name in self._STR_DEFAULTS:
            return self._STR_DEFAULTS[name]
        raise AttributeError(name)

    def __setattr__(self, name: str, value: object) -> None:
        if name.startswith("_"):
            super().__setattr__(name, value)
            return
        self[name] = value


def _default_instance_id() -> str:
    return appmod.compute_instance_id_from_config({})


@pytest.fixture
def window(
    qtbot: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> appmod.MainWindow:
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "qsettings"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(appmod.MainWindow, "_initial_load", lambda self: None)
    widget = appmod.MainWindow(
        {
            "auto_refresh": False,
            "refresh_interval": 60,
            "_instance_id": _default_instance_id(),
        }
    )
    clipboard = _ClipboardStub()
    monkeypatch.setattr(
        appmod.QApplication, "clipboard", staticmethod(lambda: clipboard)
    )
    widget._clipboard = clipboard
    widget.display_size_mode = "human"
    widget.display_speed_mode = "human"
    widget.action_human_readable.setChecked(True)
    qtbot.addWidget(widget)
    yield widget
    widget.close()


@pytest.fixture
def make_torrent() -> Callable[..., _FakeTorrent]:
    def _factory(**overrides: object) -> _FakeTorrent:
        data: dict[str, object] = {}
        data.update(_FakeTorrent._INT_DEFAULTS)
        data.update(_FakeTorrent._FLOAT_DEFAULTS)
        data.update(_FakeTorrent._BOOL_DEFAULTS)
        data.update(_FakeTorrent._STR_DEFAULTS)
        data.update({"state": "downloading", "name": "Torrent", "hash": "hash-1"})
        data.update(overrides)
        torrent = _FakeTorrent()
        torrent.update(data)
        return torrent

    return _factory
