"""Offline warm-cache benchmark. Run from the repository root with PYTHONPATH=.

Uses synthetic Comic Vine records and a temporary cache; never contacts a server
or opens the user's cache. Setup and imports are excluded from timed operations.
"""

from __future__ import annotations

import argparse
import cProfile
import dataclasses
import hashlib
import json
import pathlib
import platform
import sqlite3
import statistics
import tempfile
import time
from collections.abc import Callable

import PIL

from comictaggerlib.seriesmatch import sort_series_results
from comictalker.comiccacher import ComicCacher, Issue, Series
from comictalker.talkers.comicvine import ComicVineTalker

TITLE = "Benchmark Comics"
SEARCH_KEY = f"90\0{TITLE}".casefold()
SAMPLES = 11


def seed_cache(cache: ComicCacher, series_count: int) -> list[str]:
    selected = [str(i) for i in range(series_count - 12, series_count)]
    records = []
    issues = []
    for index in range(series_count):
        series = {
            "id": index,
            "name": TITLE if str(index) in selected else f"Other Comic {index}",
            "start_year": "2000",
            "count_of_issues": 20,
            "publisher": {"name": "Benchmark Publisher"},
            "description": "Synthetic cached series. " * 10,
        }
        records.append(Series(str(index), json.dumps(series).encode()))
        for number in range(1, 21):
            issue = {
                "id": index * 20 + number,
                "volume": {"id": index, "name": series["name"]},
                "issue_number": str(number),
                "cover_date": "2001-01-01",
                "name": f"Issue {number}",
                "description": "Synthetic cached issue. " * 10,
            }
            issues.append(Issue(str(issue["id"]), str(index), json.dumps(issue).encode()))
    cache.add_search_results("comicvine", "noise", records, True)
    cache.add_issues_info("comicvine", issues, True)
    # Distinct background searches make search lookup cost grow with cache size.
    with sqlite3.connect(cache.db_file) as con:
        con.executemany(
            "INSERT INTO SeriesSearchCache (id, source, search_term) VALUES (?, ?, ?)",
            ((str(i), "comicvine", f"query-{j}-{i}") for i in range(series_count) for j in range(4)),
        )
        con.executemany(
            "INSERT INTO SeriesSearchCache (id, source, search_term) VALUES (?, ?, ?)",
            ((series_id, "comicvine", SEARCH_KEY) for series_id in selected),
        )
    return selected


def measure(operation: Callable[[], object]) -> dict[str, object]:
    expected = operation()
    operation()  # warm filesystem and import caches equally for every version
    timings = []
    for _ in range(SAMPLES):
        start = time.perf_counter()
        result = operation()
        timings.append((time.perf_counter() - start) * 1000)
        assert result == expected, "Unstable benchmark output"
    return {
        "median_ms": statistics.median(timings),
        "min_ms": min(timings),
        "max_ms": max(timings),
        "samples_ms": timings,
        "output_sha256": hashlib.sha256(repr(expected).encode()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--profile", type=pathlib.Path)
    args = parser.parse_args()
    report: dict[str, object] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "sqlite": sqlite3.sqlite_version,
        "pillow": PIL.__version__,
        "samples": SAMPLES,
        "cases": {},
    }
    cases = {}
    for name, size in (("small", 100), ("medium", 1000), ("large", 5000)):
        with tempfile.TemporaryDirectory(prefix="comictagger-benchmark-") as directory:
            talker = ComicVineTalker("benchmark", pathlib.Path(directory))
            cache = talker.cacher()
            ids = seed_cache(cache, size)

            def reject_network(*args: object, **kwargs: object) -> None:
                raise AssertionError("Benchmark must remain offline")

            talker._get_cv_content = reject_network  # type: ignore[method-assign, assignment]

            def search() -> list[str]:
                results = sort_series_results(
                    talker.search_for_series(TITLE), TITLE, 2001, sort_by_year=True, exact_matches_first=True
                )
                assert {series.id for series in results} == set(ids)
                return [series.id for series in results]

            def tagging() -> list[dict[str, object]]:
                results = talker.fetch_issues_by_series_issue_num_and_year(ids, "7", 2001)
                assert len(results) == len(ids)
                assert {issue.series_id for issue in results} == set(ids)
                full = talker.fetch_comic_data(issue_id=str(int(ids[0]) * 20 + 7))
                assert full == results[0]
                return [dataclasses.asdict(issue) for issue in results]

            cases[name] = {"series": size, "issues": size * 20, "search": measure(search), "tagging": measure(tagging)}
            if name == "large" and args.profile:
                args.profile.parent.mkdir(parents=True, exist_ok=True)
                profiler = cProfile.Profile()
                profiler.enable()
                for _ in range(5):
                    search()
                    tagging()
                profiler.disable()
                profiler.dump_stats(str(args.profile))
    report["cases"] = cases
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                name: {key: round(case[key]["median_ms"], 3) for key in ("search", "tagging")}
                for name, case in cases.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
