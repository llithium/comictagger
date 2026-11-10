from __future__ import annotations

from unittest.mock import Mock

import pytest

import comicapi.genericmetadata
import comictaggerlib.cli
from comictaggerlib.issueidentifier import IssueIdentifier
from comictaggerlib.issueidentifier import Result as IdentificationResult
from comictaggerlib.resulttypes import Action, MatchStatus, Result, Status


def test_export_reports_failed_archive_conversion(config, tmp_path):
    config, _ = config
    cli = comictaggerlib.cli.CLI(config, {})
    archive = Mock()
    archive.path = tmp_path / "book.cbr"
    archive.is_zip.return_value = False
    archive.export_as_new_zip.return_value = None

    result = cli.export(archive)

    assert result.action == Action.export
    assert result.status == Status.write_failure


def test_export_reports_the_actual_export_folder(config, tmp_path, capsys):
    config, _ = config
    cli = comictaggerlib.cli.CLI(config, {})
    archive = Mock()
    archive.path = tmp_path / "book.cbr"
    archive.is_zip.return_value = False
    exported_path = tmp_path / "ComicTagger-export-test" / "book.cbz"
    archive.export_as_new_zip.return_value = exported_path

    result = cli.export(archive)

    assert result.status == Status.success
    assert result.renamed_path == exported_path
    assert str(exported_path.relative_to(tmp_path)) in capsys.readouterr().out


def test_online_tag_assume_issue_one_forwards_query_metadata(config, cbz, monkeypatch):
    config, _ = config
    config.Auto_Tag__assume_issue_one = True
    config.Runtime_Options__enable_quick_tag = False
    talker = Mock()
    cli = comictaggerlib.cli.CLI(config, {config.Sources__source: talker})
    local_md = comicapi.genericmetadata.GenericMetadata(series="Example")
    captured: list[comicapi.genericmetadata.GenericMetadata] = []

    def identify(self, archive, metadata):
        captured.append(metadata)
        return IdentificationResult.no_matches, []

    monkeypatch.setattr(IssueIdentifier, "identify", identify)

    result = cli.online_tag(cbz, local_md, [])

    assert result.match_status == MatchStatus.no_match
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

    result = cli.save(tmp_comic)

    assert result.status == Status.fetch_data_failure
    assert not write_tags.called
    assert tmp_comic.read_tags("cr") == original


def test_unhandled_archive_action_reports_the_requested_action(config, tmp_comic):
    config, _ = config
    cli = comictaggerlib.cli.CLI(config, {})

    result = cli.process_file_cli(Action.gui, str(tmp_comic.path))

    assert result.action == Action.gui
    assert result.status == Status.read_failure


@pytest.mark.parametrize("dryrun", [False, True])
def test_rename_reports_selected_collision_destination(config, tmp_comic, monkeypatch, capsys, dryrun):
    config, _ = config
    config.File_Rename__template = "{series}"
    config.File_Rename__auto_extension = True
    config.Runtime_Options__dryrun = dryrun
    cli = comictaggerlib.cli.CLI(config, {})
    monkeypatch.setattr(
        cli, "create_local_metadata", lambda *args: (comicapi.genericmetadata.GenericMetadata(series="Collision"), [])
    )
    (tmp_comic.path.parent / "Collision.cbz").touch()
    original = tmp_comic.path

    result = cli.rename(tmp_comic)

    assert result.status == Status.success
    assert result.renamed_path != original
    assert result.renamed_path.name != "Collision.cbz"
    assert result.renamed_path.name in capsys.readouterr().out
    assert result.renamed_path.exists() is (not dryrun)
    assert original.exists() is dryrun


def test_fetched_metadata_is_transformed_once_on_preparation(config):
    from comictaggerlib.cbltransformer import CBLTransformer
    from comictaggerlib.md import prepare_metadata

    config, _ = config
    config.Metadata_Options__apply_transform_on_import = True
    config.Metadata_Options__copy_notes_to_comments = True
    talker = Mock()
    talker.fetch_comic_data.return_value = comicapi.genericmetadata.GenericMetadata(
        is_empty=False, description="Description", notes="Notes"
    )
    cli = comictaggerlib.cli.CLI(config, {config.Sources__source: talker})
    fetched = cli.fetch_metadata("1")
    assert fetched.description == "Description"
    result = prepare_metadata(comicapi.genericmetadata.GenericMetadata(), fetched, config)
    assert result.description == "Description\n\nNotes"
    transformed = CBLTransformer(fetched, config).apply()
    assert CBLTransformer(transformed, config).apply().description == transformed.description


def test_interactive_choice_prepares_fetched_metadata_once(config, tmp_comic, monkeypatch):
    from comicapi.genericmetadata import GenericMetadata
    from comictaggerlib.resulttypes import IssueResult, Score
    from testing.comicvine import comic_series_result

    config, _ = config
    config.Runtime_Options__interactive = True
    config.Metadata_Options__apply_transform_on_import = True
    config.Metadata_Options__copy_notes_to_comments = True
    talker = Mock()
    talker.fetch_comic_data.return_value = GenericMetadata(is_empty=False, description="Description", notes="Notes")
    cli = comictaggerlib.cli.CLI(config, {config.Sources__source: talker})
    monkeypatch.setattr("builtins.input", lambda _: "1")
    monkeypatch.setattr(cli, "create_local_metadata", lambda *args: (GenericMetadata(), []))
    written = Mock(return_value=(["cr"], None))
    monkeypatch.setattr(cli, "write_tags", written)
    match = IssueResult(Score(100, "", 0, "", 0), comic_series_result, GenericMetadata(issue_id="1"))
    result = Result(Action.save, Status.success, tmp_comic.path, online_results=[match])

    assert cli.display_match_set_for_choice("Choose", result)
    assert result.md.description == "Description\n\nNotes"
    assert written.call_args.args[1].description == "Description\n\nNotes"
