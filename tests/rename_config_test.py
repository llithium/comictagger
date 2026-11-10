from __future__ import annotations

import pathlib
import shutil
from unittest.mock import Mock

import pytest

pytest.importorskip("PyQt6")

from PyQt6 import QtWidgets

from comicapi.comicarchive import ComicArchive
from comicapi.genericmetadata import GenericMetadata
from comictaggerlib.cli import CLI
from comictaggerlib.renamewindow import OptionalMessageDialog, RenameWindow
from comictaggerlib.resulttypes import Status
from comictaggerlib.settingswindow import SettingsWindow


def test_settings_gui_and_cli_preview_the_same_rename(config, tmp_path, tmp_comic, qtbot):
    settings = config.values
    settings.File_Rename__template = "{series} #{issue}"
    settings.File_Rename__issue_number_padding = 2
    settings.File_Rename__move = True
    settings.File_Rename__dir = str(tmp_path / "library")
    settings.Runtime_Options__tags_read = ["cr"]
    settings.Runtime_Options__dryrun = True
    original_path = tmp_comic.path
    metadata = GenericMetadata(series="Sample Comic", issue="3")
    assert tmp_comic.write_tags(metadata, "cr")

    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    preview = SettingsWindow(parent, config, {}, rename_example=lambda: (metadata, original_path.name))
    rename = RenameWindow(parent, [tmp_comic], ["cr"], config, {})
    expected = tmp_path / "library" / "Sample Comic #03.cbz"

    assert preview.rename_test_name == expected.name
    assert rename.twList.item(0, 0).text() == str(expected.parent)
    assert rename.twList.item(0, 2).text() == expected.name
    result = CLI(settings, {}).rename(tmp_comic)
    assert result.status == Status.success
    assert result.renamed_path == expected
    assert original_path.is_file()
    assert not expected.exists()

    rename.accept()
    assert expected.is_file()
    assert not original_path.exists()


def test_rename_target_lookup_failure_is_reported_without_stopping_other_archives(
    config, tmp_path, tmp_comic, qtbot, monkeypatch
):
    settings = config.values
    settings.File_Rename__template = "{series}"
    settings.File_Rename__move = True
    library = tmp_path / "library"
    settings.File_Rename__dir = str(library)
    settings.Runtime_Options__tags_read = ["cr"]
    second_path = tmp_path / "second.cbz"
    shutil.copyfile(tmp_comic.path, second_path)
    second = ComicArchive(second_path)
    assert tmp_comic.write_tags(GenericMetadata(series="Blocked"), "cr")
    assert second.write_tags(GenericMetadata(series="Allowed"), "cr")
    blocked_target = library / "Blocked.cbz"
    allowed_target = library / "Allowed.cbz"
    original_path = tmp_comic.path

    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    dialog = RenameWindow(parent, [tmp_comic, second], ["cr"], config, {})
    critical = Mock()
    monkeypatch.setattr(OptionalMessageDialog, "critical", critical)
    exists = pathlib.Path.exists

    def check_exists(path):
        if path == blocked_target:
            raise PermissionError("Cannot inspect rename destination")
        return exists(path)

    monkeypatch.setattr(pathlib.Path, "exists", check_exists)

    dialog.accept()

    assert original_path.is_file()
    assert allowed_target.is_file()
    assert not second_path.exists()
    message = critical.call_args.args[2]
    assert original_path.name in message
    assert blocked_target.name in message
    assert "Cannot inspect rename destination" in message
    assert CLI(settings, {}).rename(tmp_comic).status == Status.write_failure
