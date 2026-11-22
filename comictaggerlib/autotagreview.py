"""A docked panel for triaging Auto-Tag results.

After a run, every archive lands in one of four groups: matches that need a
decision, archives with no match, archives that hit an error, and archives that
were tagged. The panel lets the user work through those groups without leaving
the main window, accepting a candidate with one key press or handing the archive
to the regular online search when no candidate fits.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
from collections.abc import Callable, Iterable
from enum import auto

from PyQt6 import QtCore, QtGui, QtWidgets

from comicapi import utils
from comicapi.comicarchive import ComicArchive, tags
from comicapi.genericmetadata import GenericMetadata
from comictaggerlib.coverimagewidget import CoverImageWidget
from comictaggerlib.ctsettings import ct_ns
from comictaggerlib.md import parse_archive_filename, prepare_metadata, read_configured_tags, write_selected_tags
from comictaggerlib.optionalmsgdialog import OptionalMessageDialog
from comictaggerlib.resulttypes import Action, IssueResult, MatchStatus, OnlineMatchResults, Result, Status
from comictaggerlib.searchpanel import SearchPanel, query_from_metadata
from comictalker.comictalker import ComicTalker, TalkerError

logger = logging.getLogger(__name__)


class Outcome(utils.StrEnum):
    needs_review = auto()
    no_match = auto()
    error = auto()
    tagged = auto()


OUTCOME_LABELS = {
    Outcome.needs_review: "Needs review",
    Outcome.no_match: "No match",
    Outcome.error: "Errors",
    Outcome.tagged: "Tagged",
}


@dataclasses.dataclass
class ReviewItem:
    archive: ComicArchive
    outcome: Outcome
    reason: str
    result: Result | None = None
    resolution: str = ""

    @property
    def candidates(self) -> list[IssueResult]:
        return list(self.result.online_results) if self.result is not None else []

    @property
    def name(self) -> str:
        return self.archive.path.name

    @property
    def can_retry_write(self) -> bool:
        return (
            self.outcome == Outcome.error
            and self.result is not None
            and self.result.md is not None
            and not self.result.md.is_empty
        )


def _matches_reason(result: Result) -> str:
    count = len(result.online_results)
    return "1 possible match" if count == 1 else f"{count} possible matches"


def classify(result: Result) -> tuple[Outcome, str] | None:
    """The review group and reason for one archive's result, or None for results the review doesn't show."""
    if result.status == Status.success and result.action == Action.save:
        return Outcome.tagged, "Tagged"
    if result.status == Status.read_failure:
        return Outcome.error, "Couldn't read existing tags"
    if result.status == Status.write_failure and result.action == Action.save:
        return Outcome.error, "Couldn't write tags"
    if result.status == Status.fetch_data_failure:
        return Outcome.error, "Couldn't fetch issue details"
    if result.status == Status.match_failure:
        if result.match_status == MatchStatus.no_match:
            return Outcome.no_match, "No match found"
        if result.match_status == MatchStatus.multiple_match:
            return Outcome.needs_review, _matches_reason(result)
        if result.match_status == MatchStatus.low_confidence_match:
            return Outcome.needs_review, "Low confidence"
    return None


def make_item(result: Result, archive: ComicArchive) -> ReviewItem | None:
    found = classify(result)
    return ReviewItem(archive, found[0], found[1], result) if found is not None else None


def skipped_item(archive: ComicArchive) -> ReviewItem | None:
    """The run skips read-only archives without recording a result, so they're added when it ends."""
    return None if archive.is_writable() else ReviewItem(archive, Outcome.error, "File is read-only")


def build_review_items(match_results: OnlineMatchResults, archives: Iterable[ComicArchive]) -> list[ReviewItem]:
    """Sort the archives of a finished run into review groups, keeping the run's order inside each group."""
    results = [
        *match_results.good_matches,
        *match_results.no_matches,
        *match_results.multiple_matches,
        *match_results.low_confidence_matches,
        *match_results.write_failures,
        *match_results.fetch_data_failures,
        *match_results.read_failures,
    ]
    by_path = {result.original_path: result for result in results}
    items = []
    for archive in archives:
        result = by_path.get(archive.path)
        item = make_item(result, archive) if result is not None else skipped_item(archive)
        if item is not None:
            items.append(item)
    return items


