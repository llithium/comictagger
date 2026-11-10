"""A class to represent a single comic, be it file or folder of images"""

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

import hashlib
import importlib.util
import inspect
import io
import logging
import os
import pathlib
import shutil
from collections import Counter
from collections.abc import Callable, Iterable
from functools import cache
from typing import cast

from comicapi import utils
from comicapi.archivers import Archiver, UnknownArchiver, ZipArchiver
from comicapi.archivers.archiver import BulkRemoveArchiver, read_archive
from comicapi.genericmetadata import FileHash, GenericMetadata
from comicapi.pluginloader import ARCHIVER_ENTRY_POINT, TAG_ENTRY_POINT
from comicapi.tags import Tag
from comictaggerlib.ctversion import version

logger = logging.getLogger(__name__)

archivers: list[type[Archiver]] = []
tags: dict[str, Tag] = {}


def load_archive_plugins(local_plugins: Iterable[type[Archiver]] | None = None) -> None:
    if archivers and local_plugins is None:
        return
    from importlib.metadata import entry_points

    builtin: list[type[Archiver]] = []
    archive_plugins: list[type[Archiver]] = []
    # A list is used first matching plugin wins

    for ep in entry_points(group=ARCHIVER_ENTRY_POINT):
        try:
            spec = importlib.util.find_spec(ep.module)
        except Exception:
            spec = None
        try:
            archiver: type[Archiver] = ep.load()

            if ep.module.startswith("comicapi"):
                builtin.append(archiver)
            else:
                archive_plugins.append(archiver)
        except Exception:
            if spec and spec.has_location:
                logger.exception("Failed to load archive plugin: %s from %s", ep.name, spec.origin)
            else:
                logger.exception("Failed to load archive plugin: %s", ep.name)
    archivers.clear()
    archivers.extend(local_plugins or ())
    archivers.extend(archive_plugins)
    archivers.extend(builtin)


def load_tag_plugins(version: str = f"ComicAPI/{version}", local_plugins: Iterable[type[Tag]] | None = None) -> None:
    if tags and local_plugins is None:
        return
    from importlib.metadata import entry_points

    builtin: dict[str, Tag] = {}
    tag_plugins: dict[str, tuple[Tag, str]] = {}
    # A dict is used, last plugin wins
    for ep in entry_points(group=TAG_ENTRY_POINT):
        location = "Unknown"
        try:
            _spec = importlib.util.find_spec(ep.module)
            if _spec and _spec.has_location and _spec.origin:
                location = _spec.origin
        except Exception:
            location = "Unknown"

        try:
            tag: type[Tag] = ep.load()

            if ep.module.startswith("comicapi"):
                builtin[tag.id] = tag(version)
            else:
                if tag.id in tag_plugins:
                    logger.warning(
                        "Plugin %s from %s is overriding the existing plugin for %s tags",
                        ep.module,
                        location,
                        tag.id,
                    )
                tag_plugins[tag.id] = (tag(version), location)
        except Exception:
            logger.exception("Failed to load tag plugin: %s from %s", ep.name, location)
    # A dict is used, last plugin wins
    for tag in local_plugins or ():
        try:
            tag_plugins[tag.id] = (tag(version), "Local")
        except Exception:
            logger.exception("Failed to load local tag plugin: %s", tag)

    for tag_id in set(builtin.keys()).intersection(tag_plugins):
        location = tag_plugins[tag_id][1]
        logger.warning("Builtin plugin for %s tags are being overridden by a plugin from %s", tag_id, location)

    tags.clear()
    tags.update(builtin)
    tags.update({s[0]: s[1][0] for s in tag_plugins.items()})


@cache
def _read_placeholder(path: pathlib.Path) -> bytes:
    return path.read_bytes()


