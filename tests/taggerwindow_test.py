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


@pytest.mark.parametrize("window_color", ["white", "black"])
def test_workspace_field_and_selection_contrast(workspace, window_color):
    from PyQt6 import QtGui

    def contrast(first, second):
        def luminance(color):
            channels = [color.redF(), color.greenF(), color.blueF()]
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
            return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        low, high = sorted((luminance(first), luminance(second)))
        return (high + 0.05) / (low + 0.05)

    palette = workspace.palette()
    palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(window_color))
    workspace.setPalette(palette)
    workspace.show_editor()
    table = workspace.fileSelectionList.twList
    workspace.resize(1200, 900)
    table.setRowCount(3)
    for row in range(3):
        table.setItem(row, 0, QtWidgets.QTableWidgetItem(f"Archive {row}"))
    table.setRangeSelected(QtWidgets.QTableWidgetSelectionRange(0, 0, 1, 0), True)
    table.setFocus()
    workspace.splitter.setSizes([400, 200])
    QtWidgets.QApplication.processEvents()

    for field in (workspace.leTitle, workspace.cbFormat):
        image = field.grab().toImage()
        x = image.width() // 2
        assert contrast(image.pixelColor(x, 0), image.pixelColor(x, image.height() // 2)) >= 3

    image = table.viewport().grab().toImage()
    scale = image.devicePixelRatio()

    def row_background(row):
        point = table.visualItemRect(table.item(row, 0)).center()
        assert table.viewport().rect().contains(point)
        return image.pixelColor(round(point.x() * scale), round(point.y() * scale))

    for row in (0, 1):
        assert contrast(row_background(row), row_background(2)) >= 3
        assert contrast(row_background(row), table.palette().highlightedText().color()) >= 4.5


@pytest.mark.parametrize("write_succeeds", [True, False])
def test_save_before_switching_archives(workspace, tmp_comic, qtbot, monkeypatch, write_succeeds):
    import shutil

    from comicapi.comicarchive import ComicArchive
    from comictaggerlib import taggerwindow

    first = tmp_comic.path
    second = first.with_name("Another issue.cbz")
    shutil.copyfile(first, second)
    original_title = ComicArchive(second).read_tags("cr").title
    workspace.config[0].General__prompt_on_save = True
    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(first)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)
    workspace.leTitle.selectAll()
    qtbot.keyClicks(workspace.leTitle, "Edited first archive")
    choices = QtWidgets.QMessageBox.StandardButton
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", Mock(return_value=choices.Save))
    monkeypatch.setattr(taggerwindow.OptionalMessageDialog, "warning", Mock())
    confirmation = Mock()
    monkeypatch.setattr(taggerwindow.OptionalMessageDialog, "msg", confirmation)
    if not write_succeeds:
        monkeypatch.setattr(workspace.comic_archive, "write_tags", Mock(return_value=False))

    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(second)))
    qtbot.waitUntil(lambda: not workspace.fileSelectionList.path_load_threads)
    confirmation.assert_not_called()
    assert ComicArchive(second).read_tags("cr").title == original_title
    assert workspace.comic_archive.path == (second if write_succeeds else first)
    assert workspace.fileSelectionList.get_current_archive().path == workspace.comic_archive.path
    if write_succeeds:
        assert ComicArchive(first).read_tags("cr").title == "Edited first archive"
        assert not workspace.dirty_flag
    else:
        assert workspace.dirty_flag
        assert workspace.leTitle.text() == "Edited first archive"
        assert ComicArchive(first).read_tags("cr").title == original_title
        monkeypatch.setattr(QtWidgets.QMessageBox, "question", Mock(return_value=choices.Discard))


