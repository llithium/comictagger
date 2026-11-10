from __future__ import annotations

from unittest.mock import Mock

import pytest

from comictaggerlib import ctversion
from comictalker.comiccacher import Series
from comictalker.talkers.comicvine import ComicVineTalker

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


def test_clear_cache_preserves_metadata_rebuilt_before_restart(config, qtbot, monkeypatch):
    from comictaggerlib.settingswindow import OptionalMessageDialog, SettingsWindow

    cache_dir = config.values.Runtime_Options__config.user_cache_dir
    talker = ComicVineTalker(ctversion.version, cache_dir)
    cache = talker.cacher()
    cache.add_series_info(talker.id, Series("old", b"{}"), complete=True)

    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    settings = SettingsWindow(parent, config, {})
    monkeypatch.setattr(OptionalMessageDialog, "information", Mock())
    settings.clear_cache()
    assert cache.get_series_info("old", talker.id) is None
    cache.add_series_info(talker.id, Series("rebuilt", b"{}"), complete=True)

    restarted = ComicVineTalker(ctversion.version, cache_dir).cacher()
    assert restarted.get_series_info("rebuilt", talker.id) is not None
