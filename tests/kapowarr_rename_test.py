from __future__ import annotations

import datetime
import pathlib

import pytest

from comicapi.genericmetadata import GenericMetadata
from comictaggerlib.filerenamer import FileRenamer


def rename(metadata: GenericMetadata, *, long_special_versions: bool = False) -> str:
    renamer = FileRenamer(metadata, platform="universal")
    renamer.set_metadata(metadata, "original.cbz")
    renamer.set_kapowarr_naming(enabled=True, long_special_versions=long_special_versions)
    return renamer.determine_name(".cbz")


def assert_renamed_name(actual: str, expected: str) -> None:
    assert pathlib.PureWindowsPath(actual) == pathlib.PureWindowsPath(expected)


def test_kapowarr_regular_issue_uses_the_configured_filename() -> None:
    metadata = GenericMetadata(
        is_empty=False,
        publisher="DC Comics",
        series="The World's Finest: Batman/Superman",
        volume=1,
        issue="7",
        title="A title that is deliberately not in the default template",
        year=2025,
        format="Series",
    )

    assert_renamed_name(
        rename(metadata),
        "The World's Finest BatmanSuperman (2025) Volume 01 Issue 007.cbz",
    )


def test_kapowarr_uses_its_simple_filename_cleaner() -> None:
    metadata = GenericMetadata(
        is_empty=False,
        series='The:  World/"s?  Finest. ',
        issue="7",
        year=2025,
        format="Series",
    )

    assert FileRenamer._kapowarr_clean_filestring(metadata.series) == "The Worlds Finest"
    assert_renamed_name(rename(metadata), "The Worlds Finest (2025) Volume 01 Issue 007.cbz")


def test_kapowarr_regular_issue_defaults_an_untagged_series_to_volume_one() -> None:
    metadata = GenericMetadata(
        is_empty=False,
        publisher="Image",
        series="Lady Mechanika: The Devil in the Lake",
        issue="1",
        year=2024,
        format="Series",
    )

    assert_renamed_name(
        rename(metadata),
        "Lady Mechanika The Devil in the Lake (2024) Volume 01 Issue 001.cbz",
    )


@pytest.mark.parametrize(
    ("issue", "expected_issue"),
    [
        ("1.1", "1.1"),
        ("1A", "01A"),
        ("-1", "-01"),
        ("AU", "0AU"),
        ("12.5", "12.5"),
    ],
)
def test_kapowarr_pads_the_raw_issue_identifier(issue: str, expected_issue: str) -> None:
    metadata = GenericMetadata(
        is_empty=False,
        series="Numbered Series",
        issue=issue,
        year=2025,
        format="Series",
    )

    assert_renamed_name(rename(metadata), f"Numbered Series (2025) Volume 01 Issue {expected_issue}.cbz")


def test_kapowarr_uses_the_persisted_series_start_year() -> None:
    metadata = GenericMetadata(
        is_empty=False,
        series="Lady Mechanika: The Devil in the Lake",
        issue="3",
        year=2025,
        series_start_year=2024,
        format="Series",
    )

    assert_renamed_name(
        rename(metadata),
        "Lady Mechanika The Devil in the Lake (2024) Volume 01 Issue 003.cbz",
    )


def test_kapowarr_special_versions_use_their_own_template() -> None:
    metadata = GenericMetadata(
        is_empty=False,
        publisher="Marvel",
        series="Moon Knight",
        volume=2,
        year=2024,
        format="Hardcover",
    )

    assert_renamed_name(rename(metadata), "Moon Knight (2024) Volume 02 HC.cbz")
    assert_renamed_name(
        rename(metadata, long_special_versions=True),
        "Moon Knight (2024) Volume 02 Hard-Cover.cbz",
    )


def test_kapowarr_inferrs_spider_man_blue_hardcover_from_the_embedded_title() -> None:
    # This is the archive shown in the Kapowarr comparison: Comic Vine's
    # single issue is called "HC/TPB", while Kapowarr classifies the volume as
    # a hard-cover and uses its special-version template.
    metadata = GenericMetadata(
        is_empty=False,
        series="Spider-Man: Blue",
        issue="1",
        issue_count=1,
        title="HC/TPB",
        year=2004,
    )

    assert_renamed_name(rename(metadata), "Spider-Man Blue (2004) Volume 01 HC.cbz")


