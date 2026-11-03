from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from comicapi.genericmetadata import GenericMetadata
from comictaggerlib.quick_tag import ID, Hashes, HashType, QuickTag


def hashes(issue_id, *distances):
    kinds = list(HashType)
    return Hashes(
        id=ID("example.com", issue_id),
        domain="example.com",
        hashes=[
            {
                "Hash": {"Hash": i, "Kind": kinds[i]},
                "ID": {"Domain": "example.com", "ID": issue_id},
                "Distance": distance,
                "EquivalentIDs": [],
            }
            for i, distance in enumerate(distances)
        ],
    )


def quick_tag(tmp_path, talker=None):
    config = SimpleNamespace(Runtime_Options__config=SimpleNamespace(user_cache_dir=tmp_path))
    tagger = QuickTag(None, "example.com", talker or Mock(name="talker"), config, Mock())
    tagger.limit = 30
    return tagger


@pytest.mark.parametrize(
    ("distances", "score", "exact"),
    [
        ((0,), 90, False),
        ((0, 0), 94, True),
        ((0, 1), 94, False),
        ((0, 0, 0), 100, True),
        ((3, 3, 3), 96, True),
        ((4, 4, 4), 94, False),
        ((5, 5, 5), 94, False),
    ],
)
def test_score_and_exact_boundaries(distances, score, exact):
    result = hashes("1", *distances)
    assert result.score == score
    assert result.exact is exact


def test_filters_reject_candidates_beyond_distance_gap(tmp_path):
    tagger = quick_tag(tmp_path)
    candidates = [hashes("1", 0), hashes("2", 3), hashes("3", 7), hashes("4", 8)]
    assert [r.id.ID for r in tagger._filter_hash_results(candidates)] == ["1", "2"]
    aggressive, normal = tagger._filter_hashes(candidates, True)
    assert [r.id.ID for r in normal] == ["1", "2"]
    assert [r.id.ID for r in aggressive] == ["1", "2"]


@pytest.mark.parametrize("aggressive_filtering", [False, True])
@pytest.mark.parametrize("distances", [((0, 3), (4, 7), (5, 0)), ((0, 3), (1, 9), (2, 0))])
def test_gap_does_not_discard_later_improved_hash_match(tmp_path, distances, aggressive_filtering):
    tagger = quick_tag(tmp_path)
    candidates = [hashes(str(i), *values) for i, values in enumerate(distances, 1)]

    selected, display = tagger.match_results(candidates, aggressive_filtering)

    assert [r.id.ID for r in selected] == ["1", "3"]
    assert [r.id.ID for r in display] == ["1", "3"]


def test_aggressive_filter_can_keep_improved_later_hash_group(tmp_path):
    tagger = quick_tag(tmp_path)
    candidates = [hashes("1", 0, 5, 9), hashes("2", 5, 9), hashes("3", 6, 0)]

    selected, display = tagger.match_results(candidates, True)

    assert [r.id.ID for r in selected] == ["1", "3"]
    assert [r.id.ID for r in display] == ["1", "2", "3"]


def test_aggressive_filter_is_stricter_than_normal(tmp_path):
    tagger = quick_tag(tmp_path)
    candidates = [hashes("1", 0, 0), hashes("2", 3)]
    aggressive, normal = tagger._filter_hashes(candidates, True)
    assert [r.id.ID for r in aggressive] == ["1"]
    assert [r.id.ID for r in normal] == ["1", "2"]


@pytest.mark.parametrize("first_match", [True, False])
def test_first_or_fallback_match_returns_id(tmp_path, first_match):
    tagger = quick_tag(tmp_path)
    first, fallback = hashes("1", 0), hashes("2", 1)
    tagger.check_matches = Mock(side_effect=[first] if first_match else [None, fallback])
    result = tagger.display_results([first], [first, fallback], Mock(), GenericMetadata(series="Series"), False, False)
    assert result == (first.id if first_match else fallback.id)
    assert tagger.check_matches.call_count == (1 if first_match else 2)


