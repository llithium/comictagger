from __future__ import annotations

import pytest

from comicapi.genericmetadata import Credit

QtCore = pytest.importorskip("PyQt6.QtCore")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


def credit_rows(workspace):
    table = workspace.twCredits
    return [
        (
            table.item(row, workspace.md_attributes["credits.person"]).text(),
            table.item(row, workspace.md_attributes["credits.role"]).text(),
            table.item(row, workspace.md_attributes["credits.primary"]).text() == "Yes",
            table.item(row, workspace.md_attributes["credits.language"]).data(QtCore.Qt.ItemDataRole.UserRole),
        )
        for row in range(table.rowCount())
    ]


@pytest.fixture
def credits_workspace(workspace, monkeypatch):
    monkeypatch.setattr(workspace, "dirty_flag_verification", lambda *args: True)
    workspace.show_editor()
    workspace.tabWidget.setCurrentIndex(1)
    workspace.add_new_credit_entry(0, Credit("Alice", "Writer", True, "en"))
    workspace.add_new_credit_entry(1, Credit("Bob", "Writer", False, "de"))
    workspace.twCredits.setSortingEnabled(True)
    workspace.twCredits.sortItems(workspace.md_attributes["credits.person"], QtCore.Qt.SortOrder.AscendingOrder)
    return workspace


def test_sorted_credit_edit_keeps_each_rows_fields_together(credits_workspace):
    window = credits_workspace
    window._credit_changed(Credit("Zoe", "Writer", False, "fr"), 0)

    assert credit_rows(window) == [("Bob", "Writer", False, "de"), ("Zoe", "Writer", False, "fr")]


def test_sorted_credit_insert_keeps_each_rows_fields_together(credits_workspace):
    window = credits_workspace
    window._credit_added(Credit("Aaron", "Writer", True, "fr"))

    assert credit_rows(window) == [
        ("Aaron", "Writer", True, "fr"),
        ("Alice", "Writer", False, "en"),
        ("Bob", "Writer", False, "de"),
    ]


@pytest.mark.parametrize("editing", [True, False], ids=["edit", "add"])
@pytest.mark.parametrize("button_text", ["Merge", "Duplicate", "Cancel"])
def test_duplicate_credit_handles_each_dialog_choice(credits_workspace, qtbot, button_text, editing):
    window = credits_workspace
    credit = Credit("Bob", "Writer", True, "fr")
    if editing:
        window._credit_changed(credit, 0)
    else:
        window._credit_added(credit)
    dialog = next(box for box in window.findChildren(QtWidgets.QMessageBox) if box.isVisible())
    if button_text == "Cancel":
        qtbot.keyClick(dialog, QtCore.Qt.Key.Key_Escape)
    else:
        button = next(button for button in dialog.buttons() if button.text() == button_text)
        qtbot.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)

    original = [("Alice", "Writer", True, "en"), ("Bob", "Writer", False, "de")]
    if button_text == "Cancel":
        expected = original
    else:
        expected = [("Bob", "Writer", True, "fr")]
        if button_text == "Duplicate":
            expected.append(original[1])
        if not editing:
            expected.append(("Alice", "Writer", False, "en"))
    assert sorted(credit_rows(window)) == sorted(expected)
    assert window.dirty_flag == (button_text != "Cancel")
