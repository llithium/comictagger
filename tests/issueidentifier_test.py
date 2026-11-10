from __future__ import annotations

import io
from unittest.mock import Mock

import pytest
from PIL import Image

import comicapi.genericmetadata
import comicapi.utils
import comictaggerlib.imagehasher
import comictaggerlib.issueidentifier
import comictaggerlib.resulttypes
import testing.comicdata
import testing.comicvine


def test_crop(cbz_double_cover, config, tmp_path, comicvine_api):
    config, definitions = config
    iio = comictaggerlib.issueidentifier.IssueIdentifierOptions(
        series_match_search_thresh=config.Issue_Identifier__series_match_search_thresh,
        series_match_identify_thresh=config.Issue_Identifier__series_match_identify_thresh,
        use_publisher_filter=config.Auto_Tag__use_publisher_filter,
        publisher_filter=config.Auto_Tag__publisher_filter,
        quiet=config.Runtime_Options__quiet,
        cache_dir=config.Runtime_Options__config.user_cache_dir,
        border_crop_percent=config.Issue_Identifier__border_crop_percent,
        talker=comicvine_api,
        tpb_detection=config.Issue_Identifier__tpb_detection,
    )
    ii = comictaggerlib.issueidentifier.IssueIdentifier(iio, None)

    im = Image.open(io.BytesIO(cbz_double_cover.archiver.read_file("double_cover.jpg")))

    cropped = ii._crop_double_page(im)
    original = cbz_double_cover.get_page(0)

    original_hash = comictaggerlib.imagehasher.ImageHasher(data=original).average_hash()
    cropped_hash = comictaggerlib.imagehasher.ImageHasher(image=cropped).average_hash()

    assert original_hash == cropped_hash


@pytest.mark.parametrize("data, expected", testing.comicdata.issueidentifier_score)
def test_get_issue_cover_match_score(cbz, identifier, data, expected):
    def fetch_hash(url, kind):
        return identifier.calculate_hash(
            comictaggerlib.issueidentifier.ImageFetcher(identifier.config.cache_dir).fetch(url), kind=kind
        )

    score = identifier._get_issue_cover_match_score(
        data[0],
        data[1],
        lambda kind: [("Cover 1", identifier.calculate_hash(cbz.get_page(0), kind=kind))],
        fetch_hash,
    )
    assert expected == score


def test_search(cbz, config, comicvine_api):
    config, definitions = config
    iio = comictaggerlib.issueidentifier.IssueIdentifierOptions(
        series_match_search_thresh=config.Issue_Identifier__series_match_search_thresh,
        series_match_identify_thresh=config.Issue_Identifier__series_match_identify_thresh,
        use_publisher_filter=config.Auto_Tag__use_publisher_filter,
        publisher_filter=config.Auto_Tag__publisher_filter,
        quiet=config.Runtime_Options__quiet,
        cache_dir=config.Runtime_Options__config.user_cache_dir,
        border_crop_percent=config.Issue_Identifier__border_crop_percent,
        talker=comicvine_api,
        tpb_detection=config.Issue_Identifier__tpb_detection,
    )
    ii = comictaggerlib.issueidentifier.IssueIdentifier(iio, None)
    result, issues = ii.identify(cbz, cbz.read_tags("cr"))
    cv_expected = comictaggerlib.resulttypes.IssueResult(
        score=comictaggerlib.resulttypes.Score(
            score=0,
            url=testing.comicvine.cv_issue_result["results"]["image"]["super_url"],
            remote_hash=212201432349720,
            local_hash_name="0",
            local_hash=212201432349720,
        ),
        series=comicapi.genericmetadata.ComicSeries(
            id=str(testing.comicvine.cv_volume_result["results"]["id"]),
            name=testing.comicvine.cv_volume_result["results"]["name"],
            count_of_issues=testing.comicvine.cv_volume_result["results"]["count_of_issues"],
            publisher=testing.comicvine.cv_volume_result["results"]["publisher"]["name"],
            start_year=int(testing.comicvine.cv_volume_result["results"]["start_year"]),
            description=testing.comicvine.cv_volume_result["results"]["description"],
            aliases=set(),
            count_of_volumes=None,
            image_url=testing.comicvine.cv_volume_result["results"]["image"]["super_url"],
            format=None,
            web_links=[comicapi.utils.parse_url(testing.comicvine.cv_volume_result["results"]["site_detail_url"])],
        ),
        md=comicapi.genericmetadata.GenericMetadata(
            day=testing.comicvine.date[0],
            month=testing.comicvine.date[1],
            year=testing.comicvine.date[2],
            issue=testing.comicvine.cv_issue_result["results"]["issue_number"],
            issue_id=str(testing.comicvine.cv_issue_result["results"]["id"]),
            series_id=str(testing.comicvine.cv_volume_result["results"]["id"]),
            series_start_year=int(testing.comicvine.cv_volume_result["results"]["start_year"]),
            series=str(testing.comicvine.cv_volume_result["results"]["name"]),
            issue_count=testing.comicvine.cv_volume_result["results"]["count_of_issues"],
            publisher=str(testing.comicvine.cv_volume_result["results"]["publisher"]["name"]),
            title=testing.comicvine.cv_issue_result["results"]["name"],
            data_origin=comicapi.genericmetadata.MetadataOrigin(name="Comic Vine", id="comicvine"),
            description=testing.comicvine.cv_issue_result["results"]["description"],
            web_links=[comicapi.utils.parse_url(testing.comicvine.cv_issue_result["results"]["site_detail_url"])],
            _cover_image=comicapi.genericmetadata.ImageHash(
                Hash=0, Kind="", URL=testing.comicvine.cv_issue_result["results"]["image"]["super_url"]
            ),
        ),
    )
    assert result == comictaggerlib.issueidentifier.Result.single_good_match
    assert issues == [cv_expected]


