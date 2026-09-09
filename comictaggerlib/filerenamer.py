"""Functions for renaming files based on metadata"""

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

import calendar
import datetime
import logging
import os
import pathlib
import re
import string
import sys
import unicodedata
from collections.abc import Collection, Iterable, Mapping, Sequence, Sized
from typing import Any, cast

from pathvalidate import Platform, normalize_platform, sanitize_filename

from comicapi.comicarchive import ComicArchive
from comicapi.genericmetadata import GenericMetadata
from comicapi.issuestring import IssueString
from comictaggerlib.defaults import DEFAULT_REPLACEMENTS, Replacement, Replacements

logger = logging.getLogger(__name__)


STANDARD_CREDIT_ROLES = ("writer", "penciller", "inker", "colorist", "letterer", "cover artist", "editor", "translator")


# These are Kapowarr-compatible archive filename formats. Keeping them here,
# rather than duplicating a second formatter, means preview, GUI and CLI all
# use the same naming and filesystem-safety path.
KAPOWARR_FILE_TEMPLATE = "{series_name} ({year}) Volume {volume_number} Issue {issue_number}"
KAPOWARR_SPECIAL_TEMPLATE = "{series_name} ({year}) Volume {volume_number} {special_version}"
KAPOWARR_VOLUME_AS_ISSUE_TEMPLATE = "{series_name} ({year}) Volume {issue_number}"

KAPOWARR_SPECIAL_VERSIONS = {
    "tpb": ("TPB", "TPB"),
    "trade paperback": ("TPB", "TPB"),
    "one shot": ("OS", "One-Shot"),
    "one-shot": ("OS", "One-Shot"),
    "os": ("OS", "One-Shot"),
    "hard cover": ("HC", "Hard-Cover"),
    "hard-cover": ("HC", "Hard-Cover"),
    "hardcover": ("HC", "Hard-Cover"),
    "hc": ("HC", "Hard-Cover"),
    "omnibus": ("Omnibus", "Omnibus"),
}
KAPOWARR_VOLUME_AS_ISSUE_FORMATS = {"vai", "volume as issue", "volume-as-issue"}
KAPOWARR_VOLUME_AS_ISSUE_TITLE = re.compile(
    r"^v(?:ol(?:ume)?)?\.?\s(?:\d+|(?:(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)[-\s]{0,1})+)(?:\:\s|$)",
    re.IGNORECASE,
)
KAPOWARR_SIMPLE_FILENAME_CLEANER = re.compile(r'(<|>|(?<!^\w):|"|\||\?|\*|\x00|(?:\s|\.)+$)')


def get_rename_dir(ca: ComicArchive, rename_dir: str | pathlib.Path | None) -> pathlib.Path:
    folder = ca.path.parent.absolute()
    if rename_dir is not None:
        if isinstance(rename_dir, str):
            rename_dir = pathlib.Path(rename_dir.strip())
        folder = rename_dir.absolute()
    return folder


def _isnamedtupleinstance(x: Any) -> bool:  # pragma: no cover
    t = type(x)
    b = t.__bases__

    if len(b) != 1 or b[0] != tuple:
        return False

    f = getattr(t, "_fields", None)
    if not isinstance(f, tuple):
        return False

    return all(isinstance(n, str) for n in f)