_DIFF_FIELDS = (
    ("series", "Series"),
    ("issue", "Issue"),
    ("title", "Title"),
    ("volume", "Volume"),
    ("issue_count", "Issue count"),
    ("publisher", "Publisher"),
    ("year", "Year"),
    ("month", "Month"),
)


def _display(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def metadata_diff(current: GenericMetadata, candidate: GenericMetadata) -> list[tuple[str, str, str]]:
    """List the headline fields a candidate would fill in or change."""
    rows = []
    for field, label in _DIFF_FIELDS:
        new = getattr(candidate, field, None)
        if new is None or new == "":
            continue
        old = getattr(current, field, None)
        rows.append((label, _display(old), _display(new)))
    return rows


def write_match(
    parent: QtWidgets.QWidget, ca: ComicArchive, issue_id: str, config: ct_ns, talker: ComicTalker
) -> GenericMetadata | None:
    """Fetch the full issue for a chosen match and write it to the archive. Reports problems to the user."""
    md, _, error = read_configured_tags(ca, config.Runtime_Options__tags_read, config)
    if error is not None:
        logger.error("Failed to load tags for %s: %s", ca.path, error)
        OptionalMessageDialog.critical(
            parent, "Read Failed!", f"One or more of the read tags failed to load for {ca.path}, check log for details"
        )
        return None
    if md.is_empty:
        md = parse_archive_filename(ca, config)

    QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor))
    try:
        try:
            ct_md = talker.fetch_comic_data(issue_id=issue_id)
        except TalkerError as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            OptionalMessageDialog.critical(parent, f"{e.source} {e.code_name} Error", str(e))
            return None
        if ct_md is None or ct_md.is_empty:
            QtWidgets.QApplication.restoreOverrideCursor()
            OptionalMessageDialog.critical(parent, "Network Issue", "Could not retrieve issue details!")
            return None
        md = prepare_metadata(md, ct_md, config)
        _, failed = write_selected_tags(ca, md, config.Runtime_Options__tags_write)
        ca.reset_cache()
    finally:
        if QtWidgets.QApplication.overrideCursor() is not None:
            QtWidgets.QApplication.restoreOverrideCursor()

    if failed is not None:
        OptionalMessageDialog.warning(
            parent, "Write Error", f"Saving {tags[failed].name()} tags to the archive failed!"
        )
        return None
    return md


def _shortcut(widget: QtWidgets.QWidget, keys: str, slot: Callable[[], object]) -> QtGui.QShortcut:
    shortcut = QtGui.QShortcut(QtGui.QKeySequence(keys), widget)
    shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
    shortcut.activated.connect(slot)
    return shortcut


