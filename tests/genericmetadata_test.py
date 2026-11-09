from __future__ import annotations

import textwrap

import pytest

import comicapi.genericmetadata
import comicapi.merge
import testing.comicdata


def test_apply_default_page_list_creates_pages_and_marks_the_cover():
    metadata = comicapi.genericmetadata.GenericMetadata()

    metadata.apply_default_page_list(["cover.jpg", "page.jpg"])

    assert [page.filename for page in metadata.pages] == ["cover.jpg", "page.jpg"]
    assert metadata.get_cover_page_index_list() == [0]
    assert metadata.get_archive_page_index(1) == 1


def test_default_cover_uses_first_displayed_page_with_sparse_indexes():
    page = comicapi.genericmetadata.PageMetadata("page.jpg", "", "", display_index=0, archive_index=7)
    metadata = comicapi.genericmetadata.GenericMetadata(pages=[page])

    metadata.apply_default_page_list([])

    assert metadata.get_cover_page_index_list() == [7]
    assert metadata.pages[0].type == comicapi.genericmetadata.PageType.FrontCover


def test_overlay_can_clear_pages_and_preserves_independent_metadata():
    page = comicapi.genericmetadata.PageMetadata("page.jpg", "", "", display_index=0, archive_index=0)
    original = comicapi.genericmetadata.GenericMetadata(pages=[page], tags={"source"})
    edited = comicapi.genericmetadata.GenericMetadata()

    edited.overlay(original)
    edited.tags.add("edited")
    edited.pages[0].filename = "edited.jpg"
    assert original.tags == {"source"}
    assert original.pages[0].filename == "page.jpg"

    edited.overlay(comicapi.genericmetadata.GenericMetadata(pages=comicapi.genericmetadata.REMOVE))
    assert edited.pages == []


@pytest.mark.parametrize("md, new, expected", testing.comicdata.metadata)
def test_metadata_overlay(md, new, expected):
    md.overlay(new, comicapi.merge.Mode.OVERLAY)

    assert md == expected


@pytest.mark.parametrize("md, new, expected", testing.comicdata.metadata_add)
def test_metadata_overlay_add_missing(md, new, expected):
    md.overlay(new, comicapi.merge.Mode.ADD_MISSING, True)
    assert md == expected


@pytest.mark.parametrize("md, new, expected", testing.comicdata.metadata_combine)
def test_metadata_overlay_combine(md, new, expected):
    md.overlay(new, comicapi.merge.Mode.OVERLAY, True)
    assert md == expected


def test_add_credit():
    md = comicapi.genericmetadata.GenericMetadata()

    md.add_credit(person="test", role="writer", primary=False)
    assert md.credits == [comicapi.genericmetadata.Credit(person="test", role="writer", primary=False)]


def test_add_credit_primary():
    md = comicapi.genericmetadata.GenericMetadata()

    md.add_credit(person="test", role="writer", primary=False)
    md.add_credit(person="test", role="writer", primary=True)
    assert md.credits == [comicapi.genericmetadata.Credit(person="test", role="writer", primary=True)]


@pytest.mark.parametrize("md, role, expected", testing.comicdata.credits)
def test_get_primary_credit(md, role, expected):
    assert md.get_primary_credit(role) == expected


def test_str(md):
    expected = textwrap.dedent("""\
        data_origin:      Comic Vine
        series:           Cory Doctorow's Futuristic Tales of the Here and Now
        issue:            1
        issue_count:      6
        title:            Anda's Game
        publisher:        IDW Publishing
        year:             2007
        month:            10
        day:              1
        volume:           1
        genres:           Sci-Fi
        language:         en
        critical_rating:  3.0
        alternate_series: Tales
        alternate_number: 2
        alternate_count:  7
        imprint:          craphound.com
        web_links:        ['https://comicvine.gamespot.com/cory-doctorows-futuristic-tales-of-the-here-and-no/4000-140529/']
        format:           Series
        manga:            No
        maturity_rating:  Everyone 10+
        story_arcs:       ['Here and Now']
        series_groups:    ['Futuristic Tales']
        scan_info:        (CC BY-NC-SA 3.0)
        characters:       Anda
        teams:            Fahrenheit
        locations:        lonely  cottage
        description:      For 12-year-old Anda, getting paid real money to kill the characters of players who were cheating in her favorite online computer game was a win-win situation. Until she found out who was paying her, and what those characters meant to the livelihood of children around the world.
        notes:            Tagged with ComicTagger 1.3.2a5 using info from Comic Vine on 2022-04-16 15:52:26. [Issue ID 140529]
        credit:           Writer: Dara Naraghi
        credit:           Penciller: Esteve Polls
        credit:           Inker: Esteve Polls
        credit:           Letterer: Neil Uyetake
        credit:           Cover: Sam Kieth
        credit:           Editor: Ted Adams
    """)

    assert str(md) == expected