def test_editor_preferences_survive_metadata_refresh(workspace, tmp_comic, qtbot):
    from PyQt6 import QtGui

    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(tmp_comic.path)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)
    workspace.toolBar.hide()
    workspace.update_info_box()
    assert not workspace.toolBar.isVisible()

    font = workspace.font()
    font.setPointSize(24)
    workspace.setFont(font)
    assert workspace.label_2.fontMetrics().height() >= workspace.leSeries.fontMetrics().height() * 0.8

    palette = workspace.palette()
    palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#202426"))
    palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor("#15181a"))
    workspace.setPalette(palette)
    assert workspace.twCredits.rowCount() > 0
    for column in range(workspace.twCredits.columnCount()):
        brush = workspace.twCredits.item(0, column).background()
        assert brush.style() == QtCore.Qt.BrushStyle.NoBrush or brush.color() == palette.window().color()


def test_web_link_removal_and_localized_rating_round_trip(workspace, tmp_comic, qtbot):
    from comicapi.comicarchive import ComicArchive

    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(tmp_comic.path)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)
    assert workspace.leWebLink.count() == 1
    workspace.leWebLink.setCurrentRow(0)
    workspace.actionRemoveWebLink.trigger()
    assert workspace.dirty_flag
    workspace.dsbCriticalRating.setLocale(QtCore.QLocale("de_DE"))
    workspace.dsbCriticalRating.setValue(2.5)
    workspace.actionWrite_Tags.trigger()
    saved = ComicArchive(tmp_comic.path).read_tags("cr")
    assert not saved.web_links
    assert saved.critical_rating == 2.5


def test_archive_pane_restores_height_after_welcome(plugin_config, qtbot, monkeypatch):
    from PyQt6 import QtNetwork

    from comictaggerlib.taggerwindow import TaggerWindow

    config, talkers = plugin_config
    config[0].internal__window_height = 960
    config[0].internal__window_width = 1200
    config[0].internal__archive_list_height = 245
    config[0].Dialog_Flags__show_disclaimer = False
    config[0].Dialog_Flags__notify_plugin_changes = False
    monkeypatch.setattr(TaggerWindow, "setup_logger", lambda window: QtWidgets.QDialog(window))
    window = TaggerWindow(config, talkers, QtNetwork.QLocalServer())
    qtbot.addWidget(window)
    window.show()
    window._post_show([])
    window.show_editor()
    QtWidgets.QApplication.processEvents()
    assert abs(window.splitter.sizes()[1] - 245) <= 1


def test_delayed_save_confirmation_is_bound_to_archive(workspace, tmp_comic, qtbot, monkeypatch):
    from comictaggerlib.optionalmsgdialog import OptionalMessageDialog

    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(tmp_comic.path)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)
    workspace.config[0].General__prompt_on_save = True
    workspace.actionWrite_Tags.trigger()
    dialog = workspace.findChild(OptionalMessageDialog)
    assert dialog is not None
    write = Mock()
    monkeypatch.setattr(workspace, "write_tags", write)
    workspace.fileSelectionList.remove_archive_list([workspace.comic_archive])
    dialog.accept()
    write.assert_not_called()
    assert not workspace.actionWrite_Tags.isEnabled()


def test_save_before_removal_follows_archive_after_tags_resort(workspace, tmp_comic, qtbot, monkeypatch):
    import shutil

    from comicapi.comicarchive import ComicArchive

    first = tmp_comic.path
    second = first.with_name("Second.cbz")
    assert tmp_comic.remove_tags("cr")
    shutil.copyfile(first, second)
    files = workspace.fileSelectionList
    files.set_sorting(files.MDFlagColNum, QtCore.Qt.SortOrder.AscendingOrder)
    files.add_path_list([str(first), str(second)], recursive=False)
    qtbot.waitUntil(lambda: not files.path_load_threads)
    files.twList.selectRow(0)
    selected = workspace.comic_archive.path
    other = second if selected == first else first
    workspace.leTitle.selectAll()
    qtbot.keyClicks(workspace.leTitle, "Saved before removal")
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", Mock(return_value=QtWidgets.QMessageBox.StandardButton.Save))

    files.remove_selection()

    assert files.loaded_paths == {other}
    assert workspace.comic_archive.path == other
    assert ComicArchive(selected).read_tags("cr").title == "Saved before removal"


