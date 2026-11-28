from __future__ import annotations

import shutil
from unittest.mock import Mock

import pytest

QtCore = pytest.importorskip("PyQt6.QtCore")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from comicapi.comicarchive import ComicArchive
from comicapi.genericmetadata import ComicSeries, GenericMetadata
from comictaggerlib import autotagreview
from comictaggerlib.autotagreview import AutoTagReviewPanel, Outcome, build_review_items, metadata_diff
from comictaggerlib.resulttypes import (
    Action,
    IssueResult,
    MatchStatus,
    OnlineMatchResults,
    Result,
    Score,
    Status,
)
from comictaggerlib.searchpanel import best_issue_row, filter_publishers
from testing.filenames import cbz_path


def make_archives(tmp_path, *names: str) -> list[ComicArchive]:
    archives = []
    for name in names:
        path = tmp_path / name
        shutil.copy(cbz_path, path)
        archives.append(ComicArchive(path))
    return archives


def candidate(series: str, issue: str, year: int, issue_id: str) -> IssueResult:
    comic_series = ComicSeries(
        id=f"s-{series}",
        name=series,
        aliases=set(),
        count_of_issues=None,
        count_of_volumes=None,
        description="",
        image_url="",
        publisher="Image",
        start_year=year,
        format=None,
    )
    md = GenericMetadata(series=series, issue=issue, year=year, publisher="Image", issue_id=issue_id)
    return IssueResult(Score(4, "", 0, "", 0), comic_series, md)


def failure(archive: ComicArchive, status: MatchStatus, matches: list[IssueResult]) -> Result:
    return Result(Action.save, Status.match_failure, archive.path, online_results=matches, match_status=status)


@pytest.fixture
def run(tmp_path):
    archives = make_archives(tmp_path, "saga.cbz", "tagged.cbz", "lost.cbz", "fables.cbz", "fetch.cbz")
    saga, tagged, lost, fables, fetch = archives
    results = OnlineMatchResults()
    results.record(Result(Action.save, Status.success, tagged.path, md=GenericMetadata(series="Tagged")))
    results.record(
        failure(
            saga,
            MatchStatus.multiple_match,
            [candidate("Saga", "54", 2018, "1"), candidate("Saga Variant", "54", 2018, "2")],
        )
    )
    results.record(failure(lost, MatchStatus.no_match, []))
    results.record(failure(fables, MatchStatus.low_confidence_match, [candidate("Fables", "75", 2008, "3")]))
    results.record(Result(Action.save, Status.fetch_data_failure, fetch.path))
    return results, archives


def test_build_review_items_groups_every_outcome_in_run_order(run, tmp_path, monkeypatch):
    results, archives = run
    read_only = make_archives(tmp_path, "readonly.cbz")[0]
    monkeypatch.setattr(read_only, "is_writable", lambda: False)

    items = build_review_items(results, [*archives, read_only])

    assert [(i.name, i.outcome, i.reason) for i in items] == [
        ("saga.cbz", Outcome.needs_review, "2 possible matches"),
        ("tagged.cbz", Outcome.tagged, "Tagged"),
        ("lost.cbz", Outcome.no_match, "No match found"),
        ("fables.cbz", Outcome.needs_review, "Low confidence"),
        ("fetch.cbz", Outcome.error, "Couldn't fetch issue details"),
        ("readonly.cbz", Outcome.error, "File is read-only"),
    ]


def test_metadata_diff_lists_only_fields_the_candidate_has():
    current = GenericMetadata(series="Saga", issue=None)
    match = GenericMetadata(series="Saga", issue="54", year=2018)

    assert metadata_diff(current, match) == [("Series", "Saga", "Saga"), ("Issue", "—", "54"), ("Year", "—", "2018")]


@pytest.fixture
def panel(run, config, qtbot):
    results, archives = run
    panel = AutoTagReviewPanel(None, config[0].Runtime_Options__config.user_cache_dir)
    qtbot.addWidget(panel)
    panel.load_results(results, archives, config[0], Mock(attribution="Metadata provided by Test"))
    return panel


