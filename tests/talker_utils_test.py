from __future__ import annotations

from comictalker.talker_utils import cleanup_html


def test_cleanup_html_removes_placeholder_when_table_reconstruction_fails():
    html = "Before<table><tr><td>Value</td></tr></table>After"

    # A table without headers triggers the malformed-row fallback because there
    # is no column width available for its data cell.
    assert "{}" not in cleanup_html(html)
