from __future__ import annotations

import shutil

import pytest

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from comictaggerlib.fileselectionlist import FileSelectionList
from testing.filenames import cbz_path


def test_moved_archive_refreshes_file_list_paths(tmp_path, config) -> None:
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_path = source_dir / cbz_path.name
    shutil.copy(cbz_path, source_path)

    file_list = FileSelectionList(None, config[0], lambda _title, _description: True)
    row, archive = file_list.add_path_item(str(source_path))
    file_list.twList.selectRow(row)
    destination = tmp_path / "library" / "renamed.cbz"
    archive.rename(destination)

    file_list.update_selected_rows()

    assert file_list.loaded_paths == {destination}
    assert file_list.get_current_archive().path == destination
    application.quit()