def test_panel_opens_on_items_that_need_review(panel):
    assert panel.categoryList.currentItem().text() == "Needs review  (2)"
    assert panel.current_item().name == "saga.cbz"
    assert panel.candidateStrip.count() == 2
    assert panel.current_candidate().md.issue_id == "1"
    assert panel.btnAccept.isEnabled()
    assert panel.diffTable.rowCount() > 0


def test_accepting_a_match_writes_it_and_moves_to_the_next_archive(panel, qtbot, monkeypatch):
    written = []
    monkeypatch.setattr(
        autotagreview,
        "write_match",
        lambda ca, issue_id, config, talker: written.append((ca.path.name, issue_id))
        or autotagreview.WriteOutcome(GenericMetadata()),
    )
    panel.candidateStrip.set_current(1)

    with qtbot.waitSignal(panel.matchesWritten) as signal:
        panel.accept_current()

    assert written == [("saga.cbz", "2")]
    assert [a.path.name for a in signal.args[0]] == ["saga.cbz"]
    assert panel.current_item().name == "fables.cbz"
    assert panel.categoryList.item(0).text() == "Needs review  (1)"
    assert [i.name for i in panel.items_in(Outcome.tagged)] == ["saga.cbz", "tagged.cbz"]
    assert panel.item_for(signal.args[0][0]).resolution == "Accepted"


def test_failed_write_keeps_the_archive_in_review(panel, qtbot, monkeypatch):
    monkeypatch.setattr(
        autotagreview, "write_match", lambda *args: autotagreview.WriteOutcome(title="Network Issue", message="down")
    )
    shown = []
    monkeypatch.setattr(autotagreview.OptionalMessageDialog, "critical", lambda *args: shown.append(args[1:]))

    panel.accept_current()
    qtbot.waitUntil(lambda: not panel.writing)

    assert shown == [("Network Issue", "down")]
    assert panel.btnAccept.isEnabled()
    assert panel.current_item().name == "saga.cbz"
    assert panel.item_for(panel.current_item().archive).outcome == Outcome.needs_review


def test_saving_runs_in_the_background_and_blocks_a_second_save(panel, qtbot, monkeypatch):
    import threading

    release = threading.Event()
    calls = []

    def slow_write(ca, issue_id, config, talker):
        calls.append((ca.path.name, threading.current_thread() is threading.main_thread()))
        release.wait(5)
        return autotagreview.WriteOutcome(GenericMetadata())

    monkeypatch.setattr(autotagreview, "write_match", slow_write)

    panel.accept_current()
    # The UI thread is free while the archive is written.
    qtbot.waitUntil(lambda: bool(calls))
    assert panel.writing
    assert not panel.btnAccept.isEnabled()
    assert panel.btnAccept.text() == "Saving tags…"
    assert panel.reasonLabel.text() == "Saving tags…"
    panel.accept_current()  # ignored while saving
    panel.next_item()  # moving on is allowed
    assert panel.current_item().name == "fables.cbz"
    assert not panel.btnAccept.isEnabled()

    with qtbot.waitSignal(panel.matchesWritten):
        release.set()

    assert calls == [("saga.cbz", False)]
    assert not panel.writing
    assert [i.name for i in panel.items_in(Outcome.tagged)] == ["saga.cbz", "tagged.cbz"]
    # The user stays on the archive they moved to.
    assert panel.current_item().name == "fables.cbz"
    assert panel.btnAccept.isEnabled()


def test_search_in_progress_survives_another_archive_finishing(panel, qtbot, monkeypatch):
    import threading

    release = threading.Event()
    monkeypatch.setattr(
        autotagreview,
        "write_match",
        lambda *args: release.wait(5) and autotagreview.WriteOutcome(GenericMetadata()),
    )
    panel.talker.name = "Test"
    panel.talker.search_for_series.return_value = []
    panel.accept_current()
    qtbot.waitUntil(lambda: panel.writing)
    panel.next_item()
    panel.search_current()
    assert panel.bodyStack.currentWidget() is panel.searchPanel
    assert not panel.searchPanel.btnUse.isEnabled()

    with qtbot.waitSignal(panel.matchesWritten):
        release.set()

    assert panel.current_item().name == "fables.cbz"
    assert panel.bodyStack.currentWidget() is panel.searchPanel


def series_result(name: str, series_id: str, year: int) -> ComicSeries:
    return ComicSeries(series_id, name, set(), 80, None, "", "", "Image", year, None)


