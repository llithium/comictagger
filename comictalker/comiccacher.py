"""A python class to manage caching of metadata from comic sources"""

#
# Copyright 2012-2014 ComicTagger Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import contextlib
import datetime
import pathlib
import sqlite3
import threading
from collections.abc import Iterator
from typing import Generic, TypeVar

from typing_extensions import NamedTuple

_CACHE_SETUP_LOCK = threading.Lock()
_UPSERT_SERIES = """INSERT INTO Series (id, source, data, complete) VALUES (?, ?, ?, ?)
    ON CONFLICT (id, source) DO UPDATE SET
        timestamp = excluded.timestamp, data = excluded.data, complete = excluded.complete
    WHERE excluded.complete OR NOT Series.complete"""
_UPSERT_ISSUE = """INSERT INTO Issues (id, source, series_id, data, complete) VALUES (?, ?, ?, ?, ?)
    ON CONFLICT (id, source) DO UPDATE SET
        timestamp = excluded.timestamp, series_id = excluded.series_id, data = excluded.data, complete = excluded.complete
    WHERE excluded.complete OR NOT Issues.complete"""


class Series(NamedTuple):
    id: str
    data: bytes


class Issue(NamedTuple):
    id: str
    series_id: str
    data: bytes


T = TypeVar("T", Issue, Series)


class CacheResult(NamedTuple, Generic[T]):
    data: T
    complete: bool


class ComicCacher:
    def __init__(self, cache_folder: pathlib.Path, version: str) -> None:
        self.cache_folder = cache_folder
        self.db_file = cache_folder / "comic_cache.db"
        self.version_file = cache_folder / "cache_version.txt"
        self.version = version
        with _CACHE_SETUP_LOCK:
            self.cache_folder.mkdir(parents=True, exist_ok=True)
            try:
                cached_version = self.version_file.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                cached_version = None
            if cached_version != version:
                self._remove_cache_files()
            self._create_cache_db()
            if cached_version != version:
                self.version_file.write_text(version, encoding="utf-8")

    def a_week(self) -> datetime.datetime:
        return datetime.datetime.today() - datetime.timedelta(days=7)

    def a_year(self) -> datetime.datetime:
        return datetime.datetime.today() - datetime.timedelta(days=365)

    def clear_cache(self) -> None:
        with _CACHE_SETUP_LOCK, self._connection() as con:
            con.execute("DELETE FROM SeriesSearchCache")
            con.execute("DELETE FROM Series")
            con.execute("DELETE FROM Issues")

    def _remove_cache_files(self) -> None:
        self.db_file.unlink(missing_ok=True)
        self.version_file.unlink(missing_ok=True)

    @contextlib.contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with contextlib.closing(sqlite3.connect(self.db_file)) as con, con:
            con.row_factory = sqlite3.Row
            yield con

    def _create_cache_db(self) -> None:
        with self._connection() as con, contextlib.closing(con.cursor()) as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS SeriesSearchCache(
                timestamp DATE DEFAULT (datetime('now','localtime')),
                id          TEXT NOT NULL,
                source      TEXT NOT NULL,
                search_term TEXT,
                PRIMARY KEY (id, source, search_term))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Series(
                timestamp DATE DEFAULT (datetime('now','localtime')),
                id       TEXT NOT NULL,
                source   TEXT NOT NULL,
                data     BLOB,
                complete BOOL,
                PRIMARY KEY (id, source))""")

            cur.execute("""CREATE TABLE IF NOT EXISTS Issues(
                timestamp DATE DEFAULT (datetime('now','localtime')),
                id        TEXT NOT NULL,
                source    TEXT NOT NULL,
                series_id TEXT,
                data      BLOB,
                complete  BOOL,
                PRIMARY KEY (id, source))""")

    def expire_stale_records(self, cur: sqlite3.Cursor, table: str, expiration: datetime.datetime) -> None:
        if "'" in table:
            raise ValueError("Single quotes not allowed in table names")
        cur.execute(f"DELETE FROM '{table}' WHERE timestamp  < ?", [str(expiration)])

    def add_search_results(self, source: str, search_term: str, series_list: list[Series], complete: bool) -> None:
        key = search_term.casefold()
        with self._connection() as con:
            con.execute("DELETE FROM SeriesSearchCache WHERE search_term = ? AND source = ?", (key, source))
            con.executemany(
                "INSERT INTO SeriesSearchCache (source, search_term, id) VALUES (?, ?, ?)",
                ((source, key, series.id) for series in series_list),
            )
            con.executemany(_UPSERT_SERIES, ((series.id, source, series.data, complete) for series in series_list))

    def add_series_info(self, source: str, series: Series, complete: bool) -> None:
        with self._connection() as con:
            con.execute(_UPSERT_SERIES, (series.id, source, series.data, complete))

    def add_issues_info(self, source: str, issues: list[Issue], complete: bool) -> None:
        with self._connection() as con:
            con.executemany(
                _UPSERT_ISSUE, ((issue.id, source, issue.series_id, issue.data, complete) for issue in issues)
            )

    def get_search_results(self, source: str, search_term: str, expire_stale: bool = True) -> list[CacheResult[Series]]:
        results = []
        with self._connection() as con, contextlib.closing(con.cursor()) as cur:

            if expire_stale:
                self.expire_stale_records(cur, "SeriesSearchCache", self.a_week())
                self.expire_stale_records(cur, "Series", self.a_year())

            cur.execute(
                """SELECT * FROM SeriesSearchCache INNER JOIN Series on
                 SeriesSearchCache.id=Series.id AND SeriesSearchCache.source=Series.source
                 WHERE search_term=? AND SeriesSearchCache.source=?""",
                [search_term.casefold(), source],
            )

            rows = cur.fetchall()

            for record in rows:
                result = Series(id=record["id"], data=record["data"])

                results.append(CacheResult(result, record["complete"]))

        return results

    def get_series_info(self, series_id: str, source: str, expire_stale: bool = True) -> CacheResult[Series] | None:
        with self._connection() as con, contextlib.closing(con.cursor()) as cur:

            if expire_stale:
                self.expire_stale_records(cur, "Series", self.a_year())

            # fetch
            cur.execute("SELECT * FROM Series WHERE id=? AND source=?", [series_id, source])

            row = cur.fetchone()

            if row is None:
                return None

            result = Series(id=row["id"], data=row["data"])

            return CacheResult(result, row["complete"])

    def get_series_issues_info(
        self, series_id: str, source: str, expire_stale: bool = True
    ) -> list[CacheResult[Issue]]:
        with self._connection() as con, contextlib.closing(con.cursor()) as cur:

            if expire_stale:
                self.expire_stale_records(cur, "Issues", self.a_year())

            # fetch
            results: list[CacheResult[Issue]] = []

            cur.execute("SELECT * FROM Issues WHERE series_id=? AND source=?", [series_id, source])
            rows = cur.fetchall()

            # now process the results
            for row in rows:
                record = CacheResult(Issue(id=row["id"], series_id=row["series_id"], data=row["data"]), row["complete"])

                results.append(record)

        return results

    def get_issue_info(self, issue_id: str, source: str, expire_stale: bool = True) -> CacheResult[Issue] | None:
        with self._connection() as con, contextlib.closing(con.cursor()) as cur:

            if expire_stale:
                self.expire_stale_records(cur, "Issues", self.a_year())

            cur.execute("SELECT * FROM Issues WHERE id=? AND source=?", [issue_id, source])
            row = cur.fetchone()

            record = None

            if row:
                record = CacheResult(Issue(id=row["id"], series_id=row["series_id"], data=row["data"]), row["complete"])

            return record
