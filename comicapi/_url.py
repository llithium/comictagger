"""URL types and parsing shared by ComicAPI consumers."""

from __future__ import annotations

from urllib3.exceptions import HTTPError, LocationParseError, LocationValueError
from urllib3.util import Url, parse_url

__all__ = ("Url", "parse_url", "HTTPError", "LocationParseError", "LocationValueError")