@pytest.mark.parametrize("raises", [False, True])
def test_partial_save_refreshes_archive_status_and_keeps_edits(workspace, tmp_comic, qtbot, monkeypatch, raises):
    from comicapi.comicarchive import ComicArchive
    from comictaggerlib import taggerwindow

    assert tmp_comic.remove_tags("cr")
    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(tmp_comic.path)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)
    files = workspace.fileSelectionList
    cell = files.twList.item(0, files.MDFlagColNum)
    assert not cell.text()
    assert not workspace.view_tag_actions["cr"].isEnabled()
    archive = workspace.comic_archive
    write = archive.write_tags

    def write_format(metadata, tag_id):
        if tag_id == "cr":
            return write(metadata, tag_id)
        if raises:
            raise OSError("Tag writer failed")
        return False

    monkeypatch.setitem(taggerwindow.tags, "second", Mock(enabled=False))
    monkeypatch.setitem(workspace.view_tag_actions, "second", Mock())
    monkeypatch.setitem(workspace.remove_tag_actions, "second", Mock())
    monkeypatch.setattr(archive, "write_tags", write_format)
    monkeypatch.setattr(taggerwindow.OptionalMessageDialog, "warning", Mock())
    workspace.config[0].Runtime_Options__tags_write = ["cr", "second"]
    workspace.leTitle.selectAll()
    qtbot.keyClicks(workspace.leTitle, "Partial save")
    try:
        assert not workspace.write_tags()
        assert ComicArchive(tmp_comic.path).read_tags("cr").title == "Partial save"
        assert "cr" in cell.text().split(", ")
        assert "Comic Rack" in workspace.lblTagList.text()
        assert workspace.view_tag_actions["cr"].isEnabled()
        assert workspace.remove_tag_actions["cr"].isEnabled()
        assert workspace.dirty_flag
        assert workspace.leTitle.text() == "Partial save"
    finally:
        workspace.clear_dirty_flag()


@pytest.mark.parametrize("window_color", ["black", "white"])
def test_save_button_changes_appearance_when_an_archive_opens(workspace, tmp_comic, qtbot, window_color):
    from PyQt6 import QtGui

    palette = workspace.palette()
    palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(window_color))
    workspace.setPalette(palette)
    workspace.show_editor()
    button = workspace.toolBar.widgetForAction(workspace.actionWrite_Tags)

    def fill_color():
        image = button.grab().toImage()
        return image.pixelColor(image.width() // 2, round(3 * image.devicePixelRatio()))

    assert not button.isEnabled()
    disabled_color = fill_color()
    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(tmp_comic.path)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)
    assert button.isEnabled()
    assert fill_color() != disabled_color


def test_save_without_write_tags_keeps_draft(workspace, tmp_comic, qtbot, monkeypatch):
    from comicapi.comicarchive import ComicArchive
    from comictaggerlib import taggerwindow

    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(tmp_comic.path)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)
    original_title = ComicArchive(tmp_comic.path).read_tags("cr").title
    workspace.config[0].Runtime_Options__tags_write = []
    workspace.leTitle.selectAll()
    qtbot.keyClicks(workspace.leTitle, "Unwritten draft")
    monkeypatch.setattr(taggerwindow.OptionalMessageDialog, "warning", Mock())
    try:
        assert not workspace.write_tags()
        assert workspace.dirty_flag
        assert workspace.leTitle.text() == "Unwritten draft"
        assert ComicArchive(tmp_comic.path).read_tags("cr").title == original_title
    finally:
        workspace.clear_dirty_flag()


