from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest

from comicapi.genericmetadata import GenericMetadata

QtCore = pytest.importorskip("PyQt6.QtCore")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


@pytest.mark.parametrize("switch_editor", [False, True])
@pytest.mark.parametrize("outcome", ["success", "error", "invalid"])
def test_issue_lookup_finishes_in_its_original_editor(workspace, qtbot, monkeypatch, switch_editor, outcome):
    from comictaggerlib.taggerwindow import OptionalMessageDialog

    workspace.show_editor()
    release = threading.Event()
    metadata = GenericMetadata(series="Matched series")

    def fetch(**kwargs):
        assert release.wait(5)
        kwargs["on_rate_limit"].callback(60, 10)
        if outcome == "invalid":
            return None
        if outcome == "error":
            raise ValueError("Lookup failed")
        return metadata

    selector = QtWidgets.QDialog(workspace)
    selector.talker = Mock()
    selector.talker.fetch_comic_data.side_effect = fetch
    selector.issue_id, selector.series_id, selector.issue_number = "13", "7", "2"
    workspace.selector = selector
    alerts = []

    def critical(window, title, message):
        alerts.append((message, QtCore.QThread.currentThread() == window.thread()))

    monkeypatch.setattr(OptionalMessageDialog, "critical", critical)
    rate_limit = Mock()
    monkeypatch.setattr(workspace, "on_ratelimit", rate_limit)
    workspace.finish_query(selector)
    worker = workspace._issue_lookup
    try:
        if switch_editor:
            workspace.clear_form()
            workspace.leSeries.setText("Another series")
        release.set()
        qtbot.waitUntil(lambda: not worker.is_alive() and workspace._issue_lookup is None)
        selector.talker.fetch_comic_data.assert_called_once()
        if switch_editor:
            assert workspace.leSeries.text() == "Another series"
            assert alerts == []
            rate_limit.assert_not_called()
        elif outcome == "invalid":
            assert alerts == [("The metadata source returned an invalid issue.", True)]
        elif outcome == "error":
            assert alerts == [("Lookup failed", True)]
        else:
            assert workspace.leSeries.text() == "Matched series"
            assert workspace.dirty_flag
            rate_limit.assert_called_once_with(60, 10)
    finally:
        release.set()
        workspace.clear_dirty_flag()