class AutoTagReviewPanel(QtWidgets.QWidget):
    """Inbox-style review of the latest Auto-Tag run."""

    openRequested = QtCore.pyqtSignal(object)  # ComicArchive
    matchesWritten = QtCore.pyqtSignal(list)  # list[ComicArchive]
    stopRequested = QtCore.pyqtSignal()
    ratelimit = QtCore.pyqtSignal(float, float)
    logRequested = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None, cache_dir: pathlib.Path | None) -> None:
        super().__init__(parent)
        self.setObjectName("autoTagReview")
        self.items: list[ReviewItem] = []
        self.config: ct_ns | None = None
        self.talker: ComicTalker | None = None
        self._outcome = Outcome.needs_review
        self._current_md = GenericMetadata()
        self._run_archives: list[ComicArchive] = []
        self.running = False

        self.categoryList = QtWidgets.QListWidget()
        self.categoryList.setAccessibleName("Result groups")
        for outcome in Outcome:
            item = QtWidgets.QListWidgetItem(OUTCOME_LABELS[outcome])
            item.setData(QtCore.Qt.ItemDataRole.UserRole, outcome)
            self.categoryList.addItem(item)
        self.categoryList.currentRowChanged.connect(self._category_changed)

        self.fileList = QtWidgets.QListWidget()
        self.fileList.setAccessibleName("Archives in group")
        self.fileList.setWordWrap(True)
        self.fileList.setUniformItemSizes(False)
        self.fileList.setSpacing(2)
        self.fileList.currentRowChanged.connect(self._file_changed)
        self.fileList.itemDoubleClicked.connect(lambda _item: self.open_current())

        self.heading = QtWidgets.QLabel()
        self.heading.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        font = self.heading.font()
        font.setBold(True)
        self.heading.setFont(font)
        self.reasonLabel = QtWidgets.QLabel()
        self.positionLabel = QtWidgets.QLabel()
        self.positionLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.archiveCover = CoverImageWidget(None, CoverImageWidget.ArchiveMode, None, expand_on_click=False)
        self.archiveCover.setMinimumSize(110, 165)
        self.candidateCover = CoverImageWidget(None, CoverImageWidget.AltCoverMode, cache_dir, expand_on_click=False)
        self.candidateCover.setMinimumSize(110, 165)

        self.candidateTable = QtWidgets.QTableWidget(0, 5)
        self.candidateTable.setAccessibleName("Candidate matches")
        self.candidateTable.setHorizontalHeaderLabels(["Series", "Issue", "Date", "Publisher", "Title"])
        self.candidateTable.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.candidateTable.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.candidateTable.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.candidateTable.verticalHeader().hide()
        self.candidateTable.horizontalHeader().setStretchLastSection(True)
        self.candidateTable.currentCellChanged.connect(self._candidate_changed)
        self.candidateTable.cellDoubleClicked.connect(lambda _r, _c: self.accept_current())

        self.messageLabel = QtWidgets.QLabel()
        self.messageLabel.setWordWrap(True)
        self.messageLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        self.diffTable = QtWidgets.QTableWidget(0, 3)
        self.diffTable.setAccessibleName("Changes from selected match")
        self.diffTable.setHorizontalHeaderLabels(["Field", "In file now", "From match"])
        self.diffTable.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.diffTable.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.diffTable.verticalHeader().hide()
        self.diffTable.horizontalHeader().setStretchLastSection(True)

        self.btnAccept = QtWidgets.QPushButton("Accept match")
        self.btnAccept.setToolTip("Write the selected match to the archive (Enter)")
        self.btnAccept.setDefault(True)
        self.btnSearch = QtWidgets.QPushButton("Search by hand")
        self.btnSearch.setToolTip("Find the right series and issue yourself (/)")
        self.btnOpen = QtWidgets.QPushButton("Open in editor")
        self.btnOpen.setToolTip("Load the archive into the editor (E)")
        self.btnSkip = QtWidgets.QPushButton("Skip")
        self.btnSkip.setToolTip("Leave this archive for later and go to the next one (S)")
        self.btnAccept.clicked.connect(self.accept_current)
        self.btnSearch.clicked.connect(self.search_current)
        self.btnOpen.clicked.connect(self.open_current)
        self.btnSkip.clicked.connect(self.next_item)

        header = QtWidgets.QHBoxLayout()
        header.addWidget(self.heading)
        header.addWidget(self.reasonLabel)
        header.addStretch(1)
        header.addWidget(self.positionLabel)

        self.candidateArea = QtWidgets.QStackedWidget()
        self.candidateArea.addWidget(self.candidateTable)
        self.candidateArea.addWidget(self.messageLabel)

        compare = QtWidgets.QHBoxLayout()
        compare.addWidget(self.candidateArea, 1)
        compare.addWidget(self.candidateCover)

        buttons = QtWidgets.QHBoxLayout()
        for button in (self.btnAccept, self.btnSearch, self.btnOpen, self.btnSkip):
            buttons.addWidget(button)
        buttons.addStretch(1)
        hint = QtWidgets.QLabel("J / K: next / previous")
        hint.setEnabled(False)
        buttons.addWidget(hint)

        review_page = QtWidgets.QWidget()
        review_layout = QtWidgets.QVBoxLayout(review_page)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.addLayout(compare, 3)
        review_layout.addWidget(self.diffTable, 2)
        review_layout.addLayout(buttons)
        self.reviewPage = review_page

        self.searchPanel = SearchPanel(None, cache_dir)
        self.searchPanel.issueChosen.connect(self._search_chose)
        self.searchPanel.canceled.connect(self._leave_search)
        self.searchPanel.ratelimit.connect(self.ratelimit)

        self.bodyStack = QtWidgets.QStackedWidget()
        self.bodyStack.addWidget(review_page)
        self.bodyStack.addWidget(self.searchPanel)

        body = QtWidgets.QHBoxLayout()
        body.addWidget(self.archiveCover, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        body.addWidget(self.bodyStack, 1)

        detail = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(detail)
        detail_layout.addLayout(header)
        detail_layout.addLayout(body, 1)
        self.detail = detail

        self.emptyLabel = QtWidgets.QLabel("Nothing in this group.")
        self.emptyLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.detailStack = QtWidgets.QStackedWidget()
        self.detailStack.addWidget(detail)
        self.detailStack.addWidget(self.emptyLabel)

        self.attributionLabel = QtWidgets.QLabel()
        self.attributionLabel.setWordWrap(True)
        self.attributionLabel.setOpenExternalLinks(True)
        self.attributionLabel.setTextFormat(QtCore.Qt.TextFormat.RichText)
        groups = QtWidgets.QWidget()
        groups.setMaximumWidth(200)
        groups_layout = QtWidgets.QVBoxLayout(groups)
        groups_layout.setContentsMargins(0, 0, 0, 0)
        groups_layout.addWidget(self.categoryList, 1)
        groups_layout.addWidget(self.attributionLabel)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(groups)
        splitter.addWidget(self.fileList)
        splitter.addWidget(self.detailStack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([160, 260, 700])
        self.splitter = splitter

        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setAccessibleName("Auto-Tag progress")
        self.progressLabel = QtWidgets.QLabel()
        self.progressLabel.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.btnLog = QtWidgets.QPushButton("Show details")
        self.btnLog.setToolTip("Show the covers being compared and the run's log")
        self.btnLog.clicked.connect(self.logRequested)
        self.btnStop = QtWidgets.QPushButton("Stop")
        self.btnStop.setToolTip("Stop after the archive being identified now")
        self.btnStop.clicked.connect(self._stop)
        self.runBar = QtWidgets.QWidget()
        run_layout = QtWidgets.QHBoxLayout(self.runBar)
        run_layout.setContentsMargins(6, 4, 6, 4)
        run_layout.addWidget(self.progressLabel)
        run_layout.addWidget(self.progressBar, 1)
        run_layout.addWidget(self.btnLog)
        run_layout.addWidget(self.btnStop)
        self.runBar.hide()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.runBar)
        layout.addWidget(splitter)

        _shortcut(self, "Return", self.accept_current)
        _shortcut(self, "Enter", self.accept_current)
        _shortcut(self, "/", self.search_current)
        _shortcut(self, "E", self.open_current)
        _shortcut(self, "S", self.next_item)
        _shortcut(self, "J", self.next_item)
        _shortcut(self, "K", self.previous_item)
        _shortcut(self, "Escape", self._escape)

        self._refresh()

    # ----- data -----

    def load_results(
        self,
        match_results: OnlineMatchResults,
        archives: Iterable[ComicArchive],
        config: ct_ns,
        talker: ComicTalker,
    ) -> None:
        self.items = build_review_items(match_results, archives)
        self._set_source(config, talker)
        first = next((o for o in Outcome if self.items_in(o)), Outcome.tagged)
        self._outcome = first
        self._refresh()

    def _set_source(self, config: ct_ns, talker: ComicTalker) -> None:
        self.config = config
        self.talker = talker
        self.attributionLabel.setText(talker.attribution)

    # ----- live runs -----

    def begin_run(self, archives: list[ComicArchive], config: ct_ns, talker: ComicTalker) -> None:
        """Start an empty review that fills in while Auto-Tag works through the archives."""
        self.items = []
        self._run_archives = list(archives)
        self._set_source(config, talker)
        self.running = True
        self._outcome = Outcome.needs_review
        self.progressBar.setRange(0, len(archives))
        self.progressBar.setValue(0)
        self.progressLabel.setText(f"Auto-tagging {len(archives)} archives…")
        self.btnStop.setEnabled(True)
        self.runBar.show()
        self._refresh()

    def set_progress(self, done: int, total: int, path: object) -> None:
        self.progressBar.setRange(0, total)
        self.progressBar.setValue(done)
        name = getattr(path, "name", "")
        self.progressLabel.setText(f"{done + 1} of {total}: {name}" if name else f"{done} of {total}")

    def add_result(self, result: Result) -> None:
        """Show one archive's outcome as soon as the run has it, without disturbing what's being reviewed."""
        archive = next((a for a in self._run_archives if a.path == result.original_path), None)
        item = make_item(result, archive) if archive is not None else None
        if item is None:
            return
        existing = self.item_for(item.archive)
        if existing is not None:
            self.items.remove(existing)
        self.items.append(item)
        shown_group_empty = not any(i is not item for i in self.items_in(self._outcome))
        if shown_group_empty and item.outcome not in (self._outcome, Outcome.tagged) and not self._searching():
            # The group on screen was empty, so jump to the first one with work in it.
            self._outcome = item.outcome
            self._refresh()
            return
        self._update_counts()
        if item.outcome == self._outcome:
            self.fileList.addItem(self._list_entry(item))
            if self.fileList.count() == 1:
                self._refresh()
            else:
                self.positionLabel.setText(f"{self.fileList.currentRow() + 1} of {self.fileList.count()}")
                self.btnSkip.setEnabled(self.fileList.currentRow() + 1 < self.fileList.count())

    def finish_run(self) -> None:
        self.running = False
        self.runBar.hide()
        for archive in self._run_archives:
            if self.item_for(archive) is None:
                item = skipped_item(archive)
                if item is not None:
                    self.items.append(item)
        if not self.items_in(self._outcome) and not self._searching():
            self._outcome = next((o for o in Outcome if self.items_in(o)), Outcome.tagged)
            self._refresh()
        else:
            self._update_counts()

    def _stop(self) -> None:
        self.btnStop.setEnabled(False)
        self.progressLabel.setText("Stopping after the current archive…")
        self.stopRequested.emit()

    def items_in(self, outcome: Outcome) -> list[ReviewItem]:
        return [item for item in self.items if item.outcome == outcome]

    def item_for(self, archive: ComicArchive) -> ReviewItem | None:
        return next((item for item in self.items if item.archive.path == archive.path), None)

    def pending_count(self) -> int:
        return sum(1 for item in self.items if item.outcome != Outcome.tagged)

    def summary(self) -> str:
        words = {
            Outcome.needs_review: ("needs review", "need review"),
            Outcome.no_match: ("with no match", "with no match"),
            Outcome.error: ("error", "errors"),
            Outcome.tagged: ("tagged", "tagged"),
        }
        parts = []
        for outcome in Outcome:
            count = len(self.items_in(outcome))
            if count:
                parts.append(f"{count} {words[outcome][count != 1]}")
        return "Auto-Tag finished: " + ", ".join(parts) if parts else "Auto-Tag finished with nothing to show"

    def current_item(self) -> ReviewItem | None:
        row = self.fileList.currentRow()
        group = self.items_in(self._outcome)
        return group[row] if 0 <= row < len(group) else None

    def current_candidate(self) -> IssueResult | None:
        item = self.current_item()
        row = self.candidateTable.currentRow()
        if item is None or self.candidateArea.currentWidget() is not self.candidateTable:
            return None
        cell = self.candidateTable.item(row, 0)
        return cell.data(QtCore.Qt.ItemDataRole.UserRole) if cell is not None else None

    # ----- actions -----

    def resolve(self, item: ReviewItem, resolution: str) -> None:
        """Move an archive to the Tagged group and open the next one in the current group."""
        group = self.items_in(self._outcome)
        row = group.index(item) if item in group else -1
        item.outcome = Outcome.tagged
        item.resolution = resolution
        item.reason = resolution
        self._refresh(select_row=row)

    def mark_fixed(self, archive: ComicArchive) -> None:
        """Called when the user saves an archive in the editor."""
        item = self.item_for(archive)
        if item is not None and item.outcome != Outcome.tagged:
            self.resolve(item, "Fixed by hand")

    def remove_archives(self, archives: Iterable[ComicArchive]) -> None:
        paths = {archive.path for archive in archives}
        if any(item.archive.path in paths for item in self.items):
            self.items = [item for item in self.items if item.archive.path not in paths]
            self._refresh(select_row=self.fileList.currentRow())

    def accept_current(self) -> None:
        if self._searching():
            focus = QtWidgets.QApplication.focusWidget()
            if focus is self.searchPanel.leSeries:
                self.searchPanel.search()
            elif focus is self.searchPanel.leIssue:
                self.searchPanel._issue_number_changed()
            else:
                self.searchPanel.choose()
            return
        item = self.current_item()
        if item is None or self.config is None or not self.btnAccept.isEnabled():
            return
        if item.can_retry_write:
            assert item.result is not None and item.result.md is not None
            _, failed = write_selected_tags(item.archive, item.result.md, self.config.Runtime_Options__tags_write)
            item.archive.reset_cache()
            if failed is not None:
                OptionalMessageDialog.warning(
                    self, "Write Error", f"Saving {tags[failed].name()} tags to the archive failed again."
                )
                return
            self.resolve(item, "Written on retry")
            self.matchesWritten.emit([item.archive])
            return
        match = self.current_candidate()
        if match is None or self.talker is None:
            return
        assert match.md.issue_id
        self._write(item, match.md.issue_id, "Accepted")

    def _write(self, item: ReviewItem, issue_id: str, resolution: str) -> bool:
        assert self.config is not None and self.talker is not None
        md = write_match(self, item.archive, issue_id, self.config, self.talker)
        if md is None:
            return False
        if item.result is not None:
            item.result.md = md
        self.resolve(item, resolution)
        self.matchesWritten.emit([item.archive])
        return True

    def search_current(self) -> None:
        """Swap the matches for a series and issue search, prefilled from the archive."""
        item = self.current_item()
        if item is None or self.config is None or self.talker is None:
            return
        md = self._current_md
        if md.is_empty or not md.series:
            md = parse_archive_filename(item.archive, self.config)
        series, issue, year = query_from_metadata(md)
        self.bodyStack.setCurrentWidget(self.searchPanel)
        self.searchPanel.start(series, issue, year, self.config, self.talker)
        if series:
            self.searchPanel.seriesTable.setFocus()

    def _searching(self) -> bool:
        return self.detailStack.currentWidget() is self.detail and self.bodyStack.currentWidget() is self.searchPanel

    def _search_chose(self, issue: GenericMetadata, _series: object) -> None:
        item = self.current_item()
        if item is None or not issue.issue_id:
            return
        self._write(item, issue.issue_id, "Picked by search")

    def _leave_search(self) -> None:
        self.bodyStack.setCurrentWidget(self.reviewPage)
        self.fileList.setFocus()

    def _escape(self) -> None:
        if self._searching():
            self.searchPanel.cancel()

    def open_current(self) -> None:
        item = self.current_item()
        if item is not None:
            self.openRequested.emit(item.archive)

    def next_item(self) -> None:
        row = self.fileList.currentRow()
        if row + 1 < self.fileList.count():
            self.fileList.setCurrentRow(row + 1)

    def previous_item(self) -> None:
        row = self.fileList.currentRow()
        if row > 0:
            self.fileList.setCurrentRow(row - 1)

    # ----- view -----

    def _update_counts(self) -> None:
        self.categoryList.blockSignals(True)
        for row, outcome in enumerate(Outcome):
            count = len(self.items_in(outcome))
            self.categoryList.item(row).setText(f"{OUTCOME_LABELS[outcome]}  ({count})")
            if outcome == self._outcome:
                self.categoryList.setCurrentRow(row)
        self.categoryList.blockSignals(False)

    @staticmethod
    def _list_entry(item: ReviewItem) -> QtWidgets.QListWidgetItem:
        entry = QtWidgets.QListWidgetItem(f"{item.name}\n{item.reason}")
        entry.setToolTip(str(item.archive.path))
        return entry

    def _refresh(self, select_row: int = 0) -> None:
        self._update_counts()
        group = self.items_in(self._outcome)
        self.fileList.blockSignals(True)
        self.fileList.clear()
        for item in group:
            self.fileList.addItem(self._list_entry(item))
        self.fileList.blockSignals(False)

        if group:
            self.fileList.setCurrentRow(max(0, min(select_row, len(group) - 1)))
            self._file_changed(self.fileList.currentRow())
        else:
            self._file_changed(-1)

    def _category_changed(self, row: int) -> None:
        if 0 <= row < len(Outcome):
            self._outcome = list(Outcome)[row]
            self._refresh()

    def _file_changed(self, row: int) -> None:
        item = self.current_item()
        if self._searching():
            self.searchPanel.cancel()
        self.bodyStack.setCurrentWidget(self.reviewPage)
        if item is None:
            if self.running:
                text = "Results show up here as each archive is done. You can review while the run continues."
            else:
                text = "Nothing left to review here." if self._outcome != Outcome.tagged else "Nothing tagged yet."
            self.emptyLabel.setText(text)
            self.detailStack.setCurrentWidget(self.emptyLabel)
            self.archiveCover.clear()
            self.candidateCover.clear()
            return

        self.detailStack.setCurrentWidget(self.detail)
        self.heading.setText(item.name)
        self.reasonLabel.setText(item.reason)
        self.positionLabel.setText(f"{row + 1} of {self.fileList.count()}")
        self.archiveCover.set_archive(item.archive)

        self._current_md = GenericMetadata()
        if self.config is not None:
            md, _, error = read_configured_tags(item.archive, self.config.Runtime_Options__tags_read, self.config)
            if error is None:
                self._current_md = md

        candidates = item.candidates if item.outcome == Outcome.needs_review else []
        self.candidateTable.setRowCount(len(candidates))
        for r, match in enumerate(candidates):
            date = f"{match.md.year or '????'}" + (f"-{int(match.md.month):02d}" if match.md.month else "")
            values = (match.series.name, match.md.issue or "", date, match.md.publisher or "", match.md.title or "")
            for c, text in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(str(text))
                cell.setToolTip(str(text))
                if c == 0:
                    cell.setData(QtCore.Qt.ItemDataRole.UserRole, match)
                self.candidateTable.setItem(r, c, cell)
        self.candidateTable.resizeColumnsToContents()
        self.candidateTable.horizontalHeader().setStretchLastSection(True)

        if candidates:
            self.candidateArea.setCurrentWidget(self.candidateTable)
            self.candidateTable.setCurrentCell(0, 0)
            self._candidate_changed(0, 0, -1, -1)
        else:
            self.candidateArea.setCurrentWidget(self.messageLabel)
            self.messageLabel.setText(self._message_for(item))
            shown = item.result.md if item.result is not None and item.result.md is not None else None
            if shown is not None:
                self._show_candidate_md(shown)
            else:
                self.candidateCover.clear()
                self.diffTable.setRowCount(0)

        self.btnAccept.setEnabled(bool(candidates) or item.can_retry_write)
        self.btnAccept.setText("Retry write" if item.can_retry_write else "Accept match")
        self.btnSkip.setEnabled(row + 1 < self.fileList.count())

    def _message_for(self, item: ReviewItem) -> str:
        if item.outcome == Outcome.tagged:
            return f"{item.reason}. If this looks wrong, search by hand to pick a different issue."
        if item.outcome == Outcome.no_match:
            return "Auto-Tag couldn't find this issue. Search by hand to pick it yourself."
        if item.can_retry_write:
            return f"{item.reason}. Check the file isn't read-only or open elsewhere, then retry."
        return f"{item.reason}. Search by hand, or open it in the editor to see more."

    def _candidate_changed(self, row: int, _col: int, prev_row: int, _prev_col: int) -> None:
        if row == prev_row:
            return
        match = self.current_candidate()
        if match is not None:
            self._show_candidate_md(match.md)

    def _show_candidate_md(self, md: GenericMetadata) -> None:
        urls = [image.URL for image in [md._cover_image, *md._alternate_images] if image]
        self.candidateCover.set_url_list(urls)
        rows = metadata_diff(self._current_md, md)
        self.diffTable.setRowCount(len(rows))
        for r, (label, old, new) in enumerate(rows):
            for c, text in enumerate((label, old, new)):
                cell = QtWidgets.QTableWidgetItem(text)
                if c == 2 and old != new:
                    font = cell.font()
                    font.setBold(True)
                    cell.setFont(font)
                self.diffTable.setItem(r, c, cell)
        self.diffTable.resizeColumnsToContents()
        self.diffTable.horizontalHeader().setStretchLastSection(True)
