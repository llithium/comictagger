"""The editor's header, save bar and carded Details form, in the same style as the Auto-Tag review."""

from __future__ import annotations

import dataclasses
import platform

from PyQt6 import QtCore, QtGui, QtWidgets

from comictaggerlib.workspacestyle import ElidedLabel, chip


@dataclasses.dataclass
class FormCard:
    frame: QtWidgets.QFrame
    count: QtWidgets.QLabel
    fields: list[QtWidgets.QWidget]


def is_filled(widget: QtWidgets.QWidget) -> bool:
    if isinstance(widget, QtWidgets.QLineEdit):
        return bool(widget.text().strip())
    if isinstance(widget, QtWidgets.QComboBox):
        return bool(widget.currentText().strip())
    if isinstance(widget, QtWidgets.QCheckBox):
        return widget.isChecked()
    return False


class FormCards(QtCore.QObject):
    """Splits the Details grid into one card per section, with a fill count on each.

    The .ui file lays the Details tab out as one grid, with a heading label at the start of each
    section. This moves each section's rows into its own card and keeps every widget, so all of the
    window's existing references to the fields keep working.
    """

    changed = QtCore.pyqtSignal()

    def __init__(
        self,
        grid: QtWidgets.QGridLayout,
        headings: list[QtWidgets.QLabel],
        labels: dict[QtWidgets.QWidget, QtWidgets.QLabel],
        scroll: QtWidgets.QScrollArea | None = None,
    ) -> None:
        super().__init__(grid)
        self.scroll = scroll
        self.grid = grid
        self.labels = labels
        self.hide_empty = False
        self.cards: list[FormCard] = []
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self.refresh)
        self._build(headings)
        contents = grid.parentWidget()
        if scroll is not None and contents is not None:
            contents.installEventFilter(self)
            self.fit_width()

    def eventFilter(self, watched: QtCore.QObject | None, event: QtCore.QEvent | None) -> bool:
        if event is not None and event.type() in (
            QtCore.QEvent.Type.LayoutRequest,
            QtCore.QEvent.Type.StyleChange,
            QtCore.QEvent.Type.FontChange,
        ):
            self.fit_width()
        return False

    def fit_width(self) -> None:
        """Keep the cards from scrolling sideways; the cover column gives up width instead."""
        contents = self.grid.parentWidget()
        if self.scroll is None or contents is None:
            return
        scroll = self.scroll
        needed = contents.minimumSizeHint().width() + scroll.verticalScrollBar().sizeHint().width()
        needed += 2 * scroll.frameWidth()
        if scroll.minimumWidth() != needed:
            scroll.setMinimumWidth(needed)

    def _build(self, headings: list[QtWidgets.QLabel]) -> None:
        grid = self.grid
        cells = []
        while grid.count():
            position = grid.getItemPosition(grid.count() - 1)
            item = grid.takeAt(grid.count() - 1)
            if item is not None:
                cells.append((position, item))
        starts = sorted((pos[0], item.widget()) for pos, item in cells if item.widget() in headings)
        parent = grid.parentWidget()
        for index, (start, heading) in enumerate(starts):
            end = starts[index + 1][0] if index + 1 < len(starts) else 1 << 16
            frame = QtWidgets.QFrame(parent)
            frame.setObjectName("formCard")
            outer = QtWidgets.QVBoxLayout(frame)
            outer.setContentsMargins(16, 12, 16, 14)
            outer.setSpacing(8)
            top = QtWidgets.QHBoxLayout()
            top.addWidget(heading, 1)
            count = QtWidgets.QLabel()
            count.setObjectName("cardCount")
            top.addWidget(count)
            outer.addLayout(top)
            body = QtWidgets.QGridLayout()
            body.setHorizontalSpacing(12)
            body.setVerticalSpacing(4)
            for column in range(6):
                body.setColumnStretch(column, 1)
            fields: list[QtWidgets.QWidget] = []
            for (row, col, rows, cols), item in sorted(cells, key=lambda cell: cell[0]):
                if not start < row < end:
                    continue
                widget = item.widget()
                if widget is not None:
                    body.addWidget(widget, row - start - 1, col, rows, cols)
                    if widget not in self.labels.values() and not isinstance(widget, QtWidgets.QLabel):
                        fields.append(widget)
                        self._watch(widget)
                elif item.layout() is not None:
                    body.addLayout(item.layout(), row - start - 1, col, rows, cols)
            outer.addLayout(body)
            grid.addWidget(frame, index, 0)
            self.cards.append(FormCard(frame, count, fields))
        grid.setColumnStretch(0, 1)
        for column in range(1, 6):
            grid.setColumnStretch(column, 0)
        grid.setRowStretch(len(starts), 1)
        grid.setVerticalSpacing(12)

    def _watch(self, widget: QtWidgets.QWidget) -> None:
        if isinstance(widget, QtWidgets.QLineEdit):
            widget.textChanged.connect(self._refresh_timer.start)
        elif isinstance(widget, QtWidgets.QComboBox):
            widget.currentTextChanged.connect(self._refresh_timer.start)
        elif isinstance(widget, QtWidgets.QCheckBox):
            widget.toggled.connect(self._refresh_timer.start)

    def _counted(self, widget: QtWidgets.QWidget) -> bool:
        # Checkboxes always hold a value, and fields the write tags can't store don't count.
        return widget.isEnabled() and not isinstance(widget, QtWidgets.QCheckBox)

    def totals(self) -> tuple[int, int]:
        fields = [field for card in self.cards for field in card.fields if self._counted(field)]
        return sum(is_filled(field) for field in fields), len(fields)

    def set_hide_empty(self, hide: bool) -> None:
        self.hide_empty = hide
        self.apply_visibility()

    def apply_visibility(self) -> None:
        """Show or hide blank fields. Runs on a toggle or a new archive, never while typing."""
        for card in self.cards:
            shown = 0
            for field in card.fields:
                visible = not self.hide_empty or (field.isEnabled() and is_filled(field))
                if isinstance(field, QtWidgets.QCheckBox) and field.isEnabled():
                    visible = not self.hide_empty or field.isChecked()
                field.setVisible(visible)
                label = self.labels.get(field)
                if label is not None:
                    label.setVisible(visible)
                shown += visible
            card.frame.setVisible(shown > 0 or not self.hide_empty)
        self.refresh()

    def refresh(self) -> None:
        for card in self.cards:
            counted = [field for field in card.fields if self._counted(field)]
            filled = sum(is_filled(field) for field in counted)
            card.count.setText(f"{filled} of {len(counted)} filled" if counted else "")
        self.changed.emit()


