"""The Auto-Tag review: an inbox for triaging the results of a run.

After a run, every archive lands in one of four groups: matches that need a
decision, archives with no match, archives that hit an error, and archives that
were tagged. The panel lets the user work through those groups without leaving
the main window, accepting a candidate with one key press or handing the archive
to the regular online search when no candidate fits.
"""

from __future__ import annotations

import dataclasses
import functools
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
from comictaggerlib.workspacestyle import DEFAULT_COLORS, Painter, ThumbnailCache, chip, section_label, set_property
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


# Light palette; the main window replaces it with the workspace theme (light or dark).
OUTCOME_TONES = {
    Outcome.needs_review: "warn",
    Outcome.no_match: "bad",
    Outcome.error: "bad",
    Outcome.tagged: "ok",
}

_ITEM_ROLE = QtCore.Qt.ItemDataRole.UserRole


class GroupDelegate(QtWidgets.QStyledItemDelegate):
    """Sidebar rows: a coloured dot, the group name and its count."""

    def __init__(self, panel: AutoTagReviewPanel) -> None:
        super().__init__(panel)
        self.draw = Painter(panel)

    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> QtCore.QSize:
        return QtCore.QSize(160, option.fontMetrics.height() + 14)

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> None:
        outcome = index.data(_ITEM_ROLE)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.draw.background(painter, option, 6)
        rect = option.rect.adjusted(18, 0, -16, 0)
        tone = OUTCOME_TONES.get(outcome, "ok")
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self.draw.color(tone))
        painter.drawEllipse(QtCore.QPointF(rect.left() + 4, rect.center().y() + 1), 4, 4)
        font = QtGui.QFont(option.font)
        font.setBold(bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected))
        painter.setFont(font)
        painter.setPen(self.draw.color("ink"))
        label_rect = rect.adjusted(16, 0, -40, 0)
        painter.drawText(label_rect, QtCore.Qt.AlignmentFlag.AlignVCenter, OUTCOME_LABELS.get(outcome, ""))
        count = str(index.data(QtCore.Qt.ItemDataRole.UserRole + 1) or 0)
        mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        mono.setPointSizeF(option.font.pointSizeF() * 0.9)
        painter.setFont(mono)
        painter.setPen(self.draw.color("muted"))
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight, count)
        painter.restore()


