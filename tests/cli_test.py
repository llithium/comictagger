from __future__ import annotations

from unittest.mock import Mock

import comicapi.genericmetadata
import comictaggerlib.cli
from comictaggerlib.resulttypes import Action, OnlineMatchResults, Result, Status


def test_export_reports_failed_archive_conversion(config, tmp_path):
    config, _ = config
    cli = comictaggerlib.cli.CLI(config, {})
    archive = Mock()
    archive.path = tmp_path / "book.cbr"
    archive.is_zip.return_value = False
    archive.export_as_zip.return_value = False

    result = cli.export(archive)

    assert result.action == Action.export
    assert result.status == Status.write_failure


def test_online_tag_assume_issue_one_forwards_query_metadata(config, cbz, monkeypatch):
    config, _ = config
    config.Auto_Tag__assume_issue_one = True
    config.Runtime_Options__enable_quick_tag = False
    talker = Mock()
    cli = comictaggerlib.cli.CLI(config, {config.Sources__source: talker})
    local_md = comicapi.genericmetadata.GenericMetadata(series="Example")
    captured: list[comicapi.genericmetadata.GenericMetadata] = []

    def identify(*args, **kwargs):
        captured.append(args[1])
        return Result(Action.save, Status.success, cbz.path), args[3]

    monkeypatch.setattr(comictaggerlib.cli, "identify_comic", identify)

    cli.online_tag(cbz, local_md, [], OnlineMatchResults())

    assert local_md.issue is None
    assert captured[0].issue == "1"
