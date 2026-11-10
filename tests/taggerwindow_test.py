from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from comicapi.genericmetadata import GenericMetadata

QtCore = pytest.importorskip("PyQt6.QtCore")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


def test_copy_tags_keeps_cancel_available_during_the_last_archive(tmp_path, config, qtbot, monkeypatch):
    from comictaggerlib import taggerwindow

    progress = QtWidgets.QProgressDialog("", "Cancel", 0, 1)
    qtbot.addWidget(progress)
    monkeypatch.setattr(taggerwindow.QtWidgets, "QProgressDialog", Mock(return_value=progress))
    monkeypatch.setattr(taggerwindow, "center_window_on_parent", lambda dialog: dialog.show())
    monkeypatch.setattr(taggerwindow, "LogWindow", Mock())
    monkeypatch.setattr(
        taggerwindow, "read_configured_tags", Mock(return_value=(GenericMetadata(series="Test"), [], None))
    )
    window = SimpleNamespace(config=config, _reload_page=Mock(), update_info_box=Mock(), update_menus=Mock())

    def write_tag(metadata, tag_id):
        assert progress.isVisible()
        assert progress.value() < progress.maximum()
        QtCore.QTimer.singleShot(0, progress.findChild(QtWidgets.QPushButton).click)
        return True

    archive = SimpleNamespace(
        path=tmp_path / "comic.cbz", write_tags=Mock(side_effect=write_tag), reset_cache=Mock(), load_cache=Mock()
    )

    taggerwindow.TaggerWindow.copy_tags(window, ["cr"], ["comet", "cbi"], [archive])

    assert [call.args[1] for call in archive.write_tags.call_args_list] == ["comet"]
    assert not progress.isVisible()
