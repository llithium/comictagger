from __future__ import annotations

import json
import sqlite3

import pytest

import comictalker.comiccacher
from testing.comicdata import search_results


def test_create_cache(config, mock_version):
    config, definitions = config
    cache_dir = config.Runtime_Options__config.user_cache_dir
    cache = comictalker.comiccacher.ComicCacher(cache_dir, mock_version[0])

    cache.add_search_results(
        "test",
        "versioned search",
        [comictalker.comiccacher.Series(id="1", data=b"{}")],
        True,
    )

    reset_cache = comictalker.comiccacher.ComicCacher(cache_dir, mock_version[0] + ".next")
    assert reset_cache.get_search_results("test", "versioned search") == []

    assert (cache_dir / "cache_version.txt").read_text() == mock_version[0] + ".next"
    with sqlite3.connect(cache_dir / "comic_cache.db") as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"SeriesSearchCache", "Series", "Issues"} <= tables


def test_search_results(comic_cache):
    comic_cache.add_search_results(
        "test",
        "test search",
        [comictalker.comiccacher.Series(id=x["id"], data=json.dumps(x)) for x in search_results],
        True,
    )
    cached_results = [json.loads(x[0].data) for x in comic_cache.get_search_results("test", "test search")]
    assert search_results == cached_results


@pytest.mark.parametrize("series_info", search_results)
def test_series_info(comic_cache, series_info):
    comic_cache.add_series_info(
        series=comictalker.comiccacher.Series(id=series_info["id"], data=json.dumps(series_info).encode("utf-8")),
        source="test",
        complete=True,
    )
    vi = series_info.copy()
    cache_result = json.loads(comic_cache.get_series_info(series_id=series_info["id"], source="test")[0].data)
    assert vi == cache_result


@pytest.mark.parametrize("series_info", search_results)
def test_cache_overwrite(comic_cache, series_info):
    vi = series_info.copy()
    comic_cache.add_series_info(
        series=comictalker.comiccacher.Series(id=series_info["id"], data=json.dumps(series_info).encode("utf-8")),
        source="test",
        complete=True,
    )  # Populate the cache

    # Try to insert an incomplete series with different data
    updated_series_info = series_info.copy()
    updated_series_info["name"] = "test 3"
    comic_cache.add_series_info(
        series=comictalker.comiccacher.Series(
            id=updated_series_info["id"], data=json.dumps(updated_series_info).encode("utf-8")
        ),
        source="test",
        complete=False,
    )
    cache_result = json.loads(comic_cache.get_series_info(series_id=series_info["id"], source="test")[0].data)

    # Validate that the Series marked complete is still in the cache
    assert vi == cache_result


def test_existing_cache_gains_lookup_and_expiration_indexes(tmp_path):
    cache = comictalker.comiccacher.ComicCacher(tmp_path, "same-version")
    series = comictalker.comiccacher.Series("1", b"series")
    issue = comictalker.comiccacher.Issue("7", "1", b"issue")
    cache.add_search_results("test", "search", [series], True)
    cache.add_issues_info("test", [issue], True)
    with sqlite3.connect(cache.db_file) as con:
        # Simulate the schema used before lookup indexes were introduced.
        indexes = con.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL").fetchall()
        for (name,) in indexes:
            con.execute(f'DROP INDEX "{name}"')

    for _ in range(2):
        reopened = comictalker.comiccacher.ComicCacher(tmp_path, "same-version")
        assert reopened.get_search_results("test", "search") == [(series, True)]
        assert reopened.get_series_issues_info("1", "test") == [(issue, True)]
        with sqlite3.connect(cache.db_file) as con:
            queries = [
                "SELECT * FROM Issues WHERE series_id='1' AND source='test'",
                "SELECT * FROM SeriesSearchCache WHERE search_term='search' AND source='test'",
                *(
                    f"DELETE FROM {table} WHERE timestamp < '2000-01-01'"
                    for table in ("SeriesSearchCache", "Series", "Issues")
                ),
            ]
            for query in queries:
                plan = con.execute(f"EXPLAIN QUERY PLAN {query}").fetchall()
                assert not any("SCAN" in step[3] for step in plan), plan


def test_indexed_search_preserves_order_from_existing_series(comic_cache):
    first = comictalker.comiccacher.Series("2", b"first")
    second = comictalker.comiccacher.Series("1", b"second")
    comic_cache.add_search_results("test", "earlier search", [first, second], True)
    comic_cache.add_search_results("test", "later search", [second, first], False)
    assert comic_cache.get_search_results("test", "later search") == [(first, True), (second, True)]


def test_indexed_issue_lookup_preserves_order_and_source(comic_cache):
    issues = [comictalker.comiccacher.Issue("2", "1", b"first"), comictalker.comiccacher.Issue("1", "1", b"second")]
    comic_cache.add_issues_info("test", issues, True)
    comic_cache.add_issues_info("other", [comictalker.comiccacher.Issue("2", "1", b"other source")], True)
    comic_cache.add_issues_info("test", [comictalker.comiccacher.Issue("3", "2", b"other series")], True)
    assert comic_cache.get_series_issues_info("1", "test") == [(issue, True) for issue in issues]


def test_indexed_expiration_keeps_fresh_records(comic_cache):
    for source in ("test", "other"):
        for key in ("old", "fresh"):
            comic_cache.add_search_results(source, key, [comictalker.comiccacher.Series(key, key.encode())], True)
            comic_cache.add_issues_info(source, [comictalker.comiccacher.Issue(key, "1", key.encode())], True)
    with sqlite3.connect(comic_cache.db_file) as con:
        for table in ("SeriesSearchCache", "Series", "Issues"):
            con.execute(f"UPDATE {table} SET timestamp='2000-01-01' WHERE id='old'")

    assert comic_cache.get_search_results("test", "old", expire_stale=False)
    assert comic_cache.get_issue_info("old", "test", expire_stale=False)
    assert comic_cache.get_search_results("test", "old") == []
    assert comic_cache.get_issue_info("old", "test") is None
    for source in ("test", "other"):
        assert comic_cache.get_search_results(source, "fresh")
        assert comic_cache.get_series_info("fresh", source)
        assert [issue.data.id for issue in comic_cache.get_series_issues_info("1", source)] == ["fresh"]
        assert comic_cache.get_search_results(source, "old", expire_stale=False) == []
        assert comic_cache.get_series_info("old", source, expire_stale=False) is None
        assert comic_cache.get_issue_info("old", source, expire_stale=False) is None
