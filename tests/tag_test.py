from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import comicapi.genericmetadata
from comictaggerlib import issueidentifier
from comictaggerlib.resulttypes import OnlineMatchResults, Status
from comictaggerlib.tag import identify_comic
from comictalker.comictalker import TalkerError


def test_identify_comic_records_search_network_failure(cbz, config, comicvine_api, monkeypatch):
    config, definitions = config
    monkeypatch.setattr(
        issueidentifier.IssueIdentifier,
        "identify",
        lambda self, ca, md: (issueidentifier.Result.fetch_data_failure, []),
    )
    match_results = OnlineMatchResults()

    result, match_results = identify_comic(
        cbz,
        cbz.read_tags("cr"),
        ["cr"],
        match_results,
        config,
        comicvine_api,
        lambda text: None,
        None,
    )

    assert result.status == Status.fetch_data_failure
    assert match_results.fetch_data_failures == [result]
    assert match_results.no_matches == []


def test_identify_comic_does_not_turn_empty_issue_data_into_success(cbz, config, comicvine_api, monkeypatch):
    config, _ = config
    monkeypatch.setattr(
        issueidentifier.IssueIdentifier,
        "identify",
        lambda self, ca, md: (
            issueidentifier.Result.single_good_match,
            [SimpleNamespace(md=comicapi.genericmetadata.GenericMetadata(issue_id="1"))],
        ),
    )
    monkeypatch.setattr(
        comicvine_api, "fetch_comic_data", Mock(return_value=comicapi.genericmetadata.GenericMetadata())
    )
    match_results = OnlineMatchResults()

    result, match_results = identify_comic(
        cbz,
        cbz.read_tags("cr"),
        ["cr"],
        match_results,
        config,
        comicvine_api,
        lambda text: None,
        None,
    )

    assert result.status == Status.fetch_data_failure
    assert match_results.fetch_data_failures == [result]


def test_identify_comic_records_issue_data_fetch_error(cbz, config, comicvine_api, monkeypatch):
    config, _ = config
    monkeypatch.setattr(
        issueidentifier.IssueIdentifier,
        "identify",
        lambda self, ca, md: (
            issueidentifier.Result.single_good_match,
            [SimpleNamespace(md=comicapi.genericmetadata.GenericMetadata(issue_id="1"))],
        ),
    )
    monkeypatch.setattr(comicvine_api, "fetch_comic_data", Mock(side_effect=TalkerError("Comic Vine")))
    match_results = OnlineMatchResults()

    result, match_results = identify_comic(
        cbz,
        cbz.read_tags("cr"),
        ["cr"],
        match_results,
        config,
        comicvine_api,
        lambda text: None,
        None,
    )

    assert result.status == Status.fetch_data_failure
    assert match_results.fetch_data_failures == [result]
