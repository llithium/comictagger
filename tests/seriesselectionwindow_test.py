from __future__ import annotations

from comicapi.genericmetadata import ComicSeries
from comictaggerlib.seriesselectionwindow import sort_series_results


def series(id: str, name: str, year: int, issue_count: int) -> ComicSeries:
    return ComicSeries(
        id=id,
        name=name,
        aliases=set(),
        count_of_issues=issue_count,
        count_of_volumes=None,
        description="",
        image_url="",
        publisher="Marvel",
        start_year=year,
        format=None,
    )


def test_sort_series_results_prioritizes_year_compatible_long_running_series():
    results = [
        series("2024", "Uncanny X-Men", 2024, 34),
        series("2019", "Uncanny X-Men", 2019, 22),
        series("2016", "Uncanny X-Men", 2016, 19),
        series("2013", "Uncanny X-Men", 2013, 36),
        series("2012", "Uncanny X-Men", 2012, 20),
        series("3092", "The Uncanny X-Men", 1981, 405),
    ]

    sorted_results = sort_series_results(
        results,
        "Uncanny X-Men",
        2011,
        sort_by_year=True,
        exact_matches_first=True,
    )

    assert sorted_results[0].id == "3092"


def test_sort_series_results_honors_exact_match_preference():
    results = [
        series("related", "Uncanny X-Men Legacy", 1981, 405),
        series("exact", "Uncanny X-Men", 1980, 10),
    ]

    sorted_results = sort_series_results(
        results,
        "Uncanny X-Men",
        None,
        sort_by_year=False,
        exact_matches_first=True,
    )

    assert sorted_results[0].id == "exact"
