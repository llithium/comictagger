from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6 import QtWidgets

from comicapi.genericmetadata import GenericMetadata
from comictaggerlib.cli import CLI
from comictaggerlib.renamewindow import RenameWindow
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