class FileDelegate(QtWidgets.QStyledItemDelegate):
    """Archive rows: a cover thumbnail, the file name and a status chip."""

    def __init__(self, panel: AutoTagReviewPanel) -> None:
        super().__init__(panel)
        self.panel = panel
        self.draw = Painter(panel)

    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> QtCore.QSize:
        return QtCore.QSize(260, max(60, option.fontMetrics.height() * 2 + 26))

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> None:
        item: ReviewItem | None = index.data(_ITEM_ROLE)
        if item is None:
            return
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        self.draw.background(painter, option, 4)
        rect = option.rect.adjusted(12, 7, -10, -7)
        thumb_rect = QtCore.QRect(rect.left(), rect.top(), int(rect.height() * 2 / 3), rect.height())
        self.draw.thumbnail(painter, thumb_rect, self.panel.thumbnail(item.archive))
        text_left = thumb_rect.right() + 10
        font = QtGui.QFont(option.font)
        font.setWeight(QtGui.QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(self.draw.color("ink"))
        metrics = QtGui.QFontMetrics(font)
        name = metrics.elidedText(item.name, QtCore.Qt.TextElideMode.ElideMiddle, rect.right() - text_left)
        painter.drawText(text_left, rect.top() + metrics.ascent() + 2, name)
        tone = "ok" if item.resolution else OUTCOME_TONES[item.outcome]
        self.draw.chip(painter, text_left, rect.top() + metrics.height() + 8, item.reason, tone, option.font)
        painter.restore()


class CandidateCard(QtWidgets.QFrame):
    """One possible match: its cover, series, issue, date and how it was ranked."""

    clicked = QtCore.pyqtSignal(int)
    activated = QtCore.pyqtSignal(int)

    def __init__(self, index: int, match: IssueResult, cache_dir: pathlib.Path | None, best: bool) -> None:
        super().__init__()
        self.index = index
        self.match = match
        self.setObjectName("candidateCard")
        self.setProperty("selected", False)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(230)
        self.setAccessibleName(f"Match {index + 1}: {match.series.name} #{match.md.issue or '?'}")

        self.cover = CoverImageWidget(None, CoverImageWidget.URLMode, cache_dir, expand_on_click=False)
        self.cover.showControls = False
        self.cover.setFixedSize(66, 100)
        self.cover.set_url(match.md._cover_image.URL if match.md._cover_image else match.series.image_url)

        key = QtWidgets.QLabel(str(index + 1) if index < 9 else "")
        key.setObjectName("cardKey")
        title = QtWidgets.QLabel(f"{match.series.name} #{match.md.issue}" if match.md.issue else match.series.name)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        title.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        date = " ".join(
            x for x in (f"{int(match.md.month):02d}/" if match.md.month else "", str(match.md.year or "")) if x
        ).replace("/ ", "/")
        meta = QtWidgets.QLabel(" · ".join(x for x in (date, str(match.md.publisher or "")) if x))
        meta.setObjectName("cardMeta")
        meta.setWordWrap(True)
        meta.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        rank = chip("Best guess" if best else f"Match {index + 1}", "acc" if best else "muted")

        text = QtWidgets.QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(key)
        text.addWidget(title)
        text.addWidget(meta)
        text.addStretch(1)
        text.addWidget(rank)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        layout.addWidget(self.cover, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text, 1)

        # Clicks anywhere on the card select it; the labels already pass clicks up to the card.
        self.cover.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_selected(self, selected: bool) -> None:
        set_property(self, "selected", selected)

    def mousePressEvent(self, event: QtGui.QMouseEvent | None) -> None:
        self.clicked.emit(self.index)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent | None) -> None:
        self.activated.emit(self.index)


class CandidateStrip(QtWidgets.QScrollArea):
    """A row of candidate cards, one of which is selected."""

    currentChanged = QtCore.pyqtSignal(int)
    activated = QtCore.pyqtSignal(int)

    def __init__(self, cache_dir: pathlib.Path | None) -> None:
        super().__init__()
        self.setObjectName("candidateStrip")
        self.cache_dir = cache_dir
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAccessibleName("Candidate matches")
        self.cards: list[CandidateCard] = []
        self._current = -1
        holder = QtWidgets.QWidget()
        holder.setObjectName("candidateHolder")
        self.row = QtWidgets.QHBoxLayout(holder)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(10)
        self.row.addStretch(1)
        self.setWidget(holder)

    def set_candidates(self, matches: list[IssueResult]) -> None:
        for card in self.cards:
            self.row.removeWidget(card)
            card.deleteLater()
        self.cards = []
        self._current = -1
        for i, match in enumerate(matches):
            card = CandidateCard(i, match, self.cache_dir, best=i == 0)
            card.clicked.connect(self.set_current)
            card.activated.connect(self.activated)
            self.row.insertWidget(i, card)
            self.cards.append(card)
        if self.cards:
            self.set_current(0)

    def count(self) -> int:
        return len(self.cards)

    def current_index(self) -> int:
        return self._current

    def current_match(self) -> IssueResult | None:
        return self.cards[self._current].match if 0 <= self._current < len(self.cards) else None

    def set_current(self, index: int) -> None:
        if not 0 <= index < len(self.cards):
            return
        changed = index != self._current
        self._current = index
        for card in self.cards:
            card.set_selected(card.index == index)
        self.ensureWidgetVisible(self.cards[index])
        if changed:
            self.currentChanged.emit(index)


