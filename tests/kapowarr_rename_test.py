from __future__ import annotations

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
        "The World's Finest - Batman-Superman (2025) Volume 01 Issue 007.cbz",
    )


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
        "Lady Mechanika - The Devil in the Lake (2024) Volume 01 Issue 001.cbz",
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


def test_kapowarr_volume_as_issue_uses_the_issue_number_without_padding() -> None:
    metadata = GenericMetadata(
        is_empty=False,
        publisher="Image",
        series="Saga",
        volume=1,
        issue="12",
        year=2026,
        format="Volume As Issue",
    )

    assert_renamed_name(rename(metadata), "Saga (2026) Volume 12.cbz")


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