def test_learned_bad_ids_are_not_fetched_after_reload(tmp_path):
    talker = Mock()
    talker.name = "source"
    talker.fetch_comics.return_value = [GenericMetadata(issue_id="good", series="Series", issue="1")]
    bad, good = hashes("bad", 0), hashes("good", 1)
    tagger = quick_tag(tmp_path, talker)
    tagger.get_mds([bad.id, good.id])
    tagger.bad_ids.close()
    fresh = quick_tag(tmp_path, talker)
    talker.reset_mock()
    talker.name = "source"
    talker.fetch_comic_data.return_value = GenericMetadata(issue_id="good", series="Series", issue="1")
    assert fresh.check_matches([bad, good], GenericMetadata(series="Series", issue="1")) == good
    talker.fetch_comic_data.assert_called_once_with(issue_id="good", on_rate_limit=None)
    talker.fetch_comics.assert_not_called()


def test_menu_uses_retrieved_items_for_range_and_selection(tmp_path, monkeypatch):
    tagger = quick_tag(tmp_path)
    one, two, missing = hashes("1", 0), hashes("2", 1), hashes("3", 2)
    tagger.check_matches = Mock(return_value=None)
    tagger.get_mds = Mock(return_value=[GenericMetadata(issue_id="1"), GenericMetadata(issue_id="2")])
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "2")
    ca = Mock(path=SimpleNamespace(name="comic.cbz"))
    assert tagger.display_results([one], [one, two, missing], ca, GenericMetadata(), True, False) == two.id
    assert "[1-2]" in prompts[0]


def test_empty_menu_returns_without_prompt(tmp_path, monkeypatch):
    tagger = quick_tag(tmp_path)
    tagger.check_matches = Mock(return_value=None)
    tagger.get_mds = Mock(return_value=[])
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("unexpected prompt")))
    assert tagger.display_results([hashes("1", 0)], [hashes("1", 0)], Mock(), GenericMetadata(), True, False) is None


def test_bad_exact_candidate_does_not_hide_healthy_match(tmp_path):
    talker = Mock()
    talker.name = "source"
    talker.fetch_comic_data.return_value = GenericMetadata(issue_id="good", series="Series", issue="1")
    tagger = quick_tag(tmp_path, talker)
    bad, good = hashes("bad", 0, 0), hashes("good", 1)
    tagger.known_bad_ids[tagger.domain] = {bad.id}

    selected, display = tagger.match_results([bad, good], False)

    assert selected == [good]
    assert display == [good]
    assert (
        tagger.display_results(selected, display, Mock(), GenericMetadata(series="Series", issue="1"), False, False)
        == good.id
    )
    talker.fetch_comic_data.assert_called_once_with(issue_id="good", on_rate_limit=None)


def test_display_falls_back_when_selected_candidates_become_bad(tmp_path):
    talker = Mock()
    talker.name = "source"
    talker.fetch_comic_data.return_value = GenericMetadata(issue_id="good", series="Series", issue="1")
    tagger = quick_tag(tmp_path, talker)
    bad, good = hashes("bad", 0, 0), hashes("good", 1)
    tagger.known_bad_ids[tagger.domain] = {bad.id}

    assert (
        tagger.display_results([bad], [bad, good], Mock(), GenericMetadata(series="Series", issue="1"), False, False)
        == good.id
    )
    talker.fetch_comic_data.assert_called_once_with(issue_id="good", on_rate_limit=None)


def test_missing_single_fetch_is_recorded_and_not_offered_in_menu(tmp_path, monkeypatch):
    talker = Mock()
    talker.name = "source"
    talker.fetch_comic_data.return_value = GenericMetadata()
    tagger = quick_tag(tmp_path, talker)
    missing = hashes("missing", 0)
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("unexpected prompt")))

    assert tagger.display_results([missing], [missing], Mock(), GenericMetadata(series="Series"), True, False) is None
    assert missing.id in tagger.known_bad_ids[tagger.domain]
    assert missing.id in tagger.bad_ids.get_ids()[tagger.domain]
    talker.fetch_comic_data.assert_called_once_with(issue_id="missing", on_rate_limit=None)


def test_bulk_fetch_ignores_empty_and_unrequested_ids(tmp_path):
    talker = Mock()
    talker.name = "source"
    talker.fetch_comics.return_value = [
        GenericMetadata(),
        GenericMetadata(issue_id="other"),
        GenericMetadata(issue_id="good"),
    ]
    tagger = quick_tag(tmp_path, talker)
    good, missing = hashes("good", 0), hashes("missing", 1)

    assert [md.issue_id for md in tagger.get_mds([good.id, missing.id])] == ["good"]
    assert tagger.known_bad_ids[tagger.domain] == {missing.id}
