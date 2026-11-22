from __future__ import annotations

import shutil

import pytest

QtCore = pytest.importorskip("PyQt6.QtCore")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from comictaggerlib.fileselectionlist import FileSelectionList  # noqa: E402
from testing.filenames import cbz_path  # noqa: E402


def open_comic(workspace, qtbot, path):
    workspace.open_file_event(QtCore.QUrl.fromLocalFile(str(path)))
    qtbot.waitUntil(lambda: workspace.comic_archive is not None)


def test_card_view_shows_status_chips_filters_and_switches_to_table(tmp_path, config, qtbot):
    file_list = FileSelectionList(None, config[0], lambda _title, _description: True)
    qtbot.addWidget(file_list)
    file_list.show()
    paths = [tmp_path / name for name in ("Saga 001.cbz", "Saga 002.cbz", "Paper Girls 012.cbz")]
    for path in paths:
        shutil.copy(cbz_path, path)
        file_list.add_path_item(str(path))

    assert file_list.card_view
    assert file_list.twList.horizontalHeader().isHidden()
    assert all(file_list.twList.isColumnHidden(column) for column in range(1, file_list.twList.columnCount()))
    qtbot.waitUntil(lambda: file_list.listTitle.text() == f"{tmp_path.name} · 3".upper())

    row, _archive = file_list.get_current_list_row(str(paths[0]))
    file_list.twList.item(row, file_list.MDFlagColNum).setText("")
    file_list.twList.item(row, file_list.matchColNum).setText("No match")
    assert file_list.statuses(row) == [("No match", "bad"), ("No tags", "muted")]
    # Cards lead with series and issue parsed from the name, and keep the file name on the second line.
    titles = {file_list.card_text(r) for r in range(file_list.twList.rowCount())}
    assert ("Saga #2", "Saga 002.cbz") in titles
    assert ("Paper Girls #12", "Paper Girls 012.cbz") in titles
    file_list.twList.selectRow(row)
    file_list.set_modified_flag(True)
    assert file_list.statuses(row)[0] == ("Unsaved", "acc")

    file_list.filterEdit.setText("saga")
    visible = {
        file_list.get_archive_by_row(r).path.name
        for r in range(file_list.twList.rowCount())
        if not file_list.twList.isRowHidden(r)
    }
    assert visible == {"Saga 001.cbz", "Saga 002.cbz"}

    folder = next(a for a in file_list.sortActions.actions() if a.data() == file_list.folderColNum)
    folder.trigger()
    assert file_list.get_sorting()[0] == file_list.folderColNum
    assert file_list.sortButton.text() == "Sort: Folder ↑"
    file_list.descendingAction.trigger()
    assert file_list.get_sorting() == (file_list.folderColNum, QtCore.Qt.SortOrder.DescendingOrder.value)
    assert file_list.sortButton.text() == "Sort: Folder ↓"

    file_list.btnTable.click()
    assert not file_list.card_view
    assert config[0].internal__file_list_view == "table"
    assert not file_list.twList.horizontalHeader().isHidden()
    assert not file_list.twList.isColumnHidden(file_list.folderColNum)


def test_editor_header_and_save_bar_follow_the_form(workspace, tmp_comic, qtbot):
    open_comic(workspace, qtbot, tmp_comic.path)
    header = workspace.editorHeader
    series, issue = workspace.leSeries.text(), workspace.leIssueNum.text()
    assert header.title.full_text.startswith(f"{series} #{issue}")
    assert not workspace.saveBar.status.isVisibleTo(workspace.saveBar)
    assert not workspace.saveBar.btnRevert.isEnabled()
    assert workspace.saveBar.btnSave.text().startswith("Save tags")
    assert workspace.toolBar.widgetForAction(workspace.actionWrite_Tags) is None

    workspace.leSeries.selectAll()
    qtbot.keyClicks(workspace.leSeries, "Lady Mechanika")
    assert header.title.full_text.startswith(f"Lady Mechanika #{issue}")
    assert workspace.saveBar.status.isVisibleTo(workspace.saveBar)
    assert workspace.saveBar.btnRevert.isEnabled()

    workspace.saveBar.btnRevert.click()
    assert not workspace.dirty_flag
    assert workspace.leSeries.text() == series
    assert header.title.full_text.startswith(f"{series} #{issue}")


def test_details_form_is_split_into_cards_that_count_and_hide_empty_fields(workspace, tmp_comic, qtbot):
    open_comic(workspace, qtbot, tmp_comic.path)
    cards = workspace.formCards
    assert [card.frame.findChild(QtWidgets.QLabel).text() for card in cards.cards] == [
        workspace.issueHeading.text(),
        workspace.publicationHeading.text(),
        workspace.classificationHeading.text(),
        workspace.alternateHeading.text(),
    ]
    issue_card = cards.cards[0]
    assert workspace.leSeries in issue_card.fields
    assert workspace.leSeries.parentWidget() is issue_card.frame

    workspace.leGtin.setText("")
    workspace.leTitle.setText("")
    QtWidgets.QApplication.processEvents()
    filled, total = cards.totals()
    assert 0 < filled < total
    assert workspace.formSummary.text() == f"{filled} of {total} fields filled"
    counted = [f for f in issue_card.fields if f.isEnabled() and not isinstance(f, QtWidgets.QCheckBox)]
    assert issue_card.count.text().endswith(f"of {len(counted)} filled")

    workspace.btnHideEmpty.setChecked(True)
    assert not workspace.leTitle.isVisibleTo(workspace)
    assert not workspace.field_labels[workspace.leTitle][0].isVisibleTo(workspace)
    assert workspace.leSeries.isVisibleTo(workspace)
    workspace.btnHideEmpty.setChecked(False)
    assert workspace.leTitle.isVisibleTo(workspace)

    # The Hide button sits outside the form, so clearing the form for the next archive keeps it.
    workspace.btnHideEmpty.setChecked(True)
    workspace.clear_form()
    assert workspace.btnHideEmpty.isChecked()
    workspace.btnHideEmpty.setChecked(False)
    workspace.clear_dirty_flag()


def test_file_list_sits_left_of_the_editor(workspace, tmp_comic, qtbot):
    workspace.resize(1100, 800)
    open_comic(workspace, qtbot, tmp_comic.path)
    assert workspace.splitter.orientation() == QtCore.Qt.Orientation.Horizontal
    assert workspace.splitter.widget(0) is workspace.widgetListHolder
    assert workspace.editorSplitter.widget(1) is workspace.editorPane
    # The page editor scrolls instead of forcing the window wider than the file list leaves room for.
    assert workspace.tabWidget.minimumSizeHint().width() < 600


def test_card_titles_wrap_to_two_lines_and_keep_the_issue_number(qtbot):
    from PyQt6 import QtGui

    from comictaggerlib.fileselectionlist import wrap_lines

    metrics = QtGui.QFontMetrics(QtGui.QFont())
    title = "Lady Mechanika - The Mechanical Menagerie #2 of 4"
    width = metrics.horizontalAdvance(title) * 2 // 3
    lines = wrap_lines(title, metrics, width, 2)
    assert len(lines) == 2
    assert lines[-1].endswith("#2 of 4")
    assert all(metrics.horizontalAdvance(line) <= width for line in lines)
    assert wrap_lines("Saga #2", metrics, width, 2) == ["Saga #2"]
