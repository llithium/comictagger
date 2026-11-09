"""A class for internal metadata storage

The goal of this class is to handle ALL the data that might come from various
tagging schemes and databases, such as ComicVine or GCD.  This makes conversion
possible, however lossy it might be

"""

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

import copy
import dataclasses
import hashlib
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Union, overload

from typing_extensions import NamedTuple

from comicapi import merge, utils
from comicapi._url import Url, parse_url
from comicapi.utils import norm_fold

# needed for runtime type guessing
if TYPE_CHECKING:
    Union

logger = logging.getLogger(__name__)


REMOVE = object()


@dataclasses.dataclass
class Credit:
    person: str = ""
    role: str = ""
    primary: bool = False
    language: str = ""  # Should be ISO 639 language code

    def __str__(self) -> str:
        lang = ""
        role = ""
        if self.role:
            role = f"{self.role}: "
        if self.language:
            lang = f" [{self.language}]"
        return f"{role}{self.person}{lang}"


class PageType(merge.StrEnum):
    """
    These page info classes are exactly the same as the CIX scheme, since
    it's unique
    """

    FrontCover = "FrontCover"
    InnerCover = "InnerCover"
    Roundup = "Roundup"
    Story = "Story"
    Advertisement = "Advertisement"
    Editorial = "Editorial"
    Letters = "Letters"
    Preview = "Preview"
    BackCover = "BackCover"
    Other = "Other"
    Deleted = "Deleted"


@dataclasses.dataclass
class PageMetadata:
    filename: str
    type: str
    bookmark: str
    display_index: int
    archive_index: int
    # These are optional because getting this info requires reading in each page
    double_page: bool | None = None
    byte_size: int | None = None
    height: int | None = None
    width: int | None = None

    def set_type(self, value: str) -> None:
        values = {x.casefold(): x for x in PageType}
        self.type = values.get(value.casefold(), value)

    def is_double_page(self) -> bool:
        w = self.width or 0
        h = self.height or 0
        return self.double_page or (w >= h and w > 0 and h > 0)

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, PageMetadata):
            return False
        return self.archive_index < other.archive_index

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, PageMetadata):
            return False
        return self.archive_index == other.archive_index


@dataclasses.dataclass
class ComicSeries:
    id: str
    name: str
    aliases: set[str]
    count_of_issues: int | None
    count_of_volumes: int | None
    description: str
    image_url: str
    publisher: str
    start_year: int | None
    format: str | None
    web_links: list[Url] = dataclasses.field(default_factory=list)
    volume_number: int | None = None

    def copy(self) -> ComicSeries:
        return copy.deepcopy(self)


class MetadataOrigin(NamedTuple):
    id: str
    name: str

    def __str__(self) -> str:
        return self.name


class ImageHash(NamedTuple):
    """
    A valid ImageHash requires at a minimum a Hash and Kind or a URL
    If only a URL is given, it will be used for cover matching otherwise Hash is used
    The URL is also required for the GUI to display covers
    Available Kind's are "ahash" and "phash"
    """

    Hash: int
    Kind: str
    URL: str


class FileHash(NamedTuple):
    name: str
    hash: str

    def __str__(self) -> str:
        return self.name + ":" + self.hash

    @classmethod
    def parse(cls, string: str) -> FileHash:
        name, _, parsed_hash = string.partition(":")
        if name in hashlib.algorithms_available:
            return FileHash(name, parsed_hash)
        return FileHash("", "")

    def __bool__(self) -> bool:
        return all(self)