class ComicArchive:

    def __init__(
        self,
        path: pathlib.Path | str | Archiver,
        default_image_path: pathlib.Path | str | None = None,
        hash_archive: str = "",
    ) -> None:
        self._tag_cache: dict[str, GenericMetadata] = {}
        self._page_names: list[str] | None = None
        self.hash_archive = hash_archive
        self.default_image_path = default_image_path

        if isinstance(path, Archiver):
            self.path = path.path
            self.archiver: Archiver = path
        else:
            self.path = pathlib.Path(path).absolute()
            self.archiver = UnknownArchiver.open(self.path)

            load_archive_plugins()
            load_tag_plugins()
            archiver_missing = True
            for archiver in archivers:
                if (
                    archiver.enabled
                    and self.path.suffix in archiver.supported_extensions
                    and archiver.is_valid(self.path)
                ):
                    self.archiver = archiver.open(self.path)
                    archiver_missing = False
                    break

            if archiver_missing:
                for archiver in archivers:
                    if archiver.enabled and archiver.is_valid(self.path):
                        self.archiver = archiver.open(self.path)
                        break

    def reset_cache(self) -> None:
        self._page_names = None
        self._tag_cache.clear()

    def load_cache(self, tag_ids: Iterable[str]) -> None:
        for tag_id in tag_ids:
            if tag_id not in tags:
                continue
            md = self._read_tags(tag_id)
            if not md.is_empty:
                self._tag_cache[tag_id] = md.copy()
            else:
                self._tag_cache.pop(tag_id, None)

    def get_supported_tags(self) -> list[str]:
        return [tag_id for tag_id, tag in tags.items() if tag.enabled and tag.supports_tags(self.archiver)]

    def rename(self, path: pathlib.Path | str, *, remove_empty_source_dir: bool = False) -> None:
        new_path = pathlib.Path(path).absolute()
        if new_path == self.path:
            return
        old_parent = self.path.parent
        os.makedirs(new_path.parent, 0o777, True)
        shutil.move(self.path, new_path)
        self.path = new_path
        # Some archivers cache an open reader tied to the old filename. Reopen
        # instead of only replacing ``path`` so a post-rename refresh reads the
        # archive at its new location.
        self.archiver = type(self.archiver).open(new_path)
        self.reset_cache()
        if remove_empty_source_dir:
            try:
                old_parent.rmdir()
            except OSError:
                # Source folders with other archives or user files are kept.
                pass

    def is_writable(self, check_archive_status: bool = True) -> bool:
        if isinstance(self.archiver, UnknownArchiver):
            return False

        if check_archive_status and not self.archiver.is_writable():
            return False

        if not (os.access(self.path, os.W_OK) and os.access(self.path.parent, os.W_OK)):
            return False

        return True

    def is_zip(self) -> bool:
        return self.archiver.name() == "ZIP"

    def seems_to_be_a_comic_archive(self) -> bool:
        if (
            not (isinstance(self.archiver, UnknownArchiver))
            and self.get_number_of_pages() > 0
            and self.archiver.is_valid(self.path)
        ):
            return True

        return False

    def extension(self) -> str:
        return self.archiver.extension()

    def read_tags(self, tag_id: str) -> GenericMetadata:
        if tag_id in self._tag_cache:
            return self._tag_cache[tag_id].copy()
        return self._read_tags(tag_id)

    def _read_tags(self, tag_id: str) -> GenericMetadata:
        tag = tags[tag_id]
        if not tag.enabled:
            return GenericMetadata()
        md = tag.read_tags(self.archiver)
        # The presence check distinguishes an empty tag from no tag.
        if not md.is_empty or tag.has_tags(self.archiver):
            md.apply_default_page_list(self._get_page_names())
        return md

    def read_raw_tags(self, tag_id: str) -> str:
        if not tags[tag_id].enabled:
            return ""
        return tags[tag_id].read_raw_tags(self.archiver)

    def write_tags(self, metadata: GenericMetadata, tag_id: str) -> bool:
        self._tag_cache.pop(tag_id, None)
        if not tags[tag_id].enabled:
            logger.warning("%s tags not enabled", tags[tag_id].name())
            return False

        self.apply_archive_info_to_metadata(metadata, True, True, hash_archive=self.hash_archive)
        return tags[tag_id].write_tags(metadata, self.archiver)

    def has_tags(self, tag_id: str) -> bool:
        if tag_id in self._tag_cache:
            return True
        if not tags[tag_id].enabled:
            return False
        return tags[tag_id].has_tags(self.archiver)

    def remove_tags(self, tag_id: str) -> bool:
        self._tag_cache.pop(tag_id, None)
        if not tags[tag_id].enabled:
            return False
        return tags[tag_id].remove_tags(self.archiver)

    def get_page(self, index: int, *, reader: Callable[[str], bytes] | None = None) -> bytes:
        filename = self.get_page_name(index)
        if not filename:
            return b""
        try:
            return (reader or self.archiver.read_file)(filename) or b""
        except Exception:
            logger.exception("Error reading page %d from %s", index, self.path)
            if self.default_image_path:
                try:
                    return _read_placeholder(pathlib.Path(self.default_image_path).absolute())
                except OSError:
                    logger.exception("Error reading placeholder image %s", self.default_image_path)
            return b""

    def get_page_name(self, index: int | None) -> str:
        page_names = self._get_page_names()
        if index is None or not -len(page_names) <= index < len(page_names):
            return ""
        return page_names[index]

    def get_scanner_page_index(self) -> int | None:
        names = self._get_page_names()
        # With fewer pages there is not enough evidence for a filename pattern.
        if len(names) < 5:
            return None
        basenames = [os.path.basename(name) for name in names]
        lengths = Counter(map(len, basenames))
        mode_length = max(lengths, key=lambda length: (lengths[length], length))
        prefix = os.path.commonprefix([name for name in basenames if len(name) == mode_length])
        final_name = basenames[-1]
        if mode_length <= 7 and not prefix:
            # A run of short names with no shared prefix is likely numbered.
            is_scanner_page = len(final_name) > mode_length
        else:
            is_scanner_page = not final_name.startswith(prefix)
        return len(names) - 1 if is_scanner_page else None

    def _get_page_names(self) -> list[str]:
        if self._page_names is None:
            self._page_names = utils.get_page_name_list(self.archiver.get_filename_list())
        return self._page_names

    def get_page_name_list(self) -> list[str]:
        return self._get_page_names().copy()

    def get_number_of_pages(self) -> int:
        return len(self._get_page_names())

    def remove_pages(self, page_indexes: Iterable[int]) -> list[int]:
        """Remove image files from the archive and return the indexes successfully removed."""
        page_names = self._get_page_names()
        indexes = sorted({index for index in page_indexes if 0 <= index < len(page_names)}, reverse=True)
        if isinstance(self.archiver, BulkRemoveArchiver):
            removed_names = set(self.archiver.remove_files([page_names[index] for index in indexes]))
            removed = [index for index in indexes if page_names[index] in removed_names]
        else:
            removed = [index for index in indexes if self.archiver.remove_file(page_names[index])]
        for index in set(indexes).difference(removed):
            logger.error("Failed to remove page %d (%s) from %s", index, page_names[index], self.path)

        if removed:
            self.reset_cache()
        return sorted(removed)

    def apply_archive_info_to_metadata(
        self,
        md: GenericMetadata,
        calc_page_sizes: bool = False,
        detect_double_page: bool = False,
        *,
        hash_archive: str = "",
    ) -> None:
        md.apply_default_page_list(self._get_page_names())
        if not self.seems_to_be_a_comic_archive():
            return

        if (
            hash_archive in hashlib.algorithms_available
            and not md.original_hash
            and getattr(self.archiver, "hashable", True)
        ):
            hasher = getattr(hashlib, hash_archive, hash_archive)
            try:
                with self.archiver.path.open("rb") as archive:
                    digest = utils.file_digest(archive, hasher)
                if len(inspect.signature(digest.hexdigest).parameters) > 0:
                    length = digest.name.rpartition("_")[2]
                    if not length.isdigit():
                        length = "128"
                    hexdigest = cast(Callable[[int], str], digest.hexdigest)
                    md.original_hash = FileHash(digest.name, hexdigest(int(length) // 8))
                else:
                    md.original_hash = FileHash(digest.name, digest.hexdigest())
            except Exception:
                logger.exception("Failed to calculate original hash for '%s'", self.archiver.path)
        if not calc_page_sizes:
            return
        try:
            from PIL import Image
        except ImportError:
            Image = None
        with read_archive(self.archiver) as reader:
            for p in md.pages:
                if p.byte_size is None or p.height is None or p.width is None or p.double_page is None:
                    try:
                        data = self.get_page(p.archive_index, reader=reader)
                        p.byte_size = len(data)
                        if not data or Image is None:
                            continue
                        with Image.open(io.BytesIO(data)) as im:
                            p.width, p.height = im.size
                        if detect_double_page:
                            p.double_page = p.is_double_page()
                    except Exception as e:
                        logger.exception("Error decoding image [%s] %s :: image %s", e, self.path, p.archive_index)

    def metadata_from_filename(
        self,
        parser: utils.Parser = utils.Parser.ORIGINAL,
        remove_c2c: bool = False,
        remove_fcbd: bool = False,
        remove_publisher: bool = False,
        split_words: bool = False,
        allow_issue_start_with_letter: bool = False,
        protofolius_issue_number_scheme: bool = False,
        *,
        publisher_names: Iterable[str] = (),
    ) -> GenericMetadata:
        metadata = GenericMetadata()

        filename_info = utils.parse_filename(
            self.path.name,
            parser=parser,
            remove_c2c=remove_c2c,
            remove_fcbd=remove_fcbd,
            remove_publisher=remove_publisher,
            split_words=split_words,
            allow_issue_start_with_letter=allow_issue_start_with_letter,
            protofolius_issue_number_scheme=protofolius_issue_number_scheme,
            publisher_names=publisher_names,
        )
        metadata.alternate_number = utils.xlate(filename_info.get("alternate", None))
        metadata.issue = utils.xlate(filename_info.get("issue", None))
        metadata.issue_count = utils.xlate_int(filename_info.get("issue_count", None))
        metadata.publisher = utils.xlate(filename_info.get("publisher", None))
        metadata.series = utils.xlate(filename_info.get("series", None))
        metadata.title = utils.xlate(filename_info.get("title", None))
        metadata.volume = utils.xlate_int(filename_info.get("volume", None))
        metadata.volume_count = utils.xlate_int(filename_info.get("volume_count", None))
        metadata.year = utils.xlate_int(filename_info.get("year", None))

        metadata.scan_info = utils.xlate(filename_info.get("remainder", None))

        if filename_info.get("fcbd", None):
            metadata.format = "FCBD"
            metadata.tags.add("FCBD")

        if filename_info.get("c2c", None):
            metadata.tags.add("c2c")

        if filename_info.get("annual", None):
            metadata.format = "Annual"

        if filename_info.get("format", None):
            metadata.format = filename_info["format"]

        return metadata

    def export_as_zip(self, zip_filename: pathlib.Path, *, overwrite: bool = True) -> bool:
        if self.is_zip():
            # nothing to do, we're already a zip
            return True

        zip_archiver = ZipArchiver()
        zip_archiver.path = zip_filename
        return zip_archiver.copy_from_archive(self.archiver, overwrite=overwrite)

    def export_as_new_zip(self, zip_filename: pathlib.Path) -> pathlib.Path | None:
        if self.is_zip():
            return self.path
        zip_archiver = ZipArchiver()
        zip_archiver.path = zip_filename
        return zip_archiver.export_from_archive(self.archiver)
