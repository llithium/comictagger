from __future__ import annotations

import importlib.metadata
from unittest.mock import Mock

import pytest

from comicapi import comicarchive
from comicapi.archivers import ZipArchiver
from comicapi.tags.comicrack import ComicRack


@pytest.mark.parametrize("group", ["comicapi.archiver", "comicapi.tags"])
def test_discovery_isolates_broken_entry_point(monkeypatch, caplog, group):
    broken = Mock(name="broken")
    broken.name = "broken"
    broken.module = "missing_plugin.parent"
    broken.load.side_effect = ModuleNotFoundError("missing_plugin")
    healthy = Mock(name="healthy")
    healthy.name = "healthy"
    healthy.module = "comicapi.archivers.zip" if group == "comicapi.archiver" else "comicapi.tags.comicrack"
    healthy.load.return_value = ZipArchiver if group == "comicapi.archiver" else ComicRack
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [broken, healthy])
    monkeypatch.setattr(comicarchive, "archivers", [])
    monkeypatch.setattr(comicarchive, "tags", {})

    if group == "comicapi.archiver":
        comicarchive.load_archive_plugins()
        assert comicarchive.archivers == [ZipArchiver]
    else:
        comicarchive.load_tag_plugins()
        assert isinstance(comicarchive.tags["cr"], ComicRack)
    assert "Failed to load" in caplog.text
    broken.load.assert_called_once()
    healthy.load.assert_called_once()