@dataclasses.dataclass
class GenericMetadata:
    writer_synonyms = ("writer", "plotter", "scripter", "script")
    penciller_synonyms = ("artist", "penciller", "penciler", "breakdowns", "pencils", "painting")
    inker_synonyms = ("inker", "artist", "finishes", "inks", "painting")
    colorist_synonyms = ("colorist", "colourist", "colorer", "colourer", "colors", "painting")
    letterer_synonyms = ("letterer", "letters")
    cover_synonyms = ("cover", "covers", "coverartist", "cover artist")
    editor_synonyms = ("editor", "edits", "editing")
    translator_synonyms = ("translator", "translation")

    is_empty: bool = True
    data_origin: MetadataOrigin | None = None
    issue_id: str | None = None
    series_id: str | None = None
    original_hash: FileHash | None = None

    series: str | None = None
    series_start_year: int | None = None
    series_aliases: set[str] = dataclasses.field(default_factory=set)
    issue: str | None = None
    issue_count: int | None = None
    title: str | None = None
    title_aliases: set[str] = dataclasses.field(default_factory=set)
    volume: int | None = None
    volume_count: int | None = None
    genres: set[str] = dataclasses.field(default_factory=set)
    description: str | None = None  # use same way as Summary in CIX
    notes: str | None = None

    alternate_series: str | None = None
    alternate_number: str | None = None
    alternate_count: int | None = None
    story_arcs: list[str] = dataclasses.field(default_factory=list)
    series_groups: list[str] = dataclasses.field(default_factory=list)

    gtin: str | None = None  # ISBN/EAN identifier

    publisher: str | None = None
    imprint: str | None = None
    day: int | None = None
    month: int | None = None
    year: int | None = None
    language: str | None = None  # 2 letter iso code
    country: str | None = None
    web_links: list[Url] = dataclasses.field(default_factory=list)
    format: str | None = None
    manga: str | None = None
    black_and_white: bool | None = None
    maturity_rating: str | None = None
    critical_rating: float | None = None  # rating in CBL; CommunityRating in CIX
    scan_info: str | None = None

    tags: set[str] = dataclasses.field(default_factory=set)
    pages: list[PageMetadata] = dataclasses.field(default_factory=list)
    page_count: int | None = None

    characters: set[str] = dataclasses.field(default_factory=set)
    teams: set[str] = dataclasses.field(default_factory=set)
    locations: set[str] = dataclasses.field(default_factory=set)
    credits: list[Credit] = dataclasses.field(default_factory=list)

    # Some CoMet-only items
    price: float | None = None
    is_version_of: str | None = None
    rights: str | None = None
    identifier: str | None = None
    last_mark: str | None = None

    # urls to cover image, not generally part of the metadata
    _cover_image: ImageHash | None = None
    _alternate_images: list[ImageHash] = dataclasses.field(default_factory=list)

    @property  # type: ignore[no-redef]
    def is_empty(self) -> bool:  # noqa: F811
        for key, value in self.__dict__.items():
            if value and key != "is_empty":
                return False
        return True

    @is_empty.setter
    def is_empty(self, value: bool) -> None:
        # Older plugins pass or assign is_empty; emptiness is computed from the fields.
        pass

    def copy(self) -> GenericMetadata:
        return copy.deepcopy(self)

    def replace(self, /, **kwargs: Any) -> GenericMetadata:
        tmp = self.copy()
        tmp.__dict__.update(kwargs)
        return tmp

    def overlay(
        self, new_md: GenericMetadata, mode: merge.Mode = merge.Mode.OVERLAY, merge_lists: bool = False
    ) -> None:
        """Overlay a new metadata object on this one"""

        attribute_merge = merge.attribute[mode]
        list_merge = merge.lists[mode]
        for field in dataclasses.fields(GenericMetadata):
            name = field.name
            if name == "is_empty":
                continue
            old = getattr(self, name)
            new = getattr(new_md, name)
            default_factory = field.default_factory
            is_collection = default_factory is list or default_factory is set
            if new is REMOVE:
                setattr(self, name, default_factory() if callable(default_factory) else field.default)
                continue
            if is_collection and merge_lists and name != "pages":
                # Pages describe one archive's order and must be replaced together.
                value = list_merge(old, new)
            else:
                value = attribute_merge(old, new)

            if name == "credits":
                self.credits = []
                for credit in value:
                    self.add_credit(copy.copy(credit))
            elif value is not old:
                setattr(self, name, copy.deepcopy(value) if is_collection else value)

    def apply_default_page_list(self, page_list: Sequence[str]) -> None:
        """apply a default page list, with the first page marked as the cover"""

        pages = {page.archive_index: page for page in self.pages}
        cover_set = False
        for index, filename in enumerate(page_list):
            page = pages.get(index)
            if page is None:
                page = PageMetadata(archive_index=index, display_index=index, filename=filename, type="", bookmark="")
                pages[index] = page
            else:
                page.filename = filename
            cover_set = page.type == PageType.FrontCover or cover_set

        self.pages = sorted(pages.values())
        self.page_count = len(self.pages)
        if self.page_count != len(page_list):
            logger.warning("Wrong count of pages: expected %d got %d", len(page_list), self.page_count)
        if self.pages and not cover_set:
            min(self.pages, key=lambda page: page.display_index).type = PageType.FrontCover

    def get_archive_page_index(self, pagenum: int) -> int:
        """convert the displayed page number to the page index of the file in the archive"""
        if pagenum < len(self.pages):
            return int(sorted(self.pages, key=lambda p: p.display_index)[pagenum].archive_index)

        return 0

    def get_cover_page_index_list(self) -> list[int]:
        # return a list of archive page indices of cover pages
        if not self.pages:
            return [0]
        coverlist = []
        for p in self.pages:
            if p.type == PageType.FrontCover:
                coverlist.append(p.archive_index)

        if not coverlist:
            coverlist.append(self.get_archive_page_index(0))

        return coverlist

    @overload
    def add_credit(self, person: Credit) -> None: ...

    @overload
    def add_credit(self, person: str, role: str, primary: bool = False, language: str = "") -> None: ...

    def add_credit(
        self, person: str | Credit, role: str | None = None, primary: bool = False, language: str = ""
    ) -> None:

        credit: Credit
        if isinstance(person, Credit):
            credit = person
        else:
            assert role is not None
            credit = Credit(person=person, role=role, primary=primary, language=language)

        if credit.role is None:
            raise TypeError("GenericMetadata.add_credit takes either a Credit object or a person name and role")
        if credit.person == "":
            return

        person = norm_fold(credit.person)
        role = norm_fold(credit.role)

        for existing in self.credits:
            if norm_fold(existing.person) == person and norm_fold(existing.role) == role:
                existing.primary = existing.primary or credit.primary
                return
        self.credits.append(credit)

    def get_primary_credit(self, role: str) -> Credit | None:
        primary = None
        role = role.casefold()
        for credit in self.credits:
            if (not primary and credit.role.casefold() == role) or (credit.primary and credit.role.casefold() == role):
                primary = credit
        return primary

    def __str__(self) -> str:
        vals: list[tuple[str, Any]] = []
        if self.is_empty:
            return "No metadata"

        def add_string(tag: str, val: Any) -> None:
            if isinstance(val, (Sequence, set)):
                if val:
                    vals.append((tag, val))
            elif val is not None:
                vals.append((tag, val))

        add_string("data_origin", self.data_origin)
        add_string("series", self.series)
        add_string("series_start_year", self.series_start_year)
        add_string("original_hash", self.original_hash)
        add_string("series_aliases", ",".join(self.series_aliases))
        add_string("issue", self.issue)
        add_string("issue_count", self.issue_count)
        add_string("title", self.title)
        add_string("title_aliases", ",".join(self.title_aliases))
        add_string("publisher", self.publisher)
        add_string("year", self.year)
        add_string("month", self.month)
        add_string("day", self.day)
        add_string("volume", self.volume)
        add_string("volume_count", self.volume_count)
        add_string("genres", ", ".join(self.genres))
        add_string("language", self.language)
        add_string("country", self.country)
        add_string("critical_rating", self.critical_rating)
        add_string("alternate_series", self.alternate_series)
        add_string("alternate_number", self.alternate_number)
        add_string("alternate_count", self.alternate_count)
        add_string("imprint", self.imprint)
        add_string("web_links", [str(x) for x in self.web_links])
        add_string("format", self.format)
        add_string("manga", self.manga)
        add_string("gtin", self.gtin)

        add_string("price", self.price)
        add_string("is_version_of", self.is_version_of)
        add_string("rights", self.rights)
        add_string("identifier", self.identifier)
        add_string("last_mark", self.last_mark)

        if self.black_and_white:
            add_string("black_and_white", self.black_and_white)
        add_string("maturity_rating", self.maturity_rating)
        add_string("story_arcs", self.story_arcs)
        add_string("series_groups", self.series_groups)
        add_string("scan_info", self.scan_info)
        add_string("characters", ", ".join(self.characters))
        add_string("teams", ", ".join(self.teams))
        add_string("locations", ", ".join(self.locations))
        add_string("description", self.description)
        add_string("notes", self.notes)

        add_string("tags", ", ".join(self.tags))

        for c in self.credits:
            primary = ""
            if c.primary:
                primary = " [P]"
            add_string("credit", f"{c}{primary}")

        # find the longest field name
        flen = 0
        for i in vals:
            flen = max(flen, len(i[0]))
        flen += 1

        # format the data nicely
        outstr = ""
        fmt_str = "{0: <" + str(flen) + "} {1}\n"
        for i in vals:
            outstr += fmt_str.format(i[0] + ":", i[1])

        return outstr

    def fix_publisher(self) -> None:
        if self.publisher is None:
            return
        if self.imprint is None:
            self.imprint = ""

        imprint, publisher = utils.get_publisher(self.publisher)

        self.publisher = publisher

        if self.imprint.casefold() in publisher.casefold():
            self.imprint = None

        if self.imprint is None or self.imprint == "":
            self.imprint = imprint
        elif self.imprint.casefold() in imprint.casefold():
            self.imprint = imprint


__all__ = (
    "Url",
    "parse_url",
    "PageType",
    "PageMetadata",
    "Credit",
    "ComicSeries",
    "MetadataOrigin",
    "GenericMetadata",
)
