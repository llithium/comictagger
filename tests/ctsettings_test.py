from __future__ import annotations

import argparse
import json
import pathlib
from unittest.mock import Mock

import pytest
import settngs

import comictaggerlib.ctsettings.types
from comicapi import comicarchive, utils
from comicapi._metadata_example import example_metadata
from comicapi.archivers.rar import RarArchiver
from comictaggerlib import ctsettings
from comictaggerlib.ctsettings import ComicTaggerPaths, plugin
from comictaggerlib.ctsettings.types import parse_metadata_from_string
from comictaggerlib.main import App
from comictalker import ComicTalker

md_strings = (
    ("", example_metadata.replace()),
    ("year:", example_metadata.replace(year=None)),
    ("year: 2009", example_metadata.replace(year=2009)),
    ("series:", example_metadata.replace(series=None)),
    ("series_aliases:", example_metadata.replace(series_aliases=set())),
    ("black_and_white:", example_metadata.replace(black_and_white=None)),
    ("credits:", example_metadata.replace(credits=[])),
    ("story_arcs:", example_metadata.replace(story_arcs=[])),
)


@pytest.mark.parametrize("string,expected", md_strings)
def test_parse_metadata_from_string(string, expected, md):
    parsed_md = comictaggerlib.ctsettings.types.parse_metadata_from_string(string)

    md.overlay(parsed_md)

    assert md == expected


@pytest.mark.parametrize("source", ["year: [", "copy: value", "year: invalid"])
def test_invalid_metadata_is_an_argument_error(source, capsys):
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=parse_metadata_from_string)

    with pytest.raises(SystemExit) as error:
        parser.parse_args(["--metadata", source])

    assert error.value.code == 2
    assert "--metadata" in capsys.readouterr().err


def test_invalid_talker_settings_remove_only_the_failed_talker():
    talkers = {}
    manager = settngs.Manager()
    for name in ("broken", "healthy"):
        talker = Mock(spec=ComicTalker)
        talker.id = name
        talker.name = name
        talker.default_api_key = ""
        talker.default_api_url = ""
        talker.parse_settings.side_effect = ValueError("bad setting") if name == "broken" else lambda values: values
        talkers[name] = talker
    plugin.register_talker_settings(manager, talkers)
    values = manager.get_namespace(manager.defaults(), file=True, cmdline=True)

    plugin.validate_talker_settings(values, talkers)

    assert set(talkers) == {"healthy"}
    talkers["healthy"].parse_settings.assert_called_once()


def test_archive_executable_options_keep_the_declared_name(monkeypatch, tmp_path):
    class TestArchiver(comicarchive.Archiver):
        exe = "test-archiver"

        def __init__(self):
            raise AssertionError("An executable setting does not require opening an archiver")

    monkeypatch.setattr(comicarchive, "archivers", [TestArchiver])
    app = App()
    app.register_settings(False)
    paths = ComicTaggerPaths(tmp_path)

    app.parse_settings(paths, "--test_archiver", "bin/first")
    assert TestArchiver.exe == str(pathlib.Path("bin/first").absolute())

    paths.settings_file.write_text(json.dumps({"Archive": {"test_archiver": "bin/second"}}), encoding="utf-8")
    app.parse_settings(paths, "--config", str(tmp_path))
    assert TestArchiver.exe == str(pathlib.Path("bin/second").absolute())


def test_rar_plugins_can_declare_an_independent_executable(monkeypatch, tmp_path):
    class CustomRar(RarArchiver):
        exe = "custom-rar"

    class CustomRarVariant(CustomRar):
        pass

    monkeypatch.setattr(comicarchive, "archivers", [RarArchiver, CustomRar, CustomRarVariant])
    monkeypatch.setattr(RarArchiver, "exe", str(tmp_path / "previous-rar"))
    app = App()
    app.register_settings(False)
    bundled_path = tmp_path / "bundled-rar"
    custom_path = tmp_path / "custom-rar"

    app.parse_settings(ComicTaggerPaths(tmp_path), "--rar", str(bundled_path), "--custom_rar", str(custom_path))

    assert RarArchiver.exe == str(bundled_path)
    assert CustomRar.exe == CustomRarVariant.exe == str(custom_path)


def test_quick_tag_url_and_legacy_tag_ids_round_trip(tmp_path):
    paths = ComicTaggerPaths(tmp_path)
    paths.settings_file.write_text(json.dumps({"internal": {"read_tags": 0, "write_tags": "comet"}}), encoding="utf-8")
    url = "https://example.com:443/cover/search"
    args = ["--config", str(tmp_path), "-vv", "--enable-quick-tag"]
    bootstrap, _ = ctsettings.initial_commandline_parser().parse_known_intermixed_args(args)
    app = App()
    app.register_settings(bootstrap.enable_quick_tag)
    config = app.parse_settings(bootstrap.config, *args, "--url", url)

    assert config.values.Runtime_Options__verbose == bootstrap.verbose == 2
    assert config.values.internal__read_tags == ["cbi"]
    assert config.values.internal__write_tags == ["comet"]
    assert ctsettings.save_file(config, paths.settings_file)
    saved = json.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert saved["Quick Tag"]["url"] == url
    assert app.parse_settings(paths, *args).values.Quick_Tag__url == utils.parse_url(url)
