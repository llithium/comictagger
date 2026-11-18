from __future__ import annotations

import dataclasses

from PyQt6 import QtCore, QtWidgets

from comicapi.genericmetadata import GenericMetadata


def display_value(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, set):
        return ", ".join(sorted(map(str, value))) or "—"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "—"
    return str(value)


class DraftReview(QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        filename: str,
        original: GenericMetadata,
        merged: GenericMetadata,
        writable: bool,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review draft changes")
        layout = QtWidgets.QVBoxLayout(self)
        target = QtWidgets.QLabel()
        target.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        target.setText(filename)
        target.setWordWrap(True)
        layout.addWidget(target)
        fields = [
            field.name
            for field in dataclasses.fields(original)
            if field.name != "is_empty" and getattr(original, field.name) != getattr(merged, field.name)
        ]
        table = QtWidgets.QTableWidget(len(fields), 3)
        table.setAccessibleName("Draft changes")
        table.setHorizontalHeaderLabels(["Field", "Current value", "With draft"])
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        header = table.horizontalHeader()
        header.setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        for row, field in enumerate(fields):
            for column, value in enumerate(
                (
                    field.replace("_", " ").capitalize(),
                    display_value(getattr(original, field)),
                    display_value(getattr(merged, field)),
                )
            ):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(value)
                table.setItem(row, column, item)
        layout.addWidget(table)
        table.setVisible(bool(fields))
        if not writable:
            layout.addWidget(QtWidgets.QLabel("This archive is read-only. Cancel to choose a writable archive."))
        elif fields:
            layout.addWidget(QtWidgets.QLabel("Apply the changes to the editor, then use Save tags to write them."))
        else:
            layout.addWidget(QtWidgets.QLabel("The draft has no changes to apply."))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.addButton("Apply draft", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setEnabled(writable and bool(fields))
        discard = buttons.addButton("Discard draft and open", QtWidgets.QDialogButtonBox.ButtonRole.DestructiveRole)
        discard.clicked.connect(lambda: self.done(QtWidgets.QMessageBox.StandardButton.Discard.value))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        default = (
            self.apply_button
            if self.apply_button.isEnabled()
            else buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        )
        default.setDefault(True)
        default.setFocus()
        layout.addWidget(buttons)
        if fields:
            table.setMinimumHeight(header.sizeHint().height() + table.rowHeight(0) + 2 * table.frameWidth())
        self.resize(
            660,
            self.minimumSizeHint().height()
            + min(7, max(0, len(fields) - 1)) * table.verticalHeader().defaultSectionSize(),
        )
