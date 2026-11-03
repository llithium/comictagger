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

import html
import logging
import posixpath
import re
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


def fix_url(url: str | None) -> str:
    if not url:
        return ""
    tmp_url = urlsplit(url)
    new_path = posixpath.normpath(tmp_url.path)
    if new_path in (".", "/"):
        new_path = ""
    # joinurl only works properly if there is a trailing slash
    tmp_url = tmp_url._replace(path=new_path + "/")
    return tmp_url.geturl()


def cleanup_html(string: str | None, remove_html_tables: bool = False) -> str:
    """Cleans HTML code from any text. Will remove any HTML tables with remove_html_tables"""
    if string is None:
        return ""
    if "<" not in string:
        return string
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(string, "html.parser")
    for table in soup.find_all("table"):
        # A nested table is included in its outer cell's readable text.
        if table.find_parent("table") is not None:
            continue
        if remove_html_tables:
            table.decompose()
            continue
        try:
            rows = []
            header_rows = []
            for row in table.find_all("tr"):
                if row.find_parent("table") is not table:
                    continue
                cells = row.find_all(["th", "td"], recursive=False)
                if cells:
                    rows.append([cell.get_text(" ", strip=True) for cell in cells])
                    header_rows.append(all(cell.name == "th" for cell in cells))
            if not rows:
                table.replace_with(table.get_text(" ", strip=True))
                continue
            widths = [max(len(row[i]) if i < len(row) else 0 for row in rows) for i in range(max(map(len, rows)))]
            lines = []
            for row, is_header in zip(rows, header_rows):
                row = row + [""] * (len(widths) - len(row))
                lines.append("|" + "".join(f" {cell:{width + 1}}|" for cell, width in zip(row, widths)))
                if is_header:
                    lines.append("|" + "".join("-" * (width + 2) + "|" for width in widths))
            table.replace_with("\n".join(lines) + "\n\n")
        except Exception:
            logger.exception("table parse error")
            table.replace_with(table.get_text(" ", strip=True))

    # Add text markers before stripping the remaining HTML tags.
    string = str(soup)
    string = re.sub(r"<br\s*/?>|</li>", "\n", string, flags=re.IGNORECASE)
    string = re.sub(r"<li(?:\s[^>]*)?>", "* ", string, flags=re.IGNORECASE)
    string = re.sub(r"</p>", "\n\n", string, flags=re.IGNORECASE)
    string = re.sub(r"<h([1-6])(?:\s[^>]*)?>", lambda m: "#" * int(m.group(1)) + " ", string, flags=re.IGNORECASE)
    string = re.sub(r"</h[1-6]>", "\n", string, flags=re.IGNORECASE)
    if remove_html_tables:
        string = string.replace("*List of covers and their creators:*", "")
    string = re.sub(r"<[^<]*?>", "", string)
    return html.unescape(string).replace("\xa0", " ").strip()
