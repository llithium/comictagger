"""A PyQt6 dialog to confirm and configure auto-tagging."""

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

import copy
import logging
from dataclasses import dataclass

from PyQt6 import QtCore, QtWidgets, uic

from comicapi.genericmetadata import GenericMetadata
from comictaggerlib.ctsettings import ct_ns
from comictaggerlib.ui import qtutils, ui_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutoTagSettings:
    remove_after_success: bool
    series_match_identify_thresh: int
    split_words: bool
    search_string: str
    save_on_low_confidence: bool
    use_year_when_identifying: bool
    assume_issue_one: bool
    ignore_leading_numbers_in_filename: bool
    clear_tags: bool
    auto_imprint: bool

    def save_preferences(self, config: ct_ns) -> None:
        config.internal__remove_archive_after_successful_match = self.remove_after_success
        config.Auto_Tag__save_on_low_confidence = self.save_on_low_confidence
        config.Auto_Tag__use_year_when_identifying = self.use_year_when_identifying
        config.Auto_Tag__assume_issue_one = self.assume_issue_one
        config.Auto_Tag__ignore_leading_numbers_in_filename = self.ignore_leading_numbers_in_filename
        config.Auto_Tag__clear_tags = self.clear_tags

    def new_settings(self, config: ct_ns) -> ct_ns:
        new = copy.copy(config)
        self.save_preferences(new)
        new.Issue_Identifier__series_match_identify_thresh = self.series_match_identify_thresh
        new.Filename_Parsing__split_words = self.split_words
        new.Auto_Tag__issue_id = None
        new.Auto_Tag__metadata = GenericMetadata()
        new.Auto_Tag__auto_imprint = self.auto_imprint
        return new


class AutoTagStartWindow(QtWidgets.QDialog):
    startAutoTag = QtCore.pyqtSignal(AutoTagSettings)

    def __init__(self, parent: QtWidgets.QWidget, config: ct_ns, msg: str) -> None:
        super().__init__(parent)

        with (ui_path / "autotagstartwindow.ui").open(encoding="utf-8") as uifile:
            uic.loadUi(uifile, self)
        self.label.setText(msg)

        self.setWindowFlags(
            QtCore.Qt.WindowType(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)
        )

        self.config = config

        self.cbxSpecifySearchString.setChecked(False)
        self.cbxSplitWords.setChecked(False)
        self.sbNameMatchSearchThresh.setValue(self.config.Issue_Identifier__series_match_identify_thresh)
        self.leSearchString.setEnabled(False)

        self.cbxSaveOnLowConfidence.setChecked(self.config.Auto_Tag__save_on_low_confidence)
        self.cbxDontUseYear.setChecked(not self.config.Auto_Tag__use_year_when_identifying)
        self.cbxAssumeIssueOne.setChecked(self.config.Auto_Tag__assume_issue_one)
        self.cbxIgnoreLeadingDigitsInFilename.setChecked(self.config.Auto_Tag__ignore_leading_numbers_in_filename)
        self.cbxClearMetadata.setChecked(self.config.Auto_Tag__clear_tags)
        self.cbxRemoveAfterSuccess.setChecked(self.config.internal__remove_archive_after_successful_match)
        self.cbxAutoImprint.setChecked(self.config.Auto_Tag__auto_imprint)

        nlmt_tip = """<html>The <b>Name Match Ratio Threshold: Auto-Identify</b> is for eliminating automatic
                search matches that are too long compared to your series name search. The lower
                it is, the more likely to have a good match, but each search will take longer and
                use more bandwidth. Too high, and only the very closest matches will be explored.</html>"""

        self.sbNameMatchSearchThresh.setToolTip(nlmt_tip)

        ss_tip = """<html>
            The <b>series search string</b> specifies the search string to be used for all selected archives.
            Use this when trying to match archives with hard-to-parse or incorrect filenames.  All archives selected
            should be from the same series.
            </html>"""
        self.leSearchString.setToolTip(ss_tip)
        self.cbxSpecifySearchString.setToolTip(ss_tip)

        self.cbxSpecifySearchString.stateChanged.connect(self.search_string_toggle)

        self.adjustSize()
        self.setModal(True)
        qtutils.add_dialog_shortcuts(self)

    def search_string_toggle(self) -> None:
        enable = self.cbxSpecifySearchString.isChecked()
        self.leSearchString.setEnabled(enable)

    def accept(self) -> None:
        QtWidgets.QDialog.accept(self)

        self.startAutoTag.emit(
            AutoTagSettings(
                save_on_low_confidence=self.cbxSaveOnLowConfidence.isChecked(),
                use_year_when_identifying=not self.cbxDontUseYear.isChecked(),
                assume_issue_one=self.cbxAssumeIssueOne.isChecked(),
                ignore_leading_numbers_in_filename=self.cbxIgnoreLeadingDigitsInFilename.isChecked(),
                clear_tags=self.cbxClearMetadata.isChecked(),
                auto_imprint=self.cbxAutoImprint.isChecked(),
                remove_after_success=self.cbxRemoveAfterSuccess.isChecked(),
                series_match_identify_thresh=self.sbNameMatchSearchThresh.value(),
                split_words=self.cbxSplitWords.isChecked(),
                search_string=self.leSearchString.text() if self.cbxSpecifySearchString.isChecked() else "",
            )
        )
