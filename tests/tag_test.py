from __future__ import annotations

from comictaggerlib import issueidentifier
from comictaggerlib.resulttypes import OnlineMatchResults, Status
from comictaggerlib.tag import identify_comic


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
