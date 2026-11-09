from __future__ import annotations

import io
from unittest.mock import Mock

import pytest
from PIL import Image

from comictaggerlib import imagefetcher


def image_bytes(color):
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), color).save(stream, format="PNG")
    return stream.getvalue()


def test_blocking_fetch_caches_verified_image(tmp_path, monkeypatch):
    png = image_bytes("red")
    response = Mock(content=png)
    get = Mock(return_value=response)
    monkeypatch.setattr(imagefetcher.requests, "get", get)
    fetcher = imagefetcher.ImageFetcher(tmp_path)

    assert fetcher.fetch("https://example.com/cover.png") == png
    assert fetcher.fetch("https://example.com/cover.png") == png
    assert get.call_count == 1
    response.raise_for_status.assert_called_once()


def test_replacing_cache_entry_keeps_latest_cover_without_orphaning_old_file(tmp_path):
    fetcher = imagefetcher.ImageFetcher(tmp_path)
    url = "https://example.com/cover.png"

    fetcher.add_image_to_cache(url, image_bytes("red"))
    latest = image_bytes("blue")
    fetcher.add_image_to_cache(url, latest)

    assert fetcher.get_image_from_cache(url) == latest
    assert len(list(fetcher.cache_folder.iterdir())) == 1


def test_cover_widget_ignores_late_response_for_previous_alternate(tmp_path, request):
    pytest.importorskip("PyQt6")
    qtbot = request.getfixturevalue("qtbot")
    from PyQt6 import QtWidgets

    from comictaggerlib.coverimagewidget import CoverImageWidget

    first, second = "https://example.com/one.png", "https://example.com/two.png"
    red, blue = image_bytes("red"), image_bytes("blue")
    fetcher = imagefetcher.ImageFetcher(tmp_path)
    fetcher.add_image_to_cache(first, red)
    fetcher.add_image_to_cache(second, blue)

    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    widget = CoverImageWidget(parent, CoverImageWidget.AltCoverMode, tmp_path)
    widget.set_url_list([first, second])
    widget.increment_image()
    widget.cover_remote_fetch_complete(first, red)

    assert widget.current_pixmap.toImage().pixelColor(0, 0).name() == "#0000ff"
