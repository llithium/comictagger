"""Custom widgets"""

from __future__ import annotations

import io
from enum import auto
from sys import platform
from typing import Any, cast

from PIL import Image
from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import QEvent, QModelIndex, QPoint, QRect, QSize, Qt, pyqtSignal

from comicapi.utils import StrEnum
from comictaggerlib.graphics import graphics_path


class ClickedButtonEnum(StrEnum):
    up = auto()
    down = auto()
    main = auto()


class ModifyStyleItemDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__()
        self.combobox = parent

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QModelIndex) -> None:
        options = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(options, index)
        style = self.combobox.style()

        # Draw background with the same color as other widgets
        palette = self.combobox.palette()
        background_color = palette.color(QtGui.QPalette.ColorRole.Window)
        painter.fillRect(options.rect, background_color)

        style.drawPrimitive(QtWidgets.QStyle.PrimitiveElement.PE_PanelItemViewItem, options, painter, self.combobox)

        painter.save()

        # Checkbox drawing logic
        checked = index.data(Qt.ItemDataRole.CheckStateRole)
        opts = QtWidgets.QStyleOptionButton()
        opts.state |= QtWidgets.QStyle.StateFlag.State_Active
        opts.rect = self.getCheckBoxRect(options)
        opts.state |= QtWidgets.QStyle.StateFlag.State_ReadOnly
        if checked:
            opts.state |= QtWidgets.QStyle.StateFlag.State_On
            style.drawPrimitive(
                QtWidgets.QStyle.PrimitiveElement.PE_IndicatorMenuCheckMark, opts, painter, self.combobox
            )
        else:
            opts.state |= QtWidgets.QStyle.StateFlag.State_Off
        if platform != "darwin":
            style.drawControl(QtWidgets.QStyle.ControlElement.CE_CheckBox, opts, painter, self.combobox)

        label = index.data(Qt.ItemDataRole.DisplayRole)
        rectangle = options.rect
        rectangle.setX(opts.rect.width() + 10)
        # We need the restore here so that text is colored properly
        painter.restore()
        painter.drawText(rectangle, Qt.AlignmentFlag.AlignVCenter, label)

    def getCheckBoxRect(self, option: QtWidgets.QStyleOptionViewItem) -> QRect:
        # Get size of a standard checkbox.
        opts = QtWidgets.QStyleOptionButton()
        style = option.widget.style()
        checkBoxRect = style.subElementRect(QtWidgets.QStyle.SubElement.SE_CheckBoxIndicator, opts, None)
        y = option.rect.y()
        h = option.rect.height()
        checkBoxTopLeftCorner = QPoint(5, int(y + h / 2 - checkBoxRect.height() / 2))

        return QRect(checkBoxTopLeftCorner, checkBoxRect.size())

    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QModelIndex) -> QSize:
        # Reimplement the stock size hint. Only height is used, width is ignored.
        menu_option = QtWidgets.QStyleOptionMenuItem()
        size = self.combobox.style().sizeFromContents(
            QtWidgets.QStyle.ContentsType.CT_MenuItem, menu_option, option.rect.size(), self.combobox
        )
        return size