def shortcut_text(sequence: QtGui.QKeySequence) -> str:
    text = sequence.toString(QtGui.QKeySequence.SequenceFormat.NativeText)
    return text.replace("Ctrl+", "⌘") if platform.system() == "Darwin" and "⌘" not in text else text


class EditorHeader(QtWidgets.QWidget):
    """The comic's name above the tabs, with the Details tools and chips for read-only files and tag formats."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("editorHeader")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 8)
        layout.setSpacing(2)
        self.title = ElidedLabel()
        self.title.setObjectName("editorTitle")
        layout.addWidget(self.title)
        # The second line holds the subtitle on the left, and the Details tools and chips on the right.
        self.row = QtWidgets.QHBoxLayout()
        self.row.setSpacing(8)
        self.subtitle = ElidedLabel()
        self.subtitle.setObjectName("editorSubtitle")
        self.row.addWidget(self.subtitle, 1)
        self.readOnlyChip = chip("Read-only", "bad")
        self.formatChip = chip("", "muted")
        for widget in (self.readOnlyChip, self.formatChip):
            self.row.addWidget(widget)
            widget.hide()
        layout.addLayout(self.row)

    def add_tools(self, widgets: list[QtWidgets.QWidget]) -> None:
        for position, widget in enumerate(widgets, start=1):
            self.row.insertWidget(position, widget)

    def show_comic(self, title: str, subtitle: str, read_only: bool, tag_names: str) -> None:
        self.title.set_full_text(title)
        self.subtitle.set_full_text(subtitle)
        self.readOnlyChip.setVisible(read_only)
        self.formatChip.setText(tag_names)
        self.formatChip.setVisible(bool(tag_names))


class SaveBar(QtWidgets.QWidget):
    """Unsaved-changes status with Revert and Save tags, under the form."""

    def __init__(self, save_action: QtGui.QAction, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("saveBar")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground)
        self.save_action = save_action
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        self.status = chip("Unsaved changes", "acc")
        self.hint = ElidedLabel()
        self.hint.setObjectName("saveHint")
        self.btnRevert = QtWidgets.QPushButton("Revert")
        self.btnRevert.setToolTip("Discard your edits and reload the tags from the file")
        self.btnSave = QtWidgets.QPushButton()
        self.btnSave.setProperty("primary", True)
        self.btnSave.clicked.connect(save_action.trigger)
        layout.addWidget(self.status)
        layout.addWidget(self.hint, 1)
        layout.addWidget(self.btnRevert)
        layout.addWidget(self.btnSave)
        save_action.changed.connect(self._sync_save)
        self._sync_save()
        self.set_state(False, "")

    def _sync_save(self) -> None:
        action = self.save_action
        keys = shortcut_text(action.shortcut())
        self.btnSave.setText(f"{action.text()}   {keys}" if keys else action.text())
        self.btnSave.setEnabled(action.isEnabled())
        self.btnSave.setToolTip(action.toolTip() if action.toolTip() != action.text() else "")

    def set_state(self, unsaved: bool, hint: str) -> None:
        self.status.setVisible(unsaved)
        self.hint.set_full_text(hint)
        self.btnRevert.setEnabled(unsaved)
