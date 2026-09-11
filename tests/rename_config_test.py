from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from comicapi.genericmetadata import GenericMetadata
from comictaggerlib.cli import CLI
from comictaggerlib.filerenamer import FileRenamer, FileRenamerConfig
from comictaggerlib.renamewindow import RenameWindow
from comictaggerlib.settingswindow import SettingsWindow


class _Control:
    def __init__(self, value: object) -> None:
        self.value = value

    def text(self) -> str:
        return str(self.value)

    def isChecked(self) -> bool:
        return bool(self.value)


class _Archive:
    def __init__(self, path: pathlib.Path) -> None:
        self.path = path

    def extension(self) -> str:
        return self.path.suffix


def test_settings_preview_gui_and_cli_apply_the_same_rename_config(config, tmp_path, monkeypatch) -> None:
    settings = config[0]
    settings.File_Rename__template = "{series} #{issue}"
    settings.File_Rename__issue_number_padding = 2
    settings.File_Rename__use_smart_string_cleanup = False
    settings.File_Rename__move = True
    settings.File_Rename__only_move = True
    settings.File_Rename__strict_filenames = True
    settings.File_Rename__kapowarr_naming = False
    settings.File_Rename__kapowarr_long_special_versions = True
    settings.File_Rename__dir = str(tmp_path / "library")
    settings.File_Rename__auto_extension = False
    settings.Runtime_Options__dryrun = True

    applied: list[FileRenamerConfig] = []
    original_apply_config = FileRenamer.apply_config

    def capture_apply_config(renamer: FileRenamer, rename_config: FileRenamerConfig) -> None:
        applied.append(rename_config)
        original_apply_config(renamer, rename_config)

    monkeypatch.setattr(FileRenamer, "apply_config", capture_apply_config)

    preview = SimpleNamespace(
        leRenameTemplate=_Control(settings.File_Rename__template),
        leIssueNumPadding=_Control(settings.File_Rename__issue_number_padding),
        cbxSmartCleanup=_Control(settings.File_Rename__use_smart_string_cleanup),
        cbxMoveFiles=_Control(settings.File_Rename__move),
        cbxMoveOnly=_Control(settings.File_Rename__only_move),
        cbxRenameStrict=_Control(settings.File_Rename__strict_filenames),
        cbxKapowarrNaming=_Control(settings.File_Rename__kapowarr_naming),
        cbxKapowarrLongSpecialVersions=_Control(settings.File_Rename__kapowarr_long_special_versions),
        get_replacements=lambda: settings.File_Rename__replacements,
    )
    monkeypatch.setattr("comictaggerlib.gui.tagger_window", None)
    SettingsWindow._rename_test(preview, settings.File_Rename__template)

    archive = _Archive(tmp_path / "original.cbz")
    metadata = GenericMetadata(series="Cory Doctorow", issue="1")
    rename_preview = SimpleNamespace(
        config=(settings,),
        read_tag_ids=["cr"],
        renamer=FileRenamer(None),
    )
    RenameWindow.config_renamer(rename_preview, archive, metadata)

    cli = CLI(settings, {})
    cli.create_local_metadata = lambda comic, tag_ids: (metadata, list(tag_ids))
    cli.rename(archive)

    expected = FileRenamerConfig.from_settings(settings)
    assert applied == [expected, expected, expected]
