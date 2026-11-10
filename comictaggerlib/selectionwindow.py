from __future__ import annotations

import logging
from typing import Generic, TypeVar

from PyQt6 import QtCore, QtWidgets, uic
from PyQt6.QtCore import Qt, QUrl, pyqtSignal

from comictaggerlib.coverimagewidget import CoverImageWidget
from comictaggerlib.ctsettings import ct_ns
from comictaggerlib.ui import qtutils, ui_path
from comictalker.comictalker import ComicTalker

logger = logging.getLogger(__name__)
SelectionItem = TypeVar("SelectionItem")


class SelectionWindow(QtWidgets.QDialog, Generic[SelectionItem]):
    ui_file = ui_path / "seriesselectionwindow.ui"
    CoverImageMode = CoverImageWidget.URLMode
    ratelimit = pyqtSignal(float, float)

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        config: ct_ns,
        talker: ComicTalker,
    ) -> None:
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        with self.ui_file.open(encoding="utf-8") as uifile:
            uic.loadUi(uifile, self)

        self.cover_widget = CoverImageWidget(
            self.coverImageContainer,
            self.CoverImageMode,
            config.Runtime_Options__config.user_cache_dir,
        )
        gridlayout = QtWidgets.QGridLayout(self.coverImageContainer)
        gridlayout.addWidget(self.cover_widget)
        gridlayout.setContentsMargins(0, 0, 0, 0)

        self.teDescription: QtWidgets.QWidget
        webengine = qtutils.new_web_view(self)
        if webengine:
            self.teDescription = qtutils.replaceWidget(self.splitter, self.teDescription, webengine)
            logger.info("successfully loaded QWebEngineView")
        else:
            logger.info("failed to open QWebEngineView")

        self.setWindowFlags(
            QtCore.Qt.WindowType(
                self.windowFlags()
                | QtCore.Qt.WindowType.WindowSystemMenuHint
                | QtCore.Qt.WindowType.WindowMaximizeButtonHint
            )
        )

        self.config = config
        self.talker = talker
        self.issue_id: str = ""

        # Display talker logo and set url
        self.lblIssuesSourceName.setText(talker.attribution)

        self.imageSourceWidget = CoverImageWidget(
            self.imageSourceLogo,
            CoverImageWidget.URLMode,
            config.Runtime_Options__config.user_cache_dir,
            False,
        )
        self.imageSourceWidget.showControls = False
        gridlayoutSourceLogo = QtWidgets.QGridLayout(self.imageSourceLogo)
        gridlayoutSourceLogo.addWidget(self.imageSourceWidget)
        gridlayoutSourceLogo.setContentsMargins(0, 2, 0, 0)
        self.imageSourceWidget.set_url(talker.logo_url)

        # Set the minimum row height to the default.
        # this way rows will be more consistent when resizeRowsToContents is called
        self.twList.verticalHeader().setMinimumSectionSize(self.twList.verticalHeader().defaultSectionSize())
        self.twList.resizeColumnsToContents()
        self.twList.currentItemChanged.connect(self.current_item_changed)
        self.twList.cellDoubleClicked.connect(self.cell_double_clicked)
        self.leFilter.textChanged.connect(self.filter)
        self.twList.selectRow(0)
        qtutils.add_dialog_shortcuts(self)

    def perform_query(self, refresh: bool = False) -> None:
        raise NotImplementedError

    def cell_double_clicked(self, r: int, c: int) -> None:
        raise NotImplementedError

    def update_row(self, row: int, series: SelectionItem) -> None:
        raise NotImplementedError

    def set_description(self, widget: QtWidgets.QWidget, text: str) -> None:
        if isinstance(widget, QtWidgets.QTextEdit):
            widget.setText(text.replace("</figure>", "</div>").replace("<figure", "<div"))
        else:
            html = text
            widget.setHtml(html, QUrl(self.talker.website))

    def filter(self, text: str) -> None:
        rows = set(range(self.twList.rowCount()))
        for r in rows:
            self.twList.showRow(r)
        if text.strip():
            shown_rows = {x.row() for x in self.twList.findItems(text, QtCore.Qt.MatchFlag.MatchContains)}
            for r in rows - shown_rows:
                self.twList.hideRow(r)

    def _fetch(self, row: int) -> SelectionItem:
        raise NotImplementedError

    def on_ratelimit(self, full_time: float, sleep_time: float) -> None:
        self.ratelimit.emit(full_time, sleep_time)

    def current_item_changed(self, curr: QtCore.QModelIndex | None, prev: QtCore.QModelIndex | None) -> None:
        if curr is None:
            return
        if prev is not None and prev.row() == curr.row():
            return

        row = curr.row()

        item = self._fetch(row)
        QtWidgets.QApplication.restoreOverrideCursor()

        # Update current record information
        self.update_row(row, item)
