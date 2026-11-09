"""
ComicVine information source
"""

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

import argparse
import json
import logging
import pathlib
import re
import time
from collections.abc import Callable
from typing import Any, Generic, TypeVar
from urllib.parse import parse_qsl, urlencode, urljoin

import requests
import settngs
from typing_extensions import Required, TypedDict

from comicapi import utils
from comicapi.genericmetadata import ComicSeries, GenericMetadata, ImageHash, MetadataOrigin
from comicapi.issuestring import IssueString
from comicapi.utils import LocationParseError, StrEnum, parse_url
from comictalker.comiccacher import ComicCacher, Issue, Series
from comictalker.comictalker import ComicTalker, RLCallBack, TalkerDataError, TalkerNetworkError
from comictalker.vendor.pyrate_limiter import Limiter, RequestRate

logger = logging.getLogger(__name__)

TWITTER_TOO_MANY_REQUESTS = 420


class CVTypeID(StrEnum):
    Volume = "4050"  # CV uses volume to mean series
    Issue = "4000"


class CVImage(TypedDict, total=False):
    icon_url: str
    medium_url: str
    screen_url: str
    screen_large_url: str
    small_url: str
    super_url: Required[str]
    thumb_url: str
    tiny_url: str
    original_url: str
    image_tags: str


class CVAltImage(TypedDict):
    original_url: str
    id: Required[int]
    caption: str
    image_tags: str


class CVPublisher(TypedDict, total=False):
    api_detail_url: str
    id: Required[int]
    name: Required[str]


class CVCredit(TypedDict):
    api_detail_url: str
    id: Required[int]
    name: str
    site_detail_url: str


class CVPersonCredit(TypedDict):
    api_detail_url: str
    id: Required[int]
    name: str
    site_detail_url: str
    role: str


class CVSeries(TypedDict, total=False):
    api_detail_url: str
    site_detail_url: str
    aliases: str
    count_of_issues: int
    deck: str
    description: str
    id: Required[int]
    image: CVImage
    name: Required[str]
    publisher: CVPublisher
    start_year: str
    resource_type: str
    characters: list[CVCredit]
    locations: list[CVCredit]
    people: list[CVPersonCredit]


class CVIssue(TypedDict, total=False):
    aliases: str
    api_detail_url: str
    associated_images: list[CVAltImage]
    character_credits: list[CVCredit]
    character_died_in: None
    concept_credits: list[CVCredit]
    cover_date: str
    date_added: str
    date_last_updated: str
    deck: None
    description: str
    first_appearance_characters: None
    first_appearance_concepts: None
    first_appearance_locations: None
    first_appearance_objects: None
    first_appearance_storyarcs: None
    first_appearance_teams: None
    has_staff_review: bool
    id: Required[int]
    image: CVImage
    issue_number: str
    location_credits: list[CVCredit]
    name: str
    object_credits: list[CVCredit]
    person_credits: list[CVPersonCredit]
    site_detail_url: str
    store_date: str
    story_arc_credits: list[CVCredit]
    team_credits: list[CVCredit]
    team_disbanded_in: None
    volume: Required[CVSeries]  # CV uses volume to mean series


T = TypeVar("T", CVIssue, CVSeries, list[CVSeries], list[CVIssue])


class CVResult(TypedDict, Generic[T]):
    error: str
    limit: int
    offset: int
    number_of_page_results: int
    number_of_total_results: int
    status_code: int
    results: T
    version: str


# https://comicvine.gamespot.com/forums/api-developers-2334/api-rate-limiting-1746419/
# "Space out your requests so AT LEAST one second passes between each and you can make requests all day."
custom_limiter = Limiter(RequestRate(10, 10), RequestRate(200, 1 * 60 * 60))
default_limiter = Limiter(RequestRate(1, 10), RequestRate(100, 1 * 60 * 60))


