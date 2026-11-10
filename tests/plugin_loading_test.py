from __future__ import annotations

import importlib.metadata
import sys
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import comictalker
from comicapi import comicarchive
from comicapi.archivers import ZipArchiver
from comicapi.pluginloader import LocalPlugin
from comicapi.tags.comicrack import ComicRack
from comictaggerlib.ctsettings.plugin_finder import find_plugins
from comictalker import ComicTalker


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


def test_plugin_wheel_loads_healthy_entries_after_a_broken_entry(tmp_path, caplog):
    wheel = tmp_path / "test_tag_plugin-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("test_tag_plugin-1.0.dist-info/METADATA", "Name: test-tag-plugin\nVersion: 1.0\n")
        archive.writestr(
            "test_tag_plugin-1.0.dist-info/entry_points.txt",
            "[comicapi.tags]\nbroken = test_tag_plugin_missing:Bad\nhealthy = test_tag_plugin:Healthy\n",
        )
        archive.writestr("test_tag_plugin.py", "from comicapi.tags.comicrack import ComicRack as Healthy\n")

    plugins = find_plugins(tmp_path)

    assert [(tag.name, tag.implementation) for tag in plugins.tags] == [("healthy", ComicRack)]
    assert "Failed to load local plugin broken" in caplog.text
    assert str(wheel) not in sys.path
    assert "test_tag_plugin" not in sys.modules


def test_app_plugins_can_override_previously_loaded_defaults(monkeypatch):
    class LocalArchiver(ZipArchiver):
        pass

    class LocalTag(ComicRack):
        pass

    monkeypatch.setattr(comicarchive, "archivers", [ZipArchiver])
    monkeypatch.setattr(comicarchive, "tags", {"cr": ComicRack("previous")})

    comicarchive.load_archive_plugins([LocalArchiver])
    comicarchive.load_tag_plugins("app", [LocalTag])

    assert comicarchive.archivers[0] is LocalArchiver
    assert isinstance(comicarchive.tags["cr"], LocalTag)


@pytest.mark.parametrize("installed", [True, False], ids=["installed", "local-wheel"])
def test_talker_discovery_reads_the_instance_website(monkeypatch, tmp_path, installed):
    class PropertyTalker(ComicTalker):
        id = "property"

        @property
        def website(self):
            return "https://example.com"

    class ConfiguredTalker(ComicTalker):
        id = "configured"

        def __init__(self, version, cache_folder):
            super().__init__(version, cache_folder)
            self.website = "https://metron.example.com"

    classes = (PropertyTalker, ConfiguredTalker)
    local_plugins = []
    if installed:
        entries = [
            SimpleNamespace(name=talker.id, module="test_plugin", dist=None, load=Mock(return_value=talker))
            for talker in classes
        ]
        expected_location = "python module test_plugin"
    else:
        entries = []
        local_plugins = [LocalPlugin(talker.id, tmp_path / f"{talker.id}.whl", talker) for talker in classes]
        expected_location = f"Local package {tmp_path / 'configured.whl'}"
    monkeypatch.setattr(comictalker, "entry_points", lambda **kwargs: entries)

    talkers, metron_location = comictalker.get_talkers("test", tmp_path, local_plugins=local_plugins)

    assert list(talkers) == ["property"]
    assert metron_location == expected_location
