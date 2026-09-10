from __future__ import annotations

import shutil

import pytest

QtCore = pytest.importorskip("PyQt6.QtCore")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from comictaggerlib.fileselectionlist import FileSelectionList
from comictaggerlib.resulttypes import Action, OnlineMatchResults, Result, Status
from testing.filenames import cbz_path


def test_auto_tag_results_are_shown_in_file_list(tmp_path, config, qtbot) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    paths = [source_dir / name for name in ("multiple.cbz", "uncertain.cbz", "missing.cbz")]

    file_list = FileSelectionList(None, config[0], lambda _title, _description: True)
    qtbot.addWidget(file_list)
    for path in paths:
        shutil.copy(cbz_path, path)
        file_list.add_path_item(str(path))

    def result(path):
        return Result(Action.gui, Status.match_failure, path)

    file_list.show_auto_tag_results(
        OnlineMatchResults(
            multiple_matches=[result(paths[0])],
            low_confidence_matches=[result(paths[1])],
            no_matches=[result(paths[2])],
        )
    )

    outcomes = {
        file_list.get_archive_by_row(row).path.name: file_list.twList.item(row, FileSelectionList.matchColNum).text()
        for row in range(file_list.twList.rowCount())
    }
    assert outcomes == {
        "missing.cbz": "No match",
        "multiple.cbz": "Multiple",
        "uncertain.cbz": "Low confidence",
    }
    low_confidence_row, _archive = file_list.get_current_list_row(str(paths[1]))
    assert (
        "none were confident enough"
        in file_list.twList.item(low_confidence_row, FileSelectionList.matchColNum).toolTip()
    )

    file_list.clear_auto_tag_results([file_list.get_archive_by_row(low_confidence_row)])
    assert file_list.twList.item(low_confidence_row, FileSelectionList.matchColNum).text() == ""


def test_moved_archive_refreshes_file_list_paths(tmp_path, config) -> None:
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_path = source_dir / cbz_path.name
    shutil.copy(cbz_path, source_path)

    file_list = FileSelectionList(None, config[0], lambda _title, _description: True)
    row, archive = file_list.add_path_item(str(source_path))
    file_list.twList.selectRow(row)
    destination = tmp_path / "library" / "renamed.cbz"
    archive.rename(destination)

    file_list.update_selected_rows()

    assert file_list.loaded_paths == {destination}
    assert file_list.get_current_archive().path == destination
    application.quit()


def test_selecting_moved_archive_removes_it_without_reentrant_selection(tmp_path, config, qtbot) -> None:
    class TrackingFileSelectionList(FileSelectionList):
        def __init__(self, *args, **kwargs):
            self.callback_depth = 0
            self.max_callback_depth = 0
            self.callback_events = []
            super().__init__(*args, **kwargs)

        def current_item_changed_cb(self, curr, prev):
            self.callback_depth += 1
            self.max_callback_depth = max(self.max_callback_depth, self.callback_depth)
            self.callback_events.append(
                (
                    self.callback_depth,
                    curr.row() if curr is not None else None,
                    prev.row() if prev is not None else None,
                    self.twList.rowCount(),
                    self.twList.currentRow(),
                )
            )
            try:
                super().current_item_changed_cb(curr, prev)
            finally:
                self.callback_depth -= 1

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    first_path = source_dir / "first.cbz"
    second_path = source_dir / "second.cbz"
    shutil.copy(cbz_path, first_path)
    shutil.copy(cbz_path, second_path)

    file_list = TrackingFileSelectionList(None, config[0], lambda _title, _description: True)
    qtbot.addWidget(file_list)
    selected_archives = []
    file_list.selectionChanged.connect(selected_archives.append)
    file_list.resize(600, 240)
    file_list.show()
    qtbot.wait(10)
    first_row, _ = file_list.add_path_item(str(first_path))
    second_row, _ = file_list.add_path_item(str(second_path))
    second_index = file_list.twList.model().index(second_row, FileSelectionList.fileColNum)
    qtbot.mouseClick(
        file_list.twList.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        pos=file_list.twList.visualRect(second_index).center(),
    )

    (tmp_path / "library").mkdir()
    shutil.move(first_path, tmp_path / "library" / "first.cbz")
    first_index = file_list.twList.model().index(first_row, FileSelectionList.fileColNum)
    qtbot.mouseClick(
        file_list.twList.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        pos=file_list.twList.visualRect(first_index).center(),
    )

    assert file_list.twList.rowCount() == 1
    assert file_list.get_current_archive().path == second_path
    assert selected_archives[-1].path == second_path
    assert file_list.max_callback_depth == 1, file_list.callback_events
