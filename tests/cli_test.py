from __future__ import annotations

from unittest.mock import Mock

import pytest

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


@pytest.mark.parametrize("failure", ["empty", "exception"])
def test_direct_issue_fetch_failure_does_not_write_existing_metadata(config, tmp_comic, monkeypatch, failure):
    config, _ = config
    config.Auto_Tag__online = True
    config.Auto_Tag__issue_id = "missing"
    config.Runtime_Options__tags_read = ["cr"]
    config.Runtime_Options__tags_write = ["cr"]
    talker = Mock()
    if failure == "empty":
        talker.fetch_comic_data.return_value = comicapi.genericmetadata.GenericMetadata()
    else:
        talker.fetch_comic_data.side_effect = RuntimeError("network unavailable")
    cli = comictaggerlib.cli.CLI(config, {config.Sources__source: talker})
    original = tmp_comic.read_tags("cr")
    write_tags = Mock(return_value=True)
    monkeypatch.setattr(cli, "write_tags", write_tags)

    result, _ = cli.save(tmp_comic, OnlineMatchResults())

    assert result.status == Status.fetch_data_failure
    assert not write_tags.called
    assert tmp_comic.read_tags("cr") == original


def test_unhandled_archive_action_reports_the_requested_action(config, tmp_comic):
    config, _ = config
    cli = comictaggerlib.cli.CLI(config, {})

    result, _ = cli.process_file_cli(Action.gui, str(tmp_comic.path), OnlineMatchResults())

    assert result.action == Action.gui
    assert result.status == Status.read_failure
