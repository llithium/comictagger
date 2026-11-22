"""A PyQt6 widget for managing list of comic archive files"""

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

import logging
import os
import pathlib
import platform
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import cast

from PyQt6 import QtCore, QtGui, QtWidgets, uic

from comicapi import utils
from comicapi.comicarchive import ComicArchive
from comicapi.genericmetadata import GenericMetadata
from comictaggerlib.ctsettings import ct_ns
from comictaggerlib.graphics import graphics_path
from comictaggerlib.optionalmsgdialog import OptionalMessageDialog
from comictaggerlib.resulttypes import OnlineMatchResults
from comictaggerlib.ui import ui_path
from comictaggerlib.ui.qtutils import center_window_on_parent
from comictaggerlib.ui.rarhelp import LINUX_RAR_HELP, MAC_RAR_HELP, WINDOWS_RAR_HELP
from comictaggerlib.workspacestyle import DEFAULT_COLORS, ElidedLabel, Painter, ThumbnailCache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedPathItem:
    archive: ComicArchive
    archive_type: str
    tags: tuple[str, ...]
    writable: bool


def prepare_path_item(path: str, nocover_path: str, preferred_hash: str) -> PreparedPathItem | None:
    archive = ComicArchive(os.path.abspath(path), nocover_path, hash_archive=preferred_hash)
    if not archive.seems_to_be_a_comic_archive():
        return None

    return PreparedPathItem(
        archive=archive,
        archive_type=archive.archiver.name(),
        tags=tuple(tag for tag in archive.get_supported_tags() if archive.has_tags(tag)),
        writable=archive.is_writable(),
    )


class PathLoadThread(QtCore.QThread):
    progress = QtCore.pyqtSignal(str)
    loaded = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(object)

    def __init__(self, paths: list[str], nocover_path: str, preferred_hash: str, recursive: bool) -> None:
        super().__init__()
        self.paths = paths
        self.nocover_path = nocover_path
        self.preferred_hash = preferred_hash
        self.recursive = recursive

    def run(self) -> None:
        try:
            files = utils.get_recursive_filelist(self.paths) if self.recursive else self.paths
            prepared_items = []
            for path in files:
                if self.isInterruptionRequested():
                    return
                self.progress.emit(path)
                prepared = prepare_path_item(path, self.nocover_path, self.preferred_hash)
                if prepared is not None:
                    prepared_items.append(prepared)
            if not self.isInterruptionRequested():
                self.loaded.emit(prepared_items)
        except Exception as error:
            logger.exception("Failed while loading comic paths")
            if not self.isInterruptionRequested():
                self.error.emit(error)


class _CardInfoSignals(QtCore.QObject):
    loaded = QtCore.pyqtSignal(str, str)


class _CardInfoJob(QtCore.QRunnable):
    """Reads an archive's tags off the main thread, for the series and issue a card shows."""

    def __init__(self, path: pathlib.Path, config: ct_ns, signals: _CardInfoSignals) -> None:
        super().__init__()
        self.path = path
        self.config = config
        self.signals = signals

    def run(self) -> None:
        title = ""
        try:
            from comictaggerlib.md import read_configured_tags

            archive = ComicArchive(self.path)
            tag_ids = [tag for tag in self.config.Runtime_Options__tags_read if archive.has_tags(tag)]
            if tag_ids:
                metadata, _, _error = read_configured_tags(archive, tag_ids, self.config)
                title = card_title(metadata)
        except Exception:
            logger.debug("Could not read tags for %s", self.path, exc_info=True)
        try:
            self.signals.loaded.emit(str(self.path), title)
        except RuntimeError:
            pass  # the list was closed while this archive was being read


def card_title(metadata: GenericMetadata) -> str:
    """'Series #Issue of Count', the way the editor's header names a comic."""
    if not metadata.series:
        return ""
    title = metadata.series
    if metadata.issue:
        title += f" #{metadata.issue}"
        if metadata.issue_count:
            title += f" of {metadata.issue_count}"
    elif metadata.volume:
        title += f" v{metadata.volume}"
    return title


# Auto-Tag outcomes shown in the Match column, and the chip colour each gets in the card view.
MATCH_TONES = {
    "Matched": "ok",
    "Manual match": "ok",
    "Search match": "ok",
    "Fixed by hand": "ok",
    "Multiple": "warn",
    "Low confidence": "warn",
    "No match": "bad",
    "Fetch error": "bad",
    "Write error": "bad",
    "Read error": "bad",
}


def wrap_lines(text: str, metrics: QtGui.QFontMetrics, width: int, limit: int) -> list[str]:
    """Break text into at most ``limit`` lines that fit ``width``, eliding the end of the last one."""
    lines: list[str] = []
    words = text.split(" ")
    current = ""
    while words:
        candidate = f"{current} {words[0]}".strip()
        if metrics.horizontalAdvance(candidate) <= width or not current:
            current = candidate
            words.pop(0)
            continue
        lines.append(current)
        current = ""
        if len(lines) == limit - 1:
            break
    rest = " ".join(([current] if current else []) + words).strip()
    if rest:
        lines.append(metrics.elidedText(rest, QtCore.Qt.TextElideMode.ElideRight, width))
    return [metrics.elidedText(line, QtCore.Qt.TextElideMode.ElideRight, width) for line in lines[:limit]]


