from __future__ import annotations

import difflib

from comicapi import utils
from comicapi.genericmetadata import ComicSeries


def sort_series_results(
    results: list[ComicSeries],
    series_name: str,
    year: int | None,
    *,
    sort_by_year: bool,
    exact_matches_first: bool,
) -> list[ComicSeries]:
    sanitized_full = utils.sanitize_title(series_name, False).casefold()

    def score(result: ComicSeries) -> tuple[bool, bool, float, int, int]:
        full_name = utils.sanitize_title(result.name, False).casefold()
        year_compatible = year is None or result.start_year is None or result.start_year <= year
        exact_match = not exact_matches_first or full_name == sanitized_full
        title_score = difflib.SequenceMatcher(None, sanitized_full, full_name).ratio()
        issue_count = result.count_of_issues or 0
        start_year = result.start_year or 0
        return (
            year_compatible,
            exact_match,
            title_score,
            start_year if sort_by_year else issue_count,
            issue_count if sort_by_year else start_year,
        )

    return sorted(results, key=score, reverse=True)