class MetadataFormatter(string.Formatter):
    def __init__(
        self, smart_cleanup: bool = False, platform: str = "auto", replacements: Replacements = DEFAULT_REPLACEMENTS
    ) -> None:
        super().__init__()
        self.smart_cleanup = smart_cleanup
        self.platform = normalize_platform(platform)
        self.replacements = replacements
        self.warnings: list[str] = []

    def format_field(self, value: Any, format_spec: str) -> str:
        if value is None or value == "":
            return ""
        return cast(str, super().format_field(value, format_spec))

    def convert_field(self, value: Any, conversion: str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, Iterable) and not isinstance(value, (str, tuple)):
            if conversion == "C":
                if isinstance(value, Sized):
                    return str(len(value))
                return ""
            if conversion and conversion.isdecimal():
                if not isinstance(value, Collection):
                    return ""
                i = int(conversion)
                if i < len(value):
                    try:
                        return sorted(value)[i]
                    except Exception:
                        ...
                    return list(value)[i]
                return ""
            reverse = False
            if conversion == "R":
                reverse = True
                conversion = "s"
            if conversion == "j":
                conversion = "s"
            try:
                value = sorted((v for v in value if v is not None), reverse=reverse)
            except Exception:
                ...
            return ", ".join(list(str(self.convert_field(v, conversion)) for v in value if v is not None))
        if not conversion:
            return cast(str, super().convert_field(value, conversion))
        if conversion == "u":
            return str(value).upper()
        if conversion == "l":
            return str(value).casefold()
        if conversion == "c":
            return str(value).capitalize()
        if conversion == "S":
            return str(value).swapcase()
        if conversion == "t":
            return str(value).title()
        if conversion.isdecimal():
            return ""
        return cast(str, super().convert_field(value, conversion))

    def handle_replacements(self, string: str, replacements: list[Replacement]) -> str:
        for find, replace, strict_only in replacements:
            if self.is_strict() or not strict_only:
                string = string.replace(find, replace)
        return string

    def __get_object(self, original: str, field_name: str, args: Sequence[Any], kwargs: Mapping[str, Any]) -> str:
        if field_name.startswith("_"):
            return field_name[1:]
        if field_name not in kwargs or field_name == original:
            return field_name
        try:
            obj, arg_used = self.get_field(field_name, args, kwargs)
        except Exception:
            obj = field_name
        return obj

    def none_replacement(
        self,
        value: Any,
        field_name: str,
        replacement: str,
        r: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
    ) -> Any:
        if r == "-" and value is None or value == "":
            return self.__get_object(field_name, replacement, args, kwargs)
        if r == "+" and value is not None:
            return self.__get_object(field_name, replacement, args, kwargs)
        return value

    def split_replacement(self, field_name: str) -> tuple[str, str, str]:
        pos_index = field_name.index("+") if "+" in field_name else sys.maxsize
        neg_index = field_name.index("-") if "-" in field_name else sys.maxsize
        if neg_index < pos_index:
            return field_name.partition("-")
        if pos_index < neg_index:
            return field_name.partition("+")
        return field_name, "", ""

    def is_strict(self) -> bool:
        return self.platform in [Platform.UNIVERSAL, Platform.WINDOWS]

    def _re_format(self, field_name: str, format_spec: str | None, conversion: str | None) -> str:
        s = "{" + field_name
        if conversion:
            s += "!" + conversion
        if format_spec:
            s += ":" + format_spec
        return s + "}"

    def _vformat(
        self,
        format_string: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        used_args: set[Any],
        recursion_depth: int,
        auto_arg_index: int = 0,
    ) -> tuple[str, int]:
        if recursion_depth < 0:
            raise ValueError("Max string recursion exceeded")
        result = []
        lstrip = False
        for literal_text, field_name, format_spec, conversion in self.parse(format_string):
            # output the literal text
            if literal_text:
                if lstrip:
                    literal_text = literal_text.lstrip("-_)}]#")
                if self.smart_cleanup:
                    literal_text = self.handle_replacements(literal_text, self.replacements.literal_text)
                    lspace = literal_text[0].isspace() if literal_text else False
                    rspace = literal_text[-1].isspace() if literal_text else False
                    literal_text = " ".join(literal_text.split())
                    if literal_text == "":
                        literal_text = " "
                    else:
                        if lspace:
                            literal_text = " " + literal_text
                        if rspace:
                            literal_text += " "
                result.append(literal_text)

            lstrip = False
            # if there's not a field, skip to the next item
            if not field_name:
                continue

            field_name, r, replacement = self.split_replacement(field_name)
            field_name = field_name.casefold()
            # Needs to happen before self.get_field. Otherwise errors will swallow this warning
            if field_name.endswith("]"):
                self.warnings.append(
                    "You appear to be trying to get an item from a list instead of {story_arc[2]} use {story_arc!2}"
                )

            # Disallow index based fields
            if field_name.isdigit():
                raise ValueError("cannot use a number as a field name")

            # given the field_name, find the object it references
            #  and the argument it came from
            try:
                obj, arg_used = self.get_field(field_name, args, kwargs)
                used_args.add(arg_used)
                if arg_used in STANDARD_CREDIT_ROLES:
                    self.warnings.append(f"Please use {{credit_{arg_used}}} instead of {{{arg_used}}}")
                # this is an error specifically so that mising fields show an obvious error.
                if arg_used not in kwargs:
                    result.append(self._re_format(f"{field_name}{r}{replacement}", format_spec, conversion))
                    continue
            except Exception:
                result.append(self._re_format(f"{field_name}{r}{replacement}", format_spec, conversion))
                continue

            obj = self.none_replacement(obj, field_name, replacement, r, args, kwargs)
            # do any conversion on the resulting object
            obj = self.convert_field(obj, conversion)
            if r == "-":
                obj = self.none_replacement(obj, field_name, replacement, r, args, kwargs)

            # expand the format spec, if needed
            format_spec, _ = self._vformat(
                cast(str, format_spec), args, kwargs, used_args, recursion_depth - 1, auto_arg_index=False
            )

            # format the object and append to the result
            fmt_obj = self.format_field(obj, format_spec)
            if fmt_obj == "" and result and self.smart_cleanup:

                if self.str_contains(result[-1], "({["):
                    lstrip = True  # trailing braces are handled above

                if result[-1].startswith(" "):
                    result[-1] = ""  # handles `v{volume}` where volume is None

                result[-1] = self.rstrip(result[-1])  # cleans up opening punctuation, spaces, dashes
            if self.smart_cleanup:
                # colons and slashes get special treatment
                fmt_obj = self.handle_replacements(fmt_obj, self.replacements.format_value)
                fmt_obj = self.strip_internal(fmt_obj)
            result.append(fmt_obj)

        return "".join(result), False

    def str_contains(self, chars: str, string: str) -> bool:
        for char in chars:
            if char in string:
                return True
        return False

    def rstrip(self, string: str) -> str:
        while string:
            r = string[-1]
            if unicodedata.category(r) in ("Po", "Ps", "Pd", "Zl", "Zp", "Zs"):
                string = string[:-1]
            else:
                break
        return string

    def strip_internal(self, string: str) -> str:
        s = list(string)
        p = False
        for i, x in reversed(list(enumerate(s))):
            if p and x.isspace():
                del s[i]
            p = x.isspace()
        return "".join(s)


