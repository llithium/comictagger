"""A class to automatically identify a comic archive"""

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

import dataclasses
import functools
import io
import logging
import pathlib
from collections.abc import Callable
from enum import Enum, auto
from operator import attrgetter
from typing import Any, Literal, TypedDict

from PIL import Image, ImageChops

from comicapi import utils
from comicapi.comicarchive import ComicArchive
from comicapi.genericmetadata import ComicSeries, GenericMetadata, ImageHash
from comicapi.issuestring import IssueString
from comictaggerlib.imagefetcher import ImageFetcher, ImageFetcherException
from comictaggerlib.imagehasher import ImageHasher
from comictaggerlib.resulttypes import IssueResult, Score
from comictalker.comictalker import ComicTalker, RLCallBack, TalkerError

logger = logging.getLogger(__name__)


class SearchKeys(TypedDict):
    series: str
    issue_number: str
    month: int | None
    year: int | None
    issue_count: int | None


CoverHashKind = Literal["ahash", "phash"]


class IssueIdentifierNetworkError(Exception): ...


class IssueIdentifierCancelled(Exception): ...


class Result(Enum):
    single_good_match = auto()
    no_matches = auto()
    fetch_data_failure = auto()
    single_bad_cover_score = auto()
    multiple_bad_cover_scores = auto()
    multiple_good_matches = auto()


@dataclasses.dataclass
class IssueIdentifierOptions:
    series_match_search_thresh: int
    series_match_identify_thresh: int
    use_publisher_filter: bool
    publisher_filter: list[str]
    quiet: bool
    cache_dir: pathlib.Path
    border_crop_percent: int
    talker: ComicTalker
    tpb_detection: bool


