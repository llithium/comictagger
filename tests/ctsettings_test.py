from __future__ import annotations

import argparse
from unittest.mock import Mock

import pytest
import settngs

import comicapi.genericmetadata
import comictaggerlib.ctsettings.types
from comictaggerlib.ctsettings import plugin
from comictaggerlib.ctsettings.types import parse_metadata_from_string
from comictalker import ComicTalker

md_strings = (
    ("", comicapi.genericmetadata.md_test.replace()),
    ("year:", comicapi.genericmetadata.md_test.replace(year=None)),
    ("year: 2009", comicapi.genericmetadata.md_test.replace(year=2009)),
    ("series:", comicapi.genericmetadata.md_test.replace(series=None)),
    ("series_aliases:", comicapi.genericmetadata.md_test.replace(series_aliases=set())),
    ("black_and_white:", comicapi.genericmetadata.md_test.replace(black_and_white=None)),
    ("credits:", comicapi.genericmetadata.md_test.replace(credits=[])),
    ("story_arcs:", comicapi.genericmetadata.md_test.replace(story_arcs=[])),
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
