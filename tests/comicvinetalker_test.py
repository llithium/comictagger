from __future__ import annotations

import json
from copy import deepcopy

import pytest

import comicapi.genericmetadata
import testing.comicvine
from comictalker.comiccacher import Issue


def test_search_for_series(comicvine_api, comic_cache):
    results = comicvine_api.search_for_series(
        "cory doctorows futuristic tales of the here and now", on_rate_limit=None
    )[0]
    cache_series = comic_cache.get_search_results(
        comicvine_api.id,
        "cory doctorows futuristic tales of the here and now",
    )[0][0]
    series_results = comicvine_api._format_series(json.loads(cache_series.data))
    assert results == series_results


def test_fetch_series(comicvine_api, comic_cache):
    result = comicvine_api.fetch_series(23437)
    cache_series = comic_cache.get_series_info(23437, comicvine_api.id)[0]
    series_result = comicvine_api._format_series(json.loads(cache_series.data))
    assert result == series_result


def test_fetch_issues_in_series(comicvine_api, comic_cache):
    results = comicvine_api.fetch_issues_in_series(23437)
    cache_issues = comic_cache.get_series_issues_info(23437, comicvine_api.id)
    issues_results = [
        comicvine_api._map_comic_issue_to_metadata(
            json.loads(x[0].data),
            comicvine_api._format_series(
                json.loads(comic_cache.get_series_info(x[0].series_id, comicvine_api.id)[0].data)
            ),
        )
        for x in cache_issues
    ]
    assert results == issues_results


def test_comic_vine_deck_volume_is_mapped_to_metadata(comicvine_api):
    series = comicvine_api._format_series(
        {
            "id": 9133,
            "name": "The Punisher",
            "deck": "Volume 4.",
            "start_year": "2001",
        }
    )
    metadata = comicvine_api._map_comic_issue_to_metadata(
        {
            "id": 68397,
            "issue_number": "1",
            "volume": {"id": 9133, "name": "The Punisher"},
        },
        series,
    )

    assert metadata.volume == 4


def test_cached_comic_vine_issue_fetches_complete_series_metadata(comicvine_api, comic_cache):
    issue = deepcopy(testing.comicvine.cv_issue_result["results"])
    comic_cache.add_issues_info(
        comicvine_api.id,
        [Issue(id=str(issue["id"]), series_id=str(issue["volume"]["id"]), data=json.dumps(issue).encode("utf-8"))],
        True,
    )

    metadata = comicvine_api.fetch_comics(issue_ids=[str(issue["id"])])[0]

    assert metadata.series_start_year == 2007


def test_fetch_issue_data_by_issue_id(comicvine_api):
    result = comicvine_api.fetch_comic_data(140529, on_rate_limit=None)
    result.notes = None

    assert result == testing.comicvine.cv_md


def test_fetch_issues_in_series_issue_num_and_year(comicvine_api, cv_requests_get):
    results = comicvine_api.fetch_issues_by_series_issue_num_and_year([23437], "1", None)
    cv_expected = testing.comicvine.comic_issue_result.copy()

    assert results[0].series == cv_expected.series
    assert results[0] == cv_expected
    assert cv_requests_get.call_count == 2

    results = comicvine_api.fetch_issues_by_series_issue_num_and_year([23437], "1", None)

    assert results[0].series == cv_expected.series
    assert results[0] == cv_expected
    assert cv_requests_get.call_count == 2  # verify caching works

    results = comicvine_api.fetch_issues_by_series_issue_num_and_year([23437], "2", None)

    assert not results
    assert cv_requests_get.call_count == 2  # verify negative caching works


cv_issue = [
    (23437, "", testing.comicvine.cv_md),
    (23437, "1", testing.comicvine.cv_md),
    (23437, "0", comicapi.genericmetadata.GenericMetadata()),
]


@pytest.mark.parametrize("series_id, issue_number, expected", cv_issue)
def test_fetch_issue_data(comicvine_api, series_id, issue_number, expected):
    results = comicvine_api._fetch_issue_data(series_id, issue_number, on_rate_limit=None)
    results.notes = None
    assert results == expected