def test_search_network_failure_is_not_reported_as_no_match(cbz, config, comicvine_api, monkeypatch):
    config, definitions = config
    iio = comictaggerlib.issueidentifier.IssueIdentifierOptions(
        series_match_search_thresh=config.Issue_Identifier__series_match_search_thresh,
        series_match_identify_thresh=config.Issue_Identifier__series_match_identify_thresh,
        use_publisher_filter=config.Auto_Tag__use_publisher_filter,
        publisher_filter=config.Auto_Tag__publisher_filter,
        quiet=config.Runtime_Options__quiet,
        cache_dir=config.Runtime_Options__config.user_cache_dir,
        border_crop_percent=config.Issue_Identifier__border_crop_percent,
        talker=comicvine_api,
        tpb_detection=config.Issue_Identifier__tpb_detection,
    )
    identifier = comictaggerlib.issueidentifier.IssueIdentifier(iio, None)
    monkeypatch.setattr(
        identifier,
        "_search_for_issues",
        lambda terms: (_ for _ in ()).throw(comictaggerlib.issueidentifier.IssueIdentifierNetworkError()),
    )

    result, matches = identifier.identify(cbz, cbz.read_tags("cr"))

    assert result == comictaggerlib.issueidentifier.Result.fetch_data_failure
    assert matches == []


