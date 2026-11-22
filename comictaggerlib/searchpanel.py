"""An embeddable panel that finds a series and picks an issue in one place.

It replaces the two stacked windows (series, then issues) used by Search Online
for the Auto-Tag review flow. Network calls run on worker threads, and stale
replies are dropped when the user searches again before they arrive.
"""

from __future__ import annotations

import logging
import pathlib
from collections.abc import Callable
from typing import Any

from PyQt6 import QtCore, QtWidgets

from comicapi import utils
from comicapi.genericmetadata import ComicSeries, GenericMetadata
from comicapi.issuestring import IssueString
from comictaggerlib.coverimagewidget import CoverImageWidget
from comictaggerlib.ctsettings import ct_ns
from comictaggerlib.seriesmatch import sort_series_results
from comictalker.comictalker import ComicTalker, RLCallBack, TalkerError

logger = logging.getLogger(__name__)


class _Call(QtCore.QThread):
    """Run one blocking call off the UI thread and report the outcome."""

    succeeded = QtCore.pyqtSignal(int, object)
    failed = QtCore.pyqtSignal(int, object)

    def __init__(self, token: int, fn: Callable[[], Any], parent: QtCore.QObject) -> None:
        super().__init__(parent)
        self.token = token
        self.fn = fn

    def run(self) -> None:
        try:
            value = self.fn()
        except Exception as e:  # reported to the user by the panel
            if not isinstance(e, TalkerError):
                logger.exception("Search failed")
            self.failed.emit(self.token, e)
        else:
            self.succeeded.emit(self.token, value)


def issue_sort_key(issue: GenericMetadata) -> tuple[float, str]:
    number = IssueString(issue.issue).as_float()
    return (number if number is not None else float("inf"), issue.issue or "")


def best_issue_row(issues: list[GenericMetadata], issue_number: str) -> int:
    """The row of the issue whose number matches the one being looked for, else the first row."""
    wanted = IssueString(issue_number).as_string().casefold() if issue_number else ""
    for row, issue in enumerate(issues):
        if wanted and IssueString(issue.issue).as_string().casefold() == wanted:
            return row
    return 0


