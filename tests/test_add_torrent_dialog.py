from pathlib import Path

from PySide6.QtCore import Qt

import qbiremo_enhanced as appmod


def test_add_torrent_dialog_builds_complete_file_payload(qtbot, tmp_path):
    dialog = appmod.AddTorrentDialog(categories=["movies"], tags=["tag_a", "tag_b"])
    qtbot.addWidget(dialog)

    torrent_file = tmp_path / "sample.torrent"
    torrent_file.write_bytes(b"dummy")

    dialog.txt_torrent_files.setPlainText(str(torrent_file))
    dialog.txt_save_path.setText(str(tmp_path / "save"))
    dialog.txt_download_path.setText(str(tmp_path / "downloads"))
    dialog.chk_use_download_path.setChecked(True)
    dialog.cmb_category.setCurrentText("movies")

    # Select one existing tag + add one custom tag.
    first_tag = dialog.lst_tags.item(0)
    first_tag.setCheckState(Qt.CheckState.Checked)
    dialog.txt_tags_extra.setText("custom_tag")

    dialog.txt_rename.setText("Renamed Torrent")
    dialog.txt_cookie.setText("k=v")

    dialog.chk_auto_tmm.setChecked(True)
    dialog.chk_paused.setChecked(True)
    dialog.chk_stopped.setChecked(False)
    dialog.chk_forced.setChecked(True)
    dialog.chk_add_to_top.setChecked(True)
    dialog.chk_skip_check.setChecked(True)
    dialog.chk_sequential.setChecked(True)
    dialog.chk_first_last.setChecked(True)
    dialog.chk_root_folder.setChecked(True)
    dialog.cmb_content_layout.setCurrentText("Subfolder")
    dialog.cmb_stop_condition.setCurrentText("FilesChecked")

    dialog.spn_upload_limit.setValue(1024)  # KiB/s
    dialog.spn_download_limit.setValue(2048)  # KiB/s
    dialog.spn_ratio_limit.setValue(1.5)
    dialog.spn_seeding_time_limit.setValue(120)
    dialog.spn_inactive_seeding_time_limit.setValue(60)
    dialog.cmb_share_limit_action.setCurrentText("Stop")

    data = dialog.get_torrent_data()
    assert data is not None
    assert data["torrent_files"] == str(torrent_file)
    assert data["save_path"] == str(tmp_path / "save")
    assert data["download_path"] == str(tmp_path / "downloads")
    assert data["use_download_path"] is True
    assert data["category"] == "movies"
    assert data["tags"] == "tag_a,custom_tag"
    assert data["rename"] == "Renamed Torrent"
    assert data["cookie"] == "k=v"
    assert data["is_paused"] is True
    assert data["forced"] is True
    assert data["add_to_top_of_queue"] is True
    assert data["is_skip_checking"] is True
    assert data["is_sequential_download"] is True
    assert data["is_first_last_piece_priority"] is True
    assert data["use_auto_torrent_management"] is True
    assert data["is_root_folder"] is True
    assert data["content_layout"] == "Subfolder"
    assert data["stop_condition"] == "FilesChecked"
    assert data["upload_limit"] == 1024 * 1024
    assert data["download_limit"] == 2048 * 1024
    assert data["ratio_limit"] == 1.5
    assert data["seeding_time_limit"] == 120
    assert data["inactive_seeding_time_limit"] == 60
    assert data["share_limit_action"] == "Stop"


def test_add_torrent_dialog_accepts_multi_url_source(qtbot):
    dialog = appmod.AddTorrentDialog(categories=[], tags=[])
    qtbot.addWidget(dialog)

    dialog.txt_source_urls.setPlainText(
        "magnet:?xt=urn:btih:aaa\nhttps://example.org/file.torrent"
    )
    data = dialog.get_torrent_data()

    assert data is not None
    assert "torrent_files" not in data
    assert data["urls"] == [
        "magnet:?xt=urn:btih:aaa",
        "https://example.org/file.torrent",
    ]


def test_add_torrent_dialog_rejects_missing_file_source(qtbot, monkeypatch):
    dialog = appmod.AddTorrentDialog(categories=[], tags=[])
    qtbot.addWidget(dialog)

    called = {"count": 0}
    monkeypatch.setattr(
        appmod.QMessageBox,
        "warning",
        lambda *args, **kwargs: called.__setitem__("count", called["count"] + 1),
    )

    dialog.txt_torrent_files.setPlainText(str(Path("C:/definitely/nonexistent/file.torrent")))
    data = dialog.get_torrent_data()

    assert data is None
    assert called["count"] == 1


def test_add_torrent_dialog_accepts_multiple_file_sources(qtbot, tmp_path):
    dialog = appmod.AddTorrentDialog(categories=[], tags=[])
    qtbot.addWidget(dialog)

    t1 = tmp_path / "one.torrent"
    t2 = tmp_path / "two.torrent"
    t1.write_bytes(b"1")
    t2.write_bytes(b"2")
    dialog.txt_torrent_files.setPlainText(f"{t1}\n{t2}")

    data = dialog.get_torrent_data()

    assert data is not None
    assert data["torrent_files"] == [str(t1), str(t2)]


def test_add_torrent_dialog_accept_keeps_dialog_open_when_source_is_invalid(
    qtbot, monkeypatch
):
    dialog = appmod.AddTorrentDialog(categories=[], tags=[])
    qtbot.addWidget(dialog)
    dialog.show()

    called = {"count": 0}
    monkeypatch.setattr(
        appmod.QMessageBox,
        "warning",
        lambda *args, **kwargs: called.__setitem__("count", called["count"] + 1),
    )
    dialog.txt_torrent_files.setPlainText(str(Path("C:/definitely/nonexistent/file.torrent")))

    dialog.accept()

    assert dialog.result() != appmod.QDialog.DialogCode.Accepted
    assert called["count"] == 1


def test_add_torrent_dialog_accept_caches_payload(qtbot):
    dialog = appmod.AddTorrentDialog(categories=[], tags=[])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.txt_source_urls.setPlainText("magnet:?xt=urn:btih:aaa")

    dialog.accept()

    assert dialog.result() == appmod.QDialog.DialogCode.Accepted
    assert isinstance(dialog.torrent_data, dict)
    assert dialog.torrent_data.get("urls") == "magnet:?xt=urn:btih:aaa"
