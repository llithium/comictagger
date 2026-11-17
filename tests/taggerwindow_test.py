from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from comicapi.genericmetadata import GenericMetadata

QtCore = pytest.importorskip("PyQt6.QtCore")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


def test_copy_tags_keeps_cancel_available_during_the_last_archive(tmp_path, config, qtbot, monkeypatch):
    from comictaggerlib import taggerwindow

    progress = QtWidgets.QProgressDialog("", "Cancel", 0, 1)
    qtbot.addWidget(progress)
    monkeypatch.setattr(taggerwindow.QtWidgets, "QProgressDialog", Mock(return_value=progress))
    monkeypatch.setattr(taggerwindow, "center_window_on_parent", lambda dialog: dialog.show())
    monkeypatch.setattr(taggerwindow, "LogWindow", Mock())
    monkeypatch.setattr(
        taggerwindow, "read_configured_tags", Mock(return_value=(GenericMetadata(series="Test"), [], None))
    )
    window = SimpleNamespace(config=config, _reload_page=Mock(), update_info_box=Mock(), update_menus=Mock())

    def write_tag(metadata, tag_id):
        assert progress.isVisible()
        assert progress.value() < progress.maximum()
        QtCore.QTimer.singleShot(0, progress.findChild(QtWidgets.QPushButton).click)
        return True

    archive = SimpleNamespace(
        path=tmp_path / "comic.cbz", write_tags=Mock(side_effect=write_tag), reset_cache=Mock(), load_cache=Mock()
    )

    taggerwindow.TaggerWindow.copy_tags(window, ["cr"], ["comet", "cbi"], [archive])

    assert [call.args[1] for call in archive.write_tags.call_args_list] == ["comet"]
    assert not progress.isVisible()


def test_workspace_opens_edits_and_clears_archive(plugin_config, tmp_comic, qtbot, monkeypatch):
    from PyQt6 import QtNetwork

    from comicapi.comicarchive import ComicArchive
    from comictaggerlib.taggerwindow import TaggerWindow

    monkeypatch.setattr(TaggerWindow, "setup_logger", lambda window: QtWidgets.QDialog(window))
    config, talkers = plugin_config
    config[0].Dialog_Flags__show_disclaimer = False
    config[0].Dialog_Flags__notify_plugin_changes = False
    config[0].General__prompt_on_save = False
    window = TaggerWindow(config, talkers, QtNetwork.QLocalServer())
    qtbot.addWidget(window)
    window.show()
    window._post_show([])
    assert window.welcome.isVisible()

    blank = window.welcome.findChild(QtWidgets.QPushButton, "blankEditor")
    qtbot.keyClick(blank, QtCore.Qt.Key.Key_Space)
    assert window.tabWidget.isVisible()
    assert window.leSeries.text() == ""

    window.open_file_event(QtCore.QUrl.fromLocalFile(str(tmp_comic.path)))
    qtbot.waitUntil(lambda: window.comic_archive is not None)
    assert window.leSeries.text()
    for index in range(window.tabWidget.count()):
        window.tabWidget.setCurrentIndex(index)
        assert window.tabWidget.currentWidget().isVisible()
    window.tabWidget.setCurrentIndex(0)
    window.leTitle.setFocus()
    window.leTitle.selectAll()
    qtbot.keyClicks(window.leTitle, "Updated issue title")
    assert window.dirty_flag
    window.actionWrite_Tags.trigger()
    assert ComicArchive(tmp_comic.path).read_tags("cr").title == "Updated issue title"
    assert window.lblFilename.text() == "Updated issue title"
    assert not window.dirty_flag

    window.fileSelectionList.remove_archive_list([window.comic_archive])
    assert window.welcome.isVisible()
    assert not window.splitter.isVisible()
