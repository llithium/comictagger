from __future__ import annotations

from importlib.metadata import entry_points

import pytest

import comicapi.genericmetadata
import testing.comicdata
from comicapi.tags.comicrack import ComicRack
from comictaggerlib.md import prepare_metadata

tags = []

for x in entry_points(group="comicapi.tags"):
    tag = x.load()
    supported = tag.enabled
    tags.append(pytest.param(tag, marks=pytest.mark.skipif(not supported, reason="tags not enabled")))

if not tags:
    raise Exception("No tags found")


def supported_metadata(metadata, supported_attributes):
    # Plugin capability names predate the current PageMetadata and URL fields.
    field_aliases = {
        "web_link": "web_links",
        "pages.image_index": "display_index",
        "pages.size": "byte_size",
    }
    result = {}
    for path in supported_attributes:
        field, _, member = path.partition(".")
        if member:
            result[path] = [getattr(item, field_aliases.get(path, member)) for item in getattr(metadata, field)]
        elif field not in ("pages", "credits"):
            result[path] = getattr(metadata, field_aliases.get(path, field))
    return result


@pytest.mark.parametrize("tag_type", tags)
def test_metadata(mock_version, tmp_comic, md_saved, tag_type, md):
    tag = tag_type(mock_version[0])

    assert tag.write_tags(md, tmp_comic.archiver)
    written_metadata = tag.read_tags(tmp_comic.archiver)
    if tag.id == "comet":
        # CoMet stores just the cover filename.
        md_saved.pages = [
            comicapi.genericmetadata.PageMetadata(
                archive_index=0,
                bookmark="",
                display_index=0,
                filename="!cover.jpg",
                type=comicapi.genericmetadata.PageType.FrontCover,
            )
        ]

    assert supported_metadata(written_metadata, tag.supported_attributes) == supported_metadata(
        md_saved, tag.supported_attributes
    )


def test_comicrack_preserves_unknown_xml_and_supports_credit_aliases(mock_version, tmp_comic):
    tag = ComicRack(mock_version[0])
    archive = tmp_comic.archiver
    original = '<?xml version="1.0" encoding="iso-8859-1"?><ComicInfo><Custom>café</Custom></ComicInfo>'
    assert archive.write_file("ComicInfo.xml", original.encode("iso-8859-1"))
    assert "<Custom>café</Custom>" in tag.read_raw_tags(archive)

    metadata = comicapi.genericmetadata.GenericMetadata()
    metadata.add_credit("Example Artist", "artist")
    assert tag.supports_credit_role("ARTIST")
    assert tag.write_tags(metadata, archive)

    assert "<Custom>café</Custom>" in tag.read_raw_tags(archive)
    assert {credit.role for credit in tag.read_tags(archive).credits} == {"Penciller", "Inker"}


def test_comicrack_persists_series_start_year(mock_version, tmp_comic):
    tag = ComicRack(mock_version[0])
    metadata = comicapi.genericmetadata.GenericMetadata(series_start_year=2024)

    assert tag.write_tags(metadata, tmp_comic.archiver)
    assert tag.read_tags(tmp_comic.archiver).series_start_year == 2024


@pytest.mark.parametrize("metadata, expected", testing.comicdata.metadata_prepared)
def test_prepare_metadata(mock_version, mock_now, config, metadata, expected):
    new_md = prepare_metadata(metadata[0], metadata[1], config[0])
    assert new_md == expected
