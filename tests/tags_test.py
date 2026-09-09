from __future__ import annotations

import pytest
from importlib_metadata import entry_points

import comicapi.genericmetadata
import testing.comicdata
from comicapi.tags.comicrack import ComicRack
from comictaggerlib.md import prepare_metadata

tags = []

for x in entry_points(group="comicapi.tags"):
    tag = x.load()
    supported = tag.enabled
    exe_found = True
    tags.append(pytest.param(tag, marks=pytest.mark.xfail(not supported, reason="tags not enabled")))

if not tags:
    raise Exception("No tags found")


@pytest.mark.parametrize("tag_type", tags)
def test_metadata(mock_version, tmp_comic, md_saved, tag_type, md):
    tag = tag_type(mock_version[0])
    supported_attributes = tag.supported_attributes
    tag.write_tags(md, tmp_comic.archiver)
    written_metadata = tag.read_tags(tmp_comic.archiver)
    new_md = md_saved._get_clean_metadata(*supported_attributes)

    # Hack back in the pages variable because CoMet supports identifying the cover by the filename
    if tag.id == "comet":
        new_md.pages = [
            comicapi.genericmetadata.PageMetadata(
                archive_index=0,
                bookmark="",
                display_index=0,
                filename="!cover.jpg",
                type=comicapi.genericmetadata.PageType.FrontCover,
            )
        ]
        written_metadata = written_metadata._get_clean_metadata(*supported_attributes).replace(
            pages=written_metadata.pages
        )
    else:
        written_metadata = written_metadata._get_clean_metadata(*supported_attributes)

    assert written_metadata == new_md


def test_comicrack_persists_series_start_year(mock_version, tmp_comic):
    tag = ComicRack(mock_version[0])
    metadata = comicapi.genericmetadata.GenericMetadata(series_start_year=2024)

    assert tag.write_tags(metadata, tmp_comic.archiver)
    assert tag.read_tags(tmp_comic.archiver).series_start_year == 2024


@pytest.mark.parametrize("metadata, expected", testing.comicdata.metadata_prepared)
def test_prepare_metadata(mock_version, mock_now, config, metadata, expected):
    new_md = prepare_metadata(metadata[0], metadata[1], config[0])
    assert new_md == expected
