from __future__ import annotations

import subprocess
import sys
import threading
from unittest.mock import Mock

import pytest

from comicapi.genericmetadata import GenericMetadata

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


def test_close_can_be_cancelled_or_accepted_while_provider_is_blocked(workspace, qtbot, monkeypatch):
    workspace.show_editor()
    release = threading.Event()
    started = threading.Event()

    def fetch(**kwargs):
        started.set()
        release.wait()
        kwargs["on_rate_limit"].callback(60, 10)
        return GenericMetadata(series="Matched series")

    selector = QtWidgets.QDialog(workspace)
    selector.talker = Mock()
    selector.talker.fetch_comic_data.side_effect = fetch
    selector.issue_id, selector.series_id, selector.issue_number = "13", "7", "2"
    workspace.selector = selector
    rate_limit = Mock()
    monkeypatch.setattr(workspace, "on_ratelimit", rate_limit)
    verify = Mock(side_effect=[False, True])
    monkeypatch.setattr(workspace, "dirty_flag_verification", verify)
    workspace.finish_query(selector)
    worker = workspace._issue_lookup
    try:
        qtbot.waitUntil(started.is_set)
        assert not workspace.close()
        assert workspace._lookup_timer.isActive()
        assert workspace.isVisible()
        assert workspace.close()
        assert not workspace.isVisible()
        assert worker.is_alive()
        assert verify.call_count == 2
    finally:
        release.set()
        worker.join(timeout=5)

    workspace._poll_issue_lookup()
    assert workspace.leSeries.text() == ""
    rate_limit.assert_not_called()


def test_process_exits_with_unresponsive_issue_provider():
    # A join at interpreter shutdown would hang even after the window disappears.
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import threading
from comictaggerlib.taggerwindow import IssueLookup

started = threading.Event()
class BlockedProvider:
    def fetch_comic_data(self, **kwargs):
        started.set()
        threading.Event().wait()

worker = IssueLookup(BlockedProvider(), "13", "7", "2")
worker.start()
assert started.wait(3)
""",
        ],
        timeout=10,
        check=True,
    )
