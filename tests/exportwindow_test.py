from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("PyQt6")

from comictaggerlib import taggerwindow
from comictaggerlib.exportwindow import ExportConfig, ExportConflictOpts


def test_export_dialog_is_ready_before_post_show_work(monkeypatch):
    dialog = Mock()
    create_dialog = Mock(return_value=dialog)
    monkeypatch.setattr(taggerwindow, "ExportWindow", create_dialog)

    class StopPostShow(BaseException):
        pass

    def update_tag_tweaks():
        assert window.export_window is dialog
        dialog.export.connect.assert_called_once_with(window._repackage_archive)
        raise StopPostShow

    window = SimpleNamespace(update_tag_tweaks=update_tag_tweaks, _repackage_archive=Mock())
    with pytest.raises(StopPostShow):
        taggerwindow.TaggerWindow._post_show(window, [])
    create_dialog.assert_called_once_with(window)


@pytest.mark.parametrize(
    ("conflict", "existing", "success", "expected_name"),
    [
        (ExportConflictOpts.DONT_CREATE, False, True, "comic.cbz"),
        (ExportConflictOpts.DONT_CREATE, True, True, None),
        (ExportConflictOpts.CREATE_UNIQUE, True, True, "comic (1).cbz"),
        (ExportConflictOpts.DONT_CREATE, False, False, "comic.cbz"),
    ],
)
def test_export_conflict_and_source_deletion(tmp_path, monkeypatch, conflict, existing, success, expected_name):
    source = tmp_path / "comic.cbr"
    source.write_bytes(b"source")
    destination = tmp_path / "comic.cbz"
    if existing:
        destination.write_bytes(b"existing")

    archive = SimpleNamespace(
        path=source, is_zip=lambda: False, get_number_of_pages=lambda: 1, export_as_zip=Mock(return_value=success)
    )
    selection = SimpleNamespace(
        get_selected_archive_list=lambda: [archive], remove_archive_list=Mock(), add_path_list=Mock()
    )
    window = SimpleNamespace(fileSelectionList=selection)
    monkeypatch.setattr(taggerwindow, "LogWindow", Mock())
    monkeypatch.setattr(taggerwindow.QtCore.QCoreApplication, "processEvents", Mock())

    taggerwindow.TaggerWindow._repackage_archive(window, ExportConfig(conflict, True, True))

    if expected_name is None:
        archive.export_as_zip.assert_not_called()
    else:
        archive.export_as_zip.assert_called_once_with(tmp_path / expected_name, overwrite=False)
    assert source.exists() is (expected_name is None or not success)
    selection.remove_archive_list.assert_called_once_with([archive] if expected_name and success else [])
    selection.add_path_list.assert_called_once_with(
        [str(tmp_path / expected_name)] if expected_name and success else []
    )
    if existing:
        assert destination.read_bytes() == b"existing"