def test_save_keeps_draft_when_tags_cannot_be_reloaded(workspace, tmp_comic, qtbot, monkeypatch):
    from comicapi.comicarchive import ComicArchive
    from comictaggerlib import taggerwindow

    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(tmp_comic.path)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)
    workspace.leTitle.selectAll()
    qtbot.keyClicks(workspace.leTitle, "Edited title")
    monkeypatch.setattr(taggerwindow.OptionalMessageDialog, "warning", Mock())
    monkeypatch.setattr(
        taggerwindow,
        "read_configured_tags",
        Mock(return_value=(GenericMetadata(title="Partial reload"), [], OSError("Unreadable tags"))),
    )
    try:
        assert not workspace.write_tags()
        assert ComicArchive(tmp_comic.path).read_tags("cr").title == "Edited title"
        assert workspace.dirty_flag
        assert workspace.leTitle.text() == "Edited title"
    finally:
        workspace.clear_dirty_flag()


def test_archive_pane_keeps_a_complete_row_in_a_compact_window(workspace, tmp_comic, qtbot):
    workspace.resize(800, 500)
    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(tmp_comic.path)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)
    table = workspace.fileSelectionList.twList
    workspace.resize(workspace.size().width(), 500)
    workspace.splitter.setSizes([workspace.splitter.height(), 0])
    QtWidgets.QApplication.processEvents()

    assert table.viewport().rect().contains(table.visualItemRect(table.item(0, 0)).topLeft())
    assert table.viewport().height() >= table.rowHeight(0)


def test_open_finishing_during_read_tag_prompt_preserves_save_target(workspace, tmp_comic, qtbot, monkeypatch):
    import shutil

    from comicapi.comicarchive import ComicArchive

    first = tmp_comic.path
    second = first.with_name("Another issue.cbz")
    shutil.copyfile(first, second)
    original_title = ComicArchive(second).read_tags("cr").title
    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(first)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)
    workspace.leTitle.selectAll()
    qtbot.keyClicks(workspace.leTitle, "Save before changing read tags")
    prompts = []
    choices = QtWidgets.QMessageBox.StandardButton

    def choose(_parent, title, *_args):
        prompts.append(title)
        if len(prompts) == 1:
            workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(second)))
            qtbot.waitUntil(lambda: not workspace.fileSelectionList.path_load_threads)
            return choices.Save
        return choices.Discard

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", choose)
    workspace.select_read_tags(["cr"])
    qtbot.waitUntil(lambda: workspace.comic_archive.path == second)

    assert prompts == ["Change Read Tags"]
    assert ComicArchive(first).read_tags("cr").title == "Save before changing read tags"
    assert ComicArchive(second).read_tags("cr").title == original_title
    assert workspace.fileSelectionList.get_current_archive() is workspace.comic_archive
    assert not workspace.dirty_flag


def test_archive_open_during_cancelled_close_preserves_draft(workspace, tmp_comic, qtbot, monkeypatch):
    import shutil

    first = tmp_comic.path
    second = first.with_name("Another issue.cbz")
    shutil.copyfile(first, second)
    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(first)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)
    workspace.leTitle.selectAll()
    qtbot.keyClicks(workspace.leTitle, "Keep this draft")
    prompts = []

    def cancel(_parent, title, *_args):
        prompts.append(title)
        if len(prompts) == 1:
            workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(second)))
            qtbot.waitUntil(lambda: not workspace.fileSelectionList.path_load_threads)
            assert len(prompts) == 1
        return QtWidgets.QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", cancel)
    try:
        assert not workspace.close()
        qtbot.waitUntil(lambda: len(prompts) == 2)
        assert prompts == [f"Exit {workspace.appName}", "Change Archive"]
        assert workspace.isVisible()
        assert workspace.comic_archive.path == first
        assert workspace.fileSelectionList.get_current_archive() is workspace.comic_archive
        assert workspace.dirty_flag
        assert workspace.leTitle.text() == "Keep this draft"
    finally:
        workspace.clear_dirty_flag()