@pytest.mark.parametrize(
    ("format_value", "expected_special_version"),
    [
        ("Trade Paper Back", "TPB"),
        ("1 Shot", "OS"),
        ("One-Shot", "OS"),
        ("Hard-Cover", "HC"),
        ("Omnibus", "Omnibus"),
    ],
)
def test_kapowarr_recognizes_comicinfo_special_version_aliases(
    format_value: str, expected_special_version: str
) -> None:
    metadata = GenericMetadata(
        is_empty=False,
        series="Collected Edition",
        issue="1",
        year=2024,
        format=format_value,
    )

    assert_renamed_name(
        rename(metadata),
        f"Collected Edition (2024) Volume 01 {expected_special_version}.cbz",
    )


def test_kapowarr_keeps_an_explicit_normal_format_as_an_issue() -> None:
    metadata = GenericMetadata(
        is_empty=False,
        series="Annual Series",
        issue="1",
        issue_count=1,
        title="HC/TPB",
        year=2024,
        format="Annual",
    )

    assert_renamed_name(rename(metadata), "Annual Series (2024) Volume 01 Issue 001.cbz")


def test_kapowarr_infers_one_issue_special_versions_from_volume_metadata() -> None:
    metadata = GenericMetadata(
        is_empty=False,
        series="The Infinity Gauntlet Omnibus",
        issue="1",
        issue_count=1,
        year=2024,
    )

    assert_renamed_name(rename(metadata), "The Infinity Gauntlet Omnibus (2024) Volume 01 Omnibus.cbz")

    metadata.series = "Collected Edition"
    metadata.description = "A hard-cover collection of the complete miniseries."

    assert_renamed_name(rename(metadata), "Collected Edition (2024) Volume 01 Issue 001.cbz")

    metadata.description = "A hard-cover edition of the complete miniseries."

    assert_renamed_name(rename(metadata), "Collected Edition (2024) Volume 01 HC.cbz")


def test_kapowarr_infers_an_old_single_issue_as_a_trade_paperback() -> None:
    release_date = datetime.date.today() - datetime.timedelta(days=31)
    metadata = GenericMetadata(
        is_empty=False,
        series="Collected Edition",
        issue="1",
        issue_count=1,
        year=release_date.year,
        month=release_date.month,
        day=release_date.day,
    )

    assert_renamed_name(rename(metadata), f"Collected Edition ({release_date.year}) Volume 01 TPB.cbz")


def test_kapowarr_treats_a_thirty_day_old_single_issue_as_a_trade_paperback() -> None:
    release_date = datetime.date.today() - datetime.timedelta(days=30)
    metadata = GenericMetadata(
        is_empty=False,
        series="New Series",
        issue="1",
        issue_count=1,
        year=release_date.year,
        month=release_date.month,
        day=release_date.day,
    )

    assert_renamed_name(rename(metadata), f"New Series ({release_date.year}) Volume 01 TPB.cbz")


def test_kapowarr_volume_as_issue_uses_the_padded_issue_number() -> None:
    metadata = GenericMetadata(
        is_empty=False,
        publisher="Image",
        series="Saga",
        volume=1,
        issue="12",
        year=2026,
        format="Volume As Issue",
    )

    assert_renamed_name(rename(metadata), "Saga (2026) Volume 012.cbz")


def test_kapowarr_infers_volume_as_issue_and_uses_its_filename_cleaning() -> None:
    metadata = GenericMetadata(
        is_empty=False,
        series="X-Treme X-Men: Prisoner of Fire",
        issue="1",
        title="Volume 8",
        volume=8,
        year=2004,
    )

    assert_renamed_name(
        rename(metadata),
        "X-Treme X-Men Prisoner of Fire (2004) Volume 001.cbz",
    )


def test_kapowarr_template_aliases_are_available_without_enabling_the_profile() -> None:
    metadata = GenericMetadata(is_empty=False, series="The Question", volume=3, issue="5", title="Riddles", year=1987)
    renamer = FileRenamer(metadata, platform="universal")
    renamer.set_metadata(metadata, "original.cbz")
    renamer.move = True
    renamer.set_template(
        "{clean_series_name}/Volume {volume_number} ({year})/{series_name} {issue_number} {issue_title}"
    )

    assert_renamed_name(renamer.determine_name(".cbz"), "Question, The/Volume 03 (1987)/The Question 005 Riddles.cbz")


def test_kapowarr_profile_rejects_only_move_to_avoid_an_unexpected_layout() -> None:
    renamer = FileRenamer(GenericMetadata(is_empty=False, series="Saga"), platform="universal")
    renamer.move_only = True
    renamer.set_kapowarr_naming(enabled=True)

    with pytest.raises(ValueError, match="cannot be combined with Only Move"):
        renamer.determine_name(".cbz")