class FileCardDelegate(QtWidgets.QStyledItemDelegate):
    """Card rows for the file list: a cover thumbnail, the file name and status chips."""

    def __init__(self, file_list: FileSelectionList) -> None:
        super().__init__(file_list)
        self.file_list = file_list
        self.draw = Painter(file_list)

    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> QtCore.QSize:
        return QtCore.QSize(220, self.file_list.card_height())

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> None:
        archive: ComicArchive | None = index.data(QtCore.Qt.ItemDataRole.UserRole)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(option.rect, self.draw.color("surface"))
        self.draw.background(painter, option, 4)
        rect = option.rect.adjusted(12, 7, -10, -7)
        thumb = QtCore.QRect(rect.left(), rect.top(), int(rect.height() * 2 / 3), rect.height())
        self.draw.thumbnail(painter, thumb, self.file_list.thumbs.get(archive.path) if archive else None)
        left = thumb.right() + 10
        width = rect.right() - left
        title, filename = self.file_list.card_text(index.row())

        # Series and issue first, on up to two lines so the issue number at the end stays visible.
        # When that fits on one line, the file name fills the second, so similar files stay distinguishable.
        bold = QtGui.QFont(option.font)
        bold.setWeight(QtGui.QFont.Weight.DemiBold)
        bold_metrics = QtGui.QFontMetrics(bold)
        painter.setFont(bold)
        painter.setPen(self.draw.color("ink"))
        lines = wrap_lines(title, bold_metrics, width, 2)
        y = rect.top() + bold_metrics.ascent()
        for number, line in enumerate(lines):
            painter.drawText(left, y, line)
            if number + 1 < len(lines):
                y += bold_metrics.lineSpacing()
        small = QtGui.QFont(option.font)
        small.setPointSizeF(max(option.font.pointSizeF() * 0.88, 7))
        small_metrics = QtGui.QFontMetrics(small)
        if len(lines) < 2 and filename != title:
            painter.setFont(small)
            painter.setPen(self.draw.color("muted"))
            y += bold_metrics.descent() + 2 + small_metrics.ascent()
            painter.drawText(left, y, small_metrics.elidedText(filename, QtCore.Qt.TextElideMode.ElideMiddle, width))
            y += small_metrics.descent()
        else:
            y += bold_metrics.descent()

        x = float(left)
        chip_top = y + 5
        for text, tone in self.file_list.statuses(index.row()):
            if x > rect.right() - 30:
                break
            x += self.draw.chip(painter, x, chip_top, text, tone, option.font) + 6
        painter.restore()


