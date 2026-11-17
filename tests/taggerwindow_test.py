from __future__ import annotations

import json
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


@pytest.fixture
def workspace(plugin_config, qtbot, monkeypatch):
    from PyQt6 import QtNetwork

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
    return window


def test_alternate_numbering_has_distinct_accessible_names(workspace):
    assert workspace.leAltSeries.accessibleName() == "Alternate series"
    assert workspace.leAltIssueNum.accessibleName() == "Alternate issue"
    assert workspace.leAltIssueCount.accessibleName() == "Alternate issue count"


def test_workspace_follows_palette_changes(workspace):
    from PyQt6 import QtGui

    role = QtGui.QPalette.ColorRole.Window
    palette = workspace.palette()
    palette.setColor(role, QtGui.QColor("black"))
    workspace.setPalette(palette)
    assert "#1e2326" in workspace.centralWidget.styleSheet()
    assert "#1e2326" in workspace.toolBar.styleSheet()

    palette.setColor(role, QtGui.QColor("white"))
    workspace.setPalette(palette)
    assert "#f2f4f3" in workspace.centralWidget.styleSheet()
    assert "#f2f4f3" in workspace.toolBar.styleSheet()


@pytest.mark.parametrize("draft_field", ["title", "rating"])
def test_workspace_opens_edits_and_clears_archive(workspace, tmp_comic, qtbot, monkeypatch, draft_field):
    from comicapi.comicarchive import ComicArchive

    window = workspace
    config = window.config
    assert window.welcome.isVisible()

    blank = window.welcome.findChild(QtWidgets.QPushButton, "blankEditor")
    qtbot.keyClick(blank, QtCore.Qt.Key.Key_Space)
    assert window.tabWidget.isVisible()
    assert window.leSeries.text() == ""

    if draft_field == "rating":
        window.tabWidget.setCurrentWidget(window.tab_3)
        qtbot.keyClick(window.dsbCriticalRating, QtCore.Qt.Key.Key_Up)
        rating = window.dsbCriticalRating.value()
        assert rating > 0
    else:
        qtbot.keyClicks(window.leTitle, "Draft title")
    choices = QtWidgets.QMessageBox.StandardButton
    question = Mock(side_effect=[choices.Cancel, choices.Discard])
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", question)
    archive_url = QtCore.QUrl.fromLocalFile(str(tmp_comic.path))
    window.open_file_event(archive_url)
    qtbot.waitUntil(lambda: not window.fileSelectionList.path_load_threads)
    assert question.call_args.args[3] == choices.Cancel | choices.Discard
    assert window.comic_archive is None
    assert window.fileSelectionList.twList.rowCount() == 0
    assert window.dirty_flag
    if draft_field == "rating":
        assert window.dsbCriticalRating.value() == rating
    else:
        assert window.leTitle.text() == "Draft title"

    window.open_file_event(archive_url)
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

    label = window.lblTagList
    assert label.wordWrap()
    label.setText("Tags: Comic Rack, ComicBookLover, CoMet")
    qtbot.waitUntil(lambda: label.height() >= 2 * label.fontMetrics().lineSpacing())

    window.splitter.setSizes([400, 180])
    list_height = window.splitter.sizes()[1]
    assert list_height != config[0].internal__archive_list_height
    window.fileSelectionList.remove_archive_list([window.comic_archive])
    assert window.welcome.isVisible()
    assert not window.splitter.isVisible()
    assert window.close()
    saved = json.loads(config[0].Runtime_Options__config.settings_file.read_text(encoding="utf-8"))
    assert saved["internal"]["archive_list_height"] == list_height
