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
    cache.close()

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
