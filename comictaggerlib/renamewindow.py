"""A PyQt6 dialog to confirm a rename."""

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
from collections.abc import Callable

import settngs
from PyQt6 import QtCore, QtWidgets, uic
from PyQt6.QtGui import QColorConstants

from comicapi.comicarchive import ComicArchive, tags
from comicapi.genericmetadata import GenericMetadata
from comictaggerlib.ctsettings import ct_ns
from comictaggerlib.filerenamer import MissingRenameDirectory, RenamePlan
from comictaggerlib.md import parse_archive_filename, read_configured_tags
from comictaggerlib.optionalmsgdialog import OptionalMessageDialog
from comictaggerlib.settingswindow import SettingsWindow
from comictaggerlib.ui import qtutils, ui_path
from comictaggerlib.ui.qtutils import center_window_on_parent
from comictalker.comictalker import ComicTalker

logger = logging.getLogger(__name__)


class RenameWindow(QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        comic_archive_list: list[ComicArchive],
        read_tag_ids: list[str],
        config: settngs.Config[ct_ns],
        talkers: dict[str, ComicTalker],
        *,
        rename_example: Callable[[], tuple[GenericMetadata, str] | None] | None = None,
    ) -> None:
        super().__init__(parent)

        with (ui_path / "renamewindow.ui").open(encoding="utf-8") as uifile:
            uic.loadUi(uifile, self)

        self.label.setText(f"Preview (based on {', '.join(tags[tag].name() for tag in read_tag_ids)} tags):")

        self.setWindowFlags(
            QtCore.Qt.WindowType(
                self.windowFlags()
                | QtCore.Qt.WindowType.WindowSystemMenuHint
                | QtCore.Qt.WindowType.WindowMaximizeButtonHint
            )
        )

        self.config = config
        self.talkers = talkers
        self.comic_archive_list = comic_archive_list
        self.read_tag_ids = read_tag_ids
        self.rename_plans: list[RenamePlan] = []
        self.rename_example = rename_example
        self.tag_names_changed = False

        self.btnSettings.clicked.connect(self.modify_settings)

        self.do_preview()
        qtutils.add_dialog_shortcuts(self)

    def do_preview(self) -> None:
        self.twList.setRowCount(0)
        self.rename_plans.clear()
        plans = []
        errors = False
        self.twList.setSortingEnabled(False)
        for ca in self.comic_archive_list:
            md, _, error = read_configured_tags(ca, self.read_tag_ids, self.config[0])
            if error is not None:
                errors = True
                logger.error("Failed to load tags from %s: %s", ca.path, error)
                folder = ca.path.parent
                new_name = ""
            else:
                if md.is_empty:
                    md = parse_archive_filename(ca, self.config[0])
                try:
                    plan = RenamePlan.build(ca, md, self.config[0])
                except MissingRenameDirectory:
                    OptionalMessageDialog.warning(
                        self,
                        "Kapowarr library root required",
                        "Set Destination Directory to the Kapowarr library root before previewing compatible renames.",
                    )
                    return
                except ValueError as e:
                    logger.exception("Invalid format string: %s", self.config[0].File_Rename__template)
                    OptionalMessageDialog.critical(
                        self,
                        "Invalid format string!",
                        f"Your rename template is invalid!\n\n{e}\n\n"
                        "Please consult the template help in the settings and the documentation on the format at "
                        "https://docs.python.org/3/library/string.html#format-string-syntax",
                    )
                    return
                except Exception as e:
                    logger.exception("Formatter failure: %s metadata: %s", self.config[0].File_Rename__template, md)
                    OptionalMessageDialog.critical(
                        self,
                        "The formatter had an issue!",
                        f"The formatter has experienced an unexpected error!\n\n{type(e).__name__}: {e}\n\n"
                        "Please open an issue at https://github.com/llithium/comictagger/issues",
                    )
                    return
                plans.append(plan)
                folder = plan.folder
                new_name = plan.name

            row = self.twList.rowCount()
            self.twList.insertRow(row)
            folder_item = QtWidgets.QTableWidgetItem()
            old_name_item = QtWidgets.QTableWidgetItem()
            new_name_item = QtWidgets.QTableWidgetItem()

            item_text = str(folder)
            folder_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.twList.setItem(row, 0, folder_item)
            folder_item.setText(item_text)
            folder_item.setData(QtCore.Qt.ItemDataRole.ToolTipRole, item_text)

            item_text = str(ca.path.name)
            old_name_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.twList.setItem(row, 1, old_name_item)
            old_name_item.setText(item_text)
            old_name_item.setData(QtCore.Qt.ItemDataRole.ToolTipRole, item_text)

            new_name_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.twList.setItem(row, 2, new_name_item)
            if error is not None:
                new_name_item.setText(f"Error reading tags: {error}")
                new_name_item.setBackground(QColorConstants.Red)
            else:
                new_name_item.setText(new_name)
            new_name_item.setData(QtCore.Qt.ItemDataRole.ToolTipRole, new_name)

        self.rename_plans = plans

        # Adjust column sizes
        self.twList.setVisible(False)
        self.twList.resizeColumnsToContents()
        self.twList.setVisible(True)
        if self.twList.columnWidth(0) > 200:
            self.twList.setColumnWidth(0, 200)

        self.twList.setSortingEnabled(True)
        if errors:
            OptionalMessageDialog.warning(
                self, "Read Failed!", "One or more of the read tags failed to load, check log for details"
            )

    def modify_settings(self) -> None:
        self.settingswin = SettingsWindow(self, self.config, self.talkers, rename_example=self.rename_example)
        self.settingswin.setModal(True)
        self.settingswin.show_rename_tab()
        self.settingswin.accepted.connect(self.settings_closed)
        self.settingswin.show()

    def settings_closed(self) -> None:
        self.config = self.settingswin.config
        self.tag_names_changed |= self.settingswin.tag_names_changed
        self.do_preview()

    def accept(self) -> None:
        if not self.rename_plans:
            return
        prog_dialog = QtWidgets.QProgressDialog("", "Cancel", 0, len(self.rename_plans), self)
        prog_dialog.setWindowTitle("Renaming Archives")
        prog_dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        prog_dialog.setMinimumDuration(100)
        center_window_on_parent(prog_dialog)
        QtCore.QCoreApplication.processEvents()

        failed_renames: list[tuple[str, str, OSError]] = []
        for idx, plan in enumerate(self.rename_plans, 1):
            if prog_dialog.wasCanceled():
                break
            prog_dialog.setValue(idx)
            prog_dialog.setLabelText(plan.name)
            if idx % 5 == 0:
                QtCore.QCoreApplication.processEvents()

            archive = plan.archive
            if plan.target == archive.path:
                logger.info("%s: Filename is already good!", plan.name)
                continue
            if not archive.is_writable(check_archive_status=False):
                continue

            target = plan.target
            try:
                target = plan.available_target()
                plan.apply(target)
            except OSError as e:
                logger.exception("Failed to rename comic archive: %s", archive.path)
                failed_renames.append((str(archive.path), str(target), e))

        if failed_renames:
            OptionalMessageDialog.critical(
                self,
                f"Failed to rename {len(failed_renames)} files!",
                "Renaming failed for {} files!\n\n{}\n\n".format(
                    len(failed_renames),
                    "\n".join([f"- {x[0]!r} -> {x[1]!r}: {x[2]}" for x in failed_renames]),
                ),
            )

        prog_dialog.close()
        QtCore.QCoreApplication.processEvents()

        QtWidgets.QDialog.accept(self)