class ComicVineTalker(ComicTalker):
    name: str = "Comic Vine"
    id: str = "comicvine"
    website: str = "https://comicvine.gamespot.com"
    logo_url: str = f"{website}/a/bundles/comicvinesite/images/logo.png"
    attribution: str = f"Metadata provided by <a href='{website}'>{name}</a>"
    about: str = (
        f"<a href='{website}'>{name}</a> has the largest collection of comic book data available through "
        f"its public facing API. "
        f"<p>NOTE: Using the default API key will severely limit access times. A personal API "
        f"key will allow for a <b>10 times increase</b> in online search speed. See the "
        "<a href='https://github.com/comictagger/comictagger/wiki/UserGuide#comic-vine'>Wiki page</a> for "
        "more information.</p>"
    )

    def __init__(self, version: str, cache_folder: pathlib.Path):
        super().__init__(version, cache_folder)
        self.limiter = default_limiter
        # Default settings
        self.default_api_url = self.api_url = f"{self.website}/api/"
        self.default_api_key = self.api_key = "27431e6787042105bd3e47e169a624521f89f3a4"
        self.use_series_start_as_volume: bool = False
        self.total_requests_made: dict[str, int] = utils.DefaultDict(default=lambda x: 0)
        self.custom_url_parameters: dict[str, str] = {}

    def _log_total_requests(self) -> None:
        logger.debug("Total requests made to cv: %s", dict(self.total_requests_made))

    def register_settings(self, parser: settngs.Manager) -> None:
        parser.add_setting(
            "--cv-use-series-start-as-volume",
            default=False,
            action=argparse.BooleanOptionalAction,
            display_name="Use series start as volume",
            help="Use the series start year as the volume number",
        )

        # The default needs to be unset or None.
        # This allows this setting to be unset with the empty string, allowing the default to change
        parser.add_setting(
            f"--{self.id}-key",
            display_name="API Key",
            help=f"Use the given Comic Vine API Key. (default: {self.default_api_key})",
        )
        parser.add_setting(
            f"--{self.id}-url",
            display_name="API URL",
            help=f"Use the given Comic Vine URL. (default: {self.default_api_url})",
        )
        parser.add_setting(
            f"--{self.id}-custom-parameters",
            display_name="Custom URL Parameters",
            help="Custom url parameters to add to the url, must already be url encoded. (eg. refresh_cache=true)",
        )

    def parse_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        settings = super().parse_settings(settings)

        self.use_series_start_as_volume = settings["cv_use_series_start_as_volume"]

        self.custom_url_parameters = dict(parse_qsl(settings[f"{self.id}_custom_parameters"]))

        # Set a different limit if using the default API key
        if self.api_key == self.default_api_key:
            self.limiter = default_limiter
        else:
            self.limiter = custom_limiter

        return settings

    def _request(self, url: str, params: dict[str, Any], *, api_key: str, timeout: int) -> requests.Response:
        return requests.get(
            url,
            params={**params, "api_key": api_key, "format": "json"},
            headers={"user-agent": "comictagger/" + self.version},
            timeout=timeout,
        )

    def check_status(self, settings: dict[str, Any]) -> tuple[str, bool]:
        api_key, api_url = self._effective_api_settings(settings)
        test_url = urljoin(api_url, "team/1/")
        try:
            self.total_requests_made[test_url] += 1
            response = self._request(test_url, {}, api_key=api_key, timeout=10)
            response.raise_for_status()
            # The probe can return an API error for reasons other than invalid credentials.
            if response.json()["status_code"] == 100:
                return "The API key is INVALID!", False
            return "The API key is valid", True
        except (requests.RequestException, ValueError, KeyError, TypeError):
            return "Failed to connect to the URL!", False
        finally:
            self._log_total_requests()

    def cacher(self) -> ComicCacher:
        return ComicCacher(self.cache_folder, self.version)

    def search_for_series(
        self,
        series_name: str,
        callback: Callable[[int, int], None] | None = None,
        refresh_cache: bool = False,
        literal: bool = False,
        series_match_thresh: int = 90,
        *,
        on_rate_limit: RLCallBack | None = None,
    ) -> list[ComicSeries]:
        search_series_name = series_name if literal else utils.sanitize_title(series_name)
        cache_key = f"{series_match_thresh}\0{series_name}"

        logger.info("%s searching: %s", self.name, search_series_name)

        # Before we search online, look in our cache, since we might have done this same search recently
        # For literal searches always retrieve from online
        cvc = self.cacher()
        if not refresh_cache and not literal:
            cached_search_results = cvc.get_search_results(self.id, cache_key)

            if cached_search_results:
                logger.debug("Search for %s cached: True", repr(series_name))
                return [self._format_series(json.loads(record.data.data)) for record in cached_search_results]
        logger.debug("Search for %s cached: False", repr(series_name))

        params = {  # CV uses volume to mean series
            "resources": "volume",
            "query": search_series_name,
            "field_list": "volume,name,id,start_year,publisher,image,description,count_of_issues,aliases,site_detail_url",
            "page": 1,
            "limit": 100,
        }

        cv_response: CVResult[list[CVSeries]] = self._get_cv_content(
            urljoin(self.api_url, "search/"),
            params,
            on_rate_limit=on_rate_limit,
        )

        search_results: list[CVSeries] = []

        # see http://api.comicvine.com/documentation/#handling_responses

        current_result_count = cv_response["number_of_page_results"]
        total_result_count = cv_response["number_of_total_results"]

        # 8 Dec 2018 - Comic Vine changed query results again. Terms are now
        # ORed together, and we get thousands of results.  Good news is the
        # results are sorted by relevance, so we can be smart about halting the search.
        # 1. Don't fetch more than some sane amount of pages.
        # 2. Halt when any result on the current page is less than or equal to a set ratio using thefuzz
        max_results = 500  # 5 pages

        total_result_count = min(total_result_count, max_results)

        if callback is None:
            logger.debug(
                "Found %s of %s results", cv_response["number_of_page_results"], cv_response["number_of_total_results"]
            )
        search_results.extend(cv_response["results"])
        page = 1

        if callback is not None:
            callback(current_result_count, total_result_count)

        # see if we need to keep asking for more pages...
        while current_result_count < total_result_count:
            if not literal:
                # Stop searching once any entry falls below the threshold
                stop_searching = any(
                    not utils.titles_match(search_series_name, series["name"], series_match_thresh)
                    for series in cv_response["results"]
                )

                if stop_searching:
                    break

            if callback is None:
                logger.debug("getting another page of results %s of %s...", current_result_count, total_result_count)
            page += 1

            params["page"] = page
            cv_response = self._get_cv_content(
                urljoin(self.api_url, "search/"),
                params,
                on_rate_limit=on_rate_limit,
            )

            page_result_count = cv_response["number_of_page_results"]
            if page_result_count <= 0:
                logger.warning("Comic Vine returned an empty page before all results were received")
                break

            search_results.extend(cv_response["results"])
            current_result_count += page_result_count

            if callback is not None:
                callback(current_result_count, total_result_count)

        if not literal:
            cvc.add_search_results(self.id, cache_key, [self._series_record(item) for item in search_results], False)
        return [self._format_series(record) for record in search_results]

    def fetch_comic_data(
        self,
        issue_id: str | None = None,
        series_id: str | None = None,
        issue_number: str = "",
        on_rate_limit: RLCallBack | None = None,
    ) -> GenericMetadata:
        comic_data = GenericMetadata()
        if issue_id:
            comic_data = self._fetch_issue_data_by_issue_id(
                issue_id,
                on_rate_limit=on_rate_limit,
            )
        elif issue_number and series_id:
            comic_data = self._fetch_issue_data(
                int(series_id),
                issue_number,
                on_rate_limit=on_rate_limit,
            )

        return comic_data

    def fetch_series(
        self,
        series_id: str,
        on_rate_limit: RLCallBack | None = None,
    ) -> ComicSeries:
        return self._fetch_series_data(
            int(series_id),
            on_rate_limit=on_rate_limit,
        )

    def fetch_issues_in_series(
        self,
        series_id: str,
        on_rate_limit: RLCallBack | None = None,
    ) -> list[GenericMetadata]:
        return [
            x[0]
            for x in self._fetch_issues_in_series(
                series_id,
                on_rate_limit=on_rate_limit,
            )
        ]

    def fetch_issues_by_series_issue_num_and_year(
        self,
        series_id_list: list[str],
        issue_number: str,
        year: str | int | None,
        on_rate_limit: RLCallBack | None = None,
    ) -> list[GenericMetadata]:
        cvc = self.cacher()
        results: list[GenericMetadata] = []
        needed_volumes: list[str] = []
        start_year = utils.xlate_int(year)
        for series_id in dict.fromkeys(map(str, series_id_list)):
            series_record = cvc.get_series_info(series_id, self.id, expire_stale=False)
            issues = cvc.get_series_issues_info(series_id, self.id) if series_record else []
            for cached, _ in issues:
                issue: CVIssue = json.loads(cached.data)
                _, _, cover_year = utils.parse_date_str(issue.get("cover_date"))
                in_date_window = start_year is None or (
                    cover_year is not None and start_year <= cover_year <= start_year + 1
                )
                if issue.get("issue_number") == issue_number and in_date_window:
                    series = self._fetch_series_data(int(series_id), on_rate_limit=on_rate_limit)
                    results.append(self._map_comic_issue_to_metadata(issue, series))
                    break
            else:
                cached_count = json.loads(series_record.data.data).get("count_of_issues") if series_record else None
                if not issues or cached_count != len(issues):
                    needed_volumes.append(series_id)

        if not needed_volumes:
            return results

        flt = f"volume:{'|'.join(needed_volumes)},issue_number:{issue_number}"
        if start_year is not None:
            flt += f",cover_date:{start_year}-1-1|{start_year + 1}-12-31"

        params = {
            "field_list": "id,volume,issue_number,name,image,cover_date,site_detail_url,description,aliases,associated_images",
            "filter": flt,
        }
        fetched = self._fetch_all_issue_pages(params, on_rate_limit=on_rate_limit)
        self._cache_issues(cvc, fetched, complete=False)
        series_by_id: dict[int, ComicSeries] = {}
        fetched_results = []
        for issue in fetched:
            series_id_int = issue["volume"]["id"]
            if series_id_int not in series_by_id:
                series_by_id[series_id_int] = self._fetch_series_data(series_id_int, on_rate_limit=on_rate_limit)
            fetched_results.append(self._map_comic_issue_to_metadata(issue, series_by_id[series_id_int]))
        return fetched_results + results

    @staticmethod
    def _series_record(series: CVSeries) -> Series:
        return Series(id=str(series["id"]), data=json.dumps(series).encode("utf-8"))

    def _cache_issues(self, cache: ComicCacher, issues: list[CVIssue], *, complete: bool) -> None:
        cache.add_issues_info(
            self.id,
            [
                Issue(id=str(issue["id"]), series_id=str(issue["volume"]["id"]), data=json.dumps(issue).encode("utf-8"))
                for issue in issues
            ],
            complete,
        )

    def fetch_comics(
        self,
        *,
        issue_ids: list[str],
        on_rate_limit: RLCallBack | None = None,
    ) -> list[GenericMetadata]:
        cvc = self.cacher()
        needed_ids = []
        issues: list[CVIssue] = []
        cached_series: dict[str, ComicSeries] = {}
        for issue_id in dict.fromkeys(issue_ids):
            cached = cvc.get_issue_info(issue_id, self.id)
            if cached is None:
                needed_ids.append(issue_id)
            else:
                issues.append(json.loads(cached.data.data))

        # Comic Vine accepts up to 100 IDs in one filter.
        for start in range(0, len(needed_ids), 100):
            batch = needed_ids[start : start + 100]
            fetched = self._fetch_all_issue_pages({"filter": f"id:{'|'.join(batch)}"}, on_rate_limit=on_rate_limit)
            self._cache_issues(cvc, fetched, complete=False)
            issues.extend(fetched)
            missing = set(batch).difference(str(issue["id"]) for issue in fetched)
            if missing:
                logger.debug("%s issue ids %r do not exist anymore", self.name, missing)

        results = []
        for issue in issues:
            series = issue["volume"]
            series_id = str(series["id"])
            if series_id not in cached_series:
                record = cvc.get_series_info(series_id, self.id, expire_stale=False)
                if record is not None:
                    series = json.loads(record.data.data)
                else:
                    cvc.add_series_info(self.id, self._series_record(series), complete=False)
                cached_series[series_id] = self._format_series(series)
            results.append(self._map_comic_issue_to_metadata(issue, cached_series[series_id]))
        return results

    def _get_cv_content(
        self,
        url: str,
        params: dict[str, Any],
        *,
        on_rate_limit: RLCallBack | None,
    ) -> CVResult[T]:
        """
        Get the content from the CV server.
        """

        cv_response: CVResult[T] = self._get_url_content(url, params, on_rate_limit=on_rate_limit)
        if not isinstance(cv_response, dict) or not isinstance(cv_response.get("status_code"), int):
            raise TalkerDataError(self.name, 2, "Comic Vine did not return a response status")
        if cv_response["status_code"] != 1:
            error = cv_response.get("error", "Unknown error")
            logger.debug(
                "%s query failed with error #%s:  [%s].",
                self.name,
                cv_response["status_code"],
                error,
            )
            raise TalkerNetworkError(self.name, 0, f"{cv_response['status_code']}: {error}")

        results = cv_response.get("results")
        if not isinstance(results, (list, dict)):
            raise TalkerDataError(self.name, 2, "Comic Vine did not return issue or series results")
        if isinstance(results, list) and not all(
            isinstance(cv_response.get(field), int) for field in ("number_of_page_results", "number_of_total_results")
        ):
            raise TalkerDataError(self.name, 2, "Comic Vine did not return pagination counts")

        return cv_response

    def _get_url_content(self, url: str, params: dict[str, Any], on_rate_limit: RLCallBack | None = None) -> Any:
        final_params = {**self.custom_url_parameters, **params}
        logged_params = {key: value for key, value in final_params.items() if key != "api_key"}
        ratelimit_key = self._get_ratelimit_key(url)

        for attempt in range(1, 5):
            with self.limiter.ratelimit(ratelimit_key, delay=True, on_rate_limit=on_rate_limit):
                logger.debug("Requesting: %s?%s", url, urlencode(logged_params))
                self.total_requests_made[ratelimit_key] += 1
                try:
                    response = self._request(url, final_params, api_key=self.api_key, timeout=60)
                except requests.Timeout as e:
                    if attempt == 4:
                        raise TalkerNetworkError(self.name, 4) from e
                    continue
                except requests.RequestException as e:
                    raise TalkerNetworkError(self.name, 0, str(e)) from e

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as e:
                    raise TalkerDataError(self.name, 2, "ComicVine did not provide json") from e
            if response.status_code in (requests.codes.TOO_MANY_REQUESTS, TWITTER_TOO_MANY_REQUESTS):
                if attempt == 4:
                    raise TalkerNetworkError(
                        self.name,
                        3,
                        "Rate Limit Error: Check your current API usage limit at https://comicvine.gamespot.com/api/",
                    )
                logger.info("%s rate limit encountered. Waiting for 10 seconds", self.name)
                self._log_total_requests()
                self._wait_for_rate_limit(on_rate_limit)
            elif response.status_code in (
                requests.codes.SERVER_ERROR,
                requests.codes.BAD_GATEWAY,
                requests.codes.UNAVAILABLE,
            ):
                logger.debug("Try #%d: %d", attempt, response.status_code)
            else:
                logger.error("Unknown status code: %d, %s", response.status_code, response.content)
                break

        raise TalkerNetworkError(self.name, 5, "Unknown error occurred")

    @staticmethod
    def _wait_for_rate_limit(on_rate_limit: RLCallBack | None) -> None:
        remaining = 10.0
        interval = on_rate_limit.interval if on_rate_limit and on_rate_limit.interval > 0 else remaining
        while remaining > 0:
            delay = min(remaining, interval)
            if on_rate_limit:
                on_rate_limit.callback(remaining, delay)
            time.sleep(delay)
            remaining -= delay

    def _get_ratelimit_key(self, url: str) -> str:
        if self.api_key == self.default_api_key:
            return "cv"

        ratelimit_key = url.removeprefix(self.api_url)
        for x in CVTypeID:
            ratelimit_key = ratelimit_key.partition(f"/{x}-")[0]
        return ratelimit_key

    def _format_series(self, record: CVSeries) -> ComicSeries:
        # Flatten publisher to name only
        if record.get("publisher") is None:
            pub_name = ""
        else:
            pub_name = record["publisher"].get("name", "")

        if record.get("image") is None:
            image_url = ""
        else:
            image_url = record["image"].get("super_url", "")

        start_year = utils.xlate_int(record.get("start_year", ""))

        aliases = record.get("aliases") or ""
        volume_match = re.search(
            r"\b(?:v(?:ol|olume)?)[.\s-]*(\d+)",
            record.get("deck") or "",
            re.IGNORECASE,
        )

        series = ComicSeries(
            aliases=set(utils.split(aliases, "\n")),
            count_of_issues=record.get("count_of_issues"),
            count_of_volumes=None,
            description=record.get("description", ""),
            id=str(record["id"]),
            image_url=image_url,
            name=record["name"],
            publisher=pub_name,
            start_year=start_year,
            format=None,
            volume_number=utils.xlate_int(volume_match.group(1)) if volume_match else None,
        )
        url = utils.xlate(record.get("site_detail_url"))
        if url:
            try:
                series.web_links = [parse_url(url)]
            except LocationParseError:
                logger.debug("Ignoring invalid Comic Vine series URL: %s", url, exc_info=True)
        return series

    def _fetch_all_issue_pages(
        self,
        params: dict[str, Any],
        *,
        on_rate_limit: RLCallBack | None,
    ) -> list[CVIssue]:
        """Fetch all advertised issue pages or fail when the API stops progressing."""
        url = urljoin(self.api_url, "issues/")
        request_params = params.copy()
        response: CVResult[list[CVIssue]] = self._get_cv_content(
            url,
            request_params,
            on_rate_limit=on_rate_limit,
        )
        results = list(response["results"])
        total = response["number_of_total_results"]
        offset = response.get("offset", 0)
        page_count = response["number_of_page_results"]

        while len(results) < total:
            if page_count <= 0 or not response["results"]:
                raise TalkerDataError(
                    self.name,
                    3,
                    "Comic Vine returned an empty issue page before all advertised results were received",
                )

            next_offset = offset + page_count
            if next_offset <= offset:
                raise TalkerDataError(
                    self.name,
                    3,
                    "Comic Vine issue pagination stopped advancing before all advertised results were received",
                )

            request_params["offset"] = next_offset
            response = self._get_cv_content(
                url,
                request_params,
                on_rate_limit=on_rate_limit,
            )
            page_results = list(response["results"])
            page_count = response["number_of_page_results"]
            response_offset = response.get("offset", next_offset)
            if page_count <= 0 or not page_results or response_offset <= offset:
                raise TalkerDataError(
                    self.name,
                    3,
                    "Comic Vine issue pagination stopped advancing before all advertised results were received",
                )

            results.extend(page_results)
            offset = response_offset

        return results

    def _fetch_issues_in_series(
        self,
        series_id: str,
        on_rate_limit: RLCallBack | None,
    ) -> list[tuple[GenericMetadata, bool]]:
        logger.debug("Fetching all issues in series: %s", series_id)
        # before we search online, look in our cache, since we might already have this info
        cvc = self.cacher()
        cached_results = cvc.get_series_issues_info(series_id, self.id)

        series = self._fetch_series_data(int(series_id), on_rate_limit=on_rate_limit)
        if len(cached_results) == series.count_of_issues:
            return [
                (self._map_comic_issue_to_metadata(json.loads(item.data.data), series), item.complete)
                for item in cached_results
            ]

        fetched = self._fetch_all_issue_pages(
            {"filter": f"volume:{series_id}", "offset": 0}, on_rate_limit=on_rate_limit
        )
        self._cache_issues(cvc, fetched, complete=False)
        return [(self._map_comic_issue_to_metadata(issue, series), False) for issue in fetched]

    def _fetch_series_data(
        self,
        series_id: int,
        on_rate_limit: RLCallBack | None,
    ) -> ComicSeries:
        logger.debug("Fetching series info: %s", series_id)
        # before we search online, look in our cache, since we might already have this info
        cvc = self.cacher()
        cached_series = cvc.get_series_info(str(series_id), self.id)

        logger.debug("Series cached: %s", bool(cached_series))
        if cached_series is not None and cached_series.complete:
            return self._format_series(json.loads(cached_series.data.data))

        series_url = urljoin(self.api_url, f"volume/{CVTypeID.Volume}-{series_id}/")  # CV uses volume to mean series

        cv_response: CVResult[CVSeries] = self._get_cv_content(
            series_url,
            {},
            on_rate_limit=on_rate_limit,
        )

        series_results = cv_response["results"]

        if series_results:
            cvc.add_series_info(self.id, self._series_record(series_results), complete=True)

        return self._format_series(series_results)

    def _fetch_issue_data(
        self,
        series_id: int,
        issue_number: str,
        on_rate_limit: RLCallBack | None,
    ) -> GenericMetadata:
        logger.debug("Fetching issue by series ID: %s and issue number: %s", series_id, issue_number)
        issues_list_results = self._fetch_issues_in_series(
            str(series_id),
            on_rate_limit=on_rate_limit,
        )

        normalized = (IssueString(issue_number).as_string() or "1").casefold()
        for metadata, complete in issues_list_results:
            if IssueString(metadata.issue).as_string().casefold() != normalized:
                continue
            if complete and not metadata.is_empty:
                return metadata
            if metadata.issue_id is not None:
                return self._fetch_issue_data_by_issue_id(metadata.issue_id, on_rate_limit=on_rate_limit)
            break
        return GenericMetadata()

    def _fetch_issue_data_by_issue_id(
        self,
        issue_id: str,
        on_rate_limit: RLCallBack | None,
    ) -> GenericMetadata:
        cvc = self.cacher()
        cached_issue = cvc.get_issue_info(issue_id, self.id)
        if cached_issue and cached_issue.complete:
            issue: CVIssue = json.loads(cached_issue.data.data)
        else:
            issue_url = urljoin(self.api_url, f"issue/{CVTypeID.Issue}-{issue_id}/")
            response: CVResult[CVIssue] = self._get_cv_content(issue_url, {}, on_rate_limit=on_rate_limit)
            issue = response["results"]
            self._cache_issues(cvc, [issue], complete=True)

        series = self._fetch_series_data(issue["volume"]["id"], on_rate_limit=on_rate_limit)
        return self._map_comic_issue_to_metadata(issue, series)

    def _map_comic_issue_to_metadata(self, issue: CVIssue, series: ComicSeries) -> GenericMetadata:
        md = GenericMetadata(
            data_origin=MetadataOrigin(self.id, self.name),
            issue_id=utils.xlate(issue.get("id")),
            series_id=series.id,
            series_start_year=series.start_year,
            title_aliases=set(utils.split(issue.get("aliases"), "\n")),
            publisher=utils.xlate(series.publisher),
            description=issue.get("description"),
            issue=utils.xlate(IssueString(issue.get("issue_number")).as_string()),
            issue_count=utils.xlate_int(series.count_of_issues),
            format=utils.xlate(series.format),
            volume_count=utils.xlate_int(series.count_of_volumes),
            title=utils.xlate(issue.get("name")),
            series=utils.xlate(series.name),
            series_aliases=series.aliases,
        )
        url = utils.xlate(issue.get("site_detail_url"))
        if url:
            try:
                md.web_links = [parse_url(url)]
            except LocationParseError:
                logger.debug("Ignoring invalid Comic Vine issue URL: %s", url, exc_info=True)
        if issue.get("image") is not None:
            md._cover_image = ImageHash(URL=issue.get("image", {}).get("super_url", ""), Hash=0, Kind="")

        for alt in issue.get("associated_images", []):
            md._alternate_images.append(ImageHash(URL=alt["original_url"], Hash=0, Kind=""))

        for character in issue.get("character_credits", set()):
            md.characters.add(character["name"])

        for location in issue.get("location_credits", set()):
            md.locations.add(location["name"])

        for team in issue.get("team_credits", set()):
            md.teams.add(team["name"])

        for arc in issue.get("story_arc_credits", []):
            md.story_arcs.append(arc["name"])

        for person in issue.get("person_credits", []):
            roles = utils.split(person.get("role", ""), ",")
            for role in roles:
                md.add_credit(person["name"], role.title(), False)

        md.volume = series.volume_number
        if self.use_series_start_as_volume:
            md.volume = series.start_year

        if issue.get("cover_date"):
            md.day, md.month, md.year = utils.parse_date_str(issue.get("cover_date"))
        elif series.start_year:
            md.year = utils.xlate_int(series.start_year)

        return md