class IssueIdentifier:
    def __init__(
        self,
        config: IssueIdentifierOptions,
        on_rate_limit: RLCallBack | None,
        output: Callable[[str], Any] = print,
        on_progress: Callable[[int, int, bytes], Any] | None = None,
    ) -> None:
        self.config = config
        self.talker = config.talker

        # a decent hamming score, good enough to call it a match
        self.min_score_thresh: int = 16

        # for alternate covers, be more stringent, since we're a bit more
        # scattershot in comparisons
        self.min_alternate_score_thresh = 12

        # the min distance a hamming score must be to separate itself from
        # closest neighbor
        self.min_score_distance = 4

        # a very strong hamming score, almost certainly the same image
        self.strong_score_thresh = 8

        # used to eliminate series names that are too long based on our search
        # string
        self.series_match_thresh = config.series_match_identify_thresh

        # used to eliminate unlikely publishers
        self.use_publisher_filter = config.use_publisher_filter
        self.publisher_filter = [s.strip().casefold() for s in config.publisher_filter]

        self.tpb_detection = config.tpb_detection

        self.output_function = output
        self.progress_callback: Callable[[int, int, bytes], Any] = lambda *x: ...
        if on_progress:
            self.progress_callback = on_progress
        self.on_rate_limit = on_rate_limit
        self.cancel = False

    @staticmethod
    def calculate_hash(
        image_data: bytes = b"", image: Image.Image | None = None, *, kind: CoverHashKind = "ahash"
    ) -> int:
        hasher = ImageHasher(data=image_data, image=image)
        return hasher.perception_hash() if kind == "phash" else hasher.average_hash()

    def log_msg(self, msg: Any) -> None:
        msg = str(msg)
        for handler in logging.getLogger().handlers:
            handler.flush()
        self.output(msg)

    def output(self, *args: Any, file: Any = None, **kwargs: Any) -> None:
        # We intercept and discard the file argument otherwise everything is passed to self.output_function

        # Ensure args[0] is defined and is a string for logger.info
        if not args:
            log_args: tuple[Any, ...] = ("",)
        elif isinstance(args[0], str):
            log_args = (args[0].strip("\n"), *args[1:])
        else:
            log_args = args
        log_msg = " ".join([str(x) for x in log_args])

        # Always send to logger so that we have a record for troubleshooting
        logger.info(log_msg, **kwargs)

        # If we are quiet we don't need to call the output function
        if self.config.quiet:
            return

        # default output is stdout
        self.output_function(*args, **kwargs)

    def identify(self, ca: ComicArchive, md: GenericMetadata) -> tuple[Result, list[IssueResult]]:
        if not self._check_requirements(ca):
            return Result.no_matches, []

        terms = self._get_search_keys(md)

        # we need, at minimum, a series and issue number
        if not (terms["series"] and terms["issue_number"]):
            self.log_msg("Not enough info for a search!")
            return Result.no_matches, []

        images = self._get_images(ca, md)
        self._print_terms(terms, images)

        try:
            issues = self._search_for_issues(terms)
            self.log_msg(f"Found {len(issues)} series that have an issue #{terms['issue_number']}")
            final_cover_matching, full = self._cover_matching(images, lambda: self._get_extra_images(ca, md), issues)
        except IssueIdentifierNetworkError:
            return Result.fetch_data_failure, []
        final_cover_matching = self._filter_tpb(md, final_cover_matching)

        best_score = 0
        if final_cover_matching:
            best_score = final_cover_matching[0].distance
        if best_score >= self.min_score_thresh:
            if len(final_cover_matching) == 1:
                self.log_msg("No matching pages in the issue.")
                self.log_msg("--------------------------------------------------------------------------")
                self._print_match(final_cover_matching[0])
                self.log_msg("--------------------------------------------------------------------------")
                search_result = Result.single_bad_cover_score
            else:
                self.log_msg("--------------------------------------------------------------------------")
                self.log_msg("Multiple bad cover matches!  Need to use other info...")
                self.log_msg("--------------------------------------------------------------------------")
                search_result = Result.multiple_bad_cover_scores
        else:
            if len(final_cover_matching) == 1:
                self.log_msg("--------------------------------------------------------------------------")
                self._print_match(final_cover_matching[0])
                self.log_msg("--------------------------------------------------------------------------")
                search_result = Result.single_good_match

            elif not final_cover_matching:
                self.log_msg("--------------------------------------------------------------------------")
                self.log_msg("No matches found :(")
                self.log_msg("--------------------------------------------------------------------------")
                search_result = Result.no_matches
            else:
                # we've got multiple good matches:
                self.log_msg("More than one likely candidate.")
                search_result = Result.multiple_good_matches
                final_cover_matching = full  # display more options for the user to pick
                self.log_msg("--------------------------------------------------------------------------")
                for match_item in final_cover_matching:
                    self._print_match(match_item)
                self.log_msg("--------------------------------------------------------------------------")

        return search_result, final_cover_matching

    def _crop_double_page(self, im: Image.Image) -> Image.Image | None:
        w, h = im.size

        try:
            cropped_im = im.crop((int(w / 2), 0, w, h))
        except Exception:
            logger.exception("cropCover() error")
            return None

        return cropped_im

    # Adapted from https://stackoverflow.com/a/10616717/20629671
    def _crop_border(self, im: Image.Image, ratio: int) -> Image.Image | None:
        # RGBA doesn't work????
        tmp = im.convert("RGB")

        bg = Image.new("RGB", tmp.size, "black")
        diff = ImageChops.difference(tmp, bg)
        diff = ImageChops.add(diff, diff, 2.0, -100)

        bbox = diff.getbbox()

        width_percent = 0
        height_percent = 0

        # If bbox is None that should mean it's solid black
        if bbox:
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]

            # Convert to percent
            width_percent = int(100 - ((width / im.width) * 100))
            height_percent = int(100 - ((height / im.height) * 100))
            logger.debug(
                "Width: %s Height: %s, ratio: %s  %s ratio met: %s",
                im.width,
                im.height,
                width_percent,
                height_percent,
                width_percent > ratio or height_percent > ratio,
            )

        # If there is a difference return the image otherwise return None
        if width_percent > ratio or height_percent > ratio:
            return im.crop(bbox)
        return None

    def _get_issue_cover_match_score(
        self,
        primary: ImageHash | None,
        alternates: list[ImageHash],
        local_hashes: Callable[[CoverHashKind], list[tuple[str, int]]],
        remote_hash: Callable[[str, CoverHashKind], int | None],
    ) -> Score:
        primary_kind: CoverHashKind = "phash" if primary and primary.Kind == "phash" else "ahash"
        covers = [cover for cover in (primary, *alternates) if cover is not None]
        remote_hashes = []
        for cover in covers:
            kind: CoverHashKind
            if cover.Kind == "phash":
                kind = "phash"
            elif cover.Kind == "ahash":
                kind = "ahash"
            elif cover.URL:
                kind = primary_kind
            else:
                continue

            cover_hash = cover.Hash if cover.Kind in ("phash", "ahash") else remote_hash(cover.URL, kind)
            if cover_hash is not None:
                remote_hashes.append((cover.URL, kind, cover_hash))

        best = Score(score=100, url="", remote_hash=0, local_hash=0, local_hash_name="0")
        local_by_kind = {kind: local_hashes(kind) for _, kind, _ in remote_hashes}
        if not local_by_kind:
            return best

        for index in range(len(next(iter(local_by_kind.values())))):
            for url, kind, cover_hash in remote_hashes:
                name, local_hash = local_by_kind[kind][index]
                distance = ImageHasher.hamming_distance(local_hash, cover_hash)
                self.log_msg(f" -  {distance:03}")
                if distance < best.score:
                    best = Score(
                        score=distance, url=url, remote_hash=cover_hash, local_hash=local_hash, local_hash_name=name
                    )
                if distance <= self.strong_score_thresh:
                    return best
        return best

    def _check_requirements(self, ca: ComicArchive) -> bool:

        if not ca.seems_to_be_a_comic_archive():
            self.log_msg(f"Sorry, but {ca.path} is not a comic archive!")
            return False
        return True

    def _process_cover(self, name: str, image_data: bytes) -> list[tuple[str, Image.Image]]:
        try:
            cover_image: Image.Image = Image.open(io.BytesIO(image_data))
            cover_image.load()
            images: list[tuple[str, Image.Image]] = [(name, cover_image)]
        except Exception as e:
            logger.error("Failed to read image: %s", e)
            return []

        # check the aspect ratio
        # if it's wider than it is high, it's probably a two page spread (back_cover, front_cover)
        # if so, crop it and calculate a second hash
        aspect_ratio = float(cover_image.height) / float(cover_image.width)
        if aspect_ratio < 1.0:
            im = self._crop_double_page(cover_image)
            if im is not None:
                images.append(("double page", im))

        # Check and remove black borders. Helps in identifying comics with an excessive black border like https://comicvine.gamespot.com/marvel-graphic-novel-1-the-death-of-captain-marvel/4000-21782/
        cropped = self._crop_border(cover_image, self.config.border_crop_percent)
        if cropped is not None:
            images.append(("black border cropped", cropped))

        return images

    def _get_images(self, ca: ComicArchive, md: GenericMetadata) -> list[tuple[str, Image.Image]]:
        covers: list[tuple[str, Image.Image]] = []
        for cover_index in md.get_cover_page_index_list():
            image_data = ca.get_page(cover_index)
            covers.extend(self._process_cover(f"{cover_index}", image_data))
        return covers

    def _get_extra_images(self, ca: ComicArchive, md: GenericMetadata) -> list[tuple[str, Image.Image]]:
        assert md
        covers: list[tuple[str, Image.Image]] = []
        for cover_index in range(1, min(3, ca.get_number_of_pages())):
            image_data = ca.get_page(md.get_archive_page_index(cover_index))
            covers.extend(self._process_cover(f"{cover_index}", image_data))
        return covers

    def _get_search_keys(self, md: GenericMetadata) -> SearchKeys:
        return SearchKeys(
            series=md.series or "",
            issue_number=IssueString(md.issue).as_string(),
            month=md.month,
            year=md.year,
            issue_count=md.issue_count,
        )

    def _user_canceled(self, callback: Callable[[], Any] | None = None) -> Any:
        if self.cancel:
            raise IssueIdentifierCancelled
        if callback is not None:
            return callback()

    def _print_terms(self, keys: SearchKeys, images: list[tuple[str, Image.Image]]) -> None:
        assert keys["series"]
        assert keys["issue_number"]
        self.log_msg(f"Using {self.talker.name} to search for:")
        self.log_msg("\tSeries: " + keys["series"])
        self.log_msg("\tIssue:  " + keys["issue_number"])
        if keys["month"] is not None:
            self.log_msg("\tMonth:  " + str(keys["month"]))
        if keys["year"] is not None:
            self.log_msg("\tYear:   " + str(keys["year"]))
        if keys["issue_count"] is not None:
            self.log_msg("\tCount:  " + str(keys["issue_count"]))
        for name, _ in images:
            self.log_msg("Cover: " + name)

        self.log_msg(f"Searching for {keys['series']} #{keys['issue_number']} ...")

    def _filter_series(self, terms: SearchKeys, search_results: list[ComicSeries]) -> list[ComicSeries]:
        assert terms["series"]

        filtered_results = []
        for item in search_results:
            length_approved = False
            publisher_approved = True
            date_approved = True

            # remove any series that starts after the issue year
            if terms["year"] is not None and item.start_year is not None:
                if item.start_year > terms["year"] + 1:
                    date_approved = False

            for name in [item.name, *item.aliases]:
                if utils.titles_match(terms["series"], name, self.series_match_thresh):
                    length_approved = True
                    break
            # remove any series from publishers on the filter
            if self.use_publisher_filter and item.publisher:
                if item.publisher.casefold() in self.publisher_filter:
                    publisher_approved = False

            if length_approved and publisher_approved and date_approved:
                filtered_results.append(item)
            else:
                logger.debug(
                    "Filtered out series: '%s' length approved: '%s', publisher approved: '%s', date approved: '%s'",
                    item.name,
                    length_approved,
                    publisher_approved,
                    date_approved,
                )
        return filtered_results

    def _match_covers(
        self,
        issues: list[tuple[ComicSeries, GenericMetadata]],
        local_hashes: Callable[[CoverHashKind], list[tuple[str, int]]],
        remote_hash: Callable[[str, CoverHashKind, int], int | None],
        *,
        use_alternates: bool = False,
    ) -> list[IssueResult]:
        matches = []
        alternate = " Alternate" if use_alternates else ""
        for index, (series, issue) in enumerate(issues):
            self._user_canceled(functools.partial(self.progress_callback, index, len(issues), b""))
            self.log_msg(f"Examining{alternate} covers for Series ID: {series.id} {series.name} ({series.start_year}):")
            score = self._get_issue_cover_match_score(
                issue._cover_image,
                issue._alternate_images if use_alternates else [],
                local_hashes,
                lambda url, kind: remote_hash(url, kind, index),
            )
            matches.append(IssueResult(score=score, series=series, md=issue))
            self.log_msg(f"best score {score.score:03}")
        return sorted(matches, key=attrgetter("distance"))

    def _print_match(self, item: IssueResult) -> None:
        self.log_msg(
            "-----> {} #{} {} ({}/{}) -- score: {}".format(
                item.series.name,
                item.md.issue,
                item.md.title,
                item.md.month,
                item.md.year,
                item.score.score,
            )
        )

    def _search_for_issues(self, terms: SearchKeys) -> list[tuple[ComicSeries, GenericMetadata]]:
        try:
            search_results = self.talker.search_for_series(
                terms["series"],
                callback=lambda x, y: self._user_canceled(functools.partial(self.progress_callback, x, y, b"")),
                series_match_thresh=self.config.series_match_search_thresh,
                on_rate_limit=self.on_rate_limit,
            )
        except TalkerError as e:
            self.log_msg(f"Error searching for series.\n{e}")
            raise IssueIdentifierNetworkError from e

        if not search_results:
            return []

        filtered_series = self._filter_series(terms, search_results)
        if not filtered_series:
            return []

        self.log_msg(f"Searching in {len(filtered_series)} series")

        self._user_canceled(functools.partial(self.progress_callback, 0, len(filtered_series), b""))

        series_by_id = {series.id: series for series in filtered_series}

        try:
            talker_result = self.talker.fetch_issues_by_series_issue_num_and_year(
                list(series_by_id.keys()),
                terms["issue_number"],
                terms["year"],
                on_rate_limit=self.on_rate_limit,
            )
        except TalkerError as e:
            self.log_msg(f"Issue with while searching for series details. Aborting...\n{e}")
            raise IssueIdentifierNetworkError from e

        if not talker_result:
            return []

        self._user_canceled(functools.partial(self.progress_callback, 0, 0, b""))

        issues: list[tuple[ComicSeries, GenericMetadata]] = []

        # now re-associate the issues and series
        for issue in talker_result:
            if issue.series_id in series_by_id:
                issues.append((series_by_id[issue.series_id], issue))
            else:
                logger.warning("Talker '%s' is returning arbitrary series when searching by id", self.talker.id)
        return issues

    @staticmethod
    def _comic_is_tpb(md: GenericMetadata) -> bool:
        title = utils.sanitize_title(md.title or "", basic=True).split()
        logger.debug("Checking if metadata is a tpb: %r", md)
        if title and (
            "tpb" in title or ["trade", "paper"] == title or ["trade", "paperback"] == title or ["trade"] == title
        ):
            logger.debug("Title indicates a tpb: %r", title)
            return True
        comic_format = utils.sanitize_title(utils.xlate(md.format) or "", basic=True)
        if comic_format and (comic_format) in (
            "annual",
            "anthology",
            "box set",
            "box-set",
            "directors cut",
            "giant",
            "giant size",
            "giant-size",
            "hardcover",
            "hard-cover",
            "king",
            "king size",
            "king-size",
            "one shot",
            "one-shot",
            "point 1",
            "special",
            "tpb",
            "trade paper back",
            "year 1",
            "year one",
        ):
            logger.debug("Format probably indicates a tpb: %r", comic_format)
            return True
        if len(md.pages) > 100:
            logger.debug("Page count indicates a tpb: %d", len(md.pages))
            return True
        return False
        # TODO: "<p>Collects <a data-ref-id=\"4050-4937\" href=\"/spawn/4050-4937/\" slug=\"spawn\">Spawn</a> 1-5.</p>"
        # TODO: "<p>Series of color omnibus collections collecting <a href=\"/spawn/4050-4937/\" data-ref-id=\"4050-4937\">Spawn</a>.</p>"

    # TODO:  "<p>Brazilian publication, translates <a data-ref-id=\"4050-4937\" href=\"/spawn/4050-4937/\" slug=\"spawn\">Spawn</a>.</p><p><b>Publishers</b></p><ul><li><span>#001-150: <a data-ref-id=\"4010-2094\" href=\"/abril/4010-2094/\" slug=\"abril\">Abril</a></span></li><li><span>#151-178: Pixel</span></li></ul>"

    def _filter_tpb(self, md: GenericMetadata, results: list[IssueResult]) -> list[IssueResult]:
        if not self.tpb_detection:
            return results
        if utils.xlate_int(md.issue_count) is None and len(md.pages) < 1:
            self.log_msg(f"Unable to filter TPBs: comic must have a page count > 0: {md.pages}")
            return results
        if len(results) == 1:
            self.log_msg("Unable to filter TPBs: Only a single result")
            return results
        issue_count = utils.xlate_int(md.issue_count) or 0
        local_is_tpb = self._comic_is_tpb(md)
        compatible = []
        for match in results:
            # One more test for the case choosing limited series first issue vs a trade with the same cover:
            if issue_count > 1 and match.series.count_of_issues == 1:
                self.log_msg(
                    f"Removing series {match.series.name} [{match.series.id}] from consideration local comic reports issue count for series at {issue_count} issues. Match issue count is {match.series.count_of_issues}"
                )
                continue

            remote_is_tpb = self._comic_is_tpb(match.md)
            if remote_is_tpb == local_is_tpb:
                compatible.append(match)
            else:
                self.log_msg(
                    f"Removing series {match.series.name} [{match.series.id}] from consideration match is tpb: {remote_is_tpb}, comic is tpb: {local_is_tpb}"
                )

        return compatible or results

    def _cover_matching(
        self,
        images: list[tuple[str, Image.Image]],
        extra_images: Callable[[], list[tuple[str, Image.Image]]],
        issues: list[tuple[ComicSeries, GenericMetadata]],
    ) -> tuple[list[IssueResult], list[IssueResult]]:
        images = list(images)
        local: dict[CoverHashKind, list[tuple[str, int]]] = {}
        remote: dict[tuple[str, CoverHashKind], int | None] = {}
        fetcher: ImageFetcher | None = None

        def local_hashes(kind: CoverHashKind) -> list[tuple[str, int]]:
            hashes = local.setdefault(kind, [])
            hashes.extend((name, self.calculate_hash(image=image, kind=kind)) for name, image in images[len(hashes) :])
            return hashes

        def remote_hash(url: str, kind: CoverHashKind, progress: int) -> int | None:
            nonlocal fetcher
            self._user_canceled()
            key = (url, kind)
            if key not in remote:
                if fetcher is None:
                    fetcher = ImageFetcher(self.config.cache_dir)
                try:
                    data = fetcher.fetch(url)
                except ImageFetcherException as e:
                    self._user_canceled()
                    self.log_msg(f"Network issue while fetching cover image from {self.talker.name}.")
                    raise IssueIdentifierNetworkError from e
                self._user_canceled(functools.partial(self.progress_callback, progress, len(issues), data))
                self._user_canceled()
                remote[key] = self.calculate_hash(data, kind=kind) if data else None
            return remote[key]

        matches = self._match_covers(issues, local_hashes, remote_hash)
        if not matches:
            self.log_msg(":-( no matches!")
            return [], []

        self.log_msg(f"Compared to covers in {len(matches)} issue(s): {[match.distance for match in matches]}")
        if matches[0].distance >= self.min_score_thresh:
            self.log_msg("Very weak scores for the cover. Analyzing alternate pages and covers...")
            images.extend(extra_images())
            try:
                alternate_matches = [
                    match
                    for match in self._match_covers(issues, local_hashes, remote_hash, use_alternates=True)
                    if match.distance < self.min_alternate_score_thresh
                ]
            except IssueIdentifierNetworkError:
                self.log_msg("Alternate cover lookup failed. Keeping the primary matches.")
            else:
                if alternate_matches:
                    matches = alternate_matches
                    self.log_msg(f"Success in secondary/alternate cover matching! Best score: {matches[0].distance}")

        best_score = matches[0].distance
        closest = [match for match in matches if match.distance <= best_score + self.min_score_distance]
        return closest, matches if len(closest) <= 5 else closest