def test_no_match_archives_are_fixed_with_the_embedded_search(panel, qtbot, monkeypatch):
    panel.talker.name = "Test"
    panel.talker.search_for_series.return_value = [
        series_result("Lost Girls", "s2", 1991),
        series_result("Lost", "s1", 2004),
    ]
    panel.talker.fetch_issues_in_series.return_value = [
        GenericMetadata(series="Lost", issue=str(n), issue_id=f"i{n}", year=2004) for n in (3, 1, 2)
    ]
    written = []
    monkeypatch.setattr(
        autotagreview,
        "write_match",
        lambda ca, issue_id, config, talker: written.append(issue_id) or autotagreview.WriteOutcome(GenericMetadata()),
    )
    panel.categoryList.setCurrentRow(list(Outcome).index(Outcome.no_match))
    assert panel.current_item().name == "lost.cbz"
    assert not panel.btnAccept.isEnabled()
    assert panel.candidateArea.currentWidget() is not panel.candidateStrip
    assert panel.messageLabel.isVisibleTo(panel)

    panel.btnSearch.click()

    search = panel.searchPanel
    assert panel.bodyStack.currentWidget() is search
    assert search.leSeries.text().casefold() == "lost"
    qtbot.waitUntil(lambda: search.issueTable.rowCount() == 3)
    assert search.current_series().name == "Lost"  # exact name sorted first
    assert [search.issueTable.item(r, 0).text() for r in range(3)] == ["1", "2", "3"]
    search.leIssue.setText("2")
    search._issue_number_changed()
    assert search.current_issue().issue_id == "i2"

    with qtbot.waitSignal(panel.matchesWritten):
        search.btnUse.click()

    assert written == ["i2"]
    lost = next(i for i in panel.items if i.name == "lost.cbz")
    assert (lost.outcome, lost.resolution) == (Outcome.tagged, "Picked by search")
    assert panel.bodyStack.currentWidget() is panel.reviewPage


def test_search_errors_are_shown_in_the_panel(panel, qtbot):
    from comictalker.comictalker import TalkerNetworkError

    panel.talker.name = "Test"
    panel.talker.search_for_series.side_effect = TalkerNetworkError("Test", 2, "offline")
    panel.categoryList.setCurrentRow(list(Outcome).index(Outcome.no_match))

    panel.search_current()

    qtbot.waitUntil(lambda: "couldn't search" in panel.searchPanel.status.text())
    panel._escape()
    assert panel.bodyStack.currentWidget() is panel.reviewPage


def test_best_issue_row_matches_padded_numbers():
    issues = [GenericMetadata(issue=n) for n in ("1", "2", "10")]

    assert best_issue_row(issues, "002") == 1
    assert best_issue_row(issues, "99") == 0


def test_results_fill_in_during_a_run(run, config, qtbot, tmp_path):
    results, archives = run
    panel = AutoTagReviewPanel(None, config[0].Runtime_Options__config.user_cache_dir)
    qtbot.addWidget(panel)
    panel.begin_run(archives, config[0], Mock(attribution=""))
    assert panel.runBar.isVisibleTo(panel)
    assert "as each archive is done" in panel.emptyLabel.text()

    tagged = results.good_matches[0]
    panel.add_result(tagged)
    assert panel.categoryList.item(0).text() == "Needs review  (0)"
    assert panel.categoryList.item(3).text() == "Tagged  (1)"

    panel.add_result(results.multiple_matches[0])
    assert panel.current_item().name == "saga.cbz"
    panel.candidateStrip.set_current(1)

    panel.add_result(results.low_confidence_matches[0])
    # Reviewing saga.cbz isn't interrupted by fables.cbz arriving in the same group.
    assert panel.current_item().name == "saga.cbz"
    assert panel.candidateStrip.current_index() == 1
    assert panel.fileList.count() == 2

    with qtbot.waitSignal(panel.stopRequested):
        panel.btnStop.click()
    panel.finish_run()
    assert not panel.runBar.isVisibleTo(panel)
    assert panel.summary() == "Auto-Tag finished: 2 need review, 1 tagged"


