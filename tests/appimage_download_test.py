from __future__ import annotations

import importlib.util
import pathlib
import stat
import sys
from unittest.mock import Mock

import pytest


@pytest.fixture
def downloader():
    spec = importlib.util.spec_from_file_location("get_appimage", pathlib.Path("build-tools/get_appimage.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_download_failure_does_not_create_or_chmod(downloader, tmp_path, monkeypatch):
    destination = tmp_path / "build" / "appimagetool.AppImage"
    response = Mock(status_code=404)
    response.raise_for_status.side_effect = RuntimeError("HTTP 404")
    get = Mock(return_value=response)
    chmod = Mock()
    monkeypatch.setattr(downloader.requests, "get", get)
    monkeypatch.setattr(downloader.os, "chmod", chmod)
    monkeypatch.setattr(sys, "argv", ["get_appimage.py", str(destination)])

    with pytest.raises(RuntimeError, match="HTTP 404"):
        downloader.main()

    assert not destination.exists()
    chmod.assert_not_called()
    assert get.call_args.kwargs["timeout"] == 60


def test_download_writes_executable(downloader, tmp_path, monkeypatch):
    destination = tmp_path / "build" / "appimagetool.AppImage"
    response = Mock(status_code=200, content=b"appimage")
    monkeypatch.setattr(downloader.requests, "get", Mock(return_value=response))
    monkeypatch.setattr(sys, "argv", ["get_appimage.py", str(destination)])

    downloader.main()

    assert destination.read_bytes() == b"appimage"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
