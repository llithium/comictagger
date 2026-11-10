"""A class to encapsulate ComicRack's ComicInfo.xml data"""

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

import logging
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from comicapi import utils
from comicapi.archivers import Archiver
from comicapi.genericmetadata import FileHash, GenericMetadata, PageMetadata
from comicapi.tags import Tag

logger = logging.getLogger(__name__)


def _read_web_links(value: str | None) -> list[utils.Url]:
    return utils.split_urls(utils.xlate(value))


def _read_bool(value: str | None) -> bool | None:
    text = utils.xlate(value)
    return None if text is None else text.casefold() in ("yes", "true", "1")


def _read_set(value: str | None) -> set[str]:
    return set(utils.split(value, ","))


def _read_list(value: str | None) -> list[str]:
    return utils.split(value, ",")


_FIELDS: tuple[tuple[str, str, Callable[[str | None], object]], ...] = (
    ("series", "Series", utils.xlate),
    ("series_start_year", "SeriesStartYear", utils.xlate_int),
    ("issue", "Number", utils.xlate),
    ("issue_count", "Count", utils.xlate_int),
    ("title", "Title", utils.xlate),
    ("volume", "Volume", utils.xlate_int),
    ("genres", "Genre", _read_set),
    ("description", "Summary", utils.xlate),
    ("notes", "Notes", utils.xlate),
    ("alternate_series", "AlternateSeries", utils.xlate),
    ("alternate_number", "AlternateNumber", utils.xlate),
    ("alternate_count", "AlternateCount", utils.xlate_int),
    ("story_arcs", "StoryArc", _read_list),
    ("series_groups", "SeriesGroup", _read_list),
    ("publisher", "Publisher", utils.xlate),
    ("imprint", "Imprint", utils.xlate),
    ("day", "Day", utils.xlate_int),
    ("month", "Month", utils.xlate_int),
    ("year", "Year", utils.xlate_int),
    ("language", "LanguageISO", utils.xlate),
    ("web_links", "Web", _read_web_links),
    ("format", "Format", utils.xlate),
    ("manga", "Manga", utils.xlate),
    ("black_and_white", "BlackAndWhite", _read_bool),
    ("maturity_rating", "AgeRating", utils.xlate),
    ("critical_rating", "CommunityRating", utils.xlate_float),
)

_TRAILING_FIELDS = (
    ("page_count", "PageCount", utils.xlate_int),
    ("characters", "Characters", _read_set),
    ("teams", "Teams", _read_set),
    ("locations", "Locations", _read_set),
)

_CREDIT_ROLES = {
    "Writer": ("Writer", GenericMetadata.writer_synonyms),
    "Penciller": ("Penciller", GenericMetadata.penciller_synonyms),
    "Inker": ("Inker", GenericMetadata.inker_synonyms),
    "Colorist": ("Colorist", GenericMetadata.colorist_synonyms),
    "Letterer": ("Letterer", GenericMetadata.letterer_synonyms),
    "CoverArtist": ("Cover", GenericMetadata.cover_synonyms),
    "Editor": ("Editor", GenericMetadata.editor_synonyms),
}
_SUPPORTED_ROLES = {alias for _, aliases in _CREDIT_ROLES.values() for alias in aliases}