class AutoTagReviewPanel(QtWidgets.QWidget):
    """Inbox-style review of the latest Auto-Tag run."""

    openRequested = QtCore.pyqtSignal(object)  # ComicArchive
    matchesWritten = QtCore.pyqtSignal(list)  # list[ComicArchive]
    stopRequested = QtCore.pyqtSignal()
    ratelimit = QtCore.pyqtSignal(float, float)
    logRequested = QtCore.pyqtSignal()
    countsChanged = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None, cache_dir: pathlib.Path | None) -> None:
        super().__init__(parent)
        self.setObjectName("autoTagReview")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.items: list[ReviewItem] = []
        self.config: ct_ns | None = None
        self.talker: ComicTalker | None = None
        self.colors = dict(DEFAULT_COLORS)
        self._outcome = Outcome.needs_review
        self._current_md = GenericMetadata()
        self._run_archives: list[ComicArchive] = []
        self._thumbs = ThumbnailCache(self)
        self.running = False

        # ----- sidebar -----
        self.categoryList = QtWidgets.QListWidget()
        self.categoryList.setObjectName("reviewGroups")
        self.categoryList.setAccessibleName("Result groups")
        self.categoryList.setItemDelegate(GroupDelegate(self))
        self.categoryList.setMouseTracking(True)
        for outcome in Outcome:
            item = QtWidgets.QListWidgetItem(OUTCOME_LABELS[outcome])
            item.setData(_ITEM_ROLE, outcome)
            self.categoryList.addItem(item)
        self.categoryList.currentRowChanged.connect(self._category_changed)

        self.attributionLabel = QtWidgets.QLabel()
        self.attributionLabel.setObjectName("attribution")
        self.attributionLabel.setWordWrap(True)
        self.attributionLabel.setOpenExternalLinks(True)
        self.attributionLabel.setTextFormat(QtCore.Qt.TextFormat.RichText)

        sidebar = QtWidgets.QWidget()
        sidebar.setObjectName("reviewSidebar")
        sidebar.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 10)
        sidebar_layout.setSpacing(0)
        sidebar_layout.addWidget(section_label("This run"))
        sidebar_layout.addWidget(self.categoryList, 1)
        sidebar_layout.addWidget(self.attributionLabel)

        # ----- file list -----
        self.listHeading = section_label("")
        self.fileList = QtWidgets.QListWidget()
        self.fileList.setObjectName("reviewFiles")
        self.fileList.setAccessibleName("Archives in group")
        self.fileList.setItemDelegate(FileDelegate(self))
        self.fileList.setMouseTracking(True)
        self.fileList.setUniformItemSizes(True)
        self.fileList.currentRowChanged.connect(self._file_changed)
        self._thumbs.changed.connect(self.fileList.viewport().update)
        self.fileList.itemDoubleClicked.connect(lambda _item: self.open_current())

        files = QtWidgets.QWidget()
        files.setObjectName("reviewList")
        files.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        files_layout = QtWidgets.QVBoxLayout(files)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.setSpacing(0)
        files_layout.addWidget(self.listHeading)
        files_layout.addWidget(self.fileList, 1)

        # ----- detail -----
        self.heading = QtWidgets.QLabel()
        self.heading.setObjectName("reviewHeading")
        self.heading.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.reasonLabel = chip()
        self.positionLabel = QtWidgets.QLabel()
        self.positionLabel.setObjectName("positionLabel")
        self.positionLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.archiveCover = CoverImageWidget(None, CoverImageWidget.ArchiveMode, None, expand_on_click=True)
        self.archiveCover.showControls = False
        self.archiveCover.setFixedSize(130, 196)
        yours = QtWidgets.QLabel("Your file")
        yours.setObjectName("caption")
        yours.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        your_file = QtWidgets.QVBoxLayout()
        your_file.setSpacing(6)
        your_file.addWidget(self.archiveCover)
        your_file.addWidget(yours)
        your_file.addStretch(1)

        self.candidateStrip = CandidateStrip(cache_dir)
        self.candidateStrip.currentChanged.connect(self._candidate_changed)
        self.candidateStrip.activated.connect(lambda _i: self.accept_current())
        self.candidateStrip.setMinimumHeight(122)

        self.matchCover = CoverImageWidget(None, CoverImageWidget.URLMode, cache_dir, expand_on_click=False)
        self.matchCover.showControls = False
        self.matchCover.setFixedSize(66, 100)
        self.messageLabel = QtWidgets.QLabel()
        self.messageLabel.setObjectName("messageLabel")
        self.messageLabel.setWordWrap(True)
        message_page = QtWidgets.QWidget()
        message_layout = QtWidgets.QHBoxLayout(message_page)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(12)
        message_layout.addWidget(self.matchCover, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        message_layout.addWidget(self.messageLabel, 1, QtCore.Qt.AlignmentFlag.AlignTop)

        self.candidateArea = QtWidgets.QStackedWidget()
        self.candidateArea.addWidget(self.candidateStrip)
        self.candidateArea.addWidget(message_page)
        self.candidateArea.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Maximum)

        self.diffTable = QtWidgets.QTableWidget(0, 3)
        self.diffTable.setObjectName("diffTable")
        self.diffTable.setAccessibleName("Changes from selected match")
        self.diffTable.setHorizontalHeaderLabels(["Field", "In file now", "After accepting"])
        self.diffTable.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.diffTable.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.diffTable.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.diffTable.setShowGrid(False)
        self.diffTable.verticalHeader().hide()
        self.diffTable.horizontalHeader().setStretchLastSection(True)
        self.diffTable.horizontalHeader().setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

        self.btnAccept = QtWidgets.QPushButton("Accept match")
        self.btnAccept.setProperty("primary", True)
        self.btnAccept.setToolTip("Write the selected match to the archive (Enter)")
        self.btnSearch = QtWidgets.QPushButton("Search by hand   /")
        self.btnSearch.setToolTip("Find the right series and issue yourself (/)")
        self.btnOpen = QtWidgets.QPushButton("Open in editor   E")
        self.btnOpen.setToolTip("Edit every field of this archive (E)")
        self.btnSkip = QtWidgets.QPushButton("Skip for now   S")
        self.btnSkip.setToolTip("Leave this archive for later and go to the next one (S)")
        self.btnAccept.clicked.connect(self.accept_current)
        self.btnSearch.clicked.connect(self.search_current)
        self.btnOpen.clicked.connect(self.open_current)
        self.btnSkip.clicked.connect(self.next_item)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(self.heading)
        header.addWidget(self.reasonLabel)
        header.addStretch(1)
        header.addWidget(self.positionLabel)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(8)
        for button in (self.btnAccept, self.btnSearch, self.btnOpen, self.btnSkip):
            buttons.addWidget(button)
        buttons.addStretch(1)

        review_page = QtWidgets.QWidget()
        review_layout = QtWidgets.QVBoxLayout(review_page)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(14)
        review_layout.addWidget(self.candidateArea)
        review_layout.addWidget(self.diffTable, 1)
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
        body.setSpacing(18)
        body.addLayout(your_file)
        body.addWidget(self.bodyStack, 1)

        detail = QtWidgets.QWidget()
        detail.setObjectName("reviewDetail")
        detail.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        detail_layout = QtWidgets.QVBoxLayout(detail)
        detail_layout.setContentsMargins(18, 16, 18, 16)
        detail_layout.setSpacing(14)
        detail_layout.addLayout(header)
        detail_layout.addLayout(body, 1)
        self.detail = detail

        self.emptyLabel = QtWidgets.QLabel("Nothing in this group.")
        self.emptyLabel.setObjectName("emptyLabel")
        self.emptyLabel.setWordWrap(True)
        self.emptyLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.detailStack = QtWidgets.QStackedWidget()
        self.detailStack.setObjectName("reviewDetailStack")
        self.detailStack.addWidget(detail)
        self.detailStack.addWidget(self.emptyLabel)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setObjectName("reviewSplitter")
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(sidebar)
        splitter.addWidget(files)
        splitter.addWidget(self.detailStack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([200, 300, 800])
        sidebar.setMinimumWidth(170)
        files.setMinimumWidth(220)
        self.splitter = splitter

        # ----- run bar and status line -----
        self.progressBar = QtWidgets.QProgressBar()
        self.progressBar.setObjectName("runProgress")
        self.progressBar.setAccessibleName("Auto-Tag progress")
        self.progressBar.setTextVisible(False)
        self.progressBar.setFixedHeight(8)
        self.runTitle = QtWidgets.QLabel("Auto-tagging")
        self.runTitle.setObjectName("runTitle")
        self.progressLabel = QtWidgets.QLabel()
        self.progressLabel.setObjectName("runCount")
        self.progressLabel.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.btnLog = QtWidgets.QPushButton("Show details")
        self.btnLog.setToolTip("Show the covers being compared and the run's log")
        self.btnLog.clicked.connect(self.logRequested)
        self.btnStop = QtWidgets.QPushButton("Stop")
        self.btnStop.setToolTip("Stop after the archive being identified now")
        self.btnStop.clicked.connect(self._stop)
        self.runBar = QtWidgets.QWidget()
        self.runBar.setObjectName("runBar")
        self.runBar.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        run_layout = QtWidgets.QHBoxLayout(self.runBar)
        run_layout.setContentsMargins(14, 8, 14, 8)
        run_layout.setSpacing(12)
        run_layout.addWidget(self.runTitle)
        run_layout.addWidget(self.progressLabel)
        run_layout.addWidget(self.progressBar, 1)
        run_layout.addWidget(self.btnLog)
        run_layout.addWidget(self.btnStop)
        self.runBar.hide()

        self.hintLabel = QtWidgets.QLabel(
            "J / K  next or previous    1–9  pick a match    Enter  accept    Esc  back to matches"
        )
        self.doneLabel = QtWidgets.QLabel("Accepted files move to Tagged and the next one opens")
        status = QtWidgets.QWidget()
        status.setObjectName("reviewStatus")
        status.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        status_layout = QtWidgets.QHBoxLayout(status)
        status_layout.setContentsMargins(14, 5, 14, 5)
        status_layout.setSpacing(18)
        status_layout.addWidget(self.hintLabel)
        status_layout.addWidget(self.doneLabel)
        status_layout.addStretch(1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.runBar)
        layout.addWidget(splitter, 1)
        layout.addWidget(status)

        _shortcut(self, "Return", self.accept_current)
        _shortcut(self, "Enter", self.accept_current)
        _shortcut(self, "/", self.search_current)
        _shortcut(self, "E", self.open_current)
        _shortcut(self, "S", self.next_item)
        _shortcut(self, "J", self.next_item)
        _shortcut(self, "K", self.previous_item)
        _shortcut(self, "Escape", self._escape)
        for n in range(1, 10):
            _shortcut(self, str(n), functools.partial(self._pick_number, n - 1))

        self._refresh()

    # ----- appearance -----

    def set_colors(self, colors: dict[str, str]) -> None:
        self.colors.update(colors)
        self.categoryList.viewport().update()
        self.fileList.viewport().update()

    def thumbnail(self, archive: ComicArchive) -> QtGui.QPixmap | None:
        return self._thumbs.get(archive.path)

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
        self._thumbs.clear()

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
        self.progressLabel.setText(f"0 / {len(archives)}")
        self.runTitle.setText("Auto-tagging")
        self.btnStop.setEnabled(True)
        self.runBar.show()
        self._refresh()

    def set_progress(self, done: int, total: int, path: object) -> None:
        self.progressBar.setRange(0, total)
        self.progressBar.setValue(done)
        name = getattr(path, "name", "")
        self.progressLabel.setText(f"{done} / {total}")
        self.progressLabel.setToolTip(f"Identifying {name}" if name else "")

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
        self.runTitle.setText("Stopping after the current archive…")
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
        if self.current_item() is None or self.candidateArea.currentWidget() is not self.candidateStrip:
            return None
        return self.candidateStrip.current_match()

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
        self._thumbs.forget(item.archive.path)
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

    def _pick_number(self, index: int) -> None:
        if not self._searching() and self.candidateArea.currentWidget() is self.candidateStrip:
            self.candidateStrip.set_current(index)

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
            entry = self.categoryList.item(row)
            if entry is not None:
                entry.setText(f"{OUTCOME_LABELS[outcome]}  ({count})")
                entry.setData(QtCore.Qt.ItemDataRole.UserRole + 1, count)
            if outcome == self._outcome:
                self.categoryList.setCurrentRow(row)
        self.categoryList.blockSignals(False)
        self.listHeading.setText(f"{OUTCOME_LABELS[self._outcome]} · {len(self.items_in(self._outcome))}".upper())
        self.countsChanged.emit()

    @staticmethod
    def _list_entry(item: ReviewItem) -> QtWidgets.QListWidgetItem:
        entry = QtWidgets.QListWidgetItem(f"{item.name}\n{item.reason}")
        entry.setData(_ITEM_ROLE, item)
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
            self.matchCover.clear()
            return

        self.detailStack.setCurrentWidget(self.detail)
        self.heading.setText(item.name)
        self.reasonLabel.setText(item.reason)
        set_property(self.reasonLabel, "tone", "ok" if item.resolution else OUTCOME_TONES[item.outcome])
        self.positionLabel.setText(f"{row + 1} of {self.fileList.count()}")
        self.archiveCover.set_archive(item.archive)

        self._current_md = GenericMetadata()
        if self.config is not None:
            md, _, error = read_configured_tags(item.archive, self.config.Runtime_Options__tags_read, self.config)
            if error is None:
                self._current_md = md

        candidates = item.candidates if item.outcome == Outcome.needs_review else []
        if candidates:
            self.candidateArea.setCurrentWidget(self.candidateStrip)
            self.candidateStrip.set_candidates(candidates)
            self._candidate_changed(self.candidateStrip.current_index())
        else:
            self.candidateStrip.set_candidates([])
            self.candidateArea.setCurrentWidget(self.candidateArea.widget(1))
            self.messageLabel.setText(self._message_for(item))
            shown = item.result.md if item.result is not None and item.result.md is not None else None
            if shown is not None:
                self._show_candidate_md(shown)
            else:
                self.matchCover.clear()
                self.matchCover.setVisible(False)
                self.diffTable.setRowCount(0)

        self.btnAccept.setEnabled(bool(candidates) or item.can_retry_write)
        self._label_accept()
        self.btnSkip.setEnabled(row + 1 < self.fileList.count())

    def _label_accept(self) -> None:
        item = self.current_item()
        if item is not None and item.can_retry_write:
            self.btnAccept.setText("Retry write   Enter")
        elif self.candidateStrip.count():
            self.btnAccept.setText(f"Accept match {self.candidateStrip.current_index() + 1}   Enter")
        else:
            self.btnAccept.setText("Accept match   Enter")

    def _message_for(self, item: ReviewItem) -> str:
        if item.outcome == Outcome.tagged:
            return f"{item.reason}. If this looks wrong, search by hand to pick a different issue."
        if item.outcome == Outcome.no_match:
            return "Auto-Tag couldn't find this issue. Search by hand to pick it yourself."
        if item.can_retry_write:
            return f"{item.reason}. Check the file isn't read-only or open elsewhere, then retry."
        return f"{item.reason}. Search by hand, or open it in the editor to see more."

    def _candidate_changed(self, index: int) -> None:
        match = self.current_candidate()
        if match is not None:
            self._show_candidate_md(match.md)
        self._label_accept()

    def _show_candidate_md(self, md: GenericMetadata) -> None:
        if self.candidateArea.currentWidget() is not self.candidateStrip:
            urls = [image.URL for image in [md._cover_image, *md._alternate_images] if image]
            self.matchCover.setVisible(bool(urls))
            self.matchCover.set_url_list(urls[:1])
        rows = metadata_diff(self._current_md, md)
        self.diffTable.setRowCount(len(rows))
        ink, muted, ok = QtGui.QColor(self.colors["ink"]), QtGui.QColor(self.colors["muted"]), self.colors["ok"]
        for r, (label, old, new) in enumerate(rows):
            changed = old != new
            for c, text in enumerate((label, old, new)):
                cell = QtWidgets.QTableWidgetItem(text)
                font = cell.font()
                if c == 0:
                    cell.setForeground(muted)
                elif c == 1:
                    cell.setForeground(muted)
                    font.setStrikeOut(changed and old != "—")
                else:
                    cell.setForeground(QtGui.QColor(ok) if changed else ink)
                    font.setWeight(QtGui.QFont.Weight.DemiBold if changed else QtGui.QFont.Weight.Normal)
                cell.setFont(font)
                self.diffTable.setItem(r, c, cell)
        self.diffTable.resizeColumnsToContents()
        self.diffTable.horizontalHeader().setStretchLastSection(True)
