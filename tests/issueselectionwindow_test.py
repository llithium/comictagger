"""Tests for issue-selection retrieval."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from comicapi.genericmetadata import GenericMetadata
from comictaggerlib import seriesselectionwindow
from comictaggerlib.issueselectionwindow import IssueSelectionWindow, QueryThread
from comictaggerlib.optionalmsgdialog import OptionalMessageDialog
from comictalker.comictalker import TalkerNetworkError


class FailingTalker:
    attribution = "Test source"
    logo_url = ""
    website = "https://example.com"

    def fetch_issues_in_series(self, series_id: str, *, on_rate_limit=None):
        raise TalkerNetworkError("Test source", desc="offline")


class SuccessfulTalker:
    def fetch_issues_in_series(self, series_id: str, *, on_rate_limit=None):
        return [GenericMetadata(issue_id="issue-1", issue="1")]


def test_issue_query_success_emits_issues(qtbot) -> None:
    thread = QueryThread(SuccessfulTalker(), series_id="23437")

    with qtbot.waitSignal(thread.finish, timeout=1000) as signal:
        thread.start()

    assert [issue.issue_id for issue in signal.args[0]] == ["issue-1"]
    thread.wait()


def test_issue_query_failure_closes_progress_and_reports_error(config, qtbot, monkeypatch) -> None:
    monkeypatch.setattr(seriesselectionwindow.qtutils, "new_web_view", lambda _parent: None)
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        OptionalMessageDialog,
        "critical",
        staticmethod(lambda _parent, title, text, **_kwargs: errors.append((title, text))),
    )

    dialog = IssueSelectionWindow(None, config[0], FailingTalker(), series_id="23437")
    qtbot.addWidget(dialog)
    dialog.perform_query()

    qtbot.waitUntil(lambda: not dialog.querythread.isRunning(), timeout=1000)
    qtbot.waitUntil(lambda: dialog.prog_dialog is not None and not dialog.prog_dialog.isVisible(), timeout=1000)
    qtbot.waitUntil(lambda: bool(errors), timeout=1000)

    assert errors == [("Test source Network Error", "Test source encountered a Network error. offline")]