class FileSelectionList(QtWidgets.QWidget):
    selectionChanged = QtCore.pyqtSignal(QtCore.QVariant)
    listCleared = QtCore.pyqtSignal()

    fileColNum = 0
    MDFlagColNum = 1
    typeColNum = 2
    readonlyColNum = 3
    matchColNum = 4
    folderColNum = 5
    dataColNum = fileColNum

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        config: ct_ns,
        dirty_flag_verification: Callable[[str, str], bool],
        review_blank_draft: Callable[[ComicArchive], bool] | None = None,
    ) -> None:
        super().__init__(parent)

        with (ui_path / "fileselectionlist.ui").open(encoding="utf-8") as uifile:
            uic.loadUi(uifile, self)

        self.config = config
        self.twList: QtWidgets.QTableWidget
        self.twList.verticalHeader().hide()
        self.twList.setShowGrid(False)
        header = self.twList.horizontalHeader()
        header.setMinimumSectionSize(54)
        self.twList.setColumnWidth(self.fileColNum, 70 * self.twList.fontMetrics().averageCharWidth())
        header.setSectionResizeMode(self.MDFlagColNum, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.twList.setColumnWidth(self.folderColNum, 260)
        self.twList.currentItemChanged.connect(self.current_item_changed_cb)
        self.twList.horizontalScrollBar().rangeChanged.connect(self.update_minimum_height)

        self.currentItem = None
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.ActionsContextMenu)
        self.dirty_flag = False

        select_all_action = QtGui.QAction("Select All", self)
        remove_action = QtGui.QAction("Remove Selected Items", self)
        reveal_action = QtGui.QAction(self.reveal_action_text(), self)
        self.separator = QtGui.QAction("", self)
        self.separator.setSeparator(True)

        select_all_action.setShortcut("Ctrl+A")
        remove_action.setShortcut("Backspace" if platform.system() == "Darwin" else "Delete")

        select_all_action.triggered.connect(self.select_all)
        remove_action.triggered.connect(self.remove_selection)
        reveal_action.triggered.connect(self.reveal_current_archive)

        self.addAction(select_all_action)
        self.addAction(remove_action)
        self.addAction(reveal_action)
        self.addAction(self.separator)

        self.loaded_paths: set[pathlib.Path] = set()

        self.dirty_flag_verification = dirty_flag_verification
        self.review_blank_draft = review_blank_draft
        self.rar_ro_shown = False
        self.path_load_threads: set[PathLoadThread] = set()
        self.path_load_dialogs: dict[PathLoadThread, QtWidgets.QProgressDialog] = {}
        self._verifying_draft_transition = False
        self._deferred_path_loads: list[list[PreparedPathItem]] = []
        self._setup_card_view()

    # ----- card view -----

    SORT_CHOICES = (
        ("Name", fileColNum),
        ("Folder", folderColNum),
        ("Tags", MDFlagColNum),
        ("Type", typeColNum),
        ("Read-only", readonlyColNum),
        ("Auto-Tag result", matchColNum),
    )

    def _setup_card_view(self) -> None:
        self.colors = dict(DEFAULT_COLORS)
        self.thumbs = ThumbnailCache(self, 112)
        self.thumbs.changed.connect(self.twList.viewport().update)
        self.card_delegate = FileCardDelegate(self)
        self.table_delegate = QtWidgets.QStyledItemDelegate(self)
        self.twList.setMouseTracking(True)

        self.listTitle = ElidedLabel()
        self.listTitle.setObjectName("fileListTitle")
        self.listTitle.set_full_text("FILES")
        # A menu button rather than a combo box: a native combo pops up over the toolbar and clips its items.
        self.sortButton = QtWidgets.QToolButton()
        self.sortButton.setObjectName("fileSort")
        self.sortButton.setAccessibleName("Sort files")
        self.sortButton.setToolTip("Sort files")
        self.sortButton.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.sortButton.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.sortMenu = QtWidgets.QMenu(self.sortButton)
        self.sortMenu.addSection("Sort by")
        self.sortActions = QtGui.QActionGroup(self)
        for label, column in self.SORT_CHOICES:
            action = self.sortMenu.addAction(label)
            action.setCheckable(True)
            action.setData(column)
            self.sortActions.addAction(action)
        self.sortMenu.addSeparator()
        self.descendingAction = self.sortMenu.addAction("Descending")
        self.descendingAction.setCheckable(True)
        self.sortActions.triggered.connect(lambda action: self.sort_by(int(action.data())))
        self.descendingAction.triggered.connect(self._descending_toggled)
        self.sortButton.setMenu(self.sortMenu)
        self.twList.horizontalHeader().sortIndicatorChanged.connect(self._sort_indicator_changed)

        self.filterEdit = QtWidgets.QLineEdit()
        self.filterEdit.setObjectName("fileFilter")
        self.filterEdit.setPlaceholderText("Filter files")
        self.filterEdit.setClearButtonEnabled(True)
        self.filterEdit.setAccessibleName("Filter files")
        self.filterEdit.textChanged.connect(self.apply_filter)

        self.btnCards = QtWidgets.QToolButton()
        self.btnTable = QtWidgets.QToolButton()
        group = QtWidgets.QButtonGroup(self)
        for button, text, tip in (
            (self.btnCards, "Cards", "Show files as cards with covers"),
            (self.btnTable, "Table", "Show files as a table with columns"),
        ):
            button.setText(text)
            button.setToolTip(tip)
            button.setCheckable(True)
            button.setObjectName("viewToggle")
            group.addButton(button)
        self.btnCards.toggled.connect(self._view_toggled)

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        top.addWidget(self.listTitle, 1)
        top.addWidget(self.sortButton)
        tools = QtWidgets.QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(6)
        tools.addWidget(self.filterEdit, 1)
        toggle = QtWidgets.QHBoxLayout()
        toggle.setSpacing(0)
        toggle.addWidget(self.btnCards)
        toggle.addWidget(self.btnTable)
        tools.addLayout(toggle)

        outer = self.layout()
        assert outer is not None
        outer.removeWidget(self.twList)
        column = QtWidgets.QVBoxLayout()
        column.setSpacing(8)
        column.addLayout(top)
        column.addLayout(tools)
        column.addWidget(self.twList, 1)
        cast(QtWidgets.QBoxLayout, outer).addLayout(column)

        self._card_titles: dict[str, str] = {}
        self._card_pool = QtCore.QThreadPool(self)
        self._card_pool.setMaxThreadCount(1)
        self._card_signals = _CardInfoSignals(self)
        self._card_signals.loaded.connect(self._card_title_loaded)
        self._sort_indicator_changed(*self.get_sorting())

        self.card_view = False
        cards = getattr(self.config, "internal__file_list_view", "cards") != "table"
        (self.btnCards if cards else self.btnTable).setChecked(True)
        self.set_card_view(cards)
        # Rows are filled in after they're inserted, so update the title once the batch is done.
        self._title_timer = QtCore.QTimer(self)
        self._title_timer.setSingleShot(True)
        self._title_timer.setInterval(0)
        self._title_timer.timeout.connect(self._rows_changed)
        self.twList.model().rowsInserted.connect(self._title_timer.start)
        self.twList.model().rowsRemoved.connect(self._title_timer.start)

    def _view_toggled(self, cards: bool) -> None:
        self.set_card_view(cards)

    def card_height(self) -> int:
        return max(74, round(self.twList.fontMetrics().height() * 3.3) + 24)

    def set_colors(self, colors: dict[str, str]) -> None:
        self.colors = dict(colors)
        self.twList.viewport().update()

    def set_card_view(self, cards: bool) -> None:
        """Switch between cover cards (one column) and the full table of columns."""
        if cards == self.card_view and self.twList.itemDelegateForColumn(self.fileColNum) is not None:
            return
        self.card_view = cards
        if hasattr(self.config, "internal__file_list_view"):
            self.config.internal__file_list_view = "cards" if cards else "table"
        header = self.twList.horizontalHeader()
        rows = self.twList.verticalHeader()
        for column in range(1, self.twList.columnCount()):
            self.twList.setColumnHidden(column, cards)
        header.setVisible(not cards)
        if cards:
            self.twList.setItemDelegateForColumn(self.fileColNum, self.card_delegate)
            header.setSectionResizeMode(self.fileColNum, QtWidgets.QHeaderView.ResizeMode.Stretch)
            rows.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Fixed)
            rows.setDefaultSectionSize(self.card_height())
            self.twList.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        else:
            self.twList.setItemDelegateForColumn(self.fileColNum, self.table_delegate)
            header.setSectionResizeMode(self.fileColNum, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.twList.setColumnWidth(self.fileColNum, 70 * self.twList.fontMetrics().averageCharWidth())
            rows.setDefaultSectionSize(self.twList.fontMetrics().height() + 10)
            self.twList.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.twList.setProperty("cards", cards)
        style = self.twList.style()
        if style is not None:
            style.unpolish(self.twList)
            style.polish(self.twList)
        self.update_minimum_height()

    def statuses(self, row: int) -> list[tuple[str, str]]:
        """The chips a card shows for a row: unsaved edits, read-only, the Auto-Tag result and tags."""
        chips: list[tuple[str, str]] = []
        if self.dirty_flag and row == self.twList.currentRow():
            chips.append(("Unsaved", "acc"))
        readonly = self.twList.item(row, self.readonlyColNum)
        if readonly is not None and readonly.data(QtCore.Qt.ItemDataRole.UserRole):
            chips.append(("Read-only", "bad"))
        match = self.twList.item(row, self.matchColNum)
        match_text = match.text() if match is not None else ""
        if match_text:
            chips.append((match_text, MATCH_TONES.get(match_text, "warn")))
        tagged = self.twList.item(row, self.MDFlagColNum)
        if tagged is not None and tagged.text().strip():
            if MATCH_TONES.get(match_text) != "ok":
                chips.append(("Tagged", "ok"))
        else:
            chips.append(("No tags", "muted"))
        return chips

    def apply_filter(self, text: str | None = None) -> None:
        needle = (self.filterEdit.text() if text is None else text).casefold().strip()
        for row in range(self.twList.rowCount()):
            item = self.twList.item(row, self.fileColNum)
            archive = self.get_archive_by_row(row)
            title = self._card_titles.get(str(archive.path), "") if archive is not None else ""
            text = f"{item.text() if item is not None else ''} {title}".casefold()
            hidden = bool(needle) and needle not in text
            self.twList.setRowHidden(row, hidden)

    def _rows_changed(self) -> None:
        archives = [ca for row in range(self.twList.rowCount()) if (ca := self.get_archive_by_row(row)) is not None]
        folders = {ca.path.parent for ca in archives}
        name = next(iter(folders)).name if len(folders) == 1 else "Files"
        self.listTitle.set_full_text(f"{name} · {len(archives)}".upper() if archives else "FILES")
        self.listTitle.setToolTip(str(next(iter(folders))) if len(folders) == 1 else "")
        if self.filterEdit.text():
            self.apply_filter()

    def sort_by(self, column: int) -> None:
        # A newly chosen column starts in ascending order; the Descending item flips the current one.
        descending = self.descendingAction.isChecked() and column == self.get_sorting()[0]
        self.set_sorting(
            column, QtCore.Qt.SortOrder.DescendingOrder if descending else QtCore.Qt.SortOrder.AscendingOrder
        )

    def _descending_toggled(self, descending: bool) -> None:
        order = QtCore.Qt.SortOrder.DescendingOrder if descending else QtCore.Qt.SortOrder.AscendingOrder
        self.set_sorting(self.get_sorting()[0], order)

    def _sort_indicator_changed(self, column: int, order: QtCore.Qt.SortOrder | int) -> None:
        label = "Name"
        for action in self.sortActions.actions():
            if action.data() == column:
                action.setChecked(True)
                label = action.text()
        descending = QtCore.Qt.SortOrder(order) == QtCore.Qt.SortOrder.DescendingOrder
        self.descendingAction.setChecked(descending)
        self.sortButton.setText(f"Sort: {label} {'↓' if descending else '↑'}")

    def card_text(self, row: int) -> tuple[str, str]:
        """The two lines a card shows: series and issue (from the tags, else the file name), and the file name."""
        archive = self.get_archive_by_row(row)
        if archive is None:
            return "", ""
        key = str(archive.path)
        filename = archive.path.name
        if key not in self._card_titles:
            self._card_titles[key] = self._title_from_filename(archive)
            tagged = self.twList.item(row, self.MDFlagColNum)
            if tagged is not None and tagged.text().strip():
                self._card_pool.start(_CardInfoJob(archive.path, self.config, self._card_signals))
        return self._card_titles[key] or archive.path.stem, filename

    def _title_from_filename(self, archive: ComicArchive) -> str:
        try:
            from comictaggerlib.md import parse_archive_filename

            return card_title(parse_archive_filename(archive, self.config))
        except Exception:
            logger.debug("Could not parse %s", archive.path, exc_info=True)
            return ""

    def _card_title_loaded(self, key: str, title: str) -> None:
        if title and key in self._card_titles:
            self._card_titles[key] = title
            self.twList.viewport().update()

    def forget_card(self, archive: ComicArchive) -> None:
        """Drop the cached card title and cover, after the archive's tags or pages change."""
        self._card_titles.pop(str(archive.path), None)
        self.thumbs.forget(archive.path)

    def update_minimum_height(self) -> None:
        table = self.twList
        scrollbar = table.horizontalScrollBar()
        height = (
            2 * table.frameWidth()
            + (0 if table.horizontalHeader().isHidden() else table.horizontalHeader().sizeHint().height())
            + table.verticalHeader().defaultSectionSize()
        )
        if scrollbar.maximum() > 0:
            height += scrollbar.sizeHint().height()
        table.setMinimumHeight(height)

    @staticmethod
    def reveal_action_text() -> str:
        if platform.system() == "Darwin":
            return "Show in Finder"
        if platform.system() == "Windows":
            return "Show in File Explorer"
        return "Show in File Manager"

    def reveal_current_archive(self) -> None:
        archive = self.get_current_archive()
        if archive is not None:
            self.reveal_path(archive.path)

    @staticmethod
    def reveal_path(path: pathlib.Path) -> None:
        if platform.system() == "Darwin":
            QtCore.QProcess.startDetached("open", ["-R", str(path)])
        elif platform.system() == "Windows":
            QtCore.QProcess.startDetached("explorer.exe", [f"/select,{path}"])
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path.parent)))

    def show_auto_tag_results(self, match_results: OnlineMatchResults) -> None:
        """Show the outcome of the latest Auto-Tag run beside each loaded archive."""
        outcomes = (
            (match_results.good_matches, "Matched", "Auto-Tag found and wrote a confident match."),
            (match_results.multiple_matches, "Multiple", "Auto-Tag found multiple likely matches."),
            (
                match_results.low_confidence_matches,
                "Low confidence",
                "Auto-Tag found one or more matches, but none were confident enough.",
            ),
            (match_results.no_matches, "No match", "Auto-Tag did not find a match."),
            (match_results.fetch_data_failures, "Fetch error", "Auto-Tag could not fetch the selected metadata."),
            (match_results.write_failures, "Write error", "Auto-Tag found a match but could not write its tags."),
            (match_results.read_failures, "Read error", "Auto-Tag could not read the archive's tags."),
        )

        self.twList.setSortingEnabled(False)
        try:
            for results, label, tooltip in outcomes:
                for result in results:
                    row, _archive = self.get_current_list_row(str(result.original_path))
                    if row < 0:
                        continue
                    item = self.twList.item(row, FileSelectionList.matchColNum)
                    if item is not None:
                        item.setText(label)
                        item.setToolTip(tooltip)
        finally:
            self.twList.setSortingEnabled(True)
        self.twList.resizeColumnToContents(FileSelectionList.matchColNum)

    def clear_auto_tag_results(self, archives: list[ComicArchive]) -> None:
        """Clear stale outcomes for archives about to be Auto-Tagged again."""
        for archive in archives:
            row, _archive = self.get_current_list_row(str(archive.path))
            if row < 0:
                continue
            item = self.twList.item(row, FileSelectionList.matchColNum)
            if item is not None:
                item.setText("")
                item.setToolTip("")

    def show_manual_matches(self, archives: list[ComicArchive]) -> None:
        """Distinguish archives resolved in the manual Auto-Tag match picker."""
        for archive in archives:
            self._show_match_label(archive, "Manual match", "The match was selected manually after Auto-Tag.")
        self.twList.resizeColumnToContents(FileSelectionList.matchColNum)

    def show_search_match(self, archive: ComicArchive) -> None:
        """Distinguish metadata selected through Search Online."""
        self._show_match_label(archive, "Search match", "The match was selected through Search Online.")
        self.twList.resizeColumnToContents(FileSelectionList.matchColNum)

    def _show_match_label(self, archive: ComicArchive, label: str, tooltip: str) -> None:
        row, _archive = self.get_current_list_row(str(archive.path))
        if row < 0:
            return
        item = self.twList.item(row, FileSelectionList.matchColNum)
        if item is not None:
            item.setText(label)
            item.setToolTip(tooltip)

    def get_sorting(self) -> tuple[int, int]:
        col = self.twList.horizontalHeader().sortIndicatorSection()
        order = self.twList.horizontalHeader().sortIndicatorOrder().value
        return int(col), int(order)

    def set_sorting(self, col: int, order: QtCore.Qt.SortOrder) -> None:
        self.twList.horizontalHeader().setSortIndicator(col, order)

    def add_app_action(self, action: QtGui.QAction) -> None:
        self.insertAction(QtGui.QAction(), action)

    def set_modified_flag(self, modified: bool) -> None:
        self.dirty_flag = modified
        self.twList.viewport().update()

    def select_all(self) -> None:
        self.twList.setRangeSelected(
            QtWidgets.QTableWidgetSelectionRange(0, 0, self.twList.rowCount() - 1, self.twList.columnCount() - 1), True
        )

    def remove_deleted(self) -> None:
        deleted = []
        for row in range(self.twList.rowCount()):
            row_ca = self.get_archive_by_row(row)
            if not row_ca:
                continue
            if not row_ca.path.exists():
                deleted.append(row_ca)

        self.remove_archive_list(deleted)

    def remove_archive_list(self, ca_list: list[ComicArchive]) -> None:
        self.twList.currentItemChanged.disconnect(self.current_item_changed_cb)
        current_removed = False
        try:
            self.twList.setSortingEnabled(False)
            for ca in ca_list:
                for row in range(self.twList.rowCount()):
                    row_ca = self.get_archive_by_row(row)
                    if row_ca == ca:
                        if row == self.twList.currentRow():
                            current_removed = True
                        self.twList.removeRow(row)
                        self.loaded_paths -= {ca.path}
                        break
            if self.twList.rowCount() > 0 and current_removed:
                self.twList.selectRow(0)
        finally:
            self.twList.setSortingEnabled(True)
            self.twList.currentItemChanged.connect(self.current_item_changed_cb)

        if self.twList.rowCount() > 0 and current_removed:
            # currentItemChanged was disconnected while selecting row 0, so notify
            # listeners directly without re-entering the callback that removed the row.
            current_ca = self.get_current_archive()
            if current_ca is not None:
                self.selectionChanged.emit(QtCore.QVariant(current_ca))
        elif self.twList.rowCount() <= 0:
            self.listCleared.emit()

    def get_archive_by_row(self, row: int) -> ComicArchive | None:
        if row >= 0:
            item = self.twList.item(row, FileSelectionList.dataColNum)
            if item is not None:
                return item.data(QtCore.Qt.ItemDataRole.UserRole)
        return None

    def get_current_archive(self) -> ComicArchive | None:
        return self.get_archive_by_row(self.twList.currentRow())

    @contextmanager
    def defer_path_loads(self) -> Iterator[None]:
        already_deferred = self._verifying_draft_transition
        self._verifying_draft_transition = True
        try:
            yield
        finally:
            self._verifying_draft_transition = already_deferred
            if not already_deferred and self._deferred_path_loads:
                # Resume after the caller accepts the transition or restores the selection.
                QtCore.QTimer.singleShot(0, self._finish_deferred_path_loads)

    def _verify_draft_transition(self, title: str, description: str) -> bool:
        with self.defer_path_loads():
            return self.dirty_flag_verification(title, description)

    def _finish_deferred_path_loads(self) -> None:
        pending_loads, self._deferred_path_loads = self._deferred_path_loads, []
        for prepared_items in pending_loads:
            self._finish_path_load(prepared_items)

    def remove_selection(self) -> None:
        archives = self.get_selected_archive_list()
        if not archives:
            return

        if self.get_current_archive() in archives and not self._verify_draft_transition(
            "Remove Archive", "If you close this archive, data in the form will be lost.  Are you sure?"
        ):
            return

        self.remove_archive_list(archives)

    def add_path_list(self, pathlist: list[str], recursive: bool = True) -> None:
        if not pathlist:
            return
        progress_dialog = QtWidgets.QProgressDialog("Finding comic archives…", "Cancel", 0, 0, parent=self)
        progress_dialog.setWindowTitle("Adding Files")
        progress_dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress_dialog.setMinimumDuration(300)
        center_window_on_parent(progress_dialog)

        thread = PathLoadThread(
            pathlist,
            str(graphics_path / "nocover.png"),
            self.config.Runtime_Options__preferred_hash,
            recursive,
        )
        self.path_load_threads.add(thread)
        self.path_load_dialogs[thread] = progress_dialog
        progress_dialog.canceled.connect(thread.requestInterruption)
        thread.progress.connect(progress_dialog.setLabelText)
        thread.loaded.connect(self._finish_path_load)
        thread.error.connect(self._path_load_error)
        thread.finished.connect(self._path_load_finished)
        thread.start()

    def _finish_path_load(self, prepared_items: list[PreparedPathItem]) -> None:
        if self._verifying_draft_transition:
            self._deferred_path_loads.append(prepared_items)
            return

        if prepared_items and self.twList.rowCount() == 0 and self.dirty_flag:
            with self.defer_path_loads():
                target = prepared_items[0].archive
                if self.review_blank_draft is not None:
                    if not self.review_blank_draft(target) or not target.path.exists():
                        return
                elif not self.dirty_flag_verification(
                    "Open Archive", "Discard your blank metadata draft and open the archive?"
                ):
                    return

        first_added = None
        rar_added_ro = False
        self.twList.setSortingEnabled(False)
        try:
            for prepared in prepared_items:
                row, ca = self._add_prepared_path_item(prepared)
                if ca:
                    if prepared.archive_type == "RAR" and not prepared.writable:
                        rar_added_ro = True
                    if first_added is None and row != -1:
                        first_added = self.twList.item(row, self.fileColNum)
        finally:
            self.twList.setSortingEnabled(True)

        if first_added is not None:
            self.twList.selectRow(first_added.row())
        else:
            OptionalMessageDialog.information(self, "File/Folder Open", "No readable comic archives were found.")
            return

        if rar_added_ro:
            self.rar_ro_message()

        # Adjust column size
        self.twList.resizeColumnToContents(FileSelectionList.readonlyColNum)
        self.twList.setColumnWidth(FileSelectionList.typeColNum, 45)
        self.twList.resizeColumnToContents(FileSelectionList.matchColNum)
        self.twList.resizeColumnToContents(FileSelectionList.folderColNum)
        if self.twList.columnWidth(FileSelectionList.folderColNum) > 250:
            self.twList.setColumnWidth(FileSelectionList.folderColNum, 250)

    def _path_load_error(self, error: Exception) -> None:
        OptionalMessageDialog.critical(self, "File/Folder Open", f"Failed to load comic archives: {error}")

    def _path_load_finished(self) -> None:
        thread = self.sender()
        if not isinstance(thread, PathLoadThread):
            return
        dialog = self.path_load_dialogs.pop(thread, None)
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
        self.path_load_threads.discard(thread)
        thread.deleteLater()

    def rar_ro_message(self) -> None:
        if self.rar_ro_shown:
            return
        if platform.system() == "Windows":
            rar_help = WINDOWS_RAR_HELP

        elif platform.system() == "Darwin":
            rar_help = MAC_RAR_HELP

        else:
            rar_help = LINUX_RAR_HELP

        OptionalMessageDialog.msg_no_checkbox(
            self,
            "RAR Files are Read-Only",
            "It looks like you have opened a RAR/CBR archive,\n"
            "however ComicTagger cannot write to them without the rar program and are marked read only!\n\n"
            f"{rar_help}",
        )
        self.rar_ro_shown = True

    def get_current_list_row(self, path: str) -> tuple[int, ComicArchive]:
        pl = pathlib.Path(path)
        if pl not in self.loaded_paths:
            return -1, None  # type: ignore[return-value]

        for r in range(self.twList.rowCount()):
            ca = cast(ComicArchive, self.get_archive_by_row(r))
            if ca.path == pl:
                return r, ca

        return -1, None  # type: ignore[return-value]

    def add_path_item(self, path: str) -> tuple[int, ComicArchive]:
        path = str(path)
        path = os.path.abspath(path)

        current_row, ca = self.get_current_list_row(path)
        if current_row >= 0:
            return current_row, ca

        prepared = prepare_path_item(
            path, str(graphics_path / "nocover.png"), self.config.Runtime_Options__preferred_hash
        )
        if prepared is None:
            return -1, None  # type: ignore[return-value]
        return self._add_prepared_path_item(prepared)

    def _add_prepared_path_item(self, prepared: PreparedPathItem) -> tuple[int, ComicArchive]:
        ca = prepared.archive
        current_row, current_archive = self.get_current_list_row(str(ca.path))
        if current_row >= 0:
            return current_row, current_archive

        if ca:
            self.loaded_paths.add(ca.path)
            row: int = self.twList.rowCount()
            self.twList.insertRow(row)

            filename_item = QtWidgets.QTableWidgetItem()
            folder_item = QtWidgets.QTableWidgetItem()
            md_item = QtWidgets.QTableWidgetItem()
            readonly_item = QtWidgets.QTableWidgetItem()
            match_item = QtWidgets.QTableWidgetItem()
            type_item = QtWidgets.QTableWidgetItem()

            item_text = os.path.split(ca.path)[1]

            filename_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            filename_item.setData(QtCore.Qt.ItemDataRole.UserRole, ca)
            filename_item.setText(item_text)
            filename_item.setData(QtCore.Qt.ItemDataRole.ToolTipRole, item_text)
            self.twList.setItem(row, FileSelectionList.fileColNum, filename_item)

            item_text = os.path.split(ca.path)[0]

            folder_item.setText(item_text)
            folder_item.setData(QtCore.Qt.ItemDataRole.ToolTipRole, item_text)
            folder_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.twList.setItem(row, FileSelectionList.folderColNum, folder_item)

            item_text = prepared.archive_type
            type_item.setText(item_text)
            type_item.setData(QtCore.Qt.ItemDataRole.ToolTipRole, item_text)
            type_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.twList.setItem(row, FileSelectionList.typeColNum, type_item)

            md_item.setText(", ".join(prepared.tags))
            md_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            md_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            self.twList.setItem(row, FileSelectionList.MDFlagColNum, md_item)

            if not prepared.writable:
                readonly_item.setData(QtCore.Qt.ItemDataRole.UserRole, True)
                readonly_item.setCheckState(QtCore.Qt.CheckState.Checked)
                readonly_item.setText(" ")
            else:
                readonly_item.setData(QtCore.Qt.ItemDataRole.UserRole, False)
                readonly_item.setCheckState(QtCore.Qt.CheckState.Unchecked)
                # This is a nbsp it sorts after a space ' '
                readonly_item.setText("\xa0")

            readonly_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            readonly_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            self.twList.setItem(row, FileSelectionList.readonlyColNum, readonly_item)

            match_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.twList.setItem(row, FileSelectionList.matchColNum, match_item)

            return row, ca
        return -1, None  # type: ignore[return-value]

    def update_row(self, row: int) -> None:
        if row >= 0:
            ca: ComicArchive = self.twList.item(row, FileSelectionList.dataColNum).data(QtCore.Qt.ItemDataRole.UserRole)
            self.forget_card(ca)

            filename_item = self.twList.item(row, FileSelectionList.fileColNum)
            assert filename_item
            folder_item = self.twList.item(row, FileSelectionList.folderColNum)
            assert folder_item
            md_item = self.twList.item(row, FileSelectionList.MDFlagColNum)
            assert md_item
            type_item = self.twList.item(row, FileSelectionList.typeColNum)
            assert type_item
            readonly_item = self.twList.item(row, FileSelectionList.readonlyColNum)
            assert readonly_item

            item_text = os.path.split(ca.path)[1]
            filename_item.setText(item_text)
            filename_item.setData(QtCore.Qt.ItemDataRole.ToolTipRole, item_text)

            item_text = os.path.split(ca.path)[0]
            folder_item.setText(item_text)
            folder_item.setData(QtCore.Qt.ItemDataRole.ToolTipRole, item_text)

            item_text = ca.archiver.name()
            type_item.setText(item_text)
            type_item.setData(QtCore.Qt.ItemDataRole.ToolTipRole, item_text)

            md_item.setText(", ".join(x for x in ca.get_supported_tags() if ca.has_tags(x)))

            if not ca.is_writable():
                readonly_item.setCheckState(QtCore.Qt.CheckState.Checked)
                readonly_item.setData(QtCore.Qt.ItemDataRole.UserRole, True)
                readonly_item.setText(" ")
            else:
                readonly_item.setData(QtCore.Qt.ItemDataRole.UserRole, False)
                readonly_item.setCheckState(QtCore.Qt.CheckState.Unchecked)
                # This is a nbsp it sorts after a space ' '
                readonly_item.setText("\xa0")

    def get_selected_archive_list(self) -> list[ComicArchive]:
        ca_list: list[ComicArchive] = []
        for r in range(self.twList.rowCount()):
            item = self.twList.item(r, FileSelectionList.dataColNum)
            if item.isSelected():
                ca: ComicArchive = item.data(QtCore.Qt.ItemDataRole.UserRole)
                ca_list.append(ca)

        return ca_list

    def update_current_row(self) -> None:
        self.update_row(self.twList.currentRow())

    def update_selected_rows(self) -> None:
        self.remove_deleted()
        self.twList.setSortingEnabled(False)
        for r in range(self.twList.rowCount()):
            item = self.twList.item(r, FileSelectionList.dataColNum)
            if item.isSelected():
                self.update_row(r)
        self.twList.setSortingEnabled(True)
        self.loaded_paths = {
            ca.path for row in range(self.twList.rowCount()) if (ca := self.get_archive_by_row(row)) is not None
        }

    def current_item_changed_cb(
        self, curr: QtWidgets.QTableWidgetItem | None, prev: QtWidgets.QTableWidgetItem | None
    ) -> None:
        if curr is not None:
            new_idx = curr.row()
            old_idx = -1
            if prev is not None:
                old_idx = prev.row()

            if old_idx == new_idx:
                return
            ca = self.get_archive_by_row(new_idx)
            if not ca or not ca.path.exists():
                if prev is not None and ca is not None:
                    self._restore_current_item(prev)
                    self.remove_archive_list([ca])
                else:
                    self.remove_deleted()
                return

            # don't allow change if modified
            if prev is not None and new_idx != old_idx:
                if not self._verify_draft_transition(
                    "Change Archive", "If you change archives now, data in the form will be lost.  Are you sure?"
                ):
                    self._restore_current_item(prev)
                    return

            self.selectionChanged.emit(QtCore.QVariant(ca))

    def _restore_current_item(self, item: QtWidgets.QTableWidgetItem) -> None:
        self.twList.currentItemChanged.disconnect(self.current_item_changed_cb)
        self.twList.setCurrentItem(item)
        self.twList.currentItemChanged.connect(self.current_item_changed_cb)
        # Restore the row selection after Qt finishes handling the original selection.
        index = QtCore.QPersistentModelIndex(self.twList.currentIndex())

        def restore_selection() -> None:
            if index.isValid() and self.twList.currentIndex() == index:
                self.twList.selectRow(index.row())

        QtCore.QTimer.singleShot(0, restore_selection)