class FileRenamer:
    def __init__(
        self,
        metadata: GenericMetadata | None,
        platform: str = "auto",
        replacements: Replacements = DEFAULT_REPLACEMENTS,
    ) -> None:
        self.template = "{publisher}/{series}/{series} v{volume} #{issue} (of {issue_count}) ({year})"
        self.smart_cleanup = True
        self.issue_zero_padding = 3
        self.metadata = metadata or GenericMetadata()
        self.move = False
        self.platform = platform
        self.replacements = replacements
        self.original_name = ""
        self.move_only = False
        self.warnings: list[str] = []
        self.kapowarr_naming = False
        self.kapowarr_long_special_versions = False

    def set_metadata(self, metadata: GenericMetadata, original_name: str) -> None:
        self.metadata = metadata
        self.original_name = original_name

    def set_issue_zero_padding(self, count: int) -> None:
        self.issue_zero_padding = count

    def set_smart_cleanup(self, on: bool) -> None:
        self.smart_cleanup = on

    def set_template(self, template: str) -> None:
        self.template = template

    def set_kapowarr_naming(self, enabled: bool, long_special_versions: bool = False) -> None:
        """Enable Kapowarr's stock library layout and filename rules.

        The profile deliberately only uses embedded ComicInfo metadata.  It
        never queries or changes a Kapowarr database, so it is safe for files
        that have not been imported into Kapowarr yet.
        """
        self.kapowarr_naming = enabled
        self.kapowarr_long_special_versions = long_special_versions

    @staticmethod
    def _clean_series_name(series: str | None) -> str | None:
        if not series:
            return series
        for prefix in ("The ", "A "):
            if series.startswith(prefix):
                return f"{series[len(prefix):]}, {prefix.strip()}"
        return series

    def _kapowarr_values(self, md: GenericMetadata) -> dict[str, Any]:
        issue = IssueString(md.issue).as_string(pad=self.issue_zero_padding)
        issue_release_date = None
        if md.year is not None and md.month is not None and md.day is not None:
            issue_release_date = f"{md.year:04d}-{md.month:02d}-{md.day:02d}"

        # ComicInfo's Volume field is commonly absent for an ordinary comic
        # series. Kapowarr-compatible filenames still need the series volume,
        # where the conventional first volume is 01.
        volume_number = str(md.volume if md.volume is not None else 1).zfill(2)

        return {
            "series_name": self._kapowarr_clean_filestring(md.series),
            "clean_series_name": self._clean_series_name(md.series),
            "volume_number": volume_number,
            "comicvine_id": md.series_id,
            "issue_comicvine_id": md.issue_id,
            "issue_number": issue,
            "issue_release_date": issue_release_date,
            "issue_release_year": md.year,
            "issue_title": md.title,
            "special_version": None,
        }

    def _kapowarr_template(self, md: GenericMetadata, values: dict[str, Any]) -> str:
        comic_format = (md.format or "").strip().casefold()
        if comic_format in KAPOWARR_VOLUME_AS_ISSUE_FORMATS or KAPOWARR_VOLUME_AS_ISSUE_TITLE.search(md.title or ""):
            # Kapowarr identifies Volume-As-Issue volumes when every Comic
            # Vine issue title is "Volume N". A tagged archive only contains
            # one title, so use that same recognizable signal when Format was
            # not persisted. Its VAI template uses the normal issue padding.
            return KAPOWARR_VOLUME_AS_ISSUE_TEMPLATE

        if comic_format in KAPOWARR_SPECIAL_VERSIONS:
            short, long = KAPOWARR_SPECIAL_VERSIONS[comic_format]
            values["special_version"] = long if self.kapowarr_long_special_versions else short
            return KAPOWARR_SPECIAL_TEMPLATE

        return KAPOWARR_FILE_TEMPLATE

    @staticmethod
    def _kapowarr_clean_filestring(value: str | None) -> str | None:
        if value is None:
            return None
        # Mirror Kapowarr's simple filename cleaner: remove illegal punctuation
        # rather than replacing it with ComicTagger's dash rules.
        value = value.replace("/", "").replace("\\", "")
        return KAPOWARR_SIMPLE_FILENAME_CLEANER.sub("", value).strip()

    def determine_name(self, ext: str) -> str:
        class Default(dict[str, Any]):
            def __missing__(self, key: str) -> str | None:
                if key.startswith("credit_"):
                    self[key] = None
                    return None
                return "{" + key + "}"

        self.warnings.clear()

        if self.kapowarr_naming and self.move_only:
            raise ValueError("Kapowarr-compatible naming cannot be combined with Only Move")

        md = self.metadata

        template = self.template

        new_name = ""

        fmt = MetadataFormatter(self.smart_cleanup, platform=self.platform, replacements=self.replacements)
        md_dict = dict(vars(md))
        md_dict.update(
            dict(
                month_name=None,
                month_abbr=None,
                date=None,
                genre=None,
                story_arc=None,
                series_group=None,
                web_link=None,
                character=None,
                team=None,
                location=None,
            )
        )

        md_dict["issue"] = IssueString(md.issue).as_string(pad=self.issue_zero_padding)
        # Kapowarr names can also be used as ordinary ComicTagger templates.
        # This makes it possible to customise the profile without forking the
        # formatter a second time.
        md_dict.update(self._kapowarr_values(md))

        if (isinstance(md.month, int) or isinstance(md.month, str) and md.month.isdigit()) and 0 < int(md.month) < 13:
            md_dict["month_name"] = calendar.month_name[int(md.month)]
            md_dict["month_abbr"] = calendar.month_abbr[int(md.month)]

        if md.year is not None and datetime.MINYEAR <= md.year <= datetime.MAXYEAR:
            md_dict["date"] = datetime.datetime(year=md.year, month=md.month or 1, day=md.day or 1)

        if md.genres:
            md_dict["genre"] = sorted(md.genres)[0]
        if md.story_arcs:
            md_dict["story_arc"] = md.story_arcs[0]
        if md.series_groups:
            md_dict["series_group"] = md.series_groups[0]
        if md.web_links:
            md_dict["web_link"] = md.web_links[0]
        if md.characters:
            md_dict["character"] = sorted(md.characters)[0]
        if md.teams:
            md_dict["team"] = sorted(md.teams)[0]
        if md.locations:
            md_dict["location"] = sorted(md.locations)[0]

        for role in {c.role.casefold() for c in md.credits}:
            if f"credit_{role}" in md_dict:
                continue
            credit = md.get_primary_credit(role)
            if credit is None:
                continue
            if role in STANDARD_CREDIT_ROLES:
                md_dict[role] = credit.person
            md_dict[f"credit_{role}"] = credit.person
            md_dict[f"credit_item_{role}"] = credit

        # Ensure standard credit roles are always defined
        for role in STANDARD_CREDIT_ROLES:
            if role not in md_dict:
                md_dict[role] = None
                md_dict[f"credit_{role}"] = None
                md_dict[f"credit_item_{role}"] = None

        if self.kapowarr_naming:
            # Kapowarr substitutes these labels instead of silently creating
            # blank path components when incomplete tags are previewed.
            md_dict.update(
                {
                    "series_name": md_dict["series_name"] or "Unknown",
                    "year": (
                        md_dict["series_start_year"]
                        if md_dict["series_start_year"] is not None
                        else md_dict["year"] if md_dict["year"] is not None else "Unknown Year"
                    ),
                    "volume_number": md_dict["volume_number"] or "Unknown",
                }
            )
            template = self._kapowarr_template(md, md_dict)

        new_basename = ""
        for component in pathlib.PureWindowsPath(template).parts:
            new_component = fmt.vformat(component, args=[], kwargs=Default(md_dict))
            self.warnings.extend(fmt.warnings)
            new_basename = str(sanitize_filename(new_component, platform=self.platform)).strip()
            new_name = os.path.join(new_name, new_basename)

        if self.move_only:
            new_folder = os.path.join(new_name, os.path.splitext(self.original_name)[0])
            return new_folder + ext
        if self.move or self.kapowarr_naming:
            return new_name.strip() + ext
        return new_basename.strip() + ext
