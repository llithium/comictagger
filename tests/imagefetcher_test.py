from __future__ import annotations

import io
from unittest.mock import Mock

import pytest
from PIL import Image

from comictaggerlib import imagefetcher


@pytest.fixture
def image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(stream, format="PNG")
    return stream.getvalue()


def test_blocking_fetch_caches_verified_image(tmp_path, monkeypatch, image_bytes):
    monkeypatch.setattr(imagefetcher.ImageFetcher, "qt_available", False)
    response = Mock(content=image_bytes)
    get = Mock(return_value=response)
    monkeypatch.setattr(imagefetcher.requests, "get", get)
    fetcher = imagefetcher.ImageFetcher(tmp_path)

    assert fetcher.fetch("https://example.com/cover.png", blocking=True) == image_bytes
    assert fetcher.fetch("https://example.com/cover.png", blocking=True) == image_bytes
    assert get.call_count == 1
    assert get.call_args.kwargs["timeout"] == 60
    response.raise_for_status.assert_called_once()


def test_cached_async_fetch_supports_optional_callback(tmp_path, monkeypatch, image_bytes):
    pytest.importorskip("PyQt6")
    monkeypatch.setattr(imagefetcher.ImageFetcher, "qt_available", False)
    fetcher = imagefetcher.ImageFetcher(tmp_path)
    url = "https://example.com/cover.png"
    fetcher.add_image_to_cache(url, image_bytes)
    fetcher.qt_available = True

    assert fetcher.fetch(url) == b""

    callback = Mock()
    fetcher.image_fetch_complete = callback
    assert fetcher.fetch(url) == b""
    assert callback.call_args.args[0] == url
    assert bytes(callback.call_args.args[1]) == image_bytes