class ComicRack(Tag):
    enabled = True
    id = "cr"

    def __init__(self, version: str) -> None:
        super().__init__(version)
        self.file = "ComicInfo.xml"
        self.supported_attributes = {
            *(name for name, _, _ in (*_FIELDS, *_TRAILING_FIELDS)),
            "original_hash",
            "scan_info",
            "pages",
            "pages.bookmark",
            "pages.double_page",
            "pages.height",
            "pages.image_index",
            "pages.size",
            "pages.type",
            "pages.width",
            "credits",
            "credits.person",
            "credits.role",
        }

    def supports_credit_role(self, role: str) -> bool:
        return role.casefold() in _SUPPORTED_ROLES

    def supports_tags(self, archive: Archiver) -> bool:
        return archive.supports_files()

    def _read_xml(self, archive: Archiver) -> ET.Element | None:
        if not self.supports_tags(archive) or self.file not in archive.get_filename_list():
            return None
        try:
            root = ET.fromstring(archive.read_file(self.file))
        except (ET.ParseError, LookupError):
            return None
        return root if root.tag == "ComicInfo" else None

    def has_tags(self, archive: Archiver) -> bool:
        try:
            return self._read_xml(archive) is not None
        except Exception:
            return False

    def remove_tags(self, archive: Archiver) -> bool:
        return self.has_tags(archive) and archive.remove_file(self.file)

    def read_tags(self, archive: Archiver) -> GenericMetadata:
        try:
            root = self._read_xml(archive)
            if root is not None:
                return self._convert_xml_to_metadata(root)
        except Exception:
            logger.debug("Unable to read %s in %s", self.file, archive.path, exc_info=True)
        return GenericMetadata()

    def read_raw_tags(self, archive: Archiver) -> str:
        try:
            root = self._read_xml(archive)
            if root is not None:
                return ET.tostring(root, encoding="unicode", xml_declaration=True)
        except Exception:
            logger.debug("Unable to read %s in %s", self.file, archive.path, exc_info=True)
        return ""

    def write_tags(self, metadata: GenericMetadata, archive: Archiver) -> bool:
        if not self.supports_tags(archive):
            logger.warning("Archive %s(%s) does not support '%s' metadata", archive.path, archive.name(), self.name())
            return False

        try:
            try:
                existing_xml = self._read_xml(archive)
            except OSError:
                logger.debug("Unable to read existing %s in %s", self.file, archive.path, exc_info=True)
                existing_xml = None
            root = self._convert_metadata_to_xml(metadata, existing_xml)
            return archive.write_file(self.file, ET.tostring(root, encoding="utf-8", xml_declaration=True))
        except Exception:
            logger.exception("Unable to write %s in %s", self.file, archive.path)
            return False

    def name(self) -> str:
        return "Comic Rack"

    def _convert_metadata_to_xml(self, md: GenericMetadata, root: ET.Element | None) -> ET.Element:
        if root is None:
            root = ET.Element(
                "ComicInfo",
                {
                    "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                    "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
                },
            )

        def assign(element_name: str, value: object) -> None:
            element = root.find(element_name)
            if value:
                if element is None:
                    element = ET.SubElement(root, element_name)
                element.text = ",".join(value) if isinstance(value, (list, set)) else str(value)
            elif element is not None:
                root.remove(element)

        for name, element_name, _ in _FIELDS:
            value = getattr(md, name)
            if name == "web_links":
                value = " ".join(link.url for link in md.web_links)
            elif name == "black_and_white":
                value = "Yes" if md.black_and_white else None
            assign(element_name, value)

        scan_info = md.scan_info or ""
        if md.original_hash:
            scan_info += f" sum:{md.original_hash}"
        assign("ScanInformation", scan_info)

        for name, element_name, _ in _TRAILING_FIELDS:
            assign(element_name, getattr(md, name))

        for element_name, (_, aliases) in _CREDIT_ROLES.items():
            assign(
                element_name,
                ", ".join(credit.person.replace(",", "") for credit in md.credits if credit.role.casefold() in aliases),
            )

        pages_node = root.find("Pages")
        if pages_node is not None:
            pages_node.clear()
        else:
            pages_node = ET.SubElement(root, "Pages")

        for page in sorted(md.pages, key=lambda x: x.archive_index):
            page_node = ET.SubElement(pages_node, "Page")
            page_node.attrib = {"Image": str(page.display_index)}
            if page.bookmark:
                page_node.attrib["Bookmark"] = page.bookmark
            if page.type:
                page_node.attrib["Type"] = page.type

            if page.double_page is not None:
                page_node.attrib["DoublePage"] = str(page.double_page)
            if page.height is not None:
                page_node.attrib["ImageHeight"] = str(page.height)
            if page.byte_size is not None:
                page_node.attrib["ImageSize"] = str(page.byte_size)
            if page.width is not None:
                page_node.attrib["ImageWidth"] = str(page.width)
            page_node.attrib = dict(sorted(page_node.attrib.items()))

        ET.indent(root)

        return root

    def _convert_xml_to_metadata(self, root: ET.Element) -> GenericMetadata:
        md = GenericMetadata()
        for name, element_name, decode in (*_FIELDS, *_TRAILING_FIELDS):
            setattr(md, name, decode(root.findtext(element_name)))

        scan_info_list = (utils.xlate(root.findtext("ScanInformation")) or "").split()
        for word in scan_info_list.copy():
            if not word.startswith("sum:"):
                continue
            original_hash = FileHash.parse(word[4:])
            if original_hash:
                md.original_hash = original_hash
                scan_info_list.remove(word)
                break
        if scan_info_list:
            md.scan_info = " ".join(scan_info_list)

        for element in root:
            credit_role = _CREDIT_ROLES.get(element.tag)
            if credit_role is not None:
                for name in utils.split(element.text, ","):
                    md.add_credit(name.strip(), credit_role[0])

        pages_node = root.find("Pages")
        if pages_node is not None:
            for i, page in enumerate(pages_node):
                p: dict[str, Any] = page.attrib
                md_page = PageMetadata(
                    filename="",  # cr doesn't record the filename it just assumes it's always ordered the same
                    display_index=int(p.get("Image", i)),
                    archive_index=i,
                    bookmark=p.get("Bookmark", ""),
                    type="",
                )
                md_page.set_type(p.get("Type", ""))

                if isinstance(p.get("DoublePage", None), str):
                    md_page.double_page = p["DoublePage"].casefold() in ("yes", "true", "1")
                if p.get("ImageHeight", "").isnumeric():
                    md_page.height = int(float(p["ImageHeight"]))
                if p.get("ImageWidth", "").isnumeric():
                    md_page.width = int(float(p["ImageWidth"]))
                if p.get("ImageSize", "").isnumeric():
                    md_page.byte_size = int(float(p["ImageSize"]))

                md.pages.append(md_page)

        return md