def test_crop_border(cbz, config, comicvine_api):
    config, definitions = config
    iio = comictaggerlib.issueidentifier.IssueIdentifierOptions(
        series_match_search_thresh=config.Issue_Identifier__series_match_search_thresh,
        series_match_identify_thresh=config.Issue_Identifier__series_match_identify_thresh,
        use_publisher_filter=config.Auto_Tag__use_publisher_filter,
        publisher_filter=config.Auto_Tag__publisher_filter,
        quiet=config.Runtime_Options__quiet,
        cache_dir=config.Runtime_Options__config.user_cache_dir,
        border_crop_percent=config.Issue_Identifier__border_crop_percent,
        talker=comicvine_api,
        tpb_detection=config.Issue_Identifier__tpb_detection,
    )
    ii = comictaggerlib.issueidentifier.IssueIdentifier(iio, None)

    # This creates a white square centered on a black background
    bg = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
    fg = Image.new("RGBA", (50, 50), (255, 255, 255, 255))
    bg.paste(fg, (bg.width // 2 - (fg.width // 2), bg.height // 2 - (fg.height // 2)))

    cropped = ii._crop_border(bg, 49)

    assert cropped
    assert cropped.width == fg.width
    assert cropped.height == fg.height
    assert list(cropped.get_flattened_data()) == list(fg.get_flattened_data())


@pytest.fixture
def identifier(config, comicvine_api):
    config, _ = config
    return comictaggerlib.issueidentifier.IssueIdentifier(
        comictaggerlib.issueidentifier.IssueIdentifierOptions(
            series_match_search_thresh=config.Issue_Identifier__series_match_search_thresh,
            series_match_identify_thresh=config.Issue_Identifier__series_match_identify_thresh,
            use_publisher_filter=config.Auto_Tag__use_publisher_filter,
            publisher_filter=config.Auto_Tag__publisher_filter,
            quiet=config.Runtime_Options__quiet,
            cache_dir=config.Runtime_Options__config.user_cache_dir,
            border_crop_percent=config.Issue_Identifier__border_crop_percent,
            talker=comicvine_api,
            tpb_detection=config.Issue_Identifier__tpb_detection,
        ),
        None,
    )


def test_good_match_does_not_load_alternate_pages(identifier, cbz, monkeypatch):
    extra = Mock(side_effect=AssertionError("Alternate pages should remain unread"))
    monkeypatch.setattr(identifier, "_get_extra_images", extra)
    result, matches = identifier.identify(cbz, cbz.read_tags("cr"))
    assert result == comictaggerlib.issueidentifier.Result.single_good_match
    assert matches
    extra.assert_not_called()


def test_fallback_reuses_hashes_and_loads_extra_pages_once(identifier, cbz, monkeypatch):
    calculate_hash = Mock(side_effect=[0, (1 << 64) - 1])
    monkeypatch.setattr(identifier, "calculate_hash", calculate_hash)
    image = Image.new("L", (32, 32))
    extra = Mock(return_value=[("extra", image)])
    issue = comicapi.genericmetadata.GenericMetadata(
        issue="1", _cover_image=comicapi.genericmetadata.ImageHash(URL="", Kind="ahash", Hash=(1 << 64) - 1)
    )
    series = comicapi.genericmetadata.ComicSeries(
        id="test",
        name="Test",
        aliases=set(),
        count_of_issues=1,
        count_of_volumes=None,
        description="",
        image_url="",
        publisher="",
        start_year=None,
        format=None,
    )
    matches, _ = identifier._cover_matching([("cover", image)], extra, [(series, issue)])
    assert calculate_hash.call_count == 2
    extra.assert_called_once_with()
    assert matches[0].distance == 0
    assert matches[0].score.local_hash_name == "extra"


def candidate(id, cover):
    series = comicapi.genericmetadata.ComicSeries(
        id=id,
        name="Test",
        aliases=set(),
        count_of_issues=1,
        count_of_volumes=None,
        description="",
        image_url="",
        publisher="",
        start_year=None,
        format=None,
    )
    issue = comicapi.genericmetadata.GenericMetadata(issue_id=id, issue="1", _cover_image=cover)
    return series, issue


def test_matching_respects_candidate_hash_kind(identifier, cbz, monkeypatch):
    hasher = comictaggerlib.imagehasher.ImageHasher(data=cbz.get_page(0))
    wrong_ahash = hasher.average_hash() ^ ((1 << 64) - 1)
    matching_phash = hasher.perception_hash()
    candidates = [
        candidate("unrelated", comicapi.genericmetadata.ImageHash(Hash=wrong_ahash, Kind="ahash", URL="")),
        candidate("matching", comicapi.genericmetadata.ImageHash(Hash=matching_phash, Kind="phash", URL="")),
    ]
    monkeypatch.setattr(identifier, "_search_for_issues", lambda terms: candidates)

    result, matches = identifier.identify(cbz, cbz.read_tags("cr"))

    assert result == comictaggerlib.issueidentifier.Result.single_good_match
    assert [match.md.issue_id for match in matches] == ["matching"]
    assert matches[0].distance == 0


@pytest.mark.parametrize("remote_first", [True, False], ids=["download-first", "hash-first"])
def test_alternate_cover_order_preserves_exact_match_and_keeps_close_candidates(
    identifier, cbz, monkeypatch, remote_first
):
    primary = comicapi.genericmetadata.ImageHash(Hash=(1 << 64) - 1, Kind="ahash", URL="")
    best_series, best_issue = candidate("exact", primary)
    close_series, close_issue = candidate("close", primary)
    remote_url = "https://example.com/alternate.png"
    downloaded = comicapi.genericmetadata.ImageHash(Hash=0, Kind="", URL=remote_url)
    exact = comicapi.genericmetadata.ImageHash(Hash=0, Kind="ahash", URL="")
    best_issue._alternate_images = [downloaded, exact] if remote_first else [exact, downloaded]
    close_issue._alternate_images = [comicapi.genericmetadata.ImageHash(Hash=0b111, Kind="ahash", URL="")]
    monkeypatch.setattr(
        identifier, "_search_for_issues", lambda terms: [(best_series, best_issue), (close_series, close_issue)]
    )
    monkeypatch.setattr(comictaggerlib.issueidentifier.ImageFetcher, "fetch", Mock(return_value=b"downloaded"))
    monkeypatch.setattr(identifier, "calculate_hash", lambda data=b"", **kwargs: 0xFF if data else 0)

    result, matches = identifier.identify(cbz, cbz.read_tags("cr"))

    assert result == comictaggerlib.issueidentifier.Result.multiple_good_matches
    assert [(match.md.issue_id, match.distance) for match in matches] == [("exact", 0), ("close", 3)]


def test_identification_reuses_remote_hashes_only_within_the_run(identifier, cbz, monkeypatch):
    fetch = Mock(return_value=cbz.get_page(0))
    monkeypatch.setattr(comictaggerlib.issueidentifier.ImageFetcher, "fetch", fetch)
    cover = comicapi.genericmetadata.ImageHash(Hash=0, Kind="", URL="https://example.com/cover.png")
    monkeypatch.setattr(identifier, "_search_for_issues", lambda terms: [candidate("1", cover), candidate("2", cover)])

    for run in (1, 2):
        result, matches = identifier.identify(cbz, cbz.read_tags("cr"))
        assert result == comictaggerlib.issueidentifier.Result.multiple_good_matches
        assert [match.distance for match in matches] == [0, 0]
        assert fetch.call_count == run


def test_cover_network_failure_is_reported_at_identification_boundary(identifier, cbz, monkeypatch):
    fetch = Mock(side_effect=comictaggerlib.issueidentifier.ImageFetcherException("no connection"))
    monkeypatch.setattr(comictaggerlib.issueidentifier.ImageFetcher, "fetch", fetch)
    cover = comicapi.genericmetadata.ImageHash(Hash=0, Kind="", URL="https://example.com/cover.png")
    monkeypatch.setattr(identifier, "_search_for_issues", lambda terms: [candidate("1", cover)])

    assert identifier.identify(cbz, cbz.read_tags("cr")) == (
        comictaggerlib.issueidentifier.Result.fetch_data_failure,
        [],
    )


@pytest.mark.parametrize("cancel_during_download", [False, True])
def test_alternate_cover_download_failure_preserves_primary_match(identifier, cbz, monkeypatch, cancel_during_download):
    alternate_url = "https://example.com/alternate.png"
    series, issue = candidate("primary", comicapi.genericmetadata.ImageHash(Hash=(1 << 64) - 1, Kind="ahash", URL=""))
    issue._alternate_images = [comicapi.genericmetadata.ImageHash(Hash=0, Kind="", URL=alternate_url)]
    monkeypatch.setattr(identifier, "_search_for_issues", lambda terms: [(series, issue)])
    monkeypatch.setattr(identifier, "calculate_hash", lambda **kwargs: 0)

    def fail_download(fetcher, url):
        assert url == alternate_url
        identifier.cancel = cancel_during_download
        raise comictaggerlib.issueidentifier.ImageFetcherException("no connection")

    monkeypatch.setattr(comictaggerlib.issueidentifier.ImageFetcher, "fetch", fail_download)
    metadata = cbz.read_tags("cr")

    if cancel_during_download:
        with pytest.raises(comictaggerlib.issueidentifier.IssueIdentifierCancelled):
            identifier.identify(cbz, metadata)
    else:
        result, matches = identifier.identify(cbz, metadata)
        assert result == comictaggerlib.issueidentifier.Result.single_bad_cover_score
        assert [match.md.issue_id for match in matches] == ["primary"]


def test_cancellation_after_cover_download_propagates(identifier, cbz, monkeypatch):
    monkeypatch.setattr(comictaggerlib.issueidentifier.ImageFetcher, "fetch", Mock(return_value=cbz.get_page(0)))
    cover = comicapi.genericmetadata.ImageHash(Hash=0, Kind="", URL="https://example.com/cover.png")
    monkeypatch.setattr(identifier, "_search_for_issues", lambda terms: [candidate("1", cover)])

    def cancel_after_download(current, total, image):
        if image:
            identifier.cancel = True

    identifier.progress_callback = cancel_after_download
    with pytest.raises(comictaggerlib.issueidentifier.IssueIdentifierCancelled):
        identifier.identify(cbz, cbz.read_tags("cr"))
