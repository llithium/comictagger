from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest

from comicapi.genericmetadata import GenericMetadata

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


def test_closing_waits_for_all_outstanding_issue_lookups(workspace, qtbot, monkeypatch):
    from comictaggerlib.taggerwindow import QueryThread

    workspace.show_editor()
    verify_draft = Mock(return_value=True)
    monkeypatch.setattr(workspace, "dirty_flag_verification", verify_draft)

    def lookup(release):
        assert release.wait(5)
        return GenericMetadata(series="Matched series")

    def start_lookup():
        release = threading.Event()
        selector = QtWidgets.QDialog(workspace)
        selector.talker = Mock()
        selector.talker.fetch_comic_data.side_effect = lambda **kwargs: lookup(release)
        selector.issue_id, selector.series_id, selector.issue_number = "13", "7", "2"
        workspace.selector = selector
        workspace.finish_query(selector)
        return selector.findChild(QueryThread), release

    first, release_first = start_lookup()
    second, release_second = start_lookup()
    try:
        assert not workspace.close()
        assert workspace.isVisible()
        verify_draft.assert_not_called()

        with qtbot.waitSignal(second.finished, timeout=5000):
            release_second.set()

        assert workspace.isVisible()
        verify_draft.assert_not_called()

        with qtbot.waitSignal(first.finished, timeout=5000):
            release_first.set()

        qtbot.waitUntil(lambda: not workspace.isVisible())
        verify_draft.assert_called_once()
    finally:
        release_first.set()
        release_second.set()
        qtbot.waitUntil(lambda: not workspace.findChildren(QueryThread))
        workspace.clear_dirty_flag()
