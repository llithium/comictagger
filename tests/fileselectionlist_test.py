from __future__ import annotations

import shutil
import threading
import time

import pytest

QtCore = pytest.importorskip("PyQt6.QtCore")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from comictaggerlib.fileselectionlist import FileSelectionList
from comictaggerlib.resulttypes import Action, OnlineMatchResults, Result, Status
from testing.filenames import cbz_path


def test_show_in_finder_reveals_selected_archive(monkeypatch, tmp_path, config, qtbot) -> None:
    monkeypatch.setattr("comictaggerlib.fileselectionlist.platform.system", lambda: "Darwin")
    source_path = tmp_path / cbz_path.name
    shutil.copy(cbz_path, source_path)
    file_list = FileSelectionList(None, config[0], lambda _title, _description: True)
    qtbot.addWidget(file_list)
    row, _archive = file_list.add_path_item(str(source_path))
    file_list.twList.selectRow(row)
    started_commands = []
    monkeypatch.setattr(
        "comictaggerlib.fileselectionlist.QtCore.QProcess.startDetached",
        lambda program, arguments: started_commands.append((program, arguments)),
    )

    action = next(action for action in file_list.actions() if action.text() == "Show in Finder")
    action.trigger()

    assert started_commands == [("open", ["-R", str(source_path)])]


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

    manual_archive = file_list.get_archive_by_row(low_confidence_row)
    file_list.show_manual_matches([manual_archive])
    manual_item = file_list.twList.item(low_confidence_row, FileSelectionList.matchColNum)
    assert manual_item.text() == "Manual match"
    assert manual_item.toolTip() == "The match was selected manually after Auto-Tag."

    file_list.show_search_match(manual_archive)
    assert manual_item.text() == "Search match"
    assert manual_item.toolTip() == "The match was selected through Search Online."


def test_loading_paths_does_not_block_the_gui_thread(monkeypatch, config, qtbot) -> None:
    scan_started = threading.Event()
    release_scan = threading.Event()
    gui_remained_responsive = []

    def blocking_cloud_scan(_paths):
        scan_started.set()
        release_scan.wait(timeout=1)
        return []

    monkeypatch.setattr("comictaggerlib.fileselectionlist.utils.get_recursive_filelist", blocking_cloud_scan)
    file_list = FileSelectionList(None, config[0], lambda _title, _description: True)
    qtbot.addWidget(file_list)
    QtCore.QTimer.singleShot(0, lambda: (gui_remained_responsive.append(True), release_scan.set()))

    before_load = time.monotonic()
    file_list.add_path_list(["/cloud/comics"])
    load_call_duration = time.monotonic() - before_load

    assert load_call_duration < 0.2
    qtbot.waitUntil(scan_started.is_set)
    qtbot.waitUntil(lambda: bool(gui_remained_responsive))
    qtbot.waitUntil(lambda: not file_list.path_load_threads)


def test_probing_cloud_archive_does_not_block_the_gui_thread(monkeypatch, config, qtbot) -> None:
    probe_started = threading.Event()
    release_probe = threading.Event()

    class NotAComic:
        def seems_to_be_a_comic_archive(self):
            return False

    def blocking_cloud_archive(*_args, **_kwargs):
        probe_started.set()
        release_probe.wait(timeout=1)
        return NotAComic()

    monkeypatch.setattr("comictaggerlib.fileselectionlist.utils.get_recursive_filelist", lambda _paths: ["cloud.cbz"])
    monkeypatch.setattr("comictaggerlib.fileselectionlist.ComicArchive", blocking_cloud_archive)
    file_list = FileSelectionList(None, config[0], lambda _title, _description: True)
    qtbot.addWidget(file_list)
    QtCore.QTimer.singleShot(0, release_probe.set)

    before_load = time.monotonic()
    file_list.add_path_list(["/cloud/comics"])

    assert time.monotonic() - before_load < 0.2
    qtbot.waitUntil(probe_started.is_set)
    qtbot.waitUntil(lambda: not file_list.path_load_threads)


def test_loading_paths_adds_archives_after_background_probe(tmp_path, config, qtbot) -> None:
    source_path = tmp_path / cbz_path.name
    shutil.copy(cbz_path, source_path)
    file_list = FileSelectionList(None, config[0], lambda _title, _description: True)
    qtbot.addWidget(file_list)

    file_list.add_path_list([str(source_path)])

    qtbot.waitUntil(lambda: not file_list.path_load_threads)
    assert file_list.twList.rowCount() == 1
    assert file_list.get_current_archive().path == source_path


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
