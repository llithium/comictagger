"""A class to manage fetching and caching of images by URL"""

#
# Copyright 2012-2014 ComicTagger Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import contextlib
import datetime
import io
import logging
import os
import pathlib
import sqlite3
import tempfile

import requests
from PIL import Image

from comictaggerlib import ctversion

logger = logging.getLogger(__name__)
USER_AGENT = "comictagger image fetcher/" + ctversion.version


class ImageFetcherException(Exception): ...


class ImageFetcher:
    def __init__(self, cache_folder: pathlib.Path) -> None:
        self.db_file = cache_folder / "image_url_cache.db"
        self.cache_folder = cache_folder / "image_cache"
        self.cache_folder.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(sqlite3.connect(self.db_file)) as con, con:
            con.execute("CREATE TABLE IF NOT EXISTS Images(url TEXT,filename TEXT,timestamp TEXT,PRIMARY KEY (url))")

    def fetch(self, url: str) -> bytes:
        if cached := self.get_image_from_cache(url):
            return cached
        try:
            response = requests.get(url, headers={"user-agent": USER_AGENT}, timeout=60)
            response.raise_for_status()
        except requests.RequestException as e:
            raise ImageFetcherException(f"Could not fetch {url}") from e
        return self.add_image_to_cache(url, response.content)

    @staticmethod
    def _verify_image(url: str, data: bytes) -> bytes:
        if data:
            try:
                with Image.open(io.BytesIO(data)) as image:
                    image.verify()
                return data
            except Exception:
                logger.warning("Invalid cover image from %s", url, exc_info=True)
        return b""

    def add_image_to_cache(self, url: str, image_data: bytes) -> bytes:
        if not (image_data := self._verify_image(url, image_data)):
            return b""

        filename: str | None = None
        try:
            fd, filename = tempfile.mkstemp(dir=self.cache_folder, prefix="img")
            with os.fdopen(fd, "wb") as image_file:
                image_file.write(image_data)
            with contextlib.closing(sqlite3.connect(self.db_file)) as con, con:
                con.execute("BEGIN IMMEDIATE")
                prior = con.execute("SELECT filename FROM Images WHERE url=?", (url,)).fetchone()
                con.execute(
                    "INSERT OR REPLACE INTO Images VALUES (?, ?, ?)",
                    (url, filename, datetime.datetime.now().isoformat()),
                )
        except (OSError, sqlite3.Error):
            logger.warning("Could not cache cover image from %s", url, exc_info=True)
            if filename is not None:
                self._remove_cache_file(filename)
        else:
            if prior is not None:
                self._remove_cache_file(prior[0])
        return image_data

    def _remove_cache_file(self, filename: str) -> None:
        path = pathlib.Path(filename)
        if path.parent.absolute() == self.cache_folder.absolute() and path.name.startswith("img"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove cached image %s", path, exc_info=True)

    def get_image_from_cache(self, url: str) -> bytes:
        try:
            with contextlib.closing(sqlite3.connect(self.db_file)) as con:
                row = con.execute("SELECT filename FROM Images WHERE url=?", (url,)).fetchone()
            if row is not None:
                return self._verify_image(url, pathlib.Path(row[0]).read_bytes())
        except FileNotFoundError:
            pass
        except (OSError, sqlite3.Error):
            logger.warning("Could not read cached cover image from %s", url, exc_info=True)
        return b""