def test_saving_by_hand_resolves_the_archive(panel):
    lost = next(i for i in panel.items if i.name == "lost.cbz")

    panel.mark_fixed(lost.archive)

    assert lost.outcome == Outcome.tagged
    assert lost.reason == "Fixed by hand"
    assert panel.categoryList.item(1).text() == "No match  (0)"


def test_write_failures_can_be_retried(tmp_path, config, qtbot, monkeypatch):
    (archive,) = make_archives(tmp_path, "locked.cbz")
    results = OnlineMatchResults()
    results.record(Result(Action.save, Status.write_failure, archive.path, md=GenericMetadata(series="Low", issue="4")))
    panel = AutoTagReviewPanel(None, config[0].Runtime_Options__config.user_cache_dir)
    qtbot.addWidget(panel)
    panel.load_results(results, [archive], config[0], Mock(attribution=""))
    writes = []
    monkeypatch.setattr(
        autotagreview, "write_selected_tags", lambda ca, md, ids: writes.append(md.series) or ([], None)
    )

    assert panel.btnAccept.text().startswith("Retry write")
    with qtbot.waitSignal(panel.matchesWritten):
        panel.accept_current()

    assert writes == ["Low"]
    assert panel.items[0].outcome == Outcome.tagged


def test_workspace_shows_review_dock_without_modal_dialogs(workspace, run, monkeypatch):
    from comictaggerlib import taggerwindow

    results, archives = run
    for archive in archives:
        workspace.fileSelectionList.add_path_item(str(archive.path))
    archives = [workspace.fileSelectionList.get_current_list_row(str(a.path))[1] for a in archives]
    for name in ("question", "msg_no_checkbox", "information"):
        monkeypatch.setattr(taggerwindow.OptionalMessageDialog, name, Mock(side_effect=AssertionError(name)))

    workspace.auto_tag_finished(results, [], config=workspace.config[0], archives=archives)

    assert workspace.in_review()
    assert workspace.autoTagReview.current_item().name == "saga.cbz"
    assert "2 need review, 1 with no match, 1 error, 1 tagged" in workspace.statusBar().currentMessage()


def test_workspace_run_does_not_block_and_skips_files_saved_by_hand(workspace, run, monkeypatch, qtbot):
    from comictaggerlib import taggerwindow

    results, archives = run
    for archive in archives:
        workspace.fileSelectionList.add_path_item(str(archive.path))
    workspace.fileSelectionList.select_all()
    started = []
    monkeypatch.setattr(taggerwindow.AutoTagThread, "start", lambda thread: started.append(thread))
    monkeypatch.setattr(taggerwindow.AutoTagThread, "isRunning", lambda thread: thread in started)
    settings = Mock(search_string="", new_settings=lambda config: config)

    workspace._start_auto_tag(settings)

    thread = started[0]
    assert workspace.in_review()
    assert not workspace.atprogdialog.isVisible()
    assert not workspace.actionAutoTag.isEnabled()
    row, first = workspace.fileSelectionList.get_current_list_row(str(archives[0].path))
    workspace.fileSelectionList.twList.selectRow(row)
    assert workspace.comic_archive is first
    workspace.leSeries.setText("Saved by hand")
    workspace.set_dirty_flag()
    monkeypatch.setattr(taggerwindow.OptionalMessageDialog, "warning", Mock())
    assert workspace.write_tags()
    assert first.path in thread.skip_paths

    thread.autoTagResult.emit(results.multiple_matches[0])
    assert workspace.autoTagReview.current_item().name == "saga.cbz"
    started.clear()
    thread.autoTagComplete.emit(results, [])
    assert workspace.actionAutoTag.isEnabled()
    assert not workspace.autoTagReview.running


def test_filter_publishers_ignores_case_and_spaces():
    series = [
        ComicSeries("s1", "Vampirella", set(), 17, None, "", "", "Splitter", 1998, None),
        ComicSeries("s2", "Vampirella Horror Classics", set(), 1, None, "", "", "mg/publishing", 2000, None),
        ComicSeries("s3", "Vampirella", set(), 22, None, "", "", None, 2001, None),
    ]
    assert [s.id for s in filter_publishers(series, [" splitter ", ""])] == ["s2", "s3"]
    assert [s.id for s in filter_publishers(series, [])] == ["s1", "s2", "s3"]


