from __future__ import annotations

import json
from copy import deepcopy

import pytest

import comicapi.genericmetadata
import testing.comicvine
from comictalker.comiccacher import Issue, Series
from comictalker.comictalker import TalkerDataError
from comictalker.talkers.comicvine import ComicVineTalker


def test_search_reports_a_malformed_response_as_a_talker_error(comicvine_api, monkeypatch):
    monkeypatch.setattr(comicvine_api, "_get_url_content", lambda *args, **kwargs: {})

    with pytest.raises(TalkerDataError, match="did not return a response status"):
        comicvine_api.search_for_series("Some series")


def test_search_for_series(comicvine_api, cv_requests_get):
    name = "cory doctorows futuristic tales of the here and now"
    results = comicvine_api.search_for_series(name, on_rate_limit=None)[0]
    assert results.id == "23437"
    assert results.name == "Cory Doctorow's Futuristic Tales of the Here and Now"
    assert results.count_of_issues == 1
    assert results.start_year == 2007
    assert comicvine_api.search_for_series(name, on_rate_limit=None) == [results]
    assert cv_requests_get.call_count == 1
    assert comicvine_api.search_for_series(name, series_match_thresh=95, on_rate_limit=None) == [results]
    assert cv_requests_get.call_count == 2


def test_literal_search_does_not_replace_cached_relevance_results(comicvine_api, monkeypatch):
    first = deepcopy(testing.comicvine.cv_volume_result)
    first["results"] = [first["results"]]
    second = deepcopy(first)
    second["results"][0]["id"] = 5678
    responses = iter([first, second])
    monkeypatch.setattr(comicvine_api, "_get_cv_content", lambda *args, **kwargs: next(responses))

    first_result = comicvine_api.search_for_series("comics")
    literal_result = comicvine_api.search_for_series("comics", literal=True)
    cached_result = comicvine_api.search_for_series("comics")

    assert [series.id for series in first_result] == ["23437"]
    assert [series.id for series in literal_result] == ["5678"]
    assert cached_result == first_result


def test_search_for_series_stops_on_empty_page(comicvine_api, monkeypatch):
    responses = iter(
        [
            {"number_of_page_results": 1, "number_of_total_results": 2, "results": []},
            {"number_of_page_results": 0, "number_of_total_results": 2, "results": []},
        ]
    )
    monkeypatch.setattr(comicvine_api, "_get_cv_content", lambda *args, **kwargs: next(responses))

    assert comicvine_api.search_for_series("not cached", literal=True) == []


def test_issue_pagination_collects_valid_pages(comicvine_api, monkeypatch):
    first = deepcopy(testing.comicvine.cv_issue_result)
    first["results"] = [first["results"]]
    first["number_of_page_results"] = 1
    first["number_of_total_results"] = 2
    second_issue = deepcopy(first["results"][0])
    second_issue["id"] = 140530
    second = {**first, "offset": 1, "results": [second_issue]}
    responses = iter([first, second])
    calls = []

    def get_page(url, params, *, on_rate_limit):
        calls.append(params.copy())
        return next(responses)

    monkeypatch.setattr(comicvine_api, "_get_cv_content", get_page)

    issues = comicvine_api._fetch_all_issue_pages({"filter": "volume:23437"}, on_rate_limit=None)

    assert [issue["id"] for issue in issues] == [140529, 140530]
    assert len(calls) == 2
    assert calls[1]["offset"] == 1


def test_issue_pagination_fails_without_progress(comicvine_api, monkeypatch):
    page = deepcopy(testing.comicvine.cv_issue_result)
    page["results"] = [page["results"]]
    page["number_of_total_results"] = 2
    empty = {**page, "number_of_page_results": 0, "results": []}
    responses = iter([page, empty])
    calls = []

    def get_page(url, params, *, on_rate_limit):
        calls.append(params.copy())
        return next(responses)

    monkeypatch.setattr(comicvine_api, "_get_cv_content", get_page)

    with pytest.raises(TalkerDataError):
        comicvine_api._fetch_all_issue_pages({"filter": "volume:23437"}, on_rate_limit=None)

    assert len(calls) == 2


def test_fetch_series(comicvine_api, comic_cache):
    result = comicvine_api.fetch_series(23437)
    cache_series = comic_cache.get_series_info(23437, comicvine_api.id)[0]
    assert result == testing.comicvine.comic_series_result
    assert json.loads(cache_series.data)["id"] == 23437
    assert comicvine_api.fetch_series(23437) == result


def test_interleaved_versions_do_not_reset_the_cache_on_each_lookup(comicvine_api, cv_requests_get):
    other = ComicVineTalker(comicvine_api.version + ".next", comicvine_api.cache_folder)
    assert comicvine_api.fetch_series(23437) == testing.comicvine.comic_series_result
    assert other.fetch_series(23437) == testing.comicvine.comic_series_result
    calls_after_both_opened = cv_requests_get.call_count

    assert comicvine_api.fetch_series(23437) == testing.comicvine.comic_series_result
    assert other.fetch_series(23437) == testing.comicvine.comic_series_result
    assert cv_requests_get.call_count == calls_after_both_opened


def test_fetch_issues_in_series(comicvine_api, comic_cache):
    results = comicvine_api.fetch_issues_in_series(23437)
    cache_issues = comic_cache.get_series_issues_info(23437, comicvine_api.id)
    assert len(results) == 1
    issue = results[0]
    assert issue.issue_id == "140529"
    assert issue.series_id == "23437"
    assert issue.series == "Cory Doctorow's Futuristic Tales of the Here and Now"
    assert issue.title == "Anda's Game"
    assert issue.issue == "1"
    assert (issue.year, issue.month, issue.day) == (2007, 10, 1)
    assert json.loads(cache_issues[0][0].data)["id"] == 140529
    assert comicvine_api.fetch_issues_in_series(23437) == results


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


def test_cached_comic_vine_issue_uses_cached_series_start_year(comicvine_api, comic_cache, cv_requests_get):
    issue = deepcopy(testing.comicvine.cv_issue_result["results"])
    comic_cache.add_issues_info(
        comicvine_api.id,
        [Issue(id=str(issue["id"]), series_id=str(issue["volume"]["id"]), data=json.dumps(issue).encode("utf-8"))],
        True,
    )
    comic_cache.add_series_info(
        comicvine_api.id,
        Series(
            id=str(issue["volume"]["id"]),
            data=json.dumps({**issue["volume"], "start_year": "2007"}).encode("utf-8"),
        ),
        False,
    )

    metadata = comicvine_api.fetch_comics(issue_ids=[str(issue["id"])])[0]

    assert metadata.series_start_year == 2007
    assert cv_requests_get.call_count == 0


def test_bulk_fetch_handles_missing_ids_across_multiple_batches(comicvine_api, monkeypatch):
    filters = []

    def fetch_empty_page(url, params, *, on_rate_limit):
        filters.append(params["filter"])
        return {"number_of_page_results": 0, "number_of_total_results": 0, "results": []}

    monkeypatch.setattr(comicvine_api, "_get_cv_content", fetch_empty_page)

    assert comicvine_api.fetch_comics(issue_ids=[str(i) for i in range(101)]) == []
    assert [len(query.removeprefix("id:").split("|")) for query in filters] == [100, 1]


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

    results = comicvine_api.fetch_issues_by_series_issue_num_and_year([23437], "1", 2026)

    assert not results
    assert cv_requests_get.call_count == 2


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
