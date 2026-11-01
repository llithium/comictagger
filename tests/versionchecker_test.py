from __future__ import annotations

from unittest.mock import Mock

from comictaggerlib import versionchecker


def test_latest_version_uses_fork_release(monkeypatch):
    get = Mock()
    get.return_value.json.return_value = {"tag_name": " 1.6.0 ", "name": "ComicTagger 1.6.0"}
    monkeypatch.setattr(versionchecker.requests, "get", get)

    assert versionchecker.VersionChecker().get_latest_version() == ("1.6.0", "ComicTagger 1.6.0")
    assert get.call_args.args[0] == "https://api.github.com/repos/llithium/comictagger/releases/latest"


def test_no_published_release(monkeypatch):
    get = Mock()
    get.return_value.raise_for_status.side_effect = versionchecker.requests.HTTPError("404 Not Found")
    monkeypatch.setattr(versionchecker.requests, "get", get)

    assert versionchecker.VersionChecker().get_latest_version() == ("", "")


def test_release_without_name(monkeypatch):
    get = Mock()
    get.return_value.json.return_value = {"tag_name": "1.6.0", "name": None}
    monkeypatch.setattr(versionchecker.requests, "get", get)

    assert versionchecker.VersionChecker().get_latest_version() == ("1.6.0", "1.6.0")
