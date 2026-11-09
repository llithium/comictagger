from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from comicapi.comicarchive import ComicArchive
from comicapi.genericmetadata import GenericMetadata
from comictaggerlib.ctsettings import ct_ns
from comictaggerlib.issueidentifier import IssueIdentifier, IssueIdentifierCancelled, IssueIdentifierOptions
from comictaggerlib.issueidentifier import Result as IIResult
from comictaggerlib.md import prepare_metadata
from comictaggerlib.resulttypes import Action, MatchStatus, Result, Status
from comictalker.comictalker import ComicTalker, RLCallBack

logger = logging.getLogger(__name__)


def identify_comic(
    ca: ComicArchive,
    md: GenericMetadata,
    tags_read: list[str],
    config: ct_ns,
    talker: ComicTalker,
    output: Callable[[str], Any],
    on_rate_limit: RLCallBack | None,
    on_progress: Callable[[int, int, bytes], Any] | None = None,
    *,
    query_md: GenericMetadata | None = None,
    series_override: str = "",
) -> Result:
    if md.is_empty:
        logger.error("No metadata given to search online with!")
        return Result(
            Action.save,
            status=Status.match_failure,
            original_path=ca.path,
            match_status=MatchStatus.no_match,
            tags_read=tags_read,
        )
    iio = IssueIdentifierOptions(
        series_match_search_thresh=config.Issue_Identifier__series_match_search_thresh,
        series_match_identify_thresh=config.Issue_Identifier__series_match_identify_thresh,
        use_publisher_filter=config.Auto_Tag__use_publisher_filter,
        publisher_filter=config.Auto_Tag__publisher_filter,
        quiet=config.Runtime_Options__quiet,
        cache_dir=config.Runtime_Options__config.user_cache_dir,
        border_crop_percent=config.Issue_Identifier__border_crop_percent,
        talker=talker,
        tpb_detection=config.Issue_Identifier__tpb_detection,
    )
    ii = IssueIdentifier(
        iio,
        output=output,
        on_rate_limit=on_rate_limit,
        on_progress=on_progress,
    )

    query_md = (query_md if query_md is not None else md).copy()
    if not config.Auto_Tag__use_year_when_identifying:
        query_md.year = None
    if series_override:
        query_md.series = series_override
    elif config.Auto_Tag__ignore_leading_numbers_in_filename and query_md.series is not None:
        query_md.series = re.sub(r"^([\d.]+)", "", query_md.series)

    result, matches = ii.identify(ca, query_md)

    res = Result(
        Action.save,
        status=Status.match_failure,
        original_path=ca.path,
        online_results=matches,
        tags_read=tags_read,
    )
    if result == IIResult.multiple_bad_cover_scores or (
        result == IIResult.single_bad_cover_score and not config.Auto_Tag__save_on_low_confidence
    ):
        res.match_status = MatchStatus.low_confidence_match
        logger.error("Online search: Low confidence match. Save aborted")
        return res

    if result == IIResult.multiple_good_matches:
        logger.error("Online search: Multiple good matches. Save aborted")
        res.match_status = MatchStatus.multiple_match

        return res

    if result == IIResult.no_matches:
        logger.error("Online search: No match found. Save aborted")
        res.match_status = MatchStatus.no_match

        return res

    if result == IIResult.fetch_data_failure:
        logger.error("Online search: Data fetch failed. Save aborted")
        res.status = Status.fetch_data_failure

        return res

    # we got here, so we have a single match
    # now get the particular issue data
    try:
        assert matches[0].md.issue_id
        ct_md = talker.fetch_comic_data(issue_id=matches[0].md.issue_id, on_rate_limit=on_rate_limit)
    except IssueIdentifierCancelled:
        raise
    except Exception as e:
        logger.exception("Error retrieving issue details. Save aborted. %s", e)
        res.status = Status.fetch_data_failure
        res.match_status = MatchStatus.good_match
        return res

    if ct_md is None or ct_md.is_empty:
        logger.error("Online search returned no issue details. Save aborted")
        res.status = Status.fetch_data_failure
        res.match_status = MatchStatus.good_match
        return res

    ct_md = prepare_metadata(md, ct_md, config)

    res.status = Status.success
    res.md = ct_md
    if result == IIResult.single_good_match:
        res.match_status = MatchStatus.good_match

    return res
