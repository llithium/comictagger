"""A PyQt6 dialog to show identification progress and logs."""

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
import pathlib

from PyQt6 import QtCore, QtWidgets, uic

from comicapi import utils
from comicapi.comicarchive import ComicArchive, tags
from comictaggerlib.coverimagewidget import CoverImageWidget
from comictaggerlib.ctsettings.settngs_namespace import SettngsNS
from comictaggerlib.issueidentifier import IssueIdentifierCancelled
from comictaggerlib.md import parse_archive_filename, read_configured_tags, write_selected_tags
from comictaggerlib.resulttypes import Action, OnlineMatchResults, Result, Status
from comictaggerlib.tag import identify_comic
from comictaggerlib.ui import qtutils, ui_path
from comictalker.comictalker import ComicTalker, RLCallBack

logger = logging.getLogger(__name__)


class AutoTagThread(QtCore.QThread):  # TODO: re-check thread semantics. Specifically with signals
    autoTagComplete = QtCore.pyqtSignal(OnlineMatchResults, list)
    autoTagLogMsg = QtCore.pyqtSignal(str)
    autoTagProgress = QtCore.pyqtSignal(object, object, object, bytes, bytes)  # see progress_callback
    ratelimit = QtCore.pyqtSignal(float, float)

    def __init__(
        self, series_override: str, ca_list: list[ComicArchive], config: SettngsNS, talker: ComicTalker
    ) -> None:
        QtCore.QThread.__init__(self)
        self.series_override = series_override
        self.ca_list = ca_list
        self.config = config
        self.talker = talker

    def log_output(self, text: str) -> None:
        self.check_canceled()
        self.autoTagLogMsg.emit(str(text))

    def check_canceled(self) -> None:
        if self.isInterruptionRequested():
            raise IssueIdentifierCancelled

    def progress_callback(
        self, cur: int | None, total: int | None, path: pathlib.Path | None, archive_image: bytes, remote_image: bytes
    ) -> None:
        self.autoTagProgress.emit(cur, total, path, archive_image, remote_image)

    def run(self) -> None:
        match_results = OnlineMatchResults()
        archives_to_remove = []
        try:
            for prog_idx, ca in enumerate(self.ca_list):
                self.check_canceled()
                self.log_output("==========================================================================\n")
                self.log_output(f"Auto-Tagging {prog_idx} of {len(self.ca_list)}\n")
                self.log_output(f"{ca.path}\n")
                if ca.is_writable():
                    result = self.identify_and_tag_single_archive(ca, prog_idx)
                    match_results.record(result)
                    if result.status == Status.success and self.config.internal__remove_archive_after_successful_match:
                        archives_to_remove.append(ca)
        except IssueIdentifierCancelled:
            pass
        finally:
            self.autoTagComplete.emit(match_results, archives_to_remove)

    def on_rate_limit(self, full_time: float, sleep_time: float) -> None:
        self.log_output(
            f"Rate limit reached: {full_time:.0f}s until next request. Waiting {sleep_time:.0f}s for ratelimit"
        )
        self.ratelimit.emit(full_time, sleep_time)

    def identify_and_tag_single_archive(self, ca: ComicArchive, progress: int) -> Result:
        md, tags_used, error = read_configured_tags(ca, self.config.Runtime_Options__tags_read, self.config)
        if error is not None:
            logger.error("Failed to load tags from %s: %s", ca.path, error)
            return Result(Action.save, Status.read_failure, ca.path, tags_read=tags_used)

        cover_idx = next(iter(md.get_cover_page_index_list()), 0)
        self.progress_callback(progress, len(self.ca_list), ca.path, ca.get_page(cover_idx), b"")
        if md.is_empty:
            md = parse_archive_filename(ca, self.config)

        if self.series_override:
            md.series = self.series_override
        query_md = md.copy()
        if not query_md.issue and not query_md.is_empty:
            query_md.issue = "1" if self.config.Auto_Tag__assume_issue_one else utils.xlate(query_md.volume)

        def on_progress(x: int, y: int, image: bytes) -> None:
            self.check_canceled()
            self.progress_callback(None, None, None, b"", image)

        self.check_canceled()
        result = identify_comic(
            ca,
            md,
            tags_used,
            self.config,
            self.talker,
            self.log_output,
            on_rate_limit=RLCallBack(self.on_rate_limit, 60),
            on_progress=on_progress,
            query_md=query_md,
            series_override=self.series_override,
        )
        self.check_canceled()

        if result.status == Status.success:
            assert result.md is not None
            result.tags_written, failed = write_selected_tags(ca, result.md, self.config.Runtime_Options__tags_write)
            ca.reset_cache()
            if failed is None:
                self.autoTagLogMsg.emit("Save complete!\n")
            else:
                result.status = Status.write_failure
                self.autoTagLogMsg.emit(f"{tags[failed].name()} save failed! Aborting any additional tag saves.\n")

        return result

    def cancel(self) -> None:
        self.requestInterruption()


class AutoTagProgressWindow(QtWidgets.QDialog):
    cancel = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget, talker: ComicTalker) -> None:
        super().__init__(parent)

        with (ui_path / "autotagprogresswindow.ui").open(encoding="utf-8") as uifile:
            uic.loadUi(uifile, self)

        self.lblSourceName.setText(talker.attribution)

        self.archiveCoverWidget = CoverImageWidget(self.archiveCoverContainer, CoverImageWidget.DataMode, None, False)
        gridlayout = QtWidgets.QGridLayout(self.archiveCoverContainer)
        gridlayout.addWidget(self.archiveCoverWidget)
        gridlayout.setContentsMargins(0, 0, 0, 0)

        self.testCoverWidget = CoverImageWidget(self.testCoverContainer, CoverImageWidget.DataMode, None, False)
        gridlayout = QtWidgets.QGridLayout(self.testCoverContainer)
        gridlayout.addWidget(self.testCoverWidget)
        gridlayout.setContentsMargins(0, 0, 0, 0)

        self.setWindowFlags(
            QtCore.Qt.WindowType(
                self.windowFlags()
                | QtCore.Qt.WindowType.WindowSystemMenuHint
                | QtCore.Qt.WindowType.WindowMaximizeButtonHint
            )
        )
        qtutils.add_dialog_shortcuts(self)

    def set_archive_image(self, img_data: bytes) -> None:
        self.set_cover_image(img_data, self.archiveCoverWidget)

    def set_test_image(self, img_data: bytes) -> None:
        self.set_cover_image(img_data, self.testCoverWidget)

    def set_cover_image(self, img_data: bytes, widget: CoverImageWidget) -> None:
        widget.set_image_data(img_data)
        QtCore.QCoreApplication.processEvents()

    # @QtCore.pyqtSlot(int, int, 'Optional[pathlib.Path]', bytes, bytes)
    def on_progress(
        self, x: int | None, y: int | None, title: pathlib.Path | None, archive_image: bytes, remote_image: bytes
    ) -> None:
        if x is not None and y is not None:
            self.progressBar: QtWidgets.QProgressBar
            self.progressBar.setValue(x)
            self.progressBar.setMaximum(y)
        if title:
            self.setWindowTitle(str(title))
        if archive_image:
            self.set_archive_image(archive_image)
        if remote_image:
            self.set_test_image(remote_image)

    def reject(self) -> None:
        self.cancel.emit()