class _CheckableComboBoxBase(QtWidgets.QComboBox):
    """Shared checked-item behavior for the plain and ordered variants."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.view().viewport().installEventFilter(self)
        self.justShown = False

    def paintEvent(self, event: QEvent) -> None:
        painter = QtWidgets.QStylePainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.ColorRole.Text))

        option = QtWidgets.QStyleOptionComboBox()
        self.initStyleOption(option)
        painter.drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_ComboBox, option)

        if self.currentIndex() < 0:
            option.palette.setBrush(
                QtGui.QPalette.ColorRole.ButtonText,
                option.palette.brush(QtGui.QPalette.ColorRole.ButtonText).color(),
            )
            if self.placeholderText():
                option.currentText = self.placeholderText()

        painter.drawControl(QtWidgets.QStyle.ControlElement.CE_ComboBoxLabel, option)

    def resizeEvent(self, event: QEvent) -> None:
        super().resizeEvent(event)
        self._updateText()

    def eventFilter(self, obj: Any, event: Any) -> bool:
        if obj != self.view().viewport():
            return False

        if event.type() == QEvent.Type.Show:
            self.justShown = True
        elif event.type() == QEvent.Type.Hide:
            self._updateText()
            self.justShown = False
            self._dropdown_closed()
        elif event.type() == QEvent.Type.KeyPress:
            key_event = cast(QtGui.QKeyEvent, event)
            if key_event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.toggleItem(self.view().currentIndex().row())
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if self.justShown:
                self.justShown = False
                return True

            index = self.view().indexAt(event.pos())
            if index.isValid():
                self._handle_item_click(index, event.pos())
                return True

        return False

    def currentData(self) -> list[Any]:
        return [
            self.itemData(i) for i in range(self.count()) if self.model().item(i).checkState() == Qt.CheckState.Checked
        ]

    def addItem(self, text: str, data: Any = None) -> None:
        super().addItem(text, data)
        if self.count() == 1:
            self.model().item(0).setCheckState(Qt.CheckState.Checked)
        self._item_added(text)

    def _updateText(self) -> None:
        text = ", ".join(
            self.model().item(i).text()
            for i in range(self.count())
            if self.model().item(i).checkState() == Qt.CheckState.Checked
        )
        option = QtWidgets.QStyleOptionComboBox()
        option.initFrom(self)
        rect = self.style().subControlRect(
            QtWidgets.QStyle.ComplexControl.CC_ComboBox,
            option,
            QtWidgets.QStyle.SubControl.SC_ComboBoxEditField,
        )
        self.setCurrentIndex(-1)
        self.setPlaceholderText(self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width()))

    def setItemChecked(self, index: Any, state: bool) -> None:
        item = self.model().item(index)
        current = self.currentData()
        if len(current) == 1 and not state and item.checkState() == Qt.CheckState.Checked:
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), self.toolTip(), self, QRect(), 3000)
            return

        if current:
            item.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
            self._checked_item_changed(index, state)
            self._updateText()

    def toggleItem(self, index: int) -> None:
        if 0 <= index < self.count():
            self.setItemChecked(index, self.model().item(index).checkState() != Qt.CheckState.Checked)

    def _handle_item_click(self, index: QModelIndex, pos: QPoint) -> None:
        self.toggleItem(index.row())

    def _dropdown_closed(self) -> None:
        return

    def _item_added(self, text: str) -> None:
        return

    def _checked_item_changed(self, index: int, state: bool) -> None:
        return


# Multiselect combobox from: https://gis.stackexchange.com/a/351152 (with custom changes)
class CheckableComboBox(_CheckableComboBoxBase):
    itemChecked = pyqtSignal(str, bool)

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.setItemDelegate(ModifyStyleItemDelegate(self))

    def _checked_item_changed(self, index: int, state: bool) -> None:
        self.itemChecked.emit(self.itemData(index), state)


# Inspiration from https://github.com/marcel-goldschen-ohm/ModelViewPyQt and https://github.com/zxt50330/qitemdelegate-example
class ReadStyleItemDelegate(QtWidgets.QStyledItemDelegate):
    buttonClicked = pyqtSignal(QModelIndex, ClickedButtonEnum)

    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__()
        self.combobox = parent

        self.down_icon = QtGui.QImage(":/graphics/down.png")
        self.up_icon = QtGui.QImage(":/graphics/up.png")
        self.gray_down_icon = QtGui.QImage()
        self.gray_up_icon = QtGui.QImage()

        buffer = io.BytesIO()
        Image.open(io.BytesIO((graphics_path / "up.png").read_bytes())).convert("LA").save(buffer, format="png")
        self.gray_up_icon.loadFromData(buffer.getvalue())
        buffer = io.BytesIO()
        Image.open(io.BytesIO((graphics_path / "down.png").read_bytes())).convert("LA").save(buffer, format="png")
        self.gray_down_icon.loadFromData(buffer.getvalue())

        self.button_width = self.down_icon.width()
        self.button_padding = 5

        # Tooltip messages
        self.item_help: str = ""
        self.up_help: str = ""
        self.down_help: str = ""

        # Connect the signal to a slot in the delegate
        self.combobox.itemClicked.connect(self.itemClicked)

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QModelIndex) -> None:
        options = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(options, index)
        style = self.combobox.style()

        # Draw background with the same color as other widgets
        palette = self.combobox.palette()
        background_color = palette.color(QtGui.QPalette.ColorRole.Window)
        painter.fillRect(options.rect, background_color)

        style.drawPrimitive(QtWidgets.QStyle.PrimitiveElement.PE_PanelItemViewItem, options, painter, self.combobox)

        painter.save()

        # Checkbox drawing logic
        checked = index.data(Qt.ItemDataRole.CheckStateRole)
        opts = QtWidgets.QStyleOptionButton()
        opts.state |= QtWidgets.QStyle.StateFlag.State_Active
        opts.rect = self.getCheckBoxRect(options)
        opts.state |= QtWidgets.QStyle.StateFlag.State_ReadOnly
        if checked:
            opts.state |= QtWidgets.QStyle.StateFlag.State_On
            style.drawPrimitive(
                QtWidgets.QStyle.PrimitiveElement.PE_IndicatorMenuCheckMark, opts, painter, self.combobox
            )
        else:
            opts.state |= QtWidgets.QStyle.StateFlag.State_Off
        if platform != "darwin":
            style.drawControl(QtWidgets.QStyle.ControlElement.CE_CheckBox, opts, painter, self.combobox)

        label = index.data(Qt.ItemDataRole.DisplayRole)
        rectangle = options.rect
        rectangle.setX(opts.rect.width() + 10)
        # We need the restore here so that text is colored properly
        painter.restore()
        painter.drawText(rectangle, Qt.AlignmentFlag.AlignVCenter, label)

        # Draw buttons
        if checked and (options.state & QtWidgets.QStyle.StateFlag.State_Selected):
            up_icon = self.up_icon
            down_icon = self.down_icon
            if index.row() == 0:
                up_icon = self.gray_up_icon
            if index.row() >= index.model().rowCount() - 1:
                down_icon = self.gray_down_icon

            up_rect = self._button_up_rect(options.rect)
            down_rect = self._button_down_rect(options.rect)
            painter.drawImage(up_rect, up_icon)
            painter.drawImage(down_rect, down_icon)

    def _button_up_rect(self, rect: QRect) -> QRect:
        return QRect(
            self.combobox.view().width() - (self.button_width * 2) - (self.button_padding * 2),
            rect.top() + (rect.height() - self.button_width) // 2,
            self.button_width,
            self.button_width,
        )

    def _button_down_rect(self, rect: QRect = QRect(10, 1, 12, 12)) -> QRect:
        return QRect(
            self.combobox.view().width() - self.button_padding - self.button_width,
            rect.top() + (rect.height() - self.button_width) // 2,
            self.button_width,
            self.button_width,
        )

    def getCheckBoxRect(self, option: QtWidgets.QStyleOptionViewItem) -> QRect:
        # Get size of a standard checkbox.
        opts = QtWidgets.QStyleOptionButton()
        style = option.widget.style()
        checkBoxRect = style.subElementRect(QtWidgets.QStyle.SubElement.SE_CheckBoxIndicator, opts, None)
        y = option.rect.y()
        h = option.rect.height()
        checkBoxTopLeftCorner = QPoint(5, int(y + h / 2 - checkBoxRect.height() / 2))

        return QRect(checkBoxTopLeftCorner, checkBoxRect.size())

    def itemClicked(self, index: QModelIndex, pos: QPoint) -> None:
        item_rect = self.combobox.view().visualRect(index)
        checked = index.data(Qt.ItemDataRole.CheckStateRole)
        button_up_rect = self._button_up_rect(item_rect)
        button_down_rect = self._button_down_rect(item_rect)

        if checked and button_up_rect.contains(pos):
            self.buttonClicked.emit(index, ClickedButtonEnum.up)
        elif checked and button_down_rect.contains(pos):
            self.buttonClicked.emit(index, ClickedButtonEnum.down)
        else:
            self.buttonClicked.emit(index, ClickedButtonEnum.main)

    def setToolTip(self, item: str = "", up: str = "", down: str = "") -> None:
        if item:
            self.item_help = item
        if up:
            self.up_help = up
        if down:
            self.down_help = down

    def helpEvent(
        self,
        event: QtGui.QHelpEvent,
        view: QtWidgets.QAbstractItemView,
        option: QtWidgets.QStyleOptionViewItem,
        index: QModelIndex,
    ) -> bool:
        item_rect = view.visualRect(index)
        button_up_rect = self._button_up_rect(item_rect)
        button_down_rect = self._button_down_rect(item_rect)
        checked = index.data(Qt.ItemDataRole.CheckStateRole)

        if checked == Qt.CheckState.Checked and button_up_rect.contains(event.pos()):
            QtWidgets.QToolTip.showText(event.globalPos(), self.up_help, self.combobox, QRect(), 3000)
        elif checked == Qt.CheckState.Checked and button_down_rect.contains(event.pos()):
            QtWidgets.QToolTip.showText(event.globalPos(), self.down_help, self.combobox, QRect(), 3000)
        else:
            QtWidgets.QToolTip.showText(event.globalPos(), self.item_help, self.combobox, QRect(), 3000)
        return True

    def sizeHint(self, option: QtWidgets.QStyleOptionViewItem, index: QModelIndex) -> QSize:
        # Reimplement the standard combobox size hint. Only height is used by the view, width is ignored.
        menu_option = QtWidgets.QStyleOptionMenuItem()
        return self.combobox.style().sizeFromContents(
            QtWidgets.QStyle.ContentsType.CT_MenuItem, menu_option, option.rect.size(), self.combobox
        )


# Multiselect combobox from: https://gis.stackexchange.com/a/351152 (with custom changes)
class CheckableOrderComboBox(_CheckableComboBoxBase):
    itemClicked = pyqtSignal(QModelIndex, QPoint)
    dropdownClosed = pyqtSignal(list)

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        itemDelegate = ReadStyleItemDelegate(self)
        itemDelegate.setToolTip(
            "Select which read tag(s) to use", "Move item up in priority", "Move item down in priority"
        )
        self.setItemDelegate(itemDelegate)

        # Go on a bit of a merry-go-round with the signals to avoid custom model/view
        self.itemDelegate().buttonClicked.connect(self.buttonClicked)

    def buttonClicked(self, index: QModelIndex, button: ClickedButtonEnum) -> None:
        if button == ClickedButtonEnum.up:
            self.moveItem(index.row(), index.row() - 1)
        elif button == ClickedButtonEnum.down:
            self.moveItem(index.row(), index.row() + 1)
        else:
            self.toggleItem(index.row())

    def _handle_item_click(self, index: QModelIndex, pos: QPoint) -> None:
        self.itemClicked.emit(index, pos)

    def _dropdown_closed(self) -> None:
        self.dropdownClosed.emit(self.currentData())

    def _item_added(self, text: str) -> None:
        # Add room for "move" arrows
        text_width = self.fontMetrics().boundingRect(text).width()
        checkbox_width = 40
        total_width = text_width + checkbox_width + (self.itemDelegate().button_width * 2)
        if total_width > self.view().minimumWidth():
            self.view().setMinimumWidth(total_width)

    def moveItem(self, index: int, row: int) -> None:
        """'Move' an item. Really swap the data and titles around on the two items"""

        model = cast(QtGui.QStandardItemModel, self.model())
        if row == index or row < 0 or row >= model.rowCount():
            return
        cur = model.item(index)
        new = model.item(row)
        cur_clone = cur.clone()
        new_clone = new.clone()

        model.setItem(cur.row(), cur.column(), new_clone)
        model.setItem(new.row(), new.column(), cur_clone)