def test_embedded_search_hides_filtered_publishers(panel, qtbot):
    panel.config.Auto_Tag__use_publisher_filter = True
    panel.config.Auto_Tag__publisher_filter = ["Panini Comics", "Splitter"]
    panel.talker.name = "Test"
    panel.talker.search_for_series.return_value = [
        ComicSeries("s1", "Lost", set(), 17, None, "", "", "Splitter", 1998, None),
        series_result("Lost", "s2", 2004),
        ComicSeries("s3", "Lost Girls", set(), 3, None, "", "", "SPLITTER ", 1991, None),
    ]
    panel.talker.fetch_issues_in_series.return_value = [GenericMetadata(issue="1", issue_id="i1")]
    panel.categoryList.setCurrentRow(list(Outcome).index(Outcome.no_match))
    panel.search_current()
    search = panel.searchPanel
    qtbot.waitUntil(lambda: search.issueTable.rowCount() == 1)
    ids = lambda: [search._value(search.seriesTable, r).id for r in range(search.seriesTable.rowCount())]  # noqa: E731

    assert search.cbxPublisherFilter.isChecked()
    assert ids() == ["s2"]
    assert search.status.text() == "1 issues in Lost. 2 series hidden by the publisher filter."

    search.cbxPublisherFilter.setChecked(False)  # shows them again without searching again
    assert sorted(ids()) == ["s1", "s2", "s3"]
    assert panel.talker.search_for_series.call_count == 1
    assert panel.config.Auto_Tag__use_publisher_filter  # the setting itself is left alone

    panel.config.Auto_Tag__publisher_filter = ["Splitter", "Image"]
    search.cbxPublisherFilter.setChecked(True)
    assert ids() == []
    assert "Untick" in search.status.text()


def test_search_results_sort_by_column_without_reloading(panel, qtbot):
    panel.talker.name = "Test"
    panel.talker.search_for_series.return_value = [
        series_result("Lost", "s1", 2004),
        series_result("Lost Girls", "s2", 1991),
        series_result("Lost in Space", "s3", 2016),
    ]
    panel.talker.fetch_issues_in_series.return_value = [
        GenericMetadata(issue=str(n), issue_id=f"i{n}") for n in (10, 9)
    ]
    panel.categoryList.setCurrentRow(list(Outcome).index(Outcome.no_match))
    panel.search_current()
    search = panel.searchPanel
    qtbot.waitUntil(lambda: search.issueTable.rowCount() == 2)
    years = lambda: [search.seriesTable.item(r, 1).text() for r in range(3)]  # noqa: E731

    assert search.seriesTable.isSortingEnabled()  # header clicks sort
    assert years() == ["2004", "1991", "2016"]  # best match first until a column is chosen
    search.seriesTable.sortItems(1, QtCore.Qt.SortOrder.AscendingOrder)

    assert years() == ["1991", "2004", "2016"]
    assert search.current_series().id == "s1"
    assert panel.talker.fetch_issues_in_series.call_count == 1
    search.issueTable.sortItems(0, QtCore.Qt.SortOrder.DescendingOrder)
    assert [search.issueTable.item(r, 0).text() for r in range(2)] == ["10", "9"]


def test_editor_search_online_uses_the_docked_panel(workspace, tmp_comic, qtbot, monkeypatch):
    talker = Mock(attribution="")
    talker.name = "Test"
    talker.search_for_series.return_value = [series_result("Cory Doctorow's Futuristic Tales", "s1", 2007)]
    talker.fetch_issues_in_series.return_value = [GenericMetadata(issue="1", issue_id="i1")]
    monkeypatch.setattr(workspace, "current_talker", lambda: talker)
    lookups = []
    monkeypatch.setattr(workspace, "_start_issue_lookup", lambda *args: lookups.append(args[1:]))
    workspace.fileSelectionList.add_path_item(str(tmp_comic.path))
    workspace.fileSelectionList.twList.selectRow(0)

    workspace.actionSearchOnline.trigger()

    assert workspace.searchDock.isVisible()
    search = workspace.searchPanel
    qtbot.waitUntil(lambda: search.issueTable.rowCount() == 1)
    search.btnUse.click()
    assert lookups == [("i1", "s1", "1")]
    assert not workspace.searchDock.isVisible()
