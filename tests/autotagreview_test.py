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
    assert panel.candidateTable.rowCount() == 2
    assert panel.current_candidate().md.issue_id == "1"
    assert panel.btnAccept.isEnabled()
    assert panel.diffTable.rowCount() > 0


def test_accepting_a_match_writes_it_and_moves_to_the_next_archive(panel, qtbot, monkeypatch):
    written = []
    monkeypatch.setattr(
        autotagreview,
        "write_match",
        lambda parent, ca, match, config, talker: written.append((ca.path.name, match.md.issue_id))
        or GenericMetadata(),
    )
    panel.candidateTable.setCurrentCell(1, 0)

    with qtbot.waitSignal(panel.matchesWritten) as signal:
        panel.accept_current()

    assert written == [("saga.cbz", "2")]
    assert [a.path.name for a in signal.args[0]] == ["saga.cbz"]
    assert panel.current_item().name == "fables.cbz"
    assert panel.categoryList.item(0).text() == "Needs review  (1)"
    assert [i.name for i in panel.items_in(Outcome.tagged)] == ["saga.cbz", "tagged.cbz"]
    assert panel.item_for(signal.args[0][0]).resolution == "Accepted"


def test_failed_write_keeps_the_archive_in_review(panel, monkeypatch):
    monkeypatch.setattr(autotagreview, "write_match", lambda *args: None)

    panel.accept_current()

    assert panel.current_item().name == "saga.cbz"
    assert panel.item_for(panel.current_item().archive).outcome == Outcome.needs_review


def test_no_match_archives_offer_search_instead_of_accept(panel, qtbot):
    panel.categoryList.setCurrentRow(list(Outcome).index(Outcome.no_match))

    assert panel.current_item().name == "lost.cbz"
    assert not panel.btnAccept.isEnabled()
    assert panel.candidateArea.currentWidget() is panel.messageLabel
    with qtbot.waitSignal(panel.searchRequested) as signal:
        panel.btnSearch.click()
    assert signal.args[0].path.name == "lost.cbz"


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

    assert panel.btnAccept.text() == "Retry write"
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

    assert workspace.autoTagReviewDock.isVisible()
    assert workspace.autoTagReview.current_item().name == "saga.cbz"
    assert "2 need review, 1 with no match, 1 error, 1 tagged" in workspace.statusBar().currentMessage()


def test_workspace_search_by_hand_loads_archive_and_searches(workspace, run, monkeypatch):
    results, archives = run
    for archive in archives:
        workspace.fileSelectionList.add_path_item(str(archive.path))
    archives = [workspace.fileSelectionList.get_current_list_row(str(a.path))[1] for a in archives]
    searches = []
    monkeypatch.setattr(workspace, "query_online", lambda: searches.append(workspace.comic_archive.path.name))
    workspace.auto_tag_finished(results, [], config=workspace.config[0], archives=archives)

    workspace.review_search_archive(archives[2])

    assert searches == ["lost.cbz"]
