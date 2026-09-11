"""Focused interaction tests for the checkable tag selectors."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt

from comictaggerlib.ui.customwidgets import CheckableComboBox, CheckableOrderComboBox


def open_at_item(combo, qtbot, row: int):
    combo.showPopup()
    qtbot.wait(20)
    combo.justShown = False
    index = combo.model().index(row, 0)
    combo.view().setCurrentIndex(index)
    return combo.view().visualRect(index).center()


def test_checkable_combo_supports_mouse_and_keyboard_selection(qtbot):
    combo = CheckableComboBox()
    combo.addItem("ComicRack", "cr")
    combo.addItem("ComicBookLover", "cbl")
    combo.setFixedWidth(400)
    qtbot.addWidget(combo)
    combo.show()

    item_position = open_at_item(combo, qtbot, 1)
    with qtbot.waitSignal(combo.itemChecked, timeout=1000) as signal:
        qtbot.mouseClick(combo.view().viewport(), Qt.MouseButton.LeftButton, pos=item_position)
    assert signal.args == ["cbl", True]
    assert combo.currentData() == ["cr", "cbl"]
    assert "ComicBookLover" in combo.placeholderText()

    open_at_item(combo, qtbot, 0)
    with qtbot.waitSignal(combo.itemChecked, timeout=1000) as signal:
        qtbot.keyClick(combo.view().viewport(), Qt.Key.Key_Space)
    assert signal.args == ["cr", False]
    assert combo.currentData() == ["cbl"]


def test_ordered_checkable_combo_preserves_order_and_close_signal(qtbot):
    combo = CheckableOrderComboBox()
    combo.addItem("ComicRack", "cr")
    combo.addItem("ComicBookLover", "cbl")
    combo.addItem("ComicInfo", "cbi")
    qtbot.addWidget(combo)
    combo.setItemChecked(1, True)
    combo.setItemChecked(2, True)
    combo.moveItem(2, 0)

    assert combo.currentData() == ["cbi", "cbl", "cr"]

    open_at_item(combo, qtbot, 1)
    with qtbot.waitSignal(combo.dropdownClosed, timeout=1000) as signal:
        combo.hidePopup()
    assert signal.args == [["cbi", "cbl", "cr"]]
