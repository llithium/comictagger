from __future__ import annotations

from unittest.mock import patch

from comictalker.talker_utils import cleanup_html


def test_headerless_multiline_and_multiple_tables():
    html = "Before<table>\n<tr><td>Value</td><td>Two</td></tr>\n</table>Between<table><tr><th>Name</th></tr><tr><td>A</td></tr></table>After"
    assert cleanup_html(html) == "Before| Value | Two |\n\nBetween| Name |\n|------|\n| A    |\n\nAfter"
    assert cleanup_html(html, True) == "BeforeBetweenAfter"


def test_malformed_and_ragged_tables_keep_readable_content():
    html = "Before<table><tr><td>First<td>Second</tr><tr><td>Third</table>After"
    text = cleanup_html(html)
    assert all(part in text for part in ("Before", "First", "Second", "Third", "After"))


def test_table_failure_keeps_readable_text_and_other_tables():
    from bs4.element import Tag

    original = Tag.find_all

    def fail_first_table(self, *args, **kwargs):
        if self.name == "table" and self.get("id") == "bad":
            raise ValueError("bad table")
        return original(self, *args, **kwargs)

    html = 'Before<table id="bad"><tr><td>Saved</td></tr></table><table><tr><td>Good</td></tr></table>After'
    with patch.object(Tag, "find_all", fail_first_table):
        text = cleanup_html(html)
    assert "BeforeSaved" in text
    assert "| Good |" in text
    assert "After" in text
    assert "COMICTAGGER_TABLE" not in text


def test_nested_table_text_is_not_duplicated():
    html = "<table><tr><td>Outer<table><tr><td>Inner</td></tr></table></td></tr></table>"
    assert cleanup_html(html) == "| Outer Inner |"
    assert cleanup_html(html, True) == ""