class SearchPanel(QtWidgets.QWidget):
    """Search a series name, pick a series, then pick an issue, without leaving the panel."""

    issueChosen = QtCore.pyqtSignal(object, object)  # GenericMetadata (issue), ComicSeries
    canceled = QtCore.pyqtSignal()
    ratelimit = QtCore.pyqtSignal(float, float)

    def __init__(self, parent: QtWidgets.QWidget | None, cache_dir: pathlib.Path | None) -> None:
        super().__init__(parent)
        self.setObjectName("searchPanel")
        self.config: ct_ns | None = None
        self.talker: ComicTalker | None = None
        self.year: int | None = None
        self.series: list[ComicSeries] = []
        self.issues: list[GenericMetadata] = []
        self._token = 0
        self._calls: set[_Call] = set()

        self.leSeries = QtWidgets.QLineEdit()
        self.leSeries.setPlaceholderText("Series name")
        self.leSeries.setAccessibleName("Series name")
        self.leIssue = QtWidgets.QLineEdit()
        self.leIssue.setPlaceholderText("Issue")
        self.leIssue.setAccessibleName("Issue number")
        self.leIssue.setMaximumWidth(80)
        self.btnSearch = QtWidgets.QPushButton("Search")
        self.leSeries.returnPressed.connect(self.search)
        self.leIssue.returnPressed.connect(self._issue_number_changed)
        self.btnSearch.clicked.connect(self.search)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)

        self.seriesTable = self._table(["Series", "Year", "Issues", "Publisher"], "Series results")
        self.seriesTable.currentCellChanged.connect(self._series_changed)
        self.issueTable = self._table(["Issue", "Date", "Title"], "Issues in series")
        self.issueTable.currentCellChanged.connect(self._issue_changed)
        self.issueTable.cellDoubleClicked.connect(lambda _r, _c: self.choose())

        self.cover = CoverImageWidget(None, CoverImageWidget.AltCoverMode, cache_dir, expand_on_click=False)
        self.cover.setMinimumSize(110, 165)

        self.btnUse = QtWidgets.QPushButton("Use this issue")
        self.btnUse.setDefault(True)
        self.btnUse.setEnabled(False)
        self.btnUse.clicked.connect(self.choose)
        self.btnCancel = QtWidgets.QPushButton("Back to matches")
        self.btnCancel.clicked.connect(self.cancel)

        query = QtWidgets.QHBoxLayout()
        query.addWidget(self.leSeries, 1)
        query.addWidget(self.leIssue)
        query.addWidget(self.btnSearch)

        lists = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        lists.addWidget(self.seriesTable)
        lists.addWidget(self.issueTable)
        lists.setStretchFactor(0, 3)
        lists.setStretchFactor(1, 2)

        body = QtWidgets.QHBoxLayout()
        body.addWidget(lists, 1)
        body.addWidget(self.cover)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.btnUse)
        buttons.addWidget(self.btnCancel)
        buttons.addStretch(1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(query)
        layout.addWidget(self.status)
        layout.addLayout(body, 1)
        layout.addLayout(buttons)

    @staticmethod
    def _table(headers: list[str], name: str) -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget(0, len(headers))
        table.setAccessibleName(name)
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        return table

    # ----- public -----

    def start(self, series_name: str, issue_number: str, year: int | None, config: ct_ns, talker: ComicTalker) -> None:
        """Fill the query from what's known about the archive and search right away."""
        self.config = config
        self.talker = talker
        self.year = year
        self.leSeries.setText(series_name)
        self.leIssue.setText(issue_number)
        self._clear_results()
        if series_name.strip():
            self.search()
        else:
            self.status.setText("Type a series name and press Enter.")
            self.leSeries.setFocus()

    def search(self) -> None:
        name = self.leSeries.text().strip()
        if not name or self.talker is None:
            self.status.setText("Type a series name to search.")
            return
        talker = self.talker
        self._clear_results()
        self.status.setText(f"Searching {talker.name} for “{name}”…")
        self._run(
            lambda: talker.search_for_series(
                name,
                on_rate_limit=RLCallBack(lambda full, sleep: self.ratelimit.emit(full, sleep), 10),
            ),
            self._series_found,
        )

    def choose(self) -> None:
        series = self.current_series()
        issue = self.current_issue()
        if series is not None and issue is not None:
            self.issueChosen.emit(issue, series)

    def cancel(self) -> None:
        self._token += 1  # drop replies still in flight
        self.canceled.emit()

    def current_series(self) -> ComicSeries | None:
        row = self.seriesTable.currentRow()
        return self.series[row] if 0 <= row < len(self.series) else None

    def current_issue(self) -> GenericMetadata | None:
        row = self.issueTable.currentRow()
        return self.issues[row] if 0 <= row < len(self.issues) else None

    def wait_for_idle(self, ms: int = 5000) -> None:
        for call in list(self._calls):
            call.wait(ms)

    # ----- results -----

    def _run(self, fn: Callable[[], Any], done: Callable[[Any], None]) -> None:
        self._token += 1
        call = _Call(self._token, fn, self)
        self._calls.add(call)

        def finished(token: int, value: object) -> None:
            if token == self._token:
                done(value)

        def failed(token: int, error: object) -> None:
            if token == self._token:
                self._show_error(error)

        call.succeeded.connect(finished)
        call.failed.connect(failed)
        call.finished.connect(lambda: self._calls.discard(call))
        call.finished.connect(call.deleteLater)
        call.start()

    def _show_error(self, error: object) -> None:
        if isinstance(error, TalkerError):
            self.status.setText(f"{error.source} couldn't search: {error}")
        else:
            self.status.setText(f"Search failed: {error}")

    def _clear_results(self) -> None:
        self.series = []
        self.issues = []
        self.seriesTable.setRowCount(0)
        self.issueTable.setRowCount(0)
        self.cover.clear()
        self.btnUse.setEnabled(False)

    def _series_found(self, results: object) -> None:
        assert isinstance(results, list)
        series: list[ComicSeries] = results
        if self.config is not None:
            series = sort_series_results(
                series,
                self.leSeries.text().strip(),
                self.year,
                sort_by_year=self.config.Issue_Identifier__sort_series_by_year,
                exact_matches_first=self.config.Issue_Identifier__exact_series_matches_first,
            )
        self.series = series
        if not series:
            self.status.setText("No series found. Try a shorter or different name.")
            return
        self.status.setText(f"{len(series)} series found. Pick one, then pick the issue.")
        self.seriesTable.blockSignals(True)
        self.seriesTable.setRowCount(len(series))
        for row, s in enumerate(series):
            values = (s.name, s.start_year or "", s.count_of_issues or "", s.publisher or "")
            for col, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(str(value))
                cell.setToolTip(str(value))
                self.seriesTable.setItem(row, col, cell)
        self.seriesTable.resizeColumnsToContents()
        self.seriesTable.horizontalHeader().setStretchLastSection(True)
        self.seriesTable.blockSignals(False)
        self.seriesTable.setCurrentCell(0, 0)

    def _series_changed(self, row: int, _col: int, prev_row: int, _prev_col: int) -> None:
        if row == prev_row:
            return
        series = self.current_series()
        if series is None or self.talker is None:
            return
        talker = self.talker
        self.issues = []
        self.issueTable.setRowCount(0)
        self.btnUse.setEnabled(False)
        self.cover.set_url_list([series.image_url] if series.image_url else [])
        self.status.setText(f"Loading issues of {series.name}…")
        self._run(
            lambda: [
                issue
                for issue in talker.fetch_issues_in_series(
                    series.id, on_rate_limit=RLCallBack(lambda full, sleep: self.ratelimit.emit(full, sleep), 10)
                )
                if issue.issue_id is not None
            ],
            self._issues_found,
        )

    def _issues_found(self, results: object) -> None:
        assert isinstance(results, list)
        issues: list[GenericMetadata] = sorted(results, key=issue_sort_key)
        self.issues = issues
        series = self.current_series()
        if not issues:
            self.status.setText("This series has no issues listed. Pick another series.")
            return
        self.status.setText(f"{len(issues)} issues in {series.name if series else 'this series'}.")
        self.issueTable.blockSignals(True)
        self.issueTable.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            date = f"{issue.year or '????'}" + (f"-{int(issue.month):02d}" if issue.month else "")
            for col, value in enumerate((issue.issue or "", date, issue.title or "")):
                cell = QtWidgets.QTableWidgetItem(str(value))
                cell.setToolTip(str(value))
                self.issueTable.setItem(row, col, cell)
        self.issueTable.resizeColumnsToContents()
        self.issueTable.horizontalHeader().setStretchLastSection(True)
        self.issueTable.blockSignals(False)
        self._select_issue_number()

    def _issue_number_changed(self) -> None:
        if self.issues:
            self._select_issue_number()
        else:
            self.search()

    def _select_issue_number(self) -> None:
        row = best_issue_row(self.issues, self.leIssue.text().strip())
        self.issueTable.setCurrentCell(row, 0)
        self._issue_changed(row, 0, -1, -1)

    def _issue_changed(self, row: int, _col: int, prev_row: int, _prev_col: int) -> None:
        issue = self.current_issue()
        self.btnUse.setEnabled(issue is not None)
        if issue is not None:
            urls = [image.URL for image in [issue._cover_image, *issue._alternate_images] if image]
            self.cover.set_url_list(urls)
            self.btnUse.setText(f"Use issue #{issue.issue}" if issue.issue else "Use this issue")


def query_from_metadata(md: GenericMetadata) -> tuple[str, str, int | None]:
    """The series, issue and year to search with, taken from what's in or parsed from an archive."""
    return md.series or "", md.issue or "", utils.xlate_int(md.year)
